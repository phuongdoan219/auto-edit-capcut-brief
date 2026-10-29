"""Render explicitly approximate local typography previews; never alter native media."""
import hashlib,json
from pathlib import Path


def create_preview(entry,state_dir):
    if entry.get('category')!='text_style' or not entry.get('available'):return None
    texts=entry.get('materials',{}).get('texts',[])
    if len(texts)!=1:return None
    t=texts[0]
    try: content=json.loads(t.get('content','{}'))
    except (TypeError,ValueError):return None
    styles=content.get('styles',[])
    if len(styles)>1:return None
    font_path=t.get('font_path') or (styles[0].get('font',{}).get('path') if styles else '')
    font_file=Path(font_path or '')
    if not font_file.is_file():return None
    try:
        from PIL import Image,ImageDraw,ImageFont
    except ImportError:return None
    signature={'font':str(font_file),'font_size':font_file.stat().st_size,'font_modified':font_file.stat().st_mtime_ns,
               'color':t.get('text_color'),'background':t.get('background_color'),'background_style':t.get('background_style'),
               'border_color':t.get('border_color'),'border_width':t.get('border_width'),'version':1}
    key=hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest()[:24]
    dest=Path(state_dir)/'previews'/('text-'+key+'.png')
    if not dest.exists():
        try:
            color=t.get('text_color') or '#ffffff'
            if not isinstance(color,str) or len(color)!=7 or not color.startswith('#'):color='#ffffff'
            background=t.get('background_color') if t.get('background_style') else None
            if not isinstance(background,str) or len(background)!=7 or not background.startswith('#'):background=None
            rgb=tuple(int(color[i:i+2],16) for i in (1,3,5))
            canvas='#242a28' if sum(rgb)>420 else '#f0f2ef'
            image=Image.new('RGB',(640,240),canvas);draw=ImageDraw.Draw(image)
            label='MẪU CHỮ TIẾNG VIỆT'
            size=52
            while size>18:
                font=ImageFont.truetype(str(font_file),size)
                bounds=draw.textbbox((0,0),label,font=font,stroke_width=0)
                if bounds[2]-bounds[0]<=560:break
                size-=2
            width=bounds[2]-bounds[0];height=bounds[3]-bounds[1]
            x=(640-width)//2-bounds[0];y=(240-height)//2-bounds[1]
            if background:draw.rounded_rectangle((max(20,x+bounds[0]-18),max(20,y+bounds[1]-12),min(620,x+bounds[2]+18),min(220,y+bounds[3]+12)),radius=8,fill=background)
            border=t.get('border_color') or None
            stroke=2 if border and t.get('border_width') else 0
            draw.text((x,y),label,font=font,fill=color,stroke_width=stroke,stroke_fill=border if stroke else None)
            dest.parent.mkdir(parents=True,exist_ok=True)
            image.save(dest,format='PNG')
        except (OSError,ValueError,TypeError):return None
    entry['preview_kind']='approximate_text'
    return str(dest.resolve())
