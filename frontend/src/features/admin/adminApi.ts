import type { ApiClient } from '../../api/client'
import type {
  AdminAccessRequest,
  AdminAccessRequestState,
  AdminReadContext,
  ClassificationAccessPolicy,
  ClassificationAccessPolicyProposal,
  ClassificationAccessPolicyState,
  ErasureRequest,
  ErasureRequestState,
  ErasureTargetType,
  LegalHold,
  LegalHoldScope,
  LegalHoldState,
  InferenceProviderProfile,
  InferenceProviderProfileState,
  MembershipAccessDocument,
  MembershipAccessUpdateResult,
  RetentionDataClass,
  RetentionPolicy,
  RetentionPolicyState,
  RetentionRules,
  RestrictedSearchGrant,
  RestrictedSearchGrantProposal,
  RestrictedSearchGrantState,
  WorkspaceMembershipAccess,
  WorkspaceMembershipSummary,
  SystemDirectoryEntry,
  SystemAssigneeUpdate,
  SystemAssigneeUpdateResult,
  SystemConfigurationEntry,
} from '../../api/types'

type AdminApiClient = Pick<ApiClient, 'request' | 'requestWithMeta'>
type GovernanceDecision = 'APPROVED' | 'REJECTED'

export interface VersionedMembershipAccess extends WorkspaceMembershipAccess {
  etag: string
}

export interface VersionedErasureRequest extends ErasureRequest {
  etag: string
}

export class AdminApi {
  constructor(private readonly client: AdminApiClient) {}

  getContext() {
    return this.client.request<AdminReadContext>('/admin/me')
  }

  async listMemberships() {
    return (await this.client.request<{ items: WorkspaceMembershipSummary[] }>(
      '/admin/workspace-memberships?limit=100',
    )).items
  }

  async listSystems() {
    return (await this.client.request<{ items: SystemDirectoryEntry[] }>('/admin/systems?limit=100')).items
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

  async listSystemConfiguration() {
    return (await this.client.request<{ items: SystemConfigurationEntry[] }>('/admin/system-configuration')).items
  }

  updateSystemConfiguration(systemId: string, configurationYaml: string, version: number) {
    return this.client.request<SystemConfigurationEntry>(
      `/admin/system-configuration/${encodeURIComponent(systemId)}`,
      {
        method: 'PUT',
        ifMatch: quotedVersion(version),
        body: JSON.stringify({ configuration_yaml: configurationYaml }),
      },
    )
  }

  async getMembershipAccess(subjectId: string): Promise<VersionedMembershipAccess> {
    const response = await this.client.requestWithMeta<WorkspaceMembershipAccess>(
      `/admin/workspace-memberships/${encodeURIComponent(subjectId)}/access`,
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

  async listFallbackRequests(state?: AdminAccessRequestState) {
    const query = state ? `?state=${state}&limit=100` : '?limit=100'
    return (await this.client.request<{ items: AdminAccessRequest[] }>(
      `/admin/fallback/workspace-membership-access-requests${query}`,
    )).items
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

  async listRetentionPolicies(state?: RetentionPolicyState) {
    const query = state ? `?state=${state}&limit=100` : '?limit=100'
    return (await this.client.request<{ items: RetentionPolicy[] }>(
      `/admin/retention/policies${query}`,
    )).items
  }

  proposeRetentionPolicy(rules: RetentionRules, reason: string, idempotencyKey: string) {
    return this.client.request<RetentionPolicy>('/admin/retention/policies', {
      method: 'POST',
      idempotencyKey,
      body: JSON.stringify({ rules, reason }),
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

  async listClassificationAccessPolicies(state?: ClassificationAccessPolicyState) {
    const query = state ? `?state=${state}&limit=100` : '?limit=100'
    return (await this.client.request<{ items: ClassificationAccessPolicy[] }>(
      `/admin/classification-access/policies${query}`,
    )).items
  }

  getCurrentClassificationAccessPolicy() {
    return this.client.request<ClassificationAccessPolicy | null>(
      '/admin/classification-access/policies/current',
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

  async listInferenceProviderProfiles(state?: InferenceProviderProfileState) {
    const query = state ? `?state=${state}&limit=100` : '?limit=100'
    return (await this.client.request<{ items: InferenceProviderProfile[] }>(
      `/admin/inference/provider-profiles${query}`,
    )).items
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

  async listRestrictedSearchGrants(
    state?: RestrictedSearchGrantState,
    subjectId?: string,
  ) {
    const query = new URLSearchParams({ limit: '100' })
    if (state) query.set('state', state)
    if (subjectId) query.set('subject_id', subjectId)
    return (await this.client.request<{ items: RestrictedSearchGrant[] }>(
      `/admin/classification-access/restricted-search-grants?${query.toString()}`,
    )).items
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

  async listLegalHolds(state?: LegalHoldState) {
    const query = state ? `?state=${state}&limit=100` : '?limit=100'
    return (await this.client.request<{ items: LegalHold[] }>(
      `/admin/retention/legal-holds${query}`,
    )).items
  }

  placeLegalHold(
    dataClass: RetentionDataClass,
    scope: LegalHoldScope,
    scopeId: string | null,
    reason: string,
    idempotencyKey: string,
  ) {
    return this.client.request<LegalHold>('/admin/retention/legal-holds', {
      method: 'POST',
      idempotencyKey,
      body: JSON.stringify({ data_class: dataClass, scope, scope_id: scopeId, reason }),
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

  async listErasureRequests(state?: ErasureRequestState) {
    const query = state ? `?state=${state}&limit=100` : '?limit=100'
    return (await this.client.request<{ items: ErasureRequest[] }>(
      `/admin/retention/erasure-requests${query}`,
    )).items
  }

  async getErasureRequest(requestId: string): Promise<VersionedErasureRequest> {
    const response = await this.client.requestWithMeta<ErasureRequest>(
      `/admin/retention/erasure-requests/${encodeURIComponent(requestId)}`,
    )
    const expected = quotedVersion(response.data.version)
    if (response.etag !== expected) {
      throw new Error('파기 요청 버전 ETag를 검증하지 못했습니다. 새로고침 후 다시 시도하세요.')
    }
    return { ...response.data, etag: response.etag }
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
