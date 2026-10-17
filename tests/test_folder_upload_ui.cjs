const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('antigravity/files.html','utf8');
new vm.Script(source.match(/<script>([\s\S]*?)<\/script>/)[1]);
const script=source.slice(source.indexOf('function folderUploadPlan'),source.indexOf("$('#uploadKind').onchange"));
let calls=[],failAt='',collision=false;
const context=vm.createContext({window:{addEventListener(){}},TextEncoder,Uint8Array,btoa, csrf:'test', scoped:x=>x, fetch:async(url,options)=>{const q=new URL(url,'http://test').searchParams;const body={action:'upload',path:q.get('path'),name:q.get('name'),file:options.body};calls.push(body);if(body.name===failAt)throw Error('Rejected');return {ok:true,json:async()=>({ok:true})};}, current:'destination', $:()=>({}),request:async(_,body)=>{
 calls.push(body);if(collision||body.name===failAt)throw Error('Rejected');
}});
vm.runInContext(script,context);
vm.runInContext("sendUpload=async(file,path,name)=>{checkUploadCancelled();await fetch('file-upload?path='+encodeURIComponent(path)+'&name='+encodeURIComponent(name),{body:file});}",context);
function file(path,size=1){return {webkitRelativePath:path,size,arrayBuffer:async()=>new Uint8Array([65]).buffer};}
async function run(files){context.files=files;return vm.runInContext('uploadFolder(files)',context);}
(async()=>{
 await run([file('project/.hidden'),file('project/.config/settings'),file('project/sub/file')]);
 assert.deepEqual(calls.filter(x=>x.action==='mkdir').map(x=>[x.path,x.name]),[['destination','project'],['destination/project','.config'],['destination/project','sub']]);
 assert(calls.some(x=>x.action==='upload'&&x.path==='destination/project/.config'&&x.name==='settings'&&x.file.size===1));
 for(const files of [[],[file('project/../secret')],[file('project/huge',524288001)],[file('a/x'),file('b/y')],[file('a/x'),file('a/x')],[file('a/x'),file('a/x/y')]]){
  calls=[];await assert.rejects(run(files));assert.equal(calls.length,0);
 }
 calls=[];await run([file('project/large',524288000)]);assert(calls.some(x=>x.file&&x.file.size===524288000));
 calls=[];collision=true;await assert.rejects(run([file('project/file')]));assert.equal(calls.length,1);collision=false;
 calls=[];failAt='second';await assert.rejects(run([file('project/first'),file('project/second')]),/Partial folder retained at destination\/project/);
 assert(!calls.some(x=>x.action==='delete'));
 console.log('Folder upload checks passed: structure, hidden files, preflight, collisions and partial-failure reporting.');
})().catch(e=>{console.error(e);process.exit(1);});
