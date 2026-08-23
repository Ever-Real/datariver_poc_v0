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

export interface MonitoringDashboard {
  id: string
  label: string
  url: string
  height_px: number
  embed_state: 'AVAILABLE' | 'DISABLED'
  embed_url?: string
}

export interface MonitoringConfiguration {
  items: MonitoringDashboard[]
  version: number
}

export interface CapabilitiesResponse {
  items: Capability[]
  external_system_links: ExternalSystemLink[]
  grafana_embed: GrafanaEmbed
  monitoring_configuration: MonitoringConfiguration
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
  authorization?: PocAuthorization
}

export type PocRole = 'viewer' | 'developer' | 'data_steward' | 'manager' | 'admin'

export type PocCapability =
  | 'catalog.read'
  | 'catalog.execute'
  | 'catalog.manage'
  | 'chat.query'
  | 'change.read'
  | 'change.execute'
  | 'change.manage'
  | 'quality.read'
  | 'quality.execute'
  | 'quality.manage'
  | 'knowledge.read'
  | 'knowledge.manage'
  | 'knowledge.review'
  | 'monitoring.read'
  | 'admin.manage'

export interface PocAuthorization {
  policy_version: 'POC_PROFILE_CAPABILITIES_V1'
  role: PocRole
  capabilities: PocCapability[]
  system_scope: 'GLOBAL' | 'ASSIGNED'
  system_ids: string[]
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
  description?: string | null
  platform?: string | null
  database_name?: string | null
  schema_name?: string | null
  owner?: string | null
  domain?: string | null
  tags?: string[]
  terms?: string[]
  description_truncated?: boolean
  tags_truncated?: boolean
  terms_truncated?: boolean
  created_at?: string | null
  classification: string
  lifecycle: string
  observed_at: string
  stale_at?: string | null
  matches: CatalogMatchFragment[]
}

export interface CatalogMatchFragment {
  field: 'NAME' | 'DESCRIPTION' | 'SCHEMA' | 'COLUMN' | 'TAG' | 'TERM'
  text: string
  matched_terms: string[]
}

export interface CatalogPolicyMeta {
  observed_at?: string | null
  stale_at?: string | null
  projection_version: number
  policy_version: string
  classification_policy_version?: number | null
  authorization_generation?: number | null
}

export interface CatalogSearch {
  items: CatalogAsset[]
  page: { next_cursor?: string | null; limit: number }
  total: number
  total_exact?: boolean
  meta: CatalogPolicyMeta
  match_mode: 'ALL'
}

export interface CatalogFacets {
  asset_types: Array<{ value?: string | null; count: number }>
  platforms: Array<{ value?: string | null; count: number }>
  classifications: Array<{ value?: string | null; count: number }>
  databases: Array<{ value?: string | null; count: number }>
  schemas: Array<{ value?: string | null; count: number }>
  domains: Array<{ value?: string | null; count: number }>
  lifecycles: Array<{ value?: string | null; count: number }>
  meta: CatalogPolicyMeta
}

export interface CatalogSuggestion {
  id: string
  name: string
  asset_type: string
  platform?: string | null
  database_name?: string | null
  schema_name?: string | null
  matches: CatalogMatchFragment[]
}

export interface CatalogSuggestions {
  items: CatalogSuggestion[]
  meta: CatalogPolicyMeta
  match_mode: 'ALL'
}

export interface CatalogVocabulary {
  items: string[]
  meta: CatalogPolicyMeta
}

export interface CatalogAssetDetail extends CatalogAsset {
  ownership: Array<Record<string, unknown>>
  ownership_truncated?: boolean
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
  provider_source_version: string
  created_at: string
  created_by?: string
  asset_id?: string
  version: number
}

export interface ManualMetadataSubmissionStatus extends ManualMetadataSubmission {
  updated_at: string
  applied_at: string | null
  attempts: number
  next_attempt_at: string | null
  last_error_code: string | null
}

export interface ManualMetadataAspectReport {
  aspect_name: 'datasetProperties' | 'domains' | 'globalTags' | 'glossaryTerms' | 'schemaMetadata'
  aspect_ordinal: number
  outcome:
    | 'ALREADY_MATCHED'
    | 'APPLIED_VERIFIED'
    | 'FAILED_BEFORE_WRITE'
    | 'WRITE_REJECTED'
    | 'READBACK_FAILED'
    | 'READBACK_MISMATCH'
  before_hash: string | null
  expected_hash: string | null
  observed_hash: string | null
  write_attempted: boolean
  failure_code: string | null
  provider_version: string | null
  provider_response_hash: string | null
  observed_at: string
}

export interface ManualMetadataApplyAttempt {
  id: string
  attempt_no: number
  lease_epoch: number
  state: 'RUNNING' | 'APPLIED' | 'RETRY_WAIT' | 'FAILED' | 'SUPERSEDED'
  failure_code: string | null
  report_root_hash: string | null
  started_at: string
  finished_at: string | null
  aspects: ManualMetadataAspectReport[]
}

export interface ManualMetadataSubmissionReport {
  submission: ManualMetadataSubmissionStatus
  attempts: ManualMetadataApplyAttempt[]
}

export interface ManualMetadataSubmissionList {
  items: ManualMetadataSubmissionStatus[]
  page: { next_cursor?: string | null; limit: number }
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
  platform?: string | null
  database_name?: string | null
  schema_name?: string | null
  asset?: CatalogAsset | null
}

export interface CatalogTreePage {
  items: CatalogTreeNode[]
  page: { next_cursor?: string | null; limit: number }
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
  | 'CATALOG_METADATA_ROWS_CSV_V1'
  | 'CATALOG_METADATA_ROWS_XLSX_V1'
  | 'DATASET_DESCRIPTION_CSV_V1'
  | 'DATASET_DESCRIPTION_XLSX_V1'
  | 'KNOWLEDGE_SOURCE_DOCUMENT_V1'

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
  created_at?: string
  created_by?: string
}

