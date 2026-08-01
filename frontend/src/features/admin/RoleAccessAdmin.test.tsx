import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type {
  AccessRole,
  AccessRoleCapabilityCatalog,
  AdminReadContext,
} from '../../api/types'
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

const capabilityCatalog: AccessRoleCapabilityCatalog = {
  contract_version: 'ACCESS_ROLE_CAPABILITY_CATALOG_V1',
  action_count: 3,
  human_action_count: 2,
  service_action_count: 1,
  services: [
    {
      service_key: 'catalog',
      label: '카탈로그',
      description: '카탈로그 조회 capability',
      actions: [{
        action: 'catalog.read',
        label: '카탈로그 조회',
        description: '권한 범위 내 자산 상세와 메타데이터를 조회합니다.',
        actor_kind: 'HUMAN',
        assignability: 'HUMAN_ROLE',
        default_admin: true,
        assurance: 'SESSION',
        reason_policy: 'NOT_REQUIRED',
        self_approval_policy: 'NOT_APPLICABLE',
        self_approval_binding: 'NOT_APPLICABLE',
        risk: 'STANDARD',
      }],
    },
    {
      service_key: 'admin',
      label: '관리',
      description: '관리 capability',
      actions: [{
        action: 'admin.manage',
        label: 'Workspace 관리',
        description: '권한 있는 human Admin이 보안 및 관리 control-plane을 운영합니다.',
        actor_kind: 'HUMAN',
        assignability: 'HUMAN_ROLE',
        default_admin: true,
        assurance: 'FRESH_PHISHING_RESISTANT',
        reason_policy: 'REQUIRED',
        self_approval_policy: 'NOT_APPLICABLE',
        self_approval_binding: 'NOT_APPLICABLE',
        risk: 'HIGH',
      }],
    },
    {
      service_key: 'quality',
      label: '품질관리',
      description: '품질 worker capability',
      actions: [{
        action: 'quality.execute',
        label: '품질 Run 실행',
        description: '전용 quality worker가 고정 GX 계약을 실행합니다.',
        actor_kind: 'SERVICE_PRINCIPAL',
        assignability: 'SERVICE_PRINCIPAL_ONLY',
        default_admin: false,
        assurance: 'NOT_APPLICABLE',
        reason_policy: 'NOT_REQUIRED',
        self_approval_policy: 'NOT_APPLICABLE',
        self_approval_binding: 'NOT_APPLICABLE',
        risk: 'SERVICE_PRIVILEGED',
      }],
    },
  ],
}

function withCapabilityCatalog(api: object) {
  return {
    getAccessRoleCapabilities: vi.fn(() => Promise.resolve(capabilityCatalog)),
    ...api,
  }
}

