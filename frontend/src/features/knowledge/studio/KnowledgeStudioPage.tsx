import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, type ApiClient } from '../../../api/client'
import type { Page } from '../../../app/navigation'
import { Dialog } from '../../../components/common/Dialog'
import {
  knowledgeStudioLocationFromHref,
  knowledgeStudioUrl,
} from '../routes/knowledgeLocation'
import { BasicInformationStep, basicInformationValid } from './basic/BasicInformationStep'
import {
  createDraftRecoveryQueue,
  knowledgeDraftRecoveryScope,
  type DraftRecoveryQueue,
  type DraftRecoveryRecord,
} from './draftRecoveryQueue'
import { DataEnricherStep } from './abox/DataEnricherStep'
import {
  advanceKnowledgeStudioDraft,
  autosaveKnowledgeStudioDraft,
  createKnowledgeStudioDraft,
  createKnowledgeStudioEditDraft,
  createKnowledgeStudioManagedDomain,
  getKnowledgeStudioDraft,
  getResumableKnowledgeStudioDraft,
  listKnowledgeStudioDomains,
  newKnowledgeStudioIdempotencyKey,
  type KnowledgeStudioBasicInformation,
  type KnowledgeStudioDomainOption,
  type KnowledgeStudioDraft,
} from './knowledgeStudioApi'
import { useKnowledgeStudioSessionStore } from './knowledgeStudioSessionStore'
import { StudioShell } from './StudioShell'
import { GraphBuilder } from './tbox/GraphBuilder'

const DEFAULT_INITIALIZATION_TIMEOUT_MS = 8_000
const DEFAULT_DOMAIN_REQUEST_TIMEOUT_MS = 10_000

const EMPTY_BASIC_INFORMATION: KnowledgeStudioBasicInformation = {
  name: '',
  description: '',
  endpoint_alias: '',
  endpoint_aliases: [],
  domain_id: '',
  domain_source_version: '',
  classification: 'normal',
}

function fingerprint(value: KnowledgeStudioBasicInformation): string {
  return JSON.stringify(value)
}

function draftBasicInformation(draft: KnowledgeStudioDraft): KnowledgeStudioBasicInformation {
  return {
    name: draft.name,
    description: draft.description ?? '',
    endpoint_alias: draft.endpoint_alias,
    endpoint_aliases: draft.endpoint_aliases ?? [draft.endpoint_alias],
    domain_id: draft.domain_id,
    domain_source_version: draft.domain_source_version,
    classification: draft.classification,
  }
}

function isNetworkFailure(error: unknown): boolean {
  return !navigator.onLine || error instanceof TypeError
}

function rejectAfter<T>(
  promise: Promise<T>,
  timeoutMs: number,
  message: string,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => reject(new Error(message)), timeoutMs)
    promise.then(
      (value) => {
        window.clearTimeout(timeout)
        resolve(value)
      },
      (error: unknown) => {
        window.clearTimeout(timeout)
        reject(error instanceof Error ? error : new Error('비동기 작업이 실패했습니다.'))
      },
    )
  })
}

interface ConflictState {
  local: KnowledgeStudioBasicInformation
}

interface KnowledgeStudioPageProps {
  client: ApiClient
  workspaceId: string
  subjectId: string
  locationRevision?: number
  onNavigate: (page: Page) => void
  onStepUp?: () => Promise<void>
  onPasswordReauth?: () => Promise<void>
  onEnroll?: () => Promise<void>
  hardwareWebauthnEnabled?: boolean
  recoveryQueue?: DraftRecoveryQueue
  debounceMs?: number
  initializationTimeoutMs?: number
  domainRequestTimeoutMs?: number
}

