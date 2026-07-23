import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type {
  AccessRole,
  AdminReadContext,
  WorkspaceMembershipSummary,
} from '../../api/types'
import { MembershipAccessAdmin } from './MembershipAdmin'
import { getAdminMessages } from './messages'

describe('MembershipAccessAdmin identity provisioning', () => {
  it('creates an identity and Workspace membership through the governed API', async () => {
    const role: AccessRole = {
      id: '00000000-0000-4000-8000-000000000301', role_key: 'catalog-reader',
      name: 'Catalog Reader', description: 'Read-only catalog access', clearance: 'INTERNAL',
      groups: ['catalog-users'], allowed_actions: ['catalog.read'], denied_actions: [],
      allowed_system_ids: [], allowed_domain_ids: [], data_access_rules: [],
      active: true, assigned_count: 0,
      version: 1, created_at: '2026-07-20T00:00:00Z', updated_at: '2026-07-20T00:00:00Z',
    }
    const api = {
      listMembershipPage: vi.fn(() => Promise.resolve({
        items: [], nextCursor: null, limit: 25,
      })),
      listAccessRolePage: vi.fn((params?: {
        query?: string
        status?: string
        limit?: number
        signal?: AbortSignal
      }) => {
        void params
        return Promise.resolve({ items: [role], nextCursor: null, limit: 25 })
      }),
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
    const keyFor = vi.fn<(intent: string) => string>(() => 'stable-identity-key')

    render(<MembershipAccessAdmin
      api={api as never} context={context} messages={getAdminMessages('ko')}
      requestConfirmation={vi.fn()} keyFor={keyFor} clearKey={clearKey}
      reportError={vi.fn()} onStepUp={vi.fn(() => Promise.resolve())}
      onPasswordReauth={vi.fn(() => Promise.resolve())} onEnroll={vi.fn(() => Promise.resolve())}
    />)

    fireEvent.click(await screen.findByRole('button', { name: '신규 사용자 등록' }))
    expect(await screen.findByRole('dialog', { name: '신규 사용자 등록' })).toBeInTheDocument()
    await waitFor(() => expect(api.listAccessRolePage).toHaveBeenCalled())
    expect(api.listAccessRolePage.mock.calls[0]?.[0]).toMatchObject({
      query: undefined, status: 'ACTIVE', limit: 25,
    })
    expect(api.listAccessRolePage.mock.calls[0]?.[0]?.signal).toBeInstanceOf(AbortSignal)
    fireEvent.change(screen.getByLabelText('Role 검색'), {
      target: { value: 'catalog-reader' },
    })
    await waitFor(() => expect(api.listAccessRolePage).toHaveBeenCalledTimes(2))
    expect(api.listAccessRolePage.mock.calls.at(-1)?.[0]).toMatchObject({
      query: 'catalog-reader', status: 'ACTIVE', limit: 25,
    })
    expect(api.listAccessRolePage.mock.calls.at(-1)?.[0]?.signal).toBeInstanceOf(AbortSignal)
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
    const intent = keyFor.mock.calls[0]?.[0]
    expect(intent).toMatch(/^identity-user:[0-9a-f]{64}$/)
    expect(intent).not.toContain('Temporary-Only-42!')
    expect(clearKey).toHaveBeenCalledWith(intent)
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('never combines a stale access response with a newly selected user', async () => {
    const alpha = member('00000000-0000-4000-8000-000000000501', 'Alpha')
    const beta = member('00000000-0000-4000-8000-000000000502', 'Beta')
    const alphaResponse = deferred<unknown>()
    const betaResponse = deferred<unknown>()
    const api = {
      listMembershipPage: vi.fn(() => Promise.resolve({
        items: [alpha, beta], nextCursor: null, limit: 25,
      })),
      getMembershipAccess: vi.fn((subjectId: string) => (
        subjectId === alpha.subject_id ? alphaResponse.promise : betaResponse.promise
      )),
    }
    const context: AdminReadContext = {
      subject_id: '00000000-0000-4000-8000-000000000111',
      workspace_id: '00000000-0000-4000-8000-000000000100',
      display_name: 'Administrator',
      authentication_assurance: 'HARDWARE_WEBAUTHN',
      fallback_enabled: false,
      allowed_operations: ['MEMBERSHIP_ACCESS_READ', 'MEMBERSHIP_ACCESS_UPDATE'],
      action_vocabulary: ['catalog.read'],
    }

    render(<MembershipAccessAdmin
      api={api as never} context={context} messages={getAdminMessages('ko')}
      requestConfirmation={vi.fn()} keyFor={() => 'stable-key'} clearKey={vi.fn()}
      reportError={vi.fn()} onStepUp={vi.fn(() => Promise.resolve())}
      onPasswordReauth={vi.fn(() => Promise.resolve())} onEnroll={vi.fn(() => Promise.resolve())}
    />)

    expect(await screen.findByText('Alpha')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Beta'))
    await act(async () => {
      betaResponse.resolve(accessResponse(beta, 'CONFIDENTIAL', ['beta-users']))
      await betaResponse.promise
    })
    expect(await screen.findByDisplayValue('beta-users')).toBeInTheDocument()

    await act(async () => {
      alphaResponse.resolve(accessResponse(alpha, 'PUBLIC', ['alpha-users']))
      await alphaResponse.promise
    })

    expect(screen.getByDisplayValue('beta-users')).toBeInTheDocument()
    expect(screen.queryByDisplayValue('alpha-users')).not.toBeInTheDocument()
  })
})

function member(subjectId: string, displayName: string): WorkspaceMembershipSummary {
  return {
    subject_id: subjectId, display_name: displayName, email: `${displayName.toLowerCase()}@example.test`,
    last_login_at: null, last_login_ip: null, owned_table_count: 0, change_request_count: 0,
    subject_active: true, membership_active: true, department_id: null, job_function: 'ANALYST',
    clearance: 'INTERNAL', membership_version: 3, access_expires_at: null,
    renewal_eligible_at: null, access_expired: false, pending_renewal_request_id: null,
    renewal_request_eligible: false,
  }
}

function accessResponse(
  target: WorkspaceMembershipSummary,
  clearance: 'PUBLIC' | 'CONFIDENTIAL',
  groups: string[],
) {
  return {
    subject_id: target.subject_id,
    display_name: target.display_name,
    subject_active: true,
    department_id: null,
    job_function: target.job_function,
    membership_version: target.membership_version,
    etag: `"${target.membership_version}"`,
    access: {
      active: true, clearance, groups, allowed_actions: ['catalog.read'], denied_actions: [],
      allowed_system_ids: [], allowed_domain_ids: [],
    },
    role_assignment: {
      status: 'MANUAL', role_id: null, role_version: null, assignment_version: null,
      membership_version: null, access_payload_hash: null, assigned_by: null, updated_at: null,
      legacy_markers: [],
    },
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((next) => { resolve = next })
  return { promise, resolve }
}
