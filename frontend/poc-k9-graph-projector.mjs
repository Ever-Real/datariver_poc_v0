/* global structuredClone */
import { randomUUID } from 'node:crypto'

import { computeSha256 } from './poc-knowledge-k9-contracts.mjs'
import {
  K9_PROJECTOR_RECEIPT_CONTRACT_V2,
  normalizeK9ProjectorReceiptV2,
  normalizeK9SourcePayloadsV2,
  normalizeK9SourceSnapshotV2,
} from './poc-k9-lifecycle-persistence.mjs'

export const K9_GRAPH_PROJECTOR_IDS = Object.freeze(['LINEAGE', 'METADATA'])

const hashPattern = /^[0-9a-f]{64}$/u
const safeTokenPattern = /^[A-Z][A-Z0-9_]{0,79}$/u
const graphDiagnosticCountFields = Object.freeze([
  'batch_number', 'batch_total', 'batch_requested_nodes', 'batch_requested_edges',
  'batch_written_nodes', 'batch_written_edges',
])
const graphDiagnosticBooleanFields = Object.freeze([
  'expected_snapshot_id_present', 'active_snapshot_id_present',
  'promotion_attempted', 'promotion_completed',
])

const graphDiagnostics = Object.freeze({
  INPUT: Object.freeze({
    code: 'K9_GRAPH_SOURCE_CONTRACT_FAILED', stage: 'SOURCE_PAYLOAD', retryable: false,
    message: 'The persisted graph source payload does not match its immutable snapshot.',
  }),
  PERSISTENCE: Object.freeze({
    code: 'K9_GRAPH_RECEIPT_PERSISTENCE_FAILED', stage: 'RECEIPT', retryable: true,
    message: 'The graph projector receipt could not be persisted.',
  }),
  PROJECTION: Object.freeze({
    code: 'K9_GRAPH_PROJECTION_FAILED', stage: 'GRAPH_PROJECTION', retryable: true,
    message: 'The graph candidate could not be materialized and verified.',
  }),
  PROMOTION: Object.freeze({
    code: 'K9_GRAPH_PROMOTION_FAILED', stage: 'ACTIVE_POINTER', retryable: true,
    message: 'The graph candidate could not advance the active pointer.',
  }),
})

export class K9GraphProjectorError extends Error {
  constructor(diagnostic, projectorId) {
    const known = Object.values(graphDiagnostics).find((item) => item.code === diagnostic.code)
      || graphDiagnostics.PROJECTION
    super(known.message)
    this.name = 'K9GraphProjectorError'
    this.code = known.code
    this.stage = safeTokenPattern.test(diagnostic?.stage || '') ? diagnostic.stage : known.stage
    this.retryable = known.retryable
    this.diagnostic = Object.freeze({
      ...diagnostic,
      code: known.code,
      stage: this.stage,
      retryable: known.retryable,
      message: known.message,
    })
    this.projectorId = projectorId
  }
}

function exactProjectorId(value) {
  const projectorId = String(value || '').trim().toUpperCase()
  if (!K9_GRAPH_PROJECTOR_IDS.includes(projectorId)) {
    throw new TypeError('The K9 graph projector ID is invalid.')
  }
  return projectorId
}

function requiredPorts(persistence, managedGraphs) {
  if (!persistence
    || typeof persistence.readLifecycle !== 'function'
    || typeof persistence.appendProjectorReceipt !== 'function') {
    throw new TypeError('The K9 graph projector persistence port is incomplete.')
  }
  if (!managedGraphs || typeof managedGraphs.publishPersistedProjection !== 'function') {
    throw new TypeError('The K9 managed graph projection port is incomplete.')
  }
}

function sourceSnapshotIdFromReceipt(receipt, projectorId) {
  const sourceSnapshotId = receipt?.source_snapshot_id
  const nestedSnapshotId = receipt?.source_snapshot?.source_snapshot_id ?? sourceSnapshotId
  if (receipt?.status !== 'READY' || !hashPattern.test(sourceSnapshotId || '')
    || nestedSnapshotId !== sourceSnapshotId) {
    throw new K9GraphProjectorError(graphDiagnostics.INPUT, projectorId)
  }
  return sourceSnapshotId
}

