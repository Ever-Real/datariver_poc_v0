import assert from 'node:assert/strict'
import test from 'node:test'

import {
  activeSystemIdsForTable,
  applyTableSystemMappingCommand,
  normalizeTableSystemMappingDocument,
  resolveTableSystemAuthority,
  securityGradeRank,
  tableAuthoritySnapshot,
  legacyTableTagGrade,
  tableSystemCandidates,
} from './poc-table-system-mappings.mjs'
import {
  normalizeSecurityGrade,
  compareSecurityGrades,
} from './poc-access-document.mjs'

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
  assert.deepEqual(normalizeTableSystemMappingDocument(null), { schema_version: 2, bindings: [], asset_snapshots: [] })
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

test('upgrades legacy mappings and retains a bounded authority snapshot for deleted-Table history', () => {
  const legacy = normalizeTableSystemMappingDocument({ schema_version: 1, bindings: [] })
  assert.deepEqual(legacy, { schema_version: 2, bindings: [], asset_snapshots: [] })
  const observedAt = '2026-08-26T01:00:00.000Z'
  const snapshot = tableAuthoritySnapshot(assets[0], observedAt)
  const assigned = applyTableSystemMappingCommand(legacy, {
    action: 'ASSIGN', table_ids: ['urn:table:a'], system_ids: ['system-a'],
    reason: 'retain exact authority evidence',
  }, 'admin', observedAt, [snapshot])
  assert.deepEqual(assigned.document.asset_snapshots, [{
    table_identity: 'urn:table:a', dataset_kind: 'TABLE', platform: 'postgres',
    database_name: 'db', schema_name: 'schema_a', asset_name: 'table_a',
    security_grade: 'normal', observed_at: observedAt,
  }])
  assert.throws(() => applyTableSystemMappingCommand(legacy, {
    action: 'ASSIGN', table_ids: ['urn:table:a'], system_ids: ['system-a'],
    reason: 'reject mismatched snapshot input',
  }, 'admin', observedAt, [{ ...snapshot, table_identity: 'urn:table:b' }]), {
    code: 'TABLE_SYSTEM_MAPPING_INVALID',
  })
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

test('canonical security grade helpers: normalize, rank, compare, tags, invalid', () => {
  assert.equal(normalizeSecurityGrade('normal'), 'normal')
  assert.equal(normalizeSecurityGrade('credential'), 'credential')
  assert.equal(normalizeSecurityGrade('restricted'), 'restricted')
  assert.throws(() => normalizeSecurityGrade('confidential'), { code: 'SECURITY_GRADE_INVALID' })
  assert.throws(() => normalizeSecurityGrade(null), { code: 'SECURITY_GRADE_INVALID' })
  assert.throws(() => normalizeSecurityGrade(undefined), { code: 'SECURITY_GRADE_INVALID' })

  assert.deepEqual(['normal', 'credential', 'restricted'].map(securityGradeRank), [0, 1, 2])
  assert.throws(() => securityGradeRank('confidential'), { code: 'SECURITY_GRADE_INVALID' })

  assert.ok(compareSecurityGrades('restricted', 'normal') > 0)
  assert.ok(compareSecurityGrades('normal', 'credential') < 0)
  assert.equal(compareSecurityGrades('credential', 'credential'), 0)
  assert.throws(() => compareSecurityGrades('normal', 'invalid'), { code: 'SECURITY_GRADE_INVALID' })

  assert.equal(legacyTableTagGrade({ tags: ['not-restricted', 'CLASSIFICATION:RESTRICTED'] }), 'normal')
  assert.equal(legacyTableTagGrade({ tags: [' Restricted '] }), 'restricted')
  assert.equal(legacyTableTagGrade({ tags: [{ urn: 'urn:li:tag:credential', name: 'anything' }, 'restricted'] }), 'restricted')
  assert.equal(legacyTableTagGrade({ tags: ['credential'] }), 'credential')
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

test('resolves exact authority before legacy fallback without union or dual write', () => {
  const assigned = applyTableSystemMappingCommand(null, {
    action: 'ASSIGN', table_ids: ['urn:table:a'], system_ids: ['system-a'], reason: 'exact authority fixture mapping',
  }, 'admin', '2026-08-16T01:00:00.000Z')
  assert.deepEqual(resolveTableSystemAuthority({
    document: assigned.document,
    tableIdentity: 'urn:table:a',
    activeSystemIds: new Set(['system-a', 'system-b']),
    legacySystemId: 'system-b',
  }), { system_ids: ['system-a'], provenance: 'EXACT', conflict: true })
  assert.deepEqual(resolveTableSystemAuthority({
    document: assigned.document,
    tableIdentity: 'urn:table:b',
    activeSystemIds: new Set(['system-a', 'system-b']),
    legacySystemId: 'system-b',
  }), { system_ids: ['system-b'], provenance: 'LEGACY_FALLBACK', conflict: false })

  const removed = applyTableSystemMappingCommand(assigned.document, {
    action: 'REMOVE', table_ids: ['urn:table:a'], system_ids: ['system-a'], reason: 'remove exact authority mapping',
  }, 'admin', '2026-08-16T02:00:00.000Z')
  assert.deepEqual(resolveTableSystemAuthority({
    document: removed.document,
    tableIdentity: 'urn:table:a',
    activeSystemIds: new Set(['system-a', 'system-b']),
    legacySystemId: 'system-b',
  }), { system_ids: [], provenance: 'EXACT', conflict: true })
})
