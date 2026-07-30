import type { ApiClient, ApiResponse } from '../../../api/client'

export type KnowledgeClassification = 'PUBLIC' | 'INTERNAL' | 'CONFIDENTIAL' | 'RESTRICTED'

export interface KnowledgeStudioBasicInformation {
  name: string
  endpoint_alias: string
  endpoint_aliases?: string[]
  domain_id: string
  domain_source_version: string
  classification: KnowledgeClassification
}

export interface KnowledgeStudioDomainOption {
  id: string
  display_name: string
  source_version: string
  created_by?: string
  creator_display_name?: string
  creator_email?: string
  asset_count?: number
  lifecycle?: 'ACTIVE' | 'INACTIVE'
  version?: number
  created_at?: string
  updated_at?: string
  managed?: boolean
}

export interface KnowledgeStudioManagedDomain extends KnowledgeStudioDomainOption {
  asset_count: number
  lifecycle: 'ACTIVE' | 'INACTIVE'
  version: number
  created_at: string
  updated_at: string
  managed: true
}

export interface KnowledgeStudioDraft extends KnowledgeStudioBasicInformation {
  id: string
  author_id: string
  kind: 'CREATE' | 'EDIT'
  state: 'DRAFT' | 'REVIEW' | 'PUBLISHED' | 'DISCARDED'
  current_step: 'BASIC' | 'TBOX' | 'ABOX'
  last_autosaved_at: string
  version: number
  created_at: string
  updated_at: string
  submitted_preflight_check_id?: string
  reviewed_by?: string
  reviewed_at?: string
  review_reason?: string
  published_by?: string
  published_at?: string
  materialized_graph_id?: string
  materialized_ontology_version_id?: string
  published_studio_release_id?: string
}

export interface KnowledgeStudioTBoxElement {
  stable_element_id: string
  kind: 'CLASS' | 'PROPERTY' | 'RELATION'
  canonical_name: string
  display_name: string
  parent_stable_element_id?: string
  hierarchy_relation?: string
  source_stable_element_id?: string
  target_stable_element_id?: string
  data_type?: string
  nullable?: boolean
  ordinal: number
  version: number
  block_id?: string
  definition?: string
  aliases: string[]
  unit?: string
  vector_index_enabled: boolean
  metadata_reference_id?: string
  metadata_reference_urn?: string
  locked_by_later_block: boolean
  layout_x?: number
  layout_y?: number
}

export type KnowledgeStudioTBoxBlockKind =
  | 'DIRECT'
  | 'DOCUMENT_SCHEMA'
  | 'CATALOG_METADATA'
  | 'ASSET_RELEASE'
  | 'LLM_ASSISTANT'

export interface KnowledgeStudioTBoxBlock {
  id: string
  kind: KnowledgeStudioTBoxBlockKind
  title: string
  weight: number
  ordinal: number
  collapsed: boolean
  version: number
  source_reference?: Record<string, unknown>
  elements: KnowledgeStudioTBoxElement[]
  created_at: string
  updated_at: string
}

export interface KnowledgeStudioTBox {
  draft: KnowledgeStudioDraft
  blocks: KnowledgeStudioTBoxBlock[]
}

export type KnowledgeStudioTBoxOperation =
  | {
      operation: 'UPSERT_ELEMENT'
      stable_element_id: string
      element: Omit<
        KnowledgeStudioTBoxElement,
        'ordinal' | 'version' | 'block_id' | 'locked_by_later_block'
      >
    }
  | {
      operation: 'DELETE_ELEMENT'
      stable_element_id: string
    }
  | {
      operation: 'SET_LAYOUT'
      stable_element_id: string
      layout_x: number
      layout_y: number
    }

export interface KnowledgeStudioTBoxConflict {
  conflict_id: string
  kind: 'IDENTITY' | 'KIND' | 'PROPERTY' | 'ENDPOINT' | 'CONSTRAINT'
  stable_element_id: string
  field: string
  original_value: unknown
  proposed_value: unknown
}

export interface KnowledgeStudioTBoxProposal {
  id: string
  draft_id: string
  target_block_id?: string
  state: 'READY' | 'APPLIED' | 'REJECTED' | 'FAILED'
  mode: 'MERGE_INTO_CURRENT' | 'APPEND_LAYER'
  merge_strategy: 'KEEP_ORIGINAL' | 'ACCEPT_PROPOSAL' | 'RESOLVE'
  base_draft_version: number
  prompt: string
  elements: KnowledgeStudioTBoxElement[]
  conflicts: KnowledgeStudioTBoxConflict[]
  model_binding?: Record<string, unknown>
  source_reference?: Record<string, unknown>
  error_code?: string
  version: number
  created_at: string
  updated_at: string
  applied_at?: string
  rejected_at?: string
}

