import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiClient, ApiError, newIdempotencyKey, parseProblem } from './client'

afterEach(() => vi.unstubAllGlobals())

describe('API problem handling', () => {
  it('preserves the server request id', async () => {
    const response = new Response(JSON.stringify({ detail: 'denied', request_id: 'request-42' }), {
      status: 403,
      headers: { 'Content-Type': 'application/problem+json' },
    })
    const problem = await parseProblem(response)
    expect(problem.status).toBe(403)
    expect(problem.request_id).toBe('request-42')
    expect(problem.detail).toBe('denied')
  })

  it('generates unique operation-scoped idempotency keys', () => {
    const first = newIdempotencyKey('upload')
    const second = newIdempotencyKey('upload')
    expect(first).toMatch(/^upload-/)
    expect(first).not.toBe(second)
  })

  it('accepts only the bounded remediation contract', async () => {
    const accepted = await parseProblem(new Response(JSON.stringify({
      remediation: { kind: 'FIDO2_REQUIRED', internal: 'drop-me' },
    }), { status: 403 }))
    const rejected = await parseProblem(new Response(JSON.stringify({
      remediation: { kind: 'BYPASS_POLICY' },
    }), { status: 403 }))

    expect(accepted.remediation).toEqual({ kind: 'FIDO2_REQUIRED' })
    expect(accepted).not.toHaveProperty('internal')
    expect(rejected.remediation).toBeUndefined()
  })

  it('never retries a denied mutation automatically', async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response(JSON.stringify({
      type: 'urn:datariver:problem:forbidden',
      title: 'Forbidden',
      detail: 'denied',
      code: 'forbidden',
      request_id: 'request-one',
      remediation: { kind: 'FIDO2_REQUIRED' },
    }), { status: 403, headers: { 'Content-Type': 'application/problem+json' } })))
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')

    await expect(client.request('/change-requests/request/approvals', {
      method: 'POST',
      body: JSON.stringify({ decision: 'APPROVED' }),
    })).rejects.toBeInstanceOf(ApiError)

    expect(fetchMock).toHaveBeenCalledOnce()
  })

  it('returns a response ETag without issuing a second request', async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response(JSON.stringify({ version: 7 }), {
      status: 200, headers: { ETag: '"7"', 'Content-Type': 'application/json' },
    })))
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')

    await expect(client.requestWithMeta<{ version: number }>('/resource')).resolves.toEqual({
      data: { version: 7 }, etag: '"7"',
    })
    expect(fetchMock).toHaveBeenCalledOnce()
  })
})
