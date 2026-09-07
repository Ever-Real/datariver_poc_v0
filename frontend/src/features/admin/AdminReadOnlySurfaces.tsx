import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { Download, Plus, Search } from 'lucide-react'
import type { ApiClient } from '../../api/client'
import type { CatalogVocabulary } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import { GovernedUnavailable } from '../../components/common/GovernedUnavailable'

interface MetadataLogRow {
  id: string
  timestamp: string
  action: string
  entity: string
  verified: string
  details: string
}

interface SecurityLogRow {
  id: string
  timestamp: string
  userId: string
  ipAddress: string
  action: string
  target: string
  status: string
}

const metadataColumns: ColumnDef<MetadataLogRow>[] = [
  { accessorKey: 'timestamp', header: 'Timestamp', size: 180 }, { accessorKey: 'action', header: 'Action', size: 150 },
  { accessorKey: 'entity', header: 'Entity (URN)', size: 320 }, { accessorKey: 'verified', header: 'Verified', size: 100 },
  { accessorKey: 'details', header: 'Details', size: 300 },
]
const securityColumns: ColumnDef<SecurityLogRow>[] = [
  { accessorKey: 'timestamp', header: 'Timestamp', size: 180 }, { accessorKey: 'userId', header: 'User ID', size: 220 },
  { accessorKey: 'ipAddress', header: 'IP Address', size: 140 }, { accessorKey: 'action', header: 'Action', size: 180 },
  { accessorKey: 'target', header: 'Target', size: 280 }, { accessorKey: 'status', header: 'Status', size: 100 },
]

type AuditLogView = 'metadata' | 'security'

function initialAuditLogView(): AuditLogView {
  const parameters = new URL(window.location.href).searchParams
  return parameters.get('adminView') === 'security' || parameters.get('adminSection') === 'securityLogs'
    ? 'security'
    : 'metadata'
}

export function AuditLogsAdmin() {
  const [view, setView] = useState<AuditLogView>(initialAuditLogView)
  const selectView = (next: AuditLogView) => {
    setView(next)
    const url = new URL(window.location.href)
    url.searchParams.set('page', 'admin')
    url.searchParams.set('adminSection', 'auditLogs')
    url.searchParams.set('adminView', next)
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
  }
  return <section className="grid gap-3">
    <header className="rounded-enterprise border border-slate-300 border-l-4 border-l-blue-700 bg-slate-50 p-4">
      <span className="text-[10px] font-black tracking-[.14em] text-enterprise-blue uppercase">Admin only · governed audit read</span>
      <h2 className="my-1 text-lg font-black text-navy-900">Audit/Log 조회</h2>
      <p className="m-0 text-xs leading-5 text-slate-600">메타데이터 변경 이력과 인증·접근 보안 이력을 한 화면에서 전환합니다. 두 로그는 보존 범위와 민감 필드가 달라 서버의 별도 권한 계약을 유지합니다.</p>
    </header>
    <div className="flex gap-1 border-b border-slate-300 pb-2" role="tablist" aria-label="Audit/Log 조회 종류">
      <button type="button" role="tab" aria-selected={view === 'metadata'} className={`button ${view === 'metadata' ? '' : 'button-secondary'}`} onClick={() => selectView('metadata')}>메타데이터 변경 로그</button>
      <button type="button" role="tab" aria-selected={view === 'security'} className={`button ${view === 'security' ? '' : 'button-secondary'}`} onClick={() => selectView('security')}>시스템 보안 로그</button>
    </div>
    <div role="tabpanel">{view === 'metadata' ? <MetadataLogsAdmin /> : <SecurityLogsAdmin />}</div>
  </section>
}

export function MetadataLogsAdmin() {
  return <section className="grid gap-4 rounded-enterprise border border-slate-300 bg-white p-4 shadow-sm">
    <header><span className="text-[10px] font-black tracking-[.14em] text-enterprise-blue uppercase">Admin only</span><h2 className="my-1 text-lg font-black text-navy-900">메타데이터 변경 로그</h2></header>
    <label className="flex max-w-xl items-center gap-2 border border-slate-300 px-3 text-xs font-bold"><Search size={14} /><input className="min-w-0 flex-1 border-0 py-2" disabled placeholder="테이블명, 작업자 검색" /></label>
    <DenseDataTable caption="메타데이터 변경 로그" columns={metadataColumns} data={[]} getRowId={(row) => row.id} emptyMessage="조회 가능한 변경 로그 API가 아직 없습니다." />
    <GovernedUnavailable title="감사 로그 읽기 계약 미구현" description="감사 원장은 백엔드에 존재하지만, 현재 권한 필터·보존 정책·민감 필드 마스킹을 적용한 관리자 조회 API가 없습니다. 브라우저가 DB나 로그 저장소를 직접 조회하지 않습니다." />
  </section>
}

