import { ApiError, type ApiClient } from '../../api/client'
import type {
  ChangeRequestAttachmentUpload,
  ChangeRequestAttachmentUploadList,
} from '../../api/types'

type AttachmentKind = 'REQUEST' | 'TEST'

export const MAXIMUM_ATTACHMENT_BYTES = 10 * 1024 * 1024
export const MAXIMUM_ATTACHMENT_FILES = 10
export const MAXIMUM_ATTACHMENT_TOTAL_BYTES = 32 * 1024 * 1024

export interface AttachmentUploadOptions {
  signal?: AbortSignal
  maximumStatusReads?: number
  maximumDurationMs?: number
  pollDelayMs?: number
  uploadId?: string
}

export function attachmentSelectionError(files: File[]): Error | undefined {
  if (files.some((file) => file.size > MAXIMUM_ATTACHMENT_BYTES)) {
    return new Error('첨부파일은 파일당 10 MiB 이하만 등록할 수 있습니다.')
  }
  if (files.length > MAXIMUM_ATTACHMENT_FILES) {
    return new Error(`첨부파일은 한 요청에 최대 ${MAXIMUM_ATTACHMENT_FILES}개까지 선택할 수 있습니다.`)
  }
  if (files.reduce((total, file) => total + file.size, 0) > MAXIMUM_ATTACHMENT_TOTAL_BYTES) {
    return new Error('첨부파일의 선택 합계는 32 MiB 이하여야 합니다.')
  }
  return undefined
}

function pendingEvidenceError(): Error {
  return new Error(
    '첨부파일은 접수되었지만 독립 저장 증빙을 기다리고 있습니다. '
      + '잠시 후 변경요청 상세 화면에서 다시 확인하세요.',
  )
}

function abortReason(signal: AbortSignal): Error {
  return signal.reason instanceof Error
    ? signal.reason
    : new DOMException('The attachment operation was aborted.', 'AbortError')
}

function isAmbiguousDelivery(error: unknown): boolean {
  return !(error instanceof ApiError)
    || error.problem.status === 408
    || error.problem.status >= 500
}

function boundedSignal(
  parent: AbortSignal | undefined,
  maximumDurationMs: number,
): { signal: AbortSignal; dispose: () => void } {
  const controller = new AbortController()
  const forwardAbort = () => controller.abort(parent ? abortReason(parent) : undefined)
  if (parent?.aborted) forwardAbort()
  else parent?.addEventListener('abort', forwardAbort, { once: true })
  const timeout = window.setTimeout(
    () => controller.abort(pendingEvidenceError()),
    maximumDurationMs,
  )
  return {
    signal: controller.signal,
    dispose: () => {
      window.clearTimeout(timeout)
      parent?.removeEventListener('abort', forwardAbort)
    },
  }
}

function wait(milliseconds: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted) return Promise.reject(abortReason(signal))
  if (milliseconds <= 0) return Promise.resolve()
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      signal.removeEventListener('abort', abort)
      resolve()
    }, milliseconds)
    const abort = () => {
      window.clearTimeout(timeout)
      reject(abortReason(signal))
    }
    signal.addEventListener('abort', abort, { once: true })
  })
}

function waitUntilVisible(signal: AbortSignal): Promise<void> {
  if (signal.aborted) return Promise.reject(abortReason(signal))
  if (!document.hidden) return Promise.resolve()
  return new Promise((resolve, reject) => {
    const visibilityChanged = () => {
      if (document.hidden) return
      dispose()
      resolve()
    }
    const aborted = () => {
      dispose()
      reject(abortReason(signal))
    }
    const dispose = () => {
      document.removeEventListener('visibilitychange', visibilityChanged)
      signal.removeEventListener('abort', aborted)
    }
    document.addEventListener('visibilitychange', visibilityChanged)
    signal.addEventListener('abort', aborted, { once: true })
  })
}

function evidenceFailure(intent: ChangeRequestAttachmentUpload): Error {
  return new Error(
    `첨부파일의 독립 저장 증빙에 실패했습니다: ${intent.failure_code ?? 'UNKNOWN_FAILURE'}`,
  )
}

async function finalizeWhenStored(
  client: ApiClient,
  initial: ChangeRequestAttachmentUpload,
  signal: AbortSignal,
  maximumStatusReads: number,
  pollDelayMs: number,
): Promise<void> {
  let current = initial
  for (let reads = 0; reads <= maximumStatusReads; reads += 1) {
    if (current.state === 'FAILED') throw evidenceFailure(current)
    if (current.state === 'FINALIZED') return
    if (current.state === 'STORED') {
      let lastAmbiguousError: unknown
      for (let attempt = 0; attempt < 2; attempt += 1) {
        try {
          await client.request(current.finalize_url, { method: 'POST', signal })
          return
        } catch (error) {
          if (signal.aborted) throw abortReason(signal)
          if (!isAmbiguousDelivery(error)) throw error
          lastAmbiguousError = error
          let observed: ChangeRequestAttachmentUpload
          try {
            observed = await client.request<ChangeRequestAttachmentUpload>(
              current.status_url,
              { signal },
            )
          } catch {
            throw error
          }
          if (observed.state === 'FINALIZED') return
          if (observed.state === 'FAILED') throw evidenceFailure(observed)
          if (observed.state !== 'STORED') throw error
          current = observed
        }
      }
      throw lastAmbiguousError
    }
    if (reads === maximumStatusReads) break
    await waitUntilVisible(signal)
    await wait(pollDelayMs, signal)
    await waitUntilVisible(signal)
    current = await client.request<ChangeRequestAttachmentUpload>(
      current.status_url,
      { signal },
    )
  }
  throw pendingEvidenceError()
}

