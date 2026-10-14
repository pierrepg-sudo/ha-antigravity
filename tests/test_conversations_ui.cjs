const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(require('path').join(__dirname,'../antigravity/conversations.html'),'utf8').split('<script>')[1].split('</script>')[0];
const elements=new Map(),listeners={},timers=new Map();let next=0,calls=0,posts=0,deletes=0,revision="r",fail=false,resolveFetch;
class Element{constructor(){this.dataset={};this.value='';this.children=[];this.open=false;this.listeners={};}replaceChildren(){this.children=[];}append(...x){this.children.push(...x);}setAttribute(){}addEventListener(name,fn){this.listeners[name]=fn;}showModal(){this.open=true;}close(){this.open=false;this.listeners.close?.();}}
const get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
const document={hidden:false,getElementById:get,createElement:()=>new Element(),querySelectorAll:()=>[get('refresh'),get('apply'),get('cancel')],addEventListener:(name,fn)=>listeners[name]=fn};
const context=vm.createContext({document,console,AbortController,Date,Error,setTimeout:(fn,ms)=>{timers.set(++next,{fn,ms});return next;},clearTimeout:id=>timers.delete(id),fetch:async(url,opts)=>{calls++;if(opts.method==='POST')posts++;if(url==='conversation-delete')deletes++;if(resolveFetch)await new Promise(r=>resolveFetch=r);return {ok:!fail,json:async()=>fail?{error:'Disconnected'}:(url==='conversation-prepare'?{item:{id:'a',title:'Updated title',revision,blocked:''}}:{items:[{id:'a',title:'A',steps:1,modified:'2026-10-13',revision,blocked:''}]})};}});
const descendants=el=>el.children.flatMap(child=>[child,...descendants(child)]);
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
(async()=>{vm.runInContext(source,context);await flush();assert.equal(calls,1);assert.equal(get('connection').textContent,'Connected');assert([...timers.values()].some(t=>t.ms===15000));
get('search').value='missing';get('search').oninput();assert(get('list').children.some(e=>e.textContent==='No conversations match your search.'));get('search').value='';get('search').oninput();
await descendants(get('list')).find(e=>e.className==='row').children[1].onclick();assert(get('confirm').open);await vm.runInContext('load()',context);assert.equal(calls,2);assert.equal(timers.size,0);
 assert(get('selected').textContent.includes('Updated title'));assert.equal(deletes,0);
 revision='changed';await get('apply').onclick();
 assert.equal(deletes,0);assert(get('error').textContent.includes('confirm again'));
 await get('apply').onclick();assert.equal(deletes,1);assert(!get('confirm').open);
 await descendants(get('list')).find(e=>e.className==='row').children[1].onclick();
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
const closedKey=folders()[0].dataset.key;folders()[0].open=false;
vm.runInContext('render()',context);
assert.equal(folders().find(f=>f.dataset.key===closedKey).open,false);
assert.equal(folders().filter(f=>!f.open).length,1);
get('search').value='Home Assistant';get('search').oninput();
assert(folders().every(f=>f.open));
get('search').value='';get('search').oninput();
assert.equal(folders().find(f=>f.dataset.key===closedKey).open,false);
get('search').value='AirPrint';get('search').oninput();
assert.equal(descendants(get('list')).filter(e=>e.className==='row').length,1);
assert(get('list').children.some(e=>e.textContent==='Archived · 1'));
console.log('UI checks passed: refresh, search, dialog pause, visibility, retry backoff, prepare before confirmation, recheck, changed revision confirmation, failed refresh blocks deletion.');})().catch(e=>{console.error(e);process.exit(1);});
