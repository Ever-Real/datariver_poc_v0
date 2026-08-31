export const K9_V2_PROJECTOR_IDS = Object.freeze(['LINEAGE', 'METADATA', 'SEMANTIC'])
export const K9_V2_RECEIPT_STATES = Object.freeze(['PENDING', 'RUNNING', 'READY', 'FAILED'])

const hashPattern = /^[0-9a-f]{64}$/u
const safeDiagnosticTokenPattern = /^[A-Z][A-Z0-9_]{0,95}$/u
const receiptStates = new Set(K9_V2_RECEIPT_STATES)

const diagnostics = Object.freeze({
  AGGREGATE_NOT_READY: Object.freeze({
    code: 'K9_V2_AGGREGATE_NOT_READY', stage: 'READINESS', retryable: true,
  }),
  MIXED_SOURCE_SNAPSHOT_IDS: Object.freeze({
    code: 'K9_V2_MIXED_SOURCE_SNAPSHOT_IDS', stage: 'READINESS', retryable: false,
  }),
  PROJECTOR_FAILED: Object.freeze({
    code: 'K9_V2_PROJECTOR_FAILED', stage: 'PROJECTOR', retryable: true,
  }),
  PROJECTOR_RECEIPT_INVALID: Object.freeze({
    code: 'K9_V2_PROJECTOR_RECEIPT_INVALID', stage: 'PROJECTOR_RECEIPT', retryable: false,
  }),
  PROJECTOR_RECEIPT_NOT_READY: Object.freeze({
    code: 'K9_V2_PROJECTOR_RECEIPT_NOT_READY', stage: 'PROJECTOR_RECEIPT', retryable: true,
  }),
  PROJECTOR_RECEIPT_READ_FAILED: Object.freeze({
    code: 'K9_V2_PROJECTOR_RECEIPT_READ_FAILED', stage: 'PROJECTOR_RECEIPT', retryable: true,
  }),
  SOURCE_CAPTURE_FAILED: Object.freeze({
    code: 'K9_V2_SOURCE_CAPTURE_FAILED', stage: 'SOURCE_CAPTURE', retryable: true,
  }),
  SOURCE_RECEIPT_INVALID: Object.freeze({
    code: 'K9_V2_SOURCE_RECEIPT_INVALID', stage: 'SOURCE_RECEIPT', retryable: false,
  }),
  SOURCE_RECEIPT_PERSISTENCE_FAILED: Object.freeze({
    code: 'K9_V2_SOURCE_RECEIPT_PERSISTENCE_FAILED', stage: 'SOURCE_RECEIPT', retryable: true,
  }),
  SOURCE_RECEIPT_READ_FAILED: Object.freeze({
    code: 'K9_V2_SOURCE_RECEIPT_READ_FAILED', stage: 'SOURCE_RECEIPT', retryable: true,
  }),
})

class LifecycleFailure extends Error {
  constructor(diagnostic, projectorId) {
    super(diagnostic.code)
    this.name = 'K9V2LifecycleFailure'
    this.diagnostic = diagnostic
    this.projectorId = projectorId
  }
}

function frozenDiagnostic(value) {
  return Object.freeze({
    code: value.code,
    stage: value.stage,
    retryable: value.retryable === true,
  })
}

function safeProjectorDiagnostic(error) {
  const candidate = error?.diagnostic
  if (!candidate || !safeDiagnosticTokenPattern.test(candidate.code || '')
    || !safeDiagnosticTokenPattern.test(candidate.stage || '')
    || typeof candidate.retryable !== 'boolean') {
    return frozenDiagnostic(diagnostics.PROJECTOR_FAILED)
  }
  return frozenDiagnostic(candidate)
}

function exactSnapshotId(value) {
  return typeof value === 'string' && hashPattern.test(value) ? value : null
}

function exactProjectorId(value, expectedProjectorId) {
  return value === undefined || value === expectedProjectorId
}

