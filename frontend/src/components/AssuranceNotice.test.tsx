import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import { AssuranceNotice } from './AssuranceNotice'

function error(kind: 'FIDO2_REQUIRED' | 'REAUTH_REQUIRED' | 'FALLBACK_UNAVAILABLE') {
  return new ApiError({
    type: 'urn:datariver:problem:forbidden',
    title: 'Forbidden',
    status: 403,
    detail: 'denied',
    code: 'forbidden',
    request_id: 'request-one',
    remediation: { kind },
  })
}

describe('AssuranceNotice', () => {
  it('offers explicit enrollment and step-up without replaying an operation', () => {
    const onStepUp = vi.fn(() => Promise.resolve())
    const onPasswordReauth = vi.fn(() => Promise.resolve())
    const onEnroll = vi.fn(() => Promise.resolve())
    render(
      <AssuranceNotice
        error={error('FIDO2_REQUIRED')}
        onStepUp={onStepUp}
        onPasswordReauth={onPasswordReauth}
        onEnroll={onEnroll}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: '보안키로 인증' }))
    fireEvent.click(screen.getByRole('button', { name: '보안키 등록' }))

    expect(onStepUp).toHaveBeenCalledOnce()
    expect(onPasswordReauth).not.toHaveBeenCalled()
    expect(onEnroll).toHaveBeenCalledOnce()
    expect(screen.getByText(/자동 실행되지 않습니다/)).toBeInTheDocument()
  })

  it('routes password reauthentication without changing the existing hardware action', () => {
    const onStepUp = vi.fn(() => Promise.resolve())
    const onPasswordReauth = vi.fn(() => Promise.resolve())
    render(
      <AssuranceNotice
        error={error('REAUTH_REQUIRED')}
        requiredAssurance="PASSWORD"
        onStepUp={onStepUp}
        onPasswordReauth={onPasswordReauth}
        onEnroll={vi.fn()}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: '비밀번호로 재인증' }))

    expect(onPasswordReauth).toHaveBeenCalledOnce()
    expect(onStepUp).not.toHaveBeenCalled()
    expect(screen.getByText(/자동 실행되지 않습니다/)).toBeInTheDocument()
  })

  it('keeps REAUTH_REQUIRED on the hardware step-up path by default', () => {
    const onStepUp = vi.fn(() => Promise.resolve())
    const onPasswordReauth = vi.fn(() => Promise.resolve())
    render(
      <AssuranceNotice
        error={error('REAUTH_REQUIRED')}
        onStepUp={onStepUp}
        onPasswordReauth={onPasswordReauth}
        onEnroll={vi.fn()}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: '보안키로 인증' }))

    expect(onStepUp).toHaveBeenCalledOnce()
    expect(onPasswordReauth).not.toHaveBeenCalled()
  })

  it('uses password reauthentication when WebAuthn is disabled', () => {
    const onStepUp = vi.fn(() => Promise.resolve())
    const onPasswordReauth = vi.fn(() => Promise.resolve())
    render(
      <AssuranceNotice
        error={error('REAUTH_REQUIRED')}
        hardwareWebauthnEnabled={false}
        onStepUp={onStepUp}
        onPasswordReauth={onPasswordReauth}
        onEnroll={vi.fn()}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: '비밀번호로 재인증' }))

    expect(onPasswordReauth).toHaveBeenCalledOnce()
    expect(onStepUp).not.toHaveBeenCalled()
  })

  it('does not offer a security-key action when WebAuthn is disabled', () => {
    const { container } = render(
      <AssuranceNotice
        error={error('FIDO2_REQUIRED')}
        hardwareWebauthnEnabled={false}
        onStepUp={vi.fn()}
        onPasswordReauth={vi.fn()}
        onEnroll={vi.fn()}
      />,
    )

    expect(within(container).getByText('이 환경에서는 WebAuthn을 사용하지 않습니다.')).toBeInTheDocument()
    expect(within(container).queryByRole('button')).not.toBeInTheDocument()
  })

  it('uses the bounded unavailable-fallback copy and offers hardware only', () => {
    const onStepUp = vi.fn(() => Promise.resolve())
    const onPasswordReauth = vi.fn(() => Promise.resolve())
    const { container } = render(
      <AssuranceNotice
        error={error('FALLBACK_UNAVAILABLE')}
        onStepUp={onStepUp}
        onPasswordReauth={onPasswordReauth}
        onEnroll={vi.fn()}
      />,
    )

    expect(within(container).queryByRole('textbox')).not.toBeInTheDocument()
    expect(within(container).getByText('관리자 비밀번호 예외 경로를 사용할 수 없습니다.')).toBeInTheDocument()
    expect(within(container).getByText(/운영 검증된 환경에서만 별도로 제공됩니다/)).toBeInTheDocument()
    expect(within(container).queryByRole('button', { name: /비밀번호/ })).not.toBeInTheDocument()

    fireEvent.click(within(container).getByRole('button', { name: '보안키로 인증' }))
    expect(onStepUp).toHaveBeenCalledOnce()
    expect(onPasswordReauth).not.toHaveBeenCalled()
  })
})
