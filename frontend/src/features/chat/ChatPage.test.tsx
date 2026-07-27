import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiClient, RequestOptions } from '../../api/client'
import type { ChatResponse, ChatSession } from '../../api/types'
import { ChatPage } from './ChatPage'

vi.mock('../catalog/CatalogDetailPane', () => ({
  CatalogDetailPane: ({
    assetId,
    onClose,
    onSelectAsset,
  }: {
    assetId: string
    onClose: () => void
    onSelectAsset?: (assetId: string) => void
  }) => (
    <aside aria-label="카탈로그 상세">
      <span>asset:{assetId}</span>
      <button onClick={() => onSelectAsset?.('asset-related')} type="button">연결 테이블</button>
      <button onClick={onClose} type="button">상세 닫기</button>
    </aside>
  ),
}))

const session: ChatSession = {
  id: 'session-1',
  title: '주문 데이터',
  is_favorite: false,
  version: 3,
  created_at: '2026-07-26T01:00:00Z',
  updated_at: '2026-07-26T01:00:00Z',
  message_count: 2,
}

const response: ChatResponse = {
  session_id: session.id,
  request_message_id: 'message-user-1',
  response_message_id: 'message-assistant-1',
  answer: [
    '## 확인된 테이블',
    '',
    '| 순위 | 이름 |',
    '| ---: | --- |',
    '| 1 | **orders** |',
  ].join('\n'),
  persistence: 'PERSISTED',
  route: {
    requested_mode: 'VECTOR',
    selected_mode: 'VECTOR',
    reason: 'EXPLICIT_SELECTION',
    adapter_state: 'READY',
  },
  workflow: [
    { stage: 'AUTHORIZATION', status: 'COMPLETED', detail_code: 'AUTHORIZED' },
    { stage: 'BUDGET_RESERVATION', status: 'COMPLETED', detail_code: 'BUDGET_RESERVED' },
    { stage: 'ROUTING', status: 'COMPLETED', detail_code: 'VECTOR_SELECTED' },
    { stage: 'RETRIEVAL', status: 'COMPLETED', detail_code: 'EVIDENCE_FOUND' },
    { stage: 'RERANKING', status: 'COMPLETED', detail_code: 'RERANKED' },
    { stage: 'COMPOSITION', status: 'COMPLETED', detail_code: 'ANSWER_COMPOSED' },
    { stage: 'CITATION_VALIDATION', status: 'COMPLETED', detail_code: 'CITATIONS_VALID' },
    { stage: 'PERSISTENCE', status: 'COMPLETED', detail_code: 'PERSISTED' },
  ],
  evidence: [{
    chunk_id: 'chunk-1',
    resource_id: 'asset-orders',
    classification: 'INTERNAL',
    system_id: 'system-1',
    domain_id: null,
    owner_department_id: null,
    name: 'orders',
    description: '주문 원장',
    source_type: 'CATALOG_ASSET',
    source_locator: 'postgres.analytics.orders',
    source_version: 'v7',
    content_hash: 'a'.repeat(64),
    effective_from: '2026-07-26T01:00:00Z',
    effective_until: null,
    extraction_method: 'CATALOG_PROJECTION',
    rank: 1,
    retrieval_method: 'VECTOR',
  }],
}

function chatClient() {
  let favorite = false
  const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
    if (path === '/chat/sessions?limit=50') return Promise.resolve([{ ...session, is_favorite: favorite }])
    if (path === '/chat/query') return Promise.resolve(response)
    if (path === `/chat/sessions/${session.id}/messages?limit=200`) return Promise.resolve([
      {
        id: 'history-user',
        session_id: session.id,
        role: 'user',
        content: '저장된 질문',
        evidence_json: null,
        created_at: '2026-07-26T01:00:00Z',
        route: null,
        workflow: [],
      },
      {
        id: 'history-assistant',
        session_id: session.id,
        role: 'assistant',
        content: '저장된 답변',
        evidence_json: response.evidence,
        created_at: '2026-07-26T01:00:01Z',
        route: response.route,
        workflow: response.workflow,
      },
    ])
    if (path === `/chat/sessions/${session.id}/favorite`) {
      favorite = true
      return Promise.resolve({ ...session, is_favorite: true, version: session.version + 1 })
    }
    return Promise.reject(new Error(`Unexpected request: ${path} ${options?.method ?? 'GET'}`))
  })
  return { client: { request } as unknown as ApiClient, request }
}

function requestBody(options: RequestOptions | undefined): unknown {
  if (typeof options?.body !== 'string') throw new Error('Expected a JSON request body')
  return JSON.parse(options.body) as unknown
}

