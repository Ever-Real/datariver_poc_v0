/* global Buffer, URL, fetch, structuredClone */
import assert from 'node:assert/strict'
import { request as httpRequest } from 'node:http'
import test from 'node:test'

import { createPocLocalAuthenticator, hashPocPassword } from './poc-local-auth.mjs'
import { createPocServer, currentDatahubDatasetExists } from './poc-server.mjs'
import { createPocStateStore } from './poc-state-store.mjs'
import { changeHistoryAccessCoreProjection, privateChangeHistoryAccess } from './poc-access-document.mjs'

const AIRFLOW_SERVICE_TOKEN = 'airflow-worker-token-1234567890abcdef'
const MCP_SERVICE_TOKEN = 'mcp-service-token-1234567890abcdef'
const MCP_WORKSPACE_ID = '00000000-0000-4000-8000-000000000061'
const CURRENT_TABLE_URN = 'urn:li:dataset:(urn:li:dataPlatform:postgres,db.schema.table_c,PROD)'

function getWithHost(url, host) {
  const target = new URL(url)
  return new Promise((resolve, reject) => {
    const request = httpRequest({
      hostname: '127.0.0.1',
      port: target.port,
      path: `${target.pathname}${target.search}`,
      method: 'GET',
      headers: { Host: host },
    }, (response) => {
      response.resume()
      response.once('end', () => resolve(response))
    })
    request.once('error', reject)
    request.end()
  })
}

test('rejects the ghost Dataset shell that DataHub returns for a nonexistent URN', () => {
  assert.equal(currentDatahubDatasetExists({
    urn: CURRENT_TABLE_URN,
    type: 'DATASET',
    properties: { customProperties: [] },
    schemaMetadata: null,
  }, CURRENT_TABLE_URN), true)
  assert.equal(currentDatahubDatasetExists({
    urn: CURRENT_TABLE_URN,
    type: 'DATASET',
    properties: null,
    schemaMetadata: null,
  }, CURRENT_TABLE_URN), false)
})

function accessDocument(users) {
  return {
    schema_version: 1,
    active_subject_id: 'metadata-only-subject',
    users: users.map((user) => ({ provider_owner_refs: [], ...user })),
    system_assignments: [],
  }
}

