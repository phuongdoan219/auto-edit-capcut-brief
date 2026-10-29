"""Compose human-selected native parts. Does not choose assets or write live projects."""
import copy
import json
import uuid
import native_assets as N


def entry(catalog,key,category):
    e=next((e for e in catalog.get('entries',[]) if e.get('key')==key),None)
    if e is None or e.get('category')!=category:raise ValueError('Wrong native category: '+str(key))
    if not e.get('supported',True) or not e.get('available',True):raise ValueError('Unavailable native asset: '+str(key))
    missing=[p for p in e.get('resource_paths',[]) if not N.path_ready(p)]
    if missing:raise ValueError('Missing selected native resource: '+str(missing))
    return e


def _solid(color):
    c=(color or '#ffffff').lstrip('#')
    if len(c)!=6:c='ffffff'
    return {'content':{'render_type':'solid','solid':{'color':[int(c[i:i+2],16)/255 for i in (0,2,4)]}}}


def compose_text(segment,materials,item,catalog,duration):
    from capcut_native import clone_bundle,rewrite
    selected=[]
    if item.get('custom_text'):
        if materials.get('text_templates'):
            raise ValueError('Custom text baseline contains a template; select template mode instead')
        removed=set()
        for group in ('effects','video_effects','material_animations'):
            keep=[]
            for m in materials.get(group,[]):
                if group=='effects' and m.get('type')=='text_shape':keep.append(m)
                else:removed.add(m['id'])
            materials[group]=keep
        segment['extra_material_refs']=[r for r in segment.get('extra_material_refs',[]) if r not in removed]
        for t in materials.get('texts',[]):
            c=json.loads(t['content'])
            for style in c.get('styles',[]):
                style.pop('effectStyle',None)
                if style.get('fill',{}).get('content',{}).get('render_type')=='texture':style['fill']=_solid(t.get('text_color'))
            t['content']=json.dumps(c,ensure_ascii=False,separators=(',',':'))
    if item.get('effect_asset'):
        chosen=entry(catalog,item['effect_asset'],'text_effect');selected.append(chosen)
        recipe=chosen.get('effect_recipe')
        if not recipe:raise ValueError('Text effect has no native appearance recipe')
        effects=copy.deepcopy(recipe.get('effects',[]))
        if not effects:raise ValueError('Empty text effect recipe')
        old={m['id'] for m in materials.get('effects',[]) if m.get('type')=='text_effect'}
        materials['effects']=[m for m in materials.get('effects',[]) if m['id'] not in old]
        segment['extra_material_refs']=[r for r in segment.get('extra_material_refs',[]) if r not in old]
        pool=copy.deepcopy(chosen.get('materials',{}))
        pool.setdefault('effects',[])
        known={m.get('id') for m in pool['effects']}
        pool['effects'].extend(m for m in effects if m['id'] not in known)
        dependency=N.closure({'materials':pool},{'extra_material_refs':[m['id'] for m in effects]})
        refs,dependency=clone_bundle({'id':str(uuid.uuid4()),'extra_material_refs':[m['id'] for m in effects]},dependency)
        for group,rows in dependency.items():materials.setdefault(group,[]).extend(rows)
        segment.setdefault('extra_material_refs',[]).extend(refs['extra_material_refs'])
        overrides=recipe.get('style_overrides',[])
        if not overrides:raise ValueError('Text effect is missing content style anchors')
        for t in materials.get('texts',[]):
            c=json.loads(t['content']);styles=c.get('styles',[])
            if len(overrides)>1 and len(overrides)!=len(styles):raise ValueError('Effect/style slot count mismatch')
            for n,style in enumerate(styles):
                # Effect recipes change appearance, never the user's font/range/content.
                visual=overrides[n] if len(overrides)>1 else overrides[0]
                for key in ('effectStyle','fill','stroke','strokes','shadow','shadows','background'):
                    if key in visual:style[key]=copy.deepcopy(visual[key])
            # Keep the legacy editor color in sync with the effective single
            # style. Donors can retain green text_color beside a white effect
            # fill; neither the preview nor a later editor operation should
            # resurrect that unrelated color.
            if len(styles)==1:
                fill=styles[0].get('fill',{}).get('content',{})
                rgb=fill.get('solid',{}).get('color')
                if fill.get('render_type')=='solid' and isinstance(rgb,list) and len(rgb)>=3:
                    t['text_color']='#'+''.join(f'{round(max(0,min(1,float(v)))*255):02x}' for v in rgb[:3])
            t['content']=json.dumps(c,ensure_ascii=False,separators=(',',':'))
    animations=[]
    for anim_type,key in (item.get('animation_assets') or {}).items():
        if not key:continue
        if anim_type not in ('in','out','loop'):raise ValueError('Unsupported text animation slot')
        chosen=entry(catalog,key,'text_animation')
        if chosen.get('animation_type')!=anim_type:raise ValueError('Animation kind does not match chosen slot')
        a=copy.deepcopy(chosen['animation'])
        if a.get('type')!=anim_type:raise ValueError('Native animation type mismatch')
        length=min(duration,int(a.get('duration') or duration))
        if length<=0:raise ValueError('Invalid native animation duration')
        a['duration']=length;a['start']=duration-length if anim_type=='out' else 0
        animations.append(a);selected.append(chosen)
    if animations:
        lengths={a['type']:a['duration'] for a in animations}
        if lengths.get('in',0)+lengths.get('out',0)>duration:raise ValueError('In/out animations overlap in this text clip')
        old={m['id'] for m in materials.get('material_animations',[])}
        segment['extra_material_refs']=[r for r in segment.get('extra_material_refs',[]) if r not in old]
        container={'id':str(uuid.uuid4()).upper(),'type':'sticker_animation','animations':animations}
        materials['material_animations']=[container]
        segment.setdefault('extra_material_refs',[]).append(container['id'])
    paths=N.resource_paths(materials)
    missing=[p for p in paths if not N.path_ready(p)]
    if missing:raise ValueError('Composed text is missing resources: '+str(missing))
    return paths,selected


def video_effect(catalog,key):
    chosen=entry(catalog,key,'video_effect')
    if chosen.get('application') not in ('track','clip'):raise ValueError('Video effect application has no observed native schema')
    return chosen
