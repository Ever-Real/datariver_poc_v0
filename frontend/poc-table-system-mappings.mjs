/* global structuredClone */
import { legacyTagTaxonomyGrade, securityGradeRank, SECURITY_GRADES as POC_SECURITY_GRADES } from './poc-access-document.mjs'

export const POC_TABLE_SYSTEM_MAPPING_SCOPE = 'table-system-mappings-v1'
export const POC_TABLE_SYSTEM_MAPPING_SCHEMA_VERSION = 2

export { POC_SECURITY_GRADES }
const securityGrades = new Set(POC_SECURITY_GRADES)
const maximumBindings = 50_000
const maximumTableIdsPerCommand = 2_000
const maximumSystemIdsPerCommand = 20
const maximumOperationsPerCommand = 20_000

function mappingError(code, message) {
  return Object.assign(new Error(message), { statusCode: 400, code })
}

function exactKeys(value, expected, label) {
  const actual = Object.keys(value).sort()
  const wanted = [...expected].sort()
  if (actual.length !== wanted.length || actual.some((key, index) => key !== wanted[index])) {
    throw mappingError('TABLE_SYSTEM_MAPPING_INVALID', `${label} contains unsupported fields.`)
  }
}

function boundedText(value, maximum, label) {
  if (typeof value !== 'string' || !value.trim() || value.length > maximum) {
    throw mappingError('TABLE_SYSTEM_MAPPING_INVALID', `${label} is invalid.`)
  }
  return value.trim()
}

function boundedOptionalText(value, maximum, label) {
  if (typeof value !== 'string' || value.length > maximum
    || [...value].some((character) => character.codePointAt(0) <= 0x1f || character.codePointAt(0) === 0x7f)) {
    throw mappingError('TABLE_SYSTEM_MAPPING_INVALID', `${label} is invalid.`)
  }
  return value.trim()
}

function timestamp(value, label) {
  const normalized = boundedText(value, 40, label)
  if (!Number.isFinite(Date.parse(normalized))) {
    throw mappingError('TABLE_SYSTEM_MAPPING_INVALID', `${label} is invalid.`)
  }
  return normalized
}

function uniqueBoundedStrings(value, maximumItems, maximumLength, label) {
  if (!Array.isArray(value) || value.length === 0 || value.length > maximumItems) {
    throw mappingError('TABLE_SYSTEM_COMMAND_INVALID', `${label} must contain 1-${maximumItems} values.`)
  }
  const normalized = value.map((item) => boundedText(item, maximumLength, label))
  if (new Set(normalized).size !== normalized.length) {
    throw mappingError('TABLE_SYSTEM_COMMAND_INVALID', `${label} must not contain duplicates.`)
  }
  return normalized
}

function normalizeBinding(value, index) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw mappingError('TABLE_SYSTEM_MAPPING_INVALID', `bindings[${index}] must be an object.`)
  }
  exactKeys(value, [
    'table_identity', 'system_id', 'active', 'version',
    'created_at', 'created_by', 'updated_at', 'updated_by', 'reason',
  ], `bindings[${index}]`)
  const version = Number(value.version)
  if (!Number.isSafeInteger(version) || version < 1) {
    throw mappingError('TABLE_SYSTEM_MAPPING_INVALID', `bindings[${index}].version is invalid.`)
  }
  if (typeof value.active !== 'boolean') {
    throw mappingError('TABLE_SYSTEM_MAPPING_INVALID', `bindings[${index}].active is invalid.`)
  }
  return {
    table_identity: boundedText(value.table_identity, 4_096, `bindings[${index}].table_identity`),
    system_id: boundedText(value.system_id, 200, `bindings[${index}].system_id`),
    active: value.active,
    version,
    created_at: timestamp(value.created_at, `bindings[${index}].created_at`),
    created_by: boundedText(value.created_by, 200, `bindings[${index}].created_by`),
    updated_at: timestamp(value.updated_at, `bindings[${index}].updated_at`),
    updated_by: boundedText(value.updated_by, 200, `bindings[${index}].updated_by`),
    reason: boundedText(value.reason, 1_000, `bindings[${index}].reason`),
  }
}

