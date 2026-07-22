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
      '검색', '필터', '초기화', 'CSV 저장', 'Excel 저장',
    ])
    expect(within(toolbar as HTMLElement).getByRole('button', { name: '필터' })).toBeInTheDocument()
    expect(within(toolbar as HTMLElement).getByRole('button', { name: '검색 화면 초기화' })).toBeEnabled()
    expect(within(toolbar as HTMLElement).getByRole('button', { name: 'CSV 저장' })).toBeDisabled()
    expect(within(toolbar as HTMLElement).getByRole('button', { name: 'Excel 저장' })).toBeDisabled()
    const topPagination = screen.getByRole('navigation', { name: 'Search Results 상단 페이지 탐색' })
    expect(within(topPagination).getByText('페이지 크기')).toBeInTheDocument()
    expect(within(topPagination).getByRole('combobox', { name: '페이지 크기' })).toBeInTheDocument()
    const bottomPagination = screen.getByRole('navigation', { name: '페이지 탐색' })
    expect(within(bottomPagination).getAllByRole('option').map((option) => option.textContent)).toEqual(['25', '50', '100'])
    expect(within(bottomPagination).queryByRole('option', { name: '전체' })).not.toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: '이전' })).toHaveLength(2)
    expect(screen.getAllByRole('button', { name: '다음' })).toHaveLength(2)
    expect(request.mock.calls.some(([path]) => String(path).includes('10000'))).toBe(false)
  })

  it('keeps every browser page and request within the 100-row server bound', async () => {
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
    const bottomPagination = screen.getByRole('navigation', { name: '페이지 탐색' })
    const pageSize = within(bottomPagination).getByRole('combobox', { name: '페이지 크기' })

    fireEvent.change(pageSize, { target: { value: '100' } })
    expect(await screen.findByText('asset_099')).toBeInTheDocument()
    expect(screen.queryByText('asset_119')).not.toBeInTheDocument()
    await waitFor(() => {
      const assetCalls = request.mock.calls.filter(([path]) => String(path).startsWith('/catalog/assets?'))
      expect(assetCalls).toHaveLength(1)
      expect(assetCalls.every(([path]) => Number(new URL(String(path), 'http://catalog.test').searchParams.get('limit')) <= 100)).toBe(true)
    })

    request.mockClear()
    fireEvent.click(within(bottomPagination).getByRole('button', { name: '다음' }))
    expect(await screen.findByText('asset_119')).toBeInTheDocument()
    expect(screen.queryByText('asset_000')).not.toBeInTheDocument()
    await waitFor(() => {
      const assetCalls = request.mock.calls.filter(([path]) => String(path).startsWith('/catalog/assets?'))
      expect(assetCalls).toHaveLength(1)
      expect(new URL(String(assetCalls[0]?.[0]), 'http://catalog.test').searchParams.get('limit')).toBe('100')
    })
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

    fireEvent.click(within(tree).getByRole('button', { name: /snowflake/ }))
    expect(within(tree).queryByText('analytics')).not.toBeInTheDocument()
    fireEvent.click(within(tree).getByRole('button', { name: /snowflake/ }))
    await within(tree).findByText('analytics')
    expect(request.mock.calls.filter(([path]) => String(path).includes('parent_kind=PLATFORM'))).toHaveLength(2)
  })

  it('caps a retained Resource Tree branch at 200 nodes', async () => {
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      void options
      if (path.includes('parent_kind=ROOT')) return Promise.resolve({ items: [{ id: 'platform-node', kind: 'PLATFORM', label: 'snowflake', asset_count: 400, has_children: true, platform: 'snowflake' }], page: { limit: 100 }, meta })
      if (path.includes('parent_kind=PLATFORM')) {
        const parameters = new URL(path, 'http://catalog.test').searchParams
        const offset = Number(parameters.get('cursor')?.replace('offset-', '') ?? 0)
        return Promise.resolve({
          items: Array.from({ length: 100 }, (_, index) => ({
            id: `database-${offset + index}`,
            kind: 'DATABASE',
            label: `database_${offset + index}`,
            asset_count: 1,
            has_children: false,
            platform: 'snowflake',
            database_name: `database_${offset + index}`,
          })),
          page: { limit: 100, next_cursor: `offset-${offset + 100}` },
          meta,
        })
      }
      return defaultRequest(path)
    })
    render(<CatalogPage client={clientWith(request)} />)

    const tree = await screen.findByRole('complementary', { name: 'Resource Tree' })
    fireEvent.click(await within(tree).findByRole('button', { name: /snowflake/ }))
    fireEvent.click(await within(tree).findByRole('button', { name: /하위 항목 더 보기/ }))

    expect(await within(tree).findByText('메모리 보호를 위해 이 분기의 200개 항목만 표시합니다. 검색을 사용하세요.')).toBeInTheDocument()
    expect(within(tree).getAllByRole('button', { name: /database_/ })).toHaveLength(200)
    expect(within(tree).queryByRole('button', { name: /하위 항목 더 보기/ })).not.toBeInTheDocument()
  })

  it('evicts the least-recently expanded branch after eight retained branches', async () => {
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      void options
      if (path.includes('parent_kind=ROOT')) return Promise.resolve({
        items: Array.from({ length: 9 }, (_, index) => ({
          id: `platform-${index}`, kind: 'PLATFORM', label: `platform_${index}`,
          asset_count: 1, has_children: true, platform: `platform_${index}`,
        })),
        page: { limit: 100 }, meta,
      })
      if (path.includes('parent_kind=PLATFORM')) {
        const platform = new URL(path, 'http://catalog.test').searchParams.get('platform') ?? ''
        return Promise.resolve({
          items: [{ id: `database-${platform}`, kind: 'DATABASE', label: `database_${platform}`,
            asset_count: 1, has_children: false, platform, database_name: 'database' }],
          page: { limit: 100 }, meta,
        })
      }
      return defaultRequest(path)
    })
    render(<CatalogPage client={clientWith(request)} />)

    const tree = await screen.findByRole('complementary', { name: 'Resource Tree' })
    for (let index = 0; index < 9; index += 1) {
      fireEvent.click(await within(tree).findByRole('button', { name: new RegExp(`platform_${index}`) }))
      await within(tree).findByText(`database_platform_${index}`)
    }

    expect(within(tree).queryByText('database_platform_0')).not.toBeInTheDocument()
    expect(within(tree).getByRole('button', { name: /platform_0/ })).toHaveAttribute('aria-expanded', 'false')
    expect(within(tree).getByText('database_platform_8')).toBeInTheDocument()
  })

  it('aborts an evicted in-flight Resource Tree branch before opening the ninth branch', async () => {
    const branchSignals: AbortSignal[] = []
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      if (path.includes('parent_kind=ROOT')) return Promise.resolve({
        items: Array.from({ length: 9 }, (_, index) => ({
          id: `slow-platform-${index}`, kind: 'PLATFORM', label: `slow_platform_${index}`,
          asset_count: 1, has_children: true, platform: `slow_platform_${index}`,
        })),
        page: { limit: 100 }, meta,
      })
      if (path.includes('parent_kind=PLATFORM') && options?.signal) {
        branchSignals.push(options.signal)
        return new Promise((_resolve, reject) => {
          options.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
        })
      }
      return defaultRequest(path)
    })
    render(<CatalogPage client={clientWith(request)} />)

    const tree = await screen.findByRole('complementary', { name: 'Resource Tree' })
    for (let index = 0; index < 9; index += 1) {
      fireEvent.click(await within(tree).findByRole('button', {
        name: new RegExp(`slow_platform_${index}`),
      }))
    }

    await waitFor(() => expect(branchSignals).toHaveLength(9))
    expect(branchSignals[0]?.aborted).toBe(true)
    expect(branchSignals.slice(1).filter((signal) => !signal.aborted)).toHaveLength(8)
    expect(within(tree).getByRole('button', { name: /slow_platform_0/ })).toHaveAttribute(
      'aria-expanded', 'false',
    )
  })

  it('aborts an in-flight descendant branch when its ancestor is collapsed', async () => {
    let branchSignal: AbortSignal | undefined
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      if (path.includes('parent_kind=ROOT')) return Promise.resolve({
        items: [{ id: 'slow-platform', kind: 'PLATFORM', label: 'slow_platform',
          asset_count: 1, has_children: true, platform: 'slow_platform' }],
        page: { limit: 100 }, meta,
      })
      if (path.includes('parent_kind=PLATFORM')) return Promise.resolve({
        items: [{ id: 'slow-database', kind: 'DATABASE', label: 'slow_database',
          asset_count: 1, has_children: true, platform: 'slow_platform', database_name: 'slow' }],
        page: { limit: 100 }, meta,
      })
      if (path.includes('parent_kind=DATABASE') && options?.signal) {
        branchSignal = options.signal
        return new Promise((_resolve, reject) => {
          options.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
        })
      }
      return defaultRequest(path)
    })
    render(<CatalogPage client={clientWith(request)} />)

    const tree = await screen.findByRole('complementary', { name: 'Resource Tree' })
    const platform = await within(tree).findByRole('button', { name: /slow_platform/ })
    fireEvent.click(platform)
    fireEvent.click(await within(tree).findByRole('button', { name: /slow_database/ }))
    await waitFor(() => expect(branchSignal).toBeDefined())
    fireEvent.click(platform)

    expect(branchSignal?.aborted).toBe(true)
    expect(platform).toHaveAttribute('aria-expanded', 'false')
  })

  it('opens an authorized Resource Tree detail without crawling result pages', async () => {
    const treeAsset: CatalogAsset = { ...asset, id: 'tree-asset', name: 'tree_selected_table' }
    const assets = [...Array.from({ length: 50 }, (_, index) => ({
      ...asset,
      id: `first-page-${index}`,
      name: `first_page_${index}`,
    })), treeAsset]
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      void options
      if (path.startsWith('/catalog/assets?')) {
        const parameters = new URL(path, 'http://catalog.test').searchParams
        const offset = Number(parameters.get('cursor')?.replace('offset-', '') ?? 0)
        const limit = Number(parameters.get('limit'))
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
      if (path.includes('parent_kind=ROOT')) return Promise.resolve({ items: [{ id: 'asset-node', kind: 'ASSET', label: treeAsset.name, asset_count: 1, has_children: false, asset: treeAsset }], page: { limit: 100 }, meta })
      if (path === `/catalog/assets/${treeAsset.id}`) return Promise.resolve({ ...treeAsset, ownership: [], glossary_terms: [], tags: [], schema_fields: [], quality: {}, source_version: 'source-v7' })
      return defaultRequest(path)
    })
    render(<CatalogPage client={clientWith(request)} initialQuery="wafer" />)

    const tree = await screen.findByRole('complementary', { name: 'Resource Tree' })
    const assetCallsBeforeSelection = request.mock.calls.filter(([path]) => String(path).startsWith('/catalog/assets?')).length
    fireEvent.click(await within(tree).findByRole('button', { name: /tree_selected_table/ }))
    expect(await screen.findByRole('complementary', { name: '카탈로그 상세' })).toHaveTextContent(treeAsset.name)
    const table = screen.getByRole('table', { name: '카탈로그 검색 결과' })
    expect(table.querySelector('tbody tr.selected')).toBeNull()
    expect(screen.getAllByText('1 페이지 · 현재 50건')).toHaveLength(2)
    expect(request.mock.calls.filter(([path]) => String(path).startsWith('/catalog/assets?'))).toHaveLength(assetCallsBeforeSelection)
    expect(request.mock.calls.some(([path]) => String(path).includes('q=wafer'))).toBe(true)
    expect(request.mock.calls.some(([path]) => String(path).startsWith('/catalog/tree/') && String(path).includes('q='))).toBe(false)
  })

  it('keeps the current result page visible when a Resource Tree target is off-screen', async () => {
    const treeAsset: CatalogAsset = { ...asset, id: 'tree-third-page-asset', name: 'tree_third_page_table' }
    const assets = [...Array.from({ length: 100 }, (_, index) => ({ ...asset, id: `tree-page-${index}`, name: `tree_page_${index}` })), treeAsset]
    const responseFor = (offset: number, limit: number) => {
      const items = assets.slice(offset, offset + limit)
      const nextOffset = offset + items.length
      return { items, page: { limit, ...(nextOffset < assets.length ? { next_cursor: `offset-${nextOffset}` } : {}) }, total: assets.length, meta, match_mode: 'ALL' }
    }
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      void options
      if (path.startsWith('/catalog/assets?')) {
        const parameters = new URL(path, 'http://catalog.test').searchParams
        const offset = Number(parameters.get('cursor')?.replace('offset-', '') ?? 0)
        const limit = Number(parameters.get('limit'))
        return Promise.resolve(responseFor(offset, limit))
      }
      if (path.includes('parent_kind=ROOT')) return Promise.resolve({ items: [{ id: 'asset-node', kind: 'ASSET', label: treeAsset.name, asset_count: 1, has_children: false, asset: treeAsset }], page: { limit: 100 }, meta })
      if (path === `/catalog/assets/${treeAsset.id}`) return Promise.resolve({ ...treeAsset, ownership: [], glossary_terms: [], tags: [], schema_fields: [], quality: {}, source_version: 'source-v7' })
      return defaultRequest(path)
    })
    render(<CatalogPage client={clientWith(request)} initialQuery="wafer" />)

    const tree = await screen.findByRole('complementary', { name: 'Resource Tree' })
    const assetCallsBeforeSelection = request.mock.calls.filter(([path]) => String(path).startsWith('/catalog/assets?')).length
    fireEvent.click(await within(tree).findByRole('button', { name: /tree_third_page_table/ }))
    expect(await screen.findByRole('complementary', { name: '카탈로그 상세' })).toHaveTextContent(treeAsset.name)
    const table = screen.getByRole('table', { name: '카탈로그 검색 결과' })
    expect(table).toHaveTextContent('tree_page_0')
    expect(table).not.toHaveTextContent('tree_page_50')
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(request.mock.calls.filter(([path]) => String(path).startsWith('/catalog/assets?'))).toHaveLength(assetCallsBeforeSelection)
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

    const toolbar = document.querySelector('.catalog-search-toolbar')
    expect(toolbar).not.toBeNull()
    const reset = within(toolbar as HTMLElement).getByRole('button', { name: '검색 화면 초기화' })
    await waitFor(() => expect(reset).toBeEnabled())
    fireEvent.click(reset)
    await waitFor(() => expect(request.mock.calls.some(([path]) => (
      String(path).startsWith('/catalog/assets?')
      && !String(path).includes('database=analytics')
      && !String(path).includes('lifecycle=ACTIVE')
    ))).toBe(true))
  })

  it('opens an authorized Lineage detail without crawling Search Results', async () => {
    const lineageAsset: CatalogAsset = { ...asset, id: 'lineage-asset', name: 'lineage_selected_table' }
    const assets = [...Array.from({ length: 50 }, (_, index) => ({
      ...asset,
      id: `lineage-first-page-${index}`,
      name: `lineage_first_page_${index}`,
    })), lineageAsset]
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      void options
      if (path.startsWith('/catalog/assets?')) {
        const parameters = new URL(path, 'http://catalog.test').searchParams
        const offset = Number(parameters.get('cursor')?.replace('offset-', '') ?? 0)
        const limit = Number(parameters.get('limit'))
        const items = offset === 0 ? [asset, ...assets.slice(0, limit - 1)] : assets.slice(offset, offset + limit)
        const nextOffset = offset + items.length
        return Promise.resolve({
          items,
          page: { limit, ...(nextOffset < assets.length ? { next_cursor: `offset-${nextOffset}` } : {}) },
          total: assets.length,
          meta,
          match_mode: 'ALL',
        })
      }
      if (path === `/catalog/assets/${asset.id}`) return Promise.resolve({ ...asset, ownership: [], glossary_terms: [], tags: [], schema_fields: [], quality: {}, source_version: 'source-v7' })
      if (path === `/catalog/assets/${lineageAsset.id}`) return Promise.resolve({ ...lineageAsset, ownership: [], glossary_terms: [], tags: [], schema_fields: [], quality: {}, source_version: 'source-v7' })
      if (path.includes('/lineage?')) return Promise.resolve({ center_asset_id: asset.id, nodes: [asset, lineageAsset], edges: [{ source_asset_id: asset.id, target_asset_id: lineageAsset.id }], direction: 'BOTH', depth: 2, truncated: false, meta })
      return defaultRequest(path)
    })
    render(<CatalogPage client={clientWith(request)} initialQuery="wafer" />)

    fireEvent.click(await screen.findByText('wafer_events'))
    fireEvent.click(await screen.findByRole('tab', { name: 'Lineage' }))
    const assetCallsBeforeSelection = request.mock.calls.filter(([path]) => String(path).startsWith('/catalog/assets?')).length
    fireEvent.click(await screen.findByRole('button', { name: `${lineageAsset.name} 선택` }))
    const table = screen.getByRole('table', { name: '카탈로그 검색 결과' })
    expect(await screen.findByRole('complementary', { name: '카탈로그 상세' })).toHaveTextContent(lineageAsset.name)
    expect(table.querySelector('tbody tr.selected')).toBeNull()
    expect(request.mock.calls.filter(([path]) => String(path).startsWith('/catalog/assets?'))).toHaveLength(assetCallsBeforeSelection)
  })

  it('resets the query, filters, result selection, and Authorized Detail', async () => {
    const request = vi.fn(defaultRequest)
    render(<CatalogPage client={clientWith(request)} initialQuery="wafer" />)

    fireEvent.click(await screen.findByText('wafer_events'))
    expect(await screen.findByRole('complementary', { name: '카탈로그 상세' })).toBeInTheDocument()
    const toolbar = document.querySelector('.catalog-search-toolbar')
    expect(toolbar).not.toBeNull()
    fireEvent.click(within(toolbar as HTMLElement).getByRole('button', { name: '검색 화면 초기화' }))

    await waitFor(() => expect(screen.getByLabelText('데이터셋 이름이나 설명 검색')).toHaveValue(''))
    expect(screen.queryByRole('complementary', { name: '카탈로그 상세' })).not.toBeInTheDocument()
    expect(screen.getByRole('table', { name: '카탈로그 검색 결과' }).querySelector('tbody tr.selected')).toBeNull()
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

  it('keeps wide schema metadata on bounded server pages', async () => {
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      void options
      if (path === `/catalog/assets/${asset.id}` || path.startsWith(`/catalog/assets/${asset.id}?`)) {
        const parameters = new URL(path, 'http://catalog.test').searchParams
        const offset = Number(parameters.get('field_offset') ?? 0)
        const fields = Array.from({ length: 100 }, (_, index) => ({
          fieldPath: `field_${String(offset + index).padStart(3, '0')}`,
          nativeDataType: 'STRING',
        }))
        return Promise.resolve({
          ...asset, ownership: [], glossary_terms: [], tags: [], schema_fields: fields,
          schema_fields_total: 250, schema_fields_available: 250, schema_fields_truncated: false,
          schema_fields_total_exact: true,
          schema_fields_offset: offset, schema_fields_limit: 100,
          schema_fields_has_more: offset + fields.length < 250, quality: {},
          projection_source_version: 'projection-v7', source_version: 'source-v7',
        })
      }
      return defaultRequest(path)
    })
    render(<CatalogPage client={clientWith(request)} />)

    fireEvent.click(await screen.findByText('wafer_events'))
    expect(await screen.findByText('field_099')).toBeInTheDocument()
    const detail = screen.getByRole('complementary', { name: '카탈로그 상세' })
    expect(within(detail).getByRole('table', { name: '스키마 필드' }).querySelectorAll('tbody tr'))
      .toHaveLength(100)
    fireEvent.click(within(detail).getByRole('button', { name: '다음 컬럼' }))

    expect(await within(detail).findByText('field_100')).toBeInTheDocument()
    expect(within(detail).queryByText('field_000')).not.toBeInTheDocument()
    expect(request.mock.calls.some(([path, options]) => (
      path === `/catalog/assets/${asset.id}?field_offset=100&field_limit=100&field_source_version=source-v7`
      && options?.signal instanceof AbortSignal
    ))).toBe(true)
  })

  it('uses muted dashes for absent result and authorized-detail metadata', async () => {
    const missing: CatalogAsset = {
      ...asset,
      id: '00000000-0000-4000-8000-000000000202',
      name: 'missing_metadata',
      description: undefined,
      platform: undefined,
      database_name: undefined,
      schema_name: undefined,
      owner: undefined,
      domain: undefined,
      tags: [],
      terms: [],
      created_at: undefined,
      matches: [],
    }
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      void options
      if (path.startsWith('/catalog/assets?')) return Promise.resolve({ items: [missing], page: { limit: 50 }, total: 1, meta, match_mode: 'ALL' })
      if (path === `/catalog/assets/${missing.id}`) return Promise.resolve({ ...missing, ownership: [], glossary_terms: [], tags: [], schema_fields: [], quality: {}, source_version: 'source-v7' })
      return defaultRequest(path)
    })
    render(<CatalogPage client={clientWith(request)} />)

    const table = await screen.findByRole('table', { name: '카탈로그 검색 결과' })
    expect(within(table).getAllByLabelText('정보 없음')).toHaveLength(9)
    fireEvent.click(screen.getByText('missing_metadata'))
    const detail = await screen.findByRole('complementary', { name: '카탈로그 상세' })
    expect(within(detail).getAllByLabelText('정보 없음')).toHaveLength(11)
  })
})
