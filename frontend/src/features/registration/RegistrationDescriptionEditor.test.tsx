import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ApiError, type ApiClient, type RequestOptions } from '../../api/client'
import type {
  CatalogAssetDetail,
  CatalogDescriptionPreview,
  ChangeRequestRecord,
} from '../../api/types'
import { RegistrationDescriptionEditor } from './RegistrationDescriptionEditor'

function asset(overrides: Partial<CatalogAssetDetail> = {}): CatalogAssetDetail {
  return {
    id: 'asset-1',
    external_urn: 'urn:li:dataset:asset-1',
    asset_type: 'DATASET',
    name: 'wafer_metrics',
    description: '기존 설명',
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
    schema_fields: [],
    schema_fields_total: 0,
    schema_fields_available: 0,
    schema_fields_truncated: false,
    schema_fields_total_exact: true,
    schema_fields_offset: 0,
    schema_fields_limit: 100,
    schema_fields_has_more: false,
    quality: {},
    projection_source_version: 'projection-v1',
    source_version: 'source-v1',
    ...overrides,
  }
}

function preview(overrides: Partial<CatalogDescriptionPreview> = {}): CatalogDescriptionPreview {
  return {
    asset_id: 'asset-1',
    target_ref: 'urn:li:dataset:asset-1',
    aspect_name: 'datasetProperties',
    current_description: '기존 설명',
    proposed_description: '새 설명',
    before_hash: 'b'.repeat(64),
    after_hash: 'a'.repeat(64),
    preview_etag: `"${'e'.repeat(64)}"`,
    source_version: 'source-v2',
    observed_at: '2026-07-17T02:00:00Z',
    ...overrides,
  }
}

function changeRequest(): ChangeRequestRecord {
  return {
    id: 'change-1',
    number: 'CR-2026-1',
    request_type: 'CATALOG_METADATA',
    title: 'wafer_metrics 설명 변경',
    description: '용어를 명확히 합니다.',
    state: 'REGISTERED',
    requester_id: 'subject-1',
    requester_department_id: null,
    current_round_id: 'round-1',
    current_round_number: 1,
    created_at: '2026-07-17T01:02:03Z',
    requested_due_date: null,
    priority: null,
    urgency: null,
    classification: 'INTERNAL',
    version: 1,
    items: [],
    approvals: [],
    transitions: [],
    rounds: [{ id: 'round-1', round_number: 1, submitted_by: 'subject-1', submitted_at: '2026-07-17T01:02:03Z', closed_at: null, evidence_hash: 'a'.repeat(64) }],
    test_runs: [],
  }
}

function clientWith(
  request: (path: string, options?: RequestOptions) => Promise<unknown>,
): ApiClient {
  return { request: vi.fn(request) } as unknown as ApiClient
}

function enterProposal(description = '새 설명') {
  fireEvent.change(screen.getByLabelText('변경 사유'), {
    target: { value: '용어를 명확히 합니다.' },
  })
  fireEvent.change(screen.getByLabelText('제안 설명'), { target: { value: description } })
}

