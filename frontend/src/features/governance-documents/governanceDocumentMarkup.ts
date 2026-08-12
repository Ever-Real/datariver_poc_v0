const MAXIMUM_MARKUP_CHARACTERS = 1_000_000
const MAXIMUM_TABLE_COLUMNS = 20
const MAXIMUM_TABLE_ROWS = 200

const allowedElements = new Set([
  'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'strong', 'em', 'u', 's',
  'ul', 'ol', 'li', 'blockquote', 'code', 'pre', 'hr', 'br', 'table',
  'thead', 'tbody', 'tfoot', 'tr', 'th', 'td', 'a',
])

const suppressedElements = new Set([
  'applet', 'area', 'script', 'style', 'iframe', 'object', 'embed', 'details',
  'dialog', 'fieldset', 'form', 'frame', 'frameset', 'head', 'input', 'button',
  'legend', 'map', 'noframes', 'noscript', 'textarea', 'select', 'optgroup',
  'option', 'picture', 'plaintext', 'source', 'summary', 'svg', 'math', 'meta',
  'base', 'link', 'img', 'template', 'track', 'video', 'audio', 'canvas', 'xmp',
])

export interface GovernanceMarkupImport {
  format: 'HTML' | 'MARKDOWN'
  html: string
}

export async function governanceMarkupFromFile(file: File): Promise<GovernanceMarkupImport> {
  const name = file.name.toLocaleLowerCase()
  const source = (await file.text()).slice(0, MAXIMUM_MARKUP_CHARACTERS)
  if (name.endsWith('.html') || name.endsWith('.htm')) {
    return { format: 'HTML', html: sanitizeGovernanceHtml(source) }
  }
  if (name.endsWith('.md') || file.type === 'text/markdown') {
    return { format: 'MARKDOWN', html: markdownToGovernanceHtml(source) }
  }
  throw new Error('HTML 또는 Markdown 파일만 편집기에서 미리 볼 수 있습니다.')
}

export function sanitizeGovernanceHtml(value: string): string {
  if (typeof DOMParser === 'undefined') return ''
  const parsed = new DOMParser().parseFromString(
    value.slice(0, MAXIMUM_MARKUP_CHARACTERS),
    'text/html',
  )
  const output = parsed.implementation.createHTMLDocument('')
  const container = output.createElement('div')
  for (const child of Array.from(parsed.body.childNodes)) {
    const sanitized = sanitizeNode(child, output)
    if (sanitized) container.append(sanitized)
  }
  return container.innerHTML || '<p></p>'
}

export function markdownToGovernanceHtml(value: string): string {
  const lines = value
    .slice(0, MAXIMUM_MARKUP_CHARACTERS)
    .replace(/\r\n?/g, '\n')
    .split('\n')
  const blocks: string[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index] ?? ''
    if (!line.trim()) {
      index += 1
      continue
    }
    if (line.trim().startsWith('```')) {
      const content: string[] = []
      index += 1
      while (index < lines.length && !(lines[index] ?? '').trim().startsWith('```')) {
        content.push(lines[index] ?? '')
        index += 1
      }
      if (index < lines.length) index += 1
      blocks.push(`<pre><code>${escapeHtml(content.join('\n'))}</code></pre>`)
      continue
    }
    const heading = /^(#{1,6})\s+(.+)$/.exec(line)
    if (heading) {
      const level = heading[1]?.length ?? 1
      blocks.push(`<h${level}>${inlineMarkdown(heading[2] ?? '')}</h${level}>`)
      index += 1
      continue
    }
    if (line.includes('|') && isTableDivider(lines[index + 1] ?? '')) {
      const headers = tableCells(line)
      const rows: string[][] = []
      index += 2
      while (index < lines.length && (lines[index] ?? '').includes('|') && rows.length < MAXIMUM_TABLE_ROWS) {
        rows.push(tableCells(lines[index] ?? ''))
        index += 1
      }
      while (index < lines.length && (lines[index] ?? '').includes('|')) index += 1
      blocks.push(`<table><thead><tr>${headers.map((cell) => `<th>${inlineMarkdown(cell)}</th>`).join('')}</tr></thead><tbody>${rows.map((row) => `<tr>${headers.map((_, cellIndex) => `<td>${inlineMarkdown(row[cellIndex] ?? '')}</td>`).join('')}</tr>`).join('')}</tbody></table>`)
      continue
    }
    if (/^[-*+]\s+/.test(line)) {
      const items: string[] = []
      while (index < lines.length && /^[-*+]\s+/.test(lines[index] ?? '')) {
        items.push((lines[index] ?? '').replace(/^[-*+]\s+/, ''))
        index += 1
      }
      blocks.push(`<ul>${items.map((item) => `<li>${inlineMarkdown(item)}</li>`).join('')}</ul>`)
      continue
    }
    if (/^\d+\.\s+/.test(line)) {
      const items: string[] = []
      while (index < lines.length && /^\d+\.\s+/.test(lines[index] ?? '')) {
        items.push((lines[index] ?? '').replace(/^\d+\.\s+/, ''))
        index += 1
      }
      blocks.push(`<ol>${items.map((item) => `<li>${inlineMarkdown(item)}</li>`).join('')}</ol>`)
      continue
    }
    if (/^>\s?/.test(line)) {
      const quote: string[] = []
      while (index < lines.length && /^>\s?/.test(lines[index] ?? '')) {
        quote.push((lines[index] ?? '').replace(/^>\s?/, ''))
        index += 1
      }
      blocks.push(`<blockquote>${inlineMarkdown(quote.join(' '))}</blockquote>`)
      continue
    }
    if (/^([-*_])\1{2,}\s*$/.test(line.trim())) {
      blocks.push('<hr>')
      index += 1
      continue
    }
    const paragraph = [line]
    index += 1
    while (index < lines.length && !isBlockStart(lines, index)) {
      paragraph.push(lines[index] ?? '')
      index += 1
    }
    blocks.push(`<p>${paragraph.map(inlineMarkdown).join('<br>')}</p>`)
  }
  return sanitizeGovernanceHtml(blocks.join(''))
}

