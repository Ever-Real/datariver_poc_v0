export interface Capability {
  name: string
  state: string
  observed_at: string
  latency_ms?: number
  detail_code?: string
}

export interface ExternalSystemLink {
  system_id: 'datahub' | 'airflow' | 'grafana' | 'prometheus' | 'graph'
  label: string
  url: string
}

export interface OperationsSummary {
  observed_at: string
  jobs_by_state: Record<string, number>
  uploads_by_state: Record<string, number>
  changes_by_state: Record<string, number>
  unpublished_outbox_events: number
  dead_lettered_outbox_events: number
  oldest_unpublished_age_seconds?: number
  retention_automation_state: 'DISABLED_NOT_READY'
}

export interface CatalogAsset {
  id: string
  external_urn: string
  asset_type: string
  name: string
  description?: string
  platform?: string
  classification: string
  lifecycle: string
  observed_at: string
  stale_at?: string
}

export interface CatalogSearch {
  items: CatalogAsset[]
  page: { next_cursor?: string; limit: number }
  meta: { observed_at: string; stale_at?: string }
}

export interface UploadRecord {
  id: string
  display_name: string
  state: string
  size_bytes: number
  content_type: string
  sha256: string
  classification: string
  expires_at: string
  version: number
  recommended_part_size_bytes: number
  validation_summary: Record<string, unknown>
  last_error_code: string | null
}

export interface ChangeRequestRecord {
  id: string
  number: string
  request_type: string
  title: string
  description: string
  state: string
  requester_id: string
  classification: string
  version: number
  items: Array<{
    id: string
    target_type: string
    target_ref: string
    aspect_name: string
    operation: string
    before_hash?: string
    after_hash?: string
  }>
  approvals: Array<{
    id: string
    stage: string
    decision: string
    actor_id: string
    reason: string
    occurred_at: string
  }>
  transitions: Array<{
    id: string
    from_state: string
    to_state: string
    actor_id: string
    reason: string
    occurred_at: string
  }>
}

export interface KnowledgeGraph {
  id: string
  slug: string
  name: string
  graph_type: string
  status: string
  classification: string
  active_release_id?: string
  version: number
}

export interface ChatResponse {
  session_id: string
  request_message_id: string
  response_message_id: string
  answer: string
  evidence: Array<{
    chunk_id: string
    resource_id: string
    classification: 'PUBLIC' | 'INTERNAL' | 'CONFIDENTIAL' | 'RESTRICTED'
    system_id: string | null
    domain_id: string | null
    owner_department_id: string | null
    name: string
    source_type: string
    source_locator: string
    source_version: string
    content_hash: string
    effective_from: string
    effective_until: string | null
    extraction_method: string
  }>
}

export interface ApiProductVersion {
  id: string
  product_id: string
  graph_id: string
  release_id: string
  version_no: number
  surface: 'SNAPSHOT' | 'NEIGHBORS' | 'CHAT'
  contract: { scopes?: string[]; response_schema?: Record<string, unknown>; query_template?: string }
  maximum_hops: number
  maximum_nodes: number
  timeout_ms: number
  state: string
  published_at?: string
}

export interface ApiProduct {
  id: string
  slug: string
  name: string
  description: string
  graph_id: string
  classification: string
  owner_id: string
  state: string
  current_version_id?: string
  version: number
  versions: ApiProductVersion[]
}

export interface ConsumerGrant {
  id: string
  product_id: string
  product_version_id: string
  consumer_client_id: string
  scopes: string[]
  maximum_classification: string
  requests_per_minute: number
  monthly_quota: number
  valid_from: string
  expires_at: string
  state: string
  version: number
}

export type Classification = 'PUBLIC' | 'INTERNAL' | 'CONFIDENTIAL' | 'RESTRICTED'

