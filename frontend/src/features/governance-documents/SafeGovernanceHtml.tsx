import {
  createElement,
  useMemo,
  type ComponentPropsWithoutRef,
  type ReactNode,
} from 'react'
import { governancePresentationReactStyle } from './governancePresentationStyle'

const allowedElements = new Set([
  'p',
  'h1',
  'h2',
  'h3',
  'h4',
  'h5',
  'h6',
  'strong',
  'em',
  'u',
  's',
  'ul',
  'ol',
  'li',
  'blockquote',
  'code',
  'pre',
  'hr',
  'br',
  'table',
  'thead',
  'tbody',
  'tfoot',
  'tr',
  'th',
  'td',
  'a',
])

const suppressedElements = new Set([
  'applet',
  'area',
  'script',
  'style',
  'iframe',
  'object',
  'embed',
  'details',
  'dialog',
  'fieldset',
  'form',
  'frame',
  'frameset',
  'head',
  'input',
  'button',
  'legend',
  'map',
  'noframes',
  'noscript',
  'textarea',
  'select',
  'optgroup',
  'option',
  'picture',
  'plaintext',
  'source',
  'summary',
  'svg',
  'math',
  'meta',
  'base',
  'link',
  'img',
  'template',
  'track',
  'video',
  'audio',
  'canvas',
  'xmp',
])
const voidElements = new Set(['br', 'hr'])

export function SafeGovernanceHtml({
  html,
  contentHash,
  sanitizerPolicyVersion,
}: {
  html: string
  contentHash: string
  sanitizerPolicyVersion: string
}) {
  const content = useMemo(
    () => safeNodesForVersion(html, contentHash, sanitizerPolicyVersion),
    [contentHash, html, sanitizerPolicyVersion],
  )
  return <article className="governance-safe-html" data-sanitizer-policy={sanitizerPolicyVersion}>
    {content.length > 0 ? content : <p>표시할 수 있는 안전한 본문이 없습니다.</p>}
  </article>
}

function safeNodesForVersion(
  html: string,
  contentHash: string,
  sanitizerPolicyVersion: string,
): ReactNode[] {
  void contentHash
  void sanitizerPolicyVersion
  return safeNodes(html)
}

export function safeNodes(html: string): ReactNode[] {
  if (typeof DOMParser === 'undefined' || !html) return []
  const parsed = new DOMParser().parseFromString(html, 'text/html')
  return Array.from(parsed.body.childNodes).flatMap((node, index) => (
    safeNode(node, `root-${index}`)
  ))
}

function safeNode(node: Node, key: string): ReactNode[] {
  if (node.nodeType === Node.TEXT_NODE) return [node.textContent ?? '']
  if (!(node instanceof HTMLElement)) return []
  const tag = node.tagName.toLocaleLowerCase()
  if (suppressedElements.has(tag)) return []
  const children = Array.from(node.childNodes).flatMap((child, index) => (
    safeNode(child, `${key}-${index}`)
  ))
  const style = governancePresentationReactStyle(node.getAttribute('data-governance-style'))
  if (!allowedElements.has(tag)) return children
  if (tag === 'a') {
    const href = safeHref(node.getAttribute('href'))
    if (!href) return children
    const props: ComponentPropsWithoutRef<'a'> = {
      href,
      rel: 'noopener noreferrer',
    }
    if (/^https?:\/\//i.test(href)) props.target = '_blank'
    return [createElement('a', { ...props, key, ...(style ? { style } : {}) }, children)]
  }
  if (tag === 'th' || tag === 'td') {
    const span = boundedSpan(node.getAttribute('colspan'))
    const rowSpan = boundedSpan(node.getAttribute('rowspan'))
    return [createElement(tag, {
      key,
      ...(style ? { style } : {}),
      ...(span ? { colSpan: span } : {}),
      ...(rowSpan ? { rowSpan } : {}),
    }, children)]
  }
  if (voidElements.has(tag)) return [createElement(tag, { key, ...(style ? { style } : {}) })]
  return [createElement(tag, { key, ...(style ? { style } : {}) }, children)]
}

function safeHref(value: string | null): string | undefined {
  if (!value) return undefined
  const normalized = value.trim()
  if (
    !normalized
    || normalized.startsWith('//')
    || normalized.includes('\\')
    || Array.from(normalized).some((character) => {
      const code = character.charCodeAt(0)
      return code < 32 || code === 127
    })
  ) return undefined
  const schemeDelimiter = normalized.indexOf(':')
  const pathDelimiters = ['/', '?', '#']
    .map((delimiter) => normalized.indexOf(delimiter))
    .filter((index) => index >= 0)
  const firstPathDelimiter = pathDelimiters.length > 0
    ? Math.min(...pathDelimiters)
    : normalized.length
  if (schemeDelimiter >= 0 && schemeDelimiter < firstPathDelimiter) {
    if (!/^https:\/\//i.test(normalized)) return undefined
    try {
      const parsed = new URL(normalized)
      if (
        parsed.protocol !== 'https:'
        || !parsed.hostname
        || parsed.username
        || parsed.password
      ) return undefined
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
