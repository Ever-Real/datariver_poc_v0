/* global structuredClone */
// Dependencies are supplied by bootstrap; this module never constructs a shared client.
export function createModulesAdminApplication(deps) {
async function writeAdminAccessDocument(context, snapshot, document) {
  const normalized = deps.normalizeChangeHistoryAccessDocument(document, { allowUnresolvedActiveSubject: true })
  return context.stateStore.writeChangeHistoryAccess({
    expectedAccessVersion: snapshot.access.version,
    expectedCoreVersion: snapshot.core.version,
    accessValue: deps.privateChangeHistoryAccess(normalized),
    coreValue: deps.changeHistoryAccessCoreProjection(snapshot.core.value, normalized, snapshot.access.version + 1),
  })
}

function responsibleSystemsForUser(document, user) {
  const bySystem = new Map()
  for (const assignment of document.system_assignments) {
    if (!assignment.active || assignment.subject_id !== user.subject_id) continue
    const current = bySystem.get(assignment.system_id)
    if (!current || assignment.priority < current.priority) {
      bySystem.set(assignment.system_id, {
        system_id: assignment.system_id,
        priority: assignment.priority,
        responsibility: assignment.responsibility,
      })
    }
  }
  return [...bySystem.values()].sort((left, right) => (
    left.priority - right.priority || left.system_id.localeCompare(right.system_id)
  ))
}

function normalizedLocalHumanEmail(value) {
  const normalized = deps.boundedString(value, 320).normalize('NFKC').trim().toLocaleLowerCase()
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/u.test(normalized)) {
    throw deps.accessError(400, 'USER_EMAIL_INVALID', 'The local human email is invalid.')
  }
  return normalized
}

async function localHumanPasswordHash(value, code) {
  try {
    return await deps.hashPocPassword(value)
  } catch {
    throw deps.accessError(400, code, 'The password must contain at least 8 characters and at most 1024 UTF-8 bytes.')
  }
}

