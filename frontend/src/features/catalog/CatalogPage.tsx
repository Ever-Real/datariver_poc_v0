import { useEffect, useState, type FormEvent } from 'react'
import type { ApiClient } from '../../api/client'
import type { CatalogAsset, CatalogSearch } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { PageTitle } from '../../components/layout/PageTitle'

export function validCatalogQuery(query: string): boolean {
  const length = query.trim().length
  return length === 0 || length >= 2
}

export function CatalogPage({ client, initialQuery = '' }: { client: ApiClient; initialQuery?: string }) {
  const [query, setQuery] = useState(initialQuery)
  const [items, setItems] = useState<CatalogAsset[]>([])
  const [error, setError] = useState<unknown>()
  const [loading, setLoading] = useState(false)

  useEffect(() => setQuery(initialQuery), [initialQuery])

  const search = async (event: FormEvent) => {
    event.preventDefault()
    if (!validCatalogQuery(query)) {
      setError(new Error('검색어는 비워 두거나 2자 이상 입력하세요.'))
      return
    }
    setLoading(true); setError(undefined)
    try {
      const result = await client.request<CatalogSearch>(`/catalog/assets?q=${encodeURIComponent(query)}&limit=50`)
      setItems(result.items)
    } catch (next) { setError(next) } finally { setLoading(false) }
  }

  return (
    <section>
      <PageTitle icon="SR" eyebrow="DataHub Wrapper" title="데이터 카탈로그 검색" description="Workspace·분류정책·권한 범위 안의 로컬 projection을 검색합니다." />
      <form className="search-bar" onSubmit={(event) => void search(event)}>
        <label className="sr-only" htmlFor="catalog-query">데이터셋 이름이나 설명 검색</label>
        <input id="catalog-query" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="데이터셋 이름이나 설명 검색 (2자 이상)" maxLength={500} aria-describedby="catalog-search-hint" />
        <button className="button" disabled={loading}>{loading ? '검색 중…' : '검색'}</button>
      </form>
      <p id="catalog-search-hint" className="muted">검색어를 비워 전체 허용 범위를 탐색하거나 2자 이상 입력하세요.</p>
      <ErrorNotice error={error} />
      <div className="result-list">
        {items.map((item) => (
          <article className="result-card" key={item.id}>
            <div><span className="badge">{item.asset_type}</span><span className="badge badge-soft">{item.classification}</span></div>
            <h3>{item.name}</h3>
            <p>{item.description || '설명이 등록되지 않았습니다.'}</p>
            <footer><span>{item.platform || 'platform 미지정'}</span><code>{item.external_urn}</code></footer>
          </article>
        ))}
        {!loading && items.length === 0 && <div className="empty-state">검색 조건을 입력해 카탈로그를 탐색하세요.</div>}
      </div>
    </section>
  )
}
