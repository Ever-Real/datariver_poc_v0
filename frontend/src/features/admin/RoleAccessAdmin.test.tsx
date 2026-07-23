import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { AccessRole, AdminReadContext, WorkspaceMembershipSummary } from '../../api/types'
import type { PendingAdminMutation } from './AdminMutationConfirmDialog'
import { getAdminMessages } from './messages'
import { RoleAccessAdmin } from './RoleAccessAdmin'

const member: WorkspaceMembershipSummary = {
  subject_id: '00000000-0000-4000-8000-000000000222', display_name: 'Engineer',
  email: 'engineer@example.test', last_login_at: null, last_login_ip: null,
  owned_table_count: 0, change_request_count: 0, subject_active: true, membership_active: true,
  department_id: null, job_function: 'ENGINEER', clearance: 'INTERNAL', membership_version: 3,
  access_expires_at: '2027-01-20T00:00:00Z', renewal_eligible_at: '2026-12-21T00:00:00Z',
  access_expired: false, pending_renewal_request_id: null,
  renewal_request_eligible: false,
}

function role(id: string, key: string, name: string): AccessRole {
  return {
    id, role_key: key, name, description: `${name} description`, clearance: 'INTERNAL',
    groups: ['catalog-users'], allowed_actions: ['catalog.read'], denied_actions: [],
    allowed_system_ids: [], allowed_domain_ids: [],
    data_access_rules: [{
      classification: 'PUBLIC', access_level: 'FULL_ACCESS', partial_treatment: null,
      allowed_residency_regions: ['KR'],
      allowed_processing_purposes: ['METADATA_READ'],
    }],
    active: true, assigned_count: 0,
    version: 1, created_at: '2026-07-20T00:00:00Z', updated_at: '2026-07-20T00:00:00Z',
  }
}

