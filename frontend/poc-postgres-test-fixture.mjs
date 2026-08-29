import assert from 'node:assert/strict'
import { randomBytes } from 'node:crypto'
import process from 'node:process'
import { URL } from 'node:url'
import pg from 'pg'

const { Client } = pg

const adminDatabaseUrl = process.env.POC_LOCAL_SECURITY_POSTGRES_TEST_URL?.trim()
const isolated = process.env.POC_LOCAL_SECURITY_POSTGRES_TEST_CONFIRM_ISOLATED === '1'

export const pocPostgresTestSkipReason = adminDatabaseUrl && isolated
  ? false
  : 'requires POC_LOCAL_SECURITY_POSTGRES_TEST_URL and POC_LOCAL_SECURITY_POSTGRES_TEST_CONFIRM_ISOLATED=1'

function databaseIdentifier(label) {
  const boundedLabel = label.toLowerCase().replace(/[^a-z0-9]+/g, '_').slice(0, 20)
  const identifier = `ac01_${boundedLabel}_${process.pid}_${randomBytes(6).toString('hex')}`
  assert.match(identifier, /^[a-z][a-z0-9_]{0,62}$/)
  return identifier
}

function quoteIdentifier(identifier) {
  assert.match(identifier, /^[a-z][a-z0-9_]{0,62}$/)
  return `"${identifier}"`
}

function databaseUrlFor(identifier) {
  const url = new URL(adminDatabaseUrl)
  url.pathname = `/${identifier}`
  url.search = ''
  return url.toString()
}

export async function withDisposablePocPostgres(label, action) {
  assert.equal(pocPostgresTestSkipReason, false)
  const databaseName = databaseIdentifier(label)
  const admin = new Client({ connectionString: adminDatabaseUrl })
  let created = false
  await admin.connect()
  try {
    await admin.query(`CREATE DATABASE ${quoteIdentifier(databaseName)}`)
    created = true
    return await action({
      connectionString: databaseUrlFor(databaseName),
      databaseName,
    })
  } finally {
    if (created) {
      await admin.query(`DROP DATABASE ${quoteIdentifier(databaseName)} WITH (FORCE)`)
      const residue = await admin.query(
        'SELECT count(*)::integer AS database_count FROM pg_database WHERE datname = $1',
        [databaseName],
      )
      assert.equal(
        residue.rows[0]?.database_count,
        0,
        'the disposable database (and all synthetic row residue) must be absent',
      )
    }
    await admin.end()
  }
}
