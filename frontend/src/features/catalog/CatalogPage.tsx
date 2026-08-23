import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { useQuery, keepPreviousData, useQueryClient } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { Filter, RotateCcw, Search } from 'lucide-react'
import type { ApiClient } from '../../api/client'
import type {
  CatalogAsset,
  CatalogAssetDetail,
  CatalogFacets,
  CatalogSearch,
  CatalogSuggestion,
  CatalogSuggestions,
  Classification,
  QualityAsset,
} from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { CursorPagination } from '../../components/common/CursorPagination'
import { BadgeScroller } from '../../components/common/ControlledVocabularyInput'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import { TruncatedText } from '../../components/common/TruncatedText'
import { PageTitle } from '../../components/layout/PageTitle'
import { CatalogDetailPane } from './CatalogDetailPane'
import { CatalogEmptyValue } from './CatalogEmptyValue'
import { CatalogExportControl } from './CatalogExportControl'
import { CatalogMatchPreview } from './CatalogMatchText'
import { CatalogResourceTree } from './CatalogResourceTree'
import { QualityApi, qualityQueryKey } from '../quality/qualityApi'
import { basisPointsText, QualityStatus } from '../quality/QualityShared'
import { useQualityAuthorizationLease } from '../quality/useQualityAuthorizationLease'
import { isAuthorizationBoundaryError } from '../quality/useBoundedQualityRunPolling'

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
  lifecycle: string
  searchFields: SearchField[]
}

type SearchField = 'SCHEMA' | 'TABLE' | 'COLUMN' | 'TAG' | 'TERM' | 'DESCRIPTION'

const allSearchFields: SearchField[] = ['SCHEMA', 'TABLE', 'COLUMN', 'TAG', 'TERM', 'DESCRIPTION']
const searchFieldLabels: Record<SearchField, string> = {
  SCHEMA: 'Schema', TABLE: 'Table', COLUMN: 'Column', TAG: 'Tag', TERM: 'Term', DESCRIPTION: 'Description',
}

const emptyFilters: Filters = {
  assetType: '', platform: '', databaseName: '', schemaName: '', domain: '', classification: '', lifecycle: '', searchFields: allSearchFields,
}

function searchPath(query: string, filters: Filters, cursor: string | undefined, limit: number) {
  const parameters = new URLSearchParams({ q: query, limit: String(limit) })
  if (filters.assetType) parameters.set('asset_type', filters.assetType)
  if (filters.platform) parameters.set('platform', filters.platform)
  if (filters.databaseName) parameters.set('database', filters.databaseName)
  if (filters.schemaName) parameters.set('schema', filters.schemaName)
  if (filters.domain) parameters.set('domain', filters.domain)
  if (filters.classification) parameters.set('classification', filters.classification)
  if (filters.lifecycle) parameters.set('lifecycle', filters.lifecycle)
  parameters.set('search_fields', filters.searchFields.join(','))
  if (cursor) parameters.set('cursor', cursor)
  return parameters
}

