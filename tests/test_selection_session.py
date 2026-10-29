import copy
import hashlib
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))


def fixtures():
    request = {'schema': 'capcut-selection-request/1', 'id': 'brief-1', 'title': 'Brief',
               'frames': [{'id': 'frame-1', 'dialogue': 'Hello', 'edit_notes': 'Caption and icon', 'slots': [
                   {'id': 'caption', 'role': 'text', 'label': 'Caption', 'required': True,
                    'categories': ['text_style', 'text_effect', 'text_animation', 'text_template']},
                   {'id': 'icon', 'role': 'sticker', 'label': 'Icon', 'required': False, 'categories': ['sticker']},
                   {'id': 'fx', 'role': 'video_effect', 'label': 'Effect', 'required': True, 'categories': ['video_effect']}
               ]}]}
    entries = []
    for key, category in [('style', 'text_style'), ('glow', 'text_effect'), ('intro', 'text_animation'),
                          ('outro', 'text_animation'), ('template', 'text_template'), ('heart', 'sticker'),
                          ('blur', 'video_effect')]:
        entry = {'key': key, 'category': category, 'name': key, 'available': True, 'supported': True,
                 'sources': [], 'preview_files': []}
        if category == 'text_animation':
            entry['animation_type'] = 'in' if key == 'intro' else 'out'
        entries.append(entry)
    library = {'schema': 'capcut-native-library/2', 'machine_id': 'test-machine', 'entries': entries}
    choices = {'caption': {'style': 'style', 'effect': 'glow', 'animations': {'in': 'intro'}},
               'icon': {'skip': True}, 'fx': {'asset': 'blur'}}
    return request, library, choices


class SelectionSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module('selection_session')

    def setUp(self):
        self.request, self.library, self.choices = fixtures()

    def test_new_session_contains_no_default_choices_and_is_pending(self):
        session = self.module.make_session(self.request, self.library)
        self.assertEqual('pending', session['status'])
        self.assertEqual({}, session['choices'])
        self.assertEqual('test-machine', session['machine_id'])

    def test_confirmation_preserves_explicit_human_choices_and_hashes(self):
        session = self.module.confirm_session(self.request, self.library, self.choices, 'a' * 64, 'b' * 64)
        self.assertEqual('confirmed', session['status'])
        self.assertEqual(self.choices, session['choices'])
        self.assertEqual('a' * 64, session['request_hash'])
        self.assertEqual([], self.module.validate_confirmed_session(
            self.request, self.library, session, request_hash='a' * 64, library_hash='b' * 64))

    def test_file_hash_uses_exact_file_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'x.json'
            data = b'{ "x": 1 }\r\n'
            path.write_bytes(data)
            self.assertEqual(hashlib.sha256(data).hexdigest(), self.module.file_hash(path))

    def test_missing_required_and_missing_explicit_optional_decisions_are_rejected(self):
        self.assertTrue(self.module.validate_choices(self.request, self.library, {}))
        del self.choices['icon']
        self.assertTrue(self.module.validate_choices(self.request, self.library, self.choices))

    def test_wrong_category_animation_direction_and_unavailable_assets_are_rejected(self):
        for mutation in ('category', 'animation', 'unavailable', 'unsupported', 'unknown'):
            with self.subTest(mutation=mutation):
                choices = copy.deepcopy(self.choices)
                library = copy.deepcopy(self.library)
                if mutation == 'category': choices['fx']['asset'] = 'heart'
                if mutation == 'animation': choices['caption']['animations']['in'] = 'outro'
                if mutation == 'unavailable': library['entries'][0]['available'] = False
                if mutation == 'unsupported': library['entries'][0]['supported'] = False
                if mutation == 'unknown': choices['fx']['asset'] = 'missing'
                self.assertTrue(self.module.validate_choices(self.request, library, choices))

    def test_required_skip_unknown_fields_and_unknown_slots_are_rejected(self):
        for bad in ({'skip': True}, {'asset': 'blur', 'command': 'edit'}, {'asset': None}):
            choices = copy.deepcopy(self.choices)
            choices['fx'] = bad
            self.assertTrue(self.module.validate_choices(self.request, self.library, choices))
        self.choices['surprise'] = {'asset': 'heart'}
        self.assertTrue(self.module.validate_choices(self.request, self.library, self.choices))

    def test_optional_skip_requires_json_boolean_not_numeric_one(self):
        self.choices['icon'] = {'skip': 1}
        self.assertTrue(self.module.validate_choices(self.request, self.library, self.choices))

    def test_text_requires_baseline_and_template_is_exclusive(self):
        for bad in ({'effect': 'glow'}, {'animations': {'in': 'intro'}},
                    {'template': 'template', 'style': 'style'},
                    {'style': 'style', 'animations': {'spin': 'intro'}}):
            choices = copy.deepcopy(self.choices)
            choices['caption'] = bad
            self.assertTrue(self.module.validate_choices(self.request, self.library, choices))
        self.choices['caption'] = {'template': 'template'}
        self.assertEqual([], self.module.validate_choices(self.request, self.library, self.choices))

    def test_slot_categories_and_role_cannot_be_bypassed(self):
        self.request['frames'][0]['slots'][0]['categories'] = ['text_template']
        self.assertTrue(self.module.validate_choices(self.request, self.library, self.choices))
        self.request['frames'][0]['slots'][0]['categories'] = ['sticker']
        self.assertTrue(self.module.validate_choices(self.request, self.library, self.choices))

    def test_stale_machine_hash_pending_and_duplicate_slot_are_rejected(self):
        confirmed = self.module.confirm_session(self.request, self.library, self.choices, 'a' * 64, 'b' * 64)
        for field, value in [('status', 'pending'), ('machine_id', 'other'), ('request_hash', 'c' * 64),
                             ('library_hash', 'c' * 64)]:
            session = copy.deepcopy(confirmed)
            session[field] = value
            self.assertTrue(self.module.validate_confirmed_session(
                self.request, self.library, session, request_hash='a' * 64, library_hash='b' * 64))
        self.request['frames'][0]['slots'].append(copy.deepcopy(self.request['frames'][0]['slots'][0]))
        with self.assertRaises(ValueError):
            self.module.make_session(self.request, self.library)


if __name__ == '__main__':
    unittest.main()
