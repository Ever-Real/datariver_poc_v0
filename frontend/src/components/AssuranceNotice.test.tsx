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
    const onEnroll = vi.fn(() => Promise.resolve())
    render(
      <AssuranceNotice error={error('FIDO2_REQUIRED')} onStepUp={onStepUp} onEnroll={onEnroll} />,
    )

    fireEvent.click(screen.getByRole('button', { name: '보안키로 인증' }))
    fireEvent.click(screen.getByRole('button', { name: '보안키 등록' }))

    expect(onStepUp).toHaveBeenCalledOnce()
    expect(onEnroll).toHaveBeenCalledOnce()
    expect(screen.getByText(/자동 실행되지 않습니다/)).toBeInTheDocument()
  })

  it('does not expose a password or direct-execution control for unavailable fallback', () => {
    const { container } = render(
      <AssuranceNotice
        error={error('FALLBACK_UNAVAILABLE')}
        onStepUp={vi.fn()}
        onEnroll={vi.fn()}
      />,
    )

    expect(within(container).queryByRole('textbox')).not.toBeInTheDocument()
    expect(within(container).queryByRole('button')).not.toBeInTheDocument()
    expect(within(container).getByText(/승인 절차가 제공되기 전/)).toBeInTheDocument()
  })
})
