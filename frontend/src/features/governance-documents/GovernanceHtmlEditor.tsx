import { memo, useCallback, useRef } from 'react'
import { safeNodes } from './SafeGovernanceHtml'

export const GovernanceHtmlEditor = memo(function GovernanceHtmlEditor({
  initialHtml,
  disabled,
  onHtmlChange,
}: {
  initialHtml: string
  disabled: boolean
  onHtmlChange: (html: string) => void
}) {
  const editor = useRef<HTMLDivElement>(null)
  const emit = useCallback(() => {
    onHtmlChange(editor.current?.innerHTML ?? '')
  }, [onHtmlChange])
  const command = (name: string, value?: string) => {
    editor.current?.focus()
    document.execCommand(name, false, value)
    emit()
  }
  return <section className="governance-html-editor" aria-label="거버넌스 문서 HTML 편집기">
    <div className="governance-editor-toolbar" role="toolbar" aria-label="문서 서식">
      <button type="button" aria-label="굵게" disabled={disabled} onMouseDown={(event) => event.preventDefault()} onClick={() => command('bold')}>B</button>
      <button type="button" aria-label="기울임" disabled={disabled} onMouseDown={(event) => event.preventDefault()} onClick={() => command('italic')}><em>I</em></button>
      <button type="button" aria-label="제목 2" disabled={disabled} onMouseDown={(event) => event.preventDefault()} onClick={() => command('formatBlock', 'h2')}>H2</button>
      <button type="button" aria-label="본문 문단" disabled={disabled} onMouseDown={(event) => event.preventDefault()} onClick={() => command('formatBlock', 'p')}>P</button>
      <button type="button" aria-label="글머리 기호 목록" disabled={disabled} onMouseDown={(event) => event.preventDefault()} onClick={() => command('insertUnorderedList')}>• 목록</button>
      <button type="button" aria-label="번호 목록" disabled={disabled} onMouseDown={(event) => event.preventDefault()} onClick={() => command('insertOrderedList')}>1. 목록</button>
    </div>
    <div
      ref={editor}
      className="governance-editor-surface"
      contentEditable={!disabled}
      suppressContentEditableWarning
      role="textbox"
      aria-label="문서 본문"
      aria-multiline="true"
      aria-readonly={disabled}
      spellCheck
      onInput={emit}
      onBlur={emit}
    >
      {safeNodes(initialHtml)}
    </div>
  </section>
})
