import { render, screen, waitFor } from '@testing-library/react'
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
  it('keeps review workflow and directs new typed changes to registration', async () => {
    const existing = changeRequest()
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      if (path === '/change-requests?limit=50') return Promise.resolve({ items: [existing] })
      throw new Error(`Unexpected request: ${path} ${options?.method ?? 'GET'}`)
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

    expect(screen.getAllByText(existing.number).length).toBeGreaterThan(0)
    expect(screen.queryByLabelText('DataHub 대상 URN')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('승인 대상 JSON')).not.toBeInTheDocument()
    const link = screen.getByRole('link', { name: '등록관리에서 설명 변경 제안' })
    expect(link.getAttribute('href')).toContain('page=registration')
    expect(request).toHaveBeenCalledTimes(1)
  })
})