async function adminUsersApi(request, response, url, context) {
  const snapshot = await context.stateStore.readChangeHistoryAccess()
  const document = deps.changeHistoryDocumentFromSnapshot(snapshot)
  deps.requireActiveAccessAdmin(document, context.principal.subjectId)
  const userMatch = url.pathname.match(/^\/api\/v1\/admin\/users\/([^/]+)$/)
  const grantsMatch = url.pathname.match(/^\/api\/v1\/admin\/users\/([^/]+)\/table-grants$/)
  const credentialMatch = url.pathname.match(/^\/api\/v1\/admin\/users\/([^/]+)\/credential$/)
  const sessionsMatch = url.pathname.match(/^\/api\/v1\/admin\/users\/([^/]+)\/sessions\/revoke$/)

  if (url.pathname === '/api/v1/admin/users' && request.method === 'GET') {
    const credentials = new Map((await context.stateStore.listLocalCredentialAdministration())
      .map((item) => [item.subjectId, item]))
    const items = await Promise.all(document.users.map(async (user) => ({
      subject_id: user.subject_id,
      username: user.username ?? credentials.get(user.subject_id)?.usernameNormalized ?? null,
      display_name: user.display_name ?? user.subject_id,
      email: user.email ?? null,
      role: user.role,
      active: user.active,
      max_security_grade: user.max_security_grade ?? 'normal',
      responsible_systems: responsibleSystemsForUser(document, user),
      table_grant_count: (await context.stateStore.listUserTableGrants(user.subject_id)).length,
      credential: credentials.has(user.subject_id) ? {
        username: credentials.get(user.subject_id).usernameNormalized,
        login_enabled: credentials.get(user.subject_id).loginEnabled,
        must_change_password: credentials.get(user.subject_id).mustChangePassword,
        failed_attempts: credentials.get(user.subject_id).failedAttempts,
        locked_until: credentials.get(user.subject_id).lockedUntil,
        version: credentials.get(user.subject_id).version,
        active_session_count: credentials.get(user.subject_id).activeSessionCount,
      } : null,
    })))
    return deps.json(response, 200, {
      version: snapshot.access.version,
      items,
      systems: document.systems.filter((system) => system.active),
    }, { ETag: `"${snapshot.access.version}"` })
  }

  if (url.pathname === '/api/v1/admin/users' && request.method === 'POST') {
    const expectedVersion = deps.accessIfMatch(request)
    if (expectedVersion !== snapshot.access.version) throw deps.accessError(409, 'ACCESS_VERSION_STALE', 'The access version is stale.')
    const body = await deps.bodyJson(request)
    deps.exactBodyKeys(body, [
      'username', 'password', 'display_name', 'email', 'role', 'max_security_grade',
      'responsible_systems', 'must_change_password',
    ])
    const username = deps.normalizePocUsername(body.username)
    const displayName = deps.boundedString(body.display_name, 255).trim()
    const email = normalizedLocalHumanEmail(body.email)
    const role = deps.boundedString(body.role, 32).trim()
    if (!displayName || !role || !document.users.every((user) => user.username !== username)
      || !['admin', 'data_steward', 'developer', 'manager', 'viewer'].includes(role)) {
      throw deps.accessError(400, 'USER_CREATE_INVALID', 'The new local human user is outside the canonical contract.')
    }
    if (document.users.some((user) => (
      typeof user.email === 'string'
      && user.email.normalize('NFKC').trim().toLocaleLowerCase() === email
    ))) {
      throw deps.accessError(409, 'USER_EMAIL_EXISTS', 'The local human email already exists.')
    }
    if (typeof body.must_change_password !== 'boolean') {
      throw deps.accessError(400, 'USER_CREATE_INVALID', 'must_change_password must be boolean.')
    }
    const subjectId = deps.randomUUID()
    const user = {
      subject_id: subjectId,
      username,
      display_name: displayName,
      email,
      role,
      active: true,
      max_security_grade: deps.normalizedSecurityGrade(body.max_security_grade),
      provider_owner_refs: [],
    }
    const next = structuredClone(document)
    next.users.push(user)
    next.system_assignments.push(...deps.normalizedResponsibleSystems(body.responsible_systems, role, next)
      .map((assignment) => ({ ...assignment, subject_id: subjectId })))
    const normalized = deps.normalizeChangeHistoryAccessDocument(next, { allowUnresolvedActiveSubject: true })
    const passwordHash = await localHumanPasswordHash(body.password, 'USER_PASSWORD_INVALID')
    const result = await context.stateStore.provisionLocalCredential({
      actorSubjectId: context.principal.subjectId,
      expectedAccessVersion: snapshot.access.version,
      expectedCoreVersion: snapshot.core.version,
      credential: {
        subjectId,
        usernameNormalized: username,
        passwordHash,
        loginEnabled: true,
        mustChangePassword: body.must_change_password,
      },
      accessValue: deps.privateChangeHistoryAccess(normalized),
      coreValue: deps.changeHistoryAccessCoreProjection(snapshot.core.value, normalized, snapshot.access.version + 1),
    })
    return deps.json(response, 201, {
      subject_id: subjectId,
      access_version: result.accessVersion,
      credential_version: result.credentialVersion,
    }, { ETag: `"${result.accessVersion}"` })
  }

  if (userMatch && request.method === 'PATCH') {
    const expectedVersion = deps.accessIfMatch(request)
    if (expectedVersion !== snapshot.access.version) throw deps.accessError(409, 'ACCESS_VERSION_STALE', 'The access version is stale.')
    const subjectId = decodeURIComponent(userMatch[1])
    const body = await deps.bodyJson(request)
    deps.exactBodyKeys(body, ['display_name', 'email', 'role', 'active', 'max_security_grade', 'responsible_systems'])
    const user = document.users.find((item) => item.subject_id === subjectId)
    if (!user) throw deps.accessError(404, 'USER_NOT_FOUND', 'The access user was not found.')
    const role = deps.boundedString(body.role, 32).trim()
    if (!['admin', 'data_steward', 'developer', 'manager', 'viewer'].includes(role)
      || typeof body.active !== 'boolean') {
      throw deps.accessError(400, 'USER_UPDATE_INVALID', 'The requested user authority is invalid.')
    }
    if (subjectId === context.principal.subjectId && (!body.active || role !== 'admin')) {
      throw deps.accessError(409, 'ADMIN_SELF_LOCKOUT_FORBIDDEN', 'The current admin cannot deactivate or demote the current session subject.')
    }
    const remainingAdmins = document.users.filter((item) => (
      item.subject_id !== subjectId && item.active && item.role === 'admin'
    )).length
    if ((!body.active || role !== 'admin') && user.active && user.role === 'admin' && remainingAdmins === 0) {
      throw deps.accessError(409, 'LAST_ADMIN_REQUIRED', 'At least one other active application admin is required.')
    }
    user.display_name = deps.boundedString(body.display_name, 255).trim()
    const email = normalizedLocalHumanEmail(body.email)
    if (document.users.some((item) => (
      item.subject_id !== subjectId
      && typeof item.email === 'string'
      && item.email.normalize('NFKC').trim().toLocaleLowerCase() === email
    ))) {
      throw deps.accessError(409, 'USER_EMAIL_EXISTS', 'The local human email already exists.')
    }
    user.email = email
    if (!user.display_name || !user.email) throw deps.accessError(400, 'USER_UPDATE_INVALID', 'Display name and email are required.')
    user.role = role
    user.active = body.active
    user.max_security_grade = deps.normalizedSecurityGrade(body.max_security_grade)
    document.system_assignments = document.system_assignments.filter((assignment) => assignment.subject_id !== subjectId)
    if (user.active) {
      document.system_assignments.push(...deps.normalizedResponsibleSystems(body.responsible_systems, role, document)
        .map((assignment) => ({ ...assignment, subject_id: subjectId })))
    } else if (body.responsible_systems.length) {
      throw deps.accessError(400, 'RESPONSIBLE_SYSTEM_INVALID', 'Inactive users cannot retain Responsible Systems.')
    }
    const result = await writeAdminAccessDocument(context, snapshot, document)
    const revokedSessionCount = user.active ? 0 : await context.stateStore.revokeLocalSessionsForSubject({
      subjectId,
      revokedAt: new Date().toISOString(),
    })
    return deps.json(response, 200, {
      subject_id: subjectId,
      access_version: result.accessVersion,
      revoked_session_count: revokedSessionCount,
    }, { ETag: `"${result.accessVersion}"` })
  }

  if (grantsMatch) {
    const subjectId = decodeURIComponent(grantsMatch[1])
    const user = document.users.find((item) => item.subject_id === subjectId)
    if (!user) throw deps.accessError(404, 'USER_NOT_FOUND', 'The access user was not found.')
    if (request.method === 'GET') {
      const inventory = await deps.datahubInventory()
      const mappingSnapshot = await context.stateStore.read(deps.POC_TABLE_SYSTEM_MAPPING_SCOPE)
      const mappingDocument = deps.normalizeTableSystemMappingDocument(mappingSnapshot.value)
      const grants = new Set((await context.stateStore.listUserTableGrants(subjectId)).map((grant) => grant.tableUrn))
      const requestedLimit = Number(url.searchParams.get('limit') || 2_000)
      const limit = Number.isSafeInteger(requestedLimit) && requestedLimit >= 1 && requestedLimit <= 2_000 ? requestedLimit : 2_000
      let candidates = deps.tableSystemCandidates({
        assets: inventory,
        document: mappingDocument,
        systems: document.systems,
        query: deps.boundedString(url.searchParams.get('q'), 500),
        schema: deps.boundedString(url.searchParams.get('schema'), 500),
        systemId: deps.boundedString(url.searchParams.get('system_id'), 200),
        securityGrade: deps.boundedString(url.searchParams.get('security_grade'), 20),
      }).map((item) => ({ ...item, granted: grants.has(item.table_identity) }))
      const grantedFilter = url.searchParams.get('granted')
      if (grantedFilter === 'true') candidates = candidates.filter((item) => item.granted)
      if (grantedFilter === 'false') candidates = candidates.filter((item) => !item.granted)
      return deps.json(response, 200, {
        subject_id: subjectId,
        items: candidates.slice(0, limit),
        total: candidates.length,
        selection_complete: candidates.length <= limit,
        schemas: [...new Set(inventory.filter((asset) => asset?.dataset_kind === 'TABLE').map((asset) => asset.schema_name))].sort(),
      })
    }
    if (request.method === 'PATCH') {
      const body = await deps.bodyJson(request)
      deps.exactBodyKeys(body, ['action', 'table_ids'])
      if (!['GRANT', 'REMOVE'].includes(body.action) || !Array.isArray(body.table_ids)
        || body.table_ids.length < 1 || body.table_ids.length > 2_000
        || new Set(body.table_ids).size !== body.table_ids.length
        || body.table_ids.some((item) => typeof item !== 'string')) {
        throw deps.accessError(400, 'USER_TABLE_GRANT_INVALID', 'A bounded GRANT or REMOVE command with unique Table identities is required.')
      }
      await deps.confirmedCurrentTables(
        context,
        body.table_ids,
        'USER_TABLE_CURRENT_TABLES_UNAVAILABLE',
        'USER_TABLE_IDENTITY_INVALID',
      )
      const changed = await context.stateStore.applyUserTableGrantCommand({
        subjectId,
        tableUrns: body.table_ids,
        action: body.action,
        actorSubjectId: context.principal.subjectId,
        changedAt: new Date().toISOString(),
      })
      return deps.json(response, 200, { subject_id: subjectId, changed })
    }
    return deps.problem(response, 405, 'METHOD_NOT_ALLOWED', 'User Table grants support only GET and PATCH.')
  }

  if (credentialMatch && request.method === 'PUT') {
    const subjectId = decodeURIComponent(credentialMatch[1])
    if (!document.users.some((user) => user.subject_id === subjectId)) {
      throw deps.accessError(404, 'USER_NOT_FOUND', 'The access user was not found.')
    }
    const expectedVersion = deps.accessIfMatch(request)
    const body = await deps.bodyJson(request)
    deps.exactBodyKeys(body, ['username', 'password', 'login_enabled', 'must_change_password'], [
      'username', 'login_enabled', 'must_change_password',
    ])
    if (typeof body.login_enabled !== 'boolean' || typeof body.must_change_password !== 'boolean') {
      throw deps.accessError(400, 'CREDENTIAL_ADMIN_INVALID', 'Credential flags must be boolean.')
    }
    const passwordHash = body.password === undefined
      ? null
      : await localHumanPasswordHash(body.password, 'CREDENTIAL_PASSWORD_INVALID')
    const result = await context.stateStore.administerLocalCredential({
      subjectId,
      expectedVersion,
      usernameNormalized: deps.normalizePocUsername(body.username),
      passwordHash,
      loginEnabled: body.login_enabled,
      mustChangePassword: body.must_change_password,
      changedAt: new Date().toISOString(),
    })
    return deps.json(response, 200, {
      subject_id: subjectId,
      credential_version: result.credentialVersion,
      revoked_session_count: result.revokedSessionCount,
    }, { ETag: `"${result.credentialVersion}"` })
  }

  if (sessionsMatch && request.method === 'POST') {
    const subjectId = decodeURIComponent(sessionsMatch[1])
    if (!document.users.some((user) => user.subject_id === subjectId)) {
      throw deps.accessError(404, 'USER_NOT_FOUND', 'The access user was not found.')
    }
    deps.exactBodyKeys(await deps.bodyJson(request), [], [])
    const changed = await context.stateStore.revokeLocalSessionsForSubject({
      subjectId,
      revokedAt: new Date().toISOString(),
    })
    return deps.json(response, 200, { subject_id: subjectId, revoked_session_count: changed })
  }

  return deps.problem(response, 405, 'METHOD_NOT_ALLOWED', 'The account administration route does not support this method.')
}

