import { createHash } from 'node:crypto'

export const POC_POSTGRES_SCHEMA_INTEGRITY_FLAG = 'POC_POSTGRES_SCHEMA_INTEGRITY_REQUIRED'
export const POC_POSTGRES_SCHEMA_CONTRACT = 'DATARIVER_POC_POSTGRES_OWNED_SCHEMA_V1'
export const POC_POSTGRES_SCHEMA_REVISION = 1
export const POC_POSTGRES_SCHEMA_RECEIPT_SCOPE = 'product-owned-schema-contract-v1'

// Generated from the pinned PostgreSQL 17 / pgvector 0.8.2 canonical init contract.
// The fingerprint covers only public Product-owned objects whose names use the reserved
// poc_ prefix. Unrelated schemas, tables, extensions and rows are deliberately excluded.
export const POC_POSTGRES_SCHEMA_FINGERPRINT = '8d9d48438541c838e93b19dc6651305e34040b0a995764727c172b39d0948bd1'
export const POC_POSTGRES_MIGRATABLE_FINGERPRINTS = new Set([
  'd96eab3a780b05349bbccdbf1e2ee25e0d9da4d4b8c63c5cfd9c4fe97935d30b',
])

export const POC_POSTGRES_OWNED_SCHEMA_QUERY = `
  WITH owned_relations AS (
    SELECT relation.oid, relation.relname, relation.relkind
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'public'
      AND relation.relname LIKE 'poc\\_%' ESCAPE '\\'
      AND relation.relkind IN ('r', 'p')
  ), owned_objects AS (
    SELECT 'TABLE'::text AS kind, relation.relname::text AS identity,
      relation.relkind::text AS definition
    FROM owned_relations AS relation
    UNION ALL
    SELECT 'COLUMN', relation.relname || '.' || attribute.attnum || '.' || attribute.attname,
      concat_ws('|', pg_catalog.format_type(attribute.atttypid, attribute.atttypmod),
        attribute.attnotnull::text, attribute.attidentity, attribute.attgenerated,
        COALESCE(pg_catalog.pg_get_expr(default_value.adbin, default_value.adrelid), ''))
    FROM owned_relations AS relation
    JOIN pg_catalog.pg_attribute AS attribute ON attribute.attrelid = relation.oid
    LEFT JOIN pg_catalog.pg_attrdef AS default_value
      ON default_value.adrelid = relation.oid AND default_value.adnum = attribute.attnum
    WHERE attribute.attnum > 0 AND NOT attribute.attisdropped
    UNION ALL
    SELECT 'CONSTRAINT', relation.relname || '.' || constraint_value.conname,
      concat_ws('|', constraint_value.contype, constraint_value.condeferrable::text,
        constraint_value.condeferred::text, constraint_value.convalidated::text,
        pg_catalog.pg_get_constraintdef(constraint_value.oid, false))
    FROM owned_relations AS relation
    JOIN pg_catalog.pg_constraint AS constraint_value
      ON constraint_value.conrelid = relation.oid
    UNION ALL
    SELECT 'INDEX', relation.relname || '.' || index_relation.relname,
      concat_ws('|', index_value.indisunique::text, index_value.indisprimary::text,
        index_value.indisvalid::text, index_value.indisready::text,
        pg_catalog.pg_get_indexdef(index_value.indexrelid, 0, false))
    FROM owned_relations AS relation
    JOIN pg_catalog.pg_index AS index_value ON index_value.indrelid = relation.oid
    JOIN pg_catalog.pg_class AS index_relation ON index_relation.oid = index_value.indexrelid
    UNION ALL
    SELECT 'TRIGGER', relation.relname || '.' || trigger_value.tgname,
      concat_ws('|', trigger_value.tgenabled, pg_catalog.pg_get_triggerdef(trigger_value.oid, false))
    FROM owned_relations AS relation
    JOIN pg_catalog.pg_trigger AS trigger_value ON trigger_value.tgrelid = relation.oid
    WHERE NOT trigger_value.tgisinternal
    UNION ALL
    SELECT 'FUNCTION', procedure_value.proname || '(' ||
      pg_catalog.pg_get_function_identity_arguments(procedure_value.oid) || ')',
      concat_ws('|', pg_catalog.pg_get_function_result(procedure_value.oid),
        language_value.lanname, procedure_value.prosecdef::text, procedure_value.provolatile,
        procedure_value.prosrc)
    FROM pg_catalog.pg_proc AS procedure_value
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = procedure_value.pronamespace
    JOIN pg_catalog.pg_language AS language_value ON language_value.oid = procedure_value.prolang
    WHERE namespace.nspname = 'public'
      AND procedure_value.proname LIKE 'poc\\_%' ESCAPE '\\'
    UNION ALL
    SELECT 'TYPE', type_value.typname,
      concat_ws('|', type_value.typtype, type_value.typcategory,
        COALESCE((SELECT string_agg(enum_value.enumlabel, ',' ORDER BY enum_value.enumsortorder)
          FROM pg_catalog.pg_enum AS enum_value WHERE enum_value.enumtypid = type_value.oid), ''))
    FROM pg_catalog.pg_type AS type_value
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = type_value.typnamespace
    WHERE namespace.nspname = 'public'
      AND type_value.typname LIKE 'poc\\_%' ESCAPE '\\'
      AND type_value.typtype IN ('d', 'e')
  )
  SELECT kind, identity,
    regexp_replace(definition, '[[:space:]]+', ' ', 'g') AS definition
  FROM owned_objects
  ORDER BY kind, identity
  LIMIT 5001
`

