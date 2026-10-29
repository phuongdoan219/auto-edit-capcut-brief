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
        return ['Cấu trúc yêu cầu chọn thành phần không hợp lệ'], slots, entries
    if not isinstance(library, dict) or library.get('schema') != LIBRARY_SCHEMA:
        return ['Cấu trúc thư viện CapCut không hợp lệ'], slots, entries
    if not isinstance(request.get('id'), str) or not request['id'].strip():
        errors.append('Yêu cầu phải có mã id')
    if not isinstance(library.get('machine_id'), str) or not library['machine_id'].strip():
        errors.append('Thư viện phải có mã máy machine_id')
    frames = request.get('frames')
    if not isinstance(frames, list) or not frames:
        errors.append('Yêu cầu phải có danh sách cảnh')
        frames = []
    frame_ids = set()
    for frame in frames:
        if not isinstance(frame, dict) or not isinstance(frame.get('id'), str) or not frame['id']:
            errors.append('Mỗi cảnh cần có mã id')
            continue
        if frame['id'] in frame_ids:
            errors.append('Trùng mã cảnh: ' + frame['id'])
        frame_ids.add(frame['id'])
        if not isinstance(frame.get('slots'), list):
            errors.append('Danh sách ô chọn của cảnh không hợp lệ: ' + frame['id'])
            continue
        for slot in frame['slots']:
            if not isinstance(slot, dict) or not isinstance(slot.get('id'), str) or not slot['id']:
                errors.append('Mỗi ô chọn cần có mã id')
                continue
            sid = slot['id']
            if sid in slots:
                errors.append('Trùng mã ô chọn: ' + sid)
            slots[sid] = slot
            role = slot.get('role')
            if role not in ROLE_CATEGORIES:
                errors.append('Vai trò ô chọn không hợp lệ: ' + sid)
                continue
            categories = slot.get('categories')
            if (not isinstance(categories, list) or not categories or
                    any(not isinstance(c, str) or c not in ROLE_CATEGORIES[role] for c in categories) or
                    len(set(categories)) != len(categories)):
                errors.append('Loại thành phần của ô chọn không hợp lệ: ' + sid)
            if type(slot.get('required')) is not bool:
                errors.append('Thuộc tính required phải là true hoặc false: ' + sid)
    raw_entries = library.get('entries')
    if not isinstance(raw_entries, list):
        errors.append('Thư viện phải có danh sách thành phần')
        raw_entries = []
    for entry in raw_entries:
        if not isinstance(entry, dict) or not isinstance(entry.get('key'), str) or not entry['key']:
            errors.append('Thành phần thư viện cần có mã key')
            continue
        key = entry['key']
        if key in entries:
            errors.append('Trùng mã thành phần thư viện: ' + key)
        entries[key] = entry
        if entry.get('category') not in CATEGORIES:
            errors.append('Loại thành phần thư viện không hợp lệ: ' + key)
    return errors, slots, entries


def validate_choices(request, library, choices):
    """Return human-readable errors. Every slot needs a choice or optional skip."""
    errors, slots, entries = _contracts(request, library)
    if errors:
        return errors
    if not isinstance(choices, dict):
        return ['Lựa chọn phải là đối tượng có khóa là mã ô chọn']
    for sid in choices:
        if sid not in slots:
            errors.append('Ô chọn không tồn tại: ' + str(sid))

    def asset(sid, key, category, direction=None):
        if not isinstance(key, str) or not key:
            errors.append(sid + ': hãy chọn thành phần loại ' + category)
            return
        entry = entries.get(key)
        if entry is None:
            errors.append(sid + ': thành phần không tồn tại: ' + key)
            return
        if entry.get('category') != category or category not in slots[sid]['categories']:
            errors.append(sid + ': không được chọn loại thành phần này: ' + key)
        if entry.get('available') is not True or entry.get('supported') is not True:
            errors.append(sid + ': thành phần thiếu tài nguyên hoặc chưa hỗ trợ: ' + key)
        paths = entry.get('resource_paths', [])
        if not isinstance(paths, list):
            errors.append(sid + ': đường dẫn tài nguyên CapCut không hợp lệ: ' + key)
            paths = []
        for raw in paths:
            try:
                if not isinstance(raw, str) or '://' in raw or not Path(raw).is_absolute():
                    raise ValueError('Tài nguyên phải có đường dẫn tuyệt đối trên máy')
                path = Path(raw)
                ready = path.is_file() or (path.is_dir() and next(path.iterdir(), None) is not None)
            except (OSError, ValueError):
                ready = False
            if not ready:
                errors.append(sid + ': tài nguyên gốc không còn trên máy: ' + str(raw))
        if direction and entry.get('animation_type') != direction:
            errors.append(sid + ': loại chuyển động phải là ' + direction + ': ' + key)

    for sid, slot in slots.items():
        if sid not in choices:
            errors.append(sid + ': hãy chọn thành phần hoặc chủ động bỏ qua nếu không bắt buộc')
            continue
        choice = choices[sid]
        if not isinstance(choice, dict):
            errors.append(sid + ': lựa chọn phải là một đối tượng')
            continue
        if 'skip' in choice:
            if set(choice) != {'skip'} or choice.get('skip') is not True or slot['required']:
                errors.append(sid + ': chỉ được bỏ qua ô không bắt buộc')
            continue
        if slot['role'] != 'text':
            if set(choice) != {'asset'}:
                errors.append(sid + ': lựa chọn chỉ được chứa khóa asset')
            asset(sid, choice.get('asset'), 'sticker' if slot['role'] == 'icon' else slot['role'])
            continue
        if set(choice) - {'style', 'effect', 'template', 'animations'}:
            errors.append(sid + ': lựa chọn chữ có khóa không hợp lệ')
        animations = choice.get('animations', {})
        if not isinstance(animations, dict):
            errors.append(sid + ': animations phải là một đối tượng')
            animations = {}
        if set(animations) - {'in', 'out', 'loop'}:
            errors.append(sid + ': loại chuyển động không hợp lệ')
        if choice.get('template') is not None:
            asset(sid, choice['template'], 'text_template')
            if (choice.get('style') is not None or choice.get('effect') is not None or
                    any(value is not None for value in animations.values())):
                errors.append(sid + ': mẫu chữ không được ghép thêm kiểu chữ, hiệu ứng hoặc chuyển động riêng')
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
        return ['Phiên chọn thành phần phải là một đối tượng']
    errors = []
    for field in ('schema', 'request_id', 'request_hash', 'library_hash', 'machine_id'):
        if session.get(field) != expected[field]:
            errors.append('Trường phiên ' + field + ' không khớp yêu cầu hoặc thư viện hiện tại')
    if session.get('status') != 'confirmed':
        errors.append('Người dùng chưa xác nhận lựa chọn')
    errors.extend(validate_choices(request, library, session.get('choices')))
    return errors


def load_confirmed_session(request, library, path, request_hash=None, library_hash=None):
    session = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    errors = validate_confirmed_session(request, library, session, request_hash, library_hash)
    if errors:
        raise ValueError('; '.join(errors))
    return session
