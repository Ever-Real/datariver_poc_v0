/* global structuredClone */

export const POC_AUTHORIZATION_POLICY_VERSION = 'POC_PROFILE_CAPABILITIES_V1'

export const POC_CAPABILITIES = Object.freeze([
  'catalog.read',
  'catalog.execute',
  'catalog.manage',
  'chat.query',
  'change.read',
  'change.execute',
  'change.manage',
  'monitoring.read',
  'knowledge.read',
  'knowledge.manage',
  'knowledge.review',
  'quality.read',
  'quality.execute',
  'quality.manage',
  'admin.manage',
])

const viewerCapabilities = Object.freeze([
  'catalog.read', 'chat.query', 'change.read', 'monitoring.read', 'knowledge.read', 'quality.read',
])
const roleCapabilities = Object.freeze({
  viewer: viewerCapabilities,
  developer: [...viewerCapabilities, 'catalog.execute', 'change.execute', 'quality.execute'],
  data_steward: [
    ...viewerCapabilities,
    'catalog.execute', 'catalog.manage',
    'change.execute', 'change.manage',
    'quality.execute', 'quality.manage',
  ],
  manager: [
    ...viewerCapabilities,
    'catalog.execute', 'catalog.manage',
    'change.execute', 'change.manage',
    'quality.execute', 'quality.manage',
    'knowledge.manage', 'knowledge.review',
  ],
  admin: POC_CAPABILITIES,
})

const coreCapabilityByKey = Object.freeze({
  sequence: 'change.execute',
  changeRecords: 'change.execute',
  changeAttachments: 'change.execute',
  changeAttachmentLocations: 'change.execute',
  uploadRecords: 'catalog.execute',
  manualSubmissionReports: 'catalog.execute',
  monitoringConfiguration: 'admin.manage',
  adminMemberships: 'admin.manage',
  adminSystems: 'admin.manage',
  adminSystemAssignees: 'admin.manage',
  adminSystemSchemaScopes: 'admin.manage',
  knowledgeDomains: 'knowledge.manage',
  knowledgeDrafts: 'knowledge.manage',
  knowledgeReleases: 'knowledge.manage',
  knowledgeDraftBlocks: 'knowledge.manage',
  knowledgeDraftBindings: 'knowledge.manage',
  governanceDocuments: 'knowledge.manage',
  governanceVersions: 'knowledge.manage',
  governanceReviews: 'knowledge.review',
  governanceAttachments: 'knowledge.manage',
  governanceAttachmentLocations: 'knowledge.manage',
})

function authorizationError(statusCode, code, message) {
  return Object.assign(new Error(message), { statusCode, code })
}

function route(id, method, pattern, authorizationClass, capability, options = {}) {
  return Object.freeze({ id, method, pattern, authorizationClass, capability, ...options })
}

