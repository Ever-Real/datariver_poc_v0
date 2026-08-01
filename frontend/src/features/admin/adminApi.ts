import type { ApiClient } from '../../api/client'
import type {
  AdminAccessRequest,
  AdminAccessRequestState,
  AdminReadContext,
  AccessRole,
  AccessRoleCapabilityCatalog,
  AccessRoleWrite,
  CapabilitiesResponse,
  CatalogSearch,
  ClassificationAccessPolicy,
  ClassificationAccessPolicyProposal,
  ClassificationAccessPolicyState,
  ClassificationPolicySummary,
  ErasureRequest,
  ErasureRequestState,
  ErasureTargetType,
  LegalHold,
  LegalHoldResourceType,
  LegalHoldScope,
  LegalHoldState,
  InferenceProviderProfile,
  InferenceProviderProfileState,
  IdentityUserProvisionInput,
  IdentityUserProvisionResult,
  IdentityTemporaryPasswordResetResult,
  IdentityUserProfile,
  IdentityUserProfileUpdateInput,
  IdentityUserProfileUpdateResult,
  MembershipAccessDocument,
  MembershipAccessUpdateResult,
  MembershipChangeRequestActivity,
  MembershipOwnedTable,
  MembershipRenewalRequest,
  MembershipRoleAssignmentResult,
  RetentionDataClass,
  RetentionExecutionEvidence,
  RetentionPolicy,
  RetentionPolicyContract,
  RetentionPolicyState,
  RetentionRules,
  RestrictedSearchGrant,
  RestrictedSearchGrantProposal,
  RestrictedSearchGrantState,
  WorkspaceMembershipAccess,
  WorkspaceMembershipSummary,
  SystemDirectoryEntry,
  SystemAssigneeKey,
  SystemAssigneePage,
  SystemAssigneeUpdate,
  SystemAssigneeUpdateResult,
  SystemConfigurationInventory,
  SystemConfigurationTestResult,
} from '../../api/types'

type AdminApiClient = Pick<ApiClient, 'request' | 'requestWithMeta'>
type GovernanceDecision = 'APPROVED' | 'REJECTED'

export interface VersionedMembershipAccess extends WorkspaceMembershipAccess {
  etag: string
}

export interface VersionedIdentityUserProfile extends IdentityUserProfile {
  etag: string
}

export interface VersionedErasureRequest extends ErasureRequest {
  etag: string
}

export interface AdminCursorPage<T> {
  items: T[]
  nextCursor: string | null
  limit: number
}

interface AdminPageResponse<T> {
  items: T[]
  page: { next_cursor: string | null; limit: number }
}

export class AdminApi {
  constructor(private readonly client: AdminApiClient) {}

  getContext(signal?: AbortSignal) {
    return this.client.request<AdminReadContext>('/admin/me', {
      cache: 'no-store',
      signal,
    })
  }

  async listMemberships() {
    return (await this.client.request<{
      items: WorkspaceMembershipSummary[]
      page: { next_cursor: string | null; limit: number }
    }>(
      '/admin/workspace-memberships?limit=100',
    )).items
  }

  async listMembershipPage({
    query,
    status,
    cursor,
    limit = 25,
    signal,
  }: {
    query?: string
    status?: 'ACTIVE' | 'INACTIVE'
    cursor?: string
    limit?: number
    signal?: AbortSignal
  } = {}): Promise<AdminCursorPage<WorkspaceMembershipSummary>> {
    const parameters = new URLSearchParams({ limit: String(limit) })
    if (query) parameters.set('q', query)
    if (status) parameters.set('status', status)
    if (cursor) parameters.set('cursor', cursor)
    const response = await this.client.request<{
      items: WorkspaceMembershipSummary[]
      page: { next_cursor: string | null; limit: number }
    }>(`/admin/workspace-memberships?${parameters.toString()}`, { signal })
    return {
      items: response.items,
      nextCursor: response.page.next_cursor,
      limit: response.page.limit,
    }
  }

