import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient, RequestOptions } from '../../api/client'
import type { CatalogAsset } from '../../api/types'
import { CatalogPage } from './CatalogPage'

const meta = {
  observed_at: '2026-07-17T00:00:00Z',
  projection_version: 7,
  policy_version: 'builtin-v1',
}

const asset: CatalogAsset = {
  id: '00000000-0000-4000-8000-000000000201',
  external_urn: 'urn:li:dataset:wafer-events',
  asset_type: 'DATASET',
  name: 'wafer_events',
  description: 'yield evidence',
  platform: 'snowflake',
  database_name: 'analytics',
  schema_name: 'manufacturing',
  owner: 'urn:li:corpGroup:yield',
  domain: 'urn:li:domain:manufacturing',
  tags: ['tier:gold'],
  terms: ['urn:li:glossaryTerm:wafer'],
  created_at: '2026-07-17T00:00:00Z',
  classification: 'INTERNAL',
  lifecycle: 'ACTIVE',
  observed_at: meta.observed_at,
  matches: [
    { field: 'NAME', text: 'wafer_events', matched_terms: ['wafer'] },
    { field: 'DESCRIPTION', text: 'yield evidence', matched_terms: ['yield'] },
  ],
}

function clientWith(request: (path: string, options?: RequestOptions) => Promise<unknown>): ApiClient {
  return { request: vi.fn(request) } as unknown as ApiClient
}

function defaultRequest(path: string, options?: RequestOptions): Promise<unknown> {
  void options
  if (path.startsWith('/catalog/assets?')) return Promise.resolve({ items: [asset], page: { limit: 50 }, total: 1, meta, match_mode: 'ALL' })
  if (path.startsWith('/catalog/facets')) return Promise.resolve({
    asset_types: [{ value: 'DATASET', count: 1 }],
    platforms: [{ value: 'snowflake', count: 1 }],
    databases: [{ value: 'analytics', count: 1 }],
    schemas: [{ value: 'manufacturing', count: 1 }],
    domains: [{ value: 'urn:li:domain:manufacturing', count: 1 }],
    classifications: [{ value: 'INTERNAL', count: 1 }],
    lifecycles: [{ value: 'ACTIVE', count: 1 }],
    meta,
  })
  if (path.startsWith('/catalog/tree/')) return Promise.resolve({ items: [], page: { limit: 100 }, meta })
  if (path === `/catalog/assets/${asset.id}`) return Promise.resolve({ ...asset, ownership: [{ owner: { urn: 'urn:li:corpGroup:yield' } }], glossary_terms: [{ term: { urn: 'urn:li:glossaryTerm:wafer' } }], tags: ['trusted'], schema_fields: [{ fieldPath: 'wafer_id', type: 'STRING', description: 'identifier', globalTags: { tags: [{ tag: { name: 'tier:gold' } }] }, glossaryTerms: { terms: [{ term: { name: 'wafer' } }] } }], quality: {}, source_version: 'source-v7' })
  if (path === `/catalog/assets/${asset.id}/datahub-lineage-embed`) return Promise.resolve({ state: 'AVAILABLE', url: 'https://datahub.example.test/dataset/wafer-events/Lineage' })
  if (path.includes('/lineage?')) return Promise.resolve({ center_asset_id: asset.id, nodes: [asset], edges: [], direction: 'BOTH', depth: 2, truncated: false, meta })
  return Promise.reject(new Error(`Unexpected request: ${path}`))
}

