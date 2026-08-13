/* global process, structuredClone */
import { createHash } from 'node:crypto'
import { TextEncoder } from 'node:util'
import pg from 'pg'
import { createClient } from 'redis'

const { Pool } = pg

const CHANGE_HISTORY_ACCESS_SCOPE = 'change-history-access-v1'
const CHANGE_HISTORY_ACCESS_SCOPES = [CHANGE_HISTORY_ACCESS_SCOPE, 'core']
const PROTECTED_CORE_ACCESS_FIELDS = [
  'adminMemberships',
  'adminSystems',
  'adminSystemAssignees',
  'adminSystemSchemaScopes',
]

const CHANGE_HISTORY_SCHEMA = [
  `
    CREATE TABLE IF NOT EXISTS poc_change_history_sources (
      source_identity_hash char(64) PRIMARY KEY,
      provider_name text NOT NULL,
      provider_version text NOT NULL,
      schema_contract_hash char(64) NOT NULL,
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      CONSTRAINT ck_poc_change_history_source_identity
        CHECK (source_identity_hash ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_poc_change_history_source_schema
        CHECK (schema_contract_hash ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_poc_change_history_source_provider
        CHECK (char_length(provider_name) BETWEEN 1 AND 100
          AND char_length(provider_version) BETWEEN 1 AND 100)
    )
  `,
  `
    CREATE TABLE IF NOT EXISTS poc_change_history_ledger_events (
      event_identity char(64) PRIMARY KEY,
      event_hash char(64) NOT NULL,
      source_identity_hash char(64) NOT NULL REFERENCES poc_change_history_sources(source_identity_hash),
      source_event_identity char(64) NOT NULL,
      normalized_change_transaction_id char(64) NOT NULL,
      deterministic_ordinal integer NOT NULL,
      topic_contract text NOT NULL,
      source_partition integer NOT NULL,
      source_offset bigint NOT NULL,
      asset_urn text NOT NULL,
      normalized_entity_key text NOT NULL,
      category text NOT NULL,
      source_aspect text NOT NULL,
      operation text NOT NULL,
      before_data jsonb,
      after_data jsonb,
      before_hash char(64),
      after_hash char(64),
      actor_ref text,
      source_occurred_at timestamptz,
      detected_at timestamptz NOT NULL,
      captured_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      UNIQUE (source_identity_hash, source_event_identity, deterministic_ordinal),
      CONSTRAINT ck_poc_change_history_ledger_hashes CHECK (
        event_identity ~ '^[0-9a-f]{64}$'
        AND event_hash ~ '^[0-9a-f]{64}$'
        AND source_event_identity ~ '^[0-9a-f]{64}$'
        AND normalized_change_transaction_id ~ '^[0-9a-f]{64}$'
        AND (before_hash IS NULL OR before_hash ~ '^[0-9a-f]{64}$')
        AND (after_hash IS NULL OR after_hash ~ '^[0-9a-f]{64}$')
      ),
      CONSTRAINT ck_poc_change_history_ledger_position
        CHECK (source_partition >= 0 AND source_offset >= 0 AND deterministic_ordinal >= 0),
      CONSTRAINT ck_poc_change_history_ledger_category CHECK (
        (category = 'TECHNICAL_SCHEMA' AND source_aspect = 'schemaMetadata')
        OR (category = 'DOCUMENTATION' AND source_aspect IN ('datasetProperties', 'editableSchemaMetadata'))
        OR (category = 'TAG' AND source_aspect = 'globalTags')
        OR (category = 'GLOSSARY_TERM' AND source_aspect = 'glossaryTerms')
        OR (category = 'OWNERSHIP' AND source_aspect = 'ownership')
      ),
      CONSTRAINT ck_poc_change_history_ledger_operation
        CHECK (operation IN ('CREATE', 'UPDATE', 'UPSERT', 'DELETE', 'ADD', 'REMOVE')),
      CONSTRAINT ck_poc_change_history_ledger_bounds CHECK (
        char_length(topic_contract) BETWEEN 1 AND 255
        AND char_length(asset_urn) BETWEEN 1 AND 4096
        AND char_length(normalized_entity_key) BETWEEN 1 AND 1000
        AND (actor_ref IS NULL OR char_length(actor_ref) BETWEEN 1 AND 1000)
        AND (before_data IS NULL OR (jsonb_typeof(before_data) = 'object'
          AND octet_length(before_data::text) <= 16384
          AND NOT jsonb_path_exists(before_data, '$.** ? (@.type() == "object").keyvalue() ? (@.key == "raw" || @.key == "payload" || @.key == "aspect" || @.key == "schemaMetadata" || @.key == "previousAspectValue")')))
        AND (after_data IS NULL OR (jsonb_typeof(after_data) = 'object'
          AND octet_length(after_data::text) <= 16384
          AND NOT jsonb_path_exists(after_data, '$.** ? (@.type() == "object").keyvalue() ? (@.key == "raw" || @.key == "payload" || @.key == "aspect" || @.key == "schemaMetadata" || @.key == "previousAspectValue")')))
      )
    )
  `,
  `
    CREATE UNIQUE INDEX IF NOT EXISTS uq_poc_change_history_source_position_ordinal
      ON poc_change_history_ledger_events (
        source_identity_hash, topic_contract, source_partition, source_offset, deterministic_ordinal
      )
  `,
  `
    CREATE INDEX IF NOT EXISTS ix_poc_change_history_ledger_asset
      ON poc_change_history_ledger_events (asset_urn, source_occurred_at DESC, event_identity DESC)
  `,
  `
    CREATE TABLE IF NOT EXISTS poc_change_history_checkpoints (
      source_identity_hash char(64) NOT NULL REFERENCES poc_change_history_sources(source_identity_hash),
      topic_contract text NOT NULL,
      source_partition integer NOT NULL,
      first_exact_offset bigint NOT NULL,
      next_offset bigint NOT NULL,
      last_contiguous_event_identity char(64),
      last_source_occurred_at timestamptz,
      last_captured_at timestamptz,
      version bigint NOT NULL DEFAULT 1,
      PRIMARY KEY (source_identity_hash, topic_contract, source_partition),
      CONSTRAINT ck_poc_change_history_checkpoint_position CHECK (
        source_partition >= 0 AND first_exact_offset >= 0 AND next_offset >= first_exact_offset
      ),
      CONSTRAINT ck_poc_change_history_checkpoint_event CHECK (
        last_contiguous_event_identity IS NULL
        OR last_contiguous_event_identity ~ '^[0-9a-f]{64}$'
      ),
      CONSTRAINT ck_poc_change_history_checkpoint_version CHECK (version > 0)
    )
  `,
  `
    CREATE TABLE IF NOT EXISTS poc_change_history_cr_link_events (
      link_event_identity char(64) PRIMARY KEY,
      event_hash char(64) NOT NULL,
      request_key_hash char(64) NOT NULL UNIQUE,
      request_hash char(64) NOT NULL,
      ledger_event_identity char(64) NOT NULL REFERENCES poc_change_history_ledger_events(event_identity),
      link_version bigint NOT NULL,
      link_kind text NOT NULL,
      action text NOT NULL,
      change_request_id text NOT NULL,
      change_request_round integer NOT NULL,
      prior_link_hash char(64),
      reason text NOT NULL,
      policy_hash char(64) NOT NULL,
      basis_hash char(64) NOT NULL,
      actor_ref text NOT NULL,
      occurred_at timestamptz NOT NULL,
      captured_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      UNIQUE (ledger_event_identity, link_version),
      UNIQUE (ledger_event_identity, event_hash),
      CONSTRAINT ck_poc_change_history_cr_link_hashes CHECK (
        link_event_identity ~ '^[0-9a-f]{64}$'
        AND event_hash ~ '^[0-9a-f]{64}$'
        AND request_key_hash ~ '^[0-9a-f]{64}$'
        AND request_hash ~ '^[0-9a-f]{64}$'
        AND (prior_link_hash IS NULL OR prior_link_hash ~ '^[0-9a-f]{64}$')
        AND policy_hash ~ '^[0-9a-f]{64}$'
        AND basis_hash ~ '^[0-9a-f]{64}$'
      ),
      CONSTRAINT ck_poc_change_history_cr_link_action CHECK (
        (link_kind = 'PRIMARY' AND action IN ('SET_PRIMARY', 'CLEAR_PRIMARY'))
        OR (link_kind = 'CANDIDATE' AND action IN ('ADD_CANDIDATE', 'REMOVE_CANDIDATE'))
      ),
      CONSTRAINT ck_poc_change_history_cr_link_bounds CHECK (
        link_version > 0 AND change_request_round > 0
        AND char_length(change_request_id) BETWEEN 1 AND 200
        AND char_length(reason) BETWEEN 1 AND 2000
        AND char_length(actor_ref) BETWEEN 1 AND 1000
      )
    )
  `,
  `
    CREATE INDEX IF NOT EXISTS ix_poc_change_history_cr_link_current
      ON poc_change_history_cr_link_events (ledger_event_identity, link_version DESC)
  `,
  `
    CREATE OR REPLACE FUNCTION poc_reject_change_history_mutation()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $function$
    BEGIN
      RAISE EXCEPTION 'POC change-history evidence is append-only';
    END
    $function$
  `,
  `
    DO $block$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_poc_change_history_ledger_append_only'
          AND tgrelid = 'poc_change_history_ledger_events'::regclass
      ) THEN
        CREATE TRIGGER trg_poc_change_history_ledger_append_only
          BEFORE UPDATE OR DELETE ON poc_change_history_ledger_events
          FOR EACH ROW EXECUTE FUNCTION poc_reject_change_history_mutation();
      END IF;
      IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_poc_change_history_cr_link_append_only'
          AND tgrelid = 'poc_change_history_cr_link_events'::regclass
      ) THEN
        CREATE TRIGGER trg_poc_change_history_cr_link_append_only
          BEFORE UPDATE OR DELETE ON poc_change_history_cr_link_events
          FOR EACH ROW EXECUTE FUNCTION poc_reject_change_history_mutation();
      END IF;
    END
    $block$
  `,
]

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
      for (const statement of CHANGE_HISTORY_SCHEMA) await pool.query(statement)
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
    if (scope === 'core') return writeCoreWithAccessFence(value)
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

  async function writeCoreWithAccessFence(value) {
    if (pool) {
      const client = await pool.connect()
      try {
        await client.query('BEGIN')
        await client.query(
          'SELECT pg_advisory_xact_lock(hashtextextended($1, 0))',
          [CHANGE_HISTORY_ACCESS_SCOPE],
        )
        const locked = await client.query(`
          SELECT scope, value, version FROM poc_state
          WHERE scope IN ($1, $2)
          ORDER BY scope
          FOR UPDATE
        `, CHANGE_HISTORY_ACCESS_SCOPES)
        const accessRow = locked.rows.find((row) => row.scope === CHANGE_HISTORY_ACCESS_SCOPE)
        const coreRow = locked.rows.find((row) => row.scope === 'core')
        const fencedValue = preserveProtectedCoreAccessFields(value, coreRow?.value, Boolean(accessRow))
        const result = await client.query(`
          INSERT INTO poc_state (scope, value) VALUES ('core', $1::jsonb)
          ON CONFLICT (scope) DO UPDATE
            SET value = EXCLUDED.value, version = poc_state.version + 1, updated_at = now()
          RETURNING version
        `, [JSON.stringify(fencedValue)])
        await client.query('COMMIT')
        return Number(result.rows[0].version)
      } catch (error) {
        await client.query('ROLLBACK')
        throw error
      } finally {
        client.release()
      }
    }
    const accessExists = memory.has(CHANGE_HISTORY_ACCESS_SCOPE)
    const currentCore = memory.get('core')?.value
    const fencedValue = preserveProtectedCoreAccessFields(value, currentCore, accessExists)
    const version = (memory.get('core')?.version ?? 0) + 1
    memory.set('core', { value: fencedValue, version })
    return version
  }

  async function readChangeHistoryAccess() {
    await startDatabase()
    if (pool) {
      const result = await pool.query(`
        SELECT scope, value, version FROM poc_state
        WHERE scope IN ($1, $2)
      `, CHANGE_HISTORY_ACCESS_SCOPES)
      return changeHistoryAccessSnapshot(result.rows)
    }
    return {
      access: memory.get(CHANGE_HISTORY_ACCESS_SCOPE) ?? { value: null, version: 0 },
      core: memory.get('core') ?? { value: null, version: 0 },
    }
  }

  async function writeChangeHistoryAccess({
    expectedAccessVersion,
    expectedCoreVersion,
    accessValue,
    coreValue,
  }) {
    requireNonnegativeInteger(expectedAccessVersion, 'expectedAccessVersion')
    requireNonnegativeInteger(expectedCoreVersion, 'expectedCoreVersion')
    await startDatabase()
    if (pool) {
      const client = await pool.connect()
      try {
        await client.query('BEGIN')
        await client.query(
          'SELECT pg_advisory_xact_lock(hashtextextended($1, 0))',
          [CHANGE_HISTORY_ACCESS_SCOPE],
        )
        const locked = await client.query(`
          SELECT scope, value, version FROM poc_state
          WHERE scope IN ($1, $2)
          ORDER BY scope
          FOR UPDATE
        `, CHANGE_HISTORY_ACCESS_SCOPES)
        const current = changeHistoryAccessSnapshot(locked.rows)
        assertAccessVersions(current, expectedAccessVersion, expectedCoreVersion)
        const accessWrite = await client.query(`
          INSERT INTO poc_state (scope, value) VALUES ($1, $2::jsonb)
          ON CONFLICT (scope) DO UPDATE
            SET value = EXCLUDED.value, version = poc_state.version + 1, updated_at = now()
          RETURNING version
        `, [CHANGE_HISTORY_ACCESS_SCOPE, JSON.stringify(accessValue)])
        const coreWrite = await client.query(`
          INSERT INTO poc_state (scope, value) VALUES ('core', $1::jsonb)
          ON CONFLICT (scope) DO UPDATE
            SET value = EXCLUDED.value, version = poc_state.version + 1, updated_at = now()
          RETURNING version
        `, [JSON.stringify(coreValue)])
        await client.query('COMMIT')
        return {
          accessVersion: Number(accessWrite.rows[0].version),
          coreVersion: Number(coreWrite.rows[0].version),
        }
      } catch (error) {
        await client.query('ROLLBACK')
        throw error
      } finally {
        client.release()
      }
    }
    const current = {
      access: memory.get(CHANGE_HISTORY_ACCESS_SCOPE) ?? { value: null, version: 0 },
      core: memory.get('core') ?? { value: null, version: 0 },
    }
    assertAccessVersions(current, expectedAccessVersion, expectedCoreVersion)
    const accessVersion = current.access.version + 1
    const coreVersion = current.core.version + 1
    memory.set(CHANGE_HISTORY_ACCESS_SCOPE, { value: accessValue, version: accessVersion })
    memory.set('core', { value: coreValue, version: coreVersion })
    return { accessVersion, coreVersion }
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

  async function readChangeHistoryCheckpoint(query) {
    if (!query || typeof query !== 'object') {
      throw new Error('The POC change-history checkpoint query is invalid.')
    }
    const sourceIdentityHash = requireSha256(query.sourceIdentityHash, 'sourceIdentityHash')
    const topicContract = requireBoundedString(query.topicContract, 'topicContract', 255)
    const partition = requireNonnegativeInteger(query.partition, 'partition')
    await startDatabase()
    if (!pool) throw new Error('PostgreSQL is required for durable POC change history.')
    const result = await pool.query(`
      SELECT next_offset
      FROM poc_change_history_checkpoints
      WHERE source_identity_hash = $1 AND topic_contract = $2 AND source_partition = $3
    `, [sourceIdentityHash, topicContract, partition])
    if (!result.rows[0]) return null
    const nextOffset = Number(result.rows[0].next_offset)
    if (!Number.isSafeInteger(nextOffset) || nextOffset < 0) {
      throw new Error('The stored POC change-history checkpoint is invalid.')
    }
    return nextOffset
  }

  async function readChangeHistoryProjection({ catalogScope } = {}) {
    const normalizedCatalogScope = requireBoundedString(catalogScope, 'catalogScope', 255)
    await startDatabase()
    if (!pool) {
      throw Object.assign(new Error('PostgreSQL is required for durable POC change history.'), {
        code: 'CHANGE_HISTORY_STORE_REQUIRED',
        statusCode: 503,
      })
    }
    const client = await pool.connect()
    try {
      await client.query('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
      const stateResult = await client.query(`
        SELECT scope, value, version FROM poc_state
        WHERE scope IN ($1, $2, $3)
      `, [...CHANGE_HISTORY_ACCESS_SCOPES, normalizedCatalogScope])
      const eventResult = await client.query(`
        SELECT event_identity, event_hash, normalized_change_transaction_id,
          asset_urn, normalized_entity_key, category, source_aspect, operation,
          before_data, after_data, actor_ref, source_occurred_at, detected_at, captured_at
        FROM poc_change_history_ledger_events
        ORDER BY COALESCE(source_occurred_at, detected_at) DESC, event_identity DESC
      `)
      const linkResult = await client.query(`
        SELECT link_event_identity, event_hash, ledger_event_identity, link_version,
          link_kind, action, change_request_id, change_request_round, prior_link_hash,
          reason, policy_hash, basis_hash, actor_ref, occurred_at, captured_at
        FROM poc_change_history_cr_link_events
        ORDER BY ledger_event_identity, link_version
      `)
      await client.query('COMMIT')
      const catalog = stateResult.rows.find((row) => row.scope === normalizedCatalogScope)
      return {
        ...changeHistoryAccessSnapshot(stateResult.rows),
        catalog: catalog ? { value: catalog.value, version: Number(catalog.version) } : { value: null, version: 0 },
        events: eventResult.rows,
        links: linkResult.rows,
      }
    } catch (error) {
      await client.query('ROLLBACK')
      throw error
    } finally {
      client.release()
    }
  }

  async function initializeChangeHistoryCaptureBoundaries(command) {
    const normalized = normalizeChangeHistoryBoundaries(command)
    await startDatabase()
    if (!pool) throw new Error('PostgreSQL is required for durable POC change history.')
    const client = await pool.connect()
    try {
      await client.query('BEGIN')
      await client.query(`
        INSERT INTO poc_change_history_sources (
          source_identity_hash, provider_name, provider_version, schema_contract_hash
        ) VALUES ($1, $2, $3, $4)
        ON CONFLICT DO NOTHING
      `, [
        normalized.sourceIdentityHash,
        normalized.providerName,
        normalized.providerVersion,
        normalized.schemaContractHash,
      ])
      const sourceResult = await client.query(`
        SELECT provider_name, provider_version, schema_contract_hash
        FROM poc_change_history_sources
        WHERE source_identity_hash = $1
        FOR UPDATE
      `, [normalized.sourceIdentityHash])
      const source = sourceResult.rows[0]
      if (!source
        || source.provider_name !== normalized.providerName
        || source.provider_version !== normalized.providerVersion
        || source.schema_contract_hash !== normalized.schemaContractHash) {
        throw new Error('The POC change-history source identity conflicts with stored evidence.')
      }
      const storedResult = await client.query(`
        SELECT source_partition, next_offset
        FROM poc_change_history_checkpoints
        WHERE source_identity_hash = $1 AND topic_contract = $2
        ORDER BY source_partition
        FOR UPDATE
      `, [normalized.sourceIdentityHash, normalized.topicContract])
      let checkpoints
      if (storedResult.rows.length === 0) {
        for (const { partition, boundary } of normalized.partitions) {
          await client.query(`
            INSERT INTO poc_change_history_checkpoints (
              source_identity_hash, topic_contract, source_partition,
              first_exact_offset, next_offset
            ) VALUES ($1, $2, $3, $4, $4)
          `, [
            normalized.sourceIdentityHash,
            normalized.topicContract,
            partition,
            boundary,
          ])
        }
        checkpoints = normalized.partitions.map(({ partition, boundary }) => ({
          partition,
          nextOffset: boundary,
        }))
      } else {
        const requestedPartitions = normalized.partitions.map(({ partition }) => partition)
        const storedPartitions = storedResult.rows.map((row) => Number(row.source_partition))
        if (storedPartitions.length !== requestedPartitions.length
          || storedPartitions.some((partition, index) => partition !== requestedPartitions[index])) {
          throw new Error('The MCL partition topology changed after its durable capture boundary was fixed.')
        }
        checkpoints = storedResult.rows.map((row) => {
          const nextOffset = Number(row.next_offset)
          if (!Number.isSafeInteger(nextOffset) || nextOffset < 0) {
            throw new Error('The stored POC change-history checkpoint is invalid.')
          }
          return { partition: Number(row.source_partition), nextOffset }
        })
      }
      await client.query('COMMIT')
      return checkpoints
    } catch (error) {
      await client.query('ROLLBACK')
      throw error
    } finally {
      client.release()
    }
  }

  async function appendChangeHistoryCapture(capture) {
    const normalized = normalizeChangeHistoryCapture(capture)
    await startDatabase()
    if (!pool) throw new Error('PostgreSQL is required for durable POC change history.')
    const client = await pool.connect()
    try {
      await client.query('BEGIN')
      const insertedSource = await client.query(`
        INSERT INTO poc_change_history_sources (
          source_identity_hash, provider_name, provider_version, schema_contract_hash
        ) VALUES ($1, $2, $3, $4)
        ON CONFLICT DO NOTHING
        RETURNING source_identity_hash
      `, [
        normalized.sourceIdentityHash,
        normalized.providerName,
        normalized.providerVersion,
        normalized.schemaContractHash,
      ])
      if (!insertedSource.rows[0]) {
        const source = await client.query(`
          SELECT provider_name, provider_version, schema_contract_hash
          FROM poc_change_history_sources
          WHERE source_identity_hash = $1
        `, [normalized.sourceIdentityHash])
        const existing = source.rows[0]
        if (!existing
          || existing.provider_name !== normalized.providerName
          || existing.provider_version !== normalized.providerVersion
          || existing.schema_contract_hash !== normalized.schemaContractHash) {
          throw new Error('The POC change-history source identity conflicts with stored evidence.')
        }
      }
      await client.query(`
        INSERT INTO poc_change_history_checkpoints (
          source_identity_hash, topic_contract, source_partition,
          first_exact_offset, next_offset
        ) VALUES ($1, $2, $3, $4, $4)
        ON CONFLICT DO NOTHING
      `, [
        normalized.sourceIdentityHash,
        normalized.topicContract,
        normalized.partition,
        normalized.offset,
      ])
      const checkpointResult = await client.query(`
        SELECT next_offset
        FROM poc_change_history_checkpoints
        WHERE source_identity_hash = $1 AND topic_contract = $2 AND source_partition = $3
        FOR UPDATE
      `, [normalized.sourceIdentityHash, normalized.topicContract, normalized.partition])
      const checkpointOffset = Number(checkpointResult.rows[0]?.next_offset)
      const replayed = checkpointOffset === normalized.offset + 1
      if (checkpointOffset !== normalized.offset && !replayed) {
        throw new Error('The POC change-history capture is stale or has an offset gap.')
      }

      for (const event of normalized.events) {
        const inserted = await client.query(`
          INSERT INTO poc_change_history_ledger_events (
            event_identity, event_hash, source_identity_hash, source_event_identity,
            normalized_change_transaction_id, deterministic_ordinal, topic_contract,
            source_partition, source_offset, asset_urn, normalized_entity_key,
            category, source_aspect, operation, before_data, after_data,
            before_hash, after_hash, actor_ref, source_occurred_at, detected_at
          ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
            $12, $13, $14, $15::jsonb, $16::jsonb, $17, $18, $19, $20, $21
          )
          ON CONFLICT DO NOTHING
          RETURNING event_identity
        `, [
          event.eventIdentity,
          event.eventHash,
          normalized.sourceIdentityHash,
          normalized.sourceEventIdentity,
          normalized.transactionIdentity,
          event.ordinal,
          normalized.topicContract,
          normalized.partition,
          normalized.offset,
          event.assetUrn,
          event.entityKey,
          event.category,
          event.sourceAspect,
          event.operation,
          event.beforeData === null ? null : JSON.stringify(event.beforeData),
          event.afterData === null ? null : JSON.stringify(event.afterData),
          event.beforeHash,
          event.afterHash,
          event.actorRef,
          event.sourceOccurredAt,
          event.detectedAt,
        ])
        if (!inserted.rows[0]) {
          const existingResult = await client.query(`
            SELECT event_hash
            FROM poc_change_history_ledger_events
            WHERE source_identity_hash = $1
              AND source_event_identity = $2
              AND deterministic_ordinal = $3
          `, [normalized.sourceIdentityHash, normalized.sourceEventIdentity, event.ordinal])
          if (existingResult.rows[0]?.event_hash !== event.eventHash) {
            throw new Error('The POC change-history replay conflicts with stored ledger evidence.')
          }
        }
      }

      if (!replayed) {
        const lastEvent = normalized.events.at(-1)
        const advanced = await client.query(`
          UPDATE poc_change_history_checkpoints
          SET next_offset = $4,
              last_contiguous_event_identity = COALESCE($5, last_contiguous_event_identity),
              last_source_occurred_at = COALESCE($6, last_source_occurred_at),
              last_captured_at = clock_timestamp(),
              version = version + 1
          WHERE source_identity_hash = $1 AND topic_contract = $2
            AND source_partition = $3 AND next_offset = $7
          RETURNING next_offset
        `, [
          normalized.sourceIdentityHash,
          normalized.topicContract,
          normalized.partition,
          normalized.offset + 1,
          lastEvent?.eventIdentity ?? null,
          lastEvent?.sourceOccurredAt ?? null,
          normalized.offset,
        ])
        if (!advanced.rows[0]) throw new Error('The POC change-history checkpoint advance lost its fence.')
      }
      await client.query('COMMIT')
      return {
        sourceEventIdentity: normalized.sourceEventIdentity,
        eventIdentities: normalized.events.map((event) => event.eventIdentity),
        nextOffset: normalized.offset + 1,
        replayed,
      }
    } catch (error) {
      await client.query('ROLLBACK')
      throw error
    } finally {
      client.release()
    }
  }

  async function appendChangeHistoryCrLink(command) {
    const normalized = normalizeChangeHistoryCrLink(command)
    await startDatabase()
    if (!pool) throw new Error('PostgreSQL is required for durable POC change history.')
    const client = await pool.connect()
    try {
      await client.query('BEGIN')
      if (command.expectedAccessVersion !== undefined || command.expectedCoreVersion !== undefined) {
        await client.query(
          'SELECT pg_advisory_xact_lock(hashtextextended($1, 0))',
          [CHANGE_HISTORY_ACCESS_SCOPE],
        )
        const normalizedCatalogScope = requireBoundedString(command.expectedCatalogScope, 'expectedCatalogScope', 255)
        const locked = await client.query(`
          SELECT scope, value, version FROM poc_state
          WHERE scope IN ($1, $2, $3)
          ORDER BY scope
          FOR UPDATE
        `, [...CHANGE_HISTORY_ACCESS_SCOPES, normalizedCatalogScope])
        const snapshot = changeHistoryAccessSnapshot(locked.rows)
        assertAccessVersions(
          snapshot,
          requireNonnegativeInteger(command.expectedAccessVersion, 'expectedAccessVersion'),
          requireNonnegativeInteger(command.expectedCoreVersion, 'expectedCoreVersion'),
        )
        if (sha256(stableJson(snapshot.core.value)) !== requireSha256(command.expectedCoreHash, 'expectedCoreHash')) {
          throw Object.assign(new Error('The change-request aggregate changed; read it and retry.'), {
            code: 'CR_BINDING_DRIFT',
            statusCode: 409,
          })
        }
        const catalog = locked.rows.find((row) => row.scope === normalizedCatalogScope)
        if (Number(catalog?.version ?? 0) !== requireNonnegativeInteger(command.expectedCatalogVersion, 'expectedCatalogVersion')
          || sha256(stableJson(catalog?.value ?? null)) !== requireSha256(command.expectedCatalogHash, 'expectedCatalogHash')) {
          throw Object.assign(new Error('The current catalog projection changed; read it and retry.'), {
            code: 'SYSTEM_MAPPING_UNRESOLVED',
            statusCode: 409,
          })
        }
      }
      const ledgerResult = await client.query(`
        SELECT event_identity FROM poc_change_history_ledger_events
        WHERE event_identity = $1
        FOR UPDATE
      `, [normalized.ledgerEventIdentity])
      if (!ledgerResult.rows[0]) {
        throw Object.assign(new Error('The change-history event was not found.'), {
          code: 'CHANGE_HISTORY_EVENT_NOT_FOUND',
          statusCode: 404,
        })
      }
      await client.query(
        'SELECT pg_advisory_xact_lock(hashtextextended($1, 0))',
        [`change-history-cr-link:${normalized.requestKeyHash}`],
      )
      const replayResult = await client.query(`
        SELECT link_event_identity, event_hash, request_hash, link_version
        FROM poc_change_history_cr_link_events
        WHERE request_key_hash = $1
        FOR UPDATE
      `, [normalized.requestKeyHash])
      const replay = replayResult.rows[0]
      if (replay) {
        if (replay.request_hash !== normalized.requestHash) {
          throw Object.assign(new Error('The POC CR link idempotency key conflicts with another request.'), {
            code: 'IDEMPOTENCY_CONFLICT',
            statusCode: 409,
          })
        }
        await client.query('COMMIT')
        return {
          linkEventIdentity: replay.link_event_identity,
          eventHash: replay.event_hash,
          linkVersion: Number(replay.link_version),
          replayed: true,
        }
      }
      const previousResult = await client.query(`
        SELECT event_hash, link_version
        FROM poc_change_history_cr_link_events
        WHERE ledger_event_identity = $1
        ORDER BY link_version DESC
        LIMIT 1
        FOR UPDATE
      `, [normalized.ledgerEventIdentity])
      const previous = previousResult.rows[0]
      const previousHash = previous?.event_hash ?? null
      if (previousHash !== normalized.priorLinkHash) {
        throw Object.assign(new Error('The POC CR link command has a stale prior-link hash.'), {
          code: 'LINK_VERSION_STALE',
          statusCode: 409,
        })
      }
      const linkVersion = Number(previous?.link_version ?? 0) + 1
      await client.query(`
        INSERT INTO poc_change_history_cr_link_events (
          link_event_identity, event_hash, request_key_hash, request_hash,
          ledger_event_identity, link_version, link_kind, action,
          change_request_id, change_request_round, prior_link_hash,
          reason, policy_hash, basis_hash, actor_ref, occurred_at
        ) VALUES (
          $1, $2, $3, $4, $5, $6, $7, $8,
          $9, $10, $11, $12, $13, $14, $15, $16
        )
      `, [
        normalized.linkEventIdentity,
        normalized.eventHash,
        normalized.requestKeyHash,
        normalized.requestHash,
        normalized.ledgerEventIdentity,
        linkVersion,
        normalized.linkKind,
        normalized.action,
        normalized.changeRequestId,
        normalized.changeRequestRound,
        normalized.priorLinkHash,
        normalized.reason,
        normalized.policyHash,
        normalized.basisHash,
        normalized.actorRef,
        normalized.occurredAt,
      ])
      await client.query('COMMIT')
      return {
        linkEventIdentity: normalized.linkEventIdentity,
        eventHash: normalized.eventHash,
        linkVersion,
        replayed: false,
      }
    } catch (error) {
      await client.query('ROLLBACK')
      throw error
    } finally {
      client.release()
    }
  }

  async function readChangeHistoryCrLinkReplay(command) {
    const requestKeyHash = sha256(requireBoundedString(command.idempotencyKey, 'idempotencyKey', 200))
    const requestHash = changeHistoryCrLinkRequestHash({
      ledgerEventIdentity: requireSha256(command.ledgerEventIdentity, 'ledgerEventIdentity'),
      linkKind: requireOneOf(command.linkKind, 'linkKind', ['PRIMARY', 'CANDIDATE']),
      action: requireOneOf(command.action, 'action', ['SET_PRIMARY', 'CLEAR_PRIMARY', 'ADD_CANDIDATE', 'REMOVE_CANDIDATE']),
      changeRequestId: requireBoundedString(command.changeRequestId, 'changeRequestId', 200),
      changeRequestRound: requirePositiveInteger(command.changeRequestRound, 'changeRequestRound'),
      reason: requireBoundedString(command.reason, 'reason', 2000),
    })
    await startDatabase()
    if (!pool) throw Object.assign(new Error('PostgreSQL is required for durable POC change history.'), {
      code: 'CHANGE_HISTORY_STORE_REQUIRED', statusCode: 503,
    })
    const result = await pool.query(`
      SELECT link_event_identity, event_hash, request_hash, link_version
      FROM poc_change_history_cr_link_events
      WHERE request_key_hash = $1
    `, [requestKeyHash])
    const replay = result.rows[0]
    if (!replay) return null
    if (replay.request_hash !== requestHash) {
      throw Object.assign(new Error('The POC CR link idempotency key conflicts with another request.'), {
        code: 'IDEMPOTENCY_CONFLICT', statusCode: 409,
      })
    }
    return {
      linkEventIdentity: replay.link_event_identity,
      eventHash: replay.event_hash,
      linkVersion: Number(replay.link_version),
      replayed: true,
    }
  }

  async function runChangeHistoryScheduler(command, task) {
    if (!command || typeof command !== 'object' || typeof task !== 'function') {
      throw new Error('The POC change-history scheduler command is invalid.')
    }
    const lockName = requireBoundedString(command.lockName, 'lockName', 255)
    const scheduledFor = explicitSchedulerTimestamp(command.scheduledFor)
    const trigger = requireOneOf(command.trigger, 'trigger', ['scheduled', 'manual'])
    await startDatabase()
    if (!pool) throw new Error('PostgreSQL is required for the POC change-history scheduler.')
    const client = await pool.connect()
    let locked = false
    try {
      const lock = await client.query(
        'SELECT pg_try_advisory_lock(hashtextextended($1, 0)) AS acquired',
        [lockName],
      )
      locked = lock.rows[0]?.acquired === true
      if (!locked) return { status: 'locked', scheduledFor }
      const scope = `change-history-scheduler-v1:${lockName}`
      const current = await client.query('SELECT value FROM poc_state WHERE scope = $1', [scope])
      const lastSuccessfulSchedule = current.rows.length === 0
        ? null
        : explicitSchedulerTimestamp(
          current.rows[0]?.value?.last_successful_schedule,
          'stored last_successful_schedule',
        )
      if (lastSuccessfulSchedule === scheduledFor) {
        return { status: 'already_completed', scheduledFor }
      }
      if (lastSuccessfulSchedule !== null
        && Date.parse(lastSuccessfulSchedule) > Date.parse(scheduledFor)) {
        return { status: 'stale', scheduledFor }
      }
      const result = await task()
      const completedAt = new Date().toISOString()
      const receipt = {
        version: 1,
        last_successful_schedule: scheduledFor,
        completed_at: completedAt,
        trigger,
      }
      const receiptWrite = await client.query(`
        INSERT INTO poc_state (scope, value) VALUES ($1, $2::jsonb)
        ON CONFLICT (scope) DO UPDATE
          SET value = EXCLUDED.value, version = poc_state.version + 1, updated_at = now()
          WHERE poc_state.value ->> 'last_successful_schedule' = $3
            AND (poc_state.value ->> 'last_successful_schedule')::timestamptz < $4::timestamptz
        RETURNING poc_state.value ->> 'last_successful_schedule' AS last_successful_schedule
      `, [scope, JSON.stringify(receipt), lastSuccessfulSchedule, scheduledFor])
      if (receiptWrite.rows.length !== 1
        || receiptWrite.rows[0]?.last_successful_schedule !== scheduledFor) {
        throw new Error('The POC change-history scheduler receipt was not advanced.')
      }
      return { status: 'succeeded', scheduledFor, completedAt, result }
    } finally {
      if (locked) {
        await client.query('SELECT pg_advisory_unlock(hashtextextended($1, 0))', [lockName])
      }
      client.release()
    }
  }

  async function close() {
    await Promise.allSettled([
      redis?.isOpen ? redis.quit() : undefined,
      pool && !databasePool ? pool.end() : undefined,
    ])
    redis = undefined
    if (!databasePool) pool = undefined
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
    readChangeHistoryCheckpoint,
    readChangeHistoryProjection,
    readChangeHistoryAccess,
    writeChangeHistoryAccess,
    initializeChangeHistoryCaptureBoundaries,
    appendChangeHistoryCapture,
    appendChangeHistoryCrLink,
    readChangeHistoryCrLinkReplay,
    runChangeHistoryScheduler,
    close,
    configured: { postgres: databaseConfigured, redis: Boolean(redisUrl) },
  }
}

function changeHistoryAccessSnapshot(rows) {
  const rowByScope = new Map(rows.map((row) => [row.scope, row]))
  const snapshot = (scope) => {
    const row = rowByScope.get(scope)
    return row ? { value: row.value, version: Number(row.version) } : { value: null, version: 0 }
  }
  return { access: snapshot(CHANGE_HISTORY_ACCESS_SCOPE), core: snapshot('core') }
}

function assertAccessVersions(current, expectedAccessVersion, expectedCoreVersion) {
  if (current.access.version !== expectedAccessVersion || current.core.version !== expectedCoreVersion) {
    throw Object.assign(new Error('The change-history access state changed; read it and retry.'), {
      code: 'ACCESS_VERSION_STALE',
      statusCode: 409,
    })
  }
}

function preserveProtectedCoreAccessFields(value, currentCore, accessExists) {
  if (!accessExists) return value
  if (!isPlainObject(value)) {
    throw Object.assign(new Error('Core state must remain an object after access authority exists.'), {
      code: 'CORE_ACCESS_FIELDS_PROTECTED',
      statusCode: 409,
    })
  }
  const next = { ...value }
  const current = isPlainObject(currentCore) ? currentCore : {}
  for (const field of PROTECTED_CORE_ACCESS_FIELDS) {
    if (Object.hasOwn(current, field)) next[field] = current[field]
    else delete next[field]
  }
  return next
}

function explicitSchedulerTimestamp(value, field = 'scheduledFor') {
  if (typeof value !== 'string' || !value.endsWith('Z')) {
    throw new Error(`${field} must be an explicit UTC timestamp.`)
  }
  const parsed = new Date(value)
  if (!Number.isFinite(parsed.getTime()) || parsed.toISOString() !== value) {
    throw new Error(`${field} must be an explicit UTC timestamp.`)
  }
  return value
}

function normalizeChangeHistoryBoundaries(command) {
  if (!command || typeof command !== 'object') {
    throw new Error('The POC change-history capture boundary command is invalid.')
  }
  if (!Array.isArray(command.partitions)
    || command.partitions.length < 1
    || command.partitions.length > 1000) {
    throw new Error('The POC change-history capture boundary inventory is invalid.')
  }
  const partitions = command.partitions.map((item) => ({
    partition: requireNonnegativeInteger(item?.partition, 'partition'),
    boundary: requireNonnegativeInteger(item?.boundary, 'boundary'),
  })).sort((left, right) => left.partition - right.partition)
  if (new Set(partitions.map(({ partition }) => partition)).size !== partitions.length) {
    throw new Error('The POC change-history capture boundary inventory contains a duplicate partition.')
  }
  return {
    sourceIdentityHash: requireSha256(command.sourceIdentityHash, 'sourceIdentityHash'),
    schemaContractHash: requireSha256(command.schemaContractHash, 'schemaContractHash'),
    providerName: requireBoundedString(command.providerName, 'providerName', 100),
    providerVersion: requireBoundedString(command.providerVersion, 'providerVersion', 100),
    topicContract: requireBoundedString(command.topicContract, 'topicContract', 255),
    partitions,
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

function normalizeChangeHistoryCapture(capture) {
  if (!capture || typeof capture !== 'object') throw new Error('The POC change-history capture is invalid.')
  const sourceIdentityHash = requireSha256(capture.sourceIdentityHash, 'sourceIdentityHash')
  const schemaContractHash = requireSha256(capture.schemaContractHash, 'schemaContractHash')
  const providerName = requireBoundedString(capture.providerName, 'providerName', 100)
  const providerVersion = requireBoundedString(capture.providerVersion, 'providerVersion', 100)
  const topicContract = requireBoundedString(capture.topicContract, 'topicContract', 255)
  const partition = requireNonnegativeInteger(capture.partition, 'partition')
  const offset = requireNonnegativeInteger(capture.offset, 'offset')
  if (!Array.isArray(capture.events) || capture.events.length > 1000) {
    throw new Error('The POC change-history capture must contain 0 to 1000 normalized events.')
  }
  const sourceEventIdentity = sha256(stableJson([
    sourceIdentityHash, topicContract, partition, offset,
  ]))
  const transactionIdentity = sourceEventIdentity
  const sorted = capture.events.map((event) => normalizeSemanticEvent(event))
    .sort((left, right) => {
      const leftKey = stableJson(left)
      const rightKey = stableJson(right)
      return leftKey < rightKey ? -1 : leftKey > rightKey ? 1 : 0
    })
  const events = sorted.map((event, ordinal) => {
    const eventIdentity = sha256(stableJson([
      sourceEventIdentity, event.category, event.entityKey, event.operation, ordinal,
    ]))
    return {
      ...event,
      ordinal,
      eventIdentity,
      eventHash: sha256(stableJson({ ...event, eventIdentity, ordinal })),
    }
  })
  return {
    sourceIdentityHash,
    schemaContractHash,
    providerName,
    providerVersion,
    topicContract,
    partition,
    offset,
    sourceEventIdentity,
    transactionIdentity,
    events,
  }
}

function normalizeSemanticEvent(event) {
  if (!event || typeof event !== 'object') throw new Error('A normalized change-history event is invalid.')
  const category = requireOneOf(event.category, 'category', [
    'TECHNICAL_SCHEMA', 'DOCUMENTATION', 'TAG', 'GLOSSARY_TERM', 'OWNERSHIP',
  ])
  const aspectByCategory = {
    TECHNICAL_SCHEMA: ['schemaMetadata'],
    DOCUMENTATION: ['datasetProperties', 'editableSchemaMetadata'],
    TAG: ['globalTags'],
    GLOSSARY_TERM: ['glossaryTerms'],
    OWNERSHIP: ['ownership'],
  }
  const sourceAspect = requireOneOf(event.sourceAspect, 'sourceAspect', aspectByCategory[category])
  const beforeData = normalizeBoundedDocument(event.beforeData, 'beforeData')
  const afterData = normalizeBoundedDocument(event.afterData, 'afterData')
  return {
    assetUrn: requireBoundedString(event.assetUrn, 'assetUrn', 4096),
    entityKey: requireBoundedString(event.entityKey, 'entityKey', 1000),
    category,
    sourceAspect,
    operation: requireOneOf(event.operation, 'operation', [
      'CREATE', 'UPDATE', 'UPSERT', 'DELETE', 'ADD', 'REMOVE',
    ]),
    beforeData,
    afterData,
    beforeHash: beforeData === null ? null : sha256(stableJson(beforeData)),
    afterHash: afterData === null ? null : sha256(stableJson(afterData)),
    actorRef: event.actorRef == null ? null : requireBoundedString(event.actorRef, 'actorRef', 1000),
    sourceOccurredAt: event.sourceOccurredAt == null ? null : requireTimestamp(event.sourceOccurredAt, 'sourceOccurredAt'),
    detectedAt: requireTimestamp(event.detectedAt, 'detectedAt'),
  }
}

function normalizeChangeHistoryCrLink(command) {
  if (!command || typeof command !== 'object') throw new Error('The POC CR link command is invalid.')
  const linkKind = requireOneOf(command.linkKind, 'linkKind', ['PRIMARY', 'CANDIDATE'])
  const action = requireOneOf(command.action, 'action', linkKind === 'PRIMARY'
    ? ['SET_PRIMARY', 'CLEAR_PRIMARY']
    : ['ADD_CANDIDATE', 'REMOVE_CANDIDATE'])
  const normalized = {
    ledgerEventIdentity: requireSha256(command.ledgerEventIdentity, 'ledgerEventIdentity'),
    linkKind,
    action,
    changeRequestId: requireBoundedString(command.changeRequestId, 'changeRequestId', 200),
    changeRequestRound: requirePositiveInteger(command.changeRequestRound, 'changeRequestRound'),
    priorLinkHash: command.priorLinkHash == null ? null : requireSha256(command.priorLinkHash, 'priorLinkHash'),
    reason: requireBoundedString(command.reason, 'reason', 2000),
    policyHash: requireSha256(command.policyHash, 'policyHash'),
    basisHash: requireSha256(command.basisHash, 'basisHash'),
    actorRef: requireBoundedString(command.actorRef, 'actorRef', 1000),
    occurredAt: requireTimestamp(command.occurredAt, 'occurredAt'),
  }
  const requestKeyHash = sha256(requireBoundedString(command.idempotencyKey, 'idempotencyKey', 200))
  const requestHash = changeHistoryCrLinkRequestHash(normalized)
  const eventHash = sha256(stableJson({ ...normalized, requestKeyHash, requestHash }))
  return {
    ...normalized,
    requestKeyHash,
    requestHash,
    eventHash,
    linkEventIdentity: sha256(stableJson([requestKeyHash, requestHash])),
  }
}

function changeHistoryCrLinkRequestHash(normalized) {
  return sha256(stableJson({
    ledgerEventIdentity: normalized.ledgerEventIdentity,
    linkKind: normalized.linkKind,
    action: normalized.action,
    changeRequestId: normalized.changeRequestId,
    changeRequestRound: normalized.changeRequestRound,
    reason: normalized.reason,
  }))
}

function normalizeBoundedDocument(value, field) {
  if (value == null) return null
  if (!isPlainObject(value)) throw new Error(`${field} must be a normalized JSON object or null.`)
  assertNoRawProviderKeys(value, field)
  const normalized = JSON.parse(stableJson(value))
  if (new TextEncoder().encode(JSON.stringify(normalized)).byteLength > 16_384) {
    throw new Error(`${field} exceeds the normalized 16384-byte bound.`)
  }
  return normalized
}

function assertNoRawProviderKeys(value, field) {
  if (Array.isArray(value)) {
    for (const item of value) assertNoRawProviderKeys(item, field)
    return
  }
  if (!isPlainObject(value)) return
  for (const [key, item] of Object.entries(value)) {
    if (['raw', 'payload', 'aspect', 'schemaMetadata', 'previousAspectValue'].includes(key)) {
      throw new Error(`${field} contains a forbidden raw provider-document key.`)
    }
    assertNoRawProviderKeys(item, field)
  }
}

function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`
  if (isPlainObject(value)) {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(',')}}`
  }
  return JSON.stringify(value)
}

function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function sha256(value) {
  return createHash('sha256').update(value).digest('hex')
}

function requireSha256(value, field) {
  if (typeof value !== 'string' || !/^[0-9a-f]{64}$/.test(value)) {
    throw new Error(`${field} must be a lowercase SHA-256 value.`)
  }
  return value
}

function requireBoundedString(value, field, maximum) {
  if (typeof value !== 'string' || value.trim() !== value || value.length < 1 || value.length > maximum) {
    throw new Error(`${field} is outside its normalized string bound.`)
  }
  return value
}

function requireOneOf(value, field, allowed) {
  if (!allowed.includes(value)) throw new Error(`${field} is outside its closed vocabulary.`)
  return value
}

function requireNonnegativeInteger(value, field) {
  if (!Number.isSafeInteger(value) || value < 0) throw new Error(`${field} must be a non-negative integer.`)
  return value
}

function requirePositiveInteger(value, field) {
  if (!Number.isSafeInteger(value) || value < 1) throw new Error(`${field} must be a positive integer.`)
  return value
}

function requireTimestamp(value, field) {
  if (typeof value !== 'string' || !value.endsWith('Z')) throw new Error(`${field} must be an explicit UTC timestamp.`)
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) throw new Error(`${field} must be a valid UTC timestamp.`)
  return parsed.toISOString()
}
