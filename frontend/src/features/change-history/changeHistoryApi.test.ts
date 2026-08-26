import { describe, expect, it, vi } from 'vitest'
import type { ApiClient, RequestOptions } from '../../api/client'
import { ChangeHistoryApi } from './changeHistoryApi'
import type { ChangeHistoryAccessDocument, ChangeHistoryLinkCommand } from './types'

const eventId = '1'.repeat(64)
const transactionId = '2'.repeat(64)
const eventHash = '3'.repeat(64)
const weekStart = '2026-08-10'
const timestamp = '2026-08-11T01:00:00.000Z'

describe('ChangeHistoryApi', () => {
  it('requests server-filtered pages and validates weekly and source summaries', async () => {
    const request = vi.fn((path: string) => {
      if (path.startsWith('/change-history/events?')) return Promise.resolve({
        items: [event()], next_cursor: null, limit: 25, total: 1,
        empty_state_reason: null, empty_state_detail: null,
      })
      if (path.startsWith('/change-history/weekly?')) return Promise.resolve(weekly())
      if (path.startsWith('/change-history/summary?')) return Promise.resolve(summary())
      throw new Error(`Unexpected path: ${path}`)
    })
    const api = new ChangeHistoryApi({
      request: request as unknown as ApiClient['request'],
      requestWithMeta: vi.fn(),
    })

    const page = await api.events({
      weekStart, changeType: 'SCHEMA_CHANGE', category: 'TECHNICAL_SCHEMA', precision: 'EXACT_MCL', operation: 'UPDATE',
      platform: 'postgres', databaseName: 'business_db', schemaName: 'public',
      systemId: 'system-1', assigneeSubjectId: 'steward-1', linkState: 'UNLINKED',
      stage: 'UNLINKED', limit: 25,
    })
    expect(page.total).toBe(1)
    expect(String(request.mock.calls[0]?.[0])).toContain('week_start=2026-08-10')
    expect(String(request.mock.calls[0]?.[0])).toContain('precision=EXACT_MCL')
    expect(String(request.mock.calls[0]?.[0])).toContain('stage=UNLINKED')
    expect((await api.weekly(weekStart)).total_count).toBe(1)
    expect((await api.summary(weekStart)).sync_status).toBe('CONTIGUOUS_CAPTURE_RECORDED')
  })

  it('requires exact ETags for detail, link history and access documents', async () => {
    const request = vi.fn((path: string) => {
      if (path.startsWith('/change-requests/')) return Promise.resolve({
        change_request_id: 'cr-1', items: [event()], next_cursor: null, limit: 50,
      })
      throw new Error(`Unexpected path: ${path}`)
    })
    const requestWithMeta = vi.fn((path: string) => {
      if (path === `/change-history/events/${eventId}`) return Promise.resolve({
        data: { ...event(), before: { nullable: true }, after: { nullable: false } }, etag: '"0"',
      })
      if (path.startsWith(`/change-history/events/${eventId}/cr-links?`)) return Promise.resolve({
        data: {
          current_primary: null, current_candidates: [], items: [linkHistory()], next_cursor: null, limit: 50,
        },
        etag: `"${eventHash}"`,
      })
      if (path === '/change-history/access') return Promise.resolve({
        data: { ...access(), version: 3 }, etag: '"3"',
      })
      throw new Error(`Unexpected path: ${path}`)
    })
    const api = new ChangeHistoryApi({
      request: request as unknown as ApiClient['request'],
      requestWithMeta: requestWithMeta as unknown as ApiClient['requestWithMeta'],
    })

    expect((await api.event(eventId)).etag).toBe('"0"')
    expect((await api.links(eventId)).data.items[0]?.action).toBe('SET_PRIMARY')
    expect((await api.reverseHistory('cr-1')).items).toHaveLength(1)
    expect((await api.access()).etag).toBe('"3"')
  })

  it('sends link idempotency and If-Match and access CAS without inventing authority fields', async () => {
    const calls: Array<[string, RequestOptions]> = []
    const command: ChangeHistoryLinkCommand = {
      action: 'SET_PRIMARY', change_request_id: 'cr-1', change_request_round: 1, reason: 'reviewed',
    }
    const requestWithMeta = vi.fn((path: string, options: RequestOptions = {}) => {
      calls.push([path, options])
      if (path.endsWith('/cr-link-events')) return Promise.resolve({
        data: {
          link_event_identity: '4'.repeat(64), event_hash: eventHash, link_version: 1,
          replayed: false, event_id: eventId, change_request_id: 'cr-1',
          change_request_round: 1, action: 'SET_PRIMARY',
        },
        etag: `"${eventHash}"`,
      })
      return Promise.resolve({ data: { ...access(), version: 4 }, etag: '"4"' })
    })
    const api = new ChangeHistoryApi({
      request: vi.fn(),
      requestWithMeta: requestWithMeta as unknown as ApiClient['requestWithMeta'],
    })

    await api.linkEvent(eventId, command, '"0"', 'link-key')
    await api.updateAccess(access(), '"3"')

    expect(calls[0]).toEqual([
      `/change-history/events/${eventId}/cr-link-events`,
      expect.objectContaining({
        method: 'POST', ifMatch: '"0"', idempotencyKey: 'link-key', body: JSON.stringify(command),
      }),
    ])
    expect(calls[1]?.[0]).toBe('/change-history/access')
    expect(calls[1]?.[1]).toEqual(expect.objectContaining({ method: 'PUT', ifMatch: '"3"' }))
    const accessBody = calls[1]?.[1].body
    expect(typeof accessBody).toBe('string')
    expect(JSON.parse(typeof accessBody === 'string' ? accessBody : '')).not.toHaveProperty('version')
  })

  it.each(['1', '2026-08-11', '08/11/2026'])('rejects non-canonical UTC timestamp %s on every response surface', async (malformed) => {
    const eventApi = new ChangeHistoryApi({
      request: vi.fn().mockResolvedValue({
        items: [{ ...event(), detected_at: malformed }], next_cursor: null, limit: 50, total: 1,
      }),
      requestWithMeta: vi.fn(),
    })
    await expect(eventApi.events()).rejects.toThrow('검증된 계약')

    const weeklyApi = new ChangeHistoryApi({
      request: vi.fn().mockResolvedValue({ ...weekly(), as_of: malformed }),
      requestWithMeta: vi.fn(),
    })
    await expect(weeklyApi.weekly(weekStart)).rejects.toThrow('검증된 계약')

    const summaryApi = new ChangeHistoryApi({
      request: vi.fn().mockResolvedValue({ ...summary(), source_observed_at: malformed }),
      requestWithMeta: vi.fn(),
    })
    await expect(summaryApi.summary(weekStart)).rejects.toThrow('검증된 계약')

    const linkApi = new ChangeHistoryApi({
      request: vi.fn(),
      requestWithMeta: vi.fn().mockResolvedValue({
        data: {
          current_primary: null, current_candidates: [],
          items: [{ ...linkHistory(), occurred_at: malformed }], next_cursor: null, limit: 50,
        },
        etag: `"${eventHash}"`,
      }),
    })
    await expect(linkApi.links(eventId)).rejects.toThrow('검증된 계약')
  })

  it('fails closed on page overflow, cursor inconsistency, and unsupported precision before transport', async () => {
    const request = vi.fn().mockResolvedValue({
      items: [event(), event()], next_cursor: 'next', limit: 1, total: 2,
    })
    const api = new ChangeHistoryApi({
      request,
      requestWithMeta: vi.fn(),
    })
    await expect(api.events({ limit: 1 })).rejects.toThrow('검증된 계약')

    request.mockResolvedValueOnce({ items: [event()], next_cursor: 'next', limit: 2, total: 1 })
    await expect(api.events({ limit: 2 })).rejects.toThrow('검증된 계약')

    await expect(api.events({ precision: 'GUESSED' as 'EXACT_MCL' })).rejects.toThrow('검증된 계약')
    await expect(api.events({ dateFrom: '2026-08-12', dateTo: '2026-08-11' })).rejects.toThrow('검증된 계약')
    expect(request).toHaveBeenCalledTimes(2)
  })

  it('fails closed on malformed enums, counts and response ETags', async () => {
    const malformedEvent = { ...event(), precision: 'GUESSED' }
    const api = new ChangeHistoryApi({
      request: vi.fn().mockResolvedValue({ items: [malformedEvent], next_cursor: null, limit: 50, total: 1 }),
      requestWithMeta: vi.fn().mockResolvedValue({ data: { ...event(), before: {}, after: {} } }),
    })
    await expect(api.events()).rejects.toThrow('검증된 계약')
    await expect(api.event(eventId)).rejects.toThrow('검증된 계약')

    const summaryApi = new ChangeHistoryApi({
      request: vi.fn().mockResolvedValue({ ...summary(), completed_count: 2 }),
      requestWithMeta: vi.fn(),
    })
    await expect(summaryApi.summary(weekStart)).rejects.toThrow('검증된 계약')
  })

  it('decodes exact lifecycle events and requires the lifecycle summary zero-count key', async () => {
    const lifecycle = {
      ...event(), category: 'LIFECYCLE', change_type: 'METADATA_CHANGE', source_aspect: 'status', operation: 'DELETE',
      entity_key: 'asset:lifecycle:removed',
    }
    const api = new ChangeHistoryApi({
      request: vi.fn().mockResolvedValue({
        items: [lifecycle], next_cursor: null, limit: 50, total: 1,
        empty_state_reason: null, empty_state_detail: null,
      }),
      requestWithMeta: vi.fn().mockResolvedValue({ data: { ...lifecycle, before: { removed: false }, after: { removed: true } }, etag: '"0"' }),
    })
    expect((await api.events({ category: 'LIFECYCLE' })).items[0]?.source_aspect).toBe('status')
    expect((await api.event(eventId)).data.after).toEqual({ removed: true })
    const missingCountApi = new ChangeHistoryApi({
      request: vi.fn().mockResolvedValue({ ...summary(), category_counts: { ...summary().category_counts, LIFECYCLE: undefined } }),
      requestWithMeta: vi.fn(),
    })
    await expect(missingCountApi.summary(weekStart)).rejects.toThrow('검증된 계약')
  })
})

