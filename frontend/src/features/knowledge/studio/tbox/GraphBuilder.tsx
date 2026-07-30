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
  ConnectionMode,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  NodeToolbar,
  Position,
  ReactFlow,
  applyEdgeChanges,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
  type NodeProps,
  type Viewport,
} from '@xyflow/react'
import {
  Bot,
  Check,
  Database,
  FileUp,
  FolderTree,
  GitBranch,
  LockKeyhole,
  Plus,
  Save,
  Search,
  Trash2,
  X,
} from 'lucide-react'
import type { ApiClient } from '../../../../api/client'
import { Dialog } from '../../../../components/common/Dialog'
import {
  defaultKnowledgeStudioViewport,
  getKnowledgeStudioBlockSession,
  useKnowledgeStudioSessionStore,
} from '../knowledgeStudioSessionStore'
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
  createKnowledgeStudioTBoxCatalogProposal,
  createKnowledgeStudioTBoxProposal,
  deleteKnowledgeStudioTBoxBlock,
  getKnowledgeStudioTBoxCatalogSource,
  getKnowledgeStudioTBox,
  searchKnowledgeStudioTBoxCatalogSources,
  newKnowledgeStudioIdempotencyKey,
  uploadKnowledgeStudioTBoxDocumentProposal,
  updateKnowledgeStudioTBoxBlock,
  type KnowledgeStudioDraft,
  type KnowledgeStudioTBox,
  type KnowledgeStudioTBoxBlock,
  type KnowledgeStudioTBoxBlockKind,
  type KnowledgeStudioTBoxElement,
  type KnowledgeStudioTBoxOperation,
  type KnowledgeStudioTBoxProposal,
  type KnowledgeStudioSourceDataset,
} from '../knowledgeStudioApi'

interface SchemaNodeData extends Record<string, unknown> {
  label: string
  ordinal: number
  editable: boolean
  locked: boolean
  selected: boolean
  editorOpen: boolean
  editorScale: number
  canStartConnection: boolean
  blockLabel: string
  properties: Array<{ id: string; label: string; dataType: string }>
  onToggleEditor: () => void
  onRename: (value: string) => void
  onDelete: () => void
  onAddProperty: (value: string) => void
  onUpdateProperty: (id: string, value: string, dataType: string) => void
  onDeleteProperty: (id: string) => void
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

const directBlockOption: {
  kind: KnowledgeStudioTBoxBlockKind
  title: string
  description: string
  icon: typeof Plus
} = {
  kind: 'DIRECT',
  title: '직접 정의',
  description: '직접 편집, 문서 및 카탈로그 Proposal을 하나의 통합 레이어에서 다룹니다.',
  icon: Plus,
}

const propertyDataTypes = ['STRING', 'TEXT', 'INTEGER', 'FLOAT', 'BOOLEAN', 'DATE', 'DATETIME']
const catalogSearchFieldOptions = [
  ['TABLE', '테이블명'],
  ['SCHEMA', '스키마'],
  ['COLUMN', '컬럼'],
  ['TAG', '태그'],
  ['TERM', '용어'],
  ['DESCRIPTION', '설명'],
] as const

interface PropertyRowProps {
  classLabel: string
  property: { id: string; label: string; dataType: string }
  disabled: boolean
  onUpdate: (id: string, value: string, dataType: string) => void
  onDelete: (id: string) => void
}

function PropertyRow({
  classLabel,
  property,
  disabled,
  onUpdate,
  onDelete,
}: PropertyRowProps) {
  const [name, setName] = useState(property.label)
  const [dataType, setDataType] = useState(property.dataType)

  useEffect(() => {
    setName(property.label)
    setDataType(property.dataType)
  }, [property.dataType, property.label])

  const commit = () => {
    const nextName = schemaIdentifier(name, 'Property')
    if (!nextName) {
      setName(property.label)
      return
    }
    if (nextName !== property.label || dataType !== property.dataType) {
      onUpdate(property.id, nextName, dataType)
    }
  }

  return (
    <li className="grid grid-cols-[minmax(0,1fr)_78px_24px] items-center gap-1">
      <input
        aria-label={`${classLabel} ${property.label} Property 이름`}
        className="input min-w-0 py-1 text-[10px]"
        value={name}
        disabled={disabled}
        onChange={(event) => setName(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault()
            commit()
          } else if (event.key === 'Escape') {
            setName(property.label)
          }
        }}
      />
      <select
        aria-label={`${classLabel} ${property.label} Property 타입`}
        className="input min-w-0 py-1 text-[9px]"
        value={dataType}
        disabled={disabled}
        onChange={(event) => {
          const value = event.target.value
          setDataType(value)
          onUpdate(property.id, schemaIdentifier(name, 'Property') || property.label, value)
        }}
      >
        {propertyDataTypes.map((value) => <option key={value}>{value}</option>)}
      </select>
      <button
        type="button"
        className="rounded p-1 text-red-600 hover:bg-red-50 disabled:text-slate-300"
        aria-label={`${classLabel} ${property.label} Property 삭제`}
        disabled={disabled}
        onClick={() => onDelete(property.id)}
      >
        <Trash2 size={11} aria-hidden="true" />
      </button>
    </li>
  )
}