function renderDialog(api: object, context?: AdminReadContext) {
  return render(<RoleManagementDialog
    open
    onRequestClose={vi.fn()}
    api={withCapabilityCatalog(api) as never}
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
      open onRequestClose={vi.fn()} api={withCapabilityCatalog(api) as never} context={context} messages={getAdminMessages('ko')}
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
      open onRequestClose={vi.fn()} api={withCapabilityCatalog(api) as never}
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

  it('uses the server capability catalog and keeps service-only Actions non-assignable', async () => {
    const api = {
      listAccessRolePage: vi.fn(() => Promise.resolve({ items: [], nextCursor: null, limit: 25 })),
    }
    const context: AdminReadContext = {
      subject_id: 'admin', workspace_id: 'workspace', display_name: 'Administrator',
      authentication_assurance: 'HARDWARE_WEBAUTHN', fallback_enabled: false,
      allowed_operations: ['MEMBERSHIP_ACCESS_UPDATE'], action_vocabulary: [],
    }
    renderDialog(api, context)

    fireEvent.click(await screen.findByRole('button', { name: '+ Role 추가' }))
    fireEvent.click(screen.getByText('추가 정책 조건'))

    expect(await screen.findByText('Workspace 관리')).toBeInTheDocument()
    expect(screen.getByText('품질관리')).toBeInTheDocument()
    expect(screen.getByText(/현재 승인 동작을 활성화하지 않습니다/)).toBeInTheDocument()
    expect(screen.getByLabelText('Role admin.manage')).toBeEnabled()
    expect(screen.getByLabelText('Role quality.execute')).toBeDisabled()
    expect(screen.getByText(/service principal 전용/)).toBeInTheDocument()
  })

  it('blocks confirmation and mutation when the server capability catalog fails to load', async () => {
    const catalogReader = role(
      '00000000-0000-4000-8000-000000000301', 'catalog-reader', 'Catalog Reader',
    )
    const api = {
      getAccessRoleCapabilities: vi.fn(() => Promise.reject(new Error('catalog unavailable'))),
      listAccessRolePage: vi.fn(() => Promise.resolve({
        items: [catalogReader], nextCursor: null, limit: 25,
      })),
      updateAccessRole: vi.fn(),
    }
    const requestConfirmation = vi.fn()
    const reportError = vi.fn()
    const context: AdminReadContext = {
      subject_id: 'admin', workspace_id: 'workspace', display_name: 'Administrator',
      authentication_assurance: 'HARDWARE_WEBAUTHN', fallback_enabled: false,
      allowed_operations: ['MEMBERSHIP_ACCESS_UPDATE'], action_vocabulary: ['catalog.read'],
    }
    render(<RoleManagementDialog
      open onRequestClose={vi.fn()} api={api as never} context={context}
      messages={getAdminMessages('ko')} requestConfirmation={requestConfirmation}
      keyFor={() => 'stable-role-key'} clearKey={vi.fn()} reportError={reportError}
      onStepUp={vi.fn(() => Promise.resolve())}
      onPasswordReauth={vi.fn(() => Promise.resolve())}
      onEnroll={vi.fn(() => Promise.resolve())}
    />)

    fireEvent.click(await screen.findByText('Catalog Reader'))
    fireEvent.click(screen.getByText('추가 정책 조건'))
    expect(await screen.findByRole('alert')).toHaveTextContent('Role 저장을 차단했습니다')
    expect(screen.getByRole('button', { name: '저장' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '저장' }))

    expect(reportError).toHaveBeenCalledTimes(1)
    expect(requestConfirmation).not.toHaveBeenCalled()
    expect(api.updateAccessRole).not.toHaveBeenCalled()
  })

  it('preserves existing Actions when a late capability response enables saving', async () => {
    const catalogReader = {
      ...role('00000000-0000-4000-8000-000000000301', 'catalog-reader', 'Catalog Reader'),
      allowed_actions: ['catalog.read', 'change.edit'],
    }
    let resolveCatalog: (catalog: AccessRoleCapabilityCatalog) => void = () => undefined
    const pendingCatalog = new Promise<AccessRoleCapabilityCatalog>((resolve) => {
      resolveCatalog = resolve
    })
    const api = {
      getAccessRoleCapabilities: vi.fn(() => pendingCatalog),
      listAccessRolePage: vi.fn(() => Promise.resolve({
        items: [catalogReader], nextCursor: null, limit: 25,
      })),
      updateAccessRole: vi.fn(() => Promise.resolve(catalogReader)),
    }
    const requestConfirmation = vi.fn()
    const context: AdminReadContext = {
      subject_id: 'admin', workspace_id: 'workspace', display_name: 'Administrator',
      authentication_assurance: 'HARDWARE_WEBAUTHN', fallback_enabled: false,
      allowed_operations: ['MEMBERSHIP_ACCESS_UPDATE'], action_vocabulary: [],
    }
    render(<RoleManagementDialog
      open onRequestClose={vi.fn()} api={api as never} context={context}
      messages={getAdminMessages('ko')} requestConfirmation={requestConfirmation}
      keyFor={() => 'stable-role-key'} clearKey={vi.fn()} reportError={vi.fn()}
      onStepUp={vi.fn(() => Promise.resolve())}
      onPasswordReauth={vi.fn(() => Promise.resolve())}
      onEnroll={vi.fn(() => Promise.resolve())}
    />)

    fireEvent.click(await screen.findByText('Catalog Reader'))
    expect(screen.getByRole('button', { name: '저장' })).toBeDisabled()

    resolveCatalog(capabilityCatalog)
    await waitFor(() => expect(screen.getByRole('button', { name: '저장' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: '저장' }))
    const confirmation = requestConfirmation.mock.calls[0]?.[0] as { execute: () => Promise<void> }
    await confirmation.execute()

    expect(api.updateAccessRole).toHaveBeenCalledWith(
      catalogReader,
      expect.objectContaining({
        allowed_actions: ['catalog.read', 'change.edit'],
        denied_actions: [],
      }),
    )
  })
})
