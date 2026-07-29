import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type ReactNode,
} from 'react'
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  NodeToolbar,
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
  FolderTree,
  GitBranch,
  Layers3,
  LockKeyhole,
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
  deleteKnowledgeStudioTBoxBlock,
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

interface SchemaNodeData extends Record<string, unknown> {
  label: string
  ordinal: number
  editable: boolean
  locked: boolean
  selected: boolean
  blockLabel: string
  properties: Array<{ id: string; label: string }>
  onRename: (value: string) => void
  onDelete: () => void
  onAddProperty: (value: string) => void
}

type SchemaNode = Node<SchemaNodeData, 'schemaClass'>
interface LayerGroupData extends Record<string, unknown> {
  label: string
  later: boolean
}
type LayerGroupNode = Node<LayerGroupData, 'layerGroup'>
type CanvasNode = SchemaNode | LayerGroupNode
type SchemaEdge = Edge<{ relation: string; hierarchy?: boolean; editable: boolean }>

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
  const [propertyName, setPropertyName] = useState('')
  const [displayName, setDisplayName] = useState(data.label)

  useEffect(() => setDisplayName(data.label), [data.label])

  return (
    <div className={`relative w-[156px] rounded-md border bg-[#10253d] px-3 py-2 text-[11px] font-extrabold text-slate-50 shadow-lg ${
      selected || data.selected ? 'border-amber-300 ring-2 ring-amber-300/40' : 'border-sky-400'
    }`}>
      <span className="absolute -left-2 -top-2 rounded-full border border-sky-200 bg-sky-500 px-2 py-0.5 text-[9px] font-black text-white shadow">
        No. {data.ordinal}
      </span>
      {data.locked && (
        <span
          className="absolute -right-2 -top-2 rounded-full border border-amber-200 bg-amber-500 p-1 text-white"
          title="후속 블록에서 참조 중"
        >
          <LockKeyhole size={9} aria-hidden="true" />
        </span>
      )}
      <span className="block truncate pt-1">{data.label}</span>
      <span className="mt-0.5 block truncate text-[8px] font-semibold text-sky-200">
        {data.blockLabel}
      </span>
      {(selected || data.selected) && (
        <div className="mt-2 border-t border-slate-600 pt-1.5">
          {data.properties.length === 0 ? (
            <span className="block text-[8px] font-medium text-slate-400">Properties 없음</span>
          ) : data.properties.slice(0, 4).map((property) => (
            <span key={property.id} className="block truncate text-[8px] font-medium text-cyan-100">
              · {property.label}
            </span>
          ))}
          {data.properties.length > 4 && (
            <span className="block text-[8px] text-slate-400">
              +{data.properties.length - 4}
            </span>
          )}
        </div>
      )}
      <Handle type="target" position={Position.Left} className="border-sky-200! bg-sky-500!" />
      <Handle type="source" position={Position.Right} className="border-sky-200! bg-sky-500!" />
      <NodeToolbar
        isVisible={selected || data.selected}
        position={Position.Right}
        offset={12}
        className="w-[230px] rounded-enterprise border border-slate-300 bg-white p-3 text-slate-800 shadow-2xl"
      >
        <div
          className="grid gap-2"
          role="dialog"
          aria-label={`${data.label} Class 빠른 편집`}
          onPointerDown={(event) => event.stopPropagation()}
        >
          <div className="flex items-center justify-between gap-2">
            <strong className="truncate text-xs text-navy-900">Class 빠른 편집</strong>
            {data.locked && (
              <span className="flex items-center gap-1 rounded bg-amber-100 px-2 py-1 text-[9px] font-black text-amber-800">
                <LockKeyhole size={10} aria-hidden="true" />
                LOCKED
              </span>
            )}
          </div>
          <label className="text-[10px] font-bold text-slate-600">
            표시 이름
            <input
              className="input mt-1 py-1 text-xs"
              value={displayName}
              disabled={!data.editable}
              onChange={(event) => setDisplayName(event.target.value)}
              onBlur={() => {
                const value = displayName.trim()
                if (value && value !== data.label) data.onRename(value)
              }}
            />
          </label>
          <div className="rounded border border-slate-200 bg-slate-50 p-2">
            <strong className="text-[10px] text-slate-700">Properties</strong>
            {data.properties.length === 0 ? (
              <p className="mb-2 mt-1 text-[9px] text-slate-500">등록된 Property가 없습니다.</p>
            ) : (
              <ul className="mb-2 mt-1 max-h-24 overflow-auto pl-4 text-[9px] text-slate-600">
                {data.properties.map((property) => (
                  <li key={property.id}>{property.label}</li>
                ))}
              </ul>
            )}
            <div className="flex gap-1">
              <input
                aria-label={`${data.label} 새 Property 이름`}
                className="input min-w-0 flex-1 py-1 text-[10px]"
                value={propertyName}
                placeholder="description"
                disabled={!data.editable}
                onChange={(event) => setPropertyName(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault()
                    const value = canonicalName(propertyName)
                    if (value) {
                      data.onAddProperty(value)
                      setPropertyName('')
                    }
                  }
                }}
              />
              <button
                type="button"
                className="button px-2 py-1"
                aria-label={`${data.label} Property 추가`}
                disabled={!data.editable || !canonicalName(propertyName)}
                onClick={() => {
                  const value = canonicalName(propertyName)
                  if (!value) return
                  data.onAddProperty(value)
                  setPropertyName('')
                }}
              >
                <Plus size={11} aria-hidden="true" />
              </button>
            </div>
          </div>
          <button
            type="button"
            className="button button-danger justify-center py-1.5 text-[10px]"
            disabled={!data.editable}
            onClick={data.onDelete}
          >
            <Trash2 size={11} aria-hidden="true" />
            Class 삭제
          </button>
        </div>
      </NodeToolbar>
    </div>
  )
}

