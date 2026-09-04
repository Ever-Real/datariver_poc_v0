#!/usr/bin/env node
/* global AbortSignal, URL, URLSearchParams, clearInterval, fetch, setInterval, setTimeout */

import { chmod, lstat, readFile, rename, unlink, writeFile } from 'node:fs/promises'
import process from 'node:process'

import { prepGeneralSmokeClassification } from '../frontend/poc-llm-timeout.mjs'
import { K9_METADATA_FAILURE_DETAILS } from '../frontend/poc-k9-metadata-collection.mjs'
import {
  K9_LINEAGE_FAILURE_DETAILS,
  sanitizeK9LineageSourceProfile,
} from '../frontend/poc-k9-lineage-collection.mjs'
import { K9_V2_FAILURE_CODES } from '../frontend/poc-k9-lifecycle-v2.mjs'
import { sanitizeK9SourcePersistenceDiagnosticV2 } from '../frontend/poc-k9-lifecycle-persistence.mjs'

const processStarted = Date.now()
const inventoryFailureClassifications = new Set([
  'PREP_DATAHUB_INVENTORY_QUERY_FAILED',
  'PREP_DATAHUB_INVENTORY_PAGE_FAILED',
  'PREP_DATAHUB_INVENTORY_GRAPHQL_FAILED',
  'PREP_DATAHUB_INVENTORY_CONTRACT_FAILED',
  'PREP_DATAHUB_INVENTORY_NORMALIZATION_FAILED',
  'PREP_DATAHUB_INVENTORY_PROMOTION_FAILED',
])
const k9SourceFailureStages = new Set([
  'INVENTORY',
  'INVENTORY_PROJECTION',
  'LINEAGE_COLLECTION',
  'METADATA_COLLECTION',
  'RUNTIME_IDENTITY',
])
const k9SourceFailureDetails = new Set([
  'CONNECTIVITY',
  'TIMEOUT',
  'HTTP_4XX',
  'HTTP_5XX',
  'GRAPHQL',
  'CONTRACT',
  'EMPTY_SOURCE',
  'INTERNAL_TRANSFORM',
  ...K9_LINEAGE_FAILURE_DETAILS,
  ...K9_METADATA_FAILURE_DETAILS,
])
const k9ProviderFailureClasses = new Set([
  'CONNECTIVITY', 'TIMEOUT', 'HTTP_4XX', 'HTTP_5XX', 'HTTP_OTHER',
  'GRAPHQL', 'CONTRACT',
])
const glossaryFailureClassifications = new Set([
  'PREP_SMOKE_GLOSSARY_TERM_INPUT_FAILED',
  'PREP_SMOKE_GLOSSARY_TERM_DISCOVERY_FAILED',
  'PREP_SMOKE_GLOSSARY_TERM_LOOKUP_FAILED',
  'PREP_SMOKE_GLOSSARY_TERM_NOT_FOUND_FAILED',
  'PREP_SMOKE_GLOSSARY_TERM_CONTRACT_FAILED',
])
const k9V2Projectors = Object.freeze(['LINEAGE', 'METADATA', 'SEMANTIC'])
const k9V2FailureCodes = new Set(K9_V2_FAILURE_CODES)
const safeK9Token = (value) => typeof value === 'string' && /^[A-Z][A-Z0-9_]{0,95}$/.test(value)
const safeSnapshotHash = (value) => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value)
const safeK9Timestamp = (value) => typeof value === 'string'
  && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(value)
  && Number.isFinite(Date.parse(value))

function argument(name, fallback = null) {
  const index = process.argv.indexOf(name)
  return index >= 0 ? process.argv[index + 1] : fallback
}

function smokeFailure(stage, classification, message, status = null, diagnostic = null) {
  return Object.assign(new Error(message), {
    stage,
    classification,
    status,
    diagnostic,
    terminal: diagnostic?.terminal === true,
  })
}

function adminLoginClassification(body, status) {
  if (body?.code === 'ORIGIN_FORBIDDEN' && status === 403) {
    return 'PREP_SMOKE_ADMIN_ORIGIN_FAILED'
  }
  if (body?.code === 'AUTHENTICATION_FAILED' && status === 401) {
    return 'PREP_SMOKE_ADMIN_AUTH_FAILED'
  }
  return 'PREP_SMOKE_ADMIN_LOGIN_FAILED'
}

function mclFailureDiagnostic(body) {
  const productClassification = /^PREP_MCL_(DISCOVERY|CAPTURE)_[A-Z0-9_]+$/
    .test(body?.capture_failure_classification || '')
    ? body.capture_failure_classification
    : null
  const failureStage = /^[A-Z][A-Z0-9_]{0,79}$/.test(body?.capture_failure_stage || '')
    ? body.capture_failure_stage
    : null
  const failureDetailCode = /^[A-Z][A-Z0-9_]{0,79}$/.test(body?.capture_failure_detail_code || '')
    ? body.capture_failure_detail_code
    : null
  return {
    terminal: true,
    product_classification: productClassification,
    failure_stage: failureStage,
    failure_detail_code: failureDetailCode,
  }
}

function boundedK9SourceEligibility(value) {
  if (!value || value.contract !== 'DATARIVER_K9_SOURCE_ELIGIBILITY_V1'
    || value.classification_authority !== false) return null
  const fields = [
    'provider_current_inventory_count', 'canonical_current_count', 'eligible_source_count',
    'invalid_identity_count', 'unsupported_kind_count', 'classification_exact_count',
    'classification_missing_count', 'classification_multiple_count', 'classification_invalid_count',
  ]
  if (fields.some((field) => !Number.isSafeInteger(value[field])
    || value[field] < 0 || value[field] > 1_000_000_000)) return null
  return Object.fromEntries([
    ['contract', value.contract],
    ...fields.map((field) => [field, value[field]]),
    ['classification_ceiling', safeK9Token(value.classification_ceiling)
      ? value.classification_ceiling : null],
    ['classification_authority', false],
  ])
}

