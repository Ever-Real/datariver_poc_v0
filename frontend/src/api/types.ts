export interface Capability {
  name: string
  state: string
  observed_at: string
  latency_ms?: number
  detail_code?: string
}

export interface OperationsSummary {
  observed_at: string
  jobs_by_state: Record<string, number>
  uploads_by_state: Record<string, number>
  changes_by_state: Record<string, number>
  unpublished_outbox_events: number
  dead_lettered_outbox_events: number
  oldest_unpublished_age_seconds?: number
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
