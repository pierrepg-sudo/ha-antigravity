const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('antigravity/files.html','utf8');
const script=source.slice(source.indexOf('async function downloadItem'),source.indexOf('const icons='));
let failure=true,clicked=false,links=[];
const status={textContent:'',append:link=>links.push(link)};
const context=vm.createContext({status,size:n=>n+' B',scoped:x=>x+'&area=outputs',document:{createElement:()=>({click:()=>{clicked=true;}})},request:async()=>{
 if(failure)throw Error('Folder contains a link');return {ticket:'ready',name:'project.zip',size:400};
}});
vm.runInContext(script,context);
(async()=>{
 await assert.rejects(vm.runInContext("downloadItem('project','project.zip',true)",context),/contains a link/);
 assert.equal(links.length,0);assert.equal(clicked,false);
 failure=false;await vm.runInContext("downloadItem('project','project.zip',true)",context);
 assert.equal(links.length,1);assert(links[0].href.includes('ticket=ready'));assert.equal(links[0].download,'project.zip');assert.equal(clicked,false);
 console.log('ZIP UI checks passed: failures are not downloaded; completed archives get a download link.');
})().catch(e=>{console.error(e);process.exit(1);});