export type AdminOperation =
  | 'MEMBERSHIP_ACCESS_READ'
  | 'MEMBERSHIP_ACCESS_UPDATE'
  | 'FALLBACK_REQUEST_READ'
  | 'FALLBACK_REQUEST_CREATE'
  | 'FALLBACK_REQUEST_DECIDE'
  | 'FALLBACK_REQUEST_CONSUME'
  | 'CLASSIFICATION_POLICY_READ'
  | 'CLASSIFICATION_POLICY_PROPOSE'
  | 'CLASSIFICATION_POLICY_DECIDE'
  | 'INFERENCE_PROVIDER_PROFILE_READ'
  | 'INFERENCE_PROVIDER_PROFILE_DECIDE'
  | 'INFERENCE_PROVIDER_PROFILE_REVOKE'
  | 'RESTRICTED_SEARCH_GRANT_READ'
  | 'RESTRICTED_SEARCH_GRANT_PROPOSE'
  | 'RESTRICTED_SEARCH_GRANT_DECIDE'
  | 'RESTRICTED_SEARCH_GRANT_REVOKE'
  | 'RETENTION_POLICY_READ'
  | 'RETENTION_POLICY_MANAGE'
  | 'LEGAL_HOLD_READ'
  | 'LEGAL_HOLD_PLACE'
  | 'LEGAL_HOLD_RELEASE'
  | 'ERASURE_READ'
  | 'ERASURE_REQUEST'
  | 'ERASURE_APPROVE'

export interface MembershipAccessDocument {
  active: boolean
  clearance: Classification
  groups: string[]
  allowed_actions: string[]
  denied_actions: string[]
  allowed_system_ids: string[]
  allowed_domain_ids: string[]
}

export interface WorkspaceMembershipSummary {
  subject_id: string
  display_name: string
  subject_active: boolean
  membership_active: boolean
  department_id: string | null
  job_function: string | null
  clearance: Classification
  membership_version: number
}

export interface WorkspaceMembershipAccess {
  subject_id: string
  display_name: string
  subject_active: boolean
  department_id: string | null
  job_function: string | null
  membership_version: number
  access: MembershipAccessDocument
}

export interface AdminReadContext {
  subject_id: string
  workspace_id: string
  display_name: string
  authentication_assurance: 'PASSWORD_REAUTH' | 'HARDWARE_WEBAUTHN'
  fallback_enabled: boolean
  allowed_operations: AdminOperation[]
  action_vocabulary: string[]
}

export type AdminAccessRequestState = 'PENDING' | 'APPROVED' | 'REJECTED' | 'CONSUMED'

export interface AdminAccessRequest {
  id: string
  workspace_id: string
  requester_id: string
  request_reason: string
  command: {
    command_type: 'WORKSPACE_MEMBERSHIP_ACCESS_UPDATE_V1'
    workspace_id: string
    target_subject_id: string
    expected_membership_version: number
    access: MembershipAccessDocument
  }
  payload_hash: string
  state: AdminAccessRequestState
  version: number
  expires_at: string
  checker_id: string | null
  consumed_by: string | null
  consumed_at: string | null
  approvals: Array<{
    id: string
    decision: 'APPROVED' | 'REJECTED'
    actor_id: string
    reason: string
    payload_hash: string
    request_version: number
    occurred_at: string
  }>
}

export interface MembershipAccessUpdateResult {
  target_subject_id: string
  membership_version: number
  payload_hash: string
}

export interface RetentionRules {
  completed_operation_days: number
  chat_content_days: number
  audit_online_months: number
  immutable_archive_years: number
}

export type RetentionPolicyState = 'DRAFT' | 'ACTIVE' | 'REJECTED' | 'SUPERSEDED'

export interface RetentionPolicy {
  policy_id: string
  policy_number: number
  rules: RetentionRules
  payload_hash: string
  requester_id: string
  request_reason: string
  state: RetentionPolicyState
  checker_id: string | null
  decision_reason: string | null
  decided_at: string | null
  version: number
  partition_automation_state: string
  deletion_automation_state: string
}

export type LegalHoldState = 'ACTIVE' | 'RELEASE_REQUESTED' | 'RELEASE_REJECTED' | 'RELEASED'
export type RetentionDataClass =
  | 'COMPLETED_OPERATIONS'
  | 'CHAT_CONTENT'
  | 'AUDIT_EVIDENCE'
  | 'OBJECT_DATA'
export type LegalHoldScope = 'WORKSPACE' | 'SUBJECT' | 'RESOURCE'

export interface LegalHold {
  hold_id: string
  data_class: RetentionDataClass
  scope: LegalHoldScope
  scope_id: string | null
  reason: string
  payload_hash: string
  created_by: string
  state: LegalHoldState
  release_requested_by: string | null
  release_request_reason: string | null
  release_checker_id: string | null
  release_decision_reason: string | null
  released_at: string | null
  version: number
  deletion_effect: string
  actions: Array<{
    action_id: string
    action: 'PLACED' | 'RELEASE_REQUESTED' | 'RELEASE_APPROVED' | 'RELEASE_REJECTED'
    actor_id: string
    reason: string
    occurred_at: string
    hold_version: number
    payload_hash: string
  }>
}

