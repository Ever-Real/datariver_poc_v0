/* global Buffer */
// Dependencies are supplied by bootstrap; this module never constructs a shared client.
export function createModulesAuthHttp(deps) {
async function authenticatedRequestContext(baseContext, authentication) {
  const snapshot = await baseContext.stateStore.readChangeHistoryAccess()
  if (snapshot.access.value === null) {
    throw deps.accessError(503, 'ACCESS_NOT_CONFIGURED', 'Change-history access is not provisioned.')
  }
  const document = deps.changeHistoryDocumentFromSnapshot(snapshot)
  const user = deps.changeHistoryActiveUser(document, authentication.subjectId)

  const userTableGrants = typeof baseContext.stateStore.listUserTableGrants === 'function'
    ? await baseContext.stateStore.listUserTableGrants(authentication.subjectId)
    : []
  const policySnapshot = typeof baseContext.stateStore.readFeatureSecurityPolicy === 'function'
    ? await baseContext.stateStore.readFeatureSecurityPolicy()
    : { value: null, version: 0 }
  const featureSecurityPolicy = policySnapshot?.value ? deps.normalizePersistedFeatureSecurityPolicy(policySnapshot.value) : deps.approvedDefaultFeatureSecurityPolicy()

  const context = {
    ...baseContext,
    authentication,
    subject: { subjectId: authentication.subjectId },
    accessDocument: document,
    accessUser: user,
    userTableGrants,
    featureSecurityPolicy,
  }
  return { ...context, principal: deps.buildPocPrincipal(context) }
}

function authenticatedProfile(context, mustChangePassword) {
  return {
    ...deps.authenticatedPocProfile(context.accessUser, {
      mustChangePassword,
      passwordChangeSupported: true,
    }),
    authorization: deps.authorizationProjection(context.principal),
  }
}

function exactServiceToken(request, configuredToken, errorCode = 'AIRFLOW_SERVICE_AUTH_NOT_CONFIGURED', errorMessage = 'Airflow service authentication is not configured.') {
  if (typeof configuredToken !== 'string'
    || configuredToken.length < 32
    || configuredToken.length > 512
    || [...configuredToken].some((character) => {
      const codePoint = character.codePointAt(0)
      return codePoint === undefined || codePoint < 0x21 || codePoint > 0x7e
    })) {
    throw deps.accessError(503, errorCode, errorMessage)
  }
  const supplied = request.headers.authorization
  const expected = `Bearer ${configuredToken}`
  if (typeof supplied !== 'string') {
    throw deps.accessError(401, 'SERVICE_AUTHENTICATION_FAILED', 'Valid service authentication is required.')
  }
  const suppliedBytes = Buffer.from(supplied, 'utf8')
  const expectedBytes = Buffer.from(expected, 'utf8')
  if (suppliedBytes.length !== expectedBytes.length || !deps.timingSafeEqual(suppliedBytes, expectedBytes)) {
    throw deps.accessError(401, 'SERVICE_AUTHENTICATION_FAILED', 'Valid service authentication is required.')
  }
}

function exactBodyKeys(body, allowed, required = allowed) {
  const keys = Object.keys(body)
  const unknown = keys.find((key) => !allowed.includes(key))
  const missing = required.find((key) => !Object.hasOwn(body, key))
  if (unknown || missing) {
    throw deps.accessError(400, 'ADMIN_INPUT_INVALID', unknown
      ? `${unknown} is not supported.`
      : `${missing} is required.`)
  }
}

function normalizedSecurityGrade(value) {
  return deps.normalizeSecurityGrade(
    value,
    'USER_SECURITY_GRADE_INVALID',
    'max_security_grade must be normal, credential, or restricted.',
  )
}

function assignmentResponsibility(role) {
  if (role === 'developer') return 'DEVELOPER'
  if (role === 'data_steward') return 'DATA_STEWARD'
  if (role === 'manager') return 'MANAGER'
  return null
}

function normalizedResponsibleSystems(value, role, document) {
  if (!Array.isArray(value) || value.length > 500) {
    throw deps.accessError(400, 'RESPONSIBLE_SYSTEM_INVALID', 'responsible_systems must be a bounded array.')
  }
  const responsibility = assignmentResponsibility(role)
  if (!responsibility && value.length) {
    throw deps.accessError(400, 'RESPONSIBLE_SYSTEM_INVALID', 'Only developer, data_steward, and manager users may have Responsible Systems.')
  }
  const activeSystems = new Set(document.systems.filter((system) => system.active).map((system) => system.system_id))
  const observed = new Set()
  return value.map((raw, index) => {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
      throw deps.accessError(400, 'RESPONSIBLE_SYSTEM_INVALID', `responsible_systems[${index}] must be an object.`)
    }
    exactBodyKeys(raw, ['system_id', 'priority'])
    const systemId = deps.boundedString(raw.system_id, 255).trim()
    const priority = Number(raw.priority)
    if (!activeSystems.has(systemId) || observed.has(systemId)
      || !Number.isSafeInteger(priority) || priority < 1 || priority > 10_000) {
      throw deps.accessError(400, 'RESPONSIBLE_SYSTEM_INVALID', 'Responsible Systems must be unique active Systems with a positive priority.')
    }
    observed.add(systemId)
    return { system_id: systemId, responsibility, priority, active: true }
  })
}

