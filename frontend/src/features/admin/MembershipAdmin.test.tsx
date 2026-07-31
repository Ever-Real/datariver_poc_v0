import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type {
  AccessRole,
  AdminReadContext,
  WorkspaceMembershipSummary,
} from '../../api/types'
import type { PendingAdminMutation } from './AdminMutationConfirmDialog'
import { MembershipAccessAdmin } from './MembershipAdmin'
import { getAdminMessages } from './messages'

const catalogReader: AccessRole = {
  id: '00000000-0000-4000-8000-000000000301', role_key: 'catalog-reader',
  name: 'Catalog Reader', description: 'Read-only catalog access', clearance: 'INTERNAL',
  groups: ['catalog-users'], allowed_actions: ['catalog.read'], denied_actions: [],
  allowed_system_ids: [], allowed_domain_ids: [], data_access_rules: [], active: true,
  assigned_count: 0, version: 1, created_at: '2026-07-20T00:00:00Z', updated_at: '2026-07-20T00:00:00Z',
}

const dataSteward: AccessRole = {
  ...catalogReader,
  id: '00000000-0000-4000-8000-000000000302', role_key: 'data-steward',
  name: 'Data Steward', clearance: 'CONFIDENTIAL',
}

function context(operations: AdminReadContext['allowed_operations']): AdminReadContext {
  return {
    subject_id: '00000000-0000-4000-8000-000000000111',
    workspace_id: '00000000-0000-4000-8000-000000000100',
    display_name: 'Administrator', authentication_assurance: 'HARDWARE_WEBAUTHN',
    fallback_enabled: false, allowed_operations: operations, action_vocabulary: ['catalog.read'],
  }
}

function member(subjectId = '00000000-0000-4000-8000-000000000501'): WorkspaceMembershipSummary {
  return {
    subject_id: subjectId, display_name: 'Engineer', email: 'engineer@example.test',
    last_login_at: null, last_login_ip: null, owned_table_count: 0, change_request_count: 0,
    subject_active: true, membership_active: true, department_id: null, job_function: 'ENGINEER',
    clearance: 'INTERNAL', membership_version: 3, access_expires_at: null,
    renewal_eligible_at: null, access_expired: false, pending_renewal_request_id: null,
    renewal_request_eligible: false,
  }
}

function renderUsers(
  api: object,
  allowedOperations: AdminReadContext['allowed_operations'],
  requestConfirmation: (next: PendingAdminMutation) => void = vi.fn(),
) {
  return render(<MembershipAccessAdmin
    api={api as never} context={context(allowedOperations)} messages={getAdminMessages('ko')}
    requestConfirmation={requestConfirmation} keyFor={() => 'stable-key'} clearKey={vi.fn()}
    reportError={vi.fn()} onStepUp={vi.fn(() => Promise.resolve())}
    onPasswordReauth={vi.fn(() => Promise.resolve())} onEnroll={vi.fn(() => Promise.resolve())}
  />)
}