describe('ChatPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('sends the selected route on Enter and renders only server-returned workflow and ranked evidence', async () => {
    const { client, request } = chatClient()
    render(<ChatPage client={client} />)

    expect(await screen.findByText('주문 데이터')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('검색 경로'), { target: { value: 'VECTOR' } })
    const question = screen.getByLabelText('카탈로그 질문')
    fireEvent.change(question, { target: { value: '주문과 고객 테이블을 찾아줘' } })
    fireEvent.keyDown(question, { key: 'Enter', code: 'Enter' })

    await screen.findByRole('heading', { name: '확인된 테이블' })
    const queryCall = request.mock.calls.find(([path]) => path === '/chat/query')
    expect(requestBody(queryCall?.[1])).toEqual({
      question: '주문과 고객 테이블을 찾아줘',
      maximum_evidence: 5,
      mode: 'VECTOR',
    })
    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.getByLabelText('서버 라우팅 결정')).toHaveTextContent('요청 벡터 → 선택 벡터')
    const workflow = screen.getByLabelText('질문 응답 Workflow')
    expect(within(workflow).getByText('1. 권한 확인')).toBeInTheDocument()
    expect(within(workflow).getByText('8. 대화 저장')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '근거 1 orders 상세 열기' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '근거 1 orders 상세 열기' }))
    const dialog = screen.getByRole('dialog', { name: '근거 테이블 상세와 Lineage' })
    expect(within(dialog).getByText('asset:asset-orders')).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: '연결 테이블' })).toHaveFocus()
    fireEvent.keyDown(dialog, { key: 'Tab', shiftKey: true })
    expect(within(dialog).getByRole('button', { name: '상세 닫기' })).toHaveFocus()
    fireEvent.keyDown(dialog, { key: 'Tab' })
    expect(within(dialog).getByRole('button', { name: '연결 테이블' })).toHaveFocus()
    fireEvent.click(within(dialog).getByRole('button', { name: '연결 테이블' }))
    expect(within(dialog).getByText('asset:asset-related')).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: '상세 닫기' }))
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '근거 1 orders 상세 열기' })).toHaveFocus()
    })
    fireEvent.click(screen.getByRole('button', { name: '근거 1 orders 상세 열기' }))
    const reopenedDialog = screen.getByRole('dialog', { name: '근거 테이블 상세와 Lineage' })
    fireEvent.keyDown(reopenedDialog, { key: 'Escape' })
    expect(screen.queryByRole('dialog', { name: '근거 테이블 상세와 Lineage' })).not.toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '근거 1 orders 상세 열기' })).toHaveFocus()
    })
  })

  it('keeps Shift+Enter as a multiline escape and sends only on plain Enter', async () => {
    const { client, request } = chatClient()
    render(<ChatPage client={client} />)
    await screen.findByText('주문 데이터')

    const question = screen.getByLabelText('카탈로그 질문')
    fireEvent.change(question, { target: { value: '첫 줄' } })
    fireEvent.keyDown(question, { key: 'Enter', code: 'Enter', shiftKey: true })
    expect(request.mock.calls.some(([path]) => path === '/chat/query')).toBe(false)
    expect(question).toHaveValue('첫 줄')

    fireEvent.change(question, { target: { value: '첫 줄\n둘째 줄' } })
    fireEvent.keyDown(question, { key: 'Enter', code: 'Enter' })
    await waitFor(() => expect(request.mock.calls.some(([path]) => path === '/chat/query')).toBe(true))
  })

  it('does not submit an Enter key event while an IME composition is active', async () => {
    const { client, request } = chatClient()
    render(<ChatPage client={client} />)
    await screen.findByText('주문 데이터')

    const question = screen.getByLabelText('카탈로그 질문')
    fireEvent.change(question, { target: { value: '조합 중인 질문' } })
    fireEvent.keyDown(question, { key: 'Enter', code: 'Enter', isComposing: true })

    expect(request.mock.calls.some(([path]) => path === '/chat/query')).toBe(false)
    expect(question).toHaveValue('조합 중인 질문')
  })

  it('does not submit a one-character question from the Enter shortcut', async () => {
    const { client, request } = chatClient()
    render(<ChatPage client={client} />)
    await screen.findByText('주문 데이터')

    const question = screen.getByLabelText('카탈로그 질문')
    fireEvent.change(question, { target: { value: '한' } })
    fireEvent.keyDown(question, { key: 'Enter', code: 'Enter' })

    expect(request.mock.calls.some(([path]) => path === '/chat/query')).toBe(false)
    expect(question).toHaveValue('한')
  })

  it('loads only the bounded history endpoint and restores typed persisted evidence', async () => {
    const { client, request } = chatClient()
    render(<ChatPage client={client} />)

    fireEvent.click(await screen.findByText('주문 데이터'))
    expect(await screen.findByText('저장된 질문')).toBeInTheDocument()
    expect(screen.getByText('저장된 답변')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '근거 1 orders 상세 열기' })).toBeInTheDocument()
    expect(request).toHaveBeenCalledWith(`/chat/sessions/${session.id}/messages?limit=200`)
  })

  it('persists favorites with optimistic concurrency and reports copy success and failure', async () => {
    const clipboard = { writeText: vi.fn<() => Promise<void>>().mockResolvedValueOnce() }
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: clipboard })
    const { client, request } = chatClient()
    render(<ChatPage client={client} />)

    const favorite = await screen.findByRole('button', { name: '주문 데이터 즐겨찾기 추가' })
    fireEvent.click(favorite)
    expect(await screen.findByRole('button', { name: '주문 데이터 즐겨찾기 해제' })).toBeInTheDocument()
    const favoriteCall = request.mock.calls.find(([path]) => path.endsWith('/favorite'))
    expect(requestBody(favoriteCall?.[1])).toEqual({
      is_favorite: true,
      expected_version: 3,
    })

    const question = screen.getByLabelText('카탈로그 질문')
    fireEvent.change(question, { target: { value: '주문 테이블은?' } })
    fireEvent.keyDown(question, { key: 'Enter', code: 'Enter' })
    await screen.findByRole('heading', { name: '확인된 테이블' })

    fireEvent.click(screen.getByRole('button', { name: '질문 복사' }))
    expect(await screen.findByRole('status')).toHaveTextContent('질문 복사 완료')
    clipboard.writeText.mockRejectedValueOnce(new Error('denied'))
    fireEvent.click(screen.getByRole('button', { name: '답변 복사' }))
    expect(await screen.findByRole('status')).toHaveTextContent('답변 복사 실패')
  })

  it('refreshes a stale favorite version after a conflict before the user retries', async () => {
    let sessionReads = 0
    let favoriteWrites = 0
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      if (path === '/chat/sessions?limit=50') {
        sessionReads += 1
        return Promise.resolve([{ ...session, version: sessionReads === 1 ? 3 : 4 }])
      }
      if (path === `/chat/sessions/${session.id}/favorite`) {
        favoriteWrites += 1
        if (favoriteWrites === 1) return Promise.reject(new Error('version conflict'))
        return Promise.resolve({ ...session, is_favorite: true, version: 5 })
      }
      return Promise.reject(new Error(`Unexpected request: ${path} ${options?.method ?? 'GET'}`))
    })
    render(<ChatPage client={{ request } as unknown as ApiClient} />)

    const favorite = await screen.findByRole('button', { name: '주문 데이터 즐겨찾기 추가' })
    fireEvent.click(favorite)
    await waitFor(() => expect(sessionReads).toBe(2))
    fireEvent.click(screen.getByRole('button', { name: '주문 데이터 즐겨찾기 추가' }))
    await screen.findByRole('button', { name: '주문 데이터 즐겨찾기 해제' })

    const writes = request.mock.calls.filter(([path]) => path.endsWith('/favorite'))
    expect(requestBody(writes[0]?.[1])).toMatchObject({ expected_version: 3 })
    expect(requestBody(writes[1]?.[1])).toMatchObject({ expected_version: 4 })
  })

  it('hides stale evidence while a new request is pending and restores a failed question for retry', async () => {
    let queryCount = 0
    let rejectPending: ((reason: Error) => void) | undefined
    const { client: baseClient } = chatClient()
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      if (path === '/chat/query') {
        queryCount += 1
        if (queryCount === 1) return Promise.resolve(response)
        return new Promise((_, reject) => {
          rejectPending = reject
        })
      }
      return baseClient.request(path, options)
    })
    render(<ChatPage client={{ request } as unknown as ApiClient} />)
    await screen.findByText('주문 데이터')

    const question = screen.getByLabelText('카탈로그 질문')
    fireEvent.change(question, { target: { value: '첫 번째 질문' } })
    fireEvent.keyDown(question, { key: 'Enter', code: 'Enter' })
    await screen.findByLabelText('서버 라우팅 결정')

    fireEvent.change(question, { target: { value: '다시 시도할 질문' } })
    fireEvent.keyDown(question, { key: 'Enter', code: 'Enter' })
    expect(screen.queryByLabelText('서버 라우팅 결정')).not.toBeInTheDocument()
    expect(screen.getByText('서버가 응답하면 실제 처리 단계가 표시됩니다.')).toBeInTheDocument()

    rejectPending?.(new Error('provider unavailable'))
    await waitFor(() => expect(question).toHaveValue('다시 시도할 질문'))
    expect(screen.queryByText('다시 시도할 질문', { selector: 'article p' })).not.toBeInTheDocument()
  })

  it('renders server-declared unavailable graph state and ephemeral persistence honestly', async () => {
    const unavailable: ChatResponse = {
      ...response,
      answer: '검증 불가',
      persistence: 'EPHEMERAL_NO_STORE',
      route: {
        requested_mode: 'GRAPH',
        selected_mode: 'GRAPH',
        reason: 'EXPLICIT_SELECTION',
        adapter_state: 'UNAVAILABLE',
      },
      workflow: [
        { stage: 'AUTHORIZATION', status: 'COMPLETED', detail_code: 'AUTHORIZED' },
        { stage: 'BUDGET_RESERVATION', status: 'COMPLETED', detail_code: 'BUDGET_RESERVED' },
        { stage: 'ROUTING', status: 'UNAVAILABLE', detail_code: 'GRAPH_ADAPTER_UNAVAILABLE' },
        { stage: 'RETRIEVAL', status: 'UNAVAILABLE', detail_code: 'RETRIEVAL_NOT_EXECUTED' },
        { stage: 'RERANKING', status: 'SKIPPED', detail_code: 'NO_RETRIEVED_EVIDENCE' },
        { stage: 'COMPOSITION', status: 'REFUSED', detail_code: 'UNAVAILABLE_ROUTE_REFUSED' },
        { stage: 'CITATION_VALIDATION', status: 'SKIPPED', detail_code: 'NO_DRAFT' },
        { stage: 'PERSISTENCE', status: 'SKIPPED', detail_code: 'EPHEMERAL_NO_STORE' },
      ],
      evidence: [],
    }
    const { client: baseClient } = chatClient()
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => (
      path === '/chat/query' ? Promise.resolve(unavailable) : baseClient.request(path, options)
    ))
    render(<ChatPage client={{ request } as unknown as ApiClient} />)
    await screen.findByText('주문 데이터')

    fireEvent.change(screen.getByLabelText('검색 경로'), { target: { value: 'GRAPH' } })
    const question = screen.getByLabelText('카탈로그 질문')
    fireEvent.change(question, { target: { value: '그래프 경로 확인' } })
    fireEvent.keyDown(question, { key: 'Enter', code: 'Enter' })

    expect(await screen.findByText('검증 불가')).toBeInTheDocument()
    expect(screen.getByLabelText('서버 라우팅 결정')).toHaveTextContent('사용 불가')
    expect(screen.getByRole('status')).toHaveTextContent('서버에 저장되지 않습니다')
    expect(screen.queryByRole('button', { name: /근거 .* 상세 열기/ })).not.toBeInTheDocument()
  })

  it('explains that provider-policy binding is distinct from model reachability', async () => {
    const unavailable: ChatResponse = {
      ...response,
      answer: '검증 불가',
      route: {
        requested_mode: 'GENERAL',
        selected_mode: 'GENERAL',
        reason: 'EXPLICIT_SELECTION',
        adapter_state: 'UNAVAILABLE',
      },
      workflow: [
        { stage: 'AUTHORIZATION', status: 'COMPLETED', detail_code: 'CHAT_QUERY_AUTHORIZED' },
        {
          stage: 'ROUTING',
          status: 'UNAVAILABLE',
          detail_code: 'INFERENCE_PROVIDER_POLICY_BINDING_UNAVAILABLE',
        },
      ],
      evidence: [],
    }
    const { client: baseClient } = chatClient()
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => (
      path === '/chat/query' ? Promise.resolve(unavailable) : baseClient.request(path, options)
    ))
    render(<ChatPage client={{ request } as unknown as ApiClient} />)
    await screen.findByText('주문 데이터')

    fireEvent.change(screen.getByLabelText('검색 경로'), { target: { value: 'GENERAL' } })
    const question = screen.getByLabelText('카탈로그 질문')
    fireEvent.change(question, { target: { value: '승인된 테이블을 알려줘' } })
    fireEvent.keyDown(question, { key: 'Enter', code: 'Enter' })

    expect(await screen.findByRole('status')).toHaveTextContent(
      '모델 서버 상태와 별개로, 현재 분류 정책에 승인된 추론 프로필이 연결되지 않았습니다.',
    )
    expect(screen.getByLabelText('질문 응답 Workflow')).toHaveTextContent(
      '승인된 추론 프로필 연결이 필요합니다.',
    )
  })

  it('starts a genuinely empty AUTO session and clears draft selections', async () => {
    const { client } = chatClient()
    render(<ChatPage client={client} />)
    await screen.findByText('주문 데이터')

    fireEvent.change(screen.getByLabelText('검색 경로'), { target: { value: 'VECTOR' } })
    fireEvent.change(screen.getByLabelText('카탈로그 질문'), { target: { value: '작성 중 질문' } })
    fireEvent.click(screen.getByRole('button', { name: /새 세션/ }))

    expect(screen.getByLabelText('검색 경로')).toHaveValue('AUTO')
    expect(screen.getByLabelText('카탈로그 질문')).toHaveValue('')
    expect(screen.getByText('질문을 시작하세요')).toBeInTheDocument()
  })
})
