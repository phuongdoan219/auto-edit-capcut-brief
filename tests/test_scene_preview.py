import copy
from io import BytesIO
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import scene_preview as P
import workflow as W
from PIL import Image, ImageFont


class ScenePreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.background = self.root / 'frame.jpg'
        Image.new('RGB', (270, 480), '#334455').save(self.background)
        for face in ('arial.ttf', 'DejaVuSans.ttf'):
            try:
                self.font = ImageFont.truetype(face, 20).path
                break
            except OSError:
                pass
        else:
            self.skipTest('No test font available')
        self.request = {'frames': [{'id': 'f', 'slots': [
            {'id': 'text', 'role': 'text', 'required': True},
            {'id': 'sticker', 'role': 'sticker', 'required': False, 'opt_in': True}]}]}
        text = {'id': 't', 'content': json.dumps({'text': 'old', 'styles': [{'size': 22}]}),
                'font_path': self.font, 'text_color': '#ffffff'}
        self.effect = {'key': 'effect', 'category': 'text_effect', 'kind': 'text', 'available': True,
                       'supported': True, 'segment': {'material_id': 't', 'clip': {}},
                       'materials': {'texts': [text]}, 'effect_recipe': {'effects': [{'id': 'e'}], 'style_overrides': [{}]}}
        self.library = {'entries': [self.effect]}
        self.layers = [{'kind': 'text', 'slot_id': 'text', 'text': 'Xin chào', 'start': 1, 'duration': 1,
                        'transform': {'transform': {'x': 0, 'y': -.5}}},
                       {'kind': 'sticker', 'slot_id': 'sticker', 'start': 0, 'duration': 2}]
        self.data = {'canvas': {'width': 270, 'height': 480}, 'appearance': 'approximate_layout',
                     'scenes': [{'id': 'f', 'start': 0, 'end': 2, 'samples': [
                         {'time': .5, 'file': str(self.background)}, {'time': 1.5, 'file': str(self.background)}],
                         'layers': self.layers}]}

    def tearDown(self):
        self.tmp.cleanup()

    def test_preview_uses_real_frame_and_text_only_when_active_without_writing(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        blank, _ = P.render(self.data, self.request, self.library, 'f', 1, {})
        early, _ = P.render(self.data, self.request, self.library, 'f', 0, {'text': {'effect': 'effect'}})
        selected, warnings = P.render(self.data, self.request, self.library, 'f', 1, {'text': {'effect': 'effect'}})
        self.assertEqual(blank, early)
        self.assertNotEqual(blank, selected)
        self.assertEqual((270, 480), Image.open(BytesIO(selected)).size)
        self.assertTrue(warnings)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_preview_rejects_other_scene_unknown_asset_wrong_category_and_sample(self):
        for choices in ({'other': {'effect': 'effect'}}, {'text': {'effect': 'unknown'}},
                        {'sticker': {'asset': 'effect'}}, {'text': {'effect': ['effect']}}):
            with self.subTest(choices=choices), self.assertRaises((ValueError, TypeError)):
                P.render(self.data, self.request, self.library, 'f', 0, choices)
        with self.assertRaises(ValueError):
            P.render(self.data, self.request, self.library, 'f', 99, {})

    def test_optional_sticker_is_absent_until_selected_and_uses_own_image(self):
        icon = self.root / 'icon.png'
        Image.new('RGBA', (50, 50), '#ff0000').save(icon)
        self.library['entries'].append({'key': 'icon', 'category': 'sticker', 'available': True,
                                       'supported': True, 'preview_files': [str(icon)]})
        blank, _ = P.render(self.data, self.request, self.library, 'f', 0, {})
        skipped, _ = P.render(self.data, self.request, self.library, 'f', 0, {'sticker': {'skip': True}})
        selected, _ = P.render(self.data, self.request, self.library, 'f', 0, {'sticker': {'asset': 'icon'}})
        self.assertEqual(blank, skipped)
        self.assertNotEqual(blank, selected)

    def test_launch_requires_step_one_and_never_starts_popup_early(self):
        (self.root / 'request.json').write_text(json.dumps({'selection_mode': 'effects_stickers'}))
        (self.root / 'workflow.json').write_text(json.dumps({'request': str(self.root/'request.json'),
                                                           'service': str(self.root/'service.json')}))
        with patch.object(W.subprocess, 'Popen') as child, self.assertRaisesRegex(ValueError, 'Step 1'):
            W.launch(self.root, no_open=True)
        child.assert_not_called()

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_prepare_extracts_actual_timing_and_rejects_stale_plan(self):
        video = self.root / 'roughcut.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        'color=c=blue:s=270x480:r=10:d=2', '-c:v', 'libx264', str(video)],
                       check=True, capture_output=True)
        plan = {'canvas': {'width': 270, 'height': 480}, 'segments': [
            {'kind': 'video', 'frame': 1, 'start': 0, 'duration': 2}, *self.layers]}
        for name, obj in [('request', self.request), ('plan', plan)]:
            (self.root / (name+'.json')).write_text(json.dumps(obj))
        (self.root/'workflow.json').write_text(json.dumps({'request': str(self.root/'request.json'),
                                                         'plan': str(self.root/'plan.json'), 'status': 'ready'}))
        result = P.prepare(self.root, video)
        self.assertEqual(1, result['scenes'])
        data = P.load(self.root, P.file_hash(self.root/'request.json'))
        self.assertTrue(any(s['time'] < 1 for s in data['scenes'][0]['samples']))
        self.assertTrue(any(s['time'] > 1 for s in data['scenes'][0]['samples']))
        self.assertNotIn('file', P.metadata(data)['scenes'][0]['samples'][0])
        (self.root/'plan.json').write_text(json.dumps(plan)+'\n')
        with self.assertRaisesRegex(ValueError, 'plan changed'):
            P.load(self.root, P.file_hash(self.root/'request.json'))


if __name__ == '__main__':
    unittest.main()
