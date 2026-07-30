import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
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

  it('keeps the existing policy status view and opens the separately authorized document library', async () => {
    const request = vi.fn().mockImplementation((path: string) => {
      if (path === '/governance/documents/capability') {
        return Promise.resolve({
          contract_version: 'GOVERNANCE_DOCUMENT_CAPABILITY_V1',
          observed_at: new Date(Date.now() - 1_000).toISOString(),
          valid_until: new Date(Date.now() + 30_000).toISOString(),
          cache_scope: 'a'.repeat(64),
          axes: [
            'read',
            'create',
            'edit',
            'review',
            'publish',
            'archive',
            'template_manage',
            'artifact_storage',
            'knowledge_projection',
          ].map((id) => ({
            id,
            state: 'DENIED',
            reason_code: 'PERMISSION_DENIED',
          })),
          limits: {
            max_html_bytes: 1_000_000,
            max_attachment_bytes: 10_000_000,
            max_attachments_per_version: 25,
          },
        })
      }
      throw new Error(`unexpected request: ${path}`)
    })
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <PolicyGovernancePage
          client={{ request } as unknown as ApiClient}
          mayReadPolicies={false}
        />
      </QueryClientProvider>,
    )

    expect(await screen.findByText('이 정책 read model은 보안 관리자 권한이 있는 사용자에게만 표시됩니다.')).toBeInTheDocument()
    expect(request).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('tab', { name: '문서 라이브러리' }))

    expect(await screen.findByText('문서 열람이 허용되지 않았습니다')).toBeInTheDocument()
    expect(request).toHaveBeenCalledTimes(1)
  })
})