async function serverFixture(canonicalOrigin = null) {
  const stateStore = createPocStateStore()
  const providerInventory = [
    { id: 'urn:table:a', external_urn: 'urn:table:a', name: 'table_a', dataset_kind: 'TABLE', platform: 'postgres', database_name: 'db', schema_name: 'schema_a', tags: [] },
    { id: 'urn:table:b', external_urn: 'urn:table:b', name: 'table_b', dataset_kind: 'TABLE', platform: 'postgres', database_name: 'db', schema_name: 'schema_b', tags: ['restricted'] },
    { id: 'urn:view:a', external_urn: 'urn:view:a', name: 'view_a', dataset_kind: 'VIEW', platform: 'postgres', database_name: 'db', schema_name: 'schema_a', tags: [] },
    { id: CURRENT_TABLE_URN, external_urn: CURRENT_TABLE_URN, name: 'table_c', dataset_kind: 'TABLE', platform: 'postgres', database_name: 'db', schema_name: 'schema_c', tags: ['credential', 'restricted'] },
  ]
  let currentProviderInventory = providerInventory
  let currentProviderError
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
    items: providerInventory,
  })
  const config = {
    publicOrigin: '', secureCookie: false, sessionTtlSeconds: 300, failedAttemptLimit: 3, lockSeconds: 30,
  }
  let entropy = 10
  const authenticator = createPocLocalAuthenticator({
    stateStore,
    config,
    randomBytes: (size) => Buffer.alloc(size, entropy++),
    allowInMemoryStoreForTests: true,
  })
  const server = createPocServer({
    stateStore,
    authenticator,
    airflowServiceToken: AIRFLOW_SERVICE_TOKEN,
    mcpServiceToken: MCP_SERVICE_TOKEN,
    mcpSubjectId: 'subject-two',
    mcpWorkspaceId: MCP_WORKSPACE_ID,
    currentDatahubInventory: async () => {
      if (currentProviderError) throw currentProviderError
      return structuredClone(currentProviderInventory)
    },
    currentDatahubTables: async (tableUrns) => {
      if (currentProviderError) throw currentProviderError
      return structuredClone(currentProviderInventory.filter((item) => tableUrns.includes(item.id)))
    },
  })
  await new Promise((resolvePromise) => server.listen(0, '127.0.0.1', resolvePromise))
  const address = server.address()
  assert.equal(typeof address, 'object')
  const origin = `http://127.0.0.1:${address.port}`
  config.publicOrigin = canonicalOrigin ?? origin
  const close = async () => {
    server.closeAllConnections()
    await new Promise((resolvePromise, reject) => server.close((error) => error ? reject(error) : resolvePromise()))
  }
  const login = async (username, password, suppliedOrigin = config.publicOrigin) => {
    const response = await fetch(`${origin}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: suppliedOrigin },
      body: JSON.stringify({ username, password }),
    })
    const setCookie = response.headers.get('set-cookie')
    return { response, cookie: setCookie?.split(';', 1)[0] }
  }
  return {
    close,
    login,
    origin,
    canonicalOrigin: config.publicOrigin,
    stateStore,
    users,
    setCurrentProviderInventory(value) { currentProviderInventory = value },
    setCurrentProviderError(value) { currentProviderError = value },
  }
}

test('separates loopback transport from canonical intranet Origin for authentication', async () => {
  const fixture = await serverFixture('http://17.20.30.40:39083')
  try {
    const canonical = await fixture.login('first@example.com', 'first correct password')
    assert.equal(canonical.response.status, 200)
    assert.ok(canonical.cookie)

    const wrongOrigin = await fixture.login(
      'first@example.com',
      'first correct password',
      fixture.origin,
    )
    assert.equal(wrongOrigin.response.status, 403)
    assert.equal((await wrongOrigin.response.json()).code, 'ORIGIN_FORBIDDEN')

    const wrongPassword = await fixture.login('first@example.com', 'wrong password')
    assert.equal(wrongPassword.response.status, 401)
    assert.equal((await wrongPassword.response.json()).code, 'AUTHENTICATION_FAILED')

    const logout = await fetch(`${fixture.origin}/auth/logout`, {
      method: 'POST',
      headers: { Cookie: canonical.cookie, Origin: fixture.canonicalOrigin },
    })
    assert.equal(logout.status, 200)
  } finally {
    await fixture.close()
  }
})

test('exports the complete authorized Catalog selection as owner-bound CSV and XLSX artifacts', async () => {
  const fixture = await serverFixture()
  try {
    const admin = await fixture.login('first@example.com', 'first correct password')
    const viewer = await fixture.login('second@example.com', 'second correct password')
    assert.ok(admin.cookie)
    assert.ok(viewer.cookie)
    const create = async (format, idempotencyKey) => fetch(`${fixture.origin}/poc-api/datahub/catalog/exports`, {
      method: 'POST',
      headers: {
        Cookie: admin.cookie,
        Origin: fixture.canonicalOrigin,
        'Content-Type': 'application/json',
        'Idempotency-Key': idempotencyKey,
      },
      body: JSON.stringify({
        q: '*',
        sort: 'NAME_ASC',
        format,
      }),
    })

    const csvCreate = await create('CSV', 'generic-catalog-export-csv')
    const csvCreated = await csvCreate.json()
    assert.equal(csvCreate.status, 201, JSON.stringify(csvCreated))
    assert.equal(csvCreated.state, 'COMPLETED')

    const replay = await create('CSV', 'generic-catalog-export-csv')
    assert.equal(replay.status, 201)
    assert.equal((await replay.json()).export_id, csvCreated.export_id)

    const statusResponse = await fetch(
      `${fixture.origin}/poc-api/datahub/catalog/exports/${csvCreated.export_id}`,
      { headers: { Cookie: admin.cookie } },
    )
    const status = await statusResponse.json()
    assert.equal(statusResponse.status, 200, JSON.stringify(status))
    assert.equal(status.row_count, 1)
    assert.equal(status.state, 'COMPLETED')

    const deniedOwner = await fetch(
      `${fixture.origin}/poc-api/datahub/catalog/exports/${csvCreated.export_id}`,
      { headers: { Cookie: viewer.cookie } },
    )
    assert.equal(deniedOwner.status, 404)

    const downloadResponse = await fetch(
      `${fixture.origin}/poc-api/datahub/catalog/exports/${csvCreated.export_id}/download`,
      { method: 'POST', headers: { Cookie: admin.cookie, Origin: fixture.canonicalOrigin } },
    )
    const download = await downloadResponse.json()
    assert.equal(downloadResponse.status, 200, JSON.stringify(download))
    const fileResponse = await fetch(`${fixture.origin}${download.url}`, {
      headers: { Cookie: admin.cookie },
    })
    const csv = Buffer.from(await fileResponse.arrayBuffer())
    assert.equal(fileResponse.status, 200)
    assert.equal(fileResponse.headers.get('content-type'), 'text/csv; charset=utf-8')
    assert.deepEqual([...csv.subarray(0, 3)], [0xef, 0xbb, 0xbf])
    assert.match(csv.toString('utf8'), /table_c/)

    const xlsxCreate = await create('XLSX', 'generic-catalog-export-xlsx')
    const xlsxCreated = await xlsxCreate.json()
    assert.equal(xlsxCreate.status, 201, JSON.stringify(xlsxCreated))
    const xlsxDownload = await (await fetch(
      `${fixture.origin}/poc-api/datahub/catalog/exports/${xlsxCreated.export_id}/download`,
      { method: 'POST', headers: { Cookie: admin.cookie, Origin: fixture.canonicalOrigin } },
    )).json()
    const xlsxResponse = await fetch(`${fixture.origin}${xlsxDownload.url}`, {
      headers: { Cookie: admin.cookie },
    })
    const xlsx = Buffer.from(await xlsxResponse.arrayBuffer())
    assert.equal(xlsxResponse.status, 200)
    assert.equal(xlsx.subarray(0, 2).toString('ascii'), 'PK')
  } finally {
    await fixture.close()
  }
})

test('Catalog export fails closed for missing origin, malformed input, and RESTRICTED scope', async () => {
  const fixture = await serverFixture()
  try {
    const admin = await fixture.login('first@example.com', 'first correct password')
    assert.ok(admin.cookie)
    const request = (body, headers = {}) => fetch(`${fixture.origin}/poc-api/datahub/catalog/exports`, {
      method: 'POST',
      headers: {
        Cookie: admin.cookie,
        'Content-Type': 'application/json',
        'Idempotency-Key': 'generic-catalog-export-deny',
        ...headers,
      },
      body: JSON.stringify(body),
    })
    const payload = { q: '*', sort: 'NAME_ASC', format: 'CSV' }
    const missingOrigin = await request(payload)
    assert.equal(missingOrigin.status, 403)
    assert.equal((await missingOrigin.json()).code, 'ORIGIN_FORBIDDEN')

    const malformed = await request({ ...payload, unsupported: true }, { Origin: fixture.canonicalOrigin })
    assert.equal(malformed.status, 400)
    assert.equal((await malformed.json()).code, 'CATALOG_EXPORT_INPUT_INVALID')

    const restricted = await request(
      { ...payload, classification: 'RESTRICTED' },
      { Origin: fixture.canonicalOrigin, 'Idempotency-Key': 'generic-catalog-export-restricted' },
    )
    assert.equal(restricted.status, 403)
    assert.equal((await restricted.json()).code, 'CATALOG_EXPORT_RESTRICTED')
  } finally {
    await fixture.close()
  }
})

test('user MCP requires a real local session and exact canonical Origin while service MCP remains bearer-only', async () => {
  const fixture = await serverFixture('http://17.20.30.40:39083')
  try {
    const rpc = { jsonrpc: '2.0', method: 'initialize', id: 1 }
    const anonymous = await fetch(`${fixture.origin}/api/v1/mcp/user`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Origin: fixture.canonicalOrigin }, body: JSON.stringify(rpc),
    })
    assert.equal(anonymous.status, 401)
    const login = await fixture.login('first@example.com', 'first correct password')
    assert.equal(login.response.status, 200)
    const missingOrigin = await fetch(`${fixture.origin}/api/v1/mcp/user`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Cookie: login.cookie }, body: JSON.stringify(rpc),
    })
    assert.equal(missingOrigin.status, 403)
    assert.equal((await missingOrigin.json()).code, 'ORIGIN_FORBIDDEN')
    const wrongOrigin = await fetch(`${fixture.origin}/api/v1/mcp/user`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Cookie: login.cookie, Origin: fixture.origin }, body: JSON.stringify(rpc),
    })
    assert.equal(wrongOrigin.status, 403)
    assert.equal((await wrongOrigin.json()).code, 'ORIGIN_FORBIDDEN')
    const user = await fetch(`${fixture.origin}/api/v1/mcp/user`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Cookie: login.cookie, Origin: fixture.canonicalOrigin }, body: JSON.stringify(rpc),
    })
    const userBody = await user.json()
    assert.equal(user.status, 200, JSON.stringify(userBody))
    assert.equal(userBody.result.serverInfo.name, 'datariver-k8-mcp')

    const service = await fetch(`${fixture.origin}/api/v1/mcp`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${MCP_SERVICE_TOKEN}` }, body: JSON.stringify(rpc),
    })
    assert.equal(service.status, 200)
    assert.equal((await service.json()).result.serverInfo.name, 'datariver-k8-mcp')
  } finally {
    await fixture.close()
  }
})