function normalizeAssetSnapshot(value, index) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw mappingError('TABLE_SYSTEM_MAPPING_INVALID', `asset_snapshots[${index}] must be an object.`)
  }
  exactKeys(value, [
    'table_identity', 'dataset_kind', 'platform', 'database_name', 'schema_name',
    'asset_name', 'security_grade', 'observed_at',
  ], `asset_snapshots[${index}]`)
  if (value.dataset_kind !== 'TABLE' || !securityGrades.has(value.security_grade)) {
    throw mappingError('TABLE_SYSTEM_MAPPING_INVALID', `asset_snapshots[${index}] is not a canonical Table snapshot.`)
  }
  return {
    table_identity: boundedText(value.table_identity, 4_096, `asset_snapshots[${index}].table_identity`),
    dataset_kind: 'TABLE',
    platform: boundedText(value.platform, 255, `asset_snapshots[${index}].platform`).toLowerCase(),
    database_name: boundedOptionalText(value.database_name, 500, `asset_snapshots[${index}].database_name`),
    schema_name: boundedText(value.schema_name, 500, `asset_snapshots[${index}].schema_name`),
    asset_name: boundedText(value.asset_name, 1_000, `asset_snapshots[${index}].asset_name`),
    security_grade: value.security_grade,
    observed_at: timestamp(value.observed_at, `asset_snapshots[${index}].observed_at`),
  }
}

export function tableAuthoritySnapshot(asset, observedAt = new Date().toISOString()) {
  if (!asset || asset.dataset_kind !== 'TABLE') {
    throw mappingError('TABLE_SYSTEM_MAPPING_INVALID', 'Only a current DataHub Table can be snapshotted.')
  }
  return normalizeAssetSnapshot({
    table_identity: asset.id,
    dataset_kind: asset.dataset_kind,
    platform: asset.platform,
    database_name: asset.database_name,
    schema_name: asset.schema_name,
    asset_name: asset.name || asset.id,
    security_grade: typeof asset.security_grade === 'string' ? asset.security_grade : legacyTableTagGrade(asset),
    observed_at: observedAt,
  }, 0)
}

export function normalizeTableSystemMappingDocument(value) {
  if (value === null || value === undefined) {
    return { schema_version: POC_TABLE_SYSTEM_MAPPING_SCHEMA_VERSION, bindings: [], asset_snapshots: [] }
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw mappingError('TABLE_SYSTEM_MAPPING_INVALID', 'The Table-System mapping document must be an object.')
  }
  const isLegacy = value.schema_version === 1
  exactKeys(value, isLegacy ? ['schema_version', 'bindings'] : ['schema_version', 'bindings', 'asset_snapshots'], 'Table-System mapping document')
  if (!isLegacy && value.schema_version !== POC_TABLE_SYSTEM_MAPPING_SCHEMA_VERSION) {
    throw mappingError('TABLE_SYSTEM_MAPPING_INVALID', 'The Table-System mapping schema version is unsupported.')
  }
  if (!Array.isArray(value.bindings) || value.bindings.length > maximumBindings) {
    throw mappingError('TABLE_SYSTEM_MAPPING_INVALID', `bindings must contain at most ${maximumBindings} rows.`)
  }
  const bindings = value.bindings.map(normalizeBinding)
  const keys = bindings.map((item) => `${item.table_identity}\u0000${item.system_id}`)
  if (new Set(keys).size !== keys.length) {
    throw mappingError('TABLE_SYSTEM_MAPPING_INVALID', 'A Table-System pair must be unique.')
  }
  const assetSnapshots = isLegacy ? [] : value.asset_snapshots.map(normalizeAssetSnapshot)
  if (assetSnapshots.length > maximumBindings
    || new Set(assetSnapshots.map((item) => item.table_identity)).size !== assetSnapshots.length) {
    throw mappingError('TABLE_SYSTEM_MAPPING_INVALID', 'asset_snapshots must contain unique bounded Table identities.')
  }
  return { schema_version: POC_TABLE_SYSTEM_MAPPING_SCHEMA_VERSION, bindings, asset_snapshots: assetSnapshots }
}

