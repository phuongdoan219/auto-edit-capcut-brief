import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL/'scripts'))
import library_setup as L
import library_scan
import workflow
from test_library_scan import fixture, write_draft
from test_selection_session import fixtures


class LibrarySetupTests(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root/'state'; self.drafts = self.root/'drafts'
        self.cache = self.root/'cache'
        owner = self.cache/'123'/'hash'; owner.mkdir(parents=True)
        Image.new('RGB', (30, 30), 'red').save(owner/'cover_icon.png')
        (owner/'config.json').write_text(json.dumps({'effect': {'Link': [{'type': 'TextStyle'}]}}))
        self.draft = fixture(owner)
        write_draft(self.drafts/'one'/'draft_content.json', self.draft)

    def setup(self, **kwargs):
        return L.load_or_setup(self.state, [self.drafts], caches=[self.cache], **kwargs)

    def test_first_setup_collects_projects_and_cache_then_edits_never_rescan(self):
        catalog, path, status = self.setup()
        self.assertEqual('initialized', status['mode'])
        self.assertTrue(any(e.get('source_type') == 'native_cache' for e in catalog['entries']))
        self.assertTrue((self.state/'setup.json').is_file())
        self.assertTrue(Path(status['preview_jobs']).is_file())
        original = path.read_bytes()
        other = copy.deepcopy(self.draft); other['id'] = 'new-project'
        write_draft(self.drafts/'two'/'draft_content.json', other)
        with patch.object(library_scan, 'ensure_library', side_effect=AssertionError('rescanned')), \
             patch.object(library_scan, 'discover_roots', side_effect=AssertionError('discovered')), \
             patch.object(L, 'cache_roots', side_effect=AssertionError('cache discovery')):
            again, _, reused = self.setup()
        self.assertEqual('reused', reused['mode'])
        self.assertEqual(catalog, again)
        self.assertEqual(original, path.read_bytes())
        self.assertEqual(1, again['summary']['projects_scanned'])

    def test_explicit_refresh_picks_up_new_projects_and_keeps_custom_roots(self):
        self.setup()
        other = copy.deepcopy(self.draft); other['id'] = 'new-project'
        write_draft(self.drafts/'two'/'draft_content.json', other)
        catalog, _, result = L.load_or_setup(self.state, refresh=True, caches=[self.cache])
        self.assertEqual('refreshed', result['mode'])
        self.assertEqual(2, catalog['summary']['projects_scanned'])
        self.assertEqual([str(self.drafts.resolve())], catalog['roots'])

    def test_legacy_library_is_adopted_without_scanning_again(self):
        library_scan.ensure_library(self.state, [self.drafts])
        with patch.object(library_scan, 'ensure_library', side_effect=AssertionError('rescanned')):
            _, _, status = self.setup()
        self.assertEqual('adopted', status['mode'])

    def test_foreign_machine_library_and_registry_are_rebuilt_locally(self):
        self.setup()
        path = self.state/'library.json'; catalog = json.loads(path.read_text())
        catalog['machine_id'] = 'foreign'; path.write_text(json.dumps(catalog))
        registry = self.state/'native-catalog.json'; data = json.loads(registry.read_text())
        data['machine_id'] = 'foreign'; registry.write_text(json.dumps(data))
        refreshed, _, status = self.setup()
        self.assertNotEqual('foreign', refreshed['machine_id'])
        self.assertEqual('initialized', status['mode'])
        self.assertEqual(1, len(list(self.state.glob('native-catalog.json.foreign-*.bak'))))

    def test_invalid_local_library_requires_explicit_refresh_and_can_be_repaired(self):
        self.setup()
        (self.state/'library.json').write_text('broken json')
        with patch.object(library_scan, 'ensure_library', side_effect=AssertionError('rescanned')):
            with self.assertRaisesRegex(ValueError, '--refresh'): self.setup()
        repaired, _, _ = self.setup(refresh=True)
        self.assertTrue(repaired['entries'])

    def test_missing_projects_never_mark_setup_ready(self):
        empty = self.root/'empty-state'
        with self.assertRaisesRegex(ValueError, 'No readable'):
            L.load_or_setup(empty, [self.root/'missing-drafts'], caches=[])
        self.assertFalse((empty/'setup.json').exists())
        self.assertTrue((empty/'setup-error.json').exists())
        self.assertFalse((empty/'setup.lock').exists())

    def test_prepare_uses_installed_library_and_refresh_does_not_mutate_old_session(self):
        self.setup()
        request, _, _ = fixtures(); request['semantic_review_required'] = False
        rp = self.root/'request.json'; rp.write_text(json.dumps(request))
        old = workflow.prepare(rp, self.root/'video1', self.state)
        pinned = Path(old['library']).read_bytes()
        with patch.object(library_scan, 'ensure_library', side_effect=AssertionError('rescanned')):
            new = workflow.prepare(rp, self.root/'video2', self.state)
        self.assertEqual('reused', new['library_mode'])
        self.assertEqual(pinned, Path(new['library']).read_bytes())
        other = copy.deepcopy(self.draft); other['id'] = 'new-project'
        write_draft(self.drafts/'two'/'draft_content.json', other)
        self.setup(refresh=True)
        self.assertEqual(pinned, Path(old['library']).read_bytes())

    def test_setup_lock_prevents_parallel_scan_and_is_not_stolen(self):
        self.state.mkdir(); (self.state/'setup.lock').write_text('running')
        with patch.object(library_scan, 'ensure_library', side_effect=AssertionError('rescanned')):
            with self.assertRaisesRegex(ValueError, 'already running'): self.setup()
        self.assertTrue((self.state/'setup.lock').exists())

    def test_manual_install_first_prepare_initializes_without_a_separate_setup_command(self):
        request, _, _ = fixtures(); request['semantic_review_required'] = False
        rp = self.root/'request.json'; rp.write_text(json.dumps(request))
        with patch.object(L, 'cache_roots', return_value=[self.cache]):
            result = workflow.prepare(rp, self.root/'video', self.state, roots=[self.drafts])
        self.assertEqual('initialized', result['library_mode'])
        self.assertTrue((self.state/'setup.json').is_file())

    def test_corrupt_setup_marker_is_repaired_without_rescanning_valid_library(self):
        self.setup()
        (self.state/'setup.json').write_text('broken marker')
        with patch.object(library_scan, 'ensure_library', side_effect=AssertionError('rescanned')):
            _, _, status = self.setup()
        self.assertEqual('adopted', status['mode'])

    def test_failed_refresh_preserves_the_previous_installed_library(self):
        catalog, path, _ = self.setup()
        def failed_scan(state_dir, roots):
            broken = copy.deepcopy(catalog); broken['summary']['projects_scanned'] = 0
            path.write_text(json.dumps(broken))
            return broken, path
        with patch.object(library_scan, 'ensure_library', side_effect=failed_scan):
            with self.assertRaisesRegex(ValueError, 'No readable'): self.setup(refresh=True)
        self.assertEqual(catalog, json.loads(path.read_text()))
        self.assertEqual('reused', self.setup()[2]['mode'])

    def test_mac_container_project_root_is_discovered_on_first_setup(self):
        user_data = self.root/'Library'/'Containers'/'com.lemon.lvoverseas'/'Data'/'Movies'/'CapCut'/'User Data'
        expected = user_data/'Projects'/'com.lveditor.draft'; expected.mkdir(parents=True)
        with patch.object(Path, 'home', return_value=self.root):
            roots = library_scan.discover_roots()
        self.assertIn(expected.resolve(), roots)

    def test_installer_copies_skill_and_creates_library_during_install(self):
        spec = importlib.util.spec_from_file_location('capcut_skill_installer', SKILL/'install.py')
        installer = importlib.util.module_from_spec(spec); spec.loader.exec_module(installer)
        target = self.root/'installed-skill'
        result = installer.install(target, self.state, [self.drafts], caches=[])
        self.assertTrue((target/'SKILL.md').is_file())
        self.assertTrue((target/'scripts'/'library_setup.py').is_file())
        self.assertFalse((target/'.git').exists())
        self.assertTrue((self.state/'library.json').is_file())
        self.assertEqual('initialized', result['mode'])


if __name__ == '__main__': unittest.main()
