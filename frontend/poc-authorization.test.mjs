import assert from 'node:assert/strict'
import test from 'node:test'

import {
  POC_CAPABILITIES,
  POC_ROUTE_REGISTRY,
  assertAssetMutation,
  assertPocRouteAuthorization,
  authorizationProjection,
  authorizeCoreReplacement,
  buildPocPrincipal,
  filterAssetsForPrincipal,
  filterCoreStateForPrincipal,
  resolvePocRoute,
} from './poc-authorization.mjs'
import {
  changeHistoryAccessCoreProjection,
  normalizeChangeHistoryAccessDocument,
} from './poc-access-document.mjs'

const accessDocument = {
  systems: [
    { system_id: 'system-a', active: true },
    { system_id: 'system-b', active: true },
  ],
  system_schema_scopes: [
    { system_id: 'system-a', platform: 'postgres', database_name: 'db', schema_name: 'a', active: true },
    { system_id: 'system-b', platform: 'postgres', database_name: 'db', schema_name: 'b', active: true },
  ],
  system_assignments: [
    { subject_id: 'developer', system_id: 'system-a', responsibility: 'DEVELOPER', active: true },
    { subject_id: 'steward', system_id: 'system-b', responsibility: 'DATA_STEWARD', active: true },
    { subject_id: 'manager', system_id: 'system-a', responsibility: 'DEVELOPER', active: true },
    { subject_id: 'manager', system_id: 'system-b', responsibility: 'DATA_STEWARD', active: true },
  ],
}

function principal(subjectId, role) {
  return buildPocPrincipal({
    authentication: { subjectId },
    accessDocument,
    accessUser: { subject_id: subjectId, role, active: true },
  })
}

test('keeps one bounded server-owned capability matrix with ADR-0107 manager inheritance', () => {
  assert.equal(POC_CAPABILITIES.length, 15)
  assert.equal(new Set(POC_CAPABILITIES).size, POC_CAPABILITIES.length)
  assert.deepEqual(principal('viewer', 'viewer').capabilities, [
    'catalog.read', 'chat.query', 'change.read', 'monitoring.read', 'knowledge.read', 'quality.read',
  ])
  assert.ok(principal('developer', 'developer').capabilitySet.has('change.execute'))
  assert.ok(!principal('developer', 'developer').capabilitySet.has('change.manage'))
  assert.ok(principal('steward', 'data_steward').capabilitySet.has('catalog.manage'))
  const manager = principal('manager', 'manager')
  assert.ok(manager.capabilitySet.has('catalog.manage'))
  assert.ok(manager.capabilitySet.has('knowledge.manage'))
  assert.ok(manager.capabilitySet.has('knowledge.review'))
  assert.ok(!manager.capabilitySet.has('admin.manage'))
  assert.deepEqual(authorizationProjection(manager), {
    policy_version: 'POC_PROFILE_CAPABILITIES_V1',
    role: 'manager',
    capabilities: manager.capabilities,
    system_scope: 'ASSIGNED',
    system_ids: ['system-a', 'system-b'],
  })
  assert.deepEqual(principal('admin', 'admin').capabilities, POC_CAPABILITIES)
})

test('accepts manager in the existing access document and projects MANAGER without a role table', () => {
  const document = normalizeChangeHistoryAccessDocument({
    schema_version: 1,
    active_subject_id: 'manager',
    users: [{ subject_id: 'manager', role: 'manager', active: true }],
    systems: [],
    system_schema_scopes: [],
    system_assignments: [],
  })
  const projected = changeHistoryAccessCoreProjection({}, document, 3)
  assert.equal(projected.adminMemberships[0].effective_profile_role, 'MANAGER')
  assert.equal(projected.adminMemberships[0].membership_version, 3)
})

test('covers every named Node API route with no unknown or ambiguous registry entry', () => {
  assert.equal(POC_ROUTE_REGISTRY.length, 63)
  assert.equal(new Set(POC_ROUTE_REGISTRY.map((entry) => entry.id)).size, POC_ROUTE_REGISTRY.length)
  assert.deepEqual(Object.fromEntries(['ANONYMOUS', 'AUTHENTICATED', 'CAPABILITY_PROTECTED', 'INTERNAL_SERVICE', 'DISABLED'].map((classification) => [
    classification,
    POC_ROUTE_REGISTRY.filter((entry) => entry.authorizationClass === classification).length,
  ])), {
    ANONYMOUS: 7,
    AUTHENTICATED: 2,
    CAPABILITY_PROTECTED: 52,
    INTERNAL_SERVICE: 1,
    DISABLED: 1,
  })
  const cases = [
    ['GET', '/healthz', 'health.liveness.get'],
    ['HEAD', '/poc-runtime-config.js', 'runtime.config.head'],
    ['GET', '/auth/login', 'auth.login.shell.get'],
    ['GET', '/auth/me', 'auth.me'],
    ['GET', '/api/v1/change-history/events', 'change.events'],
    ['GET', '/api/v1/admin/table-system-mappings', 'admin.table-system-mappings.read'],
    ['PATCH', '/api/v1/admin/table-system-mappings', 'admin.table-system-mappings.write'],
    ['GET', '/api/v1/admin/users', 'admin.users.read'],
    ['PATCH', '/api/v1/admin/users/subject/table-grants', 'admin.user-table-grants.write'],
    ['GET', '/api/v1/admin/feature-security-policy', 'admin.feature-security-policy.read'],
    ['PUT', '/api/v1/admin/feature-security-policy', 'admin.feature-security-policy.write'],
    ['POST', `/api/v1/change-history/events/${'a'.repeat(64)}/cr-link-events`, 'change.event.command'],
    ['POST', '/api/v1/registration/bulk-preparations/execute', 'registration.execute.service'],
    ['PUT', '/poc-api/state/core', 'state.write'],
    ['GET', '/poc-api/datahub/asset', 'catalog.asset'],
    ['POST', '/poc-api/llm/chat/stream', 'chat.stream'],
    ['PUT', '/poc-api/minio/uploads/upload-1/parts/1', 'provider.minio.part'],
  ]
  for (const [method, path, expected] of cases) assert.equal(resolvePocRoute(method, path)?.id, expected)
  assert.equal(resolvePocRoute('GET', '/poc-api/not-a-route'), null)
  assert.throws(() => assertPocRouteAuthorization(null, principal('admin', 'admin')), { code: 'NOT_FOUND' })
})

