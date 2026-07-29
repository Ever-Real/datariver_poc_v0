import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
} from 'react'
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  addEdge,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import {
  Bot,
  ChevronDown,
  ChevronUp,
  Database,
  FileUp,
  GitBranch,
  Layers3,
  Plus,
  Save,
  Trash2,
} from 'lucide-react'
import type { ApiClient } from '../../../../api/client'
import { Dialog } from '../../../../components/common/Dialog'
import {
  formatSafeCypherDraft,
  parseSafeCypherDraft,
  type SafeCypherEdge,
  type SafeCypherNode,
} from '../../knowledgeCypherDraft'
import {
  applyKnowledgeStudioTBoxOperations,
  applyKnowledgeStudioTBoxProposal,
  createKnowledgeStudioTBoxBlock,
  createKnowledgeStudioTBoxProposal,
  getKnowledgeStudioTBox,
  newKnowledgeStudioIdempotencyKey,
  updateKnowledgeStudioTBoxBlock,
  type KnowledgeStudioDraft,
  type KnowledgeStudioTBox,
  type KnowledgeStudioTBoxBlock,
  type KnowledgeStudioTBoxBlockKind,
  type KnowledgeStudioTBoxElement,
  type KnowledgeStudioTBoxOperation,
  type KnowledgeStudioTBoxProposal,
} from '../knowledgeStudioApi'

type SchemaNode = Node<{ label: string; ordinal: number; editable: boolean }, 'schemaClass'>
type SchemaEdge = Edge<{ relation: string }>

interface GraphBuilderProps {
  client: ApiClient
  draftId: string
  etag: string
  busy: boolean
  lifecycleState?: 'DRAFT' | 'REVIEW' | 'PUBLISHED' | 'DISCARDED'
  onDraftUpdate: (draft: KnowledgeStudioDraft, etag: string) => void
  onContinue: () => void
}

const blockOptions: Array<{
  kind: KnowledgeStudioTBoxBlockKind
  title: string
  description: string
  icon: typeof Plus
}> = [
  {
    kind: 'DIRECT',
    title: '직접 정의',
    description: 'Typed Class, Property, Relation을 직접 설계합니다.',
    icon: Plus,
  },
  {
    kind: 'DOCUMENT_SCHEMA',
    title: '데이터 주입(문서)',
    description: 'PDF, DOCX, XLSX에서 인스턴스가 아닌 구조만 제안받습니다.',
    icon: FileUp,
  },
  {
    kind: 'CATALOG_METADATA',
    title: 'DB 활용',
    description: '승인된 카탈로그 스키마와 계보 버전을 선택합니다.',
    icon: Database,
  },
  {
    kind: 'ASSET_RELEASE',
    title: '다른 Asset 붙이기',
    description: '기존 Asset의 불변 버전을 새 레이어로 결합합니다.',
    icon: Layers3,
  },
]

function SchemaClassNode({ data, selected }: NodeProps<SchemaNode>) {
  return (
    <div className={`relative w-[190px] rounded-md border bg-[#10253d] px-4 py-3 text-xs font-extrabold text-slate-50 shadow-xl ${
      selected ? 'border-amber-300 ring-2 ring-amber-300/40' : 'border-sky-400'
    }`}>
      <span className="absolute -left-2 -top-2 rounded-full border border-sky-200 bg-sky-500 px-2 py-0.5 text-[9px] font-black text-white shadow">
        No. {data.ordinal}
      </span>
      <span className="block truncate pt-1">{data.label}</span>
      <Handle type="target" position={Position.Left} className="border-sky-200! bg-sky-500!" />
      <Handle type="source" position={Position.Right} className="border-sky-200! bg-sky-500!" />
    </div>
  )
}

const schemaNodeTypes = { schemaClass: SchemaClassNode }

function asSafeGraph(elements: KnowledgeStudioTBoxElement[]): {
  nodes: SafeCypherNode[]
  edges: SafeCypherEdge[]
} {
  const classes = elements.filter((item) => item.kind === 'CLASS')
  const nodes = classes.map((item, index) => ({
    id: item.stable_element_id,
    label: item.canonical_name,
    alias: `n${index}`,
  }))
  const aliasById = new Map(nodes.map((item) => [item.id, item.alias ?? '']))
  const edges = elements
    .filter((item) => item.kind === 'RELATION')
    .flatMap((item) => {
      const source = item.source_stable_element_id
      const target = item.target_stable_element_id
      if (!source || !target || !aliasById.has(source) || !aliasById.has(target)) return []
      return [{
        id: item.stable_element_id,
        source,
        target,
        relation: item.canonical_name,
        sourceAlias: aliasById.get(source),
        targetAlias: aliasById.get(target),
      }]
    })
  return { nodes, edges }
}

function effectiveElements(record: KnowledgeStudioTBox): KnowledgeStudioTBoxElement[] {
  return [...record.blocks]
    .sort((left, right) => left.weight - right.weight || left.ordinal - right.ordinal)
    .flatMap((block) => block.elements.map((item) => ({
      ...item,
      block_id: item.block_id ?? block.id,
      aliases: item.aliases ?? [],
      vector_index_enabled: item.vector_index_enabled ?? false,
    })))
}

