import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AdminReadContext } from '../../api/types'
import { AccountAccessAdmin } from './AccountAccessAdmin'
import { getAdminMessages } from './messages'

afterEach(() => window.history.replaceState({}, '', '/'))

function renderAccounts(context: AdminReadContext, api: object) {
  return render(<AccountAccessAdmin
    api={api as never} context={context} messages={getAdminMessages('ko')}
    requestConfirmation={vi.fn()} keyFor={() => 'key'} clearKey={vi.fn()} reportError={vi.fn()}
    onStepUp={vi.fn(() => Promise.resolve())}
    onPasswordReauth={vi.fn(() => Promise.resolve())}
    onEnroll={vi.fn(() => Promise.resolve())}
  />)
}

describe('AccountAccessAdmin authorization-bound navigation', () => {
  it('places the user table at the top of USERS and removes standalone Role and renewal panels', async () => {
    const context: AdminReadContext = {
      subject_id: 'administrator', workspace_id: 'workspace-one', display_name: 'Administrator',
      authentication_assurance: 'PASSWORD', fallback_enabled: false,
      allowed_operations: ['MEMBERSHIP_ACCESS_READ'], action_vocabulary: [],
    }
    renderAccounts(context, {
      listMembershipPage: vi.fn(() => Promise.resolve({ items: [], nextCursor: null, limit: 25 })),
    })

    expect(await screen.findByRole('table', { name: '워크스페이스 사용자 목록' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '계정/권한 요약' })).toHaveClass(
      'admin-access-summary',
    )
    expect(screen.getByRole('tablist', { name: '계정/권한 관리 영역' })).toHaveClass(
      'admin-access-tabs',
    )
    expect(screen.getByRole('button', { name: 'Role 관리' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Role 정의 및 사용자 할당' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '계정 갱신 승인' })).not.toBeInTheDocument()
  })

  it('opens Role management and account renewals only in their respective modals', async () => {
    const context: AdminReadContext = {
      subject_id: 'administrator', workspace_id: 'workspace-one', display_name: 'Administrator',
      authentication_assurance: 'PASSWORD', fallback_enabled: false,
      allowed_operations: ['MEMBERSHIP_ACCESS_READ', 'MEMBERSHIP_RENEWAL_READ'], action_vocabulary: [],
    }
    renderAccounts(context, {
      listMembershipPage: vi.fn(() => Promise.resolve({ items: [], nextCursor: null, limit: 25 })),
      listAccessRolePage: vi.fn(() => Promise.resolve({ items: [], nextCursor: null, limit: 25 })),
      getAccessRoleCapabilities: vi.fn(() => Promise.resolve({
        contract_version: 'ACCESS_ROLE_CAPABILITY_CATALOG_V1',
        action_count: 69,
        human_action_count: 64,
        service_action_count: 5,
        services: [],
      })),
      listMembershipRenewalPage: vi.fn(() => Promise.resolve({ items: [], nextCursor: null, limit: 25 })),
    })

    await screen.findByRole('table', { name: '워크스페이스 사용자 목록' })
    fireEvent.click(screen.getByRole('button', { name: 'Role 관리' }))
    expect(await screen.findByRole('dialog', { name: 'Role 관리' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Role 관리 닫기' }))
    fireEvent.click(screen.getByRole('button', { name: '계정 갱신' }))
    expect(await screen.findByRole('dialog', { name: '계정 갱신' })).toBeInTheDocument()
    expect(screen.getByRole('table', { name: '멤버십 갱신 요청' })).toBeInTheDocument()
  })
})
