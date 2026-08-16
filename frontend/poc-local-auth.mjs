/* global Buffer, URL */
import { createHash, randomBytes as nodeRandomBytes } from 'node:crypto'
import { isIP } from 'node:net'
import process from 'node:process'
import { argon2id, argon2Verify } from 'hash-wasm'

const SESSION_COOKIE_NAME = 'datariver_poc_session'
const SESSION_TOKEN_PATTERN = /^[A-Za-z0-9_-]{43}$/
const DEFAULT_WORKSPACE_ID = '00000000-0000-4000-8000-000000000061'
const DUMMY_PASSWORD_HASH = '$argon2id$v=19$m=19456,t=2,p=1$ZGF0YXJpdmVyLXBvYy12MSE$u72RDomCztEPw87z5in3hf+6nZv6Utc4EXWm22DdFzo'
const ARGON2_OPTIONS = Object.freeze({
  parallelism: 1,
  iterations: 2,
  memorySize: 19 * 1024,
  hashLength: 32,
  outputType: 'encoded',
})

function authError(statusCode, code, message) {
  return Object.assign(new Error(message), { statusCode, code })
}

function boundedInteger(value, name, fallback, minimum, maximum) {
  const raw = value === undefined || value === null || value === '' ? String(fallback) : String(value).trim()
  if (!/^\d+$/.test(raw)) throw new Error(`${name} must be an integer.`)
  const parsed = Number(raw)
  if (!Number.isSafeInteger(parsed) || parsed < minimum || parsed > maximum) {
    throw new Error(`${name} must be between ${minimum} and ${maximum}.`)
  }
  return parsed
}

function isLoopbackHostname(hostname) {
  const normalized = hostname.replace(/^\[|\]$/g, '').toLowerCase()
  if (normalized === 'localhost' || normalized.endsWith('.localhost')) return true
  if (isIP(normalized) === 4) return normalized.startsWith('127.')
  return normalized === '::1'
}

export function loadPocLocalAuthConfig(environment = process.env) {
  const rawOrigin = environment.POC_PUBLIC_ORIGIN?.trim()
  if (!rawOrigin) throw new Error('POC_PUBLIC_ORIGIN is required for local authentication.')
  const originUrl = new URL(rawOrigin)
  if (!['http:', 'https:'].includes(originUrl.protocol)
    || originUrl.username || originUrl.password
    || originUrl.pathname !== '/' || originUrl.search || originUrl.hash
    || originUrl.origin !== rawOrigin) {
    throw new Error('POC_PUBLIC_ORIGIN must be one exact credential-free HTTP(S) origin.')
  }
  if (originUrl.protocol === 'http:' && !isLoopbackHostname(originUrl.hostname)) {
    throw new Error('POC_PUBLIC_ORIGIN may use HTTP only for a loopback hostname or address.')
  }
  return Object.freeze({
    publicOrigin: originUrl.origin,
    secureCookie: originUrl.protocol === 'https:',
    sessionTtlSeconds: boundedInteger(
      environment.POC_AUTH_SESSION_TTL_SECONDS,
      'POC_AUTH_SESSION_TTL_SECONDS',
      8 * 60 * 60,
      5 * 60,
      24 * 60 * 60,
    ),
    failedAttemptLimit: boundedInteger(
      environment.POC_AUTH_FAILED_ATTEMPT_LIMIT,
      'POC_AUTH_FAILED_ATTEMPT_LIMIT',
      5,
      3,
      20,
    ),
    lockSeconds: boundedInteger(
      environment.POC_AUTH_LOCK_SECONDS,
      'POC_AUTH_LOCK_SECONDS',
      15 * 60,
      30,
      60 * 60,
    ),
  })
}

export function normalizePocUsername(value) {
  if (typeof value !== 'string') throw new Error('username must be a string.')
  const normalized = value.normalize('NFKC').trim().toLowerCase()
  if (!/^[a-z0-9][a-z0-9._@+-]{0,63}$/.test(normalized)) {
    throw new Error('username is outside its normalized contract.')
  }
  return normalized
}

