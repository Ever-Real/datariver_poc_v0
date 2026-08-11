import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type {
  AdminReadContext,
  ProfileRolePolicy,
  WorkspaceMembershipSummary,
} from '../../api/types'
import type { PendingAdminMutation } from './AdminMutationConfirmDialog'
import { MembershipAccessAdmin } from './MembershipAdmin'
import { getAdminMessages } from './messages'

const profileRolePolicy: ProfileRolePolicy = {
  policy_version: 'PROFILE_ROLE_POLICY_V1',
  items: [
    {
      tier: 'VIEWER',
      label: 'Viewer',
      description: '기본 서비스 조회 권한',
      allowed_actions: ['change.read'],
      services: [{ service_key: 'change', service_label: '변경관리', action_labels: ['조회'] }],
      assignable_to_system: false,
      lifecycle_note: '이력 보존',
    },
    {
      tier: 'ENGINEER_STEWARD',
      label: 'Engineer / Steward',
      description: '담당 System 범위의 등록·변경·품질 관리',
      allowed_actions: ['change.read', 'change.create', 'change.edit', 'change.review'],
      services: [{ service_key: 'change', service_label: '변경관리', action_labels: ['조회', '등록', '수정', '검토'] }],
      assignable_to_system: true,
      lifecycle_note: '취소·이력 보존',
    },
    {
      tier: 'MANAGER',
      label: 'Manager',
      description: '지식·거버넌스 관리 포함',
      allowed_actions: ['change.read', 'governance.review'],
      services: [{ service_key: 'governance', service_label: '거버넌스', action_labels: ['조회', '검토'] }],
      assignable_to_system: true,
      lifecycle_note: '버전·이력 보존',
    },
    {
      tier: 'ADMIN',
      label: 'Admin',
      description: 'Canonical Admin 권한',
      allowed_actions: ['admin.manage'],
      services: [{ service_key: 'admin', service_label: '관리자', action_labels: ['관리'] }],
      assignable_to_system: true,
      lifecycle_note: '감사 이력 보존',
    },
  ],
}

function membershipAccess(target: WorkspaceMembershipSummary) {
  return {
    ...target,
    etag: '"3"',
    access: {
      active: true,
      clearance: 'INTERNAL' as const,
      groups: [],
      allowed_actions: ['change.read'],
      denied_actions: [],
      allowed_system_ids: [],
      allowed_domain_ids: [],
    },
    role_assignment: {
      status: 'MANUAL' as const,
      role_id: null,
      role_version: null,
      assignment_version: null,
      membership_version: 3,
      access_payload_hash: null,
      assigned_by: null,
      updated_at: null,
      legacy_markers: [],
    },
    canonical_admin_binding: {
      status: 'NONE' as const,
      role_version: null,
      catalog_version: null,
      membership_version: null,
      binding_version: null,
      updated_at: null,
    },
    profile_role: {
      status: 'VERIFIED' as const,
      tier: 'ENGINEER_STEWARD' as const,
      policy_version: 'PROFILE_ROLE_POLICY_V1',
      membership_version: 3,
      assignment_version: 1,
      updated_at: '2026-07-30T00:00:00Z',
    },
  }
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
    effective_profile_role: 'ENGINEER_STEWARD',
  }
}

function renderUsers(
  api: object,
  allowedOperations: AdminReadContext['allowed_operations'],
  requestConfirmation: (next: PendingAdminMutation) => void = vi.fn(),
  actionVocabulary: string[] = ['catalog.read'],
) {
  return render(<MembershipAccessAdmin
    api={api as never} context={{ ...context(allowedOperations), action_vocabulary: actionVocabulary }} messages={getAdminMessages('ko')}
    requestConfirmation={requestConfirmation} keyFor={() => 'stable-key'} clearKey={vi.fn()}
    reportError={vi.fn()} onStepUp={vi.fn(() => Promise.resolve())}
    onPasswordReauth={vi.fn(() => Promise.resolve())} onEnroll={vi.fn(() => Promise.resolve())}
  />)
}