  async createSystem(
    payload: { code: string; name: string; description: string },
    idempotencyKey: string,
  ): Promise<SystemDirectoryEntry> {
    return this.client.request<SystemDirectoryEntry>('/admin/systems', {
      method: 'POST',
      idempotencyKey,
      body: JSON.stringify(payload),
    })
  }

  async listMembershipChangeRequestActivity(
    subjectId: string,
    cursor?: string,
    signal?: AbortSignal,
  ): Promise<AdminCursorPage<MembershipChangeRequestActivity>> {
    const parameters = new URLSearchParams({ limit: '25' })
    if (cursor) parameters.set('cursor', cursor)
    return adminCursorPage(await this.client.request<AdminPageResponse<MembershipChangeRequestActivity>>(
      `/admin/workspace-memberships/${encodeURIComponent(subjectId)}/change-requests?${parameters.toString()}`,
      { signal },
    ))
  }

  async listMembershipOwnedTables(
    subjectId: string,
    cursor?: string,
    signal?: AbortSignal,
  ): Promise<AdminCursorPage<MembershipOwnedTable>> {
    const parameters = new URLSearchParams({ limit: '25' })
    if (cursor) parameters.set('cursor', cursor)
    return adminCursorPage(await this.client.request<AdminPageResponse<MembershipOwnedTable>>(
      `/admin/workspace-memberships/${encodeURIComponent(subjectId)}/owned-tables?${parameters.toString()}`,
      { signal },
    ))
  }

  provisionIdentityUser(payload: IdentityUserProvisionInput, idempotencyKey: string) {
    return this.client.request<IdentityUserProvisionResult>('/admin/identity-users', {
      method: 'POST', idempotencyKey, body: JSON.stringify(payload),
    })
  }

  async getIdentityUserProfile(
    subjectId: string,
    signal?: AbortSignal,
  ): Promise<VersionedIdentityUserProfile> {
    const response = await this.client.requestWithMeta<IdentityUserProfile>(
      `/admin/workspace-memberships/${encodeURIComponent(subjectId)}/identity-profile`,
      { signal, cache: 'no-store' },
    )
    const expected = quotedVersion(response.data.membership_version)
    if (response.etag !== expected) {
      throw new Error('사용자 프로필 버전 ETag를 검증하지 못했습니다. 새로고침 후 다시 시도하세요.')
    }
    return { ...response.data, etag: response.etag }
  }

  updateIdentityUserProfile(
    subjectId: string,
    payload: IdentityUserProfileUpdateInput,
    etag: string,
    idempotencyKey: string,
  ) {
    return this.client.request<IdentityUserProfileUpdateResult>(
      `/admin/workspace-memberships/${encodeURIComponent(subjectId)}/identity-profile`,
      {
        method: 'PUT',
        ifMatch: etag,
        idempotencyKey,
        body: JSON.stringify(payload),
      },
    )
  }

  resetIdentityTemporaryPassword(
    subjectId: string,
    temporaryPassword: string,
    etag: string,
    idempotencyKey: string,
  ) {
    return this.client.request<IdentityTemporaryPasswordResetResult>(
      `/admin/workspace-memberships/${encodeURIComponent(subjectId)}/temporary-password`,
      {
        method: 'PUT',
        ifMatch: etag,
        idempotencyKey,
        body: JSON.stringify({ temporary_password: temporaryPassword }),
      },
    )
  }

  async listMembershipRenewalPage({
    state,
    cursor,
    limit = 25,
    signal,
  }: {
    state?: MembershipRenewalRequest['state']
    cursor?: string
    limit?: number
    signal?: AbortSignal
  } = {}): Promise<AdminCursorPage<MembershipRenewalRequest>> {
    const parameters = new URLSearchParams({ limit: String(limit) })
    if (state) parameters.set('state', state)
    if (cursor) parameters.set('cursor', cursor)
    return adminCursorPage(await this.client.request<AdminPageResponse<MembershipRenewalRequest>>(
      `/admin/membership-renewals?${parameters.toString()}`,
      { signal },
    ))
  }

