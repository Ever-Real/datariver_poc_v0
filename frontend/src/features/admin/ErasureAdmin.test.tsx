import { act, fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { AdminReadContext, ErasureRequest } from '../../api/types'
import { ErasureAdmin } from './ErasureAdmin'
import { getAdminMessages } from './messages'

describe('ErasureAdmin target binding', () => {
  it('does not let an older list response overwrite a newer refresh', async () => {
    const oldList = deferred<ReturnType<typeof page>>()
    const alpha = request('00000000-0000-4000-8000-000000000611')
    const beta = request('00000000-0000-4000-8000-000000000612')
    const api = {
      listErasureRequestPage: vi.fn()
        .mockImplementationOnce(() => oldList.promise)
        .mockResolvedValue(page([beta])),
      getErasureRequest: vi.fn(() => Promise.resolve({ ...beta, etag: '"1"' })),
      getErasureExecutionEvidence: vi.fn(() => Promise.resolve({
        erasure_request_id: beta.erasure_request_id,
        availability: 'NOT_PLANNED',
        archive_only: true,
        deletion_automation_state: 'DISABLED_NOT_READY',
        job: null,
      })),
    }

    const view = render(<ErasureAdmin
      api={api as never} context={undefined} messages={getAdminMessages('ko')}
      requestConfirmation={vi.fn()} keyFor={() => 'stable-key'} clearKey={vi.fn()}
      reportError={vi.fn()} onStepUp={vi.fn(() => Promise.resolve())}
      onPasswordReauth={vi.fn(() => Promise.resolve())} onEnroll={vi.fn(() => Promise.resolve())}
    />)

    const initialSignal = (
      api.listErasureRequestPage.mock.calls[0]?.[0] as { signal: AbortSignal }
    ).signal
    fireEvent.click(screen.getByRole('button', { name: '새로고침' }))
    expect(await screen.findByText(beta.target_id)).toBeInTheDocument()
    const refreshSignal = (
      api.listErasureRequestPage.mock.calls[1]?.[0] as { signal: AbortSignal }
    ).signal
    expect(initialSignal.aborted).toBe(true)
    expect(refreshSignal.aborted).toBe(false)

    await act(async () => {
      oldList.resolve(page([alpha]))
      await oldList.promise
    })

    expect(screen.getAllByText(beta.target_id).length).toBeGreaterThan(0)
    expect(screen.queryByText(alpha.target_id)).not.toBeInTheDocument()
    view.unmount()
    expect(refreshSignal.aborted).toBe(true)
  })

  it('discards a late detail response after another request is selected', async () => {
    const alpha = request('00000000-0000-4000-8000-000000000601')
    const beta = request('00000000-0000-4000-8000-000000000602')
    const alphaDetail = deferred<unknown>()
    const betaDetail = deferred<unknown>()
    const api = {
      listErasureRequestPage: vi.fn(() => Promise.resolve(page([alpha, beta]))),
      getErasureRequest: vi.fn((requestId: string) => (
        requestId === alpha.erasure_request_id ? alphaDetail.promise : betaDetail.promise
      )),
      getErasureExecutionEvidence: vi.fn((requestId: string) => Promise.resolve({
        erasure_request_id: requestId,
        availability: 'NOT_PLANNED',
        archive_only: true,
        deletion_automation_state: 'DISABLED_NOT_READY',
        job: null,
      })),
    }
    const context: AdminReadContext = {
      subject_id: '00000000-0000-4000-8000-000000000111',
      workspace_id: '00000000-0000-4000-8000-000000000100',
      display_name: 'Administrator', authentication_assurance: 'HARDWARE_WEBAUTHN',
      fallback_enabled: false, allowed_operations: ['ERASURE_READ', 'ERASURE_APPROVE'],
      action_vocabulary: [],
    }

    render(<ErasureAdmin
      api={api as never} context={context} messages={getAdminMessages('ko')}
      requestConfirmation={vi.fn()} keyFor={() => 'stable-key'} clearKey={vi.fn()}
      reportError={vi.fn()} onStepUp={vi.fn(() => Promise.resolve())}
      onPasswordReauth={vi.fn(() => Promise.resolve())} onEnroll={vi.fn(() => Promise.resolve())}
    />)

    expect(await screen.findByText(alpha.target_id)).toBeInTheDocument()
    fireEvent.click(screen.getByText(beta.target_id))
    await act(async () => {
      betaDetail.resolve({ ...beta, etag: '"1"' })
      await betaDetail.promise
    })
    expect(screen.getAllByText(beta.target_id).length).toBeGreaterThan(1)

    await act(async () => {
      alphaDetail.resolve({ ...alpha, etag: '"1"' })
      await alphaDetail.promise
    })

    expect(screen.getAllByText(beta.target_id).length).toBeGreaterThan(1)
    expect(screen.getAllByText(alpha.target_id)).toHaveLength(1)
    expect(await screen.findByText('Archive-only execution evidence')).toBeInTheDocument()
    expect(screen.getByText('NOT_PLANNED')).toBeInTheDocument()
  })
})

function page(items: ErasureRequest[], nextCursor: string | null = null) {
  return { items, nextCursor, limit: 25 }
}

function request(targetId: string): ErasureRequest {
  return {
    erasure_request_id: targetId.replace(/6(0[12])$/, '7$1'),
    target_type: 'CHAT_SESSION',
    target_id: targetId,
    target_version: 1,
    target_owner_id: '00000000-0000-4000-8000-000000000333',
    classification: 'INTERNAL',
    retention_policy_id: '00000000-0000-4000-8000-000000000444',
    retention_policy_hash: 'a'.repeat(64),
    requester_id: '00000000-0000-4000-8000-000000000555',
    request_reason: 'Governed erasure review',
    request_policy_decision_id: '00000000-0000-4000-8000-000000000556',
    payload_hash: 'b'.repeat(64),
    expires_at: '2026-07-24T00:00:00Z',
    state: 'PENDING',
    checker_id: null,
    decision_reason: null,
    decision_policy_decision_id: null,
    decided_at: null,
    version: 1,
    execution_state: 'DISABLED_NOT_READY',
    approval_history_truncated: true,
    approvals: [],
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((next) => { resolve = next })
  return { promise, resolve }
}
