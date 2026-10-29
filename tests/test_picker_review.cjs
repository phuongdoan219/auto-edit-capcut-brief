const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const html=fs.readFileSync(process.env.CAPCUT_PICKER_HTML||path.join(__dirname,'../assets/picker.html'),'utf8');
function picker(choices={}){
 const nodes=new Map(),storage=new Map();
 function element(tag='div'){return {tag,tagName:tag.toUpperCase(),children:[],dataset:{},textContent:'',disabled:false,hidden:false,
  classList:{add(){},remove(){},toggle(){}},append(...xs){this.children.push(...xs)},replaceChildren(...xs){this.children=xs},
  addEventListener(type,fn){this[type]=fn},setAttribute(){},querySelectorAll(){return []},focus(){},scrollTo(){}};}
 const document={createElement:element,getElementById(id){if(!nodes.has(id))nodes.set(id,element());return nodes.get(id)}};
 const script=html.match(/<script nonce="__CSP_NONCE__">([\s\S]*?)<\/script>/)[1];
 const context=vm.createContext({document,URLSearchParams,location:{hash:''},console,history:{},
  sessionStorage:{getItem(){return null}},localStorage:{getItem(k){return storage.get(k)||null},setItem(k,v){storage.set(k,v)},removeItem(k){storage.delete(k)}}});
 vm.runInContext(script.slice(0,script.indexOf('// Events.')),context);
 vm.runInContext(`state={request_hash:'r',library_hash:'l',request:{frames:[{id:'f1',slots:[
  {id:'text',role:'text',required:true,categories:['text_effect'],text:'Keep this copy'},
  {id:'sticker',role:'sticker',required:false,opt_in:true,categories:['sticker']}]}]}};
  entriesByKey={effect:{key:'effect',category:'text_effect',name:'Native Effect',available:true,supported:true,previews:[{url:'/effect',type:'image/png'}]},
   heart:{key:'heart',category:'sticker',name:'Heart',available:true,supported:true,previews:[{url:'/heart',type:'image/png'}]}};
  choices=${JSON.stringify(choices)};render=()=>{};`,context);
 return {nodes,context,run:code=>vm.runInContext(code,context)};
}
test('the page has only two action buttons and no sidebar or nested popup',()=>{
 assert.equal((html.match(/<button\b/g)||[]).length,2);
 assert.doesNotMatch(html,/<aside\b|<dialog\b/);
 assert.doesNotMatch(html,/Add Sticker \(Optional\)|Review All|Choose Missing Items/);
});
test('each step focuses on one slot, with text before its optional sticker',()=>{
 const {run}=picker();
 assert.deepEqual(Array.from(run('allSteps().map(s=>s.slot.id)')),['text','sticker']);
 run('updateControls()');assert.equal(run("$('confirm').disabled"),true);
});
test('selecting a tile saves a choice but does not advance or confirm',()=>{
 const {run}=picker();run("chooseAsset(entriesByKey.effect)");
 assert.equal(run('choices.text.effect'),'effect');assert.equal(run('currentStep'),0);
 assert.equal(run('confirmed'),false);assert.equal(run("$('confirm').disabled"),false);
 run('goNext()');assert.equal(run('currentStep'),1);
});
test('an optional sticker has Skip and does not create an invented choice',()=>{
 const {run}=picker({text:{effect:'effect'}});run('currentStep=1;updateControls()');
 assert.equal(run("$('confirm').textContent"),'Skip');assert.equal(run("$('confirm').disabled"),false);
 run('goNext()');assert.equal(run('currentStep'),2);assert.equal(run('choices.sticker'),undefined);
 assert.equal(run('confirmed'),false);
 run('updateControls()');assert.equal(run("$('confirm').textContent"),'Confirm & Edit');
});
test('Back preserves previous selections and sticker selection is optional',()=>{
 const {run}=picker({text:{effect:'effect'}});run('currentStep=1;chooseAsset(entriesByKey.heart);goBack()');
 assert.equal(run('currentStep'),0);assert.equal(run('choices.sticker.asset'),'heart');
 run('currentStep=1;chooseAsset(entriesByKey.heart);updateControls()');
 assert.equal(run('choices.sticker'),undefined);assert.equal(run("$('confirm').textContent"),'Skip');
});
test('drafts keep the step and choices and remain scoped to request/library',()=>{
 const {run}=picker({text:{effect:'effect'}});run('currentStep=1;persistDraft();choices={};currentStep=0;restoreDraft()');
 assert.equal(run('currentStep'),1);assert.equal(run('choices.text.effect'),'effect');
 run("state.library_hash='other';choices={};restoreDraft()");assert.equal(run('Object.keys(choices).length'),0);
});
test('confirmation requires the final explicit action and then leaves one Close button',async()=>{
 const {run}=picker({text:{effect:'effect'}});
 run("globalThis.posts=0;api=async(path,body)=>{posts++;return {session:{status:'confirmed',choices:body.choices}}};currentStep=1;goNext()");
 assert.equal(run('posts'),0);await run('confirmChoices()');assert.equal(run('posts'),1);
 assert.equal(run('confirmed'),true);run('updateControls()');
 assert.equal(run("$('back').hidden"),true);assert.equal(run("$('confirm').textContent"),'Close');
});
test('a failed confirmation stays on review with a visible error and a retry action',async()=>{
 const {run}=picker({text:{effect:'effect'}});run("currentStep=2;api=async()=>{throw Error('Disk unavailable')}");
 await run('confirmChoices()');assert.equal(run('confirmed'),false);assert.equal(run('currentStep'),2);
 assert.equal(run("$('notice').textContent"),'Disk unavailable');assert.equal(run("$('confirm').disabled"),false);
});
test('preview failure tries another file, then hides the option',()=>{
 const {run}=picker();run("globalThis.failed=false;globalThis.p=preview({key:'bad',previews:[{url:'/one',type:'image/png'},{url:'/two',type:'image/png'}]},()=>failed=true)");
 run('p.children[0].error()');assert.match(run('p.children[0].src'),/^\/two/);
 run('p.children[0].error()');assert.equal(run('failed'),true);
});

