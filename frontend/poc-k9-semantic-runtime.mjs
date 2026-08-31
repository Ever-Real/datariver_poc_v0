/* global structuredClone */
import { computeSha256 } from './poc-knowledge-k9-contracts.mjs'
import { createK9V2DurableProjector } from './poc-k9-lifecycle-runtime.mjs'
import { createK9SemanticProjector } from './poc-k9-semantic-projector.mjs'

const HASH = /^[0-9a-f]{64}$/u

function runtimeError(code, message) {
  return Object.assign(new Error(message), { code })
}

function inventoryItems(sourceReceipt) {
  const items = sourceReceipt?.source_payloads?.inventory?.items
  if (!Array.isArray(items) || items.some((item) => (
    !item || typeof item !== 'object' || typeof item.id !== 'string' || !item.id.trim()
  ))) {
    throw runtimeError(
      'K9_SEMANTIC_CATALOG_PROJECTION_FAILED',
      'The immutable source snapshot has no valid Semantic inventory.',
    )
  }
  return items
}

export function buildK9SemanticCatalogDocuments(sourceReceipt, {
  renderDocument,
  projectMetadata = (asset) => structuredClone(asset),
} = {}) {
  if (typeof renderDocument !== 'function' || typeof projectMetadata !== 'function') {
    throw new TypeError('The Semantic catalog projection functions are incomplete.')
  }
  const documents = inventoryItems(sourceReceipt).map((asset) => {
    const contentText = renderDocument(asset)
    const metadata = projectMetadata(asset)
    if (typeof contentText !== 'string' || !contentText
      || !metadata || typeof metadata !== 'object' || Array.isArray(metadata)) {
      throw runtimeError(
        'K9_SEMANTIC_CATALOG_PROJECTION_FAILED',
        'One immutable source document could not be projected for Semantic indexing.',
      )
    }
    return {
      document_id: asset.id,
      source_hash: computeSha256(contentText),
      content_text: contentText,
      metadata,
    }
  }).sort((left, right) => left.document_id.localeCompare(right.document_id))
  if (documents.some((item, index) => index > 0
    && item.document_id === documents[index - 1].document_id)) {
    throw runtimeError(
      'K9_SEMANTIC_CATALOG_PROJECTION_FAILED',
      'The immutable source snapshot contains duplicate Semantic document identities.',
    )
  }
  return Object.freeze(documents.map((item) => Object.freeze(item)))
}

function semanticProgress(value, sourceReceipt) {
  const documentTotal = inventoryItems(sourceReceipt).length
  const completedCandidate = value?.materialized_count
    ?? value?.result?.document_count
    ?? value?.completed
    ?? 0
  const completed = Number.isSafeInteger(completedCandidate)
    ? Math.max(0, Math.min(documentTotal, completedCandidate))
    : 0
  const batchCompleted = Number.isSafeInteger(value?.batches_completed)
    ? Math.max(0, value.batches_completed)
    : 0
  const result = {
    phase: typeof value?.stage === 'string' ? value.stage : 'SEMANTIC_INDEX',
    completed_units: completed,
    total_units: documentTotal,
    documents_processed: completed,
    documents_materialized: completed,
  }
  const changedCount = value?.changed_count ?? value?.result?.changed_count
  if (Number.isSafeInteger(changedCount) && changedCount >= 0) {
    result.documents_changed = changedCount
  }
  if (Number.isSafeInteger(value?.batch_total) && value.batch_total >= 0) {
    result.batch_total = value.batch_total
  }
  if (batchCompleted > 0) result.batch_number = batchCompleted
  if (Number.isSafeInteger(value?.batch_elapsed_ms) && value.batch_elapsed_ms >= 0) {
    result.batch_elapsed_ms = value.batch_elapsed_ms
  }
  return Object.freeze(result)
}

/**
 * Composes the real Semantic materializer with the common immutable projector receipt lifecycle.
 * Its only source input is the persisted source snapshot/payload envelope; retries cannot call
 * DataHub or a graph publisher.
 */
export function createK9V2SemanticLifecycleProjector({
  bindingHash,
  model,
  provider,
  semanticPersistence,
  lifecycle,
  renderDocument,
  projectMetadata,
  timer,
  clock,
}) {
  if (typeof bindingHash !== 'string' || !HASH.test(bindingHash)) {
    throw new TypeError('The Semantic binding hash is invalid.')
  }
  const durable = createK9V2DurableProjector({
    projectorId: 'SEMANTIC',
    lifecycle,
    progress: semanticProgress,
    clock,
    output: (result, sourceReceipt) => ({
      output_pointer: `k9-semantic-v2://${sourceReceipt.source_snapshot_id}/${bindingHash}`,
      output_hash: computeSha256({
        contract: 'DATARIVER_K9_SEMANTIC_OUTPUT_V2',
        source_snapshot_id: sourceReceipt.source_snapshot_id,
        binding_hash: bindingHash,
        document_count: result.document_count,
        changed_count: result.changed_count,
      }),
    }),
    async materialize(sourceReceipt, { onProgress }) {
      const catalogDocuments = buildK9SemanticCatalogDocuments(sourceReceipt, {
        renderDocument,
        projectMetadata,
      })
      const projector = createK9SemanticProjector({
        bindingHash,
        model,
        provider,
        persistence: semanticPersistence,
        onProgress,
        ...(timer ? { timer } : {}),
      })
      return projector.project({
        source_snapshot: sourceReceipt.source_snapshot,
        catalog_documents: catalogDocuments,
      })
    },
  })
  return durable
}