function latestReceipt(receipts, projectorId) {
  if (!Array.isArray(receipts)) return null
  return receipts.find((receipt) => receipt?.projector === projectorId) || null
}

function receiptState(lifecycle, projectorId) {
  const desired = latestReceipt(lifecycle?.desired_projector_receipts, projectorId)
  const activeLkg = latestReceipt(lifecycle?.active_ready_projector_receipts, projectorId)
  // A READY graph receipt proves that its output pointer is already active even if the aggregate
  // snapshot is still waiting for another independent projector (for example Semantic).
  const active = desired?.status === 'READY' ? desired : activeLkg
  return Object.freeze({ desired, active })
}

export function k9GraphProjectorReceiptState(lifecycle, projectorIdValue) {
  const projectorId = exactProjectorId(projectorIdValue)
  const state = receiptState(lifecycle, projectorId)
  return Object.freeze({
    projector_id: projectorId,
    desired: state.desired
      ? Object.freeze({
          projector_id: projectorId,
          desired_snapshot_id: state.desired.source_snapshot_id,
          source_snapshot_id: state.desired.source_snapshot_id,
          status: state.desired.status,
          receipt: state.desired,
        })
      : null,
    active: state.active
      ? Object.freeze({
          projector_id: projectorId,
          active_snapshot_id: state.active.source_snapshot_id,
          source_snapshot_id: state.active.source_snapshot_id,
          status: state.active.status,
          receipt: state.active,
        })
      : null,
  })
}

function normalizedLifecycleInput(lifecycle, sourceSnapshotId, projectorId) {
  if (!lifecycle || lifecycle.desired_snapshot_id !== sourceSnapshotId
    || lifecycle.desired_snapshot?.source_snapshot_id !== sourceSnapshotId) {
    throw new K9GraphProjectorError(graphDiagnostics.INPUT, projectorId)
  }
  let snapshot
  let payloads
  try {
    snapshot = normalizeK9SourceSnapshotV2(lifecycle.desired_snapshot)
    const sourcePayloads = lifecycle.desired_source_payloads
    payloads = normalizeK9SourcePayloadsV2({
      inventory: sourcePayloads?.INVENTORY,
      lineage: sourcePayloads?.LINEAGE,
      metadata: sourcePayloads?.METADATA,
      dangling_state: sourcePayloads?.DANGLING_STATE,
    }, snapshot)
  } catch {
    throw new K9GraphProjectorError(graphDiagnostics.INPUT, projectorId)
  }
  return Object.freeze({
    snapshot,
    payload: payloads[projectorId],
    totalUnits: projectorId === 'LINEAGE'
      ? (payloads.LINEAGE.nodes?.length || 0) + (payloads.LINEAGE.edges?.length || 0)
      : Object.values(payloads.METADATA.collections || {})
        .reduce((total, items) => total + (Array.isArray(items) ? items.length : 0), 0),
  })
}

function normalizedTimestamp(value) {
  const date = value instanceof Date ? value : new Date(value)
  if (!Number.isFinite(date.getTime())) throw new TypeError('The K9 graph projector clock is invalid.')
  return date.toISOString()
}

function newAttemptId(createAttemptId, projectorId, sourceSnapshotId, attemptNumber) {
  const candidate = createAttemptId({ projectorId, sourceSnapshotId, attemptNumber })
  if (typeof candidate === 'string' && hashPattern.test(candidate)) return candidate
  throw new TypeError('The K9 graph projector attempt identity is invalid.')
}

function receiptDocument({
  projectorId,
  sourceSnapshotId,
  status,
  attemptId,
  attemptNumber,
  sequence,
  previousReceiptId,
  progress,
  diagnostic = null,
  outputPointer = null,
  outputHash = null,
  clock,
}) {
  const recordedAt = normalizedTimestamp(clock())
  const document = {
    contract: K9_PROJECTOR_RECEIPT_CONTRACT_V2,
    source_snapshot_id: sourceSnapshotId,
    projector: projectorId,
    status,
    attempt_id: attemptId,
    attempt_number: attemptNumber,
    sequence,
    previous_receipt_id: previousReceiptId,
    idempotency_key_hash: computeSha256({
      contract: K9_PROJECTOR_RECEIPT_CONTRACT_V2,
      source_snapshot_id: sourceSnapshotId,
      projector: projectorId,
      attempt_id: attemptId,
      attempt_number: attemptNumber,
      sequence,
      status,
    }),
    progress,
    diagnostic,
    output_pointer: outputPointer,
    output_hash: outputHash,
    recorded_at: recordedAt,
  }
  return normalizeK9ProjectorReceiptV2({ ...document, receipt_id: computeSha256(document) })
}

