/* global AbortController, AbortSignal, clearTimeout, setTimeout, structuredClone */
import { defaultLlmProviderTimeoutMs, llmProviderFailureCodes } from './poc-llm-timeout.mjs'

export const K9_SEMANTIC_PROJECTOR_ID = 'SEMANTIC'
export const K9_SEMANTIC_BATCH_SIZE = 32
export const K9_SEMANTIC_PROVIDER_TIMEOUT_MS = defaultLlmProviderTimeoutMs

const maximumVectorDimension = 4096
const hashPattern = /^[0-9a-f]{64}$/u
const safeIdentifierPattern = /^[A-Z][A-Z0-9_]{0,63}$/u

const diagnostics = Object.freeze({
  ACTIVE_POINTER: Object.freeze({
    code: 'K9_SEMANTIC_ACTIVE_POINTER_FAILED', stage: 'ACTIVE_POINTER', retryable: true,
    message: 'The Semantic active pointer could not be advanced.',
  }),
  CANCELLED: Object.freeze({
    code: 'K9_SEMANTIC_CANCELLED', stage: 'PROVIDER', retryable: true,
    message: 'The Semantic projection was cancelled.',
  }),
  CATALOG_PROJECTION: Object.freeze({
    code: 'K9_SEMANTIC_CATALOG_PROJECTION_FAILED', stage: 'CATALOG_PROJECTION', retryable: true,
    message: 'The Semantic desired document manifest could not be persisted.',
  }),
  GENERATION_LOCK: Object.freeze({
    code: 'K9_SEMANTIC_GENERATION_LOCK_FAILED', stage: 'GENERATION_LOCK', retryable: true,
    message: 'The Semantic generation lock could not be acquired or retained.',
  }),
  MATERIALIZATION: Object.freeze({
    code: 'K9_SEMANTIC_MATERIALIZATION_FAILED', stage: 'MATERIALIZATION', retryable: true,
    message: 'The Semantic snapshot could not be materialized.',
  }),
  PROVIDER_AUTH: Object.freeze({
    code: 'K9_SEMANTIC_PROVIDER_AUTH_FAILED', stage: 'PROVIDER', retryable: false,
    message: 'The Embedding provider rejected authentication.',
  }),
  PROVIDER_CONNECTIVITY: Object.freeze({
    code: 'K9_SEMANTIC_PROVIDER_CONNECTIVITY_FAILED', stage: 'PROVIDER', retryable: true,
    message: 'The Embedding provider could not be reached.',
  }),
  PROVIDER_CONTRACT: Object.freeze({
    code: 'K9_SEMANTIC_PROVIDER_CONTRACT_FAILED', stage: 'PROVIDER', retryable: false,
    message: 'The Embedding provider returned an invalid response contract.',
  }),
  PROVIDER_HTTP: Object.freeze({
    code: 'K9_SEMANTIC_PROVIDER_HTTP_FAILED', stage: 'PROVIDER', retryable: true,
    message: 'The Embedding provider returned an unsuccessful HTTP response.',
  }),
  PROVIDER_TIMEOUT: Object.freeze({
    code: 'K9_SEMANTIC_PROVIDER_TIMEOUT', stage: 'PROVIDER', retryable: true,
    message: 'The Embedding provider exceeded the bounded request time.',
  }),
  VECTOR_COUNT: Object.freeze({
    code: 'K9_SEMANTIC_VECTOR_COUNT_INVALID', stage: 'VECTOR_VALIDATION', retryable: false,
    message: 'The Embedding provider returned an incomplete vector batch.',
  }),
  VECTOR_DIMENSION: Object.freeze({
    code: 'K9_SEMANTIC_VECTOR_DIMENSION_INVALID', stage: 'VECTOR_VALIDATION', retryable: false,
    message: 'The Embedding provider returned an invalid vector dimension.',
  }),
  VECTOR_FINITE: Object.freeze({
    code: 'K9_SEMANTIC_VECTOR_FINITE_INVALID', stage: 'VECTOR_VALIDATION', retryable: false,
    message: 'The Embedding provider returned a non-finite vector value.',
  }),
})

