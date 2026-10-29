import copy
import json
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import selection_request as R
import selection_plan as P
import selection_session as S
import capcut_native as C
import test_effect_picker as F


class TextGroupTests(unittest.TestCase):
    def setUp(self):
        self.fixture=F.EffectPickerTests();self.fixture.setUp()
        self.request=copy.deepcopy(self.fixture.request)
        self.plan=copy.deepcopy(self.fixture.plan)
        self.plan['segments'][0]['text']='BA CÓ'
        body=copy.deepcopy(self.plan['segments'][0]);body.update(text='Có kỷ luật',start=.5,duration=2.5)
        self.plan['segments'].append(body)
        self.groups=[{'id':'main','text_group':'main','segment_indices':[0]},
                     {'id':'support','text_group':'support','segment_indices':[1]}]

    def tearDown(self):self.fixture.tearDown()

    def test_two_groups_keep_independent_choices_through_native_compilation(self):
        request,plan=P.split_text_slot(self.request,self.plan,'f1.text1',self.groups)
        request=R.effect_sticker_request(request)
        # The normalizer offers an optional sticker; absence is an opt-in skip.
        self.assertEqual(['Main Text','Supporting Text'],[s['label'] for s in request['frames'][0]['slots'][:2]])
        library=copy.deepcopy(self.fixture.library)
        gentle=copy.deepcopy(self.fixture.effect);gentle['key']='gentle'
        gentle['effect_recipe']['effects'][0]['resource_id']='gentle-effect'
        gentle['effect_recipe']['style_overrides'][0]['effectStyle']['id']='gentle-effect'
        library['entries'].append(gentle)
        choices={'main':{'effect':'effect'},'support':{'effect':'gentle'}}
        session=S.confirm_session(request,library,choices)
        selected=P.assemble_plan(plan,request,library,session)
        draft,_=C.compile_plan(selected,self.fixture.base,library)
        actual={json.loads(t['content'])['text']:json.loads(t['content'])['styles'][0]['effectStyle']['id']
                for t in draft['materials']['texts']}
        self.assertEqual({'BA CÓ':'external-effect','Có kỷ luật':'gentle-effect'},actual)
        self.assertEqual(['f1.text1','f1.text1'],[s['slot_id'] for s in self.plan['segments']])

    def test_split_requires_every_segment_once_and_preserves_timings(self):
        for groups in ([self.groups[0]], [self.groups[0],dict(self.groups[1],segment_indices=[0,1])]):
            with self.assertRaises(ValueError):P.split_text_slot(self.request,self.plan,'f1.text1',groups)
        _,plan=P.split_text_slot(self.request,self.plan,'f1.text1',self.groups)
        self.assertEqual([(0,3),(.5,2.5)],[(s['start'],s['duration']) for s in plan['segments']])

    def test_missing_supporting_choice_is_a_draft_and_cannot_confirm(self):
        request,_=P.split_text_slot(self.request,self.plan,'f1.text1',self.groups)
        choices={'main':{'effect':'effect'}}
        self.assertEqual([],S.validate_draft_choices(request,self.fixture.library,choices))
        self.assertTrue(S.validate_choices(request,self.fixture.library,choices))
        with self.assertRaises(ValueError):S.confirm_session(request,self.fixture.library,choices)

    def test_structured_brief_keeps_main_and_support_instead_of_combining(self):
        request=R.make_request({'frames':[{'frame':1,'text_groups':[
            {'role':'main','text':'BA CÓ'}, {'role':'support','text':'Có kỷ luật\nCó trách nhiệm'}]}]})
        texts=[s for s in request['frames'][0]['slots'] if s['role']=='text']
        self.assertEqual(['main','support'],[s['text_group'] for s in texts])
        self.assertEqual(['BA CÓ','Có kỷ luật\nCó trách nhiệm'],[s['text'] for s in texts])


if __name__=='__main__':unittest.main()
