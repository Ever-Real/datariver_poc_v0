import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient, RequestOptions } from '../../api/client'
import type { ChangeHistoryEvent } from '../change-history/types'
import { DataChangeStatusPanel } from './DataChangeStatusPanel'

const eventId = '1'.repeat(64)
const transactionId = '2'.repeat(64)
const timestamp = '2026-08-11T01:00:00.000Z'

describe('DataChangeStatusPanel', () => {
  it('keeps valid zero counts distinct from source state and an empty event page', async () => {
    const request = vi.fn((path: string) => responseFor(path, {
      summary: summaryFor(path, { capture_state: 'SOURCE_NOT_CONFIGURED', sync_status: 'SOURCE_NOT_CONFIGURED' }),
      page: eventPage([]),
    }))
    render(<DataChangeStatusPanel client={clientFor(request)} />)

    expect(await screen.findByText('변경 이력이 없습니다.')).toBeInTheDocument()
    const facts = screen.getByLabelText('변경 이력 원장 상태')
    expect(within(facts).getByText('Schema Change').parentElement).toHaveTextContent('0')
    expect(within(facts).getByText('Metadata Change').parentElement).toHaveTextContent('0')
    expect(within(facts).getAllByText('소스 미구성')).toHaveLength(2)
    expect(within(facts).getAllByText('기록 없음')).toHaveLength(3)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows only bounded MCL rejection shape diagnostics for a failed capture', async () => {
    const request = vi.fn((path: string) => responseFor(path, {
      summary: summaryFor(path, {
        capture_state: 'CAPTURE_FAILED',
        sync_status: 'CAPTURE_FAILED',
        capture_failure_classification: 'PREP_MCL_CAPTURE_RECORD_CONTRACT_FAILED',
        capture_failure_stage: 'RECORD_NORMALIZATION',
        capture_failure_detail_code: 'CREATED_TIME_INVALID',
        capture_failure_record_shape: {
          contract: 'DATARIVER_MCL_REJECTED_RECORD_SHAPE_V1',
          partition: 0,
          offset: 17,
          entity_type: 'dataset',
          aspect_name: 'schemaMetadata',
          change_type: 'UPSERT',
          aspect_present: true,
          previous_aspect_value_present: false,
          aspect_content_type: 'APPLICATION_JSON',
          previous_aspect_content_type: 'MISSING',
          created_type: 'OBJECT',
          created_time_type: 'NUMBER',
          created_time_representation: 'NUMBER',
          created_actor_type: 'STRING',
          current_aspect_decoded_object: true,
          previous_aspect_decoded_object: false,
          current_collection_item_count: 12,
          previous_collection_item_count: null,
          rejection_locus: 'CREATED_TIME_INVALID',
        },
      }),
      page: eventPage([]),
    }))
    render(<DataChangeStatusPanel client={clientFor(request)} />)

    const facts = await screen.findByLabelText('변경 이력 원장 상태')
    expect(within(facts).getAllByText('캡처 실패')).toHaveLength(2)
    expect(within(facts).getByText('PREP_MCL_CAPTURE_RECORD_CONTRACT_FAILED')).toBeInTheDocument()
    expect(within(facts).getByText('RECORD_NORMALIZATION / CREATED_TIME_INVALID')).toBeInTheDocument()
    expect(within(facts).getByText('dataset · schemaMetadata · p0@17 · time NUMBER')).toBeInTheDocument()
    expect(facts).not.toHaveTextContent('urn:li:')
  })

  it('renders load failure separately from zero and empty states', async () => {
    const request = vi.fn().mockRejectedValue(new Error('변경 이력 provider 조회 실패'))
    render(<DataChangeStatusPanel client={clientFor(request)} />)

    expect(await screen.findByRole('alert')).toHaveTextContent('변경 이력 provider 조회 실패')
    expect(screen.queryByText('변경 이력이 없습니다.')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('변경 이력 원장 상태')).not.toBeInTheDocument()
  })

  it('computes the default Monday from the current KST calendar date', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-08-16T15:30:00.000Z'))
    try {
      const request = vi.fn((path: string) => responseFor(path, {
        summary: summaryFor(path),
        page: eventPage([]),
      }))
      render(<DataChangeStatusPanel client={clientFor(request)} />)

      await waitFor(() => expect(request).toHaveBeenCalledTimes(2))
      expect(request.mock.calls.map(([path]) => String(path))).toEqual(expect.arrayContaining([
        '/change-history/summary?week_start=2026-08-17',
        expect.stringContaining('week_start=2026-08-17'),
      ]))
    } finally {
      vi.useRealTimers()
    }
  })

  it('applies every supported filter through a bounded ChangeHistoryApi server request', async () => {
    const request = vi.fn((path: string) => responseFor(path, {
      summary: summaryFor(path),
      page: eventPage([event()]),
    }))
    render(<DataChangeStatusPanel client={clientFor(request)} />)
    await screen.findByText('총 1건 · 최대 50건 표시')

    fireEvent.change(screen.getByLabelText('주 시작일 (KST 월요일)'), { target: { value: '2026-08-03' } })
    fireEvent.change(screen.getByLabelText('변경 유형'), { target: { value: 'SCHEMA_CHANGE' } })
    fireEvent.change(screen.getByLabelText('카테고리'), { target: { value: 'TECHNICAL_SCHEMA' } })
    fireEvent.change(screen.getByLabelText('정밀도'), { target: { value: 'EXACT_MCL' } })
    fireEvent.change(screen.getByLabelText('작업'), { target: { value: 'UPDATE' } })
    fireEvent.change(screen.getByLabelText('플랫폼'), { target: { value: 'postgres' } })
    fireEvent.change(screen.getByLabelText('데이터베이스'), { target: { value: 'business_db' } })
    fireEvent.change(screen.getByLabelText('스키마'), { target: { value: 'public' } })
    fireEvent.change(screen.getByLabelText('시스템 ID'), { target: { value: 'system-1' } })
    fireEvent.change(screen.getByLabelText('담당자 ID'), { target: { value: 'steward-1' } })
    fireEvent.change(screen.getByLabelText('CR 연결 상태'), { target: { value: 'UNLINKED' } })
    fireEvent.change(screen.getByLabelText('단계'), { target: { value: 'UNLINKED' } })
    fireEvent.click(screen.getByRole('button', { name: '필터 적용' }))

    await waitFor(() => expect(eventRequestPaths(request)).toHaveLength(2))
    const url = new URL(eventRequestPaths(request).at(-1)!, 'https://datariver.invalid')
    expect(Object.fromEntries(url.searchParams)).toEqual({
      limit: '50',
      week_start: '2026-08-03',
      change_type: 'SCHEMA_CHANGE',
      category: 'TECHNICAL_SCHEMA',
      precision: 'EXACT_MCL',
      operation: 'UPDATE',
      platform: 'postgres',
      database_name: 'business_db',
      schema_name: 'public',
      system_id: 'system-1',
      assignee_subject_id: 'steward-1',
      link_state: 'UNLINKED',
      stage: 'UNLINKED',
    })
  })

  it('shows KST and visibly labels detected time when source occurrence is absent', async () => {
    const detectedAt = '2026-08-10T16:30:00.000Z'
    const detectedEvent = { ...event(), source_occurred_at: null, detected_at: detectedAt }
    const request = vi.fn((path: string) => responseFor(path, {
      summary: summaryFor(path),
      page: eventPage([detectedEvent]),
    }))
    render(<DataChangeStatusPanel client={clientFor(request)} />)

    const expectedKst = new Intl.DateTimeFormat('ko-KR', {
      timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hour12: false,
    }).format(new Date(detectedAt))
    expect(await screen.findByText(expectedKst)).toBeInTheDocument()
    expect(screen.getByText('감지 시각 (detected)')).toBeInTheDocument()
  })

  it('renders the generic lifecycle row and sends its closed category filter', async () => {
    const lifecycle = {
      ...event(), category: 'LIFECYCLE' as const, change_type: 'METADATA_CHANGE' as const,
      source_aspect: 'status', operation: 'DELETE' as const, entity_key: 'asset:lifecycle:removed',
    }
    const request = vi.fn((path: string) => responseFor(path, {
      summary: summaryFor(path, { category_counts: { ...summaryFor(path).category_counts, LIFECYCLE: 1 } }),
      page: eventPage([lifecycle]),
    }))
    render(<DataChangeStatusPanel client={clientFor(request)} />)
    expect(await screen.findByText('수명주기')).toBeInTheDocument()
    expect(screen.getAllByText('삭제')).toHaveLength(2)
    fireEvent.change(screen.getByLabelText('카테고리'), { target: { value: 'LIFECYCLE' } })
    fireEvent.click(screen.getByRole('button', { name: '필터 적용' }))
    await waitFor(() => expect(eventRequestPaths(request).at(-1)).toContain('category=LIFECYCLE'))
  })

  it('loads authoritative detail and CR link history into the safe semantic drawer', async () => {
    const request = vi.fn((path: string) => responseFor(path, {
      summary: summaryFor(path),
      page: eventPage([event()]),
    }))
    const requestWithMeta = vi.fn((path: string) => {
      if (path === `/change-history/events/${eventId}`) {
        return Promise.resolve({
          data: {
            ...event(),
            before: { nullable: true },
            after: { nullable: false, description: '<script>alert(1)</script>' },
          },
          etag: '"0"',
        })
      }
      if (path.startsWith(`/change-history/events/${eventId}/cr-links?`)) {
        return Promise.resolve({
          data: {
            current_primary: { change_request_id: 'cr-primary', change_request_round: 2 },
            current_candidates: [{ change_request_id: 'cr-candidate', change_request_round: 1 }],
            items: [linkHistory()],
            next_cursor: null,
            limit: 50,
          },
          etag: `"${'3'.repeat(64)}"`,
        })
      }
      throw new Error(`Unexpected detail path: ${path}`)
    })
    render(<DataChangeStatusPanel client={clientFor(request, requestWithMeta)} />)

    const occurrence = new Intl.DateTimeFormat('ko-KR', {
      timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hour12: false,
    }).format(new Date(timestamp))
    fireEvent.click(await screen.findByRole('button', { name: occurrence }))

    const dialog = await screen.findByRole('dialog', { name: '변경 이벤트 상세' })
    expect(within(dialog).getByText('urn:li:dataset:orders')).toBeInTheDocument()
    expect(within(dialog).getByText('schemaMetadata')).toBeInTheDocument()
    expect(within(dialog).getByText(/"nullable": true/)).toBeInTheDocument()
    expect(within(dialog).getByText(/<script>alert\(1\)<\/script>/)).toBeInTheDocument()
    expect(within(dialog).getAllByText('cr-primary · round 2')).toHaveLength(2)
    expect(within(dialog).getByText('cr-candidate · round 1')).toBeInTheDocument()
    expect(within(dialog).getByText('reviewed by steward')).toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: /연결|해제/ })).not.toBeInTheDocument()
    expect(requestWithMeta).toHaveBeenCalledTimes(2)
  })

  it('aborts in-flight summary and event reads when the panel becomes stale', async () => {
    const signals: AbortSignal[] = []
    const request = vi.fn((_path: string, options: RequestOptions = {}) => {
      if (options.signal) signals.push(options.signal)
      return new Promise<never>(() => undefined)
    })
    const { unmount } = render(<DataChangeStatusPanel client={clientFor(request)} />)
    await waitFor(() => expect(signals).toHaveLength(2))

    unmount()
    expect(signals.every((signal) => signal.aborted)).toBe(true)
  })
})

