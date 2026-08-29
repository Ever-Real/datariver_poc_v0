import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ProfilePage } from './ProfilePage'

describe('ProfilePage', () => {
  it('keeps account workflows while omitting operational security fields from the profile UI', () => {
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
        capabilities={[{ name: 'DataHub', state: 'AVAILABLE', observed_at: '2026-07-20T08:00:00Z' }]}
        externalSystemLinks={[{ system_id: 'datahub', label: 'DataHub', url: 'http://localhost:8080' }]}
        onPasswordChange={onPasswordChange}
        onPasswordReauth={onPasswordReauth}
      />,
    )

    expect(screen.getByLabelText('이름')).toHaveValue('관리자')
    expect(screen.getByLabelText('Email')).toHaveValue('admin@example.test')
    expect(screen.getByLabelText('역할')).toHaveValue('administrator')
    expect(screen.queryByLabelText('현재 Workspace')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('인증 보증')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Workspace 운영 모드')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('WebAuthn')).not.toBeInTheDocument()
    expect(screen.queryByText(/RLS·권한·캐시/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '변경사항 저장' })).toBeDisabled()
    expect(screen.getByText('Change Request History')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '서버 승인 DataHub 링크 열기' })).toHaveAttribute('href', 'http://localhost:8080')
    fireEvent.click(screen.getByRole('button', { name: '비밀번호 변경' }))
    expect(onPasswordChange).toHaveBeenCalledOnce()
    fireEvent.click(screen.getByRole('button', { name: '비밀번호 재인증' }))
    expect(onPasswordReauth).toHaveBeenCalledOnce()
  })

  it('keeps local password change separate from OIDC and validates the accessible form', async () => {
    const onPasswordChange = vi.fn()
    const onLocalPasswordChange = vi.fn().mockResolvedValue(undefined)
    const client = { request: vi.fn((path: string) => Promise.resolve(path.includes('/me/summary') ? {
      subject_id: 'subject-1', display_name: '로컬 사용자', email: null,
      last_login_at: null, last_login_ip: null, owned_table_count: 0, change_request_count: 0,
      subject_active: true, membership_active: true, department_id: null, job_function: null,
      clearance: 'NORMAL', membership_version: 1, joined_at: null, access_expires_at: null,
      renewal_eligible_at: null, access_expired: false, renewal_request_eligible: false,
      pending_renewal_request_id: null,
    } : { items: [] })) }
    render(<ProfilePage
      profile={{
        subject: 'subject-1', display_name: '로컬 사용자', roles: ['viewer'],
        authentication_assurance: 'PASSWORD', password_change_supported: true,
      }}
      client={client as never}
      capabilities={[]}
      externalSystemLinks={[]}
      onPasswordChange={onPasswordChange}
      onPasswordReauth={vi.fn()}
      onLocalPasswordChange={onLocalPasswordChange}
    />)

    expect(screen.queryByRole('button', { name: '비밀번호 변경' })).not.toBeInTheDocument()
    expect(screen.getByText(/모든 기기에서 로그아웃/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('현재 비밀번호'), { target: { value: 'current password value' } })
    fireEvent.change(screen.getByLabelText('새 비밀번호'), { target: { value: 'too short' } })
    fireEvent.change(screen.getByLabelText('새 비밀번호 확인'), { target: { value: 'different value' } })
    fireEvent.click(screen.getByRole('button', { name: '새 비밀번호 저장' }))
    expect(onLocalPasswordChange).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent('일치')

    fireEvent.change(screen.getByLabelText('새 비밀번호'), { target: { value: 'new password value' } })
    fireEvent.change(screen.getByLabelText('새 비밀번호 확인'), { target: { value: 'new password value' } })
    fireEvent.click(screen.getByRole('button', { name: '새 비밀번호 저장' }))
    await waitFor(() => expect(onLocalPasswordChange).toHaveBeenCalledWith({
      currentPassword: 'current password value',
      newPassword: 'new password value',
      confirmation: 'new password value',
    }))
    expect(onPasswordChange).not.toHaveBeenCalled()
  })
})
