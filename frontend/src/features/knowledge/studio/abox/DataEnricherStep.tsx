import { useCallback, useEffect, useMemo, useState } from 'react'
import { CheckCircle2, Database, Link2, Save, Search } from 'lucide-react'
import { ApiError, type ApiClient } from '../../../../api/client'
import { Dialog } from '../../../../components/common/Dialog'
import {
  FlowCanvas,
  type FlowCanvasEdge,
  type FlowCanvasNode,
} from '../../../../components/common/FlowCanvas'
import {
  getKnowledgeStudioABox,
  getKnowledgeStudioSource,
  newKnowledgeStudioIdempotencyKey,
  saveKnowledgeStudioBinding,
  searchKnowledgeStudioSources,
  type KnowledgeStudioABox,
  type KnowledgeStudioBinding,
  type KnowledgeStudioDraft,
  type KnowledgeStudioMappingRuleInput,
  type KnowledgeStudioSourceDataset,
  type KnowledgeStudioTBoxElement,
} from '../knowledgeStudioApi'

interface LocalBindingDraft {
  targetStableElementId: string
  source: KnowledgeStudioSourceDataset
  rules: KnowledgeStudioMappingRuleInput[]
}

interface DataEnricherStepProps {
  client: ApiClient
  draftId: string
  onDraftUpdate: (draft: KnowledgeStudioDraft, etag: string) => void
}

function sourceLocation(source: KnowledgeStudioSourceDataset): string {
  return [source.platform, source.database_name, source.schema_name]
    .filter(Boolean)
    .join(' · ')
}

function rulesForForm(
  targetId: string,
  subjectField: string,
  propertyFields: Record<string, string>,
): KnowledgeStudioMappingRuleInput[] {
  const rules: KnowledgeStudioMappingRuleInput[] = []
  if (subjectField) {
    rules.push({
      method: 'SUBJECT_ID',
      source_field_path: subjectField,
      target_stable_element_id: targetId,
    })
  }
  for (const [propertyId, fieldPath] of Object.entries(propertyFields)) {
    if (fieldPath) {
      rules.push({
        method: 'PROPERTY',
        source_field_path: fieldPath,
        target_stable_element_id: propertyId,
      })
    }
  }
  return rules
}

