/* global structuredClone */
import { createHash } from 'node:crypto'

import { sanitizeK9MetadataSourceProfile } from './poc-k9-metadata-collection.mjs'
import { sanitizeK9SourceEligibilityTelemetry } from './poc-k9-source-eligibility.mjs'

export const K9_SOURCE_SNAPSHOT_CONTRACT = 'DATARIVER_K9_SOURCE_SNAPSHOT_V2'

const sha256Pattern = /^[0-9a-f]{64}$/
const supportedClassificationCeilings = new Set(['PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED'])
const metadataCollectionKeys = Object.freeze([
  'table_nodes',
  'column_nodes',
  'table_column_edges',
  'terms',
  'parent_nodes',
  'term_parent_edges',
  'node_parent_edges',
  'glossary_relationships',
  'table_assignments',
  'column_assignments',
  'tags',
  'domains',
  'containers',
  'platform_instances',
  'table_tag_assignments',
  'column_tag_assignments',
  'table_domain_assignments',
  'table_container_assignments',
  'table_platform_instance_assignments',
])
const operationalKeys = new Set([
  'matches',
  'refresh_diagnostics',
  'refresh_state',
  'inventory_refresh',
  'latency',
  'latency_ms',
  'elapsed_ms',
  'duration_ms',
  'retry_attempt',
  'retry_count',
  'ready',
  'readiness',
])

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

function operationalKey(key) {
  const normalized = key.toLowerCase()
  return operationalKeys.has(normalized)
    || normalized.endsWith('_at')
    || normalized.endsWith('_timestamp')
    || normalized === 'created'
    || normalized === 'createdon'
    || normalized === 'updatedon'
    || /(?:password|secret|token|credential|cookie|authorization|api[_-]?key)/i.test(normalized)
}

function normalizeSourceValue(value) {
  if (Array.isArray(value)) return value.map(normalizeSourceValue)
  if (!value || typeof value !== 'object') return value
  return Object.fromEntries(Object.entries(value)
    .filter(([key, item]) => !operationalKey(key) && item !== undefined)
    .map(([key, item]) => [key, normalizeSourceValue(item)]))
}

function normalizeSourceCollection(value) {
  if (!Array.isArray(value)) return []
  return value.map(normalizeSourceValue)
    .sort((left, right) => canonicalJson(left).localeCompare(canonicalJson(right)))
}

export function buildK9SourceInventoryProjection({ items, sourceScope, eligibility = null }) {
  const normalizedItems = normalizeSourceCollection(items)
  if (typeof sourceScope !== 'string' || !sourceScope.trim()) {
    throw new Error('The K9 source inventory scope is invalid')
  }
  const normalizedEligibility = eligibility === null
    ? null
    : sanitizeK9SourceEligibilityTelemetry(eligibility)
  if (eligibility !== null && !normalizedEligibility) {
    throw new Error('The K9 source eligibility telemetry is invalid')
  }
  return Object.freeze({
    projection_version: 2,
    source_scope: sourceScope.trim(),
    source_generation: canonicalHash(normalizedItems),
    eligibility: normalizedEligibility,
    items: normalizedItems,
  })
}

function normalizedAuthorityPin(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('The K9 source authority pin is unavailable')
  }
  const pin = {
    subject_id: value.subject_id,
    workspace_id: value.workspace_id,
    classification_ceiling: value.classification_ceiling,
    projection_version: value.projection_version,
    policy_version: value.policy_version,
    classification_policy_version: value.classification_policy_version,
    authorization_generation: value.authorization_generation,
    authorization_fingerprint: value.authorization_fingerprint,
  }
  if (typeof pin.subject_id !== 'string' || !pin.subject_id.trim()
    || typeof pin.workspace_id !== 'string' || !pin.workspace_id.trim()
    || !supportedClassificationCeilings.has(pin.classification_ceiling)
    || !Number.isSafeInteger(pin.projection_version) || pin.projection_version < 1
    || typeof pin.policy_version !== 'string' || !pin.policy_version.trim()
    || !Number.isSafeInteger(pin.classification_policy_version) || pin.classification_policy_version < 1
    || !Number.isSafeInteger(pin.authorization_generation) || pin.authorization_generation < 1) {
    throw new Error('The K9 source authority pin is invalid')
  }
  if (typeof pin.authorization_fingerprint !== 'string'
    || !sha256Pattern.test(pin.authorization_fingerprint)) {
    throw new Error('The K9 source authority pin is invalid')
  }
  return pin
}

