import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient } from '../../api/client'
import type { KnowledgeRelease } from '../../api/types'
import { KnowledgeChatPage } from './KnowledgeChatPage'

const release: KnowledgeRelease = {
  id: 'release-1',
  graph_id: 'graph-1',
  release_no: 3,
  ontology_version_id: 'ontology-1',
  content_hash: 'hash-1',
  node_count: 2,
  edge_count: 1,
  published_by: '00000000-0000-0000-0000-000000000001',
  published_at: '2026-07-20T08:00:00Z',
}

describe('KnowledgeChatPage', () => {
  it('uses the release-scoped cited GraphRAG API and never routes a question to general chat', async () => {
    const request = vi.fn((path: string, options?: RequestInit) => {
      if (path === '/knowledge/graphs') return Promise.resolve([{
        id: 'graph-1', slug: 'semiconductor', name: 'Semiconductor', graph_type: 'DOMAIN',
        status: 'ACTIVE', classification: 'INTERNAL', active_release_id: 'release-1', version: 2,
      }])
      if (path === '/knowledge/graphs/graph-1/releases') return Promise.resolve([release])
      if (path === '/knowledge/graphs/graph-1/releases/release-1/snapshot?maximum_nodes=200') {
        return Promise.resolve({
          release,
          filtered: false,
          nodes: [{ id: 'tool-1', entity_type: 'Tool', properties: { name: 'ETCH-01' }, classification: 1, provenance: [] }],
          edges: [],
        })
      }
      if (path === '/knowledge/graphs/graph-1/releases/release-1/graphrag') {
        expect(options?.method).toBe('POST')
        if (typeof options?.body !== 'string') throw new Error('Expected a JSON request body.')
        expect(JSON.parse(options.body)).toEqual({
          question: '연결 관계를 보여줘', start_node_id: 'tool-1', direction: 'BOTH', edge_types: [], maximum_hops: 1, maximum_nodes: 8,
        })
        return Promise.resolve({
          release,
          truncated: false,
          answer: 'ETCH-01은 검증된 반도체 장비 노드입니다.',
          citations: [{ evidence_id: 'kg:release-1:tool-1', source_locator: 'report.pdf#page=3', source_version: 'hash-1', page_number: 3 }],
          model_audit: { provider: 'ollama', model: 'gemma4:latest', prompt_version: 'knowledge-graphrag-v1', tool_schema_version: 'knowledge-evidence-v1' },
          nodes: [{ id: 'tool-1', entity_type: 'Tool', properties: { name: 'ETCH-01' }, classification: 1, provenance: [] }],
          edges: [],
        })
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    const client = { request } as unknown as ApiClient
    render(<KnowledgeChatPage client={client} onNavigate={vi.fn()} />)

    expect(screen.getByRole('navigation', { name: '지식관리 메뉴' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Chat Test/ })).toHaveAttribute('aria-current', 'page')
    await screen.findByRole('option', { name: /ETCH-01/ })
    const evidenceGraph = screen.getByRole('region', { name: 'GraphRAG 근거 그래프' })
    expect(await within(evidenceGraph).findByLabelText('ETCH-01, Tool · 근거 0')).toBeInTheDocument()
    expect(screen.getByText('1 nodes · 0 edges · 권한 내 bounded preview')).toBeInTheDocument()
    fireEvent.click(within(evidenceGraph).getByLabelText('ETCH-01, Tool · 근거 0'))
    expect(screen.getByLabelText('시작 노드')).toHaveValue('tool-1')
    fireEvent.change(screen.getByLabelText('질문'), { target: { value: '연결 관계를 보여줘' } })
    fireEvent.click(screen.getByRole('button', { name: 'GraphRAG 질의' }))

    await screen.findByText('ETCH-01은 검증된 반도체 장비 노드입니다.')
    await screen.findByText('1 nodes · 0 edges · 답변 근거 경로')
    await waitFor(() => expect(request).toHaveBeenCalledWith(
      '/knowledge/graphs/graph-1/releases/release-1/graphrag',
      expect.objectContaining({ method: 'POST' }),
    ))
    expect(request.mock.calls.some(([path]) => String(path).startsWith('/chat'))).toBe(false)
  })

  it('uses semantic seed selection when no start node is selected and then shows cited evidence', async () => {
    const request = vi.fn((path: string, options?: RequestInit) => {
      if (path === '/knowledge/graphs') return Promise.resolve([{
        id: 'graph-1', slug: 'semiconductor', name: 'Semiconductor', graph_type: 'DOMAIN',
        status: 'ACTIVE', classification: 'INTERNAL', active_release_id: 'release-1', version: 2,
      }])
      if (path === '/knowledge/graphs/graph-1/releases') return Promise.resolve([release])
      if (path === '/knowledge/graphs/graph-1/releases/release-1/snapshot?maximum_nodes=200') {
        return Promise.resolve({
          release,
          filtered: true,
          nodes: [
            { id: 'tool-1', entity_type: 'Tool', properties: { name: 'ETCH-01' }, classification: 1, provenance: [] },
            { id: 'process-1', entity_type: 'Process', properties: { name: 'Etching' }, classification: 1, provenance: [] },
          ],
          edges: [{
            id: 'edge-1', source_id: 'tool-1', target_id: 'process-1', edge_type: 'PERFORMS',
            properties: {}, classification: 1, provenance: [],
          }],
        })
      }
      if (path === '/knowledge/graphs/graph-1/releases/release-1/graphrag') {
        if (typeof options?.body !== 'string') throw new Error('Expected a JSON request body.')
        expect(JSON.parse(options.body)).toEqual({
          question: '식각 공정 장비는?', start_node_id: null, direction: 'BOTH', edge_types: [], maximum_hops: 1, maximum_nodes: 8,
        })
        return Promise.resolve({
          release,
          truncated: true,
          answer: '질문 의미에 따라 ETCH-01이 근거로 선택됐습니다.',
          citations: [{ evidence_id: 'kg:release-1:tool-1', source_locator: 'report.pdf#page=3', source_version: 'hash-1', page_number: 3 }],
          model_audit: { provider: 'ollama', model: 'gemma4:latest', prompt_version: 'knowledge-graphrag-v1', tool_schema_version: 'knowledge-evidence-v1' },
          nodes: [{ id: 'tool-1', entity_type: 'Tool', properties: { name: 'ETCH-01' }, classification: 1, provenance: [] }],
          edges: [],
        })
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    render(
      <KnowledgeChatPage
        client={{ request } as unknown as ApiClient}
        onNavigate={vi.fn()}
      />,
    )

    expect(await screen.findByText('2 nodes · 1 edges · 권한 내 bounded preview · filtered')).toBeInTheDocument()
    expect(screen.getByLabelText('시작 노드')).toHaveValue('')
    expect(screen.getByRole('option', {
      name: '자동 선택 · 의미 검색 또는 소형 그래프 bounded fallback',
    })).toBeInTheDocument()
    expect(screen.getByText(/질문 의미 기반 또는 소형 그래프 bounded fallback/))
      .toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('질문'), { target: { value: '식각 공정 장비는?' } })
    expect(screen.getByRole('button', { name: 'GraphRAG 질의' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'GraphRAG 질의' }))

    expect(await screen.findByText('질문 의미에 따라 ETCH-01이 근거로 선택됐습니다.')).toBeInTheDocument()
    expect(screen.getByText('1 nodes · 0 edges · 답변 근거 경로')).toBeInTheDocument()
    expect(screen.getByText('자동 seed · 의미 검색 또는 소형 그래프 bounded fallback'))
      .toBeInTheDocument()
    expect(request.mock.calls.some(([path]) => String(path).startsWith('/chat'))).toBe(false)
  })
})
