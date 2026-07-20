import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
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
    allowed_system_ids: [], allowed_domain_ids: [], active: true, assigned_count: 0,
    version: 1, created_at: '2026-07-20T00:00:00Z', updated_at: '2026-07-20T00:00:00Z',
  }
}

describe('RoleAccessAdmin', () => {
  it('loads server roles and assigns one through the governed membership role endpoint', async () => {
    const catalogReader = role('00000000-0000-4000-8000-000000000301', 'catalog-reader', 'Catalog Reader')
    const dataSteward = role('00000000-0000-4000-8000-000000000302', 'data-steward', 'Data Steward')
    const roles = [catalogReader, dataSteward]
    const api = {
      listMemberships: vi.fn(() => Promise.resolve([member])),
      listAccessRoles: vi.fn(() => Promise.resolve(roles)),
      listSystems: vi.fn(() => Promise.resolve([])),
      getMembershipAccess: vi.fn(() => Promise.resolve({
        ...member, etag: '"3"',
        access: {
          active: true, clearance: 'INTERNAL', groups: ['datariver-role-catalog-reader'],
          allowed_actions: ['catalog.read'], denied_actions: [],
          allowed_system_ids: [], allowed_domain_ids: [],
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
    expect(screen.getByText('Data Steward')).toBeInTheDocument()
    expect(screen.queryByText('카탈로그 조회자')).not.toBeInTheDocument()
    const assignment = screen.getByLabelText('할당할 Role')
    await waitFor(() => expect(assignment).toHaveValue(catalogReader.id))
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
})