  async listMembershipRenewals(state?: MembershipRenewalRequest['state']) {
    return (await this.listMembershipRenewalPage({ state, limit: 100 })).items
  }

  decideMembershipRenewal(
    renewal: MembershipRenewalRequest,
    decision: GovernanceDecision,
    reason: string,
    idempotencyKey: string,
  ) {
    return this.client.request<MembershipRenewalRequest>(
      `/admin/membership-renewals/${encodeURIComponent(renewal.id)}/decisions`,
      {
        method: 'POST',
        ifMatch: quotedVersion(renewal.version),
        idempotencyKey,
        body: JSON.stringify({ decision, reason }),
      },
    )
  }

  requestOwnMembershipRenewal(reason: string, idempotencyKey: string) {
    return this.client.request<MembershipRenewalRequest>('/admin/membership-renewals/me', {
      method: 'POST', idempotencyKey, body: JSON.stringify({ reason }),
    })
  }

  async listOwnMembershipRenewals() {
    return (await this.client.request<{ items: MembershipRenewalRequest[] }>(
      '/admin/membership-renewals/me?limit=100',
    )).items
  }

  async listAccessRolePage({
    query,
    status,
    cursor,
    limit = 25,
    signal,
  }: {
    query?: string
    status?: 'ACTIVE' | 'INACTIVE'
    cursor?: string
    limit?: number
    signal?: AbortSignal
  } = {}): Promise<AdminCursorPage<AccessRole>> {
    const parameters = new URLSearchParams({ limit: String(limit) })
    if (query) parameters.set('q', query)
    if (status) parameters.set('status', status)
    if (cursor) parameters.set('cursor', cursor)
    return adminCursorPage(await this.client.request<AdminPageResponse<AccessRole>>(
      `/admin/access-roles?${parameters.toString()}`,
      { signal },
    ))
  }

  async listAccessRoles() {
    return (await this.listAccessRolePage({ limit: 100 })).items
  }

  getAccessRoleCapabilities(signal?: AbortSignal) {
    return this.client.request<AccessRoleCapabilityCatalog>('/admin/access-roles/capabilities', {
      cache: 'no-store',
      signal,
    })
  }

