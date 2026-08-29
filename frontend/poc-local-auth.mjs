/* global Buffer, URL */
import { createHash, randomBytes as nodeRandomBytes } from 'node:crypto'
import { BlockList, isIP } from 'node:net'
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

function authConfigError(code, message) {
  return Object.assign(new Error(message), { code })
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

function normalizedIpLiteral(hostname) {
  const normalized = hostname.replace(/^\[|\]$/g, '').toLowerCase()
  return { address: normalized, family: isIP(normalized) }
}

function isLoopbackAddress(address, family) {
  if (family === 4) return address.startsWith('127.')
  return family === 6 && address === '::1'
}

function isPrivateIntranetAddress(address, family) {
  if (family === 4) {
    const [first, second] = address.split('.').map(Number)
    return first === 10
      || (first === 172 && second >= 16 && second <= 31)
      || (first === 192 && second === 168)
  }
  if (family === 6) {
    const firstHextet = Number.parseInt(address.split(':', 1)[0] || '0', 16)
    return (firstHextet & 0xfe00) === 0xfc00
  }
  return false
}

function isUnspecifiedOrMulticast(address, family) {
  if (family === 4) {
    const first = Number(address.split('.', 1)[0])
    return address === '0.0.0.0' || (first >= 224 && first <= 239)
  }
  return family === 6 && (address === '::' || address.startsWith('ff'))
}

function approvedIntranetCidrs(rawValue) {
  const raw = rawValue?.trim() || ''
  if (!raw) return []
  if (raw.length > 4096) {
    throw authConfigError(
      'POC_INTRANET_HTTP_ALLOWED_CIDRS_INVALID',
      'POC_INTRANET_HTTP_ALLOWED_CIDRS exceeds its bounded contract.',
    )
  }
  const values = raw.split(',')
  if (values.length > 64 || values.some((value) => !value.trim())) {
    throw authConfigError(
      'POC_INTRANET_HTTP_ALLOWED_CIDRS_INVALID',
      'POC_INTRANET_HTTP_ALLOWED_CIDRS must contain one to 64 comma-separated CIDRs.',
    )
  }
  return values.map((value) => {
    const candidate = value.trim()
    const separator = candidate.lastIndexOf('/')
    if (separator <= 0 || separator === candidate.length - 1 || candidate.includes('*')) {
      throw authConfigError(
        'POC_INTRANET_HTTP_ALLOWED_CIDRS_INVALID',
        'POC_INTRANET_HTTP_ALLOWED_CIDRS contains an invalid CIDR.',
      )
    }
    const address = candidate.slice(0, separator)
    const prefixValue = candidate.slice(separator + 1)
    const family = isIP(address)
    const maximum = family === 4 ? 32 : family === 6 ? 128 : -1
    const minimum = family === 4 ? 8 : family === 6 ? 16 : Number.POSITIVE_INFINITY
    if (!/^\d{1,3}$/.test(prefixValue)) {
      throw authConfigError(
        'POC_INTRANET_HTTP_ALLOWED_CIDRS_INVALID',
        'POC_INTRANET_HTTP_ALLOWED_CIDRS contains an invalid prefix.',
      )
    }
    const prefix = Number(prefixValue)
    if (maximum < 0 || prefix < minimum || prefix > maximum
      || isUnspecifiedOrMulticast(address, family)) {
      throw authConfigError(
        'POC_INTRANET_HTTP_ALLOWED_CIDRS_INVALID',
        'POC_INTRANET_HTTP_ALLOWED_CIDRS contains an unsafe or invalid CIDR.',
      )
    }
    const blockList = new BlockList()
    try {
      blockList.addSubnet(address, prefix, family === 4 ? 'ipv4' : 'ipv6')
    } catch {
      throw authConfigError(
        'POC_INTRANET_HTTP_ALLOWED_CIDRS_INVALID',
        'POC_INTRANET_HTTP_ALLOWED_CIDRS contains an invalid CIDR.',
      )
    }
    return { blockList, family }
  })
}

function isApprovedHttpOriginAddress(address, family, approvedCidrs) {
  if (isLoopbackAddress(address, family) || isPrivateIntranetAddress(address, family)) return true
  const type = family === 4 ? 'ipv4' : 'ipv6'
  return approvedCidrs.some((item) => item.family === family && item.blockList.check(address, type))
}

export function loadPocLocalAuthConfig(environment = process.env) {
  const rawOrigin = environment.POC_PUBLIC_ORIGIN?.trim()
  if (!rawOrigin) throw new Error('POC_PUBLIC_ORIGIN is required for local authentication.')
  const approvedCidrs = approvedIntranetCidrs(environment.POC_INTRANET_HTTP_ALLOWED_CIDRS)
  let originUrl
  try {
    originUrl = new URL(rawOrigin)
  } catch {
    throw authConfigError(
      'POC_PUBLIC_ORIGIN_MALFORMED',
      'POC_PUBLIC_ORIGIN must be one exact credential-free HTTP(S) origin.',
    )
  }
  if (!['http:', 'https:'].includes(originUrl.protocol)
    || originUrl.username || originUrl.password
    || originUrl.pathname !== '/' || originUrl.search || originUrl.hash
    || originUrl.origin !== rawOrigin) {
    throw authConfigError(
      'POC_PUBLIC_ORIGIN_MALFORMED',
      'POC_PUBLIC_ORIGIN must be one exact credential-free HTTP(S) origin.',
    )
  }
  if (originUrl.protocol === 'http:') {
    const { address, family } = normalizedIpLiteral(originUrl.hostname)
    if (!family || isUnspecifiedOrMulticast(address, family)) {
      throw authConfigError(
        'POC_PUBLIC_ORIGIN_MALFORMED',
        'POC_PUBLIC_ORIGIN HTTP mode requires one safe literal IP address.',
      )
    }
    if (!isApprovedHttpOriginAddress(address, family, approvedCidrs)) {
      throw authConfigError(
        'POC_PUBLIC_ORIGIN_NOT_APPROVED',
        'POC_PUBLIC_ORIGIN HTTP address is outside the approved intranet ranges.',
      )
    }
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
    'readLocalCredential', 'readLocalCredentialForSubject', 'recordLocalLoginFailure', 'recordLocalLoginSuccess',
    'createLocalSession', 'readLocalSession', 'revokeLocalSession',
    'changeOwnLocalPassword',
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

  async function changePassword(authentication, {
    currentPassword,
    newPassword,
    confirmation,
  } = {}) {
    const invalidInput = () => authError(
      400,
      'PASSWORD_CHANGE_INPUT_INVALID',
      'Password change input is invalid.',
    )
    if (!authentication || typeof authentication.subjectId !== 'string'
      || typeof currentPassword !== 'string'
      || typeof newPassword !== 'string'
      || typeof confirmation !== 'string'
      || newPassword !== confirmation) {
      throw invalidInput()
    }
    let currentPasswordInPolicy = true
    try {
      boundedPassword(currentPassword)
    } catch {
      currentPasswordInPolicy = false
    }
    try {
      boundedPassword(newPassword)
    } catch {
      throw invalidInput()
    }
    const credential = await stateStore.readLocalCredentialForSubject(authentication?.subjectId)
    const verified = currentPasswordInPolicy
      && credential?.loginEnabled === true
      && await verifyPocPassword(currentPassword, credential.passwordHash)
    if (!credential || !verified) {
      throw authError(401, 'PASSWORD_CHANGE_FAILED', 'Password change could not be completed.')
    }
    const passwordHash = await hashPocPassword(newPassword, { salt: randomBytes(16) })
    let result
    try {
      result = await stateStore.changeOwnLocalPassword({
        subjectId: credential.subjectId,
        expectedVersion: credential.version,
        passwordHash,
      })
    } catch (error) {
      if (error?.code === 'CREDENTIAL_VERSION_STALE') {
        throw authError(
          409,
          'PASSWORD_CHANGE_CONFLICT',
          'Password change could not be completed. Sign in and try again.',
        )
      }
      throw error
    }
    return { revokedSessionCount: result.revokedSessionCount }
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
    changePassword,
    clearCookie,
    config,
    login,
    logout,
    setCookie,
  }
}

export function authenticatedPocProfile(user, {
  mustChangePassword,
  passwordChangeSupported = false,
} = {}) {
  const profile = {
    subject: user.subject_id,
    display_name: user.display_name || user.subject_id,
    roles: [user.role],
    max_security_grade: user.max_security_grade ?? 'normal',
    authentication_assurance: 'PASSWORD',
    default_workspace_id: DEFAULT_WORKSPACE_ID,
    workspace_selection_enabled: false,
    hardware_webauthn_enabled: false,
    password_change_supported: passwordChangeSupported === true,
  }
  if (mustChangePassword !== undefined) profile.must_change_password = Boolean(mustChangePassword)
  return profile
}