test('site branding is anonymously readable while mutation requires admin CAS and idempotency', async () => {
  const fixture = await serverFixture()
  try {
    const anonymous = await fetch(`${fixture.origin}/api/v1/site-branding`)
    assert.equal(anonymous.status, 200)
    assert.equal(anonymous.headers.get('etag'), '"0"')
    assert.deepEqual(await anonymous.json(), { site_name: 'DataRiver', logo: null, favicon: null })

    const anonymousMutation = await fetch(`${fixture.origin}/api/v1/site-branding`, {
      method: 'PUT',
      headers: {
        Origin: fixture.canonicalOrigin,
        'Content-Type': 'application/json',
        'If-Match': '"0"',
        'Idempotency-Key': 'generic-anonymous-branding-attempt',
      },
      body: JSON.stringify({ site_name: 'Denied', logo: null, favicon: null, restore_default: false }),
    })
    assert.equal(anonymousMutation.status, 401)
    assert.equal((await anonymousMutation.json()).code, 'SESSION_REQUIRED')

    const viewer = await fixture.login('second@example.com', 'second correct password')
    assert.ok(viewer.cookie)
    const denied = await fetch(`${fixture.origin}/api/v1/site-branding`, {
      method: 'PUT',
      headers: {
        Cookie: viewer.cookie,
        Origin: fixture.canonicalOrigin,
        'Content-Type': 'application/json',
        'If-Match': '"0"',
        'Idempotency-Key': 'generic-viewer-branding-attempt',
      },
      body: JSON.stringify({ site_name: 'Denied', logo: null, favicon: null, restore_default: false }),
    })
    assert.equal(denied.status, 403)
    assert.equal((await denied.json()).code, 'CAPABILITY_REQUIRED')

    const admin = await fixture.login('first@example.com', 'first correct password')
    assert.ok(admin.cookie)
    const headers = {
      Cookie: admin.cookie,
      Origin: fixture.canonicalOrigin,
      'Content-Type': 'application/json',
      'If-Match': '"0"',
      'Idempotency-Key': 'generic-admin-branding-update',
    }
    const body = JSON.stringify({ site_name: 'Generic Portal', logo: null, favicon: null, restore_default: false })
    const missingOriginHeaders = { ...headers }
    delete missingOriginHeaders.Origin
    const missingOrigin = await fetch(`${fixture.origin}/api/v1/site-branding`, {
      method: 'PUT', headers: missingOriginHeaders, body,
    })
    assert.equal(missingOrigin.status, 403)
    assert.equal((await missingOrigin.json()).code, 'ORIGIN_FORBIDDEN')
    const wrongOrigin = await fetch(`${fixture.origin}/api/v1/site-branding`, {
      method: 'PUT', headers: { ...headers, Origin: 'http://wrong-origin.invalid' }, body,
    })
    assert.equal(wrongOrigin.status, 403)
    assert.equal((await wrongOrigin.json()).code, 'ORIGIN_FORBIDDEN')

    const updated = await fetch(`${fixture.origin}/api/v1/site-branding`, { method: 'PUT', headers, body })
    assert.equal(updated.status, 200)
    assert.equal(updated.headers.get('etag'), '"1"')
    assert.deepEqual(await updated.json(), { site_name: 'Generic Portal', logo: null, favicon: null })

    const replay = await fetch(`${fixture.origin}/api/v1/site-branding`, { method: 'PUT', headers, body })
    assert.equal(replay.status, 200)
    assert.equal(replay.headers.get('etag'), '"1"')

    const replayWithoutIfMatchHeaders = { ...headers }
    delete replayWithoutIfMatchHeaders['If-Match']
    const replayWithoutIfMatch = await fetch(`${fixture.origin}/api/v1/site-branding`, {
      method: 'PUT', headers: replayWithoutIfMatchHeaders, body,
    })
    assert.equal(replayWithoutIfMatch.status, 428)
    assert.equal((await replayWithoutIfMatch.json()).code, 'IF_MATCH_REQUIRED')
    const replayWithMalformedIfMatch = await fetch(`${fixture.origin}/api/v1/site-branding`, {
      method: 'PUT', headers: { ...headers, 'If-Match': '0' }, body,
    })
    assert.equal(replayWithMalformedIfMatch.status, 400)
    assert.equal((await replayWithMalformedIfMatch.json()).code, 'IF_MATCH_INVALID')

    const stale = await fetch(`${fixture.origin}/api/v1/site-branding`, {
      method: 'PUT',
      headers: { ...headers, 'Idempotency-Key': 'generic-admin-stale-update' },
      body: JSON.stringify({ site_name: 'Stale Portal', logo: null, favicon: null, restore_default: false }),
    })
    assert.equal(stale.status, 409)
    assert.equal((await stale.json()).code, 'SITE_BRANDING_VERSION_STALE')
  } finally {
    await fixture.close()
  }
})

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
      max_security_grade: 'normal',
      authentication_assurance: 'PASSWORD',
      default_workspace_id: '00000000-0000-4000-8000-000000000061',
      workspace_selection_enabled: false,
      hardware_webauthn_enabled: false,
      password_change_supported: true,
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

