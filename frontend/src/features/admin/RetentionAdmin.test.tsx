import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { AdminReadContext } from '../../api/types'
import type { PendingAdminMutation } from './AdminMutationConfirmDialog'
import { getAdminMessages } from './messages'
import { LegalHoldAdmin, RetentionPolicyAdmin } from './RetentionAdmin'

const commonProps = {
  context: undefined,
  messages: getAdminMessages('ko'),
  requestConfirmation: vi.fn(),
  keyFor: () => 'stable-key',
  clearKey: vi.fn(),
  reportError: vi.fn(),
  onStepUp: vi.fn(() => Promise.resolve()),
  onPasswordReauth: vi.fn(() => Promise.resolve()),
  onEnroll: vi.fn(() => Promise.resolve()),
}

describe('Retention admin list races', () => {
  it('does not let an older retention-policy response replace a refreshed page', async () => {
    const oldPage = deferred<ReturnType<typeof page>>()
    const api = {
      listRetentionPolicyPage: vi.fn()
        .mockImplementationOnce(() => oldPage.promise)
        .mockResolvedValue(page([policy('new-policy', 2)])),
    }

    const view = render(<RetentionPolicyAdmin api={api as never} {...commonProps} />)
    await waitFor(() => expect(api.listRetentionPolicyPage).toHaveBeenCalledOnce())
    const initialSignal = (
      api.listRetentionPolicyPage.mock.calls[0]?.[0] as { signal: AbortSignal }
    ).signal
    fireEvent.click(screen.getByRole('button', { name: '새로고침' }))
    await screen.findByRole('heading', { name: '#2 · DRAFT' })
    const refreshSignal = (
      api.listRetentionPolicyPage.mock.calls[1]?.[0] as { signal: AbortSignal }
    ).signal
    expect(initialSignal.aborted).toBe(true)
    expect(refreshSignal.aborted).toBe(false)

    await act(async () => {
      oldPage.resolve(page([policy('old-policy', 1)]))
      await oldPage.promise
    })

    expect(screen.getByRole('heading', { name: '#2 · DRAFT' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '#1 · DRAFT' })).not.toBeInTheDocument()
    view.unmount()
    expect(refreshSignal.aborted).toBe(true)
  })

  it('does not let an older Legal Hold response replace a refreshed page', async () => {
    const oldPage = deferred<ReturnType<typeof page>>()
    const api = {
      listLegalHoldPage: vi.fn()
        .mockImplementationOnce(() => oldPage.promise)
        .mockResolvedValue(page([hold('new-hold', 'CHAT_CONTENT')])),
      getLegalHold: vi.fn((holdId: string) => Promise.resolve(
        hold(holdId, holdId === 'new-hold' ? 'CHAT_CONTENT' : 'AUDIT_EVIDENCE'),
      )),
    }

    render(<LegalHoldAdmin api={api as never} {...commonProps} />)
    fireEvent.click(screen.getByRole('button', { name: '새로고침' }))
    await waitFor(() => expect(screen.getAllByText('CHAT_CONTENT').length).toBeGreaterThan(0))

    await act(async () => {
      oldPage.resolve(page([hold('old-hold', 'AUDIT_EVIDENCE')]))
      await oldPage.promise
    })

    expect(screen.getAllByText('CHAT_CONTENT').length).toBeGreaterThan(0)
    expect(screen.queryByText('AUDIT_EVIDENCE')).not.toBeInTheDocument()
  })

  it('binds the policy cursor to its state filter and resets to page one', async () => {
    const api = {
      listRetentionPolicyPage: vi.fn()
        .mockResolvedValueOnce(page([policy('page-one', 1)], 'policy-cursor'))
        .mockResolvedValueOnce(page([policy('page-two', 2)]))
        .mockResolvedValueOnce(page([policy('draft-page', 3)])),
    }

    render(<RetentionPolicyAdmin api={api as never} {...commonProps} />)
    await screen.findByRole('heading', { name: '#1 · DRAFT' })
    fireEvent.click(screen.getByRole('button', { name: '다음' }))
    await screen.findByRole('heading', { name: '#2 · DRAFT' })
    fireEvent.change(screen.getByLabelText('상태 필터'), { target: { value: 'DRAFT' } })
    await screen.findByRole('heading', { name: '#3 · DRAFT' })

    const requestedPages = api.listRetentionPolicyPage.mock.calls.map(
      ([options]) => {
        const pageOptions = options as {
          state?: string
          cursor?: string
          limit: number
          signal: AbortSignal
        }
        return {
          state: pageOptions.state,
          cursor: pageOptions.cursor,
          limit: pageOptions.limit,
        }
      },
    )
    expect(requestedPages).toEqual([
      { state: undefined, cursor: undefined, limit: 25 },
      { state: undefined, cursor: 'policy-cursor', limit: 25 },
      { state: 'DRAFT', cursor: undefined, limit: 25 },
    ])
    const signals = api.listRetentionPolicyPage.mock.calls.map(
      ([options]) => (options as { signal: AbortSignal }).signal,
    )
    expect(signals.every((signal) => signal instanceof AbortSignal)).toBe(true)
    expect(signals[0]?.aborted).toBe(true)
    expect(signals[1]?.aborted).toBe(true)
    expect(signals[2]?.aborted).toBe(false)
    expect(screen.getByText('페이지 1')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '이전' })).toBeDisabled()
  })

  it('returns to the first server page after a confirmed policy mutation', async () => {
    const created = policy('created-policy', 3)
    const requestConfirmation = vi.fn()
    const api = {
      listRetentionPolicyPage: vi.fn()
        .mockResolvedValueOnce(page([policy('page-one', 1)], 'policy-cursor'))
        .mockResolvedValueOnce(page([policy('page-two', 2)]))
        .mockResolvedValueOnce(page([created])),
      proposeRetentionPolicy: vi.fn(() => Promise.resolve(created)),
    }
    const context: AdminReadContext = {
      subject_id: 'checker',
      workspace_id: 'workspace',
      display_name: 'Checker',
      authentication_assurance: 'HARDWARE_WEBAUTHN',
      fallback_enabled: false,
      allowed_operations: ['RETENTION_POLICY_MANAGE'],
      action_vocabulary: [],
    }

    render(<RetentionPolicyAdmin
      api={api as never}
      {...commonProps}
      context={context}
      requestConfirmation={requestConfirmation}
    />)
    await screen.findByRole('heading', { name: '#1 · DRAFT' })
    fireEvent.click(screen.getByRole('button', { name: '다음' }))
    await screen.findByRole('heading', { name: '#2 · DRAFT' })
    fireEvent.change(screen.getByLabelText('완료 작업 온라인 보존일'), { target: { value: '30' } })
    fireEvent.change(screen.getByLabelText('Chat 콘텐츠 보존일'), { target: { value: '30' } })
    fireEvent.change(screen.getByLabelText('감사 온라인 보존개월'), { target: { value: '12' } })
    fireEvent.change(screen.getByLabelText('불변 아카이브 보존년'), { target: { value: '7' } })
    fireEvent.change(screen.getByLabelText('계약 버전'), { target: { value: 'POLICY_BOOK_V2' } })
    screen.getAllByLabelText('단위').forEach((field) => {
      fireEvent.change(field, { target: { value: 'DAYS' } })
    })
    screen.getAllByLabelText('최소 보존').forEach((field) => {
      fireEvent.change(field, { target: { value: '1' } })
    })
    screen.getAllByLabelText('최대 보존').forEach((field) => {
      fireEvent.change(field, { target: { value: '30' } })
    })
    screen.getAllByLabelText('만료 처리').forEach((field) => {
      fireEvent.change(field, { target: { value: 'NO_ARCHIVE' } })
    })
    fireEvent.change(screen.getAllByLabelText('사유')[0]!, { target: { value: 'reviewed' } })
    fireEvent.click(screen.getByRole('button', { name: '정책 제안' }))

    const mutation = requestConfirmation.mock.calls[0]?.[0] as PendingAdminMutation
    await act(() => mutation.execute())
    await waitFor(() => expect(api.listRetentionPolicyPage).toHaveBeenCalledTimes(3))
    expect(api.listRetentionPolicyPage.mock.calls[2]?.[0]).toEqual(expect.objectContaining({
      state: undefined,
      cursor: undefined,
      limit: 25,
    }))
    expect(
      (api.listRetentionPolicyPage.mock.calls[2]?.[0] as { signal: unknown }).signal,
    ).toBeInstanceOf(AbortSignal)
    expect(screen.getByText('페이지 1')).toBeInTheDocument()
  })
})

