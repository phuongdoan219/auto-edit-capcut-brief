import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import capcut_native as C
import selection_plan as A
import selection_session as S


class ChoiceAssemblyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.font=self.root/'font.ttf';self.font.write_bytes(b'font')
        self.fx=self.root/'effect';self.fx.mkdir();(self.fx/'config.json').write_text('{}')
        text={'id':'text-old','type':'text','font_path':str(self.font),'text_color':'#ffffff',
              'content':json.dumps({'text':'Original','styles':[{'range':[0,8],'font':{'path':str(self.font),'id':'external-font'},'fill':{'content':{'render_type':'solid','solid':{'color':[1,1,1]}}}}]})}
        segment={'id':'text-segment','material_id':'text-old','target_timerange':{'start':0,'duration':3000000},'source_timerange':None,'extra_material_refs':[],
                 'keyframe_refs':[],'common_keyframes':[],'clip':{'scale':{'x':1,'y':1},'transform':{'x':0,'y':0},'rotation':0,'alpha':1,'flip':{'horizontal':False,'vertical':False}}}
        self.style={'key':'style','category':'text_style','kind':'text','name':'Base','track_type':'text','segment':segment,'materials':{'texts':[text]},'resource_paths':[str(self.font)],'available':True,'supported':True}
        effect={'id':'local-effect','type':'text_effect','resource_id':'external-effect','path':str(self.fx)}
        self.effect={'key':'effect','category':'text_effect','kind':'text','name':'Glow','available':True,'supported':True,'resource_paths':[str(self.fx)],
                     'effect_recipe':{'effects':[effect],'style_overrides':[{'effectStyle':{'id':'external-effect','path':str(self.fx)}}]}}
        self.animation={'key':'anim','category':'text_animation','kind':'text_animation','name':'In','animation_type':'in','available':True,'supported':True,'resource_paths':[str(self.fx)],
                        'animation':{'id':'12345678-1234-1234-1234-123456789012','resource_id':'external-animation','type':'in','start':0,'duration':500000,'path':str(self.fx)}}
        self.library={'schema':'capcut-native-library/2','machine_id':'test-machine','entries':[self.style,self.effect,self.animation]}
        self.request={'schema':'capcut-selection-request/1','id':'req','title':'T','frames':[{'id':'f1','dialogue':'Hello','slots':[{'id':'f1.text1','role':'text','label':'Title','required':True,'text':'Xin chào','categories':['text_style','text_effect','text_animation','text_template']}]}]}
        self.choices={'f1.text1':{'style':'style','effect':'effect','template':None,'animations':{'in':'anim','out':None,'loop':None}}}
        self.plan={'duration':3,'fps':30,'canvas':{'width':1080,'height':1920},'segments':[{'kind':'text','slot_id':'f1.text1','text':'Xin chào','start':0,'duration':3,'layer':1}]}
        self.base={'id':'p','duration':3000000,'fps':30,'canvas_config':{'width':1080,'height':1920},'materials':{},'tracks':[]}
    def tearDown(self):self.tmp.cleanup()
    def confirmed(self):return S.confirm_session(self.request,self.library,self.choices)
    def test_pending_user_choices_cannot_assemble(self):
        with self.assertRaises(ValueError):A.assemble_plan(self.plan,self.request,self.library,{'status':'pending'})
    def test_user_choices_drive_native_fields(self):
        p=A.assemble_plan(self.plan,self.request,self.library,self.confirmed())
        s=p['segments'][0]
        self.assertEqual((s['asset'],s['effect_asset'],s['animation_assets']['in']),('style','effect','anim'))
        self.assertEqual(s['text'],'Xin chào')
    def test_required_slot_missing_in_plan_is_rejected(self):
        p=copy.deepcopy(self.plan);p['segments']=[]
        with self.assertRaises(ValueError):A.assemble_plan(p,self.request,self.library,self.confirmed())
    def test_compile_composes_chosen_native_effect_and_animation(self):
        plan=A.assemble_plan(self.plan,self.request,self.library,self.confirmed())
        d,_=C.compile_plan(plan,self.base,self.library)
        content=json.loads(d['materials']['texts'][0]['content'])
        self.assertEqual(content['text'],'Xin chào')
        self.assertEqual(content['styles'][0]['effectStyle']['id'],'external-effect')
        self.assertEqual(content['styles'][0]['font']['id'],'external-font')
        anim=d['materials']['material_animations'][0]['animations'][0]
        self.assertEqual(anim['id'],'12345678-1234-1234-1234-123456789012')
        self.assertEqual(anim['start'],0)
        self.assertEqual(anim['duration'],500000)
    def test_unknown_slot_and_unselected_native_decorations_rejected(self):
        p=copy.deepcopy(self.plan);p['segments'].append({'kind':'sticker','asset':'made-up','start':0,'duration':1})
        with self.assertRaises(ValueError):A.assemble_plan(p,self.request,self.library,self.confirmed())
    def test_changing_library_after_confirmation_rejected(self):
        s=self.confirmed();lib=copy.deepcopy(self.library);lib['machine_id']='another-machine'
        with self.assertRaises(ValueError):A.assemble_plan(self.plan,self.request,lib,s)


if __name__=='__main__':unittest.main()