function boundedPassword(password) {
  if (typeof password !== 'string') throw new Error('password must be a string.')
  const byteLength = Buffer.byteLength(password, 'utf8')
  if (byteLength < 12 || byteLength > 1024) throw new Error('password is outside its bounded contract.')
  return password
}

export async function hashPocPassword(password, { salt = nodeRandomBytes(16) } = {}) {
  boundedPassword(password)
  if (!(salt instanceof Uint8Array) || salt.byteLength !== 16) {
    throw new Error('Argon2id salt must contain exactly 16 random bytes.')
  }
  return argon2id({ password, salt, ...ARGON2_OPTIONS })
}

export async function verifyPocPassword(password, passwordHash) {
  if (typeof password !== 'string' || Buffer.byteLength(password, 'utf8') > 1024) return false
  if (typeof passwordHash !== 'string' || !passwordHash.startsWith('$argon2id$v=19$')) return false
  try {
    return await argon2Verify({ password, hash: passwordHash })
  } catch {
    return false
  }
}

export function hashPocSessionToken(token) {
  if (typeof token !== 'string' || !SESSION_TOKEN_PATTERN.test(token)) {
    throw new Error('session token is malformed.')
  }
  return createHash('sha256').update(token, 'utf8').digest('hex')
}

function sessionCookie(request) {
  const header = request.headers.cookie
  if (header === undefined) return undefined
  if (typeof header !== 'string' || header.length > 4096) return null
  const values = []
  for (const part of header.split(';')) {
    const separator = part.indexOf('=')
    if (separator < 1) return null
    const name = part.slice(0, separator).trim()
    const value = part.slice(separator + 1).trim()
    if (name === SESSION_COOKIE_NAME) values.push(value)
  }
  if (values.length === 0) return undefined
  if (values.length !== 1 || !SESSION_TOKEN_PATTERN.test(values[0])) return null
  return values[0]
}

function timestamp(now) {
  const value = now()
  const parsed = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(parsed.getTime())) throw new Error('Authentication clock returned an invalid timestamp.')
  return parsed
}

