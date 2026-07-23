import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, type RequestOptions } from '../../api/client'
import type { ChangeRequestAttachmentUpload } from '../../api/types'
import {
  attachmentSelectionError,
  resumeAttachmentUpload,
  resumeStoredAttachmentUploads,
  uploadAndFinalizeAttachment,
} from './attachmentUploads'

const changeRequestId = '00000000-0000-4000-8000-000000000301'
const attachmentId = '00000000-0000-4000-8000-000000000302'
const roundId = '00000000-0000-4000-8000-000000000303'

function intent(
  state: ChangeRequestAttachmentUpload['state'],
  patch: Partial<ChangeRequestAttachmentUpload> = {},
): ChangeRequestAttachmentUpload {
  return {
    id: attachmentId,
    change_request_id: changeRequestId,
    round_id: roundId,
    kind: 'REQUEST',
    original_name: 'evidence.txt',
    state,
    expected_size_bytes: 8,
    expected_content_sha256: 'a'.repeat(64),
    provider_checksum: state === 'STORED' ? 'etag:provider' : null,
    failure_code: null,
    status_url: `/change-requests/${changeRequestId}/attachment-uploads/${attachmentId}`,
    finalize_url:
      `/change-requests/${changeRequestId}/attachment-uploads/${attachmentId}/finalize`,
    ...patch,
  }
}

