import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { AccessRole, AdminReadContext } from '../../api/types'
import { MembershipAccessAdmin } from './MembershipAdmin'
import { getAdminMessages } from './messages'

describe('MembershipAccessAdmin identity provisioning', () => {
  it('creates an identity and Workspace membership through the governed API', async () => {
    const role: AccessRole = {
      id: '00000000-0000-4000-8000-000000000301', role_key: 'catalog-reader',
      name: 'Catalog Reader', description: 'Read-only catalog access', clearance: 'INTERNAL',
      groups: ['catalog-users'], allowed_actions: ['catalog.read'], denied_actions: [],
      allowed_system_ids: [], allowed_domain_ids: [], active: true, assigned_count: 0,
      version: 1, created_at: '2026-07-20T00:00:00Z', updated_at: '2026-07-20T00:00:00Z',
    }
    const api = {
      listMemberships: vi.fn(() => Promise.resolve([])),
      listAccessRoles: vi.fn(() => Promise.resolve([role])),
      provisionIdentityUser: vi.fn(() => Promise.resolve({
        subject_id: '00000000-0000-4000-8000-000000000401',
        username: 'hong.gildong', display_name: 'Gildong Hong', email: 'hong@example.test',
        workspace_id: '00000000-0000-4000-8000-000000000100', role_id: role.id,
        access_expires_at: '2027-01-20T00:00:00Z', temporary_password_required: true,
      })),
    }
    const context: AdminReadContext = {
      subject_id: '00000000-0000-4000-8000-000000000111',
      workspace_id: '00000000-0000-4000-8000-000000000100',
      display_name: 'Administrator', authentication_assurance: 'HARDWARE_WEBAUTHN',
      fallback_enabled: false,
      allowed_operations: ['MEMBERSHIP_ACCESS_READ', 'IDENTITY_USER_PROVISION'],
      action_vocabulary: ['admin.manage', 'catalog.read'],
    }
    const clearKey = vi.fn()

    render(<MembershipAccessAdmin
      api={api as never} context={context} messages={getAdminMessages('ko')}
      requestConfirmation={vi.fn()} keyFor={() => 'stable-identity-key'} clearKey={clearKey}
      reportError={vi.fn()} onStepUp={vi.fn(() => Promise.resolve())}
      onPasswordReauth={vi.fn(() => Promise.resolve())} onEnroll={vi.fn(() => Promise.resolve())}
    />)

    fireEvent.click(await screen.findByRole('button', { name: '신규 사용자 등록' }))
    expect(await screen.findByRole('dialog', { name: '신규 사용자 등록' })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('사용자명'), { target: { value: 'hong.gildong' } })
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'hong@example.test' } })
    fireEvent.change(screen.getByLabelText('이름'), { target: { value: 'Gildong' } })
    fireEvent.change(screen.getByLabelText('성'), { target: { value: 'Hong' } })
    fireEvent.change(screen.getByLabelText('간편 Role'), { target: { value: role.id } })
    fireEvent.change(screen.getByLabelText('임시 비밀번호'), {
      target: { value: 'Temporary-Only-42!' },
    })
    fireEvent.change(screen.getByLabelText('임시 비밀번호 확인'), {
      target: { value: 'Temporary-Only-42!' },
    })
    fireEvent.click(screen.getByRole('button', { name: '계정 생성' }))

    await waitFor(() => expect(api.provisionIdentityUser).toHaveBeenCalledWith({
      username: 'hong.gildong', email: 'hong@example.test',
      first_name: 'Gildong', last_name: 'Hong', department_id: null,
      job_function: null, role_id: role.id, temporary_password: 'Temporary-Only-42!',
    }, 'stable-identity-key'))
    expect(clearKey).toHaveBeenCalledWith(
      `identity-user:hong.gildong:hong@example.test:${role.id}`,
    )
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })
})
