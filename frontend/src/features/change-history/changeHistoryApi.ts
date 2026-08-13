import type { ApiClient, ApiResponse } from '../../api/client'
import type {
  ChangeHistoryAccessDocument,
  ChangeHistoryAssignee,
  ChangeHistoryCategory,
  ChangeHistoryEvent,
  ChangeHistoryEventDetail,
  ChangeHistoryEventFilters,
  ChangeHistoryEventPage,
  ChangeHistoryLinkAction,
  ChangeHistoryLinkCommand,
  ChangeHistoryLinkCommandResult,
  ChangeHistoryLinkHistoryEvent,
  ChangeHistoryLinkPage,
  ChangeHistoryOperation,
  ChangeHistoryPrecision,
  ChangeHistoryReversePage,
  ChangeHistoryStage,
  ChangeHistorySummary,
  ChangeHistorySystemResolution,
  ChangeHistoryWeeklySummary,
  VersionedChangeHistoryAccess,
} from './types'

type ChangeHistoryClient = Pick<ApiClient, 'request' | 'requestWithMeta'>
type JsonRecord = Record<string, unknown>

const categories = new Set<ChangeHistoryCategory>(['TECHNICAL_SCHEMA', 'DOCUMENTATION', 'TAG', 'GLOSSARY_TERM', 'OWNERSHIP'])
const operations = new Set<ChangeHistoryOperation>(['CREATE', 'UPDATE', 'UPSERT', 'DELETE', 'ADD', 'REMOVE'])
const precisions = new Set<ChangeHistoryPrecision>(['EXACT_TIMELINE', 'EXACT_MCL', 'DRIFT_DETECTED', 'BACKFILLED_BEST_EFFORT', 'INITIAL_BASELINE'])
const stages = new Set<ChangeHistoryStage>(['UNLINKED', 'RECEIVED', 'RECHECK', 'TESTING', 'FINAL_REVIEW', 'COMPLETED'])
const actions = new Set<ChangeHistoryLinkAction>(['SET_PRIMARY', 'CLEAR_PRIMARY', 'ADD_CANDIDATE', 'REMOVE_CANDIDATE'])
const syncStates = new Set<ChangeHistorySummary['sync_status']>([
  'SOURCE_NOT_CONFIGURED', 'SOURCE_AMBIGUOUS', 'CHECKPOINT_NOT_AVAILABLE',
  'CHECKPOINT_INVALID', 'CAPTURE_PENDING', 'CONTIGUOUS_CAPTURE_RECORDED',
])

export class ChangeHistoryApi {
  constructor(private readonly client: ChangeHistoryClient) {}

  async summary(weekStart: string, signal?: AbortSignal): Promise<ChangeHistorySummary> {
    const value = await this.client.request<ChangeHistorySummary>(
      `/change-history/summary?week_start=${encodeURIComponent(weekStart)}`,
      { cache: 'no-store', signal },
    )
    assertSummary(value, weekStart)
    return value
  }

  async weekly(weekStart: string, signal?: AbortSignal): Promise<ChangeHistoryWeeklySummary> {
    const value = await this.client.request<ChangeHistoryWeeklySummary>(
      `/change-history/weekly?week_start=${encodeURIComponent(weekStart)}`,
      { cache: 'no-store', signal },
    )
    assertWeekly(value, weekStart)
    return value
  }

  async events(filters: ChangeHistoryEventFilters = {}, signal?: AbortSignal): Promise<ChangeHistoryEventPage> {
    const limit = filters.limit ?? 50
    if (!integerBetween(limit, 1, 100)
      || (filters.precision !== undefined && !precisions.has(filters.precision))) invalid()
    const parameters = new URLSearchParams({ limit: String(limit) })
    setParameter(parameters, 'week_start', filters.weekStart)
    setParameter(parameters, 'change_type', filters.changeType)
    setParameter(parameters, 'category', filters.category)
    setParameter(parameters, 'precision', filters.precision)
    setParameter(parameters, 'operation', filters.operation)
    setParameter(parameters, 'platform', filters.platform)
    setParameter(parameters, 'database_name', filters.databaseName)
    setParameter(parameters, 'schema_name', filters.schemaName)
    setParameter(parameters, 'system_id', filters.systemId)
    setParameter(parameters, 'assignee_subject_id', filters.assigneeSubjectId)
    setParameter(parameters, 'link_state', filters.linkState)
    setParameter(parameters, 'stage', filters.stage)
    setParameter(parameters, 'cursor', filters.cursor)
    const value = await this.client.request<ChangeHistoryEventPage>(
      `/change-history/events?${parameters.toString()}`,
      { cache: 'no-store', signal },
    )
    assertEventPage(value, limit, filters.cursor)
    return value
  }