async function tableSystemMappingApi(request, response, url, context) {
  const snapshot = await context.stateStore.read(deps.POC_TABLE_SYSTEM_MAPPING_SCOPE)
  const document = deps.normalizeTableSystemMappingDocument(snapshot.value)
  const systems = context.accessDocument.systems || []
  if (request.method === 'GET') {
    const inventory = await deps.datahubInventory()
    const requestedLimit = Number(url.searchParams.get('limit') || 2_000)
    const limit = Number.isSafeInteger(requestedLimit) && requestedLimit >= 1 && requestedLimit <= 2_000
      ? requestedLimit
      : 2_000
    const candidates = deps.tableSystemCandidates({
      assets: inventory,
      document,
      systems,
      query: deps.boundedString(url.searchParams.get('q'), 500),
      schema: deps.boundedString(url.searchParams.get('schema'), 500),
      systemId: deps.boundedString(url.searchParams.get('system_id'), 200),
      securityGrade: deps.boundedString(url.searchParams.get('security_grade'), 20),
    })
    const items = candidates.slice(0, limit)
    return deps.json(response, 200, {
      version: snapshot.version,
      items,
      total: candidates.length,
      selection_complete: candidates.length <= limit,
      schemas: [...new Set(inventory
        .filter((asset) => asset?.dataset_kind === 'TABLE' && typeof asset.schema_name === 'string')
        .map((asset) => asset.schema_name))].sort(),
    }, { ETag: `"${snapshot.version}"` })
  }
  if (request.method !== 'PATCH') {
    return deps.problem(response, 405, 'METHOD_NOT_ALLOWED', 'Table-System mappings support only GET and PATCH.')
  }
  const expectedVersion = deps.tableSystemIfMatch(request)
  if (expectedVersion !== snapshot.version) {
    throw deps.accessError(409, 'TABLE_SYSTEM_MAPPING_VERSION_STALE', 'The Table-System mapping version is stale.')
  }
  const body = await deps.bodyJson(request)
  deps.rejectProtectedAccessBodyClaims(body)
  const requestedSystems = Array.isArray(body.system_ids) ? body.system_ids.map(String) : []
  const activeSystems = new Set(systems.filter((system) => system.active).map((system) => system.system_id))
  if (requestedSystems.some((systemId) => !activeSystems.has(systemId))) {
    throw deps.accessError(400, 'TABLE_SYSTEM_SYSTEM_INVALID', 'Every selected System must exist and be active in the current access authority.')
  }
  const requestedTables = Array.isArray(body.table_ids) ? body.table_ids.map(String) : []
  const confirmedTables = await deps.confirmedCurrentTables(
    context,
    requestedTables,
    'TABLE_SYSTEM_CURRENT_TABLES_UNAVAILABLE',
    'TABLE_SYSTEM_TABLE_INVALID',
  )
  let authorityAssets = []
  if (body.action === 'ASSIGN') {
    let inventory
    try {
      inventory = await context.currentDatahubInventory()
      if (!Array.isArray(inventory)) throw new Error('DataHub returned an invalid current inventory.')
    } catch {
      throw deps.accessError(503, 'TABLE_SYSTEM_CURRENT_TABLES_UNAVAILABLE', 'Current DataHub Table identities could not be confirmed; no change was made.')
    }
    const confirmedIds = new Set(confirmedTables.map((asset) => asset.id))
    authorityAssets = inventory.filter((asset) => confirmedIds.has(asset?.id) && asset?.dataset_kind === 'TABLE')
    if (authorityAssets.length !== confirmedIds.size) {
      throw deps.accessError(503, 'TABLE_SYSTEM_CURRENT_TABLES_UNAVAILABLE', 'Current DataHub Table hierarchy could not be confirmed; no change was made.')
    }
  }
  const observedAt = new Date().toISOString()
  const applied = deps.applyTableSystemMappingCommand(
    document,
    body,
    context.principal.subjectId,
    observedAt,
    body.action === 'ASSIGN'
      ? authorityAssets.map((asset) => deps.tableAuthoritySnapshot(asset, observedAt))
      : [],
  )
  if (applied.changed === 0) {
    return deps.json(response, 200, { version: snapshot.version, changed: 0 }, { ETag: `"${snapshot.version}"` })
  }
  const version = await context.stateStore.writeIfVersion(
    deps.POC_TABLE_SYSTEM_MAPPING_SCOPE,
    applied.document,
    expectedVersion,
  )
  return deps.json(response, 200, { version, changed: applied.changed }, { ETag: `"${version}"` })
}

