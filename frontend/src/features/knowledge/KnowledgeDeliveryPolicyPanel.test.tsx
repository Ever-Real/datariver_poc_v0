import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient, RequestOptions } from '../../api/client'
import type {
  KnowledgeAssetPage,
  KnowledgeAssetSummary,
  KnowledgeDeliveryPolicy,
} from '../../api/types'
import { KnowledgeDeliveryPolicyPanel } from './KnowledgeDeliveryPolicyPanel'

const asset: KnowledgeAssetSummary = {
  id: '019fa57b-52de-74c0-9f5e-06ae7b1d0001',
  slug: 'enterprise_ontology',
  name: 'Enterprise Ontology',
  graph_type: 'CURATED_KNOWLEDGE',
  status: 'PUBLISHED',
  classification: 'INTERNAL',
  domain_id: null,
  domain_name: null,
  creator_name: null,
  creator_email: null,
  editor_name: null,
  editor_email: null,
  active_studio_release_id: '019fa57b-52de-74c0-9f5e-06ae7b1d0002',
  active_studio_release_no: 1,
  active_release_id: '019fa57b-52de-74c0-9f5e-06ae7b1d0003',
  active_release_no: 1,
  class_count: 2,
  property_count: 2,
  relationship_count: 1,
  binding_count: 0,
  source_count: 0,
  node_count: 1,
  edge_count: 0,
  projection_state: 'SHADOW_VERIFIED',
  created_at: '2026-07-31T00:00:00Z',
  updated_at: '2026-07-31T00:00:00Z',
  version: 1,
  delivery_policy: null,
}

describe('KnowledgeDeliveryPolicyPanel', () => {
  it('keeps the same idempotency key after a lost response and preserves success feedback', async () => {
    const saveCalls: RequestOptions[] = []
    const policy: KnowledgeDeliveryPolicy = {
      id: '019fa57b-52de-74c0-9f5e-06ae7b1d0004',
      graph_id: asset.id,
      api_enabled: true,
      chat_enabled: true,
      priority: 200,
      match_any_terms: ['온톨로지'],
      match_all_terms: [],
      excluded_terms: [],
      version: 1,
      created_by: '019fa57b-52de-74c0-9f5e-06ae7b1d0005',
      updated_by: '019fa57b-52de-74c0-9f5e-06ae7b1d0005',
      created_at: '2026-07-31T00:00:00Z',
      updated_at: '2026-07-31T00:00:00Z',
    }
    const request = vi.fn((path: string, options?: RequestOptions) => {
      if (path.startsWith('/knowledge/registry/assets?')) {
        return Promise.resolve({
          items: [asset],
          next_cursor: null,
          limit: 100,
        } satisfies KnowledgeAssetPage)
      }
      if (path.endsWith('/delivery-policy')) {
        saveCalls.push(options ?? {})
        return saveCalls.length === 1
          ? Promise.reject(new Error('response lost'))
          : Promise.resolve(policy)
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`))
    })
    render(
      <KnowledgeDeliveryPolicyPanel
        client={{ request } as unknown as ApiClient}
      />,
    )

    await screen.findByRole('heading', { name: 'Enterprise Ontology' })
    fireEvent.click(
      screen.getByRole('checkbox', { name: /외부 서비스 API 제공/ }),
    )
    fireEvent.click(
      screen.getByRole('checkbox', { name: /플랫폼 Chat 자동 라우팅/ }),
    )
    fireEvent.change(screen.getByLabelText('우선순위 (0–1000)'), {
      target: { value: '200' },
    })
    fireEvent.change(screen.getByLabelText('ANY 조건 · 쉼표 구분'), {
      target: { value: '온톨로지' },
    })
    fireEvent.click(screen.getByRole('button', { name: '정책 저장' }))
    expect(await screen.findByText('response lost')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '정책 저장' }))
    expect(await screen.findByRole('status')).toHaveTextContent(
      'API 제공 및 Chat routing 정책을 저장했습니다.',
    )
    expect(saveCalls).toHaveLength(2)
    expect(saveCalls[0]?.idempotencyKey).toBe(saveCalls[1]?.idempotencyKey)
    expect(saveCalls[0]?.body).toBe(saveCalls[1]?.body)
    await waitFor(() => expect(screen.getByText('ENABLED')).toBeInTheDocument())
  })
})