function k9SourceFailureDiagnostic(asset) {
  if (!(asset?.last_error_code === 'K9_DATAHUB_SOURCE_FAILED'
    && k9SourceFailureStages.has(asset?.failure_stage)
    && k9SourceFailureDetails.has(asset?.failure_detail_code))) return null
  const profile = asset?.metadata_source_profile
  const assignments = profile?.assignments
  const count = (value) => Number.isSafeInteger(value) && value >= 0 ? value : 0
  const boundedAssignments = assignments && typeof assignments === 'object' ? {
    raw_table_refs: count(assignments.raw_table_refs),
    raw_column_refs: count(assignments.raw_column_refs),
    projectable_table_refs: count(assignments.projectable_table_refs),
    projectable_column_refs: count(assignments.projectable_column_refs),
    dangling_table_refs: count(assignments.dangling_table_refs),
    dangling_column_refs: count(assignments.dangling_column_refs),
    unique_projected_table_edges: count(assignments.unique_projected_table_edges),
    unique_projected_column_edges: count(assignments.unique_projected_column_edges),
    duplicate_table_refs: count(assignments.duplicate_table_refs),
    duplicate_column_refs: count(assignments.duplicate_column_refs),
    provider_incoming_table_total: count(assignments.provider_incoming_table_total),
    provider_incoming_column_total: count(assignments.provider_incoming_column_total),
  } : null
  const direct = profile?.direct_resolution
  const boundedDirect = direct && typeof direct === 'object' ? {
    total: Number.isSafeInteger(direct.total) ? direct.total : 0,
    total_unique_terms: Number.isSafeInteger(direct.total_unique_terms) ? direct.total_unique_terms : 0,
    recovered_unique_terms: Number.isSafeInteger(direct.recovered_unique_terms) ? direct.recovered_unique_terms : 0,
    dangling_unique_terms: Number.isSafeInteger(direct.dangling_unique_terms) ? direct.dangling_unique_terms : 0,
    recovered_assignment_references: Number.isSafeInteger(direct.recovered_assignment_references)
      ? direct.recovered_assignment_references : 0,
    dangling_assignment_references: Number.isSafeInteger(direct.dangling_assignment_references)
      ? direct.dangling_assignment_references : 0,
    dangling_absent_count: Number.isSafeInteger(direct.dangling_absent_count)
      ? direct.dangling_absent_count : 0,
    dangling_does_not_exist_count: Number.isSafeInteger(direct.dangling_does_not_exist_count)
      ? direct.dangling_does_not_exist_count : 0,
    dangling_removed_count: Number.isSafeInteger(direct.dangling_removed_count)
      ? direct.dangling_removed_count : 0,
    dangling_incompatible_type_count: Number.isSafeInteger(direct.dangling_incompatible_type_count)
      ? direct.dangling_incompatible_type_count : 0,
    batch_size: Number.isSafeInteger(direct.batch_size) ? direct.batch_size : 0,
    batch_total: Number.isSafeInteger(direct.batch_total) ? direct.batch_total : 0,
    batch_number: Number.isSafeInteger(direct.batch_number) ? direct.batch_number : 0,
    batch_requested_count: Number.isSafeInteger(direct.batch_requested_count)
      ? direct.batch_requested_count : 0,
    batch_response_count: Number.isSafeInteger(direct.batch_response_count)
      ? direct.batch_response_count : 0,
    batch_elapsed_ms: Number.isSafeInteger(direct.batch_elapsed_ms) ? direct.batch_elapsed_ms : 0,
    completed_resolution_count: Number.isSafeInteger(direct.completed_resolution_count)
      ? direct.completed_resolution_count : 0,
    retry_attempt: Number.isSafeInteger(direct.retry_attempt) ? direct.retry_attempt : 0,
    provider_failure_class: k9ProviderFailureClasses.has(direct.provider_failure_class)
      ? direct.provider_failure_class : null,
    graphql_error_class: typeof direct.graphql_error_class === 'string'
      && /^[A-Z][A-Z0-9_]{0,63}$/.test(direct.graphql_error_class)
      ? direct.graphql_error_class : null,
    graphql_error_path: typeof direct.graphql_error_path === 'string'
      && /^[A-Za-z0-9_.]{1,160}$/.test(direct.graphql_error_path)
      ? direct.graphql_error_path : null,
    failing_identity_hash: typeof direct.failing_identity_hash === 'string'
      && /^[0-9a-f]{64}$/.test(direct.failing_identity_hash)
      ? direct.failing_identity_hash : null,
    first_dangling_identity_hash: typeof direct.first_dangling_identity_hash === 'string'
      && /^[0-9a-f]{64}$/.test(direct.first_dangling_identity_hash)
      ? direct.first_dangling_identity_hash : null,
  } : null
  const sourceEligibility = boundedK9SourceEligibility(asset.source_eligibility)
  const lineageProfile = sanitizeK9LineageSourceProfile(asset.lineage_source_profile)
  return {
    failure_stage: asset.failure_stage,
    failure_detail_code: asset.failure_detail_code,
    ...(sourceEligibility ? { source_eligibility: sourceEligibility } : {}),
    ...(lineageProfile ? { lineage_profile: lineageProfile } : {}),
    ...(boundedDirect ? {
      provider_failure_class: boundedDirect.provider_failure_class,
      batch_number: boundedDirect.batch_number,
      batch_count: boundedDirect.batch_total,
      batch_requested_count: boundedDirect.batch_requested_count,
      batch_response_count: boundedDirect.batch_response_count,
      batch_elapsed_ms: boundedDirect.batch_elapsed_ms,
      metadata_profile: {
        contract: profile.contract,
        glossary_reported_total: profile.glossary_scroll?.provider_reported_total || 0,
        glossary_entities_fetched: profile.glossary_scroll?.entities_fetched || 0,
        missing_term_reference_count: profile.assignments?.missing_term_reference_count || 0,
        ...(boundedAssignments ? { assignments: boundedAssignments } : {}),
        direct_resolution: boundedDirect,
      },
    } : {}),
  }
}

function k9SourceWarning(asset) {
  const warning = asset?.k9_source_warning
  if (!warning || warning.code !== 'DANGLING_GLOSSARY_ASSIGNMENTS') return null
  const count = (value) => Number.isSafeInteger(value) && value >= 0 ? value : 0
  const bounded = {
    code: 'DANGLING_GLOSSARY_ASSIGNMENTS',
    dangling_unique_terms: count(warning.dangling_unique_terms),
    dangling_assignment_references: count(warning.dangling_assignment_references),
    absent: count(warning.absent),
    does_not_exist: count(warning.does_not_exist),
    removed: count(warning.removed),
  }
  return bounded.dangling_unique_terms > 0 ? bounded : null
}

function k9AssignmentScope(asset) {
  const value = asset?.k9_assignment_scope
  const count = (item) => Number.isSafeInteger(item) && item >= 0 ? item : 0
  if (!value || !['EQUAL', 'GLOBAL_GREATER', 'GLOBAL_SMALLER', 'MIXED']
    .includes(value.provider_scope_relation)) return null
  return {
    provider_incoming_table_total: count(value.provider_incoming_table_total),
    provider_incoming_column_total: count(value.provider_incoming_column_total),
    k9_scoped_table_reference_total: count(value.k9_scoped_table_reference_total),
    k9_scoped_column_reference_total: count(value.k9_scoped_column_reference_total),
    provider_scope_relation: value.provider_scope_relation,
  }
}

function k9V2ProjectorFailure(lifecycle) {
  if (lifecycle?.contract !== 'DATARIVER_K9_LIFECYCLE_STATUS_V2') return null
  for (const projector of k9V2Projectors) {
    const state = lifecycle.projectors?.[projector]
    if (state?.status !== 'FAILED') continue
    const code = safeK9Token(state.diagnostic?.code)
      ? state.diagnostic.code : `K9_${projector}_PROJECTOR_FAILED`
    const stage = safeK9Token(state.diagnostic?.stage)
      ? state.diagnostic.stage : `${projector}_PROJECTOR`
    const progressValue = state.progress && typeof state.progress === 'object'
      ? state.progress : {}
    const count = (value) => Number.isSafeInteger(value) && value >= 0 ? value : 0
    const diagnosticValue = state.diagnostic && typeof state.diagnostic === 'object'
      ? state.diagnostic : {}
    return {
      projector,
      classification: projector === 'SEMANTIC'
        ? 'PREP_SMOKE_SEMANTIC_INDEX_NOT_READY'
        : 'PREP_SMOKE_K9_NEO4J_PROJECTION_FAILED',
      diagnostic: {
        terminal: true,
        product_error_code: code,
        failure_stage: stage,
        failure_detail_code: safeK9Token(diagnosticValue.failure_detail_code)
          ? diagnosticValue.failure_detail_code : code,
        projector,
        provider_failure_class: safeK9Token(diagnosticValue.provider_failure_class)
          ? diagnosticValue.provider_failure_class : null,
        desired_snapshot_id: safeSnapshotHash(state.desired_snapshot_id)
          ? state.desired_snapshot_id : null,
        active_snapshot_id: safeSnapshotHash(state.active_snapshot_id)
          ? state.active_snapshot_id : null,
        documents_completed: count(progressValue.documents_processed),
        documents_total: count(progressValue.total_units),
        documents_changed: count(progressValue.documents_changed),
        documents_materialized: count(progressValue.documents_materialized),
        batch_number: count(diagnosticValue.batch_number ?? progressValue.batch_number),
        batch_count: count(diagnosticValue.batch_total ?? progressValue.batch_total),
        ...(projector === 'SEMANTIC' ? {} : {
          neo4j_http_class: safeK9Token(diagnosticValue.neo4j_http_class)
            ? diagnosticValue.neo4j_http_class : null,
          neo4j_error_class: safeK9Token(diagnosticValue.neo4j_error_class)
            ? diagnosticValue.neo4j_error_class : null,
          query_family: safeK9Token(diagnosticValue.query_family)
            ? diagnosticValue.query_family : null,
          transaction_phase: safeK9Token(diagnosticValue.transaction_phase)
            ? diagnosticValue.transaction_phase : null,
          batch_requested_nodes: count(diagnosticValue.batch_requested_nodes),
          batch_requested_edges: count(diagnosticValue.batch_requested_edges),
          batch_written_nodes: count(diagnosticValue.batch_written_nodes),
          batch_written_edges: count(diagnosticValue.batch_written_edges),
          expected_snapshot_id_present: diagnosticValue.expected_snapshot_id_present === true,
          active_snapshot_id_present: diagnosticValue.active_snapshot_id_present === true,
          promotion_attempted: diagnosticValue.promotion_attempted === true,
          promotion_completed: diagnosticValue.promotion_completed === true,
        }),
      },
    }
  }
  return null
}