function adminSystemIdempotencyKey(request) {
  const value = request.headers['idempotency-key']
  if (typeof value !== 'string' || value.length < 16 || value.length > 200 || deps.hasAccessControlCharacter(value)) {
    throw deps.accessError(428, 'IDEMPOTENCY_KEY_REQUIRED', 'A bounded Idempotency-Key is required for System creation.')
  }
  return value
}

function generatedSystemCode(name, identityHash) {
  const normalized = name.normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^A-Za-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .toUpperCase()
  const base = /^[A-Z]/.test(normalized) ? normalized.slice(0, 72) : 'SYSTEM'
  return `${base}_${identityHash.slice(0, 12).toUpperCase()}`
}

async function adminSystemsApi(request, response, context) {
  if (request.method !== 'POST') {
    return deps.problem(response, 405, 'METHOD_NOT_ALLOWED', 'System creation supports POST only.')
  }
  const snapshot = await context.stateStore.readChangeHistoryAccess()
  const document = deps.changeHistoryDocumentFromSnapshot(snapshot)
  deps.requireActiveAccessAdmin(document, context.principal.subjectId)
  const idempotencyKey = adminSystemIdempotencyKey(request)
  const body = await deps.bodyJson(request)
  deps.exactBodyKeys(body, ['name', 'description'], ['name'])
  const name = typeof body.name === 'string' ? body.name.trim() : ''
  const description = body.description === undefined
    ? ''
    : typeof body.description === 'string' ? body.description.trim() : null
  if (!name || name.length > 255 || description === null || description.length > 2_000
    || deps.hasAccessControlCharacter(name) || deps.hasAccessControlCharacter(description)) {
    throw deps.accessError(400, 'SYSTEM_INPUT_INVALID', 'System name and description are invalid or too long.')
  }
  const identityHash = deps.canonicalHash({
    actor_subject_id: context.principal.subjectId,
    idempotency_key: idempotencyKey,
  })
  const systemId = `system-${identityHash.slice(0, 32)}`
  const code = generatedSystemCode(name, identityHash)
  const replay = document.systems.find((system) => system.system_id === systemId)
  if (replay) {
    if (replay.code !== code || replay.name !== name || replay.description !== description) {
      throw deps.accessError(409, 'SYSTEM_IDEMPOTENCY_CONFLICT', 'The Idempotency-Key is already bound to another System request.')
    }
    return deps.json(response, 200, replay, { ETag: `"${snapshot.access.version}"` })
  }
  if (document.systems.some((system) => system.code.toLocaleLowerCase() === code.toLocaleLowerCase())) {
    throw deps.accessError(409, 'SYSTEM_CODE_CONFLICT', 'The generated System code conflicts with an existing System.')
  }
  const system = { system_id: systemId, code, name, description, active: true, version: 1 }
  document.systems.push(system)
  let result
  try {
    result = await writeAdminAccessDocument(context, snapshot, document)
  } catch (error) {
    if (error?.code === 'STATE_VERSION_STALE') {
      throw deps.accessError(409, 'ACCESS_VERSION_STALE', 'The access authority changed while the System was created. Refresh and retry.')
    }
    throw error
  }
  return deps.json(response, 201, system, { ETag: `"${result.accessVersion}"` })
}

