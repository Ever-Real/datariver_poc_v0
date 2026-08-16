import assert from 'node:assert/strict'
import test from 'node:test'

import {
  disableLocalCredential,
  parseCredentialDisableArguments,
} from './poc-disable-local-credential.mjs'
import { createPocStateStore } from './poc-state-store.mjs'

test('requires explicit operator confirmation and a version guard without accepting secrets', () => {
  assert.throws(() => parseCredentialDisableArguments([
    '--env-file', './test.env', '--username', 'person@example.com', '--expected-version', '1',
  ]), { code: 'CREDENTIAL_DISABLE_INPUT_INVALID' })
  assert.throws(() => parseCredentialDisableArguments([
    '--env-file', './test.env', '--username', 'person@example.com', '--expected-version', '1',
    '--confirm', 'yes', '--password', 'forbidden',
  ]), { code: 'CREDENTIAL_DISABLE_INPUT_INVALID' })
  const parsed = parseCredentialDisableArguments([
    '--env-file', './test.env', '--username', 'Person@Example.com', '--expected-version', '7',
    '--confirm', 'DISABLE_LOCAL_CREDENTIAL_AND_REVOKE_SESSIONS',
  ])
  assert.equal(parsed.username, 'person@example.com')
  assert.equal(parsed.expectedVersion, 7)
})

test('version-guards disable and revokes every active local session atomically', async () => {
  const store = createPocStateStore()
  await store.insertLocalCredential({
    expectedAccessVersion: 0,
    expectedCoreVersion: 0,
    subjectId: 'subject-one',
    usernameNormalized: 'person@example.com',
    passwordHash: '$argon2id$v=19$fixture',
    loginEnabled: true,
    mustChangePassword: false,
  })
  await store.createLocalSession({
    tokenHash: 'a'.repeat(64),
    subjectId: 'subject-one',
    createdAt: '2026-08-16T00:00:00.000Z',
    expiresAt: '2026-08-17T00:00:00.000Z',
  })
  const result = await disableLocalCredential({
    stateStore: store,
    username: 'person@example.com',
    expectedVersion: 1,
    now: () => new Date('2026-08-16T01:00:00.000Z'),
    allowInMemoryStoreForTests: true,
  })
  assert.deepEqual(result, {
    subject_id: 'subject-one',
    credential_version: 2,
    login_enabled: false,
    revoked_session_count: 1,
    disabled_at: '2026-08-16T01:00:00.000Z',
  })
  assert.equal((await store.readLocalCredential('person@example.com')).loginEnabled, false)
  assert.equal((await store.readLocalSession('a'.repeat(64))).revokedAt, '2026-08-16T01:00:00.000Z')
  await assert.rejects(
    () => store.disableLocalCredential({
      usernameNormalized: 'person@example.com', expectedVersion: 1,
      disabledAt: '2026-08-16T02:00:00.000Z',
    }),
    { code: 'CREDENTIAL_VERSION_STALE' },
  )
})
