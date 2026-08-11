import type {
  ApiClient,
  ApiDownload,
  ApiEventStreamHandler,
  ApiResponse,
} from '../api/client'
import { sha256 } from 'hash-wasm'
import type {
  CatalogAsset,
  CatalogAssetDetail,
  CatalogPolicyMeta,
  CatalogSearch,
  ChangeRequestRecord,
  ChangeRequestAttachment,
  ChangeRequestAttachmentUpload,
  ChangeRequestSummary,
  ChangeRequestState,
  ChatMessage,
  ChatMode,
  ChatSession,
  SystemConfigurationEntry,
  SystemConfigurationTestResult,
  WorkspaceMembershipSummary,
} from '../api/types'
import {
  POC_CACHE_SCOPE,
  POC_NOW,
  POC_SUBJECT_ID,
  POC_WORKSPACE_ID,
  authorizationWindow,
  catalogMeta,
  chatWorkflow,
  scorePolicy,
} from './pocContracts'

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
    ...['DataHub', 'Airflow', 'MinIO', 'LLM Chat', 'LLM Embedding', 'LLM Reranker', 'Neo4j']
      .map((name) => ({ name, state: 'disabled', observed_at: POC_NOW, latency_ms: null, detail_code: 'NOT_CONFIGURED' })),
  ],
  external_system_links: [],
  grafana_embed: { state: 'NOT_CONFIGURED' },
  monitoring_configuration: { version: 1, items: [] },
  deployment_tier: 'SINGLE_NODE_PILOT',
} as const

const managedIndicators = [
  { indicator_id: 'ACCURACY', name: 'Accuracy', definition: '허용 범위와 패턴 준수', calculation: '통과 규칙 / 평가 규칙', target_grain: 'FIELD', rule_kinds: ['RANGE', 'REGEX'] },
  { indicator_id: 'COMPLETENESS', name: 'Completeness', definition: '필수 값의 존재', calculation: 'nonnull 값 / 전체 값', target_grain: 'FIELD', rule_kinds: ['NOT_NULL'] },
  { indicator_id: 'TIMELINESS', name: 'Timeliness', definition: '정해진 시점 내 관측', calculation: '현재 watermark와 기준 비교', target_grain: 'TABLE', rule_kinds: ['RANGE'] },
].map((item) => ({ ...item, contract_version: 'QUALITY_MANAGED_INDICATORS_V1' }))

let sequence = 900
let changeRecords: ChangeRequestRecord[] = []
let chatSessions: ChatSession[] = []
let uploadRecords: Array<Record<string, unknown>> = []
let manualSubmissionReports: Array<Record<string, unknown>> = []
let adminMemberships: WorkspaceMembershipSummary[] = [pocAdminMembership()]
const chatMessages = new Map<string, ChatMessage[]>()
const changeAttachmentUploads = new Map<string, ChangeRequestAttachmentUpload & { file: File }>()
const changeAttachments = new Map<string, Array<ChangeRequestAttachment & { file: File }>>()
const liveAssetDetails = new Map<string, CatalogAssetDetail>()

function nextId(namespace: string): string {
  sequence += 1
  return `poc-${namespace}-${sequence}`
}

function pocAdminMembership(): WorkspaceMembershipSummary {
  return {
    subject_id: POC_SUBJECT_ID,
    display_name: 'POC User',
    email: 'poc.user@local',
    last_login_at: null,
    last_login_ip: null,
    owned_table_count: 0,
    change_request_count: 0,
    joined_at: POC_NOW,
    access_expires_at: null,
    renewal_eligible_at: null,
    access_expired: false,
    renewal_request_eligible: false,
    pending_renewal_request_id: null,
    subject_active: true,
    membership_active: true,
    department_id: null,
    job_function: 'POC',
    clearance: 'INTERNAL',
    membership_version: 1,
    effective_profile_role: 'ADMIN',
  }
}

function changeSummaryOf(record: ChangeRequestRecord): ChangeRequestSummary {
  const first = record.items[0]
  return {
    id: record.id,
    number: record.number,
    request_type: record.request_type,
    title: record.title,
    state: record.state,
    requester_id: record.requester_id,
    requester_department_id: record.requester_department_id,
    current_round_number: record.current_round_number,
    created_at: record.created_at,
    requested_due_date: record.requested_due_date,
    priority: record.priority,
    urgency: record.urgency,
    classification: record.classification,
    version: record.version,
    item_count: record.items.length,
    first_item: {
      target_ref: first?.target_ref ?? 'POC target',
      aspect_name: first?.aspect_name ?? 'datasetProperties',
      operation: first?.operation ?? 'UPSERT',
    },
  }
}

function changeAfterDocument(target: Record<string, unknown>): Record<string, unknown> {
  if (target.kind !== 'EXISTING') return { ...target }
  const columns = Array.isArray(target.columns)
    ? target.columns.filter((item): item is Record<string, unknown> => (
        Boolean(item) && typeof item === 'object' && !Array.isArray(item)
      ))
    : []
  return {
    kind: 'EXISTING',
    asset_id: target.asset_id,
    requested: {
      description: target.description,
      requested_change: target.requested_change,
      tags: target.tags,
      terms: target.terms,
      columns: columns.map((column) => ({
        field_path: column.field_path,
        requested: {
          data_type: column.data_type,
          description: column.description,
          requested_change: column.requested_change,
          tags: column.tags,
          terms: column.terms,
        },
      })),
    },
  }
}

function createChangeRequest(body: Record<string, unknown>): ChangeRequestRecord {
  const id = nextId('change-request')
  const roundId = nextId('change-round')
  const now = new Date().toISOString()
  const targets = Array.isArray(body.targets)
    ? body.targets.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object' && !Array.isArray(item))
    : []
  const title = responseString(body.title, 'POC 변경 요청')
  const classification = responseString(body.security_level, 'INTERNAL')
  const record: ChangeRequestRecord = {
    id,
    number: `CR-POC-${String(sequence).padStart(5, '0')}`,
    request_type: 'CHANGE_INTAKE',
    title,
    description: responseString(body.request_content, ''),
    state: 'REGISTERED',
    requester_id: POC_SUBJECT_ID,
    requester_department_id: null,
    current_round_id: roundId,
    current_round_number: 1,
    revision_allowed: true,
    created_at: now,
    requested_due_date: typeof body.requested_due_date === 'string' && body.requested_due_date
      ? new Date(`${body.requested_due_date}T00:00:00.000Z`).toISOString()
      : null,
    priority: ['LOW', 'NORMAL', 'HIGH', 'CRITICAL'].includes(String(body.priority))
      ? body.priority as ChangeRequestRecord['priority']
      : 'NORMAL',
    urgency: ['NORMAL', 'URGENT', 'EMERGENCY'].includes(String(body.urgency))
      ? body.urgency as ChangeRequestRecord['urgency']
      : 'NORMAL',
    classification,
    version: 1,
    items: targets.map((target, index) => {
      const existing = target.kind === 'EXISTING'
      const assetId = responseString(target.asset_id, '')
      const asset = existing ? liveAssetDetails.get(assetId) : undefined
      const targetRef = existing
        ? [asset?.platform, asset?.database_name, asset?.schema_name, asset?.name]
            .filter(Boolean).join('.') || assetId || `POC target ${index + 1}`
        : [target.database_name, target.schema_name, target.table_name].filter(Boolean).join('.') || `POC target ${index + 1}`
      return {
        id: nextId('change-item'),
        target_type: 'DATASET',
        target_ref: targetRef,
        aspect_name: 'datasetProperties',
        operation: 'UPSERT',
        after_document: changeAfterDocument(target),
        target_asset_id: existing ? assetId || null : null,
        target_asset_type: 'DATASET',
        target_system_id: responseString(body.system_id, '') || null,
        target_domain_id: null,
        target_owner_department_id: null,
        target_classification: classification,
        target_lifecycle: 'ACTIVE',
        target_source_version: existing ? 'datahub-live' : 'poc-manual',
        target_observed_at: now,
        target_binding_hash: '5'.repeat(64),
        routing_system_id: responseString(body.system_id, '') || null,
      }
    }),
    approvals: [],
    transitions: [],
    rounds: [{
      id: roundId,
      round_number: 1,
      submitted_by: POC_SUBJECT_ID,
      submitted_at: now,
      closed_at: null,
      evidence_hash: '6'.repeat(64),
      revision_kind: 'INITIAL',
      title,
      request_date: responseString(body.request_date, '') || null,
      request_department: responseString(body.request_department, ''),
      request_reason: responseString(body.request_reason, ''),
      request_content: responseString(body.request_content, ''),
      requested_due_date: typeof body.requested_due_date === 'string' ? body.requested_due_date : null,
      priority: ['LOW', 'NORMAL', 'HIGH', 'CRITICAL'].includes(String(body.priority))
        ? body.priority as ChangeRequestRecord['priority']
        : 'NORMAL',
      urgency: ['NORMAL', 'URGENT', 'EMERGENCY'].includes(String(body.urgency))
        ? body.urgency as ChangeRequestRecord['urgency']
        : 'NORMAL',
      classification,
      selected_system_id: responseString(body.system_id, '') || null,
    }],
    test_runs: [],
  }
  changeRecords.unshift(record)
  return record
}

