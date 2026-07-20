import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { AdminReadContext } from '../../api/types'
import { getAdminMessages } from './messages'
import { RetentionGovernanceAdmin } from './RetentionGovernanceAdmin'

describe('RetentionGovernanceAdmin', () => {
  it('explains the provider-neutral lifecycle and switches the three distinct workflows', async () => {
    const api = {
      listRetentionPolicies: vi.fn(() => Promise.resolve([])),
      listLegalHolds: vi.fn(() => Promise.resolve([])),
      listErasureRequests: vi.fn(() => Promise.resolve([])),
    }
    const context: AdminReadContext = {
      subject_id: 'administrator', workspace_id: 'workspace-one', display_name: 'Administrator',
      authentication_assurance: 'PASSWORD', fallback_enabled: false,
      allowed_operations: ['RETENTION_POLICY_READ', 'LEGAL_HOLD_READ', 'ERASURE_READ'],
      action_vocabulary: [],
    }

    render(<RetentionGovernanceAdmin
      api={api as never} context={context} messages={getAdminMessages('ko')}
      requestConfirmation={vi.fn()} keyFor={() => 'key'} clearKey={vi.fn()}
      reportError={vi.fn()} onStepUp={vi.fn(() => Promise.resolve())}
      onPasswordReauth={vi.fn(() => Promise.resolve())} onEnroll={vi.fn(() => Promise.resolve())}
    />)

    expect(screen.getByRole('heading', { name: '보존·예외보존·파기 Workflow' })).toBeInTheDocument()
    expect(screen.getByText(/대상 데이터 저장소를 PostgreSQL로 제한한다는 뜻이 아닙니다/)).toBeInTheDocument()
    expect(screen.getByText(/현재 자동 삭제와 파티션 제거는 항상/)).toHaveTextContent('DISABLED_NOT_READY')
    fireEvent.click(screen.getByRole('tab', { name: 'Legal Hold' }))
    expect(await screen.findByRole('heading', { name: 'Legal Hold 이력' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: '파기 검토' }))
    expect(await screen.findByRole('heading', { name: '파기 검토 이력' })).toBeInTheDocument()
  })
})