export interface KnowledgeStudioIngestionJob {
  id: string
  draft_id: string
  requested_by: string
  state: 'PENDING' | 'RUNNING' | 'FAILED' | 'SUCCESS'
  progress_percent: number
  current_stage: string
  vector_target_count: number
  result?: Record<string, unknown>
  error_code?: string
  error_message?: string
  version: number
  created_at: string
  updated_at: string
  started_at?: string
  finished_at?: string
}

export type KnowledgeStudioMappingMethod =
  | 'SUBJECT_ID'
  | 'PROPERTY'
  | 'EDGE_LINK'
  | 'EDGE_PROPERTY'

export interface KnowledgeStudioMappingRuleInput {
  method: KnowledgeStudioMappingMethod
  source_field_path: string
  target_stable_element_id: string
}

export interface KnowledgeStudioMappingRule extends KnowledgeStudioMappingRuleInput {
  id: string
  ordinal: number
  transform_id: 'IDENTITY'
  transform_version: '1'
  source_unit?: string
  canonical_unit?: string
}

export interface KnowledgeStudioBinding {
  id: string
  target_stable_element_id: string
  source_reference_id: string
  source_asset_id: string
  source_name: string
  source_version: string
  projection_source_version: string
  source_classification: KnowledgeClassification
  readiness: 'DRAFT' | 'VALIDATED' | 'STALE'
  tbox_version: number
  version: number
  rules: KnowledgeStudioMappingRule[]
  created_at: string
  updated_at: string
}

export interface KnowledgeStudioABox {
  draft: KnowledgeStudioDraft
  tbox_elements: KnowledgeStudioTBoxElement[]
  bindings: KnowledgeStudioBinding[]
}

export interface KnowledgeStudioSourceDataset {
  id: string
  name: string
  asset_type: 'DATASET' | 'TABLE' | 'VIEW'
  platform?: string
  database_name?: string
  schema_name?: string
  classification: KnowledgeClassification
  source_version: string
  projection_source_version: string
  field_paths: string[]
  fields_truncated: boolean
  domain?: string
  tags?: string[]
  glossary_terms?: string[]
}

export interface KnowledgeStudioSourcePage {
  items: KnowledgeStudioSourceDataset[]
  page: { next_cursor?: string; limit: number }
}

export interface KnowledgeStudioSourceDetail {
  dataset: KnowledgeStudioSourceDataset
  observed_at: string
  stale_at?: string
}

export type KnowledgeStudioPreviewScalar = string | number | boolean | null

export interface KnowledgeStudioValidationEvidence {
  severity: 'ERROR' | 'WARNING' | 'INFO'
  code: string
  location: string
  message: string
}

export interface KnowledgeStudioPreviewNode {
  id: string
  stable_element_id: string
  type: string
  identity: KnowledgeStudioPreviewScalar
  properties: Record<string, KnowledgeStudioPreviewScalar>
}

export interface KnowledgeStudioPreviewEdge {
  id: string
  stable_element_id: string
  type: string
  source_node_id: string
  target_node_id: string
  properties: Record<string, KnowledgeStudioPreviewScalar>
}

export interface KnowledgeStudioPreview {
  status: 'READY' | 'INVALID' | 'UNAVAILABLE'
  draft_version: number
  binding_version?: number
  target_stable_element_id: string
  dry_run: true
  sample_size: number
  graph: {
    nodes: KnowledgeStudioPreviewNode[]
    edges: KnowledgeStudioPreviewEdge[]
  }
  evidence: KnowledgeStudioValidationEvidence[]
}

export interface KnowledgeStudioPreflight {
  status: 'PASS' | 'FAIL' | 'UNAVAILABLE'
  valid: boolean
  draft_version: number
  checked_at: string
  receipt_id: string
  contract_hash: string
  evidence: KnowledgeStudioValidationEvidence[]
}