  createAccessRole(payload: AccessRoleWrite) {
    return this.client.request<AccessRole>('/admin/access-roles', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  }

  updateAccessRole(role: AccessRole, payload: AccessRoleWrite) {
    return this.client.request<AccessRole>(`/admin/access-roles/${encodeURIComponent(role.id)}`, {
      method: 'PUT',
      ifMatch: quotedVersion(role.version),
      body: JSON.stringify(payload),
    })
  }

  deactivateAccessRole(role: AccessRole) {
    return this.client.request<AccessRole>(`/admin/access-roles/${encodeURIComponent(role.id)}`, {
      method: 'DELETE',
      ifMatch: quotedVersion(role.version),
    })
  }

  assignMembershipRole(
    subjectId: string,
    roleId: string | null,
    etag: string,
    idempotencyKey: string,
  ) {
    return this.client.request<MembershipRoleAssignmentResult>(
      `/admin/workspace-memberships/${encodeURIComponent(subjectId)}/role`,
      {
        method: 'PUT', ifMatch: etag, idempotencyKey,
        body: JSON.stringify({ role_id: roleId }),
      },
    )
  }

  async listSystemPage({
    query,
    status,
    cursor,
    limit = 25,
    signal,
  }: {
    query?: string
    status?: 'ACTIVE' | 'INACTIVE'
    cursor?: string
    limit?: number
    signal?: AbortSignal
  } = {}): Promise<AdminCursorPage<SystemDirectoryEntry>> {
    const parameters = new URLSearchParams({ limit: String(limit) })
    if (query) parameters.set('q', query)
    if (status) parameters.set('status', status)
    if (cursor) parameters.set('cursor', cursor)
    return adminCursorPage(await this.client.request<AdminPageResponse<SystemDirectoryEntry>>(
      `/admin/systems?${parameters.toString()}`,
      { signal },
    ))
  }

  async listSystems() {
    return (await this.listSystemPage({ limit: 100 })).items
  }

  async listSystemAssigneePage(
    systemId: string,
    {
      cursor,
      limit = 25,
      signal,
    }: {
      cursor?: string
      limit?: number
      signal?: AbortSignal
    } = {},
  ) {
    const parameters = new URLSearchParams({ limit: String(limit) })
    if (cursor) parameters.set('cursor', cursor)
    return this.client.request<SystemAssigneePage>(
      `/admin/systems/${encodeURIComponent(systemId)}/assignees?${parameters.toString()}`,
      { signal },
    )
  }

  async searchRestrictedGrantTargets(query: string, signal?: AbortSignal) {
    return (await this.client.request<CatalogSearch>(
      `/catalog/assets?q=${encodeURIComponent(query)}&limit=20`,
      { signal },
    )).items
  }

  updateSystemAssignees(
    systemId: string,
    assignees: SystemAssigneeUpdate[],
    version: number,
    idempotencyKey: string,
  ) {
    return this.client.request<SystemAssigneeUpdateResult>(
      `/admin/systems/${encodeURIComponent(systemId)}/assignees`,
      {
        method: 'PUT',
        ifMatch: quotedVersion(version),
        idempotencyKey,
        body: JSON.stringify({ assignees }),
      },
    )
  }

  patchSystemAssignees(
    systemId: string,
    upserts: SystemAssigneeUpdate[],
    removals: SystemAssigneeKey[],
    version: number,
    idempotencyKey: string,
  ) {
    return this.client.request<SystemAssigneeUpdateResult>(
      `/admin/systems/${encodeURIComponent(systemId)}/assignees`,
      {
        method: 'PATCH',
        ifMatch: quotedVersion(version),
        idempotencyKey,
        body: JSON.stringify({ upserts, removals }),
      },
    )
  }

  listSystemConfiguration(signal?: AbortSignal) {
    return this.client.request<SystemConfigurationInventory>(
      '/admin/system-configuration',
      { signal, cache: 'no-store' },
    )
  }

  getCapabilities(signal?: AbortSignal) {
    return this.client.request<CapabilitiesResponse>(
      '/capabilities',
      { signal, cache: 'no-store' },
    )
  }

  testDeploymentSystemConfiguration(systemId: string) {
    return this.client.request<SystemConfigurationTestResult>(
      `/admin/system-configuration/${encodeURIComponent(systemId)}/test-deployment`,
      { method: 'POST' },
    )
  }

  async getMembershipAccess(
    subjectId: string,
    signal?: AbortSignal,
  ): Promise<VersionedMembershipAccess> {
    const response = await this.client.requestWithMeta<WorkspaceMembershipAccess>(
      `/admin/workspace-memberships/${encodeURIComponent(subjectId)}/access`,
      { signal },
    )
    const expected = quotedVersion(response.data.membership_version)
    if (response.etag !== expected) {
      throw new Error('멤버십 버전 ETag를 검증하지 못했습니다. 새로고침 후 다시 시도하세요.')
    }
    return { ...response.data, etag: response.etag }
  }

  updateMembership(
    subjectId: string,
    access: MembershipAccessDocument,
    etag: string,
    idempotencyKey: string,
  ) {
    return this.client.request<MembershipAccessUpdateResult>(
      `/admin/workspace-memberships/${encodeURIComponent(subjectId)}/access`,
      {
        method: 'PUT',
        ifMatch: etag,
        idempotencyKey,
        body: JSON.stringify(access),
      },
    )
  }

  async listFallbackRequestPage({
    state,
    cursor,
    limit = 25,
    signal,
  }: {
    state?: AdminAccessRequestState
    cursor?: string
    limit?: number
    signal?: AbortSignal
  } = {}): Promise<AdminCursorPage<AdminAccessRequest>> {
    const parameters = new URLSearchParams({ limit: String(limit) })
    if (state) parameters.set('state', state)
    if (cursor) parameters.set('cursor', cursor)
    return adminCursorPage(await this.client.request<AdminPageResponse<AdminAccessRequest>>(
      `/admin/fallback/workspace-membership-access-requests?${parameters.toString()}`,
      { signal },
    ))
  }

  async listFallbackRequests(state?: AdminAccessRequestState) {
    return (await this.listFallbackRequestPage({ state, limit: 100 })).items
  }

  createFallbackRequest(
    subjectId: string,
    reason: string,
    access: MembershipAccessDocument,
    etag: string,
    idempotencyKey: string,
  ) {
    return this.client.request<AdminAccessRequest>(
      '/admin/fallback/workspace-membership-access-requests',
      {
        method: 'POST',
        ifMatch: etag,
        idempotencyKey,
        body: JSON.stringify({ target_subject_id: subjectId, reason, access }),
      },
    )
  }

  decideFallbackRequest(
    request: AdminAccessRequest,
    decision: GovernanceDecision,
    reason: string,
    idempotencyKey: string,
  ) {
    return this.client.request<AdminAccessRequest>(
      `/admin/fallback/workspace-membership-access-requests/${encodeURIComponent(request.id)}/decisions`,
      {
        method: 'POST',
        ifMatch: quotedVersion(request.version),
        idempotencyKey,
        body: JSON.stringify({ decision, reason }),
      },
    )
  }

  consumeFallbackRequest(request: AdminAccessRequest, idempotencyKey: string) {
    return this.client.request<{ request: AdminAccessRequest; membership_version: number }>(
      `/admin/fallback/workspace-membership-access-requests/${encodeURIComponent(request.id)}/consume`,
      {
        method: 'POST',
        ifMatch: quotedVersion(request.version),
        idempotencyKey,
        body: JSON.stringify({ confirmed_payload_hash: request.payload_hash }),
      },
    )
  }

  async listRetentionPolicyPage({
    state,
    cursor,
    limit = 25,
    signal,
  }: {
    state?: RetentionPolicyState
    cursor?: string
    limit?: number
    signal?: AbortSignal
  } = {}): Promise<AdminCursorPage<RetentionPolicy>> {
    const parameters = new URLSearchParams({ limit: String(limit) })
    if (state) parameters.set('state', state)
    if (cursor) parameters.set('cursor', cursor)
    return adminCursorPage(await this.client.request<AdminPageResponse<RetentionPolicy>>(
      `/admin/retention/policies?${parameters.toString()}`,
      { signal },
    ))
  }

  async listRetentionPolicies(state?: RetentionPolicyState) {
    return (await this.listRetentionPolicyPage({ state, limit: 100 })).items
  }

  proposeRetentionPolicy(
    rules: RetentionRules,
    contract: RetentionPolicyContract,
    reason: string,
    idempotencyKey: string,
  ) {
    return this.client.request<RetentionPolicy>('/admin/retention/policies', {
      method: 'POST',
      idempotencyKey,
      body: JSON.stringify({ rules, contract, reason }),
    })
  }

  decideRetentionPolicy(
    policy: RetentionPolicy,
    decision: GovernanceDecision,
    reason: string,
    idempotencyKey: string,
  ) {
    return this.client.request<RetentionPolicy>(
      `/admin/retention/policies/${encodeURIComponent(policy.policy_id)}/decisions`,
      {
        method: 'POST',
        ifMatch: quotedVersion(policy.version),
        idempotencyKey,
        body: JSON.stringify({ decision, reason }),
      },
    )
  }

  async listClassificationAccessPolicyPage({
    state,
    cursor,
    limit = 25,
    signal,
  }: {
    state?: ClassificationAccessPolicyState
    cursor?: string
    limit?: number
    signal?: AbortSignal
  } = {}): Promise<AdminCursorPage<ClassificationAccessPolicy>> {
    const parameters = new URLSearchParams({ limit: String(limit) })
    if (state) parameters.set('state', state)
    if (cursor) parameters.set('cursor', cursor)
    return adminCursorPage(await this.client.request<AdminPageResponse<ClassificationAccessPolicy>>(
      `/admin/classification-access/policies?${parameters.toString()}`,
      { signal },
    ))
  }

  async listClassificationAccessPolicies(state?: ClassificationAccessPolicyState) {
    return (await this.listClassificationAccessPolicyPage({ state, limit: 100 })).items
  }

  getCurrentClassificationPolicySummary(signal?: AbortSignal) {
    return this.client.request<ClassificationPolicySummary>(
      '/admin/classification-access/policies/current/summary',
      { cache: 'no-store', signal },
    )
  }

  getCurrentClassificationAccessPolicy(signal?: AbortSignal) {
    return this.client.request<ClassificationAccessPolicy | null>(
      '/admin/classification-access/policies/current',
      { signal },
    )
  }

  proposeClassificationAccessPolicy(
    proposal: ClassificationAccessPolicyProposal,
    idempotencyKey: string,
  ) {
    return this.client.request<ClassificationAccessPolicy>(
      '/admin/classification-access/policies',
      {
        method: 'POST',
        idempotencyKey,
        body: JSON.stringify(proposal),
      },
    )
  }

  decideClassificationAccessPolicy(
    policy: ClassificationAccessPolicy,
    decision: GovernanceDecision,
    reason: string,
    idempotencyKey: string,
  ) {
    return this.client.request<ClassificationAccessPolicy>(
      `/admin/classification-access/policies/${encodeURIComponent(policy.policy_id)}/decisions`,
      {
        method: 'POST',
        ifMatch: quotedVersion(policy.version),
        idempotencyKey,
        body: JSON.stringify({ decision, reason }),
      },
    )
  }

  async listInferenceProviderProfilePage({
    profileKey,
    state,
    cursor,
    limit = 25,
    signal,
  }: {
    profileKey?: string
    state?: InferenceProviderProfileState
    cursor?: string
    limit?: number
    signal?: AbortSignal
  } = {}): Promise<AdminCursorPage<InferenceProviderProfile>> {
    const parameters = new URLSearchParams({ limit: String(limit) })
    if (profileKey) parameters.set('profile_key', profileKey)
    if (state) parameters.set('state', state)
    if (cursor) parameters.set('cursor', cursor)
    return adminCursorPage(await this.client.request<AdminPageResponse<InferenceProviderProfile>>(
      `/admin/inference/provider-profiles?${parameters.toString()}`,
      { signal },
    ))
  }

  async listInferenceProviderProfiles(state?: InferenceProviderProfileState) {
    return (await this.listInferenceProviderProfilePage({ state, limit: 100 })).items
  }

  decideInferenceProviderProfile(
    profile: InferenceProviderProfile,
    decision: GovernanceDecision,
    reason: string,
    idempotencyKey: string,
  ) {
    return this.client.request<InferenceProviderProfile>(
      `/admin/inference/provider-profiles/${encodeURIComponent(profile.provider_profile_version_id)}/decisions`,
      {
        method: 'POST',
        ifMatch: quotedVersion(profile.version),
        idempotencyKey,
        body: JSON.stringify({ decision, reason }),
      },
    )
  }

  revokeInferenceProviderProfile(
    profile: InferenceProviderProfile,
    reason: string,
    idempotencyKey: string,
  ) {
    return this.client.request<InferenceProviderProfile>(
      `/admin/inference/provider-profiles/${encodeURIComponent(profile.provider_profile_version_id)}/revocations`,
      {
        method: 'POST',
        ifMatch: quotedVersion(profile.version),
        idempotencyKey,
        body: JSON.stringify({ reason }),
      },
    )
  }

  async listRestrictedSearchGrantPage({
    state,
    subjectId,
    cursor,
    limit = 25,
    signal,
  }: {
    state?: RestrictedSearchGrantState
    subjectId?: string
    cursor?: string
    limit?: number
    signal?: AbortSignal
  } = {}): Promise<AdminCursorPage<RestrictedSearchGrant>> {
    const parameters = new URLSearchParams({ limit: String(limit) })
    if (state) parameters.set('state', state)
    if (subjectId) parameters.set('subject_id', subjectId)
    if (cursor) parameters.set('cursor', cursor)
    return adminCursorPage(await this.client.request<AdminPageResponse<RestrictedSearchGrant>>(
      `/admin/classification-access/restricted-search-grants?${parameters.toString()}`,
      { signal },
    ))
  }

  async listRestrictedSearchGrants(
    state?: RestrictedSearchGrantState,
    subjectId?: string,
  ) {
    return (await this.listRestrictedSearchGrantPage({
      state,
      subjectId,
      limit: 100,
    })).items
  }

  proposeRestrictedSearchGrant(
    proposal: RestrictedSearchGrantProposal,
    idempotencyKey: string,
  ) {
    return this.client.request<RestrictedSearchGrant>(
      '/admin/classification-access/restricted-search-grants',
      {
        method: 'POST',
        idempotencyKey,
        body: JSON.stringify(proposal),
      },
    )
  }

  decideRestrictedSearchGrant(
    grant: RestrictedSearchGrant,
    decision: GovernanceDecision,
    reason: string,
    idempotencyKey: string,
  ) {
    return this.client.request<RestrictedSearchGrant>(
      `/admin/classification-access/restricted-search-grants/${encodeURIComponent(grant.grant_id)}/decisions`,
      {
        method: 'POST',
        ifMatch: quotedVersion(grant.version),
        idempotencyKey,
        body: JSON.stringify({ decision, reason }),
      },
    )
  }

  revokeRestrictedSearchGrant(
    grant: RestrictedSearchGrant,
    reason: string,
    idempotencyKey: string,
  ) {
    return this.client.request<RestrictedSearchGrant>(
      `/admin/classification-access/restricted-search-grants/${encodeURIComponent(grant.grant_id)}/revocations`,
      {
        method: 'POST',
        ifMatch: quotedVersion(grant.version),
        idempotencyKey,
        body: JSON.stringify({ reason }),
      },
    )
  }

  async listLegalHoldPage({
    state,
    cursor,
    limit = 25,
    signal,
  }: {
    state?: LegalHoldState
    cursor?: string
    limit?: number
    signal?: AbortSignal
  } = {}): Promise<AdminCursorPage<LegalHold>> {
    const parameters = new URLSearchParams({ limit: String(limit) })
    if (state) parameters.set('state', state)
    if (cursor) parameters.set('cursor', cursor)
    return adminCursorPage(await this.client.request<AdminPageResponse<LegalHold>>(
      `/admin/retention/legal-holds?${parameters.toString()}`,
      { signal },
    ))
  }

  async listLegalHolds(state?: LegalHoldState) {
    return (await this.listLegalHoldPage({ state, limit: 100 })).items
  }

  getLegalHold(holdId: string, signal?: AbortSignal) {
    return this.client.request<LegalHold>(
      `/admin/retention/legal-holds/${encodeURIComponent(holdId)}`,
      { signal },
    )
  }

  placeLegalHold(
    dataClass: RetentionDataClass,
    scope: LegalHoldScope,
    scopeId: string | null,
    resourceType: LegalHoldResourceType | null,
    reason: string,
    idempotencyKey: string,
  ) {
    return this.client.request<LegalHold>('/admin/retention/legal-holds', {
      method: 'POST',
      idempotencyKey,
      body: JSON.stringify({
        data_class: dataClass,
        scope,
        scope_id: scopeId,
        resource_type: resourceType,
        reason,
      }),
    })
  }

  requestLegalHoldRelease(hold: LegalHold, reason: string, idempotencyKey: string) {
    return this.client.request<LegalHold>(
      `/admin/retention/legal-holds/${encodeURIComponent(hold.hold_id)}/release-requests`,
      {
        method: 'POST',
        ifMatch: quotedVersion(hold.version),
        idempotencyKey,
        body: JSON.stringify({ reason }),
      },
    )
  }

  decideLegalHoldRelease(
    hold: LegalHold,
    decision: GovernanceDecision,
    reason: string,
    idempotencyKey: string,
  ) {
    return this.client.request<LegalHold>(
      `/admin/retention/legal-holds/${encodeURIComponent(hold.hold_id)}/release-decisions`,
      {
        method: 'POST',
        ifMatch: quotedVersion(hold.version),
        idempotencyKey,
        body: JSON.stringify({ decision, reason }),
      },
    )
  }

  async listErasureRequestPage({
    state,
    cursor,
    limit = 25,
    signal,
  }: {
    state?: ErasureRequestState
    cursor?: string
    limit?: number
    signal?: AbortSignal
  } = {}): Promise<AdminCursorPage<ErasureRequest>> {
    const parameters = new URLSearchParams({ limit: String(limit) })
    if (state) parameters.set('state', state)
    if (cursor) parameters.set('cursor', cursor)
    return adminCursorPage(await this.client.request<AdminPageResponse<ErasureRequest>>(
      `/admin/retention/erasure-requests?${parameters.toString()}`,
      { signal },
    ))
  }

  async listErasureRequests(state?: ErasureRequestState) {
    return (await this.listErasureRequestPage({ state, limit: 100 })).items
  }

  async getErasureRequest(
    requestId: string,
    signal?: AbortSignal,
  ): Promise<VersionedErasureRequest> {
    const response = await this.client.requestWithMeta<ErasureRequest>(
      `/admin/retention/erasure-requests/${encodeURIComponent(requestId)}`,
      { signal },
    )
    const expected = quotedVersion(response.data.version)
    if (response.etag !== expected) {
      throw new Error('파기 요청 버전 ETag를 검증하지 못했습니다. 새로고침 후 다시 시도하세요.')
    }
    return { ...response.data, etag: response.etag }
  }

  getErasureExecutionEvidence(requestId: string, signal?: AbortSignal) {
    return this.client.request<RetentionExecutionEvidence>(
      `/admin/retention/erasure-requests/${encodeURIComponent(requestId)}/execution-evidence`,
      { signal },
    )
  }

  async requestErasure(
    targetType: ErasureTargetType,
    targetId: string,
    reason: string,
    reviewTtlSeconds: number,
    idempotencyKey: string,
  ) {
    const response = await this.client.requestWithMeta<ErasureRequest>(
      '/admin/retention/erasure-requests', {
      method: 'POST',
      idempotencyKey,
      body: JSON.stringify({
        target_type: targetType,
        target_id: targetId,
        reason,
        review_ttl_seconds: reviewTtlSeconds,
      }),
      },
    )
    return versionedErasure(response.data, response.etag)
  }

  async decideErasure(
    request: VersionedErasureRequest,
    decision: GovernanceDecision,
    reason: string,
    idempotencyKey: string,
  ) {
    const response = await this.client.requestWithMeta<ErasureRequest>(
      `/admin/retention/erasure-requests/${encodeURIComponent(request.erasure_request_id)}/decisions`,
      {
        method: 'POST',
        ifMatch: request.etag,
        idempotencyKey,
        body: JSON.stringify({ decision, reason }),
      },
    )
    return versionedErasure(response.data, response.etag)
  }
}

export function quotedVersion(version: number): string {
  if (!Number.isInteger(version) || version < 1) throw new Error('유효한 버전이 필요합니다.')
  return `"${version}"`
}

function versionedErasure(value: ErasureRequest, etag?: string): VersionedErasureRequest {
  const expected = quotedVersion(value.version)
  if (etag !== expected) {
    throw new Error('파기 요청 버전 ETag를 검증하지 못했습니다. 새로고침 후 다시 시도하세요.')
  }
  return { ...value, etag }
}

function adminCursorPage<T>(response: AdminPageResponse<T>): AdminCursorPage<T> {
  return {
    items: response.items,
    nextCursor: response.page.next_cursor,
    limit: response.page.limit,
  }
}
