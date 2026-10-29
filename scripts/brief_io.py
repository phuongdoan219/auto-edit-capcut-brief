"""Normalize a fetched MarkFlow daily script or a structured frame brief. No network writes."""
import argparse
import html
import json
import re
import unicodedata
from pathlib import Path


def clean_notes(value):
    text = html.unescape(str(value or ''))
    text = re.sub(r'\[([^\]]+)\]\(https?://[^)]+\)', r'\1', text)
    text = text.replace('\\_', '_').replace('\\\n', '\n')
    return re.sub(r'(?m)^\\-', '-', text)


def source_paths(notes):
    found = []
    for p in re.findall(r'"([^"\n]+)"', notes):
        if not re.match(r'^(?:[A-Za-z]:[\\/]|/|\\\\)', p):
            continue
        if re.match(r'^[A-Za-z]:', p):
            p = re.sub(r'\\{2,}', lambda _: '\\', p)
        # Keep the supplied Unicode spelling. NFC is a lookup fallback, not a rewrite.
        if p not in found:
            found.append(p)
    return found


def normalize(raw):
    if 'structuredContent' in raw:
        raw = raw['structuredContent']
    if isinstance(raw.get('frames'), list):
        return raw
    if not isinstance(raw.get('items'), list):
        raise ValueError('Expected MarkFlow items[] or an explicit frames[] brief')
    frames = []
    for item in sorted(raw['items'], key=lambda i: i['item_order']):
        notes = clean_notes(item.get('source'))
        paths = source_paths(notes)
        voice_tail = re.split(r'(?i)-\s*Voice\s*:', notes)[-1]
        voice_paths = source_paths(voice_tail) if voice_tail != notes else []
        speed = re.search(r'(?i)(?:speed\s*voice|tốc\s*độ|speed)[^\n]{0,25}?x\s*(\d+(?:\.\d+)?)', voice_tail)
        voice_mode = item.get('voice_mode')
        if not voice_mode:
            if re.search(r'(?i)voice\s*gốc|tiếng\s*gốc', voice_tail):
                voice_mode = 'original'
            elif voice_paths and Path(voice_paths[0]).suffix.lower() in ('.mp3', '.wav', '.m4a', '.aac', '.flac'):
                voice_mode = 'provided_clone'
            else:
                voice_mode = 'unspecified'
        issues = []
        for p in paths:
            if p.lower().endswith(('.crdownload', '.part', '.tmp')):
                issues.append({'type': 'incomplete_download', 'path': p})
            elif not Path(p).exists() and not Path(unicodedata.normalize('NFC', p)).exists():
                issues.append({'type': 'missing_path', 'path': p})
        if voice_mode == 'unspecified':
            issues.append({'type': 'voice_mode_unresolved'})
        frames.append({'frame': item['item_order'], 'item_uid': item.get('item_uid'),
                       'dialogue': item.get('voice', ''), 'edit_notes': notes,
                       'source_paths': paths, 'voice': {'mode': voice_mode,
                       'file': voice_paths[0] if voice_paths else None,
                       'speed': float(speed.group(1)) if speed else 1.0,
                       'alignment': 'required', 'mute_footage': bool(re.search(r'(?i)tắt\s*(?:voice|tiếng)', notes))},
                       'issues': issues, 'raw_source': item.get('source', '')})
    return {'schema': 'capcut-frame-brief/1', 'source_id': raw.get('id'),
            'title': raw.get('title', 'CapCut edit'), 'frames': frames,
            'timing_status': 'unresolved', 'notes': 'Frame means editorial scene, not a single video frame. No durations inferred.'}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    result = normalize(json.loads(Path(a.input).read_text(encoding='utf-8-sig')))
    dest = Path(a.out); dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'frames': len(result['frames']), 'issues': sum(len(f.get('issues', [])) for f in result['frames']), 'out': str(dest)}, ensure_ascii=True))


if __name__ == '__main__':
    main()
