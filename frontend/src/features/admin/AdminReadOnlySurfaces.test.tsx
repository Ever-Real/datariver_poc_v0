import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { AuditLogsAdmin } from './AdminReadOnlySurfaces'

describe('AuditLogsAdmin', () => {
  afterEach(() => {
    window.history.replaceState({}, '', '/')
  })

  it('switches the governed metadata and security log views without inventing rows', () => {
    render(<AuditLogsAdmin />)

    expect(screen.getByRole('tab', { name: '메타데이터 변경 로그' })).toHaveAttribute(
      'aria-selected', 'true',
    )
    expect(screen.getByText('조회 가능한 변경 로그 API가 아직 없습니다.')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('tab', { name: '시스템 보안 로그' }))

    expect(screen.getByRole('tab', { name: '시스템 보안 로그' })).toHaveAttribute(
      'aria-selected', 'true',
    )
    expect(screen.getByText('조회 가능한 보안 로그 API가 아직 없습니다.')).toBeInTheDocument()
    expect(new URL(window.location.href).searchParams.get('adminSection')).toBe('auditLogs')
    expect(new URL(window.location.href).searchParams.get('adminView')).toBe('security')
  })
})
