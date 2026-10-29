"""Persistent native preview queue and CapCut catalogue capture imports.

This CLI does not pretend to render CapCut effects. The agent operates CapCut,
then imports the observed captures/exports with identity and provenance.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, obj):
    from picker_server import atomic_json
    atomic_json(path, obj)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fingerprint(entry):
    from selection_session import object_hash
    return object_hash({k: entry.get(k) for k in ('key', 'category', 'materials', 'segment', 'animation', 'effect_material')})


def media_info(path):
    path = Path(path)
    if path.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp', '.gif'}:
        from PIL import Image
        with Image.open(path) as im:
            im.load()
            return {'motion': getattr(im, 'n_frames', 1) > 1, 'width': im.width, 'height': im.height}
    if path.suffix.lower() not in {'.mp4', '.webm', '.mov'}:
        raise ValueError('Preview must be a real image or video')
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)], capture_output=True, text=True)
    if result.returncode:
        raise ValueError('Cannot decode native preview video')
    info = json.loads(result.stdout)
    stream = next((s for s in info['streams'] if s.get('codec_type') == 'video'), None)
    if not stream or float(info.get('format', {}).get('duration', 0)) <= 0:
        raise ValueError('Preview contains no playable video')
    return {'motion': True, 'width': stream['width'], 'height': stream['height']}


def merge(catalog, state_dir):
    """Called on each scan; captures survive refresh, stale donors do not."""
    root = Path(state_dir)
    index = root / 'native-previews.json'
    records = read(index) if index.exists() else {}
    for entry in catalog['entries']:
        record = records.get(entry['key'])
        if not record or record.get('machine_id') != catalog['machine_id'] or record.get('fingerprint') != fingerprint(entry):
            continue
        media = Path(record['file'])
        if not media.is_file() or digest(media) != record['sha256']:
            continue
        entry.update(preview_files=[str(media)], preview_kind=record['kind'], preview_evidence=record['evidence'], preview_motion=record['motion'])
    path = root / 'native-catalog.json'
    existing = {e['key'] for e in catalog['entries']}
    if path.exists():
        data = read(path)
        if data.get('machine_id') == catalog['machine_id']:
            for entry in data.get('entries', []):
                if entry['key'] not in existing and all(Path(p).is_file() for p in entry.get('preview_files', [])):
                    catalog['entries'].append(entry)
                    existing.add(entry['key'])


def jobs(catalog):
    result = []
    for entry in catalog['entries']:
        if entry.get('origin') == 'capcut_catalog':
            continue
        paths = entry.get('preview_files', [])
        motion_needed = entry['category'] in {'text_animation', 'text_template', 'video_effect'}
        motion = entry.get('preview_motion') or any(Path(p).suffix.lower() in {'.gif', '.mp4', '.webm', '.mov'} for p in paths)
        if paths and entry.get('preview_kind') != 'approximate_text' and (not motion_needed or motion):
            continue
        segment = entry.get('segment', {})
        result.append({'asset_key': entry['key'], 'fingerprint': fingerprint(entry), 'category': entry['category'],
                       'name': entry.get('display_name') or entry.get('name'), 'native_name': entry.get('name'),
                       'project': entry.get('project'), 'segment_id': segment.get('id'),
                       'target_timerange': segment.get('target_timerange'), 'motion_required': motion_needed,
                       'available': entry.get('available'), 'supported': entry.get('supported'),
                       'resource_ids': sorted({str(m[k]) for rows in entry.get('materials', {}).values() for m in rows
                                               for k in ('resource_id', 'effect_id') if m.get(k)}),
                       'status': 'needs_native_preview'})
    return {'schema': 'capcut-preview-jobs/1', 'machine_id': catalog['machine_id'], 'pending': len(result),
            'catalog_browse': {'status': 'not_exhaustive', 'categories': ['text_style', 'text_effect', 'text_animation', 'text_template', 'sticker', 'video_effect']}, 'jobs': result}


def attach(library, state_dir, key, media, evidence_path):
    catalog = read(library)
    entry = next(e for e in catalog['entries'] if e['key'] == key)
    evidence = read(evidence_path)
    if evidence.get('asset_key') != key or evidence.get('fingerprint') != fingerprint(entry):
        raise ValueError('Capture evidence does not match this asset/donor')
    if evidence.get('method') not in {'capcut_export', 'capcut_ui_capture'} or not evidence.get('app_version'):
        raise ValueError('CapCut capture method and observed app version are required')
    if evidence.get('scope') not in {'isolated', 'project_context'}:
        raise ValueError('Identify isolated preview or project context')
    if evidence['scope'] == 'project_context' and (evidence.get('project') != entry.get('project') or evidence.get('segment_id') != entry.get('segment', {}).get('id')):
        raise ValueError('Context capture must identify the donor project and segment')
    info = media_info(media)
    root = Path(state_dir)
    dest = root / 'previews' / (key + '-' + digest(media)[:16] + Path(media).suffix.lower())
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.resolve() != Path(media).resolve():
        shutil.copyfile(media, dest)
    index = root / 'native-previews.json'
    records = read(index) if index.exists() else {}
    records[key] = {'machine_id': catalog['machine_id'], 'fingerprint': fingerprint(entry), 'file': str(dest.resolve()),
                    'sha256': digest(dest), 'kind': 'capcut_render' if evidence['scope'] == 'isolated' else 'capcut_project_context',
                    'evidence': evidence, **info}
    save(index, records)
    return records[key]


def import_catalog(library, state_dir, sheet, manifest_path):
    """Crop observed native tiles; no guessed resource IDs or invented recipes."""
    from PIL import Image
    from selection_session import object_hash, CATEGORIES
    catalog = read(library)
    manifest = read(manifest_path)
    if not manifest.get('app_version') or not manifest.get('panel') or not manifest.get('items'):
        raise ValueError('Observed CapCut version, panel and tile annotations required')
    root = Path(state_dir)
    path = root / 'native-catalog.json'
    data = read(path) if path.exists() else {'machine_id': catalog['machine_id'], 'entries': []}
    if data['machine_id'] != catalog['machine_id']:
        raise ValueError('Catalogue belongs to another machine')
    entries = {e['key']: e for e in data['entries']}
    with Image.open(sheet) as image:
        for item in manifest['items']:
            category, label = item['category'], item['label']
            if category not in CATEGORIES or not isinstance(label, str) or not label.strip():
                raise ValueError('Invalid native tile category/name')
            x, y, w, h = item['box']
            if any(type(v) is not int for v in item['box']) or min(x, y) < 0 or min(w, h) <= 0 or x+w > image.width or y+h > image.height:
                raise ValueError('Tile outside observed screenshot')
            tile = image.crop((x, y, x+w, y+h)).convert('RGBA')
            pixel_hash = hashlib.sha256(tile.tobytes()).hexdigest()
            key = 'catalog-' + object_hash({'category': category, 'resource_id': item.get('resource_id'), 'label': label, 'pixels': pixel_hash})[:24]
            dest = root / 'previews' / (key+'.png')
            dest.parent.mkdir(parents=True, exist_ok=True)
            tile.save(dest)
            entries[key] = {'key': key, 'category': category, 'name': label, 'display_name': label, 'origin': 'capcut_catalog',
                'resource_id': item.get('resource_id'), 'resource_paths': [], 'missing_paths': [], 'available': True, 'supported': False, 'materials': {},
                'unsupported_reasons': ['Native catalogue tile only; timeline recipe not collected'],
                'sources': [{'name': 'CapCut · '+manifest['panel']}], 'occurrences': 1, 'preview_files': [str(dest.resolve())],
                'preview_kind': 'capcut_catalog_thumbnail', 'preview_motion': False, 'capcut_verified': False,
                'preview_evidence': {'method': 'capcut_ui_capture', 'app_version': manifest['app_version'],
                    'panel': manifest['panel'], 'sheet_sha256': digest(sheet), 'box': item['box'], 'scope': 'catalog_tile'}}
    data['entries'] = list(entries.values())
    data['coverage'] = {'status': 'partial', 'observed_items': len(entries), 'note': 'Only observed tiles, never the whole online catalogue'}
    save(path, data)
    return data['coverage']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('queue'); p.add_argument('--library', required=True); p.add_argument('--out', required=True)
    p = sub.add_parser('attach')
    for arg in ('library', 'state-dir', 'key', 'media', 'evidence'): p.add_argument('--'+arg, required=True)
    p = sub.add_parser('catalog')
    for arg in ('library', 'state-dir', 'sheet', 'manifest'): p.add_argument('--'+arg, required=True)
    args = parser.parse_args()
    if args.command == 'queue':
        result = jobs(read(args.library)); save(args.out, result); print(json.dumps({'pending': result['pending']}))
    elif args.command == 'attach':
        result = attach(args.library, args.state_dir, args.key, args.media, args.evidence); print(json.dumps({'kind': result['kind'], 'motion': result['motion']}))
    else:
        print(json.dumps(import_catalog(args.library, args.state_dir, args.sheet, args.manifest)))


if __name__ == '__main__':
    main()