async function recoverLostResponse(
  client: ApiClient,
  changeRequestId: string,
  uploadId: string,
  signal: AbortSignal,
  maximumStatusReads: number,
  pollDelayMs: number,
): Promise<boolean> {
  let exact: ChangeRequestAttachmentUpload
  try {
    exact = await client.request<ChangeRequestAttachmentUpload>(
      `/change-requests/${changeRequestId}/attachment-uploads/${uploadId}`,
      { signal },
    )
  } catch {
    return false
  }
  if (exact.id !== uploadId || exact.change_request_id !== changeRequestId) return false
  await finalizeWhenStored(
    client,
    exact,
    signal,
    maximumStatusReads,
    pollDelayMs,
  )
  return true
}

export async function uploadAndFinalizeAttachment(
  client: ApiClient,
  changeRequestId: string,
  kind: AttachmentKind,
  file: File,
  options: AttachmentUploadOptions = {},
): Promise<void> {
  const selectionError = attachmentSelectionError([file])
  if (selectionError) throw selectionError
  const uploadId = options.uploadId ?? crypto.randomUUID()
  const maximumStatusReads = options.maximumStatusReads ?? 20
  const pollDelayMs = options.pollDelayMs ?? 1_000
  const bounded = boundedSignal(options.signal, options.maximumDurationMs ?? 120_000)
  const body = new FormData()
  body.set('kind', kind)
  body.set('upload_id', uploadId)
  body.set('file', file)
  try {
    let intent: ChangeRequestAttachmentUpload
    try {
      intent = await client.request<ChangeRequestAttachmentUpload>(
        `/change-requests/${changeRequestId}/attachments`,
        { method: 'POST', body, signal: bounded.signal },
      )
    } catch (error) {
      if (bounded.signal.aborted) throw abortReason(bounded.signal)
      if (!isAmbiguousDelivery(error)) throw error
      if (await recoverLostResponse(
        client,
        changeRequestId,
        uploadId,
        bounded.signal,
        maximumStatusReads,
        pollDelayMs,
      )) return
      throw error
    }
    if (intent.id !== uploadId || intent.change_request_id !== changeRequestId) {
      throw new Error('첨부파일 업로드 응답의 작업 식별자가 요청과 일치하지 않습니다.')
    }
    await finalizeWhenStored(
      client,
      intent,
      bounded.signal,
      maximumStatusReads,
      pollDelayMs,
    )
  } finally {
    bounded.dispose()
  }
}

export async function resumeAttachmentUpload(
  client: ApiClient,
  changeRequestId: string,
  uploadId: string,
  options: Omit<AttachmentUploadOptions, 'uploadId'> = {},
): Promise<void> {
  const bounded = boundedSignal(options.signal, options.maximumDurationMs ?? 120_000)
  try {
    const intent = await client.request<ChangeRequestAttachmentUpload>(
      `/change-requests/${changeRequestId}/attachment-uploads/${uploadId}`,
      { signal: bounded.signal },
    )
    if (intent.id !== uploadId || intent.change_request_id !== changeRequestId) {
      throw new Error('첨부파일 상태 응답의 작업 식별자가 요청과 일치하지 않습니다.')
    }
    await finalizeWhenStored(
      client,
      intent,
      bounded.signal,
      options.maximumStatusReads ?? 20,
      options.pollDelayMs ?? 1_000,
    )
  } finally {
    bounded.dispose()
  }
}

export async function resumeStoredAttachmentUploads(
  client: ApiClient,
  changeRequestId: string,
  currentRoundId: string,
  options: Pick<AttachmentUploadOptions, 'signal' | 'maximumDurationMs'> = {},
): Promise<{ finalized: number; failed: number; error?: Error }> {
  const bounded = boundedSignal(options.signal, options.maximumDurationMs ?? 15_000)
  try {
    const response = await client.request<ChangeRequestAttachmentUploadList>(
      `/change-requests/${changeRequestId}/attachment-uploads`
        + `?round_id=${encodeURIComponent(currentRoundId)}&limit=${MAXIMUM_ATTACHMENT_FILES}`,
      { signal: bounded.signal },
    )
    const stored = response.items.filter((item) => (
      item.round_id === currentRoundId && item.state === 'STORED'
    )).slice(0, MAXIMUM_ATTACHMENT_FILES)
    let finalized = 0
    let firstError: Error | undefined
    for (const intent of stored) {
      try {
        await finalizeWhenStored(client, intent, bounded.signal, 0, 0)
        finalized += 1
      } catch (error) {
        firstError ??= error instanceof Error
          ? error
          : new Error('미완료 첨부파일을 다시 확인하지 못했습니다.')
      }
    }
    return {
      finalized,
      failed: stored.length - finalized,
      ...(firstError ? { error: firstError } : {}),
    }
  } finally {
    bounded.dispose()
  }
}
