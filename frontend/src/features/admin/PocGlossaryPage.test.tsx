import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient } from '../../api/client'
import { PocGlossaryPage } from './PocGlossaryPage'

describe('PocGlossaryPage', () => {
  it('renders the live GlossaryNode hierarchy and separates applied tables from columns', async () => {
    const term = {
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
        asset_count: 2,
        table_asset_count: 1,
        column_asset_count: 1,
        assets: [],
        relationship_count: 1,
        relationships: [{
          type: 'RelatedTo', direction: 'OUTGOING',
          target_urn: 'urn:li:glossaryTerm:substrate', target_type: 'GLOSSARY_TERM', target_name: 'Substrate',
        }],
        relationships_truncated: false,
      }
    const table = {
          id: 'urn:li:dataset:wafer-events',
          target_type: 'TABLE',
          name: 'wafer_events',
          table_name: 'wafer_events',
          field_path: null,
          qualified_name: 'postgres.MANUFACTURING.QUALITY.wafer_events',
          platform: 'postgres',
          database_name: 'MANUFACTURING',
          schema_name: 'QUALITY',
        }
    const column = {
          id: 'urn:li:dataset:wafer-events#wafer_id',
          target_type: 'COLUMN',
          name: 'wafer_id',
          table_name: 'wafer_events',
          field_path: 'wafer_id',
          qualified_name: 'postgres.MANUFACTURING.QUALITY.wafer_events.wafer_id',
          platform: 'postgres',
          database_name: 'MANUFACTURING',
          schema_name: 'QUALITY',
        }
    const request = vi.fn((path: string) => {
      if (path.includes('/glossary/detail?')) return Promise.resolve(term)
      if (path.includes('/assignments?') && path.includes('target_type=TABLE')) {
        return Promise.resolve({ items: [table], total: 1, page: { next_cursor: null, limit: 25 } })
      }
      if (path.includes('/assignments?') && path.includes('target_type=COLUMN')) {
        return Promise.resolve({ items: [column], total: 1, page: { next_cursor: null, limit: 25 } })
      }
      return Promise.resolve({
        items: [term], total: 1, page: { next_cursor: null, limit: 50 },
        currentness: {
          source: 'DATAHUB_GMS_LIVE', observed_at: '2026-08-29T00:00:00.000Z', atomic_snapshot: false,
        },
      })
    })
    const client = { request } as unknown as ApiClient
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><PocGlossaryPage client={client} /></QueryClientProvider>)

    expect(await screen.findByRole('cell', { name: '반도체 회로를 형성하는 원판입니다.' })).toBeInTheDocument()
    expect(screen.getByRole('row', { name: /Semiconductor/ })).toBeInTheDocument()
    expect(screen.getByRole('row', { name: /Manufacturing/ })).toBeInTheDocument()
    expect(screen.getByRole('row', { name: /Wafermanufacturing\.wafer/ })).toBeInTheDocument()
    expect(screen.getByRole('row', { name: /Wafermanufacturing\.wafer/ }).querySelector('[style]')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Semiconductor 하위 용어 접기' }))
    expect(screen.queryByRole('row', { name: /Wafermanufacturing\.wafer/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Semiconductor 하위 용어 펼치기' }))
    fireEvent.click(screen.getByRole('button', { name: 'Wafer 적용 테이블 1개 보기' }))

    expect(screen.getByRole('region', { name: /적용된 DataHub 테이블/ })).toBeVisible()
    expect(screen.getByRole('region', { name: /적용된 DataHub 컬럼/ })).toBeVisible()
    expect(await screen.findByText('wafer_events')).toBeInTheDocument()
    expect(await screen.findByText('postgres.MANUFACTURING.QUALITY.wafer_events')).toBeInTheDocument()
    expect(await screen.findByText('wafer_events.wafer_id')).toBeInTheDocument()
    expect(await screen.findByText('postgres.MANUFACTURING.QUALITY.wafer_events.wafer_id')).toBeInTheDocument()
    expect(screen.getByText(/DataHub Glossary Term은 leaf/)).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '선택 용어의 DataHub 직접 관계' })).toHaveTextContent('RelatedTo')
    expect(screen.getByRole('region', { name: '선택 용어의 DataHub 직접 관계' })).toHaveTextContent('Substrate')
    expect(screen.getByText(/atomic snapshot으로 간주하지 않습니다/)).toBeInTheDocument()
  })
})
