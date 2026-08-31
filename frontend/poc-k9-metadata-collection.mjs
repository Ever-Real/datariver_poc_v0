import { createHash } from 'node:crypto'

export const K9_METADATA_FAILURE_DETAILS = Object.freeze([
  'TAG_IDENTITY_CONFLICT',
  'GLOSSARY_RESPONSE_MALFORMED',
  'GLOSSARY_TOTAL_DRIFT',
  'GLOSSARY_CURSOR_STALLED',
  'GLOSSARY_RELATION_PAGE_INCOMPLETE',
  'GLOSSARY_RELATION_COUNT_MISMATCH',
  'RELATION_ENTITY_IDENTITY_MISMATCH',
  'DUPLICATE_TERM_IDENTITY',
  'DUPLICATE_NODE_IDENTITY',
  'DUPLICATE_TERM_PARENT_EDGE',
  'DUPLICATE_NODE_PARENT_EDGE',
  'DANGLING_GLOSSARY_ASSIGNMENT',
  'GLOSSARY_DIRECT_RESOLUTION_LIMIT_EXCEEDED',
  // Retained only so the current Actual-PREP-style failed receipt remains
  // readable during descendant resume. New collection paths resolve first.
  'ASSIGNMENT_TERM_OUTSIDE_SNAPSHOT',
  'DUPLICATE_ASSIGNMENT_IDENTITY',
  'RELATION_IDENTITY_CONFLICT',
  // Retained only so an existing failed scheduler receipt remains readable
  // across a same-command descendant resume. New collection paths use an
  // exact bounded locus above.
  'METADATA_IDENTITY_CONFLICT',
  'GLOSSARY_ASSIGNMENT_COUNT_MISMATCH',
  'METADATA_NORMALIZATION_FAILED',
])

export const K9_METADATA_SOURCE_PROFILE_CONTRACT = 'DATARIVER_K9_METADATA_SOURCE_PROFILE_V1'
export const K9_METADATA_IDENTITY_CLASSIFICATIONS = Object.freeze([
  'EXACT_DUPLICATE',
  'COMPATIBLE_SPARSE_RICH',
  'CONTRADICTION',
])

const supportedMetadataFailureDetails = new Set(K9_METADATA_FAILURE_DETAILS)
const supportedTagNameSources = new Set(['LEGACY', 'PROPERTIES'])
const supportedIdentityClassifications = new Set(K9_METADATA_IDENTITY_CLASSIFICATIONS)
const supportedProviderFailureClasses = new Set([
  'CONNECTIVITY', 'TIMEOUT', 'HTTP_4XX', 'HTTP_5XX', 'HTTP_OTHER',
  'GRAPHQL', 'CONTRACT',
])
const sha256Pattern = /^[0-9a-f]{64}$/
const DIRECT_GLOSSARY_TERM_BATCH_SIZE = 250

function boundedCount(value) {
  return Number.isSafeInteger(value) && value >= 0 ? value : 0
}

function boundedOptionalOrdinal(value) {
  return Number.isSafeInteger(value) && value >= 0 ? value : null
}

function canonicalProfileJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalProfileJson).join(',')}]`
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalProfileJson(value[key])}`).join(',')}}`
  }
  return JSON.stringify(value)
}

function boundedIdentityHash(value) {
  return createHash('sha256').update(String(value || ''), 'utf8').digest('hex')
}

function boundedShapeHash(value) {
  return createHash('sha256').update(canonicalProfileJson(value), 'utf8').digest('hex')
}

function boundedIdentityFailure(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)
    || !K9_METADATA_FAILURE_DETAILS.includes(value.locus)
    || !supportedIdentityClassifications.has(value.classification)
    || !sha256Pattern.test(value.identity_hash || '')
    || !sha256Pattern.test(value.shape_hash || '')) return null
  return {
    locus: value.locus,
    classification: value.classification,
    identity_hash: value.identity_hash,
    shape_hash: value.shape_hash,
    page_number: boundedOptionalOrdinal(value.page_number),
    ordinal: boundedOptionalOrdinal(value.ordinal),
  }
}

export function sanitizeK9MetadataSourceProfile(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)
    || value.contract !== K9_METADATA_SOURCE_PROFILE_CONTRACT) return null
  const inventory = value.inventory || {}
  const glossary = value.glossary_scroll || {}
  const relationships = value.relationships || {}
  const assignments = value.assignments || {}
  const resolution = value.identity_resolution || {}
  const directResolution = value.direct_resolution || {}
  const sourceGeneration = sha256Pattern.test(value.source_generation || '')
    ? value.source_generation
    : null
  const cursorStatus = ['NOT_STARTED', 'ADVANCING', 'COMPLETE', 'FAILED'].includes(glossary.cursor_progression_status)
    ? glossary.cursor_progression_status
    : 'NOT_STARTED'
  return {
    contract: K9_METADATA_SOURCE_PROFILE_CONTRACT,
    source_generation: sourceGeneration,
    inventory: {
      total_dataset_count: boundedCount(inventory.total_dataset_count),
      table_count: boundedCount(inventory.table_count),
      view_count: boundedCount(inventory.view_count),
      materialized_view_count: boundedCount(inventory.materialized_view_count),
      total_column_count: boundedCount(inventory.total_column_count),
      table_tag_observation_count: boundedCount(inventory.table_tag_observation_count),
      column_tag_observation_count: boundedCount(inventory.column_tag_observation_count),
      table_glossary_term_observation_count: boundedCount(inventory.table_glossary_term_observation_count),
      column_glossary_term_observation_count: boundedCount(inventory.column_glossary_term_observation_count),
      non_empty: inventory.non_empty === true,
    },
    glossary_scroll: {
      provider_reported_total: boundedCount(glossary.provider_reported_total),
      pages_fetched: boundedCount(glossary.pages_fetched),
      entities_fetched: boundedCount(glossary.entities_fetched),
      unique_term_count: boundedCount(glossary.unique_term_count),
      unique_node_count: boundedCount(glossary.unique_node_count),
      duplicate_term_observation_count: boundedCount(glossary.duplicate_term_observation_count),
      duplicate_node_observation_count: boundedCount(glossary.duplicate_node_observation_count),
      cursor_progression_status: cursorStatus,
      completion_status: glossary.completion_status === true,
    },
    relationships: {
      glossary_entities_inspected: boundedCount(relationships.glossary_entities_inspected),
      provider_relationship_total: boundedCount(relationships.provider_relationship_total),
      relationship_pages_fetched: boundedCount(relationships.relationship_pages_fetched),
      relationships_fetched: boundedCount(relationships.relationships_fetched),
      duplicate_relationship_observations: boundedCount(relationships.duplicate_relationship_observations),
      response_entity_identity_mismatch_count: boundedCount(relationships.response_entity_identity_mismatch_count),
      completeness_mismatch_count: boundedCount(relationships.completeness_mismatch_count),
    },
    assignments: {
      declared_table_assignment_total: boundedCount(assignments.declared_table_assignment_total),
      observed_table_assignment_total: boundedCount(assignments.observed_table_assignment_total),
      declared_column_assignment_total: boundedCount(assignments.declared_column_assignment_total),
      observed_column_assignment_total: boundedCount(assignments.observed_column_assignment_total),
      term_outside_snapshot_count: boundedCount(assignments.term_outside_snapshot_count),
      duplicate_assignment_observation_count: boundedCount(assignments.duplicate_assignment_observation_count),
      missing_term_reference_count: boundedCount(assignments.missing_term_reference_count),
      direct_term_resolution_attempt_count: boundedCount(assignments.direct_term_resolution_attempt_count),
      direct_term_resolution_recovered_count: boundedCount(assignments.direct_term_resolution_recovered_count),
      direct_term_resolution_dangling_count: boundedCount(assignments.direct_term_resolution_dangling_count),
      table_missing_term_count: boundedCount(assignments.table_missing_term_count),
      column_missing_term_count: boundedCount(assignments.column_missing_term_count),
      source_consistency_conflict_count: boundedCount(assignments.source_consistency_conflict_count),
    },
    direct_resolution: {
      total: boundedCount(directResolution.total),
      batch_size: boundedCount(directResolution.batch_size),
      batch_total: boundedCount(directResolution.batch_total),
      batch_number: boundedCount(directResolution.batch_number),
      batch_requested_count: boundedCount(directResolution.batch_requested_count),
      batch_response_count: boundedCount(directResolution.batch_response_count),
      batch_elapsed_ms: boundedCount(directResolution.batch_elapsed_ms),
      completed_resolution_count: boundedCount(directResolution.completed_resolution_count),
      retry_attempt: boundedCount(directResolution.retry_attempt),
      provider_failure_class: supportedProviderFailureClasses.has(directResolution.provider_failure_class)
        ? directResolution.provider_failure_class
        : null,
      graphql_error_class: typeof directResolution.graphql_error_class === 'string'
        && /^[A-Z][A-Z0-9_]{0,63}$/.test(directResolution.graphql_error_class)
        ? directResolution.graphql_error_class
        : null,
      graphql_error_path: typeof directResolution.graphql_error_path === 'string'
        && /^[A-Za-z0-9_.]{1,160}$/.test(directResolution.graphql_error_path)
        ? directResolution.graphql_error_path
        : null,
      failing_identity_hash: sha256Pattern.test(directResolution.failing_identity_hash || '')
        ? directResolution.failing_identity_hash
        : null,
    },
    identity_resolution: {
      exact_duplicate_observation_count: boundedCount(resolution.exact_duplicate_observation_count),
      compatible_sparse_rich_observation_count: boundedCount(resolution.compatible_sparse_rich_observation_count),
      contradiction_observation_count: boundedCount(resolution.contradiction_observation_count),
      failure: boundedIdentityFailure(resolution.failure),
    },
  }
}

function profileError(error, profile) {
  const sanitized = sanitizeK9MetadataSourceProfile(profile)
  if (sanitized && error && typeof error === 'object') {
    error.k9MetadataSourceProfile = Object.freeze(sanitized)
  }
  return error
}

function metadataFailure(detailCode, cause, profile) {
  if (!supportedMetadataFailureDetails.has(detailCode)) {
    throw new Error('The K9 metadata failure detail is invalid.')
  }
  return profileError(Object.assign(
    new Error('The bounded K9 metadata collection invariant failed.', cause ? { cause } : undefined),
    { k9SourceFailureDetailCode: detailCode },
  ), profile)
}

function providerContractFailure(profile) {
  return profileError(Object.assign(
    new Error('The bounded DataHub glossary entity response contract is invalid.'),
    { providerFailureKind: 'CONTRACT' },
  ), profile)
}

function providerFailure(error) {
  return error?.providerFailureKind
    || error?.providerHttpClass
    || Number.isInteger(error?.statusCode)
    || ['TimeoutError', 'AbortError'].includes(error?.name)
    || String(error?.code || '').includes('GRAPHQL')
    || String(error?.code || '').includes('CONTRACT')
}

function providerFailureClass(error) {
  if (['TimeoutError', 'AbortError'].includes(error?.name)) return 'TIMEOUT'
  if (error?.providerFailureKind === 'HTTP') {
    if (error?.providerHttpClass === '4xx') return 'HTTP_4XX'
    if (error?.providerHttpClass === '5xx') return 'HTTP_5XX'
    return 'HTTP_OTHER'
  }
  if (error?.providerFailureKind === 'GRAPHQL') return 'GRAPHQL'
  if (['RESPONSE_JSON', 'CONTRACT'].includes(error?.providerFailureKind)) return 'CONTRACT'
  return 'CONNECTIVITY'
}

function nonNegativeSafeInteger(value) {
  return Number.isSafeInteger(value) && value >= 0
}

function boundedTagNameSource(value) {
  if (value === null || value === undefined) return 'LEGACY'
  if (supportedTagNameSources.has(value)) return value
  throw metadataFailure('METADATA_NORMALIZATION_FAILED')
}

function canonicalTagObservation(reference, nameSource) {
  if (typeof reference?.urn !== 'string' || !reference.urn
    || typeof reference?.name !== 'string' || !reference.name) {
    throw metadataFailure('METADATA_NORMALIZATION_FAILED')
  }
  if (typeof reference.description !== 'string') {
    throw metadataFailure('METADATA_NORMALIZATION_FAILED')
  }
  return {
    urn: reference.urn,
    name: reference.name,
    name_source: boundedTagNameSource(nameSource),
    description: reference.description || '',
  }
}

export function normalizeDatahubTagReferences(entity) {
  const declaredReferences = entity?.globalTags?.tags
  if (declaredReferences === null || declaredReferences === undefined) return []
  if (!Array.isArray(declaredReferences)) throw metadataFailure('METADATA_NORMALIZATION_FAILED')
  return declaredReferences.map((item) => {
    const tag = item?.tag
    const properties = tag?.properties
    const hasProperties = properties !== null && properties !== undefined
    if (hasProperties && (typeof properties !== 'object' || Array.isArray(properties))) {
      throw metadataFailure('METADATA_NORMALIZATION_FAILED')
    }
    const propertiesName = properties?.name
    if (hasProperties && (typeof propertiesName !== 'string' || !propertiesName)) {
      throw metadataFailure('METADATA_NORMALIZATION_FAILED')
    }
    const name = propertiesName || tag?.name
    if (typeof tag?.urn !== 'string' || !tag.urn || typeof name !== 'string' || !name) {
      throw metadataFailure('METADATA_NORMALIZATION_FAILED')
    }
    const description = properties?.description
    if (description !== null && description !== undefined && typeof description !== 'string') {
      throw metadataFailure('METADATA_NORMALIZATION_FAILED')
    }
    return {
      urn: tag.urn,
      name,
      description: description || '',
      _k9_name_source: propertiesName ? 'PROPERTIES' : 'LEGACY',
    }
  })
}

function mergeCanonicalTagObservation(existing, reference, nameSource) {
  const incoming = canonicalTagObservation(reference, nameSource)
  if (!incoming) return existing || null
  if (!existing) return incoming
  if (existing.urn !== incoming.urn
    || (existing.name !== incoming.name && existing.name_source === incoming.name_source)
    || (existing.description && incoming.description && existing.description !== incoming.description)) {
    throw metadataFailure('TAG_IDENTITY_CONFLICT')
  }
  const preferredName = existing.name_source === 'PROPERTIES'
    ? existing
    : incoming.name_source === 'PROPERTIES' ? incoming : existing
  return {
    urn: existing.urn,
    name: preferredName.name,
    name_source: preferredName.name_source,
    description: existing.description || incoming.description,
  }
}

function publicTag(value) {
  return { urn: value.urn, name: value.name, description: value.description }
}

function createMetadataSourceProfile(sourceGeneration) {
  return {
    contract: K9_METADATA_SOURCE_PROFILE_CONTRACT,
    source_generation: sha256Pattern.test(sourceGeneration || '') ? sourceGeneration : null,
    inventory: {
      total_dataset_count: 0,
      table_count: 0,
      view_count: 0,
      materialized_view_count: 0,
      total_column_count: 0,
      table_tag_observation_count: 0,
      column_tag_observation_count: 0,
      table_glossary_term_observation_count: 0,
      column_glossary_term_observation_count: 0,
      non_empty: false,
    },
    glossary_scroll: {
      provider_reported_total: 0,
      pages_fetched: 0,
      entities_fetched: 0,
      unique_term_count: 0,
      unique_node_count: 0,
      duplicate_term_observation_count: 0,
      duplicate_node_observation_count: 0,
      cursor_progression_status: 'NOT_STARTED',
      completion_status: false,
    },
    relationships: {
      glossary_entities_inspected: 0,
      provider_relationship_total: 0,
      relationship_pages_fetched: 0,
      relationships_fetched: 0,
      duplicate_relationship_observations: 0,
      response_entity_identity_mismatch_count: 0,
      completeness_mismatch_count: 0,
    },
    assignments: {
      declared_table_assignment_total: 0,
      observed_table_assignment_total: 0,
      declared_column_assignment_total: 0,
      observed_column_assignment_total: 0,
      term_outside_snapshot_count: 0,
      duplicate_assignment_observation_count: 0,
      missing_term_reference_count: 0,
      direct_term_resolution_attempt_count: 0,
      direct_term_resolution_recovered_count: 0,
      direct_term_resolution_dangling_count: 0,
      table_missing_term_count: 0,
      column_missing_term_count: 0,
      source_consistency_conflict_count: 0,
    },
    direct_resolution: {
      total: 0,
      batch_size: DIRECT_GLOSSARY_TERM_BATCH_SIZE,
      batch_total: 0,
      batch_number: 0,
      batch_requested_count: 0,
      batch_response_count: 0,
      batch_elapsed_ms: 0,
      completed_resolution_count: 0,
      retry_attempt: 0,
      provider_failure_class: null,
      graphql_error_class: null,
      graphql_error_path: null,
      failing_identity_hash: null,
    },
    identity_resolution: {
      exact_duplicate_observation_count: 0,
      compatible_sparse_rich_observation_count: 0,
      contradiction_observation_count: 0,
      failure: null,
    },
  }
}

function observeInventoryProfile(profile, inventory, fieldsFor) {
  profile.inventory.total_dataset_count = inventory.length
  profile.inventory.non_empty = inventory.length > 0
  for (const item of inventory) {
    if (item?.dataset_kind === 'TABLE') profile.inventory.table_count += 1
    if (item?.dataset_kind === 'VIEW') profile.inventory.view_count += 1
    if (item?.dataset_kind === 'MATERIALIZED_VIEW') profile.inventory.materialized_view_count += 1
    profile.inventory.table_tag_observation_count += Array.isArray(item?.tag_references)
      ? item.tag_references.length : 0
    profile.inventory.table_glossary_term_observation_count += Array.isArray(item?.glossary_terms)
      ? item.glossary_terms.length : 0
    const fields = fieldsFor(item)
    profile.inventory.total_column_count += fields.length
    for (const field of fields) {
      profile.inventory.column_tag_observation_count += Array.isArray(field?.globalTags?.tags)
        ? field.globalTags.tags.length : 0
      profile.inventory.column_glossary_term_observation_count += Array.isArray(field?.glossaryTerms?.terms)
        ? field.glossaryTerms.terms.length : 0
    }
  }
}

function identityShape(value) {
  const properties = value && typeof value === 'object' && !Array.isArray(value) ? value : {}
  return Object.fromEntries(Object.entries(properties).map(([key, item]) => {
    if (Array.isArray(item)) return [key, { kind: 'ARRAY', count: item.length }]
    if (item && typeof item === 'object') return [key, { kind: 'OBJECT', keys: Object.keys(item).sort() }]
    if (typeof item === 'string') return [key, { kind: 'STRING', present: item.length > 0 }]
    return [key, { kind: item === null ? 'NULL' : typeof item }]
  }))
}

function observationClassification(existing, incoming) {
  if (canonicalProfileJson(existing) === canonicalProfileJson(incoming)) return 'EXACT_DUPLICATE'
  const existingDomain = existing?.domain_reference?.urn || null
  const incomingDomain = incoming?.domain_reference?.urn || null
  if (existing?.entity_type !== incoming?.entity_type
    || (existing?.assignment_totals && incoming?.assignment_totals
      && (existing.assignment_totals.TABLE !== incoming.assignment_totals.TABLE
        || existing.assignment_totals.COLUMN !== incoming.assignment_totals.COLUMN))
    || (existingDomain && incomingDomain && existingDomain !== incomingDomain)) return 'CONTRADICTION'
  return 'COMPATIBLE_SPARSE_RICH'
}

function deterministicText(left, right) {
  const candidates = [left, right].filter((value) => typeof value === 'string' && value.length > 0)
  if (!candidates.length) return typeof left === 'string' ? left : (typeof right === 'string' ? right : '')
  return candidates.sort((first, second) => (
    second.length - first.length || first.localeCompare(second)
  ))[0]
}

function deterministicAttributeMerge(left, right) {
  if (left === null || left === undefined) return globalThis.structuredClone(right)
  if (right === null || right === undefined) return globalThis.structuredClone(left)
  if (typeof left === 'string' || typeof right === 'string') return deterministicText(left, right)
  if (Array.isArray(left) && Array.isArray(right)) {
    const byShape = new Map([...left, ...right].map((item) => [canonicalProfileJson(item), item]))
    return [...byShape.entries()].sort(([first], [second]) => first.localeCompare(second))
      .map(([, item]) => globalThis.structuredClone(item))
  }
  if (left && right && typeof left === 'object' && typeof right === 'object'
    && !Array.isArray(left) && !Array.isArray(right)) {
    return Object.fromEntries([...new Set([...Object.keys(left), ...Object.keys(right)])].sort()
      .map((key) => [key, deterministicAttributeMerge(left[key], right[key])]))
  }
  if (Object.is(left, right)) return left
  return canonicalProfileJson(left).localeCompare(canonicalProfileJson(right)) <= 0
    ? globalThis.structuredClone(left)
    : globalThis.structuredClone(right)
}

function mergeCompatibleObservation(existing, incoming) {
  const classification = observationClassification(existing, incoming)
  return {
    classification,
    value: classification === 'CONTRADICTION'
      ? null
      : deterministicAttributeMerge(existing, incoming),
  }
}

function publicGlossaryObservation(value) {
  const publicValue = { ...value }
  delete publicValue.entity_type
  delete publicValue.assignment_totals
  return publicValue
}

function compareBy(...keys) {
  return (left, right) => {
    for (const key of keys) {
      const comparison = String(left?.[key] ?? '').localeCompare(String(right?.[key] ?? ''))
      if (comparison) return comparison
    }
    return 0
  }
}

function observeIdentityResolution(profile, classification) {
  if (classification === 'EXACT_DUPLICATE') {
    profile.identity_resolution.exact_duplicate_observation_count += 1
  } else if (classification === 'COMPATIBLE_SPARSE_RICH') {
    profile.identity_resolution.compatible_sparse_rich_observation_count += 1
  } else {
    profile.identity_resolution.contradiction_observation_count += 1
  }
}

function identityFailure(profile, locus, classification, identity, shape, pageNumber, ordinal) {
  observeIdentityResolution(profile, classification)
  profile.identity_resolution.failure = {
    locus,
    classification,
    identity_hash: boundedIdentityHash(identity),
    shape_hash: boundedShapeHash(identityShape(shape)),
    page_number: boundedOptionalOrdinal(pageNumber),
    ordinal: boundedOptionalOrdinal(ordinal),
  }
  throw metadataFailure(locus, undefined, profile)
}

function requiredFunction(value, label) {
  if (typeof value !== 'function') throw new Error(`The ${label} dependency is unavailable.`)
  return value
}

export function createK9MetadataCollector({
  refreshGraphql,
  glossaryQuery,
  glossaryTermsQuery,
  relationshipsQuery,
  buildScrollVariables,
  schemaFields,
  sourceClassification,
  assetUrn,
  metadataProperties,
  customProperties,
  structuredProperties,
  tagNameSource,
  urnTail,
  signal,
} = {}) {
  const fetchGraphql = requiredFunction(refreshGraphql, 'GraphQL refresh')
  const scrollVariables = requiredFunction(buildScrollVariables, 'glossary scroll')
  const fieldsFor = requiredFunction(schemaFields, 'schema field')
  const classificationFor = requiredFunction(sourceClassification, 'source classification')
  const urnFor = requiredFunction(assetUrn, 'asset URN')
  const propertiesFor = requiredFunction(metadataProperties, 'metadata properties')
  const customPropertiesFor = requiredFunction(customProperties, 'custom properties')
  const structuredPropertiesFor = requiredFunction(structuredProperties, 'structured properties')
  const tagNameSourceFor = requiredFunction(tagNameSource, 'tag name source')
  const tailFor = requiredFunction(urnTail, 'URN tail')

  async function collect(authorityPin, inventory, {
    sourceGeneration = null,
    retryAttempt = 1,
    reportProgress = null,
  } = {}) {
    const profile = createMetadataSourceProfile(sourceGeneration)
    profile.direct_resolution.retry_attempt = boundedCount(retryAttempt)
    const publishProgress = () => {
      if (typeof reportProgress !== 'function') return
      try {
        reportProgress(sanitizeK9MetadataSourceProfile(profile)?.direct_resolution || null)
      } catch {
        // Operator progress is a bounded projection. It must never change the
        // source correctness or fail-open semantics of metadata collection.
      }
    }
    try {
      if (!Array.isArray(inventory) || inventory.length === 0) {
        throw metadataFailure('METADATA_NORMALIZATION_FAILED', undefined, profile)
      }
      observeInventoryProfile(profile, inventory, fieldsFor)
    const table_nodes = []
    const column_nodes = []
    const table_column_edges = []
    const tags = new Map()
    const domains = new Map()
    const containers = new Map()
    const platform_instances = new Map()
    const table_tag_assignments = []
    const column_tag_assignments = []
    const table_domain_assignments = []
    const table_container_assignments = []
    const table_platform_instance_assignments = []
    const metadataAssignmentSet = new Set()

    const registerMetadataAssignment = (collection, sourceId, targetId) => {
      const key = `${sourceId}->${targetId}`
      if (metadataAssignmentSet.has(key)) return
      metadataAssignmentSet.add(key)
      collection.push({ source_id: sourceId, target_id: targetId })
    }

    const registerTag = (reference, explicitNameSource) => {
      const nameSource = boundedTagNameSource(explicitNameSource || tagNameSourceFor(reference))
      const value = canonicalTagObservation(reference, nameSource)
      tags.set(value.urn, mergeCanonicalTagObservation(tags.get(value.urn), value, nameSource))
      return value.urn
    }

    for (const item of inventory) {
      const classification = classificationFor(item, authorityPin.classification_ceiling)
      if (!classification || !['TABLE', 'VIEW', 'MATERIALIZED_VIEW'].includes(item.dataset_kind)) continue
      const canonicalAssetUrn = urnFor(item)
      const tableId = `TABLE:${canonicalAssetUrn}`
      table_nodes.push({ id: tableId, classification, properties: propertiesFor(item) })
      for (const reference of item.tag_references || []) {
        const tagId = registerTag(reference)
        if (tagId) registerMetadataAssignment(table_tag_assignments, tableId, tagId)
      }
      if (item.domain_reference?.urn) {
        domains.set(item.domain_reference.urn, item.domain_reference)
        registerMetadataAssignment(table_domain_assignments, tableId, item.domain_reference.urn)
      }
      if (item.container_reference?.urn) {
        containers.set(item.container_reference.urn, item.container_reference)
        registerMetadataAssignment(table_container_assignments, tableId, item.container_reference.urn)
      }
      if (item.platform_instance_reference?.urn) {
        platform_instances.set(item.platform_instance_reference.urn, item.platform_instance_reference)
        registerMetadataAssignment(table_platform_instance_assignments, tableId, item.platform_instance_reference.urn)
      }
      for (const field of fieldsFor(item)) {
        const columnId = `COLUMN:${canonicalAssetUrn}:${field.fieldPath}`
        column_nodes.push({ id: columnId, classification, properties: propertiesFor(item, field) })
        table_column_edges.push({ table_id: tableId, column_id: columnId })
        for (const reference of normalizeDatahubTagReferences(field)) {
          const tagId = registerTag(reference)
          if (tagId) registerMetadataAssignment(column_tag_assignments, columnId, tagId)
        }
      }
    }

    let nextScrollId = null
    const seenScrollIds = new Set()
    let fetchedTerms = 0
    let pages = 0
    const terms = []
    const parent_nodes = []
    const term_parent_edges = []
    const node_parent_edges = []
    const glossary_relationships = []
    const table_assignments = []
    const column_assignments = []
    const termSet = new Set()
    const nodeSet = new Set()
    const termObservations = new Map()
    const nodeObservations = new Map()
    const termIndexes = new Map()
    const nodeIndexes = new Map()
    const glossaryIdentityTypes = new Map()
    const assignmentSet = new Set()
    const termParentEdgeSet = new Set()
    const nodeParentEdgeSet = new Set()
    const glossaryRelationshipSet = new Set()
    const assignmentTotals = new Map()
    const completeness_metadata = { fetched: 0, total: 0, per_assignment: {} }
    let lastTotal = -1

    const explicitOutgoingRelationships = async (entity) => {
      const first = entity.outgoingRelationships
      const total = first === null || first === undefined ? 0 : first.total
      if (!nonNegativeSafeInteger(total) || (first && !Array.isArray(first.relationships))) {
        profile.relationships.completeness_mismatch_count += 1
        throw metadataFailure('GLOSSARY_RELATION_PAGE_INCOMPLETE')
      }
      const relationships = [...(first?.relationships || [])]
      profile.relationships.glossary_entities_inspected += 1
      profile.relationships.provider_relationship_total += total
      profile.relationships.relationship_pages_fetched += first ? 1 : 0
      profile.relationships.relationships_fetched += relationships.length
      if (relationships.length > total) {
        profile.relationships.completeness_mismatch_count += 1
        throw metadataFailure('GLOSSARY_RELATION_COUNT_MISMATCH')
      }
      let start = relationships.length
      while (start < total) {
        const data = await fetchGraphql(relationshipsQuery, {
          urn: entity.urn,
          input: { types: [], direction: 'OUTGOING', start, count: 100, includeSoftDelete: false },
        }, signal)
        profile.relationships.relationship_pages_fetched += 1
        if (data?.entity?.urn !== entity.urn || data.entity.type !== entity.type) {
          profile.relationships.response_entity_identity_mismatch_count += 1
          identityFailure(
            profile,
            'RELATION_ENTITY_IDENTITY_MISMATCH',
            'CONTRADICTION',
            entity.urn,
            {
              entity_type: entity.type,
              response_type: data?.entity?.type,
              response_identity_matches: data?.entity?.urn === entity.urn,
            },
            pages,
            start,
          )
        }
        const page = data.entity.relationships
        if (!page || !nonNegativeSafeInteger(page.total) || !nonNegativeSafeInteger(page.start)
          || page.total !== total || page.start !== start || !Array.isArray(page.relationships)) {
          profile.relationships.completeness_mismatch_count += 1
          throw metadataFailure('GLOSSARY_RELATION_PAGE_INCOMPLETE')
        }
        const items = page.relationships
        profile.relationships.relationships_fetched += items.length
        if (items.length === 0) {
          profile.relationships.completeness_mismatch_count += 1
          throw metadataFailure('GLOSSARY_RELATION_PAGE_INCOMPLETE')
        }
        if (relationships.length + items.length > total) {
          profile.relationships.completeness_mismatch_count += 1
          throw metadataFailure('GLOSSARY_RELATION_COUNT_MISMATCH')
        }
        relationships.push(...items)
        start += items.length
      }
      if (relationships.length !== total) {
        profile.relationships.completeness_mismatch_count += 1
        throw metadataFailure('GLOSSARY_RELATION_COUNT_MISMATCH')
      }
      return relationships
    }

    const registerGlossaryTerm = async (entity, {
      pageNumber = null,
      ordinal = null,
      fromScroll = false,
    } = {}) => {
      const termInfo = entity.glossaryTermInfo || entity.properties || {}
      const tableTotal = entity.tableAssignments?.total
      const columnTotal = entity.columnAssignments?.total
      if (!nonNegativeSafeInteger(tableTotal) || !nonNegativeSafeInteger(columnTotal)) {
        throw metadataFailure('GLOSSARY_ASSIGNMENT_COUNT_MISMATCH')
      }
      const termValue = {
        urn: entity.urn,
        name: termInfo.name || entity.properties?.name || '',
        description: termInfo.description || entity.properties?.description || '',
        term_source: termInfo.termSource || entity.properties?.termSource || null,
        source_ref: termInfo.sourceRef || entity.properties?.sourceRef || null,
        source_url: termInfo.sourceUrl || entity.properties?.sourceUrl || null,
        custom_properties: customPropertiesFor(termInfo),
        structured_properties: structuredPropertiesFor(entity.structuredProperties),
        domain_reference: entity.domain?.domain?.urn ? {
          urn: entity.domain.domain.urn,
          name: entity.domain.domain.properties?.name || tailFor(entity.domain.domain.urn),
          description: entity.domain.domain.properties?.description || '',
        } : null,
      }
      const termObservation = {
        ...termValue,
        entity_type: entity.type,
        assignment_totals: { TABLE: tableTotal, COLUMN: columnTotal },
      }
      if (termSet.has(entity.urn)) {
        if (fromScroll) profile.glossary_scroll.duplicate_term_observation_count += 1
        const merged = mergeCompatibleObservation(termObservations.get(entity.urn), termObservation)
        if (merged.classification === 'CONTRADICTION') {
          identityFailure(
            profile,
            'DUPLICATE_TERM_IDENTITY',
            merged.classification,
            entity.urn,
            termObservation,
            pageNumber,
            ordinal,
          )
        }
        observeIdentityResolution(profile, merged.classification)
        termObservations.set(entity.urn, merged.value)
        terms[termIndexes.get(entity.urn)] = publicGlossaryObservation(merged.value)
      } else {
        termSet.add(entity.urn)
        termObservations.set(entity.urn, termObservation)
        termIndexes.set(entity.urn, terms.length)
        if (fromScroll) profile.glossary_scroll.unique_term_count = termSet.size
        terms.push(termValue)
        profile.assignments.declared_table_assignment_total += tableTotal
        profile.assignments.declared_column_assignment_total += columnTotal
        assignmentTotals.set(entity.urn, { TABLE: tableTotal, COLUMN: columnTotal })
      }
      for (const parentNode of entity.parentNodes?.nodes || []) {
        const edgeKey = `${entity.urn}->${parentNode.urn}`
        if (termParentEdgeSet.has(edgeKey)) {
          observeIdentityResolution(profile, 'EXACT_DUPLICATE')
          continue
        }
        termParentEdgeSet.add(edgeKey)
        term_parent_edges.push({ term_urn: entity.urn, parent_urn: parentNode.urn })
      }
      for (const relationship of await explicitOutgoingRelationships(entity)) {
        if (!['GLOSSARY_TERM', 'GLOSSARY_NODE'].includes(relationship.entity?.type)
          || typeof relationship.entity?.urn !== 'string') continue
        const relationKey = `${entity.urn}->${relationship.entity.urn}->${relationship.type}`
        const targetType = glossaryIdentityTypes.get(relationship.entity.urn)
        if (targetType && targetType !== relationship.entity.type) {
          identityFailure(
            profile,
            'RELATION_IDENTITY_CONFLICT',
            'CONTRADICTION',
            relationKey,
            { source_type: entity.type, target_type: relationship.entity.type, existing_target_type: targetType },
            pageNumber,
            ordinal,
          )
        }
        glossaryIdentityTypes.set(relationship.entity.urn, relationship.entity.type)
        if (glossaryRelationshipSet.has(relationKey)) {
          profile.relationships.duplicate_relationship_observations += 1
          observeIdentityResolution(profile, 'EXACT_DUPLICATE')
          continue
        }
        glossaryRelationshipSet.add(relationKey)
        glossary_relationships.push({
          source_urn: entity.urn,
          target_urn: relationship.entity.urn,
          source_type: entity.type,
          target_type: relationship.entity.type,
          relationship_type: relationship.type,
        })
      }
    }

    while (true) {
      if (pages >= 10002) throw metadataFailure('GLOSSARY_CURSOR_STALLED')
      const data = await fetchGraphql(glossaryQuery, scrollVariables(nextScrollId), signal)
      pages += 1
      profile.glossary_scroll.pages_fetched = pages
      const scroll = data?.scrollAcrossEntities
      if (!scroll || typeof scroll !== 'object' || !nonNegativeSafeInteger(scroll.total)
        || !Array.isArray(scroll.searchResults)) {
        throw metadataFailure('GLOSSARY_RESPONSE_MALFORMED')
      }
      const rawNextScrollId = scroll.nextScrollId
      if (rawNextScrollId !== null && rawNextScrollId !== undefined
        && (typeof rawNextScrollId !== 'string' || !rawNextScrollId)) {
        throw metadataFailure('GLOSSARY_RESPONSE_MALFORMED')
      }
      if (lastTotal !== -1 && scroll.total !== lastTotal) throw metadataFailure('GLOSSARY_TOTAL_DRIFT')
      lastTotal = scroll.total
      profile.glossary_scroll.provider_reported_total = scroll.total
      const results = scroll.searchResults
      profile.glossary_scroll.entities_fetched += results.length
      if (results.length === 0) {
        if (fetchedTerms < scroll.total || rawNextScrollId) throw metadataFailure('GLOSSARY_CURSOR_STALLED')
        break
      }
      for (const [resultIndex, result] of results.entries()) {
        const entity = result?.entity
        if (!entity || typeof entity !== 'object' || typeof entity.urn !== 'string'
          || !['GLOSSARY_TERM', 'GLOSSARY_NODE'].includes(entity.type)) {
          throw metadataFailure('GLOSSARY_RESPONSE_MALFORMED')
        }
        const existingEntityType = glossaryIdentityTypes.get(entity.urn)
        if (existingEntityType && existingEntityType !== entity.type) {
          identityFailure(
            profile,
            'RELATION_IDENTITY_CONFLICT',
            'CONTRADICTION',
            entity.urn,
            { entity_type: entity.type, existing_entity_type: existingEntityType },
            pages,
            fetchedTerms + resultIndex,
          )
        }
        glossaryIdentityTypes.set(entity.urn, entity.type)
        if (entity.type === 'GLOSSARY_TERM') {
          await registerGlossaryTerm(entity, {
            pageNumber: pages,
            ordinal: fetchedTerms + resultIndex,
            fromScroll: true,
          })
        } else {
          const nodeValue = {
            urn: entity.urn,
            name: entity.properties?.name || '',
            description: entity.properties?.description || '',
            custom_properties: customPropertiesFor(entity.properties),
            structured_properties: structuredPropertiesFor(entity.structuredProperties),
          }
          const nodeObservation = { ...nodeValue, entity_type: entity.type }
          if (nodeSet.has(entity.urn)) {
            profile.glossary_scroll.duplicate_node_observation_count += 1
            const merged = mergeCompatibleObservation(nodeObservations.get(entity.urn), nodeObservation)
            if (merged.classification === 'CONTRADICTION') {
              identityFailure(
                profile,
                'DUPLICATE_NODE_IDENTITY',
                merged.classification,
                entity.urn,
                nodeObservation,
                pages,
                fetchedTerms + resultIndex,
              )
            }
            observeIdentityResolution(profile, merged.classification)
            nodeObservations.set(entity.urn, merged.value)
            parent_nodes[nodeIndexes.get(entity.urn)] = publicGlossaryObservation(merged.value)
          } else {
            nodeSet.add(entity.urn)
            nodeObservations.set(entity.urn, nodeObservation)
            nodeIndexes.set(entity.urn, parent_nodes.length)
            profile.glossary_scroll.unique_node_count = nodeSet.size
            parent_nodes.push(nodeValue)
          }
          for (const parentNode of entity.parentNodes?.nodes || []) {
            const edgeKey = `${entity.urn}->${parentNode.urn}`
            if (nodeParentEdgeSet.has(edgeKey)) {
              observeIdentityResolution(profile, 'EXACT_DUPLICATE')
              continue
            }
            nodeParentEdgeSet.add(edgeKey)
            node_parent_edges.push({ child_urn: entity.urn, parent_urn: parentNode.urn })
          }
          for (const relationship of await explicitOutgoingRelationships(entity)) {
            if (!['GLOSSARY_TERM', 'GLOSSARY_NODE'].includes(relationship.entity?.type)
              || typeof relationship.entity?.urn !== 'string') continue
            const relationKey = `${entity.urn}->${relationship.entity.urn}->${relationship.type}`
            const targetType = glossaryIdentityTypes.get(relationship.entity.urn)
            if (targetType && targetType !== relationship.entity.type) {
              identityFailure(
                profile,
                'RELATION_IDENTITY_CONFLICT',
                'CONTRADICTION',
                relationKey,
                { source_type: entity.type, target_type: relationship.entity.type, existing_target_type: targetType },
                pages,
                fetchedTerms + resultIndex,
              )
            }
            glossaryIdentityTypes.set(relationship.entity.urn, relationship.entity.type)
            if (glossaryRelationshipSet.has(relationKey)) {
              profile.relationships.duplicate_relationship_observations += 1
              observeIdentityResolution(profile, 'EXACT_DUPLICATE')
              continue
            }
            glossaryRelationshipSet.add(relationKey)
            glossary_relationships.push({
              source_urn: entity.urn,
              target_urn: relationship.entity.urn,
              source_type: entity.type,
              target_type: relationship.entity.type,
              relationship_type: relationship.type,
            })
          }
        }
      }
      fetchedTerms += results.length
      nextScrollId = rawNextScrollId || null
      if (!nextScrollId && fetchedTerms < scroll.total) throw metadataFailure('GLOSSARY_CURSOR_STALLED')
      if (nextScrollId) {
        if (seenScrollIds.has(nextScrollId)) throw metadataFailure('GLOSSARY_CURSOR_STALLED')
        seenScrollIds.add(nextScrollId)
        profile.glossary_scroll.cursor_progression_status = 'ADVANCING'
      }
      if (fetchedTerms >= scroll.total) {
        if (fetchedTerms !== scroll.total || nextScrollId) throw metadataFailure('GLOSSARY_CURSOR_STALLED')
        break
      }
    }
    completeness_metadata.fetched = fetchedTerms
    completeness_metadata.total = lastTotal === -1 ? 0 : lastTotal
    if (fetchedTerms !== completeness_metadata.total) throw metadataFailure('GLOSSARY_CURSOR_STALLED')
    profile.glossary_scroll.cursor_progression_status = 'COMPLETE'
    profile.glossary_scroll.completion_status = true

    const assignmentReferences = []
    for (const item of inventory) {
      const classification = classificationFor(item, authorityPin.classification_ceiling)
      for (const term of item.glossary_terms || []) {
        if (term?.urn) assignmentReferences.push({ type: 'TABLE', reference: term, item, field: null, classification })
      }
      for (const field of fieldsFor(item)) {
        for (const reference of field.glossaryTerms?.terms || []) {
          if (reference.term?.urn) assignmentReferences.push({
            type: 'COLUMN', reference: reference.term, item, field, classification,
          })
        }
      }
    }

    const missingTermReferences = new Map()
    for (const assignment of assignmentReferences) {
      const termUrn = assignment.reference.urn
      if (termSet.has(termUrn)) continue
      profile.assignments.term_outside_snapshot_count += 1
      profile.assignments.missing_term_reference_count += 1
      if (assignment.type === 'TABLE') profile.assignments.table_missing_term_count += 1
      else profile.assignments.column_missing_term_count += 1
      const observations = missingTermReferences.get(termUrn) || []
      observations.push(assignment.reference)
      missingTermReferences.set(termUrn, observations)
    }
    const directTermReferences = [...missingTermReferences.entries()]
      .sort(([left], [right]) => left.localeCompare(right))
    profile.direct_resolution.total = directTermReferences.length
    profile.direct_resolution.batch_total = Math.ceil(
      directTermReferences.length / DIRECT_GLOSSARY_TERM_BATCH_SIZE,
    )
    publishProgress()
    for (let offset = 0; offset < directTermReferences.length;
      offset += DIRECT_GLOSSARY_TERM_BATCH_SIZE) {
      const batch = directTermReferences.slice(offset, offset + DIRECT_GLOSSARY_TERM_BATCH_SIZE)
      const urns = batch.map(([termUrn]) => termUrn)
      const batchStartedAt = Date.now()
      profile.direct_resolution.batch_number = Math.floor(offset / DIRECT_GLOSSARY_TERM_BATCH_SIZE) + 1
      profile.direct_resolution.batch_requested_count = batch.length
      profile.direct_resolution.batch_response_count = 0
      profile.direct_resolution.batch_elapsed_ms = 0
      profile.direct_resolution.provider_failure_class = null
      profile.direct_resolution.graphql_error_class = null
      profile.direct_resolution.graphql_error_path = null
      profile.direct_resolution.failing_identity_hash = boundedIdentityHash(urns.join('\n'))
      publishProgress()
      let data
      try {
        data = await fetchGraphql(glossaryTermsQuery, { urns }, signal)
      } catch (error) {
        profile.direct_resolution.batch_elapsed_ms = Date.now() - batchStartedAt
        profile.direct_resolution.retry_attempt = boundedCount(error?.providerRetryAttempt)
          || profile.direct_resolution.retry_attempt
        profile.direct_resolution.provider_failure_class = providerFailureClass(error)
        profile.direct_resolution.graphql_error_class = error?.providerGraphqlDiagnostic?.error_class || null
        profile.direct_resolution.graphql_error_path = error?.providerGraphqlDiagnostic?.path || null
        publishProgress()
        throw profileError(error, profile)
      }
      profile.direct_resolution.batch_elapsed_ms = Date.now() - batchStartedAt
      profile.direct_resolution.batch_response_count = Array.isArray(data?.entities)
        ? data.entities.length
        : 0
      if (!data || typeof data !== 'object' || Array.isArray(data)
        || !Array.isArray(data.entities) || data.entities.length !== batch.length) {
        profile.direct_resolution.provider_failure_class = 'CONTRACT'
        publishProgress()
        throw providerContractFailure(profile)
      }
      for (const [[termUrn, references], entity] of batch.map((entry, index) => (
        [entry, data.entities[index]]
      ))) {
        profile.assignments.direct_term_resolution_attempt_count += 1
        if (entity === null) {
          profile.assignments.direct_term_resolution_dangling_count += 1
          identityFailure(
            profile,
            'DANGLING_GLOSSARY_ASSIGNMENT',
            'CONTRADICTION',
            termUrn,
            { resolution: 'ABSENT', assignment_reference_count: references.length },
            pages,
            profile.assignments.direct_term_resolution_attempt_count,
          )
        }
        if (!entity || typeof entity !== 'object' || Array.isArray(entity)
          || typeof entity.urn !== 'string' || typeof entity.type !== 'string') {
          throw providerContractFailure(profile)
        }
        if (entity.urn !== termUrn) throw providerContractFailure(profile)
        if (entity.type !== 'GLOSSARY_TERM') {
          profile.assignments.direct_term_resolution_dangling_count += 1
          identityFailure(
            profile,
            'DANGLING_GLOSSARY_ASSIGNMENT',
            'CONTRADICTION',
            termUrn,
            { resolution: 'INCOMPATIBLE_ENTITY_TYPE', entity_type: entity.type },
            pages,
            profile.assignments.direct_term_resolution_attempt_count,
          )
        }
        if (typeof entity.exists !== 'boolean') throw providerContractFailure(profile)
        if (entity.status !== null && entity.status !== undefined
          && (typeof entity.status !== 'object' || Array.isArray(entity.status)
            || typeof entity.status.removed !== 'boolean')) throw providerContractFailure(profile)
        if (entity.exists === false || entity.status?.removed === true) {
          profile.assignments.direct_term_resolution_dangling_count += 1
          identityFailure(
            profile,
            'DANGLING_GLOSSARY_ASSIGNMENT',
            'CONTRADICTION',
            termUrn,
            {
              resolution: entity.status?.removed === true ? 'REMOVED' : 'DOES_NOT_EXIST',
              assignment_reference_count: references.length,
            },
            pages,
            profile.assignments.direct_term_resolution_attempt_count,
          )
        }
        const existingEntityType = glossaryIdentityTypes.get(entity.urn)
        if (existingEntityType && existingEntityType !== entity.type) {
          identityFailure(
            profile,
            'RELATION_IDENTITY_CONFLICT',
            'CONTRADICTION',
            entity.urn,
            { entity_type: entity.type, existing_entity_type: existingEntityType },
            pages,
            profile.assignments.direct_term_resolution_attempt_count,
          )
        }
        glossaryIdentityTypes.set(entity.urn, entity.type)
        await registerGlossaryTerm(entity, {
          pageNumber: pages,
          ordinal: profile.assignments.direct_term_resolution_attempt_count,
        })
        let mergedObservation = termObservations.get(termUrn)
        for (const reference of references) {
          const sparseObservation = {
            urn: termUrn,
            name: typeof reference.name === 'string' ? reference.name : '',
            description: typeof reference.description === 'string' ? reference.description : '',
            term_source: null,
            source_ref: null,
            source_url: null,
            custom_properties: [],
            structured_properties: [],
            domain_reference: null,
            entity_type: 'GLOSSARY_TERM',
          }
          const merged = mergeCompatibleObservation(mergedObservation, sparseObservation)
          if (merged.classification === 'CONTRADICTION') {
            identityFailure(
              profile,
              'DUPLICATE_TERM_IDENTITY',
              merged.classification,
              termUrn,
              sparseObservation,
              pages,
              profile.assignments.direct_term_resolution_attempt_count,
            )
          }
          observeIdentityResolution(profile, merged.classification)
          mergedObservation = merged.value
        }
        termObservations.set(termUrn, mergedObservation)
        terms[termIndexes.get(termUrn)] = publicGlossaryObservation(mergedObservation)
        profile.assignments.direct_term_resolution_recovered_count += 1
        profile.direct_resolution.completed_resolution_count += 1
      }
      profile.direct_resolution.failing_identity_hash = null
      publishProgress()
      // Runtime latency/retry observations are diagnostic-only. Successful
      // source profiles participate in deterministic source fencing and must
      // not vary with wall-clock/provider timing.
      profile.direct_resolution.batch_elapsed_ms = 0
    }
    profile.direct_resolution.retry_attempt = 0

    const observedAssignmentTotals = new Map([...termSet].sort()
      .map((urn) => [urn, { TABLE: 0, COLUMN: 0 }]))
    const registerAssignment = (type, termUrn, item, field, classification) => {
      if (type === 'TABLE') profile.assignments.observed_table_assignment_total += 1
      else profile.assignments.observed_column_assignment_total += 1
      if (!termSet.has(termUrn)) {
        throw providerContractFailure(profile)
      }
      const assignId = type === 'TABLE'
        ? `TABLE:${urnFor(item)}`
        : `COLUMN:${urnFor(item)}:${field.fieldPath}`
      const assignKey = `${assignId}->${termUrn}`
      if (assignmentSet.has(assignKey)) {
        profile.assignments.duplicate_assignment_observation_count += 1
        observeIdentityResolution(profile, 'EXACT_DUPLICATE')
        return
      }
      assignmentSet.add(assignKey)
      observedAssignmentTotals.get(termUrn)[type] += 1
      if (!classification || !['TABLE', 'VIEW', 'MATERIALIZED_VIEW'].includes(item.dataset_kind)) return
      const assignment = {
        id: assignId,
        term_urn: termUrn,
        classification,
        properties: propertiesFor(item, field),
      }
      if (type === 'TABLE') table_assignments.push(assignment)
      else column_assignments.push(assignment)
    }

    for (const assignment of assignmentReferences) {
      registerAssignment(
        assignment.type,
        assignment.reference.urn,
        assignment.item,
        assignment.field,
        assignment.classification,
      )
    }

    for (const termUrn of [...termSet].sort()) {
      const expected = assignmentTotals.get(termUrn)
      const observed = observedAssignmentTotals.get(termUrn)
      completeness_metadata.per_assignment[termUrn] = {
        TABLE: { fetched: observed.TABLE, total: expected.TABLE },
        COLUMN: { fetched: observed.COLUMN, total: expected.COLUMN },
      }
      if (observed.TABLE !== expected.TABLE || observed.COLUMN !== expected.COLUMN) {
        throw metadataFailure('GLOSSARY_ASSIGNMENT_COUNT_MISMATCH')
      }
    }

    return {
      authority_pin: authorityPin,
      source_profile: sanitizeK9MetadataSourceProfile(profile),
      completeness_metadata,
      table_nodes: table_nodes.sort(compareBy('id')),
      column_nodes: column_nodes.sort(compareBy('id')),
      table_column_edges: table_column_edges.sort(compareBy('table_id', 'column_id')),
      terms: terms.sort(compareBy('urn')),
      parent_nodes: parent_nodes.sort(compareBy('urn')),
      table_assignments: table_assignments.sort(compareBy('id', 'term_urn')),
      column_assignments: column_assignments.sort(compareBy('id', 'term_urn')),
      term_parent_edges: term_parent_edges.sort(compareBy('term_urn', 'parent_urn')),
      node_parent_edges: node_parent_edges.sort(compareBy('child_urn', 'parent_urn')),
      glossary_relationships: glossary_relationships.sort(compareBy(
        'source_urn', 'target_urn', 'relationship_type',
      )),
      tags: [...tags.values()].map(publicTag).sort((left, right) => left.urn.localeCompare(right.urn)),
      domains: [...domains.values()].sort((left, right) => left.urn.localeCompare(right.urn)),
      containers: [...containers.values()].sort((left, right) => left.urn.localeCompare(right.urn)),
      platform_instances: [...platform_instances.values()].sort((left, right) => left.urn.localeCompare(right.urn)),
      table_tag_assignments: table_tag_assignments.sort(compareBy('source_id', 'target_id')),
      column_tag_assignments: column_tag_assignments.sort(compareBy('source_id', 'target_id')),
      table_domain_assignments: table_domain_assignments.sort(compareBy('source_id', 'target_id')),
      table_container_assignments: table_container_assignments.sort(compareBy('source_id', 'target_id')),
      table_platform_instance_assignments: table_platform_instance_assignments.sort(compareBy('source_id', 'target_id')),
    }
    } catch (error) {
      if (!profile.glossary_scroll.completion_status) {
        profile.glossary_scroll.cursor_progression_status = 'FAILED'
      }
      throw profileError(error, profile)
    }
  }

  return async function collectK9Metadata(authorityPin, inventory, context) {
    try {
      return await collect(authorityPin, inventory, context)
    } catch (error) {
      if (error?.k9SourceFailureDetailCode || providerFailure(error)) throw error
      throw metadataFailure('METADATA_NORMALIZATION_FAILED', error, error?.k9MetadataSourceProfile)
    }
  }
}
