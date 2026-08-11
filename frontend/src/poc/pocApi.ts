import type {
  ApiClient,
  ApiDownload,
  ApiEventStreamHandler,
  ApiResponse,
} from '../api/client'
import type {
  ChangeRequestState,
  ChatMessage,
  ChatMode,
  ChatSession,
} from '../api/types'
import {
  POC_CACHE_SCOPE,
  POC_NOW,
  POC_SUBJECT_ID,
  POC_WORKSPACE_ID,
  authorizationWindow,
  catalogAssets,
  catalogDetail,
  catalogLineage,
  catalogMeta,
  changeRecord,
  changeSummary,
  chatEvidence,
  chatWorkflow,
  initialChatMessages,
  initialChatSession,
  knowledgeAsset,
  knowledgeDetail,
  knowledgeGraph,
  knowledgeRelease,
  knowledgeSnapshot,
  qualityAsset,
  qualityAuthoring,
  qualityRuleSet,
  qualityRun,
  scorePolicy,
} from './pocFixtures'

interface PocRequestOptions extends RequestInit {
  idempotencyKey?: string
  ifMatch?: string
}

interface PocRuntimeFlags {
  datahub?: boolean
  airflow?: boolean
  minio?: boolean
  llmChat?: boolean
  llmEmbedding?: boolean
  llmReranker?: boolean
  neo4j?: boolean
}

function runtimeFlags(): PocRuntimeFlags {
  return (globalThis as typeof globalThis & {
    __DATARIVER_POC_RUNTIME__?: PocRuntimeFlags
  }).__DATARIVER_POC_RUNTIME__ ?? {}
}

function responseString(value: unknown, fallback: string): string {
  return typeof value === 'string' || typeof value === 'number'
    ? String(value)
    : fallback
}

async function gatewayRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options.headers },
  })
  if (!response.ok) {
    const problem = await response.json().catch(() => ({})) as { detail?: unknown }
    throw new Error(typeof problem.detail === 'string'
      ? problem.detail
      : `POC provider gateway request failed (${response.status}).`)
  }
  return response.json() as Promise<T>
}

const capabilities = {
  items: [
    { name: 'DataHub', state: 'sample', observed_at: POC_NOW, latency_ms: 0, detail_code: 'POC_MEMORY_ONLY' },
    { name: 'Quality', state: 'sample', observed_at: POC_NOW, latency_ms: 0, detail_code: 'POC_MEMORY_ONLY' },
    { name: 'Knowledge', state: 'sample', observed_at: POC_NOW, latency_ms: 0, detail_code: 'POC_MEMORY_ONLY' },
  ],
  external_system_links: [],
  grafana_embed: { state: 'DISABLED' },
  monitoring_configuration: {
    version: 1,
    items: [{
      id: '00000000-0000-4000-8000-000000000701',
      label: 'POC Platform',
      url: 'https://monitoring.poc.invalid/platform',
      height_px: 840,
      embed_state: 'DISABLED',
    }],
  },
  deployment_tier: 'SINGLE_NODE_PILOT',
} as const

const managedIndicators = [
  { indicator_id: 'ACCURACY', name: 'Accuracy', definition: '허용 범위와 패턴 준수', calculation: '통과 규칙 / 평가 규칙', target_grain: 'FIELD', rule_kinds: ['RANGE', 'REGEX'] },
  { indicator_id: 'COMPLETENESS', name: 'Completeness', definition: '필수 값의 존재', calculation: 'nonnull 값 / 전체 값', target_grain: 'FIELD', rule_kinds: ['NOT_NULL'] },
  { indicator_id: 'TIMELINESS', name: 'Timeliness', definition: '정해진 시점 내 관측', calculation: '현재 watermark와 기준 비교', target_grain: 'TABLE', rule_kinds: ['RANGE'] },
].map((item) => ({ ...item, contract_version: 'QUALITY_MANAGED_INDICATORS_V1' }))

const governanceDocument = {
  document_id: '00000000-0000-4000-8000-000000000801',
  workspace_id: POC_WORKSPACE_ID,
  kind: 'DOCUMENT',
  category: 'POLICY',
  title: '데이터 분류·접근 정책',
  summary: 'POC에서 기존 문서 조회 화면을 확인하기 위한 sample 문서입니다.',
  classification: 1,
  state: 'ACTIVE',
  owner_subject_id: POC_SUBJECT_ID,
  current_published_version_id: '00000000-0000-4000-8000-000000000802',
  current_version_number: 1,
  created_at: POC_NOW,
  updated_at: POC_NOW,
  version: 1,
  allowed_actions: ['read'],
}