function boundedFailureDiagnostic(projectorId, sourceSnapshotId, result) {
  const promotionFailure = result?.failureCode === 'K9_PROMOTION_FAILED'
  const diagnostic = promotionFailure ? graphDiagnostics.PROMOTION : graphDiagnostics.PROJECTION
  const sourceCode = safeTokenPattern.test(result?.failureCode || '')
    ? result.failureCode
    : diagnostic.code
  const detail = result?.diagnostic && typeof result.diagnostic === 'object'
    ? result.diagnostic : {}
  const stage = safeTokenPattern.test(detail.failure_stage || '')
    ? detail.failure_stage : diagnostic.stage
  const failureDetailCode = safeTokenPattern.test(detail.failure_detail_code || '')
    ? detail.failure_detail_code : sourceCode
  const bounded = {
    code: diagnostic.code,
    stage,
    failure_detail_code: failureDetailCode,
    projector_id: projectorId,
    detail_hash: computeSha256({ projectorId, sourceSnapshotId, sourceCode, stage, failureDetailCode }),
  }
  for (const field of ['neo4j_http_class', 'neo4j_error_class', 'query_family', 'transaction_phase']) {
    if (safeTokenPattern.test(detail[field] || '')) bounded[field] = detail[field]
  }
  for (const field of graphDiagnosticCountFields) {
    bounded[field] = Number.isSafeInteger(detail[field]) && detail[field] >= 0
      ? Math.min(detail[field], 1_000_000_000) : 0
  }
  for (const field of graphDiagnosticBooleanFields) bounded[field] = detail[field] === true
  return Object.freeze({
    ...bounded,
  })
}

function progress(phase, completedUnits, totalUnits, pointerAdvanced = false) {
  return Object.freeze({
    phase,
    completed_units: completedUnits,
    total_units: totalUnits,
    pointer_advanced: pointerAdvanced,
  })
}

/**
 * Creates one LINEAGE or METADATA projector over immutable persisted source payload X. The
 * persistence port owns forward-only receipt serialization; the managed graph port owns staging,
 * read-back verification, and the atomic active-pointer/LKG fence. No source collector or Semantic
 * state is read by this adapter.
 */
