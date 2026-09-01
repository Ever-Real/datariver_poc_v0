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

test('requires the exact active Table grant and feature capability without TAG-derived grade authority', () => {
  const allowed = principal()
  assert.equal(evaluateTableDataAccess(allowed, tableA, 'catalog'), true)
  assert.equal(evaluateTableDataAccess(allowed, tableB, 'catalog'), false)
  assert.equal(evaluateTableDataAccess(allowed, tableA, 'governance'), true)
  assert.equal(evaluateTableDataAccess({ ...allowed, capabilitySet: new Set() }, tableA, 'catalog'), false)

  const systemAssignedWithoutGrant = principal({ role: 'developer', grants: [] })
  assert.deepEqual([...systemAssignedWithoutGrant.systemIds], ['system-a'])
  assert.equal(evaluateTableDataAccess(systemAssignedWithoutGrant, tableA, 'catalog'), false)
})

test('fails closed for malformed identity and non-TABLE data while preserving bounded Admin data bypass', () => {
  const viewer = principal()
  assert.equal(canReadAsset(viewer, { id: tableA, dataset_kind: 'TABLE' }), true)
  assert.equal(canReadAsset(viewer, tableAsset(tableA, { grade: 'invalid' })), true)
  assert.equal(canReadAsset(viewer, tableAsset(tableA, { kind: 'VIEW' })), false)
  assert.equal(evaluateTableDataAccess(viewer, 'urn:li:dataset:(malformed', 'catalog'), false)

  const admin = principal({ role: 'admin', maxSecurityGrade: null, grants: [], allowedCells: [] })
  assert.equal(evaluateTableDataAccess(admin, tableB, 'catalog'), true)
  assert.equal(evaluateTableDataAccess(admin, 'not-a-dataset-urn', 'catalog'), false)
  assert.equal(canReadAsset(admin, tableAsset(tableB, { grade: 'restricted', kind: 'VIEW' })), true)
  assert.doesNotThrow(() => assertAssetMutation(admin, tableAsset(tableB, { grade: 'restricted' })))
  assert.throws(
    () => assertAssetMutation(admin, tableAsset(tableB, { grade: 'restricted', kind: 'VIEW' })),
    { code: 'TABLE_DATA_FORBIDDEN' },
  )
  assert.doesNotThrow(() => assertAssetMutation(admin, tableAsset(tableB, { grade: 'invalid' })))
})

test('rehydrating each request immediately observes grant removal while arbitrary TAG changes do not alter authority', () => {
  assert.equal(canReadAsset(principal(), tableAsset(tableA), 'catalog'), true)
  assert.equal(canReadAsset(principal({ grants: [] }), tableAsset(tableA), 'catalog'), false)
  for (const tag of [
    'restricted', 'credential', 'confidential', 'critical',
    'CLASSIFICATION:INTERNAL', 'classfication: typo',
  ]) {
    assert.equal(canReadAsset(principal(), { ...tableAsset(tableA), tags: [tag] }, 'catalog'), true)
    assert.equal(canReadAsset(principal({ grants: [] }), { ...tableAsset(tableA), tags: [tag] }, 'catalog'), false)
  }
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
