import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient, RequestOptions } from '../../api/client'
import type {
  KnowledgeAssetOperationalDetail,
  KnowledgeAssetPage,
  KnowledgeAssetSummary,
  KnowledgeRelease,
  KnowledgeSnapshot,
} from '../../api/types'
import { KnowledgeRegistry } from './KnowledgeRegistry'

const asset: KnowledgeAssetSummary = {
  id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3c0',
  slug: 'finance-terms',
  name: 'Finance Terms',
  graph_type: 'DOMAIN',
  status: 'PUBLISHED',
  classification: 'INTERNAL',
  domain_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3c1',
  domain_name: 'Finance',
  creator_name: 'SUA Han',
  creator_email: 'sua.han@example.com',
  editor_name: 'SUA Han',
  editor_email: 'sua.han@example.com',
  active_studio_release_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3c6',
  active_studio_release_no: 3,
  active_release_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3c2',
  active_release_no: 2,
  class_count: 4,
  property_count: 8,
  relationship_count: 3,
  binding_count: 1,
  source_count: 1,
  node_count: 2,
  edge_count: 1,
  projection_state: 'SHADOW_VERIFIED',
  created_at: '2026-07-27T10:00:00Z',
  updated_at: '2026-07-28T10:00:00Z',
  version: 4,
  delivery_policy: null,
}

const detail: KnowledgeAssetOperationalDetail = {
  asset,
  schema_elements: [],
  bindings: [],
  projections: [],
}

const currentRelease: KnowledgeRelease = {
  id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3c2',
  graph_id: asset.id,
  release_no: 2,
  ontology_version_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3c4',
  content_hash: 'a'.repeat(64),
  node_count: 2,
  edge_count: 1,
  published_by: '019fa57b-52de-74c0-9f5e-06ae7b1bf3c5',
  published_at: '2026-07-28T10:00:00Z',
}

const historicalRelease: KnowledgeRelease = {
  ...currentRelease,
  id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3c3',
  release_no: 1,
  node_count: 1,
  edge_count: 0,
  published_at: '2026-07-27T10:00:00Z',
}

function snapshot(release: KnowledgeRelease): KnowledgeSnapshot {
  return {
    release,
    nodes: [],
    edges: [],
    filtered: false,
  }
}

describe('KnowledgeRegistry', () => {
  it('edits, archives, and focuses immutable release history through typed APIs', async () => {
    let graphReads = 0
    const request = vi.fn((path: string, options?: RequestOptions) => {
      if (path.startsWith('/knowledge/registry/assets?')) {
        graphReads += 1
        return Promise.resolve({
          items: graphReads === 1 ? [asset] : [],
          next_cursor: null,
          limit: 25,
        } satisfies KnowledgeAssetPage)
      }
      if (path === `/knowledge/registry/assets/${asset.id}/detail`) {
        return Promise.resolve(detail)
      }
      if (path.endsWith('/releases')) {
        return Promise.resolve([currentRelease, historicalRelease])
      }
      if (path.includes(`/releases/${currentRelease.id}/snapshot`)) {
        return Promise.resolve(snapshot(currentRelease))
      }
      if (path.includes(`/releases/${historicalRelease.id}/snapshot`)) {
        return Promise.resolve(snapshot(historicalRelease))
      }
      if (path.endsWith(`/graphs/${asset.id}/archive`) && options?.method === 'POST') {
        return Promise.resolve({ ...asset, status: 'ARCHIVED', version: 5 })
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`))
    })
    const client = { request } as unknown as ApiClient
    const onEdit = vi.fn()

    render(
      <KnowledgeRegistry
        client={client}
        onCreate={vi.fn()}
        onEdit={onEdit}
      />,
    )

    await screen.findByText('Finance Terms')
    fireEvent.click(screen.getByRole('button', { name: 'Finance Terms 에셋 편집' }))
    expect(onEdit).toHaveBeenCalledWith(asset.id)

    fireEvent.click(screen.getByText('Finance Terms'))
    const drawer = await screen.findByRole('complementary', {
      name: 'Finance Terms 지식 에셋 상세',
    })
    expect(await within(drawer).findByText('CURRENT')).toBeInTheDocument()
    fireEvent.click(within(drawer).getByRole('button', { name: '미리보기' }))
    await waitFor(() => expect(request).toHaveBeenCalledWith(
      expect.stringContaining(`/releases/${historicalRelease.id}/snapshot`),
      expect.objectContaining({ cache: 'no-store' }),
    ))
    expect(within(drawer).getByText('Release v1')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '에셋 상세 닫기' }))
    fireEvent.click(screen.getByRole('button', { name: 'Finance Terms 에셋 삭제' }))
    const dialog = await screen.findByRole('dialog', { name: '지식 자산 아카이빙' })
    expect(within(dialog).getByText(/정말 이 지식 자산을 삭제\/아카이빙/)).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: '아카이빙' }))

    await waitFor(() => expect(request).toHaveBeenCalledWith(
      `/knowledge/graphs/${asset.id}/archive`,
      expect.objectContaining({
        method: 'POST',
        ifMatch: '"4"',
      }),
    ))
    await waitFor(() => expect(graphReads).toBe(2))
  })
})
