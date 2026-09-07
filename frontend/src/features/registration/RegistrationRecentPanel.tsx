import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { CheckCircle2, Clock3, LoaderCircle, RefreshCw, TriangleAlert } from 'lucide-react'
import type { ApiClient } from '../../api/client'
import type {
  ManualMetadataSubmissionList,
  ManualMetadataSubmissionReport,
  ManualMetadataSubmissionStatus,
  UploadPreparation,
  UploadRecord,
} from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'

type RunType = 'MANUAL' | 'BULK'
type StatusFilter = 'ALL' | 'SUCCESS' | 'IN_PROGRESS' | 'FAILED'
type PeriodFilter = 'ALL' | '1D' | '7D' | '30D'

interface RecentRun {
  id: string
  type: RunType
  title: string
  state: string
  createdAt?: string
  createdBy?: string
  assetId?: string
  upload?: UploadRecord
  manual?: ManualMetadataSubmissionStatus
}

function isSuccessful(state: string): boolean {
  return ['APPLIED', 'ACCEPTED', 'READY'].includes(state)
}

function isFailed(state: string): boolean {
  return ['FAILED', 'REJECTED', 'CANCELLED', 'STALE'].includes(state)
}

function isInProgress(state: string): boolean {
  return ['QUEUED', 'APPLYING', 'INITIATED', 'UPLOADING', 'PREPARING'].includes(state)
}

