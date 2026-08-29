import { describe, expect, it, vi } from 'vitest'
import type {
  AdminAccessRequest,
  ClassificationAccessPolicy,
  ClassificationAccessRule,
  ErasureRequest,
  InferenceProviderProfile,
  LegalHold,
  RestrictedSearchGrant,
  RetentionPolicy,
  WorkspaceMembershipAccess,
} from '../../api/types'
import { AdminApi } from './adminApi'

function mockClient() {
  const request = vi.fn()
  const requestWithMeta = vi.fn()
  return {
    request,
    requestWithMeta,
    api: new AdminApi({ request, requestWithMeta }),
  }
}

const access: WorkspaceMembershipAccess = {
  subject_id: 'subject-one', display_name: 'User', subject_active: true, department_id: null,
  job_function: 'ENGINEER', membership_version: 3,
  access: {
    active: true, clearance: 'INTERNAL', groups: ['engineers'], allowed_actions: ['catalog.read'],
    denied_actions: [], allowed_system_ids: [], allowed_domain_ids: [],
  },
  role_assignment: {
    status: 'MANUAL', role_id: null, role_version: null, assignment_version: null,
    membership_version: null, access_payload_hash: null, assigned_by: null, updated_at: null,
    legacy_markers: [],
  },
  canonical_admin_binding: {
    status: 'NONE', role_version: null, catalog_version: null, membership_version: null,
    binding_version: null, updated_at: null,
  },
  profile_role: {
    status: 'UNASSIGNED', tier: null, policy_version: null, membership_version: null,
    assignment_version: null, updated_at: null,
  },
}

