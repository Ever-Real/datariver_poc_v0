import { createHash } from 'node:crypto'

export const POC_POSTGRES_SCHEMA_INTEGRITY_FLAG = 'POC_POSTGRES_SCHEMA_INTEGRITY_REQUIRED'
export const POC_POSTGRES_SCHEMA_V1_CONTRACT = 'DATARIVER_POC_POSTGRES_OWNED_SCHEMA_V1'
export const POC_POSTGRES_SCHEMA_V1_REVISION = 1
export const POC_POSTGRES_SCHEMA_V1_RECEIPT_SCOPE = 'product-owned-schema-contract-v1'
export const POC_POSTGRES_SCHEMA_V1_FINGERPRINT = '8d9d48438541c838e93b19dc6651305e34040b0a995764727c172b39d0948bd1'

export const POC_POSTGRES_SCHEMA_V2_CONTRACT = 'DATARIVER_POC_POSTGRES_OWNED_SCHEMA_V2'
export const POC_POSTGRES_SCHEMA_V2_REVISION = 2
export const POC_POSTGRES_SCHEMA_V2_RECEIPT_SCOPE = 'product-owned-schema-contract-v2'
export const POC_POSTGRES_SCHEMA_V2_FINGERPRINT = 'b19760b2ca0857e572e5c16684747a2f76ec43d46988b52af649b997d4991dc1'

export const POC_POSTGRES_SCHEMA_CONTRACT = 'DATARIVER_POC_POSTGRES_OWNED_SCHEMA_V3'
export const POC_POSTGRES_SCHEMA_REVISION = 3
export const POC_POSTGRES_SCHEMA_RECEIPT_SCOPE = 'product-owned-schema-contract-v3'

// Generated from the pinned PostgreSQL 17 / pgvector 0.8.2 canonical init contract.
// The fingerprint covers only public Product-owned objects whose names use the reserved
// poc_ prefix. Unrelated schemas, tables, extensions and rows are deliberately excluded.
export const POC_POSTGRES_SCHEMA_FINGERPRINT = '80a64380b21040a1a308301a236fd74bb5d8aad210be675f97ffba87523c6e48'
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

function validateReceipt(receipt, { contract, revision, fingerprint }) {
  if (!exactKeys(receipt, ['contract', 'fingerprint', 'revision'])) {
    throw schemaError(
      'POC_POSTGRES_SCHEMA_RECEIPT_MISMATCH',
      'The Product-owned PostgreSQL schema receipt is malformed.',
    )
  }
  if (receipt.contract !== contract
    || !Number.isSafeInteger(receipt.revision) || receipt.revision !== revision
    || receipt.fingerprint !== fingerprint) {
    const code = Number.isSafeInteger(receipt.revision)
      && receipt.revision > POC_POSTGRES_SCHEMA_REVISION
      ? 'POC_POSTGRES_SCHEMA_NEWER_UNSUPPORTED'
      : 'POC_POSTGRES_SCHEMA_RECEIPT_MISMATCH'
    throw schemaError(code, 'The Product-owned PostgreSQL schema receipt is incompatible.')
  }
  return true
}

