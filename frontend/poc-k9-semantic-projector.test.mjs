/* global AbortController, queueMicrotask */
import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  K9_SEMANTIC_BATCH_SIZE,
  K9_SEMANTIC_PROVIDER_TIMEOUT_MS,
  createK9SemanticProjector,
  k9SemanticProjectorDiagnostic,
  validateEmbeddingVectors,
} from './poc-k9-semantic-projector.mjs'

const bindingHash = 'b'.repeat(64)
const generationA = 'a'.repeat(64)

function snapshot(documentCount, {
  snapshotId = '1'.repeat(64),
  generation = generationA,
  changed = () => true,
} = {}) {
  return Object.freeze({
    source_snapshot: Object.freeze({
      source_snapshot_id: snapshotId,
      catalog_generation: generation,
    }),
    catalog_documents: Object.freeze(Array.from({ length: documentCount }, (_, index) => Object.freeze({
      document_id: `urn:li:dataset:(urn:li:dataPlatform:test,asset-${String(index).padStart(5, '0')},PROD)`,
      source_hash: (changed(index) ? (index + 2).toString(16).padStart(64, '0') : 'f'.repeat(64)),
      content_text: `private catalog text ${index}`,
      metadata: Object.freeze({ ordinal: index }),
    }))),
  })
}

function fakePersistence({ activeSnapshot, activeDocuments = [], failures = {} } = {}) {
  const state = {
    activeSnapshot,
    activeHashes: new Map(activeDocuments.map((document) => [document.document_id, document.source_hash])),
    desired: null,
    staged: new Map(),
    stagedDimension: undefined,
    stagedBatchCount: 0,
    stagedBatchTotal: 0,
    materialized: null,
    calls: [],
  }
  return {
    state,
    async withProjectorGenerationLock(target, task) {
      state.calls.push(['lock', target.projector_id, target.source_snapshot_id])
      if (failures.lock) throw new Error('raw lock token must not escape')
      const ownership = new AbortController()
      if (failures.ownership) queueMicrotask(() => ownership.abort())
      return task(ownership.signal)
    },
    async setDesiredSnapshot(target) {
      state.calls.push(['desired', target.source_snapshot_id])
      state.desired = target.source_snapshot_id
    },
    async readProjectorState() {
      return state.activeSnapshot
        ? { status: 'READY', active_snapshot_id: state.activeSnapshot }
        : { status: 'PENDING', active_snapshot_id: null }
    },
    async readActiveDocumentHashes() { return new Map(state.activeHashes) },
    async readStagedDocumentHashes() {
      return {
        hashes: new Map(state.staged),
        vector_dimension: state.stagedDimension,
        batch_count: state.stagedBatchCount,
        batch_total: state.stagedBatchTotal,
      }
    },
    async writeEmbeddingBatch(batch) {
      if (failures.batch) throw new Error('raw vector must not escape')
      state.calls.push([
        'batch', batch.records.length, batch.completed_count, batch.changed_count,
        batch.batch_number, batch.batch_total,
      ])
      state.stagedDimension = batch.vector_dimension
      state.stagedBatchCount = batch.batch_number
      state.stagedBatchTotal = batch.batch_total
      for (const record of batch.records) state.staged.set(record.document_id, record.source_hash)
    },
    async materializeSnapshot(target) {
      state.calls.push(['materialize', target.document_count])
      if (failures.materialize) throw new Error('raw URN must not escape')
      state.materialized = target
    },
    async activateSnapshot(target) {
      state.calls.push(['activate', target.source_snapshot_id])
      if (failures.pointer) throw new Error('raw database detail must not escape')
      assert.ok(state.materialized)
      state.activeSnapshot = target.source_snapshot_id
      state.activeHashes = new Map(state.materialized.documents.map((document) => (
        [document.document_id, document.source_hash]
      )))
    },
  }
}

function provider(result = ({ input }) => ({
  data: input.map((_, index) => ({ index, embedding: [index + 0.25, index + 0.5] })),
})) {
  const calls = []
  return {
    calls,
    async embed(request) {
      calls.push(request)
      return result(request, calls.length)
    },
  }
}

function projector(overrides = {}) {
  const persistence = overrides.persistence || fakePersistence()
  const embeddingProvider = overrides.provider || provider()
  return {
    persistence,
    provider: embeddingProvider,
    value: createK9SemanticProjector({
      bindingHash,
      model: 'embedding-model-v1',
      persistence,
      provider: embeddingProvider,
      ...overrides,
    }),
  }
}

async function diagnosticForProviderFailure(error) {
  const embeddingProvider = provider(() => { throw error })
  const { value } = projector({ provider: embeddingProvider })
  return assert.rejects(value.project(snapshot(1)), (failure) => {
    assert.deepEqual(k9SemanticProjectorDiagnostic(failure), error.expected)
    return true
  })
}