export type ErasureTargetType = 'SUBJECT_DATA' | 'CHAT_SESSION' | 'UPLOAD_OBJECT'
export type ErasureRequestState = 'PENDING' | 'APPROVED' | 'REJECTED'

export interface ErasureRequest {
  erasure_request_id: string
  target_type: ErasureTargetType
  target_id: string
  target_version: number
  target_owner_id: string | null
  classification: Classification
  retention_policy_id: string
  retention_policy_hash: string
  requester_id: string
  request_reason: string
  request_policy_decision_id: string
  payload_hash: string
  expires_at: string
  state: ErasureRequestState
  checker_id: string | null
  decision_reason: string | null
  decision_policy_decision_id: string | null
  decided_at: string | null
  version: number
  execution_state: 'DISABLED_NOT_READY'
  approvals: Array<{
    approval_id: string
    decision: 'APPROVED' | 'REJECTED'
    actor_id: string
    reason: string
    policy_decision_id: string
    payload_hash: string
    request_version: number
    occurred_at: string
  }>
}

export type ClassificationSearchMode = 'ABAC' | 'DENY' | 'EXPLICIT_GRANT_ONLY'
export type ClassificationChatMode =
  | 'DENY'
  | 'INTERNAL_APPROVED_ONLY'
  | 'APPROVED_PROVIDER_ONLY'
export type ClassificationAccessPolicyState = 'PROPOSED' | 'ACTIVE' | 'REJECTED' | 'SUPERSEDED'

export interface ClassificationAccessRule {
  classification: Classification
  search_mode: ClassificationSearchMode
  chat_mode: ClassificationChatMode
  provider_profile_version_id: string | null
}

export interface ClassificationAccessPolicy {
  policy_id: string
  policy_number: number
  required_jurisdiction: string
  restricted_search_grant_maximum_days: number
  rules: ClassificationAccessRule[]
  payload_hash: string
  requester_id: string
  request_reason: string
  state: ClassificationAccessPolicyState
  checker_id: string | null
  decision_reason: string | null
  decided_at: string | null
  superseded_by: string | null
  supersede_reason: string | null
  superseded_at: string | null
  version: number
}

export interface ProviderAttestationSummary {
  fingerprint: string
  observed_at: string
  expires_at: string
}

export type InferenceProviderKind = 'INTERNAL' | 'EXTERNAL'
export type InferenceProviderProfileState = 'PROPOSED' | 'APPROVED' | 'REJECTED' | 'REVOKED'

export interface InferenceProviderProfile {
  provider_profile_version_id: string
  profile_key: string
  profile_version: number
  kind: InferenceProviderKind
  provider_identity: string
  model_identity: string
  deployment_identity: string
  jurisdiction: string
  region: string
  maximum_classification: Exclude<Classification, 'RESTRICTED'>
  residency_attestation: ProviderAttestationSummary
  zero_retention_attestation: ProviderAttestationSummary
  payload_hash: string
  maker_id: string
  proposal_reason: string
  proposed_at: string
  state: InferenceProviderProfileState
  checker_id: string | null
  decision_reason: string | null
  decided_at: string | null
  revoked_by: string | null
  revocation_reason: string | null
  revoked_at: string | null
  version: number
}

export type RestrictedSearchScope = 'RESOURCE' | 'SYSTEM' | 'DOMAIN'
export type RestrictedSearchGrantState = 'PENDING' | 'ACTIVE' | 'REJECTED' | 'REVOKED'

export interface RestrictedSearchGrant {
  grant_id: string
  classification_policy_id: string
  classification_policy_hash: string
  subject_id: string
  scope: RestrictedSearchScope
  scope_id: string
  purpose: string
  valid_from: string
  expires_at: string
  payload_hash: string
  requester_id: string
  request_reason: string
  state: RestrictedSearchGrantState
  checker_id: string | null
  decision_reason: string | null
  decided_at: string | null
  revoked_by: string | null
  revocation_reason: string | null
  revoked_at: string | null
  version: number
}

export interface ClassificationAccessPolicyProposal {
  required_jurisdiction: string
  restricted_search_grant_maximum_days: number
  rules: ClassificationAccessRule[]
  reason: string
}

export interface RestrictedSearchGrantProposal {
  subject_id: string
  scope: RestrictedSearchScope
  scope_id: string
  purpose: string
  valid_from: string
  expires_at: string
  reason: string
}