function receiptValues(receipts, legacyReceipt, { v1Fingerprint, v2Fingerprint, v3Fingerprint }) {
  const rows = legacyReceipt === undefined
    ? receipts
    : [{ scope: POC_POSTGRES_SCHEMA_V1_RECEIPT_SCOPE, value: legacyReceipt }]
  if (!Array.isArray(rows) || rows.length > 4) {
    throw schemaError(
      'POC_POSTGRES_SCHEMA_RECEIPT_MISMATCH',
      'The Product-owned PostgreSQL schema receipt set is malformed.',
    )
  }
  const values = new Map()
  for (const row of rows) {
    if (!exactKeys(row, ['scope', 'value']) || typeof row.scope !== 'string'
      || values.has(row.scope)) {
      throw schemaError(
        'POC_POSTGRES_SCHEMA_RECEIPT_MISMATCH',
        'The Product-owned PostgreSQL schema receipt set is malformed.',
      )
    }
    if (![POC_POSTGRES_SCHEMA_V1_RECEIPT_SCOPE, POC_POSTGRES_SCHEMA_V2_RECEIPT_SCOPE, POC_POSTGRES_SCHEMA_RECEIPT_SCOPE].includes(row.scope)) {
      const revision = /^product-owned-schema-contract-v([0-9]+)$/.exec(row.scope)?.[1]
      throw schemaError(
        revision && Number(revision) > POC_POSTGRES_SCHEMA_REVISION
          ? 'POC_POSTGRES_SCHEMA_NEWER_UNSUPPORTED'
          : 'POC_POSTGRES_SCHEMA_RECEIPT_MISMATCH',
        'The Product-owned PostgreSQL schema receipt scope is incompatible.',
      )
    }
    values.set(row.scope, row.value)
  }
  const v1 = values.get(POC_POSTGRES_SCHEMA_V1_RECEIPT_SCOPE)
  const v2 = values.get(POC_POSTGRES_SCHEMA_V2_RECEIPT_SCOPE)
  const v3 = values.get(POC_POSTGRES_SCHEMA_RECEIPT_SCOPE)
  if (v1 !== undefined) {
    validateReceipt(v1, {
      contract: POC_POSTGRES_SCHEMA_V1_CONTRACT,
      revision: POC_POSTGRES_SCHEMA_V1_REVISION,
      fingerprint: v1Fingerprint,
    })
  }
  if (v2 !== undefined) {
    validateReceipt(v2, {
      contract: POC_POSTGRES_SCHEMA_V2_CONTRACT,
      revision: POC_POSTGRES_SCHEMA_V2_REVISION,
      fingerprint: v2Fingerprint,
    })
  }
  if (v3 !== undefined) {
    validateReceipt(v3, {
      contract: POC_POSTGRES_SCHEMA_CONTRACT,
      revision: POC_POSTGRES_SCHEMA_REVISION,
      fingerprint: v3Fingerprint,
    })
  }
  if (v1 !== undefined && v3 !== undefined && v2 === undefined) {
    throw schemaError(
      'POC_POSTGRES_SCHEMA_RECEIPT_MISMATCH',
      'The Product-owned PostgreSQL schema receipt ancestry is incomplete.',
    )
  }
  return { v1, v2, v3 }
}

export function classifyPocPostgresOwnedSchema({
  rows,
  receipts = [],
  receipt,
  expectedFingerprint = POC_POSTGRES_SCHEMA_FINGERPRINT,
  v1Fingerprint = POC_POSTGRES_SCHEMA_V1_FINGERPRINT,
  v2Fingerprint = POC_POSTGRES_SCHEMA_V2_FINGERPRINT,
  migratableFingerprints = POC_POSTGRES_MIGRATABLE_FINGERPRINTS,
} = {}) {
  const normalized = canonicalizePocOwnedSchemaRows(rows)
  const receiptSet = receiptValues(receipts, receipt, {
    v1Fingerprint,
    v2Fingerprint,
    v3Fingerprint: expectedFingerprint,
  })
  if (normalized.length === 0) {
    if (receiptSet.v1 !== undefined || receiptSet.v2 !== undefined || receiptSet.v3 !== undefined) {
      throw schemaError(
        'POC_POSTGRES_SCHEMA_RECEIPT_MISMATCH',
        'A Product schema receipt exists without its owned schema.',
      )
    }
    return Object.freeze({ state: 'FRESH', fingerprint: null })
  }
  const fingerprint = fingerprintPocOwnedSchema(normalized)
  if (fingerprint === expectedFingerprint) {
    if (receiptSet.v1 !== undefined && receiptSet.v2 === undefined && receiptSet.v3 === undefined) {
      throw schemaError(
        'POC_POSTGRES_SCHEMA_RECEIPT_MISMATCH',
        'The Product-owned PostgreSQL schema receipt ancestry does not match the current schema.',
      )
    }
    const state = receiptSet.v3 !== undefined
      ? 'CURRENT'
      : receiptSet.v2 !== undefined ? 'V3_RECEIPT_PENDING' : 'CURRENT_UNVERSIONED'
    return Object.freeze({
      state,
      fingerprint,
    })
  }
  if (fingerprint === v2Fingerprint
    && receiptSet.v2 !== undefined && receiptSet.v3 === undefined) {
    return Object.freeze({ state: 'RECEIPTED_V2', fingerprint })
  }
  if (fingerprint === v2Fingerprint
    && receiptSet.v1 !== undefined && receiptSet.v2 === undefined && receiptSet.v3 === undefined) {
    return Object.freeze({ state: 'V2_RECEIPT_PENDING', fingerprint })
  }
  if (fingerprint === v1Fingerprint
    && receiptSet.v1 !== undefined && receiptSet.v2 === undefined && receiptSet.v3 === undefined) {
    return Object.freeze({ state: 'RECEIPTED_V1', fingerprint })
  }
  if (fingerprint === v1Fingerprint
    && receiptSet.v1 === undefined && receiptSet.v2 === undefined && receiptSet.v3 === undefined) {
    return Object.freeze({ state: 'V1_RECEIPT_PENDING', fingerprint })
  }
  if (migratableFingerprints.has(fingerprint)
    && receiptSet.v1 === undefined && receiptSet.v2 === undefined && receiptSet.v3 === undefined) {
    return Object.freeze({ state: 'KNOWN_OLDER_MIGRATABLE', fingerprint })
  }
  throw schemaError(
    'POC_POSTGRES_SCHEMA_INTEGRITY_FAILED',
    'The Product-owned PostgreSQL schema surface is partial, malformed or unsupported.',
  )
}

