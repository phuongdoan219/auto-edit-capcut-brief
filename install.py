"""Install the skill and initialize its CapCut library on this machine."""
import argparse
from pathlib import Path
import shutil
import sys


def install(target=None, state_dir=None, roots=None, refresh=False, caches=None):
    source = Path(__file__).resolve().parent
    target = Path(target or Path.home()/'.codex'/'skills'/'auto-edit-capcut-brief').expanduser().resolve()
    if source != target:
        if target.exists() and not ((target/'SKILL.md').is_file() and 'name: auto-edit-capcut-brief' in (target/'SKILL.md').read_text(encoding='utf-8') and (target/'scripts'/'library_setup.py').is_file()):
            raise ValueError('Target is an existing or older installation. Update it in place, then run its workflow.py setup.')
        if source in target.parents or target in source.parents:
            raise ValueError('Install target must be separate from the source checkout')
        ignored = {'.git', '__pycache__', 'work', 'state', 'previews', 'library.json', 'library.local.json',
                   'native-catalog.json', 'native-previews.json', 'preview-jobs.json', 'setup.json',
                   'selection.json', 'picker-service.json', 'setup.lock', 'setup-error.json', 'cache-coverage.json'}
        if not target.exists():
            shutil.copytree(source, target, ignore=lambda directory, names: [n for n in names if n in ignored or n.endswith(('.pyc', '.log', '.bak'))])
    sys.path.insert(0, str(target/'scripts'))
    from library_setup import load_or_setup
    _, _, status = load_or_setup(state_dir, roots, refresh=refresh, caches=caches)
    return {'skill': str(target), **status}


def main():
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target'); parser.add_argument('--state-dir'); parser.add_argument('--root', action='append')
    parser.add_argument('--cache-root', action='append'); parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    try:
        result = install(args.target, args.state_dir, args.root, args.refresh, args.cache_root)
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, OSError) as exc:
        print(json.dumps({'status': 'setup_required', 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__': main()
