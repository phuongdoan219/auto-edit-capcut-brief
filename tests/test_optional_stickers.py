import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import selection_request as R
import selection_session as S
import selection_plan as A
from test_selection_session import fixtures

class OptionalStickerTests(unittest.TestCase):
    def setUp(self):
        _,self.library,_=fixtures()
        self.request={'schema':S.REQUEST_SCHEMA,'id':'opt-in','selection_mode':'effects_stickers',
          'frames':[{'id':'frame-1','dialogue':'Keep voice','slots':[{
           'id':'frame-1.sticker','role':'sticker','label':'Sticker','required':False,'opt_in':True,'categories':['sticker']}]}]}
        self.plan={'duration':3,'fps':30,'segments':[{'kind':'video','frame':1,'file':'source.mp4','start':0,'duration':3,'layer':0}]}
    def test_empty_optional_sticker_does_not_require_a_choice_or_skip(self):
        self.assertEqual([],S.validate_choices(self.request,self.library,{}))
        session=S.confirm_session(self.request,self.library,{})
        self.assertEqual({},session['choices'])
        pending=A.with_optional_sticker_placements(self.plan,self.request)
        built=A.assemble_plan(pending,self.request,self.library,session)
        self.assertEqual(self.plan['segments'],built['segments'])
    def test_chosen_sticker_is_placed_and_compiles_into_the_plan(self):
        pending=A.with_optional_sticker_placements(self.plan,self.request)
        self.assertEqual(1,len(self.plan['segments'])) # do not mutate the input
        session=S.confirm_session(self.request,self.library,{'frame-1.sticker':{'asset':'heart'}})
        result=A.assemble_plan(pending,self.request,self.library,session)
        sticker=result['segments'][-1]
        self.assertEqual(('sticker','heart',1,0,3),(sticker['kind'],sticker['asset'],sticker['frame'],sticker['start'],sticker['duration']))
        self.assertGreater(sticker['layer'],0)
    def test_required_or_text_slots_cannot_opt_out_of_validation(self):
        for change in [{'required':True},{'role':'text','categories':['text_effect']},{'opt_in':'yes'}]:
            request=copy.deepcopy(self.request);request['frames'][0]['slots'][0].update(change)
            self.assertTrue(S.validate_choices(request,self.library,{}))
    def test_selected_sticker_without_a_known_scene_placement_is_rejected(self):
        pending=A.with_optional_sticker_placements({**self.plan,'segments':[]},self.request)
        session=S.confirm_session(self.request,self.library,{'frame-1.sticker':{'asset':'heart'}})
        with self.assertRaisesRegex(ValueError,'placement'):A.assemble_plan(pending,self.request,self.library,session)
    def test_explicit_scene_number_does_not_place_stickers_on_another_scene(self):
        self.request['frames'][0]['frame']=2
        plan={**self.plan,'segments':[
          {'kind':'video','frame':1,'start':0,'duration':1,'layer':0},
          {'kind':'video','frame':2,'start':1,'duration':2,'layer':0}]}
        pending=A.with_optional_sticker_placements(plan,self.request)
        self.assertEqual((1,2),(pending['segments'][-1]['start'],pending['segments'][-1]['duration']))
    def test_every_scene_has_an_optional_sticker_without_duplicating_requested_stickers(self):
        request=R.effect_sticker_request({'frames':[
          {'id':'frame-1','slots':[{'id':'text','role':'text','categories':['text_effect'],'required':True}]},
          {'id':'frame-2','slots':[{'id':'requested','role':'sticker','categories':['sticker'],'required':True}]}]})
        self.assertTrue(request['frames'][0]['slots'][-1]['opt_in'])
        self.assertFalse(request['frames'][0]['slots'][-1]['required'])
        self.assertEqual(1,len(request['frames'][1]['slots']))
        self.assertEqual(request,R.effect_sticker_request(request))

if __name__=='__main__':unittest.main()
