"""Compile an explicit footage plan using native CapCut donors; install only with guards."""
import argparse
import copy
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
import native_assets as N
import native_composition as NC


def uid():
    return str(uuid.uuid4()).upper()


def probe_media(path):
    p = Path(path)
    if not p.is_file():
        raise ValueError('Missing media: ' + str(p))
    if p.suffix.lower() in ('.crdownload', '.part', '.tmp'):
        raise ValueError('Incomplete download: ' + str(p))
    proc = subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(p)], capture_output=True, text=True)
    if proc.returncode:
        raise ValueError('Cannot probe media: ' + str(p))
    info = json.loads(proc.stdout)
    vs = next((s for s in info['streams'] if s.get('codec_type') == 'video'), {})
    duration = float(info.get('format', {}).get('duration', 0))
    kind = 'photo' if p.suffix.lower() in ('.png','.jpg','.jpeg','.webp','.bmp') else ('video' if vs else 'audio')
    return {'duration': duration, 'width': vs.get('width',0), 'height': vs.get('height',0),
            'has_audio': any(s.get('codec_type')=='audio' for s in info['streams']), 'kind': kind}


def rewrite(obj, mapping):
    if isinstance(obj, str):
        if obj in mapping: return mapping[obj]
        if obj.lstrip().startswith(('{', '[')):
            try: return json.dumps(rewrite(json.loads(obj), mapping), ensure_ascii=False, separators=(',',':'))
            except ValueError: pass
        return obj
    if isinstance(obj, list): return [rewrite(x, mapping) for x in obj]
    if isinstance(obj, dict): return {k:rewrite(v,mapping) for k,v in obj.items()}
    return obj


def clone_bundle(segment, materials):
    mapping = {segment['id']: uid()}
    for rows in materials.values():
        for m in rows: mapping[m['id']] = uid()
    # Animation IDs may themselves be UUIDs owned by CapCut's resource catalog.
    # Re-ID only known local graph objects, never arbitrary nested `id` fields.
    for kf in segment.get('common_keyframes',[]):
        if kf.get('id'):mapping.setdefault(kf['id'],uid())
        for pt in kf.get('keyframe_list',[]):
            if pt.get('id'):mapping.setdefault(pt['id'],uid())
    for mat in materials.get('text_templates',[]):
        for slot in mat.get('text_info_resources',[]):
            if slot.get('id'):mapping.setdefault(slot['id'],uid())
    return rewrite(copy.deepcopy(segment),mapping), rewrite(copy.deepcopy(materials),mapping)


def text_replace(mat, text, ranges=None):
    content = json.loads(mat.get('content','{}'))
    styles = content.get('styles',[])
    n = len(text.encode('utf-16-le')) // 2
    if len(styles) > 1 and ranges is None:
        raise ValueError('Rich text has multiple styles: provide style_ranges or select a uniform-style donor')
    if ranges is not None:
        if len(ranges)!=len(styles) or any(not isinstance(r,list) or len(r)!=2 or not 0<=r[0]<=r[1]<=n for r in ranges):
            raise ValueError('style_ranges must match styles and use valid UTF-16 boundaries')
    content['text'] = text
    for i,sty in enumerate(styles): sty['range'] = ranges[i] if ranges is not None else [0,n]
    mat['content'] = json.dumps(content,ensure_ascii=False,separators=(',',':'))
    mat['words'] = {'start_time':[], 'end_time':[], 'text':[]}
    mat['current_words'] = {'start_time':[], 'end_time':[], 'text':[]}
    for k in ('recognize_text','translate_original_text','base_content'):
        if k in mat: mat[k] = ''