  async event(eventId: string, signal?: AbortSignal): Promise<ApiResponse<ChangeHistoryEventDetail>> {
    assertEventIdentifier(eventId)
    const response = await this.client.requestWithMeta<ChangeHistoryEventDetail>(
      `/change-history/events/${encodeURIComponent(eventId)}`,
      { cache: 'no-store', signal },
    )
    assertEvent(response.data, true)
    assertLinkEtag(response.etag)
    return response
  }

  async links(
    eventId: string,
    options: { cursor?: string; limit?: number; signal?: AbortSignal } = {},
  ): Promise<ApiResponse<ChangeHistoryLinkPage>> {
    assertEventIdentifier(eventId)
    const limit = options.limit ?? 50
    if (!integerBetween(limit, 1, 100)) invalid()
    const parameters = new URLSearchParams({ limit: String(limit) })
    setParameter(parameters, 'cursor', options.cursor)
    const response = await this.client.requestWithMeta<ChangeHistoryLinkPage>(
      `/change-history/events/${encodeURIComponent(eventId)}/cr-links?${parameters.toString()}`,
      { cache: 'no-store', signal: options.signal },
    )
    assertLinkPage(response.data, limit, options.cursor)
    assertLinkEtag(response.etag)
    return response
  }

  async reverseHistory(
    changeRequestId: string,
    options: { cursor?: string; limit?: number; signal?: AbortSignal } = {},
  ): Promise<ChangeHistoryReversePage> {
    assertIdentifier(changeRequestId, 200)
    const limit = options.limit ?? 50
    if (!integerBetween(limit, 1, 100)) invalid()
    const parameters = new URLSearchParams({ limit: String(limit) })
    setParameter(parameters, 'cursor', options.cursor)
    const value = await this.client.request<ChangeHistoryReversePage>(
      `/change-requests/${encodeURIComponent(changeRequestId)}/change-history?${parameters.toString()}`,
      { cache: 'no-store', signal: options.signal },
    )
    if (!isRecord(value) || value.change_request_id !== changeRequestId) invalid()
    assertPage(value, limit, options.cursor)
    value.items.forEach((item) => assertEvent(item))
    return value
  }

  async access(signal?: AbortSignal): Promise<VersionedChangeHistoryAccess> {
    const response = await this.client.requestWithMeta<ChangeHistoryAccessDocument & { version: number }>(
      '/change-history/access',
      { cache: 'no-store', signal },
    )
    assertAccess(response.data)
    const etag = quotedVersion(response.data.version)
    if (response.etag !== etag) invalid()
    return { ...response.data, etag }
  }

  async updateAccess(
    document: ChangeHistoryAccessDocument,
    etag: string,
    signal?: AbortSignal,
  ): Promise<VersionedChangeHistoryAccess> {
    assertAccess(document)
    if (!/^"(?:0|[1-9]\d*)"$/.test(etag)) invalid()
    const response = await this.client.requestWithMeta<ChangeHistoryAccessDocument & { version: number }>(
      '/change-history/access',
      { method: 'PUT', cache: 'no-store', signal, ifMatch: etag, body: JSON.stringify(document) },
    )
    assertAccess(response.data)
    const responseEtag = quotedVersion(response.data.version)
    if (response.etag !== responseEtag) invalid()
    return { ...response.data, etag: responseEtag }
  }

