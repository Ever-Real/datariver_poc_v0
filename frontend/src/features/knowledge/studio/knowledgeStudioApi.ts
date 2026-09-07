import type { ApiClient, ApiResponse } from '../../../api/client'

export type KnowledgeClassification = 'normal' | 'credential' | 'restricted'

export interface KnowledgeStudioBasicInformation {
  name: string
  description?: string
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

export interface KnowledgePropertyProfile {
  id: string
  description: string | null
  unit: string | null
  synonyms: string[]
  lifecycle: 'ACTIVE' | 'ARCHIVED'
  created_by: string
  updated_by: string
  archived_by: string | null
  created_at: string
  updated_at: string
  archived_at: string | null
  version: number
}

export interface KnowledgePropertyProfileItem {
  graph_id: string
  graph_name: string
  studio_release_id: string
  release_no: number
  ontology_version_id: string
  ontology_element_id: string
  stable_property_id: string
  property_name: string
  owner_class_id: string
  data_type: string
  property_urn: string
  profile: KnowledgePropertyProfile | null
}

export interface KnowledgePropertyProfileValues {
  description?: string
  unit?: string
  synonyms: string[]
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
  managed_intent?: string
  managed_graph_type?: string
  accepted_proposal_id?: string
  accepted_proposal_hash?: string
  source_contract_hash?: string
  mapping_contract_hash?: string
}

export interface KnowledgeStudioTBoxElement {
  stable_element_id: string
  kind: 'CLASS' | 'PROPERTY' | 'RELATION'
  canonical_name: string
  display_name: string
  parent_stable_element_id?: string
  owner_relation_stable_element_id?: string
  hierarchy_relation?: string
  source_stable_element_id?: string
  target_stable_element_id?: string
  data_type?: string
  nullable?: boolean
  value_cardinality?: 'SINGLE' | 'MULTI'
  direction?: 'DIRECTED' | 'BIDIRECTED' | 'UNDIRECTED'
  cardinality?: 'UNSPECIFIED' | 'ONE_TO_ONE' | 'ONE_TO_MANY' | 'MANY_TO_ONE' | 'MANY_TO_MANY'
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

export const knowledgeStudioPropertyDataTypes = [
  'STRING',
  'TEXT',
  'INTEGER',
  'FLOAT',
  'BOOLEAN',
  'DATE',
  'DATETIME',
] as const

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

export type KnowledgeStudioSourceUploadState =
  | 'INITIATED'
  | 'COMPLETION_QUEUED'
  | 'COMPLETING'
  | 'QUARANTINED'
  | 'VALIDATING'
  | 'ACCEPTED'
  | 'REJECTED'
  | 'ABORTED'
  | 'EXPIRED'

export interface KnowledgeStudioSourceUpload {
  id: string
  display_name: string
  state: KnowledgeStudioSourceUploadState
  size_bytes: number
  content_type: string
  sha256: string
  classification: KnowledgeClassification
  content_profile: 'KNOWLEDGE_STUDIO_DOCUMENT_V1'
  expires_at: string
  version: number
  validation_summary: Record<string, unknown>
  last_error_code: string | null
  recommended_part_size_bytes: number
}

export type KnowledgeStudioProposalJobState =
  | 'QUEUED'
  | 'RUNNING'
  | 'RETRY_WAIT'
  | 'CANCEL_REQUESTED'
  | 'SUCCEEDED'
  | 'FAILED'
  | 'STALE'
  | 'CANCELLED'

export type KnowledgeStudioProposalJobStage =
  | 'QUEUED'
  | 'SOURCE_VALIDATION'
  | 'PARSING'
  | 'INFERENCE'
  | 'VALIDATING'
  | 'FINALIZING'
  | 'COMPLETED'

export interface KnowledgeStudioProposalJob {
  id: string
  draft_id: string
  input_kind: 'DOCUMENT_SCHEMA' | 'CATALOG_SCHEMA'
  mode: 'MERGE_INTO_CURRENT' | 'APPEND_LAYER'
  target_block_id: string | null
  state: KnowledgeStudioProposalJobState
  stage: KnowledgeStudioProposalJobStage
  progress_percent: number
  attempt_count: number
  maximum_attempts: number
  last_failure_code: string | null
  version: number
  created_at: string
  updated_at: string
  completed_at: string | null
  result_proposal_id: string | null
  result_evidence_hash: string | null
  supersedes_job_id: string | null
}

export interface KnowledgeStudioProposalJobPage {
  items: KnowledgeStudioProposalJob[]
  page: {
    next_cursor: string | null
    limit: number
  }
}

export type KnowledgeStudioIngestionState =
  | 'PENDING'
  | 'RUNNING'
  | 'RETRY_WAIT'
  | 'CANCEL_REQUESTED'
  | 'SUCCESS'
  | 'FAILED'
  | 'STALE'
  | 'CANCELLED'

export type KnowledgeStudioIngestionAction = 'CANCEL' | 'RETRY'

export interface KnowledgeStudioIngestionJob {
  id: string
  draft_id: string
  graph_id: string
  studio_release_id: string
  requested_by: string
  state: KnowledgeStudioIngestionState
  progress_percent: number
  current_stage: string
  vector_target_count: number
  attempt_count: number
  maximum_attempts: number
  result_changeset_id: string | null
  result_evidence_hash: string | null
  error_code: string | null
  allowed_actions: KnowledgeStudioIngestionAction[]
  version: number
  created_at: string
  updated_at: string
  started_at: string | null
  finished_at: string | null
  node_count?: number
  edge_count?: number
  duplicate_count?: number
  pinned_tbox_version?: number
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
  description?: string
  description_truncated: boolean
  field_metadata: KnowledgeStudioCatalogFieldMetadata[]
  selection_fingerprint?: string | null
}

export interface KnowledgeStudioCatalogFieldMetadata {
  field_path: string
  field_urn?: string | null
  field_type?: string | null
  native_data_type?: string | null
  description?: string | null
  description_truncated: boolean
  tags: string[]
  tags_truncated: boolean
  glossary_terms: string[]
  terms_truncated: boolean
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

export interface KnowledgeStudioTBoxAssetRelease {
  graph_id: string
  graph_name: string
  graph_slug: string
  classification: KnowledgeClassification
  domain_name?: string
  studio_release_id: string
  release_no: number
  state: 'ACTIVE' | 'ARCHIVED'
  contract_hash: string
  tbox_hash: string
  published_at: string
  class_count: number
  property_count: number
  relationship_count: number
}

export interface KnowledgeStudioTBoxAssetReleasePage {
  items: KnowledgeStudioTBoxAssetRelease[]
  page: { next_cursor?: string | null; limit: number }
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
  job_id: string
  status: 'READY' | 'INVALID' | 'UNAVAILABLE'
  draft_version: number
  plan_mode?: 'NODE' | 'RELATION'
  binding_version?: number
  binding_versions?: Record<string, number>
  target_stable_element_id: string | null
  target_stable_element_ids?: string[]
  relation_stable_element_id?: string | null
  pinned_tbox_version: number
  node_count: number
  relation_count: number
  source: {
    asset_urn: string
    source_version: string
    manifest_ref: string
  }
  dry_run: true
  sample_size: number
  graph: {
    nodes: KnowledgeStudioPreviewNode[]
    edges: KnowledgeStudioPreviewEdge[]
  }
  rejected: Array<{ row_key?: string; source_field_path?: string; reason: string }>
  unmapped: Array<{ row_key: string; source_field_path: string; target_stable_element_id: string }>
  evidence: KnowledgeStudioValidationEvidence[]
  provenance: Array<{
    entity_kind?: 'NODE' | 'RELATION'
    source_type: string
    source_urn: string
    source_row_key: string
    source_hash: string
    graph_id: string
    studio_release_id: string
    tbox_version: number
    manifest_ref: string
    secret_ref: string
    relation_stable_element_id?: string
    source_node_id?: string
    target_node_id?: string
  }>
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

export async function listKnowledgeStudioManagedDomains(
  client: ApiClient,
  signal?: AbortSignal,
): Promise<KnowledgeStudioManagedDomain[]> {
  const response = await client.request<{ items: KnowledgeStudioManagedDomain[] }>(
    '/knowledge/domains/manage?limit=100',
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

export async function listKnowledgePropertyProfiles(
  client: ApiClient,
  query = '',
  signal?: AbortSignal,
): Promise<KnowledgePropertyProfileItem[]> {
  const params = new URLSearchParams({ q: query.trim(), limit: '200' })
  const response = await client.request<{ items: KnowledgePropertyProfileItem[] }>(
    `/knowledge/property-profiles?${params.toString()}`,
    { cache: 'no-store', signal },
  )
  return response.items
}

export async function createKnowledgePropertyProfile(
  client: ApiClient,
  ontologyElementId: string,
  values: KnowledgePropertyProfileValues,
  idempotencyKey: string,
): Promise<KnowledgePropertyProfile> {
  return client.request<KnowledgePropertyProfile>('/knowledge/property-profiles', {
    method: 'POST',
    cache: 'no-store',
    idempotencyKey,
    body: JSON.stringify({
      ontology_element_id: ontologyElementId,
      ...values,
    }),
  })
}

export async function updateKnowledgePropertyProfile(
  client: ApiClient,
  profileId: string,
  version: number,
  values: KnowledgePropertyProfileValues,
  idempotencyKey: string,
): Promise<KnowledgePropertyProfile> {
  return client.request<KnowledgePropertyProfile>(
    `/knowledge/property-profiles/${encodeURIComponent(profileId)}`,
    {
      method: 'PATCH',
      cache: 'no-store',
      ifMatch: `"${version}"`,
      idempotencyKey,
      body: JSON.stringify(values),
    },
  )
}

export async function archiveKnowledgePropertyProfile(
  client: ApiClient,
  profileId: string,
  version: number,
  idempotencyKey: string,
): Promise<KnowledgePropertyProfile> {
  return client.request<KnowledgePropertyProfile>(
    `/knowledge/property-profiles/${encodeURIComponent(profileId)}`,
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

export async function createKnowledgeStudioManagedDraft(
  client: ApiClient,
  intent: string,
  payload: KnowledgeStudioBasicInformation,
  idempotencyKey: string,
): Promise<ApiResponse<KnowledgeStudioDraft>> {
  return requireEtag(await client.requestWithMeta<KnowledgeStudioDraft>(
    `/knowledge/studio/managed-drafts/${encodeURIComponent(intent)}`,
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

export async function getKnowledgeStudioTBoxProposal(
  client: ApiClient,
  draftId: string,
  proposalId: string,
  signal?: AbortSignal,
): Promise<KnowledgeStudioTBoxProposal> {
  return client.request<KnowledgeStudioTBoxProposal>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/tbox/proposals/${encodeURIComponent(proposalId)}`,
    { cache: 'no-store', signal },
  )
}

export async function initiateKnowledgeStudioSourceUpload(
  client: ApiClient,
  draftId: string,
  payload: {
    display_name: string
    size_bytes: number
    content_type: string
    sha256: string
  },
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<ApiResponse<KnowledgeStudioSourceUpload>> {
  return requireEtag(await client.requestWithMeta<KnowledgeStudioSourceUpload>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/source-uploads`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
      cache: 'no-store',
      idempotencyKey,
      signal,
    },
  ))
}

export async function presignKnowledgeStudioSourceUploadPart(
  client: ApiClient,
  draftId: string,
  uploadId: string,
  partNumber: number,
  signal?: AbortSignal,
): Promise<{ url: string; expires_seconds: number }> {
  return client.request<{ url: string; expires_seconds: number }>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/source-uploads/${encodeURIComponent(uploadId)}/parts`,
    {
      method: 'POST',
      body: JSON.stringify({ part_number: partNumber }),
      cache: 'no-store',
      signal,
    },
  )
}

export async function uploadKnowledgeStudioSourceUploadPart(
  url: string,
  file: File,
  signal?: AbortSignal,
): Promise<{ part_number: 1; etag: string }> {
  const response = await fetch(url, {
    method: 'PUT',
    body: file,
    signal,
  })
  if (!response.ok) {
    throw new Error(`오브젝트 스토리지 업로드에 실패했습니다. (${response.status})`)
  }
  const etag = response.headers.get('ETag')?.replaceAll('"', '').trim()
  if (!etag) {
    throw new Error(
      '오브젝트 스토리지 응답에서 ETag를 확인할 수 없습니다. CORS 설정을 확인하세요.',
    )
  }
  return { part_number: 1, etag }
}

export async function completeKnowledgeStudioSourceUpload(
  client: ApiClient,
  draftId: string,
  uploadId: string,
  parts: Array<{ part_number: number; etag: string }>,
  uploadEtag: string,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<ApiResponse<KnowledgeStudioSourceUpload>> {
  return requireEtag(await client.requestWithMeta<KnowledgeStudioSourceUpload>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/source-uploads/${encodeURIComponent(uploadId)}/complete`,
    {
      method: 'POST',
      body: JSON.stringify({ parts }),
      cache: 'no-store',
      ifMatch: uploadEtag,
      idempotencyKey,
      signal,
    },
  ))
}

export async function getKnowledgeStudioSourceUpload(
  client: ApiClient,
  draftId: string,
  uploadId: string,
  signal?: AbortSignal,
): Promise<ApiResponse<KnowledgeStudioSourceUpload>> {
  return requireEtag(await client.requestWithMeta<KnowledgeStudioSourceUpload>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/source-uploads/${encodeURIComponent(uploadId)}`,
    { cache: 'no-store', signal },
  ))
}

export async function createKnowledgeStudioTBoxProposalJob(
  client: ApiClient,
  draftId: string,
  payload:
    | {
        input_kind: 'DOCUMENT_SCHEMA'
        source_upload_id: string
        source_manifest_version: number
        target_block_id?: string
        mode: 'MERGE_INTO_CURRENT' | 'APPEND_LAYER'
      }
    | {
        input_kind: 'CATALOG_SCHEMA'
        asset_id: string
        selected_field_paths: string[]
        expected_selection_fingerprint: string
        target_block_id?: string
        mode: 'MERGE_INTO_CURRENT' | 'APPEND_LAYER'
      },
  draftEtag: string,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<ApiResponse<KnowledgeStudioProposalJob>> {
  return requireEtag(await client.requestWithMeta<KnowledgeStudioProposalJob>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/tbox/proposal-jobs`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
      cache: 'no-store',
      ifMatch: draftEtag,
      idempotencyKey,
      signal,
    },
  ))
}

export async function listKnowledgeStudioTBoxProposalJobs(
  client: ApiClient,
  draftId: string,
  cursor?: string,
  signal?: AbortSignal,
): Promise<KnowledgeStudioProposalJobPage> {
  const params = new URLSearchParams({ limit: '20' })
  if (cursor) params.set('cursor', cursor)
  return client.request<KnowledgeStudioProposalJobPage>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/tbox/proposal-jobs?${params.toString()}`,
    { cache: 'no-store', signal },
  )
}

export async function getKnowledgeStudioTBoxProposalJob(
  client: ApiClient,
  draftId: string,
  jobId: string,
  signal?: AbortSignal,
): Promise<ApiResponse<KnowledgeStudioProposalJob>> {
  return requireEtag(await client.requestWithMeta<KnowledgeStudioProposalJob>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/tbox/proposal-jobs/${encodeURIComponent(jobId)}`,
    { cache: 'no-store', signal },
  ))
}

export async function cancelKnowledgeStudioTBoxProposalJob(
  client: ApiClient,
  draftId: string,
  jobId: string,
  reason: string,
  jobEtag: string,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<ApiResponse<KnowledgeStudioProposalJob>> {
  return requireEtag(await client.requestWithMeta<KnowledgeStudioProposalJob>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/tbox/proposal-jobs/${encodeURIComponent(jobId)}/cancel`,
    {
      method: 'POST',
      body: JSON.stringify({ reason }),
      cache: 'no-store',
      ifMatch: jobEtag,
      idempotencyKey,
      signal,
    },
  ))
}

export async function retryKnowledgeStudioTBoxProposalJob(
  client: ApiClient,
  draftId: string,
  jobId: string,
  jobEtag: string,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<ApiResponse<KnowledgeStudioProposalJob>> {
  return requireEtag(await client.requestWithMeta<KnowledgeStudioProposalJob>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/tbox/proposal-jobs/${encodeURIComponent(jobId)}/retry`,
    {
      method: 'POST',
      body: JSON.stringify({}),
      cache: 'no-store',
      ifMatch: jobEtag,
      idempotencyKey,
      signal,
    },
  ))
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
  previewJobId: string,
  targetStableElementId: string,
): Promise<KnowledgeStudioIngestionJob> {
  return client.request<KnowledgeStudioIngestionJob>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/abox/ingestions`,
    {
      method: 'POST',
      cache: 'no-store',
      ifMatch: etag,
      idempotencyKey,
      body: JSON.stringify({
        preview_job_id: previewJobId,
        target_stable_element_id: targetStableElementId,
      }),
    },
  )
}

export async function createKnowledgeStudioRelationIngestion(
  client: ApiClient,
  draftId: string,
  etag: string,
  idempotencyKey: string,
  previewJobId: string,
  relationStableElementId: string,
): Promise<KnowledgeStudioIngestionJob> {
  return client.request<KnowledgeStudioIngestionJob>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/abox/ingestions`,
    {
      method: 'POST',
      cache: 'no-store',
      ifMatch: etag,
      idempotencyKey,
      body: JSON.stringify({
        preview_job_id: previewJobId,
        relation_stable_element_id: relationStableElementId,
      }),
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

export async function cancelKnowledgeStudioIngestion(
  client: ApiClient,
  draftId: string,
  jobId: string,
  version: number,
  reason: string,
  idempotencyKey: string,
): Promise<KnowledgeStudioIngestionJob> {
  return client.request<KnowledgeStudioIngestionJob>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/abox/ingestions/${
      encodeURIComponent(jobId)
    }/cancel`,
    {
      method: 'POST',
      body: JSON.stringify({ reason: reason.trim() }),
      cache: 'no-store',
      ifMatch: `"${version}"`,
      idempotencyKey,
    },
  )
}

export async function retryKnowledgeStudioIngestion(
  client: ApiClient,
  draftId: string,
  jobId: string,
  version: number,
  idempotencyKey: string,
): Promise<KnowledgeStudioIngestionJob> {
  return client.request<KnowledgeStudioIngestionJob>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/abox/ingestions/${
      encodeURIComponent(jobId)
    }/retry`,
    {
      method: 'POST',
      cache: 'no-store',
      ifMatch: `"${version}"`,
      idempotencyKey,
    },
  )
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
    cursor?: string
  },
  signal?: AbortSignal,
): Promise<KnowledgeStudioSourcePage> {
  const params = new URLSearchParams({ q: query.trim(), limit: '50' })
  if (filters?.domain?.trim()) params.set('domain', filters.domain.trim())
  if (filters?.search_fields?.length) {
    params.set('search_fields', filters.search_fields.join(','))
  }
  if (filters?.cursor) params.set('cursor', filters.cursor)
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

export async function searchKnowledgeStudioTBoxAssetReleases(
  client: ApiClient,
  draftId: string,
  query: string,
  signal?: AbortSignal,
): Promise<KnowledgeStudioTBoxAssetReleasePage> {
  const params = new URLSearchParams({ q: query.trim(), limit: '50' })
  return client.request<KnowledgeStudioTBoxAssetReleasePage>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/tbox/asset-releases?${params.toString()}`,
    { cache: 'no-store', signal },
  )
}

export async function createKnowledgeStudioTBoxAssetReleaseProposal(
  client: ApiClient,
  draftId: string,
  payload: {
    studio_release_id: string
    tbox_hash: string
    target_block_id?: string
    mode: 'MERGE_INTO_CURRENT' | 'APPEND_LAYER'
  },
  etag: string,
): Promise<KnowledgeStudioTBoxProposal> {
  return client.request<KnowledgeStudioTBoxProposal>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/tbox/asset-release-proposals`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
      cache: 'no-store',
      ifMatch: etag,
    },
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

export async function previewKnowledgeStudioRelation(
  client: ApiClient,
  draftId: string,
  relationStableElementId: string,
  etag: string,
  sampleLimit = 5,
): Promise<ApiResponse<KnowledgeStudioPreview>> {
  return requireEtag(await client.requestWithMeta<KnowledgeStudioPreview>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/abox/previews`,
    {
      method: 'POST',
      body: JSON.stringify({
        relation_stable_element_id: relationStableElementId,
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