function sourceAuthorityPin(lineageSource, metadataSource) {
  const lineagePin = normalizedAuthorityPin(lineageSource?.authority_pin)
  const metadataPin = normalizedAuthorityPin(metadataSource?.authority_pin)
  if (canonicalJson(lineagePin) !== canonicalJson(metadataPin)) {
    throw new Error('The K9 source collectors do not share one authority pin')
  }
  return lineagePin
}

function normalizedInventoryProjection(value) {
  const catalogGeneration = value?.source_generation
  if (typeof catalogGeneration !== 'string' || !sha256Pattern.test(catalogGeneration)) {
    throw new Error('The shared DataHub Catalog generation is unavailable for K9 refresh')
  }
  const eligibility = value?.eligibility === null || value?.eligibility === undefined
    ? null
    : sanitizeK9SourceEligibilityTelemetry(value.eligibility)
  if (value?.eligibility !== null && value?.eligibility !== undefined && !eligibility) {
    throw new Error('The K9 source eligibility telemetry is invalid for K9 refresh')
  }
  return {
    projection_version: Number.isSafeInteger(value?.projection_version) ? value.projection_version : null,
    source_scope: typeof value?.source_scope === 'string' ? value.source_scope : null,
    source_generation: catalogGeneration,
    eligibility,
    items: normalizeSourceCollection(value?.items),
  }
}

function normalizedRuntimeIdentity(value) {
  const version = typeof value?.version === 'string' ? value.version.trim() : ''
  const commit = value?.commit == null ? null : typeof value.commit === 'string' ? value.commit.trim() : ''
  if (!version || version.length > 200 || (commit !== null && (!commit || commit.length > 200))) {
    throw new Error('The DataHub runtime identity is invalid for K9 refresh')
  }
  return { version, commit }
}

function scopedCompletenessMetadata(value) {
  const scoped = normalizeSourceValue(value)
  for (const types of Object.values(scoped?.per_assignment || {})) {
    if (!types || typeof types !== 'object' || Array.isArray(types)) continue
    for (const totals of Object.values(types)) {
      if (totals && typeof totals === 'object' && !Array.isArray(totals)) {
        delete totals.provider_incoming_total
      }
    }
  }
  return scoped ?? null
}

function normalizedMetadataDocument(metadataSource) {
  const profile = sanitizeK9MetadataSourceProfile(metadataSource?.source_profile)
  return {
    collections: Object.fromEntries(metadataCollectionKeys.map((key) => [
      key,
      normalizeSourceCollection(metadataSource?.[key]),
    ])),
    completeness_metadata: scopedCompletenessMetadata(metadataSource?.completeness_metadata),
    raw_assignment_reference_hash: profile?.assignments.raw_reference_hash || null,
  }
}

function normalizedLineageDocument(lineageSource) {
  return {
    direction: lineageSource?.direction || null,
    depth: Number.isSafeInteger(lineageSource?.depth) ? lineageSource.depth : null,
    truncated: lineageSource?.truncated === true,
    nodes: normalizeSourceCollection(lineageSource?.nodes),
    column_nodes: normalizeSourceCollection(lineageSource?.column_nodes),
    edges: normalizeSourceCollection(lineageSource?.edges),
    completeness_metadata: normalizeSourceValue(lineageSource?.completeness_metadata),
  }
}

