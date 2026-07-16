import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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
        allowed_operations: ['MEMBERSHIP_ACCESS_READ', 'MEMBERSHIP_ACCESS_UPDATE'],
        action_vocabulary: ['admin.manage', 'catalog.read'],
      }))
      if (url.endsWith('/admin/workspace-memberships?limit=100')) return Promise.resolve(json({ items: [{
        subject_id: 'target-one', display_name: 'Target User', subject_active: true,
        membership_active: true, department_id: null, job_function: 'ENGINEER',
        clearance: 'INTERNAL', membership_version: 1,
      }] }))
      if (url.endsWith('/admin/workspace-memberships/target-one/access') && init?.method === 'PUT') {
        return Promise.resolve(json({
          type: 'urn:datariver:problem:forbidden', title: 'Forbidden', detail: 'step-up required',
          code: 'forbidden', request_id: 'request-admin-one', remediation: { kind: 'FIDO2_REQUIRED' },
        }, 403))
      }
      if (url.endsWith('/admin/workspace-memberships/target-one/access')) return Promise.resolve(json({
        subject_id: 'target-one', display_name: 'Target User', subject_active: true,
        department_id: null, job_function: 'ENGINEER', membership_version: 1,
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

    const update = await screen.findByRole('button', { name: /보안키로 직접 변경|Update with security key/ })
    expect(screen.queryByRole('button', { name: /보존정책|Retention policies/ })).not.toBeInTheDocument()
    fireEvent.click(update)
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'PUT')).toHaveLength(0)

    fireEvent.click(screen.getByRole('button', { name: /확인 후 실행|Review and execute/ }))
    await screen.findByText('USB 보안키 인증이 필요합니다.')
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'PUT')).toHaveLength(1)

    fireEvent.click(screen.getByRole('button', { name: '보안키로 인증' }))
    await waitFor(() => expect(onStepUp).toHaveBeenCalledOnce())
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'PUT')).toHaveLength(1)
  })
})

function json(body: object, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } })
}