function sourceReceiptState(value) {
  if (value === null || value === undefined) return Object.freeze({ kind: 'MISSING' })
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return Object.freeze({ kind: 'INVALID' })
  }
  if (!receiptStates.has(value.status)) return Object.freeze({ kind: 'INVALID' })
  if (value.status !== 'READY') return Object.freeze({ kind: 'INCOMPLETE' })
  const sourceSnapshotId = exactSnapshotId(value.source_snapshot_id)
  const nestedSnapshotId = value.source_snapshot === undefined
    ? sourceSnapshotId
    : exactSnapshotId(value.source_snapshot?.source_snapshot_id)
  if (!sourceSnapshotId || nestedSnapshotId !== sourceSnapshotId) {
    return Object.freeze({ kind: 'INVALID' })
  }
  return Object.freeze({ kind: 'READY', sourceSnapshotId, receipt: value })
}

function projectorReceiptState(value, projectorId, kind) {
  if (value === null || value === undefined) return Object.freeze({ kind: 'MISSING' })
  if (!value || typeof value !== 'object' || Array.isArray(value)
    || !exactProjectorId(value.projector_id, projectorId)) {
    return Object.freeze({ kind: 'INVALID' })
  }
  const roleKey = kind === 'DESIRED' ? 'desired_snapshot_id' : 'active_snapshot_id'
  const roleSnapshotId = exactSnapshotId(value[roleKey])
  const commonSnapshotId = value.source_snapshot_id === undefined
    ? roleSnapshotId
    : exactSnapshotId(value.source_snapshot_id)
  if (!roleSnapshotId || commonSnapshotId !== roleSnapshotId) {
    return Object.freeze({ kind: 'INVALID' })
  }
  if (kind === 'DESIRED' && !receiptStates.has(value.status)) {
    return Object.freeze({ kind: 'INVALID' })
  }
  if (kind === 'ACTIVE' && value.status !== undefined && !receiptStates.has(value.status)) {
    return Object.freeze({ kind: 'INVALID' })
  }
  return Object.freeze({
    kind: 'VALID',
    sourceSnapshotId: roleSnapshotId,
    status: value.status,
  })
}

function projectorReadiness(projectorId, desiredReceipt, activeReceipt, sourceSnapshotId) {
  const desired = projectorReceiptState(desiredReceipt, projectorId, 'DESIRED')
  const active = projectorReceiptState(activeReceipt, projectorId, 'ACTIVE')
  const invalid = desired.kind === 'INVALID' || active.kind === 'INVALID'
  const desiredMismatch = desired.kind === 'VALID'
    && desired.sourceSnapshotId !== sourceSnapshotId
  const contradictoryActive = desired.kind === 'VALID'
    && desired.status === 'READY'
    && active.kind === 'VALID'
    && active.sourceSnapshotId !== sourceSnapshotId
  const ready = !invalid
    && desired.kind === 'VALID'
    && active.kind === 'VALID'
    && desired.status === 'READY'
    && (active.status === undefined || active.status === 'READY')
    && desired.sourceSnapshotId === sourceSnapshotId
    && active.sourceSnapshotId === sourceSnapshotId
  return Object.freeze({
    projectorId,
    desired,
    active,
    invalid,
    desiredMismatch,
    contradictoryActive,
    ready,
  })
}

function readinessSummary(state) {
  return Object.freeze({
    desired: state.desired.kind === 'MISSING' ? 'MISSING' : state.desired.status || state.desired.kind,
    active: state.active.kind === 'MISSING' ? 'MISSING' : state.active.status || state.active.kind,
    ready: state.ready,
  })
}

/**
 * Computes REQUIRED-mode readiness from opaque source and projector receipts. Snapshot hashes are
 * compared but never expanded into source identifiers, and no provider/source payload is returned.
 */
