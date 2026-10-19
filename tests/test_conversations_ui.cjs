const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(require('path').join(__dirname,'../antigravity/conversations.html'),'utf8').split('<script>')[1].split('</script>')[0];
const elements=new Map(),listeners={},timers=new Map();let next=0,calls=0,posts=0,deletes=0,revision="r",fail=false,resolveFetch;
class Element{constructor(){this.dataset={};this.value='';this.children=[];this.open=false;this.listeners={};}replaceChildren(){this.children=[];}append(...x){this.children.push(...x);}setAttribute(){}addEventListener(name,fn){this.listeners[name]=fn;}showModal(){this.open=true;}close(){this.open=false;this.listeners.close?.();}}
const get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
const document={hidden:false,getElementById:get,createElement:()=>new Element(),querySelectorAll:()=>[get('refresh'),get('apply'),get('cancel')],addEventListener:(name,fn)=>listeners[name]=fn};
const context=vm.createContext({window:{location:{}},URLSearchParams,document,console,AbortController,Date,Error,setTimeout:(fn,ms)=>{timers.set(++next,{fn,ms});return next;},clearTimeout:id=>timers.delete(id),fetch:async(url,opts)=>{calls++;if(opts.method==='POST')posts++;if(url==='conversation-delete')deletes++;if(resolveFetch)await new Promise(r=>resolveFetch=r);return {ok:!fail,json:async()=>fail?{error:'Disconnected'}:(url==='conversation-session'?{ok:true}:url==='conversation-prepare'?{item:{id:'a',title:'Updated title',revision,blocked:''}}:{items:[{id:'a',title:'A',steps:1,modified:'2026-10-13',revision,blocked:''}]})};}});
const descendants=el=>el.children.flatMap(child=>[child,...descendants(child)]);
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
(async()=>{vm.runInContext(source,context);await flush();assert.equal(calls,1);assert.equal(get('connection').textContent,'Connected');assert([...timers.values()].some(t=>t.ms===15000));
get('search').value='missing';get('search').oninput();assert(get('list').children.some(e=>e.textContent==='No conversations match your search.'));get('search').value='';get('search').oninput();
await descendants(get('list')).find(e=>e.className==='row').children[1].children[1].onclick();assert(get('confirm').open);await vm.runInContext('load()',context);assert.equal(calls,2);assert.equal(timers.size,0);
 assert(get('selected').textContent.includes('Updated title'));assert.equal(deletes,0);
 revision='changed';await get('apply').onclick();
 assert.equal(deletes,0);assert(get('error').textContent.includes('confirm again'));
 await get('apply').onclick();assert.equal(deletes,1);assert(!get('confirm').open);
 await descendants(get('list')).find(e=>e.className==='row').children[1].children[1].onclick();
 fail=true;await get('apply').onclick();assert.equal(deletes,1);assert(get('apply').disabled);fail=false;
 const beforeVisibility=calls;
get('cancel').onclick();document.hidden=true;listeners.visibilitychange();assert.equal(timers.size,0);document.hidden=false;listeners.visibilitychange();await flush();assert.equal(calls,beforeVisibility+1);
fail=true;await vm.runInContext('load()',context);assert.equal(get('connection').textContent,'Not connected');assert.equal(get('list').children.length,1);assert([...timers.values()].some(t=>t.ms===30000));assert(posts>0);assert.equal(deletes,1);

vm.runInContext(`items=[
 {id:'one',title:'First',projectId:'p1',projectName:'Home Assistant',archived:false},
 {id:'two',title:'Second',projectId:'p2',projectName:'AirPrint',archived:true},
 {id:'three',title:'Third',projectId:'p3',projectName:'Home Assistant',archived:false},
 {id:'four',title:'Fourth',projectId:'',projectName:'No project',archived:null}
];connected=true;render();`,context);
let headings=descendants(get('list')).filter(e=>e.className==='group-heading').map(e=>e.textContent);
assert.equal(headings.filter(t=>t==='Home Assistant · 1').length,2);
assert(headings.includes('AirPrint · 1'));assert(headings.includes('No project · 1'));
assert(get('list').children.some(e=>e.textContent==='Archived · 1'));
const folders=()=>get('list').children.filter(e=>e.className==='project-folder');
assert(folders().every(f=>!f.open));
const closedKey=folders()[0].dataset.key;folders()[1].open=true;
vm.runInContext('render()',context);
assert.equal(folders().find(f=>f.dataset.key===closedKey).open,false);
assert.equal(folders().filter(f=>f.open).length,1);
get('search').value='Home Assistant';get('search').oninput();
assert(folders().every(f=>f.open));
get('search').value='';get('search').oninput();
assert.equal(folders().find(f=>f.dataset.key===closedKey).open,false);
get('search').value='AirPrint';get('search').oninput();
assert.equal(descendants(get('list')).filter(e=>e.className==='row').length,1);
assert(get('list').children.some(e=>e.textContent==='Archived · 1'));
get('search').value='';get('search').oninput();
// Every conversation owns a footer, including blocked/active entries. Refreshes
// and filtering must not move it into the project or reset its disclosure state.
vm.runInContext(`items.push({id:'five',title:'Active',projectId:'p1',projectName:'Home Assistant',blocked:'Active conversation'});render();`,context);
const rows=()=>descendants(get('list')).filter(e=>e.className==='row');
const footer=id=>rows().map(r=>r.children[2]).find(e=>e.dataset.conversationId===id);
for(const row of rows()){
 assert.equal(row.children.length,3);
 assert.equal(row.children[2].className,'conversation-more');
 assert.equal(row.children[2].children[1].hidden,true);
}
assert(folders().every(f=>!f.children.some(c=>c.className==='conversation-more')));
footer('one').children[0].onclick();
assert.equal(footer('one').children[1].hidden,false);
assert.equal(footer('five').children[1].hidden,true);
vm.runInContext('render()',context);
assert.equal(footer('one').children[1].hidden,false);
get('search').value='Active';get('search').oninput();
assert.equal(rows().length,1);assert(footer('five'));
get('search').value='';get('search').oninput();
assert.equal(footer('one').children[1].hidden,false);
footer('one').children[0].onclick();vm.runInContext('render()',context);
assert.equal(footer('one').children[1].hidden,true);
function checkProjectMenus(){
 for(const folder of folders()){
  assert.equal(folder.children[0].className,'group-heading');
  const body=folder.children[1];assert.equal(body.className,'project-content');
  const menu=body.children.find(e=>e.className==='action-more project-more');
  if(menu)assert.equal(body.children[0],menu,'Project More precedes paths and all conversations');
  for(const row of body.children.filter(e=>e.className==='row')){
   assert.equal(row.children.length,3,'Conversation footer retained');
   assert.equal(row.children[2].className,'conversation-more');
  }
 }
}
checkProjectMenus();
folders().forEach(f=>f.open=true);vm.runInContext('render()',context);checkProjectMenus();
get('search').value='Home Assistant';get('search').oninput();checkProjectMenus();
get('search').value='';get('search').oninput();checkProjectMenus();
fail=false;get('newConversation').onclick();assert(get('sessionDialog').open);assert.equal(get('project').value,'');
assert.equal(timers.size,0);await vm.runInContext('load()',context);assert(get('sessionDialog').open);
await get('sessionApply').onclick();assert.equal(context.window.location.href,'controls');
get('sessionCancel').onclick();
await descendants(get('list')).find(e=>e.className==='row').children[1].children[0].onclick();
assert.equal(get('sessionTitle').textContent,'Open conversation');assert.equal(get('projectField').hidden,true);
const choice=vm.runInContext('chooseProjectFiles({name:"Test project",folder:"Test project"})',context);
assert(get('projectDeleteDialog').open);assert.equal(get('projectDeleteFiles').value,'keep');
assert.equal(get('projectDeleteReview').disabled,false);assert.equal(get('projectDeleteCancel').disabled,false);
get('projectDeleteReview').onclick();get('projectDeleteDialog').onclose();assert.equal(await choice,'keep');
const destructiveChoice=vm.runInContext('chooseProjectFiles({name:"Test project",folder:"Test project"})',context);
get('projectDeleteFiles').value='delete';get('projectDeleteReview').onclick();get('projectDeleteDialog').onclose();assert.equal(await destructiveChoice,'delete');
const cancelChoice=vm.runInContext('chooseProjectFiles({name:"Test project",folder:"Test project"})',context);
get('projectDeleteCancel').onclick();get('projectDeleteDialog').onclose();assert.equal(await cancelChoice,null);
console.log('UI checks passed: refresh, search, confirmation/recheck safety, project file retention default, explicit deletion choice and cancellation.');})().catch(e=>{console.error(e);process.exit(1);});
