import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiClient, RequestOptions } from '../../api/client'
import type {
  CatalogAssetDetail,
  UploadContentProfile,
  UploadPreparation,
  UploadRecord,
} from '../../api/types'
import { loadCompleteAssetDetail, RegistrationPage } from './RegistrationPage'
import { supportedContentType } from './RegistrationBulkWorkbench'
import { RegistrationManualWorkbench } from './RegistrationManualWorkbench'

const emptyTree = {
  items: [],
  page: { limit: 100 },
  meta: {
    policy_version: 'test',
    source_watermark: 1,
    observed_at: '2026-01-01T00:00:00Z',
  },
}

function clientWith(
  request: (path: string, options?: RequestOptions) => Promise<unknown>,
): ApiClient {
  return { request: vi.fn(request) } as unknown as ApiClient
}

function uploadRecord(
  state = 'ACCEPTED',
  displayName = 'catalog.csv',
  contentProfile: UploadContentProfile = 'FORMAT_ONLY_V1',
): UploadRecord {
  return {
    id: 'upload-1',
    display_name: displayName,
    state,
    size_bytes: 128,
    content_type: 'text/csv',
    sha256: 'a'.repeat(64),
    classification: 'INTERNAL',
    content_profile: contentProfile,
    expires_at: '2026-01-02T00:00:00Z',
    version: 3,
    recommended_part_size_bytes: 5_242_880,
    validation_summary: { rows: 2 },
    last_error_code: null,
  }
}

