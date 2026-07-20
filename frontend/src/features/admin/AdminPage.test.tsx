import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiClient } from '../../api/client'
import { AdminPage } from './AdminPage'

afterEach(() => vi.unstubAllGlobals())

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
      if (url.endsWith('/admin/workspace-memberships?limit=100')) return Promise.resolve(json({ items: [{
        subject_id: 'target-one', display_name: 'Target User', subject_active: true,
        membership_active: true, department_id: null, job_function: 'ENGINEER',
        clearance: 'INTERNAL', membership_version: 1, email: null, last_login_at: null,
        last_login_ip: null, owned_table_count: 0, change_request_count: 0,
      }] }))
      if (url.endsWith('/admin/systems?limit=100')) return Promise.resolve(json({ items: [{
        system_id: 'system-one', code: 'FAB', name: 'Fabrication', description: 'Fab data', active: true, version: 1,
        assignees: [
          { subject_id: 'target-one', display_name: 'Target User', responsibility: 'DEVELOPER', priority: 1, active: true },
          { subject_id: 'target-one', display_name: 'Target User', responsibility: 'DATA_STEWARD', priority: 1, active: true },
        ],
      }] }))
      if (url.endsWith('/admin/system-configuration')) return Promise.resolve(json({ items: [{
        system_id: 'GRAFANA_DASHBOARD', label: 'Grafana Dashboard', state: 'CONFIGURED', management_plane: 'DEPLOYMENT',
        secret_reference_configured: false, embedding_state: 'DISABLED', configuration_yaml: '',
        template_yaml: '', display_yaml: '', version: 0, configured_at: null,
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
    expect(screen.getByRole('table', { name: '워크스페이스 사용자 목록' })).toBeInTheDocument()
    expect(screen.getByText(/OIDC 주체와 현재 Workspace 멤버십, 소유 테이블 및 CR 이력을 표시합니다/)).toBeInTheDocument()
    fireEvent.change(screen.getByRole('searchbox', { name: '사용자 검색' }), { target: { value: 'missing' } })
    expect(screen.getByText(/조회 가능한 항목이 없습니다|No authorized items are available/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '필터 초기화' }))
    expect(screen.getAllByText('Target User')).toHaveLength(2)
    const accountTabs = screen.getByRole('tablist', { name: '계정/권한 관리 영역' })
    expect(within(accountTabs).getByRole('tab', { name: 'USERS' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Role 정의·할당' })).toBeInTheDocument()
    fireEvent.click(within(accountTabs).getByRole('tab', { name: 'SYSTEMS' }))
    await screen.findByText('Fabrication')
    expect(screen.getAllByText('1. Target User')).toHaveLength(2)
    expect(screen.getByRole('table', { name: '워크스페이스 시스템 목록' })).toBeInTheDocument()
    const updateAssignments = await screen.findByRole('button', { name: '설정 저장' })
    await waitFor(() => expect(updateAssignments).toBeEnabled())
    fireEvent.click(updateAssignments)
    expect(await screen.findByText('시스템 담당자 배정 변경')).toBeInTheDocument()
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'PUT')).toHaveLength(0)
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
})

function json(body: object, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } })
}