export const POC_ROUTE_REGISTRY = Object.freeze([
  route('health.liveness.get', 'GET', /^\/healthz$/, 'ANONYMOUS'),
  route('health.liveness.head', 'HEAD', /^\/healthz$/, 'ANONYMOUS'),
  route('runtime.config.get', 'GET', /^\/poc-runtime-config\.js$/, 'ANONYMOUS'),
  route('runtime.config.head', 'HEAD', /^\/poc-runtime-config\.js$/, 'ANONYMOUS'),
  route('auth.login.shell.get', 'GET', /^\/auth\/login$/, 'ANONYMOUS'),
  route('auth.login.shell.head', 'HEAD', /^\/auth\/login$/, 'ANONYMOUS'),
  route('auth.login', 'POST', /^\/auth\/login$/, 'ANONYMOUS'),
  route('auth.me', 'GET', /^\/auth\/me$/, 'AUTHENTICATED'),
  route('auth.logout', 'POST', /^\/auth\/logout$/, 'AUTHENTICATED'),
  route('change.access.read', 'GET', /^\/api\/v1\/change-history\/access$/, 'CAPABILITY_PROTECTED', 'admin.manage'),
  route('change.access.write', 'PUT', /^\/api\/v1\/change-history\/access$/, 'CAPABILITY_PROTECTED', 'admin.manage'),
  route('admin.table-system-mappings.read', 'GET', /^\/api\/v1\/admin\/table-system-mappings$/, 'CAPABILITY_PROTECTED', 'admin.manage'),
  route('admin.table-system-mappings.write', 'PATCH', /^\/api\/v1\/admin\/table-system-mappings$/, 'CAPABILITY_PROTECTED', 'admin.manage'),
  route('change.events', 'GET', /^\/api\/v1\/change-history\/events$/, 'CAPABILITY_PROTECTED', 'change.read'),
  route('change.event', 'GET', /^\/api\/v1\/change-history\/events\/[0-9a-f]{64}$/, 'CAPABILITY_PROTECTED', 'change.read'),
  route('change.event.links', 'GET', /^\/api\/v1\/change-history\/events\/[0-9a-f]{64}\/cr-links$/, 'CAPABILITY_PROTECTED', 'change.read'),
  route('change.event.command', 'POST', /^\/api\/v1\/change-history\/events\/[0-9a-f]{64}\/cr-link-events$/, 'CAPABILITY_PROTECTED', 'change.execute', { scopedMutation: true }),
  route('change.weekly', 'GET', /^\/api\/v1\/change-history\/weekly$/, 'CAPABILITY_PROTECTED', 'change.read'),
  route('change.summary', 'GET', /^\/api\/v1\/change-history\/summary$/, 'CAPABILITY_PROTECTED', 'change.read'),
  route('change.reverse', 'GET', /^\/api\/v1\/change-requests\/[^/]+\/change-history$/, 'CAPABILITY_PROTECTED', 'change.read'),
  route('registration.execute.service', 'POST', /^\/api\/v1\/registration\/bulk-preparations\/execute$/, 'INTERNAL_SERVICE'),
  route('state.read', 'GET', /^\/poc-api\/state\/(core|knowledge|governance)$/, 'CAPABILITY_PROTECTED', 'catalog.read'),
  route('state.write', 'PUT', /^\/poc-api\/state\/(core|knowledge|governance)$/, 'CAPABILITY_PROTECTED', null),
  route('providers.capabilities', 'GET', /^\/poc-api\/capabilities$/, 'CAPABILITY_PROTECTED', 'monitoring.read'),
  route('catalog.search', 'GET', /^\/poc-api\/datahub\/catalog$/, 'CAPABILITY_PROTECTED', 'catalog.read'),
  route('catalog.tree', 'GET', /^\/poc-api\/datahub\/tree$/, 'CAPABILITY_PROTECTED', 'catalog.read'),
  route('catalog.facets', 'GET', /^\/poc-api\/datahub\/facets$/, 'CAPABILITY_PROTECTED', 'catalog.read'),
  route('catalog.dashboard', 'GET', /^\/poc-api\/datahub\/dashboard$/, 'CAPABILITY_PROTECTED', 'catalog.read'),
  route('catalog.profile-coverage', 'GET', /^\/poc-api\/datahub\/profile-coverage$/, 'CAPABILITY_PROTECTED', 'quality.read'),
  route('catalog.vector-index', 'GET', /^\/poc-api\/datahub\/vector-index$/, 'CAPABILITY_PROTECTED', 'catalog.read'),
  route('catalog.systems', 'GET', /^\/poc-api\/datahub\/systems$/, 'CAPABILITY_PROTECTED', 'catalog.read'),
  route('catalog.glossary', 'GET', /^\/poc-api\/datahub\/glossary$/, 'CAPABILITY_PROTECTED', 'catalog.read'),
  route('catalog.glossary-assignments', 'GET', /^\/poc-api\/datahub\/glossary\/assignments$/, 'CAPABILITY_PROTECTED', 'catalog.read'),
  route('catalog.asset', 'GET', /^\/poc-api\/datahub\/asset$/, 'CAPABILITY_PROTECTED', 'catalog.read'),
  route('catalog.lineage', 'GET', /^\/poc-api\/datahub\/lineage$/, 'CAPABILITY_PROTECTED', 'catalog.read'),
  route('catalog.manual-metadata', 'POST', /^\/poc-api\/datahub\/manual-metadata$/, 'CAPABILITY_PROTECTED', 'catalog.manage', { scopedMutation: true }),
  route('catalog.template.xlsx', 'GET', /^\/poc-api\/templates\/catalog-metadata\.xlsx$/, 'CAPABILITY_PROTECTED', 'catalog.read'),
  route('catalog.template.csv', 'GET', /^\/poc-api\/templates\/catalog-metadata\.csv$/, 'CAPABILITY_PROTECTED', 'catalog.read'),
  route('catalog.bulk.create', 'POST', /^\/poc-api\/bulk\/preparations$/, 'CAPABILITY_PROTECTED', 'catalog.execute', { scopedMutation: true }),
  route('catalog.bulk.list', 'GET', /^\/poc-api\/bulk\/uploads\/[a-zA-Z0-9_-]+\/preparations$/, 'CAPABILITY_PROTECTED', 'catalog.read'),
  route('catalog.bulk.candidates', 'GET', /^\/poc-api\/bulk\/uploads\/[a-zA-Z0-9_-]+\/preparations\/[^/]+\/metadata-candidates$/, 'CAPABILITY_PROTECTED', 'catalog.read'),
  route('catalog.bulk.preview', 'GET', /^\/poc-api\/bulk\/uploads\/[a-zA-Z0-9_-]+\/preparations\/[^/]+\/metadata-candidates\/[^/]+\/preview$/, 'CAPABILITY_PROTECTED', 'catalog.read'),
  route('chat.query', 'POST', /^\/poc-api\/llm\/chat$/, 'CAPABILITY_PROTECTED', 'chat.query'),
  route('chat.compact', 'POST', /^\/poc-api\/llm\/chat\/compact$/, 'CAPABILITY_PROTECTED', 'chat.query'),
  route('chat.stream', 'POST', /^\/poc-api\/llm\/chat\/stream$/, 'CAPABILITY_PROTECTED', 'chat.query'),
  route('provider.airflow', 'POST', /^\/poc-api\/airflow\/dags\/[^/]+\/runs$/, 'CAPABILITY_PROTECTED', 'admin.manage'),
  route('provider.minio.part', 'PUT', /^\/poc-api\/minio\/uploads\/[a-zA-Z0-9_-]+\/parts\/\d+$/, 'CAPABILITY_PROTECTED', 'catalog.execute', { scopedMutation: true }),
  route('provider.minio.complete', 'POST', /^\/poc-api\/minio\/uploads\/[a-zA-Z0-9_-]+\/complete$/, 'CAPABILITY_PROTECTED', 'catalog.execute', { scopedMutation: true }),
  route('provider.minio.accepted', 'GET', /^\/poc-api\/minio\/accepted\/[a-zA-Z0-9_-]+\/[^/]+$/, 'CAPABILITY_PROTECTED', 'catalog.read'),
  route('provider.neo4j', 'GET', /^\/poc-api\/neo4j\/graph$/, 'CAPABILITY_PROTECTED', 'catalog.read'),
  route('api.disabled', '*', /^\/(api\/v1|poc-api)\/?$/, 'DISABLED'),
])

