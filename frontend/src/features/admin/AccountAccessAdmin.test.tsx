import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AdminReadContext } from '../../api/types'
import { AccountAccessAdmin } from './AccountAccessAdmin'
import { getAdminMessages } from './messages'

afterEach(() => window.history.replaceState({}, '', '/'))

describe('AccountAccessAdmin authorization-bound navigation', () => {
  it('falls back from an unauthorized renewal deep link to the user directory', async () => {
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
    const selected = screen.getByRole('tab', { name: '사용자' })
    expect(selected).toHaveAttribute('tabindex', '0')
    expect(selected).toHaveAttribute('aria-controls', 'admin-users-panel-directory')
    expect(screen.getByRole('tabpanel', { name: '사용자' })).toHaveAttribute(
      'id',
      'admin-users-panel-directory',
    )
  })
})
