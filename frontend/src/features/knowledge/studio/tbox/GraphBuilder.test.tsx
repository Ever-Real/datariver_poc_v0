import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiClient } from '../../../../api/client'
import { GraphBuilder } from './GraphBuilder'

const draftId = '019fa57b-52de-74c0-9f5e-06ae7b1bf3b0'
const blockId = '019fa57b-52de-74c0-9f5e-06ae7b1bf3b1'
const secondBlockId = '019fa57b-52de-74c0-9f5e-06ae7b1bf3b4'

function draft(version: number) {
  return {
    id: draftId,
    author_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3b2',
    kind: 'CREATE',
    state: 'DRAFT',
    current_step: 'TBOX',
    name: 'Enterprise ontology',
    endpoint_alias: 'enterprise_ontology',
    domain_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3b3',
    domain_source_version: 'domain-v1',
    classification: 'INTERNAL',
    last_autosaved_at: '2026-07-29T01:00:00Z',
    version,
    created_at: '2026-07-29T01:00:00Z',
    updated_at: '2026-07-29T01:00:00Z',
  }
}

function tbox(elements: unknown[] = []) {
  return {
    draft: draft(2),
    blocks: [{
      id: blockId,
      kind: 'DIRECT',
      title: '직접 정의',
      weight: 50,
      ordinal: 0,
      collapsed: false,
      version: 1,
      source_reference: null,
      elements,
      created_at: '2026-07-29T01:00:00Z',
      updated_at: '2026-07-29T01:00:00Z',
    }],
  }
}

function json(value: unknown, etag = '"2"'): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { 'Content-Type': 'application/json', ETag: etag },
  })
}

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input
  return input instanceof URL ? input.toString() : input.url
}