test('keeps the accepted provider timeout and Semantic batch size unchanged', () => {
  assert.equal(K9_SEMANTIC_PROVIDER_TIMEOUT_MS, 120_000)
  assert.equal(K9_SEMANTIC_BATCH_SIZE, 32)
})

test('classifies provider authentication, connectivity, timeout, HTTP, and contract failures', async () => {
  const cases = [{
    error: Object.assign(new Error('raw bearer token'), { status: 401 }),
    expected: {
      code: 'K9_SEMANTIC_PROVIDER_AUTH_FAILED', stage: 'PROVIDER', retryable: false,
      message: 'The Embedding provider rejected authentication.',
    },
  }, {
    error: Object.assign(new TypeError('raw endpoint'), { code: 'ECONNREFUSED' }),
    expected: {
      code: 'K9_SEMANTIC_PROVIDER_CONNECTIVITY_FAILED', stage: 'PROVIDER', retryable: true,
      message: 'The Embedding provider could not be reached.',
    },
  }, {
    error: Object.assign(new Error('raw timeout'), { code: 'ETIMEDOUT' }),
    expected: {
      code: 'K9_SEMANTIC_PROVIDER_TIMEOUT', stage: 'PROVIDER', retryable: true,
      message: 'The Embedding provider exceeded the bounded request time.',
    },
  }, {
    error: Object.assign(new Error('raw body'), { status: 503 }),
    expected: {
      code: 'K9_SEMANTIC_PROVIDER_HTTP_FAILED', stage: 'PROVIDER', retryable: true,
      message: 'The Embedding provider returned an unsuccessful HTTP response.',
    },
  }, {
    error: Object.assign(new Error('raw response'), { productCode: 'POC_LLM_PROVIDER_CONTRACT_FAILED' }),
    expected: {
      code: 'K9_SEMANTIC_PROVIDER_CONTRACT_FAILED', stage: 'PROVIDER', retryable: false,
      message: 'The Embedding provider returned an invalid response contract.',
    },
  }]
  for (const item of cases) {
    item.error.expected = item.expected
    await diagnosticForProviderFailure(item.error)
  }
})

test('classifies a malformed provider payload separately from vector validation', async () => {
  const embeddingProvider = provider(() => ({ unexpected: 'raw response body' }))
  const { value } = projector({ provider: embeddingProvider })
  await assert.rejects(value.project(snapshot(1)), (error) => {
    assert.equal(error.diagnostic.code, 'K9_SEMANTIC_PROVIDER_CONTRACT_FAILED')
    assert.equal(JSON.stringify(error.diagnostic).includes('raw response body'), false)
    return true
  })
})

test('enforces its own 120-second provider signal without exposing provider details', async () => {
  let requestedTimeout
  const embeddingProvider = provider(({ signal, timeout_ms: timeoutMs }) => new Promise((resolve, reject) => {
    requestedTimeout = timeoutMs
    signal.addEventListener('abort', () => reject(Object.assign(new Error('secret timeout'), {
      name: 'AbortError',
    })), { once: true })
  }))
  const timer = {
    schedule(callback, milliseconds) {
      assert.equal(milliseconds, 120_000)
      queueMicrotask(callback)
      return 1
    },
    cancel() {},
  }
  const { value } = projector({ provider: embeddingProvider, timer })
  await assert.rejects(value.project(snapshot(1)), (error) => {
    assert.equal(error.diagnostic.code, 'K9_SEMANTIC_PROVIDER_TIMEOUT')
    assert.equal(JSON.stringify(error.diagnostic).includes('secret'), false)
    return true
  })
  assert.equal(requestedTimeout, 120_000)
})

test('validates vector count, dimension consistency, bounds, and finite values', () => {
  assert.throws(
    () => validateEmbeddingVectors({ data: [{ index: 0, embedding: [1] }] }, 2),
    (error) => error.diagnostic.code === 'K9_SEMANTIC_VECTOR_COUNT_INVALID',
  )
  assert.throws(
    () => validateEmbeddingVectors({ data: [
      { index: 0, embedding: [1] }, { index: 1, embedding: [1, 2] },
    ] }, 2),
    (error) => error.diagnostic.code === 'K9_SEMANTIC_VECTOR_DIMENSION_INVALID',
  )
  assert.throws(
    () => validateEmbeddingVectors({ embeddings: [[]] }, 1),
    (error) => error.diagnostic.code === 'K9_SEMANTIC_VECTOR_DIMENSION_INVALID',
  )
  assert.throws(
    () => validateEmbeddingVectors({ embeddings: [[Number.NaN]] }, 1),
    (error) => error.diagnostic.code === 'K9_SEMANTIC_VECTOR_FINITE_INVALID',
  )
  assert.throws(
    () => validateEmbeddingVectors({ data: [
      { index: 1, embedding: [1] }, { index: 1, embedding: [2] },
    ] }, 2),
    (error) => error.diagnostic.code === 'K9_SEMANTIC_VECTOR_COUNT_INVALID',
  )
})