export async function inspectPocPostgresOwnedSchema(client) {
  const { rows } = await client.query(POC_POSTGRES_OWNED_SCHEMA_QUERY)
  const hasStateTable = rows.some((row) => row.kind === 'TABLE' && row.identity === 'poc_state')
  let receipts = []
  if (hasStateTable) {
    const result = await client.query(
      `SELECT scope, value FROM poc_state
        WHERE scope LIKE 'product-owned-schema-contract-v%'
        ORDER BY scope
        LIMIT 4`,
    )
    receipts = result.rows
  }
  return classifyPocPostgresOwnedSchema({ rows, receipts })
}

export async function recordPocPostgresOwnedSchemaReceipt(client) {
  const receipt = {
    contract: POC_POSTGRES_SCHEMA_CONTRACT,
    revision: POC_POSTGRES_SCHEMA_REVISION,
    fingerprint: POC_POSTGRES_SCHEMA_FINGERPRINT,
  }
  const inserted = await client.query(
    `INSERT INTO poc_state (scope, value) VALUES ($1, $2::jsonb)
      RETURNING scope`,
    [POC_POSTGRES_SCHEMA_RECEIPT_SCOPE, JSON.stringify(receipt)],
  )
  if (inserted.rows.length !== 1 || inserted.rows[0]?.scope !== POC_POSTGRES_SCHEMA_RECEIPT_SCOPE) {
    throw schemaError(
      'POC_POSTGRES_SCHEMA_RECEIPT_MISMATCH',
      'The Product-owned PostgreSQL schema receipt was not inserted.',
    )
  }
}

export async function recordPocPostgresV1SchemaReceipt(client) {
  const receipt = {
    contract: POC_POSTGRES_SCHEMA_V1_CONTRACT,
    revision: POC_POSTGRES_SCHEMA_V1_REVISION,
    fingerprint: POC_POSTGRES_SCHEMA_V1_FINGERPRINT,
  }
  const inserted = await client.query(
    `INSERT INTO poc_state (scope, value) VALUES ($1, $2::jsonb)
      RETURNING scope`,
    [POC_POSTGRES_SCHEMA_V1_RECEIPT_SCOPE, JSON.stringify(receipt)],
  )
  if (inserted.rows.length !== 1 || inserted.rows[0]?.scope !== POC_POSTGRES_SCHEMA_V1_RECEIPT_SCOPE) {
    throw schemaError(
      'POC_POSTGRES_SCHEMA_RECEIPT_MISMATCH',
      'The Product-owned PostgreSQL schema V1 receipt was not inserted.',
    )
  }
}

export async function recordPocPostgresV2SchemaReceipt(client) {
  const receipt = {
    contract: POC_POSTGRES_SCHEMA_V2_CONTRACT,
    revision: POC_POSTGRES_SCHEMA_V2_REVISION,
    fingerprint: POC_POSTGRES_SCHEMA_V2_FINGERPRINT,
  }
  const inserted = await client.query(
    `INSERT INTO poc_state (scope, value) VALUES ($1, $2::jsonb)
      RETURNING scope`,
    [POC_POSTGRES_SCHEMA_V2_RECEIPT_SCOPE, JSON.stringify(receipt)],
  )
  if (inserted.rows.length !== 1 || inserted.rows[0]?.scope !== POC_POSTGRES_SCHEMA_V2_RECEIPT_SCOPE) {
    throw schemaError(
      'POC_POSTGRES_SCHEMA_RECEIPT_MISMATCH',
      'The Product-owned PostgreSQL schema V2 receipt was not inserted.',
    )
  }
}

