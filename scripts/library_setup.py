"""One-time, machine-local library setup. Normal edits load the saved library."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import library_scan as scan
from native_previews import jobs, merge
from picker_server import atomic_json


def default_state():
    if os.name == 'nt':
        return Path(os.environ.get('LOCALAPPDATA', Path.home()/'AppData'/'Local'))/'CodexCapCutBrief'
    if os.sys.platform == 'darwin':
        return Path.home()/'Library'/'Application Support'/'CodexCapCutBrief'
    return Path.home()/'.cache'/'codex-capcut-brief'


def cache_roots():
    home = Path.home()
    bases = [Path(os.environ.get('LOCALAPPDATA', home/'AppData'/'Local'))/'CapCut'/'User Data',
             home/'Library'/'Application Support'/'CapCut'/'User Data',
             home/'Movies'/'CapCut'/'User Data',
             home/'Library'/'Containers'/'com.lemon.lvoverseas'/'Data'/'Movies'/'CapCut'/'User Data']
    return sorted({(b/'Cache'/name).resolve() for b in bases for name in ('effect', 'artistEffect')
                   if (b/'Cache'/name).is_dir()}, key=str)


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (ValueError, OSError) as exc:
        raise ValueError('Saved library is unreadable; run workflow.py setup --refresh: '+str(exc)) from exc


def _summary(catalog):
    entries = catalog['entries']
    catalog['summary'].update(entries=len(entries), categories={c: sum(e['category'] == c for e in entries) for c in scan.CATEGORIES},
                              available=sum(e.get('available') is True for e in entries),
                              supported=sum(e.get('supported') is True for e in entries),
                              missing_resource_entries=sum(bool(e.get('missing_paths')) for e in entries))


def _write_setup(root, catalog, mode, warnings=None):
    queue = jobs(catalog)
    atomic_json(root/'preview-jobs.json', queue)
    status = {'schema': 'capcut-library-setup/1', 'status': 'ready', 'machine_id': catalog['machine_id'],
              'library': str((root/'library.json').resolve()), 'initialized_at': datetime.now(timezone.utc).isoformat(),
              'mode': mode, 'summary': catalog['summary'], 'previews_pending': queue['pending'],
              'preview_jobs': str((root/'preview-jobs.json').resolve()), 'warnings': warnings or []}
    atomic_json(root/'setup.json', status)
    return status


def load_or_setup(state_dir=None, roots=None, refresh=False, caches=None):
    """Return (catalog, path, setup status); no project/cache discovery on reuse.

    A foreign-machine library triggers local initialization. A damaged local
    library requires explicit refresh instead of silently rescanning each edit.
    """
    root = Path(state_dir or default_state()).expanduser().resolve()
    path = root/'library.json'
    foreign = False
    if path.exists() and refresh and roots is None:
        try:
            old = _read(path)
        except ValueError:
            old = {}
        if isinstance(old, dict) and isinstance(old.get('roots'), list) and old.get('machine_id') == scan.machine_identity(old['roots']):
            roots = old['roots']
    if path.exists() and not refresh:
        catalog = _read(path)
        if not isinstance(catalog, dict) or catalog.get('schema') != scan.SCHEMA or not isinstance(catalog.get('entries'), list) or not isinstance(catalog.get('roots'), list):
            raise ValueError('Saved library has invalid schema; run workflow.py setup --refresh')
        foreign = catalog.get('machine_id') != scan.machine_identity(catalog['roots'])
        if not foreign and catalog.get('summary', {}).get('projects_scanned', 0) > 0:
            if roots is not None and scan._normalize_roots(roots) != scan._normalize_roots(catalog['roots']):
                raise ValueError('Project roots changed; use workflow.py setup --refresh --root PATH')
            status_path = root/'setup.json'
            if status_path.exists():
                try:
                    status = _read(status_path)
                except ValueError:
                    status = {}
                if (isinstance(status, dict) and status.get('schema') == 'capcut-library-setup/1'
                        and status.get('machine_id') == catalog['machine_id']
                        and 'previews_pending' in status and status.get('preview_jobs')
                        and Path(status['preview_jobs']).is_file()):
                    return catalog, path, {**status, 'mode': 'reused'}
            # Adopt libraries created by older versions without another scan.
            return catalog, path, _write_setup(root, catalog, 'adopted')
    root.mkdir(parents=True, exist_ok=True)
    previous_library = path.read_bytes() if path.exists() else None
    lock = root/'setup.lock'
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError('Library setup is already running (setup.lock); wait for it to finish') from exc
    try:
        os.close(descriptor)
        current_machine = scan.machine_identity(roots if roots is not None else scan.discover_roots())
        # Keep foreign registry files recoverable, never mix them with this machine.
        for name in ('native-catalog.json', 'native-previews.json'):
            registry = root/name
            if registry.exists():
                data = _read(registry)
                machines = [data.get('machine_id')] if name == 'native-catalog.json' else [r.get('machine_id') for r in data.values()]
                if any(m and m != current_machine for m in machines):
                    registry.rename(root/(name+'.foreign-'+datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')+'.bak'))
        catalog, path = scan.ensure_library(root, roots)
        if not catalog['summary']['projects_scanned']:
            atomic_json(root/'setup-error.json', {'status': 'needs_projects', 'summary': catalog['summary'], 'errors': catalog['errors']})
            raise ValueError('No readable CapCut projects found; run workflow.py setup --refresh --root PATH')
        warnings = list(catalog.get('errors', []))
        available_caches = cache_roots() if caches is None else caches
        if available_caches:
            try:
                from cache_catalog import scan as scan_cache
                coverage = scan_cache(path, root, available_caches)
                atomic_json(root/'cache-coverage.json', coverage)
                warnings.extend(coverage.get('errors', []))
                merge(catalog, root)
            except ImportError:
                warnings.append({'code': 'preview_dependency_missing', 'error': 'Install Pillow to collect cache previews; then setup --refresh'})
        _summary(catalog)
        atomic_json(path, catalog)
        return catalog, path, _write_setup(root, catalog, 'refreshed' if refresh else 'initialized', warnings)
    except Exception:
        if previous_library is not None:
            # A failed refresh must not replace an installed library with an empty scan.
            try:
                previous = json.loads(previous_library.decode('utf-8-sig'))
            except ValueError:
                previous = None
            if previous is not None:
                atomic_json(path, previous)
        raise
    finally:
        lock.unlink()
