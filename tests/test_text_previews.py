import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import text_previews as P

class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.font=Path('C:/Windows/Fonts/arial.ttf')
        if not self.font.exists():self.skipTest('system font fixture not present')
        t={'font_path':str(self.font),'text_color':'#ffffff','background_style':1,'background_color':'#a74100',
           'content':json.dumps({'text':'Ví dụ chữ tiếng Việt','styles':[{'font':{'path':str(self.font)}}]})}
        self.entry={'key':'text-style-fixture','category':'text_style','available':True,'materials':{'texts':[t]}}
    def tearDown(self):self.temp.cleanup()
    def test_real_font_generates_explicit_approximate_preview(self):
        result=P.create_preview(self.entry,self.root)
        self.assertTrue(Path(result).is_file())
        from PIL import Image
        with Image.open(result) as image:self.assertEqual(image.size,(640,240))
        self.assertEqual(self.entry['preview_kind'],'approximate_text')
    def test_missing_font_never_fabricates_a_preview(self):
        self.entry['materials']['texts'][0]['font_path']=str(self.root/'missing.ttf')
        self.entry['materials']['texts'][0]['content']='{}'
        self.assertIsNone(P.create_preview(self.entry,self.root))
        self.assertNotIn('preview_kind',self.entry)
    def test_reuses_existing_cached_file_and_font_change_invalidates(self):
        a=P.create_preview(self.entry,self.root)
        b=P.create_preview(self.entry,self.root)
        self.assertEqual(a,b)
        self.entry['materials']['texts'][0]['text_color']='#00ff00'
        c=P.create_preview(self.entry,self.root)
        self.assertNotEqual(a,c)

if __name__=='__main__':unittest.main()