test('changes the current local subject password and revokes every session without widening target authority', async () => {
  const fixture = await serverFixture()
  try {
    const first = await fixture.login('first@example.com', 'first correct password')
    const sibling = await fixture.login('first@example.com', 'first correct password')
    const other = await fixture.login('second@example.com', 'second correct password')
    assert.equal(first.response.status, 200)
    assert.equal(sibling.response.status, 200)
    assert.equal(other.response.status, 200)

    const wrongOrigin = await fetch(`${fixture.origin}/auth/password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Cookie: first.cookie, Origin: 'http://127.0.0.1:1' },
      body: JSON.stringify({
        current_password: 'first correct password',
        new_password: 'first replacement password',
        new_password_confirmation: 'first replacement password',
      }),
    })
    assert.equal(wrongOrigin.status, 403)
    assert.equal((await wrongOrigin.json()).code, 'ORIGIN_FORBIDDEN')

    const wrongCurrent = await fetch(`${fixture.origin}/auth/password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Cookie: first.cookie, Origin: fixture.origin },
      body: JSON.stringify({
        current_password: 'wrong current password',
        new_password: 'first replacement password',
        new_password_confirmation: 'first replacement password',
      }),
    })
    assert.equal(wrongCurrent.status, 401)
    const wrongCurrentProblem = await wrongCurrent.json()
    assert.equal(wrongCurrentProblem.code, 'PASSWORD_CHANGE_FAILED')
    assert.doesNotMatch(JSON.stringify(wrongCurrentProblem), /wrong current password|first correct password/)

    const targetAttempt = await fetch(`${fixture.origin}/auth/password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Cookie: first.cookie, Origin: fixture.origin },
      body: JSON.stringify({
        current_password: 'first correct password',
        new_password: 'first replacement password',
        new_password_confirmation: 'first replacement password',
        subject_id: 'subject-two',
      }),
    })
    assert.equal(targetAttempt.status, 400)
    assert.equal((await targetAttempt.json()).code, 'PASSWORD_CHANGE_INPUT_INVALID')

    for (const body of ['{', JSON.stringify({ current_password: 'x'.repeat(5000) })]) {
      const malformed = await fetch(`${fixture.origin}/auth/password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Cookie: first.cookie, Origin: fixture.origin },
        body,
      })
      assert.equal(malformed.status, 400)
      assert.equal((await malformed.json()).code, 'PASSWORD_CHANGE_INPUT_INVALID')
    }

    for (const [newPassword, confirmation] of [
      ['first replacement password', 'mismatched replacement'],
      ['short', 'short'],
      ['x'.repeat(1025), 'x'.repeat(1025)],
    ]) {
      const invalid = await fetch(`${fixture.origin}/auth/password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Cookie: first.cookie, Origin: fixture.origin },
        body: JSON.stringify({
          current_password: 'first correct password',
          new_password: newPassword,
          new_password_confirmation: confirmation,
        }),
      })
      assert.equal(invalid.status, 400)
      assert.equal((await invalid.json()).code, 'PASSWORD_CHANGE_INPUT_INVALID')
    }

    const changed = await fetch(`${fixture.origin}/auth/password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Cookie: first.cookie, Origin: fixture.origin },
      body: JSON.stringify({
        current_password: 'first correct password',
        new_password: 'first replacement password',
        new_password_confirmation: 'first replacement password',
      }),
    })
    assert.equal(changed.status, 200, JSON.stringify(await changed.clone().json()))
    assert.deepEqual(await changed.json(), { ok: true, reauthentication_required: true })
    assert.match(changed.headers.get('set-cookie'), /Max-Age=0/)
    assert.equal((await fetch(`${fixture.origin}/auth/me`, { headers: { Cookie: first.cookie } })).status, 401)
    assert.equal((await fetch(`${fixture.origin}/auth/me`, { headers: { Cookie: sibling.cookie } })).status, 401)
    assert.equal((await fetch(`${fixture.origin}/auth/me`, { headers: { Cookie: other.cookie } })).status, 200)
    assert.equal((await fixture.login('first@example.com', 'first correct password')).response.status, 401)
    assert.equal((await fixture.login('first@example.com', 'first replacement password')).response.status, 200)
    assert.equal((await fixture.login('second@example.com', 'second correct password')).response.status, 200)
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
    assert.deepEqual(initialBody.items.map((item) => item.table_identity), ['urn:table:a', 'urn:table:b', CURRENT_TABLE_URN])
    assert.deepEqual(initialBody.items.map((item) => item.security_grade), ['normal', 'restricted', 'restricted'])

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

    fixture.setCurrentProviderInventory([
      { id: 'urn:table:a', dataset_kind: 'VIEW' },
      { id: 'urn:table:b', dataset_kind: 'TABLE' },
    ])
    const changedKind = await fetch(`${fixture.origin}/api/v1/admin/table-system-mappings`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Cookie: admin.cookie, 'If-Match': '"1"', Origin: fixture.origin },
      body: JSON.stringify({ ...command, action: 'REMOVE', reason: 'reject a type-changed Table' }),
    })
    assert.equal(changedKind.status, 400)
    assert.equal((await changedKind.json()).code, 'TABLE_SYSTEM_TABLE_INVALID')
    assert.equal((await fixture.stateStore.read('table-system-mappings-v1')).version, 1)

    fixture.setCurrentProviderInventory([{ id: 'urn:table:b', dataset_kind: 'TABLE' }])
    const deletedTable = await fetch(`${fixture.origin}/api/v1/admin/table-system-mappings`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Cookie: admin.cookie, 'If-Match': '"1"', Origin: fixture.origin },
      body: JSON.stringify({ ...command, action: 'REMOVE', reason: 'reject a deleted Table identity' }),
    })
    assert.equal(deletedTable.status, 400)
    assert.equal((await deletedTable.json()).code, 'TABLE_SYSTEM_TABLE_INVALID')
    assert.equal((await fixture.stateStore.read('table-system-mappings-v1')).version, 1)

    fixture.setCurrentProviderError(new Error('provider unavailable'))
    const providerUnavailable = await fetch(`${fixture.origin}/api/v1/admin/table-system-mappings`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Cookie: admin.cookie, 'If-Match': '"1"', Origin: fixture.origin },
      body: JSON.stringify({ ...command, action: 'REMOVE', reason: 'reject without provider confirmation' }),
    })
    assert.equal(providerUnavailable.status, 503)
    assert.equal((await providerUnavailable.json()).code, 'TABLE_SYSTEM_CURRENT_TABLES_UNAVAILABLE')
    assert.equal((await fixture.stateStore.read('table-system-mappings-v1')).version, 1)

    fixture.setCurrentProviderError(undefined)
    fixture.setCurrentProviderInventory([
      { id: 'urn:table:a', dataset_kind: 'TABLE' },
      { id: 'urn:table:b', dataset_kind: 'TABLE' },
    ])

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