export interface UploadPreparation {
  id: string
  upload_id: string
  content_profile:
    | 'CATALOG_METADATA_ROWS_CSV_V1'
    | 'CATALOG_METADATA_ROWS_XLSX_V1'
    | 'DATASET_DESCRIPTION_CSV_V1'
    | 'DATASET_DESCRIPTION_XLSX_V1'
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

export interface TypedBulkCandidatePreview {
  candidate_id: string
  target_asset_id: string
  target_ref: string
  platform: string
  database_name: string
  schema_name: string
  table_name: string
  current_description: string | null
  proposed_description: string
  before_hash: string
  after_hash: string
  source_version: string
  observed_at: string
  preview_etag: string
}

export type CatalogMetadataRecordKind =
  | 'TABLE_DESCRIPTION'
  | 'COLUMN_DESCRIPTION'
  | 'DATASET_DOMAIN'
  | 'DATASET_TERM'
  | 'DATASET_TAG'

export type CatalogMetadataCandidateKind =
  | 'TABLE_DESCRIPTION_UPDATE'
  | 'COLUMN_DESCRIPTION_UPDATE'
  | 'DATASET_DOMAIN_UPDATE'
  | 'DATASET_TERM_ADD'
  | 'DATASET_TAG_ADD'

export interface CatalogMetadataCandidate {
  id: string
  ordinal: number
  evidence_version: 'CATALOG_METADATA_CANDIDATE_V3'
  record_kind: CatalogMetadataRecordKind
  candidate_kind: CatalogMetadataCandidateKind
  operation_count: number
  field_path_sample: string[]
  controlled_reference_count: number
  row_summary_truncated: boolean
  submitted_identity: UploadRegistrationCandidate['submitted_identity']
  candidate_hash: string
  created_at: string
  current_target: UploadRegistrationCandidate['current_target']
}

export interface CatalogMetadataCandidatePage {
  items: CatalogMetadataCandidate[]
  page: { next_cursor?: string; limit: number }
  receipt: {
    id: string
    preparation_id: string
    manifest_version: number
    source_sha256: string
    content_profile:
      | 'CATALOG_METADATA_ROWS_CSV_V1'
      | 'CATALOG_METADATA_ROWS_XLSX_V1'
    parser_version: string
    scanner_version: string
    schema_version: string
    configuration_hash: string
    item_count: number
    candidate_count: number
    candidate_root_hash: string
    receipt_hash: string
    observed_at: string
    created_at: string
  }
  meta: UploadRegistrationCandidatePage['meta']
}

export interface TypedCatalogMetadataPreview {
  candidate_id: string
  target_asset_id: string
  platform: string
  database_name: string
  schema_name: string
  table_name: string
  record_kind: CatalogMetadataRecordKind
  candidate_kind: CatalogMetadataCandidateKind
  operation_count: number
  description_change_count: number
  description_change_sample: Array<{
    field_path: string | null
    current_description: string | null
    proposed_description: string | null
  }>
  description_changes_truncated: boolean
  current_reference_count: number
  proposed_reference_count: number
  before_hash: string
  after_hash: string
  source_version: string
  observed_at: string
  preview_etag: string
}

export interface TypedCatalogMetadataChangeRequest {
  id: string
  number: string
  request_type: 'BULK_CATALOG_METADATA'
  state: string
}

export type CatalogMetadataVocabularyKind = 'DOMAIN' | 'TAG' | 'TERM'

export interface CatalogMetadataVocabularyItem {
  id: string
  kind: CatalogMetadataVocabularyKind
  display_name: string
  source_version: string
}

export interface CatalogMetadataVocabularyPage {
  items: CatalogMetadataVocabularyItem[]
  page: {
    next_cursor?: string
    limit: number
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
  revision_allowed: boolean
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
      kind: 'SYSTEM_DEVELOPER' | 'SYSTEM_DATA_STEWARD' | 'SYSTEM_MANAGER' | 'GLOBAL_ADMIN'
      system_id: string | null
    }>
  }>
  approval_lanes?: Array<{
    id: string
    stage: 'REVIEW' | 'TEST' | 'FINAL'
    lane_kind: 'DEVELOPER' | 'DATA_STEWARD' | 'MANAGER'
    decision: 'APPROVED'
    actor_subject_id: string
    actor_role: 'developer' | 'data_steward' | 'manager'
    responsible_system_id: string
    reason: string
    occurred_at: string
    round_id: string
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
    revision_kind: 'LEGACY' | 'INITIAL' | 'EDITED'
    title: string
    request_date: string | null
    request_department: string
    request_reason: string
    request_content: string
    requested_due_date: string | null
    priority: 'LOW' | 'NORMAL' | 'HIGH' | 'CRITICAL' | null
    urgency: 'NORMAL' | 'URGENT' | 'EMERGENCY' | null
    classification: string
    selected_system_id: string | null
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

export interface GovernanceApplyReport {
  change_request_id: string
  job_id: string | null
  state: string
  attempt_count: number
  last_error_code: string | null
  expected_hash: string | null
  observed_hash: string | null
  reconciled: boolean
  created_at: string | null
  updated_at: string | null
  items: Array<{
    item_id: string
    expected_hash: string
    observed_hash: string | null
    source_version: string | null
    provider_version: string | null
  }>
  attempts: Array<{
    id: string
    attempt_no: number
    state: string
    failure_code: string | null
    external_response_hash: string | null
    started_at: string
    finished_at: string | null
  }>
}

export interface RegistrationOperatorCapability {
  eligible: boolean
  can_view_registration: boolean
  can_view_workspace_history: boolean
  reason_code:
    | 'ELIGIBLE'
    | 'READ_ONLY'
    | 'ACTIVE_HUMAN_ADMIN_OR_DATA_STEWARD_REQUIRED'
  allowed_roles: ['ADMIN', 'DATA_STEWARD']
}

export interface ChangeRequestSummary {
  id: string
  number: string
  request_type: string
  title: string
  state: ChangeRequestState
  requester_id: string
  requester_name?: string | null
  requester_department_id: string | null
  current_round_number: number
  created_at: string
  requested_due_date: string | null
  priority: 'LOW' | 'NORMAL' | 'HIGH' | 'CRITICAL' | null
  urgency: 'NORMAL' | 'URGENT' | 'EMERGENCY' | null
  classification: string
  version: number
  item_count: number
  target_schema_name?: string | null
  assignee_names?: string[]
  first_item: {
    target_ref: string
    aspect_name: string
    operation: string
  }
}

export interface ChangeRequestSummaryList {
  items: ChangeRequestSummary[]
  overview: ChangeRequestSchemaOverview[]
  overview_truncated: boolean
  page: { next_cursor?: string | null; limit: number }
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
  page: { next_cursor?: string | null; limit: number }
}

export interface ChangeRequestAttachmentUpload {
  id: string
  change_request_id: string
  round_id: string
  kind: 'REQUEST' | 'TEST'
  original_name: string
  state: 'STARTED' | 'STORED' | 'FINALIZED' | 'FAILED'
  expected_size_bytes: number
  expected_content_sha256: string
  provider_checksum: string | null
  failure_code: string | null
  status_url: string
  finalize_url: string
}

export interface ChangeRequestAttachmentUploadList {
  items: ChangeRequestAttachmentUpload[]
}

export interface ChangeRequestSchemaOverview {
  platform: string
  database_name: string
  schema_name: string
  system_id: string | null
  system_resolution?: 'RESOLVED' | 'UNMAPPED' | 'AMBIGUOUS'
  system_code: string | null
  system_name: string | null
  assignees: Array<{
    subject_id: string
    display_name: string
    responsibility: 'DEVELOPER' | 'DATA_STEWARD'
    priority: number
  }>
  event_count?: number
  unprogressed_event_count?: number
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
  domain_id?: string
  domain_source_version?: string
  domain_name?: string
  active_release_id?: string
  created_by?: string
  updated_by?: string
  created_at?: string
  updated_at?: string
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
  published_by: string
  published_at: string
  publisher_name?: string | null
  publisher_email?: string | null
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

export interface KnowledgeSourceJobResult {
  changeset_id: string
  page_count: number
  proposed_node_count: number
  proposed_edge_count: number
  evidence_hash: string
  embedding_model: string
  extraction_model: string
}

export interface KnowledgeSourceJob {
  id: string
  graph_id: string
  source_snapshot_id: string
  upload_id: string
  title: string
  state:
    | 'QUEUED'
    | 'RUNNING'
    | 'RETRY_WAIT'
    | 'CANCEL_REQUESTED'
    | 'SUCCEEDED'
    | 'FAILED'
    | 'STALE'
    | 'CANCELLED'
  stage:
    | 'QUEUED'
    | 'SOURCE_READ'
    | 'PARSED'
    | 'EMBEDDED'
    | 'EXTRACTED'
    | 'FINALIZING'
    | 'COMPLETED'
  progress: {
    completed_pages?: number
    total_pages?: number
  }
  attempt_count: number
  maximum_attempts: number
  next_attempt_at: string
  last_failure_code: string | null
  version: number
  created_at: string
  updated_at: string
  completed_at: string | null
  result: KnowledgeSourceJobResult | null
}

export interface KnowledgeSourceJobPage {
  items: KnowledgeSourceJob[]
  next_cursor: string | null
}

export interface KnowledgeProjectionReceipt {
  deployment_id: string
  release_id: string
  release_hash: string
  node_count: number
  edge_count: number
  state: 'SHADOW_VERIFIED'
}

export interface KnowledgeDeliveryPolicy {
  id: string
  graph_id: string
  api_enabled: boolean
  chat_enabled: boolean
  priority: number
  match_any_terms: string[]
  match_all_terms: string[]
  excluded_terms: string[]
  version: number
  created_by: string
  updated_by: string
  created_at: string
  updated_at: string
}

export interface KnowledgeAssetSummary {
  id: string
  draft_id?: string
  slug: string
  name: string
  description?: string | null
  display_version?: number
  graph_type: string
  status: string
  classification: 'PUBLIC' | 'INTERNAL' | 'CONFIDENTIAL' | 'RESTRICTED'
  domain_id: string | null
  domain_name: string | null
  creator_name: string | null
  creator_email: string | null
  editor_name: string | null
  editor_email: string | null
  active_studio_release_id: string | null
  active_studio_release_no: number | null
  active_release_id: string | null
  active_release_no: number | null
  class_count: number
  property_count: number
  relationship_count: number
  binding_count: number
  source_count: number
  node_count: number
  edge_count: number
  projection_state: string | null
  created_at: string
  updated_at: string
  version: number
  delivery_policy: KnowledgeDeliveryPolicy | null
}

export interface KnowledgeAssetPage {
  items: KnowledgeAssetSummary[]
  next_cursor: string | null
  limit: number
}

export type KnowledgeAssetVersionKind =
  | 'STUDIO_RELEASE'
  | 'INSTANCE_RELEASE'
  | 'CHANGESET'

export interface KnowledgeAssetVersionHistoryItem {
  id: string
  kind: KnowledgeAssetVersionKind
  version_label: string
  title: string | null
  status: string
  author_id: string | null
  author_name: string | null
  author_email: string | null
  reviewed_by: string | null
  reviewer_name: string | null
  reviewer_email: string | null
  published_by: string | null
  publisher_name: string | null
  publisher_email: string | null
  created_at: string
  is_current: boolean
  studio_release_id: string | null
  instance_release_id: string | null
  changeset_id: string | null
  content_hash: string | null
  node_count: number | null
  edge_count: number | null
}

export interface KnowledgeAssetVersionHistoryPage {
  items: KnowledgeAssetVersionHistoryItem[]
  next_cursor: string | null
  limit: number
}

export interface KnowledgeAssetBindingSummary {
  id: string
  target_stable_element_id: string
  source_reference_id: string
  source_kind: string
  source_name: string
  source_version: string
  mapping_rule_count: number
  mapping_rules?: Array<{
    method: 'SUBJECT_ID' | 'PROPERTY' | 'EDGE_LINK' | 'EDGE_PROPERTY'
    source_field_path: string
    target_stable_element_id: string
    source_unit: string | null
    canonical_unit: string | null
  }>
}

export interface KnowledgeAssetProjectionSummary {
  id: string
  release_id: string
  adapter: string
  state: string
  node_count: number | null
  edge_count: number | null
  verified_at: string | null
  error_code: string | null
  updated_at: string
}

export interface KnowledgeAssetOperationalDetail {
  asset: KnowledgeAssetSummary
  schema_elements: Array<{
    stable_element_id: string
    kind: 'CLASS' | 'PROPERTY' | 'RELATION'
    display_name: string
    canonical_name: string
    parent_stable_element_id?: string | null
    data_type: string | null
    source_stable_element_id: string | null
    target_stable_element_id: string | null
  }>
  bindings: KnowledgeAssetBindingSummary[]
  projections: KnowledgeAssetProjectionSummary[]
}

export interface ChatSession {
  id: string
  title: string
  is_favorite: boolean
  version: number
  created_at: string
  updated_at: string
  message_count: number
}

export type ChatMode = 'AUTO' | 'GENERAL' | 'VECTOR' | 'GRAPH'

export interface ChatRouteDecision {
  requested_mode: ChatMode
  selected_mode: ChatMode
  reason: 'EXPLICIT_SELECTION' | 'GRAPH_INTENT' | 'KNOWLEDGE_ASSET_POLICY' | 'SEMANTIC_INTENT' | 'GENERAL_DEFAULT'
  adapter_state: 'READY' | 'UNAVAILABLE' | 'FAILED'
  intent?:
    | 'EXPLICIT_SELECTION'
    | 'GENERAL_CONVERSATION'
    | 'EXACT_METADATA'
    | 'SEMANTIC_DISCOVERY'
    | 'SEMANTIC_SIMILARITY'
    | 'LINEAGE'
    | 'IMPACT_ANALYSIS'
    | 'RELATIONSHIP'
    | 'KNOWLEDGE_RELATIONSHIP'
    | 'MIXED_DISCOVERY_GRAPH'
    | 'AMBIGUOUS'
  confidence?: number
  entity_resolution_required?: boolean
  graph_traversal_required?: boolean
  semantic_retrieval_required?: boolean
  fallback_mode?: Exclude<ChatMode, 'AUTO'> | null
  clarification_required?: boolean
  knowledge_scope?: {
    graph_id: string
    release_id: string
    asset_name: string
    policy_id: string
    policy_version: number
    policy_hash: string
  }
}

export interface ChatWorkflowStep {
  stage:
    | 'AUTHORIZATION'
    | 'BUDGET_RESERVATION'
    | 'ROUTING'
    | 'RETRIEVAL'
    | 'RERANKING'
    | 'COMPOSITION'
    | 'CITATION_VALIDATION'
    | 'PERSISTENCE'
  status: 'COMPLETED' | 'SKIPPED' | 'UNAVAILABLE' | 'FAILED' | 'REFUSED'
  detail_code: string
}

export interface ChatEvidence {
  chunk_id: string
  resource_id: string
  classification: 'PUBLIC' | 'INTERNAL' | 'CONFIDENTIAL' | 'RESTRICTED'
  system_id: string | null
  domain_id: string | null
  owner_department_id: string | null
  name: string
  asset_kind?: 'TABLE' | 'VIEW' | 'MATERIALIZED_VIEW' | 'CATALOG'
  description: string | null
  source_type: string
  source_locator: string
  source_version: string
  content_hash: string
  effective_from: string
  effective_until: string | null
  extraction_method: string
  rank: number
  retrieval_method: string
}

export interface ChatMessage {
  id: string
  session_id: string
  role: 'user' | 'assistant'
  content: string
  evidence_json: ChatEvidence[] | null
  created_at: string
  route: ChatRouteDecision | null
  workflow: ChatWorkflowStep[]
}
export interface ChatResponse {
  session_id: string
  request_message_id: string
  response_message_id: string
  answer: string
  persistence: 'PERSISTED' | 'EPHEMERAL_NO_STORE'
  route: ChatRouteDecision
  workflow: ChatWorkflowStep[]
  evidence: ChatEvidence[]
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
  contract_version: 'LEGACY_CLIENT_V1' | 'SUBJECT_CLIENT_V2'
  consumer_subject_id?: string
  consumer_issuer?: string
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
  | 'IDENTITY_USER_PROFILE_READ'
  | 'IDENTITY_USER_PROFILE_UPDATE'
  | 'IDENTITY_USER_PASSWORD_RESET'
  | 'MEMBERSHIP_ACCESS_READ'
  | 'MEMBERSHIP_ACCESS_UPDATE'
  | 'MEMBERSHIP_RENEWAL_READ'
  | 'MEMBERSHIP_RENEWAL_DECIDE'
  | 'SYSTEM_ASSIGNMENT_UPDATE'
  | 'SYSTEM_CONFIGURATION_READ'
  | 'SYSTEM_CONFIGURATION_UPDATE'
  | 'SYSTEM_CONFIGURATION_ACTIVATE'
  | 'MONITORING_CONFIGURATION_READ'
  | 'MONITORING_CONFIGURATION_UPDATE'
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
  change_history_role?: 'admin' | 'data_steward' | 'developer' | 'manager' | 'viewer'
  effective_profile_role:
    | 'VIEWER'
    | 'ENGINEER_STEWARD'
    | 'MANAGER'
    | 'ADMIN'
    | 'UNASSIGNED'
    | 'STALE'
    | 'REVOKED'
}

export interface MembershipChangeRequestActivity {
  change_request_id: string
  number: string
  title: string
  request_type: string
  state: string
  relationship: 'REQUESTER' | 'APPROVER' | 'REQUESTER_AND_APPROVER'
  classification: Classification
  updated_at: string
}

export interface MembershipOwnedTable {
  asset_id: string
  name: string
  platform: string | null
  database_name: string | null
  schema_name: string | null
  classification: Classification
  source_version: string
  observed_at: string
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
  canonical_admin_binding: CanonicalAdminBindingEvidence
  profile_role: ProfileRoleAssignmentEvidence
}

export interface CanonicalAdminBindingEvidence {
  status: 'NONE' | 'VERIFIED' | 'STALE' | 'REVOKED'
  role_version: number | null
  catalog_version: string | null
  membership_version: number | null
  binding_version: number | null
  updated_at: string | null
}

export interface ProfileRoleAssignmentEvidence {
  status: 'VERIFIED' | 'UNASSIGNED' | 'STALE' | 'REVOKED'
  tier: 'VIEWER' | 'ENGINEER_STEWARD' | 'MANAGER' | 'ADMIN' | null
  policy_version: string | null
  membership_version: number | null
  assignment_version: number | null
  updated_at: string | null
}

export interface ProfileRolePolicyItem {
  tier: 'VIEWER' | 'ENGINEER_STEWARD' | 'MANAGER' | 'ADMIN'
  label: string
  description: string
  allowed_actions: string[]
  services: Array<{
    service_key: string
    service_label: string
    action_labels: string[]
  }>
  assignable_to_system: boolean
  lifecycle_note: string
}

export interface ProfileRolePolicy {
  policy_version: string
  items: ProfileRolePolicyItem[]
}

export interface ProfileRoleTransitionResult {
  subject_id: string
  tier: ProfileRolePolicyItem['tier']
  membership_version: number
  assignment_version: number
  binding_version: number | null
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

export type CapabilityActorKind = 'HUMAN' | 'SERVICE_PRINCIPAL'
export type CapabilityAssignability =
  | 'HUMAN_ROLE'
  | 'CANONICAL_ADMIN_ONLY'
  | 'SERVICE_PRINCIPAL_ONLY'
export type CapabilityAssurance = 'NOT_APPLICABLE' | 'SESSION' | 'FRESH_PHISHING_RESISTANT'
export type CapabilityReasonPolicy = 'NOT_REQUIRED' | 'REQUIRED'
export type CapabilitySelfApprovalPolicy = 'NOT_APPLICABLE' | 'CANONICAL_ADMIN_ONLY'
export type CapabilitySelfApprovalBinding =
  | 'NOT_APPLICABLE'
  | 'PENDING_PROTECTED_BINDING'
export type CapabilityRisk = 'STANDARD' | 'ELEVATED' | 'HIGH' | 'SERVICE_PRIVILEGED'

export interface AccessRoleCapability {
  action: string
  label: string
  description: string
  actor_kind: CapabilityActorKind
  assignability: CapabilityAssignability
  default_admin: boolean
  assurance: CapabilityAssurance
  reason_policy: CapabilityReasonPolicy
  self_approval_policy: CapabilitySelfApprovalPolicy
  self_approval_binding: CapabilitySelfApprovalBinding
  risk: CapabilityRisk
}

export interface AccessRoleProtectedCapability {
  capability_key: 'admin.self_approve'
  label: string
  description: string
  actor_kind: CapabilityActorKind
  assignability: CapabilityAssignability
  default_admin: boolean
  assurance: CapabilityAssurance
  reason_policy: CapabilityReasonPolicy
  self_approval_policy: CapabilitySelfApprovalPolicy
  self_approval_binding: CapabilitySelfApprovalBinding
  risk: CapabilityRisk
}

export interface AccessRoleCapabilityService {
  service_key: string
  label: string
  description: string
  actions: AccessRoleCapability[]
  protected_capabilities: AccessRoleProtectedCapability[]
}

export interface AccessRoleCapabilityCatalog {
  contract_version: 'ACCESS_ROLE_CAPABILITY_CATALOG_V2'
  action_count: number
  human_action_count: number
  service_action_count: number
  protected_capability_count: number
  services: AccessRoleCapabilityService[]
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
  role_id: null
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

export interface IdentityUserProfile {
  subject_id: string
  username: string
  display_name: string
  email: string
  first_name: string
  last_name: string
  department_id: string | null
  job_function: string | null
  membership_version: number
  provider_enabled: boolean
  email_verified: boolean
  required_actions: string[]
}

export interface IdentityUserProfileUpdateInput {
  email: string
  first_name: string
  last_name: string
  department_id: string | null
  job_function: string | null
}

export interface IdentityUserProfileUpdateResult {
  subject_id: string
  username: string
  display_name: string
  email: string
  department_id: string | null
  job_function: string | null
  membership_version: number
}

export interface IdentityTemporaryPasswordResetResult {
  subject_id: string
  temporary_password_required: boolean
  sessions_revoked: boolean
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

export interface SystemAssigneeCandidate {
  subject_id: string
  display_name: string
  email: string | null
  tier: 'ENGINEER_STEWARD' | 'MANAGER' | 'ADMIN'
}

export interface SystemAssigneeUpdateResult {
  system_id: string
  system_version: number
  payload_hash: string
}

export interface SystemSchemaScope {
  scope_id: string
  system_id: string
  platform: string
  database_name: string
  schema_name: string
  active: boolean
  version: number
}

export interface SystemSchemaScopePage {
  system_version: number
  items: SystemSchemaScope[]
  page: { next_cursor: string | null; limit: number }
}

export interface SystemSchemaScopeCandidate {
  asset_id: string
  asset_name: string
  asset_type: 'TABLE' | 'VIEW' | 'DATASET'
  platform: string
  database_name: string
  schema_name: string
  classification: 'PUBLIC' | 'INTERNAL' | 'CONFIDENTIAL' | 'RESTRICTED'
  mapped_system_id: string | null
}

export interface SystemSchemaScopeUpdateResult {
  system_id: string
  system_version: number
  payload_hash: string
}

export type TableSecurityGrade = 'normal' | 'credential' | 'restricted'

export interface TableSystemMappingCandidate {
  table_identity: string
  table_name: string
  platform: string
  database_name: string
  schema_name: string
  security_grade: TableSecurityGrade
  system_ids: string[]
}

export interface TableSystemMappingPage {
  version: number
  items: TableSystemMappingCandidate[]
  total: number
  selection_complete: boolean
  schemas: string[]
}

export interface TableSystemMappingUpdateResult {
  version: number
  changed: number
}

export interface PocResponsibleSystem {
  system_id: string
  priority: number
  responsibility?: 'DEVELOPER' | 'DATA_STEWARD' | 'MANAGER'
}

export interface PocAdminCredentialStatus {
  username: string
  login_enabled: boolean
  must_change_password: boolean
  failed_attempts: number
  locked_until: string | null
  version: number
  active_session_count: number
}

export interface PocAdminUser {
  subject_id: string
  username: string | null
  display_name: string
  email: string | null
  role: 'admin' | 'data_steward' | 'developer' | 'manager' | 'viewer'
  active: boolean
  max_security_grade: TableSecurityGrade
  responsible_systems: PocResponsibleSystem[]
  table_grant_count: number
  credential: PocAdminCredentialStatus | null
}

export interface PocAdminUserPage {
  version: number
  items: PocAdminUser[]
  systems: SystemDirectoryEntry[]
}

export interface PocUserTableGrantCandidate extends TableSystemMappingCandidate {
  granted: boolean
}

export interface PocUserTableGrantPage {
  subject_id: string
  items: PocUserTableGrantCandidate[]
  total: number
  selection_complete: boolean
  schemas: string[]
}

export interface SystemConfigurationEntry {
  system_id: 'PLATFORM_RUNTIME' | 'POSTGRESQL' | 'OIDC_IDENTITY' | 'RETENTION_ARCHIVE' | 'DATAHUB_GMS' | 'DATAHUB_FRONTEND' | 'AIRFLOW' | 'REDIS_CACHE' | 'REDIS_DELIVERY' | 'S3_STORAGE' | 'LLM_CHAT_MODEL' | 'LLM_EMBEDDING' | 'LLM_RERANKER' | 'NEO4J' | 'PROMETHEUS' | 'GRAFANA_DASHBOARD'
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
  management_plane: 'DEPLOYMENT'
  secret_reference_configured: boolean
  embedding_state: 'NOT_APPLICABLE' | 'AVAILABLE' | 'DISABLED' | 'NOT_CONFIGURED'
  configuration_yaml: string
  template_yaml: string
  display_yaml: string
  environment_template: string
  effective_configuration_yaml: string
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
  is_core?: boolean
}

export interface DeploymentEnvironment {
  environment_file: string
  operator_profile: 'unmanaged' | 'portable-development' | 'mac-development' | 'wsl-preparation' | 'source-host-development' | 'wsl-source-host' | 'source-free-pilot'
  apply_method: 'UNAVAILABLE' | 'WORKFLOW_UPDATE_RESTART' | 'SOURCE_HOST_UPDATE' | 'SOURCE_HOST_RESTART' | 'PILOT_REDEPLOY'
  apply_command: string | null
  browser_execution_supported: false
}

export interface SystemConfigurationInventory {
  items: SystemConfigurationEntry[]
  deployment_environment: DeploymentEnvironment
}

export interface SystemConfigurationTestResult {
  system_id: SystemConfigurationEntry['system_id']
  status: 'AVAILABLE' | 'AUTHENTICATION_REQUIRED' | 'UNAVAILABLE'
  scope: 'HTTP_HEALTH' | 'MODEL_DISCOVERY' | 'MODEL_INFERENCE' | 'EMBEDDING_INFERENCE'
    | 'RERANKING_INFERENCE' | 'AUTHENTICATED_QUERY' | 'REDIS_PING' | 'REDIS_POLICY'
    | 'S3_HEAD_BUCKET'
  latency_ms: number
  detail: string
  configuration_version: number | null
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
export type RetentionContractVersion = 'POLICY_BOOK_V2' | 'POLICY_BOOK_V3' | 'POLICY_BOOK_V4'

export interface RetentionClassRule {
  data_class: RetentionDataClass
  unit: RetentionPeriodUnit
  minimum: number
  maximum: number
  archive_disposition: RetentionArchiveDisposition
}

export interface RetentionPolicyContract {
  contract_version: RetentionContractVersion
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
  contract_version: 'SINGLE_DEADLINE_V1' | RetentionContractVersion
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
  | 'QUALITY_RULE'
  | 'QUALITY_RESULT'
  | 'QUALITY_AUDIT'
  | 'QUALITY_PROFILE'
export type LegalHoldScope = 'WORKSPACE' | 'SUBJECT' | 'RESOURCE'
export type LegalHoldResourceType =
  | 'LEGACY_UNTYPED'
  | 'CHAT_SESSION'
  | 'UPLOAD_OBJECT'
  | 'QUALITY_RULE_SET'
  | 'QUALITY_VALIDATION_RUN'
  | 'PROFILE_SNAPSHOT'

export interface LegalHold {
  hold_id: string
  data_class: RetentionDataClass
  scope: LegalHoldScope
  scope_id: string | null
  resource_type: LegalHoldResourceType | null
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
export type ClassificationPolicySummaryState = 'GOVERNED' | 'STATIC_FLOOR'

export interface ClassificationPolicySummaryRule {
  classification: Classification
  search_mode: ClassificationSearchMode
  chat_mode: ClassificationChatMode
}

export interface ClassificationPolicySummary {
  state: ClassificationPolicySummaryState
  rules: ClassificationPolicySummaryRule[]
}

export interface ClassificationAccessRule {
  classification: Classification
  search_mode: ClassificationSearchMode
  chat_mode: ClassificationChatMode
  provider_profile_version_id: string | null
  embedding_provider_profile_version_id: string | null
  reranker_provider_profile_version_id: string | null
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

export type QualityCapabilityAxisId =
  | 'read_access'
  | 'profile_readiness'
  | 'rule_authoring'
  | 'review'
  | 'activation'
  | 'manual_execution'
  | 'scheduling'
  | 'operations'

export type QualityCapabilityState = 'AVAILABLE' | 'DENIED' | 'UNAVAILABLE'

export interface QualityCapabilityAxis {
  id: QualityCapabilityAxisId
  state: QualityCapabilityState
  reason_code?: string | null
}

export interface QualityCapability {
  contract_version: 'QUALITY_CAPABILITY_V2'
  observed_at: string
  valid_until: string
  cache_scope: string
  axes: QualityCapabilityAxis[]
}

export type QualityAvailability = 'AVAILABLE' | 'PARTIAL' | 'UNAVAILABLE'
export type QualityFreshness = 'CURRENT' | 'STALE' | 'UNKNOWN'
export type QualityOutcome = 'PASS' | 'WARN' | 'FAIL' | 'UNKNOWN'
export type QualityOverallState = QualityOutcome
export type QualityRunState =
  | 'QUEUED'
  | 'RUNNING'
  | 'RETRY_WAIT'
  | 'CANCEL_REQUESTED'
  | 'SUCCEEDED'
  | 'FAILED'
  | 'STALE'
  | 'CANCELLED'
export type QualityRuleSetState = 'ACTIVE' | 'ARCHIVED'
export type QualityRuleSetVersionState =
  | 'PROPOSED'
  | 'APPROVED'
  | 'REJECTED'
  | 'ACTIVE'
  | 'SUPERSEDED'
  | 'REVOKED'
export type QualityRuleKind = 'NOT_NULL' | 'RANGE' | 'REGEX'
export type QualityRuleSeverity = 'BLOCKING' | 'ADVISORY'
export type QualityExpectationOutcome = 'PASS' | 'ADVISORY_FAIL' | 'BLOCKING_FAIL'
export type QualityProfileReadiness = 'READY' | 'STALE' | 'UNAVAILABLE' | 'REDACTED'

export interface QualityTrendPoint {
  bucket_start: string
  passed_count: number
  advisory_failed_count: number
  blocking_failed_count: number
  evaluated_rule_count: number
  score_basis_points: number | null
}

export interface QualityOverview {
  availability: QualityAvailability
  freshness: QualityFreshness
  as_of: string
  authorization_valid_until: string
  overall_state: QualityOverallState
  active_rule_set_count: number
  evaluated_rule_set_count: number
  unknown_rule_set_count: number
  passed_count: number
  advisory_failed_count: number
  blocking_failed_count: number
  evaluated_rule_count: number
  score_basis_points: number | null
  coverage_basis_points: number | null
  trend: QualityTrendPoint[]
  failure_code: string | null
}

export interface QualityPageMeta {
  next_cursor: string | null
  limit: number
}

export interface QualityListResponse<T> {
  items: T[]
  page: QualityPageMeta
  cache_scope: string
  observed_at: string
  authorization_valid_until: string
}

export interface QualityResourceResponse<T> {
  item: T
  cache_scope: string
  observed_at: string
  authorization_valid_until: string
}

export interface QualityAsset {
  asset_id: string
  name: string
  platform?: string | null
  database_name?: string | null
  schema_name?: string | null
  classification: Classification
  lifecycle: string
  profile_readiness: QualityProfileReadiness
  profile_observed_at: string | null
  active_rule_set_count: number
  latest_run_state: QualityRunState | null
  latest_quality_outcome: QualityOutcome | null
  latest_score_basis_points: number | null
}

export type QualityAuthoringState = 'READY' | 'UNAVAILABLE'
export type QualityAuthoringLogicalType =
  | 'STRING'
  | 'INTEGER'
  | 'DECIMAL'
  | 'DATE'
  | 'TIMESTAMP'
  | 'BOOLEAN'
  | 'OTHER'
export type QualityAuthoringRuleKind = Extract<QualityRuleKind, 'NOT_NULL' | 'RANGE'>

export interface QualityAuthoringField {
  field_identifier: string
  display_path: string
  logical_type: QualityAuthoringLogicalType
  supported_rule_kinds: QualityAuthoringRuleKind[]
}

export interface QualityAssetAuthoring {
  state: QualityAuthoringState
  reason_code: string | null
  source_version: string
  schema_hash: string | null
  fields: QualityAuthoringField[]
}

export interface QualityAssetDetailResponse extends QualityResourceResponse<QualityAsset> {
  authoring: QualityAssetAuthoring
}

export interface QualityAssetSummaryBatchResponse {
  items: QualityAsset[]
  cache_scope: string
  observed_at: string
  authorization_valid_until: string
}

export interface QualityRuleDraftRequest {
  field_identifier: string
  kind: QualityAuthoringRuleKind
  severity: QualityRuleSeverity
  parameters: Record<string, unknown>
}

export interface QualityRuleBatchProposalRequest {
  name_prefix: string
  asset_ids: string[]
  rules: QualityRuleDraftRequest[]
}

export interface QualityRuleProposalItem {
  asset_id: string
  rule_set_id: string
  version_id: string
  version: number
}

export interface QualityRuleBatchProposalResponse {
  items: QualityRuleProposalItem[]
  replayed: boolean
}

export interface QualityAssetWorkspace {
  asset: QualityAsset
  rule_sets: QualityRuleSetSummary[]
  runs: QualityRunSummary[]
  trend: QualityTrendPoint[]
}

export interface QualityCommonRuleTemplateRule {
  field_identifier: string
  kind: QualityAuthoringRuleKind
  severity: QualityRuleSeverity
  parameters: Record<string, unknown>
}

export interface QualityCommonRuleTemplate {
  template_id: string
  name: string
  description: string | null
  rules: QualityCommonRuleTemplateRule[]
  mapping_count: number
  created_at: string
  updated_at: string
}

export interface QualityCommonRuleTemplateMapping {
  asset_id: string
  asset_name: string
  platform: string | null
  database_name: string | null
  schema_name: string | null
  rule_set_id: string
  rule_set_name: string
  mapped_at: string
}

export interface QualityCommonRuleTemplateDetail {
  template: QualityCommonRuleTemplate
  mappings: QualityCommonRuleTemplateMapping[]
}

export interface QualityCommonRuleTemplateListResponse {
  items: QualityCommonRuleTemplate[]
  cache_scope: string
  observed_at: string
  authorization_valid_until: string
}

export interface QualityCommonRuleTemplateCreateRequest {
  name: string
  description?: string | null
  rules: QualityRuleDraftRequest[]
}

export interface QualityCommonRuleTemplateCreateResponse {
  template_id: string
  replayed: boolean
}

export interface QualityRuleReviewRequest {
  decision: 'APPROVE' | 'REJECT'
  reason: string
}

export interface QualityRuleVersionCommandResponse {
  rule_set_id: string
  version_id: string
  state: QualityRuleSetVersionState
  version: number
}

export interface QualityManualRunResponse {
  run_id: string
  state: QualityRunState
  created_at: string
  replayed: boolean
}

export interface QualityRuleDefinitionCapability {
  kind: QualityRuleKind
  available: boolean
  reason_code: string | null
  parameter_contract: Record<string, unknown>
}

export interface QualityRuleDefinitionCatalog {
  contract_version: 'QUALITY_TYPED_RULES_V1'
  items: QualityRuleDefinitionCapability[]
}

export interface QualityRuleSetSummary {
  rule_set_id: string
  name: string
  asset_id: string
  asset_name: string
  state: QualityRuleSetState
  active_version_id: string | null
  active_version_number: number | null
  active_version_state: QualityRuleSetVersionState | null
  rule_count: number
  created_at: string
  updated_at: string
  version: number
}

export interface QualityRuleSetVersionSummary {
  version_id: string
  version_number: number
  state: QualityRuleSetVersionState
  author_id: string
  reviewed_by: string | null
  activated_by: string | null
  rule_count: number
  schedule_mode: string
  created_at: string
  updated_at: string
  version: number
}

export interface QualityRuleDefinition {
  rule_definition_id: string
  version_id: string
  ordinal: number
  field_identifier: string
  kind: QualityRuleKind
  severity: QualityRuleSeverity
  parameters: Record<string, unknown>
}

export interface QualityRuleSetDetail {
  rule_set: QualityRuleSetSummary
  versions: QualityRuleSetVersionSummary[]
  definitions: QualityRuleDefinition[]
}

export interface QualityRunSummary {
  run_id: string
  rule_set_id: string
  rule_set_name: string
  asset_id: string
  asset_name: string
  trigger_kind: 'MANUAL' | 'SCHEDULED' | 'RETRY'
  state: QualityRunState
  quality_outcome: QualityOutcome
  score_basis_points: number | null
  passed_count: number | null
  advisory_failed_count: number | null
  blocking_failed_count: number | null
  created_at: string
  completed_at: string | null
  failure_code: string | null
  version: number
}

export interface QualityExpectationResult {
  result_id: string
  rule_definition_id: string
  field_identifier: string
  kind: QualityRuleKind
  severity: QualityRuleSeverity
  outcome: QualityExpectationOutcome
  evaluated_count: number
  missing_count: number
  unexpected_count: number
  missing_ratio: number
  unexpected_ratio: number
  duration_ms: number
  occurred_at: string
}

export interface QualityIssueSummary {
  issue_id: string
  asset_id: string
  asset_name: string
  field_identifier: string
  kind: QualityRuleKind
  severity: QualityRuleSeverity
  outcome: Exclude<QualityExpectationOutcome, 'PASS'>
  occurrence_count: number
  last_observed_at: string
}

export type PocFeature = 'catalog' | 'registration' | 'change' | 'quality' | 'knowledge' | 'governance' | 'chat' | 'monitoring'

export interface PocFeatureSecurityCell {
  feature: PocFeature
  role: PocRole
  grade: TableSecurityGrade
  allow: boolean
}

export interface PocFeatureSecurityPolicy {
  version: number
  schema_version: number
  cells: PocFeatureSecurityCell[]
  updated_at: string | null
  updated_by: string | null
  reason: string
}

export interface PocFeatureSecurityPolicyUpdate {
  cells: PocFeatureSecurityCell[]
  reason: string
}