function preparationRecord(
  state: UploadPreparation['state'] = 'QUEUED',
): UploadPreparation {
  return {
    id: 'preparation-1',
    upload_id: 'upload-1',
    content_profile: 'DATASET_DESCRIPTION_CSV_V1',
    source_manifest_version: 3,
    source_sha256: 'a'.repeat(64),
    configuration_hash: 'b'.repeat(64),
    state,
    attempts: 0,
    rows_processed: 0,
    total_rows: null,
    last_error_code: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    version: 1,
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Registration workbench', () => {
  it('accepts PDF as a format-only Knowledge source media type', () => {
    expect(supportedContentType({ name: 'semiconductor-outlook.pdf', type: '' }))
      .toBe('application/pdf')
  })

  it('opens in a governed manual catalog workbench', async () => {
    const request = vi.fn((path: string, options?: RequestOptions) => {
      void path
      void options
      return Promise.resolve(emptyTree)
    })

    render(<RegistrationPage client={clientWith(request)} />)

    expect(screen.getByRole('tab', { name: /MANUAL/ })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('GOVERNED')).toBeInTheDocument()
    expect(screen.getByText(/Resource Tree에서 테이블을 선택하세요/)).toBeInTheDocument()
    expect(screen.getByText('Metadata Registration')).toBeInTheDocument()
    expect(screen.queryByLabelText('Aspect JSON')).not.toBeInTheDocument()
    await waitFor(() => expect(request.mock.calls.some(([path, options]) => (
      path.startsWith('/catalog/tree/nodes?') && options?.signal instanceof AbortSignal
    ))).toBe(true))
  })

  it('loads every version-bound schema page before manual editing', async () => {
    const fields = Array.from({ length: 450 }, (_, index) => ({
      fieldPath: `column_${index}`,
      nativeDataType: 'varchar',
    }))
    const base = {
      id: 'asset-many-fields',
      external_urn: 'urn:li:dataset:many-fields',
      asset_type: 'DATASET',
      name: 'many_fields',
      description: null,
      platform: 'postgres',
      database_name: 'warehouse',
      schema_name: 'public',
      domain: null,
      tags: [],
      terms: [],
      classification: 'INTERNAL',
      lifecycle: 'ACTIVE',
      observed_at: '2026-01-01T00:00:00Z',
      matches: [],
      ownership: [],
      glossary_terms: [],
      quality: {},
      projection_source_version: 'source/version 7',
      source_version: 'source-7',
      schema_fields_total: 450,
      schema_fields_available: 450,
      schema_fields_truncated: false,
      schema_fields_total_exact: true,
    } satisfies Partial<CatalogAssetDetail>
    const request = vi.fn((path: string) => {
      const offset = Number(new URL(`https://example.test${path}`).searchParams.get('field_offset'))
      const pageFields = fields.slice(offset, offset + 200)
      return Promise.resolve({
        ...base,
        schema_fields: pageFields,
        schema_fields_offset: offset,
        schema_fields_limit: 200,
        schema_fields_has_more: offset + pageFields.length < fields.length,
      } as CatalogAssetDetail)
    })

    const detail = await loadCompleteAssetDetail(
      clientWith(request),
      'asset-many-fields',
      new AbortController().signal,
    )

    expect(detail.schema_fields).toHaveLength(450)
    expect(detail.schema_fields[449]?.fieldPath).toBe('column_449')
    expect(request.mock.calls.map(([path]) => path)).toEqual([
      '/catalog/assets/asset-many-fields?field_offset=0&field_limit=200',
      '/catalog/assets/asset-many-fields?field_offset=200&field_limit=200&field_source_version=source-7',
      '/catalog/assets/asset-many-fields?field_offset=400&field_limit=200&field_source_version=source-7',
    ])
  })

  it('rejects a provider-version change while loading schema pages', async () => {
    const request = vi.fn((path: string) => Promise.resolve({
      id: 'asset-version-drift',
      external_urn: 'urn:li:dataset:version-drift',
      asset_type: 'DATASET',
      name: 'version_drift',
      description: null,
      platform: 'postgres',
      database_name: 'warehouse',
      schema_name: 'public',
      domain: null,
      tags: [],
      terms: [],
      classification: 'INTERNAL',
      lifecycle: 'ACTIVE',
      observed_at: '2026-01-01T00:00:00Z',
      matches: [],
      ownership: [],
      glossary_terms: [],
      quality: {},
      projection_source_version: 'projection-stable',
      source_version: path.includes('field_offset=0') ? 'provider-v1' : 'provider-v2',
      schema_fields: [{ fieldPath: path.includes('field_offset=0') ? 'first' : 'second' }],
      schema_fields_total: 2,
      schema_fields_available: 2,
      schema_fields_truncated: false,
      schema_fields_total_exact: true,
      schema_fields_offset: path.includes('field_offset=0') ? 0 : 1,
      schema_fields_limit: 1,
      schema_fields_has_more: path.includes('field_offset=0'),
    } as CatalogAssetDetail))

    await expect(loadCompleteAssetDetail(
      clientWith(request),
      'asset-version-drift',
      new AbortController().signal,
    )).rejects.toThrow(/원본 버전/)
    expect(request.mock.calls[1]?.[0]).toContain('field_source_version=provider-v1')
  })

  it('uses the v0.3 property table and column grid with an independent manual submission', async () => {
    const asset: CatalogAssetDetail = {
      id: 'asset-1',
      external_urn: 'urn:li:dataset:(urn:li:dataPlatform:postgres,seed.wafer,DEV)',
      asset_type: 'TABLE',
      name: 'wafer',
      description: 'Wafer production records.',
      platform: 'postgres',
      database_name: 'datariver',
      schema_name: 'semiconductor_seed',
      domain: 'manufacturing',
      tags: ['tier:gold'],
      terms: ['wafer'],
      classification: 'INTERNAL',
      lifecycle: 'ACTIVE',
      observed_at: '2026-01-01T00:00:00Z',
      matches: [],
      ownership: [],
      glossary_terms: [],
      schema_fields: [{
        fieldPath: 'wafer_id', label: 'Wafer identifier', nativeDataType: 'uuid', description: 'Identifier',
        globalTags: { tags: [{ tag: { name: 'field:identifier' } }] },
        glossaryTerms: { terms: [{ term: { name: 'record_identifier' } }] },
      }],
      schema_fields_total: 1,
      schema_fields_available: 1,
      schema_fields_truncated: false,
      schema_fields_total_exact: true,
      schema_fields_offset: 0,
      schema_fields_limit: 100,
      schema_fields_has_more: false,
      quality: {},
      projection_source_version: 'projection-1',
      source_version: 'source-1',
    }
    const submissions: RequestOptions[] = []
    const request = vi.fn((path: string, options?: RequestOptions) => {
      if (path.startsWith('/catalog/vocabulary?kind=TAG') && path.includes('q=silver')) {
        return Promise.resolve({ items: ['tier:silver'] })
      }
      if (path === '/registration/manual-submissions' && options?.method === 'POST') {
        submissions.push(options)
        return Promise.resolve({
          id: 'submission-1', state: 'QUEUED', serial_number: 3, row_count: 2,
          source_version: 'source-1', created_at: '2026-01-01T00:00:00Z', version: 1,
        })
      }
      return Promise.resolve({ items: [], meta: emptyTree.meta })
    })
    const view = render(<RegistrationManualWorkbench
      client={clientWith(request)}
      asset={asset}
      loading={false}
      onClose={vi.fn()}
    />)

    expect(screen.getByText('Table Properties')).toBeInTheDocument()
    expect(screen.getByText('Column Schema Specifications')).toBeInTheDocument()
    expect(screen.getByText('wafer_id')).toBeInTheDocument()
    expect(screen.getByText('Wafer identifier')).toBeInTheDocument()
    const columnGrid = screen.getByRole('region', { name: 'Column Schema Specifications' })
    expect(within(columnGrid).getByRole('columnheader', { name: 'Logical Name' })).toBeInTheDocument()
    expect(within(columnGrid).getByRole('columnheader', { name: 'Description' })).toBeInTheDocument()
    expect(screen.getByLabelText('테이블 Description')).toHaveValue('Wafer production records.')
    expect(screen.getByLabelText('wafer_id Description')).toHaveValue('Identifier')
    expect(screen.getByText('tier:gold')).toBeInTheDocument()
    expect(screen.getByText('field:identifier')).toBeInTheDocument()
    expect(screen.getByText('record_identifier')).toBeInTheDocument()
    expect(screen.queryByLabelText('Aspect JSON')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '테이블 Tags 추가' }))
    fireEvent.change(screen.getByLabelText('테이블 Tags'), { target: { value: 'silver' } })
    fireEvent.click(await screen.findByRole('option', { name: 'tier:silver' }))
    expect(screen.getByText('tier:silver')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '테이블 Tags 추가' }))
    fireEvent.change(screen.getByLabelText('테이블 Tags'), { target: { value: 'proposed-tag' } })
    expect(await screen.findByText('등록된 Tag이 없습니다.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('option', { name: 'proposed-tag 신규 제안값으로 추가' }))
    expect(screen.getByText('proposed-tag')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '테이블 Tags 선택된 값 이전 항목' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '테이블 Tags 이전 항목' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '테이블 Tags 다음 항목' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '테이블 Tags 추가' }))
    expect(document.querySelector('.controlled-vocabulary-menu')).toHaveClass('controlled-vocabulary-menu')
    fireEvent.change(screen.getByLabelText('테이블 Tags'), { target: { value: 'manual-one,manual-two,' } })
    expect(screen.getByText('manual-one')).toBeInTheDocument()
    expect(screen.getByText('manual-two')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('테이블 Description'), { target: { value: 'Verified wafer records.' } })
    fireEvent.click(screen.getByRole('button', { name: 'SAVE' }))
    await waitFor(() => expect(submissions).toHaveLength(1))
    expect(submissions[0]?.method).toBe('POST')
    expect(submissions[0]?.idempotencyKey).toMatch(/^manual-metadata-/)
    const submittedBody = submissions[0]?.body
    expect(typeof submittedBody).toBe('string')
    if (typeof submittedBody !== 'string') throw new Error('Expected a serialized request body.')
    expect(JSON.parse(submittedBody)).toMatchObject({
      asset_id: 'asset-1',
      source_version: 'projection-1',
    })
    expect(screen.getByText(/제출 #3이 2개 행으로 저장되었습니다/)).toBeInTheDocument()

    view.rerender(<RegistrationManualWorkbench
      client={clientWith(request)}
      asset={{ ...asset, description_truncated: true }}
      loading={false}
      onClose={vi.fn()}
    />)
    expect(screen.getByRole('alert')).toHaveTextContent(/응답 상한으로 잘려/)
    expect(screen.getByRole('button', { name: 'SAVE' })).toBeDisabled()

    view.rerender(<RegistrationManualWorkbench
      client={clientWith(request)}
      asset={{
        ...asset,
        description_truncated: false,
        schema_fields_truncated: true,
        schema_fields_total_exact: false,
        schema_fields_total: 1_001,
      }}
      loading={false}
      onClose={vi.fn()}
    />)
    expect(screen.getByRole('alert')).toHaveTextContent(/응답 상한으로 잘려/)
    expect(screen.getByRole('button', { name: 'SAVE' })).toBeDisabled()
  })

  it('loads upload history only after the bulk workbench is selected', async () => {
    const calls: Array<[string, RequestOptions | undefined]> = []
    const request = vi.fn((path: string, options?: RequestOptions) => {
      calls.push([path, options])
      void options
      return Promise.resolve(path.startsWith('/uploads') ? { items: [] } : emptyTree)
    })

    render(<RegistrationPage client={clientWith(request)} />)
    fireEvent.click(screen.getByRole('tab', { name: /BULK/ }))

    expect(screen.getByRole('tab', { name: /BULK/ })).toHaveAttribute('aria-selected', 'true')
    await waitFor(() => expect(calls.some(([path, options]) => (
      path === '/uploads?limit=50' && options?.signal instanceof AbortSignal
    ))).toBe(true))
  })

  it('aborts the prior workspace client request when the security boundary changes', async () => {
    let priorSignal: AbortSignal | undefined
    const firstClient = clientWith((path, options) => {
      if (path.startsWith('/catalog/tree')) return Promise.resolve(emptyTree)
      priorSignal = options?.signal ?? undefined
      return new Promise((_resolve, reject) => {
        priorSignal?.addEventListener(
          'abort',
          () => reject(new DOMException('aborted', 'AbortError')),
          { once: true },
        )
      })
    })
    const secondClient = clientWith((path) => Promise.resolve(
      path.startsWith('/uploads') ? { items: [] } : emptyTree,
    ))
    const view = render(<RegistrationPage client={firstClient} />)
    fireEvent.click(screen.getByRole('tab', { name: /BULK/ }))
    await waitFor(() => expect(priorSignal).toBeDefined())

    view.rerender(<RegistrationPage client={secondClient} />)

    await waitFor(() => expect(priorSignal?.aborted).toBe(true))
    expect(screen.queryByText('업로드 또는 검증 상태 확인 실패')).not.toBeInTheDocument()
  })

  it('discards an in-flight preparation read when the workspace client changes', async () => {
    const typed = uploadRecord(
      'ACCEPTED',
      'dataset-description.csv',
      'DATASET_DESCRIPTION_CSV_V1',
    )
    const generic = uploadRecord('ACCEPTED', 'generic.csv')
    let preparationSignal: AbortSignal | undefined
    const firstClient = clientWith((path, options) => {
      if (path.startsWith('/catalog/tree')) return Promise.resolve(emptyTree)
      if (path === '/uploads?limit=50') return Promise.resolve({ items: [typed] })
      if (path === '/uploads/upload-1/preparations?limit=20') {
        preparationSignal = options?.signal ?? undefined
        return new Promise((_resolve, reject) => {
          preparationSignal?.addEventListener(
            'abort',
            () => reject(new DOMException('aborted', 'AbortError')),
            { once: true },
          )
        })
      }
      throw new Error(`unexpected request: ${path}`)
    })
    const secondClient = clientWith((path) => Promise.resolve(
      path === '/uploads?limit=50' ? { items: [generic] } : emptyTree,
    ))

    const view = render(<RegistrationPage client={firstClient} />)
    fireEvent.click(screen.getByRole('tab', { name: /BULK/ }))
    fireEvent.click(await screen.findByRole('button', { name: /dataset-description.csv/ }))
    await waitFor(() => expect(preparationSignal).toBeDefined())

    view.rerender(<RegistrationPage client={secondClient} />)

    await waitFor(() => expect(preparationSignal?.aborted).toBe(true))
    fireEvent.click(await screen.findByRole('button', { name: /generic.csv/ }))
    expect(screen.getByText(/형식 검증 전용/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Bulk preparation 상태')).not.toBeInTheDocument()
  })

  it('keeps accepted uploads read-only until typed accepted-content binding exists', async () => {
    const upload = uploadRecord()
    const request = vi.fn((path: string, options?: RequestOptions) => {
      void options
      return Promise.resolve(path.startsWith('/uploads') ? { items: [upload] } : emptyTree)
    })

    render(<RegistrationPage client={clientWith(request)} />)
    fireEvent.click(screen.getByRole('tab', { name: /BULK/ }))
    const historyItem = await screen.findByRole('button', { name: /catalog.csv/ })
    fireEvent.click(historyItem)

    expect(screen.getByText(/형식 검증 전용/)).toBeInTheDocument()
    expect(screen.queryByLabelText('대상 URN')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Aspect JSON')).not.toBeInTheDocument()
    expect(request.mock.calls.some(([path]) => path.includes('/registration-proposals'))).toBe(false)
    const bindingStage = within(screen.getByRole('list', { name: '등록 처리 단계' }))
      .getByText('Preparation').closest('li')
    expect(bindingStage).not.toBeNull()
    expect(within(bindingStage as HTMLElement).getByText('대기')).toBeInTheDocument()
  })

  it('binds the selected typed profile to upload initiation', async () => {
    const initiated = uploadRecord(
      'INITIATED',
      'dataset-description.csv',
      'DATASET_DESCRIPTION_CSV_V1',
    )
    const accepted = { ...initiated, state: 'ACCEPTED', version: 3 }
    const request = vi.fn((path: string, options?: RequestOptions) => {
      if (path.startsWith('/catalog/tree')) return Promise.resolve(emptyTree)
      if (path === '/uploads?limit=50') return Promise.resolve({ items: [] })
      if (path === '/uploads' && options?.method === 'POST') return Promise.resolve(initiated)
      if (path === '/uploads/upload-1/parts') return Promise.resolve({ url: 'https://object.test/part' })
      if (path === '/uploads/upload-1/complete') return Promise.resolve(accepted)
      if (path === '/uploads/upload-1') return Promise.resolve(accepted)
      if (path === '/uploads/upload-1/preparations?limit=20') return Promise.resolve({ items: [] })
      throw new Error(`unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ ETag: '"part-etag"' }),
    }))

    render(<RegistrationPage client={clientWith(request)} />)
    fireEvent.click(screen.getByRole('tab', { name: /BULK/ }))
    fireEvent.change(screen.getByLabelText('등록 프로파일'), {
      target: { value: 'DATASET_DESCRIPTION_CSV_V1' },
    })
    const input = document.querySelector<HTMLInputElement>('input[type="file"]')
    expect(input).not.toBeNull()
    fireEvent.change(input as HTMLInputElement, {
      target: {
        files: [new File(['description'], 'dataset-description.csv', { type: 'text/csv' })],
      },
    })
    fireEvent.click(screen.getByRole('button', { name: '검증 업로드 시작' }))

    await waitFor(() => expect(request.mock.calls.some(([path, options]) => {
      if (path !== '/uploads' || options?.method !== 'POST' || typeof options.body !== 'string') {
        return false
      }
      const body = JSON.parse(options.body) as Record<string, unknown>
      return body.content_profile === 'DATASET_DESCRIPTION_CSV_V1'
    })).toBe(true))
    await screen.findByRole('button', { name: '미리보기 준비' })
  })

  it('creates only a server-owned preparation from an accepted typed upload', async () => {
    const upload = uploadRecord(
      'ACCEPTED',
      'dataset-description.csv',
      'DATASET_DESCRIPTION_CSV_V1',
    )
    const queued = preparationRecord()
    const request = vi.fn((path: string, options?: RequestOptions) => {
      if (path.startsWith('/catalog/tree')) return Promise.resolve(emptyTree)
      if (path === '/uploads?limit=50') return Promise.resolve({ items: [upload] })
      if (path === '/uploads/upload-1/preparations?limit=20') {
        return Promise.resolve({ items: [] })
      }
      if (path === '/uploads/upload-1/preparations' && options?.method === 'POST') {
        return Promise.resolve(queued)
      }
      throw new Error(`unexpected request: ${path}`)
    })

    render(<RegistrationPage client={clientWith(request)} />)
    fireEvent.click(screen.getByRole('tab', { name: /BULK/ }))
    fireEvent.click(await screen.findByRole('button', { name: /dataset-description.csv/ }))
    fireEvent.click(await screen.findByRole('button', { name: '미리보기 준비' }))

    expect((await screen.findAllByText('QUEUED')).length).toBeGreaterThan(0)
    const createCall = request.mock.calls.find(([path, options]) => (
      path === '/uploads/upload-1/preparations' && options?.method === 'POST'
    ))
    expect(createCall).toBeDefined()
    expect(createCall?.[1]?.ifMatch).toBe('"3"')
    expect(createCall?.[1]?.idempotencyKey).toMatch(/^upload-preparation-/)
    expect(createCall?.[1]?.body).toBeUndefined()
    expect(screen.getByLabelText('Bulk preparation 상태')).toHaveTextContent('준비 작업이 대기열에 등록되었습니다.')
    const bindingStage = within(screen.getByRole('list', { name: '등록 처리 단계' }))
      .getByText('Preparation').closest('li')
    expect(bindingStage).not.toBeNull()
    expect(within(bindingStage as HTMLElement).getByText('진행 중')).toBeInTheDocument()
    expect(request.mock.calls.some(([path]) => path.includes('/registration-proposals'))).toBe(false)
  })

  it('refreshes the selected upload detail with the latest server state', async () => {
    const queued = uploadRecord(
      'COMPLETION_QUEUED',
      'dataset-description.xlsx',
      'DATASET_DESCRIPTION_XLSX_V1',
    )
    const accepted = { ...queued, state: 'ACCEPTED', version: 6 }
    let loadCount = 0
    const request = vi.fn((path: string) => {
      if (path.startsWith('/catalog/tree')) return Promise.resolve(emptyTree)
      if (path === '/uploads?limit=50') {
        loadCount += 1
        return Promise.resolve({ items: [loadCount === 1 ? queued : accepted] })
      }
      if (path === '/uploads/upload-1/preparations?limit=20') {
        return Promise.resolve({ items: [] })
      }
      throw new Error(`unexpected request: ${path}`)
    })

    render(<RegistrationPage client={clientWith(request)} />)
    fireEvent.click(screen.getByRole('tab', { name: /BULK/ }))
    fireEvent.click(await screen.findByRole('button', { name: /dataset-description.xlsx/ }))
    expect(screen.getByText('Version').nextElementSibling).toHaveTextContent('3')

    fireEvent.click(screen.getByRole('button', { name: '목록 새로고침' }))

    await waitFor(() => expect(screen.getByText('Version').nextElementSibling).toHaveTextContent('6'))
    expect(screen.getAllByText('ACCEPTED').length).toBeGreaterThan(0)
  })

  it('renders determinate server progress without inventing completion', async () => {
    const upload = uploadRecord(
      'ACCEPTED',
      'dataset-description.csv',
      'DATASET_DESCRIPTION_CSV_V1',
    )
    const preparing = {
      ...preparationRecord('PREPARING'),
      attempts: 1,
      rows_processed: 25,
      total_rows: 100,
    }
    const request = vi.fn((path: string) => {
      if (path.startsWith('/catalog/tree')) return Promise.resolve(emptyTree)
      if (path === '/uploads?limit=50') return Promise.resolve({ items: [upload] })
      if (path === '/uploads/upload-1/preparations?limit=20') {
        return Promise.resolve({ items: [preparing] })
      }
      throw new Error(`unexpected request: ${path}`)
    })

    render(<RegistrationPage client={clientWith(request)} />)
    fireEvent.click(screen.getByRole('tab', { name: /BULK/ }))
    fireEvent.click(await screen.findByRole('button', { name: /dataset-description.csv/ }))

    const progress = await screen.findByRole('progressbar', { name: '후보 준비 진행률' })
    expect(progress).toHaveAttribute('aria-valuenow', '25')
    expect(screen.getByLabelText('Bulk preparation 상태')).toHaveTextContent('후보 25행을 처리했습니다.')
    const bindingStage = within(screen.getByRole('list', { name: '등록 처리 단계' }))
      .getByText('Preparation').closest('li')
    expect(bindingStage).toHaveClass('pending')
  })

  it('renders only server-authorized typed candidates as read-only evidence', async () => {
    const upload = uploadRecord(
      'ACCEPTED',
      'dataset-description.csv',
      'DATASET_DESCRIPTION_CSV_V1',
    )
    const ready = {
      ...preparationRecord('READY'),
      rows_processed: 1,
      total_rows: 1,
    }
    const candidates = {
      items: [{
        id: 'candidate-1',
        ordinal: 1,
        evidence_version: 'DATASET_DESCRIPTION_CANDIDATE_V2',
        candidate_kind: 'DATASET_DESCRIPTION_UPDATE',
        proposed_description: 'Clarify the event identifier.',
        submitted_identity: {
          platform: 'postgres', database_name: 'fab', schema_name: 'quality', table_name: 'wafer_events', identity_hash: 'a'.repeat(64),
        },
        candidate_hash: 'b'.repeat(64),
        created_at: '2026-01-01T00:00:00Z',
        current_target: {
          id: 'asset-1', asset_type: 'DATASET', name: 'wafer_events', platform: 'postgres', database_name: 'fab', schema_name: 'quality', classification: 'INTERNAL', lifecycle: 'ACTIVE', source_version: 'source-v3', observed_at: '2026-01-01T00:00:00Z',
        },
      }],
      page: { limit: 20 },
      receipt: {
        id: 'receipt-1', preparation_id: 'preparation-1', manifest_version: 3, source_sha256: 'c'.repeat(64), content_profile: 'DATASET_DESCRIPTION_CSV_V1', parser_version: 'parser-v1', scanner_version: 'scanner-v1', schema_version: 'schema-v1', configuration_hash: 'd'.repeat(64), candidate_root_hash: 'e'.repeat(64), receipt_hash: 'f'.repeat(64), observed_at: '2026-01-01T00:00:00Z', created_at: '2026-01-01T00:00:00Z',
      },
      meta: { projection_version: 3, policy_version: 'test', classification_policy_version: 1, authorization_generation: 2 },
    }
    const request = vi.fn((path: string) => {
      if (path.startsWith('/catalog/tree')) return Promise.resolve(emptyTree)
      if (path === '/uploads?limit=50') return Promise.resolve({ items: [upload] })
      if (path === '/uploads/upload-1/preparations?limit=20') return Promise.resolve({ items: [ready] })
      if (path === '/uploads/upload-1/preparations/preparation-1/candidates?limit=20') return Promise.resolve(candidates)
      throw new Error(`unexpected request: ${path}`)
    })

    render(<RegistrationPage client={clientWith(request)} />)
    fireEvent.click(screen.getByRole('tab', { name: /BULK/ }))
    fireEvent.click(await screen.findByRole('button', { name: /dataset-description.csv/ }))
    fireEvent.click(await screen.findByRole('button', { name: '후보 조회' }))

    const preview = await screen.findByRole('region', { name: '등록 후보 미리보기' })
    expect(within(preview).getByText('wafer_events')).toBeInTheDocument()
    expect(within(preview).getByText('Clarify the event identifier.')).toBeInTheDocument()
    expect(within(preview).getByText(/typed 서버 명령으로만 열립니다/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /변경요청 생성/ })).not.toBeInTheDocument()
    expect(request.mock.calls.some(([path]) => path.includes('/registration-proposals'))).toBe(false)
  })

  it.each(['READY', 'FAILED', 'STALE'] as const)(
    'keeps %s preparation evidence non-executable',
    async (state) => {
      const upload = uploadRecord(
        'ACCEPTED',
        'dataset-description.csv',
        'DATASET_DESCRIPTION_CSV_V1',
      )
      const preparation = {
        ...preparationRecord(state),
        rows_processed: state === 'READY' ? 2 : 0,
        total_rows: state === 'READY' ? 2 : null,
        last_error_code: state === 'FAILED' ? 'PARSER_REJECTED' : null,
      }
      const request = vi.fn((path: string) => {
        if (path.startsWith('/catalog/tree')) return Promise.resolve(emptyTree)
        if (path === '/uploads?limit=50') return Promise.resolve({ items: [upload] })
        if (path === '/uploads/upload-1/preparations?limit=20') {
          return Promise.resolve({ items: [preparation] })
        }
        throw new Error(`unexpected request: ${path}`)
      })

      render(<RegistrationPage client={clientWith(request)} />)
      fireEvent.click(screen.getByRole('tab', { name: /BULK/ }))
      fireEvent.click(await screen.findByRole('button', { name: /dataset-description.csv/ }))

      expect((await screen.findAllByText(state)).length).toBeGreaterThan(0)
      expect(screen.queryByRole('button', { name: /UPDATE|변경 요청 생성|후보 실행/ })).not.toBeInTheDocument()
      expect(request.mock.calls.some(([path]) => (
        path.includes('/registration-proposals') || path.includes('/candidates')
      ))).toBe(false)
    },
  )

  it('purges all bulk form values when the workspace client changes', async () => {
    const firstUpload = uploadRecord('ACCEPTED', 'catalog-a.csv')
    const secondUpload = uploadRecord('ACCEPTED', 'catalog-b.csv')
    const firstClient = clientWith((path) => Promise.resolve(
      path.startsWith('/uploads') ? { items: [firstUpload] } : emptyTree,
    ))
    const secondClient = clientWith((path) => Promise.resolve(
      path.startsWith('/uploads') ? { items: [secondUpload] } : emptyTree,
    ))
    const view = render(<RegistrationPage client={firstClient} />)
    fireEvent.click(screen.getByRole('tab', { name: /BULK/ }))
    fireEvent.click(await screen.findByRole('button', { name: /catalog-a.csv/ }))
    fireEvent.change(screen.getByLabelText('분류등급'), {
      target: { value: 'CONFIDENTIAL' },
    })
    fireEvent.change(screen.getByLabelText('등록 프로파일'), {
      target: { value: 'DATASET_DESCRIPTION_CSV_V1' },
    })

    view.rerender(<RegistrationPage client={secondClient} />)
    fireEvent.click(await screen.findByRole('button', { name: /catalog-b.csv/ }))

    expect(screen.getByLabelText('분류등급')).toHaveValue('INTERNAL')
    expect(screen.getByLabelText('등록 프로파일')).toHaveValue('FORMAT_ONLY_V1')
  })

  it('renders rejected validation as failure rather than completion', async () => {
    const rejected = uploadRecord('REJECTED', 'rejected.csv')
    const request = vi.fn((path: string, options?: RequestOptions) => {
      void options
      return Promise.resolve(path.startsWith('/uploads') ? { items: [rejected] } : emptyTree)
    })
    render(<RegistrationPage client={clientWith(request)} />)
    fireEvent.click(screen.getByRole('tab', { name: /BULK/ }))
    fireEvent.click(await screen.findByRole('button', { name: /rejected.csv/ }))

    const validationStage = screen.getByText('Validation').closest('li')
    expect(validationStage).not.toBeNull()
    expect(validationStage).toHaveClass('failed')
    expect(within(validationStage as HTMLElement).getByText('실패')).toBeInTheDocument()
  })
})