export function evaluateK9V2AggregateReadiness({
  sourceReceipt,
  projectorReceipts,
  expectedSourceSnapshotId,
} = {}) {
  const source = sourceReceiptState(sourceReceipt)
  const expected = expectedSourceSnapshotId === undefined
    ? source.sourceSnapshotId
    : exactSnapshotId(expectedSourceSnapshotId)
  const identities = new Set()
  if (expected) identities.add(expected)
  if (source.sourceSnapshotId) identities.add(source.sourceSnapshotId)
  let invalid = source.kind === 'INVALID' || !expected
  const projectors = {}

  for (const projectorId of K9_V2_PROJECTOR_IDS) {
    const pair = projectorReceipts?.[projectorId]
    const state = projectorReadiness(projectorId, pair?.desired, pair?.active, expected)
    invalid ||= state.invalid
    if (state.desiredMismatch) identities.add(state.desired.sourceSnapshotId)
    if (state.contradictoryActive) identities.add(state.active.sourceSnapshotId)
    projectors[projectorId] = readinessSummary(state)
  }

  const mixed = identities.size > 1
  const ready = source.kind === 'READY'
    && source.sourceSnapshotId === expected
    && !invalid
    && !mixed
    && K9_V2_PROJECTOR_IDS.every((projectorId) => projectors[projectorId].ready)
  const reason = ready
    ? null
    : mixed
      ? diagnostics.MIXED_SOURCE_SNAPSHOT_IDS.code
      : invalid
        ? diagnostics.PROJECTOR_RECEIPT_INVALID.code
        : diagnostics.AGGREGATE_NOT_READY.code

  return Object.freeze({
    status: ready ? 'READY' : 'NOT_READY',
    source_snapshot_id: expected || null,
    reason,
    projectors: Object.freeze(projectors),
  })
}

function requiredPorts({ captureSource, receipts, projectors }) {
  const receiptMethods = [
    'readSourceCaptureReceipt',
    'writeSourceCaptureReceipt',
    'readProjectorDesiredReceipt',
    'readProjectorActiveReceipt',
  ]
  if (typeof captureSource !== 'function'
    || !receipts
    || receiptMethods.some((method) => typeof receipts[method] !== 'function')
    || !projectors
    || K9_V2_PROJECTOR_IDS.some((projectorId) => (
      typeof projectors[projectorId]?.project !== 'function'
    ))) {
    throw new TypeError('The K9 V2 lifecycle ports are incomplete.')
  }
}

async function readSource(receipts) {
  try {
    return await receipts.readSourceCaptureReceipt()
  } catch {
    throw new LifecycleFailure(frozenDiagnostic(diagnostics.SOURCE_RECEIPT_READ_FAILED))
  }
}

async function captureOrReuseSource(captureSource, receipts, {
  currentReceipt,
  reuseCurrent = false,
} = {}) {
  if (currentReceipt === undefined) currentReceipt = await readSource(receipts)
  const current = sourceReceiptState(currentReceipt)
  if (current.kind === 'READY' && reuseCurrent) {
    return Object.freeze({ outcome: 'REUSED', receipt: current.receipt, sourceSnapshotId: current.sourceSnapshotId })
  }
  if (current.kind === 'INVALID') {
    throw new LifecycleFailure(frozenDiagnostic(diagnostics.SOURCE_RECEIPT_INVALID))
  }

  let capturedReceipt
  try {
    capturedReceipt = await captureSource()
  } catch {
    throw new LifecycleFailure(frozenDiagnostic(diagnostics.SOURCE_CAPTURE_FAILED))
  }
  const captured = sourceReceiptState(capturedReceipt)
  if (captured.kind !== 'READY') {
    throw new LifecycleFailure(frozenDiagnostic(diagnostics.SOURCE_RECEIPT_INVALID))
  }
  try {
    await receipts.writeSourceCaptureReceipt(capturedReceipt)
  } catch {
    throw new LifecycleFailure(frozenDiagnostic(diagnostics.SOURCE_RECEIPT_PERSISTENCE_FAILED))
  }
  const persistedReceipt = await readSource(receipts)
  const persisted = sourceReceiptState(persistedReceipt)
  if (persisted.kind !== 'READY' || persisted.sourceSnapshotId !== captured.sourceSnapshotId) {
    throw new LifecycleFailure(frozenDiagnostic(diagnostics.SOURCE_RECEIPT_PERSISTENCE_FAILED))
  }
  return Object.freeze({
    outcome: 'CAPTURED', receipt: persisted.receipt, sourceSnapshotId: persisted.sourceSnapshotId,
  })
}