function k9V2RunningProjector(lifecycle) {
  if (lifecycle?.contract !== 'DATARIVER_K9_LIFECYCLE_STATUS_V2') return null
  const projector = k9V2Projectors.find((item) => lifecycle.projectors?.[item]?.status === 'RUNNING')
  if (!projector) return null
  const state = lifecycle.projectors[projector]
  const value = state.progress && typeof state.progress === 'object' ? state.progress : {}
  const count = (candidate) => Number.isSafeInteger(candidate) && candidate >= 0 ? candidate : 0
  return {
    contract: 'DATARIVER_PREP39083_K9_PROGRESS_V2',
    k9: 'RUNNING',
    stage: `${projector}_PROJECTOR`,
    detail: safeK9Token(value.phase) ? value.phase : `${projector}_RUNNING`,
    source_snapshot_id: safeSnapshotHash(state.desired_snapshot_id) ? state.desired_snapshot_id : null,
    completed: count(value.completed_units),
    total: count(value.total_units),
    documents_changed: count(value.documents_changed),
    documents_materialized: count(value.documents_materialized),
    batch_number: count(value.batch_number),
    batch_total: count(value.batch_total),
    observed_at: new Date().toISOString(),
  }
}

function k9V2Ready(lifecycle) {
  if (lifecycle?.contract !== 'DATARIVER_K9_LIFECYCLE_STATUS_V2'
    || lifecycle.aggregate?.status !== 'READY'
    || lifecycle.source?.status !== 'READY'
    || !safeSnapshotHash(lifecycle.source.desired_snapshot_id)
    || lifecycle.source.active_snapshot_id !== lifecycle.source.desired_snapshot_id) return false
  return k9V2Projectors.every((projector) => {
    const state = lifecycle.projectors?.[projector]
    return state?.status === 'READY'
      && state.desired_snapshot_id === lifecycle.source.desired_snapshot_id
      && state.active_snapshot_id === lifecycle.source.desired_snapshot_id
  })
}

function boundedK9V2LifecycleStatus(lifecycle) {
  if (lifecycle?.contract !== 'DATARIVER_K9_LIFECYCLE_STATUS_V2') return null
  const snapshot = (value) => safeSnapshotHash(value) ? value : null
  const projector = (value) => {
    const progressValue = value?.progress && typeof value.progress === 'object'
      ? value.progress : null
    const count = (candidate) => Number.isSafeInteger(candidate) && candidate >= 0 ? candidate : 0
    const diagnosticValue = value?.diagnostic && typeof value.diagnostic === 'object'
      ? value.diagnostic : null
    const diagnostic = diagnosticValue ? {
      code: safeK9Token(diagnosticValue.code) ? diagnosticValue.code : 'K9_V2_DIAGNOSTIC_INVALID',
      stage: safeK9Token(diagnosticValue.stage) ? diagnosticValue.stage : 'UNKNOWN',
      ...(Object.hasOwn(diagnosticValue, 'failure_detail_code') ? {
        failure_detail_code: safeK9Token(diagnosticValue.failure_detail_code)
          ? diagnosticValue.failure_detail_code : null,
      } : {}),
      ...(Object.hasOwn(diagnosticValue, 'provider_failure_class') ? {
        provider_failure_class: safeK9Token(diagnosticValue.provider_failure_class)
          ? diagnosticValue.provider_failure_class : null,
      } : {}),
      ...Object.fromEntries(['neo4j_http_class', 'neo4j_error_class', 'query_family', 'transaction_phase']
        .filter((field) => Object.hasOwn(diagnosticValue, field))
        .map((field) => [field, safeK9Token(diagnosticValue[field]) ? diagnosticValue[field] : null])),
      ...Object.fromEntries([
        'batch_number', 'batch_total', 'batch_requested_nodes', 'batch_requested_edges',
        'batch_written_nodes', 'batch_written_edges',
      ].filter((field) => Object.hasOwn(diagnosticValue, field))
        .map((field) => [field, count(diagnosticValue[field])])),
      ...Object.fromEntries([
        'expected_snapshot_id_present', 'active_snapshot_id_present',
        'promotion_attempted', 'promotion_completed',
      ].filter((field) => Object.hasOwn(diagnosticValue, field))
        .map((field) => [field, diagnosticValue[field] === true])),
    } : null
    return {
      desired_snapshot_id: snapshot(value?.desired_snapshot_id),
      active_snapshot_id: snapshot(value?.active_snapshot_id),
      status: ['NOT_STARTED', 'PENDING', 'RUNNING', 'READY', 'FAILED'].includes(value?.status)
        ? value.status : 'FAILED',
      progress: progressValue ? {
        phase: safeK9Token(progressValue.phase) ? progressValue.phase : 'UNKNOWN',
        completed_units: count(progressValue.completed_units),
        total_units: count(progressValue.total_units),
        documents_changed: count(progressValue.documents_changed),
        documents_materialized: count(progressValue.documents_materialized),
        batch_number: count(progressValue.batch_number),
        batch_total: count(progressValue.batch_total),
      } : null,
      diagnostic,
    }
  }
  return {
    contract: 'DATARIVER_K9_LIFECYCLE_STATUS_V2',
    source: {
      desired_snapshot_id: snapshot(lifecycle.source?.desired_snapshot_id),
      active_snapshot_id: snapshot(lifecycle.source?.active_snapshot_id),
      status: ['NOT_STARTED', 'PENDING', 'RUNNING', 'READY', 'FAILED'].includes(lifecycle.source?.status)
        ? lifecycle.source.status : 'FAILED',
      eligibility: boundedK9SourceEligibility(lifecycle.source?.eligibility),
    },
    projectors: Object.fromEntries(k9V2Projectors.map((item) => (
      [item, projector(lifecycle.projectors?.[item])]
    ))),
    aggregate: {
      status: ['NOT_READY', 'RUNNING', 'READY', 'FAILED'].includes(lifecycle.aggregate?.status)
        ? lifecycle.aggregate.status : 'FAILED',
      reason: safeK9Token(lifecycle.aggregate?.reason) ? lifecycle.aggregate.reason : null,
    },
  }
}

async function privateSecret(path) {
  const metadata = await lstat(path)
  if (!metadata.isFile() || metadata.isSymbolicLink() || (metadata.mode & 0o077) !== 0 || metadata.size > 1026) {
    throw smokeFailure(
      'INPUT',
      'PREP_SMOKE_INPUT_INVALID',
      'Password file must be a regular non-symlink file, mode 0600 or stricter, at most 1026 bytes.',
    )
  }
  const value = (await readFile(path, 'utf8')).trim()
  if (!value) throw smokeFailure('INPUT', 'PREP_SMOKE_INPUT_INVALID', 'Password file is empty.')
  return value
}

async function responseJson(url, init, stage, classification) {
  let response
  try {
    response = await fetch(url, { ...init, signal: AbortSignal.timeout(300_000) })
  } catch (error) {
    const requestClassification = stage === 'GENERAL_PROVIDER' && error?.name === 'TimeoutError'
      ? 'PREP_SMOKE_GENERAL_PROVIDER_TIMEOUT_FAILED'
      : classification
    throw smokeFailure(stage, requestClassification, `${stage} request failed.`)
  }
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    const inventoryClassification = stage === 'DATAHUB'
      && typeof body?.code === 'string'
      && inventoryFailureClassifications.has(body.code)
      ? body.code
      : classification
    const glossaryClassification = stage === 'DATAHUB_GLOSSARY_TERM'
      && typeof body?.code === 'string'
      && glossaryFailureClassifications.has(body.code)
      ? body.code
      : undefined
    const generalClassification = stage === 'GENERAL_PROVIDER'
      ? prepGeneralSmokeClassification(body?.code)
      : undefined
    const adminClassification = stage === 'ADMIN_LOGIN'
      ? adminLoginClassification(body, response.status)
      : undefined
    const failureClassification = adminClassification || generalClassification
      || glossaryClassification || inventoryClassification
    throw smokeFailure(
      stage,
      failureClassification,
      `${stage} request was rejected.`,
      response.status,
      failureClassification === body?.code ? body?.diagnostic : null,
    )
  }
  return { response, body }
}

function boundedMilliseconds(value, fallback, minimum, maximum, name) {
  const raw = value === null ? String(fallback) : String(value)
  if (!/^\d+$/.test(raw)) throw smokeFailure('INPUT', 'PREP_SMOKE_INPUT_INVALID', `${name} must be an integer.`)
  const parsed = Number(raw)
  if (!Number.isSafeInteger(parsed) || parsed < minimum || parsed > maximum) {
    throw smokeFailure('INPUT', 'PREP_SMOKE_INPUT_INVALID', `${name} must be between ${minimum} and ${maximum}.`)
  }
  return parsed
}

function progress(step, message) {
  process.stdout.write(`[SMOKE ${step}] ${message}\n`)
}

