import assert from 'node:assert/strict'
import test from 'node:test'

import { createPocStateStore } from './poc-state-store.mjs'
import { inspectPrepBootstrap, reconcilePrepBootstrap } from './poc-prep-bootstrap.mjs'

const environment = Object.freeze({
  POC_K9_SYSTEM_SUBJECT_ID: 'prep39083-k9-system',
  POC_K9_WORKSPACE_ID: '00000000-0000-4000-8000-000000000061',
  POC_MCP_SUBJECT_ID: 'prep39083-mcp-service',
  POC_MCP_WORKSPACE_ID: '00000000-0000-4000-8000-000000000061',
  POC_MCP_SERVICE_TOKEN: 'x'.repeat(48),
})

test('PREP bootstrap creates one admin and distinct K9/MCP identities exactly once', async () => {
  const stateStore = createPocStateStore()
  const first = await reconcilePrepBootstrap({
    stateStore,
    environment,
    administrator: { username: 'admin', password: 'correct horse battery staple' },
    randomPassword: () => 'service password that is never logged',
  })
  assert.deepEqual(first.created, ['ADMIN', 'K9', 'MCP'])
  assert.equal(first.administrators.length, 1)
  assert.deepEqual(first.services.map((item) => item.status), ['PRESENT', 'PRESENT'])
  assert.notEqual(first.services[0].subject_id, first.services[1].subject_id)

  const second = await reconcilePrepBootstrap({
    stateStore,
    environment,
    randomPassword: () => assert.fail('idempotent reconciliation must not generate a password'),
  })
  assert.deepEqual(second.created, [])
  assert.equal(second.administrators.length, 1)
  assert.deepEqual(second.services.map((item) => item.status), ['PRESENT', 'PRESENT'])
  await stateStore.close()
})

test('PREP bootstrap requires a hidden admin password only when no admin exists', async () => {
  const stateStore = createPocStateStore()
  await assert.rejects(
    reconcilePrepBootstrap({ stateStore, environment }),
    (error) => error.code === 'PREP_ADMIN_REQUIRED',
  )
  const inspected = await inspectPrepBootstrap({ stateStore, environment })
  assert.equal(inspected.administrators.length, 0)
  assert.deepEqual(inspected.services.map((item) => item.status), ['ABSENT', 'ABSENT'])
  await stateStore.close()
})

test('PREP bootstrap rejects shared K9/MCP Subject identity', async () => {
  const stateStore = createPocStateStore()
  await assert.rejects(
    inspectPrepBootstrap({
      stateStore,
      environment: { ...environment, POC_MCP_SUBJECT_ID: environment.POC_K9_SYSTEM_SUBJECT_ID },
    }),
    (error) => error.code === 'PREP_SERVICE_SUBJECT_COLLISION',
  )
  await stateStore.close()
})
