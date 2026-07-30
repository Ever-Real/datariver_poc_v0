import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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
      if (path === '/knowledge/graphs/graph-1/releases/release-1/snapshot?maximum_nodes=200') return Promise.resolve({
        release,
        filtered: false,
        nodes: [{ id: 'tool-1', entity_type: 'Tool', properties: { name: 'ETCH-01' }, classification: 1, provenance: [] }],
        edges: [],
      })
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
    fireEvent.change(screen.getByLabelText('질문'), { target: { value: '연결 관계를 보여줘' } })
    fireEvent.click(screen.getByRole('button', { name: 'GraphRAG 질의' }))

    await screen.findByText('ETCH-01은 검증된 반도체 장비 노드입니다.')
    await screen.findByText('1 nodes · 0 edges')
    await waitFor(() => expect(request).toHaveBeenCalledWith(
      '/knowledge/graphs/graph-1/releases/release-1/graphrag',
      expect.objectContaining({ method: 'POST' }),
    ))
    expect(request.mock.calls.some(([path]) => String(path).startsWith('/chat'))).toBe(false)
  })
})
