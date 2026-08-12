import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient } from '../../api/client'
import { PocGlossaryPage } from './PocGlossaryPage'

describe('PocGlossaryPage', () => {
  it('shows live definitions and opens applied assets from the count', async () => {
    const request = vi.fn().mockResolvedValue({
      items: [{
        urn: 'urn:li:glossaryTerm:wafer',
        name: 'Wafer',
        hierarchical_name: 'manufacturing.wafer',
        description: '반도체 회로를 형성하는 원판입니다.',
        parent_terms: [
          { urn: 'urn:li:glossaryNode:semiconductor', name: 'Semiconductor', description: '' },
          { urn: 'urn:li:glossaryNode:manufacturing', name: 'Manufacturing', description: '' },
        ],
        child_terms: [],
        hierarchy_kind: 'LEAF_TERM',
        asset_count: 1,
        assets: [{
          id: 'urn:li:dataset:wafer-events',
          name: 'wafer_events',
          qualified_name: 'postgres.MANUFACTURING.QUALITY.wafer_events',
          platform: 'postgres',
          database_name: 'MANUFACTURING',
          schema_name: 'QUALITY',
        }],
      }],
    })
    const client = { request } as unknown as ApiClient
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><PocGlossaryPage client={client} /></QueryClientProvider>)

    expect(await screen.findByRole('cell', { name: '반도체 회로를 형성하는 원판입니다.' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: 'Semiconductor › Manufacturing' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Wafer 적용 자산 1개 보기' }))

    expect(screen.getByRole('region', { name: /적용된 DataHub 테이블/ })).toBeVisible()
    expect(screen.getByText('wafer_events')).toBeInTheDocument()
    expect(screen.getByText('postgres.MANUFACTURING.QUALITY.wafer_events')).toBeInTheDocument()
    expect(screen.getByText(/DataHub Glossary Term은 leaf/)).toBeInTheDocument()
  })
})
