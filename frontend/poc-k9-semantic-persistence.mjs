/* global AbortController */
const HASH = /^[0-9a-f]{64}$/

function contractError(code, message) {
  return Object.assign(new Error(message), { code })
}

function hash(value, name) {
  if (typeof value !== 'string' || !HASH.test(value)) {
    throw contractError('K9_SEMANTIC_PERSISTENCE_INVALID', `${name} is invalid.`)
  }
  return value
}

export function createK9SemanticPersistenceV2({ requireDatabase, lifecycle }) {
  if (typeof requireDatabase !== 'function' || !lifecycle) {
    throw new TypeError('K9 semantic persistence requires PostgreSQL and lifecycle persistence.')
  }

  async function withProjectorGenerationLock(target, operation) {
    const sourceSnapshotId = hash(target?.source_snapshot_id, 'source_snapshot_id')
    const bindingHash = hash(target?.binding_hash, 'binding_hash')
    if (typeof operation !== 'function') throw new TypeError('The K9 semantic lock operation is invalid.')
    const pool = await requireDatabase()
    const client = await pool.connect()
    const ownership = new AbortController()
    const onError = (error) => ownership.abort(error)
    client.on?.('error', onError)
    try {
      await client.query('SELECT pg_advisory_lock(hashtextextended($1, 0))', [
        `k9-semantic-projector-v2:${sourceSnapshotId}:${bindingHash}`,
      ])
      return await operation(ownership.signal)
    } finally {
      await client.query('SELECT pg_advisory_unlock(hashtextextended($1, 0))', [
        `k9-semantic-projector-v2:${sourceSnapshotId}:${bindingHash}`,
      ]).catch(() => undefined)
      client.off?.('error', onError)
      client.release()
    }
  }

  async function readProjectorState() {
    const state = await lifecycle.readLifecycle()
    return state && {
      status: state.status,
      desired_snapshot_id: state.desired_snapshot_id,
      active_snapshot_id: state.active_snapshot_id,
      version: Number(state.version),
    }
  }

  async function setDesiredSnapshot(target) {
    const sourceSnapshotId = hash(target?.source_snapshot_id, 'source_snapshot_id')
    const state = await lifecycle.readLifecycle()
    if (!state || state.desired_snapshot_id !== sourceSnapshotId) {
      throw contractError('K9_LIFECYCLE_HEAD_MISMATCH', 'The semantic target is not the durable desired source snapshot.')
    }
    return { source_snapshot_id: sourceSnapshotId, version: Number(state.version) }
  }

  async function readActiveDocumentHashes(identity) {
    const bindingHash = hash(identity?.output_binding_hash, 'output_binding_hash')
    const pool = await requireDatabase()
    const pointer = await pool.query('SELECT value FROM poc_state WHERE scope = $1', [
      `catalog-embedding-active-v1:${bindingHash}`,
    ])
    const value = pointer.rows[0]?.value
    if (value?.binding_hash !== bindingHash || typeof value.source_generation !== 'string') {
      return { hashes: [] }
    }
    const rows = await pool.query(`
      SELECT asset_urn AS document_id, source_hash
      FROM poc_catalog_embedding
      WHERE binding_hash = $1 AND source_generation = $2
      ORDER BY asset_urn
    `, [bindingHash, value.source_generation])
    return {
      hashes: rows.rows,
      source_snapshot_id: value.source_snapshot_id ?? null,
      semantic_input_contract: value.semantic_input_contract ?? null,
      materialization_hash: value.materialization_hash ?? null,
      pooling_contract: value.pooling_contract ?? null,
    }
  }

  async function readLegacyStagedDocumentHashes(target) {
    const sourceSnapshotId = hash(target?.source_snapshot_id, 'source_snapshot_id')
    const legacyBindingHash = hash(target?.legacy_binding_hash, 'legacy_binding_hash')
    const materializationHash = hash(target?.binding_hash, 'binding_hash')
    if (legacyBindingHash === materializationHash) return { hashes: [] }
    const pool = await requireDatabase()
    const rows = await pool.query(`
      SELECT document_id, source_hash
      FROM poc_k9_semantic_staging_v2
      WHERE source_snapshot_id = $1 AND binding_hash = $2
      ORDER BY batch_number, document_id
    `, [sourceSnapshotId, legacyBindingHash])
    return { hashes: rows.rows }
  }

  async function readStagedDocumentHashes(target) {
    const sourceSnapshotId = hash(target?.source_snapshot_id, 'source_snapshot_id')
    const bindingHash = hash(target?.binding_hash, 'binding_hash')
    const pool = await requireDatabase()
    const [batches, documents] = await Promise.all([
      pool.query(`
        SELECT batch_number, batch_total, document_count
        FROM poc_k9_semantic_batches_v2
        WHERE source_snapshot_id = $1 AND binding_hash = $2
        ORDER BY batch_number
      `, [sourceSnapshotId, bindingHash]),
      pool.query(`
        SELECT document_id, source_hash, batch_number, vector_dims(embedding)::integer AS vector_dimension
        FROM poc_k9_semantic_staging_v2
        WHERE source_snapshot_id = $1 AND binding_hash = $2
        ORDER BY batch_number, document_id
      `, [sourceSnapshotId, bindingHash]),
    ])
    const batchCount = batches.rows.length
    const batchTotal = batchCount === 0 ? 0 : Number(batches.rows[0].batch_total)
    const dimension = documents.rows.length === 0 ? undefined : Number(documents.rows[0].vector_dimension)
    if (batches.rows.some((row, index) => Number(row.batch_number) !== index + 1
      || Number(row.batch_total) !== batchTotal
      || Number(row.document_count) !== documents.rows.filter((item) => Number(item.batch_number) === index + 1).length)
      || documents.rows.some((row) => Number(row.vector_dimension) !== dimension)) {
      throw contractError('K9_SEMANTIC_STAGING_DRIFT', 'Semantic staging batch evidence is not contiguous or dimension-consistent.')
    }
    return {
      hashes: documents.rows.map(({ document_id, source_hash }) => ({ document_id, source_hash })),
      vector_dimension: dimension,
      batch_count: batchCount,
      batch_total: batchTotal,
    }
  }

  async function writeEmbeddingBatch(batch) {
    return lifecycle.stageSemanticBatch({
      source_snapshot_id: batch.source_snapshot_id,
      binding_hash: batch.binding_hash,
      batch_number: batch.batch_number,
      batch_total: batch.batch_total,
      documents: batch.records.map((record) => ({
        document_id: record.document_id,
        source_hash: record.source_hash,
        embedding: record.embedding,
      })),
    })
  }

  async function persistDesiredManifest(target) {
    if (!Array.isArray(target.documents) || target.documents.length !== target.document_count) {
      throw contractError('K9_SEMANTIC_MANIFEST_INVALID', 'The full desired semantic manifest is incomplete.')
    }
    return lifecycle.persistSemanticDesiredManifest({
      source_snapshot_id: target.source_snapshot_id,
      binding_hash: target.binding_hash,
      documents: target.documents,
    })
  }

  async function activateSnapshot(target) {
    return lifecycle.activateSemanticSnapshot({
      source_snapshot_id: target.source_snapshot_id,
      binding_hash: target.binding_hash,
      output_binding_hash: target.output_binding_hash,
      legacy_binding_hash: target.legacy_binding_hash,
      materialization_contract: target.materialization_contract,
      semantic_input_contract: target.semantic_input_contract,
      pooling_contract: target.pooling_contract,
      maximum_segment_bytes: target.maximum_segment_bytes,
      expected_desired_count: target.document_count,
      expected_changed_count: target.staged_count,
      expected_batch_count: target.batch_total,
    })
  }

  return Object.freeze({
    withProjectorGenerationLock,
    readProjectorState,
    setDesiredSnapshot,
    readActiveDocumentHashes,
    readLegacyStagedDocumentHashes,
    readStagedDocumentHashes,
    writeEmbeddingBatch,
    persistDesiredManifest,
    activateSnapshot,
  })
}