describe('RoleAccessAdmin', () => {
  it('keeps Role definitions on bounded server cursor pages', async () => {
    const first = role(
      '00000000-0000-4000-8000-000000000313',
      'first-role',
      'First Role',
    )
    const second = role(
      '00000000-0000-4000-8000-000000000314',
      'second-role',
      'Second Role',
    )
    const api = {
      listMembershipPage: vi.fn(() => Promise.resolve({
        items: [], nextCursor: null, limit: 25,
      })),
      listAccessRolePage: vi.fn()
        .mockResolvedValueOnce({ items: [first], nextCursor: 'next-role', limit: 25 })
        .mockResolvedValueOnce({ items: [second], nextCursor: null, limit: 25 }),
      listSystemPage: vi.fn(() => Promise.resolve({
        items: [], nextCursor: null, limit: 25,
      })),
    }

    render(<RoleAccessAdmin
      api={api as never} context={undefined} messages={getAdminMessages('ko')}
      requestConfirmation={vi.fn()} keyFor={() => 'stable-role-key'}
      clearKey={vi.fn()} reportError={vi.fn()} onStepUp={vi.fn(() => Promise.resolve())}
      onPasswordReauth={vi.fn(() => Promise.resolve())} onEnroll={vi.fn(() => Promise.resolve())}
    />)

    expect(await screen.findByText('First Role')).toBeInTheDocument()
    const rolePanel = screen.getByRole('heading', { name: 'Role 정의' }).closest('section')
    if (!rolePanel) throw new Error('Role panel is not available')
    const next = within(rolePanel).getAllByRole('button', { name: '다음' })
      .find((button) => !button.hasAttribute('disabled'))
    if (!next) throw new Error('Role next-page control is not enabled')
    fireEvent.click(next)

    expect(await screen.findByText('Second Role')).toBeInTheDocument()
    expect(api.listAccessRolePage).toHaveBeenLastCalledWith(expect.objectContaining({
      cursor: 'next-role',
      limit: 25,
    }))
    expect(screen.queryByText('First Role')).not.toBeInTheDocument()
  })

  it('does not let an older directory response overwrite a newer refresh', async () => {
    const oldRoles = deferred<{
      items: AccessRole[]
      nextCursor: string | null
      limit: number
    }>()
    const oldRole = role(
      '00000000-0000-4000-8000-000000000311',
      'old-role',
      'Old Role',
    )
    const newRole = role(
      '00000000-0000-4000-8000-000000000312',
      'new-role',
      'New Role',
    )
    const api = {
      listMembershipPage: vi.fn(() => Promise.resolve({
        items: [], nextCursor: null, limit: 25,
      })),
      listAccessRolePage: vi.fn()
        .mockImplementationOnce(() => oldRoles.promise)
        .mockResolvedValue({ items: [newRole], nextCursor: null, limit: 25 }),
      listSystemPage: vi.fn(() => Promise.resolve({
        items: [], nextCursor: null, limit: 25,
      })),
    }

    render(<RoleAccessAdmin
      api={api as never} context={undefined} messages={getAdminMessages('ko')}
      requestConfirmation={vi.fn()} keyFor={() => 'stable-role-key'}
      clearKey={vi.fn()} reportError={vi.fn()} onStepUp={vi.fn(() => Promise.resolve())}
      onPasswordReauth={vi.fn(() => Promise.resolve())} onEnroll={vi.fn(() => Promise.resolve())}
    />)

    fireEvent.click(screen.getByRole('button', { name: '새로고침' }))
    expect(await screen.findByText('New Role')).toBeInTheDocument()

    await act(async () => {
      oldRoles.resolve({ items: [oldRole], nextCursor: null, limit: 25 })
      await oldRoles.promise
    })

    expect(screen.getByText('New Role')).toBeInTheDocument()
    expect(screen.queryByText('Old Role')).not.toBeInTheDocument()
  })

  it('loads server roles and assigns one through the governed membership role endpoint', async () => {
    const catalogReader = role('00000000-0000-4000-8000-000000000301', 'catalog-reader', 'Catalog Reader')
    const dataSteward = role('00000000-0000-4000-8000-000000000302', 'data-steward', 'Data Steward')
    const roles = [catalogReader, dataSteward]
    const api = {
      listMembershipPage: vi.fn(() => Promise.resolve({
        items: [member], nextCursor: null, limit: 25,
      })),
      listAccessRolePage: vi.fn(() => Promise.resolve({
        items: roles, nextCursor: null, limit: 25,
      })),
      listSystemPage: vi.fn(() => Promise.resolve({
        items: [], nextCursor: null, limit: 25,
      })),
      getMembershipAccess: vi.fn(() => Promise.resolve({
        ...member, etag: '"3"',
        access: {
          active: true, clearance: 'INTERNAL', groups: ['datariver-role-data-steward'],
          allowed_actions: ['catalog.read'], denied_actions: [],
          allowed_system_ids: [], allowed_domain_ids: [],
        },
        role_assignment: {
          status: 'VERIFIED', role_id: catalogReader.id, role_version: 1,
          assignment_version: 2, membership_version: 3, access_payload_hash: 'b'.repeat(64),
          assigned_by: context.subject_id, updated_at: '2026-07-20T00:00:00Z',
          legacy_markers: ['datariver-role-data-steward'],
        },
      })),
      assignMembershipRole: vi.fn(() => Promise.resolve({
        subject_id: member.subject_id, role_id: dataSteward.id, membership_version: 4,
        payload_hash: 'a'.repeat(64),
      })),
    }
    const context: AdminReadContext = {
      subject_id: '00000000-0000-4000-8000-000000000111', workspace_id: 'workspace-one',
      display_name: 'Administrator', authentication_assurance: 'HARDWARE_WEBAUTHN',
      fallback_enabled: false, allowed_operations: ['MEMBERSHIP_ACCESS_READ', 'MEMBERSHIP_ACCESS_UPDATE'],
      action_vocabulary: ['catalog.read'],
    }
    let pending: PendingAdminMutation | undefined

    render(<RoleAccessAdmin
      api={api as never} context={context} messages={getAdminMessages('ko')}
      requestConfirmation={(next) => { pending = next }} keyFor={() => 'stable-role-key'}
      clearKey={vi.fn()} reportError={vi.fn()} onStepUp={vi.fn(() => Promise.resolve())}
      onPasswordReauth={vi.fn(() => Promise.resolve())} onEnroll={vi.fn(() => Promise.resolve())}
    />)

    expect(await screen.findByText('Catalog Reader')).toBeInTheDocument()
    expect(screen.getAllByText('Data Steward').length).toBeGreaterThan(0)
    expect(screen.queryByText('카탈로그 조회자')).not.toBeInTheDocument()
    const assignment = screen.getByLabelText('할당할 Role')
    await waitFor(() => expect(assignment).toHaveValue(catalogReader.id))
    expect(screen.getByText('v1 · VERIFIED')).toBeInTheDocument()
    fireEvent.change(assignment, { target: { value: dataSteward.id } })
    const assignButton = screen.getByRole('button', { name: 'Role 할당' })
    await waitFor(() => expect(assignButton).toBeEnabled())
    fireEvent.click(assignButton)
    expect(pending?.title).toBe('Engineer Role 할당')
    if (!pending) throw new Error('role assignment confirmation was not requested')
    await act(async () => { await pending?.execute() })
    await waitFor(() => expect(api.assignMembershipRole).toHaveBeenCalledWith(
      member.subject_id, dataSteward.id, '"3"', 'stable-role-key',
    ))
  })

  it('preserves missing classifications and edits the four-class policy-book rules', async () => {
    const catalogReader = role(
      '00000000-0000-4000-8000-000000000301',
      'catalog-reader',
      'Catalog Reader',
    )
    const api = {
      listMembershipPage: vi.fn(() => Promise.resolve({
        items: [member], nextCursor: null, limit: 25,
      })),
      listAccessRolePage: vi.fn(() => Promise.resolve({
        items: [catalogReader], nextCursor: null, limit: 25,
      })),
      listSystemPage: vi.fn(() => Promise.resolve({
        items: [], nextCursor: null, limit: 25,
      })),
      getMembershipAccess: vi.fn(() => Promise.resolve({
        ...member, etag: '"3"',
        access: {
          active: true, clearance: 'INTERNAL', groups: [],
          allowed_actions: ['catalog.read'], denied_actions: [],
          allowed_system_ids: [], allowed_domain_ids: [],
        },
        role_assignment: {
          status: 'MANUAL', role_id: null, role_version: null,
          assignment_version: null, membership_version: null, access_payload_hash: null,
          assigned_by: null, updated_at: null, legacy_markers: [],
        },
      })),
    }
    const context: AdminReadContext = {
      subject_id: '00000000-0000-4000-8000-000000000111', workspace_id: 'workspace-one',
      display_name: 'Administrator', authentication_assurance: 'HARDWARE_WEBAUTHN',
      fallback_enabled: false, allowed_operations: ['MEMBERSHIP_ACCESS_READ', 'MEMBERSHIP_ACCESS_UPDATE'],
      action_vocabulary: ['catalog.read'],
    }

    render(<RoleAccessAdmin
      api={api as never} context={context} messages={getAdminMessages('ko')}
      requestConfirmation={vi.fn()} keyFor={() => 'stable-role-key'}
      clearKey={vi.fn()} reportError={vi.fn()} onStepUp={vi.fn(() => Promise.resolve())}
      onPasswordReauth={vi.fn(() => Promise.resolve())} onEnroll={vi.fn(() => Promise.resolve())}
    />)

    fireEvent.click(await screen.findByRole('button', { name: /Catalog Reader/ }))
    expect(screen.getByRole('heading', { name: '데이터 접근 정책' })).toBeInTheDocument()
    expect(screen.getByLabelText('PUBLIC 접근 수준')).toHaveValue('FULL_ACCESS')
    expect(screen.getByLabelText('INTERNAL 접근 수준')).toHaveValue('MISSING')
    expect(screen.getByLabelText('CONFIDENTIAL 접근 수준')).toHaveValue('MISSING')
    expect(screen.getByLabelText('RESTRICTED 접근 수준')).toHaveValue('MISSING')
    expect(screen.getByText(/누락된 등급은 fail-closed/)).toBeInTheDocument()
  })
})

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((next) => { resolve = next })
  return { promise, resolve }
}
