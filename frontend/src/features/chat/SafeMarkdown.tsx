import { Fragment, useState, type ReactNode } from 'react'

const MAX_MARKDOWN_CHARACTERS = 100_000
const MAX_TABLE_COLUMNS = 20
const MAX_TABLE_ROWS = 100

function inlineMarkdown(value: string, keyPrefix: string): ReactNode[] {
  const parts: ReactNode[] = []
  const token = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\[[^\]\n]+\]\([^\s)\n]+\))/g
  let cursor = 0
  let match: RegExpExecArray | null
  let tokenIndex = 0

  while ((match = token.exec(value)) !== null) {
    if (match.index > cursor) parts.push(value.slice(cursor, match.index))
    const current = match[0]
    const key = `${keyPrefix}-${tokenIndex}`
    if (current.startsWith('`')) {
      parts.push(<code key={key}>{current.slice(1, -1)}</code>)
    } else if (current.startsWith('**')) {
      parts.push(<strong key={key}>{current.slice(2, -2)}</strong>)
    } else {
      const separator = current.lastIndexOf('](')
      const label = current.slice(1, separator)
      parts.push(
        <Fragment key={key}>
          {label}<span aria-label="답변 링크 비활성화"> (링크 비활성화됨)</span>
        </Fragment>,
      )
    }
    cursor = match.index + current.length
    tokenIndex += 1
  }
  if (cursor < value.length) parts.push(value.slice(cursor))
  return parts
}

function tableCells(line: string): string[] {
  const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '')
  return trimmed.split('|').map((cell) => cell.trim()).slice(0, MAX_TABLE_COLUMNS)
}

function isTableDivider(line: string): boolean {
  const cells = tableCells(line)
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell))
}

function tableClipboardCell(value: string): string {
  const plainText = value
    .replace(/`([^`\n]+)`/g, '$1')
    .replace(/\*\*([^*\n]+)\*\*/g, '$1')
    .replace(/\[([^\]\n]+)\]\([^\s)\n]+\)/g, '$1')
    .replace(/[\t\r\n]+/g, ' ')

  // TSV is intentionally used so Excel can paste cells directly. Prefix formulas
  // to prevent an answer-provided cell from becoming executable spreadsheet content.
  return /^[=+\-@]/.test(plainText) ? `'${plainText}` : plainText
}

function tableClipboardText(headers: string[], rows: string[][]): string {
  return [headers, ...rows]
    .map((row) => headers.map((_, index) => tableClipboardCell(row[index] ?? '')).join('\t'))
    .join('\n')
}

function MarkdownTable({
  headers,
  rows,
  truncated,
}: {
  headers: string[]
  rows: string[][]
  truncated: boolean
}) {
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle')

  const copyTable = async () => {
    try {
      await navigator.clipboard.writeText(tableClipboardText(headers, rows))
      setCopyState('copied')
    } catch {
      setCopyState('failed')
    }
  }

  const copyLabel = copyState === 'copied'
    ? '표 복사됨'
    : copyState === 'failed'
      ? '표 복사 실패'
      : '표 복사'

  return (
    <div className="chat-markdown-table-frame">
      <button
        aria-label={copyLabel}
        className="chat-markdown-table-copy"
        onClick={(event) => {
          event.stopPropagation()
          void copyTable()
        }}
        onKeyDown={(event) => event.stopPropagation()}
        type="button"
      >
        {copyLabel}
      </button>
      <div className="chat-markdown-table-scroll">
        <table className="chat-markdown-table">
          <thead>
            <tr>{headers.map((cell, cellIndex) => <th key={`header-${cellIndex}`}>{inlineMarkdown(cell, `header-${cellIndex}`)}</th>)}</tr>
          </thead>
          <tbody>{rows.map((row, rowIndex) => (
            <tr key={`row-${rowIndex}`}>{headers.map((_, cellIndex) => <td key={`cell-${rowIndex}-${cellIndex}`}>{inlineMarkdown(row[cellIndex] ?? '', `cell-${rowIndex}-${cellIndex}`)}</td>)}</tr>
          ))}</tbody>
        </table>
      </div>
      {truncated && <p role="status">표는 최대 {MAX_TABLE_ROWS}개 행까지만 표시됩니다.</p>}
    </div>
  )
}