test('creates an immutable server-authored System identity with admin, Origin, and idempotency fences', async () => {
  const fixture = await serverFixture()
  try {
    const [admin, viewer] = await Promise.all([
      fixture.login('first@example.com', 'first correct password'),
      fixture.login('second@example.com', 'second correct password'),
    ])
    assert.ok(admin.cookie)
    assert.ok(viewer.cookie)
    const body = JSON.stringify({ name: 'Order Fulfillment', description: 'Current business System' })
    const key = 'system-create-order-fulfillment-1'

    const denied = await fetch(`${fixture.origin}/api/v1/admin/systems`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Cookie: viewer.cookie, Origin: fixture.canonicalOrigin, 'Idempotency-Key': key },
      body,
    })
    assert.equal(denied.status, 403)
    assert.equal((await denied.json()).code, 'CAPABILITY_REQUIRED')

    const missingOrigin = await fetch(`${fixture.origin}/api/v1/admin/systems`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Cookie: admin.cookie, 'Idempotency-Key': key },
      body,
    })
    assert.equal(missingOrigin.status, 403)
    assert.equal((await missingOrigin.json()).code, 'ORIGIN_FORBIDDEN')

    const missingKey = await fetch(`${fixture.origin}/api/v1/admin/systems`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Cookie: admin.cookie, Origin: fixture.canonicalOrigin },
      body,
    })
    assert.equal(missingKey.status, 428)
    assert.equal((await missingKey.json()).code, 'IDEMPOTENCY_KEY_REQUIRED')

    const clientCode = await fetch(`${fixture.origin}/api/v1/admin/systems`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Cookie: admin.cookie, Origin: fixture.canonicalOrigin, 'Idempotency-Key': key },
      body: JSON.stringify({ code: 'CLIENT_CODE', name: 'Order Fulfillment', description: '' }),
    })
    assert.equal(clientCode.status, 400)
    assert.equal((await clientCode.json()).code, 'ADMIN_INPUT_INVALID')

    const create = () => fetch(`${fixture.origin}/api/v1/admin/systems`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Cookie: admin.cookie, Origin: fixture.canonicalOrigin, 'Idempotency-Key': key },
      body,
    })
    const createdResponse = await create()
    const created = await createdResponse.json()
    assert.equal(createdResponse.status, 201, JSON.stringify(created))
    assert.match(created.system_id, /^system-[0-9a-f]{32}$/)
    assert.match(created.code, /^ORDER_FULFILLMENT_[0-9A-F]{12}$/)
    assert.equal(created.name, 'Order Fulfillment')

    const replayResponse = await create()
    assert.equal(replayResponse.status, 200)
    assert.deepEqual(await replayResponse.json(), created)
    const persisted = await fixture.stateStore.readChangeHistoryAccess()
    assert.equal(persisted.core.value.adminSystems.filter((system) => system.system_id === created.system_id).length, 1)

    const conflict = await fetch(`${fixture.origin}/api/v1/admin/systems`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Cookie: admin.cookie, Origin: fixture.canonicalOrigin, 'Idempotency-Key': key },
      body: JSON.stringify({ name: 'Different System', description: '' }),
    })
    assert.equal(conflict.status, 409)
    assert.equal((await conflict.json()).code, 'SYSTEM_IDEMPOTENCY_CONFLICT')
  } finally {
    await fixture.close()
  }
})