def clean_media_bundle(base, kind):
    wanted = 'audios' if kind=='audio' else 'videos'
    idx = N.material_index(base)
    candidates=[]
    for track in base['tracks']:
        for seg in track['segments']:
            group,mat = idx.get(seg.get('material_id'),('',{}))
            if group == wanted and (kind=='audio' or mat.get('type') == kind):
                candidates.append((seg,mat))
    if not candidates:
        raise ValueError('Base project needs a clean imported '+kind+' segment on its timeline')
    source,mat = candidates[0]
    if source.get('keyframe_refs'):
        raise ValueError('Base media donor uses external keyframes; create a clean donor')
    mats={wanted:[copy.deepcopy(mat)]}
    safe=('speeds','sound_channel_mappings','vocal_separations','placeholder_infos','material_colors')
    refs=[]
    for ref in source.get('extra_material_refs',[]):
        group,m = idx.get(ref,('',{}))
        if group in safe:
            mats.setdefault(group,[]).append(copy.deepcopy(m));refs.append(ref)
    seg=copy.deepcopy(source);seg['extra_material_refs']=refs
    seg['common_keyframes']=[];seg['keyframe_refs']=[];seg['group_id']=''
    seg['reverse']=False;seg['is_loop']=False
    seg['enable_adjust']=False;seg['enable_lut']=False;seg['enable_hsl']=False
    for key in ('enable_color_curves','enable_hsl_curves','enable_color_wheels','enable_video_mask','enable_color_adjust_pro'):
        seg[key]=False
    seg, mats = clone_bundle(seg,mats)
    return seg,mats


def reset_source_metadata(mat):
    # Clear saved processing results that refer to the donor's old source.
    for key in ('media_path','local_material_id','unique_id','reverse_path','intensifies_path','reverse_intensifies_path','intensifies_audio_path','cartoon_path'):
        if key in mat:mat[key]=''
    for key in ('video_algorithm','matting','stable','beauty_face_auto_preset','video_mask_stroke','video_mask_shadow'):
        if key in mat:
            def zero(v):
                if isinstance(v,dict):return {k:zero(x) for k,x in v.items()}
                if isinstance(v,list):return []
                if isinstance(v,bool):return False
                if isinstance(v,(int,float)):return 0
                if isinstance(v,str):return ''
                return None
            mat[key]=zero(mat[key])
    for key in ('freeze','smart_motion','multi_camera_info','corner_pin'):
        if key in mat:mat[key]=None


def set_box(seg,mat,box,canvas):
    x,y,w,h = map(float,box)
    if min(x,y)<0 or min(w,h)<=0 or x+w>1.000001 or y+h>1.000001:
        raise ValueError('box must be [left,top,width,height] within normalized canvas')
    cw,ch=canvas; sw,sh=mat['width'],mat['height']
    if not sw or not sh:raise ValueError('Visual dimensions missing')
    ratio=(cw*w)/(ch*h); sr=sw/sh
    cropw=min(1,ratio/sr);croph=min(1,sr/ratio)
    lx=(1-cropw)/2;ty=(1-croph)/2
    mat['crop']={'upper_left_x':lx,'upper_left_y':ty,'upper_right_x':1-lx,'upper_right_y':ty,
                 'lower_left_x':lx,'lower_left_y':1-ty,'lower_right_x':1-lx,'lower_right_y':1-ty}
    mat['crop_ratio']='free';mat['crop_scale']=1.0
    fit=min(cw/sw,ch/sh)
    scale=(cw*w)/(sw*cropw*fit)
    seg['clip']={'scale':{'x':scale,'y':scale},'rotation':0.0,
                 'transform':{'x':2*(x+w/2)-1,'y':1-2*(y+h/2)},
                 'flip':{'horizontal':False,'vertical':False},'alpha':1.0}
    seg['uniform_scale']={'on':True,'value':1.0}