function event() {
  return {
    event_id: eventId,
    transaction_id: transactionId,
    asset_urn: 'urn:li:dataset:orders',
    entity_key: 'business_db.public.orders',
    category: 'TECHNICAL_SCHEMA',
    change_type: 'SCHEMA_CHANGE',
    source_aspect: 'schemaMetadata',
    operation: 'UPDATE',
    target_kind: 'COLUMN',
    field_name: 'customer_id',
    presentation_change_type: 'COLUMN_CHANGE',
    change_summary: 'UPDATE · TECHNICAL_SCHEMA',
    change_detail: [{ field: 'NULLABLE', before: 'true', after: 'false' }],
    precision: 'EXACT_MCL',
    source_occurred_at: timestamp,
    detected_at: timestamp,
    captured_at: timestamp,
    system: {
      resolution: 'RESOLVED', system_id: 'system-1',
      provider_context: { platform: 'postgres', database_name: 'business_db', schema_name: 'public' },
    },
    locator: { platform: 'postgres', database_name: 'business_db', schema_name: 'public', asset_name: 'orders' },
    assignee: {
      subject_id: 'steward-1', responsibility: 'DATA_STEWARD', system_id: 'system-1',
      priority: 1, basis: 'CURRENT_POC_PROJECTION',
    },
    current_stage: 'UNLINKED',
    allowed_link_actions: ['SET_PRIMARY', 'CLEAR_PRIMARY', 'ADD_CANDIDATE', 'REMOVE_CANDIDATE'],
    current_primary: null,
    current_candidates: [],
    link_version: 0,
  }
}

