/* global structuredClone */

export const CHANGE_HISTORY_ACCESS_ROLES = Object.freeze([
  'admin', 'data_steward', 'developer', 'manager', 'viewer',
])
export const CHANGE_HISTORY_RESPONSIBILITIES = Object.freeze(['DATA_STEWARD', 'DEVELOPER', 'MANAGER'])
export const SECURITY_GRADES = Object.freeze(['normal', 'credential', 'restricted'])

export function normalizeSecurityGrade(value, code = 'SECURITY_GRADE_INVALID', message = 'The security grade is invalid.') {
  if (value === 'restricted' || value === 'credential' || value === 'normal') return value
  throw Object.assign(new Error(message), { statusCode: 400, code })
}

export function securityGradeRank(value) {
  return SECURITY_GRADES.indexOf(normalizeSecurityGrade(value, 'SECURITY_GRADE_INVALID', 'The security grade is outside the canonical product policy.'))
}

export function compareSecurityGrades(left, right) {
  return securityGradeRank(left) - securityGradeRank(right)
}

export function tagPrecedenceSecurityGrade(tags) {
  if (!Array.isArray(tags)) return 'normal'
  const normalized = new Set(tags.flatMap((tag) => {
    if (typeof tag === 'string') return [tag.trim().toLowerCase()]
    if (!tag || typeof tag !== 'object' || Array.isArray(tag)) return []
    return [tag.name, tag.urn].filter((item) => typeof item === 'string')
      .map((item) => item.trim().toLowerCase())
  }))
  if (normalized.has('restricted') || normalized.has('urn:li:tag:restricted')) return 'restricted'
  if (normalized.has('credential') || normalized.has('urn:li:tag:credential')) return 'credential'
  return 'normal'
}

const changeHistoryAccessRoles = new Set(CHANGE_HISTORY_ACCESS_ROLES)
const changeHistoryResponsibilities = new Set(CHANGE_HISTORY_RESPONSIBILITIES)

function accessError(statusCode, code, message) {
  return Object.assign(new Error(message), { statusCode, code })
}

function accessRecord(value, field) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw accessError(400, 'ACCESS_DOCUMENT_INVALID', `${field} must be an object.`)
  }
  return value
}

function exactAccessKeys(value, field, allowed, required = allowed) {
  const keys = Object.keys(value)
  const unknown = keys.find((key) => !allowed.includes(key))
  const missing = required.find((key) => !Object.hasOwn(value, key))
  if (unknown || missing) {
    throw accessError(400, 'ACCESS_DOCUMENT_INVALID', unknown
      ? `${field}.${unknown} is not allowed.`
      : `${field}.${missing} is required.`)
  }
}

function hasAccessControlCharacter(value) {
  return [...value].some((character) => {
    const codePoint = character.codePointAt(0)
    return codePoint <= 0x1f || codePoint === 0x7f
  })
}

function accessString(value, field, maximum) {
  if (typeof value !== 'string') {
    throw accessError(400, 'ACCESS_DOCUMENT_INVALID', `${field} must be a string.`)
  }
  const normalized = value.trim()
  if (!normalized || normalized.length > maximum || hasAccessControlCharacter(normalized)) {
    throw accessError(400, 'ACCESS_DOCUMENT_INVALID', `${field} is outside its bounded string contract.`)
  }
  return normalized
}

function accessOptionalString(value, field, maximum) {
  if (typeof value !== 'string' || value.length > maximum || hasAccessControlCharacter(value)) {
    throw accessError(400, 'ACCESS_DOCUMENT_INVALID', `${field} is outside its bounded string contract.`)
  }
  return value.trim()
}

function accessBoolean(value, field) {
  if (typeof value !== 'boolean') {
    throw accessError(400, 'ACCESS_DOCUMENT_INVALID', `${field} must be boolean.`)
  }
  return value
}

function accessPositiveInteger(value, field) {
  if (!Number.isSafeInteger(value) || value < 1) {
    throw accessError(400, 'ACCESS_DOCUMENT_INVALID', `${field} must be a positive integer.`)
  }
  return value
}

function accessArray(value, field, maximum) {
  if (!Array.isArray(value) || value.length > maximum) {
    throw accessError(400, 'ACCESS_DOCUMENT_INVALID', `${field} must contain at most ${maximum} items.`)
  }
  return value
}

