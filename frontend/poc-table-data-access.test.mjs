import assert from 'node:assert/strict'
import test from 'node:test'

import { assertAssetMutation, buildPocPrincipal, canReadAsset } from './poc-authorization.mjs'
import { createPocStateStore } from './poc-state-store.mjs'
import { evaluateTableDataAccess } from './poc-table-data-access.mjs'

const tableA = 'urn:li:dataset:(urn:li:dataPlatform:postgres,db.schema.table_a,PROD)'
const tableB = 'urn:li:dataset:(urn:li:dataPlatform:postgres,db.schema.table_b,PROD)'
const accessDocument = {
  systems: [{ system_id: 'system-a', active: true }],
  system_schema_scopes: [],
  system_assignments: [
    { subject_id: 'subject', system_id: 'system-a', responsibility: 'DEVELOPER', active: true },
  ],
}

function principal({
  role = 'viewer',
  maxSecurityGrade = 'normal',
  grants = [tableA],
  allowedCells = [
    ['catalog', role, 'normal'],
    ['chat', role, 'normal'],
  ],
} = {}) {
  return buildPocPrincipal({
    authentication: { subjectId: 'subject' },
    accessDocument,
    accessUser: {
      subject_id: 'subject', role, active: true, max_security_grade: maxSecurityGrade,
    },
    userTableGrants: grants.map((tableUrn) => ({ tableUrn, active: true })),
    featureSecurityPolicy: {
      cells: allowedCells.map(([feature, cellRole, grade]) => ({
        feature, role: cellRole, grade, allow: true,
      })),
    },
  })
}

function tableAsset(id, { grade = 'normal', kind = 'TABLE' } = {}) {
  return { id, dataset_kind: kind, security_grade: grade, tags: [] }
}

test('requires the exact active Table grant, grade ceiling and fixed feature cell together', () => {
  const allowed = principal()
  assert.equal(evaluateTableDataAccess(allowed, tableA, 'normal', 'catalog'), true)
  assert.equal(evaluateTableDataAccess(allowed, tableB, 'normal', 'catalog'), false)
  assert.equal(evaluateTableDataAccess(allowed, tableA, 'credential', 'catalog'), false)
  assert.equal(evaluateTableDataAccess(allowed, tableA, 'normal', 'governance'), false)

  const credential = principal({
    maxSecurityGrade: 'credential',
    allowedCells: [['catalog', 'viewer', 'credential']],
  })
  assert.equal(evaluateTableDataAccess(credential, tableA, 'credential', 'catalog'), true)

  const systemAssignedWithoutGrant = principal({ role: 'developer', grants: [] })
  assert.deepEqual([...systemAssignedWithoutGrant.systemIds], ['system-a'])
  assert.equal(evaluateTableDataAccess(systemAssignedWithoutGrant, tableA, 'normal', 'catalog'), false)
})

test('fails closed for malformed identity, unresolved grade and non-TABLE data while preserving bounded Admin data bypass', () => {
  const viewer = principal()
  assert.equal(canReadAsset(viewer, { id: tableA, dataset_kind: 'TABLE' }), false)
  assert.equal(canReadAsset(viewer, tableAsset(tableA, { grade: 'invalid' })), false)
  assert.equal(canReadAsset(viewer, tableAsset(tableA, { kind: 'VIEW' })), false)
  assert.equal(evaluateTableDataAccess(viewer, 'urn:li:dataset:(malformed', 'normal'), false)

  const admin = principal({ role: 'admin', maxSecurityGrade: null, grants: [], allowedCells: [] })
  assert.equal(evaluateTableDataAccess(admin, tableB, 'restricted', 'catalog'), true)
  assert.equal(evaluateTableDataAccess(admin, tableB, 'invalid', 'catalog'), false)
  assert.equal(evaluateTableDataAccess(admin, 'not-a-dataset-urn', 'normal', 'catalog'), false)
  assert.equal(canReadAsset(admin, tableAsset(tableB, { grade: 'restricted', kind: 'VIEW' })), true)
  assert.doesNotThrow(() => assertAssetMutation(admin, tableAsset(tableB, { grade: 'restricted' })))
  assert.throws(
    () => assertAssetMutation(admin, tableAsset(tableB, { grade: 'restricted', kind: 'VIEW' })),
    { code: 'TABLE_DATA_FORBIDDEN' },
  )
  assert.throws(
    () => assertAssetMutation(admin, tableAsset(tableB, { grade: 'invalid' })),
    { code: 'TABLE_DATA_FORBIDDEN' },
  )
})

test('rehydrating each request immediately observes grant removal, grade change and policy change', () => {
  assert.equal(canReadAsset(principal(), tableAsset(tableA), 'catalog'), true)
  assert.equal(canReadAsset(principal({ grants: [] }), tableAsset(tableA), 'catalog'), false)
  assert.equal(canReadAsset(principal({ maxSecurityGrade: 'normal' }), tableAsset(tableA, { grade: 'credential' }), 'catalog'), false)
  assert.equal(canReadAsset(principal({ allowedCells: [] }), tableAsset(tableA), 'catalog'), false)
})

test('filters the memory vector candidate set before cosine ranking and returns early for empty scope', async () => {
  const stateStore = createPocStateStore()
  const projectionScope = 'catalog-inventory-v1:table-access-test'
  const generation = '1'.repeat(64)
  const bindingHash = 'a'.repeat(64)
  await stateStore.write(projectionScope, { source_generation: generation })
  await stateStore.replaceCatalogEmbeddingGeneration(bindingHash, projectionScope, generation, [
    {
      bindingHash, assetUrn: tableA, sourceHash: '2'.repeat(64), sourceGeneration: generation,
      contentText: 'allowed but less similar', metadata: tableAsset(tableA), embedding: [0.8, 0.2],
    },
    {
      bindingHash, assetUrn: tableB, sourceHash: '3'.repeat(64), sourceGeneration: generation,
      contentText: 'unauthorized exact match', metadata: tableAsset(tableB), embedding: [1, 0],
    },
  ], [tableA, tableB])

  assert.deepEqual(await stateStore.searchCatalogEmbeddings(
    bindingHash, projectionScope, generation, [1, 0], 10, new Set(),
  ), [])
  const results = await stateStore.searchCatalogEmbeddings(
    bindingHash, projectionScope, generation, [1, 0], 10, new Set([tableA]),
  )
  assert.deepEqual(results.map((item) => item.assetUrn), [tableA])

  await stateStore.close()
})