export interface KnowledgeStudioRelease {
  id: string
  graph_id: string
  ontology_version_id: string
  release_no: number
  state: 'ACTIVE' | 'ARCHIVED'
  contract_version: 'KNOWLEDGE_STUDIO_RELEASE_V1'
  contract_hash: string
  tbox_hash: string
  abox_hash: string
  supersedes_studio_release_id?: string
  reviewed_by: string
  published_by: string
  published_at: string
  archived_studio_release_id?: string
}

function requireEtag<T>(response: ApiResponse<T>): ApiResponse<T> {
  if (!response.etag) throw new Error('서버가 Draft ETag를 반환하지 않았습니다.')
  return response
}

export async function listKnowledgeStudioDomains(
  client: ApiClient,
  classification: KnowledgeClassification,
  query?: string,
  signal?: AbortSignal,
): Promise<KnowledgeStudioDomainOption[]> {
  const params = new URLSearchParams({ classification, limit: '100' })
  if (query?.trim()) params.set('q', query.trim())
  const response = await client.request<{ items: KnowledgeStudioDomainOption[] }>(
    `/knowledge/domains?${params.toString()}`,
    { cache: 'no-store', signal },
  )
  return response.items
}

export async function createKnowledgeStudioManagedDomain(
  client: ApiClient,
  displayName: string,
  idempotencyKey: string,
): Promise<KnowledgeStudioManagedDomain> {
  return client.request<KnowledgeStudioManagedDomain>('/knowledge/domains', {
    method: 'POST',
    cache: 'no-store',
    idempotencyKey,
    body: JSON.stringify({ display_name: displayName }),
  })
}

export async function updateKnowledgeStudioManagedDomain(
  client: ApiClient,
  domainId: string,
  displayName: string,
  version: number,
  idempotencyKey: string,
): Promise<KnowledgeStudioManagedDomain> {
  return client.request<KnowledgeStudioManagedDomain>(
    `/knowledge/domains/${encodeURIComponent(domainId)}`,
    {
      method: 'PATCH',
      cache: 'no-store',
      ifMatch: `"${version}"`,
      idempotencyKey,
      body: JSON.stringify({ display_name: displayName }),
    },
  )
}

export async function deleteKnowledgeStudioManagedDomain(
  client: ApiClient,
  domainId: string,
  version: number,
  idempotencyKey: string,
): Promise<void> {
  await client.request<void>(
    `/knowledge/domains/${encodeURIComponent(domainId)}`,
    {
      method: 'DELETE',
      cache: 'no-store',
      ifMatch: `"${version}"`,
      idempotencyKey,
    },
  )
}

export async function createKnowledgeStudioEditDraft(
  client: ApiClient,
  assetId: string,
  idempotencyKey: string,
): Promise<ApiResponse<KnowledgeStudioDraft>> {
  return requireEtag(await client.requestWithMeta<KnowledgeStudioDraft>(
    `/knowledge/studio/drafts/from-asset/${encodeURIComponent(assetId)}`,
    {
      method: 'POST',
      cache: 'no-store',
      idempotencyKey,
    },
  ))
}

export async function getKnowledgeStudioDraft(
  client: ApiClient,
  draftId: string,
): Promise<ApiResponse<KnowledgeStudioDraft>> {
  return requireEtag(await client.requestWithMeta<KnowledgeStudioDraft>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}`,
    { cache: 'no-store' },
  ))
}

export async function getResumableKnowledgeStudioDraft(
  client: ApiClient,
  endpointAlias: string,
): Promise<ApiResponse<KnowledgeStudioDraft>> {
  const params = new URLSearchParams({ endpoint_alias: endpointAlias })
  return requireEtag(await client.requestWithMeta<KnowledgeStudioDraft>(
    `/knowledge/studio/drafts/resumable?${params.toString()}`,
    { cache: 'no-store' },
  ))
}

export async function createKnowledgeStudioDraft(
  client: ApiClient,
  payload: KnowledgeStudioBasicInformation,
  idempotencyKey: string,
): Promise<ApiResponse<KnowledgeStudioDraft>> {
  return requireEtag(await client.requestWithMeta<KnowledgeStudioDraft>(
    '/knowledge/studio/drafts',
    {
      method: 'POST',
      body: JSON.stringify(payload),
      cache: 'no-store',
      idempotencyKey,
    },
  ))
}

export async function autosaveKnowledgeStudioDraft(
  client: ApiClient,
  draftId: string,
  payload: KnowledgeStudioBasicInformation,
  etag: string,
  idempotencyKey: string,
): Promise<ApiResponse<KnowledgeStudioDraft>> {
  return requireEtag(await client.requestWithMeta<KnowledgeStudioDraft>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}`,
    {
      method: 'PATCH',
      body: JSON.stringify(payload),
      cache: 'no-store',
      ifMatch: etag,
      idempotencyKey,
    },
  ))
}

