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

export interface GrafanaEmbed {
  state: 'AVAILABLE' | 'DISABLED' | 'NOT_CONFIGURED'
  url?: string
}

export interface CapabilitiesResponse {
  items: Capability[]
  external_system_links: ExternalSystemLink[]
  grafana_embed: GrafanaEmbed
  deployment_tier: 'SINGLE_NODE_PILOT' | 'HA_CANDIDATE' | 'HA_ACCEPTED'
}

export interface AuthenticatedProfile {
  subject: string
  display_name: string
  email?: string
  roles: string[]
  authentication_assurance: 'UNKNOWN' | 'PASSWORD' | 'PASSWORD_REAUTH' | 'OTHER_MFA' | 'HARDWARE_WEBAUTHN'
  authentication_time?: string
  default_workspace_id?: string
  workspace_selection_enabled?: boolean
  hardware_webauthn_enabled?: boolean
  password_change_supported?: boolean
}

export interface CatalogExportCapability {
  enabled: boolean
}

export interface OperationsSummary {
  observed_at: string
  jobs_by_state: Record<string, number>
  uploads_by_state: Record<string, number>
  changes_by_state: Record<string, number>
  catalog_asset_count: number
  catalog_described_asset_count: number
  catalog_schema_metrics: CatalogSchemaMetric[]
  catalog_schema_metrics_truncated: boolean
  unpublished_outbox_events: number
  dead_lettered_outbox_events: number
  oldest_unpublished_age_seconds?: number
  retention_automation_state: 'DISABLED_NOT_READY'
}

export interface CatalogSchemaMetric {
  platform?: string
  database_name?: string
  schema_name?: string
  asset_count: number
  described_asset_count: number
}

export interface CatalogAsset {
  id: string
  external_urn: string
  asset_type: string
  name: string
  description?: string
  platform?: string
  database_name?: string
  schema_name?: string
  owner?: string
  domain?: string
  tags?: string[]
  terms?: string[]
  created_at?: string
  classification: string
  lifecycle: string
  observed_at: string
  stale_at?: string
  matches: CatalogMatchFragment[]
}

export interface CatalogMatchFragment {
  field: 'NAME' | 'DESCRIPTION'
  text: string
  matched_terms: string[]
}

export interface CatalogPolicyMeta {
  observed_at?: string
  stale_at?: string
  projection_version: number
  policy_version: string
  classification_policy_version?: number
  authorization_generation?: number
}

export interface CatalogSearch {
  items: CatalogAsset[]
  page: { next_cursor?: string; limit: number }
  total: number
  meta: CatalogPolicyMeta
  match_mode: 'ALL'
}

export interface CatalogFacets {
  asset_types: Array<{ value?: string; count: number }>
  platforms: Array<{ value?: string; count: number }>
  classifications: Array<{ value?: string; count: number }>
  databases: Array<{ value?: string; count: number }>
  schemas: Array<{ value?: string; count: number }>
  domains: Array<{ value?: string; count: number }>
  lifecycles: Array<{ value?: string; count: number }>
  meta: CatalogPolicyMeta
}

export interface CatalogSuggestion {
  id: string
  name: string
  asset_type: string
  platform?: string
}

export interface CatalogSuggestions {
  items: CatalogSuggestion[]
  meta: CatalogPolicyMeta
}

export interface CatalogVocabulary {
  items: string[]
  meta: CatalogPolicyMeta
}

export interface CatalogAssetDetail extends CatalogAsset {
  ownership: Array<Record<string, unknown>>
  glossary_terms: Array<Record<string, unknown>>
  tags: string[]
  schema_fields: Array<Record<string, unknown>>
  schema_fields_total: number
  schema_fields_available: number
  schema_fields_truncated: boolean
  schema_fields_total_exact: boolean
  schema_fields_offset: number
  schema_fields_limit: number
  schema_fields_has_more: boolean
  quality: Record<string, unknown>
  projection_source_version: string
  source_version: string
}

export interface ManualMetadataColumn {
  field_path: string
  description: string
  tags: string[]
  terms: string[]
}

export interface ManualMetadataSubmission {
  id: string
  state: 'QUEUED' | 'APPLYING' | 'APPLIED' | 'FAILED'
  serial_number: number
  row_count: number
  source_version: string
  created_at: string
  version: number
}

export interface CatalogDescriptionPreview {
  asset_id: string
  target_ref: string
  aspect_name: 'datasetProperties'
  current_description: string | null
  proposed_description: string
  before_hash: string
  after_hash: string
  preview_etag: string
  source_version: string
  observed_at: string
}