const governanceVersion = {
  version_id: governanceDocument.current_published_version_id,
  workspace_id: POC_WORKSPACE_ID,
  document_id: governanceDocument.document_id,
  version_number: 1,
  version_tag: 'v1',
  title: governanceDocument.title,
  summary: governanceDocument.summary,
  applicability_scope: 'POC SAMPLE ONLY',
  sanitized_html: '<h2>POC sample 정책</h2><p>이 문서는 synthetic fixture이며 실제 정책 또는 운영 승인을 의미하지 않습니다.</p>',
  plain_text: 'POC sample 정책. 이 문서는 synthetic fixture이며 실제 정책 또는 운영 승인을 의미하지 않습니다.',
  content_sha256: '8'.repeat(64),
  size_bytes: 148,
  sanitizer_policy_version: 'POC_SANITIZER_V1',
  sanitizer_policy_sha256: '9'.repeat(64),
  source_format: 'HTML',
  source_template_version_id: null,
  parent_document_id: null,
  state: 'PUBLISHED',
  author_id: POC_SUBJECT_ID,
  submitted_at: POC_NOW,
  reviewed_by: POC_SUBJECT_ID,
  reviewed_at: POC_NOW,
  published_at: POC_NOW,
  artifact_state: 'STORED',
  knowledge_state: 'READY',
  created_at: POC_NOW,
  version: 1,
}

let sequence = 900
let currentChangeState: ChangeRequestState = changeSummary.state
let currentChangeVersion = changeSummary.version
let chatSessions: ChatSession[] = [{ ...initialChatSession }]
let uploadRecords: Array<Record<string, unknown>> = []
const chatMessages = new Map<string, ChatMessage[]>([
  [initialChatSession.id, initialChatMessages.map((item) => ({ ...item }))],
])

function nextId(namespace: string): string {
  sequence += 1
  return `poc-${namespace}-${sequence}`
}

function createUploadRecord(body: Record<string, unknown>, contentProfile?: string): Record<string, unknown> {
  const now = new Date()
  const record = {
    id: nextId('upload'),
    display_name: typeof body.display_name === 'string' ? body.display_name : 'poc-upload.bin',
    state: 'INITIATED',
    size_bytes: typeof body.size_bytes === 'number' ? body.size_bytes : 0,
    content_type: typeof body.content_type === 'string' ? body.content_type : 'application/octet-stream',
    sha256: typeof body.sha256 === 'string' ? body.sha256 : '0'.repeat(64),
    classification: typeof body.classification === 'string' ? body.classification : 'INTERNAL',
    content_profile: typeof body.content_profile === 'string'
      ? body.content_profile
      : contentProfile ?? 'KNOWLEDGE_SOURCE_DOCUMENT_V1',
    expires_at: new Date(now.getTime() + 60 * 60 * 1000).toISOString(),
    version: 1,
    recommended_part_size_bytes: 8 * 1024 * 1024,
    validation_summary: {},
    last_error_code: null,
  }
  uploadRecords.unshift(record)
  return record
}

function uploadById(id: string): Record<string, unknown> | undefined {
  return uploadRecords.find((item) => item.id === id)
}

function parsedPath(path: string): URL {
  return new URL(path, 'https://poc.invalid')
}

function jsonBody(options: PocRequestOptions): Record<string, unknown> {
  if (typeof options.body !== 'string') return {}
  try {
    const value = JSON.parse(options.body) as unknown
    return value && typeof value === 'object' && !Array.isArray(value)
      ? value as Record<string, unknown>
      : {}
  } catch {
    return {}
  }
}

function qualityEnvelope<T>(item: T) {
  return { item, cache_scope: POC_CACHE_SCOPE, ...authorizationWindow() }
}

function qualityList<T>(items: T[], url: URL) {
  const limit = Number(url.searchParams.get('limit') ?? 25)
  return {
    items: items.slice(0, limit),
    page: { next_cursor: null, limit },
    cache_scope: POC_CACHE_SCOPE,
    ...authorizationWindow(),
  }
}

function catalogSearch(url: URL) {
  const query = (url.searchParams.get('q') ?? '').trim().toLocaleLowerCase()
  const platform = url.searchParams.get('platform')
  const databaseName = url.searchParams.get('database_name')
  const schemaName = url.searchParams.get('schema_name')
  const classification = url.searchParams.get('classification')
  const items = catalogAssets.filter((asset) => {
    const searchable = [
      asset.name,
      asset.description,
      asset.platform,
      asset.database_name,
      asset.schema_name,
      asset.owner,
      asset.domain,
      ...(asset.tags ?? []),
      ...(asset.terms ?? []),
    ].filter(Boolean).join(' ').toLocaleLowerCase()
    return (!query || searchable.includes(query))
      && (!platform || asset.platform === platform)
      && (!databaseName || asset.database_name === databaseName)
      && (!schemaName || asset.schema_name === schemaName)
      && (!classification || asset.classification === classification)
  })
  const limit = Number(url.searchParams.get('limit') ?? 50)
  return {
    items: items.slice(0, limit),
    page: { next_cursor: null, limit },
    total: items.length,
    total_exact: true,
    meta: catalogMeta,
    match_mode: 'ALL',
  }
}