function clientFor(
  request: ReturnType<typeof vi.fn>,
  requestWithMeta: ReturnType<typeof vi.fn> = vi.fn(),
): ApiClient {
  return {
    request: request as unknown as ApiClient['request'],
    requestWithMeta: requestWithMeta as unknown as ApiClient['requestWithMeta'],
  } as ApiClient
}

function responseFor(
  path: string,
  values: { summary: ReturnType<typeof summary>; page: ReturnType<typeof eventPage> },
) {
  if (path.startsWith('/change-history/summary?')) return Promise.resolve(values.summary)
  if (path.startsWith('/change-history/events?')) return Promise.resolve(values.page)
  throw new Error(`Unexpected path: ${path}`)
}

function summaryFor(path: string, overrides: Record<string, unknown> = {}) {
  const weekStart = path.startsWith('/change-history/summary?')
    ? new URL(path, 'https://datariver.invalid').searchParams.get('week_start') ?? '2026-08-10'
    : '2026-08-10'
  return summary(weekStart, overrides)
}

function summary(weekStart: string, overrides: Record<string, unknown> = {}) {
  const weekEnd = new Date(`${weekStart}T00:00:00.000Z`)
  weekEnd.setUTCDate(weekEnd.getUTCDate() + 7)
  return {
    week_start: weekStart,
    week_end_exclusive: weekEnd.toISOString().slice(0, 10),
    timezone: 'Asia/Seoul',
    as_of: timestamp,
    policy_version: 1,
    policy_hash: '4'.repeat(64),
    count_unit: 'DISTINCT_NORMALIZED_CHANGE_TRANSACTION',
    total_count: 0,
    unlinked_count: 0,
    received_count: 0,
    recheck_count: 0,
    testing_count: 0,
    final_review_count: 0,
    completed_count: 0,
    time_unknown_count: 0,
    schema_change_count: 0,
    metadata_change_count: 0,
    event_count: 0,
    distinct_asset_count: 0,
    precision_counts: {
      EXACT_TIMELINE: 0,
      EXACT_MCL: 0,
      DRIFT_DETECTED: 0,
      BACKFILLED_BEST_EFFORT: 0,
      INITIAL_BASELINE: 0,
    },
    category_counts: {
      TECHNICAL_SCHEMA: 0,
      DOCUMENTATION: 0,
      TAG: 0,
      GLOSSARY_TERM: 0,
      DOMAIN: 0,
      OWNERSHIP: 0,
      LIFECYCLE: 0,
    },
    operation_counts: { CREATE: 0, UPDATE: 0, UPSERT: 0, DELETE: 0, ADD: 0, REMOVE: 0 },
    capture_state: 'CAPTURE_PENDING',
    sync_status: 'CAPTURE_PENDING',
    capture_failure_classification: null,
    capture_failure_stage: null,
    capture_failure_detail_code: null,
    capture_failure_record_shape: null,
    source_generation: '5'.repeat(64),
    source_observed_at: timestamp,
    source_occurred_at: null,
    detected_at: null,
    captured_at: null,
    effective_week_start: weekStart,
    history_available_from: null,
    ledger_guarantee_from: null,
    first_exact_capture_at: null,
    first_timeline_checkpoint: null,
    first_mcl_offsets: null,
    last_successful_capture_at: null,
    ...overrides,
  }
}

