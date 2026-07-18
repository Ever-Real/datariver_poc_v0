import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { Search } from 'lucide-react'
import { ApiError, newIdempotencyKey, type ApiClient } from '../../api/client'
import type { ChangeRequestRecord, ChangeRequestState } from '../../api/types'
import { pageUrl } from '../../app/navigation'
import { AssuranceNotice, type AssuranceActions } from '../../components/AssuranceNotice'
import { ErrorNotice } from '../../components/ErrorNotice'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import { TruncatedText } from '../../components/common/TruncatedText'
import { PageTitle } from '../../components/layout/PageTitle'
import { ChangeActionConfirmDialog } from './ChangeActionConfirmDialog'
import { ChangeRequestDetailDialog } from './ChangeRequestDetailDialog'
import {
  changeStateLabel,
  changeStateOptions,
  type ChangeActionHint,
} from './changePresentation'

const DEFAULT_REASON = '검토 기준과 현재 대상 증거를 확인했습니다.'

const columns: ColumnDef<ChangeRequestRecord>[] = [
  {
    accessorKey: 'number',
    header: 'CR-No',
    size: 155,
    enableSorting: false,
    cell: ({ row }) => <TruncatedText value={row.original.number} className="governance-request-number" />,
  },
  {
    accessorKey: 'title',
    header: 'CR명',
    size: 300,
    enableSorting: false,
    cell: ({ row }) => <TruncatedText value={row.original.title} className="governance-request-title" />,
  },
  {
    id: 'aspect',
    header: '변경 Aspect',
    size: 145,
    enableSorting: false,
    cell: ({ row }) => <TruncatedText value={row.original.items[0]?.aspect_name ?? '—'} />,
  },
  {
    accessorKey: 'state',
    header: '상태',
    size: 175,
    enableSorting: false,
    cell: ({ row }) => (
      <span className={`badge governance-state state-${row.original.state.toLowerCase()}`}>
        {changeStateLabel(row.original.state)} · {row.original.state}
      </span>
    ),
  },
  {
    accessorKey: 'classification',
    header: '등급',
    size: 115,
    enableSorting: false,
  },
  {
    accessorKey: 'requester_id',
    header: '요청자',
    size: 235,
    enableSorting: false,
    cell: ({ row }) => <TruncatedText value={row.original.requester_id} />,
  },
  {
    accessorKey: 'version',
    header: '버전',
    size: 70,
    enableSorting: false,
  },
]

