import assert from 'node:assert/strict'
import test from 'node:test'

import { createPocStateStore } from './poc-state-store.mjs'
import {
  inspectPrepBootstrap,
  inspectPrepOwnedPartial,
  reconcilePrepBootstrap,
} from './poc-prep-bootstrap.mjs'
import { computeK9PolicyHash, K9_POLICIES } from './poc-k9-managed-graphs.mjs'

const environment = Object.freeze({
  POC_K9_SCHEDULER_ENABLED: 'true',
  POC_K9_STUDIO_DATABASE_URL: 'postgres://readonly@studio.example.test/studio',
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

test('PREP bootstrap defers K9 identity when Studio authority is not configured', async () => {
  const stateStore = createPocStateStore()
  const deferredEnvironment = {
    ...environment,
    POC_K9_SCHEDULER_ENABLED: 'false',
    POC_K9_STUDIO_DATABASE_URL: '',
    POC_K9_SYSTEM_SUBJECT_ID: '',
    POC_K9_WORKSPACE_ID: '',
  }
  const first = await reconcilePrepBootstrap({
    stateStore,
    environment: deferredEnvironment,
    administrator: { username: 'admin', password: 'correct horse battery staple' },
    randomPassword: () => 'service password that is never logged',
  })
  assert.equal(first.k9_mode, 'DEFERRED')
  assert.deepEqual(first.created, ['ADMIN', 'MCP'])
  assert.deepEqual(first.services.map((item) => item.name), ['MCP'])
  assert.deepEqual(first.services.map((item) => item.status), ['PRESENT'])

  const second = await reconcilePrepBootstrap({
    stateStore,
    environment: deferredEnvironment,
    randomPassword: () => assert.fail('deferred rerun must not create another service identity'),
  })
  assert.deepEqual(second.created, [])
  assert.equal(second.administrators.length, 1)
  await stateStore.close()
})

function ownedFootprint(credentialCount, overrides = {}) {
  const { table_counts: tableOverrides = {}, ...rest } = overrides
  return {
    table_counts: {
      poc_state: 2,
      poc_catalog_embedding: 0,
      poc_change_history_sources: 0,
      poc_change_history_ledger_events: 0,
      poc_change_history_checkpoints: 0,
      poc_change_history_cr_link_events: 0,
      poc_local_credentials: credentialCount,
      poc_local_sessions: 0,
      poc_user_table_grants: 0,
      poc_knowledge_ingestion_jobs: 0,
      poc_knowledge_source_rows: 0,
      poc_k9_managed_graph_policies: 0,
      poc_k9_refresh_runs: 0,
      ...tableOverrides,
    },
    state_scopes: ['change-history-access-v1', 'core'],
    active_session_count: 0,
    k9_runs: [],
    ...rest,
  }
}

test('legacy owned-partial inspection accepts only canonical bootstrap identities', async () => {
  const stateStore = createPocStateStore()
  const deferredEnvironment = {
    ...environment,
    POC_K9_SCHEDULER_ENABLED: 'false',
    POC_K9_STUDIO_DATABASE_URL: '',
    POC_K9_SYSTEM_SUBJECT_ID: '',
    POC_K9_WORKSPACE_ID: '',
  }
  await reconcilePrepBootstrap({
    stateStore,
    environment: deferredEnvironment,
    administrator: { username: 'admin', password: 'correct horse battery staple' },
    randomPassword: () => 'service password that is never logged',
  })
  const inspector = {
    ...stateStore,
    inspectPrepDeploymentFootprint: async () => ownedFootprint(2),
    listK9ManagedGraphAssets: async () => [],
  }
  const inspected = await inspectPrepOwnedPartial({ stateStore: inspector, environment: deferredEnvironment })
  assert.equal(inspected.status, 'OWNED_PARTIAL')
  assert.equal(inspected.footprint.k9_run_count, 0)

  await assert.rejects(
    inspectPrepOwnedPartial({
      stateStore: {
        ...inspector,
        inspectPrepDeploymentFootprint: async () => ownedFootprint(2, {
          table_counts: { poc_user_table_grants: 1 },
        }),
      },
      environment: deferredEnvironment,
    }),
    (error) => error.code === 'PREP_LEGACY_PARTIAL_BUSINESS_STATE_PRESENT',
  )
  await stateStore.close()
})

test('legacy owned-partial inspection recognizes canonical managed K9 run namespaces', async () => {
  const stateStore = createPocStateStore()
  await reconcilePrepBootstrap({
    stateStore,
    environment,
    administrator: { username: 'admin', password: 'correct horse battery staple' },
    randomPassword: () => 'service password that is never logged',
  })
  const namespace = 'k9-canonical-namespace-v6'
  const policies = Object.values(K9_POLICIES).map((base) => {
    const policy = {
      ...base,
      subject_id: environment.POC_K9_SYSTEM_SUBJECT_ID,
      workspace_id: environment.POC_K9_WORKSPACE_ID,
    }
    return {
      ...policy,
      policy_hash: computeK9PolicyHash(policy),
      active_release_pointer: namespace,
      latest_run_id: '00000000-0000-4000-8000-000000000071',
    }
  })
  const runs = policies.map((policy, index) => ({
    run_id: `00000000-0000-4000-8000-00000000007${index + 1}`,
    graph_id: policy.graph_id,
    status: 'RUN',
    policy_hash: policy.policy_hash,
    active_release_pointer: namespace,
  }))
  const inspector = {
    ...stateStore,
    inspectPrepDeploymentFootprint: async () => ownedFootprint(3, {
      table_counts: { poc_k9_managed_graph_policies: 2, poc_k9_refresh_runs: 2 },
      state_scopes: [
        'change-history-access-v1',
        'core',
        'k9-scheduler-v1:datariver:poc:k9-scheduler:v1',
      ],
      k9_runs: runs,
    }),
    listK9ManagedGraphAssets: async () => policies,
  }
  const inspected = await inspectPrepOwnedPartial({ stateStore: inspector, environment })
  assert.deepEqual(inspected.footprint.neo4j_namespaces, [namespace])
  assert.equal(inspected.footprint.k9_run_count, 2)
  await stateStore.close()
})
