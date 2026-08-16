import assert from 'node:assert/strict'
import test from 'node:test'

import {
  activeSystemIdsForTable,
  applyTableSystemMappingCommand,
  normalizeTableSystemMappingDocument,
  securityGradeRank,
  tableSecurityGrade,
  tableSystemCandidates,
} from './poc-table-system-mappings.mjs'

const systems = [
  { system_id: 'system-a', active: true },
  { system_id: 'system-b', active: true },
  { system_id: 'system-archived', active: false },
]
const assets = [
  { id: 'urn:table:a', name: 'table_a', dataset_kind: 'TABLE', platform: 'postgres', database_name: 'db', schema_name: 'schema_a', tags: [] },
  { id: 'urn:table:b', name: 'table_b', dataset_kind: 'TABLE', platform: 'postgres', database_name: 'db', schema_name: 'schema_a', tags: ['restricted'] },
  { id: 'urn:table:c', name: 'table_c', dataset_kind: 'TABLE', platform: 'postgres', database_name: 'db', schema_name: 'schema_b', tags: ['credential', 'restricted'] },
  { id: 'urn:view:a', name: 'view_a', dataset_kind: 'VIEW', platform: 'postgres', database_name: 'db', schema_name: 'schema_a', tags: [] },
]

test('normalizes a bounded exact Table-System document and rejects duplicate pairs', () => {
  assert.deepEqual(normalizeTableSystemMappingDocument(null), { schema_version: 1, bindings: [] })
  const created = applyTableSystemMappingCommand(null, {
    action: 'ASSIGN', table_ids: ['urn:table:a'], system_ids: ['system-a'], reason: 'initial exact Table mapping',
  }, 'admin', '2026-08-16T01:00:00.000Z')
  assert.equal(created.changed, 1)
  assert.equal(created.document.bindings[0].version, 1)
  assert.throws(() => normalizeTableSystemMappingDocument({
    schema_version: 1,
    bindings: [created.document.bindings[0], created.document.bindings[0]],
  }), { code: 'TABLE_SYSTEM_MAPPING_INVALID' })
})

test('assigns and removes N:M pairs idempotently while preserving inactive history', () => {
  const assigned = applyTableSystemMappingCommand(null, {
    action: 'ASSIGN',
    table_ids: ['urn:table:a', 'urn:table:b'],
    system_ids: ['system-a', 'system-b'],
    reason: 'assign selected exact Tables',
  }, 'admin', '2026-08-16T01:00:00.000Z')
  assert.equal(assigned.changed, 4)
  assert.deepEqual(activeSystemIdsForTable(assigned.document, 'urn:table:a', new Set(['system-a', 'system-b'])), ['system-a', 'system-b'])
  assert.equal(applyTableSystemMappingCommand(assigned.document, {
    action: 'ASSIGN', table_ids: ['urn:table:a'], system_ids: ['system-a'], reason: 'repeat selected Table mapping',
  }, 'admin').changed, 0)

  const removed = applyTableSystemMappingCommand(assigned.document, {
    action: 'REMOVE', table_ids: ['urn:table:a'], system_ids: ['system-a'], reason: 'remove selected Table mapping',
  }, 'admin', '2026-08-16T02:00:00.000Z')
  assert.equal(removed.changed, 1)
  const row = removed.document.bindings.find((item) => item.table_identity === 'urn:table:a' && item.system_id === 'system-a')
  assert.equal(row.active, false)
  assert.equal(row.version, 2)
})

test('derives only exact normalized security tags and gives restricted precedence', () => {
  assert.equal(tableSecurityGrade({ tags: ['not-restricted', 'CLASSIFICATION:RESTRICTED'] }), 'normal')
  assert.equal(tableSecurityGrade({ tags: [' Restricted '] }), 'restricted')
  assert.equal(tableSecurityGrade({ tags: [{ urn: 'urn:li:tag:credential', name: 'anything' }, 'restricted'] }), 'restricted')
  assert.deepEqual(['normal', 'credential', 'restricted'].map(securityGradeRank), [0, 1, 2])
  assert.throws(() => securityGradeRank('confidential'), /outside the canonical product policy/)
})

test('returns TABLE-only candidates with search, schema, System and grade filters', () => {
  const assigned = applyTableSystemMappingCommand(null, {
    action: 'ASSIGN', table_ids: ['urn:table:a', 'urn:table:b'], system_ids: ['system-a'], reason: 'candidate mapping fixture',
  }, 'admin', '2026-08-16T01:00:00.000Z')
  assert.deepEqual(tableSystemCandidates({ assets, document: assigned.document, systems }).map((item) => item.table_identity), [
    'urn:table:a', 'urn:table:b', 'urn:table:c',
  ])
  assert.deepEqual(tableSystemCandidates({ assets, document: assigned.document, systems, systemId: 'system-a' }).map((item) => item.table_identity), [
    'urn:table:a', 'urn:table:b',
  ])
  assert.deepEqual(tableSystemCandidates({ assets, document: assigned.document, systems, schema: 'schema_a', securityGrade: 'restricted' }).map((item) => item.table_identity), [
    'urn:table:b',
  ])
  assert.deepEqual(tableSystemCandidates({ assets, document: assigned.document, systems, query: 'table_c' }).map((item) => item.security_grade), ['restricted'])
})
