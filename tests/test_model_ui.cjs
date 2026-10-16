const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(require('path').join(__dirname,'../antigravity/mobile.html'),'utf8');
const script=source.slice(source.indexOf("let modelConversation="),source.indexOf("const status=document.querySelector"));
class Element{constructor(){this.children=[];this.disabled=false;}replaceChildren(){this.children=[];}append(e){this.children.push(e);}}
const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
let fail=true,timeout=false;
const context=vm.createContext({document:{getElementById:get,createElement:()=>new Element()},AbortController,setTimeout,clearTimeout,csrf:'test',window:{confirm:()=>true,location:{}},fetch:async()=>{
 if(timeout)throw Object.assign(new Error('timeout'),{name:'AbortError'});
 return {ok:!fail,json:async()=>fail?{error:'Unsupported catalog'}:{id:'test',models:[{id:'gemini-example',name:'Gemini Example'}],selected:''}};
}});
(async()=>{
 vm.runInContext(script,context);await vm.runInContext('refreshModels()',context);
 assert.equal(get('modelSelect').children[0].textContent,'Models unavailable');assert(get('modelSelect').disabled);assert(!get('reloadModels').disabled);
 fail=false;await vm.runInContext('refreshModels()',context);assert.equal(get('modelSelect').children.length,2);assert(!get('modelSelect').disabled);
 timeout=true;await vm.runInContext('refreshModels()',context);assert.equal(get('modelSelect').children[0].textContent,'Models unavailable');assert(get('modelStatus').textContent.includes('timed out'));assert(!get('reloadModels').disabled);
 console.log('Model UI checks passed: errors clear Loading, retry succeeds, timeouts remain retryable.');
})().catch(e=>{console.error(e);process.exit(1);});
