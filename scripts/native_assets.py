"""Harvest native text/sticker material closures from CapCut drafts; rank local candidates."""
import argparse
import copy
import hashlib
import json
import re
import unicodedata
from pathlib import Path


def load_project(path):
    p = Path(path)
    if p.is_dir():
        p = next((p/n for n in ('draft_info.json', 'draft_content.json') if (p/n).exists()), None)
        if p is None:
            raise ValueError('No root draft JSON in project directory')
    raw = p.read_text(encoding='utf-8-sig')
    if not raw.lstrip().startswith('{'):
        raise ValueError('Encrypted/non-JSON draft: cannot use file editing route')
    return json.loads(raw)


def walk_strings(obj):
    if isinstance(obj, str):
        yield obj
        if obj.lstrip().startswith(('{', '[')):
            try:
                yield from walk_strings(json.loads(obj))
            except (ValueError, TypeError):
                pass
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from walk_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_strings(v)


def resource_paths(obj):
    return sorted({s for s in walk_strings(obj)
                   if re.match(r'^(?:[A-Za-z]:[\\/]|/|\\\\)', s)})


def path_ready(path):
    p = Path(path)
    return p.is_file() or (p.is_dir() and any(p.iterdir()))


def material_index(draft):
    return {m['id']: (group, m) for group, rows in draft.get('materials', {}).items()
            if isinstance(rows, list) for m in rows if isinstance(m, dict) and m.get('id')}


def closure(draft, segment):
    index = material_index(draft)
    todo = list(walk_strings(segment)); selected = {}
    while todo:
        ref = todo.pop()
        if ref in index and ref not in selected:
            group, mat = index[ref]
            selected[ref] = (group, mat)
            todo.extend(walk_strings(mat))
    mats = {}
    for group, mat in selected.values():
        mats.setdefault(group, []).append(copy.deepcopy(mat))
    return mats


def unresolved_refs(materials):
    known={m['id'] for rows in materials.values() for m in rows}
    missing=set()
    def check(obj):
        if isinstance(obj,dict):
            for k,v in obj.items():
                if k=='text_material_id' and v and v not in known:missing.add(v)
                if k=='extra_material_refs':missing.update(x for x in v if x and x not in known)
                check(v)
        elif isinstance(obj,list):
            for v in obj:check(v)
    check(materials)
    return sorted(missing)


def fold(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s.lower().replace('đ', 'd')) if not unicodedata.combining(c))


def harvest(projects):
    entries = []; errors = []
    for path in projects:
        try:
            d = load_project(path)
            idx = material_index(d)
        except (ValueError, OSError) as exc:
            errors.append({'project': str(path), 'error': str(exc)}); continue
        for tr in d.get('tracks', []):
            for seg in tr.get('segments', []):
                group, mat = idx.get(seg.get('material_id'), ('', {}))
                if group not in ('texts', 'text_templates', 'stickers'):
                    continue
                mats = closure(d, seg)
                content = []
                for t in mats.get('texts', []):
                    try:
                        content.append(json.loads(t.get('content', '{}')).get('text', ''))
                    except ValueError:
                        pass
                paths = resource_paths(mats)
                missing = [p for p in paths if not path_ready(p)]
                graph_missing=unresolved_refs(mats)
                previews = []
                for p in paths:
                    if Path(p).is_dir():
                        previews.extend(str(Path(p)/n) for n in ('singleImage.png', 'final.gif', 'cover.png', 'icon.png') if (Path(p)/n).is_file())
                key = hashlib.sha256((str(Path(path).resolve()) + ':' + seg['id']).encode()).hexdigest()[:16]
                kind = 'sticker' if group == 'stickers' else 'text'
                desc = mat.get('name') or mat.get('preset_name') or ' / '.join(content) or group
                tags = [kind, group, desc]
                for t in mats.get('texts', []):
                    tags += [t.get('text_color',''), t.get('background_color','')]
                    tags += [f.get('title','') for f in t.get('fonts', [])]
                entries.append({'key': key, 'kind': kind, 'name': desc, 'tags': tags,
                                'sample_texts': content, 'project': str(Path(path).resolve()),
                                'app_version': d.get('last_modified_platform', {}).get('app_version'),
                                'canvas': d.get('canvas_config'), 'track_type': tr['type'],
                                'segment': copy.deepcopy(seg), 'materials': mats,
                                'resource_paths': paths, 'missing_paths': missing,
                                'available': not missing, 'supported': not bool(seg.get('keyframe_refs')) and not graph_missing,
                                'unresolved_refs':graph_missing,
                                'text_slots':[{'slot':t['id'],'sample_text':json.loads(t.get('content','{}')).get('text','')} for t in mats.get('texts',[])],
                                'preview_files': sorted(set(previews)), 'capcut_verified': False,
                                'visual_reviewed': False})
    return {'schema': 'capcut-native-library/1', 'entries': entries, 'errors': errors}


