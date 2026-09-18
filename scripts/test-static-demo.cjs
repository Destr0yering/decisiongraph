const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const { randomUUID } = require('node:crypto');
const data = new Map();
const window = {location:{hostname:'localhost', search:'?sandbox=1',href:'http://localhost:8000/?sandbox=1'},
  localStorage:{getItem:k=>data.get(k),setItem:(k,v)=>data.set(k,v)},crypto:{randomUUID}};
vm.runInNewContext(fs.readFileSync('backend/app/static/static-demo.js','utf8'),{window,URL,URLSearchParams});
const request = window.DecisionGraphStaticDemo.request;
(async () => {
 const first = await request('/api/v1/decisions/run',{method:'POST'});
 assert.equal(first.status,'PENDING_APPROVAL');
 await request(`/api/v1/decisions/${first.id}/approve`,{method:'POST'});
 await request('/api/v1/events/invalidation',{method:'POST',body:JSON.stringify({asset_urn:first.dependencies[0].asset_urn})});
 await assert.rejects(()=>request(`/api/v1/decisions/${first.id}/approve`,{method:'POST'}), /Only pending/);
 const next = await request(`/api/v1/decisions/${first.id}/revalidate`,{method:'POST'});
 assert.equal(next.status,'PENDING_APPROVAL');
 await assert.rejects(()=>request(`/api/v1/decisions/${first.id}/revalidate`,{method:'POST'}), /replacement already exists/);
 await request(`/api/v1/decisions/${next.id}/approve`,{method:'POST'});
 const list = await request('/api/v1/decisions');
 assert.equal(list.find(x=>x.id===first.id).status,'SUPERSEDED');
 assert.equal(list.length,2);
 const comparison=await request(`/api/v1/decisions/${next.id}/comparison`);
 assert.ok(comparison.changes.length>0);
 assert.equal(next.analysis.rows.length,4);
 assert.equal(next.projection_status,'NOT_CONFIGURED');
 console.log('PASS: sandbox lifecycle, stale approval rejection, duplicate revision rejection, comparison, no external projection');
})().catch(e=>{console.error(e); process.exit(1)});
