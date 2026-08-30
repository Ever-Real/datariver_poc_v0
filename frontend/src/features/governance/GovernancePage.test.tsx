import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, type ApiClient, type RequestOptions } from '../../api/client'
import type {
  CatalogAsset,
  ChangeRequestRecord,
  ChangeRequestSchemaOverview,
  ChangeRequestSummary,
} from '../../api/types'
import type { ChangeHistoryEvent } from '../change-history/types'
import { GovernancePage, requestMatchesStateFilter } from './GovernancePage'

vi.mock('./DetectedChangeCrPanel', () => ({
  DetectedChangeCrPanel: ({
    selection,
    dateRange,
  }: {
    selection?: { schemaName: string; systemId: string | null; systemResolution: string }
    dateRange?: { from: string; to: string }
  }) => selection ? (
    <section data-testid="detected-change-cr-panel" data-system-id={selection.systemId ?? ''} data-system-resolution={selection.systemResolution}>{selection.schemaName}</section>
  ) : <section data-testid="detected-change-history-panel">{dateRange?.from}–{dateRange?.to}</section>,
}))

afterEach(() => {
  window.history.replaceState({}, '', '/')
})

function changeRequest(overrides: Partial<ChangeRequestRecord> = {}): ChangeRequestRecord {
  return {
    id: 'change-1',
    number: 'CR-2026-1',
    request_type: 'CATALOG_METADATA',
    title: 'Governed change',
    description: '설명 변경을 검토합니다.',
    state: 'REGISTERED',
    requester_id: 'subject-1',
    requester_department_id: null,
    current_round_id: 'round-1',
    current_round_number: 1,
    revision_allowed: false,
    created_at: '2026-07-17T01:02:03Z',
    requested_due_date: null,
    priority: null,
    urgency: null,
    classification: 'INTERNAL',
    version: 7,
    items: [{
      id: 'item-1',
      target_type: 'DATAHUB_ASPECT',
      target_ref: 'urn:li:dataset:(urn:li:dataPlatform:postgres,engineering.parts,PROD)',
      aspect_name: 'datasetProperties',
      operation: 'UPSERT',
      before_hash: 'before-hash',
      after_hash: 'after-hash',
      target_asset_id: 'asset-1',
      target_asset_type: 'TABLE',
      target_system_id: 'system-1',
      target_domain_id: 'domain-1',
      target_owner_department_id: 'department-1',
      target_classification: 'INTERNAL',
      target_lifecycle: 'ACTIVE',
      target_source_version: 'source-v3',
      target_observed_at: '2026-07-17T01:02:03Z',
      target_binding_hash: 'binding-hash',
      routing_system_id: 'system-1',
    }],
    approvals: [{
      id: 'approval-1',
      stage: 'REVIEW',
      decision: 'APPROVED',
      actor_id: 'reviewer-1',
      reason: '검토 근거가 일치합니다.',
      occurred_at: '2026-07-17T02:03:04Z',
      round_id: 'round-1',
      authorities: [{ kind: 'SYSTEM_DEVELOPER', system_id: 'system-1' }],
    }],
    transitions: [{
      id: 'transition-1',
      from_state: 'REGISTERED',
      to_state: 'IN_REVIEW',
      actor_id: 'reviewer-1',
      reason: '검토를 시작합니다.',
      occurred_at: '2026-07-17T02:04:05Z',
      round_id: 'round-1',
    }],
    rounds: [{
      id: 'round-1',
      round_number: 1,
      submitted_by: 'subject-1',
      submitted_at: '2026-07-17T01:02:03Z',
      closed_at: null,
      evidence_hash: 'a'.repeat(64),
      revision_kind: 'LEGACY',
      title: 'Governed change',
      request_date: null,
      request_department: '',
      request_reason: '설명 변경을 검토합니다.',
      request_content: '',
      requested_due_date: null,
      priority: null,
      urgency: null,
      classification: 'INTERNAL',
      selected_system_id: null,
    }],
    test_runs: [],
    ...overrides,
  }
}

function summary(record: ChangeRequestRecord): ChangeRequestSummary {
  const first = record.items[0]
  if (!first) throw new Error('A test change request requires one item.')
  return {
    id: record.id,
    number: record.number,
    request_type: record.request_type,
    title: record.title,
    state: record.state,
    requester_id: record.requester_id,
    requester_name: '요청자 김',
    requester_department_id: record.requester_department_id,
    current_round_number: record.current_round_number,
    created_at: record.created_at,
    requested_due_date: record.requested_due_date,
    priority: record.priority,
    urgency: record.urgency,
    classification: record.classification,
    version: record.version,
    item_count: record.items.length,
    target_schema_name: 'engineering',
    assignee_names: ['담당자 이'],
    first_item: {
      target_ref: first.target_ref,
      aspect_name: first.aspect_name,
      operation: first.operation,
    },
  }
}

function summaryList(
  records: ChangeRequestRecord[],
  nextCursor: string | null = null,
  overview: ChangeRequestSchemaOverview[] = [],
) {
  return {
    items: records.map(summary),
    overview,
    overview_truncated: false,
    page: { limit: 25, next_cursor: nextCursor },
  }
}

function apiClient(
  request: (path: string, options?: RequestOptions) => Promise<unknown>,
  preserveDateRange = false,
): ApiClient {
  return {
    request: (path: string, options?: RequestOptions) => {
      if (preserveDateRange || !path.startsWith('/change-requests/summaries?')) return request(path, options)
      const url = new URL(path, 'https://datariver.invalid')
      url.searchParams.delete('date_from')
      url.searchParams.delete('date_to')
      return request(`${url.pathname}?${url.searchParams.toString()}`, options)
    },
  } as unknown as ApiClient
}

const governedCatalogAsset: CatalogAsset = {
  id: 'catalog-asset-1',
  external_urn: 'urn:li:dataset:(urn:li:dataPlatform:postgres,manufacturing.wafer_events,PROD)',
  asset_type: 'DATASET',
  name: 'wafer_events',
  platform: 'postgres',
  database_name: 'manufacturing',
  schema_name: 'quality',
  classification: 'INTERNAL',
  lifecycle: 'ACTIVE',
  observed_at: '2026-07-17T01:02:03Z',
  matches: [],
  tags: ['tier:silver'],
  terms: ['yield'],
}

