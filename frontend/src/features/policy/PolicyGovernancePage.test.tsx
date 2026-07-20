import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient } from '../../api/client'
import { PolicyGovernancePage } from './PolicyGovernancePage'

describe('PolicyGovernancePage', () => {
  it('does not issue administrator-policy requests for a user without policy read authority', async () => {
    const request = vi.fn()

    render(
      <PolicyGovernancePage
        client={{ request } as unknown as ApiClient}
        mayReadPolicies={false}
      />,
    )

    expect(
      await screen.findByText('이 정책 read model은 보안 관리자 권한이 있는 사용자에게만 표시됩니다.'),
    ).toBeInTheDocument()
    expect(request).not.toHaveBeenCalled()
  })
})
