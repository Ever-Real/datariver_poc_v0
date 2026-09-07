import { useState } from 'react'
import { Pencil, Plus, Sparkles, Trash2 } from 'lucide-react'
import {
  knowledgeStudioPropertyDataTypes,
  type KnowledgeStudioTBoxBlock,
  type KnowledgeStudioTBoxElement,
} from '../knowledgeStudioApi'

interface ElementInspectorProps {
  element: KnowledgeStudioTBoxElement | undefined
  elements: KnowledgeStudioTBoxElement[]
  blocks: KnowledgeStudioTBoxBlock[]
  warnings: string[]
  locked: boolean
  working: boolean
  onUpdate: (id: string, patch: Partial<KnowledgeStudioTBoxElement>) => void
  onDelete: (id: string) => void
  onAddProperty: (ownerId: string, name: string) => void
  onSelect: (id: string) => void
}

const sourceLabels: Record<KnowledgeStudioTBoxBlock['kind'], string> = {
  DIRECT: '사용자 직접 정의',
  DOCUMENT_SCHEMA: '파일 제안',
  CATALOG_METADATA: 'DataHub 동기화',
  ASSET_RELEASE: '다른 Asset import',
  LLM_ASSISTANT: 'AI 제안',
}

export function ElementInspector({
  element,
  elements,
  blocks,
  warnings,
  locked,
  working,
  onUpdate,
  onDelete,
  onAddProperty,
  onSelect,
}: ElementInspectorProps) {
  const [propertyName, setPropertyName] = useState('')
  if (!element) {
    return (
      <aside className="order-3 flex min-w-0 flex-col rounded-enterprise border border-slate-300 bg-slate-50 p-4 text-center text-xs text-slate-500 xl:col-start-4 xl:row-span-2">
        <p className="m-0">Class, Property 또는 Relation을 선택하면 상세 속성과 검증 결과를 편집할 수 있습니다.</p>
        {warnings.length > 0 && (
          <section className="mt-4 rounded border border-red-300 bg-red-50 p-2 text-left text-[10px] text-red-800" role="alert">
            <strong>전체 검증 경고</strong>
            <ul className="mb-0 mt-1 list-disc pl-4">
            {warnings.map((warning, index) => (
              <li key={`${index}:${warning}`}>{warning}</li>
            ))}
            </ul>
          </section>
        )}
      </aside>
    )
  }

  const disabled = locked || working || element.locked_by_later_block
  const classes = elements.filter((item) => item.kind === 'CLASS')
  const relationProperties = element.kind === 'RELATION'
    ? elements.filter((item) => (
        item.kind === 'PROPERTY'
        && item.owner_relation_stable_element_id === element.stable_element_id
      ))
    : []
  const owner = element.kind === 'PROPERTY'
    ? elements.find((item) => item.stable_element_id === (
        element.parent_stable_element_id ?? element.owner_relation_stable_element_id
      ))
    : undefined
  const block = element.block_id
    ? blocks.find((item) => item.id === element.block_id)
    : undefined
  const catalogSourced = element.metadata_reference_urn?.startsWith('urn:li:') === true
  const sourceLabel = catalogSourced
    ? 'DataHub Catalog 제안'
    : block ? sourceLabels[block.kind] : '사용자 직접 정의'
  const aiSuggested = block?.kind === 'LLM_ASSISTANT'

  return (
    <aside className="order-3 flex max-h-[760px] min-w-0 flex-col gap-4 overflow-y-auto rounded-enterprise border border-slate-300 bg-white p-4 xl:col-start-4 xl:row-span-2">
      <header className="flex items-start justify-between gap-2 border-b pb-2">
        <div>
          <h3 className="m-0 flex items-center gap-1 text-sm font-black text-slate-800">
            {aiSuggested && <Sparkles size={13} aria-label="AI 제안 요소" />}
            {element.kind === 'CLASS' ? 'Class' : element.kind === 'PROPERTY' ? 'Property' : 'Relation'} 속성
          </h3>
          <p className="mb-0 mt-1 text-[10px] text-slate-500">{sourceLabel}</p>
        </div>
        <code className="max-w-40 break-all rounded bg-slate-100 px-2 py-0.5 text-[9px] text-slate-500">
          {element.stable_element_id}
        </code>
      </header>

      <div className="grid gap-3 text-xs">
        <label className="grid gap-1">
          <span className="font-bold text-slate-700">이름 (Canonical Name)</span>
          <input
            className="input bg-white"
            value={element.canonical_name}
            disabled={disabled}
            onChange={(event) => onUpdate(element.stable_element_id, {
              canonical_name: event.target.value,
            })}
          />
        </label>

        <label className="grid gap-1">
          <span className="font-bold text-slate-700">표시 이름 (Display Name)</span>
          <input
            className="input bg-white"
            value={element.display_name}
            disabled={disabled}
            onChange={(event) => onUpdate(element.stable_element_id, {
              display_name: event.target.value,
            })}
          />
        </label>

        {element.kind === 'CLASS' && (
          <label className="grid gap-1">
            <span className="font-bold text-slate-700">부모 Class</span>
            <select
              className="input bg-white"
              value={element.parent_stable_element_id ?? ''}
              disabled={disabled}
              onChange={(event) => onUpdate(element.stable_element_id, {
                parent_stable_element_id: event.target.value || undefined,
                hierarchy_relation: event.target.value ? 'SUBCLASS_OF' : undefined,
              })}
            >
              <option value="">최상위 Class</option>
              {classes.filter((item) => item.stable_element_id !== element.stable_element_id)
                .map((item) => (
                  <option key={item.stable_element_id} value={item.stable_element_id}>
                    {item.display_name}
                  </option>
                ))}
            </select>
          </label>
        )}

        {element.kind === 'RELATION' && (
          <>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {(['source_stable_element_id', 'target_stable_element_id'] as const).map((field) => (
                <label className="grid gap-1" key={field}>
                  <span className="font-bold text-slate-700">
                    {field === 'source_stable_element_id' ? '이전 Class (Domain)' : '이후 Class (Range)'}
                  </span>
                  <select
                    className="input bg-white"
                    value={element[field] ?? ''}
                    disabled={disabled}
                    onChange={(event) => onUpdate(element.stable_element_id, {
                      [field]: event.target.value || undefined,
                    })}
                  >
                    <option value="">선택</option>
                    {classes.map((item) => (
                      <option key={item.stable_element_id} value={item.stable_element_id}>
                        {item.display_name}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
            </div>
            <label className="grid gap-1">
              <span className="font-bold text-slate-700">방향 (Direction)</span>
              <select
                className="input bg-white"
                value={element.direction ?? 'DIRECTED'}
                disabled={disabled}
                onChange={(event) => onUpdate(element.stable_element_id, {
                  direction: event.target.value as KnowledgeStudioTBoxElement['direction'],
                })}
              >
                <option value="DIRECTED">DIRECTED</option>
                <option value="BIDIRECTED">BIDIRECTED</option>
                <option value="UNDIRECTED">UNDIRECTED</option>
              </select>
            </label>
            <label className="grid gap-1">
              <span className="font-bold text-slate-700">카디널리티 (Cardinality)</span>
              <select
                className="input bg-white"
                value={element.cardinality ?? 'UNSPECIFIED'}
                disabled={disabled}
                onChange={(event) => onUpdate(element.stable_element_id, {
                  cardinality: event.target.value as KnowledgeStudioTBoxElement['cardinality'],
                })}
              >
                <option value="UNSPECIFIED">UNSPECIFIED</option>
                <option value="ONE_TO_ONE">ONE_TO_ONE</option>
                <option value="ONE_TO_MANY">ONE_TO_MANY</option>
                <option value="MANY_TO_ONE">MANY_TO_ONE</option>
                <option value="MANY_TO_MANY">MANY_TO_MANY</option>
              </select>
            </label>
            <section className="rounded border border-slate-200 bg-slate-50 p-2" aria-label="Relation Property 목록">
              <strong className="text-[11px] text-slate-700">Relation Properties</strong>
              {relationProperties.length === 0 ? (
                <p className="my-2 text-[10px] text-slate-500">등록된 Relation Property가 없습니다.</p>
              ) : (
                <ul className="my-2 grid list-none gap-1 p-0">
                  {relationProperties.map((property) => (
                    <li className="flex items-center justify-between gap-2" key={property.stable_element_id}>
                      <button
                        type="button"
                        className="flex min-w-0 items-center gap-1 truncate text-left text-[10px] font-bold text-enterprise-blue"
                        onClick={() => onSelect(property.stable_element_id)}
                      >
                        <Pencil size={10} aria-hidden="true" />
                        {property.display_name} · {property.data_type}
                      </button>
                      <button
                        type="button"
                        className="rounded p-1 text-red-600 hover:bg-red-50"
                        aria-label={`${property.display_name} Relation Property 삭제`}
                        disabled={disabled}
                        onClick={() => onDelete(property.stable_element_id)}
                      >
                        <Trash2 size={10} aria-hidden="true" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <div className="flex gap-1">
                <input
                  className="input min-w-0 flex-1 py-1 text-[10px]"
                  aria-label="새 Relation Property 이름"
                  value={propertyName}
                  placeholder="confidence"
                  disabled={disabled}
                  onChange={(event) => setPropertyName(event.target.value)}
                />
                <button
                  type="button"
                  className="button px-2 py-1"
                  aria-label="Relation Property 추가"
                  disabled={disabled || propertyName.trim().length === 0}
                  onClick={() => {
                    onAddProperty(element.stable_element_id, propertyName)
                    setPropertyName('')
                  }}
                >
                  <Plus size={11} aria-hidden="true" />
                </button>
              </div>
            </section>
          </>
        )}

        {element.kind === 'PROPERTY' && (
          <>
            <p className="m-0 rounded bg-slate-100 p-2 text-[10px] text-slate-600">
              소유 요소: <strong>{owner?.display_name ?? '유효하지 않은 참조'}</strong>
            </p>
            <label className="grid gap-1">
              <span className="font-bold text-slate-700">데이터 타입 (Data Type)</span>
              <select
                className="input bg-white"
                value={element.data_type ?? 'STRING'}
                disabled={disabled}
                onChange={(event) => onUpdate(element.stable_element_id, {
                  data_type: event.target.value,
                })}
              >
                {knowledgeStudioPropertyDataTypes.map((value) => (
                  <option value={value} key={value}>{value}</option>
                ))}
              </select>
            </label>
            <label className="grid gap-1">
              <span className="font-bold text-slate-700">값 개수 (Value Cardinality)</span>
              <select
                className="input bg-white"
                value={element.value_cardinality ?? 'SINGLE'}
                disabled={disabled}
                onChange={(event) => onUpdate(element.stable_element_id, {
                  value_cardinality: event.target.value as KnowledgeStudioTBoxElement['value_cardinality'],
                })}
              >
                <option value="SINGLE">SINGLE</option>
                <option value="MULTI">MULTI</option>
              </select>
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={!element.nullable}
                disabled={disabled}
                onChange={(event) => onUpdate(element.stable_element_id, {
                  nullable: !event.target.checked,
                })}
              />
              <span className="font-bold text-slate-700">필수 항목 (Required)</span>
            </label>
            <label className="grid gap-1">
              <span className="font-bold text-slate-700">단위 (Unit)</span>
              <input
                className="input bg-white"
                value={element.unit ?? ''}
                disabled={disabled}
                onChange={(event) => onUpdate(element.stable_element_id, {
                  unit: event.target.value || undefined,
                })}
              />
            </label>
          </>
        )}

        <label className="grid gap-1">
          <span className="font-bold text-slate-700">설명 (Definition)</span>
          <textarea
            className="input resize-y bg-white text-xs"
            rows={3}
            value={element.definition ?? ''}
            disabled={disabled}
            onChange={(event) => onUpdate(element.stable_element_id, {
              definition: event.target.value || undefined,
            })}
          />
        </label>

        <label className="grid gap-1">
          <span className="font-bold text-slate-700">동의어 (Aliases) - 쉼표로 구분</span>
          <input
            className="input bg-white"
            value={element.aliases.join(', ')}
            disabled={disabled}
            onChange={(event) => onUpdate(element.stable_element_id, {
              aliases: event.target.value.split(',').map((value) => value.trim()).filter(Boolean),
            })}
          />
        </label>

        <section className="rounded border border-blue-200 bg-blue-50 p-2 text-[10px] text-blue-900">
          <strong>Provenance:</strong> {sourceLabel}
          {element.metadata_reference_urn && (
            <code className="mt-1 block break-all">{element.metadata_reference_urn}</code>
          )}
        </section>

        {warnings.length > 0 && (
          <section className="rounded border border-red-300 bg-red-50 p-2 text-[10px] text-red-800" role="alert">
            <strong>검증 경고</strong>
            <ul className="mb-0 mt-1 list-disc pl-4">
            {warnings.map((warning, index) => (
              <li key={`${index}:${warning}`}>{warning}</li>
            ))}
            </ul>
          </section>
        )}

        <div className="mt-2 border-t pt-3">
          <button
            type="button"
            className="button button-danger w-full justify-center"
            disabled={disabled}
            onClick={() => onDelete(element.stable_element_id)}
          >
            <Trash2 size={12} aria-hidden="true" />
            요소 삭제
          </button>
        </div>
      </div>
    </aside>
  )
}
