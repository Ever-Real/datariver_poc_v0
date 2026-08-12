import { memo, useEffect, type ReactNode } from 'react'
import { Extension } from '@tiptap/core'
import { EditorContent, useEditor, type Editor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { TableKit } from '@tiptap/extension-table'
import {
  AlignCenter,
  AlignLeft,
  AlignRight,
  Bold,
  Code2,
  IndentDecrease,
  IndentIncrease,
  Italic,
  Link2,
  List,
  ListOrdered,
  Minus,
  Quote,
  Redo2,
  Strikethrough,
  Table2,
  UnderlineIcon,
  Undo2,
} from 'lucide-react'
import { safeGovernancePresentation } from './governancePresentationStyle'

const fontSizes = ['10px', '12px', '14px', '16px', '18px', '24px', '32px'] as const
const maximumIndentLevel = 6

const GovernanceBlockPresentation = Extension.create({
  name: 'governanceBlockPresentation',
  addGlobalAttributes() {
    return [{
      types: ['heading', 'paragraph'],
      attributes: {
        governancePresentation: {
          default: null,
          parseHTML: (element) => safeGovernancePresentation(
            element.getAttribute('data-governance-style') ?? element.getAttribute('style'),
          ) || null,
          renderHTML: (attributes) => {
            const presentation = safeGovernancePresentation(
              typeof attributes.governancePresentation === 'string'
                ? attributes.governancePresentation
                : '',
            )
            return presentation
              ? { 'data-governance-style': presentation, style: presentation }
              : {}
          },
        },
      },
    }]
  },
})

function presentationEntries(value: unknown): Map<string, string> {
  const presentation = safeGovernancePresentation(typeof value === 'string' ? value : '')
  return new Map(presentation.split(';').flatMap((declaration) => {
    const delimiter = declaration.indexOf(':')
    return delimiter > 0
      ? [[declaration.slice(0, delimiter), declaration.slice(delimiter + 1)] as const]
      : []
  }))
}

function activeBlockType(editor: Editor): 'heading' | 'paragraph' {
  return editor.isActive('heading') ? 'heading' : 'paragraph'
}

function activePresentation(editor: Editor): Map<string, string> {
  return presentationEntries(
    editor.getAttributes(activeBlockType(editor)).governancePresentation,
  )
}

function updatePresentation(
  editor: Editor,
  property: 'font-size' | 'padding-left' | 'text-align',
  value: string | null,
) {
  const entries = activePresentation(editor)
  if (value) entries.set(property, value)
  else entries.delete(property)
  const presentation = [...entries]
    .map(([name, candidate]) => `${name}:${candidate}`)
    .join(';')
  editor.chain().focus().updateAttributes(activeBlockType(editor), {
    governancePresentation: presentation || null,
  }).run()
}

function currentIndentLevel(editor: Editor): number {
  const padding = activePresentation(editor).get('padding-left') ?? ''
  const match = /^(\d+)em$/.exec(padding)
  if (!match) return 0
  return Math.min(maximumIndentLevel, Math.floor(Number(match[1]) / 2))
}

function changeIndent(editor: Editor, direction: 1 | -1) {
  const next = Math.max(0, Math.min(maximumIndentLevel, currentIndentLevel(editor) + direction))
  updatePresentation(editor, 'padding-left', next > 0 ? `${next * 2}em` : null)
}

function ToolbarButton({
  label,
  active = false,
  disabled = false,
  children,
  onClick,
}: {
  label: string
  active?: boolean
  disabled?: boolean
  children: ReactNode
  onClick: () => void
}) {
  return <button
    type="button"
    aria-label={label}
    title={label}
    aria-pressed={active || undefined}
    className={active ? 'active' : undefined}
    disabled={disabled}
    onMouseDown={(event) => event.preventDefault()}
    onClick={onClick}
  >{children}</button>
}

function setLink(editor: Editor) {
  const previous = editor.getAttributes('link').href as string | undefined
  const href = window.prompt('연결할 HTTPS 또는 상대 경로를 입력하세요.', previous ?? 'https://')
  if (href === null) return
  const normalized = href.trim()
  if (!normalized) {
    editor.chain().focus().extendMarkRange('link').unsetLink().run()
    return
  }
  editor.chain().focus().extendMarkRange('link').setLink({ href: normalized }).run()
}

export const GovernanceHtmlEditor = memo(function GovernanceHtmlEditor({
  initialHtml,
  disabled,
  onHtmlChange,
}: {
  initialHtml: string
  disabled: boolean
  onHtmlChange: (html: string) => void
}) {
  const editor = useEditor({
    immediatelyRender: false,
    shouldRerenderOnTransaction: true,
    editable: !disabled,
    content: initialHtml,
    extensions: [
      StarterKit.configure({
        link: { openOnClick: false, autolink: false, defaultProtocol: 'https' },
      }),
      GovernanceBlockPresentation,
      TableKit.configure({ table: { resizable: true } }),
    ],
    editorProps: {
      attributes: {
        class: 'governance-editor-surface',
        role: 'textbox',
        'aria-label': '문서 본문',
        'aria-multiline': 'true',
        'aria-readonly': String(disabled),
        spellcheck: 'true',
      },
    },
    onUpdate: ({ editor: current }) => onHtmlChange(current.getHTML()),
  }, [])

  useEffect(() => {
    editor?.setEditable(!disabled)
  }, [disabled, editor])

  if (!editor) return <div className="governance-editor-loading" role="status">문서 편집기를 준비하는 중입니다.</div>

  const commandDisabled = disabled || !editor.isEditable
  return <section className="governance-html-editor" aria-label="거버넌스 문서 HTML 편집기">
    <div className="governance-editor-toolbar" role="toolbar" aria-label="문서 서식">
      <div className="governance-editor-tool-group" aria-label="실행 취소">
        <ToolbarButton label="실행 취소" disabled={commandDisabled || !editor.can().chain().focus().undo().run()} onClick={() => editor.chain().focus().undo().run()}><Undo2 size={14} /></ToolbarButton>
        <ToolbarButton label="다시 실행" disabled={commandDisabled || !editor.can().chain().focus().redo().run()} onClick={() => editor.chain().focus().redo().run()}><Redo2 size={14} /></ToolbarButton>
      </div>
      <div className="governance-editor-tool-group governance-editor-block-style" aria-label="문단 스타일">
        <select
          aria-label="문단 스타일"
          title="문단 스타일"
          disabled={commandDisabled}
          value={editor.isActive('heading', { level: 1 }) ? 'heading-1' : editor.isActive('heading', { level: 2 }) ? 'heading-2' : 'paragraph'}
          onChange={(event) => {
            if (event.target.value === 'heading-1') editor.chain().focus().setHeading({ level: 1 }).run()
            else if (event.target.value === 'heading-2') editor.chain().focus().setHeading({ level: 2 }).run()
            else editor.chain().focus().setParagraph().run()
          }}
        >
          <option value="paragraph">본문</option>
          <option value="heading-1">제목 1</option>
          <option value="heading-2">제목 2</option>
        </select>
      </div>
      <div className="governance-editor-tool-group governance-editor-font-size" aria-label="글자 크기">
        <select
          aria-label="글자 크기"
          title="글자 크기"
          disabled={commandDisabled}
          value={activePresentation(editor).get('font-size') ?? 'default'}
          onChange={(event) => updatePresentation(
            editor,
            'font-size',
            event.target.value === 'default' ? null : event.target.value,
          )}
        >
          <option value="default">기본 크기</option>
          {fontSizes.map((fontSize) => <option key={fontSize} value={fontSize}>{fontSize}</option>)}
        </select>
      </div>
      <div className="governance-editor-tool-group" aria-label="문자 스타일">
        <ToolbarButton label="굵게" active={editor.isActive('bold')} disabled={commandDisabled} onClick={() => editor.chain().focus().toggleBold().run()}><Bold size={14} /></ToolbarButton>
        <ToolbarButton label="기울임" active={editor.isActive('italic')} disabled={commandDisabled} onClick={() => editor.chain().focus().toggleItalic().run()}><Italic size={14} /></ToolbarButton>
        <ToolbarButton label="밑줄" active={editor.isActive('underline')} disabled={commandDisabled} onClick={() => editor.chain().focus().toggleUnderline().run()}><UnderlineIcon size={14} /></ToolbarButton>
        <ToolbarButton label="취소선" active={editor.isActive('strike')} disabled={commandDisabled} onClick={() => editor.chain().focus().toggleStrike().run()}><Strikethrough size={14} /></ToolbarButton>
        <ToolbarButton label="인라인 코드" active={editor.isActive('code')} disabled={commandDisabled} onClick={() => editor.chain().focus().toggleCode().run()}><Code2 size={14} /></ToolbarButton>
        <ToolbarButton label="링크" active={editor.isActive('link')} disabled={commandDisabled} onClick={() => setLink(editor)}><Link2 size={14} /></ToolbarButton>
      </div>
      <div className="governance-editor-tool-group" aria-label="목록과 인용">
        <ToolbarButton label="글머리 기호 목록" active={editor.isActive('bulletList')} disabled={commandDisabled} onClick={() => editor.chain().focus().toggleBulletList().run()}><List size={14} /></ToolbarButton>
        <ToolbarButton label="번호 목록" active={editor.isActive('orderedList')} disabled={commandDisabled} onClick={() => editor.chain().focus().toggleOrderedList().run()}><ListOrdered size={14} /></ToolbarButton>
        <ToolbarButton label="인용문" active={editor.isActive('blockquote')} disabled={commandDisabled} onClick={() => editor.chain().focus().toggleBlockquote().run()}><Quote size={14} /></ToolbarButton>
        <ToolbarButton label="구분선" disabled={commandDisabled} onClick={() => editor.chain().focus().setHorizontalRule().run()}><Minus size={14} /></ToolbarButton>
        <ToolbarButton label="내어쓰기" disabled={commandDisabled || currentIndentLevel(editor) === 0} onClick={() => changeIndent(editor, -1)}><IndentDecrease size={14} /></ToolbarButton>
        <ToolbarButton label="들여쓰기" disabled={commandDisabled || currentIndentLevel(editor) >= maximumIndentLevel} onClick={() => changeIndent(editor, 1)}><IndentIncrease size={14} /></ToolbarButton>
      </div>
      <div className="governance-editor-tool-group" aria-label="정렬과 표">
        <ToolbarButton label="왼쪽 정렬" active={!activePresentation(editor).has('text-align') || activePresentation(editor).get('text-align') === 'left'} disabled={commandDisabled} onClick={() => updatePresentation(editor, 'text-align', null)}><AlignLeft size={14} /></ToolbarButton>
        <ToolbarButton label="가운데 정렬" active={activePresentation(editor).get('text-align') === 'center'} disabled={commandDisabled} onClick={() => updatePresentation(editor, 'text-align', 'center')}><AlignCenter size={14} /></ToolbarButton>
        <ToolbarButton label="오른쪽 정렬" active={activePresentation(editor).get('text-align') === 'right'} disabled={commandDisabled} onClick={() => updatePresentation(editor, 'text-align', 'right')}><AlignRight size={14} /></ToolbarButton>
        <ToolbarButton label="3열 표 삽입" disabled={commandDisabled} onClick={() => editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()}><Table2 size={14} /></ToolbarButton>
      </div>
      {editor.isActive('table') && <div className="governance-editor-tool-group governance-editor-table-tools" aria-label="표 편집">
        <ToolbarButton label="행 추가" disabled={commandDisabled} onClick={() => editor.chain().focus().addRowAfter().run()}>+행</ToolbarButton>
        <ToolbarButton label="열 추가" disabled={commandDisabled} onClick={() => editor.chain().focus().addColumnAfter().run()}>+열</ToolbarButton>
        <ToolbarButton label="행 삭제" disabled={commandDisabled} onClick={() => editor.chain().focus().deleteRow().run()}>−행</ToolbarButton>
        <ToolbarButton label="열 삭제" disabled={commandDisabled} onClick={() => editor.chain().focus().deleteColumn().run()}>−열</ToolbarButton>
        <ToolbarButton label="표 삭제" disabled={commandDisabled} onClick={() => editor.chain().focus().deleteTable().run()}>표 삭제</ToolbarButton>
      </div>}
    </div>
    <EditorContent className="governance-editor-content" editor={editor} />
  </section>
})
