import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { ApiError, type ApiClient, type RequestOptions } from '../../api/client'
import type { CatalogAssetDetail, CatalogMetadataRecommendation } from '../../api/types'
import { CatalogMetadataRecommendationPanel } from './CatalogMetadataRecommendationPanel'

const assetId = '01900000-0000-7000-8000-000000000001'
const tagId = '01900000-0000-7000-8000-000000000010'
const termId = '01900000-0000-7000-8000-000000000011'
const recommendationId = '01900000-0000-7000-8000-000000000020'
const recommendationId2 = '01900000-0000-7000-8000-000000000021'

const detail = {
  id: assetId,
  name: 'Generic customer profile',
  source_version: 'catalog-v1',
  schema_fields: [{ fieldPath: 'customer_name', nativeDataType: 'STRING' }],
} as unknown as CatalogAssetDetail

function recommendation(
  id = recommendationId,
  vocabularyId = tagId,
): CatalogMetadataRecommendation {
  return {
    recommendation_id: id,
    asset_id: assetId,
    field_path: null,
    vocabulary_id: vocabularyId,
    kind: vocabularyId === tagId ? 'TAG' : 'TERM',
    source_version: 'catalog-v1',
    confidence: 0.85,
    reason: 'Current metadata overlaps the selected label.',
    evidence: ['asset name: normalized token overlap 1/1'],
    provider: 'datariver_local_similarity',
    model: 'normalized_token_overlap_v1',
    prompt_version: 'none',
    rule_version: 'catalog-recommendation-local-v1',
    state: 'NEEDS_DECISION',
    version: 1,
    change_request_id: null,
    created_at: '2026-08-29T00:00:00Z',
    updated_at: '2026-08-29T00:00:00Z',
  }
}

it('previews exact selected vocabulary then bulk-approves through a confirmed governed request', async () => {
  const request = vi.fn((path: string, options?: RequestOptions) => {
    if (path.startsWith('/uploads/metadata-vocabulary')) return Promise.resolve({
      items: [
        { id: tagId, kind: 'TAG', display_name: 'Customer', source_version: 'a'.repeat(64) },
        { id: termId, kind: 'TAG', display_name: 'Profile', source_version: 'b'.repeat(64) },
      ],
      page: { limit: 20 },
    })
    if (path.endsWith('/metadata-recommendation-previews')) return Promise.resolve({
      items: [recommendation(), recommendation(recommendationId2, termId)],
      auto_application: 'DISABLED_NEEDS_DECISION',
    })
    if (path === '/catalog/metadata-recommendations/approve') {
      const submitted = JSON.parse(String(options?.body)) as { targets: unknown[] }
      expect(submitted.targets).toHaveLength(2)
      const changeRequestId = '01900000-0000-7000-8000-000000000030'
      return Promise.resolve({
        change_request_id: changeRequestId,
        items: [
          { ...recommendation(), state: 'APPROVED', version: 2, change_request_id: changeRequestId },
          { ...recommendation(recommendationId2, termId), state: 'APPROVED', version: 2, change_request_id: changeRequestId },
        ],
        auto_application: 'DISABLED_NEEDS_DECISION',
      })
    }
    throw new Error(`Unexpected request: ${path}`)
  })
  const client = { request } as unknown as ApiClient

  render(<CatalogMetadataRecommendationPanel client={client} detail={detail} />)

  await waitFor(() => expect(screen.getByText('Customer')).toBeInTheDocument())
  fireEvent.click(screen.getByLabelText('Customer'))
  fireEvent.click(screen.getByLabelText('Profile'))
  fireEvent.click(screen.getByRole('button', { name: '추천 미리보기 (2)' }))

  await waitFor(() => expect(screen.getByRole('button', { name: '선택 승인 요청 (2)' })).toBeEnabled())
  const previewCall = request.mock.calls.find(([path]) => String(path).endsWith('/metadata-recommendation-previews'))
  expect(JSON.parse(String(previewCall?.[1]?.body))).toEqual({
    source_version: 'catalog-v1', field_path: null, vocabulary_ids: [tagId, termId],
  })
  fireEvent.click(screen.getByRole('button', { name: '선택 승인 요청 (2)' }))
  expect(screen.getByRole('dialog', { name: '추천 승인 요청 확인' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '확인' }))

  await waitFor(() => expect(screen.getByText(/변경 요청/)).toHaveTextContent(
    '01900000-0000-7000-8000-000000000030',
  ))
  expect(screen.getAllByText('APPROVED')).toHaveLength(2)
  expect(request.mock.calls.find(([path]) => path === '/catalog/metadata-recommendations/approve')?.[1]?.idempotencyKey).toMatch(/^catalog-metadata-recommendation-approve-/)
})

it('keeps a rejection retry idempotent and reports permission/provider errors without mutation', async () => {
  let rejectAttempts = 0
  const request = vi.fn((path: string, options?: RequestOptions) => {
    if (path.startsWith('/uploads/metadata-vocabulary')) return Promise.resolve({
      items: [{ id: tagId, kind: 'TAG', display_name: 'Customer', source_version: 'a'.repeat(64) }],
      page: { limit: 20 },
    })
    if (path.endsWith('/metadata-recommendation-previews')) return Promise.resolve({
      items: [recommendation()], auto_application: 'DISABLED_NEEDS_DECISION',
    })
    if (path.includes('/reject')) {
      rejectAttempts += 1
      if (rejectAttempts === 1) return Promise.reject(new ApiError({
        type: 'about:blank',
        title: 'Forbidden',
        status: 403,
        detail: '권한 정책이 변경되었습니다.',
        code: 'FORBIDDEN',
        request_id: 'request-1',
      }))
      expect(options?.method).toBe('POST')
      return Promise.resolve({ ...recommendation(), state: 'REJECTED', version: 2 })
    }
    throw new Error(`Unexpected request: ${path}`)
  })
  const client = { request } as unknown as ApiClient

  render(<CatalogMetadataRecommendationPanel client={client} detail={detail} />)
  await waitFor(() => expect(screen.getByText('Customer')).toBeInTheDocument())
  fireEvent.click(screen.getByLabelText('Customer'))
  fireEvent.click(screen.getByRole('button', { name: '추천 미리보기 (1)' }))
  await waitFor(() => expect(screen.getByRole('button', { name: '반려' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: '반려' }))
  fireEvent.click(screen.getByRole('button', { name: '확인' }))

  await waitFor(() => expect(screen.getByText('권한 정책이 변경되었습니다.')).toBeInTheDocument())
  fireEvent.click(screen.getByRole('button', { name: '확인' }))
  await waitFor(() => expect(screen.getByText('REJECTED')).toBeInTheDocument())

  const rejectCalls = request.mock.calls.filter(([path]) => String(path).includes('/reject'))
  expect(rejectCalls).toHaveLength(2)
  expect(rejectCalls[0]?.[1]?.idempotencyKey).toBe(rejectCalls[1]?.[1]?.idempotencyKey)
  expect(request.mock.calls.some(([path]) => String(path).includes('apply'))).toBe(false)
})