// Historical/admin display compatibility only. This value is never an
// authorization authority and never determines K9 source inclusion.
export function legacyTableTagGrade(asset) {
  const tags = [
    ...(Array.isArray(asset?.tags) ? asset.tags : []),
    ...(Array.isArray(asset?.tag_references) ? asset.tag_references : []),
  ]
  return legacyTagTaxonomyGrade(tags)
}

export { securityGradeRank }

export function activeSystemIdsForTable(document, tableIdentity, activeSystemIds) {
  const activeSystems = activeSystemIds instanceof Set ? activeSystemIds : new Set(activeSystemIds || [])
  return normalizeTableSystemMappingDocument(document).bindings
    .filter((item) => item.active && item.table_identity === tableIdentity && activeSystems.has(item.system_id))
    .map((item) => item.system_id)
    .sort()
}

export function resolveTableSystemAuthority({
  document,
  tableIdentity,
  activeSystemIds,
  legacySystemId = null,
  allowLegacyFallback = true,
}) {
  const normalized = normalizeTableSystemMappingDocument(document)
  const table = boundedText(tableIdentity, 4_096, 'tableIdentity')
  const activeSystems = activeSystemIds instanceof Set ? activeSystemIds : new Set(activeSystemIds || [])
  const exactRows = normalized.bindings.filter((item) => item.table_identity === table)
  if (exactRows.length) {
    const systemIds = [...new Set(exactRows
      .filter((item) => item.active && activeSystems.has(item.system_id))
      .map((item) => item.system_id))].sort()
    return {
      system_ids: systemIds,
      provenance: 'EXACT',
      conflict: typeof legacySystemId === 'string' && legacySystemId.length > 0
        ? systemIds.length !== 1 || systemIds[0] !== legacySystemId
        : false,
    }
  }
  if (allowLegacyFallback && typeof legacySystemId === 'string' && activeSystems.has(legacySystemId)) {
    return { system_ids: [legacySystemId], provenance: 'LEGACY_FALLBACK', conflict: false }
  }
  return { system_ids: [], provenance: 'NONE', conflict: false }
}

