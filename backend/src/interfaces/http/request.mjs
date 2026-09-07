/* global Buffer */
// Dependencies are supplied by bootstrap; this module never constructs a shared client.
export function createInterfacesHttpRequest(deps) {
function json(response, status, value, extraHeaders = {}) {
  const body = JSON.stringify(value)
  response.writeHead(status, {
    'Cache-Control': 'no-store',
    'Content-Length': Buffer.byteLength(body),
    'Content-Type': 'application/json; charset=utf-8',
    ...securityHeaders(),
    ...extraHeaders,
  })
  response.end(body)
}

function problem(response, status, code, detail, diagnostic) {
  json(response, status, {
    code,
    detail,
    status,
    title: 'POC integration request failed',
    ...(diagnostic ? { diagnostic } : {}),
  })
}

function writeEventStream(response, event, value) {
  response.write(`event: ${event}\ndata: ${JSON.stringify(value)}\n\n`)
}

function securityHeaders() {
  const frameOrigins = [...new Set(deps.configuredMonitoringDashboards
    .flatMap((item) => item.embed_state === 'AVAILABLE' ? [new deps.URL(item.embed_url).origin] : []))]
  const frameSource = frameOrigins.length ? frameOrigins.join(' ') : "'none'"
  return {
    'Content-Security-Policy': `default-src 'self'; base-uri 'self'; connect-src 'self'; font-src 'self'; form-action 'self'; frame-ancestors 'none'; frame-src ${frameSource}; img-src 'self' data:; object-src 'none'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self'`,
    'Permissions-Policy': 'camera=(), geolocation=(), microphone=(), payment=(), usb=()',
    'Referrer-Policy': 'no-referrer',
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
  }
}

function redirectBrowserToCanonicalOrigin(request, response, url, authenticator) {
  const publicOrigin = authenticator?.config?.publicOrigin
  if (typeof publicOrigin !== 'string' || !publicOrigin) return false
  const canonical = new deps.URL(publicOrigin)
  if (request.headers.host === canonical.host) return false
  const location = new deps.URL(`${url.pathname}${url.search}`, canonical).toString()
  response.writeHead(307, {
    'Cache-Control': 'no-store',
    Location: location,
    ...securityHeaders(),
  })
  response.end()
  return true
}

function unconfiguredPocAuthenticator() {
  const unavailable = () => {
    throw accessError(503, 'AUTHENTICATION_NOT_CONFIGURED', 'Local authentication is not configured.')
  }
  return {
    authenticate: unavailable,
    assertOrigin: unavailable,
    changePassword: unavailable,
    clearCookie: () => 'datariver_poc_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0',
    login: unavailable,
    logout: unavailable,
    setCookie: unavailable,
  }
}

async function bodyBuffer(request, limit = deps.maximumJsonBytes) {
  const chunks = []
  let size = 0
  for await (const chunk of request) {
    size += chunk.length
    if (size > limit) throw Object.assign(new Error('Request body is too large.'), { statusCode: 413 })
    chunks.push(chunk)
  }
  return Buffer.concat(chunks)
}

async function bodyJson(request, limit = deps.maximumJsonBytes) {
  const body = await bodyBuffer(request, limit)
  if (body.length === 0) return {}
  const value = JSON.parse(body.toString('utf8'))
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw Object.assign(new Error('A JSON object is required.'), { statusCode: 400 })
  }
  return value
}

function boundedString(value, maximum, fallback = '') {
  return typeof value === 'string' && value.length <= maximum ? value : fallback
}

function accessError(statusCode, code, message) {
  return Object.assign(new Error(message), { statusCode, code })
}

function hasAccessControlCharacter(value) {
  return [...value].some((character) => {
    const codePoint = character.codePointAt(0)
    return codePoint <= 0x1f || codePoint === 0x7f
  })
}

function rejectProtectedAccessClaims(request, url, { allowSystemFilter = false } = {}) {
  const header = Object.keys(request.headers).find((key) => deps.protectedAccessHeaders.has(key.toLowerCase()))
  const query = [...url.searchParams.keys()].find((key) => deps.protectedAccessQueryKeys.has(key.toLowerCase())
    && !(allowSystemFilter && key.toLowerCase() === 'system_id'))
  if (header || query) {
    throw accessError(400, 'PROTECTED_CLAIM', 'Browser-supplied identity and authorization claims are forbidden.')
  }
}

