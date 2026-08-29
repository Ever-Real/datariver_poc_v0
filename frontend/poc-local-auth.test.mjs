/* global Buffer */
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createPocLocalAuthenticator,
  hashPocPassword,
  hashPocSessionToken,
  loadPocLocalAuthConfig,
  normalizePocUsername,
  verifyPocPassword,
} from './poc-local-auth.mjs'
import { createPocStateStore } from './poc-state-store.mjs'

const config = Object.freeze({
  publicOrigin: 'http://127.0.0.1:39080',
  secureCookie: false,
  sessionTtlSeconds: 300,
  failedAttemptLimit: 3,
  lockSeconds: 30,
})

async function authFixture(authConfig = config) {
  const stateStore = createPocStateStore()
  const passwordHash = await hashPocPassword('correct horse battery staple', {
    salt: Buffer.from('0123456789abcdef'),
  })
  await stateStore.insertLocalCredential({
    expectedAccessVersion: 0,
    expectedCoreVersion: 0,
    subjectId: 'subject-one',
    usernameNormalized: 'person@example.com',
    passwordHash,
    loginEnabled: true,
    mustChangePassword: false,
  })
  let currentTime = Date.parse('2026-08-16T03:00:00.000Z')
  let entropy = 1
  const authenticator = createPocLocalAuthenticator({
    stateStore,
    config: authConfig,
    now: () => new Date(currentTime),
    randomBytes: (size) => Buffer.alloc(size, entropy++),
    allowInMemoryStoreForTests: true,
  })
  return {
    authenticator,
    stateStore,
    advance(milliseconds) { currentTime += milliseconds },
  }
}

test('changes only the authenticated subject password without creating a session', async () => {
  const { authenticator, stateStore } = await authFixture()
  const first = await authenticator.login('person@example.com', 'correct horse battery staple')
  const second = await authenticator.login('person@example.com', 'correct horse battery staple')
  const authentication = await authenticator.authenticate({
    headers: { cookie: `datariver_poc_session=${first.token}` },
  })
  let sessionCreates = 0
  let selfPasswordChanges = 0
  const createLocalSession = stateStore.createLocalSession
  stateStore.createLocalSession = async (input) => {
    sessionCreates += 1
    return createLocalSession(input)
  }
  const changeOwnLocalPassword = stateStore.changeOwnLocalPassword
  stateStore.changeOwnLocalPassword = async (input) => {
    selfPasswordChanges += 1
    return changeOwnLocalPassword(input)
  }
  stateStore.administerLocalCredential = async () => {
    assert.fail('self password change must not use the admin credential method')
  }

  const result = await authenticator.changePassword(authentication, {
    currentPassword: 'correct horse battery staple',
    newPassword: 'replacement battery staple',
    confirmation: 'replacement battery staple',
  })

  assert.deepEqual(result, { revokedSessionCount: 2 })
  assert.equal(sessionCreates, 0)
  assert.equal(selfPasswordChanges, 1)
  assert.equal(await verifyPocPassword(
    'replacement battery staple',
    (await stateStore.readLocalCredentialForSubject('subject-one')).passwordHash,
  ), true)
  await assert.rejects(authenticator.authenticate({
    headers: { cookie: `datariver_poc_session=${first.token}` },
  }), (error) => error.code === 'SESSION_REQUIRED')
  await assert.rejects(authenticator.authenticate({
    headers: { cookie: `datariver_poc_session=${second.token}` },
  }), (error) => error.code === 'SESSION_REQUIRED')
})

