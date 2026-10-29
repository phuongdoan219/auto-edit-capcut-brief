"""Approximate text appearance from the selected native recipe, never stale UI colors.

This is a Pillow interpretation of observed effectStyle data, not CapCut's renderer.
Unsupported paint modes use an explicitly reported neutral placement preview.
"""
import copy
import json
import math
from pathlib import Path


class UnsupportedPaint(ValueError):
    pass


def appearance(entry):
    material = entry['materials']['texts'][0]
    style = copy.deepcopy(json.loads(material['content'])['styles'][0])
    override = entry.get('effect_recipe', {}).get('style_overrides', [{}])[0]
    style.update(copy.deepcopy(override))
    root = None
    path = style.get('effectStyle', {}).get('path')
    if path and '://' not in path:
        candidate = Path(path)
        if candidate.is_absolute():
            root = candidate
    if material.get('use_effect_default_color') is not False and root:
        try:
            data = json.loads((root / 'effectStyle.json').read_text(encoding='utf-8-sig'))
            if isinstance(data, dict) and data.get('fill'):
                return data, root
        except (OSError, ValueError):
            pass
    # text_color/border_color belong to the donor editor state. They may be
    # bright green even when the selected effect's fill/defaults are white.
    # Do not use them to fill holes in an effect appearance recipe.
    return style, root


def rgb(values):
    if not isinstance(values, list) or len(values) < 3:
        raise UnsupportedPaint('Missing native paint color')
    return tuple(round(max(0, min(1, float(v))) * 255) for v in values[:3])


def paint(mask, spec, root):
    from PIL import Image, ImageChops, ImageOps
    content = spec.get('content') or {}
    mode = content.get('render_type')
    alpha = float(spec.get('alpha', 1))
    if mode == 'solid':
        data = content.get('solid') or {}
        layer = Image.new('RGBA', mask.size, rgb(data.get('color')) + (255,))
        alpha *= float(data.get('alpha', 1))
    elif mode == 'texture':
        data = content.get('texture') or {}
        if root is None or not isinstance(data.get('path'), str):
            raise UnsupportedPaint('Missing native texture')
        path = (root / data['path']).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise UnsupportedPaint('Missing native texture')
        layer = ImageOps.fit(Image.open(path).convert('RGBA'), mask.size)
        flips = data.get('flip') or [False, False]
        if flips[0]: layer = ImageOps.mirror(layer)
        if flips[1]: layer = ImageOps.flip(layer)
        alpha *= float(data.get('alpha', 1))
    elif mode == 'gradient':
        data = content.get('gradient') or {}
        colors = [rgb(v) for v in data.get('color', [])]
        if len(colors) < 2 or data.get('style', 'linear') != 'linear':
            raise UnsupportedPaint('Unsupported native gradient')
        stops = data.get('percent') or [i / (len(colors)-1) for i in range(len(colors))]
        if len(stops) != len(colors):
            raise UnsupportedPaint('Invalid native gradient stops')
        # The native engine can repeat gradients per glyph. This layout preview
        # interpolates the full text mask and is therefore still approximate.
        strip = Image.new('RGBA', (1, 256))
        for y in range(256):
            t = y / 255
            n = next((i for i in range(len(stops)-1) if t <= stops[i+1]), len(stops)-2)
            f = max(0, min(1, (t-stops[n]) / max(1e-9, stops[n+1]-stops[n])))
            strip.putpixel((0, y), tuple(round(a+(b-a)*f) for a,b in zip(colors[n],colors[n+1])) + (255,))
        layer = strip.resize(mask.size)
    else:
        raise UnsupportedPaint('Unsupported native paint mode')
    coverage = mask.point(lambda v: round(v * max(0, min(1, alpha))))
    layer.putalpha(ImageChops.multiply(layer.getchannel('A'), coverage))
    return layer


def render_text(entry, text, font, spacing):
    from PIL import Image, ImageDraw, ImageFilter
    style, root = appearance(entry)
    size = font.size
    pad = max(12, round(size * 1.5))
    box = ImageDraw.Draw(Image.new('L', (1, 1))).multiline_textbbox((0, 0), text, font=font, spacing=spacing)
    dimensions = (max(1, box[2]-box[0]+pad*2), max(1, box[3]-box[1]+pad*2))
    if dimensions[0] * dimensions[1] > 16000000:
        raise ValueError('Text preview dimensions are too large')
    origin = (pad-box[0], pad-box[1])

    def mask(stroke=0):
        result = Image.new('L', dimensions)
        ImageDraw.Draw(result).multiline_text(origin, text, font=font, fill=255,
                                             spacing=spacing, align='center', stroke_width=stroke)
        return result

    def stroke_masks(strokes):
        if isinstance(strokes,dict):strokes=[strokes]
        if not isinstance(strokes,list) or any(not isinstance(s,dict) for s in strokes):
            raise UnsupportedPaint('Unsupported native stroke structure')
        for spec in sorted((s for s in strokes if s.get('enable', True)), key=lambda s:s.get('width',0), reverse=True):
            yield mask(max(1, round(float(spec.get('width', 0))*size))), spec

    result = Image.new('RGBA', dimensions)
    try:
        shadows=style.get('shadows') or []
        if isinstance(shadows,dict):shadows=[shadows]
        if not isinstance(shadows,list) or any(not isinstance(s,dict) for s in shadows):
            raise UnsupportedPaint('Unsupported native shadow structure')
        for shadow in reversed(shadows):
            if not shadow.get('enable', True): continue
            shadow_layer = Image.new('RGBA', dimensions)
            for coverage, stroke in stroke_masks(shadow.get('strokes') or []):
                shadow_layer.alpha_composite(paint(coverage, stroke, root))
            shadow_layer.alpha_composite(paint(mask(), shadow, root))
            diffuse = max(0, min(size*2, size*float(shadow.get('diffuse', 0))))
            if diffuse: shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(diffuse))
            distance = size*float(shadow.get('distance', 0))/100
            angle = math.radians(float(shadow.get('angle', 0)))
            result.alpha_composite(shadow_layer, (round(math.cos(angle)*distance), round(math.sin(angle)*distance)))
        for coverage, stroke in stroke_masks(style.get('strokes') or style.get('stroke') or []):
            result.alpha_composite(paint(coverage, stroke, root))
        result.alpha_composite(paint(mask(), style.get('fill') or {}, root))
        return result, 'Native recipe approximation; exact appearance needs CapCut.'
    except (UnsupportedPaint, OSError, TypeError, ValueError):
        # Do not show donor colors as if they represented this chosen effect.
        result = Image.new('RGBA', dimensions)
        ImageDraw.Draw(result).multiline_text(origin, text, font=font, fill='#eeeeee',
            spacing=spacing, align='center', stroke_width=1, stroke_fill='#303030')
        return result, 'Native appearance unavailable. Neutral text shows placement only.'