function rejectProtectedAccessBodyClaims(body, { allowPriority = false } = {}) {
  const alwaysProtected = new Set(['actor', 'actor_ref', 'policy_hash', 'basis_hash', 'occurred_at'])
  const topLevelProtected = new Set(['subject_id', 'role', 'system_id', 'responsibility', 'priority'])
  if (allowPriority) topLevelProtected.delete('priority')
  if (Object.keys(body).some((key) => topLevelProtected.has(key.toLowerCase()))) {
    throw accessError(400, 'PROTECTED_CLAIM', 'Browser-supplied identity and authorization claims are forbidden.')
  }
  const visit = (value) => {
    if (Array.isArray(value)) return value.forEach(visit)
    if (!value || typeof value !== 'object') return
    for (const [key, nested] of Object.entries(value)) {
      if (alwaysProtected.has(key.toLowerCase())) {
        throw accessError(400, 'PROTECTED_CLAIM', 'Browser-supplied authority evidence is forbidden.')
      }
      visit(nested)
    }
  }
  visit(body)
}

function accessIfMatch(request) {
  const value = request.headers['if-match']
  if (typeof value !== 'string') throw accessError(428, 'IF_MATCH_REQUIRED', 'If-Match is required.')
  const match = value.match(/^"(0|[1-9]\d*)"$/)
  const version = match ? Number(match[1]) : Number.NaN
  if (!Number.isSafeInteger(version)) throw accessError(400, 'IF_MATCH_INVALID', 'If-Match must be a quoted access version.')
  return version
}

function airflowIdempotencyKey(request) {
  const value = request.headers['idempotency-key']
  if (typeof value !== 'string') {
    throw accessError(428, 'AIRFLOW_IDEMPOTENCY_KEY_REQUIRED', 'Idempotency-Key is required.')
  }
  if (value.length < 16 || value.length > 200 || [...value].some((character) => {
    const code = character.codePointAt(0)
    return code < 0x21 || code > 0x7e
  })) {
    throw accessError(400, 'AIRFLOW_IDEMPOTENCY_KEY_INVALID', 'Idempotency-Key must contain 16-200 visible ASCII characters.')
  }
  return value
}

function stateIfMatch(request) {
  const value = request.headers['if-match']
  if (typeof value !== 'string') throw accessError(428, 'IF_MATCH_REQUIRED', 'If-Match is required for core state replacement.')
  const match = value.match(/^"(0|[1-9]\d*)"$/)
  const version = match ? Number(match[1]) : Number.NaN
  if (!Number.isSafeInteger(version)) throw accessError(400, 'IF_MATCH_INVALID', 'If-Match must be a quoted core state version.')
  return version
}

function tableSystemIfMatch(request) {
  const value = request.headers['if-match']
  if (typeof value !== 'string') throw accessError(428, 'IF_MATCH_REQUIRED', 'If-Match is required for Table-System mapping changes.')
  const match = value.match(/^"(0|[1-9]\d*)"$/)
  const version = match ? Number(match[1]) : Number.NaN
  if (!Number.isSafeInteger(version)) throw accessError(400, 'IF_MATCH_INVALID', 'If-Match must be a quoted Table-System mapping version.')
  return version
}

function featureSecurityPolicyIfMatch(request) {
  const value = request.headers['if-match']
  if (typeof value !== 'string') throw accessError(428, 'IF_MATCH_REQUIRED', 'If-Match is required for feature security policy changes.')
  const match = value.match(/^"(0|[1-9]\d*)"$/)
  const version = match ? Number(match[1]) : Number.NaN
  if (!Number.isSafeInteger(version)) throw accessError(400, 'IF_MATCH_INVALID', 'If-Match must be a quoted feature security policy version.')
  return version
}

function siteBrandingIfMatch(request) {
  const value = request.headers['if-match']
  if (typeof value !== 'string') throw accessError(428, 'IF_MATCH_REQUIRED', 'If-Match is required for site branding changes.')
  const match = value.match(/^"(0|[1-9]\d*)"$/)
  const version = match ? Number(match[1]) : Number.NaN
  if (!Number.isSafeInteger(version)) throw accessError(400, 'IF_MATCH_INVALID', 'If-Match must be a quoted site branding version.')
  return version
}

return { json, problem, writeEventStream, securityHeaders, redirectBrowserToCanonicalOrigin, unconfiguredPocAuthenticator, bodyBuffer, bodyJson, boundedString, accessError, hasAccessControlCharacter, rejectProtectedAccessClaims, rejectProtectedAccessBodyClaims, accessIfMatch, airflowIdempotencyKey, stateIfMatch, tableSystemIfMatch, featureSecurityPolicyIfMatch, siteBrandingIfMatch }
}
