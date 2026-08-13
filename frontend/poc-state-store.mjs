/* global process, structuredClone */
import pg from 'pg'
import { createClient } from 'redis'

const { Pool } = pg

export function createPocStateStore({ databasePool } = {}) {
  const databaseUrl = process.env.POC_DATABASE_URL?.trim()
  const databaseHost = process.env.POC_POSTGRES_HOST?.trim()
  const databaseConfigured = Boolean(databasePool || databaseUrl || databaseHost)
  const redisUrl = process.env.POC_REDIS_URL?.trim()
  const memory = new Map()
  const memoryCatalogEmbeddings = new Map()
  let pool = databasePool
  let redis
  let startingDatabase
  let startingRedis

  async function startDatabase() {
    if (!databaseConfigured) return
    if (startingDatabase) return startingDatabase
    startingDatabase = (async () => {
      if (!pool) {
        pool = new Pool(databaseUrl ? {
          connectionString: databaseUrl, max: 4, idleTimeoutMillis: 30_000,
        } : {
          host: databaseHost,
          port: Number(process.env.POC_POSTGRES_PORT || 5432),
          database: process.env.POC_POSTGRES_DB?.trim() || 'datariver_poc',
          user: process.env.POC_POSTGRES_USER?.trim() || 'datariver_poc',
          password: process.env.POC_POSTGRES_PASSWORD || undefined,
          max: 4,
          idleTimeoutMillis: 30_000,
        })
      }
      await pool.query(`
        CREATE TABLE IF NOT EXISTS poc_state (
          scope text PRIMARY KEY,
          value jsonb NOT NULL,
          version bigint NOT NULL DEFAULT 1,
          updated_at timestamptz NOT NULL DEFAULT now()
        )
      `)
      await pool.query(`
        CREATE TABLE IF NOT EXISTS poc_catalog_embedding (
          binding_hash char(64) NOT NULL,
          asset_urn text NOT NULL,
          source_hash char(64) NOT NULL,
          source_generation char(64) NOT NULL,
          content_text text NOT NULL,
          metadata jsonb NOT NULL,
          embedding vector NOT NULL,
          updated_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (binding_hash, asset_urn),
          CONSTRAINT ck_poc_catalog_embedding_dimension
            CHECK (vector_dims(embedding) BETWEEN 1 AND 4096)
        )
      `)
    })()
    try {
      await startingDatabase
    } catch (error) {
      startingDatabase = undefined
      if (!databasePool) {
        await Promise.allSettled([pool?.end()])
        pool = undefined
      }
      throw error
    }
  }

  async function startRedis() {
    if (!redisUrl || redis) return
    if (startingRedis) return startingRedis
    startingRedis = (async () => {
      const client = createClient({
        url: redisUrl,
        socket: { reconnectStrategy: false },
      })
      client.on('error', () => undefined)
      try {
        await client.connect()
        redis = client
      } catch {
        if (client.isOpen) client.destroy()
      }
    })()
    try {
      await startingRedis
    } finally {
      startingRedis = undefined
    }
  }

  async function read(scope) {
    await startDatabase()
    if (pool) {
      const result = await pool.query('SELECT value, version FROM poc_state WHERE scope = $1', [scope])
      if (result.rows[0]) return { value: result.rows[0].value, version: Number(result.rows[0].version) }
    }
    return memory.has(scope) ? memory.get(scope) : { value: null, version: 0 }
  }

  async function write(scope, value) {
    await startDatabase()
    if (pool) {
      const result = await pool.query(`
        INSERT INTO poc_state (scope, value) VALUES ($1, $2::jsonb)
        ON CONFLICT (scope) DO UPDATE
          SET value = EXCLUDED.value, version = poc_state.version + 1, updated_at = now()
        RETURNING version
      `, [scope, JSON.stringify(value)])
      return Number(result.rows[0].version)
    }
    const version = (memory.get(scope)?.version ?? 0) + 1
    memory.set(scope, { value, version })
    return version
  }

  async function cacheGet(key) {
    await startRedis()
    if (!redis) return undefined
    const value = await redis.get(`datariver:poc:cache:${key}`)
    return value ? JSON.parse(value) : undefined
  }

  async function cacheSet(key, value, ttlSeconds) {
    await startRedis()
    if (!redis) return
    await redis.set(`datariver:poc:cache:${key}`, JSON.stringify(value), { EX: ttlSeconds })
  }

  async function cacheDelete(key) {
    await startRedis()
    if (!redis) return
    await redis.del(`datariver:poc:cache:${key}`)
  }

  async function catalogEmbeddingHashes(bindingHash) {
    await startDatabase()
    const sourceGeneration = await catalogEmbeddingActiveGeneration(bindingHash)
    if (!sourceGeneration) return new Map()
    if (pool) {
      const result = await pool.query(
        `SELECT asset_urn, source_hash FROM poc_catalog_embedding
         WHERE binding_hash = $1 AND source_generation = $2`,
        [bindingHash, sourceGeneration],
      )
      return new Map(result.rows.map((row) => [row.asset_urn, row.source_hash]))
    }
    return new Map([...memoryCatalogEmbeddings.values()]
      .filter((record) => record.bindingHash === bindingHash && record.sourceGeneration === sourceGeneration)
      .map((record) => [record.assetUrn, record.sourceHash]))
  }

  async function catalogEmbeddingProfileCoverage(bindingHash, projectionScope) {
    await startDatabase()
    const sourceGeneration = await catalogEmbeddingActiveGeneration(bindingHash)
    if (!sourceGeneration) return []
    if (pool) {
      const result = await pool.query(`
        SELECT
          COALESCE(NULLIF(embedding.metadata->>'platform', ''), 'unknown') AS platform,
          count(*)::int AS asset_count,
          count(*) FILTER (WHERE (embedding.metadata->'quality') ? 'rowCount')::int AS row_count_available,
          count(*) FILTER (WHERE (embedding.metadata->'quality') ? 'sizeInBytes')::int AS size_bytes_available,
          count(*) FILTER (WHERE NULLIF(embedding.metadata->>'created_at', '') IS NOT NULL)::int AS created_at_available,
          count(*) FILTER (
            WHERE COALESCE((embedding.metadata->>'schema_fields_total')::int, 0) > 0
          )::int AS schema_available,
          max(embedding.updated_at) AS observed_at
        FROM poc_catalog_embedding AS embedding
        JOIN poc_state AS current_projection ON current_projection.scope = $3
        JOIN poc_state AS active_generation ON active_generation.scope = $4
        WHERE embedding.binding_hash = $1
          AND embedding.source_generation = $2
          AND current_projection.value->>'source_generation' = $2
          AND active_generation.value->>'source_generation' = $2
        GROUP BY COALESCE(NULLIF(embedding.metadata->>'platform', ''), 'unknown')
        ORDER BY platform
      `, [
        bindingHash,
        sourceGeneration,
        projectionScope,
        catalogEmbeddingActiveScope(bindingHash),
      ])
      return result.rows.map((row) => ({
        platform: row.platform,
        asset_count: Number(row.asset_count),
        row_count_available: Number(row.row_count_available),
        size_bytes_available: Number(row.size_bytes_available),
        created_at_available: Number(row.created_at_available),
        schema_available: Number(row.schema_available),
        observed_at: row.observed_at instanceof Date ? row.observed_at.toISOString() : row.observed_at,
      }))
    }
    if (memory.get(projectionScope)?.value?.source_generation !== sourceGeneration) return []
    const grouped = new Map()
    for (const record of memoryCatalogEmbeddings.values()) {
      if (record.bindingHash !== bindingHash || record.sourceGeneration !== sourceGeneration) continue
      const metadata = record.metadata && typeof record.metadata === 'object' ? record.metadata : {}
      const platform = typeof metadata.platform === 'string' && metadata.platform ? metadata.platform : 'unknown'
      const current = grouped.get(platform) || {
        platform, asset_count: 0, row_count_available: 0, size_bytes_available: 0,
        created_at_available: 0, schema_available: 0, observed_at: new Date().toISOString(),
      }
      current.asset_count += 1
      if (Number.isInteger(metadata.quality?.rowCount)) current.row_count_available += 1
      if (Number.isInteger(metadata.quality?.sizeInBytes)) current.size_bytes_available += 1
      if (metadata.created_at) current.created_at_available += 1
      if (Number.isInteger(metadata.schema_fields_total) && metadata.schema_fields_total > 0) current.schema_available += 1
      grouped.set(platform, current)
    }
    return [...grouped.values()].sort((left, right) => left.platform.localeCompare(right.platform))
  }

  function catalogEmbeddingActiveScope(bindingHash) {
    return `catalog-embedding-active-v1:${bindingHash}`
  }

  async function catalogEmbeddingActiveGeneration(bindingHash) {
    await startDatabase()
    if (pool) {
      const result = await pool.query('SELECT value FROM poc_state WHERE scope = $1', [
        catalogEmbeddingActiveScope(bindingHash),
      ])
      const value = result.rows[0]?.value
      return value?.projection_version === 1
        && value.binding_hash === bindingHash
        && typeof value.source_generation === 'string'
        ? value.source_generation
        : undefined
    }
    const value = memory.get(catalogEmbeddingActiveScope(bindingHash))?.value
    return value?.projection_version === 1
      && value.binding_hash === bindingHash
      && typeof value.source_generation === 'string'
      ? value.source_generation
      : undefined
  }

  async function replaceCatalogEmbeddingGeneration(
    bindingHash,
    projectionScope,
    sourceGeneration,
    records,
    assetUrns,
  ) {
    for (const record of records) vectorLiteral(record.embedding)
    await startDatabase()
    const activeValue = {
      projection_version: 1,
      binding_hash: bindingHash,
      source_generation: sourceGeneration,
    }
    if (pool) {
      const client = await pool.connect()
      try {
        await client.query('BEGIN')
        const projection = await client.query(
          'SELECT value FROM poc_state WHERE scope = $1 FOR UPDATE',
          [projectionScope],
        )
        if (projection.rows[0]?.value?.source_generation !== sourceGeneration) {
          throw new Error('The Catalog projection changed while its Embedding generation was being built.')
        }
        for (const record of records) {
          await client.query(`
            INSERT INTO poc_catalog_embedding (
              binding_hash, asset_urn, source_hash, source_generation,
              content_text, metadata, embedding
            ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::vector)
            ON CONFLICT (binding_hash, asset_urn) DO UPDATE SET
              source_hash = EXCLUDED.source_hash,
              source_generation = EXCLUDED.source_generation,
              content_text = EXCLUDED.content_text,
              metadata = EXCLUDED.metadata,
              embedding = EXCLUDED.embedding,
              updated_at = now()
          `, [
            record.bindingHash,
            record.assetUrn,
            record.sourceHash,
            record.sourceGeneration,
            record.contentText,
            JSON.stringify(record.metadata),
            vectorLiteral(record.embedding),
          ])
        }
        await client.query(`
          UPDATE poc_catalog_embedding
          SET source_generation = $2, updated_at = now()
          WHERE binding_hash = $1 AND asset_urn = ANY($3::text[])
        `, [bindingHash, sourceGeneration, assetUrns])
        await client.query(
          'DELETE FROM poc_catalog_embedding WHERE binding_hash = $1 AND source_generation <> $2',
          [bindingHash, sourceGeneration],
        )
        await client.query(`
          INSERT INTO poc_state (scope, value) VALUES ($1, $2::jsonb)
          ON CONFLICT (scope) DO UPDATE
            SET value = EXCLUDED.value, version = poc_state.version + 1, updated_at = now()
        `, [catalogEmbeddingActiveScope(bindingHash), JSON.stringify(activeValue)])
        await client.query('COMMIT')
      } catch (error) {
        await client.query('ROLLBACK')
        throw error
      } finally {
        client.release()
      }
      return
    }
    if (memory.get(projectionScope)?.value?.source_generation !== sourceGeneration) {
      throw new Error('The Catalog projection changed while its Embedding generation was being built.')
    }
    const replacement = new Map(memoryCatalogEmbeddings)
    for (const record of records) {
      replacement.set(`${record.bindingHash}:${record.assetUrn}`, structuredClone(record))
    }
    const retained = new Set(assetUrns)
    for (const [key, record] of replacement) {
      if (record.bindingHash !== bindingHash) continue
      if (retained.has(record.assetUrn)) {
        record.sourceGeneration = sourceGeneration
      } else {
        replacement.delete(key)
      }
    }
    memoryCatalogEmbeddings.clear()
    for (const [key, record] of replacement) memoryCatalogEmbeddings.set(key, record)
    const activeScope = catalogEmbeddingActiveScope(bindingHash)
    memory.set(activeScope, {
      value: activeValue,
      version: (memory.get(activeScope)?.version ?? 0) + 1,
    })
  }

  async function searchCatalogEmbeddings(bindingHash, projectionScope, sourceGeneration, embedding, limit) {
    await startDatabase()
    const boundedLimit = Math.max(1, Math.min(Number(limit) || 1, 20))
    if (pool) {
      const vector = vectorLiteral(embedding)
      const result = await pool.query(`
        SELECT catalog_embedding.asset_urn, catalog_embedding.content_text, catalog_embedding.metadata,
          1 - (catalog_embedding.embedding <=> $5::vector) AS similarity
        FROM poc_catalog_embedding AS catalog_embedding
        JOIN poc_state AS current_projection ON current_projection.scope = $3
        JOIN poc_state AS active_generation ON active_generation.scope = $4
        WHERE catalog_embedding.binding_hash = $1
          AND catalog_embedding.source_generation = $2
          AND current_projection.value->>'source_generation' = $2
          AND active_generation.value->>'source_generation' = $2
          AND vector_dims(catalog_embedding.embedding) = vector_dims($5::vector)
        ORDER BY catalog_embedding.embedding <=> $5::vector, catalog_embedding.asset_urn
        LIMIT $6
      `, [
        bindingHash,
        sourceGeneration,
        projectionScope,
        catalogEmbeddingActiveScope(bindingHash),
        vector,
        boundedLimit,
      ])
      return result.rows.map((row) => ({
        assetUrn: row.asset_urn,
        contentText: row.content_text,
        metadata: row.metadata,
        similarity: Number(row.similarity),
      }))
    }
    if (memory.get(projectionScope)?.value?.source_generation !== sourceGeneration
      || await catalogEmbeddingActiveGeneration(bindingHash) !== sourceGeneration) return []
    return [...memoryCatalogEmbeddings.values()]
      .filter((record) => record.bindingHash === bindingHash
        && record.sourceGeneration === sourceGeneration
        && record.embedding.length === embedding.length)
      .map((record) => ({
        assetUrn: record.assetUrn,
        contentText: record.contentText,
        metadata: structuredClone(record.metadata),
        similarity: cosineSimilarity(record.embedding, embedding),
      }))
      .sort((left, right) => right.similarity - left.similarity || left.assetUrn.localeCompare(right.assetUrn))
      .slice(0, boundedLimit)
  }

  return {
    read,
    write,
    cacheGet,
    cacheSet,
    cacheDelete,
    catalogEmbeddingHashes,
    catalogEmbeddingProfileCoverage,
    catalogEmbeddingActiveGeneration,
    replaceCatalogEmbeddingGeneration,
    searchCatalogEmbeddings,
    configured: { postgres: databaseConfigured, redis: Boolean(redisUrl) },
  }
}

function vectorLiteral(values) {
  if (!Array.isArray(values) || values.length < 1 || values.length > 4096
    || values.some((value) => typeof value !== 'number' || !Number.isFinite(value))) {
    throw new Error('The catalog embedding is invalid or outside the supported dimension bound.')
  }
  return `[${values.join(',')}]`
}

function cosineSimilarity(left, right) {
  let dot = 0
  let leftMagnitude = 0
  let rightMagnitude = 0
  for (let index = 0; index < left.length; index += 1) {
    dot += left[index] * right[index]
    leftMagnitude += left[index] ** 2
    rightMagnitude += right[index] ** 2
  }
  if (!leftMagnitude || !rightMagnitude) return 0
  return dot / (Math.sqrt(leftMagnitude) * Math.sqrt(rightMagnitude))
}
