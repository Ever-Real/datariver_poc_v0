import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { Search } from 'lucide-react'
import { ApiError, newIdempotencyKey, type ApiClient } from '../../api/client'
import type {
  ChangeRequestRecord,
  ChangeRequestSummary,
  ChangeRequestSummaryList,
  ChangeRequestAttachment,
  ChangeRequestAttachmentList,
  ChangeRequestSchemaOverview,
  ChangeRequestState,
  GovernanceApplyReport,
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
  resumeAttachmentUpload,
  resumeStoredAttachmentUploads,
  uploadAndFinalizeAttachment,
} from './attachmentUploads'
import {
  changeStateLabel,
  changeStateOptions,
  type ChangeActionHint,
} from './changePresentation'
import './changeManagement.css'

const columns: ColumnDef<ChangeRequestSummary>[] = [
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
    cell: ({ row }) => <TruncatedText value={row.original.first_item.aspect_name} />,
  },
  {
    id: 'target',
    header: '대상 데이터셋',
    size: 230,
    enableSorting: false,
    cell: ({ row }) => <TruncatedText value={row.original.first_item.target_ref} />,
  },
  {
    id: 'operation',
    header: '작업',
    size: 105,
    enableSorting: false,
    cell: ({ row }) => <TruncatedText value={row.original.first_item.operation} />,
  },
  {
    id: 'items',
    header: '항목',
    size: 65,
    enableSorting: false,
    cell: ({ row }) => row.original.item_count.toLocaleString(),
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

function displayWidth(value: string): number {
  return Array.from(value).reduce(
    (width, character) => width + (character.codePointAt(0)! > 0xff ? 2 : 1),
    0,
  )
}

function proportionalOverviewWidths(rows: ChangeRequestSchemaOverview[]): number[] {
  const samples = [
    ['스키마', ...rows.flatMap((row) => [
      row.schema_name,
      `${row.platform} · ${row.database_name}`,
    ])],
    ['시스템', ...rows.flatMap((row) => [
      row.system_name ?? '시스템 미지정',
      row.system_code ?? '',
    ])],
    ['담당자', ...rows.map((row) => row.assignees.length
      ? `${row.assignees.length.toLocaleString()}명`
      : '미지정')],
    ['데이터셋별 미진행', ...rows.map((row) => `${row.pending_count.toLocaleString()}건`)],
    ['CR 전체', ...rows.map((row) => `${row.total_count.toLocaleString()}건`)],
    ['접수완료', ...rows.map((row) => `${row.received_count.toLocaleString()}건`)],
    ['재검토', ...rows.map((row) => `${row.recheck_count.toLocaleString()}건`)],
    ['변경 / TEST', ...rows.map((row) => `${row.testing_count.toLocaleString()}건`)],
    ['완료검토', ...rows.map((row) => `${row.final_review_count.toLocaleString()}건`)],
    ['완료', ...rows.map((row) => `${row.completed_count.toLocaleString()}건`)],
  ]
  const weights = samples.map((values) => Math.min(
    32,
    Math.max(...values.map(displayWidth)),
  ))
  const dimensionWeights = weights.slice(0, 3)
  const metricWeights = weights.slice(3)
  const sharedMetricWeight = metricWeights.reduce((sum, width) => sum + width, 0)
    / metricWeights.length
  const normalizedWeights = [
    ...dimensionWeights,
    ...metricWeights.map(() => sharedMetricWeight),
  ]
  const total = normalizedWeights.reduce((sum, width) => sum + width, 0)
  return normalizedWeights.map((width) => (width / total) * 100)
}

export function GovernancePage({
  client,
  requesterName,
  requesterEmail,
  onStepUp,
  onPasswordReauth,
  onEnroll,
  hardwareWebauthnEnabled,
}: { client: ApiClient; requesterName: string; requesterEmail?: string; onNavigate?: (page: Page) => void } & AssuranceActions) {
  const [stateFilter, setStateFilter] = useState<'' | ChangeRequestState>('')
  const [textFilter, setTextFilter] = useState('')
  const [requests, setRequests] = useState<ChangeRequestSummary[]>([])
  const [overview, setOverview] = useState<ChangeRequestSchemaOverview[]>([])
  const [overviewTruncated, setOverviewTruncated] = useState(false)
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
  const [attachmentNextCursor, setAttachmentNextCursor] = useState<string>()
  const [attachmentCursorStack, setAttachmentCursorStack] = useState<string[]>([])
  const [applyReport, setApplyReport] = useState<GovernanceApplyReport>()
  const [applyReportLoading, setApplyReportLoading] = useState(false)
  const [applyReportError, setApplyReportError] = useState<unknown>()
  const [actionError, setActionError] = useState<unknown>()
  const [pendingAction, setPendingAction] = useState<ChangeActionHint>()
  const [createOpen, setCreateOpen] = useState(false)
  const [revision, setRevision] = useState<ChangeRequestRecord>()
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [nextCursor, setNextCursor] = useState<string>()
  const [cursorStack, setCursorStack] = useState<string[]>([])
  const generation = useRef(0)
  const listIntent = useRef(0)
  const detailIntent = useRef(0)
  const attachmentMutationIntent = useRef(0)
  const preserveReasonForConflictRetry = useRef(false)
  const controllers = useRef(new Set<AbortController>())
  const detailController = useRef<AbortController | undefined>(undefined)
  const attachmentMutationController = useRef<AbortController | undefined>(undefined)
  const attachmentUploadIds = useRef(new WeakMap<File, string>())
  const selectedIdRef = useRef<string | undefined>(undefined)

  const beginOperation = useCallback(() => {
    const controller = new AbortController()
    controllers.current.add(controller)
    return { controller, expectedGeneration: generation.current }
  }, [])

  // Load one bounded authorized summary window. Full documents are fetched only for one detail.
  const loadRequests = useCallback(async (cursor?: string) => {
    const intent = ++listIntent.current
    const { controller, expectedGeneration } = beginOperation()
    setListLoading(true)
    setListError(undefined)
    try {
      const query = new URLSearchParams({ limit: '25' })
      if (stateFilter) query.set('state', stateFilter)
      if (cursor) query.set('cursor', cursor)
      const value = await client.request<ChangeRequestSummaryList>(
        `/change-requests/summaries?${query.toString()}`, {
        signal: controller.signal,
      })
      if (controller.signal.aborted || expectedGeneration !== generation.current || intent !== listIntent.current) return
      setRequests(value.items)
      setOverview(value.overview ?? [])
      setOverviewTruncated(value.overview_truncated)
      setNextCursor(value.page.next_cursor ?? undefined)
    } catch (error) {
      if (!controller.signal.aborted && expectedGeneration === generation.current && intent === listIntent.current) {
        setListError(error)
      }
    } finally {
      controllers.current.delete(controller)
      if (expectedGeneration === generation.current && intent === listIntent.current) setListLoading(false)
    }
  }, [beginOperation, client, stateFilter])

  useEffect(() => {
    const activeControllers = controllers.current
    generation.current += 1
    listIntent.current += 1
    detailIntent.current += 1
    attachmentMutationIntent.current += 1
    activeControllers.forEach((controller) => controller.abort())
    activeControllers.clear()
    detailController.current = undefined
    attachmentMutationController.current = undefined
    selectedIdRef.current = undefined
    setRequests([])
    setCursorStack([])
    setNextCursor(undefined)
    setOverview([])
    setOverviewTruncated(false)
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
    setAttachmentNextCursor(undefined)
    setAttachmentCursorStack([])
    setApplyReport(undefined)
    setApplyReportLoading(false)
    setApplyReportError(undefined)
    setActionError(undefined)
    setPendingAction(undefined)
    setCreateOpen(false)
    setRevision(undefined)
    setReason('')
    preserveReasonForConflictRetry.current = false
    setBusy(false)
    void loadRequests()
    return () => {
      generation.current += 1
      listIntent.current += 1
      detailIntent.current += 1
      attachmentMutationIntent.current += 1
      activeControllers.forEach((controller) => controller.abort())
      activeControllers.clear()
      detailController.current = undefined
      attachmentMutationController.current = undefined
      selectedIdRef.current = undefined
    }
  }, [client, loadRequests])

  const loadDetail = useCallback(async (changeRequestId: string) => {
    detailController.current?.abort()
    attachmentMutationController.current?.abort()
    attachmentMutationController.current = undefined
    attachmentMutationIntent.current += 1
    setAttachmentBusy(false)
    const intent = ++detailIntent.current
    const { controller, expectedGeneration } = beginOperation()
    detailController.current = controller
    selectedIdRef.current = changeRequestId
    setSelectedId(changeRequestId)
    setDetail(undefined)
    setDetailLoading(true)
    setDetailError(undefined)
    setAttachments([])
    setAttachmentLoading(true)
    setAttachmentError(undefined)
    setAttachmentNextCursor(undefined)
    setAttachmentCursorStack([])
    setApplyReport(undefined)
    setApplyReportLoading(true)
    setApplyReportError(undefined)
    try {
      const value = await client.request<ChangeRequestRecord>(`/change-requests/${changeRequestId}`, {
        signal: controller.signal,
      })
      if (controller.signal.aborted || expectedGeneration !== generation.current || intent !== detailIntent.current) return
      setDetail(value)
      setRequests((current) => current.map((item) => item.id === value.id
        ? { ...item, state: value.state, version: value.version, current_round_number: value.current_round_number }
        : item))
      try {
        const attachmentList = await client.request<ChangeRequestAttachmentList>(
          `/change-requests/${changeRequestId}/attachments/page?limit=25`,
          { signal: controller.signal },
        )
        if (!controller.signal.aborted && expectedGeneration === generation.current && intent === detailIntent.current) {
          setAttachments(attachmentList.items)
          setAttachmentNextCursor(attachmentList.page.next_cursor ?? undefined)
        }
      } catch (error) {
        if (!controller.signal.aborted && expectedGeneration === generation.current && intent === detailIntent.current) {
          setAttachmentError(error)
        }
      }
      try {
        const report = await client.request<GovernanceApplyReport>(
          `/change-requests/${changeRequestId}/apply-report`,
          { signal: controller.signal },
        )
        if (!controller.signal.aborted && expectedGeneration === generation.current && intent === detailIntent.current) {
          setApplyReport(report)
        }
      } catch (error) {
        if (!controller.signal.aborted && expectedGeneration === generation.current && intent === detailIntent.current) {
          setApplyReportError(error)
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
        setApplyReportLoading(false)
      }
    }
  }, [beginOperation, client])

  const loadAttachmentPage = useCallback(async (
    changeRequestId: string,
    cursor?: string,
  ) => {
    const { controller, expectedGeneration } = beginOperation()
    const expectedDetailIntent = detailIntent.current
    setAttachmentLoading(true)
    setAttachmentError(undefined)
    try {
      const query = new URLSearchParams({ limit: '25' })
      if (cursor) query.set('cursor', cursor)
      const value = await client.request<ChangeRequestAttachmentList>(
        `/change-requests/${changeRequestId}/attachments/page?${query.toString()}`,
        { signal: controller.signal },
      )
      if (
        controller.signal.aborted
        || expectedGeneration !== generation.current
        || expectedDetailIntent !== detailIntent.current
        || selectedIdRef.current !== changeRequestId
      ) return
      setAttachments(value.items)
      setAttachmentNextCursor(value.page.next_cursor ?? undefined)
    } catch (error) {
      if (
        !controller.signal.aborted
        && expectedGeneration === generation.current
        && expectedDetailIntent === detailIntent.current
        && selectedIdRef.current === changeRequestId
      ) {
        setAttachmentError(error)
      }
    } finally {
      controllers.current.delete(controller)
      if (
        expectedGeneration === generation.current
        && expectedDetailIntent === detailIntent.current
        && selectedIdRef.current === changeRequestId
      ) setAttachmentLoading(false)
    }
  }, [beginOperation, client])

  const nextAttachmentPage = useCallback(() => {
    if (!selectedId || !attachmentNextCursor || attachmentLoading) return
    setAttachmentCursorStack((current) => [...current, attachmentNextCursor].slice(-50))
    void loadAttachmentPage(selectedId, attachmentNextCursor)
  }, [attachmentLoading, attachmentNextCursor, loadAttachmentPage, selectedId])

  const previousAttachmentPage = useCallback(() => {
    if (!selectedId || attachmentCursorStack.length === 0 || attachmentLoading) return
    const previousCursor = attachmentCursorStack.length > 1
      ? attachmentCursorStack[attachmentCursorStack.length - 2]
      : undefined
    setAttachmentCursorStack((current) => current.slice(0, -1))
    void loadAttachmentPage(selectedId, previousCursor)
  }, [attachmentCursorStack, attachmentLoading, loadAttachmentPage, selectedId])

  const openDetail = useCallback((changeRequest: ChangeRequestSummary) => {
    setActionError(undefined)
    setReason('')
    preserveReasonForConflictRetry.current = false
    void loadDetail(changeRequest.id)
  }, [loadDetail])

  const closeDetail = useCallback(() => {
    detailController.current?.abort()
    detailController.current = undefined
    attachmentMutationController.current?.abort()
    attachmentMutationController.current = undefined
    attachmentMutationIntent.current += 1
    detailIntent.current += 1
    selectedIdRef.current = undefined
    setSelectedId(undefined)
    setDetail(undefined)
    setDetailLoading(false)
    setDetailError(undefined)
    setAttachments([])
    setAttachmentLoading(false)
    setAttachmentBusy(false)
    setAttachmentError(undefined)
    setAttachmentNextCursor(undefined)
    setAttachmentCursorStack([])
    setApplyReport(undefined)
    setApplyReportLoading(false)
    setApplyReportError(undefined)
    setActionError(undefined)
    setPendingAction(undefined)
    setRevision(undefined)
    setReason('')
    preserveReasonForConflictRetry.current = false
  }, [])

  const openAction = useCallback((action: ChangeActionHint, actionReason?: string) => {
    setActionError(undefined)
    if (actionReason?.trim()) {
      setReason(actionReason.trim())
    } else if (!preserveReasonForConflictRetry.current) {
      setReason('')
    }
    preserveReasonForConflictRetry.current = false
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
    attachmentMutationController.current?.abort()
    const { controller, expectedGeneration } = beginOperation()
    attachmentMutationController.current = controller
    const intent = ++attachmentMutationIntent.current
    const expectedDetailIntent = detailIntent.current
    const changeRequestId = current.id
    setAttachmentBusy(true)
    setAttachmentError(undefined)
    try {
      for (const file of files) {
        const pendingUploadId = attachmentUploadIds.current.get(file)
        if (pendingUploadId) {
          try {
            await resumeAttachmentUpload(
              client,
              changeRequestId,
              pendingUploadId,
              { signal: controller.signal },
            )
            attachmentUploadIds.current.delete(file)
            continue
          } catch (error) {
            if (!(error instanceof ApiError && error.problem.status === 404)) throw error
            attachmentUploadIds.current.delete(file)
          }
        }
        const uploadId = crypto.randomUUID()
        attachmentUploadIds.current.set(file, uploadId)
        try {
          await uploadAndFinalizeAttachment(
            client,
            changeRequestId,
            kind,
            file,
            { signal: controller.signal, uploadId },
          )
          attachmentUploadIds.current.delete(file)
        } catch (error) {
          if (
            error instanceof ApiError
            && error.problem.status !== 408
            && error.problem.status < 500
          ) attachmentUploadIds.current.delete(file)
          throw error
        }
      }
      const value = await client.request<ChangeRequestAttachmentList>(
        `/change-requests/${changeRequestId}/attachments/page?limit=25`,
        { signal: controller.signal },
      )
      if (
        controller.signal.aborted
        || expectedGeneration !== generation.current
        || intent !== attachmentMutationIntent.current
        || expectedDetailIntent !== detailIntent.current
        || selectedIdRef.current !== changeRequestId
      ) return
      setAttachments(value.items)
      setAttachmentNextCursor(value.page.next_cursor ?? undefined)
      setAttachmentCursorStack([])
    } catch (error) {
      if (
        !controller.signal.aborted
        && expectedGeneration === generation.current
        && intent === attachmentMutationIntent.current
        && expectedDetailIntent === detailIntent.current
        && selectedIdRef.current === changeRequestId
      ) {
        setAttachmentError(error)
        throw error
      }
    } finally {
      controllers.current.delete(controller)
      if (attachmentMutationController.current === controller) {
        attachmentMutationController.current = undefined
      }
      if (
        expectedGeneration === generation.current
        && intent === attachmentMutationIntent.current
        && expectedDetailIntent === detailIntent.current
        && selectedIdRef.current === changeRequestId
      ) setAttachmentBusy(false)
    }
  }, [attachmentBusy, beginOperation, client, detail])

  const resumePendingAttachments = useCallback(async () => {
    const current = detail
    if (!current || attachmentBusy) return
    attachmentMutationController.current?.abort()
    const { controller, expectedGeneration } = beginOperation()
    attachmentMutationController.current = controller
    const intent = ++attachmentMutationIntent.current
    const expectedDetailIntent = detailIntent.current
    const changeRequestId = current.id
    setAttachmentBusy(true)
    setAttachmentError(undefined)
    try {
      const recovery = await resumeStoredAttachmentUploads(
        client,
        changeRequestId,
        current.current_round_id,
        { signal: controller.signal },
      )
      const value = await client.request<ChangeRequestAttachmentList>(
        `/change-requests/${changeRequestId}/attachments/page?limit=25`,
        { signal: controller.signal },
      )
      if (
        controller.signal.aborted
        || expectedGeneration !== generation.current
        || intent !== attachmentMutationIntent.current
        || expectedDetailIntent !== detailIntent.current
        || selectedIdRef.current !== changeRequestId
      ) return
      setAttachments(value.items)
      setAttachmentNextCursor(value.page.next_cursor ?? undefined)
      setAttachmentCursorStack([])
      if (recovery.error) setAttachmentError(recovery.error)
    } catch (error) {
      if (
        !controller.signal.aborted
        && expectedGeneration === generation.current
        && intent === attachmentMutationIntent.current
        && expectedDetailIntent === detailIntent.current
        && selectedIdRef.current === changeRequestId
      ) setAttachmentError(error)
    } finally {
      controllers.current.delete(controller)
      if (attachmentMutationController.current === controller) {
        attachmentMutationController.current = undefined
      }
      if (
        expectedGeneration === generation.current
        && intent === attachmentMutationIntent.current
        && expectedDetailIntent === detailIntent.current
        && selectedIdRef.current === changeRequestId
      ) setAttachmentBusy(false)
    }
  }, [attachmentBusy, beginOperation, client, detail])

  const confirmAction = async () => {
    const action = pendingAction
    const current = detail
    if (!action || !current || busy || !reason.trim()) return
    const { controller, expectedGeneration } = beginOperation()
    setBusy(true)
    setActionError(undefined)
    let approvalPersisted = false
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
      let next = await client.request<ChangeRequestRecord>(path, {
        method: 'POST',
        idempotencyKey: newIdempotencyKey('change-action'),
        ifMatch: `"${current.version}"`,
        signal: controller.signal,
        body: JSON.stringify(body),
      })
      if (action.kind === 'APPROVAL' && action.stage === 'REVIEW' && next.state === 'IN_REVIEW') {
        approvalPersisted = true
        next = await client.request<ChangeRequestRecord>(
          `/change-requests/${current.id}/transitions`,
          {
            method: 'POST',
            idempotencyKey: newIdempotencyKey('change-review-transition'),
            ifMatch: `"${next.version}"`,
            signal: controller.signal,
            body: JSON.stringify({
              target_state: 'TESTING',
              reason,
            }),
          },
        )
      }
      if (controller.signal.aborted || expectedGeneration !== generation.current) return
      setPendingAction(undefined)
      setDetail(next)
      setRequests((values) => {
        if (stateFilter && next.state !== stateFilter) return values.filter((item) => item.id !== next.id)
        return values.map((item) => item.id === next.id
          ? { ...item, state: next.state, version: next.version, current_round_number: next.current_round_number }
          : item)
      })
      setReason('')
      preserveReasonForConflictRetry.current = false
    } catch (error) {
      if (controller.signal.aborted || expectedGeneration !== generation.current) return
      setPendingAction(undefined)
      setActionError(error)
      if (approvalPersisted || (error instanceof ApiError && error.problem.status === 409)) {
        preserveReasonForConflictRetry.current = true
        await loadDetail(current.id)
      }
    } finally {
      controllers.current.delete(controller)
      if (expectedGeneration === generation.current) setBusy(false)
    }
  }

  const visibleRequests = useMemo(() => {
    const query = textFilter.trim().toLocaleLowerCase()
    return requests.filter((request) => {
      if (stateFilter && request.state !== stateFilter) return false
      if (!query) return true
      return [
      request.number, request.title, request.requester_id, request.first_item.aspect_name, request.classification,
      ].some((value) => value.toLocaleLowerCase().includes(query))
    })
  }, [requests, stateFilter, textFilter])
  const overviewColumnWidths = useMemo(() => proportionalOverviewWidths(overview), [overview])
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

  const nextPage = () => {
    if (!nextCursor || listLoading) return
    const stack = [...cursorStack, nextCursor].slice(-50)
    setCursorStack(stack)
    void loadRequests(stack.at(-1))
  }

  const previousPage = () => {
    if (!cursorStack.length || listLoading) return
    const stack = cursorStack.slice(0, -1)
    setCursorStack(stack)
    void loadRequests(stack.at(-1))
  }

  const refreshFirstPage = () => {
    setCursorStack([])
    void loadRequests()
  }

  return (
    <section className="governance-page">
      <PageTitle
        icon="CR"
        eyebrow="Four-eyes Governance"
        title="변경 요청과 승인"
        description="타입이 지정된 변경을 검토하고 Maker-Checker 상태 전이와 적용 증거를 관리합니다."
        actions={<div className="page-title-actions"><button type="button" className="button button-secondary" disabled={listLoading} onClick={refreshFirstPage}>새로고침</button><button type="button" className="button" onClick={() => { setRevision(undefined); setCreateOpen(true) }}>신규 CR 신청</button></div>}
      />

      <div className="governance-toolbar panel">
        <div className="governance-window-summary" aria-live="polite">
          <span className="governance-kicker">Authorized window</span>
          <strong>현재 조회된 요청 · 페이지당 최대 25건</strong>
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
        <header><span className="governance-kicker">CR Status Overview</span><small>현재 권한으로 열람 가능한 DataHub 스키마와 같은 서버 읽기 창의 요청을 결합합니다. 최대 100개 스키마와 시스템별 20명 담당자를 표시합니다.{overviewTruncated ? ' 추가 항목은 저사양 보호를 위해 생략되었습니다.' : ''}</small></header>
        <div className="governance-status-scroll"><table><colgroup>{overviewColumnWidths.map((width, index) => <col key={index} style={{ width: `${width}%` }} />)}</colgroup><thead><tr><th>스키마</th><th>시스템</th><th>담당자</th><th>데이터셋별 미진행</th><th>CR 전체</th><th>접수완료</th><th>재검토</th><th>변경 / TEST</th><th>완료검토</th><th>완료</th></tr></thead><tbody>
          {overview.length === 0 ? <tr><td colSpan={10}>{listLoading ? '스키마별 현황을 확인하는 중' : '현재 권한 범위에서 표시할 DataHub 스키마가 없습니다.'}</td></tr> : overview.map((row) => {
            const expanded = expandedSchemas.has(schemaKey(row))
            return <Fragment key={schemaKey(row)}>
              <tr className="governance-schema-summary-row">
                <td><button type="button" className="governance-schema-toggle" aria-expanded={expanded} onClick={() => toggleSchema(row)}><strong className="governance-overview-primary" title={row.schema_name}>{row.schema_name}</strong><small className="governance-overview-secondary" title={`${row.platform} · ${row.database_name}`}>{row.platform} · {row.database_name}</small></button></td>
                <td><span className="governance-overview-primary" title={row.system_name ?? '시스템 미지정'}>{row.system_name ?? '시스템 미지정'}</span>{row.system_code ? <small className="governance-overview-secondary" title={row.system_code}>{row.system_code}</small> : null}</td>
                <td><span className="governance-overview-primary" title={row.assignees.length ? `${row.assignees.length.toLocaleString()}명` : '미지정'}>{row.assignees.length ? `${row.assignees.length.toLocaleString()}명` : '미지정'}</span></td>
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
        hardwareWebauthnEnabled={hardwareWebauthnEnabled}
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
        <div className="governance-list-pagination" aria-label="변경 요청 페이지 이동">
          <button className="button button-secondary" type="button" disabled={listLoading || !cursorStack.length} onClick={previousPage}>이전</button>
          <button className="button button-secondary" type="button" disabled={listLoading || !nextCursor} onClick={nextPage}>다음</button>
        </div>
      </section>

      <ChangeRequestDetailDialog
        key={selectedId ?? 'closed'}
        open={Boolean(selectedId) && !revision}
        client={client}
        fallback={undefined}
        value={detail}
        loading={detailLoading}
        busy={busy}
        error={detailError}
        actionError={actionError}
        attachments={attachments}
        attachmentLoading={attachmentLoading}
        attachmentBusy={attachmentBusy}
        attachmentError={attachmentError}
        attachmentHasNext={Boolean(attachmentNextCursor)}
        attachmentHasPrevious={attachmentCursorStack.length > 0}
        applyReport={applyReport}
        applyReportLoading={applyReportLoading}
        applyReportError={applyReportError}
        onClose={closeDetail}
        onEdit={() => { if (detail?.revision_allowed) setRevision(detail) }}
        onRefresh={() => { if (selectedId) void loadDetail(selectedId) }}
        onAction={openAction}
        onDownloadAttachment={(attachment) => { void downloadAttachment(attachment) }}
        onNextAttachmentPage={nextAttachmentPage}
        onPreviousAttachmentPage={previousAttachmentPage}
        onUploadAttachments={uploadAttachments}
        onResumePendingAttachments={resumePendingAttachments}
        onStepUp={onStepUp}
        onPasswordReauth={onPasswordReauth}
        onEnroll={onEnroll}
        hardwareWebauthnEnabled={hardwareWebauthnEnabled}
      />
      {(createOpen || revision) && <ChangeRequestCreateDialog
        key={revision ? `revision-${revision.id}-${revision.current_round_id}` : 'create'}
        open
        client={client}
        requesterName={requesterName}
        requesterEmail={requesterEmail}
        revision={revision}
        onClose={() => { setCreateOpen(false); setRevision(undefined) }}
        onCreated={(value) => {
          setCreateOpen(false)
          setRevision(undefined)
          if (selectedId === value.id) setDetail(value)
          void refreshFirstPage()
        }}
      />}
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
