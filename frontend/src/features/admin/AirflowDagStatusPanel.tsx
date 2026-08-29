import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { ErrorNotice } from '../../components/ErrorNotice'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import type { AdminApi, AirflowDagInventory, AirflowDagStatus } from './adminApi'

function timestamp(value: string | null) {
  if (!value) return '없음'
  const milliseconds = Date.parse(value)
  return Number.isFinite(milliseconds) ? new Date(milliseconds).toLocaleString() : '확인 불가'
}

export function AirflowDagStatusPanel({ api }: { api: AdminApi }) {
  const [inventory, setInventory] = useState<AirflowDagInventory>()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>()
  const request = useRef<{ generation: number; controller?: AbortController }>({ generation: 0 })

  const load = useCallback(async () => {
    request.current.controller?.abort()
    const controller = new AbortController()
    const generation = request.current.generation + 1
    request.current = { generation, controller }
    setLoading(true)
    setError(undefined)
    try {
      const next = await api.getAirflowDagInventory(controller.signal)
      if (!controller.signal.aborted && request.current.generation === generation) {
        setInventory(next)
      }
    } catch (next) {
      if (!controller.signal.aborted && request.current.generation === generation) {
        setInventory(undefined)
        setError(next)
      }
    } finally {
      if (!controller.signal.aborted && request.current.generation === generation) {
        setLoading(false)
      }
    }
  }, [api])

  useEffect(() => {
    void load()
    return () => request.current.controller?.abort()
  }, [load])

  const columns = useMemo<ColumnDef<AirflowDagStatus>[]>(() => [
    {
      accessorKey: 'dag_id',
      header: 'DAG ID',
      size: 280,
      cell: ({ row }) => <code>{row.original.dag_id}</code>,
    },
    {
      accessorKey: 'state',
      header: '상태',
      size: 100,
      cell: ({ row }) => (
        <span className={`badge ${row.original.state === 'READY' ? '' : 'badge-warning'}`}>
          {row.original.state === 'READY' ? '사용 가능' : '찾을 수 없음'}
        </span>
      ),
    },
    {
      accessorKey: 'paused',
      header: '실행',
      size: 100,
      cell: ({ row }) => row.original.paused === null
        ? '—'
        : row.original.paused
          ? '일시 중지'
          : '활성',
    },
    {
      accessorKey: 'next_run_at',
      header: '다음 실행',
      size: 180,
      cell: ({ row }) => timestamp(row.original.next_run_at),
    },
    {
      accessorKey: 'last_parsed_at',
      header: '마지막 확인',
      size: 180,
      cell: ({ row }) => timestamp(row.original.last_parsed_at),
    },
  ], [])

  return (
    <section className="grid gap-3 rounded-enterprise border border-slate-300 bg-slate-50 p-3" aria-label="검토된 Airflow DAG 상태">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <span className="eyebrow">Read-only reviewed inventory</span>
          <h5 className="m-0 text-sm font-black text-navy-900">Airflow DAG 상태</h5>
          <p className="m-0 text-xs leading-5 text-slate-600">
            서버가 검토한 DAG만 Airflow API에서 읽습니다. 자격증명과 임의 DAG ID는 브라우저에 노출하지 않습니다.
          </p>
        </div>
        <button className="button button-secondary" disabled={loading} onClick={() => void load()} type="button">
          {loading ? 'DAG 상태 확인 중…' : 'DAG 상태 새로고침'}
        </button>
      </header>
      {inventory && (
        <div className="flex flex-wrap gap-2" role="status" aria-label="Airflow DAG 조회 정보">
          <span className="badge">API {inventory.api_mode}</span>
          <span className="badge badge-soft">확인 시각 {timestamp(inventory.observed_at)}</span>
        </div>
      )}
      <ErrorNotice error={error} />
      <DenseDataTable
        caption="검토된 Airflow DAG 목록"
        columns={columns}
        data={inventory?.items ?? []}
        getRowId={(row) => row.dag_id}
        loading={loading}
        emptyMessage="현재 조회 가능한 검토된 DAG가 없습니다."
        fitContainer
      />
      <p className="callout m-0" role="note">
        DAG 실행·중지 변경은 확인·감사·재시도 안전 계약이 마련되기 전까지 이 화면에서 수행하지 않습니다.
      </p>
    </section>
  )
}
