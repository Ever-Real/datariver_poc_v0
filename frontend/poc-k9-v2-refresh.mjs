import {
  createK9V2LifecycleOrchestrator,
  K9_V2_FAILURE_DIAGNOSTICS,
} from './poc-k9-lifecycle-v2.mjs'
import { sanitizeK9SourcePersistenceDiagnosticV2 } from './poc-k9-lifecycle-persistence.mjs'
import { sanitizeK9SourceEligibilityTelemetry } from './poc-k9-source-eligibility.mjs'
import { sanitizeK9LineageSourceProfile } from './poc-k9-lineage-collection.mjs'

const HASH = /^[0-9a-f]{64}$/u
const TOKEN = /^[A-Z][A-Z0-9_]{0,95}$/u

const aggregateFailure = K9_V2_FAILURE_DIAGNOSTICS.AGGREGATE_PROMOTION_FAILED

function boundedDiagnostic(value, fallback = aggregateFailure) {
  if (!value || !TOKEN.test(value.code || '') || !TOKEN.test(value.stage || '')) return fallback
  if (value.code === 'K9_V2_SOURCE_RECEIPT_PERSISTENCE_FAILED') {
    return sanitizeK9SourcePersistenceDiagnosticV2(value) || fallback
  }
  const bounded = {
    code: value.code,
    stage: value.stage,
    retryable: value.retryable === true,
    ...(TOKEN.test(value.failure_detail_code || '')
      ? { failure_detail_code: value.failure_detail_code }
      : {}),
  }
  for (const field of ['projector_id', 'query_family', 'transaction_phase']) {
    if (TOKEN.test(value[field] || '')) bounded[field] = value[field]
  }
  for (const field of ['provider_failure_class', 'neo4j_http_class', 'neo4j_error_class']) {
    if (Object.hasOwn(value, field)) bounded[field] = TOKEN.test(value[field] || '') ? value[field] : null
  }
  for (const field of [
    'batch_number', 'batch_total', 'batch_requested_nodes', 'batch_requested_edges',
    'batch_written_nodes', 'batch_written_edges', 'payload_bytes', 'configured_limit_bytes',
  ]) {
    if (Object.hasOwn(value, field)) {
      bounded[field] = Number.isSafeInteger(value[field]) && value[field] >= 0 ? value[field] : 0
    }
  }
  for (const field of [
    'expected_snapshot_id_present', 'active_snapshot_id_present',
    'promotion_attempted', 'promotion_completed',
  ]) {
    if (Object.hasOwn(value, field)) bounded[field] = value[field] === true
  }
  const sourceEligibility = sanitizeK9SourceEligibilityTelemetry(value.source_eligibility)
  if (sourceEligibility) bounded.source_eligibility = sourceEligibility
  const lineageProfile = sanitizeK9LineageSourceProfile(value.lineage_source_profile)
  if (lineageProfile) bounded.lineage_source_profile = lineageProfile
  return Object.freeze(bounded)
}

/**
 * Production-shaped K9 V2 trigger. The core owns source/projector selection, while this boundary
 * owns the single aggregate promotion after all exact snapshot receipts are READY. Scheduler
 * callers retain the existing SUCCESS/FAILURE envelope during additive adoption.
 */
export function createPocK9V2RefreshTask({
  captureSource,
  receipts,
  projectors,
  onTransition,
} = {}) {
  if (typeof receipts?.promoteAggregate !== 'function') {
    throw new TypeError('The K9 V2 aggregate promotion port is unavailable.')
  }
  const orchestrator = createK9V2LifecycleOrchestrator({
    captureSource,
    receipts,
    projectors,
    onTransition,
  })
  return async function triggerK9V2Refresh({
    lifecycleMode = 'REFRESH',
    expectedSourceSnapshotId = null,
  } = {}) {
    const result = await orchestrator.run({
      sourceRunMode: lifecycleMode,
      expectedSourceSnapshotId,
    })
    if (result.status !== 'READY') {
      const diagnostic = boundedDiagnostic(
        result.diagnostic,
        K9_V2_FAILURE_DIAGNOSTICS.LIFECYCLE_FAILED,
      )
      return Object.freeze({
        status: 'FAILURE',
        reason: diagnostic.code,
        failureCode: diagnostic.code,
        failureStage: diagnostic.stage,
        failureDetailCode: diagnostic.failure_detail_code || diagnostic.code,
        ...(diagnostic.code === 'K9_DATAHUB_SOURCE_FAILED' && diagnostic.source_eligibility
          ? { sourceEligibility: diagnostic.source_eligibility }
          : {}),
        ...(diagnostic.code === 'K9_DATAHUB_SOURCE_FAILED' && diagnostic.lineage_source_profile
          ? { lineageProfile: diagnostic.lineage_source_profile }
          : {}),
        diagnostic,
        source_snapshot_id: result.source_snapshot_id,
        ...(result.failed_projector ? { failedProjector: result.failed_projector } : {}),
        lifecycle: result,
      })
    }
    if (!HASH.test(result.source_snapshot_id || '')) {
      return Object.freeze({
        status: 'FAILURE',
        reason: aggregateFailure.code,
        failureCode: aggregateFailure.code,
        failureStage: aggregateFailure.stage,
        diagnostic: aggregateFailure,
        source_snapshot_id: null,
        lifecycle: result,
      })
    }
    try {
      await receipts.promoteAggregate(result.source_snapshot_id)
    } catch {
      return Object.freeze({
        status: 'FAILURE',
        reason: aggregateFailure.code,
        failureCode: aggregateFailure.code,
        failureStage: aggregateFailure.stage,
        diagnostic: aggregateFailure,
        source_snapshot_id: result.source_snapshot_id,
        lifecycle: result,
      })
    }
    return Object.freeze({
      status: 'SUCCESS',
      source_snapshot_id: result.source_snapshot_id,
      source_snapshot: result.source_snapshot_id,
      lifecycle: result,
    })
  }
}
