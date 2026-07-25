import { useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
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

/** 각 match fragment를 하나씩 슬라이드(Carousel) 방식으로 표시하고, 전체 텍스트는 title(tooltip)으로 제공 */
export function CatalogMatchPreview({ fragments }: { fragments: CatalogMatchFragment[] }) {
  const [index, setIndex] = useState(0)
  
  if (fragments.length === 0) return <CatalogEmptyValue />
  const labels: Record<CatalogMatchFragment['field'], string> = {
    NAME: 'Name',
    DESCRIPTION: 'Desc',
    SCHEMA: 'Schema',
    COLUMN: 'Column',
    TAG: 'Tag',
    TERM: 'Term',
  }
  
  const fullText = fragments.map((f) => `[${labels[f.field]}] ${f.text}`).join(' | ')
  const fragment = fragments[index]
  if (!fragment) return null
  const hasMultiple = fragments.length > 1

  return (
    <div className="catalog-match-carousel" title={fullText} style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
      {hasMultiple && (
        <button
          type="button"
          className="catalog-match-carousel-btn"
          disabled={index === 0}
          onClick={(e) => { e.stopPropagation(); setIndex(i => Math.max(0, i - 1)) }}
          style={{ cursor: index === 0 ? 'default' : 'pointer', background: 'transparent', border: 'none', padding: 0, display: 'flex', color: index === 0 ? '#ccc' : 'inherit' }}
        >
          <ChevronLeft size={14} />
        </button>
      )}
      <span className="catalog-match-preview catalog-match-preview--single-line" style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        <span key={`${fragment.field}-${index}-${fragment.text}`}>
          <b>{labels[fragment.field]}</b>
          <HighlightedText text={fragment.text} terms={fragment.matched_terms} />
        </span>
      </span>
      {hasMultiple && (
        <button
          type="button"
          className="catalog-match-carousel-btn"
          disabled={index === fragments.length - 1}
          onClick={(e) => { e.stopPropagation(); setIndex(i => Math.min(fragments.length - 1, i + 1)) }}
          style={{ cursor: index === fragments.length - 1 ? 'default' : 'pointer', background: 'transparent', border: 'none', padding: 0, display: 'flex', color: index === fragments.length - 1 ? '#ccc' : 'inherit' }}
        >
          <ChevronRight size={14} />
        </button>
      )}
    </div>
  )
}
