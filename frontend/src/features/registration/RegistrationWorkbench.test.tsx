import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiClient, RequestOptions } from '../../api/client'
import type {
  CatalogAssetDetail,
  RegistrationOperatorCapability,
  UploadContentProfile,
  UploadPreparation,
  UploadRecord,
} from '../../api/types'
import { loadAssetDetailPage, RegistrationPage } from './RegistrationPage'
import { supportedContentType } from './RegistrationBulkWorkbench'
import { RegistrationManualWorkbench } from './RegistrationManualWorkbench'
import { RegistrationRecentPanel } from './RegistrationRecentPanel'

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
  capability: RegistrationOperatorCapability = {
    eligible: true,
    can_view_registration: true,
    can_view_workspace_history: true,
    reason_code: 'ELIGIBLE',
    allowed_roles: ['ADMIN', 'DATA_STEWARD'],
  },
  download: (
    path: string,
    options?: Pick<RequestOptions, 'signal'>,
  ) => Promise<{ blob: Blob; filename: string; etag?: string }> = () => Promise.resolve({
    blob: new Blob(),
    filename: 'download',
  }),
  includeRecentRequests = false,
): ApiClient {
  return {
    request: vi.fn((path: string, options?: RequestOptions) => {
      if (path === '/uploads/operator-capability') return Promise.resolve(capability)
      if (!includeRecentRequests && (
        path === '/registration/manual-submissions?scope=workspace&limit=100'
        || path === '/registration/manual-submissions?scope=mine&limit=100'
        || path === '/uploads?limit=100'
      )) return Promise.resolve({ items: [], page: { limit: 100 } })
      return request(path, options)
    }),
    download: vi.fn(download),
  } as unknown as ApiClient
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

function manualAsset(): CatalogAssetDetail {
  return {
    id: 'asset-polling',
    external_urn: 'urn:li:dataset:registration-polling',
    asset_type: 'TABLE',
    name: 'registration_polling',
    description: 'Polling test asset.',
    platform: 'postgres',
    database_name: 'datariver',
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
    schema_fields: [{
      fieldPath: 'id',
      nativeDataType: 'uuid',
      description: 'Identifier',
    }],
    schema_fields_total: 1,
    schema_fields_available: 1,
    schema_fields_truncated: false,
    schema_fields_total_exact: true,
    schema_fields_offset: 0,
    schema_fields_limit: 100,
    schema_fields_has_more: false,
    quality: {},
    projection_source_version: 'projection-polling',
    source_version: 'a'.repeat(64),
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('Registration workbench', () => {
  it('shows manager registration history as read-only without mutation controls', async () => {
    const request = vi.fn((path: string) => {
      if (path.startsWith('/registration/manual-submissions')) return Promise.resolve({ items: [] })
      if (path.startsWith('/uploads')) return Promise.resolve({ items: [] })
      return Promise.resolve(emptyTree)
    })

    render(<RegistrationPage client={clientWith(request, {
      eligible: false,
      can_view_registration: true,
      can_view_workspace_history: true,
      reason_code: 'READ_ONLY',
      allowed_roles: ['ADMIN', 'DATA_STEWARD'],
    })} />)

    expect(await screen.findByText('등록관리 조회 전용')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '최근 실행' })).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: /MANUAL/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: /BULK/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /SAVE|검증 업로드 시작/ })).not.toBeInTheDocument()
  })

  it('does not issue registration history reads for an identity outside the reader roles', async () => {
    const request = vi.fn(() => Promise.resolve(emptyTree))

    render(<RegistrationPage client={clientWith(request, {
      eligible: false,
      can_view_registration: false,
      can_view_workspace_history: false,
      reason_code: 'ACTIVE_HUMAN_ADMIN_OR_DATA_STEWARD_REQUIRED',
      allowed_roles: ['ADMIN', 'DATA_STEWARD'],
    })} />)

    expect(await screen.findByText('등록관리 접근 권한이 없습니다')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '최근 실행' })).not.toBeInTheDocument()
    expect(request).not.toHaveBeenCalled()
  })

  it('filters unified recent runs and loads detail only for the selected receipt', async () => {
    const now = new Date().toISOString()
    const request = vi.fn((path: string, _options?: RequestOptions) => {
      void _options
      if (path === '/registration/manual-submissions?scope=workspace&limit=100') return Promise.resolve({
        items: [{
          id: 'manual-1', state: 'APPLIED', serial_number: 8, row_count: 1,
          source_version: 'projection-1', provider_source_version: 'provider-1',
          created_at: now, created_by: 'steward-one', asset_id: 'asset-wafer', version: 1,
          updated_at: now, applied_at: now, attempts: 1, next_attempt_at: null,
          last_error_code: null,
        }],
        page: { limit: 100 },
      })
      if (path === '/uploads?limit=100') return Promise.resolve({ items: [{
        ...uploadRecord('ACCEPTED', 'bulk-catalog.csv'),
        created_at: now,
        created_by: 'admin-one',
      }] })
      if (path === '/registration/manual-submissions/manual-1') return Promise.resolve({
        submission: {
          id: 'manual-1', state: 'APPLIED', serial_number: 8, row_count: 1,
          source_version: 'projection-1', provider_source_version: 'provider-1',
          created_at: now, created_by: 'steward-one', asset_id: 'asset-wafer', version: 1,
          updated_at: now, applied_at: now, attempts: 1, next_attempt_at: null,
          last_error_code: null,
        },
        attempts: [],
      })
      if (path === '/uploads/upload-1/preparations?limit=20') return Promise.resolve({
        items: [{ ...preparationRecord('READY'), rows_processed: 2, total_rows: 2 }],
      })
      return Promise.resolve(emptyTree)
    })

    render(<RegistrationPage client={clientWith(
      request,
      undefined,
      undefined,
      true,
    )} />)

    expect(await screen.findByText('asset-wafer')).toBeInTheDocument()
    expect(screen.getByText('bulk-catalog.csv')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('실행 유형 필터'), { target: { value: 'MANUAL' } })
    expect(screen.getByText('asset-wafer')).toBeInTheDocument()
    expect(screen.queryByText('bulk-catalog.csv')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /asset-wafer/ }))
    expect(await screen.findByText('아직 적용 영수증이 없습니다.')).toBeInTheDocument()
    const detailCall = request.mock.calls.find(([path]) => (
      path === '/registration/manual-submissions/manual-1'
    ))
    expect(detailCall?.[1]?.signal).toBeInstanceOf(AbortSignal)
    expect(request).not.toHaveBeenCalledWith(
      '/uploads/upload-1/preparations?limit=20',
      expect.anything(),
    )
  })

  it('keeps the current Manual poll alive while an older unified receipt opens', async () => {
    const now = new Date().toISOString()
    const status = (id: string, serialNumber: number, state: 'QUEUED' | 'APPLIED') => ({
      id,
      state,
      serial_number: serialNumber,
      row_count: 2,
      source_version: 'projection-polling',
      provider_source_version: 'a'.repeat(64),
      created_at: now,
      created_by: 'steward-one',
      asset_id: manualAsset().id,
      updated_at: now,
      applied_at: state === 'APPLIED' ? now : null,
      attempts: state === 'APPLIED' ? 1 : 0,
      next_attempt_at: null,
      last_error_code: null,
      version: state === 'APPLIED' ? 2 : 1,
    })
    const historySubmission = status('submission-history', 41, 'APPLIED')
    const currentQueued = status('submission-current', 42, 'QUEUED')
    const currentApplied = status('submission-current', 42, 'APPLIED')
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      if (path === '/registration/manual-submissions?scope=workspace&limit=100') {
        return Promise.resolve({ items: [historySubmission], page: { limit: 100 } })
      }
      if (path === '/uploads?limit=100') return Promise.resolve({ items: [] })
      if (path === '/registration/manual-submissions' && options?.method === 'POST') {
        return Promise.resolve(currentQueued)
      }
      if (path === '/registration/manual-submissions/submission-history') {
        return Promise.resolve({ submission: historySubmission, attempts: [] })
      }
      if (path === '/registration/manual-submissions/submission-current') {
        return Promise.resolve({ submission: currentApplied, attempts: [] })
      }
      return Promise.resolve({ items: [] })
    })
    const client = clientWith(request, undefined, undefined, true)

    render(<>
      <RegistrationManualWorkbench
        client={client}
        asset={manualAsset()}
        loading={false}
        onClose={vi.fn()}
      />
      <RegistrationRecentPanel client={client} canViewWorkspaceHistory />
    </>)

    expect(await screen.findByRole('button', { name: /asset-polling.*steward-one.*APPLIED/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'SAVE' }))
    expect(await screen.findByText(/제출 #42.*상태: QUEUED/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /asset-polling.*steward-one.*APPLIED/ }))
    expect(await screen.findByRole('heading', { name: '실행 결과' })).toBeInTheDocument()

    expect(await screen.findByText(/제출 #42.*상태: APPLIED/, {}, { timeout: 2_500 })).toBeInTheDocument()
    const currentPoll = request.mock.calls.find(([path]) => (
      path === '/registration/manual-submissions/submission-current'
    ))
    expect(currentPoll?.[1]?.signal).toBeInstanceOf(AbortSignal)
    expect(currentPoll?.[1]?.signal?.aborted).toBe(false)
  })


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

    expect(await screen.findByRole('tab', { name: /MANUAL/ })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('heading', { name: '최근 실행' })).toBeInTheDocument()
    expect(screen.getByText('GOVERNED')).toBeInTheDocument()
    expect(screen.getByText(/Resource Tree에서 테이블을 선택하세요/)).toBeInTheDocument()
    expect(screen.getByText('Metadata Registration')).toBeInTheDocument()
    expect(screen.queryByLabelText('Aspect JSON')).not.toBeInTheDocument()
    await waitFor(() => expect(request.mock.calls.some(([path, options]) => (
      path.startsWith('/catalog/tree/nodes?') && options?.signal instanceof AbortSignal
    ))).toBe(true))
  })

  it('loads only one bounded schema page for manual editing', async () => {
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
      const pageFields = fields.slice(offset, offset + 100)
      return Promise.resolve({
        ...base,
        schema_fields: pageFields,
        schema_fields_offset: offset,
        schema_fields_limit: 100,
        schema_fields_has_more: offset + pageFields.length < fields.length,
      } as CatalogAssetDetail)
    })

    const detail = await loadAssetDetailPage(
      clientWith(request),
      'asset-many-fields',
      0,
      undefined,
      undefined,
      new AbortController().signal,
    )

    expect(detail.schema_fields).toHaveLength(100)
    expect(detail.schema_fields[99]?.fieldPath).toBe('column_99')
    expect(request.mock.calls.map(([path]) => path)).toEqual([
      '/catalog/assets/asset-many-fields?field_offset=0&field_limit=100',
    ])
  })

  it('rejects a provider-version change on the next schema page', async () => {
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

    const first = await loadAssetDetailPage(
      clientWith(request),
      'asset-version-drift',
      0,
      undefined,
      undefined,
      new AbortController().signal,
    )
    await expect(loadAssetDetailPage(
      clientWith(request),
      'asset-version-drift',
      1,
      first.source_version,
      first.projection_source_version,
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
      source_version: 'a'.repeat(64),
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
          source_version: 'projection-1', provider_source_version: 'a'.repeat(64),
          created_at: '2026-01-01T00:00:00Z', version: 1,
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
      provider_source_version: 'a'.repeat(64),
      column_edits: [],
    })
    expect(screen.getByText(/제출 #3이 2개 행으로 저장되었습니다/)).toBeInTheDocument()

    view.rerender(<RegistrationManualWorkbench
      client={clientWith(request)}
      asset={{ ...asset, description_truncated: true }}
      loading={false}
      onClose={vi.fn()}
    />)
    expect(screen.getByRole('alert')).toHaveTextContent(/원본 메타데이터가 잘렸거나 stale/)
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
    expect(screen.getByRole('alert')).toHaveTextContent(/원본 메타데이터가 잘렸거나 stale/)
    expect(screen.getByRole('button', { name: 'SAVE' })).toBeDisabled()
  })

  it('retains only sparse edits while replacing the current schema page', async () => {
    const base: CatalogAssetDetail = {
      id: 'asset-paged',
      external_urn: 'urn:li:dataset:paged',
      asset_type: 'DATASET',
      name: 'paged',
      description: 'Paged table',
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
      projection_source_version: 'projection-paged',
      source_version: 'a'.repeat(64),
      schema_fields: [{ fieldPath: 'first_column', description: 'first baseline' }],
      schema_fields_total: 2,
      schema_fields_available: 2,
      schema_fields_truncated: false,
      schema_fields_total_exact: true,
      schema_fields_offset: 0,
      schema_fields_limit: 1,
      schema_fields_has_more: true,
    }
    let submittedBody: string | undefined
    const request = vi.fn((path: string, options?: RequestOptions) => {
      if (path === '/registration/manual-submissions' && options?.method === 'POST') {
        submittedBody = typeof options.body === 'string' ? options.body : undefined
        return Promise.resolve({
          id: 'submission-paged',
          state: 'QUEUED',
          serial_number: 7,
          row_count: 3,
          source_version: base.projection_source_version,
          provider_source_version: base.source_version,
          created_at: '2026-01-01T00:00:00Z',
          version: 1,
        })
      }
      return Promise.resolve({ items: [], page: { limit: 25 } })
    })
    const props = {
      client: clientWith(request),
      loading: false,
      onClose: vi.fn(),
    }
    const view = render(<RegistrationManualWorkbench {...props} asset={base} />)

    fireEvent.change(screen.getByLabelText('first_column Description'), {
      target: { value: 'first edited' },
    })
    view.rerender(<RegistrationManualWorkbench
      {...props}
      asset={{
        ...base,
        schema_fields: [{ fieldPath: 'second_column', description: 'second baseline' }],
        schema_fields_offset: 1,
        schema_fields_has_more: false,
      }}
    />)
    expect(screen.queryByText('first_column')).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('second_column Description'), {
      target: { value: 'second edited' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'SAVE' }))
    await waitFor(() => expect(submittedBody).toBeDefined())
    const parsed = JSON.parse(submittedBody ?? '{}') as { column_edits: unknown }
    expect(parsed.column_edits).toEqual([
      { field_path: 'first_column', description: 'first edited', tags: [], terms: [] },
      { field_path: 'second_column', description: 'second edited', tags: [], terms: [] },
    ])

    view.rerender(<RegistrationManualWorkbench {...props} asset={base} />)
    expect(screen.getByLabelText('first_column Description')).toHaveValue('first edited')
    expect(screen.queryByText('second_column')).not.toBeInTheDocument()
  })

  it('aborts and discards a late manual submission after the selected asset changes', async () => {
    const asset = (id: string, sourceVersion: string): CatalogAssetDetail => ({
      id,
      external_urn: `urn:li:dataset:(urn:li:dataPlatform:postgres,${id},DEV)`,
      asset_type: 'TABLE',
      name: id,
      description: `${id} description`,
      platform: 'postgres',
      database_name: 'datariver',
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
      schema_fields: [{ fieldPath: 'id', nativeDataType: 'uuid' }],
      schema_fields_total: 1,
      schema_fields_available: 1,
      schema_fields_truncated: false,
      schema_fields_total_exact: true,
      schema_fields_offset: 0,
      schema_fields_limit: 100,
      schema_fields_has_more: false,
      quality: {},
      projection_source_version: sourceVersion,
      source_version: sourceVersion,
    })
    let submissionSignal: AbortSignal | undefined
    let resolveSubmission: ((value: unknown) => void) | undefined
    const pendingSubmission = new Promise<unknown>((resolve) => {
      resolveSubmission = resolve
    })
    const request = vi.fn((path: string, options?: RequestOptions) => {
      if (path === '/registration/manual-submissions' && options?.method === 'POST') {
        submissionSignal = options.signal ?? undefined
        return pendingSubmission
      }
      if (path.startsWith('/registration/manual-submissions?')) {
        return Promise.resolve({ items: [], page: { limit: 25, next_cursor: null } })
      }
      return Promise.resolve({ items: [] })
    })
    const client = clientWith(request)
    const view = render(<RegistrationManualWorkbench
      client={client}
      asset={asset('asset-a', 'source-a')}
      loading={false}
      onClose={vi.fn()}
    />)

    fireEvent.click(screen.getByRole('button', { name: 'SAVE' }))
    await waitFor(() => expect(submissionSignal).toBeInstanceOf(AbortSignal))

    view.rerender(<RegistrationManualWorkbench
      client={client}
      asset={asset('asset-b', 'source-b')}
      loading={false}
      onClose={vi.fn()}
    />)
    expect(submissionSignal?.aborted).toBe(true)
    resolveSubmission?.({
      id: 'late-a',
      state: 'QUEUED',
      serial_number: 9,
      row_count: 2,
      source_version: 'source-a',
      created_at: '2026-01-01T00:00:00Z',
      version: 1,
    })

    await waitFor(() => expect(screen.getByLabelText('테이블 Description')).toHaveValue(
      'asset-b description',
    ))
    expect(screen.queryByText(/제출 #9/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'SAVE' })).toHaveTextContent('SAVE')
  })

  it('does not present a late save as the result of newer edits or field-page navigation', async () => {
    let resolveSubmission: ((value: unknown) => void) | undefined
    const pendingSubmission = new Promise<unknown>((resolve) => {
      resolveSubmission = resolve
    })
    const request = vi.fn((path: string, options?: RequestOptions) => {
      if (path === '/registration/manual-submissions' && options?.method === 'POST') {
        return pendingSubmission
      }
      if (path.startsWith('/registration/manual-submissions?')) {
        return Promise.resolve({ items: [], page: { limit: 25, next_cursor: null } })
      }
      return Promise.resolve({ items: [] })
    })
    const onNextFieldPage = vi.fn()
    const asset = {
      ...manualAsset(),
      schema_fields_total: 2,
      schema_fields_available: 2,
      schema_fields_has_more: true,
    }

    render(<RegistrationManualWorkbench
      client={clientWith(request)}
      asset={asset}
      loading={false}
      onClose={vi.fn()}
      onNextFieldPage={onNextFieldPage}
    />)

    fireEvent.click(screen.getByRole('button', { name: 'SAVE' }))
    await waitFor(() => expect(request.mock.calls.some(([path, options]) => (
      path === '/registration/manual-submissions' && options?.method === 'POST'
    ))).toBe(true))

    fireEvent.change(screen.getByLabelText('테이블 Description'), {
      target: { value: 'A newer unsaved description.' },
    })
    fireEvent.click(within(
      screen.getByRole('region', { name: 'Column Schema Specifications' }),
    ).getByRole('button', { name: '다음' }))
    expect(onNextFieldPage).toHaveBeenCalledOnce()

    resolveSubmission?.({
      id: 'stale-submission',
      state: 'QUEUED',
      serial_number: 99,
      row_count: 2,
      source_version: asset.projection_source_version,
      provider_source_version: asset.source_version,
      created_at: '2026-01-01T00:00:00Z',
      version: 1,
    })

    await waitFor(() => expect(screen.getByRole('button', { name: 'SAVE' })).toBeEnabled())
    expect(screen.getByLabelText('테이블 Description')).toHaveValue('A newer unsaved description.')
    expect(screen.queryByText(/제출 #99/)).not.toBeInTheDocument()
  })

  it('loads upload history only after the bulk workbench is selected', async () => {
    const calls: Array<[string, RequestOptions | undefined]> = []
    const request = vi.fn((path: string, options?: RequestOptions) => {
      calls.push([path, options])
      void options
      return Promise.resolve(path.startsWith('/uploads') ? { items: [] } : emptyTree)
    })

    render(<RegistrationPage client={clientWith(request)} />)
    fireEvent.click(await screen.findByRole('tab', { name: /BULK/ }))

    expect(await screen.findByRole('tab', { name: /BULK/ })).toHaveAttribute('aria-selected', 'true')
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
    fireEvent.click(await screen.findByRole('tab', { name: /BULK/ }))
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
    fireEvent.click(await screen.findByRole('tab', { name: /BULK/ }))
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
    fireEvent.click(await screen.findByRole('tab', { name: /BULK/ }))
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
    fireEvent.click(await screen.findByRole('tab', { name: /BULK/ }))
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
    fireEvent.click(await screen.findByRole('tab', { name: /BULK/ }))
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

  it('stops manual submission polling while the browser is hidden', async () => {
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
    const request = vi.fn((path: string, options?: RequestOptions) => {
      if (path.startsWith('/registration/manual-submissions?')) {
        return Promise.resolve({ items: [], page: { limit: 25 } })
      }
      if (path === '/registration/manual-submissions' && options?.method === 'POST') {
        return Promise.resolve({
          id: 'submission-hidden',
          state: 'QUEUED',
          serial_number: 1,
          row_count: 2,
          source_version: 'projection-polling',
          provider_source_version: 'a'.repeat(64),
          created_at: '2026-01-01T00:00:00Z',
          version: 1,
        })
      }
      throw new Error(`unexpected request: ${path}`)
    })

    render(<RegistrationManualWorkbench
      client={clientWith(request)}
      asset={manualAsset()}
      loading={false}
      onClose={vi.fn()}
    />)
    fireEvent.click(screen.getByRole('button', { name: 'SAVE' }))

    expect(await screen.findByRole('button', { name: '상태 새로고침' })).toBeInTheDocument()
    expect(request.mock.calls.some(([path]) => (
      path === '/registration/manual-submissions/submission-hidden'
    ))).toBe(false)
  })


  it('stops bulk preparation polling while the browser is hidden', async () => {
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
    const upload = uploadRecord(
      'ACCEPTED',
      'dataset-description.csv',
      'DATASET_DESCRIPTION_CSV_V1',
    )
    const preparing = preparationRecord('PREPARING')
    const request = vi.fn((path: string) => {
      if (path.startsWith('/catalog/tree')) return Promise.resolve(emptyTree)
      if (path === '/uploads?limit=50') return Promise.resolve({ items: [upload] })
      if (path === '/uploads/upload-1/preparations?limit=20') {
        return Promise.resolve({ items: [preparing] })
      }
      throw new Error(`unexpected request: ${path}`)
    })

    render(<RegistrationPage client={clientWith(request)} />)
    fireEvent.click(await screen.findByRole('tab', { name: /BULK/ }))
    fireEvent.click(await screen.findByRole('button', { name: /dataset-description.csv/ }))

    expect(await screen.findByText(/자동 상태 확인을 중단했습니다/)).toBeInTheDocument()
    expect(request.mock.calls.filter(([path]) => (
      path === '/uploads/upload-1/preparations?limit=20'
    ))).toHaveLength(1)
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
    fireEvent.click(await screen.findByRole('tab', { name: /BULK/ }))
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
    fireEvent.click(await screen.findByRole('tab', { name: /BULK/ }))
    fireEvent.click(await screen.findByRole('button', { name: /dataset-description.csv/ }))

    const progress = await screen.findByRole('progressbar', { name: '후보 준비 진행률' })
    expect(progress).toHaveAttribute('aria-valuenow', '25')
    expect(screen.getByLabelText('Bulk preparation 상태')).toHaveTextContent('후보 25행을 처리했습니다.')
    const bindingStage = within(screen.getByRole('list', { name: '등록 처리 단계' }))
      .getByText('Preparation').closest('li')
    expect(bindingStage).toHaveClass('pending')
  })

  it('creates one server-authored governed change request from an authorized typed candidate', async () => {
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
      page: { limit: 20, next_cursor: 'cursor-page-2' },
      receipt: {
        id: 'receipt-1', preparation_id: 'preparation-1', manifest_version: 3, source_sha256: 'c'.repeat(64), content_profile: 'DATASET_DESCRIPTION_CSV_V1', parser_version: 'parser-v1', scanner_version: 'scanner-v1', schema_version: 'schema-v1', configuration_hash: 'd'.repeat(64), candidate_root_hash: 'e'.repeat(64), receipt_hash: 'f'.repeat(64), observed_at: '2026-01-01T00:00:00Z', created_at: '2026-01-01T00:00:00Z',
      },
      meta: { projection_version: 3, policy_version: 'test', classification_policy_version: 1, authorization_generation: 2 },
    }
    const request = vi.fn((path: string, options?: RequestOptions) => {
      if (path.startsWith('/catalog/tree')) return Promise.resolve(emptyTree)
      if (path === '/uploads?limit=50') return Promise.resolve({ items: [upload] })
      if (path === '/uploads/upload-1/preparations?limit=20') return Promise.resolve({ items: [ready] })
      if (path === '/uploads/upload-1/preparations/preparation-1/candidates?limit=20') {
        return Promise.resolve(candidates)
      }
      if (
        path
        === '/uploads/upload-1/preparations/preparation-1/candidates?limit=20&cursor=cursor-page-2'
      ) {
        return Promise.resolve({
          ...candidates,
          items: [{
            ...candidates.items[0],
            id: 'candidate-2',
            ordinal: 2,
            proposed_description: 'Second bounded candidate page.',
          }],
          page: { limit: 20 },
        })
      }
      if (
        path
        === '/uploads/upload-1/preparations/preparation-1/candidates/candidate-1/preview'
      ) {
        return Promise.resolve({
          candidate_id: 'candidate-1',
          target_asset_id: 'asset-1',
          target_ref: 'urn:li:dataset:asset-1',
          platform: 'postgres',
          database_name: 'fab',
          schema_name: 'quality',
          table_name: 'wafer_events',
          current_description: 'Current description',
          proposed_description: 'Clarify the event identifier.',
          before_hash: '1'.repeat(64),
          after_hash: '2'.repeat(64),
          source_version: 'provider-v7',
          observed_at: '2026-01-01T00:00:00Z',
          preview_etag: `"${'3'.repeat(64)}"`,
        })
      }
      if (
        path
        === '/uploads/upload-1/preparations/preparation-1/candidates/candidate-1/change-request'
        && options?.method === 'POST'
      ) {
        return Promise.resolve({
          id: 'change-1',
          number: 'CR-POSTGRES-260101-ABCD',
          request_type: 'BULK_DATASET_DESCRIPTION',
          title: 'wafer_events Dataset 설명 변경',
          description: '검증된 BULK 업로드 후보를 변경관리 검토 대상으로 등록합니다.',
          state: 'REGISTERED',
          requester_id: 'subject-1',
          requester_department_id: null,
          current_round_id: 'round-1',
          current_round_number: 1,
          created_at: '2026-01-01T00:00:00Z',
          requested_due_date: null,
          priority: null,
          urgency: null,
          classification: 'INTERNAL',
          version: 1,
          items: [{
            id: 'item-1',
            target_type: 'DATAHUB_ASPECT',
            target_ref: 'urn:li:dataset:asset-1',
            aspect_name: 'datasetProperties',
            operation: 'UPSERT',
            target_asset_id: 'asset-1',
          }],
          approvals: [],
          transitions: [],
          rounds: [],
          test_runs: [],
        })
      }
      throw new Error(`unexpected request: ${path}`)
    })

    render(<RegistrationPage client={clientWith(request)} />)
    fireEvent.click(await screen.findByRole('tab', { name: /BULK/ }))
    fireEvent.click(await screen.findByRole('button', { name: /dataset-description.csv/ }))
    fireEvent.click(await screen.findByRole('button', { name: '후보 조회' }))

    const preview = await screen.findByRole('region', { name: '등록 후보 미리보기' })
    expect(within(preview).getByText('wafer_events')).toBeInTheDocument()
    expect(within(preview).getByText('Clarify the event identifier.')).toBeInTheDocument()
    fireEvent.click(within(preview).getByRole('button', { name: '검토 및 변경요청' }))
    expect(await within(preview).findByText('Current description')).toBeInTheDocument()
    expect(within(preview).getAllByText('Clarify the event identifier.')).toHaveLength(2)
    expect(within(preview).queryByText('urn:li:dataset:asset-1')).not.toBeInTheDocument()
    fireEvent.click(within(preview).getByRole('button', { name: '검증된 후보로 변경요청 생성' }))
    expect(await within(preview).findByText(/CR-POSTGRES-260101-ABCD/)).toBeInTheDocument()
    const createCall = request.mock.calls.find(([path]) => (
      path
      === '/uploads/upload-1/preparations/preparation-1/candidates/candidate-1/change-request'
    ))
    expect(createCall?.[1]?.ifMatch).toBe(`"${'3'.repeat(64)}"`)
    expect(createCall?.[1]?.idempotencyKey).toMatch(/^typed-bulk-change-/)
    expect(JSON.parse(createCall?.[1]?.body as string)).toEqual({
      title: 'wafer_events Dataset 설명 변경',
      reason: '검증된 BULK 업로드 후보를 변경관리 검토 대상으로 등록합니다.',
    })
    expect(request.mock.calls.some(([path]) => path.includes('/registration-proposals'))).toBe(false)

    fireEvent.click(within(preview).getByRole('button', { name: '다음 후보' }))
    expect(await within(preview).findByText('Second bounded candidate page.')).toBeInTheDocument()
    fireEvent.click(within(preview).getByRole('button', { name: '이전 후보' }))
    expect(await within(preview).findByText('Clarify the event identifier.')).toBeInTheDocument()
  })

  it('uses bounded server pages to create one governed catalog metadata change request', async () => {
    let createAttempts = 0
    const upload = uploadRecord(
      'ACCEPTED',
      'catalog-metadata.csv',
      'CATALOG_METADATA_ROWS_CSV_V1',
    )
    const ready: UploadPreparation = {
      ...preparationRecord('READY'),
      content_profile: 'CATALOG_METADATA_ROWS_CSV_V1',
      rows_processed: 2,
      total_rows: 2,
    }
    const candidate = {
      id: 'metadata-candidate-1',
      ordinal: 1,
      evidence_version: 'CATALOG_METADATA_CANDIDATE_V3',
      record_kind: 'COLUMN_DESCRIPTION',
      candidate_kind: 'COLUMN_DESCRIPTION_UPDATE',
      aspect_name: 'schemaMetadata',
      operation_count: 2,
      field_path_sample: ['event_id', 'event_time'],
      controlled_reference_count: 0,
      row_summary_truncated: false,
      submitted_identity: {
        platform: 'postgres',
        database_name: 'fab',
        schema_name: 'quality',
        table_name: 'wafer_events',
        identity_hash: 'a'.repeat(64),
      },
      candidate_hash: 'b'.repeat(64),
      created_at: '2026-01-01T00:00:00Z',
      current_target: {
        id: 'asset-1',
        asset_type: 'DATASET',
        name: 'wafer_events',
        platform: 'postgres',
        database_name: 'fab',
        schema_name: 'quality',
        classification: 'INTERNAL',
        lifecycle: 'ACTIVE',
        source_version: 'source-v3',
        observed_at: '2026-01-01T00:00:00Z',
      },
      target_ref: 'urn:li:dataset:must-not-enter-ui-state',
      controlled_ref: 'urn:li:tag:must-not-enter-ui-state',
      after_document: { secret: 'raw-after-document-secret' },
      object_key: 'private/storage/coordinate.csv',
    }
    const firstPage = {
      items: [candidate],
      page: { limit: 20, next_cursor: 'metadata-page-2' },
      receipt: {
        id: 'metadata-receipt-1',
        preparation_id: 'preparation-1',
        manifest_version: 3,
        source_sha256: 'c'.repeat(64),
        content_profile: 'CATALOG_METADATA_ROWS_CSV_V1',
        parser_version: 'catalog-parser-v1',
        scanner_version: 'scanner-v1',
        schema_version: 'catalog-schema-v1',
        configuration_hash: 'd'.repeat(64),
        item_count: 2,
        candidate_count: 1,
        candidate_root_hash: 'e'.repeat(64),
        receipt_hash: 'f'.repeat(64),
        observed_at: '2026-01-01T00:00:00Z',
        created_at: '2026-01-01T00:00:00Z',
      },
      meta: {
        projection_version: 3,
        policy_version: 'test',
        classification_policy_version: 1,
        authorization_generation: 2,
      },
    }
    const request = vi.fn((path: string, options?: RequestOptions) => {
      if (path.startsWith('/catalog/tree')) return Promise.resolve(emptyTree)
      if (path === '/uploads?limit=50') return Promise.resolve({ items: [upload] })
      if (path === '/uploads/upload-1/preparations?limit=20') {
        return Promise.resolve({ items: [ready] })
      }
      if (
        path
        === '/uploads/upload-1/preparations/preparation-1/metadata-candidates?limit=20'
      ) return Promise.resolve(firstPage)
      if (
        path
        === '/uploads/upload-1/preparations/preparation-1/metadata-candidates?limit=20&cursor=metadata-page-2'
      ) {
        return Promise.resolve({
          ...firstPage,
          items: [{
            ...candidate,
            id: 'metadata-candidate-2',
            ordinal: 2,
            record_kind: 'DATASET_TAG',
            candidate_kind: 'DATASET_TAG_ADD',
            aspect_name: 'globalTags',
            operation_count: 1,
            field_path_sample: [],
            controlled_reference_count: 1,
          }],
          page: { limit: 20 },
        })
      }
      if (
        path
        === '/uploads/upload-1/preparations/preparation-1/metadata-candidates/metadata-candidate-1/preview'
      ) {
        return Promise.resolve({
          candidate_id: 'metadata-candidate-1',
          target_asset_id: 'asset-1',
          platform: 'postgres',
          database_name: 'fab',
          schema_name: 'quality',
          table_name: 'wafer_events',
          record_kind: 'COLUMN_DESCRIPTION',
          candidate_kind: 'COLUMN_DESCRIPTION_UPDATE',
          aspect_name: 'schemaMetadata',
          operation_count: 2,
          description_change_count: 2,
          description_change_sample: [
            {
              field_path: 'event_id',
              current_description: 'Old identifier',
              proposed_description: 'Stable event identifier',
            },
            {
              field_path: 'event_time',
              current_description: null,
              proposed_description: 'Event occurrence time',
            },
          ],
          description_changes_truncated: false,
          current_reference_count: 0,
          proposed_reference_count: 0,
          before_hash: '1'.repeat(64),
          after_hash: '2'.repeat(64),
          source_version: 'provider-v7',
          observed_at: '2026-01-01T00:00:00Z',
          preview_etag: `"${'3'.repeat(64)}"`,
          target_ref: 'urn:li:dataset:must-not-enter-ui-state',
          controlled_ref: 'urn:li:tag:must-not-enter-ui-state',
          after_document: { secret: 'raw-after-document-secret' },
          bucket: 'private-bucket',
        })
      }
      if (
        path
        === '/uploads/upload-1/preparations/preparation-1/metadata-candidates/metadata-candidate-1/change-request'
        && options?.method === 'POST'
      ) {
        createAttempts += 1
        if (createAttempts === 1) {
          return Promise.reject(new TypeError('response lost after server acceptance'))
        }
        return Promise.resolve({
          id: 'metadata-change-1',
          number: 'CR-METADATA-260101-ABCD',
          request_type: 'BULK_CATALOG_METADATA',
          state: 'REGISTERED',
          target_ref: 'urn:li:dataset:must-not-enter-ui-state',
          after_document: { secret: 'raw-after-document-secret' },
        })
      }
      throw new Error(`unexpected request: ${path}`)
    })

    render(<RegistrationPage client={clientWith(request)} />)
    fireEvent.click(await screen.findByRole('tab', { name: /BULK/ }))
    fireEvent.click(await screen.findByRole('button', { name: /catalog-metadata.csv/ }))
    fireEvent.click(await screen.findByRole('button', { name: '후보 조회' }))

    const preview = await screen.findByRole('region', { name: '등록 후보 미리보기' })
    expect(within(preview).getByText('컬럼 설명')).toBeInTheDocument()
    expect(within(preview).getByText('event_id, event_time')).toBeInTheDocument()
    expect(within(preview).queryByText(/must-not-enter-ui-state/)).not.toBeInTheDocument()
    expect(within(preview).queryByText(/raw-after-document-secret/)).not.toBeInTheDocument()
    expect(within(preview).queryByText(/private\/storage/)).not.toBeInTheDocument()
    expect(within(preview).queryByText('schemaMetadata')).not.toBeInTheDocument()

    fireEvent.click(within(preview).getByRole('button', { name: '검토 및 변경요청' }))
    expect(await within(preview).findByText('Stable event identifier')).toBeInTheDocument()
    expect(within(preview).getByText('Event occurrence time')).toBeInTheDocument()
    fireEvent.click(within(preview).getByRole('button', {
      name: '검증된 후보로 변경요청 생성',
    }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'response lost after server acceptance',
    )
    fireEvent.click(within(preview).getByRole('button', {
      name: '검증된 후보로 변경요청 생성',
    }))
    expect(await within(preview).findByText(/CR-METADATA-260101-ABCD/)).toBeInTheDocument()

    const createCalls = request.mock.calls.filter(([path]) => path.endsWith(
      '/metadata-candidates/metadata-candidate-1/change-request',
    ))
    expect(createCalls).toHaveLength(2)
    expect(createCalls[0]?.[1]?.ifMatch).toBe(`"${'3'.repeat(64)}"`)
    expect(createCalls[0]?.[1]?.idempotencyKey).toMatch(/^typed-catalog-metadata-change-/)
    expect(createCalls[1]?.[1]?.idempotencyKey).toBe(createCalls[0]?.[1]?.idempotencyKey)
    expect(JSON.parse(createCalls[0]?.[1]?.body as string)).toEqual({
      title: 'wafer_events 컬럼 설명 변경',
      reason: '검증된 BULK 업로드 후보를 변경관리 검토 대상으로 등록합니다.',
    })

    fireEvent.click(within(preview).getByRole('button', { name: '다음 후보' }))
    expect(await within(preview).findByText('태그 추가')).toBeInTheDocument()
    expect(within(preview).queryByText('컬럼 설명')).not.toBeInTheDocument()
    fireEvent.click(within(preview).getByRole('button', { name: '이전 후보' }))
    expect(await within(preview).findByText('컬럼 설명')).toBeInTheDocument()
    expect(within(preview).queryByText('태그 추가')).not.toBeInTheDocument()
  })

  it('downloads the server-versioned template only for the new typed profiles', async () => {
    const request = vi.fn((path: string) => Promise.resolve(
      path.startsWith('/uploads') ? { items: [] } : emptyTree,
    ))
    const download = vi.fn().mockResolvedValue({
      blob: new Blob([
        'record_kind,asset_id,platform,database_name,schema_name,table_name,field_path,operation,value_text,controlled_ref\n',
      ], { type: 'text/csv' }),
      filename: 'catalog-metadata-template-v3.csv',
      etag: '"template-v3"',
    })
    const createObjectURL = vi.fn().mockReturnValue('blob:template-v3')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL,
      revokeObjectURL,
    })
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    render(<RegistrationPage client={clientWith(request, undefined, download)} />)
    fireEvent.click(await screen.findByRole('tab', { name: /BULK/ }))
    const profile = screen.getByLabelText('등록 프로파일')

    expect(screen.queryByRole('button', { name: '서버 템플릿 받기' }))
      .not.toBeInTheDocument()
    fireEvent.change(profile, { target: { value: 'CATALOG_METADATA_ROWS_CSV_V1' } })
    fireEvent.click(screen.getByRole('button', { name: '서버 템플릿 받기' }))
    await waitFor(() => expect(download).toHaveBeenCalledOnce())
    const downloadCall = download.mock.calls[0] as unknown as [
      string,
      { signal?: AbortSignal },
    ]
    expect(downloadCall[0]).toBe('/uploads/profiles/CATALOG_METADATA_ROWS_CSV_V1/template')
    expect(downloadCall[1].signal).toBeInstanceOf(AbortSignal)
    expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob))
    expect(anchorClick).toHaveBeenCalledOnce()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:template-v3')
    expect(document.querySelector('a[href^="data:"]')).not.toBeInTheDocument()
    expect(document.querySelector('input[type="file"]')).toHaveAttribute(
      'accept',
      '.csv,text/csv',
    )

    fireEvent.change(profile, { target: { value: 'CATALOG_METADATA_ROWS_XLSX_V1' } })
    expect(document.querySelector('input[type="file"]')).toHaveAttribute(
      'accept',
      '.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    anchorClick.mockRestore()
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
      fireEvent.click(await screen.findByRole('tab', { name: /BULK/ }))
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
    fireEvent.click(await screen.findByRole('tab', { name: /BULK/ }))
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
    fireEvent.click(await screen.findByRole('tab', { name: /BULK/ }))
    fireEvent.click(await screen.findByRole('button', { name: /rejected.csv/ }))

    const validationStage = screen.getByText('Validation').closest('li')
    expect(validationStage).not.toBeNull()
    expect(validationStage).toHaveClass('failed')
    expect(within(validationStage as HTMLElement).getByText('실패')).toBeInTheDocument()
  })
})
