import assert from 'node:assert/strict'
import test from 'node:test'
import { createServer } from 'node:http'
import { spawn } from 'node:child_process'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
const table='urn:li:dataset:(urn:li:dataPlatform:postgres,synthetic.table,PROD)'
const related='urn:li:dataset:(urn:li:dataPlatform:postgres,synthetic.child,PROD)'
async function fixture({k9='READY',mcl='CAPTURE_CAUGHT_UP',noTable=false,badEvidence=false,badRelation=false}={}) {
 const folder=await mkdtemp(join(tmpdir(),'datariver-focused-'))
 const password=join(folder,'password');const receipt=join(folder,'result.json')
 await writeFile(password,'synthetic-local-only',{mode:0o600})
 let pages=0;let chats=0
 const server=createServer(async(req,res)=>{
  const url=new URL(req.url,'http://synthetic.invalid');let body={};if(req.method==='POST'){let s='';for await(const c of req)s+=c;body=JSON.parse(s||'{}')}
  let result={};if(url.pathname==='/auth/login'){res.setHeader('set-cookie','synthetic=session');result={}}
  else if(url.pathname==='/poc-api/knowledge/managed-assets'){
   const id='a'.repeat(64);const projector={status:k9,desired_snapshot_id:id,active_snapshot_id:id}
   result={k9_lifecycle:{contract:'DATARIVER_K9_LIFECYCLE_STATUS_V2',source:projector,aggregate:{status:k9},projectors:{LINEAGE:projector,METADATA:projector,SEMANTIC:projector}},items:[{id:'graph',status:'READY',active_release_id:'release',projection_state:'READY'}]}
  } else if(url.pathname==='/api/v1/change-history/summary')result={capture_state:mcl,history_completeness:'EXACT'}
  else if(url.pathname==='/poc-api/datahub/catalog'){pages++;result=pages===1?{items:[{dataset_kind:'VIEW',id:'view',name:'view'}],page:{next_cursor:'page2'}}:{items:noTable?[]:[{id:table,name:'synthetic.table',dataset_kind:'TABLE'}],page:{next_cursor:null}}}
  else if(url.pathname==='/poc-api/datahub/lineage')result={center_asset_id:table,edges:[{source_asset_id:table,target_asset_id:related}]}
  else if(url.pathname==='/poc-api/llm/chat'){
   chats++;const general=body.question==='데이터 계보가 무엇인지 일반적으로 설명해줘.';const graph=body.mode==='GRAPH'||body.question.includes('downstream')
   result={route:{selected_mode:general?'GENERAL':graph?'GRAPH':'VECTOR'},answer:'Synthetic answer grounded in the returned synthetic evidence.',evidence:general||badEvidence?[]:[{id:table,source_locator:table,graph_nodes:[{id:table},{id:badRelation?'unrelated':related}]}]}
  } else if(url.pathname.endsWith('/versions'))result={items:[{is_current:true,status:'READY'}]}
  else if(url.pathname.endsWith('/snapshot'))result={release:{id:'release'},nodes:[{id:table}],edges:[{id:'synthetic-edge'}]}
  res.setHeader('content-type','application/json');res.end(JSON.stringify(result))
 })
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin=`http://127.0.0.1:${server.address().port}`
 try{
  const child=spawn(process.execPath,[resolve('scripts/accept_dev_deploy.mjs'),'--origin',origin,'--request-origin',origin,'--username','admin','--password-file',password,'--output',receipt],{stdio:'ignore'})
  const code=await new Promise(r=>child.on('close',r));const result=JSON.parse(await readFile(receipt,'utf8'));return{code,result,pages,chats}
 } finally{await new Promise(r=>server.close(r));await rm(folder,{recursive:true,force:true})}
}
test('bounded second-page target preserves all positive routes and relation readback',async()=>{const r=await fixture();assert.equal(r.code,0);assert.equal(r.pages,2);assert.equal(r.chats,5);for(const k of ['auto_chat','auto_graph','auto_search','vector_chat','graph_chat','knowledge_graph_preview'])assert.equal(r.result[k],'PASS')})
test('terminal semantic failure fails before any Chat mutation',async()=>{const r=await fixture({k9:'FAILED'});assert.equal(r.code,2);assert.equal(r.chats,0)})
test('missing MCL is not a success or a twenty-minute wait',async()=>{const r=await fixture({mcl:'SOURCE_NOT_CONFIGURED'});assert.equal(r.code,2);assert.equal(r.chats,0)})
test('no positive graph target is NO_TEST_DATA, not E2E PASS',async()=>{const r=await fixture({noTable:true});assert.equal(r.code,2);assert.equal(r.result.failure_code,'NO_TEST_DATA_GRAPH_RELATION')})
test('empty evidence cannot pass a successful HTTP response',async()=>{const r=await fixture({badEvidence:true});assert.equal(r.code,2);assert.equal(r.result.failure_code,'GRAPH_CHAT_CONTRACT')})
test('unrelated evidence cannot pass change-impact readback',async()=>{const r=await fixture({badRelation:true});assert.equal(r.code,2);assert.equal(r.result.failure_code,'GRAPH_CHAT_RELATION_READBACK_MISSING')})
