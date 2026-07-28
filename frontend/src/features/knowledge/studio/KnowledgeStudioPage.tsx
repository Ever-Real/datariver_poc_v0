import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Database, Network } from 'lucide-react'
import { ApiError, type ApiClient } from '../../../api/client'
import type { Page } from '../../../app/navigation'
import { Dialog } from '../../../components/common/Dialog'
import {
  knowledgeStudioLocationFromHref,
  knowledgeStudioUrl,
  type KnowledgeStudioStep,
} from '../routes/knowledgeLocation'
import { BasicInformationStep, basicInformationValid } from './basic/BasicInformationStep'
import {
  createDraftRecoveryQueue,
  knowledgeDraftRecoveryScope,
  type DraftRecoveryQueue,
  type DraftRecoveryRecord,
} from './draftRecoveryQueue'
import {
  advanceKnowledgeStudioDraft,
  autosaveKnowledgeStudioDraft,
  createKnowledgeStudioDraft,
  getKnowledgeStudioDraft,
  listKnowledgeStudioDomains,
  newKnowledgeStudioIdempotencyKey,
  type KnowledgeStudioBasicInformation,
  type KnowledgeStudioDomainOption,
  type KnowledgeStudioDraft,
} from './knowledgeStudioApi'
import { StudioShell } from './StudioShell'

const EMPTY_BASIC_INFORMATION: KnowledgeStudioBasicInformation = {
  name: '',
  endpoint_alias: '',
  domain_id: '',
  domain_source_version: '',
  classification: 'INTERNAL',
}

function fingerprint(value: KnowledgeStudioBasicInformation): string {
  return JSON.stringify(value)
}

function draftBasicInformation(draft: KnowledgeStudioDraft): KnowledgeStudioBasicInformation {
  return {
    name: draft.name,
    endpoint_alias: draft.endpoint_alias,
    domain_id: draft.domain_id,
    domain_source_version: draft.domain_source_version,
    classification: draft.classification,
  }
}

function isNetworkFailure(error: unknown): boolean {
  return !navigator.onLine || error instanceof TypeError
}

function FoundationPlaceholder({ step }: { step: Exclude<KnowledgeStudioStep, 'basic'> }) {
  const tbox = step === 'tbox'
  const Icon = tbox ? Network : Database
  return <section className="grid min-h-[420px] place-items-center rounded-enterprise border border-dashed border-slate-300 bg-white p-8 text-center">
    <div className="max-w-xl">
      <Icon className="mx-auto mb-3 text-enterprise-blue" size={38} />
      <span className="text-[10px] font-black tracking-[.14em] text-enterprise-blue uppercase">
        {tbox ? 'Step 2 · T-Box' : 'Step 3 · A-Box'}
      </span>
      <h2 className="my-2 text-lg font-black text-navy-900">
        {tbox ? 'Graph Builder canvas foundation' : 'Data Enricher mapping foundation'}
      </h2>
      <p className="m-0 text-xs leading-5 text-slate-500">
        {tbox
          ? 'Step 1 Draft가 저장되고 version fence를 통과했습니다. Block/Proposal persistence가 연결되기 전에는 LLM 또는 파일 결과를 accepted graph로 표시하지 않습니다.'
          : 'PUBLISHED T-Box target과 versioned source contract가 연결되기 전에는 실제 row mapping이나 ingestion 성공을 표시하지 않습니다.'}
      </p>
    </div>
  </section>
}

interface ConflictState {
  local: KnowledgeStudioBasicInformation
}

interface KnowledgeStudioPageProps {
  client: ApiClient
  workspaceId: string
  subjectId: string
  onNavigate: (page: Page) => void
  recoveryQueue?: DraftRecoveryQueue
  debounceMs?: number
}

