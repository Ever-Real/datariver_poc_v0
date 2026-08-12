import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { CheckCircle2, FileCheck2, ShieldCheck } from 'lucide-react'
import { newIdempotencyKey, type ApiClient } from '../../api/client'
import type {
  CatalogLineage,
  ChangeRequestAttachment,
  ChangeRequestRecord,
  ChangeRequestState,
  GovernanceApplyReport,
} from '../../api/types'
import { attachmentSelectionError } from './attachmentUploads'
import { AssuranceNotice, type AssuranceActions } from '../../components/AssuranceNotice'
import { ErrorNotice } from '../../components/ErrorNotice'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import { Dialog } from '../../components/common/Dialog'
import { FlowCanvas, type FlowCanvasEdge, type FlowCanvasNode } from '../../components/common/FlowCanvas'
import { GovernedUnavailable } from '../../components/common/GovernedUnavailable'
import { TruncatedText } from '../../components/common/TruncatedText'
import { WorkflowStepper, type WorkflowStep } from '../../components/common/WorkflowStepper'
import { changeActionHints, changeStateLabel, type ChangeActionHint } from './changePresentation'

interface ChangeRequestDetailDialogProps extends AssuranceActions {
  open: boolean
  client: ApiClient
  fallback?: ChangeRequestRecord
  value?: ChangeRequestRecord
  loading: boolean
  busy: boolean
  error?: unknown
  actionError?: unknown
  attachments: ChangeRequestAttachment[]
  attachmentLoading: boolean
  attachmentBusy: boolean
  attachmentError?: unknown
  attachmentHasNext: boolean
  attachmentHasPrevious: boolean
  applyReport?: GovernanceApplyReport
  applyReportLoading: boolean
  applyReportError?: unknown
  onClose: () => void
  onEdit: () => void
  onRefresh: () => void | Promise<void>
  onAction: (action: ChangeActionHint, reason?: string) => void
  onDownloadAttachment: (attachment: ChangeRequestAttachment) => void
  onNextAttachmentPage: () => void
  onPreviousAttachmentPage: () => void
  onUploadAttachments: (kind: ChangeRequestAttachment['kind'], files: File[]) => Promise<void>
  onResumePendingAttachments: () => Promise<void>
}

interface ChangeTargetRow {
  id: string
  type: string
  physicalName: string
  logicalName: string
  remarks: string
  change: string
}

function finalAuthorityRows(value: ChangeRequestRecord) {
  const systems = [...new Set(value.items
    .map((item) => item.routing_system_id ?? item.target_system_id)
    .filter((systemId): systemId is string => Boolean(systemId)))]
  const approvals = value.approvals.filter(
    (approval) => approval.stage === 'FINAL' && approval.decision === 'APPROVED',
  )
  const rows: Array<{
    key: string
    label: string
    kind: 'SYSTEM_DEVELOPER' | 'SYSTEM_DATA_STEWARD' | 'GLOBAL_ADMIN'
    systemId: string | null
  }> = [
    ...systems.flatMap((systemId) => ([
    { key: `${systemId}:developer`, label: `Developer · ${systemId}`, kind: 'SYSTEM_DEVELOPER' as const, systemId },
    { key: `${systemId}:steward`, label: `Data Steward · ${systemId}`, kind: 'SYSTEM_DATA_STEWARD' as const, systemId },
    ])),
    { key: 'global-admin', label: '전역 Admin', kind: 'GLOBAL_ADMIN' as const, systemId: null },
  ]
  return rows.map((row) => ({
    ...row,
    approval: approvals.find((approval) => approval.authorities.some(
      (authority) => authority.kind === row.kind && authority.system_id === row.systemId,
    )),
  }))
}

const steps: WorkflowStep[] = [
  { id: 'request', label: '요청 상세', description: '기본 정보와 대상' },
  { id: 'review', label: '검토 및 영향도', description: 'Lineage와 검토 의견' },
  { id: 'test', label: '테스트 및 결과', description: '검증 증거' },
  { id: 'approval', label: '최종 승인', description: '승인 및 적용' },
]

function display(value: string | null | undefined): string {
  return value && value.trim() ? value : '—'
}