export class K9SemanticProjectorError extends Error {
  constructor(diagnostic) {
    super(diagnostic.message)
    this.name = 'K9SemanticProjectorError'
    this.code = diagnostic.code
    this.stage = diagnostic.stage
    this.retryable = diagnostic.retryable
    this.diagnostic = Object.freeze({ ...diagnostic })
  }
}

function projectorError(kind) {
  return new K9SemanticProjectorError(diagnostics[kind])
}

export function k9SemanticProjectorDiagnostic(error) {
  if (error instanceof K9SemanticProjectorError) return error.diagnostic
  return diagnostics.MATERIALIZATION
}

function providerStatus(error) {
  const value = Number(error?.statusCode ?? error?.status ?? error?.response?.status)
  return Number.isInteger(value) && value >= 100 && value <= 599 ? value : undefined
}

function providerError(error, timedOut, externallyAborted) {
  if (externallyAborted) return projectorError('CANCELLED')
  const status = providerStatus(error)
  const code = String(error?.code || '')
  if (timedOut || error?.name === 'TimeoutError' || code === 'ETIMEDOUT'
    || error?.productCode === llmProviderFailureCodes.TIMEOUT) return projectorError('PROVIDER_TIMEOUT')
  if (status === 401 || status === 403
    || error?.productCode === llmProviderFailureCodes.AUTH) return projectorError('PROVIDER_AUTH')
  if (status !== undefined || error?.productCode === llmProviderFailureCodes.HTTP) {
    return projectorError('PROVIDER_HTTP')
  }
  if (error?.productCode === llmProviderFailureCodes.CONTRACT) return projectorError('PROVIDER_CONTRACT')
  return projectorError('PROVIDER_CONNECTIVITY')
}

function normalizedProviderRows(payload) {
  if (Array.isArray(payload?.data)) {
    const rows = payload.data.map((row) => ({ index: Number(row?.index), vector: row?.embedding }))
    if (rows.some((row) => !Number.isSafeInteger(row.index) || row.index < 0)) return null
    rows.sort((left, right) => left.index - right.index)
    if (rows.some((row, index) => row.index !== index)) return null
    return rows.map((row) => row.vector)
  }
  if (Array.isArray(payload?.embeddings)) return payload.embeddings
  return null
}

export function validateEmbeddingVectors(payload, expectedCount, expectedDimension) {
  const vectors = normalizedProviderRows(payload)
  if (!vectors && !Array.isArray(payload?.data) && !Array.isArray(payload?.embeddings)) {
    throw projectorError('PROVIDER_CONTRACT')
  }
  if (!vectors) throw projectorError('VECTOR_COUNT')
  if (vectors.length !== expectedCount) throw projectorError('VECTOR_COUNT')
  if (vectors.some((vector) => !Array.isArray(vector)
    || vector.length < 1 || vector.length > maximumVectorDimension)) {
    throw projectorError('VECTOR_DIMENSION')
  }
  const dimension = vectors[0]?.length ?? expectedDimension
  if (!dimension || vectors.some((vector) => vector.length !== dimension)
    || (expectedDimension !== undefined && dimension !== expectedDimension)) {
    throw projectorError('VECTOR_DIMENSION')
  }
  if (vectors.some((vector) => vector.some((value) => (
    typeof value !== 'number' || !Number.isFinite(value)
  )))) throw projectorError('VECTOR_FINITE')
  return Object.freeze({
    vectors: Object.freeze(vectors.map((vector) => Object.freeze([...vector]))),
    dimension,
  })
}

function exactHash(value, label) {
  const normalized = String(value || '').trim().toLowerCase()
  if (!hashPattern.test(normalized)) throw new TypeError(`${label} must be a SHA-256 value.`)
  return normalized
}

function normalizedDocument(document) {
  if (!document || typeof document !== 'object') throw new TypeError('A catalog document is invalid.')
  const documentId = String(document.document_id || '').trim()
  const contentText = typeof document.content_text === 'string' ? document.content_text : ''
  if (!documentId || !contentText) throw new TypeError('A catalog document identity or content is invalid.')
  return Object.freeze({
    documentId,
    sourceHash: exactHash(document.source_hash, 'Catalog document source_hash'),
    contentText,
    metadata: document.metadata && typeof document.metadata === 'object'
      ? structuredClone(document.metadata)
      : {},
  })
}

