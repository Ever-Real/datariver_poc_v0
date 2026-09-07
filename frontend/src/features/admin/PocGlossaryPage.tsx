import { useCallback, useMemo, useState, type FormEvent } from 'react'
import { useInfiniteQuery, useQuery, useQueries } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import type { ApiClient } from '../../api/client'
import { ErrorNotice } from '../../components/ErrorNotice'
import { AccordionItem } from '../../components/common/Accordion'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import { PageTitle } from '../../components/layout/PageTitle'
import './pocGlossaryPage.css'

interface PocGlossaryHierarchyItem {
  urn: string
  name: string
  description: string
}

interface PocGlossaryAsset {
  id: string
  target_type: 'TABLE' | 'COLUMN'
  name: string
  table_name: string
  field_path: string | null
  qualified_name: string
  platform: string
  database_name: string
  schema_name: string
}

interface PocGlossaryTerm {
  urn: string
  name: string
  hierarchical_name: string
  description: string
  parent_terms: PocGlossaryHierarchyItem[]
  child_terms: PocGlossaryHierarchyItem[]
  hierarchy_kind: 'LEAF_TERM'
  asset_count: number | null
  table_asset_count: number | null
  column_asset_count: number | null
  assets: PocGlossaryAsset[]
  relationship_count: number
  relationships: Array<{
    type: string
    direction: string
    target_urn: string
    target_type: 'GLOSSARY_TERM' | 'GLOSSARY_NODE'
    target_name: string | null
  }>
  relationships_truncated: boolean
}

interface PocGlossaryPage {
  items: PocGlossaryTerm[]
  total: number
  page: { next_cursor: string | null; limit: number }
  currentness: {
    source: 'DATAHUB_GMS_LIVE'
    observed_at: string
    atomic_snapshot: false
  }
}

interface PocGlossaryAssignmentPage {
  items: PocGlossaryAsset[]
  total: number
  page: { next_cursor: string | null; limit: number }
}

interface PocGlossaryAssignmentCount {
  urn: string
  table_asset_count: number
  column_asset_count: number
}

interface PocGlossaryAssignmentCounts {
  items: PocGlossaryAssignmentCount[]
}

class MissingGlossaryAssignmentCountError extends Error {
  constructor(urn: string) {
    super(`용어 적용 수량 응답에 ${urn} 항목이 없습니다.`)
    this.name = 'MissingGlossaryAssignmentCountError'
  }
}

type AssignmentCountState =
  | { kind: 'LOADING' }
  | { kind: 'ERROR'; error: Error }
  | { kind: 'READY'; value: number }

interface PocGlossaryTreeRow {
  id: string
  kind: 'NODE' | 'TERM'
  name: string
  description: string
  hierarchical_name: string
  term?: PocGlossaryTerm
  children?: PocGlossaryTreeRow[]
}

function glossaryTree(terms: PocGlossaryTerm[]): PocGlossaryTreeRow[] {
  const roots: PocGlossaryTreeRow[] = []
  for (const term of terms) {
    let parentKey = 'ROOT'
    let siblings = roots
    for (const parent of term.parent_terms) {
      const id = `${parentKey}/${parent.urn}`
      let node = siblings.find((item) => item.id === id)
      if (!node) {
        node = {
          id,
          kind: 'NODE',
          name: parent.name,
          description: parent.description,
          hierarchical_name: parent.name,
          children: [],
        }
        siblings.push(node)
      }
      parentKey = id
      siblings = node.children ?? (node.children = [])
    }
    siblings.push({
      id: term.urn,
      kind: 'TERM',
      name: term.name,
      description: term.description,
      hierarchical_name: term.hierarchical_name,
      term,
    })
  }
  const sort = (rows: PocGlossaryTreeRow[]) => {
    rows.sort((left, right) => (
      left.kind.localeCompare(right.kind) || left.name.localeCompare(right.name)
    ))
    for (const row of rows) if (row.children) sort(row.children)
  }
  sort(roots)
  return roots
}