def retime(seg,mats,duration,fps):
    old=seg.get('target_timerange',{}).get('duration',duration) or duration
    maxoff=max(0,duration-round(1e6/fps))
    for kf in seg.get('common_keyframes',[]):
        kf['id']=uid()
        for key in kf.get('keyframe_list',[]):
            key['id']=uid();key['time_offset']=min(maxoff,round(key.get('time_offset',0)*duration/old))
    for mat in mats.get('material_animations',[]):
        for anim in mat.get('animations',[]):
            if 'start' in anim:anim['start']=min(maxoff,max(0,anim['start']))
            if 'duration' in anim:anim['duration']=min(duration-anim.get('start',0),anim['duration'])
    for mat in mats.get('text_templates',[]):
        for slot in mat.get('text_info_resources',[]):
            info=slot.get('attach_info',{})
            if 'start_time' in info:info['start_time']=round(info['start_time']*duration/old)
            if 'duration' in info:info['duration']=min(duration-info.get('start_time',0),round(info['duration']*duration/old))


def compile_plan(plan,base,catalog,probe=probe_media):
    allowed={'canvas','fps','duration','segments','title','brief_source'}
    if set(plan)-allowed:raise ValueError('Unsupported plan fields: '+str(sorted(set(plan)-allowed)))
    fps=float(plan.get('fps',base.get('fps',30)))
    if not 0<fps<=240:raise ValueError('Invalid fps')
    def us(v):
        v=float(v)
        if not math.isfinite(v):raise ValueError('Non-finite time')
        return round(round(v*fps)/fps*1e6)
    duration=us(plan['duration'])
    if duration<=0:raise ValueError('Empty edit')
    canvas=plan.get('canvas',base['canvas_config']);cw=int(canvas['width']);ch=int(canvas['height'])
    if min(cw,ch)<=0:raise ValueError('Invalid canvas')
    out=copy.deepcopy(base)
    out['materials']={k:[] if isinstance(v,list) else copy.deepcopy(v) for k,v in base['materials'].items()}
    out['tracks']=[];out['duration']=duration;out['fps']=fps
    out['canvas_config']={**base.get('canvas_config',{}),'width':cw,'height':ch,'ratio': '9:16' if cw*16==ch*9 else ('16:9' if cw*9==ch*16 else 'original')}
    for key in ('group_container','relationships','keyframe_graph_list','time_marks'):
        if isinstance(out.get(key),list):out[key]=[]
        elif isinstance(out.get(key),dict):out[key]={}
    if 'keyframes' in out:out['keyframes']={k:[] for k in out['keyframes']}
    entries={e['key']:e for e in catalog.get('entries',[])}
    tracks={};segment_targets={};pending_effects=[];report={'schema':'capcut-build-report/1','capcut_open_verified':False,
                       'segments':[],'warnings':[],'resource_paths':[]}
    for i,item in enumerate(plan['segments']):
        allowed={'kind','file','start','duration','source_start','speed','role','volume','tone_modify','box','transform',
                 'flip_horizontal','keyframes','asset','text','text_slots','style_ranges','layer','frame',
                 'slot_id','segment_id','target_segment','custom_text','effect_asset','animation_assets'}
        if set(item)-allowed:raise ValueError('Unsupported segment fields: '+str(sorted(set(item)-allowed)))
        kind=item['kind'];start=us(item['start']);dur=us(item['duration'])
        if start<0 or dur<=0 or start+dur>duration+1:
            raise ValueError('Segment outside edit: '+str(i))
        if kind=='video_effect':
            chosen=NC.video_effect(catalog,item.get('asset'))
            if chosen['application']=='clip':
                if not item.get('target_segment'):raise ValueError('Clip effect requires target_segment')
                pending_effects.append((item,chosen,start,dur))
                report['resource_paths']+=chosen.get('resource_paths',[])
                report['segments'].append({'index':i,'frame':item.get('frame'),'kind':kind,'asset':item.get('asset'),
                                           'start':start/1e6,'duration':dur/1e6,'target_segment':item['target_segment']})
                report['warnings'].append('Clip effect '+chosen['key']+' requires CapCut render verification')
                continue
            if not chosen.get('segment') or not chosen.get('materials'):raise ValueError('Effect has no observed track segment bundle')
            seg,mats=clone_bundle(chosen['segment'],chosen['materials'])
            retime(seg,mats,dur,fps);track_type=chosen.get('track_type','effect')
            if track_type!='effect':raise ValueError('Unsupported native effect track type')
            report['resource_paths']+=chosen.get('resource_paths',[])
            report['warnings'].append('Track effect '+chosen['key']+' requires CapCut render verification')
        elif kind in ('video','photo','audio'):
            path=str(Path(item['file']).resolve());info=probe(path)
            if kind=='audio' and not info.get('has_audio'):raise ValueError('Voice source contains no audio')
            if kind in ('video','photo') and info.get('kind')!=kind:raise ValueError('Media kind does not match plan')
            seg,mats=clean_media_bundle(base,kind)
            primary=mats['audios' if kind=='audio' else 'videos'][0]
            reset_source_metadata(primary)
            src=us(item.get('source_start',0));speed=float(item.get('speed',1))
            if src<0 or not math.isfinite(speed) or speed<=0:raise ValueError('Invalid source range/speed')
            srcdur=round(dur*speed)
            if kind!='photo' and src+srcdur>round(info['duration']*1e6)+round(1e6/fps):
                raise ValueError('Source interval exceeds media duration: '+path)
            primary.update({'path':path.replace('\\','/'),'duration':round(info['duration']*1e6) if kind!='photo' else dur,
                            'name':Path(path).name,'material_name':Path(path).name})
            if kind!='audio':
                primary.update({'width':info['width'],'height':info['height'],'has_audio':info['has_audio']})
                set_box(seg,primary,item.get('box',[0,0,1,1]),(cw,ch))
                if item.get('flip_horizontal'):seg['clip']['flip']['horizontal']=True
            seg['speed']=speed;seg['source_timerange']={'start':src,'duration':srcdur}
            for m in mats.get('speeds',[]):m['speed']=speed;m['curve_speed']=None
            seg['volume']=float(item.get('volume',0 if kind!='audio' else 1))
            if seg['volume']<0 or not math.isfinite(seg['volume']):raise ValueError('Invalid linear volume')
            seg['last_nonzero_volume']=seg['volume'] or 1
            seg['is_tone_modify']=bool(item.get('tone_modify',False))
            if item.get('transform'):
                for k,v in item['transform'].items():
                    if k not in ('scale','rotation','transform','flip','alpha'):raise ValueError('Unknown transform')
                    seg['clip'][k]=v
            if item.get('keyframes'):
                seg['common_keyframes']=copy.deepcopy(item['keyframes'])
                for kf in seg['common_keyframes']:
                    kf['id']=uid()
                    for key in kf.get('keyframe_list',[]):
                        key['id']=uid()
                        if not 0<=key['time_offset']<dur:raise ValueError('Keyframe outside clip')
            track_type='audio' if kind=='audio' else 'video'
            report['resource_paths'].append(path)
        elif kind in ('text','sticker'):
            if item.get('asset') not in entries:raise ValueError('Unknown native asset: '+str(item.get('asset')))
            entry=entries[item['asset']]
            if entry['kind']!=kind:raise ValueError('Native asset kind mismatch')
            if not entry.get('supported',True):raise ValueError('Native donor uses unsupported external keyframes')
            missing=[p for p in entry.get('resource_paths',[]) if not N.path_ready(p)]
            if missing:raise ValueError('Missing native resource: '+str(missing))
            seg,mats=clone_bundle(entry['segment'],entry['materials'])
            retime(seg,mats,dur,fps)
            if kind=='text':
                if item.get('custom_text') or item.get('effect_asset') or item.get('animation_assets'):
                    paths,parts=NC.compose_text(seg,mats,item,catalog,dur)
                    report['resource_paths']+=paths
                    for part in parts:
                        if not part.get('capcut_verified'):report['warnings'].append('Composed native part '+part['key']+' needs CapCut render verification')
                textmats=mats.get('texts',[])
                if not textmats:raise ValueError('Native text asset has no resolved editable text materials')
                if 'text' in item:
                    if len(textmats)!=1:raise ValueError('Multi-slot template needs text_slots mapping by slot index')
                    text_replace(textmats[0],item['text'],item.get('style_ranges'))
                elif isinstance(item.get('text_slots'),list):
                    by_slot={old['id']:new for old,new in zip(entry['materials']['texts'],textmats)}
                    slots=[tx.get('slot') for tx in item['text_slots']]
                    if len(slots)!=len(set(slots)) or set(slots)!=set(by_slot):raise ValueError('text_slots must map every original text material ID exactly once')
                    for tx in item['text_slots']:text_replace(by_slot[tx['slot']],tx['text'],tx.get('style_ranges'))
                else:raise ValueError('Text needs explicit replacement content')
            if item.get('transform'):
                for k,v in item['transform'].items():
                    if k not in ('scale','rotation','transform','flip','alpha'):raise ValueError('Unknown transform')
                    seg['clip'][k]=v
            track_type=entry['track_type']
            report['resource_paths']+=entry.get('resource_paths',[])
            if not entry.get('capcut_verified'):
                report['warnings'].append('Native asset '+entry['key']+' needs CapCut open/render verification')
        else:raise ValueError('Unsupported segment kind: '+kind)
        seg['target_timerange']={'start':start,'duration':dur}
        seg['group_id']='';seg['track_render_index']=int(item.get('layer',0))
        seg['render_index']=int(item.get('layer',0)) if track_type=='video' else (11000 if track_type=='effect' else 14000)+int(item.get('layer',0))
        seg['visible']=True
        if item.get('segment_id'):
            if item['segment_id'] in segment_targets:raise ValueError('Duplicate plan segment_id')
            segment_targets[item['segment_id']]=(seg,track_type)
        # One segment per track avoids hidden overlap on a single track. Layer order is explicit.
        tr={'id':uid(),'type':track_type,'flag':0,'attribute':0,'name':item.get('role',f'{kind}-{i+1}'),
            'is_default_name':False,'segments':[seg]}
        tracks[(int(item.get('layer',0)),i)]=tr
        for group,rows in mats.items():out['materials'].setdefault(group,[]).extend(rows)
        report['segments'].append({'index':i,'frame':item.get('frame'),'kind':kind,'asset':item.get('asset'),
                                   'start':start/1e6,'duration':dur/1e6,'source':item.get('file'),
                                   'source_start':item.get('source_start'),'role':item.get('role')})
    for item,chosen,start,dur in pending_effects:
        if item['target_segment'] not in segment_targets:raise ValueError('Video effect target segment not found')
        target,typ=segment_targets[item['target_segment']]
        if typ!='video':raise ValueError('Clip video effect target is not a video')
        tr=target['target_timerange'];offset=start-tr['start']
        if offset<0 or offset+dur>tr['duration']+1:raise ValueError('Clip effect extends outside its target clip')
        effect=chosen.get('effect_material')
        if not effect:raise ValueError('Clip effect missing native effect material')
        group=chosen.get('material_group','video_effects')
        pool=copy.deepcopy(chosen.get('materials',{}))
        if not pool:pool={group:[effect]}
        dependency=N.closure({'materials':pool},{'material_id':effect['id']})
        reference,mats=clone_bundle({'id':uid(),'material_id':effect['id']},dependency)
        cloned=next(m for rows in mats.values() for m in rows if m.get('id')==reference['material_id'])
        cloned['time_range']={'start':offset,'duration':dur}
        target.setdefault('extra_material_refs',[]).append(cloned['id'])
        for group,rows in mats.items():out['materials'].setdefault(group,[]).extend(rows)
    out['tracks']=[tracks[k] for k in sorted(tracks)]
    report['resource_paths']=sorted(set(report['resource_paths']))
    validate_draft(out)
    if any('box' in x for x in plan['segments']):report['warnings'].append('Verify crop/box geometry in CapCut on this app version')
    return out,report


