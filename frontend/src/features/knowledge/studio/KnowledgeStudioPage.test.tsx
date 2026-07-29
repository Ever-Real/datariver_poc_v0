import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiClient } from '../../../api/client'
import type { DraftRecoveryQueue, DraftRecoveryRecord } from './draftRecoveryQueue'
import { KnowledgeStudioPage } from './KnowledgeStudioPage'

const domainId = '019fa57b-52de-74c0-9f5e-06ae7b1bf3af'
const draftId = '019fa57b-52de-74c0-9f5e-06ae7b1bf3b0'

class MemoryRecoveryQueue implements DraftRecoveryQueue {
  records = new Map<string, DraftRecoveryRecord>()

  read(scopeHash: string, id?: string): Promise<DraftRecoveryRecord | undefined> {
    return Promise.resolve(this.records.get(`${scopeHash}:${id ?? 'NEW'}`))
  }

  put(record: DraftRecoveryRecord): Promise<void> {
    this.records.set(`${record.scopeHash}:${record.draftId ?? 'NEW'}`, record)
    return Promise.resolve()
  }

  remove(scopeHash: string, id: string | undefined, key: string): Promise<void> {
    const storageKey = `${scopeHash}:${id ?? 'NEW'}`
    if (this.records.get(storageKey)?.idempotencyKey === key) {
      this.records.delete(storageKey)
    }
    return Promise.resolve()
  }
}

class FailingRecoveryQueue extends MemoryRecoveryQueue {
  override put(): Promise<void> {
    return Promise.reject(new Error('storage unavailable'))
  }
}

function draft(version: number, name = '서버 그래프', currentStep = 'BASIC') {
  return {
    id: draftId,
    author_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3b1',
    kind: 'CREATE',
    state: 'DRAFT',
    current_step: currentStep,
    name,
    endpoint_alias: 'semiconductor_materials',
    domain_id: domainId,
    domain_source_version: 'domain-v3',
    classification: 'INTERNAL',
    last_autosaved_at: '2026-07-28T01:00:00Z',
    version,
    created_at: '2026-07-28T01:00:00Z',
    updated_at: '2026-07-28T01:00:00Z',
  }
}

function json(value: unknown, status = 200, etag?: string): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: {
      'Content-Type': 'application/json',
      ...(etag ? { ETag: etag } : {}),
    },
  })
}

function domains(): Response {
  return json({
    items: [{ id: domainId, display_name: '반도체', source_version: 'domain-v3' }],
  })
}

function missingResumableDraft(): Response {
  return json({
    type: 'urn:datariver:problem:not_found',
    title: 'Not Found',
    status: 404,
    detail: 'A resumable Knowledge Studio draft does not exist.',
    code: 'not_found',
    request_id: 'request',
  }, 404)
}

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input
  return input instanceof URL ? input.toString() : input.url
}

beforeEach(() => {
  vi.stubGlobal('crypto', {
    ...crypto,
    randomUUID: vi.fn(() => '019fa57b-52de-74c0-9f5e-06ae7b1bf399'),
    subtle: crypto.subtle,
  })
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  window.history.replaceState({}, '', '/')
})