function changeRecordById(id: string): ChangeRequestRecord {
  const record = changeRecords.find((item) => item.id === id)
  if (!record) throw new Error('POC 변경 요청을 찾을 수 없습니다.')
  return record
}

function requireCurrentVersion(record: ChangeRequestRecord, options: PocRequestOptions): void {
  if (options.ifMatch && options.ifMatch !== `"${record.version}"`) {
    throw new Error('변경 요청 버전이 갱신되었습니다. 상세를 새로고침한 뒤 다시 시도하세요.')
  }
}

function currentRound(record: ChangeRequestRecord) {
  return record.rounds.find((round) => round.id === record.current_round_id)
}

function hasCurrentApproval(record: ChangeRequestRecord, stage: 'REVIEW' | 'TEST' | 'FINAL'): boolean {
  return record.approvals.some((approval) => (
    approval.round_id === record.current_round_id
    && approval.stage === stage
    && approval.decision === 'APPROVED'
  ))
}

function revisionItems(
  targets: Record<string, unknown>[],
  body: Record<string, unknown>,
  classification: string,
  now: string,
): ChangeRequestRecord['items'] {
  return targets.map((target, index) => {
    const existing = target.kind === 'EXISTING'
    const assetId = responseString(target.asset_id, '')
    const asset = existing ? liveAssetDetails.get(assetId) : undefined
    return {
      id: nextId('change-item'),
      target_type: 'DATASET',
      target_ref: existing
        ? [asset?.platform, asset?.database_name, asset?.schema_name, asset?.name]
            .filter(Boolean).join('.') || assetId || `POC target ${index + 1}`
        : [target.database_name, target.schema_name, target.table_name]
            .filter(Boolean).join('.') || `POC target ${index + 1}`,
      aspect_name: 'datasetProperties',
      operation: 'UPSERT',
      after_document: changeAfterDocument(target),
      target_asset_id: existing ? assetId || null : null,
      target_asset_type: 'DATASET',
      target_system_id: responseString(body.system_id, '') || null,
      target_domain_id: null,
      target_owner_department_id: null,
      target_classification: classification,
      target_lifecycle: 'ACTIVE',
      target_source_version: existing ? 'datahub-live' : 'poc-manual',
      target_observed_at: now,
      target_binding_hash: '5'.repeat(64),
      routing_system_id: responseString(body.system_id, '') || null,
    }
  })
}

function reviseChangeRequest(
  record: ChangeRequestRecord,
  body: Record<string, unknown>,
): ChangeRequestRecord {
  if (record.state !== 'CHANGES_REQUESTED' || !record.revision_allowed) {
    throw new Error('현재 변경 요청은 수정하여 재상신할 수 없습니다.')
  }
  const targets = Array.isArray(body.targets)
    ? body.targets.filter((item): item is Record<string, unknown> => (
        Boolean(item) && typeof item === 'object' && !Array.isArray(item)
      ))
    : []
  if (targets.length === 0) throw new Error('수정 재상신에는 하나 이상의 현재 대상이 필요합니다.')
  const oldRound = currentRound(record)
  const selectedSystemId = oldRound?.selected_system_id
  if (!selectedSystemId || body.system_id !== selectedSystemId) {
    throw new Error('수정 재상신에서는 기존 관련 시스템을 변경할 수 없습니다.')
  }
  const now = new Date().toISOString()
  if (oldRound) oldRound.closed_at = now
  const roundId = nextId('change-round')
  const classification = responseString(body.security_level, record.classification)
  const title = responseString(body.title, record.title)
  record.items = revisionItems(targets, body, classification, now)
  record.rounds.push({
    id: roundId,
    round_number: record.current_round_number + 1,
    submitted_by: POC_SUBJECT_ID,
    submitted_at: now,
    closed_at: null,
    evidence_hash: '6'.repeat(64),
    revision_kind: 'EDITED',
    title,
    request_date: responseString(body.request_date, '') || null,
    request_department: responseString(body.request_department, ''),
    request_reason: responseString(body.request_reason, ''),
    request_content: responseString(body.request_content, ''),
    requested_due_date: typeof body.requested_due_date === 'string' ? body.requested_due_date : null,
    priority: ['LOW', 'NORMAL', 'HIGH', 'CRITICAL'].includes(String(body.priority))
      ? body.priority as ChangeRequestRecord['priority']
      : 'NORMAL',
    urgency: ['NORMAL', 'URGENT', 'EMERGENCY'].includes(String(body.urgency))
      ? body.urgency as ChangeRequestRecord['urgency']
      : 'NORMAL',
    classification,
    selected_system_id: selectedSystemId,
  })
  record.transitions.push({
    id: nextId('change-transition'),
    from_state: 'CHANGES_REQUESTED',
    to_state: 'REGISTERED',
    actor_id: POC_SUBJECT_ID,
    reason: '수정된 변경 요청 재상신',
    occurred_at: now,
    round_id: roundId,
  })
  record.current_round_id = roundId
  record.current_round_number += 1
  record.title = title
  record.description = responseString(body.request_content, '')
  record.classification = classification
  record.requested_due_date = typeof body.requested_due_date === 'string' && body.requested_due_date
    ? new Date(`${body.requested_due_date}T00:00:00.000Z`).toISOString()
    : null
  record.priority = record.rounds.at(-1)?.priority ?? 'NORMAL'
  record.urgency = record.rounds.at(-1)?.urgency ?? 'NORMAL'
  record.state = 'REGISTERED'
  record.version += 1
  return record
}

function publicAttachmentUpload(
  value: ChangeRequestAttachmentUpload & { file: File },
): ChangeRequestAttachmentUpload {
  const { file: _file, ...upload } = value
  void _file
  return upload
}