export function resolvePocRoute(method, pathname) {
  const normalizedMethod = String(method || '').toUpperCase()
  const matches = POC_ROUTE_REGISTRY.filter((entry) => (
    (entry.method === '*' || entry.method === normalizedMethod) && entry.pattern.test(pathname)
  ))
  if (matches.length > 1) throw new Error(`POC route registry is ambiguous for ${normalizedMethod} ${pathname}.`)
  return matches[0] ?? null
}

export function buildPocPrincipal({ authentication, accessDocument, accessUser }) {
  if (!authentication || authentication.subjectId !== accessUser?.subject_id || !accessUser.active) {
    throw authorizationError(403, 'SUBJECT_FORBIDDEN', 'The current authenticated subject is not active.')
  }
  const capabilities = roleCapabilities[accessUser.role]
  if (!capabilities) throw authorizationError(403, 'PROFILE_ROLE_UNSUPPORTED', 'The current profile role is unsupported.')
  const allowedResponsibilities = accessUser.role === 'manager'
    ? new Set(['DEVELOPER', 'DATA_STEWARD'])
    : accessUser.role === 'developer'
      ? new Set(['DEVELOPER'])
      : accessUser.role === 'data_steward'
        ? new Set(['DATA_STEWARD'])
        : new Set()
  const systemIds = new Set((accessDocument.system_assignments || [])
    .filter((item) => item.active && item.subject_id === accessUser.subject_id
      && allowedResponsibilities.has(item.responsibility))
    .map((item) => item.system_id))
  return Object.freeze({
    subjectId: accessUser.subject_id,
    role: accessUser.role,
    capabilities: Object.freeze([...capabilities]),
    capabilitySet: new Set(capabilities),
    systemIds,
    globalSystemRead: accessUser.role === 'admin' || accessUser.role === 'viewer',
    globalSystemMutation: accessUser.role === 'admin',
    accessDocument,
  })
}