describe('RegistrationDescriptionEditor', () => {
  it('requires an explicit preview and submits its opaque ETag without client classification', async () => {
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      void options
      if (path.endsWith('/description-previews')) return Promise.resolve(preview())
      if (path.endsWith('/description-change-requests')) return Promise.resolve(changeRequest())
      throw new Error(`Unexpected request: ${path}`)
    })
    render(<RegistrationDescriptionEditor client={clientWith(request)} asset={asset()} />)
    enterProposal()

    const submit = screen.getByRole('button', { name: '변경요청 생성' })
    expect(submit).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '변경 미리보기' }))

    await screen.findByRole('region', { name: '설명 변경 미리보기' })
    const previewCall = request.mock.calls.find(([path]) => path.endsWith('/description-previews'))
    expect(previewCall?.[1]).toMatchObject({
      method: 'POST',
      body: JSON.stringify({ description: '새 설명' }),
    })
    expect(screen.getByText('source-v2')).toBeInTheDocument()
    expect(screen.getByText('b'.repeat(64))).toBeInTheDocument()
    expect(screen.getByText('a'.repeat(64))).toBeInTheDocument()

    fireEvent.click(submit)
    await screen.findByText(/CR-2026-1 변경 요청을 생성/)
    const createCall = request.mock.calls.find(([path]) => path.endsWith('/description-change-requests'))
    expect(createCall?.[1]).toMatchObject({
      method: 'POST',
      ifMatch: `"${'e'.repeat(64)}"`,
      body: JSON.stringify({
        description: '새 설명',
        title: 'wafer_metrics 설명 변경',
        change_description: '용어를 명확히 합니다.',
      }),
    })
    expect(createCall?.[1]?.idempotencyKey).toMatch(/^description-change-/)
    expect(screen.queryByLabelText('Aspect JSON')).not.toBeInTheDocument()
  })

  it('allows an explicit empty description as a clear proposal', async () => {
    const request = vi.fn((path: string, options?: RequestOptions) => {
      void path
      void options
      return Promise.resolve(preview({
        proposed_description: '',
        after_hash: 'c'.repeat(64),
      }))
    })
    render(<RegistrationDescriptionEditor client={clientWith(request)} asset={asset()} />)
    enterProposal('')

    expect(screen.getByText(/기존 설명을 삭제하도록 제안/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '변경 미리보기' }))

    await screen.findByRole('region', { name: '설명 변경 미리보기' })
    expect(request.mock.calls[0]?.[1]?.body).toBe(JSON.stringify({ description: '' }))
    expect(screen.getByText('(빈 설명)')).toBeInTheDocument()
  })

  it('allows live preview when the proposal matches a potentially stale projection', async () => {
    const request = vi.fn(() => Promise.resolve(preview({
      current_description: 'DataHub live 설명',
      proposed_description: '기존 설명',
    })))
    render(<RegistrationDescriptionEditor
      client={clientWith(request)}
      asset={asset({ stale_at: '2026-07-17T02:00:00Z' })}
    />)
    fireEvent.change(screen.getByLabelText('변경 사유'), {
      target: { value: 'projection에 표시된 설명으로 복원합니다.' },
    })

    expect(screen.getByText(/live 원본 검증 전에는 no-op 여부를 확정하지 않습니다/)).toBeInTheDocument()
    const previewButton = screen.getByRole('button', { name: '변경 미리보기' })
    expect(previewButton).toBeEnabled()
    fireEvent.click(previewButton)

    await screen.findByRole('region', { name: '설명 변경 미리보기' })
    expect(screen.getByText(/DataHub 원본 설명이 화면의 projection과 다릅니다/)).toBeInTheDocument()
  })

  it('invalidates preview and idempotency intent whenever the proposal is edited', async () => {
    const request = vi.fn(() => Promise.resolve(preview()))
    render(<RegistrationDescriptionEditor client={clientWith(request)} asset={asset()} />)
    enterProposal()
    fireEvent.click(screen.getByRole('button', { name: '변경 미리보기' }))
    await screen.findByRole('region', { name: '설명 변경 미리보기' })
    expect(screen.getByRole('button', { name: '변경요청 생성' })).toBeEnabled()

    fireEvent.change(screen.getByLabelText('변경 요청 제목'), {
      target: { value: '수정된 제목' },
    })

    expect(screen.queryByRole('region', { name: '설명 변경 미리보기' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '변경요청 생성' })).toBeDisabled()
  })

  it('prevents duplicate preview and create requests while each operation is in flight', async () => {
    let resolvePreview: ((value: CatalogDescriptionPreview) => void) | undefined
    let resolveCreate: ((value: ChangeRequestRecord) => void) | undefined
    const previewPromise = new Promise<CatalogDescriptionPreview>((resolve) => { resolvePreview = resolve })
    const createPromise = new Promise<ChangeRequestRecord>((resolve) => { resolveCreate = resolve })
    const request = vi.fn((path: string): Promise<unknown> => (
      path.endsWith('/description-previews') ? previewPromise : createPromise
    ))
    render(<RegistrationDescriptionEditor client={clientWith(request)} asset={asset()} />)
    enterProposal()
    const previewButton = screen.getByRole('button', { name: '변경 미리보기' })
    fireEvent.click(previewButton)
    fireEvent.click(previewButton)
    expect(request.mock.calls.filter(([path]) => path.endsWith('/description-previews'))).toHaveLength(1)

    await act(async () => {
      resolvePreview?.(preview())
      await previewPromise
    })
    const submit = screen.getByRole('button', { name: '변경요청 생성' })
    fireEvent.click(submit)
    fireEvent.click(submit)
    expect(request.mock.calls.filter(([path]) => path.endsWith('/description-change-requests'))).toHaveLength(1)
    expect(screen.getByRole('button', { name: '생성 중…' })).toBeDisabled()

    await act(async () => {
      resolveCreate?.(changeRequest())
      await createPromise
    })
    expect(screen.getByText(/CR-2026-1 변경 요청을 생성/)).toBeInTheDocument()
  })

  it('discards a stale preview and reports source drift on precondition failure', async () => {
    const conflict = new ApiError({
      type: 'urn:datariver:problem:preview-drift',
      title: '원본 변경 충돌',
      status: 412,
      detail: '미리보기 이후 원본이 변경되었습니다.',
      code: 'catalog_description_preview_stale',
      request_id: 'request-1',
    })
    const request = vi.fn((path: string): Promise<unknown> => (
      path.endsWith('/description-previews')
        ? Promise.resolve(preview())
        : Promise.reject(conflict)
    ))
    render(<RegistrationDescriptionEditor client={clientWith(request)} asset={asset()} />)
    enterProposal()
    fireEvent.click(screen.getByRole('button', { name: '변경 미리보기' }))
    await screen.findByRole('region', { name: '설명 변경 미리보기' })
    fireEvent.click(screen.getByRole('button', { name: '변경요청 생성' }))

    await screen.findByText(/미리보기 이후 DataHub 원본이 변경/)
    expect(screen.queryByRole('region', { name: '설명 변경 미리보기' })).not.toBeInTheDocument()
    expect(screen.getByText('원본 변경 충돌')).toBeInTheDocument()
    expect(screen.getByText('요청 ID: request-1')).toBeInTheDocument()
  })

  it('resets all editor state when the asset or workspace client changes', async () => {
    const firstClient = clientWith(() => Promise.resolve(preview()))
    const secondClient = clientWith(() => Promise.resolve(preview({
      asset_id: 'asset-2',
      target_ref: 'urn:li:dataset:asset-2',
    })))
    const view = render(<RegistrationDescriptionEditor client={firstClient} asset={asset()} />)
    enterProposal()
    fireEvent.click(screen.getByRole('button', { name: '변경 미리보기' }))
    await screen.findByRole('region', { name: '설명 변경 미리보기' })

    view.rerender(<RegistrationDescriptionEditor
      client={secondClient}
      asset={asset({
        id: 'asset-2',
        external_urn: 'urn:li:dataset:asset-2',
        name: 'lot_summary',
        description: '두 번째 설명',
        source_version: 'source-v9',
      })}
    />)

    await waitFor(() => expect(screen.getByLabelText('제안 설명')).toHaveValue('두 번째 설명'))
    expect(screen.getByLabelText('변경 요청 제목')).toHaveValue('lot_summary 설명 변경')
    expect(screen.getByLabelText('변경 사유')).toHaveValue('')
    expect(screen.queryByRole('region', { name: '설명 변경 미리보기' })).not.toBeInTheDocument()
  })
})
