import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  CheckCircle2,
  Database,
  Eye,
  Link2,
  Play,
  Save,
  Search,
  Send,
  ShieldCheck,
  TriangleAlert,
} from 'lucide-react'
import { ApiError, type ApiClient } from '../../../../api/client'
import { AssuranceNotice } from '../../../../components/AssuranceNotice'
import { Dialog } from '../../../../components/common/Dialog'
import {
  FlowCanvas,
  type FlowCanvasEdge,
  type FlowCanvasNode,
} from '../../../../components/common/FlowCanvas'
import {
  cancelKnowledgeStudioIngestion,
  createKnowledgeStudioIngestion,
  discardKnowledgeStudioDraft,
  getKnowledgeStudioABox,
  getKnowledgeStudioSource,
  listKnowledgeStudioIngestions,
  newKnowledgeStudioIdempotencyKey,
  preflightKnowledgeStudioABox,
  previewKnowledgeStudioBinding,
  publishKnowledgeStudioDraft,
  retryKnowledgeStudioIngestion,
  saveKnowledgeStudioBinding,
  searchKnowledgeStudioSources,
  submitKnowledgeStudioReview,
  type KnowledgeStudioABox,
  type KnowledgeStudioBinding,
  type KnowledgeStudioDraft,
  type KnowledgeStudioIngestionJob,
  type KnowledgeStudioMappingRuleInput,
  type KnowledgeStudioPreflight,
  type KnowledgeStudioPreview,
  type KnowledgeStudioPreviewScalar,
  type KnowledgeStudioRelease,
  type KnowledgeStudioSourceDataset,
  type KnowledgeStudioTBoxElement,
} from '../knowledgeStudioApi'
import {
  getKnowledgeStudioABoxSession,
  useKnowledgeStudioSessionStore,
} from '../knowledgeStudioSessionStore'

interface LocalBindingDraft {
  targetStableElementId: string
  source: KnowledgeStudioSourceDataset
  rules: KnowledgeStudioMappingRuleInput[]
}

interface DataEnricherStepProps {
  client: ApiClient
  draftId: string
  subjectId?: string
  onDraftUpdate: (draft: KnowledgeStudioDraft, etag: string) => void
  onStepUp?: () => Promise<void>
  onPasswordReauth?: () => Promise<void>
  onEnroll?: () => Promise<void>
  hardwareWebauthnEnabled?: boolean
}

const ACTIVE_INGESTION_STATES = new Set<KnowledgeStudioIngestionJob['state']>([
  'PENDING',
  'RUNNING',
  'RETRY_WAIT',
  'CANCEL_REQUESTED',
])

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

function previewValue(value: KnowledgeStudioPreviewScalar): string {
  if (value === null) return 'null'
  return String(value)
}