function LayerGroup({ data }: NodeProps<LayerGroupNode>) {
  return (
    <div className={`h-full w-full rounded-xl border-2 border-dashed ${
      data.later
        ? 'border-violet-400/60 bg-violet-950/15'
        : 'border-slate-400/50 bg-slate-800/20'
    }`}>
      <span className="absolute left-3 top-2 rounded bg-slate-950/80 px-2 py-1 text-[9px] font-black text-slate-200">
        {data.label}
      </span>
    </div>
  )
}

const schemaNodeTypes = {
  schemaClass: SchemaClassNode,
  layerGroup: LayerGroup,
}

interface ClassHierarchyTreeProps {
  classes: KnowledgeStudioTBoxElement[]
  selectedId: string
  activeBlockId: string
  allowedParentIds: ReadonlySet<string>
  disabled: boolean
  onSelect: (id: string) => void
  onAdd: (name: string, parentId?: string) => void
  onReparent: (id: string, parentId?: string) => void
}

function ClassHierarchyTree({
  classes,
  selectedId,
  activeBlockId,
  allowedParentIds,
  disabled,
  onSelect,
  onAdd,
  onReparent,
}: ClassHierarchyTreeProps) {
  const [newClassName, setNewClassName] = useState('')
  const [parentForNewClass, setParentForNewClass] = useState<string>()
  const draggedId = useRef('')
  const newClassInput = useRef<HTMLInputElement>(null)
  const classById = useMemo(
    () => new Map(classes.map((item) => [item.stable_element_id, item])),
    [classes],
  )
  const childrenByParent = useMemo(() => {
    const result = new Map<string, KnowledgeStudioTBoxElement[]>()
    for (const item of classes) {
      const parent = item.parent_stable_element_id
      const key = parent && classById.has(parent) ? parent : ''
      result.set(key, [...(result.get(key) ?? []), item])
    }
    for (const children of result.values()) {
      children.sort((left, right) => left.ordinal - right.ordinal)
    }
    return result
  }, [classById, classes])

  const createsCycle = (classId: string, parentId: string): boolean => {
    let cursor: string | undefined = parentId
    const visited = new Set<string>()
    while (cursor) {
      if (cursor === classId || visited.has(cursor)) return true
      visited.add(cursor)
      cursor = classById.get(cursor)?.parent_stable_element_id
    }
    return false
  }

  const drop = (event: DragEvent<HTMLElement>, parentId?: string) => {
    event.preventDefault()
    const classId = draggedId.current
    draggedId.current = ''
    if (
      !classId
      || disabled
      || (parentId && (!allowedParentIds.has(parentId) || createsCycle(classId, parentId)))
    ) return
    onReparent(classId, parentId)
  }

  const renderBranch = (parentId = '', depth = 0): ReactNode => (
    (childrenByParent.get(parentId) ?? []).map((item) => {
      const editable = item.block_id === activeBlockId && !item.locked_by_later_block
      const children = childrenByParent.get(item.stable_element_id) ?? []
      return (
        <li key={item.stable_element_id}>
          <div
            className={`group flex items-center gap-1 rounded px-1 py-1 ${
              selectedId === item.stable_element_id
                ? 'bg-blue-100 text-blue-950'
                : 'text-slate-700 hover:bg-slate-100'
            }`}
            style={{ marginLeft: depth * 12 }}
            draggable={editable && !disabled}
            onDragStart={() => {
              draggedId.current = item.stable_element_id
            }}
            onDragOver={(event) => {
              if (allowedParentIds.has(item.stable_element_id)) event.preventDefault()
            }}
            onDrop={(event) => drop(event, item.stable_element_id)}
          >
            <button
              type="button"
              className="min-w-0 flex-1 truncate text-left text-[11px] font-bold"
              onClick={() => onSelect(item.stable_element_id)}
            >
              {children.length > 0 ? '▾ ' : '· '}
              {item.display_name}
            </button>
            {item.locked_by_later_block && (
              <LockKeyhole
                size={10}
                className="shrink-0 text-amber-600"
                aria-label={`${item.display_name} 후속 블록 참조 잠금`}
              />
            )}
            {allowedParentIds.has(item.stable_element_id) && (
              <button
                type="button"
                className="rounded p-1 opacity-0 hover:bg-blue-100 group-hover:opacity-100 focus:opacity-100"
                aria-label={`${item.display_name} 하위 Class 추가`}
                disabled={disabled}
                onClick={() => {
                  setParentForNewClass(item.stable_element_id)
                  newClassInput.current?.focus()
                }}
              >
                <Plus size={10} aria-hidden="true" />
              </button>
            )}
          </div>
          {children.length > 0 && <ul className="m-0 list-none p-0">
            {renderBranch(item.stable_element_id, depth + 1)}
          </ul>}
        </li>
      )
    })
  )

  return (
    <aside className="flex min-h-[500px] flex-col rounded-enterprise border border-slate-300 bg-white">
      <header className="flex items-center gap-2 border-b border-slate-200 px-3 py-2">
        <FolderTree size={14} className="text-enterprise-blue" aria-hidden="true" />
        <strong className="text-xs text-navy-900">Class Hierarchy</strong>
      </header>
      <form
        className="flex gap-1 border-b border-slate-200 p-2"
        onSubmit={(event) => {
          event.preventDefault()
          const name = canonicalName(newClassName)
          if (!name) return
          onAdd(name, parentForNewClass)
          setNewClassName('')
          setParentForNewClass(undefined)
        }}
      >
        <input
          ref={newClassInput}
          aria-label={parentForNewClass ? '하위 Class 이름' : '최상위 Class 이름'}
          className="input min-w-0 flex-1 py-1 text-[11px]"
          value={newClassName}
          placeholder={parentForNewClass
            ? `${classById.get(parentForNewClass)?.display_name ?? ''} 하위 Class`
            : '최상위 Class'}
          disabled={disabled}
          onChange={(event) => setNewClassName(event.target.value)}
        />
        {parentForNewClass && (
          <button
            type="button"
            className="rounded px-1 text-[10px] text-slate-500 hover:bg-slate-100"
            aria-label="하위 Class 추가 취소"
            onClick={() => setParentForNewClass(undefined)}
          >
            ×
          </button>
        )}
        <button
          type="submit"
          className="button px-2 py-1"
          aria-label={parentForNewClass ? '하위 Class 추가' : '최상위 Class 추가'}
          disabled={disabled || !canonicalName(newClassName)}
        >
          <Plus size={12} aria-hidden="true" />
        </button>
      </form>
      <div
        className="min-h-0 flex-1 overflow-auto p-2"
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => drop(event)}
      >
        {classes.length === 0 ? (
          <p className="p-3 text-center text-[11px] leading-5 text-slate-500">
            (+)로 첫 Class를 추가하세요.
          </p>
        ) : (
          <ul className="m-0 list-none p-0" aria-label="T-Box Class 계층">
            {renderBranch()}
          </ul>
        )}
      </div>
      <p className="m-0 border-t border-slate-200 p-2 text-[9px] leading-4 text-slate-500">
        Class를 드래그해 다른 Class에 놓으면 subClassOf 계층이 형성됩니다.
      </p>
    </aside>
  )
}

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
  const hierarchyEdges = classes.flatMap((item): SafeCypherEdge[] => {
    const parent = item.parent_stable_element_id
    if (!parent || !aliasById.has(parent)) return []
    return [{
      id: `hierarchy:${item.stable_element_id}`,
      source: item.stable_element_id,
      target: parent,
      relation: 'SUBCLASS_OF',
      sourceAlias: aliasById.get(item.stable_element_id),
      targetAlias: aliasById.get(parent),
    }]
  })
  const relationEdges = elements
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
  return { nodes, edges: [...hierarchyEdges, ...relationEdges] }
}

