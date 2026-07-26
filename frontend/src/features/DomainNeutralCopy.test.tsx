import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient } from '../api/client'
import { ChatPage } from './chat/ChatPage'
import { KnowledgeIngestionStudio } from './knowledge/KnowledgeIngestionStudio'

function clientReturningEmptyCollections() {
  return {
    request: vi.fn(() => Promise.resolve([])),
  } as unknown as ApiClient
}

describe('domain-neutral product copy', () => {
  it('uses general data-catalog questions instead of semiconductor defaults', () => {
    const chat = render(<ChatPage client={clientReturningEmptyCollections()} />)

    expect(
      screen.getByPlaceholderText('예: 고객 주문 데이터는 어떤 테이블에 있나요?'),
    ).toBeInTheDocument()
    expect(screen.queryByText(/wafer|semiconductor|반도체|수율/i)).not.toBeInTheDocument()

    chat.unmount()
    render(<KnowledgeIngestionStudio client={clientReturningEmptyCollections()} />)

    expect(
      screen.getByPlaceholderText(
        '예: 고객, 주문, 상품 간 관계를 중심으로 노드를 추출해 주세요.',
      ),
    ).toBeInTheDocument()
    expect(screen.queryByText(/wafer|semiconductor|반도체|수율/i)).not.toBeInTheDocument()
  })
})
