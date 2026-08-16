/* global Buffer, structuredClone */
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  changeHistoryAccessCoreProjection,
  changeHistoryDocumentFromSnapshot,
  normalizeChangeHistoryAccessDocument,
  privateChangeHistoryAccess,
} from './poc-access-document.mjs'
import {
  bootstrapLocalHumanAccount,
  parseLocalHumanBootstrapArguments,
  runLocalHumanBootstrapCli,
} from './poc-bootstrap-local-user.mjs'
import { createPocStateStore } from './poc-state-store.mjs'

const SYSTEM = {
  system_id: 'system-one', code: 'SYSTEM_ONE', name: 'System One', description: 'Fixture System',
  active: true, version: 3,
}
const SCOPE = {
  scope_id: 'scope-one', system_id: SYSTEM.system_id, platform: 'postgres',
  database_name: 'fixture_db', schema_name: 'fixture_schema', active: true, version: 4,
}

async function configuredAccessFixture(store) {
  const originalCore = {
    fixtureMarker: { preserve: true },
    changeRecords: [{ id: 'fixture-change', state: 'IN_REVIEW' }],
    adminMemberships: [{
      subject_id: 'existing-admin', display_name: 'Existing Admin', custom_fixture: 'keep-me',
    }],
    adminSystems: [SYSTEM],
    adminSystemAssignees: [[SYSTEM.system_id, []]],
    adminSystemSchemaScopes: [[SYSTEM.system_id, [SCOPE]]],
  }
  assert.equal(await store.write('core', originalCore), 1)
  const document = normalizeChangeHistoryAccessDocument({
    schema_version: 1,
    active_subject_id: 'existing-admin',
    users: [{
      subject_id: 'existing-admin', role: 'admin', active: true,
      provider_owner_refs: ['urn:li:corpuser:existing-admin'], display_name: 'Existing Admin',
    }],
    systems: [SYSTEM],
    system_schema_scopes: [SCOPE],
    system_assignments: [],
  })
  assert.deepEqual(await store.writeChangeHistoryAccess({
    expectedAccessVersion: 0,
    expectedCoreVersion: 1,
    accessValue: privateChangeHistoryAccess(document),
    coreValue: changeHistoryAccessCoreProjection(originalCore, document, 1),
  }), { accessVersion: 1, coreVersion: 2 })
  return document
}

test('additively creates viewer authority and credential while preserving the access/core fixture', async () => {
  const store = createPocStateStore()
  const before = await configuredAccessFixture(store)
  const result = await bootstrapLocalHumanAccount({
    stateStore: store,
    subjectId: 'viewer-subject',
    username: 'Viewer.Person@example.com',
    role: 'viewer',
    password: 'viewer correct password',
    assignments: [{ systemId: SYSTEM.system_id, responsibility: 'DATA_STEWARD', priority: 2 }],
  })
  assert.equal(result.activeSubjectId, 'existing-admin')
  assert.equal(result.assignmentCount, 1)
  const snapshot = await store.readChangeHistoryAccess()
  const document = changeHistoryDocumentFromSnapshot(snapshot)
  assert.equal(document.active_subject_id, before.active_subject_id)
  assert.deepEqual(document.users.find((user) => user.subject_id === 'existing-admin'), before.users[0])
  assert.deepEqual(document.users.find((user) => user.subject_id === 'viewer-subject'), {
    subject_id: 'viewer-subject', username: 'viewer.person@example.com', role: 'viewer',
    active: true, provider_owner_refs: [],
  })
  assert.deepEqual(document.system_assignments, [{
    system_id: SYSTEM.system_id, subject_id: 'viewer-subject',
    responsibility: 'DATA_STEWARD', priority: 2, active: true,
  }])
  assert.deepEqual(snapshot.core.value.fixtureMarker, { preserve: true })
  assert.deepEqual(snapshot.core.value.changeRecords, [{ id: 'fixture-change', state: 'IN_REVIEW' }])
  assert.equal(snapshot.core.value.adminMemberships.find(
    (membership) => membership.subject_id === 'existing-admin',
  ).custom_fixture, 'keep-me')
  assert.equal(snapshot.core.value.adminMemberships.find(
    (membership) => membership.subject_id === 'viewer-subject',
  ).effective_profile_role, 'VIEWER')
  const credential = await store.readLocalCredential('viewer.person@example.com')
  assert.equal(credential.subjectId, 'viewer-subject')
  assert.equal(credential.loginEnabled, true)
  assert.equal(credential.mustChangePassword, false)
})

test('creates the initial canonical admin structure and selects it only because no active subject exists', async () => {
  const store = createPocStateStore()
  await store.write('core', { fixtureMarker: 'initial-core' })
  const result = await bootstrapLocalHumanAccount({
    stateStore: store,
    subjectId: 'stable-admin-subject',
    username: 'admin@example.com',
    role: 'admin',
    password: 'admin correct password',
    mustChangePassword: true,
  })
  assert.equal(result.activeSubjectId, 'stable-admin-subject')
  const snapshot = await store.readChangeHistoryAccess()
  const document = changeHistoryDocumentFromSnapshot(snapshot)
  assert.deepEqual(document.users, [{
    subject_id: 'stable-admin-subject', username: 'admin@example.com', role: 'admin',
    active: true, provider_owner_refs: [],
  }])
  assert.equal(snapshot.core.value.fixtureMarker, 'initial-core')
  assert.equal(snapshot.core.value.adminMemberships[0].effective_profile_role, 'ADMIN')
  assert.equal((await store.readLocalCredential('admin@example.com')).mustChangePassword, true)
})