function isBlockStart(lines: string[], index: number): boolean {
  const line = lines[index] ?? ''
  const next = lines[index + 1] ?? ''
  return (
    !line.trim()
    || /^```/.test(line.trim())
    || /^#{1,6}\s+/.test(line)
    || /^>\s?/.test(line)
    || /^[-*+]\s+/.test(line)
    || /^\d+\.\s+/.test(line)
    || /^([-*_])\1{2,}\s*$/.test(line.trim())
    || (line.includes('|') && isTableDivider(next))
  )
}

export function SafeMarkdown({ value }: { value: string }) {
  const truncated = value.length > MAX_MARKDOWN_CHARACTERS
  const source = value.slice(0, MAX_MARKDOWN_CHARACTERS).replace(/\r\n?/g, '\n')
  const lines = source.split('\n')
  const blocks: ReactNode[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index] ?? ''
    if (!line.trim()) {
      index += 1
      continue
    }

    if (line.trim().startsWith('```')) {
      const language = line.trim().slice(3).trim()
      const content: string[] = []
      index += 1
      while (index < lines.length && !(lines[index] ?? '').trim().startsWith('```')) {
        content.push(lines[index] ?? '')
        index += 1
      }
      if (index < lines.length) index += 1
      blocks.push(<pre key={`code-${index}`}><code data-language={language || undefined}>{content.join('\n')}</code></pre>)
      continue
    }

    const heading = /^(#{1,6})\s+(.+)$/.exec(line)
    if (heading) {
      const level = heading[1]?.length ?? 1
      const content = inlineMarkdown(heading[2] ?? '', `heading-${index}`)
      if (level === 1) blocks.push(<h1 key={`heading-${index}`}>{content}</h1>)
      else if (level === 2) blocks.push(<h2 key={`heading-${index}`}>{content}</h2>)
      else if (level === 3) blocks.push(<h3 key={`heading-${index}`}>{content}</h3>)
      else if (level === 4) blocks.push(<h4 key={`heading-${index}`}>{content}</h4>)
      else if (level === 5) blocks.push(<h5 key={`heading-${index}`}>{content}</h5>)
      else blocks.push(<h6 key={`heading-${index}`}>{content}</h6>)
      index += 1
      continue
    }

    if (line.includes('|') && isTableDivider(lines[index + 1] ?? '')) {
      const headers = tableCells(line)
      const rows: string[][] = []
      index += 2
      while (index < lines.length && (lines[index] ?? '').includes('|') && rows.length < MAX_TABLE_ROWS) {
        rows.push(tableCells(lines[index] ?? ''))
        index += 1
      }
      const tableWasTruncated = index < lines.length && (lines[index] ?? '').includes('|')
      while (index < lines.length && (lines[index] ?? '').includes('|')) index += 1
      blocks.push(
        <MarkdownTable
          headers={headers}
          key={`table-${index}`}
          rows={rows}
          truncated={tableWasTruncated}
        />,
      )
      continue
    }

    if (/^[-*+]\s+/.test(line)) {
      const items: string[] = []
      while (index < lines.length && /^[-*+]\s+/.test(lines[index] ?? '')) {
        items.push((lines[index] ?? '').replace(/^[-*+]\s+/, ''))
        index += 1
      }
      blocks.push(<ul key={`list-${index}`}>{items.map((item, itemIndex) => <li key={`item-${itemIndex}`}>{inlineMarkdown(item, `item-${itemIndex}`)}</li>)}</ul>)
      continue
    }

    if (/^\d+\.\s+/.test(line)) {
      const items: string[] = []
      while (index < lines.length && /^\d+\.\s+/.test(lines[index] ?? '')) {
        items.push((lines[index] ?? '').replace(/^\d+\.\s+/, ''))
        index += 1
      }
      blocks.push(<ol key={`ordered-${index}`}>{items.map((item, itemIndex) => <li key={`ordered-item-${itemIndex}`}>{inlineMarkdown(item, `ordered-item-${itemIndex}`)}</li>)}</ol>)
      continue
    }

    if (/^>\s?/.test(line)) {
      const quote: string[] = []
      while (index < lines.length && /^>\s?/.test(lines[index] ?? '')) {
        quote.push((lines[index] ?? '').replace(/^>\s?/, ''))
        index += 1
      }
      blocks.push(<blockquote key={`quote-${index}`}>{inlineMarkdown(quote.join(' '), `quote-${index}`)}</blockquote>)
      continue
    }

    if (/^([-*_])\1{2,}\s*$/.test(line.trim())) {
      blocks.push(<hr key={`rule-${index}`} />)
      index += 1
      continue
    }

    const paragraph: string[] = [line]
    index += 1
    while (index < lines.length && !isBlockStart(lines, index)) {
      paragraph.push(lines[index] ?? '')
      index += 1
    }
    blocks.push(<p key={`paragraph-${index}`}>{paragraph.flatMap((item, lineIndex) => [
      ...(lineIndex > 0 ? [<br key={`break-${lineIndex}`} />] : []),
      ...inlineMarkdown(item, `paragraph-${index}-${lineIndex}`),
    ])}</p>)
  }

  return (
    <div className="chat-markdown">
      {blocks}
      {truncated && <p role="status">안전한 표시 한도를 초과한 답변의 뒷부분은 표시하지 않습니다.</p>}
    </div>
  )
}
