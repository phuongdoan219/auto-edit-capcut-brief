"""Draft frame selection slots from a brief; AI reviews semantic/layout requirements."""
import argparse,copy,json,re,uuid
from pathlib import Path
import brief_io


def effect_sticker_request(request):
    result=copy.deepcopy(request)
    result['selection_mode']='effects_stickers'
    used={s.get('id') for f in result.get('frames',[]) for s in f.get('slots',[])}
    for frame in result.get('frames',[]):
        slots=[]
        for slot in frame.get('slots',[]):
            if slot.get('role')=='text':
                slot['categories']=['text_effect'];slot['label']='Text Effect '+str(len(slots)+1)
            elif slot.get('role') in ('sticker','icon'):
                slot['categories']=['sticker'];slot['label']='Stickers'
            else:continue
            slots.append(slot)
        if not any(s.get('role') in ('sticker','icon') for s in slots):
            sid=str(frame['id'])+'.sticker.optional';index=1
            while sid in used:
                index+=1;sid=str(frame['id'])+'.sticker.optional'+str(index)
            used.add(sid)
            slots.append({'id':sid,'role':'sticker','label':'Stickers','required':False,
                          'opt_in':True,'categories':['sticker']})
        frame['slots']=slots
    return result


def make_request(raw):
    brief=brief_io.normalize(raw)
    frames=[]
    for f in brief['frames']:
        fid=str(f.get('id') or 'frame-'+str(f.get('frame',len(frames)+1)))
        notes=f.get('edit_notes') or f.get('description') or ''
        slots=[]
        if isinstance(f.get('selection_slots'),list):
            slots=f['selection_slots']
        else:
            explicit=f.get('on_screen_text') or f.get('text')
            blocks=[]
            if explicit:
                blocks=[str(x) for x in explicit] if isinstance(explicit,list) else [str(explicit)]
            else:
                pattern=r'(?im)^(?:-\s*)?(?:Text\b[^\n]*|Ở phần[^\n]*hiện text[^\n]*|[^\n]*nội dung text hiện[^\n]*)(?::|：)[ \t]*'
                markers=list(re.finditer(pattern,notes))
                for m in markers:
                    rest=notes[m.end():]
                    end=re.search(r'(?im)^\s*(?:-\s*(?:Text|Hình ảnh|Voice)\b|Ở phần)',rest)
                    blocks.append(rest[:end.start() if end else len(rest)].strip())
            for n,text in enumerate(blocks,1):
                slots.append({'id':f'{fid}.text{n}','role':'text','label':'Text Effect '+str(n),
                              'text':text,'requirement':notes,'required':True,
                              'categories':['text_effect']})
            if re.search(r'(?i)\b(?:stickers?|icons?|nhãn d[áã]n|biểu tượng|mũi tên)\b',notes):
                slots.append({'id':fid+'.sticker1','role':'sticker','label':'Sticker',
                              'requirement':notes,'required':True,'categories':['sticker']})
        frames.append({'id':fid,'frame':f.get('frame',len(frames)+1),'dialogue':f.get('dialogue',''),'edit_notes':notes,'slots':slots})
    return effect_sticker_request({'schema':'capcut-selection-request/1','id':str(uuid.uuid4()),'title':brief.get('title','Choose Text Effects & Stickers'),
            'brief_source':brief.get('source_id'),'semantic_review_required':True,'frames':frames})


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--brief',required=True);ap.add_argument('--out',required=True)
    a=ap.parse_args();request=make_request(json.loads(Path(a.brief).read_text(encoding='utf-8-sig')))
    out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(request,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'out':str(out),'frames':len(request['frames']),'slots':sum(len(f['slots']) for f in request['frames']),'semantic_review_required':True}))


if __name__=='__main__':main()
