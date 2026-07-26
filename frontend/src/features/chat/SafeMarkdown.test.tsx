import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SafeMarkdown } from './SafeMarkdown'

describe('SafeMarkdown', () => {
  it('renders bounded Markdown tables and common text formatting', () => {
    render(<SafeMarkdown value={[
      '## 검색 결과',
      '',
      '| 순위 | 테이블 |',
      '| ---: | --- |',
      '| 1 | **orders** |',
      '| 2 | `customers` |',
      '',
      '- 권한 확인',
      '- 인용 검증',
    ].join('\n')} />)

    expect(screen.getByRole('heading', { name: '검색 결과' })).toBeInTheDocument()
    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: '순위' })).toBeInTheDocument()
    expect(screen.getByText('orders').tagName).toBe('STRONG')
    expect(screen.getByText('customers').tagName).toBe('CODE')
    expect(screen.getByText('권한 확인')).toBeInTheDocument()
  })

  it('never interprets raw HTML or activates answer-provided links', () => {
    const { container } = render(<SafeMarkdown value={[
      '<script>globalThis.compromised = true</script>',
      '<img src=x onerror=alert(1)>',
      '[실행](javascript:alert(1))',
      '[안전한 문서](https://catalog.example.test/docs)',
    ].join('\n')} />)

    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('img')).toBeNull()
    expect(screen.getByText(/<script>globalThis\.compromised/)).toBeInTheDocument()
    expect(container.querySelector('a')).toBeNull()
    expect(container).toHaveTextContent('실행')
    expect(screen.getAllByLabelText('답변 링크 비활성화')).toHaveLength(2)
    expect(container).toHaveTextContent('안전한 문서')
  })
})