function normalizedAccessUsers(value) {
  const subjects = new Set()
  const users = accessArray(value, 'users', 500).map((raw, index) => {
    const user = accessRecord(raw, `users[${index}]`)
    exactAccessKeys(user, `users[${index}]`, [
      'subject_id', 'role', 'active', 'provider_owner_refs', 'username', 'display_name', 'email',
      'first_name', 'last_name', 'department_id', 'job_function', 'max_security_grade',
    ], [
      'subject_id', 'role', 'active',
    ])
    const subjectId = accessString(user.subject_id, `users[${index}].subject_id`, 255)
    const role = accessString(user.role, `users[${index}].role`, 32)
    if (!changeHistoryAccessRoles.has(role) || subjects.has(subjectId)) {
      throw accessError(400, 'ACCESS_DOCUMENT_INVALID', `users[${index}] has a duplicate subject or unknown role.`)
    }
    const ownerRefs = accessArray(user.provider_owner_refs ?? [], `users[${index}].provider_owner_refs`, 100)
      .map((item, ownerIndex) => accessString(item, `users[${index}].provider_owner_refs[${ownerIndex}]`, 1024))
    if (new Set(ownerRefs).size !== ownerRefs.length) {
      throw accessError(400, 'ACCESS_DOCUMENT_INVALID', `users[${index}].provider_owner_refs contains duplicates.`)
    }
    subjects.add(subjectId)
    const maximumSecurityGrade = normalizeSecurityGrade(
      accessString(
        user.max_security_grade ?? 'normal',
        `users[${index}].max_security_grade`,
        20,
      ),
      'ACCESS_DOCUMENT_INVALID',
      `users[${index}].max_security_grade is unknown.`,
    )
    return {
      subject_id: subjectId,
      role,
      active: accessBoolean(user.active, `users[${index}].active`),
      max_security_grade: maximumSecurityGrade,
      provider_owner_refs: ownerRefs.sort(),
      ...(user.username === undefined
        ? {} : { username: accessString(user.username, `users[${index}].username`, 64) }),
      ...(user.display_name === undefined
        ? {} : { display_name: accessString(user.display_name, `users[${index}].display_name`, 255) }),
      ...(user.email === undefined
        ? {} : { email: accessOptionalString(user.email, `users[${index}].email`, 320) }),
      ...(user.first_name === undefined
        ? {} : { first_name: accessOptionalString(user.first_name, `users[${index}].first_name`, 100) }),
      ...(user.last_name === undefined
        ? {} : { last_name: accessOptionalString(user.last_name, `users[${index}].last_name`, 100) }),
      ...(user.department_id === undefined
        ? {} : {
            department_id: user.department_id === null
              ? null
              : accessOptionalString(user.department_id, `users[${index}].department_id`, 255) || null,
          }),
      ...(user.job_function === undefined
        ? {} : {
            job_function: user.job_function === null
              ? null
              : accessOptionalString(user.job_function, `users[${index}].job_function`, 100) || null,
          }),
    }
  })
  return users.sort((left, right) => left.subject_id.localeCompare(right.subject_id))
}

function normalizedAccessSystems(value) {
  const ids = new Set()
  const codes = new Set()
  const systems = accessArray(value, 'systems', 500).map((raw, index) => {
    const system = accessRecord(raw, `systems[${index}]`)
    exactAccessKeys(system, `systems[${index}]`, [
      'system_id', 'code', 'name', 'description', 'active', 'version',
    ], ['system_id', 'code', 'name', 'active'])
    const systemId = accessString(system.system_id, `systems[${index}].system_id`, 255)
    const code = accessString(system.code, `systems[${index}].code`, 100)
    const normalizedCode = code.toLowerCase()
    if (ids.has(systemId) || codes.has(normalizedCode)) {
      throw accessError(400, 'ACCESS_DOCUMENT_INVALID', `systems[${index}] has a duplicate id or code.`)
    }
    ids.add(systemId)
    codes.add(normalizedCode)
    return {
      system_id: systemId,
      code,
      name: accessString(system.name, `systems[${index}].name`, 255),
      description: system.description === undefined ? '' : accessOptionalString(system.description, `systems[${index}].description`, 2000),
      active: accessBoolean(system.active, `systems[${index}].active`),
      version: system.version === undefined ? 1 : accessPositiveInteger(system.version, `systems[${index}].version`),
    }
  })
  return systems.sort((left, right) => left.system_id.localeCompare(right.system_id))
}

