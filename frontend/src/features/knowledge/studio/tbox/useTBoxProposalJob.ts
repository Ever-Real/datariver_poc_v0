import { sha256 } from 'hash-wasm'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { ApiClient } from '../../../../api/client'
import {
  cancelKnowledgeStudioTBoxProposalJob,
  completeKnowledgeStudioSourceUpload,
  createKnowledgeStudioTBoxProposalJob,
  getKnowledgeStudioSourceUpload,
  getKnowledgeStudioTBoxProposal,
  getKnowledgeStudioTBoxProposalJob,
  initiateKnowledgeStudioSourceUpload,
  listKnowledgeStudioTBoxProposalJobs,
  newKnowledgeStudioIdempotencyKey,
  presignKnowledgeStudioSourceUploadPart,
  retryKnowledgeStudioTBoxProposalJob,
  uploadKnowledgeStudioSourceUploadPart,
  type KnowledgeStudioProposalJob,
  type KnowledgeStudioProposalJobState,
  type KnowledgeStudioSourceUpload,
  type KnowledgeStudioTBoxProposal,
} from '../knowledgeStudioApi'

const MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
const TERMINAL_UPLOAD_STATES = new Set<KnowledgeStudioSourceUpload['state']>([
  'ACCEPTED',
  'REJECTED',
  'ABORTED',
  'EXPIRED',
])
const ACTIVE_JOB_STATES = new Set<KnowledgeStudioProposalJobState>([
  'QUEUED',
  'RUNNING',
  'RETRY_WAIT',
  'CANCEL_REQUESTED',
])
const RETRYABLE_JOB_STATES = new Set<KnowledgeStudioProposalJobState>([
  'FAILED',
  'STALE',
  'CANCELLED',
])

