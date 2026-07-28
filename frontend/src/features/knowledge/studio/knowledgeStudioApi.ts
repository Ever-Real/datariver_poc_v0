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
    `/knowledge/studio/domains?${params.toString()}`,
    { cache: 'no-store', signal },
  )
  return response.items
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
): Promise<ApiResponse<KnowledgeStudioDraft>> {
  return requireEtag(await client.requestWithMeta<KnowledgeStudioDraft>(
    `/knowledge/studio/drafts/${encodeURIComponent(draftId)}/advance`,
    {
      method: 'POST',
      body: JSON.stringify({ target_step: 'TBOX' }),
      cache: 'no-store',
      ifMatch: etag,
      idempotencyKey,
    },
  ))
}

export function newKnowledgeStudioIdempotencyKey(): string {
  return `knowledge-studio-${crypto.randomUUID()}`
}