function normalizedAccessScopes(value, systems) {
  const systemById = new Map(systems.map((system) => [system.system_id, system]))
  const ids = new Set()
  const activeMappings = new Set()
  const scopes = accessArray(value, 'system_schema_scopes', 2_000).map((raw, index) => {
    const scope = accessRecord(raw, `system_schema_scopes[${index}]`)
    exactAccessKeys(scope, `system_schema_scopes[${index}]`, [
      'scope_id', 'system_id', 'platform', 'database_name', 'schema_name', 'active', 'version',
    ], ['scope_id', 'system_id', 'platform', 'database_name', 'schema_name', 'active'])
    const scopeId = accessString(scope.scope_id, `system_schema_scopes[${index}].scope_id`, 255)
    const systemId = accessString(scope.system_id, `system_schema_scopes[${index}].system_id`, 255)
    const system = systemById.get(systemId)
    const platform = accessString(scope.platform, `system_schema_scopes[${index}].platform`, 100).toLowerCase()
    const databaseName = accessString(scope.database_name, `system_schema_scopes[${index}].database_name`, 255)
    const schemaName = accessString(scope.schema_name, `system_schema_scopes[${index}].schema_name`, 255)
    const active = accessBoolean(scope.active, `system_schema_scopes[${index}].active`)
    const mappingKey = JSON.stringify([platform, databaseName, schemaName])
    if (ids.has(scopeId) || !system || (active && (!system.active || activeMappings.has(mappingKey)))) {
      throw accessError(400, 'ACCESS_DOCUMENT_INVALID', `system_schema_scopes[${index}] is duplicate, unmapped, or ambiguous.`)
    }
    ids.add(scopeId)
    if (active) activeMappings.add(mappingKey)
    return {
      scope_id: scopeId,
      system_id: systemId,
      platform,
      database_name: databaseName,
      schema_name: schemaName,
      active,
      version: scope.version === undefined ? 1 : accessPositiveInteger(scope.version, `system_schema_scopes[${index}].version`),
    }
  })
  return scopes.sort((left, right) => left.scope_id.localeCompare(right.scope_id))
}

function normalizedAccessAssignments(value, users, systems) {
  const userById = new Map(users.map((user) => [user.subject_id, user]))
  const systemById = new Map(systems.map((system) => [system.system_id, system]))
  const keys = new Set()
  const assignments = accessArray(value, 'system_assignments', 2_000).map((raw, index) => {
    const assignment = accessRecord(raw, `system_assignments[${index}]`)
    exactAccessKeys(assignment, `system_assignments[${index}]`, [
      'system_id', 'subject_id', 'responsibility', 'priority', 'active',
    ])
    const systemId = accessString(assignment.system_id, `system_assignments[${index}].system_id`, 255)
    const subjectId = accessString(assignment.subject_id, `system_assignments[${index}].subject_id`, 255)
    const responsibility = accessString(assignment.responsibility, `system_assignments[${index}].responsibility`, 32)
    const active = accessBoolean(assignment.active, `system_assignments[${index}].active`)
    const key = JSON.stringify([systemId, subjectId, responsibility])
    const user = userById.get(subjectId)
    const system = systemById.get(systemId)
    if (!changeHistoryResponsibilities.has(responsibility) || keys.has(key) || !user?.active || !system
      || (active && !system.active)) {
      throw accessError(400, 'ACCESS_DOCUMENT_INVALID', `system_assignments[${index}] is duplicate or references an inactive/unknown subject or System.`)
    }
    keys.add(key)
    return {
      system_id: systemId,
      subject_id: subjectId,
      responsibility,
      priority: accessPositiveInteger(assignment.priority, `system_assignments[${index}].priority`),
      active,
    }
  })
  return assignments.sort((left, right) => JSON.stringify(left).localeCompare(JSON.stringify(right)))
}

export function normalizeChangeHistoryAccessDocument(raw, { allowUnresolvedActiveSubject = false } = {}) {
  const document = accessRecord(raw, 'access')
  exactAccessKeys(document, 'access', [
    'schema_version', 'active_subject_id', 'policy', 'users', 'systems', 'system_schema_scopes', 'system_assignments',
  ], ['schema_version', 'active_subject_id', 'users', 'systems', 'system_schema_scopes', 'system_assignments'])
  if (document.schema_version !== 1) {
    throw accessError(400, 'ACCESS_DOCUMENT_INVALID', 'access.schema_version must be 1.')
  }
  const users = normalizedAccessUsers(document.users)
  const systems = normalizedAccessSystems(document.systems)
  const activeSubjectId = accessString(document.active_subject_id, 'access.active_subject_id', 255)
  const activeUser = users.find((user) => user.subject_id === activeSubjectId)
  if (!allowUnresolvedActiveSubject && !activeUser?.active) {
    throw accessError(400, 'ACCESS_DOCUMENT_INVALID', 'The active subject must reference an active user.')
  }
  const policy = document.policy === undefined
    ? { version: 1, priority_order: 'ASCENDING', fallback: ['DATA_STEWARD', 'DEVELOPER', 'DATAHUB_OWNER', 'UNASSIGNED'] }
    : accessRecord(document.policy, 'access.policy')
  exactAccessKeys(policy, 'access.policy', ['version', 'priority_order', 'fallback'])
  if (policy.version !== 1 || policy.priority_order !== 'ASCENDING'
    || JSON.stringify(policy.fallback) !== JSON.stringify(['DATA_STEWARD', 'DEVELOPER', 'DATAHUB_OWNER', 'UNASSIGNED'])) {
    throw accessError(400, 'ACCESS_DOCUMENT_INVALID', 'access.policy must use the reviewed v1 assignment precedence.')
  }
  return {
    schema_version: 1,
    active_subject_id: activeSubjectId,
    policy,
    users,
    systems,
    system_schema_scopes: normalizedAccessScopes(document.system_schema_scopes, systems),
    system_assignments: normalizedAccessAssignments(document.system_assignments, users, systems),
  }
}

