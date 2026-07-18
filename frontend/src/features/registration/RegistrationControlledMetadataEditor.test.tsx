import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient } from '../../api/client'
import type { CatalogAssetDetail, ChangeRequestRecord } from '../../api/types'
import { RegistrationControlledMetadataEditor } from './RegistrationControlledMetadataEditor'

const asset: CatalogAssetDetail = {
  id: 'asset-1', external_urn: 'urn:li:dataset:(urn:li:dataPlatform:postgres,wafer,PROD)', asset_type: 'DATASET',
  name: 'wafer', platform: 'postgres', database_name: 'fab', schema_name: 'yield', classification: 'INTERNAL', lifecycle: 'ACTIVE', observed_at: '2026-07-18T00:00:00Z',
  ownership: [], glossary_terms: [], tags: ['PII'], schema_fields: [], quality: {}, source_version: 'source-v1', matches: [],
}

const proposal: ChangeRequestRecord = {
  id: 'cr-1', number: 'CR-FAB-260718-9A3C', request_type: 'CATALOG_CONTROLLED_METADATA', title: 'wafer Tag 변경', description: 'Governed tag update', state: 'REGISTERED', requester_id: 'subject-1', classification: 'INTERNAL', version: 1, items: [], approvals: [], transitions: [],
}

function clientWith(request: unknown): ApiClient {
  return { request } as ApiClient
}

describe('RegistrationControlledMetadataEditor', () => {
  it('uses a typed live preview and creates a governed Tag change request', async () => {
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path.endsWith('/controlled-metadata-previews')) return Promise.resolve({
        asset_id: asset.id, target_ref: asset.external_urn, aspect_name: 'globalTags', current_refs: ['urn:li:tag:legacy'], proposed_refs: ['urn:li:tag:governed'], before_hash: 'a'.repeat(64), after_hash: 'b'.repeat(64), preview_etag: `"${'c'.repeat(64)}"`, source_version: 'datahub-v1', observed_at: '2026-07-18T00:00:00Z',
      })
      if (path.endsWith('/controlled-metadata-change-requests')) return Promise.resolve(proposal)
      return Promise.reject(new Error(`Unexpected path ${path}`))
    })
    render(<RegistrationControlledMetadataEditor client={clientWith(request)} asset={asset} />)

    fireEvent.click(screen.getByRole('radio', { name: /Tag/i }))
    fireEvent.change(screen.getByLabelText(/제안 Tag 참조/), { target: { value: 'urn:li:tag:governed' } })
    fireEvent.change(screen.getByLabelText('변경 사유'), { target: { value: 'Replace the legacy classification tag.' } })
    fireEvent.click(screen.getByRole('button', { name: '변경 미리보기' }))

    await screen.findByText('검증된 Tag 변경 비교')
    expect(request).toHaveBeenCalledWith(expect.stringContaining('/controlled-metadata-previews'), expect.objectContaining({ method: 'POST' }))
    fireEvent.click(screen.getByRole('button', { name: '변경요청 생성' }))

    await screen.findByText(/CR-FAB-260718-9A3C 변경 요청을 생성했습니다/)
    await waitFor(() => expect(request).toHaveBeenCalledWith(expect.stringContaining('/controlled-metadata-change-requests'), expect.objectContaining({ method: 'POST', ifMatch: `"${'c'.repeat(64)}"` })))
  })
})