def validate_draft(draft):
    idx=N.material_index(draft); ids=[]
    for tr in draft['tracks']:
        for seg in tr['segments']:
            ids.append(seg['id'])
            for ref in [seg['material_id'],*seg.get('extra_material_refs',[])]:
                if ref not in idx:raise ValueError('Unresolved material: '+ref)
            rg=seg['target_timerange']
            if rg['duration']<=0 or rg['start']<0 or rg['start']+rg['duration']>draft['duration']+1:raise ValueError('Invalid output range')
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate segment IDs')
    material_ids=[m['id'] for rows in draft['materials'].values() if isinstance(rows,list) for m in rows if isinstance(m,dict) and m.get('id')]
    if len(material_ids)!=len(set(material_ids)):raise ValueError('Duplicate material IDs')
    def refs(obj):
        if isinstance(obj,dict):
            for k,v in obj.items():
                if k=='extra_material_refs':
                    for ref in v:
                        if ref and ref not in idx:raise ValueError('Unresolved nested material: '+ref)
                if k=='text_material_id' and v and v not in idx:raise ValueError('Unresolved text slot: '+v)
                refs(v)
        elif isinstance(obj,list):
            for v in obj:refs(v)
    refs(draft['materials'])
    visuals=[s for tr in draft['tracks'] if tr['type']=='video' for s in tr['segments']]
    if visuals:
        layer=min(s['track_render_index'] for s in visuals)
        intervals=sorted((s['target_timerange']['start'],s['target_timerange']['start']+s['target_timerange']['duration']) for s in visuals if s['track_render_index']==layer)
        end=0
        for a,b in intervals:
            if a>end+1:raise ValueError('Gap in base visual layer')
            end=max(end,b)
        if end<draft['duration']-1:raise ValueError('Base visual ends before edit')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def project_file(folder):
    return next((Path(folder)/n for n in ('draft_info.json','draft_content.json') if (Path(folder)/n).is_file()),None)