test('administers local users, security grade, Responsible Systems, explicit Table grants, credentials, and sessions', async () => {
  const fixture = await serverFixture()
  try {
    const [admin, viewer] = await Promise.all([
      fixture.login('first@example.com', 'first correct password'),
      fixture.login('second@example.com', 'second correct password'),
    ])
    assert.equal(admin.response.status, 200)
    assert.equal(viewer.response.status, 200)

    const denied = await fetch(`${fixture.origin}/api/v1/admin/users`, { headers: { Cookie: viewer.cookie } })
    assert.equal(denied.status, 403)
    assert.equal((await denied.json()).code, 'CAPABILITY_REQUIRED')

    const snapshot = await fixture.stateStore.readChangeHistoryAccess()
    const document = {
      ...snapshot.access.value,
      systems: [{ system_id: 'system-a', code: 'SYSTEM-A', name: 'System A', description: '', active: true, version: 1 }],
      system_schema_scopes: [],
    }
    await fixture.stateStore.writeChangeHistoryAccess({
      expectedAccessVersion: snapshot.access.version,
      expectedCoreVersion: snapshot.core.version,
      accessValue: privateChangeHistoryAccess(document),
      coreValue: changeHistoryAccessCoreProjection(snapshot.core.value, document, snapshot.access.version + 1),
    })

    const list = await fetch(`${fixture.origin}/api/v1/admin/users`, { headers: { Cookie: admin.cookie } })
    assert.equal(list.status, 200)
    const version = Number(list.headers.get('etag')?.replaceAll('"', ''))
    const created = await fetch(`${fixture.origin}/api/v1/admin/users`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Cookie: admin.cookie, Origin: fixture.origin, 'If-Match': `"${version}"` },
      body: JSON.stringify({
        username: 'developer@example.com', password: 'developer first password',
        display_name: 'Developer Person', email: 'developer@example.com', role: 'developer',
        max_security_grade: 'credential', responsible_systems: [{ system_id: 'system-a', priority: 2 }],
        must_change_password: true,
      }),
    })
    assert.equal(created.status, 201, JSON.stringify(await created.clone().json()))
    const createdBody = await created.json()
    assert.match(createdBody.subject_id, /^[0-9a-f-]{36}$/)

    const developerLogin = await fixture.login('developer@example.com', 'developer first password')
    assert.equal(developerLogin.response.status, 200)
    const developerProfile = await developerLogin.response.json()
    assert.equal(developerProfile.subject, createdBody.subject_id)
    assert.equal(developerProfile.max_security_grade, 'credential')
    assert.deepEqual(developerProfile.authorization.system_ids, ['system-a'])

    const spoof = await fetch(`${fixture.origin}/api/v1/admin/users`, {
      headers: { Cookie: developerLogin.cookie, 'X-Subject-Id': 'subject-one' },
    })
    assert.equal(spoof.status, 403)

    const grant = async (subjectId, tableIds, action = 'GRANT') => fetch(
      `${fixture.origin}/api/v1/admin/users/${encodeURIComponent(subjectId)}/table-grants`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', Cookie: admin.cookie, Origin: fixture.origin },
        body: JSON.stringify({ action, table_ids: tableIds }),
      },
    )
    const granted = await grant(createdBody.subject_id, [CURRENT_TABLE_URN])
    assert.equal(granted.status, 200, JSON.stringify(await granted.clone().json()))
    assert.equal((await granted.json()).changed, 1)
    assert.equal((await (await grant(createdBody.subject_id, [CURRENT_TABLE_URN])).json()).changed, 0)
    assert.equal((await (await grant('subject-two', [CURRENT_TABLE_URN])).json()).changed, 1)
    assert.equal((await fixture.stateStore.listUserTableGrants(createdBody.subject_id)).length, 1)
    assert.equal((await fixture.stateStore.listUserTableGrants('subject-two')).length, 1)

    const grantPage = await fetch(
      `${fixture.origin}/api/v1/admin/users/${encodeURIComponent(createdBody.subject_id)}/table-grants?security_grade=restricted`,
      { headers: { Cookie: admin.cookie } },
    )
    assert.equal(grantPage.status, 200)
    assert.deepEqual((await grantPage.json()).items.map((item) => [item.table_identity, item.security_grade, item.granted]), [
      ['urn:table:b', 'restricted', false],
      [CURRENT_TABLE_URN, 'restricted', true],
    ])

    const unknown = await grant(createdBody.subject_id, ['urn:li:dataset:(urn:li:dataPlatform:postgres,missing.table,PROD)'])
    assert.equal(unknown.status, 400)
    assert.equal((await unknown.json()).code, 'USER_TABLE_IDENTITY_INVALID')
    fixture.setCurrentProviderError(new Error('provider unavailable'))
    const unavailable = await grant(createdBody.subject_id, [CURRENT_TABLE_URN], 'REMOVE')
    assert.equal(unavailable.status, 503)
    assert.equal((await unavailable.json()).code, 'USER_TABLE_CURRENT_TABLES_UNAVAILABLE')
    fixture.setCurrentProviderError(undefined)

    const accounts = await (await fetch(`${fixture.origin}/api/v1/admin/users`, { headers: { Cookie: admin.cookie } })).json()
    const createdAccount = accounts.items.find((item) => item.subject_id === createdBody.subject_id)
    assert.equal(createdAccount.max_security_grade, 'credential')
    assert.equal(createdAccount.table_grant_count, 1)
    assert.deepEqual(createdAccount.responsible_systems.map((item) => [item.system_id, item.priority]), [['system-a', 2]])

    const credentialUpdate = await fetch(`${fixture.origin}/api/v1/admin/users/${createdBody.subject_id}/credential`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json', Cookie: admin.cookie, Origin: fixture.origin,
        'If-Match': `"${createdAccount.credential.version}"`,
      },
      body: JSON.stringify({
        username: 'developer@example.com', login_enabled: false, must_change_password: true,
      }),
    })
    assert.equal(credentialUpdate.status, 200)
    assert.equal((await credentialUpdate.json()).revoked_session_count, 1)
    assert.equal((await fetch(`${fixture.origin}/auth/me`, { headers: { Cookie: developerLogin.cookie } })).status, 401)
    assert.equal((await fixture.login('developer@example.com', 'developer first password')).response.status, 401)

    const afterDisable = await (await fetch(`${fixture.origin}/api/v1/admin/users`, { headers: { Cookie: admin.cookie } })).json()
    const disabled = afterDisable.items.find((item) => item.subject_id === createdBody.subject_id)
    const reset = await fetch(`${fixture.origin}/api/v1/admin/users/${createdBody.subject_id}/credential`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json', Cookie: admin.cookie, Origin: fixture.origin,
        'If-Match': `"${disabled.credential.version}"`,
      },
      body: JSON.stringify({
        username: 'developer@example.com', password: 'developer replacement password',
        login_enabled: true, must_change_password: false,
      }),
    })
    assert.equal(reset.status, 200)
    assert.equal((await fixture.login('developer@example.com', 'developer replacement password')).response.status, 200)

    const removed = await grant(createdBody.subject_id, [CURRENT_TABLE_URN], 'REMOVE')
    assert.equal(removed.status, 200)
    assert.equal((await removed.json()).changed, 1)
    assert.equal((await fixture.stateStore.listUserTableGrants(createdBody.subject_id)).length, 0)
  } finally {
    await fixture.close()
  }
})