test('on-frame preview sends only this scene choices and never confirms',async()=>{
 const {run}=picker({text:{effect:'effect'},otherScene:{effect:'effect'}});
 run(`state.scene_preview={scenes:[{id:'f1',start:0,samples:[{time:.5},{time:1.5}],slots:[{id:'text',start:1,duration:1}]}]};
 globalThis.calls=[];globalThis.URL={createObjectURL:()=>'/blob',revokeObjectURL(){}};
 fetch=async(path,options)=>{calls.push({path,options});return {ok:true,headers:{get(){return ''}},blob:async()=>({})}};
 $('moment').value='1';`);
 await run('updateScenePreview()');
 const request=new URL(run('calls[0].path'),'http://localhost');
 assert.equal(request.pathname,'/api/scene-preview');
 assert.deepEqual(JSON.parse(request.searchParams.get('choices')),{text:{effect:'effect'}});
 assert.equal(request.searchParams.get('sample'),'1');assert.equal(run('confirmed'),false);
 assert.equal(run("$('frame-image').hidden"),false);
});

test('main and supporting text have separate steps and keep different effects',()=>{
 const {run}=picker();
 run(`state.request.frames[0].slots[0].text_group='main';
 state.request.frames[0].slots.splice(1,0,{id:'body',role:'text',required:true,categories:['text_effect'],text_group:'support',text:'Supporting copy'});
 entriesByKey.gentle={...entriesByKey.effect,key:'gentle',name:'Gentle'};`);
 assert.equal(run('stepTitle(activeStep())'),'Choose main text');
 run('chooseAsset(entriesByKey.effect);goNext()');
 assert.equal(run('stepTitle(activeStep())'),'Choose supporting text');
 assert.equal(run("$('confirm').disabled"),false); // render is stubbed by this harness
 run('updateControls()');assert.equal(run("$('confirm').disabled"),true);
 run('chooseAsset(entriesByKey.gentle)');
 assert.equal(run('choices.text.effect'),'effect');assert.equal(run('choices.body.effect'),'gentle');
});
