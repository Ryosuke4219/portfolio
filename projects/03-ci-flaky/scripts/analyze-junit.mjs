import fs from 'fs';
import { XMLParser } from 'fast-xml-parser';
const junitPath='junit-results.xml';
if(!fs.existsSync(junitPath)){ console.warn('No junit-results.xml'); process.exit(0); }
const xml=fs.readFileSync(junitPath,'utf8');
const parser=new XMLParser({ignoreAttributes:false,attributeNamePrefix:''});
const d=parser.parse(xml);
const cases=[];
function collect(ts){ if(!ts) return; const arr=Array.isArray(ts.testcase)?ts.testcase:(ts.testcase?[ts.testcase]:[]);
  for(const c of arr){ const failed=!!(c.failure||c.error); cases.push({name:`${c.classname||''}::${c.name}`,failed}); } }
if(d.testsuite) collect(d.testsuite);
if(d.testsuites){ const arr=Array.isArray(d.testsuites.testsuite)?d.testsuites.testsuite:[d.testsuites.testsuite]; for(const ts of arr) collect(ts);}
let db={history:{}}; const p='database.json'; if(fs.existsSync(p)) db=JSON.parse(fs.readFileSync(p,'utf8'));
for(const c of cases){ const h=db.history[c.name]||[]; h.push({ts:Date.now(),failed:c.failed}); db.history[c.name]=h.slice(-10); }
fs.writeFileSync(p,JSON.stringify(db,null,2));
const flaky=Object.entries(db.history).filter(([,arr])=>{ const last2=arr.slice(-2); return last2.length===2 && last2[0].failed && !last2[1].failed;}).map(([n])=>n);
console.log('Analyzed cases:',cases.length); console.log('Flaky detected:',flaky.length); if(flaky.length) console.log(flaky.join('\n'));