test('serializes concurrent cross-admin deactivation and preserves one active admin', async () => {
  const fixture = await serverFixture()
  try {
    const first = await fixture.login('first@example.com', 'first correct password')
    assert.equal(first.response.status, 200)
    const initial = await fetch(`${fixture.origin}/api/v1/admin/users`, { headers: { Cookie: first.cookie } })
    const initialVersion = Number(initial.headers.get('etag')?.replaceAll('"', ''))
    const created = await fetch(`${fixture.origin}/api/v1/admin/users`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json', Cookie: first.cookie, Origin: fixture.origin,
        'If-Match': `"${initialVersion}"`,
      },
      body: JSON.stringify({
        username: 'concurrent-admin@example.com', password: 'concurrent admin password',
        display_name: 'Concurrent Admin', email: 'concurrent-admin@example.com', role: 'admin',
        max_security_grade: 'restricted', responsible_systems: [], must_change_password: false,
      }),
    })
    assert.equal(created.status, 201)
    const secondSubject = (await created.json()).subject_id
    const second = await fixture.login('concurrent-admin@example.com', 'concurrent admin password')
    assert.equal(second.response.status, 200)

    const current = await fetch(`${fixture.origin}/api/v1/admin/users`, { headers: { Cookie: first.cookie } })
    const expectedVersion = Number(current.headers.get('etag')?.replaceAll('"', ''))
    const demote = (cookie, subjectId, displayName, email) => fetch(
      `${fixture.origin}/api/v1/admin/users/${encodeURIComponent(subjectId)}`,
      {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json', Cookie: cookie, Origin: fixture.origin,
          'If-Match': `"${expectedVersion}"`,
        },
        body: JSON.stringify({
          display_name: displayName, email, role: 'viewer', active: false,
          max_security_grade: 'normal', responsible_systems: [],
        }),
      },
    )
    const results = await Promise.all([
      demote(first.cookie, secondSubject, 'Concurrent Admin', 'concurrent-admin@example.com'),
      demote(second.cookie, 'subject-one', 'First Person', 'first@example.com'),
    ])
    const statuses = results.map((response) => response.status)
    assert.equal(results.filter((response) => response.status === 200).length, 1, JSON.stringify(statuses))
    assert.equal(results.filter((response) => [401, 403, 409].includes(response.status)).length, 1, JSON.stringify(statuses))

    const snapshot = await fixture.stateStore.readChangeHistoryAccess()
    const activeAdmins = snapshot.access.value.users.filter((user) => user.active && user.role === 'admin')
    assert.equal(activeAdmins.length, 1)
    const remaining = activeAdmins[0].subject_id
    const remainingCookie = remaining === 'subject-one' ? first.cookie : second.cookie
    const selfLockout = await fetch(`${fixture.origin}/api/v1/admin/users/${encodeURIComponent(remaining)}`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json', Cookie: remainingCookie, Origin: fixture.origin,
        'If-Match': `"${snapshot.access.version}"`,
      },
      body: JSON.stringify({
        display_name: remaining === 'subject-one' ? 'First Person' : 'Concurrent Admin',
        email: remaining === 'subject-one' ? 'first@example.com' : 'concurrent-admin@example.com',
        role: 'viewer', active: false, max_security_grade: 'normal', responsible_systems: [],
      }),
    })
    assert.equal(selfLockout.status, 409)
    assert.equal((await selfLockout.json()).code, 'ADMIN_SELF_LOCKOUT_FORBIDDEN')
  } finally {
    await fixture.close()
  }
})

test('serializes concurrent cross-admin role downgrades without relying on inactivity', async () => {
  const fixture = await serverFixture()
  try {
    const first = await fixture.login('first@example.com', 'first correct password')
    const initial = await fetch(`${fixture.origin}/api/v1/admin/users`, { headers: { Cookie: first.cookie } })
    const initialVersion = Number(initial.headers.get('etag')?.replaceAll('"', ''))
    const created = await fetch(`${fixture.origin}/api/v1/admin/users`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json', Cookie: first.cookie, Origin: fixture.origin,
        'If-Match': `"${initialVersion}"`,
      },
      body: JSON.stringify({
        username: 'role-race-admin@example.com', password: 'role race admin password',
        display_name: 'Role Race Admin', email: 'role-race-admin@example.com', role: 'admin',
        max_security_grade: 'restricted', responsible_systems: [], must_change_password: false,
      }),
    })
    assert.equal(created.status, 201)
    const secondSubject = (await created.json()).subject_id
    const second = await fixture.login('role-race-admin@example.com', 'role race admin password')
    assert.equal(second.response.status, 200)

    const current = await fetch(`${fixture.origin}/api/v1/admin/users`, { headers: { Cookie: first.cookie } })
    const expectedVersion = Number(current.headers.get('etag')?.replaceAll('"', ''))
    const downgrade = (cookie, subjectId, displayName, email) => fetch(
      `${fixture.origin}/api/v1/admin/users/${encodeURIComponent(subjectId)}`,
      {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json', Cookie: cookie, Origin: fixture.origin,
          'If-Match': `"${expectedVersion}"`,
        },
        body: JSON.stringify({
          display_name: displayName, email, role: 'viewer', active: true,
          max_security_grade: 'normal', responsible_systems: [],
        }),
      },
    )
    const responses = await Promise.all([
      downgrade(first.cookie, secondSubject, 'Role Race Admin', 'role-race-admin@example.com'),
      downgrade(second.cookie, 'subject-one', 'First Person', 'first@example.com'),
    ])
    assert.equal(responses.filter((response) => response.status === 200).length, 1)
    assert.equal(responses.filter((response) => [403, 409].includes(response.status)).length, 1)
    const snapshot = await fixture.stateStore.readChangeHistoryAccess()
    assert.equal(snapshot.access.value.users.filter((user) => user.active && user.role === 'admin').length, 1)
  } finally {
    await fixture.close()
  }
})

