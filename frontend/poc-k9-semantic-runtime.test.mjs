/* global AbortController, structuredClone */
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { buildK9ProjectorReceiptV2 } from './poc-k9-lifecycle-runtime.mjs'
import {
  buildK9SemanticCatalogDocuments,
  createK9V2SemanticLifecycleProjector,
} from './poc-k9-semantic-runtime.mjs'

const snapshotId = 'a'.repeat(64)
const bindingHash = 'b'.repeat(64)

function nextClock() {
  let tick = 0
  return () => new Date(Date.UTC(2026, 7, 31, 0, 0, tick++)).toISOString()
}

function sourceReceipt(count = 33) {
  return Object.freeze({
    status: 'READY',
    source_snapshot_id: snapshotId,
    source_snapshot: Object.freeze({
      source_snapshot_id: snapshotId,
      catalog_generation: 'c'.repeat(64),
    }),
    source_payloads: Object.freeze({
      inventory: Object.freeze({
        items: Object.freeze(Array.from({ length: count }, (_, index) => Object.freeze({
          id: `urn:li:dataset:(urn:li:dataPlatform:test,asset-${String(index).padStart(5, '0')},PROD)`,
          name: `asset-${index}`,
          ordinal: index,
        }))),
      }),
      lineage: {},
      metadata: {},
      dangling_state: {},
    }),
  })
}

function sourceReady(now) {
  let receipt = buildK9ProjectorReceiptV2({
    sourceSnapshotId: snapshotId, projectorId: 'SOURCE', status: 'PENDING', recordedAt: now(),
  })
  receipt = buildK9ProjectorReceiptV2({
    sourceSnapshotId: snapshotId,
    projectorId: 'SOURCE',
    status: 'RUNNING',
    previous: receipt,
    progress: { phase: 'SOURCE_CAPTURE', completed_units: 1, total_units: 1 },
    recordedAt: now(),
  })
  return buildK9ProjectorReceiptV2({
    sourceSnapshotId: snapshotId,
    projectorId: 'SOURCE',
    status: 'READY',
    previous: receipt,
    progress: { phase: 'SOURCE_CAPTURE', completed_units: 1, total_units: 1 },
    outputPointer: `k9-source-v2://${snapshotId}`,
    outputHash: snapshotId,
    recordedAt: now(),
  })
}

function fakeLifecycle(now) {
  const state = {
    desired_snapshot_id: snapshotId,
    active_snapshot_id: null,
    status: 'RUNNING',
    version: 1,
    desired_projector_receipts: [sourceReady(now)],
    active_ready_projector_receipts: [],
  }
  return {
    state,
    async readLifecycle() { return structuredClone(state) },
    async appendProjectorReceipt(receipt) {
      const index = state.desired_projector_receipts.findIndex((item) => item.projector === receipt.projector)
      if (index >= 0) state.desired_projector_receipts[index] = structuredClone(receipt)
      else state.desired_projector_receipts.push(structuredClone(receipt))
      state.status = receipt.status === 'FAILED' ? 'FAILED' : 'RUNNING'
      state.version += 1
      return { created: true, receipt }
    },
  }
}

