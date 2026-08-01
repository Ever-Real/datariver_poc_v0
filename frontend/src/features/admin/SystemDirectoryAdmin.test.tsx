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
      effective_profile_role: 'ENGINEER_STEWARD',
    }
    const replacement: WorkspaceMembershipSummary = {
      ...target,
      subject_id: '00000000-0000-4000-8000-000000000725',
      display_name: 'Replacement User',
      email: 'replacement@example.test',
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
      listSystemAssigneeCandidates: vi.fn(() => Promise.resolve({
        items: [
          { subject_id: target.subject_id, display_name: target.display_name, email: target.email, tier: 'ENGINEER_STEWARD' },
          { subject_id: replacement.subject_id, display_name: replacement.display_name, email: replacement.email, tier: 'MANAGER' },
        ], nextCursor: null, limit: 25,
      })),
      listSystemAssigneePage: vi.fn()
        .mockResolvedValueOnce({
          system_version: 1,
          items: assignments,
          page: { next_cursor: null, limit: 25 },
        })
        .mockResolvedValue({
          system_version: 2,
          items: [{
            ...assignments[0],
            subject_id: replacement.subject_id,
            display_name: replacement.display_name,
          }, assignments[1]],
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

    const changeDeveloper = await screen.findByRole('button', { name: 'Developer 담당자 변경' })
    fireEvent.change(screen.getByLabelText('Developer 검색'), {
      target: { value: 'replacement@example.test' },
    })
    await waitFor(() => expect(api.listSystemAssigneeCandidates).toHaveBeenCalledWith(
      'replacement@example.test', expect.anything(),
    ))
    expect(screen.getAllByRole('option', {
      name: 'Replacement User · replacement@example.test · MANAGER',
    })).toHaveLength(2)
    fireEvent.click(changeDeveloper)
    fireEvent.change(screen.getByLabelText('Developer 담당자'), {
      target: { value: replacement.subject_id },
    })
    fireEvent.click(screen.getByRole('button', { name: '변경사항 저장' }))
    expect(pending?.title).toBe('시스템 담당자 변경')
    if (!pending) throw new Error('system assignment confirmation was not requested')
    await act(async () => { await pending?.execute() })

    expect(api.patchSystemAssignees).toHaveBeenCalledWith(
      selectedSystem.system_id,
      [{
        subject_id: replacement.subject_id,
        responsibility: 'DEVELOPER',
        priority: 1,
      }],
      [{
        subject_id: target.subject_id,
        responsibility: 'DEVELOPER',
      }],
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
      listSystemAssigneeCandidates: vi.fn(() => Promise.resolve({
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

  it('creates a system only after confirmation with one idempotency key', async () => {
    const api = {
      listSystemPage: vi.fn(() => Promise.resolve({ items: [], nextCursor: null, limit: 25 })),
      listSystemAssigneeCandidates: vi.fn(() => Promise.resolve({ items: [], nextCursor: null, limit: 25 })),
      listSystemAssigneePage: vi.fn(),
      createSystem: vi.fn(() => Promise.resolve(system(
        '00000000-0000-4000-8000-000000000799', 'CRM', 'Customer Data',
      ))),
    }
    let pending: PendingAdminMutation | undefined
    render(<SystemDirectoryAdmin
      api={api as never}
      context={{
        subject_id: 'admin', workspace_id: 'workspace', display_name: 'Administrator',
        authentication_assurance: 'HARDWARE_WEBAUTHN', fallback_enabled: false,
        allowed_operations: ['SYSTEM_ASSIGNMENT_UPDATE'], action_vocabulary: [],
      }}
      messages={getAdminMessages('ko')}
      requestConfirmation={(value) => { pending = value }}
      keyFor={() => 'system-create-idempotency-key'}
      clearKey={vi.fn()} reportError={vi.fn()}
      onStepUp={vi.fn(() => Promise.resolve())}
      onPasswordReauth={vi.fn(() => Promise.resolve())}
      onEnroll={vi.fn(() => Promise.resolve())}
    />)

    fireEvent.click(await screen.findByRole('button', { name: '시스템 추가' }))
    fireEvent.change(screen.getByLabelText('시스템 코드'), { target: { value: 'CRM' } })
    fireEvent.change(screen.getByLabelText('시스템 이름'), { target: { value: 'Customer Data' } })
    fireEvent.change(screen.getByLabelText('설명'), { target: { value: 'Customer source' } })
    fireEvent.click(screen.getByRole('button', { name: '저장' }))
    expect(api.createSystem).not.toHaveBeenCalled()
    expect(pending?.title).toBe('신규 시스템 생성')
    await act(async () => { await pending?.execute() })
    expect(api.createSystem).toHaveBeenCalledWith(
      { code: 'CRM', name: 'Customer Data', description: 'Customer source' },
      'system-create-idempotency-key',
    )
  })

  it('makes no system mutation, confirmation, or step-up call without the capability', async () => {
    const selectedSystem = system(
      '00000000-0000-4000-8000-000000000722', 'FAB', 'Fabrication',
    )
    const api = {
      listSystemPage: vi.fn(() => Promise.resolve({
        items: [selectedSystem], nextCursor: null, limit: 25,
      })),
      listSystemAssigneeCandidates: vi.fn(() => Promise.resolve({
        items: [{ subject_id: 'member-one', display_name: 'Member One', email: null, tier: 'ENGINEER_STEWARD' }], nextCursor: null, limit: 25,
      })),
      listSystemAssigneePage: vi.fn(() => Promise.resolve({
        system_version: 1,
        items: [{
          subject_id: 'member-one', display_name: 'Member One',
          responsibility: 'DEVELOPER' as const, priority: 1, active: true,
        }],
        page: { next_cursor: null, limit: 25 },
      })),
      createSystem: vi.fn(),
      patchSystemAssignees: vi.fn(),
    }
    const requestConfirmation = vi.fn()
    const onStepUp = vi.fn(() => Promise.resolve())
    render(<SystemDirectoryAdmin
      api={api as never}
      context={{
        subject_id: 'admin', workspace_id: 'workspace', display_name: 'Administrator',
        authentication_assurance: 'PASSWORD', fallback_enabled: false,
        allowed_operations: ['MEMBERSHIP_ACCESS_READ'], action_vocabulary: [],
      }}
      messages={getAdminMessages('ko')}
      requestConfirmation={requestConfirmation}
      keyFor={() => 'stable-system-key'}
      clearKey={vi.fn()}
      reportError={vi.fn()}
      onStepUp={onStepUp}
      onPasswordReauth={vi.fn(() => Promise.resolve())}
      onEnroll={vi.fn(() => Promise.resolve())}
    />)

    const create = await screen.findByRole('button', { name: '시스템 추가' })
    expect(create).toBeDisabled()
    fireEvent.click(create)
    const edit = await screen.findByRole('button', { name: 'Developer 담당자 변경' })
    const remove = screen.getByRole('button', { name: 'Developer 담당자 삭제' })
    expect(edit).toBeDisabled()
    expect(remove).toBeDisabled()
    fireEvent.click(edit)
    fireEvent.click(remove)

    expect(api.createSystem).not.toHaveBeenCalled()
    expect(api.patchSystemAssignees).not.toHaveBeenCalled()
    expect(requestConfirmation).not.toHaveBeenCalled()
    expect(onStepUp).not.toHaveBeenCalled()
  })
})

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((next) => { resolve = next })
  return { promise, resolve }
}
