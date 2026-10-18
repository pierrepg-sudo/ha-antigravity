const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync('antigravity/files.html','utf8');
const source=html.slice(html.indexOf('async function refreshProjects'),html.indexOf('async function renameItem'));
class Element{constructor(){this.children=[];}append(...items){this.children.push(...items);}replaceChildren(){this.children=[];}}
const elements=new Map();const get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
let selected;
const context=vm.createContext({$:get,document:{createElement:()=>new Element()},encodeURIComponent,button:(text,fn)=>({textContent:text,onclick:fn}),browse:async path=>{selected=path;},fetch:async()=>({ok:true,json:async()=>({projects:[{id:'remote',name:'Remote',paths:['/data/home/Remote'],folder:''},{id:'local',name:'Local',folder:'Local'}]})})});
vm.runInContext(source,context);
(async()=>{
 await vm.runInContext('refreshProjects()',context);
 const rows=get('#projectList').children;assert.equal(rows.length,2);
 assert.equal(rows[0].children[1].textContent,'/data/home/Remote');
 assert(rows[0].children[2].textContent.includes('not browsable'));
 assert(rows[0].children[3].children[0].href.endsWith('project=remote'));
 await rows[1].children[2].children[0].onclick();assert.equal(selected,'Local');
 assert(html.includes('conversations?action=new-project'));assert(html.includes('conversations?action=new-conversation'));
 console.log('Files project directory: both sources visible, external paths labelled, managed folders browsable, conversation project preserved.');
})().catch(e=>{console.error(e);process.exit(1);});