  async linkEvent(
    eventId: string,
    command: ChangeHistoryLinkCommand,
    etag: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<ApiResponse<ChangeHistoryLinkCommandResult>> {
    assertEventIdentifier(eventId)
    if (!actions.has(command.action) || !positiveInteger(command.change_request_round)
      || !bounded(command.change_request_id, 200) || !bounded(command.reason, 2_000)
      || !bounded(idempotencyKey, 200)) invalid()
    assertLinkEtag(etag)
    const response = await this.client.requestWithMeta<ChangeHistoryLinkCommandResult>(
      `/change-history/events/${encodeURIComponent(eventId)}/cr-link-events`,
      {
        method: 'POST', cache: 'no-store', signal, ifMatch: etag,
        idempotencyKey, body: JSON.stringify(command),
      },
    )
    assertLinkCommandResult(response.data, eventId, command)
    if (response.etag !== `"${response.data.event_hash}"`) invalid()
    return response
  }
}

function setParameter(parameters: URLSearchParams, name: string, value?: string) {
  if (value !== undefined) {
    if (!bounded(value, 2_000)) invalid()
    parameters.set(name, value)
  }
}

function assertEventPage(
  value: unknown,
  expectedLimit: number,
  requestedCursor?: string,
): asserts value is ChangeHistoryEventPage {
  assertPage(value, expectedLimit, requestedCursor, true)
  value.items.forEach((item) => assertEvent(item))
}

function assertPage(value: unknown, expectedLimit: number, requestedCursor?: string, totalRequired = false): asserts value is {
  items: unknown[]; next_cursor: string | null; limit: number; total?: number; [key: string]: unknown
} {
  if (!isRecord(value) || !Array.isArray(value.items) || value.items.length > 100
    || !integerBetween(value.limit, 1, 100) || value.limit !== expectedLimit || value.items.length > value.limit
    || !(value.next_cursor === null || bounded(value.next_cursor, 2_000))
    || (value.next_cursor !== null && value.items.length !== value.limit)
    || (requestedCursor !== undefined && value.next_cursor === requestedCursor)
    || (totalRequired && (!nonNegativeInteger(value.total) || Number(value.total) < value.items.length))
    || (totalRequired && requestedCursor === undefined
      && ((Number(value.total) > value.items.length) !== (value.next_cursor !== null)))) invalid()
}

function assertEvent(value: unknown, detail = false): asserts value is ChangeHistoryEvent | ChangeHistoryEventDetail {
  if (!isRecord(value)
    || !sha(value.event_id) || !sha(value.transaction_id)
    || !bounded(value.asset_urn, 4_096) || !bounded(value.entity_key, 1_000)
    || !categories.has(value.category as ChangeHistoryCategory)
    || !['SCHEMA_CHANGE', 'METADATA_CHANGE'].includes(String(value.change_type))
    || ((value.category === 'TECHNICAL_SCHEMA' && value.source_aspect === 'schemaMetadata')
      !== (value.change_type === 'SCHEMA_CHANGE'))
    || !bounded(value.source_aspect, 100)
    || !operations.has(value.operation as ChangeHistoryOperation)
    || !(value.precision === null || precisions.has(value.precision as ChangeHistoryPrecision))
    || !nullableTimestamp(value.source_occurred_at) || !timestamp(value.detected_at) || !timestamp(value.captured_at)
    || !nonNegativeInteger(value.link_version)
    || !stages.has(value.current_stage as ChangeHistoryStage)
    || !Array.isArray(value.allowed_link_actions) || value.allowed_link_actions.length > actions.size
    || value.allowed_link_actions.some((action) => !actions.has(action as ChangeHistoryLinkAction))
    || new Set(value.allowed_link_actions).size !== value.allowed_link_actions.length
    || !Array.isArray(value.current_candidates) || value.current_candidates.length > 100) invalid()
  assertSystem(value.system)
  assertAssignee(value.assignee)
  assertLocator(value.locator)
  assertCrLink(value.current_primary)
  value.current_candidates.forEach(assertCrLink)
  if (detail && (!Object.hasOwn(value, 'before') || !Object.hasOwn(value, 'after')
    || !boundedObject(value.before) || !boundedObject(value.after))) invalid()
}

function assertSystem(value: unknown): asserts value is ChangeHistorySystemResolution {
  if (!isRecord(value) || !['RESOLVED', 'UNMAPPED', 'AMBIGUOUS'].includes(String(value.resolution))
    || !(value.system_id === null || bounded(value.system_id, 255))) invalid()
  if (value.provider_context !== null) {
    if (!isRecord(value.provider_context) || !bounded(value.provider_context.platform, 100)
      || !bounded(value.provider_context.database_name, 255) || !bounded(value.provider_context.schema_name, 255)) invalid()
  }
}

function assertLocator(value: unknown) {
  if (value === null) return
  if (!isRecord(value) || !bounded(value.platform, 100) || !bounded(value.database_name, 255)
    || !bounded(value.schema_name, 255) || !(value.asset_name === null || bounded(value.asset_name, 255))) invalid()
}

function assertAssignee(value: unknown): asserts value is ChangeHistoryAssignee {
  if (!isRecord(value) || !(value.subject_id === null || bounded(value.subject_id, 255))
    || !['DATA_STEWARD', 'DEVELOPER', 'UNASSIGNED'].includes(String(value.responsibility))
    || !(value.system_id === null || bounded(value.system_id, 255))
    || !(value.priority === null || positiveInteger(value.priority))
    || value.basis !== 'CURRENT_POC_PROJECTION') invalid()
}

function assertCrLink(value: unknown) {
  if (value === null) return
  if (!isRecord(value) || !bounded(value.change_request_id, 200) || !positiveInteger(value.change_request_round)) invalid()
}

function assertWeekly(value: unknown, expectedWeekStart: string): asserts value is ChangeHistoryWeeklySummary {
  if (!isRecord(value) || value.week_start !== expectedWeekStart || value.timezone !== 'Asia/Seoul'
    || !/^\d{4}-\d{2}-\d{2}$/.test(String(value.week_end_exclusive)) || !timestamp(value.as_of)
    || !positiveInteger(value.policy_version) || !sha(value.policy_hash)
    || value.count_unit !== 'DISTINCT_NORMALIZED_CHANGE_TRANSACTION') invalid()
  const counts = ['total_count', 'unlinked_count', 'received_count', 'recheck_count', 'testing_count',
    'final_review_count', 'completed_count', 'time_unknown_count'] as const
  if (counts.some((field) => !nonNegativeInteger(value[field]))) invalid()
  if (Number(value.total_count) !== Number(value.unlinked_count) + Number(value.received_count) + Number(value.recheck_count)
    + Number(value.testing_count) + Number(value.final_review_count) + Number(value.completed_count)) invalid()
}

function assertSummary(value: unknown, expectedWeekStart: string): asserts value is ChangeHistorySummary {
  assertWeekly(value, expectedWeekStart)
  const candidate = value as unknown as JsonRecord
  if (!nonNegativeInteger(candidate.schema_change_count) || !nonNegativeInteger(candidate.metadata_change_count)
    || !nonNegativeInteger(candidate.event_count) || !nonNegativeInteger(candidate.distinct_asset_count)
    || !syncStates.has(candidate.capture_state as ChangeHistorySummary['sync_status'])
    || candidate.sync_status !== candidate.capture_state
    || !sha(candidate.source_generation) || !timestamp(candidate.source_observed_at)
    || !nullableTimestamp(candidate.source_occurred_at) || !nullableTimestamp(candidate.detected_at)
    || !nullableTimestamp(candidate.captured_at) || candidate.effective_week_start !== expectedWeekStart
    || !nullableTimestamp(candidate.history_available_from) || !nullableTimestamp(candidate.ledger_guarantee_from)
    || !nullableTimestamp(candidate.first_exact_capture_at) || !nullableTimestamp(candidate.first_timeline_checkpoint)
    || !nullableTimestamp(candidate.last_successful_capture_at)) invalid()
  assertCountRecord(candidate.precision_counts, precisions)
  assertCountRecord(candidate.category_counts, categories)
  assertCountRecord(candidate.operation_counts, operations)
  if (candidate.first_mcl_offsets !== null && (!Array.isArray(candidate.first_mcl_offsets)
    || candidate.first_mcl_offsets.length > 1_000
    || candidate.first_mcl_offsets.some((item: unknown) => !isRecord(item)
      || !nonNegativeInteger(item.partition) || !nonNegativeInteger(item.offset)))) invalid()
}

function assertCountRecord<T extends string>(value: unknown, allowed: Set<T>) {
  if (!isRecord(value) || Object.keys(value).length !== allowed.size
    || [...allowed].some((key) => !nonNegativeInteger(value[key]))) invalid()
}

function assertLinkPage(value: unknown, expectedLimit: number, requestedCursor?: string): asserts value is ChangeHistoryLinkPage {
  assertPage(value, expectedLimit, requestedCursor)
  if (!isRecord(value) || !Array.isArray(value.current_candidates) || value.current_candidates.length > 100) invalid()
  assertCrLink(value.current_primary)
  value.current_candidates.forEach(assertCrLink)
  value.items.forEach(assertLinkHistoryEvent)
}

function assertLinkHistoryEvent(value: unknown): asserts value is ChangeHistoryLinkHistoryEvent {
  if (!isRecord(value) || !sha(value.link_event_identity) || !sha(value.event_hash)
    || !sha(value.ledger_event_identity) || !positiveInteger(value.link_version)
    || !['PRIMARY', 'CANDIDATE'].includes(String(value.link_kind))
    || !actions.has(value.action as ChangeHistoryLinkAction)
    || ((value.link_kind === 'PRIMARY') !== ['SET_PRIMARY', 'CLEAR_PRIMARY'].includes(String(value.action)))
    || !bounded(value.change_request_id, 200) || !positiveInteger(value.change_request_round)
    || !(value.prior_link_hash === null || sha(value.prior_link_hash))
    || !bounded(value.reason, 2_000) || !sha(value.policy_hash) || !sha(value.basis_hash)
    || !bounded(value.actor_ref, 1_000) || !timestamp(value.occurred_at) || !timestamp(value.captured_at)) invalid()
}

function assertLinkCommandResult(value: unknown, eventId: string, command: ChangeHistoryLinkCommand) {
  if (!isRecord(value) || !sha(value.link_event_identity) || !sha(value.event_hash)
    || !positiveInteger(value.link_version) || typeof value.replayed !== 'boolean'
    || value.event_id !== eventId || value.change_request_id !== command.change_request_id
    || value.change_request_round !== command.change_request_round || value.action !== command.action) invalid()
}

function assertAccess(value: unknown): asserts value is ChangeHistoryAccessDocument & { version?: number } {
  if (!isRecord(value) || value.schema_version !== 1 || !bounded(value.active_subject_id, 255)
    || !isRecord(value.policy) || value.policy.version !== 1 || value.policy.priority_order !== 'ASCENDING'
    || JSON.stringify(value.policy.fallback) !== JSON.stringify(['DATA_STEWARD', 'DEVELOPER', 'DATAHUB_OWNER', 'UNASSIGNED'])
    || !boundedArray(value.users, 500) || !boundedArray(value.systems, 500)
    || !boundedArray(value.system_schema_scopes, 2_000) || !boundedArray(value.system_assignments, 2_000)
    || (Object.hasOwn(value, 'version') && !nonNegativeInteger(value.version))) invalid()
  value.users.forEach((item) => {
    if (!isRecord(item) || !bounded(item.subject_id, 255)
      || !['admin', 'data_steward', 'developer', 'viewer'].includes(String(item.role))
      || typeof item.active !== 'boolean' || !boundedArray(item.provider_owner_refs, 100)
      || item.provider_owner_refs.some((owner) => !bounded(owner, 1_024))) invalid()
  })
  value.systems.forEach((item) => {
    if (!isRecord(item) || !bounded(item.system_id, 255) || !bounded(item.code, 100)
      || !bounded(item.name, 255) || typeof item.description !== 'string' || item.description.length > 2_000
      || typeof item.active !== 'boolean' || !positiveInteger(item.version)) invalid()
  })
  value.system_schema_scopes.forEach((item) => {
    if (!isRecord(item) || !bounded(item.scope_id, 255) || !bounded(item.system_id, 255)
      || !bounded(item.platform, 100) || !bounded(item.database_name, 255) || !bounded(item.schema_name, 255)
      || typeof item.active !== 'boolean' || !positiveInteger(item.version)) invalid()
  })
  value.system_assignments.forEach((item) => {
    if (!isRecord(item) || !bounded(item.system_id, 255) || !bounded(item.subject_id, 255)
      || !['DATA_STEWARD', 'DEVELOPER'].includes(String(item.responsibility))
      || !positiveInteger(item.priority) || typeof item.active !== 'boolean') invalid()
  })
}

function quotedVersion(value: unknown) {
  if (!nonNegativeInteger(value)) invalid()
  return `"${value}"`
}

function assertLinkEtag(value: unknown): asserts value is string {
  if (typeof value !== 'string' || !/^"(?:0|[0-9a-f]{64})"$/.test(value)) invalid()
}

function assertIdentifier(value: string, maximum: number) {
  if (!bounded(value, maximum)) invalid()
}

function assertEventIdentifier(value: string) {
  if (!sha(value)) invalid()
}

function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function boundedArray(value: unknown, maximum: number): value is unknown[] {
  return Array.isArray(value) && value.length <= maximum
}

function bounded(value: unknown, maximum: number): value is string {
  return typeof value === 'string' && value.trim().length > 0 && value.length <= maximum
    && ![...value].some((character) => {
      const code = character.codePointAt(0) ?? 0
      return code <= 0x1f || code === 0x7f
    })
}

function boundedObject(value: unknown) {
  return value === null || (isRecord(value) && JSON.stringify(value).length <= 16_384)
}

function sha(value: unknown): value is string {
  return typeof value === 'string' && /^[0-9a-f]{64}$/.test(value)
}

function timestamp(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(value)) return false
  const parsed = new Date(value)
  return Number.isFinite(parsed.getTime()) && parsed.toISOString() === value
}

function nullableTimestamp(value: unknown): value is string | null {
  return value === null || timestamp(value)
}

function positiveInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) > 0
}

function nonNegativeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0
}

function integerBetween(value: unknown, minimum: number, maximum: number): value is number {
  return Number.isSafeInteger(value) && Number(value) >= minimum && Number(value) <= maximum
}

function invalid(): never {
  throw new Error('변경 이력 서버 응답이 검증된 계약과 일치하지 않습니다.')
}
