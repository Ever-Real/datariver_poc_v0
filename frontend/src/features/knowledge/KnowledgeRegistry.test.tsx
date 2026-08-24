import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient, RequestOptions } from '../../api/client'
import type {
  KnowledgeAssetOperationalDetail,
  KnowledgeAssetPage,
  KnowledgeAssetSummary,
  KnowledgeAssetVersionHistoryPage,
  KnowledgeRelease,
  KnowledgeSnapshot,
} from '../../api/types'
import { KnowledgeRegistry } from './KnowledgeRegistry'

const asset: KnowledgeAssetSummary = {
  id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3c0',
  slug: 'finance-terms',
  name: 'Finance Terms',
  description: '재무 용어 지식 그래프',
  display_version: 3,
  graph_type: 'DOMAIN',
  status: 'ACTIVE',
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

const versionHistory: KnowledgeAssetVersionHistoryPage = {
  items: [
    {
      id: asset.active_studio_release_id!,
      kind: 'STUDIO_RELEASE',
      version_label: 'T v3',
      title: 'Finance schema',
      status: 'ACTIVE',
      author_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3d0',
      author_name: 'Schema Author',
      author_email: 'author@example.com',
      reviewed_by: '019fa57b-52de-74c0-9f5e-06ae7b1bf3d1',
      reviewer_name: 'Schema Reviewer',
      reviewer_email: 'reviewer@example.com',
      published_by: '019fa57b-52de-74c0-9f5e-06ae7b1bf3d2',
      publisher_name: 'Schema Publisher',
      publisher_email: 'publisher@example.com',
      created_at: '2026-07-28T09:00:00Z',
      is_current: true,
      studio_release_id: asset.active_studio_release_id,
      instance_release_id: null,
      changeset_id: null,
      content_hash: 'c'.repeat(64),
      node_count: null,
      edge_count: null,
    },
    {
      id: currentRelease.id,
      kind: 'INSTANCE_RELEASE',
      version_label: 'A v2',
      title: null,
      status: 'PUBLISHED',
      author_id: currentRelease.published_by,
      author_name: 'Instance Author',
      author_email: 'instance@example.com',
      reviewed_by: null,
      reviewer_name: null,
      reviewer_email: null,
      published_by: currentRelease.published_by,
      publisher_name: 'Instance Publisher',
      publisher_email: 'publisher@example.com',
      created_at: currentRelease.published_at,
      is_current: true,
      studio_release_id: null,
      instance_release_id: currentRelease.id,
      changeset_id: null,
      content_hash: currentRelease.content_hash,
      node_count: currentRelease.node_count,
      edge_count: currentRelease.edge_count,
    },
    {
      id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3e0',
      kind: 'CHANGESET',
      version_label: 'Changeset v4',
      title: 'Finance enrichment',
      status: 'PUBLISHED',
      author_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3e1',
      author_name: 'Changeset Author',
      author_email: 'changeset@example.com',
      reviewed_by: '019fa57b-52de-74c0-9f5e-06ae7b1bf3e2',
      reviewer_name: 'Changeset Reviewer',
      reviewer_email: 'reviewer@example.com',
      published_by: '019fa57b-52de-74c0-9f5e-06ae7b1bf3e3',
      publisher_name: 'Changeset Publisher',
      publisher_email: 'publisher@example.com',
      created_at: '2026-07-28T08:00:00Z',
      is_current: false,
      studio_release_id: null,
      instance_release_id: currentRelease.id,
      changeset_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3e0',
      content_hash: null,
      node_count: null,
      edge_count: null,
    },
    {
      id: historicalRelease.id,
      kind: 'INSTANCE_RELEASE',
      version_label: 'A v1',
      title: null,
      status: 'HISTORICAL',
      author_id: historicalRelease.published_by,
      author_name: 'Historical Author',
      author_email: 'historical@example.com',
      reviewed_by: null,
      reviewer_name: null,
      reviewer_email: null,
      published_by: historicalRelease.published_by,
      publisher_name: 'Historical Publisher',
      publisher_email: 'publisher@example.com',
      created_at: historicalRelease.published_at,
      is_current: false,
      studio_release_id: null,
      instance_release_id: historicalRelease.id,
      changeset_id: null,
      content_hash: historicalRelease.content_hash,
      node_count: historicalRelease.node_count,
      edge_count: historicalRelease.edge_count,
    },
  ],
  next_cursor: null,
  limit: 50,
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
      if (path === `/knowledge/registry/assets/${asset.id}/versions?limit=50`) {
        return Promise.resolve(versionHistory)
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
        canManage
        canArchive
      />,
    )

    await screen.findByText('Finance Terms')
    expect(screen.getAllByRole('columnheader').map((header) => header.textContent)).toEqual([
      'No', '지식그래프명', 'Type', 'Source', 'Default', 'Version', 'Nodes / Edges', 'Refresh',
      '설명', '최근 수정일', '생성자', '최근 수정자', '편집',
    ])
    expect(screen.getByText('재무 용어 지식 그래프')).toBeInTheDocument()
    expect(screen.getByText('v3')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Finance Terms 에셋 편집' }))
    expect(onEdit).toHaveBeenCalledWith(asset.id, asset.status)

    fireEvent.click(screen.getByText('Finance Terms'))
    const drawer = await screen.findByRole('complementary', {
      name: 'Finance Terms 지식 에셋 상세',
    })
    expect(await within(drawer).findAllByText('CURRENT')).toHaveLength(2)
    expect(within(drawer).getByText('T v3')).toBeInTheDocument()
    expect(within(drawer).getByText('Changeset v4')).toBeInTheDocument()
    expect(within(drawer).getByText('검토 Schema Reviewer')).toBeInTheDocument()
    expect(within(drawer).getByText('발행 Changeset Publisher')).toBeInTheDocument()
    fireEvent.click(within(drawer).getByRole('button', { name: '미리보기' }))
    await waitFor(() => expect(request).toHaveBeenCalledWith(
      expect.stringContaining(`/releases/${historicalRelease.id}/snapshot`),
      expect.objectContaining({ cache: 'no-store' }),
    ))
    expect(within(drawer).getByText('Release v1')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '에셋 상세 닫기' }))
    fireEvent.click(screen.getByRole('button', { name: 'Finance Terms 에셋 아카이빙' }))
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

  it('shows an actionable empty state only to Knowledge managers', async () => {
    const client = {
      request: vi.fn().mockResolvedValue({ items: [], next_cursor: null, limit: 25 }),
    } as unknown as ApiClient
    const onCreate = vi.fn()
    const { rerender } = render(
      <KnowledgeRegistry client={client} onCreate={onCreate} onEdit={vi.fn()} />,
    )
    expect(await screen.findByText('등록된 지식 에셋이 없습니다')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /일반 에셋 추가/ })).not.toBeInTheDocument()
    expect(screen.getByText(/현재 계정은 레지스트리를 조회할 수 있지만/)).toBeInTheDocument()

    rerender(
      <KnowledgeRegistry client={client} onCreate={onCreate} onEdit={vi.fn()} canManage />,
    )
    const normalAdds = await screen.findAllByRole('button', { name: /일반 에셋 추가/ })
    const metadataAdds = await screen.findAllByRole('button', { name: /Metadata Lineage 생성/ })
    const glossaryAdds = await screen.findAllByRole('button', { name: /Data Glossary 생성/ })

    const normalAdd = normalAdds.at(0)
    const metadataAdd = metadataAdds.at(0)
    const glossaryAdd = glossaryAdds.at(0)

    if (!normalAdd || !metadataAdd || !glossaryAdd) {
      throw new Error('expected all three create actions')
    }

    fireEvent.click(normalAdd)
    expect(onCreate).toHaveBeenCalledWith()

    fireEvent.click(metadataAdd)
    expect(onCreate).toHaveBeenCalledWith('metadata-lineage')

    fireEvent.click(glossaryAdd)
    expect(onCreate).toHaveBeenCalledWith('data-glossary')
  })

  it('shows the admin-only managed V2 snapshot and typed graph quality receipt', async () => {
    const managed: KnowledgeAssetSummary = {
      ...asset,
      id: '01a02d2a-f90d-74fe-bd96-aa596276cb87',
      name: 'Metadata Master Graph',
      graph_type: 'METADATA_MASTER',
      status: 'READY',
      managed: true,
      source: 'DataHub',
      is_default: true,
      active_release_id: 'k9-stage-v2',
      active_projection: 'k9-stage-v2',
      graph_model_version: 2,
      source_snapshot_id: '1'.repeat(64),
      source_snapshot_observed_at: '2026-08-24T00:00:00.000Z',
      source_datahub_version: 'v1.6.0',
      source_datahub_commit: 'source-commit',
      semantic_index_status: 'READY',
      semantic_index_generation: '2'.repeat(64),
      refresh_mode: 'DAILY',
      last_result: 'SUCCESS',
      quality_metrics: {
        entity_count_by_type: { 'class.table': 2, 'class.tag': 1 },
        relation_count_by_type: { 'rel.table_has_tag': 2 },
        explicit_edge_count: 2,
        inferred_edge_count: 0,
        orphan_node_count: 0,
        duplicate_node_count: 0,
        duplicate_edge_count: 0,
        average_degree: 1.3333,
        maximum_degree: 2,
        top_hubs: [],
        pairwise_clique_count: 0,
        semantic_candidate_count: 0,
        unit_explicit_count: 0,
        unit_inferred_count: 0,
        lineage_table_edge_count: 0,
        lineage_column_edge_count: 0,
        reconciliation: {
          baseline_available: true,
          nodes: { added: 1, removed: 0, changed: 2 },
          edges: { added: 2, removed: 0, changed: 0 },
          stale_entity_count: 0,
          previous_source_snapshot_id: '3'.repeat(64),
        },
      },
    }
    const request = vi.fn((path: string) => {
      if (path.startsWith('/knowledge/registry/assets?')) {
        return Promise.resolve({ items: [managed], next_cursor: null, limit: 25 })
      }
      if (path === `/knowledge/graphs/${managed.id}/releases`) return Promise.resolve([])
      if (path === `/knowledge/registry/assets/${managed.id}/detail`) {
        return Promise.resolve({ asset: managed, schema_elements: [], bindings: [], projections: [] })
      }
      if (path === `/knowledge/registry/assets/${managed.id}/versions?limit=50`) {
        return Promise.resolve({ items: [], next_cursor: null, limit: 50 })
      }
      if (path.includes(`/knowledge/graphs/${managed.id}/releases/${managed.active_release_id}/snapshot`)) {
        return Promise.resolve({
          release: currentRelease,
          nodes: [], edges: [], filtered: false,
          bounds: {
            root_node_id: null, maximum_nodes: 60, maximum_edges: 120, maximum_hops: 1,
            returned_nodes: 0, returned_edges: 0, total_authorized_nodes: 0,
            total_authorized_edges: 0, truncated: false, available_node_types: [],
            available_edge_types: [],
          },
        })
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`))
    })
    render(<KnowledgeRegistry client={{ request } as unknown as ApiClient} onCreate={vi.fn()} onEdit={vi.fn()} />)
    fireEvent.click(await screen.findByText('Metadata Master Graph'))
    const drawer = await screen.findByRole('complementary', { name: 'Metadata Master Graph 지식 에셋 상세' })
    expect(within(drawer).getByText('Graph Model')).toBeInTheDocument()
    expect(within(drawer).getByText('v2')).toBeInTheDocument()
    expect(within(drawer).getByText('class.table: 2 · class.tag: 1')).toBeInTheDocument()
    expect(within(drawer).getByText('rel.table_has_tag: 2')).toBeInTheDocument()
    expect(within(drawer).getByText('Nodes 1 / 0 / 2 · Edges 2 / 0 / 0')).toBeInTheDocument()
  })
})
