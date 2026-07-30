import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiClient } from '../../api/client'
import { KnowledgePage } from './KnowledgePage'

afterEach(() => vi.unstubAllGlobals())

describe('KnowledgePage', () => {
  it('shows only Registry and Knowledge Chat and routes creation to full-screen Studio', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      if (url.endsWith('/knowledge/graphs')) return Promise.resolve(json([]))
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
    const registryMenu = screen.getByRole('button', { name: /지식 레지스트리/ })
    const instanceMenu = screen.getByRole('button', {
      name: /지식 자산 인스턴스 관리/,
    })
    expect(registryMenu).not.toHaveClass('ml-5')
    expect(instanceMenu).not.toHaveClass('ml-5')

    fireEvent.click(screen.getByRole('button', { name: /에셋 추가/ }))
    expect(onNavigate).toHaveBeenCalledWith('knowledge-studio')

    fireEvent.click(screen.getByRole('button', { name: /지식 챗/ }))
    expect(onNavigate).toHaveBeenCalledWith('knowledge-chat')
  })
})

function json(body: object | object[], status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}
