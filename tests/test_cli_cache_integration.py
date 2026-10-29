import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import cache_catalog as C
import capcut_cli_bridge as B
from native_previews import save, read


class CacheIntegrationTests(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root/'cache'; self.cache.mkdir()
        self.state = self.root/'state'
        self.library = self.root/'library.json'; save(self.library, {'machine_id': 'local', 'entries': []})
        buf = io.BytesIO(); Image.new('RGB', (40, 30), 'red').save(buf, format='PNG'); self.png = buf.getvalue()

    def test_cache_scans_all_packages_dedups_zip_and_does_not_misclassify_fonts(self):
        folder = self.cache/'123'/'hash'; folder.mkdir(parents=True)
        config = {'effect': {'Link': [{'type': 'TextStyle'}]}}
        save(folder/'config.json', config); (folder/'cover_icon.png').write_bytes(self.png)
        with zipfile.ZipFile(self.cache/'123'/'download_tmp', 'w') as z:
            z.writestr('config.json', json.dumps(config)); z.writestr('cover_icon.png', self.png)
            z.writestr('../../escape.png', self.png)
        font = self.cache/'456'/'font'; font.mkdir(parents=True)
        save(font/'config.json', {'effect': {'Link': [{'type': 'InfoSticker'}]}})
        (font/'font.ttf').write_bytes(b'font')
        result = C.scan(self.library, self.state, [self.cache])
        self.assertEqual(3, result['counts']['packages_read'])
        self.assertEqual(1, result['unique_native_cache_previews'])
        self.assertEqual([], result['errors'])
        self.assertFalse((self.root/'escape.png').exists())
        entries = read(self.state/'native-catalog.json')['entries']
        self.assertEqual(1, len(entries)); self.assertFalse(entries[0]['supported'])
        self.assertEqual('text_effect', entries[0]['category'])
        self.assertEqual(hashlib.sha256(self.png).hexdigest(), entries[0]['preview_evidence']['sha256'])

    def test_lookup_direction_and_namespace_are_not_guessed(self):
        results = B.lookup('fade-in', 'text_animation')
        self.assertTrue(results)
        self.assertTrue(any(e['animation_type'] == 'in' for e in results))
        self.assertEqual([], B.lookup('nonexistent-resource-xyz'))

    def test_audit_argv_is_read_only_and_findings_do_not_become_render_verification(self):
        entry = self.root/'index.js'; entry.write_text('')
        project = self.root/'draft'; project.mkdir()
        response = type('Response', (), {'returncode': 1, 'stdout': '{"ok":false,"issues":["missing media"]}', 'stderr': ''})()
        with patch.object(B.subprocess, 'run', return_value=response) as run:
            report = B.audit(entry, project, self.root/'report.json')
        self.assertEqual(['info', 'lint'], [call.args[0][2] for call in run.call_args_list])
        self.assertTrue(all(call.kwargs['shell'] is False for call in run.call_args_list))
        self.assertFalse(report['capcut_render_verified'])
        self.assertEqual(1, report['commands']['lint']['exit_code'])


if __name__ == '__main__': unittest.main()
