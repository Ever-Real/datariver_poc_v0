export type ChangeHistoryCategory =
  | 'TECHNICAL_SCHEMA'
  | 'DOCUMENTATION'
  | 'TAG'
  | 'GLOSSARY_TERM'
  | 'OWNERSHIP'
  | 'LIFECYCLE'

export type ChangeHistoryChangeType = 'SCHEMA_CHANGE' | 'METADATA_CHANGE'
export type ChangeHistoryOperation = 'CREATE' | 'UPDATE' | 'UPSERT' | 'DELETE' | 'ADD' | 'REMOVE'
export type ChangeHistoryPrecision =
  | 'EXACT_TIMELINE'
  | 'EXACT_MCL'
  | 'DRIFT_DETECTED'
  | 'BACKFILLED_BEST_EFFORT'
  | 'INITIAL_BASELINE'
export type ChangeHistoryStage = 'UNLINKED' | 'RECEIVED' | 'RECHECK' | 'TESTING' | 'FINAL_REVIEW' | 'COMPLETED'
export type ChangeHistoryLinkAction = 'SET_PRIMARY' | 'CLEAR_PRIMARY' | 'ADD_CANDIDATE' | 'REMOVE_CANDIDATE'

export interface ChangeHistoryLocator {
  platform: string
  database_name: string
  schema_name: string
  asset_name: string | null
}

export interface ChangeHistorySystemResolution {
  resolution: 'RESOLVED' | 'UNMAPPED' | 'AMBIGUOUS'
  system_id: string | null
  provider_context: Omit<ChangeHistoryLocator, 'asset_name'> | null
}

export interface ChangeHistoryAssignee {
  subject_id: string | null
  responsibility: 'DATA_STEWARD' | 'DEVELOPER' | 'UNASSIGNED'
  system_id: string | null
  priority: number | null
  basis: 'CURRENT_POC_PROJECTION'
}

export interface ChangeHistoryCrLink {
  change_request_id: string
  change_request_round: number
}

export interface ChangeHistoryEvent {
  event_id: string
  transaction_id: string
  asset_urn: string
  entity_key: string
  category: ChangeHistoryCategory
  change_type: ChangeHistoryChangeType
  source_aspect: string
  operation: ChangeHistoryOperation
  precision: ChangeHistoryPrecision | null
  source_occurred_at: string | null
  detected_at: string
  captured_at: string
  system: ChangeHistorySystemResolution
  locator: ChangeHistoryLocator | null
  assignee: ChangeHistoryAssignee
  current_stage: ChangeHistoryStage
  allowed_link_actions: ChangeHistoryLinkAction[]
  current_primary: ChangeHistoryCrLink | null
  current_candidates: ChangeHistoryCrLink[]
  link_version: number
}

export interface ChangeHistoryEventDetail extends ChangeHistoryEvent {
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
}

export interface ChangeHistoryEventPage {
  items: ChangeHistoryEvent[]
  next_cursor: string | null
  limit: number
  total: number
}

export interface ChangeHistoryWeeklySummary {
  week_start: string
  week_end_exclusive: string
  timezone: 'Asia/Seoul'
  as_of: string
  policy_version: number
  policy_hash: string
  count_unit: 'DISTINCT_NORMALIZED_CHANGE_TRANSACTION'
  total_count: number
  unlinked_count: number
  received_count: number
  recheck_count: number
  testing_count: number
  final_review_count: number
  completed_count: number
  time_unknown_count: number
}

export type ChangeHistorySyncStatus = 'SOURCE_NOT_CONFIGURED' | 'SOURCE_AMBIGUOUS'
  | 'CHECKPOINT_NOT_AVAILABLE' | 'CHECKPOINT_INVALID' | 'CAPTURE_PENDING'
  | 'CONTIGUOUS_CAPTURE_RECORDED'

