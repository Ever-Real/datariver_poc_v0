import { createK9V2LifecycleOrchestrator } from './poc-k9-lifecycle-v2.mjs'

const HASH = /^[0-9a-f]{64}$/u
const TOKEN = /^[A-Z][A-Z0-9_]{0,95}$/u

const aggregateFailure = Object.freeze({
  code: 'K9_V2_AGGREGATE_PROMOTION_FAILED',
  stage: 'AGGREGATE_READINESS',
  retryable: true,
})

function boundedDiagnostic(value, fallback = aggregateFailure) {
  if (!value || !TOKEN.test(value.code || '') || !TOKEN.test(value.stage || '')) return fallback
  return Object.freeze({
    code: value.code,
    stage: value.stage,
    retryable: value.retryable === true,
  })
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
  return async function triggerK9V2Refresh() {
    const result = await orchestrator.run()
    if (result.status !== 'READY') {
      const diagnostic = boundedDiagnostic(result.diagnostic, Object.freeze({
        code: 'K9_V2_LIFECYCLE_FAILED', stage: 'K9_V2_LIFECYCLE', retryable: true,
      }))
      return Object.freeze({
        status: 'FAILURE',
        reason: diagnostic.code,
        failureCode: diagnostic.code,
        failureStage: diagnostic.stage,
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