describe('KnowledgeStudioPage Draft recovery', () => {
  it('converts an asset route into its server-issued EDIT Draft route', async () => {
    const assetId = '019fa57b-52de-74c0-9f5e-06ae7b1bf3c0'
    window.history.replaceState(
      {},
      '',
      `/?page=knowledge-studio&workspace=workspace&asset_id=${assetId}`,
    )
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const path = requestUrl(input)
      if (path.includes('/domains?')) return Promise.resolve(domains())
      if (
        path.endsWith(`/knowledge/studio/drafts/from-asset/${assetId}`)
        && init?.method === 'POST'
      ) {
        return Promise.resolve(json({ ...draft(1), kind: 'EDIT' }, 201, '"1"'))
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')

    render(
      <KnowledgeStudioPage
        client={client}
        workspaceId="workspace"
        subjectId="subject"
        onNavigate={vi.fn()}
        recoveryQueue={new MemoryRecoveryQueue()}
        debounceMs={10}
      />,
    )

    await waitFor(() => expect(screen.getByLabelText('지식 그래프 이름')).toHaveValue('서버 그래프'))
    expect(window.location.search).toContain(`draft=${draftId}`)
    expect(window.location.search).not.toContain('asset_id=')
    const editCall = fetchMock.mock.calls.find(([input]) => (
      requestUrl(input).includes('/drafts/from-asset/')
    ))
    expect(new Headers(editCall?.[1]?.headers).get('Idempotency-Key')).toBeTruthy()
  })

  it('runs the basic-information to T-Box to A-Box authoring flow through typed APIs', async () => {
    window.history.replaceState({}, '', '/?page=knowledge-studio&workspace=workspace')
    const queue = new MemoryRecoveryQueue()
    const blockId = '019fa57b-52de-74c0-9f5e-06ae7b1bf3d0'
    const tboxElement = {
      stable_element_id: 'class:019fa57b-52de-74c0-9f5e-06ae7b1bf399',
      kind: 'CLASS',
      canonical_name: 'Employee',
      display_name: 'Employee',
      ordinal: 0,
      version: 1,
      block_id: blockId,
      aliases: [],
      vector_index_enabled: false,
      layout_x: 80,
      layout_y: 100,
    }
    const tboxRecord = (version: number, elements: unknown[]) => ({
      draft: draft(version, '반도체 소재 그래프', 'TBOX'),
      blocks: [{
        id: blockId,
        kind: 'DIRECT',
        title: '직접 정의',
        weight: 50,
        ordinal: 0,
        collapsed: false,
        version: 1,
        elements,
        created_at: '2026-07-28T01:00:00Z',
        updated_at: '2026-07-28T01:00:00Z',
      }],
    })
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const path = requestUrl(input)
      if (path.includes('/domains?')) return Promise.resolve(domains())
      if (path.includes('/drafts/resumable?')) {
        return Promise.resolve(missingResumableDraft())
      }
      if (path.endsWith('/knowledge/studio/drafts') && init?.method === 'POST') {
        return Promise.resolve(json(draft(1, '반도체 소재 그래프'), 201, '"1"'))
      }
      if (path.endsWith(`/drafts/${draftId}/advance`)) {
        if (typeof init?.body !== 'string') throw new Error('Expected a JSON request body.')
        const body = JSON.parse(init.body) as { target_step: string }
        return Promise.resolve(body.target_step === 'ABOX'
          ? json(draft(4, '반도체 소재 그래프', 'ABOX'), 200, '"4"')
          : json(draft(2, '반도체 소재 그래프', 'TBOX'), 200, '"2"'))
      }
      if (path.endsWith(`/drafts/${draftId}/tbox`) && !init?.method) {
        return Promise.resolve(json(tboxRecord(2, []), 200, '"2"'))
      }
      if (path.endsWith(`/tbox/blocks/${blockId}/operations`) && init?.method === 'POST') {
        if (typeof init.body !== 'string') throw new Error('Expected a JSON request body.')
        const body = JSON.parse(init.body) as {
          operations: Array<{ operation: string; element?: { canonical_name?: string } }>
        }
        const upsert = body.operations.find((item) => item.operation === 'UPSERT_ELEMENT')
        expect(upsert?.element?.canonical_name).toBe('Employee')
        return Promise.resolve(json(tboxRecord(3, [tboxElement]), 200, '"3"'))
      }
      if (path.endsWith(`/drafts/${draftId}/abox`) && !init?.method) {
        return Promise.resolve(json({
          draft: draft(4, '반도체 소재 그래프', 'ABOX'),
          tbox_elements: [tboxElement],
          bindings: [],
        }, 200, '"4"'))
      }
      if (path.endsWith('/abox/ingestions') && !init?.method) {
        return Promise.resolve(json({ items: [] }))
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')
    render(<KnowledgeStudioPage
      client={client}
      workspaceId="workspace"
      subjectId="subject"
      onNavigate={vi.fn()}
      recoveryQueue={queue}
      debounceMs={10}
    />)

    fireEvent.change(await screen.findByLabelText('지식 그래프 이름'), {
      target: { value: '반도체 소재 그래프' },
    })
    fireEvent.change(screen.getByLabelText('Endpoint alias'), {
      target: { value: 'semiconductor_materials' },
    })
    await screen.findByRole('option', { name: '반도체' })
    fireEvent.change(screen.getByLabelText('업무 도메인'), {
      target: { value: domainId },
    })
    await waitFor(() => {
      expect(screen.getByLabelText('지식 그래프 이름')).toHaveValue('반도체 소재 그래프')
      expect(screen.getByLabelText('Endpoint alias')).toHaveValue('semiconductor_materials')
      expect(screen.getByLabelText('업무 도메인')).toHaveValue(domainId)
      expect(screen.getByRole('button', { name: /저장 후 Graph Builder/ })).toBeEnabled()
    })

    await waitFor(() => expect(fetchMock.mock.calls.some(([input, init]) => (
      init?.method === 'POST'
      && requestUrl(input).endsWith('/knowledge/studio/drafts')
    ))).toBe(true))
    await waitFor(() => expect(window.location.search).toContain(`draft=${draftId}`))

    fireEvent.click(screen.getByRole('button', { name: /저장 후 Graph Builder/ }))
    expect(await screen.findByRole('heading', {
      name: 'Ontology Graph Builder',
    })).toBeInTheDocument()
    expect(screen.getByText('(+)로 첫 Class를 추가하세요.')).toBeInTheDocument()
    expect(screen.getByText(/Typed T-Box Draft를 불러왔습니다/)).toBeInTheDocument()
    expect(window.location.search).toContain('step=tbox')
    expect(queue.records.size).toBe(0)

    fireEvent.change(screen.getByLabelText('최상위 Class 이름'), {
      target: { value: 'Employee' },
    })
    fireEvent.click(screen.getByRole('button', { name: '최상위 Class 추가' }))
    fireEvent.click(screen.getByRole('button', { name: 'T-Box 저장' }))
    await screen.findByText(/Typed T-Box 저장 완료/)

    fireEvent.click(screen.getByRole('button', { name: 'Data Enricher' }))
    expect(await screen.findByRole('heading', { name: 'Data Enricher' })).toBeInTheDocument()
    expect(await screen.findByText('Employee')).toBeInTheDocument()
    expect(window.location.search).toContain('step=abox')
  })

  it('keeps local input on 412 and reloads server state only after explicit choice', async () => {
    window.history.replaceState(
      {},
      '',
      `/?page=knowledge-studio&workspace=workspace&draft=${draftId}`,
    )
    const queue = new MemoryRecoveryQueue()
    let draftReads = 0
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const path = requestUrl(input)
      if (path.includes('/domains?')) return Promise.resolve(domains())
      if (path.endsWith(`/drafts/${draftId}`) && !init?.method) {
        draftReads += 1
        return Promise.resolve(draftReads === 1
          ? json(draft(1), 200, '"1"')
          : json(draft(2, '다른 편집자의 최신 그래프'), 200, '"2"'))
      }
      if (path.endsWith(`/drafts/${draftId}`) && init?.method === 'PATCH') {
        return Promise.resolve(json({
          type: 'urn:datariver:problem:precondition_failed',
          title: 'Precondition Failed',
          status: 412,
          detail: 'The Draft was modified by another editor.',
          code: 'precondition_failed',
          request_id: 'request',
        }, 412))
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')
    render(<KnowledgeStudioPage
      client={client}
      workspaceId="workspace"
      subjectId="subject"
      onNavigate={vi.fn()}
      recoveryQueue={queue}
      debounceMs={10}
    />)

    const name = await screen.findByLabelText('지식 그래프 이름')
    await waitFor(() => expect(name).toHaveValue('서버 그래프'))
    fireEvent.change(name, { target: { value: '보존해야 할 내 입력' } })

    const dialog = await screen.findByRole('dialog', { name: '동시 편집 충돌' })
    expect(name).toHaveValue('보존해야 할 내 입력')
    expect(within(dialog).getByText(/로컬 입력은 아직 삭제되지 않았습니다/)).toBeInTheDocument()

    fireEvent.click(within(dialog).getByRole('button', { name: '최신 버전 불러오기' }))
    await waitFor(() => expect(name).toHaveValue('다른 편집자의 최신 그래프'))
    expect(screen.queryByRole('dialog', { name: '동시 편집 충돌' })).not.toBeInTheDocument()
    expect(queue.records.size).toBe(0)
  })

  it('keeps the same focused input mounted while controlled text changes', async () => {
    window.history.replaceState({}, '', '/?page=knowledge-studio&workspace=workspace')
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const path = requestUrl(input)
      if (path.includes('/domains?')) return Promise.resolve(domains())
      return Promise.reject(new Error(`Unexpected request: ${path}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')
    render(<KnowledgeStudioPage
      client={client}
      workspaceId="workspace"
      subjectId="subject"
      onNavigate={vi.fn()}
      recoveryQueue={new MemoryRecoveryQueue()}
      debounceMs={60_000}
    />)

    const name = await screen.findByLabelText('지식 그래프 이름')
    name.focus()
    expect(document.activeElement).toBe(name)

    for (const value of ['연', '연속', '연속 입력', '연속 입력 검증']) {
      fireEvent.change(name, { target: { value } })
      expect(screen.getByLabelText('지식 그래프 이름')).toBe(name)
      expect(document.activeElement).toBe(name)
    }
    expect(name).toHaveValue('연속 입력 검증')
  })

  it('resumes an existing Draft and PATCHes with its latest ETag before advancing', async () => {
    window.history.replaceState({}, '', '/?page=knowledge-studio&workspace=workspace')
    const queue = new MemoryRecoveryQueue()
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const path = requestUrl(input)
      if (path.includes('/domains?')) return Promise.resolve(domains())
      if (path.includes('/drafts/resumable?')) {
        return Promise.resolve(json(draft(4, '기존 서버 그래프'), 200, '"4"'))
      }
      if (path.endsWith(`/drafts/${draftId}`) && init?.method === 'PATCH') {
        expect(new Headers(init.headers).get('If-Match')).toBe('"4"')
        return Promise.resolve(json(draft(5, '이어 쓰는 그래프'), 200, '"5"'))
      }
      if (path.endsWith(`/drafts/${draftId}/advance`) && init?.method === 'POST') {
        expect(new Headers(init.headers).get('If-Match')).toBe('"5"')
        return Promise.resolve(json(draft(6, '이어 쓰는 그래프', 'TBOX'), 200, '"6"'))
      }
      if (path.endsWith(`/drafts/${draftId}/tbox`) && !init?.method) {
        return Promise.resolve(json({
          draft: draft(6, '이어 쓰는 그래프', 'TBOX'),
          blocks: [],
        }, 200, '"6"'))
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')
    render(<KnowledgeStudioPage
      client={client}
      workspaceId="workspace"
      subjectId="subject"
      onNavigate={vi.fn()}
      recoveryQueue={queue}
      debounceMs={60_000}
    />)

    fireEvent.change(await screen.findByLabelText('지식 그래프 이름'), {
      target: { value: '이어 쓰는 그래프' },
    })
    fireEvent.change(screen.getByLabelText('Endpoint alias'), {
      target: { value: 'semiconductor_materials' },
    })
    await screen.findByRole('option', { name: '반도체' })
    fireEvent.change(screen.getByLabelText('업무 도메인'), {
      target: { value: domainId },
    })
    fireEvent.click(screen.getByRole('button', { name: /저장 후 Graph Builder/ }))

    expect(await screen.findByRole('heading', {
      name: 'Ontology Graph Builder',
    })).toBeInTheDocument()
    expect(window.location.search).toContain(`draft=${draftId}`)
    expect(window.location.search).toContain('step=tbox')
    expect(fetchMock.mock.calls.some(([input, init]) => (
      requestUrl(input).endsWith('/knowledge/studio/drafts')
      && init?.method === 'POST'
    ))).toBe(false)
  })

  it('rebases preserved local input onto the latest ETag only after overwrite confirmation', async () => {
    window.history.replaceState(
      {},
      '',
      `/?page=knowledge-studio&workspace=workspace&draft=${draftId}`,
    )
    const queue = new MemoryRecoveryQueue()
    let draftReads = 0
    let patches = 0
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const path = requestUrl(input)
      if (path.includes('/domains?')) return Promise.resolve(domains())
      if (path.endsWith(`/drafts/${draftId}`) && !init?.method) {
        draftReads += 1
        return Promise.resolve(draftReads === 1
          ? json(draft(1), 200, '"1"')
          : json(draft(2, '다른 편집자의 최신 그래프'), 200, '"2"'))
      }
      if (path.endsWith(`/drafts/${draftId}`) && init?.method === 'PATCH') {
        patches += 1
        if (patches === 1) {
          return Promise.resolve(json({
            type: 'urn:datariver:problem:precondition_failed',
            title: 'Precondition Failed',
            status: 412,
            detail: 'The Draft was modified by another editor.',
            code: 'precondition_failed',
            request_id: 'request',
          }, 412))
        }
        return Promise.resolve(json(draft(3, '보존해야 할 내 입력'), 200, '"3"'))
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')
    render(<KnowledgeStudioPage
      client={client}
      workspaceId="workspace"
      subjectId="subject"
      onNavigate={vi.fn()}
      recoveryQueue={queue}
      debounceMs={10}
    />)

    const name = await screen.findByLabelText('지식 그래프 이름')
    await waitFor(() => expect(name).toHaveValue('서버 그래프'))
    fireEvent.change(name, { target: { value: '보존해야 할 내 입력' } })
    const dialog = await screen.findByRole('dialog', { name: '동시 편집 충돌' })
    fireEvent.click(within(dialog).getByRole('button', { name: '내 변경사항으로 덮어쓰기' }))

    await waitFor(() => expect(
      screen.queryByRole('dialog', { name: '동시 편집 충돌' }),
    ).not.toBeInTheDocument())
    expect(name).toHaveValue('보존해야 할 내 입력')
    const patchCalls = fetchMock.mock.calls.filter(([, init]) => init?.method === 'PATCH')
    const overwriteHeaders = new Headers(patchCalls[1]?.[1]?.headers)
    expect(overwriteHeaders.get('If-Match')).toBe('"2"')
    expect(queue.records.size).toBe(0)
  })

  it('keeps an offline revision queued and retries it when the browser comes online', async () => {
    window.history.replaceState({}, '', '/?page=knowledge-studio&workspace=workspace')
    const queue = new MemoryRecoveryQueue()
    let online = false
    vi.spyOn(navigator, 'onLine', 'get').mockImplementation(() => online)
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const path = requestUrl(input)
      if (path.includes('/domains?')) return Promise.resolve(domains())
      if (path.includes('/drafts/resumable?')) {
        return Promise.resolve(missingResumableDraft())
      }
      if (path.endsWith('/knowledge/studio/drafts') && init?.method === 'POST') {
        return Promise.resolve(json(draft(1, '오프라인 복구 그래프'), 201, '"1"'))
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')
    render(<KnowledgeStudioPage
      client={client}
      workspaceId="workspace"
      subjectId="subject"
      onNavigate={vi.fn()}
      recoveryQueue={queue}
      debounceMs={10}
    />)

    fireEvent.change(await screen.findByLabelText('지식 그래프 이름'), {
      target: { value: '오프라인 복구 그래프' },
    })
    fireEvent.change(screen.getByLabelText('Endpoint alias'), {
      target: { value: 'offline_recovery' },
    })
    await screen.findByRole('option', { name: '반도체' })
    fireEvent.change(screen.getByLabelText('업무 도메인'), {
      target: { value: domainId },
    })

    await screen.findByText(/오프라인입니다/)
    expect(queue.records.size).toBe(1)
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)

    online = true
    window.dispatchEvent(new Event('online'))
    await waitFor(() => expect(
      fetchMock.mock.calls.some(([, init]) => init?.method === 'POST'),
    ).toBe(true))
    await waitFor(() => expect(queue.records.size).toBe(0))
  })

  it('does not transmit a recoverability-dependent write when the queue fails', async () => {
    window.history.replaceState({}, '', '/?page=knowledge-studio&workspace=workspace')
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const path = requestUrl(input)
      if (path.includes('/domains?')) return Promise.resolve(domains())
      return Promise.reject(new Error(`Unexpected request: ${path}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')
    render(<KnowledgeStudioPage
      client={client}
      workspaceId="workspace"
      subjectId="subject"
      onNavigate={vi.fn()}
      recoveryQueue={new FailingRecoveryQueue()}
      debounceMs={10}
    />)

    fireEvent.change(await screen.findByLabelText('지식 그래프 이름'), {
      target: { value: '복구 실패 그래프' },
    })
    fireEvent.change(screen.getByLabelText('Endpoint alias'), {
      target: { value: 'recovery_failure' },
    })
    await screen.findByRole('option', { name: '반도체' })
    fireEvent.change(screen.getByLabelText('업무 도메인'), {
      target: { value: domainId },
    })

    await screen.findByText(/복구 큐 기록에 실패/)
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
  })
})
