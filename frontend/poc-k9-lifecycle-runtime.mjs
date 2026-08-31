import { canonicalStringify, computeSha256 } from './poc-knowledge-k9-contracts.mjs'
import {
  K9_PROJECTOR_RECEIPT_CONTRACT_V2,
  K9_PROJECTORS_V2,
  normalizeK9ProjectorReceiptV2,
} from './poc-k9-lifecycle-persistence.mjs'

const HASH = /^[0-9a-f]{64}$/u
const TOKEN = /^[A-Z][A-Z0-9_]{0,79}$/u

function runtimeError(code, message) {
  return Object.assign(new Error(message), { code })
}

function exactHash(value, name) {
  if (typeof value !== 'string' || !HASH.test(value)) {
    throw runtimeError('K9_LIFECYCLE_RUNTIME_INVALID', `${name} is invalid.`)
  }
  return value
}

function projector(value) {
  const normalized = String(value || '').trim().toUpperCase()
  if (!K9_PROJECTORS_V2.includes(normalized)) {
    throw runtimeError('K9_LIFECYCLE_RUNTIME_INVALID', 'The K9 projector identity is invalid.')
  }
  return normalized
}

function receiptFor(state, projectorId) {
  return state?.desired_projector_receipts?.find((item) => item.projector === projectorId) || null
}

function activeReceiptFor(state, projectorId) {
  return state?.active_ready_projector_receipts?.find((item) => item.projector === projectorId) || null
}

function sourceEnvelope(state, sourceReceipt) {
  if (!state?.desired_snapshot) return null
  return Object.freeze({
    status: sourceReceipt?.status || 'PENDING',
    source_snapshot_id: state.desired_snapshot_id,
    source_snapshot: state.desired_snapshot,
    source_payloads: Object.freeze({
      inventory: state.desired_source_payloads?.INVENTORY,
      lineage: state.desired_source_payloads?.LINEAGE,
      metadata: state.desired_source_payloads?.METADATA,
      dangling_state: state.desired_source_payloads?.DANGLING_STATE,
    }),
  })
}

function mappedDesiredReceipt(value, projectorId) {
  if (!value) return null
  return Object.freeze({
    projector_id: projectorId,
    desired_snapshot_id: value.source_snapshot_id,
    source_snapshot_id: value.source_snapshot_id,
    status: value.status,
    receipt: value,
  })
}

function mappedActiveReceipt(value, projectorId) {
  if (!value) return null
  return Object.freeze({
    projector_id: projectorId,
    active_snapshot_id: value.source_snapshot_id,
    source_snapshot_id: value.source_snapshot_id,
    status: 'READY',
    receipt: value,
  })
}

function attemptIdentity(sourceSnapshotId, projectorId, attemptNumber) {
  return computeSha256({
    contract: 'DATARIVER_K9_PROJECTOR_ATTEMPT_V2',
    source_snapshot_id: sourceSnapshotId,
    projector: projectorId,
    attempt_number: attemptNumber,
  })
}

function nextAttempt(previous, status) {
  if (!previous) {
    if (status !== 'PENDING') throw runtimeError('K9_PROJECTOR_TRANSITION_INVALID', 'A K9 projector attempt must start PENDING.')
    return { attemptNumber: 1, sequence: 1, previousReceiptId: null }
  }
  if (previous.status === 'FAILED') {
    if (status !== 'PENDING') throw runtimeError('K9_PROJECTOR_TRANSITION_INVALID', 'A failed K9 projector requires a new PENDING attempt.')
    return {
      attemptNumber: Number(previous.attempt_number) + 1,
      sequence: 1,
      previousReceiptId: previous.receipt_id,
    }
  }
  return {
    attemptNumber: Number(previous.attempt_number),
    sequence: Number(previous.sequence) + 1,
    previousReceiptId: previous.receipt_id,
  }
}

