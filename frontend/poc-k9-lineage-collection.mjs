import { createHash } from 'node:crypto'

export const K9_LINEAGE_FAILURE_DETAILS = Object.freeze([
  'LINEAGE_TOTAL_DRIFT',
  'LINEAGE_PAGE_GAP',
  'LINEAGE_RESPONSE_MALFORMED',
  'LINEAGE_DUPLICATE_REPLAY',
  'LINEAGE_COMPLETENESS_MISMATCH',
])

export const K9_LINEAGE_SOURCE_PROFILE_CONTRACT = 'DATARIVER_K9_LINEAGE_SOURCE_PROFILE_V1'

const supportedFailureDetails = new Set(K9_LINEAGE_FAILURE_DETAILS)
const supportedDirections = new Set(['UPSTREAM', 'DOWNSTREAM'])
const hashPattern = /^[0-9a-f]{64}$/u

function boundedCount(value) {
  return Number.isSafeInteger(value) && value >= 0 ? Math.min(value, 1_000_000_000) : 0
}

function boundedDirection(value) {
  return supportedDirections.has(value) ? value : null
}

function boundedIdentityHash(value) {
  return createHash('sha256').update(String(value || ''), 'utf8').digest('hex')
}

function nonNegativeInteger(value) {
  return Number.isSafeInteger(value) && value >= 0
}

export function sanitizeK9LineageSourceProfile(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)
    || value.contract !== K9_LINEAGE_SOURCE_PROFILE_CONTRACT) return null
  const failure = value.failure && typeof value.failure === 'object' && !Array.isArray(value.failure)
    && supportedFailureDetails.has(value.failure.detail_code)
    && boundedDirection(value.failure.direction)
    && hashPattern.test(value.failure.identity_hash || '')
    ? {
        detail_code: value.failure.detail_code,
        direction: value.failure.direction,
        page_number: boundedCount(value.failure.page_number),
        request_start: boundedCount(value.failure.request_start),
        response_start: boundedCount(value.failure.response_start),
        response_count: boundedCount(value.failure.response_count),
        total: boundedCount(value.failure.total),
        filtered: boundedCount(value.failure.filtered),
        relationships: boundedCount(value.failure.relationships),
        identity_hash: value.failure.identity_hash,
      }
    : null
  return {
    contract: K9_LINEAGE_SOURCE_PROFILE_CONTRACT,
    total_asset_count: boundedCount(value.total_asset_count),
    processed_asset_count: boundedCount(value.processed_asset_count),
    pages_fetched: boundedCount(value.pages_fetched),
    provider_relationship_total: boundedCount(value.provider_relationship_total),
    returned_relationship_count: boundedCount(value.returned_relationship_count),
    filtered_relationship_count: boundedCount(value.filtered_relationship_count),
    projectable_table_edge_observation_count: boundedCount(value.projectable_table_edge_observation_count),
    projectable_column_edge_observation_count: boundedCount(value.projectable_column_edge_observation_count),
    outside_source_scope_relationship_count: boundedCount(value.outside_source_scope_relationship_count),
    exact_duplicate_observation_count: boundedCount(value.exact_duplicate_observation_count),
    distinct_same_edge_observation_count: boundedCount(value.distinct_same_edge_observation_count),
    failure,
  }
}

function lineageFailure(detailCode, profile, failure) {
  if (!supportedFailureDetails.has(detailCode)) {
    throw new Error('The K9 lineage failure detail is invalid.')
  }
  const error = Object.assign(
    new Error('The bounded K9 lineage collection invariant failed.'),
    { k9SourceFailureDetailCode: detailCode },
  )
  const sanitized = sanitizeK9LineageSourceProfile({ ...profile, failure: {
    detail_code: detailCode,
    ...failure,
  } })
  if (sanitized) error.k9LineageSourceProfile = Object.freeze(sanitized)
  return error
}

function malformedFailure(profile, trace, response = {}) {
  return lineageFailure('LINEAGE_RESPONSE_MALFORMED', profile, {
    direction: trace.direction,
    page_number: trace.pagesFetched + 1,
    request_start: trace.nextStart,
    response_start: response?.start,
    response_count: response?.count,
    total: response?.total,
    filtered: response?.filtered,
    relationships: Array.isArray(response?.relationships) ? response.relationships.length : 0,
    identity_hash: trace.identityHash,
  })
}

/**
 * Tracks one exact DataHub GraphQL EntityLineageResult pagination trace.
 * DataHub's `filtered` count belongs to the requested page and accounts for
 * soft-deleted or non-existent relationships omitted from `relationships`.
 * Request offsets therefore advance by the fixed request count, never by the
 * returned relationship count.
 */
