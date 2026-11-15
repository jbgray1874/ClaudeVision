/* Dependency-free DOM harness. Tests request behavior, not rendered layout. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const code = fs.readFileSync(path.join(__dirname,'../../sdi-intelligence-backend/tti-batch-controls.js'),'utf8');
class Node {
  constructor(){this.value='';this.checked=false;this.disabled=false;this.children=[];this.events={};}
  addEventListener(n,f){this.events[n]=f;}
  setAttribute(){}
  append(n){this.children.push(n);}
  replaceChildren(){this.children=[];}
  scrollIntoView(){}
  querySelectorAll(selector){
    const all=this.children.flatMap(x=>[x,...x.querySelectorAll('all')]);
    return selector==='all'?all:all.filter(x=>x.type==='checkbox'&&(selector!=='input:checked'||x.checked));
  }
}
function setup(respond,hash=''){
  const nodes={},calls=[];
  const el=id=>nodes[id]||(nodes[id]=new Node());
  el('ttiCtlMode').value='next'; el('ttiCtlCount').value='5';el('ttiCtlStart').value='3';
  const context={document:{getElementById:el,createElement:()=>new Node(),dispatchEvent(){}},
    location:{hash},URLSearchParams,confirm:()=>true,CustomEvent:class{},
    api:async(url,options)=>{const body=JSON.parse(options.body);calls.push({url,body});return respond(url,body);}};
  vm.runInNewContext(code,context);
  return {el:id=>el('ttiCtl'+id),calls};
}
const ok=data=>({ok:true,json:async()=>data});
(async()=>{
  let h=setup(()=>ok({})); assert.equal(h.calls.length,0,'no automatic submit on load');
  h=setup(()=>ok({rows:[{row_id:'abc',row:3,drawing:'<script>',quantity:3,state:'completed',rerun_allowed:true}],enabled:true}), '#tti-row-id=abc');
  await h.el('Load').onclick();
  assert.equal(h.calls.length,1);assert.ok(h.calls[0].url.endsWith('/rows'));
  assert.equal(h.el('Mode').value,'rerun'); assert.equal(h.el('Count').disabled,true);
  assert.equal(h.el('Rows').querySelectorAll('input:checked').length,1,'row link selects only');
  assert.equal(h.el('Rows').children[0].children[2].textContent,'<script>','row rendered as text');
  const plan={plan_id:'p',mode:'next',selected:[{row:3,drawing:'GA',quantity:3}],runnable:true,message:'Preview'};
  h=setup(url=>url.endsWith('/preview')?ok(plan):Promise.reject(new Error('Timeout')));
  await h.el('Preview').onclick();
  assert.equal(h.calls[0].body.count,5);
  await h.el('Run').onclick(); await h.el('Run').onclick();
  assert.equal(h.calls.filter(x=>x.url.endsWith('/run')).length,1,'uncertain POST never retried');
  assert.equal(h.el('Run').disabled,true);
  assert.match(h.el('Status').textContent,/Do not retry/);
  h=setup(()=>ok({...plan,mode:'rerun'}));h.el('Mode').value='rerun';
  await h.el('Preview').onclick(); await h.el('Run').onclick();
  assert.equal(h.calls.length,1,'replacement needs consent');
  h.el('Replace').checked=true; await h.el('Run').onclick();
  assert.equal(h.calls[1].body.confirm_replace,true);
  console.log('4 UI scenarios passed (DOM harness; not browser visual QA)');
})().catch(e=>{console.error(e);process.exitCode=1;});
