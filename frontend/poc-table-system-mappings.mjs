/* global structuredClone */

export const POC_TABLE_SYSTEM_MAPPING_SCOPE = 'table-system-mappings-v1'
export const POC_TABLE_SYSTEM_MAPPING_SCHEMA_VERSION = 1

const securityGrades = new Set(['normal', 'restricted', 'credential'])
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

export function normalizeTableSystemMappingDocument(value) {
  if (value === null || value === undefined) {
    return { schema_version: POC_TABLE_SYSTEM_MAPPING_SCHEMA_VERSION, bindings: [] }
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw mappingError('TABLE_SYSTEM_MAPPING_INVALID', 'The Table-System mapping document must be an object.')
  }
  exactKeys(value, ['schema_version', 'bindings'], 'Table-System mapping document')
  if (value.schema_version !== POC_TABLE_SYSTEM_MAPPING_SCHEMA_VERSION) {
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
  return { schema_version: POC_TABLE_SYSTEM_MAPPING_SCHEMA_VERSION, bindings }
}

export function tableSecurityGrade(asset) {
  const tags = [
    ...(Array.isArray(asset?.tags) ? asset.tags : []),
    ...(Array.isArray(asset?.tag_references) ? asset.tag_references : []),
  ]
  const normalized = new Set(tags.flatMap((tag) => {
    if (typeof tag === 'string') return [tag.trim().toLocaleLowerCase()]
    if (!tag || typeof tag !== 'object' || Array.isArray(tag)) return []
    return [tag.name, tag.urn].filter((item) => typeof item === 'string')
      .map((item) => item.trim().toLocaleLowerCase())
  }))
  if (normalized.has('credential') || normalized.has('urn:li:tag:credential')) return 'credential'
  if (normalized.has('restricted') || normalized.has('urn:li:tag:restricted')) return 'restricted'
  return 'normal'
}

export function activeSystemIdsForTable(document, tableIdentity, activeSystemIds) {
  const activeSystems = activeSystemIds instanceof Set ? activeSystemIds : new Set(activeSystemIds || [])
  return normalizeTableSystemMappingDocument(document).bindings
    .filter((item) => item.active && item.table_identity === tableIdentity && activeSystems.has(item.system_id))
    .map((item) => item.system_id)
    .sort()
}

export function applyTableSystemMappingCommand(document, command, actor, now = new Date().toISOString()) {
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
    const grade = tableSecurityGrade(asset)
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
