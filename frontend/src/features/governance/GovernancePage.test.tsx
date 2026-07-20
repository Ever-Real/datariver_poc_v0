import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ApiError, type ApiClient, type RequestOptions } from '../../api/client'
import type { CatalogAsset, ChangeRequestRecord } from '../../api/types'
import { GovernancePage } from './GovernancePage'

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
    rounds: [{ id: 'round-1', round_number: 1, submitted_by: 'subject-1', submitted_at: '2026-07-17T01:02:03Z', closed_at: null, evidence_hash: 'a'.repeat(64) }],
    test_runs: [],
    ...overrides,
  }
}

function apiClient(request: (path: string, options?: RequestOptions) => Promise<unknown>): ApiClient {
  return { request } as unknown as ApiClient
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

describe('GovernancePage', () => {
  it('distinguishes loading from an authorized empty window', async () => {
    const list = deferred<{ items: ChangeRequestRecord[] }>()
    const request = vi.fn((): Promise<unknown> => list.promise)
    renderPage(apiClient(request))

    const loading = screen.getByText('데이터를 불러오는 중입니다.')
    expect(loading.closest('.dense-table-frame')).toHaveAttribute('aria-busy', 'true')
    expect(screen.getByText('현재 조회된 요청 · 최대 100건')).toBeInTheDocument()

    act(() => list.resolve({ items: [] }))
    expect(await screen.findByText('현재 권한 범위에서 조회 가능한 요청이 없습니다.')).toBeInTheDocument()
    expect(screen.getByText('0건 표시')).toBeInTheDocument()
  })

  it('renders the bounded dense list and opens independent CR creation', async () => {
    const existing = changeRequest()
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      if (path === '/change-requests?limit=100') return Promise.resolve({ items: [existing] })
      if (path === '/change-requests/systems') return Promise.resolve({
        items: [{ id: 'system-1', code: 'FAB', name: 'Fabrication' }],
      })
      throw new Error(`Unexpected request: ${path} ${options?.method ?? 'GET'}`)
    })
    renderPage(apiClient(request))

    expect(await screen.findByText(existing.number)).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'CR-No' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: '변경 Aspect' })).toBeInTheDocument()
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
    const listOptions = request.mock.calls.find(([path]) => path === '/change-requests?limit=100')?.[1]
    expect(listOptions?.signal).toBeInstanceOf(AbortSignal)
  })

  it('renders every selected table and column under one shared hierarchical target table', async () => {
    const existing = changeRequest()
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/change-requests?limit=100') return Promise.resolve({ items: [existing] })
      if (path.startsWith('/catalog/assets?q=wafer')) return Promise.resolve({ items: [governedCatalogAsset] })
      if (path === `/catalog/assets/${governedCatalogAsset.id}`) return Promise.resolve({
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

    fireEvent.change(screen.getByLabelText('wafer_events 컬럼 추가'), { target: { value: 'wafer_id' } })
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
      if (path === '/change-requests?limit=100') return Promise.resolve({ items: [existing] })
      throw new Error(`Unexpected request: ${path}`)
    })
    renderPage(apiClient(request))
    await screen.findByText(existing.number)

    fireEvent.change(screen.getByLabelText('상태 필터'), { target: { value: 'IN_REVIEW' } })
    expect(await screen.findByText('선택한 상태에서 조회 가능한 요청이 없습니다.')).toBeInTheDocument()
    const filterOptions = request.mock.calls.find(([path]) => path === '/change-requests?limit=100')?.[1]
    expect(filterOptions?.signal).toBeInstanceOf(AbortSignal)
  })

  it('opens a freshly authorized accessible detail by keyboard and restores focus', async () => {
    const existing = changeRequest()
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      void options
      if (path === '/change-requests?limit=100') return Promise.resolve({ items: [existing] })
      if (path === `/change-requests/${existing.id}`) return Promise.resolve(existing)
      throw new Error(`Unexpected request: ${path}`)
    })
    renderPage(apiClient(request))
    const dialog = await openDetail(existing)

    expect(await within(dialog).findByText('REQUEST REASON')).toBeInTheDocument()
    expect(within(dialog).getByRole('table', { name: 'CR 변경 대상' })).toBeInTheDocument()
    expect(within(dialog).getByLabelText(`${existing.items[0]!.target_ref} 비고`)).toHaveAttribute('readonly')
    expect(within(dialog).getByText(/등록 후 대상 편집 미지원/)).toBeInTheDocument()
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

  it('requires explicit confirmation and sends exact idempotency and version preconditions', async () => {
    const existing = changeRequest()
    const updated = changeRequest({ state: 'IN_REVIEW', version: 8 })
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      if (path === '/change-requests?limit=100') return Promise.resolve({ items: [existing] })
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

  it('does not replay a denied mutation after step-up', async () => {
    const existing = changeRequest()
    const denied = problem(403, 'strong assurance required', 'FIDO2_REQUIRED')
    const onStepUp = vi.fn(() => Promise.resolve())
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      if (path === '/change-requests?limit=100') return Promise.resolve({ items: [existing] })
      if (path === `/change-requests/${existing.id}`) return Promise.resolve(existing)
      if (path.endsWith('/transitions') && options?.method === 'POST') return Promise.reject(denied)
      throw new Error(`Unexpected request: ${path}`)
    })
    renderPage(apiClient(request), onStepUp)
    const detailDialog = await openDetail(existing)
    fireEvent.click(await within(detailDialog).findByRole('button', { name: '검토 시작' }))
    fireEvent.click(within(screen.getByRole('dialog', { name: '변경관리 명령 확인' })).getByRole('button', { name: '확인 후 제출' }))

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
      if (path === '/change-requests?limit=100') return Promise.resolve({ items: [existing] })
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
      if (path === '/change-requests?limit=100') return Promise.resolve({ items: [first] })
      if (path === `/change-requests/${first.id}`) {
        firstDetailSignal = options?.signal ?? undefined
        return pendingDetail.promise
      }
      throw new Error(`Unexpected first-client request: ${path}`)
    })
    const secondRequest = vi.fn((path: string): Promise<unknown> => {
      if (path === '/change-requests?limit=100') return Promise.resolve({ items: [second] })
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
    await openDetail(first)

    view.rerender(<GovernancePage client={secondClient} requesterName="Test Requester" {...actions} />)
    expect(await screen.findByText(second.number)).toBeInTheDocument()
    expect(firstDetailSignal?.aborted).toBe(true)
    expect(screen.queryByRole('dialog', { name: `${first.number} · ${first.title}` })).not.toBeInTheDocument()
    expect(screen.queryByText(first.number)).not.toBeInTheDocument()
  })

  it('treats apply eligibility as a server decision and never exposes worker-owned transitions', async () => {
    const finalReview = changeRequest({ state: 'FINAL_REVIEW', approvals: [] })
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/change-requests?limit=100') return Promise.resolve({ items: [finalReview] })
      if (path === `/change-requests/${finalReview.id}`) return Promise.resolve(finalReview)
      throw new Error(`Unexpected request: ${path}`)
    })
    renderPage(apiClient(request))
    const dialog = await openDetail(finalReview)

    expect(await within(dialog).findByRole('button', { name: '적용 대기열 등록' })).toBeEnabled()
    expect(within(dialog).getByText(/서버가 클릭할 때마다 현재 대상 권한/)).toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: /APPLYING|APPLIED|APPLY_FAILED/ })).not.toBeInTheDocument()
  })

  it('derives final authority slots from server system routing and approval evidence', async () => {
    const finalReview = changeRequest({ state: 'FINAL_REVIEW' })
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/change-requests?limit=100') return Promise.resolve({ items: [finalReview] })
      if (path === `/change-requests/${finalReview.id}`) return Promise.resolve(finalReview)
      throw new Error(`Unexpected request: ${path}`)
    })
    renderPage(apiClient(request))
    const dialog = await openDetail(finalReview)

    expect(within(dialog).getByText('Developer · system-1')).toBeInTheDocument()
    expect(within(dialog).getByText('Data Steward · system-1')).toBeInTheDocument()
    expect(within(dialog).getByText('전역 Admin')).toBeInTheDocument()
    expect(within(dialog).getAllByText('승인 대기 중')).toHaveLength(3)
    expect(within(dialog).getByText('REVIEW · APPROVED')).toBeInTheDocument()
    expect(within(dialog).getByText('reviewer-1')).toBeInTheDocument()
    expect(within(dialog).queryByText('역할별 승인자 계약 미제공')).not.toBeInTheDocument()
  })
})