test('fails password change generically for a wrong current password without mutating state', async () => {
  const { authenticator, stateStore } = await authFixture()
  const login = await authenticator.login('person@example.com', 'correct horse battery staple')
  const authentication = await authenticator.authenticate({
    headers: { cookie: `datariver_poc_session=${login.token}` },
  })
  const before = await stateStore.readLocalCredentialForSubject('subject-one')
  const genericPasswordChangeFailure = (error) => error.statusCode === 401
    && error.code === 'PASSWORD_CHANGE_FAILED'
    && !error.message.includes('current')

  await assert.rejects(authenticator.changePassword(authentication, {
    currentPassword: 'wrong current password',
    newPassword: 'replacement battery staple',
    confirmation: 'replacement battery staple',
  }), genericPasswordChangeFailure)

  const after = await stateStore.readLocalCredentialForSubject('subject-one')
  assert.equal(after.version, before.version)
  assert.equal(after.passwordHash, before.passwordHash)
  assert.equal((await stateStore.readLocalSession(login.tokenHash)).revokedAt, null)

  await assert.rejects(authenticator.changePassword(authentication, {
    currentPassword: 'x'.repeat(1025),
    newPassword: 'replacement battery staple',
    confirmation: 'replacement battery staple',
  }), genericPasswordChangeFailure)
})

test('rejects mismatched and out-of-policy replacement passwords with bounded typed errors', async () => {
  const { authenticator } = await authFixture()
  const login = await authenticator.login('person@example.com', 'correct horse battery staple')
  const authentication = await authenticator.authenticate({
    headers: { cookie: `datariver_poc_session=${login.token}` },
  })
  const invalid = (error) => error.statusCode === 400
    && error.code === 'PASSWORD_CHANGE_INPUT_INVALID'
    && error.message.length <= 128

  await assert.rejects(authenticator.changePassword(authentication, {
    currentPassword: 'correct horse battery staple',
    newPassword: 'replacement battery staple',
    confirmation: 'different replacement',
  }), invalid)
  await assert.rejects(authenticator.changePassword(authentication, {
    currentPassword: 'correct horse battery staple',
    newPassword: 'too short',
    confirmation: 'too short',
  }), invalid)
  await assert.rejects(authenticator.changePassword(authentication, {
    currentPassword: 'correct horse battery staple',
    newPassword: 'x'.repeat(1025),
    confirmation: 'x'.repeat(1025),
  }), invalid)
})

test('maps a stale credential CAS to a generic password-change conflict', async () => {
  const fixture = await authFixture()
  const login = await fixture.authenticator.login('person@example.com', 'correct horse battery staple')
  const authentication = await fixture.authenticator.authenticate({
    headers: { cookie: `datariver_poc_session=${login.token}` },
  })
  fixture.stateStore.changeOwnLocalPassword = async () => {
    throw Object.assign(new Error('internal credential version detail'), {
      statusCode: 409,
      code: 'CREDENTIAL_VERSION_STALE',
    })
  }

  await assert.rejects(fixture.authenticator.changePassword(authentication, {
    currentPassword: 'correct horse battery staple',
    newPassword: 'replacement battery staple',
    confirmation: 'replacement battery staple',
  }), (error) => error.statusCode === 409
    && error.code === 'PASSWORD_CHANGE_CONFLICT'
    && !error.message.includes('version'))
})

test('normalizes usernames and hashes passwords with encoded Argon2id', async () => {
  assert.equal(normalizePocUsername('  PERSON@Example.COM  '), 'person@example.com')
  assert.throws(() => normalizePocUsername('person name'), /normalized contract/)
  const passwordHash = await hashPocPassword('a sufficiently long local password', {
    salt: Buffer.from('fedcba9876543210'),
  })
  assert.match(passwordHash, /^\$argon2id\$v=19\$m=19456,t=2,p=1\$/)
  assert.equal(await verifyPocPassword('a sufficiently long local password', passwordHash), true)
  assert.equal(await verifyPocPassword('wrong password', passwordHash), false)
})

test('stores and resolves only the SHA-256 session-token hash', async () => {
  const { authenticator, stateStore } = await authFixture()
  const login = await authenticator.login('PERSON@example.com', 'correct horse battery staple')
  assert.match(login.token, /^[A-Za-z0-9_-]{43}$/)
  assert.equal(login.tokenHash, hashPocSessionToken(login.token))
  assert.notEqual(login.tokenHash, login.token)
  assert.equal((await stateStore.readLocalSession(login.tokenHash)).subjectId, 'subject-one')
  const authentication = await authenticator.authenticate({
    headers: { cookie: `unrelated=x; datariver_poc_session=${login.token}` },
  })
  assert.deepEqual(authentication, {
    subjectId: 'subject-one', tokenHash: login.tokenHash, mustChangePassword: false,
  })
})

