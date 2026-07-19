import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ApiError, type ApiClient, type RequestOptions } from '../../api/client'
import type { ChangeRequestRecord } from '../../api/types'
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
    }],
    approvals: [{
      id: 'approval-1',
      stage: 'REVIEW',
      decision: 'APPROVED',
      actor_id: 'reviewer-1',
      reason: '검토 근거가 일치합니다.',
      occurred_at: '2026-07-17T02:03:04Z',
    }],
    transitions: [{
      id: 'transition-1',
      from_state: 'REGISTERED',
      to_state: 'IN_REVIEW',
      actor_id: 'reviewer-1',
      reason: '검토를 시작합니다.',
      occurred_at: '2026-07-17T02:04:05Z',
    }],
    ...overrides,
  }
}

function apiClient(request: (path: string, options?: RequestOptions) => Promise<unknown>): ApiClient {
  return { request } as unknown as ApiClient
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
      throw new Error(`Unexpected request: ${path} ${options?.method ?? 'GET'}`)
    })
    renderPage(apiClient(request))

    expect(await screen.findByText(existing.number)).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'CR-No' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: '변경 Aspect' })).toBeInTheDocument()
    expect(screen.getByText('1건 표시')).toBeInTheDocument()
    expect(screen.queryByLabelText('DataHub 대상 URN')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('승인 대상 JSON')).not.toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: '신규 CR 신청' })[0])
    expect(await screen.findByRole('dialog', { name: '신규 CR 신청' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '신규 CR 신청' })).not.toBeInTheDocument()
    const listOptions = request.mock.calls.find(([path]) => path === '/change-requests?limit=100')?.[1]
    expect(listOptions?.signal).toBeInstanceOf(AbortSignal)
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

    expect(await within(dialog).findByText('대상 및 원본 증거')).toBeInTheDocument()
    expect(within(dialog).getByLabelText(existing.items[0]!.target_ref)).toHaveAttribute('tabindex', '0')
    expect(within(dialog).getByText('검토 근거가 일치합니다.')).toBeInTheDocument()
    expect(within(dialog).getByText('검토를 시작합니다.')).toBeInTheDocument()
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

    expect(await within(detailDialog).findByText('USB 보안키 인증이 필요합니다.')).toBeInTheDocument()
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
    const view = render(<GovernancePage client={firstClient} {...actions} />)
    await openDetail(first)

    view.rerender(<GovernancePage client={secondClient} {...actions} />)
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
})
