"""Draft frame selection slots from a brief; AI reviews semantic/layout requirements."""
import argparse,json,re,uuid
from pathlib import Path
import brief_io


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
                slots.append({'id':f'{fid}.text{n}','role':'text','label':'Chữ '+str(n),
                              'text':text,'requirement':notes,'required':True,
                              'categories':['text_style','text_effect','text_animation','text_template']})
            if re.search(r'(?i)\b(?:sticker|icon|biểu tượng|mũi tên)\b',notes):
                slots.append({'id':fid+'.sticker1','role':'sticker','label':'Sticker / icon',
                              'requirement':notes,'required':True,'categories':['sticker']})
            if f.get('video_effect') or re.search(r'(?i)(?:video effect|hiệu ứng video|hiệu ứng toàn (?:cảnh|khung))',notes):
                slots.append({'id':fid+'.effect1','role':'video_effect','label':'Hiệu ứng video',
                              'requirement':f.get('video_effect') or notes,'required':True,'categories':['video_effect']})
        frames.append({'id':fid,'dialogue':f.get('dialogue',''),'edit_notes':notes,'slots':slots})
    return {'schema':'capcut-selection-request/1','id':str(uuid.uuid4()),'title':brief.get('title','Chọn element CapCut'),
            'brief_source':brief.get('source_id'),'semantic_review_required':True,'frames':frames}


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--brief',required=True);ap.add_argument('--out',required=True)
    a=ap.parse_args();request=make_request(json.loads(Path(a.brief).read_text(encoding='utf-8-sig')))
    out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(request,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'out':str(out),'frames':len(request['frames']),'slots':sum(len(f['slots']) for f in request['frames']),'semantic_review_required':True}))


if __name__=='__main__':main()
