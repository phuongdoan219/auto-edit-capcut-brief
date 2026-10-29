"""Read-only machine-local CapCut library inventory.

Python: ``catalog, path = ensure_library(state_dir, roots=None, force=False)``.
CLI: ``library_scan.py ensure --state-dir DIR [--root ROOT ...] [--force]``.
Only state_dir/library.json is written. Every ensure refreshes project and resource
availability, so a removed resource cannot survive an unchanged draft fingerprint.
No remote downloads, credential files, project writes, or whole-disk discovery.
"""
import argparse
import copy
import hashlib
import json
import os
import platform
import re
import socket
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from native_assets import closure, material_index, resource_paths, unresolved_refs

SCHEMA = 'capcut-native-library/2'
CATEGORIES = ('text_style', 'text_effect', 'text_animation', 'text_template', 'sticker', 'video_effect')
DRAFT_NAMES = ('draft_info.json', 'draft_content.json')
SKIP_DIRS = {'backup', 'backups', 'autobackup', 'auto_backup', 'cache', '.git', '.recycle_bin', 'recycle_bin', 'trash', '.trash', 'draft_content.json.bak'}
MAX_METADATA_BYTES = 4 * 1024 * 1024
MAX_DRAFT_BYTES = 128 * 1024 * 1024
UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
ABS_RE = re.compile(r'^(?:[A-Za-z]:[\\/]|/|\\\\)')
META_PATH_KEYS = {'root_path', 'draft_root_path', 'draft_fold_path', 'draft_path', 'draft_storage_path', 'draft_save_path', 'project_path', 'project_root_path', 'project_save_path', 'currentcustomdraftpath'}