def rank(catalog, query, kind=None):
    words = set(re.findall(r'[a-z0-9#]+', fold(query)))
    synonyms = {'canh': ['warning','exclamation'], 'bao': ['warning'], 'tick': ['tick','check'],
                'ich': ['tick','check'], 'mui': ['arrow'], 'ten': ['arrow'],
                'nhan': ['emphasis','highlight'], 'gia': ['price','highlight'],
                'nen': ['background','box'], 'do': ['red'], 'vang': ['yellow'],
                'tim': ['search'], 'kiem': ['search']}
    expanded = words | {s for w in words for s in synonyms.get(w, [])}
    out = []
    for e in catalog['entries']:
        if kind and e['kind'] != kind:
            continue
        if not e['available'] or not e['supported']:
            continue
        hay = fold(' '.join([e['name'], *e.get('tags', [])]))
        tokens = set(re.findall(r'[a-z0-9#]+', hay))
        score = len(tokens & expanded)
        if score:
            out.append({'key': e['key'], 'name': e['name'], 'kind': e['kind'], 'score': score,
                        'preview_files': e['preview_files'], 'visual_reviewed': e['visual_reviewed'],
                        'capcut_verified': e['capcut_verified']})
    return sorted(out, key=lambda x: (-x['score'], x['key']))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    p = sub.add_parser('harvest'); p.add_argument('--project', action='append', required=True); p.add_argument('--out', required=True)
    p = sub.add_parser('search'); p.add_argument('--library', required=True); p.add_argument('--query', required=True); p.add_argument('--kind', choices=['text','sticker']); p.add_argument('--limit', type=int, default=10)
    p = sub.add_parser('label'); p.add_argument('--library', required=True); p.add_argument('--key', required=True); p.add_argument('--tags', nargs='+', required=True); p.add_argument('--visual-reviewed', action='store_true'); p.add_argument('--capcut-verified', action='store_true')
    a = ap.parse_args()
    if a.command == 'harvest':
        cat = harvest(a.project); dest = Path(a.out); dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(cat, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'entries': len(cat['entries']), 'available': sum(e['available'] for e in cat['entries']), 'errors': cat['errors']}))
    else:
        cat = json.loads(Path(a.library).read_text(encoding='utf-8-sig'))
        if a.command == 'search':
            print(json.dumps(rank(cat, a.query, a.kind)[:a.limit], ensure_ascii=True, indent=2))
        else:
            entry = next(e for e in cat['entries'] if e['key'] == a.key)
            entry['tags'] = sorted(set(entry['tags'] + a.tags))
            if a.visual_reviewed: entry['visual_reviewed'] = True
            if a.capcut_verified: entry['capcut_verified'] = True
            Path(a.library).write_text(json.dumps(cat, ensure_ascii=False, indent=2), encoding='utf-8')
            print(entry['key'])


if __name__ == '__main__':
    main()
