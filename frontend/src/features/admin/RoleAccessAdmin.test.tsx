import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { AccessRole, AdminReadContext } from '../../api/types'
import { getAdminMessages } from './messages'
import { RoleManagementDialog } from './RoleAccessAdmin'

function role(id: string, key: string, name: string): AccessRole {
  return {
    id, role_key: key, name, description: `${name} description`, clearance: 'INTERNAL',
    groups: ['catalog-users'], allowed_actions: ['catalog.read'], denied_actions: [],
    allowed_system_ids: [], allowed_domain_ids: [],
    data_access_rules: [{
      classification: 'PUBLIC', access_level: 'FULL_ACCESS', partial_treatment: null,
      allowed_residency_regions: ['KR'], allowed_processing_purposes: ['METADATA_READ'],
    }],
    active: true, assigned_count: 0, version: 1,
    created_at: '2026-07-20T00:00:00Z', updated_at: '2026-07-20T00:00:00Z',
  }
}

function renderDialog(api: object, context?: AdminReadContext) {
  return render(<RoleManagementDialog
    open
    onRequestClose={vi.fn()}
    api={api as never}
    context={context}
    messages={getAdminMessages('ko')}
    requestConfirmation={vi.fn()}
    keyFor={() => 'stable-role-key'}
    clearKey={vi.fn()}
    reportError={vi.fn()}
    onStepUp={vi.fn(() => Promise.resolve())}
    onPasswordReauth={vi.fn(() => Promise.resolve())}
    onEnroll={vi.fn(() => Promise.resolve())}
  />)
}

