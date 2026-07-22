import type { CatalogMatchFragment } from '../../api/types'
import { CatalogEmptyValue } from './CatalogEmptyValue'

function escapeExpression(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

export function HighlightedText({ text, terms }: { text: string; terms: string[] }) {
  const normalized = [...new Set(terms.filter(Boolean))]
  if (normalized.length === 0) return <>{text}</>
  const expression = new RegExp(`(${normalized.map(escapeExpression).join('|')})`, 'gi')
  return <>{text.split(expression).map((part, index) => (
    normalized.some((term) => term.localeCompare(part, undefined, { sensitivity: 'accent' }) === 0)
      ? <mark key={`${part}-${index}`}>{part}</mark>
      : <span key={`${part}-${index}`}>{part}</span>
  ))}</>
}

export function CatalogMatchPreview({ fragments }: { fragments: CatalogMatchFragment[] }) {
  if (fragments.length === 0) return <CatalogEmptyValue />
  return <span className="catalog-match-preview">{fragments.map((fragment) => (
    <span key={`${fragment.field}-${fragment.text}`} title={fragment.text}>
      <b>{fragment.field === 'NAME' ? 'Name' : 'Desc'}</b>
      <HighlightedText text={fragment.text} terms={fragment.matched_terms} />
    </span>
  ))}</span>
}