function catalogTree(url: URL) {
  const parentKind = url.searchParams.get('parent_kind') ?? 'ROOT'
  const platform = url.searchParams.get('platform')
  const databaseName = url.searchParams.get('database')
  const schemaName = url.searchParams.get('schema')
  const limit = Number(url.searchParams.get('limit') ?? 100)
  let items: Array<Record<string, unknown>>
  if (parentKind === 'ROOT') {
    items = [...new Set(catalogAssets.map((asset) => asset.platform).filter(Boolean))].map((value) => ({
      id: `PLATFORM:${value}`,
      kind: 'PLATFORM',
      label: value,
      asset_count: catalogAssets.filter((asset) => asset.platform === value).length,
      has_children: true,
      platform: value,
    }))
  } else if (parentKind === 'PLATFORM') {
    items = [...new Set(catalogAssets.filter((asset) => asset.platform === platform).map((asset) => asset.database_name).filter(Boolean))].map((value) => ({
      id: `DATABASE:${platform}:${value}`,
      kind: 'DATABASE',
      label: value,
      asset_count: catalogAssets.filter((asset) => asset.platform === platform && asset.database_name === value).length,
      has_children: true,
      platform,
      database_name: value,
    }))
  } else if (parentKind === 'DATABASE') {
    items = [...new Set(catalogAssets.filter((asset) => asset.platform === platform && asset.database_name === databaseName).map((asset) => asset.schema_name).filter(Boolean))].map((value) => ({
      id: `SCHEMA:${platform}:${databaseName}:${value}`,
      kind: 'SCHEMA',
      label: value,
      asset_count: catalogAssets.filter((asset) => asset.platform === platform && asset.database_name === databaseName && asset.schema_name === value).length,
      has_children: true,
      platform,
      database_name: databaseName,
      schema_name: value,
    }))
  } else {
    items = catalogAssets
      .filter((asset) => asset.platform === platform && asset.database_name === databaseName && asset.schema_name === schemaName)
      .map((asset) => ({
        id: `ASSET:${asset.id}`,
        kind: 'ASSET',
        label: asset.name,
        asset_count: 1,
        has_children: false,
        platform,
        database_name: databaseName,
        schema_name: schemaName,
        asset,
      }))
  }
  return { items: items.slice(0, limit), page: { next_cursor: null, limit }, meta: catalogMeta }
}

function chatRoute(mode: ChatMode) {
  return {
    requested_mode: mode,
    selected_mode: mode === 'AUTO' ? 'VECTOR' as const : mode,
    reason: mode === 'AUTO' ? 'SEMANTIC_INTENT' as const : 'EXPLICIT_SELECTION' as const,
    adapter_state: 'READY' as const,
  }
}

class PocApiClient {
  async request<T>(path: string, options: PocRequestOptions = {}): Promise<T> {
    return (await this.requestWithMeta<T>(path, options)).data
  }

  async requestWithMeta<T>(path: string, options: PocRequestOptions = {}): Promise<ApiResponse<T>> {
    if (options.signal?.aborted) throw new DOMException('The operation was aborted.', 'AbortError')
    const value = await this.dispatch(parsedPath(path), options)
    if (options.signal?.aborted) throw new DOMException('The operation was aborted.', 'AbortError')
    return { data: value as T, etag: '"1"' }
  }

  requestEventStream<T>(
    _path: string,
    options: PocRequestOptions,
    onEvent: ApiEventStreamHandler,
  ): Promise<T> {
    const body = jsonBody(options)
    const question = typeof body.question === 'string' ? body.question : 'POC sample question'
    const mode = ['AUTO', 'GENERAL', 'VECTOR', 'GRAPH'].includes(String(body.mode))
      ? body.mode as ChatMode
      : 'AUTO'
    const sessionId = typeof body.session_id === 'string' && body.session_id
      ? body.session_id
      : nextId('chat-session')
    const live = runtimeFlags().llmChat
      ? gatewayRequest<{ answer: string; evidence: Array<Record<string, unknown>> }>('/poc-api/llm/chat', {
          method: 'POST',
          signal: options.signal,
          body: JSON.stringify({ question }),
        })
      : Promise.resolve({
          answer: `Sample \`${catalogAssets[0]!.name}\`의 품질 점수는 **98.75%**입니다. 이 답변은 브라우저 메모리 fixture 근거만 사용하며 실제 시스템 상태를 의미하지 않습니다.`,
          evidence: [] as Array<Record<string, unknown>>,
        })
    return live.then((liveResult) => {
      const workflow = chatWorkflow.map((step) => ({
        ...step,
        detail_code: runtimeFlags().llmChat ? 'POC_LIVE_PROVIDER' : step.detail_code,
      }))
      for (const step of workflow) onEvent({ event: 'workflow', data: { ...step, status: 'IN_PROGRESS' } })
      const requestId = nextId('chat-request')
      const responseId = nextId('chat-response')
      const route = chatRoute(mode)
      const evidence = liveResult.evidence.length
        ? liveResult.evidence.map((item, index) => ({
            ...chatEvidence,
            chunk_id: `poc-live-evidence-${index + 1}`,
            resource_id: responseString(item.id ?? item.external_urn, chatEvidence.resource_id),
            name: responseString(item.name, 'DataHub asset'),
            description: responseString(item.description, ''),
            source_locator: responseString(item.external_urn ?? item.id, 'datahub://asset'),
            source_version: 'datahub-live',
            extraction_method: 'DATAHUB_GMS',
            rank: index + 1,
          }))
        : [chatEvidence]
      const messages = chatMessages.get(sessionId) ?? []
      messages.push({ id: requestId, session_id: sessionId, role: 'user', content: question, evidence_json: null, created_at: new Date().toISOString(), route: null, workflow: [] })
      messages.push({ id: responseId, session_id: sessionId, role: 'assistant', content: liveResult.answer, evidence_json: evidence, created_at: new Date().toISOString(), route, workflow })
      chatMessages.set(sessionId, messages)
      const existing = chatSessions.find((item) => item.id === sessionId)
      if (existing) {
        existing.message_count = messages.length
        existing.updated_at = new Date().toISOString()
        existing.version += 1
      } else {
        chatSessions.unshift({ id: sessionId, title: question.slice(0, 60), is_favorite: false, version: 1, created_at: new Date().toISOString(), updated_at: new Date().toISOString(), message_count: 2 })
      }
      return {
        session_id: sessionId,
        request_message_id: requestId,
        response_message_id: responseId,
        answer: liveResult.answer,
        persistence: 'EPHEMERAL_NO_STORE',
        route,
        workflow,
        evidence,
      } as T
    })
  }