export async function advanceKnowledgeStudioDraft(
  client: ApiClient,
  draftId: string,
  etag: string,
  idempotencyKey: string,
  targetStep: 'TBOX' | 'ABOX' = 'TBOX',
): Promise<ApiResponse<KnowledgeStudioDraft>> {
  return requireEtag(await client.requestWithMeta<KnowledgeStudioDraft>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/advance`,
    {
      method: 'POST',
      body: JSON.stringify({ target_step: targetStep }),
      cache: 'no-store',
      ifMatch: etag,
      idempotencyKey,
    },
  ))
}

export async function getKnowledgeStudioTBox(
  client: ApiClient,
  draftId: string,
  signal?: AbortSignal,
): Promise<ApiResponse<KnowledgeStudioTBox>> {
  return requireEtag(await client.requestWithMeta<KnowledgeStudioTBox>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/tbox`,
    { cache: 'no-store', signal },
  ))
}

export async function createKnowledgeStudioTBoxBlock(
  client: ApiClient,
  draftId: string,
  payload: {
    kind: KnowledgeStudioTBoxBlockKind
    title: string
    weight?: number
  },
  etag: string,
  idempotencyKey: string,
): Promise<ApiResponse<KnowledgeStudioTBox>> {
  return requireEtag(await client.requestWithMeta<KnowledgeStudioTBox>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/tbox/blocks`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
      cache: 'no-store',
      ifMatch: etag,
      idempotencyKey,
    },
  ))
}

export async function updateKnowledgeStudioTBoxBlock(
  client: ApiClient,
  draftId: string,
  blockId: string,
  payload: {
    title: string
    weight: number
    collapsed: boolean
  },
  etag: string,
  idempotencyKey: string,
): Promise<ApiResponse<KnowledgeStudioTBox>> {
  return requireEtag(await client.requestWithMeta<KnowledgeStudioTBox>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/tbox/blocks/${encodeURIComponent(blockId)}`,
    {
      method: 'PATCH',
      body: JSON.stringify(payload),
      cache: 'no-store',
      ifMatch: etag,
      idempotencyKey,
    },
  ))
}

export async function deleteKnowledgeStudioTBoxBlock(
  client: ApiClient,
  draftId: string,
  blockId: string,
  etag: string,
  idempotencyKey: string,
): Promise<ApiResponse<KnowledgeStudioTBox>> {
  return requireEtag(await client.requestWithMeta<KnowledgeStudioTBox>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/tbox/blocks/${encodeURIComponent(blockId)}`,
    {
      method: 'DELETE',
      cache: 'no-store',
      ifMatch: etag,
      idempotencyKey,
    },
  ))
}

export async function applyKnowledgeStudioTBoxOperations(
  client: ApiClient,
  draftId: string,
  blockId: string,
  operations: KnowledgeStudioTBoxOperation[],
  etag: string,
  idempotencyKey: string,
): Promise<ApiResponse<KnowledgeStudioTBox>> {
  return requireEtag(await client.requestWithMeta<KnowledgeStudioTBox>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/tbox/blocks/${encodeURIComponent(blockId)}/operations`,
    {
      method: 'POST',
      body: JSON.stringify({ operations }),
      cache: 'no-store',
      ifMatch: etag,
      idempotencyKey,
    },
  ))
}

export async function createKnowledgeStudioTBoxProposal(
  client: ApiClient,
  draftId: string,
  payload: {
    target_block_id?: string
    mode: 'MERGE_INTO_CURRENT' | 'APPEND_LAYER'
    prompt: string
  },
  etag: string,
): Promise<KnowledgeStudioTBoxProposal> {
  return client.request<KnowledgeStudioTBoxProposal>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/tbox/proposals`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
      cache: 'no-store',
      ifMatch: etag,
    },
  )
}

export async function createKnowledgeStudioTBoxCatalogProposal(
  client: ApiClient,
  draftId: string,
  payload: {
    asset_id: string
    selected_field_paths: string[]
    target_block_id?: string
    mode: 'MERGE_INTO_CURRENT' | 'APPEND_LAYER'
  },
  etag: string,
): Promise<KnowledgeStudioTBoxProposal> {
  return client.request<KnowledgeStudioTBoxProposal>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/tbox/catalog-proposals`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
      cache: 'no-store',
      ifMatch: etag,
    },
  )
}