export interface CatalogColumnDescriptionPreview {
  asset_id: string
  target_ref: string
  aspect_name: 'schemaMetadata'
  field_path: string
  current_description: string | null
  proposed_description: string
  before_hash: string
  after_hash: string
  preview_etag: string
  source_version: string
  observed_at: string
}

export type CatalogControlledMetadataAspect = 'domains' | 'globalTags' | 'glossaryTerms'

export interface CatalogControlledMetadataPreview {
  asset_id: string
  target_ref: string
  aspect_name: CatalogControlledMetadataAspect
  current_refs: string[]
  proposed_refs: string[]
  before_hash: string
  after_hash: string
  preview_etag: string
  source_version: string
  observed_at: string
}

export interface CatalogTreeNode {
  id: string
  kind: 'PLATFORM' | 'DATABASE' | 'SCHEMA' | 'ASSET'
  label: string
  asset_count: number
  has_children: boolean
  platform?: string
  database_name?: string
  schema_name?: string
  asset?: CatalogAsset
}

export interface CatalogTreePage {
  items: CatalogTreeNode[]
  page: { next_cursor?: string; limit: number }
  meta: CatalogPolicyMeta
}

export interface CatalogLineage {
  center_asset_id: string
  nodes: CatalogAsset[]
  edges: Array<{ source_asset_id: string; target_asset_id: string }>
  direction: 'UPSTREAM' | 'DOWNSTREAM' | 'BOTH'
  depth: number
  truncated: boolean
  meta: CatalogPolicyMeta
}

export interface CatalogDataHubEmbed {
  state: 'AVAILABLE' | 'UNAVAILABLE'
  url?: string
  reason_code?: 'DISABLED' | 'NOT_CONFIGURED'
}

export interface CatalogExportCreateRequest {
  q: string
  asset_type?: string
  platform?: string
  database_name?: string
  schema_name?: string
  domain?: string
  search_fields?: string
  classification?: Classification
  lifecycle?: 'ACTIVE'
  sort: 'NAME_ASC'
  format: 'CSV' | 'XLSX'
}

export interface CatalogExportCreateResponse {
  export_id: string
  job_id: string
  state: string
}

export interface CatalogExportStatus {
  export_id: string
  job_id: string
  state: string
  last_error_code: string | null
  row_count: number | null
  size_bytes: number | null
  content_sha256: string | null
  display_name: string
  created_at: string
  completed_at: string | null
  access_until: string
}

export interface CatalogExportDownload {
  url: string
  expires_seconds: number
}

export type UploadContentProfile =
  | 'FORMAT_ONLY_V1'
  | 'DATASET_DESCRIPTION_CSV_V1'
  | 'DATASET_DESCRIPTION_XLSX_V1'

export type UploadPreparationState =
  | 'QUEUED'
  | 'PREPARING'
  | 'READY'
  | 'FAILED'
  | 'CANCELLED'
  | 'STALE'

export interface UploadRecord {
  id: string
  display_name: string
  state: string
  size_bytes: number
  content_type: string
  sha256: string
  classification: string
  content_profile: UploadContentProfile
  expires_at: string
  version: number
  recommended_part_size_bytes: number
  validation_summary: Record<string, unknown>
  last_error_code: string | null
}

export interface UploadPreparation {
  id: string
  upload_id: string
  content_profile: 'DATASET_DESCRIPTION_CSV_V1' | 'DATASET_DESCRIPTION_XLSX_V1'
  source_manifest_version: number
  source_sha256: string
  configuration_hash: string
  state: UploadPreparationState
  attempts: number
  rows_processed: number
  total_rows: number | null
  last_error_code: string | null
  created_at: string
  updated_at: string
  version: number
}

export interface UploadRegistrationCandidate {
  id: string
  ordinal: number
  evidence_version: 'DATASET_DESCRIPTION_CANDIDATE_V2'
  candidate_kind: 'DATASET_DESCRIPTION_UPDATE'
  proposed_description: string
  submitted_identity: {
    platform: string
    database_name: string
    schema_name: string
    table_name: string
    identity_hash: string
  }
  candidate_hash: string
  created_at: string
  current_target: {
    id: string
    asset_type: 'DATASET'
    name: string
    platform: string
    database_name: string
    schema_name: string
    classification: 'PUBLIC' | 'INTERNAL' | 'CONFIDENTIAL' | 'RESTRICTED'
    lifecycle: 'ACTIVE'
    source_version: string
    observed_at: string
  }
}