async function retryReadiness(operation, timeoutMs, label) {
  const started = Date.now()
  const deadline = started + timeoutMs
  let lastError
  do {
    try {
      return await operation()
    } catch (error) {
      lastError = error
      if (error?.terminal) throw error
      if (Date.now() >= deadline) break
      const diagnostic = error?.diagnostic
      if (diagnostic && Number.isSafeInteger(diagnostic.page_number) && diagnostic.page_number > 0) {
        const pageProgress = `inventory page ${diagnostic.page_number}`
        const countProgress = Number.isSafeInteger(diagnostic.expected_total)
          ? `; ${diagnostic.processed_count}/${diagnostic.expected_total} processed`
          : ''
        progress(label, `${pageProgress}${countProgress}`)
      } else if (diagnostic?.failure_stage === 'SOURCE_CAPTURE'
        && safeK9Token(diagnostic.failure_detail_code)
        && (diagnostic.candidate_total > 0 || diagnostic.total > 0)) {
        const candidate = Number.isSafeInteger(diagnostic.candidate_number)
          && diagnostic.candidate_total > 0
          ? `candidate ${diagnostic.candidate_number}/${diagnostic.candidate_total}; ` : ''
        const processed = Number.isSafeInteger(diagnostic.completed) && diagnostic.total > 0
          ? `${diagnostic.completed}/${diagnostic.total} processed; ` : ''
        progress(
          label,
          `K9 SOURCE_CAPTURE / ${diagnostic.failure_detail_code}; ${candidate}${processed}elapsed ${Math.round((Date.now() - started) / 1000)}s`,
        )
      } else {
        progress(label, `still pending (elapsed ${Math.round((Date.now() - started) / 1000)}s)`)
      }
      const remaining = deadline - Date.now()
      if (remaining > 0) {
        await new Promise((resolvePromise) => setTimeout(resolvePromise, Math.min(15_000, remaining)))
      }
    }
  } while (Date.now() < deadline)
  throw lastError
}

async function withHeartbeat(promise, label, intervalMs = 30_000) {
  const started = Date.now()
  const timer = setInterval(() => {
    progress(label, `still pending (elapsed ${Math.round((Date.now() - started) / 1000)}s)`)
  }, intervalMs)
  timer.unref()
  try {
    return await promise
  } finally {
    clearInterval(timer)
  }
}

async function atomicJson(path, value) {
  const temporary = `${path}.tmp-${process.pid}`
  try {
    await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600, flag: 'wx' })
    await rename(temporary, path)
    await chmod(path, 0o600)
  } finally {
    await removeIfPresent(temporary)
  }
}

async function removeIfPresent(path) {
  if (!path) return
  await unlink(path).catch((error) => {
    if (error?.code !== 'ENOENT') throw error
  })
}

const transportOrigin = argument('--origin', 'http://127.0.0.1:39083')
const requestOrigin = argument('--request-origin')
const username = argument('--username')
const passwordFile = argument('--password-file')
const output = argument('--output')
const failureOutput = argument('--failure-output')
const progressOutput = argument('--progress-output', '')
const smokeProductSha = argument('--smoke-product-sha', '')
const glossaryTermUrn = String(argument('--glossary-term-urn', '') || '').trim()
const k9Mode = String(argument('--k9-mode', 'required')).trim().toUpperCase()
const readinessTimeoutMs = boundedMilliseconds(
  argument('--readiness-timeout-ms'), 1_200_000, 1_000, 3_600_000, '--readiness-timeout-ms',
)