def _json_bytes(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def _digest(obj):
    return hashlib.sha256(_json_bytes(obj)).hexdigest()


def _read_bounded(path, limit):
    with Path(path).open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('file exceeds safe read limit')
    return data


def _normalize_roots(roots):
    return sorted({Path(p).expanduser().resolve() for p in roots}, key=lambda p: str(p).casefold())


def _metadata_roots(path):
    """Read path-only settings from explicitly allowlisted metadata names."""
    if not path.is_file():
        return []
    raw = _read_bounded(path, MAX_METADATA_BYTES).decode('utf-8-sig')
    out = []
    def walk(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key.lower() in META_PATH_KEYS and isinstance(value, str) and ABS_RE.match(value):
                    out.append(Path(value))
                elif isinstance(value, (list, dict)):
                    walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)
    try:
        obj=json.loads(raw)
    except ValueError:
        obj=None
    if isinstance(obj,(dict,list)):
        walk(obj)
    else:
        for line in raw.splitlines():
            key, sep, value = line.partition('=')
            if sep and key.strip().lower() in META_PATH_KEYS:
                value = value.strip().strip('"').replace('\\\\', '\\')
                if ABS_RE.match(value):
                    out.append(Path(value))
    return out


def discover_roots(roots=None, errors=None):
    """Explicit roots replace defaults. Otherwise inspect standard roots and known metadata."""
    if roots is not None:
        return _normalize_roots(roots)
    errors = errors if errors is not None else []
    home = Path.home()
    user_data = []
    if os.environ.get('LOCALAPPDATA'):
        user_data.append(Path(os.environ['LOCALAPPDATA']) / 'CapCut' / 'User Data')
    # Include platform conventions, never enumerate unrelated home subdirectories.
    user_data += [home / 'AppData' / 'Local' / 'CapCut' / 'User Data',
                  home / 'Library' / 'Application Support' / 'CapCut' / 'User Data']
    standard = [base / 'Projects' / 'com.lveditor.draft' for base in user_data]
    standard += [home / 'Movies' / 'CapCut' / 'User Data' / 'Projects' / 'com.lveditor.draft']
    found = [p for p in standard if p.exists()]
    metadata = [p / 'root_meta_info.json' for p in standard]
    metadata += [base / 'Config' / name for base in user_data for name in ('commonSetting.ini', 'globalSetting')]
    for path in _normalize_roots(metadata):
        try:
            found.extend(p for p in _metadata_roots(path) if p.exists())
        except (OSError, ValueError, UnicodeError) as exc:
            errors.append({'project': str(path), 'code': 'metadata_unreadable', 'error': str(exc)})
    return _normalize_roots(found)


def machine_identity(roots):
    """Computer identity plus resolved roots: a copied catalog is never authoritative."""
    return _digest({'host': socket.gethostname(), 'node': uuid.getnode(), 'system': platform.system(),
                    'user': str(Path.home()), 'roots': [str(p) for p in _normalize_roots(roots)]})[:24]


def discover_projects(roots, errors=None):
    errors = errors if errors is not None else []
    found = set()
    def onerror(exc):
        errors.append({'project': str(exc.filename), 'code': 'inaccessible', 'error': str(exc)})
    for root in roots:
        root = Path(root)
        if not root.exists():
            errors.append({'project': str(root), 'code': 'missing_root', 'error': 'Project root does not exist'})
            continue
        if root.is_file():
            if root.name in DRAFT_NAMES:
                found.add(root.resolve())
            continue
        for directory, dirs, files in os.walk(root, onerror=onerror, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d.casefold() not in SKIP_DIRS and not d.casefold().endswith(('.bak', '.backup')) and not Path(directory, d).is_symlink())
            # Some versions keep both names for one timeline: draft_info is preferred.
            for name in DRAFT_NAMES:
                if name in files:
                    found.add(Path(directory, name).resolve())
                    break
    return sorted(found, key=lambda p: str(p).casefold())


IGNORE_CANON = {'request_id', 'team_id', 'group_id', 'raw_segment_id', 'text_material_id', 'extra_material_refs',
    'target_timerange', 'source_timerange', 'render_timerange', 'time_range', 'apply_time_range',
    'start', 'start_time', 'end_time', 'range', 'text', 'recognize_text', 'recognize_task_id', 'words', 'current_words',
    'origin_word_info', 'current_word_info', 'translate_original_text', 'ssml_content', 'base_content',
    'text_to_audio_ids', 'relevance_segment', 'lyric_group_id', 'word_index', 'lyric_keyframes', 'material_text_ranges',
    'name', 'report_name', 'preset_name', 'style_name', 'category_name', 'category_id', 'category_key', 'sub_category_id',
    'sub_category_name', 'icon_url', 'preview_cover_url', 'font_url', 'file_uri', 'operation_type', 'add_type',
    'check_flag', 'original_size', 'recognize_model', 'punc_model', 'recognize_type'}


def _canonical(obj, local_ids=None, style=False):
    local_ids = local_ids or set()
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            if key in IGNORE_CANON or (style and key in {'combo_info', 'caption_template_info', 'lyrics_template', 'effectStyle'}):
                continue
            if key == 'id' and (value in local_ids or isinstance(value, str) and UUID_RE.match(value)):
                continue
            if key in {'path', 'font_path', 'lumi_hub_path', 'algorithm_artifact_path'}:
                # Resource IDs/font metadata, not the computer cache location, define identity.
                resource=obj.get('font_resource_id') or obj.get('resource_id') or obj.get('id')
                if style and key in {'path','font_path'} and (not resource or resource in local_ids):
                    p=Path(value) if isinstance(value,str) and value else None
                    if p and p.is_file():
                        try:out[key]={'content_sha256':hashlib.sha256(_read_bounded(p,32*1024*1024)).hexdigest()}
                        except (OSError,ValueError):out[key]={'local_path':str(p)}
                    elif p:out[key]={'local_path':str(p)}
                continue
            if isinstance(value, str) and value in local_ids:
                continue
            out[key] = _canonical(value, local_ids, style)
        return out
    if isinstance(obj, list):
        return [_canonical(v, local_ids, style) for v in obj]
    if isinstance(obj, str) and obj.lstrip().startswith(('{', '[')):
        try:
            return _canonical(json.loads(obj), local_ids, style)
        except ValueError:
            pass
    return obj


def _content(text):
    try:
        raw = text.get('content', {})
        return json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return {}


def _native_effects(mats):
    return [copy.deepcopy(m) for m in mats.get('effects', []) if m.get('type') in {'text_effect', 'text_shape', 'bloom'}]


def _plain_style(mats, segment):
    """Make one editable typography donor without inherited template/effect/motion."""
    texts = mats.get('texts', [])
    if not texts:
        return {}, copy.deepcopy(segment)
    text = copy.deepcopy(texts[0])
    content = _content(text)
    for style in content.get('styles', []):
        style.pop('effectStyle', None)
        if style.get('fill',{}).get('content',{}).get('render_type')=='texture':
            color=text.get('text_color','#ffffff').lstrip('#')
            if len(color)!=6:color='ffffff'
            style['fill']={'content':{'render_type':'solid','solid':{'color':[int(color[i:i+2],16)/255 for i in (0,2,4)]}}}
    text['content'] = json.dumps(content, ensure_ascii=False)
    text['combo_info'] = {'text_templates': []}
    for key in ('base_content','recognize_text','translate_original_text'):
        if key in text:text[key]=''
    for key in ('words','current_words'):
        if key in text:text[key]={'start_time':[],'end_time':[],'text':[]}
    for key in ('caption_template_info', 'lyrics_template'):
        text.pop(key, None)
    seg = copy.deepcopy(segment)
    seg['material_id'] = text['id']
    seg['extra_material_refs'] = []
    return {'texts': [text]}, seg


def _recipe(mats, effects=None):
    overrides = []
    ids={str(m.get(k)) for m in (effects or []) for k in ('resource_id','effect_id','third_resource_id') if m.get(k)}
    for text in mats.get('texts', []):
        for style in _content(text).get('styles', []):
            if effects is not None and str(style.get('effectStyle',{}).get('id','')) not in ids:continue
            # These appearance anchors are needed by CapCut's rich text renderer.
            visual={k: copy.deepcopy(v) for k, v in style.items() if k not in {'font', 'range', 'size'}}
            if visual not in overrides:overrides.append(visual)
    return {'effects': effects if effects is not None else _native_effects(mats),
            'style_overrides': overrides, 'material_group': 'effects'}


def _entry(category, draft, project, segment=None, track_type=None, mats=None, **fields):
    mats = copy.deepcopy(mats or {})
    texts = mats.get('texts', [])
    samples = [_content(t).get('text', '') for t in texts]
    native = next((m for rows in mats.values() for m in rows), {})
    graph_missing = unresolved_refs(mats)
    unsupported = []
    if graph_missing:
        unsupported.append('unresolved native material references')
    if segment and (segment.get('keyframe_refs') or segment.get('common_keyframes')):
        unsupported.append('segment keyframes require unsupported native dependencies')
    item = {'kind': 'text' if category in {'text_style', 'text_effect', 'text_template'} else category,
        'category': category, 'name': native.get('name') or native.get('preset_name') or ' / '.join(s for s in samples if s)[:160] or category,
        'project': str(project), 'app_version': draft.get('last_modified_platform', {}).get('app_version'),
        'canvas': copy.deepcopy(draft.get('canvas_config')), 'track_type': track_type,
        'materials': mats, 'sample_texts': samples, 'text_slots': [{'slot': t['id'], 'sample_text': _content(t).get('text', '')} for t in texts],
        'sources': [{'project': str(project), 'draft_id': draft.get('id'), 'segment_id': (segment or {}).get('id'), 'track_type': track_type}],
        'occurrences': 1, 'supported': not unsupported, 'unsupported_reasons': unsupported,
        'unresolved_refs': graph_missing, 'capcut_verified': False, 'visual_reviewed': False}
    if segment is not None:
        item['segment'] = copy.deepcopy(segment)
    item.update(fields)
    item['tags'] = [category, item['name']]
    return item


def _harvest(draft, project):
    idx = material_index(draft)
    local_ids = set(idx)
    out = []
    used_video = set()
    def emit(item, identity):
        item['key'] = item['category'] + '-' + _digest(identity)[:24]
        out.append(item)
    for track in draft.get('tracks', []):
        for seg in track.get('segments', []):
            group, mat = idx.get(seg.get('material_id'), ('', {}))
            mats = closure(draft, seg)
            if group in {'texts', 'text_templates'}:
                plain_mats, plain_segment = _plain_style(mats, seg)
                text_item = _entry('text_style', draft, project, plain_segment, 'text', plain_mats)
                if plain_mats.get('texts'):
                    t=plain_mats['texts'][0]
                    fonts=[f.get('title') for f in t.get('fonts',[]) if f.get('title')]
                    font=', '.join(dict.fromkeys(fonts)) or t.get('font_title') or 'Font theo project'
                    text_item['name']=font+' · '+str(t.get('text_color','theo style'))
                    if t.get('background_style'):text_item['name']+=' · nền '+str(t.get('background_color',''))
                styles = [_canonical(t, local_ids, style=True) for t in plain_mats.get('texts', [])]
                if not styles:
                    text_item['supported'] = False
                    text_item['unsupported_reasons'].append('template has no editable native text slot')
                emit(text_item, {'texts': styles})
                effects = _native_effects(mats)
                for effect in effects:
                    recipe = _recipe(mats, [effect])
                    item = _entry('text_effect', draft, project, seg, track.get('type'), mats, effect_recipe=recipe)
                    item['name'] = effect.get('name') or effect.get('resource_id') or effect.get('third_resource_id') or 'Text effect'
                    ids = {effect.get(k) for k in ('resource_id', 'effect_id', 'third_resource_id') if effect.get(k)}
                    anchors = [s['effectStyle'] for s in recipe['style_overrides'] if s.get('effectStyle')]
                    if not any(str(anchor.get('id')) in ids for anchor in anchors):
                        item['supported'] = False
                        item['unsupported_reasons'].append('no matching native rich-text effectStyle anchor')
                    if len(recipe['style_overrides'])>1:
                        item['supported']=False
                        item['unsupported_reasons'].append('multiple distinct effect appearance slots need explicit mapping')
                    emit(item, {'effect': _canonical(effect, local_ids), 'anchors': _canonical(recipe['style_overrides'], local_ids)})
                templates = mats.get('text_templates', [])
                if templates:
                    item = _entry('text_template', draft, project, seg, track.get('type'), mats, effect_recipe=_recipe(mats))
                    item['name'] = ' / '.join(t.get('name') or t.get('resource_id') or 'Text template' for t in templates)
                    emit(item, {'templates': [_canonical(t, local_ids) for t in templates], 'styles': styles})
                for animation_mat in mats.get('material_animations', []):
                    for anim in animation_mat.get('animations', []):
                        if not isinstance(anim, dict):
                            continue
                        native_mats = {'material_animations': [copy.deepcopy(animation_mat)]}
                        item = _entry('text_animation', draft, project, seg, track.get('type'), native_mats,
                            animation=copy.deepcopy(anim), animation_type=anim['type'], animation_material=copy.deepcopy(animation_mat))
                        item['name'] = anim.get('name') or anim.get('resource_id') or 'Text animation'
                        if anim.get('type') not in {'in', 'out', 'loop'}:
                            item['supported'] = False
                            item['unsupported_reasons'].append('unsupported native text animation type')
                        emit(item, _canonical(anim, local_ids))
            if group == 'stickers':
                item = _entry('sticker', draft, project, seg, track.get('type'), mats)
                emit(item, {'sticker': _canonical(mat, local_ids), 'clip': _canonical(seg.get('clip'), local_ids)})
            for ref, (effect_group, effect) in idx.items():
                if effect_group != 'video_effects' or effect.get('type') != 'video_effect':
                    continue
                primary = seg.get('material_id') == ref
                attached = ref in seg.get('extra_material_refs', []) and group == 'videos'
                if not primary and not attached:
                    continue
                used_video.add(ref)
                application = 'track' if primary and track.get('type') == 'effect' else 'clip' if attached else None
                effect_mats = closure(draft, {'material_id': ref})
                if application == 'track':
                    effect_mats = mats
                item = _entry('video_effect', draft, project, seg, track.get('type'), effect_mats,
                    effect_material=copy.deepcopy(effect), material_group=effect_group, application=application,
                    native_refs={'material_id': seg.get('material_id'), 'extra_material_refs': copy.deepcopy(seg.get('extra_material_refs', []))})
                item['name'] = effect.get('name') or effect.get('resource_id') or 'Video effect'
                if application is None:
                    item['supported'] = False; item['unsupported_reasons'].append('unrecognized effect application schema')
                emit(item, {'effect': _canonical(effect, local_ids), 'application': application})
    # Retain unused resource parts visibly, without claiming an invented application.
    for ref, (group, mat) in idx.items():
        if group == 'video_effects' and mat.get('type') == 'video_effect' and ref not in used_video:
            item = _entry('video_effect', draft, project, mats=closure(draft, {'material_id': ref}),
                effect_material=copy.deepcopy(mat), material_group=group, application=None)
            item['name'] = mat.get('name') or mat.get('resource_id') or 'Video effect'
            item['supported'] = False; item['unsupported_reasons'].append('no observed segment application')
            emit(item, {'effect': _canonical(mat, local_ids), 'application': None})
    return out


def _path_state(path):
    try:
        p = Path(path)
        return p.is_file() or p.is_dir() and next(p.iterdir(), None) is not None
    except OSError:
        return False


def _previews(paths):
    found = set()
    names = ('cover_icon.png', 'singleImage.png', 'final.gif', 'cover.png', 'cover.jpg', 'icon.png', 'preview.png', 'preview.gif','preview.mp4','preview.webm')
    for value in paths:
        p = Path(value)
        try:
            if p.is_file() and p.name.casefold() in {n.casefold() for n in names}:
                found.add(str(p))
            if not p.is_dir():
                continue
            # Bounded local resource directory, including common nested preview folders.
            for base in (p, p / 'preview', p / 'previews', p / 'cover'):
                for name in names:
                    candidate = base / name
                    if candidate.is_file():
                        found.add(str(candidate))
        except OSError:
            continue
    return sorted(found)


def _availability(item):
    native = {'materials': item.get('materials', {}), 'animation': item.get('animation', {}), 'effect_material': item.get('effect_material', {})}
    paths = resource_paths(native)
    missing = [p for p in paths if not _path_state(p)]
    item['resource_paths'] = paths
    item['missing_paths'] = missing
    item['available'] = not missing
    item['preview_files'] = _previews(paths)


def ensure_library(state_dir, roots=None, force=False):
    """Return (fresh catalog dict, absolute Path to state_dir/library.json).

    ``roots=None`` discovers Windows/macOS defaults plus allowlisted CapCut metadata;
    a list replaces that discovery. ``force`` is accepted for CLI parity: this version
    always refreshes, including resources, instead of trusting a stale cached catalog.
    Individual unreadable/encrypted/corrupt drafts appear in projects/errors.
    """
    errors = []
    roots = discover_roots(roots, errors)
    paths = discover_projects(roots, errors)
    entries = {}
    projects = []
    fingerprints = {}
    fingerprint_sources = {}
    for path in paths:
        project = {'path': str(path)}
        try:
            raw = _read_bounded(path, MAX_DRAFT_BYTES)
            if not raw.lstrip(b'\xef\xbb\xbf \n\r\t').startswith(b'{'):
                raise RuntimeError('Encrypted or non-JSON native draft; no decryption attempted')
            draft = json.loads(raw.decode('utf-8-sig'))
            if not isinstance(draft.get('materials'), dict) or not isinstance(draft.get('tracks'), list):
                raise ValueError('Draft lacks native materials/tracks')
            fingerprint = _digest(draft)
            project['fingerprint'] = fingerprint
            if fingerprint in fingerprints:
                project.update(status='duplicate', duplicate_of=fingerprints[fingerprint])
                for key, source in fingerprint_sources[fingerprint]:
                    duplicate_source = {**source, 'project': str(path), 'duplicate': True}
                    entries[key]['sources'].append(duplicate_source)
                projects.append(project)
                continue
            fingerprints[fingerprint] = str(path)
            harvested = _harvest(draft, path)
            fingerprint_sources[fingerprint] = [(e['key'], copy.deepcopy(e['sources'][0])) for e in harvested]
            project.update(status='scanned', entries=len(harvested), draft_id=draft.get('id'))
            for item in harvested:
                _availability(item)
                key = item['key']
                if key not in entries:
                    entries[key] = item
                    continue
                existing = entries[key]
                existing['occurrences'] += 1
                existing['sources'].extend(item['sources'])
                existing['sample_texts'] = sorted(set(existing.get('sample_texts', []) + item.get('sample_texts', [])))
                # Keep one complete donor bundle. Prefer a usable donor over a missing one.
                if (item['available'] and item['supported']) and not (existing['available'] and existing['supported']):
                    for name, value in item.items():
                        if name not in {'occurrences', 'sources', 'sample_texts'}:
                            existing[name] = value
                else:
                    existing['preview_files'] = sorted(set(existing['preview_files'] + item['preview_files']))
        except RuntimeError as exc:
            project.update(status='failed', code='encrypted', error=str(exc))
        except (ValueError, UnicodeError, TypeError, KeyError, AttributeError) as exc:
            project.update(status='failed', code='corrupt', error=str(exc))
        except OSError as exc:
            project.update(status='failed', code='inaccessible', error=str(exc))
        if project.get('status') == 'failed':
            errors.append({'project': str(path), 'code': project['code'], 'error': project['error']})
        projects.append(project)
    rows = sorted(entries.values(), key=lambda e: (e['category'], e['key']))
    from text_previews import create_preview
    for entry in rows:
        if entry.get('category') == 'text_style' and not entry.get('preview_files'):
            preview = create_preview(entry, state_dir)
            if preview:
                entry['preview_files'] = [preview]
    cat = {'schema': SCHEMA, 'machine_id': machine_identity(roots), 'roots': [str(p) for p in roots],
        'generated_at': datetime.now(timezone.utc).isoformat(), 'projects': projects, 'entries': rows, 'errors': errors,
        'summary': {'timelines_found': len(paths), 'projects_scanned': sum(p['status'] == 'scanned' for p in projects),
            'projects_failed': sum(p['status'] == 'failed' for p in projects), 'duplicate_timelines': sum(p['status'] == 'duplicate' for p in projects),
            'entries': len(rows), 'categories': {c: sum(e['category'] == c for e in rows) for c in CATEGORIES},
            'available': sum(e['available'] for e in rows), 'supported': sum(e['supported'] for e in rows),
            'missing_resource_entries': sum(bool(e['missing_paths']) for e in rows), 'errors': len(errors)}}
    dest = Path(state_dir).expanduser().resolve() / 'library.json'
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(cat, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(dest)
    return cat, dest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    command = sub.add_parser('ensure')
    command.add_argument('--state-dir', required=True)
    command.add_argument('--root', action='append')
    command.add_argument('--force', action='store_true')
    args = parser.parse_args()
    cat, path = ensure_library(args.state_dir, args.root, args.force)
    print(json.dumps({'library': str(path), 'machine_id': cat['machine_id'], 'summary': cat['summary']}, ensure_ascii=True))


if __name__ == '__main__':
    main()