export interface UploadRegistrationCandidatePage {
  items: UploadRegistrationCandidate[]
  page: { next_cursor?: string; limit: number }
  receipt: {
    id: string
    preparation_id: string
    manifest_version: number
    source_sha256: string
    content_profile: 'DATASET_DESCRIPTION_CSV_V1' | 'DATASET_DESCRIPTION_XLSX_V1'
    parser_version: string
    scanner_version: string
    schema_version: string
    configuration_hash: string
    candidate_root_hash: string
    receipt_hash: string
    observed_at: string
    created_at: string
  }
  meta: {
    projection_version: number
    policy_version: string
    classification_policy_version: number | null
    authorization_generation: number | null
  }
}

export type ChangeRequestState =
  | 'REGISTERED'
  | 'IN_REVIEW'
  | 'TESTING'
  | 'FINAL_REVIEW'
  | 'APPLY_QUEUED'
  | 'APPLYING'
  | 'APPLIED'
  | 'APPLY_FAILED'
  | 'COMPLETED'
  | 'CHANGES_REQUESTED'
  | 'REJECTED'
  | 'CANCELLED'

export interface ChangeRequestRecord {
  id: string
  number: string
  request_type: string
  title: string
  description: string
  state: ChangeRequestState
  requester_id: string
  requester_department_id: string | null
  current_round_id: string
  current_round_number: number
  created_at: string
  requested_due_date: string | null
  priority: 'LOW' | 'NORMAL' | 'HIGH' | 'CRITICAL' | null
  urgency: 'NORMAL' | 'URGENT' | 'EMERGENCY' | null
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
    after_document?: Record<string, unknown>
    target_asset_id: string | null
    target_asset_type: string | null
    target_system_id: string | null
    target_domain_id: string | null
    target_owner_department_id: string | null
    target_classification: string | null
    target_lifecycle: string | null
    target_source_version: string | null
    target_observed_at: string | null
    target_binding_hash: string | null
    routing_system_id: string | null
  }>
  approvals: Array<{
    id: string
    stage: string
    decision: string
    actor_id: string
    reason: string
    occurred_at: string
    round_id: string
    authorities: Array<{
      kind: 'SYSTEM_DEVELOPER' | 'SYSTEM_DATA_STEWARD' | 'GLOBAL_ADMIN'
      system_id: string | null
    }>
  }>
  transitions: Array<{
    id: string
    from_state: ChangeRequestState
    to_state: ChangeRequestState
    actor_id: string
    reason: string
    occurred_at: string
    round_id: string
  }>
  rounds: Array<{
    id: string
    round_number: number
    submitted_by: string
    submitted_at: string
    closed_at: string | null
    evidence_hash: string
  }>
  test_runs: Array<{
    id: string
    round_id: string
    system_id: string
    attachment_id: string
    state: 'PASSED' | 'FAILED'
    plan_hash: string
    result_hash: string
    bounded_summary: Record<string, unknown>
    recorded_by: string
    occurred_at: string
  }>
}

export interface ChangeRequestAttachment {
  id: string
  kind: 'REQUEST' | 'TEST'
  round_id: string
  original_name: string
  serial_number: number
  content_type: string
  size_bytes: number
  content_sha256: string
  created_at: string
}

export interface ChangeRequestAttachmentList {
  items: ChangeRequestAttachment[]
}

