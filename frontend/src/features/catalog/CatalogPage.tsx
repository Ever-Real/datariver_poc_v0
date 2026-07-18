import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { Filter, Search } from 'lucide-react'
import type { ApiClient } from '../../api/client'
import type {
  CatalogAsset,
  CatalogFacets,
  CatalogSearch,
  CatalogSuggestion,
  CatalogSuggestions,
  Classification,
} from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { CursorPagination } from '../../components/common/CursorPagination'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import { TruncatedText } from '../../components/common/TruncatedText'
import { PageTitle } from '../../components/layout/PageTitle'
import { CatalogDetailPane } from './CatalogDetailPane'
import { CatalogExportControl } from './CatalogExportControl'
import { CatalogMatchPreview } from './CatalogMatchText'
import { CatalogResourceTree } from './CatalogResourceTree'

export function validCatalogQuery(query: string): boolean {
  const length = query.trim().length
  return length === 0 || length >= 2
}

interface Filters {
  assetType: string
  platform: string
  databaseName: string
  schemaName: string
  domain: string
  classification: string
  searchFields: SearchField[]
}

type SearchField = 'SCHEMA' | 'TABLE' | 'COLUMN' | 'TAG' | 'TERM' | 'DESCRIPTION'

const allSearchFields: SearchField[] = ['SCHEMA', 'TABLE', 'COLUMN', 'TAG', 'TERM', 'DESCRIPTION']
const searchFieldLabels: Record<SearchField, string> = {
  SCHEMA: 'Schema', TABLE: 'Table', COLUMN: 'Column', TAG: 'Tag', TERM: 'Term', DESCRIPTION: 'Description',
}

const emptyFilters: Filters = {
  assetType: '', platform: '', databaseName: '', schemaName: '', domain: '', classification: '', searchFields: allSearchFields,
}

function searchPath(query: string, filters: Filters, cursor: string | undefined, limit: number) {
  const parameters = new URLSearchParams({ q: query, limit: String(limit) })
  if (filters.assetType) parameters.set('asset_type', filters.assetType)
  if (filters.platform) parameters.set('platform', filters.platform)
  if (filters.databaseName) parameters.set('database', filters.databaseName)
  if (filters.schemaName) parameters.set('schema', filters.schemaName)
  if (filters.domain) parameters.set('domain', filters.domain)
  if (filters.classification) parameters.set('classification', filters.classification)
  parameters.set('search_fields', filters.searchFields.join(','))
  if (cursor) parameters.set('cursor', cursor)
  return parameters
}

