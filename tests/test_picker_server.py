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

    def test_scene_preview_is_authenticated_read_only_and_rejects_path_parameters(self):
        from PIL import Image
        from urllib.parse import urlencode
        still=self.directory/'scene.jpg'
        Image.new('RGB',(90,160),'blue').save(still)
        self.server.scene_preview={'canvas':{'width':90,'height':160},'appearance':'approximate_layout',
            'scenes':[{'id':'frame-1','start':0,'end':1,'layers':[],
                       'samples':[{'time':.5,'file':str(still)}]}]}
        query='/api/scene-preview?'+urlencode({'frame':'frame-1','sample':0,'choices':'{}'})
        before=self.session_path.read_bytes()
        self.assertEqual(401,self.call(query,token=False)[0])
        status,body,headers=self.call(query)
        self.assertEqual(200,status)
        self.assertEqual('image/jpeg',headers['Content-Type'])
        self.assertTrue(body.startswith(b'\xff\xd8'))
        self.assertEqual(400,self.call(query+'&path=secret.txt')[0])
        self.assertEqual(422,self.call(query.replace('sample=0','sample=99'))[0])
        self.assertEqual(before,self.session_path.read_bytes())

    def test_previous_confirmed_choices_restore_as_pending_and_never_auto_confirm(self):
        from selection_session import confirm_session
        old=confirm_session(self.request,self.library,self.choices,self.server.request_hash,self.server.library_hash)
        self.module.atomic_json(self.directory/'draft-from-confirmed.json',old)
        server=self.module.create_server(self.request_path,self.library_path,self.directory/'revision.json')
        try:
            self.assertEqual(self.choices,server.initial_choices)
            self.assertEqual('pending',server.session['status'])
            self.assertEqual({},server.session['choices'])
        finally:server.server_close()

    def test_text_split_restores_old_choice_to_main_only_and_keeps_support_pending(self):
        import copy
        import workflow as W
        from selection_session import confirm_session
        saved=confirm_session(self.request,self.library,self.choices,self.server.request_hash,self.server.library_hash)
        self.module.atomic_json(self.session_path,saved)
        source={'request':str(self.request_path),'library':str(self.library_path),'session':str(self.session_path)}
        self.module.atomic_json(self.directory/'workflow.json',source)
        revision=self.directory/'revision';revision.mkdir()
        request=copy.deepcopy(self.request)
        slot=request['frames'][0]['slots'][0];slot.update(id='main',text_group='main')
        support=copy.deepcopy(slot);support.update(id='support',text_group='support')
        request['frames'][0]['slots'].insert(1,support)
        rp=revision/'request.json';self.module.atomic_json(rp,request)
        target={'request':str(rp),'library':str(self.library_path),'session':str(revision/'session.json')}
        self.module.atomic_json(revision/'workflow.json',target)
        result=W.restore_mapped_draft(revision,self.directory,{'caption':'main'},focus_slot='main')
        self.assertIn('support',result['unselected_slots'])
        server=self.module.create_server(rp,self.library_path,revision/'session.json')
        try:
            self.assertEqual(self.choices['caption'],server.initial_choices['main'])
            self.assertNotIn('support',server.initial_choices)
            self.assertEqual('main',server.initial_slot)
            self.assertEqual('pending',server.session['status'])
            self.assertEqual({},server.session['choices'])
        finally:server.server_close()

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

    def test_selectable_only_hides_unusable_items_and_counts_before_pagination(self):
        result=json.loads(self.call('/api/assets?selectable_only=1&page_size=1')[1])
        self.assertEqual(1,result['total'])
        self.assertEqual('style',result['entries'][0]['key'])
        self.server.entries[0]['supported']=False
        self.assertEqual(0,json.loads(self.call('/api/assets?selectable_only=1')[1])['total'])
        self.assertEqual(400,self.call('/api/assets?selectable_only=maybe')[0])

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

    def test_effect_mode_exposes_only_two_categories_and_disables_preview_only_effects(self):
        from selection_request import effect_sticker_request
        request=effect_sticker_request(self.request)
        path=self.directory/'effects-request.json'
        path.write_text(json.dumps(request),encoding='utf-8')
        server=self.module.create_server(path,self.library_path,self.directory/'effects-session.json',port=0)
        try:
            self.assertEqual({'text_effect','sticker'},{e['category']for e in server.entries})
            effect=next(e for e in server.entries if e['category']=='text_effect')
            self.assertFalse(effect['supported']) # fixture has a preview, but no text donor
        finally:server.server_close()

    def test_effect_gallery_hides_missing_and_empty_previews_before_pagination(self):
        from selection_request import effect_sticker_request
        request=effect_sticker_request(self.request)
        effect=next(e for e in self.library['entries'] if e['key']=='glow')
        effect['preview_files']=[str(self.directory/'preview.gif')]
        (self.directory/'empty.png').write_bytes(b'')
        next(e for e in self.library['entries'] if e['key']=='heart')['preview_files']=[str(self.directory/'empty.png')]
        rp=self.directory/'filtered-request.json';lp=self.directory/'filtered-library.json'
        rp.write_text(json.dumps(request),encoding='utf-8');lp.write_text(json.dumps(self.library),encoding='utf-8')
        server=self.module.create_server(rp,lp,self.directory/'filtered-session.json',port=0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def assets():
            req=urllib.request.Request(f'http://127.0.0.1:{server.server_port}/api/assets?page=1&page_size=1',
                headers={'Authorization':'Bearer '+server.token})
            with urllib.request.urlopen(req,timeout=3)as response:return json.load(response)
        try:
            result=assets()
            self.assertEqual(1,result['total'])
            self.assertEqual('glow',result['entries'][0]['key'])
            # A preview can disappear after the server starts.
            (self.directory/'preview.gif').unlink()
            self.assertEqual(0,assets()['total'])
            # Full metadata remains for existing unconfirmed choices.
            self.assertEqual({'glow','heart'},{e['key']for e in server.entries})
        finally:server.shutdown();server.server_close();thread.join(2)


if __name__ == '__main__':
    unittest.main()
