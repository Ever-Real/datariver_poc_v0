import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient, RequestOptions } from '../../api/client'
import type {
  KnowledgeAssetOperationalDetail,
  KnowledgeAssetPage,
  KnowledgeAssetSummary,
  KnowledgeChangeSet,
} from '../../api/types'
import { KnowledgeAssetInstancePanel } from './KnowledgeAssetInstancePanel'

const asset: KnowledgeAssetSummary = {
  id: '019fa57b-52de-74c0-9f5e-06ae7b1e0001',
  slug: 'confidential_asset',
  name: 'Confidential Asset',
  graph_type: 'CURATED_KNOWLEDGE',
  status: 'PUBLISHED',
  classification: 'CONFIDENTIAL',
  domain_id: null,
  domain_name: null,
  creator_name: null,
  creator_email: null,
  editor_name: null,
  editor_email: null,
  active_studio_release_id: '019fa57b-52de-74c0-9f5e-06ae7b1e0002',
  active_studio_release_no: 1,
  active_release_id: null,
  active_release_no: null,
  class_count: 1,
  property_count: 0,
  relationship_count: 0,
  binding_count: 0,
  source_count: 0,
  node_count: 0,
  edge_count: 0,
  projection_state: null,
  created_at: '2026-07-31T00:00:00Z',
  updated_at: '2026-07-31T00:00:00Z',
  version: 1,
  delivery_policy: null,
}

const detail: KnowledgeAssetOperationalDetail = {
  asset,
  schema_elements: [{
    stable_element_id: 'class.customer',
    kind: 'CLASS',
    display_name: '고객',
    canonical_name: 'Customer',
    parent_stable_element_id: null,
    data_type: null,
    source_stable_element_id: null,
    target_stable_element_id: null,
  }, {
    stable_element_id: 'property.customer.name',
    kind: 'PROPERTY',
    display_name: '고객명',
    canonical_name: 'name',
    parent_stable_element_id: 'class.customer',
    data_type: 'STRING',
    source_stable_element_id: null,
    target_stable_element_id: null,
  }, {
    stable_element_id: 'property.customer.segment',
    kind: 'PROPERTY',
    display_name: '고객군',
    canonical_name: 'segment',
    parent_stable_element_id: 'class.customer',
    data_type: 'STRING',
    source_stable_element_id: null,
    target_stable_element_id: null,
  }],
  bindings: [{
    id: '019fa57b-52de-74c0-9f5e-06ae7b1e0010',
    target_stable_element_id: 'class.customer',
    source_reference_id: '019fa57b-52de-74c0-9f5e-06ae7b1e0011',
    source_kind: 'CATALOG_DATASET',
    source_name: 'crm.customer',
    source_version: 'catalog-v3',
    mapping_rule_count: 2,
    mapping_rules: [{
      method: 'SUBJECT_ID',
      source_field_path: 'customer_id',
      target_stable_element_id: 'class.customer',
      source_unit: null,
      canonical_unit: null,
    }, {
      method: 'PROPERTY',
      source_field_path: 'customer_name',
      target_stable_element_id: 'property.customer.name',
      source_unit: null,
      canonical_unit: null,
    }],
  }],
  projections: [],
}

const changeset: KnowledgeChangeSet = {
  id: '019fa57b-52de-74c0-9f5e-06ae7b1e0003',
  graph_id: asset.id,
  base_release_id: null,
  ontology_version_id: '019fa57b-52de-74c0-9f5e-06ae7b1e0004',
  title: '고객 인스턴스',
  state: 'DRAFT',
  author_id: '019fa57b-52de-74c0-9f5e-06ae7b1e0005',
  reviewed_by: null,
  review_reason: null,
  published_release_id: null,
  version: 2,
  created_at: '2026-07-31T00:00:00Z',
  updated_at: '2026-07-31T00:00:00Z',
  operations: [],
  validations: [],
}

