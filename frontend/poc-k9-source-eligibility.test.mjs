import assert from 'node:assert/strict'
import test from 'node:test'

import {
  sanitizeK9SourceEligibilityTelemetry,
  selectCanonicalK9SourceInventory,
} from './poc-k9-source-eligibility.mjs'

function dataset(index, {
  kind = 'TABLE',
  classification = 'MISSING',
  tags = [],
} = {}) {
  return {
    id: `urn:li:dataset:(urn:li:dataPlatform:postgres,prep.table_${index},PROD)`,
    dataset_kind: kind,
    tags,
    classification_resolution: { status: classification },
  }
}

test('PREP-shaped 1892 current Tables remain eligible when all TAG classifications are missing', () => {
  const input = Array.from({ length: 1_892 }, (_, index) => dataset(index))
  const selection = selectCanonicalK9SourceInventory(input, { classificationCeiling: 'INTERNAL' })

  assert.equal(selection.items.length, 1_892)
  assert.deepEqual(selection.telemetry, {
    contract: 'DATARIVER_K9_SOURCE_ELIGIBILITY_V1',
    provider_current_inventory_count: 1_892,
    canonical_current_count: 1_892,
    eligible_source_count: 1_892,
    invalid_identity_count: 0,
    unsupported_kind_count: 0,
    classification_exact_count: 0,
    classification_missing_count: 1_892,
    classification_multiple_count: 0,
    classification_invalid_count: 0,
    classification_ceiling: 'INTERNAL',
    classification_authority: false,
  })
})

test('arbitrary TAG vocabulary is telemetry only and cannot change canonical source eligibility', () => {
  const tags = [
    'restricted', 'credential', 'confidential', 'critical',
    'CLASSIFICATION:INTERNAL', 'classfication: typo',
  ]
  const items = tags.map((tag, index) => dataset(index, {
    classification: index === 4 ? 'EXACT' : index === 5 ? 'INVALID' : 'MISSING',
    tags: [tag],
  }))
  items.push(dataset(100, { kind: 'VIEW', classification: 'MULTIPLE' }))
  items.push(dataset(101, { kind: 'MATERIALIZED_VIEW', classification: 'INVALID' }))
  const selection = selectCanonicalK9SourceInventory(items, { classificationCeiling: 'PUBLIC' })

  assert.deepEqual(selection.items.map((item) => item.id), items.map((item) => item.id))
  assert.equal(selection.telemetry.eligible_source_count, items.length)
  assert.equal(selection.telemetry.classification_authority, false)
  assert.deepEqual(sanitizeK9SourceEligibilityTelemetry(selection.telemetry), selection.telemetry)
})

test('invalid identities and unsupported kinds are excluded with complete bounded accounting', () => {
  const selection = selectCanonicalK9SourceInventory([
    dataset(1),
    { ...dataset(2), id: 'not-a-dataset-urn' },
    dataset(3, { kind: 'CHART' }),
  ])
  assert.equal(selection.items.length, 1)
  assert.equal(selection.telemetry.provider_current_inventory_count, 3)
  assert.equal(selection.telemetry.canonical_current_count, 1)
  assert.equal(selection.telemetry.invalid_identity_count, 1)
  assert.equal(selection.telemetry.unsupported_kind_count, 1)
})

test('a truly empty provider/current inventory remains empty and never invents source authority', () => {
  const selection = selectCanonicalK9SourceInventory([], { classificationCeiling: 'INTERNAL' })
  assert.deepEqual(selection.items, [])
  assert.equal(selection.telemetry.provider_current_inventory_count, 0)
  assert.equal(selection.telemetry.eligible_source_count, 0)
  assert.equal(selection.telemetry.classification_authority, false)
})