function normalizedDanglingState(metadataSource) {
  const profile = sanitizeK9MetadataSourceProfile(metadataSource?.source_profile)
  const assignments = profile?.assignments || {}
  const direct = profile?.direct_resolution || {}
  return {
    dangling_reference_hash: assignments.dangling_reference_hash || null,
    dangling_table_refs: assignments.dangling_table_refs || 0,
    dangling_column_refs: assignments.dangling_column_refs || 0,
    missing_term_reference_count: assignments.missing_term_reference_count || 0,
    direct_term_resolution_dangling_count: assignments.direct_term_resolution_dangling_count || 0,
    table_missing_term_count: assignments.table_missing_term_count || 0,
    column_missing_term_count: assignments.column_missing_term_count || 0,
    source_consistency_conflict_count: assignments.source_consistency_conflict_count || 0,
    dangling_unique_terms: direct.dangling_unique_terms || 0,
    dangling_assignment_references: direct.dangling_assignment_references || 0,
    dangling_absent_count: direct.dangling_absent_count || 0,
    dangling_does_not_exist_count: direct.dangling_does_not_exist_count || 0,
    dangling_removed_count: direct.dangling_removed_count || 0,
    dangling_incompatible_type_count: direct.dangling_incompatible_type_count || 0,
    first_dangling_identity_hash: direct.first_dangling_identity_hash || null,
  }
}

function sourceOnlyMetadataProfile(value) {
  const profile = sanitizeK9MetadataSourceProfile(value)
  if (!profile) return null
  const normalized = structuredClone(profile)
  for (const key of [
    'batch_number',
    'batch_requested_count',
    'batch_response_count',
    'batch_elapsed_ms',
    'completed_resolution_count',
    'retry_attempt',
    'provider_failure_class',
    'graphql_error_class',
    'graphql_error_path',
    'failing_identity_hash',
  ]) delete normalized.direct_resolution[key]
  return normalized
}

export function buildDatahubKnowledgeSourceCapture({
  inventoryProjection,
  datahubIdentity,
  lineageSource,
  metadataSource,
}) {
  const inventory = normalizedInventoryProjection(inventoryProjection)
  const runtimeIdentity = normalizedRuntimeIdentity(datahubIdentity)
  const authorityPin = sourceAuthorityPin(lineageSource, metadataSource)
  const lineage = normalizedLineageDocument(lineageSource)
  const metadata = normalizedMetadataDocument(metadataSource)
  const danglingState = normalizedDanglingState(metadataSource)
  const snapshotDocument = {
    contract_version: K9_SOURCE_SNAPSHOT_CONTRACT,
    catalog_generation: inventory.source_generation,
    datahub_version: runtimeIdentity.version,
    datahub_commit: runtimeIdentity.commit,
    authority_pin: authorityPin,
    inventory_projection_hash: canonicalHash(inventory),
    lineage_hash: canonicalHash(lineage),
    metadata_hash: canonicalHash(metadata),
    dangling_state_hash: canonicalHash(danglingState),
  }
  const sourceSnapshotId = canonicalHash(snapshotDocument)
  const snapshot = {
    ...snapshotDocument,
    source_snapshot_id: sourceSnapshotId,
    // Retained as a compatibility alias for the existing bounded
    // two-candidate consistency fence.
    source_fingerprint_id: sourceSnapshotId,
    source_eligibility: inventory.eligibility,
    // Bounded source accounting remains available to the managed read model,
    // but operational progress/failure fields never enter the identity.
    metadata_source_profile: sourceOnlyMetadataProfile(metadataSource?.source_profile),
  }
  return {
    snapshot,
    source_payloads: {
      inventory,
      lineage,
      metadata,
      dangling_state: danglingState,
    },
  }
}

export function buildDatahubKnowledgeSourceSnapshot(input) {
  return buildDatahubKnowledgeSourceCapture(input).snapshot
}

export function buildDatahubKnowledgeSourceFingerprint(input) {
  return buildDatahubKnowledgeSourceSnapshot(input)
}