test('keeps credential disable and access inactivity consistent under concurrent administration', async () => {
  const fixture = await serverFixture()
  try {
    const admin = await fixture.login('first@example.com', 'first correct password')
    const initial = await fetch(`${fixture.origin}/api/v1/admin/users`, { headers: { Cookie: admin.cookie } })
    const initialVersion = Number(initial.headers.get('etag')?.replaceAll('"', ''))
    const created = await fetch(`${fixture.origin}/api/v1/admin/users`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json', Cookie: admin.cookie, Origin: fixture.origin,
        'If-Match': `"${initialVersion}"`,
      },
      body: JSON.stringify({
        username: 'disable-race-viewer@example.com', password: 'disable race viewer password',
        display_name: 'Disable Race Viewer', email: 'disable-race-viewer@example.com', role: 'viewer',
        max_security_grade: 'normal', responsible_systems: [], must_change_password: false,
      }),
    })
    assert.equal(created.status, 201)
    const subjectId = (await created.json()).subject_id
    const viewer = await fixture.login('disable-race-viewer@example.com', 'disable race viewer password')
    assert.equal(viewer.response.status, 200)

    const current = await fetch(`${fixture.origin}/api/v1/admin/users`, { headers: { Cookie: admin.cookie } })
    const accessVersion = Number(current.headers.get('etag')?.replaceAll('"', ''))
    const page = await current.json()
    const target = page.items.find((item) => item.subject_id === subjectId)
    assert.ok(target?.credential)
    const [disabled, inactive] = await Promise.all([
      fetch(`${fixture.origin}/api/v1/admin/users/${encodeURIComponent(subjectId)}/credential`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json', Cookie: admin.cookie, Origin: fixture.origin,
          'If-Match': `"${target.credential.version}"`,
        },
        body: JSON.stringify({
          username: target.credential.username, login_enabled: false, must_change_password: false,
        }),
      }),
      fetch(`${fixture.origin}/api/v1/admin/users/${encodeURIComponent(subjectId)}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json', Cookie: admin.cookie, Origin: fixture.origin,
          'If-Match': `"${accessVersion}"`,
        },
        body: JSON.stringify({
          display_name: 'Disable Race Viewer', email: 'disable-race-viewer@example.com', role: 'viewer',
          active: false, max_security_grade: 'normal', responsible_systems: [],
        }),
      }),
    ])
    assert.equal(disabled.status, 200)
    assert.equal(inactive.status, 200)
    assert.equal((await fetch(`${fixture.origin}/auth/me`, { headers: { Cookie: viewer.cookie } })).status, 401)
    assert.equal((await fixture.login('disable-race-viewer@example.com', 'disable race viewer password')).response.status, 401)
    const after = await (await fetch(`${fixture.origin}/api/v1/admin/users`, { headers: { Cookie: admin.cookie } })).json()
    const stored = after.items.find((item) => item.subject_id === subjectId)
    assert.equal(stored.active, false)
    assert.equal(stored.credential.login_enabled, false)
  } finally {
    await fixture.close()
  }
})

test('manages only the complete fixed feature-role-grade policy through admin CAS', async () => {
  const fixture = await serverFixture()
  try {
    const [admin, viewer] = await Promise.all([
      fixture.login('first@example.com', 'first correct password'),
      fixture.login('second@example.com', 'second correct password'),
    ])
    assert.equal(admin.response.status, 200)
    assert.equal(viewer.response.status, 200)
    assert.equal((await fetch(`${fixture.origin}/api/v1/admin/feature-security-policy`)).status, 401)
    assert.equal((await fetch(`${fixture.origin}/api/v1/admin/feature-security-policy`, {
      headers: { Cookie: viewer.cookie },
    })).status, 403)

    const initial = await fetch(`${fixture.origin}/api/v1/admin/feature-security-policy`, {
      headers: { Cookie: admin.cookie },
    })
    assert.equal(initial.status, 200)
    assert.equal(initial.headers.get('etag'), '"0"')
    const defaultPolicy = await initial.json()
    assert.equal(defaultPolicy.cells.length, 120)
    assert.ok(defaultPolicy.cells.filter((cell) => cell.role === 'admin').every((cell) => cell.allow))

    const cells = defaultPolicy.cells.map((cell) => (
      cell.feature === 'catalog' && cell.role === 'viewer' && cell.grade === 'credential'
        ? { ...cell, allow: true }
        : cell
    ))
    const invalid = await fetch(`${fixture.origin}/api/v1/admin/feature-security-policy`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json', Cookie: admin.cookie, Origin: fixture.origin, 'If-Match': '"0"',
      },
      body: JSON.stringify({ cells: cells.slice(1), reason: 'reject an incomplete fixed policy' }),
    })
    assert.equal(invalid.status, 400)
    assert.equal((await invalid.json()).code, 'FEATURE_SECURITY_POLICY_INVALID')

    const saved = await fetch(`${fixture.origin}/api/v1/admin/feature-security-policy`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json', Cookie: admin.cookie, Origin: fixture.origin, 'If-Match': '"0"',
      },
      body: JSON.stringify({ cells, reason: 'permit reviewed credential Catalog metadata' }),
    })
    assert.equal(saved.status, 200, JSON.stringify(await saved.clone().json()))
    const savedPolicy = await saved.json()
    assert.equal(savedPolicy.version, 1)
    assert.equal(savedPolicy.updated_by, 'subject-one')
    assert.equal(savedPolicy.cells.find((cell) => (
      cell.feature === 'catalog' && cell.role === 'viewer' && cell.grade === 'credential'
    )).allow, true)

    const stale = await fetch(`${fixture.origin}/api/v1/admin/feature-security-policy`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json', Cookie: admin.cookie, Origin: fixture.origin, 'If-Match': '"0"',
      },
      body: JSON.stringify({ cells, reason: 'reject a stale complete policy update' }),
    })
    assert.equal(stale.status, 409)
    assert.equal((await stale.json()).code, 'FEATURE_SECURITY_POLICY_VERSION_STALE')
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
    const canonicalPort = new URL(fixture.origin).port
    const wrongHostShell = await getWithHost(`${fixture.origin}/?page=admin`, `localhost:${canonicalPort}`)
    assert.equal(wrongHostShell.statusCode, 307)
    assert.equal(wrongHostShell.headers.location, `${fixture.origin}/?page=admin`)
    assert.equal(wrongHostShell.headers['cache-control'], 'no-store')
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
