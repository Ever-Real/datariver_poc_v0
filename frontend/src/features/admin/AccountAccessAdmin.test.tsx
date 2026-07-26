import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AdminReadContext } from '../../api/types'
import { AccountAccessAdmin } from './AccountAccessAdmin'
import { getAdminMessages } from './messages'

afterEach(() => window.history.replaceState({}, '', '/'))

describe('AccountAccessAdmin authorization-bound navigation', () => {
  it('ignores an unauthorized renewal deep link and keeps the unified user page bounded', async () => {
    window.history.replaceState(
      {},
      '',
      '/?page=admin&adminSection=memberships&adminView=users&adminDetail=renewals',
    )
    const context: AdminReadContext = {
      subject_id: 'administrator',
      workspace_id: 'workspace-one',
      display_name: 'Administrator',
      authentication_assurance: 'PASSWORD',
      fallback_enabled: false,
      allowed_operations: ['MEMBERSHIP_ACCESS_READ'],
      action_vocabulary: [],
    }
    const api = {
      listMembershipPage: vi.fn(() => Promise.resolve({
        items: [], nextCursor: null, limit: 25,
      })),
    }

    render(<AccountAccessAdmin
      api={api as never}
      context={context}
      messages={getAdminMessages('ko')}
      requestConfirmation={vi.fn()}
      keyFor={() => 'key'}
      clearKey={vi.fn()}
      reportError={vi.fn()}
      onStepUp={vi.fn(() => Promise.resolve())}
      onPasswordReauth={vi.fn(() => Promise.resolve())}
      onEnroll={vi.fn(() => Promise.resolve())}
    />)

    expect(await screen.findByRole('heading', { name: 'User 관리' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '계정 갱신 승인' })).not.toBeInTheDocument()
    expect(screen.queryByRole('tablist', { name: '사용자 권한 관리 방식' })).not.toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: '사용자 통합 관리 바로가기' })).toBeInTheDocument()
  })

  it('renders users, roles, and renewal approvals together without lower tabs', async () => {
    const context: AdminReadContext = {
      subject_id: 'administrator',
      workspace_id: 'workspace-one',
      display_name: 'Administrator',
      authentication_assurance: 'PASSWORD',
      fallback_enabled: false,
      allowed_operations: ['MEMBERSHIP_ACCESS_READ', 'MEMBERSHIP_RENEWAL_READ'],
      action_vocabulary: [],
    }
    const api = {
      listMembershipPage: vi.fn(() => Promise.resolve({ items: [], nextCursor: null, limit: 25 })),
      listAccessRolePage: vi.fn(() => Promise.resolve({ items: [], nextCursor: null, limit: 25 })),
      listSystemPage: vi.fn(() => Promise.resolve({ items: [], nextCursor: null, limit: 25 })),
      listMembershipRenewalPage: vi.fn(() => Promise.resolve({
        items: [], nextCursor: null, limit: 25,
      })),
    }

    render(<AccountAccessAdmin
      api={api as never}
      context={context}
      messages={getAdminMessages('ko')}
      requestConfirmation={vi.fn()}
      keyFor={() => 'key'}
      clearKey={vi.fn()}
      reportError={vi.fn()}
      onStepUp={vi.fn(() => Promise.resolve())}
      onPasswordReauth={vi.fn(() => Promise.resolve())}
      onEnroll={vi.fn(() => Promise.resolve())}
    />)

    expect(await screen.findByRole('heading', { name: 'User 관리' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Role 정의 및 사용자 할당' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '계정 갱신 승인' })).toBeInTheDocument()
    expect(screen.queryByRole('tablist', { name: '사용자 권한 관리 방식' })).not.toBeInTheDocument()
  })
})
