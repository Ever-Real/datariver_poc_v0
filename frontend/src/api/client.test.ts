import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  ApiClient,
  ApiError,
  StaleSecurityContextError,
  newIdempotencyKey,
  parseProblem,
} from './client'

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

  it('renews once and retries an idempotent read after 401', async () => {
    const responses = [
      new Response(JSON.stringify({ detail: 'expired' }), { status: 401 }),
      new Response(JSON.stringify({ value: 'fresh' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    ]
    const requests: RequestInit[] = []
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      if (init) requests.push(init)
      const response = responses.shift()
      if (!response) throw new Error('unexpected request')
      return Promise.resolve(response)
    })
    const renew = vi.fn().mockResolvedValue('fresh-token')
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'expired-token', () => 'workspace', renew)

    await expect(client.request<{ value: string }>('/catalog/assets?q=wafer')).resolves.toEqual({
      value: 'fresh',
    })

    expect(renew).toHaveBeenCalledOnce()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(new Headers(requests[1]?.headers).get('Authorization')).toBe(
      'Bearer fresh-token',
    )
  })

  it('does not retry after renewal changes the authenticated security epoch', async () => {
    let securityEpoch = 7
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'expired' }), { status: 401 }),
    )
    const renew = vi.fn().mockImplementation(() => {
      securityEpoch = 8
      return Promise.resolve('different-session-token')
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient(
      '/api/v1',
      () => 'expired-token',
      () => 'workspace',
      renew,
      () => securityEpoch,
    )

    await expect(client.request('/catalog/assets')).rejects.toBeInstanceOf(
      StaleSecurityContextError,
    )
    expect(renew).toHaveBeenCalledOnce()
    expect(fetchMock).toHaveBeenCalledOnce()
  })

  it('does not replay an idempotent mutation under a newer authenticated session', async () => {
    let securityEpoch = 3
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'expired' }), { status: 401 }),
    )
    const renew = vi.fn().mockImplementation(() => {
      securityEpoch = 4
      return Promise.resolve('different-session-token')
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient(
      '/api/v1',
      () => 'expired-token',
      () => 'workspace',
      renew,
      () => securityEpoch,
    )

    await expect(client.request('/admin/retention-policies', {
      method: 'POST',
      idempotencyKey: 'retention-00000000-0000-4000-8000-000000000001',
      body: JSON.stringify({}),
    })).rejects.toBeInstanceOf(StaleSecurityContextError)
    expect(fetchMock).toHaveBeenCalledOnce()
  })

  it('discards a successful response that arrives after its security boundary changed', async () => {
    let workspace = 'workspace-a'
    let securityEpoch = 11
    const response = deferred<Response>()
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(response.promise))
    const client = new ApiClient(
      '/api/v1',
      () => 'token',
      () => workspace,
      undefined,
      () => securityEpoch,
    )

    const request = client.request('/admin/me')
    workspace = 'workspace-b'
    securityEpoch = 12
    response.resolve(new Response(JSON.stringify({ allowed_operations: [] }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))

    await expect(request).rejects.toBeInstanceOf(StaleSecurityContextError)
  })

  it('does not retry a non-idempotent write after 401', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'expired' }), {
      status: 401,
    }))
    const renew = vi.fn().mockResolvedValue('fresh-token')
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'expired-token', () => 'workspace', renew)

    await expect(client.request('/change-requests', {
      method: 'POST',
      body: JSON.stringify({}),
    })).rejects.toBeInstanceOf(ApiError)

    expect(renew).not.toHaveBeenCalled()
    expect(fetchMock).toHaveBeenCalledOnce()
  })

  it('retries a mutation only when it carries the durable idempotency key', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'expired' }), { status: 401 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
    const renew = vi.fn().mockResolvedValue('fresh-token')
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'expired-token', () => 'workspace', renew)

    await expect(client.request('/change-requests', {
      method: 'POST',
      body: JSON.stringify({}),
      idempotencyKey: 'change-00000000-0000-4000-8000-000000000001',
    })).resolves.toBeUndefined()

    expect(renew).toHaveBeenCalledOnce()
    expect(fetchMock).toHaveBeenCalledTimes(2)
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

  it('downloads a server-versioned template through the authenticated no-store boundary', async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => {
      void _input
      void _init
      return Promise.resolve(new Response(
        'record_kind,asset_id,platform,database_name,schema_name,table_name,field_path,operation,value_text,controlled_ref\n',
        {
          status: 200,
          headers: {
            'Cache-Control': 'private, no-store',
            'Content-Disposition': 'attachment; filename="catalog-metadata-template.csv"',
            'Content-Type': 'text/csv',
            ETag: '"template-v3"',
          },
        },
      ))
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')

    const downloaded = await client.download(
      '/uploads/profiles/CATALOG_METADATA_ROWS_CSV_V1/template',
    )

    expect(await downloaded.blob.text()).toBe(
      'record_kind,asset_id,platform,database_name,schema_name,table_name,field_path,operation,value_text,controlled_ref\n',
    )
    expect(downloaded.filename).toBe('catalog-metadata-template.csv')
    expect(downloaded.etag).toBe('"template-v3"')
    const [, options] = fetchMock.mock.calls[0] ?? []
    expect(options?.cache).toBe('no-store')
    const headers = new Headers(options?.headers)
    expect(headers.get('Authorization')).toBe('Bearer token')
    expect(headers.get('X-Workspace-Id')).toBe('workspace')
  })

  it('discards a download whose security epoch changes before the body is returned', async () => {
    let securityEpoch = 21
    const response = deferred<Response>()
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(response.promise))
    const client = new ApiClient(
      '/api/v1',
      () => 'token',
      () => 'workspace',
      undefined,
      () => securityEpoch,
    )

    const download = client.download('/uploads/template')
    securityEpoch = 22
    response.resolve(new Response('sensitive', {
      status: 200,
      headers: { 'Content-Type': 'text/csv' },
    }))

    await expect(download).rejects.toBeInstanceOf(StaleSecurityContextError)
  })
})

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((accept) => { resolve = accept })
  return { promise, resolve }
}
