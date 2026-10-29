import importlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from test_selection_session import fixtures


class PickerServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module('picker_server')

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.request, self.library, self.choices = fixtures()
        (self.directory / 'preview.gif').write_bytes(b'GIF89a')
        (self.directory / 'secret.txt').write_text('not exposed')
        self.library['entries'][0]['preview_files'] = [str(self.directory / 'preview.gif'),
            'https://example.invalid/steal-token.png', '//example.invalid/remote.png']
        self.request_path = self.directory / 'request.json'
        self.library_path = self.directory / 'library.json'
        self.session_path = self.directory / 'session.json'
        self.request_path.write_text(json.dumps(self.request), encoding='utf-8')
        self.library_path.write_text(json.dumps(self.library), encoding='utf-8')
        self.server = self.module.create_server(self.request_path, self.library_path, self.session_path, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.temporary.cleanup()

    def call(self, path, data=None, token=True, origin=True):
        headers = {}
        if token: headers['Authorization'] = 'Bearer ' + self.server.token
        if data is not None:
            headers['Content-Type'] = 'application/json'
            if origin: headers['Origin'] = self.origin
        request = urllib.request.Request(self.origin + path,
            data=None if data is None else json.dumps(data).encode(), headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return response.status, response.read(), response.headers
        except urllib.error.HTTPError as error:
            return error.code, error.read(), error.headers

    def payload(self):
        return {'choices': self.choices, 'request_hash': self.server.request_hash,
                'library_hash': self.server.library_hash}

    def test_real_http_confirmation_roundtrip_and_pending_until_confirm(self):
        self.assertEqual('pending', json.loads(self.session_path.read_text())['status'])
        status, body, headers = self.call('/api/state')
        self.assertEqual(200, status)
        state = json.loads(body)
        self.assertEqual('frame-1', state['request']['frames'][0]['id'])
        self.assertEqual({}, state['session']['choices'])
        status, body, _ = self.call('/api/confirm', self.payload())
        self.assertEqual(200, status, body)
        saved = json.loads(self.session_path.read_text())
        self.assertEqual('confirmed', saved['status'])
        self.assertEqual(self.choices, saved['choices'])

    def test_auth_origin_body_limit_and_invalid_choice_never_confirm(self):
        self.assertEqual(401, self.call('/api/state', token=False)[0])
        self.assertEqual(403, self.call('/api/confirm', self.payload(), origin=False)[0])
        payload = self.payload()
        payload['choices'] = {}
        self.assertEqual(422, self.call('/api/confirm', payload)[0])
        self.assertEqual(413, self.call('/api/confirm', {'padding': 'x' * (1024 * 1024 + 1)})[0])
        self.assertEqual('pending', json.loads(self.session_path.read_text())['status'])

    def test_early_rejections_return_errors_after_bounded_body_discard(self):
        for _ in range(8):
            payload = {'padding': 'x' * 65536}
            self.assertEqual(401, self.call('/api/confirm', payload, token=False)[0])
            self.assertEqual(403, self.call('/api/confirm', payload, origin=False)[0])
        self.assertEqual('pending', json.loads(self.session_path.read_text())['status'])

    def test_preview_is_authenticated_allowlisted_and_not_arbitrary_file_read(self):
        state = json.loads(self.call('/api/state')[1])
        self.assertEqual(1, len(state['library']['entries'][0]['previews']))
        preview = state['library']['entries'][0]['previews'][0]['url']
        self.assertTrue(preview.startswith('/api/media/'))
        self.assertEqual(401, self.call(preview, token=False)[0])
        status, body, headers = self.call(preview)
        self.assertEqual(200, status)
        self.assertEqual(b'GIF89a', body)
        self.assertEqual('image/gif', headers['Content-Type'])
        self.assertEqual(404, self.call('/api/media/../../secret.txt')[0])
        self.assertEqual(404, self.call('/secret.txt')[0])
        self.assertEqual(404, self.call('/api/media/0?path=secret.txt')[0])

    def test_all_assets_are_paginated_searchable_and_filterable(self):
        status, body, _ = self.call('/api/assets?category=text_animation&query=int&page=1&page_size=1')
        self.assertEqual(200, status)
        result = json.loads(body)
        self.assertEqual(1, result['total'])
        self.assertEqual('intro', result['entries'][0]['key'])
        self.assertEqual(7, json.loads(self.call('/api/assets')[1])['total'])

    def test_file_change_stale_hash_and_duplicate_confirm_are_rejected(self):
        stale = self.payload()
        stale['library_hash'] = '0' * 64
        self.assertEqual(409, self.call('/api/confirm', stale)[0])
        self.request_path.write_text(json.dumps(self.request) + '\n')
        self.assertEqual(409, self.call('/api/confirm', self.payload())[0])
        self.assertEqual('pending', json.loads(self.session_path.read_text())['status'])

    def test_deleted_selected_native_resource_is_rechecked_at_confirmation(self):
        native = self.directory / 'native-resource.bin'
        native.write_bytes(b'native')
        self.server.library['entries'][0]['resource_paths'] = [str(native)]
        native.unlink()
        status, body, _ = self.call('/api/confirm', self.payload())
        self.assertEqual(422, status, body)
        self.assertEqual('pending', json.loads(self.session_path.read_text())['status'])

    def test_static_ui_is_served_with_restrictive_csp_and_localhost_binding(self):
        status, body, headers = self.call('/')
        self.assertEqual(200, status)
        self.assertIn('text/html', headers['Content-Type'])
        self.assertIn("default-src 'none'", headers['Content-Security-Policy'])
        self.assertEqual('127.0.0.1', self.server.server_address[0])


if __name__ == '__main__':
    unittest.main()