async function confirmedCurrentTables(context, requestedTables, unavailableCode, invalidCode) {
  let current
  try {
    current = await context.currentDatahubTables(requestedTables)
    if (!Array.isArray(current)) throw new Error('DataHub returned invalid current entities.')
  } catch {
    throw deps.accessError(503, unavailableCode, 'Current DataHub Table identities could not be confirmed; no change was made.')
  }
  const currentTables = new Set(current
    .filter((asset) => asset?.dataset_kind === 'TABLE')
    .map((asset) => asset.id))
  if (requestedTables.some((tableId) => !currentTables.has(tableId))) {
    throw deps.accessError(400, invalidCode, 'Every selected identity must be a current DataHub TABLE.')
  }
  return current.filter((asset) => currentTables.has(asset.id))
}

async function authRoute(request, response, url, baseContext, authenticator) {
  if (url.pathname === '/auth/login') {
    if (request.method !== 'POST') return deps.problem(response, 405, 'METHOD_NOT_ALLOWED', 'Local login supports only POST.')
    authenticator.assertOrigin(request)
    const body = await deps.bodyJson(request)
    if (Object.keys(body).some((key) => !['username', 'password'].includes(key))
      || !Object.hasOwn(body, 'username') || !Object.hasOwn(body, 'password')) {
      throw deps.accessError(401, 'AUTHENTICATION_FAILED', 'The username or password is invalid.')
    }
    const login = await authenticator.login(body.username, body.password)
    let context
    try {
      context = await authenticatedRequestContext(baseContext, login)
    } catch (error) {
      await authenticator.logout(login)
      throw error
    }
    deps.assertPocRouteAuthorization(deps.resolvePocRoute(request.method, url.pathname), context.principal)
    return deps.json(response, 200, authenticatedProfile(context, login.mustChangePassword), {
      'Set-Cookie': authenticator.setCookie(login.token),
    })
  }
  if (url.pathname === '/auth/me') {
    if (request.method !== 'GET') return deps.problem(response, 405, 'METHOD_NOT_ALLOWED', 'Session profile supports only GET.')
    const authentication = await authenticator.authenticate(request)
    const context = await authenticatedRequestContext(baseContext, authentication)
    deps.assertPocRouteAuthorization(deps.resolvePocRoute(request.method, url.pathname), context.principal)
    return deps.json(response, 200, authenticatedProfile(context, authentication.mustChangePassword))
  }
  if (url.pathname === '/auth/password') {
    if (request.method !== 'POST') return deps.problem(response, 405, 'METHOD_NOT_ALLOWED', 'Local password change supports only POST.')
    authenticator.assertOrigin(request)
    const authentication = await authenticator.authenticate(request)
    const context = await authenticatedRequestContext(baseContext, authentication)
    deps.assertPocRouteAuthorization(deps.resolvePocRoute(request.method, url.pathname), context.principal)
    let body
    try {
      body = await deps.bodyJson(request, 4096)
    } catch (error) {
      if (error instanceof SyntaxError || error?.statusCode === 413) {
        throw deps.accessError(400, 'PASSWORD_CHANGE_INPUT_INVALID', 'Password change input is invalid.')
      }
      throw error
    }
    const allowed = ['current_password', 'new_password', 'new_password_confirmation']
    if (Object.keys(body).length !== allowed.length
      || Object.keys(body).some((key) => !allowed.includes(key))
      || allowed.some((key) => !Object.hasOwn(body, key))) {
      throw deps.accessError(400, 'PASSWORD_CHANGE_INPUT_INVALID', 'Password change input is invalid.')
    }
    await authenticator.changePassword(authentication, {
      currentPassword: body.current_password,
      newPassword: body.new_password,
      confirmation: body.new_password_confirmation,
    })
    return deps.json(response, 200, { ok: true, reauthentication_required: true }, {
      'Set-Cookie': authenticator.clearCookie(),
    })
  }
  if (url.pathname === '/auth/logout') {
    if (request.method !== 'POST') return deps.problem(response, 405, 'METHOD_NOT_ALLOWED', 'Local logout supports only POST.')
    authenticator.assertOrigin(request)
    const authentication = await authenticator.authenticate(request)
    const context = await authenticatedRequestContext(baseContext, authentication)
    deps.assertPocRouteAuthorization(deps.resolvePocRoute(request.method, url.pathname), context.principal)
    await authenticator.logout(authentication)
    return deps.json(response, 200, { ok: true }, { 'Set-Cookie': authenticator.clearCookie() })
  }
  return deps.problem(response, 404, 'NOT_FOUND', 'The authentication route does not exist.')
}

return { authenticatedRequestContext, authenticatedProfile, exactServiceToken, exactBodyKeys, normalizedSecurityGrade, assignmentResponsibility, normalizedResponsibleSystems, confirmedCurrentTables, authRoute }
}