export function createPocLocalAuthenticator({
  stateStore,
  config = loadPocLocalAuthConfig(),
  now = () => new Date(),
  randomBytes = nodeRandomBytes,
  allowInMemoryStoreForTests = false,
} = {}) {
  const requiredMethods = [
    'readLocalCredential', 'recordLocalLoginFailure', 'recordLocalLoginSuccess',
    'createLocalSession', 'readLocalSession', 'revokeLocalSession',
  ]
  if (!stateStore || requiredMethods.some((method) => typeof stateStore[method] !== 'function')) {
    throw new Error('Local authentication storage is unavailable.')
  }
  if (!stateStore.configured?.postgres && !allowInMemoryStoreForTests) {
    throw new Error('Local authentication requires configured PostgreSQL storage.')
  }

  function assertOrigin(request) {
    const supplied = request.headers.origin
    if (typeof supplied !== 'string' || supplied !== config.publicOrigin) {
      throw authError(403, 'ORIGIN_FORBIDDEN', 'The request Origin is not allowed.')
    }
  }

  async function recordFailedAttempt(initialCredential, usernameNormalized, currentTime) {
    let current = initialCredential
    for (let retry = 0; retry < 8; retry += 1) {
      if (!current?.loginEnabled
        || (current.lockedUntil && Date.parse(current.lockedUntil) > currentTime.getTime())) return
      const failedAttempts = current.failedAttempts + 1
      const lockedUntil = failedAttempts >= config.failedAttemptLimit
        ? new Date(currentTime.getTime() + config.lockSeconds * 1000).toISOString()
        : null
      if (await stateStore.recordLocalLoginFailure({
        subjectId: current.subjectId,
        expectedVersion: current.version,
        failedAttempts,
        lockedUntil,
      })) return
      current = await stateStore.readLocalCredential(usernameNormalized)
    }
    throw authError(503, 'AUTHENTICATION_STATE_BUSY', 'Local authentication state is temporarily unavailable.')
  }

  async function login(username, password) {
    let normalizedUsername
    try {
      normalizedUsername = normalizePocUsername(username)
    } catch {
      normalizedUsername = undefined
    }
    const credential = normalizedUsername
      ? await stateStore.readLocalCredential(normalizedUsername)
      : null
    const currentTime = timestamp(now)
    const locked = credential?.lockedUntil && Date.parse(credential.lockedUntil) > currentTime.getTime()
    const hash = credential?.passwordHash ?? DUMMY_PASSWORD_HASH
    const verified = await verifyPocPassword(password, hash)
    if (!credential || !credential.loginEnabled || locked || !verified) {
      if (credential?.loginEnabled && !locked) {
        await recordFailedAttempt(credential, normalizedUsername, currentTime)
      }
      throw authError(401, 'AUTHENTICATION_FAILED', 'The username or password is invalid.')
    }
    const reset = await stateStore.recordLocalLoginSuccess({
      subjectId: credential.subjectId,
      expectedVersion: credential.version,
    })
    if (!reset) throw authError(401, 'AUTHENTICATION_FAILED', 'The username or password is invalid.')
    const tokenBytes = randomBytes(32)
    if (!(tokenBytes instanceof Uint8Array) || tokenBytes.byteLength !== 32) {
      throw new Error('Session entropy source returned an invalid token.')
    }
    const token = Buffer.from(tokenBytes).toString('base64url')
    const tokenHash = hashPocSessionToken(token)
    const expiresAt = new Date(currentTime.getTime() + config.sessionTtlSeconds * 1000).toISOString()
    await stateStore.createLocalSession({
      tokenHash,
      subjectId: credential.subjectId,
      createdAt: currentTime.toISOString(),
      expiresAt,
    })
    return {
      subjectId: credential.subjectId,
      mustChangePassword: credential.mustChangePassword,
      token,
      tokenHash,
      expiresAt,
    }
  }

  async function authenticate(request) {
    const token = sessionCookie(request)
    if (!token) throw authError(401, 'SESSION_REQUIRED', 'A valid local session is required.')
    const tokenHash = hashPocSessionToken(token)
    const session = await stateStore.readLocalSession(tokenHash)
    const currentTime = timestamp(now)
    if (!session || session.revokedAt || Date.parse(session.expiresAt) <= currentTime.getTime()) {
      throw authError(401, 'SESSION_REQUIRED', 'A valid local session is required.')
    }
    return {
      subjectId: session.subjectId,
      tokenHash,
      mustChangePassword: session.mustChangePassword === true,
    }
  }

  async function logout(authentication) {
    await stateStore.revokeLocalSession({
      tokenHash: authentication.tokenHash,
      revokedAt: timestamp(now).toISOString(),
    })
  }

  function setCookie(token) {
    return [
      `${SESSION_COOKIE_NAME}=${token}`,
      'HttpOnly',
      'SameSite=Strict',
      'Path=/',
      `Max-Age=${config.sessionTtlSeconds}`,
      ...(config.secureCookie ? ['Secure'] : []),
    ].join('; ')
  }

  function clearCookie() {
    return [
      `${SESSION_COOKIE_NAME}=`,
      'HttpOnly',
      'SameSite=Strict',
      'Path=/',
      'Max-Age=0',
      ...(config.secureCookie ? ['Secure'] : []),
    ].join('; ')
  }

  return {
    authenticate,
    assertOrigin,
    clearCookie,
    config,
    login,
    logout,
    setCookie,
  }
}

export function authenticatedPocProfile(user, { mustChangePassword } = {}) {
  const profile = {
    subject: user.subject_id,
    display_name: user.display_name || user.subject_id,
    roles: [user.role],
    authentication_assurance: 'PASSWORD',
    default_workspace_id: DEFAULT_WORKSPACE_ID,
    workspace_selection_enabled: false,
    hardware_webauthn_enabled: false,
    password_change_supported: false,
  }
  if (mustChangePassword !== undefined) profile.must_change_password = Boolean(mustChangePassword)
  return profile
}
