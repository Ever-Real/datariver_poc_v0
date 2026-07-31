import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiClient } from '../../../../api/client'
import { useKnowledgeStudioSessionStore } from '../knowledgeStudioSessionStore'
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
  useKnowledgeStudioSessionStore.setState({ sessions: {} })
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
  it('ends a stalled T-Box read with a retry action', async () => {
    const fetchMock = vi.fn<typeof fetch>(() => new Promise(() => undefined))
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')

    render(
      <GraphBuilder
        client={client}
        draftId={draftId}
        etag='"2"'
        busy={false}
        loadTimeoutMs={20}
        onDraftUpdate={vi.fn()}
        onContinue={vi.fn()}
      />,
    )

    expect(await screen.findByRole('heading', {
      name: 'Graph Builder를 열지 못했습니다.',
    })).toBeInTheDocument()
    expect(screen.getByText(/T-Box 정본 조회가 제한 시간 안에 완료되지 않았습니다/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'T-Box 다시 불러오기' })).toBeEnabled()
  })

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
    fireEvent.click(screen.getByLabelText('Employee Class 편집기 열기'))
    const quickEditor = screen.getByLabelText('Employee Class 빠른 편집')
    expect(quickEditor).toBeInTheDocument()
    expect(quickEditor).toHaveStyle({ transform: 'scale(1)' })
    expect(quickEditor.parentElement?.style.transform).not.toContain('scale')
    fireEvent.click(screen.getByLabelText('Employee Class 편집기 닫기'))
    expect(screen.queryByLabelText('Employee Class 빠른 편집')).not.toBeInTheDocument()

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

    fireEvent.change(screen.getByLabelText('T-Box Cypher 편집기'), {
      target: {
        value: 'CREATE (n0:Employee)\n'
          + 'CREATE (n1:Department)\n'
          + 'CREATE (n0)-[:REPORTS_TO]->(n1)',
      },
    })

    expect(await screen.findByRole('button', {
      name: 'Employee → Department',
    })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'REPORTS_TO' })).toBeInTheDocument()
    expect(canvas.querySelectorAll('.react-flow__handle')).toHaveLength(22)
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

  it('allows active-owned relationships in both directions across an earlier layer and projects SUBCLASS_OF once', async () => {
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
      kind: 'DIRECT',
      title: '확장 레이어',
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
      name: '확장 레이어 DIRECT 블록 열기',
    }))
    const classInput = screen.getByLabelText('최상위 Class 이름')
    fireEvent.change(classInput, { target: { value: 'Department' } })
    fireEvent.click(screen.getByRole('button', { name: '최상위 Class 추가' }))

    const canvas = screen.getByLabelText('T-Box 그래프 캔버스')
    const employeeNode = within(canvas).getByText('Employee').closest('.react-flow__node')
    const departmentNode = within(canvas).getByText('Department').closest('.react-flow__node')
    expect(employeeNode?.querySelectorAll('.react-flow__handle.source.connectable').length)
      .toBeGreaterThan(0)
    expect(departmentNode?.querySelectorAll('.react-flow__handle.source.connectable').length)
      .toBeGreaterThan(0)

    fireEvent.change(screen.getByLabelText('T-Box Cypher 편집기'), {
      target: {
        value: 'CREATE (n0:Employee)\n'
          + 'CREATE (n1:Department)\n'
          + 'CREATE (n0)-[:LEGACY_TO_CURRENT]->(n1)\n'
          + 'CREATE (n1)-[:REPORTS_TO]->(n0)',
      },
    })

    expect(await screen.findByRole('button', {
      name: 'LEGACY_TO_CURRENT Relationship 편집',
    })).toBeEnabled()
    expect(screen.getByRole('button', {
      name: 'REPORTS_TO Relationship 편집',
    })).toBeEnabled()

    fireEvent.click(screen.getByRole('button', {
      name: 'REPORTS_TO Relationship 편집',
    }))
    const relationshipName = screen.getByLabelText('REPORTS_TO Relationship 이름')
    fireEvent.change(relationshipName, { target: { value: 'SUBCLASS_OF' } })
    fireEvent.keyDown(relationshipName, { key: 'Enter' })

    expect(await screen.findByRole('button', {
      name: 'SUBCLASS_OF Relationship 편집',
    })).toBeEnabled()
    expect(screen.getByLabelText<HTMLTextAreaElement>('T-Box Cypher 편집기').value)
      .toContain('CREATE (n1)-[:SUBCLASS_OF]->(n0)')
    expect(screen.getAllByText('SUBCLASS_OF')).toHaveLength(2)

    fireEvent.click(screen.getByRole('button', {
      name: 'LEGACY_TO_CURRENT Relationship 삭제',
    }))
    await waitFor(() => {
      expect(screen.queryByRole('button', {
        name: 'LEGACY_TO_CURRENT Relationship 편집',
      })).not.toBeInTheDocument()
    })
  })

  it('retains unsaved per-block graph and editor state while switching layer headers', async () => {
    const layered = tbox([])
    layered.blocks.push({
      id: secondBlockId,
      kind: 'DIRECT',
      title: '확장 레이어',
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
    fireEvent.change(screen.getByLabelText('최상위 Class 이름'), {
      target: { value: '임시_클래스' },
    })
    fireEvent.click(screen.getByRole('button', { name: '최상위 Class 추가' }))
    expect(screen.getByLabelText('T-Box Cypher 편집기')).toHaveValue(
      'CREATE (n0:임시_클래스)',
    )

    fireEvent.click(screen.getByRole('button', {
      name: '확장 레이어 DIRECT 블록 열기',
    }))
    expect(await within(screen.getByLabelText('T-Box 그래프 캔버스'))
      .findByText('임시_클래스')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', {
      name: '직접 정의 DIRECT 블록 열기',
    }))

    expect(screen.getByLabelText('T-Box Cypher 편집기')).toHaveValue(
      'CREATE (n0:임시_클래스)',
    )
    expect(within(screen.getByLabelText('T-Box 그래프 캔버스'))
      .getByText('임시_클래스')).toBeInTheDocument()
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
    fireEvent.click(screen.getByRole('button', {
      name: 'Department 계층 관계 SUBCLASS_OF 편집',
    }))
    const hierarchyInput = screen.getByLabelText('Department 계층 관계 이름')
    fireEvent.change(hierarchyInput, { target: { value: 'PART_OF' } })
    fireEvent.keyDown(hierarchyInput, { key: 'Enter' })
    await waitFor(() => {
      expect(screen.getByLabelText('T-Box Cypher 편집기')).toHaveValue(
        'CREATE (n0:Organization)\n'
        + 'CREATE (n1:Department)\n'
        + 'CREATE (n1)-[:PART_OF]->(n0)',
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

  it('keeps Korean identifiers intact and supports Property update and delete without opening editors by default', async () => {
    let savedBody: Record<string, unknown> | undefined
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const path = requestUrl(input)
      if (path.endsWith(`/drafts/${draftId}/tbox`) && !init?.method) {
        return Promise.resolve(json(tbox()))
      }
      if (path.endsWith(`/drafts/${draftId}/tbox/blocks/${blockId}/operations`)) {
        if (typeof init?.body !== 'string') throw new Error('Expected JSON request body')
        savedBody = JSON.parse(init.body) as Record<string, unknown>
        return Promise.resolve(json(tbox(), '"3"'))
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
    fireEvent.change(screen.getByLabelText('최상위 Class 이름'), {
      target: { value: '데이터 자산' },
    })
    fireEvent.click(screen.getByRole('button', { name: '최상위 Class 추가' }))
    expect(screen.queryByRole('dialog', { name: '데이터_자산 Class 빠른 편집' }))
      .not.toBeInTheDocument()
    expect(screen.getByLabelText('T-Box Cypher 편집기')).toHaveValue(
      'CREATE (n0:데이터_자산)',
    )

    const canvas = screen.getByLabelText('T-Box 그래프 캔버스')
    fireEvent.click(within(canvas).getByLabelText('데이터_자산 Class 편집기 열기'))
    const panel = await screen.findByRole('dialog', {
      name: '데이터_자산 Class 빠른 편집',
    })
    fireEvent.change(within(panel).getByLabelText('데이터_자산 새 Property 이름'), {
      target: { value: '한글 속성' },
    })
    fireEvent.click(within(panel).getByRole('button', {
      name: '데이터_자산 Property 추가',
    }))

    const propertyName = await within(panel).findByLabelText(
      '데이터_자산 한글_속성 Property 이름',
    )
    fireEvent.change(propertyName, { target: { value: '상세 설명' } })
    fireEvent.keyDown(propertyName, { key: 'Enter' })
    expect(await within(panel).findByLabelText(
      '데이터_자산 상세_설명 Property 이름',
    )).toBeInTheDocument()
    fireEvent.click(within(panel).getByRole('button', {
      name: '데이터_자산 상세_설명 Property 삭제',
    }))
    expect(within(panel).queryByLabelText(
      '데이터_자산 상세_설명 Property 이름',
    )).not.toBeInTheDocument()

    fireEvent.change(within(panel).getByLabelText('데이터_자산 새 Property 이름'), {
      target: { value: '최종 속성' },
    })
    fireEvent.click(within(panel).getByRole('button', {
      name: '데이터_자산 Property 추가',
    }))
    fireEvent.click(screen.getByRole('button', { name: 'T-Box 저장' }))
    await waitFor(() => expect(savedBody).toBeDefined())
    expect(JSON.stringify(savedBody)).toContain('"canonical_name":"데이터_자산"')
    expect(JSON.stringify(savedBody)).toContain('"canonical_name":"최종_속성"')
    expect(JSON.stringify(savedBody)).not.toContain('Class__')
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

  it('commits a compact block title with Enter and exposes explicit confirm and cancel controls', async () => {
    const updated = tbox([])
    updated.blocks[0]!.title = '핵심 스키마'
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const path = requestUrl(input)
      if (path.endsWith(`/drafts/${draftId}/tbox`) && !init?.method) {
        return Promise.resolve(json(tbox()))
      }
      if (
        path.endsWith(`/drafts/${draftId}/tbox/blocks/${blockId}`)
        && init?.method === 'PATCH'
      ) {
        return Promise.resolve(json(updated, '"3"'))
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
    const title = screen.getByLabelText('1번 블록 이름')
    fireEvent.change(title, { target: { value: '핵심 스키마' } })
    const editingCheck = screen.getByLabelText('직접 정의 블록 이름 입력 중')
    expect(editingCheck.tagName).toBe('SPAN')
    expect(editingCheck).toHaveClass('text-slate-300')
    expect(screen.getByRole('button', { name: '직접 정의 블록 이름 취소' })).toBeEnabled()
    fireEvent.keyDown(title, { key: 'Enter' })

    await waitFor(() => expect(title).toHaveValue('핵심 스키마'))
    expect(title).toHaveClass('border-white')
    expect(title).toHaveClass('hover:border-slate-200')
    expect(screen.getByLabelText('핵심 스키마 블록 이름 저장됨')).toHaveClass('text-emerald-600')
    const patch = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH')
    expect(new Headers(patch?.[1]?.headers).get('If-Match')).toBe('"2"')
  })

  it('uses the governed global catalog search surface in a workspace database modal', async () => {
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const path = requestUrl(input)
      if (path.endsWith(`/drafts/${draftId}/tbox`)) {
        return Promise.resolve(json(tbox()))
      }
      if (path.includes(`/drafts/${draftId}/tbox/catalog-sources?`)) {
        return Promise.resolve(json({
          items: [{
            id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3d0',
            name: 'orders',
            asset_type: 'TABLE',
            platform: 'postgres',
            database_name: 'sales',
            schema_name: 'public',
            classification: 'INTERNAL',
            source_version: 'projection-v4',
            projection_source_version: 'projection-v4',
            field_paths: [],
            fields_truncated: true,
            domain: 'Finance',
            tags: ['gold'],
            glossary_terms: ['Order'],
          }],
          page: { next_cursor: null, limit: 50 },
        }))
      }
      if (path.endsWith(
        `/drafts/${draftId}/tbox/catalog-sources/019fa57b-52de-74c0-9f5e-06ae7b1bf3d0`,
      )) {
        return Promise.resolve(json({
          dataset: {
            id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3d0',
            name: 'orders',
            asset_type: 'TABLE',
            platform: 'postgres',
            database_name: 'sales',
            schema_name: 'public',
            classification: 'INTERNAL',
            source_version: 'datahub-v8',
            projection_source_version: 'projection-v4',
            field_paths: ['order_id', 'amount'],
            fields_truncated: false,
            domain: 'Finance',
            tags: ['gold'],
            glossary_terms: ['Order'],
          },
          observed_at: '2026-07-31T01:00:00Z',
          stale_at: null,
        }))
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
    fireEvent.click(screen.getByRole('button', { name: 'DB 테이블 검색' }))
    const dialog = await screen.findByRole('dialog', {
      name: 'DB 카탈로그에서 T-Box 제안',
    })
    expect(dialog).toHaveClass('app-dialog-workspace')
    const query = screen.getByLabelText('T-Box 카탈로그 검색어')
    fireEvent.change(query, { target: { value: 'orders' } })
    fireEvent.submit(query.closest('form')!)

    await waitFor(() => {
      const requested = fetchMock.mock.calls.map(([input]) => requestUrl(input))
      expect(requested).toContainEqual(expect.stringContaining(
        `/tbox/catalog-sources?q=orders&limit=50`,
      ))
    })
    const results = await screen.findByRole('table', {
      name: 'T-Box 카탈로그 검색 결과',
    })
    fireEvent.click(within(results).getByText('orders'))
    const fields = await screen.findByRole('table', { name: 'orders 컬럼 선택' })
    expect(within(fields).getByRole('checkbox', { name: 'order_id 컬럼 선택' })).toBeChecked()
    expect(within(fields).getByRole('checkbox', { name: 'amount 컬럼 선택' })).toBeChecked()
  })

  it('selects an exact published Asset release and opens it in the shared Proposal preview', async () => {
    const release = {
      graph_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3e0',
      graph_name: 'Enterprise glossary',
      graph_slug: 'enterprise-glossary',
      classification: 'INTERNAL',
      domain_name: 'Data Governance',
      studio_release_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3e1',
      release_no: 7,
      state: 'ACTIVE',
      contract_hash: 'a'.repeat(64),
      tbox_hash: 'b'.repeat(64),
      published_at: '2026-07-31T01:00:00Z',
      class_count: 1,
      property_count: 0,
      relationship_count: 0,
    }
    const proposal = {
      id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3e2',
      draft_id: draftId,
      target_block_id: blockId,
      state: 'READY',
      mode: 'MERGE_INTO_CURRENT',
      merge_strategy: 'KEEP_ORIGINAL',
      base_draft_version: 2,
      prompt: 'server-owned exact Asset release import',
      elements: [{
        stable_element_id: 'class.BusinessTerm',
        kind: 'CLASS',
        canonical_name: 'BusinessTerm',
        display_name: 'Business Term',
        ordinal: 0,
        version: 1,
        aliases: [],
        vector_index_enabled: false,
        locked_by_later_block: false,
      }],
      conflicts: [],
      source_reference: {
        contract_version: 'KNOWLEDGE_STUDIO_ASSET_RELEASE_SOURCE_V1',
        studio_release_id: release.studio_release_id,
        tbox_hash: release.tbox_hash,
      },
      version: 1,
      created_at: '2026-07-31T01:00:00Z',
      updated_at: '2026-07-31T01:00:00Z',
    }
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const path = requestUrl(input)
      if (path.endsWith(`/drafts/${draftId}/tbox`)) {
        return Promise.resolve(json(tbox()))
      }
      if (path.includes(`/drafts/${draftId}/tbox/asset-releases?`)) {
        return Promise.resolve(json({
          items: [release],
          page: { next_cursor: null, limit: 50 },
        }))
      }
      if (
        path.endsWith(`/drafts/${draftId}/tbox/asset-release-proposals`)
        && init?.method === 'POST'
      ) {
        return Promise.resolve(json(proposal))
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
    fireEvent.click(screen.getByRole('button', { name: '다른 Asset 붙이기' }))
    const dialog = await screen.findByRole('dialog', {
      name: '다른 지식 Asset의 T-Box 붙이기',
    })
    expect(dialog).toHaveClass('app-dialog-workspace')

    const query = within(dialog).getByLabelText('T-Box 지식 Asset 검색어')
    fireEvent.change(query, { target: { value: 'glossary' } })
    fireEvent.submit(query.closest('form')!)

    const results = await within(dialog).findByRole('table', {
      name: '게시된 지식 Asset 버전 검색 결과',
    })
    fireEvent.click(within(results).getByText('Enterprise glossary'))
    expect(within(dialog).getByLabelText('선택한 지식 Asset 버전')).toHaveTextContent(
      'Enterprise glossary · v7',
    )
    fireEvent.click(within(dialog).getByRole('button', { name: '현재 블록 Proposal' }))

    const preview = await screen.findByLabelText('T-Box Proposal 미리보기')
    expect(within(preview).getByLabelText('Business Term Proposal 이름')).toHaveValue(
      'Business Term',
    )
    const proposalCall = fetchMock.mock.calls.find(([input]) => (
      requestUrl(input).endsWith(`/drafts/${draftId}/tbox/asset-release-proposals`)
    ))
    expect(new Headers(proposalCall?.[1]?.headers).get('If-Match')).toBe('"2"')
    const proposalBody = proposalCall?.[1]?.body
    expect(JSON.parse(typeof proposalBody === 'string' ? proposalBody : '{}')).toEqual({
      studio_release_id: release.studio_release_id,
      tbox_hash: release.tbox_hash,
      target_block_id: blockId,
      mode: 'MERGE_INTO_CURRENT',
    })
  })
})