describe('AdminApi', () => {
  it('forces administrator context hydration through the no-store boundary', async () => {
    const { api, request } = mockClient()
    const controller = new AbortController()
    request.mockResolvedValue({})

    await api.getContext(controller.signal)

    expect(request).toHaveBeenCalledWith('/admin/me', {
      cache: 'no-store',
      signal: controller.signal,
    })
  })

  it('loads the server-canonical Role capability catalog through no-store', async () => {
    const { api, request } = mockClient()
    const controller = new AbortController()
    request.mockResolvedValue({})

    await api.getAccessRoleCapabilities(controller.signal)

    expect(request).toHaveBeenCalledWith('/admin/access-roles/capabilities', {
      cache: 'no-store',
      signal: controller.signal,
    })
  })

  it('forwards cancellation to the fixed deployment probe', async () => {
    const { api, request } = mockClient()
    const controller = new AbortController()
    request.mockResolvedValue({})

    await api.testDeploymentSystemConfiguration('DATAHUB_GMS', controller.signal)

    expect(request).toHaveBeenCalledWith(
      '/admin/system-configuration/DATAHUB_GMS/test-deployment',
      { method: 'POST', signal: controller.signal },
    )
  })

  it('uses asset IDs and the System ETag for governed schema-scope changes', async () => {
    const { api, request } = mockClient()
    const controller = new AbortController()
    request.mockResolvedValue({ items: [], page: { next_cursor: null, limit: 25 } })

    await api.listSystemSchemaScopes('system-one', controller.signal)
    await api.listSystemSchemaScopeCandidates('system-one', 'orders', controller.signal)
    await api.patchSystemSchemaScopes(
      'system-one',
      ['asset-one'],
      ['scope-one'],
      '변경관리 대상 스키마 연결',
      7,
      'schema-idempotency-key',
    )

    expect(request).toHaveBeenNthCalledWith(
      1,
      '/admin/systems/system-one/schema-scopes?limit=100',
      { cache: 'no-store', signal: controller.signal },
    )
    expect(request).toHaveBeenNthCalledWith(
      2,
      '/admin/systems/system-one/schema-scope-candidates?limit=25&q=orders',
      { cache: 'no-store', signal: controller.signal },
    )
    expect(request).toHaveBeenNthCalledWith(
      3,
      '/admin/systems/system-one/schema-scopes',
      {
        method: 'PATCH',
        ifMatch: '"7"',
        idempotencyKey: 'schema-idempotency-key',
        body: JSON.stringify({
          upsert_asset_ids: ['asset-one'],
          deactivate_scope_ids: ['scope-one'],
          reason: '변경관리 대상 스키마 연결',
        }),
      },
    )
  })

  it('loads only the redacted classification summary through no-store', async () => {
    const { api, request } = mockClient()
    const controller = new AbortController()
    request.mockResolvedValue({ state: 'STATIC_FLOOR', rules: [] })

    await api.getCurrentClassificationPolicySummary(controller.signal)

    expect(request).toHaveBeenCalledWith(
      '/admin/classification-access/policies/current/summary',
      { cache: 'no-store', signal: controller.signal },
    )
  })

  it('binds administrator cursor pages to their filters and forwards cancellation', async () => {
    const { api, request } = mockClient()
    const controller = new AbortController()
    request.mockResolvedValue({ items: [], page: { next_cursor: 'next-page', limit: 25 } })

    await expect(api.listMembershipRenewalPage({
      state: 'PENDING', cursor: 'renewal-cursor', signal: controller.signal,
    })).resolves.toMatchObject({ items: [], nextCursor: 'next-page', limit: 25 })
    await api.listAccessRolePage({
      query: 'reader', status: 'ACTIVE', cursor: 'role-cursor', signal: controller.signal,
    })
    await api.listSystemPage({
      query: 'warehouse', status: 'ACTIVE', cursor: 'system-cursor', signal: controller.signal,
    })
    await api.listFallbackRequestPage({
      state: 'APPROVED', cursor: 'fallback-cursor', signal: controller.signal,
    })
    await api.listRetentionPolicyPage({
      state: 'DRAFT', cursor: 'retention-cursor', signal: controller.signal,
    })
    await api.listLegalHoldPage({
      state: 'ACTIVE', cursor: 'hold-cursor', signal: controller.signal,
    })
    await api.listErasureRequestPage({
      state: 'PENDING', cursor: 'erasure-cursor', signal: controller.signal,
    })
    await api.listClassificationAccessPolicyPage({
      state: 'PROPOSED', cursor: 'classification-cursor', signal: controller.signal,
    })
    await api.listInferenceProviderProfilePage({
      profileKey: 'internal-chat',
      state: 'APPROVED',
      cursor: 'provider-cursor',
      signal: controller.signal,
    })
    await api.listRestrictedSearchGrantPage({
      state: 'ACTIVE',
      subjectId: 'subject-one',
      cursor: 'grant-cursor',
      signal: controller.signal,
    })

    expect(request.mock.calls.map((call) => String(call[0]))).toEqual([
      '/admin/membership-renewals?limit=25&state=PENDING&cursor=renewal-cursor',
      '/admin/access-roles?limit=25&q=reader&status=ACTIVE&cursor=role-cursor',
      '/admin/systems?limit=25&q=warehouse&status=ACTIVE&cursor=system-cursor',
      '/admin/fallback/workspace-membership-access-requests?limit=25&state=APPROVED&cursor=fallback-cursor',
      '/admin/retention/policies?limit=25&state=DRAFT&cursor=retention-cursor',
      '/admin/retention/legal-holds?limit=25&state=ACTIVE&cursor=hold-cursor',
      '/admin/retention/erasure-requests?limit=25&state=PENDING&cursor=erasure-cursor',
      '/admin/classification-access/policies?limit=25&state=PROPOSED&cursor=classification-cursor',
      '/admin/inference/provider-profiles?limit=25&profile_key=internal-chat&state=APPROVED&cursor=provider-cursor',
      '/admin/classification-access/restricted-search-grants?limit=25&state=ACTIVE&subject_id=subject-one&cursor=grant-cursor',
    ])
    for (const call of request.mock.calls) {
      expect(call[1]).toEqual({ signal: controller.signal })
    }
  })

  it('requires the membership ETag to match the body version', async () => {
    const { api, requestWithMeta } = mockClient()
    requestWithMeta.mockResolvedValueOnce({ data: access, etag: '"3"' })
      .mockResolvedValueOnce({ data: access, etag: '"2"' })

    await expect(api.getMembershipAccess('subject-one')).resolves.toMatchObject({ etag: '"3"' })
    await expect(api.getMembershipAccess('subject-one')).rejects.toThrow(/ETag/)
  })

  it('binds member activity drilldowns to the target and cursor', async () => {
    const { api, request } = mockClient()
    const controller = new AbortController()
    request.mockResolvedValue({ items: [], page: { next_cursor: null, limit: 25 } })

    await api.listMembershipChangeRequestActivity('subject-one', 'cr-cursor', controller.signal)
    await api.listMembershipOwnedTables('subject-one', 'table-cursor', controller.signal)

    expect(request.mock.calls).toEqual([
      [
        '/admin/workspace-memberships/subject-one/change-requests?limit=25&cursor=cr-cursor',
        { signal: controller.signal },
      ],
      [
        '/admin/workspace-memberships/subject-one/owned-tables?limit=25&cursor=table-cursor',
        { signal: controller.signal },
      ],
    ])
  })

  it('binds identity profile and temporary-password mutations to the exact membership ETag', async () => {
    const { api, request, requestWithMeta } = mockClient()
    requestWithMeta.mockResolvedValue({
      data: {
        subject_id: 'subject-one',
        username: 'engineer',
        display_name: 'Data Engineer',
        email: 'engineer@example.test',
        first_name: 'Data',
        last_name: 'Engineer',
        department_id: null,
        job_function: 'ENGINEER',
        membership_version: 3,
        provider_enabled: true,
        email_verified: true,
        required_actions: [],
      },
      etag: '"3"',
    })
    request.mockResolvedValue({})

    await expect(api.getIdentityUserProfile('subject-one')).resolves.toMatchObject({ etag: '"3"' })
    await api.updateIdentityUserProfile(
      'subject-one',
      {
        email: 'engineer@example.test',
        first_name: 'Data',
        last_name: 'Engineer',
        department_id: null,
        job_function: 'DATA_ENGINEER',
      },
      '"3"',
      'identity-profile-key',
    )
    await api.resetIdentityTemporaryPassword(
      'subject-one',
      'Temporary-Only-42!',
      '"3"',
      'identity-password-key',
    )

    expect(requestWithMeta).toHaveBeenCalledWith(
      '/admin/workspace-memberships/subject-one/identity-profile',
      { cache: 'no-store', signal: undefined },
    )
    expect(request.mock.calls).toEqual([
      [
        '/admin/workspace-memberships/subject-one/identity-profile',
        {
          method: 'PUT',
          ifMatch: '"3"',
          idempotencyKey: 'identity-profile-key',
          body: JSON.stringify({
            email: 'engineer@example.test',
            first_name: 'Data',
            last_name: 'Engineer',
            department_id: null,
            job_function: 'DATA_ENGINEER',
          }),
        },
      ],
      [
        '/admin/workspace-memberships/subject-one/temporary-password',
        {
          method: 'PUT',
          ifMatch: '"3"',
          idempotencyKey: 'identity-password-key',
          body: JSON.stringify({ temporary_password: 'Temporary-Only-42!' }),
        },
      ],
    ])
  })

  it('sends an exact direct update with If-Match and one idempotency key', async () => {
    const { api, request } = mockClient()
    request.mockResolvedValue({ target_subject_id: 'subject-one', membership_version: 4, payload_hash: 'a'.repeat(64) })

    await api.updateMembership('subject-one', access.access, '"3"', 'admin-direct-operation-key')

    expect(request).toHaveBeenCalledOnce()
    expect(request).toHaveBeenCalledWith('/admin/workspace-memberships/subject-one/access', {
      method: 'PUT', ifMatch: '"3"', idempotencyKey: 'admin-direct-operation-key',
      body: JSON.stringify(access.access),
    })
  })

  it('binds fallback decisions and consume to the aggregate version and approved hash', async () => {
    const { api, request } = mockClient()
    const fallback = {
      id: 'request-one', version: 2, payload_hash: 'b'.repeat(64),
    } as AdminAccessRequest
    request.mockResolvedValue(fallback)

    await api.decideFallbackRequest(fallback, 'APPROVED', 'checked', 'fallback-decision-key')
    await api.consumeFallbackRequest(fallback, 'fallback-consume-key')

    expect(request.mock.calls[0]?.[1]).toMatchObject({ ifMatch: '"2"', idempotencyKey: 'fallback-decision-key' })
    expect(request.mock.calls[1]?.[1]).toMatchObject({
      ifMatch: '"2"', idempotencyKey: 'fallback-consume-key',
      body: JSON.stringify({ confirmed_payload_hash: 'b'.repeat(64) }),
    })
  })

  it('exposes retention and Legal Hold governance without any destructive route', async () => {
    const { api, request } = mockClient()
    const policy = { policy_id: 'policy-one', version: 1 } as RetentionPolicy
    const hold = { hold_id: 'hold-one', version: 1 } as LegalHold
    request.mockResolvedValue({})

    await api.proposeRetentionPolicy(
      { completed_operation_days: 1, chat_content_days: 1, audit_online_months: 1, immutable_archive_years: 1 },
      {
        contract_version: 'POLICY_BOOK_V2',
        effective_from: '2026-07-23T00:00:00.000Z',
        effective_until: null,
        execution_authorization_hours: 24,
        class_rules: [
          { data_class: 'COMPLETED_OPERATIONS', unit: 'DAYS', minimum: 1, maximum: 30, archive_disposition: 'NO_ARCHIVE' },
          { data_class: 'CHAT_CONTENT', unit: 'DAYS', minimum: 1, maximum: 30, archive_disposition: 'NO_ARCHIVE' },
          { data_class: 'AUDIT_EVIDENCE', unit: 'MONTHS', minimum: 1, maximum: 12, archive_disposition: 'CONTENT_WORM' },
          { data_class: 'OBJECT_DATA', unit: 'DAYS', minimum: 1, maximum: 365, archive_disposition: 'CONTENT_WORM' },
        ],
      },
      'reason',
      'policy-key',
    )
    await api.decideRetentionPolicy(policy, 'APPROVED', 'reason', 'policy-decision-key')
    await api.placeLegalHold('AUDIT_EVIDENCE', 'WORKSPACE', null, null, 'reason', 'hold-key')
    await api.getLegalHold('hold-one')
    await api.requestLegalHoldRelease(hold, 'reason', 'hold-release-key')
    await api.decideLegalHoldRelease(hold, 'APPROVED', 'reason', 'hold-decision-key')

    const proposalBody = JSON.parse(
      String((request.mock.calls[0]?.[1] as { body?: string }).body),
    ) as {
      contract: {
        class_rules: Array<{ archive_disposition: string }>
      }
    }
    expect(proposalBody.contract.class_rules.map((rule) => rule.archive_disposition)).toEqual([
      'NO_ARCHIVE',
      'NO_ARCHIVE',
      'CONTENT_WORM',
      'CONTENT_WORM',
    ])
    const paths = request.mock.calls.map((call) => String(call[0]))
    expect(paths).toEqual([
      '/admin/retention/policies',
      '/admin/retention/policies/policy-one/decisions',
      '/admin/retention/legal-holds',
      '/admin/retention/legal-holds/hold-one',
      '/admin/retention/legal-holds/hold-one/release-requests',
      '/admin/retention/legal-holds/hold-one/release-decisions',
    ])
    expect(paths.join(' ')).not.toMatch(/delet|destroy|execute/i)
  })

  it('binds erasure review to response ETags without exposing execution', async () => {
    const { api, request, requestWithMeta } = mockClient()
    const erasure = {
      erasure_request_id: 'request-one', target_type: 'UPLOAD_OBJECT', target_id: 'target-one',
      version: 1, state: 'PENDING', execution_state: 'DISABLED_NOT_READY',
    } as ErasureRequest
    request.mockResolvedValue({
      items: [erasure],
      page: { next_cursor: null, limit: 100 },
    })
    requestWithMeta.mockResolvedValue({ data: erasure, etag: '"1"' })

    await api.listErasureRequests()
    const created = await api.requestErasure(
      'UPLOAD_OBJECT', 'target-one', 'review', 3600, 'erasure-create-key',
    )
    await api.getErasureRequest('request-one')
    await api.decideErasure(created, 'APPROVED', 'checked', 'erasure-decision-key')

    const paths = [
      ...request.mock.calls.map((call) => String(call[0])),
      ...requestWithMeta.mock.calls.map((call) => String(call[0])),
    ]
    expect(paths).toContain('/admin/retention/erasure-requests?limit=100')
    expect(paths).toContain('/admin/retention/erasure-requests')
    expect(paths).toContain('/admin/retention/erasure-requests/request-one')
    expect(paths).toContain('/admin/retention/erasure-requests/request-one/decisions')
    expect(paths.join(' ')).not.toMatch(/delete|destroy|execute|consume/i)
    expect(requestWithMeta.mock.calls.at(-1)?.[1]).toMatchObject({
      ifMatch: '"1"', idempotencyKey: 'erasure-decision-key',
    })
  })

  it('reads sanitized archive-only execution evidence without a mutation route', async () => {
    const { api, request } = mockClient()
    request.mockResolvedValue({
      erasure_request_id: 'request-one',
      availability: 'NOT_PLANNED',
      archive_only: true,
      deletion_automation_state: 'DISABLED_NOT_READY',
      job: null,
    })

    await api.getErasureExecutionEvidence('request-one')

    expect(request).toHaveBeenCalledWith(
      '/admin/retention/erasure-requests/request-one/execution-evidence',
      { signal: undefined },
    )
  })

  it('binds classification, provider, and RESTRICTED grant mutations to versions', async () => {
    const { api, request } = mockClient()
    const rules: ClassificationAccessRule[] = [
      { classification: 'PUBLIC', search_mode: 'ABAC', chat_mode: 'DENY', provider_profile_version_id: null, embedding_provider_profile_version_id: null, reranker_provider_profile_version_id: null },
      { classification: 'INTERNAL', search_mode: 'ABAC', chat_mode: 'DENY', provider_profile_version_id: null, embedding_provider_profile_version_id: null, reranker_provider_profile_version_id: null },
      { classification: 'CONFIDENTIAL', search_mode: 'DENY', chat_mode: 'DENY', provider_profile_version_id: null, embedding_provider_profile_version_id: null, reranker_provider_profile_version_id: null },
      { classification: 'RESTRICTED', search_mode: 'EXPLICIT_GRANT_ONLY', chat_mode: 'DENY', provider_profile_version_id: null, embedding_provider_profile_version_id: null, reranker_provider_profile_version_id: null },
    ]
    const policy = { policy_id: 'policy-one', version: 1, rules } as ClassificationAccessPolicy
    const profile = {
      provider_profile_version_id: 'profile-one', version: 2,
    } as InferenceProviderProfile
    const grant = { grant_id: 'grant-one', version: 2 } as RestrictedSearchGrant
    request.mockResolvedValue({})

    await api.proposeClassificationAccessPolicy({
      required_jurisdiction: 'approved-jurisdiction',
      restricted_search_grant_maximum_days: 30,
      rules,
      reason: 'reviewed',
    }, 'classification-propose-key')
    await api.decideClassificationAccessPolicy(policy, 'APPROVED', 'checked', 'classification-decision-key')
    await api.decideInferenceProviderProfile(profile, 'APPROVED', 'checked', 'provider-decision-key')
    await api.revokeInferenceProviderProfile(profile, 'deny first', 'provider-revoke-key')
    await api.decideRestrictedSearchGrant(grant, 'APPROVED', 'checked', 'grant-decision-key')
    await api.revokeRestrictedSearchGrant(grant, 'deny first', 'grant-revoke-key')

    expect(request.mock.calls.map((call) => String(call[0]))).toEqual([
      '/admin/classification-access/policies',
      '/admin/classification-access/policies/policy-one/decisions',
      '/admin/inference/provider-profiles/profile-one/decisions',
      '/admin/inference/provider-profiles/profile-one/revocations',
      '/admin/classification-access/restricted-search-grants/grant-one/decisions',
      '/admin/classification-access/restricted-search-grants/grant-one/revocations',
    ])
    expect(request.mock.calls[0]?.[1]).toMatchObject({ idempotencyKey: 'classification-propose-key' })
    expect(request.mock.calls[1]?.[1] as unknown).toMatchObject({ ifMatch: '"1"', idempotencyKey: 'classification-decision-key' })
    expect(request.mock.calls[2]?.[1] as unknown).toMatchObject({ ifMatch: '"2"', idempotencyKey: 'provider-decision-key' })
    expect(request.mock.calls[3]?.[1] as unknown).toMatchObject({ ifMatch: '"2"', idempotencyKey: 'provider-revoke-key' })
    expect(request.mock.calls[4]?.[1] as unknown).toMatchObject({ ifMatch: '"2"', idempotencyKey: 'grant-decision-key' })
    expect(request.mock.calls[5]?.[1] as unknown).toMatchObject({ ifMatch: '"2"', idempotencyKey: 'grant-revoke-key' })
  })

  it('never lets a grant proposal choose its governing policy binding', async () => {
    const { api, request } = mockClient()
    request.mockResolvedValue({})
    await api.proposeRestrictedSearchGrant({
      subject_id: 'subject-one',
      scope: 'RESOURCE',
      scope_id: 'resource-one',
      purpose: 'investigation',
      valid_from: '2030-01-01T00:00:00.000Z',
      expires_at: '2030-01-02T00:00:00.000Z',
      reason: 'reviewed request',
    }, 'grant-propose-key')

    const options = request.mock.calls[0]?.[1] as unknown as { body?: BodyInit }
    if (typeof options.body !== 'string') throw new Error('expected a JSON request body')
    const body = JSON.parse(options.body) as Record<string, unknown>
    expect(request.mock.calls[0]?.[0]).toBe('/admin/classification-access/restricted-search-grants')
    expect(options).toMatchObject({ method: 'POST', idempotencyKey: 'grant-propose-key' })
    expect(body).not.toHaveProperty('classification_policy_id')
    expect(body).not.toHaveProperty('classification_policy_hash')
    expect(body).not.toHaveProperty('provider')
  })
})
