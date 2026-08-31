/* global structuredClone */
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { test } from 'node:test'

import {
  K9_SOURCE_SNAPSHOT_CONTRACT,
  buildDatahubKnowledgeSourceCapture,
  buildDatahubKnowledgeSourceSnapshot,
} from './poc-k9-source-snapshot.mjs'

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(',')}}`
  }
  return JSON.stringify(value)
}

function canonicalHash(value) {
  return createHash('sha256').update(canonicalJson(value), 'utf8').digest('hex')
}

function fixture() {
  const authorityPin = {
    subject_id: 'k9-system',
    workspace_id: 'workspace-1',
    classification_ceiling: 'INTERNAL',
    projection_version: 2,
    policy_version: 'POC_DATAHUB_SEMANTIC_MODEL_V2',
    classification_policy_version: 1,
    authorization_generation: 7,
  }
  return {
    inventoryProjection: {
      projection_version: 1,
      source_scope: 'scope-1',
      source_generation: '1'.repeat(64),
      observed_at: '2026-08-31T00:00:00.000Z',
      items: [
        { id: 'urn:li:dataset:b', name: 'B', observed_at: '2026-08-31T00:00:00.000Z', matches: [] },
        { id: 'urn:li:dataset:a', name: 'A', observed_at: '2026-08-31T00:00:00.000Z', matches: [] },
      ],
    },
    datahubIdentity: { version: 'v1.6.0', commit: 'provider-commit' },
    lineageSource: {
      authority_pin: structuredClone(authorityPin),
      direction: 'BOTH',
      depth: 1,
      truncated: false,
      nodes: [{ id: 'TABLE:urn:li:dataset:a' }, { id: 'TABLE:urn:li:dataset:b' }],
      column_nodes: [],
      edges: [{
        source_asset_id: 'TABLE:urn:li:dataset:a',
        target_asset_id: 'TABLE:urn:li:dataset:b',
        properties: { source: 'DataHub', observed_at: '2026-08-31T00:00:00.000Z' },
      }],
      completeness_metadata: { per_asset: { a: { fetched: 1, total: 1 } } },
    },
    metadataSource: {
      authority_pin: structuredClone(authorityPin),
      table_nodes: [{ id: 'TABLE:urn:li:dataset:a', name: 'A' }],
      column_nodes: [],
      table_column_edges: [],
      terms: [{ urn: 'urn:li:glossaryTerm:term-a', name: 'Term A' }],
      parent_nodes: [],
      term_parent_edges: [],
      node_parent_edges: [],
      glossary_relationships: [],
      table_assignments: [{ id: 'TABLE:urn:li:dataset:a', term_urn: 'urn:li:glossaryTerm:term-a' }],
      column_assignments: [],
      tags: [],
      domains: [],
      containers: [],
      platform_instances: [],
      table_tag_assignments: [],
      column_tag_assignments: [],
      table_domain_assignments: [],
      table_container_assignments: [],
      table_platform_instance_assignments: [],
      completeness_metadata: {
        fetched: 1,
        total: 1,
        per_assignment: {
          'urn:li:glossaryTerm:term-a': {
            TABLE: { raw: 1, projectable: 1, dangling: 0, provider_incoming_total: 99 },
          },
        },
      },
      source_profile: {
        contract: 'DATARIVER_K9_METADATA_SOURCE_PROFILE_V1',
        source_generation: '1'.repeat(64),
        assignments: {
          raw_reference_hash: '2'.repeat(64),
          dangling_reference_hash: null,
        },
        direct_resolution: {},
      },
    },
  }
}

function snapshot(input = fixture()) {
  return buildDatahubKnowledgeSourceSnapshot(input)
}

function changed(mutator) {
  const input = fixture()
  mutator(input)
  return snapshot(input).source_snapshot_id
}

test('K9 V2 source snapshot is deterministic and source-only', () => {
  const input = fixture()
  const first = snapshot(input)
  const reordered = structuredClone(input)
  reordered.inventoryProjection.items.reverse()
  reordered.lineageSource.nodes.reverse()

  assert.equal(first.contract_version, K9_SOURCE_SNAPSHOT_CONTRACT)
  assert.match(first.source_snapshot_id, /^[0-9a-f]{64}$/)
  assert.equal(first.source_fingerprint_id, first.source_snapshot_id)
  assert.equal(snapshot(structuredClone(input)).source_snapshot_id, first.source_snapshot_id)
  assert.equal(snapshot(reordered).source_snapshot_id, first.source_snapshot_id)
  assert.deepEqual(first.authority_pin, input.lineageSource.authority_pin)
})

test('K9 V2 capture emits the exact normalized immutable payloads bound by the snapshot', () => {
  const input = fixture()
  const capture = buildDatahubKnowledgeSourceCapture(input)
  assert.deepEqual(capture.snapshot, buildDatahubKnowledgeSourceSnapshot(input))
  assert.equal(canonicalHash(capture.source_payloads.inventory), capture.snapshot.inventory_projection_hash)
  assert.equal(canonicalHash(capture.source_payloads.lineage), capture.snapshot.lineage_hash)
  assert.equal(canonicalHash(capture.source_payloads.metadata), capture.snapshot.metadata_hash)
  assert.equal(canonicalHash(capture.source_payloads.dangling_state), capture.snapshot.dangling_state_hash)
  assert.equal(capture.source_payloads.inventory.items.some((item) => 'observed_at' in item), false)
  assert.equal('batch_elapsed_ms' in capture.source_payloads.dangling_state, false)
})

test('K9 V2 source snapshot rotates for every source identity input', () => {
  const baseline = snapshot().source_snapshot_id
  const changes = [
    changed((input) => { input.inventoryProjection.source_generation = '3'.repeat(64) }),
    changed((input) => { input.inventoryProjection.items[0].name = 'Changed inventory' }),
    changed((input) => { input.lineageSource.edges[0].properties.source_relationship_type = 'COPY' }),
    changed((input) => { input.metadataSource.terms[0].name = 'Changed term' }),
    changed((input) => {
      input.metadataSource.source_profile.assignments.dangling_reference_hash = '4'.repeat(64)
      input.metadataSource.source_profile.assignments.dangling_table_refs = 1
      input.metadataSource.source_profile.direct_resolution.dangling_unique_terms = 1
    }),
    changed((input) => { input.datahubIdentity.version = 'v1.7.0' }),
    changed((input) => { input.datahubIdentity.commit = 'new-provider-commit' }),
    changed((input) => {
      input.lineageSource.authority_pin.subject_id = 'next-k9-system'
      input.metadataSource.authority_pin.subject_id = 'next-k9-system'
    }),
    changed((input) => {
      input.lineageSource.authority_pin.workspace_id = 'workspace-2'
      input.metadataSource.authority_pin.workspace_id = 'workspace-2'
    }),
    changed((input) => {
      input.lineageSource.authority_pin.classification_ceiling = 'CONFIDENTIAL'
      input.metadataSource.authority_pin.classification_ceiling = 'CONFIDENTIAL'
    }),
    changed((input) => {
      input.lineageSource.authority_pin.projection_version += 1
      input.metadataSource.authority_pin.projection_version += 1
    }),
    changed((input) => {
      input.lineageSource.authority_pin.authorization_generation += 1
      input.metadataSource.authority_pin.authorization_generation += 1
    }),
    changed((input) => {
      input.lineageSource.authority_pin.policy_version = 'POC_DATAHUB_SEMANTIC_MODEL_V3'
      input.metadataSource.authority_pin.policy_version = 'POC_DATAHUB_SEMANTIC_MODEL_V3'
    }),
    changed((input) => {
      input.lineageSource.authority_pin.classification_policy_version += 1
      input.metadataSource.authority_pin.classification_policy_version += 1
    }),
  ]

  for (const candidate of changes) assert.notEqual(candidate, baseline)
})

test('K9 V2 source snapshot excludes semantic, graph, time, retry, latency and readiness noise', () => {
  const baseline = snapshot().source_snapshot_id
  const noisy = fixture()
  noisy.semanticIndex = { generation: '9'.repeat(64), bindingHash: '8'.repeat(64) }
  noisy.graphManifest = { release_id: 'release-noise', result: 'SUCCESS' }
  noisy.inventoryProjection.observed_at = '2030-01-01T00:00:00.000Z'
  noisy.inventoryProjection.refresh_diagnostics = { elapsed_ms: 9_999, retry_count: 4, readiness: 'READY' }
  noisy.inventoryProjection.items[0].observed_at = '2030-01-01T00:00:00.000Z'
  noisy.lineageSource.edges[0].properties.observed_at = '2030-01-01T00:00:00.000Z'
  noisy.lineageSource.edges[0].properties.latency_ms = 9_999
  noisy.metadataSource.terms[0].updated_at = '2030-01-01T00:00:00.000Z'
  noisy.metadataSource.terms[0].ready = false
  noisy.metadataSource.source_profile.direct_resolution = {
    batch_elapsed_ms: 9_999,
    retry_attempt: 4,
    provider_failure_class: 'TIMEOUT',
  }

  assert.equal(snapshot(noisy).source_snapshot_id, baseline)
})

test('K9 V2 source snapshot ignores provider-wide assignment telemetry outside authorized scope', () => {
  const baseline = snapshot().source_snapshot_id
  const noisy = fixture()
  noisy.metadataSource.source_profile.assignments.declared_table_assignment_total = 1_000
  noisy.metadataSource.source_profile.assignments.provider_incoming_table_total = 1_000
  noisy.metadataSource.source_profile.assignments.provider_scope_relation = 'GLOBAL_GREATER'
  noisy.metadataSource.completeness_metadata.per_assignment['urn:li:glossaryTerm:term-a']
    .TABLE.provider_incoming_total = 1_000

  assert.equal(snapshot(noisy).source_snapshot_id, baseline)
})

test('K9 V2 source snapshot rejects mixed authority and never retains raw secret fields', () => {
  const mixed = fixture()
  mixed.metadataSource.authority_pin.workspace_id = 'other-workspace'
  assert.throws(() => snapshot(mixed), /do not share one authority pin/)

  const input = fixture()
  input.datahubIdentity.provider_token = 'raw-runtime-secret'
  input.lineageSource.nodes[0].password = 'raw-lineage-secret'
  input.metadataSource.terms[0].api_key = 'raw-metadata-secret'
  const value = snapshot(input)
  const encoded = JSON.stringify(value)
  assert.equal(encoded.includes('raw-runtime-secret'), false)
  assert.equal(encoded.includes('raw-lineage-secret'), false)
  assert.equal(encoded.includes('raw-metadata-secret'), false)
  assert.equal(value.source_snapshot_id, snapshot().source_snapshot_id)
})