function effectiveElements(record: KnowledgeStudioTBox): KnowledgeStudioTBoxElement[] {
  return [...record.blocks]
    .sort((left, right) => left.weight - right.weight || left.ordinal - right.ordinal)
    .flatMap((block) => block.elements.map((item) => ({
      ...item,
      block_id: item.block_id ?? block.id,
      aliases: item.aliases ?? [],
      vector_index_enabled: item.vector_index_enabled ?? false,
      locked_by_later_block: item.locked_by_later_block ?? false,
    })))
}

function flowGraph(
  elements: KnowledgeStudioTBoxElement[],
  editableBlockId: string,
  blocks: KnowledgeStudioTBoxBlock[],
  selectedElementId: string,
): {
  nodes: CanvasNode[]
  edges: SchemaEdge[]
} {
  const blockById = new Map(blocks.map((block) => [block.id, block]))
  const activeOrdinal = blockById.get(editableBlockId)?.ordinal ?? 0
  const classes = elements.filter((item) => item.kind === 'CLASS')
  const classPositions = new Map(classes.map((item, index) => [
    item.stable_element_id,
    {
      x: item.layout_x ?? 70 + (index % 3) * 220,
      y: item.layout_y ?? 90 + Math.floor(index / 3) * 150,
    },
  ]))
  const groupNodes: LayerGroupNode[] = blocks
    .filter((block) => block.id !== editableBlockId)
    .flatMap((block): LayerGroupNode[] => {
      const blockClasses = classes.filter((item) => item.block_id === block.id)
      if (blockClasses.length === 0) return []
      const positions = blockClasses.map((item) => classPositions.get(item.stable_element_id)!)
      const minX = Math.min(...positions.map((position) => position.x)) - 28
      const minY = Math.min(...positions.map((position) => position.y)) - 38
      const maxX = Math.max(...positions.map((position) => position.x)) + 184
      const maxY = Math.max(...positions.map((position) => position.y)) + 112
      return [{
        id: `group:${block.id}`,
        type: 'layerGroup',
        position: { x: minX, y: minY },
        data: {
          label: `${block.ordinal + 1}. ${block.title} · 읽기 전용`,
          later: block.ordinal > activeOrdinal,
        },
        style: { width: maxX - minX, height: maxY - minY },
        draggable: false,
        selectable: false,
        connectable: false,
        focusable: false,
        zIndex: -1,
        ariaLabel: `${block.title} 읽기 전용 그룹`,
      }]
    })
  const classNodes = classes.map((item): SchemaNode => {
    const editable = (
      (item.block_id === editableBlockId || item.block_id === undefined)
      && !item.locked_by_later_block
    )
    const block = item.block_id ? blockById.get(item.block_id) : undefined
    return {
    id: item.stable_element_id,
    type: 'schemaClass',
    position: classPositions.get(item.stable_element_id)!,
    data: {
      label: item.display_name,
      ordinal: item.ordinal + 1,
      editable,
      locked: item.locked_by_later_block,
      selected: item.stable_element_id === selectedElementId,
      blockLabel: block?.title ?? '현재 블록',
      properties: elements
        .filter(
          (property) => property.kind === 'PROPERTY'
            && property.parent_stable_element_id === item.stable_element_id,
        )
        .map((property) => ({
          id: property.stable_element_id,
          label: property.display_name,
        })),
      onRename: () => undefined,
      onDelete: () => undefined,
      onAddProperty: () => undefined,
    },
    draggable: editable,
    connectable: true,
    ariaLabel: `No. ${item.ordinal + 1}, ${item.display_name} 클래스`,
  }})
  const relationshipEdges = elements
    .filter((item) => item.kind === 'RELATION')
    .flatMap((item): SchemaEdge[] => {
      if (!item.source_stable_element_id || !item.target_stable_element_id) return []
      return [{
        id: item.stable_element_id,
        source: item.source_stable_element_id,
        target: item.target_stable_element_id,
        label: item.display_name,
        data: {
          relation: item.canonical_name,
          editable: item.block_id === editableBlockId,
        },
        markerEnd: { type: MarkerType.ArrowClosed, color: '#7dd3fc' },
        style: { stroke: '#7dd3fc', strokeWidth: 1.6 },
        labelStyle: { fill: '#e2e8f0', fontWeight: 700 },
      }]
    })
  const hierarchyEdges = classes.flatMap((item): SchemaEdge[] => {
    const parent = item.parent_stable_element_id
    if (!parent || !classPositions.has(parent)) return []
    return [{
      id: `hierarchy:${item.stable_element_id}`,
      source: item.stable_element_id,
      target: parent,
      label: 'subClassOf',
      data: {
        relation: 'SUBCLASS_OF',
        hierarchy: true,
        editable: item.block_id === editableBlockId && !item.locked_by_later_block,
      },
      markerEnd: { type: MarkerType.ArrowClosed, color: '#34d399' },
      style: { stroke: '#34d399', strokeWidth: 1.5, strokeDasharray: '6 4' },
      labelStyle: { fill: '#a7f3d0', fontWeight: 800 },
    }]
  })
  return {
    nodes: [...groupNodes, ...classNodes],
    edges: [...hierarchyEdges, ...relationshipEdges],
  }
}

