"""Optional read-only capcut-cli integration plus pinned catalogue lookup."""
import argparse
import json
from pathlib import Path
import subprocess


CATALOGUE = Path(__file__).resolve().parents[1] / 'assets' / 'capcut-cli-catalogue.json'


def lookup(query, category=None):
    data = json.loads(CATALOGUE.read_text(encoding='utf-8'))
    term = query.strip().casefold()
    return [e for e in data['entries'] if (not category or e['category'] == category) and
            any(term in str(e.get(k, '')).casefold() for k in ('name', 'title', 'slug', 'member', 'effect_id', 'resource_id'))]


def audit(entry, project, out):
    entry, project = Path(entry).resolve(strict=True), Path(project).resolve(strict=True)
    report = {'source': 'capcut-cli', 'mode': 'read_only', 'project': str(project), 'commands': {},
              'capcut_render_verified': False}
    for command in ('info', 'lint'):
        result = subprocess.run(['node', str(entry), command, str(project)], capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=120, shell=False)
        try:
            payload = json.loads(result.stdout)
        except ValueError:
            payload = {'error': 'CLI did not return JSON', 'detail': result.stderr[-2000:]}
        report['commands'][command] = {'exit_code': result.returncode, 'result': payload}
    from picker_server import atomic_json
    atomic_json(Path(out), report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('lookup'); p.add_argument('query'); p.add_argument('--category'); p.add_argument('--limit', type=int, default=30)
    p = sub.add_parser('audit')
    for name in ('entry', 'project', 'out'): p.add_argument('--'+name, required=True)
    args = parser.parse_args()
    if args.command == 'lookup': print(json.dumps(lookup(args.query, args.category)[:args.limit], ensure_ascii=False))
    else:
        report = audit(args.entry, args.project, args.out)
        print(json.dumps({k: v['exit_code'] for k, v in report['commands'].items()}))


if __name__ == '__main__': main()