export function DataEnricherStep({
  client,
  draftId,
  onDraftUpdate,
}: DataEnricherStepProps) {
  const [abox, setAbox] = useState<KnowledgeStudioABox>()
  const [etag, setEtag] = useState<string>()
  const [selectedTargetId, setSelectedTargetId] = useState<string>()
  const [sourceQuery, setSourceQuery] = useState('')
  const [sourceResults, setSourceResults] = useState<KnowledgeStudioSourceDataset[]>([])
  const [selectedSource, setSelectedSource] = useState<KnowledgeStudioSourceDataset>()
  const [selectedSourceStale, setSelectedSourceStale] = useState(false)
  const [subjectField, setSubjectField] = useState('')
  const [propertyFields, setPropertyFields] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [sourceLoading, setSourceLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState('Accepted T-Box와 Binding Draft를 불러오고 있습니다.')
  const [conflict, setConflict] = useState<LocalBindingDraft>()

  const applyAbox = useCallback((
    next: KnowledgeStudioABox,
    responseEtag: string,
  ) => {
    setAbox(next)
    setEtag(responseEtag)
    onDraftUpdate(next.draft, responseEtag)
  }, [onDraftUpdate])

  const loadAbox = useCallback(async () => {
    const response = await getKnowledgeStudioABox(client, draftId)
    applyAbox(response.data, response.etag ?? '')
    return response
  }, [applyAbox, client, draftId])

  useEffect(() => {
    let active = true
    void loadAbox()
      .then(() => {
        if (active) setStatus('노드를 선택하여 물리 Dataset을 연결하세요.')
      })
      .catch((error: unknown) => {
        if (active) {
          setStatus(error instanceof Error ? error.message : 'Data Enricher를 불러오지 못했습니다.')
        }
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [loadAbox])

  const elements = useMemo(
    () => abox?.tbox_elements ?? [],
    [abox?.tbox_elements],
  )
  const classes = useMemo(
    () => elements.filter((element) => element.kind === 'CLASS'),
    [elements],
  )
  const propertiesByClass = useMemo(() => {
    const values = new Map<string, KnowledgeStudioTBoxElement[]>()
    for (const element of elements) {
      if (element.kind !== 'PROPERTY' || !element.parent_stable_element_id) continue
      values.set(element.parent_stable_element_id, [
        ...(values.get(element.parent_stable_element_id) ?? []),
        element,
      ])
    }
    return values
  }, [elements])
  const bindingByTarget = useMemo(
    () => new Map((abox?.bindings ?? []).map((binding) => [
      binding.target_stable_element_id,
      binding,
    ])),
    [abox?.bindings],
  )
  const flowNodes = useMemo<FlowCanvasNode[]>(() => classes.map((element, index) => {
    const binding = bindingByTarget.get(element.stable_element_id)
    const propertyCount = propertiesByClass.get(element.stable_element_id)?.length ?? 0
    return {
      id: element.stable_element_id,
      label: element.display_name,
      subtitle: `${propertyCount} properties · ${
        binding?.rules.length ? `Mapped · ${binding.readiness}` : 'Unbound'
      }`,
      kind: binding?.rules.length ? 'target' : 'neutral',
      x: 40 + (index % 4) * 220,
      y: 45 + Math.floor(index / 4) * 140,
    }
  }), [bindingByTarget, classes, propertiesByClass])
  const flowEdges = useMemo<FlowCanvasEdge[]>(() => elements
    .filter((element) => (
      element.kind === 'RELATION'
      && element.source_stable_element_id
      && element.target_stable_element_id
    ))
    .map((element) => ({
      id: element.stable_element_id,
      source: element.source_stable_element_id ?? '',
      target: element.target_stable_element_id ?? '',
      label: element.display_name,
    })), [elements])
  const selectedTarget = classes.find(
    (element) => element.stable_element_id === selectedTargetId,
  )
  const selectedProperties = selectedTargetId
    ? propertiesByClass.get(selectedTargetId) ?? []
    : []

  const hydrateBindingForm = useCallback(async (
    targetId: string,
    binding?: KnowledgeStudioBinding,
  ) => {
    setSelectedTargetId(targetId)
    setSourceQuery('')
    setSourceResults([])
    if (!binding) {
      setSelectedSource(undefined)
      setSelectedSourceStale(false)
      setSubjectField('')
      setPropertyFields({})
      return
    }
    setSourceLoading(true)
    try {
      const detail = await getKnowledgeStudioSource(client, draftId, binding.source_asset_id)
      setSelectedSource(detail.dataset)
      setSelectedSourceStale(Boolean(detail.stale_at))
      setSubjectField(
        binding.rules.find((rule) => rule.method === 'SUBJECT_ID')?.source_field_path ?? '',
      )
      setPropertyFields(Object.fromEntries(
        binding.rules
          .filter((rule) => rule.method === 'PROPERTY')
          .map((rule) => [rule.target_stable_element_id, rule.source_field_path]),
      ))
    } catch (error) {
      setSelectedSource(undefined)
      setSelectedSourceStale(false)
      setStatus(error instanceof Error ? error.message : 'Binding Dataset을 불러오지 못했습니다.')
    } finally {
      setSourceLoading(false)
    }
  }, [client, draftId])

  useEffect(() => {
    if (!selectedTargetId) return
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      setSourceLoading(true)
      void searchKnowledgeStudioSources(
        client,
        draftId,
        sourceQuery,
        controller.signal,
      )
        .then((page) => setSourceResults(page.items))
        .catch((error: unknown) => {
          if (!controller.signal.aborted) {
            setStatus(error instanceof Error ? error.message : 'Dataset 검색에 실패했습니다.')
          }
        })
        .finally(() => {
          if (!controller.signal.aborted) setSourceLoading(false)
        })
    }, 250)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [client, draftId, selectedTargetId, sourceQuery])

  const selectSource = async (source: KnowledgeStudioSourceDataset) => {
    setSourceLoading(true)
    try {
      const detail = await getKnowledgeStudioSource(client, draftId, source.id)
      setSelectedSource(detail.dataset)
      setSelectedSourceStale(Boolean(detail.stale_at))
      setSubjectField('')
      setPropertyFields({})
      setStatus(
        detail.stale_at
          ? 'Dataset 상세가 오래되어 새 Binding 저장이 제한됩니다.'
          : `${detail.dataset.field_paths.length}개 컬럼을 확인했습니다.`,
      )
    } catch (error) {
      setSelectedSource(undefined)
      setStatus(error instanceof Error ? error.message : 'Dataset 컬럼을 불러오지 못했습니다.')
      setSelectedSourceStale(false)
    } finally {
      setSourceLoading(false)
    }
  }

  const persist = async (local: LocalBindingDraft, versionEtag: string) => {
    setSaving(true)
    try {
      const response = await saveKnowledgeStudioBinding(
        client,
        draftId,
        local.targetStableElementId,
        local.source,
        local.rules,
        versionEtag,
        newKnowledgeStudioIdempotencyKey(),
      )
      if (!response.etag) return false
      setEtag(response.etag)
      onDraftUpdate(response.data.draft, response.etag)
      setAbox((current) => current
        ? {
            ...current,
            draft: response.data.draft,
            bindings: [
              ...current.bindings.filter((binding) => (
                binding.target_stable_element_id
                !== response.data.binding.target_stable_element_id
              )),
              response.data.binding,
            ],
          }
        : current)
      setConflict(undefined)
      setStatus(`Binding Draft 저장 완료 · version ${response.data.binding.version}`)
      return true
    } catch (error) {
      if (error instanceof ApiError && error.problem.status === 412) {
        setConflict(local)
        setStatus('다른 세션의 변경사항과 충돌했습니다. 현재 Mapping 입력은 보존됩니다.')
      } else {
        setStatus(error instanceof Error ? error.message : 'Binding Draft 저장에 실패했습니다.')
      }
      return false
    } finally {
      setSaving(false)
    }
  }

  const save = () => {
    if (!selectedTarget || !selectedSource || !etag) return
    const rules = rulesForForm(
      selectedTarget.stable_element_id,
      subjectField,
      propertyFields,
    )
    if (!rules.length) {
      setStatus('SUBJECT ID 또는 Property mapping을 하나 이상 선택하세요.')
      return
    }
    void persist({
      targetStableElementId: selectedTarget.stable_element_id,
      source: selectedSource,
      rules,
    }, etag)
  }

  const reloadLatest = async () => {
    if (!conflict) return
    setSaving(true)
    try {
      const response = await loadAbox()
      const binding = response.data.bindings.find((item) => (
        item.target_stable_element_id === conflict.targetStableElementId
      ))
      await hydrateBindingForm(conflict.targetStableElementId, binding)
      setConflict(undefined)
      setStatus(`최신 서버 Draft version ${response.data.draft.version}을 불러왔습니다.`)
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '최신 A-Box Draft를 불러오지 못했습니다.')
    } finally {
      setSaving(false)
    }
  }

  const overwriteLatest = async () => {
    if (!conflict) return
    setSaving(true)
    try {
      const latest = await loadAbox()
      if (!latest.etag) return
      const local = conflict
      setConflict(undefined)
      setSaving(false)
      await persist(local, latest.etag)
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '최신 ETag를 확인하지 못했습니다.')
      setSaving(false)
    }
  }

  if (loading) {
    return <section className="grid min-h-[420px] place-items-center rounded-enterprise border border-slate-300 bg-white text-sm text-slate-500">
      Data Enricher 계약을 확인하고 있습니다.
    </section>
  }

  return <div className="grid gap-4">
    <section className="rounded-enterprise border border-slate-300 bg-white p-4">
      <header className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <span className="text-[10px] font-black tracking-[.14em] text-enterprise-blue uppercase">
            Step 3 · A-Box Mapping
          </span>
          <h2 className="my-1 text-lg font-black text-navy-900">Data Enricher</h2>
          <p className="m-0 text-xs leading-5 text-slate-500">
            Accepted T-Box는 읽기 전용입니다. 초록 노드는 Mapping Draft가 하나 이상 저장된 상태이며
            ingestion 또는 publication 완료를 뜻하지 않습니다.
          </p>
        </div>
        <div className="flex gap-2 text-[11px]">
          <span className="badge badge-soft">Mapping: DRAFT</span>
          <span className="badge badge-soft">Ingestion: NOT_RUN</span>
        </div>
      </header>
      <FlowCanvas
        ariaLabel="Data Enricher accepted T-Box"
        nodes={flowNodes}
        edges={flowEdges}
        height={420}
        locked
        emptyTitle="Accepted T-Box 요소가 없습니다."
        emptyDescription="Step 2에서 Class 또는 Relation을 승인한 뒤 Data Enricher를 열어야 합니다."
        onNodeActivate={(nodeId) => {
          void hydrateBindingForm(nodeId, bindingByTarget.get(nodeId))
        }}
      />
    </section>

    {selectedTarget
      ? <section aria-label="Data Binding Panel" className="grid gap-4 rounded-enterprise border border-slate-300 bg-white p-4 lg:grid-cols-[minmax(260px,.8fr)_minmax(420px,1.2fr)]">
          <div className="grid content-start gap-3">
            <header>
              <span className="text-[10px] font-black tracking-[.12em] text-enterprise-blue uppercase">
                Selected class
              </span>
              <h3 className="my-1 text-base font-black text-navy-900">{selectedTarget.display_name}</h3>
              <p className="m-0 text-xs text-slate-500">
                {selectedProperties.length} properties · {bindingByTarget.has(selectedTarget.stable_element_id)
                  ? 'Mapped Draft'
                  : 'Unbound'}
              </p>
            </header>
            <label className="grid gap-1 text-xs font-black text-navy-900">
              Dataset 검색
              <span className="relative">
                <Search className="absolute top-2.5 left-2.5 text-slate-400" size={14} />
                <input
                  className="w-full pl-8"
                  type="search"
                  value={sourceQuery}
                  onChange={(event) => setSourceQuery(event.target.value)}
                  placeholder="Table 또는 Dataset 이름"
                  maxLength={200}
                />
              </span>
            </label>
            <div className="grid max-h-64 gap-2 overflow-y-auto" aria-label="Dataset 검색 결과">
              {sourceLoading && <p className="m-0 text-xs text-slate-500">Dataset 확인 중…</p>}
              {!sourceLoading && sourceResults.length === 0 && (
                <p className="m-0 text-xs text-slate-500">권한 범위에 검색 가능한 Dataset이 없습니다.</p>
              )}
              {sourceResults.map((source) => (
                <button
                  key={source.id}
                  type="button"
                  className={`rounded-enterprise border p-3 text-left ${
                    selectedSource?.id === source.id
                      ? 'border-enterprise-blue bg-blue-50'
                      : 'border-slate-200 bg-white'
                  }`}
                  onClick={() => void selectSource(source)}
                >
                  <span className="block text-xs font-black text-navy-900">{source.name}</span>
                  <span className="mt-1 block text-[10px] text-slate-500">
                    {source.asset_type} · {sourceLocation(source) || 'Catalog projection'}
                  </span>
                </button>
              ))}
            </div>
          </div>

          <div className="grid content-start gap-3">
            {selectedSource
              ? <>
                  <header className="flex items-start justify-between gap-3">
                    <div>
                      <span className="text-[10px] font-black tracking-[.12em] text-enterprise-blue uppercase">
                        Property mapping
                      </span>
                      <h3 className="my-1 text-sm font-black text-navy-900">{selectedSource.name}</h3>
                      <p className="m-0 text-[11px] text-slate-500">
                        source version {selectedSource.source_version.slice(0, 12)}…
                      </p>
                    </div>
                    <span className="badge badge-soft">
                      <Database size={12} /> {selectedSource.field_paths.length} columns
                    </span>
                  </header>
                  <div className="overflow-x-auto rounded-enterprise border border-slate-200">
                    <table className="w-full text-left text-xs">
                      <thead className="bg-slate-50 text-[10px] tracking-wide text-slate-500 uppercase">
                        <tr>
                          <th className="p-2">T-Box target</th>
                          <th className="p-2">Mapping</th>
                          <th className="p-2">Dataset column</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr className="border-t border-slate-200">
                          <td className="p-2 font-black text-navy-900">{selectedTarget.display_name}</td>
                          <td className="p-2"><span className="badge badge-soft">SUBJECT_ID</span></td>
                          <td className="p-2">
                            <select
                              aria-label={`${selectedTarget.display_name} SUBJECT ID column`}
                              value={subjectField}
                              onChange={(event) => setSubjectField(event.target.value)}
                            >
                              <option value="">선택 안 함</option>
                              {selectedSource.field_paths.map((field) => (
                                <option key={field}>{field}</option>
                              ))}
                            </select>
                          </td>
                        </tr>
                        {selectedProperties.map((property) => (
                          <tr key={property.stable_element_id} className="border-t border-slate-200">
                            <td className="p-2 font-black text-navy-900">
                              {property.display_name}
                              <small className="ml-1 font-normal text-slate-500">
                                {property.data_type}
                              </small>
                            </td>
                            <td className="p-2"><span className="badge badge-soft">PROPERTY</span></td>
                            <td className="p-2">
                              <select
                                aria-label={`${property.display_name} source column`}
                                value={propertyFields[property.stable_element_id] ?? ''}
                                onChange={(event) => setPropertyFields((current) => ({
                                  ...current,
                                  [property.stable_element_id]: event.target.value,
                                }))}
                              >
                                <option value="">선택 안 함</option>
                                {selectedSource.field_paths.map((field) => (
                                  <option key={field}>{field}</option>
                                ))}
                              </select>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-3">
                    <p className="m-0 flex items-center gap-1 text-[11px] text-slate-500">
                      <Link2 size={13} /> IDENTITY transform만 허용되며 실제 Row는 아직 적재되지 않습니다.
                    </p>
                    <button
                      type="button"
                      className="button"
                      disabled={saving || !etag || selectedSourceStale}
                      onClick={save}
                    >
                      {saving ? <Database size={14} /> : <Save size={14} />}
                      {saving ? '저장 중…' : 'Binding Draft 저장'}
                    </button>
                  </footer>
                </>
              : <div className="grid min-h-72 place-items-center rounded-enterprise border border-dashed border-slate-300 bg-slate-50 p-6 text-center">
                  <div>
                    <Database className="mx-auto mb-2 text-slate-400" size={30} />
                    <p className="m-0 text-sm font-black text-navy-900">Dataset을 선택하세요.</p>
                    <p className="mt-1 text-xs text-slate-500">컬럼 상세를 서버에서 검증한 뒤 Mapping 표가 열립니다.</p>
                  </div>
                </div>}
          </div>
        </section>
      : classes.length > 0 && (
          <section className="grid min-h-32 place-items-center rounded-enterprise border border-dashed border-slate-300 bg-white p-5 text-center">
            <div>
              <CheckCircle2 className="mx-auto mb-2 text-enterprise-blue" size={24} />
              <p className="m-0 text-sm font-black text-navy-900">T-Box 노드를 선택하세요.</p>
              <p className="mt-1 text-xs text-slate-500">선택한 Class의 Data Binding Panel이 여기에 열립니다.</p>
            </div>
          </section>
        )}
    <p role="status" className="m-0 text-xs text-slate-500">{status}</p>

    <Dialog
      open={Boolean(conflict)}
      title="A-Box 동시 편집 충돌"
      description="다른 사용자에 의해 Binding Draft가 변경되었습니다. 현재 Mapping 입력은 아직 삭제되지 않았습니다."
      onRequestClose={() => undefined}
      footer={<>
        <button type="button" className="button button-secondary" disabled={saving} onClick={() => void reloadLatest()}>
          최신 버전 불러오기
        </button>
        <button type="button" className="button" disabled={saving} onClick={() => void overwriteLatest()}>
          내 Mapping으로 덮어쓰기
        </button>
      </>}
    >
      <p className="m-0 text-sm leading-6 text-slate-600">
        덮어쓰기는 서버의 최신 ETag를 다시 읽은 뒤 보존된 typed mapping을 새 version fence로
        저장합니다. T-Box와 다른 노드의 Binding은 변경하지 않습니다.
      </p>
    </Dialog>
  </div>
}
