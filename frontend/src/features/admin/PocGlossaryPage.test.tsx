import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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

  it('posts the visible page URNs and distinguishes skeleton, explicit zero, and missing-item errors', async () => {
    const term = glossaryTerm('urn:li:glossaryTerm:loaded', 'LoadedTerm')
    const zeroTerm = glossaryTerm('urn:li:glossaryTerm:zero', 'ZeroTerm')
    const missingTerm = glossaryTerm('urn:li:glossaryTerm:missing', 'MissingTerm')
    let resolveCounts!: (value: unknown) => void
    const countsPromise = new Promise<unknown>((resolve) => { resolveCounts = resolve })
    const request = vi.fn((path: string, options?: RequestInit) => {
      if (path === '/poc/glossary/assignments/batch-counts' && options?.method === 'POST') return countsPromise
      return Promise.resolve(glossaryPage([term, zeroTerm, missingTerm]))
    })
    const client = { request } as unknown as ApiClient
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><PocGlossaryPage client={client} /></QueryClientProvider>)

    await waitFor(() => expect(request).toHaveBeenCalledWith(
      '/poc/glossary/assignments/batch-counts',
      expect.objectContaining({ method: 'POST' }),
    ))
    expect(screen.getByRole('button', { name: 'LoadedTerm 적용 테이블 조회 중' })).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /적용 (테이블|컬럼) 조회 중/ })).toHaveLength(6)
    const countCall = request.mock.calls.find(([path]) => path === '/poc/glossary/assignments/batch-counts')
    expect(countCall?.[1]).toMatchObject({
      method: 'POST',
      body: JSON.stringify({ urns: [term.urn, zeroTerm.urn, missingTerm.urn] }),
    })
    expect(jsonRequestBody(countCall?.[1]).urns).toHaveLength(3)

    resolveCounts({
      items: [
        { urn: term.urn, table_asset_count: 5, column_asset_count: 10 },
        { urn: zeroTerm.urn, table_asset_count: 0, column_asset_count: 0 },
      ],
    })

    expect(await screen.findByRole('button', { name: 'LoadedTerm 적용 테이블 5개 보기' })).toHaveTextContent('5')
    expect(screen.getByRole('button', { name: 'LoadedTerm 적용 컬럼 10개 보기' })).toHaveTextContent('10')
    expect(screen.getByRole('button', { name: 'ZeroTerm 적용 테이블 0개 보기' })).toHaveTextContent('0')
    expect(screen.getByRole('button', { name: 'ZeroTerm 적용 컬럼 0개 보기' })).toHaveTextContent('0')
    expect(screen.getByRole('button', { name: 'MissingTerm 적용 테이블 조회 오류' })).toHaveTextContent('오류')
    expect(screen.getByRole('button', { name: 'MissingTerm 적용 컬럼 조회 오류' })).toHaveTextContent('오류')
    expect(screen.getAllByRole('alert')[0]).toHaveAttribute('title', expect.stringContaining(missingTerm.urn))
    expect(screen.getByRole('row', { name: /MissingTerm/ }).querySelector('[style]')).toBeNull()
  })

  it('keeps the initial page count independent while the exact next-page batch is loading', async () => {
    const firstTerm = glossaryTerm('urn:li:glossaryTerm:first', 'FirstTerm')
    const nextTerm = glossaryTerm('urn:li:glossaryTerm:next', 'NextTerm')
    const batchBodies: string[][] = []
    const pendingNextPage = new Promise<unknown>(() => undefined)
    const request = vi.fn((path: string, options?: RequestInit) => {
      if (path === '/poc/glossary/assignments/batch-counts') {
        const urns = jsonRequestBody(options).urns
        batchBodies.push(urns)
        return urns[0] === firstTerm.urn
          ? Promise.resolve({ items: [{ urn: firstTerm.urn, table_asset_count: 3, column_asset_count: 4 }] })
          : pendingNextPage
      }
      if (path.includes('cursor=next-page')) return Promise.resolve(glossaryPage([nextTerm]))
      return Promise.resolve(glossaryPage([firstTerm], 'next-page'))
    })
    const client = { request } as unknown as ApiClient
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><PocGlossaryPage client={client} /></QueryClientProvider>)

    expect(await screen.findByRole('button', { name: 'FirstTerm 적용 테이블 3개 보기' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '용어 더 보기' }))

    await waitFor(() => expect(batchBodies).toHaveLength(2))
    expect(screen.getByRole('button', { name: 'NextTerm 적용 테이블 조회 중' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'FirstTerm 적용 테이블 3개 보기' })).toHaveTextContent('3')
    expect(batchBodies).toEqual([[firstTerm.urn], [nextTerm.urn]])
    expect(batchBodies.every((urns) => urns.length <= 50)).toBe(true)
  })
})

function glossaryTerm(urn: string, name: string) {
  return {
    urn,
    name,
    hierarchical_name: `test.${name}`,
    description: '',
    parent_terms: [],
    child_terms: [],
    hierarchy_kind: 'LEAF_TERM',
    asset_count: null,
    table_asset_count: null,
    column_asset_count: null,
    assets: [],
    relationship_count: 0,
    relationships: [],
    relationships_truncated: false,
  }
}

function glossaryPage(items: ReturnType<typeof glossaryTerm>[], nextCursor: string | null = null) {
  return {
    items,
    total: items.length + (nextCursor ? 1 : 0),
    page: { next_cursor: nextCursor, limit: 50 },
    currentness: {
      source: 'DATAHUB_GMS_LIVE',
      observed_at: '2026-08-29T00:00:00.000Z',
      atomic_snapshot: false,
    },
  }
}

function jsonRequestBody(options?: RequestInit): { urns: string[] } {
  if (typeof options?.body !== 'string') throw new Error('Expected a JSON request body.')
  return JSON.parse(options.body) as { urns: string[] }
}