function flowGraph(
  elements: KnowledgeStudioTBoxElement[],
  editableBlockId: string,
): {
  nodes: SchemaNode[]
  edges: SchemaEdge[]
} {
  const classes = elements.filter((item) => item.kind === 'CLASS')
  const nodes = classes.map((item, index): SchemaNode => ({
    id: item.stable_element_id,
    type: 'schemaClass',
    position: {
      x: item.layout_x ?? 70 + (index % 3) * 245,
      y: item.layout_y ?? 90 + Math.floor(index / 3) * 165,
    },
    data: {
      label: item.display_name,
      ordinal: item.ordinal + 1,
      editable: item.block_id === editableBlockId || item.block_id === undefined,
    },
    draggable: item.block_id === editableBlockId || item.block_id === undefined,
    ariaLabel: `No. ${item.ordinal + 1}, ${item.display_name} 클래스`,
  }))
  const edges = elements
    .filter((item) => item.kind === 'RELATION')
    .flatMap((item): SchemaEdge[] => {
      if (!item.source_stable_element_id || !item.target_stable_element_id) return []
      return [{
        id: item.stable_element_id,
        source: item.source_stable_element_id,
        target: item.target_stable_element_id,
        label: item.display_name,
        data: { relation: item.canonical_name },
        markerEnd: { type: MarkerType.ArrowClosed, color: '#7dd3fc' },
        style: { stroke: '#7dd3fc', strokeWidth: 1.6 },
        labelStyle: { fill: '#e2e8f0', fontWeight: 700 },
      }]
    })
  return { nodes, edges }
}

function elementPayload(
  item: KnowledgeStudioTBoxElement,
): Omit<KnowledgeStudioTBoxElement, 'ordinal' | 'version' | 'block_id'> {
  return {
    stable_element_id: item.stable_element_id,
    kind: item.kind,
    canonical_name: item.canonical_name,
    display_name: item.display_name,
    parent_stable_element_id: item.parent_stable_element_id,
    source_stable_element_id: item.source_stable_element_id,
    target_stable_element_id: item.target_stable_element_id,
    data_type: item.data_type,
    nullable: item.nullable,
    definition: item.definition,
    aliases: item.aliases,
    unit: item.unit,
    vector_index_enabled: item.vector_index_enabled,
    layout_x: item.layout_x,
    layout_y: item.layout_y,
  }
}

function createdClass(
  label: string,
  position: { x: number; y: number },
  ordinal: number,
): KnowledgeStudioTBoxElement {
  const id = `class:${crypto.randomUUID()}`
  return {
    stable_element_id: id,
    kind: 'CLASS',
    canonical_name: label,
    display_name: label,
    ordinal,
    version: 1,
    aliases: [],
    vector_index_enabled: false,
    layout_x: position.x,
    layout_y: position.y,
  }
}

function canonicalName(value: string): string {
  const cleaned = value.trim().replace(/[^A-Za-z0-9_]/g, '_')
  if (!cleaned) return ''
  return /^[A-Za-z]/.test(cleaned) ? cleaned : `Class_${cleaned}`
}

function aliasesFromInput(value: string): string[] {
  const seen = new Set<string>()
  return value
    .split(',')
    .map((item) => item.trim())
    .filter((item) => {
      if (!item) return false
      const identity = item.toLocaleLowerCase()
      if (seen.has(identity)) return false
      seen.add(identity)
      return true
    })
    .slice(0, 50)
}