describe('catalog workspace', () => {
  it('renders dense server results and plain-text ALL keyword fragments', async () => {
    const request = vi.fn(defaultRequest)
    const client = { request } as unknown as ApiClient
    render(<CatalogPage client={client} initialQuery="wafer yield" />)

    expect(await screen.findByText('wafer_events')).toBeInTheDocument()
    expect(screen.getByText(/ALL keywords/)).toBeInTheDocument()
    expect(screen.getAllByText('wafer').some((node) => node.tagName === 'MARK')).toBe(true)
    expect(screen.getAllByText('yield').some((node) => node.tagName === 'MARK')).toBe(true)
    expect(screen.getByText('urn:li:corpGroup:yield')).toBeInTheDocument()
    expect(screen.getByText('urn:li:domain:manufacturing')).toBeInTheDocument()
    expect(screen.getAllByText('tier:gold').length).toBeGreaterThan(0)
    expect(screen.getByLabelText('wafer_events Terms')).toHaveTextContent('urn:li:glossaryTerm:wafer')
    expect(screen.getByLabelText('wafer_events Tags')).toHaveTextContent('tier:gold')
    const table = screen.getByRole('table', { name: '카탈로그 검색 결과' })
    const headings = within(table).getAllByRole('columnheader').map((heading) => heading.textContent)
    expect(headings.indexOf('Terms ↕')).toBeLessThan(headings.indexOf('Owner ↕'))
    expect(headings.indexOf('Tags ↕')).toBeLessThan(headings.indexOf('Owner ↕'))
    expect(table.closest('.dense-table-frame')).toHaveAttribute('aria-label', '카탈로그 검색 결과 스크롤 영역')
    expect(Number.parseFloat(table.style.width)).toBeGreaterThan(840)
    const toolbar = document.querySelector('.catalog-search-toolbar')
    expect(toolbar).not.toBeNull()
    expect(within(toolbar as HTMLElement).getAllByRole('button').map((button) => button.textContent)).toEqual([
      '검색', '필터', 'CSV 저장', 'Excel 저장',
    ])
    expect(within(toolbar as HTMLElement).getByRole('button', { name: '필터' })).toBeInTheDocument()
    expect(within(toolbar as HTMLElement).getByRole('button', { name: 'CSV 저장' })).toBeDisabled()
    expect(within(toolbar as HTMLElement).getByRole('button', { name: 'Excel 저장' })).toBeDisabled()
    expect(within(screen.getByRole('combobox', { name: '페이지 크기' })).getByRole('option', { name: '전체' })).toBeInTheDocument()
    expect(request.mock.calls.some(([path]) => String(path).includes('10000'))).toBe(false)
  })

  it('builds 200, 500, 1000, and all logical pages from the bounded 100-row server cursor', async () => {
    const assets = Array.from({ length: 120 }, (_, index): CatalogAsset => ({
      ...asset,
      id: `asset-${index}`,
      name: `asset_${String(index).padStart(3, '0')}`,
      terms: index === 0 ? ['term:first'] : [],
      tags: index === 0 ? ['tag:first'] : [],
    }))
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      void options
      if (path.startsWith('/catalog/assets?')) {
        const parameters = new URL(path, 'http://catalog.test').searchParams
        const limit = Number(parameters.get('limit'))
        const offset = Number(parameters.get('cursor')?.replace('offset-', '') ?? 0)
        const items = assets.slice(offset, offset + limit)
        const nextOffset = offset + items.length
        return Promise.resolve({
          items,
          page: { limit, ...(nextOffset < assets.length ? { next_cursor: `offset-${nextOffset}` } : {}) },
          total: assets.length,
          meta,
          match_mode: 'ALL',
        })
      }
      return defaultRequest(path)
    })
    render(<CatalogPage client={clientWith(request)} />)
    await screen.findByText('asset_049')
    request.mockClear()

    fireEvent.change(screen.getByRole('combobox', { name: '페이지 크기' }), { target: { value: '200' } })
    expect(await screen.findByText('asset_119')).toBeInTheDocument()
    await waitFor(() => {
      const assetCalls = request.mock.calls.filter(([path]) => String(path).startsWith('/catalog/assets?'))
      expect(assetCalls).toHaveLength(2)
      expect(assetCalls.every(([path]) => Number(new URL(String(path), 'http://catalog.test').searchParams.get('limit')) <= 100)).toBe(true)
    })

    for (const logicalSize of ['500', '1000']) {
      request.mockClear()
      fireEvent.change(screen.getByRole('combobox', { name: '페이지 크기' }), { target: { value: logicalSize } })
      await waitFor(() => {
        const assetCalls = request.mock.calls.filter(([path]) => String(path).startsWith('/catalog/assets?'))
        expect(assetCalls).toHaveLength(2)
        expect(assetCalls.every(([path]) => Number(new URL(String(path), 'http://catalog.test').searchParams.get('limit')) <= 100)).toBe(true)
      })
    }

    request.mockClear()
    fireEvent.change(screen.getByRole('combobox', { name: '페이지 크기' }), { target: { value: '0' } })
    expect(await screen.findByText('전체 · 현재 120건')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '다음' })).toBeDisabled()
    await waitFor(() => expect(request.mock.calls.filter(([path]) => String(path).startsWith('/catalog/assets?'))).toHaveLength(2))
  })

  it('loads canonical tree branches only when a parent is expanded', async () => {
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      void options
      if (path.includes('parent_kind=ROOT')) return Promise.resolve({ items: [{ id: 'platform-node', kind: 'PLATFORM', label: 'snowflake', asset_count: 1, has_children: true, platform: 'snowflake' }], page: { limit: 100 }, meta })
      if (path.includes('parent_kind=PLATFORM')) return Promise.resolve({ items: [{ id: 'database-node', kind: 'DATABASE', label: 'analytics', asset_count: 1, has_children: true, platform: 'snowflake', database_name: 'analytics' }], page: { limit: 100 }, meta })
      return defaultRequest(path)
    })
    render(<CatalogPage client={clientWith(request)} />)

    const tree = await screen.findByRole('complementary', { name: 'Resource Tree' })
    fireEvent.click(await within(tree).findByRole('button', { name: /snowflake/ }))
    await within(tree).findByText('analytics')
    expect(request.mock.calls.some(([path, options]) => (
      path.includes('parent_kind=PLATFORM') && options?.signal instanceof AbortSignal
    ))).toBe(true)
    expect(request.mock.calls.filter(([path]) => String(path).includes('parent_kind=PLATFORM'))).toHaveLength(1)
    expect(request.mock.calls.some(([path]) => String(path).includes('platform=snowflake'))).toBe(true)
  })

  it('keeps legacy search targets and bounded facet filtering in a responsive popover', async () => {
    const request = vi.fn(defaultRequest)
    render(<CatalogPage client={clientWith(request)} initialQuery="wafer" />)

    fireEvent.click(await screen.findByRole('button', { name: '필터' }))
    expect(screen.getByRole('dialog', { name: '상세 검색 필터' })).toBeInTheDocument()
    expect(screen.getByLabelText('Search in 전체')).toBeChecked()
    fireEvent.change(screen.getByLabelText('Database'), { target: { value: 'analytics' } })
    fireEvent.change(screen.getByLabelText('Lifecycle'), { target: { value: 'ACTIVE' } })

    await waitFor(() => expect(request.mock.calls.some(([path]) => (
      String(path).includes('database=analytics') && String(path).includes('lifecycle=ACTIVE')
    ))).toBe(true))
  })

  it('opens authorized detail and fetches bounded lineage on demand', async () => {
    const request = vi.fn(defaultRequest)
    render(<CatalogPage client={clientWith(request)} initialQuery="wafer" />)

    fireEvent.click(await screen.findByText('wafer_events'))
    expect(await screen.findByText('Created Date')).toBeInTheDocument()
    expect(screen.queryByText('source-v7')).not.toBeInTheDocument()
    const properties = document.querySelector('.catalog-detail-properties')
    expect(properties).toHaveTextContent('Platform')
    expect(properties).toHaveTextContent('Database')
    expect(properties).toHaveTextContent('Schema')
    expect(properties).toHaveTextContent('Domain')
    expect(properties).toHaveTextContent('Owner')
    expect(properties).toHaveTextContent('Rows')
    expect(properties).toHaveTextContent('Size')
    expect(properties).toHaveTextContent('Created Date')
    expect(screen.getByText('Column metadata')).toBeInTheDocument()
    expect(screen.getAllByText('wafer').length).toBeGreaterThan(0)
    expect(screen.getAllByText('tier:gold').length).toBeGreaterThan(0)
    expect(screen.getByLabelText('테이블 Tags')).toBeInTheDocument()
    expect(screen.getByLabelText('wafer_id Tags')).toBeInTheDocument()
    const identity = document.querySelector('.catalog-detail-identity')
    expect(identity).toHaveTextContent('DATASET')
    expect(identity).toHaveTextContent('INTERNAL')
    expect(identity?.querySelector('.catalog-detail-urn')).toHaveTextContent(asset.external_urn)
    const resizer = screen.getByRole('button', { name: '상세 패널 너비 조절' })
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1_500 })
    fireEvent.keyDown(resizer, { key: 'ArrowLeft' })
    expect(document.querySelector('.catalog-workspace')).toHaveStyle('--catalog-detail-width: 574px')
    const detailScroll = document.querySelector<HTMLElement>('.catalog-detail-scroll')
    expect(detailScroll).not.toBeNull()
    expect(detailScroll).not.toContainElement(resizer)
    Object.defineProperty(detailScroll as HTMLElement, 'scrollTop', { configurable: true, value: 160 })
    fireEvent.pointerDown(resizer, { clientX: 900, pointerId: 7 })
    fireEvent.pointerMove(window, { clientX: 860, pointerId: 7 })
    fireEvent.pointerUp(window, { clientX: 860, pointerId: 7 })
    expect(document.querySelector('.catalog-workspace')).toHaveStyle('--catalog-detail-width: 614px')
    expect(request.mock.calls.some(([path]) => String(path).includes('/lineage?'))).toBe(false)
    fireEvent.click(screen.getByRole('tab', { name: 'Lineage' }))
    expect(await screen.findByText('1 nodes · 0 edges')).toBeInTheDocument()
    await waitFor(() => expect(request.mock.calls.some(([path, options]) => (
      path.includes('/lineage?direction=BOTH&depth=2') && options?.signal instanceof AbortSignal
    ))).toBe(true))
    expect(screen.getByRole('button', { name: 'wafer_events 선택' })).toHaveAttribute('title', 'wafer_events 상세 정보 열기')
    expect(screen.getByRole('complementary', { name: '카탈로그 상세' })).toHaveTextContent('wafer_events')
  })
})
