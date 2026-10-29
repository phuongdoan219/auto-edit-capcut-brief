"""Prepare rough-cut stills, then composite explicitly approximate layout previews.

FFmpeg runs only in the prepare command. HTTP preview rendering reads pinned
stills and native donor data; it never edits a project or confirms choices.
"""
import argparse
from io import BytesIO
import json
from pathlib import Path
import subprocess

from selection_session import file_hash, effect_baseline_ready


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def prepare(work, video, ffmpeg='ffmpeg', ffprobe='ffprobe'):
    from picker_server import atomic_json
    try:
        from PIL import Image
    except ImportError as error:
        raise ValueError('Install Pillow before preparing on-frame previews') from error
    work = Path(work).resolve()
    state = read(work / 'workflow.json')
    if not state.get('plan'):
        raise ValueError('Resolve the media/text placement plan before preparing scene previews')
    plan, request = read(state['plan']), read(state['request'])
    video = Path(video).resolve(strict=True)
    probe = subprocess.run([ffprobe, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(video)],
                           capture_output=True, check=True, timeout=30)
    info = json.loads(probe.stdout)
    duration = float(info['format']['duration'])
    stream = next(s for s in info['streams'] if s['codec_type'] == 'video')
    canvas = plan.get('canvas', {})
    width, height = int(canvas.get('width', stream['width'])), int(canvas.get('height', stream['height']))
    if (stream['width'], stream['height']) != (width, height):
        raise ValueError('Rough cut dimensions must match the final plan canvas')
    hashes = {'request_hash': file_hash(state['request']), 'plan_hash': file_hash(state['plan']),
              'roughcut_hash': file_hash(video)}
    stamp = '-'.join(hashes[k][:12] for k in ('request_hash', 'plan_hash', 'roughcut_hash'))
    out = work / 'scene-stills' / stamp
    out.mkdir(parents=True, exist_ok=True)
    scenes = []
    for index, frame in enumerate(request['frames'], 1):
        ids = {str(frame['id']), str(frame.get('frame', index))}
        visuals = [s for s in plan['segments'] if s['kind'] in ('video', 'photo') and str(s.get('frame')) in ids]
        if not visuals:
            raise ValueError('No resolved visual timing for scene ' + str(index))
        start = min(s['start'] for s in visuals)
        end = max(s['start'] + s['duration'] for s in visuals)
        if not (0 <= start < end <= duration + .1):
            raise ValueError('Scene timing falls outside the rough cut')
        slots = {s['id'] for s in frame['slots']}
        layers = [s for s in plan['segments'] if s.get('slot_id') in slots]
        missing = slots - {s['slot_id'] for s in layers}
        if missing:
            raise ValueError('Preview needs final placements for slots: ' + ', '.join(sorted(missing)))
        # Include changes in text visibility, so sequential bullet points can be
        # inspected without showing future text on an earlier video frame.
        boundaries = sorted({start, end, *[max(start, min(end, s['start'])) for s in layers],
                             *[max(start, min(end, s['start'] + s['duration'])) for s in layers]})
        times = sorted({round((a + b) / 2, 6) for a, b in zip(boundaries, boundaries[1:]) if b - a > .01}
                       | {round(start + (end - start) * f, 6) for f in (.05, .5, .95)})
        samples = []
        for n, moment in enumerate(times):
            dest = out / f'scene-{index:03d}-{n:03d}.jpg'
            subprocess.run([ffmpeg, '-v', 'error', '-y', '-ss', str(moment), '-i', str(video),
                            '-frames:v', '1', '-vf', 'scale=540:-2', '-q:v', '3', str(dest)],
                           capture_output=True, check=True, timeout=60)
            if not dest.is_file() or not dest.stat().st_size:
                raise ValueError('Could not extract rough-cut frame')
            samples.append({'time': moment, 'file': str(dest)})
        scenes.append({'id': frame['id'], 'start': start, 'end': end, 'samples': samples, 'layers': layers})
    manifest = {'schema': 'capcut-scene-preview/1', 'canvas': {'width': width, 'height': height},
                **hashes, 'roughcut': str(video),
                'appearance': 'approximate_layout', 'scenes': scenes}
    atomic_json(work / 'scene-preview.json', manifest)
    state.update(roughcut=str(video), scene_preview=str(work / 'scene-preview.json'),
                 edit_sequence='roughcut_then_choices_then_native')
    atomic_json(work / 'workflow.json', state)
    return {'status': 'scene_previews_ready', 'scenes': len(scenes), 'manifest': str(work / 'scene-preview.json')}


def load(work, request_hash):
    path = Path(work) / 'scene-preview.json'
    if not path.is_file():
        return None
    data = read(path)
    state = read(Path(work) / 'workflow.json')
    if data.get('schema') != 'capcut-scene-preview/1' or data.get('request_hash') != request_hash:
        raise ValueError('Scene previews belong to a different request; prepare them again')
    if not state.get('plan') or file_hash(state['plan']) != data.get('plan_hash'):
        raise ValueError('Layout plan changed; prepare scene previews again')
    if not Path(data['roughcut']).is_file() or file_hash(data['roughcut']) != data.get('roughcut_hash'):
        raise ValueError('Rough cut changed; prepare scene previews again')
    for scene in data['scenes']:
        if not scene.get('samples') or any(not Path(s['file']).is_file() for s in scene['samples']):
            raise ValueError('Scene stills are missing; prepare scene previews again')
    return data