function normalizedInput(input) {
  const snapshot = input?.source_snapshot
  if (!snapshot || typeof snapshot !== 'object') throw new TypeError('The source snapshot is invalid.')
  const sourceSnapshotId = exactHash(snapshot.source_snapshot_id, 'source_snapshot_id')
  const sourceGeneration = exactHash(snapshot.catalog_generation, 'catalog_generation')
  if (!Array.isArray(input.catalog_documents)) {
    throw new TypeError('The Semantic catalog_documents are invalid.')
  }
  const documents = Object.freeze(input.catalog_documents.map(normalizedDocument)
    .sort((left, right) => left.documentId.localeCompare(right.documentId)))
  if (documents.some((document, index) => index > 0
    && document.documentId === documents[index - 1].documentId)) {
    throw new TypeError('The source snapshot contains duplicate catalog document identities.')
  }
  return Object.freeze({ sourceSnapshotId, sourceGeneration, documents })
}

function normalizedHashMap(value) {
  const candidate = value?.hashes ?? value
  if (candidate === undefined || candidate === null) return new Map()
  if (candidate instanceof Map) return new Map(candidate)
  if (Array.isArray(candidate)) return new Map(candidate.map((item) => [item.document_id, item.source_hash]))
  if (typeof candidate === 'object') return new Map(Object.entries(candidate))
  throw new TypeError('The Semantic document hash receipt is invalid.')
}

function requiredPort(persistence) {
  const methods = [
    'withProjectorGenerationLock',
    'readProjectorState',
    'setDesiredSnapshot',
    'readActiveDocumentHashes',
    'readStagedDocumentHashes',
    'writeEmbeddingBatch',
    'persistDesiredManifest',
    'activateSnapshot',
  ]
  if (!persistence || methods.some((method) => typeof persistence[method] !== 'function')) {
    throw new TypeError('The Semantic projector persistence port is incomplete.')
  }
  return persistence
}

function safeProgress(stage, completed, total, batchesCompleted) {
  return Object.freeze({
    stage,
    completed: Math.max(0, Math.min(total, completed)),
    total,
    batches_completed: Math.max(0, batchesCompleted),
  })
}

async function persisted(operation, failureKind) {
  try {
    return await operation()
  } catch (error) {
    if (error instanceof K9SemanticProjectorError) throw error
    throw projectorError(failureKind)
  }
}

async function providerBatch(provider, model, input, externalSignal, ownershipSignal, timer) {
  externalSignal?.throwIfAborted()
  ownershipSignal?.throwIfAborted()
  const timeoutController = new AbortController()
  let timedOut = false
  const timeout = timer.schedule(() => {
    timedOut = true
    timeoutController.abort()
  }, K9_SEMANTIC_PROVIDER_TIMEOUT_MS)
  const signals = [externalSignal, ownershipSignal, timeoutController.signal].filter(Boolean)
  const signal = signals.length === 1 ? signals[0] : AbortSignal.any(signals)
  try {
    const payload = await provider.embed({
      model,
      input,
      signal,
      timeout_ms: K9_SEMANTIC_PROVIDER_TIMEOUT_MS,
    })
    if (payload && typeof payload === 'object' && 'ok' in payload && 'status' in payload) {
      if (!payload.ok) throw Object.assign(new Error('provider HTTP failure'), { status: payload.status })
      try {
        return await payload.json()
      } catch {
        throw projectorError('PROVIDER_CONTRACT')
      }
    }
    return payload
  } catch (error) {
    if (error instanceof K9SemanticProjectorError) throw error
    if (ownershipSignal?.aborted) throw projectorError('GENERATION_LOCK')
    throw providerError(error, timedOut, Boolean(externalSignal?.aborted))
  } finally {
    timer.cancel(timeout)
  }
}

/**
 * The input keeps the immutable `source_snapshot` identity separate from `catalog_documents` so
 * the bounded durable source receipt need not contain provider text. Persistence supplies the
 * eight methods asserted by `requiredPort`; it receives source identities and opaque catalog
 * records, while diagnostics and progress contain counts/codes only. The port owns durable
 * idempotency and the atomic pointer fence. This projector never reacquires source data while
 * retrying a fixed input.
 */