describe('governance attachment upload evidence', () => {
  afterEach(() => vi.restoreAllMocks())

  it('waits for independent STORED evidence before finalizing', async () => {
    const request = vi.fn(
      (path: string, options?: RequestOptions): Promise<unknown> => {
        if (path.endsWith('/attachments') && options?.method === 'POST') {
          return Promise.resolve(intent('STARTED'))
        }
        if (path === intent('STARTED').status_url) {
          return Promise.resolve(intent('STORED'))
        }
        if (path === intent('STARTED').finalize_url && options?.method === 'POST') {
          return Promise.resolve({})
        }
        throw new Error(`Unexpected request: ${path}`)
      },
    )

    await uploadAndFinalizeAttachment(
      { request } as never,
      changeRequestId,
      'REQUEST',
      new File(['evidence'], 'evidence.txt', { type: 'text/plain' }),
      { pollDelayMs: 0, uploadId: attachmentId },
    )

    expect(request.mock.calls.map(([path]) => path)).toEqual([
      `/change-requests/${changeRequestId}/attachments`,
      intent('STARTED').status_url,
      intent('STARTED').finalize_url,
    ])
  })

  it('recovers a lost POST response through the bounded current-owner intent list', async () => {
    const file = new File(['evidence'], 'evidence.txt', { type: 'text/plain' })
    const stored = intent('STORED', {
      expected_size_bytes: file.size,
    })
    const sameBytesDifferentUpload = intent('STORED', {
      id: '00000000-0000-4000-8000-000000000399',
      expected_size_bytes: file.size,
      status_url:
        `/change-requests/${changeRequestId}/attachment-uploads/`
        + '00000000-0000-4000-8000-000000000399',
      finalize_url:
        `/change-requests/${changeRequestId}/attachment-uploads/`
        + '00000000-0000-4000-8000-000000000399/finalize',
    })
    const request = vi.fn(
      (path: string, options?: RequestOptions): Promise<unknown> => {
        if (path.endsWith('/attachments') && options?.method === 'POST') {
          return Promise.reject(new TypeError('response lost'))
        }
        if (path === stored.status_url) return Promise.resolve(stored)
        if (path === stored.finalize_url && options?.method === 'POST') {
          return Promise.resolve({})
        }
        throw new Error(`Unexpected request: ${path}`)
      },
    )

    await uploadAndFinalizeAttachment(
      { request } as never,
      changeRequestId,
      'REQUEST',
      file,
      { pollDelayMs: 0, uploadId: attachmentId },
    )

    const recoveryCall = request.mock.calls.find(
      ([path]) =>
        path === stored.status_url,
    )
    expect(recoveryCall?.[1]?.signal).toBeInstanceOf(AbortSignal)
    expect(request.mock.calls.some(
      ([path]) => path === sameBytesDifferentUpload.finalize_url,
    )).toBe(false)
  })

  it('treats a finalized status as success after the finalize response is lost', async () => {
    const stored = intent('STORED')
    const request = vi.fn(
      (path: string, options?: RequestOptions): Promise<unknown> => {
        if (path.endsWith('/attachments') && options?.method === 'POST') {
          return Promise.resolve(stored)
        }
        if (path === stored.finalize_url && options?.method === 'POST') {
          return Promise.reject(new TypeError('finalize response lost'))
        }
        if (path === stored.status_url) return Promise.resolve(intent('FINALIZED'))
        throw new Error(`Unexpected request: ${path}`)
      },
    )

    await uploadAndFinalizeAttachment(
      { request } as never,
      changeRequestId,
      'REQUEST',
      new File(['evidence'], 'evidence.txt'),
      { pollDelayMs: 0, uploadId: attachmentId },
    )

    expect(request.mock.calls.map(([path]) => path)).toEqual([
      `/change-requests/${changeRequestId}/attachments`,
      stored.finalize_url,
      stored.status_url,
    ])
  })

  it('retries the same finalize URL when a gateway timeout leaves the intent STORED', async () => {
    const stored = intent('STORED')
    const gatewayTimeout = new ApiError({
      type: 'urn:test',
      title: 'Gateway timeout',
      status: 504,
      detail: 'upstream response was lost',
      code: 'gateway_timeout',
      request_id: 'request-504',
    })
    let finalizeReads = 0
    const request = vi.fn(
      (path: string, options?: RequestOptions): Promise<unknown> => {
        if (path.endsWith('/attachments') && options?.method === 'POST') {
          return Promise.resolve(stored)
        }
        if (path === stored.finalize_url && options?.method === 'POST') {
          finalizeReads += 1
          return finalizeReads === 1
            ? Promise.reject(gatewayTimeout)
            : Promise.resolve({})
        }
        if (path === stored.status_url) return Promise.resolve(stored)
        throw new Error(`Unexpected request: ${path}`)
      },
    )

    await uploadAndFinalizeAttachment(
      { request } as never,
      changeRequestId,
      'REQUEST',
      new File(['evidence'], 'evidence.txt'),
      { pollDelayMs: 0, uploadId: attachmentId },
    )

    expect(finalizeReads).toBe(2)
  })

  it('recovers an ambiguous gateway POST response through the exact upload ID', async () => {
    const stored = intent('STORED')
    const gatewayFailure = new ApiError({
      type: 'urn:test',
      title: 'Bad gateway',
      status: 502,
      detail: 'upstream response was lost',
      code: 'bad_gateway',
      request_id: 'request-502',
    })
    const request = vi.fn(
      (path: string, options?: RequestOptions): Promise<unknown> => {
        if (path.endsWith('/attachments') && options?.method === 'POST') {
          return Promise.reject(gatewayFailure)
        }
        if (path === stored.status_url) return Promise.resolve(stored)
        if (path === stored.finalize_url && options?.method === 'POST') {
          return Promise.resolve({})
        }
        throw new Error(`Unexpected request: ${path}`)
      },
    )

    await uploadAndFinalizeAttachment(
      { request } as never,
      changeRequestId,
      'REQUEST',
      new File(['evidence'], 'evidence.txt'),
      { pollDelayMs: 0, uploadId: attachmentId },
    )

    expect(request.mock.calls.map(([path]) => path)).toEqual([
      `/change-requests/${changeRequestId}/attachments`,
      stored.status_url,
      stored.finalize_url,
    ])
  })

  it('does not turn a deterministic POST rejection into a recovery read', async () => {
    const rejection = new ApiError({
      type: 'urn:test',
      title: 'Forbidden',
      status: 403,
      detail: 'forbidden',
      code: 'forbidden',
      request_id: 'request-1',
    })
    const request = vi.fn((): Promise<unknown> => Promise.reject(rejection))

    await expect(uploadAndFinalizeAttachment(
      { request } as never,
      changeRequestId,
      'REQUEST',
      new File(['evidence'], 'evidence.txt'),
      { uploadId: attachmentId },
    )).rejects.toBe(rejection)
    expect(request).toHaveBeenCalledTimes(1)
  })

  it('fails closed when provider evidence is FAILED', async () => {
    const failed = intent('FAILED', { failure_code: 'ATTACHMENT_PROVIDER_READBACK_MISMATCH' })
    const request = vi.fn(
      (path: string, options?: RequestOptions): Promise<unknown> => {
        if (path.endsWith('/attachments') && options?.method === 'POST') {
          return Promise.resolve(failed)
        }
        throw new Error(`Unexpected request: ${path}`)
      },
    )

    await expect(uploadAndFinalizeAttachment(
      { request } as never,
      changeRequestId,
      'REQUEST',
      new File(['evidence'], 'evidence.txt'),
      { pollDelayMs: 0, uploadId: attachmentId },
    )).rejects.toThrow('ATTACHMENT_PROVIDER_READBACK_MISMATCH')
  })

  it('stops after the bounded number of status reads', async () => {
    const started = intent('STARTED')
    const request = vi.fn(
      (path: string, options?: RequestOptions): Promise<unknown> => {
        if (path.endsWith('/attachments') && options?.method === 'POST') {
          return Promise.resolve(started)
        }
        if (path === started.status_url) return Promise.resolve(started)
        throw new Error(`Unexpected request: ${path}`)
      },
    )

    await expect(uploadAndFinalizeAttachment(
      { request } as never,
      changeRequestId,
      'REQUEST',
      new File(['evidence'], 'evidence.txt'),
      { maximumStatusReads: 2, pollDelayMs: 0, uploadId: attachmentId },
    )).rejects.toThrow('독립 저장 증빙을 기다리고 있습니다')
    expect(request).toHaveBeenCalledTimes(3)
  })

  it('does not poll while the document is hidden', async () => {
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
    const request = vi.fn((): Promise<unknown> => Promise.resolve(intent('STARTED')))

    await expect(uploadAndFinalizeAttachment(
      { request } as never,
      changeRequestId,
      'REQUEST',
      new File(['evidence'], 'evidence.txt'),
      { maximumDurationMs: 5, pollDelayMs: 0, uploadId: attachmentId },
    )).rejects.toThrow('독립 저장 증빙을 기다리고 있습니다')
    expect(request).toHaveBeenCalledTimes(1)
  })

  it('resumes one exact pending upload ID without creating a replacement upload', async () => {
    const stored = intent('STORED')
    const request = vi.fn(
      (path: string, options?: RequestOptions): Promise<unknown> => {
        if (path === stored.status_url) return Promise.resolve(stored)
        if (path === stored.finalize_url && options?.method === 'POST') {
          return Promise.resolve({})
        }
        throw new Error(`Unexpected request: ${path}`)
      },
    )

    await resumeAttachmentUpload(
      { request } as never,
      changeRequestId,
      attachmentId,
      { pollDelayMs: 0 },
    )

    expect(request.mock.calls.map(([path]) => path)).toEqual([
      stored.status_url,
      stored.finalize_url,
    ])
  })

  it('recovers only bounded STORED intents from the current round', async () => {
    const current = intent('STORED')
    const priorRound = intent('STORED', {
      id: '00000000-0000-4000-8000-000000000399',
      round_id: '00000000-0000-4000-8000-000000000398',
      status_url: '/prior/status',
      finalize_url: '/prior/finalize',
    })
    const request = vi.fn(
      (path: string, options?: RequestOptions): Promise<unknown> => {
        if (path.endsWith(`/attachment-uploads?round_id=${roundId}&limit=10`)) {
          return Promise.resolve({ items: [current, priorRound] })
        }
        if (path === current.finalize_url && options?.method === 'POST') {
          return Promise.resolve({})
        }
        throw new Error(`Unexpected request: ${path}`)
      },
    )

    await expect(resumeStoredAttachmentUploads(
      { request } as never,
      changeRequestId,
      roundId,
    )).resolves.toEqual({ finalized: 1, failed: 0 })
    expect(request).not.toHaveBeenCalledWith('/prior/finalize', expect.anything())
  })

  it('reports a partial current-round recovery instead of hiding the failed intent', async () => {
    const first = intent('STORED')
    const second = intent('STORED', {
      id: '00000000-0000-4000-8000-000000000397',
      status_url: '/second/status',
      finalize_url: '/second/finalize',
    })
    const failure = new ApiError({
      type: 'urn:test',
      title: 'Forbidden',
      status: 403,
      detail: 'authorization was revoked',
      code: 'forbidden',
      request_id: 'request-partial',
    })
    const request = vi.fn(
      (path: string, options?: RequestOptions): Promise<unknown> => {
        if (path.endsWith(`/attachment-uploads?round_id=${roundId}&limit=10`)) {
          return Promise.resolve({ items: [first, second] })
        }
        if (path === first.finalize_url && options?.method === 'POST') {
          return Promise.resolve({})
        }
        if (path === second.finalize_url && options?.method === 'POST') {
          return Promise.reject(failure)
        }
        throw new Error(`Unexpected request: ${path}`)
      },
    )

    const result = await resumeStoredAttachmentUploads(
      { request } as never,
      changeRequestId,
      roundId,
    )

    expect(result).toEqual({ finalized: 1, failed: 1, error: failure })
  })

  it('pauses a pending status read until the hidden document becomes visible', async () => {
    let hidden = true
    vi.spyOn(document, 'hidden', 'get').mockImplementation(() => hidden)
    const started = intent('STARTED')
    const request = vi.fn(
      (path: string, options?: RequestOptions): Promise<unknown> => {
        if (path.endsWith('/attachments') && options?.method === 'POST') {
          return Promise.resolve(started)
        }
        if (path === started.status_url) return Promise.resolve(intent('STORED'))
        if (path === started.finalize_url && options?.method === 'POST') {
          return Promise.resolve({})
        }
        throw new Error(`Unexpected request: ${path}`)
      },
    )

    const pending = uploadAndFinalizeAttachment(
      { request } as never,
      changeRequestId,
      'REQUEST',
      new File(['evidence'], 'evidence.txt'),
      { maximumDurationMs: 1_000, pollDelayMs: 0, uploadId: attachmentId },
    )
    await Promise.resolve()
    expect(request).toHaveBeenCalledTimes(1)
    hidden = false
    document.dispatchEvent(new Event('visibilitychange'))

    await expect(pending).resolves.toBeUndefined()
    expect(request).toHaveBeenCalledTimes(3)
  })

  it('aborts a delayed poll at the wall-clock deadline', async () => {
    const request = vi.fn((): Promise<unknown> => Promise.resolve(intent('STARTED')))

    await expect(uploadAndFinalizeAttachment(
      { request } as never,
      changeRequestId,
      'REQUEST',
      new File(['evidence'], 'evidence.txt'),
      {
        maximumDurationMs: 5,
        pollDelayMs: 1_000,
        uploadId: attachmentId,
      },
    )).rejects.toThrow('독립 저장 증빙을 기다리고 있습니다')
    expect(request).toHaveBeenCalledTimes(1)
  })

  it('bounds the selected file count and aggregate bytes', () => {
    const tooMany = Array.from(
      { length: 11 },
      (_, index) => new File(['x'], `evidence-${index}.txt`),
    )
    expect(attachmentSelectionError(tooMany)?.message).toContain('최대 10개')

    const aggregate = Array.from(
      { length: 4 },
      (_, index) => new File(['x'], `aggregate-${index}.bin`),
    )
    aggregate.forEach((file) => {
      Object.defineProperty(file, 'size', { value: 9 * 1024 * 1024 })
    })
    expect(attachmentSelectionError(aggregate)?.message).toContain('합계는 32 MiB')
  })
})
