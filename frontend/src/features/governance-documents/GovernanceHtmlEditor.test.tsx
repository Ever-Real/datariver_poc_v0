import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Editor } from '@tiptap/react'
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
    expect(within(blockStyle).getAllByRole('option').map((option) => option.textContent)).toEqual(['본문', '제목 1', '제목 2', '제목 3'])
    fireEvent.change(blockStyle, { target: { value: 'heading-2' } })
    fireEvent.click(screen.getByRole('button', { name: '구분선' }))
    await waitFor(() => expect(onHtmlChange).toHaveBeenCalled())
    expect(onHtmlChange.mock.calls.at(-1)?.[0]).toContain('<hr>')
  })

  it('persists font size, indentation, and alignment through the safe presentation token', async () => {
    const onHtmlChange = vi.fn()
    render(<GovernanceHtmlEditor
      initialHtml="<p>정책 본문</p>"
      disabled={false}
      onHtmlChange={onHtmlChange}
    />)

    const editor = await screen.findByRole('textbox', { name: '문서 본문' })
    fireEvent.focus(editor)
    fireEvent.change(screen.getByRole('combobox', { name: '글자 크기' }), {
      target: { value: '18px' },
    })
    fireEvent.click(screen.getByRole('button', { name: '들여쓰기' }))
    fireEvent.click(screen.getByRole('button', { name: '가운데 정렬' }))

    await waitFor(() => {
      expect(onHtmlChange.mock.calls.at(-1)?.[0]).toContain(
        'data-governance-style="font-size:18px;padding-left:2em;text-align:center"',
      )
    })
    expect(editor.querySelector('p')).toHaveAttribute(
      'data-governance-style',
      'font-size:18px;padding-left:2em;text-align:center',
    )

    fireEvent.click(screen.getByRole('button', { name: '내어쓰기' }))
    await waitFor(() => {
      expect(onHtmlChange.mock.calls.at(-1)?.[0]).toContain(
        'data-governance-style="font-size:18px;text-align:center"',
      )
    })
  })

  it('restores saved presentation controls when an existing document is reopened', async () => {
    render(<GovernanceHtmlEditor
      initialHtml={'<p data-governance-style="font-size:16px;padding-left:4em;text-align:right">본문</p>'}
      disabled={false}
      onHtmlChange={vi.fn()}
    />)

    expect(await screen.findByRole('combobox', { name: '글자 크기' })).toHaveValue('16px')
    expect(screen.getByRole('button', { name: '오른쪽 정렬' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('makes formatting commands unavailable in read-only mode', async () => {
    render(<GovernanceHtmlEditor initialHtml="<p>본문</p>" disabled onHtmlChange={vi.fn()} />)
    expect(await screen.findByRole('button', { name: '굵게' })).toBeDisabled()
    expect(screen.getByRole('textbox', { name: '문서 본문' })).toHaveAttribute('contenteditable', 'false')
  })

  it('executes the required formatting commands against the document model', async () => {
    const onHtmlChange = vi.fn()
    let tiptap: Editor | undefined
    render(<GovernanceHtmlEditor
      initialHtml="<p>정책 본문</p>"
      disabled={false}
      onHtmlChange={onHtmlChange}
      onEditorReady={(editor) => { tiptap = editor }}
    />)
    await screen.findByRole('textbox', { name: '문서 본문' })
    await waitFor(() => expect(tiptap).toBeDefined())

    const selectDocumentText = () => tiptap?.commands.setTextSelection({ from: 1, to: Math.max(1, tiptap.state.doc.content.size - 1) })
    const reset = (html = '<p>정책 본문</p>') => {
      tiptap?.commands.setContent(html)
      selectDocumentText()
    }
    const click = (name: string) => fireEvent.click(screen.getByRole('button', { name }))

    reset(); click('굵게'); expect(tiptap?.getHTML()).toContain('<strong>정책 본문</strong>')
    reset(); click('기울임'); expect(tiptap?.getHTML()).toContain('<em>정책 본문</em>')
    reset(); click('밑줄'); expect(tiptap?.getHTML()).toContain('<u>정책 본문</u>')
    reset(); fireEvent.change(screen.getByRole('combobox', { name: '문단 스타일' }), { target: { value: 'heading-3' } }); expect(tiptap?.getHTML()).toContain('<h3>정책 본문</h3>')
    reset(); click('글머리 기호 목록'); expect(tiptap?.getHTML()).toContain('<ul>')
    reset(); click('번호 목록'); expect(tiptap?.getHTML()).toContain('<ol>')
    reset(); click('인용문'); expect(tiptap?.getHTML()).toContain('<blockquote>')
    reset(); click('코드 블록'); expect(tiptap?.getHTML()).toContain('<pre><code>정책 본문</code></pre>')

    reset('<p><strong>정책 본문</strong></p>'); click('서식 지우기'); expect(tiptap?.getHTML()).toBe('<p>정책 본문</p>')
    tiptap?.commands.setContent('<p>첫 문단</p>')
    tiptap?.commands.insertContent('<p>둘째 문단</p>')
    const beforeUndo = tiptap?.getHTML()
    click('실행 취소'); expect(tiptap?.getHTML()).not.toBe(beforeUndo)
    click('다시 실행'); expect(tiptap?.getHTML()).toBe(beforeUndo)
  })

  it('provides accessible focus tooltips and rejects unsafe link schemes', async () => {
    const prompt = vi.spyOn(window, 'prompt').mockReturnValue('javascript:alert(1)')
    let tiptap: Editor | undefined
    render(<GovernanceHtmlEditor
      initialHtml="<p>정책 링크</p>"
      disabled={false}
      onHtmlChange={vi.fn()}
      onEditorReady={(editor) => { tiptap = editor }}
    />)
    await waitFor(() => expect(tiptap).toBeDefined())
    tiptap?.commands.setTextSelection({ from: 1, to: 6 })

    const bold = screen.getByRole('button', { name: '굵게' })
    fireEvent.focus(bold)
    const tooltip = screen.getByRole('tooltip', { name: '굵게 (Ctrl/Cmd+B)' })
    expect(bold).toHaveAttribute('aria-describedby', tooltip.id)

    fireEvent.click(screen.getByRole('button', { name: '링크 추가 또는 편집' }))
    expect(prompt).toHaveBeenCalledOnce()
    expect(tiptap?.getHTML()).not.toContain('javascript:')
    expect(tiptap?.getHTML()).not.toContain('<a')
  })

  it('sanitizes pasted HTML before it enters the editor document', async () => {
    let tiptap: Editor | undefined
    render(<GovernanceHtmlEditor
      initialHtml="<p>기존 본문</p>"
      disabled={false}
      onHtmlChange={vi.fn()}
      onEditorReady={(editor) => { tiptap = editor }}
    />)
    const surface = await screen.findByRole('textbox', { name: '문서 본문' })
    await waitFor(() => expect(tiptap).toBeDefined())

    fireEvent.paste(surface, {
      clipboardData: {
        getData: (format: string) => format === 'text/html'
          ? '<p style="font-size:18px;text-align:center;position:fixed">붙여넣기<script>alert(1)</script></p>'
          : format === 'text/plain' ? '붙여넣기' : '',
        types: ['text/html', 'text/plain'],
      },
    })

    await waitFor(() => expect(tiptap?.getHTML()).toContain('붙여넣기'))
    expect(tiptap?.getHTML()).not.toMatch(/script|position|style=/i)
  })
})
