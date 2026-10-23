const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync('antigravity/files.html','utf8');
const source=html.slice(html.indexOf('async function request('),html.indexOf('function showFilesError'));
let response,options,timer,cleared=0,calls=0;
const ctx=vm.createContext({AbortController,Error,JSON,csrf:'token',scoped:x=>x+'?area=outputs',setTimeout:fn=>{timer=fn;return 1;},clearTimeout:()=>cleared++,fetch:async(url,opts)=>{calls++;options=opts;if(response instanceof Error)throw response;return response;}});
vm.runInContext(source,ctx);
const call=()=>vm.runInContext("request('file-list')",ctx);
(async()=>{
 response={ok:true,status:200,headers:{get:()=> 'text/html'},json:()=>{throw Error('must not parse HTML');}};
 await assert.rejects(call(),e=>e.reopen===true);
 response={ok:false,status:403,headers:{get:()=> 'application/json'}};
 await assert.rejects(call(),e=>e.reopen===true);
 response={ok:true,status:200,headers:{get:()=> 'application/json'},json:async()=>({entries:[]})};
 assert.deepEqual(await call(),{entries:[]});assert.equal(options.cache,'no-store');assert(options.signal);
 response=Object.assign(new Error('aborted'),{name:'AbortError'});await assert.rejects(call(),/timed out/);
 response={ok:true,status:200,headers:{get:()=> 'application/json'},json:async()=>{throw Error('bad JSON');}};
 await assert.rejects(call(),/incomplete response/);
 assert.equal(calls,5);assert.equal(cleared,5);
 assert(html.includes("$('#count').textContent='Listing unavailable'"));
 console.log('Files recovery checks passed: HTML/auth errors, timeout, malformed response, uncached success, no automatic retries.');
})().catch(e=>{console.error(e);process.exit(1);});

(async()=>{
 let calls=0,delays=[],topReloads=0,frameReloads=0,saved;
 const state={hidden:false};
 const recovery=vm.createContext({Error,TypeError,JSON,Promise,encodeURIComponent,
  document:state,status:{textContent:''},area:'outputs',current:'paper-trader',
  sessionStorage:{setItem:(key,value)=>{saved=JSON.parse(value);}},
  window:{top:{location:{reload:()=>topReloads++}},location:{reload:()=>frameReloads++}},
  setTimeout:(fn,ms)=>{delays.push(ms);fn();},
  request:async()=>{calls++;if(calls<3)throw Object.assign(Error('offline'),{retryable:true});return {path:'paper-trader'};}
 });
 vm.runInContext(html.slice(html.indexOf('async function requestListing('),html.indexOf('function showFilesError')),recovery);
 assert.equal((await vm.runInContext("requestListing('paper-trader')",recovery)).path,'paper-trader');
 assert.equal(calls,3);assert.deepEqual(delays,[1000,3000]);
 calls=0;recovery.request=async()=>{calls++;throw Object.assign(Error('expired'),{retryable:true});};
 await assert.rejects(vm.runInContext("requestListing('')",recovery),/expired/);assert.equal(calls,3);
 calls=0;state.hidden=true;
 await assert.rejects(vm.runInContext("requestListing('')",recovery),/expired/);assert.equal(calls,1);
 state.hidden=false;calls=0;recovery.request=async()=>{calls++;throw Error('not found');};
 await assert.rejects(vm.runInContext("requestListing('')",recovery),/not found/);assert.equal(calls,1);
 vm.runInContext('reopenFiles()',recovery);assert.equal(topReloads,1);assert.equal(frameReloads,0);
 assert.deepEqual(saved,{area:'outputs',path:'paper-trader'});
 recovery.window.top.location.reload=()=>{throw Error('cross origin');};
 vm.runInContext('reopenFiles()',recovery);assert.equal(frameReloads,1);
 console.log('Files resume checks passed: bounded retries, hidden-page stop, permanent errors, HA shell reload, saved folder, iframe fallback.');
})().catch(e=>{console.error(e);process.exitCode=1;});