async function featureSecurityPolicyApi(request, response, context) {
  const snapshot = await context.stateStore.read(deps.POC_FEATURE_SECURITY_POLICY_SCOPE)
  const document = deps.normalizePersistedFeatureSecurityPolicy(snapshot.value)
  if (request.method === 'GET') {
    return deps.json(response, 200, { version: snapshot.version, ...document }, { ETag: `"${snapshot.version}"` })
  }
  if (request.method !== 'PUT') {
    return deps.problem(response, 405, 'METHOD_NOT_ALLOWED', 'Feature security policy supports only GET and PUT.')
  }
  const expectedVersion = deps.featureSecurityPolicyIfMatch(request)
  if (expectedVersion !== snapshot.version) {
    throw deps.accessError(409, 'FEATURE_SECURITY_POLICY_VERSION_STALE', 'The feature security policy version is stale.')
  }
  const body = await deps.bodyJson(request)
  const next = deps.applyFeatureSecurityPolicyUpdate(document, body, context.principal.subjectId)
  const version = await context.stateStore.writeIfVersion(deps.POC_FEATURE_SECURITY_POLICY_SCOPE, next, expectedVersion)
  return deps.json(response, 200, { version, ...next }, { ETag: `"${version}"` })
}

function siteBrandingIdempotencyKey(request) {
  const value = request.headers['idempotency-key']
  if (typeof value !== 'string' || !value.trim() || value.length > 200 || deps.hasAccessControlCharacter(value)) {
    throw deps.accessError(428, 'IDEMPOTENCY_KEY_REQUIRED', 'A bounded Idempotency-Key is required for site branding changes.')
  }
  return value.trim()
}