const DOCUMENT_MEDIA = new Map<string, {
  contentType: string
  browserTypes: ReadonlySet<string>
}>([
  ['.pdf', {
    contentType: 'application/pdf',
    browserTypes: new Set(['application/pdf']),
  }],
  ['.csv', {
    contentType: 'text/csv',
    browserTypes: new Set(['text/csv', 'application/vnd.ms-excel']),
  }],
  ['.txt', {
    contentType: 'text/plain',
    browserTypes: new Set(['text/plain']),
  }],
  ['.json', {
    contentType: 'application/json',
    browserTypes: new Set(['application/json', 'text/json']),
  }],
  ['.xml', {
    contentType: 'application/xml',
    browserTypes: new Set(['application/xml', 'text/xml']),
  }],
  ['.html', {
    contentType: 'text/html',
    browserTypes: new Set(['text/html']),
  }],
  ['.htm', {
    contentType: 'text/html',
    browserTypes: new Set(['text/html']),
  }],
  ['.docx', {
    contentType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    browserTypes: new Set([
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    ]),
  }],
  ['.xlsx', {
    contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    browserTypes: new Set([
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    ]),
  }],
  ['.pptx', {
    contentType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    browserTypes: new Set([
      'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    ]),
  }],
])

type DocumentOperationPhase =
  | 'IDLE'
  | 'HASHING'
  | 'UPLOADING'
  | 'SOURCE_VALIDATION'
  | 'JOB'

interface StartDocumentProposal {
  file: File
  mode: 'MERGE_INTO_CURRENT' | 'APPEND_LAYER'
  targetBlockId?: string
}

interface StartCatalogProposal {
  assetId: string
  selectedFieldPaths: string[]
  expectedSelectionFingerprint: string
  mode: 'MERGE_INTO_CURRENT' | 'APPEND_LAYER'
  targetBlockId?: string
}

interface UseTBoxProposalJobOptions {
  client: ApiClient
  draftId: string
  draftEtag: string
  pollIntervalMs?: number
  maximumPolls?: number
}

export function isActiveTBoxProposalJob(job?: KnowledgeStudioProposalJob): boolean {
  return Boolean(job && ACTIVE_JOB_STATES.has(job.state))
}

export function canRetryTBoxProposalJob(job?: KnowledgeStudioProposalJob): boolean {
  return Boolean(job && RETRYABLE_JOB_STATES.has(job.state))
}

export function validateTBoxDocument(file: Pick<File, 'name' | 'size' | 'type'>): string {
  const suffix = file.name.toLowerCase().match(/\.[^.]+$/)?.[0] ?? ''
  const media = DOCUMENT_MEDIA.get(suffix)
  if (!media) {
    throw new Error('지원 형식은 PDF, CSV, TXT, JSON, XML, HTML, DOCX, XLSX, PPTX입니다.')
  }
  const browserType = file.type.trim().toLowerCase()
  if (browserType && !media.browserTypes.has(browserType)) {
    throw new Error('파일 확장자와 브라우저가 확인한 문서 형식이 일치하지 않습니다.')
  }
  if (file.size < 1) throw new Error('빈 문서는 분석할 수 없습니다.')
  if (file.size > MAX_DOCUMENT_BYTES) {
    throw new Error('Knowledge Studio 분석 문서는 최대 10 MiB입니다.')
  }
  return media.contentType
}

export async function sha256TBoxDocument(
  file: File,
  signal?: AbortSignal,
): Promise<string> {
  signal?.throwIfAborted()
  const bytes = await file.arrayBuffer()
  signal?.throwIfAborted()
  const digest = await sha256(new Uint8Array(bytes))
  signal?.throwIfAborted()
  return digest
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

function jobFailureMessage(job: KnowledgeStudioProposalJob): string {
  if (job.state === 'CANCELLED') return 'T-Box Proposal 작업이 취소되었습니다.'
  if (job.state === 'STALE') {
    return '작업 중 Draft 정본이 변경되어 이 Proposal 작업은 만료되었습니다.'
  }
  return `T-Box Proposal 작업이 실패했습니다. (${job.last_failure_code ?? '원인 미상'})`
}

async function waitForVisibleInterval(milliseconds: number, signal: AbortSignal): Promise<void> {
  signal.throwIfAborted()
  if (document.visibilityState !== 'visible') {
    await new Promise<void>((resolve, reject) => {
      const onAbort = () => {
        cleanup()
        reject(new DOMException('Aborted', 'AbortError'))
      }
      const onVisibility = () => {
        if (document.visibilityState !== 'visible') return
        cleanup()
        resolve()
      }
      const cleanup = () => {
        signal.removeEventListener('abort', onAbort)
        document.removeEventListener('visibilitychange', onVisibility)
      }
      signal.addEventListener('abort', onAbort, { once: true })
      document.addEventListener('visibilitychange', onVisibility)
    })
  }
  await new Promise<void>((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      signal.removeEventListener('abort', onAbort)
      resolve()
    }, milliseconds)
    const onAbort = () => {
      window.clearTimeout(timeout)
      reject(new DOMException('Aborted', 'AbortError'))
    }
    signal.addEventListener('abort', onAbort, { once: true })
  })
}

export function useTBoxProposalJob({
  client,
  draftId,
  draftEtag,
  pollIntervalMs = 1_000,
  maximumPolls = 120,
}: UseTBoxProposalJobOptions) {
  const [upload, setUpload] = useState<KnowledgeStudioSourceUpload>()
  const [job, setJob] = useState<KnowledgeStudioProposalJob>()
  const [jobEtag, setJobEtag] = useState('')
  const [proposal, setProposal] = useState<KnowledgeStudioTBoxProposal>()
  const [phase, setPhase] = useState<DocumentOperationPhase>('IDLE')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [pollingExhausted, setPollingExhausted] = useState(false)
  const [restoredFromHistory, setRestoredFromHistory] = useState(false)
  const [pollGeneration, setPollGeneration] = useState(0)
  const controllers = useRef(new Set<AbortController>())
  const operationGeneration = useRef(0)
  const operationStarted = useRef(false)
  const currentJob = useRef<KnowledgeStudioProposalJob | undefined>(undefined)

  const beginOperation = useCallback(() => {
    const controller = new AbortController()
    controllers.current.add(controller)
    return {
      controller,
      generation: operationGeneration.current,
    }
  }, [])

  const finishOperation = useCallback((controller: AbortController) => {
    controllers.current.delete(controller)
  }, [])

  const reset = useCallback(() => {
    operationGeneration.current += 1
    for (const controller of controllers.current) controller.abort()
    controllers.current.clear()
    operationStarted.current = false
    setUpload(undefined)
    setJob(undefined)
    setJobEtag('')
    setProposal(undefined)
    setPhase('IDLE')
    setBusy(false)
    setError('')
    setPollingExhausted(false)
    setRestoredFromHistory(false)
  }, [])

  const loadTerminalJobResult = useCallback(async (
    terminalJob: KnowledgeStudioProposalJob,
    signal: AbortSignal,
    generation: number,
  ): Promise<void> => {
    if (isActiveTBoxProposalJob(terminalJob)) return
    if (terminalJob.state !== 'SUCCEEDED') {
      setError(jobFailureMessage(terminalJob))
      return
    }
    if (!terminalJob.result_proposal_id) {
      setError('완료된 T-Box Proposal 작업에 결과 Proposal ID가 없습니다.')
      return
    }
    const exactProposal = await getKnowledgeStudioTBoxProposal(
      client,
      draftId,
      terminalJob.result_proposal_id,
      signal,
    )
    if (generation !== operationGeneration.current) return
    if (
      exactProposal.id !== terminalJob.result_proposal_id
      || exactProposal.draft_id !== draftId
    ) {
      setError('완료된 T-Box Proposal 결과가 현재 Draft와 일치하지 않습니다.')
      return
    }
    if (exactProposal.state !== 'READY') {
      setError(`완료된 T-Box Proposal은 다시 적용할 수 없는 상태입니다. (${exactProposal.state})`)
      return
    }
    setProposal(exactProposal)
    setError('')
  }, [client, draftId])

  useEffect(() => {
    operationGeneration.current += 1
    operationStarted.current = false
    setRestoredFromHistory(false)
    const controller = new AbortController()
    const activeControllers = controllers.current
    activeControllers.add(controller)
    const generation = operationGeneration.current
    void listKnowledgeStudioTBoxProposalJobs(client, draftId, undefined, controller.signal)
      .then(async (page) => {
        if (
          controller.signal.aborted
          || generation !== operationGeneration.current
          || operationStarted.current
        ) return
        const resumable = page.items[0]
        if (!resumable || resumable.draft_id !== draftId) return
        const response = await getKnowledgeStudioTBoxProposalJob(
          client,
          draftId,
          resumable.id,
          controller.signal,
        )
        if (
          controller.signal.aborted
          || generation !== operationGeneration.current
          || operationStarted.current
        ) return
        if (
          response.data.id !== resumable.id
          || response.data.draft_id !== draftId
        ) {
          setError('최근 T-Box Proposal 작업이 현재 Draft와 일치하지 않습니다.')
          return
        }
        setRestoredFromHistory(true)
        setJob(response.data)
        setJobEtag(response.etag ?? '')
        setPhase('JOB')
        setError('')
        await loadTerminalJobResult(response.data, controller.signal, generation)
      })
      .catch((next: unknown) => {
        if (!controller.signal.aborted && !isAbortError(next)) {
          setError(next instanceof Error ? next.message : '진행 중인 Proposal 작업을 조회하지 못했습니다.')
        }
      })
      .finally(() => finishOperation(controller))
    return () => {
      controller.abort()
      activeControllers.delete(controller)
    }
  }, [client, draftId, finishOperation, loadTerminalJobResult])

  useEffect(() => {
    currentJob.current = job
  }, [job])

  const activeJobId = isActiveTBoxProposalJob(job) ? job?.id : undefined
  useEffect(() => {
    const initialJob = currentJob.current
    if (!initialJob || !activeJobId) return
    const controller = new AbortController()
    const activeControllers = controllers.current
    activeControllers.add(controller)
    const generation = operationGeneration.current
    void (async () => {
      let current = initialJob
      for (let count = 0; count < maximumPolls; count += 1) {
        await waitForVisibleInterval(pollIntervalMs, controller.signal)
        const response = await getKnowledgeStudioTBoxProposalJob(
          client,
          draftId,
          current.id,
          controller.signal,
        )
        if (generation !== operationGeneration.current) return
        current = response.data
        setJob(current)
        setJobEtag(response.etag ?? '')
        if (isActiveTBoxProposalJob(current)) continue
        await loadTerminalJobResult(current, controller.signal, generation)
        return
      }
      setPollingExhausted(true)
      setError('작업이 계속 진행 중입니다. 상태 확인을 다시 시작해 주세요.')
    })()
      .catch((next: unknown) => {
        if (!controller.signal.aborted && !isAbortError(next)) {
          setError(next instanceof Error ? next.message : 'Proposal 작업 상태를 확인하지 못했습니다.')
        }
      })
      .finally(() => finishOperation(controller))
    return () => {
      controller.abort()
      activeControllers.delete(controller)
    }
  }, [
    activeJobId,
    client,
    draftId,
    finishOperation,
    loadTerminalJobResult,
    maximumPolls,
    pollGeneration,
    pollIntervalMs,
  ])

  const waitForAcceptedUpload = useCallback(async (
    initial: KnowledgeStudioSourceUpload,
    controller: AbortController,
    generation: number,
  ): Promise<KnowledgeStudioSourceUpload> => {
    let current = initial
    for (let count = 0; count < maximumPolls; count += 1) {
      if (TERMINAL_UPLOAD_STATES.has(current.state)) break
      await waitForVisibleInterval(pollIntervalMs, controller.signal)
      const response = await getKnowledgeStudioSourceUpload(
        client,
        draftId,
        current.id,
        controller.signal,
      )
      if (generation !== operationGeneration.current) {
        throw new DOMException('Aborted', 'AbortError')
      }
      current = response.data
      setUpload(current)
    }
    if (current.state === 'ACCEPTED') return current
    if (!TERMINAL_UPLOAD_STATES.has(current.state)) {
      throw new Error('문서 검증이 계속 진행 중입니다. 잠시 후 다시 시도하세요.')
    }
    throw new Error(
      `문서 검증이 승인되지 않았습니다. (${current.last_error_code ?? current.state})`,
    )
  }, [client, draftId, maximumPolls, pollIntervalMs])

  const start = useCallback(async ({
    file,
    mode,
    targetBlockId,
  }: StartDocumentProposal): Promise<void> => {
    if (busy || isActiveTBoxProposalJob(job)) return
    operationStarted.current = true
    operationGeneration.current += 1
    const { controller, generation } = beginOperation()
    setBusy(true)
    setError('')
    setPollingExhausted(false)
    setRestoredFromHistory(false)
    setProposal(undefined)
    setJob(undefined)
    setJobEtag('')
    try {
      const contentType = validateTBoxDocument(file)
      setPhase('HASHING')
      const sha256 = await sha256TBoxDocument(file, controller.signal)
      setPhase('UPLOADING')
      const initiated = await initiateKnowledgeStudioSourceUpload(
        client,
        draftId,
        {
          display_name: file.name,
          size_bytes: file.size,
          content_type: contentType,
          sha256,
        },
        newKnowledgeStudioIdempotencyKey(),
        controller.signal,
      )
      setUpload(initiated.data)
      const signed = await presignKnowledgeStudioSourceUploadPart(
        client,
        draftId,
        initiated.data.id,
        1,
        controller.signal,
      )
      const part = await uploadKnowledgeStudioSourceUploadPart(
        signed.url,
        file,
        controller.signal,
      )
      setPhase('SOURCE_VALIDATION')
      const completed = await completeKnowledgeStudioSourceUpload(
        client,
        draftId,
        initiated.data.id,
        [part],
        initiated.etag ?? '',
        newKnowledgeStudioIdempotencyKey(),
        controller.signal,
      )
      setUpload(completed.data)
      const accepted = await waitForAcceptedUpload(completed.data, controller, generation)
      const created = await createKnowledgeStudioTBoxProposalJob(
        client,
        draftId,
        {
          input_kind: 'DOCUMENT_SCHEMA',
          source_upload_id: accepted.id,
          source_manifest_version: accepted.version,
          target_block_id: mode === 'MERGE_INTO_CURRENT' ? targetBlockId : undefined,
          mode,
        },
        draftEtag,
        newKnowledgeStudioIdempotencyKey(),
        controller.signal,
      )
      if (generation !== operationGeneration.current) return
      setJob(created.data)
      setJobEtag(created.etag ?? '')
      setPhase('JOB')
      await loadTerminalJobResult(created.data, controller.signal, generation)
    } catch (next) {
      if (!controller.signal.aborted && !isAbortError(next)) {
        setError(next instanceof Error ? next.message : '문서 Proposal 작업을 시작하지 못했습니다.')
      }
    } finally {
      finishOperation(controller)
      if (generation === operationGeneration.current) setBusy(false)
    }
  }, [
    beginOperation,
    busy,
    client,
    draftEtag,
    draftId,
    finishOperation,
    job,
    loadTerminalJobResult,
    waitForAcceptedUpload,
  ])

  const startCatalog = useCallback(async ({
    assetId,
    selectedFieldPaths,
    expectedSelectionFingerprint,
    mode,
    targetBlockId,
  }: StartCatalogProposal): Promise<void> => {
    if (busy || isActiveTBoxProposalJob(job)) return
    if (!expectedSelectionFingerprint) {
      setError('카탈로그 메타데이터가 변경되었을 수 있습니다. Dataset을 다시 불러오세요.')
      return
    }
    operationStarted.current = true
    operationGeneration.current += 1
    const { controller, generation } = beginOperation()
    setBusy(true)
    setError('')
    setPollingExhausted(false)
    setRestoredFromHistory(false)
    setProposal(undefined)
    setJob(undefined)
    setJobEtag('')
    setPhase('JOB')
    try {
      const created = await createKnowledgeStudioTBoxProposalJob(
        client,
        draftId,
        {
          input_kind: 'CATALOG_SCHEMA',
          asset_id: assetId,
          selected_field_paths: selectedFieldPaths,
          expected_selection_fingerprint: expectedSelectionFingerprint,
          target_block_id: mode === 'MERGE_INTO_CURRENT' ? targetBlockId : undefined,
          mode,
        },
        draftEtag,
        newKnowledgeStudioIdempotencyKey(),
        controller.signal,
      )
      if (generation !== operationGeneration.current) return
      setJob(created.data)
      setJobEtag(created.etag ?? '')
      await loadTerminalJobResult(created.data, controller.signal, generation)
    } catch (next) {
      if (!controller.signal.aborted && !isAbortError(next)) {
        setError(next instanceof Error ? next.message : '카탈로그 Proposal 작업을 시작하지 못했습니다.')
      }
    } finally {
      finishOperation(controller)
      if (generation === operationGeneration.current) setBusy(false)
    }
  }, [
    beginOperation,
    busy,
    client,
    draftEtag,
    draftId,
    finishOperation,
    job,
    loadTerminalJobResult,
  ])

  const cancel = useCallback(async () => {
    if (!job || !jobEtag || !isActiveTBoxProposalJob(job) || busy) return
    const { controller, generation } = beginOperation()
    setBusy(true)
    setError('')
    try {
      const response = await cancelKnowledgeStudioTBoxProposalJob(
        client,
        draftId,
        job.id,
        'USER_REQUESTED',
        jobEtag,
        newKnowledgeStudioIdempotencyKey(),
        controller.signal,
      )
      if (generation !== operationGeneration.current) return
      setJob(response.data)
      setJobEtag(response.etag ?? '')
      setPollGeneration((value) => value + 1)
    } catch (next) {
      if (!controller.signal.aborted && !isAbortError(next)) {
        setError(next instanceof Error ? next.message : 'Proposal 작업을 취소하지 못했습니다.')
      }
    } finally {
      finishOperation(controller)
      if (generation === operationGeneration.current) setBusy(false)
    }
  }, [beginOperation, busy, client, draftId, finishOperation, job, jobEtag])

  const retry = useCallback(async () => {
    if (!job || !jobEtag || !canRetryTBoxProposalJob(job) || busy) return
    const { controller, generation } = beginOperation()
    setBusy(true)
    setError('')
    setPollingExhausted(false)
    setProposal(undefined)
    try {
      const response = await retryKnowledgeStudioTBoxProposalJob(
        client,
        draftId,
        job.id,
        jobEtag,
        newKnowledgeStudioIdempotencyKey(),
        controller.signal,
      )
      if (generation !== operationGeneration.current) return
      setJob(response.data)
      setJobEtag(response.etag ?? '')
      setPhase('JOB')
      setPollGeneration((value) => value + 1)
    } catch (next) {
      if (!controller.signal.aborted && !isAbortError(next)) {
        setError(next instanceof Error ? next.message : 'Proposal 작업을 재시도하지 못했습니다.')
      }
    } finally {
      finishOperation(controller)
      if (generation === operationGeneration.current) setBusy(false)
    }
  }, [beginOperation, busy, client, draftId, finishOperation, job, jobEtag])

  const resumePolling = useCallback(() => {
    if (!job || !isActiveTBoxProposalJob(job)) return
    setPollingExhausted(false)
    setError('')
    setPollGeneration((value) => value + 1)
  }, [job])

  useEffect(() => () => {
    operationGeneration.current += 1
    for (const controller of controllers.current) controller.abort()
    controllers.current.clear()
  }, [])

  return {
    upload,
    job,
    proposal,
    phase,
    busy,
    error,
    pollingExhausted,
    restoredFromHistory,
    active: isActiveTBoxProposalJob(job),
    canRetry: canRetryTBoxProposalJob(job),
    start,
    startCatalog,
    cancel,
    retry,
    resumePolling,
    reset,
  }
}