function sanitizeNode(node: Node, output: Document): Node | undefined {
  if (node.nodeType === Node.TEXT_NODE) return output.createTextNode(node.textContent ?? '')
  if (!(node instanceof HTMLElement)) return undefined
  const tag = node.tagName.toLocaleLowerCase()
  if (suppressedElements.has(tag)) return undefined
  const children = Array.from(node.childNodes)
    .map((child) => sanitizeNode(child, output))
    .filter((child): child is Node => Boolean(child))
  if (!allowedElements.has(tag)) {
    const fragment = output.createDocumentFragment()
    fragment.append(...children)
    return fragment
  }
  if (tag === 'a') {
    const href = safeHref(node.getAttribute('href'))
    if (!href) {
      const fragment = output.createDocumentFragment()
      fragment.append(...children)
      return fragment
    }
    const anchor = output.createElement('a')
    anchor.setAttribute('href', href)
    anchor.setAttribute('rel', 'noopener noreferrer')
    if (/^https?:\/\//i.test(href)) anchor.setAttribute('target', '_blank')
    anchor.append(...children)
    return anchor
  }
  const element = output.createElement(tag)
  if (tag === 'th' || tag === 'td') {
    const colSpan = boundedSpan(node.getAttribute('colspan'))
    const rowSpan = boundedSpan(node.getAttribute('rowspan'))
    if (colSpan) element.setAttribute('colspan', String(colSpan))
    if (rowSpan) element.setAttribute('rowspan', String(rowSpan))
  }
  if (tag !== 'br' && tag !== 'hr') element.append(...children)
  return element
}

function inlineMarkdown(value: string): string {
  return escapeHtml(value)
    .replace(/`([^`\n]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
    .replace(/__([^_\n]+)__/g, '<strong>$1</strong>')
    .replace(/\*([^*\n]+)\*/g, '<em>$1</em>')
    .replace(/\[([^\]\n]+)\]\(([^\s)\n]+)\)/g, '<a href="$2">$1</a>')
}

function tableCells(line: string): string[] {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '')
    .split('|').map((cell) => cell.trim()).slice(0, MAXIMUM_TABLE_COLUMNS)
}

function isTableDivider(line: string): boolean {
  const cells = tableCells(line)
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell))
}

function isBlockStart(lines: string[], index: number): boolean {
  const line = lines[index] ?? ''
  const next = lines[index + 1] ?? ''
  return !line.trim()
    || /^```/.test(line.trim())
    || /^#{1,6}\s+/.test(line)
    || /^>\s?/.test(line)
    || /^[-*+]\s+/.test(line)
    || /^\d+\.\s+/.test(line)
    || /^([-*_])\1{2,}\s*$/.test(line.trim())
    || (line.includes('|') && isTableDivider(next))
}

function escapeHtml(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;')
}

function safeHref(value: string | null): string | undefined {
  if (!value) return undefined
  const normalized = value.trim()
  if (!normalized || normalized.startsWith('//') || normalized.includes('\\')) return undefined
  if (Array.from(normalized).some((character) => {
    const code = character.charCodeAt(0)
    return code < 32 || code === 127
  })) return undefined
  const schemeDelimiter = normalized.indexOf(':')
  const firstPathDelimiter = Math.min(
    ...['/', '?', '#'].map((delimiter) => normalized.indexOf(delimiter))
      .filter((position) => position >= 0),
    normalized.length,
  )
  if (schemeDelimiter >= 0 && schemeDelimiter < firstPathDelimiter) {
    if (!/^https:\/\//i.test(normalized)) return undefined
    try {
      const parsed = new URL(normalized)
      if (parsed.protocol !== 'https:' || !parsed.hostname || parsed.username || parsed.password) return undefined
    } catch {
      return undefined
    }
  }
  return normalized
}

function boundedSpan(value: string | null): number | undefined {
  if (!value || !/^[1-9][0-9]?$/.test(value)) return undefined
  const parsed = Number(value)
  return parsed <= 20 ? parsed : undefined
}