async function createChangeAttachmentUpload(
  changeRequestId: string,
  options: PocRequestOptions,
): Promise<ChangeRequestAttachmentUpload> {
  const record = changeRecordById(changeRequestId)
  if (!(options.body instanceof FormData)) throw new Error('첨부파일 FormData가 필요합니다.')
  const kind = options.body.get('kind') === 'TEST' ? 'TEST' : 'REQUEST'
  const uploadId = responseString(options.body.get('upload_id'), '')
  const file = options.body.get('file')
  if (!uploadId || !(file instanceof File)) throw new Error('첨부파일과 upload_id가 필요합니다.')
  const existing = changeAttachmentUploads.get(uploadId)
  if (existing) return publicAttachmentUpload(existing)
  const digest = await sha256(new Uint8Array(await file.arrayBuffer()))
  if (runtimeFlags().minio) {
    const part = await fetch(`/poc-api/minio/uploads/${encodeURIComponent(uploadId)}/parts/1`, {
      method: 'PUT',
      signal: options.signal,
      headers: { 'Content-Type': file.type || 'application/octet-stream' },
      body: file,
    })
    if (!part.ok) throw new Error(`MinIO 첨부파일 저장에 실패했습니다. (${part.status})`)
    await gatewayRequest(`/poc-api/minio/uploads/${encodeURIComponent(uploadId)}/complete`, {
      method: 'POST',
      signal: options.signal,
      body: JSON.stringify({
        part_count: 1,
        display_name: file.name,
        content_type: file.type || 'application/octet-stream',
      }),
    })
  }
  const upload: ChangeRequestAttachmentUpload & { file: File } = {
    id: uploadId,
    change_request_id: record.id,
    round_id: record.current_round_id,
    kind,
    original_name: file.name,
    state: 'STORED',
    expected_size_bytes: file.size,
    expected_content_sha256: digest,
    provider_checksum: digest,
    failure_code: null,
    status_url: `/change-requests/${record.id}/attachment-uploads/${uploadId}`,
    finalize_url: `/change-requests/${record.id}/attachment-uploads/${uploadId}/finalize`,
    file,
  }
  changeAttachmentUploads.set(uploadId, upload)
  return publicAttachmentUpload(upload)
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

function qualityAssetFromCatalog(asset: CatalogAsset) {
  return {
    asset_id: asset.id,
    name: asset.name,
    platform: asset.platform,
    database_name: asset.database_name,
    schema_name: asset.schema_name,
    classification: asset.classification,
    lifecycle: asset.lifecycle,
    profile_readiness: 'UNAVAILABLE' as const,
    profile_observed_at: null,
    active_rule_set_count: 0,
    latest_run_state: null,
    latest_quality_outcome: null,
    latest_score_basis_points: null,
  }
}

function qualityLogicalType(value: unknown) {
  const normalized = (typeof value === 'string' || typeof value === 'number'
    ? String(value)
    : '').toUpperCase()
  if (/INT|LONG|SHORT/.test(normalized)) return 'INTEGER' as const
  if (/DECIMAL|DOUBLE|FLOAT|NUMBER|NUMERIC/.test(normalized)) return 'DECIMAL' as const
  if (/TIMESTAMP|DATETIME/.test(normalized)) return 'TIMESTAMP' as const
  if (/DATE/.test(normalized)) return 'DATE' as const
  if (/BOOL/.test(normalized)) return 'BOOLEAN' as const
  if (/CHAR|STRING|TEXT/.test(normalized)) return 'STRING' as const
  return 'OTHER' as const
}

function catalogSearch(url: URL, assets: CatalogAsset[] = []) {
  const query = (url.searchParams.get('q') ?? '').trim().toLocaleLowerCase()
  const platform = url.searchParams.get('platform')
  const databaseName = url.searchParams.get('database_name')
  const schemaName = url.searchParams.get('schema_name')
  const classification = url.searchParams.get('classification')
  const items = assets.filter((asset) => {
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

function catalogTree(
  url: URL,
  assets: CatalogAsset[] = [],
  meta: CatalogPolicyMeta = catalogMeta,
) {
  const parentKind = url.searchParams.get('parent_kind') ?? 'ROOT'
  const platform = url.searchParams.get('platform')
  const databaseName = url.searchParams.get('database')
  const schemaName = url.searchParams.get('schema')
  const limit = Number(url.searchParams.get('limit') ?? 100)
  let items: Array<Record<string, unknown>>
  if (parentKind === 'ROOT') {
    items = [...new Set(assets.map((asset) => asset.platform).filter((value): value is string => Boolean(value)))].map((value) => ({
      id: `PLATFORM:${value}`,
      kind: 'PLATFORM',
      label: value,
      asset_count: assets.filter((asset) => asset.platform === value).length,
      has_children: true,
      platform: value,
    }))
  } else if (parentKind === 'PLATFORM') {
    items = [...new Set(assets.filter((asset) => asset.platform === platform).map((asset) => asset.database_name).filter((value): value is string => Boolean(value)))].map((value) => ({
      id: `DATABASE:${platform}:${value}`,
      kind: 'DATABASE',
      label: value,
      asset_count: assets.filter((asset) => asset.platform === platform && asset.database_name === value).length,
      has_children: true,
      platform,
      database_name: value,
    }))
  } else if (parentKind === 'DATABASE') {
    items = [...new Set(assets.filter((asset) => asset.platform === platform && asset.database_name === databaseName).map((asset) => asset.schema_name).filter((value): value is string => Boolean(value)))].map((value) => ({
      id: `SCHEMA:${platform}:${databaseName}:${value}`,
      kind: 'SCHEMA',
      label: value,
      asset_count: assets.filter((asset) => asset.platform === platform && asset.database_name === databaseName && asset.schema_name === value).length,
      has_children: true,
      platform,
      database_name: databaseName,
      schema_name: value,
    }))
  } else {
    items = assets
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
  return { items: items.slice(0, limit), page: { next_cursor: null, limit }, meta }
}

async function liveCatalog(
  searchParameters: URLSearchParams,
  signal?: AbortSignal | null,
): Promise<CatalogSearch> {
  const parameters = new URLSearchParams()
  parameters.set('q', searchParameters.get('q')?.trim() || '*')
  const requestedLimit = Number(searchParameters.get('limit') ?? 100)
  parameters.set('limit', String(Math.min(100, Math.max(1, Number.isFinite(requestedLimit) ? requestedLimit : 100))))
  for (const key of [
    'cursor', 'asset_type', 'platform', 'database', 'schema', 'domain',
    'classification', 'lifecycle', 'search_fields',
  ]) {
    const value = searchParameters.get(key)
    if (value) parameters.set(key, value)
  }
  return gatewayRequest<CatalogSearch>(`/poc-api/datahub/catalog?${parameters.toString()}`, {
    ...(signal ? { signal } : {}),
  })
}

function chatRoute(mode: ChatMode) {
  return {
    requested_mode: mode,
    selected_mode: mode === 'AUTO' ? 'VECTOR' as const : mode,
    reason: mode === 'AUTO' ? 'SEMANTIC_INTENT' as const : 'EXPLICIT_SELECTION' as const,
    adapter_state: 'READY' as const,
  }
}

const systemConfigurationSpecs: Array<{
  systemId: SystemConfigurationEntry['system_id']
  label: string
  category: SystemConfigurationEntry['category']
  flag: keyof PocRuntimeFlags
  capabilityName: string
  environmentKeys: string[]
  scope: SystemConfigurationTestResult['scope']
  isCore?: boolean
}> = [
  { systemId: 'DATAHUB_GMS', label: 'DataHub GMS', category: 'CATALOG', flag: 'datahub', capabilityName: 'DataHub', environmentKeys: ['DATAHUB_GMS_URL', 'DATAHUB_GMS_TOKEN'], scope: 'AUTHENTICATED_QUERY', isCore: true },
  { systemId: 'AIRFLOW', label: 'Airflow', category: 'ORCHESTRATION', flag: 'airflow', capabilityName: 'Airflow', environmentKeys: ['AIRFLOW_URL', 'AIRFLOW_USERNAME', 'AIRFLOW_PASSWORD'], scope: 'HTTP_HEALTH' },
  {
    systemId: 'S3_STORAGE',
    label: 'MinIO / S3',
    category: 'STORAGE',
    flag: 'minio',
    capabilityName: 'MinIO',
    environmentKeys: [
      'MINIO_URL', 'MINIO_ACCESS_KEY', 'MINIO_SECRET_KEY',
      'S3_BUCKET_QUARANTINE', 'S3_BUCKET_ACCEPTED', 'S3_BUCKET_EXPORTS',
      'S3_BUCKET_FILEFOLDER', 'S3_BUCKET_INFOSCHEMA',
    ],
    scope: 'S3_HEAD_BUCKET',
  },
  { systemId: 'LLM_CHAT_MODEL', label: 'LLM Chat', category: 'AI', flag: 'llmChat', capabilityName: 'LLM Chat', environmentKeys: ['LLM_CHAT_URL', 'LLM_CHAT_MODEL', 'LLM_CHAT_TOKEN'], scope: 'MODEL_DISCOVERY' },
  { systemId: 'LLM_EMBEDDING', label: 'LLM Embedding', category: 'AI', flag: 'llmEmbedding', capabilityName: 'LLM Embedding', environmentKeys: ['LLM_EMBEDDING_URL', 'LLM_EMBEDDING_MODEL', 'LLM_EMBEDDING_TOKEN'], scope: 'EMBEDDING_INFERENCE' },
  { systemId: 'LLM_RERANKER', label: 'LLM Reranker', category: 'AI', flag: 'llmReranker', capabilityName: 'LLM Reranker', environmentKeys: ['LLM_RERANKER_URL', 'LLM_RERANKER_MODEL', 'LLM_RERANKER_TOKEN'], scope: 'RERANKING_INFERENCE' },
  { systemId: 'NEO4J', label: 'Neo4j', category: 'CATALOG', flag: 'neo4j', capabilityName: 'Neo4j', environmentKeys: ['NEO4J_HTTP_URL', 'NEO4J_USERNAME', 'NEO4J_PASSWORD'], scope: 'AUTHENTICATED_QUERY' },
]

function systemConfigurationItems(): SystemConfigurationEntry[] {
  const flags = runtimeFlags()
  return systemConfigurationSpecs.map((spec) => {
    const configured = Boolean(flags[spec.flag])
    const environmentTemplate = spec.environmentKeys.map((key) => `${key}=`).join('\n')
    return {
      system_id: spec.systemId,
      label: spec.label,
      category: spec.category,
      requirement: spec.isCore ? 'CORE_CONNECTOR' : 'FEATURE_CONNECTOR',
      description: `${spec.label} POC server-side connector 상태입니다. 비밀값은 브라우저에 노출하지 않습니다.`,
      connection_requirements: spec.environmentKeys.map((key) => ({
        key,
        label: key,
        required: true,
        secret: /(TOKEN|PASSWORD|SECRET|ACCESS_KEY)/.test(key),
        example: null,
      })),
      state: configured ? 'CONFIGURED' : 'NOT_CONFIGURED',
      management_plane: 'DEPLOYMENT',
      secret_reference_configured: configured && spec.environmentKeys.some((key) => /(TOKEN|PASSWORD|SECRET|ACCESS_KEY)/.test(key)),
      embedding_state: spec.systemId === 'LLM_EMBEDDING'
        ? configured ? 'AVAILABLE' : 'NOT_CONFIGURED'
        : 'NOT_APPLICABLE',
      configuration_yaml: `source: deploy/poc/.env\nconfigured: ${configured}`,
      template_yaml: environmentTemplate,
      display_yaml: `configured: ${configured}`,
      environment_template: environmentTemplate,
      effective_configuration_yaml: `configured: ${configured}\ncredentials: redacted`,
      version: 1,
      configured_at: configured ? new Date().toISOString() : null,
      runtime_supported: true,
      restart_scope: 'API_ONLY',
      activation_state: configured ? 'APPLIED_TO_API_PROCESS' : 'NOT_CONFIGURED',
      tested_version: null,
      test_status: null,
      tested_at: null,
      activated_version: configured ? 1 : null,
      activated_at: configured ? new Date().toISOString() : null,
      applied_version: configured ? 1 : null,
      ...(spec.isCore ? { is_core: true } : {}),
    }
  })
}

async function testSystemConfiguration(
  systemId: string,
  signal?: AbortSignal | null,
): Promise<SystemConfigurationTestResult> {
  const spec = systemConfigurationSpecs.find((item) => item.systemId === systemId)
  if (!spec) throw new Error('지원하지 않는 POC 시스템 설정입니다.')
  const response = await gatewayRequest<{ items: Array<{ name: string; state: string; observed_at: string; latency_ms?: number; detail_code?: string }> }>(
    '/poc-api/capabilities',
    { ...(signal ? { signal } : {}) },
  )
  const capability = response.items.find((item) => item.name === spec.capabilityName)
  const available = capability?.state === 'available'
  return {
    system_id: spec.systemId,
    status: available ? 'AVAILABLE' : 'UNAVAILABLE',
    scope: spec.scope,
    latency_ms: capability?.latency_ms ?? 0,
    detail: available
      ? `${spec.label} live probe가 성공했습니다.`
      : `${spec.label} probe 상태: ${capability?.detail_code ?? 'NOT_CONFIGURED'}`,
    configuration_version: 1,
    tested_at: capability?.observed_at ?? new Date().toISOString(),
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
    const question = typeof body.question === 'string' ? body.question.trim() : ''
    if (!question) return Promise.reject(new Error('질문을 입력하세요.'))
    const mode = ['AUTO', 'GENERAL', 'VECTOR', 'GRAPH'].includes(String(body.mode))
      ? body.mode as ChatMode
      : 'AUTO'
    const sessionId = typeof body.session_id === 'string' && body.session_id
      ? body.session_id
      : nextId('chat-session')
    const live = runtimeFlags().llmChat && runtimeFlags().datahub
      ? gatewayRequest<{ answer: string; evidence: Array<Record<string, unknown>> }>('/poc-api/llm/chat', {
          method: 'POST',
          signal: options.signal,
          body: JSON.stringify({ question }),
        })
      : Promise.reject(new Error('검증 불가: DataHub와 LLM Chat 연결을 모두 설정해야 합니다.'))
    return live.then(async (liveResult) => {
      const workflow = chatWorkflow.map((step) => ({
        ...step,
        detail_code: runtimeFlags().llmChat ? 'POC_LIVE_PROVIDER' : step.detail_code,
      }))
      for (const step of workflow) onEvent({ event: 'workflow', data: { ...step, status: 'IN_PROGRESS' } })
      const requestId = nextId('chat-request')
      const responseId = nextId('chat-response')
      const route = chatRoute(mode)
      const evidence = await Promise.all(liveResult.evidence.map(async (item, index) => {
        const resourceId = responseString(item.id ?? item.external_urn, '')
        const classification = ['PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED']
          .includes(String(item.classification))
          ? item.classification as 'PUBLIC' | 'INTERNAL' | 'CONFIDENTIAL' | 'RESTRICTED'
          : 'INTERNAL'
        return {
          chunk_id: `datahub-evidence-${index + 1}`,
          resource_id: resourceId,
          classification,
          system_id: null,
          domain_id: null,
          owner_department_id: null,
          name: responseString(item.name, 'DataHub asset'),
          description: responseString(item.description, '') || null,
          source_type: 'CATALOG_ASSET',
          source_locator: responseString(item.external_urn ?? item.id, ''),
          source_version: responseString(item.source_version, 'datahub-live'),
          content_hash: await sha256(JSON.stringify(item)),
          effective_from: new Date().toISOString(),
          effective_until: null,
          extraction_method: 'DATAHUB_GMS',
          rank: index + 1,
          retrieval_method: runtimeFlags().llmReranker ? 'RERANKED' : 'DATAHUB_SEARCH',
        }
      }))
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
    return Promise.reject(new Error('생성된 내보내기 산출물이 없습니다.'))
  }

  private async dispatch(url: URL, options: PocRequestOptions): Promise<unknown> {
    const path = url.pathname
    const method = options.method?.toUpperCase() ?? 'GET'

    if (path === '/admin/me') return {
      subject_id: POC_SUBJECT_ID,
      workspace_id: POC_WORKSPACE_ID,
      display_name: 'POC User',
      authentication_assurance: 'UNKNOWN',
      fallback_enabled: false,
      allowed_operations: [
        'IDENTITY_USER_PROVISION',
        'MEMBERSHIP_ACCESS_READ',
        'SYSTEM_CONFIGURATION_READ',
      ],
      action_vocabulary: ['POC_BROWSER_MEMORY_USER_CREATE', 'POC_PROVIDER_CONFIGURATION_READ'],
    }
    if (path === '/capabilities') {
      return runtimeFlags().datahub || runtimeFlags().airflow || runtimeFlags().minio
        || runtimeFlags().llmChat || runtimeFlags().neo4j
        ? gatewayRequest('/poc-api/capabilities', { signal: options.signal })
        : capabilities
    }
    if (path === '/catalog/export-capability') return { enabled: false }
    if (path === '/operations/dashboard') {
      if (runtimeFlags().datahub) {
        const dashboard = await gatewayRequest<Record<string, unknown>>(
          '/poc-api/datahub/dashboard', { signal: options.signal },
        )
        const changesByState = changeRecords.reduce<Record<string, number>>((counts, record) => {
          counts[record.state] = (counts[record.state] ?? 0) + 1
          return counts
        }, {})
        return { ...dashboard, changes_by_state: changesByState }
      }
      return {
        observed_at: new Date().toISOString(),
        changes_by_state: {},
        catalog_asset_count: 0,
        catalog_described_asset_count: 0,
        catalog_glossary_term_count: 0,
        catalog_schema_metrics: [],
        catalog_schema_metrics_truncated: false,
      }
    }

    if (path === '/catalog/assets') {
      return runtimeFlags().datahub
        ? liveCatalog(url.searchParams, options.signal)
        : catalogSearch(url, [])
    }
    if (path === '/catalog/facets') {
      if (runtimeFlags().datahub) {
        return gatewayRequest(`/poc-api/datahub/facets?${url.searchParams.toString()}`, {
          signal: options.signal,
        })
      }
      return {
        asset_types: [], platforms: [], classifications: [], databases: [], schemas: [], domains: [], lifecycles: [],
        meta: catalogMeta,
      }
    }
    if (path === '/catalog/suggestions') {
      const query = (url.searchParams.get('q') ?? '').toLocaleLowerCase()
      if (runtimeFlags().datahub) {
        const live = await liveCatalog(new URLSearchParams({ q: query, limit: '8' }), options.signal)
        return {
          items: live.items.slice(0, 8).map((asset) => ({
            id: asset.id,
            name: asset.name,
            asset_type: asset.asset_type,
            platform: asset.platform,
            database_name: asset.database_name,
            schema_name: asset.schema_name,
            matches: asset.matches,
          })),
          meta: live.meta,
          match_mode: 'ALL',
        }
      }
      return { items: [], meta: catalogMeta, match_mode: 'ALL' }
    }
    if (path === '/catalog/vocabulary') {
      if (runtimeFlags().datahub) {
        const live = await liveCatalog(new URLSearchParams({ q: '*', limit: '100' }), options.signal)
        return {
          items: [...new Set(live.items.flatMap((asset) => [asset.domain, ...(asset.tags ?? []), ...(asset.terms ?? [])]).filter((item): item is string => Boolean(item)))],
          meta: live.meta,
        }
      }
      return { items: [], meta: catalogMeta }
    }
    if (path === '/catalog/tree/nodes') {
      if (runtimeFlags().datahub) {
        return gatewayRequest(`/poc-api/datahub/tree?${url.searchParams.toString()}`, {
          signal: options.signal,
        })
      }
      return catalogTree(url, [])
    }
    if (path.endsWith('/lineage') && path.startsWith('/catalog/assets/')) {
      const assetId = decodeURIComponent(path.split('/')[3] ?? '')
      if (runtimeFlags().datahub && assetId.startsWith('urn:li:')) {
        return gatewayRequest(`/poc-api/datahub/lineage?urn=${encodeURIComponent(assetId)}`, { signal: options.signal })
      }
      throw new Error(`DataHub lineage를 사용할 수 없는 자산입니다: ${assetId}`)
    }
    const metadataPreview = path.match(/^\/catalog\/assets\/([^/]+)\/(description-previews|column-description-previews|controlled-metadata-previews)$/)
    if (metadataPreview && method === 'POST') {
      const assetId = decodeURIComponent(metadataPreview[1] ?? '')
      if (!runtimeFlags().datahub || !assetId.startsWith('urn:li:')) {
        throw new Error('DataHub 원본 메타데이터를 확인할 수 없습니다.')
      }
      const detail = await gatewayRequest<CatalogAssetDetail>(
        `/poc-api/datahub/asset?urn=${encodeURIComponent(assetId)}`, { signal: options.signal },
      )
      liveAssetDetails.set(assetId, detail)
      const body = jsonBody(options)
      const kind = metadataPreview[2]
      const observedAt = new Date().toISOString()
      if (kind === 'description-previews') {
        const proposed = responseString(body.description, '')
        const beforeHash = await sha256(JSON.stringify({ description: detail.description ?? null }))
        const afterHash = await sha256(JSON.stringify({ description: proposed }))
        return {
          asset_id: detail.id,
          target_ref: detail.external_urn,
          aspect_name: 'datasetProperties',
          current_description: detail.description ?? null,
          proposed_description: proposed,
          before_hash: beforeHash,
          after_hash: afterHash,
          preview_etag: `"${beforeHash}"`,
          source_version: detail.source_version,
          observed_at: observedAt,
        }
      }
      if (kind === 'column-description-previews') {
        const fieldPath = responseString(body.field_path, '')
        const field = detail.schema_fields.find((item) => (item.fieldPath ?? item.field_path) === fieldPath)
        if (!field) throw new Error('DataHub 원본에서 대상 컬럼을 찾을 수 없습니다.')
        const currentDescription = typeof field.description === 'string' ? field.description : null
        const proposed = responseString(body.description, '')
        const beforeHash = await sha256(JSON.stringify({ field_path: fieldPath, description: currentDescription }))
        const afterHash = await sha256(JSON.stringify({ field_path: fieldPath, description: proposed }))
        return {
          asset_id: detail.id,
          target_ref: detail.external_urn,
          aspect_name: 'schemaMetadata',
          field_path: fieldPath,
          current_description: currentDescription,
          proposed_description: proposed,
          before_hash: beforeHash,
          after_hash: afterHash,
          preview_etag: `"${beforeHash}"`,
          source_version: detail.source_version,
          observed_at: observedAt,
        }
      }
      const aspectName = ['domains', 'globalTags', 'glossaryTerms'].includes(String(body.aspect_name))
        ? String(body.aspect_name)
        : 'globalTags'
      const proposedRefs = Array.isArray(body.refs)
        ? body.refs.filter((item): item is string => typeof item === 'string')
        : []
      const currentRefs = aspectName === 'domains'
        ? detail.domain ? [detail.domain] : []
        : aspectName === 'globalTags'
          ? detail.tags ?? []
          : detail.glossary_terms.flatMap((entry) => {
              const term = entry.term as Record<string, unknown> | undefined
              const value = term?.urn ?? entry.urn
              return typeof value === 'string' ? [value] : []
            })
      const beforeHash = await sha256(JSON.stringify({ aspect_name: aspectName, refs: currentRefs }))
      const afterHash = await sha256(JSON.stringify({ aspect_name: aspectName, refs: proposedRefs }))
      return {
        asset_id: detail.id,
        target_ref: detail.external_urn,
        aspect_name: aspectName,
        current_refs: currentRefs,
        proposed_refs: proposedRefs,
        before_hash: beforeHash,
        after_hash: afterHash,
        preview_etag: `"${beforeHash}"`,
        source_version: detail.source_version,
        observed_at: observedAt,
      }
    }
    const metadataChangeRequest = path.match(/^\/catalog\/assets\/([^/]+)\/(description-change-requests|column-description-change-requests|controlled-metadata-change-requests)$/)
    if (metadataChangeRequest && method === 'POST') {
      const assetId = decodeURIComponent(metadataChangeRequest[1] ?? '')
      const detail = liveAssetDetails.get(assetId)
      if (!detail) throw new Error('변경 요청 전에 DataHub 원본 미리보기를 다시 실행하세요.')
      const body = jsonBody(options)
      const kind = metadataChangeRequest[2]
      const target: Record<string, unknown> = { kind: 'EXISTING', asset_id: assetId }
      if (kind === 'description-change-requests') target.description = responseString(body.description, '')
      if (kind === 'column-description-change-requests') target.columns = [{
        field_path: responseString(body.field_path, ''),
        description: responseString(body.description, ''),
        requested_change: responseString(body.change_description, ''),
      }]
      const record = createChangeRequest({
        title: responseString(body.title, `${detail.name} metadata 변경`),
        system_id: detail.platform,
        request_reason: responseString(body.change_description, ''),
        request_content: responseString(body.change_description, ''),
        priority: 'NORMAL',
        urgency: 'NORMAL',
        security_level: detail.classification,
        targets: [target],
      })
      if (kind === 'column-description-change-requests') record.items[0]!.aspect_name = 'schemaMetadata'
      if (kind === 'controlled-metadata-change-requests') {
        record.items[0]!.aspect_name = responseString(body.aspect_name, 'globalTags')
        record.items[0]!.after_document = { refs: Array.isArray(body.refs) ? body.refs : [] }
      }
      return { ...record }
    }
    if (path.startsWith('/catalog/assets/')) {
      const assetId = decodeURIComponent(path.split('/')[3] ?? '')
      if (runtimeFlags().datahub && assetId.startsWith('urn:li:')) {
        const parameters = new URLSearchParams({ urn: assetId })
        const fieldOffset = url.searchParams.get('field_offset')
        const fieldLimit = url.searchParams.get('field_limit')
        if (fieldOffset) parameters.set('field_offset', fieldOffset)
        if (fieldLimit) parameters.set('field_limit', fieldLimit)
        const asset = await gatewayRequest<CatalogAssetDetail>(
          `/poc-api/datahub/asset?${parameters.toString()}`, { signal: options.signal },
        )
        liveAssetDetails.set(assetId, asset)
        return asset
      }
      throw new Error(`DataHub 상세를 사용할 수 없는 자산입니다: ${assetId}`)
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
    if (path === '/registration/manual-submissions' && method === 'POST') {
      const body = jsonBody(options)
      const now = new Date().toISOString()
      const serialNumber = manualSubmissionReports.length + 1
      const columnEdits = Array.isArray(body.column_edits) ? body.column_edits : []
      const submission = {
        id: nextId('manual-submission'),
        state: 'APPLIED',
        serial_number: serialNumber,
        row_count: 1 + columnEdits.length,
        source_version: responseString(body.source_version, 'datahub-live-poc'),
        provider_source_version: responseString(body.provider_source_version, 'datahub-live'),
        created_at: now,
        updated_at: now,
        applied_at: now,
        attempts: 1,
        next_attempt_at: null,
        last_error_code: null,
        version: 1,
      }
      const reportHash = await sha256(JSON.stringify(body))
      const aspects = [
        ['datasetProperties', 1],
        ['domains', 2],
        ['globalTags', 3],
        ['glossaryTerms', 4],
        ['schemaMetadata', 5],
      ].map(([aspectName, aspectOrdinal]) => ({
        aspect_name: aspectName,
        aspect_ordinal: aspectOrdinal,
        outcome: 'APPLIED_VERIFIED',
        before_hash: null,
        expected_hash: reportHash,
        observed_hash: reportHash,
        write_attempted: false,
        failure_code: null,
        provider_version: 'POC_MEMORY_ONLY',
        provider_response_hash: reportHash,
        observed_at: now,
      }))
      const report = {
        submission,
        attempts: [{
          id: nextId('manual-attempt'),
          attempt_no: 1,
          lease_epoch: 1,
          state: 'APPLIED',
          failure_code: null,
          report_root_hash: reportHash,
          started_at: now,
          finished_at: now,
          aspects,
        }],
      }
      manualSubmissionReports.unshift(report)
      return submission
    }
    if (path === '/registration/manual-submissions' && method === 'GET') {
      const limit = Number(url.searchParams.get('limit') ?? 25)
      return {
        items: manualSubmissionReports.slice(0, limit).map((item) => item.submission),
        page: { next_cursor: null, limit },
      }
    }
    const manualSubmission = path.match(/^\/registration\/manual-submissions\/([^/]+)$/)
    if (manualSubmission && method === 'GET') {
      const report = manualSubmissionReports.find((item) => (
        (item.submission as { id?: unknown } | undefined)?.id === decodeURIComponent(manualSubmission[1] ?? '')
      ))
      if (!report) throw new Error('Manual 실행 이력을 찾을 수 없습니다.')
      return report
    }

    if (path === '/change-requests/systems') {
      return runtimeFlags().datahub
        ? gatewayRequest('/poc-api/datahub/systems', { signal: options.signal })
        : { items: [] }
    }
    if (path === '/change-requests/targets') {
      const systemId = url.searchParams.get('system_id')
      const result = runtimeFlags().datahub
        ? await liveCatalog(new URLSearchParams({
            q: url.searchParams.get('q') ?? '*',
            limit: url.searchParams.get('limit') ?? '12',
            ...(systemId ? { platform: systemId } : {}),
          }), options.signal)
        : catalogSearch(url, [])
      const items = result.items.filter((asset) => !systemId || asset.platform === systemId)
      return { ...result, items, total: items.length, total_exact: true }
    }
    const changeTarget = path.match(/^\/change-requests\/targets\/(.+)$/)
    if (changeTarget) {
      const assetId = decodeURIComponent(changeTarget[1] ?? '')
      if (runtimeFlags().datahub && assetId.startsWith('urn:li:')) {
        const asset = await gatewayRequest<CatalogAssetDetail>(
          `/poc-api/datahub/asset?urn=${encodeURIComponent(assetId)}`, { signal: options.signal },
        )
        liveAssetDetails.set(assetId, asset)
        return asset
      }
      throw new Error(`DataHub 상세를 사용할 수 없는 변경 대상입니다: ${assetId}`)
    }
    const revisionTargetList = path.match(/^\/change-requests\/([^/]+)\/revision-targets$/)
    if (revisionTargetList && method === 'GET') {
      const record = changeRecordById(decodeURIComponent(revisionTargetList[1] ?? ''))
      if (record.state !== 'CHANGES_REQUESTED' || !record.revision_allowed) {
        throw new Error('현재 변경 요청은 수정 대상 검색을 사용할 수 없습니다.')
      }
      const systemId = currentRound(record)?.selected_system_id
      if (!runtimeFlags().datahub || !systemId) return catalogSearch(url, [])
      return liveCatalog(new URLSearchParams({
        q: url.searchParams.get('q') ?? '*',
        limit: url.searchParams.get('limit') ?? '12',
        platform: systemId,
        ...(url.searchParams.get('cursor') ? { cursor: url.searchParams.get('cursor')! } : {}),
      }), options.signal)
    }
    const revisionTargetDetail = path.match(/^\/change-requests\/([^/]+)\/revision-targets\/(.+)$/)
    if (revisionTargetDetail && method === 'GET') {
      const record = changeRecordById(decodeURIComponent(revisionTargetDetail[1] ?? ''))
      if (record.state !== 'CHANGES_REQUESTED' || !record.revision_allowed) {
        throw new Error('현재 변경 요청은 수정 대상 상세를 사용할 수 없습니다.')
      }
      const assetId = decodeURIComponent(revisionTargetDetail[2] ?? '')
      if (!runtimeFlags().datahub || !assetId.startsWith('urn:li:')) {
        throw new Error('DataHub 현재 대상 상세를 확인할 수 없습니다.')
      }
      const asset = await gatewayRequest<CatalogAssetDetail>(
        `/poc-api/datahub/asset?urn=${encodeURIComponent(assetId)}`, { signal: options.signal },
      )
      if (asset.platform !== currentRound(record)?.selected_system_id) {
        throw new Error('현재 변경 요청의 관련 시스템과 대상이 일치하지 않습니다.')
      }
      liveAssetDetails.set(assetId, asset)
      return asset
    }
    if (path === '/change-requests/intake' && method === 'POST') {
      return createChangeRequest(jsonBody(options))
    }
    const revisionCommand = path.match(/^\/change-requests\/([^/]+)\/revisions$/)
    if (revisionCommand && method === 'POST') {
      const record = changeRecordById(decodeURIComponent(revisionCommand[1] ?? ''))
      requireCurrentVersion(record, options)
      return { ...reviseChangeRequest(record, jsonBody(options)) }
    }
    if (path === '/change-requests/summaries') {
      const state = url.searchParams.get('state')
      return {
        items: changeRecords.filter((record) => !state || record.state === state).map(changeSummaryOf),
        overview: [],
        overview_truncated: false,
        page: { next_cursor: null, limit: 25 },
      }
    }
    const attachmentCreate = path.match(/^\/change-requests\/([^/]+)\/attachments$/)
    if (attachmentCreate && method === 'POST') {
      return createChangeAttachmentUpload(decodeURIComponent(attachmentCreate[1] ?? ''), options)
    }
    const attachmentPage = path.match(/^\/change-requests\/([^/]+)\/attachments\/page$/)
    if (attachmentPage && method === 'GET') {
      const record = changeRecordById(decodeURIComponent(attachmentPage[1] ?? ''))
      const limit = Number(url.searchParams.get('limit') ?? 25)
      return {
        items: (changeAttachments.get(record.id) ?? [])
          .filter((item) => item.round_id === record.current_round_id)
          .slice(0, limit)
          .map(({ file: _file, ...item }) => { void _file; return item }),
        page: { next_cursor: null, limit },
      }
    }
    const attachmentDownload = path.match(/^\/change-requests\/([^/]+)\/attachments\/([^/]+)\/download$/)
    if (attachmentDownload && method === 'GET') {
      const record = changeRecordById(decodeURIComponent(attachmentDownload[1] ?? ''))
      const attachment = (changeAttachments.get(record.id) ?? [])
        .find((item) => item.id === decodeURIComponent(attachmentDownload[2] ?? ''))
      if (!attachment) throw new Error('첨부파일을 찾을 수 없습니다.')
      return { url: URL.createObjectURL(attachment.file) }
    }
    const attachmentUploadList = path.match(/^\/change-requests\/([^/]+)\/attachment-uploads$/)
    if (attachmentUploadList && method === 'GET') {
      const record = changeRecordById(decodeURIComponent(attachmentUploadList[1] ?? ''))
      const roundId = url.searchParams.get('round_id')
      const limit = Math.min(10, Number(url.searchParams.get('limit') ?? 10))
      return {
        items: [...changeAttachmentUploads.values()]
          .filter((item) => item.change_request_id === record.id && (!roundId || item.round_id === roundId))
          .slice(0, limit)
          .map(publicAttachmentUpload),
      }
    }
    const attachmentFinalize = path.match(/^\/change-requests\/([^/]+)\/attachment-uploads\/([^/]+)\/finalize$/)
    if (attachmentFinalize && method === 'POST') {
      const record = changeRecordById(decodeURIComponent(attachmentFinalize[1] ?? ''))
      const uploadId = decodeURIComponent(attachmentFinalize[2] ?? '')
      const upload = changeAttachmentUploads.get(uploadId)
      if (!upload || upload.change_request_id !== record.id) throw new Error('첨부파일 업로드를 찾을 수 없습니다.')
      if (upload.round_id !== record.current_round_id) throw new Error('이전 회차 첨부파일은 현재 회차에 확정할 수 없습니다.')
      if (upload.state !== 'FINALIZED') {
        const attachments = changeAttachments.get(record.id) ?? []
        attachments.push({
          id: nextId('change-attachment'),
          kind: upload.kind,
          round_id: upload.round_id,
          original_name: upload.original_name,
          serial_number: attachments.length + 1,
          content_type: upload.file.type || 'application/octet-stream',
          size_bytes: upload.expected_size_bytes,
          content_sha256: upload.expected_content_sha256,
          created_at: new Date().toISOString(),
          file: upload.file,
        })
        changeAttachments.set(record.id, attachments)
        upload.state = 'FINALIZED'
      }
      return publicAttachmentUpload(upload)
    }
    const attachmentUploadStatus = path.match(/^\/change-requests\/([^/]+)\/attachment-uploads\/([^/]+)$/)
    if (attachmentUploadStatus && method === 'GET') {
      const record = changeRecordById(decodeURIComponent(attachmentUploadStatus[1] ?? ''))
      const upload = changeAttachmentUploads.get(decodeURIComponent(attachmentUploadStatus[2] ?? ''))
      if (!upload || upload.change_request_id !== record.id) throw new Error('첨부파일 업로드를 찾을 수 없습니다.')
      return publicAttachmentUpload(upload)
    }
    if (/^\/change-requests\/[^/]+\/apply-report$/.test(path)) return {
      change_request_id: path.split('/')[2] ?? '',
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
    const changeCommand = path.match(/^\/change-requests\/([^/]+)\/(transitions|approvals|complete-intake|test-runs)$/)
    if (changeCommand && method === 'POST') {
      const changeRequestId = decodeURIComponent(changeCommand[1] ?? '')
      const command = changeCommand[2]
      const record = changeRecordById(changeRequestId)
      requireCurrentVersion(record, options)
      const body = jsonBody(options)
      const now = new Date().toISOString()
      if (command === 'approvals') {
        const stage = responseString(body.stage, 'REVIEW') as 'REVIEW' | 'TEST' | 'FINAL'
        const requiredState: Record<typeof stage, ChangeRequestState> = {
          REVIEW: 'IN_REVIEW', TEST: 'TESTING', FINAL: 'FINAL_REVIEW',
        }
        if (record.state !== requiredState[stage]) throw new Error('현재 단계에서는 해당 승인을 기록할 수 없습니다.')
        if (hasCurrentApproval(record, stage)) throw new Error('현재 회차에 이미 기록된 승인입니다.')
        const systemId = currentRound(record)?.selected_system_id ?? null
        record.approvals.push({
          id: nextId('change-approval'),
          stage,
          decision: responseString(body.decision, 'APPROVED'),
          actor_id: POC_SUBJECT_ID,
          reason: responseString(body.reason, 'POC 단일 사용자 승인 시연'),
          occurred_at: now,
          round_id: record.current_round_id,
          authorities: stage === 'FINAL'
            ? [
                { kind: 'SYSTEM_DEVELOPER', system_id: systemId },
                { kind: 'SYSTEM_DATA_STEWARD', system_id: systemId },
                { kind: 'GLOBAL_ADMIN', system_id: null },
              ]
            : [{ kind: 'SYSTEM_DEVELOPER', system_id: systemId }],
        })
      } else if (command === 'test-runs') {
        if (record.state !== 'TESTING') throw new Error('TESTING 단계에서만 테스트 결과를 기록할 수 있습니다.')
        const attachmentId = responseString(body.attachment_id, '')
        const attachment = (changeAttachments.get(record.id) ?? []).find((item) => (
          item.id === attachmentId && item.round_id === record.current_round_id && item.kind === 'TEST'
        ))
        if (!attachment) throw new Error('현재 회차의 TEST 첨부파일을 선택하세요.')
        record.test_runs.push({
          id: nextId('change-test-run'),
          round_id: record.current_round_id,
          system_id: responseString(body.system_id, record.rounds.at(-1)?.selected_system_id ?? 'POC_SYSTEM'),
          attachment_id: attachment.id,
          state: body.state === 'FAILED' ? 'FAILED' : 'PASSED',
          plan_hash: '7'.repeat(64),
          result_hash: '8'.repeat(64),
          bounded_summary: body.bounded_summary && typeof body.bounded_summary === 'object'
            ? body.bounded_summary as Record<string, unknown>
            : {},
          recorded_by: POC_SUBJECT_ID,
          occurred_at: now,
        })
      } else {
        const previous = record.state
        const target = command === 'complete-intake'
          ? 'COMPLETED'
          : responseString(body.target_state, previous) as ChangeRequestState
        const legalTransitions: Partial<Record<ChangeRequestState, ChangeRequestState[]>> = {
          REGISTERED: ['IN_REVIEW', 'CANCELLED'],
          IN_REVIEW: ['TESTING', 'CHANGES_REQUESTED', 'REJECTED', 'CANCELLED'],
          TESTING: ['IN_REVIEW', 'FINAL_REVIEW', 'CHANGES_REQUESTED', 'REJECTED', 'CANCELLED'],
          FINAL_REVIEW: ['COMPLETED', 'CHANGES_REQUESTED', 'REJECTED', 'CANCELLED'],
          APPLY_FAILED: ['APPLY_QUEUED', 'CANCELLED'],
          CHANGES_REQUESTED: ['CANCELLED'],
        }
        if (!(legalTransitions[previous] ?? []).includes(target)) throw new Error('허용되지 않은 변경 요청 상태 전이입니다.')
        if (previous === 'IN_REVIEW' && target === 'TESTING' && !hasCurrentApproval(record, 'REVIEW')) {
          throw new Error('REVIEW 승인 후 TESTING 단계로 이동할 수 있습니다.')
        }
        if (previous === 'TESTING' && target === 'FINAL_REVIEW') {
          const passed = record.test_runs.some((run) => run.round_id === record.current_round_id && run.state === 'PASSED')
          if (!passed || !hasCurrentApproval(record, 'TEST')) {
            throw new Error('현재 회차의 통과한 테스트 결과와 TEST 승인이 필요합니다.')
          }
        }
        if (previous === 'FINAL_REVIEW' && target === 'COMPLETED' && !hasCurrentApproval(record, 'FINAL')) {
          throw new Error('FINAL 승인 후 변경 요청을 완료할 수 있습니다.')
        }
        record.state = target
        if (target === 'REJECTED' || target === 'CANCELLED' || target === 'COMPLETED') record.revision_allowed = false
        record.transitions.push({
          id: nextId('change-transition'),
          from_state: previous,
          to_state: target,
          actor_id: POC_SUBJECT_ID,
          reason: responseString(body.reason, 'POC browser-memory transition'),
          occurred_at: now,
          round_id: record.current_round_id,
        })
      }
      record.version += 1
      return { ...record }
    }
    if (/^\/change-requests\/[^/]+$/.test(path)) {
      return { ...changeRecordById(path.split('/')[2] ?? '') }
    }

    if (path === '/quality/capability') {
      const observedAt = new Date()
      const readAvailable = runtimeFlags().datahub
      return {
        contract_version: 'QUALITY_CAPABILITY_V2',
        observed_at: observedAt.toISOString(),
        valid_until: new Date(observedAt.getTime() + 30_000).toISOString(),
        cache_scope: POC_CACHE_SCOPE,
        axes: ['read_access', 'profile_readiness', 'rule_authoring', 'review', 'activation', 'manual_execution', 'scheduling', 'operations'].map((id) => ({
          id,
          state: id === 'read_access' && readAvailable ? 'AVAILABLE' : 'UNAVAILABLE',
          reason_code: id === 'read_access' && !readAvailable
            ? 'DATAHUB_NOT_CONFIGURED'
            : id === 'read_access' ? null : 'QUALITY_CONTROL_PLANE_NOT_CONFIGURED',
        })),
      }
    }
    if (path === '/quality/dashboard') {
      const dashboard = runtimeFlags().datahub
        ? await gatewayRequest<{ catalog_asset_count: number; catalog_schema_metrics: unknown[] }>(
            '/poc-api/datahub/dashboard', { signal: options.signal },
          )
        : { catalog_asset_count: 0, catalog_schema_metrics: [] }
      return {
        contract_version: 'QUALITY_DASHBOARD_V1',
        cache_scope: POC_CACHE_SCOPE,
        ...authorizationWindow(),
        as_of: new Date().toISOString(),
        schema_count: dashboard.catalog_schema_metrics.length,
        table_count: dashboard.catalog_asset_count,
        active_rule_set_count: 0,
        common_rule_template_count: 0,
        covered_table_count: 0,
        table_coverage_basis_points: dashboard.catalog_asset_count ? 0 : null,
        managed_rule_sets: managedIndicators,
        schemas: [],
        schemas_truncated: false,
      }
    }
    if (path === '/quality/overview') return {
      availability: runtimeFlags().datahub ? 'AVAILABLE' : 'UNAVAILABLE', freshness: 'UNKNOWN', as_of: new Date().toISOString(),
      authorization_valid_until: authorizationWindow().authorization_valid_until,
      overall_state: 'UNKNOWN', active_rule_set_count: 0, evaluated_rule_set_count: 0,
      unknown_rule_set_count: 0, passed_count: 0, advisory_failed_count: 0,
      blocking_failed_count: 0, evaluated_rule_count: 0, score_basis_points: null,
      coverage_basis_points: null, trend: [], failure_code: 'QUALITY_CONTROL_PLANE_NOT_CONFIGURED',
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
      return { items: [], cache_scope: POC_CACHE_SCOPE, ...authorizationWindow() }
    }
    if (path === '/quality/assets') {
      if (!runtimeFlags().datahub) return { ...qualityList([], url) }
      const result = await liveCatalog(new URLSearchParams({
        q: url.searchParams.get('q') ?? '*',
        limit: url.searchParams.get('limit') ?? '25',
        ...(url.searchParams.get('schema') ? { schema: url.searchParams.get('schema')! } : {}),
        ...(url.searchParams.get('cursor') ? { cursor: url.searchParams.get('cursor')! } : {}),
      }), options.signal)
      return {
        items: result.items.map(qualityAssetFromCatalog),
        page: result.page,
        cache_scope: POC_CACHE_SCOPE,
        ...authorizationWindow(),
      }
    }
    const qualityWorkspace = path.match(/^\/quality\/assets\/([^/]+)\/workspace$/)
    if (qualityWorkspace) {
      const assetId = decodeURIComponent(qualityWorkspace[1] ?? '')
      if (!runtimeFlags().datahub) throw new Error('DataHub가 설정되지 않았습니다.')
      const detail = await gatewayRequest<CatalogAssetDetail>(
        `/poc-api/datahub/asset?urn=${encodeURIComponent(assetId)}`, { signal: options.signal },
      )
      liveAssetDetails.set(assetId, detail)
      const fields = detail.schema_fields.flatMap((field) => {
        const fieldPath = field.fieldPath ?? field.field_path
        if (typeof fieldPath !== 'string' || !fieldPath) return []
        const nativeType = field.nativeDataType ?? field.native_data_type ?? field.type
        return [{
          field_identifier: fieldPath,
          display_path: fieldPath,
          logical_type: qualityLogicalType(nativeType),
          supported_rule_kinds: [],
          configured_rule_count: 0,
          active_rule_count: 0,
          evaluated_rule_count: 0,
          passed_count: 0,
          advisory_failed_count: 0,
          blocking_failed_count: 0,
          latest_score_basis_points: null,
          latest_quality_outcome: null,
          latest_evaluated_at: null,
        }]
      })
      return qualityEnvelope({
        asset: qualityAssetFromCatalog(detail),
        rule_sets: [],
        runs: [],
        trend: [],
        authoring: {
          state: 'UNAVAILABLE',
          reason_code: 'QUALITY_CONTROL_PLANE_NOT_CONFIGURED',
          source_version: detail.source_version,
          schema_hash: null,
          fields: fields.map(({ configured_rule_count: _configured, active_rule_count: _active, evaluated_rule_count: _evaluated, passed_count: _passed, advisory_failed_count: _advisory, blocking_failed_count: _blocking, latest_score_basis_points: _score, latest_quality_outcome: _outcome, latest_evaluated_at: _at, ...field }) => {
            void _configured; void _active; void _evaluated; void _passed; void _advisory; void _blocking; void _score; void _outcome; void _at
            return field
          }),
        },
        fields,
        score_policy: scorePolicy,
      })
    }
    if (/^\/quality\/assets\/[^/]+\/fields\/[^/]+\/workspace$/.test(path)) throw new Error('품질 제어 plane이 설정되지 않았습니다.')
    if (/^\/quality\/assets\/[^/]+$/.test(path)) throw new Error('품질 제어 plane이 설정되지 않았습니다.')
    if (path === '/quality/common-rule-templates') return { items: [], cache_scope: POC_CACHE_SCOPE, ...authorizationWindow() }
    if (path === '/quality/rule-sets') return qualityList([], url)
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
    if (path === '/quality/runs') return qualityList([], url)
    if (/^\/quality\/runs\/[^/]+\/results$/.test(path)) return qualityList([], url)
    if (path === '/quality/issues') return qualityList([], url)

    if (path === '/knowledge/graphs') return []
    if (path === '/knowledge/registry/assets') return { items: [], next_cursor: null, limit: Number(url.searchParams.get('limit') ?? 25) }
    if (/^\/knowledge\/registry\/assets\/[^/]+\/(detail|versions)$/.test(path)) throw new Error('등록된 지식 자산이 없습니다.')
    if (/^\/knowledge\/graphs\/[^/]+\/releases(\/[^/]+\/snapshot)?$/.test(path)) throw new Error('등록된 지식 그래프 릴리스가 없습니다.')
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
    if (path === '/governance/documents') return { items: [], page: { next_cursor: null, limit: Number(url.searchParams.get('limit') ?? 100) }, cache_scope: POC_CACHE_SCOPE, ...authorizationWindow() }
    if (path === '/admin/profile-role-policy') return { policy_version: 'PROFILE_ROLE_POLICY_V1', items: [{ tier: 'ENGINEER_STEWARD', label: 'Engineer / Steward', description: '담당 System 범위의 등록·수정·검토', allowed_actions: ['change.read', 'change.create', 'change.edit', 'change.review'], services: [{ service_key: 'change', service_label: '변경관리', action_labels: ['조회', '등록', '수정', '검토'] }], assignable_to_system: true, lifecycle_note: '취소·이력 보존' }] }
    if (path === '/admin/system-configuration') return {
      items: systemConfigurationItems(),
      deployment_environment: {
        environment_file: 'deploy/poc/.env',
        operator_profile: 'unmanaged',
        apply_method: 'UNAVAILABLE',
        apply_command: null,
        browser_execution_supported: false,
      },
    }
    const systemConfigurationTest = path.match(/^\/admin\/system-configuration\/([^/]+)\/test-deployment$/)
    if (systemConfigurationTest && method === 'POST') {
      return testSystemConfiguration(decodeURIComponent(systemConfigurationTest[1] ?? ''), options.signal)
    }
    if (path === '/admin/workspace-memberships' && method === 'GET') {
      const query = (url.searchParams.get('q') ?? '').trim().toLocaleLowerCase()
      const status = url.searchParams.get('status')
      const limit = Number(url.searchParams.get('limit') ?? 25)
      const items = adminMemberships.filter((member) => {
        const matches = !query || [member.display_name, member.email, member.job_function]
          .filter(Boolean).join(' ').toLocaleLowerCase().includes(query)
        const active = member.subject_active && member.membership_active && !member.access_expired
        return matches && (!status || (status === 'ACTIVE' ? active : !active))
      }).slice(0, limit)
      return { items, page: { next_cursor: null, limit } }
    }
    if (path === '/admin/identity-users' && method === 'POST') {
      const body = jsonBody(options)
      const subjectId = nextId('user')
      const firstName = responseString(body.first_name, '')
      const lastName = responseString(body.last_name, '')
      const displayName = `${firstName} ${lastName}`.trim() || responseString(body.username, 'POC User')
      const member: WorkspaceMembershipSummary = {
        ...pocAdminMembership(),
        subject_id: subjectId,
        display_name: displayName,
        email: responseString(body.email, ''),
        owned_table_count: 0,
        change_request_count: 0,
        joined_at: new Date().toISOString(),
        department_id: responseString(body.department_id, '') || null,
        job_function: responseString(body.job_function, '') || null,
        effective_profile_role: 'VIEWER',
      }
      adminMemberships = [...adminMemberships, member]
      return {
        subject_id: subjectId,
        username: responseString(body.username, 'poc.user'),
        display_name: displayName,
        email: member.email,
        workspace_id: POC_WORKSPACE_ID,
        role_id: null,
        access_expires_at: new Date(Date.now() + 180 * 24 * 60 * 60 * 1000).toISOString(),
        temporary_password_required: true,
      }
    }
    const memberAccess = path.match(/^\/admin\/workspace-memberships\/([^/]+)\/access$/)
    if (memberAccess && method === 'GET') {
      const member = adminMemberships.find((item) => item.subject_id === decodeURIComponent(memberAccess[1] ?? ''))
      if (!member) throw new Error('POC 사용자를 찾을 수 없습니다.')
      return {
        subject_id: member.subject_id,
        display_name: member.display_name,
        subject_active: member.subject_active,
        department_id: member.department_id,
        job_function: member.job_function,
        membership_version: member.membership_version,
        access: { active: member.membership_active, clearance: member.clearance, groups: [], allowed_actions: [], denied_actions: [], allowed_system_ids: [], allowed_domain_ids: [] },
        role_assignment: { status: 'MANUAL', role_id: null, role_version: null, assignment_version: null, membership_version: member.membership_version, access_payload_hash: null, assigned_by: POC_SUBJECT_ID, updated_at: POC_NOW, legacy_markers: ['POC_BROWSER_MEMORY'] },
        canonical_admin_binding: { status: member.subject_id === POC_SUBJECT_ID ? 'VERIFIED' : 'NONE', role_version: null, catalog_version: 'POC_V1', membership_version: member.membership_version, binding_version: 1, updated_at: POC_NOW },
        profile_role: { status: 'VERIFIED', tier: member.effective_profile_role === 'UNASSIGNED' || member.effective_profile_role === 'STALE' || member.effective_profile_role === 'REVOKED' ? 'VIEWER' : member.effective_profile_role, policy_version: 'PROFILE_ROLE_POLICY_V1', membership_version: member.membership_version, assignment_version: 1, updated_at: POC_NOW },
      }
    }
    if (/^\/admin\/workspace-memberships\/[^/]+\/(change-requests|owned-tables)$/.test(path)) {
      const limit = Number(url.searchParams.get('limit') ?? 25)
      return { items: [], page: { next_cursor: null, limit } }
    }

    if (path === '/chat/sessions') return chatSessions.map((item) => ({ ...item }))
    const messageMatch = path.match(/^\/chat\/sessions\/([^/]+)\/messages$/)
    if (messageMatch) return (chatMessages.get(messageMatch[1] ?? '') ?? []).map((item) => ({ ...item }))
    const favoriteMatch = path.match(/^\/chat\/sessions\/([^/]+)\/favorite$/)
    if (favoriteMatch && method === 'PATCH') {
      const session = chatSessions.find((item) => item.id === favoriteMatch[1])
      if (!session) throw new Error('Chat 세션을 찾을 수 없습니다.')
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
      subject_id: POC_SUBJECT_ID, display_name: 'POC User', email: 'poc.user@local',
      last_login_at: null, last_login_ip: null, owned_table_count: 0, change_request_count: changeRecords.length,
      joined_at: POC_NOW, access_expires_at: null, renewal_eligible_at: null, access_expired: false,
      renewal_request_eligible: false, pending_renewal_request_id: null, subject_active: true,
      membership_active: true, department_id: null, job_function: 'POC', clearance: 'INTERNAL',
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
  changeRecords = []
  chatSessions = []
  uploadRecords = []
  manualSubmissionReports = []
  adminMemberships = [pocAdminMembership()]
  chatMessages.clear()
  changeAttachmentUploads.clear()
  changeAttachments.clear()
  liveAssetDetails.clear()
}