function problem(status: number, detail: string, remediation?: 'FIDO2_REQUIRED'): ApiError {
  return new ApiError({
    type: `urn:datariver:problem:${status}`,
    title: status === 409 ? 'Conflict' : 'Forbidden',
    status,
    detail,
    code: status === 409 ? 'version_conflict' : 'forbidden',
    request_id: `request-${status}`,
    remediation: remediation ? { kind: remediation } : undefined,
  })
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function reverseEvent(overrides: Partial<ChangeHistoryEvent> = {}): ChangeHistoryEvent {
  return {
    event_id: 'a'.repeat(64),
    transaction_id: 'b'.repeat(64),
    asset_urn: 'urn:li:dataset:(urn:li:dataPlatform:postgres,engineering.parts,PROD)',
    entity_key: 'engineering.parts',
    category: 'DOCUMENTATION',
    change_type: 'METADATA_CHANGE',
    source_aspect: 'datasetProperties',
    operation: 'UPSERT',
    target_kind: 'TABLE',
    field_name: null,
    presentation_change_type: 'TABLE_CHANGE',
    change_summary: 'UPSERT · DOCUMENTATION',
    change_detail: [{ field: 'DESCRIPTION', before: 'old', after: 'new' }],
    precision: 'EXACT_MCL',
    source_occurred_at: null,
    detected_at: '2026-07-17T03:04:05.000Z',
    captured_at: '2026-07-17T03:04:06.000Z',
    system: { resolution: 'RESOLVED', system_id: 'system-1', provider_context: null },
    locator: { platform: 'postgres', database_name: 'engineering', schema_name: 'public', asset_name: 'parts' },
    assignee: { subject_id: 'steward-1', responsibility: 'DATA_STEWARD', system_id: 'system-1', priority: 1, basis: 'CURRENT_POC_PROJECTION' },
    current_stage: 'RECEIVED',
    allowed_link_actions: [],
    current_primary: { change_request_id: 'change-1', change_request_round: 1 },
    current_candidates: [],
    link_version: 1,
    ...overrides,
  }
}

function renderPage(client: ApiClient, onStepUp = vi.fn(() => Promise.resolve())) {
  return render(<GovernancePage
    client={client}
    requesterName="Test Requester"
    onStepUp={onStepUp}
    onPasswordReauth={vi.fn(() => Promise.resolve())}
    onEnroll={vi.fn(() => Promise.resolve())}
  />)
}

async function openDetail(record: ChangeRequestRecord) {
  const row = await screen.findByText(record.number).then((cell) => cell.closest('tr'))
  if (!row) throw new Error('Change request row was not rendered')
  row.focus()
  fireEvent.keyDown(row, { key: 'Enter' })
  return screen.findByRole('dialog', { name: `${record.number} · ${record.title}` })
}

async function openDetailAfterRender(
  request: (path: string, options?: RequestOptions) => Promise<unknown>,
  record: ChangeRequestRecord,
) {
  renderPage(apiClient(request))
  return openDetail(record)
}

describe('GovernancePage', () => {
  it('keeps live state updates only while they remain in the selected server group', () => {
    expect(requestMatchesStateFilter('IN_REVIEW', 'GROUP:IN_PROGRESS')).toBe(true)
    expect(requestMatchesStateFilter('APPLYING', 'GROUP:IN_PROGRESS')).toBe(true)
    expect(requestMatchesStateFilter('CHANGES_REQUESTED', 'GROUP:IN_PROGRESS')).toBe(true)
    expect(requestMatchesStateFilter('APPLIED', 'GROUP:IN_PROGRESS')).toBe(false)
    expect(requestMatchesStateFilter('COMPLETED', 'GROUP:COMPLETED')).toBe(true)
    expect(requestMatchesStateFilter('CANCELLED', 'GROUP:CLOSED')).toBe(true)
  })

  it('initializes a bounded server group from the deep link without exact-state eviction', async () => {
    window.history.replaceState(
      {},
      '',
      '/?page=change-management&crStateGroup=IN_PROGRESS',
    )
    const reviewing = changeRequest({ id: 'change-review', number: 'CR-REVIEW', state: 'IN_REVIEW' })
    const applying = changeRequest({ id: 'change-apply', number: 'CR-APPLY', state: 'APPLYING' })
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/change-requests/summaries?limit=25&state_group=IN_PROGRESS') {
        return Promise.resolve(summaryList([reviewing, applying]))
      }
      throw new Error(`Unexpected request: ${path}`)
    })

    renderPage(apiClient(request))

    expect(await screen.findByText('CR-REVIEW')).toBeInTheDocument()
    expect(screen.getByText('CR-APPLY')).toBeInTheDocument()
    expect(screen.getByLabelText('상태 필터')).toHaveValue('GROUP:IN_PROGRESS')
  })

  it('renders one consolidated overview while keeping Monitoring independently navigable', async () => {
    const onNavigate = vi.fn()
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/change-requests/summaries?limit=25') return Promise.resolve(summaryList([]))
      throw new Error(`Unexpected request: ${path}`)
    })
    render(<GovernancePage
      client={apiClient(request)}
      requesterName="Test Requester"
      onNavigate={onNavigate}
      onStepUp={vi.fn(() => Promise.resolve())}
      onPasswordReauth={vi.fn(() => Promise.resolve())}
      onEnroll={vi.fn(() => Promise.resolve())}
    />)

    const combined = screen.getByRole('region', { name: '현재 권한과 기간의 스키마별 변경 현황' })
      .closest('.governance-combined-overview')
    expect(combined).toHaveAccessibleName('통합 변경 현황')
    expect(within(combined as HTMLElement).queryByTestId('detected-change-cr-panel')).not.toBeInTheDocument()
    fireEvent.click(within(combined as HTMLElement).getByRole('button', { name: 'Monitoring Dashboard' }))
    expect(onNavigate).toHaveBeenCalledWith('monitoring')
    const disclosure = screen.getByRole('button', { name: /감지 변경과 CR 연결/ })
    expect(disclosure).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByTestId('detected-change-history-panel')).not.toBeInTheDocument()
    fireEvent.click(disclosure)
    expect(disclosure).toHaveAttribute('aria-expanded', 'true')
    expect(await screen.findByTestId('detected-change-history-panel')).toBeInTheDocument()
    expect(await screen.findByText('현재 권한 범위에서 조회 가능한 요청이 없습니다.')).toBeInTheDocument()
  })

  it('distinguishes loading from an authorized empty window', async () => {
    const list = deferred<ReturnType<typeof summaryList>>()
    const request = vi.fn((): Promise<unknown> => list.promise)
    renderPage(apiClient(request))

    expect(screen.queryByTestId('detected-change-cr-panel')).not.toBeInTheDocument()
    const loading = screen.getByText('데이터를 불러오는 중입니다.')
    expect(loading.closest('.dense-table-frame')).toHaveAttribute('aria-busy', 'true')
    expect(screen.getByText('현재 조회된 요청 · 페이지당 최대 25건')).toBeInTheDocument()

    act(() => list.resolve(summaryList([])))
    expect(await screen.findByText('현재 권한 범위에서 조회 가능한 요청이 없습니다.')).toBeInTheDocument()
    expect(screen.getByText('0건 표시')).toBeInTheDocument()
  })

  it('reloads the authoritative summary when the KST date range changes', async () => {
    const request = vi.fn((path: string): Promise<unknown> => {
      void path
      return Promise.resolve(summaryList([]))
    })
    renderPage(apiClient(request, true))

    await screen.findByText('현재 권한 범위에서 조회 가능한 요청이 없습니다.')
    fireEvent.change(screen.getByLabelText('조회 시작일'), { target: { value: '2026-08-01' } })
    fireEvent.change(screen.getByLabelText('조회 종료일'), { target: { value: '2026-08-03' } })

    await waitFor(() => expect(request.mock.calls.some(([path]) => {
      const url = new URL(path, 'https://datariver.invalid')
      return url.pathname === '/change-requests/summaries'
        && url.searchParams.get('date_from') === '2026-08-01'
        && url.searchParams.get('date_to') === '2026-08-03'
    })).toBe(true))
  })

  it('uses CSP-safe fixed identity and metric column tokens and exposes clipped values in titles', async () => {
    const schemaOverview: ChangeRequestSchemaOverview = {
      platform: 'postgres',
      database_name: 'semiconductor_warehouse',
      schema_name: 'semiconductor_seed_with_a_long_authorized_name',
      system_id: 'system-1',
      system_code: 'FAB',
      system_name: 'Fabrication data platform',
      assignees: [],
      event_count: 7,
      unprogressed_event_count: 2,
      pending_count: 0,
      total_count: 0,
      received_count: 0,
      recheck_count: 0,
      testing_count: 0,
      final_review_count: 0,
      completed_count: 0,
    }
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/change-requests/summaries?limit=25') {
        return Promise.resolve(summaryList([], null, [schemaOverview]))
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    renderPage(apiClient(request))

    const region = await screen.findByRole('region', {
      name: '현재 권한과 기간의 스키마별 변경 현황',
    })
    const columns = Array.from(region.querySelectorAll('col'))
    expect(columns).toHaveLength(10)
    expect(columns.every((column) => !column.hasAttribute('style'))).toBe(true)
    expect(columns[0]).toHaveClass('governance-status-col-schema')
    expect(columns[1]).toHaveClass('governance-status-col-system')
    expect(columns.slice(2).every((column) => (
      column.classList.contains('governance-status-col-metric')
    ))).toBe(true)
    expect(screen.getByText(schemaOverview.schema_name)).toHaveClass('governance-overview-primary')
    expect(screen.getByText(schemaOverview.schema_name)).toHaveAttribute(
      'title',
      schemaOverview.schema_name,
    )
    expect(screen.getByText(schemaOverview.system_name!)).toHaveAttribute(
      'title',
      schemaOverview.system_name,
    )
    expect(screen.getByText(schemaOverview.schema_name).closest('button')).toBeNull()
    expect(screen.queryByRole('combobox', { name: /담당자/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: `${schemaOverview.schema_name} 이벤트 7건 열기` }))
    expect(screen.getByTestId('detected-change-cr-panel')).toHaveTextContent(schemaOverview.schema_name)
  })

  it('keeps concurrent resolved, unmapped, and ambiguous row identities aligned with drawer selection', async () => {
    const common = {
      platform: 'postgres', database_name: 'warehouse', schema_name: 'shared',
      system_code: null, system_name: null, assignees: [], unprogressed_event_count: 0,
      pending_count: 0, total_count: 0, received_count: 0, recheck_count: 0,
      testing_count: 0, final_review_count: 0, completed_count: 0,
    }
    const rows: ChangeRequestSchemaOverview[] = [
      { ...common, system_id: 'system-1', system_resolution: 'RESOLVED', system_code: 'ONE', system_name: 'One', event_count: 2 },
      { ...common, system_id: null, system_resolution: 'UNMAPPED', event_count: 3 },
      { ...common, system_id: null, system_resolution: 'AMBIGUOUS', event_count: 4 },
    ]
    const request = vi.fn((path: string): Promise<unknown> => path === '/change-requests/summaries?limit=25'
      ? Promise.resolve(summaryList([], null, rows))
      : Promise.reject(new Error(`Unexpected request: ${path}`)))
    renderPage(apiClient(request))

    await screen.findByRole('button', { name: 'shared 이벤트 2건 열기' })
    fireEvent.click(screen.getByRole('button', { name: 'shared 이벤트 2건 열기' }))
    expect(screen.getByTestId('detected-change-cr-panel')).toHaveAttribute('data-system-id', 'system-1')
    expect(screen.getByTestId('detected-change-cr-panel')).toHaveAttribute('data-system-resolution', 'RESOLVED')
    fireEvent.click(screen.getByRole('button', { name: 'shared 이벤트 3건 열기' }))
    expect(screen.getByTestId('detected-change-cr-panel')).toHaveAttribute('data-system-id', '')
    expect(screen.getByTestId('detected-change-cr-panel')).toHaveAttribute('data-system-resolution', 'UNMAPPED')
    fireEvent.click(screen.getByRole('button', { name: 'shared 이벤트 4건 열기' }))
    expect(screen.getByTestId('detected-change-cr-panel')).toHaveAttribute('data-system-resolution', 'AMBIGUOUS')
  })

  it('renders the bounded dense list and opens independent CR creation', async () => {
    const existing = changeRequest()
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      if (path === '/change-requests/summaries?limit=25') return Promise.resolve(summaryList([existing]))
      if (path === '/change-requests/systems') return Promise.resolve({
        items: [{ id: 'system-1', code: 'FAB', name: 'Fabrication' }],
      })
      throw new Error(`Unexpected request: ${path} ${options?.method ?? 'GET'}`)
    })
    renderPage(apiClient(request))

    expect(await screen.findByText(existing.number)).toBeInTheDocument()
    const listRegion = screen.getByRole('region', { name: '변경 요청 목록' })
    expect(within(listRegion).getAllByRole('columnheader').map((header) => header.textContent)).toEqual([
      'CR-No', 'CR명', '유형', '대상스키마', '상태', '등급', '요청자', '담당자',
      '요청일', '요청납기', '중요도', '긴급도', '버전',
    ])
    expect(within(listRegion).getByText('engineering')).toBeInTheDocument()
    expect(within(listRegion).getByText('요청자 김')).toBeInTheDocument()
    expect(within(listRegion).getByText('담당자 이')).toBeInTheDocument()
    expect(within(listRegion).queryByText(existing.items[0]!.target_ref)).not.toBeInTheDocument()
    expect(within(listRegion).getByLabelText('현재 권한 범위의 변경 요청 스크롤 영역')).toHaveClass('dense-table-frame')
    expect(within(listRegion).getByText(/하단 스크롤바 또는 Shift\+휠/)).toBeInTheDocument()
    expect(screen.getByText('1건 표시')).toBeInTheDocument()
    expect(screen.queryByLabelText('DataHub 대상 URN')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('승인 대상 JSON')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '신규 CR 신청' }))
    expect(await screen.findByRole('dialog', { name: '신규 CR 신청' })).toBeInTheDocument()
    expect(screen.getByLabelText('요청내용')).toBeInTheDocument()
    expect(screen.getByLabelText('요청사유')).toHaveAttribute('rows', '1')
    expect(screen.getByLabelText('요청사유')).toHaveClass('governance-request-reason')
    expect(screen.getByLabelText('요청자')).toHaveValue('Test Requester')
    const titleInput = screen.getByLabelText('변경요청 제목')
    titleInput.focus()
    fireEvent.change(titleInput, { target: { value: 'Lineage metadata remediation' } })
    expect(titleInput).toHaveFocus()
    expect(titleInput).toHaveValue('Lineage metadata remediation')
    expect(screen.queryByRole('link', { name: '신규 CR 신청' })).not.toBeInTheDocument()
    const listOptions = request.mock.calls.find(([path]) => path === '/change-requests/summaries?limit=25')?.[1]
    expect(listOptions?.signal).toBeInstanceOf(AbortSignal)
  })

  it('keeps only the current authorized summary page and supports bounded cursor navigation', async () => {
    const first = changeRequest()
    const second = changeRequest({
      id: 'change-2',
      number: 'CR-2026-2',
      title: 'Second page request',
    })
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      void options
      if (path === '/change-requests/summaries?limit=25') {
        return Promise.resolve(summaryList([first], 'cursor-page-2'))
      }
      if (path === '/change-requests/summaries?limit=25&cursor=cursor-page-2') {
        return Promise.resolve(summaryList([second]))
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    renderPage(apiClient(request))

    expect(await screen.findByText(first.number)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '다음' }))
    expect(await screen.findByText(second.number)).toBeInTheDocument()
    expect(screen.queryByText(first.number)).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '이전' }))
    expect(await screen.findByText(first.number)).toBeInTheDocument()
    expect(screen.queryByText(second.number)).not.toBeInTheDocument()
    const secondPageOptions = request.mock.calls.find(
      ([path]) => path === '/change-requests/summaries?limit=25&cursor=cursor-page-2',
    )?.[1]
    expect(secondPageOptions?.signal).toBeInstanceOf(AbortSignal)
  })

  it('renders every selected table and column under one shared hierarchical target table', async () => {
    const existing = changeRequest()
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/change-requests/summaries?limit=25') return Promise.resolve(summaryList([existing]))
      if (path === '/change-requests/systems') return Promise.resolve({
        items: [{ id: 'system-1', code: 'FAB', name: 'Fabrication' }],
      })
      if (path.startsWith('/change-requests/targets?system_id=system-1&q=wafer')) return Promise.resolve({ items: [governedCatalogAsset] })
      if (path === `/change-requests/targets/${governedCatalogAsset.id}?system_id=system-1`) return Promise.resolve({
        ...governedCatalogAsset,
        description: 'Current wafer event table',
        ownership: [], glossary_terms: [], quality: {}, projection_source_version: 'projection-v1', source_version: 'source-v1',
        schema_fields: [{
          fieldPath: 'wafer_id', nativeDataType: 'uuid', description: 'Wafer identifier',
          globalTags: { tags: [{ tag: { name: 'field:identifier' } }] },
          glossaryTerms: { terms: [{ term: { name: 'record_identifier' } }] },
        }],
      })
      return Promise.reject(new Error(`Unexpected request: ${path}`))
    })
    renderPage(apiClient(request))

    fireEvent.click(await screen.findByRole('button', { name: '신규 CR 신청' }))
    fireEvent.change(screen.getByLabelText('변경 대상 검색'), { target: { value: 'wafer' } })
    fireEvent.click(await screen.findByRole('button', { name: /wafer_events/ }))
    expect(await screen.findByDisplayValue('Current wafer event table')).toBeInTheDocument()
    const targetTable = screen.getByRole('table', { name: '변경 대상 테이블 및 컬럼' })
    expect(within(targetTable).getAllByRole('columnheader').map((header) => header.textContent?.trim())).toEqual([
      'TABLE / COLUMN NAME', 'SCHEMA', 'DESC (LOGICAL NAME)', '비고 (REMARKS)', '관리',
    ])
    expect(screen.getAllByRole('table', { name: '변경 대상 테이블 및 컬럼' })).toHaveLength(1)
    const addManualButton = screen.getByRole('button', { name: /ADD NEW TABLE MANUALLY/ })
    expect(targetTable.compareDocumentPosition(addManualButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()

    fireEvent.change(screen.getByLabelText('wafer_events 기존 컬럼 선택'), { target: { value: 'wafer_id' } })
    expect(await screen.findByDisplayValue('Wafer identifier')).toBeInTheDocument()
    expect(targetTable.querySelectorAll('.governance-target-column-branch')).toHaveLength(1)
    expect(within(targetTable).getAllByRole('row')).toHaveLength(3)

    fireEvent.click(addManualButton)
    fireEvent.change(screen.getByLabelText('신규 테이블 2 테이블명'), { target: { value: 'wafer_summary' } })
    fireEvent.change(screen.getByLabelText('신규 테이블 2 스키마'), { target: { value: 'quality' } })
    fireEvent.click(screen.getByRole('button', { name: 'wafer_summary 컬럼 추가' }))
    fireEvent.change(screen.getByLabelText('wafer_summary 컬럼 1 이름'), { target: { value: 'wafer_id' } })

    expect(screen.getAllByRole('table', { name: '변경 대상 테이블 및 컬럼' })).toHaveLength(1)
    expect(within(targetTable).getAllByRole('columnheader', { name: 'TABLE / COLUMN NAME' })).toHaveLength(1)
    expect(within(targetTable).getAllByRole('row')).toHaveLength(5)
    expect(targetTable.querySelectorAll('.governance-target-column-branch')).toHaveLength(2)
  })

  it('filters with the exact server state contract', async () => {
    const existing = changeRequest()
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      void options
      if (path === '/change-requests/summaries?limit=25') return Promise.resolve(summaryList([existing]))
      throw new Error(`Unexpected request: ${path}`)
    })
    renderPage(apiClient(request))
    await screen.findByText(existing.number)

    fireEvent.change(screen.getByLabelText('상태 필터'), { target: { value: 'IN_REVIEW' } })
    expect(await screen.findByText('선택한 상태에서 조회 가능한 요청이 없습니다.')).toBeInTheDocument()
    const filterOptions = request.mock.calls.find(([path]) => path === '/change-requests/summaries?limit=25')?.[1]
    expect(filterOptions?.signal).toBeInstanceOf(AbortSignal)
  })

  it('opens a freshly authorized accessible detail by keyboard and restores focus', async () => {
    const existing = changeRequest()
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      void options
      if (path === '/change-requests/summaries?limit=25') return Promise.resolve(summaryList([existing]))
      if (path === `/change-requests/${existing.id}`) return Promise.resolve(existing)
      throw new Error(`Unexpected request: ${path}`)
    })
    renderPage(apiClient(request))
    const dialog = await openDetail(existing)

    expect(await within(dialog).findByText('REQUEST REASON')).toBeInTheDocument()
    expect(within(dialog).getByRole('table', { name: 'CR 변경 대상' })).toBeInTheDocument()
    expect(within(dialog).getByLabelText(`${existing.items[0]!.target_ref} 비고`)).toHaveAttribute('readonly')
    expect(within(dialog).getByText('현재 요청 수정 불가')).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Edit Request' })).toBeDisabled()
    expect(within(dialog).getByText('화면의 명령은 현재 상태를 기준으로 한 힌트입니다.')).toBeInTheDocument()
    expect(screen.queryByLabelText('DataHub 대상 URN')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('승인 대상 JSON')).not.toBeInTheDocument()

    const row = screen.getAllByText(existing.number)[0]!.closest('tr')
    fireEvent.click(within(dialog).getByRole('button', { name: '닫기' }))
    expect(screen.queryByRole('dialog', { name: `${existing.number} · ${existing.title}` })).not.toBeInTheDocument()
    expect(row).toHaveFocus()
    const detailOptions = request.mock.calls.find(([path]) => path === `/change-requests/${existing.id}`)?.[1]
    expect(detailOptions?.signal).toBeInstanceOf(AbortSignal)
  })

  it('renders the bounded read-only reverse change history with KST detected-at fallback', async () => {
    const existing = changeRequest()
    const event = reverseEvent()
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      void options
      if (path === '/change-requests/summaries?limit=25') return Promise.resolve(summaryList([existing]))
      if (path === `/change-requests/${existing.id}`) return Promise.resolve(existing)
      if (path === `/change-requests/${existing.id}/attachments/page?limit=25`) return Promise.resolve({ items: [], page: { limit: 25, next_cursor: null } })
      if (path === `/change-requests/${existing.id}/apply-report`) return Promise.reject(new Error('No apply report yet.'))
      if (path === `/change-requests/${existing.id}/change-history?limit=50`) return Promise.resolve({ change_request_id: existing.id, items: [event], next_cursor: null, limit: 50 })
      throw new Error(`Unexpected request: ${path}`)
    })
    const dialog = await openDetailAfterRender(request, existing)

    const table = await within(dialog).findByRole('table', { name: 'CR 연결 변경 이력' })
    expect(within(table).getByText('DOCUMENTATION')).toBeInTheDocument()
    expect(within(table).getByText('UPSERT')).toBeInTheDocument()
    expect(within(table).getByText(event.entity_key)).toBeInTheDocument()
    expect(within(table).getByText('RECEIVED')).toBeInTheDocument()
    expect(within(table).getByText('change-1 · round 1')).toBeInTheDocument()
    expect(within(table).getByText('source_occurred_at 없음 · detected_at 대체')).toBeInTheDocument()
    expect(within(table).getByText(/12시 4분 5초/)).toBeInTheDocument()
    const historyOptions = request.mock.calls.find(([path]) => path.endsWith('/change-history?limit=50'))?.[1]
    expect(historyOptions?.signal).toBeInstanceOf(AbortSignal)
    expect(historyOptions?.cache).toBe('no-store')
  })

  it('shows an authorized empty reverse history independently from CR detail', async () => {
    const existing = changeRequest()
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/change-requests/summaries?limit=25') return Promise.resolve(summaryList([existing]))
      if (path === `/change-requests/${existing.id}`) return Promise.resolve(existing)
      if (path === `/change-requests/${existing.id}/attachments/page?limit=25`) return Promise.resolve({ items: [], page: { limit: 25, next_cursor: null } })
      if (path === `/change-requests/${existing.id}/apply-report`) return Promise.reject(new Error('No apply report yet.'))
      if (path === `/change-requests/${existing.id}/change-history?limit=50`) return Promise.resolve({ change_request_id: existing.id, items: [], next_cursor: null, limit: 50 })
      throw new Error(`Unexpected request: ${path}`)
    })
    const dialog = await openDetailAfterRender(request, existing)

    expect(await within(dialog).findByText('현재 권한 범위에서 연결된 변경 이력이 없습니다.')).toBeInTheDocument()
    expect(within(dialog).getByText('REQUEST REASON')).toBeInTheDocument()
  })

  it('keeps reverse-history denial isolated without closing or failing the CR dialog', async () => {
    const existing = changeRequest()
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/change-requests/summaries?limit=25') return Promise.resolve(summaryList([existing]))
      if (path === `/change-requests/${existing.id}`) return Promise.resolve(existing)
      if (path === `/change-requests/${existing.id}/attachments/page?limit=25`) return Promise.resolve({ items: [], page: { limit: 25, next_cursor: null } })
      if (path === `/change-requests/${existing.id}/apply-report`) return Promise.reject(new Error('No apply report yet.'))
      if (path === `/change-requests/${existing.id}/change-history?limit=50`) return Promise.reject(problem(403, '변경 이력 조회 권한이 없습니다.'))
      throw new Error(`Unexpected request: ${path}`)
    })
    const dialog = await openDetailAfterRender(request, existing)

    expect(await within(dialog).findByText('변경 이력 조회 권한이 없습니다.')).toBeInTheDocument()
    expect(within(dialog).getByText('REQUEST REASON')).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: '닫기' })).toBeEnabled()
  })

  it('aborts and rejects stale reverse history across close and CR id switch', async () => {
    const first = changeRequest()
    const second = changeRequest({ id: 'change-2', number: 'CR-2026-2', title: 'Second governed change' })
    const staleHistory = deferred<unknown>()
    let firstHistorySignal: AbortSignal | undefined
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      if (path === '/change-requests/summaries?limit=25') return Promise.resolve(summaryList([first, second]))
      if (path === `/change-requests/${first.id}`) return Promise.resolve(first)
      if (path === `/change-requests/${second.id}`) return Promise.resolve(second)
      if (path.endsWith('/attachments/page?limit=25')) return Promise.resolve({ items: [], page: { limit: 25, next_cursor: null } })
      if (path.endsWith('/apply-report')) return Promise.reject(new Error('No apply report yet.'))
      if (path === `/change-requests/${first.id}/change-history?limit=50`) {
        firstHistorySignal = options?.signal ?? undefined
        return staleHistory.promise
      }
      if (path === `/change-requests/${second.id}/change-history?limit=50`) return Promise.resolve({
        change_request_id: second.id,
        items: [reverseEvent({ event_id: 'c'.repeat(64), entity_key: 'second.current', current_primary: { change_request_id: second.id, change_request_round: 1 } })],
        next_cursor: null,
        limit: 50,
      })
      throw new Error(`Unexpected request: ${path}`)
    })
    renderPage(apiClient(request))
    const firstDialog = await openDetail(first)
    await within(firstDialog).findByText('연결된 변경 이력을 불러오는 중입니다.')
    fireEvent.click(within(firstDialog).getByRole('button', { name: '닫기' }))
    expect(firstHistorySignal?.aborted).toBe(true)

    const secondDialog = await openDetail(second)
    expect(await within(secondDialog).findByText('second.current')).toBeInTheDocument()
    act(() => staleHistory.resolve({ change_request_id: first.id, items: [reverseEvent({ entity_key: 'first.stale' })], next_cursor: null, limit: 50 }))
    await waitFor(() => expect(within(secondDialog).queryByText('first.stale')).not.toBeInTheDocument())
    expect(within(secondDialog).getByText('second.current')).toBeInTheDocument()
  })

  it('never issues a mutation request while loading reverse change history', async () => {
    const existing = changeRequest()
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      void options
      if (path === '/change-requests/summaries?limit=25') return Promise.resolve(summaryList([existing]))
      if (path === `/change-requests/${existing.id}`) return Promise.resolve(existing)
      if (path === `/change-requests/${existing.id}/attachments/page?limit=25`) return Promise.resolve({ items: [], page: { limit: 25, next_cursor: null } })
      if (path === `/change-requests/${existing.id}/apply-report`) return Promise.reject(new Error('No apply report yet.'))
      if (path === `/change-requests/${existing.id}/change-history?limit=50`) return Promise.resolve({ change_request_id: existing.id, items: [], next_cursor: null, limit: 50 })
      throw new Error(`Unexpected request: ${path}`)
    })
    await openDetailAfterRender(request, existing)
    await screen.findByText('현재 권한 범위에서 연결된 변경 이력이 없습니다.')

    expect(request.mock.calls.every(([, options]) => !options?.method || options.method === 'GET')).toBe(true)
  })

  it('opens the bounded revision editor only when the server allows it and shows the new round', async () => {
    const manualItem = {
      ...changeRequest().items[0]!,
      id: 'manual-item-1',
      target_type: 'PROPOSED_DATASET_CHANGE_INTAKE',
      target_ref: 'urn:datariver:proposed-dataset:manual-item-1',
      aspect_name: 'changeIntake',
      operation: 'CREATE',
      after_document: {
        contract: 'change-intake-v1',
        kind: 'MANUAL',
        database_name: 'analytics',
        schema_name: 'quality',
        table_name: 'wafer_summary',
        owner: 'Data Engineering',
        description: 'Current summary description',
        requested_change: 'Create the governed summary',
        tags: ['tier:silver'],
        terms: ['Wafer'],
        columns: [{
          field_path: 'wafer_id',
          data_type: 'uuid',
          description: 'Wafer identifier',
          requested_change: 'Create the identifier',
          tags: [],
          terms: [],
        }],
      },
      target_asset_id: null,
      target_asset_type: null,
      target_system_id: null,
      target_domain_id: null,
      target_owner_department_id: null,
      target_classification: null,
      target_lifecycle: null,
      target_source_version: null,
      target_observed_at: null,
      target_binding_hash: null,
      routing_system_id: 'system-1',
    }
    const editable = changeRequest({
      request_type: 'CHANGE_INTAKE',
      title: 'Original intake title',
      description: 'Original reason\nOriginal content',
      state: 'CHANGES_REQUESTED',
      revision_allowed: true,
      items: [manualItem],
      rounds: [{
        id: 'round-1',
        round_number: 1,
        submitted_by: 'subject-1',
        submitted_at: '2026-08-02T01:02:03Z',
        closed_at: null,
        evidence_hash: 'a'.repeat(64),
        revision_kind: 'INITIAL',
        title: 'Original intake title',
        request_date: '2026-08-02',
        request_department: 'Data Platform',
        request_reason: 'Original reason',
        request_content: 'Original content',
        requested_due_date: '2026-08-20',
        priority: 'HIGH',
        urgency: 'URGENT',
        classification: 'CONFIDENTIAL',
        selected_system_id: 'system-1',
      }],
    })
    const revised = changeRequest({
      ...editable,
      title: 'Revised intake title',
      state: 'REGISTERED',
      revision_allowed: false,
      current_round_id: 'round-2',
      current_round_number: 2,
      version: 8,
      rounds: [...editable.rounds, {
        ...editable.rounds[0]!,
        id: 'round-2',
        round_number: 2,
        revision_kind: 'EDITED',
        title: 'Revised intake title',
        evidence_hash: 'b'.repeat(64),
      }],
    })
    let mutationCompleted = false
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      if (path === '/change-requests/summaries?limit=25') {
        return Promise.resolve(summaryList([mutationCompleted ? revised : editable]))
      }
      if (path === `/change-requests/${editable.id}`) return Promise.resolve(editable)
      if (path === `/change-requests/${editable.id}/attachments/page?limit=25`) {
        return Promise.resolve({ items: [], page: { limit: 25, next_cursor: null } })
      }
      if (path === `/change-requests/${editable.id}/apply-report`) {
        return Promise.reject(new Error('No apply report yet.'))
      }
      if (path === `/change-requests/${editable.id}/revisions` && options?.method === 'POST') {
        mutationCompleted = true
        return Promise.resolve(revised)
      }
      throw new Error(`Unexpected request: ${path} ${options?.method ?? 'GET'}`)
    })
    renderPage(apiClient(request))
    const detailDialog = await openDetail(editable)

    const edit = within(detailDialog).getByRole('button', { name: 'Edit Request' })
    expect(edit).toBeEnabled()
    fireEvent.click(edit)
    const revisionDialog = await screen.findByRole('dialog', {
      name: `${editable.number} 수정 및 재상신`,
    })
    expect(within(revisionDialog).getByLabelText('관련 시스템')).toHaveAttribute('readonly')
    expect(within(revisionDialog).getByLabelText('변경요청 제목')).toHaveValue('Original intake title')
    expect(within(revisionDialog).getByLabelText('신규 테이블 1 테이블명')).toHaveValue('wafer_summary')
    fireEvent.change(within(revisionDialog).getByLabelText('변경요청 제목'), {
      target: { value: 'Revised intake title' },
    })
    fireEvent.click(within(revisionDialog).getByRole('button', { name: '수정 재상신' }))

    await waitFor(() => expect(request.mock.calls.filter(
      ([path]) => path === `/change-requests/${editable.id}/revisions`,
    )).toHaveLength(1))
    const options = request.mock.calls.find(
      ([path]) => path === `/change-requests/${editable.id}/revisions`,
    )?.[1]
    expect(options).toMatchObject({ method: 'POST', ifMatch: '"7"' })
    expect(options?.idempotencyKey).toMatch(/^change-request-revision-/)

    const revisedDialog = await screen.findByRole('dialog', {
      name: `${revised.number} · ${revised.title}`,
    })
    expect(within(revisedDialog).getByText('접수 · REGISTERED')).toBeInTheDocument()
    expect(within(revisedDialog).getByText('8')).toBeInTheDocument()
    expect(within(revisedDialog).getByRole('button', { name: 'Edit Request' })).toBeDisabled()
  })

  it('aborts and discards a late attachment upload when another CR becomes current', async () => {
    const first = changeRequest()
    const second = changeRequest({
      id: 'change-2',
      number: 'CR-2026-2',
      title: 'Second governed change',
    })
    const upload = deferred<unknown>()
    let uploadSignal: AbortSignal | undefined
    let firstAttachmentReads = 0
    const firstAttachment = {
      id: 'attachment-a',
      kind: 'REQUEST' as const,
      round_id: first.current_round_id,
      original_name: 'must-not-leak-from-a.txt',
      serial_number: 1,
      content_type: 'text/plain',
      size_bytes: 12,
      content_sha256: 'a'.repeat(64),
      created_at: '2026-07-17T03:00:00Z',
    }
    const secondAttachment = {
      ...firstAttachment,
      id: 'attachment-b',
      round_id: second.current_round_id,
      original_name: 'belongs-to-b.txt',
      content_sha256: 'b'.repeat(64),
    }
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      if (path === '/change-requests/summaries?limit=25') {
        return Promise.resolve(summaryList([first, second]))
      }
      if (path === `/change-requests/${first.id}`) return Promise.resolve(first)
      if (path === `/change-requests/${second.id}`) return Promise.resolve(second)
      if (path === `/change-requests/${first.id}/attachments` && options?.method === 'POST') {
        uploadSignal = options.signal ?? undefined
        return upload.promise
      }
      if (path === `/change-requests/${first.id}/attachments/page?limit=25`) {
        firstAttachmentReads += 1
        return Promise.resolve({
          items: firstAttachmentReads === 1 ? [] : [firstAttachment],
          page: { limit: 25, next_cursor: null },
        })
      }
      if (path === `/change-requests/${second.id}/attachments/page?limit=25`) {
        return Promise.resolve({
          items: [secondAttachment],
          page: { limit: 25, next_cursor: null },
        })
      }
      if (path.endsWith('/apply-report')) return Promise.reject(new Error('No apply report yet.'))
      throw new Error(`Unexpected request: ${path} ${options?.method ?? 'GET'}`)
    })
    renderPage(apiClient(request))
    const firstDialog = await openDetail(first)
    await within(firstDialog).findByText('등록된 요청 첨부파일이 없습니다.')

    fireEvent.change(within(firstDialog).getByLabelText('클릭하여 신규 파일 첨부'), {
      target: { files: [new File(['evidence'], 'evidence.txt', { type: 'text/plain' })] },
    })
    fireEvent.click(within(firstDialog).getByRole('button', { name: '1개 파일 저장' }))
    await waitFor(() => expect(uploadSignal).toBeInstanceOf(AbortSignal))

    const secondRow = screen.getByText(second.number).closest('tr')
    if (!secondRow) throw new Error('Second change request row was not rendered')
    fireEvent.click(secondRow)
    const secondDialog = await screen.findByRole('dialog', {
      name: `${second.number} · ${second.title}`,
    })
    expect(uploadSignal?.aborted).toBe(true)
    fireEvent.change(within(secondDialog).getByLabelText('클릭하여 신규 파일 첨부'), {
      target: { files: [new File(['belongs to B'], 'belongs-to-b-new.txt', { type: 'text/plain' })] },
    })
    expect(
      await within(secondDialog).findByRole('button', { name: '1개 파일 저장' }),
    ).toBeInTheDocument()

    act(() => upload.resolve({}))
    expect(await within(secondDialog).findByText(secondAttachment.original_name)).toBeInTheDocument()
    expect(firstAttachmentReads).toBe(1)
    expect(within(secondDialog).queryByText(firstAttachment.original_name)).not.toBeInTheDocument()
    expect(within(secondDialog).getByRole('button', { name: '1개 파일 저장' })).toBeInTheDocument()
  })

  it('aborts and discards a late TEST evidence success before another CR becomes current', async () => {
    const first = changeRequest({ state: 'TESTING' })
    const second = changeRequest({
      id: 'change-2',
      number: 'CR-2026-2',
      title: 'Second testing change',
      state: 'TESTING',
    })
    const testRun = deferred<ChangeRequestRecord>()
    let testRunSignal: AbortSignal | undefined
    let firstDetailReads = 0
    let secondDetailReads = 0
    const testAttachment = (record: ChangeRequestRecord) => ({
      id: `test-${record.id}`,
      kind: 'TEST' as const,
      round_id: record.current_round_id,
      original_name: `${record.id}.txt`,
      serial_number: 1,
      content_type: 'text/plain',
      size_bytes: 12,
      content_sha256: record.id.padEnd(64, 'a').slice(0, 64),
      created_at: '2026-07-17T03:00:00Z',
    })
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      if (path === '/change-requests/summaries?limit=25') {
        return Promise.resolve(summaryList([first, second]))
      }
      if (path === `/change-requests/${first.id}`) {
        firstDetailReads += 1
        return Promise.resolve(first)
      }
      if (path === `/change-requests/${second.id}`) {
        secondDetailReads += 1
        return Promise.resolve(second)
      }
      if (path === `/change-requests/${first.id}/attachments/page?limit=25`) {
        return Promise.resolve({ items: [testAttachment(first)], page: { limit: 25, next_cursor: null } })
      }
      if (path === `/change-requests/${second.id}/attachments/page?limit=25`) {
        return Promise.resolve({ items: [testAttachment(second)], page: { limit: 25, next_cursor: null } })
      }
      if (path === `/change-requests/${first.id}/test-runs` && options?.method === 'POST') {
        testRunSignal = options.signal ?? undefined
        return testRun.promise
      }
      if (path.endsWith('/apply-report')) return Promise.reject(new Error('No apply report yet.'))
      throw new Error(`Unexpected request: ${path} ${options?.method ?? 'GET'}`)
    })
    renderPage(apiClient(request))
    const firstDialog = await openDetail(first)
    expect((await within(firstDialog).findAllByText(`${first.id}.txt`)).length).toBeGreaterThan(0)
    fireEvent.change(await within(firstDialog).findByLabelText('테스트 대상 시스템'), {
      target: { value: 'system-1' },
    })
    fireEvent.change(within(firstDialog).getByLabelText('테스트 증거 파일'), {
      target: { value: `test-${first.id}` },
    })
    fireEvent.change(within(firstDialog).getByLabelText('테스트 결과 요약'), {
      target: { value: 'A evidence must not refresh after switching.' },
    })
    fireEvent.click(within(firstDialog).getByRole('button', { name: '승인 요청' }))
    await waitFor(() => expect(testRunSignal).toBeInstanceOf(AbortSignal))

    const secondRow = screen.getByText(second.number).closest('tr')
    if (!secondRow) throw new Error('Second change request row was not rendered')
    fireEvent.click(secondRow)
    const secondDialog = await screen.findByRole('dialog', {
      name: `${second.number} · ${second.title}`,
    })
    expect(testRunSignal?.aborted).toBe(true)

    act(() => testRun.resolve(first))
    await waitFor(() => expect(secondDetailReads).toBe(1))
    expect(firstDetailReads).toBe(1)
    expect(within(secondDialog).getByLabelText('테스트 결과 요약')).toHaveValue('')
  })

  it('does not surface a late TEST evidence error in a newly selected CR', async () => {
    const first = changeRequest({ state: 'TESTING' })
    const second = changeRequest({
      id: 'change-2',
      number: 'CR-2026-2',
      title: 'Second testing change',
      state: 'TESTING',
    })
    const testRun = deferred<ChangeRequestRecord>()
    let testRunSignal: AbortSignal | undefined
    const attachment = {
      id: 'test-a',
      kind: 'TEST' as const,
      round_id: first.current_round_id,
      original_name: 'test-a.txt',
      serial_number: 1,
      content_type: 'text/plain',
      size_bytes: 12,
      content_sha256: 'a'.repeat(64),
      created_at: '2026-07-17T03:00:00Z',
    }
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      if (path === '/change-requests/summaries?limit=25') {
        return Promise.resolve(summaryList([first, second]))
      }
      if (path === `/change-requests/${first.id}`) return Promise.resolve(first)
      if (path === `/change-requests/${second.id}`) return Promise.resolve(second)
      if (path.endsWith('/attachments/page?limit=25')) {
        return Promise.resolve({
          items: [{ ...attachment, round_id: path.includes(first.id) ? first.current_round_id : second.current_round_id }],
          page: { limit: 25, next_cursor: null },
        })
      }
      if (path === `/change-requests/${first.id}/test-runs` && options?.method === 'POST') {
        testRunSignal = options.signal ?? undefined
        return testRun.promise
      }
      if (path.endsWith('/apply-report')) return Promise.reject(new Error('No apply report yet.'))
      throw new Error(`Unexpected request: ${path} ${options?.method ?? 'GET'}`)
    })
    renderPage(apiClient(request))
    const firstDialog = await openDetail(first)
    expect((await within(firstDialog).findAllByText(attachment.original_name)).length).toBeGreaterThan(0)
    fireEvent.change(await within(firstDialog).findByLabelText('테스트 대상 시스템'), {
      target: { value: 'system-1' },
    })
    fireEvent.change(within(firstDialog).getByLabelText('테스트 증거 파일'), {
      target: { value: attachment.id },
    })
    fireEvent.change(within(firstDialog).getByLabelText('테스트 결과 요약'), {
      target: { value: 'A late failure must not appear in B.' },
    })
    fireEvent.click(within(firstDialog).getByRole('button', { name: '승인 요청' }))
    await waitFor(() => expect(testRunSignal).toBeInstanceOf(AbortSignal))

    const secondRow = screen.getByText(second.number).closest('tr')
    if (!secondRow) throw new Error('Second change request row was not rendered')
    fireEvent.click(secondRow)
    const secondDialog = await screen.findByRole('dialog', {
      name: `${second.number} · ${second.title}`,
    })
    expect(testRunSignal?.aborted).toBe(true)

    act(() => testRun.reject(new Error('late A TEST failure')))
    await waitFor(() => expect(within(secondDialog).getByLabelText('테스트 결과 요약')).toHaveValue(''))
    expect(within(secondDialog).queryByText('late A TEST failure')).not.toBeInTheDocument()
  })

  it('keeps attachment footer controls hidden while an upload refreshes the bounded first page', async () => {
    const existing = changeRequest()
    let firstPageReads = 0
    const attachment = (id: string, name: string) => ({
      id,
      kind: 'REQUEST' as const,
      round_id: existing.current_round_id,
      original_name: name,
      serial_number: 1,
      content_type: 'text/plain',
      size_bytes: 12,
      content_sha256: id.padEnd(64, 'a').slice(0, 64),
      created_at: '2026-07-17T03:00:00Z',
    })
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      if (path === '/change-requests/summaries?limit=25') {
        return Promise.resolve(summaryList([existing]))
      }
      if (path === `/change-requests/${existing.id}`) return Promise.resolve(existing)
      if (path === `/change-requests/${existing.id}/attachments/page?limit=25`) {
        firstPageReads += 1
        return Promise.resolve({
          items: [attachment(
            firstPageReads === 1 ? 'attachment-first' : 'attachment-refreshed',
            firstPageReads === 1 ? 'first-page.txt' : 'refreshed-first-page.txt',
          )],
          page: { limit: 25, next_cursor: firstPageReads === 1 ? 'cursor-2' : 'fresh-cursor-2' },
        })
      }
      if (
        path ===
        `/change-requests/${existing.id}/attachments/page?limit=25&cursor=cursor-2`
      ) {
        return Promise.resolve({
          items: [attachment('attachment-second', 'second-page.txt')],
          page: { limit: 25, next_cursor: null },
        })
      }
      if (path === `/change-requests/${existing.id}/attachments` && options?.method === 'POST') {
        expect(options.signal).toBeInstanceOf(AbortSignal)
        const attachmentId = options.body instanceof FormData
          ? options.body.get('upload_id')
          : null
        if (typeof attachmentId !== 'string') throw new Error('upload_id was not submitted')
        return Promise.resolve({
          id: attachmentId,
          change_request_id: existing.id,
          round_id: existing.current_round_id,
          kind: 'REQUEST',
          original_name: 'evidence.txt',
          state: 'FINALIZED',
          expected_size_bytes: 8,
          expected_content_sha256: 'a'.repeat(64),
          provider_checksum: 'etag:test',
          failure_code: null,
          status_url:
            `/change-requests/${existing.id}/attachment-uploads/${attachmentId}`,
          finalize_url:
            `/change-requests/${existing.id}/attachment-uploads/${attachmentId}/finalize`,
        })
      }
      if (path.endsWith('/apply-report')) return Promise.reject(new Error('No apply report yet.'))
      throw new Error(`Unexpected request: ${path} ${options?.method ?? 'GET'}`)
    })
    renderPage(apiClient(request))
    const dialog = await openDetail(existing)
    expect(await within(dialog).findByText('first-page.txt')).toBeInTheDocument()
    expect(within(dialog).queryByLabelText('첨부파일 페이지 이동')).not.toBeInTheDocument()

    fireEvent.change(within(dialog).getByLabelText('클릭하여 신규 파일 첨부'), {
      target: { files: [new File(['evidence'], 'evidence.txt', { type: 'text/plain' })] },
    })
    fireEvent.click(within(dialog).getByRole('button', { name: '1개 파일 저장' }))

    expect(await within(dialog).findByText('refreshed-first-page.txt')).toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: '미완료 첨부 다시 확인' })).not.toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: '이전' })).not.toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: '다음' })).not.toBeInTheDocument()
  })

  it('retries a response-lost upload with the same client-generated ID', async () => {
    const existing = changeRequest()
    const gatewayFailure = new ApiError({
      type: 'urn:test',
      title: 'Service unavailable',
      status: 503,
      detail: 'upstream response was lost',
      code: 'service_unavailable',
      request_id: 'request-503',
    })
    let uploadId = ''
    let statusReads = 0
    let pageReads = 0
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      if (path === '/change-requests/summaries?limit=25') {
        return Promise.resolve(summaryList([existing]))
      }
      if (path === `/change-requests/${existing.id}`) return Promise.resolve(existing)
      if (path === `/change-requests/${existing.id}/attachments/page?limit=25`) {
        pageReads += 1
        return Promise.resolve({
          items: pageReads > 1
            ? [{
                id: uploadId,
                kind: 'REQUEST',
                round_id: existing.current_round_id,
                original_name: 'response-lost.txt',
                serial_number: 1,
                content_type: 'text/plain',
                size_bytes: 8,
                content_sha256: 'a'.repeat(64),
                created_at: '2026-07-23T01:00:00Z',
              }]
            : [],
          page: { limit: 25, next_cursor: null },
        })
      }
      if (path === `/change-requests/${existing.id}/attachments` && options?.method === 'POST') {
        const submitted = options.body instanceof FormData
          ? options.body.get('upload_id')
          : null
        if (typeof submitted !== 'string') throw new Error('upload_id was not submitted')
        uploadId = submitted
        return Promise.reject(gatewayFailure)
      }
      if (path === `/change-requests/${existing.id}/attachment-uploads/${uploadId}`) {
        statusReads += 1
        if (statusReads === 1) return Promise.reject(new TypeError('status response lost'))
        return Promise.resolve({
          id: uploadId,
          change_request_id: existing.id,
          round_id: existing.current_round_id,
          kind: 'REQUEST',
          original_name: 'response-lost.txt',
          state: 'STORED',
          expected_size_bytes: 8,
          expected_content_sha256: 'a'.repeat(64),
          provider_checksum: 'etag:test',
          failure_code: null,
          status_url: path,
          finalize_url: `${path}/finalize`,
        })
      }
      if (
        path === `/change-requests/${existing.id}/attachment-uploads/${uploadId}/finalize`
        && options?.method === 'POST'
      ) return Promise.resolve({})
      if (path.endsWith('/apply-report')) return Promise.reject(new Error('No apply report yet.'))
      throw new Error(`Unexpected request: ${path} ${options?.method ?? 'GET'}`)
    })
    renderPage(apiClient(request))
    const dialog = await openDetail(existing)
    const file = new File(['evidence'], 'response-lost.txt', { type: 'text/plain' })

    fireEvent.change(within(dialog).getByLabelText('클릭하여 신규 파일 첨부'), {
      target: { files: [file] },
    })
    fireEvent.click(within(dialog).getByRole('button', { name: '1개 파일 저장' }))
    await within(dialog).findByText('upstream response was lost')
    fireEvent.click(within(dialog).getByRole('button', { name: '1개 파일 저장' }))

    expect(await within(dialog).findByText('response-lost.txt')).toBeInTheDocument()
    expect(request.mock.calls.filter(
      ([path, options]) =>
        path === `/change-requests/${existing.id}/attachments`
        && options?.method === 'POST',
    )).toHaveLength(1)
    expect(statusReads).toBe(2)
  })

  it('does not expose a manual current-round STORED upload recovery control', async () => {
    const existing = changeRequest()
    const uploadId = '00000000-0000-4000-8000-000000000401'
    let pageReads = 0
    const uploadStatus = `/change-requests/${existing.id}/attachment-uploads/${uploadId}`
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      if (path === '/change-requests/summaries?limit=25') {
        return Promise.resolve(summaryList([existing]))
      }
      if (path === `/change-requests/${existing.id}`) return Promise.resolve(existing)
      if (path === `/change-requests/${existing.id}/attachments/page?limit=25`) {
        pageReads += 1
        return Promise.resolve({
          items: pageReads > 1
            ? [{
                id: uploadId,
                kind: 'REQUEST',
                round_id: existing.current_round_id,
                original_name: 'recovered.txt',
                serial_number: 1,
                content_type: 'text/plain',
                size_bytes: 8,
                content_sha256: 'a'.repeat(64),
                created_at: '2026-07-23T01:00:00Z',
              }]
            : [],
          page: { limit: 25, next_cursor: null },
        })
      }
      if (
        path
        === `/change-requests/${existing.id}/attachment-uploads`
          + `?round_id=${existing.current_round_id}&limit=10`
      ) {
        return Promise.resolve({
          items: [{
            id: uploadId,
            change_request_id: existing.id,
            round_id: existing.current_round_id,
            kind: 'REQUEST',
            original_name: 'recovered.txt',
            state: 'STORED',
            expected_size_bytes: 8,
            expected_content_sha256: 'a'.repeat(64),
            provider_checksum: 'etag:test',
            failure_code: null,
            status_url: uploadStatus,
            finalize_url: `${uploadStatus}/finalize`,
          }],
        })
      }
      if (path === `${uploadStatus}/finalize` && options?.method === 'POST') {
        return Promise.resolve({})
      }
      if (path.endsWith('/apply-report')) return Promise.reject(new Error('No apply report yet.'))
      throw new Error(`Unexpected request: ${path} ${options?.method ?? 'GET'}`)
    })
    renderPage(apiClient(request))
    const dialog = await openDetail(existing)

    expect(within(dialog).queryByRole('button', { name: '미완료 첨부 다시 확인' })).not.toBeInTheDocument()
    expect(request).not.toHaveBeenCalledWith(
      `${uploadStatus}/finalize`,
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('requires explicit confirmation and sends exact idempotency and version preconditions', async () => {
    const existing = changeRequest()
    const updated = changeRequest({ state: 'IN_REVIEW', version: 8 })
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      if (path === '/change-requests/summaries?limit=25') return Promise.resolve(summaryList([existing]))
      if (path === `/change-requests/${existing.id}`) return Promise.resolve(existing)
      if (path === `/change-requests/${existing.id}/transitions` && options?.method === 'POST') return Promise.resolve(updated)
      if (path.includes(`/catalog/assets/${existing.items[0]!.target_asset_id}/lineage`)) return Promise.resolve({ center_asset_id: 'asset-1', nodes: [], edges: [], direction: 'BOTH', depth: 2, truncated: false, meta: { projection_version: 1, policy_version: 'test' } })
      throw new Error(`Unexpected request: ${path} ${options?.method ?? 'GET'}`)
    })
    renderPage(apiClient(request))
    const detailDialog = await openDetail(existing)
    fireEvent.click(await within(detailDialog).findByRole('button', { name: '검토 시작' }))

    expect(request.mock.calls.filter(([path]) => path.endsWith('/transitions'))).toHaveLength(0)
    const confirmDialog = screen.getByRole('dialog', { name: '변경관리 명령 확인' })
    fireEvent.change(within(confirmDialog).getByLabelText('판단 사유'), { target: { value: '명시적으로 재검토했습니다.' } })
    fireEvent.click(within(confirmDialog).getByRole('button', { name: '확인 후 제출' }))

    await waitFor(() => expect(request.mock.calls.filter(([path]) => path.endsWith('/transitions'))).toHaveLength(1))
    const mutation = request.mock.calls.find(([path]) => path.endsWith('/transitions'))
    expect(mutation).toBeDefined()
    const options = mutation?.[1]
    expect(options).toMatchObject({ method: 'POST', ifMatch: '"7"' })
    expect(options?.idempotencyKey).toMatch(/^change-action-/)
    const requestBody = typeof options?.body === 'string' ? options.body : ''
    expect(JSON.parse(requestBody) as unknown).toEqual({
      target_state: 'IN_REVIEW',
      reason: '명시적으로 재검토했습니다.',
    })
    expect(await within(detailDialog).findByText('검토 중 · IN_REVIEW')).toBeInTheDocument()
  })

  it('offers a recoverable changes request without a terminal reject action', async () => {
    const existing = changeRequest({ state: 'IN_REVIEW' })
    const changesRequested = changeRequest({
      state: 'CHANGES_REQUESTED',
      version: 8,
      transitions: [
        ...existing.transitions,
        {
          id: 'transition-changes-requested',
          from_state: 'IN_REVIEW',
          to_state: 'CHANGES_REQUESTED',
          actor_id: 'reviewer-1',
          reason: '보완 후 재상신이 필요합니다.',
          occurred_at: '2026-07-17T03:04:05Z',
          round_id: existing.current_round_id,
        },
      ],
    })
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      if (path === '/change-requests/summaries?limit=25') return Promise.resolve(summaryList([existing]))
      if (path === `/change-requests/${existing.id}`) return Promise.resolve(existing)
      if (path === `/change-requests/${existing.id}/transitions` && options?.method === 'POST') {
        return Promise.resolve(changesRequested)
      }
      if (path.includes(`/catalog/assets/${existing.items[0]!.target_asset_id}/lineage`)) {
        return Promise.resolve({ center_asset_id: 'asset-1', nodes: [], edges: [], direction: 'BOTH', depth: 2, truncated: false, meta: { projection_version: 1, policy_version: 'test' } })
      }
      throw new Error(`Unexpected request: ${path} ${options?.method ?? 'GET'}`)
    })
    renderPage(apiClient(request))
    const detailDialog = await openDetail(existing)
    fireEvent.change(
      await within(detailDialog).findByRole('textbox', { name: 'REVIEWER COMMENTS · Data Steward 검토 의견' }),
      { target: { value: '변경 근거를 보완해 재상신해 주세요.' } },
    )

    expect(within(detailDialog).getByRole('button', { name: '보완 요청' })).toBeInTheDocument()
    expect(within(detailDialog).queryByRole('button', { name: /반려/ })).not.toBeInTheDocument()
    expect(request.mock.calls.filter(([path]) => path.endsWith('/transitions'))).toHaveLength(0)

    fireEvent.click(within(detailDialog).getByRole('button', { name: '보완 요청' }))
    const confirmDialog = screen.getByRole('dialog', { name: '변경관리 명령 확인' })
    expect(within(confirmDialog).getByText('보완 요청')).toBeInTheDocument()
    fireEvent.click(within(confirmDialog).getByRole('button', { name: '확인 후 제출' }))

    await waitFor(() => expect(request.mock.calls.filter(([path]) => path.endsWith('/transitions'))).toHaveLength(1))
    const mutation = request.mock.calls.find(([path]) => path.endsWith('/transitions'))
    const requestBody = typeof mutation?.[1]?.body === 'string' ? mutation[1].body : ''
    expect(JSON.parse(requestBody) as unknown).toEqual({
      target_state: 'CHANGES_REQUESTED',
      reason: '변경 근거를 보완해 재상신해 주세요.',
    })
    expect(await within(detailDialog).findByText('보완 요청 · CHANGES_REQUESTED')).toBeInTheDocument()
  })

  it('records review approval and advances to testing in one explicit UI action', async () => {
    const existing = changeRequest({ state: 'IN_REVIEW', approvals: [] })
    const approved = changeRequest({
      state: 'IN_REVIEW',
      version: 8,
    })
    const testing = changeRequest({
      state: 'TESTING',
      version: 9,
    })
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      if (path === '/change-requests/summaries?limit=25') return Promise.resolve(summaryList([existing]))
      if (path === `/change-requests/${existing.id}`) return Promise.resolve(existing)
      if (path === `/change-requests/${existing.id}/approvals` && options?.method === 'POST') {
        return Promise.resolve(approved)
      }
      if (path === `/change-requests/${existing.id}/transitions` && options?.method === 'POST') {
        return Promise.resolve(testing)
      }
      if (path.includes(`/catalog/assets/${existing.items[0]!.target_asset_id}/lineage`)) {
        return Promise.resolve({ center_asset_id: 'asset-1', nodes: [], edges: [], direction: 'BOTH', depth: 2, truncated: false, meta: { projection_version: 1, policy_version: 'test' } })
      }
      throw new Error(`Unexpected request: ${path} ${options?.method ?? 'GET'}`)
    })
    renderPage(apiClient(request))
    const detailDialog = await openDetail(existing)
    fireEvent.change(
      await within(detailDialog).findByRole('textbox', { name: 'REVIEWER COMMENTS · Data Steward 검토 의견' }),
      { target: { value: '검토 승인 후 테스트를 진행합니다.' } },
    )
    fireEvent.click(within(detailDialog).getByRole('button', { name: '검토 승인 및 변경 \/ 테스트로 이동' }))
    const confirmDialog = screen.getByRole('dialog', { name: '변경관리 명령 확인' })
    fireEvent.click(within(confirmDialog).getByRole('button', { name: '확인 후 제출' }))

    await waitFor(() => expect(request.mock.calls.filter(([path]) => path.endsWith('/approvals'))).toHaveLength(1))
    await waitFor(() => expect(request.mock.calls.filter(([path]) => path.endsWith('/transitions'))).toHaveLength(1))
    const transition = request.mock.calls.find(([path]) => path.endsWith('/transitions'))
    expect(transition?.[1]).toMatchObject({ method: 'POST', ifMatch: '"8"' })
    const transitionBody = transition?.[1]?.body
    if (typeof transitionBody !== 'string') throw new Error('Expected a JSON transition body')
    expect(JSON.parse(transitionBody) as unknown).toEqual({
      target_state: 'TESTING',
      reason: '검토 승인 후 테스트를 진행합니다.',
    })
    expect(await within(detailDialog).findByText('변경 / 테스트 · TESTING')).toBeInTheDocument()
  })

  it('records TEST approval and advances to final review from the approval request button', async () => {
    const passedRun = {
      id: 'test-run-1',
      round_id: 'round-1',
      system_id: 'system-1',
      attachment_id: 'test-attachment-1',
      state: 'PASSED' as const,
      plan_hash: 'a'.repeat(64),
      result_hash: 'b'.repeat(64),
      bounded_summary: { summary: '검증 통과' },
      recorded_by: 'subject-1',
      occurred_at: '2026-07-17T03:00:00Z',
    }
    const testing = changeRequest({ state: 'TESTING', test_runs: [passedRun] })
    const approved = changeRequest({
      state: 'TESTING',
      version: 8,
      test_runs: [passedRun],
      approvals: [
        ...testing.approvals,
        {
          id: 'approval-test',
          stage: 'TEST',
          decision: 'APPROVED',
          actor_id: 'tester-1',
          reason: '현재 회차 테스트 증거 승인',
          occurred_at: '2026-07-17T03:01:00Z',
          round_id: 'round-1',
          authorities: [{ kind: 'SYSTEM_DEVELOPER', system_id: 'system-1' }],
        },
      ],
    })
    const finalReview = changeRequest({
      state: 'FINAL_REVIEW',
      version: 9,
      test_runs: [passedRun],
      approvals: approved.approvals,
    })
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      if (path === '/change-requests/summaries?limit=25') return Promise.resolve(summaryList([testing]))
      if (path === `/change-requests/${testing.id}`) return Promise.resolve(testing)
      if (path === `/change-requests/${testing.id}/attachments/page?limit=25`) {
        return Promise.resolve({ items: [], page: { limit: 25, next_cursor: null } })
      }
      if (path === `/change-requests/${testing.id}/approvals` && options?.method === 'POST') {
        return Promise.resolve(approved)
      }
      if (path === `/change-requests/${testing.id}/transitions` && options?.method === 'POST') {
        return Promise.resolve(finalReview)
      }
      if (path.endsWith('/apply-report')) return Promise.reject(new Error('No apply report yet.'))
      throw new Error(`Unexpected request: ${path} ${options?.method ?? 'GET'}`)
    })
    renderPage(apiClient(request))
    const detailDialog = await openDetail(testing)
    const approvalButton = await within(detailDialog).findByRole('button', { name: '승인 요청' })
    expect(approvalButton).toBeEnabled()
    fireEvent.click(approvalButton)

    await waitFor(() => expect(request.mock.calls.filter(([path]) => path.endsWith('/approvals'))).toHaveLength(1))
    await waitFor(() => expect(request.mock.calls.filter(([path]) => path.endsWith('/transitions'))).toHaveLength(1))
    const transition = request.mock.calls.find(([path]) => path.endsWith('/transitions'))
    expect(transition?.[1]).toMatchObject({ method: 'POST', ifMatch: '"8"' })
    expect(screen.queryByRole('dialog', { name: '변경관리 명령 확인' })).not.toBeInTheDocument()
    expect(await within(detailDialog).findByText('최종 검토 · FINAL_REVIEW')).toBeInTheDocument()
  })

  it('asks for missing current-round TEST evidence only when approval is requested', async () => {
    const testing = changeRequest({ state: 'TESTING', test_runs: [] })
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/change-requests/summaries?limit=25') return Promise.resolve(summaryList([testing]))
      if (path === `/change-requests/${testing.id}`) return Promise.resolve(testing)
      if (path === `/change-requests/${testing.id}/attachments/page?limit=25`) {
        return Promise.resolve({ items: [], page: { limit: 25, next_cursor: null } })
      }
      if (path.endsWith('/apply-report')) return Promise.reject(new Error('No apply report yet.'))
      throw new Error(`Unexpected request: ${path}`)
    })
    renderPage(apiClient(request))
    const detailDialog = await openDetail(testing)

    expect(within(detailDialog).queryByRole('button', { name: 'Typed TEST 결과 기록' })).not.toBeInTheDocument()
    fireEvent.click(await within(detailDialog).findByRole('button', { name: '승인 요청' }))

    const validationDialog = screen.getByRole('dialog', { name: '테스트 결과 입력 필요' })
    expect(within(validationDialog).getByText(/현재 회차 TEST 증거 파일/)).toBeInTheDocument()
    expect(within(validationDialog).getByText(/테스트 결과 요약/)).toBeInTheDocument()
    expect(request.mock.calls.filter(([path]) => path.endsWith('/test-runs'))).toHaveLength(0)
    expect(request.mock.calls.filter(([path]) => path.endsWith('/approvals'))).toHaveLength(0)
  })

  it('records a PASSED result and advances to final review in one approval request', async () => {
    const testing = changeRequest({ state: 'TESTING', test_runs: [] })
    const attachment = {
      id: 'test-attachment-1', kind: 'TEST' as const, round_id: testing.current_round_id,
      original_name: 'sandbox-result.txt', serial_number: 1, content_type: 'text/plain',
      size_bytes: 12, content_sha256: 'a'.repeat(64), created_at: '2026-07-17T03:00:00Z',
    }
    const passedRun = {
      id: 'test-run-1', round_id: testing.current_round_id, system_id: 'system-1',
      attachment_id: attachment.id, state: 'PASSED' as const, plan_hash: 'b'.repeat(64),
      result_hash: 'c'.repeat(64), bounded_summary: { summary: '전체 검증 통과' },
      recorded_by: 'subject-1', occurred_at: '2026-07-17T03:01:00Z',
    }
    const recorded = changeRequest({ state: 'TESTING', version: 8, test_runs: [passedRun] })
    const approved = changeRequest({ state: 'TESTING', version: 9, test_runs: [passedRun], approvals: [
      ...recorded.approvals,
      {
        id: 'approval-test', stage: 'TEST', decision: 'APPROVED', actor_id: 'tester-1',
        reason: '전체 검증 통과', occurred_at: '2026-07-17T03:02:00Z', round_id: testing.current_round_id,
        authorities: [{ kind: 'SYSTEM_DEVELOPER', system_id: 'system-1' }],
      },
    ] })
    const finalReview = changeRequest({
      state: 'FINAL_REVIEW', version: 10, test_runs: [passedRun], approvals: approved.approvals,
    })
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      if (path === '/change-requests/summaries?limit=25') return Promise.resolve(summaryList([testing]))
      if (path === `/change-requests/${testing.id}`) return Promise.resolve(testing)
      if (path === `/change-requests/${testing.id}/attachments/page?limit=25`) {
        return Promise.resolve({ items: [attachment], page: { limit: 25, next_cursor: null } })
      }
      if (path === `/change-requests/${testing.id}/test-runs` && options?.method === 'POST') return Promise.resolve(recorded)
      if (path === `/change-requests/${testing.id}/approvals` && options?.method === 'POST') return Promise.resolve(approved)
      if (path === `/change-requests/${testing.id}/transitions` && options?.method === 'POST') return Promise.resolve(finalReview)
      if (path.endsWith('/apply-report')) return Promise.reject(new Error('No apply report yet.'))
      throw new Error(`Unexpected request: ${path} ${options?.method ?? 'GET'}`)
    })
    renderPage(apiClient(request))
    const detailDialog = await openDetail(testing)
    await waitFor(() => expect(within(detailDialog).getByLabelText('테스트 대상 시스템')).toHaveValue('system-1'))
    await waitFor(() => expect(within(detailDialog).getByLabelText('테스트 증거 파일')).toHaveValue(attachment.id))
    fireEvent.change(within(detailDialog).getByLabelText('테스트 결과 요약'), {
      target: { value: '전체 검증 통과' },
    })
    fireEvent.click(within(detailDialog).getByRole('button', { name: '승인 요청' }))

    await waitFor(() => expect(request.mock.calls.filter(([path]) => path.endsWith('/transitions'))).toHaveLength(1))
    const testRunMutation = request.mock.calls.find(([path]) => path.endsWith('/test-runs'))?.[1]
    const approvalMutation = request.mock.calls.find(([path]) => path.endsWith('/approvals'))?.[1]
    const transitionMutation = request.mock.calls.find(([path]) => path.endsWith('/transitions'))?.[1]
    expect(testRunMutation).toMatchObject({ method: 'POST', ifMatch: '"7"' })
    if (typeof testRunMutation?.body !== 'string') throw new Error('Expected a JSON TEST run body')
    expect(JSON.parse(testRunMutation.body) as unknown).toEqual({
      system_id: 'system-1', attachment_id: attachment.id, state: 'PASSED',
      bounded_summary: { summary: '전체 검증 통과' },
    })
    expect(approvalMutation).toMatchObject({ method: 'POST', ifMatch: '"8"' })
    expect(transitionMutation).toMatchObject({ method: 'POST', ifMatch: '"9"' })
    expect(await within(detailDialog).findByText('최종 검토 · FINAL_REVIEW')).toBeInTheDocument()
  })

  it('does not replay a denied mutation after step-up', async () => {
    const existing = changeRequest()
    const denied = problem(403, 'strong assurance required', 'FIDO2_REQUIRED')
    const onStepUp = vi.fn(() => Promise.resolve())
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      if (path === '/change-requests/summaries?limit=25') return Promise.resolve(summaryList([existing]))
      if (path === `/change-requests/${existing.id}`) return Promise.resolve(existing)
      if (path.endsWith('/transitions') && options?.method === 'POST') return Promise.reject(denied)
      throw new Error(`Unexpected request: ${path}`)
    })
    renderPage(apiClient(request), onStepUp)
    const detailDialog = await openDetail(existing)
    fireEvent.click(await within(detailDialog).findByRole('button', { name: '검토 시작' }))
    const confirmDialog = screen.getByRole('dialog', { name: '변경관리 명령 확인' })
    fireEvent.change(within(confirmDialog).getByLabelText('판단 사유'), {
      target: { value: '보안키 재인증이 필요한 변경 사유' },
    })
    fireEvent.click(within(confirmDialog).getByRole('button', { name: '확인 후 제출' }))

    expect(await within(detailDialog).findByText('WebAuthn 보안키 인증이 필요합니다.')).toBeInTheDocument()
    fireEvent.click(within(detailDialog).getByRole('button', { name: '보안키로 인증' }))
    await waitFor(() => expect(onStepUp).toHaveBeenCalledOnce())
    expect(request.mock.calls.filter(([path]) => path.endsWith('/transitions'))).toHaveLength(1)
    expect(screen.queryByRole('dialog', { name: '변경관리 명령 확인' })).not.toBeInTheDocument()
  })

  it('reloads after conflict, preserves the reason, and waits for a new explicit click', async () => {
    const existing = changeRequest()
    const latest = changeRequest({ version: 8 })
    const completed = changeRequest({ state: 'IN_REVIEW', version: 9 })
    let detailReads = 0
    let mutations = 0
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      if (path === '/change-requests/summaries?limit=25') return Promise.resolve(summaryList([existing]))
      if (path === `/change-requests/${existing.id}`) {
        detailReads += 1
        return Promise.resolve(detailReads === 1 ? existing : latest)
      }
      if (path.endsWith('/transitions') && options?.method === 'POST') {
        mutations += 1
        return mutations === 1 ? Promise.reject(problem(409, 'version conflict')) : Promise.resolve(completed)
      }
      if (path.includes(`/catalog/assets/${existing.items[0]!.target_asset_id}/lineage`)) return Promise.resolve({ center_asset_id: 'asset-1', nodes: [], edges: [], direction: 'BOTH', depth: 2, truncated: false, meta: { projection_version: 1, policy_version: 'test' } })
      throw new Error(`Unexpected request: ${path}`)
    })
    renderPage(apiClient(request))
    const detailDialog = await openDetail(existing)
    fireEvent.click(await within(detailDialog).findByRole('button', { name: '검토 시작' }))
    let confirmDialog = screen.getByRole('dialog', { name: '변경관리 명령 확인' })
    fireEvent.change(within(confirmDialog).getByLabelText('판단 사유'), { target: { value: '충돌 뒤에도 보존할 사유' } })
    fireEvent.click(within(confirmDialog).getByRole('button', { name: '확인 후 제출' }))

    expect(await within(detailDialog).findByText('version conflict')).toBeInTheDocument()
    expect(within(detailDialog).getByText('8')).toBeInTheDocument()
    expect(mutations).toBe(1)
    expect(screen.queryByRole('dialog', { name: '변경관리 명령 확인' })).not.toBeInTheDocument()

    fireEvent.click(within(detailDialog).getByRole('button', { name: '검토 시작' }))
    confirmDialog = screen.getByRole('dialog', { name: '변경관리 명령 확인' })
    expect(within(confirmDialog).getByLabelText('판단 사유')).toHaveValue('충돌 뒤에도 보존할 사유')
    expect(mutations).toBe(1)
    fireEvent.click(within(confirmDialog).getByRole('button', { name: '확인 후 제출' }))
    await waitFor(() => expect(mutations).toBe(2))
  })

  it('aborts and purges in-flight detail when the API client context changes', async () => {
    const first = changeRequest()
    const second = changeRequest({ id: 'change-2', number: 'CR-2026-2', title: 'Second workspace request' })
    const pendingDetail = deferred<ChangeRequestRecord>()
    let firstDetailSignal: AbortSignal | undefined
    const firstRequest = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      if (path === '/change-requests/summaries?limit=25') return Promise.resolve(summaryList([first]))
      if (path === `/change-requests/${first.id}`) {
        firstDetailSignal = options?.signal ?? undefined
        return pendingDetail.promise
      }
      throw new Error(`Unexpected first-client request: ${path}`)
    })
    const secondRequest = vi.fn((path: string): Promise<unknown> => {
      if (path === '/change-requests/summaries?limit=25') return Promise.resolve(summaryList([second]))
      throw new Error(`Unexpected second-client request: ${path}`)
    })
    const firstClient = apiClient(firstRequest)
    const secondClient = apiClient(secondRequest)
    const actions = {
      onStepUp: vi.fn(() => Promise.resolve()),
      onPasswordReauth: vi.fn(() => Promise.resolve()),
      onEnroll: vi.fn(() => Promise.resolve()),
    }
    const view = render(<GovernancePage client={firstClient} requesterName="Test Requester" {...actions} />)
    const row = await screen.findByText(first.number).then((cell) => cell.closest('tr'))
    if (!row) throw new Error('Change request row was not rendered')
    fireEvent.click(row)
    await waitFor(() => expect(firstDetailSignal).toBeDefined())

    view.rerender(<GovernancePage client={secondClient} requesterName="Test Requester" {...actions} />)
    expect(await screen.findByText(second.number)).toBeInTheDocument()
    expect(firstDetailSignal?.aborted).toBe(true)
    expect(screen.queryByRole('dialog', { name: `${first.number} · ${first.title}` })).not.toBeInTheDocument()
    expect(screen.queryByText(first.number)).not.toBeInTheDocument()
  })

  it('treats apply eligibility as a server decision and never exposes worker-owned transitions', async () => {
    const finalReview = changeRequest({ state: 'FINAL_REVIEW', approvals: [] })
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/change-requests/summaries?limit=25') return Promise.resolve(summaryList([finalReview]))
      if (path === `/change-requests/${finalReview.id}`) return Promise.resolve(finalReview)
      if (path === `/change-requests/${finalReview.id}/attachments`) {
        return Promise.resolve({ items: [] })
      }
      if (path === `/change-requests/${finalReview.id}/apply-report`) {
        return Promise.resolve({
          change_request_id: finalReview.id,
          job_id: 'job-1',
          state: 'COMPLETED',
          attempt_count: 1,
          last_error_code: null,
          expected_hash: 'a'.repeat(64),
          observed_hash: 'a'.repeat(64),
          reconciled: true,
          created_at: '2026-07-17T02:04:05Z',
          updated_at: '2026-07-17T02:04:06Z',
          items: [{
            item_id: finalReview.items[0]!.id,
            expected_hash: 'b'.repeat(64),
            observed_hash: 'b'.repeat(64),
            source_version: 'provider-source-1',
            provider_version: 'datahub-1',
          }],
          attempts: [{
            id: 'attempt-1',
            attempt_no: 1,
            state: 'COMPLETED',
            failure_code: null,
            external_response_hash: 'a'.repeat(64),
            started_at: '2026-07-17T02:04:05Z',
            finished_at: '2026-07-17T02:04:06Z',
          }],
        })
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    renderPage(apiClient(request))
    const dialog = await openDetail(finalReview)

    expect(await within(dialog).findByRole('button', { name: '적용 대기열 등록' })).toBeEnabled()
    expect(within(dialog).getByText(/서버가 클릭할 때마다 현재 대상 권한/)).toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: /APPLYING|APPLIED|APPLY_FAILED/ })).not.toBeInTheDocument()
    expect(await within(dialog).findByText('HASH MATCH · VERIFIED')).toBeInTheDocument()
    expect(within(dialog).queryByText('must-not-be-returned')).not.toBeInTheDocument()
  })

  it('derives final authority slots from server system routing and approval evidence', async () => {
    const finalReview = changeRequest({ state: 'FINAL_REVIEW' })
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/change-requests/summaries?limit=25') return Promise.resolve(summaryList([finalReview]))
      if (path === `/change-requests/${finalReview.id}`) return Promise.resolve(finalReview)
      throw new Error(`Unexpected request: ${path}`)
    })
    renderPage(apiClient(request))
    const dialog = await openDetail(finalReview)

    expect(await within(dialog).findByText('Developer · system-1')).toBeInTheDocument()
    expect(within(dialog).getByText('Data Steward · system-1')).toBeInTheDocument()
    expect(within(dialog).getByText('전역 Admin')).toBeInTheDocument()
    expect(within(dialog).getAllByText('승인 대기 중')).toHaveLength(3)
    expect(within(dialog).getByText('REVIEW · APPROVED')).toBeInTheDocument()
    expect(within(dialog).getByText('reviewer-1')).toBeInTheDocument()
    expect(within(dialog).queryByText('역할별 승인자 계약 미제공')).not.toBeInTheDocument()
  })
})