describe('MembershipAccessAdmin', () => {
  it('keeps user provisioning fail-closed when the server omits the capability', async () => {
    const api = {
      listMembershipPage: vi.fn(() => Promise.resolve({ items: [], nextCursor: null, limit: 25 })),
      provisionIdentityUser: vi.fn(),
    }
    const requestConfirmation = vi.fn()
    const onStepUp = vi.fn(() => Promise.resolve())
    render(<MembershipAccessAdmin
      api={api as never}
      context={{ ...context(['MEMBERSHIP_ACCESS_READ']), authentication_assurance: 'PASSWORD' }}
      messages={getAdminMessages('ko')}
      requestConfirmation={requestConfirmation}
      keyFor={() => 'stable-key'}
      clearKey={vi.fn()}
      reportError={vi.fn()}
      onStepUp={onStepUp}
      onPasswordReauth={vi.fn(() => Promise.resolve())}
      onEnroll={vi.fn(() => Promise.resolve())}
    />)

    const provision = await screen.findByRole('button', { name: '사용자 등록' })
    expect(provision).toBeDisabled()
    fireEvent.click(provision)

    expect(screen.queryByRole('dialog', { name: '사용자 등록' })).not.toBeInTheDocument()
    expect(api.provisionIdentityUser).not.toHaveBeenCalled()
    expect(requestConfirmation).not.toHaveBeenCalled()
    expect(onStepUp).not.toHaveBeenCalled()
  })

  it('creates an identity and Workspace membership through the governed API', async () => {
    const api = {
      listMembershipPage: vi.fn(() => Promise.resolve({ items: [], nextCursor: null, limit: 25 })),
      provisionIdentityUser: vi.fn(() => Promise.resolve({ subject_id: 'new-user' })),
    }
    renderUsers(api, ['MEMBERSHIP_ACCESS_READ', 'IDENTITY_USER_PROVISION'])

    fireEvent.click(await screen.findByRole('button', { name: '사용자 등록' }))
    expect(await screen.findByRole('dialog', { name: '사용자 등록' })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('사용자명'), { target: { value: 'hong.gildong' } })
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'hong@example.test' } })
    fireEvent.change(screen.getByLabelText('이름'), { target: { value: 'Gildong' } })
    fireEvent.change(screen.getByLabelText('성'), { target: { value: 'Hong' } })
    expect(screen.getByLabelText('업무 역할').tagName).toBe('SELECT')
    fireEvent.change(screen.getByLabelText('업무 역할'), { target: { value: 'data_steward' } })
    expect(screen.getByText(/POC 접근 정책/)).toBeInTheDocument()
    expect(screen.queryByLabelText('데이터·화면 접근 Role')).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('임시 비밀번호'), { target: { value: 'Temporary-Only-42!' } })
    fireEvent.change(screen.getByLabelText('임시 비밀번호 확인'), { target: { value: 'Temporary-Only-42!' } })
    fireEvent.click(screen.getAllByRole('button', { name: '사용자 등록' }).at(-1)!)

    await waitFor(() => expect(api.provisionIdentityUser).toHaveBeenCalledWith({
      username: 'hong.gildong', email: 'hong@example.test', first_name: 'Gildong', last_name: 'Hong',
      department_id: null, job_function: 'data_steward', role_id: null,
      temporary_password: 'Temporary-Only-42!',
    }, 'stable-key'))
    expect(screen.queryByRole('dialog', { name: '사용자 등록' })).not.toBeInTheDocument()
  })

  it('creates a local POC profile without collecting an authentication password', async () => {
    const api = {
      listMembershipPage: vi.fn(() => Promise.resolve({ items: [], nextCursor: null, limit: 25 })),
      provisionIdentityUser: vi.fn(() => Promise.resolve({ subject_id: 'poc-user' })),
    }
    renderUsers(
      api,
      ['MEMBERSHIP_ACCESS_READ', 'IDENTITY_USER_PROVISION'],
      vi.fn(),
      ['POC_OPEN_ACCESS_V1'],
    )

    fireEvent.click(await screen.findByRole('button', { name: '사용자 등록' }))
    expect(await screen.findByText(/Keycloak 계정과 비밀번호는 생성하지 않습니다/)).toBeInTheDocument()
    expect(screen.queryByLabelText('임시 비밀번호')).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('사용자명'), { target: { value: 'poc.viewer' } })
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'poc.viewer@example.test' } })
    fireEvent.change(screen.getByLabelText('이름'), { target: { value: 'POC' } })
    fireEvent.change(screen.getByLabelText('성'), { target: { value: 'Viewer' } })
    fireEvent.change(screen.getByLabelText('업무 역할'), { target: { value: 'viewer' } })
    fireEvent.click(screen.getAllByRole('button', { name: '사용자 등록' }).at(-1)!)

    await waitFor(() => expect(api.provisionIdentityUser).toHaveBeenCalledWith({
      username: 'poc.viewer', email: 'poc.viewer@example.test', first_name: 'POC', last_name: 'Viewer',
      department_id: null, job_function: 'viewer', role_id: null, temporary_password: '',
    }, 'stable-key'))
  })

  it('opens the profile modal and assigns a server-managed profile tier', async () => {
    const target = member()
    const api = {
      listMembershipPage: vi.fn(() => Promise.resolve({ items: [target], nextCursor: null, limit: 25 })),
      getMembershipAccess: vi.fn(() => Promise.resolve(membershipAccess(target))),
      getProfileRolePolicy: vi.fn(() => Promise.resolve(profileRolePolicy)),
      listMembershipChangeRequestActivity: vi.fn(() => Promise.resolve({ items: [], nextCursor: null, limit: 25 })),
      listMembershipOwnedTables: vi.fn(() => Promise.resolve({ items: [], nextCursor: null, limit: 25 })),
      updateProfileRole: vi.fn(() => Promise.resolve({
        subject_id: target.subject_id,
        tier: 'MANAGER',
        membership_version: 4,
        assignment_version: 2,
        binding_version: null,
      })),
    }
    let pending: PendingAdminMutation | undefined
    renderUsers(api, ['MEMBERSHIP_ACCESS_READ', 'MEMBERSHIP_ACCESS_UPDATE'], (next) => { pending = next })

    fireEvent.click(await screen.findByText('Engineer'))
    expect(await screen.findByRole('dialog', { name: '사용자 프로필 수정' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: '데이터·화면 접근' }))
    const roleSelect = await screen.findByLabelText('사용자 프로필 권한')
    await waitFor(() => expect(roleSelect).toHaveValue('ENGINEER_STEWARD'))
    fireEvent.change(roleSelect, { target: { value: 'MANAGER' } })
    fireEvent.change(screen.getByLabelText('변경 사유'), { target: { value: '관리 책임 범위 확대' } })
    fireEvent.click(screen.getByRole('button', { name: '프로필 권한 저장' }))
    if (!pending) throw new Error('Profile-role confirmation was not requested')
    await act(async () => { await pending?.execute() })
    expect(api.updateProfileRole).toHaveBeenCalledWith(
      target.subject_id,
      'MANAGER',
      0,
      '관리 책임 범위 확대',
      '"3"',
      'stable-key',
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
      getMembershipAccess: vi.fn(() => Promise.resolve(membershipAccess(target))),
      getProfileRolePolicy: vi.fn(() => Promise.resolve(profileRolePolicy)),
      getIdentityUserProfile: vi.fn(() => Promise.resolve({
        subject_id: target.subject_id, username: 'engineer', display_name: 'Engineer',
        email: 'engineer@example.test', first_name: 'Data', last_name: 'Engineer',
        department_id: null, job_function: 'ENGINEER', membership_version: 3,
        provider_enabled: true, email_verified: true, required_actions: [], etag: '"3"',
      })),
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