export function buildK9ProjectorReceiptV2({
  sourceSnapshotId: sourceSnapshotIdValue,
  projectorId: projectorIdValue,
  status,
  previous = null,
  progress = null,
  diagnostic = null,
  outputPointer = null,
  outputHash = null,
  recordedAt = new Date().toISOString(),
}) {
  const sourceSnapshotId = exactHash(sourceSnapshotIdValue, 'sourceSnapshotId')
  const projectorId = projector(projectorIdValue)
  const attempt = nextAttempt(previous, status)
  const attemptId = previous && previous.status !== 'FAILED'
    ? previous.attempt_id
    : attemptIdentity(sourceSnapshotId, projectorId, attempt.attemptNumber)
  const idempotencyKeyHash = computeSha256({
    contract: 'DATARIVER_K9_PROJECTOR_RECEIPT_IDEMPOTENCY_V2',
    source_snapshot_id: sourceSnapshotId,
    projector: projectorId,
    attempt_id: attemptId,
    sequence: attempt.sequence,
    status,
  })
  const document = {
    contract: K9_PROJECTOR_RECEIPT_CONTRACT_V2,
    source_snapshot_id: sourceSnapshotId,
    projector: projectorId,
    status,
    attempt_id: attemptId,
    attempt_number: attempt.attemptNumber,
    sequence: attempt.sequence,
    previous_receipt_id: attempt.previousReceiptId,
    idempotency_key_hash: idempotencyKeyHash,
    progress,
    diagnostic,
    output_pointer: outputPointer,
    output_hash: outputHash,
    recorded_at: recordedAt,
  }
  return normalizeK9ProjectorReceiptV2({ ...document, receipt_id: computeSha256(document) })
}

async function appendTerminalSourceReceipts(lifecycle, state, sourceSnapshotId, clock) {
  let previous = receiptFor(state, 'SOURCE')
  if (previous?.status === 'READY') return previous
  if (!previous || previous.status === 'FAILED') {
    previous = (await lifecycle.appendProjectorReceipt(buildK9ProjectorReceiptV2({
      sourceSnapshotId,
      projectorId: 'SOURCE',
      status: 'PENDING',
      previous,
      recordedAt: clock(),
    }))).receipt
  }
  if (previous.status === 'PENDING') {
    previous = (await lifecycle.appendProjectorReceipt(buildK9ProjectorReceiptV2({
      sourceSnapshotId,
      projectorId: 'SOURCE',
      status: 'RUNNING',
      previous,
      progress: { phase: 'SOURCE_CAPTURE', completed_units: 1, total_units: 1 },
      recordedAt: clock(),
    }))).receipt
  }
  return (await lifecycle.appendProjectorReceipt(buildK9ProjectorReceiptV2({
    sourceSnapshotId,
    projectorId: 'SOURCE',
    status: 'READY',
    previous,
    progress: { phase: 'SOURCE_CAPTURE', completed_units: 1, total_units: 1 },
    outputPointer: `k9-source-v2://${sourceSnapshotId}`,
    outputHash: sourceSnapshotId,
    recordedAt: clock(),
  }))).receipt
}

/**
 * Adapts immutable PostgreSQL V2 lifecycle evidence to the orchestration core. A desired READY
 * receipt is considered projector-active before aggregate promotion because each projector writes
 * READY only after its own atomic active-pointer verification. The aggregate head is promoted only
 * after SOURCE and all three projector READY receipts exist for the exact snapshot.
 */
