import assert from 'node:assert/strict'
import test from 'node:test'
import {pathToFileURL} from 'node:url'
import {resolve} from 'node:path'
const {retryAllowed,requestBudget,withReadinessDeadline}=await import(pathToFileURL(resolve('scripts/readiness.mjs')))

test('authorization/config/schema/terminal failures never consume the progress budget', () => {
  for (const error of [{status:401,retryable:true}, {status:403,retryable:true}, {message:'MCL_SOURCE_NOT_CONFIGURED'}, {classification:'PREP_SCHEMA_MISMATCH',retryable:true}, {message:'K9_SEMANTIC_NOT_READY',terminal:true},new Error('unknown')]) assert.equal(retryAllowed(error),false)
})
test('only explicit transient read errors and progress states retry', () => {
  for (const error of [{status:429,retryable:true}, {retryable:true}, {classification:'PREP_SMOKE_K9_NOT_READY'}, {message:'MCL_CURRENT_NOT_READY'}]) assert.equal(retryAllowed(error),true)
})
test('request timeout cannot outlive readiness stage budget', async () => {
  assert.equal(requestBudget(42),42)
  await withReadinessDeadline(Date.now()+100,async()=>{assert(requestBudget(300000)<=100);assert(requestBudget(300000)>0)})
  assert.equal(requestBudget(42),42)
})