describe('KnowledgeAssetInstancePanel', () => {
  it('shows released Class and Property binding coverage without exposing source rows', async () => {
    const onEditAsset = vi.fn()
    const request = vi.fn((path: string) => {
      if (path.startsWith('/knowledge/registry/assets?')) {
        return Promise.resolve({
          items: [asset],
          next_cursor: null,
          limit: 100,
        } satisfies KnowledgeAssetPage)
      }
      if (path.endsWith('/detail')) return Promise.resolve(detail)
      if (path.endsWith('/changesets')) return Promise.resolve([])
      return Promise.reject(new Error(`Unexpected request: ${path}`))
    })

    render(
      <KnowledgeAssetInstancePanel
        client={{ request } as unknown as ApiClient}
        onEditAsset={onEditAsset}
      />,
    )

    fireEvent.click(await screen.findByRole('button', { name: 'DB Binding' }))
    expect(await screen.findByLabelText('Class 및 Property DB Binding coverage'))
      .toBeInTheDocument()
    expect(screen.getByText(/crm\.customer · CATALOG_DATASET/)).toBeInTheDocument()
    expect(screen.getByText('customer_id')).toBeInTheDocument()
    expect(screen.getByText('customer_name')).toBeInTheDocument()
    expect(screen.getByText('고객군').closest('tr')).toHaveTextContent('UNMAPPED')

    fireEvent.click(screen.getByRole('button', { name: 'Studio에서 Binding 편집' }))
    expect(onEditAsset).toHaveBeenCalledWith(asset.id)
  })

  it('focuses the result Changeset supplied by the Studio ingestion route', async () => {
    const focusedChangeset = {
      ...changeset,
      id: '019fa57b-52de-74c0-9f5e-06ae7b1e0099',
      title: 'DB Ingestion 결과',
    }
    const request = vi.fn((path: string) => {
      if (path.startsWith('/knowledge/registry/assets?')) {
        return Promise.resolve({
          items: [asset],
          next_cursor: null,
          limit: 100,
        } satisfies KnowledgeAssetPage)
      }
      if (path.endsWith('/detail')) return Promise.resolve(detail)
      if (path.endsWith('/changesets')) {
        return Promise.resolve([changeset, focusedChangeset])
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`))
    })

    render(
      <KnowledgeAssetInstancePanel
        client={{ request } as unknown as ApiClient}
        onEditAsset={vi.fn()}
        initialAssetId={asset.id}
        initialChangesetId={focusedChangeset.id}
      />,
    )

    await waitFor(() => {
      expect(screen.getByLabelText('대상 Knowledge Asset')).toHaveValue(asset.id)
      expect(screen.getByLabelText('편집할 DRAFT')).toHaveValue(
        focusedChangeset.id,
      )
    })
  })

  it('creates a T-Box-bound typed operation with the exact classification and ETag', async () => {
    const operationCalls: RequestOptions[] = []
    const request = vi.fn((path: string, options?: RequestOptions) => {
      if (path.startsWith('/knowledge/registry/assets?')) {
        return Promise.resolve({
          items: [asset],
          next_cursor: null,
          limit: 100,
        } satisfies KnowledgeAssetPage)
      }
      if (path.endsWith('/detail')) return Promise.resolve(detail)
      if (path.endsWith('/changesets') && options?.method !== 'POST') {
        return Promise.resolve([changeset])
      }
      if (path.endsWith('/operations')) {
        operationCalls.push(options ?? {})
        return Promise.resolve({ ...changeset, version: 3 })
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`))
    })
    render(
      <KnowledgeAssetInstancePanel
        client={{ request } as unknown as ApiClient}
        onEditAsset={vi.fn()}
      />,
    )

    await screen.findByText('고객 인스턴스')
    fireEvent.change(screen.getByLabelText('표시 이름'), {
      target: { value: '홍길동' },
    })
    fireEvent.change(screen.getByLabelText('Source ref'), {
      target: { value: 'manual://customer' },
    })
    fireEvent.change(screen.getByLabelText('Source locator'), {
      target: { value: 'row:1' },
    })
    fireEvent.change(screen.getByLabelText('Source version'), {
      target: { value: 'v1' },
    })
    fireEvent.change(screen.getByLabelText('Method'), {
      target: { value: 'MANUAL_ENTRY' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Typed operation 추가' }))

    await waitFor(() => expect(operationCalls).toHaveLength(1))
    expect(operationCalls[0]?.ifMatch).toBe('"2"')
    const rawBody = operationCalls[0]?.body
    expect(typeof rawBody).toBe('string')
    if (typeof rawBody !== 'string') {
      throw new TypeError('Typed operation body must be JSON text.')
    }
    const body = JSON.parse(rawBody) as Record<string, unknown>
    expect(body).toMatchObject({
      operation: 'UPSERT',
      entity_kind: 'NODE',
      document: {
        entity_type: 'Customer',
        classification: 2,
        properties: { name: '홍길동' },
      },
    })
  })
})