test('rejects a vector dimension change between provider batches before materialization', async () => {
  const persistence = fakePersistence()
  const embeddingProvider = provider(({ input }, call) => ({
    data: input.map((_, index) => ({
      index,
      embedding: call === 1 ? [index, 1] : [index, 1, 2],
    })),
  }))
  const { value } = projector({ persistence, provider: embeddingProvider })
  await assert.rejects(value.project(snapshot(33)), (error) => (
    error.diagnostic.code === 'K9_SEMANTIC_VECTOR_DIMENSION_INVALID'
  ))
  assert.equal(persistence.state.staged.size, 32)
  assert.equal(persistence.state.calls.some(([name]) => name === 'materialize'), false)
  assert.equal(persistence.state.calls.some(([name]) => name === 'activate'), false)
})

test('reports typed bounded generation-lock, materialization, and active-pointer failures', async () => {
  for (const [failure, code, forbidden] of [
    ['lock', 'K9_SEMANTIC_GENERATION_LOCK_FAILED', 'token'],
    ['materialize', 'K9_SEMANTIC_MATERIALIZATION_FAILED', 'URN'],
    ['pointer', 'K9_SEMANTIC_ACTIVE_POINTER_FAILED', 'database'],
  ]) {
    const persistence = fakePersistence({ failures: { [failure]: true } })
    const { value } = projector({ persistence })
    await assert.rejects(value.project(snapshot(1)), (error) => {
      assert.equal(error.diagnostic.code, code)
      const serialized = JSON.stringify(error.diagnostic)
      assert.ok(serialized.length < 300)
      assert.equal(serialized.includes(forbidden), false)
      return true
    })
    if (failure !== 'pointer') {
      assert.equal(persistence.state.calls.some(([name]) => name === 'activate'), false)
    }
  }
})

test('maps generation ownership loss to the bounded lock diagnostic', async () => {
  const persistence = fakePersistence({ failures: { ownership: true } })
  const embeddingProvider = provider(({ signal }) => new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(Object.assign(new Error('raw session detail'), {
      name: 'AbortError',
    })), { once: true })
  }))
  const { value } = projector({ persistence, provider: embeddingProvider })
  await assert.rejects(value.project(snapshot(1)), (error) => {
    assert.equal(error.diagnostic.code, 'K9_SEMANTIC_GENERATION_LOCK_FAILED')
    assert.equal(JSON.stringify(error.diagnostic).includes('session'), false)
    return true
  })
  assert.equal(persistence.state.calls.some(([name]) => name === 'activate'), false)
})

test('supports READY reuse and zero, partial, and full source changes', async () => {
  const readySource = snapshot(3)
  const readyPersistence = fakePersistence({ activeSnapshot: readySource.source_snapshot.source_snapshot_id })
  const ready = projector({ persistence: readyPersistence })
  assert.equal((await ready.value.project(readySource)).outcome, 'REUSED')
  assert.equal(ready.provider.calls.length, 0)
  assert.deepEqual(readyPersistence.state.calls.slice(0, 2).map(([name]) => name), ['lock', 'desired'])

  const zeroSource = snapshot(3, { snapshotId: '2'.repeat(64), changed: () => false })
  const zeroPersistence = fakePersistence({ activeDocuments: zeroSource.catalog_documents })
  const zero = projector({ persistence: zeroPersistence })
  const zeroResult = await zero.value.project(zeroSource)
  assert.deepEqual([zeroResult.outcome, zeroResult.embedded_count], ['ZERO_CHANGE', 0])
  assert.equal(zero.provider.calls.length, 0)

  const partialSource = snapshot(3, { snapshotId: '3'.repeat(64), changed: (index) => index === 2 })
  const partialPersistence = fakePersistence({ activeDocuments: partialSource.catalog_documents.slice(0, 2) })
  const partial = projector({ persistence: partialPersistence })
  const partialResult = await partial.value.project(partialSource)
  assert.deepEqual([partialResult.outcome, partialResult.embedded_count], ['PARTIAL_CHANGE', 1])

  const removalSource = snapshot(2, { snapshotId: '9'.repeat(64), changed: () => false })
  const removedDocument = {
    document_id: 'urn:li:dataset:(urn:li:dataPlatform:test,removed,PROD)',
    source_hash: 'e'.repeat(64),
  }
  const removalPersistence = fakePersistence({
    activeDocuments: [...removalSource.catalog_documents, removedDocument],
  })
  const removal = projector({ persistence: removalPersistence })
  const removalResult = await removal.value.project(removalSource)
  assert.deepEqual(
    [removalResult.outcome, removalResult.embedded_count, removalResult.removed_count],
    ['PARTIAL_CHANGE', 0, 1],
  )

  const full = projector()
  const fullResult = await full.value.project(snapshot(3, { snapshotId: '4'.repeat(64) }))
  assert.deepEqual([fullResult.outcome, fullResult.embedded_count], ['FULL_CHANGE', 3])
})

