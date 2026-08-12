import { useMemo, useState, type FormEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
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
  name: string
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
  asset_count: number
  assets: PocGlossaryAsset[]
}

export function PocGlossaryPage({ client }: { client: ApiClient }) {
  const [input, setInput] = useState('')
  const [query, setQuery] = useState('')
  const [selectedTermUrn, setSelectedTermUrn] = useState<string>()
  const [assetsExpanded, setAssetsExpanded] = useState(true)
  const terms = useQuery({
    queryKey: ['poc', 'glossary', query],
    queryFn: ({ signal }) => client.request<{ items: PocGlossaryTerm[] }>(
      `/poc/glossary?${new URLSearchParams(query ? { q: query } : {})}`,
      { signal },
    ),
    staleTime: 30_000,
  })
  const selectedTerm = useMemo(
    () => terms.data?.items.find((item) => item.urn === selectedTermUrn),
    [selectedTermUrn, terms.data?.items],
  )
  const columns = useMemo<ColumnDef<PocGlossaryTerm>[]>(() => [
    { accessorKey: 'name', header: '용어', size: 190, cell: ({ row }) => <div className="poc-glossary-name"><strong>{row.original.name}</strong><small>{row.original.hierarchical_name}</small></div> },
    { accessorKey: 'description', header: '용어 뜻', size: 360, cell: ({ row }) => row.original.description || 'DataHub에 정의가 등록되지 않았습니다.' },
    { id: 'parents', accessorFn: (row) => row.parent_terms.map((item) => item.name).join(' '), header: '상위 용어/분류', size: 250, cell: ({ row }) => row.original.parent_terms.map((item) => item.name).join(' › ') || '—' },
    { id: 'children', accessorFn: (row) => row.child_terms.map((item) => item.name).join(' '), header: '하위 용어', size: 180, cell: ({ row }) => row.original.child_terms.map((item) => item.name).join(', ') || '없음 (leaf term)' },
    { accessorKey: 'asset_count', header: '적용 자산', size: 110, cell: ({ row }) => <button
      type="button"
      className="poc-glossary-asset-count"
      aria-label={`${row.original.name} 적용 자산 ${row.original.asset_count}개 보기`}
      onClick={(event) => {
        event.stopPropagation()
        setSelectedTermUrn(row.original.urn)
        setAssetsExpanded(true)
      }}
    >{row.original.asset_count}</button> },
  ], [])
  const submit = (event: FormEvent) => {
    event.preventDefault()
    setQuery(input.trim())
  }
  return <section className="admin-page">
    <PageTitle icon="GL" eyebrow="Live DataHub glossary" title="용어사전" description="DataHub 실데이터에 연결된 Glossary Term과 적용 테이블을 조회합니다." />
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
          data={terms.data?.items ?? []}
          getRowId={(item) => item.urn}
          loading={terms.isFetching}
          emptyMessage="DataHub에 등록된 용어가 없습니다."
          selectedRowId={selectedTermUrn}
          onRowActivate={(item) => {
            setSelectedTermUrn(item.urn)
            setAssetsExpanded(true)
          }}
        />
        <aside className="poc-glossary-detail" aria-label="선택 용어 상세와 적용 자산">
          {selectedTerm ? <>
            <header><span className="eyebrow">Glossary context</span><h2>{selectedTerm.name}</h2><p>{selectedTerm.description || 'DataHub에 정의가 등록되지 않았습니다.'}</p></header>
            <dl>
              <div><dt>상위 용어/분류</dt><dd>{selectedTerm.parent_terms.map((item) => item.name).join(' › ') || '—'}</dd></div>
              <div><dt>하위 용어</dt><dd>{selectedTerm.child_terms.map((item) => item.name).join(', ') || '없음 · DataHub Glossary Term은 leaf입니다.'}</dd></div>
            </dl>
            <AccordionItem
              itemId="applied-assets"
              title="적용된 DataHub 테이블"
              summary={`${selectedTerm.asset_count}개`}
              expanded={assetsExpanded}
              onToggle={() => setAssetsExpanded((current) => !current)}
            >
              {selectedTerm.assets.length > 0
                ? <ul className="poc-glossary-assets">{selectedTerm.assets.map((asset) => <li key={asset.id}><strong>{asset.name}</strong><span>{asset.platform} · {asset.database_name || 'database 미지정'} · {asset.schema_name || 'schema 미지정'}</span><small>{asset.qualified_name}</small></li>)}</ul>
                : <p className="poc-glossary-empty">현재 DataHub 자산에 적용되지 않은 용어입니다.</p>}
            </AccordionItem>
          </> : <div className="poc-glossary-placeholder"><strong>용어를 선택하세요</strong><p>행 또는 적용 자산 수량을 클릭하면 정의와 연결 테이블이 이곳에 표시됩니다.</p></div>}
        </aside>
      </div>
    </section>
  </section>
}
