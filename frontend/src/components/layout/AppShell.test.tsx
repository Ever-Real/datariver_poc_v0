import { useState } from 'react'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AdminReadContext } from '../../api/types'
import type { ApiClient } from '../../api/client'
import { allowedAdminSections } from '../../features/admin/adminSections'
import { CatalogPage } from '../../features/catalog/CatalogPage'
import { AppShell } from './AppShell'
import { GlobalCatalogSearch } from './GlobalCatalogSearch'
import { PageTitle } from './PageTitle'
import { ProfileMenu } from './ProfileMenu'
import { TopNavigation } from './TopNavigation'

afterEach(() => vi.unstubAllGlobals())

function WorkspaceScopedInput() {
  const [value, setValue] = useState('')
  return <input aria-label="Workspace scoped value" value={value} onChange={(event) => setValue(event.target.value)} />
}

describe('application shell contracts', () => {
  it('enforces the two-character search floor without catalog preload', () => {
    const onSearch = vi.fn()
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    render(<GlobalCatalogSearch onSearch={onSearch} />)

    const input = screen.getByRole('textbox', { name: '카탈로그 검색' })
    fireEvent.change(input, { target: { value: ' a ' } })
    fireEvent.submit(screen.getByRole('search', { name: '전역 카탈로그 검색' }))
    expect(screen.getByRole('alert')).toHaveTextContent('2자 이상')
    expect(onSearch).not.toHaveBeenCalled()

    fireEvent.change(input, { target: { value: '  wafer  ' } })
    fireEvent.submit(screen.getByRole('search', { name: '전역 카탈로그 검색' }))
    expect(onSearch).toHaveBeenCalledWith('wafer')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('updates and queries server catalog contracts without catalog preload', async () => {
    const request = vi.fn((path: string) => {
      if (path.startsWith('/catalog/tree/')) return Promise.resolve({ items: [], page: { limit: 100 }, meta: { projection_version: 1, policy_version: 'test' } })
      if (path.startsWith('/catalog/facets')) return Promise.resolve({ asset_types: [], platforms: [], classifications: [], meta: { projection_version: 1, policy_version: 'test' } })
      return Promise.resolve({ items: [], page: { limit: 50 }, meta: { projection_version: 1, policy_version: 'test' }, match_mode: 'ALL' })
    })
    const client = { request } as unknown as ApiClient
    const view = render(<CatalogPage client={client} initialQuery="wafer" />)
    expect(screen.getByRole('textbox', { name: /데이터셋 이름이나 설명 검색/ })).toHaveValue('wafer')
    view.rerender(<CatalogPage client={client} initialQuery="yield" />)
    expect(screen.getByRole('textbox', { name: /데이터셋 이름이나 설명 검색/ })).toHaveValue('yield')
    await waitFor(() => expect(request).toHaveBeenCalledWith(expect.stringContaining('/catalog/assets?q=yield&limit=50'), expect.anything()))
    expect(request.mock.calls.some(([path]) => String(path).includes('10000'))).toBe(false)
  })

  it('remounts workspace-scoped feature state on a committed workspace switch', () => {
    const common = {
      page: 'dashboard' as const,
      displayName: 'User',
      adminMenuItems: [],
      externalSystemLinks: [],
      onNavigate: vi.fn(),
      onNavigateAdmin: vi.fn(),
      onSearch: vi.fn(),
      onWorkspaceChange: vi.fn(),
      onEnrollSecurityKey: vi.fn(),
      onSignOut: vi.fn(),
      onClearNotice: vi.fn(),
    }
    const view = render(<AppShell {...common} workspace="workspace-a"><WorkspaceScopedInput /></AppShell>)
    fireEvent.change(screen.getByRole('textbox', { name: 'Workspace scoped value' }), { target: { value: 'secret-a' } })
    expect(screen.getByRole('textbox', { name: 'Workspace scoped value' })).toHaveValue('secret-a')
    view.rerender(<AppShell {...common} workspace="workspace-b"><WorkspaceScopedInput /></AppShell>)
    expect(screen.getByRole('textbox', { name: 'Workspace scoped value' })).toHaveValue('')
  })

  it('derives administration tabs from exact server operations', () => {
    const context: AdminReadContext = {
      subject_id: 'administrator', workspace_id: 'workspace', display_name: 'Administrator',
      authentication_assurance: 'HARDWARE_WEBAUTHN', fallback_enabled: false,
      allowed_operations: ['RETENTION_POLICY_READ', 'RETENTION_POLICY_MANAGE', 'ERASURE_REQUEST'],
      action_vocabulary: [],
    }
    expect(allowedAdminSections(context)).toEqual(['retention'])
  })

  it('collapses leaf administration capabilities into stable grouped sections', () => {
    const context: AdminReadContext = {
      subject_id: 'administrator', workspace_id: 'workspace', display_name: 'Administrator',
      authentication_assurance: 'HARDWARE_WEBAUTHN', fallback_enabled: true,
      allowed_operations: [
        'MEMBERSHIP_ACCESS_READ', 'SYSTEM_CONFIGURATION_READ', 'CLASSIFICATION_POLICY_READ',
        'INFERENCE_PROVIDER_PROFILE_READ', 'RESTRICTED_SEARCH_GRANT_READ', 'FALLBACK_REQUEST_READ',
        'RETENTION_POLICY_READ', 'LEGAL_HOLD_READ', 'ERASURE_READ',
      ],
      action_vocabulary: [],
    }

    expect(allowedAdminSections(context)).toEqual([
      'memberships', 'systemSettings', 'retention',
    ])
  })

  it('shows administration only from the server-derived capability', () => {
    render(
      <ProfileMenu
        displayName="Administrator"
        workspace="workspace-one"
        deploymentTier="SINGLE_NODE_PILOT"
        adminMenuItems={[]}
        onAdmin={vi.fn()}
        onWorkspaceChange={vi.fn()}
        onEnrollSecurityKey={vi.fn()}
        onSignOut={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Administrator 사용자 메뉴' }))
    expect(screen.queryByText('Administration')).not.toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'WebAuthn 보안키 등록' })).toBeInTheDocument()
  })

  it('hides workspace switching and WebAuthn enrollment when platform controls disable them', () => {
    render(
      <ProfileMenu
        displayName="Administrator"
        workspace="workspace-one"
        workspaceSelectionEnabled={false}
        hardwareWebauthnEnabled={false}
        deploymentTier="SINGLE_NODE_PILOT"
        adminMenuItems={[]}
        onAdmin={vi.fn()}
        onWorkspaceChange={vi.fn()}
        onEnrollSecurityKey={vi.fn()}
        onSignOut={vi.fn()}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Administrator 사용자 메뉴' }))
    expect(screen.queryByRole('menuitem', { name: 'Workspace 전환' })).not.toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: 'WebAuthn 보안키 등록' })).not.toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: '나가기' })).toBeInTheDocument()
  })

  it('routes allowed administration and account actions explicitly', () => {
    const onAdmin = vi.fn()
    const onEnrollSecurityKey = vi.fn()
    const onSignOut = vi.fn()
    render(
      <ProfileMenu
        displayName="Administrator"
        workspace="workspace-one"
        deploymentTier="SINGLE_NODE_PILOT"
        adminMenuItems={[{ id: 'retention', label: '보존·파기 거버넌스' }]}
        onAdmin={onAdmin}
        onWorkspaceChange={vi.fn()}
        onEnrollSecurityKey={onEnrollSecurityKey}
        onSignOut={onSignOut}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Administrator 사용자 메뉴' }))
    fireEvent.click(screen.getByRole('menuitem', { name: '보존·파기 거버넌스' }))
    fireEvent.click(screen.getByRole('button', { name: 'Administrator 사용자 메뉴' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'WebAuthn 보안키 등록' }))
    fireEvent.click(screen.getByRole('button', { name: 'Administrator 사용자 메뉴' }))
    fireEvent.click(screen.getByRole('menuitem', { name: '나가기' }))
    expect(onAdmin).toHaveBeenCalledWith('retention')
    expect(onEnrollSecurityKey).toHaveBeenCalledOnce()
    expect(onSignOut).toHaveBeenCalledOnce()
  })

  it('renders the requested admin-only profile entries from server-derived sections', () => {
    const onAdmin = vi.fn()
    render(
      <ProfileMenu
        displayName="Administrator"
        workspace="workspace-one"
        deploymentTier="SINGLE_NODE_PILOT"
        adminMenuItems={[
          { id: 'memberships', label: '계정/권한' },
          { id: 'systemSettings', label: '시스템 설정' },
          { id: 'retention', label: '보존·파기 거버넌스' },
          { id: 'auditLogs', label: 'Audit/Log 조회' },
          { id: 'dictionary', label: '용어사전' },
        ]}
        onAdmin={onAdmin}
        onWorkspaceChange={vi.fn()}
        onEnrollSecurityKey={vi.fn()}
        onSignOut={vi.fn()}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Administrator 사용자 메뉴' }))
    expect(screen.getByRole('menuitem', { name: '계정/권한' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: '시스템 설정' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: '보존·파기 거버넌스' })).toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: /LLM Provider|Legal Hold|파기 검토/ })).not.toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'Audit/Log 조회' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('menuitem', { name: '용어사전' }))
    expect(onAdmin).toHaveBeenCalledWith('dictionary')
  })

  it('offers an explicit password reauthentication entry when the server requires it', () => {
    const onPasswordReauth = vi.fn()
    render(
      <ProfileMenu
        displayName="Administrator"
        workspace="workspace-one"
        deploymentTier="SINGLE_NODE_PILOT"
        adminMenuItems={[]}
        adminContextStatus="reauth_required"
        onAdmin={vi.fn()}
        onWorkspaceChange={vi.fn()}
        onPasswordReauth={onPasswordReauth}
        onEnrollSecurityKey={vi.fn()}
        onSignOut={vi.fn()}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Administrator 사용자 메뉴' }))
    expect(screen.getByText(/현재 Workspace에 대해 비밀번호 재인증/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('menuitem', { name: '관리자 재인증' }))
    expect(onPasswordReauth).toHaveBeenCalledOnce()
  })

  it('provides one accessible page heading, description and action area', () => {
    render(
      <PageTitle
        icon="SR"
        eyebrow="Catalog"
        title="데이터 검색"
        description="인가된 projection을 검색합니다."
        actions={<button type="button">새로고침</button>}
      />,
    )
    expect(screen.getByRole('heading', { level: 1, name: '데이터 검색' })).toBeInTheDocument()
    expect(screen.getByText('인가된 projection을 검색합니다.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '새로고침' })).toBeInTheDocument()
  })

  it('keeps administration out of the primary menu and marks the active page', () => {
    const onNavigate = vi.fn()
    const onWorkspaceChange = vi.fn()
    render(
      <TopNavigation
        page="catalog"
        workspace="workspace-one"
        deploymentTier="SINGLE_NODE_PILOT"
        displayName="User"
        adminMenuItems={[{ id: 'memberships', label: '계정/권한' }]}
        externalSystemLinks={[{ system_id: 'datahub', label: 'DataHub', url: 'https://datahub.example.com' }]}
        onNavigate={onNavigate}
        onNavigateAdmin={vi.fn()}
        onSearch={vi.fn()}
        onWorkspaceChange={onWorkspaceChange}
        onEnrollSecurityKey={vi.fn()}
        onSignOut={vi.fn()}
      />,
    )
    const navigation = screen.getByRole('navigation', { name: '주 메뉴' })
    expect(navigation).not.toHaveTextContent('관리자')
    expect(within(navigation).getByRole('button', { name: '검색' })).toHaveAttribute('aria-current', 'page')
    expect(within(navigation).getByRole('button', { name: '등록관리' })).toBeInTheDocument()
    expect(within(navigation).getByRole('button', { name: /품질관리.*Beta/ })).toBeInTheDocument()
    expect(within(navigation).getByRole('button', { name: '모니터링' })).toBeInTheDocument()
    expect(within(navigation).getByRole('button', { name: '거버넌스' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '변경관리' }))
    expect(onNavigate).toHaveBeenCalledWith('change-management')
    fireEvent.click(screen.getByRole('button', { name: 'User 사용자 메뉴' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Workspace 전환' }))
    const workspace = screen.getByRole('textbox', { name: 'Workspace ID' })
    fireEvent.change(workspace, { target: { value: ' workspace-two ' } })
    expect(onWorkspaceChange).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '적용' }))
    expect(onWorkspaceChange).toHaveBeenCalledWith('workspace-two')
    fireEvent.click(screen.getByRole('button', { name: 'User 사용자 메뉴' }))
    expect(screen.getByText(/Environment: Single-node Pilot/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'DataHub' })).toHaveAttribute('href', 'https://datahub.example.com')
    expect(screen.getByRole('link', { name: 'DataHub' })).toHaveAttribute('rel', 'noopener noreferrer')
  })
})