test('persists batch progress and resumes the same immutable snapshot without source callbacks', async () => {
  const source = snapshot(70, { snapshotId: '5'.repeat(64) })
  const persistence = fakePersistence()
  let interrupted = true
  const embeddingProvider = provider(({ input }, call) => {
    if (interrupted && call === 2) throw Object.assign(new Error('provider disconnected'), { code: 'ECONNRESET' })
    return { data: input.map((_, index) => ({ index, embedding: [index, 1] })) }
  })
  const progress = []
  const first = projector({ persistence, provider: embeddingProvider, onProgress: (item) => progress.push(item) })
  await assert.rejects(first.value.project(source), (error) => (
    error.diagnostic.code === 'K9_SEMANTIC_PROVIDER_CONNECTIVITY_FAILED'
  ))
  assert.equal(persistence.state.staged.size, 32)
  assert.equal(persistence.state.activeSnapshot, undefined)
  interrupted = false
  const callsBeforeRetry = embeddingProvider.calls.length
  const result = await first.value.project(source)
  assert.deepEqual([result.status, result.outcome, result.embedded_count], ['READY', 'FULL_CHANGE', 38])
  assert.equal(embeddingProvider.calls.length - callsBeforeRetry, 2)
  assert.deepEqual(
    persistence.state.calls.filter(([name]) => name === 'batch')
      .map(([, size, completed, , batchNumber, batchTotal]) => (
        [size, completed, batchNumber, batchTotal]
      )),
    [[32, 32, 1, 3], [32, 64, 2, 3], [6, 70, 3, 3]],
  )
  assert.ok(progress.some((item) => item.stage === 'EMBEDDING' && item.completed === 64))
  const callsAfterSuccess = embeddingProvider.calls.length
  assert.equal((await first.value.project(source)).outcome, 'REUSED')
  assert.equal(embeddingProvider.calls.length, callsAfterSuccess)
})

test('rejects non-prefix or conflicting immutable staged batches before provider reuse', async () => {
  const source = snapshot(70, { snapshotId: '8'.repeat(64) })
  const persistence = fakePersistence()
  persistence.state.staged.set(
    source.catalog_documents[32].document_id,
    source.catalog_documents[32].source_hash,
  )
  persistence.state.stagedBatchCount = 1
  persistence.state.stagedBatchTotal = 3
  const current = projector({ persistence })
  await assert.rejects(current.value.project(source), (error) => (
    error.diagnostic.code === 'K9_SEMANTIC_MATERIALIZATION_FAILED'
  ))
  assert.equal(current.provider.calls.length, 0)
})

test('retries active-pointer failure from staged vectors without another provider call', async () => {
  const failures = { pointer: true }
  const source = snapshot(40, { snapshotId: '7'.repeat(64) })
  const persistence = fakePersistence({ failures })
  const current = projector({ persistence })
  await assert.rejects(current.value.project(source), (error) => (
    error.diagnostic.code === 'K9_SEMANTIC_ACTIVE_POINTER_FAILED'
  ))
  assert.equal(current.provider.calls.length, 2)
  assert.equal(persistence.state.activeSnapshot, undefined)
  failures.pointer = false
  const result = await current.value.project(source)
  assert.deepEqual([result.status, result.embedded_count], ['READY', 0])
  assert.equal(current.provider.calls.length, 2)
  assert.equal(persistence.state.activeSnapshot, source.source_snapshot.source_snapshot_id)
})

test('activates only after every batch and full materialization succeed for 2000+ documents', async () => {
  const source = snapshot(2_003, { snapshotId: '6'.repeat(64) })
  const persistence = fakePersistence()
  const { value, provider: embeddingProvider } = projector({ persistence })
  const result = await value.project(source)
  assert.deepEqual({
    status: result.status,
    outcome: result.outcome,
    documents: result.document_count,
    embedded: result.embedded_count,
    batches: result.batches_completed,
  }, {
    status: 'READY', outcome: 'FULL_CHANGE', documents: 2_003, embedded: 2_003, batches: 63,
  })
  assert.equal(embeddingProvider.calls.length, 63)
  const operations = persistence.state.calls.map(([name]) => name)
  assert.ok(operations.lastIndexOf('batch') < operations.indexOf('materialize'))
  assert.ok(operations.indexOf('materialize') < operations.indexOf('activate'))
  assert.equal(persistence.state.activeSnapshot, source.source_snapshot.source_snapshot_id)
})
