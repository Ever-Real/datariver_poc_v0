import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { Search } from 'lucide-react'
import type { ApiClient } from '../../api/client'
import type { CatalogSuggestion, CatalogSuggestions } from '../../api/types'

const matchLabels = {
  NAME: '이름',
  DESCRIPTION: '설명',
  SCHEMA: '스키마',
  COLUMN: '컬럼',
  TAG: '태그',
  TERM: '용어',
} as const

export function GlobalCatalogSearch({
  client,
  onSearch,
  idPrefix = 'global-catalog',
  searchLabel = '전역 카탈로그 검색',
  inputLabel = '카탈로그 검색',
  placeholder = '검색어를 입력하세요...',
  maxLength = 500,
}: {
  client?: ApiClient
  onSearch: (query: string) => void
  idPrefix?: string
  searchLabel?: string
  inputLabel?: string
  placeholder?: string
  maxLength?: number
}) {
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')
  const [focused, setFocused] = useState(false)
  const [loading, setLoading] = useState(false)
  const [suggestions, setSuggestions] = useState<CatalogSuggestion[]>([])
  const [suggestionIndex, setSuggestionIndex] = useState(-1)
  const [suggestionError, setSuggestionError] = useState(false)
  const intent = useRef(0)

  useEffect(() => {
    const normalized = query.trim()
    const currentIntent = ++intent.current
    if (!client || !focused || normalized.length < 2) {
      setSuggestions([])
      setSuggestionIndex(-1)
      setLoading(false)
      setSuggestionError(false)
      return
    }
    setLoading(true)
    setSuggestionError(false)
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      void client.request<CatalogSuggestions>(
        `/catalog/suggestions?q=${encodeURIComponent(normalized)}&limit=8`,
        { signal: controller.signal },
      )
        .then((response) => {
          if (currentIntent === intent.current) {
            setSuggestions(response.items)
            setSuggestionIndex(-1)
          }
        })
        .catch(() => {
          if (!controller.signal.aborted && currentIntent === intent.current) {
            setSuggestions([])
            setSuggestionIndex(-1)
            setSuggestionError(true)
          }
        })
        .finally(() => {
          if (currentIntent === intent.current) setLoading(false)
        })
    }, 350)
    return () => { controller.abort(); window.clearTimeout(timer) }
  }, [client, focused, query])

  const commitQuery = () => {
    const normalized = query.trim()
    if (normalized.length < 2) {
      setError('검색어를 2자 이상 입력하세요.')
      return
    }
    setError('')
    setFocused(false)
    setSuggestionIndex(-1)
    onSearch(normalized)
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    commitQuery()
  }

  const choose = (suggestion: CatalogSuggestion) => {
    setQuery(suggestion.name)
    setFocused(false)
    setSuggestionIndex(-1)
    onSearch(suggestion.name)
  }

  const navigateSuggestions = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      setFocused(false)
      setSuggestionIndex(-1)
      return
    }
    if (event.key === 'Enter' && suggestionIndex < 0) {
      event.preventDefault()
      commitQuery()
      return
    }
    if (
      !suggestions.length
      || !['ArrowDown', 'ArrowUp', 'Home', 'End', 'Enter'].includes(event.key)
    ) return
    event.preventDefault()
    if (event.key === 'ArrowDown') {
      setSuggestionIndex((current) => Math.min(current + 1, suggestions.length - 1))
    } else if (event.key === 'ArrowUp') {
      setSuggestionIndex((current) => current < 0 ? suggestions.length - 1 : Math.max(current - 1, 0))
    } else if (event.key === 'Home') {
      setSuggestionIndex(0)
    } else if (event.key === 'End') {
      setSuggestionIndex(suggestions.length - 1)
    } else {
      const selected = suggestions[suggestionIndex]
      if (selected) choose(selected)
    }
  }

  return (
    <div className="global-search-wrap" onBlur={(event) => {
      if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false)
    }}>
      <form className="global-search" role="search" aria-label={searchLabel} onSubmit={submit}>
        <label className="sr-only" htmlFor={`${idPrefix}-query`}>{inputLabel}</label>
        <Search size={15} aria-hidden="true" className="global-search-icon" />
        <input
          id={`${idPrefix}-query`}
          value={query}
          onChange={(event) => { setQuery(event.target.value); setError(''); setFocused(true); setSuggestionIndex(-1) }}
          onFocus={() => setFocused(true)}
          onKeyDown={navigateSuggestions}
          placeholder={placeholder}
          maxLength={maxLength}
          autoComplete="off"
          aria-invalid={Boolean(error)}
          aria-expanded={focused && query.trim().length >= 2}
          aria-controls={`${idPrefix}-suggestions`}
          aria-autocomplete="list"
          aria-activedescendant={focused && suggestionIndex >= 0 ? `${idPrefix}-suggestion-${suggestionIndex}` : undefined}
          aria-describedby={error ? `${idPrefix}-error` : undefined}
          role="combobox"
        />
        <button type="submit">검색</button>
        {error && <span className="global-search-error" id={`${idPrefix}-error`} role="alert">{error}</span>}
      </form>
      {focused && query.trim().length >= 2 && (
        <section className="global-search-suggestions" aria-label="실시간 검색 결과">
          <header><span>실시간 검색 결과</span><small>{loading ? '조회 중' : `${suggestions.length}건`}</small></header>
          <div id={`${idPrefix}-suggestions`} role="listbox" aria-label="카탈로그 검색 제안">
          {suggestions.map((suggestion, index) => (
            <button
              id={`${idPrefix}-suggestion-${index}`}
              role="option"
              aria-selected={index === suggestionIndex}
              type="button"
              key={suggestion.id}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => choose(suggestion)}
            >
              <span className="global-search-suggestion-type">{suggestion.asset_type}</span>
              <span>
                <strong title={suggestion.name}>{suggestion.name}</strong>
                <small>
                  {[suggestion.platform, suggestion.database_name, suggestion.schema_name]
                    .filter(Boolean)
                    .join(' · ') || '위치 정보 없음'}
                </small>
                <span className="global-search-match-evidence">
                  {(suggestion.matches ?? []).map((match, index) => (
                    <span key={`${match.field}-${index}-${match.text}`} title={match.text}>
                      <small>{matchLabels[match.field]} · {match.matched_terms.join(', ')}</small>
                      <span>{match.text}</span>
                    </span>
                  ))}
                </span>
              </span>
            </button>
          ))}
          </div>
          {!loading && suggestions.length === 0 && (
            <p>{suggestionError ? '검색 미리보기를 불러오지 못했습니다. Enter로 전체 검색을 실행할 수 있습니다.' : '현재 권한 범위에서 일치하는 미리보기가 없습니다.'}</p>
          )}
        </section>
      )}
    </div>
  )
}