export async function uploadKnowledgeStudioTBoxDocumentProposal(
  client: ApiClient,
  draftId: string,
  payload: {
    file: File
    upload_id: string
    target_block_id?: string
    mode: 'MERGE_INTO_CURRENT' | 'APPEND_LAYER'
  },
  etag: string,
): Promise<KnowledgeStudioTBoxProposal> {
  const body = new FormData()
  body.set('file', payload.file, payload.file.name)
  body.set('upload_id', payload.upload_id)
  body.set('mode', payload.mode)
  if (payload.target_block_id) body.set('target_block_id', payload.target_block_id)
  return client.request<KnowledgeStudioTBoxProposal>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/tbox/document-proposals`,
    {
      method: 'POST',
      body,
      cache: 'no-store',
      ifMatch: etag,
    },
  )
}

export async function applyKnowledgeStudioTBoxProposal(
  client: ApiClient,
  draftId: string,
  proposalId: string,
  payload: {
    merge_strategy: 'KEEP_ORIGINAL' | 'ACCEPT_PROPOSAL' | 'RESOLVE'
    resolutions: Array<{
      conflict_id: string
      action: 'KEEP_ORIGINAL' | 'ACCEPT_PROPOSAL' | 'RENAME_PROPOSAL'
      renamed_stable_element_id?: string
      renamed_canonical_name?: string
      renamed_display_name?: string
    }>
    excluded_stable_element_ids: string[]
    element_overrides: Array<{
      stable_element_id: string
      canonical_name: string
      display_name: string
      data_type?: string
    }>
  },
  etag: string,
  idempotencyKey: string,
): Promise<ApiResponse<KnowledgeStudioTBox>> {
  return requireEtag(await client.requestWithMeta<KnowledgeStudioTBox>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/tbox/proposals/${encodeURIComponent(proposalId)}/apply`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
      cache: 'no-store',
      ifMatch: etag,
      idempotencyKey,
    },
  ))
}

export async function getKnowledgeStudioABox(
  client: ApiClient,
  draftId: string,
): Promise<ApiResponse<KnowledgeStudioABox>> {
  return requireEtag(await client.requestWithMeta<KnowledgeStudioABox>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/abox`,
    { cache: 'no-store' },
  ))
}

export async function createKnowledgeStudioIngestion(
  client: ApiClient,
  draftId: string,
  etag: string,
  idempotencyKey: string,
): Promise<KnowledgeStudioIngestionJob> {
  return client.request<KnowledgeStudioIngestionJob>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/abox/ingestions`,
    {
      method: 'POST',
      cache: 'no-store',
      ifMatch: etag,
      idempotencyKey,
    },
  )
}

export async function listKnowledgeStudioIngestions(
  client: ApiClient,
  draftId: string,
  signal?: AbortSignal,
): Promise<KnowledgeStudioIngestionJob[]> {
  const result = await client.request<{ items: KnowledgeStudioIngestionJob[] }>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/abox/ingestions?limit=20`,
    { cache: 'no-store', signal },
  )
  return result.items
}

export async function searchKnowledgeStudioSources(
  client: ApiClient,
  draftId: string,
  query: string,
  signal?: AbortSignal,
): Promise<KnowledgeStudioSourcePage> {
  const params = new URLSearchParams({ q: query.trim(), limit: '25' })
  return client.request<KnowledgeStudioSourcePage>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/abox/sources?${params.toString()}`,
    { cache: 'no-store', signal },
  )
}

export async function searchKnowledgeStudioTBoxCatalogSources(
  client: ApiClient,
  draftId: string,
  query: string,
  filters?: {
    domain?: string
    search_fields?: string[]
  },
  signal?: AbortSignal,
): Promise<KnowledgeStudioSourcePage> {
  const params = new URLSearchParams({ q: query.trim(), limit: '25' })
  if (filters?.domain?.trim()) params.set('domain', filters.domain.trim())
  if (filters?.search_fields?.length) {
    params.set('search_fields', filters.search_fields.join(','))
  }
  return client.request<KnowledgeStudioSourcePage>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/tbox/catalog-sources?${params.toString()}`,
    { cache: 'no-store', signal },
  )
}

export async function getKnowledgeStudioTBoxCatalogSource(
  client: ApiClient,
  draftId: string,
  assetId: string,
): Promise<KnowledgeStudioSourceDetail> {
  return client.request<KnowledgeStudioSourceDetail>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/tbox/catalog-sources/${encodeURIComponent(assetId)}`,
    { cache: 'no-store' },
  )
}