function schemaError(code, message) {
  return Object.assign(new Error(message), { code })
}

function exactKeys(value, expected) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const keys = Object.keys(value).sort()
  return keys.length === expected.length && keys.every((key, index) => key === expected[index])
}

export function canonicalizePocOwnedSchemaRows(rows) {
  if (!Array.isArray(rows) || rows.length > 5000) {
    throw schemaError(
      'POC_POSTGRES_SCHEMA_INSPECTION_INVALID',
      'Product-owned PostgreSQL schema inspection returned an invalid bounded result.',
    )
  }
  const normalized = rows.map((row) => {
    if (!row || typeof row !== 'object' || Array.isArray(row)
      || !['TABLE', 'COLUMN', 'CONSTRAINT', 'INDEX', 'TRIGGER', 'FUNCTION', 'TYPE'].includes(row.kind)
      || typeof row.identity !== 'string' || !row.identity || row.identity.length > 300
      || typeof row.definition !== 'string' || row.definition.length > 20_000) {
      throw schemaError(
        'POC_POSTGRES_SCHEMA_INSPECTION_INVALID',
        'Product-owned PostgreSQL schema inspection returned one malformed object.',
      )
    }
    return { kind: row.kind, identity: row.identity, definition: row.definition.trim() }
  })
  normalized.sort((left, right) => (
    left.kind.localeCompare(right.kind) || left.identity.localeCompare(right.identity)
  ))
  for (let index = 1; index < normalized.length; index += 1) {
    if (normalized[index - 1].kind === normalized[index].kind
      && normalized[index - 1].identity === normalized[index].identity) {
      throw schemaError(
        'POC_POSTGRES_SCHEMA_INSPECTION_INVALID',
        'Product-owned PostgreSQL schema inspection returned duplicate object identity.',
      )
    }
  }
  return normalized
}

export function fingerprintPocOwnedSchema(rows) {
  return createHash('sha256')
    .update(JSON.stringify(canonicalizePocOwnedSchemaRows(rows)), 'utf8')
    .digest('hex')
}