export function authorizationProjection(principal) {
  return {
    policy_version: POC_AUTHORIZATION_POLICY_VERSION,
    role: principal.role,
    capabilities: [...principal.capabilities],
    system_scope: principal.globalSystemRead ? 'GLOBAL' : 'ASSIGNED',
    system_ids: [...principal.systemIds].sort(),
  }
}

export function assertPocRouteAuthorization(routeEntry, principal) {
  if (!routeEntry || routeEntry.authorizationClass === 'DISABLED') {
    throw authorizationError(404, 'NOT_FOUND', 'The POC gateway route does not exist.')
  }
  if (routeEntry.authorizationClass === 'INTERNAL_SERVICE') return
  if (!principal) throw authorizationError(401, 'SESSION_REQUIRED', 'A valid local session is required.')
  if (routeEntry.authorizationClass === 'CAPABILITY_PROTECTED' && routeEntry.capability
    && !principal.capabilitySet.has(routeEntry.capability)) {
    throw authorizationError(403, 'CAPABILITY_REQUIRED', `${routeEntry.capability} is required.`)
  }
}

export function assetSystemResolution(asset, accessDocument) {
  if (!asset || typeof asset !== 'object') return { resolution: 'UNRESOLVED', systemId: null }
  const platform = String(asset.platform || '').trim().toLowerCase()
  const databaseName = String(asset.database_name || '').trim()
  const schemaName = String(asset.schema_name || '').trim()
  if (!platform || !databaseName || !schemaName) return { resolution: 'UNRESOLVED', systemId: null }
  const activeSystems = new Set((accessDocument.systems || [])
    .filter((system) => system.active)
    .map((system) => system.system_id))
  const matches = (accessDocument.system_schema_scopes || []).filter((scope) => scope.active
    && activeSystems.has(scope.system_id)
    && scope.platform === platform
    && scope.database_name === databaseName
    && scope.schema_name === schemaName)
  return matches.length === 1
    ? { resolution: 'RESOLVED', systemId: matches[0].system_id }
    : { resolution: matches.length > 1 ? 'AMBIGUOUS' : 'UNRESOLVED', systemId: null }
}

export function canReadAsset(principal, asset) {
  if (principal.globalSystemRead) return true
  const resolved = assetSystemResolution(asset, principal.accessDocument)
  return resolved.resolution === 'RESOLVED' && principal.systemIds.has(resolved.systemId)
}

export function filterAssetsForPrincipal(principal, assets) {
  return (Array.isArray(assets) ? assets : []).filter((asset) => canReadAsset(principal, asset))
}

