import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient, RequestOptions } from '../../api/client'
import type { ChangeRequestRecord } from '../../api/types'
import { ChangeRequestCreateDialog } from './ChangeRequestCreateDialog'

function apiClient(request: (path: string, options?: RequestOptions) => Promise<unknown>): ApiClient {
  return { request } as unknown as ApiClient
}

function renderDialog(
  client: ApiClient,
  onCreated = vi.fn(),
  revision?: ChangeRequestRecord,
) {
  const onClose = vi.fn()
  render(<ChangeRequestCreateDialog
    open
    client={client}
    requesterName="Test Requester"
    requesterEmail="requester@example.test"
    revision={revision}
    onClose={onClose}
    onCreated={onCreated}
  />)
  return { onCreated, onClose }
}

function editableRevision(): ChangeRequestRecord {
  return {
    id: 'change-revision-1',
    number: 'CR-SCT-2026-1',
    request_type: 'CHANGE_INTAKE',
    title: 'Current intake title',
    description: 'Current reason\nCurrent content',
    state: 'CHANGES_REQUESTED',
    requester_id: 'requester-1',
    requester_department_id: null,
    current_round_id: 'round-1',
    current_round_number: 1,
    revision_allowed: true,
    created_at: '2026-08-02T01:02:03Z',
    requested_due_date: '2026-08-20',
    priority: 'HIGH',
    urgency: 'URGENT',
    classification: 'CONFIDENTIAL',
    version: 11,
    items: [
      {
        id: 'item-existing-1',
        target_type: 'DATAHUB_DATASET_CHANGE_INTAKE',
        target_ref: 'urn:li:dataset:(urn:li:dataPlatform:postgres,erp.orders,PROD)',
        aspect_name: 'changeIntake',
        operation: 'REVIEW',
        after_document: {
          contract: 'change-intake-v1',
          kind: 'EXISTING',
          requested: {
            description: 'Requested orders description',
            requested_change: 'Clarify order metadata',
            tags: ['tier:gold'],
            terms: ['Order'],
            columns: [{
              field_path: 'order_id',
              source: { data_type: 'uuid', description: 'Current order ID', tags: [], terms: [] },
              requested: {
                data_type: 'uuid',
                description: 'Requested order ID',
                requested_change: 'Clarify identifier',
                tags: ['identifier'],
                terms: ['Order ID'],
              },
            }],
          },
        },
        target_asset_id: 'catalog-asset-1',
        target_asset_type: 'VIEW',
        target_system_id: 'system-1',
        target_domain_id: null,
        target_owner_department_id: null,
        target_classification: 'CONFIDENTIAL',
        target_lifecycle: 'ACTIVE',
        target_source_version: 'source-v1',
        target_observed_at: '2026-08-02T01:02:03Z',
        target_binding_hash: 'binding-1',
        routing_system_id: 'system-1',
      },
      {
        id: 'item-manual-1',
        target_type: 'PROPOSED_DATASET_CHANGE_INTAKE',
        target_ref: 'urn:datariver:proposed-dataset:item-manual-1',
        aspect_name: 'changeIntake',
        operation: 'CREATE',
        after_document: {
          contract: 'change-intake-v1',
          kind: 'MANUAL',
          database_name: 'analytics',
          schema_name: 'quality',
          table_name: 'wafer_summary',
          owner: 'Data Engineering',
          description: 'Requested wafer summary',
          requested_change: 'Create a governed dataset',
          tags: ['tier:silver'],
          terms: ['Wafer'],
          columns: [{
            field_path: 'wafer_id',
            data_type: 'uuid',
            description: 'Wafer identifier',
            requested_change: 'Create primary identifier',
            tags: ['identifier'],
            terms: ['Wafer ID'],
          }],
        },
        target_asset_id: null,
        target_asset_type: null,
        target_system_id: null,
        target_domain_id: null,
        target_owner_department_id: null,
        target_classification: null,
        target_lifecycle: null,
        target_source_version: null,
        target_observed_at: null,
        target_binding_hash: null,
        routing_system_id: 'system-1',
      },
    ],
    approvals: [],
    transitions: [],
    rounds: [{
      id: 'round-1',
      round_number: 1,
      submitted_by: 'requester-1',
      submitted_at: '2026-08-02T01:02:03Z',
      closed_at: null,
      evidence_hash: 'a'.repeat(64),
      revision_kind: 'INITIAL',
      title: 'Current intake title',
      request_date: '2026-08-02',
      request_department: 'Data Platform',
      request_reason: 'Current reason',
      request_content: 'Current content',
      requested_due_date: '2026-08-20',
      priority: 'HIGH',
      urgency: 'URGENT',
      classification: 'CONFIDENTIAL',
      selected_system_id: 'system-1',
    }],
    test_runs: [],
  }
}