async function siteBrandingApi(request, response, context) {
  const snapshot = await context.stateStore.read(deps.POC_SITE_BRANDING_SCOPE)
  const current = deps.normalizeSiteBrandingDocument(snapshot.value)
  if (request.method === 'GET') {
    return deps.json(response, 200, deps.publicSiteBranding(current), { ETag: `"${snapshot.version}"` })
  }
  if (request.method !== 'PUT') {
    return deps.problem(response, 405, 'METHOD_NOT_ALLOWED', 'Site branding supports only GET and PUT.')
  }
  const expectedVersion = deps.siteBrandingIfMatch(request)
  const idempotencyKey = siteBrandingIdempotencyKey(request)
  const body = await deps.bodyJson(request)
  const keyHash = deps.siteBrandingIdempotencyHash(idempotencyKey)
  const requestHash = deps.siteBrandingRequestHash(body)
  const replay = current.idempotency_receipts.find((receipt) => receipt.key_hash === keyHash)
  if (replay) {
    if (replay.request_hash !== requestHash) {
      throw deps.accessError(409, 'SITE_BRANDING_IDEMPOTENCY_CONFLICT', 'The Idempotency-Key is already bound to another site branding request.')
    }
    return deps.json(response, 200, replay.projection, { ETag: `"${replay.version}"` })
  }
  if (expectedVersion !== snapshot.version) {
    throw deps.accessError(409, 'SITE_BRANDING_VERSION_STALE', 'The site branding version is stale.')
  }
  const applied = deps.applySiteBrandingUpdate(current, body, {
    actor: context.principal.subjectId,
    idempotencyKey,
    version: expectedVersion + 1,
    occurredAt: new Date().toISOString(),
  })
  try {
    const version = await context.stateStore.writeIfVersion(
      deps.POC_SITE_BRANDING_SCOPE,
      applied.document,
      expectedVersion,
    )
    return deps.json(response, 200, applied.projection, { ETag: `"${version}"` })
  } catch (error) {
    if (error?.code !== 'STATE_VERSION_STALE') throw error
    const concurrent = deps.normalizeSiteBrandingDocument((await context.stateStore.read(deps.POC_SITE_BRANDING_SCOPE)).value)
    const concurrentReplay = concurrent.idempotency_receipts.find((receipt) => receipt.key_hash === keyHash)
    if (concurrentReplay?.request_hash === requestHash) {
      return deps.json(response, 200, concurrentReplay.projection, { ETag: `"${concurrentReplay.version}"` })
    }
    throw deps.accessError(409, 'SITE_BRANDING_VERSION_STALE', 'The site branding version is stale.')
  }
}

return { writeAdminAccessDocument, responsibleSystemsForUser, normalizedLocalHumanEmail, localHumanPasswordHash, adminUsersApi, tableSystemMappingApi, adminSystemIdempotencyKey, generatedSystemCode, adminSystemsApi, featureSecurityPolicyApi, siteBrandingIdempotencyKey, siteBrandingApi }
}
