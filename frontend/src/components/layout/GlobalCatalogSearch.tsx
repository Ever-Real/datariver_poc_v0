import { useState, type FormEvent } from 'react'

export function GlobalCatalogSearch({ onSearch }: { onSearch: (query: string) => void }) {
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const normalized = query.trim()
    if (normalized.length < 2) {
      setError('검색어를 2자 이상 입력하세요.')
      return
    }
    setError('')
    onSearch(normalized)
  }

  return (
    <form className="global-search" role="search" aria-label="전역 카탈로그 검색" onSubmit={submit}>
      <label className="sr-only" htmlFor="global-catalog-query">카탈로그 검색</label>
      <span aria-hidden="true" className="global-search-icon">⌕</span>
      <input
        id="global-catalog-query"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="카탈로그 검색 (2자 이상)"
        maxLength={500}
        aria-invalid={Boolean(error)}
        aria-describedby={error ? 'global-search-error' : undefined}
      />
      <button type="submit">검색</button>
      {error && <span className="global-search-error" id="global-search-error" role="alert">{error}</span>}
    </form>
  )
}

