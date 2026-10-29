import copy,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import selection_session as S
import selection_request as R
import selection_plan as A
import capcut_native as C
import test_choice_assembly as fixtures

class EffectPickerTests(fixtures.ChoiceAssemblyTests):
    def setUp(self):
        super().setUp()
        self.effect.update(segment=copy.deepcopy(self.style['segment']),materials=copy.deepcopy(self.style['materials']),track_type='text')
        self.effect['materials']['effects']=[copy.deepcopy(self.effect['effect_recipe']['effects'][0])]
        self.effect['materials']['material_animations']=[{'id':'old-animation','animations':[{'type':'in','id':'old'}]}]
        self.effect['segment']['extra_material_refs']=['local-effect','old-animation']
        self.effect['resource_paths'].append(str(self.font))
        self.request['selection_mode']='effects_stickers'
        self.request['frames'][0]['slots'][0]['categories']=['text_effect']
        self.choices={'f1.text1':{'effect':'effect'}}

    # The parent is a fixture; these assertions exercise the new contract.
    def test_effect_alone_is_confirmable(self):
        self.assertEqual([],S.validate_choices(self.request,self.library,self.choices))
        for extra in [{'style':'style'},{'template':'style'},{'animations':{'in':'anim'}}]:
            bad=copy.deepcopy(self.choices);bad['f1.text1'].update(extra)
            self.assertTrue(S.validate_choices(self.request,self.library,bad))
        for invalid in [None,[],{},42]:
            self.assertTrue(S.validate_choices(self.request,self.library,{'f1.text1':{'effect':invalid}}))

    def test_compile_effect_uses_its_donor_font_without_inherited_animation(self):
        plan=A.assemble_plan(self.plan,self.request,self.library,self.confirmed())
        self.assertEqual('effect',plan['segments'][0]['asset'])
        self.assertEqual({},plan['segments'][0]['animation_assets'])
        d,_=C.compile_plan(plan,self.base,self.library)
        content=json.loads(d['materials']['texts'][0]['content'])
        self.assertEqual('Xin chào',content['text'])
        self.assertEqual('external-font',content['styles'][0]['font']['id'])
        self.assertEqual('external-effect',content['styles'][0]['effectStyle']['id'])
        self.assertEqual([],d['materials']['material_animations'])

    def test_preview_only_or_complex_effect_is_not_confirmable(self):
        for change in ('missing_donor','template','rich_text'):
            lib=copy.deepcopy(self.library);entry=next(e for e in lib['entries'] if e['key']=='effect')
            if change=='missing_donor':entry.pop('segment')
            elif change=='template':entry['materials']['text_templates']=[{'id':'template'}]
            else:
                content=json.loads(entry['materials']['texts'][0]['content']);content['styles']*=2
                entry['materials']['texts'][0]['content']=json.dumps(content)
            self.assertTrue(S.validate_choices(self.request,lib,self.choices),change)

    def test_user_choices_drive_native_fields(self):
        plan=A.assemble_plan(self.plan,self.request,self.library,self.confirmed())
        self.assertEqual('effect',plan['segments'][0]['asset'])
        self.assertEqual('Xin chào',plan['segments'][0]['text'])

    def test_compile_composes_chosen_native_effect_and_animation(self):
        self.test_compile_effect_uses_its_donor_font_without_inherited_animation()

class RequestModeTests(unittest.TestCase):
    def test_sticker_mentions_in_english_and_vietnamese_create_a_sticker_slot(self):
        for word in ['stickers','icons','nhãn dán','nhãn dãn','biểu tượng']:
            with self.subTest(word=word):
                req=R.make_request({'frames':[{'frame':1,'dialogue':'Giữ nguyên','edit_notes':'Thêm '+word}]})
                self.assertEqual(['sticker'],[s['role'] for s in req['frames'][0]['slots']])

    def test_default_request_contains_only_effects_and_stickers(self):
        req=R.make_request({'title':'Test','frames':[{'frame':1,'dialogue':'Keep this','text':'Keep Vietnamese: Xin chào','edit_notes':'Add a sticker and video effect'}]})
        self.assertEqual('effects_stickers',req['selection_mode'])
        slots=req['frames'][0]['slots']
        self.assertEqual(['text','sticker'],[s['role']for s in slots])
        self.assertEqual(['text_effect'],slots[0]['categories'])
        self.assertEqual('Keep Vietnamese: Xin chào',slots[0]['text'])

    def test_normalize_keeps_frame_copy_but_removes_other_picker_types(self):
        source={'frames':[{'id':'f','dialogue':'Giữ thoại','slots':[
          {'id':'text','role':'text','label':'Chữ','categories':['text_style','text_template'],'required':True},
          {'id':'sticker','role':'icon','label':'Biểu tượng','categories':['sticker'],'required':True},
          {'id':'fx','role':'video_effect','categories':['video_effect'],'required':True}]}]}
        result=R.effect_sticker_request(source)
        self.assertEqual(['text','sticker'],[s['id'] for s in result['frames'][0]['slots']])
        self.assertEqual('Giữ thoại',result['frames'][0]['dialogue'])
        self.assertEqual(['text_style','text_template'],source['frames'][0]['slots'][0]['categories'])

if __name__=='__main__':unittest.main()
