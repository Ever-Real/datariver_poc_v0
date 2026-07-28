import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiClient } from '../../../../api/client'
import { DataEnricherStep } from './DataEnricherStep'

const draftId = '019fa57b-52de-74c0-9f5e-06ae7b1bf3b0'
const assetId = '019fa57b-52de-74c0-9f5e-06ae7b1bf3b1'

function draft(version: number) {
  return {
    id: draftId,
    author_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3b2',
    kind: 'CREATE',
    state: 'DRAFT',
    current_step: 'ABOX',
    name: '임직원 지식 그래프',
    endpoint_alias: 'employee_graph',
    domain_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3b3',
    domain_source_version: 'domain-v1',
    classification: 'INTERNAL',
    last_autosaved_at: '2026-07-28T04:00:00Z',
    version,
    created_at: '2026-07-28T03:00:00Z',
    updated_at: '2026-07-28T04:00:00Z',
  }
}

const tboxElements = [
  {
    stable_element_id: 'class.employee',
    kind: 'CLASS',
    canonical_name: 'Employee',
    display_name: 'Employee',
    ordinal: 0,
    version: 2,
  },
  {
    stable_element_id: 'property.employee.id',
    kind: 'PROPERTY',
    canonical_name: 'employeeId',
    display_name: 'employeeId',
    parent_stable_element_id: 'class.employee',
    data_type: 'STRING',
    nullable: false,
    ordinal: 1,
    version: 1,
  },
  {
    stable_element_id: 'property.employee.name',
    kind: 'PROPERTY',
    canonical_name: 'name',
    display_name: 'name',
    parent_stable_element_id: 'class.employee',
    data_type: 'STRING',
    nullable: true,
    ordinal: 2,
    version: 1,
  },
]

const source = {
  id: assetId,
  name: 'hr_employee',
  asset_type: 'TABLE',
  platform: 'postgres',
  database_name: 'hr',
  schema_name: 'public',
  classification: 'INTERNAL',
  source_version: 'source-v1',
  projection_source_version: 'projection-v3',
  field_paths: ['emp_id', 'emp_nm'],
  fields_truncated: false,
}

function json(value: unknown, status = 200, etag?: string): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: {
      'Content-Type': 'application/json',
      ...(etag ? { ETag: etag } : {}),
    },
  })
}

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input
  return input instanceof URL ? input.toString() : input.url
}

function binding(version: number) {
  return {
    id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3b4',
    target_stable_element_id: 'class.employee',
    source_reference_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3b5',
    source_asset_id: assetId,
    source_name: 'hr_employee',
    source_version: 'source-v1',
    projection_source_version: 'projection-v3',
    source_classification: 'INTERNAL',
    readiness: 'DRAFT',
    tbox_version: 2,
    version,
    rules: [
      {
        id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3b6',
        ordinal: 0,
        method: 'SUBJECT_ID',
        source_field_path: 'emp_id',
        target_stable_element_id: 'class.employee',
        transform_id: 'IDENTITY',
        transform_version: '1',
      },
      {
        id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3b7',
        ordinal: 1,
        method: 'PROPERTY',
        source_field_path: 'emp_nm',
        target_stable_element_id: 'property.employee.name',
        transform_id: 'IDENTITY',
        transform_version: '1',
      },
    ],
    created_at: '2026-07-28T04:00:00Z',
    updated_at: '2026-07-28T04:00:00Z',
  }
}

