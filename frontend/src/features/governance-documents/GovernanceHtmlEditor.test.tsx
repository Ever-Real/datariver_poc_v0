import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { GovernanceHtmlEditor } from './GovernanceHtmlEditor'

describe('GovernanceHtmlEditor', () => {
  it('loads safe rich HTML and emits Tiptap HTML changes', async () => {
    const onHtmlChange = vi.fn()
    render(<GovernanceHtmlEditor
      initialHtml="<h2>운영 정책</h2><table><tbody><tr><td>보존 기간</td></tr></tbody></table>"
      disabled={false}
      onHtmlChange={onHtmlChange}
    />)

    const editor = await screen.findByRole('textbox', { name: '문서 본문' })
    expect(editor).toHaveTextContent('운영 정책')
    expect(editor.querySelector('table')).not.toBeNull()
    const blockStyle = screen.getByRole('combobox', { name: '문단 스타일' })
    expect(within(blockStyle).getAllByRole('option').map((option) => option.textContent)).toEqual(['본문', '제목 1', '제목 2'])
    fireEvent.change(blockStyle, { target: { value: 'heading-2' } })
    fireEvent.click(screen.getByRole('button', { name: '구분선' }))
    await waitFor(() => expect(onHtmlChange).toHaveBeenCalled())
    expect(onHtmlChange.mock.calls.at(-1)?.[0]).toContain('<hr>')
  })

  it('makes formatting commands unavailable in read-only mode', async () => {
    render(<GovernanceHtmlEditor initialHtml="<p>본문</p>" disabled onHtmlChange={vi.fn()} />)
    expect(await screen.findByRole('button', { name: '굵게' })).toBeDisabled()
    expect(screen.getByRole('textbox', { name: '문서 본문' })).toHaveAttribute('contenteditable', 'false')
  })
})