function elementPayload(
  item: KnowledgeStudioTBoxElement,
): Omit<
  KnowledgeStudioTBoxElement,
  'ordinal' | 'version' | 'block_id' | 'locked_by_later_block'
> {
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
    metadata_reference_id: item.metadata_reference_id,
    metadata_reference_urn: item.metadata_reference_urn,
    layout_x: item.layout_x,
    layout_y: item.layout_y,
  }
}

function createdClass(
  label: string,
  position: { x: number; y: number },
  ordinal: number,
  parentId?: string,
): KnowledgeStudioTBoxElement {
  const id = `class:${crypto.randomUUID()}`
  return {
    stable_element_id: id,
    kind: 'CLASS',
    canonical_name: label,
    display_name: label,
    parent_stable_element_id: parentId,
    ordinal,
    version: 1,
    aliases: [],
    vector_index_enabled: false,
    locked_by_later_block: false,
    layout_x: position.x,
    layout_y: position.y,
  }
}

function canonicalName(value: string): string {
  const cleaned = value.trim().replace(/[^A-Za-z0-9_]/g, '_')
  if (!cleaned) return ''
  return /^[A-Za-z]/.test(cleaned) ? cleaned : `Class_${cleaned}`
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
  const [nodes, setNodes, onNodesChange] = useNodesState<CanvasNode>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<SchemaEdge>([])
  const [editorText, setEditorText] = useState('')
  const [editorError, setEditorError] = useState<{
    message: string
    line: number
    column: number
  }>()
  const [selectedElementId, setSelectedElementId] = useState('')
  const [status, setStatus] = useState('T-Box 정본을 불러오는 중입니다.')
  const [working, setWorking] = useState(false)
  const [showBlockMenu, setShowBlockMenu] = useState(false)
  const [assistantPrompt, setAssistantPrompt] = useState('')
  const [proposal, setProposal] = useState<KnowledgeStudioTBoxProposal>()
  const [conflictOpen, setConflictOpen] = useState(false)
  const [blockPendingDelete, setBlockPendingDelete] = useState<KnowledgeStudioTBoxBlock>()
  const [conflictActions, setConflictActions] = useState<Record<string, 'KEEP_ORIGINAL' | 'ACCEPT_PROPOSAL'>>({})
  const locked = lifecycleState !== 'DRAFT'

  const selectedBlock = record?.blocks.find((item) => item.id === selectedBlockId)
  const lastBlockId = record?.blocks.at(-1)?.id

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
    const graph = flowGraph(nextElements, block.id, source.blocks, '')
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
    const graph = flowGraph(next, selectedBlockId, record?.blocks ?? [], selectedElementId)
    const safe = asSafeGraph(next)
    setElements(next)
    setNodes(graph.nodes)
    setEdges(graph.edges)
    setEditorText(formatSafeCypherDraft(safe.nodes, safe.edges))
    setEditorError(undefined)
  }, [record?.blocks, selectedBlockId, selectedElementId, setEdges, setNodes])

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
    const hierarchyParentByClass = new Map<string, string>()
    for (const edge of parsed.edges) {
      if (edge.relation !== 'SUBCLASS_OF') continue
      if (edge.source === edge.target || hierarchyParentByClass.has(edge.source)) {
        setEditorError({
          message: 'Class hierarchy는 Class당 하나의 부모만 가지며 순환할 수 없습니다.',
          line: 1,
          column: 1,
        })
        return
      }
      hierarchyParentByClass.set(edge.source, edge.target)
    }
    for (const classId of hierarchyParentByClass.keys()) {
      const visited = new Set<string>()
      let cursor: string | undefined = classId
      while (cursor) {
        if (visited.has(cursor)) {
          setEditorError({
            message: 'Class hierarchy에는 순환 subClassOf 관계를 만들 수 없습니다.',
            line: 1,
            column: 1,
          })
          return
        }
        visited.add(cursor)
        cursor = hierarchyParentByClass.get(cursor)
      }
    }
    const inheritedChanged = inherited.some((item) => {
      if (item.kind === 'CLASS') {
        return (
          parsedNodes.get(item.stable_element_id)?.label !== item.canonical_name
          || hierarchyParentByClass.get(item.stable_element_id)
            !== item.parent_stable_element_id
        )
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
        parent_stable_element_id: hierarchyParentByClass.get(item.id),
        definition: prior?.definition,
        aliases: prior?.aliases ?? [],
        vector_index_enabled: false,
        metadata_reference_id: prior?.metadata_reference_id,
        metadata_reference_urn: prior?.metadata_reference_urn,
        locked_by_later_block: prior?.locked_by_later_block ?? false,
        block_id: prior?.block_id,
        layout_x: node?.position.x ?? 70 + (index % 3) * 220,
        layout_y: node?.position.y ?? 90 + Math.floor(index / 3) * 150,
        ordinal: prior?.ordinal ?? nextOrdinal++,
        version: prior?.version ?? 1,
      }
    })
    const nextProperties = elements.filter(
      (item) => item.kind === 'PROPERTY'
        && Boolean(item.parent_stable_element_id && classIds.has(item.parent_stable_element_id)),
    )
    const nextRelations = parsed.edges
      .filter((item) => item.relation !== 'SUBCLASS_OF')
      .map((item): KnowledgeStudioTBoxElement => {
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
        metadata_reference_id: prior?.metadata_reference_id,
        metadata_reference_urn: prior?.metadata_reference_urn,
        locked_by_later_block: prior?.locked_by_later_block ?? false,
        block_id: prior?.block_id,
        ordinal: prior?.ordinal ?? nextOrdinal++,
        version: prior?.version ?? 1,
      }
    })
    const next = [...nextClasses, ...nextProperties, ...nextRelations]
    const graph = flowGraph(next, selectedBlockId, record?.blocks ?? [], selectedElementId)
    setElements(next)
    setNodes(graph.nodes)
    setEdges(graph.edges)
    setEditorError(undefined)
  }

  const addClass = (rawName: string, parentId?: string) => {
    const name = canonicalName(rawName)
    if (!name || locked || working) return
    if (elements.some(
      (item) => item.kind === 'CLASS' && item.canonical_name.toLowerCase() === name.toLowerCase(),
    )) {
      setStatus(`Class '${name}'은(는) 이미 존재합니다.`)
      return
    }
    const classCount = elements.filter((item) => item.kind === 'CLASS').length
    const item = createdClass(name, {
      x: 80 + (classCount % 3) * 220,
      y: 100 + Math.floor(classCount / 3) * 150,
    }, Math.max(-1, ...elements.map((element) => element.ordinal)) + 1, parentId)
    syncCanvasAndEditor([...elements, item])
    setSelectedElementId(item.stable_element_id)
  }

  const connect = useCallback((connection: Connection) => {
    if (locked || !connection.source || !connection.target || !selectedBlock) return
    const blockOrdinalById = new Map(
      (record?.blocks ?? []).map((block) => [block.id, block.ordinal]),
    )
    const endpointIsAvailable = [connection.source, connection.target].every((id) => {
      const endpoint = elements.find((item) => item.stable_element_id === id)
      if (!endpoint || endpoint.kind !== 'CLASS') return false
      const ordinal = endpoint.block_id
        ? blockOrdinalById.get(endpoint.block_id)
        : selectedBlock.ordinal
      return ordinal !== undefined && ordinal <= selectedBlock.ordinal
    })
    if (!endpointIsAvailable) {
      setStatus('현재 블록은 자신의 Class 또는 이전 블록의 Class에만 연결할 수 있습니다.')
      return
    }
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
      locked_by_later_block: false,
      ordinal: Math.max(-1, ...elements.map((item) => item.ordinal)) + 1,
      version: 1,
    }
    const next = [...elements, relation]
    setElements(next)
    setEdges((current) => addEdge({
      ...connection,
      id: stableId,
      label: 'RELATED_TO',
      data: { relation: 'RELATED_TO', editable: true },
      markerEnd: { type: MarkerType.ArrowClosed, color: '#7dd3fc' },
      style: { stroke: '#7dd3fc', strokeWidth: 1.6 },
    }, current))
    const safe = asSafeGraph(next)
    setEditorText(formatSafeCypherDraft(safe.nodes, safe.edges))
    setEditorError(undefined)
  }, [elements, locked, record?.blocks, selectedBlock, setEdges])

  const deleteElement = (elementId: string) => {
    const target = elements.find((item) => item.stable_element_id === elementId)
    const editable = target
      && (target.block_id === selectedBlockId || target.block_id === undefined)
      && !target.locked_by_later_block
    if (!target || !editable || locked || working) return
    const externalDependants = elements.filter((item) => (
      item.block_id !== undefined
      && item.block_id !== selectedBlockId
      && (
        item.parent_stable_element_id === target.stable_element_id
        || item.source_stable_element_id === target.stable_element_id
        || item.target_stable_element_id === target.stable_element_id
      )
    ))
    if (externalDependants.length > 0) {
      setStatus(
        '후속 블록이 참조하는 Class입니다. 참조 블록을 먼저 정리해야 합니다.',
      )
      return
    }
    const removed = new Set([target.stable_element_id])
    if (target.kind === 'CLASS') {
      for (const item of elements) {
        if (
          (item.block_id === selectedBlockId || item.block_id === undefined)
          && (
            item.parent_stable_element_id === target.stable_element_id
            || item.source_stable_element_id === target.stable_element_id
            || item.target_stable_element_id === target.stable_element_id
          )
        ) removed.add(item.stable_element_id)
      }
    }
    syncCanvasAndEditor(elements.filter((item) => !removed.has(item.stable_element_id)))
    setSelectedElementId('')
  }

  const addProperty = (classId: string, rawName: string) => {
    const classElement = elements.find((item) => item.stable_element_id === classId)
    if (
      classElement?.kind !== 'CLASS'
      || (
        classElement.block_id !== selectedBlockId
        && classElement.block_id !== undefined
      )
      || classElement.locked_by_later_block
      || locked
      || working
    ) return
    const name = canonicalName(rawName)
    if (!name) return
    if (elements.some(
      (item) => item.kind === 'PROPERTY'
        && item.parent_stable_element_id === classId
        && item.canonical_name.toLowerCase() === name.toLowerCase(),
    )) {
      setStatus(`Property '${name}'은(는) 이미 존재합니다.`)
      return
    }
    const property: KnowledgeStudioTBoxElement = {
      stable_element_id: `property:${crypto.randomUUID()}`,
      kind: 'PROPERTY',
      canonical_name: name,
      display_name: name,
      parent_stable_element_id: classId,
      data_type: 'STRING',
      nullable: true,
      aliases: [],
      vector_index_enabled: false,
      locked_by_later_block: false,
      ordinal: Math.max(-1, ...elements.map((item) => item.ordinal)) + 1,
      version: 1,
    }
    syncCanvasAndEditor([...elements, property])
    setSelectedElementId(classId)
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
    values: { title?: string; weight?: number; collapsed?: boolean },
  ) => {
    if (locked || working) return
    setWorking(true)
    try {
      const response = await updateKnowledgeStudioTBoxBlock(
        client,
        draftId,
        block.id,
        {
          title: values.title ?? block.title,
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

  const deleteBlock = async (block: KnowledgeStudioTBoxBlock) => {
    if (locked || working || block.id !== lastBlockId) return
    setWorking(true)
    try {
      const response = await deleteKnowledgeStudioTBoxBlock(
        client,
        draftId,
        block.id,
        responseEtag,
        newKnowledgeStudioIdempotencyKey(),
      )
      if (!response.etag) return
      applyResponse(
        response.data,
        response.etag,
        response.data.blocks.at(-1)?.id,
      )
      setBlockPendingDelete(undefined)
      setStatus(`최신 블록 '${block.title}'을 삭제했습니다.`)
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '블록을 삭제하지 못했습니다.')
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

  const updateElement = (
    elementId: string,
    patch: Partial<KnowledgeStudioTBoxElement>,
  ) => {
    const target = elements.find((item) => item.stable_element_id === elementId)
    if (
      !target
      || (
        target.block_id !== selectedBlockId
        && target.block_id !== undefined
      )
      || target.locked_by_later_block
    ) return
    const next = elements.map((item) => (
      item.stable_element_id === elementId
        ? { ...item, ...patch }
        : item
    ))
    syncCanvasAndEditor(next)
  }

  const classes = elements.filter((item) => item.kind === 'CLASS')
  const blockOrdinalById = new Map(
    (record?.blocks ?? []).map((block) => [block.id, block.ordinal]),
  )
  const allowedParentIds = new Set(
    classes
      .filter((item) => {
        const ownerOrdinal = item.block_id
          ? blockOrdinalById.get(item.block_id)
          : selectedBlock?.ordinal
        return ownerOrdinal !== undefined && ownerOrdinal <= (selectedBlock?.ordinal ?? -1)
      })
      .map((item) => item.stable_element_id),
  )

  const reparentClass = (classId: string, parentId?: string) => {
    const target = elements.find((item) => item.stable_element_id === classId)
    if (
      target?.kind !== 'CLASS'
      || (
        target.block_id !== selectedBlockId
        && target.block_id !== undefined
      )
      || target.locked_by_later_block
      || (parentId && !allowedParentIds.has(parentId))
    ) return
    updateElement(classId, { parent_stable_element_id: parentId })
    setSelectedElementId(classId)
    setStatus(parentId
      ? `${target.display_name} Class의 subClassOf 계층을 변경했습니다.`
      : `${target.display_name} Class를 최상위로 이동했습니다.`)
  }

  const renderedNodes = nodes.map((node): CanvasNode => {
    if (node.type !== 'schemaClass') return node
    const item = elements.find((element) => element.stable_element_id === node.id)
    if (!item) return node
    const editable = (
      (item.block_id === selectedBlockId || item.block_id === undefined)
      && !item.locked_by_later_block
      && !locked
      && !working
    )
    return {
      ...node,
      data: {
        ...node.data,
        label: item.display_name,
        editable,
        locked: item.locked_by_later_block,
        selected: item.stable_element_id === selectedElementId,
        properties: elements
          .filter(
            (property) => property.kind === 'PROPERTY'
              && property.parent_stable_element_id === item.stable_element_id,
          )
          .map((property) => ({
            id: property.stable_element_id,
            label: property.display_name,
          })),
        onRename: (value) => updateElement(item.stable_element_id, {
          display_name: value,
        }),
        onDelete: () => deleteElement(item.stable_element_id),
        onAddProperty: (value) => addProperty(item.stable_element_id, value),
      },
    }
  })

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
            <header className="flex min-h-12 flex-wrap items-center gap-2 px-3 py-2">
              <button
                type="button"
                className="flex min-w-24 items-center gap-2 text-left"
                aria-label={`${block.title} ${block.kind} 블록 열기`}
                onClick={() => applyBlock(block, record)}
              >
                <span className="rounded bg-slate-100 px-2 py-1 text-[10px] font-black text-slate-600">
                  {block.ordinal + 1}
                </span>
              </button>
              <input
                aria-label={`${block.ordinal + 1}번 블록 이름`}
                className="input min-w-[180px] flex-1 border-transparent bg-transparent py-1 text-sm font-black text-navy-900 hover:border-slate-300 focus:bg-white"
                defaultValue={block.title}
                maxLength={120}
                disabled={locked || working}
                onClick={(event) => event.stopPropagation()}
                onBlur={(event) => {
                  const title = event.currentTarget.value.trim()
                  if (title && title !== block.title) void updateBlock(block, { title })
                  else event.currentTarget.value = block.title
                }}
              />
              <span className="rounded bg-slate-100 px-2 py-1 text-[9px] font-bold text-slate-500">
                {block.kind}
              </span>
              <label className="flex items-center gap-2 text-xs font-bold text-slate-600">
                W
                <input
                  aria-label={`${block.title} 가중치`}
                  className="input w-16 py-1"
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
                className="button button-danger px-2 py-1.5"
                aria-label={`${block.title} 블록 삭제`}
                title={block.id === lastBlockId
                  ? '최신 블록 삭제'
                  : '의존성 보호: 가장 최신 블록만 삭제할 수 있습니다.'}
                disabled={locked || working || block.id !== lastBlockId}
                onClick={() => setBlockPendingDelete(block)}
              >
                <Trash2 size={13} aria-hidden="true" />
              </button>
              <button
                type="button"
                className="button button-secondary px-2 py-1.5"
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
                <div className="grid min-h-[520px] gap-3 xl:grid-cols-[270px_minmax(0,1fr)]">
                  <ClassHierarchyTree
                    classes={classes}
                    selectedId={selectedElementId}
                    activeBlockId={selectedBlockId}
                    allowedParentIds={allowedParentIds}
                    disabled={locked || working}
                    onSelect={setSelectedElementId}
                    onAdd={addClass}
                    onReparent={reparentClass}
                  />
                  <div className="relative min-h-[520px] overflow-hidden rounded-enterprise border border-slate-700 bg-[#0b1d31]">
                    <header className="absolute left-3 top-3 z-10 rounded border border-slate-600 bg-[#10253d]/95 px-3 py-2 text-xs font-black text-slate-100 shadow">
                      <span className="flex items-center gap-2">
                        <GitBranch size={14} aria-hidden="true" />
                        TBoxGraphCanvas · Class schema
                      </span>
                    </header>
                    {classes.length === 0 && (
                      <div className="pointer-events-none absolute inset-0 z-10 grid place-items-center p-8 text-center">
                        <p className="rounded border border-dashed border-slate-600 bg-[#10253d]/95 p-5 text-xs leading-5 text-slate-300">
                          좌측 Class Hierarchy의 (+)로 첫 Class를 추가하세요.
                        </p>
                      </div>
                    )}
                    <ReactFlow<CanvasNode, SchemaEdge>
                      aria-label="T-Box 그래프 캔버스"
                      nodes={renderedNodes}
                      edges={edges}
                      nodeTypes={schemaNodeTypes}
                      onNodesChange={onNodesChange}
                      onEdgesChange={onEdgesChange}
                      onConnect={connect}
                      onNodeClick={(_, node) => {
                        if (node.type === 'schemaClass') setSelectedElementId(node.id)
                      }}
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
                      {classes.length > 0 && (
                        <MiniMap
                          pannable
                          zoomable
                          nodeColor={(node) => (
                            node.type === 'layerGroup' ? '#334155' : '#0ea5e9'
                          )}
                          maskColor="rgba(2, 12, 27, .72)"
                        />
                      )}
                    </ReactFlow>
                  </div>
                </div>
                <section className="mt-3 flex min-h-0 flex-col rounded-enterprise border border-slate-700 bg-[#081525]">
                  <header className="flex items-center justify-between border-b border-slate-700 px-3 py-2 text-xs font-black text-slate-100">
                    <span>SchemaCypherEditor · safe CREATE subset · 실행되지 않음</span>
                    <span className="text-[9px] font-semibold text-slate-400">
                      Class hierarchy = SUBCLASS_OF
                    </span>
                  </header>
                  <textarea
                    aria-label="T-Box Cypher 편집기"
                    className="min-h-[220px] resize-y bg-transparent p-4 font-mono text-xs leading-6 text-cyan-100 outline-none"
                    spellCheck={false}
                    value={editorText}
                    disabled={locked || working}
                    onChange={(event) => changeEditor(event.target.value)}
                  />
                  <div
                    className={`min-h-12 border-t p-3 text-xs leading-5 ${editorError ? 'border-red-700 bg-red-950/70 text-red-100' : 'border-slate-700 text-emerald-300'}`}
                    role={editorError ? 'alert' : 'status'}
                  >
                    {editorError
                      ? `Line ${editorError.line}, Column ${editorError.column} · ${editorError.message}`
                      : 'Validation OK · 트리, 캔버스와 마지막 정상 AST가 동기화되었습니다.'}
                  </div>
                </section>
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
        open={Boolean(blockPendingDelete)}
        title="최신 T-Box 블록 삭제"
        description="블록 의존성 보호를 위해 가장 마지막 블록만 삭제할 수 있습니다."
        onRequestClose={() => {
          if (!working) setBlockPendingDelete(undefined)
        }}
        footer={<>
          <button
            type="button"
            className="button button-secondary"
            disabled={working}
            onClick={() => setBlockPendingDelete(undefined)}
          >
            취소
          </button>
          <button
            type="button"
            className="button button-danger"
            disabled={working || !blockPendingDelete}
            onClick={() => {
              if (blockPendingDelete) void deleteBlock(blockPendingDelete)
            }}
          >
            최신 블록 삭제
          </button>
        </>}
      >
        <p className="m-0 text-sm leading-6 text-slate-700">
          <strong>{blockPendingDelete?.title}</strong> 블록과 이 블록이 소유한 Class,
          Property, Relationship 초안을 삭제합니다. 이전 블록은 변경하지 않습니다.
        </p>
      </Dialog>

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
