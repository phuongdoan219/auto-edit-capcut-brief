import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
try:
    import library_scan as scan
except ImportError:
    scan = None


def write_draft(path, draft):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(draft), encoding='utf-8')


def fixture(cache):
    return {'id': 'draft-1', 'canvas_config': {'width': 1080, 'height': 1920},
        'materials': {
            'texts': [{'id': 'text-1', 'type': 'text', 'font_size': 15,
                'content': json.dumps({'text': 'first', 'styles': [{'range': [0, 5], 'font': {'id': 'font-resource'}, 'fill': {'color': 'red'}, 'effectStyle': {'id': 'flower-resource'}}]}),
                'combo_info': {'text_templates': ['template-1']}}],
            'effects': [{'id': 'effect-1', 'type': 'text_effect', 'resource_id': 'flower-resource', 'name': 'Red glow', 'path': str(cache), 'value': 0.8},
                        {'id': 'adjust-1', 'type': 'brightness', 'resource_id': 'adjust-resource', 'value': 0.3}],
            'text_templates': [{'id': 'template-1', 'type': 'text_template', 'resource_id': 'template-resource', 'text_info_resources': [{'text_material_id': 'text-1', 'extra_material_refs': ['effect-1']}]}],
            'material_animations': [{'id': 'animation-1', 'type': 'sticker_animation', 'animations': [{'id': 'in-resource', 'resource_id': 'in-resource', 'type': 'in', 'name': 'Fade', 'start': 0, 'duration': 300000, 'path': str(cache)}]},
                {'id': 'video-animation', 'animations': [{'id': 'video-only-resource', 'resource_id': 'video-only-resource', 'type': 'out', 'duration': 100}]}],
            'stickers': [{'id': 'sticker-1', 'type': 'sticker', 'resource_id': 'sticker-resource', 'name': 'Arrow', 'path': str(cache)}],
            'video_effects': [{'id': 'video-effect-1', 'type': 'video_effect', 'resource_id': 'snow-resource', 'name': 'Snow', 'path': str(cache), 'adjust_params': [{'name': 'speed', 'value': 0.3}]}],
            'videos': [{'id': 'video-1', 'type': 'video', 'path': '/not/a/host-video.mp4'}]},
        'tracks': [{'type': 'text', 'segments': [{'id': 'text-seg', 'material_id': 'text-1', 'extra_material_refs': ['effect-1', 'animation-1'], 'target_timerange': {'start': 0, 'duration': 1000000}, 'clip': {'scale': {'x': 1, 'y': 1}}}]},
                   {'type': 'sticker', 'segments': [{'id': 'sticker-seg', 'material_id': 'sticker-1'}]},
                   {'type': 'effect', 'segments': [{'id': 'effect-seg', 'material_id': 'video-effect-1', 'render_index': 11000, 'source_timerange': None}]},
                   {'type': 'video', 'segments': [{'id': 'video-seg', 'material_id': 'video-1', 'extra_material_refs': ['video-animation', 'adjust-1']}]}]}


class LibraryScanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root / 'cache'
        self.cache.mkdir()
        (self.cache / 'cover_icon.png').write_bytes(b'png')
        (self.cache / 'final.gif').write_bytes(b'gif')
        self.draft = fixture(self.cache)

    def require_scan(self):
        self.assertIsNotNone(scan, 'library scanner has not been implemented')

    def test_template_preview_does_not_borrow_dependent_effect_icon(self):
        template_cache = self.root / 'template-cache'
        template_cache.mkdir()
        (template_cache / 'config.json').write_text('{}')
        self.draft['materials']['text_templates'][0].update(
            path=str(template_cache), type='text_template_subtitle', name='短文本边框弹出Ⅱ')
        write_draft(self.root / 'drafts' / 'one' / 'draft_content.json', self.draft)
        cat, _ = scan.ensure_library(self.root / 'state', roots=[self.root / 'drafts'])
        template = next(e for e in cat['entries'] if e['category'] == 'text_template')
        self.assertEqual([], template['preview_files'])
        self.assertEqual('subtitle', template['template_kind'])
        self.assertTrue(template['display_name'].startswith('Mẫu phụ đề'))
        self.assertEqual('短文本边框弹出Ⅱ', template['name'])
        (template_cache / 'preview.mp4').write_bytes(b'native preview')
        cat, _ = scan.ensure_library(self.root / 'state', roots=[self.root / 'drafts'])
        template = next(e for e in cat['entries'] if e['category'] == 'text_template')
        self.assertEqual([str(template_cache / 'preview.mp4')], template['preview_files'])

    def test_harvest_six_categories_and_keep_native_recipes(self):
        self.require_scan()
        write_draft(self.root / 'drafts' / 'one' / 'draft_content.json', self.draft)
        catalog, path = scan.ensure_library(self.root / 'state', roots=[self.root / 'drafts'])
        self.assertTrue(path.is_file())
        self.assertEqual({e['category'] for e in catalog['entries']}, {'text_style', 'text_effect', 'text_template', 'text_animation', 'sticker', 'video_effect'})
        by = {e['category']: e for e in catalog['entries']}
        self.assertEqual(by['text_effect']['effect_recipe']['effects'][0]['resource_id'], 'flower-resource')
        self.assertEqual(by['text_template']['materials']['texts'][0]['id'], 'text-1')
        self.assertEqual(by['text_animation']['animation_type'], 'in')
        self.assertEqual(by['video_effect']['application'], 'track')
        self.assertEqual(by['video_effect']['segment']['render_index'], 11000)
        self.assertTrue(by['sticker']['available'])
        self.assertTrue(any(Path(p).name == 'cover_icon.png' for p in by['sticker']['preview_files']))
        self.assertNotIn('video-only-resource', json.dumps(by['text_animation']))

    def test_dedup_ignores_text_local_ids_and_timing_but_keeps_effect_settings(self):
        self.require_scan()
        write_draft(self.root / 'drafts' / 'one' / 'draft_content.json', self.draft)
        other = copy.deepcopy(self.draft)
        other['id'] = 'draft-2'
        text = other['materials']['texts'][0]
        content = json.loads(text['content']); content['text'] = 'a much longer sample'; content['styles'][0]['range'] = [0, 20]; text['content'] = json.dumps(content)
        other['tracks'][0]['segments'][0]['target_timerange'] = {'start': 8000000, 'duration': 3000000}
        other = json.loads(json.dumps(other).replace('text-1', 'text-2').replace('text-seg', 'text-seg-2').replace('effect-1', 'effect-2').replace('template-1', 'template-2'))
        write_draft(self.root / 'drafts' / 'two' / 'draft_content.json', other)
        cat, _ = scan.ensure_library(self.root / 'state', roots=[self.root / 'drafts'])
        styles = [e for e in cat['entries'] if e['category'] == 'text_style']
        self.assertEqual(len(styles), 1)
        self.assertEqual(styles[0]['occurrences'], 2)
        self.assertEqual(len(styles[0]['sources']), 2)
        old_key = next(e['key'] for e in cat['entries'] if e['category'] == 'text_effect')
        other['materials']['effects'][0]['value'] = 0.2
        write_draft(self.root / 'drafts' / 'two' / 'draft_content.json', other)
        cat, _ = scan.ensure_library(self.root / 'state', roots=[self.root / 'drafts'])
        self.assertEqual(len([e for e in cat['entries'] if e['category'] == 'text_effect']), 2)
        self.assertIn(old_key, [e['key'] for e in cat['entries']])

    def test_discover_all_timelines_skip_backups_and_exact_copies_report_errors(self):
        self.require_scan()
        drafts = self.root / 'drafts'
        write_draft(drafts / 'one' / 'draft_content.json', self.draft)
        write_draft(drafts / 'one' / 'Timelines' / 'timeline-two' / 'draft_content.json', {**self.draft, 'id': 'timeline-two'})
        write_draft(drafts / 'copy' / 'draft_content.json', self.draft)
        write_draft(drafts / 'backup' / 'one' / 'draft_content.json', self.draft)
        (drafts / 'encrypted').mkdir(); (drafts / 'encrypted' / 'draft_content.json').write_bytes(b'ENCRYPTED DATA')
        (drafts / 'corrupt').mkdir(); (drafts / 'corrupt' / 'draft_content.json').write_text('{bad')
        cat, _ = scan.ensure_library(self.root / 'state', roots=[drafts, drafts / 'one'])
        self.assertEqual(cat['summary']['projects_scanned'], 2)
        self.assertEqual(cat['summary']['duplicate_timelines'], 1)
        self.assertEqual(cat['summary']['projects_failed'], 2)
        self.assertEqual({e['code'] for e in cat['errors']}, {'encrypted', 'corrupt'})

    def test_machine_identity_and_refresh_do_not_reuse_foreign_catalog(self):
        self.require_scan()
        write_draft(self.root / 'drafts' / 'one' / 'draft_content.json', self.draft)
        cat, path = scan.ensure_library(self.root / 'state', roots=[self.root / 'drafts'])
        original = cat['machine_id']; cat['machine_id'] = 'another-machine'; cat['entries'] = []
        path.write_text(json.dumps(cat))
        cat, _ = scan.ensure_library(self.root / 'state', roots=[self.root / 'drafts'])
        self.assertEqual(cat['machine_id'], original); self.assertEqual(len(cat['entries']), 6)
        (self.cache / 'cover_icon.png').unlink(); (self.cache / 'final.gif').unlink()
        cat, _ = scan.ensure_library(self.root / 'state', roots=[self.root / 'drafts'])
        self.assertFalse(next(e for e in cat['entries'] if e['category'] == 'sticker')['available'])

    def test_discovery_reads_known_metadata_and_explicit_roots(self):
        self.require_scan()
        local = self.root / 'local'; standard = local / 'CapCut' / 'User Data' / 'Projects' / 'com.lveditor.draft'
        moved = self.root / 'moved'; moved.mkdir(); standard.mkdir(parents=True)
        (standard / 'root_meta_info.json').write_text(json.dumps({'root_path': str(moved), 'all_draft_store': []}))
        with patch.dict('os.environ', {'LOCALAPPDATA': str(local)}):
            roots = scan.discover_roots()
        self.assertIn(moved.resolve(), roots); self.assertIn(standard.resolve(), roots)
        self.assertEqual(scan.discover_roots([moved]), [moved.resolve()])

    def test_clip_effect_observed_schema_and_unattached_material_unsupported(self):
        self.require_scan()
        self.draft['tracks'] = [self.draft['tracks'][-1]]
        self.draft['tracks'][0]['segments'][0]['extra_material_refs'].append('video-effect-1')
        write_draft(self.root / 'drafts' / 'one' / 'draft_content.json', self.draft)
        cat, _ = scan.ensure_library(self.root / 'state', roots=[self.root / 'drafts'])
        effect = next(e for e in cat['entries'] if e['category'] == 'video_effect')
        self.assertEqual(effect['application'], 'clip'); self.assertTrue(effect['supported'])
        self.assertTrue(effect['available'], 'host video is not a dependency of reusable effect')
        self.draft['tracks'] = []
        write_draft(self.root / 'drafts' / 'one' / 'draft_content.json', self.draft)
        cat, _ = scan.ensure_library(self.root / 'state', roots=[self.root / 'drafts'])
        effect = next(e for e in cat['entries'] if e['category'] == 'video_effect')
        self.assertFalse(effect['supported']); self.assertIsNone(effect['application'])

    def test_plain_style_has_no_inherited_effect_template_or_animation(self):
        self.require_scan()
        write_draft(self.root / 'drafts' / 'one' / 'draft_content.json', self.draft)
        cat, _ = scan.ensure_library(self.root / 'state', roots=[self.root / 'drafts'])
        style = next(e for e in cat['entries'] if e['category'] == 'text_style')
        self.assertEqual(set(style['materials']), {'texts'})
        self.assertEqual(style['segment']['extra_material_refs'], [])
        self.assertEqual(style['materials']['texts'][0]['combo_info']['text_templates'], [])
        self.assertNotIn('effectStyle', json.loads(style['materials']['texts'][0]['content'])['styles'][0])

    def test_duplicate_sources_are_retained_and_unknown_animation_is_visible(self):
        self.require_scan()
        self.draft['materials']['material_animations'][0]['animations'][0]['type'] = 'caption'
        write_draft(self.root / 'drafts' / 'one' / 'draft_content.json', self.draft)
        write_draft(self.root / 'drafts' / 'copy' / 'draft_content.json', self.draft)
        cat, _ = scan.ensure_library(self.root / 'state', roots=[self.root / 'drafts'])
        animations = [e for e in cat['entries'] if e['category'] == 'text_animation']
        self.assertEqual(len(animations), 1)
        anim = animations[0]
        self.assertEqual(anim['animation_type'], 'caption'); self.assertFalse(anim['supported'])
        self.assertEqual(anim['occurrences'], 1)
        self.assertEqual(len(anim['sources']), 2)

    def test_effect_without_matching_native_style_anchor_is_unsupported(self):
        self.require_scan()
        text = self.draft['materials']['texts'][0]
        content = json.loads(text['content']); content['styles'][0].pop('effectStyle'); text['content'] = json.dumps(content)
        write_draft(self.root / 'drafts' / 'one' / 'draft_content.json', self.draft)
        cat, _ = scan.ensure_library(self.root / 'state', roots=[self.root / 'drafts'])
        effect = next(e for e in cat['entries'] if e['category'] == 'text_effect')
        self.assertFalse(effect['supported'])


if __name__ == '__main__':
    unittest.main()
