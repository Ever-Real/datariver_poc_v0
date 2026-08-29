import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiClient, RequestOptions } from '../../api/client'
import type { ChangeRequestSummary } from '../../api/types'
import type {
  ChangeHistoryEvent,
  ChangeHistoryEventPage,
  ChangeHistoryLinkAction,
  ChangeHistoryLinkPage,
} from '../change-history/types'
import { DetectedChangeCrPanel } from './DetectedChangeCrPanel'

const eventId = '1'.repeat(64)
const transactionId = '2'.repeat(64)
const linkEtagHash = '3'.repeat(64)
const commandHash = '4'.repeat(64)
const timestamp = '2026-08-11T01:00:00.000Z'
const weekStart = '2026-08-10'

afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('DetectedChangeCrPanel', () => {
  it.each([
    ['전체', {}],
    ['CR 미연결', { link_state: 'UNLINKED' }],
    ['접수 완료', { stage: 'RECEIVED' }],
    ['재검토', { stage: 'RECHECK' }],
    ['변경 / TEST', { stage: 'TESTING' }],
    ['완료검토', { stage: 'FINAL_REVIEW' }],
    ['완료', { stage: 'COMPLETED' }],
  ])('uses the exact current week and bounded server filter for %s', async (label, expectedFilter) => {
    setCurrentWeek()
    const request = vi.fn((path: string) => listResponse(path))
    render(<DetectedChangeCrPanel client={clientFor(request)} changeRequests={[]} />)

    await screen.findByLabelText('주간 변경 7개 집계')
    if (label !== '전체') {
      const filterButton = screen.getByText(label, { selector: '.detected-change-weekly span' }).closest('button')
      if (!filterButton) throw new Error(`Weekly filter button was not rendered: ${label}`)
      fireEvent.click(filterButton)
      await waitFor(() => expect(eventPaths(request)).toHaveLength(2))
    }

    const url = new URL(eventPaths(request).at(-1)!, 'https://datariver.invalid')
    expect(Object.fromEntries(url.searchParams)).toEqual({
      limit: '50',
      week_start: weekStart,
      ...expectedFilter,
    })
    if (label === 'CR 미연결') expect(url.searchParams.has('stage')).toBe(false)
  })

  it('shows all seven server counts and keeps loading, authorized empty, and failure distinct', async () => {
    setCurrentWeek()
    const pending = deferred<ReturnType<typeof weekly>>()
    const request = vi.fn((path: string) => {
      if (path.startsWith('/change-history/weekly?')) return pending.promise
      if (path.startsWith('/change-history/events?')) return Promise.resolve(eventPage([]))
      throw new Error(`Unexpected path: ${path}`)
    })
    const view = render(<DetectedChangeCrPanel client={clientFor(request)} changeRequests={[]} />)

    expect(screen.getByRole('status')).toHaveTextContent('변경 이벤트를 불러오는 중입니다.')
    pending.resolve(weekly())
    const counts = await screen.findByLabelText('주간 변경 7개 집계')
    expect(within(counts).getByRole('button', { name: /전체21/ })).toBeInTheDocument()
    expect(within(counts).getByRole('button', { name: /CR 미연결1/ })).toBeInTheDocument()
    expect(within(counts).getByRole('button', { name: /접수 완료2/ })).toBeInTheDocument()
    expect(within(counts).getByRole('button', { name: /재검토3/ })).toBeInTheDocument()
    expect(within(counts).getByRole('button', { name: /변경 \/ TEST4/ })).toBeInTheDocument()
    expect(within(counts).getByRole('button', { name: /완료검토5/ })).toBeInTheDocument()
    expect(within(counts).getByRole('button', { name: /완료6/ })).toBeInTheDocument()
    expect(screen.getByText('현재 canonical change ledger에 감지 이벤트가 없습니다.')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()

    view.unmount()
    render(<DetectedChangeCrPanel
      client={clientFor(vi.fn().mockRejectedValue(new Error('주간 원장 조회 실패')))}
      changeRequests={[]}
    />)
    expect(await screen.findByRole('alert')).toHaveTextContent('주간 원장 조회 실패')
    expect(screen.queryByText('현재 canonical change ledger에 감지 이벤트가 없습니다.')).not.toBeInTheDocument()
  })

  it('uses the Change Management date range and canonical type filter for visible detection history', async () => {
    const request = vi.fn((path: string) => path.startsWith('/change-history/events?')
      ? Promise.resolve(eventPage([event()]))
      : Promise.reject(new Error(`Unexpected path: ${path}`)))
    render(<DetectedChangeCrPanel
      client={clientFor(request, detailTransport([]))}
      changeRequests={[]}
      dateRange={{ from: '2026-08-01', to: '2026-08-24' }}
    />)

    expect(await screen.findByRole('heading', { name: 'Schema / Metadata 감지 변경 이력' })).toBeInTheDocument()
    expect(screen.getAllByRole('columnheader').map((header) => header.textContent)).toEqual([
      '플랫폼', '스키마', '변경일', '변경유형', '테이블명', '변경요약', '변경내용',
    ])
    expect(screen.getByText('컬럼변경')).toBeInTheDocument()
    expect(screen.getByText('customer_id Nullable 기존(true)에서 변경(false)')).toBeInTheDocument()
    expect(screen.getByText('2026-08-11')).toBeInTheDocument()
    expect(screen.getByLabelText('현재 기간과 권한 범위의 Schema 및 Metadata 감지 변경 이력 스크롤 영역'))
      .toHaveClass('detected-change-history-table')
    let url = new URL(eventPaths(request)[0]!, 'https://datariver.invalid')
    expect(Object.fromEntries(url.searchParams)).toEqual({ limit: '50', date_from: '2026-08-01', date_to: '2026-08-24' })
    expect(weeklyPaths(request)).toHaveLength(0)

    fireEvent.click(screen.getByRole('button', { name: 'Schema Change' }))
    await waitFor(() => expect(eventPaths(request)).toHaveLength(2))
    url = new URL(eventPaths(request)[1]!, 'https://datariver.invalid')
    expect(url.searchParams.get('change_type')).toBe('SCHEMA_CHANGE')

    fireEvent.click(screen.getByText('orders').closest('tr')!)
    const detail = await screen.findByLabelText('선택 이벤트 CR 연결')
    expect(within(detail).getByText('DataHub · schemaMetadata · EXACT_MCL')).toBeInTheDocument()
    expect(within(detail).getAllByText('{}')).toHaveLength(2)
  })

  it('renders the bounded seven-column presentation matrix without list-to-detail N+1 requests', async () => {
    const items = [
      presentationEvent(1, { category: 'LIFECYCLE', source_aspect: 'entity', operation: 'CREATE', target_kind: 'TABLE', field_name: null, presentation_change_type: 'TABLE_CREATE', change_summary: 'CREATE · LIFECYCLE', change_detail: [] }),
      presentationEvent(2, { category: 'LIFECYCLE', source_aspect: 'status', operation: 'DELETE', target_kind: 'TABLE', field_name: null, presentation_change_type: 'TABLE_DELETE', change_summary: 'DELETE · LIFECYCLE', change_detail: [] }),
      presentationEvent(3, { category: 'DOCUMENTATION', source_aspect: 'datasetProperties', target_kind: 'TABLE', field_name: null, presentation_change_type: 'TABLE_CHANGE', change_summary: 'UPDATE · DOCUMENTATION', change_detail: [{ field: 'DESCRIPTION', before: 'old', after: 'new' }] }),
      presentationEvent(4, { category: 'TAG', source_aspect: 'globalTags', target_kind: 'TABLE', field_name: null, presentation_change_type: 'TABLE_CHANGE', change_summary: 'ADD · TAG', change_detail: [{ field: 'TAG', before: null, after: 'curated' }] }),
      presentationEvent(5, { category: 'GLOSSARY_TERM', source_aspect: 'glossaryTerms', target_kind: 'TABLE', field_name: null, presentation_change_type: 'TABLE_CHANGE', change_summary: 'ADD · GLOSSARY_TERM', change_detail: [{ field: 'GLOSSARY_TERM', before: null, after: 'business-term' }] }),
      presentationEvent(6, { category: 'OWNERSHIP', source_aspect: 'ownership', target_kind: 'TABLE', field_name: null, presentation_change_type: 'TABLE_CHANGE', change_summary: 'UPDATE · OWNERSHIP', change_detail: [{ field: 'OWNER', before: 'owner-a', after: 'owner-b' }] }),
      presentationEvent(7, { category: 'DOMAIN', source_aspect: 'domains', target_kind: 'TABLE', field_name: null, presentation_change_type: 'TABLE_CHANGE', change_summary: 'UPDATE · DOMAIN', change_detail: [{ field: 'DOMAIN', before: 'domain-a', after: 'domain-b' }] }),
      presentationEvent(8, { operation: 'CREATE', target_kind: 'COLUMN', field_name: 'amount', presentation_change_type: 'COLUMN_CREATE', change_summary: 'CREATE · TECHNICAL_SCHEMA', change_detail: [] }),
      presentationEvent(9, { operation: 'DELETE', target_kind: 'COLUMN', field_name: 'legacy_amount', presentation_change_type: 'COLUMN_DELETE', change_summary: 'DELETE · TECHNICAL_SCHEMA', change_detail: [] }),
      presentationEvent(10, { target_kind: 'COLUMN', field_name: 'amount', presentation_change_type: 'COLUMN_CHANGE', change_summary: 'UPDATE · TECHNICAL_SCHEMA', change_detail: [{ field: 'TYPE', before: 'integer', after: 'bigint' }, { field: 'NULLABLE', before: 'true', after: 'false' }, { field: 'DESCRIPTION', before: 'old', after: 'new' }] }),
    ]
    const request = vi.fn((path: string) => path.startsWith('/change-history/events?')
      ? Promise.resolve(eventPage(items))
      : Promise.reject(new Error(`Unexpected path: ${path}`)))
    const requestWithMeta = vi.fn()
    render(<DetectedChangeCrPanel
      client={clientFor(request, requestWithMeta)}
      changeRequests={[]}
      dateRange={{ from: '2026-08-01', to: '2026-08-24' }}
    />)

    expect(await screen.findByText('테이블 orders 생성')).toBeInTheDocument()
    expect(screen.getByText('테이블 orders 삭제')).toBeInTheDocument()
    expect(screen.getByText('Desc 기존(old)에서 변경(new)')).toBeInTheDocument()
    expect(screen.getByText('Tag 기존(없음)에서 변경(curated)')).toBeInTheDocument()
    expect(screen.getByText('Term 기존(없음)에서 변경(business-term)')).toBeInTheDocument()
    expect(screen.getByText('Owner 기존(owner-a)에서 변경(owner-b)')).toBeInTheDocument()
    expect(screen.getByText('Domain 기존(domain-a)에서 변경(domain-b)')).toBeInTheDocument()
    expect(screen.getByText('컬럼 amount 생성')).toBeInTheDocument()
    expect(screen.getByText('컬럼 legacy_amount 삭제')).toBeInTheDocument()
    expect(screen.getByText('amount Type 기존(integer)에서 변경(bigint) · amount Nullable 기존(true)에서 변경(false) · amount Desc 기존(old)에서 변경(new)')).toBeInTheDocument()
    expect(requestWithMeta).not.toHaveBeenCalled()
  })

  it('hides every mutation control when the fresh event grants no link actions', async () => {
    setCurrentWeek()
    const request = vi.fn((path: string) => listResponse(path, [event()]))
    const requestWithMeta = detailTransport([])
    render(<DetectedChangeCrPanel
      client={clientFor(request, requestWithMeta)}
      changeRequests={[changeRequest()]}
    />)

    await openFirstEvent()
    const linker = await screen.findByLabelText('선택 이벤트 CR 연결')
    expect(within(linker).getByText('현재 권한과 이벤트 상태에서 허용된 연결 작업이 없습니다.')).toBeInTheDocument()
    expect(within(linker).queryByRole('combobox')).not.toBeInTheDocument()
    expect(within(linker).queryByRole('button', { name: '연결 이력 저장' })).not.toBeInTheDocument()
    expect(within(linker).getByText('event ETag "0" · link ETag "0"')).toBeInTheDocument()
  })

  it('fails closed when the fresh event and link-history ETags do not identify the same link head', async () => {
    setCurrentWeek()
    const request = vi.fn((path: string) => listResponse(path, [event(['SET_PRIMARY'])]))
    const requestWithMeta = detailTransport(['SET_PRIMARY'], {}, undefined, true)
    render(<DetectedChangeCrPanel
      client={clientFor(request, requestWithMeta)}
      changeRequests={[changeRequest()]}
    />)

    await clickFirstEvent()
    expect(await screen.findByRole('alert')).toHaveTextContent('이벤트와 CR 연결 이력의 최신 ETag가 일치하지 않습니다.')
    expect(screen.queryByLabelText('선택 이벤트 CR 연결')).not.toBeInTheDocument()
  })

  it.each<{
    action: ChangeHistoryLinkAction
    label: string
    primary: ChangeHistoryLinkPage['current_primary']
    candidates: ChangeHistoryLinkPage['current_candidates']
  }>([
    { action: 'SET_PRIMARY', label: 'Primary 지정', primary: null, candidates: [] },
    { action: 'CLEAR_PRIMARY', label: 'Primary 해제', primary: target(), candidates: [] },
    { action: 'ADD_CANDIDATE', label: 'Candidate 추가', primary: null, candidates: [] },
    { action: 'REMOVE_CANDIDATE', label: 'Candidate 제거', primary: null, candidates: [target()] },
  ])('sends only the exact $action command and refetches event, links, weekly, and list', async ({ action, label, primary, candidates }) => {
    setCurrentWeek()
    vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue('00000000-0000-4000-8000-000000000007')
    const request = vi.fn((path: string) => listResponse(path, [event([action])]))
    const requestWithMeta = detailTransport([action], { current_primary: primary, current_candidates: candidates })
    render(<DetectedChangeCrPanel
      client={clientFor(request, requestWithMeta)}
      changeRequests={[changeRequest()]}
    />)

    await openFirstEvent()
    fireEvent.change(screen.getByLabelText('허용 작업'), { target: { value: action } })
    expect(await screen.findByRole('option', { name: 'CR-2026-7 · round 3' })).toBeInTheDocument()
    expect(screen.getByLabelText('현재 round CR 대상')).toHaveValue(JSON.stringify(['cr-7', 3]))
    fireEvent.change(screen.getByLabelText('연결 사유'), { target: { value: '  승인된 변경 연결  ' } })
    fireEvent.click(screen.getByRole('button', { name: '연결 이력 저장' }))

    await waitFor(() => expect(postCalls(requestWithMeta)).toHaveLength(1))
    const [path, options] = postCalls(requestWithMeta)[0]!
    expect(path).toBe(`/change-history/events/${eventId}/cr-link-events`)
    expect(options).toEqual(expect.objectContaining({
      method: 'POST',
      cache: 'no-store',
      ifMatch: '"0"',
      idempotencyKey: '00000000-0000-4000-8000-000000000007',
    }))
    const command = jsonBody(options)
    expect(command).toEqual({
      action,
      change_request_id: 'cr-7',
      change_request_round: 3,
      reason: '승인된 변경 연결',
    })
    expect(Object.keys(command).sort()).toEqual([
      'action', 'change_request_id', 'change_request_round', 'reason',
    ])
    await waitFor(() => {
      expect(eventPaths(request)).toHaveLength(2)
      expect(weeklyPaths(request)).toHaveLength(2)
      expect(detailGetCalls(requestWithMeta)).toHaveLength(4)
    })
    expect(screen.getByLabelText('허용 작업')).toHaveValue('')
    expect(screen.getByLabelText('연결 사유')).toHaveValue('')
    expect(screen.getByRole('option', { name: label })).toBeInTheDocument()
  })

  it('keeps the authoritative pre-command state and does not refetch after a stale ETag failure', async () => {
    setCurrentWeek()
    vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue('00000000-0000-4000-8000-000000000008')
    const request = vi.fn((path: string) => listResponse(path, [event(['SET_PRIMARY'])]))
    const requestWithMeta = detailTransport(['SET_PRIMARY'], {}, new Error('최신 link ETag와 일치하지 않습니다.'))
    render(<DetectedChangeCrPanel
      client={clientFor(request, requestWithMeta)}
      changeRequests={[changeRequest()]}
    />)

    await openFirstEvent()
    fireEvent.change(screen.getByLabelText('허용 작업'), { target: { value: 'SET_PRIMARY' } })
    fireEvent.change(screen.getByLabelText('연결 사유'), { target: { value: 'stale command' } })
    fireEvent.click(screen.getByRole('button', { name: '연결 이력 저장' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('최신 link ETag와 일치하지 않습니다.')
    expect(screen.getByLabelText('허용 작업')).toHaveValue('SET_PRIMARY')
    expect(screen.getByLabelText('연결 사유')).toHaveValue('stale command')
    expect(screen.getAllByText('미연결')).not.toHaveLength(0)
    expect(eventPaths(request)).toHaveLength(1)
    expect(weeklyPaths(request)).toHaveLength(1)
    expect(detailGetCalls(requestWithMeta)).toHaveLength(2)
  })

  it('offers only authorized summaries at their current rounds, including unlink targets', async () => {
    setCurrentWeek()
    const request = vi.fn((path: string) => listResponse(path, [event(['CLEAR_PRIMARY'])]))
    const requestWithMeta = detailTransport(['CLEAR_PRIMARY'], {
      current_primary: { change_request_id: 'cr-7', change_request_round: 2 },
    })
    render(<DetectedChangeCrPanel
      client={clientFor(request, requestWithMeta)}
      changeRequests={[changeRequest({ current_round_number: 3 })]}
    />)

    await openFirstEvent()
    fireEvent.change(screen.getByLabelText('허용 작업'), { target: { value: 'CLEAR_PRIMARY' } })
    expect(await screen.findByText('현재 권한의 CR 목록에서 일치하는 current round 대상을 찾을 수 없습니다.')).toBeInTheDocument()
    expect(screen.getByLabelText('현재 round CR 대상')).toHaveDisplayValue('선택')
    expect(screen.getByRole('button', { name: '연결 이력 저장' })).toBeDisabled()
  })

  it('uses the exact schema, system, and KST date range in the reused right-side TanStack drawer', async () => {
    const request = vi.fn((path: string) => {
      if (path.startsWith('/change-history/events?')) return Promise.resolve(eventPage([event()]))
      throw new Error(`Unexpected path: ${path}`)
    })
    const onClose = vi.fn()
    render(<DetectedChangeCrPanel
      client={clientFor(request, detailTransport([]))}
      changeRequests={[changeRequest()]}
      selection={{
        platform: 'postgres', databaseName: 'business', schemaName: 'public',
        systemId: 'system-1', systemResolution: 'RESOLVED', systemName: 'Business', dateFrom: '2026-08-01', dateTo: '2026-08-03',
      }}
      onClose={onClose}
    />)

    const drawer = await screen.findByRole('complementary', { name: 'public 이벤트 상세' })
    expect(within(drawer).getAllByRole('columnheader').map((header) => header.textContent)).toEqual([
      '발생 시각', '변경', '대상', '단계', 'CR',
    ])
    expect(within(drawer).getByText('orders')).toBeInTheDocument()
    const url = new URL(eventPaths(request)[0]!, 'https://datariver.invalid')
    expect(Object.fromEntries(url.searchParams)).toEqual({
      limit: '50', date_from: '2026-08-01', date_to: '2026-08-03',
      platform: 'postgres', database_name: 'business', schema_name: 'public',
      system_id: 'system-1', system_resolution: 'RESOLVED',
    })
    expect(weeklyPaths(request)).toHaveLength(0)
    fireEvent.click(within(drawer).getByText('orders').closest('tr')!)
    expect(await within(drawer).findByLabelText('선택 이벤트 CR 연결')).toBeInTheDocument()
    fireEvent.click(within(drawer).getByRole('button', { name: '이벤트 상세 닫기' }))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('shows an authorized empty state inside the event drawer', async () => {
    const request = vi.fn((path: string) => path.startsWith('/change-history/events?')
      ? Promise.resolve(eventPage([], 'FILTER_DATE_RANGE_EMPTY'))
      : Promise.reject(new Error(`Unexpected path: ${path}`)))
    render(<DetectedChangeCrPanel
      client={clientFor(request)}
      changeRequests={[]}
      selection={{
        platform: 'postgres', databaseName: 'business', schemaName: 'empty_schema',
        systemId: 'system-1', systemResolution: 'RESOLVED', systemName: 'Business', dateFrom: '2026-08-01', dateTo: '2026-08-03',
      }}
      onClose={vi.fn()}
    />)
    expect(await screen.findByText('선택한 스키마·시스템·기간 필터에 일치하는 이벤트가 없습니다.')).toBeInTheDocument()
  })

  it('distinguishes exact-mapping authorization emptiness from a date/type filter miss', async () => {
    const request = vi.fn((path: string) => path.startsWith('/change-history/events?')
      ? Promise.resolve(eventPage([], 'EVENTS_EXIST_BUT_NOT_AUTHORIZED', 'NO_EXACT_MAPPING'))
      : Promise.reject(new Error(`Unexpected path: ${path}`)))
    render(<DetectedChangeCrPanel
      client={clientFor(request)}
      changeRequests={[]}
      dateRange={{ from: '2026-08-01', to: '2026-08-24' }}
    />)
    expect(await screen.findByText(
      '감지 이벤트는 존재하지만 현재 Table↔System exact mapping이 없어 권한 행을 표시할 수 없습니다.',
    )).toBeInTheDocument()
  })

  it('keeps every authorized exact-match event reachable across cursor pages', async () => {
    const firstItems = Array.from({ length: 50 }, (_, index) => ({
      ...event(),
      event_id: index.toString(16).padStart(64, '0'),
      locator: { ...event().locator!, asset_name: `orders-${index}` },
    }))
    const finalItem = {
      ...event(),
      event_id: 'f'.repeat(64),
      locator: { ...event().locator!, asset_name: 'invoices-final' },
    }
    const request = vi.fn((path: string) => {
      if (!path.startsWith('/change-history/events?')) throw new Error(`Unexpected path: ${path}`)
      const cursor = new URL(path, 'https://datariver.invalid').searchParams.get('cursor')
      return Promise.resolve(cursor
        ? { items: [finalItem], next_cursor: null, limit: 50, total: 51, empty_state_reason: null, empty_state_detail: null }
        : { items: firstItems, next_cursor: 'cursor-2', limit: 50, total: 51, empty_state_reason: null, empty_state_detail: null })
    })
    render(<DetectedChangeCrPanel
      client={clientFor(request)}
      changeRequests={[]}
      selection={{
        platform: 'postgres', databaseName: 'business', schemaName: 'public',
        systemId: 'system-1', systemResolution: 'RESOLVED', systemName: 'Business', dateFrom: '2026-08-01', dateTo: '2026-08-03',
      }}
      onClose={vi.fn()}
    />)

    expect(await screen.findByText('orders-0')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '다음' }))
    expect(await screen.findByText('invoices-final')).toBeInTheDocument()
    expect(new URL(eventPaths(request)[1]!, 'https://datariver.invalid').searchParams.get('cursor')).toBe('cursor-2')
    fireEvent.click(screen.getByRole('button', { name: '이전' }))
    expect(await screen.findByText('orders-0')).toBeInTheDocument()
  })

  it('shows remediation CTA when callback is present and NO_EXACT_MAPPING is returned, and invokes it exactly once', async () => {
    setCurrentWeek()
    const onManageTableSystemMappings = vi.fn()
    const request = vi.fn((path: string) => {
      if (path.startsWith('/change-history/events?')) {
        return Promise.resolve(eventPage([], 'EVENTS_EXIST_BUT_NOT_AUTHORIZED', 'NO_EXACT_MAPPING'))
      }
      return listResponse(path)
    })
    render(<DetectedChangeCrPanel
      client={clientFor(request)}
      changeRequests={[]}
      onManageTableSystemMappings={onManageTableSystemMappings}
    />)

    const cta = await screen.findByRole('button', { name: 'Table↔System 연결 관리' })
    expect(cta).toBeInTheDocument()
    fireEvent.click(cta)
    expect(onManageTableSystemMappings).toHaveBeenCalledTimes(1)
  })

  it('hides remediation CTA when callback is absent even if NO_EXACT_MAPPING is returned', async () => {
    setCurrentWeek()
    const request = vi.fn((path: string) => {
      if (path.startsWith('/change-history/events?')) {
        return Promise.resolve(eventPage([], 'EVENTS_EXIST_BUT_NOT_AUTHORIZED', 'NO_EXACT_MAPPING'))
      }
      return listResponse(path)
    })
    render(<DetectedChangeCrPanel
      client={clientFor(request)}
      changeRequests={[]}
    />)

    await screen.findByText('감지 이벤트는 존재하지만 현재 Table↔System exact mapping이 없어 권한 행을 표시할 수 없습니다.')
    expect(screen.queryByRole('button', { name: 'Table↔System 연결 관리' })).not.toBeInTheDocument()
  })
})

function setCurrentWeek() {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date('2026-08-14T03:00:00.000Z'))
}

function clientFor(
  request: ReturnType<typeof vi.fn>,
  requestWithMeta: ReturnType<typeof vi.fn> = vi.fn(),
): ApiClient {
  return {
    request: request as unknown as ApiClient['request'],
    requestWithMeta: requestWithMeta as unknown as ApiClient['requestWithMeta'],
  } as ApiClient
}

function listResponse(path: string, items: ChangeHistoryEvent[] = []) {
  if (path.startsWith('/change-history/weekly?')) return Promise.resolve(weekly())
  if (path.startsWith('/change-history/events?')) return Promise.resolve(eventPage(items))
  throw new Error(`Unexpected path: ${path}`)
}

function weekly() {
  return {
    week_start: weekStart,
    week_end_exclusive: '2026-08-17',
    timezone: 'Asia/Seoul' as const,
    as_of: timestamp,
    policy_version: 1,
    policy_hash: '5'.repeat(64),
    count_unit: 'DISTINCT_NORMALIZED_CHANGE_TRANSACTION' as const,
    total_count: 21,
    unlinked_count: 1,
    received_count: 2,
    recheck_count: 3,
    testing_count: 4,
    final_review_count: 5,
    completed_count: 6,
    time_unknown_count: 0,
  }
}

function eventPage(
  items: ChangeHistoryEvent[],
  emptyState: ChangeHistoryEventPage['empty_state_reason'] = 'NO_LEDGER_EVENTS',
  emptyDetail: ChangeHistoryEventPage['empty_state_detail'] = null,
) {
  return {
    items,
    next_cursor: null,
    limit: 50,
    total: items.length,
    empty_state_reason: items.length ? null : emptyState,
    empty_state_detail: emptyDetail,
  }
}

function event(allowedLinkActions: ChangeHistoryLinkAction[] = []): ChangeHistoryEvent {
  return {
    event_id: eventId,
    transaction_id: transactionId,
    asset_urn: 'urn:li:dataset:orders',
    entity_key: 'business.public.orders',
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
      provider_context: { platform: 'postgres', database_name: 'business', schema_name: 'public' },
    },
    locator: { platform: 'postgres', database_name: 'business', schema_name: 'public', asset_name: 'orders' },
    assignee: {
      subject_id: 'steward-1', responsibility: 'DATA_STEWARD', system_id: 'system-1',
      priority: 1, basis: 'CURRENT_POC_PROJECTION',
    },
    current_stage: 'UNLINKED',
    allowed_link_actions: allowedLinkActions,
    current_primary: null,
    current_candidates: [],
    link_version: 0,
  }
}

function presentationEvent(index: number, overrides: Partial<ChangeHistoryEvent>): ChangeHistoryEvent {
  const merged = {
    ...event(),
    event_id: index.toString(16).padStart(64, '0'),
    ...overrides,
  }
  return {
    ...merged,
    change_type: merged.category === 'TECHNICAL_SCHEMA' && merged.source_aspect === 'schemaMetadata'
      ? 'SCHEMA_CHANGE'
      : 'METADATA_CHANGE',
  }
}

function target() {
  return { change_request_id: 'cr-7', change_request_round: 3 }
}

function detailTransport(
  allowedLinkActions: ChangeHistoryLinkAction[],
  links: Partial<Pick<ChangeHistoryLinkPage, 'current_primary' | 'current_candidates'>> = {},
  postError?: Error,
  mismatchEtag = false,
) {
  let headEtag = '"0"'
  return vi.fn((path: string, options: RequestOptions = {}) => {
    if (path.endsWith('/cr-link-events')) {
      if (postError) return Promise.reject(postError)
      const body = jsonBody(options) as {
        action: ChangeHistoryLinkAction
        change_request_id: string
        change_request_round: number
      }
      headEtag = `"${commandHash}"`
      return Promise.resolve({
        data: {
          link_event_identity: '6'.repeat(64),
          event_hash: commandHash,
          link_version: 1,
          replayed: false,
          event_id: eventId,
          change_request_id: body.change_request_id,
          change_request_round: body.change_request_round,
          action: body.action,
        },
        etag: `"${commandHash}"`,
      })
    }
    if (path === `/change-history/events/${eventId}`) {
      return Promise.resolve({ data: { ...event(allowedLinkActions), before: {}, after: {} }, etag: headEtag })
    }
    if (path.startsWith(`/change-history/events/${eventId}/cr-links?`)) {
      return Promise.resolve({
        data: {
          current_primary: links.current_primary ?? null,
          current_candidates: links.current_candidates ?? [],
          items: [],
          next_cursor: null,
          limit: 50,
        },
        etag: mismatchEtag ? `"${linkEtagHash}"` : headEtag,
      })
    }
    throw new Error(`Unexpected detail path: ${path}`)
  })
}

function changeRequest(overrides: Partial<ChangeRequestSummary> = {}): ChangeRequestSummary {
  return {
    id: 'cr-7',
    number: 'CR-2026-7',
    request_type: 'CATALOG_METADATA',
    title: 'Authorized target',
    state: 'REGISTERED',
    requester_id: 'subject-1',
    requester_department_id: null,
    current_round_number: 3,
    created_at: timestamp,
    requested_due_date: null,
    priority: null,
    urgency: null,
    classification: 'INTERNAL',
    version: 1,
    item_count: 1,
    first_item: { target_ref: 'urn:li:dataset:orders', aspect_name: 'schemaMetadata', operation: 'UPDATE' },
    ...overrides,
  }
}

async function openFirstEvent() {
  await clickFirstEvent()
  await screen.findByLabelText('선택 이벤트 CR 연결')
}

async function clickFirstEvent() {
  const asset = await screen.findByText('orders')
  const row = asset.closest('tr')
  if (!row) throw new Error('Event row was not rendered')
  fireEvent.click(within(row).getByRole('button'))
}

function eventPaths(request: ReturnType<typeof vi.fn>) {
  return request.mock.calls.map(([path]) => String(path)).filter((path) => path.startsWith('/change-history/events?'))
}

function weeklyPaths(request: ReturnType<typeof vi.fn>) {
  return request.mock.calls.map(([path]) => String(path)).filter((path) => path.startsWith('/change-history/weekly?'))
}

function postCalls(requestWithMeta: ReturnType<typeof vi.fn>): Array<[string, RequestOptions]> {
  return requestWithMeta.mock.calls
    .filter(([path]) => String(path).endsWith('/cr-link-events')) as Array<[string, RequestOptions]>
}

function detailGetCalls(requestWithMeta: ReturnType<typeof vi.fn>) {
  return requestWithMeta.mock.calls.filter(([path]) => !String(path).endsWith('/cr-link-events'))
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}

function jsonBody(options: RequestOptions): Record<string, unknown> {
  if (typeof options.body !== 'string') throw new Error('Expected a JSON string request body')
  const parsed: unknown = JSON.parse(options.body)
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('Expected a JSON object request body')
  }
  return parsed as Record<string, unknown>
}
