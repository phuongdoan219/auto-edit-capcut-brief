import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import workflow as W
import selection_request as R
import library_scan as L


class WorkflowTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_ini_sections_are_not_treated_as_json_arrays(self):
        p=self.root/'commonSetting.ini';target=self.root/'MovedProjects';target.mkdir()
        p.write_text('[General]\ncurrentCustomDraftPath='+str(target).replace('\\','\\\\')+'\n')
        self.assertEqual(L._metadata_roots(p),[target])
    def test_headline_in_non_text_prefixed_line_is_drafted(self):
        raw={'id':'brief','items':[{'item_order':1,'voice':'Hello','source':'- Text font Montserrat\nKhung nền đỏ chữ trắng, nội dung text hiện, cân đối dòng: Tiêu đề'}]}
        request=R.make_request(raw)
        self.assertEqual(request['frames'][0]['slots'][0]['text'],'Tiêu đề')
        self.assertTrue(request['semantic_review_required'])
    def test_prepare_refuses_unreviewed_semantic_slots(self):
        p=self.root/'request.json';p.write_text(json.dumps({'semantic_review_required':True}))
        with self.assertRaisesRegex(ValueError,'review'):W.prepare(p,self.root/'video')
    def test_pending_popup_never_builds(self):
        lib={'roots':[],'machine_id':'machine'}
        paths={k:self.root/(k+'.json') for k in ('library','request','session')}
        for k,value in [('library',lib),('request',{}),('session',{'status':'pending','choices':{}})]:paths[k].write_text(json.dumps(value))
        (self.root/'workflow.json').write_text(json.dumps({k:str(p) for k,p in paths.items()}))
        with patch.object(W.library_scan,'machine_identity',return_value='machine'),patch.object(W.capcut_native,'build_files') as build:
            result=W.resume(self.root)
            self.assertEqual(result['status'],'pending_selection');build.assert_not_called()


if __name__=='__main__':unittest.main()