function SchemaClassNode({ data, selected }: NodeProps<SchemaNode>) {
  const [propertyName, setPropertyName] = useState('')
  const [displayName, setDisplayName] = useState(data.label)

  useEffect(() => setDisplayName(data.label), [data.label])

  return (
    <div className={`relative w-[138px] rounded-md border bg-[#10253d] px-2.5 py-1.5 text-[10px] font-extrabold text-slate-50 shadow-lg ${
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
      <Handle
        id="body"
        type="source"
        position={Position.Bottom}
        isConnectable
        isConnectableStart={data.canStartConnection}
        isConnectableEnd
        className="border-transparent! bg-transparent!"
        style={{
          inset: -5,
          width: 'calc(100% + 10px)',
          height: 'calc(100% + 10px)',
          transform: 'none',
          borderRadius: 9,
          zIndex: 0,
        }}
      />
      <Handle
        id="hierarchy-source-bottom"
        type="source"
        position={Position.Bottom}
        isConnectable={false}
        className="border-transparent! bg-transparent!"
        style={{ width: 1, height: 1, minWidth: 1, minHeight: 1 }}
      />
      <Handle
        id="hierarchy-target-top"
        type="target"
        position={Position.Top}
        isConnectable={false}
        className="border-transparent! bg-transparent!"
        style={{ width: 1, height: 1, minWidth: 1, minHeight: 1 }}
      />
      <button
        type="button"
        className="nodrag nowheel relative z-10 block w-full truncate rounded pt-1 text-left hover:text-cyan-200 focus:outline-none focus:ring-1 focus:ring-cyan-300"
        aria-label={`${data.label} Class 편집기 ${data.editorOpen ? '닫기' : '열기'}`}
        onClick={(event) => {
          event.stopPropagation()
          data.onToggleEditor()
        }}
      >
        {data.label}
      </button>
      <span className="mt-0.5 block truncate text-[8px] font-semibold text-sky-200">
        {data.blockLabel}
      </span>
      {data.editorOpen && (
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
      <span aria-hidden="true" className="pointer-events-none absolute -top-1 left-1/2 z-20 size-2 -translate-x-1/2 rounded-full border border-sky-100 bg-cyan-400" />
      <span aria-hidden="true" className="pointer-events-none absolute -bottom-1 left-1/2 z-20 size-2 -translate-x-1/2 rounded-full border border-sky-100 bg-cyan-400" />
      <span aria-hidden="true" className="pointer-events-none absolute -left-1 top-1/2 z-20 size-2 -translate-y-1/2 rounded-full border border-sky-100 bg-cyan-400" />
      <span aria-hidden="true" className="pointer-events-none absolute -right-1 top-1/2 z-20 size-2 -translate-y-1/2 rounded-full border border-sky-100 bg-cyan-400" />
      <NodeToolbar
        isVisible={data.editorOpen}
        position={Position.Right}
        offset={10}
        className="w-[218px] rounded-enterprise border border-slate-300 bg-white p-2.5 text-[10px] text-slate-800 shadow-2xl"
      >
        <div
          className="grid gap-2"
          role="dialog"
          aria-label={`${data.label} Class 빠른 편집`}
          style={{
            transform: `scale(${data.editorScale})`,
            transformOrigin: 'left center',
          }}
          onPointerDown={(event) => event.stopPropagation()}
        >
          <div className="flex items-center justify-between gap-2">
            <strong className="truncate text-[11px] text-navy-900">Class 빠른 편집</strong>
            {data.locked && (
              <span className="flex items-center gap-1 rounded bg-amber-100 px-2 py-1 text-[9px] font-black text-amber-800">
                <LockKeyhole size={10} aria-hidden="true" />
                LOCKED
              </span>
            )}
          </div>
          <label className="text-[10px] font-bold leading-4 text-slate-600">
            표시 이름
            <input
              className="input mt-1 py-1 text-[10px]"
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
              <ul className="mb-2 mt-1 grid max-h-28 list-none gap-1 overflow-auto p-0 text-[9px] text-slate-600">
                {data.properties.map((property) => (
                  <PropertyRow
                    key={property.id}
                    classLabel={data.label}
                    property={property}
                    disabled={!data.editable}
                    onUpdate={data.onUpdateProperty}
                    onDelete={data.onDeleteProperty}
                  />
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
                    const value = schemaIdentifier(propertyName, 'Property')
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
                disabled={!data.editable || !schemaIdentifier(propertyName, 'Property')}
                onClick={() => {
                  const value = schemaIdentifier(propertyName, 'Property')
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
  relationships: KnowledgeStudioTBoxElement[]
  selectedId: string
  activeBlockId: string
  allowedParentIds: ReadonlySet<string>
  disabled: boolean
  onSelect: (id: string) => void
  onAdd: (name: string, parentId?: string) => void
  onReparent: (id: string, parentId?: string) => void
  onRenameHierarchy: (id: string, relation: string) => void
  onRenameRelationship: (id: string, relation: string) => void
}

function ClassHierarchyTree({
  classes,
  relationships,
  selectedId,
  activeBlockId,
  allowedParentIds,
  disabled,
  onSelect,
  onAdd,
  onReparent,
  onRenameHierarchy,
  onRenameRelationship,
}: ClassHierarchyTreeProps) {
  const [newClassName, setNewClassName] = useState('')
  const [parentForNewClass, setParentForNewClass] = useState<string>()
  const [editingRelationId, setEditingRelationId] = useState('')
  const [relationName, setRelationName] = useState('')
  const [dropTargetId, setDropTargetId] = useState<string>()
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
    setDropTargetId(undefined)
    if (
      !classId
      || disabled
      || (parentId && (!allowedParentIds.has(parentId) || createsCycle(classId, parentId)))
    ) return
    onReparent(classId, parentId)
  }

  const renderBranch = (parentId = '', depth = 0): ReactNode => (
    (childrenByParent.get(parentId) ?? []).map((item) => {
      const editable = (
        (item.block_id === activeBlockId || item.block_id === undefined)
        && !item.locked_by_later_block
      )
      const children = childrenByParent.get(item.stable_element_id) ?? []
      const hierarchyRelation = item.hierarchy_relation ?? 'SUBCLASS_OF'
      return (
        <li key={item.stable_element_id}>
          {parentId && (
            <div
              className="flex h-5 items-center gap-1 text-[9px] text-emerald-700"
              style={{ marginLeft: Math.max(4, depth * 12 - 8) }}
              title={`${classById.get(parentId)?.display_name ?? parentId} → ${item.display_name}: ${hierarchyRelation}`}
            >
              <span
                aria-hidden="true"
                className="h-5 w-3 rounded-bl border-b border-l border-emerald-400"
              />
              {editingRelationId === item.stable_element_id ? (
                <input
                  autoFocus
                  aria-label={`${item.display_name} 계층 관계 이름`}
                  className="input h-5 min-w-0 flex-1 py-0 text-[9px]"
                  value={relationName}
                  onChange={(event) => setRelationName(event.target.value)}
                  onBlur={() => {
                    const value = schemaIdentifier(relationName, 'Relation')
                    if (value && value !== hierarchyRelation) {
                      onRenameHierarchy(item.stable_element_id, value)
                    }
                    setEditingRelationId('')
                  }}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      event.preventDefault()
                      event.currentTarget.blur()
                    } else if (event.key === 'Escape') {
                      setEditingRelationId('')
                    }
                  }}
                />
              ) : (
                <button
                  type="button"
                  className="truncate rounded px-1 font-bold hover:bg-emerald-50 hover:text-emerald-900 disabled:text-slate-400"
                  aria-label={`${item.display_name} 계층 관계 ${hierarchyRelation} 편집`}
                  disabled={!editable || disabled}
                  onClick={() => {
                    setRelationName(hierarchyRelation)
                    setEditingRelationId(item.stable_element_id)
                  }}
                >
                  {hierarchyRelation}
                </button>
              )}
            </div>
          )}
          <div
            className={`group flex items-center gap-1 rounded border px-1 py-1 transition-colors ${
              dropTargetId === item.stable_element_id
                ? 'border-enterprise-blue bg-blue-100 ring-2 ring-blue-300'
                : 'border-transparent'
            } ${
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
              if (allowedParentIds.has(item.stable_element_id)) {
                event.preventDefault()
                setDropTargetId(item.stable_element_id)
              }
            }}
            onDragLeave={() => {
              setDropTargetId((current) => (
                current === item.stable_element_id ? undefined : current
              ))
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
          const name = schemaIdentifier(newClassName, 'Class')
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
          disabled={disabled || !schemaIdentifier(newClassName, 'Class')}
        >
          <Plus size={12} aria-hidden="true" />
        </button>
      </form>
      <div
        className={`min-h-0 flex-1 overflow-auto border-2 p-2 transition-colors ${
          dropTargetId === ''
            ? 'border-blue-300 bg-blue-50'
            : 'border-transparent'
        }`}
        onDragOver={(event) => {
          event.preventDefault()
          if (event.target === event.currentTarget) setDropTargetId('')
        }}
        onDragLeave={(event) => {
          const related = event.relatedTarget
          if (!(related instanceof Element) || !event.currentTarget.contains(related)) {
            setDropTargetId(undefined)
          }
        }}
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
      {relationships.length > 0 && (
        <section className="border-t border-slate-200 p-2" aria-label="T-Box 일반 관계">
          <strong className="mb-1 block text-[9px] font-black text-slate-500 uppercase">
            Relationships
          </strong>
          <ul className="m-0 grid max-h-28 list-none gap-1 overflow-auto p-0">
            {relationships.map((relationship) => {
              const editable = (
                (relationship.block_id === activeBlockId || relationship.block_id === undefined)
                && !relationship.locked_by_later_block
                && !disabled
              )
              const source = classById.get(relationship.source_stable_element_id ?? '')
              const target = classById.get(relationship.target_stable_element_id ?? '')
              return (
                <li
                  key={relationship.stable_element_id}
                  className={`rounded border px-2 py-1 text-[9px] ${
                    selectedId === relationship.stable_element_id
                      ? 'border-enterprise-blue bg-blue-50'
                      : 'border-slate-200'
                  }`}
                >
                  <button
                    type="button"
                    className="block w-full truncate text-left text-slate-500"
                    title={`${source?.display_name ?? '?'} → ${target?.display_name ?? '?'}`}
                    onClick={() => onSelect(relationship.stable_element_id)}
                  >
                    {source?.display_name ?? '?'} → {target?.display_name ?? '?'}
                  </button>
                  {editingRelationId === relationship.stable_element_id ? (
                    <input
                      autoFocus
                      aria-label={`${relationship.display_name} Relationship 이름`}
                      className="input mt-1 h-5 w-full py-0 text-[9px]"
                      value={relationName}
                      onChange={(event) => setRelationName(event.target.value)}
                      onBlur={() => {
                        const value = schemaIdentifier(relationName, 'Relation')
                        if (value && value !== relationship.canonical_name) {
                          onRenameRelationship(relationship.stable_element_id, value)
                        }
                        setEditingRelationId('')
                      }}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter') {
                          event.preventDefault()
                          event.currentTarget.blur()
                        } else if (event.key === 'Escape') {
                          setEditingRelationId('')
                        }
                      }}
                    />
                  ) : (
                    <button
                      type="button"
                      className="mt-1 truncate font-black text-violet-700 disabled:text-slate-400"
                      disabled={!editable}
                      onClick={() => {
                        setRelationName(relationship.canonical_name)
                        setEditingRelationId(relationship.stable_element_id)
                      }}
                    >
                      {relationship.display_name}
                    </button>
                  )}
                </li>
              )
            })}
          </ul>
        </section>
      )}
      <p className="m-0 border-t border-slate-200 p-2 text-[9px] leading-4 text-slate-500">
        Sibling도 자유롭게 드래그할 수 있습니다. 연결 라벨을 눌러 계층 관계 이름을 편집하세요.
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
      relation: item.hierarchy_relation ?? 'SUBCLASS_OF',
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

function effectiveSessionElements(
  record: KnowledgeStudioTBox,
  draftId: string,
): KnowledgeStudioTBoxElement[] {
  const merged = new Map(
    effectiveElements(record).map((item) => [item.stable_element_id, item]),
  )
  for (const block of record.blocks) {
    const cached = getKnowledgeStudioBlockSession(draftId, block.id)
    if (!cached) continue
    for (const [stableId, item] of merged) {
      if (item.block_id === block.id) merged.delete(stableId)
    }
    for (const item of cached.elements) {
      if (item.block_id === block.id) merged.set(item.stable_element_id, item)
    }
  }
  return [...merged.values()].sort((left, right) => left.ordinal - right.ordinal)
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
      editorOpen: false,
      editorScale: 1,
      canStartConnection: editable,
      blockLabel: block?.title ?? '현재 블록',
      properties: elements
        .filter(
          (property) => property.kind === 'PROPERTY'
            && property.parent_stable_element_id === item.stable_element_id,
        )
        .map((property) => ({
          id: property.stable_element_id,
          label: property.display_name,
          dataType: property.data_type ?? 'STRING',
        })),
      onRename: () => undefined,
      onDelete: () => undefined,
      onAddProperty: () => undefined,
      onToggleEditor: () => undefined,
      onUpdateProperty: () => undefined,
      onDeleteProperty: () => undefined,
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
        sourceHandle: 'body',
        targetHandle: 'body',
        style: { stroke: '#7dd3fc', strokeWidth: 1.6 },
        labelStyle: { fill: '#e2e8f0', fontWeight: 700 },
      }]
    })
  const hierarchyEdges = classes.flatMap((item): SchemaEdge[] => {
    const parent = item.parent_stable_element_id
    if (!parent || !classPositions.has(parent)) return []
    return [{
      id: `hierarchy:${item.stable_element_id}`,
      source: parent,
      target: item.stable_element_id,
      sourceHandle: 'hierarchy-source-bottom',
      targetHandle: 'hierarchy-target-top',
      label: item.hierarchy_relation ?? 'SUBCLASS_OF',
      data: {
        relation: item.hierarchy_relation ?? 'SUBCLASS_OF',
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
    hierarchy_relation: item.hierarchy_relation,
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
    hierarchy_relation: parentId ? 'SUBCLASS_OF' : undefined,
    ordinal,
    version: 1,
    aliases: [],
    vector_index_enabled: false,
    locked_by_later_block: false,
    layout_x: position.x,
    layout_y: position.y,
  }
}

function hasProposalValidationEvidence(proposal: KnowledgeStudioTBoxProposal): boolean {
  const source = proposal.source_reference
  const evidence = source?.pipeline_evidence
  return (
    typeof evidence === 'object'
    && evidence !== null
    && Reflect.get(evidence, 'typed_schema_parse') === 'PASSED'
    && Reflect.get(evidence, 'deterministic_correction_passes') === 1
    && Reflect.get(evidence, 'aggregate_validation_passes') === 1
    && Reflect.get(evidence, 'cypher_execution') === false
  )
}

export function schemaIdentifier(value: string, prefix = 'Class'): string {
  const cleaned = value
    .trim()
    .normalize('NFC')
    .replace(/[^\p{L}\p{N}_]+/gu, '_')
    .replace(/_+/g, '_')
    .replace(/^_+|_+$/g, '')
  if (!cleaned) return ''
  return /^\p{L}/u.test(cleaned) ? cleaned : `${prefix}_${cleaned}`
}

interface EditableBlockTitleProps {
  block: KnowledgeStudioTBoxBlock
  disabled: boolean
  onSave: (title: string) => void
}

function EditableBlockTitle({ block, disabled, onSave }: EditableBlockTitleProps) {
  const [value, setValue] = useState(block.title)
  useEffect(() => setValue(block.title), [block.title])
  const nextTitle = value.trim()
  const dirty = Boolean(nextTitle && nextTitle !== block.title)

  const save = () => {
    if (dirty) onSave(nextTitle)
    else setValue(block.title)
  }

  return (
    <div className="flex min-w-[220px] flex-1 items-center gap-1">
      <input
        aria-label={`${block.ordinal + 1}번 블록 이름`}
        className={`input min-w-0 flex-1 py-1 text-xs font-black text-navy-900 ${
          dirty
            ? 'border-enterprise-blue bg-white'
            : 'border-slate-200 bg-slate-50/60'
        }`}
        value={value}
        maxLength={120}
        disabled={disabled}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault()
            save()
          } else if (event.key === 'Escape') {
            setValue(block.title)
          }
        }}
      />
      <button
        type="button"
        className="rounded bg-transparent p-1 text-emerald-700 shadow-none hover:bg-transparent active:bg-transparent disabled:text-emerald-700"
        aria-label={`${block.title} 블록 이름 ${dirty ? '확인' : '저장됨'}`}
        title={dirty ? '저장' : '저장됨'}
        disabled={disabled || !dirty}
        onClick={save}
      >
        <Check size={13} aria-hidden="true" />
      </button>
      <button
        type="button"
        className="rounded p-1 text-slate-500 hover:bg-slate-100 disabled:text-slate-300"
        aria-label={`${block.title} 블록 이름 취소`}
        title="취소"
        disabled={disabled || value === block.title}
        onClick={() => setValue(block.title)}
      >
        <X size={13} aria-hidden="true" />
      </button>
    </div>
  )
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
  const [nodes, setNodes, applyNodeChanges] = useNodesState<CanvasNode>([])
  const [edges, setEdges] = useEdgesState<SchemaEdge>([])
  const [viewport, setViewport] = useState<Viewport>(defaultKnowledgeStudioViewport)
  const [editorText, setEditorText] = useState('')
  const [editorError, setEditorError] = useState<{
    message: string
    line: number
    column: number
  }>()
  const [selectedElementId, setSelectedElementId] = useState('')
  const [editorOpenId, setEditorOpenId] = useState('')
  const editorOpenIdRef = useRef('')
  const [status, setStatus] = useState('T-Box 정본을 불러오는 중입니다.')
  const [working, setWorking] = useState(false)
  const [showBlockMenu, setShowBlockMenu] = useState(false)
  const [assistantPrompt, setAssistantPrompt] = useState('')
  const [proposal, setProposal] = useState<KnowledgeStudioTBoxProposal>()
  const [proposalExcluded, setProposalExcluded] = useState<Set<string>>(new Set())
  const [proposalOverrides, setProposalOverrides] = useState<Record<string, {
    canonical_name: string
    display_name: string
    data_type?: string
  }>>({})
  const proposalOverridesValid = Object.values(proposalOverrides).every((item) => (
    item.display_name.trim().length > 0 && item.canonical_name.trim().length > 0
  ))
  const [conflictOpen, setConflictOpen] = useState(false)
  const [catalogOpen, setCatalogOpen] = useState(false)
  const [catalogQuery, setCatalogQuery] = useState('')
  const [catalogDomain, setCatalogDomain] = useState('')
  const [catalogSearchFields, setCatalogSearchFields] = useState<Set<string>>(
    () => new Set(catalogSearchFieldOptions.map(([value]) => value)),
  )
  const [catalogResults, setCatalogResults] = useState<KnowledgeStudioSourceDataset[]>([])
  const [selectedCatalog, setSelectedCatalog] = useState<KnowledgeStudioSourceDataset>()
  const [selectedCatalogFields, setSelectedCatalogFields] = useState<Set<string>>(new Set())
  const [catalogLoading, setCatalogLoading] = useState(false)
  const [catalogDetailLoading, setCatalogDetailLoading] = useState(false)
  const [documentCapabilityOpen, setDocumentCapabilityOpen] = useState(false)
  const [documentFile, setDocumentFile] = useState<File>()
  const [documentProposalMode, setDocumentProposalMode] = useState<
    'MERGE_INTO_CURRENT' | 'APPEND_LAYER'
  >('MERGE_INTO_CURRENT')
  const [documentWorkflow, setDocumentWorkflow] = useState<
    'IDLE' | 'PARSING' | 'COMPLETE' | 'FAILED'
  >('IDLE')
  const [documentWorkflowError, setDocumentWorkflowError] = useState('')
  const [validationPhase, setValidationPhase] = useState<'CHECKING' | 'VALID' | 'INVALID'>('VALID')
  const [blockPendingDelete, setBlockPendingDelete] = useState<KnowledgeStudioTBoxBlock>()
  const [conflictActions, setConflictActions] = useState<Record<string, 'KEEP_ORIGINAL' | 'ACCEPT_PROPOSAL'>>({})
  const setSessionBlock = useKnowledgeStudioSessionStore((state) => state.setBlock)
  const setSessionSelectedBlock = useKnowledgeStudioSessionStore(
    (state) => state.setSelectedBlock,
  )
  const removeSessionBlock = useKnowledgeStudioSessionStore((state) => state.removeBlock)
  const locked = lifecycleState !== 'DRAFT'

  const setOpenEditor = useCallback((nextId: string) => {
    editorOpenIdRef.current = nextId
    setEditorOpenId(nextId)
    setNodes((current) => current.map((node) => (
      node.type === 'schemaClass'
        ? {
            ...node,
            data: {
              ...node.data,
              editorOpen: node.id === nextId,
            },
          }
        : node
    )))
  }, [setNodes])

  const selectedBlock = record?.blocks.find((item) => item.id === selectedBlockId)
  const lastBlockId = record?.blocks.at(-1)?.id

  const applyBlock = useCallback((
    block: KnowledgeStudioTBoxBlock,
    source: KnowledgeStudioTBox,
  ) => {
    const nextElements = effectiveSessionElements(source, draftId)
    const blockElements = block.elements.map((item) => ({
      ...item,
      block_id: item.block_id ?? block.id,
      aliases: item.aliases ?? [],
      vector_index_enabled: item.vector_index_enabled ?? false,
    }))
    const cached = getKnowledgeStudioBlockSession(draftId, block.id)
    const restored = nextElements
    const graph = flowGraph(restored, block.id, source.blocks, '')
    const safe = asSafeGraph(nextElements)
    setSelectedBlockId(block.id)
    setSessionSelectedBlock(draftId, block.id)
    setElements(restored)
    setBaseline(blockElements)
    setNodes(graph.nodes)
    setEdges(graph.edges)
    const cachedParse = cached
      ? parseSafeCypherDraft(cached.editorText, asSafeGraph(cached.elements))
      : undefined
    const nextEditorText = cachedParse?.error
      ? cached!.editorText
      : formatSafeCypherDraft(safe.nodes, safe.edges)
    const parsed = parseSafeCypherDraft(nextEditorText, asSafeGraph(restored))
    setEditorText(nextEditorText)
    setEditorError(parsed.error
      ? parsed.diagnostic ?? { message: parsed.error, line: 1, column: 1 }
      : undefined)
    setViewport(cached
      ? cached.viewport
      : defaultKnowledgeStudioViewport())
    setSelectedElementId('')
    editorOpenIdRef.current = ''
    setEditorOpenId('')
  }, [
    draftId,
    setEdges,
    setNodes,
    setSessionSelectedBlock,
  ])

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
        const cachedBlockId = useKnowledgeStudioSessionStore
          .getState()
          .sessions[draftId]
          ?.selectedBlockId
        const selected = response.data.blocks.find((item) => item.id === cachedBlockId)
          ?? response.data.blocks[0]
        if (selected) applyBlock(selected, response.data)
        setStatus('Typed T-Box Draft를 불러왔습니다.')
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setStatus(error instanceof Error ? error.message : 'T-Box Draft를 불러오지 못했습니다.')
        }
      })
    return () => controller.abort()
  }, [applyBlock, client, draftId])

  useEffect(() => {
    if (!record || !selectedBlock) return
    const positioned = elements.map((item) => {
      const node = nodes.find((candidate) => candidate.id === item.stable_element_id)
      return node
        ? { ...item, layout_x: node.position.x, layout_y: node.position.y }
        : item
    })
    setSessionBlock(draftId, selectedBlock.id, {
      blockVersion: selectedBlock.version,
      elements: positioned.map((item) => (
        item.block_id
          ? item
          : { ...item, block_id: selectedBlock.id }
      )),
      editorText,
      viewport,
    })
  }, [
    draftId,
    editorText,
    elements,
    nodes,
    record,
    selectedBlock,
    setSessionBlock,
    viewport,
  ])

  useEffect(() => {
    if (editorError) {
      setValidationPhase('INVALID')
      return
    }
    setValidationPhase('CHECKING')
    const timeout = window.setTimeout(() => setValidationPhase('VALID'), 220)
    return () => window.clearTimeout(timeout)
  }, [editorError, editorText])

  const syncCanvasAndEditor = useCallback((next: KnowledgeStudioTBoxElement[]) => {
    const positions = new Map(
      nodes
        .filter((node) => node.type === 'schemaClass')
        .map((node) => [node.id, node.position]),
    )
    const positioned = next.map((item) => {
      const position = positions.get(item.stable_element_id)
      return position
        ? { ...item, layout_x: position.x, layout_y: position.y }
        : item
    })
    const graph = flowGraph(
      positioned,
      selectedBlockId,
      record?.blocks ?? [],
      selectedElementId,
    )
    const safe = asSafeGraph(positioned)
    setElements(positioned)
    setNodes(graph.nodes)
    setEdges(graph.edges)
    setEditorText(formatSafeCypherDraft(safe.nodes, safe.edges))
    setEditorError(undefined)
  }, [nodes, record?.blocks, selectedBlockId, selectedElementId, setEdges, setNodes])

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
    const hierarchyRelationByClass = new Map<string, string>()
    const priorHierarchyEdgeIds = new Set(
      elements
        .filter((item) => item.kind === 'CLASS' && item.parent_stable_element_id)
        .map((item) => `hierarchy:${item.stable_element_id}`),
    )
    const hierarchyEdgeIds = new Set<string>()
    for (const edge of parsed.edges) {
      const hierarchy = priorHierarchyEdgeIds.has(edge.id)
        || (edge.relation === 'SUBCLASS_OF' && !elements.some(
          (item) => item.kind === 'RELATION' && item.stable_element_id === edge.id,
        ))
      if (!hierarchy) continue
      if (edge.source === edge.target || hierarchyParentByClass.has(edge.source)) {
        setEditorError({
          message: 'Class hierarchy는 Class당 하나의 부모만 가지며 순환할 수 없습니다.',
          line: 1,
          column: 1,
        })
        return
      }
      hierarchyParentByClass.set(edge.source, edge.target)
      hierarchyRelationByClass.set(edge.source, edge.relation)
      hierarchyEdgeIds.add(edge.id)
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
          || (
            item.parent_stable_element_id !== undefined
            && hierarchyRelationByClass.get(item.stable_element_id)
              !== (item.hierarchy_relation ?? 'SUBCLASS_OF')
          )
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
        hierarchy_relation: hierarchyParentByClass.has(item.id)
          ? hierarchyRelationByClass.get(item.id) ?? 'SUBCLASS_OF'
          : undefined,
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
      .filter((item) => !hierarchyEdgeIds.has(item.id))
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
    const name = schemaIdentifier(rawName, 'Class')
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
    if (
      locked
      || !connection.source
      || !connection.target
      || connection.source === connection.target
      || !selectedBlock
    ) return
    const blockOrdinalById = new Map(
      (record?.blocks ?? []).map((block) => [block.id, block.ordinal]),
    )
    const source = elements.find((item) => item.stable_element_id === connection.source)
    const target = elements.find((item) => item.stable_element_id === connection.target)
    const sourceIsCurrent = source?.kind === 'CLASS' && (
      source.block_id === selectedBlock.id || source.block_id === undefined
    )
    const targetOrdinal = target?.block_id
      ? blockOrdinalById.get(target.block_id)
      : selectedBlock.ordinal
    if (
      !sourceIsCurrent
      || target?.kind !== 'CLASS'
      || targetOrdinal === undefined
      || targetOrdinal > selectedBlock.ordinal
    ) {
      setStatus('Relationship는 현재 블록 Class에서 현재 또는 이전 블록 Class 방향으로만 연결할 수 있습니다.')
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
    syncCanvasAndEditor(next)
    setSelectedElementId(stableId)
  }, [elements, locked, record?.blocks, selectedBlock, syncCanvasAndEditor])

  const deleteElement = useCallback((elementId: string) => {
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
  }, [elements, locked, selectedBlockId, syncCanvasAndEditor, working])

  const handleNodesChange = useCallback((changes: NodeChange<CanvasNode>[]) => {
    const removals = changes.filter((change) => change.type === 'remove')
    for (const change of removals) deleteElement(change.id)
    applyNodeChanges(changes.filter((change) => change.type !== 'remove'))
    const positions = new Map(
      changes.flatMap((change) => (
        change.type === 'position' && change.position
          ? [[change.id, change.position] as const]
          : []
      )),
    )
    if (positions.size === 0) return
    setElements((current) => current.map((item) => {
      const position = positions.get(item.stable_element_id)
      return position
        ? { ...item, layout_x: position.x, layout_y: position.y }
        : item
    }))
  }, [applyNodeChanges, deleteElement])

  const handleEdgesChange = useCallback((changes: EdgeChange<SchemaEdge>[]) => {
    const removals = changes.filter((change) => change.type === 'remove')
    const hierarchyClassIds = new Set(
      removals
        .filter((change) => change.id.startsWith('hierarchy:'))
        .map((change) => change.id.replace(/^hierarchy:/, '')),
    )
    if (hierarchyClassIds.size > 0) {
      syncCanvasAndEditor(elements.map((item) => (
        hierarchyClassIds.has(item.stable_element_id)
          ? {
              ...item,
              parent_stable_element_id: undefined,
              hierarchy_relation: undefined,
            }
          : item
      )))
    }
    for (const change of removals) {
      if (!change.id.startsWith('hierarchy:')) deleteElement(change.id)
    }
    const presentationChanges = changes.filter((change) => change.type !== 'remove')
    if (presentationChanges.length > 0) {
      setEdges((current) => applyEdgeChanges(presentationChanges, current))
    }
  }, [deleteElement, elements, setEdges, syncCanvasAndEditor])

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
    const name = schemaIdentifier(rawName, 'Property')
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

  const updateProperty = (
    propertyId: string,
    rawName: string,
    dataType: string,
  ) => {
    const property = elements.find((item) => item.stable_element_id === propertyId)
    const name = schemaIdentifier(rawName, 'Property')
    if (
      property?.kind !== 'PROPERTY'
      || !name
      || !propertyDataTypes.includes(dataType)
      || locked
      || working
    ) return
    if (elements.some(
      (item) => item.kind === 'PROPERTY'
        && item.stable_element_id !== propertyId
        && item.parent_stable_element_id === property.parent_stable_element_id
        && item.canonical_name.toLocaleLowerCase() === name.toLocaleLowerCase(),
    )) {
      setStatus(`Property '${name}'은(는) 이미 존재합니다.`)
      return
    }
    updateElement(propertyId, {
      canonical_name: name,
      display_name: name,
      data_type: dataType,
      vector_index_enabled: property.vector_index_enabled
        && (dataType === 'STRING' || dataType === 'TEXT'),
    })
    setStatus(`Property '${name}'을(를) 수정했습니다. 저장 시 Typed Operation으로 반영됩니다.`)
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

  const createBlock = async (option: typeof directBlockOption) => {
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
      removeSessionBlock(draftId, block.id)
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
          excluded_stable_element_ids: [...proposalExcluded],
          element_overrides: Object.entries(proposalOverrides).map(([stableId, value]) => ({
            stable_element_id: stableId,
            ...value,
          })),
        },
        responseEtag,
        newKnowledgeStudioIdempotencyKey(),
      )
      if (!response.etag) return
      applyResponse(response.data, response.etag)
      setConflictOpen(false)
      setProposal(undefined)
      setProposalExcluded(new Set())
      setProposalOverrides({})
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
    promptOverride?: string,
  ) => {
    const prompt = promptOverride?.trim() || assistantPrompt.trim()
    if (!prompt || working || locked || !selectedBlock) return
    setWorking(true)
    setStatus('서버의 승인된 LLM 런타임에서 T-Box Proposal을 생성 중입니다.')
    try {
      const next = await createKnowledgeStudioTBoxProposal(client, draftId, {
        target_block_id: mode === 'MERGE_INTO_CURRENT' ? selectedBlock.id : undefined,
        mode,
        prompt,
      }, responseEtag)
      setProposal(next)
      setProposalExcluded(new Set())
      setProposalOverrides({})
      setConflictActions(Object.fromEntries(
        next.conflicts.map((item) => [item.conflict_id, 'KEEP_ORIGINAL']),
      ))
      setWorking(false)
      setStatus(
        next.conflicts.length > 0
          ? `${next.conflicts.length}개의 충돌이 포함된 Proposal을 미리보기로 불러왔습니다.`
          : `${next.elements.length}개의 Typed 요소 Proposal을 미리보기로 불러왔습니다.`,
      )
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'LLM Proposal 생성에 실패했습니다.')
      setWorking(false)
    }
  }

  const requestDocumentProposal = async () => {
    if (!documentFile || working || locked || !selectedBlock) return
    setWorking(true)
    setDocumentWorkflow('PARSING')
    setDocumentWorkflowError('')
    setStatus('문서를 안전하게 저장하고 실제 T-Box Proposal을 생성 중입니다.')
    try {
      const next = await uploadKnowledgeStudioTBoxDocumentProposal(
        client,
        draftId,
        {
          file: documentFile,
          upload_id: crypto.randomUUID(),
          target_block_id: documentProposalMode === 'MERGE_INTO_CURRENT'
            ? selectedBlock.id
            : undefined,
          mode: documentProposalMode,
        },
        responseEtag,
      )
      if (!hasProposalValidationEvidence(next)) {
        throw new Error('서버가 Typed T-Box 검증 증거를 반환하지 않아 Proposal을 표시하지 않았습니다.')
      }
      setProposal(next)
      setProposalExcluded(new Set())
      setProposalOverrides({})
      setConflictActions(Object.fromEntries(
        next.conflicts.map((item) => [item.conflict_id, 'KEEP_ORIGINAL']),
      ))
      setDocumentWorkflow('COMPLETE')
      setStatus(
        `${documentFile.name}에서 ${next.elements.length}개의 Typed 요소 Proposal을 생성했습니다.`,
      )
    } catch (error) {
      const message = error instanceof Error
        ? error.message
        : '문서 Proposal 생성에 실패했습니다.'
      setDocumentWorkflow('FAILED')
      setDocumentWorkflowError(message)
      setStatus(message)
    } finally {
      setWorking(false)
    }
  }

  const searchCatalog = async () => {
    if (catalogLoading) return
    setCatalogLoading(true)
    try {
      const result = await searchKnowledgeStudioTBoxCatalogSources(
        client,
        draftId,
        catalogQuery,
        {
          domain: catalogDomain,
          search_fields: [...catalogSearchFields],
        },
      )
      setCatalogResults(result.items)
      setStatus(`권한 범위의 카탈로그 ${result.items.length}건을 조회했습니다.`)
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '카탈로그를 조회하지 못했습니다.')
    } finally {
      setCatalogLoading(false)
    }
  }

  const selectCatalogSource = async (summary: KnowledgeStudioSourceDataset) => {
    if (catalogDetailLoading) return
    setSelectedCatalog(summary)
    setSelectedCatalogFields(new Set())
    setCatalogDetailLoading(true)
    try {
      const detail = await getKnowledgeStudioTBoxCatalogSource(
        client,
        draftId,
        summary.id,
      )
      setSelectedCatalog(detail.dataset)
      setSelectedCatalogFields(new Set(detail.dataset.field_paths))
      setStatus(
        `${detail.dataset.name}의 실제 컬럼 ${detail.dataset.field_paths.length}개를 불러왔습니다.`,
      )
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '카탈로그 컬럼을 불러오지 못했습니다.')
    } finally {
      setCatalogDetailLoading(false)
    }
  }

  const proposeSelectedCatalog = async (
    mode: 'MERGE_INTO_CURRENT' | 'APPEND_LAYER',
  ) => {
    if (
      !selectedCatalog
      || selectedCatalogFields.size === 0
      || selectedCatalogFields.size > 100
      || working
      || locked
      || !selectedBlock
    ) return
    setWorking(true)
    setStatus('서버에서 카탈로그 Asset·버전·선택 컬럼을 재검증하고 Proposal을 생성 중입니다.')
    try {
      const next = await createKnowledgeStudioTBoxCatalogProposal(
        client,
        draftId,
        {
          asset_id: selectedCatalog.id,
          selected_field_paths: [...selectedCatalogFields].sort(),
          target_block_id: mode === 'MERGE_INTO_CURRENT' ? selectedBlock.id : undefined,
          mode,
        },
        responseEtag,
      )
      setProposal(next)
      setProposalExcluded(new Set())
      setProposalOverrides({})
      setConflictActions(Object.fromEntries(
        next.conflicts.map((item) => [item.conflict_id, 'KEEP_ORIGINAL']),
      ))
      setCatalogOpen(false)
      setStatus(
        `${selectedCatalog.name}의 검증된 메타데이터에서 ${next.elements.length}개 Typed 요소를 제안했습니다.`,
      )
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '카탈로그 Proposal 생성에 실패했습니다.')
    } finally {
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
    updateElement(classId, {
      parent_stable_element_id: parentId,
      hierarchy_relation: parentId
        ? target.hierarchy_relation ?? 'SUBCLASS_OF'
        : undefined,
    })
    setSelectedElementId(classId)
    setStatus(parentId
      ? `${target.display_name} Class의 subClassOf 계층을 변경했습니다.`
      : `${target.display_name} Class를 최상위로 이동했습니다.`)
  }

  const renameHierarchy = (classId: string, rawRelation: string) => {
    const relation = schemaIdentifier(rawRelation, 'Relation')
    const target = elements.find((item) => item.stable_element_id === classId)
    if (
      !relation
      || target?.kind !== 'CLASS'
      || !target.parent_stable_element_id
      || (target.block_id !== selectedBlockId && target.block_id !== undefined)
      || target.locked_by_later_block
    ) return
    updateElement(classId, { hierarchy_relation: relation })
    setStatus(`계층 관계 이름을 '${relation}'(으)로 변경했습니다.`)
  }

  const renameRelationship = (relationshipId: string, rawRelation: string) => {
    const relation = schemaIdentifier(rawRelation, 'Relation')
    const target = elements.find((item) => item.stable_element_id === relationshipId)
    if (
      !relation
      || target?.kind !== 'RELATION'
      || (target.block_id !== selectedBlockId && target.block_id !== undefined)
      || target.locked_by_later_block
    ) return
    updateElement(relationshipId, {
      canonical_name: relation,
      display_name: relation,
    })
    setStatus(`Relationship 이름을 '${relation}'(으)로 변경했습니다.`)
  }

  const reconnect = (edge: SchemaEdge, connection: Connection) => {
    if (
      locked
      || working
      || !connection.source
      || !connection.target
      || !selectedBlock
    ) return
    if (edge.data?.hierarchy) {
      const classId = edge.id.replace(/^hierarchy:/, '')
      if (connection.target !== classId || !allowedParentIds.has(connection.source)) {
        setStatus('계층선은 허용된 이전/현재 부모의 아래에서 현재 Class의 위로만 변경할 수 있습니다.')
        return
      }
      reparentClass(classId, connection.source)
      return
    }
    const relation = elements.find((item) => item.stable_element_id === edge.id)
    if (
      relation?.kind !== 'RELATION'
      || (relation.block_id !== selectedBlockId && relation.block_id !== undefined)
    ) return
    const source = elements.find((item) => item.stable_element_id === connection.source)
    const target = elements.find((item) => item.stable_element_id === connection.target)
    const sourceIsCurrent = source?.kind === 'CLASS' && (
      source.block_id === selectedBlock.id || source.block_id === undefined
    )
    const targetOrdinal = target?.block_id
      ? blockOrdinalById.get(target.block_id)
      : selectedBlock.ordinal
    if (
      !sourceIsCurrent
      || target?.kind !== 'CLASS'
      || targetOrdinal === undefined
      || targetOrdinal > selectedBlock.ordinal
    ) {
      setStatus('Relationship는 현재 블록 Class에서 현재 또는 이전 블록 Class 방향으로만 연결할 수 있습니다.')
      return
    }
    updateElement(relation.stable_element_id, {
      source_stable_element_id: connection.source,
      target_stable_element_id: connection.target,
    })
    setSelectedElementId(relation.stable_element_id)
  }

  const deleteSelection = useCallback(() => {
    if (!selectedElementId || locked || working) return
    if (selectedElementId.startsWith('hierarchy:')) {
      const classId = selectedElementId.replace(/^hierarchy:/, '')
      const target = elements.find((item) => item.stable_element_id === classId)
      if (
        target?.kind === 'CLASS'
        && (target.block_id === selectedBlockId || target.block_id === undefined)
        && !target.locked_by_later_block
      ) {
        const next = elements.map((item) => item.stable_element_id === classId
          ? {
              ...item,
              parent_stable_element_id: undefined,
              hierarchy_relation: undefined,
            }
          : item)
        syncCanvasAndEditor(next)
        setSelectedElementId('')
      }
      return
    }
    deleteElement(selectedElementId)
  }, [
    elements,
    deleteElement,
    locked,
    selectedBlockId,
    selectedElementId,
    syncCanvasAndEditor,
    working,
  ])

  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if (event.key !== 'Backspace' && event.key !== 'Delete') return
      const target = event.target
      if (
        target instanceof HTMLInputElement
        || target instanceof HTMLTextAreaElement
        || target instanceof HTMLSelectElement
        || (target instanceof HTMLElement && target.isContentEditable)
      ) return
      event.preventDefault()
      deleteSelection()
    }
    window.addEventListener('keydown', listener)
    return () => window.removeEventListener('keydown', listener)
  }, [deleteSelection])

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
        editorOpen: item.stable_element_id === editorOpenId,
        editorScale: Math.max(0.65, Math.min(1.25, viewport.zoom / 0.8)),
        canStartConnection: editable,
        properties: elements
          .filter(
            (property) => property.kind === 'PROPERTY'
              && property.parent_stable_element_id === item.stable_element_id,
          )
          .map((property) => ({
            id: property.stable_element_id,
            label: property.display_name,
            dataType: property.data_type ?? 'STRING',
        })),
        onToggleEditor: () => {
          setSelectedElementId(item.stable_element_id)
          setOpenEditor(
            editorOpenIdRef.current === item.stable_element_id
              ? ''
              : item.stable_element_id,
          )
        },
        onRename: (value) => {
          const name = schemaIdentifier(value, 'Class')
          if (!name) return
          if (elements.some(
            (candidate) => candidate.kind === 'CLASS'
              && candidate.stable_element_id !== item.stable_element_id
              && candidate.canonical_name.toLocaleLowerCase() === name.toLocaleLowerCase(),
          )) {
            setStatus(`Class '${name}'은(는) 이미 존재합니다.`)
            return
          }
          updateElement(item.stable_element_id, {
            canonical_name: name,
            display_name: name,
          })
        },
        onDelete: () => deleteElement(item.stable_element_id),
        onAddProperty: (value) => addProperty(item.stable_element_id, value),
        onUpdateProperty: updateProperty,
        onDeleteProperty: deleteElement,
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
              <EditableBlockTitle
                block={block}
                disabled={locked || working}
                onSave={(title) => void updateBlock(block, { title })}
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
            </header>
            {block.id === selectedBlockId && (
              <div className="border-t border-slate-200 p-3">
                <div className="mb-3 flex flex-wrap items-center gap-2 rounded-enterprise border border-blue-200 bg-blue-50 p-2">
                  <strong className="mr-auto text-[11px] text-blue-950">
                    통합 Schema Proposal Pipeline
                  </strong>
                  <button
                    type="button"
                    className="button button-secondary py-1.5 text-[10px]"
                    disabled={locked || working}
                    onClick={() => setDocumentCapabilityOpen(true)}
                  >
                    <FileUp size={13} aria-hidden="true" />
                    데이터 업로드
                  </button>
                  <button
                    type="button"
                    className="button button-secondary py-1.5 text-[10px]"
                    disabled={locked || working}
                    onClick={() => {
                      setCatalogOpen(true)
                      if (catalogResults.length === 0) void searchCatalog()
                    }}
                  >
                    <Database size={13} aria-hidden="true" />
                    DB 테이블 검색
                  </button>
                  <span
                    className={`rounded px-2 py-1 text-[9px] font-black ${
                      validationPhase === 'VALID'
                        ? 'bg-emerald-100 text-emerald-800'
                        : validationPhase === 'INVALID'
                          ? 'bg-red-100 text-red-800'
                          : 'bg-amber-100 text-amber-800'
                    }`}
                    role="status"
                  >
                    {validationPhase === 'VALID'
                      ? 'TYPED VALID'
                      : validationPhase === 'INVALID'
                        ? 'INVALID'
                        : 'VALIDATING…'}
                  </span>
                </div>
                <div className="grid min-h-[520px] gap-3 xl:grid-cols-[270px_minmax(0,1fr)]">
                  <ClassHierarchyTree
                    classes={classes}
                    relationships={elements.filter((item) => item.kind === 'RELATION')}
                    selectedId={selectedElementId}
                    activeBlockId={selectedBlockId}
                    allowedParentIds={allowedParentIds}
                    disabled={locked || working}
                    onSelect={setSelectedElementId}
                    onAdd={addClass}
                    onReparent={reparentClass}
                    onRenameHierarchy={renameHierarchy}
                    onRenameRelationship={renameRelationship}
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
                    {proposal && (
                      <aside
                        className="absolute right-3 top-3 z-20 w-[230px] rounded-enterprise border border-violet-300 bg-white/95 p-2.5 text-slate-800 shadow-2xl backdrop-blur"
                        aria-label="T-Box Proposal 미리보기"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <strong className="text-[10px] text-violet-950">
                            Proposal · {proposal.elements.length} elements
                          </strong>
                          <button
                            type="button"
                            className="rounded p-1 text-slate-500 hover:bg-slate-100"
                            aria-label="Proposal 미리보기 닫기"
                            onClick={() => {
                              setProposal(undefined)
                              setProposalExcluded(new Set())
                              setProposalOverrides({})
                            }}
                          >
                            <X size={12} aria-hidden="true" />
                          </button>
                        </div>
                        <p className="my-1 text-[9px] leading-4 text-slate-500">
                          불필요한 요소를 제외한 뒤 적용하세요. 정본은 적용 전까지 바뀌지 않습니다.
                        </p>
                        <ul className="m-0 grid max-h-48 list-none gap-1 overflow-auto p-0">
                          {proposal.elements.map((item) => (
                            <li key={item.stable_element_id}>
                              <label className="flex items-center gap-1 rounded border border-slate-200 px-2 py-1 text-[9px]">
                                <input
                                  type="checkbox"
                                  checked={!proposalExcluded.has(item.stable_element_id)}
                                  onChange={(event) => {
                                    setProposalExcluded((current) => {
                                      const next = new Set(current)
                                      if (event.target.checked) next.delete(item.stable_element_id)
                                      else next.add(item.stable_element_id)
                                      return next
                                    })
                                  }}
                                />
                                <input
                                  aria-label={`${item.display_name} Proposal 이름`}
                                  className="input min-w-0 flex-1 px-1.5 py-0.5 text-[9px] font-bold"
                                  value={proposalOverrides[item.stable_element_id]?.display_name
                                    ?? item.display_name}
                                  disabled={proposalExcluded.has(item.stable_element_id)}
                                  onChange={(event) => {
                                    const displayName = event.target.value
                                    setProposalOverrides((current) => ({
                                      ...current,
                                      [item.stable_element_id]: {
                                        canonical_name: schemaIdentifier(
                                          displayName,
                                          item.kind === 'PROPERTY' ? 'Property' : item.kind === 'RELATION'
                                            ? 'Relation'
                                            : 'Class',
                                        ) || item.canonical_name,
                                        display_name: displayName,
                                        data_type: current[item.stable_element_id]?.data_type
                                          ?? item.data_type,
                                      },
                                    }))
                                  }}
                                />
                                <span className="ml-auto text-[8px] text-slate-400">{item.kind}</span>
                                {item.kind === 'PROPERTY' && (
                                  <select
                                    aria-label={`${item.display_name} Proposal 타입`}
                                    className="input w-[68px] px-1 py-0.5 text-[8px]"
                                    value={proposalOverrides[item.stable_element_id]?.data_type
                                      ?? item.data_type
                                      ?? 'STRING'}
                                    disabled={proposalExcluded.has(item.stable_element_id)}
                                    onChange={(event) => {
                                      setProposalOverrides((current) => ({
                                        ...current,
                                        [item.stable_element_id]: {
                                          canonical_name: current[item.stable_element_id]?.canonical_name
                                            ?? item.canonical_name,
                                          display_name: current[item.stable_element_id]?.display_name
                                            ?? item.display_name,
                                          data_type: event.target.value,
                                        },
                                      }))
                                    }}
                                  >
                                    {propertyDataTypes.map((value) => (
                                      <option key={value}>{value}</option>
                                    ))}
                                  </select>
                                )}
                              </label>
                            </li>
                          ))}
                        </ul>
                        <div className="mt-2 flex gap-1">
                          <button
                            type="button"
                            className="button flex-1 justify-center py-1 text-[9px]"
                            disabled={
                              proposalExcluded.size === proposal.elements.length
                              || !proposalOverridesValid
                              || working
                            }
                            onClick={() => {
                              if (proposal.conflicts.length > 0) setConflictOpen(true)
                              else void applyProposal(proposal, 'KEEP_ORIGINAL')
                            }}
                          >
                            {proposal.mode === 'APPEND_LAYER' ? '새 블록 생성' : '현재 블록 적용'}
                          </button>
                        </div>
                      </aside>
                    )}
                    <ReactFlow<CanvasNode, SchemaEdge>
                      aria-label="T-Box 그래프 캔버스"
                      nodes={renderedNodes}
                      edges={edges}
                      nodeTypes={schemaNodeTypes}
                      onNodesChange={handleNodesChange}
                      onEdgesChange={handleEdgesChange}
                      onConnect={connect}
                      onReconnect={reconnect}
                      onNodeClick={(_, node) => {
                        if (node.type === 'schemaClass') setSelectedElementId(node.id)
                      }}
                      onEdgeClick={(_, edge) => setSelectedElementId(edge.id)}
                      onPaneClick={() => {
                        setSelectedElementId('')
                        setOpenEditor('')
                      }}
                      nodesDraggable={!locked && !working}
                      nodesConnectable={!locked && !working}
                      edgesReconnectable={!locked && !working}
                      connectionMode={ConnectionMode.Loose}
                      deleteKeyCode={null}
                      viewport={viewport}
                      onViewportChange={setViewport}
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
                      계층선 이름 편집 가능 · PostgreSQL Class parent 정본
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
            <button
              type="button"
              className="rounded-enterprise border border-slate-200 p-3 text-left hover:border-enterprise-blue hover:bg-blue-50"
              onClick={() => void createBlock(directBlockOption)}
            >
              <Plus size={16} className="text-enterprise-blue" aria-hidden="true" />
              <strong className="mt-2 block text-xs text-navy-900">
                통합 직접 정의 블록
              </strong>
              <span className="mt-1 block text-[11px] leading-4 text-slate-500">
                직접 편집, 문서, 카탈로그 Proposal을 한 레이어에서 누적합니다.
              </span>
            </button>
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
        open={catalogOpen}
        title="DB 카탈로그에서 T-Box 제안"
        description="현재 사용자의 권한과 지식 자산 보안등급 범위 안에서만 Dataset과 컬럼을 조회합니다."
        onRequestClose={() => {
          if (!catalogLoading && !working) setCatalogOpen(false)
        }}
        footer={<>
          <button
            type="button"
            className="button button-secondary"
            disabled={working}
            onClick={() => setCatalogOpen(false)}
          >
            취소
          </button>
          <button
            type="button"
            className="button button-secondary"
            disabled={
              !selectedCatalog
              || selectedCatalogFields.size === 0
              || selectedCatalogFields.size > 100
              || working
            }
            onClick={() => void proposeSelectedCatalog('APPEND_LAYER')}
          >
            새 블록 Proposal
          </button>
          <button
            type="button"
            className="button"
            disabled={
              !selectedCatalog
              || selectedCatalogFields.size === 0
              || selectedCatalogFields.size > 100
              || working
            }
            onClick={() => void proposeSelectedCatalog('MERGE_INTO_CURRENT')}
          >
            현재 블록 Proposal
          </button>
        </>}
      >
        <div className="grid gap-3">
          <form
            className="flex gap-2"
            onSubmit={(event) => {
              event.preventDefault()
              void searchCatalog()
            }}
          >
            <div className="grid min-w-0 flex-1 gap-2 md:grid-cols-[minmax(0,2fr)_minmax(160px,1fr)]">
              <input
                aria-label="T-Box 카탈로그 검색어"
                className="input min-w-0"
                value={catalogQuery}
                maxLength={200}
                placeholder="테이블명, 컬럼, 태그, 용어, 설명 검색"
                onChange={(event) => setCatalogQuery(event.target.value)}
              />
              <input
                aria-label="T-Box 카탈로그 도메인 필터"
                className="input min-w-0"
                value={catalogDomain}
                maxLength={1000}
                placeholder="도메인 필터 (선택)"
                onChange={(event) => setCatalogDomain(event.target.value)}
              />
            </div>
            <button type="submit" className="button" disabled={catalogLoading}>
              <Search size={13} aria-hidden="true" />
              검색
            </button>
          </form>
          <fieldset className="flex flex-wrap gap-2 rounded border border-slate-200 px-3 py-2">
            <legend className="px-1 text-[10px] font-black text-slate-600">검색 범위</legend>
            {catalogSearchFieldOptions.map(([value, label]) => (
              <label key={value} className="flex items-center gap-1 text-[10px] text-slate-600">
                <input
                  type="checkbox"
                  checked={catalogSearchFields.has(value)}
                  onChange={(event) => {
                    setCatalogSearchFields((current) => {
                      const next = new Set(current)
                      if (event.target.checked) next.add(value)
                      else if (next.size > 1) next.delete(value)
                      return next
                    })
                  }}
                />
                {label}
              </label>
            ))}
          </fieldset>
          <div className="grid max-h-[48vh] gap-3 overflow-auto md:grid-cols-[220px_minmax(0,1fr)]">
            <ul className="m-0 grid content-start gap-1 list-none p-0">
              {catalogResults.length === 0 && (
                <li className="rounded border border-dashed border-slate-300 p-4 text-center text-xs text-slate-500">
                  검색 결과가 없습니다.
                </li>
              )}
              {catalogResults.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    className={`w-full rounded border p-2 text-left ${
                      selectedCatalog?.id === item.id
                        ? 'border-enterprise-blue bg-blue-50'
                        : 'border-slate-200 hover:bg-slate-50'
                    }`}
                    disabled={catalogDetailLoading}
                    onClick={() => void selectCatalogSource(item)}
                  >
                    <strong className="block truncate text-xs text-navy-900">{item.name}</strong>
                    <span className="mt-1 block truncate text-[9px] text-slate-500">
                      {[item.platform, item.database_name, item.schema_name]
                        .filter(Boolean)
                        .join(' / ')}
                    </span>
                    <span className="mt-1 block truncate text-[9px] text-slate-500">
                      {[item.domain, ...(item.tags ?? []).slice(0, 2)].filter(Boolean).join(' · ')}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            <section className="rounded border border-slate-200 p-3">
              <h4 className="m-0 text-xs font-black text-navy-900">
                {selectedCatalog?.name ?? 'Dataset을 선택하세요'}
              </h4>
              {selectedCatalog && (
                <>
                  <p className="my-2 text-[10px] leading-4 text-slate-500">
                    Source {selectedCatalog.source_version} · Projection{' '}
                    {selectedCatalog.projection_source_version}
                  </p>
                  {selectedCatalogFields.size > 100 && (
                    <p role="alert" className="text-[10px] text-red-700">
                      Typed Proposal 입력은 최대 100개 컬럼입니다. 선택을 줄여 주세요.
                    </p>
                  )}
                  {catalogDetailLoading && (
                    <p role="status" className="text-[10px] text-enterprise-blue">
                      실제 카탈로그 컬럼을 조회하는 중…
                    </p>
                  )}
                  <div className="grid max-h-64 gap-1 overflow-auto">
                    {selectedCatalog.field_paths.map((field) => (
                      <label
                        key={field}
                        className="flex items-center gap-2 rounded px-2 py-1 text-[10px] hover:bg-slate-50"
                      >
                        <input
                          type="checkbox"
                          checked={selectedCatalogFields.has(field)}
                          onChange={(event) => {
                            setSelectedCatalogFields((current) => {
                              const next = new Set(current)
                              if (event.target.checked) next.add(field)
                              else next.delete(field)
                              return next
                            })
                          }}
                        />
                        <span className="truncate">{field}</span>
                      </label>
                    ))}
                  </div>
                </>
              )}
            </section>
          </div>
        </div>
      </Dialog>

      <Dialog
        open={documentCapabilityOpen}
        title="문서 기반 T-Box Proposal"
        description="파일은 filefolder Object Storage에 create-only로 저장되고, 문서 내용은 A-Box가 아닌 Typed T-Box Proposal로만 분석됩니다."
        onRequestClose={() => {
          if (!working) setDocumentCapabilityOpen(false)
        }}
        footer={<>
          <button
            type="button"
            className="button button-secondary"
            disabled={working}
            onClick={() => setDocumentCapabilityOpen(false)}
          >
            {documentWorkflow === 'COMPLETE' ? '제안 확인' : '취소'}
          </button>
          <button
            type="button"
            className="button"
            disabled={!documentFile || working || documentWorkflow === 'COMPLETE'}
            onClick={() => void requestDocumentProposal()}
          >
            <FileUp size={13} aria-hidden="true" />
            업로드 및 분석
          </button>
        </>}
      >
        <div className="grid gap-4">
          <label className="grid gap-1 text-xs font-bold text-slate-700">
            분석 파일
            <input
              aria-label="T-Box 분석 파일"
              className="input bg-white"
              type="file"
              accept=".pdf,.csv,.txt,.xlsx,.docx,.pptx,.html,.htm,.xml,.json"
              disabled={working}
              onChange={(event) => {
                setDocumentFile(event.target.files?.[0])
                setDocumentWorkflow('IDLE')
                setDocumentWorkflowError('')
              }}
            />
            <span className="text-[10px] font-medium leading-4 text-slate-500">
              PDF, CSV, TXT, XLSX, DOCX, PPTX, HTML, XML, JSON · 최대 10 MiB · DOC/XLS 제외
            </span>
          </label>
          <fieldset className="grid gap-2 rounded border border-slate-200 p-3">
            <legend className="px-1 text-xs font-black text-navy-900">반영 방식</legend>
            <label className="flex items-start gap-2 text-xs text-slate-700">
              <input
                type="radio"
                name="document-proposal-mode"
                checked={documentProposalMode === 'MERGE_INTO_CURRENT'}
                disabled={working}
                onChange={() => setDocumentProposalMode('MERGE_INTO_CURRENT')}
              />
              <span><strong>현재 블록 Proposal</strong> · 기본 Keep Original 병합</span>
            </label>
            <label className="flex items-start gap-2 text-xs text-slate-700">
              <input
                type="radio"
                name="document-proposal-mode"
                checked={documentProposalMode === 'APPEND_LAYER'}
                disabled={working}
                onChange={() => setDocumentProposalMode('APPEND_LAYER')}
              />
              <span><strong>새 블록 Proposal</strong> · 승인 시 최신 레이어 추가</span>
            </label>
          </fieldset>
          <ol
            className="m-0 grid list-none gap-2 p-0"
            aria-label="문서 T-Box 분석 진행 상태"
          >
            {[
              'Object Storage 저장 및 문서 파싱',
              '승인된 Schema Assistant로 T-Box 추출',
              'Typed AST 기본값 보정 및 무결성 검증(1회)',
              '검증 증거가 포함된 Proposal 준비',
            ].map((label, index) => {
              const completed = documentWorkflow === 'COMPLETE'
              const active = documentWorkflow === 'PARSING' && index === 0
              const failed = documentWorkflow === 'FAILED' && index === 0
              return (
                <li
                  key={label}
                  className={`flex items-center gap-3 rounded border px-3 py-2 text-xs font-bold ${
                    completed
                      ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
                      : active
                        ? 'border-blue-300 bg-blue-50 text-blue-800'
                        : failed
                          ? 'border-red-300 bg-red-50 text-red-800'
                          : 'border-slate-200 bg-slate-50 text-slate-500'
                  }`}
                >
                  <span className="grid size-5 shrink-0 place-items-center rounded-full bg-white text-[10px] shadow-sm">
                    {completed ? '✓' : index + 1}
                  </span>
                  {label}
                  {active && <span className="ml-auto animate-pulse text-[10px]">실행 중</span>}
                </li>
              )
            })}
          </ol>
          {documentWorkflowError && (
            <p role="alert" className="m-0 rounded border border-red-200 bg-red-50 p-3 text-xs text-red-800">
              {documentWorkflowError}
            </p>
          )}
          {documentWorkflow === 'COMPLETE' && (
            <p role="status" className="m-0 rounded border border-violet-200 bg-violet-50 p-3 text-xs leading-5 text-violet-900">
              제안이 캔버스 우측의 임시 Proposal 패널에 표시되었습니다. 요소를 제외하거나
              보완한 뒤 적용해야 PostgreSQL Draft 정본이 변경됩니다.
            </p>
          )}
        </div>
      </Dialog>

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
