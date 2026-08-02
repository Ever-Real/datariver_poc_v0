import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiClient } from '../../../../api/client'
import {
  sha256TBoxDocument,
  useTBoxProposalJob,
  validateTBoxDocument,
} from './useTBoxProposalJob'

const draftId = '019fa57b-52de-74c0-9f5e-06ae7b1bf3b0'
const jobId = '019fa57b-52de-74c0-9f5e-06ae7b1bf3b1'
const proposalId = '019fa57b-52de-74c0-9f5e-06ae7b1bf3b2'
const uploadId = '019fa57b-52de-74c0-9f5e-06ae7b1bf3b3'

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input
  return input instanceof URL ? input.toString() : input.url
}

function json(value: unknown, etag?: string, status = 200): Response {
  const headers = new Headers({ 'Content-Type': 'application/json' })
  if (etag) headers.set('ETag', etag)
  return new Response(JSON.stringify(value), { status, headers })
}

function proposal() {
  return {
    id: proposalId,
    draft_id: draftId,
    target_block_id: null,
    state: 'READY',
    mode: 'APPEND_LAYER',
    merge_strategy: 'KEEP_ORIGINAL',
    base_draft_version: 2,
    prompt: 'Document schema proposal: schema.json',
    elements: [],
    conflicts: [],
    source_reference: {
      pipeline_evidence: {
        typed_schema_parse: 'PASSED',
        deterministic_correction_passes: 1,
        aggregate_validation_passes: 1,
        cypher_execution: false,
      },
    },
    version: 1,
    created_at: '2026-07-31T01:00:00Z',
    updated_at: '2026-07-31T01:00:00Z',
  }
}

type TestJobState = 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'STALE' | 'CANCELLED'

function job(state: TestJobState, overrides: Record<string, unknown> = {}) {
  const succeeded = state === 'SUCCEEDED'
  const active = state === 'QUEUED' || state === 'RUNNING'
  return {
    id: jobId,
    draft_id: draftId,
    input_kind: 'DOCUMENT_SCHEMA',
    mode: 'APPEND_LAYER',
    target_block_id: null,
    state,
    stage: state === 'QUEUED'
      ? 'QUEUED'
      : state === 'RUNNING' ? 'INFERENCE' : succeeded ? 'COMPLETED' : 'FAILED',
    progress_percent: state === 'QUEUED' ? 0 : state === 'RUNNING' ? 55 : 100,
    attempt_count: state === 'QUEUED' ? 0 : 1,
    maximum_attempts: 4,
    last_failure_code: active || succeeded ? null : 'INFERENCE_REJECTED',
    version: succeeded ? 3 : 1,
    created_at: '2026-07-31T01:00:00Z',
    updated_at: '2026-07-31T01:01:00Z',
    completed_at: active ? null : '2026-07-31T01:01:00Z',
    result_proposal_id: succeeded ? proposalId : null,
    result_evidence_hash: succeeded ? 'b'.repeat(64) : null,
    supersedes_job_id: null,
    ...overrides,
  }
}

function upload(state: 'INITIATED' | 'ACCEPTED') {
  return {
    id: uploadId,
    display_name: 'schema.json',
    state,
    size_bytes: 2,
    content_type: 'application/json',
    sha256: '0'.repeat(64),
    classification: 'INTERNAL',
    content_profile: 'KNOWLEDGE_STUDIO_DOCUMENT_V1',
    expires_at: '2026-07-31T03:00:00Z',
    version: state === 'ACCEPTED' ? 5 : 1,
    validation_summary: state === 'ACCEPTED'
      ? { profile_configuration_hash: 'a'.repeat(64) }
      : {},
    last_error_code: null,
    recommended_part_size_bytes: 10 * 1024 * 1024,
  }
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  Reflect.deleteProperty(document, 'visibilityState')
})

