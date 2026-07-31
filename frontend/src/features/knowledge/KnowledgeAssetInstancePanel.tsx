import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from 'react'
import { Database, FileUp, GitBranchPlus, Plus, Send, Workflow } from 'lucide-react'
import { newIdempotencyKey, type ApiClient } from '../../api/client'
import type {
  KnowledgeAssetOperationalDetail,
  KnowledgeAssetSummary,
  KnowledgeChangeOperationCreate,
  KnowledgeChangeSet,
  KnowledgeChangeSetPublish,
  KnowledgeGraph,
  KnowledgeSnapshot,
} from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { KnowledgeSourceUpload } from './KnowledgeSourceUpload'
import { listAllKnowledgeAssets } from './knowledgeRegistryApi'

type InstanceTab = 'DIRECT' | 'FILE' | 'DATABASE'
type OperationKind = 'NODE' | 'EDGE'
type OperationAction = 'UPSERT' | 'DELETE'

const CLASSIFICATION_LEVEL = {
  PUBLIC: 0,
  INTERNAL: 1,
  CONFIDENTIAL: 2,
  RESTRICTED: 3,
} as const

function instanceLabel(value: unknown, fallback: string): string {
  return typeof value === 'string' || typeof value === 'number'
    ? String(value)
    : fallback
}

function asKnowledgeGraph(asset: KnowledgeAssetSummary): KnowledgeGraph {
  return {
    id: asset.id,
    slug: asset.slug,
    name: asset.name,
    graph_type: asset.graph_type,
    status: asset.status,
    classification: asset.classification,
    domain_id: asset.domain_id ?? undefined,
    domain_name: asset.domain_name ?? undefined,
    active_release_id: asset.active_release_id ?? undefined,
    created_at: asset.created_at,
    updated_at: asset.updated_at,
    version: asset.version,
  }
}

