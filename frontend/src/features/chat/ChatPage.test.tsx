import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
  performance: {
    routing_ms: 12,
    retrieval_ms: 34,
    reranking_ms: 8,
    composition_ms: 120,
    total_ms: 190,
  },
  evidence: [{
    chunk_id: 'chunk-1',
    resource_id: 'asset-orders',
    classification: 'INTERNAL',
    system_id: 'system-1',
    domain_id: null,
    owner_department_id: null,
    name: 'orders',
    asset_kind: 'TABLE',
    description: '주문 원장 [[Dataset:urn:li:dataset:(orders,PROD)]]',
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
  discovery: null,
}

function chatClient() {
  let favorite = false
  const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
    if (path === '/chat/sessions?limit=50') return Promise.resolve([{ ...session, is_favorite: favorite }])
    if (path === `/chat/sessions/${session.id}/messages?limit=200`) return Promise.resolve([
      {
        id: 'history-user',
        session_id: session.id,
        role: 'user',
        content: '저장된 질문',
        evidence_json: null,
        discovery_json: null,
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
        discovery_json: null,
        created_at: '2026-07-26T01:00:01Z',
        route: response.route,
        workflow: response.workflow,
      },
    ])
    if (path === `/chat/sessions/${session.id}/favorite`) {
      favorite = true
      return Promise.resolve({ ...session, is_favorite: true, version: session.version + 1 })
    }
    if (path.startsWith(`/chat/sessions/${session.id}?expected_version=`)) {
      return Promise.resolve(undefined)
    }
    return Promise.reject(new Error(`Unexpected request: ${path} ${options?.method ?? 'GET'}`))
  })
  const requestEventStream = vi.fn((
    path: string,
    _options: RequestOptions,
    onEvent: (event: { event: string; data: unknown }) => void,
  ): Promise<unknown> => {
    if (path === '/chat/query/stream') {
      response.workflow.forEach((step) => onEvent({ event: 'workflow', data: step }))
      const midpoint = Math.ceil(response.answer.length / 2)
      onEvent({ event: 'answer_delta', data: { delta: response.answer.slice(0, midpoint) } })
      onEvent({ event: 'answer_delta', data: { delta: response.answer.slice(midpoint) } })
      return Promise.resolve(response)
    }
    return Promise.reject(new Error(`Unexpected stream request: ${path}`))
  })
  return { client: { request, requestEventStream } as unknown as ApiClient, request, requestEventStream }
}

function requestBody(options: RequestOptions | undefined): unknown {
  if (typeof options?.body !== 'string') throw new Error('Expected a JSON request body')
  return JSON.parse(options.body) as unknown
}

function selectRoute(label: '일반' | '벡터' | '그래프'): void {
  fireEvent.click(screen.getByRole('button', { name: '검색 경로' }))
  fireEvent.click(screen.getByRole('option', { name: `검색 경로 ${label}` }))
}

