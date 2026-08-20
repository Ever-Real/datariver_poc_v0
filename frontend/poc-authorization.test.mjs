/* global structuredClone */

import assert from 'node:assert/strict'
import test from 'node:test'

import {
  POC_CAPABILITIES,
  POC_ROUTE_REGISTRY,
  assertAssetMutation,
  assertRegistrationAssetMutation,
  assertPocRouteAuthorization,
  authorizationProjection,
  authorizeCoreReplacement,
  buildPocPrincipal,
  canReadRegistrationAsset,
  filterAssetsForPrincipal,
  filterCoreStateForPrincipal,
  resolvePocRoute,
} from './poc-authorization.mjs'
import {
  changeHistoryAccessCoreProjection,
  normalizeChangeHistoryAccessDocument,
} from './poc-access-document.mjs'
import { approvedDefaultFeatureSecurityPolicy } from './poc-feature-security-policy.mjs'

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

function principal(subjectId, role, { grants = [], maxSecurityGrade = 'normal', policy = approvedDefaultFeatureSecurityPolicy() } = {}) {
  return buildPocPrincipal({
    authentication: { subjectId },
    accessDocument,
    accessUser: { subject_id: subjectId, role, active: true, max_security_grade: maxSecurityGrade },
    userTableGrants: grants.map((tableUrn) => ({ tableUrn, active: true })),
    featureSecurityPolicy: policy,
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
  const steward = principal('steward', 'data_steward')
  assert.ok(steward.capabilitySet.has('catalog.manage'))
  assert.ok(steward.capabilitySet.has('change.manage'))
  assert.ok(!steward.capabilitySet.has('knowledge.manage'))
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
  assert.equal(POC_ROUTE_REGISTRY.length, 76)
  assert.equal(new Set(POC_ROUTE_REGISTRY.map((entry) => entry.id)).size, POC_ROUTE_REGISTRY.length)
  assert.deepEqual(Object.fromEntries(['ANONYMOUS', 'AUTHENTICATED', 'CAPABILITY_PROTECTED', 'INTERNAL_SERVICE', 'DISABLED'].map((classification) => [
    classification,
    POC_ROUTE_REGISTRY.filter((entry) => entry.authorizationClass === classification).length,
  ])), {
    ANONYMOUS: 7,
    AUTHENTICATED: 2,
    CAPABILITY_PROTECTED: 65,
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
    ['GET', '/poc-api/knowledge/catalog', 'knowledge.catalog.search'],
    ['GET', '/poc-api/knowledge/catalog/asset', 'knowledge.catalog.detail'],
    ['GET', '/poc-api/knowledge/graphs', 'knowledge.chat.graphs'],
    ['GET', '/poc-api/knowledge/graphs/graph-1/releases', 'knowledge.chat.releases'],
    ['GET', '/poc-api/knowledge/graphs/graph-1/releases/release-1/snapshot', 'knowledge.chat.snapshot'],
    ['POST', '/poc-api/knowledge/graphs/graph-1/releases/release-1/graphrag', 'knowledge.chat.graphrag'],
    ['PATCH', '/api/v1/admin/users/subject/table-grants', 'admin.user-table-grants.write'],
    ['GET', '/api/v1/admin/feature-security-policy', 'admin.feature-security-policy.read'],
    ['PUT', '/api/v1/admin/feature-security-policy', 'admin.feature-security-policy.write'],
    ['POST', `/api/v1/change-history/events/${'a'.repeat(64)}/cr-link-events`, 'change.event.command'],
    ['GET', '/poc-api/change-requests/abc/apply-report', 'change.cr.apply-report'],
    ['POST', '/poc-api/bulk/uploads/abc/preparations/def/metadata-candidates/ghi/change-request', 'catalog.bulk.candidate-cr'],
    ['POST', '/api/v1/registration/bulk-preparations/execute', 'registration.execute.service'],
    ['POST', '/poc-api/knowledge/projections', 'knowledge.projections.create'],
    ['GET', '/poc-api/knowledge/projections', 'knowledge.projections.list'],
    ['POST', '/poc-api/knowledge/studio/drafts/draft-1/abox/previews', 'knowledge.abox.preview'],
    ['POST', '/poc-api/knowledge/studio/drafts/draft-1/abox/ingestions', 'knowledge.abox.ingestion.create'],
    ['GET', '/poc-api/knowledge/studio/drafts/draft-1/abox/ingestions', 'knowledge.abox.ingestion.list'],

    ['PUT', '/poc-api/state/core', 'state.write'],
    ['GET', '/poc-api/datahub/asset', 'catalog.asset'],
    ['POST', '/poc-api/llm/chat/stream', 'chat.stream'],
    ['PUT', '/poc-api/minio/uploads/upload-1/parts/1', 'provider.minio.part'],
  ]
  for (const [method, path, expected] of cases) assert.equal(resolvePocRoute(method, path)?.id, expected)
  assert.equal(resolvePocRoute('GET', '/poc-api/not-a-route'), null)
  assert.throws(() => assertPocRouteAuthorization(null, principal('admin', 'admin')), { code: 'NOT_FOUND' })
})

test('enforces capability plus current Table grant, grade and policy without using Responsible System for general reads', () => {
  const tableA = 'urn:li:dataset:(urn:li:dataPlatform:postgres,db.a.table_a,PROD)'
  const tableB = 'urn:li:dataset:(urn:li:dataPlatform:postgres,db.b.table_b,PROD)'
  const unknown = 'urn:li:dataset:(urn:li:dataPlatform:postgres,db.unknown.table_c,PROD)'
  const developer = principal('developer', 'developer', { grants: [tableB] })
  assert.doesNotThrow(() => assertPocRouteAuthorization(resolvePocRoute('GET', '/poc-api/datahub/catalog'), developer))
  assert.throws(
    () => assertPocRouteAuthorization(resolvePocRoute('POST', '/poc-api/datahub/manual-metadata'), developer),
    { code: 'CAPABILITY_REQUIRED' },
  )
  const assets = [
    { id: tableA, dataset_kind: 'TABLE', security_grade: 'normal', platform: 'postgres', database_name: 'db', schema_name: 'a' },
    { id: tableB, dataset_kind: 'TABLE', security_grade: 'normal', platform: 'postgres', database_name: 'db', schema_name: 'b' },
    { id: unknown, dataset_kind: 'TABLE', security_grade: 'normal', platform: 'postgres', database_name: 'db', schema_name: 'unknown' },
  ]
  assert.deepEqual(filterAssetsForPrincipal(developer, assets).map((item) => item.id), [tableB])
  assert.doesNotThrow(() => assertAssetMutation(developer, assets[1]))
  assert.throws(() => assertAssetMutation(developer, assets[0]), { code: 'TABLE_DATA_FORBIDDEN' })
  assert.throws(() => assertAssetMutation(developer, assets[2]), { code: 'TABLE_DATA_FORBIDDEN' })
  assert.deepEqual(
    filterAssetsForPrincipal(principal('viewer', 'viewer', { grants: [tableA] }), assets).map((item) => item.id),
    [tableA],
  )
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
    bulkRegistrationCandidateBindings: [{ idempotency_key_hash: 'a'.repeat(64) }],
  }
  const filtered = filterCoreStateForPrincipal(developer, current)
  assert.equal(Object.hasOwn(filtered, 'bulkRegistrationCandidateBindings'), false)
  assert.equal(Object.hasOwn(filterCoreStateForPrincipal(principal('admin', 'admin'), current), 'bulkRegistrationCandidateBindings'), false)
  assert.deepEqual(filtered.changeRecords.map((item) => item.id), ['a'])
  assert.deepEqual(filtered.changeAttachments.map((entry) => entry[0]), ['a'])
  assert.deepEqual(filtered.adminMemberships, [{ subject_id: 'developer' }])
  assert.deepEqual(filtered.adminSystems, [{ system_id: 'system-a' }])
  const proposed = { ...filtered, sequence: 2, changeRecords: [{ id: 'a', selected_system_id: 'system-a', state: 'TESTING' }] }
  const authorized = authorizeCoreReplacement(developer, current, proposed)
  assert.deepEqual(authorized.changedKeys, ['changeRecords', 'sequence'])
  assert.deepEqual(authorized.value.changeRecords.map((item) => item.id), ['a', 'b'])
  assert.deepEqual(authorized.value.changeAttachments.map((entry) => entry[0]), ['a', 'b'])
  assert.deepEqual(authorized.value.bulkRegistrationCandidateBindings, current.bulkRegistrationCandidateBindings)
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
  const admin = principal('admin', 'admin')
  const knowledgeProposalState = authorizeCoreReplacement(admin, current, {
    ...filterCoreStateForPrincipal(admin, current),
    knowledgeProposalJobs: [{ id: 'job-1', state: 'SUCCEEDED' }],
    knowledgeTBoxProposals: [{ id: 'proposal-1', state: 'READY' }],
  })
  assert.deepEqual(knowledgeProposalState.changedKeys, ['knowledgeProposalJobs', 'knowledgeTBoxProposals'])
  assert.throws(
    () => authorizeCoreReplacement(principal('viewer', 'viewer'), current, {
      ...filterCoreStateForPrincipal(principal('viewer', 'viewer'), current),
      knowledgeProposalJobs: [{ id: 'job-1' }],
      knowledgeTBoxProposals: [],
    }),
    { code: 'CAPABILITY_REQUIRED' },
  )
})

test('enforces Registration-only asset mutation seam', () => {
  const tableUrn = 'urn:li:dataset:(urn:li:dataPlatform:postgres,db.a.table_test,PROD)'
  const validAsset = { id: tableUrn, dataset_kind: 'TABLE', security_grade: 'normal', platform: 'postgres', database_name: 'db', schema_name: 'a' }
  const restrictedAsset = { ...validAsset, security_grade: 'restricted' }
  const viewAsset = { ...validAsset, dataset_kind: 'VIEW' }
  const malformedAsset = { ...validAsset, security_grade: undefined }

  const dev = principal('developer', 'developer', { grants: [tableUrn] })
  assert.throws(
    () => assertPocRouteAuthorization(resolvePocRoute(
      'POST', '/poc-api/bulk/uploads/u/preparations/p/metadata-candidates/c/change-request',
    ), dev),
    { code: 'ROLE_FORBIDDEN' },
  )
  const managerSysTable = principal('manager', 'manager', { grants: [tableUrn] })
  const stewardNoSys = principal('steward', 'data_steward', { grants: [tableUrn] })

  const activeSystems = new Set(['system-a'])
  const emptySystems = new Set()

  for (const route of POC_ROUTE_REGISTRY.filter((entry) => [
    'catalog.template.xlsx', 'catalog.template.csv',
    'provider.minio.part', 'provider.minio.complete', 'provider.minio.accepted',
    'catalog.bulk.create', 'catalog.bulk.list', 'catalog.bulk.candidates', 'catalog.bulk.preview',
    'catalog.manual-metadata',
  ].includes(entry.id))) {
    if (route.capability) dev.capabilitySet.add(route.capability)
    assert.throws(() => assertPocRouteAuthorization(route, dev), { code: 'ROLE_FORBIDDEN' })
  }

  for (const route of POC_ROUTE_REGISTRY.filter((entry) => [
    'catalog.bulk.list',
  ].includes(entry.id))) {
    if (route.capability) managerSysTable.capabilitySet.add(route.capability)
    assert.doesNotThrow(() => assertPocRouteAuthorization(route, managerSysTable))
  }
  for (const route of POC_ROUTE_REGISTRY.filter((entry) => [
    'catalog.bulk.create', 'catalog.bulk.candidate-cr', 'catalog.manual-metadata',
    'catalog.template.xlsx', 'catalog.template.csv', 'catalog.bulk.candidates',
    'catalog.bulk.preview', 'provider.minio.part', 'provider.minio.complete',
  ].includes(entry.id))) {
    if (route.capability) managerSysTable.capabilitySet.add(route.capability)
    assert.throws(() => assertPocRouteAuthorization(route, managerSysTable), { code: 'ROLE_FORBIDDEN' })
  }

  assert.ok(!canReadRegistrationAsset(dev, validAsset, activeSystems))
  assert.throws(() => assertRegistrationAssetMutation(dev, validAsset, activeSystems), { code: 'TABLE_DATA_FORBIDDEN' })

  assert.ok(!canReadRegistrationAsset(stewardNoSys, validAsset, activeSystems))
  assert.throws(() => assertRegistrationAssetMutation(stewardNoSys, validAsset, activeSystems), { code: 'TABLE_DATA_FORBIDDEN' })

  const managerNoTable = principal('manager', 'manager')
  assert.ok(!canReadRegistrationAsset(managerNoTable, validAsset, activeSystems))
  assert.throws(() => assertRegistrationAssetMutation(managerNoTable, validAsset, activeSystems), { code: 'TABLE_DATA_FORBIDDEN' })

  assert.ok(!canReadRegistrationAsset(managerSysTable, validAsset, activeSystems))
  assert.throws(() => assertRegistrationAssetMutation(managerSysTable, validAsset, activeSystems), { code: 'TABLE_DATA_FORBIDDEN' })

  const stewardSysTable = principal('steward', 'data_steward', { grants: [tableUrn] })
  const stewardSystems = new Set(['system-b'])
  assert.ok(canReadRegistrationAsset(stewardSysTable, validAsset, stewardSystems))
  assert.doesNotThrow(() => assertRegistrationAssetMutation(stewardSysTable, validAsset, stewardSystems))

  assert.ok(!canReadRegistrationAsset(stewardSysTable, restrictedAsset, stewardSystems))
  const deniedPolicy = structuredClone(approvedDefaultFeatureSecurityPolicy())
  deniedPolicy.cells.find((cell) => (
    cell.feature === 'registration' && cell.role === 'data_steward' && cell.grade === 'normal'
  )).allow = false
  const stewardPolicyDenied = principal('steward', 'data_steward', { grants: [tableUrn], policy: deniedPolicy })
  assert.ok(!canReadRegistrationAsset(stewardPolicyDenied, validAsset, stewardSystems))

  const admin = principal('admin', 'admin')
  assert.ok(canReadRegistrationAsset(admin, validAsset, activeSystems))
  assert.doesNotThrow(() => assertRegistrationAssetMutation(admin, validAsset, activeSystems))

  assert.ok(!canReadRegistrationAsset(admin, malformedAsset, activeSystems))
  assert.throws(() => assertRegistrationAssetMutation(admin, malformedAsset, activeSystems), { code: 'TABLE_DATA_FORBIDDEN' })

  assert.ok(!canReadRegistrationAsset(managerSysTable, validAsset, emptySystems))
  assert.throws(() => assertRegistrationAssetMutation(managerSysTable, validAsset, emptySystems), { code: 'TABLE_DATA_FORBIDDEN' })

  const otherSystems = new Set(['system-c'])
  assert.ok(!canReadRegistrationAsset(managerSysTable, validAsset, otherSystems))
  assert.throws(() => assertRegistrationAssetMutation(managerSysTable, validAsset, otherSystems), { code: 'TABLE_DATA_FORBIDDEN' })

  assert.ok(!canReadRegistrationAsset(admin, viewAsset, activeSystems))
  assert.throws(() => assertRegistrationAssetMutation(admin, viewAsset, activeSystems), { code: 'TABLE_DATA_FORBIDDEN' })
})

test('limits Governance document management to change.manage without widening Knowledge authority', () => {
  const steward = principal('steward', 'data_steward')
  const manager = principal('manager', 'manager')
  const viewer = principal('viewer', 'viewer')
  const developer = principal('developer', 'developer')

  const current = {
    adminMemberships: [],
    adminSystems: [],
    adminSystemAssignees: [],
    adminSystemSchemaScopes: [],
    changeRecords: [],
    changeAttachments: [],
    changeAttachmentLocations: [],
    governanceDocuments: [
      { document_id: 'doc-1', state: 'DRAFT', current_published_version_id: null, current_version_number: null, title: 'Draft' },
      { document_id: 'doc-2', state: 'ACTIVE', current_published_version_id: 'v-2', current_version_number: 2, title: 'Active' },
    ],
    governanceVersions: [
      { version_id: 'v-1', document_id: 'doc-1', state: 'DRAFT', submitted_at: null, reviewed_by: null, reviewed_at: null, published_at: null, title: 'Draft' },
      { version_id: 'v-2', document_id: 'doc-2', state: 'PUBLISHED', submitted_at: 'before', reviewed_by: 'reviewer', reviewed_at: 'then', published_at: 'now', title: 'Published' },
    ],
  }

  assert.doesNotThrow(() => authorizeCoreReplacement(steward, current, {
    ...current,
    governanceDocuments: [...current.governanceDocuments, {
      document_id: 'doc-3', state: 'DRAFT', current_published_version_id: null, current_version_number: null,
    }],
  }))

  assert.throws(() => authorizeCoreReplacement(steward, current, {
    ...current,
    governanceDocuments: [current.governanceDocuments[0]],
  }), { code: 'GOVERNANCE_HARD_DELETE_FORBIDDEN' })

  assert.throws(() => authorizeCoreReplacement(steward, current, {
    ...current,
    governanceDocuments: [...current.governanceDocuments, {
      document_id: 'doc-3', state: 'ACTIVE', current_published_version_id: null, current_version_number: null,
    }],
  }), { code: 'GOVERNANCE_LIFECYCLE_FORBIDDEN' })

  assert.throws(() => authorizeCoreReplacement(steward, current, {
    ...current,
    governanceDocuments: [
      { document_id: 'doc-1', state: 'DRAFT', current_published_version_id: 'v-1' },
      current.governanceDocuments[1]
    ],
  }), { code: 'GOVERNANCE_LIFECYCLE_FORBIDDEN' })

  assert.throws(() => authorizeCoreReplacement(steward, current, {
    ...current,
    governanceDocuments: [
      { ...current.governanceDocuments[0], state: 'ACTIVE' },
      current.governanceDocuments[1],
    ],
  }), { code: 'GOVERNANCE_LIFECYCLE_FORBIDDEN' })

  assert.doesNotThrow(() => authorizeCoreReplacement(steward, current, {
    ...current,
    governanceDocuments: [
      current.governanceDocuments[0],
      { ...current.governanceDocuments[1], state: 'ARCHIVED' },
    ],
  }))

  assert.doesNotThrow(() => authorizeCoreReplacement(steward, current, {
    ...current,
    governanceVersions: [...current.governanceVersions, {
      version_id: 'v-3', document_id: 'doc-1', state: 'DRAFT', submitted_at: null,
      reviewed_by: null, reviewed_at: null, published_at: null, title: 'New draft',
    }],
  }))

  assert.throws(() => authorizeCoreReplacement(steward, current, {
    ...current,
    governanceVersions: [
      { ...current.governanceVersions[0], state: 'IN_REVIEW', submitted_at: 'now' },
      current.governanceVersions[1],
    ],
  }), { code: 'GOVERNANCE_LIFECYCLE_FORBIDDEN' })

  assert.throws(() => authorizeCoreReplacement(steward, current, {
    ...current,
    governanceVersions: [
      current.governanceVersions[0],
      { ...current.governanceVersions[1], title: 'Tampered publication' },
    ],
  }), { code: 'GOVERNANCE_VERSION_IMMUTABLE' })

  assert.doesNotThrow(() => authorizeCoreReplacement(manager, current, {
    ...current,
    governanceDocuments: [
      { ...current.governanceDocuments[0], state: 'ACTIVE', current_published_version_id: 'v-1', current_version_number: 1 },
      current.governanceDocuments[1],
    ],
  }))

  assert.throws(() => authorizeCoreReplacement(viewer, current, {
    ...current,
    governanceDocuments: [...current.governanceDocuments, {
      document_id: 'doc-3', state: 'DRAFT', current_published_version_id: null, current_version_number: null,
    }],
  }), { code: 'CAPABILITY_REQUIRED' })

  assert.throws(() => authorizeCoreReplacement(developer, current, {
    ...current,
    governanceDocuments: [...current.governanceDocuments, {
      document_id: 'doc-3', state: 'DRAFT', current_published_version_id: null, current_version_number: null,
    }],
  }), { code: 'CAPABILITY_REQUIRED' })
})
