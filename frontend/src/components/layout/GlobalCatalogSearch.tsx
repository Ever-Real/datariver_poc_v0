import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Search } from 'lucide-react'
import type { ApiClient } from '../../api/client'
import type { CatalogSuggestion, CatalogSuggestions } from '../../api/types'

export function GlobalCatalogSearch({ client, onSearch }: { client?: ApiClient; onSearch: (query: string) => void }) {
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')
  const [focused, setFocused] = useState(false)
  const [loading, setLoading] = useState(false)
  const [suggestions, setSuggestions] = useState<CatalogSuggestion[]>([])
  const [suggestionError, setSuggestionError] = useState(false)
  const intent = useRef(0)

  useEffect(() => {
    const normalized = query.trim()
    const currentIntent = ++intent.current
    if (!client || !focused || normalized.length < 2) {
      setSuggestions([])
      setLoading(false)
      setSuggestionError(false)
      return
    }
    setLoading(true)
    setSuggestionError(false)
    const timer = window.setTimeout(() => {
      void client.request<CatalogSuggestions>(`/catalog/suggestions?q=${encodeURIComponent(normalized)}&limit=8`)
        .then((response) => {
          if (currentIntent === intent.current) setSuggestions(response.items)
        })
        .catch(() => {
          if (currentIntent === intent.current) {
            setSuggestions([])
            setSuggestionError(true)
          }
        })
        .finally(() => {
          if (currentIntent === intent.current) setLoading(false)
        })
    }, 350)
    return () => window.clearTimeout(timer)
  }, [client, focused, query])

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const normalized = query.trim()
    if (normalized.length < 2) {
      setError('검색어를 2자 이상 입력하세요.')
      return
    }
    setError('')
    setFocused(false)
    onSearch(normalized)
  }

  const choose = (suggestion: CatalogSuggestion) => {
    setQuery(suggestion.name)
    setFocused(false)
    onSearch(suggestion.name)
  }

  return (
    <div className="global-search-wrap" onBlur={(event) => {
      if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false)
    }}>
      <form className="global-search" role="search" aria-label="전역 카탈로그 검색" onSubmit={submit}>
        <label className="sr-only" htmlFor="global-catalog-query">카탈로그 검색</label>
        <Search size={15} aria-hidden="true" className="global-search-icon" />
        <input
          id="global-catalog-query"
          value={query}
          onChange={(event) => { setQuery(event.target.value); setError('') }}
          onFocus={() => setFocused(true)}
          placeholder="검색어를 입력하세요..."
          maxLength={500}
          autoComplete="off"
          aria-invalid={Boolean(error)}
          aria-expanded={focused && query.trim().length >= 2}
          aria-controls="global-search-suggestions"
          aria-describedby={error ? 'global-search-error' : undefined}
        />
        <button type="submit">검색</button>
        {error && <span className="global-search-error" id="global-search-error" role="alert">{error}</span>}
      </form>
      {focused && query.trim().length >= 2 && (
        <section className="global-search-suggestions" id="global-search-suggestions" aria-label="실시간 검색 결과">
          <header><span>실시간 검색 결과</span><small>{loading ? '조회 중' : `${suggestions.length}건`}</small></header>
          {suggestions.map((suggestion) => (
            <button type="button" key={suggestion.id} onClick={() => choose(suggestion)}>
              <span className="global-search-suggestion-type">{suggestion.asset_type}</span>
              <span><strong title={suggestion.name}>{suggestion.name}</strong><small>{suggestion.platform ?? 'Platform 정보 없음'}</small></span>
            </button>
          ))}
          {!loading && suggestions.length === 0 && (
            <p>{suggestionError ? '검색 미리보기를 불러오지 못했습니다. Enter로 전체 검색을 실행할 수 있습니다.' : '현재 권한 범위에서 일치하는 미리보기가 없습니다.'}</p>
          )}
        </section>
      )}
    </div>
  )
}