export function CatalogPage({
  client,
  initialQuery = '',
  onQueryChange,
  catalogExportWorkerEnabled = false,
  workspaceId = '',
  subjectId = '',
  securityEpoch = 0,
  authorizationRevision = 0,
}: {
  client: ApiClient
  initialQuery?: string
  onQueryChange?: (query: string) => void
  catalogExportWorkerEnabled?: boolean
  workspaceId?: string
  subjectId?: string
  securityEpoch?: number
  authorizationRevision?: number
}) {
  const queryClient = useQueryClient()
  const qualityApi = useMemo(() => new QualityApi(client), [client])
  const qualityLease = useQualityAuthorizationLease({
    api: qualityApi,
    workspaceId,
    subjectId,
    securityEpoch,
    authorizationRevision,
  })
  const [draftQuery, setDraftQuery] = useState(initialQuery)
  const [query, setQuery] = useState(initialQuery)
  const [filters, setFilters] = useState<Filters>(emptyFilters)
  const [error, setError] = useState<unknown>()
  const [suggestions, setSuggestions] = useState<CatalogSuggestion[]>([])
  const [suggestionIndex, setSuggestionIndex] = useState(-1)
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [selectedAssetId, setSelectedAssetId] = useState<string>()
  const [focusedAssetId, setFocusedAssetId] = useState<string>()
  const [treeAssetId, setTreeAssetId] = useState<string>()
  const [detailWidth, setDetailWidth] = useState(550)
  const [cursors, setCursors] = useState<Array<string | undefined>>([undefined])
  const [pageIndex, setPageIndex] = useState(0)
  const [pageSize, setPageSize] = useState(50)
  const suggestionRoot = useRef<HTMLDivElement>(null)
  const filterRoot = useRef<HTMLDivElement>(null)
  const workspaceRef = useRef<HTMLDivElement>(null)
  const initialQueryRef = useRef(initialQuery)
  const hasSearchTargets = filters.searchFields.length > 0

  useEffect(() => {
    if (initialQueryRef.current === initialQuery) return
    initialQueryRef.current = initialQuery
    setDraftQuery(initialQuery); setQuery(initialQuery); setCursors([undefined]); setPageIndex(0)
    setTreeAssetId(undefined); setSelectedAssetId(undefined); setFocusedAssetId(undefined)
  }, [initialQuery])

  useEffect(() => {
    return () => {
      queryClient.removeQueries({ queryKey: ['catalog', 'assets'] })
      queryClient.removeQueries({ queryKey: ['catalog', 'facets'] })
    }
  }, [queryClient])

  const { data: result, isFetching: loading } = useQuery({
    queryKey: ['catalog', 'assets', query, filters, cursors[pageIndex], pageSize],
    queryFn: async ({ signal }) => client.request<CatalogSearch>(
      `/catalog/assets?${searchPath(query, filters, cursors[pageIndex], pageSize)}`,
      { signal },
    ),
    placeholderData: keepPreviousData,
    enabled: hasSearchTargets,
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
  })

  const { data: facets } = useQuery({
    queryKey: ['catalog', 'facets', query, filters],
    queryFn: async ({ signal }) => client.request<CatalogFacets>(
      `/catalog/facets?${searchPath(query, filters, undefined, 30)}`,
      { signal },
    ),
    enabled: hasSearchTargets,
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
  })

  const { data: treeAsset, error: treeAssetError, isFetching: treeAssetLoading } = useQuery({
    queryKey: ['catalog', 'asset', treeAssetId, 0],
    queryFn: async ({ signal }) => client.request<CatalogAssetDetail>(
      `/catalog/assets/${treeAssetId}`,
      { signal },
    ),
    enabled: Boolean(treeAssetId),
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
  })

  useEffect(() => {
    if (!treeAssetId || !treeAsset) return
    if (treeAsset.id !== treeAssetId) {
      setError(new Error('Resource Tree가 요청한 정확한 자산을 확인하지 못했습니다.'))
      return
    }
    setError(undefined)
    setFocusedAssetId(treeAsset.id)
    setSelectedAssetId(treeAsset.id)
  }, [treeAsset, treeAssetId])

  const resolvedTreeAsset = treeAsset?.id === treeAssetId ? treeAsset : undefined
  const displayedItems = resolvedTreeAsset
    ? [resolvedTreeAsset]
    : hasSearchTargets
      ? result?.items ?? []
      : []

  const qualityAssetIds = useMemo(() => {
    return hasSearchTargets ? result?.items.map((item) => item.id) ?? [] : []
  }, [hasSearchTargets, result?.items])
  const qualityBoundary = qualityLease.boundary
  const qualityReadAvailable = Boolean(
    qualityBoundary && qualityLease.axis('read_access')?.state === 'AVAILABLE',
  )
  const qualitySummaries = useQuery({
    queryKey: qualityBoundary
      ? qualityQueryKey(qualityBoundary, 'asset-summaries', ...qualityAssetIds)
      : ['quality', 'catalog-asset-summaries', 'unavailable'],
    queryFn: ({ signal }) => qualityApi.assetSummaries(
      qualityAssetIds,
      qualityBoundary?.cacheScope ?? '',
      signal,
    ),
    enabled: Boolean(
      qualityReadAvailable
      && qualityAssetIds.length > 0,
    ),
    staleTime: 0,
    gcTime: 30_000,
    retry: false,
  })
  const invalidateQualityLease = qualityLease.invalidate
  useEffect(() => {
    if (isAuthorizationBoundaryError(qualitySummaries.error)) invalidateQualityLease()
  }, [invalidateQualityLease, qualitySummaries.error])
  const qualityByAsset = useMemo(
    () => new Map(qualitySummaries.data?.items.map((item) => [item.asset_id, item]) ?? []),
    [qualitySummaries.data?.items],
  )

  useEffect(() => {
    const normalized = draftQuery.trim()
    if (normalized.length < 2 || normalized === query) { setSuggestions([]); setSuggestionIndex(-1); return }
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      void client.request<CatalogSuggestions>(`/catalog/suggestions?q=${encodeURIComponent(normalized)}&limit=8`, { signal: controller.signal })
        .then((response) => { if (!controller.signal.aborted) { setSuggestions(response.items); setSuggestionIndex(-1) } })
        .catch(() => { if (!controller.signal.aborted) { setSuggestions([]); setSuggestionIndex(-1) } })
    }, 300)
    return () => { controller.abort(); window.clearTimeout(timer) }
  }, [client, draftQuery, query])

  useEffect(() => {
    const close = (event: MouseEvent) => {
      if (!suggestionRoot.current?.contains(event.target as Node)) {
        setSuggestions([])
        setSuggestionIndex(-1)
      }
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  useEffect(() => {
    const close = (event: MouseEvent) => {
      if (!filterRoot.current?.contains(event.target as Node)) setFiltersOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  const commitQuery = (value: string) => {
    const normalized = value.trim()
    if (!validCatalogQuery(normalized)) { setError(new Error('검색어는 비워 두거나 2자 이상 입력하세요.')); return }
    setTreeAssetId(undefined); setSelectedAssetId(undefined); setFocusedAssetId(undefined)
    if (normalized === query) { setSuggestions([]); setSuggestionIndex(-1); return }
    setDraftQuery(normalized); setQuery(normalized); setSuggestions([]); setSuggestionIndex(-1); setCursors([undefined]); setPageIndex(0)
    onQueryChange?.(normalized)
  }

  const submit = (event: FormEvent) => { event.preventDefault(); commitQuery(draftQuery) }
  const navigateSuggestions = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Escape') { setSuggestions([]); setSuggestionIndex(-1); return }
    if (event.key === 'Enter' && suggestionIndex < 0) {
      event.preventDefault()
      commitQuery(draftQuery)
      return
    }
    if (suggestions.length === 0 || !['ArrowDown', 'ArrowUp', 'Home', 'End', 'Enter'].includes(event.key)) return
    event.preventDefault()
    if (event.key === 'ArrowDown') setSuggestionIndex((current) => Math.min(current + 1, suggestions.length - 1))
    if (event.key === 'ArrowUp') setSuggestionIndex((current) => current < 0 ? suggestions.length - 1 : Math.max(current - 1, 0))
    if (event.key === 'Home') setSuggestionIndex(0)
    if (event.key === 'End') setSuggestionIndex(suggestions.length - 1)
    if (event.key === 'Enter' && suggestionIndex >= 0) {
      const selected = suggestions[suggestionIndex]
      if (selected) commitQuery(selected.name)
    }
  }

  const columns = useMemo<ColumnDef<CatalogAsset>[]>(() => [
    { id: 'number', header: 'No', size: 36, enableSorting: false, cell: ({ row }) => <span>{pageIndex * pageSize + row.index + 1}</span> },
    { accessorKey: 'asset_type', header: 'Type', size: 76, cell: ({ row }) => <span className={`badge catalog-asset-type-${row.original.asset_type.toLowerCase()}`}>{row.original.asset_type}</span> },
    { accessorKey: 'platform', header: 'Platform', size: 60, cell: ({ row }) => optionalTableText(row.original.platform) },
    { accessorKey: 'database_name', header: 'Database', size: 68, cell: ({ row }) => optionalTableText(row.original.database_name) },
    { accessorKey: 'schema_name', header: 'Schema', size: 68, cell: ({ row }) => optionalTableText(row.original.schema_name) },
    { accessorKey: 'name', header: 'Table / Asset', size: 210, cell: ({ row }) => <TruncatedText value={row.original.name} className="catalog-asset-name" /> },
    {
      id: 'quality',
      header: 'Quality',
      size: 80,
      enableSorting: false,
      cell: ({ row }) => <CatalogQualitySummary
        available={qualityReadAvailable}
        loading={qualitySummaries.isPending && qualitySummaries.fetchStatus === 'fetching'}
        value={qualityByAsset.get(row.original.id)}
      />,
    },
    { id: 'terms', accessorFn: (row) => (row.terms ?? []).join(' '), header: 'Terms', size: 104, cell: ({ row }) => <BadgeScroller label={`${row.original.name} Terms`} values={row.original.terms ?? []} truncated={row.original.terms_truncated} /> },
    { id: 'tags', accessorFn: (row) => (row.tags ?? []).join(' '), header: 'Tags', size: 104, cell: ({ row }) => <BadgeScroller label={`${row.original.name} Tags`} values={row.original.tags ?? []} truncated={row.original.tags_truncated} /> },
    { accessorKey: 'owner', header: 'Owner', size: 86, cell: ({ row }) => optionalTableText(row.original.owner) },
    { accessorKey: 'domain', header: 'Domain', size: 80, cell: ({ row }) => optionalTableText(row.original.domain) },
    { accessorKey: 'classification', header: 'Class', size: 100, cell: ({ row }) => <span className="badge badge-soft">{row.original.classification}</span> },
    { accessorKey: 'description', header: 'Description', size: 260, cell: ({ row }) => boundedTableText(row.original.description, row.original.description_truncated) },
    { id: 'matches', accessorFn: (row) => row.matches.map((match) => match.text).join(' '), header: 'Matches', size: 300, cell: ({ row }) => <CatalogMatchPreview fragments={row.original.matches} /> },
  ], [
    pageIndex,
    pageSize,
    qualityByAsset,
    qualityReadAvailable,
    qualitySummaries.fetchStatus,
    qualitySummaries.isPending,
  ])

  const updateFilter = (name: keyof Filters, value: string) => {
    setTreeAssetId(undefined); setSelectedAssetId(undefined); setFocusedAssetId(undefined)
    setFilters((current) => ({ ...current, [name]: value })); setCursors([undefined]); setPageIndex(0)
  }

  const toggleSearchField = (field: SearchField) => {
    setTreeAssetId(undefined); setSelectedAssetId(undefined); setFocusedAssetId(undefined)
    setFilters((current) => {
      const selected = current.searchFields.includes(field)
      const searchFields = selected
        ? current.searchFields.filter((value) => value !== field)
        : [...current.searchFields, field]
      return { ...current, searchFields }
    })
    setCursors([undefined]); setPageIndex(0)
  }

  const setAllSearchFields = (checked: boolean) => {
    setTreeAssetId(undefined); setSelectedAssetId(undefined); setFocusedAssetId(undefined)
    setFilters((current) => ({ ...current, searchFields: checked ? allSearchFields : [] }))
    setCursors([undefined]); setPageIndex(0)
  }

  const resetFilters = () => {
    setFilters(emptyFilters)
    setDraftQuery('')
    setQuery('')
    setSuggestions([])
    setSuggestionIndex(-1)
    setFiltersOpen(false)
    setCursors([undefined])
    setPageIndex(0)
    setPageSize(50)
    setSelectedAssetId(undefined)
    setFocusedAssetId(undefined)
    setTreeAssetId(undefined)
    setError(undefined)
    onQueryChange?.('')
  }

  const selectAsset = (assetId: string) => {
    if (treeAssetId && treeAssetId !== assetId) setTreeAssetId(undefined)
    setFocusedAssetId(assetId)
    setSelectedAssetId(assetId)
  }

  const focusTreeAsset = (assetId: string) => {
    setTreeAssetId(assetId)
    setFocusedAssetId(undefined)
    setSelectedAssetId(undefined)
    setError(undefined)
  }

  const closeSelectedAsset = () => {
    setSelectedAssetId(undefined)
  }


  const activeFilterCount = [
    filters.assetType,
    filters.platform,
    filters.databaseName,
    filters.schemaName,
    filters.domain,
    filters.classification,
    filters.lifecycle,
  ].filter(Boolean).length + (filters.searchFields.length === allSearchFields.length ? 0 : 1)
  const canReset = activeFilterCount > 0 || Boolean(draftQuery || query || selectedAssetId || focusedAssetId) || pageIndex > 0 || pageSize !== 50

  const paginationProps = {
    page: pageIndex + 1,
    pageSize,
    pageSizeOptions: [25, 50, 100],
    canPrevious: hasSearchTargets && !resolvedTreeAsset && pageIndex > 0,
    canNext: hasSearchTargets && !resolvedTreeAsset && Boolean(result?.page.next_cursor),
    itemCount: displayedItems.length,
    onPrevious: () => {
      setTreeAssetId(undefined); setSelectedAssetId(undefined); setFocusedAssetId(undefined)
      setPageIndex((current) => Math.max(0, current - 1))
    },
    onNext: () => {
      const nextCursor = result?.page.next_cursor
      if (!nextCursor) return
      setTreeAssetId(undefined); setSelectedAssetId(undefined); setFocusedAssetId(undefined)
      setCursors((current) => [...current.slice(0, pageIndex + 1), nextCursor])
      setPageIndex((current) => current + 1)
    },
    onPageSizeChange: (value: number) => {
      setTreeAssetId(undefined); setSelectedAssetId(undefined); setFocusedAssetId(undefined)
      setPageSize(value); setCursors([undefined]); setPageIndex(0)
    },
  }

  return <section className="catalog-page">
    <PageTitle icon="SR" eyebrow="DataHub Wrapper" title="데이터 카탈로그 검색" description="Workspace·분류정책·권한 범위 안의 로컬 projection을 검색합니다." />
    <div className="catalog-search-panel panel">
      <div className="catalog-search-toolbar">
        <form className="catalog-search-form" role="search" aria-label="카탈로그 상세 검색" onSubmit={submit}>
          <div className="catalog-query-control" ref={suggestionRoot}>
            <Search size={16} aria-hidden="true" />
            <label className="sr-only" htmlFor="catalog-query">데이터셋 이름이나 설명 검색</label>
            <input id="catalog-query" value={draftQuery} onChange={(event) => { setDraftQuery(event.target.value); setSuggestionIndex(-1); }} onKeyDown={navigateSuggestions} placeholder="데이터셋 이름이나 설명 검색 (2자 이상)" maxLength={500} autoComplete="off" aria-controls="catalog-suggestions" aria-expanded={suggestions.length > 0} aria-autocomplete="list" aria-activedescendant={suggestionIndex >= 0 ? `catalog-suggestion-${suggestionIndex}` : undefined} role="combobox" />
            {suggestions.length > 0 && <ul id="catalog-suggestions" className="catalog-suggestions" role="listbox">
              {suggestions.map((suggestion, index) => <li key={suggestion.id} role="none"><button id={`catalog-suggestion-${index}`} role="option" aria-selected={index === suggestionIndex} type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => commitQuery(suggestion.name)}><span><b>{suggestion.name}</b><small>{suggestion.asset_type} · {[suggestion.platform, suggestion.database_name, suggestion.schema_name].filter(Boolean).join(' · ') || '위치 미지정'}</small><CatalogMatchPreview fragments={suggestion.matches ?? []} interactive={false} /></span></button></li>)}
            </ul>}
          </div>
          <button className="button" disabled={loading}><Search size={13} />{loading ? '검색 중…' : '검색'}</button>
        </form>
        <div className="catalog-filter-root" ref={filterRoot}>
          <button aria-controls="catalog-filter-popover" aria-expanded={filtersOpen} className="button button-secondary catalog-filter-trigger" onClick={() => setFiltersOpen((current) => !current)} type="button"><Filter size={14} />필터{activeFilterCount > 0 && <span className="catalog-filter-count">{activeFilterCount}</span>}</button>
          {filtersOpen && <div className="catalog-filter-popover" id="catalog-filter-popover" role="dialog" aria-label="상세 검색 필터">
            <header><div><span className="eyebrow">Advanced search</span><strong>검색 필터</strong></div><button aria-label="필터 조건 초기화" className="button button-secondary" onClick={resetFilters} type="button"><RotateCcw size={12} />초기화</button></header>
            <fieldset className="catalog-search-targets"><legend>Search in</legend><label><input aria-label="Search in 전체" checked={filters.searchFields.length === allSearchFields.length} onChange={(event) => setAllSearchFields(event.target.checked)} type="checkbox" />전체</label>{allSearchFields.map((field) => <label key={field}><input checked={filters.searchFields.includes(field)} onChange={() => toggleSearchField(field)} type="checkbox" />{searchFieldLabels[field]}</label>)}</fieldset>
            <div className="catalog-filter-fields">
              <FacetSelect label="Type" value={filters.assetType} onChange={(value) => updateFilter('assetType', value)} options={facets?.asset_types ?? []} />
              <FacetSelect label="Platform" value={filters.platform} onChange={(value) => updateFilter('platform', value)} options={facets?.platforms ?? []} />
              <FacetSelect label="Database" value={filters.databaseName} onChange={(value) => updateFilter('databaseName', value)} options={facets?.databases ?? []} />
              <FacetSelect label="Schema" value={filters.schemaName} onChange={(value) => updateFilter('schemaName', value)} options={facets?.schemas ?? []} />
              <FacetSelect label="Domain" value={filters.domain} onChange={(value) => updateFilter('domain', value)} options={facets?.domains ?? []} />
              <FacetSelect label="Classification" value={filters.classification} onChange={(value) => updateFilter('classification', value)} options={facets?.classifications ?? []} />
              <FacetSelect label="Lifecycle" value={filters.lifecycle} onChange={(value) => updateFilter('lifecycle', value)} options={facets?.lifecycles ?? []} />
            </div>
            <footer><button className="button" onClick={() => setFiltersOpen(false)} type="button">필터 적용</button></footer>
          </div>}
        </div>
        <button aria-label="검색 화면 초기화" className="button button-secondary catalog-reset-trigger" disabled={!canReset} onClick={resetFilters} type="button"><RotateCcw size={13} />초기화</button>
        <CatalogExportControl
          client={client}
          compact
          workerEnabled={catalogExportWorkerEnabled}
          disabled={!hasSearchTargets}
          query={query}
          assetType={filters.assetType || undefined}
          platform={filters.platform || undefined}
          databaseName={filters.databaseName || undefined}
          schemaName={filters.schemaName || undefined}
          domain={filters.domain || undefined}
          searchFields={filters.searchFields}
          classification={classificationValue(filters.classification)}
          lifecycle={filters.lifecycle === 'ACTIVE' ? 'ACTIVE' : undefined}
        />
      </div>
    </div>
    <ErrorNotice error={error ?? treeAssetError} />
    {/* 오버레이 모드: catalog-workspace는 2컬럼 공유, 상세 창은 fixed overlay로 뜸 */}
    <div
      className="catalog-workspace"
      ref={workspaceRef}
      aria-busy={loading || treeAssetLoading}
    >
      <CatalogResourceTree client={client} selectedAssetId={focusedAssetId} onSelectAsset={focusTreeAsset} />
      <section className="catalog-results" aria-label="카탈로그 검색 결과">
        <header><div><span className="eyebrow">Permission scoped</span><h2>Search Results</h2><span>{resolvedTreeAsset ? '정확히 선택된 1 item' : hasSearchTargets && result ? (result.total_exact ? `${result.total.toLocaleString()} items` : `현재 ${result.items.length.toLocaleString()}건${result.page.next_cursor ? ' · 더 있음' : ''}`) : '0 items'} · ALL keywords · ↔ 좌우 스크롤</span></div><CursorPagination {...paginationProps} label="Search Results 상단 페이지 탐색" /></header>
        <DenseDataTable caption="카탈로그 검색 결과" columns={columns} data={displayedItems} getRowId={(item) => item.id} loading={(hasSearchTargets && loading) || treeAssetLoading} emptyMessage={!hasSearchTargets ? '검색 대상을 하나 이상 선택하세요.' : query ? '검색 조건에 맞는 허용 자산이 없습니다.' : '현재 권한 범위에서 표시할 자산이 없습니다.'} selectedRowId={focusedAssetId} onRowActivate={(item) => selectAsset(item.id)} />
        <p className="catalog-local-table-note">열 정렬은 현재 로드된 {displayedItems.length.toLocaleString()}건에 적용됩니다.</p>
        <CursorPagination {...paginationProps} />
        {hasSearchTargets && result && <footer className="catalog-result-meta"><span>projection v{result.meta.projection_version}</span><span>policy {result.meta.policy_version}</span><time dateTime={result.meta.observed_at ?? undefined}>{result.meta.observed_at ? new Date(result.meta.observed_at).toLocaleString() : '관측 시각 없음'}</time></footer>}
      </section>
      {/* 상세 창은 오버레이로 렌더링 (검색 결과를 밀어내지 않음) */}
      {selectedAssetId && (
        <CatalogDetailPane
          key={selectedAssetId}
          client={client}
          assetId={selectedAssetId}
          onClose={closeSelectedAsset}
          onSelectAsset={selectAsset}
          onResizeWidth={(w) => setDetailWidth(Math.max(320, Math.min(w, 900)))}
          width={detailWidth}
          qualitySummary={qualityByAsset.get(selectedAssetId)}
          showQualityEvidence
          qualityReadAvailable={qualityReadAvailable}
          qualityLoading={qualitySummaries.isPending && qualitySummaries.fetchStatus === 'fetching'}
          asOverlay
        />
      )}
    </div>
  </section>

}

function CatalogQualitySummary({
  value,
  loading,
  available,
}: {
  value?: QualityAsset
  loading: boolean
  available: boolean
}) {
  if (loading) return <span className="catalog-quality-summary pending">확인 중…</span>
  if (!available) return <span className="catalog-quality-summary empty">표시 불가</span>
  if (!value || !value.latest_quality_outcome) {
    return <span className="catalog-quality-summary empty">검사 이력 없음</span>
  }
  return <span className="catalog-quality-summary">
    <QualityStatus value={value.latest_quality_outcome} />
    <strong>{basisPointsText(value.latest_score_basis_points)}</strong>
  </span>
}

function optionalTableText(value: string | null | undefined) {
  return value?.trim() ? <TruncatedText value={value} /> : <CatalogEmptyValue />
}

function boundedTableText(value: string | null | undefined, truncated = false) {
  if (!value?.trim()) return <CatalogEmptyValue />
  return <span><TruncatedText value={value} />{truncated && <span aria-label="일부만 표시" title="응답 크기 제한으로 일부 내용만 표시됩니다."> …</span>}</span>
}

function classificationValue(value: string): Classification | undefined {
  if (value === 'PUBLIC' || value === 'INTERNAL' || value === 'CONFIDENTIAL' || value === 'RESTRICTED') {
    return value
  }
  return undefined
}

function FacetSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  options: Array<{ value?: string | null; count: number }>
}) {
  const available = options.filter((item): item is { value: string; count: number } => Boolean(item.value))
  const selectedMissing = value && !available.some((item) => item.value === value)
  return <label>{label}<select onChange={(event) => onChange(event.target.value)} value={value}><option value="">전체</option>{selectedMissing && <option value={value}>{value}</option>}{available.map((item) => <option key={item.value} value={item.value}>{item.value} ({item.count})</option>)}</select></label>
}