async function sourceRunDisposition(receipts) {
  const currentReceipt = await readSource(receipts)
  const current = sourceReceiptState(currentReceipt)
  if (current.kind !== 'READY') return Object.freeze({ currentReceipt, reuseCurrent: false })
  const currentProjectors = await readAllProjectorPairs(receipts)
  const readiness = evaluateK9V2AggregateReadiness({
    sourceReceipt: currentReceipt,
    projectorReceipts: currentProjectors,
    expectedSourceSnapshotId: current.sourceSnapshotId,
  })
  // An incomplete lifecycle resumes its immutable source. Once every
  // projector is READY, the next scheduled/manual run captures again so
  // DataHub drift can produce a successor snapshot. A same-source capture
  // deterministically returns the same identity and all projectors are reused.
  return Object.freeze({
    currentReceipt,
    reuseCurrent: readiness.status !== 'READY',
  })
}

async function readProjectorPair(receipts, projectorId) {
  try {
    const [desired, active] = await Promise.all([
      receipts.readProjectorDesiredReceipt(projectorId),
      receipts.readProjectorActiveReceipt(projectorId),
    ])
    return Object.freeze({ desired, active })
  } catch {
    throw new LifecycleFailure(
      frozenDiagnostic(diagnostics.PROJECTOR_RECEIPT_READ_FAILED), projectorId,
    )
  }
}

async function readAllProjectorPairs(receipts) {
  const entries = await Promise.all(K9_V2_PROJECTOR_IDS.map(async (projectorId) => (
    [projectorId, await readProjectorPair(receipts, projectorId)]
  )))
  return Object.freeze(Object.fromEntries(entries))
}

function failureResult({ source, projectors, readiness, diagnostic, failedProjector }) {
  return Object.freeze({
    status: 'FAILED',
    source_snapshot_id: source?.sourceSnapshotId || readiness?.source_snapshot_id || null,
    source: Object.freeze({
      status: source ? 'READY' : 'FAILED',
      outcome: source?.outcome || 'FAILED',
    }),
    projectors: Object.freeze(projectors || {}),
    readiness: readiness || null,
    diagnostic,
    ...(failedProjector ? { failed_projector: failedProjector } : {}),
  })
}

/**
 * Coordinates one source-only capture and three independently resumable projector lifecycles.
 * Every persistence and materialization action is supplied as a port; the core assumes no database,
 * graph, provider, transaction, or source payload shape beyond the bounded receipt envelopes.
 */
