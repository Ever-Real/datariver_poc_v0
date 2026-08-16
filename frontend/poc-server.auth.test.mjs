/* global Buffer, fetch */
import assert from 'node:assert/strict'
import test from 'node:test'

import { createPocLocalAuthenticator, hashPocPassword } from './poc-local-auth.mjs'
import { createPocServer } from './poc-server.mjs'
import { createPocStateStore } from './poc-state-store.mjs'

const AIRFLOW_SERVICE_TOKEN = 'airflow-worker-token-1234567890abcdef'

function accessDocument(users) {
  return {
    schema_version: 1,
    active_subject_id: 'metadata-only-subject',
    users: users.map((user) => ({ provider_owner_refs: [], ...user })),
    system_assignments: [],
  }
}

async function serverFixture() {
  const stateStore = createPocStateStore()
  const users = [
    { subject_id: 'subject-one', role: 'admin', active: true, display_name: 'First Person' },
    { subject_id: 'subject-two', role: 'viewer', active: true, display_name: 'Second Person' },
  ]
  const firstHash = await hashPocPassword('first correct password', {
    salt: Buffer.from('0123456789abcdef'),
  })
  const secondHash = await hashPocPassword('second correct password', {
    salt: Buffer.from('fedcba9876543210'),
  })
  await stateStore.provisionLocalCredential({
    expectedAccessVersion: 0,
    expectedCoreVersion: 0,
    accessValue: accessDocument(users),
    coreValue: {
      adminMemberships: [], adminSystems: [], adminSystemAssignees: [], adminSystemSchemaScopes: [],
    },
    credential: {
      subjectId: 'subject-one', usernameNormalized: 'first@example.com', passwordHash: firstHash,
      loginEnabled: true, mustChangePassword: false,
    },
  })
  await stateStore.insertLocalCredential({
    expectedAccessVersion: 1,
    expectedCoreVersion: 1,
    subjectId: 'subject-two', usernameNormalized: 'second@example.com', passwordHash: secondHash,
    loginEnabled: true, mustChangePassword: true,
  })
  const config = {
    publicOrigin: '', secureCookie: false, sessionTtlSeconds: 300, failedAttemptLimit: 3, lockSeconds: 30,
  }
  let entropy = 10
  const authenticator = createPocLocalAuthenticator({
    stateStore,
    config,
    randomBytes: () => Buffer.alloc(32, entropy++),
    allowInMemoryStoreForTests: true,
  })
  const server = createPocServer({ stateStore, authenticator, airflowServiceToken: AIRFLOW_SERVICE_TOKEN })
  await new Promise((resolvePromise) => server.listen(0, '127.0.0.1', resolvePromise))
  const address = server.address()
  assert.equal(typeof address, 'object')
  const origin = `http://127.0.0.1:${address.port}`
  config.publicOrigin = origin
  const close = async () => {
    server.closeAllConnections()
    await new Promise((resolvePromise, reject) => server.close((error) => error ? reject(error) : resolvePromise()))
  }
  const login = async (username, password, suppliedOrigin = origin) => {
    const response = await fetch(`${origin}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: suppliedOrigin },
      body: JSON.stringify({ username, password }),
    })
    const setCookie = response.headers.get('set-cookie')
    return { response, cookie: setCookie?.split(';', 1)[0] }
  }
  return { close, login, origin, stateStore, users }
}

test('binds concurrent browser sessions to current server-side access profiles', async () => {
  const fixture = await serverFixture()
  try {
    const [first, second] = await Promise.all([
      fixture.login('first@example.com', 'first correct password'),
      fixture.login('second@example.com', 'second correct password'),
    ])
    assert.equal(first.response.status, 200)
    assert.equal(second.response.status, 200)
    const firstLoginProfile = await first.response.json()
    assert.deepEqual(firstLoginProfile, {
      subject: 'subject-one',
      display_name: 'First Person',
      roles: ['admin'],
      authentication_assurance: 'PASSWORD',
      default_workspace_id: '00000000-0000-4000-8000-000000000061',
      workspace_selection_enabled: false,
      hardware_webauthn_enabled: false,
      password_change_supported: false,
      must_change_password: false,
    })
    assert.equal((await second.response.json()).subject, 'subject-two')
    const profiles = await Promise.all([first.cookie, second.cookie].map(async (cookie) => {
      const response = await fetch(`${fixture.origin}/auth/me`, { headers: { Cookie: cookie } })
      assert.equal(response.status, 200)
      return response.json()
    }))
    assert.deepEqual(profiles.map((profile) => profile.subject), ['subject-one', 'subject-two'])
    assert.deepEqual(profiles[0], firstLoginProfile)

    const snapshot = await fixture.stateStore.readChangeHistoryAccess()
    const refreshed = accessDocument([
      { ...fixture.users[0], role: 'viewer' },
      fixture.users[1],
    ])
    await fixture.stateStore.writeChangeHistoryAccess({
      expectedAccessVersion: snapshot.access.version,
      expectedCoreVersion: snapshot.core.version,
      accessValue: refreshed,
      coreValue: snapshot.core.value,
    })
    const refreshedProfile = await (await fetch(`${fixture.origin}/auth/me`, {
      headers: { Cookie: first.cookie },
    })).json()
    assert.deepEqual(refreshedProfile.roles, ['viewer'])

    const headerSpoof = await fetch(`${fixture.origin}/poc-api/capabilities`, {
      headers: { Cookie: first.cookie, 'X-Subject-Id': 'subject-two' },
    })
    assert.equal(headerSpoof.status, 400)
    const querySpoof = await fetch(`${fixture.origin}/poc-api/capabilities?subject_id=subject-two`, {
      headers: { Cookie: first.cookie },
    })
    assert.equal(querySpoof.status, 400)
    const bodySpoof = await fetch(`${fixture.origin}/poc-api/state/knowledge`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Cookie: first.cookie, Origin: fixture.origin },
      body: JSON.stringify({ value: { subject_id: 'subject-two', role: 'admin' } }),
    })
    assert.equal(bodySpoof.status, 200)
    assert.equal((await (await fetch(`${fixture.origin}/auth/me`, {
      headers: { Cookie: first.cookie },
    })).json()).subject, 'subject-one')

    const logout = await fetch(`${fixture.origin}/auth/logout`, {
      method: 'POST', headers: { Cookie: first.cookie, Origin: fixture.origin },
    })
    assert.equal(logout.status, 200)
    assert.deepEqual(await logout.json(), { ok: true })
    assert.match(logout.headers.get('set-cookie'), /Max-Age=0/)
    assert.equal((await fetch(`${fixture.origin}/auth/me`, { headers: { Cookie: first.cookie } })).status, 401)
  } finally {
    await fixture.close()
  }
})

test('enforces anonymous, Origin, JSON 404, inactive-subject, and Airflow-token boundaries', async () => {
  const fixture = await serverFixture()
  try {
    for (const path of ['/healthz', '/poc-runtime-config.js', '/', '/auth/login']) {
      assert.equal((await fetch(`${fixture.origin}${path}`)).status, 200, path)
    }
    assert.equal((await fetch(`${fixture.origin}/auth/me`)).status, 401)
    assert.equal((await fixture.login(
      'first@example.com', 'first correct password', 'http://127.0.0.1:1',
    )).response.status, 403)
    const login = await fixture.login('first@example.com', 'first correct password')
    assert.equal(login.response.status, 200)
    const csrf = await fetch(`${fixture.origin}/poc-api/state/knowledge`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Cookie: login.cookie, Origin: 'http://127.0.0.1:1' },
      body: JSON.stringify({ value: {} }),
    })
    assert.equal(csrf.status, 403)
    for (const path of ['/api/v1/not-a-route', '/poc-api/not-a-route']) {
      assert.equal((await fetch(`${fixture.origin}${path}`)).status, 401)
      const response = await fetch(`${fixture.origin}${path}`, { headers: { Cookie: login.cookie } })
      assert.equal(response.status, 404)
      assert.match(response.headers.get('content-type'), /^application\/json/)
    }

    const missingServiceToken = await fetch(`${fixture.origin}/api/v1/registration/bulk-preparations/execute`, {
      method: 'POST',
    })
    assert.equal(missingServiceToken.status, 401)
    const inexactServiceToken = await fetch(`${fixture.origin}/api/v1/registration/bulk-preparations/execute`, {
      method: 'POST', headers: { Authorization: `Bearer ${AIRFLOW_SERVICE_TOKEN}x` },
    })
    assert.equal(inexactServiceToken.status, 401)
    const worker = await fetch(`${fixture.origin}/api/v1/registration/bulk-preparations/execute`, {
      method: 'POST', headers: { Authorization: `Bearer ${AIRFLOW_SERVICE_TOKEN}` },
    })
    assert.equal(worker.status, 200)
    assert.deepEqual(await worker.json(), { processed: false })
    assert.equal((await fetch(`${fixture.origin}/poc-api/capabilities`, {
      headers: { Authorization: `Bearer ${AIRFLOW_SERVICE_TOKEN}` },
    })).status, 401)

    const snapshot = await fixture.stateStore.readChangeHistoryAccess()
    await fixture.stateStore.writeChangeHistoryAccess({
      expectedAccessVersion: snapshot.access.version,
      expectedCoreVersion: snapshot.core.version,
      accessValue: accessDocument([
        { ...fixture.users[0], active: false },
        fixture.users[1],
      ]),
      coreValue: snapshot.core.value,
    })
    assert.equal((await fetch(`${fixture.origin}/auth/me`, { headers: { Cookie: login.cookie } })).status, 403)
  } finally {
    await fixture.close()
  }
})
