import type {
  ApiClient,
  ApiDownload,
  ApiEventStreamHandler,
  ApiResponse,
} from '../api/client'
import { sha256 } from 'hash-wasm'
import type {
  AdminOperation,
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
  ChatResponse,
  ChatSession,
  CapabilitiesResponse,
  ClassificationPolicySummary,
  MonitoringConfiguration,
  SystemConfigurationEntry,
  SystemConfigurationTestResult,
  WorkspaceMembershipSummary,
} from '../api/types'
import type {
  GovernanceDocumentAttachment,
  GovernanceDocumentReview,
  GovernanceDocumentSummary,
  GovernanceDocumentVersion,
} from '../features/governance-documents/types'
import {
  governanceMarkupFromFile,
  sanitizeGovernanceHtml,
} from '../features/governance-documents/governanceDocumentMarkup'
import {
  POC_CACHE_SCOPE,
  POC_NOW,
  POC_SUBJECT_ID,
  POC_WORKSPACE_ID,
  authorizationWindow,
  catalogMeta,
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
  pocState?: boolean
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

function responseAssetKind(value: unknown): 'TABLE' | 'VIEW' | 'MATERIALIZED_VIEW' | 'CATALOG' {
  return value === 'VIEW' || value === 'MATERIALIZED_VIEW' || value === 'CATALOG' ? value : 'TABLE'
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

async function gatewayEventStream<T>(
  path: string,
  options: RequestInit,
  onEvent: ApiEventStreamHandler,
): Promise<T> {
  const headers = new Headers(options.headers)
  headers.set('Accept', 'text/event-stream')
  headers.set('Content-Type', 'application/json')
  const response = await fetch(path, { ...options, cache: 'no-store', headers })
  if (!response.ok) {
    const problem = await response.json().catch(() => ({})) as { detail?: unknown }
    throw new Error(typeof problem.detail === 'string'
      ? problem.detail
      : `POC provider gateway stream failed (${response.status}).`)
  }
  if (!response.body) throw new Error('POC Chat 진행 상태 스트림을 열지 못했습니다.')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let receivedBytes = 0
  let result: T | undefined
  let receivedResult = false
  const parseFrame = (frame: string) => {
    let event = 'message'
    const data: string[] = []
    for (const line of frame.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
    }
    if (!data.length) return
    const parsed = JSON.parse(data.join('\n')) as unknown
    if (event === 'error') {
      const detail = parsed && typeof parsed === 'object'
        ? (parsed as { detail?: unknown }).detail
        : undefined
      throw new Error(typeof detail === 'string' ? detail : 'POC Chat provider request failed.')
    }
    if (event === 'result') {
      result = parsed as T
      receivedResult = true
      return
    }
    onEvent({ event, data: parsed })
  }
  try {
    while (!receivedResult) {
      const { done, value } = await reader.read()
      receivedBytes += value?.byteLength ?? 0
      if (receivedBytes > 8 * 1024 * 1024) throw new Error('POC Chat 스트림 크기 제한을 초과했습니다.')
      buffer += decoder.decode(value, { stream: !done }).replace(/\r\n?/g, '\n')
      const frames = buffer.split('\n\n')
      buffer = done ? '' : (frames.pop() ?? '')
      for (const frame of frames) {
        if (frame.trim()) parseFrame(frame)
        if (receivedResult) break
      }
      if (done && !receivedResult) throw new Error('POC Chat 서버가 최종 결과를 반환하지 않았습니다.')
    }
  } finally {
    if (!receivedResult) await reader.cancel().catch(() => undefined)
    reader.releaseLock()
  }
  return result as T
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

const pocAdminOperations: AdminOperation[] = [
  'IDENTITY_USER_PROVISION', 'IDENTITY_USER_PROFILE_READ', 'IDENTITY_USER_PROFILE_UPDATE',
  'MEMBERSHIP_ACCESS_READ', 'MEMBERSHIP_ACCESS_UPDATE',
  'MEMBERSHIP_RENEWAL_READ', 'MEMBERSHIP_RENEWAL_DECIDE', 'SYSTEM_ASSIGNMENT_UPDATE',
  'SYSTEM_CONFIGURATION_READ', 'SYSTEM_CONFIGURATION_UPDATE', 'SYSTEM_CONFIGURATION_ACTIVATE',
  'MONITORING_CONFIGURATION_READ', 'MONITORING_CONFIGURATION_UPDATE',
  'FALLBACK_REQUEST_READ', 'FALLBACK_REQUEST_CREATE', 'FALLBACK_REQUEST_DECIDE',
  'FALLBACK_REQUEST_CONSUME', 'CLASSIFICATION_POLICY_READ', 'CLASSIFICATION_POLICY_PROPOSE',
  'CLASSIFICATION_POLICY_DECIDE', 'INFERENCE_PROVIDER_PROFILE_READ',
  'INFERENCE_PROVIDER_PROFILE_DECIDE', 'INFERENCE_PROVIDER_PROFILE_REVOKE',
  'RESTRICTED_SEARCH_GRANT_READ', 'RESTRICTED_SEARCH_GRANT_PROPOSE',
  'RESTRICTED_SEARCH_GRANT_DECIDE', 'RESTRICTED_SEARCH_GRANT_REVOKE',
  'RETENTION_POLICY_READ', 'RETENTION_POLICY_MANAGE', 'LEGAL_HOLD_READ', 'LEGAL_HOLD_PLACE',
  'LEGAL_HOLD_RELEASE', 'ERASURE_READ', 'ERASURE_REQUEST', 'ERASURE_APPROVE',
]

const pocClassificationPolicySummary: ClassificationPolicySummary = {
  state: 'STATIC_FLOOR',
  rules: [
    { classification: 'PUBLIC', search_mode: 'ABAC', chat_mode: 'INTERNAL_APPROVED_ONLY' },
    { classification: 'INTERNAL', search_mode: 'ABAC', chat_mode: 'INTERNAL_APPROVED_ONLY' },
    { classification: 'CONFIDENTIAL', search_mode: 'ABAC', chat_mode: 'DENY' },
    { classification: 'RESTRICTED', search_mode: 'DENY', chat_mode: 'DENY' },
  ],
}

let sequence = 900
let changeRecords: ChangeRequestRecord[] = []
let chatSessions: ChatSession[] = []
let uploadRecords: Array<Record<string, unknown>> = []
let manualSubmissionReports: Array<Record<string, unknown>> = []
let monitoringConfiguration: MonitoringConfiguration | undefined
let adminMemberships: WorkspaceMembershipSummary[] = [pocAdminMembership()]
let adminSystems: Array<{
  system_id: string
  code: string
  name: string
  description: string
  active: boolean
  version: number
}> = []
const adminSystemAssignees = new Map<string, Array<{
  subject_id: string
  display_name: string
  responsibility: 'DEVELOPER' | 'DATA_STEWARD'
  priority: number
  active: boolean
}>>()
const adminSystemSchemaScopes = new Map<string, Array<{
  scope_id: string
  system_id: string
  platform: string
  database_name: string
  schema_name: string
  active: boolean
  version: number
}>>()
let knowledgeDomains: Array<Record<string, unknown>> = []
let knowledgeDrafts: Array<Record<string, unknown>> = []
let knowledgeReleases: Array<Record<string, unknown>> = []
const knowledgeDraftBlocks = new Map<string, Array<Record<string, unknown>>>()
const knowledgeDraftBindings = new Map<string, Array<Record<string, unknown>>>()
let governanceDocuments: GovernanceDocumentSummary[] = []
let governanceVersions: GovernanceDocumentVersion[] = []
let governanceReviews: GovernanceDocumentReview[] = []
let governanceAttachments: GovernanceDocumentAttachment[] = []
const governanceAttachmentLocations = new Map<string, { upload_id: string; key: string }>()
const chatMessages = new Map<string, ChatMessage[]>()
const CHAT_QUESTION_MAX_CHARACTERS = 12_000
const CHAT_MEMORY_COMPACTION_INTERVAL = 5
const CHAT_MEMORY_SUMMARY_CHARACTERS = 5_000
const CHAT_MEMORY_TURN_QUESTION_CHARACTERS = 900
const CHAT_MEMORY_TURN_ANSWER_CHARACTERS = 1_300
interface PocChatMemoryTurn { question: string; answer: string }
interface PocChatMemoryState {
  summary: string
  compactedTurnCount: number
  recentTurns: PocChatMemoryTurn[]
  compaction?: Promise<void>
}
const chatMemory = new Map<string, PocChatMemoryState>()
const changeAttachmentUploads = new Map<string, ChangeRequestAttachmentUpload & { file: File }>()
const changeAttachments = new Map<string, Array<ChangeRequestAttachment & { file?: File }>>()
const changeAttachmentLocations = new Map<string, { upload_id: string; display_name: string }>()
const liveAssetDetails = new Map<string, CatalogAssetDetail>()
const bulkCandidatePreviews = new Map<string, Record<string, unknown>>()

function pocSystemEntry(system: typeof adminSystems[number]) {
  const assignees = adminSystemAssignees.get(system.system_id) ?? []
  return { ...system, assignee_count: assignees.length, assignees }
}

function knowledgeDraftById(id: string): Record<string, unknown> {
  const draft = knowledgeDrafts.find((item) => item.id === id)
  if (!draft) throw new Error('POC Knowledge Studio Draft를 찾을 수 없습니다.')
  return draft
}

function knowledgeTBox(draftId: string) {
  return { draft: knowledgeDraftById(draftId), blocks: knowledgeDraftBlocks.get(draftId) ?? [] }
}

function knowledgeAssetSummary(draft: Record<string, unknown>, release: Record<string, unknown>) {
  const blocks = knowledgeDraftBlocks.get(String(draft.id)) ?? []
  const elements = blocks.flatMap((block) => Array.isArray(block.elements) ? block.elements as Array<Record<string, unknown>> : [])
  return {
    id: draft.materialized_graph_id,
    slug: draft.endpoint_alias,
    name: draft.name,
    graph_type: 'CURATED_KNOWLEDGE',
    status: 'ACTIVE',
    classification: draft.classification,
    domain_id: draft.domain_id,
    domain_name: knowledgeDomains.find((domain) => domain.id === draft.domain_id)?.display_name ?? null,
    creator_name: 'POC User', creator_email: 'poc.user@local',
    editor_name: 'POC User', editor_email: 'poc.user@local',
    active_studio_release_id: release.id, active_studio_release_no: release.release_no,
    active_release_id: null, active_release_no: null,
    class_count: elements.filter((item) => item.kind === 'CLASS').length,
    property_count: elements.filter((item) => item.kind === 'PROPERTY').length,
    relationship_count: elements.filter((item) => item.kind === 'RELATION').length,
    binding_count: 0, source_count: 0, node_count: 0, edge_count: 0,
    projection_state: null,
    created_at: draft.created_at,
    updated_at: draft.updated_at,
    version: draft.version,
    delivery_policy: null,
  }
}

function governanceActions(document: GovernanceDocumentSummary) {
  if (document.state === 'ARCHIVED') return ['read', 'download_attachment'] satisfies GovernanceDocumentSummary['allowed_actions']
  const actions: GovernanceDocumentSummary['allowed_actions'] = [
    'read', 'create_version', 'submit', 'review', 'publish', 'archive',
    'add_attachment', 'download_attachment',
  ]
  if (document.kind === 'TEMPLATE') actions.push('instantiate_template')
  return actions
}

function governanceDetail(documentId: string) {
  const document = governanceDocuments.find((item) => item.document_id === documentId)
  if (!document) throw new Error('POC 거버넌스 문서를 찾을 수 없습니다.')
  document.allowed_actions = [...governanceActions(document)]
  return {
    document,
    versions: governanceVersions
      .filter((item) => item.document_id === documentId)
      .sort((left, right) => right.version_number - left.version_number),
    reviews: governanceReviews.filter((item) => item.document_id === documentId),
    attachments: governanceAttachments.filter((item) => item.document_id === documentId),
    parent_document: document.current_published_version_id
      ? (() => {
          const version = governanceVersions.find((item) => item.version_id === document.current_published_version_id)
          return version?.parent_document_id
            ? governanceDocuments.find((item) => item.document_id === version.parent_document_id) ?? null
            : null
        })()
      : null,
    child_documents: governanceDocuments.filter((candidate) => governanceVersions.some((version) => (
      version.document_id === candidate.document_id && version.parent_document_id === documentId
    ))),
  }
}

function governancePlainText(html: string): string {
  return html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()
}

async function governanceVersion(
  document: GovernanceDocumentSummary,
  input: {
    title: string
    summary: string
    applicability_scope: string
    sanitized_html: string
    source_template_version_id: string | null
    parent_document_id: string | null
    source_format?: 'HTML' | 'MARKDOWN' | 'DOCX'
  },
): Promise<GovernanceDocumentVersion> {
  const now = new Date().toISOString()
  const versionNumber = governanceVersions.filter((item) => item.document_id === document.document_id).length + 1
  const sanitizedHtml = sanitizeGovernanceHtml(input.sanitized_html)
  const contentHash = await sha256(sanitizedHtml)
  return {
    version_id: crypto.randomUUID(), workspace_id: POC_WORKSPACE_ID,
    document_id: document.document_id, version_number: versionNumber,
    version_tag: `v${versionNumber}`, state: 'DRAFT', title: input.title,
    summary: input.summary, applicability_scope: input.applicability_scope,
    sanitized_html: sanitizedHtml, plain_text: governancePlainText(sanitizedHtml),
    content_sha256: contentHash, size_bytes: new TextEncoder().encode(sanitizedHtml).byteLength,
    sanitizer_policy_version: 'POC_SANITIZER_V1', sanitizer_policy_sha256: 'c'.repeat(64),
    source_format: input.source_format ?? 'HTML', source_template_version_id: input.source_template_version_id,
    parent_document_id: input.parent_document_id, author_id: POC_SUBJECT_ID,
    submitted_at: null, reviewed_by: null, reviewed_at: null, published_at: null,
    artifact_state: 'STORED', knowledge_state: 'PENDING', created_at: now, version: 1,
  }
}

async function governanceImportedMarkup(file: File): Promise<{
  html: string
  sourceFormat: 'HTML' | 'MARKDOWN' | 'DOCX'
}> {
  const name = file.name.toLocaleLowerCase()
  if (!name.endsWith('.docx')) {
    const imported = await governanceMarkupFromFile(file)
    return { html: imported.html, sourceFormat: imported.format }
  }
  const source = await file.text()
  const escaped = source.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  return { html: `<pre>${escaped}</pre>`, sourceFormat: 'DOCX' }
}

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

function normalizePocChangeRecord(record: ChangeRequestRecord): ChangeRequestRecord {
  // Older persisted POC records may predate editable revision rounds. The
  // authentication-free POC keeps CHANGE_INTAKE revisions open after a
  // recoverable changes request; terminal REJECTED/CANCELLED records stay closed.
  if (record.request_type === 'CHANGE_INTAKE' && record.state === 'CHANGES_REQUESTED') {
    record.revision_allowed = true
  }
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
  if (!runtimeFlags().minio) throw new Error('변경요청 첨부파일에는 MinIO 설정이 필요합니다.')
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

function boundedChatMemoryTurn(question: string, answer: string): PocChatMemoryTurn {
  return {
    question: question.slice(0, CHAT_MEMORY_TURN_QUESTION_CHARACTERS),
    answer: answer.slice(0, CHAT_MEMORY_TURN_ANSWER_CHARACTERS),
  }
}

function chatMemoryRequest(sessionId: string): Record<string, unknown> | undefined {
  const state = chatMemory.get(sessionId)
  if (!state || (!state.summary && !state.recentTurns.length)) return undefined
  return {
    summary: state.summary,
    compacted_turn_count: state.compactedTurnCount,
    recent_turns: state.recentTurns.slice(-CHAT_MEMORY_COMPACTION_INTERVAL),
  }
}

function deterministicChatMemorySummary(previous: string, turns: PocChatMemoryTurn[]): string {
  const turnText = turns.map((turn, index) => (
    `${index + 1}. 질문: ${turn.question}\n답변 요지: ${turn.answer}`
  )).join('\n')
  return [previous ? `이전 요약:\n${previous}` : '', turnText]
    .filter(Boolean)
    .join('\n\n')
    .slice(-CHAT_MEMORY_SUMMARY_CHARACTERS)
}

function scheduleChatMemoryCompaction(sessionId: string, state: PocChatMemoryState): void {
  if (state.compaction || state.recentTurns.length < CHAT_MEMORY_COMPACTION_INTERVAL) return
  const turns = state.recentTurns.slice(0, CHAT_MEMORY_COMPACTION_INTERVAL)
  const previousSummary = state.summary
  const previousCompactedTurnCount = state.compactedTurnCount
  state.compaction = gatewayRequest<{ summary: string; compacted_turn_count: number }>(
    '/poc-api/llm/chat/compact',
    {
      method: 'POST',
      body: JSON.stringify({
        memory: {
          summary: previousSummary,
          compacted_turn_count: previousCompactedTurnCount,
          recent_turns: turns,
        },
      }),
    },
  ).then((result) => {
    if (chatMemory.get(sessionId) !== state) return
    state.summary = result.summary.slice(0, CHAT_MEMORY_SUMMARY_CHARACTERS)
    state.compactedTurnCount = result.compacted_turn_count
    state.recentTurns.splice(0, CHAT_MEMORY_COMPACTION_INTERVAL)
  }).catch(() => {
    if (chatMemory.get(sessionId) !== state) return
    state.summary = deterministicChatMemorySummary(previousSummary, turns)
    state.compactedTurnCount = previousCompactedTurnCount + turns.length
    state.recentTurns.splice(0, CHAT_MEMORY_COMPACTION_INTERVAL)
  }).finally(() => {
    if (chatMemory.get(sessionId) !== state) return
    state.compaction = undefined
    scheduleChatMemoryCompaction(sessionId, state)
  })
}

function rememberChatTurn(sessionId: string, question: string, answer: string): void {
  const state = chatMemory.get(sessionId) ?? {
    summary: '',
    compactedTurnCount: 0,
    recentTurns: [],
  }
  if (!chatMemory.has(sessionId)) chatMemory.set(sessionId, state)
  state.recentTurns.push(boundedChatMemoryTurn(question, answer))
  scheduleChatMemoryCompaction(sessionId, state)
}

class PocApiClient {
  private hydration?: Promise<void>

  private ensureHydrated(): Promise<void> {
    if (this.hydration) return this.hydration
    this.hydration = gatewayRequest<{ value: Record<string, unknown> | null }>('/poc-api/state/core')
      .then(({ value }) => {
        if (!value) return
        if (Number.isSafeInteger(value.sequence)) sequence = Number(value.sequence)
        if (Array.isArray(value.changeRecords)) {
          changeRecords = (value.changeRecords as ChangeRequestRecord[]).map(normalizePocChangeRecord)
        }
        if (Array.isArray(value.changeAttachments)) {
          changeAttachments.clear()
          for (const entry of value.changeAttachments) {
            if (Array.isArray(entry) && typeof entry[0] === 'string' && Array.isArray(entry[1])) {
              changeAttachments.set(entry[0], entry[1] as ChangeRequestAttachment[])
            }
          }
        }
        if (Array.isArray(value.changeAttachmentLocations)) {
          changeAttachmentLocations.clear()
          for (const entry of value.changeAttachmentLocations) {
            if (Array.isArray(entry) && typeof entry[0] === 'string' && entry[1] && typeof entry[1] === 'object') {
              changeAttachmentLocations.set(entry[0], entry[1] as { upload_id: string; display_name: string })
            }
          }
        }
        if (Array.isArray(value.uploadRecords)) uploadRecords = value.uploadRecords as Array<Record<string, unknown>>
        if (Array.isArray(value.manualSubmissionReports)) manualSubmissionReports = value.manualSubmissionReports as Array<Record<string, unknown>>
        if (value.monitoringConfiguration && typeof value.monitoringConfiguration === 'object') {
          monitoringConfiguration = value.monitoringConfiguration as MonitoringConfiguration
        }
        if (Array.isArray(value.adminMemberships)) adminMemberships = value.adminMemberships as WorkspaceMembershipSummary[]
        if (Array.isArray(value.adminSystems)) adminSystems = value.adminSystems as typeof adminSystems
        if (Array.isArray(value.knowledgeDomains)) knowledgeDomains = value.knowledgeDomains as Array<Record<string, unknown>>
        if (Array.isArray(value.knowledgeDrafts)) knowledgeDrafts = value.knowledgeDrafts as Array<Record<string, unknown>>
        if (Array.isArray(value.knowledgeReleases)) knowledgeReleases = value.knowledgeReleases as Array<Record<string, unknown>>
        if (Array.isArray(value.governanceDocuments)) governanceDocuments = value.governanceDocuments as GovernanceDocumentSummary[]
        if (Array.isArray(value.governanceVersions)) governanceVersions = value.governanceVersions as GovernanceDocumentVersion[]
        if (Array.isArray(value.governanceReviews)) governanceReviews = value.governanceReviews as GovernanceDocumentReview[]
        if (Array.isArray(value.governanceAttachments)) governanceAttachments = value.governanceAttachments as GovernanceDocumentAttachment[]
        if (Array.isArray(value.knowledgeDraftBlocks)) {
          knowledgeDraftBlocks.clear()
          for (const entry of value.knowledgeDraftBlocks) {
            if (Array.isArray(entry) && typeof entry[0] === 'string' && Array.isArray(entry[1])) {
              knowledgeDraftBlocks.set(entry[0], entry[1] as Array<Record<string, unknown>>)
            }
          }
        }
        if (Array.isArray(value.knowledgeDraftBindings)) {
          knowledgeDraftBindings.clear()
          for (const entry of value.knowledgeDraftBindings) {
            if (Array.isArray(entry) && typeof entry[0] === 'string' && Array.isArray(entry[1])) {
              knowledgeDraftBindings.set(entry[0], entry[1] as Array<Record<string, unknown>>)
            }
          }
        }
        if (Array.isArray(value.adminSystemAssignees)) {
          adminSystemAssignees.clear()
          for (const entry of value.adminSystemAssignees) {
            if (Array.isArray(entry) && typeof entry[0] === 'string' && Array.isArray(entry[1])) {
              adminSystemAssignees.set(entry[0], entry[1] as Parameters<typeof adminSystemAssignees.set>[1])
            }
          }
        }
        if (Array.isArray(value.adminSystemSchemaScopes)) {
          adminSystemSchemaScopes.clear()
          for (const entry of value.adminSystemSchemaScopes) {
            if (Array.isArray(entry) && typeof entry[0] === 'string' && Array.isArray(entry[1])) {
              adminSystemSchemaScopes.set(entry[0], entry[1] as Parameters<typeof adminSystemSchemaScopes.set>[1])
            }
          }
        }
        if (Array.isArray(value.governanceAttachmentLocations)) {
          governanceAttachmentLocations.clear()
          for (const entry of value.governanceAttachmentLocations) {
            if (Array.isArray(entry) && typeof entry[0] === 'string' && entry[1] && typeof entry[1] === 'object') {
              governanceAttachmentLocations.set(entry[0], entry[1] as { upload_id: string; key: string })
            }
          }
        }
      })
    return this.hydration
  }

  private async persistCore(): Promise<void> {
    if (!runtimeFlags().pocState) return
    await gatewayRequest('/poc-api/state/core', {
      method: 'PUT',
      body: JSON.stringify({
        value: {
          sequence,
          changeRecords,
          changeAttachments: [...changeAttachments.entries()].map(([recordId, items]) => [
            recordId,
            items.map(({ file: _file, ...item }) => { void _file; return item }),
          ]),
          changeAttachmentLocations: [...changeAttachmentLocations.entries()],
          uploadRecords,
          manualSubmissionReports,
          monitoringConfiguration,
          adminMemberships,
          adminSystems,
          adminSystemAssignees: [...adminSystemAssignees.entries()],
          adminSystemSchemaScopes: [...adminSystemSchemaScopes.entries()],
          knowledgeDomains,
          knowledgeDrafts,
          knowledgeReleases,
          knowledgeDraftBlocks: [...knowledgeDraftBlocks.entries()],
          knowledgeDraftBindings: [...knowledgeDraftBindings.entries()],
          governanceDocuments,
          governanceVersions,
          governanceReviews,
          governanceAttachments,
          governanceAttachmentLocations: [...governanceAttachmentLocations.entries()],
        },
      }),
    })
  }

  async request<T>(path: string, options: PocRequestOptions = {}): Promise<T> {
    return (await this.requestWithMeta<T>(path, options)).data
  }

  async requestWithMeta<T>(path: string, options: PocRequestOptions = {}): Promise<ApiResponse<T>> {
    if (options.signal?.aborted) throw new DOMException('The operation was aborted.', 'AbortError')
    if (runtimeFlags().pocState) await this.ensureHydrated()
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
    const rawQuestion = typeof body.question === 'string' ? body.question : ''
    if (rawQuestion.length > CHAT_QUESTION_MAX_CHARACTERS) {
      return Promise.reject(new Error(`질문은 ${CHAT_QUESTION_MAX_CHARACTERS.toLocaleString()}자까지 입력할 수 있습니다.`))
    }
    const question = rawQuestion.trim()
    if (!question) return Promise.reject(new Error('질문을 입력하세요.'))
    const mode = ['AUTO', 'GENERAL', 'VECTOR', 'GRAPH'].includes(String(body.mode))
      ? body.mode as ChatMode
      : 'AUTO'
    const sessionId = typeof body.session_id === 'string' && body.session_id
      ? body.session_id
      : nextId('chat-session')
    const memory = chatMemoryRequest(sessionId)
    const live = runtimeFlags().llmChat
      ? gatewayEventStream<Pick<ChatResponse, 'answer' | 'route' | 'workflow'> & { evidence: Array<Record<string, unknown>> }>('/poc-api/llm/chat/stream', {
          method: 'POST',
          signal: options.signal,
          body: JSON.stringify({ question, mode, ...(memory ? { memory } : {}) }),
        }, onEvent)
      : Promise.reject(new Error('검증 불가: LLM Chat 연결을 설정해야 합니다.'))
    return live.then(async (liveResult) => {
      const workflow = liveResult.workflow
      const requestId = nextId('chat-request')
      const responseId = nextId('chat-response')
      const route = liveResult.route ?? chatRoute(mode)
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
          system_id: responseString(item.platform, '') || null,
          domain_id: responseString(item.domain, '') || null,
          owner_department_id: null,
          name: responseString(item.name, 'DataHub asset'),
          asset_kind: responseAssetKind(item.dataset_kind),
          description: responseString(item.provider_description ?? item.description, '') || null,
          source_type: responseString(item.evidence_type, 'CATALOG_ASSET'),
          source_locator: responseString(item.external_urn ?? item.id, ''),
          source_version: responseString(item.source_version, 'datahub-live'),
          content_hash: await sha256(JSON.stringify(item)),
          effective_from: new Date().toISOString(),
          effective_until: null,
          extraction_method: responseString(item.extraction_method, 'DATAHUB_GMS'),
          rank: index + 1,
          retrieval_method: responseString(
            item.retrieval_method,
            runtimeFlags().llmReranker ? 'RERANKED' : 'DATAHUB_SEARCH',
          ),
        }
      }))
      const messages = chatMessages.get(sessionId) ?? []
      messages.push({ id: requestId, session_id: sessionId, role: 'user', content: question, evidence_json: null, created_at: new Date().toISOString(), route: null, workflow: [] })
      messages.push({ id: responseId, session_id: sessionId, role: 'assistant', content: liveResult.answer, evidence_json: evidence, created_at: new Date().toISOString(), route, workflow })
      chatMessages.set(sessionId, messages)
      rememberChatTurn(sessionId, question, liveResult.answer)
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
    const templateProfile = path.match(/^\/uploads\/profiles\/(CATALOG_METADATA_ROWS_(?:CSV|XLSX)_V1)\/template$/)
    if (templateProfile) {
      const extension = templateProfile[1]?.includes('XLSX') ? 'xlsx' : 'csv'
      return fetch(`/poc-api/templates/catalog-metadata.${extension}`, { cache: 'no-store' }).then(async (response) => {
        if (!response.ok) throw new Error(`Excel 템플릿을 내려받지 못했습니다. (${response.status})`)
        return {
          blob: await response.blob(),
          filename: `datariver-catalog-metadata-rows.${extension}`,
          etag: response.headers.get('ETag') ?? undefined,
        }
      })
    }
    return Promise.reject(new Error('이 POC에서 생성된 다운로드 산출물이 없습니다.'))
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
      allowed_operations: pocAdminOperations,
      action_vocabulary: [
        'POC_OPEN_ACCESS_V1', 'catalog.read', 'registration.create', 'change.create',
        'change.edit', 'change.review', 'change.approve', 'quality.read', 'quality.execute', 'kg.read',
        'kg.edit', 'governance.read', 'governance.edit', 'chat.query', 'admin.manage',
      ],
    }
    if (path === '/admin/classification-access/policies/current/summary' && method === 'GET') {
      return structuredClone(pocClassificationPolicySummary)
    }
    if (path === '/admin/classification-access/policies/current' && method === 'GET') return null
    if (path === '/admin/classification-access/policies' && method === 'GET') {
      return { items: [], page: { next_cursor: null, limit: Number(url.searchParams.get('limit') ?? 25) } }
    }
    if (path === '/admin/inference/provider-profiles' && method === 'GET') {
      return { items: [], page: { next_cursor: null, limit: Number(url.searchParams.get('limit') ?? 25) } }
    }
    if (path === '/admin/classification-access/restricted-search-grants' && method === 'GET') {
      return { items: [], page: { next_cursor: null, limit: Number(url.searchParams.get('limit') ?? 25) } }
    }
    if (path === '/capabilities') {
      const providerCapabilities = runtimeFlags().datahub || runtimeFlags().airflow || runtimeFlags().minio
        || runtimeFlags().llmChat || runtimeFlags().neo4j
        ? await gatewayRequest<CapabilitiesResponse>('/poc-api/capabilities', { signal: options.signal })
        : capabilities
      return monitoringConfiguration
        ? { ...providerCapabilities, monitoring_configuration: monitoringConfiguration }
        : providerCapabilities
    }
    if (path === '/admin/monitoring-configuration' && method === 'PUT') {
      const body = jsonBody(options)
      const items = Array.isArray(body.items) ? body.items : []
      if (items.length > 8) throw new Error('Monitoring 탭은 최대 8개까지 설정할 수 있습니다.')
      const deployed = await gatewayRequest<CapabilitiesResponse>('/poc-api/capabilities', { signal: options.signal })
      const approvedOrigins = new Set(deployed.monitoring_configuration.items.map((item) => new URL(item.url).origin))
      const embeddableOrigins = new Set(deployed.monitoring_configuration.items
        .filter((item) => item.embed_state === 'AVAILABLE')
        .map((item) => new URL(item.url).origin))
      const ids = new Set<string>()
      const normalized = items.map((item, index) => {
        if (!item || typeof item !== 'object' || Array.isArray(item)) throw new Error(`Monitoring 탭 ${index + 1} 형식이 올바르지 않습니다.`)
        const draft = item as Record<string, unknown>
        const id = responseString(draft.id, '').trim()
        const label = responseString(draft.label, '').trim()
        const rawUrl = responseString(draft.url, '').trim()
        let url: URL
        try { url = new URL(rawUrl) } catch { throw new Error(`Monitoring 탭 ${index + 1} URL이 올바르지 않습니다.`) }
        const height = Number(draft.height_px ?? 900)
        if (!/^[a-zA-Z][a-zA-Z0-9_-]{1,99}$/.test(id) || ids.has(id) || !label) {
          throw new Error(`Monitoring 탭 ${index + 1}의 id 또는 이름이 올바르지 않습니다.`)
        }
        if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.hash
          || !approvedOrigins.has(url.origin)) {
          throw new Error('새 Dashboard origin은 먼저 MONITORING_DASHBOARDS_JSON과 Grafana embed 환경변수로 승인해야 합니다.')
        }
        if (!Number.isInteger(height) || height < 480 || height > 2000) throw new Error('Monitoring 높이는 480~2000px이어야 합니다.')
        ids.add(id)
        const available = embeddableOrigins.has(url.origin)
        return {
          id, label, url: url.toString(), height_px: height,
          embed_state: available ? 'AVAILABLE' : 'DISABLED',
          ...(available ? { embed_url: url.toString() } : {}),
        }
      }) as MonitoringConfiguration['items']
      monitoringConfiguration = {
        items: normalized,
        version: (monitoringConfiguration?.version ?? deployed.monitoring_configuration.version) + 1,
      }
      await this.persistCore()
      return monitoringConfiguration
    }
    if (path === '/catalog/export-capability') return { enabled: false }
    if (path === '/poc/glossary/assignments') {
      return runtimeFlags().datahub
        ? gatewayRequest(`/poc-api/datahub/glossary/assignments?${url.searchParams.toString()}`, { signal: options.signal })
        : { items: [], total: 0, page: { next_cursor: null, limit: 25 } }
    }
    if (path === '/poc/glossary') {
      return runtimeFlags().datahub
        ? gatewayRequest(`/poc-api/datahub/glossary?${url.searchParams.toString()}`, { signal: options.signal })
        : { items: [] }
    }
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
      if (!runtimeFlags().minio) throw new Error('파일 업로드에는 MinIO 설정이 필요합니다.')
      const record = createUploadRecord(jsonBody(options), knowledgeUploadCollection ? 'KNOWLEDGE_SOURCE_DOCUMENT_V1' : undefined)
      await this.persistCore()
      return record
    }
    if (path === '/uploads' && method === 'GET') return { items: uploadRecords }
    const uploadPart = path.match(/^\/uploads\/([^/]+)\/parts$/)
      ?? path.match(/^\/knowledge\/graphs\/[^/]+\/source-uploads\/([^/]+)\/parts$/)
    if (uploadPart && method === 'POST') {
      if (!runtimeFlags().minio) throw new Error('파일 업로드에는 MinIO 설정이 필요합니다.')
      const partNumber = Number(jsonBody(options).part_number ?? 1)
      return { url: `/poc-api/minio/uploads/${encodeURIComponent(uploadPart[1] ?? '')}/parts/${partNumber}` }
    }
    const uploadComplete = path.match(/^\/uploads\/([^/]+)\/complete$/)
      ?? path.match(/^\/knowledge\/graphs\/[^/]+\/source-uploads\/([^/]+)\/complete$/)
    if (uploadComplete && method === 'POST') {
      if (!runtimeFlags().minio) throw new Error('파일 업로드 완료에는 MinIO 설정이 필요합니다.')
      const record = uploadById(uploadComplete[1] ?? '')
      if (!record) throw new Error('POC upload record was not found.')
      const parts = jsonBody(options).parts
      const stored = await gatewayRequest<{ bucket?: string; key?: string; sha256?: string }>(
        `/poc-api/minio/uploads/${encodeURIComponent(String(record.id))}/complete`,
        {
          method: 'POST',
          signal: options.signal,
          body: JSON.stringify({
            part_count: Array.isArray(parts) ? parts.length : 1,
            display_name: record.display_name,
            content_type: record.content_type,
            ...(['CATALOG_METADATA_ROWS_CSV_V1', 'CATALOG_METADATA_ROWS_XLSX_V1'].includes(String(record.content_profile))
              ? { target_bucket: 'filefolder' }
              : {}),
          }),
        },
      )
      Object.assign(record, {
        state: 'ACCEPTED',
        version: Number(record.version) + 2,
        validation_summary: {
          provider: 'MINIO_LIVE',
          status: 'PASS',
        },
        ...(stored?.bucket && stored.key ? {
          object_bucket: stored.bucket,
          object_key: stored.key,
          provider_sha256: stored.sha256,
        } : {}),
      })
      await this.persistCore()
      return { ...record }
    }
    const uploadDetail = path.match(/^\/uploads\/([^/]+)$/)
      ?? path.match(/^\/knowledge\/graphs\/[^/]+\/source-uploads\/([^/]+)$/)
    if (uploadDetail && method === 'GET') {
      const record = uploadById(uploadDetail[1] ?? '')
      if (!record) throw new Error('업로드를 찾을 수 없습니다.')
      return record
    }
    const preparationCollection = path.match(/^\/uploads\/([^/]+)\/preparations$/)
    if (preparationCollection && method === 'GET') {
      return gatewayRequest(
        `/poc-api/bulk/uploads/${encodeURIComponent(preparationCollection[1] ?? '')}/preparations`,
        { signal: options.signal },
      )
    }
    if (preparationCollection && method === 'POST') {
      const record = uploadById(preparationCollection[1] ?? '')
      if (!record || record.state !== 'ACCEPTED') throw new Error('검증·승격된 bulk 업로드가 필요합니다.')
      if (!record.object_key || !record.object_bucket) throw new Error('filefolder 저장 영수증이 없습니다.')
      return gatewayRequest('/poc-api/bulk/preparations', {
        method: 'POST',
        signal: options.signal,
        body: JSON.stringify({
          upload_id: record.id,
          content_profile: record.content_profile,
          source_sha256: record.sha256,
          object_bucket: record.object_bucket,
          object_key: record.object_key,
        }),
      })
    }
    const bulkCandidateCollection = path.match(/^\/uploads\/([^/]+)\/preparations\/([^/]+)\/metadata-candidates$/)
    if (bulkCandidateCollection && method === 'GET') {
      return gatewayRequest(
        `/poc-api/bulk/uploads/${encodeURIComponent(bulkCandidateCollection[1] ?? '')}/preparations/${encodeURIComponent(bulkCandidateCollection[2] ?? '')}/metadata-candidates?${url.searchParams.toString()}`,
        { signal: options.signal },
      )
    }
    const bulkCandidatePreviewPath = path.match(/^\/uploads\/([^/]+)\/preparations\/([^/]+)\/metadata-candidates\/([^/]+)\/preview$/)
    if (bulkCandidatePreviewPath && method === 'GET') {
      const preview = await gatewayRequest<Record<string, unknown>>(
        `/poc-api/bulk/uploads/${encodeURIComponent(bulkCandidatePreviewPath[1] ?? '')}/preparations/${encodeURIComponent(bulkCandidatePreviewPath[2] ?? '')}/metadata-candidates/${encodeURIComponent(bulkCandidatePreviewPath[3] ?? '')}/preview`,
        { signal: options.signal },
      )
      bulkCandidatePreviews.set(bulkCandidatePreviewPath[3] ?? '', preview)
      return preview
    }
    const bulkCandidateChangePath = path.match(/^\/uploads\/([^/]+)\/preparations\/([^/]+)\/metadata-candidates\/([^/]+)\/change-request$/)
    if (bulkCandidateChangePath && method === 'POST') {
      const preview = bulkCandidatePreviews.get(bulkCandidateChangePath[3] ?? '')
      if (!preview) throw new Error('변경요청 전에 bulk 후보 미리보기를 다시 확인하세요.')
      const body = jsonBody(options)
      const targetAssetId = responseString(preview.target_asset_id, '')
      const detail = await gatewayRequest<CatalogAssetDetail>(
        `/poc-api/datahub/asset?urn=${encodeURIComponent(targetAssetId)}`,
        { signal: options.signal },
      )
      const target: Record<string, unknown> = { kind: 'EXISTING', asset_id: targetAssetId }
      const sample = Array.isArray(preview.description_change_sample)
        ? preview.description_change_sample[0] as Record<string, unknown> | undefined
        : undefined
      if (preview.record_kind === 'TABLE_DESCRIPTION') target.description = sample?.proposed_description ?? ''
      if (preview.record_kind === 'COLUMN_DESCRIPTION') target.columns = [{
        field_path: sample?.field_path,
        description: sample?.proposed_description ?? '',
        requested_change: responseString(body.reason, ''),
      }]
      const record = createChangeRequest({
        title: responseString(body.title, `${detail.name} bulk metadata 변경`),
        system_id: detail.platform,
        request_reason: responseString(body.reason, ''),
        request_content: responseString(body.reason, ''),
        priority: 'NORMAL', urgency: 'NORMAL', security_level: detail.classification,
        targets: [target],
      })
      if (preview.record_kind === 'COLUMN_DESCRIPTION') record.items[0]!.aspect_name = 'schemaMetadata'
      else if (preview.record_kind === 'TABLE_DESCRIPTION') record.items[0]!.aspect_name = 'datasetProperties'
      else {
        record.items[0]!.aspect_name = preview.record_kind === 'DATASET_DOMAIN' ? 'domains'
          : preview.record_kind === 'DATASET_TERM' ? 'glossaryTerms' : 'globalTags'
      }
      await this.persistCore()
      return { id: record.id, number: record.number, request_type: 'BULK_CATALOG_METADATA', state: record.state }
    }
    if (path === '/registration/manual-submissions' && method === 'POST') {
      const body = jsonBody(options)
      if (!runtimeFlags().datahub) throw new Error('Manual metadata 저장에는 DataHub 설정이 필요합니다.')
      const now = new Date().toISOString()
      const serialNumber = manualSubmissionReports.length + 1
      const columnEdits = Array.isArray(body.column_edits) ? body.column_edits : []
      const applied = await gatewayRequest<{
        urn: string
        reports: Array<{
          aspect_name: string
          aspect_ordinal: number
          outcome: string
          before_hash: string
          expected_hash: string
          observed_hash: string
          write_attempted: boolean
          failure_code: string | null
          provider_version: string
          provider_response_hash: string | null
          observed_at: string
        }>
      }>('/poc-api/datahub/manual-metadata', {
        method: 'POST',
        signal: options.signal,
        body: JSON.stringify(body),
      })
      if (applied.urn !== body.asset_id || applied.reports.length !== 5) {
        throw new Error('DataHub Manual 적용 영수증이 요청 대상과 일치하지 않습니다.')
      }
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
      const aspects = applied.reports
      const reportHash = await sha256(JSON.stringify(aspects))
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
      await this.persistCore()
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
      const live = runtimeFlags().datahub
        ? await gatewayRequest<{ items: Array<{ id: string; code: string; name: string }> }>(
            '/poc-api/datahub/systems', { signal: options.signal },
          )
        : { items: [] }
      const merged = new Map(live.items.map((item) => [item.id, item]))
      for (const system of adminSystems.filter((item) => item.active)) {
        if (!merged.has(system.system_id)) {
          merged.set(system.system_id, {
            id: system.system_id,
            code: system.code,
            name: system.name,
          })
        }
      }
      return { items: [...merged.values()] }
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
      const created = createChangeRequest(jsonBody(options))
      await this.persistCore()
      return created
    }
    const revisionCommand = path.match(/^\/change-requests\/([^/]+)\/revisions$/)
    if (revisionCommand && method === 'POST') {
      const record = changeRecordById(decodeURIComponent(revisionCommand[1] ?? ''))
      requireCurrentVersion(record, options)
      const revised = reviseChangeRequest(record, jsonBody(options))
      await this.persistCore()
      return { ...revised }
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
      if (attachment.file) return { url: URL.createObjectURL(attachment.file) }
      const location = changeAttachmentLocations.get(attachment.id)
      if (!location) throw new Error('첨부파일 저장 위치를 찾을 수 없습니다. 파일을 현재 회차에 다시 첨부하세요.')
      const stored = await fetch(`/poc-api/minio/accepted/${encodeURIComponent(location.upload_id)}/${encodeURIComponent(location.display_name)}`, {
        signal: options.signal,
      })
      if (!stored.ok) throw new Error(`MinIO 첨부파일을 불러오지 못했습니다. (${stored.status})`)
      return { url: URL.createObjectURL(await stored.blob()) }
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
        const attachment = {
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
        }
        attachments.push(attachment)
        changeAttachments.set(record.id, attachments)
        changeAttachmentLocations.set(attachment.id, {
          upload_id: upload.id,
          display_name: upload.original_name,
        })
        upload.state = 'FINALIZED'
        await this.persistCore()
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
        if (target === 'CHANGES_REQUESTED' && record.request_type === 'CHANGE_INTAKE') {
          record.revision_allowed = true
        }
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
      await this.persistCore()
      return { ...record }
    }
    if (/^\/change-requests\/[^/]+$/.test(path)) {
      return { ...changeRecordById(path.split('/')[2] ?? '') }
    }

    if (path === '/quality/capability') {
      const observedAt = new Date()
      const states: Record<string, { state: 'AVAILABLE' | 'UNAVAILABLE'; reason_code: string | null }> = {
        read_access: runtimeFlags().datahub
          ? { state: 'AVAILABLE', reason_code: null }
          : { state: 'UNAVAILABLE', reason_code: 'DATAHUB_NOT_CONFIGURED' },
        profile_readiness: runtimeFlags().datahub
          ? { state: 'AVAILABLE', reason_code: null }
          : { state: 'UNAVAILABLE', reason_code: 'DATAHUB_NOT_CONFIGURED' },
        rule_authoring: { state: 'UNAVAILABLE', reason_code: 'QUALITY_CONTROL_PLANE_NOT_CONFIGURED' },
        review: { state: 'UNAVAILABLE', reason_code: 'QUALITY_CONTROL_PLANE_NOT_CONFIGURED' },
        activation: { state: 'UNAVAILABLE', reason_code: 'QUALITY_CONTROL_PLANE_NOT_CONFIGURED' },
        manual_execution: runtimeFlags().airflow
          ? { state: 'AVAILABLE', reason_code: null }
          : { state: 'UNAVAILABLE', reason_code: 'AIRFLOW_NOT_CONFIGURED' },
        scheduling: { state: 'UNAVAILABLE', reason_code: 'QUALITY_CONTROL_PLANE_NOT_CONFIGURED' },
        operations: { state: 'UNAVAILABLE', reason_code: 'QUALITY_CONTROL_PLANE_NOT_CONFIGURED' },
      }
      return {
        contract_version: 'QUALITY_CAPABILITY_V2',
        observed_at: observedAt.toISOString(),
        valid_until: new Date(observedAt.getTime() + 30_000).toISOString(),
        cache_scope: POC_CACHE_SCOPE,
        axes: Object.entries(states).map(([id, state]) => ({ id, ...state })),
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
          latest_quality_outcome: 'UNKNOWN' as const,
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
          fields: [],
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

    if (path === '/knowledge/domains/manage') return { items: knowledgeDomains.filter((item) => item.managed === true) }
    if (path === '/knowledge/domains' && method === 'GET') {
      const query = (url.searchParams.get('q') ?? '').trim().toLocaleLowerCase()
      return { items: knowledgeDomains.filter((item) => !query || String(item.display_name).toLocaleLowerCase().includes(query)) }
    }
    if (path === '/knowledge/domains' && method === 'POST') {
      const now = new Date().toISOString()
      const displayName = responseString(jsonBody(options).display_name, '').trim()
      if (!displayName) throw new Error('Domain 표시명이 필요합니다.')
      const domain = {
        id: crypto.randomUUID(), display_name: displayName, source_version: 'd'.repeat(64),
        created_by: POC_SUBJECT_ID, creator_display_name: 'POC User', creator_email: 'poc.user@local',
        asset_count: 0, lifecycle: 'ACTIVE', version: 1, created_at: now, updated_at: now, managed: true,
      }
      knowledgeDomains = [...knowledgeDomains, domain]
      await this.persistCore()
      return domain
    }
    const knowledgeDomainPath = path.match(/^\/knowledge\/domains\/([^/]+)$/)
    if (knowledgeDomainPath) {
      const domain = knowledgeDomains.find((item) => item.id === decodeURIComponent(knowledgeDomainPath[1] ?? ''))
      if (!domain) throw new Error('POC Knowledge Domain을 찾을 수 없습니다.')
      if (method === 'PATCH') {
        const displayName = responseString(jsonBody(options).display_name, '').trim()
        if (!displayName) throw new Error('Domain 표시명이 필요합니다.')
        domain.display_name = displayName
        domain.version = Number(domain.version) + 1
        domain.updated_at = new Date().toISOString()
        await this.persistCore()
        return domain
      }
      if (method === 'DELETE') {
        domain.lifecycle = 'INACTIVE'
        domain.version = Number(domain.version) + 1
        domain.updated_at = new Date().toISOString()
        await this.persistCore()
        return undefined
      }
    }
    if (path === '/knowledge/property-profiles') return { items: [] }
    const knowledgeEditDraftPath = path.match(/^\/knowledge\/studio\/drafts\/from-asset\/([^/]+)$/)
    if (knowledgeEditDraftPath && method === 'POST') {
      const graphId = decodeURIComponent(knowledgeEditDraftPath[1] ?? '')
      const source = knowledgeDrafts.find((item) => item.materialized_graph_id === graphId && item.state === 'PUBLISHED')
      if (!source) throw new Error('편집할 게시 지식 자산을 찾을 수 없습니다.')
      const existing = knowledgeDrafts.find((item) => item.materialized_graph_id === graphId && item.kind === 'EDIT' && item.state === 'DRAFT')
      if (existing) return existing
      const now = new Date().toISOString()
      const draft = {
        ...source, id: crypto.randomUUID(), author_id: POC_SUBJECT_ID, kind: 'EDIT', state: 'DRAFT',
        current_step: 'TBOX', last_autosaved_at: now, version: 1, created_at: now, updated_at: now,
        reviewed_by: undefined, reviewed_at: undefined, review_reason: undefined,
        published_by: undefined, published_at: undefined, published_studio_release_id: undefined,
      }
      knowledgeDrafts = [...knowledgeDrafts, draft]
      knowledgeDraftBlocks.set(String(draft.id), structuredClone(knowledgeDraftBlocks.get(String(source.id)) ?? []))
      knowledgeDraftBindings.set(String(draft.id), structuredClone(knowledgeDraftBindings.get(String(source.id)) ?? []))
      await this.persistCore()
      return draft
    }
    if (path === '/knowledge/studio/drafts/resumable') {
      const alias = url.searchParams.get('endpoint_alias') ?? ''
      const draft = knowledgeDrafts.find((item) => item.endpoint_alias === alias && item.state === 'DRAFT')
      if (!draft) throw new Error('A resumable Knowledge Studio draft does not exist.')
      return draft
    }
    if (path === '/knowledge/studio/drafts' && method === 'POST') {
      const body = jsonBody(options)
      const domain = knowledgeDomains.find((item) => item.id === body.domain_id && item.lifecycle === 'ACTIVE')
      if (!domain) throw new Error('활성 Knowledge Domain을 선택하세요.')
      const now = new Date().toISOString()
      const draft = {
        id: crypto.randomUUID(), author_id: POC_SUBJECT_ID, kind: 'CREATE', state: 'DRAFT', current_step: 'BASIC',
        name: responseString(body.name, '').trim(), endpoint_alias: responseString(body.endpoint_alias, '').trim(),
        endpoint_aliases: Array.isArray(body.endpoint_aliases) ? body.endpoint_aliases : [body.endpoint_alias],
        domain_id: body.domain_id, domain_source_version: body.domain_source_version,
        classification: body.classification ?? 'INTERNAL', last_autosaved_at: now,
        version: 1, created_at: now, updated_at: now,
      }
      if (!draft.name || !/^[a-z][a-z0-9_]{2,99}$/.test(draft.endpoint_alias)) throw new Error('Knowledge Asset 이름과 유효한 endpoint alias가 필요합니다.')
      if (knowledgeDrafts.some((item) => item.endpoint_alias === draft.endpoint_alias && !['DISCARDED', 'PUBLISHED'].includes(String(item.state)))) throw new Error('동일한 endpoint alias의 Draft가 이미 있습니다.')
      knowledgeDrafts = [...knowledgeDrafts, draft]
      knowledgeDraftBlocks.set(draft.id, [])
      knowledgeDraftBindings.set(draft.id, [])
      await this.persistCore()
      return draft
    }
    const knowledgeDraftPath = path.match(/^\/knowledge\/studio\/drafts\/([^/]+)$/)
    if (knowledgeDraftPath) {
      const draft = knowledgeDraftById(decodeURIComponent(knowledgeDraftPath[1] ?? ''))
      if (method === 'GET') return draft
      if (method === 'PATCH') {
        Object.assign(draft, jsonBody(options), { version: Number(draft.version) + 1, updated_at: new Date().toISOString(), last_autosaved_at: new Date().toISOString() })
        await this.persistCore()
        return draft
      }
    }
    const draftAdvancePath = path.match(/^\/knowledge\/studio\/drafts\/([^/]+)\/advance$/)
    if (draftAdvancePath && method === 'POST') {
      const draft = knowledgeDraftById(decodeURIComponent(draftAdvancePath[1] ?? ''))
      const target = jsonBody(options).target_step
      draft.current_step = target === 'ABOX' ? 'ABOX' : 'TBOX'
      draft.version = Number(draft.version) + 1
      draft.updated_at = new Date().toISOString()
      await this.persistCore()
      return draft
    }
    const tboxPath = path.match(/^\/knowledge\/studio\/drafts\/([^/]+)\/tbox$/)
    if (tboxPath && method === 'GET') return knowledgeTBox(decodeURIComponent(tboxPath[1] ?? ''))
    const tboxBlocksPath = path.match(/^\/knowledge\/studio\/drafts\/([^/]+)\/tbox\/blocks$/)
    if (tboxBlocksPath && method === 'POST') {
      const draftId = decodeURIComponent(tboxBlocksPath[1] ?? '')
      const draft = knowledgeDraftById(draftId)
      const body = jsonBody(options)
      const blocks = knowledgeDraftBlocks.get(draftId) ?? []
      const now = new Date().toISOString()
      blocks.push({ id: crypto.randomUUID(), kind: body.kind ?? 'DIRECT', title: responseString(body.title, 'Layer'), weight: Number(body.weight) || 0, ordinal: blocks.length, collapsed: false, version: 1, elements: [], created_at: now, updated_at: now })
      knowledgeDraftBlocks.set(draftId, blocks)
      draft.version = Number(draft.version) + 1
      draft.updated_at = now
      await this.persistCore()
      return knowledgeTBox(draftId)
    }
    const tboxBlockOperationPath = path.match(/^\/knowledge\/studio\/drafts\/([^/]+)\/tbox\/blocks\/([^/]+)\/operations$/)
    if (tboxBlockOperationPath && method === 'POST') {
      const draftId = decodeURIComponent(tboxBlockOperationPath[1] ?? '')
      const blockId = decodeURIComponent(tboxBlockOperationPath[2] ?? '')
      const draft = knowledgeDraftById(draftId)
      const block = (knowledgeDraftBlocks.get(draftId) ?? []).find((item) => item.id === blockId)
      if (!block) throw new Error('POC T-Box Layer를 찾을 수 없습니다.')
      const elements = Array.isArray(block.elements) ? block.elements as Array<Record<string, unknown>> : []
      const operations = jsonBody(options).operations
      for (const raw of Array.isArray(operations) ? operations : []) {
        if (!raw || typeof raw !== 'object') continue
        const operation = raw as Record<string, unknown>
        const stableId = responseString(operation.stable_element_id, '')
        const index = elements.findIndex((item) => item.stable_element_id === stableId)
        if (operation.operation === 'DELETE_ELEMENT') {
          if (index >= 0) elements.splice(index, 1)
        } else if (operation.operation === 'SET_LAYOUT' && index >= 0) {
          Object.assign(elements[index]!, { layout_x: operation.layout_x, layout_y: operation.layout_y, version: Number(elements[index]!.version) + 1 })
        } else if (operation.operation === 'UPSERT_ELEMENT' && operation.element && typeof operation.element === 'object') {
          const value = { ...(operation.element as Record<string, unknown>), stable_element_id: stableId, ordinal: index >= 0 ? elements[index]!.ordinal : elements.length, version: index >= 0 ? Number(elements[index]!.version) + 1 : 1, block_id: blockId, locked_by_later_block: false }
          if (index >= 0) elements[index] = value
          else elements.push(value)
        }
      }
      block.elements = elements
      block.version = Number(block.version) + 1
      block.updated_at = new Date().toISOString()
      draft.version = Number(draft.version) + 1
      draft.updated_at = block.updated_at
      await this.persistCore()
      return knowledgeTBox(draftId)
    }
    const tboxBlockPath = path.match(/^\/knowledge\/studio\/drafts\/([^/]+)\/tbox\/blocks\/([^/]+)$/)
    if (tboxBlockPath) {
      const draftId = decodeURIComponent(tboxBlockPath[1] ?? '')
      const blockId = decodeURIComponent(tboxBlockPath[2] ?? '')
      const draft = knowledgeDraftById(draftId)
      const blocks = knowledgeDraftBlocks.get(draftId) ?? []
      const block = blocks.find((item) => item.id === blockId)
      if (!block) throw new Error('POC T-Box Layer를 찾을 수 없습니다.')
      if (method === 'PATCH') Object.assign(block, jsonBody(options), { version: Number(block.version) + 1, updated_at: new Date().toISOString() })
      if (method === 'DELETE') knowledgeDraftBlocks.set(draftId, blocks.filter((item) => item.id !== blockId))
      draft.version = Number(draft.version) + 1
      draft.updated_at = new Date().toISOString()
      await this.persistCore()
      return knowledgeTBox(draftId)
    }
    const aboxPath = path.match(/^\/knowledge\/studio\/drafts\/([^/]+)\/abox$/)
    if (aboxPath && method === 'GET') {
      const draftId = decodeURIComponent(aboxPath[1] ?? '')
      const blocks = knowledgeDraftBlocks.get(draftId) ?? []
      return { draft: knowledgeDraftById(draftId), tbox_elements: blocks.flatMap((block) => Array.isArray(block.elements) ? block.elements as Array<Record<string, unknown>> : []), bindings: knowledgeDraftBindings.get(draftId) ?? [] }
    }
    const aboxBindingPath = path.match(/^\/knowledge\/studio\/drafts\/([^/]+)\/abox\/bindings\/(.+)$/)
    if (aboxBindingPath && method === 'PATCH') {
      const draftId = decodeURIComponent(aboxBindingPath[1] ?? '')
      const targetStableElementId = decodeURIComponent(aboxBindingPath[2] ?? '')
      const draft = knowledgeDraftById(draftId)
      const body = jsonBody(options)
      const assetId = responseString(body.source_asset_id, '')
      const detail = await gatewayRequest<CatalogAssetDetail>(`/poc-api/datahub/asset?urn=${encodeURIComponent(assetId)}`, { signal: options.signal })
      const now = new Date().toISOString()
      const bindings = knowledgeDraftBindings.get(draftId) ?? []
      const existingIndex = bindings.findIndex((item) => item.target_stable_element_id === targetStableElementId)
      const binding = {
        id: existingIndex >= 0 ? bindings[existingIndex]!.id : crypto.randomUUID(),
        target_stable_element_id: targetStableElementId, source_reference_id: assetId,
        source_asset_id: assetId, source_name: detail.name,
        source_version: responseString(body.source_version, detail.source_version),
        projection_source_version: responseString(body.projection_source_version, detail.projection_source_version),
        source_classification: detail.classification, readiness: 'DRAFT',
        tbox_version: Number(draft.version), version: existingIndex >= 0 ? Number(bindings[existingIndex]!.version) + 1 : 1,
        rules: (Array.isArray(body.rules) ? body.rules : []).map((rule, ordinal) => ({
          ...(rule as Record<string, unknown>), id: crypto.randomUUID(), ordinal,
          transform_id: 'IDENTITY', transform_version: '1',
        })),
        created_at: existingIndex >= 0 ? bindings[existingIndex]!.created_at : now, updated_at: now,
      }
      if (existingIndex >= 0) bindings[existingIndex] = binding
      else bindings.push(binding)
      knowledgeDraftBindings.set(draftId, bindings)
      draft.version = Number(draft.version) + 1; draft.updated_at = now
      await this.persistCore()
      return { draft, binding }
    }
    const catalogSourcesPath = path.match(/^\/knowledge\/studio\/drafts\/([^/]+)\/(?:tbox\/catalog-sources|abox\/sources)$/)
    if (catalogSourcesPath && method === 'GET') {
      knowledgeDraftById(decodeURIComponent(catalogSourcesPath[1] ?? ''))
      const result = runtimeFlags().datahub
        ? await liveCatalog(new URLSearchParams({ q: url.searchParams.get('q') || '*', limit: url.searchParams.get('limit') || '25' }), options.signal)
        : { items: [], page: { next_cursor: null, limit: 25 } }
      return { items: result.items.map((asset) => ({ id: asset.id, name: asset.name, asset_type: 'DATASET', platform: asset.platform, database_name: asset.database_name, schema_name: asset.schema_name, classification: asset.classification, source_version: 'datahub-live', projection_source_version: 'datahub-live-poc', field_paths: [], fields_truncated: false, domain: asset.domain, tags: asset.tags, glossary_terms: asset.terms, description: asset.description, description_truncated: false, field_metadata: [], selection_fingerprint: null })), page: result.page }
    }
    const catalogSourceDetailPath = path.match(/^\/knowledge\/studio\/drafts\/([^/]+)\/(?:tbox\/catalog-sources|abox\/sources)\/(.+)$/)
    if (catalogSourceDetailPath && method === 'GET') {
      knowledgeDraftById(decodeURIComponent(catalogSourceDetailPath[1] ?? ''))
      const detail = await gatewayRequest<CatalogAssetDetail>(`/poc-api/datahub/asset?urn=${encodeURIComponent(decodeURIComponent(catalogSourceDetailPath[2] ?? ''))}`, { signal: options.signal })
      const fieldMetadata = detail.schema_fields.map((field) => ({
        field_path: responseString(field.fieldPath ?? field.field_path, ''), field_type: field.type ?? null,
        native_data_type: field.nativeDataType ?? field.native_data_type ?? null,
        description: field.description ?? null, description_truncated: false,
        tags: Array.isArray(field.tags) ? field.tags.map(String) : [], tags_truncated: false,
        glossary_terms: Array.isArray(field.terms) ? field.terms.map(String) : [], terms_truncated: false,
      }))
      return { dataset: { id: detail.id, name: detail.name, asset_type: 'DATASET', platform: detail.platform, database_name: detail.database_name, schema_name: detail.schema_name, classification: detail.classification, source_version: detail.source_version, projection_source_version: detail.projection_source_version, field_paths: fieldMetadata.map((field) => field.field_path), fields_truncated: detail.schema_fields_truncated, domain: detail.domain, tags: detail.tags, glossary_terms: detail.terms, description: detail.description, description_truncated: false, field_metadata: fieldMetadata, selection_fingerprint: null }, observed_at: new Date().toISOString() }
    }
    const preflightPath = path.match(/^\/knowledge\/studio\/drafts\/([^/]+)\/abox\/preflight$/)
    if (preflightPath && method === 'POST') {
      const draft = knowledgeDraftById(decodeURIComponent(preflightPath[1] ?? ''))
      return { status: 'PASS', valid: true, draft_version: draft.version, checked_at: new Date().toISOString(), receipt_id: crypto.randomUUID(), contract_hash: 'e'.repeat(64), evidence: [] }
    }
    const draftLifecyclePath = path.match(/^\/knowledge\/studio\/drafts\/([^/]+)\/(submit-review|discard|publish)$/)
    if (draftLifecyclePath && method === 'POST') {
      const draft = knowledgeDraftById(decodeURIComponent(draftLifecyclePath[1] ?? ''))
      const action = draftLifecyclePath[2]
      const now = new Date().toISOString()
      draft.version = Number(draft.version) + 1
      draft.updated_at = now
      if (action === 'submit-review') {
        draft.state = 'REVIEW'
        draft.submitted_preflight_check_id = crypto.randomUUID()
        await this.persistCore()
        return draft
      }
      if (action === 'discard') {
        draft.state = 'DISCARDED'
        await this.persistCore()
        return draft
      }
      const graphId = responseString(draft.materialized_graph_id, crypto.randomUUID())
      const release = { id: crypto.randomUUID(), graph_id: graphId, ontology_version_id: crypto.randomUUID(), release_no: 1, state: 'ACTIVE', contract_version: 'KNOWLEDGE_STUDIO_RELEASE_V1', contract_hash: 'f'.repeat(64), tbox_hash: 'a'.repeat(64), abox_hash: 'b'.repeat(64), reviewed_by: POC_SUBJECT_ID, published_by: POC_SUBJECT_ID, published_at: now }
      Object.assign(draft, { state: 'PUBLISHED', reviewed_by: POC_SUBJECT_ID, reviewed_at: now, review_reason: responseString(jsonBody(options).review_reason, 'POC open review'), published_by: POC_SUBJECT_ID, published_at: now, materialized_graph_id: graphId, materialized_ontology_version_id: release.ontology_version_id, published_studio_release_id: release.id })
      knowledgeReleases = [...knowledgeReleases, release]
      await this.persistCore()
      return { draft, release }
    }
    const publishedPairs = knowledgeDrafts.flatMap((draft) => {
      const release = knowledgeReleases.find((item) => item.id === draft.published_studio_release_id)
      return release ? [{ draft, release }] : []
    })
    if (path === '/knowledge/graphs') return publishedPairs.map(({ draft, release }) => ({ id: draft.materialized_graph_id, slug: draft.endpoint_alias, name: draft.name, graph_type: 'CURATED_KNOWLEDGE', status: 'ACTIVE', classification: draft.classification, domain_id: draft.domain_id, domain_source_version: draft.domain_source_version, domain_name: knowledgeDomains.find((item) => item.id === draft.domain_id)?.display_name, active_release_id: release.id, created_by: POC_SUBJECT_ID, updated_by: POC_SUBJECT_ID, created_at: draft.created_at, updated_at: draft.updated_at, version: draft.version }))
    if (path === '/knowledge/registry/assets') return { items: publishedPairs.map(({ draft, release }) => knowledgeAssetSummary(draft, release)), next_cursor: null, limit: Number(url.searchParams.get('limit') ?? 25) }
    const knowledgeRegistryPath = path.match(/^\/knowledge\/registry\/assets\/([^/]+)\/(detail|versions)$/)
    if (knowledgeRegistryPath) {
      const graphId = decodeURIComponent(knowledgeRegistryPath[1] ?? '')
      const pair = publishedPairs.find(({ draft }) => draft.materialized_graph_id === graphId)
      if (!pair) throw new Error('등록된 지식 자산이 없습니다.')
      const asset = knowledgeAssetSummary(pair.draft, pair.release)
      const blocks = knowledgeDraftBlocks.get(String(pair.draft.id)) ?? []
      const elements = blocks.flatMap((block) => Array.isArray(block.elements) ? block.elements as Array<Record<string, unknown>> : [])
      if (knowledgeRegistryPath[2] === 'detail') return { asset, schema_elements: elements.map((item) => ({ stable_element_id: item.stable_element_id, kind: item.kind, display_name: item.display_name, canonical_name: item.canonical_name, parent_stable_element_id: item.parent_stable_element_id ?? null, data_type: item.data_type ?? null, source_stable_element_id: item.source_stable_element_id ?? null, target_stable_element_id: item.target_stable_element_id ?? null })), bindings: [], projections: [] }
      return { items: [{ id: pair.release.id, kind: 'STUDIO_RELEASE', version_label: `T v${responseString(pair.release.release_no, '1')}`, title: responseString(pair.draft.name, 'POC knowledge asset'), status: 'ACTIVE', author_id: POC_SUBJECT_ID, author_name: 'POC User', author_email: 'poc.user@local', reviewed_by: POC_SUBJECT_ID, reviewer_name: 'POC User', reviewer_email: 'poc.user@local', published_by: POC_SUBJECT_ID, publisher_name: 'POC User', publisher_email: 'poc.user@local', created_at: pair.release.published_at, is_current: true, studio_release_id: pair.release.id, instance_release_id: null, changeset_id: null, content_hash: pair.release.contract_hash, node_count: 0, edge_count: 0 }], next_cursor: null, limit: 50 }
    }
    const graphReleasesPath = path.match(/^\/knowledge\/graphs\/([^/]+)\/releases$/)
    if (graphReleasesPath) {
      const graphId = decodeURIComponent(graphReleasesPath[1] ?? '')
      return knowledgeReleases.filter((item) => item.graph_id === graphId).map((item) => ({ id: item.id, graph_id: item.graph_id, release_no: item.release_no, ontology_version_id: item.ontology_version_id, content_hash: item.contract_hash, node_count: 0, edge_count: 0, published_by: POC_SUBJECT_ID, published_at: item.published_at, publisher_name: 'POC User', publisher_email: 'poc.user@local' }))
    }
    const graphSnapshotPath = path.match(/^\/knowledge\/graphs\/([^/]+)\/releases\/([^/]+)\/snapshot$/)
    if (graphSnapshotPath) {
      const graphId = decodeURIComponent(graphSnapshotPath[1] ?? '')
      const releaseId = decodeURIComponent(graphSnapshotPath[2] ?? '')
      const release = knowledgeReleases.find((item) => item.graph_id === graphId && item.id === releaseId)
      if (!release) throw new Error('등록된 지식 그래프 릴리스가 없습니다.')
      return { release: { id: release.id, graph_id: graphId, release_no: release.release_no, ontology_version_id: release.ontology_version_id, content_hash: release.contract_hash, node_count: 0, edge_count: 0, published_by: POC_SUBJECT_ID, published_at: release.published_at }, nodes: [], edges: [], filtered: false }
    }
    if (/^\/knowledge\/graphs\/[^/]+\/changesets$/.test(path)) return []

    if (path === '/governance/documents/capability') {
      const window = authorizationWindow()
      const providerAxis = (id: string, configured: boolean) => ({
        id,
        state: configured ? 'AVAILABLE' : 'UNAVAILABLE',
        reason_code: configured ? null : 'PROVIDER_NOT_CONFIGURED',
      })
      return {
        contract_version: 'GOVERNANCE_DOCUMENT_CAPABILITY_V1',
        observed_at: window.observed_at,
        valid_until: window.authorization_valid_until,
        cache_scope: POC_CACHE_SCOPE,
        axes: [
          ...['read', 'create', 'edit', 'review', 'publish', 'archive', 'template_manage']
            .map((id) => ({ id, state: 'AVAILABLE', reason_code: null })),
          providerAxis('artifact_storage', Boolean(runtimeFlags().minio)),
          providerAxis('knowledge_projection', Boolean(runtimeFlags().neo4j)),
        ],
        limits: { max_html_bytes: 1_000_000, max_attachment_bytes: 10_000_000, max_attachments_per_version: 25 },
      }
    }
    if (path === '/governance/documents/template-blueprints') {
      const definitions = [
        ['template-policy', 'TEMPLATE', 'POLICY', '정책 Template', '정책 문서 작성을 위한 승인 가능한 기본 구조', '전사 데이터 정책', '<h2>목적</h2><p>정책 목적을 작성하세요.</p><h2>통제</h2><p>통제 기준을 작성하세요.</p>'],
        ['template-terminology', 'TEMPLATE', 'STANDARD_TERMINOLOGY', '표준 용어 Template', '표준 용어와 적용 범위를 기록하는 기본 구조', '전사 표준 용어', '<h2>정의</h2><p>표준 용어를 작성하세요.</p><h2>적용 범위</h2><p>적용 범위를 작성하세요.</p>'],
        ['template-security', 'TEMPLATE', 'SECURITY_GUIDE', '보안 가이드 Template', '데이터 보안 통제를 기록하는 기본 구조', '전사 보안 통제', '<h2>보호 대상</h2><p>보호 대상을 작성하세요.</p><h2>보안 통제</h2><p>통제를 작성하세요.</p>'],
        ['starter-classification', 'STARTER_DOCUMENT', 'POLICY', '데이터 분류·접근 정책', '분류와 접근 원칙을 작성하는 시작 문서', '전사 데이터', '<h2>데이터 분류</h2><p>분류 기준을 작성하세요.</p><h2>접근 원칙</h2><p>접근 통제를 작성하세요.</p>'],
        ['starter-retention', 'STARTER_DOCUMENT', 'POLICY', '보존·파기 정책', '보존 기간과 파기 절차를 작성하는 시작 문서', '전사 데이터', '<h2>보존</h2><p>보존 기간을 작성하세요.</p><h2>파기</h2><p>파기 절차를 작성하세요.</p>'],
        ['starter-legal-hold', 'STARTER_DOCUMENT', 'SECURITY_GUIDE', 'Legal Hold 관리', '법적 보존 대상과 해제 절차를 작성하는 시작 문서', '법적 보존 대상', '<h2>지정</h2><p>Legal Hold 지정 기준을 작성하세요.</p><h2>해제</h2><p>해제 절차를 작성하세요.</p>'],
      ] as const
      return {
        contract_version: 'GOVERNANCE_DOCUMENT_BLUEPRINTS_V2',
        items: await Promise.all(definitions.map(async ([id, purpose, category, title, summary, scope, html]) => ({
          blueprint_id: id, blueprint_version: 'GOVERNANCE_DOCUMENT_BLUEPRINTS_V2', purpose,
          category, title, summary, applicability_scope: scope, sanitized_html: html,
          content_sha256: await sha256(html), sanitizer_policy_version: 'POC_SANITIZER_V1',
          sanitizer_policy_sha256: 'c'.repeat(64),
        }))),
      }
    }
    if (path === '/governance/documents/knowledge/evidence') {
      const query = (url.searchParams.get('q') ?? '').trim().toLocaleLowerCase()
      const items = governanceVersions
        .filter((version) => version.state === 'PUBLISHED' && (!query || `${version.title} ${version.plain_text}`.toLocaleLowerCase().includes(query)))
        .slice(0, 25)
        .map((version, index) => ({
          chunk_id: `${version.version_id}:0`, document_id: version.document_id,
          document_version_id: version.version_id, document_title: version.title,
          version_tag: version.version_tag, ordinal: index,
          excerpt: version.plain_text.slice(0, 500), content_sha256: version.content_sha256,
          score_basis_points: 10_000, classification: governanceDocuments.find((item) => item.document_id === version.document_id)?.classification ?? 1,
          published_at: version.published_at ?? version.created_at,
        }))
      return { items, cache_scope: POC_CACHE_SCOPE, ...authorizationWindow() }
    }
    const governanceCreate = path === '/governance/documents' && method === 'POST'
      || path === '/governance/documents/imports' && method === 'POST'
    if (governanceCreate) {
      const form = options.body instanceof FormData ? options.body : null
      const body = form ? Object.fromEntries(form.entries()) : jsonBody(options)
      const now = new Date().toISOString()
      const documentId = crypto.randomUUID()
      const title = responseString(body.title, '').trim()
      if (!title) throw new Error('거버넌스 문서명이 필요합니다.')
      const kind = body.kind === 'TEMPLATE' ? 'TEMPLATE' as const : 'DOCUMENT' as const
      const category = ['POLICY', 'STANDARD_TERMINOLOGY', 'SECURITY_GUIDE', 'OTHER'].includes(String(body.category))
        ? body.category as GovernanceDocumentSummary['category'] : 'OTHER'
      const document: GovernanceDocumentSummary = {
        document_id: documentId, workspace_id: POC_WORKSPACE_ID, kind, category, title,
        summary: responseString(body.summary, ''), classification: Number(body.classification) || 1,
        state: 'DRAFT', owner_subject_id: POC_SUBJECT_ID, current_published_version_id: null,
        current_version_number: null, created_at: now, updated_at: now, version: 1, allowed_actions: [],
      }
      let html = responseString(body.sanitized_html, '')
      const sourceTemplateId = responseString(body.source_template_version_id, '') || null
      if (!html && sourceTemplateId) html = governanceVersions.find((item) => item.version_id === sourceTemplateId)?.sanitized_html ?? ''
      const imported = form?.get('file')
      let sourceFormat: 'HTML' | 'MARKDOWN' | 'DOCX' = 'HTML'
      if (imported instanceof File) {
        const converted = await governanceImportedMarkup(imported)
        html = converted.html
        sourceFormat = converted.sourceFormat
      }
      if (!html) html = '<p></p>'
      const version = await governanceVersion(document, {
        title, summary: document.summary,
        applicability_scope: responseString(body.applicability_scope, ''), sanitized_html: html,
        source_template_version_id: sourceTemplateId,
        parent_document_id: responseString(body.parent_document_id, '') || null,
        source_format: sourceFormat,
      })
      document.allowed_actions = [...governanceActions(document)]
      governanceDocuments = [...governanceDocuments, document]
      governanceVersions = [...governanceVersions, version]
      await this.persistCore()
      return { item: governanceDetail(documentId) }
    }
    if (path === '/governance/documents' && method === 'GET') {
      const query = (url.searchParams.get('q') ?? '').trim().toLocaleLowerCase()
      const kind = url.searchParams.get('kind')
      const state = url.searchParams.get('state')
      const includeArchived = url.searchParams.get('include_archived') === 'true'
      const limit = Number(url.searchParams.get('limit') ?? 100)
      const items = governanceDocuments.filter((item) => (
        (!query || `${item.title} ${item.summary}`.toLocaleLowerCase().includes(query))
        && (!kind || item.kind === kind)
        && (!state || item.state === state)
        && (includeArchived || item.state !== 'ARCHIVED')
      )).slice(0, limit).map((item) => ({ ...item, allowed_actions: [...governanceActions(item)] }))
      return { items, page: { next_cursor: null, limit }, cache_scope: POC_CACHE_SCOPE, ...authorizationWindow() }
    }
    const governanceExportPath = path.match(/^\/governance\/documents\/([^/]+)\/export$/)
    if (governanceExportPath && method === 'GET') {
      const documentId = decodeURIComponent(governanceExportPath[1] ?? '')
      const detail = governanceDetail(documentId)
      const requestedVersion = url.searchParams.get('version_id')
      const selected = detail.versions.find((item) => item.version_id === requestedVersion)
        ?? detail.versions.find((item) => item.version_id === detail.document.current_published_version_id)
        ?? detail.versions[0]
      if (!selected) throw new Error('내보낼 문서 버전이 없습니다.')
      return {
        contract_version: 'GOVERNANCE_DOCUMENT_EXPORT_V1', exported_at: new Date().toISOString(),
        document: detail.document, selected_version: selected, version_history: detail.versions,
        reviews: detail.reviews, attachments: detail.attachments,
        parent_document: detail.parent_document, child_documents: detail.child_documents,
        cache_scope: POC_CACHE_SCOPE, ...authorizationWindow(),
      }
    }
    const governanceVersionCreatePath = path.match(/^\/governance\/documents\/([^/]+)\/versions$/)
    if (governanceVersionCreatePath && method === 'POST') {
      const documentId = decodeURIComponent(governanceVersionCreatePath[1] ?? '')
      const document = governanceDetail(documentId).document
      const form = options.body instanceof FormData ? options.body : null
      const body = form ? Object.fromEntries(form.entries()) : jsonBody(options)
      let html = responseString(body.sanitized_html, '')
      const imported = form?.get('file')
      let sourceFormat: 'HTML' | 'MARKDOWN' | 'DOCX' = 'HTML'
      if (imported instanceof File) {
        const converted = await governanceImportedMarkup(imported)
        html = converted.html
        sourceFormat = converted.sourceFormat
      }
      const version = await governanceVersion(document, {
        title: responseString(body.title, document.title), summary: responseString(body.summary, document.summary),
        applicability_scope: responseString(body.applicability_scope, ''), sanitized_html: html || '<p></p>',
        source_template_version_id: responseString(body.source_template_version_id, '') || null,
        parent_document_id: responseString(body.parent_document_id, '') || null,
        source_format: sourceFormat,
      })
      governanceVersions = [...governanceVersions, version]
      document.version += 1
      document.updated_at = new Date().toISOString()
      await this.persistCore()
      return { item: governanceDetail(documentId) }
    }
    const governanceSubmissionPath = path.match(/^\/governance\/documents\/([^/]+)\/versions\/([^/]+)\/submissions$/)
    if (governanceSubmissionPath && method === 'POST') {
      const documentId = decodeURIComponent(governanceSubmissionPath[1] ?? '')
      const versionId = decodeURIComponent(governanceSubmissionPath[2] ?? '')
      const document = governanceDetail(documentId).document
      const version = governanceVersions.find((item) => item.document_id === documentId && item.version_id === versionId)
      if (!version || version.state !== 'DRAFT') throw new Error('상신 가능한 Draft 버전이 아닙니다.')
      version.state = 'IN_REVIEW'; version.submitted_at = new Date().toISOString(); version.version += 1
      document.version += 1; document.updated_at = version.submitted_at
      await this.persistCore()
      return { item: governanceDetail(documentId) }
    }
    const governanceReviewPath = path.match(/^\/governance\/documents\/([^/]+)\/versions\/([^/]+)\/reviews$/)
    if (governanceReviewPath && method === 'POST') {
      const documentId = decodeURIComponent(governanceReviewPath[1] ?? '')
      const versionId = decodeURIComponent(governanceReviewPath[2] ?? '')
      const document = governanceDetail(documentId).document
      const version = governanceVersions.find((item) => item.document_id === documentId && item.version_id === versionId)
      if (!version || version.state !== 'IN_REVIEW') throw new Error('검토 가능한 상신 버전이 아닙니다.')
      const body = jsonBody(options)
      const decision = body.decision === 'REJECT' ? 'REJECT' as const : 'APPROVE' as const
      const now = new Date().toISOString()
      governanceReviews = [...governanceReviews, {
        review_id: crypto.randomUUID(), workspace_id: POC_WORKSPACE_ID, document_id: documentId,
        document_version_id: versionId, decision, reviewer_id: POC_SUBJECT_ID,
        reason: responseString(body.reason, ''), policy_decision_id: 'POC_OPEN_SCOPE',
        authentication_assurance: 'POC_OPEN_SCOPE', created_at: now,
      }]
      version.state = decision === 'APPROVE' ? 'PUBLISHED' : 'REJECTED'
      version.reviewed_by = POC_SUBJECT_ID; version.reviewed_at = now; version.version += 1
      if (decision === 'APPROVE') {
        for (const candidate of governanceVersions) {
          if (candidate.document_id === documentId && candidate.state === 'PUBLISHED' && candidate.version_id !== versionId) candidate.state = 'SUPERSEDED'
        }
        version.published_at = now
        version.knowledge_state = runtimeFlags().neo4j ? 'READY' : 'PENDING'
        document.state = 'ACTIVE'; document.current_published_version_id = versionId
        document.current_version_number = version.version_number; document.title = version.title; document.summary = version.summary
      }
      document.version += 1; document.updated_at = now
      await this.persistCore()
      return { item: governanceDetail(documentId) }
    }
    const governanceArchivePath = path.match(/^\/governance\/documents\/([^/]+)\/archive$/)
    if (governanceArchivePath && method === 'POST') {
      const documentId = decodeURIComponent(governanceArchivePath[1] ?? '')
      const document = governanceDetail(documentId).document
      document.state = 'ARCHIVED'; document.version += 1; document.updated_at = new Date().toISOString()
      document.allowed_actions = [...governanceActions(document)]
      await this.persistCore()
      return { item: governanceDetail(documentId) }
    }
    const governanceAttachmentPath = path.match(/^\/governance\/documents\/([^/]+)\/versions\/([^/]+)\/attachments$/)
    if (governanceAttachmentPath && method === 'POST') {
      if (!runtimeFlags().minio) throw new Error('거버넌스 첨부파일에는 MinIO 설정이 필요합니다.')
      if (!(options.body instanceof FormData)) throw new Error('첨부파일 FormData가 필요합니다.')
      const file = options.body.get('file')
      if (!(file instanceof File)) throw new Error('첨부파일이 필요합니다.')
      const documentId = decodeURIComponent(governanceAttachmentPath[1] ?? '')
      const versionId = decodeURIComponent(governanceAttachmentPath[2] ?? '')
      const document = governanceDetail(documentId).document
      if (!governanceVersions.some((item) => item.document_id === documentId && item.version_id === versionId)) throw new Error('첨부 대상 버전이 없습니다.')
      const uploadId = crypto.randomUUID()
      const digest = await sha256(new Uint8Array(await file.arrayBuffer()))
      const part = await fetch(`/poc-api/minio/uploads/${encodeURIComponent(uploadId)}/parts/1`, {
        method: 'PUT', signal: options.signal,
        headers: { 'Content-Type': file.type || 'application/octet-stream' }, body: file,
      })
      if (!part.ok) throw new Error(`MinIO 첨부파일 저장에 실패했습니다. (${part.status})`)
      const stored = await gatewayRequest<{ key: string }>(`/poc-api/minio/uploads/${encodeURIComponent(uploadId)}/complete`, {
        method: 'POST', signal: options.signal,
        body: JSON.stringify({ part_count: 1, display_name: file.name, content_type: file.type || 'application/octet-stream' }),
      })
      const attachment: GovernanceDocumentAttachment = {
        attachment_id: crypto.randomUUID(), workspace_id: POC_WORKSPACE_ID, document_id: documentId,
        document_version_id: versionId,
        serial_number: governanceAttachments.filter((item) => item.document_version_id === versionId).length + 1,
        storage_filename: stored.key, original_name: file.name,
        content_type: file.type || 'application/octet-stream', size_bytes: file.size,
        content_sha256: digest, uploaded_by: POC_SUBJECT_ID, created_at: new Date().toISOString(),
      }
      governanceAttachments = [...governanceAttachments, attachment]
      governanceAttachmentLocations.set(attachment.attachment_id, { upload_id: uploadId, key: stored.key })
      document.version += 1; document.updated_at = attachment.created_at
      await this.persistCore()
      return attachment
    }
    const governanceAttachmentDownloadPath = path.match(/^\/governance\/documents\/([^/]+)\/attachments\/([^/]+)\/download$/)
    if (governanceAttachmentDownloadPath && method === 'GET') {
      const documentId = decodeURIComponent(governanceAttachmentDownloadPath[1] ?? '')
      const attachmentId = decodeURIComponent(governanceAttachmentDownloadPath[2] ?? '')
      const attachment = governanceAttachments.find((item) => item.document_id === documentId && item.attachment_id === attachmentId)
      const location = governanceAttachmentLocations.get(attachmentId)
      if (!attachment || !location) throw new Error('첨부파일 저장 위치를 찾을 수 없습니다.')
      const origin = globalThis.location?.origin ?? 'http://127.0.0.1:39080'
      return {
        attachment,
        url: `${origin}/poc-api/minio/accepted/${encodeURIComponent(location.upload_id)}/${encodeURIComponent(attachment.original_name)}`,
        expires_at: new Date(Date.now() + 5 * 60 * 1000).toISOString(),
      }
    }
    const governanceDetailPath = path.match(/^\/governance\/documents\/([^/]+)$/)
    if (governanceDetailPath && method === 'GET') {
      const documentId = decodeURIComponent(governanceDetailPath[1] ?? '')
      return { item: governanceDetail(documentId), cache_scope: POC_CACHE_SCOPE, ...authorizationWindow() }
    }
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
    if (path === '/admin/systems/assignee-candidates' && method === 'GET') {
      const query = (url.searchParams.get('q') ?? '').trim().toLocaleLowerCase()
      const items = adminMemberships.flatMap((member) => {
        if (!['ENGINEER_STEWARD', 'MANAGER', 'ADMIN'].includes(member.effective_profile_role)) return []
        if (query && ![member.display_name, member.email].filter(Boolean).join(' ').toLocaleLowerCase().includes(query)) return []
        return [{
          subject_id: member.subject_id,
          display_name: member.display_name,
          email: member.email,
          tier: member.effective_profile_role,
        }]
      })
      return { items, page: { next_cursor: null, limit: 25 } }
    }
    if (path === '/admin/systems' && method === 'GET') {
      const query = (url.searchParams.get('q') ?? '').trim().toLocaleLowerCase()
      const items = adminSystems
        .filter((system) => !query || `${system.code} ${system.name}`.toLocaleLowerCase().includes(query))
        .map(pocSystemEntry)
      return { items, page: { next_cursor: null, limit: Number(url.searchParams.get('limit') ?? 25) } }
    }
    if (path === '/admin/systems' && method === 'POST') {
      const body = jsonBody(options)
      const code = responseString(body.code, '').trim()
      const name = responseString(body.name, '').trim()
      if (!/^[A-Za-z][A-Za-z0-9_-]{1,99}$/.test(code) || !name) throw new Error('유효한 시스템 코드와 이름이 필요합니다.')
      if (adminSystems.some((item) => item.code.toLocaleLowerCase() === code.toLocaleLowerCase())) throw new Error('이미 등록된 시스템 코드입니다.')
      const system = {
        system_id: nextId('system'), code, name,
        description: responseString(body.description, '').trim(),
        active: true, version: 1,
      }
      adminSystems = [...adminSystems, system]
      adminSystemAssignees.set(system.system_id, [])
      adminSystemSchemaScopes.set(system.system_id, [])
      await this.persistCore()
      return pocSystemEntry(system)
    }
    const systemAssigneePath = path.match(/^\/admin\/systems\/([^/]+)\/assignees$/)
    if (systemAssigneePath) {
      const systemId = decodeURIComponent(systemAssigneePath[1] ?? '')
      const system = adminSystems.find((item) => item.system_id === systemId)
      if (!system) throw new Error('POC 시스템을 찾을 수 없습니다.')
      if (method === 'GET') return {
        system_version: system.version,
        items: adminSystemAssignees.get(systemId) ?? [],
        page: { next_cursor: null, limit: Number(url.searchParams.get('limit') ?? 25) },
      }
      if (method === 'PATCH' || method === 'PUT') {
        const body = jsonBody(options)
        const current = [...(adminSystemAssignees.get(systemId) ?? [])]
        const removals = Array.isArray(body.removals) ? body.removals : method === 'PUT' ? current : []
        const upserts = Array.isArray(body.upserts) ? body.upserts : Array.isArray(body.assignees) ? body.assignees : []
        const removalKeys = new Set(removals.flatMap((item) => item && typeof item === 'object'
          ? [`${String((item as Record<string, unknown>).responsibility)}:${String((item as Record<string, unknown>).subject_id)}`]
          : []))
        const next = current.filter((item) => !removalKeys.has(`${item.responsibility}:${item.subject_id}`))
        for (const raw of upserts) {
          if (!raw || typeof raw !== 'object') continue
          const value = raw as Record<string, unknown>
          const subjectId = responseString(value.subject_id, '')
          const responsibility = value.responsibility === 'DATA_STEWARD' ? 'DATA_STEWARD' as const : 'DEVELOPER' as const
          const member = adminMemberships.find((item) => item.subject_id === subjectId)
          if (!member) throw new Error('등록된 POC 사용자만 시스템 담당자로 지정할 수 있습니다.')
          const assignment = { subject_id: subjectId, display_name: member.display_name, responsibility, priority: Number(value.priority) || 1, active: true }
          const index = next.findIndex((item) => item.subject_id === subjectId && item.responsibility === responsibility)
          if (index >= 0) next[index] = assignment
          else next.push(assignment)
        }
        adminSystemAssignees.set(systemId, next)
        system.version += 1
        await this.persistCore()
        return { system_id: systemId, system_version: system.version, payload_hash: 'a'.repeat(64) }
      }
    }
    const systemSchemaCandidatePath = path.match(/^\/admin\/systems\/([^/]+)\/schema-scope-candidates$/)
    if (systemSchemaCandidatePath && method === 'GET') {
      const systemId = decodeURIComponent(systemSchemaCandidatePath[1] ?? '')
      if (!adminSystems.some((item) => item.system_id === systemId)) throw new Error('POC 시스템을 찾을 수 없습니다.')
      const query = url.searchParams.get('q') ?? '*'
      const catalog = runtimeFlags().datahub
        ? await liveCatalog(new URLSearchParams({ q: query || '*', limit: '25' }), options.signal)
        : { items: [] }
      return {
        items: catalog.items.map((asset) => ({
          asset_id: asset.id, asset_name: asset.name, asset_type: 'DATASET',
          platform: asset.platform, database_name: asset.database_name, schema_name: asset.schema_name,
          classification: asset.classification,
          mapped_system_id: [...adminSystemSchemaScopes.entries()].find(([, scopes]) => scopes.some((scope) => (
            scope.active && scope.platform === asset.platform && scope.database_name === asset.database_name && scope.schema_name === asset.schema_name
          )))?.[0] ?? null,
        })),
        page: { next_cursor: null, limit: 25 },
      }
    }
    const systemSchemaPath = path.match(/^\/admin\/systems\/([^/]+)\/schema-scopes$/)
    if (systemSchemaPath) {
      const systemId = decodeURIComponent(systemSchemaPath[1] ?? '')
      const system = adminSystems.find((item) => item.system_id === systemId)
      if (!system) throw new Error('POC 시스템을 찾을 수 없습니다.')
      if (method === 'GET') return {
        system_version: system.version,
        items: adminSystemSchemaScopes.get(systemId) ?? [],
        page: { next_cursor: null, limit: 100 },
      }
      if (method === 'PATCH') {
        const body = jsonBody(options)
        const scopes = [...(adminSystemSchemaScopes.get(systemId) ?? [])]
        const deactivate = new Set(Array.isArray(body.deactivate_scope_ids) ? body.deactivate_scope_ids.map(String) : [])
        for (const scope of scopes) if (deactivate.has(scope.scope_id)) scope.active = false
        for (const assetId of Array.isArray(body.upsert_asset_ids) ? body.upsert_asset_ids.map(String) : []) {
          const detail = runtimeFlags().datahub
            ? await gatewayRequest<CatalogAssetDetail>(`/poc-api/datahub/asset?urn=${encodeURIComponent(assetId)}`, { signal: options.signal })
            : undefined
          if (!detail) continue
          const existing = scopes.find((scope) => scope.platform === detail.platform && scope.database_name === detail.database_name && scope.schema_name === detail.schema_name)
          if (existing) existing.active = true
          else scopes.push({ scope_id: nextId('system-schema'), system_id: systemId, platform: detail.platform ?? '', database_name: detail.database_name ?? '', schema_name: detail.schema_name ?? '', active: true, version: 1 })
        }
        adminSystemSchemaScopes.set(systemId, scopes)
        system.version += 1
        await this.persistCore()
        return { system_id: systemId, system_version: system.version, payload_hash: 'b'.repeat(64) }
      }
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
      const jobFunction = ['developer', 'data_steward', 'viewer', 'admin'].includes(String(body.job_function))
        ? String(body.job_function)
        : 'viewer'
      const effectiveProfileRole = jobFunction === 'admin'
        ? 'ADMIN' as const
        : jobFunction === 'viewer' ? 'VIEWER' as const : 'ENGINEER_STEWARD' as const
      const member: WorkspaceMembershipSummary = {
        ...pocAdminMembership(),
        subject_id: subjectId,
        display_name: displayName,
        email: responseString(body.email, ''),
        owned_table_count: 0,
        change_request_count: 0,
        joined_at: new Date().toISOString(),
        department_id: responseString(body.department_id, '') || null,
        job_function: jobFunction,
        effective_profile_role: effectiveProfileRole,
      }
      adminMemberships = [...adminMemberships, member]
      await this.persistCore()
      return {
        subject_id: subjectId,
        username: responseString(body.username, 'poc.user'),
        display_name: displayName,
        email: member.email,
        workspace_id: POC_WORKSPACE_ID,
        role_id: null,
        access_expires_at: new Date(Date.now() + 180 * 24 * 60 * 60 * 1000).toISOString(),
        temporary_password_required: false,
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
      chatMemory.delete(deleteMatch[1] ?? '')
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
    throw new Error(`POC live provider contract is not implemented for ${method} ${path}.`)
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
  sequence = 900
  changeRecords = []
  chatSessions = []
  uploadRecords = []
  manualSubmissionReports = []
  monitoringConfiguration = undefined
  adminMemberships = [pocAdminMembership()]
  adminSystems = []
  adminSystemAssignees.clear()
  adminSystemSchemaScopes.clear()
  knowledgeDomains = []
  knowledgeDrafts = []
  knowledgeReleases = []
  knowledgeDraftBlocks.clear()
  knowledgeDraftBindings.clear()
  governanceDocuments = []
  governanceVersions = []
  governanceReviews = []
  governanceAttachments = []
  governanceAttachmentLocations.clear()
  chatMessages.clear()
  chatMemory.clear()
  changeAttachmentUploads.clear()
  changeAttachments.clear()
  changeAttachmentLocations.clear()
  liveAssetDetails.clear()
}