export function createK9V2LifecycleReceiptPort({ lifecycle, clock = () => new Date().toISOString() }) {
  for (const method of ['readLifecycle', 'setDesiredSnapshot', 'appendProjectorReceipt', 'promoteActiveSnapshot']) {
    if (typeof lifecycle?.[method] !== 'function') throw new TypeError('The K9 V2 lifecycle persistence port is incomplete.')
  }
  if (typeof clock !== 'function') throw new TypeError('The K9 V2 lifecycle clock is invalid.')

  return Object.freeze({
    async readSourceCaptureReceipt() {
      const state = await lifecycle.readLifecycle()
      if (!state) return null
      return sourceEnvelope(state, receiptFor(state, 'SOURCE'))
    },

    async writeSourceCaptureReceipt(receipt) {
      const sourceSnapshotId = exactHash(receipt?.source_snapshot_id, 'source_snapshot_id')
      if (receipt?.status !== 'READY' || receipt?.source_snapshot?.source_snapshot_id !== sourceSnapshotId) {
        throw runtimeError('K9_SOURCE_RECEIPT_INVALID', 'The captured K9 source receipt is invalid.')
      }
      await lifecycle.setDesiredSnapshot({
        snapshot: receipt.source_snapshot,
        source_payloads: receipt.source_payloads,
      })
      const state = await lifecycle.readLifecycle()
      if (!state || state.desired_snapshot_id !== sourceSnapshotId) {
        throw runtimeError('K9_SOURCE_RECEIPT_PERSISTENCE_FAILED', 'The K9 desired source snapshot was not durable.')
      }
      await appendTerminalSourceReceipts(lifecycle, state, sourceSnapshotId, clock)
    },

    async readProjectorDesiredReceipt(projectorIdValue) {
      const projectorId = projector(projectorIdValue)
      if (projectorId === 'SOURCE') throw new TypeError('SOURCE is not a materialization projector.')
      const state = await lifecycle.readLifecycle()
      return mappedDesiredReceipt(receiptFor(state, projectorId), projectorId)
    },

    async readProjectorActiveReceipt(projectorIdValue) {
      const projectorId = projector(projectorIdValue)
      if (projectorId === 'SOURCE') throw new TypeError('SOURCE is not a materialization projector.')
      const state = await lifecycle.readLifecycle()
      const desired = receiptFor(state, projectorId)
      if (desired?.status === 'READY') return mappedActiveReceipt(desired, projectorId)
      return mappedActiveReceipt(activeReceiptFor(state, projectorId), projectorId)
    },

    async promoteAggregate(sourceSnapshotIdValue) {
      const sourceSnapshotId = exactHash(sourceSnapshotIdValue, 'sourceSnapshotId')
      const state = await lifecycle.readLifecycle()
      if (!state || state.desired_snapshot_id !== sourceSnapshotId) {
        throw runtimeError('K9_LIFECYCLE_HEAD_MISMATCH', 'The aggregate K9 target changed before promotion.')
      }
      return lifecycle.promoteActiveSnapshot({
        sourceSnapshotId,
        expectedVersion: Number(state.version),
      })
    },
  })
}

function safeFailure(projectorId, error) {
  const code = TOKEN.test(error?.diagnostic?.code || '')
    ? error.diagnostic.code
    : `K9_${projectorId}_PROJECTOR_FAILED`
  const stage = TOKEN.test(error?.diagnostic?.stage || '')
    ? error.diagnostic.stage
    : `${projectorId}_PROJECTION`
  const retryable = error?.diagnostic?.retryable !== false
  const providerFailureClass = TOKEN.test(error?.diagnostic?.provider_failure_class || '')
    ? error.diagnostic.provider_failure_class
    : null
  return Object.freeze({ code, stage, retryable, provider_failure_class: providerFailureClass })
}

function persistedDiagnostic(value) {
  return Object.freeze({
    code: value.code,
    stage: value.stage,
    detail_hash: null,
    ...(value.provider_failure_class ? { provider_failure_class: value.provider_failure_class } : {}),
  })
}

/**
 * Owns one projectors immutable attempt/sequence evidence. Materializers receive a durable
 * `onProgress` callback and must not append receipts themselves. No raw provider/source payload is
 * accepted by the receipt serializer.
 */
