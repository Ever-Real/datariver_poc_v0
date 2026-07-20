import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { Search } from 'lucide-react'
import { ApiError, newIdempotencyKey, type ApiClient } from '../../api/client'
import type {
  ChangeRequestRecord,
  ChangeRequestAttachment,
  ChangeRequestAttachmentList,
  ChangeRequestSchemaOverview,
  ChangeRequestState,
} from '../../api/types'
import type { Page } from '../../app/navigation'
import { AssuranceNotice, type AssuranceActions } from '../../components/AssuranceNotice'
import { ErrorNotice } from '../../components/ErrorNotice'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import { TruncatedText } from '../../components/common/TruncatedText'
import { PageTitle } from '../../components/layout/PageTitle'
import { ChangeActionConfirmDialog } from './ChangeActionConfirmDialog'
import { ChangeRequestCreateDialog } from './ChangeRequestCreateDialog'
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
    size: 230,
    enableSorting: false,
    cell: ({ row }) => <TruncatedText value={row.original.title} className="governance-request-title" />,
  },
  {
    accessorKey: 'request_type',
    header: '유형',
    size: 105,
    enableSorting: false,
  },
  {
    id: 'aspect',
    header: '변경 Aspect',
    size: 145,
    enableSorting: false,
    cell: ({ row }) => <TruncatedText value={row.original.items[0]?.aspect_name ?? '—'} />,
  },
  {
    id: 'target',
    header: '대상 데이터셋',
    size: 230,
    enableSorting: false,
    cell: ({ row }) => <TruncatedText value={row.original.items[0]?.target_ref ?? '—'} />,
  },
  {
    id: 'operation',
    header: '작업',
    size: 105,
    enableSorting: false,
    cell: ({ row }) => <TruncatedText value={row.original.items[0]?.operation ?? '—'} />,
  },
  {
    id: 'items',
    header: '항목',
    size: 65,
    enableSorting: false,
    cell: ({ row }) => row.original.items.length.toLocaleString(),
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
    accessorKey: 'created_at',
    header: '요청일',
    size: 138,
    enableSorting: false,
    cell: ({ row }) => new Date(row.original.created_at).toLocaleString('ko-KR'),
  },
  {
    accessorKey: 'requested_due_date',
    header: '요청 납기',
    size: 105,
    enableSorting: false,
    cell: ({ row }) => row.original.requested_due_date ?? '—',
  },
  {
    accessorKey: 'priority',
    header: '중요도',
    size: 80,
    enableSorting: false,
    cell: ({ row }) => row.original.priority ?? '—',
  },
  {
    accessorKey: 'urgency',
    header: '긴급도',
    size: 80,
    enableSorting: false,
    cell: ({ row }) => row.original.urgency ?? '—',
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
  requesterName,
  requesterEmail,
  onStepUp,
  onPasswordReauth,
  onEnroll,
}: { client: ApiClient; requesterName: string; requesterEmail?: string; onNavigate?: (page: Page) => void } & AssuranceActions) {
  const [stateFilter, setStateFilter] = useState<'' | ChangeRequestState>('')
  const [textFilter, setTextFilter] = useState('')
  const [requests, setRequests] = useState<ChangeRequestRecord[]>([])
  const [overview, setOverview] = useState<ChangeRequestSchemaOverview[]>([])
  const [expandedSchemas, setExpandedSchemas] = useState<Set<string>>(() => new Set())
  const [listLoading, setListLoading] = useState(true)
  const [listError, setListError] = useState<unknown>()
  const [selectedId, setSelectedId] = useState<string>()
  const [detail, setDetail] = useState<ChangeRequestRecord>()
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<unknown>()
  const [attachments, setAttachments] = useState<ChangeRequestAttachment[]>([])
  const [attachmentLoading, setAttachmentLoading] = useState(false)
  const [attachmentBusy, setAttachmentBusy] = useState(false)
  const [attachmentError, setAttachmentError] = useState<unknown>()
  const [actionError, setActionError] = useState<unknown>()
  const [pendingAction, setPendingAction] = useState<ChangeActionHint>()
  const [createOpen, setCreateOpen] = useState(false)
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

  // Load one authorized server window, then apply the presentation-only badge filter.
  // Fetching a state-specific list here would make the summary rows misleading.
  const listPath = useMemo(() => '/change-requests?limit=100', [])

  const loadRequests = useCallback(async () => {
    const intent = ++listIntent.current
    const { controller, expectedGeneration } = beginOperation()
    setListLoading(true)
    setListError(undefined)
    try {
      const value = await client.request<{
        items: ChangeRequestRecord[]
        overview?: ChangeRequestSchemaOverview[]
      }>(listPath, {
        signal: controller.signal,
      })
      if (controller.signal.aborted || expectedGeneration !== generation.current || intent !== listIntent.current) return
      setRequests(value.items)
      setOverview(value.overview ?? [])
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
    setOverview([])
    setExpandedSchemas(new Set())
    setListError(undefined)
    setListLoading(true)
    setSelectedId(undefined)
    setDetail(undefined)
    setDetailError(undefined)
    setAttachments([])
    setAttachmentLoading(false)
    setAttachmentBusy(false)
    setAttachmentError(undefined)
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
    setAttachments([])
    setAttachmentLoading(true)
    setAttachmentError(undefined)
    try {
      const value = await client.request<ChangeRequestRecord>(`/change-requests/${changeRequestId}`, {
        signal: controller.signal,
      })
      if (controller.signal.aborted || expectedGeneration !== generation.current || intent !== detailIntent.current) return
      setDetail(value)
      setRequests((current) => current.map((item) => item.id === value.id ? value : item))
      try {
        const attachmentList = await client.request<ChangeRequestAttachmentList>(
          `/change-requests/${changeRequestId}/attachments`,
          { signal: controller.signal },
        )
        if (!controller.signal.aborted && expectedGeneration === generation.current && intent === detailIntent.current) {
          setAttachments(attachmentList.items)
        }
      } catch (error) {
        if (!controller.signal.aborted && expectedGeneration === generation.current && intent === detailIntent.current) {
          setAttachmentError(error)
        }
      }
    } catch (error) {
      if (!controller.signal.aborted && expectedGeneration === generation.current && intent === detailIntent.current) {
        setDetailError(error)
      }
    } finally {
      controllers.current.delete(controller)
      if (detailController.current === controller) detailController.current = undefined
      if (expectedGeneration === generation.current && intent === detailIntent.current) {
        setDetailLoading(false)
        setAttachmentLoading(false)
      }
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
    setAttachments([])
    setAttachmentLoading(false)
    setAttachmentBusy(false)
    setAttachmentError(undefined)
    setActionError(undefined)
    setPendingAction(undefined)
    setReason(DEFAULT_REASON)
  }, [])

  const openAction = useCallback((action: ChangeActionHint, actionReason?: string) => {
    setActionError(undefined)
    if (actionReason?.trim()) setReason(actionReason.trim())
    setPendingAction(action)
  }, [])
  const cancelAction = useCallback(() => setPendingAction(undefined), [])

  const downloadAttachment = useCallback(async (attachment: ChangeRequestAttachment) => {
    const current = detail
    if (!current) return
    setAttachmentError(undefined)
    try {
      const value = await client.request<{ url: string }>(
        `/change-requests/${current.id}/attachments/${attachment.id}/download`,
      )
      window.location.assign(value.url)
    } catch (error) {
      setAttachmentError(error)
    }
  }, [client, detail])

  const uploadAttachments = useCallback(async (kind: ChangeRequestAttachment['kind'], files: File[]) => {
    const current = detail
    if (!current || files.length === 0 || attachmentBusy) return
    setAttachmentBusy(true)
    setAttachmentError(undefined)
    try {
      for (const file of files) {
        const body = new FormData()
        body.set('kind', kind)
        body.set('file', file)
        await client.request(`/change-requests/${current.id}/attachments`, { method: 'POST', body })
      }
      const value = await client.request<ChangeRequestAttachmentList>(
        `/change-requests/${current.id}/attachments`,
      )
      setAttachments(value.items)
    } catch (error) {
      setAttachmentError(error)
      throw error
    } finally {
      setAttachmentBusy(false)
    }
  }, [attachmentBusy, client, detail])

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
        : action.kind === 'INTAKE_COMPLETE'
          ? `/change-requests/${current.id}/complete-intake`
          : `/change-requests/${current.id}/transitions`
      const body = action.kind === 'APPROVAL'
        ? { stage: action.stage, decision: action.decision, reason }
        : action.kind === 'INTAKE_COMPLETE'
          ? { reason }
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
    return requests.filter((request) => {
      if (stateFilter && request.state !== stateFilter) return false
      if (!query) return true
      return [
      request.number, request.title, request.requester_id, request.items[0]?.aspect_name ?? '', request.classification,
      ].some((value) => value.toLocaleLowerCase().includes(query))
    })
  }, [requests, stateFilter, textFilter])
  const statusBadges: Array<{ label: string; state: '' | ChangeRequestState }> = [
    { label: '전체', state: '' },
    { label: '접수', state: 'REGISTERED' },
    { label: '검토', state: 'IN_REVIEW' },
    { label: '재검토', state: 'CHANGES_REQUESTED' },
    { label: '변경/TEST', state: 'TESTING' },
    { label: '완료검토', state: 'FINAL_REVIEW' },
    { label: '적용 완료', state: 'APPLIED' },
    { label: '수동 완료', state: 'COMPLETED' },
  ]
  const schemaKey = (row: ChangeRequestSchemaOverview) => `${row.platform}\u0000${row.database_name}\u0000${row.schema_name}`
  const toggleSchema = (row: ChangeRequestSchemaOverview) => {
    const key = schemaKey(row)
    setExpandedSchemas((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  return (
    <section className="governance-page">
      <PageTitle
        icon="CR"
        eyebrow="Four-eyes Governance"
        title="변경 요청과 승인"
        description="타입이 지정된 변경을 검토하고 Maker-Checker 상태 전이와 적용 증거를 관리합니다."
        actions={<div className="page-title-actions"><button type="button" className="button button-secondary" disabled={listLoading} onClick={() => void loadRequests()}>새로고침</button><button type="button" className="button" onClick={() => setCreateOpen(true)}>신규 CR 신청</button></div>}
      />

      <div className="governance-toolbar panel">
        <div className="governance-window-summary" aria-live="polite">
          <span className="governance-kicker">Authorized window</span>
          <strong>현재 조회된 요청 · 최대 100건</strong>
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
          <span>새 변경 요청은 독립된 CR 모달에서 DataHub 원본을 서버 검증한 뒤 생성됩니다.</span>
        </div>
      </div>

      <section className="governance-status-overview" aria-label="현재 권한 창의 스키마별 변경요청 현황">
        <header><span className="governance-kicker">CR Status Overview</span><small>현재 권한으로 열람 가능한 DataHub 스키마와 같은 서버 읽기 창의 요청을 결합합니다. 행을 클릭하면 시스템 담당자를 표시합니다.</small></header>
        <div className="governance-status-scroll"><table><thead><tr><th>스키마</th><th>시스템</th><th>담당자</th><th>데이터셋별 미진행</th><th>CR 전체</th><th>접수완료</th><th>재검토</th><th>변경 / TEST</th><th>완료검토</th><th>완료</th></tr></thead><tbody>
          {overview.length === 0 ? <tr><td colSpan={10}>{listLoading ? '스키마별 현황을 확인하는 중' : '현재 권한 범위에서 표시할 DataHub 스키마가 없습니다.'}</td></tr> : overview.map((row) => {
            const expanded = expandedSchemas.has(schemaKey(row))
            return <Fragment key={schemaKey(row)}>
              <tr className="governance-schema-summary-row">
                <td><button type="button" className="governance-schema-toggle" aria-expanded={expanded} onClick={() => toggleSchema(row)}><strong>{row.schema_name}</strong><small>{row.platform} · {row.database_name}</small></button></td>
                <td>{row.system_name ?? '시스템 미지정'}{row.system_code ? <small>{row.system_code}</small> : null}</td>
                <td>{row.assignees.length ? `${row.assignees.length.toLocaleString()}명` : '미지정'}</td>
                <td>{row.pending_count.toLocaleString()}건</td><td>{row.total_count.toLocaleString()}건</td><td>{row.received_count.toLocaleString()}건</td><td>{row.recheck_count.toLocaleString()}건</td><td>{row.testing_count.toLocaleString()}건</td><td>{row.final_review_count.toLocaleString()}건</td><td>{row.completed_count.toLocaleString()}건</td>
              </tr>
              {expanded && <tr className="governance-schema-assignees"><td colSpan={10}>{row.assignees.length ? <ul>{row.assignees.map((assignee) => <li key={`${assignee.subject_id}-${assignee.responsibility}`}><strong>{assignee.display_name}</strong> · {assignee.responsibility === 'DATA_STEWARD' ? 'Data Steward' : '개발자'} · 우선순위 {assignee.priority}</li>)}</ul> : '이 스키마에 활성 시스템 담당자가 아직 지정되지 않았습니다.'}</td></tr>}
            </Fragment>
          })}
        </tbody></table></div>
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
        <div className="governance-stage-filters" aria-label="단계별 CR 필터">
          {statusBadges.map((item) => <button key={item.label} type="button" className={stateFilter === item.state ? 'active' : ''} onClick={() => setStateFilter((current) => current === item.state ? '' : item.state)}>{item.label}</button>)}
        </div>
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
        client={client}
        fallback={fallback}
        value={detail}
        loading={detailLoading}
        busy={busy}
        error={detailError}
        actionError={actionError}
        attachments={attachments}
        attachmentLoading={attachmentLoading}
        attachmentBusy={attachmentBusy}
        attachmentError={attachmentError}
        onClose={closeDetail}
        onRefresh={() => { if (selectedId) void loadDetail(selectedId) }}
        onAction={openAction}
        onDownloadAttachment={(attachment) => { void downloadAttachment(attachment) }}
        onUploadAttachments={uploadAttachments}
        onStepUp={onStepUp}
        onPasswordReauth={onPasswordReauth}
        onEnroll={onEnroll}
      />
      <ChangeRequestCreateDialog
        open={createOpen}
        client={client}
        requesterName={requesterName}
        requesterEmail={requesterEmail}
        onClose={() => setCreateOpen(false)}
        onCreated={(value) => {
          setCreateOpen(false)
          setRequests((current) => [value, ...current.filter((item) => item.id !== value.id)])
          void loadRequests()
        }}
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
