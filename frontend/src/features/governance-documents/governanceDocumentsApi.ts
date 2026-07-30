import type { ApiClient, ApiResponse } from '../../api/client'
import type {
  GovernanceDocumentAttachment,
  GovernanceDocumentBlueprintListResponse,
  GovernanceDocumentCapability,
  GovernanceDocumentCommandResponse,
  GovernanceDocumentCreateRequest,
  GovernanceDocumentDetailResponse,
  GovernanceDocumentKind,
  GovernanceDocumentListResponse,
  GovernanceDocumentReviewRequest,
  GovernanceDocumentVersionCreateRequest,
  GovernanceKnowledgeEvidenceResponse,
  GovernanceReadEnvelope,
} from './types'

const BASE_PATH = '/governance/documents'

export type GovernanceDocumentResource =
  | 'documents'
  | 'document-detail'
  | 'templates'
  | 'template-blueprints'
  | 'knowledge-evidence'

export function governanceDocumentQueryKey(
  cacheScope: string,
  resource: GovernanceDocumentResource,
  ...scope: readonly unknown[]
) {
  return ['governance-documents', cacheScope, resource, ...scope] as const
}

export class GovernanceDocumentsApi {
  constructor(private readonly client: Pick<ApiClient, 'request' | 'requestWithMeta'>) {}

  async capability(signal?: AbortSignal): Promise<GovernanceDocumentCapability> {
    const value = await this.client.request<GovernanceDocumentCapability>(
      `${BASE_PATH}/capability`,
      { cache: 'no-store', signal },
    )
    assertCapability(value)
    return value
  }

  async documents(
    expectedCacheScope: string,
    options: {
      cursor?: string
      query?: string
      kind?: GovernanceDocumentKind
      includeArchived?: boolean
      limit: number
      signal?: AbortSignal
    },
  ): Promise<GovernanceDocumentListResponse> {
    const query = new URLSearchParams({ limit: String(options.limit) })
    if (options.cursor) query.set('cursor', options.cursor)
    if (options.query?.trim()) query.set('q', options.query.trim())
    if (options.kind) query.set('kind', options.kind)
    if (options.includeArchived) query.set('include_archived', 'true')
    const value = await this.client.request<GovernanceDocumentListResponse>(
      `${BASE_PATH}?${query.toString()}`,
      { cache: 'no-store', signal: options.signal },
    )
    assertList(value, expectedCacheScope, options.limit)
    return value
  }

  async document(
    documentId: string,
    expectedCacheScope: string,
    signal?: AbortSignal,
  ): Promise<ApiResponse<GovernanceDocumentDetailResponse>> {
    const response = await this.client.requestWithMeta<GovernanceDocumentDetailResponse>(
      `${BASE_PATH}/${encodeURIComponent(documentId)}`,
      { cache: 'no-store', signal },
    )
    if (
      response.data?.item?.document?.document_id !== documentId
      || response.data.cache_scope !== expectedCacheScope
      || !validReadEnvelope(response.data)
      || !response.etag
      || !isPositiveInteger(response.data.item.document.version)
    ) {
      throw new Error('거버넌스 문서 상세와 변경 버전을 확인할 수 없습니다.')
    }
    assertDetail(response.data.item)
    return response
  }