export function createK9SemanticProjector({
  bindingHash,
  model,
  provider,
  persistence,
  projectorId = K9_SEMANTIC_PROJECTOR_ID,
  onProgress,
  timer = { schedule: setTimeout, cancel: clearTimeout },
}) {
  const exactBindingHash = exactHash(bindingHash, 'Semantic bindingHash')
  const exactProjectorId = String(projectorId || '').trim().toUpperCase()
  if (!safeIdentifierPattern.test(exactProjectorId)) throw new TypeError('The Semantic projector ID is invalid.')
  if (!model || typeof model !== 'string' || typeof provider?.embed !== 'function') {
    throw new TypeError('The Semantic Embedding provider configuration is invalid.')
  }
  if (typeof timer?.schedule !== 'function' || typeof timer?.cancel !== 'function') {
    throw new TypeError('The Semantic provider timer is invalid.')
  }
  const port = requiredPort(persistence)
  const progress = (stage, completed, total, batchesCompleted) => {
    if (typeof onProgress === 'function') onProgress(safeProgress(stage, completed, total, batchesCompleted))
  }

  return Object.freeze({
    async project(input, { signal } = {}) {
      const desired = normalizedInput(input)
      const identity = Object.freeze({ projector_id: exactProjectorId, binding_hash: exactBindingHash })
      const target = Object.freeze({
        ...identity,
        source_snapshot_id: desired.sourceSnapshotId,
        source_generation: desired.sourceGeneration,
        document_count: desired.documents.length,
      })
      let enteredLock = false
      try {
        return await port.withProjectorGenerationLock(target, async (ownershipSignal) => {
          enteredLock = true
          signal?.throwIfAborted()
          ownershipSignal?.throwIfAborted()
          await persisted(() => port.setDesiredSnapshot(target), 'MATERIALIZATION')
          progress('DESIRED', 0, desired.documents.length, 0)
          const state = await persisted(() => port.readProjectorState(identity), 'MATERIALIZATION')
          if (state?.status === 'READY' && state?.active_snapshot_id === desired.sourceSnapshotId) {
            progress('READY', desired.documents.length, desired.documents.length, 0)
            return Object.freeze({
              status: 'READY', outcome: 'REUSED', source_snapshot_id: desired.sourceSnapshotId,
              source_generation: desired.sourceGeneration, document_count: desired.documents.length,
              embedded_count: 0, reused_count: desired.documents.length,
              changed_count: 0, removed_count: 0, batches_completed: 0,
            })
          }

          const activeHashes = normalizedHashMap(await persisted(
            () => port.readActiveDocumentHashes(identity), 'MATERIALIZATION',
          ))
          const stagedReceipt = await persisted(
            () => port.readStagedDocumentHashes(target), 'MATERIALIZATION',
          )
          const stagedHashes = normalizedHashMap(stagedReceipt)
          let expectedDimension = Number(stagedReceipt?.vector_dimension) || undefined
          if (expectedDimension !== undefined && (!Number.isSafeInteger(expectedDimension)
            || expectedDimension < 1 || expectedDimension > maximumVectorDimension)) {
            throw projectorError('MATERIALIZATION')
          }
          const desiredHashes = new Map(desired.documents.map((document) => (
            [document.documentId, document.sourceHash]
          )))
          const changedDocuments = desired.documents.filter((document) => (
            activeHashes.get(document.documentId) !== document.sourceHash
          ))
          const changedDocumentCount = changedDocuments.length
          const removedCount = [...activeHashes.keys()].filter((documentId) => (
            !desiredHashes.has(documentId)
          )).length
          const changedCount = changedDocumentCount + removedCount
          const stagedPrefix = changedDocuments.filter((document) => (
            stagedHashes.get(document.documentId) === document.sourceHash
          ))
          const alreadyStaged = stagedPrefix.length
          const pending = changedDocuments.slice(alreadyStaged)
          const batchTotal = Math.ceil(changedDocumentCount / K9_SEMANTIC_BATCH_SIZE)
          const expectedStagedKeys = new Set(stagedPrefix.map((document) => document.documentId))
          const stagedBatchCount = Number(stagedReceipt?.batch_count ?? Math.ceil(
            alreadyStaged / K9_SEMANTIC_BATCH_SIZE,
          ))
          const reportedBatchTotal = Number(stagedReceipt?.batch_total ?? batchTotal)
          const stagedBatchTotal = alreadyStaged === 0 && reportedBatchTotal === 0
            ? batchTotal
            : reportedBatchTotal
          const stagedPrefixValid = changedDocuments.slice(0, alreadyStaged).every((document) => (
            expectedStagedKeys.has(document.documentId)
          ))
          if (!Number.isSafeInteger(stagedBatchCount) || stagedBatchCount < 0
            || stagedBatchCount > batchTotal || stagedBatchTotal !== batchTotal
            || stagedHashes.size !== alreadyStaged || !stagedPrefixValid
            || (pending.length > 0 && alreadyStaged % K9_SEMANTIC_BATCH_SIZE !== 0)
            || [...stagedHashes].some(([documentId, sourceHash]) => (
              desiredHashes.get(documentId) !== sourceHash
            ))) {
            throw projectorError('MATERIALIZATION')
          }
          let batchesCompleted = stagedBatchCount
          let completed = alreadyStaged
          await persisted(() => port.persistDesiredManifest({
            ...target,
            documents: desired.documents.map((document) => ({
              document_id: document.documentId,
              source_hash: document.sourceHash,
              content_text: document.contentText,
              metadata: document.metadata,
            })),
            vector_dimension: expectedDimension,
            changed_count: changedCount,
            removed_count: removedCount,
            staged_count: changedDocumentCount,
            batch_total: batchTotal,
          }), 'CATALOG_PROJECTION')
          progress('MANIFEST', 0, desired.documents.length, batchesCompleted)
          progress('EMBEDDING', completed, changedDocumentCount, batchesCompleted)
          for (let offset = 0; offset < pending.length; offset += K9_SEMANTIC_BATCH_SIZE) {
            signal?.throwIfAborted()
            ownershipSignal?.throwIfAborted()
            const batch = pending.slice(offset, offset + K9_SEMANTIC_BATCH_SIZE)
            const payload = await providerBatch(
              provider, model, batch.map((document) => document.contentText), signal, ownershipSignal, timer,
            )
            const validated = validateEmbeddingVectors(payload, batch.length, expectedDimension)
            expectedDimension = validated.dimension
            const records = batch.map((document, index) => ({
              document_id: document.documentId,
              source_hash: document.sourceHash,
              content_text: document.contentText,
              metadata: document.metadata,
              embedding: validated.vectors[index],
            }))
            completed += batch.length
            batchesCompleted += 1
            await persisted(() => port.writeEmbeddingBatch({
              ...target,
              records,
              batch_number: batchesCompleted,
              batch_total: batchTotal,
              vector_dimension: expectedDimension,
              completed_count: completed,
              changed_count: changedDocumentCount,
              removed_count: removedCount,
              batches_completed: batchesCompleted,
            }), 'MATERIALIZATION')
            progress('EMBEDDING', completed, changedDocumentCount, batchesCompleted)
          }
          signal?.throwIfAborted()
          ownershipSignal?.throwIfAborted()
          await persisted(() => port.activateSnapshot({
            ...target,
            changed_count: changedCount,
            removed_count: removedCount,
            staged_count: changedDocumentCount,
            batch_total: batchTotal,
            vector_dimension: expectedDimension,
          }), 'ACTIVE_POINTER')
          progress('MATERIALIZED', desired.documents.length, desired.documents.length, batchesCompleted)
          progress('READY', desired.documents.length, desired.documents.length, batchesCompleted)
          const outcome = changedCount === 0
            ? 'ZERO_CHANGE'
            : changedDocumentCount === desired.documents.length ? 'FULL_CHANGE' : 'PARTIAL_CHANGE'
          return Object.freeze({
            status: 'READY', outcome, source_snapshot_id: desired.sourceSnapshotId,
            source_generation: desired.sourceGeneration, document_count: desired.documents.length,
            embedded_count: pending.length, reused_count: desired.documents.length - pending.length,
            changed_count: changedCount, removed_count: removedCount, batches_completed: batchesCompleted,
          })
        })
      } catch (error) {
        if (error instanceof K9SemanticProjectorError) throw error
        if (signal?.aborted) throw projectorError('CANCELLED')
        if (!enteredLock) throw projectorError('GENERATION_LOCK')
        throw projectorError('GENERATION_LOCK')
      }
    },
  })
}
