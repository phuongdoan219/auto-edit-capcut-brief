const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html=fs.readFileSync(process.env.CAPCUT_PICKER_HTML||path.join(__dirname,'../assets/picker.html'),'utf8');

function picker(choices={}) {
  const nodes=new Map(), storage=new Map();
  function element(tag='div') {
    return {tag,children:[],textContent:'',disabled:false,open:false,dataset:{},
      classList:{add(){},remove(){},toggle(){}},
      append(...children){this.children.push(...children);},replaceChildren(...children){this.children=children;},
      addEventListener(type,action){this[type]=action;},setAttribute(){},
      showModal(){this.open=true;},close(){this.open=false;},scrollTo(){},focus(){}};
  }
  const document={createElement:element,getElementById(id){
    if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);
  }};
  const script=html.match(/<script nonce="__CSP_NONCE__">([\s\S]*?)<\/script>/)[1];
  const end=script.includes('// Events.')?script.indexOf('// Events.'):script.indexOf("$('close-detail').addEventListener");
  const context=vm.createContext({document,URLSearchParams,location:{hash:''},console,
    sessionStorage:{getItem(){return null;}},history:{},
    localStorage:{getItem(k){return storage.get(k)||null;},setItem(k,v){storage.set(k,v);},removeItem(k){storage.delete(k);}}});
  vm.runInContext(script.slice(0,end),context);
  vm.runInContext(`state={request_hash:'request-a',library_hash:'library-a',request:{frames:[{id:'frame-1',slots:[
    {id:'text',label:'Text Effect 1',role:'text',required:true,categories:['text_effect']}]}]}};
    entriesByKey={font:{key:'font',category:'text_style',name:'Font',available:true,supported:true},
      effect:{key:'effect',category:'text_effect',name:'Effect',available:true,supported:true},
      template:{key:'template',category:'text_template',name:'Template',available:true,supported:true}};
    choices=${JSON.stringify(choices)};render=()=>{};`,context);
  return {nodes,context,storage,run:code=>vm.runInContext(code,context)};
}

test('confirmation is on the main footer, without a second review dialog',()=>{
  assert.match(html,/<footer[^>]*id="footer"[\s\S]*?id="confirm"/);
  assert.doesNotMatch(html,/<dialog[^>]*id="review-dialog"/);
  assert.doesNotMatch(html,/<dialog[^>]*id="asset-detail"/);
});
test('incomplete selections can be reviewed inline without changing choices',()=>{
  const {run}=picker({});
  run('review()');
  assert.equal(run('viewMode'),'review');
  assert.equal(run('Object.keys(choices).length'),0);
});
test('a text effect alone enables confirmation without asking for a style',()=>{
  const {run,nodes}=picker({});
  run('updateProgress()');
  assert.equal(nodes.get('confirm').disabled,true);
  assert.match(nodes.get('remaining').textContent,/1/);
  run("choices.text={effect:'effect'};updateProgress()");
  assert.equal(nodes.get('confirm').disabled,false);
});
test('unconfirmed choices survive reload and are scoped to request and library',()=>{
  const {run}=picker({text:{effect:'effect'}});
  run('persistDraft(); choices={};restoreDraft()');
  assert.equal(run('choices.text.effect'),'effect');
  run("state.library_hash='different';choices={};restoreDraft()");
  assert.equal(run('Object.keys(choices).length'),0);
});
test('choosing an effect saves that choice without confirming automatically',()=>{
  const {run,nodes}=picker({});
  run("target={slot:state.request.frames[0].slots[0],part:'effect'};chooseAsset(entriesByKey.effect)");
  assert.equal(run('choices.text.effect'),'effect');
  assert.equal(run('confirmed'),false);
  assert.equal(nodes.get('gallery').open,false);
});
test('the picker exposes only English Text Effects and Stickers controls',()=>{
  assert.doesNotMatch(html,/Chọn|Xác nhận|Kiểu chữ|Mẫu chữ|Chuyển động/);
  const {run}=picker();
  assert.deepEqual(Array.from(run('Object.keys(labels)')),['text_effect','sticker']);
});