async function main() {
  const started = processStarted
  if (!requestOrigin || !username || !passwordFile || !output
    || !/^[0-9a-f]{40}$/.test(smokeProductSha)) {
    throw smokeFailure(
      'INPUT',
      'PREP_SMOKE_INPUT_INVALID',
      'Required: bounded request, credential, output and serving Product inputs',
    )
  }
  if (!['REQUIRED', 'DEFERRED'].includes(k9Mode)) {
    throw smokeFailure('INPUT', 'PREP_SMOKE_INPUT_INVALID', '--k9-mode must be required or deferred.')
  }
  // The input boundary intentionally rejects every ASCII control character.
  if (glossaryTermUrn && (!glossaryTermUrn.startsWith('urn:li:glossaryTerm:')
    || glossaryTermUrn === 'urn:li:glossaryTerm:' || glossaryTermUrn.length > 1000
    // eslint-disable-next-line no-control-regex
    || /[\u0000-\u001f\u007f]/u.test(glossaryTermUrn))) {
    throw smokeFailure(
      'INPUT',
      'PREP_SMOKE_INPUT_INVALID',
      '--glossary-term-urn must be one bounded canonical DataHub GlossaryTerm URN.',
    )
  }
  for (const [name, value] of [['--origin', transportOrigin], ['--request-origin', requestOrigin]]) {
    let parsed
    try {
      parsed = new URL(value)
    } catch {
      throw smokeFailure('INPUT', 'PREP_SMOKE_INPUT_INVALID', `${name} must be one exact HTTP(S) origin.`)
    }
    if (!['http:', 'https:'].includes(parsed.protocol)
      || parsed.username || parsed.password || parsed.pathname !== '/'
      || parsed.search || parsed.hash || parsed.origin !== value) {
      throw smokeFailure('INPUT', 'PREP_SMOKE_INPUT_INVALID', `${name} must be one exact HTTP(S) origin.`)
    }
  }

  let health
  try {
    health = await fetch(`${transportOrigin}/healthz`, { signal: AbortSignal.timeout(10_000) })
  } catch {
    throw smokeFailure('HEALTH', 'PREP_SMOKE_WEB_HEALTH_FAILED', 'Host web health request failed.')
  }
  if (!health.ok || (await health.text()).trim() !== 'ok') {
    throw smokeFailure('HEALTH', 'PREP_SMOKE_WEB_HEALTH_FAILED', 'Host web health is not canonical ok.', health.status)
  }
  progress('1/6', 'Host and Product health PASS')

  const password = await privateSecret(passwordFile)
  const login = await responseJson(`${transportOrigin}/auth/login`, {
    method: 'POST',
    headers: { Origin: requestOrigin, 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  }, 'ADMIN_LOGIN', 'PREP_SMOKE_ADMIN_AUTH_FAILED')
  const cookie = login.response.headers.get('set-cookie')?.split(';', 1)[0]
  if (!cookie) {
    throw smokeFailure(
      'ADMIN_LOGIN',
      'PREP_SMOKE_ADMIN_LOGIN_CONTRACT_FAILED',
      'Login returned no opaque session.',
    )
  }
  progress('2/6', 'Administrator login PASS')

  const report = {
    contract: 'DATARIVER_PREP39083_SMOKE_V2',
    smoke_product_sha: smokeProductSha,
    generated_at: new Date().toISOString(),
    origin: transportOrigin,
    request_origin: requestOrigin,
    health: 'PASS',
    login: 'PASS',
    k9_mode: k9Mode,
    datahub: 'FAIL',
    glossary_term: 'FAIL',
    glossary_term_urn: null,
    glossary_term_selection_source: null,
    glossary_term_entity_exists: false,
    glossary_term_exists: false,
    glossary_term_metadata_read: false,
    glossary_term_mutation_performed: false,
    managed_assets: k9Mode === 'REQUIRED' ? 'FAIL' : 'DEFERRED',
    default_lineage: k9Mode === 'REQUIRED' ? 'FAIL' : 'DEFERRED',
    metadata_master: k9Mode === 'REQUIRED' ? 'FAIL' : 'DEFERRED',
    semantic_index: k9Mode === 'REQUIRED' ? 'FAIL' : 'DEFERRED',
    k9_source_warning: null,
    k9_assignment_scope: null,
    k9_lifecycle: null,
    mcl_change_history: 'FAIL',
    mcl_current_capture: 'PENDING',
    mcl_history_completeness: 'UNKNOWN',
    mcl_history_gap_reason: null,
    mcl_history_gap_count: 0,
    mcl_exact_current_segment_count: 0,
    llm_general: 'FAIL',
    readiness: {
      DATAHUB: { status: 'PENDING', stage: null, classification: null },
      K9: {
        status: k9Mode === 'REQUIRED' ? 'PENDING' : 'DEFERRED',
        stage: null,
        classification: null,
      },
      MCL: { status: 'PENDING', stage: null, classification: null },
      GENERAL: { status: 'PENDING', stage: null, classification: null },
    },
  }
  try {
    await retryReadiness(async () => {
      const currentInventory = await withHeartbeat(responseJson(
        `${transportOrigin}/poc-api/datahub/tree?parent_kind=ROOT&limit=1`,
        { headers: { Cookie: cookie } },
        'DATAHUB',
        'PREP_SMOKE_DATAHUB_CONNECTIVITY_FAILED',
      ), '3/6 DataHub current inventory')
      if (!currentInventory.body || typeof currentInventory.body !== 'object') {
        throw smokeFailure('DATAHUB', 'PREP_DATAHUB_INVENTORY_CONTRACT_FAILED', 'Current DataHub inventory response is invalid.', null, {
          phase: 'RESPONSE_BUILD', terminal: true,
        })
      }
      const catalog = await responseJson(`${transportOrigin}/poc-api/datahub/catalog?limit=1`, {
        headers: { Cookie: cookie },
      }, 'DATAHUB', 'PREP_SMOKE_DATAHUB_CONNECTIVITY_FAILED')
      if (!catalog.body || typeof catalog.body !== 'object') {
        throw smokeFailure('DATAHUB', 'PREP_SMOKE_DATAHUB_CONNECTIVITY_FAILED', 'DataHub Catalog response is invalid.')
      }
      const glossaryParameters = new URLSearchParams()
      if (glossaryTermUrn) glossaryParameters.set('urn', glossaryTermUrn)
      const glossaryQuery = glossaryParameters.toString()
      const glossaryTarget = await responseJson(
        `${transportOrigin}/poc-api/datahub/glossary/smoke-target${glossaryQuery ? `?${glossaryQuery}` : ''}`,
        { headers: { Cookie: cookie } },
        'DATAHUB_GLOSSARY_TERM',
        'PREP_SMOKE_GLOSSARY_TERM_LOOKUP_FAILED',
      )
      const term = glossaryTarget.body
      if (term?.contract !== 'DATARIVER_PREP_GLOSSARY_TERM_SMOKE_TARGET_V1'
        || !['CONFIGURED', 'RUNTIME_DISCOVERED'].includes(term?.selection_source)
        || typeof term?.urn !== 'string' || !term.urn.startsWith('urn:li:glossaryTerm:')
        || term.entity_exists !== true || term.entity_type !== 'GLOSSARY_TERM'
        || term.glossary_term_exists !== true || term.basic_metadata_read !== true
        || term.mutation_performed !== false
        || (glossaryTermUrn && (term.urn !== glossaryTermUrn || term.selection_source !== 'CONFIGURED'))
        || (!glossaryTermUrn && term.selection_source !== 'RUNTIME_DISCOVERED')) {
        throw smokeFailure(
          'DATAHUB_GLOSSARY_TERM',
          'PREP_SMOKE_GLOSSARY_TERM_CONTRACT_FAILED',
          'GlossaryTerm smoke target response is invalid.',
          null,
          {
            terminal: true,
            substage: 'SMOKE_RESPONSE_VALIDATION',
            endpoint: 'PRODUCT_GLOSSARY_SMOKE_TARGET',
            operation: 'VALIDATE_GLOSSARY_TERM_READ',
            sanitized_reason: 'PRODUCT_RESPONSE_CONTRACT_INVALID',
            nested_error_code: 'CONTRACT',
          },
        )
      }
      report.glossary_term = 'PASS'
      report.glossary_term_urn = term.urn
      report.glossary_term_selection_source = term.selection_source
      report.glossary_term_entity_exists = true
      report.glossary_term_exists = true
      report.glossary_term_metadata_read = true
      report.glossary_term_mutation_performed = false
      report.datahub = 'PASS'
    }, readinessTimeoutMs, '3/6 DataHub')
    report.readiness.DATAHUB = { status: 'PASS', stage: null, classification: null }
    await atomicJson(output, report)
    progress('3/6', 'DataHub bounded read and read-only GlossaryTerm smoke PASS')

    const laneFailures = []
    try {
      if (k9Mode === 'REQUIRED') {
        await retryReadiness(async () => {
        const managed = await responseJson(`${transportOrigin}/poc-api/knowledge/managed-assets`, {
          headers: { Cookie: cookie },
        }, 'K9', 'PREP_SMOKE_K9_NOT_READY')
        const items = Array.isArray(managed.body?.items) ? managed.body.items : []
        const lineage = items.find((item) => item.graph_type === 'LINEAGE' && item.is_default)
        const metadata = items.find((item) => item.graph_type === 'METADATA_MASTER')
        const lifecycle = managed.body?.k9_lifecycle
        if (lifecycle?.contract === 'DATARIVER_K9_LIFECYCLE_STATUS_V2') {
          report.k9_lifecycle = boundedK9V2LifecycleStatus(lifecycle)
          const boundedAttempt = (attempt) => {
            if (!attempt || !['RUNNING', 'SUCCESS', 'FAILURE'].includes(attempt.status)) return null
            const count = (value) => Number.isSafeInteger(value) && value >= 0 ? value : 0
            const successorSourceSnapshotId = safeSnapshotHash(attempt.successor_source_snapshot_id)
              ? attempt.successor_source_snapshot_id : null
            const sourceCorrectionIdentity = safeSnapshotHash(attempt.execution_id)
              && safeSnapshotHash(attempt.expected_source_snapshot_id)
              && ((attempt.lifecycle_mode === 'SOURCE_CORRECTION_RECAPTURE'
                && successorSourceSnapshotId === null)
                || (attempt.lifecycle_mode === 'RESUME' && successorSourceSnapshotId !== null))
              ? {
                  lifecycle_mode: attempt.lifecycle_mode,
                  execution_id: attempt.execution_id,
                  expected_source_snapshot_id: attempt.expected_source_snapshot_id,
                  source_correction_phase: successorSourceSnapshotId
                    ? 'SUCCESSOR_BOUND' : 'CLAIMED',
                  ...(successorSourceSnapshotId
                    ? { successor_source_snapshot_id: successorSourceSnapshotId } : {}),
                }
              : null
            const persistence = attempt.reason === 'K9_V2_SOURCE_RECEIPT_PERSISTENCE_FAILED'
              ? sanitizeK9SourcePersistenceDiagnosticV2({
                  code: attempt.reason,
                  stage: attempt.failure_stage,
                  failure_detail_code: attempt.failure_detail_code,
                  persistence_substage: attempt.persistence_substage,
                  payload_kind: attempt.payload_kind,
                  payload_bytes: attempt.payload_bytes,
                  configured_limit_bytes: attempt.configured_limit_bytes,
                  sqlstate_class: attempt.sqlstate_class,
                  constraint_name: attempt.constraint_name,
                  retryable: attempt.retryable,
                }) || sanitizeK9SourcePersistenceDiagnosticV2({
                  code: 'K9_V2_SOURCE_RECEIPT_PERSISTENCE_FAILED',
                  stage: 'SOURCE_RECEIPT',
                  failure_detail_code: 'K9_SOURCE_PERSISTENCE_UNKNOWN',
                  persistence_substage: 'SOURCE_RECEIPT_VALIDATE',
                  payload_kind: 'NONE',
                  payload_bytes: 0,
                  configured_limit_bytes: 0,
                  sqlstate_class: 'NONE',
                  constraint_name: 'NONE',
                  retryable: true,
                })
              : null
            return {
              status: attempt.status,
              ...(sourceCorrectionIdentity || {}),
              ...(safeK9Token(attempt.stage) ? { stage: attempt.stage } : {}),
              ...(safeK9Token(attempt.detail) ? { detail: attempt.detail } : {}),
              ...(safeK9Token(attempt.reason) ? { reason: attempt.reason } : {}),
              ...(persistence
                ? { failure_stage: persistence.stage }
                : safeK9Token(attempt.failure_stage)
                  ? { failure_stage: attempt.failure_stage } : {}),
              ...(persistence
                ? { failure_detail_code: persistence.failure_detail_code }
                : safeK9Token(attempt.failure_detail_code)
                  ? { failure_detail_code: attempt.failure_detail_code } : {}),
              ...(persistence ? Object.fromEntries([
                'persistence_substage', 'payload_kind', 'sqlstate_class', 'constraint_name',
                'payload_bytes', 'configured_limit_bytes',
              ].map((field) => [field, persistence[field]])) : {}),
              completed: count(attempt.completed),
              total: count(attempt.total),
              candidate_number: count(attempt.candidate_number),
              candidate_total: count(attempt.candidate_total),
              batch_number: count(attempt.batch_number),
              batch_total: count(attempt.batch_total),
              ...(safeK9Timestamp(attempt.scheduled_for)
                ? { scheduled_for: attempt.scheduled_for } : {}),
              ...(safeK9Timestamp(attempt.started_at) ? { started_at: attempt.started_at } : {}),
              ...(safeK9Timestamp(attempt.observed_at) ? { observed_at: attempt.observed_at } : {}),
              ...(safeK9Timestamp(attempt.completed_at) ? { completed_at: attempt.completed_at } : {}),
            }
          }
          const currentAttempt = items
            .map((item) => item?.scheduler_current_attempt)
            .find((attempt) => attempt?.status === 'RUNNING')
          const lastCompletedAttempt = items
            .map((item) => item?.scheduler_last_completed_attempt || item?.scheduler_last_attempt)
            .find((attempt) => ['SUCCESS', 'FAILURE'].includes(attempt?.status))
          const historicalAssetError = [lineage, metadata]
            .map((item) => item?.last_error_code)
            .find((code) => safeK9Token(code)) || null
          const schedulerStatus = items
            .map((item) => item?.scheduler_status)
            .find((value) => ['RUNNING', 'SCHEDULED', 'ON_DEMAND', 'DISABLED'].includes(value))
          const boundedLastCompletedAttempt = boundedAttempt(lastCompletedAttempt)
          report.k9_scheduler = {
            status: currentAttempt ? 'RUNNING' : (schedulerStatus || 'UNKNOWN'),
            current_attempt: boundedAttempt(currentAttempt),
            last_completed_attempt: boundedLastCompletedAttempt,
          }
          report.k9_historical_asset_error = historicalAssetError
          const runningProjector = k9V2RunningProjector(lifecycle)
          if (runningProjector) {
            if (progressOutput) await atomicJson(progressOutput, runningProjector)
            progress(
              '4/6',
              `K9 ${runningProjector.stage} ${runningProjector.completed}/${runningProjector.total}; batch ${runningProjector.batch_number}/${runningProjector.batch_total}`,
            )
          }
          if (currentAttempt) {
            const count = (value) => Number.isSafeInteger(value) && value >= 0 ? value : 0
            if (currentAttempt.stage === 'SOURCE_CAPTURE' && safeK9Token(currentAttempt.detail)
              && (count(currentAttempt.candidate_total) > 0 || count(currentAttempt.total) > 0)) {
              const sourceProgress = {
                contract: 'DATARIVER_PREP39083_K9_PROGRESS_V2',
                k9: 'RUNNING',
                stage: 'SOURCE_CAPTURE',
                detail: currentAttempt.detail,
                completed: count(currentAttempt.completed),
                total: count(currentAttempt.total),
                candidate_number: count(currentAttempt.candidate_number),
                candidate_total: count(currentAttempt.candidate_total),
                batch_number: count(currentAttempt.batch_number),
                batch_total: count(currentAttempt.batch_total),
                observed_at: new Date().toISOString(),
              }
              if (progressOutput) await atomicJson(progressOutput, sourceProgress)
            }
            throw smokeFailure(
              'K9',
              'PREP_SMOKE_K9_NOT_READY',
              'The current K9 lifecycle attempt is still running.',
              null,
              {
                terminal: false,
                failure_stage: safeK9Token(currentAttempt.stage)
                  ? currentAttempt.stage : 'K9_LIFECYCLE',
                failure_detail_code: safeK9Token(currentAttempt.detail)
                  ? currentAttempt.detail : 'CURRENT_ATTEMPT_RUNNING',
                scheduled_for: safeK9Timestamp(currentAttempt.scheduled_for)
                  ? currentAttempt.scheduled_for : null,
                attempt_started_at: safeK9Timestamp(currentAttempt.started_at)
                  ? currentAttempt.started_at : null,
                attempt_observed_at: safeK9Timestamp(currentAttempt.observed_at)
                  ? currentAttempt.observed_at : null,
                trigger: ['scheduled', 'manual'].includes(currentAttempt.trigger)
                  ? currentAttempt.trigger : null,
                source_receipt_present: lifecycle.source?.status !== 'NOT_STARTED',
                completed: count(currentAttempt.completed),
                total: count(currentAttempt.total),
                candidate_number: count(currentAttempt.candidate_number),
                candidate_total: count(currentAttempt.candidate_total),
                batch_number: count(currentAttempt.batch_number),
                batch_total: count(currentAttempt.batch_total),
              },
            )
          }
          if (runningProjector) {
            throw smokeFailure(
              'K9',
              'PREP_SMOKE_K9_NOT_READY',
              'The persisted K9 V2 projector lifecycle is still running.',
              null,
              {
                terminal: false,
                failure_stage: runningProjector.stage,
                failure_detail_code: runningProjector.detail,
                source_receipt_present: lifecycle.source?.status !== 'NOT_STARTED',
                completed: runningProjector.completed,
                total: runningProjector.total,
                batch_number: runningProjector.batch_number,
                batch_total: runningProjector.batch_total,
              },
            )
          }
          if (progressOutput && !runningProjector) await removeIfPresent(progressOutput)
          const sourceCorrectionSuccessorExists = safeSnapshotHash(
            lifecycle.source?.desired_snapshot_id,
          ) && lifecycle.source.desired_snapshot_id
            !== boundedLastCompletedAttempt?.expected_source_snapshot_id
          const completedSourceCorrectionFailure = boundedLastCompletedAttempt?.status === 'FAILURE'
            && boundedLastCompletedAttempt.lifecycle_mode === 'SOURCE_CORRECTION_RECAPTURE'
            && safeSnapshotHash(boundedLastCompletedAttempt.execution_id)
            && safeSnapshotHash(boundedLastCompletedAttempt.expected_source_snapshot_id)
            && safeK9Token(boundedLastCompletedAttempt.reason)
            && !sourceCorrectionSuccessorExists
            ? boundedLastCompletedAttempt : null
          if (completedSourceCorrectionFailure) {
            const persistenceDiagnostic = completedSourceCorrectionFailure.reason
              === 'K9_V2_SOURCE_RECEIPT_PERSISTENCE_FAILED'
              ? sanitizeK9SourcePersistenceDiagnosticV2({
                  code: completedSourceCorrectionFailure.reason,
                  stage: completedSourceCorrectionFailure.failure_stage,
                  failure_detail_code: completedSourceCorrectionFailure.failure_detail_code,
                  persistence_substage: completedSourceCorrectionFailure.persistence_substage,
                  payload_kind: completedSourceCorrectionFailure.payload_kind,
                  payload_bytes: completedSourceCorrectionFailure.payload_bytes,
                  configured_limit_bytes: completedSourceCorrectionFailure.configured_limit_bytes,
                  sqlstate_class: completedSourceCorrectionFailure.sqlstate_class,
                  constraint_name: completedSourceCorrectionFailure.constraint_name,
                  retryable: completedSourceCorrectionFailure.retryable,
                })
              : null
            throw smokeFailure(
              'K9_INITIAL_REFRESH',
              completedSourceCorrectionFailure.reason === 'K9_DATAHUB_SOURCE_FAILED'
                ? 'PREP_SMOKE_K9_DATAHUB_SOURCE_FAILED'
                : 'PREP_SMOKE_K9_REFRESH_FAILED',
              'The explicit K9 source-correction attempt failed before successor readiness.',
              null,
              {
                terminal: true,
                product_error_code: completedSourceCorrectionFailure.reason,
                failure_stage: persistenceDiagnostic?.stage
                  || completedSourceCorrectionFailure.failure_stage || 'SOURCE_CAPTURE',
                failure_detail_code: persistenceDiagnostic?.failure_detail_code
                  || completedSourceCorrectionFailure.failure_detail_code
                  || completedSourceCorrectionFailure.reason,
                scheduled_for: completedSourceCorrectionFailure.scheduled_for || null,
                attempt_observed_at: completedSourceCorrectionFailure.completed_at || null,
                source_receipt_present: lifecycle.source?.status !== 'NOT_STARTED',
                ...(persistenceDiagnostic ? Object.fromEntries([
                  'persistence_substage', 'payload_kind', 'payload_bytes',
                  'configured_limit_bytes', 'sqlstate_class', 'constraint_name',
                ].map((field) => [field, persistenceDiagnostic[field]])) : {}),
              },
            )
          }
          const projectorFailure = k9V2ProjectorFailure(lifecycle)
          if (projectorFailure) {
            throw smokeFailure(
              'K9_INITIAL_REFRESH',
              projectorFailure.classification,
              'A persisted K9 V2 projector failed.',
              null,
              projectorFailure.diagnostic,
            )
          }
          const sourceCaptureFailure = items
            .map((item) => item?.scheduler_last_completed_attempt
              || item?.scheduler_last_attempt)
            .find((attempt) => attempt?.status === 'FAILURE'
              && attempt?.reason === 'K9_DATAHUB_SOURCE_FAILED'
              && safeK9Token(attempt?.failure_stage)
              && safeK9Token(attempt?.failure_detail_code))
          if (lifecycle.source?.status === 'NOT_STARTED' && sourceCaptureFailure) {
            throw smokeFailure(
              'K9_INITIAL_REFRESH',
              'PREP_SMOKE_K9_DATAHUB_SOURCE_FAILED',
              'K9 source capture failed before an immutable source snapshot was persisted.',
              null,
              {
                terminal: true,
                product_error_code: 'K9_DATAHUB_SOURCE_FAILED',
                failure_stage: sourceCaptureFailure.failure_stage,
                failure_detail_code: sourceCaptureFailure.failure_detail_code,
                scheduled_for: safeK9Timestamp(sourceCaptureFailure.scheduled_for)
                  ? sourceCaptureFailure.scheduled_for : null,
                attempt_observed_at: safeK9Timestamp(sourceCaptureFailure.completed_at)
                  ? sourceCaptureFailure.completed_at : null,
                trigger: ['scheduled', 'manual'].includes(sourceCaptureFailure.trigger)
                  ? sourceCaptureFailure.trigger : null,
                source_receipt_present: false,
                ...(boundedK9SourceEligibility(sourceCaptureFailure.source_eligibility)
                  ? { source_eligibility: boundedK9SourceEligibility(sourceCaptureFailure.source_eligibility) }
                  : {}),
                ...(sanitizeK9LineageSourceProfile(sourceCaptureFailure.lineage_source_profile)
                  ? { lineage_profile: sanitizeK9LineageSourceProfile(sourceCaptureFailure.lineage_source_profile) }
                  : {}),
              },
            )
          }
          const completedV2Failure = boundedLastCompletedAttempt?.status === 'FAILURE'
            && k9V2FailureCodes.has(boundedLastCompletedAttempt.reason)
            && safeK9Token(boundedLastCompletedAttempt.failure_stage)
            && safeK9Token(boundedLastCompletedAttempt.failure_detail_code)
            ? boundedLastCompletedAttempt : null
          if (completedV2Failure) {
            const persistenceDiagnostic = completedV2Failure.reason
              === 'K9_V2_SOURCE_RECEIPT_PERSISTENCE_FAILED'
              ? sanitizeK9SourcePersistenceDiagnosticV2({
                  code: completedV2Failure.reason,
                  stage: completedV2Failure.failure_stage,
                  failure_detail_code: completedV2Failure.failure_detail_code,
                  persistence_substage: completedV2Failure.persistence_substage,
                  payload_kind: completedV2Failure.payload_kind,
                  payload_bytes: completedV2Failure.payload_bytes,
                  configured_limit_bytes: completedV2Failure.configured_limit_bytes,
                  sqlstate_class: completedV2Failure.sqlstate_class,
                  constraint_name: completedV2Failure.constraint_name,
                  retryable: completedV2Failure.retryable,
                })
              : null
            throw smokeFailure(
              'K9_INITIAL_REFRESH',
              'PREP_SMOKE_K9_REFRESH_FAILED',
              'The current completed K9 V2 attempt failed with a bounded diagnostic.',
              null,
              {
                terminal: true,
                product_error_code: completedV2Failure.reason,
                failure_stage: completedV2Failure.failure_stage,
                failure_detail_code: completedV2Failure.failure_detail_code,
                scheduled_for: safeK9Timestamp(completedV2Failure.scheduled_for)
                  ? completedV2Failure.scheduled_for : null,
                attempt_observed_at: safeK9Timestamp(completedV2Failure.completed_at)
                  ? completedV2Failure.completed_at : null,
                source_receipt_present: lifecycle.source?.status !== 'NOT_STARTED',
                ...(persistenceDiagnostic ? Object.fromEntries([
                  'persistence_substage', 'payload_kind', 'payload_bytes',
                  'configured_limit_bytes', 'sqlstate_class', 'constraint_name',
                ].map((field) => [field, persistenceDiagnostic[field]])) : {}),
              },
            )
          }
          if (lifecycle.aggregate?.status === 'FAILED') {
            const reason = safeK9Token(lifecycle.aggregate?.reason)
              ? lifecycle.aggregate.reason : 'K9_V2_LIFECYCLE_FAILED'
            throw smokeFailure(
              'K9_INITIAL_REFRESH',
              'PREP_SMOKE_K9_REFRESH_FAILED',
              'The persisted K9 V2 lifecycle failed before aggregate readiness.',
              null,
              {
                terminal: true,
                product_error_code: reason,
                failure_stage: 'K9_V2_LIFECYCLE',
                failure_detail_code: reason,
              },
            )
          }
          if (!k9V2Ready(lifecycle)) {
            throw smokeFailure(
              'K9',
              'PREP_SMOKE_K9_NOT_READY',
              'The persisted K9 V2 lifecycle is not aggregate READY.',
              null,
              {
                terminal: false,
                failure_stage: 'AGGREGATE_READINESS',
                failure_detail_code: safeK9Token(lifecycle.aggregate?.reason)
                  ? lifecycle.aggregate.reason : 'K9_V2_AGGREGATE_NOT_READY',
              },
            )
          }
        } else {
          const refreshFailureAsset = [lineage, metadata]
            .find((item) => typeof item?.last_error_code === 'string' && item.last_error_code.startsWith('K9_'))
          const runningAttempt = [lineage, metadata]
            .map((item) => item?.refresh_attempt)
            .find((attempt) => attempt?.status === 'RUNNING'
              && attempt?.stage === 'METADATA_COLLECTION'
              && attempt?.detail === 'DIRECT_GLOSSARY_RESOLUTION')
          if (runningAttempt) {
            const progressRecord = {
              contract: 'DATARIVER_PREP39083_K9_PROGRESS_V1',
              k9: 'RUNNING',
              stage: 'METADATA_COLLECTION',
              detail: 'DIRECT_GLOSSARY_RESOLUTION',
              completed: Number.isSafeInteger(runningAttempt.completed_resolution_count)
                ? runningAttempt.completed_resolution_count : 0,
              total: Number.isSafeInteger(runningAttempt.direct_resolution_total)
                ? runningAttempt.direct_resolution_total : 0,
              batch_number: Number.isSafeInteger(runningAttempt.batch_number)
                ? runningAttempt.batch_number : 0,
              batch_total: Number.isSafeInteger(runningAttempt.batch_total)
                ? runningAttempt.batch_total : 0,
              batch_elapsed_ms: Number.isSafeInteger(runningAttempt.batch_elapsed_ms)
                ? runningAttempt.batch_elapsed_ms : 0,
              dangling_unique_terms: Number.isSafeInteger(runningAttempt.dangling_unique_terms)
                ? runningAttempt.dangling_unique_terms : 0,
              dangling_assignment_references: Number.isSafeInteger(runningAttempt.dangling_assignment_references)
                ? runningAttempt.dangling_assignment_references : 0,
              observed_at: new Date().toISOString(),
            }
            if (progressOutput) await atomicJson(progressOutput, progressRecord)
            progress('4/6', `K9 metadata direct resolution ${progressRecord.completed}/${progressRecord.total}; batch ${progressRecord.batch_number}/${progressRecord.batch_total}`)
          }
          const refreshFailure = refreshFailureAsset?.last_error_code
          const refreshClassifications = {
            K9_DATAHUB_SOURCE_FAILED: 'PREP_SMOKE_K9_DATAHUB_SOURCE_FAILED',
            K9_POLICY_PIN_DRIFT_FAILED: 'PREP_SMOKE_K9_POLICY_PIN_DRIFT_FAILED',
            K9_NEO4J_PROJECTION_FAILED: 'PREP_SMOKE_K9_NEO4J_PROJECTION_FAILED',
            K9_PROMOTION_FAILED: 'PREP_SMOKE_K9_PROMOTION_FAILED',
            K9_SEMANTIC_INDEX_FAILED: 'PREP_SMOKE_SEMANTIC_INDEX_NOT_READY',
            K9_SOURCE_DRIFT_RETRY_EXHAUSTED: 'PREP_SMOKE_K9_SOURCE_DRIFT_RETRY_EXHAUSTED',
          }
          if (refreshFailure) {
            throw smokeFailure(
              'K9_INITIAL_REFRESH',
              refreshClassifications[refreshFailure] || 'PREP_SMOKE_K9_REFRESH_FAILED',
              'The initial managed-graph refresh failed at a classified stage.',
              null,
              {
                terminal: true,
                product_error_code: refreshFailure,
                ...(k9SourceFailureDiagnostic(refreshFailureAsset) || {}),
              },
            )
          }
        }
        if (!lineage || !metadata || !String(lineage.status).startsWith('READY')
          || !String(metadata.status).startsWith('READY')
          || lineage.refresh_mode !== 'DAILY' || metadata.refresh_mode !== 'DAILY') {
          throw smokeFailure('K9', 'PREP_SMOKE_K9_NOT_READY', 'Canonical managed graphs are not DAILY and READY.')
        }
        if (lifecycle?.contract !== 'DATARIVER_K9_LIFECYCLE_STATUS_V2'
          && (lineage.semantic_index_status !== 'READY' || metadata.semantic_index_status !== 'READY')) {
          throw smokeFailure('K9', 'PREP_SMOKE_SEMANTIC_INDEX_NOT_READY', 'The shared semantic index is not READY.')
        }
        report.managed_assets = 'PASS'
        report.default_lineage = 'PASS'
        report.metadata_master = 'PASS'
        report.semantic_index = 'PASS'
        report.k9_source_warning = k9SourceWarning(metadata)
        report.k9_assignment_scope = k9AssignmentScope(metadata)
        if (progressOutput) await removeIfPresent(progressOutput)
        }, readinessTimeoutMs, '4/6 K9')
        report.readiness.K9 = { status: 'PASS', stage: null, classification: null }
        progress('4/6', 'Managed graphs and semantic index PASS')
      } else {
        progress('4/6', 'K9 DEFERRED')
      }
    } catch (error) {
      if (progressOutput && error?.terminal) await removeIfPresent(progressOutput)
      laneFailures.push(error)
      report.readiness.K9 = {
        status: 'FAILED',
        stage: safeK9Token(error?.stage) ? error.stage : 'K9',
        classification: safeK9Token(error?.classification)
          ? error.classification : 'PREP_SMOKE_K9_REFRESH_FAILED',
      }
      progress('4/6', `${report.readiness.K9.classification}; continuing read-only diagnostics`)
    }
    await atomicJson(output, report)

    const week = new Date()
    const day = (week.getUTCDay() + 6) % 7
    week.setUTCDate(week.getUTCDate() - day)
    const weekStart = week.toISOString().slice(0, 10)
    try {
      let mclHistoryCompleteness = 'UNKNOWN'
      await retryReadiness(async () => {
        const changeHistory = await responseJson(
        `${transportOrigin}/api/v1/change-history/summary?week_start=${weekStart}`,
        { headers: { Cookie: cookie } },
        'MCL_CHANGE_HISTORY',
        'PREP_SMOKE_MCL_SOURCE_FAILED',
      )
      if (changeHistory.body?.capture_state === 'DISCOVERY_FAILED') {
        throw smokeFailure(
          'MCL_INITIAL_CAPTURE',
          'PREP_SMOKE_MCL_RUNTIME_DISCOVERY_FAILED',
          'MCL runtime discovery failed after read-only provider preflight.',
          null,
          mclFailureDiagnostic(changeHistory.body),
        )
      }
      if (changeHistory.body?.capture_state === 'CAPTURE_FAILED') {
        const historyGap = changeHistory.body?.capture_failure_classification
          === 'PREP_MCL_CAPTURE_HISTORY_GAP_BLOCKED'
        throw smokeFailure(
          'MCL_INITIAL_CAPTURE',
          historyGap
            ? 'PREP_SMOKE_MCL_HISTORY_GAP_BLOCKED'
            : 'PREP_SMOKE_MCL_RUNTIME_CAPTURE_FAILED',
          'MCL runtime capture failed after read-only provider preflight.',
          null,
          mclFailureDiagnostic(changeHistory.body),
        )
      }
      if (changeHistory.body?.capture_state !== 'CAPTURE_CAUGHT_UP') {
        throw smokeFailure(
          'MCL_CHANGE_HISTORY',
          'PREP_SMOKE_MCL_CURRENT_CAPTURE_NOT_READY',
          'MCL current retained capture has not reached its observed high watermark.',
        )
      }
      const historyCompleteness = changeHistory.body?.history_completeness
      const gapCount = changeHistory.body?.history_gap_count
      const exactSegments = changeHistory.body?.exact_current_segments
      if (!['EXACT', 'DEGRADED_GAP'].includes(historyCompleteness)
        || !Number.isSafeInteger(gapCount) || gapCount < 0
        || !Array.isArray(exactSegments) || exactSegments.length > 1_000
        || (historyCompleteness === 'DEGRADED_GAP'
          && (changeHistory.body?.history_gap_reason !== 'RETENTION_EXPIRED'
            || gapCount < 1 || exactSegments.length < 1))
        || (historyCompleteness === 'EXACT'
          && (changeHistory.body?.history_gap_reason !== null || gapCount !== 0))) {
        throw smokeFailure(
          'MCL_CHANGE_HISTORY',
          'PREP_SMOKE_MCL_SOURCE_FAILED',
          'MCL current capture and historical-completeness contracts conflict.',
        )
      }
      mclHistoryCompleteness = historyCompleteness
      report.mcl_current_capture = 'READY'
      report.mcl_history_completeness = historyCompleteness
      report.mcl_history_gap_reason = changeHistory.body.history_gap_reason
      report.mcl_history_gap_count = gapCount
      report.mcl_exact_current_segment_count = exactSegments.length
      report.mcl_change_history = historyCompleteness
      }, readinessTimeoutMs, '5/6 MCL')
      report.readiness.MCL = {
        status: mclHistoryCompleteness === 'DEGRADED_GAP' ? 'DEGRADED_GAP' : 'PASS',
        stage: null,
        classification: null,
      }
      progress('5/6', mclHistoryCompleteness === 'DEGRADED_GAP'
        ? 'MCL current capture READY; history DEGRADED_GAP (RETENTION_EXPIRED)'
        : 'MCL current capture READY; history EXACT')
    } catch (error) {
      laneFailures.push(error)
      report.readiness.MCL = {
        status: 'FAILED',
        stage: safeK9Token(error?.stage) ? error.stage : 'MCL',
        classification: safeK9Token(error?.classification)
          ? error.classification : 'PREP_SMOKE_MCL_SOURCE_FAILED',
      }
      progress('5/6', `${report.readiness.MCL.classification}; continuing read-only diagnostics`)
    }
    await atomicJson(output, report)

    try {
      const chat = await withHeartbeat(responseJson(`${transportOrigin}/poc-api/llm/chat`, {
        method: 'POST',
        headers: { Cookie: cookie, Origin: requestOrigin, 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: '데이터 계보가 무엇인지 일반적으로 설명해줘.', mode: 'AUTO' }),
      }, 'GENERAL_PROVIDER', 'PREP_SMOKE_GENERAL_PROVIDER_FAILED'), '6/6 GENERAL provider')
      if (chat.body?.route?.selected_mode !== 'GENERAL' || (chat.body?.evidence || []).length !== 0) {
        throw smokeFailure('GENERAL_ROUTE', 'PREP_SMOKE_GENERAL_ROUTE_FAILED', 'Representative GENERAL route used internal retrieval or selected another route.')
      }
      report.llm_general = 'PASS'
      report.readiness.GENERAL = { status: 'PASS', stage: null, classification: null }
      progress('6/6', 'GENERAL provider and route PASS')
    } catch (error) {
      laneFailures.push(error)
      report.readiness.GENERAL = {
        status: 'FAILED',
        stage: safeK9Token(error?.stage) ? error.stage : 'GENERAL',
        classification: safeK9Token(error?.classification)
          ? error.classification : 'PREP_SMOKE_GENERAL_PROVIDER_FAILED',
      }
      progress('6/6', report.readiness.GENERAL.classification)
    }
    await atomicJson(output, report)
    if (laneFailures.length) {
      const primary = laneFailures[0]
      primary.readiness = report.readiness
      throw primary
    }
  } finally {
    await fetch(`${transportOrigin}/auth/logout`, {
      method: 'POST',
      headers: { Cookie: cookie, Origin: requestOrigin, 'Content-Type': 'application/json' },
      body: '{}',
      signal: AbortSignal.timeout(10_000),
    }).catch(() => undefined)
  }

  await atomicJson(output, report)
  await removeIfPresent(failureOutput)
  process.stdout.write(`${JSON.stringify(report)}\n`)
  process.stdout.write(`[SMOKE PASS] completed in ${Math.round((Date.now() - started) / 1000)}s\n`)
}

main().catch(async (error) => {
  const failure = {
    contract: 'DATARIVER_PREP39083_SMOKE_FAILURE_V2',
    smoke_product_sha: /^[0-9a-f]{40}$/.test(smokeProductSha) ? smokeProductSha : null,
    stage: error?.stage || 'UNKNOWN',
    classification: error?.classification || 'PREP_SMOKE_UNKNOWN_FAILED',
    status_class: Number.isInteger(error?.status) ? `${Math.floor(error.status / 100)}xx` : null,
    elapsed_ms: Date.now() - processStarted,
    k9_mode: k9Mode,
    failed_at: new Date().toISOString(),
    ...(error?.diagnostic ? { diagnostic: error.diagnostic } : {}),
    ...(error?.readiness ? { readiness: error.readiness } : {}),
  }
  if (failureOutput) await atomicJson(failureOutput, failure).catch(() => undefined)
  process.stderr.write(`${JSON.stringify(failure)}\n`)
  process.exitCode = 2
})