export function createK9GraphProjector({
  projectorId: projectorIdValue,
  persistence,
  managedGraphs,
  resolveAuthContext,
  clock = () => new Date(),
  createAttemptId = ({ projectorId, sourceSnapshotId, attemptNumber }) => computeSha256({
    projectorId, sourceSnapshotId, attemptNumber, nonce: randomUUID(),
  }),
} = {}) {
  const projectorId = exactProjectorId(projectorIdValue)
  requiredPorts(persistence, managedGraphs)
  if (typeof resolveAuthContext !== 'function' || typeof clock !== 'function'
    || typeof createAttemptId !== 'function') {
    throw new TypeError('The K9 graph projector runtime ports are incomplete.')
  }

  const append = async (receipt) => {
    try {
      await persistence.appendProjectorReceipt(receipt)
      return receipt
    } catch {
      throw new K9GraphProjectorError(graphDiagnostics.PERSISTENCE, projectorId)
    }
  }

  return Object.freeze({
    async project(sourceReceipt) {
      const sourceSnapshotId = sourceSnapshotIdFromReceipt(sourceReceipt, projectorId)
      let lifecycle
      try {
        lifecycle = await persistence.readLifecycle()
      } catch {
        throw new K9GraphProjectorError(graphDiagnostics.PERSISTENCE, projectorId)
      }
      const input = normalizedLifecycleInput(lifecycle, sourceSnapshotId, projectorId)
      const existing = receiptState(lifecycle, projectorId).desired
      if (existing?.status === 'READY' && existing.source_snapshot_id === sourceSnapshotId) {
        return Object.freeze({
          status: 'READY', outcome: 'REUSED', projector_id: projectorId,
          source_snapshot_id: sourceSnapshotId,
          desired_snapshot_id: sourceSnapshotId,
          active_snapshot_id: sourceSnapshotId,
          output_pointer: existing.output_pointer,
          output_hash: existing.output_hash,
        })
      }
      if (existing && existing.source_snapshot_id !== sourceSnapshotId) {
        throw new K9GraphProjectorError(graphDiagnostics.INPUT, projectorId)
      }

      const continuing = existing && ['PENDING', 'RUNNING'].includes(existing.status)
      const attemptNumber = continuing ? existing.attempt_number : (existing?.attempt_number || 0) + 1
      const attemptId = continuing
        ? existing.attempt_id
        : newAttemptId(createAttemptId, projectorId, sourceSnapshotId, attemptNumber)
      let previous = existing
      if (!continuing) {
        previous = await append(receiptDocument({
          projectorId,
          sourceSnapshotId,
          status: 'PENDING',
          attemptId,
          attemptNumber,
          sequence: 1,
          previousReceiptId: existing?.receipt_id || null,
          progress: progress(`${projectorId}_PENDING`, 0, input.totalUnits),
          clock,
        }))
      }
      const running = await append(receiptDocument({
        projectorId,
        sourceSnapshotId,
        status: 'RUNNING',
        attemptId,
        attemptNumber,
        sequence: previous.sequence + 1,
        previousReceiptId: previous.receipt_id,
        progress: progress(`${projectorId}_RUNNING`, 0, input.totalUnits),
        clock,
      }))

      let result
      try {
        const authContext = await resolveAuthContext()
        result = await managedGraphs.publishPersistedProjection(authContext, {
          projector_id: projectorId,
          source_snapshot: structuredClone(input.snapshot),
          source_payload: structuredClone(input.payload),
        })
      } catch {
        result = { status: 'FAILURE', failureCode: 'K9_GRAPH_PROJECTION_FAILED' }
      }
      const ready = ['RUN', 'NO_OP'].includes(result?.status)
        && result.sourceSnapshotId === sourceSnapshotId
        && typeof result.outputPointer === 'string' && result.outputPointer.length > 0
        && hashPattern.test(result.manifestHash || '')
      if (!ready) {
        const diagnostic = boundedFailureDiagnostic(projectorId, sourceSnapshotId, result)
        await append(receiptDocument({
          projectorId,
          sourceSnapshotId,
          status: 'FAILED',
          attemptId,
          attemptNumber,
          sequence: running.sequence + 1,
          previousReceiptId: running.receipt_id,
          progress: progress(`${projectorId}_FAILED`, 0, input.totalUnits),
          diagnostic,
          clock,
        }))
        throw new K9GraphProjectorError(diagnostic, projectorId)
      }

      const terminal = await append(receiptDocument({
        projectorId,
        sourceSnapshotId,
        status: 'READY',
        attemptId,
        attemptNumber,
        sequence: running.sequence + 1,
        previousReceiptId: running.receipt_id,
        progress: progress(`${projectorId}_READY`, input.totalUnits, input.totalUnits, true),
        outputPointer: result.outputPointer,
        outputHash: result.manifestHash,
        clock,
      }))
      return Object.freeze({
        status: 'READY',
        outcome: result.status === 'NO_OP' ? 'REUSED_OUTPUT' : 'PROJECTED',
        projector_id: projectorId,
        source_snapshot_id: sourceSnapshotId,
        desired_snapshot_id: sourceSnapshotId,
        active_snapshot_id: sourceSnapshotId,
        output_pointer: terminal.output_pointer,
        output_hash: terminal.output_hash,
      })
    },
  })
}

export function createK9GraphProjectors(options = {}) {
  return Object.freeze(Object.fromEntries(K9_GRAPH_PROJECTOR_IDS.map((projectorId) => [
    projectorId,
    createK9GraphProjector({ ...options, projectorId }),
  ])))
}

export function createK9LineageProjector(options = {}) {
  return createK9GraphProjector({ ...options, projectorId: 'LINEAGE' })
}

export function createK9MetadataProjector(options = {}) {
  return createK9GraphProjector({ ...options, projectorId: 'METADATA' })
}
