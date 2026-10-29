"""Read-only reviewer repros; fixtures/state stay inside the review folder."""
import copy
import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.dont_write_bytecode = True
sys.path.insert(0, str(SCRIPTS))
import library_scan as L
import native_composition as NC


class IndependentNativeReview(unittest.TestCase):
    def style(self):
        return {'id': 'txt', 'type': 'text', 'content': json.dumps({'text':'x','styles':[{'range':[0,1],'font':{'id':'font'},'fill':{'content':{'render_type':'solid'}}}]})}

    def test_font_without_resource_id_is_not_merged_with_other_font(self):
        a = self.style(); b = self.style()
        for mat, name in ((a, '/fonts/a.ttf'), (b, '/fonts/b.ttf')):
            obj=json.loads(mat['content']);obj['styles'][0]['font']={'id':'','path':name};mat['content']=json.dumps(obj)
            mat['font_resource_id']='';mat['font_path']=name
        self.assertNotEqual(L._canonical(a, {'txt'}, True), L._canonical(b, {'txt'}, True))

    def test_plain_style_removes_obsolete_base_content_font(self):
        mat=self.style();mat['base_content']=json.dumps({'text':'old','styles':[{'font':{'path':'/old-app/font.ttf'}}]})
        mats, _=L._plain_style({'texts':[mat]}, {'id':'s','material_id':'txt'})
        self.assertNotIn('/old-app/font.ttf', json.dumps(mats))

    def test_recipe_has_only_selected_effect_appearance(self):
        mat=self.style();obj=json.loads(mat['content']);obj['styles']=[{'effectStyle':{'id':'other'}},{'effectStyle':{'id':'selected'}}];mat['content']=json.dumps(obj)
        recipe=L._recipe({'texts':[mat]}, [{'id':'local','type':'text_effect','resource_id':'selected'}])
        self.assertEqual([s['effectStyle']['id'] for s in recipe['style_overrides']], ['selected'])

    def test_native_strokes_are_composed(self):
        mat=self.style();seg={'id':'s','material_id':'txt','extra_material_refs':[]}
        strokes=[{'width':0.12}]
        asset={'key':'fx','category':'text_effect','available':True,'supported':True,'resource_paths':[],
               'effect_recipe':{'effects':[{'id':'local','type':'text_effect','resource_id':'external'}],
                                'style_overrides':[{'effectStyle':{'id':'external'},'strokes':strokes}]}}
        mats={'texts':[mat]};NC.compose_text(seg,mats,{'effect_asset':'fx'},{'entries':[asset]},1000000)
        self.assertEqual(json.loads(mats['texts'][0]['content'])['styles'][0].get('strokes'), strokes)

    def test_composed_effect_retains_dependency_closure(self):
        mat=self.style();seg={'id':'s','material_id':'txt','extra_material_refs':[]}
        dependency={'id':'dependent','type':'text_shape'}
        effect={'id':'local','type':'text_effect','resource_id':'external','extra_material_refs':['dependent']}
        asset={'key':'fx','category':'text_effect','available':True,'supported':True,'resource_paths':[],
               'materials':{'effects':[effect,dependency]},
               'effect_recipe':{'effects':[effect],'style_overrides':[{'effectStyle':{'id':'external'}}]}}
        mats={'texts':[mat]};NC.compose_text(seg,mats,{'effect_asset':'fx'},{'entries':[asset]},1000000)
        ids={m['id'] for rows in mats.values() for m in rows}
        refs=[r for m in mats['effects'] for r in m.get('extra_material_refs',[])]
        self.assertTrue(all(r in ids for r in refs), (ids,refs))

if __name__ == '__main__':unittest.main()