describe('ChatPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('describes General as retrieval-free and Graph as an authorized Knowledge or lineage route', async () => {
    const { client } = chatClient()
    render(<ChatPage client={client} />)
    await screen.findByText('주문 데이터')

    fireEvent.click(screen.getByRole('button', { name: '검색 경로' }))
    expect(screen.getByText('메타데이터를 검색하지 않고 일반 질문에 답변합니다.')).toBeInTheDocument()
    expect(screen.getByText('인가된 Knowledge Asset 또는 DataHub lineage 관계를 탐색합니다.')).toBeInTheDocument()
  })

  it('shows the pinned Knowledge Asset route and keeps graph evidence out of Catalog detail', async () => {
    const knowledgeResponse: ChatResponse = {
      ...response,
      route: {
        requested_mode: 'AUTO',
        selected_mode: 'GRAPH',
        reason: 'KNOWLEDGE_ASSET_POLICY',
        intent: 'KNOWLEDGE_RELATIONSHIP',
        adapter_state: 'READY',
        knowledge_scope: {
          graph_id: 'graph-1',
          release_id: 'release-7',
          asset_name: '품질 관계 지식',
          policy_id: 'policy-1',
          policy_version: 3,
          policy_hash: 'b'.repeat(64),
        },
      },
      evidence: [{
        ...response.evidence[0]!,
        chunk_id: 'knowledge-node-1',
        resource_id: 'knowledge-node:node-1',
        name: 'Wafer W-001',
        source_type: 'KNOWLEDGE_NODE',
        source_locator: 'urn:li:dataset:(quality)#row=1',
        source_version: 'release-7',
        extraction_method: 'K5_PROJECTED_RECEIPT',
        retrieval_method: 'KNOWLEDGE_GRAPH_RAG',
        graph_nodes: [
          { id: 'node-1', label: '품질 원천', entity_type: 'TABLE', role: 'ROOT', source_locator: 'urn:node-1' },
          { id: 'node-2', label: '품질 결과', entity_type: 'TABLE', role: 'DOWNSTREAM', source_locator: 'urn:node-2' },
        ],
        graph_edges: [{ id: 'edge-1', source: 'node-1', target: 'node-2', relation_type: 'UPSTREAM_OF', source_locator: 'urn:edge-1' }],
      }],
    }
    const { client: baseClient } = chatClient()
    const requestEventStream = vi.fn((path: string): Promise<unknown> => (
      path === '/chat/query/stream'
        ? Promise.resolve(knowledgeResponse)
        : Promise.reject(new Error(`Unexpected stream request: ${path}`))
    ))
    render(<ChatPage client={{
      request: (path: string, options?: RequestOptions) => baseClient.request(path, options),
      requestEventStream,
    } as unknown as ApiClient} />)
    await screen.findByText('주문 데이터')
    const question = screen.getByLabelText('카탈로그 질문')
    fireEvent.change(question, { target: { value: '품질 관계를 알려줘' } })
    fireEvent.keyDown(question, { key: 'Enter', code: 'Enter' })

    expect(await screen.findByText(/지식 Asset 품질 관계 지식/)).toHaveTextContent('version release-7')
    expect(screen.getByLabelText('서버 라우팅 결정')).toHaveTextContent('지식 Asset 관계 탐색')
    expect(screen.getByLabelText('근거 1 Wafer W-001')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '근거 1 Wafer W-001 상세 열기' })).not.toBeInTheDocument()
    expect(screen.getByText('지식 그래프 근거')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '답변에 사용된 인가 그래프 근거' })).toHaveTextContent('2 nodes · 1 edges')
    expect(screen.getByRole('region', { name: '답변에 사용된 인가 그래프' })).toBeInTheDocument()
    expect(screen.queryByRole('dialog', { name: '근거 테이블 상세와 Lineage' })).not.toBeInTheDocument()
  })

  it('sends the selected route on Enter and renders only server-returned workflow and ranked evidence', async () => {
    const { client, requestEventStream } = chatClient()
    render(<ChatPage client={client} />)

    expect(await screen.findByText('주문 데이터')).toBeInTheDocument()
    selectRoute('벡터')
    const question = screen.getByLabelText('카탈로그 질문')
    fireEvent.change(question, { target: { value: '주문과 고객 테이블을 찾아줘' } })
    fireEvent.keyDown(question, { key: 'Enter', code: 'Enter' })

    await screen.findByRole('heading', { name: '확인된 테이블' })
    const queryCall = requestEventStream.mock.calls.find(([path]) => path === '/chat/query/stream')
    expect(requestBody(queryCall?.[1])).toEqual({
      question: '주문과 고객 테이블을 찾아줘',
      maximum_evidence: 5,
      mode: 'VECTOR',
    })
    expect(await screen.findByRole('table')).toBeInTheDocument()
    expect(screen.getByLabelText('서버 라우팅 결정')).toHaveTextContent('요청 벡터 → 선택 벡터')
    const workflow = screen.getByLabelText('질문 응답 Workflow')
    expect(within(workflow).getByText('1. 권한 확인')).toBeInTheDocument()
    expect(within(workflow).getByText('8. 대화 저장')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '근거 1 orders 상세 열기' })).toBeInTheDocument()
    expect(screen.getByText('주문 원장')).toBeInTheDocument()
    expect(screen.queryByText('postgres.analytics.orders')).not.toBeInTheDocument()
    expect(screen.queryByText(/VECTOR · vv7/)).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '근거 1 orders 상세 열기' }))
    const dialog = screen.getByRole('dialog', { name: '근거 테이블 상세와 Lineage' })
    expect(dialog.parentElement).toBe(document.body)
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

  it('previews five authorized citations and states the truthful total before expansion', async () => {
    const expandedResponse: ChatResponse = {
      ...response,
      evidence: Array.from({ length: 7 }, (_, index) => ({
        ...response.evidence[0]!,
        chunk_id: `chunk-${index + 1}`,
        resource_id: `asset-${index + 1}`,
        name: `table_${index + 1}`,
        rank: index + 1,
      })),
    }
    const { client: baseClient } = chatClient()
    const requestEventStream = vi.fn(() => Promise.resolve(expandedResponse))
    render(<ChatPage client={{
      request: (path: string, options?: RequestOptions) => baseClient.request(path, options),
      requestEventStream,
    } as unknown as ApiClient} />)

    await screen.findByText('주문 데이터')
    fireEvent.change(screen.getByLabelText('카탈로그 질문'), { target: { value: '인가된 테이블을 찾아줘' } })
    fireEvent.click(screen.getByRole('button', { name: '질문 전송' }))

    expect(await screen.findByText('총 7개 중 5개 표시 · 더 있음')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '근거 5 table_5 상세 열기' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '근거 6 table_6 상세 열기' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '나머지 2개 보기' }))
    expect(screen.getByText('총 7개 모두 표시')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '근거 7 table_7 상세 열기' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '처음 5개만 보기' }))
    expect(screen.getByText('총 7개 중 5개 표시 · 더 있음')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '근거 6 table_6 상세 열기' })).not.toBeInTheDocument()
  })

  it('keeps bounded discovery results separate from citations without inventing a total', async () => {
    const discoveryItems = Array.from({ length: 7 }, (_, index) => ({
      ...response.evidence[0]!,
      chunk_id: `discovery-${index + 1}`,
      resource_id: `discovery-asset-${index + 1}`,
      name: `authorized_asset_${index + 1}`,
      source_type: index === 5
        ? 'KNOWLEDGE_NODE'
        : index === 6 ? 'GOVERNANCE_DOCUMENT' : index === 4 ? 'UNRECOGNIZED_SOURCE' : 'CATALOG_ASSET',
      rank: index + 1,
    }))
    const discoveryResponse: ChatResponse = {
      ...response,
      discovery: {
        items: discoveryItems,
        returned_count: 7,
        limit: 8,
        truncated: true,
        retrieved_count: 7,
        reranked_count: 5,
        answer_context_count: 5,
        catalog_search_query: 'inspection_results',
        catalog_search_fields: ['TABLE'],
        total: null,
        total_exact: false,
        next_cursor: null,
      },
    }
    const { client: baseClient } = chatClient()
    const requestEventStream = vi.fn(() => Promise.resolve(discoveryResponse))
    render(<ChatPage client={{
      request: (path: string, options?: RequestOptions) => baseClient.request(path, options),
      requestEventStream,
    } as unknown as ApiClient} />)

    await screen.findByText('주문 데이터')
    fireEvent.change(screen.getByLabelText('카탈로그 질문'), { target: { value: '인가된 자산 후보를 찾아줘' } })
    fireEvent.click(screen.getByRole('button', { name: '질문 전송' }))

    expect(await screen.findByText(/상위 7개 조회 · 추가 결과 가능/)).toHaveTextContent(
      '검색 7 · 재정렬 5 · 답변 입력 5',
    )
    expect(screen.getByLabelText('현재 응답 처리 시간')).toHaveTextContent('전체190 ms')
    expect(screen.getByLabelText('검색 후보 5 authorized_asset_5')).toHaveTextContent('기타 인가 후보')
    expect(screen.queryByRole('button', { name: '검색 후보 5 authorized_asset_5 상세 열기' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '검색 후보 6 authorized_asset_6 상세 열기' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '근거 1 orders 상세 열기' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '검색 후보 나머지 2개 보기' }))
    expect(screen.getByLabelText('검색 후보 6 authorized_asset_6')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '검색 후보 6 authorized_asset_6 상세 열기' })).not.toBeInTheDocument()
    expect(screen.getByText('지식 그래프 후보')).toBeInTheDocument()
    expect(screen.getByLabelText('검색 후보 7 authorized_asset_7')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '검색 후보 7 authorized_asset_7 상세 열기' })).not.toBeInTheDocument()
    expect(screen.getByText('거버넌스 문서')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '같은 카탈로그 후보 범위 전체 보기' }))
    expect(new URL(window.location.href).searchParams.get('page')).toBe('catalog')
    expect(new URL(window.location.href).searchParams.get('q')).toBe('inspection_results')
    expect(new URL(window.location.href).searchParams.get('search_fields')).toBe('TABLE')
  })

  it('keeps an empty canonical candidate query as a full-inventory Catalog handoff', async () => {
    const discoveryResponse: ChatResponse = {
      ...response,
      discovery: {
        items: [response.evidence[0]!],
        returned_count: 1,
        limit: 8,
        truncated: true,
        retrieved_count: 1,
        reranked_count: 0,
        answer_context_count: 1,
        catalog_search_query: '',
        catalog_search_fields: [],
        total: null,
        total_exact: false,
        next_cursor: null,
      },
    }
    const { client: baseClient } = chatClient()
    render(<ChatPage client={{
      request: (path: string, options?: RequestOptions) => baseClient.request(path, options),
      requestEventStream: vi.fn(() => Promise.resolve(discoveryResponse)),
    } as unknown as ApiClient} />)

    await screen.findByText('주문 데이터')
    fireEvent.change(screen.getByLabelText('카탈로그 질문'), {
      target: { value: '관련 자산을 의미 기반으로 찾아줘' },
    })
    fireEvent.click(screen.getByRole('button', { name: '질문 전송' }))
    fireEvent.click(await screen.findByRole('button', {
      name: '같은 카탈로그 후보 범위 전체 보기',
    }))

    const destination = new URL(window.location.href)
    expect(destination.searchParams.get('page')).toBe('catalog')
    expect(destination.searchParams.get('q')).toBe('')
    expect(destination.searchParams.has('search_fields')).toBe(false)
  })

  it('renders server-observed in-progress workflow stages before the final answer arrives', async () => {
    let resolveResult: ((value: ChatResponse) => void) | undefined
    const { client: baseClient } = chatClient()
    const requestEventStream = vi.fn((
      path: string,
      _options: RequestOptions,
      onEvent: (event: { event: string; data: unknown }) => void,
    ): Promise<ChatResponse> => {
      if (path !== '/chat/query/stream') return Promise.reject(new Error(`Unexpected stream: ${path}`))
      onEvent({
        event: 'workflow',
        data: {
          stage: 'AUTHORIZATION',
          status: 'IN_PROGRESS',
          detail_code: 'AUTHORIZATION_IN_PROGRESS',
        },
      })
      onEvent({
        event: 'workflow',
        data: {
          stage: 'AUTHORIZATION',
          status: 'COMPLETED',
          detail_code: 'CHAT_QUERY_AUTHORIZED',
        },
      })
      onEvent({
        event: 'workflow',
        data: {
          stage: 'RETRIEVAL',
          status: 'IN_PROGRESS',
          detail_code: 'RETRIEVAL_IN_PROGRESS',
        },
      })
      return new Promise((resolve) => {
        resolveResult = resolve
      })
    })
    render(<ChatPage client={{
      request: (path: string, options?: RequestOptions) => baseClient.request(path, options),
      requestEventStream,
    } as unknown as ApiClient} />)
    await screen.findByText('주문 데이터')

    const question = screen.getByLabelText('카탈로그 질문')
    fireEvent.change(question, { target: { value: '주문 테이블을 찾아줘' } })
    fireEvent.keyDown(question, { key: 'Enter', code: 'Enter' })

    const workflow = await screen.findByLabelText('질문 응답 Workflow')
    expect(within(workflow).getByText('진행 중')).toBeInTheDocument()
    expect(within(workflow).getByText('근거 검색')).toBeInTheDocument()
    expect(within(workflow).getByText('인가된 근거를 검색하고 있습니다.')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '확인된 테이블' })).not.toBeInTheDocument()

    resolveResult?.(response)
    expect(await screen.findByRole('heading', { name: '확인된 테이블' })).toBeInTheDocument()
    expect(within(screen.getByLabelText('질문 응답 Workflow')).queryByText('진행 중')).not.toBeInTheDocument()
  })

  it('keeps Shift+Enter as a multiline escape and sends only on plain Enter', async () => {
    const { client, requestEventStream } = chatClient()
    render(<ChatPage client={client} />)
    await screen.findByText('주문 데이터')

    const question = screen.getByLabelText('카탈로그 질문')
    fireEvent.change(question, { target: { value: '첫 줄' } })
    fireEvent.keyDown(question, { key: 'Enter', code: 'Enter', shiftKey: true })
    expect(requestEventStream.mock.calls.some(([path]) => path === '/chat/query/stream')).toBe(false)
    expect(question).toHaveValue('첫 줄')

    fireEvent.change(question, { target: { value: '첫 줄\n둘째 줄' } })
    fireEvent.keyDown(question, { key: 'Enter', code: 'Enter' })
    await waitFor(() => expect(
      requestEventStream.mock.calls.some(([path]) => path === '/chat/query/stream'),
    ).toBe(true))
    const renderedQuestion = document.querySelector('.chat-question-text')
    if (!renderedQuestion) throw new Error('Expected the submitted question to be rendered')
    expect(renderedQuestion).toHaveClass('chat-question-text')
    expect(renderedQuestion.textContent).toBe('첫 줄\n둘째 줄')
  })

  it('copies an immutable historical question into the composer and resends it as a new question', async () => {
    const { client, requestEventStream } = chatClient()
    render(<ChatPage client={client} />)
    await screen.findByText('주문 데이터')

    fireEvent.change(screen.getByLabelText('카탈로그 질문'), { target: { value: '원래 질문' } })
    fireEvent.click(screen.getByRole('button', { name: '질문 전송' }))
    await screen.findByRole('heading', { name: '확인된 테이블' })
    fireEvent.click(screen.getByRole('button', { name: '질문을 입력창에서 편집' }))
    expect(screen.getByLabelText('카탈로그 질문')).toHaveValue('원래 질문')
    expect(screen.getAllByText('원래 질문')).toHaveLength(2)

    fireEvent.change(screen.getByLabelText('카탈로그 질문'), { target: { value: '수정한 새 질문' } })
    fireEvent.click(screen.getByRole('button', { name: '질문 전송' }))
    await waitFor(() => expect(requestEventStream).toHaveBeenCalledTimes(2))
    expect(requestBody(requestEventStream.mock.calls[1]?.[1])).toEqual(expect.objectContaining({
      question: '수정한 새 질문',
    }))
    expect(screen.getByText('원래 질문')).toBeInTheDocument()
  })

  it('aborts an in-flight answer without persisting an incomplete assistant response', async () => {
    const { client: baseClient } = chatClient()
    let observedSignal: AbortSignal | undefined
    const requestEventStream = vi.fn((_path: string, options: RequestOptions) => {
      observedSignal = options.signal ?? undefined
      return new Promise<ChatResponse>((_resolve, reject) => {
        options.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
      })
    })
    render(<ChatPage client={{
      request: (path: string, options?: RequestOptions) => baseClient.request(path, options),
      requestEventStream,
    } as unknown as ApiClient} />)
    await screen.findByText('주문 데이터')

    fireEvent.change(screen.getByLabelText('카탈로그 질문'), { target: { value: '중지할 질문' } })
    fireEvent.click(screen.getByRole('button', { name: '질문 전송' }))
    fireEvent.click(await screen.findByRole('button', { name: '답변 생성 중지' }))

    await waitFor(() => expect(observedSignal?.aborted).toBe(true))
    expect(screen.getByText('중지할 질문')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '답변 근거 다시 보기' })).not.toBeInTheDocument()
    expect(screen.queryByText(/오류|aborted/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '질문 전송' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '질문을 입력창에서 편집' }))
    expect(screen.getByRole('button', { name: '질문 전송' })).toBeEnabled()
  })

  it('auto-grows the composer to a six-line cap and then uses vertical scrolling', async () => {
    const { client } = chatClient()
    render(<ChatPage client={client} />)
    await screen.findByText('주문 데이터')
    const question = screen.getByLabelText<HTMLTextAreaElement>('카탈로그 질문')
    Object.defineProperty(question, 'scrollHeight', { configurable: true, value: 360 })
    fireEvent.change(question, { target: { value: Array.from({ length: 8 }, (_, index) => `줄 ${index}`).join('\n') } })
    expect(question).toHaveAttribute('rows', '1')
    expect(question.style.overflowY).toBe('auto')
    expect(Number.parseFloat(question.style.height)).toBeLessThan(150)
  })

  it('caps questions at 12,000 characters and shows the live count at the composer edge', async () => {
    const { client } = chatClient()
    render(<ChatPage client={client} />)
    await screen.findByText('주문 데이터')

    const question = screen.getByLabelText('카탈로그 질문')
    expect(question).toHaveAttribute('maxlength', '12000')
    expect(screen.getByText('0 / 12,000')).toBeInTheDocument()
    fireEvent.change(question, { target: { value: '가'.repeat(12_001) } })
    expect(question).toHaveValue('가'.repeat(12_000))
    expect(screen.getByText('12,000 / 12,000')).toBeInTheDocument()
  })

  it('renders server answer deltas before the final result and follows the streaming answer', async () => {
    let resolveResult: ((value: ChatResponse) => void) | undefined
    let emit: ((event: { event: string; data: unknown }) => void) | undefined
    const scrollIntoView = vi.fn()
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: scrollIntoView,
    })
    const { client: baseClient } = chatClient()
    const requestEventStream = vi.fn((
      _path: string,
      _options: RequestOptions,
      onEvent: (event: { event: string; data: unknown }) => void,
    ) => {
      emit = onEvent
      return new Promise<ChatResponse>((resolve) => { resolveResult = resolve })
    })
    render(<ChatPage client={{
      request: (path: string, options?: RequestOptions) => baseClient.request(path, options),
      requestEventStream,
    } as unknown as ApiClient} />)
    await screen.findByText('주문 데이터')

    fireEvent.change(screen.getByLabelText('카탈로그 질문'), { target: { value: '주문 테이블을 찾아줘' } })
    fireEvent.click(screen.getByRole('button', { name: '질문 전송' }))

    const midpoint = Math.ceil(response.answer.length / 2)
    act(() => emit?.({ event: 'answer_delta', data: { delta: response.answer.slice(0, midpoint) } }))
    expect(screen.getByText(/확인된 테/)).toBeInTheDocument()
    act(() => emit?.({ event: 'answer_delta', data: { delta: response.answer.slice(midpoint) } }))
    const answerHeading = await screen.findByRole('heading', { name: '확인된 테이블' })
    await waitFor(() => expect(scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'end' }))
    expect(answerHeading.closest('article')).toHaveClass('is-revealing')
    act(() => resolveResult?.(response))
    await waitFor(() => expect(screen.getByRole('heading', { name: '확인된 테이블' }).closest('article')).not.toHaveClass('is-revealing'))
  })

  it('stops answer following on scroll-up, resumes at bottom, and restarts for a new question', async () => {
    let resolveResult: ((value: ChatResponse) => void) | undefined
    let emit: ((event: { event: string; data: unknown }) => void) | undefined
    const scrollIntoView = vi.fn()
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: scrollIntoView,
    })
    const { client: baseClient } = chatClient()
    const requestEventStream = vi.fn((
      _path: string,
      _options: RequestOptions,
      onEvent: (event: { event: string; data: unknown }) => void,
    ) => {
      emit = onEvent
      return new Promise<ChatResponse>((resolve) => { resolveResult = resolve })
    })
    render(<ChatPage client={{
      request: (path: string, options?: RequestOptions) => baseClient.request(path, options),
      requestEventStream,
    } as unknown as ApiClient} />)
    await screen.findByText('주문 데이터')

    fireEvent.change(screen.getByLabelText('카탈로그 질문'), { target: { value: '주문 테이블을 찾아줘' } })
    fireEvent.click(screen.getByRole('button', { name: '질문 전송' }))
    act(() => emit?.({ event: 'answer_delta', data: { delta: '첫 번째 승인 chunk' } }))
    await waitFor(() => expect(scrollIntoView).toHaveBeenCalled())
    scrollIntoView.mockClear()
    const log = screen.getByLabelText('답변 생성 중').closest('.chat-log')!
    fireEvent.wheel(log, { deltaY: -120 })
    act(() => emit?.({ event: 'answer_delta', data: { delta: ' 두 번째 승인 chunk' } }))
    expect(scrollIntoView).not.toHaveBeenCalled()
    Object.defineProperties(log, {
      scrollHeight: { configurable: true, value: 500 },
      clientHeight: { configurable: true, value: 200 },
      scrollTop: { configurable: true, value: 300 },
    })
    fireEvent.scroll(log)
    act(() => emit?.({ event: 'answer_delta', data: { delta: ' 세 번째 승인 chunk' } }))
    await waitFor(() => expect(scrollIntoView).toHaveBeenCalled())
    act(() => resolveResult?.(response))
    expect(await screen.findByRole('heading', { name: '확인된 테이블' })).toBeInTheDocument()
  })

  it('does not submit an Enter key event while an IME composition is active', async () => {
    const { client, requestEventStream } = chatClient()
    render(<ChatPage client={client} />)
    await screen.findByText('주문 데이터')

    const question = screen.getByLabelText('카탈로그 질문')
    fireEvent.change(question, { target: { value: '조합 중인 질문' } })
    fireEvent.keyDown(question, { key: 'Enter', code: 'Enter', isComposing: true })

    expect(requestEventStream.mock.calls.some(([path]) => path === '/chat/query/stream')).toBe(false)
    expect(question).toHaveValue('조합 중인 질문')
  })

  it('does not submit a one-character question from the Enter shortcut', async () => {
    const { client, requestEventStream } = chatClient()
    render(<ChatPage client={client} />)
    await screen.findByText('주문 데이터')

    const question = screen.getByLabelText('카탈로그 질문')
    fireEvent.change(question, { target: { value: '한' } })
    fireEvent.keyDown(question, { key: 'Enter', code: 'Enter' })

    expect(requestEventStream.mock.calls.some(([path]) => path === '/chat/query/stream')).toBe(false)
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
    const questionActions = screen.getByRole('group', { name: '질문 작업' })
    expect(questionActions.tagName).toBe('DIV')
    expect(questionActions).toHaveClass('chat-message-actions-user')
    expect(questionActions.closest('footer')).toBeNull()
    expect(questionActions.parentElement).toHaveClass('message-user')
    clipboard.writeText.mockRejectedValueOnce(new Error('denied'))
    fireEvent.click(screen.getByRole('button', { name: '답변 복사' }))
    expect(await screen.findByRole('status')).toHaveTextContent('답변 복사 실패')
  })

  it('filters the owner history to favorites and archives a session through the versioned endpoint', async () => {
    const { client, request } = chatClient()
    render(<ChatPage client={client} />)
    await screen.findByText('주문 데이터')

    fireEvent.click(screen.getByRole('tab', { name: '즐겨찾기' }))
    expect(screen.getByText('즐겨찾기가 없습니다.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: '최근' }))
    fireEvent.click(screen.getByRole('button', { name: '주문 데이터 즐겨찾기 추가' }))
    await screen.findByRole('button', { name: '주문 데이터 즐겨찾기 해제' })
    fireEvent.click(screen.getByRole('tab', { name: '즐겨찾기' }))
    expect(screen.getByRole('button', { name: '주문 데이터 열기' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '주문 데이터 삭제' }))
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: '주문 데이터 열기' })).not.toBeInTheDocument()
    })
    expect(request).toHaveBeenCalledWith(
      `/chat/sessions/${session.id}?expected_version=${session.version + 1}`,
      { method: 'DELETE' },
    )
  })

  it('collapses only history and keeps the fixed Evidence panel without a manual width toggle', async () => {
    const { client } = chatClient()
    render(<ChatPage client={client} />)

    fireEvent.click(await screen.findByRole('button', { name: '주문 데이터 열기' }))
    await screen.findByText('저장된 답변')
    fireEvent.click(screen.getByRole('button', { name: '대화 이력 숨기기' }))
    expect(screen.getByRole('button', { name: '대화 이력 펼치기' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /EVIDENCE 패널 (?:숨기기|펼치기)/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '근거 1 orders 상세 열기' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '이 답변의 근거 다시 보기' }))
    expect(screen.getByRole('button', { name: '근거 1 orders 상세 열기' })).toBeInTheDocument()
  })

  it('clears account-local message state when the authenticated client boundary changes', async () => {
    const first = chatClient()
    const secondSession = { ...session, id: 'session-2', title: '다른 계정 대화' }
    const secondRequest = vi.fn((path: string) => (
      path === '/chat/sessions?limit=50'
        ? Promise.resolve([secondSession])
        : Promise.reject(new Error(`Unexpected request: ${path}`))
    ))
    const view = render(<ChatPage client={first.client} />)
    await screen.findByRole('button', { name: '주문 데이터 열기' })

    view.rerender(<ChatPage client={{ request: secondRequest } as unknown as ApiClient} />)
    expect(screen.queryByRole('button', { name: '주문 데이터 열기' })).not.toBeInTheDocument()
    expect(await screen.findByRole('button', { name: '다른 계정 대화 열기' })).toBeInTheDocument()
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
    const requestEventStream = vi.fn((
      path: string,
      options: RequestOptions,
      onEvent: (event: { event: string; data: unknown }) => void,
    ): Promise<unknown> => {
      if (path === '/chat/query/stream') {
        queryCount += 1
        if (queryCount === 1) return Promise.resolve(response)
        return new Promise((_, reject) => {
          rejectPending = reject
        })
      }
      return baseClient.requestEventStream(path, options, onEvent)
    })
    render(<ChatPage client={{
      request: (path: string, options?: RequestOptions) => baseClient.request(path, options),
      requestEventStream,
    } as unknown as ApiClient} />)
    await screen.findByText('주문 데이터')

    const question = screen.getByLabelText('카탈로그 질문')
    fireEvent.change(question, { target: { value: '첫 번째 질문' } })
    fireEvent.keyDown(question, { key: 'Enter', code: 'Enter' })
    await screen.findByLabelText('서버 라우팅 결정')

    fireEvent.change(question, { target: { value: '다시 시도할 질문' } })
    fireEvent.keyDown(question, { key: 'Enter', code: 'Enter' })
    expect(screen.queryByLabelText('서버 라우팅 결정')).not.toBeInTheDocument()
    expect(screen.getByText('서버가 실제 처리 단계를 시작하면 표시됩니다.')).toBeInTheDocument()

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
    const requestEventStream = vi.fn((
      path: string,
      options: RequestOptions,
      onEvent: (event: { event: string; data: unknown }) => void,
    ): Promise<unknown> => (
      path === '/chat/query/stream'
        ? Promise.resolve(unavailable)
        : baseClient.requestEventStream(path, options, onEvent)
    ))
    render(<ChatPage client={{
      request: (path: string, options?: RequestOptions) => baseClient.request(path, options),
      requestEventStream,
    } as unknown as ApiClient} />)
    await screen.findByText('주문 데이터')

    selectRoute('그래프')
    const question = screen.getByLabelText('카탈로그 질문')
    fireEvent.change(question, { target: { value: '그래프 경로 확인' } })
    fireEvent.keyDown(question, { key: 'Enter', code: 'Enter' })

    expect(await screen.findByText('검증 불가')).toBeInTheDocument()
    expect(screen.getByLabelText('서버 라우팅 결정')).toHaveTextContent('사용 불가')
    expect(screen.getByRole('status')).toHaveTextContent('서버에 저장되지 않습니다')
    expect(screen.queryByRole('button', { name: /근거 .* 상세 열기/ })).not.toBeInTheDocument()
  })

  it('renders a clearly separated general-knowledge answer with no internal citations', async () => {
    const generalAnswer: ChatResponse = {
      ...response,
      answer: '※ 사내 인용 근거가 없어 일반 지식으로 답변합니다.\n\n온톨로지는 개념과 관계를 구조화한 지식 모델입니다.',
      workflow: [
        { stage: 'AUTHORIZATION', status: 'COMPLETED', detail_code: 'CHAT_QUERY_AUTHORIZED' },
        { stage: 'RETRIEVAL', status: 'COMPLETED', detail_code: 'GENERAL_RETRIEVAL_COMPLETED' },
        { stage: 'RERANKING', status: 'SKIPPED', detail_code: 'NO_RETRIEVED_EVIDENCE' },
        {
          stage: 'COMPOSITION',
          status: 'COMPLETED',
          detail_code: 'GENERAL_KNOWLEDGE_DRAFT_COMPOSED',
        },
        {
          stage: 'CITATION_VALIDATION',
          status: 'SKIPPED',
          detail_code: 'NO_INTERNAL_CITATIONS_GENERAL_ANSWER',
        },
      ],
      evidence: [],
    }
    const { client: baseClient } = chatClient()
    const requestEventStream = vi.fn((
      path: string,
      options: RequestOptions,
      onEvent: (event: { event: string; data: unknown }) => void,
    ): Promise<unknown> => (
      path === '/chat/query/stream'
        ? Promise.resolve(generalAnswer)
        : baseClient.requestEventStream(path, options, onEvent)
    ))
    render(<ChatPage client={{
      request: (path: string, options?: RequestOptions) => baseClient.request(path, options),
      requestEventStream,
    } as unknown as ApiClient} />)
    await screen.findByText('주문 데이터')

    const question = screen.getByLabelText('카탈로그 질문')
    fireEvent.change(question, { target: { value: '온톨로지가 뭐야?' } })
    fireEvent.keyDown(question, { key: 'Enter', code: 'Enter' })

    expect(await screen.findByText(/사내 인용 근거가 없어 일반 지식으로 답변합니다/)).toBeInTheDocument()
    expect(screen.getByLabelText('질문 응답 Workflow')).toHaveTextContent(
      '사내 근거와 분리된 일반 지식 답변을 작성했습니다.',
    )
    expect(screen.getByText('총 0개 모두 표시')).toBeInTheDocument()
  })

  it.each([
    {
      detailCode: 'INVALID_GROUNDED_DRAFT_CITATIONS',
      detailText: '답변 초안의 인용 형식을 검증하지 못해 생성을 중단했습니다.',
      stage: 'COMPOSITION' as const,
      status: 'REFUSED' as const,
    },
    {
      detailCode: 'FINAL_CITATION_REAUTHORIZATION_FAILED',
      detailText: '최종 권한 또는 근거 상태가 변경되어 답변을 중단했습니다.',
      stage: 'CITATION_VALIDATION' as const,
      status: 'REFUSED' as const,
    },
  ])('renders the server refusal state for $detailCode', async ({
    detailCode,
    detailText,
    stage,
    status,
  }) => {
    const refused: ChatResponse = {
      ...response,
      answer: '검증 불가',
      workflow: [{ stage, status, detail_code: detailCode }],
      evidence: [],
    }
    const { client: baseClient } = chatClient()
    const requestEventStream = vi.fn((
      path: string,
      options: RequestOptions,
      onEvent: (event: { event: string; data: unknown }) => void,
    ): Promise<unknown> => (
      path === '/chat/query/stream'
        ? Promise.resolve(refused)
        : baseClient.requestEventStream(path, options, onEvent)
    ))
    render(<ChatPage client={{
      request: (path: string, options?: RequestOptions) => baseClient.request(path, options),
      requestEventStream,
    } as unknown as ApiClient} />)
    await screen.findByText('주문 데이터')

    const question = screen.getByLabelText('카탈로그 질문')
    fireEvent.change(question, { target: { value: 'capital 이름을 가진 테이블을 찾아줘' } })
    fireEvent.keyDown(question, { key: 'Enter', code: 'Enter' })

    expect(await screen.findByText('검증 불가')).toBeInTheDocument()
    expect(screen.getByLabelText('질문 응답 Workflow')).toHaveTextContent(detailText)
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
    const requestEventStream = vi.fn((
      path: string,
      options: RequestOptions,
      onEvent: (event: { event: string; data: unknown }) => void,
    ): Promise<unknown> => (
      path === '/chat/query/stream'
        ? Promise.resolve(unavailable)
        : baseClient.requestEventStream(path, options, onEvent)
    ))
    render(<ChatPage client={{
      request: (path: string, options?: RequestOptions) => baseClient.request(path, options),
      requestEventStream,
    } as unknown as ApiClient} />)
    await screen.findByText('주문 데이터')

    selectRoute('일반')
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

    selectRoute('벡터')
    fireEvent.change(screen.getByLabelText('카탈로그 질문'), { target: { value: '작성 중 질문' } })
    fireEvent.click(screen.getByRole('button', { name: '새 대화' }))

    expect(screen.getByRole('button', { name: '검색 경로' })).toHaveTextContent('자동')
    expect(screen.getByLabelText('카탈로그 질문')).toHaveValue('')
    expect(screen.getByText('데이터를 이해하는 대화를 시작하세요')).toBeInTheDocument()
  })
})