test('duplicate username leaves the access and core fixture unchanged', async () => {
  const store = createPocStateStore()
  await configuredAccessFixture(store)
  await bootstrapLocalHumanAccount({
    stateStore: store,
    subjectId: 'first-new-subject',
    username: 'duplicate@example.com',
    role: 'viewer',
    password: 'first correct password',
  })
  const beforeDuplicate = structuredClone(await store.readChangeHistoryAccess())
  await assert.rejects(bootstrapLocalHumanAccount({
    stateStore: store,
    subjectId: 'second-new-subject',
    username: 'duplicate@example.com',
    role: 'admin',
    password: 'second correct password',
  }), (error) => error.code === 'CREDENTIAL_EXISTS')
  assert.deepEqual(await store.readChangeHistoryAccess(), beforeDuplicate)
})

test('passes the read versions to provisionLocalCredential and surfaces stale CAS without retry', async () => {
  const snapshot = {
    access: { value: null, version: 4 },
    core: { value: { fixtureMarker: 'stale-double' }, version: 9 },
  }
  let provisionCalls = 0
  const stateStore = {
    async readChangeHistoryAccess() { return structuredClone(snapshot) },
    async readLocalCredential() { return null },
    async provisionLocalCredential(input) {
      provisionCalls += 1
      assert.equal(input.expectedAccessVersion, 4)
      assert.equal(input.expectedCoreVersion, 9)
      assert.equal(input.coreValue.fixtureMarker, 'stale-double')
      throw Object.assign(new Error('The change-history access state changed; read it and retry.'), {
        code: 'ACCESS_VERSION_STALE', statusCode: 409,
      })
    },
  }
  await assert.rejects(bootstrapLocalHumanAccount({
    stateStore,
    subjectId: 'stale-subject',
    username: 'stale@example.com',
    role: 'admin',
    password: 'stale correct password',
  }), (error) => error.code === 'ACCESS_VERSION_STALE')
  assert.equal(provisionCalls, 1)
})

test('CLI success output never contains the plaintext password', async () => {
  const store = createPocStateStore()
  const plaintext = 'never print this password'
  let stdout = ''
  let stderr = ''
  const result = await runLocalHumanBootstrapCli([
    '--subject-id', 'output-safe-subject',
    '--username', 'output.safe@example.com',
    '--role', 'viewer',
    '--password-file', '/operator/secret/password',
  ], {
    stateStore: store,
    passwordFileReader: async () => plaintext,
    output: { write(value) { stdout += value } },
    errorOutput: { write(value) { stderr += value } },
  })
  assert.equal(result.subjectId, 'output-safe-subject')
  assert.equal(stdout.includes(plaintext), false)
  assert.equal(stderr.includes(plaintext), false)
  const credential = await store.readLocalCredential('output.safe@example.com')
  assert.notEqual(credential.passwordHash, plaintext)
  assert.equal(Buffer.from(stdout).includes(Buffer.from(plaintext)), false)
})

test('CLI accepts no plaintext password argument surface', () => {
  const plaintext = 'forbidden-argument-password'
  for (const argv of [
    ['--password', plaintext],
    [`--password=${plaintext}`],
  ]) {
    assert.throws(() => parseLocalHumanBootstrapArguments(argv), (error) => {
      assert.equal(error.message.includes(plaintext), false)
      return true
    })
  }
})

test('CLI must-change-password flag defaults false and is explicit-only', () => {
  const base = [
    '--subject-id', 'flag-subject', '--username', 'flag@example.com', '--role', 'viewer',
  ]
  assert.equal(parseLocalHumanBootstrapArguments(base).mustChangePassword, false)
  assert.equal(parseLocalHumanBootstrapArguments([...base, '--must-change-password']).mustChangePassword, true)
  assert.throws(() => parseLocalHumanBootstrapArguments([
    ...base, '--must-change-password', '--must-change-password',
  ]), /may be supplied only once/)
})

test('CLI uses configured process environment when --env-file is omitted', async () => {
  const store = createPocStateStore()
  store.configured.postgres = true
  let environmentLoads = 0
  let stdout = ''
  await runLocalHumanBootstrapCli([
    '--subject-id', 'environment-subject',
    '--username', 'environment@example.com',
    '--role', 'admin',
    '--password-file', '/operator/secret/password',
  ], {
    loadEnvironmentFile() { environmentLoads += 1 },
    passwordFileReader: async () => 'environment correct password',
    stateStoreFactory: () => store,
    output: { write(value) { stdout += value } },
  })
  assert.equal(environmentLoads, 0)
  assert.match(stdout, /"status":"created"/)
})