export function createK9V2LifecycleOrchestrator({
  captureSource,
  receipts,
  projectors,
  onTransition,
} = {}) {
  requiredPorts({ captureSource, receipts, projectors })
  const transition = (event) => {
    if (typeof onTransition === 'function') onTransition(Object.freeze({ ...event }))
  }

  return Object.freeze({
    async run() {
      let source
      const projectorOutcomes = {}
      const failures = []
      try {
        const disposition = await sourceRunDisposition(receipts)
        source = await captureOrReuseSource(captureSource, receipts, disposition)
        transition({ stage: 'SOURCE', status: 'READY', outcome: source.outcome })

        for (const projectorId of K9_V2_PROJECTOR_IDS) {
          let before
          try {
            before = await readProjectorPair(receipts, projectorId)
            const state = projectorReadiness(
              projectorId, before.desired, before.active, source.sourceSnapshotId,
            )
            if (state.invalid) {
              throw new LifecycleFailure(
                frozenDiagnostic(diagnostics.PROJECTOR_RECEIPT_INVALID), projectorId,
              )
            }
            if (state.ready) {
              projectorOutcomes[projectorId] = Object.freeze({ status: 'READY', outcome: 'REUSED' })
              transition({ stage: 'PROJECTOR', projector_id: projectorId, status: 'READY', outcome: 'REUSED' })
              continue
            }

            transition({ stage: 'PROJECTOR', projector_id: projectorId, status: 'RUNNING' })
            const result = await projectors[projectorId].project(source.receipt)
            if (result?.status !== 'READY'
              || exactSnapshotId(result.source_snapshot_id) !== source.sourceSnapshotId) {
              throw new LifecycleFailure(
                frozenDiagnostic(diagnostics.PROJECTOR_RECEIPT_NOT_READY), projectorId,
              )
            }
            const after = await readProjectorPair(receipts, projectorId)
            const verified = projectorReadiness(
              projectorId, after.desired, after.active, source.sourceSnapshotId,
            )
            if (verified.invalid) {
              throw new LifecycleFailure(
                frozenDiagnostic(diagnostics.PROJECTOR_RECEIPT_INVALID), projectorId,
              )
            }
            if (!verified.ready) {
              throw new LifecycleFailure(
                frozenDiagnostic(diagnostics.PROJECTOR_RECEIPT_NOT_READY), projectorId,
              )
            }
            projectorOutcomes[projectorId] = Object.freeze({ status: 'READY', outcome: 'PROJECTED' })
            transition({ stage: 'PROJECTOR', projector_id: projectorId, status: 'READY', outcome: 'PROJECTED' })
          } catch (error) {
            const diagnostic = error instanceof LifecycleFailure
              ? error.diagnostic
              : safeProjectorDiagnostic(error)
            const failedProjector = error instanceof LifecycleFailure && error.projectorId
              ? error.projectorId
              : projectorId
            projectorOutcomes[projectorId] = Object.freeze({
              status: 'FAILED', outcome: 'ATTEMPTED', diagnostic,
            })
            failures.push(Object.freeze({ projectorId: failedProjector, diagnostic }))
            transition({ stage: 'PROJECTOR', projector_id: projectorId, status: 'FAILED', diagnostic })
          }
        }

        const [finalSourceReceipt, finalProjectorReceipts] = await Promise.all([
          readSource(receipts),
          readAllProjectorPairs(receipts),
        ])
        const readiness = evaluateK9V2AggregateReadiness({
          sourceReceipt: finalSourceReceipt,
          projectorReceipts: finalProjectorReceipts,
          expectedSourceSnapshotId: source.sourceSnapshotId,
        })
        if (failures.length || readiness.status !== 'READY') {
          const firstFailure = failures[0]
          const diagnostic = firstFailure?.diagnostic || frozenDiagnostic(
            readiness.reason === diagnostics.MIXED_SOURCE_SNAPSHOT_IDS.code
              ? diagnostics.MIXED_SOURCE_SNAPSHOT_IDS
              : diagnostics.AGGREGATE_NOT_READY,
          )
          return failureResult({
            source,
            projectors: projectorOutcomes,
            readiness,
            diagnostic,
            failedProjector: firstFailure?.projectorId,
          })
        }
        transition({ stage: 'READINESS', status: 'READY' })
        return Object.freeze({
          status: 'READY',
          source_snapshot_id: source.sourceSnapshotId,
          source: Object.freeze({ status: 'READY', outcome: source.outcome }),
          projectors: Object.freeze(projectorOutcomes),
          readiness,
        })
      } catch (error) {
        const diagnostic = error instanceof LifecycleFailure
          ? error.diagnostic
          : frozenDiagnostic(diagnostics.AGGREGATE_NOT_READY)
        return failureResult({
          source,
          projectors: projectorOutcomes,
          readiness: null,
          diagnostic,
          failedProjector: error instanceof LifecycleFailure ? error.projectorId : undefined,
        })
      }
    },
  })
}
