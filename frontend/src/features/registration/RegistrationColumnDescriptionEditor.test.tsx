import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient, RequestOptions } from '../../api/client'
import type {
  CatalogAssetDetail,
  CatalogColumnDescriptionPreview,
  ChangeRequestRecord,
} from '../../api/types'
import {
  RegistrationColumnDescriptionEditor,
  schemaDescriptionFields,
} from './RegistrationColumnDescriptionEditor'

function asset(): CatalogAssetDetail {
  return {
    id: 'asset-1',
    external_urn: 'urn:li:dataset:asset-1',
    asset_type: 'DATASET',
    name: 'wafer_metrics',
    description: 'Dataset description',
    platform: 'postgres',
    database_name: 'fab',
    schema_name: 'quality',
    classification: 'INTERNAL',
    lifecycle: 'ACTIVE',
    observed_at: '2026-07-17T01:00:00Z',
    matches: [],
    ownership: [],
    glossary_terms: [],
    tags: [],
    schema_fields: [
      { fieldPath: 'event_id', description: 'Legacy identifier', nativeDataType: 'BIGINT' },
      { fieldPath: 'event_time', description: 'Event time', nativeDataType: 'TIMESTAMP' },
    ],
    quality: {},
    source_version: 'projection-v1',
  }
}

function preview(): CatalogColumnDescriptionPreview {
  return {
    asset_id: 'asset-1',
    target_ref: 'urn:li:dataset:asset-1',
    aspect_name: 'schemaMetadata',
    field_path: 'event_id',
    current_description: 'Legacy identifier',
    proposed_description: 'Immutable event identifier',
    before_hash: 'b'.repeat(64),
    after_hash: 'a'.repeat(64),
    preview_etag: `"${'e'.repeat(64)}"`,
    source_version: 'provider-v2',
    observed_at: '2026-07-17T02:00:00Z',
  }
}

function changeRequest(): ChangeRequestRecord {
  return {
    id: 'change-1',
    number: 'CR-FAB-260717-7F2A',
    request_type: 'CATALOG_COLUMN_DESCRIPTION',
    title: 'event_id 컬럼 설명 변경',
    description: 'Clarify the identifier.',
    state: 'REGISTERED',
    requester_id: 'subject-1',
    created_at: '2026-07-17T01:02:03Z',
    requested_due_date: null,
    priority: null,
    urgency: null,
    classification: 'INTERNAL',
    version: 1,
    items: [],
    approvals: [],
    transitions: [],
  }
}

function clientWith(
  request: (path: string, options?: RequestOptions) => Promise<unknown>,
): ApiClient {
  return { request: vi.fn(request) } as unknown as ApiClient
}

describe('RegistrationColumnDescriptionEditor', () => {
  it('filters malformed projection rows and submits only a typed field-path proposal after preview', async () => {
    expect(schemaDescriptionFields([
      { fieldPath: 'valid', description: 'description' },
      { fieldPath: 'valid', description: 'duplicate' },
      { fieldPath: 2, description: 'invalid' },
      { fieldPath: 'bad-description', description: { nested: true } },
    ])).toEqual([{ fieldPath: 'valid', description: 'description', dataType: null }])

    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      void options
      if (path.endsWith('/column-description-previews')) return Promise.resolve(preview())
      if (path.endsWith('/column-description-change-requests')) return Promise.resolve(changeRequest())
      throw new Error(`Unexpected request: ${path}`)
    })
    render(<RegistrationColumnDescriptionEditor client={clientWith(request)} asset={asset()} />)

    fireEvent.change(screen.getByLabelText('변경 사유'), { target: { value: 'Clarify the identifier.' } })
    fireEvent.change(screen.getByLabelText('제안 컬럼 설명'), {
      target: { value: 'Immutable event identifier' },
    })
    fireEvent.click(screen.getByRole('button', { name: '변경 미리보기' }))

    await screen.findByRole('region', { name: '컬럼 설명 변경 미리보기' })
    const previewCall = request.mock.calls.find(([path]) => path.endsWith('/column-description-previews'))
    expect(previewCall?.[1]).toMatchObject({
      method: 'POST',
      body: JSON.stringify({ field_path: 'event_id', description: 'Immutable event identifier' }),
    })

    fireEvent.click(screen.getByRole('button', { name: '변경요청 생성' }))
    await screen.findByText(/CR-FAB-260717-7F2A 변경 요청을 생성/)
    const createCall = request.mock.calls.find(([path]) => path.endsWith('/column-description-change-requests'))
    expect(createCall?.[1]).toMatchObject({
      method: 'POST',
      ifMatch: `"${'e'.repeat(64)}"`,
      body: JSON.stringify({
        field_path: 'event_id',
        description: 'Immutable event identifier',
        title: 'event_id 컬럼 설명 변경',
        change_description: 'Clarify the identifier.',
      }),
    })
    expect(createCall?.[1]?.idempotencyKey).toMatch(/^column-description-change-/)
    expect(screen.queryByLabelText('Aspect JSON')).not.toBeInTheDocument()
  })
})
