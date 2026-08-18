import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiClient } from '../../../../api/client'
import { useKnowledgeStudioSessionStore } from '../knowledgeStudioSessionStore'
import { GraphBuilder, relationshipHandles } from './GraphBuilder'

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
      source_reference: null as Record<string, unknown> | null,
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
  it('chooses the nearest fixed relationship sides as nodes move', () => {
    expect(relationshipHandles({ x: 0, y: 0 }, { x: 300, y: 20 })).toEqual({
      sourceHandle: 'source-right',
      targetHandle: 'target-left',
    })
    expect(relationshipHandles({ x: 300, y: 20 }, { x: 0, y: 0 })).toEqual({
      sourceHandle: 'source-left',
      targetHandle: 'target-right',
    })
    expect(relationshipHandles({ x: 0, y: 0 }, { x: 20, y: 300 })).toEqual({
      sourceHandle: 'source-bottom',
      targetHandle: 'target-top',
    })
    expect(relationshipHandles({ x: 20, y: 300 }, { x: 0, y: 0 })).toEqual({
      sourceHandle: 'source-top',
      targetHandle: 'target-bottom',
    })
  })

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
    expect(screen.getByRole('button', { name: 'T-Box 저장 후 A-Box로 이동' }))
      .toBeDisabled()

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
    expect(within(canvas).getByLabelText('Employee 상단 Relationship 연결점'))
      .toBeInTheDocument()
    expect(within(canvas).getByLabelText('Employee 우측 Relationship 연결점'))
      .toBeInTheDocument()
    expect(within(canvas).getByLabelText('Employee 하단 Relationship 연결점'))
      .toBeInTheDocument()
    expect(within(canvas).getByLabelText('Employee 좌측 Relationship 연결점'))
      .toBeInTheDocument()
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
      name: 'DB 활용 CATALOG_METADATA 블록 선택',
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
      name: '확장 레이어 DIRECT 블록 선택',
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
    const canvasElement = screen.getByLabelText('T-Box 그래프 캔버스')
    const editorElement = screen.getByLabelText('T-Box Cypher 편집기')

    fireEvent.click(screen.getByRole('button', {
      name: '확장 레이어 DIRECT 블록 선택',
    }))
    expect(screen.getByLabelText('T-Box 그래프 캔버스')).toBe(canvasElement)
    expect(screen.getByLabelText('T-Box Cypher 편집기')).toBe(editorElement)
    expect(await within(screen.getByLabelText('T-Box 그래프 캔버스'))
      .findByText('임시_클래스')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', {
      name: '직접 정의 DIRECT 블록 선택',
    }))

    expect(screen.getByLabelText('T-Box 그래프 캔버스')).toBe(canvasElement)
    expect(screen.getByLabelText('T-Box Cypher 편집기')).toBe(editorElement)
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

  it('updates ElementInspector properties and serializes correctly on save', async () => {
    let savedBody: Record<string, unknown> | undefined
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const path = requestUrl(input)
      if (path.endsWith(`/drafts/${draftId}/tbox`) && !init?.method) {
        return Promise.resolve(json(tbox([
          {
            stable_element_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3c0',
            kind: 'CLASS',
            canonical_name: 'Person',
            display_name: 'Person',
            aliases: [],
            vector_index_enabled: false,
            locked_by_later_block: false,
            block_id: blockId,
            ordinal: 0,
            version: 1,
            layout_x: 0,
            layout_y: 0,
          },
          {
            stable_element_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3c1',
            kind: 'PROPERTY',
            canonical_name: 'age',
            display_name: 'age',
            parent_stable_element_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3c0',
            data_type: 'INTEGER',
            value_cardinality: 'SINGLE',
            nullable: true,
            aliases: [],
            vector_index_enabled: false,
            locked_by_later_block: false,
            block_id: blockId,
            ordinal: 1,
            version: 1,
          }
        ])))
      }
      if (path.endsWith(`/drafts/${draftId}/tbox/blocks/${blockId}/operations`)) {
        savedBody = JSON.parse(init!.body as string) as Record<string, unknown>
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

    fireEvent.click(screen.getByText('Person'))
    const aliasesInput = await screen.findByLabelText('동의어 (Aliases) - 쉼표로 구분')
    fireEvent.change(aliasesInput, { target: { value: 'Human, Individual' } })

    const displayInput = await screen.findByLabelText('표시 이름 (Display Name)')
    fireEvent.change(displayInput, { target: { value: '사람' } })

    fireEvent.click(screen.getByRole('button', { name: 'T-Box 저장' }))
    await waitFor(() => expect(savedBody).toBeDefined())

    const operations = savedBody?.operations
    expect(Array.isArray(operations)).toBe(true)
    const classOp = (operations as Array<{
      stable_element_id: string
      element: Record<string, unknown>
    }>).find((operation) => (
      operation.stable_element_id === '019fa57b-52de-74c0-9f5e-06ae7b1bf3c0'
    ))
    expect(classOp?.element.aliases).toEqual(['Human', 'Individual'])
    expect(classOp?.element.display_name).toEqual('사람')
  })

  it('edits bounded Relation shape and relation-owned Property fields', async () => {
    let savedBody: Record<string, unknown> | undefined
    const relationId = 'relation:owns'
    const classA = {
      stable_element_id: 'class:person',
      kind: 'CLASS',
      canonical_name: 'Person',
      display_name: 'Person',
      aliases: [],
      vector_index_enabled: false,
      locked_by_later_block: false,
      block_id: blockId,
      ordinal: 0,
      version: 1,
      layout_x: 0,
      layout_y: 0,
    }
    const classB = {
      ...classA,
      stable_element_id: 'class:asset',
      canonical_name: 'Asset',
      display_name: 'Asset',
      ordinal: 1,
      layout_x: 280,
    }
    const relation = {
      stable_element_id: relationId,
      kind: 'RELATION',
      canonical_name: 'OWNS',
      display_name: 'Owns',
      source_stable_element_id: classA.stable_element_id,
      target_stable_element_id: classB.stable_element_id,
      direction: 'DIRECTED',
      cardinality: 'ONE_TO_MANY',
      aliases: [],
      vector_index_enabled: false,
      locked_by_later_block: false,
      block_id: blockId,
      ordinal: 2,
      version: 1,
    }
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const path = requestUrl(input)
      if (path.endsWith(`/drafts/${draftId}/tbox`) && !init?.method) {
        return Promise.resolve(json(tbox([classA, classB, relation])))
      }
      if (path.endsWith(`/drafts/${draftId}/tbox/blocks/${blockId}/operations`)) {
        savedBody = JSON.parse(init!.body as string) as Record<string, unknown>
        return Promise.resolve(json(tbox([classA, classB, relation]), '"3"'))
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
    expect(within(screen.getByLabelText('T-Box 그래프 캔버스')).getByText('No. 1'))
      .toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Person → Asset' }))

    expect(await screen.findByText('Relation 속성')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('방향 (Direction)'), {
      target: { value: 'BIDIRECTED' },
    })
    fireEvent.change(screen.getByLabelText('카디널리티 (Cardinality)'), {
      target: { value: 'MANY_TO_MANY' },
    })
    fireEvent.change(screen.getByLabelText('동의어 (Aliases) - 쉼표로 구분'), {
      target: { value: 'possesses, controls' },
    })
    fireEvent.change(screen.getByLabelText('새 Relation Property 이름'), {
      target: { value: 'confidence' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Relation Property 추가' }))

    expect(await screen.findByText('Property 속성')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('값 개수 (Value Cardinality)'), {
      target: { value: 'MULTI' },
    })
    fireEvent.click(screen.getByLabelText('필수 항목 (Required)'))
    fireEvent.change(screen.getByLabelText('단위 (Unit)'), {
      target: { value: 'ratio' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'T-Box 저장' }))

    await waitFor(() => expect(savedBody).toBeDefined())
    const operations = savedBody?.operations as Array<{
      stable_element_id: string
      element: Record<string, unknown>
    }>
    expect(operations.find((item) => item.stable_element_id === relationId)?.element)
      .toMatchObject({
        direction: 'BIDIRECTED',
        cardinality: 'MANY_TO_MANY',
        aliases: ['possesses', 'controls'],
      })
    expect(operations.find((item) => item.element.canonical_name === 'confidence')?.element)
      .toMatchObject({
        owner_relation_stable_element_id: relationId,
        data_type: 'STRING',
        value_cardinality: 'MULTI',
        nullable: false,
        unit: 'ratio',
      })
  })

  it('does not advance to A-Box when the fenced T-Box save fails', async () => {
    const onContinue = vi.fn()
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const path = requestUrl(input)
      if (path.endsWith(`/drafts/${draftId}/tbox`) && !init?.method) {
        return Promise.resolve(json(tbox()))
      }
      if (path.endsWith(`/drafts/${draftId}/tbox/blocks/${blockId}/operations`)) {
        return Promise.resolve(new Response(JSON.stringify({ detail: 'Draft ETag changed.' }), {
          status: 412,
          headers: { 'Content-Type': 'application/json', ETag: '"3"' },
        }))
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
        onContinue={onContinue}
      />,
    )

    await screen.findByText(/Typed T-Box Draft를 불러왔습니다/)
    fireEvent.change(screen.getByLabelText('최상위 Class 이름'), {
      target: { value: 'Asset' },
    })
    fireEvent.click(screen.getByRole('button', { name: '최상위 Class 추가' }))
    fireEvent.click(screen.getByRole('button', { name: 'T-Box 저장 후 A-Box로 이동' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining(`/tbox/blocks/${blockId}/operations`),
      expect.objectContaining({ method: 'POST' }),
    ))
    expect(onContinue).not.toHaveBeenCalled()
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
    expect(screen.queryByRole('button', {
      name: '직접 정의 블록 삭제',
    })).not.toBeInTheDocument()
    expect(screen.getByLabelText('직접 정의 이전 블록 잠김')).toBeInTheDocument()
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

  it('creates a direct block immediately from the compact block rail menu', async () => {
    const layered = tbox([])
    layered.blocks.push({
      id: secondBlockId,
      kind: 'DIRECT',
      title: '직접 정의',
      weight: 50,
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
        return Promise.resolve(json(tbox()))
      }
      if (path.endsWith(`/drafts/${draftId}/tbox/blocks`) && init?.method === 'POST') {
        return Promise.resolve(json(layered, '"3"'))
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
    fireEvent.click(screen.getByRole('button', { name: '블록 추가' }))
    const menu = document.getElementById('tbox-block-add-menu')
    fireEvent.click(within(menu!).getByRole('button', { name: '직접 정의' }))

    expect(await screen.findByText(/직접 정의 블록을 생성했습니다/)).toBeInTheDocument()
    expect(screen.getByRole('button', {
      name: '직접 정의 DIRECT 블록 선택',
      current: 'step',
    })).toBeInTheDocument()
    const createCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')
    expect(new Headers(createCall?.[1]?.headers).get('If-Match')).toBe('"2"')
    const createBody = createCall?.[1]?.body
    expect(JSON.parse(typeof createBody === 'string' ? createBody : '{}')).toEqual({
      kind: 'DIRECT',
      title: '직접 정의',
    })
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
    const catalogProposalId = '019fa57b-52de-74c0-9f5e-06ae7b1bf3d1'
    const catalogJobId = '019fa57b-52de-74c0-9f5e-06ae7b1bf3d2'
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const path = requestUrl(input)
      if (path.endsWith(`/drafts/${draftId}/tbox`)) {
        return Promise.resolve(json(tbox()))
      }
      if (path.includes(`/drafts/${draftId}/tbox/proposal-jobs?`)) {
        return Promise.resolve(json({ items: [], page: { next_cursor: null, limit: 20 } }))
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
            description_truncated: false,
            field_metadata: [],
            selection_fingerprint: null,
          }],
          page: {
            next_cursor: path.includes('cursor=catalog-next') ? null : 'catalog-next',
            limit: 50,
          },
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
            description: 'Governed order facts',
            description_truncated: false,
            field_metadata: [{
              field_path: 'order_id',
              field_type: 'KEY',
              native_data_type: 'uuid',
              description: 'Order identifier',
              description_truncated: false,
              tags: ['gold'],
              tags_truncated: false,
              glossary_terms: ['Order'],
              terms_truncated: false,
            }, {
              field_path: 'amount',
              field_type: null,
              native_data_type: 'numeric(18,2)',
              description: 'Gross amount',
              description_truncated: false,
              tags: [],
              tags_truncated: false,
              glossary_terms: ['Amount'],
              terms_truncated: false,
            }],
            selection_fingerprint: 'f'.repeat(64),
          },
          observed_at: '2026-07-31T01:00:00Z',
          stale_at: null,
        }))
      }
      if (
        path.endsWith(`/drafts/${draftId}/tbox/proposal-jobs`)
        && init?.method === 'POST'
      ) {
        return Promise.resolve(json({
          id: catalogJobId,
          draft_id: draftId,
          input_kind: 'CATALOG_SCHEMA',
          mode: 'APPEND_LAYER',
          target_block_id: secondBlockId,
          state: 'SUCCEEDED',
          stage: 'COMPLETED',
          progress_percent: 100,
          attempt_count: 1,
          maximum_attempts: 4,
          last_failure_code: null,
          version: 3,
          created_at: '2026-07-31T01:00:00Z',
          updated_at: '2026-07-31T01:01:00Z',
          completed_at: '2026-07-31T01:01:00Z',
          result_proposal_id: catalogProposalId,
          result_evidence_hash: 'c'.repeat(64),
          supersedes_job_id: null,
        }, '"3"'))
      }
      if (path.endsWith(`/drafts/${draftId}/tbox/proposals/${catalogProposalId}`)) {
        return Promise.resolve(json({
          id: catalogProposalId,
          draft_id: draftId,
          target_block_id: secondBlockId,
          state: 'READY',
          mode: 'APPEND_LAYER',
          merge_strategy: 'KEEP_ORIGINAL',
          base_draft_version: 2,
          prompt: 'Catalog schema proposal: orders',
          elements: [{
            stable_element_id: 'class:orders',
            kind: 'CLASS',
            canonical_name: 'Orders',
            display_name: 'Orders',
            ordinal: 0,
            version: 1,
            aliases: [],
            vector_index_enabled: false,
            locked_by_later_block: false,
          }],
          conflicts: [],
          source_reference: {
            pipeline_evidence: {
              typed_schema_parse: 'PASSED',
              deterministic_correction_passes: 1,
              aggregate_validation_passes: 1,
              cypher_execution: false,
            },
          },
          version: 1,
          created_at: '2026-07-31T01:01:00Z',
          updated_at: '2026-07-31T01:01:00Z',
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
    fireEvent.click(screen.getByRole('button', { name: '블록 추가' }))
    fireEvent.click(within(screen.getByRole('button', { name: '블록 추가' }).parentElement!)
      .getByRole('button', { name: 'DB 메타데이터' }))
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
    fireEvent.click(screen.getByRole('button', { name: '다음 50건 불러오기' }))
    await waitFor(() => {
      expect(fetchMock.mock.calls.map(([input]) => requestUrl(input))).toContainEqual(
        expect.stringContaining('cursor=catalog-next'),
      )
    })
    const results = await screen.findByRole('table', {
      name: 'T-Box 카탈로그 검색 결과',
    })
    fireEvent.click(within(results).getByText('orders'))
    const fields = await screen.findByRole('table', { name: 'orders 컬럼 선택' })
    const orderId = within(fields).getByRole('checkbox', { name: 'order_id 컬럼 선택' })
    const amount = within(fields).getByRole('checkbox', { name: 'amount 컬럼 선택' })
    expect(orderId).not.toBeChecked()
    expect(amount).not.toBeChecked()
    expect(within(fields).getByText('Order identifier')).toBeInTheDocument()
    expect(within(fields).getByText('numeric(18,2)')).toBeInTheDocument()
    expect(within(dialog).getByText(/선택 0개 \/ 최대 100개/)).toHaveTextContent(
      '최종 프롬프트를 4,000자로 검증합니다',
    )
    expect(within(dialog).getByRole('button', { name: '새 블록 Proposal' })).toBeDisabled()
    expect(within(dialog).getByRole('button', { name: '현재 블록 Proposal' })).toBeDisabled()
    fireEvent.click(orderId)
    fireEvent.click(amount)
    expect(within(dialog).getByText(/선택 2개 \/ 최대 100개/)).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: '새 블록 Proposal' }))

    expect(await screen.findByLabelText('T-Box Proposal 미리보기')).toBeInTheDocument()
    const jobCall = fetchMock.mock.calls.find(([input, options]) => (
      requestUrl(input).endsWith(`/drafts/${draftId}/tbox/proposal-jobs`)
      && options?.method === 'POST'
    ))
    const jobBody = jobCall?.[1]?.body
    expect(JSON.parse(typeof jobBody === 'string' ? jobBody : '{}')).toEqual({
      input_kind: 'CATALOG_SCHEMA',
      asset_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3d0',
      selected_field_paths: ['amount', 'order_id'],
      expected_selection_fingerprint: 'f'.repeat(64),
      mode: 'APPEND_LAYER',
    })
    expect(fetchMock.mock.calls.some(([input]) => (
      requestUrl(input).endsWith('/tbox/catalog-proposals')
    ))).toBe(false)
  })

  it.each([
    {
      code: 'CATALOG_PROPOSAL_PROMPT_TOO_LARGE',
      detail: '메타데이터가 포함된 Proposal 프롬프트가 4,000자를 초과합니다. 선택을 줄여 주세요.',
    },
    {
      code: 'CATALOG_PROPOSAL_SELECTION_STALE',
      detail: '카탈로그 메타데이터가 변경되었습니다. Dataset을 다시 불러오세요.',
    },
  ])('preserves the exact server Catalog error for $code', async ({ code, detail }) => {
    const assetId = '019fa57b-52de-74c0-9f5e-06ae7b1bf3d0'
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const path = requestUrl(input)
      if (path.endsWith(`/drafts/${draftId}/tbox`) && !init?.method) {
        return Promise.resolve(json(tbox()))
      }
      if (path.includes(`/drafts/${draftId}/tbox/proposal-jobs?`)) {
        return Promise.resolve(json({ items: [], page: { next_cursor: null, limit: 20 } }))
      }
      if (path.includes(`/drafts/${draftId}/tbox/catalog-sources?`)) {
        return Promise.resolve(json({
          items: [{
            id: assetId,
            name: 'orders',
            asset_type: 'TABLE',
            classification: 'INTERNAL',
            source_version: 'datahub-v8',
            projection_source_version: 'projection-v4',
            field_paths: [],
            fields_truncated: true,
            description_truncated: false,
            field_metadata: [],
            selection_fingerprint: null,
          }],
          page: { next_cursor: null, limit: 50 },
        }))
      }
      if (path.endsWith(`/drafts/${draftId}/tbox/catalog-sources/${assetId}`)) {
        return Promise.resolve(json({
          dataset: {
            id: assetId,
            name: 'orders',
            asset_type: 'TABLE',
            classification: 'INTERNAL',
            source_version: 'datahub-v8',
            projection_source_version: 'projection-v4',
            field_paths: ['order_id'],
            fields_truncated: false,
            description_truncated: false,
            field_metadata: [],
            selection_fingerprint: 'f'.repeat(64),
          },
          observed_at: '2026-08-01T01:00:00Z',
          stale_at: null,
        }))
      }
      if (
        path.endsWith(`/drafts/${draftId}/tbox/proposal-jobs`)
        && init?.method === 'POST'
      ) {
        return Promise.resolve(new Response(JSON.stringify({
          type: 'about:blank',
          title: 'Conflict',
          status: 409,
          detail,
          code,
          request_id: `request-${code}`,
        }), {
          status: 409,
          headers: { 'Content-Type': 'application/problem+json' },
        }))
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
    fireEvent.click(screen.getByRole('button', { name: '블록 추가' }))
    fireEvent.click(within(screen.getByRole('button', { name: '블록 추가' }).parentElement!)
      .getByRole('button', { name: 'DB 메타데이터' }))
    const dialog = await screen.findByRole('dialog', { name: 'DB 카탈로그에서 T-Box 제안' })
    const results = await within(dialog).findByRole('table', {
      name: 'T-Box 카탈로그 검색 결과',
    })
    fireEvent.click(within(results).getByText('orders'))
    const fields = await within(dialog).findByRole('table', { name: 'orders 컬럼 선택' })
    fireEvent.click(within(fields).getByRole('checkbox', { name: 'order_id 컬럼 선택' }))
    fireEvent.click(within(dialog).getByRole('button', { name: '새 블록 Proposal' }))

    expect(await within(dialog).findByLabelText('카탈로그 Proposal 오류'))
      .toHaveTextContent(detail)
    expect(within(fields).getByRole('checkbox', { name: 'order_id 컬럼 선택' })).toBeChecked()
  })

  it('requires a fresh server-issued Catalog fingerprint before creating a job', async () => {
    const assetId = '019fa57b-52de-74c0-9f5e-06ae7b1bf3d0'
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const path = requestUrl(input)
      if (path.endsWith(`/drafts/${draftId}/tbox`)) return Promise.resolve(json(tbox()))
      if (path.includes(`/drafts/${draftId}/tbox/proposal-jobs?`)) {
        return Promise.resolve(json({ items: [], page: { next_cursor: null, limit: 20 } }))
      }
      if (path.includes(`/drafts/${draftId}/tbox/catalog-sources?`)) {
        return Promise.resolve(json({
          items: [{
            id: assetId,
            name: 'orders',
            asset_type: 'TABLE',
            classification: 'INTERNAL',
            source_version: 'projection-v4',
            projection_source_version: 'projection-v4',
            field_paths: [],
            fields_truncated: true,
            description_truncated: false,
            field_metadata: [],
            selection_fingerprint: null,
          }],
          page: { next_cursor: null, limit: 50 },
        }))
      }
      if (path.endsWith(`/drafts/${draftId}/tbox/catalog-sources/${assetId}`)) {
        return Promise.resolve(json({
          dataset: {
            id: assetId,
            name: 'orders',
            asset_type: 'TABLE',
            classification: 'INTERNAL',
            source_version: 'datahub-v8',
            projection_source_version: 'projection-v4',
            field_paths: ['order_id'],
            fields_truncated: false,
            description_truncated: false,
            field_metadata: [],
            selection_fingerprint: null,
          },
          observed_at: '2026-08-01T01:00:00Z',
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
    fireEvent.click(screen.getByRole('button', { name: '블록 추가' }))
    fireEvent.click(within(screen.getByRole('button', { name: '블록 추가' }).parentElement!)
      .getByRole('button', { name: 'DB 메타데이터' }))
    const results = await screen.findByRole('table', { name: 'T-Box 카탈로그 검색 결과' })
    fireEvent.click(within(results).getByText('orders'))

    expect(await screen.findByRole('alert')).toHaveTextContent('Dataset을 다시 불러오세요')
    expect(screen.getByRole('button', { name: '새 블록 Proposal' })).toBeDisabled()
    expect(fetchMock.mock.calls.some(([input, options]) => (
      requestUrl(input).endsWith(`/drafts/${draftId}/tbox/proposal-jobs`)
      && options?.method === 'POST'
    ))).toBe(false)
  })

  it('keeps one Proposal source per block and exposes append-layer alternatives', async () => {
    const claimed = tbox([])
    const claimedBlock = claimed.blocks[0]!
    claimed.blocks[0] = {
      ...claimedBlock,
      kind: 'CATALOG_METADATA',
      title: '카탈로그 스키마',
      source_reference: {
        contract_version: 'KNOWLEDGE_STUDIO_CATALOG_SOURCE_PIN_V1',
      },
    }
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const path = requestUrl(input)
      if (path.endsWith(`/drafts/${draftId}/tbox`)) return Promise.resolve(json(claimed))
      if (path.includes(`/drafts/${draftId}/tbox/proposal-jobs?`)) {
        return Promise.resolve(json({ items: [], page: { next_cursor: null, limit: 20 } }))
      }
      if (path.includes(`/drafts/${draftId}/tbox/catalog-sources?`)) {
        return Promise.resolve(json({ items: [], page: { next_cursor: null, limit: 50 } }))
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
    expect(screen.getByText('[DB 메타데이터]')).toBeInTheDocument()
    expect(screen.getByLabelText('T-Box 블록 목록')).toBeInTheDocument()
    const workspace = screen.getByRole('article', { name: 'T-Box 단일 작업공간' })
    const layout = within(workspace).getByTestId('tbox-shared-workspace-layout')
    expect(layout).toHaveClass('xl:grid-cols-[240px_minmax(0,1fr)_180px_320px]')
    expect(within(workspace).getByLabelText('T-Box 블록')).toHaveClass(
      'xl:col-start-3',
      'xl:row-start-1',
    )
    expect(within(workspace).getByLabelText('T-Box Cypher 편집기').closest('section'))
      .toHaveClass('xl:col-span-3', 'xl:row-start-2')
    expect(within(workspace).getByLabelText('T-Box 블록 목록')).toHaveClass(
      'flex',
      'overflow-x-auto',
      'xl:grid',
    )
    expect(screen.getByRole('button', {
      name: '카탈로그 스키마 CATALOG_METADATA 블록 선택',
    })).toHaveAttribute('aria-current', 'step')
    expect(screen.getAllByLabelText('T-Box 그래프 캔버스')).toHaveLength(1)
    expect(screen.getAllByLabelText('T-Box Cypher 편집기')).toHaveLength(1)

    fireEvent.click(screen.getByRole('button', { name: '블록 추가' }))
    const menu = document.getElementById('tbox-block-add-menu')
    expect(menu).not.toBeNull()
    expect(within(menu!).getByRole('button', { name: '직접 정의' })).toBeEnabled()
    expect(within(menu!).getByRole('button', { name: '데이터 업로드' })).toBeEnabled()
    expect(within(menu!).getByRole('button', { name: 'DB 메타데이터' })).toBeEnabled()
    expect(within(menu!).getByRole('button', { name: 'LLM Assistant' })).toBeEnabled()
    expect(within(menu!).getByRole('button', { name: '다른 Asset' })).toBeEnabled()
  })

  it('opens an append-layer LLM Assistant from the block rail menu', async () => {
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const path = requestUrl(input)
      if (path.endsWith(`/drafts/${draftId}/tbox`)) return Promise.resolve(json(tbox()))
      if (path.includes(`/drafts/${draftId}/tbox/proposal-jobs?`)) {
        return Promise.resolve(json({ items: [], page: { next_cursor: null, limit: 20 } }))
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
    expect(screen.queryByRole('dialog', { name: 'LLM Schema Assistant' }))
      .not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '블록 추가' }))
    const menu = document.getElementById('tbox-block-add-menu')
    fireEvent.click(within(menu!).getByRole('button', { name: 'LLM Assistant' }))
    const dialog = await screen.findByRole('dialog', { name: 'LLM Schema Assistant' })
    fireEvent.change(within(dialog).getByLabelText('LLM T-Box 요청'), {
      target: { value: '업무 용어 스키마를 제안해 줘.' },
    })
    expect(within(dialog).getByRole('button', { name: '새 블록 Proposal' })).toBeEnabled()
    expect(within(dialog).getByRole('button', { name: '현재 블록 Proposal' })).toBeDisabled()
  })

  it('uploads a document through accepted storage and renders the durable job Proposal', async () => {
    const uploadId = '019fa57b-52de-74c0-9f5e-06ae7b1bf3d3'
    const proposalId = '019fa57b-52de-74c0-9f5e-06ae7b1bf3d4'
    vi.stubGlobal('crypto', {
      randomUUID: vi.fn().mockReturnValue('019fa57b-52de-74c0-9f5e-06ae7b1bf3ff'),
      subtle: {
        digest: vi.fn().mockResolvedValue(new Uint8Array(32).buffer),
      },
    })
    const upload = {
      id: uploadId,
      display_name: 'schema.json',
      state: 'INITIATED',
      size_bytes: 2,
      content_type: 'application/json',
      sha256: '0'.repeat(64),
      classification: 'INTERNAL',
      content_profile: 'KNOWLEDGE_STUDIO_DOCUMENT_V1',
      expires_at: '2026-07-31T03:00:00Z',
      version: 1,
      validation_summary: {},
      last_error_code: null,
      recommended_part_size_bytes: 10 * 1024 * 1024,
    }
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const path = requestUrl(input)
      if (path.endsWith(`/drafts/${draftId}/tbox`)) {
        return Promise.resolve(json(tbox()))
      }
      if (path.includes(`/drafts/${draftId}/tbox/proposal-jobs?`)) {
        return Promise.resolve(json({ items: [], page: { next_cursor: null, limit: 20 } }))
      }
      if (path.endsWith(`/drafts/${draftId}/source-uploads`) && init?.method === 'POST') {
        return Promise.resolve(json(upload, '"1"'))
      }
      if (path.endsWith(`/source-uploads/${uploadId}/parts`)) {
        return Promise.resolve(json({ url: 'https://objects.test/studio-part', expires_seconds: 900 }))
      }
      if (path === 'https://objects.test/studio-part') {
        return Promise.resolve(new Response(undefined, {
          status: 200,
          headers: { ETag: '"part-etag"' },
        }))
      }
      if (path.endsWith(`/source-uploads/${uploadId}/complete`)) {
        return Promise.resolve(json({
          ...upload,
          state: 'ACCEPTED',
          version: 5,
          validation_summary: { profile_configuration_hash: 'a'.repeat(64) },
        }, '"5"'))
      }
      if (path.endsWith(`/drafts/${draftId}/tbox/proposal-jobs`) && init?.method === 'POST') {
        return Promise.resolve(json({
          id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3d5',
          draft_id: draftId,
          input_kind: 'DOCUMENT_SCHEMA',
          mode: 'APPEND_LAYER',
          target_block_id: secondBlockId,
          state: 'SUCCEEDED',
          stage: 'COMPLETED',
          progress_percent: 100,
          attempt_count: 1,
          maximum_attempts: 4,
          last_failure_code: null,
          version: 3,
          created_at: '2026-07-31T01:00:00Z',
          updated_at: '2026-07-31T01:01:00Z',
          completed_at: '2026-07-31T01:01:00Z',
          result_proposal_id: proposalId,
          result_evidence_hash: 'b'.repeat(64),
          supersedes_job_id: null,
        }, '"3"'))
      }
      if (path.endsWith(`/drafts/${draftId}/tbox/proposals/${proposalId}`)) {
        return Promise.resolve(json({
          id: proposalId,
          draft_id: draftId,
          target_block_id: secondBlockId,
          state: 'READY',
          mode: 'APPEND_LAYER',
          merge_strategy: 'KEEP_ORIGINAL',
          base_draft_version: 2,
          prompt: 'Document schema proposal: schema.json',
          elements: [],
          conflicts: [],
          source_reference: {
            pipeline_evidence: {
              typed_schema_parse: 'PASSED',
              deterministic_correction_passes: 1,
              aggregate_validation_passes: 1,
              cypher_execution: false,
            },
          },
          version: 1,
          created_at: '2026-07-31T01:01:00Z',
          updated_at: '2026-07-31T01:01:00Z',
        }))
      }
      return Promise.reject(new Error(`Unexpected request: ${init?.method ?? 'GET'} ${path}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')
    const file = new File(['{}'], 'schema.json', { type: 'application/json' })
    Object.defineProperty(file, 'arrayBuffer', {
      value: () => Promise.resolve(new TextEncoder().encode('{}').buffer),
    })

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
    fireEvent.click(screen.getByRole('button', { name: '블록 추가' }))
    const menu = document.getElementById('tbox-block-add-menu')
    fireEvent.click(within(menu!).getByRole('button', { name: '데이터 업로드' }))
    const dialog = await screen.findByRole('dialog', { name: '문서 기반 T-Box Proposal' })
    expect(within(dialog).getByRole('radio', { name: /현재 블록 Proposal/ })).toBeDisabled()
    expect(within(dialog).getByRole('radio', { name: /새 블록 Proposal/ })).toBeChecked()
    fireEvent.change(within(dialog).getByLabelText('T-Box 분석 파일'), {
      target: { files: [file] },
    })
    fireEvent.click(within(dialog).getByRole('button', { name: '업로드 및 분석' }))

    expect(await screen.findByLabelText('T-Box Proposal 미리보기')).toBeInTheDocument()
    expect(within(dialog).getByText(/서버 상태 SUCCEEDED · 단계 COMPLETED · 100%/))
      .toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input]) => (
      requestUrl(input).endsWith('/tbox/document-proposals')
    ))).toBe(false)
  })

  it('restores the latest failed document job in its dialog without replaying it', async () => {
    const restoredJobId = '019fa57b-52de-74c0-9f5e-06ae7b1bf3d6'
    const restoredJob = {
      id: restoredJobId,
      draft_id: draftId,
      input_kind: 'DOCUMENT_SCHEMA',
      mode: 'APPEND_LAYER',
      target_block_id: null,
      state: 'FAILED',
      stage: 'INFERENCE',
      progress_percent: 70,
      attempt_count: 3,
      maximum_attempts: 3,
      last_failure_code: 'PROVIDER_REJECTED',
      version: 4,
      created_at: '2026-07-31T01:00:00Z',
      updated_at: '2026-07-31T01:02:00Z',
      completed_at: '2026-07-31T01:02:00Z',
      result_proposal_id: null,
      result_evidence_hash: null,
      supersedes_job_id: null,
    }
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const path = requestUrl(input)
      if (path.endsWith(`/drafts/${draftId}/tbox`)) {
        return Promise.resolve(json(tbox()))
      }
      if (path.includes(`/drafts/${draftId}/tbox/proposal-jobs?`)) {
        return Promise.resolve(json({
          items: [restoredJob],
          page: { next_cursor: null, limit: 20 },
        }))
      }
      if (path.endsWith(`/drafts/${draftId}/tbox/proposal-jobs/${restoredJobId}`)) {
        return Promise.resolve(json(restoredJob, '"4"'))
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

    const dialog = await screen.findByRole('dialog', { name: '문서 기반 T-Box Proposal' })
    expect(within(dialog).getByText(/서버 상태 FAILED · 단계 INFERENCE · 70%/))
      .toBeInTheDocument()
    expect(within(dialog).getByRole('alert')).toHaveTextContent('PROVIDER_REJECTED')
    expect(within(dialog).getByRole('button', { name: '작업 다시 시도' })).toBeEnabled()
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
  })

  it('restores the latest successful catalog result for explicit review without applying it', async () => {
    const restoredJobId = '019fa57b-52de-74c0-9f5e-06ae7b1bf3d7'
    const restoredProposalId = '019fa57b-52de-74c0-9f5e-06ae7b1bf3d8'
    const restoredJob = {
      id: restoredJobId,
      draft_id: draftId,
      input_kind: 'CATALOG_SCHEMA',
      mode: 'APPEND_LAYER',
      target_block_id: null,
      state: 'SUCCEEDED',
      stage: 'COMPLETED',
      progress_percent: 100,
      attempt_count: 1,
      maximum_attempts: 4,
      last_failure_code: null,
      version: 3,
      created_at: '2026-07-31T01:00:00Z',
      updated_at: '2026-07-31T01:01:00Z',
      completed_at: '2026-07-31T01:01:00Z',
      result_proposal_id: restoredProposalId,
      result_evidence_hash: 'b'.repeat(64),
      supersedes_job_id: null,
    }
    const restoredProposal = {
      id: restoredProposalId,
      draft_id: draftId,
      target_block_id: secondBlockId,
      state: 'READY',
      mode: 'APPEND_LAYER',
      merge_strategy: 'KEEP_ORIGINAL',
      base_draft_version: 2,
      prompt: 'Catalog metadata proposal',
      elements: [{
        stable_element_id: 'class:CatalogEntity',
        kind: 'CLASS',
        canonical_name: 'CatalogEntity',
        display_name: 'Catalog Entity',
        ordinal: 0,
        version: 1,
        aliases: [],
        vector_index_enabled: false,
        locked_by_later_block: false,
      }],
      conflicts: [],
      source_reference: {
        pipeline_evidence: {
          typed_schema_parse: 'PASSED',
          deterministic_correction_passes: 1,
          aggregate_validation_passes: 1,
          cypher_execution: false,
        },
      },
      version: 1,
      created_at: '2026-07-31T01:01:00Z',
      updated_at: '2026-07-31T01:01:00Z',
    }
    const onDraftUpdate = vi.fn()
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const path = requestUrl(input)
      if (path.endsWith(`/drafts/${draftId}/tbox`)) {
        return Promise.resolve(json(tbox()))
      }
      if (path.includes(`/drafts/${draftId}/tbox/proposal-jobs?`)) {
        return Promise.resolve(json({
          items: [restoredJob],
          page: { next_cursor: null, limit: 20 },
        }))
      }
      if (path.endsWith(`/drafts/${draftId}/tbox/proposal-jobs/${restoredJobId}`)) {
        return Promise.resolve(json(restoredJob, '"3"'))
      }
      if (path.endsWith(`/drafts/${draftId}/tbox/proposals/${restoredProposalId}`)) {
        return Promise.resolve(json(restoredProposal))
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
        onDraftUpdate={onDraftUpdate}
        onContinue={vi.fn()}
      />,
    )

    const dialog = await screen.findByRole('dialog', {
      name: 'DB 카탈로그에서 T-Box 제안',
    })
    expect(within(dialog).getByLabelText('카탈로그 Proposal 작업 상태'))
      .toHaveTextContent('SUCCEEDED · COMPLETED · 100%')
    expect(await screen.findByLabelText('T-Box Proposal 미리보기')).toBeInTheDocument()
    expect(onDraftUpdate).not.toHaveBeenCalled()
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
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
      target_block_id: secondBlockId,
      state: 'READY',
      mode: 'APPEND_LAYER',
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
    fireEvent.click(screen.getByRole('button', { name: '블록 추가' }))
    const menu = document.getElementById('tbox-block-add-menu')
    fireEvent.click(within(menu!).getByRole('button', { name: '다른 Asset' }))
    const dialog = await screen.findByRole('dialog', {
      name: '다른 지식 Asset의 T-Box 붙이기',
    })
    expect(dialog).toHaveClass('app-dialog-workspace')
    expect(within(dialog).getByRole('button', { name: '현재 블록 Proposal' })).toBeDisabled()

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
    fireEvent.click(within(dialog).getByRole('button', { name: '새 블록 Proposal' }))

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
      mode: 'APPEND_LAYER',
    })
  })

  it('presents inheritance-cycle warning and disables save on invalid schema', async () => {
    const classA = {
      stable_element_id: 'class:a',
      kind: 'CLASS',
      canonical_name: 'A',
      display_name: 'A',
      parent_stable_element_id: 'class:b',
      aliases: [],
      vector_index_enabled: false,
      locked_by_later_block: false,
      block_id: blockId,
      ordinal: 0,
      version: 1,
      layout_x: 0,
      layout_y: 0,
    }
    const classB = {
      stable_element_id: 'class:b',
      kind: 'CLASS',
      canonical_name: 'B',
      display_name: 'B',
      parent_stable_element_id: 'class:a',
      aliases: [],
      vector_index_enabled: false,
      locked_by_later_block: false,
      block_id: blockId,
      ordinal: 1,
      version: 1,
      layout_x: 100,
      layout_y: 100,
    }
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const path = requestUrl(input)
      if (path.endsWith(`/drafts/${draftId}/tbox`) && !init?.method) {
        return Promise.resolve(json(tbox([classA, classB])))
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

    expect(screen.getByRole('alert')).toHaveTextContent('Class 상속 순환이 감지되었습니다.')
    expect(screen.getByRole('button', { name: 'T-Box 저장' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'T-Box 저장 후 A-Box로 이동' })).toBeDisabled()
  })

  it('exposes a controlled canvas lock instead of the React Flow internal toggle', async () => {
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const path = requestUrl(input)
      if (path.endsWith(`/drafts/${draftId}/tbox`) && !init?.method) {
        return Promise.resolve(json(tbox()))
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
    expect(screen.queryByRole('button', { name: 'Toggle Interactivity' })).not.toBeInTheDocument()

    const lockButton = screen.getByRole('button', { name: '캔버스 잠금' })
    expect(lockButton).toHaveAttribute('aria-pressed', 'false')
    fireEvent.click(lockButton)
    expect(screen.getByRole('button', { name: '캔버스 잠금 해제' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })
})