beforeEach(() => {
  vi.stubGlobal('crypto', {
    ...crypto,
    randomUUID: vi.fn(() => '019fa57b-52de-74c0-9f5e-06ae7b1bf399'),
  })
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('DataEnricherStep', () => {
  it('maps Dataset columns and marks the persisted T-Box node as Mapped', async () => {
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const path = requestUrl(input)
      if (path.endsWith(`/drafts/${draftId}/abox`) && !init?.method) {
        return Promise.resolve(json({
          draft: draft(3),
          tbox_elements: tboxElements,
          bindings: [],
        }, 200, '"3"'))
      }
      if (path.includes(`/drafts/${draftId}/abox/sources?`)) {
        return Promise.resolve(json({ items: [source], page: { limit: 25 } }))
      }
      if (path.endsWith(`/abox/sources/${assetId}`)) {
        return Promise.resolve(json({
          dataset: source,
          observed_at: '2026-07-28T04:00:00Z',
        }))
      }
      if (path.endsWith('/abox/bindings/class.employee') && init?.method === 'PATCH') {
        return Promise.resolve(json({
          draft: draft(4),
          binding: binding(1),
        }, 200, '"4"'))
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')
    render(<DataEnricherStep client={client} draftId={draftId} onDraftUpdate={vi.fn()} />)

    fireEvent.click(await screen.findByText('Employee'))
    fireEvent.click(await screen.findByRole('button', { name: /hr_employee/ }))
    await screen.findByText(/2개 컬럼을 확인했습니다/)

    fireEvent.change(screen.getByLabelText('Employee SUBJECT ID column'), {
      target: { value: 'emp_id' },
    })
    fireEvent.change(screen.getByLabelText('name source column'), {
      target: { value: 'emp_nm' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Binding Draft 저장' }))

    await screen.findByText(/Binding Draft 저장 완료/)
    expect(await screen.findByLabelText(
      'Employee, 2 properties · Mapped · DRAFT',
    )).toBeInTheDocument()
    const patchCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH')
    expect(new Headers(patchCall?.[1]?.headers).get('If-Match')).toBe('"3"')
    const patchBody = patchCall?.[1]?.body
    expect(typeof patchBody).toBe('string')
    expect(JSON.parse(patchBody as string)).toEqual({
      source_asset_id: assetId,
      source_version: 'source-v1',
      projection_source_version: 'projection-v3',
      rules: [
        {
          method: 'SUBJECT_ID',
          source_field_path: 'emp_id',
          target_stable_element_id: 'class.employee',
        },
        {
          method: 'PROPERTY',
          source_field_path: 'emp_nm',
          target_stable_element_id: 'property.employee.name',
        },
      ],
    })
  })

  it('preserves local mapping on 412 and rebases only after overwrite confirmation', async () => {
    let aboxReads = 0
    let patches = 0
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const path = requestUrl(input)
      if (path.endsWith(`/drafts/${draftId}/abox`) && !init?.method) {
        aboxReads += 1
        return Promise.resolve(json({
          draft: draft(aboxReads === 1 ? 3 : 4),
          tbox_elements: tboxElements,
          bindings: [],
        }, 200, aboxReads === 1 ? '"3"' : '"4"'))
      }
      if (path.includes(`/drafts/${draftId}/abox/sources?`)) {
        return Promise.resolve(json({ items: [source], page: { limit: 25 } }))
      }
      if (path.endsWith(`/abox/sources/${assetId}`)) {
        return Promise.resolve(json({
          dataset: source,
          observed_at: '2026-07-28T04:00:00Z',
        }))
      }
      if (path.endsWith('/abox/bindings/class.employee') && init?.method === 'PATCH') {
        patches += 1
        if (patches === 1) {
          return Promise.resolve(json({
            type: 'urn:datariver:problem:precondition_failed',
            title: 'Precondition Failed',
            status: 412,
            detail: 'The Draft changed.',
            code: 'precondition_failed',
            request_id: 'request',
          }, 412))
        }
        return Promise.resolve(json({
          draft: draft(5),
          binding: binding(1),
        }, 200, '"5"'))
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')
    render(<DataEnricherStep client={client} draftId={draftId} onDraftUpdate={vi.fn()} />)

    fireEvent.click(await screen.findByText('Employee'))
    fireEvent.click(await screen.findByRole('button', { name: /hr_employee/ }))
    await screen.findByText(/2개 컬럼을 확인했습니다/)
    fireEvent.change(screen.getByLabelText('Employee SUBJECT ID column'), {
      target: { value: 'emp_id' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Binding Draft 저장' }))

    const dialog = await screen.findByRole('dialog', { name: 'A-Box 동시 편집 충돌' })
    expect(screen.getByLabelText('Employee SUBJECT ID column')).toHaveValue('emp_id')
    fireEvent.click(within(dialog).getByRole('button', { name: '내 Mapping으로 덮어쓰기' }))

    await waitFor(() => expect(
      screen.queryByRole('dialog', { name: 'A-Box 동시 편집 충돌' }),
    ).not.toBeInTheDocument())
    const patchCalls = fetchMock.mock.calls.filter(([, init]) => init?.method === 'PATCH')
    expect(new Headers(patchCalls[1]?.[1]?.headers).get('If-Match')).toBe('"4"')
  })

  it('shows a dry-run graph overlay, click-to-inspect properties and pre-flight evidence', async () => {
    const firstNodeId = `preview:${'a'.repeat(64)}`
    const secondNodeId = `preview:${'b'.repeat(64)}`
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const path = requestUrl(input)
      if (path.endsWith(`/drafts/${draftId}/abox`) && !init?.method) {
        return Promise.resolve(json({
          draft: draft(3),
          tbox_elements: tboxElements,
          bindings: [binding(1)],
        }, 200, '"3"'))
      }
      if (path.includes(`/drafts/${draftId}/abox/sources?`)) {
        return Promise.resolve(json({ items: [source], page: { limit: 25 } }))
      }
      if (path.endsWith(`/abox/sources/${assetId}`)) {
        return Promise.resolve(json({
          dataset: source,
          observed_at: '2026-07-28T04:00:00Z',
        }))
      }
      if (path.endsWith('/abox/previews') && init?.method === 'POST') {
        return Promise.resolve(json({
          status: 'READY',
          draft_version: 3,
          binding_version: 1,
          target_stable_element_id: 'class.employee',
          dry_run: true,
          sample_size: 2,
          graph: {
            nodes: [
              {
                id: firstNodeId,
                stable_element_id: 'class.employee',
                type: 'Employee',
                identity: 'E-001',
                properties: { name: 'Kim' },
              },
              {
                id: secondNodeId,
                stable_element_id: 'class.employee',
                type: 'Employee',
                identity: 'E-002',
                properties: { name: 'Park' },
              },
            ],
            edges: [],
          },
          evidence: [],
        }, 200, '"3"'))
      }
      if (path.endsWith('/abox/preflight') && init?.method === 'POST') {
        return Promise.resolve(json({
          status: 'UNAVAILABLE',
          valid: false,
          draft_version: 3,
          checked_at: '2026-07-28T08:00:00Z',
          evidence: [{
            severity: 'ERROR',
            code: 'SOURCE_ROW_READER_UNAVAILABLE',
            location: 'abox',
            message: 'No approved physical Dataset row reader is configured.',
          }],
        }, 200, '"3"'))
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')
    render(<DataEnricherStep client={client} draftId={draftId} onDraftUpdate={vi.fn()} />)

    fireEvent.click(await screen.findByLabelText('Employee, 2 properties · Mapped · DRAFT'))
    await screen.findByText(/source version source-v1/)
    fireEvent.click(screen.getByRole('button', { name: 'Preview · Dry Run' }))

    const previewDialog = await screen.findByRole('dialog', {
      name: 'Knowledge Graph Preview · Dry Run',
    })
    expect(within(previewDialog).getByText('Kim')).toBeInTheDocument()
    fireEvent.click(await within(previewDialog).findByLabelText(
      'Employee, SUBJECT_ID E-002 · 1 properties',
    ))
    expect(within(previewDialog).getByText('Park')).toBeInTheDocument()
    expect(within(previewDialog).getByText(/Neo4j에는 쓰지 않습니다/)).toBeInTheDocument()
    fireEvent.click(within(previewDialog).getByRole('button', { name: '닫기' }))

    fireEvent.click(screen.getByRole('button', { name: 'Pre-flight 검증' }))
    const preflightResult = await screen.findByLabelText('Ingestion Pre-flight 결과')
    expect(within(preflightResult).getByText(/Pre-flight UNAVAILABLE/)).toBeInTheDocument()
    expect(within(preflightResult).getByText(/SOURCE_ROW_READER_UNAVAILABLE/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Run Ingestion' })).toBeDisabled()

    const previewCall = fetchMock.mock.calls.find(([input]) => (
      requestUrl(input).endsWith('/abox/previews')
    ))
    expect(new Headers(previewCall?.[1]?.headers).get('If-Match')).toBe('"3"')
    expect(JSON.parse(previewCall?.[1]?.body as string)).toEqual({
      target_stable_element_id: 'class.employee',
      sample_limit: 5,
    })
  })
})
