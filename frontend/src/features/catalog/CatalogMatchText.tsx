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

/** 각 match fragment를 한 줄로 표시하고, 전체 텍스트는 title(tooltip)으로 제공 */
export function CatalogMatchPreview({ fragments }: { fragments: CatalogMatchFragment[] }) {
  if (fragments.length === 0) return <CatalogEmptyValue />
  const labels: Record<CatalogMatchFragment['field'], string> = {
    NAME: 'Name',
    DESCRIPTION: 'Desc',
    SCHEMA: 'Schema',
    COLUMN: 'Column',
    TAG: 'Tag',
    TERM: 'Term',
  }
  // 전체 텍스트를 합쳐 tooltip에 표시
  const fullText = fragments.map((f) => `[${labels[f.field]}] ${f.text}`).join(' | ')
  return (
    <span className="catalog-match-preview catalog-match-preview--single-line" title={fullText}>
      {fragments.map((fragment, index) => (
        <span key={`${fragment.field}-${index}-${fragment.text}`}>
          <b>{labels[fragment.field]}</b>
          <HighlightedText text={fragment.text} terms={fragment.matched_terms} />
        </span>
      ))}
    </span>
  )
}
