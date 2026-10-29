import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import native_previews as P


class NativePreviewTests(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.image = self.root / 'capture.png'
        Image.new('RGB', (100, 100), 'red').save(self.image)
        self.entry = {'key': 'text_animation-a', 'category': 'text_animation', 'name': 'Fade',
                      'project': 'donor.json', 'segment': {'id': 's1', 'target_timerange': {'start': 200, 'duration': 300}},
                      'materials': {}, 'available': True, 'supported': True, 'preview_files': []}
        self.catalog = {'machine_id': 'local', 'entries': [self.entry]}
        self.library = self.root / 'library.json'
        P.save(self.library, self.catalog)
        self.evidence = self.root / 'evidence.json'
        P.save(self.evidence, {'asset_key': self.entry['key'], 'fingerprint': P.fingerprint(self.entry),
                              'method': 'capcut_ui_capture', 'scope': 'project_context', 'app_version': '9.7',
                              'project': 'donor.json', 'segment_id': 's1'})

    def test_queue_retains_motion_jobs_after_static_native_capture(self):
        record = P.attach(self.library, self.root, self.entry['key'], self.image, self.evidence)
        self.assertFalse(record['motion'])
        P.merge(self.catalog, self.root)
        self.assertEqual('capcut_project_context', self.entry['preview_kind'])
        self.assertEqual(1, P.jobs(self.catalog)['pending'])
        self.assertNotIn('capcut_verified', self.entry)

    def test_motion_capture_completes_animation_job_and_persists(self):
        from PIL import Image
        media = self.root / 'motion.gif'
        Image.new('RGB', (30, 30), 'red').save(media, save_all=True,
            append_images=[Image.new('RGB', (30, 30), 'blue')], duration=150, loop=0)
        record = P.attach(self.library, self.root, self.entry['key'], media, self.evidence)
        self.assertTrue(record['motion'])
        P.merge(self.catalog, self.root)
        self.assertEqual(0, P.jobs(self.catalog)['pending'])

    def test_stale_donor_foreign_machine_and_tampered_media_are_not_applied(self):
        record = P.attach(self.library, self.root, self.entry['key'], self.image, self.evidence)
        for field, value in [('machine_id', 'foreign'), ('segment', {'id': 'changed'})]:
            cat = copy.deepcopy(self.catalog)
            if field == 'machine_id': cat[field] = value
            else: cat['entries'][0][field] = value
            P.merge(cat, self.root)
            self.assertEqual([], cat['entries'][0]['preview_files'])
        Path(record['file']).write_bytes(b'corrupt')
        P.merge(self.catalog, self.root)
        self.assertEqual([], self.entry['preview_files'])

    def test_wrong_asset_or_project_binding_is_rejected(self):
        evidence = P.read(self.evidence)
        evidence['segment_id'] = 'other'
        P.save(self.evidence, evidence)
        with self.assertRaisesRegex(ValueError, 'donor'): P.attach(self.library, self.root, self.entry['key'], self.image, self.evidence)
        evidence['asset_key'] = 'other'
        P.save(self.evidence, evidence)
        with self.assertRaisesRegex(ValueError, 'match'): P.attach(self.library, self.root, self.entry['key'], self.image, self.evidence)

    def test_native_catalog_import_dedups_and_stays_browse_only(self):
        manifest = self.root / 'tiles.json'
        data = {'app_version': '9.7', 'panel': 'Text template',
                'items': [{'label': 'Sample', 'category': 'text_template', 'box': [10, 10, 80, 80]}]}
        P.save(manifest, data)
        for _ in range(2): P.import_catalog(self.library, self.root, self.image, manifest)
        P.merge(self.catalog, self.root)
        self.assertEqual(2, len(self.catalog['entries']))
        added = self.catalog['entries'][-1]
        self.assertFalse(added['supported'])
        self.assertEqual({}, added['materials'])
        self.assertEqual('capcut_catalog_thumbnail', added['preview_kind'])
        self.assertEqual(1, P.jobs(self.catalog)['pending'])
        import library_scan
        with patch.object(library_scan, 'machine_identity', return_value='local'):
            scanned, _ = library_scan.ensure_library(self.root, roots=[])
        self.assertEqual(1, scanned['summary']['entries'])
        self.assertEqual(0, scanned['summary']['missing_resource_entries'])
        data['items'][0]['box'] = [-1, 0, 20, 20]
        P.save(manifest, data)
        with self.assertRaisesRegex(ValueError, 'outside'): P.import_catalog(self.library, self.root, self.image, manifest)


if __name__ == '__main__': unittest.main()