test('enforces capability and current System scope without accepting client authority', () => {
  const developer = principal('developer', 'developer')
  assert.doesNotThrow(() => assertPocRouteAuthorization(resolvePocRoute('GET', '/poc-api/datahub/catalog'), developer))
  assert.throws(
    () => assertPocRouteAuthorization(resolvePocRoute('POST', '/poc-api/datahub/manual-metadata'), developer),
    { code: 'CAPABILITY_REQUIRED' },
  )
  const assets = [
    { id: 'a', platform: 'postgres', database_name: 'db', schema_name: 'a' },
    { id: 'b', platform: 'postgres', database_name: 'db', schema_name: 'b' },
    { id: 'unknown', platform: 'postgres', database_name: 'db', schema_name: 'unknown' },
  ]
  assert.deepEqual(filterAssetsForPrincipal(developer, assets).map((item) => item.id), ['a'])
  assert.doesNotThrow(() => assertAssetMutation(developer, assets[0]))
  assert.throws(() => assertAssetMutation(developer, assets[1]), { code: 'SYSTEM_SCOPE_FORBIDDEN' })
  assert.throws(() => assertAssetMutation(developer, assets[2]), { code: 'SYSTEM_SCOPE_UNRESOLVED' })
  assert.deepEqual(filterAssetsForPrincipal(principal('viewer', 'viewer'), assets), assets)
})

test('filters non-admin core access data and authorizes an exact bounded top-level CAS diff', () => {
  const developer = principal('developer', 'developer')
  const current = {
    sequence: 1,
    changeRecords: [
      { id: 'a', selected_system_id: 'system-a' },
      { id: 'b', selected_system_id: 'system-b' },
    ],
    changeAttachments: [['a', [{ id: 'attachment-a' }]], ['b', [{ id: 'attachment-b' }]]],
    changeAttachmentLocations: [['a', { key: 'a' }], ['b', { key: 'b' }]],
    adminMemberships: [{ subject_id: 'developer' }, { subject_id: 'admin' }],
    adminSystems: [{ system_id: 'system-a' }, { system_id: 'system-b' }],
    adminSystemAssignees: [['system-a', [{ subject_id: 'developer' }]], ['system-b', [{ subject_id: 'admin' }]]],
    adminSystemSchemaScopes: [['system-a', [{}]], ['system-b', [{}]]],
  }
  const filtered = filterCoreStateForPrincipal(developer, current)
  assert.deepEqual(filtered.changeRecords.map((item) => item.id), ['a'])
  assert.deepEqual(filtered.changeAttachments.map((entry) => entry[0]), ['a'])
  assert.deepEqual(filtered.adminMemberships, [{ subject_id: 'developer' }])
  assert.deepEqual(filtered.adminSystems, [{ system_id: 'system-a' }])
  const proposed = { ...filtered, sequence: 2, changeRecords: [{ id: 'a', selected_system_id: 'system-a', state: 'TESTING' }] }
  const authorized = authorizeCoreReplacement(developer, current, proposed)
  assert.deepEqual(authorized.changedKeys, ['changeRecords', 'sequence'])
  assert.deepEqual(authorized.value.changeRecords.map((item) => item.id), ['a', 'b'])
  assert.deepEqual(authorized.value.changeAttachments.map((entry) => entry[0]), ['a', 'b'])
  assert.throws(
    () => authorizeCoreReplacement(developer, current, { ...proposed, changeRecords: [{ id: 'b', selected_system_id: 'system-b', state: 'TESTING' }] }),
    { code: 'SYSTEM_SCOPE_UNRESOLVED' },
  )
  assert.throws(
    () => authorizeCoreReplacement(developer, current, { ...proposed, changeRecords: [{ id: 'a', selected_system_id: 'system-b' }] }),
    { code: 'SYSTEM_SCOPE_SPOOFED' },
  )
  assert.throws(
    () => authorizeCoreReplacement(developer, current, { ...proposed, changeRecords: [{ id: 'new', selected_system_id: 'system-a' }] }),
    { code: 'SYSTEM_SCOPE_UNRESOLVED' },
  )
  assert.throws(
    () => authorizeCoreReplacement(developer, current, { ...proposed, changeAttachments: [['b', []]] }),
    { code: 'SYSTEM_SCOPE_UNRESOLVED' },
  )
  assert.throws(
    () => authorizeCoreReplacement(principal('viewer', 'viewer'), current, proposed),
    { code: 'CAPABILITY_REQUIRED' },
  )
  assert.throws(
    () => authorizeCoreReplacement(principal('admin', 'admin'), current, { ...current, unknown: true }),
    { code: 'CORE_DIFF_INVALID' },
  )
})