export async function getKnowledgeStudioSource(
  client: ApiClient,
  draftId: string,
  assetId: string,
): Promise<KnowledgeStudioSourceDetail> {
  return client.request<KnowledgeStudioSourceDetail>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/abox/sources/${encodeURIComponent(assetId)}`,
    { cache: 'no-store' },
  )
}

export async function saveKnowledgeStudioBinding(
  client: ApiClient,
  draftId: string,
  targetStableElementId: string,
  source: KnowledgeStudioSourceDataset,
  rules: KnowledgeStudioMappingRuleInput[],
  etag: string,
  idempotencyKey: string,
): Promise<ApiResponse<{ draft: KnowledgeStudioDraft; binding: KnowledgeStudioBinding }>> {
  return requireEtag(await client.requestWithMeta<{
    draft: KnowledgeStudioDraft
    binding: KnowledgeStudioBinding
  }>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/abox/bindings/${encodeURIComponent(targetStableElementId)}`,
    {
      method: 'PATCH',
      body: JSON.stringify({
        source_asset_id: source.id,
        source_version: source.source_version,
        projection_source_version: source.projection_source_version,
        rules,
      }),
      cache: 'no-store',
      ifMatch: etag,
      idempotencyKey,
    },
  ))
}

export async function previewKnowledgeStudioBinding(
  client: ApiClient,
  draftId: string,
  targetStableElementId: string,
  etag: string,
  sampleLimit = 5,
): Promise<ApiResponse<KnowledgeStudioPreview>> {
  return requireEtag(await client.requestWithMeta<KnowledgeStudioPreview>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/abox/previews`,
    {
      method: 'POST',
      body: JSON.stringify({
        target_stable_element_id: targetStableElementId,
        sample_limit: sampleLimit,
      }),
      cache: 'no-store',
      ifMatch: etag,
    },
  ))
}

export async function preflightKnowledgeStudioABox(
  client: ApiClient,
  draftId: string,
  etag: string,
  idempotencyKey: string,
): Promise<ApiResponse<KnowledgeStudioPreflight>> {
  return requireEtag(await client.requestWithMeta<KnowledgeStudioPreflight>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/abox/preflight`,
    {
      method: 'POST',
      cache: 'no-store',
      ifMatch: etag,
      idempotencyKey,
    },
  ))
}

export async function submitKnowledgeStudioReview(
  client: ApiClient,
  draftId: string,
  etag: string,
  idempotencyKey: string,
): Promise<ApiResponse<KnowledgeStudioDraft>> {
  return requireEtag(await client.requestWithMeta<KnowledgeStudioDraft>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/submit-review`,
    {
      method: 'POST',
      cache: 'no-store',
      ifMatch: etag,
      idempotencyKey,
    },
  ))
}

export async function discardKnowledgeStudioDraft(
  client: ApiClient,
  draftId: string,
  etag: string,
  idempotencyKey: string,
): Promise<ApiResponse<KnowledgeStudioDraft>> {
  return requireEtag(await client.requestWithMeta<KnowledgeStudioDraft>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/discard`,
    {
      method: 'POST',
      cache: 'no-store',
      ifMatch: etag,
      idempotencyKey,
    },
  ))
}

export async function publishKnowledgeStudioDraft(
  client: ApiClient,
  draftId: string,
  reviewReason: string,
  etag: string,
  idempotencyKey: string,
): Promise<ApiResponse<{ draft: KnowledgeStudioDraft; release: KnowledgeStudioRelease }>> {
  return requireEtag(await client.requestWithMeta<{
    draft: KnowledgeStudioDraft
    release: KnowledgeStudioRelease
  }>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/publish`,
    {
      method: 'POST',
      body: JSON.stringify({ review_reason: reviewReason }),
      cache: 'no-store',
      ifMatch: etag,
      idempotencyKey,
    },
  ))
}

export function newKnowledgeStudioIdempotencyKey(): string {
  return `knowledge-studio-${crypto.randomUUID()}`
}
