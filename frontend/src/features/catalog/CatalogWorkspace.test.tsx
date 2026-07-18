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
  if (path.startsWith('/catalog/assets?')) return Promise.resolve({ items: [asset], page: { limit: 50 }, meta, match_mode: 'ALL' })
  if (path.startsWith('/catalog/facets')) return Promise.resolve({ asset_types: [{ value: 'DATASET', count: 1 }], platforms: [{ value: 'snowflake', count: 1 }], classifications: [{ value: 'INTERNAL', count: 1 }], meta })
  if (path.startsWith('/catalog/tree/')) return Promise.resolve({ items: [], page: { limit: 100 }, meta })
  if (path === `/catalog/assets/${asset.id}`) return Promise.resolve({ ...asset, ownership: [{ owner: { urn: 'urn:li:corpGroup:yield' } }], glossary_terms: [{ term: { urn: 'urn:li:glossaryTerm:wafer' } }], tags: ['trusted'], schema_fields: [{ fieldPath: 'wafer_id', type: 'STRING', description: 'identifier', globalTags: { tags: [{ tag: { name: 'tier:gold' } }] }, glossaryTerms: { terms: [{ term: { name: 'wafer' } }] } }], quality: {}, source_version: 'source-v7' })
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
    expect(request.mock.calls.some(([path]) => String(path).includes('10000'))).toBe(false)
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
  })

  it('opens authorized detail and fetches bounded lineage on demand', async () => {
    const request = vi.fn(defaultRequest)
    render(<CatalogPage client={clientWith(request)} initialQuery="wafer" />)

    fireEvent.click(await screen.findByText('wafer_events'))
    expect(await screen.findByText('source-v7')).toBeInTheDocument()
    expect(screen.getByText('Column metadata')).toBeInTheDocument()
    expect(screen.getAllByText('wafer').length).toBeGreaterThan(0)
    expect(screen.getAllByText('tier:gold').length).toBeGreaterThan(0)
    expect(request.mock.calls.some(([path]) => String(path).includes('/lineage?'))).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: /Lineage/ }))
    expect(await screen.findByText('1 nodes · 0 edges')).toBeInTheDocument()
    await waitFor(() => expect(request.mock.calls.some(([path, options]) => (
      path.includes('/lineage?direction=BOTH&depth=2') && options?.signal instanceof AbortSignal
    ))).toBe(true))
  })
})