export interface ChangeRequestSchemaOverview {
  platform: string
  database_name: string
  schema_name: string
  system_id: string | null
  system_code: string | null
  system_name: string | null
  assignees: Array<{
    subject_id: string
    display_name: string
    responsibility: 'DEVELOPER' | 'DATA_STEWARD'
    priority: number
  }>
  pending_count: number
  total_count: number
  received_count: number
  recheck_count: number
  testing_count: number
  final_review_count: number
  completed_count: number
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

export interface KnowledgeRelease {
  id: string
  graph_id: string
  release_no: number
  ontology_version_id: string
  content_hash: string
  node_count: number
  edge_count: number
  published_at: string
}

export interface KnowledgeProvenance {
  source_ref: string
  source_locator: string
  source_version: string
  method: string
  confidence: number
}

export interface KnowledgeGraphNode {
  id: string
  entity_type: string
  properties: Record<string, unknown>
  classification: number
  provenance: KnowledgeProvenance[]
}

export interface KnowledgeGraphEdge {
  id: string
  source_id: string
  target_id: string
  edge_type: string
  properties: Record<string, unknown>
  classification: number
  provenance: KnowledgeProvenance[]
}

export interface KnowledgeSnapshot {
  release: KnowledgeRelease
  nodes: KnowledgeGraphNode[]
  edges: KnowledgeGraphEdge[]
  filtered: boolean
}

export interface KnowledgeNeighborAnalysis {
  release: KnowledgeRelease
  nodes: KnowledgeGraphNode[]
  edges: KnowledgeGraphEdge[]
  truncated: boolean
}

export interface KnowledgeValidation {
  id: string
  severity: string
  code: string
  location: string
  message: string
  validator: string
  validator_version: string
}

export interface KnowledgeChangeOperationCreate {
  sequence: number
  operation: 'UPSERT' | 'DELETE'
  entity_kind: 'NODE' | 'EDGE'
  stable_entity_id: string
  document: Record<string, unknown>
  provenance: KnowledgeProvenance[]
  confidence: number
}

export interface KnowledgeChangeSet {
  id: string
  graph_id: string
  base_release_id: string | null
  ontology_version_id: string
  title: string
  state: string
  author_id: string
  reviewed_by: string | null
  review_reason: string | null
  published_release_id: string | null
  version: number
  created_at: string
  updated_at: string
  operations: Array<KnowledgeChangeOperationCreate & {
    id: string
  }>
  validations: KnowledgeValidation[]
}

export interface KnowledgeChangeSetPublish {
  changeset: KnowledgeChangeSet
  release: KnowledgeRelease
}

export interface KnowledgeSourceAnalyzeResult {
  source_snapshot_id: string
  changeset_id: string
  page_count: number
  proposed_node_count: number
  proposed_edge_count: number
  evidence_hash: string
  embedding_model: string
  extraction_model: string
}

export interface KnowledgeProjectionReceipt {
  deployment_id: string
  release_id: string
  release_hash: string
  node_count: number
  edge_count: number
  state: 'SHADOW_VERIFIED'
}

export interface ChatResponse {
  session_id: string
  request_message_id: string
  response_message_id: string
  answer: string
  persistence: 'PERSISTED' | 'EPHEMERAL_NO_STORE'
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
  | 'IDENTITY_USER_PROVISION'
  | 'MEMBERSHIP_ACCESS_READ'
  | 'MEMBERSHIP_ACCESS_UPDATE'
  | 'MEMBERSHIP_RENEWAL_READ'
  | 'MEMBERSHIP_RENEWAL_DECIDE'
  | 'SYSTEM_ASSIGNMENT_UPDATE'
  | 'SYSTEM_CONFIGURATION_READ'
  | 'SYSTEM_CONFIGURATION_UPDATE'
  | 'SYSTEM_CONFIGURATION_ACTIVATE'
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
  email: string | null
  last_login_at: string | null
  last_login_ip: string | null
  owned_table_count: number
  change_request_count: number
  joined_at?: string | null
  access_expires_at: string | null
  renewal_eligible_at: string | null
  access_expired: boolean
  renewal_request_eligible: boolean
  pending_renewal_request_id: string | null
  subject_active: boolean
  membership_active: boolean
  department_id: string | null
  job_function: string | null
  clearance: Classification
  membership_version: number
}

export interface MembershipRenewalRequest {
  id: string
  workspace_id: string
  target_subject_id: string
  requester_id: string
  requester_display_name: string
  reason: string
  current_expires_at: string
  requested_expires_at: string
  state: 'PENDING' | 'APPROVED' | 'REJECTED'
  version: number
  created_at: string
  checker_id: string | null
  checker_display_name: string | null
  decision_reason: string | null
  decided_at: string | null
  membership_version: number | null
}

export interface WorkspaceMembershipAccess {
  subject_id: string
  display_name: string
  subject_active: boolean
  department_id: string | null
  job_function: string | null
  membership_version: number
  access: MembershipAccessDocument
  role_assignment: MembershipRoleAssignmentEvidence
}

export type DataAccessLevel = 'NO_ACCESS' | 'PARTIAL_ACCESS' | 'FULL_ACCESS'
export type PartialAccessTreatment = 'MASK' | 'REDACT' | 'TOKENIZE'
export type DataProcessingPurpose =
  | 'METADATA_READ'
  | 'DATA_READ'
  | 'EXPORT'
  | 'ANALYTICS'
  | 'MODEL_TRAINING'

export interface AccessRoleDataRule {
  classification: Classification
  access_level: DataAccessLevel
  partial_treatment: PartialAccessTreatment | null
  allowed_residency_regions: string[]
  allowed_processing_purposes: DataProcessingPurpose[]
}

export interface MembershipRoleAssignmentEvidence {
  status: 'VERIFIED' | 'MANUAL' | 'LEGACY_UNVERIFIED' | 'EVIDENCE_MISMATCH'
  role_id: string | null
  role_version: number | null
  assignment_version: number | null
  membership_version: number | null
  access_payload_hash: string | null
  assigned_by: string | null
  updated_at: string | null
  legacy_markers: string[]
}

export interface AccessRole {
  id: string
  role_key: string
  name: string
  description: string
  clearance: Classification
  groups: string[]
  allowed_actions: string[]
  denied_actions: string[]
  allowed_system_ids: string[]
  allowed_domain_ids: string[]
  data_access_rules: AccessRoleDataRule[]
  active: boolean
  assigned_count: number
  version: number
  created_at: string
  updated_at: string
}

export interface AccessRoleWrite {
  role_key: string
  name: string
  description: string
  clearance: Classification
  groups: string[]
  allowed_actions: string[]
  denied_actions: string[]
  allowed_system_ids: string[]
  allowed_domain_ids: string[]
  data_access_rules: AccessRoleDataRule[]
  active: boolean
}

export interface MembershipRoleAssignmentResult {
  subject_id: string
  role_id: string | null
  membership_version: number
  payload_hash: string
}

export interface IdentityUserProvisionInput {
  username: string
  email: string
  first_name: string
  last_name: string
  department_id: string | null
  job_function: string | null
  role_id: string | null
  temporary_password: string
}

export interface IdentityUserProvisionResult {
  subject_id: string
  username: string
  display_name: string
  email: string
  workspace_id: string
  role_id: string | null
  access_expires_at: string
  temporary_password_required: boolean
}

export interface SystemDirectoryEntry {
  system_id: string
  code: string
  name: string
  description: string
  active: boolean
  version: number
  assignee_count: number
  assignees: SystemDirectoryAssignee[]
}

export interface SystemDirectoryAssignee {
  subject_id: string
  display_name: string
  responsibility: 'DEVELOPER' | 'DATA_STEWARD'
  priority: number
  active: boolean
}

export interface SystemAssigneeUpdate {
  subject_id: string
  responsibility: SystemDirectoryAssignee['responsibility']
  priority: number
}

export interface SystemAssigneeKey {
  subject_id: string
  responsibility: SystemDirectoryAssignee['responsibility']
}

export interface SystemAssigneePage {
  system_version: number
  items: SystemDirectoryAssignee[]
  page: { next_cursor: string | null; limit: number }
}

export interface SystemAssigneeUpdateResult {
  system_id: string
  system_version: number
  payload_hash: string
}

export interface SystemConfigurationEntry {
  system_id: 'POSTGRESQL' | 'OIDC_IDENTITY' | 'DATAHUB_GMS' | 'DATAHUB_FRONTEND' | 'AIRFLOW' | 'REDIS_CACHE' | 'REDIS_DELIVERY' | 'S3_STORAGE' | 'LLM_CHAT_MODEL' | 'LLM_EMBEDDING' | 'LLM_RERANKER' | 'NEO4J' | 'PROMETHEUS' | 'GRAFANA_DASHBOARD'
  label: string
  category: 'PLATFORM' | 'CATALOG' | 'ORCHESTRATION' | 'STORAGE' | 'AI' | 'OBSERVABILITY'
  requirement: 'BOOTSTRAP_REQUIRED' | 'CORE_CONNECTOR' | 'FEATURE_CONNECTOR'
  description: string
  connection_requirements: Array<{
    key: string
    label: string
    required: boolean
    secret: boolean
    example: string | null
  }>
  state: 'CONFIGURED' | 'NOT_CONFIGURED' | 'GOVERNED_PROFILE_REQUIRED'
  management_plane: 'DEVELOPMENT_DATABASE' | 'DEPLOYMENT' | 'GOVERNED_PROVIDER_PROFILE'
  secret_reference_configured: boolean
  embedding_state: 'NOT_APPLICABLE' | 'AVAILABLE' | 'DISABLED' | 'NOT_CONFIGURED'
  configuration_yaml: string
  template_yaml: string
  display_yaml: string
  version: number
  configured_at: string | null
  runtime_supported: boolean
  restart_scope: 'API_ONLY' | 'WORKERS_ONLY' | 'API_AND_WORKERS' | 'NOT_IMPLEMENTED'
  activation_state: 'NOT_CONFIGURED' | 'SAVED_UNTESTED' | 'TEST_NOT_AVAILABLE' | 'TESTED' | 'ACTIVATED_RESTART_REQUIRED' | 'APPLIED_TO_API_PROCESS' | 'DEPLOYMENT_MANAGED' | 'RUNTIME_NOT_IMPLEMENTED'
  tested_version: number | null
  test_status: 'AVAILABLE' | 'AUTHENTICATION_REQUIRED' | 'UNAVAILABLE' | null
  tested_at: string | null
  activated_version: number | null
  activated_at: string | null
  applied_version: number | null
}

export interface SystemConfigurationTestResult {
  system_id: SystemConfigurationEntry['system_id']
  status: 'AVAILABLE' | 'AUTHENTICATION_REQUIRED' | 'UNAVAILABLE'
  scope: 'HTTP_HEALTH' | 'MODEL_DISCOVERY' | 'MODEL_INFERENCE' | 'EMBEDDING_INFERENCE'
    | 'AUTHENTICATED_QUERY' | 'REDIS_PING' | 'REDIS_POLICY' | 'S3_HEAD_BUCKET'
  latency_ms: number
  detail: string
  configuration_version: number
  tested_at: string
}

export interface AdminReadContext {
  subject_id: string
  workspace_id: string
  display_name: string
  authentication_assurance: 'UNKNOWN' | 'PASSWORD' | 'PASSWORD_REAUTH' | 'OTHER_MFA' | 'HARDWARE_WEBAUTHN'
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

export type RetentionPeriodUnit = 'DAYS' | 'MONTHS' | 'YEARS'
export type RetentionArchiveDisposition = 'NO_ARCHIVE' | 'EVIDENCE_ONLY' | 'CONTENT_WORM'

export interface RetentionClassRule {
  data_class: RetentionDataClass
  unit: RetentionPeriodUnit
  minimum: number
  maximum: number
  archive_disposition: RetentionArchiveDisposition
}

export interface RetentionPolicyContract {
  effective_from: string
  effective_until: string | null
  execution_authorization_hours: number
  class_rules: RetentionClassRule[]
}

export type RetentionPolicyState = 'DRAFT' | 'ACTIVE' | 'REJECTED' | 'SUPERSEDED'

export interface RetentionPolicy {
  policy_id: string
  policy_number: number
  rules: RetentionRules
  contract_version: 'SINGLE_DEADLINE_V1' | 'POLICY_BOOK_V2'
  contract: RetentionPolicyContract | null
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
  action_history_truncated: boolean
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
  approval_history_truncated: boolean
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

export interface RetentionExecutionEvidence {
  erasure_request_id: string
  availability: 'NOT_PLANNED' | 'AVAILABLE'
  archive_only: true
  deletion_automation_state: 'DISABLED_NOT_READY'
  job: {
    job_id: string
    erasure_request_version: number
    erasure_request_payload_hash: string
    target_type: 'CHAT_SESSION'
    target_id: string
    target_version: number
    classification: Classification
    retention_policy_id: string
    retention_policy_hash: string
    policy_number: number
    execution_authorization_valid_until: string
    archive_disposition: 'EVIDENCE_ONLY'
    command_hash: string
    archive_retain_until: string
    state: 'PLANNED' | 'LEASED' | 'RETRY_WAIT' | 'BLOCKED'
      | 'ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED'
    next_attempt_at: string
    attempt_count: number
    maximum_attempts: number
    archive_manifest_hash: string | null
    destructive_state: 'DISABLED_NOT_READY'
    separation_of_duties_verified: true
    version: number
    created_at: string
    updated_at: string
    attempts: Array<{
      attempt_no: number
      state: 'RUNNING' | 'RETRY_WAIT' | 'BLOCKED'
        | 'ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED' | 'SUPERSEDED'
      stage: string
      evidence_hash: string
      destructive_effect_count: 0
      started_at: string
      finished_at: string | null
    }>
    attempts_truncated: boolean
    events: Array<{
      sequence: number
      event_type: 'PLANNED' | 'LEASED' | 'RETRY_WAIT' | 'BLOCKED'
        | 'ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED'
      attempt_no: number | null
      evidence_hash: string
      occurred_at: string
    }>
    events_truncated: boolean
    receipt: {
      receipt_id: string
      manifest_hash: string
      content_sha256: string
      row_count: number
      byte_count: number
      retention_until: string
      legal_hold: boolean
      content_verified_at: string
      retention_verified_at: string
      verified_at: string
      payload_hash: string
    } | null
  } | null
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
