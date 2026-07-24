import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient, RequestOptions } from '../../api/client'
import type { ApiProduct, ConsumerGrant, KnowledgeGraph } from '../../api/types'
import { SharingPage } from './SharingPage'

const productId = '10000000-0000-4000-8000-000000000001'
const versionId = '10000000-0000-4000-8000-000000000002'
const graphId = '10000000-0000-4000-8000-000000000003'
const releaseId = '10000000-0000-4000-8000-000000000004'
const serviceSubjectId = '10000000-0000-4000-8000-000000000005'

const product: ApiProduct = {
  id: productId,
  slug: 'governed-neighbors',
  name: 'Governed Neighbors',
  description: 'Release-pinned neighbor contract',
  graph_id: graphId,
  classification: 'INTERNAL',
  owner_id: '10000000-0000-4000-8000-000000000006',
  state: 'PUBLISHED',
  current_version_id: versionId,
  version: 2,
  versions: [{
    id: versionId,
    product_id: productId,
    graph_id: graphId,
    release_id: releaseId,
    version_no: 1,
    surface: 'NEIGHBORS',
    contract: { scopes: ['neighbors.query'] },
    maximum_hops: 2,
    maximum_nodes: 200,
    timeout_ms: 5000,
    state: 'PUBLISHED',
  }],
}

const graph: KnowledgeGraph = {
  id: graphId,
  slug: 'governed-graph',
  name: 'Governed Graph',
  graph_type: 'DOMAIN',
  status: 'ACTIVE',
  classification: 'INTERNAL',
  active_release_id: releaseId,
  version: 1,
}

describe('SharingPage consumer grant', () => {
  it('requires and submits the service Subject UUID with the OIDC client', async () => {
    const request = vi.fn(
      (path: string, options?: RequestOptions): Promise<unknown> => {
        if (path === '/api-products' && options?.method !== 'POST') {
          return Promise.resolve([product])
        }
        if (path === '/knowledge/graphs') return Promise.resolve([graph])
        if (path === `/api-products/${productId}/grants` && options?.method === 'POST') {
          return Promise.resolve({
            id: '10000000-0000-4000-8000-000000000007',
            product_id: productId,
            product_version_id: versionId,
            contract_version: 'SUBJECT_CLIENT_V2',
            consumer_subject_id: serviceSubjectId,
            consumer_issuer: 'https://issuer.example',
            consumer_client_id: 'catalog-reader',
            scopes: ['neighbors.query'],
            maximum_classification: 'INTERNAL',
            requests_per_minute: 60,
            monthly_quota: 100000,
            valid_from: '2026-07-24T00:00:00Z',
            expires_at: '2026-08-23T00:00:00Z',
            state: 'ACTIVE',
            version: 1,
          } satisfies ConsumerGrant)
        }
        if (path === `/api-products/${productId}/grants`) return Promise.resolve([])
        throw new Error(`Unexpected request: ${path}`)
      },
    )
    const client = { request } as unknown as ApiClient
    const noop = vi.fn(() => Promise.resolve())

    render(
      <SharingPage
        client={client}
        onStepUp={noop}
        onPasswordReauth={noop}
        onEnroll={noop}
      />,
    )

    fireEvent.change(await screen.findByLabelText('Service Subject UUID'), {
      target: { value: serviceSubjectId },
    })
    fireEvent.change(screen.getByLabelText('OIDC Consumer client_id'), {
      target: { value: 'catalog-reader' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Grant 생성' }))

    await waitFor(() => {
      const post = request.mock.calls.find(
        ([path, options]) =>
          path === `/api-products/${productId}/grants` && options?.method === 'POST',
      )
      expect(post).toBeDefined()
      expect(typeof post?.[1]?.body).toBe('string')
      expect(JSON.parse(post?.[1]?.body as string)).toMatchObject({
        consumer_subject_id: serviceSubjectId,
        consumer_client_id: 'catalog-reader',
        scopes: ['neighbors.query'],
      })
    })
  })
})