export function PocGlossaryPage({ client }: { client: ApiClient }) {
  const [input, setInput] = useState('')
  const [query, setQuery] = useState('')
  const [selectedTermUrn, setSelectedTermUrn] = useState<string>()
  const [tablesExpanded, setTablesExpanded] = useState(true)
  const [columnsExpanded, setColumnsExpanded] = useState(true)
  const terms = useInfiniteQuery({
    queryKey: ['poc', 'glossary', query],
    queryFn: ({ signal, pageParam }) => client.request<PocGlossaryPage>(
      `/poc/glossary?${new URLSearchParams({
        limit: '50',
        ...(query ? { q: query } : {}),
        ...(pageParam ? { cursor: pageParam } : {}),
      })}`,
      { signal },
    ),
    initialPageParam: '',
    getNextPageParam: (lastPage) => lastPage.page.next_cursor ?? undefined,
    staleTime: 30_000,
  })
  const loadedTerms = useMemo(
    () => terms.data?.pages.flatMap((page) => page.items) ?? [],
    [terms.data?.pages],
  )
  const selectedTermSummary = useMemo(
    () => loadedTerms.find((item) => item.urn === selectedTermUrn),
    [loadedTerms, selectedTermUrn],
  )
  const selectedTermDetail = useQuery({
    queryKey: ['poc', 'glossary', 'detail', selectedTermUrn],
    queryFn: ({ signal }) => client.request<PocGlossaryTerm>(
      `/poc/glossary/detail?urn=${encodeURIComponent(selectedTermUrn ?? '')}`,
      { signal },
    ),
    enabled: Boolean(selectedTermUrn),
    staleTime: 30_000,
  })
  const selectedTerm = selectedTermDetail.data ?? selectedTermSummary
  const tableAssignments = useInfiniteQuery({
    queryKey: ['poc', 'glossary', 'assignments', selectedTermUrn, 'TABLE'],
    queryFn: ({ signal, pageParam }) => client.request<PocGlossaryAssignmentPage>(
      `/poc/glossary/assignments?${new URLSearchParams({
        urn: selectedTermUrn ?? '', target_type: 'TABLE', limit: '25',
        ...(pageParam ? { cursor: pageParam } : {}),
      })}`,
      { signal },
    ),
    initialPageParam: '',
    getNextPageParam: (lastPage) => lastPage.page.next_cursor ?? undefined,
    enabled: Boolean(selectedTermUrn),
    staleTime: 30_000,
  })
  const columnAssignments = useInfiniteQuery({
    queryKey: ['poc', 'glossary', 'assignments', selectedTermUrn, 'COLUMN'],
    queryFn: ({ signal, pageParam }) => client.request<PocGlossaryAssignmentPage>(
      `/poc/glossary/assignments?${new URLSearchParams({
        urn: selectedTermUrn ?? '', target_type: 'COLUMN', limit: '25',
        ...(pageParam ? { cursor: pageParam } : {}),
      })}`,
      { signal },
    ),
    initialPageParam: '',
    getNextPageParam: (lastPage) => lastPage.page.next_cursor ?? undefined,
    enabled: Boolean(selectedTermUrn),
    staleTime: 30_000,
  })
  const appliedTables = tableAssignments.data?.pages.flatMap((page) => page.items) ?? []
  const appliedColumns = columnAssignments.data?.pages.flatMap((page) => page.items) ?? []
  const treeRows = useMemo(() => glossaryTree(loadedTerms), [loadedTerms])
  const selectTerm = useCallback((term: PocGlossaryTerm) => {
    setSelectedTermUrn(term.urn)
    setTablesExpanded(true)
    setColumnsExpanded(true)
  }, [])

  const batchCountScopes = useMemo(() => (terms.data?.pages ?? []).flatMap((page) => {
    const urns = page.items
      .filter((term) => term.table_asset_count === null || term.column_asset_count === null)
      .map((term) => term.urn)
    const scopes: string[][] = []
    for (let index = 0; index < urns.length; index += 50) scopes.push(urns.slice(index, index + 50))
    return scopes
  }), [terms.data?.pages])
  const batchCountsQueries = useQueries({
    queries: batchCountScopes.map((urns) => ({
      queryKey: ['poc', 'glossary', 'batch-counts', urns],
      queryFn: ({ signal }: { signal: AbortSignal }) => client.request<PocGlossaryAssignmentCounts>(
        '/poc/glossary/assignments/batch-counts',
        { method: 'POST', body: JSON.stringify({ urns }), signal },
      ),
      enabled: urns.length > 0,
      staleTime: 60_000,
      retry: false,
    })),
  })

  const getCount = useCallback((term: PocGlossaryTerm, type: 'table' | 'column'): AssignmentCountState => {
    const original = type === 'table' ? term.table_asset_count : term.column_asset_count
    if (original !== null) return { kind: 'READY', value: original }
    const pageIndex = batchCountScopes.findIndex((urns) => urns.includes(term.urn))
    const pageQuery = batchCountsQueries[pageIndex]
    if (!pageQuery || pageQuery.isPending) return { kind: 'LOADING' }
    if (pageQuery.isError) {
      return {
        kind: 'ERROR',
        error: pageQuery.error instanceof Error ? pageQuery.error : new Error('용어 적용 수량 조회에 실패했습니다.'),
      }
    }
    const item = pageQuery.data.items.find((count) => count.urn === term.urn)
    if (!item) return { kind: 'ERROR', error: new MissingGlossaryAssignmentCountError(term.urn) }
    return {
      kind: 'READY',
      value: type === 'table' ? item.table_asset_count : item.column_asset_count,
    }
  }, [batchCountScopes, batchCountsQueries])

  const columns = useMemo<ColumnDef<PocGlossaryTreeRow>[]>(() => [
    { accessorKey: 'name', header: '용어 계층', size: 300, cell: ({ row }) => <div className={`poc-glossary-tree-name poc-glossary-depth-${Math.min(row.depth, 8)}`}>
      {row.getCanExpand() ? <button
        type="button"
        className="poc-glossary-expander"
        aria-label={`${row.original.name} 하위 용어 ${row.getIsExpanded() ? '접기' : '펼치기'}`}
        aria-expanded={row.getIsExpanded()}
        onClick={(event) => { event.stopPropagation(); row.toggleExpanded() }}
      >{row.getIsExpanded() ? '−' : '+'}</button> : <span className="poc-glossary-expander-placeholder" />}
      <div className="poc-glossary-name"><strong>{row.original.name}</strong><small>{row.original.hierarchical_name}</small></div>
      <span className={`badge ${row.original.kind === 'NODE' ? 'badge-soft' : ''}`}>{row.original.kind === 'NODE' ? '분류' : '용어'}</span>
    </div> },
    { accessorKey: 'description', header: '뜻/설명', size: 360, cell: ({ row }) => row.original.description || (row.original.kind === 'NODE' ? 'DataHub에 분류 설명이 없습니다.' : 'DataHub에 정의가 등록되지 않았습니다.') },
    { id: 'table_count', accessorFn: (row) => row.term?.table_asset_count ?? -1, header: '적용 테이블', size: 105, cell: ({ row }) => {
      if (!row.original.term) return '—'
      const count = getCount(row.original.term, 'table')
      return <button
        type="button"
        className="poc-glossary-asset-count"
        aria-label={`${row.original.name} 적용 테이블 ${count.kind === 'READY' ? `${count.value}개 보기` : count.kind === 'LOADING' ? '조회 중' : '조회 오류'}`}
        onClick={(event) => {
          event.stopPropagation()
          selectTerm(row.original.term!)
        }}
      ><AssignmentCountValue state={count} /></button>
    } },
    { id: 'column_count', accessorFn: (row) => row.term?.column_asset_count ?? -1, header: '적용 컬럼', size: 105, cell: ({ row }) => {
      if (!row.original.term) return '—'
      const count = getCount(row.original.term, 'column')
      return <button
        type="button"
        className="poc-glossary-asset-count"
        aria-label={`${row.original.name} 적용 컬럼 ${count.kind === 'READY' ? `${count.value}개 보기` : count.kind === 'LOADING' ? '조회 중' : '조회 오류'}`}
        onClick={(event) => {
          event.stopPropagation()
          selectTerm(row.original.term!)
        }}
      ><AssignmentCountValue state={count} /></button>
    } },
  ], [getCount, selectTerm])
  const submit = (event: FormEvent) => {
    event.preventDefault()
    setSelectedTermUrn(undefined)
    setQuery(input.trim())
  }
  return <section className="admin-page">
    <PageTitle icon="GL" eyebrow="Live DataHub glossary" title="용어사전" description="DataHub GlossaryNode 계층과 실제 적용 테이블·컬럼을 구분해 조회합니다." />
    <section className="panel">
      <form className="catalog-search-form" role="search" aria-label="용어사전 검색" onSubmit={submit}>
        <label className="sr-only" htmlFor="poc-glossary-query">용어 검색</label>
        <input id="poc-glossary-query" type="search" maxLength={200} value={input} onChange={(event) => setInput(event.target.value)} placeholder="용어명 검색" />
        <button className="button" type="submit">검색</button>
      </form>
      <ErrorNotice error={terms.error} />
      <div className="poc-glossary-workspace">
        <DenseDataTable
          caption="DataHub 용어사전"
          columns={columns}
          data={treeRows}
          getRowId={(item) => item.id}
          getSubRows={(item) => item.children}
          initialExpanded
          loading={terms.isFetching}
          emptyMessage="DataHub에 등록된 용어가 없습니다."
          selectedRowId={selectedTermUrn}
          onRowActivate={(item) => {
            if (item.term) selectTerm(item.term)
          }}
        />
        <div className="poc-glossary-page-state" aria-live="polite">
          <span>
            현재 DataHub에서 {loadedTerms.length.toLocaleString()} / {(terms.data?.pages[0]?.total ?? 0).toLocaleString()}개 용어를 불러왔습니다.
            페이지 사이 provider 변경은 하나의 atomic snapshot으로 간주하지 않습니다.
          </span>
          {terms.hasNextPage && <button
            type="button"
            className="button button-secondary"
            disabled={terms.isFetchingNextPage}
            onClick={() => void terms.fetchNextPage()}
          >{terms.isFetchingNextPage ? '불러오는 중…' : '용어 더 보기'}</button>}
        </div>
        <aside className="poc-glossary-detail" aria-label="선택 용어 상세와 적용 자산">
          {selectedTermDetail.isFetching && <p className="poc-glossary-empty" role="status">선택 용어 상세와 관계를 불러오는 중입니다.</p>}
          <ErrorNotice error={selectedTermDetail.error} />
          {selectedTerm ? <>
            <header><span className="eyebrow">Glossary context</span><h2>{selectedTerm.name}</h2><p>{selectedTerm.description || 'DataHub에 정의가 등록되지 않았습니다.'}</p></header>
            <dl>
              <div><dt>상위 용어/분류</dt><dd>{selectedTerm.parent_terms.map((item) => item.name).join(' › ') || '—'}</dd></div>
              <div><dt>하위 용어</dt><dd>{selectedTerm.child_terms.map((item) => item.name).join(', ') || '없음 · DataHub Glossary Term은 leaf입니다.'}</dd></div>
              <div><dt>DataHub 직접 관계</dt><dd>{selectedTerm.relationship_count.toLocaleString()}개{selectedTerm.relationships_truncated ? ' · 현재 응답 일부' : ''}</dd></div>
            </dl>
            {selectedTerm.relationships.length > 0 && <section aria-label="선택 용어의 DataHub 직접 관계">
              <h3>직접 관계</h3>
              <ul className="poc-glossary-assets">{selectedTerm.relationships.map((relationship) => <li key={`${relationship.type}:${relationship.direction}:${relationship.target_urn}`}>
                <strong>{relationship.target_name ?? '이름 없음'}</strong>
                <span><span className="badge badge-soft">{relationship.direction}</span>{relationship.type} · {relationship.target_type}</span>
                <small>{relationship.target_urn}</small>
              </li>)}</ul>
              {selectedTerm.relationships_truncated && <p className="poc-glossary-empty">전체 관계는 K9 collector의 bounded provider pagination에서 검증하며, 이 화면은 현재 DataHub 응답에 포함된 관계만 표시합니다.</p>}
            </section>}
            <ErrorNotice error={tableAssignments.error ?? columnAssignments.error} />
            <AccordionItem
              itemId="applied-tables"
              title="적용된 DataHub 테이블"
              summary={`${tableAssignments.data?.pages[0]?.total ?? selectedTerm.table_asset_count ?? '권한 범위 조회'}${tableAssignments.data?.pages[0]?.total !== undefined || selectedTerm.table_asset_count !== null ? '개' : ''}`}
              expanded={tablesExpanded}
              onToggle={() => setTablesExpanded((current) => !current)}
            >
              {tableAssignments.isFetching && appliedTables.length === 0
                ? <p className="poc-glossary-empty">적용 테이블을 불러오는 중입니다.</p>
                : appliedTables.length > 0
                ? <><ul className="poc-glossary-assets">{appliedTables.map((asset) => <li key={asset.id}><strong>{asset.table_name}</strong><span><span className="badge badge-soft">TABLE</span>{asset.platform} · {asset.database_name || 'database 미지정'} · {asset.schema_name || 'schema 미지정'}</span><small>{asset.qualified_name}</small></li>)}</ul>{tableAssignments.hasNextPage && <button type="button" className="button button-secondary poc-glossary-more" disabled={tableAssignments.isFetchingNextPage} onClick={() => void tableAssignments.fetchNextPage()}>{tableAssignments.isFetchingNextPage ? '불러오는 중…' : '테이블 더 보기'}</button>}</>
                : <p className="poc-glossary-empty">현재 DataHub 테이블에 직접 적용되지 않은 용어입니다.</p>}
            </AccordionItem>
            <AccordionItem
              itemId="applied-columns"
              title="적용된 DataHub 컬럼"
              summary={`${columnAssignments.data?.pages[0]?.total ?? selectedTerm.column_asset_count ?? '권한 범위 조회'}${columnAssignments.data?.pages[0]?.total !== undefined || selectedTerm.column_asset_count !== null ? '개' : ''}`}
              expanded={columnsExpanded}
              onToggle={() => setColumnsExpanded((current) => !current)}
            >
              {columnAssignments.isFetching && appliedColumns.length === 0
                ? <p className="poc-glossary-empty">적용 컬럼을 불러오는 중입니다.</p>
                : appliedColumns.length > 0
                ? <><ul className="poc-glossary-assets">{appliedColumns.map((asset) => <li key={asset.id}><strong>{asset.table_name}.{asset.field_path}</strong><span><span className="badge badge-soft">COLUMN</span>{asset.platform} · {asset.database_name || 'database 미지정'} · {asset.schema_name || 'schema 미지정'}</span><small>{asset.qualified_name}</small></li>)}</ul>{columnAssignments.hasNextPage && <button type="button" className="button button-secondary poc-glossary-more" disabled={columnAssignments.isFetchingNextPage} onClick={() => void columnAssignments.fetchNextPage()}>{columnAssignments.isFetchingNextPage ? '불러오는 중…' : '컬럼 더 보기'}</button>}</>
                : <p className="poc-glossary-empty">현재 DataHub 컬럼에 적용되지 않은 용어입니다.</p>}
            </AccordionItem>
          </> : <div className="poc-glossary-placeholder"><strong>용어를 선택하세요</strong><p>계층의 용어 행 또는 적용 수량을 클릭하면 정의와 연결 테이블·컬럼이 이곳에 표시됩니다.</p></div>}
        </aside>
      </div>
    </section>
  </section>
}

function AssignmentCountValue({ state }: { state: AssignmentCountState }) {
  if (state.kind === 'LOADING') {
    return <span className="poc-glossary-count-skeleton" aria-hidden="true" />
  }
  if (state.kind === 'ERROR') {
    return <span className="poc-glossary-count-error" role="alert" title={state.error.message}>오류</span>
  }
  return state.value.toLocaleString()
}
