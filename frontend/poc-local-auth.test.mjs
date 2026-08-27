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

async function authFixture() {
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
    config,
    now: () => new Date(currentTime),
    randomBytes: () => Buffer.alloc(32, entropy++),
    allowInMemoryStoreForTests: true,
  })
  return {
    authenticator,
    stateStore,
    advance(milliseconds) { currentTime += milliseconds },
  }
}

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
    /HTTP only for a loopback or private intranet IP/,
  )
  assert.throws(
    () => loadPocLocalAuthConfig({ POC_PUBLIC_ORIGIN: 'http://203.0.113.10:39083' }),
    /private intranet IP/,
  )
})