  download(path: string): Promise<ApiDownload> {
    void path
    return Promise.resolve({
      blob: new Blob(['DataRiver POC sample export\n'], { type: 'text/plain;charset=utf-8' }),
      filename: 'datariver-poc-sample.txt',
      etag: '"1"',
    })
  }

  private async dispatch(url: URL, options: PocRequestOptions): Promise<unknown> {
    const path = url.pathname
    const method = options.method?.toUpperCase() ?? 'GET'

    if (path === '/admin/me') return {
      subject_id: POC_SUBJECT_ID,
      workspace_id: POC_WORKSPACE_ID,
      display_name: 'POC Sample User',
      authentication_assurance: 'UNKNOWN',
      fallback_enabled: false,
      allowed_operations: [],
      action_vocabulary: [],
    }
    if (path === '/capabilities') {
      return runtimeFlags().datahub || runtimeFlags().airflow || runtimeFlags().minio
        || runtimeFlags().llmChat || runtimeFlags().neo4j
        ? gatewayRequest('/poc-api/capabilities', { signal: options.signal })
        : capabilities
    }
    if (path === '/catalog/export-capability') return { enabled: false }
    if (path === '/operations/dashboard') return {
      observed_at: POC_NOW,
      changes_by_state: { REGISTERED: 2, IN_REVIEW: 1, APPLIED: 4 },
      catalog_asset_count: catalogAssets.length,
      catalog_described_asset_count: catalogAssets.length,
      catalog_glossary_term_count: 7,
      catalog_schema_metrics: catalogAssets.map((asset) => ({
        platform: asset.platform,
        database_name: asset.database_name,
        schema_name: asset.schema_name,
        asset_count: 1,
        described_asset_count: 1,
      })),
      catalog_schema_metrics_truncated: false,
    }

    if (path === '/catalog/assets') {
      return runtimeFlags().datahub
        ? gatewayRequest(`/poc-api/datahub/catalog${url.search}`, { signal: options.signal })
        : catalogSearch(url)
    }
    if (path === '/catalog/facets') {
      const counts = (values: Array<string | null | undefined>) => [...new Set(values.filter((value): value is string => Boolean(value)))].map((value) => ({ value, count: catalogAssets.filter((asset) => Object.values(asset).includes(value)).length || 1 }))
      return {
        asset_types: counts(catalogAssets.map((item) => item.asset_type)),
        platforms: counts(catalogAssets.map((item) => item.platform)),
        classifications: counts(catalogAssets.map((item) => item.classification)),
        databases: counts(catalogAssets.map((item) => item.database_name)),
        schemas: counts(catalogAssets.map((item) => item.schema_name)),
        domains: counts(catalogAssets.map((item) => item.domain)),
        lifecycles: counts(catalogAssets.map((item) => item.lifecycle)),
        meta: catalogMeta,
      }
    }
    if (path === '/catalog/suggestions') {
      const query = (url.searchParams.get('q') ?? '').toLocaleLowerCase()
      return {
        items: catalogAssets.filter((asset) => asset.name.toLocaleLowerCase().includes(query)).slice(0, 8).map((asset) => ({
          id: asset.id,
          name: asset.name,
          asset_type: asset.asset_type,
          platform: asset.platform,
          database_name: asset.database_name,
          schema_name: asset.schema_name,
          matches: asset.matches,
        })),
        meta: catalogMeta,
        match_mode: 'ALL',
      }
    }
    if (path === '/catalog/vocabulary') return { items: ['Manufacturing Quality', 'Yield Engineering', 'gold', 'Wafer'], meta: catalogMeta }
    if (path === '/catalog/tree/nodes') return catalogTree(url)
    if (path.endsWith('/lineage') && path.startsWith('/catalog/assets/')) {
      const assetId = decodeURIComponent(path.split('/')[3] ?? '')
      if (runtimeFlags().datahub && assetId.startsWith('urn:li:')) {
        return gatewayRequest(`/poc-api/datahub/lineage?urn=${encodeURIComponent(assetId)}`, { signal: options.signal })
      }
      return catalogLineage(assetId)
    }
    if (path.startsWith('/catalog/assets/')) {
      const assetId = decodeURIComponent(path.split('/')[3] ?? '')
      if (runtimeFlags().datahub && assetId.startsWith('urn:li:')) {
        return gatewayRequest(`/poc-api/datahub/asset?urn=${encodeURIComponent(assetId)}`, { signal: options.signal })
      }
      return catalogDetail(assetId, Number(url.searchParams.get('field_offset') ?? 0))
    }
    if (path === '/uploads/operator-capability') return { eligible: true, can_view_workspace_history: true, reason_code: 'ELIGIBLE', allowed_roles: ['ADMIN', 'DATA_STEWARD'] }
    const knowledgeUploadCollection = path.match(/^\/knowledge\/graphs\/[^/]+\/source-uploads$/)
    if ((path === '/uploads' || knowledgeUploadCollection) && method === 'POST') {
      return createUploadRecord(jsonBody(options), knowledgeUploadCollection ? 'KNOWLEDGE_SOURCE_DOCUMENT_V1' : undefined)
    }
    if (path === '/uploads' && method === 'GET') return { items: uploadRecords }
    const uploadPart = path.match(/^\/uploads\/([^/]+)\/parts$/)
      ?? path.match(/^\/knowledge\/graphs\/[^/]+\/source-uploads\/([^/]+)\/parts$/)
    if (uploadPart && method === 'POST') {
      const partNumber = Number(jsonBody(options).part_number ?? 1)
      return { url: `/poc-api/minio/uploads/${encodeURIComponent(uploadPart[1] ?? '')}/parts/${partNumber}` }
    }
    const uploadComplete = path.match(/^\/uploads\/([^/]+)\/complete$/)
      ?? path.match(/^\/knowledge\/graphs\/[^/]+\/source-uploads\/([^/]+)\/complete$/)
    if (uploadComplete && method === 'POST') {
      const record = uploadById(uploadComplete[1] ?? '')
      if (!record) throw new Error('POC upload record was not found.')
      const parts = jsonBody(options).parts
      if (runtimeFlags().minio) {
        await gatewayRequest(`/poc-api/minio/uploads/${encodeURIComponent(String(record.id))}/complete`, {
          method: 'POST',
          signal: options.signal,
          body: JSON.stringify({
            part_count: Array.isArray(parts) ? parts.length : 1,
            display_name: record.display_name,
            content_type: record.content_type,
          }),
        })
      }
      Object.assign(record, {
        state: 'ACCEPTED',
        version: Number(record.version) + 2,
        validation_summary: {
          provider: runtimeFlags().minio ? 'MINIO_LIVE' : 'POC_MEMORY_ONLY',
          status: 'PASS',
        },
      })
      return { ...record }
    }
    const uploadDetail = path.match(/^\/uploads\/([^/]+)$/)
      ?? path.match(/^\/knowledge\/graphs\/[^/]+\/source-uploads\/([^/]+)$/)
    if (uploadDetail && method === 'GET') return uploadById(uploadDetail[1] ?? '') ?? createUploadRecord({})
    if (/^\/uploads\/[^/]+\/preparations$/.test(path)) return { items: [] }
    if (path.startsWith('/registration/manual-submissions')) return path.endsWith('/report') ? { submission: {}, attempts: [] } : { items: [], page: { next_cursor: null, limit: 25 } }

    if (path === '/change-requests/summaries') return {
      items: [{ ...changeSummary, state: currentChangeState, version: currentChangeVersion }],
      overview: [],
      overview_truncated: false,
      page: { next_cursor: null, limit: 25 },
    }
    if (/^\/change-requests\/[^/]+\/attachments\/page$/.test(path)) return { items: [], page: { next_cursor: null, limit: Number(url.searchParams.get('limit') ?? 25) } }
    if (/^\/change-requests\/[^/]+\/apply-report$/.test(path)) return {
      change_request_id: changeSummary.id,
      job_id: null,
      state: 'NOT_STARTED',
      attempt_count: 0,
      last_error_code: null,
      expected_hash: null,
      observed_hash: null,
      reconciled: false,
      created_at: null,
      updated_at: null,
      items: [],
      attempts: [],
    }
    if (/^\/change-requests\/[^/]+\/(submit|approve|reject|request-changes|cancel|test-runs|apply)$/.test(path) && method === 'POST') {
      const action = path.split('/').at(-1)
      const nextStates: Record<string, ChangeRequestState> = { submit: 'IN_REVIEW', approve: 'FINAL_REVIEW', reject: 'REJECTED', 'request-changes': 'CHANGES_REQUESTED', cancel: 'CANCELLED', apply: 'APPLIED', 'test-runs': 'TESTING' }
      currentChangeState = nextStates[action ?? ''] ?? currentChangeState
      currentChangeVersion += 1
      return changeRecord(currentChangeState, currentChangeVersion)
    }
    if (/^\/change-requests\/[^/]+$/.test(path)) return changeRecord(currentChangeState, currentChangeVersion)

    if (path === '/quality/capability') {
      const observedAt = new Date()
      return {
        contract_version: 'QUALITY_CAPABILITY_V2',
        observed_at: observedAt.toISOString(),
        valid_until: new Date(observedAt.getTime() + 30_000).toISOString(),
        cache_scope: POC_CACHE_SCOPE,
        axes: ['read_access', 'profile_readiness', 'rule_authoring', 'review', 'activation', 'manual_execution', 'scheduling', 'operations'].map((id) => ({ id, state: 'AVAILABLE' })),
      }
    }
    if (path === '/quality/dashboard') return {
      contract_version: 'QUALITY_DASHBOARD_V1',
      cache_scope: POC_CACHE_SCOPE,
      ...authorizationWindow(),
      as_of: POC_NOW,
      schema_count: 3,
      table_count: catalogAssets.length,
      active_rule_set_count: 1,
      common_rule_template_count: 1,
      covered_table_count: 1,
      table_coverage_basis_points: 3333,
      managed_rule_sets: managedIndicators,
      schemas: [],
      schemas_truncated: false,
    }
    if (path === '/quality/overview') return {
      availability: 'AVAILABLE', freshness: 'CURRENT', as_of: POC_NOW,
      authorization_valid_until: authorizationWindow().authorization_valid_until,
      overall_state: 'PASS', active_rule_set_count: 1, evaluated_rule_set_count: 1,
      unknown_rule_set_count: 0, passed_count: 79, advisory_failed_count: 0,
      blocking_failed_count: 1, evaluated_rule_count: 80, score_basis_points: 9875,
      coverage_basis_points: 3333, trend: [{ bucket_start: POC_NOW, passed_count: 79, advisory_failed_count: 0, blocking_failed_count: 1, evaluated_rule_count: 80, score_basis_points: 9875 }], failure_code: null,
    }
    if (path === '/quality/rule-definitions') return {
      contract_version: 'QUALITY_TYPED_RULES_V1',
      items: [
        { kind: 'NOT_NULL', available: true, reason_code: null, parameter_contract: {} },
        { kind: 'RANGE', available: true, reason_code: null, parameter_contract: { minimum: 'number?', maximum: 'number?' } },
        { kind: 'REGEX', available: true, reason_code: null, parameter_contract: { pattern: 'string' } },
      ],
    }
    if (path === '/quality/assets/summary-batch') {
      const ids = jsonBody(options).asset_ids
      return { items: Array.isArray(ids) && ids.includes(qualityAsset.asset_id) ? [qualityAsset] : [], cache_scope: POC_CACHE_SCOPE, ...authorizationWindow() }
    }
    if (path === '/quality/assets') return qualityList([qualityAsset], url)
    if (/^\/quality\/assets\/[^/]+\/workspace$/.test(path)) return qualityEnvelope({
      asset: qualityAsset,
      rule_sets: [qualityRuleSet],
      runs: [qualityRun],
      trend: [{ bucket_start: POC_NOW, passed_count: 79, advisory_failed_count: 0, blocking_failed_count: 1, evaluated_rule_count: 80, score_basis_points: 9875 }],
      authoring: { ...qualityAuthoring, fields: qualityAuthoring.fields.map((field) => ({ ...field, supported_rule_kinds: [...field.supported_rule_kinds] })) },
      fields: [{ ...qualityAuthoring.fields[0], supported_rule_kinds: ['NOT_NULL'], configured_rule_count: 1, active_rule_count: 1, evaluated_rule_count: 1, passed_count: 1, advisory_failed_count: 0, blocking_failed_count: 0, latest_score_basis_points: 10000, latest_quality_outcome: 'PASS', latest_evaluated_at: POC_NOW }],
      score_policy: scorePolicy,
    })
    if (/^\/quality\/assets\/[^/]+\/fields\/[^/]+\/workspace$/.test(path)) return qualityEnvelope({
      asset_id: qualityAsset.asset_id,
      field: { ...qualityAuthoring.fields[0], supported_rule_kinds: ['NOT_NULL'] },
      rules: [{ rule_definition_id: 'poc-rule-definition-1', rule_set_id: qualityRuleSet.rule_set_id, rule_set_name: qualityRuleSet.name, version_id: qualityRuleSet.active_version_id, version_number: 1, version_state: 'ACTIVE', kind: 'NOT_NULL', severity: 'BLOCKING', parameters: {} }],
      runs: [{ ...qualityRun, run_quality_outcome: 'PASS', field_quality_outcome: 'PASS', evaluated_value_count: 80, missing_count: 0, unexpected_count: 0 }],
      trend: [{ bucket_start: POC_NOW, passed_count: 1, advisory_failed_count: 0, blocking_failed_count: 0, evaluated_rule_count: 1, score_basis_points: 10000 }],
      score_policy: scorePolicy,
    })
    if (/^\/quality\/assets\/[^/]+$/.test(path)) return { ...qualityEnvelope(qualityAsset), authoring: { ...qualityAuthoring, fields: qualityAuthoring.fields.map((field) => ({ ...field, supported_rule_kinds: [...field.supported_rule_kinds] })) } }
    if (path === '/quality/common-rule-templates') return { items: [{ template_id: 'poc-template-1', name: 'Essential completeness', description: 'Sample reusable rules', rules: [{ field_identifier: 'wafer_id', kind: 'NOT_NULL', severity: 'BLOCKING', parameters: {} }], mapping_count: 1, created_at: POC_NOW, updated_at: POC_NOW }], cache_scope: POC_CACHE_SCOPE, ...authorizationWindow() }
    if (path === '/quality/rule-sets') return qualityList([qualityRuleSet], url)
    if (/^\/quality\/rule-sets\/[^/]+$/.test(path)) return qualityEnvelope({ rule_set: qualityRuleSet, versions: [{ version_id: qualityRuleSet.active_version_id, version_number: 1, state: 'ACTIVE', author_id: POC_SUBJECT_ID, reviewed_by: POC_SUBJECT_ID, activated_by: POC_SUBJECT_ID, rule_count: 2, schedule_mode: 'MANUAL', created_at: POC_NOW, updated_at: POC_NOW, version: 1 }], definitions: [{ rule_definition_id: 'poc-rule-definition-1', version_id: qualityRuleSet.active_version_id, ordinal: 1, field_identifier: 'wafer_id', kind: 'NOT_NULL', severity: 'BLOCKING', parameters: {} }] })
    if (path === '/quality/runs' && method === 'POST') {
      const runId = nextId('quality-run')
      if (runtimeFlags().airflow) {
        await gatewayRequest('/poc-api/airflow/dags/datariver_quality_dispatch/runs', {
          method: 'POST',
          signal: options.signal,
          body: JSON.stringify({ conf: { poc_run_id: runId, ...jsonBody(options) } }),
        })
      }
      return { run_id: runId, state: 'QUEUED', created_at: new Date().toISOString(), replayed: false }
    }
    if (path === '/quality/runs') return qualityList([qualityRun], url)
    if (/^\/quality\/runs\/[^/]+\/results$/.test(path)) return qualityList([{ result_id: 'poc-result-1', rule_definition_id: 'poc-rule-definition-1', field_identifier: 'wafer_id', kind: 'NOT_NULL', severity: 'BLOCKING', outcome: 'PASS', evaluated_count: 80, missing_count: 0, unexpected_count: 0, missing_ratio: 0, unexpected_ratio: 0, duration_ms: 12, occurred_at: POC_NOW }], url)
    if (/^\/quality\/runs\/[^/]+$/.test(path)) return qualityEnvelope(qualityRun)
    if (path === '/quality/issues') return qualityList([{ issue_id: 'poc-issue-1', asset_id: qualityAsset.asset_id, asset_name: qualityAsset.name, field_identifier: 'defect_code', kind: 'NOT_NULL', severity: 'ADVISORY', outcome: 'ADVISORY_FAIL', occurrence_count: 1, last_observed_at: POC_NOW }], url)

    if (path === '/knowledge/graphs') return [knowledgeGraph]
    if (path === '/knowledge/registry/assets') return { items: [knowledgeAsset], next_cursor: null, limit: Number(url.searchParams.get('limit') ?? 25) }
    if (path === `/knowledge/registry/assets/${knowledgeAsset.id}/detail`) return knowledgeDetail
    if (path === `/knowledge/registry/assets/${knowledgeAsset.id}/versions`) return { items: [{ id: knowledgeRelease.id, kind: 'INSTANCE_RELEASE', version_label: 'Release 1', title: 'Initial sample release', status: 'PUBLISHED', author_id: POC_SUBJECT_ID, author_name: 'POC Sample User', author_email: 'sample.user@poc.invalid', reviewed_by: POC_SUBJECT_ID, reviewer_name: 'POC Sample User', reviewer_email: 'sample.user@poc.invalid', published_by: POC_SUBJECT_ID, publisher_name: 'POC Sample User', publisher_email: 'sample.user@poc.invalid', created_at: POC_NOW, is_current: true, studio_release_id: knowledgeAsset.active_studio_release_id, instance_release_id: knowledgeRelease.id, changeset_id: null, content_hash: knowledgeRelease.content_hash, node_count: 3, edge_count: 2 }], next_cursor: null, limit: 50 }
    if (path === `/knowledge/graphs/${knowledgeAsset.id}/releases`) return [knowledgeRelease]
    if (path === `/knowledge/graphs/${knowledgeAsset.id}/releases/${knowledgeRelease.id}/snapshot`) {
      if (!runtimeFlags().neo4j) return knowledgeSnapshot
      const graph = await gatewayRequest<{
        nodes: Array<{ id: string; name: string; entity_type: string }>
        edges: Array<{ id: string; source_id: string; target_id: string; edge_type: string }>
      }>('/poc-api/neo4j/graph', { signal: options.signal })
      const provenance = knowledgeSnapshot.nodes[0]?.provenance ?? []
      return {
        release: { ...knowledgeRelease, node_count: graph.nodes.length, edge_count: graph.edges.length },
        nodes: graph.nodes.map((node) => ({
          id: node.id,
          entity_type: node.entity_type,
          properties: { name: node.name },
          classification: 1,
          provenance,
        })),
        edges: graph.edges.map((edge) => ({
          ...edge,
          properties: {},
          classification: 1,
          provenance,
        })),
        filtered: false,
      }
    }
    if (/^\/knowledge\/graphs\/[^/]+\/releases$/.test(path)) return [knowledgeRelease]
    if (/^\/knowledge\/graphs\/[^/]+\/changesets$/.test(path)) return []

    if (path === '/governance/documents/capability') {
      const window = authorizationWindow()
      return {
        contract_version: 'GOVERNANCE_DOCUMENT_CAPABILITY_V1',
        observed_at: window.observed_at,
        valid_until: window.authorization_valid_until,
        cache_scope: POC_CACHE_SCOPE,
        axes: ['read', 'create', 'edit', 'review', 'publish', 'archive', 'template_manage', 'artifact_storage', 'knowledge_projection'].map((id) => ({ id, state: id === 'read' ? 'AVAILABLE' : 'DENIED', reason_code: id === 'read' ? null : 'POC_READ_ONLY' })),
        limits: { max_html_bytes: 1_000_000, max_attachment_bytes: 10_000_000, max_attachments_per_version: 25 },
      }
    }
    if (path === '/governance/documents') return { items: [governanceDocument], page: { next_cursor: null, limit: Number(url.searchParams.get('limit') ?? 100) }, cache_scope: POC_CACHE_SCOPE, ...authorizationWindow() }
    if (path === `/governance/documents/${governanceDocument.document_id}`) return { item: { document: governanceDocument, versions: [governanceVersion], reviews: [], attachments: [], parent_document: null, child_documents: [] }, cache_scope: POC_CACHE_SCOPE, ...authorizationWindow() }
    if (path === '/admin/profile-role-policy') return { policy_version: 'PROFILE_ROLE_POLICY_V1', items: [{ tier: 'ENGINEER_STEWARD', label: 'Engineer / Steward', description: '담당 System 범위의 등록·수정·검토', allowed_actions: ['change.read', 'change.create', 'change.edit', 'change.review'], services: [{ service_key: 'change', service_label: '변경관리', action_labels: ['조회', '등록', '수정', '검토'] }], assignable_to_system: true, lifecycle_note: '취소·이력 보존' }] }

    if (path === '/chat/sessions') return chatSessions.map((item) => ({ ...item }))
    const messageMatch = path.match(/^\/chat\/sessions\/([^/]+)\/messages$/)
    if (messageMatch) return (chatMessages.get(messageMatch[1] ?? '') ?? []).map((item) => ({ ...item }))
    const favoriteMatch = path.match(/^\/chat\/sessions\/([^/]+)\/favorite$/)
    if (favoriteMatch && method === 'PATCH') {
      const session = chatSessions.find((item) => item.id === favoriteMatch[1])
      if (!session) return initialChatSession
      session.is_favorite = Boolean(jsonBody(options).is_favorite)
      session.version += 1
      session.updated_at = new Date().toISOString()
      return { ...session }
    }
    const deleteMatch = path.match(/^\/chat\/sessions\/([^/]+)$/)
    if (deleteMatch && method === 'DELETE') {
      chatSessions = chatSessions.filter((item) => item.id !== deleteMatch[1])
      chatMessages.delete(deleteMatch[1] ?? '')
      return undefined
    }

    if (path === '/api-products') return []
    if (/^\/api-products\/[^/]+\/grants$/.test(path)) return []
    if (path === '/admin/workspace-memberships/me/summary') return {
      subject_id: POC_SUBJECT_ID, display_name: 'POC Sample User', email: 'sample.user@poc.invalid',
      last_login_at: null, last_login_ip: null, owned_table_count: 3, change_request_count: 1,
      joined_at: POC_NOW, access_expires_at: null, renewal_eligible_at: null, access_expired: false,
      renewal_request_eligible: false, pending_renewal_request_id: null, subject_active: true,
      membership_active: true, department_id: null, job_function: 'POC_SAMPLE', clearance: 'INTERNAL',
      membership_version: 1, effective_profile_role: 'ENGINEER_STEWARD',
    }
    if (path === '/admin/membership-renewals/me') return { items: [] }

    if (method === 'GET') {
      if (url.searchParams.has('limit')) return { items: [], page: { next_cursor: null, limit: Number(url.searchParams.get('limit') ?? 25) } }
      return { items: [] }
    }
    return { id: nextId('memory-record'), state: 'COMPLETED', version: 1, replayed: false }
  }
}

const pocClient = new PocApiClient() as unknown as ApiClient

export function useStableApiClient(
  _baseUrl?: string,
  _accessToken?: string,
  _workspace?: string,
  _renewAccessToken?: () => Promise<string | undefined>,
  _readSecurityEpoch?: () => number,
): ApiClient {
  void _baseUrl
  void _accessToken
  void _workspace
  void _renewAccessToken
  void _readSecurityEpoch
  return pocClient
}

export function resetPocMemory(): void {
  currentChangeState = changeSummary.state
  currentChangeVersion = changeSummary.version
  chatSessions = [{ ...initialChatSession }]
  uploadRecords = []
  chatMessages.clear()
  chatMessages.set(initialChatSession.id, initialChatMessages.map((item) => ({ ...item })))
}