beforeEach(() => {
  vi.stubGlobal('crypto', {
    ...crypto,
    randomUUID: vi.fn()
      .mockReturnValueOnce('019fa57b-52de-74c0-9f5e-06ae7b1bf3c0')
      .mockReturnValueOnce('019fa57b-52de-74c0-9f5e-06ae7b1bf3c1')
      .mockReturnValueOnce('019fa57b-52de-74c0-9f5e-06ae7b1bf3c2')
      .mockReturnValue('019fa57b-52de-74c0-9f5e-06ae7b1bf3cf'),
  })
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('GraphBuilder', () => {
  it('synchronizes canvas changes to safe text and retains the last valid canvas on syntax error', async () => {
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const path = requestUrl(input)
      if (path.endsWith(`/drafts/${draftId}/tbox`)) {
        return Promise.resolve(json(tbox()))
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')

    render(
      <GraphBuilder
        client={client}
        draftId={draftId}
        etag='"2"'
        busy={false}
        onDraftUpdate={vi.fn()}
        onContinue={vi.fn()}
      />,
    )

    await screen.findByText(/Typed T-Box Draft를 불러왔습니다/)
    fireEvent.change(screen.getByLabelText('최상위 Class 이름'), {
      target: { value: 'Employee' },
    })
    fireEvent.click(screen.getByRole('button', { name: '최상위 Class 추가' }))

    const canvas = screen.getByLabelText('T-Box 그래프 캔버스')
    expect(await within(canvas).findByText('Employee')).toBeInTheDocument()
    expect(screen.getByLabelText('T-Box Cypher 편집기')).toHaveValue(
      'CREATE (n0:Employee)',
    )

    fireEvent.change(screen.getByLabelText('T-Box Cypher 편집기'), {
      target: { value: 'CREATE (n0:Employee)\nMATCH (n0)' },
    })

    expect(await screen.findByRole('alert')).toHaveTextContent('Line 2, Column 1')
    expect(within(canvas).getByText('Employee')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('T-Box Cypher 편집기'), {
      target: {
        value: 'CREATE (n0:Employee)\nCREATE (n1:Department)',
      },
    })

    await waitFor(() => {
      expect(within(canvas).getByText('Employee')).toBeInTheDocument()
      expect(within(canvas).getByText('Department')).toBeInTheDocument()
    })
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows prior layers in a new block and keeps inherited elements read-only', async () => {
    const inheritedClass = {
      stable_element_id: 'class:employee',
      kind: 'CLASS',
      canonical_name: 'Employee',
      display_name: 'Employee',
      ordinal: 0,
      version: 1,
      block_id: blockId,
      aliases: [],
      vector_index_enabled: false,
      layout_x: 80,
      layout_y: 100,
    }
    const layered = tbox([inheritedClass])
    layered.blocks.push({
      id: secondBlockId,
      kind: 'CATALOG_METADATA',
      title: 'DB 활용',
      weight: 60,
      ordinal: 1,
      collapsed: false,
      version: 1,
      source_reference: null,
      elements: [],
      created_at: '2026-07-29T01:01:00Z',
      updated_at: '2026-07-29T01:01:00Z',
    })
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const path = requestUrl(input)
      if (path.endsWith(`/drafts/${draftId}/tbox`)) {
        return Promise.resolve(json(layered))
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')

    render(
      <GraphBuilder
        client={client}
        draftId={draftId}
        etag='"2"'
        busy={false}
        onDraftUpdate={vi.fn()}
        onContinue={vi.fn()}
      />,
    )

    await screen.findByText(/Typed T-Box Draft를 불러왔습니다/)
    fireEvent.click(screen.getByRole('button', {
      name: 'DB 활용 CATALOG_METADATA 블록 열기',
    }))

    const canvas = screen.getByLabelText('T-Box 그래프 캔버스')
    expect(within(canvas).getByText('Employee')).toBeInTheDocument()
    expect(within(canvas).getByText('1. 직접 정의 · 읽기 전용')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('T-Box Cypher 편집기'), {
      target: { value: '' },
    })

    expect(await screen.findByRole('alert')).toHaveTextContent('이전 블록의 요소')
    expect(within(canvas).getByText('Employee')).toBeInTheDocument()
  })

  it('synchronizes hierarchy drag and drop and edits properties in the node floating panel', async () => {
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const path = requestUrl(input)
      if (path.endsWith(`/drafts/${draftId}/tbox`)) {
        return Promise.resolve(json(tbox()))
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')

    render(
      <GraphBuilder
        client={client}
        draftId={draftId}
        etag='"2"'
        busy={false}
        onDraftUpdate={vi.fn()}
        onContinue={vi.fn()}
      />,
    )

    await screen.findByText(/Typed T-Box Draft를 불러왔습니다/)
    const classInput = screen.getByLabelText('최상위 Class 이름')
    fireEvent.change(classInput, { target: { value: 'Organization' } })
    fireEvent.click(screen.getByRole('button', { name: '최상위 Class 추가' }))
    fireEvent.change(classInput, { target: { value: 'Department' } })
    fireEvent.click(screen.getByRole('button', { name: '최상위 Class 추가' }))

    const department = screen.getByRole('button', { name: '· Department' }).parentElement
    const organization = screen.getByRole('button', { name: '· Organization' }).parentElement
    expect(department).not.toBeNull()
    expect(organization).not.toBeNull()
    fireEvent.dragStart(department!)
    fireEvent.dragOver(organization!)
    fireEvent.drop(organization!)

    await waitFor(() => {
      expect(screen.getByLabelText('T-Box Cypher 편집기')).toHaveValue(
        'CREATE (n0:Organization)\n'
        + 'CREATE (n1:Department)\n'
        + 'CREATE (n1)-[:SUBCLASS_OF]->(n0)',
      )
    })

    const canvas = screen.getByLabelText('T-Box 그래프 캔버스')
    fireEvent.click(within(canvas).getByText('Department'))
    const floatingPanel = await screen.findByRole('dialog', {
      name: 'Department Class 빠른 편집',
    })
    const propertyInput = within(floatingPanel).getByLabelText('Department 새 Property 이름')
    propertyInput.focus()
    fireEvent.change(propertyInput, { target: { value: 'description' } })
    expect(propertyInput).toHaveFocus()
    fireEvent.click(within(floatingPanel).getByRole('button', {
      name: 'Department Property 추가',
    }))

    expect(await within(canvas).findByText('· description')).toBeInTheDocument()
    expect(screen.getByRole('dialog', {
      name: 'Department Class 빠른 편집',
    })).toBeInTheDocument()
  })

  it('disables historical block deletion and deletes only the newest block with ETag fencing', async () => {
    const layered = tbox([])
    layered.blocks.push({
      id: secondBlockId,
      kind: 'CATALOG_METADATA',
      title: 'DB 활용',
      weight: 60,
      ordinal: 1,
      collapsed: false,
      version: 1,
      source_reference: null,
      elements: [],
      created_at: '2026-07-29T01:01:00Z',
      updated_at: '2026-07-29T01:01:00Z',
    })
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const path = requestUrl(input)
      if (path.endsWith(`/drafts/${draftId}/tbox`) && !init?.method) {
        return Promise.resolve(json(layered))
      }
      if (
        path.endsWith(`/drafts/${draftId}/tbox/blocks/${secondBlockId}`)
        && init?.method === 'DELETE'
      ) {
        return Promise.resolve(json(tbox([]), '"3"'))
      }
      return Promise.reject(new Error(`Unexpected request: ${init?.method ?? 'GET'} ${path}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')

    render(
      <GraphBuilder
        client={client}
        draftId={draftId}
        etag='"2"'
        busy={false}
        onDraftUpdate={vi.fn()}
        onContinue={vi.fn()}
      />,
    )

    await screen.findByText(/Typed T-Box Draft를 불러왔습니다/)
    expect(screen.getByRole('button', {
      name: '직접 정의 블록 삭제',
    })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', {
      name: 'DB 활용 블록 삭제',
    }))
    fireEvent.click(screen.getByRole('button', {
      name: '최신 블록 삭제',
    }))

    expect(await screen.findByText(/최신 블록 'DB 활용'을 삭제했습니다/)).toBeInTheDocument()
    const deleteRequest = fetchMock.mock.calls.find(([, init]) => init?.method === 'DELETE')
    expect(new Headers(deleteRequest?.[1]?.headers).get('If-Match')).toBe('"2"')
  })
})
