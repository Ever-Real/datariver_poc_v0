import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import type { SystemConfigurationEntry } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import type {
  AdminApi,
  AirflowDagInventory,
  AirflowDagStatus,
} from './adminApi'
import type { PendingAdminMutation } from './AdminMutationConfirmDialog'

function timestamp(value: string | null) {
  if (!value) return '없음'
  const milliseconds = Date.parse(value)
  return Number.isFinite(milliseconds) ? new Date(milliseconds).toLocaleString() : '확인 불가'
}

function operationKey(action: string, dagId: string) {
  return `airflow-${action.toLowerCase()}-${dagId}-${globalThis.crypto.randomUUID()}`
}

export function AirflowDagStatusPanel({
  api,
  configuration,
  requestConfirmation,
}: {
  api: AdminApi
  configuration: SystemConfigurationEntry
  requestConfirmation: (mutation: PendingAdminMutation) => void
}) {
  const [inventory, setInventory] = useState<AirflowDagInventory>()
  const [loading, setLoading] = useState(true)
  const [activeOperation, setActiveOperation] = useState<string>()
  const [notice, setNotice] = useState<string>()
  const [error, setError] = useState<unknown>()
  const request = useRef<{ generation: number; controller?: AbortController }>({ generation: 0 })
  const retryKeys = useRef(new Map<string, string>())
  const inFlightOperations = useRef(new Set<string>())

  const load = useCallback(async () => {
    request.current.controller?.abort()
    const controller = new AbortController()
    const generation = request.current.generation + 1
    request.current = { generation, controller }
    setLoading(true)
    setError(undefined)
    try {
      const nextInventory = await api.getAirflowDagInventory(controller.signal)
      if (!controller.signal.aborted && request.current.generation === generation) {
        setInventory(nextInventory)
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

  const applyOperation = useCallback(async (
    dag: AirflowDagStatus,
    action: 'TRIGGER' | 'PAUSE' | 'UNPAUSE',
  ) => {
    const operation = `${action}:${dag.dag_id}`
    if (inFlightOperations.current.has(operation)) return
    inFlightOperations.current.add(operation)
    const key = retryKeys.current.get(operation) ?? operationKey(action, dag.dag_id)
    retryKeys.current.set(operation, key)
    setActiveOperation(operation)
    setNotice(undefined)
    setError(undefined)
    try {
      if (action === 'TRIGGER') {
        const result = await api.triggerAirflowDag(dag.dag_id, key)
        setNotice(`${dag.dag_id} 실행이 ${result.receipt.state === 'ACCEPTED' ? '접수' : '조정'}되었습니다.`)
      } else {
        await api.transitionAirflowDag(dag.dag_id, action, key)
        setNotice(`${dag.dag_id}을(를) ${action === 'PAUSE' ? '일시 중지' : '재개'}했습니다.`)
      }
      retryKeys.current.delete(operation)
      await load()
    } catch (next) {
      setError(next)
    } finally {
      inFlightOperations.current.delete(operation)
      setActiveOperation(undefined)
    }
  }, [api, load])

  const requestOperation = useCallback((
    dag: AirflowDagStatus,
    action: 'TRIGGER' | 'PAUSE' | 'UNPAUSE',
  ) => {
    const actionLabel = action === 'TRIGGER' ? '실행' : action === 'PAUSE' ? '일시 중지' : '재개'
    requestConfirmation({
      title: `Airflow DAG ${actionLabel}`,
      summary: [
        `System configuration ID: ${configuration.system_id}`,
        `검토된 DAG: ${dag.dag_id}`,
        `작업: ${action}`,
        '확인 후 동일한 멱등성 키로 내구성 있는 작업 receipt를 기록합니다.',
      ],
      execute: () => applyOperation(dag, action),
    })
  }, [applyOperation, configuration.system_id, requestConfirmation])

  const columns = useMemo<ColumnDef<AirflowDagStatus>[]>(() => [
    {
      accessorKey: 'dag_id',
      header: 'DAG ID',
      size: 260,
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
      id: 'latest_run',
      header: '최근 실행',
      size: 130,
      cell: ({ row }) => row.original.latest_run
        ? <span className="badge badge-soft">{row.original.latest_run.state}</span>
        : '없음',
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
      header: '다음 실행 / 논리 시각',
      size: 210,
      cell: ({ row }) => (
        <span>
          {timestamp(row.original.next_run_at)}
          {row.original.next_logical_date && (
            <small className="block text-slate-500">논리 {timestamp(row.original.next_logical_date)}</small>
          )}
        </span>
      ),
    },
    {
      id: 'operations',
      header: '관리',
      size: 220,
      cell: ({ row }) => {
        const dag = row.original
        if (dag.state !== 'READY') return '—'
        const pauseAction = dag.paused ? 'UNPAUSE' : 'PAUSE'
        return (
          <div className="flex flex-wrap gap-2">
            <button
              className="button button-secondary"
              disabled={Boolean(activeOperation)}
              onClick={() => requestOperation(dag, 'TRIGGER')}
              type="button"
            >
              {activeOperation === `TRIGGER:${dag.dag_id}` ? '접수 중…' : 'DAG 실행'}
            </button>
            <button
              className="button button-secondary"
              disabled={Boolean(activeOperation)}
              onClick={() => requestOperation(dag, pauseAction)}
              type="button"
            >
              {activeOperation === `${pauseAction}:${dag.dag_id}`
                ? '변경 중…'
                : pauseAction === 'PAUSE' ? '일시 중지' : '재개'}
            </button>
          </div>
        )
      },
    },
  ], [activeOperation, requestOperation])

  return (
    <section className="grid gap-3 rounded-enterprise border border-slate-300 bg-slate-50 p-3" aria-label="검토된 Airflow DAG 상태">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <span className="eyebrow">Bounded Airflow control</span>
          <h5 className="m-0 text-sm font-black text-navy-900">Airflow DAG 상태</h5>
          <p className="m-0 text-xs leading-5 text-slate-600">
            canonical 시스템 구성에서 선택한 Airflow와 검토된 DAG만 관리합니다. 자격증명 값과 임의 DAG ID는 브라우저에 노출하지 않습니다.
          </p>
        </div>
        <button className="button button-secondary" disabled={loading || Boolean(activeOperation)} onClick={() => void load()} type="button">
          {loading ? 'DAG 상태 확인 중…' : 'DAG 상태 새로고침'}
        </button>
      </header>
      <dl className="summary-list" aria-label="Canonical Airflow 시스템 구성">
        <div><dt>구성 ID</dt><dd><code>{configuration.system_id}</code></dd></div>
        <div><dt>관리 원천</dt><dd><code>/admin/system-configuration</code></dd></div>
        <div><dt>버전</dt><dd>{configuration.version}</dd></div>
        <div><dt>활성화</dt><dd>{configuration.activation_state}</dd></div>
      </dl>
      {inventory && (
        <div className="flex flex-wrap gap-2" role="status" aria-label="Airflow DAG 조회 정보">
          <span className="badge">Config {inventory.system_id}</span>
          <span className="badge">API {inventory.api_mode}</span>
          <span className="badge badge-soft">확인 시각 {timestamp(inventory.observed_at)}</span>
        </div>
      )}
      {notice && <p className="callout m-0" role="status">{notice}</p>}
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
        실행은 비밀값 없는 고정 요청과 내구성 있는 멱등성·감사·실패 조정 receipt를 사용합니다. 실제 외부 Airflow 연결 검증은 별도 런타임 승인 게이트입니다.
      </p>
    </section>
  )
}