describe('useTBoxProposalJob', () => {
  it('validates the bounded document contract and hashes bytes with WebCrypto', async () => {
    vi.stubGlobal('crypto', {
      randomUUID: () => '019fa57b-52de-74c0-9f5e-06ae7b1bf3ff',
      subtle: {
        digest: vi.fn().mockResolvedValue(Uint8Array.from({ length: 32 }, () => 0xab).buffer),
      },
    })
    const file = new File(['{}'], 'schema.json', { type: 'application/json' })
    Object.defineProperty(file, 'arrayBuffer', {
      value: () => Promise.resolve(new TextEncoder().encode('{}').buffer),
    })

    expect(validateTBoxDocument(file)).toBe('application/json')
    await expect(sha256TBoxDocument(file)).resolves.toBe('ab'.repeat(32))
    expect(() => validateTBoxDocument({
      name: 'schema.yaml',
      type: 'application/yaml',
      size: 2,
    })).toThrow(/지원 형식/)
    expect(() => validateTBoxDocument({
      name: 'schema.pdf',
      type: 'application/pdf',
      size: 10 * 1024 * 1024 + 1,
    })).toThrow(/10 MiB/)
  })

  it('runs accepted upload to a terminal 202 job and fetches the exact Proposal', async () => {
    vi.stubGlobal('crypto', {
      randomUUID: vi.fn().mockReturnValue('019fa57b-52de-74c0-9f5e-06ae7b1bf3ff'),
      subtle: {
        digest: vi.fn().mockResolvedValue(new Uint8Array(32).buffer),
      },
    })
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const path = requestUrl(input)
      if (path.includes('/tbox/proposal-jobs?')) {
        return Promise.resolve(json({ items: [], page: { next_cursor: null, limit: 20 } }))
      }
      if (path.endsWith(`/source-uploads`) && init?.method === 'POST') {
        return Promise.resolve(json(upload('INITIATED'), '"1"', 201))
      }
      if (path.endsWith(`/source-uploads/${uploadId}/parts`)) {
        return Promise.resolve(json({ url: 'https://objects.test/part', expires_seconds: 900 }))
      }
      if (path === 'https://objects.test/part') {
        return Promise.resolve(new Response(undefined, {
          status: 200,
          headers: { ETag: '"part-etag"' },
        }))
      }
      if (path.endsWith(`/source-uploads/${uploadId}/complete`)) {
        return Promise.resolve(json(upload('ACCEPTED'), '"5"'))
      }
      if (path.endsWith('/tbox/proposal-jobs') && init?.method === 'POST') {
        return Promise.resolve(json(job('SUCCEEDED'), '"3"', 202))
      }
      if (path.endsWith(`/tbox/proposals/${proposalId}`)) {
        return Promise.resolve(json(proposal()))
      }
      return Promise.reject(new Error(`Unexpected request: ${init?.method ?? 'GET'} ${path}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')
    const file = new File(['{}'], 'schema.json', { type: 'application/json' })
    Object.defineProperty(file, 'arrayBuffer', {
      value: () => Promise.resolve(new TextEncoder().encode('{}').buffer),
    })
    const { result } = renderHook(() => useTBoxProposalJob({
      client,
      draftId,
      draftEtag: '"2"',
      pollIntervalMs: 1,
      maximumPolls: 3,
    }))

    await act(async () => {
      await result.current.start({ file, mode: 'APPEND_LAYER' })
    })

    await waitFor(() => expect(result.current.proposal?.id).toBe(proposalId))
    expect(result.current.job?.state).toBe('SUCCEEDED')
    const initiateCall = fetchMock.mock.calls.find(([input]) => (
      requestUrl(input).endsWith('/source-uploads')
    ))
    const initiateBody = initiateCall?.[1]?.body
    expect(JSON.parse(typeof initiateBody === 'string' ? initiateBody : '{}')).toMatchObject({
      display_name: 'schema.json',
      content_type: 'application/json',
      sha256: '0'.repeat(64),
    })
    const jobCall = fetchMock.mock.calls.find(([input]) => (
      requestUrl(input).endsWith('/tbox/proposal-jobs')
    ))
    const jobBody = jobCall?.[1]?.body
    expect(JSON.parse(typeof jobBody === 'string' ? jobBody : '{}')).toEqual({
      input_kind: 'DOCUMENT_SCHEMA',
      source_upload_id: uploadId,
      source_manifest_version: 5,
      mode: 'APPEND_LAYER',
    })
  })

  it('resumes an active job on mount and pauses polling while the document is hidden', async () => {
    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      value: 'hidden',
    })
    let detailReads = 0
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const path = requestUrl(input)
      if (path.includes('/tbox/proposal-jobs?')) {
        return Promise.resolve(json({
          items: [job('RUNNING')],
          page: { next_cursor: null, limit: 20 },
        }))
      }
      if (path.endsWith(`/tbox/proposal-jobs/${jobId}`)) {
        detailReads += 1
        return Promise.resolve(json(
          detailReads === 1 ? job('RUNNING') : job('SUCCEEDED'),
          detailReads === 1 ? '"1"' : '"3"',
        ))
      }
      if (path.endsWith(`/tbox/proposals/${proposalId}`)) {
        return Promise.resolve(json(proposal()))
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')
    const { result } = renderHook(() => useTBoxProposalJob({
      client,
      draftId,
      draftEtag: '"2"',
      pollIntervalMs: 1,
      maximumPolls: 3,
    }))

    await waitFor(() => expect(result.current.job?.state).toBe('RUNNING'))
    await new Promise((resolve) => window.setTimeout(resolve, 10))
    expect(detailReads).toBe(1)

    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      value: 'visible',
    })
    document.dispatchEvent(new Event('visibilitychange'))

    await waitFor(() => expect(result.current.proposal?.id).toBe(proposalId))
    expect(detailReads).toBe(2)
  })

  it('restores the latest terminal Proposal without replaying its upload or job request', async () => {
    const olderActive = job('RUNNING', {
      id: '019fa57b-52de-74c0-9f5e-06ae7b1bf399',
      created_at: '2026-07-31T00:00:00Z',
    })
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const path = requestUrl(input)
      if (path.includes('/tbox/proposal-jobs?')) {
        return Promise.resolve(json({
          items: [job('SUCCEEDED'), olderActive],
          page: { next_cursor: null, limit: 20 },
        }))
      }
      if (path.endsWith(`/tbox/proposal-jobs/${jobId}`)) {
        return Promise.resolve(json(job('SUCCEEDED'), '"3"'))
      }
      if (path.endsWith(`/tbox/proposals/${proposalId}`)) {
        return Promise.resolve(json(proposal()))
      }
      return Promise.reject(new Error(`Unexpected request: ${init?.method ?? 'GET'} ${path}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')
    const { result } = renderHook(() => useTBoxProposalJob({
      client,
      draftId,
      draftEtag: '"2"',
    }))

    await waitFor(() => expect(result.current.proposal?.id).toBe(proposalId))
    expect(result.current.job?.state).toBe('SUCCEEDED')
    expect(result.current.restoredFromHistory).toBe(true)
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
    expect(fetchMock.mock.calls.some(([input]) => requestUrl(input).endsWith(olderActive.id)))
      .toBe(false)
  })

  it('restores a terminal failure read-only and keeps malformed results fail-closed', async () => {
    const failedFetch = vi.fn<typeof fetch>((input, init) => {
      const path = requestUrl(input)
      if (path.includes('/tbox/proposal-jobs?')) {
        return Promise.resolve(json({
          items: [job('FAILED')],
          page: { next_cursor: null, limit: 20 },
        }))
      }
      if (path.endsWith(`/tbox/proposal-jobs/${jobId}`)) {
        return Promise.resolve(json(job('FAILED'), '"2"'))
      }
      return Promise.reject(new Error(`Unexpected request: ${init?.method ?? 'GET'} ${path}`))
    })
    vi.stubGlobal('fetch', failedFetch)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')
    const failed = renderHook(() => useTBoxProposalJob({
      client,
      draftId,
      draftEtag: '"2"',
    }))

    await waitFor(() => expect(failed.result.current.job?.state).toBe('FAILED'))
    expect(failed.result.current.error).toContain('INFERENCE_REJECTED')
    expect(failed.result.current.canRetry).toBe(true)
    expect(failed.result.current.proposal).toBeUndefined()
    expect(failedFetch.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
    failed.unmount()

    const malformedFetch = vi.fn<typeof fetch>((input) => {
      const path = requestUrl(input)
      if (path.includes('/tbox/proposal-jobs?')) {
        return Promise.resolve(json({
          items: [job('SUCCEEDED', { result_proposal_id: null })],
          page: { next_cursor: null, limit: 20 },
        }))
      }
      if (path.endsWith(`/tbox/proposal-jobs/${jobId}`)) {
        return Promise.resolve(json(job('SUCCEEDED', { result_proposal_id: null }), '"3"'))
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`))
    })
    vi.stubGlobal('fetch', malformedFetch)
    const malformed = renderHook(() => useTBoxProposalJob({
      client,
      draftId,
      draftEtag: '"2"',
    }))

    await waitFor(() => expect(malformed.result.current.error).toContain('결과 Proposal ID'))
    expect(malformed.result.current.proposal).toBeUndefined()
  })

  it('ignores a latest job outside the current Draft', async () => {
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const path = requestUrl(input)
      if (path.includes('/tbox/proposal-jobs?')) {
        return Promise.resolve(json({
          items: [job('SUCCEEDED', { draft_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf300' })],
          page: { next_cursor: null, limit: 20 },
        }))
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')
    const { result } = renderHook(() => useTBoxProposalJob({
      client,
      draftId,
      draftEtag: '"2"',
    }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    expect(result.current.job).toBeUndefined()
    expect(result.current.proposal).toBeUndefined()
    expect(result.current.restoredFromHistory).toBe(false)
  })
})