export function DataEnricherStep({
  client,
  draftId,
  subjectId,
  onDraftUpdate,
  onStepUp,
  onPasswordReauth,
  onEnroll,
  hardwareWebauthnEnabled,
}: DataEnricherStepProps) {
  const cachedSession = getKnowledgeStudioABoxSession(draftId)
  const setCachedABox = useKnowledgeStudioSessionStore((state) => state.setABox)
  const [abox, setAbox] = useState<KnowledgeStudioABox>()
  const [etag, setEtag] = useState<string>()
  const [selectedTargetId, setSelectedTargetId] = useState<string | undefined>(
    cachedSession?.selectedTargetId,
  )
  const [sourceQuery, setSourceQuery] = useState(cachedSession?.sourceQuery ?? '')
  const [sourceResults, setSourceResults] = useState<KnowledgeStudioSourceDataset[]>([])
  const [selectedSource, setSelectedSource] = useState<KnowledgeStudioSourceDataset | undefined>(
    cachedSession?.selectedSource,
  )
  const [selectedSourceStale, setSelectedSourceStale] = useState(
    cachedSession?.selectedSourceStale ?? false,
  )
  const [subjectField, setSubjectField] = useState(cachedSession?.subjectField ?? '')
  const [propertyFields, setPropertyFields] = useState<Record<string, string>>(
    cachedSession?.propertyFields ?? {},
  )
  const [loading, setLoading] = useState(true)
  const [sourceLoading, setSourceLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [preview, setPreview] = useState<KnowledgeStudioPreview>()
  const [previewOpen, setPreviewOpen] = useState(false)
  const [selectedPreviewNodeId, setSelectedPreviewNodeId] = useState<string | undefined>(
    cachedSession?.selectedPreviewNodeId,
  )
  const [preflightLoading, setPreflightLoading] = useState(false)
  const [preflight, setPreflight] = useState<KnowledgeStudioPreflight>()
  const [release, setRelease] = useState<KnowledgeStudioRelease>()
  const [reviewReason, setReviewReason] = useState(cachedSession?.reviewReason ?? '')
  const [publishDialogOpen, setPublishDialogOpen] = useState(false)
  const [discardDialogOpen, setDiscardDialogOpen] = useState(false)
  const [governanceBusy, setGovernanceBusy] = useState(false)
  const [publishError, setPublishError] = useState<unknown>()
  const [status, setStatus] = useState('Accepted T-Box와 Binding Draft를 불러오고 있습니다.')
  const [conflict, setConflict] = useState<LocalBindingDraft>()
  const [ingestionJobs, setIngestionJobs] = useState<KnowledgeStudioIngestionJob[]>([])
  const [ingestionLoading, setIngestionLoading] = useState(false)
  const [ingestionPollRevision, setIngestionPollRevision] = useState(0)
  const [ingestionActionJobId, setIngestionActionJobId] = useState<string>()
  const [cancelTarget, setCancelTarget] = useState<KnowledgeStudioIngestionJob>()
  const [cancelReason, setCancelReason] = useState('')

  useEffect(() => {
    setCachedABox(draftId, {
      selectedTargetId,
      sourceQuery,
      selectedSource,
      selectedSourceStale,
      subjectField,
      propertyFields,
      selectedPreviewNodeId,
      reviewReason,
    })
  }, [
    draftId,
    propertyFields,
    reviewReason,
    selectedPreviewNodeId,
    selectedSource,
    selectedSourceStale,
    selectedTargetId,
    setCachedABox,
    sourceQuery,
    subjectField,
  ])

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

  useEffect(() => {
    let active = true
    let timer: number | undefined
    let attempts = 0
    let inFlight = false
    const poll = async () => {
      if (!active || inFlight || document.visibilityState === 'hidden') return
      inFlight = true
      try {
        const jobs = await listKnowledgeStudioIngestions(client, draftId)
        if (!active) return
        setIngestionJobs(jobs)
        attempts += 1
        if (
          attempts < 150
          && jobs.some((job) => ACTIVE_INGESTION_STATES.has(job.state))
        ) {
          timer = window.setTimeout(() => { void poll() }, 2000)
        }
      } catch {
        if (active) setStatus('Ingestion 진행 상태를 불러오지 못했습니다.')
      } finally {
        inFlight = false
      }
    }
    const resumeWhenVisible = () => {
      if (!active || document.visibilityState !== 'visible') return
      if (timer !== undefined) window.clearTimeout(timer)
      void poll()
    }
    document.addEventListener('visibilitychange', resumeWhenVisible)
    void poll()
    return () => {
      active = false
      if (timer !== undefined) window.clearTimeout(timer)
      document.removeEventListener('visibilitychange', resumeWhenVisible)
    }
  }, [client, draftId, ingestionPollRevision])

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
  const actorId = subjectId ?? abox?.draft.author_id
  const isAuthor = Boolean(abox && actorId === abox.draft.author_id)
  const editable = Boolean(abox && isAuthor && abox.draft.state === 'DRAFT')
  const isIndependentReviewer = Boolean(
    abox && !isAuthor && abox.draft.state === 'REVIEW',
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
  const selectedBinding = selectedTargetId
    ? bindingByTarget.get(selectedTargetId)
    : undefined

  const hydrateBindingForm = useCallback(async (
    targetId: string,
    binding?: KnowledgeStudioBinding,
  ) => {
    setPreview(undefined)
    setPreviewOpen(false)
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
    setSubjectField(
      binding.rules.find((rule) => rule.method === 'SUBJECT_ID')?.source_field_path ?? '',
    )
    setPropertyFields(Object.fromEntries(
      binding.rules
        .filter((rule) => rule.method === 'PROPERTY')
        .map((rule) => [rule.target_stable_element_id, rule.source_field_path]),
    ))
    if (!editable) {
      setSelectedSource(undefined)
      setSelectedSourceStale(false)
      return
    }
    setSourceLoading(true)
    try {
      const detail = await getKnowledgeStudioSource(client, draftId, binding.source_asset_id)
      setSelectedSource(detail.dataset)
      setSelectedSourceStale(Boolean(detail.stale_at))
    } catch (error) {
      setSelectedSource(undefined)
      setSelectedSourceStale(false)
      setStatus(error instanceof Error ? error.message : 'Binding Dataset을 불러오지 못했습니다.')
    } finally {
      setSourceLoading(false)
    }
  }, [client, draftId, editable])

  useEffect(() => {
    if (!selectedTargetId || !editable) return
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
  }, [client, draftId, editable, selectedTargetId, sourceQuery])

  const selectSource = async (source: KnowledgeStudioSourceDataset) => {
    if (!editable) return
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
    if (!editable) return false
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
      setPreflight(undefined)
      setPreview(undefined)
      setPreviewOpen(false)
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
    if (!editable || !selectedTarget || !selectedSource || !etag) return
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

  const openPreview = async () => {
    if (!selectedTarget || !etag) return
    if (!bindingByTarget.has(selectedTarget.stable_element_id)) {
      setStatus('먼저 Binding Draft를 저장한 뒤 Preview를 실행하세요.')
      return
    }
    setPreviewLoading(true)
    try {
      const response = await previewKnowledgeStudioBinding(
        client,
        draftId,
        selectedTarget.stable_element_id,
        etag,
        5,
      )
      setPreview(response.data)
      setPreviewOpen(true)
      setSelectedPreviewNodeId(response.data.graph.nodes[0]?.id)
      setStatus(
        response.data.status === 'READY'
          ? `${response.data.sample_size}개 실제 Row를 Dry-run Graph로 변환했습니다.`
          : 'Preview evidence를 확인하세요. 실제 적재는 수행되지 않았습니다.',
      )
    } catch (error) {
      setStatus(
        error instanceof ApiError && error.problem.status === 412
          ? 'Draft가 변경되어 Preview를 중단했습니다. Mapping 입력은 그대로 보존됩니다.'
          : error instanceof Error ? error.message : 'Knowledge Graph Preview에 실패했습니다.',
      )
    } finally {
      setPreviewLoading(false)
    }
  }

  const runPreflight = async () => {
    if (!etag) return
    setPreflightLoading(true)
    try {
      const response = await preflightKnowledgeStudioABox(
        client,
        draftId,
        etag,
        newKnowledgeStudioIdempotencyKey(),
      )
      setPreflight(response.data)
      setStatus(
        response.data.valid
          ? 'Pre-flight PASS · 현재 Draft version과 Contract hash가 발행 증거로 고정되었습니다.'
          : 'Pre-flight evidence를 확인하세요. Run Ingestion은 실행되지 않았습니다.',
      )
    } catch (error) {
      setStatus(
        error instanceof ApiError && error.problem.status === 412
          ? 'Draft가 변경되어 Pre-flight를 중단했습니다. 최신 version을 확인하세요.'
          : error instanceof Error ? error.message : 'Pre-flight 검증에 실패했습니다.',
      )
    } finally {
      setPreflightLoading(false)
    }
  }

  const runIngestion = async () => {
    if (
      !etag
      || abox?.draft.state !== 'PUBLISHED'
      || ingestionLoading
      || !preview?.job_id
      || !selectedTarget
      || preview.target_stable_element_id !== selectedTarget.stable_element_id
      || ingestionJobs.some((job) => ACTIVE_INGESTION_STATES.has(job.state))
    ) return
    setIngestionLoading(true)
    try {
      const job = await createKnowledgeStudioIngestion(
        client,
        draftId,
        etag,
        newKnowledgeStudioIdempotencyKey(),
        preview.job_id,
        selectedTarget.stable_element_id,
      )
      setIngestionJobs((current) => [job, ...current.filter((item) => item.id !== job.id)])
      setIngestionPollRevision((current) => current + 1)
      setStatus(
        `확인한 Preview로 A-Box projection을 실행했습니다. `
        + `Node ${job.node_count ?? 0}개 · ${job.state}`,
      )
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Ingestion 작업을 접수하지 못했습니다.')
    } finally {
      setIngestionLoading(false)
    }
  }

  const cancelIngestion = async () => {
    const reason = cancelReason.trim()
    if (!cancelTarget || !reason || ingestionActionJobId) return
    setIngestionActionJobId(cancelTarget.id)
    try {
      const job = await cancelKnowledgeStudioIngestion(
        client,
        draftId,
        cancelTarget.id,
        cancelTarget.version,
        reason,
        newKnowledgeStudioIdempotencyKey(),
      )
      setIngestionJobs((current) => [
        job,
        ...current.filter((item) => item.id !== job.id),
      ])
      setCancelTarget(undefined)
      setCancelReason('')
      setIngestionPollRevision((current) => current + 1)
      setStatus(`Ingestion 취소 요청을 기록했습니다. 현재 상태: ${job.state}`)
    } catch (error) {
      if (error instanceof ApiError && error.problem.status === 412) {
        setIngestionPollRevision((current) => current + 1)
        setStatus('Ingestion 상태가 변경되어 취소하지 못했습니다. 최신 상태를 다시 확인합니다.')
      } else {
        setStatus(error instanceof Error ? error.message : 'Ingestion 취소 요청에 실패했습니다.')
      }
    } finally {
      setIngestionActionJobId(undefined)
    }
  }

  const retryIngestion = async (target: KnowledgeStudioIngestionJob) => {
    if (ingestionActionJobId) return
    setIngestionActionJobId(target.id)
    try {
      const job = await retryKnowledgeStudioIngestion(
        client,
        draftId,
        target.id,
        target.version,
        newKnowledgeStudioIdempotencyKey(),
      )
      setIngestionJobs((current) => [
        job,
        ...current.filter((item) => item.id !== job.id),
      ])
      setIngestionPollRevision((current) => current + 1)
      setStatus(`Ingestion 재시도를 접수했습니다. 현재 상태: ${job.state}`)
    } catch (error) {
      if (error instanceof ApiError && error.problem.status === 412) {
        setIngestionPollRevision((current) => current + 1)
        setStatus('Ingestion 상태가 변경되어 재시도하지 못했습니다. 최신 상태를 다시 확인합니다.')
      } else {
        setStatus(error instanceof Error ? error.message : 'Ingestion 재시도에 실패했습니다.')
      }
    } finally {
      setIngestionActionJobId(undefined)
    }
  }

  const openResultChangeset = (job: KnowledgeStudioIngestionJob) => {
    if (!job.result_changeset_id) return
    const url = new URL(window.location.href)
    url.searchParams.set('page', 'knowledge-instances')
    url.searchParams.set('information_tab', 'instances')
    url.searchParams.set('asset_id', job.graph_id)
    url.searchParams.set('changeset_id', job.result_changeset_id)
    url.searchParams.delete('draft')
    url.searchParams.delete('step')
    window.history.pushState({}, '', `${url.pathname}${url.search}${url.hash}`)
    window.dispatchEvent(new PopStateEvent('popstate'))
  }

  const submitReview = async () => {
    if (!etag || !editable) return
    setGovernanceBusy(true)
    try {
      const response = await submitKnowledgeStudioReview(
        client,
        draftId,
        etag,
        newKnowledgeStudioIdempotencyKey(),
      )
      if (!response.etag) return
      setAbox((current) => current ? { ...current, draft: response.data } : current)
      setEtag(response.etag)
      setPreflight(undefined)
      onDraftUpdate(response.data, response.etag)
      setStatus('독립 검토를 요청했습니다. Draft는 REVIEW 상태로 잠겼습니다.')
    } catch (error) {
      if (error instanceof ApiError && error.problem.status === 412) {
        await loadAbox().catch(() => undefined)
        setStatus('Draft가 변경되어 검토 요청을 중단했습니다. 최신 상태를 확인하세요.')
      } else {
        setStatus(error instanceof Error ? error.message : '독립 검토 요청에 실패했습니다.')
      }
    } finally {
      setGovernanceBusy(false)
    }
  }

  const discardDraft = async () => {
    if (!etag || !isAuthor || !abox || !['DRAFT', 'REVIEW'].includes(abox.draft.state)) return
    setGovernanceBusy(true)
    try {
      const response = await discardKnowledgeStudioDraft(
        client,
        draftId,
        etag,
        newKnowledgeStudioIdempotencyKey(),
      )
      if (!response.etag) return
      setAbox((current) => current ? { ...current, draft: response.data } : current)
      setEtag(response.etag)
      setPreflight(undefined)
      setDiscardDialogOpen(false)
      onDraftUpdate(response.data, response.etag)
      setStatus('Draft를 명시적으로 Discard했습니다. 정본 데이터는 삭제하지 않았습니다.')
    } catch (error) {
      setStatus(
        error instanceof ApiError && error.problem.status === 412
          ? 'Draft가 변경되어 Discard를 중단했습니다. 최신 상태를 확인하세요.'
          : error instanceof Error ? error.message : 'Draft Discard에 실패했습니다.',
      )
    } finally {
      setGovernanceBusy(false)
    }
  }

  const publishDraft = async () => {
    const reason = reviewReason.trim()
    if (
      !etag
      || !isIndependentReviewer
      || !abox
      || !preflight?.valid
      || preflight.draft_version !== abox.draft.version
      || !preflight.receipt_id
      || !reason
    ) return
    setGovernanceBusy(true)
    setPublishError(undefined)
    try {
      const response = await publishKnowledgeStudioDraft(
        client,
        draftId,
        reason,
        etag,
        newKnowledgeStudioIdempotencyKey(),
      )
      if (!response.etag) return
      setAbox((current) => current
        ? { ...current, draft: response.data.draft }
        : current)
      setEtag(response.etag)
      setRelease(response.data.release)
      setPublishDialogOpen(false)
      onDraftUpdate(response.data.draft, response.etag)
      setStatus(
        `Studio Release #${response.data.release.release_no} 발행 완료 · `
        + '실제 Ingestion은 NOT_RUN 상태입니다.',
      )
    } catch (error) {
      setPublishError(error)
      setStatus(
        error instanceof ApiError && error.problem.status === 412
          ? 'Draft가 변경되어 Publish를 중단했습니다. Pre-flight부터 다시 수행하세요.'
          : error instanceof Error ? error.message : 'Studio Release 발행에 실패했습니다.',
      )
    } finally {
      setGovernanceBusy(false)
    }
  }

  const previewFlowNodes = useMemo<FlowCanvasNode[]>(() => (
    preview?.graph.nodes.map((node, index) => ({
      id: node.id,
      label: node.type,
      subtitle: `SUBJECT_ID ${previewValue(node.identity)} · ${
        Object.keys(node.properties).length
      } properties`,
      kind: 'source',
      x: 40 + (index % 3) * 220,
      y: 45 + Math.floor(index / 3) * 140,
    })) ?? []
  ), [preview?.graph.nodes])
  const previewFlowEdges = useMemo<FlowCanvasEdge[]>(() => (
    preview?.graph.edges.map((edge) => ({
      id: edge.id,
      source: edge.source_node_id,
      target: edge.target_node_id,
      label: edge.type,
    })) ?? []
  ), [preview?.graph.edges])
  const selectedPreviewNode = preview?.graph.nodes.find(
    (node) => node.id === selectedPreviewNodeId,
  )
  const draftState = abox?.draft.state ?? 'DRAFT'
  const exactPreflightPass = Boolean(
    abox
    && preflight?.valid
    && preflight.status === 'PASS'
    && preflight.draft_version === abox.draft.version
    && preflight.receipt_id
    && preflight.contract_hash,
  )
  const latestIngestion = ingestionJobs[0]
  const hasActiveIngestion = ingestionJobs.some((job) => (
    ACTIVE_INGESTION_STATES.has(job.state)
  ))
  const canRunIngestion = Boolean(
    etag
    && draftState === 'PUBLISHED'
    && preview?.job_id
    && selectedTarget
    && preview.target_stable_element_id === selectedTarget.stable_element_id
    && !ingestionLoading
    && !hasActiveIngestion,
  )

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
        <div className="flex flex-wrap justify-end gap-2 text-[11px]">
          <span className="badge badge-soft">Studio: {draftState}</span>
          <span className="badge badge-soft">
            Ingestion: {latestIngestion?.state ?? 'NOT_RUN'}
          </span>
          <button
            type="button"
            className="button button-secondary"
            disabled={
              !etag
              || preflightLoading
              || draftState === 'PUBLISHED'
              || draftState === 'DISCARDED'
              || (draftState === 'REVIEW' && !isIndependentReviewer)
            }
            onClick={() => void runPreflight()}
          >
            <ShieldCheck size={14} />
            {preflightLoading ? '검증 중…' : 'Pre-flight 검증'}
          </button>
          {editable && (
            <button
              type="button"
              className="button"
              disabled={governanceBusy || !etag}
              onClick={() => void submitReview()}
            >
              <Send size={14} />
              {governanceBusy ? '처리 중…' : '독립 검토 요청'}
            </button>
          )}
          {isIndependentReviewer && (
            <button
              type="button"
              className="button"
              disabled={governanceBusy || !exactPreflightPass}
              title={exactPreflightPass
                ? '검토 사유 확인 후 Studio Release를 발행합니다.'
                : '현재 REVIEW Draft의 정확한 PASS receipt가 필요합니다.'}
              onClick={() => {
                setPublishError(undefined)
                setPublishDialogOpen(true)
              }}
            >
              <ShieldCheck size={14} />
              Publish
            </button>
          )}
          {isAuthor && ['DRAFT', 'REVIEW'].includes(draftState) && (
            <button
              type="button"
              className="button button-secondary"
              disabled={governanceBusy}
              onClick={() => setDiscardDialogOpen(true)}
            >
              Discard
            </button>
          )}
          <button
            type="button"
            className="button"
            disabled={!canRunIngestion}
            title={draftState !== 'PUBLISHED'
              ? 'Schema와 Mapping을 발행한 뒤에만 실제 A-Box Ingestion을 실행할 수 있습니다.'
              : hasActiveIngestion
                ? '진행 중인 Ingestion이 끝난 뒤 새 작업을 실행할 수 있습니다.'
                : !preview?.job_id
                  ? '선택한 Mapping의 Preview를 먼저 확인해야 합니다.'
                  : '확인한 exact Preview receipt로 bounded A-Box projection을 실행합니다.'}
            onClick={() => void runIngestion()}
          >
            <Play size={14} /> {ingestionLoading ? '접수 중…' : 'Run Ingestion'}
          </button>
        </div>
      </header>
      {preflight && (
        <section
          aria-label="Ingestion Pre-flight 결과"
          className={`mb-3 rounded-enterprise border p-3 ${
            preflight.valid
              ? 'border-emerald-300 bg-emerald-50'
              : 'border-amber-300 bg-amber-50'
          }`}
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <strong className="flex items-center gap-1 text-xs text-navy-900">
              {preflight.valid
                ? <CheckCircle2 size={14} className="text-emerald-700" />
                : <TriangleAlert size={14} className="text-amber-700" />}
              Pre-flight {preflight.status}
            </strong>
            <span className="text-[10px] text-slate-500">
              Draft version {preflight.draft_version} · receipt {preflight.receipt_id.slice(0, 8)}…
            </span>
          </div>
          {preflight.evidence.length > 0
            ? <ul className="mb-0 pl-5 text-[11px] leading-5 text-slate-700">
                {preflight.evidence.map((item, index) => (
                  <li key={`${item.code}:${item.location}:${index}`}>
                    <strong>{item.code}</strong> · {item.message}
                  </li>
                ))}
              </ul>
            : <p className="mb-0 text-[11px] text-emerald-800">
                Required Class, Property, source contract와 access probe가 모두 유효합니다.
              </p>}
          <p className="mb-0 text-[10px] text-slate-500">
            PASS receipt는 동일 Draft version과 Contract hash에만 유효하며 실제 Ingestion을 실행하지 않습니다.
          </p>
        </section>
      )}
      {latestIngestion && (
        <section
          aria-label="A-Box Ingestion 진행 상태"
          className={`mb-3 rounded-enterprise border p-3 ${
            latestIngestion.state === 'SUCCESS'
              ? 'border-emerald-200 bg-emerald-50'
              : ['FAILED', 'STALE'].includes(latestIngestion.state)
                ? 'border-red-200 bg-red-50'
                : latestIngestion.state === 'CANCELLED'
                  ? 'border-slate-300 bg-slate-50'
                  : 'border-blue-200 bg-blue-50'
          }`}
        >
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
            <strong className="text-navy-900">
              {latestIngestion.state} · {latestIngestion.current_stage}
            </strong>
            <span className="text-slate-600">
              {latestIngestion.progress_percent}% · 시도 {latestIngestion.attempt_count}/
              {latestIngestion.maximum_attempts} · Vector 대상 {latestIngestion.vector_target_count}개
            </span>
          </div>
          <div
            className="mt-2 h-2 overflow-hidden rounded-full bg-blue-100"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={latestIngestion.progress_percent}
          >
            <div
              className={`h-full transition-[width] ${
                ['FAILED', 'STALE'].includes(latestIngestion.state)
                  ? 'bg-red-600'
                  : latestIngestion.state === 'SUCCESS'
                    ? 'bg-emerald-600'
                    : 'bg-enterprise-blue'
              }`}
              style={{ width: `${latestIngestion.progress_percent}%` }}
            />
          </div>
          {latestIngestion.error_code && (
            <p role="alert" className="mb-0 mt-2 text-[11px] text-red-800">
              실패 코드 · {latestIngestion.error_code}
            </p>
          )}
          {latestIngestion.result_changeset_id && (
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-enterprise border border-emerald-200 bg-white p-2 text-[11px]">
              <span className="min-w-0">
                DRAFT Changeset · <code className="break-all">
                  {latestIngestion.result_changeset_id}
                </code>
              </span>
              <button
                type="button"
                className="button button-secondary"
                onClick={() => openResultChangeset(latestIngestion)}
              >
                Changeset 검토 화면으로 이동
              </button>
            </div>
          )}
          <div className="mt-3 flex flex-wrap justify-end gap-2">
            {latestIngestion.allowed_actions.includes('CANCEL') && (
              <button
                type="button"
                className="button button-secondary"
                disabled={Boolean(ingestionActionJobId)}
                onClick={() => {
                  setCancelReason('')
                  setCancelTarget(latestIngestion)
                }}
              >
                Ingestion 취소
              </button>
            )}
            {latestIngestion.allowed_actions.includes('RETRY') && (
              <button
                type="button"
                className="button"
                disabled={Boolean(ingestionActionJobId)}
                onClick={() => void retryIngestion(latestIngestion)}
              >
                {ingestionActionJobId === latestIngestion.id ? '재접수 중…' : 'Ingestion 재시도'}
              </button>
            )}
          </div>
        </section>
      )}
      {draftState !== 'PUBLISHED' && draftState !== 'DISCARDED' && (
        <p className="mb-3 rounded-enterprise border border-amber-200 bg-amber-50 p-3 text-xs text-amber-950">
          실제 A-Box Ingestion은 변경 가능한 Draft가 아니라 독립 검토를 거쳐 발행된
          Studio Release만 입력으로 사용합니다. Pre-flight를 완료하고 Publish한 뒤 실행하세요.
        </p>
      )}
      {draftState === 'REVIEW' && isAuthor && (
        <p className="mb-3 rounded-enterprise border border-blue-200 bg-blue-50 p-3 text-xs text-blue-950">
          독립 검토 대기 중입니다. REVIEW 상태에서는 T-Box/A-Box Mapping이 잠기며,
          작성자는 검토 Pre-flight 또는 Publish를 수행할 수 없습니다.
        </p>
      )}
      {draftState === 'PUBLISHED' && (
        <p className="mb-3 rounded-enterprise border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-950">
          Studio Release가 발행되었습니다. Schema/Mapping 정본만 활성화되었으며,
          Neo4j instance release와 Ingestion은 별도 파이프라인에서 수행됩니다.
          {release ? ` Release #${release.release_no} · ${release.contract_hash.slice(0, 12)}…` : ''}
        </p>
      )}
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
            {editable
              ? <>
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
                </>
              : <div className="rounded-enterprise border border-slate-200 bg-slate-50 p-3 text-xs">
                  <strong className="block text-navy-900">읽기 전용 Mapping Contract</strong>
                  {selectedBinding
                    ? <>
                        <span className="mt-1 block text-slate-600">
                          {selectedBinding.source_name} · {selectedBinding.source_version}
                        </span>
                        <span className="mt-1 block text-slate-500">
                          {selectedBinding.rules.length} typed rules · {selectedBinding.readiness}
                        </span>
                      </>
                    : <span className="mt-1 block text-amber-700">연결된 Dataset이 없습니다.</span>}
                </div>}
          </div>

          <div className="grid content-start gap-3">
            {!editable
              ? <div className="grid gap-3 rounded-enterprise border border-slate-200 bg-slate-50 p-4">
                  <header>
                    <span className="text-[10px] font-black tracking-[.12em] text-enterprise-blue uppercase">
                      Published candidate rules
                    </span>
                    <h3 className="my-1 text-sm font-black text-navy-900">
                      {selectedBinding?.source_name ?? 'Unbound'}
                    </h3>
                  </header>
                  {selectedBinding?.rules.length
                    ? <dl className="grid grid-cols-[minmax(120px,.7fr)_1fr] gap-2 text-xs">
                        {selectedBinding.rules.map((rule) => (
                          <div className="contents" key={rule.id}>
                            <dt className="font-black text-slate-500">
                              {rule.method} · {rule.target_stable_element_id}
                            </dt>
                            <dd className="m-0 break-all text-navy-900">
                              {rule.source_field_path} → {rule.transform_id}@{rule.transform_version}
                            </dd>
                          </div>
                        ))}
                      </dl>
                    : <p className="m-0 text-xs text-amber-700">
                        이 T-Box Class에는 Mapping Contract가 없습니다.
                      </p>}
                  <footer className="flex justify-end border-t border-slate-200 pt-3">
                    <button
                      type="button"
                      className="button button-secondary"
                      disabled={previewLoading || !etag || !selectedBinding}
                      onClick={() => void openPreview()}
                    >
                      <Eye size={14} />
                      {previewLoading ? 'Preview 중…' : 'Preview · Dry Run'}
                    </button>
                  </footer>
                </div>
              : selectedSource
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
                    <span className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        className="button button-secondary"
                        disabled={
                          previewLoading
                          || !etag
                          || !bindingByTarget.has(selectedTarget.stable_element_id)
                        }
                        onClick={() => void openPreview()}
                      >
                        <Eye size={14} />
                        {previewLoading ? 'Preview 중…' : 'Preview · Dry Run'}
                      </button>
                      <button
                        type="button"
                        className="button"
                        disabled={saving || !etag || selectedSourceStale}
                        onClick={save}
                      >
                        {saving ? <Database size={14} /> : <Save size={14} />}
                        {saving ? '저장 중…' : 'Binding Draft 저장'}
                      </button>
                    </span>
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
      open={Boolean(cancelTarget)}
      title="A-Box Ingestion 취소"
      description="현재 job version을 ETag로 확인한 뒤 취소 요청과 사유를 감사 증거로 기록합니다."
      onRequestClose={() => {
        if (!ingestionActionJobId) {
          setCancelTarget(undefined)
          setCancelReason('')
        }
      }}
      footer={<>
        <button
          type="button"
          className="button button-secondary"
          disabled={Boolean(ingestionActionJobId)}
          onClick={() => {
            setCancelTarget(undefined)
            setCancelReason('')
          }}
        >
          닫기
        </button>
        <button
          type="button"
          className="button"
          disabled={Boolean(ingestionActionJobId) || !cancelReason.trim()}
          onClick={() => void cancelIngestion()}
        >
          {ingestionActionJobId ? '취소 요청 중…' : 'Ingestion 취소 요청'}
        </button>
      </>}
    >
      <label className="grid gap-1 text-xs font-black text-navy-900">
        취소 사유
        <textarea
          className="min-h-24"
          maxLength={500}
          value={cancelReason}
          onChange={(event) => setCancelReason(event.target.value)}
          placeholder="취소가 필요한 운영 사유를 입력하세요."
        />
      </label>
    </Dialog>

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

    <Dialog
      open={publishDialogOpen}
      title="Knowledge Studio Release 발행"
      description="독립 검토자와 정확한 PASS receipt를 정본 Schema/Mapping Release에 함께 고정합니다."
      onRequestClose={() => {
        if (!governanceBusy) setPublishDialogOpen(false)
      }}
      footer={<>
        <button
          type="button"
          className="button button-secondary"
          disabled={governanceBusy}
          onClick={() => setPublishDialogOpen(false)}
        >
          취소
        </button>
        <button
          type="button"
          className="button"
          disabled={governanceBusy || !reviewReason.trim() || !exactPreflightPass}
          onClick={() => void publishDraft()}
        >
          <ShieldCheck size={14} />
          {governanceBusy ? '발행 중…' : '검토 승인 및 Publish'}
        </button>
      </>}
    >
      <div className="grid gap-3">
        <label className="grid gap-1 text-xs font-black text-navy-900">
          독립 검토 사유
          <textarea
            aria-label="독립 검토 사유"
            className="min-h-28"
            maxLength={2000}
            value={reviewReason}
            onChange={(event) => setReviewReason(event.target.value)}
            placeholder="검토한 Schema, Mapping, source access evidence를 기록하세요."
          />
        </label>
        <p className="m-0 text-[11px] leading-5 text-slate-500">
          작성자와 검토자는 달라야 합니다. 기존 Active Studio Release는 Archive되지만
          기존 Neo4j instance Release는 변경되지 않습니다.
        </p>
        {publishError
          ? onStepUp && onPasswordReauth && onEnroll
            ? <AssuranceNotice
                error={publishError}
                onStepUp={onStepUp}
                onPasswordReauth={onPasswordReauth}
                onEnroll={onEnroll}
                hardwareWebauthnEnabled={hardwareWebauthnEnabled}
              />
            : <p role="alert" className="m-0 text-xs text-red-700">
                {publishError instanceof Error ? publishError.message : 'Publish 권한을 확인할 수 없습니다.'}
              </p>
          : null}
      </div>
    </Dialog>

    <Dialog
      open={discardDialogOpen}
      title="Knowledge Studio Draft Discard"
      description="Draft를 영구 보존 정책에서 명시적으로 제외합니다. 정본 Release는 삭제하지 않습니다."
      onRequestClose={() => {
        if (!governanceBusy) setDiscardDialogOpen(false)
      }}
      footer={<>
        <button
          type="button"
          className="button button-secondary"
          disabled={governanceBusy}
          onClick={() => setDiscardDialogOpen(false)}
        >
          취소
        </button>
        <button
          type="button"
          className="button"
          disabled={governanceBusy}
          onClick={() => void discardDraft()}
        >
          {governanceBusy ? '처리 중…' : 'Draft Discard'}
        </button>
      </>}
    >
      <p className="m-0 text-sm leading-6 text-slate-600">
        하드 삭제가 아니라 DISCARDED lifecycle 전환입니다. 감사·복구를 위해 DB 행은 유지됩니다.
      </p>
    </Dialog>

    <Dialog
      open={previewOpen && Boolean(preview)}
      title="Knowledge Graph Preview · Dry Run"
      description="저장된 Mapping으로 실제 Row 샘플을 JSON Graph로 변환합니다. Neo4j에는 쓰지 않습니다."
      size="workspace"
      onRequestClose={() => {
        setPreviewOpen(false)
        setSelectedPreviewNodeId(undefined)
      }}
      footer={<button
        type="button"
        className="button button-secondary"
        onClick={() => {
          setPreviewOpen(false)
          setSelectedPreviewNodeId(undefined)
        }}
      >
        닫기
      </button>}
    >
      {preview && <div className="grid gap-4">
        <header className="flex flex-wrap items-center justify-between gap-2">
          <span className="badge badge-soft">
            {preview.status} · {preview.sample_size} sampled rows
          </span>
          <span className="text-[10px] text-slate-500">
            Draft {preview.draft_version} · T-Box {preview.pinned_tbox_version}
            {' · '}Binding {preview.binding_version ?? '없음'}
          </span>
        </header>
        <section className="grid gap-2 rounded-enterprise border border-slate-200 bg-slate-50 p-3 text-[11px] text-slate-700 sm:grid-cols-2">
          <span className="break-all"><strong>Source</strong> · {preview.source.asset_urn}</span>
          <span><strong>예상 결과</strong> · Node {preview.node_count} · Relation {preview.relation_count}</span>
          <span><strong>Rejected</strong> · {preview.rejected.length}</span>
          <span><strong>Unmapped</strong> · {preview.unmapped.length}</span>
          <span><strong>Provenance</strong> · {preview.provenance[0]?.source_type ?? '없음'}</span>
          <span className="break-all"><strong>Manifest</strong> · {preview.source.manifest_ref}</span>
        </section>
        {preview.graph.nodes.length > 0
          ? <div className="grid gap-4 lg:grid-cols-[minmax(520px,1.5fr)_minmax(260px,.7fr)]">
              <FlowCanvas
                ariaLabel="Knowledge Graph sample preview"
                nodes={previewFlowNodes}
                edges={previewFlowEdges}
                height={430}
                locked
                onNodeActivate={setSelectedPreviewNodeId}
              />
              <aside
                aria-label="Preview node properties"
                className="rounded-enterprise border border-slate-300 bg-slate-50 p-4"
              >
                {selectedPreviewNode
                  ? <>
                      <span className="text-[10px] font-black tracking-[.12em] text-enterprise-blue uppercase">
                        Sample node properties
                      </span>
                      <h3 className="my-1 text-sm font-black text-navy-900">
                        {selectedPreviewNode.type}
                      </h3>
                      <dl className="grid grid-cols-[minmax(90px,.5fr)_1fr] gap-x-3 gap-y-2 text-xs">
                        <dt className="font-black text-slate-500">SUBJECT_ID</dt>
                        <dd className="m-0 break-all text-navy-900">
                          {previewValue(selectedPreviewNode.identity)}
                        </dd>
                        {Object.entries(selectedPreviewNode.properties).map(([key, value]) => (
                          <div className="contents" key={key}>
                            <dt className="font-black text-slate-500">{key}</dt>
                            <dd className="m-0 break-all text-navy-900">
                              {previewValue(value)}
                            </dd>
                          </div>
                        ))}
                      </dl>
                    </>
                  : <p className="m-0 text-xs text-slate-500">
                      샘플 노드를 클릭하면 Mapping된 Property 값을 확인할 수 있습니다.
                    </p>}
              </aside>
            </div>
          : <div className="rounded-enterprise border border-dashed border-slate-300 bg-slate-50 p-6 text-center">
              <TriangleAlert className="mx-auto mb-2 text-amber-600" size={24} />
              <p className="m-0 text-sm font-black text-navy-900">Preview Graph가 생성되지 않았습니다.</p>
              <p className="mt-1 text-xs text-slate-500">아래 Validation Evidence를 확인하세요.</p>
            </div>}
        {preview.evidence.length > 0 && (
          <section aria-label="Preview Validation Evidence">
            <h3 className="mb-2 text-xs font-black text-navy-900">Validation Evidence</h3>
            <ul className="m-0 grid gap-2 p-0 text-xs">
              {preview.evidence.map((item, index) => (
                <li
                  key={`${item.code}:${item.location}:${index}`}
                  className="list-none rounded-enterprise border border-amber-200 bg-amber-50 p-2"
                >
                  <strong>{item.severity} · {item.code}</strong>
                  <span className="ml-2 text-slate-600">{item.message}</span>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>}
    </Dialog>
  </div>
}
