"""Inventory ALL readable native previews in specified CapCut effect caches.

No online-catalogue claim, guessed recipes, downloads or project writes. Archives
are read by allowlisted names, never extracted. Font-only InfoSticker packages
are excluded. capcut-cli's pinned IDs help name resources; they are not previews.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import zipfile

from native_previews import digest, media_info, read, save
from selection_session import object_hash

MAX_FILE = 32 * 1024 * 1024
MEDIA = ('preview.mp4', 'preview.webm', 'final.gif', 'preview.gif', 'singleImage.png', 'cover_icon.png', 'cover.png', 'icon.png')


def links(config):
    effect = config.get('effect', {})
    return effect.get('Link', []) if isinstance(effect, dict) else []


def classify(config, names, reference):
    kinds = {link.get('type') for link in links(config) if isinstance(link, dict)}
    if kinds == {'TextStyle'}: return 'text_effect', None
    # Fonts also use InfoSticker. Actual sticker images/scripts are required.
    if kinds == {'InfoSticker'} and any(n in names for n in ('final.gif', 'singleImage.png', 'infoSticker.lua')):
        return 'sticker', None
    if reference: return reference['category'], reference.get('animation_type')
    return None, None


def scan(library, state_dir, roots):
    catalog = read(library)
    root = Path(state_dir)
    path = root/'native-catalog.json'
    data = read(path) if path.exists() else {'machine_id': catalog['machine_id'], 'entries': []}
    if data['machine_id'] != catalog['machine_id']: raise ValueError('Cache catalogue belongs to another machine')
    entries = {e['key']: e for e in data['entries']}
    refs = read(Path(__file__).resolve().parents[1]/'assets'/'capcut-cli-catalogue.json')
    by_id = {}
    for row in refs['entries']:
        for field in ('resource_id', 'effect_id'):
            if row.get(field): by_id.setdefault(row[field], row)
    counts, errors, seen = Counter(), [], set()

    def consume(resource_id, owner, config, names, load):
        counts['packages_read'] += 1
        ref = by_id.get(resource_id)
        category, direction = classify(config, names, ref)
        if not category:
            counts['unclassified_or_font'] += 1; return
        candidates = [n for n in MEDIA if n in names]
        if not candidates:
            counts['classified_without_preview'] += 1; return
        for name in candidates:
            try:
                raw = load(name)
                if len(raw) > MAX_FILE: raise ValueError('Preview exceeds size limit')
                sha = hashlib.sha256(raw).hexdigest()
                key = 'cache-'+object_hash({'category': category, 'resource_id': resource_id, 'media_sha256': sha})[:24]
                dest = root/'previews'/(key+Path(name).suffix.lower())
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists(): dest.write_bytes(raw)
                info = media_info(dest)
                native_name = (ref or {}).get('name') or (ref or {}).get('title') or (ref or {}).get('slug', '').replace('-', ' ')
                label = native_name or ({'text_effect': 'Hiệu ứng chữ', 'sticker': 'Sticker', 'text_animation': 'Chuyển động chữ', 'video_effect': 'Hiệu ứng video'}[category]+' · '+resource_id)
                entries[key] = {'key': key, 'name': label, 'display_name': label, 'category': category, 'animation_type': direction,
                    'origin': 'capcut_catalog', 'source_type': 'native_cache', 'resource_id': resource_id,
                    'available': True, 'supported': False, 'materials': {}, 'resource_paths': [], 'missing_paths': [],
                    'sources': [{'name': 'Cache CapCut', 'path': str(owner)}], 'occurrences': 1,
                    'preview_files': [str(dest.resolve())], 'preview_kind': 'capcut_cache_thumbnail', 'preview_motion': info['motion'],
                    'capcut_verified': False, 'unsupported_reasons': ['Preview/resource cache only; timeline recipe not collected'],
                    'preview_evidence': {'method': 'native_cache', 'resource_id': resource_id, 'owner': str(owner), 'file': name, 'sha256': sha}}
                seen.add(key); counts['with_preview'] += 1; counts[category] += 1
                return
            except (OSError, ValueError, KeyError) as exc:
                errors.append({'owner': str(owner), 'preview': name, 'error': str(exc)})

    for cache in roots:
        cache = Path(cache).resolve()
        if not cache.is_dir():
            errors.append({'root': str(cache), 'error': 'Missing cache root'}); continue
        for config_path in sorted(cache.glob('*/*/config.json')):
            try:
                if config_path.stat().st_size > MAX_FILE: raise ValueError('Oversized config')
                config = read(config_path)
                folder = config_path.parent
                names = {p.name for p in folder.iterdir() if p.is_file()}
                consume(folder.parent.name, folder, config, names, lambda n, folder=folder: (folder/n).read_bytes())
            except (ValueError, OSError) as exc:
                errors.append({'owner': str(config_path), 'error': str(exc)})
        for archive in sorted(cache.glob('*/*')):
            if not archive.is_file() or not zipfile.is_zipfile(archive): continue
            try:
                with zipfile.ZipFile(archive) as z:
                    names = set(z.namelist())
                    if 'config.json' not in names: continue
                    def load(n):
                        if z.getinfo(n).file_size > MAX_FILE: raise ValueError('Archive member exceeds size limit')
                        return z.read(n)
                    config = json.loads(load('config.json').decode('utf-8-sig'))
                    consume(archive.parent.name, archive, config, names, load)
            except (ValueError, OSError, zipfile.BadZipFile) as exc:
                errors.append({'owner': str(archive), 'error': str(exc)})
    data['entries'] = list(entries.values())
    data['coverage'] = {'status': 'partial_online_catalogue', 'cache_roots_completed': [str(Path(p).resolve()) for p in roots],
                        'unique_native_cache_previews': len(seen), 'counts': dict(counts), 'errors': errors,
                        'reference': {'source': refs['source'], 'revision': refs['revision']}}
    save(path, data)
    return data['coverage']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', required=True); parser.add_argument('--state-dir', required=True)
    parser.add_argument('--root', action='append', required=True); parser.add_argument('--report', required=True)
    args = parser.parse_args()
    result = scan(args.library, args.state_dir, args.root)
    save(args.report, result)
    print(json.dumps({k: v for k, v in result.items() if k not in {'errors', 'reference', 'cache_roots_completed'}}))


if __name__ == '__main__': main()