def metadata(data):
    if not data:
        return None
    return {'appearance': data['appearance'], 'canvas': data['canvas'], 'scenes': [
        {'id': s['id'], 'start': s['start'], 'end': s['end'],
         'samples': [{'time': p['time']} for p in s['samples']],
         'slots': [{'id': layer['slot_id'], 'start': layer['start'], 'duration': layer['duration']}
                   for layer in s['layers']]} for s in data['scenes']]}


def color(value, fallback='#ffffff'):
    if isinstance(value, str) and len(value) in (4, 7) and value.startswith('#'):
        try:
            int(value[1:], 16)
            return value
        except ValueError:
            pass
    return fallback


def render(data, request, library, frame_id, sample_index, choices):
    from PIL import Image, ImageDraw, ImageFont
    if not data:
        raise ValueError('Prepare the rough cut and scene previews first')
    scene = next((s for s in data['scenes'] if s['id'] == frame_id), None)
    frame = next((f for f in request['frames'] if f['id'] == frame_id), None)
    if not scene or not frame or not 0 <= sample_index < len(scene['samples']):
        raise ValueError('Unknown scene or preview moment')
    if not isinstance(choices, dict):
        raise ValueError('Invalid preview choices')
    slots = {s['id']: s for s in frame['slots']}
    entries = {e['key']: e for e in library['entries']}
    for sid, choice in choices.items():
        if sid not in slots or not isinstance(choice, dict):
            raise ValueError('Preview choice belongs to another scene')
        if choice == {'skip': True} and not slots[sid]['required']:
            continue
        part = 'effect' if slots[sid]['role'] == 'text' else 'asset'
        key = choice.get(part)
        entry = entries.get(key)
        if set(choice) != {part} or not entry or entry['category'] != ('text_effect' if part == 'effect' else 'sticker'):
            raise ValueError('Invalid preview asset')
        if not entry.get('supported') or not entry.get('available') or (part == 'effect' and not effect_baseline_ready(entry)):
            raise ValueError('Preview asset is unavailable')
    sample = scene['samples'][sample_index]
    image = Image.open(sample['file']).convert('RGBA')
    w, h = image.size
    warnings = set()
    for layer in sorted(scene['layers'], key=lambda s: s.get('layer', 0)):
        if not layer['start'] <= sample['time'] < layer['start'] + layer['duration']:
            continue
        choice = choices.get(layer['slot_id'], {})
        entry = entries.get(choice.get('effect') or choice.get('asset'))
        if not entry:
            continue
        clip = dict(entry.get('segment', {}).get('clip') or {})
        clip.update(layer.get('transform') or {})
        position = clip.get('transform') or {}
        scale = clip.get('scale') or {'x': 1, 'y': 1}
        cx, cy = (1 + position.get('x', 0)) * w / 2, (1 - position.get('y', 0)) * h / 2
        overlay = None
        if layer['kind'] == 'text':
            material = entry['materials']['texts'][0]
            content = json.loads(material['content'])
            style = content.get('styles', [{}])[0]
            font_path = material.get('font_path') or style.get('font', {}).get('path')
            size = max(1, round(float(style.get('size', material.get('font_size', 15))) * h / 480))
            try:
                font = ImageFont.truetype(font_path, size)
            except (OSError, TypeError):
                raise ValueError('The selected native font is missing; choose another effect')
            text = layer.get('text', slots[layer['slot_id']].get('text', ''))
            spacing = max(0, round(size * float(material.get('line_spacing') or .12)))
            from effect_preview import render_text
            overlay, appearance_notice = render_text(entry, text, font, spacing)
            warnings.add(appearance_notice)
            overlay = overlay.resize((max(1, round(overlay.width * abs(scale.get('x', 1)))),
                                      max(1, round(overlay.height * abs(scale.get('y', 1))))))
        elif layer['kind'] == 'sticker':
            for raw in entry.get('preview_files', []):
                try:
                    path = Path(raw)
                    if not path.is_absolute():
                        path = Path(library.get('_preview_library_dir', '.')) / path
                    overlay = Image.open(path).convert('RGBA')
                    break
                except (OSError, ValueError):
                    continue
            if overlay is None:
                warnings.add('Sticker motion preview is unavailable at this moment.')
                continue
            # Native donor size is not a reliable bounding box for every sticker.
            target = max(1, round(w * abs(scale.get('x', .3))))
            overlay.thumbnail((target, max(1, round(h * abs(scale.get('y', .3))))))
            warnings.add('Sticker size and motion are approximate.')
        if overlay is not None:
            if clip.get('rotation'):
                overlay = overlay.rotate(-float(clip['rotation']), expand=True)
            alpha = max(0, min(1, float(clip.get('alpha', 1))))
            if alpha != 1:
                overlay.putalpha(overlay.getchannel('A').point(lambda v: round(v * alpha)))
            image.alpha_composite(overlay, (round(cx - overlay.width / 2), round(cy - overlay.height / 2)))
    output = BytesIO()
    image.convert('RGB').save(output, 'JPEG', quality=88)
    return output.getvalue(), warnings


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', required=True)
    parser.add_argument('--video', required=True, help='Fully composed Step 1 rough cut, without picker text/stickers')
    args = parser.parse_args()
    print(json.dumps(prepare(args.work, args.video), ensure_ascii=False))
