import { useMemo, useState, type FormEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import type { ApiClient } from '../../api/client'
import { ErrorNotice } from '../../components/ErrorNotice'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import { PageTitle } from '../../components/layout/PageTitle'

interface PocGlossaryTerm {
  name: string
  asset_count: number
  assets: string[]
}

export function PocGlossaryPage({ client }: { client: ApiClient }) {
  const [input, setInput] = useState('')
  const [query, setQuery] = useState('')
  const terms = useQuery({
    queryKey: ['poc', 'glossary', query],
    queryFn: ({ signal }) => client.request<{ items: PocGlossaryTerm[] }>(
      `/poc/glossary?${new URLSearchParams(query ? { q: query } : {})}`,
      { signal },
    ),
    staleTime: 30_000,
  })
  const columns = useMemo<ColumnDef<PocGlossaryTerm>[]>(() => [
    { accessorKey: 'name', header: '용어', size: 220, cell: ({ row }) => <strong>{row.original.name}</strong> },
    { accessorKey: 'asset_count', header: '적용 자산', size: 110 },
    { id: 'assets', accessorFn: (row) => row.assets.join(' '), header: '연결된 DataHub 테이블', size: 520, cell: ({ row }) => row.original.assets.join(', ') || '—' },
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
      <DenseDataTable caption="DataHub 용어사전" columns={columns} data={terms.data?.items ?? []} getRowId={(item) => item.name} loading={terms.isFetching} emptyMessage="DataHub 자산에 연결된 용어가 없습니다." />
    </section>
  </section>
}
