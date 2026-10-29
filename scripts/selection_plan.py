"""Apply confirmed human choices to a resolved media plan, preserving supplied sources."""
import argparse
import copy
import json
from pathlib import Path
import selection_session as S


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
            if choice is None:raise ValueError('Slot has no explicit human decision: '+sid)
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