export function assertAssetMutation(principal, asset) {
  if (principal.globalSystemMutation) return
  const resolved = assetSystemResolution(asset, principal.accessDocument)
  if (resolved.resolution !== 'RESOLVED') {
    throw authorizationError(403, 'SYSTEM_SCOPE_UNRESOLVED', 'The mutation target does not resolve to one active System.')
  }
  if (!principal.systemIds.has(resolved.systemId)) {
    throw authorizationError(403, 'SYSTEM_SCOPE_FORBIDDEN', 'The mutation target is outside the current System assignment.')
  }
}

function recordSystemIds(record) {
  const values = new Set()
  const visit = (value, key = '') => {
    if (Array.isArray(value)) return value.forEach((item) => visit(item, key))
    if (!value || typeof value !== 'object') {
      if (typeof value === 'string' && ['system_id', 'selected_system_id', 'routing_system_id'].includes(key)) values.add(value)
      return
    }
    for (const [nestedKey, nested] of Object.entries(value)) visit(nested, nestedKey)
  }
  visit(record)
  return values
}

function filterSystemRecords(principal, values) {
  if (principal.globalSystemRead) return values
  return (Array.isArray(values) ? values : []).filter((item) => {
    const ids = recordSystemIds(item)
    return ids.size > 0 && [...ids].every((id) => principal.systemIds.has(id))
  })
}

export function filterCoreStateForPrincipal(principal, value) {
  if (value === null || principal.role === 'admin') return value
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const filtered = structuredClone(value)
  if (Array.isArray(filtered.changeRecords)) filtered.changeRecords = filterSystemRecords(principal, filtered.changeRecords)
  const visibleChangeIds = new Set((Array.isArray(filtered.changeRecords) ? filtered.changeRecords : [])
    .map((item) => item?.id).filter((id) => typeof id === 'string'))
  for (const key of ['changeAttachments', 'changeAttachmentLocations']) {
    if (Array.isArray(filtered[key])) {
      filtered[key] = filtered[key].filter((entry) => Array.isArray(entry) && visibleChangeIds.has(entry[0]))
    }
  }
  const allowedSystems = principal.globalSystemRead
    ? new Set((principal.accessDocument.systems || []).filter((item) => item.active).map((item) => item.system_id))
    : principal.systemIds
  filtered.adminMemberships = (Array.isArray(filtered.adminMemberships) ? filtered.adminMemberships : [])
    .filter((item) => item?.subject_id === principal.subjectId)
  filtered.adminSystems = (Array.isArray(filtered.adminSystems) ? filtered.adminSystems : [])
    .filter((item) => allowedSystems.has(item?.system_id))
  filtered.adminSystemAssignees = (Array.isArray(filtered.adminSystemAssignees) ? filtered.adminSystemAssignees : [])
    .filter((entry) => Array.isArray(entry) && allowedSystems.has(entry[0]))
    .map(([systemId, assignees]) => [systemId, (Array.isArray(assignees) ? assignees : [])
      .filter((item) => item?.subject_id === principal.subjectId)])
  filtered.adminSystemSchemaScopes = (Array.isArray(filtered.adminSystemSchemaScopes) ? filtered.adminSystemSchemaScopes : [])
    .filter((entry) => Array.isArray(entry) && allowedSystems.has(entry[0]))
  return filtered
}

function sameJson(left, right) {
  return JSON.stringify(left) === JSON.stringify(right)
}

