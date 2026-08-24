import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiClient } from '../../api/client'
import { KnowledgePage } from './KnowledgePage'

afterEach(() => vi.unstubAllGlobals())

describe('KnowledgePage', () => {
  it('shows the consolidated Knowledge workspaces and routes creation to full-screen Studio', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      if (url.endsWith('/knowledge/graphs')) return Promise.resolve(json([]))
      if (url.endsWith('/poc-api/knowledge/managed-assets')) {
        return Promise.resolve(json({ items: [], next_cursor: null, limit: 25 }))
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const onNavigate = vi.fn()
    render(
      <KnowledgePage
        client={new ApiClient('/api/v1', () => 'token', () => 'workspace-one')}
        onNavigate={onNavigate}
      />,
    )

    await screen.findByRole('table', { name: '지식 에셋 목록' })
    expect(screen.queryByRole('button', { name: /데이터 적재/ })).not.toBeInTheDocument()
    const registryMenu = screen.getByRole('button', { name: /조회 및 생성/ })
    const informationMenu = screen.getByRole('button', { name: /정보 관리/ })
    expect(registryMenu).not.toHaveClass('ml-5')
    expect(informationMenu).not.toHaveClass('ml-5')
    expect(screen.queryByRole('button', { name: /인스턴스 관리/ })).not.toBeInTheDocument()

    fireEvent.click(screen.getAllByRole('button', { name: /^일반 에셋 추가$/ })[0]!)
    expect(onNavigate).toHaveBeenCalledWith('knowledge-studio')

    fireEvent.click(screen.getByRole('button', { name: /Chat Test/ }))
    expect(onNavigate).toHaveBeenCalledWith('knowledge-chat')
    fireEvent.click(informationMenu)
    expect(onNavigate).toHaveBeenCalledWith('knowledge-instances')
  })
})

function json(body: object | object[], status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}
