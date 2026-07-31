import { render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiClient } from '../../api/client'
import type { AdminReadContext } from '../../api/types'
import { AdminPage } from './AdminPage'

afterEach(() => {
  vi.unstubAllGlobals()
  window.history.replaceState({}, '', '/')
  window.localStorage?.clear?.()
})

function adminContext(overrides: Partial<AdminReadContext> = {}): AdminReadContext {
  return {
    subject_id: 'admin-one', workspace_id: 'workspace-one', display_name: 'Administrator',
    authentication_assurance: 'HARDWARE_WEBAUTHN', fallback_enabled: false,
    allowed_operations: [
      'MEMBERSHIP_ACCESS_READ', 'MEMBERSHIP_RENEWAL_READ', 'SYSTEM_CONFIGURATION_READ',
      'RETENTION_POLICY_READ',
    ],
    action_vocabulary: ['admin.manage', 'catalog.read'],
    ...overrides,
  }
}

function renderPage(context = adminContext(), hardwareWebauthnEnabled = true) {
  return render(<AdminPage
    client={new ApiClient('/api/v1', () => 'token', () => 'workspace-one')}
    initialContext={context}
    workspace="workspace-one"
    hardwareWebauthnEnabled={hardwareWebauthnEnabled}
    onStepUp={vi.fn(() => Promise.resolve())}
    onPasswordReauth={vi.fn(() => Promise.resolve())}
    onEnroll={vi.fn(() => Promise.resolve())}
  />)
}

describe('AdminPage', () => {
  it('shows the administrator display name without exposing the canonical subject identifier', () => {
    const subjectId = '00000000-0000-4000-8000-000000000106'
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(json({
      items: [], page: { next_cursor: null, limit: 25 },
    }))))

    renderPage(adminContext({ subject_id: subjectId, display_name: '한수아' }))

    expect(screen.getByText('한수아')).toBeInTheDocument()
    expect(screen.queryByText(subjectId)).not.toBeInTheDocument()
  })

  it('renders exactly the three primary administration tabs and keeps USERS focused on the user table', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(json({
      items: [], page: { next_cursor: null, limit: 25 },
    }))))
    renderPage()

    const tabs = screen.getByRole('tablist', { name: 'Administration and data governance' })
    expect(within(tabs).getAllByRole('tab')).toHaveLength(3)
    expect(within(tabs).getByRole('tab', { name: 'Accounts & access' })).toBeInTheDocument()
    expect(within(tabs).getByRole('tab', { name: 'System settings' })).toBeInTheDocument()
    expect(within(tabs).getByRole('tab', { name: 'Retention & erasure governance' })).toBeInTheDocument()
    expect(await screen.findByRole('table', { name: '워크스페이스 사용자 목록' })).toBeInTheDocument()
    expect(screen.queryByText('세부 Access 문서 (고급)')).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Role 정의 및 사용자 할당' })).not.toBeInTheDocument()

  })

  it('shows the disabled-WebAuthn warning once per authorized administrator', async () => {
    const storage = new Map<string, string>()
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => { storage.set(key, value) },
      clear: () => { storage.clear() },
    })
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(json({
      items: [], page: { next_cursor: null, limit: 25 },
    }))))
    const first = renderPage(adminContext({ subject_id: 'admin-warning' }), false)
    expect(await screen.findByText('WebAuthn 보안키 인증이 필요합니다.')).toBeInTheDocument()
    expect(storage.get('webAuthnWarningShown_admin-warning')).toBe('true')
    first.unmount()

    renderPage(adminContext({ subject_id: 'admin-warning' }), false)
    await waitFor(() => expect(screen.queryByText('WebAuthn 보안키 인증이 필요합니다.')).not.toBeInTheDocument())
  })
})

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
}