function page<T>(items: T[], nextCursor: string | null = null) {
  return { items, nextCursor, limit: 25 }
}

function policy(id: string, number: number) {
  return {
    policy_id: id,
    policy_number: number,
    state: 'DRAFT',
    contract_version: 'POLICY_BOOK_V2',
    contract: {
      contract_version: 'POLICY_BOOK_V2',
      effective_from: '2026-07-23T00:00:00.000Z',
      effective_until: null,
      execution_authorization_hours: 24,
      class_rules: [
        { data_class: 'COMPLETED_OPERATIONS', unit: 'DAYS', minimum: 30, maximum: 365, archive_disposition: 'NO_ARCHIVE' },
        { data_class: 'CHAT_CONTENT', unit: 'DAYS', minimum: 7, maximum: 365, archive_disposition: 'NO_ARCHIVE' },
        { data_class: 'AUDIT_EVIDENCE', unit: 'MONTHS', minimum: 12, maximum: 84, archive_disposition: 'CONTENT_WORM' },
        { data_class: 'OBJECT_DATA', unit: 'DAYS', minimum: 30, maximum: 3650, archive_disposition: 'CONTENT_WORM' },
      ],
    },
    rules: {
      completed_operation_days: 30,
      chat_content_days: 30,
      audit_online_months: 12,
      immutable_archive_years: 7,
    },
    request_reason: 'test',
    requester_id: 'maker',
    payload_hash: 'a'.repeat(64),
    partition_automation_state: 'DISABLED_NOT_READY',
    deletion_automation_state: 'DISABLED_NOT_READY',
    version: 1,
  }
}

function hold(id: string, dataClass: string) {
  return {
    hold_id: id,
    data_class: dataClass,
    scope: 'WORKSPACE',
    scope_id: null,
    resource_type: null,
    state: 'ACTIVE',
    reason: 'test',
    created_by: 'maker',
    version: 1,
    payload_hash: 'b'.repeat(64),
    deletion_effect: 'BLOCKED',
    action_history_truncated: true,
    actions: [],
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((next) => { resolve = next })
  return { promise, resolve }
}
