/* global process, structuredClone */
import pg from 'pg'
import { createClient } from 'redis'

const { Pool } = pg

export function createPocStateStore() {
  const databaseUrl = process.env.POC_DATABASE_URL?.trim()
  const databaseHost = process.env.POC_POSTGRES_HOST?.trim()
  const databaseConfigured = Boolean(databaseUrl || databaseHost)
  const redisUrl = process.env.POC_REDIS_URL?.trim()
  const memory = new Map()
  const memoryCatalogEmbeddings = new Map()
  let pool
  let redis
  let starting

  async function start() {
    if (starting) return starting
    starting = (async () => {
      if (databaseConfigured) {
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
      }
      if (redisUrl) {
        redis = createClient({ url: redisUrl })
        redis.on('error', () => undefined)
        try {
          await redis.connect()
        } catch {
          redis.destroy()
          redis = undefined
        }
      }
    })()
    try {
      await starting
    } catch (error) {
      starting = undefined
      await Promise.allSettled([pool?.end(), redis?.quit()])
      pool = undefined
      redis = undefined
      throw error
    }
  }

  async function read(scope) {
    await start()
    if (pool) {
      const result = await pool.query('SELECT value, version FROM poc_state WHERE scope = $1', [scope])
      if (result.rows[0]) return { value: result.rows[0].value, version: Number(result.rows[0].version) }
    }
    return memory.has(scope) ? memory.get(scope) : { value: null, version: 0 }
  }

  async function write(scope, value) {
    await start()
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
    await start()
    if (!redis) return undefined
    const value = await redis.get(`datariver:poc:cache:${key}`)
    return value ? JSON.parse(value) : undefined
  }

  async function cacheSet(key, value, ttlSeconds) {
    await start()
    if (!redis) return
    await redis.set(`datariver:poc:cache:${key}`, JSON.stringify(value), { EX: ttlSeconds })
  }

  async function cacheDelete(key) {
    await start()
    if (!redis) return
    await redis.del(`datariver:poc:cache:${key}`)
  }

  async function catalogEmbeddingHashes(bindingHash) {
    await start()
    if (pool) {
      const result = await pool.query(
        'SELECT asset_urn, source_hash FROM poc_catalog_embedding WHERE binding_hash = $1',
        [bindingHash],
      )
      return new Map(result.rows.map((row) => [row.asset_urn, row.source_hash]))
    }
    return new Map([...memoryCatalogEmbeddings.values()]
      .filter((record) => record.bindingHash === bindingHash)
      .map((record) => [record.assetUrn, record.sourceHash]))
  }

  async function upsertCatalogEmbeddings(records) {
    if (!records.length) return
    await start()
    if (pool) {
      const client = await pool.connect()
      try {
        await client.query('BEGIN')
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
        await client.query('COMMIT')
      } catch (error) {
        await client.query('ROLLBACK')
        throw error
      } finally {
        client.release()
      }
      return
    }
    for (const record of records) {
      memoryCatalogEmbeddings.set(`${record.bindingHash}:${record.assetUrn}`, structuredClone(record))
    }
  }

  async function deleteCatalogEmbeddingsExceptGeneration(bindingHash, sourceGeneration) {
    await start()
    if (pool) {
      await pool.query(
        'DELETE FROM poc_catalog_embedding WHERE binding_hash = $1 AND source_generation <> $2',
        [bindingHash, sourceGeneration],
      )
      return
    }
    for (const [key, record] of memoryCatalogEmbeddings) {
      if (record.bindingHash === bindingHash && record.sourceGeneration !== sourceGeneration) {
        memoryCatalogEmbeddings.delete(key)
      }
    }
  }

  async function retainCatalogEmbeddingGeneration(bindingHash, sourceGeneration, assetUrns) {
    await start()
    if (pool) {
      await pool.query(`
        UPDATE poc_catalog_embedding
        SET source_generation = $2, updated_at = now()
        WHERE binding_hash = $1 AND asset_urn = ANY($3::text[])
      `, [bindingHash, sourceGeneration, assetUrns])
      return
    }
    const retained = new Set(assetUrns)
    for (const record of memoryCatalogEmbeddings.values()) {
      if (record.bindingHash === bindingHash && retained.has(record.assetUrn)) {
        record.sourceGeneration = sourceGeneration
      }
    }
  }

  async function searchCatalogEmbeddings(bindingHash, embedding, limit) {
    await start()
    const boundedLimit = Math.max(1, Math.min(Number(limit) || 1, 20))
    if (pool) {
      const vector = vectorLiteral(embedding)
      const result = await pool.query(`
        SELECT asset_urn, content_text, metadata,
          1 - (embedding <=> $2::vector) AS similarity
        FROM poc_catalog_embedding
        WHERE binding_hash = $1
          AND vector_dims(embedding) = vector_dims($2::vector)
        ORDER BY embedding <=> $2::vector, asset_urn
        LIMIT $3
      `, [bindingHash, vector, boundedLimit])
      return result.rows.map((row) => ({
        assetUrn: row.asset_urn,
        contentText: row.content_text,
        metadata: row.metadata,
        similarity: Number(row.similarity),
      }))
    }
    return [...memoryCatalogEmbeddings.values()]
      .filter((record) => record.bindingHash === bindingHash && record.embedding.length === embedding.length)
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
    upsertCatalogEmbeddings,
    retainCatalogEmbeddingGeneration,
    deleteCatalogEmbeddingsExceptGeneration,
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
