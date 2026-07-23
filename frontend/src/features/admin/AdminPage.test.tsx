import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiClient } from '../../api/client'
import type { AdminReadContext } from '../../api/types'
import { AdminPage } from './AdminPage'

afterEach(() => {
  vi.unstubAllGlobals()
  window.history.replaceState({}, '', '/')
})

describe('AdminPage mutation safety', () => {
  it('requires confirmation and never replays a denied mutation after step-up', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string'
        ? input
        : input instanceof URL
          ? input.href
          : input.url
      if (url.endsWith('/admin/me')) return Promise.resolve(json({
        subject_id: 'admin-one', workspace_id: 'workspace-one', display_name: 'Administrator',
        authentication_assurance: 'HARDWARE_WEBAUTHN', fallback_enabled: false,
        allowed_operations: ['MEMBERSHIP_ACCESS_READ', 'MEMBERSHIP_ACCESS_UPDATE', 'SYSTEM_ASSIGNMENT_UPDATE', 'SYSTEM_CONFIGURATION_READ'],
        action_vocabulary: ['admin.manage', 'catalog.read'],
      }))
      if (url.includes('/admin/workspace-memberships?')) return Promise.resolve(json({ items: url.includes('q=missing') ? [] : [{
        subject_id: 'target-one', display_name: 'Target User', subject_active: true,
        membership_active: true, department_id: null, job_function: 'ENGINEER',
        clearance: 'INTERNAL', membership_version: 1, email: null, last_login_at: null,
        last_login_ip: null, owned_table_count: 0, change_request_count: 0,
        joined_at: null, access_expires_at: null, access_expired: false,
        pending_renewal_request_id: null,
      }], page: { next_cursor: null, limit: 25 } }))
      if (url.endsWith('/admin/systems?limit=25')) return Promise.resolve(json({ items: [{
        system_id: 'system-one', code: 'FAB', name: 'Fabrication', description: 'Fab data', active: true, version: 1, assignee_count: 2,
        assignees: [],
      }], page: { next_cursor: null, limit: 25 } }))
      if (url.endsWith('/admin/systems/system-one/assignees?limit=25')) return Promise.resolve(json({
        system_version: 1,
        items: [
          { subject_id: 'target-one', display_name: 'Target User', responsibility: 'DEVELOPER', priority: 1, active: true },
          { subject_id: 'target-one', display_name: 'Target User', responsibility: 'DATA_STEWARD', priority: 1, active: true },
        ],
        page: { next_cursor: null, limit: 25 },
      }))
      if (url.endsWith('/admin/system-configuration')) return Promise.resolve(json({ items: [{
        system_id: 'GRAFANA_DASHBOARD', label: 'Grafana Dashboard', state: 'CONFIGURED', management_plane: 'DEPLOYMENT',
        category: 'OBSERVABILITY', requirement: 'FEATURE_CONNECTOR', description: 'Dashboard', connection_requirements: [],
        secret_reference_configured: false, embedding_state: 'DISABLED', configuration_yaml: '',
        template_yaml: '', display_yaml: '', version: 0, configured_at: null, runtime_supported: true,
        restart_scope: 'API_ONLY', activation_state: 'DEPLOYMENT_MANAGED', tested_version: null,
        test_status: null, tested_at: null, activated_version: null, activated_at: null, applied_version: null,
      }] }))
      if (url.endsWith('/admin/workspace-memberships/target-one/access') && init?.method === 'PUT') {
        return Promise.resolve(json({
          type: 'urn:datariver:problem:forbidden', title: 'Forbidden', detail: 'step-up required',
          code: 'forbidden', request_id: 'request-admin-one', remediation: { kind: 'FIDO2_REQUIRED' },
        }, 403))
      }
      if (url.endsWith('/admin/workspace-memberships/target-one/access')) return Promise.resolve(json({
        subject_id: 'target-one', display_name: 'Target User', subject_active: true,
        department_id: null, job_function: 'ENGINEER', membership_version: 1, email: null,
        last_login_at: null, last_login_ip: null, owned_table_count: 0, change_request_count: 0,
        access: { active: true, clearance: 'INTERNAL', groups: ['engineers'], allowed_actions: ['catalog.read'], denied_actions: [], allowed_system_ids: [], allowed_domain_ids: [] },
        role_assignment: {
          status: 'MANUAL', role_id: null, role_version: null, assignment_version: null,
          membership_version: 1, access_payload_hash: null, assigned_by: null,
          updated_at: null, legacy_markers: [],
        },
      }, 200, { ETag: '"1"' }))
      throw new Error(`unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const onStepUp = vi.fn(() => Promise.resolve())
    render(<AdminPage
      client={new ApiClient('/api/v1', () => 'token', () => 'workspace-one')}
      onStepUp={onStepUp}
      onPasswordReauth={vi.fn(() => Promise.resolve())}
      onEnroll={vi.fn(() => Promise.resolve())}
    />)

    expect(await screen.findByText('Target User')).toBeInTheDocument()
    expect(screen.getByText('Audit/Log·전사 용어사전 관리자 API 미구현')).toBeInTheDocument()
    expect(screen.getByRole('table', { name: '워크스페이스 사용자 목록' })).toBeInTheDocument()
    expect(screen.getByText(/인증된 사용자와 현재 Workspace 멤버십, 소유 테이블 및 CR 이력을 표시합니다/)).toBeInTheDocument()
    fireEvent.change(screen.getByRole('searchbox', { name: '사용자 검색' }), { target: { value: 'missing' } })
    await screen.findByText(/조회 가능한 항목이 없습니다|No authorized items are available/)
    fireEvent.click(screen.getByRole('button', { name: '필터 초기화' }))
    await waitFor(() => expect(screen.getAllByText('Target User')).toHaveLength(2))
    const accountTabs = screen.getByRole('tablist', { name: '계정/권한 관리 영역' })
    expect(within(accountTabs).getByRole('tab', { name: 'USERS' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Role 정의·할당' })).toBeInTheDocument()
    fireEvent.click(within(accountTabs).getByRole('tab', { name: 'SYSTEMS' }))
    await screen.findByText('Fabrication')
    expect(screen.getByRole('table', { name: '워크스페이스 시스템 목록' })).toBeInTheDocument()
    const priorities = await screen.findAllByRole('spinbutton')
    expect(screen.getAllByRole('option', { name: 'Target User' })).toHaveLength(2)
    fireEvent.change(priorities[0]!, { target: { value: '2' } })
    const updateAssignments = await screen.findByRole('button', { name: '현재 페이지 변경 저장' })
    await waitFor(() => expect(updateAssignments).toBeEnabled())
    fireEvent.click(updateAssignments)
    expect(await screen.findByText('시스템 담당자 변경')).toBeInTheDocument()
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'PATCH')).toHaveLength(0)
    fireEvent.click(screen.getByRole('button', { name: /취소|Cancel/ }))
    fireEvent.click(screen.getByRole('tab', { name: /시스템 설정|System settings/ }))
    expect(await screen.findByRole('heading', { name: 'Grafana Dashboard' })).toBeInTheDocument()
    expect(screen.getByText('배포 설정')).toBeInTheDocument()
    expect(screen.getByText(/이 환경에서는 설정 YAML을 편집할 수 없습니다/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: /계정\/권한|Accounts & access/ }))
    fireEvent.click(within(screen.getByRole('tablist', { name: '계정/권한 관리 영역' })).getByRole('tab', { name: 'USERS' }))
    const update = await screen.findByRole('button', { name: /보안키로 직접 변경|Update with security key/ })
    expect(screen.queryByRole('button', { name: /보존정책|Retention policies/ })).not.toBeInTheDocument()
    fireEvent.click(update)
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'PUT')).toHaveLength(0)

    fireEvent.click(screen.getByRole('button', { name: /확인 후 실행|Review and execute/ }))
    await screen.findByText('WebAuthn 보안키 인증이 필요합니다.')
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'PUT')).toHaveLength(1)

    fireEvent.click(screen.getByRole('button', { name: '보안키로 인증' }))
    await waitFor(() => expect(onStepUp).toHaveBeenCalledOnce())
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'PUT')).toHaveLength(1)
  })

  it('discards a pending mutation when fallback or action vocabulary changes', async () => {
    const initial = adminContext({
      fallback_enabled: false,
      action_vocabulary: ['admin.manage', 'catalog.read'],
    })
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = requestUrl(input)
      if (url.includes('/admin/workspace-memberships?')) return Promise.resolve(json({
        items: [{
          subject_id: 'target-one', display_name: 'Target User', subject_active: true,
          membership_active: true, department_id: null, job_function: 'ENGINEER',
          clearance: 'INTERNAL', membership_version: 1, email: null, last_login_at: null,
          last_login_ip: null, owned_table_count: 0, change_request_count: 0,
          joined_at: null, access_expires_at: null, access_expired: false,
          pending_renewal_request_id: null,
        }],
        page: { next_cursor: null, limit: 25 },
      }))
      if (url.endsWith('/admin/workspace-memberships/target-one/access')) {
        return Promise.resolve(json({
          subject_id: 'target-one', display_name: 'Target User', subject_active: true,
          department_id: null, job_function: 'ENGINEER', membership_version: 1,
          access: {
            active: true, clearance: 'INTERNAL', groups: ['engineers'],
            allowed_actions: ['catalog.read'], denied_actions: [],
            allowed_system_ids: [], allowed_domain_ids: [],
          },
          role_assignment: {
            status: 'MANUAL', role_id: null, role_version: null, assignment_version: null,
            membership_version: 1, access_payload_hash: null, assigned_by: null,
            updated_at: null, legacy_markers: [],
          },
        }, 200, { ETag: '"1"' }))
      }
      throw new Error(`unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace-one')
    const actions = {
      onStepUp: vi.fn(() => Promise.resolve()),
      onPasswordReauth: vi.fn(() => Promise.resolve()),
      onEnroll: vi.fn(() => Promise.resolve()),
    }
    const view = render(
      <AdminPage client={client} initialContext={initial} {...actions} />,
    )

    fireEvent.click(await screen.findByRole('button', { name: /보안키로 직접 변경|Update with security key/ }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()

    view.rerender(<AdminPage
      client={client}
      initialContext={adminContext({
        fallback_enabled: true,
        action_vocabulary: ['admin.manage', 'catalog.read', 'catalog.search'],
      })}
      {...actions}
    />)

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('does not let an older manual refresh overwrite a newer initial context', async () => {
    const delayed = deferred<Response>()
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = requestUrl(input)
      if (url.endsWith('/admin/me')) return delayed.promise
      throw new Error(`unexpected request: ${url}`)
    }))
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace-one')
    const actions = {
      onStepUp: vi.fn(() => Promise.resolve()),
      onPasswordReauth: vi.fn(() => Promise.resolve()),
      onEnroll: vi.fn(() => Promise.resolve()),
    }
    const view = render(<AdminPage
      client={client}
      initialContext={adminContext({ subject_id: 'admin-old', display_name: 'Old Admin' })}
      {...actions}
    />)

    fireEvent.click(screen.getAllByRole('button', { name: /새로고침|Refresh/ })[0]!)
    view.rerender(<AdminPage
      client={client}
      initialContext={adminContext({ subject_id: 'admin-new', display_name: 'New Admin' })}
      {...actions}
    />)
    delayed.resolve(json(adminContext({ subject_id: 'admin-old', display_name: 'Old Admin' })))

    expect(await screen.findByText('New Admin')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText('Old Admin')).not.toBeInTheDocument())
  })
})

function adminContext(overrides: Partial<{
  subject_id: string
  display_name: string
  fallback_enabled: boolean
  action_vocabulary: string[]
}> = {}): AdminReadContext {
  return {
    subject_id: overrides.subject_id ?? 'admin-one',
    workspace_id: 'workspace-one',
    display_name: overrides.display_name ?? 'Administrator',
    authentication_assurance: 'HARDWARE_WEBAUTHN' as const,
    fallback_enabled: overrides.fallback_enabled ?? false,
    allowed_operations: ['MEMBERSHIP_ACCESS_READ', 'MEMBERSHIP_ACCESS_UPDATE'],
    action_vocabulary: overrides.action_vocabulary ?? ['admin.manage', 'catalog.read'],
  }
}

function requestUrl(input: RequestInfo | URL) {
  return typeof input === 'string'
    ? input
    : input instanceof URL
      ? input.href
      : input.url
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((accept) => { resolve = accept })
  return { promise, resolve }
}

function json(body: object, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } })
}
