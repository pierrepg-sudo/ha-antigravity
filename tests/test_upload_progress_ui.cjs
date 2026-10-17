const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('antigravity/files.html','utf8');
new vm.Script(source.match(/<script>([\s\S]*?)<\/script>/)[1]);
const script=source.slice(source.indexOf('let uploadState='),source.indexOf('async function uploadFolder'));
let xhr,tick,now=0;const elements={};
class XHR{
 constructor(){xhr=this;this.upload={};}
 open(method,url){this.url=url;}
 setRequestHeader(){}
 send(file){this.file=file;}
 abort(){this.aborted=true;this.onabort();}
 reply(status,body){this.status=status;this.responseText=body;this.onload();}
}
const ctx=vm.createContext({XMLHttpRequest:XHR,Date:{now:()=>now},setInterval:fn=>(tick=fn,1),clearInterval:()=>{tick=null;},scoped:x=>x,csrf:'test',size:n=>n+' B',$:id=>elements[id]||(elements[id]={})});
vm.runInContext(script,ctx);
const start=()=>vm.runInContext("sendUpload({size:100},'project','large.zip')",ctx);
(async()=>{
 let p=start();assert.equal(xhr.file.size,100);xhr.upload.onprogress({loaded:50});assert.equal(elements['#uploadBar'].value,50);
 xhr.upload.onload();assert(elements['#uploadProgress'].textContent.includes('waiting for server'));xhr.reply(200,'{"ok":true}');await p;assert.equal(tick,null);
 p=start();xhr.abort();await assert.rejects(p,/cancelled/);assert.equal(tick,null);
 p=start();now+=120001;tick();await assert.rejects(p,/stalled/);assert(xhr.aborted);
 p=start();xhr.upload.onload();now+=180001;tick();await assert.rejects(p,/may have arrived/);
 p=start();xhr.reply(413,'<html>Too large</html>');await assert.rejects(p,/HTTP 413/);
 p=start();xhr.reply(409,'{"error":"Already exists"}');await assert.rejects(p,/Already exists/);
 vm.runInContext('uploadState={done:100,total:200}',ctx);p=start();xhr.upload.onprogress({loaded:50});assert.equal(elements['#uploadBar'].value,75);xhr.reply(200,'{"ok":true}');await p;assert.equal(vm.runInContext('uploadState.done',ctx),200);
 console.log('Upload progress checks passed: bytes, folder totals, finalizing, cancellation, stalls and server errors.');
})().catch(e=>{console.error(e);process.exit(1);});