function eventTime(value: string): string {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('ko-KR', { hour12: false })
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : undefined
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function stageForState(state: ChangeRequestState): number {
  if (state === 'IN_REVIEW') return 1
  if (state === 'TESTING') return 2
  if (['FINAL_REVIEW', 'APPLY_QUEUED', 'APPLYING', 'APPLIED', 'APPLY_FAILED', 'COMPLETED'].includes(state)) return 3
  return 0
}

function currentStage(value: ChangeRequestRecord): number {
  return stageForState(value.state)
}

function targetRows(value: ChangeRequestRecord): ChangeTargetRow[] {
  return value.items.flatMap((item) => {
    const document = asRecord(item.after_document)
    const source = asRecord(document?.source)
    const requested = asRecord(document?.requested)
    const tableName = text(source?.table_name) || item.target_ref
    const table: ChangeTargetRow = {
      id: item.id,
      type: text(document?.kind) || item.target_asset_type || item.target_type,
      physicalName: tableName,
      logicalName: text(requested?.description) || text(source?.description),
      remarks: text(requested?.requested_change),
      change: text(document?.kind) === 'MANUAL' ? 'NEW' : item.operation,
    }
    const columns = Array.isArray(requested?.columns) ? requested.columns : []
    const columnRows = columns.flatMap((column, columnIndex) => {
      const columnRecord = asRecord(column)
      if (!columnRecord) return []
      const columnRequested = asRecord(columnRecord.requested) ?? columnRecord
      return [{
        id: `${item.id}:column:${columnIndex}`,
        type: 'COLUMN',
        physicalName: text(columnRecord.field_path),
        logicalName: text(columnRequested.description),
        remarks: text(columnRequested.requested_change),
        change: text(document?.kind) === 'MANUAL' ? 'NEW' : 'UPDATE',
      }]
    })
    return [table, ...columnRows.map((row) => ({ ...row, physicalName: `┝ ${row.physicalName}` }))]
  })
}

const targetColumns: ColumnDef<ChangeTargetRow>[] = [
  { accessorKey: 'type', header: 'Type', size: 95, enableSorting: false },
  { accessorKey: 'physicalName', header: 'Physical Name', size: 250, enableSorting: false, cell: ({ row }) => <TruncatedText value={row.original.physicalName} /> },
  { accessorKey: 'logicalName', header: 'Desc (Logical Name)', size: 230, enableSorting: false, cell: ({ row }) => <TruncatedText value={display(row.original.logicalName)} /> },
  {
    accessorKey: 'remarks', header: 'Remarks (비고)', size: 250, enableSorting: false,
    cell: ({ row }) => <input aria-label={`${row.original.physicalName} 비고`} className="w-full border border-slate-300 bg-slate-50 px-2 py-1 text-xs" readOnly value={row.original.remarks} />,
  },
  {
    accessorKey: 'change', header: 'Change', size: 140, enableSorting: false,
    cell: ({ row }) => <input aria-label={`${row.original.physicalName} 작업 내용`} className="w-full border border-slate-300 bg-slate-50 px-2 py-1 text-xs" readOnly value={row.original.change} />,
  },
]

function AttachmentList({
  items,
  kind,
  loading,
  onDownload,
}: {
  items: ChangeRequestAttachment[]
  kind: ChangeRequestAttachment['kind']
  loading: boolean
  onDownload: (attachment: ChangeRequestAttachment) => void
}) {
  const visible = items.filter((item) => item.kind === kind)
  if (loading) return <p className="m-0 text-xs text-slate-500">첨부파일 접근 권한을 확인하는 중입니다.</p>
  if (!visible.length) return <p className="m-0 text-xs text-slate-500">등록된 {kind === 'REQUEST' ? '요청' : 'TEST'} 첨부파일이 없습니다.</p>
  return <ul className="m-0 grid list-none gap-2 p-0">{visible.map((attachment) => <li className="flex flex-wrap items-center gap-2 border-b border-slate-200 pb-2 text-xs" key={attachment.id}>
    <FileCheck2 size={15} className="text-enterprise-blue" aria-hidden="true" />
    <strong className="min-w-0 flex-1 truncate">{attachment.original_name}</strong>
    <span className="text-slate-500">{Math.ceil(attachment.size_bytes / 1024).toLocaleString()} KiB · {eventTime(attachment.created_at)}</span>
    <button type="button" className="button button-secondary" onClick={() => onDownload(attachment)}>열기/다운로드</button>
  </li>)}</ul>
}

export function ChangeRequestDetailDialog({
  open,
  client,
  fallback,
  value,
  loading,
  busy,
  error,
  actionError,
  attachments,
  attachmentLoading,
  attachmentBusy,
  attachmentError,
  applyReport,
  applyReportLoading,
  applyReportError,
  onClose,
  onEdit,
  onRefresh,
  onAction,
  onDownloadAttachment,
  onUploadAttachments,
  onStepUp,
  onPasswordReauth,
  onEnroll,
}: ChangeRequestDetailDialogProps) {
  const current = value ?? fallback
  const activeStage = value ? currentStage(value) : 0
  const [selectedStage, setSelectedStage] = useState(activeStage)
  const [reviewComment, setReviewComment] = useState('')
  const [pendingFiles, setPendingFiles] = useState<File[]>([])
  const [uploadKind, setUploadKind] = useState<ChangeRequestAttachment['kind']>('REQUEST')
  const [uploadError, setUploadError] = useState<unknown>()
  const [lineage, setLineage] = useState<CatalogLineage[]>([])
  const [lineageLoading, setLineageLoading] = useState(false)
  const [lineageError, setLineageError] = useState<unknown>()
  const [testSystemId, setTestSystemId] = useState('')
  const [testAttachmentId, setTestAttachmentId] = useState('')
  const [testSummary, setTestSummary] = useState('')
  const [testState, setTestState] = useState<'PASSED' | 'FAILED'>('PASSED')
  const [testSaving, setTestSaving] = useState(false)
  const [testError, setTestError] = useState<unknown>()
  const busyRef = useRef(busy)
  const uploadIntent = useRef(0)
  const testMutationIntent = useRef(0)
  const testMutationController = useRef<AbortController | undefined>(undefined)
  const visibleError = actionError ?? error
  const hints = useMemo(() => value ? changeActionHints(value) : [], [value])
  const rows = useMemo(() => value ? targetRows(value) : [], [value])
  const finalAuthorities = useMemo(() => value ? finalAuthorityRows(value) : [], [value])
  const routedSystems = useMemo(() => value ? [...new Set(value.items
    .map((item) => item.routing_system_id ?? item.target_system_id)
    .filter((systemId): systemId is string => Boolean(systemId)))] : [], [value])
  const currentTestAttachments = useMemo(() => value ? attachments.filter(
    (attachment) => attachment.kind === 'TEST' && attachment.round_id === value.current_round_id,
  ) : [], [attachments, value])

  useEffect(() => { busyRef.current = busy }, [busy])
  useEffect(() => {
    uploadIntent.current += 1
    testMutationIntent.current += 1
    testMutationController.current?.abort()
    testMutationController.current = undefined
    setSelectedStage(current ? currentStage(current) : 0)
    setReviewComment('')
    setPendingFiles([])
    setUploadError(undefined)
    setTestSystemId('')
    setTestAttachmentId('')
    setTestSummary('')
    setTestSaving(false)
    setTestError(undefined)
  }, [current])
  useEffect(() => () => {
    uploadIntent.current += 1
    testMutationIntent.current += 1
    testMutationController.current?.abort()
  }, [])
  useEffect(() => {
    if (!testSystemId && routedSystems.length > 0) setTestSystemId(routedSystems[0] ?? '')
  }, [routedSystems, testSystemId])
  useEffect(() => {
    if (!testAttachmentId && currentTestAttachments.length > 0) {
      setTestAttachmentId(currentTestAttachments.at(-1)?.id ?? '')
    }
  }, [currentTestAttachments, testAttachmentId])

  useEffect(() => {
    if (!open || !value || selectedStage !== 1) return
    const assetIds = Array.from(new Set(value.items.flatMap((item) => item.target_asset_id ? [item.target_asset_id] : [])))
    if (!assetIds.length) {
      setLineage([])
      setLineageError(undefined)
      setLineageLoading(false)
      return
    }
    const controller = new AbortController()
    setLineageLoading(true)
    setLineageError(undefined)
    Promise.all(assetIds.slice(0, 20).map((assetId) => client.request<CatalogLineage>(
      `/catalog/assets/${assetId}/lineage?direction=BOTH&depth=2`,
      { signal: controller.signal },
    )))
      .then((results) => { if (!controller.signal.aborted) setLineage(results) })
      .catch((next) => { if (!controller.signal.aborted) setLineageError(next) })
      .finally(() => { if (!controller.signal.aborted) setLineageLoading(false) })
    return () => controller.abort()
  }, [client, open, selectedStage, value])

  const flowNodes = useMemo<FlowCanvasNode[]>(() => {
    const values = new Map<string, FlowCanvasNode>()
    lineage.forEach((result) => result.nodes.forEach((node) => values.set(node.id, {
      id: node.id,
      label: node.name,
      subtitle: [node.platform, node.schema_name, node.asset_type].filter(Boolean).join(' · '),
      kind: node.id === result.center_asset_id ? 'target' : 'source',
    })))
    return Array.from(values.values())
  }, [lineage])
  const flowEdges = useMemo<FlowCanvasEdge[]>(() => {
    const values = new Map<string, FlowCanvasEdge>()
    lineage.forEach((result) => result.edges.forEach((edge) => {
      const id = `${edge.source_asset_id}:${edge.target_asset_id}`
      values.set(id, { id, source: edge.source_asset_id, target: edge.target_asset_id, label: 'LINEAGE' })
    }))
    return Array.from(values.values())
  }, [lineage])

  const requestClose = useCallback(() => { if (!busyRef.current) onClose() }, [onClose])
  const addFiles = (event: ChangeEvent<HTMLInputElement>, kind: ChangeRequestAttachment['kind']) => {
    const files = Array.from(event.target.files ?? [])
    event.target.value = ''
    const selectionError = attachmentSelectionError(files)
    if (selectionError) {
      setUploadError(selectionError)
      return
    }
    uploadIntent.current += 1
    setUploadKind(kind)
    setPendingFiles(files)
    setUploadError(undefined)
  }
  const upload = async () => {
    if (!pendingFiles.length || attachmentBusy) return
    const intent = uploadIntent.current
    const files = pendingFiles
    try {
      await onUploadAttachments(uploadKind, files)
      if (intent !== uploadIntent.current) return
      setPendingFiles((currentFiles) => currentFiles === files ? [] : currentFiles)
    } catch (next) {
      if (intent === uploadIntent.current) setUploadError(next)
    }
  }
  const recordTestEvidence = useCallback(async () => {
    if (!value || !testSystemId || !testAttachmentId || !testSummary.trim()) return
    testMutationController.current?.abort()
    const controller = new AbortController()
    testMutationController.current = controller
    const intent = ++testMutationIntent.current
    const changeRequestId = value.id
    const changeRequestVersion = value.version
    setTestSaving(true)
    setTestError(undefined)
    try {
      await client.request<ChangeRequestRecord>(`/change-requests/${changeRequestId}/test-runs`, {
        method: 'POST',
        signal: controller.signal,
        body: JSON.stringify({
          system_id: testSystemId,
          attachment_id: testAttachmentId,
          state: testState,
          bounded_summary: { summary: testSummary.trim() },
        }),
        idempotencyKey: newIdempotencyKey('change-test-run'),
        ifMatch: `"${changeRequestVersion}"`,
      })
      if (
        controller.signal.aborted
        || intent !== testMutationIntent.current
        || value.id !== changeRequestId
        || value.version !== changeRequestVersion
      ) return
      setTestSummary('')
      await onRefresh()
    } catch (next) {
      if (
        !controller.signal.aborted
        && intent === testMutationIntent.current
        && value.id === changeRequestId
        && value.version === changeRequestVersion
      ) setTestError(next)
    } finally {
      if (testMutationController.current === controller) {
        testMutationController.current = undefined
      }
      if (
        !controller.signal.aborted
        && intent === testMutationIntent.current
        && value.id === changeRequestId
        && value.version === changeRequestVersion
      ) setTestSaving(false)
    }
  }, [client, onRefresh, testAttachmentId, testState, testSummary, testSystemId, value])
  const stageHints = selectedStage === activeStage ? hints : []
  const currentRound = value?.rounds.find((item) => item.id === value.current_round_id)
  const canEdit = Boolean(
    value?.revision_allowed
    && value.state === 'CHANGES_REQUESTED'
    && value.request_type === 'CHANGE_INTAKE',
  )

  return (
    <Dialog
      open={open}
      size="workspace"
      title={current ? `${current.number} · ${current.title}` : '변경 요청 상세'}
      description={current ? `요청일 ${eventTime(current.created_at)} · 서버 검증 상태 ${changeStateLabel(current.state)}` : '현재 권한으로 변경 요청을 확인합니다.'}
      onRequestClose={requestClose}
      footer={<>
        <button type="button" className="button button-secondary" disabled={busy || loading} onClick={() => { void onRefresh() }}>새로고침</button>
        <button type="button" className="button button-secondary" disabled={busy} onClick={requestClose}>닫기</button>
      </>}
    >
      <div className="grid gap-4">
        {loading && <div className="rounded-enterprise border border-slate-300 bg-white p-5 text-sm" role="status">변경 요청을 다시 인가하고 불러오는 중입니다.</div>}
        <AssuranceNotice error={visibleError} onStepUp={onStepUp} onPasswordReauth={onPasswordReauth} onEnroll={onEnroll} />
        <ErrorNotice error={visibleError} />

        {value && !loading && <>
          <header className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-300 pb-3">
            <div>
              <span className="text-[10px] font-black tracking-[.14em] text-enterprise-blue uppercase">{value.number}</span>
              <h2 className="my-1 text-xl font-black text-navy-900">{value.title}</h2>
              <p className="m-0 text-xs text-slate-500">시스템 범위는 각 변경 대상의 서버 binding으로 확인됩니다.</p>
            </div>
            <span className={`badge governance-state state-${value.state.toLowerCase()}`}>{changeStateLabel(value.state)} · {value.state}</span>
          </header>

          <WorkflowStepper steps={steps} currentIndex={activeStage} selectedIndex={selectedStage} onSelect={setSelectedStage} />
          <div className="rounded-enterprise border border-blue-200 bg-blue-50 px-3 py-2 text-[11px] leading-5 text-slate-700" role="note"><strong className="text-navy-900">화면의 명령은 현재 상태를 기준으로 한 힌트입니다.</strong> 서버가 클릭할 때마다 현재 대상 권한, 요청자 분리, 인증 보증과 승인 요건을 다시 판단하며 인증 뒤 작업을 자동 재실행하지 않습니다.</div>

          {selectedStage === 0 && <section className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)]" aria-labelledby="request-stage-heading">
            <h3 id="request-stage-heading" className="sr-only">1단계 요청 상세</h3>
            <aside className="grid content-start gap-3">
              <section className="rounded-enterprise border border-slate-300 bg-white p-4 shadow-sm">
                <div className="mb-3 flex items-center justify-between"><h4 className="m-0 text-xs font-black text-navy-900">BASIC METADATA</h4><button type="button" className="button button-secondary" disabled={!canEdit || busy} title={canEdit ? '현재 회차를 보존하고 수정된 새 회차를 재상신합니다.' : '현재 사용자와 상태에서는 요청을 수정할 수 없습니다.'} onClick={onEdit}>Edit Request</button></div>
                <dl className="grid gap-2 text-xs">
                  <div><dt className="text-[10px] font-black text-slate-500 uppercase">요청자</dt><dd className="m-0 mt-0.5 break-all">{value.requester_id}</dd></div>
                  <div><dt className="text-[10px] font-black text-slate-500 uppercase">담당자</dt><dd className="m-0 mt-0.5">서버 상세 응답에 미포함</dd></div>
                  <div><dt className="text-[10px] font-black text-slate-500 uppercase">요청부서</dt><dd className="m-0 mt-0.5">{display(currentRound?.request_department)}</dd></div>
                  <div><dt className="text-[10px] font-black text-slate-500 uppercase">긴급도</dt><dd className="m-0 mt-0.5">{display(value.urgency)}</dd></div>
                  <div><dt className="text-[10px] font-black text-slate-500 uppercase">보안등급</dt><dd className="m-0 mt-0.5">{value.classification}</dd></div>
                  <div><dt className="text-[10px] font-black text-slate-500 uppercase">희망 납기일</dt><dd className="m-0 mt-0.5">{display(value.requested_due_date)}</dd></div>
                  <div><dt className="text-[10px] font-black text-slate-500 uppercase">집계 버전</dt><dd className="m-0 mt-0.5">{value.version}</dd></div>
                </dl>
              </section>
              <section className="rounded-enterprise border border-slate-300 bg-white p-4 shadow-sm">
                <h4 className="mt-0 mb-3 text-xs font-black text-navy-900">Attachments · 증빙 자료</h4>
                <AttachmentList items={attachments} kind="REQUEST" loading={attachmentLoading} onDownload={onDownloadAttachment} />
                {['REGISTERED', 'CHANGES_REQUESTED'].includes(value.state) && <label className="mt-3 block rounded-enterprise border border-dashed border-enterprise-blue bg-blue-50 p-3 text-center text-xs font-bold text-enterprise-blue">
                  클릭하여 신규 파일 첨부
                  <input type="file" multiple className="sr-only" disabled={attachmentBusy} onChange={(event) => addFiles(event, 'REQUEST')} />
                </label>}
                {uploadKind === 'REQUEST' && pendingFiles.length > 0 && <button type="button" className="button mt-2 w-full" disabled={attachmentBusy} onClick={() => void upload()}>{attachmentBusy ? '저장 중…' : `${pendingFiles.length}개 파일 저장`}</button>}
              </section>
            </aside>
            <div className="grid content-start gap-4">
              <section className="rounded-enterprise border border-slate-300 bg-white p-4 shadow-sm">
                <h4 className="mt-0 mb-2 text-xs font-black text-navy-900">REQUEST REASON</h4>
                <p className="m-0 whitespace-pre-wrap text-sm leading-6 text-slate-700">{display(currentRound?.request_reason || value.description)}</p>
                {currentRound?.request_content && <p className="mb-0 mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-700">{currentRound.request_content}</p>}
              </section>
              <section className="rounded-enterprise border border-slate-300 bg-white p-4 shadow-sm">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><h4 className="m-0 text-xs font-black text-navy-900">CHANGE TARGETS <span className="text-enterprise-blue">{rows.length}</span></h4><span className="text-[10px] text-slate-500">비고와 작업 내용은 불변 요청 증거이며 읽기 전용입니다.</span></div>
                <DenseDataTable caption="CR 변경 대상" columns={targetColumns} data={rows} getRowId={(row) => row.id} emptyMessage="등록된 변경 대상이 없습니다." />
                <div className="mt-3"><GovernedUnavailable compact title={canEdit ? '새 회차에서 수정 가능' : '현재 요청 수정 불가'} description={canEdit ? 'Edit Request를 누르면 현재 회차의 메타데이터와 대상을 새 revision draft로 불러옵니다. 기존 회차 증거는 변경되지 않습니다.' : '서버가 현재 사용자·상태·대상 권한을 확인한 결과 수정 가능한 revision 명령을 제공하지 않았습니다.'} /></div>
              </section>
              <div className="flex justify-end gap-2">
                {canEdit && <button type="button" className="button" disabled={busy} onClick={onEdit}>보완 후 재신청</button>}
                {stageHints.map((hint) => <button key={hint.id} type="button" className={`button ${hint.tone === 'danger' ? 'button-danger' : hint.tone === 'primary' ? '' : 'button-secondary'}`} disabled={busy} onClick={() => onAction(hint)}>{hint.label}</button>)}
              </div>
            </div>
          </section>}

          {selectedStage === 1 && <section className="grid gap-4" aria-labelledby="review-stage-heading">
            <div><span className="text-[10px] font-black tracking-[.14em] text-enterprise-blue uppercase">Impact Analysis</span><h3 id="review-stage-heading" className="my-1 text-lg font-black text-navy-900">검토 및 영향도</h3><p className="m-0 text-xs text-slate-500">Upstream 소스 정합성과 Downstream 파생 범위를 권한 필터된 DataHub 계보로 확인합니다.</p></div>
            {lineageLoading && <p role="status" className="m-0 text-xs text-slate-500">실제 계보를 불러오는 중입니다.</p>}
            <ErrorNotice error={lineageError} />
            <FlowCanvas ariaLabel="변경 대상 영향도 계보" nodes={flowNodes} edges={flowEdges} height={440} emptyTitle="조회 가능한 Lineage가 없습니다." emptyDescription="수동 신규 대상이거나 현재 권한 범위에 연결된 계보가 없습니다." />
            {lineage.some((item) => item.truncated) && <p className="m-0 text-xs font-bold text-amber-800">서버 조회 한도에 따라 일부 계보가 생략되었습니다.</p>}
            <label className="grid gap-2 rounded-enterprise border border-slate-300 bg-white p-4 text-xs font-black text-navy-900">REVIEWER COMMENTS · Data Steward 검토 의견
              <textarea className="min-h-24 resize-y border border-slate-300 p-3 text-sm font-normal" maxLength={4000} placeholder="승인·보완 요청 사유로 기록할 검토 의견을 입력하세요." value={reviewComment} onChange={(event) => setReviewComment(event.target.value)} />
            </label>
            <div className="flex flex-wrap justify-end gap-2">
              {stageHints.map((hint) => <button key={hint.id} type="button" className={`button ${hint.tone === 'danger' ? 'button-danger' : hint.tone === 'primary' ? '' : 'button-secondary'}`} disabled={busy || !reviewComment.trim()} onClick={() => onAction(hint, reviewComment)}>{hint.label}</button>)}
            </div>
          </section>}

          {selectedStage === 2 && <section className="grid gap-4" aria-labelledby="test-stage-heading">
            <div><span className="text-[10px] font-black tracking-[.14em] text-enterprise-blue uppercase">SQL Validation & Sandbox Test</span><h3 id="test-stage-heading" className="my-1 text-lg font-black text-navy-900">테스트 및 결과</h3></div>
            <section className="rounded-enterprise border border-slate-300 bg-navy-950 p-4 text-slate-100 shadow-sm">
              <div className="mb-3 flex items-center gap-2 text-xs font-black"><ShieldCheck size={16} /> SERVER-BOUND TEST EVIDENCE</div>
              <pre className="m-0 min-h-16 whitespace-pre-wrap text-xs text-slate-300">브라우저 SQL은 실행하지 않습니다. 현재 회차의 TEST 첨부파일 해시를 대상 시스템과 결합해 typed 결과 증거로 기록합니다.</pre>
            </section>
            <section className="rounded-enterprise border border-slate-300 bg-white p-4 shadow-sm">
              <h4 className="mt-0 mb-3 text-xs font-black text-navy-900">TEST EVIDENCE</h4>
              <AttachmentList items={attachments} kind="TEST" loading={attachmentLoading} onDownload={onDownloadAttachment} />
              {value.state === 'TESTING' && <label className="mt-3 block rounded-enterprise border border-dashed border-enterprise-blue bg-blue-50 p-3 text-center text-xs font-bold text-enterprise-blue">클릭하여 테스트 결과 파일 첨부<input type="file" multiple className="sr-only" disabled={attachmentBusy} onChange={(event) => addFiles(event, 'TEST')} /></label>}
              {uploadKind === 'TEST' && pendingFiles.length > 0 && <button type="button" className="button mt-2" disabled={attachmentBusy} onClick={() => void upload()}>{attachmentBusy ? '저장 중…' : `${pendingFiles.length}개 TEST 증거 저장`}</button>}
            </section>
            <section className="grid gap-3 rounded-enterprise border border-slate-300 bg-white p-4 shadow-sm">
              <h4 className="m-0 text-xs font-black text-navy-900">시스템별 검증 결과 기록</h4>
              {value.test_runs.filter((run) => run.round_id === value.current_round_id).map((run) => <div key={run.id} className="flex flex-wrap gap-2 border-b border-slate-200 pb-2 text-xs"><span className={run.state === 'PASSED' ? 'badge' : 'badge badge-danger'}>{run.state}</span><TruncatedText value={run.system_id} /><span className="text-slate-500">{eventTime(run.occurred_at)}</span></div>)}
              {value.state === 'TESTING' && <div className="grid gap-2 md:grid-cols-3">
                <select aria-label="테스트 대상 시스템" className="border border-slate-300 p-2 text-xs" value={testSystemId} onChange={(event) => setTestSystemId(event.target.value)}><option value="">대상 시스템 선택</option>{routedSystems.map((systemId) => <option key={systemId} value={systemId}>{systemId}</option>)}</select>
                <select aria-label="테스트 증거 파일" className="border border-slate-300 p-2 text-xs" value={testAttachmentId} onChange={(event) => setTestAttachmentId(event.target.value)}><option value="">현재 회차 TEST 파일 선택</option>{currentTestAttachments.map((attachment) => <option key={attachment.id} value={attachment.id}>{attachment.original_name}</option>)}</select>
                <select aria-label="테스트 결과" className="border border-slate-300 p-2 text-xs" value={testState} onChange={(event) => setTestState(event.target.value as 'PASSED' | 'FAILED')}><option value="PASSED">PASSED</option><option value="FAILED">FAILED</option></select>
                <textarea aria-label="테스트 결과 요약" className="min-h-20 resize-y border border-slate-300 p-2 text-xs md:col-span-3" maxLength={4000} placeholder="실제 검증 결과와 확인 범위를 기록하세요." value={testSummary} onChange={(event) => setTestSummary(event.target.value)} />
                <button type="button" className="button md:col-span-3" disabled={testSaving || !testSystemId || !testAttachmentId || !testSummary.trim()} onClick={() => void recordTestEvidence()}>{testSaving ? '기록 중…' : 'Typed TEST 결과 기록'}</button>
              </div>}
              <ErrorNotice error={testError} />
            </section>
            {stageHints.some((hint) => hint.disabledReason) && <p className="m-0 text-right text-xs font-bold text-amber-800" role="status">{stageHints.find((hint) => hint.disabledReason)?.disabledReason}</p>}
            <div className="flex flex-wrap justify-end gap-2">{stageHints.map((hint) => <button key={hint.id} type="button" className={`button ${hint.tone === 'danger' ? 'button-danger' : hint.tone === 'primary' ? '' : 'button-secondary'}`} disabled={busy || Boolean(hint.disabledReason)} title={hint.disabledReason} onClick={() => onAction(hint)}>{hint.label}</button>)}</div>
          </section>}

          {selectedStage === 3 && <section className="grid gap-4" aria-labelledby="approval-stage-heading">
            <div><span className="text-[10px] font-black tracking-[.14em] text-enterprise-blue uppercase">Final Approval Status</span><h3 id="approval-stage-heading" className="my-1 text-lg font-black text-navy-900">최종 의사결정권자 승인 단계</h3></div>
            <div className="grid gap-3 md:grid-cols-3">{finalAuthorities.map((row) => <article key={row.key} className="rounded-enterprise border border-slate-300 bg-white p-4 shadow-sm"><strong className="text-xs text-navy-900">{row.label}</strong>{row.approval ? <div className="mt-3 grid gap-1 text-xs"><span className="badge w-fit">승인 완료</span><TruncatedText value={row.approval.actor_id} /><time dateTime={row.approval.occurred_at} className="text-[10px] text-slate-500">{eventTime(row.approval.occurred_at)}</time></div> : <p className="mb-0 mt-3 text-xs text-slate-500">승인 대기 중</p>}</article>)}</div>
            {value.items.some((item) => !(item.routing_system_id ?? item.target_system_id)) && <GovernedUnavailable compact title="대상 시스템 증거 누락" description="이전 CR에는 정규화된 시스템 라우팅 정보가 없어 최종 승인을 완료할 수 없습니다. 대상 시스템을 선택한 새 요청으로 다시 등록해야 합니다." />}
            <section className="rounded-enterprise border border-slate-300 bg-white p-4 shadow-sm">
              <h4 className="mt-0 mb-3 text-xs font-black text-navy-900">서버 승인 증거</h4>
              {value.approvals.length === 0 ? <p className="m-0 text-xs text-slate-500">기록된 승인 판단이 없습니다.</p> : <ol className="m-0 grid list-none gap-2 p-0">{value.approvals.map((approval) => <li className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-3 border-b border-slate-200 pb-2 text-xs" key={approval.id}><CheckCircle2 size={16} className="text-emerald-700" /><div><strong>{approval.stage} · {approval.decision}</strong><p className="my-1 text-slate-600">{approval.reason}</p><TruncatedText value={approval.actor_id} /><div className="mt-1 flex flex-wrap gap-1">{approval.authorities.map((authority) => <span className="badge badge-soft" key={`${authority.kind}:${authority.system_id ?? 'global'}`}>{authority.kind}{authority.system_id ? ` · ${authority.system_id}` : ''}</span>)}</div></div><time dateTime={approval.occurred_at} className="text-[10px] text-slate-500">{eventTime(approval.occurred_at)}</time></li>)}</ol>}
            </section>
            <section className="rounded-enterprise border border-slate-300 bg-white p-4 shadow-sm">
              <h4 className="mt-0 mb-3 text-xs font-black text-navy-900">상태 전이 이력</h4>
              {value.transitions.length === 0 ? <p className="m-0 text-xs text-slate-500">기록된 상태 전이가 없습니다.</p> : <ol className="m-0 grid list-none gap-2 p-0">{value.transitions.map((transition) => <li className="flex flex-wrap items-center gap-2 border-b border-slate-200 pb-2 text-xs" key={transition.id}><strong>{changeStateLabel(transition.from_state)} → {changeStateLabel(transition.to_state)}</strong><span className="min-w-0 flex-1 truncate text-slate-600">{transition.reason}</span><time dateTime={transition.occurred_at} className="text-[10px] text-slate-500">{eventTime(transition.occurred_at)}</time></li>)}</ol>}
            </section>
            <section className="rounded-enterprise border border-slate-300 bg-white p-4 shadow-sm" aria-label="DataHub 적용 리포트">
              <h4 className="mt-0 mb-3 text-xs font-black text-navy-900">DATAHUB APPLY / READ-BACK</h4>
              {applyReportLoading && <p role="status" className="m-0 text-xs text-slate-500">적용 증거를 확인하는 중입니다.</p>}
              <ErrorNotice error={applyReportError} />
              {applyReport && !applyReportLoading && <>
                <dl className="grid gap-2 text-xs md:grid-cols-3">
                  <div><dt className="text-[10px] font-black text-slate-500 uppercase">Job state</dt><dd className="m-0 mt-1"><span className="badge">{applyReport.state}</span></dd></div>
                  <div><dt className="text-[10px] font-black text-slate-500 uppercase">Attempts</dt><dd className="m-0 mt-1">{applyReport.attempt_count}</dd></div>
                  <div><dt className="text-[10px] font-black text-slate-500 uppercase">Read-back</dt><dd className="m-0 mt-1">{applyReport.reconciled ? 'HASH MATCH · VERIFIED' : '미완료 또는 불일치'}</dd></div>
                </dl>
                {applyReport.last_error_code && <p className="notice notice-error">실패 코드: {applyReport.last_error_code}</p>}
                <div className="mt-3 grid gap-2">
                  {applyReport.items.map((item) => <article key={item.item_id} className="grid gap-1 border-t border-slate-200 pt-2 text-[11px]">
                    <strong>{item.item_id}</strong>
                    <span>Expected <code>{item.expected_hash}</code></span>
                    <span>Observed <code>{item.observed_hash ?? '—'}</code></span>
                    <span>Source {item.source_version ?? '—'} · Provider {item.provider_version ?? '—'}</span>
                  </article>)}
                </div>
                {applyReport.attempts.length > 0 && <ol className="mt-3 grid list-none gap-1 p-0 text-[11px]">{applyReport.attempts.map((attempt) => <li key={attempt.id} className="flex flex-wrap gap-2"><strong>#{attempt.attempt_no} {attempt.state}</strong><span>{attempt.failure_code ?? 'failure 없음'}</span><time dateTime={attempt.started_at}>{eventTime(attempt.started_at)}</time></li>)}</ol>}
              </>}
            </section>
            <div className="flex flex-wrap justify-end gap-2">{stageHints.map((hint) => <button key={hint.id} type="button" className={`button ${hint.tone === 'danger' ? 'button-danger' : hint.tone === 'primary' ? '' : 'button-secondary'}`} disabled={busy} onClick={() => onAction(hint)}>{hint.label}</button>)}</div>
          </section>}
          <ErrorNotice error={attachmentError ?? uploadError} />
        </>}
      </div>
    </Dialog>
  )
}