describe('RoleManagementDialog', () => {
  it('keeps Role definitions on bounded server cursor pages in the modal', async () => {
    const first = role('00000000-0000-4000-8000-000000000313', 'first-role', 'First Role')
    const second = role('00000000-0000-4000-8000-000000000314', 'second-role', 'Second Role')
    const api = {
      listAccessRolePage: vi.fn()
        .mockResolvedValueOnce({ items: [first], nextCursor: 'next-role', limit: 25 })
        .mockResolvedValueOnce({ items: [second], nextCursor: null, limit: 25 }),
    }

    renderDialog(api)

    expect(await screen.findByText('First Role')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '다음' }))
    expect(await screen.findByText('Second Role')).toBeInTheDocument()
    expect(api.listAccessRolePage).toHaveBeenLastCalledWith(expect.objectContaining({
      cursor: 'next-role', limit: 25,
    }))
    expect(screen.queryByText('First Role')).not.toBeInTheDocument()
  })

  it('renders the four-class data-access grid and uses governed Role writes', async () => {
    const catalogReader = role(
      '00000000-0000-4000-8000-000000000301', 'catalog-reader', 'Catalog Reader',
    )
    const api = {
      listAccessRolePage: vi.fn(() => Promise.resolve({ items: [catalogReader], nextCursor: null, limit: 25 })),
      updateAccessRole: vi.fn(() => Promise.resolve(catalogReader)),
    }
    const context: AdminReadContext = {
      subject_id: '00000000-0000-4000-8000-000000000111', workspace_id: 'workspace-one',
      display_name: 'Administrator', authentication_assurance: 'HARDWARE_WEBAUTHN',
      fallback_enabled: false, allowed_operations: ['MEMBERSHIP_ACCESS_UPDATE'],
      action_vocabulary: ['catalog.read'],
    }
    const requestConfirmation = vi.fn()
    render(<RoleManagementDialog
      open onRequestClose={vi.fn()} api={api as never} context={context} messages={getAdminMessages('ko')}
      requestConfirmation={requestConfirmation} keyFor={() => 'stable-role-key'} clearKey={vi.fn()}
      reportError={vi.fn()} onStepUp={vi.fn(() => Promise.resolve())}
      onPasswordReauth={vi.fn(() => Promise.resolve())} onEnroll={vi.fn(() => Promise.resolve())}
    />)

    fireEvent.click(await screen.findByText('Catalog Reader'))
    expect(screen.getByRole('table', { name: 'Role 목록' })).toBeInTheDocument()
    expect(screen.getByRole('table', { name: '데이터 접근 수준' }).querySelectorAll('select')).toHaveLength(4)
    expect(screen.getByLabelText('PUBLIC 접근 수준')).toHaveValue('FULL_ACCESS')
    expect(screen.getByLabelText('INTERNAL 접근 수준')).toHaveValue('MISSING')
    fireEvent.change(screen.getByLabelText('INTERNAL 접근 수준'), { target: { value: 'NO_ACCESS' } })
    expect(screen.getAllByRole('button', { name: '저장' })).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: '저장' }))
    await waitFor(() => expect(requestConfirmation).toHaveBeenCalled())
  })

  it('discards only the local Role draft when the administrator cancels', async () => {
    const catalogReader = role(
      '00000000-0000-4000-8000-000000000301', 'catalog-reader', 'Catalog Reader',
    )
    const api = {
      listAccessRolePage: vi.fn(() => Promise.resolve({
        items: [catalogReader], nextCursor: null, limit: 25,
      })),
    }
    const context: AdminReadContext = {
      subject_id: 'admin', workspace_id: 'workspace', display_name: 'Administrator',
      authentication_assurance: 'PASSWORD', fallback_enabled: false,
      allowed_operations: ['MEMBERSHIP_ACCESS_UPDATE'], action_vocabulary: [],
    }
    renderDialog(api, context)

    expect(await screen.findByText('Catalog Reader')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '+ Role 추가' }))
    fireEvent.change(screen.getByLabelText('Role Key'), { target: { value: 'draft-role' } })
    fireEvent.change(screen.getByLabelText('Role 이름'), { target: { value: 'Draft Role' } })
    fireEvent.click(screen.getByRole('button', { name: '취소' }))

    expect(screen.queryByLabelText('Role Key')).not.toBeInTheDocument()
    expect(screen.getByText('Catalog Reader')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '+ Role 추가' }))
    expect(screen.getByLabelText('Role Key')).toHaveValue('')
    expect(screen.getByLabelText('Role 이름')).toHaveValue('')
  })

  it('makes no Role mutation, confirmation, or step-up call without the capability', async () => {
    const catalogReader = role(
      '00000000-0000-4000-8000-000000000301', 'catalog-reader', 'Catalog Reader',
    )
    const api = {
      listAccessRolePage: vi.fn(() => Promise.resolve({
        items: [catalogReader], nextCursor: null, limit: 25,
      })),
      createAccessRole: vi.fn(),
      updateAccessRole: vi.fn(),
      deactivateAccessRole: vi.fn(),
    }
    const requestConfirmation = vi.fn()
    const onStepUp = vi.fn(() => Promise.resolve())
    render(<RoleManagementDialog
      open onRequestClose={vi.fn()} api={api as never}
      context={{
        subject_id: 'admin', workspace_id: 'workspace', display_name: 'Administrator',
        authentication_assurance: 'PASSWORD', fallback_enabled: false,
        allowed_operations: ['MEMBERSHIP_ACCESS_READ'], action_vocabulary: [],
      }}
      messages={getAdminMessages('ko')}
      requestConfirmation={requestConfirmation}
      keyFor={() => 'stable-role-key'}
      clearKey={vi.fn()}
      reportError={vi.fn()}
      onStepUp={onStepUp}
      onPasswordReauth={vi.fn(() => Promise.resolve())}
      onEnroll={vi.fn(() => Promise.resolve())}
    />)

    const add = await screen.findByRole('button', { name: '+ Role 추가' })
    expect(add).toBeDisabled()
    fireEvent.click(add)
    fireEvent.click(screen.getByText('Catalog Reader'))
    expect(screen.getAllByRole('button', { name: '저장' })).toHaveLength(1)
    expect(screen.getByRole('button', { name: '저장' })).toBeDisabled()

    expect(api.createAccessRole).not.toHaveBeenCalled()
    expect(api.updateAccessRole).not.toHaveBeenCalled()
    expect(api.deactivateAccessRole).not.toHaveBeenCalled()
    expect(requestConfirmation).not.toHaveBeenCalled()
    expect(onStepUp).not.toHaveBeenCalled()
  })
})
