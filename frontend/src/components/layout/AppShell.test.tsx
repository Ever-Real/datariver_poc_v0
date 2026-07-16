import { useState } from 'react'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AdminReadContext } from '../../api/types'
import type { ApiClient } from '../../api/client'
import { allowedAdminSections } from '../../features/admin/AdminPage'
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

  it('updates the catalog form when another global query targets the current page', () => {
    const request = vi.fn()
    const client = { request } as unknown as ApiClient
    const view = render(<CatalogPage client={client} initialQuery="wafer" />)
    expect(screen.getByRole('textbox', { name: /데이터셋 이름이나 설명 검색/ })).toHaveValue('wafer')
    view.rerender(<CatalogPage client={client} initialQuery="yield" />)
    expect(screen.getByRole('textbox', { name: /데이터셋 이름이나 설명 검색/ })).toHaveValue('yield')
    expect(request).not.toHaveBeenCalled()
  })

  it('remounts workspace-scoped feature state on a committed workspace switch', () => {
    const common = {
      page: 'dashboard' as const,
      displayName: 'User',
      canAdminister: false,
      onNavigate: vi.fn(),
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

  it('shows administration only from the server-derived capability', () => {
    render(
      <ProfileMenu
        displayName="Administrator"
        canAdminister={false}
        onAdmin={vi.fn()}
        onEnrollSecurityKey={vi.fn()}
        onSignOut={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByText('Administrator'))
    expect(screen.queryByRole('button', { name: '관리자' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'USB 보안키 등록' })).toBeInTheDocument()
  })

  it('routes allowed administration and account actions explicitly', () => {
    const onAdmin = vi.fn()
    const onEnrollSecurityKey = vi.fn()
    const onSignOut = vi.fn()
    render(
      <ProfileMenu
        displayName="Administrator"
        canAdminister
        onAdmin={onAdmin}
        onEnrollSecurityKey={onEnrollSecurityKey}
        onSignOut={onSignOut}
      />,
    )
    fireEvent.click(screen.getByText('Administrator'))
    fireEvent.click(screen.getByRole('button', { name: '관리자' }))
    fireEvent.click(screen.getByRole('button', { name: 'USB 보안키 등록' }))
    fireEvent.click(screen.getByRole('button', { name: '로그아웃' }))
    expect(onAdmin).toHaveBeenCalledOnce()
    expect(onEnrollSecurityKey).toHaveBeenCalledOnce()
    expect(onSignOut).toHaveBeenCalledOnce()
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
        displayName="User"
        canAdminister
        onNavigate={onNavigate}
        onSearch={vi.fn()}
        onWorkspaceChange={onWorkspaceChange}
        onEnrollSecurityKey={vi.fn()}
        onSignOut={vi.fn()}
      />,
    )
    const navigation = screen.getByRole('navigation', { name: '주 메뉴' })
    expect(navigation).not.toHaveTextContent('관리자')
    expect(within(navigation).getByRole('button', { name: '검색' })).toHaveAttribute('aria-current', 'page')
    fireEvent.click(screen.getByRole('button', { name: '변경관리' }))
    expect(onNavigate).toHaveBeenCalledWith('governance')
    const workspace = screen.getByRole('textbox', { name: 'Workspace ID' })
    fireEvent.change(workspace, { target: { value: ' workspace-two ' } })
    expect(onWorkspaceChange).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '적용' }))
    expect(onWorkspaceChange).toHaveBeenCalledWith('workspace-two')
    expect(screen.getByText('Single-node Pilot')).toBeInTheDocument()
  })
})
