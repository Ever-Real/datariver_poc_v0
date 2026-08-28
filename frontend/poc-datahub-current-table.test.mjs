import assert from 'node:assert/strict'
import test from 'node:test'

import {
  classifyCurrentDatahubDataset,
  currentDatahubDatasetExists,
  datahubDatasetKind,
  isCurrentDatahubTable,
} from './poc-datahub-current-table.mjs'

const tableUrn = 'urn:li:dataset:(urn:li:dataPlatform:postgres,db.schema.table_a,PROD)'

test('uses one current Dataset/Table predicate for Catalog and Admin mutations', () => {
  const table = { urn: tableUrn, type: 'DATASET', properties: { customProperties: [] }, schemaMetadata: null }
  const view = { ...table, subTypes: { typeNames: ['VIEW'] } }
  const materializedView = { ...table, properties: { customProperties: [{ key: 'object_kind', value: 'MATERIALIZED VIEW' }] } }
  assert.equal(currentDatahubDatasetExists(table, tableUrn), true)
  assert.equal(datahubDatasetKind(table), 'TABLE')
  assert.equal(isCurrentDatahubTable(table, tableUrn), true)
  assert.equal(datahubDatasetKind(view), 'VIEW')
  assert.equal(isCurrentDatahubTable(view, tableUrn), false)
  assert.equal(datahubDatasetKind(materializedView), 'MATERIALIZED_VIEW')
  assert.equal(isCurrentDatahubTable(materializedView, tableUrn), false)
})

test('rejects deleted, ghost, malformed, mismatched and aspect-less entities', () => {
  const cases = [
    null,
    {},
    { urn: tableUrn, type: 'DATASET' },
    { urn: tableUrn, type: 'DATASET', properties: null, schemaMetadata: null },
    { urn: `${tableUrn}-other`, type: 'DATASET', properties: {}, schemaMetadata: null },
    { urn: tableUrn, type: 'CHART', properties: {}, schemaMetadata: null },
    { urn: 'table_a', type: 'DATASET', properties: {}, schemaMetadata: null },
  ]
  for (const entity of cases) {
    assert.equal(currentDatahubDatasetExists(entity, tableUrn), false)
    assert.equal(isCurrentDatahubTable(entity, tableUrn), false)
  }
})

test('excludes every explicit non-current signal before identity and classification projection', () => {
  const current = {
    urn: tableUrn,
    type: 'DATASET',
    exists: true,
    status: { removed: false },
    properties: { customProperties: [] },
    schemaMetadata: null,
  }
  assert.deepEqual(classifyCurrentDatahubDataset(current, tableUrn, { entityExists: true }), {
    current: true,
    reason: null,
  })
  assert.equal(
    classifyCurrentDatahubDataset(current, tableUrn, { entityExists: false }).reason,
    'DATASET_CURRENTNESS_CONTRADICTORY',
  )
  assert.equal(
    classifyCurrentDatahubDataset({ ...current, exists: false }, tableUrn).reason,
    'DATASET_EXISTS_FALSE',
  )
  assert.equal(
    classifyCurrentDatahubDataset({ ...current, status: { removed: true } }, tableUrn).reason,
    'DATASET_STATUS_REMOVED',
  )
  assert.equal(
    classifyCurrentDatahubDataset({ ...current, exists: undefined }, tableUrn, { entityExists: false }).reason,
    'DATASET_ENTITY_EXISTS_FALSE',
  )
})

test('fails currentness closed for malformed signals and retains the documented aspect fallback', () => {
  const base = {
    urn: tableUrn,
    type: 'DATASET',
    properties: { customProperties: [] },
    schemaMetadata: null,
  }
  assert.equal(
    classifyCurrentDatahubDataset({ ...base, exists: 'false' }, tableUrn).reason,
    'DATASET_CURRENTNESS_SIGNAL_INVALID',
  )
  assert.equal(
    classifyCurrentDatahubDataset({ ...base, status: { removed: 'true' } }, tableUrn).reason,
    'DATASET_CURRENTNESS_SIGNAL_INVALID',
  )
  assert.equal(currentDatahubDatasetExists(base, tableUrn), true)
})
