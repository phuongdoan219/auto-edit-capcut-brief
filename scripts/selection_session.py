"""Strict, side-effect-free human selection validation for the native picker.

File-backed callers must pass file_hash values; object-only callers use canonical
JSON hashes. Choices are copied, never completed or changed automatically.
"""
import copy
import hashlib
import json
from pathlib import Path

REQUEST_SCHEMA = 'capcut-selection-request/1'
LIBRARY_SCHEMA = 'capcut-native-library/2'
SESSION_SCHEMA = 'capcut-selection-session/1'
CATEGORIES = frozenset(('text_style', 'text_effect', 'text_animation', 'text_template', 'sticker', 'video_effect'))
ROLE_CATEGORIES = {'text': CATEGORIES - {'sticker', 'video_effect'},
                   'sticker': frozenset(('sticker',)), 'icon': frozenset(('sticker',)),
                   'video_effect': frozenset(('video_effect',))}


def effect_baseline_ready(entry):
    """An effect picker needs the selected effect's own editable text donor."""
    try:
        materials = entry.get('materials', {})
        texts = materials.get('texts', [])
        if not isinstance(texts, list) or len(texts) != 1:
            return False
        styles = json.loads(texts[0].get('content', '{}')).get('styles', [])
        recipe = entry.get('effect_recipe', {})
        return (entry.get('kind') == 'text' and isinstance(entry.get('segment'), dict)
                and entry['segment'].get('material_id') == texts[0].get('id')
                and bool(texts[0].get('id')) and not materials.get('text_templates')
                and isinstance(styles, list) and len(styles) == 1 and isinstance(styles[0], dict)
                and isinstance(recipe.get('effects'), list) and bool(recipe['effects'])
                and isinstance(recipe.get('style_overrides'), list) and bool(recipe['style_overrides']))
    except (TypeError, ValueError, KeyError, AttributeError):
        return False


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def object_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()


def _contracts(request, library):
    errors, slots, entries = [], {}, {}
    if not isinstance(request, dict) or request.get('schema') != REQUEST_SCHEMA:
        return ['Invalid selection request schema'], slots, entries
    if not isinstance(library, dict) or library.get('schema') != LIBRARY_SCHEMA:
        return ['Invalid CapCut library schema'], slots, entries
    if not isinstance(request.get('id'), str) or not request['id'].strip():
        errors.append('A request id is required')
    if not isinstance(library.get('machine_id'), str) or not library['machine_id'].strip():
        errors.append('The library needs a machine_id')
    frames = request.get('frames')
    if not isinstance(frames, list) or not frames:
        errors.append('A scene list is required')
        frames = []
    frame_ids = set()
    for frame in frames:
        if not isinstance(frame, dict) or not isinstance(frame.get('id'), str) or not frame['id']:
            errors.append('Each scene needs an id')
            continue
        if frame['id'] in frame_ids:
            errors.append('Duplicate scene id: ' + frame['id'])
        frame_ids.add(frame['id'])
        if not isinstance(frame.get('slots'), list):
            errors.append('Invalid scene slots: ' + frame['id'])
            continue
        for slot in frame['slots']:
            if not isinstance(slot, dict) or not isinstance(slot.get('id'), str) or not slot['id']:
                errors.append('Each slot needs an id')
                continue
            sid = slot['id']
            if sid in slots:
                errors.append('Duplicate slot id: ' + sid)
            slots[sid] = slot
            role = slot.get('role')
            if 'text_group' in slot and (role != 'text' or slot['text_group'] not in ('main','support')):
                errors.append('Text hierarchy must be main/support on a text slot: ' + sid)
            if role not in ROLE_CATEGORIES:
                errors.append('Invalid slot role: ' + sid)
                continue
            categories = slot.get('categories')
            if (not isinstance(categories, list) or not categories or
                    any(not isinstance(c, str) or c not in ROLE_CATEGORIES[role] for c in categories) or
                    len(set(categories)) != len(categories)):
                errors.append('Invalid slot categories: ' + sid)
            if type(slot.get('required')) is not bool:
                errors.append('Required must be true or false: ' + sid)
            if 'opt_in' in slot and (type(slot['opt_in']) is not bool or
                    (slot['opt_in'] and (role not in ('sticker','icon') or slot.get('required') is not False))):
                errors.append('Only optional sticker slots may be opt-in: ' + sid)
    raw_entries = library.get('entries')
    if not isinstance(raw_entries, list):
        errors.append('The library needs an asset list')
        raw_entries = []
    for entry in raw_entries:
        if not isinstance(entry, dict) or not isinstance(entry.get('key'), str) or not entry['key']:
            errors.append('Each library asset needs a key')
            continue
        key = entry['key']
        if key in entries:
            errors.append('Duplicate library key: ' + key)
        entries[key] = entry
        if entry.get('category') not in CATEGORIES:
            errors.append('Invalid library category: ' + key)
    return errors, slots, entries


def validate_draft_choices(request, library, choices):
    """Validate a partial browser/revision draft without inventing missing choices."""
    import copy
    errors, slots, _ = _contracts(request, library)
    if errors:return errors
    if not isinstance(choices, dict):return ['Draft choices must be an object']
    if any(sid not in slots for sid in choices):return ['Draft has an unknown slot']
    if not choices:return []
    partial=copy.deepcopy(request)
    for frame in partial['frames']:
        frame['slots']=[s for s in frame['slots'] if s['id'] in choices]
    partial['frames']=[f for f in partial['frames'] if f['slots']]
    return validate_choices(partial,library,choices)


