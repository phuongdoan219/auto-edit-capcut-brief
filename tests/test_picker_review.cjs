const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Run the actual review logic with a small DOM adapter, without a live session.
function picker(choices) {
  const nodes = new Map();
  function element(tag='div') {
    return {tag, children:[], textContent:'', disabled:false, open:false,
      append(...children){this.children.push(...children);},
      replaceChildren(...children){this.children=children;},
      addEventListener(type, action){this[type]=action;},
      showModal(){this.open=true;}, close(){this.open=false;}};
  }
  const document = {createElement:element, getElementById(id){
    if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);
  }};
  for(const id of ['review-dialog','confirm','review-error','summary'])document.getElementById(id);
  const html = fs.readFileSync(path.join(__dirname,'../assets/picker.html'),'utf8');
  const script = html.match(/<script nonce="__CSP_NONCE__">([\s\S]*?)<\/script>/)[1];
  const context = vm.createContext({document,URLSearchParams,location:{hash:''},
    sessionStorage:{getItem(){return null;}},history:{},console});
  vm.runInContext(script.slice(0,script.indexOf("$('close-detail').addEventListener")), context);
  vm.runInContext(`state={request:{frames:[{id:'frame-1',slots:[
    {id:'text',label:'Chữ cảnh 1',role:'text',required:true}]}]}};
    entriesByKey={font:{name:'Font đã chọn'},effect:{name:'Hiệu ứng đã chọn'}};
    choices=${JSON.stringify(choices)};render=()=>{};review();`,context);
  return {nodes,context};
}

test('effect-only selection opens review, shows missing style and keeps confirmation disabled',()=>{
  const {nodes,context}=picker({text:{effect:'effect'}});
  assert.equal(nodes.get('review-dialog').open,true);
  assert.equal(nodes.get('confirm').disabled,true);
  assert.match(nodes.get('review-error').textContent,/kiểu chữ hoặc mẫu chữ/);
  assert.match(JSON.stringify(nodes.get('summary')),/Hiệu ứng đã chọn/);
  assert.equal(vm.runInContext('choices.text.effect',context),'effect');
});

test('complete selection opens review with confirmation enabled',()=>{
  const {nodes}=picker({text:{style:'font',effect:'effect'}});
  assert.equal(nodes.get('review-dialog').open,true);
  assert.equal(nodes.get('confirm').disabled,false);
  assert.equal(nodes.get('review-error').textContent,'');
});

test('required missing selection stays visible in review and cannot confirm',()=>{
  const {nodes}=picker({});
  assert.equal(nodes.get('review-dialog').open,true);
  assert.equal(nodes.get('confirm').disabled,true);
  assert.match(nodes.get('review-error').textContent,/hãy chọn thành phần/);
});
