import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient, RequestOptions } from '../../api/client'
import type { ChangeRequestRecord } from '../../api/types'
import { ChangeRequestCreateDialog } from './ChangeRequestCreateDialog'

function apiClient(request: (path: string, options?: RequestOptions) => Promise<unknown>): ApiClient {
  return { request } as unknown as ApiClient
}

function renderDialog(client: ApiClient, onCreated = vi.fn()) {
  render(<ChangeRequestCreateDialog
    open
    client={client}
    requesterName="Test Requester"
    requesterEmail="requester@example.test"
    onClose={vi.fn()}
    onCreated={onCreated}
  />)
  return { onCreated }
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
      if (path.startsWith('/catalog/assets?q=wafer')) return Promise.resolve({ items: [asset] })
      if (path === `/catalog/assets/${asset.id}`) return Promise.resolve({
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
    const searchedColumnPicker = await screen.findByLabelText('wafer_events 컬럼 추가')
    expect(searchedColumnPicker.parentElement).toHaveClass('governance-target-add-column')

    fireEvent.click(screen.getByRole('button', { name: /ADD NEW TABLE MANUALLY/ }))
    const manualColumnButton = screen.getByRole('button', { name: '신규 테이블 2 컬럼 추가' })
    expect(manualColumnButton).toHaveClass('governance-target-add-column')
    expect(searchedColumnPicker.parentElement).toHaveClass(
      ...Array.from(manualColumnButton.classList),
    )
  })

  it('reports missing required fields, then submits a complete manual request', async () => {
    const created = {
      id: 'change-1',
      number: 'CR-FAB-2026-0001',
    } as ChangeRequestRecord
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      if (path === '/change-requests/systems') return Promise.resolve({
        items: [{ id: 'system-1', code: 'FAB', name: 'Fabrication' }],
      })
      if (path === '/change-requests/intake' && options?.method === 'POST') {
        return Promise.resolve(created)
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    const onCreated = vi.fn()
    renderDialog(apiClient(request), onCreated)

    await screen.findByRole('option', { name: 'Fabrication · FAB' })
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
    fireEvent.click(screen.getByRole('button', { name: /ADD NEW TABLE MANUALLY/ }))
    fireEvent.change(screen.getByLabelText('신규 테이블 1 테이블명'), {
      target: { value: 'wafer_summary' },
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
    expect(onCreated).toHaveBeenCalledWith(created)
  })
})