  async createDocument(
    payload: GovernanceDocumentCreateRequest,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<GovernanceDocumentCommandResponse> {
    const response = await this.client.requestWithMeta<GovernanceDocumentCommandResponse>(
      BASE_PATH,
      {
        method: 'POST',
        cache: 'no-store',
        signal,
        idempotencyKey,
        body: JSON.stringify(payload),
      },
    )
    assertCommand(response.data, response.etag)
    return response.data
  }

  async templateBlueprints(
    signal?: AbortSignal,
  ): Promise<GovernanceDocumentBlueprintListResponse> {
    const value = await this.client.request<GovernanceDocumentBlueprintListResponse>(
      `${BASE_PATH}/template-blueprints`,
      { cache: 'no-store', signal },
    )
    const categories = new Set(value?.items?.map((item) => item.category))
    if (
      value?.contract_version !== 'GOVERNANCE_DOCUMENT_BLUEPRINTS_V1'
      || !Array.isArray(value.items)
      || value.items.length !== 3
      || categories.size !== 3
      || !categories.has('POLICY')
      || !categories.has('STANDARD_TERMINOLOGY')
      || !categories.has('SECURITY_GUIDE')
      || value.items.some((item) => (
        item.blueprint_version !== value.contract_version
        || !item.blueprint_id
        || !item.title
        || !item.sanitized_html
        || !validSha256(item.content_sha256)
        || !validSha256(item.sanitizer_policy_sha256)
      ))
    ) {
      throw new Error('거버넌스 기본 양식 계약이 올바르지 않습니다.')
    }
    return value
  }

  async createVersion(
    documentId: string,
    expectedVersion: number,
    payload: GovernanceDocumentVersionCreateRequest,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<GovernanceDocumentCommandResponse> {
    return this.command(
      `${BASE_PATH}/${encodeURIComponent(documentId)}/versions`,
      documentId,
      expectedVersion,
      idempotencyKey,
      payload,
      signal,
    )
  }

  async importVersion(
    documentId: string,
    expectedVersion: number,
    file: File,
    title: string,
    applicabilityScope: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<GovernanceDocumentCommandResponse> {
    const body = new FormData()
    body.set('file', file)
    body.set('title', title)
    body.set('applicability_scope', applicabilityScope)
    return this.command(
      `${BASE_PATH}/${encodeURIComponent(documentId)}/versions`,
      documentId,
      expectedVersion,
      idempotencyKey,
      body,
      signal,
    )
  }

  async submitVersion(
    documentId: string,
    versionId: string,
    expectedVersion: number,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<GovernanceDocumentCommandResponse> {
    return this.command(
      `${BASE_PATH}/${encodeURIComponent(documentId)}/versions/${encodeURIComponent(versionId)}/submissions`,
      documentId,
      expectedVersion,
      idempotencyKey,
      {},
      signal,
    )
  }

  async reviewVersion(
    documentId: string,
    versionId: string,
    expectedVersion: number,
    payload: GovernanceDocumentReviewRequest,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<GovernanceDocumentCommandResponse> {
    return this.command(
      `${BASE_PATH}/${encodeURIComponent(documentId)}/versions/${encodeURIComponent(versionId)}/reviews`,
      documentId,
      expectedVersion,
      idempotencyKey,
      payload,
      signal,
    )
  }

  async archiveDocument(
    documentId: string,
    expectedVersion: number,
    reason: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<GovernanceDocumentCommandResponse> {
    return this.command(
      `${BASE_PATH}/${encodeURIComponent(documentId)}/archive`,
      documentId,
      expectedVersion,
      idempotencyKey,
      { reason },
      signal,
    )
  }

  async uploadAttachment(
    documentId: string,
    versionId: string,
    expectedVersion: number,
    file: File,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<GovernanceDocumentAttachment> {
    const body = new FormData()
    body.set('file', file)
    const value = await this.client.request<GovernanceDocumentAttachment>(
      `${BASE_PATH}/${encodeURIComponent(documentId)}/versions/${encodeURIComponent(versionId)}/attachments`,
      {
        method: 'POST',
        cache: 'no-store',
        signal,
        ifMatch: `"${expectedVersion}"`,
        idempotencyKey,
        body,
      },
    )
    if (
      !value?.attachment_id
      || value.document_id !== documentId
      || value.document_version_id !== versionId
      || !validSha256(value.content_sha256)
    ) {
      throw new Error('거버넌스 문서 첨부 증빙을 확인할 수 없습니다.')
    }
    return value
  }

  async knowledgeEvidence(
    expectedCacheScope: string,
    query: string,
    signal?: AbortSignal,
  ): Promise<GovernanceKnowledgeEvidenceResponse> {
    const search = new URLSearchParams({ q: query.trim() })
    const value = await this.client.request<GovernanceKnowledgeEvidenceResponse>(
      `${BASE_PATH}/knowledge/evidence?${search.toString()}`,
      { cache: 'no-store', signal },
    )
    if (
      !Array.isArray(value?.items)
      || value.cache_scope !== expectedCacheScope
      || !validReadEnvelope(value)
      || value.items.some((item) => !validSha256(item.content_sha256))
    ) {
      throw new Error('거버넌스 문서 지식 근거 계약이 올바르지 않습니다.')
    }
    return value
  }

  private async command(
    path: string,
    documentId: string,
    expectedVersion: number,
    idempotencyKey: string,
    payload: object | FormData,
    signal?: AbortSignal,
  ): Promise<GovernanceDocumentCommandResponse> {
    const response = await this.client.requestWithMeta<GovernanceDocumentCommandResponse>(path, {
      method: 'POST',
      cache: 'no-store',
      signal,
      ifMatch: `"${expectedVersion}"`,
      idempotencyKey,
      body: payload instanceof FormData ? payload : JSON.stringify(payload),
    })
    assertCommand(response.data, response.etag)
    const value = response.data
    if (value.item.document.document_id !== documentId) {
      throw new Error('거버넌스 문서 명령 대상이 일치하지 않습니다.')
    }
    return value
  }
}

function assertCapability(value: GovernanceDocumentCapability): void {
  const ids = new Set([
    'read',
    'create',
    'edit',
    'review',
    'publish',
    'archive',
    'template_manage',
    'artifact_storage',
    'knowledge_projection',
  ])
  const limits = [
    value?.limits?.max_html_bytes,
    value?.limits?.max_attachment_bytes,
    value?.limits?.max_attachments_per_version,
  ]
  if (
    !value
    || value.contract_version !== 'GOVERNANCE_DOCUMENT_CAPABILITY_V1'
    || !validDate(value.observed_at)
    || !validDate(value.valid_until)
    || Date.parse(value.valid_until) <= Date.parse(value.observed_at)
    || !validCacheScope(value.cache_scope)
    || !Array.isArray(value.axes)
    || value.axes.length !== ids.size
    || new Set(value.axes.map((axis) => axis.id)).size !== ids.size
    || value.axes.some((axis) => (
      !ids.has(axis.id)
      || !['AVAILABLE', 'DENIED', 'UNAVAILABLE'].includes(axis.state)
    ))
    || limits.some((limit) => !isPositiveInteger(limit))
  ) {
    throw new Error('거버넌스 문서 capability 계약이 올바르지 않습니다.')
  }
}

function assertList(
  value: GovernanceDocumentListResponse,
  expectedCacheScope: string,
  requestedLimit: number,
): void {
  if (
    !value
    || !Array.isArray(value.items)
    || value.items.length > requestedLimit
    || value.page?.limit !== requestedLimit
    || (
      value.page.next_cursor !== null
      && (typeof value.page.next_cursor !== 'string' || !value.page.next_cursor)
    )
    || value.cache_scope !== expectedCacheScope
    || !validReadEnvelope(value)
    || value.items.some((item) => (
      !item.document_id
      || !isPositiveInteger(item.version)
      || !Array.isArray(item.allowed_actions)
    ))
  ) {
    throw new Error('거버넌스 문서 목록 계약이 올바르지 않습니다.')
  }
}

function assertCommand(value: GovernanceDocumentCommandResponse, etag?: string): void {
  if (
    !value?.item?.document?.document_id
    || !isPositiveInteger(value.item.document.version)
    || (etag !== undefined && !etag)
  ) {
    throw new Error('거버넌스 문서 명령 응답이 올바르지 않습니다.')
  }
  assertDetail(value.item)
}

function assertDetail(value: GovernanceDocumentCommandResponse['item']): void {
  if (
    !Array.isArray(value.versions)
    || !Array.isArray(value.reviews)
    || !Array.isArray(value.attachments)
    || value.versions.some((version) => (
      version.document_id !== value.document.document_id
      || !isPositiveInteger(version.version)
      || !validSha256(version.content_sha256)
      || !validSha256(version.sanitizer_policy_sha256)
    ))
  ) {
    throw new Error('거버넌스 문서 상세 계약이 올바르지 않습니다.')
  }
}

function validReadEnvelope(value: GovernanceReadEnvelope): boolean {
  return (
    validCacheScope(value.cache_scope)
    && validDate(value.observed_at)
    && validDate(value.authorization_valid_until)
  )
}

function validCacheScope(value: string): boolean {
  return typeof value === 'string' && /^[0-9a-f]{64}$/.test(value)
}

function validSha256(value: string): boolean {
  return typeof value === 'string' && /^[0-9a-f]{64}$/.test(value)
}

function validDate(value: string): boolean {
  return typeof value === 'string' && Number.isFinite(Date.parse(value))
}

function isPositiveInteger(value: number): boolean {
  return Number.isSafeInteger(value) && value > 0
}