export function createK9LineageTrace({
  assetIdentity,
  direction,
  requestedCount = 100,
  maximumPages = 10_002,
  totalAssetCount = 0,
  processedAssetCount = 0,
} = {}) {
  if (!supportedDirections.has(direction)
    || typeof assetIdentity !== 'string' || !assetIdentity
    || !Number.isSafeInteger(requestedCount) || requestedCount < 1 || requestedCount > 1_000
    || !Number.isSafeInteger(maximumPages) || maximumPages < 1 || maximumPages > 100_000) {
    throw new TypeError('The K9 lineage trace configuration is invalid.')
  }

  const profile = {
    contract: K9_LINEAGE_SOURCE_PROFILE_CONTRACT,
    total_asset_count: boundedCount(totalAssetCount),
    processed_asset_count: boundedCount(processedAssetCount),
    pages_fetched: 0,
    provider_relationship_total: 0,
    returned_relationship_count: 0,
    filtered_relationship_count: 0,
    projectable_table_edge_observation_count: 0,
    projectable_column_edge_observation_count: 0,
    outside_source_scope_relationship_count: 0,
    exact_duplicate_observation_count: 0,
    distinct_same_edge_observation_count: 0,
    failure: null,
  }
  const trace = {
    direction,
    identityHash: boundedIdentityHash(assetIdentity),
    nextStart: 0,
    pagesFetched: 0,
    providerTotal: null,
    returnedRelationships: 0,
    filteredRelationships: 0,
  }
  const observationPages = new Map()
  const edgeObservations = new Map()

  const failureContext = (response = {}) => ({
    direction,
    page_number: trace.pagesFetched + 1,
    request_start: trace.nextStart,
    response_start: response?.start,
    response_count: response?.count,
    total: response?.total ?? trace.providerTotal,
    filtered: response?.filtered,
    relationships: Array.isArray(response?.relationships) ? response.relationships.length : 0,
    identity_hash: trace.identityHash,
  })

  return Object.freeze({
    get nextStart() { return trace.nextStart },
    get pagesFetched() { return trace.pagesFetched },

    observePage(response) {
      if (trace.pagesFetched >= maximumPages) {
        throw lineageFailure('LINEAGE_COMPLETENESS_MISMATCH', profile, failureContext(response))
      }
      if (!response || typeof response !== 'object' || Array.isArray(response)
        || !nonNegativeInteger(response.start)
        || !nonNegativeInteger(response.count)
        || !nonNegativeInteger(response.total)
        || !nonNegativeInteger(response.filtered)
        || !Array.isArray(response.relationships)
        || response.start !== trace.nextStart
        || response.count > requestedCount
        || response.relationships.length > requestedCount
        || response.filtered > requestedCount
        || response.relationships.length + response.filtered > requestedCount) {
        throw malformedFailure(profile, trace, response)
      }
      if (trace.providerTotal !== null && response.total !== trace.providerTotal) {
        throw lineageFailure('LINEAGE_TOTAL_DRIFT', profile, failureContext(response))
      }
      if (trace.providerTotal === null) trace.providerTotal = response.total
      const explainedPageCount = response.relationships.length + response.filtered
      if (explainedPageCount === 0 && trace.nextStart < response.total) {
        throw lineageFailure('LINEAGE_PAGE_GAP', profile, failureContext(response))
      }

      trace.pagesFetched += 1
      trace.returnedRelationships += response.relationships.length
      trace.filteredRelationships += response.filtered
      profile.pages_fetched = trace.pagesFetched
      profile.provider_relationship_total = trace.providerTotal
      profile.returned_relationship_count = trace.returnedRelationships
      profile.filtered_relationship_count = trace.filteredRelationships

      if (trace.returnedRelationships + trace.filteredRelationships > trace.providerTotal) {
        throw lineageFailure('LINEAGE_COMPLETENESS_MISMATCH', profile, {
          ...failureContext(response), page_number: trace.pagesFetched,
        })
      }
      const currentStart = trace.nextStart
      trace.nextStart += requestedCount
      const done = trace.nextStart >= trace.providerTotal
      return Object.freeze({
        start: currentStart,
        done,
        relationships: response.relationships,
      })
    },

    observeRelationship({ observationIdentity, edgeIdentity } = {}) {
      if (!hashPattern.test(observationIdentity || '')
        || typeof edgeIdentity !== 'string' || !edgeIdentity) {
        throw malformedFailure(profile, trace)
      }
      const currentPageStart = trace.nextStart - requestedCount
      const previousPageStart = observationPages.get(observationIdentity)
      if (previousPageStart !== undefined && previousPageStart !== currentPageStart) {
        throw lineageFailure('LINEAGE_DUPLICATE_REPLAY', profile, {
          ...failureContext(),
          page_number: trace.pagesFetched,
          request_start: currentPageStart,
          identity_hash: trace.identityHash,
        })
      }
      if (previousPageStart === currentPageStart) {
        profile.exact_duplicate_observation_count += 1
        return 'EXACT_DUPLICATE'
      }
      observationPages.set(observationIdentity, currentPageStart)
      const edgeObservationSet = edgeObservations.get(edgeIdentity) || new Set()
      const disposition = edgeObservationSet.size > 0 ? 'DISTINCT_OBSERVATION' : 'NEW_EDGE'
      if (disposition === 'DISTINCT_OBSERVATION') profile.distinct_same_edge_observation_count += 1
      edgeObservationSet.add(observationIdentity)
      edgeObservations.set(edgeIdentity, edgeObservationSet)
      return disposition
    },

    rejectMalformedRelationship() {
      throw malformedFailure(profile, trace)
    },

    recordProjectableTableEdge() {
      profile.projectable_table_edge_observation_count += 1
    },

    recordProjectableColumnEdge() {
      profile.projectable_column_edge_observation_count += 1
    },

    recordOutsideSourceScope() {
      profile.outside_source_scope_relationship_count += 1
    },

    complete() {
      const total = trace.providerTotal ?? 0
      if (trace.returnedRelationships + trace.filteredRelationships !== total) {
        throw lineageFailure('LINEAGE_COMPLETENESS_MISMATCH', profile, {
          ...failureContext(),
          page_number: trace.pagesFetched,
          request_start: Math.max(0, trace.nextStart - requestedCount),
          total,
          filtered: 0,
          relationships: 0,
        })
      }
      return Object.freeze({
        returned: trace.returnedRelationships,
        filtered: trace.filteredRelationships,
        total,
        pages: trace.pagesFetched,
        profile: Object.freeze(sanitizeK9LineageSourceProfile(profile)),
      })
    },
  })
}