export function KnowledgeStudioPage({
  client,
  workspaceId,
  subjectId,
  locationRevision = 0,
  onNavigate,
  onStepUp,
  onPasswordReauth,
  onEnroll,
  hardwareWebauthnEnabled,
  recoveryQueue,
  debounceMs = 1500,
  initializationTimeoutMs = DEFAULT_INITIALIZATION_TIMEOUT_MS,
  domainRequestTimeoutMs = DEFAULT_DOMAIN_REQUEST_TIMEOUT_MS,
}: KnowledgeStudioPageProps) {
  const location = useMemo(
    () => {
      void locationRevision
      return knowledgeStudioLocationFromHref()
    },
    [locationRevision],
  )
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
  const [serverDraft, setServerDraft] = useState<KnowledgeStudioDraft>()
  const [form, setForm] = useState<KnowledgeStudioBasicInformation>(EMPTY_BASIC_INFORMATION)
  const [domains, setDomains] = useState<KnowledgeStudioDomainOption[]>([])
  const [domainQuery, setDomainQuery] = useState('')
  const [domainsLoading, setDomainsLoading] = useState(true)
  const [domainsError, setDomainsError] = useState('')
  const [domainLoadSequence, setDomainLoadSequence] = useState(0)
  const [initialized, setInitialized] = useState(false)
  const [initializationError, setInitializationError] = useState('')
  const [initializationSequence, setInitializationSequence] = useState(0)
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
  const setSessionBasic = useKnowledgeStudioSessionStore((state) => state.setBasic)
  const setSessionStep = useKnowledgeStudioSessionStore((state) => state.setStep)

  const reloadDomains = useCallback(async (
    classification = formRef.current.classification,
    signal?: AbortSignal,
  ) => {
    const refreshed = await listKnowledgeStudioDomains(
      client,
      classification,
      undefined,
      signal,
    )
    setDomains(refreshed)
    return refreshed
  }, [client])

  const applyServerDraft = useCallback((
    value: KnowledgeStudioDraft,
    responseEtag: string,
    replaceForm: boolean,
    preferSession = true,
  ) => {
    const basic = draftBasicInformation(value)
    setDraftId(value.id)
    setEtag(responseEtag)
    setServerDraft(value)
    draftIdRef.current = value.id
    etagRef.current = responseEtag
    lastSavedFingerprintRef.current = fingerprint(basic)
    if (replaceForm) {
      const cached = preferSession
        ? useKnowledgeStudioSessionStore.getState().sessions[value.id]?.basic
        : undefined
      const next = cached ?? basic
      formRef.current = next
      setForm(next)
      setSessionBasic(value.id, next)
    }
  }, [setSessionBasic])
  const applyChildDraft = useCallback((
    value: KnowledgeStudioDraft,
    responseEtag: string,
  ) => {
    applyServerDraft(value, responseEtag, false)
  }, [applyServerDraft])

  useEffect(() => {
    if (!location.valid) onNavigate('knowledge')
  }, [location.valid, onNavigate])

  useEffect(() => {
    if (!location.valid || !workspaceId || !subjectId || scopeHash) return
    let active = true
    setInitialized(false)
    setInitializationError('')
    void rejectAfter(
      knowledgeDraftRecoveryScope(workspaceId, subjectId),
      initializationTimeoutMs,
      '브라우저 Draft 복구 범위를 제한 시간 안에 계산하지 못했습니다.',
    )
      .then((value) => { if (active) setScopeHash(value) })
      .catch((error: unknown) => {
        if (active) {
          const message = error instanceof Error
            ? error.message
            : '브라우저 Draft 복구 범위를 만들 수 없습니다.'
          setInitializationError(message)
          setSaveStatus(message)
          setInitialized(true)
        }
      })
    return () => { active = false }
  }, [
    initializationSequence,
    initializationTimeoutMs,
    location.valid,
    scopeHash,
    subjectId,
    workspaceId,
  ])

  useEffect(() => {
    if (!location.valid || !scopeHash) return
    let active = true
    const hydrate = async () => {
      setInitialized(false)
      setInitializationError('')
      setStep(location.step)
      if (location.draftId) setSessionStep(location.draftId, location.step)
      setDraftId(location.draftId)
      draftIdRef.current = location.draftId
      let recoveryDraftId = location.draftId
      let hydratedFromServer = false
      if (location.assetId) {
        try {
          const response = await createKnowledgeStudioEditDraft(
            client,
            location.assetId,
            newKnowledgeStudioIdempotencyKey(),
          )
          if (!active || !response.etag) return
          recoveryDraftId = response.data.id
          hydratedFromServer = true
          applyServerDraft(response.data, response.etag, true)
          const resumeStep = response.data.current_step === 'ABOX'
            ? 'abox'
            : response.data.current_step === 'TBOX'
              ? 'tbox'
              : 'basic'
          setStep(resumeStep)
          window.history.replaceState(
            {},
            '',
            knowledgeStudioUrl({ draftId: response.data.id, step: resumeStep }),
          )
        } catch (error) {
          if (active) {
            setSaveStatus(
              error instanceof Error
                ? error.message
                : '선택한 지식 에셋의 편집 Draft를 열지 못했습니다.',
            )
            setInitialized(true)
          }
          return
        }
      } else if (location.draftId) {
        try {
          const response = await getKnowledgeStudioDraft(client, location.draftId)
          if (!active || !response.etag) return
          hydratedFromServer = true
          applyServerDraft(response.data, response.etag, true)
          if (response.data.state !== 'DRAFT') {
            setSaveStatus(
              response.data.state === 'REVIEW'
                ? '독립 검토 중인 Draft입니다. 편집과 자동 저장은 잠겨 있습니다.'
                : `Draft lifecycle: ${response.data.state}`,
            )
            setInitialized(true)
            return
          }
        } catch (error) {
          if (active) {
            setSaveStatus(error instanceof Error ? error.message : 'Draft를 불러오지 못했습니다.')
          }
        }
      }
      if (!hydratedFromServer) {
        lastSavedFingerprintRef.current = fingerprint(EMPTY_BASIC_INFORMATION)
      }
      try {
        if (!queue) {
          if (active) {
            const message = '브라우저 Draft 복구 저장소를 사용할 수 없습니다.'
            setInitializationError(message)
            setSaveStatus(`${message} 편집을 시작하지 않습니다.`)
          }
          return
        }
        const recovered = await rejectAfter(
          queue.read(scopeHash, recoveryDraftId),
          initializationTimeoutMs,
          '브라우저 Draft 복구 저장소가 제한 시간 안에 응답하지 않았습니다.',
        )
        if (!active) return
        if (recovered) {
          pendingRef.current = recovered
          formRef.current = recovered.payload
          setForm(recovered.payload)
          setSaveStatus('이 브라우저에 남아 있던 미전송 변경사항을 복구했습니다.')
          setSaveSequence((value) => value + 1)
        } else {
          setSaveStatus(
            recoveryDraftId
              ? '서버 Draft를 불러왔습니다.'
              : '입력을 시작하면 복구 큐에 보존됩니다.',
          )
        }
      } catch (error) {
        if (!active) return
        const message = error instanceof Error
          ? error.message
          : '브라우저 복구 큐를 읽지 못했습니다.'
        setInitializationError(message)
        setSaveStatus(`${message} 재시도하기 전까지 편집을 시작하지 않습니다.`)
      } finally {
        if (active) setInitialized(true)
      }
    }
    void hydrate()
    return () => { active = false }
  }, [
    applyServerDraft,
    client,
    location.assetId,
    location.draftId,
    location.step,
    location.valid,
    initializationSequence,
    initializationTimeoutMs,
    queue,
    scopeHash,
    setSessionStep,
  ])

  useEffect(() => {
    if (!location.valid || !initialized || initializationError) return
    const controller = new AbortController()
    let active = true
    let timedOut = false
    setDomainsError('')
    setDomainsLoading(true)
    const timer = window.setTimeout(() => {
      const requestTimeout = window.setTimeout(() => {
        timedOut = true
        controller.abort()
        if (!active) return
        const message = '업무 도메인 조회가 제한 시간 안에 완료되지 않았습니다.'
        setDomains([])
        setDomainsError(message)
        setSaveStatus(message)
        setDomainsLoading(false)
      }, domainRequestTimeoutMs)
      void reloadDomains(form.classification, controller.signal)
        .catch((error: unknown) => {
          if (!active || timedOut) return
          setDomains([])
          const message = error instanceof Error ? error.message : '업무 도메인을 불러오지 못했습니다.'
          setDomainsError(message)
          setSaveStatus(message)
        })
        .finally(() => {
          window.clearTimeout(requestTimeout)
          if (active && !timedOut) setDomainsLoading(false)
        })
    }, 250)
    return () => {
      active = false
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [
    domainLoadSequence,
    domainRequestTimeoutMs,
    form.classification,
    initialized,
    initializationError,
    location.valid,
    reloadDomains,
  ])

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
    if (serverDraft && serverDraft.state !== 'DRAFT') {
      setSaveStatus('DRAFT 상태가 아니므로 입력과 자동 저장을 허용하지 않습니다.')
      return
    }
    formRef.current = next
    setForm(next)
    if (draftIdRef.current) setSessionBasic(draftIdRef.current, next)
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
  }, [queue, scopeHash, serverDraft, setSessionBasic])

  const performPendingSave = useCallback(async (): Promise<boolean> => {
    const pending = pendingRef.current
    if (!pending || !queue || !scopeHash || !basicInformationValid(pending.payload)) {
      return !pending
    }
    if (serverDraft && serverDraft.state !== 'DRAFT') {
      setSaveStatus('DRAFT 상태가 아니므로 자동 저장을 중단했습니다.')
      return false
    }
    if (!navigator.onLine) {
      setSaveStatus('오프라인입니다. 변경사항은 복구 큐에 보존되어 있습니다.')
      return false
    }
    if (!await pendingWriteRef.current) {
      setSaveStatus('복구 큐 기록을 확인할 수 없어 서버 전송을 중단했습니다.')
      return false
    }
    let currentDraftId = draftIdRef.current
    const needsDraftRoute = !currentDraftId
    let savingRecord: DraftRecoveryRecord = {
      ...pending,
      draftId: pending.draftId ?? currentDraftId,
      expectedEtag: pending.expectedEtag ?? etagRef.current,
    }
    const bindSavingRecord = async (
      response: Awaited<ReturnType<typeof getResumableKnowledgeStudioDraft>>,
      idempotencyKey = savingRecord.idempotencyKey,
    ) => {
      const previous = savingRecord
      savingRecord = {
        ...savingRecord,
        draftId: response.data.id,
        expectedEtag: response.etag,
        idempotencyKey,
        updatedAt: new Date().toISOString(),
      }
      currentDraftId = response.data.id
      applyServerDraft(response.data, response.etag!, false)
      try {
        await queue.put(savingRecord)
        await queue.remove(scopeHash, previous.draftId, previous.idempotencyKey)
      } catch {
        setSaveStatus('복구 큐의 Draft 식별자를 갱신하지 못해 서버 전송을 중단했습니다.')
        return false
      }
      if (pendingRef.current?.idempotencyKey === previous.idempotencyKey) {
        pendingRef.current = savingRecord
      }
      return true
    }
    if (savingRecord.draftId !== pending.draftId) {
      try {
        await queue.put(savingRecord)
        await queue.remove(scopeHash, pending.draftId, pending.idempotencyKey)
      } catch {
        setSaveStatus('복구 큐의 Draft 식별자를 갱신하지 못해 서버 전송을 중단했습니다.')
        return false
      }
    }
    if (pendingRef.current?.idempotencyKey === pending.idempotencyKey) {
      pendingRef.current = savingRecord
    }
    setBusy(true)
    setSaveStatus('서버 Draft에 저장 중입니다.')
    try {
      if (!currentDraftId) {
        try {
          const resumable = await getResumableKnowledgeStudioDraft(
            client,
            savingRecord.payload.endpoint_alias,
          )
          if (!await bindSavingRecord(resumable)) return false
          setSaveStatus(`기존 Draft version ${resumable.data.version}을 이어서 저장합니다.`)
        } catch (error) {
          if (!(error instanceof ApiError) || error.problem.status !== 404) throw error
        }
      }
      if (currentDraftId && !savingRecord.expectedEtag) {
        setSaveStatus('저장할 Draft의 ETag가 없어 안전한 자동 저장을 중단했습니다.')
        return false
      }
      let response
      try {
        response = currentDraftId
          ? await autosaveKnowledgeStudioDraft(
              client,
              currentDraftId,
              savingRecord.payload,
              savingRecord.expectedEtag ?? '',
              savingRecord.idempotencyKey,
            )
          : await createKnowledgeStudioDraft(
              client,
              savingRecord.payload,
              savingRecord.idempotencyKey,
            )
      } catch (error) {
        if (
          currentDraftId
          || !(error instanceof ApiError)
          || error.problem.status !== 409
        ) throw error
        let resumable: Awaited<ReturnType<typeof getResumableKnowledgeStudioDraft>>
        try {
          resumable = await getResumableKnowledgeStudioDraft(
            client,
            savingRecord.payload.endpoint_alias,
          )
        } catch (resumeError) {
          // A create race can converge only when the conflicting Draft belongs
          // to this author. Preserve the original 409 when the non-disclosing
          // lookup still returns 404 (another author or a published graph).
          if (
            resumeError instanceof ApiError
            && resumeError.problem.status === 404
          ) throw error
          throw resumeError
        }
        if (!await bindSavingRecord(resumable, newKnowledgeStudioIdempotencyKey())) return false
        response = await autosaveKnowledgeStudioDraft(
          client,
          resumable.data.id,
          savingRecord.payload,
          savingRecord.expectedEtag!,
          savingRecord.idempotencyKey,
        )
      }
      if (!response.etag) return false
      const sentFingerprint = fingerprint(savingRecord.payload)
      applyServerDraft(response.data, response.etag, false)
      await queue.remove(
        scopeHash,
        savingRecord.draftId,
        savingRecord.idempotencyKey,
      )
      if (needsDraftRoute) {
        const url = knowledgeStudioUrl({ draftId: response.data.id, step: 'basic' })
        window.history.replaceState({}, '', url)
      }
      if (pendingRef.current?.idempotencyKey === savingRecord.idempotencyKey) {
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
        setConflict({ local: savingRecord.payload })
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
  }, [applyServerDraft, client, queue, scopeHash, serverDraft])

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
      applyServerDraft(response.data, response.etag, true, false)
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
      setSessionStep(currentDraftId, 'tbox')
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
            setSessionStep(currentDraftId, 'tbox')
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

  const continueToAbox = async () => {
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
        'ABOX',
      )
      if (!response.etag) return
      applyServerDraft(response.data, response.etag, false)
      const url = knowledgeStudioUrl({ draftId: currentDraftId, step: 'abox' })
      window.history.pushState({}, '', url)
      setStep('abox')
      setSessionStep(currentDraftId, 'abox')
      setSaveStatus(`Data Enricher 진입 완료 · version ${response.data.version}`)
    } catch (error) {
      if (error instanceof ApiError && error.problem.status === 412) {
        setSaveStatus('T-Box가 다른 세션에서 변경되었습니다. 최신 Draft를 다시 불러오세요.')
      } else {
        setSaveStatus(error instanceof Error ? error.message : 'Data Enricher를 열지 못했습니다.')
      }
    } finally {
      setBusy(false)
    }
  }

  const selectStep = (target: 'basic' | 'tbox' | 'abox') => {
    const currentDraftId = draftIdRef.current
    if (!currentDraftId || target === step) return
    if (target === 'abox' && serverDraft?.current_step !== 'ABOX') {
      void continueToAbox()
      return
    }
    if (
      target === 'tbox'
      && serverDraft?.current_step !== 'TBOX'
      && serverDraft?.current_step !== 'ABOX'
    ) {
      void continueToTbox()
      return
    }
    const url = knowledgeStudioUrl({ draftId: currentDraftId, step: target })
    window.history.pushState({}, '', url)
    setStep(target)
    setSessionStep(currentDraftId, target)
  }

  const createDomain = async (displayName: string) => {
    setBusy(true)
    setSaveStatus('새 업무 도메인을 등록하고 있습니다.')
    try {
      const created = await createKnowledgeStudioManagedDomain(
        client,
        displayName,
        newKnowledgeStudioIdempotencyKey(),
      )
      const refreshed = await reloadDomains()
      if (!refreshed.some((item) => item.id === created.id)) {
        throw new Error('등록된 도메인이 현재 작성자 범위에 반영되지 않았습니다.')
      }
      setDomains(refreshed)
      queueForm({
        ...formRef.current,
        domain_id: created.id,
        domain_source_version: created.source_version,
      })
      setSaveStatus(`'${created.display_name}' 도메인을 등록하고 선택했습니다.`)
    } catch (error) {
      setSaveStatus(error instanceof Error ? error.message : '새 업무 도메인을 등록하지 못했습니다.')
      throw error
    } finally {
      setBusy(false)
    }
  }

  const handleBack = useCallback(() => {
    if (
      pendingRef.current
      && !window.confirm(
        '미전송 변경사항은 이 브라우저의 복구 큐에 남습니다. 레지스트리로 이동하시겠습니까?',
      )
    ) return
    onNavigate('knowledge')
  }, [onNavigate])

  const retryInitialization = useCallback(() => {
    setSaveStatus('Draft와 브라우저 복구 큐를 다시 확인하고 있습니다.')
    setInitializationSequence((value) => value + 1)
  }, [])

  const retryDomains = useCallback(() => {
    setDomainLoadSequence((value) => value + 1)
  }, [])

  if (!location.valid) return null

  return <StudioShell
    step={step}
    draftId={draftId}
    saveStatus={saveStatus}
    onBack={handleBack}
    onStepSelect={selectStep}
  >
    {initializationError
      ? <section
          className="grid min-h-[320px] place-items-center rounded-enterprise border border-red-200 bg-white p-8 text-center"
          role="alert"
        >
          <div className="max-w-xl">
            <h2 className="m-0 text-base font-black text-red-900">Knowledge Studio 초기화 실패</h2>
            <p className="mb-4 mt-2 text-sm leading-6 text-slate-600">{initializationError}</p>
            <div className="flex justify-center gap-2">
              <button type="button" className="button button-secondary" onClick={handleBack}>
                레지스트리로 돌아가기
              </button>
              <button type="button" className="button" onClick={retryInitialization}>
                초기화 다시 시도
              </button>
            </div>
          </div>
        </section>
      : step === 'basic' && !initialized
      ? <section className="grid min-h-[320px] place-items-center rounded-enterprise border border-slate-300 bg-white p-8 text-sm text-slate-500">
          Draft와 브라우저 복구 큐를 확인하고 있습니다.
        </section>
      : step === 'basic' && serverDraft && serverDraft.state !== 'DRAFT'
      ? <section className="rounded-enterprise border border-blue-200 bg-blue-50 p-5 text-sm text-blue-950">
          이 Studio Draft는 <strong>{serverDraft.state}</strong> 상태이므로 기본정보를 수정할 수 없습니다.
          Data Enricher에서 검토·발행 상태와 증거를 확인하세요.
        </section>
      : step === 'basic'
      ? <BasicInformationStep
          value={form}
          domains={domains}
          domainsLoading={domainsLoading}
          domainsError={domainsError}
          domainQuery={domainQuery}
          busy={busy || !initialized || !queue}
          saveStatus={saveStatus}
          onChange={queueForm}
          onDomainQueryChange={setDomainQuery}
          onRetryDomains={retryDomains}
          onCreateDomain={createDomain}
          onSave={() => { void flushLatest() }}
          onContinue={() => { void continueToTbox() }}
        />
      : step === 'tbox' && (!serverDraft || !etag)
      ? <section className="grid min-h-[320px] place-items-center rounded-enterprise border border-slate-300 bg-white p-8 text-sm text-slate-500">
          Graph Builder를 열기 전에 서버 Draft와 lifecycle을 확인하고 있습니다.
        </section>
      : step === 'tbox'
      ? <GraphBuilder
          client={client}
          draftId={draftId ?? serverDraft!.id}
          etag={etag!}
          busy={busy}
          lifecycleState={serverDraft?.state}
          onDraftUpdate={applyChildDraft}
          onContinue={() => { void continueToAbox() }}
        />
      : draftId
      ? <DataEnricherStep
          client={client}
          draftId={draftId}
          subjectId={subjectId}
          onDraftUpdate={applyChildDraft}
          onStepUp={onStepUp}
          onPasswordReauth={onPasswordReauth}
          onEnroll={onEnroll}
          hardwareWebauthnEnabled={hardwareWebauthnEnabled}
        />
      : null}
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