function weekly() {
  return {
    week_start: weekStart,
    week_end_exclusive: '2026-08-17',
    timezone: 'Asia/Seoul',
    as_of: timestamp,
    policy_version: 1,
    policy_hash: '5'.repeat(64),
    count_unit: 'DISTINCT_NORMALIZED_CHANGE_TRANSACTION',
    total_count: 1,
    unlinked_count: 1,
    received_count: 0,
    recheck_count: 0,
    testing_count: 0,
    final_review_count: 0,
    completed_count: 0,
    time_unknown_count: 0,
  }
}

function summary() {
  return {
    ...weekly(),
    schema_change_count: 1,
    metadata_change_count: 0,
    event_count: 1,
    distinct_asset_count: 1,
    precision_counts: {
      EXACT_TIMELINE: 0, EXACT_MCL: 1, DRIFT_DETECTED: 0, BACKFILLED_BEST_EFFORT: 0, INITIAL_BASELINE: 0,
    },
    category_counts: { TECHNICAL_SCHEMA: 1, DOCUMENTATION: 0, TAG: 0, GLOSSARY_TERM: 0, DOMAIN: 0, OWNERSHIP: 0, LIFECYCLE: 0 },
    operation_counts: { CREATE: 0, UPDATE: 1, UPSERT: 0, DELETE: 0, ADD: 0, REMOVE: 0 },
    capture_state: 'CONTIGUOUS_CAPTURE_RECORDED',
    sync_status: 'CONTIGUOUS_CAPTURE_RECORDED',
    source_generation: '6'.repeat(64),
    source_observed_at: timestamp,
    source_occurred_at: timestamp,
    detected_at: timestamp,
    captured_at: timestamp,
    effective_week_start: weekStart,
    history_available_from: timestamp,
    ledger_guarantee_from: timestamp,
    first_exact_capture_at: timestamp,
    first_timeline_checkpoint: null,
    first_mcl_offsets: [{ partition: 0, offset: 10 }],
    last_successful_capture_at: timestamp,
  }
}

function linkHistory() {
  return {
    link_event_identity: '4'.repeat(64),
    event_hash: eventHash,
    ledger_event_identity: eventId,
    link_version: 1,
    link_kind: 'PRIMARY',
    action: 'SET_PRIMARY',
    change_request_id: 'cr-1',
    change_request_round: 1,
    prior_link_hash: null,
    reason: 'reviewed',
    policy_hash: '5'.repeat(64),
    basis_hash: '6'.repeat(64),
    actor_ref: 'steward-1',
    occurred_at: timestamp,
    captured_at: timestamp,
  }
}

function access(): ChangeHistoryAccessDocument {
  return {
    schema_version: 1,
    active_subject_id: 'admin-1',
    policy: {
      version: 1, priority_order: 'ASCENDING',
      fallback: ['DATA_STEWARD', 'DEVELOPER', 'DATAHUB_OWNER', 'UNASSIGNED'],
    },
    users: [{ subject_id: 'admin-1', role: 'admin', active: true, provider_owner_refs: [] }],
    systems: [{ system_id: 'system-1', code: 'ONE', name: 'One', description: '', active: true, version: 1 }],
    system_schema_scopes: [{
      scope_id: 'scope-1', system_id: 'system-1', platform: 'postgres', database_name: 'business_db',
      schema_name: 'public', active: true, version: 1,
    }],
    system_assignments: [],
  }
}