export function KnowledgeAssetInstancePanel({
  client,
  onEditAsset,
}: {
  client: ApiClient
  onEditAsset: (assetId: string) => void
}) {
  const [assets, setAssets] = useState<KnowledgeAssetSummary[]>([])
  const [assetId, setAssetId] = useState('')
  const [detail, setDetail] = useState<KnowledgeAssetOperationalDetail>()
  const [changesets, setChangesets] = useState<KnowledgeChangeSet[]>([])
  const [changesetId, setChangesetId] = useState('')
  const [snapshot, setSnapshot] = useState<KnowledgeSnapshot>()
  const [tab, setTab] = useState<InstanceTab>('DIRECT')
  const [title, setTitle] = useState('')
  const [kind, setKind] = useState<OperationKind>('NODE')
  const [operationAction, setOperationAction] = useState<OperationAction>('UPSERT')
  const [stableEntityId, setStableEntityId] = useState('')
  const [className, setClassName] = useState('')
  const [relationName, setRelationName] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [propertiesText, setPropertiesText] = useState('{}')
  const [sourceNodeId, setSourceNodeId] = useState('')
  const [targetNodeId, setTargetNodeId] = useState('')
  const [sourceRef, setSourceRef] = useState('')
  const [sourceLocator, setSourceLocator] = useState('')
  const [sourceVersion, setSourceVersion] = useState('')
  const [method, setMethod] = useState('MANUAL_ENTRY')
  const [reviewReason, setReviewReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>()
  const [status, setStatus] = useState('')
  const [snapshotNotice, setSnapshotNotice] = useState('')
  const changesetRetryRef = useRef<{ fingerprint: string; key: string } | undefined>(undefined)
  const publishRetryRef = useRef<{ fingerprint: string; key: string } | undefined>(undefined)

  const loadAssets = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    setError(undefined)
    try {
      const items = await listAllKnowledgeAssets(client, signal)
      if (signal?.aborted) return
      setAssets(items)
      setAssetId((current) => (
        current && items.some((item) => item.id === current)
          ? current
          : items[0]?.id ?? ''
      ))
    } catch (next) {
      setError(next)
    } finally {
      setLoading(false)
    }
  }, [client])

  useEffect(() => {
    const controller = new AbortController()
    void loadAssets(controller.signal)
    return () => controller.abort()
  }, [loadAssets])

  const loadAssetState = useCallback(async (
    selectedAssetId: string,
    signal?: AbortSignal,
  ) => {
    if (!selectedAssetId) {
      setDetail(undefined)
      setChangesets([])
      setSnapshot(undefined)
      return
    }
    setLoading(true)
    setError(undefined)
    try {
      const nextDetail = await client.request<KnowledgeAssetOperationalDetail>(
        `/knowledge/registry/assets/${encodeURIComponent(selectedAssetId)}/detail`,
        { cache: 'no-store', signal },
      )
      const nextChangesets = await client.request<KnowledgeChangeSet[]>(
        `/knowledge/graphs/${encodeURIComponent(selectedAssetId)}/changesets`,
        { cache: 'no-store', signal },
      )
      if (signal?.aborted) return
      setDetail(nextDetail)
      setChangesets(nextChangesets)
      setChangesetId((current) => (
        current && nextChangesets.some((item) => item.id === current && item.state === 'DRAFT')
          ? current
          : nextChangesets.find((item) => item.state === 'DRAFT')?.id ?? ''
      ))
      if (nextDetail.asset.active_release_id) {
        try {
          setSnapshot(await client.request<KnowledgeSnapshot>(
            `/knowledge/graphs/${encodeURIComponent(selectedAssetId)}/releases/${
              encodeURIComponent(nextDetail.asset.active_release_id)
            }/snapshot?maximum_nodes=500`,
            { cache: 'no-store', signal },
          ))
          setSnapshotNotice('')
        } catch (snapshotError) {
          if (signal?.aborted) return
          setSnapshot(undefined)
          setSnapshotNotice(
            snapshotError instanceof Error
              ? `기존 인스턴스 미리보기를 제한 내에서 불러오지 못했습니다: ${snapshotError.message}`
              : '기존 인스턴스 미리보기를 제한 내에서 불러오지 못했습니다.',
          )
        }
      } else {
        setSnapshot(undefined)
        setSnapshotNotice('')
      }
    } catch (next) {
      if (!signal?.aborted) setError(next)
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [client])

  useEffect(() => {
    const controller = new AbortController()
    setChangesetId('')
    setOperationAction('UPSERT')
    setStableEntityId('')
    setClassName('')
    setRelationName('')
    setSourceNodeId('')
    setTargetNodeId('')
    setDisplayName('')
    setPropertiesText('{}')
    setStatus('')
    changesetRetryRef.current = undefined
    publishRetryRef.current = undefined
    void loadAssetState(assetId, controller.signal)
    return () => controller.abort()
  }, [assetId, loadAssetState])

  const selectedAsset = assets.find((item) => item.id === assetId)
  const selectedChangeset = changesets.find((item) => item.id === changesetId)
  const classes = useMemo(
    () => detail?.schema_elements.filter((item) => item.kind === 'CLASS') ?? [],
    [detail],
  )
  const relations = useMemo(
    () => detail?.schema_elements.filter((item) => item.kind === 'RELATION') ?? [],
    [detail],
  )
  const nodeChoices = useMemo(() => {
    const persisted = (snapshot?.nodes ?? []).map((node) => ({
      id: node.id,
      label: instanceLabel(node.properties.name ?? node.properties.label, node.id),
    }))
    const drafted = (selectedChangeset?.operations ?? [])
      .filter((item) => item.operation === 'UPSERT' && item.entity_kind === 'NODE')
      .map((item) => ({
        id: item.stable_entity_id,
        label: instanceLabel(
          (item.document.properties as Record<string, unknown> | undefined)?.name
          ?? item.stable_entity_id,
          item.stable_entity_id,
        ),
      }))
    return [...persisted, ...drafted.filter(
      (item) => !persisted.some((existing) => existing.id === item.id),
    )]
  }, [selectedChangeset, snapshot])
  const edgeChoices = useMemo(() => {
    const persisted = (snapshot?.edges ?? []).map((edge) => ({
      id: edge.id,
      label: `${edge.edge_type} · ${edge.source_id} → ${edge.target_id}`,
    }))
    const drafted = (selectedChangeset?.operations ?? [])
      .filter((item) => item.operation === 'UPSERT' && item.entity_kind === 'EDGE')
      .map((item) => ({
        id: item.stable_entity_id,
        label: `${instanceLabel(item.document.edge_type, 'Relationship')} · ${
          item.stable_entity_id
        }`,
      }))
    return [...persisted, ...drafted.filter(
      (item) => !persisted.some((existing) => existing.id === item.id),
    )]
  }, [selectedChangeset, snapshot])

  useEffect(() => {
    if (!className && classes[0]) setClassName(classes[0].canonical_name)
    if (!relationName && relations[0]) setRelationName(relations[0].canonical_name)
  }, [className, classes, relationName, relations])

  const createChangeset = async (event: FormEvent) => {
    event.preventDefault()
    if (!selectedAsset || !title.trim() || busy) return
    setBusy(true)
    setError(undefined)
    try {
      const normalizedTitle = title.trim()
      const fingerprint = `${selectedAsset.id}:${normalizedTitle}`
      if (changesetRetryRef.current?.fingerprint !== fingerprint) {
        changesetRetryRef.current = {
          fingerprint,
          key: newIdempotencyKey('knowledge-instance-changeset'),
        }
      }
      const created = await client.request<KnowledgeChangeSet>(
        `/knowledge/graphs/${encodeURIComponent(selectedAsset.id)}/changesets`,
        {
          method: 'POST',
          body: JSON.stringify({ title: normalizedTitle }),
          idempotencyKey: changesetRetryRef.current.key,
        },
      )
      changesetRetryRef.current = undefined
      setTitle('')
      await loadAssetState(selectedAsset.id)
      setChangesetId(created.id)
      setStatus('A-Box DRAFT changeset을 생성했습니다.')
    } catch (next) {
      setError(next)
    } finally {
      setBusy(false)
    }
  }

  const appendOperation = async () => {
    if (!selectedAsset || !selectedChangeset || busy) return
    if (![sourceRef, sourceLocator, sourceVersion, method].every((value) => value.trim())) {
      setError(new Error('Source ref, locator, version, 작성/추출 방법을 모두 입력하세요.'))
      return
    }
    let properties: Record<string, unknown> = {}
    if (operationAction === 'UPSERT') {
      try {
        const parsed: unknown = JSON.parse(propertiesText)
        if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
          throw new Error()
        }
        properties = parsed as Record<string, unknown>
      } catch {
        setError(new Error('Properties는 JSON object여야 합니다.'))
        return
      }
    }
    const sequence = Math.max(
      0,
      ...selectedChangeset.operations.map((item) => item.sequence),
    ) + 1
    const entityId = stableEntityId.trim() || crypto.randomUUID()
    const provenance = [{
      source_ref: sourceRef.trim(),
      source_locator: sourceLocator.trim(),
      source_version: sourceVersion.trim(),
      method: method.trim(),
      confidence: 1,
    }]
    const operation: KnowledgeChangeOperationCreate = operationAction === 'DELETE'
      ? {
          sequence,
          operation: 'DELETE',
          entity_kind: kind,
          stable_entity_id: entityId,
          document: {},
          provenance,
          confidence: 1,
        }
      : kind === 'NODE'
      ? {
          sequence,
          operation: 'UPSERT',
          entity_kind: 'NODE',
          stable_entity_id: entityId,
          document: {
            entity_type: className,
            properties: {
              ...properties,
              ...(displayName.trim() ? { name: displayName.trim() } : {}),
            },
            classification: CLASSIFICATION_LEVEL[selectedAsset.classification],
          },
          provenance,
          confidence: 1,
        }
      : {
          sequence,
          operation: 'UPSERT',
          entity_kind: 'EDGE',
          stable_entity_id: entityId,
          document: {
            source_id: sourceNodeId,
            target_id: targetNodeId,
            edge_type: relationName,
            properties,
            classification: CLASSIFICATION_LEVEL[selectedAsset.classification],
          },
          provenance,
          confidence: 1,
        }
    if (
      (operationAction === 'DELETE' && !stableEntityId.trim())
      || (
        operationAction === 'UPSERT'
        && (
          (kind === 'NODE' && !className)
          || (kind === 'EDGE' && (!relationName || !sourceNodeId || !targetNodeId))
        )
      )
    ) {
      setError(new Error(
        operationAction === 'DELETE'
          ? '삭제할 기존 Node/Relationship ID를 선택하거나 입력하세요.'
          : 'T-Box Class/Relationship와 연결할 인스턴스를 선택하세요.',
      ))
      return
    }
    setBusy(true)
    setError(undefined)
    try {
      await client.request<KnowledgeChangeSet>(
        `/knowledge/graphs/${encodeURIComponent(selectedAsset.id)}/changesets/${
          encodeURIComponent(selectedChangeset.id)
        }/operations`,
        {
          method: 'POST',
          ifMatch: `"${selectedChangeset.version}"`,
          body: JSON.stringify(operation),
        },
      )
      setDisplayName('')
      setPropertiesText('{}')
      setStableEntityId('')
      await loadAssetState(selectedAsset.id)
      setStatus(
        `${kind === 'NODE' ? 'Node' : 'Relationship'} ${operationAction} operation을 추가했습니다.`,
      )
    } catch (next) {
      setError(next)
    } finally {
      setBusy(false)
    }
  }

  const transition = async (
    changeset: KnowledgeChangeSet,
    operation: 'submit' | 'approve' | 'reject' | 'publish',
  ) => {
    if (!selectedAsset || busy) return
    setBusy(true)
    setError(undefined)
    try {
      const decision = operation === 'approve' || operation === 'reject'
      const path = `/knowledge/graphs/${encodeURIComponent(selectedAsset.id)}/changesets/${
        encodeURIComponent(changeset.id)
      }/${decision ? 'reviews' : operation}`
      const publishFingerprint = `${selectedAsset.id}:${changeset.id}:${changeset.version}`
      if (
        operation === 'publish'
        && publishRetryRef.current?.fingerprint !== publishFingerprint
      ) {
        publishRetryRef.current = {
          fingerprint: publishFingerprint,
          key: newIdempotencyKey('knowledge-instance-release'),
        }
      }
      await client.request<KnowledgeChangeSet | KnowledgeChangeSetPublish>(
        path,
        operation === 'publish'
          ? {
              method: 'POST',
              idempotencyKey: publishRetryRef.current?.key,
            }
          : {
              method: 'POST',
              ifMatch: `"${changeset.version}"`,
              body: decision
                ? JSON.stringify({
                    decision: operation === 'approve' ? 'APPROVED' : 'REJECTED',
                    reason: reviewReason.trim(),
                  })
                : undefined,
            },
      )
      if (operation === 'publish') publishRetryRef.current = undefined
      setReviewReason('')
      await Promise.all([loadAssetState(selectedAsset.id), loadAssets()])
      setStatus(`Changeset ${operation} 처리를 완료했습니다.`)
    } catch (next) {
      setError(next)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="grid gap-4">
      <header className="rounded-enterprise border border-blue-200 bg-blue-50 p-4">
        <span className="text-[10px] font-black tracking-[.14em] text-enterprise-blue uppercase">
          Governed A-Box lifecycle
        </span>
        <h3 className="my-1 text-sm font-black text-navy-900">인스턴스·적재·Release 관리</h3>
        <p className="m-0 text-xs leading-5 text-slate-600">
          직접 입력과 PDF+LLM 추출은 typed DRAFT changeset을 만들며, 독립 검토·발행 전에는
          활성 A-Box가 아닙니다. DB 연결은 Studio의 immutable Binding 계약과 정확한 source
          version을 그대로 보여줍니다.
        </p>
      </header>
      <ErrorNotice error={error} />
      {status && <p role="status" className="m-0 rounded border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-800">{status}</p>}
      {snapshotNotice && (
        <p role="status" className="m-0 rounded border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
          {snapshotNotice} UUID 직접 입력과 새 Changeset 작성은 계속 사용할 수 있습니다.
        </p>
      )}
      <label className="grid max-w-xl gap-1 text-xs font-bold">
        대상 Knowledge Asset
        <select value={assetId} disabled={loading} onChange={(event) => setAssetId(event.target.value)}>
          <option value="">선택</option>
          {assets.map((asset) => (
            <option key={asset.id} value={asset.id}>
              {asset.name} · T v{asset.active_studio_release_no ?? '—'} · A v{asset.active_release_no ?? '—'}
            </option>
          ))}
        </select>
      </label>
      <nav className="flex flex-wrap gap-2 border-b border-slate-200 pb-3" aria-label="A-Box 관리 방식">
        {[
          { id: 'DIRECT' as const, label: '직접 입력', icon: GitBranchPlus },
          { id: 'FILE' as const, label: '파일 + LLM', icon: FileUp },
          { id: 'DATABASE' as const, label: 'DB Binding', icon: Database },
        ].map((item) => {
          const Icon = item.icon
          return (
            <button
              key={item.id}
              type="button"
              className={`button ${tab === item.id ? '' : 'button-secondary'}`}
              aria-pressed={tab === item.id}
              onClick={() => setTab(item.id)}
            >
              <Icon size={13} /> {item.label}
            </button>
          )
        })}
      </nav>
      {tab === 'DIRECT' && (
        <div className="grid gap-4 xl:grid-cols-[minmax(360px,.8fr)_minmax(0,1.2fr)]">
          <section className="grid content-start gap-3 rounded-enterprise border border-slate-300 bg-slate-50 p-4">
            <form className="grid gap-2" onSubmit={(event) => void createChangeset(event)}>
              <label className="grid gap-1 text-xs font-bold">
                새 Changeset 제목
                <input value={title} maxLength={500} onChange={(event) => setTitle(event.target.value)} />
              </label>
              <button type="submit" className="button" disabled={!selectedAsset || !title.trim() || busy}>
                <Plus size={13} /> DRAFT 생성
              </button>
            </form>
            <label className="grid gap-1 text-xs font-bold">
              편집할 DRAFT
              <select value={changesetId} onChange={(event) => setChangesetId(event.target.value)}>
                <option value="">선택</option>
                {changesets.filter((item) => item.state === 'DRAFT').map((item) => (
                  <option key={item.id} value={item.id}>{item.title} · v{item.version}</option>
                ))}
              </select>
            </label>
            <div className="flex gap-2">
              <button type="button" className={`button ${kind === 'NODE' ? '' : 'button-secondary'}`} onClick={() => { setKind('NODE'); setStableEntityId('') }}>Node</button>
              <button type="button" className={`button ${kind === 'EDGE' ? '' : 'button-secondary'}`} onClick={() => { setKind('EDGE'); setStableEntityId('') }}>Relationship</button>
            </div>
            <label className="grid gap-1 text-xs font-bold">
              Operation
              <select
                value={operationAction}
                onChange={(event) => setOperationAction(event.target.value as OperationAction)}
              >
                <option value="UPSERT">신규 또는 수정 (UPSERT)</option>
                <option value="DELETE">기존 항목 삭제 (DELETE)</option>
              </select>
            </label>
            <label className="grid gap-1 text-xs font-bold">
              Stable {kind === 'NODE' ? 'Node' : 'Relationship'} ID
              <input
                list={`knowledge-${kind.toLowerCase()}-ids`}
                value={stableEntityId}
                placeholder={operationAction === 'UPSERT' ? '비우면 신규 UUID 생성' : '삭제할 UUID'}
                onChange={(event) => setStableEntityId(event.target.value)}
              />
              <datalist id={`knowledge-${kind.toLowerCase()}-ids`}>
                {(kind === 'NODE' ? nodeChoices : edgeChoices).map((item) => (
                  <option key={item.id} value={item.id}>{item.label}</option>
                ))}
              </datalist>
            </label>
            {operationAction === 'UPSERT' && (kind === 'NODE' ? (
              <>
                <label className="grid gap-1 text-xs font-bold">
                  T-Box Class
                  <select value={className} onChange={(event) => setClassName(event.target.value)}>
                    <option value="">선택</option>
                    {classes.map((item) => <option key={item.stable_element_id} value={item.canonical_name}>{item.display_name}</option>)}
                  </select>
                </label>
                <label className="grid gap-1 text-xs font-bold">
                  표시 이름
                  <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
                </label>
              </>
            ) : (
              <>
                <label className="grid gap-1 text-xs font-bold">
                  T-Box Relationship
                  <select value={relationName} onChange={(event) => setRelationName(event.target.value)}>
                    <option value="">선택</option>
                    {relations.map((item) => <option key={item.stable_element_id} value={item.canonical_name}>{item.display_name}</option>)}
                  </select>
                </label>
                <label className="grid gap-1 text-xs font-bold">
                  Source Node
                  <input list="knowledge-source-node-ids" value={sourceNodeId} onChange={(event) => setSourceNodeId(event.target.value)} />
                </label>
                <label className="grid gap-1 text-xs font-bold">
                  Target Node
                  <input list="knowledge-target-node-ids" value={targetNodeId} onChange={(event) => setTargetNodeId(event.target.value)} />
                </label>
                <datalist id="knowledge-source-node-ids">
                  {nodeChoices.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
                </datalist>
                <datalist id="knowledge-target-node-ids">
                  {nodeChoices.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
                </datalist>
              </>
            ))}
            {operationAction === 'UPSERT' && (
              <label className="grid gap-1 text-xs font-bold">
                Properties JSON
                <textarea className="min-h-28 font-mono text-xs" value={propertiesText} onChange={(event) => setPropertiesText(event.target.value)} />
              </label>
            )}
            <label className="grid gap-1 text-xs font-bold">
              Source ref
              <input value={sourceRef} onChange={(event) => setSourceRef(event.target.value)} />
            </label>
            <label className="grid gap-1 text-xs font-bold">
              Source locator
              <input value={sourceLocator} onChange={(event) => setSourceLocator(event.target.value)} />
            </label>
            <label className="grid gap-1 text-xs font-bold">
              Source version
              <input value={sourceVersion} onChange={(event) => setSourceVersion(event.target.value)} />
            </label>
            <label className="grid gap-1 text-xs font-bold">
              Method
              <input value={method} onChange={(event) => setMethod(event.target.value)} />
            </label>
            <button type="button" className="button" disabled={!selectedChangeset || busy} onClick={() => void appendOperation()}>
              <Workflow size={13} /> Typed operation 추가
            </button>
          </section>
          <section className="grid content-start gap-3 rounded-enterprise border border-slate-300 bg-white p-4">
            <h4 className="m-0 text-sm font-black text-navy-900">검토 및 Release</h4>
            <label className="grid gap-1 text-xs font-bold">
              승인·반려 사유
              <textarea value={reviewReason} onChange={(event) => setReviewReason(event.target.value)} />
            </label>
            {changesets.length === 0 ? (
              <p className="m-0 text-xs text-slate-500">아직 Changeset이 없습니다.</p>
            ) : changesets.map((changeset) => (
              <article key={changeset.id} className="flex flex-wrap items-center gap-2 border-t border-slate-200 pt-3 text-xs">
                <span className="badge badge-soft">{changeset.state}</span>
                <div className="min-w-0 flex-1">
                  <strong className="block truncate">{changeset.title}</strong>
                  <small>{changeset.operations.length} operations · {changeset.validations.length} validations</small>
                </div>
                {changeset.state === 'DRAFT' && <button type="button" className="button button-secondary" disabled={busy} onClick={() => void transition(changeset, 'submit')}><Send size={12} /> 검토 제출</button>}
                {changeset.state === 'REVIEW' && (
                  <>
                    <button type="button" className="button" disabled={busy || !reviewReason.trim()} onClick={() => void transition(changeset, 'approve')}>승인</button>
                    <button type="button" className="button button-danger" disabled={busy || !reviewReason.trim()} onClick={() => void transition(changeset, 'reject')}>반려</button>
                  </>
                )}
                {changeset.state === 'APPROVED' && <button type="button" className="button" disabled={busy} onClick={() => void transition(changeset, 'publish')}>Release 발행</button>}
              </article>
            ))}
          </section>
        </div>
      )}
      {tab === 'FILE' && (
        selectedAsset
          ? (
              <KnowledgeSourceUpload
                client={client}
                graph={asKnowledgeGraph(selectedAsset)}
                onAnalysisCreated={() => loadAssetState(selectedAsset.id)}
                onOpenChangeset={async (nextChangesetId) => {
                  await loadAssetState(selectedAsset.id)
                  setChangesetId(nextChangesetId)
                  setTab('DIRECT')
                }}
              />
            )
          : <p className="m-0 text-xs text-slate-500">Asset을 선택하세요.</p>
      )}
      {tab === 'DATABASE' && (
        <section className="grid gap-3 rounded-enterprise border border-slate-300 bg-white p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h4 className="m-0 text-sm font-black text-navy-900">발행된 DB Binding 계약</h4>
              <p className="mb-0 mt-1 text-xs text-slate-500">
                실제 DB credential이나 SQL을 노출하지 않고 source·projection version과 mapping rule만 표시합니다.
              </p>
            </div>
            <button type="button" className="button" disabled={!selectedAsset} onClick={() => selectedAsset && onEditAsset(selectedAsset.id)}>
              Studio에서 Binding 편집
            </button>
          </div>
          {detail?.bindings.length ? (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-left text-xs">
                <thead><tr className="border-b border-slate-300"><th className="p-2">Target</th><th className="p-2">Source</th><th className="p-2">Version</th><th className="p-2">Rules</th></tr></thead>
                <tbody>
                  {detail.bindings.map((binding) => (
                    <tr key={binding.id} className="border-b border-slate-200">
                      <td className="p-2 font-bold">{binding.target_stable_element_id}</td>
                      <td className="p-2">{binding.source_name}</td>
                      <td className="p-2">{binding.source_version}</td>
                      <td className="p-2">{binding.mapping_rule_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <p className="m-0 text-xs text-slate-500">활성 Studio Release에 DB Binding이 없습니다.</p>}
        </section>
      )}
    </section>
  )
}