describe('MembershipAccessAdmin', () => {
  it('creates an identity and Workspace membership through the governed API', async () => {
    const api = {
      listMembershipPage: vi.fn(() => Promise.resolve({ items: [], nextCursor: null, limit: 25 })),
      listAccessRolePage: vi.fn(() => Promise.resolve({ items: [catalogReader], nextCursor: null, limit: 25 })),
      provisionIdentityUser: vi.fn(() => Promise.resolve({ subject_id: 'new-user' })),
    }
    renderUsers(api, ['MEMBERSHIP_ACCESS_READ', 'IDENTITY_USER_PROVISION'])

    fireEvent.click(await screen.findByRole('button', { name: '사용자 등록' }))
    expect(await screen.findByRole('dialog', { name: '사용자 등록' })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('사용자명'), { target: { value: 'hong.gildong' } })
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'hong@example.test' } })
    fireEvent.change(screen.getByLabelText('이름'), { target: { value: 'Gildong' } })
    fireEvent.change(screen.getByLabelText('성'), { target: { value: 'Hong' } })
    fireEvent.change(screen.getByLabelText('데이터·화면 접근 Role'), { target: { value: catalogReader.id } })
    fireEvent.change(screen.getByLabelText('임시 비밀번호'), { target: { value: 'Temporary-Only-42!' } })
    fireEvent.change(screen.getByLabelText('임시 비밀번호 확인'), { target: { value: 'Temporary-Only-42!' } })
    fireEvent.click(screen.getAllByRole('button', { name: '사용자 등록' }).at(-1)!)

    await waitFor(() => expect(api.provisionIdentityUser).toHaveBeenCalledWith({
      username: 'hong.gildong', email: 'hong@example.test', first_name: 'Gildong', last_name: 'Hong',
      department_id: null, job_function: null, role_id: catalogReader.id,
      temporary_password: 'Temporary-Only-42!',
    }, 'stable-key'))
    expect(screen.queryByRole('dialog', { name: '사용자 등록' })).not.toBeInTheDocument()
  })

  it('opens the profile modal from a table row and assigns Role through the governed endpoint', async () => {
    const target = member()
    const api = {
      listMembershipPage: vi.fn(() => Promise.resolve({ items: [target], nextCursor: null, limit: 25 })),
      getMembershipAccess: vi.fn(() => Promise.resolve({
        ...target, etag: '"3"',
        access: { active: true, clearance: 'INTERNAL', groups: [], allowed_actions: ['catalog.read'], denied_actions: [], allowed_system_ids: [], allowed_domain_ids: [] },
        role_assignment: { status: 'VERIFIED', role_id: catalogReader.id, role_version: 1, assignment_version: 1, membership_version: 3, access_payload_hash: 'a'.repeat(64), assigned_by: null, updated_at: null, legacy_markers: [] },
      })),
      listAccessRolePage: vi.fn(() => Promise.resolve({ items: [catalogReader, dataSteward], nextCursor: null, limit: 25 })),
      listMembershipChangeRequestActivity: vi.fn(() => Promise.resolve({ items: [], nextCursor: null, limit: 25 })),
      listMembershipOwnedTables: vi.fn(() => Promise.resolve({ items: [], nextCursor: null, limit: 25 })),
      assignMembershipRole: vi.fn(() => Promise.resolve({ subject_id: target.subject_id, role_id: dataSteward.id, membership_version: 4, payload_hash: 'b'.repeat(64) })),
    }
    let pending: PendingAdminMutation | undefined
    renderUsers(api, ['MEMBERSHIP_ACCESS_READ', 'MEMBERSHIP_ACCESS_UPDATE'], (next) => { pending = next })

    fireEvent.click(await screen.findByText('Engineer'))
    expect(await screen.findByRole('dialog', { name: '사용자 프로필 수정' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: '데이터·화면 접근' }))
    const roleSelect = await screen.findByLabelText('데이터 및 화면 접근 Role')
    await waitFor(() => expect(roleSelect).toHaveValue(catalogReader.id))
    fireEvent.change(roleSelect, { target: { value: dataSteward.id } })
    fireEvent.click(screen.getByRole('button', { name: '접근 Role 저장' }))
    if (!pending) throw new Error('Role assignment confirmation was not requested')
    await act(async () => { await pending?.execute() })
    expect(api.assignMembershipRole).toHaveBeenCalledWith(
      target.subject_id, dataSteward.id, '"3"', 'stable-key',
    )
    expect(screen.queryByText('세부 Access 문서 (고급)')).not.toBeInTheDocument()
  })

  it('uses governed profile, activity and temporary-password APIs without inventing audit data', async () => {
    const target = {
      ...member(),
      last_login_at: '2026-07-30T01:00:00Z',
      last_login_ip: '10.0.0.42',
      change_request_count: 1,
      owned_table_count: 1,
    }
    const api = {
      listMembershipPage: vi.fn(() => Promise.resolve({ items: [target], nextCursor: null, limit: 25 })),
      getMembershipAccess: vi.fn(() => Promise.resolve({
        ...target, etag: '"3"',
        access: { active: true, clearance: 'INTERNAL', groups: [], allowed_actions: ['catalog.read'], denied_actions: [], allowed_system_ids: [], allowed_domain_ids: [] },
        role_assignment: { status: 'VERIFIED', role_id: catalogReader.id, role_version: 1, assignment_version: 1, membership_version: 3, access_payload_hash: 'a'.repeat(64), assigned_by: null, updated_at: null, legacy_markers: [] },
      })),
      getIdentityUserProfile: vi.fn(() => Promise.resolve({
        subject_id: target.subject_id, username: 'engineer', display_name: 'Engineer',
        email: 'engineer@example.test', first_name: 'Data', last_name: 'Engineer',
        department_id: null, job_function: 'ENGINEER', membership_version: 3,
        provider_enabled: true, email_verified: true, required_actions: [], etag: '"3"',
      })),
      listAccessRolePage: vi.fn(() => Promise.resolve({ items: [catalogReader], nextCursor: null, limit: 25 })),
      listMembershipChangeRequestActivity: vi.fn(() => Promise.resolve({
        items: [{
          change_request_id: 'cr-one', number: 'CR-1', title: 'Schema change',
          request_type: 'SCHEMA', state: 'APPROVED', relationship: 'REQUESTER',
          classification: 'INTERNAL', updated_at: '2026-07-30T02:00:00Z',
        }], nextCursor: null, limit: 25,
      })),
      listMembershipOwnedTables: vi.fn(() => Promise.resolve({
        items: [{
          asset_id: 'asset-one', name: 'orders', platform: 'postgres',
          database_name: 'warehouse', schema_name: 'public', classification: 'INTERNAL',
          source_version: 'v1', observed_at: '2026-07-30T03:00:00Z',
        }], nextCursor: null, limit: 25,
      })),
      updateIdentityUserProfile: vi.fn(() => Promise.resolve({
        subject_id: target.subject_id, membership_version: 4,
      })),
      resetIdentityTemporaryPassword: vi.fn(() => Promise.resolve({
        subject_id: target.subject_id, temporary_password_required: true, sessions_revoked: true,
      })),
    }
    const confirmations: PendingAdminMutation[] = []
    renderUsers(api, [
      'MEMBERSHIP_ACCESS_READ',
      'IDENTITY_USER_PROFILE_READ',
      'IDENTITY_USER_PROFILE_UPDATE',
      'IDENTITY_USER_PASSWORD_RESET',
    ], (next) => { confirmations.push(next) })

    fireEvent.click(await screen.findByText('Engineer'))
    expect(await screen.findByText('10.0.0.42')).toBeInTheDocument()
    fireEvent.change(await screen.findByLabelText('업무 역할'), { target: { value: 'DATA_ENGINEER' } })
    fireEvent.click(screen.getByRole('button', { name: '사용자 정보 저장' }))
    await act(async () => { await confirmations.at(-1)?.execute() })
    expect(api.updateIdentityUserProfile).toHaveBeenCalledWith(
      target.subject_id,
      {
        email: 'engineer@example.test',
        first_name: 'Data',
        last_name: 'Engineer',
        department_id: null,
        job_function: 'DATA_ENGINEER',
      },
      '"3"',
      'stable-key',
    )

    fireEvent.click(screen.getByRole('tab', { name: 'CR·활동' }))
    expect(await screen.findByText('Schema change')).toBeInTheDocument()
    expect(screen.getByText('orders')).toBeInTheDocument()
    expect(screen.getByText(/상세 감사 로그가 아니라/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('tab', { name: '비밀번호 재설정' }))
    fireEvent.change(screen.getByLabelText('새 임시 비밀번호'), { target: { value: 'Temporary-Only-42!' } })
    fireEvent.change(screen.getByLabelText('임시 비밀번호 확인'), { target: { value: 'Temporary-Only-42!' } })
    fireEvent.click(screen.getByRole('button', { name: '임시 비밀번호 재설정' }))
    await act(async () => { await confirmations.at(-1)?.execute() })
    expect(api.resetIdentityTemporaryPassword).toHaveBeenCalledWith(
      target.subject_id,
      'Temporary-Only-42!',
      '"3"',
      'stable-key',
    )
  })
})
