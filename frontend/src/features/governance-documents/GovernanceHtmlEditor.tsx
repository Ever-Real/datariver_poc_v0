import { memo, useEffect, type ReactNode } from 'react'
import { EditorContent, useEditor, type Editor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import TextAlign from '@tiptap/extension-text-align'
import { TableKit } from '@tiptap/extension-table'
import {
  AlignCenter,
  AlignLeft,
  AlignRight,
  Bold,
  Code2,
  Heading1,
  Heading2,
  Italic,
  Link2,
  List,
  ListOrdered,
  Minus,
  Pilcrow,
  Quote,
  Redo2,
  Strikethrough,
  Table2,
  UnderlineIcon,
  Undo2,
} from 'lucide-react'

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
      TextAlign.configure({ types: ['heading', 'paragraph'] }),
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
      <div className="governance-editor-tool-group" aria-label="문단 스타일">
        <ToolbarButton label="본문 문단" active={editor.isActive('paragraph')} disabled={commandDisabled} onClick={() => editor.chain().focus().setParagraph().run()}><Pilcrow size={14} /></ToolbarButton>
        <ToolbarButton label="제목 1" active={editor.isActive('heading', { level: 1 })} disabled={commandDisabled} onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()}><Heading1 size={14} /></ToolbarButton>
        <ToolbarButton label="제목 2" active={editor.isActive('heading', { level: 2 })} disabled={commandDisabled} onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}><Heading2 size={14} /></ToolbarButton>
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
      </div>
      <div className="governance-editor-tool-group" aria-label="정렬과 표">
        <ToolbarButton label="왼쪽 정렬" active={editor.isActive({ textAlign: 'left' })} disabled={commandDisabled} onClick={() => editor.chain().focus().setTextAlign('left').run()}><AlignLeft size={14} /></ToolbarButton>
        <ToolbarButton label="가운데 정렬" active={editor.isActive({ textAlign: 'center' })} disabled={commandDisabled} onClick={() => editor.chain().focus().setTextAlign('center').run()}><AlignCenter size={14} /></ToolbarButton>
        <ToolbarButton label="오른쪽 정렬" active={editor.isActive({ textAlign: 'right' })} disabled={commandDisabled} onClick={() => editor.chain().focus().setTextAlign('right').run()}><AlignRight size={14} /></ToolbarButton>
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