describe('ChangeRequestCreateDialog', () => {
  it('keeps target file actions beside search and explains an unavailable system on submit', async () => {
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      void options
      if (path === '/change-requests/systems') return Promise.resolve({ items: [] })
      throw new Error(`Unexpected request: ${path}`)
    })
    renderDialog(apiClient(request))

    await waitFor(() => expect(request).toHaveBeenCalled())
    const systemsOptions = request.mock.calls.find(
      ([path]) => path === '/change-requests/systems',
    )?.[1]
    expect(systemsOptions?.signal).toBeInstanceOf(AbortSignal)
    const targetControls = screen.getByLabelText('변경 대상 검색')
      .closest('.governance-target-controls')
    expect(targetControls).not.toBeNull()
    expect(within(targetControls as HTMLElement).getByRole('button', {
      name: '양식 다운로드',
    })).toBeInTheDocument()
    expect(within(targetControls as HTMLElement).getByRole('button', {
      name: '엑셀 업로드',
    })).toBeInTheDocument()

    const submit = screen.getByRole('button', { name: 'CR 제출' })
    expect(submit).toBeEnabled()
    fireEvent.click(submit)
    expect(await screen.findByRole('status')).toHaveTextContent(
      '등록 가능한 활성 시스템이 없습니다.',
    )
  })

  it('uses the same add-column control shape for searched and manual tables', async () => {
    const asset = {
      id: 'catalog-asset-1',
      external_urn: 'urn:li:dataset:(urn:li:dataPlatform:postgres,fab.wafer_events,PROD)',
      asset_type: 'DATASET',
      name: 'wafer_events',
      platform: 'postgres',
      database_name: 'fab',
      schema_name: 'quality',
      classification: 'INTERNAL',
      lifecycle: 'ACTIVE',
      observed_at: '2026-07-31T01:02:03Z',
      matches: [],
      tags: [],
      terms: [],
    }
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/change-requests/systems') return Promise.resolve({
        items: [{ id: 'system-1', code: 'FAB', name: 'Fabrication' }],
      })
      if (path.startsWith('/change-requests/targets?system_id=system-1&q=wafer')) return Promise.resolve({ items: [asset] })
      if (path === `/change-requests/targets/${asset.id}?system_id=system-1`) return Promise.resolve({
        ...asset,
        description: 'Current wafer event table',
        ownership: [],
        glossary_terms: [],
        quality: {},
        projection_source_version: 'projection-v1',
        source_version: 'source-v1',
        schema_fields: [{
          fieldPath: 'wafer_id',
          nativeDataType: 'uuid',
          description: 'Wafer identifier',
        }],
      })
      throw new Error(`Unexpected request: ${path}`)
    })
    renderDialog(apiClient(request))

    fireEvent.change(screen.getByLabelText('변경 대상 검색'), {
      target: { value: 'wafer' },
    })
    fireEvent.click(await screen.findByRole('button', { name: /wafer_events/ }))
    const searchedColumnPicker = await screen.findByLabelText('wafer_events 기존 컬럼 선택')
    expect(searchedColumnPicker.parentElement).toHaveClass('governance-target-add-column')

    fireEvent.click(screen.getByRole('button', { name: /ADD NEW TABLE MANUALLY/ }))
    const manualColumnButton = screen.getByRole('button', { name: '신규 테이블 2 컬럼 추가' })
    expect(manualColumnButton).toHaveClass('governance-target-add-column')
    expect(searchedColumnPicker.parentElement).toHaveClass(
      ...Array.from(manualColumnButton.classList),
    )
  })

  it('does not search without a system and clears stale targets when the system changes', async () => {
    const asset = {
      id: 'catalog-asset-1',
      external_urn: 'urn:li:dataset:(urn:li:dataPlatform:postgres,fab.wafer_events,PROD)',
      asset_type: 'TABLE',
      name: 'wafer_events',
      platform: 'postgres',
      database_name: 'fab',
      schema_name: 'quality',
      classification: 'INTERNAL',
      lifecycle: 'ACTIVE',
      observed_at: '2026-07-31T01:02:03Z',
      matches: [],
      tags: [],
      terms: [],
    }
    let resolveSystems: ((value: unknown) => void) | undefined
    const systems = new Promise((resolve) => { resolveSystems = resolve })
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      void options
      if (path === '/change-requests/systems') return systems
      if (path.startsWith('/change-requests/targets?system_id=system-1&q=wafer')) {
        return Promise.resolve({ items: [asset] })
      }
      if (path === `/change-requests/targets/${asset.id}?system_id=system-1`) {
        return Promise.resolve({
          ...asset,
          description: 'Current wafer event table',
          ownership: [],
          glossary_terms: [],
          quality: {},
          projection_source_version: 'projection-v1',
          source_version: 'source-v1',
          schema_fields: [{ fieldPath: 'wafer_id', nativeDataType: 'uuid' }],
        })
      }
      if (path.startsWith('/change-requests/targets?system_id=system-2&q=lot')) {
        return Promise.resolve({ items: [] })
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    renderDialog(apiClient(request))

    fireEvent.change(screen.getByLabelText('변경 대상 검색'), {
      target: { value: 'wafer' },
    })
    await new Promise((resolve) => window.setTimeout(resolve, 250))
    expect(request.mock.calls.some(([path]) => path.includes('/change-requests/targets?'))).toBe(false)

    resolveSystems?.({
      items: [
        { id: 'system-1', code: 'FAB', name: 'Fabrication' },
        { id: 'system-2', code: 'ERP', name: 'Enterprise Resource Planning' },
      ],
    })
    await screen.findByRole('option', { name: 'Fabrication · FAB' })
    fireEvent.change(screen.getByLabelText('변경 대상 검색'), {
      target: { value: 'wafer' },
    })
    fireEvent.click(await screen.findByRole('button', { name: /wafer_events/ }))
    const columnPicker = await screen.findByLabelText('wafer_events 기존 컬럼 선택')
    fireEvent.change(columnPicker, { target: { value: 'wafer_id' } })
    expect(screen.getByText('wafer_id')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('관련 시스템'), {
      target: { value: 'system-2' },
    })

    expect(screen.queryByText('wafer_id')).not.toBeInTheDocument()
    expect(screen.queryByRole('table', { name: '변경 대상 테이블 및 컬럼' })).not.toBeInTheDocument()
    expect(screen.getByLabelText('변경 대상 검색')).toHaveValue('')
    fireEvent.change(screen.getByLabelText('변경 대상 검색'), {
      target: { value: 'lot' },
    })
    await waitFor(() => expect(request.mock.calls.some(
      ([path]) => path.includes('/change-requests/targets?system_id=system-2&q=lot'),
    )).toBe(true))
    const targetOptions = request.mock.calls.find(
      ([path]) => path.includes('/change-requests/targets?system_id=system-2&q=lot'),
    )?.[1]
    expect(targetOptions?.signal).toBeInstanceOf(AbortSignal)
  })

  it('keeps focus while typing consecutive characters in a manual column name', async () => {
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/change-requests/systems') return Promise.resolve({
        items: [{ id: 'system-1', code: 'FAB', name: 'Fabrication' }],
      })
      throw new Error(`Unexpected request: ${path}`)
    })
    renderDialog(apiClient(request))

    await screen.findByRole('option', { name: 'Fabrication · FAB' })
    fireEvent.click(screen.getByRole('button', { name: /ADD NEW TABLE MANUALLY/ }))
    fireEvent.click(screen.getByRole('button', { name: '신규 테이블 1 컬럼 추가' }))
    const columnName = screen.getByRole('textbox', { name: '신규 테이블 1 컬럼 1 이름' })
    columnName.focus()

    fireEvent.change(columnName, { target: { value: 's' } })
    expect(columnName).toHaveFocus()
    fireEvent.change(columnName, { target: { value: 'ss' } })

    expect(columnName).toHaveFocus()
    expect(columnName).toHaveValue('ss')
  })

  it('ignores backdrop and Escape and applies the dirty guard only to explicit cancel', async () => {
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/change-requests/systems') return Promise.resolve({
        items: [{ id: 'system-1', code: 'FAB', name: 'Fabrication' }],
      })
      throw new Error(`Unexpected request: ${path}`)
    })
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const { onClose } = renderDialog(apiClient(request))
    const dialog = await screen.findByRole('dialog', { name: '신규 CR 신청' })

    fireEvent.keyDown(dialog, { key: 'Escape' })
    fireEvent.click(dialog)
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: '신규 CR 신청 닫기' })).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('변경요청 제목'), { target: { value: '작성 중' } })
    fireEvent.click(screen.getByRole('button', { name: '취소' }))
    expect(confirm).toHaveBeenCalledOnce()
    expect(onClose).not.toHaveBeenCalled()

    confirm.mockReturnValue(true)
    fireEvent.click(screen.getByRole('button', { name: '취소' }))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('locks the exact DataHub classification and submits a validated new-column proposal', async () => {
    const asset = {
      id: 'catalog-asset-1',
      external_urn: 'urn:li:dataset:(urn:li:dataPlatform:postgres,erp.orders,PROD)',
      asset_type: 'DATASET', name: 'orders', platform: 'postgres', database_name: 'erp',
      schema_name: 'public', classification: 'CONFIDENTIAL', lifecycle: 'ACTIVE',
      observed_at: '2026-08-30T01:02:03Z', matches: [], tags: ['Classification:CONFIDENTIAL'], terms: [],
      classification_resolution: { status: 'EXACT', values: ['CONFIDENTIAL'], value: 'CONFIDENTIAL' },
    }
    const created = { id: 'change-1', number: 'CR-1' } as ChangeRequestRecord
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      if (path === '/change-requests/systems') return Promise.resolve({
        items: [{ id: 'system-1', code: 'ERP', name: 'ERP' }],
      })
      if (path.includes('/change-requests/targets?')) return Promise.resolve({ items: [asset] })
      if (path.startsWith('/change-requests/targets/')) return Promise.resolve({
        ...asset, description: '', ownership: [], glossary_terms: [], quality: {},
        projection_source_version: 'projection-1', source_version: 'source-1',
        schema_fields: [{ fieldPath: 'order_id', nativeDataType: 'uuid' }],
      })
      if (path === '/change-requests/intake' && options?.method === 'POST') return Promise.resolve(created)
      throw new Error(`Unexpected request: ${path}`)
    })
    renderDialog(apiClient(request))
    await screen.findByRole('option', { name: 'ERP · ERP' })
    fireEvent.change(screen.getByLabelText('변경요청 제목'), { target: { value: '신규 컬럼 제안' } })
    fireEvent.change(screen.getByLabelText('요청사유'), { target: { value: '스키마 확장' } })
    fireEvent.change(screen.getByLabelText('변경 대상 검색'), { target: { value: 'orders' } })
    fireEvent.click(await screen.findByRole('button', { name: /orders/ }))

    await waitFor(() => expect(screen.getByLabelText('보안등급')).toHaveValue('CONFIDENTIAL'))
    const classification = screen.getByLabelText('보안등급')
    expect(classification).toHaveAttribute('readonly')
    fireEvent.click(screen.getByRole('button', { name: 'orders 신규 컬럼 추가' }))
    const name = screen.getByLabelText('orders 컬럼 1 이름')
    fireEvent.change(name, { target: { value: 'order_id' } })
    fireEvent.change(screen.getByLabelText('order_id 데이터 타입'), { target: { value: 'uuid' } })
    fireEvent.click(screen.getByRole('button', { name: 'CR 제출' }))
    expect(await screen.findByRole('status')).toHaveTextContent('기존 컬럼 충돌')
    expect(request.mock.calls.some(([path]) => path === '/change-requests/intake')).toBe(false)

    fireEvent.change(name, { target: { value: 'external_reference' } })
    fireEvent.change(screen.getByLabelText('external_reference 데이터 타입'), { target: { value: 'varchar(128)' } })
    fireEvent.click(screen.getByLabelText('external_reference NULL 허용'))
    fireEvent.change(screen.getByLabelText('external_reference 배치 순서'), { target: { value: '2' } })
    fireEvent.click(screen.getByRole('button', { name: 'CR 제출' }))

    await waitFor(() => expect(request.mock.calls.some(([path]) => path === '/change-requests/intake')).toBe(true))
    const options = request.mock.calls.find(([path]) => path === '/change-requests/intake')?.[1]
    if (typeof options?.body !== 'string') throw new Error('Expected CR JSON body')
    const body = JSON.parse(options.body) as {
      security_level: string
      targets: Array<{ columns: Array<Record<string, unknown>> }>
    }
    expect(body.security_level).toBe('CONFIDENTIAL')
    expect(body.targets[0]?.columns[0]).toEqual(expect.objectContaining({
      proposal_kind: 'NEW', field_path: 'external_reference', data_type: 'varchar(128)',
      nullable: false, ordinal: 2,
    }))
  })

  it('blocks a missing DataHub classification before submission', async () => {
    const asset = {
      id: 'catalog-asset-1', external_urn: 'urn:li:dataset:(urn:li:dataPlatform:postgres,erp.orders,PROD)',
      asset_type: 'DATASET', name: 'orders', platform: 'postgres', database_name: 'erp', schema_name: 'public',
      classification: '', lifecycle: 'ACTIVE', observed_at: '2026-08-30T01:02:03Z', matches: [], tags: [], terms: [],
      classification_resolution: { status: 'MISSING', values: [], value: null },
    }
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/change-requests/systems') return Promise.resolve({ items: [{ id: 'system-1', code: 'ERP', name: 'ERP' }] })
      if (path.includes('/change-requests/targets?')) return Promise.resolve({ items: [asset] })
      if (path.startsWith('/change-requests/targets/')) return Promise.resolve({
        ...asset, ownership: [], glossary_terms: [], quality: {}, projection_source_version: 'p1', source_version: 's1', schema_fields: [],
      })
      throw new Error(`Unexpected request: ${path}`)
    })
    renderDialog(apiClient(request))
    await screen.findByRole('option', { name: 'ERP · ERP' })
    fireEvent.change(screen.getByLabelText('변경요청 제목'), { target: { value: '분류 검증' } })
    fireEvent.change(screen.getByLabelText('요청사유'), { target: { value: '분류 검증' } })
    fireEvent.change(screen.getByLabelText('변경 대상 검색'), { target: { value: 'orders' } })
    fireEvent.click(await screen.findByRole('button', { name: /orders/ }))
    fireEvent.click(screen.getByRole('button', { name: 'CR 제출' }))
    expect(await screen.findByRole('status')).toHaveTextContent('DataHub 분류 태그가 없는 대상')
    expect(request.mock.calls.some(([path]) => path === '/change-requests/intake')).toBe(false)
  })

  it('reports missing fields, then submits existing and manual targets together', async () => {
    let attachmentUploadId = ''
    const asset = {
      id: 'catalog-asset-1',
      external_urn: 'urn:li:dataset:(urn:li:dataPlatform:postgres,erp.orders,PROD)',
      asset_type: 'VIEW',
      name: 'orders',
      platform: 'postgres',
      database_name: 'erp',
      schema_name: 'public',
      classification: 'INTERNAL',
      lifecycle: 'ACTIVE',
      observed_at: '2026-07-31T01:02:03Z',
      matches: [],
      tags: [],
      terms: [],
    }
    const created = {
      id: 'change-1',
      number: 'CR-FAB-2026-0001',
    } as ChangeRequestRecord
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      if (path === '/change-requests/systems') return Promise.resolve({
        items: [
          { id: 'system-1', code: 'FAB', name: 'Fabrication' },
          { id: 'system-2', code: 'ERP', name: 'Enterprise Resource Planning' },
        ],
      })
      if (path.startsWith('/change-requests/targets?system_id=system-2&q=orders')) {
        return Promise.resolve({ items: [asset] })
      }
      if (path === `/change-requests/targets/${asset.id}?system_id=system-2`) {
        return Promise.resolve({
          ...asset,
          description: 'Current orders view',
          ownership: [],
          glossary_terms: [],
          quality: {},
          projection_source_version: 'projection-v1',
          source_version: 'source-v1',
          schema_fields: [{
            fieldPath: 'order_id',
            nativeDataType: 'uuid',
            description: 'Order identifier',
          }],
        })
      }
      if (path === '/change-requests/intake' && options?.method === 'POST') {
        return Promise.resolve(created)
      }
      if (path === `/change-requests/${created.id}/attachments` && options?.method === 'POST') {
        const body = options.body
        const uploadId = body instanceof FormData ? body.get('upload_id') : null
        attachmentUploadId = typeof uploadId === 'string' ? uploadId : ''
        return Promise.resolve({
          id: attachmentUploadId,
          change_request_id: created.id,
          round_id: 'round-1',
          kind: 'REQUEST',
          original_name: 'request-evidence.txt',
          state: 'STORED',
          expected_size_bytes: 8,
          expected_content_sha256: 'a'.repeat(64),
          provider_checksum: 'a'.repeat(64),
          failure_code: null,
          status_url: `/change-requests/${created.id}/attachment-uploads/${attachmentUploadId}`,
          finalize_url: `/change-requests/${created.id}/attachment-uploads/${attachmentUploadId}/finalize`,
        })
      }
      if (path === `/change-requests/${created.id}/attachment-uploads/${attachmentUploadId}/finalize` && options?.method === 'POST') {
        return Promise.resolve({})
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    const onCreated = vi.fn()
    renderDialog(apiClient(request), onCreated)

    await screen.findByRole('option', { name: 'Fabrication · FAB' })
    expect(screen.getByRole('option', {
      name: 'Enterprise Resource Planning · ERP',
    })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('관련 시스템'), {
      target: { value: 'system-2' },
    })
    const submit = screen.getByRole('button', { name: 'CR 제출' })
    fireEvent.click(submit)
    expect(await screen.findByRole('status')).toHaveTextContent('변경요청 제목')
    expect(screen.getByRole('status')).toHaveTextContent('요청사유')
    expect(screen.getByRole('status')).toHaveTextContent('변경 대상 테이블')

    fireEvent.change(screen.getByLabelText('변경요청 제목'), {
      target: { value: '신규 테이블 등록' },
    })
    fireEvent.change(screen.getByLabelText('요청사유'), {
      target: { value: '검증된 신규 데이터셋을 등록합니다.' },
    })
    fireEvent.change(screen.getByLabelText('변경 대상 검색'), {
      target: { value: 'orders' },
    })
    fireEvent.click(await screen.findByRole('button', { name: /orders/ }))
    fireEvent.change(await screen.findByLabelText('orders 기존 컬럼 선택'), {
      target: { value: 'order_id' },
    })
    fireEvent.click(screen.getByRole('button', { name: /ADD NEW TABLE MANUALLY/ }))
    fireEvent.change(screen.getByLabelText('신규 테이블 2 테이블명'), {
      target: { value: 'wafer_summary' },
    })
    fireEvent.change(screen.getByLabelText(/클릭하거나 파일을 드래그하세요/), {
      target: { files: [new File(['evidence'], 'request-evidence.txt', { type: 'text/plain' })] },
    })
    fireEvent.click(submit)

    await waitFor(() => expect(request).toHaveBeenCalledWith(
      '/change-requests/intake',
      expect.objectContaining({ method: 'POST' }),
    ))
    const intakeOptions = request.mock.calls.find(
      ([path]) => path === '/change-requests/intake',
    )?.[1]
    expect(intakeOptions?.idempotencyKey).toMatch(/^change-request-intake-/)
    expect(typeof intakeOptions?.body).toBe('string')
    if (typeof intakeOptions?.body !== 'string') throw new Error('Expected a JSON request body')
    expect(JSON.parse(intakeOptions.body)).toEqual(expect.objectContaining({
      system_id: 'system-2',
      targets: [
        expect.objectContaining({
          kind: 'EXISTING',
          asset_id: 'catalog-asset-1',
          columns: [expect.objectContaining({ field_path: 'order_id' })],
        }),
        expect.objectContaining({ kind: 'MANUAL', table_name: 'wafer_summary' }),
      ],
    }))
    expect(onCreated).toHaveBeenCalledWith(created)
    expect(attachmentUploadId).toMatch(/^[0-9a-f-]{36}$/)
    expect(request).toHaveBeenCalledWith(
      `/change-requests/${created.id}/attachment-uploads/${attachmentUploadId}/finalize`,
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('reuses the bounded editor for one fixed-system revision POST', async () => {
    const original = editableRevision()
    const revised: ChangeRequestRecord = {
      ...original,
      title: 'Revised intake title',
      state: 'REGISTERED',
      current_round_id: 'round-2',
      current_round_number: 2,
      revision_allowed: false,
      version: 12,
      rounds: [...original.rounds, {
        ...original.rounds[0]!,
        id: 'round-2',
        round_number: 2,
        revision_kind: 'EDITED',
        title: 'Revised intake title',
        evidence_hash: 'b'.repeat(64),
      }],
    }
    let finishRevision!: (value: ChangeRequestRecord) => void
    const revisionResponse = new Promise<ChangeRequestRecord>((resolve) => {
      finishRevision = resolve
    })
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      if (path === `/change-requests/${original.id}/revision-targets/catalog-asset-1`) {
        return Promise.resolve({
          id: 'catalog-asset-1',
          external_urn: original.items[0]!.target_ref,
          asset_type: 'VIEW',
          name: 'orders',
          platform: 'postgres',
          database_name: 'erp',
          schema_name: 'public',
          classification: 'CONFIDENTIAL',
          lifecycle: 'ACTIVE',
          observed_at: '2026-08-02T01:02:03Z',
          matches: [],
          tags: [],
          terms: [],
          description: 'Current orders description',
          ownership: [],
          glossary_terms: [],
          quality: {},
          projection_source_version: 'projection-v1',
          source_version: 'source-v1',
          schema_fields: [{
            fieldPath: 'order_id',
            nativeDataType: 'uuid',
            description: 'Current order ID',
          }],
        })
      }
      if (path === `/change-requests/${original.id}/revision-targets?q=ledger&limit=12`) {
        return Promise.resolve({ items: [] })
      }
      if (path === `/change-requests/${original.id}/revisions` && options?.method === 'POST') {
        return revisionResponse
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    const onCreated = vi.fn()
    renderDialog(apiClient(request), onCreated, original)

    expect(await screen.findByDisplayValue('Current intake title')).toBeInTheDocument()
    expect(screen.getByLabelText('관련 시스템')).toHaveValue('system-1')
    expect(screen.getByLabelText('관련 시스템')).toHaveAttribute('readonly')
    expect(screen.queryByRole('combobox', { name: '관련 시스템' })).not.toBeInTheDocument()
    expect(screen.getByLabelText('orders 설명')).toHaveValue('Requested orders description')
    expect(screen.getByLabelText('order_id 설명')).toHaveValue('Requested order ID')
    expect(screen.getByLabelText('신규 테이블 2 테이블명')).toHaveValue('wafer_summary')
    expect(screen.getByLabelText('wafer_summary 컬럼 1 이름')).toHaveValue('wafer_id')
    expect(request.mock.calls.some(([path]) => path === '/change-requests/systems')).toBe(false)

    fireEvent.change(screen.getByLabelText('변경 대상 검색'), {
      target: { value: 'ledger' },
    })
    await waitFor(() => expect(request.mock.calls.some(
      ([path]) => path === `/change-requests/${original.id}/revision-targets?q=ledger&limit=12`,
    )).toBe(true))
    const searchOptions = request.mock.calls.find(
      ([path]) => path === `/change-requests/${original.id}/revision-targets?q=ledger&limit=12`,
    )?.[1]
    expect(searchOptions?.signal).toBeInstanceOf(AbortSignal)
    fireEvent.change(screen.getByLabelText('변경요청 제목'), {
      target: { value: 'Revised intake title' },
    })
    fireEvent.change(screen.getByLabelText('orders 설명'), {
      target: { value: 'Revised orders description' },
    })
    fireEvent.change(screen.getByLabelText('신규 테이블 2 테이블명'), {
      target: { value: 'wafer_summary_v2' },
    })
    const submit = screen.getByRole('button', { name: '수정 재상신' })
    fireEvent.click(submit)

    await waitFor(() => expect(request.mock.calls.filter(
      ([path]) => path === `/change-requests/${original.id}/revisions`,
    )).toHaveLength(1))
    expect(submit).toBeDisabled()
    fireEvent.click(submit)
    expect(request.mock.calls.filter(
      ([path]) => path === `/change-requests/${original.id}/revisions`,
    )).toHaveLength(1)
    const revisionOptions = request.mock.calls.find(
      ([path]) => path === `/change-requests/${original.id}/revisions`,
    )?.[1]
    expect(revisionOptions).toMatchObject({ method: 'POST', ifMatch: '"11"' })
    expect(revisionOptions?.idempotencyKey).toMatch(/^change-request-revision-/)
    if (typeof revisionOptions?.body !== 'string') throw new Error('Expected a revision JSON body')
    expect(JSON.parse(revisionOptions.body)).toEqual(expect.objectContaining({
      title: 'Revised intake title',
      system_id: 'system-1',
      request_date: '2026-08-02',
      request_department: 'Data Platform',
      request_reason: 'Current reason',
      request_content: 'Current content',
      security_level: 'CONFIDENTIAL',
      targets: [
        expect.objectContaining({
          kind: 'EXISTING',
          asset_id: 'catalog-asset-1',
          description: 'Revised orders description',
          columns: [expect.objectContaining({ field_path: 'order_id' })],
        }),
        expect.objectContaining({
          kind: 'MANUAL',
          table_name: 'wafer_summary_v2',
          columns: [expect.objectContaining({ field_path: 'wafer_id' })],
        }),
      ],
    }))

    finishRevision(revised)
    expect(await screen.findByRole('status')).toHaveTextContent('새 회차로 재상신했습니다.')
    expect(onCreated).toHaveBeenCalledOnce()
    expect(onCreated).toHaveBeenCalledWith(revised)
  })

  it('preserves the original round and draft when revision submission fails', async () => {
    const original = editableRevision()
    const originalSnapshot = structuredClone(original)
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      if (path === `/change-requests/${original.id}/revision-targets/catalog-asset-1`) {
        return Promise.resolve({
          id: 'catalog-asset-1',
          external_urn: original.items[0]!.target_ref,
          asset_type: 'VIEW',
          name: 'orders',
          platform: 'postgres',
          database_name: 'erp',
          schema_name: 'public',
          classification: 'CONFIDENTIAL',
          lifecycle: 'ACTIVE',
          observed_at: '2026-08-02T01:02:03Z',
          matches: [],
          tags: [],
          terms: [],
          description: 'Current orders description',
          ownership: [],
          glossary_terms: [],
          quality: {},
          projection_source_version: 'projection-v1',
          source_version: 'source-v1',
          schema_fields: [{ fieldPath: 'order_id', nativeDataType: 'uuid' }],
        })
      }
      if (path === `/change-requests/${original.id}/revisions` && options?.method === 'POST') {
        return Promise.reject(new Error('revision failed'))
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    const onCreated = vi.fn()
    renderDialog(apiClient(request), onCreated, original)

    await screen.findByDisplayValue('Current intake title')
    fireEvent.change(screen.getByLabelText('변경요청 제목'), {
      target: { value: 'Draft remains visible' },
    })
    fireEvent.click(screen.getByRole('button', { name: '수정 재상신' }))

    expect(await screen.findByText('revision failed')).toBeInTheDocument()
    expect(request.mock.calls.filter(
      ([path]) => path === `/change-requests/${original.id}/revisions`,
    )).toHaveLength(1)
    expect(onCreated).not.toHaveBeenCalled()
    expect(screen.getByLabelText('변경요청 제목')).toHaveValue('Draft remains visible')
    expect(original).toEqual(originalSnapshot)
  })
})