test('rejects missing, duplicate, malformed, expired, and revoked session cookies', async () => {
  const { authenticator, advance } = await authFixture()
  await assert.rejects(authenticator.authenticate({ headers: {} }), (error) => error.statusCode === 401)
  await assert.rejects(authenticator.authenticate({
    headers: { cookie: 'datariver_poc_session=not-a-token' },
  }), (error) => error.statusCode === 401)
  const login = await authenticator.login('person@example.com', 'correct horse battery staple')
  await assert.rejects(authenticator.authenticate({
    headers: { cookie: `datariver_poc_session=${login.token}; datariver_poc_session=${login.token}` },
  }), (error) => error.statusCode === 401)
  const authentication = await authenticator.authenticate({
    headers: { cookie: `datariver_poc_session=${login.token}` },
  })
  await authenticator.logout(authentication)
  await assert.rejects(authenticator.authenticate({
    headers: { cookie: `datariver_poc_session=${login.token}` },
  }), (error) => error.statusCode === 401)
  const expiring = await authenticator.login('person@example.com', 'correct horse battery staple')
  advance(301_000)
  await assert.rejects(authenticator.authenticate({
    headers: { cookie: `datariver_poc_session=${expiring.token}` },
  }), (error) => error.statusCode === 401)
})

test('locks repeated failures without distinguishing an unknown username or wrong password', async () => {
  const { authenticator, advance } = await authFixture()
  const genericFailure = (error) => error.statusCode === 401
    && error.code === 'AUTHENTICATION_FAILED'
    && error.message === 'The username or password is invalid.'
  await assert.rejects(authenticator.login('unknown@example.com', 'wrong password'), genericFailure)
  for (let attempt = 0; attempt < 3; attempt += 1) {
    await assert.rejects(authenticator.login('person@example.com', 'wrong password'), genericFailure)
  }
  await assert.rejects(
    authenticator.login('person@example.com', 'correct horse battery staple'),
    genericFailure,
  )
  advance(31_000)
  assert.equal((await authenticator.login(
    'person@example.com',
    'correct horse battery staple',
  )).subjectId, 'subject-one')
})

test('requires an exact configured Origin and derives Secure cookies only from HTTPS', async () => {
  const { authenticator } = await authFixture()
  assert.doesNotThrow(() => authenticator.assertOrigin({ headers: { origin: config.publicOrigin } }))
  for (const origin of [undefined, 'http://localhost:39080', `${config.publicOrigin}/`]) {
    assert.throws(
      () => authenticator.assertOrigin({ headers: { ...(origin ? { origin } : {}) } }),
      (error) => error.statusCode === 403,
    )
  }
  const login = await authenticator.login('person@example.com', 'correct horse battery staple')
  assert.match(authenticator.setCookie(login.token), /HttpOnly; SameSite=Strict; Path=\/; Max-Age=300/)
  assert.doesNotMatch(authenticator.setCookie(login.token), /; Secure/)
  const https = loadPocLocalAuthConfig({ POC_PUBLIC_ORIGIN: 'https://poc.example.test' })
  assert.equal(https.secureCookie, true)
  for (const origin of [
    'http://127.0.0.1:39083',
    'http://10.20.30.40:39083',
    'http://172.20.30.40:39083',
    'http://192.168.10.40:39083',
    'http://[fd00::40]:39083',
  ]) {
    const intranet = loadPocLocalAuthConfig({ POC_PUBLIC_ORIGIN: origin })
    assert.equal(intranet.publicOrigin, origin)
    assert.equal(intranet.secureCookie, false)
  }
  assert.throws(
    () => loadPocLocalAuthConfig({ POC_PUBLIC_ORIGIN: 'http://poc.example.test' }),
    (error) => error.code === 'POC_PUBLIC_ORIGIN_MALFORMED',
  )
  assert.throws(
    () => loadPocLocalAuthConfig({ POC_PUBLIC_ORIGIN: 'http://203.0.113.10:39083' }),
    (error) => error.code === 'POC_PUBLIC_ORIGIN_NOT_APPROVED',
  )
})