export function GraphBuilder({
  client,
  draftId,
  etag,
  busy,
  lifecycleState = 'DRAFT',
  onDraftUpdate,
  onContinue,
}: GraphBuilderProps) {
  const [record, setRecord] = useState<KnowledgeStudioTBox>()
  const [responseEtag, setResponseEtag] = useState(etag)
  const [selectedBlockId, setSelectedBlockId] = useState('')
  const [elements, setElements] = useState<KnowledgeStudioTBoxElement[]>([])
  const [baseline, setBaseline] = useState<KnowledgeStudioTBoxElement[]>([])
  const [nodes, setNodes, onNodesChange] = useNodesState<SchemaNode>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<SchemaEdge>([])
  const [editorText, setEditorText] = useState('')
  const [editorError, setEditorError] = useState<{
    message: string
    line: number
    column: number
  }>()
  const [selectedElementId, setSelectedElementId] = useState('')
  const [newClassName, setNewClassName] = useState('')
  const [newPropertyName, setNewPropertyName] = useState('')
  const [status, setStatus] = useState('T-Box 정본을 불러오는 중입니다.')
  const [working, setWorking] = useState(false)
  const [showBlockMenu, setShowBlockMenu] = useState(false)
  const [assistantPrompt, setAssistantPrompt] = useState('')
  const [proposal, setProposal] = useState<KnowledgeStudioTBoxProposal>()
  const [conflictOpen, setConflictOpen] = useState(false)
  const [conflictActions, setConflictActions] = useState<Record<string, 'KEEP_ORIGINAL' | 'ACCEPT_PROPOSAL'>>({})
  const locked = lifecycleState !== 'DRAFT'

  const selectedBlock = record?.blocks.find((item) => item.id === selectedBlockId)
  const selectedElement = elements.find((item) => item.stable_element_id === selectedElementId)
  const selectedElementEditable = Boolean(
    selectedElement
    && (selectedElement.block_id === selectedBlockId || selectedElement.block_id === undefined),
  )
  const properties = selectedElement?.kind === 'CLASS'
    ? elements.filter(
      (item) => item.kind === 'PROPERTY'
        && item.parent_stable_element_id === selectedElement.stable_element_id,
    )
    : []

  const applyBlock = useCallback((
    block: KnowledgeStudioTBoxBlock,
    source: KnowledgeStudioTBox,
  ) => {
    const nextElements = effectiveElements(source)
    const blockElements = block.elements.map((item) => ({
      ...item,
      block_id: item.block_id ?? block.id,
      aliases: item.aliases ?? [],
      vector_index_enabled: item.vector_index_enabled ?? false,
    }))
    const graph = flowGraph(nextElements, block.id)
    const safe = asSafeGraph(nextElements)
    setSelectedBlockId(block.id)
    setElements(nextElements)
    setBaseline(blockElements)
    setNodes(graph.nodes)
    setEdges(graph.edges)
    setEditorText(formatSafeCypherDraft(safe.nodes, safe.edges))
    setEditorError(undefined)
    setSelectedElementId('')
  }, [setEdges, setNodes])

  const applyResponse = useCallback((
    next: KnowledgeStudioTBox,
    nextEtag: string,
    preferredBlockId?: string,
  ) => {
    setRecord(next)
    setResponseEtag(nextEtag)
    onDraftUpdate(next.draft, nextEtag)
    const selected = next.blocks.find((item) => item.id === (preferredBlockId ?? selectedBlockId))
      ?? next.blocks[0]
    if (selected) applyBlock(selected, next)
  }, [applyBlock, onDraftUpdate, selectedBlockId])

  useEffect(() => {
    const controller = new AbortController()
    void getKnowledgeStudioTBox(client, draftId)
      .then((response) => {
        if (controller.signal.aborted || !response.etag) return
        setRecord(response.data)
        setResponseEtag(response.etag)
        const first = response.data.blocks[0]
        if (first) applyBlock(first, response.data)
        setStatus('Typed T-Box Draft를 불러왔습니다.')
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setStatus(error instanceof Error ? error.message : 'T-Box Draft를 불러오지 못했습니다.')
        }
      })
    return () => controller.abort()
  }, [applyBlock, client, draftId])

  const syncCanvasAndEditor = useCallback((next: KnowledgeStudioTBoxElement[]) => {
    const graph = flowGraph(next, selectedBlockId)
    const safe = asSafeGraph(next)
    setElements(next)
    setNodes(graph.nodes)
    setEdges(graph.edges)
    setEditorText(formatSafeCypherDraft(safe.nodes, safe.edges))
    setEditorError(undefined)
  }, [selectedBlockId, setEdges, setNodes])

  const changeEditor = (value: string) => {
    setEditorText(value)
    const previous = asSafeGraph(elements)
    const parsed = parseSafeCypherDraft(value, previous)
    if (parsed.error) {
      setEditorError(parsed.diagnostic ?? {
        message: parsed.error,
        line: 1,
        column: 1,
      })
      return
    }
    const inherited = elements.filter(
      (item) => item.block_id !== undefined && item.block_id !== selectedBlockId,
    )
    const parsedNodes = new Map(parsed.nodes.map((item) => [item.id, item]))
    const parsedEdges = new Map(parsed.edges.map((item) => [item.id, item]))
    const inheritedChanged = inherited.some((item) => {
      if (item.kind === 'CLASS') {
        return parsedNodes.get(item.stable_element_id)?.label !== item.canonical_name
      }
      if (item.kind === 'RELATION') {
        const edge = parsedEdges.get(item.stable_element_id)
        return (
          edge?.relation !== item.canonical_name
          || edge.source !== item.source_stable_element_id
          || edge.target !== item.target_stable_element_id
        )
      }
      return false
    })
    if (inheritedChanged) {
      setEditorError({
        message: '이전 블록의 요소는 현재 레이어에서 변경하거나 삭제할 수 없습니다.',
        line: 1,
        column: 1,
      })
      return
    }
    const priorById = new Map(elements.map((item) => [item.stable_element_id, item]))
    const classIds = new Set(parsed.nodes.map((item) => item.id))
    let nextOrdinal = Math.max(-1, ...elements.map((item) => item.ordinal)) + 1
    const nextClasses = parsed.nodes.map((item, index): KnowledgeStudioTBoxElement => {
      const prior = priorById.get(item.id)
      const node = nodes.find((candidate) => candidate.id === item.id)
      return {
        stable_element_id: item.id,
        kind: 'CLASS',
        canonical_name: item.label,
        display_name: prior?.display_name ?? item.label,
        definition: prior?.definition,
        aliases: prior?.aliases ?? [],
        vector_index_enabled: false,
        block_id: prior?.block_id,
        layout_x: node?.position.x ?? 70 + (index % 3) * 245,
        layout_y: node?.position.y ?? 90 + Math.floor(index / 3) * 165,
        ordinal: prior?.ordinal ?? nextOrdinal++,
        version: prior?.version ?? 1,
      }
    })
    const nextProperties = elements.filter(
      (item) => item.kind === 'PROPERTY'
        && Boolean(item.parent_stable_element_id && classIds.has(item.parent_stable_element_id)),
    )
    const nextRelations = parsed.edges.map((item): KnowledgeStudioTBoxElement => {
      const prior = priorById.get(item.id)
      return {
        stable_element_id: item.id,
        kind: 'RELATION',
        canonical_name: item.relation,
        display_name: prior?.display_name ?? item.relation,
        source_stable_element_id: item.source,
        target_stable_element_id: item.target,
        aliases: prior?.aliases ?? [],
        vector_index_enabled: false,
        block_id: prior?.block_id,
        ordinal: prior?.ordinal ?? nextOrdinal++,
        version: prior?.version ?? 1,
      }
    })
    const next = [...nextClasses, ...nextProperties, ...nextRelations]
    const graph = flowGraph(next, selectedBlockId)
    setElements(next)
    setNodes(graph.nodes)
    setEdges(graph.edges)
    setEditorError(undefined)
  }

  const addClass = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const name = canonicalName(newClassName)
    if (!name || locked || working) return
    const item = createdClass(name, {
      x: 80 + (nodes.length % 3) * 245,
      y: 100 + Math.floor(nodes.length / 3) * 165,
    }, Math.max(-1, ...elements.map((element) => element.ordinal)) + 1)
    syncCanvasAndEditor([...elements, item])
    setSelectedElementId(item.stable_element_id)
    setNewClassName('')
  }

  const connect = useCallback((connection: Connection) => {
    if (locked || !connection.source || !connection.target) return
    const stableId = `relation:${crypto.randomUUID()}`
    const relation: KnowledgeStudioTBoxElement = {
      stable_element_id: stableId,
      kind: 'RELATION',
      canonical_name: 'RELATED_TO',
      display_name: 'RELATED_TO',
      source_stable_element_id: connection.source,
      target_stable_element_id: connection.target,
      aliases: [],
      vector_index_enabled: false,
      ordinal: Math.max(-1, ...elements.map((item) => item.ordinal)) + 1,
      version: 1,
    }
    const next = [...elements, relation]
    setElements(next)
    setEdges((current) => addEdge({
      ...connection,
      id: stableId,
      label: 'RELATED_TO',
      data: { relation: 'RELATED_TO' },
      markerEnd: { type: MarkerType.ArrowClosed, color: '#7dd3fc' },
      style: { stroke: '#7dd3fc', strokeWidth: 1.6 },
    }, current))
    const safe = asSafeGraph(next)
    setEditorText(formatSafeCypherDraft(safe.nodes, safe.edges))
    setEditorError(undefined)
  }, [elements, locked, setEdges])

  const deleteSelected = () => {
    if (!selectedElement || !selectedElementEditable || locked || working) return
    const inheritedDependants = elements.filter((item) => (
      item.block_id !== undefined
      && item.block_id !== selectedBlockId
      && (
        item.parent_stable_element_id === selectedElement.stable_element_id
        || item.source_stable_element_id === selectedElement.stable_element_id
        || item.target_stable_element_id === selectedElement.stable_element_id
      )
    ))
    if (inheritedDependants.length > 0) {
      setStatus(
        '다른 블록이 참조하는 요소입니다. 참조 블록을 먼저 정리한 뒤 삭제하세요.',
      )
      return
    }
    const removed = new Set([selectedElement.stable_element_id])
    if (selectedElement.kind === 'CLASS') {
      for (const item of elements) {
        if (
          item.parent_stable_element_id === selectedElement.stable_element_id
          || item.source_stable_element_id === selectedElement.stable_element_id
          || item.target_stable_element_id === selectedElement.stable_element_id
        ) removed.add(item.stable_element_id)
      }
    }
    syncCanvasAndEditor(elements.filter((item) => !removed.has(item.stable_element_id)))
    setSelectedElementId('')
  }

  const addProperty = () => {
    if (selectedElement?.kind !== 'CLASS' || locked || working) return
    const name = canonicalName(newPropertyName)
    if (!name) return
    const property: KnowledgeStudioTBoxElement = {
      stable_element_id: `property:${crypto.randomUUID()}`,
      kind: 'PROPERTY',
      canonical_name: name,
      display_name: name,
      parent_stable_element_id: selectedElement.stable_element_id,
      data_type: 'STRING',
      nullable: true,
      aliases: [],
      vector_index_enabled: false,
      ordinal: Math.max(-1, ...elements.map((item) => item.ordinal)) + 1,
      version: 1,
    }
    syncCanvasAndEditor([...elements, property])
    setSelectedElementId(property.stable_element_id)
    setNewPropertyName('')
  }

  const save = async () => {
    if (!selectedBlock || editorError || locked || working) return
    const positioned = elements.map((item) => {
      const node = nodes.find((candidate) => candidate.id === item.stable_element_id)
      return node ? { ...item, layout_x: node.position.x, layout_y: node.position.y } : item
    })
    const targetElements = positioned.filter(
      (item) => item.block_id === selectedBlock.id || item.block_id === undefined,
    )
    const currentIds = new Set(targetElements.map((item) => item.stable_element_id))
    const operations: KnowledgeStudioTBoxOperation[] = [
      ...targetElements.map((item): KnowledgeStudioTBoxOperation => ({
        operation: 'UPSERT_ELEMENT',
        stable_element_id: item.stable_element_id,
        element: elementPayload(item),
      })),
      ...baseline
        .filter((item) => !currentIds.has(item.stable_element_id))
        .map((item): KnowledgeStudioTBoxOperation => ({
          operation: 'DELETE_ELEMENT',
          stable_element_id: item.stable_element_id,
        })),
    ]
    if (operations.length === 0) {
      setStatus('현재 블록에는 저장할 Typed T-Box 요소가 없습니다.')
      return
    }
    setWorking(true)
    setStatus('Typed Operation을 검증하고 저장 중입니다.')
    try {
      const response = await applyKnowledgeStudioTBoxOperations(
        client,
        draftId,
        selectedBlock.id,
        operations,
        responseEtag,
        newKnowledgeStudioIdempotencyKey(),
      )
      if (!response.etag) return
      applyResponse(response.data, response.etag)
      setStatus(`Typed T-Box 저장 완료 · version ${response.data.draft.version}`)
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'T-Box 저장에 실패했습니다.')
    } finally {
      setWorking(false)
    }
  }

  const createBlock = async (option: typeof blockOptions[number]) => {
    if (locked || working) return
    setWorking(true)
    try {
      const response = await createKnowledgeStudioTBoxBlock(
        client,
        draftId,
        { kind: option.kind, title: option.title },
        responseEtag,
        newKnowledgeStudioIdempotencyKey(),
      )
      if (!response.etag) return
      const createdBlockId = response.data.blocks.at(-1)?.id
      applyResponse(response.data, response.etag, createdBlockId)
      setShowBlockMenu(false)
      setStatus(`${option.title} 블록을 생성했습니다.`)
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '블록을 생성하지 못했습니다.')
    } finally {
      setWorking(false)
    }
  }

  const updateBlock = async (
    block: KnowledgeStudioTBoxBlock,
    values: { weight?: number; collapsed?: boolean },
  ) => {
    if (locked || working) return
    setWorking(true)
    try {
      const response = await updateKnowledgeStudioTBoxBlock(
        client,
        draftId,
        block.id,
        {
          title: block.title,
          weight: values.weight ?? block.weight,
          collapsed: values.collapsed ?? block.collapsed,
        },
        responseEtag,
        newKnowledgeStudioIdempotencyKey(),
      )
      if (!response.etag) return
      applyResponse(response.data, response.etag)
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '블록 설정을 저장하지 못했습니다.')
    } finally {
      setWorking(false)
    }
  }

  const applyProposal = async (
    selected: KnowledgeStudioTBoxProposal,
    strategy: 'KEEP_ORIGINAL' | 'RESOLVE',
  ) => {
    setWorking(true)
    try {
      const response = await applyKnowledgeStudioTBoxProposal(
        client,
        draftId,
        selected.id,
        {
          merge_strategy: strategy,
          resolutions: strategy === 'RESOLVE'
            ? selected.conflicts.map((conflict) => ({
              conflict_id: conflict.conflict_id,
              action: conflictActions[conflict.conflict_id] ?? 'KEEP_ORIGINAL',
            }))
            : [],
        },
        responseEtag,
        newKnowledgeStudioIdempotencyKey(),
      )
      if (!response.etag) return
      applyResponse(response.data, response.etag)
      setConflictOpen(false)
      setProposal(undefined)
      setAssistantPrompt('')
      setStatus('LLM Proposal을 Typed T-Box에 반영했습니다.')
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'LLM Proposal 반영에 실패했습니다.')
    } finally {
      setWorking(false)
    }
  }

  const requestProposal = async (
    mode: 'MERGE_INTO_CURRENT' | 'APPEND_LAYER',
  ) => {
    if (!assistantPrompt.trim() || working || locked || !selectedBlock) return
    setWorking(true)
    setStatus('서버의 승인된 LLM 런타임에서 T-Box Proposal을 생성 중입니다.')
    try {
      const next = await createKnowledgeStudioTBoxProposal(client, draftId, {
        target_block_id: mode === 'MERGE_INTO_CURRENT' ? selectedBlock.id : undefined,
        mode,
        prompt: assistantPrompt.trim(),
      }, responseEtag)
      setProposal(next)
      setConflictActions(Object.fromEntries(
        next.conflicts.map((item) => [item.conflict_id, 'KEEP_ORIGINAL']),
      ))
      if (next.conflicts.length > 0) {
        setWorking(false)
        setConflictOpen(true)
        setStatus(`${next.conflicts.length}개의 병합 충돌을 확인해야 합니다.`)
      } else {
        await applyProposal(next, 'KEEP_ORIGINAL')
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'LLM Proposal 생성에 실패했습니다.')
      setWorking(false)
    }
  }

  const updateSelected = (patch: Partial<KnowledgeStudioTBoxElement>) => {
    if (!selectedElement || !selectedElementEditable) return
    const next = elements.map((item) => (
      item.stable_element_id === selectedElement.stable_element_id
        ? { ...item, ...patch }
        : item
    ))
    syncCanvasAndEditor(next)
  }

  if (!record) {
    return (
      <section className="grid min-h-[520px] place-items-center rounded-enterprise border border-slate-300 bg-white p-8">
        <p role="status" className="text-sm text-slate-600">{status}</p>
      </section>
    )
  }

  return (
    <section className="grid gap-4">
      <header className="rounded-enterprise border border-slate-300 bg-white p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <span className="text-[10px] font-black tracking-[.14em] text-enterprise-blue uppercase">
              Step 2 · T-Box Schema
            </span>
            <h2 className="mb-1 mt-2 text-xl font-black text-navy-900">Ontology Graph Builder</h2>
            <p className="m-0 max-w-3xl text-xs leading-5 text-slate-500">
              이 단계에서는 인스턴스(A-Box)가 아닌 Class, Property, Relation 구조만 설계합니다.
              Cypher 영역은 실행 입력이 아니라 서버 Typed Operation의 안전한 편집 표현입니다.
            </p>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              className="button button-secondary"
              disabled={locked || working || Boolean(editorError)}
              onClick={() => void save()}
            >
              <Save size={14} aria-hidden="true" />
              T-Box 저장
            </button>
            <button
              type="button"
              className="button"
              disabled={busy || working || locked || Boolean(editorError) || elements.length === 0}
              onClick={onContinue}
            >
              Data Enricher
            </button>
          </div>
        </div>
        <p role="status" className="mb-0 mt-3 text-xs font-semibold text-slate-600">{status}</p>
      </header>

      <div className="grid gap-3">
        {record.blocks.map((block) => (
          <article
            key={block.id}
            className={`rounded-enterprise border bg-white ${block.id === selectedBlockId ? 'border-enterprise-blue shadow-sm' : 'border-slate-300'}`}
          >
            <header className="flex flex-wrap items-center gap-3 p-3">
              <button
                type="button"
                className="flex min-w-0 flex-1 items-center gap-2 text-left"
                onClick={() => applyBlock(block, record)}
              >
                <span className="rounded bg-slate-100 px-2 py-1 text-[10px] font-black text-slate-600">
                  {block.ordinal + 1}
                </span>
                <strong className="truncate text-sm text-navy-900">{block.title}</strong>
                <span className="text-[10px] font-bold text-slate-400">{block.kind}</span>
              </button>
              <label className="flex items-center gap-2 text-xs font-bold text-slate-600">
                가중치
                <input
                  aria-label={`${block.title} 가중치`}
                  className="input w-20 py-1"
                  type="number"
                  min={0}
                  max={100}
                  defaultValue={block.weight}
                  disabled={locked || working}
                  onBlur={(event) => {
                    const weight = Number(event.currentTarget.value)
                    if (Number.isInteger(weight) && weight >= 0 && weight <= 100 && weight !== block.weight) {
                      void updateBlock(block, { weight })
                    }
                  }}
                />
              </label>
              <button
                type="button"
                className="button button-secondary px-2"
                aria-label={block.collapsed ? `${block.title} 펼치기` : `${block.title} 접기`}
                disabled={locked || working}
                onClick={() => void updateBlock(block, { collapsed: !block.collapsed })}
              >
                {block.collapsed
                  ? <ChevronDown size={14} aria-hidden="true" />
                  : <ChevronUp size={14} aria-hidden="true" />}
              </button>
            </header>
            {block.id === selectedBlockId && !block.collapsed && (
              <div className="border-t border-slate-200 p-3">
                <div className="grid min-h-[620px] gap-3 xl:grid-cols-[minmax(300px,.8fr)_minmax(460px,1.2fr)_260px]">
                  <section className="flex min-h-0 flex-col rounded-enterprise border border-slate-700 bg-[#081525]">
                    <header className="border-b border-slate-700 px-3 py-2 text-xs font-black text-slate-100">
                      SchemaCypherEditor · safe CREATE subset
                    </header>
                    <textarea
                      aria-label="T-Box Cypher 편집기"
                      className="min-h-[500px] flex-1 resize-none bg-transparent p-4 font-mono text-xs leading-6 text-cyan-100 outline-none"
                      spellCheck={false}
                      value={editorText}
                      disabled={locked || working}
                      onChange={(event) => changeEditor(event.target.value)}
                    />
                    <div
                      className={`min-h-16 border-t p-3 text-xs leading-5 ${editorError ? 'border-red-700 bg-red-950/70 text-red-100' : 'border-slate-700 text-emerald-300'}`}
                      role={editorError ? 'alert' : 'status'}
                    >
                      {editorError
                        ? `Line ${editorError.line}, Column ${editorError.column} · ${editorError.message}`
                        : 'Validation OK · 캔버스와 마지막 정상 AST가 동기화되었습니다.'}
                    </div>
                  </section>

                  <div className="relative min-h-[620px] overflow-hidden rounded-enterprise border border-slate-700 bg-[#0b1d31]">
                    <header className="absolute left-3 top-3 z-10 rounded border border-slate-600 bg-[#10253d]/95 px-3 py-2 text-xs font-black text-slate-100 shadow">
                      <span className="flex items-center gap-2">
                        <GitBranch size={14} aria-hidden="true" />
                        TBoxGraphCanvas
                      </span>
                    </header>
                    {nodes.length === 0 && (
                      <div className="pointer-events-none absolute inset-0 z-10 grid place-items-center p-8 text-center">
                        <p className="rounded border border-dashed border-slate-600 bg-[#10253d]/95 p-5 text-xs leading-5 text-slate-300">
                          왼쪽 에디터 또는 오른쪽 보드에서 첫 Class를 추가하세요.
                        </p>
                      </div>
                    )}
                    <ReactFlow
                      aria-label="T-Box 그래프 캔버스"
                      nodes={nodes}
                      edges={edges}
                      nodeTypes={schemaNodeTypes}
                      onNodesChange={onNodesChange}
                      onEdgesChange={onEdgesChange}
                      onConnect={connect}
                      onNodeClick={(_, node) => setSelectedElementId(node.id)}
                      onEdgeClick={(_, edge) => setSelectedElementId(edge.id)}
                      onPaneClick={() => setSelectedElementId('')}
                      nodesDraggable={!locked && !working}
                      nodesConnectable={!locked && !working}
                      deleteKeyCode={null}
                      fitView
                      minZoom={0.2}
                      maxZoom={2}
                      colorMode="dark"
                    >
                      <Background
                        variant={BackgroundVariant.Lines}
                        color="#27445f"
                        gap={20}
                        size={1}
                      />
                      <Controls showInteractive={!locked && !working} />
                      {nodes.length > 0 && (
                        <MiniMap
                          pannable
                          zoomable
                          nodeColor="#0ea5e9"
                          maskColor="rgba(2, 12, 27, .72)"
                        />
                      )}
                    </ReactFlow>
                  </div>

                  <aside className="rounded-enterprise border border-slate-300 bg-slate-50 p-3">
                    <h3 className="m-0 text-sm font-black text-navy-900">Schema board</h3>
                    <form className="mt-3 grid gap-2" onSubmit={addClass}>
                      <label className="text-xs font-bold text-slate-600" htmlFor="tbox-class-name">
                        Class canonical name
                      </label>
                      <input
                        id="tbox-class-name"
                        className="input"
                        value={newClassName}
                        placeholder="BusinessTerm"
                        maxLength={255}
                        disabled={locked || working}
                        onChange={(event) => setNewClassName(event.target.value)}
                      />
                      <button
                        type="submit"
                        className="button justify-center"
                        disabled={!canonicalName(newClassName) || locked || working}
                      >
                        <Plus size={14} aria-hidden="true" />
                        Class 추가
                      </button>
                    </form>

                    {selectedElement ? (
                      <div className="mt-4 grid gap-2 border-t border-slate-300 pt-4">
                        <span className="text-[10px] font-black tracking-wider text-enterprise-blue">
                          {selectedElement.kind}
                        </span>
                        {!selectedElementEditable && (
                          <p className="m-0 rounded border border-slate-300 bg-white p-2 text-[11px] leading-4 text-slate-600">
                            이전 블록에서 상속된 요소입니다. 원본 블록에서만 수정·삭제할 수 있습니다.
                          </p>
                        )}
                        <label className="text-xs font-bold text-slate-600">
                          표시 이름
                          <input
                            className="input mt-1"
                            value={selectedElement.display_name}
                            disabled={locked || working || !selectedElementEditable}
                            onChange={(event) => updateSelected({ display_name: event.target.value })}
                          />
                        </label>
                        <label className="text-xs font-bold text-slate-600">
                          정의
                          <textarea
                            className="input mt-1 min-h-20"
                            value={selectedElement.definition ?? ''}
                            disabled={locked || working || !selectedElementEditable}
                            onChange={(event) => updateSelected({
                              definition: event.target.value || undefined,
                            })}
                          />
                        </label>
                        <button
                          type="button"
                          className="button button-danger mt-1 justify-center"
                          disabled={locked || working || !selectedElementEditable}
                          onClick={deleteSelected}
                        >
                          <Trash2 size={14} aria-hidden="true" />
                          선택 요소 삭제
                        </button>
                        {selectedElement.kind === 'CLASS' && (
                          <div className="mt-2 border-t border-slate-300 pt-3">
                            <strong className="text-xs text-navy-900">Properties</strong>
                            <div className="mt-2 flex gap-1">
                              <input
                                aria-label="새 Property 이름"
                                className="input min-w-0 flex-1 py-1"
                                value={newPropertyName}
                                placeholder="description"
                                disabled={locked || working}
                                onChange={(event) => setNewPropertyName(event.target.value)}
                              />
                              <button
                                type="button"
                                className="button px-2"
                                aria-label="Property 추가"
                                disabled={!canonicalName(newPropertyName) || locked || working}
                                onClick={addProperty}
                              >
                                <Plus size={13} aria-hidden="true" />
                              </button>
                            </div>
                            {properties.length === 0
                              ? <p className="text-[11px] text-slate-500">등록된 속성이 없습니다.</p>
                              : properties.map((item) => (
                                <button
                                  key={item.stable_element_id}
                                  type="button"
                                  className="mt-2 block w-full rounded border border-slate-200 bg-white p-2 text-left text-xs hover:border-enterprise-blue"
                                  disabled={working}
                                  onClick={() => setSelectedElementId(item.stable_element_id)}
                                >
                                  <strong>{item.display_name}</strong>
                                  {item.vector_index_enabled && (
                                    <span className="ml-2 rounded bg-violet-100 px-1.5 py-0.5 text-[9px] font-black text-violet-800">
                                      VECTOR
                                    </span>
                                  )}
                                </button>
                              ))}
                          </div>
                        )}
                        {selectedElement.kind === 'PROPERTY' && (
                          <>
                            <label className="text-xs font-bold text-slate-600">
                              데이터 타입
                              <select
                                className="input mt-1"
                                value={selectedElement.data_type ?? 'STRING'}
                                disabled={locked || working || !selectedElementEditable}
                                onChange={(event) => updateSelected({
                                  data_type: event.target.value,
                                  vector_index_enabled: (
                                    event.target.value === 'STRING'
                                    || event.target.value === 'TEXT'
                                  ) ? selectedElement.vector_index_enabled : false,
                                })}
                              >
                                <option value="STRING">STRING</option>
                                <option value="TEXT">TEXT</option>
                                <option value="INTEGER">INTEGER</option>
                                <option value="FLOAT">FLOAT</option>
                                <option value="BOOLEAN">BOOLEAN</option>
                                <option value="DATE">DATE</option>
                              </select>
                            </label>
                            <label className="flex items-center gap-2 text-xs font-bold text-slate-700">
                              <input
                                type="checkbox"
                                checked={selectedElement.vector_index_enabled}
                                disabled={
                                  locked
                                  || working
                                  || !selectedElementEditable
                                  || !['STRING', 'TEXT'].includes(selectedElement.data_type ?? '')
                                }
                                onChange={(event) => updateSelected({
                                  vector_index_enabled: event.target.checked,
                                })}
                              />
                              GraphRAG Vector Index 대상
                            </label>
                            <label className="text-xs font-bold text-slate-600">
                              단위
                              <input
                                className="input mt-1"
                                value={selectedElement.unit ?? ''}
                                disabled={locked || working || !selectedElementEditable}
                                onChange={(event) => updateSelected({
                                  unit: event.target.value || undefined,
                                })}
                              />
                            </label>
                          </>
                        )}
                        <label className="text-xs font-bold text-slate-600">
                          동의어
                          <input
                            className="input mt-1"
                            value={selectedElement.aliases.join(', ')}
                            placeholder="한글명, 약어, synonym"
                            disabled={locked || working || !selectedElementEditable}
                            onChange={(event) => updateSelected({
                              aliases: aliasesFromInput(event.target.value),
                            })}
                          />
                        </label>
                      </div>
                    ) : (
                      <p className="mt-4 text-xs leading-5 text-slate-500">
                        노드 또는 관계를 선택하면 의미, 동의어, 단위, Vector Index 정책을
                        편집할 수 있습니다.
                      </p>
                    )}
                  </aside>
                </div>
              </div>
            )}
          </article>
        ))}
      </div>

      <div className="relative">
        <button
          type="button"
          className="button button-secondary w-full justify-center border-dashed py-3"
          disabled={locked || working}
          onClick={() => setShowBlockMenu((value) => !value)}
        >
          <Plus size={15} aria-hidden="true" />
          블록 추가
        </button>
        {showBlockMenu && (
          <div className="mt-2 grid gap-2 rounded-enterprise border border-slate-300 bg-white p-3 shadow-lg md:grid-cols-2 xl:grid-cols-4">
            {blockOptions.map((option) => {
              const Icon = option.icon
              return (
                <button
                  key={option.kind}
                  type="button"
                  className="rounded-enterprise border border-slate-200 p-3 text-left hover:border-enterprise-blue hover:bg-blue-50"
                  onClick={() => void createBlock(option)}
                >
                  <Icon size={16} className="text-enterprise-blue" aria-hidden="true" />
                  <strong className="mt-2 block text-xs text-navy-900">{option.title}</strong>
                  <span className="mt-1 block text-[11px] leading-4 text-slate-500">
                    {option.description}
                  </span>
                </button>
              )
            })}
          </div>
        )}
      </div>

      <section className="rounded-enterprise border border-violet-200 bg-violet-50 p-4">
        <div className="flex items-start gap-3">
          <Bot className="mt-0.5 text-violet-700" size={18} aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <h3 className="m-0 text-sm font-black text-violet-950">LLM Schema Assistant</h3>
            <p className="mb-3 mt-1 text-xs leading-5 text-violet-800">
              모델 출력은 Proposal로만 저장됩니다. 기본 병합 정책은 기존 사용자 정의 우선
              (Keep Original)이며, 충돌 시 선택 팝업을 표시합니다.
            </p>
            <textarea
              aria-label="LLM T-Box 요청"
              className="input min-h-24 w-full bg-white"
              maxLength={4000}
              value={assistantPrompt}
              disabled={locked || working}
              placeholder="예: 데이터 카탈로그의 Dataset, Owner, Domain 관계와 검색용 설명 속성을 설계해 줘."
              onChange={(event) => setAssistantPrompt(event.target.value)}
            />
            <div className="mt-2 flex flex-wrap gap-2">
              <button
                type="button"
                className="button"
                disabled={!assistantPrompt.trim() || locked || working || !selectedBlock}
                onClick={() => void requestProposal('MERGE_INTO_CURRENT')}
              >
                현재 그래프에 적용/병합
              </button>
              <button
                type="button"
                className="button button-secondary"
                disabled={!assistantPrompt.trim() || locked || working}
                onClick={() => void requestProposal('APPEND_LAYER')}
              >
                추가 그래프로 분리 생성
              </button>
            </div>
          </div>
        </div>
      </section>

      <Dialog
        open={conflictOpen && Boolean(proposal)}
        title="T-Box 병합 충돌 해결"
        description="기본값은 기존 사용자 정의 우선(Keep Original)입니다."
        onRequestClose={() => {
          if (!working) setConflictOpen(false)
        }}
        footer={<>
          <button
            type="button"
            className="button button-secondary"
            disabled={working || !proposal}
            onClick={() => {
              if (proposal) void applyProposal(proposal, 'KEEP_ORIGINAL')
            }}
          >
            모두 기존 값 유지
          </button>
          <button
            type="button"
            className="button"
            disabled={working || !proposal}
            onClick={() => {
              if (proposal) void applyProposal(proposal, 'RESOLVE')
            }}
          >
            선택한 전략으로 병합
          </button>
        </>}
      >
        <div className="grid max-h-[55vh] gap-3 overflow-auto">
          {proposal?.conflicts.map((conflict) => (
            <article key={conflict.conflict_id} className="rounded-enterprise border border-amber-200 bg-amber-50 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <strong className="text-xs text-amber-950">{conflict.stable_element_id}</strong>
                  <span className="ml-2 rounded bg-amber-200 px-2 py-0.5 text-[9px] font-black text-amber-900">
                    {conflict.kind}
                  </span>
                </div>
                <select
                  aria-label={`${conflict.stable_element_id} 충돌 전략`}
                  className="input w-auto py-1 text-xs"
                  value={conflictActions[conflict.conflict_id] ?? 'KEEP_ORIGINAL'}
                  onChange={(event) => setConflictActions((current) => ({
                    ...current,
                    [conflict.conflict_id]: event.target.value as 'KEEP_ORIGINAL' | 'ACCEPT_PROPOSAL',
                  }))}
                >
                  <option value="KEEP_ORIGINAL">기존 값 유지</option>
                  <option value="ACCEPT_PROPOSAL">제안으로 덮어쓰기</option>
                </select>
              </div>
              <div className="mt-2 grid gap-2 text-[10px] md:grid-cols-2">
                <pre className="m-0 overflow-auto rounded bg-white p-2 text-slate-600">
                  {JSON.stringify(conflict.original_value, null, 2)}
                </pre>
                <pre className="m-0 overflow-auto rounded bg-violet-100 p-2 text-violet-900">
                  {JSON.stringify(conflict.proposed_value, null, 2)}
                </pre>
              </div>
            </article>
          ))}
        </div>
      </Dialog>
    </section>
  )
}
