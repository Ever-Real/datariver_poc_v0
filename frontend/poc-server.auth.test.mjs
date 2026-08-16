/* global Buffer, fetch */
import assert from 'node:assert/strict'
import test from 'node:test'

import { createPocLocalAuthenticator, hashPocPassword } from './poc-local-auth.mjs'
import { createPocServer } from './poc-server.mjs'
import { createPocStateStore } from './poc-state-store.mjs'
import { changeHistoryAccessCoreProjection, privateChangeHistoryAccess } from './poc-access-document.mjs'

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
  await stateStore.write('catalog-inventory-v1:disabled', {
    projection_version: 1,
    source_scope: 'disabled',
    source_generation: 'a'.repeat(64),
    observed_at: new Date().toISOString(),
    items: [
      { id: 'urn:table:a', external_urn: 'urn:table:a', name: 'table_a', dataset_kind: 'TABLE', platform: 'postgres', database_name: 'db', schema_name: 'schema_a', tags: [] },
      { id: 'urn:table:b', external_urn: 'urn:table:b', name: 'table_b', dataset_kind: 'TABLE', platform: 'postgres', database_name: 'db', schema_name: 'schema_b', tags: ['restricted'] },
      { id: 'urn:view:a', external_urn: 'urn:view:a', name: 'view_a', dataset_kind: 'VIEW', platform: 'postgres', database_name: 'db', schema_name: 'schema_a', tags: [] },
    ],
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
      authorization: {
        policy_version: 'POC_PROFILE_CAPABILITIES_V1',
        role: 'admin',
        capabilities: [
          'catalog.read', 'catalog.execute', 'catalog.manage', 'chat.query',
          'change.read', 'change.execute', 'change.manage', 'monitoring.read',
          'knowledge.read', 'knowledge.manage', 'knowledge.review',
          'quality.read', 'quality.execute', 'quality.manage', 'admin.manage',
        ],
        system_scope: 'GLOBAL',
        system_ids: [],
      },
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
    assert.equal(bodySpoof.status, 403)
    assert.equal((await bodySpoof.json()).code, 'CAPABILITY_REQUIRED')
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

test('fences exact Table-System mappings with admin capability, current identities, Origin, and CAS', async () => {
  const fixture = await serverFixture()
  try {
    const [admin, viewer] = await Promise.all([
      fixture.login('first@example.com', 'first correct password'),
      fixture.login('second@example.com', 'second correct password'),
    ])
    assert.equal(admin.response.status, 200)
    assert.equal(viewer.response.status, 200)

    const accessSnapshot = await fixture.stateStore.readChangeHistoryAccess()
    const updatedAccess = {
      ...accessSnapshot.access.value,
      systems: [{ system_id: 'system-a', code: 'SYSTEM-A', name: 'System A', description: '', active: true, version: 1 }],
      system_schema_scopes: [],
    }
    await fixture.stateStore.writeChangeHistoryAccess({
      expectedAccessVersion: accessSnapshot.access.version,
      expectedCoreVersion: accessSnapshot.core.version,
      accessValue: privateChangeHistoryAccess(updatedAccess),
      coreValue: changeHistoryAccessCoreProjection(
        accessSnapshot.core.value,
        updatedAccess,
        accessSnapshot.access.version + 1,
      ),
    })

    const viewerRead = await fetch(`${fixture.origin}/api/v1/admin/table-system-mappings`, {
      headers: { Cookie: viewer.cookie },
    })
    const viewerProblem = await viewerRead.json()
    assert.equal(viewerRead.status, 403, JSON.stringify(viewerProblem))
    assert.equal(viewerProblem.code, 'CAPABILITY_REQUIRED')

    const initial = await fetch(`${fixture.origin}/api/v1/admin/table-system-mappings`, {
      headers: { Cookie: admin.cookie },
    })
    assert.equal(initial.status, 200)
    assert.equal(initial.headers.get('etag'), '"0"')
    const initialBody = await initial.json()
    assert.deepEqual(initialBody.items.map((item) => item.table_identity), ['urn:table:a', 'urn:table:b'])
    assert.deepEqual(initialBody.items.map((item) => item.security_grade), ['normal', 'restricted'])

    const command = {
      action: 'ASSIGN', table_ids: ['urn:table:a'], system_ids: ['system-a'], reason: 'assign exact runtime Table',
    }
    const csrf = await fetch(`${fixture.origin}/api/v1/admin/table-system-mappings`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Cookie: admin.cookie, 'If-Match': '"0"', Origin: 'http://127.0.0.1:1' },
      body: JSON.stringify(command),
    })
    assert.equal(csrf.status, 403)

    const assigned = await fetch(`${fixture.origin}/api/v1/admin/table-system-mappings`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Cookie: admin.cookie, 'If-Match': '"0"', Origin: fixture.origin },
      body: JSON.stringify(command),
    })
    assert.equal(assigned.status, 200)
    assert.deepEqual(await assigned.json(), { version: 1, changed: 1 })

    const filtered = await fetch(`${fixture.origin}/api/v1/admin/table-system-mappings?system_id=system-a`, {
      headers: { Cookie: admin.cookie },
    })
    assert.equal(filtered.status, 200)
    assert.deepEqual((await filtered.json()).items.map((item) => item.table_identity), ['urn:table:a'])

    const stale = await fetch(`${fixture.origin}/api/v1/admin/table-system-mappings`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Cookie: admin.cookie, 'If-Match': '"0"', Origin: fixture.origin },
      body: JSON.stringify(command),
    })
    assert.equal(stale.status, 409)
    assert.equal((await stale.json()).code, 'TABLE_SYSTEM_MAPPING_VERSION_STALE')

    const invalidTable = await fetch(`${fixture.origin}/api/v1/admin/table-system-mappings`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Cookie: admin.cookie, 'If-Match': '"1"', Origin: fixture.origin },
      body: JSON.stringify({ ...command, table_ids: ['urn:missing'] }),
    })
    assert.equal(invalidTable.status, 400)
    assert.equal((await invalidTable.json()).code, 'TABLE_SYSTEM_TABLE_INVALID')

    const removed = await fetch(`${fixture.origin}/api/v1/admin/table-system-mappings`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Cookie: admin.cookie, 'If-Match': '"1"', Origin: fixture.origin },
      body: JSON.stringify({ ...command, action: 'REMOVE', reason: 'remove exact runtime Table' }),
    })
    assert.equal(removed.status, 200)
    assert.deepEqual(await removed.json(), { version: 2, changed: 1 })
    const stored = await fixture.stateStore.read('table-system-mappings-v1')
    assert.equal(stored.value.bindings[0].active, false)
    assert.equal(stored.value.bindings[0].version, 2)
  } finally {
    await fixture.close()
  }
})

test('enforces anonymous, Origin, JSON 404, inactive-subject, and Airflow-token boundaries', async () => {
  const fixture = await serverFixture()
  try {
    for (const path of ['/healthz', '/poc-runtime-config.js', '/']) {
      assert.equal((await fetch(`${fixture.origin}${path}`)).status, 200, path)
    }
    assert.equal((await fetch(`${fixture.origin}/healthz`, { method: 'POST' })).status, 405)
    assert.equal((await fetch(`${fixture.origin}/poc-runtime-config.js`, { method: 'POST' })).status, 405)
    const loginShell = await fetch(`${fixture.origin}/auth/login`)
    assert.equal(loginShell.status, 200)
    const loginHtml = await loginShell.text()
    assert.match(loginHtml, /<base href="\/">/)
    assert.ok(loginHtml.indexOf('<base href="/">') < loginHtml.indexOf('<script type="module"'))
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