def install_targets(project,name):
    project=Path(project);dirs=[project]
    timeline_meta=project/'Timelines'/'project.json'
    if timeline_meta.is_file():
        tid=json.loads(timeline_meta.read_text(encoding='utf-8-sig')).get('main_timeline_id')
        if not tid or not re.fullmatch(r'[A-Za-z0-9_-]+',str(tid)):
            raise ValueError('Cannot identify a safe main_timeline_id')
        timeline=project/'Timelines'/tid
        if not (timeline/name).is_file():raise ValueError('Main timeline file is missing; do not guess another timeline')
        dirs.append(timeline)
    elif (project/'Timelines').exists() and any((project/'Timelines').glob('*/'+name)):
        raise ValueError('Multiple timeline layout without main_timeline_id metadata; installation needs investigation')
    return [d/n for d in dirs for n in (name,name+'.bak','template-2.tmp') if (d/n).is_file()]


def build_files(plan_path,base_path,library_path,out_path):
    base_file=project_file(base_path)
    if not base_file:raise ValueError('Base project not found')
    base_dir=Path(base_path).resolve();out_dir=Path(out_path).resolve()
    if out_dir==base_dir or base_dir in out_dir.parents or out_dir in base_dir.parents:
        raise ValueError('Build output must be separate from the live project')
    base_hash=sha(base_file)
    target_hashes={str(p.relative_to(base_dir)):sha(p) for p in install_targets(base_dir,base_file.name)}
    draft,report=compile_plan(json.loads(Path(plan_path).read_text(encoding='utf-8-sig')),N.load_project(base_file),json.loads(Path(library_path).read_text(encoding='utf-8-sig')))
    if sha(base_file)!=base_hash or {str(p.relative_to(base_dir)):sha(p) for p in install_targets(base_dir,base_file.name)}!=target_hashes:
        raise ValueError('Base project changed during build; rebuild from the current saved draft')
    out_dir.mkdir(parents=True,exist_ok=True)
    dest=out_dir/base_file.name;dest.write_text(json.dumps(draft,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    report.update({'content_name':base_file.name,'base_project':str(base_dir),'base_sha256':base_hash,'built_sha256':sha(dest),
                   'target_sha256':target_hashes})
    (out_dir/'build_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (out_dir/'report.md').write_text('# Validation\n\nCompiled draft; CapCut open/render verification: pending.\n\n'+'\n'.join('- '+x for x in report['warnings']),encoding='utf-8')
    print(json.dumps({'out':str(out_dir),'segments':len(report['segments']),'capcut_open_verified':False,'warnings':len(report['warnings'])}))


def capcut_running():
    if os.name=='nt':
        r=subprocess.run(['tasklist','/FO','CSV','/NH'],capture_output=True,text=True,errors='replace')
        if r.returncode:raise ValueError('Cannot check running applications')
        return bool(re.search(r'(?i)"CapCut[^\"]*\.exe"',r.stdout))
    r=subprocess.run(['pgrep','-x','CapCut'],capture_output=True)
    return r.returncode==0


def install_build(build,project,confirmed_closed):
    if not confirmed_closed:raise ValueError('Confirm CapCut is closed before installation')
    if capcut_running():raise ValueError('CapCut is running; close it before installation')
    build=Path(build).resolve();project=Path(project).resolve()
    report=json.loads((build/'build_report.json').read_text(encoding='utf-8'))
    if project!=Path(report['base_project']).resolve():raise ValueError('Install target differs from the base project')
    main=project/report['content_name'];built=build/report['content_name']
    if sha(main)!=report['base_sha256']:raise ValueError('Project changed since build; rebuild before installing')
    if sha(built)!=report['built_sha256']:raise ValueError('Built draft changed since validation')
    data=N.load_project(built);validate_draft(data)
    missing=[p for p in report['resource_paths'] if not N.path_ready(p)]
    if missing:raise ValueError('Missing resources: '+str(missing))
    name=report['content_name'];targets=install_targets(project,name)
    current={str(p.relative_to(project)):sha(p) for p in targets}
    if current!=report.get('target_sha256'):raise ValueError('A timeline copy changed since build; rebuild before installing')
    backup=project/('_backup_before_custom_'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
    meta=project/'draft_meta_info.json'
    for p in [*targets,*([meta] if meta.exists() else [])]:
        dest=backup/p.relative_to(project);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
    # Recheck immediately before the first write; never quit the user's app automatically.
    if capcut_running() or sha(main)!=report['base_sha256']:raise ValueError('Project/app state changed; no timeline installed')
    try:
        for p in targets:
            tmp=p.with_name(p.name+'.custom-write.tmp');shutil.copyfile(built,tmp);os.replace(tmp,p)
        if meta.exists():
            m=json.loads(meta.read_text(encoding='utf-8-sig'));m['tm_duration']=data['duration'];m['tm_draft_modified']=int(time.time()*1e6)
            tmp=meta.with_name(meta.name+'.custom-write.tmp');tmp.write_text(json.dumps(m,ensure_ascii=False,separators=(',',':')),encoding='utf-8');os.replace(tmp,meta)
        if any(sha(p)!=report['built_sha256'] for p in targets):raise ValueError('Installed checksum mismatch')
    except Exception:
        for p in [*targets,*([meta] if meta.exists() else [])]:
            bk=backup/p.relative_to(project)
            if bk.exists():shutil.copy2(bk,p)
        raise
    return {'backup':str(backup),'written':len(targets),'capcut_open_verified':False}


def main():
    ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest='command',required=True)
    p=sub.add_parser('build');p.add_argument('--plan',required=True);p.add_argument('--base',required=True);p.add_argument('--library',required=True);p.add_argument('--out',required=True)
    p=sub.add_parser('install');p.add_argument('--build',required=True);p.add_argument('--project',required=True);p.add_argument('--confirmed-closed',action='store_true')
    a=ap.parse_args()
    if a.command=='build':build_files(a.plan,a.base,a.library,a.out)
    else:print(json.dumps(install_build(a.build,a.project,a.confirmed_closed)))


if __name__=='__main__':main()
