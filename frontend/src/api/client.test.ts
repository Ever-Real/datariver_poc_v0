import { describe, expect, it } from 'vitest'
import { newIdempotencyKey, parseProblem } from './client'

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
})