export interface ChangeHistorySummary extends ChangeHistoryWeeklySummary {
  schema_change_count: number
  metadata_change_count: number
  event_count: number
  distinct_asset_count: number
  precision_counts: Record<ChangeHistoryPrecision, number>
  category_counts: Record<ChangeHistoryCategory, number>
  operation_counts: Record<ChangeHistoryOperation, number>
  capture_state: ChangeHistorySyncStatus
  sync_status: ChangeHistorySyncStatus
  source_generation: string
  source_observed_at: string
  source_occurred_at: string | null
  detected_at: string | null
  captured_at: string | null
  effective_week_start: string
  history_available_from: string | null
  ledger_guarantee_from: string | null
  first_exact_capture_at: string | null
  first_timeline_checkpoint: string | null
  first_mcl_offsets: Array<{ partition: number; offset: number }> | null
  last_successful_capture_at: string | null
}

export interface ChangeHistoryLinkHistoryEvent {
  link_event_identity: string
  event_hash: string
  ledger_event_identity: string
  link_version: number
  link_kind: 'PRIMARY' | 'CANDIDATE'
  action: ChangeHistoryLinkAction
  change_request_id: string
  change_request_round: number
  prior_link_hash: string | null
  reason: string
  policy_hash: string
  basis_hash: string
  actor_ref: string
  occurred_at: string
  captured_at: string
}

export interface ChangeHistoryLinkPage {
  current_primary: ChangeHistoryCrLink | null
  current_candidates: ChangeHistoryCrLink[]
  items: ChangeHistoryLinkHistoryEvent[]
  next_cursor: string | null
  limit: number
}

export interface ChangeHistoryReversePage {
  change_request_id: string
  items: ChangeHistoryEvent[]
  next_cursor: string | null
  limit: number
}

export interface ChangeHistoryLinkCommand {
  action: ChangeHistoryLinkAction
  change_request_id: string
  change_request_round: number
  reason: string
}

export interface ChangeHistoryLinkCommandResult {
  link_event_identity: string
  event_hash: string
  link_version: number
  replayed: boolean
  event_id: string
  change_request_id: string
  change_request_round: number
  action: ChangeHistoryLinkAction
}

export type ChangeHistoryAccessRole = 'admin' | 'data_steward' | 'developer' | 'viewer'

export interface ChangeHistoryAccessDocument {
  schema_version: 1
  active_subject_id: string
  policy: {
    version: 1
    priority_order: 'ASCENDING'
    fallback: ['DATA_STEWARD', 'DEVELOPER', 'DATAHUB_OWNER', 'UNASSIGNED']
  }
  users: Array<{
    subject_id: string
    role: ChangeHistoryAccessRole
    active: boolean
    provider_owner_refs: string[]
    username?: string
    display_name?: string
    email?: string
    first_name?: string
    last_name?: string
    department_id?: string | null
    job_function?: string | null
  }>
  systems: Array<{
    system_id: string
    code: string
    name: string
    description: string
    active: boolean
    version: number
  }>
  system_schema_scopes: Array<{
    scope_id: string
    system_id: string
    platform: string
    database_name: string
    schema_name: string
    active: boolean
    version: number
  }>
  system_assignments: Array<{
    system_id: string
    subject_id: string
    responsibility: 'DATA_STEWARD' | 'DEVELOPER'
    priority: number
    active: boolean
  }>
}

export interface VersionedChangeHistoryAccess extends ChangeHistoryAccessDocument {
  version: number
  etag: string
}

export interface ChangeHistoryEventFilters {
  weekStart?: string
  changeType?: ChangeHistoryChangeType
  category?: ChangeHistoryCategory
  precision?: ChangeHistoryPrecision
  operation?: ChangeHistoryOperation
  platform?: string
  databaseName?: string
  schemaName?: string
  systemId?: string
  assigneeSubjectId?: string
  linkState?: 'LINKED' | 'UNLINKED'
  stage?: ChangeHistoryStage
  cursor?: string
  limit?: number
}
