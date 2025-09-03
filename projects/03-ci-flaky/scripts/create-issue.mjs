import fs from 'fs';
const p='database.json';
if(!fs.existsSync(p)){ console.log('No database.json'); process.exit(0); }
const db=JSON.parse(fs.readFileSync(p,'utf8'));
const flaky=Object.entries(db.history).filter(([,arr])=>{ const last2=arr.slice(-2); return last2.length===2 && last2[0].failed && !last2[1].failed;}).map(([n])=>n);
if(!flaky.length){ console.log('No flaky tests'); process.exit(0); }
console.log('# Flaky tests detected\n' + flaky.map(n=>`- ${n}`).join('\n'));