function validateReceipt(receipt, fingerprint) {
  if (receipt === null || receipt === undefined) return false
  if (!exactKeys(receipt, ['contract', 'fingerprint', 'revision'])) {
    throw schemaError(
      'POC_POSTGRES_SCHEMA_RECEIPT_MISMATCH',
      'The Product-owned PostgreSQL schema receipt is malformed.',
    )
  }
  if (receipt.contract !== POC_POSTGRES_SCHEMA_CONTRACT
    || !Number.isSafeInteger(receipt.revision) || receipt.revision !== POC_POSTGRES_SCHEMA_REVISION
    || receipt.fingerprint !== fingerprint) {
    const code = Number.isSafeInteger(receipt.revision)
      && receipt.revision > POC_POSTGRES_SCHEMA_REVISION
      ? 'POC_POSTGRES_SCHEMA_NEWER_UNSUPPORTED'
      : 'POC_POSTGRES_SCHEMA_RECEIPT_MISMATCH'
    throw schemaError(code, 'The Product-owned PostgreSQL schema receipt is incompatible.')
  }
  return true
}

export function classifyPocPostgresOwnedSchema({
  rows,
  receipt = null,
  expectedFingerprint = POC_POSTGRES_SCHEMA_FINGERPRINT,
  migratableFingerprints = POC_POSTGRES_MIGRATABLE_FINGERPRINTS,
} = {}) {
  const normalized = canonicalizePocOwnedSchemaRows(rows)
  if (normalized.length === 0) {
    if (receipt !== null && receipt !== undefined) {
      throw schemaError(
        'POC_POSTGRES_SCHEMA_RECEIPT_MISMATCH',
        'A Product schema receipt exists without its owned schema.',
      )
    }
    return Object.freeze({ state: 'FRESH', fingerprint: null })
  }
  const fingerprint = fingerprintPocOwnedSchema(normalized)
  if (fingerprint === expectedFingerprint) {
    return Object.freeze({
      state: validateReceipt(receipt, fingerprint) ? 'CURRENT' : 'CURRENT_UNVERSIONED',
      fingerprint,
    })
  }
  if (migratableFingerprints.has(fingerprint) && receipt === null) {
    return Object.freeze({ state: 'KNOWN_OLDER_MIGRATABLE', fingerprint })
  }
  if (receipt && Number.isSafeInteger(receipt.revision)
    && receipt.revision > POC_POSTGRES_SCHEMA_REVISION) {
    throw schemaError(
      'POC_POSTGRES_SCHEMA_NEWER_UNSUPPORTED',
      'The Product-owned PostgreSQL schema revision is newer than this Product.',
    )
  }
  throw schemaError(
    'POC_POSTGRES_SCHEMA_INTEGRITY_FAILED',
    'The Product-owned PostgreSQL schema surface is partial, malformed or unsupported.',
  )
}

export async function inspectPocPostgresOwnedSchema(client) {
  const { rows } = await client.query(POC_POSTGRES_OWNED_SCHEMA_QUERY)
  const hasStateTable = rows.some((row) => row.kind === 'TABLE' && row.identity === 'poc_state')
  let receipt = null
  if (hasStateTable) {
    const result = await client.query(
      'SELECT value FROM poc_state WHERE scope = $1',
      [POC_POSTGRES_SCHEMA_RECEIPT_SCOPE],
    )
    receipt = result.rows[0]?.value ?? null
  }
  return classifyPocPostgresOwnedSchema({ rows, receipt })
}

export async function recordPocPostgresOwnedSchemaReceipt(client) {
  const receipt = {
    contract: POC_POSTGRES_SCHEMA_CONTRACT,
    revision: POC_POSTGRES_SCHEMA_REVISION,
    fingerprint: POC_POSTGRES_SCHEMA_FINGERPRINT,
  }
  await client.query(
    `INSERT INTO poc_state (scope, value) VALUES ($1, $2::jsonb)
      ON CONFLICT (scope) DO UPDATE SET value = EXCLUDED.value,
        version = poc_state.version + 1, updated_at = clock_timestamp()`,
    [POC_POSTGRES_SCHEMA_RECEIPT_SCOPE, JSON.stringify(receipt)],
  )
}
