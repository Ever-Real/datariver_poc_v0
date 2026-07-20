import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiClient } from '../../api/client'
import { KnowledgePage } from './KnowledgePage'

afterEach(() => vi.unstubAllGlobals())

describe('KnowledgePage', () => {
  it('creates a graph from the entered contract-bounded ontology rather than a fixed ontology', async () => {
    const postBodies: unknown[] = []
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      if (url.endsWith('/knowledge/graphs') && init?.method === 'POST') {
        if (typeof init.body !== 'string') throw new Error('Expected a JSON request body.')
        postBodies.push(JSON.parse(init.body))
        return Promise.resolve(json({
          id: 'graph-1', slug: 'factory-knowledge', name: 'Factory knowledge',
          graph_type: 'ANALYTIC_PRODUCT', classification: 'CONFIDENTIAL', status: 'DRAFT', version: 1,
        }, 201))
      }
      if (url.endsWith('/knowledge/graphs')) return Promise.resolve(json([]))
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const onNavigate = vi.fn()
    render(<KnowledgePage client={new ApiClient('/api/v1', () => 'token', () => 'workspace-one')} onNavigate={onNavigate} />)

    await screen.findByRole('table', { name: '지식 에셋 목록' })
    fireEvent.click(screen.getByRole('button', { name: /에셋 추가/ }))
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Factory knowledge' } })
    fireEvent.change(screen.getByLabelText('Slug'), { target: { value: 'factory-knowledge' } })
    fireEvent.change(screen.getByLabelText('Domain · Graph type'), { target: { value: 'ANALYTIC_PRODUCT' } })
    fireEvent.change(screen.getByLabelText('Security classification'), { target: { value: 'CONFIDENTIAL' } })
    fireEvent.change(screen.getByLabelText('Entity types · 쉼표 구분'), { target: { value: 'Plant, Tool, Tool' } })
    fireEvent.change(screen.getByLabelText('Edge types · 쉼표 구분'), { target: { value: 'USES, PRODUCES' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(postBodies).toEqual([{
      slug: 'factory-knowledge', name: 'Factory knowledge', graph_type: 'ANALYTIC_PRODUCT', classification: 'CONFIDENTIAL',
      ontology: { entity_types: ['Plant', 'Tool'], edge_types: ['USES', 'PRODUCES'] },
    }]))
    fireEvent.click(screen.getByRole('button', { name: /지식 챗/ }))
    expect(onNavigate).toHaveBeenCalledWith('knowledge-chat')
  })
})

function json(body: object | object[], status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}