test('allows only explicit bounded CIDRs beyond default intranet address ranges', () => {
  const exact = loadPocLocalAuthConfig({
    POC_PUBLIC_ORIGIN: 'http://203.0.113.10:39083',
    POC_INTRANET_HTTP_ALLOWED_CIDRS: '203.0.113.10/32',
  })
  assert.equal(exact.publicOrigin, 'http://203.0.113.10:39083')

  const corporate = loadPocLocalAuthConfig({
    POC_PUBLIC_ORIGIN: 'http://100.64.17.9:39083',
    POC_INTRANET_HTTP_ALLOWED_CIDRS: '198.51.100.0/24, 100.64.0.0/10',
  })
  assert.equal(corporate.publicOrigin, 'http://100.64.17.9:39083')

  const ipv6 = loadPocLocalAuthConfig({
    POC_PUBLIC_ORIGIN: 'http://[2001:db8:abcd::17]:39083',
    POC_INTRANET_HTTP_ALLOWED_CIDRS: '2001:db8:abcd::/48',
  })
  assert.equal(ipv6.publicOrigin, 'http://[2001:db8:abcd::17]:39083')

  assert.throws(
    () => loadPocLocalAuthConfig({
      POC_PUBLIC_ORIGIN: 'http://203.0.114.10:39083',
      POC_INTRANET_HTTP_ALLOWED_CIDRS: '203.0.113.0/24',
    }),
    (error) => error.code === 'POC_PUBLIC_ORIGIN_NOT_APPROVED',
  )
})

test('keeps exact Origin enforcement for an approved non-RFC1918 HTTP address', async () => {
  const approvedConfig = loadPocLocalAuthConfig({
    POC_PUBLIC_ORIGIN: 'http://100.64.17.9:39083',
    POC_INTRANET_HTTP_ALLOWED_CIDRS: '100.64.0.0/10',
  })
  const { authenticator } = await authFixture(approvedConfig)
  assert.doesNotThrow(() => authenticator.assertOrigin({
    headers: { origin: approvedConfig.publicOrigin },
  }))
  for (const origin of ['http://100.64.17.10:39083', 'https://100.64.17.9:39083', undefined]) {
    assert.throws(
      () => authenticator.assertOrigin({ headers: { ...(origin ? { origin } : {}) } }),
      (error) => error.statusCode === 403,
    )
  }
})

test('rejects malformed or unsafe CIDR configuration and unsafe HTTP hosts', () => {
  for (const cidrs of [
    '*', '203.0.113.0', '203.0.113.0/33', '2001:db8::/129',
    '0.0.0.0/0', '1.0.0.0/1', '::/0', '2000::/3',
    '224.0.0.0/4', 'ff00::/8', '203.0.113.0/24,',
  ]) {
    assert.throws(
      () => loadPocLocalAuthConfig({
        POC_PUBLIC_ORIGIN: 'http://203.0.113.10:39083',
        POC_INTRANET_HTTP_ALLOWED_CIDRS: cidrs,
      }),
      (error) => error.code === 'POC_INTRANET_HTTP_ALLOWED_CIDRS_INVALID',
    )
  }
  for (const origin of [
    'http://localhost:39083',
    'http://0.0.0.0:39083',
    'http://224.0.0.1:39083',
    'http://[::]:39083',
    'http://[ff02::1]:39083',
    'http://user:password@203.0.113.10:39083',
    'http://203.0.113.10:39083/path',
    'http://203.0.113.10:39083?query=1',
    'http://203.0.113.10:39083#fragment',
  ]) {
    assert.throws(
      () => loadPocLocalAuthConfig({
        POC_PUBLIC_ORIGIN: origin,
        POC_INTRANET_HTTP_ALLOWED_CIDRS: '203.0.113.0/24',
      }),
      (error) => error.code === 'POC_PUBLIC_ORIGIN_MALFORMED',
    )
  }
})