export function createK9V2DurableProjector({
  projectorId: projectorIdValue,
  lifecycle,
  materialize,
  progress,
  output,
  clock = () => new Date().toISOString(),
}) {
  const projectorId = projector(projectorIdValue)
  if (projectorId === 'SOURCE' || typeof lifecycle?.readLifecycle !== 'function'
    || typeof lifecycle?.appendProjectorReceipt !== 'function'
    || typeof materialize !== 'function' || typeof progress !== 'function'
    || typeof output !== 'function' || typeof clock !== 'function') {
    throw new TypeError('The durable K9 projector contract is incomplete.')
  }

  return Object.freeze({
    async project(sourceReceipt) {
      const sourceSnapshotId = exactHash(sourceReceipt?.source_snapshot_id, 'source_snapshot_id')
      let state = await lifecycle.readLifecycle()
      if (!state || state.desired_snapshot_id !== sourceSnapshotId) {
        throw runtimeError('K9_LIFECYCLE_HEAD_MISMATCH', 'The K9 projector target is not current.')
      }
      let previous = receiptFor(state, projectorId)
      if (previous?.status === 'READY') {
        return Object.freeze({ status: 'READY', outcome: 'REUSED', source_snapshot_id: sourceSnapshotId })
      }
      if (!previous || previous.status === 'FAILED') {
        previous = (await lifecycle.appendProjectorReceipt(buildK9ProjectorReceiptV2({
          sourceSnapshotId, projectorId, status: 'PENDING', previous, recordedAt: clock(),
        }))).receipt
      }
      if (previous.status === 'PENDING') {
        previous = (await lifecycle.appendProjectorReceipt(buildK9ProjectorReceiptV2({
          sourceSnapshotId,
          projectorId,
          status: 'RUNNING',
          previous,
          progress: progress(null, sourceReceipt),
          recordedAt: clock(),
        }))).receipt
      }
      const onProgress = async (value) => {
        state = await lifecycle.readLifecycle()
        previous = receiptFor(state, projectorId)
        if (previous?.status !== 'RUNNING') {
          throw runtimeError('K9_PROJECTOR_TRANSITION_INVALID', 'The K9 projector progress head is not RUNNING.')
        }
        previous = (await lifecycle.appendProjectorReceipt(buildK9ProjectorReceiptV2({
          sourceSnapshotId,
          projectorId,
          status: 'RUNNING',
          previous,
          progress: progress(value, sourceReceipt),
          recordedAt: clock(),
        }))).receipt
      }
      try {
        const result = await materialize(sourceReceipt, { onProgress })
        state = await lifecycle.readLifecycle()
        previous = receiptFor(state, projectorId)
        const terminal = output(result, sourceReceipt)
        previous = (await lifecycle.appendProjectorReceipt(buildK9ProjectorReceiptV2({
          sourceSnapshotId,
          projectorId,
          status: 'READY',
          previous,
          progress: progress({ stage: 'READY', result }, sourceReceipt),
          outputPointer: terminal.output_pointer,
          outputHash: terminal.output_hash,
          recordedAt: clock(),
        }))).receipt
        return Object.freeze({
          status: 'READY', outcome: 'PROJECTED', source_snapshot_id: sourceSnapshotId,
          receipt_id: previous.receipt_id,
        })
      } catch (error) {
        const diagnostic = safeFailure(projectorId, error)
        try {
          state = await lifecycle.readLifecycle()
          previous = receiptFor(state, projectorId)
          if (previous?.status === 'PENDING' || previous?.status === 'RUNNING') {
            await lifecycle.appendProjectorReceipt(buildK9ProjectorReceiptV2({
              sourceSnapshotId,
              projectorId,
              status: 'FAILED',
              previous,
              progress: previous.progress,
              diagnostic: persistedDiagnostic(diagnostic),
              recordedAt: clock(),
            }))
          }
        } catch {
          throw Object.assign(runtimeError(
            'K9_PROJECTOR_FAILURE_RECEIPT_FAILED',
            'The K9 projector failure receipt could not be persisted.',
          ), { diagnostic: Object.freeze({
            code: 'K9_PROJECTOR_FAILURE_RECEIPT_FAILED', stage: 'PROJECTOR_RECEIPT', retryable: true,
          }) })
        }
        throw Object.assign(error instanceof Error ? error : new Error(diagnostic.code), {
          diagnostic: Object.freeze({
            code: diagnostic.code, stage: diagnostic.stage, retryable: diagnostic.retryable,
          }),
        })
      }
    },
  })
}

export function k9V2ReceiptDebugIdentity(receipt) {
  return computeSha256(canonicalStringify(receipt))
}