export async function convergePocPostgresOwnedSchema(client, {
  applyFreshSchema,
  applyKnownOlderSchema,
  applyV2Schema,
  applyV3Schema,
  inspect = inspectPocPostgresOwnedSchema,
  recordV1Receipt = recordPocPostgresV1SchemaReceipt,
  recordV2Receipt = recordPocPostgresV2SchemaReceipt,
  recordReceipt = recordPocPostgresOwnedSchemaReceipt,
} = {}) {
  if (typeof applyFreshSchema !== 'function' || typeof applyKnownOlderSchema !== 'function'
    || typeof applyV2Schema !== 'function' || typeof applyV3Schema !== 'function') {
    throw new Error('Product-owned PostgreSQL schema convergence callbacks are required.')
  }
  try {
    await client.query('BEGIN')
    const before = await inspect(client)
    if (before.state === 'FRESH') {
      await applyFreshSchema(client)
      const after = await inspect(client)
      if (after.state !== 'CURRENT_UNVERSIONED') {
        throw schemaError(
          'POC_POSTGRES_SCHEMA_MIGRATION_INCOMPLETE',
          'Fresh Product-owned PostgreSQL schema initialization was incomplete.',
        )
      }
      await recordReceipt(client)
    } else if (before.state === 'KNOWN_OLDER_MIGRATABLE') {
      await applyKnownOlderSchema(client)
      const v1Pending = await inspect(client)
      if (v1Pending.state !== 'V1_RECEIPT_PENDING') {
        throw schemaError(
          'POC_POSTGRES_SCHEMA_MIGRATION_INCOMPLETE',
          'Known older Product-owned PostgreSQL schema convergence to V1 was incomplete.',
        )
      }
      await recordV1Receipt(client)
      const v1Current = await inspect(client)
      if (v1Current.state !== 'RECEIPTED_V1') {
        throw schemaError(
          'POC_POSTGRES_SCHEMA_RECEIPT_MISMATCH',
          'The Product-owned PostgreSQL schema V1 receipt was not durable.',
        )
      }
      await applyV2Schema(client)
      const after = await inspect(client)
      if (after.state !== 'V2_RECEIPT_PENDING') {
        throw schemaError(
          'POC_POSTGRES_SCHEMA_MIGRATION_INCOMPLETE',
          'Product-owned PostgreSQL schema V1 to V2 migration was incomplete.',
        )
      }
      await recordV2Receipt(client)
      const v2Current = await inspect(client)
      if (v2Current.state !== 'RECEIPTED_V2') {
        throw schemaError(
          'POC_POSTGRES_SCHEMA_RECEIPT_MISMATCH',
          'The Product-owned PostgreSQL schema V2 receipt was not durable.',
        )
      }
      await applyV3Schema(client)
      const v3Pending = await inspect(client)
      if (v3Pending.state !== 'V3_RECEIPT_PENDING') {
        throw schemaError(
          'POC_POSTGRES_SCHEMA_MIGRATION_INCOMPLETE',
          'Product-owned PostgreSQL schema V2 to V3 migration was incomplete.',
        )
      }
      await recordReceipt(client)
    } else if (before.state === 'RECEIPTED_V1') {
      await applyV2Schema(client)
      const after = await inspect(client)
      if (after.state !== 'V2_RECEIPT_PENDING') {
        throw schemaError(
          'POC_POSTGRES_SCHEMA_MIGRATION_INCOMPLETE',
          'Product-owned PostgreSQL schema V1 to V2 migration was incomplete.',
        )
      }
      await recordV2Receipt(client)
      const v2Current = await inspect(client)
      if (v2Current.state !== 'RECEIPTED_V2') {
        throw schemaError(
          'POC_POSTGRES_SCHEMA_RECEIPT_MISMATCH',
          'The Product-owned PostgreSQL schema V2 receipt was not durable.',
        )
      }
      await applyV3Schema(client)
      const v3Pending = await inspect(client)
      if (v3Pending.state !== 'V3_RECEIPT_PENDING') {
        throw schemaError(
          'POC_POSTGRES_SCHEMA_MIGRATION_INCOMPLETE',
          'Product-owned PostgreSQL schema V2 to V3 migration was incomplete.',
        )
      }
      await recordReceipt(client)
    } else if (before.state === 'RECEIPTED_V2') {
      await applyV3Schema(client)
      const after = await inspect(client)
      if (after.state !== 'V3_RECEIPT_PENDING') {
        throw schemaError(
          'POC_POSTGRES_SCHEMA_MIGRATION_INCOMPLETE',
          'Product-owned PostgreSQL schema V2 to V3 migration was incomplete.',
        )
      }
      await recordReceipt(client)
    } else if (before.state !== 'CURRENT') {
      throw schemaError(
        'POC_POSTGRES_SCHEMA_INTEGRITY_FAILED',
        'The Product-owned PostgreSQL schema is unreceipted or partially migrated.',
      )
    }
    const current = await inspect(client)
    if (current.state !== 'CURRENT') {
      throw schemaError(
        'POC_POSTGRES_SCHEMA_RECEIPT_MISMATCH',
        'The Product-owned PostgreSQL schema V3 receipt was not durable.',
      )
    }
    await client.query('COMMIT')
    return current
  } catch (error) {
    await client.query('ROLLBACK').catch(() => undefined)
    throw error
  }
}
