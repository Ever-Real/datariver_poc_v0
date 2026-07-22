import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ProfilePage } from './ProfilePage'

describe('ProfilePage', () => {
  it('shows verified identity facts and keeps unsupported profile mutations disabled', () => {
    const onPasswordChange = vi.fn()
    const onPasswordReauth = vi.fn()
    const client = {
      request: vi.fn((path: string) => Promise.resolve(path.includes('/me/summary') ? {
        subject_id: 'subject-1', display_name: '관리자', email: 'admin@example.test',
        last_login_at: null, last_login_ip: null, owned_table_count: 0, change_request_count: 0,
        subject_active: true, membership_active: true, department_id: null,
        job_function: 'ADMINISTRATOR', clearance: 'RESTRICTED', membership_version: 1,
        joined_at: '2026-07-20T00:00:00Z', access_expires_at: '2027-01-20T00:00:00Z',
        renewal_eligible_at: '2026-12-21T00:00:00Z', access_expired: false,
        renewal_request_eligible: false,
        pending_renewal_request_id: null,
      } : { items: [] })),
    }
    render(
      <ProfilePage
        profile={{
          subject: 'subject-1', display_name: '관리자', email: 'admin@example.test',
          roles: ['administrator'], authentication_assurance: 'PASSWORD_REAUTH',
          workspace_selection_enabled: false, hardware_webauthn_enabled: false,
          password_change_supported: true,
        }}
        client={client as never}
        workspace="workspace-one"
        capabilities={[{ name: 'DataHub', state: 'AVAILABLE', observed_at: '2026-07-20T08:00:00Z' }]}
        externalSystemLinks={[{ system_id: 'datahub', label: 'DataHub', url: 'http://localhost:8080' }]}
        onPasswordChange={onPasswordChange}
        onPasswordReauth={onPasswordReauth}
      />,
    )

    expect(screen.getByLabelText('이름')).toHaveValue('관리자')
    expect(screen.getByLabelText('Email')).toHaveValue('admin@example.test')
    expect(screen.getByLabelText('현재 Workspace')).toHaveValue('workspace-one')
    expect(screen.getByLabelText('Workspace 운영 모드')).toHaveValue('단일 Workspace · 전환 비활성')
    expect(screen.getByLabelText('WebAuthn')).toHaveValue('비활성 · 고위험 작업 차단')
    expect(screen.getByRole('button', { name: '변경사항 저장' })).toBeDisabled()
    expect(screen.getByRole('link', { name: '서버 승인 DataHub 링크 열기' })).toHaveAttribute('href', 'http://localhost:8080')
    fireEvent.click(screen.getByRole('button', { name: '비밀번호 변경' }))
    expect(onPasswordChange).toHaveBeenCalledOnce()
    fireEvent.click(screen.getByRole('button', { name: '비밀번호 재인증' }))
    expect(onPasswordReauth).toHaveBeenCalledOnce()
  })
})