function fakeSemanticPersistence() {
  const state = {
    activeSnapshot: null,
    activeHashes: new Map(),
    staged: new Map(),
    stagedDimension: undefined,
    stagedBatchCount: 0,
    stagedBatchTotal: 0,
    manifest: null,
    calls: [],
  }
  return {
    state,
    async withProjectorGenerationLock(_target, operation) {
      return operation(new AbortController().signal)
    },
    async readProjectorState() {
      return state.activeSnapshot
        ? { status: 'READY', active_snapshot_id: state.activeSnapshot }
        : { status: 'RUNNING', active_snapshot_id: null }
    },
    async setDesiredSnapshot() {},
    async readActiveDocumentHashes() { return { hashes: [...state.activeHashes].map(([document_id, source_hash]) => ({ document_id, source_hash })) } },
    async readStagedDocumentHashes() {
      return {
        hashes: [...state.staged].map(([document_id, source_hash]) => ({ document_id, source_hash })),
        vector_dimension: state.stagedDimension,
        batch_count: state.stagedBatchCount,
        batch_total: state.stagedBatchTotal,
      }
    },
    async persistDesiredManifest(value) { state.manifest = value },
    async writeEmbeddingBatch(batch) {
      state.calls.push(['batch', batch.batch_number, batch.records.length])
      state.stagedDimension = batch.vector_dimension
      state.stagedBatchCount = batch.batch_number
      state.stagedBatchTotal = batch.batch_total
      for (const item of batch.records) state.staged.set(item.document_id, item.source_hash)
    },
    async activateSnapshot(target) {
      state.activeSnapshot = target.source_snapshot_id
      state.activeHashes = new Map(state.manifest.documents.map((item) => [item.document_id, item.source_hash]))
    },
  }
}

test('catalog documents are deterministic derivatives of the immutable inventory payload', () => {
  const receipt = sourceReceipt(3)
  const first = buildK9SemanticCatalogDocuments(receipt, {
    renderDocument: (asset) => `${asset.name}|${asset.ordinal}`,
  })
  const second = buildK9SemanticCatalogDocuments(receipt, {
    renderDocument: (asset) => `${asset.name}|${asset.ordinal}`,
  })
  assert.deepEqual(first, second)
  assert.deepEqual(first.map((item) => item.document_id), [...first.map((item) => item.document_id)].sort())
  assert.ok(first.every((item) => /^[0-9a-f]{64}$/.test(item.source_hash)))
})

test('Semantic V2 persists a bounded provider failure and retries only the persisted snapshot materializer', async () => {
  const now = nextClock()
  const lifecycle = fakeLifecycle(now)
  const semanticPersistence = fakeSemanticPersistence()
  const receipt = sourceReceipt()
  let providerRequests = 0
  let rendered = 0
  const projector = createK9V2SemanticLifecycleProjector({
    bindingHash,
    model: 'embedding-model-v1',
    lifecycle,
    semanticPersistence,
    clock: now,
    renderDocument(asset) { rendered += 1; return `${asset.name}|${asset.ordinal}` },
    provider: {
      async embed({ input }) {
        providerRequests += 1
        if (providerRequests === 1) {
          throw Object.assign(new Error('raw provider endpoint and token'), { code: 'ETIMEDOUT' })
        }
        return { data: input.map((_, index) => ({ index, embedding: [index + 0.25, index + 0.5] })) }
      },
    },
  })

  await assert.rejects(projector.project(receipt), {
    diagnostic: { code: 'K9_SEMANTIC_PROVIDER_TIMEOUT', stage: 'PROVIDER', retryable: true },
  })
  let semanticReceipt = lifecycle.state.desired_projector_receipts.find((item) => item.projector === 'SEMANTIC')
  assert.equal(semanticReceipt.status, 'FAILED')
  assert.equal(semanticReceipt.diagnostic.code, 'K9_SEMANTIC_PROVIDER_TIMEOUT')
  assert.equal(JSON.stringify(semanticReceipt).includes('raw provider'), false)

  const result = await projector.project(receipt)
  assert.equal(result.status, 'READY')
  assert.equal(providerRequests, 3)
  assert.equal(rendered, 66)
  assert.deepEqual(semanticPersistence.state.calls, [['batch', 1, 32], ['batch', 2, 1]])
  semanticReceipt = lifecycle.state.desired_projector_receipts.find((item) => item.projector === 'SEMANTIC')
  assert.equal(semanticReceipt.status, 'READY')
  assert.equal(semanticReceipt.attempt_number, 2)
  assert.equal(semanticReceipt.progress.completed_units, 33)
  assert.equal(semanticReceipt.progress.total_units, 33)
})