export function applyTableSystemMappingCommand(
  document,
  command,
  actor,
  now = new Date().toISOString(),
  tableSnapshots = [],
) {
  if (!command || typeof command !== 'object' || Array.isArray(command)) {
    throw mappingError('TABLE_SYSTEM_COMMAND_INVALID', 'A mapping command object is required.')
  }
  exactKeys(command, ['action', 'table_ids', 'system_ids', 'reason'], 'Table-System mapping command')
  const action = command.action
  if (!['ASSIGN', 'REMOVE'].includes(action)) {
    throw mappingError('TABLE_SYSTEM_COMMAND_INVALID', 'action must be ASSIGN or REMOVE.')
  }
  const tableIds = uniqueBoundedStrings(command.table_ids, maximumTableIdsPerCommand, 4_096, 'table_ids')
  const systemIds = uniqueBoundedStrings(command.system_ids, maximumSystemIdsPerCommand, 200, 'system_ids')
  if (tableIds.length * systemIds.length > maximumOperationsPerCommand) {
    throw mappingError('TABLE_SYSTEM_COMMAND_INVALID', `A command may change at most ${maximumOperationsPerCommand} Table-System pairs.`)
  }
  const reason = boundedText(command.reason, 1_000, 'reason')
  if (reason.length < 10) {
    throw mappingError('TABLE_SYSTEM_COMMAND_INVALID', 'reason must contain at least 10 characters.')
  }
  const actorId = boundedText(actor, 200, 'actor')
  const changedAt = timestamp(now, 'now')
  const next = structuredClone(normalizeTableSystemMappingDocument(document))
  const snapshotByTable = new Map(tableSnapshots.map((item, index) => {
    const snapshot = normalizeAssetSnapshot(item, index)
    return [snapshot.table_identity, snapshot]
  }))
  if (snapshotByTable.size !== tableSnapshots.length
    || [...snapshotByTable.keys()].some((tableIdentity) => !tableIds.includes(tableIdentity))) {
    throw mappingError('TABLE_SYSTEM_MAPPING_INVALID', 'Table snapshots must be unique and match the requested Tables.')
  }
  const storedSnapshotByTable = new Map(next.asset_snapshots.map((item) => [item.table_identity, item]))
  const byKey = new Map(next.bindings.map((item) => [`${item.table_identity}\u0000${item.system_id}`, item]))
  let changed = 0
  for (const tableIdentity of tableIds) {
    for (const systemId of systemIds) {
      const key = `${tableIdentity}\u0000${systemId}`
      const existing = byKey.get(key)
      if (action === 'ASSIGN') {
        if (existing?.active) continue
        if (existing) {
          existing.active = true
          existing.version += 1
          existing.updated_at = changedAt
          existing.updated_by = actorId
          existing.reason = reason
        } else {
          const binding = {
            table_identity: tableIdentity,
            system_id: systemId,
            active: true,
            version: 1,
            created_at: changedAt,
            created_by: actorId,
            updated_at: changedAt,
            updated_by: actorId,
            reason,
          }
          next.bindings.push(binding)
          byKey.set(key, binding)
        }
        changed += 1
        const snapshot = snapshotByTable.get(tableIdentity)
        if (snapshot) storedSnapshotByTable.set(tableIdentity, snapshot)
      } else if (existing?.active) {
        existing.active = false
        existing.version += 1
        existing.updated_at = changedAt
        existing.updated_by = actorId
        existing.reason = reason
        changed += 1
      }
    }
  }
  if (next.bindings.length > maximumBindings) {
    throw mappingError('TABLE_SYSTEM_MAPPING_LIMIT', `The mapping document may contain at most ${maximumBindings} rows.`)
  }
  next.bindings.sort((left, right) => (
    left.table_identity.localeCompare(right.table_identity) || left.system_id.localeCompare(right.system_id)
  ))
  next.asset_snapshots = [...storedSnapshotByTable.values()]
    .sort((left, right) => left.table_identity.localeCompare(right.table_identity))
  return { document: next, changed }
}

export function tableSystemCandidates({ assets, document, systems, query = '', schema = '', systemId = '', securityGrade = '' }) {
  if (securityGrade && !securityGrades.has(securityGrade)) {
    throw mappingError('TABLE_SYSTEM_QUERY_INVALID', 'security_grade is invalid.')
  }
  const normalizedDocument = normalizeTableSystemMappingDocument(document)
  const activeSystems = new Map((Array.isArray(systems) ? systems : [])
    .filter((system) => system?.active)
    .map((system) => [system.system_id, system]))
  const bindingsByTable = new Map()
  for (const binding of normalizedDocument.bindings) {
    if (!binding.active || !activeSystems.has(binding.system_id)) continue
    const values = bindingsByTable.get(binding.table_identity) || []
    values.push(binding.system_id)
    bindingsByTable.set(binding.table_identity, values)
  }
  const search = query.trim().toLocaleLowerCase()
  return (Array.isArray(assets) ? assets : []).flatMap((asset) => {
    if (!asset || asset.dataset_kind !== 'TABLE' || typeof asset.id !== 'string') return []
    const grade = legacyTableTagGrade(asset)
    const systemIds = [...new Set(bindingsByTable.get(asset.id) || [])].sort()
    if (schema && asset.schema_name !== schema) return []
    if (systemId && !systemIds.includes(systemId)) return []
    if (securityGrade && grade !== securityGrade) return []
    const haystack = [asset.name, asset.platform, asset.database_name, asset.schema_name, asset.id]
      .filter(Boolean).join(' ').toLocaleLowerCase()
    if (search && !haystack.includes(search)) return []
    return [{
      table_identity: asset.id,
      table_name: asset.name || asset.id,
      platform: asset.platform || '',
      database_name: asset.database_name || '',
      schema_name: asset.schema_name || '',
      security_grade: grade,
      system_ids: systemIds,
    }]
  }).sort((left, right) => (
    left.schema_name.localeCompare(right.schema_name)
    || left.table_name.localeCompare(right.table_name)
    || left.table_identity.localeCompare(right.table_identity)
  ))
}
