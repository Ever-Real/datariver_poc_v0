/* global process */
import pg from 'pg'
import { createClient } from 'redis'

const { Pool } = pg

export function createPocStateStore() {
  const databaseUrl = process.env.POC_DATABASE_URL?.trim()
  const databaseHost = process.env.POC_POSTGRES_HOST?.trim()
  const databaseConfigured = Boolean(databaseUrl || databaseHost)
  const redisUrl = process.env.POC_REDIS_URL?.trim()
  const memory = new Map()
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

  return {
    read,
    write,
    cacheGet,
    cacheSet,
    cacheDelete,
    configured: { postgres: databaseConfigured, redis: Boolean(redisUrl) },
  }
}
