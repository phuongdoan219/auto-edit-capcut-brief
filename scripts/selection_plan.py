"""Apply confirmed human choices to a resolved media plan, preserving supplied sources."""
import argparse
import copy
import json
from pathlib import Path
import selection_session as S


def split_text_slot(request,plan,slot_id,groups):
    """Split reviewed semantic groups using explicit plan segment indexes.

    No first-line heuristic: parallel bullets are not automatically a headline.
    Every old text segment must belong to exactly one new group.
    """
    from selection_request import TEXT_GROUP_LABELS
    result=copy.deepcopy(request);edited=copy.deepcopy(plan)
    frame=next((f for f in result['frames'] if any(s['id']==slot_id for s in f['slots'])),None)
    if frame is None:raise ValueError('Unknown text slot: '+slot_id)
    old=next(s for s in frame['slots'] if s['id']==slot_id)
    if old['role']!='text':raise ValueError('Only text slots can have text groups')
    expected={i for i,s in enumerate(edited['segments']) if s.get('slot_id')==slot_id}
    if not expected or any(edited['segments'][i]['kind']!='text' for i in expected):
        raise ValueError('Split requires resolved text placements')
    occupied={s['id'] for f in result['frames'] for s in f['slots']}
    used=set();new=[]
    for group in groups:
        sid=group.get('id');hierarchy=group.get('text_group');indexes=group.get('segment_indices')
        if not isinstance(sid,str) or not sid or sid in occupied or hierarchy not in TEXT_GROUP_LABELS:
            raise ValueError('Each text group needs a unique id and main/support hierarchy')
        if not isinstance(indexes,list) or not indexes or any(type(i) is not int for i in indexes):
            raise ValueError('Each group needs explicit segment indexes')
        for i in indexes:
            if i not in expected or i in used:raise ValueError('Groups must partition the original text placements exactly once')
            used.add(i);edited['segments'][i]['slot_id']=sid
        item=copy.deepcopy(old)
        item.update(id=sid,text_group=hierarchy,label=TEXT_GROUP_LABELS[hierarchy],
                    text='\n'.join(edited['segments'][i]['text'] for i in indexes))
        new.append(item);occupied.add(sid)
    if len(new)<2 or used!=expected:raise ValueError('Groups must cover every old text placement')
    pos=frame['slots'].index(old);frame['slots'][pos:pos+1]=new
    return result,edited


def with_optional_sticker_placements(plan,request):
    """Prepare editable defaults on known scene ranges, without choosing assets.

    Agents may supply a scene-specific placement instead. Native scale and safe
    areas still require checking in CapCut after the user has picked the sticker.
    """
    result=copy.deepcopy(plan)
    known={s.get('slot_id') for s in result['segments']}
    for index,frame in enumerate(request['frames'],1):
        wanted=[s for s in frame['slots'] if s.get('opt_in') and s['id'] not in known]
        if not wanted:continue
        ids={str(frame['id']),str(frame.get('frame',index))}
        visuals=[s for s in result['segments'] if s['kind'] in ('video','photo') and str(s.get('frame')) in ids]
        intervals=[]
        for start,end in sorted((s['start'],s['start']+s['duration']) for s in visuals):
            if intervals and start<=intervals[-1][1]+1e-6:intervals[-1][1]=max(intervals[-1][1],end)
            else:intervals.append([start,end])
        for slot in wanted:
            for start,end in intervals:
                result['segments'].append({'kind':'sticker','frame':visuals[0]['frame'],'slot_id':slot['id'],
                    'start':start,'duration':end-start,'layer':max(s.get('layer',0) for s in visuals)+4,
                    'transform':{'scale':{'x':.3,'y':.3},'transform':{'x':.65,'y':-.65}}})
    return result


def assemble_plan(plan,request,library,session,request_hash=None,library_hash=None):
    errors=S.validate_confirmed_session(request,library,session,request_hash=request_hash,library_hash=library_hash)
    if errors:raise ValueError('Selection is not confirmed/current: '+str(errors))
    slots={slot['id']:slot for frame in request['frames'] for slot in frame.get('slots',[])}
    entries={e['key']:e for e in library['entries']}
    seen=set();result=copy.deepcopy(plan);segments=[]
    for segment in result['segments']:
        kind=segment['kind'];sid=segment.get('slot_id')
        if sid:
            if sid not in slots:raise ValueError('Unknown plan slot: '+sid)
            slot=slots[sid];choice=session['choices'].get(sid)
            if choice is None:
                if slot.get('opt_in'):continue
                raise ValueError('Slot has no explicit human decision: '+sid)
            seen.add(sid)
            if choice.get('skip'):
                if slot.get('required',True):raise ValueError('Required slot cannot be skipped')
                continue
            if slot['role']=='text':
                if kind!='text':raise ValueError('Text slot attached to non-text segment')
                if slot['categories']==['text_effect']:
                    # The human selected this complete effect donor, including
                    # its existing font. Remove inherited motion before reapplying
                    # only its appearance; no separate style decision is invented.
                    segment['asset']=choice['effect'];segment['custom_text']=True
                    segment['effect_asset']=choice['effect'];segment['animation_assets']={}
                elif choice.get('template'):
                    segment['asset']=choice['template'];segment['custom_text']=False
                    segment.pop('effect_asset',None);segment.pop('animation_assets',None)
                else:
                    segment['asset']=choice['style'];segment['custom_text']=True
                    segment['effect_asset']=choice.get('effect')
                    segment['animation_assets']=copy.deepcopy(choice.get('animations') or {})
            elif slot['role'] in ('sticker','icon'):
                if kind!='sticker':raise ValueError('Sticker slot attached to wrong segment')
                segment['asset']=choice['asset']
            elif slot['role']=='video_effect':
                if kind!='video_effect':raise ValueError('Effect slot attached to wrong segment')
                segment['asset']=choice['asset']
            else:raise ValueError('Unsupported slot role: '+str(slot['role']))
            if segment['asset'] not in entries:raise ValueError('Selected asset disappeared')
        elif kind in ('text','sticker','video_effect'):
            raise ValueError('Decorative segment lacks a human selection slot')
        segments.append(segment)
    for sid,slot in slots.items():
        choice=session['choices'].get(sid,{})
        if slot.get('opt_in') and not choice:
            continue
        if sid not in seen and not choice.get('skip'):
            raise ValueError('Selected slot has no placement in the edit plan: '+sid)
    result['segments']=segments
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('plan','request','library','session','out'):ap.add_argument('--'+name,required=True)
    a=ap.parse_args()
    def load(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    result=assemble_plan(load(a.plan),load(a.request),load(a.library),load(a.session),S.file_hash(a.request),S.file_hash(a.library))
    out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'out':str(out),'segments':len(result['segments']),'human_choices_applied':True}))


if __name__=='__main__':main()