function formatTimestamp(value: string | undefined): string {
  if (!value) return '기록 없음'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '기록 없음'
  return new Intl.DateTimeFormat('ko-KR', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(parsed)
}

function RunState({ state }: { state: string }) {
  if (isSuccessful(state)) return <><CheckCircle2 size={14} className="text-success" />{state}</>
  if (isFailed(state)) return <><TriangleAlert size={14} className="text-danger" />{state}</>
  if (isInProgress(state)) return <><LoaderCircle size={14} className="text-muted spin" />{state}</>
  return <><Clock3 size={14} className="text-muted" />{state}</>
}

export function RegistrationRecentPanel({
  client,
  canViewWorkspaceHistory,
}: {
  client: ApiClient
  canViewWorkspaceHistory: boolean
}) {
  const [manualRecords, setManualRecords] = useState<ManualMetadataSubmissionStatus[]>([])
  const [bulkRecords, setBulkRecords] = useState<UploadRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<unknown>()
  const [refresh, setRefresh] = useState(0)
  const [filterType, setFilterType] = useState<'ALL' | RunType>('ALL')
  const [filterState, setFilterState] = useState<StatusFilter>('ALL')
  const [filterPeriod, setFilterPeriod] = useState<PeriodFilter>('ALL')
  const [filterExecutor, setFilterExecutor] = useState('ALL')
  const [observedAt, setObservedAt] = useState(0)
  const [selected, setSelected] = useState<RecentRun>()
  const [manualReport, setManualReport] = useState<ManualMetadataSubmissionReport>()
  const [preparations, setPreparations] = useState<UploadPreparation[]>([])
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<unknown>()
  const detailController = useRef<AbortController | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    const scope = canViewWorkspaceHistory ? 'workspace' : 'mine'
    setLoading(true)
    setError(undefined)
    setObservedAt(Date.now())
    void Promise.all([
      client.request<ManualMetadataSubmissionList>(
        `/registration/manual-submissions?scope=${scope}&limit=100`,
        { signal: controller.signal },
      ),
      client.request<{ items: UploadRecord[] }>('/uploads?limit=100', {
        signal: controller.signal,
      }),
    ]).then(([manual, bulk]) => {
      if (controller.signal.aborted) return
      setManualRecords(Array.isArray(manual.items) ? manual.items : [])
      setBulkRecords(Array.isArray(bulk.items) ? bulk.items : [])
    }).catch((next: unknown) => {
      if (!controller.signal.aborted) setError(next)
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false)
    })
    return () => controller.abort()
  }, [canViewWorkspaceHistory, client, refresh])

  const combined = useMemo<RecentRun[]>(() => [
    ...manualRecords.map((manual) => ({
      id: manual.id,
      type: 'MANUAL' as const,
      title: manual.asset_id || `Manual #${manual.serial_number}`,
      state: manual.state,
      createdAt: manual.created_at,
      createdBy: manual.created_by,
      assetId: manual.asset_id,
      manual,
    })),
    ...bulkRecords.map((upload) => ({
      id: upload.id,
      type: 'BULK' as const,
      title: upload.display_name || upload.id,
      state: upload.state,
      createdAt: upload.created_at,
      createdBy: upload.created_by,
      upload,
    })),
  ].sort((left, right) => {
    const leftTime = left.createdAt ? new Date(left.createdAt).getTime() : 0
    const rightTime = right.createdAt ? new Date(right.createdAt).getTime() : 0
    return rightTime - leftTime
  }), [bulkRecords, manualRecords])

  const executors = useMemo(() => Array.from(new Set(
    combined.flatMap((record) => record.createdBy ? [record.createdBy] : []),
  )).sort(), [combined])

  const filtered = useMemo(() => combined.filter((record) => {
    if (filterType !== 'ALL' && record.type !== filterType) return false
    if (filterExecutor !== 'ALL' && record.createdBy !== filterExecutor) return false
    if (filterState === 'SUCCESS' && !isSuccessful(record.state)) return false
    if (filterState === 'FAILED' && !isFailed(record.state)) return false
    if (filterState === 'IN_PROGRESS' && !isInProgress(record.state)) return false
    if (filterPeriod !== 'ALL') {
      if (!record.createdAt) return false
      const timestamp = new Date(record.createdAt).getTime()
      if (Number.isNaN(timestamp)) return false
      const maximumDays = filterPeriod === '1D' ? 1 : filterPeriod === '7D' ? 7 : 30
      if (observedAt - timestamp > maximumDays * 86_400_000) return false
    }
    return true
  }), [combined, filterExecutor, filterPeriod, filterState, filterType, observedAt])

  const openDetail = useCallback((record: RecentRun) => {
    detailController.current?.abort()
    const controller = new AbortController()
    detailController.current = controller
    setSelected(record)
    setManualReport(undefined)
    setPreparations([])
    setDetailLoading(true)
    setDetailError(undefined)
    const request = record.type === 'MANUAL'
      ? client.request<ManualMetadataSubmissionReport>(
          `/registration/manual-submissions/${record.id}`,
          { signal: controller.signal },
        ).then(setManualReport)
      : client.request<{ items: UploadPreparation[] }>(
          `/uploads/${record.id}/preparations?limit=20`,
          { signal: controller.signal },
        ).then((result) => setPreparations(Array.isArray(result.items) ? result.items : []))
    void request.catch((next: unknown) => {
      if (!controller.signal.aborted) setDetailError(next)
    }).finally(() => {
      if (!controller.signal.aborted) setDetailLoading(false)
      if (detailController.current === controller) detailController.current = null
    })
  }, [client])

  useEffect(() => {
    detailController.current?.abort()
    setSelected(undefined)
    setManualReport(undefined)
    setPreparations([])
    setDetailError(undefined)
    return () => detailController.current?.abort()
  }, [client])

  return (
    <aside className="registration-recent-panel" aria-labelledby="registration-recent-title">
      <header className="registration-recent-header">
        <div>
          <span className="eyebrow">History</span>
          <h2 id="registration-recent-title">등록 실행 이력</h2>
        </div>
        <button
          type="button"
          className="button button-quiet"
          aria-label="최근 실행 새로고침"
          onClick={() => setRefresh((current) => current + 1)}
          disabled={loading}
        ><RefreshCw size={13} />새로고침</button>
      </header>

      <div className="registration-recent-filters">
        <select aria-label="실행 유형 필터" value={filterType} onChange={(event) => setFilterType(event.target.value as 'ALL' | RunType)}>
          <option value="ALL">전체 유형</option><option value="MANUAL">Manual</option><option value="BULK">Bulk</option>
        </select>
        <select aria-label="상태 필터" value={filterState} onChange={(event) => setFilterState(event.target.value as StatusFilter)}>
          <option value="ALL">전체 상태</option><option value="SUCCESS">성공</option><option value="IN_PROGRESS">진행 중</option><option value="FAILED">실패</option>
        </select>
        <select aria-label="기간 필터" value={filterPeriod} onChange={(event) => setFilterPeriod(event.target.value as PeriodFilter)}>
          <option value="ALL">전체 기간</option><option value="1D">최근 1일</option><option value="7D">최근 7일</option><option value="30D">최근 30일</option>
        </select>
        <select aria-label="실행자 필터" value={filterExecutor} onChange={(event) => setFilterExecutor(event.target.value)}>
          <option value="ALL">전체 실행자</option>
          {executors.map((executor) => <option key={executor} value={executor}>{executor}</option>)}
        </select>
      </div>

      <ErrorNotice error={error} />
      {loading ? <p role="status">최근 실행을 불러오는 중…</p> : (
        <ul className="registration-recent-list" aria-label="최근 등록 실행">
          {filtered.map((record) => (
            <li key={`${record.type}-${record.id}`}>
              <button
                type="button"
                className={selected?.id === record.id && selected.type === record.type ? 'active' : ''}
                onClick={() => openDetail(record)}
              >
                <span className="badge">{record.type}</span>
                <span className="registration-recent-run-copy"><strong>{record.title}</strong><small>{formatTimestamp(record.createdAt)} · {record.createdBy || '실행자 기록 없음'}</small></span>
                <span className="registration-recent-state"><RunState state={record.state} /></span>
              </button>
            </li>
          ))}
          {!filtered.length && <li className="muted">조건에 맞는 실행 이력이 없습니다.</li>}
        </ul>
      )}

      {selected && (
        <section className="registration-recent-detail" aria-labelledby="registration-recent-detail-title">
          <h3 id="registration-recent-detail-title">실행 결과</h3>
          <dl><dt>유형</dt><dd>{selected.type}</dd><dt>상태</dt><dd>{selected.state}</dd><dt>대상</dt><dd>{selected.assetId || selected.title}</dd></dl>
          {detailLoading && <p role="status">실행 영수증을 불러오는 중…</p>}
          <ErrorNotice error={detailError} />
          {manualReport && (
            <div className="registration-recent-receipt">
              <strong>시도 {manualReport.submission.attempts}회 · {manualReport.submission.state}</strong>
              {manualReport.attempts.flatMap((attempt) => attempt.aspects).map((aspect) => (
                <span key={`${aspect.aspect_ordinal}-${aspect.observed_at}`}>{aspect.aspect_name} · {aspect.outcome}{aspect.failure_code ? ` · ${aspect.failure_code}` : ''}</span>
              ))}
              {!manualReport.attempts.length && <span>아직 적용 영수증이 없습니다.</span>}
            </div>
          )}
          {selected.type === 'BULK' && !detailLoading && (
            <div className="registration-recent-receipt">
              {preparations.map((preparation) => <span key={preparation.id}>{preparation.state} · {preparation.rows_processed}/{preparation.total_rows ?? '?'} rows · 시도 {preparation.attempts}회{preparation.last_error_code ? ` · ${preparation.last_error_code}` : ''}</span>)}
              {!preparations.length && <span>아직 준비 작업 영수증이 없습니다.</span>}
            </div>
          )}
        </section>
      )}
    </aside>
  )
}