export function GovernancePage({
  client,
  onStepUp,
  onPasswordReauth,
  onEnroll,
}: { client: ApiClient } & AssuranceActions) {
  const [stateFilter, setStateFilter] = useState<'' | ChangeRequestState>('')
  const [textFilter, setTextFilter] = useState('')
  const [requests, setRequests] = useState<ChangeRequestRecord[]>([])
  const [listLoading, setListLoading] = useState(true)
  const [listError, setListError] = useState<unknown>()
  const [selectedId, setSelectedId] = useState<string>()
  const [detail, setDetail] = useState<ChangeRequestRecord>()
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<unknown>()
  const [actionError, setActionError] = useState<unknown>()
  const [pendingAction, setPendingAction] = useState<ChangeActionHint>()
  const [reason, setReason] = useState(DEFAULT_REASON)
  const [busy, setBusy] = useState(false)
  const generation = useRef(0)
  const listIntent = useRef(0)
  const detailIntent = useRef(0)
  const controllers = useRef(new Set<AbortController>())
  const detailController = useRef<AbortController | undefined>(undefined)

  const beginOperation = useCallback(() => {
    const controller = new AbortController()
    controllers.current.add(controller)
    return { controller, expectedGeneration: generation.current }
  }, [])

  const listPath = useMemo(() => (
    stateFilter
      ? `/change-requests?state=${encodeURIComponent(stateFilter)}&limit=50`
      : '/change-requests?limit=50'
  ), [stateFilter])

  const loadRequests = useCallback(async () => {
    const intent = ++listIntent.current
    const { controller, expectedGeneration } = beginOperation()
    setListLoading(true)
    setListError(undefined)
    try {
      const value = await client.request<{ items: ChangeRequestRecord[] }>(listPath, {
        signal: controller.signal,
      })
      if (controller.signal.aborted || expectedGeneration !== generation.current || intent !== listIntent.current) return
      setRequests(value.items)
    } catch (error) {
      if (!controller.signal.aborted && expectedGeneration === generation.current && intent === listIntent.current) {
        setListError(error)
      }
    } finally {
      controllers.current.delete(controller)
      if (expectedGeneration === generation.current && intent === listIntent.current) setListLoading(false)
    }
  }, [beginOperation, client, listPath])

  useEffect(() => {
    const activeControllers = controllers.current
    generation.current += 1
    listIntent.current += 1
    detailIntent.current += 1
    activeControllers.forEach((controller) => controller.abort())
    activeControllers.clear()
    detailController.current = undefined
    setRequests([])
    setListError(undefined)
    setListLoading(true)
    setSelectedId(undefined)
    setDetail(undefined)
    setDetailError(undefined)
    setActionError(undefined)
    setPendingAction(undefined)
    setReason(DEFAULT_REASON)
    setBusy(false)
    void loadRequests()
    return () => {
      generation.current += 1
      listIntent.current += 1
      detailIntent.current += 1
      activeControllers.forEach((controller) => controller.abort())
      activeControllers.clear()
      detailController.current = undefined
    }
  }, [client, listPath, loadRequests])

  const loadDetail = useCallback(async (changeRequestId: string) => {
    detailController.current?.abort()
    const intent = ++detailIntent.current
    const { controller, expectedGeneration } = beginOperation()
    detailController.current = controller
    setSelectedId(changeRequestId)
    setDetail(undefined)
    setDetailLoading(true)
    setDetailError(undefined)
    try {
      const value = await client.request<ChangeRequestRecord>(`/change-requests/${changeRequestId}`, {
        signal: controller.signal,
      })
      if (controller.signal.aborted || expectedGeneration !== generation.current || intent !== detailIntent.current) return
      setDetail(value)
      setRequests((current) => current.map((item) => item.id === value.id ? value : item))
    } catch (error) {
      if (!controller.signal.aborted && expectedGeneration === generation.current && intent === detailIntent.current) {
        setDetailError(error)
      }
    } finally {
      controllers.current.delete(controller)
      if (detailController.current === controller) detailController.current = undefined
      if (expectedGeneration === generation.current && intent === detailIntent.current) setDetailLoading(false)
    }
  }, [beginOperation, client])

  const openDetail = useCallback((changeRequest: ChangeRequestRecord) => {
    setActionError(undefined)
    setReason(DEFAULT_REASON)
    void loadDetail(changeRequest.id)
  }, [loadDetail])

  const closeDetail = useCallback(() => {
    detailController.current?.abort()
    detailController.current = undefined
    detailIntent.current += 1
    setSelectedId(undefined)
    setDetail(undefined)
    setDetailLoading(false)
    setDetailError(undefined)
    setActionError(undefined)
    setPendingAction(undefined)
    setReason(DEFAULT_REASON)
  }, [])

  const openAction = useCallback((action: ChangeActionHint) => {
    setActionError(undefined)
    setPendingAction(action)
  }, [])
  const cancelAction = useCallback(() => setPendingAction(undefined), [])

  const confirmAction = async () => {
    const action = pendingAction
    const current = detail
    if (!action || !current || busy || !reason.trim()) return
    const { controller, expectedGeneration } = beginOperation()
    setBusy(true)
    setActionError(undefined)
    try {
      const path = action.kind === 'APPROVAL'
        ? `/change-requests/${current.id}/approvals`
        : `/change-requests/${current.id}/transitions`
      const body = action.kind === 'APPROVAL'
        ? { stage: action.stage, decision: action.decision, reason }
        : { target_state: action.targetState, reason }
      const next = await client.request<ChangeRequestRecord>(path, {
        method: 'POST',
        idempotencyKey: newIdempotencyKey('change-action'),
        ifMatch: `"${current.version}"`,
        signal: controller.signal,
        body: JSON.stringify(body),
      })
      if (controller.signal.aborted || expectedGeneration !== generation.current) return
      setPendingAction(undefined)
      setDetail(next)
      setRequests((values) => {
        if (stateFilter && next.state !== stateFilter) return values.filter((item) => item.id !== next.id)
        return values.map((item) => item.id === next.id ? next : item)
      })
      setReason(DEFAULT_REASON)
    } catch (error) {
      if (controller.signal.aborted || expectedGeneration !== generation.current) return
      setPendingAction(undefined)
      setActionError(error)
      if (error instanceof ApiError && error.problem.status === 409) {
        await loadDetail(current.id)
      }
    } finally {
      controllers.current.delete(controller)
      if (expectedGeneration === generation.current) setBusy(false)
    }
  }

  const fallback = selectedId ? requests.find((item) => item.id === selectedId) : undefined
  const visibleRequests = useMemo(() => {
    const query = textFilter.trim().toLocaleLowerCase()
    if (!query) return requests
    return requests.filter((request) => [
      request.number, request.title, request.requester_id, request.items[0]?.aspect_name ?? '', request.classification,
    ].some((value) => value.toLocaleLowerCase().includes(query)))
  }, [requests, textFilter])
  const summary = useMemo(() => [
    { label: '전체', count: requests.length, state: '' as const },
    { label: '검토 필요', count: requests.filter((item) => ['REGISTERED', 'IN_REVIEW', 'FINAL_REVIEW', 'CHANGES_REQUESTED'].includes(item.state)).length, state: 'IN_REVIEW' as const },
    { label: '적용 중', count: requests.filter((item) => ['APPLY_QUEUED', 'APPLYING', 'APPLY_FAILED'].includes(item.state)).length, state: 'APPLYING' as const },
    { label: '적용 완료', count: requests.filter((item) => item.state === 'APPLIED').length, state: 'APPLIED' as const },
  ], [requests])

  return (
    <section className="governance-page">
      <PageTitle
        icon="CR"
        eyebrow="Four-eyes Governance"
        title="변경 요청과 승인"
        description="타입이 지정된 변경을 검토하고 Maker-Checker 상태 전이와 적용 증거를 관리합니다."
        actions={<button type="button" className="button button-secondary" disabled={listLoading} onClick={() => void loadRequests()}>새로고침</button>}
      />

      <div className="governance-toolbar panel">
        <div className="governance-window-summary" aria-live="polite">
          <span className="governance-kicker">Authorized window</span>
          <strong>현재 조회된 요청 · 최대 50건</strong>
          <small>{listLoading ? '서버에서 권한 범위를 확인하는 중' : `${requests.length.toLocaleString()}건 표시`}</small>
        </div>
        <label className="governance-state-filter">
          <span>상태 필터</span>
          <select value={stateFilter} onChange={(event) => setStateFilter(event.target.value as '' | ChangeRequestState)}>
            {changeStateOptions.map((option) => <option key={option.value || 'all'} value={option.value}>{option.label}</option>)}
          </select>
        </label>
        <label className="governance-text-filter">
          <span>요청 검색</span>
          <div><Search size={13} aria-hidden="true" /><input value={textFilter} onChange={(event) => setTextFilter(event.target.value)} placeholder="CR 번호, 제목, 요청자" maxLength={300} /></div>
        </label>
        <div className="governance-registration-link">
          <span>새 변경 요청은 서버 검증 미리보기에서 시작합니다.</span>
          <a className="button" href={pageUrl('registration')}>등록관리에서 설명 변경 제안</a>
        </div>
      </div>

      <section className="governance-status-overview" aria-label="현재 조회 창의 변경요청 상태 요약">
        {summary.map((item) => <button key={item.label} type="button" className={stateFilter === item.state ? 'active' : ''} onClick={() => setStateFilter(item.state)}><span>{item.label}</span><strong>{item.count.toLocaleString()}</strong><small>현재 권한 창</small></button>)}
      </section>

      <AssuranceNotice
        error={listError}
        onStepUp={onStepUp}
        onPasswordReauth={onPasswordReauth}
        onEnroll={onEnroll}
      />
      <ErrorNotice error={listError} />

      <section className="governance-list-panel panel" aria-labelledby="governance-list-heading">
        <header>
          <div>
            <span className="governance-kicker">Change requests</span>
            <h2 id="governance-list-heading">변경 요청 목록</h2>
          </div>
          <p>행을 클릭하거나 Enter/Space로 열면 서버가 상세 권한을 다시 확인합니다. 검색은 현재 서버 권한 창 안에서만 필터링합니다.</p>
        </header>
        <DenseDataTable
          caption="현재 권한 범위의 변경 요청"
          columns={columns}
          data={visibleRequests}
          getRowId={(item) => item.id}
          loading={listLoading}
          emptyMessage={textFilter ? '현재 권한 창에서 검색 조건에 맞는 요청이 없습니다.' : stateFilter ? '선택한 상태에서 조회 가능한 요청이 없습니다.' : '현재 권한 범위에서 조회 가능한 요청이 없습니다.'}
          selectedRowId={selectedId}
          onRowActivate={openDetail}
        />
      </section>

      <ChangeRequestDetailDialog
        open={Boolean(selectedId)}
        fallback={fallback}
        value={detail}
        loading={detailLoading}
        busy={busy}
        error={detailError}
        actionError={actionError}
        onClose={closeDetail}
        onRefresh={() => { if (selectedId) void loadDetail(selectedId) }}
        onAction={openAction}
        onStepUp={onStepUp}
        onPasswordReauth={onPasswordReauth}
        onEnroll={onEnroll}
      />
      <ChangeActionConfirmDialog
        action={pendingAction}
        changeRequest={detail}
        reason={reason}
        busy={busy}
        onReasonChange={setReason}
        onCancel={cancelAction}
        onConfirm={() => void confirmAction()}
      />
    </section>
  )
}