export function KnowledgeStudioPage({
  client,
  workspaceId,
  subjectId,
  onNavigate,
  recoveryQueue,
  debounceMs = 1500,
}: KnowledgeStudioPageProps) {
  const location = useMemo(() => knowledgeStudioLocationFromHref(), [])
  const queue = useMemo(() => {
    if (recoveryQueue) return recoveryQueue
    try {
      return createDraftRecoveryQueue()
    } catch {
      return undefined
    }
  }, [recoveryQueue])
  const [step, setStep] = useState(location.step)
  const [draftId, setDraftId] = useState(location.draftId)
  const [etag, setEtag] = useState<string>()
  const [form, setForm] = useState<KnowledgeStudioBasicInformation>(EMPTY_BASIC_INFORMATION)
  const [domains, setDomains] = useState<KnowledgeStudioDomainOption[]>([])
  const [domainQuery, setDomainQuery] = useState('')
  const [domainsLoading, setDomainsLoading] = useState(true)
  const [initialized, setInitialized] = useState(false)
  const [busy, setBusy] = useState(false)
  const [saveStatus, setSaveStatus] = useState('서버 연결을 준비하고 있습니다.')
  const [scopeHash, setScopeHash] = useState<string>()
  const [conflict, setConflict] = useState<ConflictState>()
  const [saveSequence, setSaveSequence] = useState(0)
  const [onlineSequence, setOnlineSequence] = useState(0)
  const formRef = useRef(form)
  const draftIdRef = useRef(draftId)
  const etagRef = useRef(etag)
  const pendingRef = useRef<DraftRecoveryRecord | undefined>(undefined)
  const pendingWriteRef = useRef<Promise<boolean>>(Promise.resolve(true))
  const lastSavedFingerprintRef = useRef<string | undefined>(undefined)
  const savePromiseRef = useRef<Promise<boolean> | undefined>(undefined)

  const applyServerDraft = useCallback((
    value: KnowledgeStudioDraft,
    responseEtag: string,
    replaceForm: boolean,
  ) => {
    const basic = draftBasicInformation(value)
    setDraftId(value.id)
    setEtag(responseEtag)
    draftIdRef.current = value.id
    etagRef.current = responseEtag
    lastSavedFingerprintRef.current = fingerprint(basic)
    if (replaceForm) {
      formRef.current = basic
      setForm(basic)
    }
  }, [])

  useEffect(() => {
    if (!location.valid) onNavigate('knowledge')
  }, [location.valid, onNavigate])

  useEffect(() => {
    if (!location.valid || !workspaceId || !subjectId) return
    let active = true
    void knowledgeDraftRecoveryScope(workspaceId, subjectId)
      .then((value) => { if (active) setScopeHash(value) })
      .catch(() => {
        if (active) {
          setSaveStatus('브라우저 복구 범위를 만들 수 없어 저장을 중단했습니다.')
          setInitialized(true)
        }
      })
    return () => { active = false }
  }, [location.valid, subjectId, workspaceId])

  useEffect(() => {
    if (!location.valid || !scopeHash) return
    let active = true
    const hydrate = async () => {
      if (location.draftId) {
        try {
          const response = await getKnowledgeStudioDraft(client, location.draftId)
          if (!active || !response.etag) return
          applyServerDraft(response.data, response.etag, true)
        } catch (error) {
          if (active) {
            setSaveStatus(error instanceof Error ? error.message : 'Draft를 불러오지 못했습니다.')
          }
        }
      } else {
        lastSavedFingerprintRef.current = fingerprint(EMPTY_BASIC_INFORMATION)
      }
      try {
        if (!queue) {
          if (active) setSaveStatus('IndexedDB 복구 큐를 사용할 수 없어 저장이 비활성화되었습니다.')
          return
        }
        const recovered = await queue.read(scopeHash, location.draftId)
        if (!active) return
        if (recovered) {
          pendingRef.current = recovered
          formRef.current = recovered.payload
          setForm(recovered.payload)
          setSaveStatus('이 브라우저에 남아 있던 미전송 변경사항을 복구했습니다.')
          setSaveSequence((value) => value + 1)
        } else {
          setSaveStatus(location.draftId ? '서버 Draft를 불러왔습니다.' : '입력을 시작하면 복구 큐에 보존됩니다.')
        }
      } catch {
        if (!active) return
        setSaveStatus('브라우저 복구 큐를 읽지 못해 저장을 중단했습니다.')
      } finally {
        if (active) setInitialized(true)
      }
    }
    void hydrate()
    return () => { active = false }
  }, [applyServerDraft, client, location.draftId, location.valid, queue, scopeHash])

  useEffect(() => {
    if (!location.valid || !initialized) return
    const controller = new AbortController()
    setDomainsLoading(true)
    const timer = window.setTimeout(() => {
      void listKnowledgeStudioDomains(
        client,
        form.classification,
        domainQuery,
        controller.signal,
      )
        .then(setDomains)
        .catch((error: unknown) => {
          if (controller.signal.aborted) return
          setDomains([])
          setSaveStatus(error instanceof Error ? error.message : '업무 도메인을 불러오지 못했습니다.')
        })
        .finally(() => {
          if (!controller.signal.aborted) setDomainsLoading(false)
        })
    }, 250)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [client, domainQuery, form.classification, initialized, location.valid])

  useEffect(() => {
    const online = () => {
      setSaveStatus('네트워크가 복구되어 보류 중인 Draft 저장을 재시도합니다.')
      setOnlineSequence((value) => value + 1)
    }
    window.addEventListener('online', online)
    return () => window.removeEventListener('online', online)
  }, [])

  useEffect(() => {
    const warnBeforeLeave = (event: BeforeUnloadEvent) => {
      if (!pendingRef.current) return
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warnBeforeLeave)
    return () => window.removeEventListener('beforeunload', warnBeforeLeave)
  }, [])

  const queueForm = useCallback((next: KnowledgeStudioBasicInformation) => {
    formRef.current = next
    setForm(next)
    if (!queue || !scopeHash) {
      setSaveStatus('브라우저 복구 큐가 준비되지 않아 저장하지 않았습니다.')
      return
    }
    if (fingerprint(next) === lastSavedFingerprintRef.current) {
      const pending = pendingRef.current
      pendingRef.current = undefined
      if (pending) {
        pendingWriteRef.current = queue.remove(
          scopeHash,
          pending.draftId,
          pending.idempotencyKey,
        ).then(() => true).catch(() => false)
      }
      setSaveStatus('서버에 저장된 내용과 같습니다.')
      return
    }
    const pending: DraftRecoveryRecord = {
      key: '',
      scopeHash,
      draftId: draftIdRef.current,
      payload: next,
      expectedEtag: etagRef.current,
      idempotencyKey: newKnowledgeStudioIdempotencyKey(),
      updatedAt: new Date().toISOString(),
    }
    pendingRef.current = pending
    pendingWriteRef.current = queue.put(pending)
      .then(() => {
        setSaveStatus(
          basicInformationValid(next)
            ? '변경사항을 복구 큐에 보존했습니다. 자동 저장 대기 중입니다.'
            : '작성 중인 입력을 복구 큐에 보존했습니다.',
        )
        return true
      })
      .catch(() => {
        setSaveStatus('복구 큐 기록에 실패하여 서버 전송을 중단했습니다.')
        return false
      })
    setSaveSequence((value) => value + 1)
  }, [queue, scopeHash])

  const performPendingSave = useCallback(async (): Promise<boolean> => {
    const pending = pendingRef.current
    if (!pending || !queue || !scopeHash || !basicInformationValid(pending.payload)) {
      return !pending
    }
    if (!navigator.onLine) {
      setSaveStatus('오프라인입니다. 변경사항은 복구 큐에 보존되어 있습니다.')
      return false
    }
    if (!await pendingWriteRef.current) {
      setSaveStatus('복구 큐 기록을 확인할 수 없어 서버 전송을 중단했습니다.')
      return false
    }
    const currentDraftId = draftIdRef.current
    const rebased: DraftRecoveryRecord = {
      ...pending,
      draftId: pending.draftId ?? currentDraftId,
    }
    pendingRef.current = rebased
    if (
      rebased.draftId !== pending.draftId
    ) {
      try {
        await queue.put(rebased)
        await queue.remove(scopeHash, pending.draftId, pending.idempotencyKey)
      } catch {
        setSaveStatus('복구 큐의 Draft 식별자를 갱신하지 못해 서버 전송을 중단했습니다.')
        return false
      }
    }
    setBusy(true)
    setSaveStatus('서버 Draft에 저장 중입니다.')
    try {
      if (currentDraftId && !rebased.expectedEtag) {
        setSaveStatus('저장할 Draft의 ETag가 없어 안전한 자동 저장을 중단했습니다.')
        return false
      }
      const response = currentDraftId
        ? await autosaveKnowledgeStudioDraft(
            client,
            currentDraftId,
            rebased.payload,
            rebased.expectedEtag ?? '',
            rebased.idempotencyKey,
          )
        : await createKnowledgeStudioDraft(client, rebased.payload, rebased.idempotencyKey)
      if (!response.etag) return false
      const sentFingerprint = fingerprint(rebased.payload)
      applyServerDraft(response.data, response.etag, false)
      await queue.remove(scopeHash, rebased.draftId, rebased.idempotencyKey)
      if (!currentDraftId) {
        const url = knowledgeStudioUrl({ draftId: response.data.id, step: 'basic' })
        window.history.replaceState({}, '', url)
      }
      if (pendingRef.current?.idempotencyKey === rebased.idempotencyKey) {
        pendingRef.current = undefined
      } else if (pendingRef.current) {
        const newer = {
          ...pendingRef.current,
          draftId: response.data.id,
          expectedEtag: response.etag,
        }
        const previousDraftId = pendingRef.current.draftId
        pendingRef.current = newer
        pendingWriteRef.current = queue.put(newer)
          .then(() => queue.remove(scopeHash, previousDraftId, newer.idempotencyKey))
          .then(() => true)
          .catch(() => {
            setSaveStatus('새 변경사항의 복구 큐 갱신에 실패했습니다.')
            return false
          })
      }
      lastSavedFingerprintRef.current = sentFingerprint
      setSaveStatus(`자동 저장 완료 · version ${response.data.version}`)
      if (pendingRef.current) setSaveSequence((value) => value + 1)
      return true
    } catch (error) {
      if (error instanceof ApiError && error.problem.status === 412) {
        setConflict({ local: rebased.payload })
        setSaveStatus('다른 편집자의 변경사항과 충돌했습니다. 로컬 입력은 보존되어 있습니다.')
      } else if (isNetworkFailure(error)) {
        setSaveStatus('네트워크가 끊겼습니다. 변경사항은 복구 큐에 보존되어 있습니다.')
      } else {
        setSaveStatus(error instanceof Error ? error.message : 'Draft 저장에 실패했습니다.')
      }
      return false
    } finally {
      setBusy(false)
    }
  }, [applyServerDraft, client, queue, scopeHash])

  const savePending = useCallback(async (): Promise<boolean> => {
    savePromiseRef.current ??= performPendingSave()
      .finally(() => { savePromiseRef.current = undefined })
    return savePromiseRef.current
  }, [performPendingSave])

  const flushLatest = useCallback(async (): Promise<boolean> => {
    for (let attempt = 0; attempt < 4; attempt += 1) {
      if (!pendingRef.current) return Boolean(draftIdRef.current)
      const saved = await savePending()
      if (!saved || conflict) return false
    }
    setSaveStatus('입력이 계속 변경되고 있습니다. 잠시 후 다시 저장하세요.')
    return false
  }, [conflict, savePending])

  useEffect(() => {
    if (!initialized || conflict || !pendingRef.current) return
    if (!basicInformationValid(pendingRef.current.payload)) return
    const timer = window.setTimeout(() => { void savePending() }, debounceMs)
    return () => window.clearTimeout(timer)
  }, [conflict, debounceMs, initialized, onlineSequence, savePending, saveSequence])

  const reloadLatest = async () => {
    const currentDraftId = draftIdRef.current
    const pending = pendingRef.current
    if (!currentDraftId || !queue || !scopeHash) return
    setBusy(true)
    try {
      const response = await getKnowledgeStudioDraft(client, currentDraftId)
      if (!response.etag) return
      applyServerDraft(response.data, response.etag, true)
      if (pending) await queue.remove(scopeHash, pending.draftId, pending.idempotencyKey)
      pendingRef.current = undefined
      setConflict(undefined)
      setSaveStatus(`최신 서버 version ${response.data.version}을 불러왔습니다.`)
    } catch (error) {
      setSaveStatus(error instanceof Error ? error.message : '최신 Draft를 불러오지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  const overwriteLatest = async () => {
    const currentDraftId = draftIdRef.current
    if (!currentDraftId || !conflict || !queue || !scopeHash) return
    setBusy(true)
    try {
      const latest = await getKnowledgeStudioDraft(client, currentDraftId)
      if (!latest.etag) return
      applyServerDraft(latest.data, latest.etag, false)
      const pending: DraftRecoveryRecord = {
        key: '',
        scopeHash,
        draftId: currentDraftId,
        payload: conflict.local,
        expectedEtag: latest.etag,
        idempotencyKey: newKnowledgeStudioIdempotencyKey(),
        updatedAt: new Date().toISOString(),
      }
      pendingRef.current = pending
      pendingWriteRef.current = queue.put(pending)
        .then(() => true)
        .catch(() => false)
      if (!await pendingWriteRef.current) {
        setSaveStatus('복구 큐 기록에 실패하여 덮어쓰기를 중단했습니다.')
        return
      }
      setConflict(undefined)
      setBusy(false)
      await savePending()
    } catch (error) {
      setSaveStatus(error instanceof Error ? error.message : '로컬 변경사항을 다시 저장하지 못했습니다.')
      setBusy(false)
    }
  }

  const continueToTbox = async () => {
    if (!await flushLatest()) return
    const currentDraftId = draftIdRef.current
    const currentEtag = etagRef.current
    if (!currentDraftId || !currentEtag) return
    setBusy(true)
    try {
      const response = await advanceKnowledgeStudioDraft(
        client,
        currentDraftId,
        currentEtag,
        newKnowledgeStudioIdempotencyKey(),
      )
      if (!response.etag) return
      applyServerDraft(response.data, response.etag, false)
      const url = knowledgeStudioUrl({ draftId: currentDraftId, step: 'tbox' })
      window.history.pushState({}, '', url)
      setStep('tbox')
      setSaveStatus(`Step 1 저장 완료 · version ${response.data.version}`)
    } catch (error) {
      if (error instanceof ApiError && error.problem.status === 412) {
        setConflict({ local: formRef.current })
        setSaveStatus('단계 전환 전에 다른 편집자의 변경사항이 확인되었습니다.')
      } else if (isNetworkFailure(error)) {
        try {
          const latest = await getKnowledgeStudioDraft(client, currentDraftId)
          if (latest.data.current_step === 'TBOX' && latest.etag) {
            applyServerDraft(latest.data, latest.etag, false)
            const url = knowledgeStudioUrl({ draftId: currentDraftId, step: 'tbox' })
            window.history.pushState({}, '', url)
            setStep('tbox')
          } else {
            setSaveStatus('단계 전환 결과를 확인하지 못했습니다. 다시 시도하세요.')
          }
        } catch {
          setSaveStatus('오프라인으로 단계 전환 결과를 확인하지 못했습니다.')
        }
      } else {
        setSaveStatus(error instanceof Error ? error.message : 'Graph Builder로 이동하지 못했습니다.')
      }
    } finally {
      setBusy(false)
    }
  }

  if (!location.valid) return null

  return <StudioShell
    step={step}
    draftId={draftId}
    saveStatus={saveStatus}
    onBack={() => {
      if (pendingRef.current && !window.confirm('미전송 변경사항은 이 브라우저의 복구 큐에 남습니다. 레지스트리로 이동하시겠습니까?')) return
      onNavigate('knowledge')
    }}
  >
    {step === 'basic' && !initialized
      ? <section className="grid min-h-[320px] place-items-center rounded-enterprise border border-slate-300 bg-white p-8 text-sm text-slate-500">
          Draft와 브라우저 복구 큐를 확인하고 있습니다.
        </section>
      : step === 'basic'
      ? <BasicInformationStep
          value={form}
          domains={domains}
          domainsLoading={domainsLoading}
          domainQuery={domainQuery}
          busy={busy || !initialized || !queue}
          saveStatus={saveStatus}
          onChange={queueForm}
          onDomainQueryChange={setDomainQuery}
          onSave={() => { void flushLatest() }}
          onContinue={() => { void continueToTbox() }}
        />
      : <FoundationPlaceholder step={step} />}
    <Dialog
      open={Boolean(conflict)}
      title="동시 편집 충돌"
      description="다른 사용자에 의해 변경사항이 발생했습니다. 로컬 입력은 아직 삭제되지 않았습니다."
      onRequestClose={() => undefined}
      footer={<>
        <button type="button" className="button button-secondary" disabled={busy} onClick={() => void reloadLatest()}>
          최신 버전 불러오기
        </button>
        <button type="button" className="button" disabled={busy} onClick={() => void overwriteLatest()}>
          내 변경사항으로 덮어쓰기
        </button>
      </>}
    >
      <p className="m-0 text-sm leading-6 text-slate-600">
        최신 버전을 불러오면 현재 로컬 입력을 명시적으로 폐기합니다. 덮어쓰기를 선택하면
        서버의 최신 ETag를 다시 읽은 뒤 보존된 로컬 입력을 새 version fence로 저장합니다.
      </p>
    </Dialog>
  </StudioShell>
}