function eventPage(items: ChangeHistoryEvent[]) {
  return {
    items,
    next_cursor: null,
    limit: 50,
    total: items.length,
    empty_state_reason: items.length ? null : 'NO_LEDGER_EVENTS' as const,
    empty_state_detail: null,
  }
}

function event(): ChangeHistoryEvent {
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
      resolution: 'RESOLVED',
      system_id: 'system-1',
      provider_context: { platform: 'postgres', database_name: 'business_db', schema_name: 'public' },
    },
    locator: { platform: 'postgres', database_name: 'business_db', schema_name: 'public', asset_name: 'orders' },
    assignee: {
      subject_id: 'steward-1',
      responsibility: 'DATA_STEWARD',
      system_id: 'system-1',
      priority: 1,
      basis: 'CURRENT_POC_PROJECTION',
    },
    current_stage: 'UNLINKED',
    allowed_link_actions: [],
    current_primary: null,
    current_candidates: [],
    link_version: 0,
  }
}

function linkHistory() {
  return {
    link_event_identity: '6'.repeat(64),
    event_hash: '3'.repeat(64),
    ledger_event_identity: eventId,
    link_version: 1,
    link_kind: 'PRIMARY',
    action: 'SET_PRIMARY',
    change_request_id: 'cr-primary',
    change_request_round: 2,
    prior_link_hash: null,
    reason: 'reviewed by steward',
    policy_hash: '4'.repeat(64),
    basis_hash: '5'.repeat(64),
    actor_ref: 'steward-1',
    occurred_at: timestamp,
    captured_at: timestamp,
  }
}

function eventRequestPaths(request: ReturnType<typeof vi.fn>): string[] {
  return request.mock.calls
    .map(([path]) => String(path))
    .filter((path) => path.startsWith('/change-history/events?'))
}