export function CatalogPage({
  client,
  initialQuery = '',
  onQueryChange,
  catalogExportWorkerEnabled = false,
}: {
  client: ApiClient
  initialQuery?: string
  onQueryChange?: (query: string) => void
  catalogExportWorkerEnabled?: boolean
}) {
  const [draftQuery, setDraftQuery] = useState(initialQuery)
  const [query, setQuery] = useState(initialQuery)
  const [filters, setFilters] = useState<Filters>(emptyFilters)
  const [result, setResult] = useState<CatalogSearch>()
  const [facets, setFacets] = useState<CatalogFacets>()
  const [suggestions, setSuggestions] = useState<CatalogSuggestion[]>([])
  const [suggestionIndex, setSuggestionIndex] = useState(-1)
  const [selectedAssetId, setSelectedAssetId] = useState<string>()
  const [cursors, setCursors] = useState<Array<string | undefined>>([undefined])
  const [pageIndex, setPageIndex] = useState(0)
  const [pageSize, setPageSize] = useState(50)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<unknown>()
  const suggestionRoot = useRef<HTMLDivElement>(null)
  const initialQueryRef = useRef(initialQuery)

  useEffect(() => {
    if (initialQueryRef.current === initialQuery) return
    initialQueryRef.current = initialQuery
    setDraftQuery(initialQuery); setQuery(initialQuery); setCursors([undefined]); setPageIndex(0)
  }, [initialQuery])

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setError(undefined); setSelectedAssetId(undefined)
    const parameters = searchPath(query, filters, cursors[pageIndex], pageSize)
    void Promise.all([
      client.request<CatalogSearch>(`/catalog/assets?${parameters}`, { signal: controller.signal }),
      client.request<CatalogFacets>(`/catalog/facets?${searchPath(query, filters, undefined, 30)}`, { signal: controller.signal }),
    ]).then(([nextResult, nextFacets]) => {
      if (!controller.signal.aborted) { setResult(nextResult); setFacets(nextFacets) }
    }).catch((next: unknown) => { if (!controller.signal.aborted) setError(next) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [client, cursors, filters, pageIndex, pageSize, query])

  useEffect(() => {
    const normalized = draftQuery.trim()
    if (normalized.length < 2 || normalized === query) { setSuggestions([]); return }
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      void client.request<CatalogSuggestions>(`/catalog/suggestions?q=${encodeURIComponent(normalized)}&limit=8`, { signal: controller.signal })
        .then((response) => { if (!controller.signal.aborted) { setSuggestions(response.items); setSuggestionIndex(-1) } })
        .catch(() => { if (!controller.signal.aborted) setSuggestions([]) })
    }, 300)
    return () => { controller.abort(); window.clearTimeout(timer) }
  }, [client, draftQuery, query])

  useEffect(() => {
    const close = (event: MouseEvent) => {
      if (!suggestionRoot.current?.contains(event.target as Node)) setSuggestions([])
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  const commitQuery = (value: string) => {
    const normalized = value.trim()
    if (!validCatalogQuery(normalized)) { setError(new Error('검색어는 비워 두거나 2자 이상 입력하세요.')); return }
    setDraftQuery(normalized); setQuery(normalized); setSuggestions([]); setCursors([undefined]); setPageIndex(0)
    onQueryChange?.(normalized)
  }

  const submit = (event: FormEvent) => { event.preventDefault(); commitQuery(draftQuery) }
  const navigateSuggestions = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Escape') { setSuggestions([]); return }
    if (suggestions.length === 0 || !['ArrowDown', 'ArrowUp', 'Enter'].includes(event.key)) return
    event.preventDefault()
    if (event.key === 'ArrowDown') setSuggestionIndex((current) => Math.min(current + 1, suggestions.length - 1))
    if (event.key === 'ArrowUp') setSuggestionIndex((current) => Math.max(current - 1, 0))
    if (event.key === 'Enter' && suggestionIndex >= 0) {
      const selected = suggestions[suggestionIndex]
      if (selected) commitQuery(selected.name)
    }
  }

  const columns = useMemo<ColumnDef<CatalogAsset>[]>(() => [
    { id: 'number', header: 'No', size: 56, enableSorting: false, cell: ({ row }) => <span>{pageIndex * pageSize + row.index + 1}</span> },
    { accessorKey: 'asset_type', header: 'Type', size: 76, enableSorting: false, cell: ({ row }) => <span className={`badge catalog-asset-type-${row.original.asset_type.toLowerCase()}`}>{row.original.asset_type}</span> },
    { accessorKey: 'platform', header: 'Platform', size: 96, enableSorting: false, cell: ({ row }) => <TruncatedText value={row.original.platform ?? '—'} /> },
    { accessorKey: 'database_name', header: 'Database', size: 110, enableSorting: false, cell: ({ row }) => <TruncatedText value={row.original.database_name ?? '—'} /> },
    { accessorKey: 'schema_name', header: 'Schema', size: 110, enableSorting: false, cell: ({ row }) => <TruncatedText value={row.original.schema_name ?? '—'} /> },
    { accessorKey: 'name', header: 'Table / Asset', size: 210, enableSorting: false, cell: ({ row }) => <TruncatedText value={row.original.name} className="catalog-asset-name" /> },
    { accessorKey: 'owner', header: 'Owner', size: 140, enableSorting: false, cell: ({ row }) => <TruncatedText value={row.original.owner ?? '—'} /> },
    { accessorKey: 'domain', header: 'Domain', size: 130, enableSorting: false, cell: ({ row }) => <TruncatedText value={row.original.domain ?? '—'} /> },
    { accessorKey: 'terms', header: 'Terms', size: 170, enableSorting: false, cell: ({ row }) => <TruncatedText value={row.original.terms?.join(', ') || '—'} /> },
    { accessorKey: 'tags', header: 'Tags', size: 170, enableSorting: false, cell: ({ row }) => <TruncatedText value={row.original.tags?.join(', ') || '—'} /> },
    { accessorKey: 'classification', header: 'Class', size: 100, enableSorting: false, cell: ({ row }) => <span className="badge badge-soft">{row.original.classification}</span> },
    { accessorKey: 'description', header: 'Description', size: 260, enableSorting: false, cell: ({ row }) => <TruncatedText value={row.original.description ?? '설명 없음'} /> },
    { id: 'matches', header: 'Matches', size: 300, enableSorting: false, cell: ({ row }) => <CatalogMatchPreview fragments={row.original.matches} /> },
  ], [pageIndex, pageSize])

  const updateFilter = (name: keyof Filters, value: string) => {
    setFilters((current) => ({ ...current, [name]: value })); setCursors([undefined]); setPageIndex(0)
  }

  const toggleSearchField = (field: SearchField) => {
    setFilters((current) => {
      const selected = current.searchFields.includes(field)
      if (selected && current.searchFields.length === 1) return current
      const searchFields = selected
        ? current.searchFields.filter((value) => value !== field)
        : [...current.searchFields, field]
      return { ...current, searchFields }
    })
    setCursors([undefined]); setPageIndex(0)
  }

  const selectTreeScope = (scope: Pick<Filters, 'platform' | 'databaseName' | 'schemaName'>) => {
    setFilters((current) => ({ ...current, ...scope })); setCursors([undefined]); setPageIndex(0)
  }

  return <section className="catalog-page">
    <PageTitle icon="SR" eyebrow="DataHub Wrapper" title="데이터 카탈로그 검색" description="Workspace·분류정책·권한 범위 안의 로컬 projection을 검색합니다." />
    <div className="catalog-search-panel panel">
      <form className="catalog-search-form" role="search" aria-label="카탈로그 상세 검색" onSubmit={submit}>
        <div className="catalog-query-control" ref={suggestionRoot}>
          <Search size={16} aria-hidden="true" />
          <label className="sr-only" htmlFor="catalog-query">데이터셋 이름이나 설명 검색</label>
          <input id="catalog-query" value={draftQuery} onChange={(event) => setDraftQuery(event.target.value)} onKeyDown={navigateSuggestions} placeholder="데이터셋 이름이나 설명 검색 (2자 이상)" maxLength={500} autoComplete="off" aria-controls={suggestions.length ? 'catalog-suggestions' : undefined} aria-expanded={suggestions.length > 0} />
          {suggestions.length > 0 && <ul id="catalog-suggestions" className="catalog-suggestions" role="listbox">
            {suggestions.map((suggestion, index) => <li key={suggestion.id} role="option" aria-selected={index === suggestionIndex}><button type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => commitQuery(suggestion.name)}><span><b>{suggestion.name}</b><small>{suggestion.asset_type} · {suggestion.platform ?? 'platform 미지정'}</small></span></button></li>)}
          </ul>}
        </div>
        <button className="button" disabled={loading}><Search size={13} />{loading ? '검색 중…' : '검색'}</button>
      </form>
      <div className="catalog-filters" aria-label="검색 필터"><Filter size={14} aria-hidden="true" />
        <fieldset className="catalog-search-targets"><legend>Search in</legend>{allSearchFields.map((field) => <label key={field}><input type="checkbox" checked={filters.searchFields.includes(field)} onChange={() => toggleSearchField(field)} />{searchFieldLabels[field]}</label>)}</fieldset>
        <label>Type<select value={filters.assetType} onChange={(event) => updateFilter('assetType', event.target.value)}><option value="">전체</option>{facets?.asset_types.map((item) => item.value && <option key={item.value} value={item.value}>{item.value} ({item.count})</option>)}</select></label>
        <label>Platform<select value={filters.platform} onChange={(event) => updateFilter('platform', event.target.value)}><option value="">전체</option>{facets?.platforms.map((item) => item.value && <option key={item.value} value={item.value}>{item.value} ({item.count})</option>)}</select></label>
        <label>Database<input value={filters.databaseName} onChange={(event) => updateFilter('databaseName', event.target.value)} placeholder="Tree에서 선택" /></label>
        <label>Schema<input value={filters.schemaName} onChange={(event) => updateFilter('schemaName', event.target.value)} placeholder="Tree에서 선택" /></label>
        <label>Domain<input value={filters.domain} onChange={(event) => updateFilter('domain', event.target.value)} placeholder="DataHub domain" /></label>
        <label>Classification<select value={filters.classification} onChange={(event) => updateFilter('classification', event.target.value)}><option value="">전체</option>{facets?.classifications.map((item) => item.value && <option key={item.value} value={item.value}>{item.value} ({item.count})</option>)}</select></label>
        <button type="button" className="button button-secondary" onClick={() => { setFilters(emptyFilters); setCursors([undefined]); setPageIndex(0) }}>필터 초기화</button>
      </div>
      <CatalogExportControl
        client={client}
        workerEnabled={catalogExportWorkerEnabled}
        query={query}
        assetType={filters.assetType || undefined}
        platform={filters.platform || undefined}
        databaseName={filters.databaseName || undefined}
        schemaName={filters.schemaName || undefined}
        domain={filters.domain || undefined}
        searchFields={filters.searchFields}
        classification={classificationValue(filters.classification)}
      />
    </div>
    <ErrorNotice error={error} />
    <div className={`catalog-workspace ${selectedAssetId ? 'with-detail' : ''}`}>
      <CatalogResourceTree client={client} query={query} selectedAssetId={selectedAssetId} onSelectAsset={setSelectedAssetId} onSelectScope={selectTreeScope} />
      <section className="catalog-results" aria-label="카탈로그 검색 결과">
        <header><div><span className="eyebrow">Permission scoped</span><h2>Search Results</h2></div><span>{result ? `${result.items.length} / ${(result.total ?? result.items.length).toLocaleString()} items` : '0 items'} · ALL keywords</span></header>
        <DenseDataTable caption="카탈로그 검색 결과" columns={columns} data={result?.items ?? []} getRowId={(item) => item.id} loading={loading} emptyMessage={query ? '검색 조건에 맞는 허용 자산이 없습니다.' : '현재 권한 범위에서 표시할 자산이 없습니다.'} selectedRowId={selectedAssetId} onRowActivate={(item) => setSelectedAssetId(item.id)} />
        <CursorPagination page={pageIndex + 1} pageSize={pageSize} canPrevious={pageIndex > 0} canNext={Boolean(result?.page.next_cursor)} itemCount={result?.items.length} onPrevious={() => setPageIndex((current) => Math.max(0, current - 1))} onNext={() => { if (!result?.page.next_cursor) return; setCursors((current) => [...current.slice(0, pageIndex + 1), result.page.next_cursor]); setPageIndex((current) => current + 1) }} onPageSizeChange={(value) => { setPageSize(value); setCursors([undefined]); setPageIndex(0) }} />
        {result && <footer className="catalog-result-meta"><span>projection v{result.meta.projection_version}</span><span>policy {result.meta.policy_version}</span><time dateTime={result.meta.observed_at}>{result.meta.observed_at ? new Date(result.meta.observed_at).toLocaleString() : '관측 시각 없음'}</time></footer>}
      </section>
      {selectedAssetId && <CatalogDetailPane key={selectedAssetId} client={client} assetId={selectedAssetId} onClose={() => setSelectedAssetId(undefined)} onSelectAsset={setSelectedAssetId} />}
    </div>
  </section>
}

function classificationValue(value: string): Classification | undefined {
  if (value === 'PUBLIC' || value === 'INTERNAL' || value === 'CONFIDENTIAL' || value === 'RESTRICTED') {
    return value
  }
  return undefined
}
