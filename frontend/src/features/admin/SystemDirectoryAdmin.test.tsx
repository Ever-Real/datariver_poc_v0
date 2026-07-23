import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type {
  AdminReadContext,
  SystemDirectoryEntry,
  WorkspaceMembershipSummary,
} from '../../api/types'
import type { PendingAdminMutation } from './AdminMutationConfirmDialog'
import { getAdminMessages } from './messages'
import { SystemDirectoryAdmin } from './SystemDirectoryAdmin'

function system(id: string, code: string, name: string): SystemDirectoryEntry {
  return {
    system_id: id,
    code,
    name,
    description: `${name} description`,
    active: true,
    version: 1,
    assignee_count: 0,
    assignees: [],
  }
}

describe('SystemDirectoryAdmin', () => {
  it('submits only the changed page as a version-fenced delta and reloads it', async () => {
    const target: WorkspaceMembershipSummary = {
      subject_id: '00000000-0000-4000-8000-000000000721',
      display_name: 'Target User',
      email: 'target@example.test',
      last_login_at: null,
      last_login_ip: null,
      owned_table_count: 0,
      change_request_count: 0,
      subject_active: true,
      membership_active: true,
      department_id: null,
      job_function: 'ENGINEER',
      clearance: 'INTERNAL',
      membership_version: 1,
      access_expires_at: null,
      renewal_eligible_at: null,
      access_expired: false,
      pending_renewal_request_id: null,
      renewal_request_eligible: false,
    }
    const selectedSystem = system(
      '00000000-0000-4000-8000-000000000722',
      'FAB',
      'Fabrication',
    )
    const assignments = [
      {
        subject_id: target.subject_id,
        display_name: target.display_name,
        responsibility: 'DEVELOPER' as const,
        priority: 1,
        active: true,
      },
      {
        subject_id: target.subject_id,
        display_name: target.display_name,
        responsibility: 'DATA_STEWARD' as const,
        priority: 1,
        active: true,
      },
    ]
    const api = {
      listSystemPage: vi.fn(() => Promise.resolve({
        items: [{ ...selectedSystem, assignee_count: 2 }],
        nextCursor: null,
        limit: 25,
      })),
      listMembershipPage: vi.fn(() => Promise.resolve({
        items: [target], nextCursor: null, limit: 25,
      })),
      listSystemAssigneePage: vi.fn()
        .mockResolvedValueOnce({
          system_version: 1,
          items: assignments,
          page: { next_cursor: null, limit: 25 },
        })
        .mockResolvedValue({
          system_version: 2,
          items: [{ ...assignments[0], priority: 2 }, assignments[1]],
          page: { next_cursor: null, limit: 25 },
        }),
      patchSystemAssignees: vi.fn(() => Promise.resolve({
        system_id: selectedSystem.system_id,
        system_version: 2,
        payload_hash: 'a'.repeat(64),
      })),
    }
    const context: AdminReadContext = {
      subject_id: '00000000-0000-4000-8000-000000000723',
      workspace_id: '00000000-0000-4000-8000-000000000724',
      display_name: 'Administrator',
      authentication_assurance: 'HARDWARE_WEBAUTHN',
      fallback_enabled: false,
      allowed_operations: ['MEMBERSHIP_ACCESS_READ', 'SYSTEM_ASSIGNMENT_UPDATE'],
      action_vocabulary: ['admin.manage'],
    }
    let pending: PendingAdminMutation | undefined

    render(<SystemDirectoryAdmin
      api={api as never} context={context} messages={getAdminMessages('ko')}
      requestConfirmation={(value) => { pending = value }} keyFor={() => 'stable-system-key'}
      clearKey={vi.fn()} reportError={vi.fn()} onStepUp={vi.fn(() => Promise.resolve())}
      onPasswordReauth={vi.fn(() => Promise.resolve())} onEnroll={vi.fn(() => Promise.resolve())}
    />)

    const priorities = await screen.findAllByRole('spinbutton')
    fireEvent.change(priorities[0]!, { target: { value: '2' } })
    fireEvent.click(screen.getByRole('button', { name: '현재 페이지 변경 저장' }))
    expect(pending?.title).toBe('시스템 담당자 변경')
    if (!pending) throw new Error('system assignment confirmation was not requested')
    await act(async () => { await pending?.execute() })

    expect(api.patchSystemAssignees).toHaveBeenCalledWith(
      selectedSystem.system_id,
      [{
        subject_id: target.subject_id,
        responsibility: 'DEVELOPER',
        priority: 2,
      }],
      [],
      1,
      'stable-system-key',
    )
    await waitFor(() => expect(api.listSystemAssigneePage).toHaveBeenCalledTimes(2))
  })

  it('does not let an older directory response overwrite a newer refresh', async () => {
    const oldSystems = deferred<{
      items: SystemDirectoryEntry[]
      nextCursor: string | null
      limit: number
    }>()
    const oldSystem = system(
      '00000000-0000-4000-8000-000000000711',
      'OLD',
      'Old System',
    )
    const newSystem = system(
      '00000000-0000-4000-8000-000000000712',
      'NEW',
      'New System',
    )
    const api = {
      listSystemPage: vi.fn()
        .mockImplementationOnce(() => oldSystems.promise)
        .mockResolvedValue({ items: [newSystem], nextCursor: null, limit: 25 }),
      listMembershipPage: vi.fn(() => Promise.resolve({
        items: [], nextCursor: null, limit: 25,
      })),
      listSystemAssigneePage: vi.fn(() => Promise.resolve({
        system_version: 1, items: [], page: { next_cursor: null, limit: 25 },
      })),
    }

    render(<SystemDirectoryAdmin
      api={api as never} context={undefined} messages={getAdminMessages('ko')}
      requestConfirmation={vi.fn()} keyFor={() => 'stable-system-key'}
      clearKey={vi.fn()} reportError={vi.fn()} onStepUp={vi.fn(() => Promise.resolve())}
      onPasswordReauth={vi.fn(() => Promise.resolve())} onEnroll={vi.fn(() => Promise.resolve())}
    />)

    fireEvent.click(screen.getByRole('button', { name: '새로고침' }))
    await waitFor(() => expect(screen.getAllByText('New System').length).toBeGreaterThan(0))

    await act(async () => {
      oldSystems.resolve({ items: [oldSystem], nextCursor: null, limit: 25 })
      await oldSystems.promise
    })

    expect(screen.getAllByText('New System').length).toBeGreaterThan(0)
    expect(screen.queryByText('Old System')).not.toBeInTheDocument()
  })
})

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((next) => { resolve = next })
  return { promise, resolve }
}
