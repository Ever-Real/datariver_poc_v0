import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiClient, ApiError } from '../../api/client'
import type { AdminReadContext } from '../../api/types'
import type { PendingAdminMutation } from './AdminMutationConfirmDialog'
import { AdminPage } from './AdminPage'

const mutationProbe = vi.hoisted(() => ({ execute: vi.fn<() => Promise<void>>() }))

vi.mock('./SystemConfigurationAdmin', () => ({
  SystemConfigurationAdmin: ({
    requestConfirmation,
  }: {
    requestConfirmation: (mutation: PendingAdminMutation) => void
  }) => <button type="button" onClick={() => requestConfirmation({
    title: 'Test admin mutation',
    summary: ['Review this mutation'],
    execute: mutationProbe.execute,
  })}>Request test mutation</button>,
}))

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  window.history.replaceState({}, '', '/')
  window.localStorage?.clear?.()
  mutationProbe.execute.mockReset()
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

  it('removes the duplicate administration glossary tab and keeps USERS focused on the user table', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(json({
      items: [], page: { next_cursor: null, limit: 25 },
    }))))
    renderPage()

    const tabs = screen.getByRole('tablist', { name: 'Administration and data governance' })
    expect(within(tabs).getAllByRole('tab')).toHaveLength(4)
    expect(within(tabs).getByRole('tab', { name: 'Accounts & access' })).toBeInTheDocument()
    expect(within(tabs).getByRole('tab', { name: 'System settings' })).toBeInTheDocument()
    expect(within(tabs).getByRole('tab', { name: 'Retention & erasure governance' })).toBeInTheDocument()
    expect(within(tabs).getByRole('tab', { name: 'Audit/Log review' })).toBeInTheDocument()
    expect(within(tabs).queryByRole('tab', { name: 'Terminology dictionary' })).not.toBeInTheDocument()
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

  it('dismisses the disabled-WebAuthn warning after three seconds and cleans up its timer', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(json({
      items: [], page: { next_cursor: null, limit: 25 },
    }))))

    const view = renderPage(adminContext({ subject_id: 'admin-timed-warning' }), false)
    expect(screen.getByText('WebAuthn 보안키 인증이 필요합니다.')).toBeInTheDocument()

    await act(() => vi.advanceTimersByTime(2_999))
    expect(screen.getByText('WebAuthn 보안키 인증이 필요합니다.')).toBeInTheDocument()
    await act(() => vi.advanceTimersByTime(1))
    expect(screen.queryByText('WebAuthn 보안키 인증이 필요합니다.')).not.toBeInTheDocument()

    expect(() => view.unmount()).not.toThrow()
  })

  it('keeps a failed mutation open with its typed error, then closes after a successful retry', async () => {
    window.history.replaceState({}, '', '/?page=admin&adminSection=systemSettings')
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const requestUrl = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      if (requestUrl.endsWith('/quality/capability')) return Promise.resolve(json(qualityCapability()))
      return Promise.resolve(json({ items: [], page: { next_cursor: null, limit: 25 } }))
    }))
    mutationProbe.execute
      .mockRejectedValueOnce(new ApiError({
        type: 'https://datariver.invalid/problems/admin-mutation',
        title: 'Mutation rejected',
        status: 422,
        detail: 'The requested mutation is invalid.',
        code: 'ADMIN_MUTATION_INVALID',
        request_id: 'request-admin-mutation',
      }))
      .mockResolvedValueOnce(undefined)

    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Request test mutation' }))
    fireEvent.click(within(screen.getByRole('dialog', { name: 'Test admin mutation' })).getByRole('button', { name: 'Review and execute' }))

    expect(await screen.findByText('The requested mutation is invalid.')).toBeVisible()
    expect(screen.getByRole('dialog', { name: 'Test admin mutation' })).toBeInTheDocument()
    expect(mutationProbe.execute).toHaveBeenCalledTimes(1)

    fireEvent.click(within(screen.getByRole('dialog', { name: 'Test admin mutation' })).getByRole('button', { name: 'Review and execute' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Test admin mutation' })).not.toBeInTheDocument())
    expect(mutationProbe.execute).toHaveBeenCalledTimes(2)
  })

  it('keeps Quality/GX read capability visible when execution control is deferred', async () => {
    window.history.replaceState({}, '', '/?page=admin&adminSection=systemSettings')
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const requestUrl = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      if (requestUrl.endsWith('/quality/capability')) return Promise.resolve(json(qualityCapability()))
      return Promise.resolve(json({ items: [], page: { next_cursor: null, limit: 25 } }))
    }))

    renderPage()

    const status = await screen.findByText('사용 가능')
    expect(status).toHaveAttribute('role', 'status')
    expect(screen.getByText('Quality/GX 읽기 capability를 사용할 수 있습니다.')).toBeInTheDocument()
    expect(screen.getByText('실행 제어: 확인 보류')).toBeInTheDocument()
    expect(screen.getByText((_, element) => (
      element?.textContent === '실행 제어: 확인 보류 · 현재 연결은 품질 정보를 읽을 수 있지만 실행 기능은 제공하지 않습니다.'
    ))).toBeInTheDocument()
    expect(screen.queryByText('QUALITY_CONTROL_PLANE_NOT_CONFIGURED')).not.toBeInTheDocument()
  })
})

function qualityCapability() {
  return {
    contract_version: 'QUALITY_CAPABILITY_V2',
    observed_at: '2026-08-30T00:00:00.000Z',
    valid_until: '2026-08-30T00:00:30.000Z',
    cache_scope: 'a'.repeat(64),
    axes: [
      { id: 'read_access', state: 'AVAILABLE' },
      { id: 'manual_execution', state: 'UNAVAILABLE', reason_code: 'QUALITY_CONTROL_PLANE_NOT_CONFIGURED' },
    ],
  }
}

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
}