def validate_choices(request, library, choices):
    """Return human-readable errors. Every slot needs a choice or optional skip."""
    errors, slots, entries = _contracts(request, library)
    if errors:
        return errors
    if not isinstance(choices, dict):
        return ['Choices must be an object keyed by slot id']
    for sid in choices:
        if sid not in slots:
            errors.append('Unknown slot: ' + str(sid))

    def asset(sid, key, category, direction=None):
        if not isinstance(key, str) or not key:
            errors.append(sid + ': choose an asset of type ' + category)
            return
        entry = entries.get(key)
        if entry is None:
            errors.append(sid + ': unknown asset: ' + key)
            return
        if entry.get('category') != category or category not in slots[sid]['categories']:
            errors.append(sid + ': this asset category is not allowed: ' + key)
        if entry.get('available') is not True or entry.get('supported') is not True:
            errors.append(sid + ': asset unavailable or unsupported: ' + key)
        paths = entry.get('resource_paths', [])
        if not isinstance(paths, list):
            errors.append(sid + ': invalid CapCut resource path: ' + key)
            paths = []
        for raw in paths:
            try:
                if not isinstance(raw, str) or '://' in raw or not Path(raw).is_absolute():
                    raise ValueError('Resources require absolute local paths')
                path = Path(raw)
                ready = path.is_file() or (path.is_dir() and next(path.iterdir(), None) is not None)
            except (OSError, ValueError):
                ready = False
            if not ready:
                errors.append(sid + ': resource is missing on this computer: ' + str(raw))
        if direction and entry.get('animation_type') != direction:
            errors.append(sid + ': animation direction must be ' + direction + ': ' + key)

    for sid, slot in slots.items():
        if sid not in choices:
            if slot.get('opt_in') is True:
                continue
            errors.append(sid + ': choose an item, or explicitly skip an optional slot')
            continue
        choice = choices[sid]
        if not isinstance(choice, dict):
            errors.append(sid + ': choice must be an object')
            continue
        if 'skip' in choice:
            if set(choice) != {'skip'} or choice.get('skip') is not True or slot['required']:
                errors.append(sid + ': only optional slots may be skipped')
            continue
        if slot['role'] != 'text':
            if set(choice) != {'asset'}:
                errors.append(sid + ': choice may contain only the asset key')
            asset(sid, choice.get('asset'), 'sticker' if slot['role'] == 'icon' else slot['role'])
            continue
        if slot['categories'] == ['text_effect']:
            if set(choice) != {'effect'}:
                errors.append(sid + ': choose one Text Effect only')
            asset(sid, choice.get('effect'), 'text_effect')
            selected = entries.get(choice['effect'], {}) if isinstance(choice.get('effect'), str) else {}
            if not effect_baseline_ready(selected):
                errors.append(sid + ': this effect has no supported editable text donor')
            continue
        if set(choice) - {'style', 'effect', 'template', 'animations'}:
            errors.append(sid + ': invalid text choice key')
        animations = choice.get('animations', {})
        if not isinstance(animations, dict):
            errors.append(sid + ': animations must be an object')
            animations = {}
        if set(animations) - {'in', 'out', 'loop'}:
            errors.append(sid + ': invalid animation direction')
        if choice.get('template') is not None:
            asset(sid, choice['template'], 'text_template')
            if (choice.get('style') is not None or choice.get('effect') is not None or
                    any(value is not None for value in animations.values())):
                errors.append(sid + ': templates cannot be combined with separate styles, effects, or animations')
        else:
            asset(sid, choice.get('style'), 'text_style')
            if choice.get('effect') is not None:
                asset(sid, choice['effect'], 'text_effect')
            for direction in ('in', 'out', 'loop'):
                if animations.get(direction) is not None:
                    asset(sid, animations[direction], 'text_animation', direction)
    return errors


def make_session(request, library, request_hash=None, library_hash=None):
    errors, _, _ = _contracts(request, library)
    if errors:
        raise ValueError('; '.join(errors))
    return {'schema': SESSION_SCHEMA, 'request_id': request['id'],
            'request_hash': request_hash or object_hash(request),
            'library_hash': library_hash or object_hash(library),
            'machine_id': library['machine_id'], 'status': 'pending', 'choices': {}}


def confirm_session(request, library, choices, request_hash=None, library_hash=None):
    errors = validate_choices(request, library, choices)
    if errors:
        raise ValueError('; '.join(errors))
    session = make_session(request, library, request_hash, library_hash)
    session['status'] = 'confirmed'
    session['choices'] = copy.deepcopy(choices)
    return session


def validate_confirmed_session(request, library, session, request_hash=None, library_hash=None):
    """Validate confirmation, provenance, exact hashes, and all human choices."""
    try:
        expected = make_session(request, library, request_hash, library_hash)
    except (ValueError, TypeError) as error:
        return [str(error)]
    if not isinstance(session, dict):
        return ['Selection session must be an object']
    errors = []
    for field in ('schema', 'request_id', 'request_hash', 'library_hash', 'machine_id'):
        if session.get(field) != expected[field]:
            errors.append('Session field ' + field + ' does not match the current request or library')
    if session.get('status') != 'confirmed':
        errors.append('Selections have not been confirmed by the user')
    errors.extend(validate_choices(request, library, session.get('choices')))
    return errors


def load_confirmed_session(request, library, path, request_hash=None, library_hash=None):
    session = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    errors = validate_confirmed_session(request, library, session, request_hash, library_hash)
    if errors:
        raise ValueError('; '.join(errors))
    return session