export function changeHistoryDocumentFromSnapshot(snapshot) {
  try {
    const access = accessRecord(snapshot.access.value, 'stored access')
    exactAccessKeys(access, 'stored access', [
      'schema_version', 'active_subject_id', 'policy', 'users', 'system_assignments',
    ], ['schema_version', 'active_subject_id', 'users', 'system_assignments'])
    const core = snapshot.core.value && typeof snapshot.core.value === 'object' && !Array.isArray(snapshot.core.value)
      ? snapshot.core.value
      : {}
    const groupedScopes = Array.isArray(core.adminSystemSchemaScopes) ? core.adminSystemSchemaScopes : []
    return normalizeChangeHistoryAccessDocument({
      ...access,
      systems: Array.isArray(core.adminSystems) ? core.adminSystems : [],
      system_schema_scopes: groupedScopes.flatMap((entry) => Array.isArray(entry?.[1]) ? entry[1] : []),
    }, { allowUnresolvedActiveSubject: true })
  } catch (error) {
    if (error?.code === 'ACCESS_DOCUMENT_INVALID') {
      throw accessError(503, 'ACCESS_STATE_INVALID', 'Stored change-history access state is invalid.')
    }
    throw error
  }
}

export function requireActiveAccessAdmin(document, subjectId) {
  const user = document.users.find((item) => item.subject_id === subjectId)
  if (!user?.active) throw accessError(403, 'SUBJECT_FORBIDDEN', 'The session subject is missing or inactive.')
  if (user.role !== 'admin') throw accessError(403, 'ACCESS_ADMIN_REQUIRED', 'An active admin is required.')
}

export function changeHistoryAccessCoreProjection(currentValue, document, membershipVersion) {
  const current = currentValue && typeof currentValue === 'object' && !Array.isArray(currentValue)
    ? structuredClone(currentValue)
    : {}
  const memberships = new Map((Array.isArray(current.adminMemberships) ? current.adminMemberships : [])
    .filter((item) => item && typeof item === 'object' && typeof item.subject_id === 'string')
    .map((item) => [item.subject_id, item]))
  const documentUsers = new Map(document.users.map((user) => [user.subject_id, user]))
  current.adminMemberships = document.users.map((user) => {
    const existing = memberships.get(user.subject_id) ?? {}
    const effectiveProfileRole = user.role === 'admin'
      ? 'ADMIN'
      : user.role === 'manager'
        ? 'MANAGER'
        : user.role === 'viewer' ? 'VIEWER' : 'ENGINEER_STEWARD'
    return {
      ...existing,
      subject_id: user.subject_id,
      display_name: user.display_name || existing.display_name || user.subject_id,
      email: user.email || existing.email || null,
      job_function: user.job_function ?? existing.job_function ?? user.role,
      department_id: user.department_id ?? existing.department_id ?? null,
      effective_profile_role: effectiveProfileRole,
      membership_version: membershipVersion ?? existing.membership_version ?? 1,
      subject_active: user.active,
      membership_active: user.active,
      change_history_role: user.role,
    }
  })
  current.adminSystems = document.systems
  current.adminSystemSchemaScopes = document.systems.map((system) => [
    system.system_id,
    document.system_schema_scopes.filter((scope) => scope.system_id === system.system_id),
  ])
  current.adminSystemAssignees = document.systems.map((system) => [
    system.system_id,
    document.system_assignments.filter((assignment) => assignment.system_id === system.system_id).map((assignment) => ({
      subject_id: assignment.subject_id,
      display_name: documentUsers.get(assignment.subject_id)?.display_name
        || memberships.get(assignment.subject_id)?.display_name
        || assignment.subject_id,
      responsibility: assignment.responsibility,
      priority: assignment.priority,
      active: assignment.active,
    })),
  ])
  return current
}

export function privateChangeHistoryAccess(document) {
  return {
    schema_version: document.schema_version,
    active_subject_id: document.active_subject_id,
    policy: document.policy,
    users: document.users,
    system_assignments: document.system_assignments,
  }
}
