import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient, RequestOptions } from '../../api/client'
import type { ChangeRequestRecord } from '../../api/types'
import { GovernancePage } from './GovernancePage'

function changeRequest(): ChangeRequestRecord {
  return {
    id: 'change-1',
    number: 'CR-2026-1',
    request_type: 'CATALOG_METADATA',
    title: 'Governed change',
    description: '',
    state: 'REGISTERED',
    requester_id: 'subject-1',
    classification: 'INTERNAL',
    version: 1,
    items: [],
    approvals: [],
    transitions: [],
  }
}

describe('GovernancePage', () => {
  it('submits only allowlisted aspects with a mandatory optimistic concurrency hash', async () => {
    let submitted: Record<string, unknown> | undefined
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      if (path === '/change-requests?limit=50') return Promise.resolve({ items: [] })
      if (typeof options?.body !== 'string') throw new Error('Expected a JSON request body.')
      submitted = JSON.parse(options.body) as Record<string, unknown>
      return Promise.resolve(changeRequest())
    })
    const client = { request } as unknown as ApiClient
    render(<GovernancePage
      client={client}
      onStepUp={vi.fn(() => Promise.resolve())}
      onPasswordReauth={vi.fn(() => Promise.resolve())}
      onEnroll={vi.fn(() => Promise.resolve())}
    />)

    await waitFor(() => expect(request.mock.calls.some(([path, options]) => (
      path === '/change-requests?limit=50' && options?.signal instanceof AbortSignal
    ))).toBe(true))
    fireEvent.change(screen.getByLabelText('제목'), { target: { value: 'Governed change' } })
    fireEvent.change(screen.getByLabelText('DataHub 대상 URN'), { target: { value: 'urn:li:dataset:test' } })
    fireEvent.change(screen.getByLabelText('원본 Aspect SHA-256'), { target: { value: 'b'.repeat(64) } })
    fireEvent.click(screen.getByRole('button', { name: '변경 요청 생성' }))

    await waitFor(() => expect(submitted).toBeDefined())
    const items = submitted?.items as Array<Record<string, unknown>>
    expect(items[0]).toMatchObject({
      target_ref: 'urn:li:dataset:test',
      aspect_name: 'datasetProperties',
      before_hash: 'b'.repeat(64),
    })
    expect(screen.getByRole('option', { name: 'schemaMetadata' })).toBeInTheDocument()
  })
})