export function SecurityLogsAdmin() {
  return <section className="grid gap-4 rounded-enterprise border border-slate-300 bg-white p-4 shadow-sm">
    <header className="flex flex-wrap items-start justify-between gap-3"><div><span className="text-[10px] font-black tracking-[.14em] text-enterprise-blue uppercase">Admin only</span><h2 className="my-1 text-lg font-black text-navy-900">시스템 보안 로그</h2></div><button type="button" className="button button-secondary" disabled title="권한 필터된 보안 로그 export API가 아직 없습니다."><Download size={14} /> CSV 내보내기</button></header>
    <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_180px]"><label className="flex items-center gap-2 border border-slate-300 px-3 text-xs font-bold"><Search size={14} /><input className="min-w-0 flex-1 border-0 py-2" disabled placeholder="사용자 ID, 타겟 검색" /></label><label className="grid gap-1 text-xs font-bold">기간 지정<input type="date" disabled /></label></div>
    <DenseDataTable caption="시스템 보안 로그" columns={securityColumns} data={[]} getRowId={(row) => row.id} emptyMessage="조회 가능한 보안 로그 API가 아직 없습니다." />
    <GovernedUnavailable title="보안 로그 조회·내보내기 계약 미구현" description="IP 주소와 인증 이벤트는 민감 정보입니다. 범위 제한, 마스킹, 내보내기 감사 증거를 갖춘 서버 API가 추가되기 전에는 화면에 값을 채우지 않습니다." />
  </section>
}

interface VocabularyRow {
  id: string
  term: string
  mapping: string
  scope: 'TERM' | 'TAG'
}

export function DictionaryAdmin({ client }: { client: ApiClient }) {
  const [query, setQuery] = useState('')
  const [tab, setTab] = useState<'ALL' | 'TERM' | 'TAG'>('ALL')
  const [rows, setRows] = useState<VocabularyRow[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<unknown>()
  const load = useCallback(async () => {
    const kinds: Array<'TERM' | 'TAG'> = tab === 'ALL' ? ['TERM', 'TAG'] : [tab]
    setLoading(true); setError(undefined)
    try {
      const results = await Promise.all(kinds.map(async (kind) => ({ kind, result: await client.request<CatalogVocabulary>(`/catalog/vocabulary?kind=${kind}&q=${encodeURIComponent(query.trim())}&limit=50`) })))
      setRows(results.flatMap(({ kind, result }) => result.items.map((item) => ({ id: `${kind}:${item}`, term: item, mapping: '—', scope: kind }))))
    } catch (next) { setError(next) } finally { setLoading(false) }
  }, [client, query, tab])
  useEffect(() => { const timer = window.setTimeout(() => { void load() }, 180); return () => window.clearTimeout(timer) }, [load])
  const exportJson = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(rows, null, 2)], { type: 'application/json' }))
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'datariver-vocabulary-projection.json'; anchor.click(); URL.revokeObjectURL(url)
  }
  const columns = useMemo<ColumnDef<VocabularyRow>[]>(() => [
    { accessorKey: 'term', header: '용어명', size: 350, cell: ({ row }) => <code className="text-xs">{row.original.term}</code> },
    { accessorKey: 'mapping', header: '매핑명', size: 260 },
    { accessorKey: 'scope', header: '적용범위', size: 130, cell: ({ row }) => <span className="badge badge-soft">{row.original.scope}</span> },
    { id: 'manage', header: '관리', size: 150, enableSorting: false, cell: () => <div className="flex gap-1"><button type="button" className="button button-secondary" disabled>편집</button><button type="button" className="button button-secondary" disabled>삭제</button></div> },
  ], [])
  return <section className="grid gap-4 rounded-enterprise border border-slate-300 bg-white p-4 shadow-sm">
    <header className="flex flex-wrap items-start justify-between gap-3"><div><span className="text-[10px] font-black tracking-[.14em] text-enterprise-blue uppercase">Admin only · governed projection</span><h2 className="my-1 text-lg font-black text-navy-900">용어사전</h2></div><div className="flex gap-2"><button type="button" className="button button-secondary" disabled={!rows.length} onClick={exportJson}><Download size={14} /> JSON 내보내기</button><button type="button" className="button" disabled title="용어 매핑 mutation API가 아직 없습니다."><Plus size={14} /> 신규 매핑 추가</button></div></header>
    <div className="flex flex-wrap items-center gap-2"><label className="flex min-w-72 flex-1 items-center gap-2 border border-slate-300 px-3 text-xs font-bold"><Search size={14} /><input className="min-w-0 flex-1 border-0 py-2" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="용어명, 매핑명으로 검색" /></label><div className="flex gap-1" role="tablist" aria-label="용어 범위">{([['ALL', '전체'], ['TERM', '필드명'], ['TAG', '태그/용어']] as const).map(([id, label]) => <button key={id} type="button" role="tab" aria-selected={tab === id} className={`button ${tab === id ? '' : 'button-secondary'}`} onClick={() => setTab(id)}>{label}</button>)}</div></div>
    <ErrorNotice error={error} />
    <DenseDataTable caption="권한 범위 용어 프로젝션" columns={columns} data={rows} getRowId={(row) => row.id} loading={loading} emptyMessage="현재 권한 범위에 표시할 용어가 없습니다." />
    <GovernedUnavailable compact title="매핑 편집·삭제 API 미구현" description="표에는 Catalog가 권한 필터링해 제공한 TERM/TAG projection만 표시합니다. 전역 매핑 정본과 변경 워크플로가 없으므로 매핑명은 추정하지 않고 변경 버튼도 활성화하지 않습니다." />
  </section>
}
