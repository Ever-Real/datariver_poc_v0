import type { ApiClient, ApiResponse } from '../../../api/client'

export type KnowledgeClassification = 'PUBLIC' | 'INTERNAL' | 'CONFIDENTIAL' | 'RESTRICTED'

export interface KnowledgeStudioBasicInformation {
  name: string
  endpoint_alias: string
  domain_id: string
  domain_source_version: string
  classification: KnowledgeClassification
}

export interface KnowledgeStudioDomainOption {
  id: string
  display_name: string
  source_version: string
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
  source_stable_element_id?: string
  target_stable_element_id?: string
  data_type?: string
  nullable?: boolean
  ordinal: number
  version: number
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

export async function getKnowledgeStudioABox(
  client: ApiClient,
  draftId: string,
): Promise<ApiResponse<KnowledgeStudioABox>> {
  return requireEtag(await client.requestWithMeta<KnowledgeStudioABox>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/abox`,
    { cache: 'no-store' },
  ))
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