export function authorizeCoreReplacement(principal, currentValue, proposedValue) {
  if (!proposedValue || typeof proposedValue !== 'object' || Array.isArray(proposedValue)) {
    throw authorizationError(409, 'CORE_STATE_INVALID', 'Core state must be a JSON object.')
  }
  const current = currentValue && typeof currentValue === 'object' && !Array.isArray(currentValue)
    ? currentValue
    : {}
  const visibleCurrent = filterCoreStateForPrincipal(principal, current) ?? {}
  const keys = new Set([...Object.keys(visibleCurrent), ...Object.keys(proposedValue)])
  if (keys.size > Object.keys(coreCapabilityByKey).length) {
    throw authorizationError(400, 'CORE_DIFF_INVALID', 'Core state contains an unknown top-level key.')
  }
  const changedKeys = [...keys].filter((key) => !sameJson(visibleCurrent[key], proposedValue[key]))
  const replacement = structuredClone(current)
  for (const key of changedKeys) {
    const capability = coreCapabilityByKey[key]
    if (!capability) throw authorizationError(400, 'CORE_DIFF_INVALID', `Core state key ${key} is not allowlisted.`)
    if (!principal.capabilitySet.has(capability)) {
      throw authorizationError(403, 'CAPABILITY_REQUIRED', `${capability} is required to change core.${key}.`)
    }
    if (key === 'changeRecords' && !principal.globalSystemMutation) {
      const records = Array.isArray(proposedValue[key]) ? proposedValue[key] : []
      const currentById = new Map((Array.isArray(visibleCurrent[key]) ? visibleCurrent[key] : [])
        .filter((record) => record && typeof record.id === 'string')
        .map((record) => [record.id, record]))
      for (const record of records) {
        const prior = record && typeof record.id === 'string' ? currentById.get(record.id) : undefined
        if (!prior) {
          throw authorizationError(403, 'SYSTEM_SCOPE_UNRESOLVED', 'A new Change record requires a server-resolved System mutation route.')
        }
        const ids = recordSystemIds(record)
        const priorIds = recordSystemIds(prior)
        if (ids.size === 0 || priorIds.size === 0) {
          throw authorizationError(403, 'SYSTEM_SCOPE_UNRESOLVED', 'Every changed Change record must resolve to an active assigned System.')
        }
        if ([...ids].sort().join('\u0000') !== [...priorIds].sort().join('\u0000')) {
          throw authorizationError(403, 'SYSTEM_SCOPE_SPOOFED', 'A client cannot change a Change record System binding.')
        }
        if ([...ids].some((id) => !principal.systemIds.has(id))) {
          throw authorizationError(403, 'SYSTEM_SCOPE_FORBIDDEN', 'A changed Change record is outside the current System assignment.')
        }
      }
    }
    if (!principal.globalSystemMutation && ['changeAttachments', 'changeAttachmentLocations'].includes(key)) {
      const visibleIds = new Set((Array.isArray(visibleCurrent.changeRecords) ? visibleCurrent.changeRecords : [])
        .map((item) => item?.id).filter((id) => typeof id === 'string'))
      const invalid = (Array.isArray(proposedValue[key]) ? proposedValue[key] : [])
        .some((entry) => !Array.isArray(entry) || !visibleIds.has(entry[0]))
      if (invalid) {
        throw authorizationError(403, 'SYSTEM_SCOPE_UNRESOLVED', `core.${key} contains a Change record outside the current System scope.`)
      }
    }
    if (!principal.globalSystemRead && ['changeRecords', 'changeAttachments', 'changeAttachmentLocations'].includes(key)) {
      const visibleIds = new Set((Array.isArray(visibleCurrent.changeRecords) ? visibleCurrent.changeRecords : [])
        .map((item) => item?.id).filter((id) => typeof id === 'string'))
      const hidden = (Array.isArray(current[key]) ? current[key] : []).filter((item) => {
        const id = key === 'changeRecords' ? item?.id : Array.isArray(item) ? item[0] : undefined
        return typeof id !== 'string' || !visibleIds.has(id)
      })
      replacement[key] = [...(Array.isArray(proposedValue[key]) ? proposedValue[key] : []), ...hidden]
    } else if (Object.hasOwn(proposedValue, key)) {
      replacement[key] = structuredClone(proposedValue[key])
    } else {
      delete replacement[key]
    }
  }
  return Object.freeze({ changedKeys: Object.freeze(changedKeys.sort()), value: replacement })
}
