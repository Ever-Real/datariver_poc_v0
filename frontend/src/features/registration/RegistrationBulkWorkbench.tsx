import { createSHA256 } from 'hash-wasm'
import {
  CheckCircle2,
  Circle,
  FileUp,
  LoaderCircle,
  RefreshCw,
  XCircle,
} from 'lucide-react'
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type DragEvent,
  type FormEvent,
} from 'react'
import { newIdempotencyKey, type ApiClient } from '../../api/client'
import type {
  CatalogMetadataCandidate,
  CatalogMetadataCandidatePage,
  ChangeRequestRecord,
  TypedCatalogMetadataChangeRequest,
  TypedCatalogMetadataPreview,
  TypedBulkCandidatePreview,
  UploadContentProfile,
  UploadPreparation,
  UploadRegistrationCandidate,
  UploadRegistrationCandidatePage,
  UploadRecord,
} from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'

const HASH_CHUNK_SIZE = 4 * 1024 * 1024
const PREPARATION_POLL_MAX_ATTEMPTS = 20
const PREPARATION_POLL_MAX_ELAPSED_MS = 120_000
const TERMINAL_STATES = new Set(['ACCEPTED', 'REJECTED', 'ABORTED', 'EXPIRED'])
const TYPED_DESCRIPTION_PROFILES = new Set<UploadContentProfile>([
  'CATALOG_METADATA_ROWS_CSV_V1',
  'CATALOG_METADATA_ROWS_XLSX_V1',
  'DATASET_DESCRIPTION_CSV_V1',
  'DATASET_DESCRIPTION_XLSX_V1',
])
const CATALOG_METADATA_PROFILES = new Set<UploadContentProfile>([
  'CATALOG_METADATA_ROWS_CSV_V1',
  'CATALOG_METADATA_ROWS_XLSX_V1',
])

type TypedCandidate = UploadRegistrationCandidate | CatalogMetadataCandidate
type TypedCandidatePage = UploadRegistrationCandidatePage | CatalogMetadataCandidatePage
type SafeDatasetDescriptionPreview = Omit<TypedBulkCandidatePreview, 'target_ref'>
type TypedCandidatePreview = SafeDatasetDescriptionPreview | TypedCatalogMetadataPreview
type TypedCandidatePreviewResponse = TypedBulkCandidatePreview | TypedCatalogMetadataPreview
type TypedChangeRequest = ChangeRequestRecord | TypedCatalogMetadataChangeRequest

function isTypedDescriptionProfile(profile: UploadContentProfile): boolean {
  return TYPED_DESCRIPTION_PROFILES.has(profile)
}

function isCatalogMetadataProfile(profile: UploadContentProfile): boolean {
  return CATALOG_METADATA_PROFILES.has(profile)
}

function isCatalogMetadataCandidate(
  candidate: TypedCandidate,
): candidate is CatalogMetadataCandidate {
  return candidate.evidence_version === 'CATALOG_METADATA_CANDIDATE_V3'
}

function isCatalogMetadataPage(
  page: TypedCandidatePage,
): page is CatalogMetadataCandidatePage {
  return page.receipt.content_profile === 'CATALOG_METADATA_ROWS_CSV_V1'
    || page.receipt.content_profile === 'CATALOG_METADATA_ROWS_XLSX_V1'
}

function isCatalogMetadataPreview(
  preview: TypedCandidatePreviewResponse | TypedCandidatePreview,
): preview is TypedCatalogMetadataPreview {
  return 'record_kind' in preview
}

function boundedCatalogMetadataPage(
  value: CatalogMetadataCandidatePage,
): CatalogMetadataCandidatePage {
  return {
    items: value.items.slice(0, 50).map((candidate) => ({
      id: candidate.id,
      ordinal: candidate.ordinal,
      evidence_version: candidate.evidence_version,
      record_kind: candidate.record_kind,
      candidate_kind: candidate.candidate_kind,
      operation_count: candidate.operation_count,
      field_path_sample: candidate.field_path_sample.slice(0, 20),
      controlled_reference_count: candidate.controlled_reference_count,
      row_summary_truncated: candidate.row_summary_truncated,
      submitted_identity: {
        platform: candidate.submitted_identity.platform,
        database_name: candidate.submitted_identity.database_name,
        schema_name: candidate.submitted_identity.schema_name,
        table_name: candidate.submitted_identity.table_name,
        identity_hash: candidate.submitted_identity.identity_hash,
      },
      candidate_hash: candidate.candidate_hash,
      created_at: candidate.created_at,
      current_target: {
        id: candidate.current_target.id,
        asset_type: candidate.current_target.asset_type,
        name: candidate.current_target.name,
        platform: candidate.current_target.platform,
        database_name: candidate.current_target.database_name,
        schema_name: candidate.current_target.schema_name,
        classification: candidate.current_target.classification,
        lifecycle: candidate.current_target.lifecycle,
        source_version: candidate.current_target.source_version,
        observed_at: candidate.current_target.observed_at,
      },
    })),
    page: {
      limit: Math.min(value.page.limit, 50),
      ...(value.page.next_cursor ? { next_cursor: value.page.next_cursor } : {}),
    },
    receipt: {
      id: value.receipt.id,
      preparation_id: value.receipt.preparation_id,
      manifest_version: value.receipt.manifest_version,
      source_sha256: value.receipt.source_sha256,
      content_profile: value.receipt.content_profile,
      parser_version: value.receipt.parser_version,
      scanner_version: value.receipt.scanner_version,
      schema_version: value.receipt.schema_version,
      configuration_hash: value.receipt.configuration_hash,
      item_count: value.receipt.item_count,
      candidate_count: value.receipt.candidate_count,
      candidate_root_hash: value.receipt.candidate_root_hash,
      receipt_hash: value.receipt.receipt_hash,
      observed_at: value.receipt.observed_at,
      created_at: value.receipt.created_at,
    },
    meta: {
      projection_version: value.meta.projection_version,
      policy_version: value.meta.policy_version,
      classification_policy_version: value.meta.classification_policy_version,
      authorization_generation: value.meta.authorization_generation,
    },
  }
}

function boundedCatalogMetadataPreview(
  value: TypedCatalogMetadataPreview,
): TypedCatalogMetadataPreview {
  return {
    candidate_id: value.candidate_id,
    target_asset_id: value.target_asset_id,
    platform: value.platform,
    database_name: value.database_name,
    schema_name: value.schema_name,
    table_name: value.table_name,
    record_kind: value.record_kind,
    candidate_kind: value.candidate_kind,
    operation_count: value.operation_count,
    description_change_count: value.description_change_count,
    description_change_sample: value.description_change_sample.slice(0, 20).map((change) => ({
      field_path: change.field_path,
      current_description: change.current_description,
      proposed_description: change.proposed_description,
    })),
    description_changes_truncated: value.description_changes_truncated,
    current_reference_count: value.current_reference_count,
    proposed_reference_count: value.proposed_reference_count,
    before_hash: value.before_hash,
    after_hash: value.after_hash,
    source_version: value.source_version,
    observed_at: value.observed_at,
    preview_etag: value.preview_etag,
  }
}

function boundedDatasetDescriptionPreview(
  value: TypedBulkCandidatePreview,
): SafeDatasetDescriptionPreview {
  return {
    candidate_id: value.candidate_id,
    target_asset_id: value.target_asset_id,
    platform: value.platform,
    database_name: value.database_name,
    schema_name: value.schema_name,
    table_name: value.table_name,
    current_description: value.current_description,
    proposed_description: value.proposed_description,
    before_hash: value.before_hash,
    after_hash: value.after_hash,
    source_version: value.source_version,
    observed_at: value.observed_at,
    preview_etag: value.preview_etag,
  }
}

function boundedCatalogMetadataChangeRequest(
  value: TypedCatalogMetadataChangeRequest,
): TypedCatalogMetadataChangeRequest {
  return {
    id: value.id,
    number: value.number,
    request_type: value.request_type,
    state: value.state,
  }
}

export function RegistrationBulkWorkbench({ client }: { client: ApiClient }) {
  const inputId = useId()
  const profileHintId = useId()
  const [file, setFile] = useState<File>()
  const [classification, setClassification] = useState('INTERNAL')
  const [contentProfile, setContentProfile] = useState<UploadContentProfile>('FORMAT_ONLY_V1')
  const [progress, setProgress] = useState(0)
  const [status, setStatus] = useState('파일을 선택하세요.')
  const [record, setRecord] = useState<UploadRecord>()
  const [records, setRecords] = useState<UploadRecord[]>([])
  const [preparation, setPreparation] = useState<UploadPreparation>()
  const [preparationLoaded, setPreparationLoaded] = useState(false)
  const [preparationBusy, setPreparationBusy] = useState(false)
  const [templateBusy, setTemplateBusy] = useState(false)
  const [preparationPollingStopped, setPreparationPollingStopped] = useState(false)
  const [candidatePage, setCandidatePage] = useState<TypedCandidatePage>()
  const [candidateCursorStack, setCandidateCursorStack] = useState<string[]>([])
  const [candidatesBusy, setCandidatesBusy] = useState(false)
  const [selectedCandidate, setSelectedCandidate] = useState<TypedCandidate>()
  const [candidatePreview, setCandidatePreview] = useState<TypedCandidatePreview>()
  const [candidatePreviewBusy, setCandidatePreviewBusy] = useState(false)
  const [candidateCreateBusy, setCandidateCreateBusy] = useState(false)
  const [candidateTitle, setCandidateTitle] = useState('')
  const [candidateReason, setCandidateReason] = useState('')
  const [createdChangeRequest, setCreatedChangeRequest] = useState<TypedChangeRequest>()
  const [error, setError] = useState<unknown>()
  const [busy, setBusy] = useState(false)
  const generation = useRef(0)
  const controllers = useRef(new Set<AbortController>())
  const loadIntent = useRef(0)
  const preparationIntent = useRef(0)
  const candidateIntent = useRef(0)
  const candidatePreviewIntent = useRef(0)
  const candidatePreviewController = useRef<AbortController | undefined>(undefined)
  const candidateCreateIdempotency = useRef<
    { fingerprint: string; key: string } | undefined
  >(undefined)
  const preparationPollDelay = useRef(1_000)
  const preparationPollAttempts = useRef(0)
  const preparationPollStartedAt = useRef(0)

  const beginOperation = useCallback(() => {
    const controller = new AbortController()
    controllers.current.add(controller)
    return { controller, expectedGeneration: generation.current }
  }, [])

  const finishOperation = useCallback((controller: AbortController) => {
    controllers.current.delete(controller)
  }, [])

  const clearCandidateCommand = useCallback(() => {
    candidatePreviewController.current?.abort()
    candidatePreviewController.current = undefined
    candidatePreviewIntent.current += 1
    setSelectedCandidate(undefined)
    setCandidatePreview(undefined)
    setCandidatePreviewBusy(false)
    setCandidateCreateBusy(false)
    setCandidateTitle('')
    setCandidateReason('')
    setCreatedChangeRequest(undefined)
    candidateCreateIdempotency.current = undefined
  }, [])

  const load = useCallback(async () => {
    const { controller, expectedGeneration } = beginOperation()
    const expectedLoadIntent = loadIntent.current + 1
    loadIntent.current = expectedLoadIntent
    try {
      const value = await client.request<{ items: UploadRecord[] }>('/uploads?limit=50', {
        signal: controller.signal,
      })
      if (
        expectedGeneration === generation.current
        && expectedLoadIntent === loadIntent.current
      ) {
        setRecords(value.items)
        setRecord((current) => (
          current
            ? value.items.find((item) => item.id === current.id) ?? current
            : current
        ))
      }
    } catch (next) {
      if (!controller.signal.aborted && expectedGeneration === generation.current) setError(next)
    } finally {
      finishOperation(controller)
    }
  }, [beginOperation, client, finishOperation])

  const loadPreparations = useCallback(async (upload: UploadRecord) => {
    const expectedIntent = preparationIntent.current + 1
    preparationIntent.current = expectedIntent
    preparationPollDelay.current = 1_000
    preparationPollAttempts.current = 0
    preparationPollStartedAt.current = Date.now()
    setPreparationPollingStopped(false)
    setPreparation(undefined)
    setPreparationLoaded(false)
    setCandidatePage(undefined)
    setCandidateCursorStack([])
    setCandidatesBusy(false)
    clearCandidateCommand()
    candidateIntent.current += 1
    if (upload.state !== 'ACCEPTED' || !isTypedDescriptionProfile(upload.content_profile)) {
      setPreparationBusy(false)
      return
    }
    const { controller, expectedGeneration } = beginOperation()
    setPreparationBusy(true)
    try {
      const value = await client.request<{ items: UploadPreparation[] }>(
        `/uploads/${upload.id}/preparations?limit=20`,
        { signal: controller.signal },
      )
      if (
        expectedGeneration === generation.current
        && expectedIntent === preparationIntent.current
      ) {
        setPreparation(value.items[0])
        setPreparationLoaded(true)
      }
    } catch (next) {
      if (
        !controller.signal.aborted
        && expectedGeneration === generation.current
        && expectedIntent === preparationIntent.current
      ) setError(next)
    } finally {
      finishOperation(controller)
      if (
        expectedGeneration === generation.current
        && expectedIntent === preparationIntent.current
      ) setPreparationBusy(false)
    }
  }, [beginOperation, clearCandidateCommand, client, finishOperation])

  useEffect(() => {
    const activeControllers = controllers.current
    generation.current += 1
    activeControllers.forEach((controller) => controller.abort())
    activeControllers.clear()
    setFile(undefined); setClassification('INTERNAL'); setContentProfile('FORMAT_ONLY_V1')
    setProgress(0)
    setStatus('파일을 선택하세요.'); setRecord(undefined); setRecords([])
    setPreparation(undefined); setPreparationLoaded(false); setPreparationBusy(false)
    setTemplateBusy(false)
    setPreparationPollingStopped(false)
    preparationPollDelay.current = 1_000
    preparationPollAttempts.current = 0
    preparationPollStartedAt.current = 0
    setCandidatePage(undefined); setCandidatesBusy(false)
    setCandidateCursorStack([])
    clearCandidateCommand()
    setError(undefined); setBusy(false); loadIntent.current += 1; preparationIntent.current += 1; candidateIntent.current += 1
    void load()
    return () => {
      generation.current += 1
      activeControllers.forEach((controller) => controller.abort())
      activeControllers.clear()
    }
  }, [clearCandidateCommand, client, load])

  useEffect(() => {
    if (
      !record
      || !preparation
      || !['QUEUED', 'PREPARING'].includes(preparation.state)
    ) {
      preparationPollDelay.current = 1_000
      preparationPollAttempts.current = 0
      preparationPollStartedAt.current = 0
      setPreparationPollingStopped(false)
      return
    }
    if (
      preparationPollAttempts.current >= PREPARATION_POLL_MAX_ATTEMPTS
      || (
        preparationPollStartedAt.current > 0
        && Date.now() - preparationPollStartedAt.current >= PREPARATION_POLL_MAX_ELAPSED_MS
      )
      || document.visibilityState === 'hidden'
    ) {
      setPreparationPollingStopped(true)
      return
    }
    if (preparationPollStartedAt.current === 0) {
      preparationPollStartedAt.current = Date.now()
    }
    const { controller, expectedGeneration } = beginOperation()
    const uploadId = record.id
    const preparationId = preparation.id
    const delay = preparationPollDelay.current
    preparationPollAttempts.current += 1
    void abortableDelay(delay, controller.signal).then(async () => {
      const value = await client.request<{ items: UploadPreparation[] }>(
        `/uploads/${uploadId}/preparations?limit=20`,
        { signal: controller.signal },
      )
      if (controller.signal.aborted || expectedGeneration !== generation.current) return
      const current = value.items.find((item) => item.id === preparationId)
      if (!current || current.upload_id !== uploadId) return
      preparationPollDelay.current = Math.min(delay * 2, 10_000)
      setPreparation(current)
      setPreparationLoaded(true)
    }).catch((next: unknown) => {
      if (!controller.signal.aborted && expectedGeneration === generation.current) setError(next)
    }).finally(() => finishOperation(controller))
    return () => {
      controller.abort()
      finishOperation(controller)
    }
  }, [
    beginOperation,
    client,
    finishOperation,
    preparation,
    record,
  ])

  const poll = async (
    uploadId: string,
    controller: AbortController,
    expectedGeneration: number,
  ): Promise<UploadRecord | undefined> => {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      const current = await client.request<UploadRecord>(`/uploads/${uploadId}`, {
        signal: controller.signal,
      })
      if (expectedGeneration !== generation.current) return undefined
      setRecord(current)
      setRecords((values) => [current, ...values.filter((item) => item.id !== current.id)])
      setStatus(stateLabel(current))
      if (TERMINAL_STATES.has(current.state)) return current
      await abortableDelay(1000, controller.signal)
    }
    if (expectedGeneration === generation.current) {
      setStatus('검증이 계속 진행 중입니다. 최근 등록 목록에서 상태를 새로고침하세요.')
    }
    return undefined
  }

  const upload = async (event: FormEvent) => {
    event.preventDefault()
    if (!file) return
    const { controller, expectedGeneration } = beginOperation()
    setBusy(true); setError(undefined); setProgress(0)
    try {
      validateProfileFile(file, contentProfile)
      setStatus('SHA-256 계산 중')
      const sha256 = await digestFile(file, controller.signal, (value) => setProgress(value * 0.15))
      const contentType = supportedContentType(file)
      const initiated = await client.request<UploadRecord>('/uploads', {
        method: 'POST',
        idempotencyKey: newIdempotencyKey('upload-init'),
        signal: controller.signal,
        body: JSON.stringify({
          display_name: file.name,
          size_bytes: file.size,
          content_type: contentType,
          sha256,
          classification,
          content_profile: contentProfile,
        }),
      })
      if (expectedGeneration !== generation.current) return
      setRecord(initiated)
      const partSize = initiated.recommended_part_size_bytes
      const completed: Array<{ part_number: number; etag: string }> = []
      const partCount = Math.ceil(file.size / partSize)
      for (let index = 0; index < partCount; index += 1) {
        const partNumber = index + 1
        setStatus(`${partNumber}/${partCount} 파트 업로드 중`)
        const signed = await client.request<{ url: string }>(`/uploads/${initiated.id}/parts`, {
          method: 'POST',
          signal: controller.signal,
          body: JSON.stringify({ part_number: partNumber }),
        })
        const response = await fetch(signed.url, {
          method: 'PUT',
          signal: controller.signal,
          body: file.slice(index * partSize, Math.min(file.size, (index + 1) * partSize)),
        })
        if (!response.ok) throw new Error(`오브젝트 스토리지 업로드 실패 (${response.status})`)
        const etag = response.headers.get('ETag')?.replaceAll('"', '')
        if (!etag) throw new Error('오브젝트 스토리지 응답에서 ETag를 읽을 수 없습니다. CORS 설정을 확인하세요.')
        completed.push({ part_number: partNumber, etag })
        setProgress(0.15 + (partNumber / partCount) * 0.8)
      }
      const queued = await client.request<UploadRecord>(`/uploads/${initiated.id}/complete`, {
        method: 'POST',
        idempotencyKey: newIdempotencyKey('upload-complete'),
        ifMatch: `"${initiated.version}"`,
        signal: controller.signal,
        body: JSON.stringify({ parts: completed }),
      })
      if (expectedGeneration !== generation.current) return
      setRecord(queued); setProgress(0.97); setStatus('무결성·형식 검증 대기 중')
      const terminal = await poll(queued.id, controller, expectedGeneration)
      if (terminal && expectedGeneration === generation.current) {
        setProgress(1)
        await loadPreparations(terminal)
      }
    } catch (next) {
      if (!controller.signal.aborted && expectedGeneration === generation.current) {
        setError(next); setStatus('업로드 또는 검증 상태 확인 실패')
      }
    } finally {
      finishOperation(controller)
      if (expectedGeneration === generation.current) setBusy(false)
    }
  }

  const selectFile = (next?: File) => {
    if (busy) return
    preparationIntent.current += 1
    setFile(next); setProgress(0); setRecord(undefined)
    setPreparation(undefined); setPreparationLoaded(false); setPreparationBusy(false)
    setPreparationPollingStopped(false)
    preparationPollDelay.current = 1_000
    preparationPollAttempts.current = 0
    preparationPollStartedAt.current = 0
    clearCandidateCommand()
    setStatus(next ? `${next.name} 업로드 준비됨` : '파일을 선택하세요.')
  }

  const selectProfile = (next: UploadContentProfile) => {
    if (busy) return
    setContentProfile(next)
    setError(undefined)
    if (file) {
      try {
        validateProfileFile(file, next)
      } catch (nextError) {
        setFile(undefined)
        setProgress(0)
        setStatus(nextError instanceof Error ? nextError.message : '프로파일과 파일이 맞지 않습니다.')
      }
    }
  }

  const dropFile = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault()
    if (busy) return
    selectFile(event.dataTransfer.files[0])
  }

  const selectRecord = (next: UploadRecord) => {
    if (busy) return
    setRecord(next)
    setError(undefined)
    void loadPreparations(next)
  }

  const loadCandidates = async (cursor?: string) => {
    if (!record || !preparation || preparation.state !== 'READY' || candidatesBusy) return
    const catalogMetadata = isCatalogMetadataProfile(record.content_profile)
    clearCandidateCommand()
    const expectedIntent = candidateIntent.current + 1
    candidateIntent.current = expectedIntent
    const { controller, expectedGeneration } = beginOperation()
    setCandidatesBusy(true)
    setError(undefined)
    try {
      const query = new URLSearchParams({ limit: '20' })
      if (cursor) query.set('cursor', cursor)
      const received = await client.request<TypedCandidatePage>(
        `/uploads/${record.id}/preparations/${preparation.id}/${
          catalogMetadata ? 'metadata-candidates' : 'candidates'
        }?${query.toString()}`,
        { signal: controller.signal },
      )
      if (catalogMetadata !== isCatalogMetadataPage(received)) {
        throw new Error('후보 프로파일과 서버 응답이 일치하지 않습니다.')
      }
      const value = catalogMetadata
        ? boundedCatalogMetadataPage(received as CatalogMetadataCandidatePage)
        : received
      if (
        candidatePage
        && (
          value.receipt.id !== candidatePage.receipt.id
          || value.receipt.receipt_hash !== candidatePage.receipt.receipt_hash
          || value.receipt.candidate_root_hash !== candidatePage.receipt.candidate_root_hash
        )
      ) throw new Error('후보 receipt가 페이지 이동 중 변경되었습니다. 준비 상태를 다시 확인하세요.')
      if (
        expectedGeneration === generation.current
        && expectedIntent === candidateIntent.current
        && value.receipt.preparation_id === preparation.id
      ) setCandidatePage(value)
    } catch (next) {
      if (
        !controller.signal.aborted
        && expectedGeneration === generation.current
        && expectedIntent === candidateIntent.current
      ) setError(next)
    } finally {
      finishOperation(controller)
      if (
        expectedGeneration === generation.current
        && expectedIntent === candidateIntent.current
      ) setCandidatesBusy(false)
    }
  }

  const nextCandidatePage = () => {
    const cursor = candidatePage?.page.next_cursor
    if (!cursor || candidatesBusy) return
    const stack = [...candidateCursorStack, cursor].slice(-50)
    setCandidateCursorStack(stack)
    void loadCandidates(stack.at(-1))
  }

  const previousCandidatePage = () => {
    if (!candidateCursorStack.length || candidatesBusy) return
    const stack = candidateCursorStack.slice(0, -1)
    setCandidateCursorStack(stack)
    void loadCandidates(stack.at(-1))
  }

  const resetCandidatePages = () => {
    if (candidatesBusy) return
    setCandidateCursorStack([])
    void loadCandidates()
  }

  const openCandidatePreview = async (candidate: TypedCandidate) => {
    if (!record || !preparation || candidatePreviewBusy || candidateCreateBusy) return
    const catalogMetadata = isCatalogMetadataCandidate(candidate)
    clearCandidateCommand()
    const intent = candidatePreviewIntent.current + 1
    candidatePreviewIntent.current = intent
    const { controller, expectedGeneration } = beginOperation()
    candidatePreviewController.current = controller
    setSelectedCandidate(candidate)
    setCandidateTitle(
      `${candidate.submitted_identity.table_name} ${
        catalogMetadata ? catalogMetadataRecordLabel(candidate.record_kind) : 'Dataset 설명'
      } 변경`,
    )
    setCandidateReason('검증된 BULK 업로드 후보를 변경관리 검토 대상으로 등록합니다.')
    setCandidatePreviewBusy(true)
    setError(undefined)
    try {
      const received = await client.request<TypedCandidatePreviewResponse>(
        `/uploads/${record.id}/preparations/${preparation.id}/${
          catalogMetadata ? 'metadata-candidates' : 'candidates'
        }/${candidate.id}/preview`,
        { signal: controller.signal },
      )
      if (catalogMetadata !== isCatalogMetadataPreview(received)) {
        throw new Error('후보와 미리보기 프로파일이 일치하지 않습니다.')
      }
      const value = catalogMetadata
        ? boundedCatalogMetadataPreview(received as TypedCatalogMetadataPreview)
        : boundedDatasetDescriptionPreview(received as TypedBulkCandidatePreview)
      if (
        controller.signal.aborted
        || expectedGeneration !== generation.current
        || intent !== candidatePreviewIntent.current
        || value.candidate_id !== candidate.id
        || value.target_asset_id !== candidate.current_target.id
        || value.source_version.trim().length === 0
      ) return
      setCandidatePreview(value)
    } catch (next) {
      if (
        !controller.signal.aborted
        && expectedGeneration === generation.current
        && intent === candidatePreviewIntent.current
      ) setError(next)
    } finally {
      finishOperation(controller)
      if (candidatePreviewController.current === controller) {
        candidatePreviewController.current = undefined
      }
      if (
        expectedGeneration === generation.current
        && intent === candidatePreviewIntent.current
      ) setCandidatePreviewBusy(false)
    }
  }

  const createCandidateChangeRequest = async () => {
    if (
      !record
      || !preparation
      || !selectedCandidate
      || !candidatePreview
      || candidateCreateBusy
      || !candidateTitle.trim()
      || !candidateReason.trim()
    ) return
    const catalogMetadata = isCatalogMetadataCandidate(selectedCandidate)
    const normalizedTitle = candidateTitle.trim()
    const normalizedReason = candidateReason.trim()
    const commandFingerprint = JSON.stringify({
      candidate_id: selectedCandidate.id,
      preview_etag: candidatePreview.preview_etag,
      reason: normalizedReason,
      title: normalizedTitle,
    })
    if (candidateCreateIdempotency.current?.fingerprint !== commandFingerprint) {
      candidateCreateIdempotency.current = {
        fingerprint: commandFingerprint,
        key: newIdempotencyKey(
          catalogMetadata ? 'typed-catalog-metadata-change' : 'typed-bulk-change',
        ),
      }
    }
    const idempotencyKey = candidateCreateIdempotency.current.key
    const intent = candidatePreviewIntent.current + 1
    candidatePreviewIntent.current = intent
    const { controller, expectedGeneration } = beginOperation()
    candidatePreviewController.current = controller
    setCandidateCreateBusy(true)
    setError(undefined)
    try {
      const received = await client.request<TypedChangeRequest>(
        `/uploads/${record.id}/preparations/${preparation.id}/${
          catalogMetadata ? 'metadata-candidates' : 'candidates'
        }/${selectedCandidate.id}/change-request`,
        {
          method: 'POST',
          idempotencyKey,
          ifMatch: candidatePreview.preview_etag,
          signal: controller.signal,
          body: JSON.stringify({
            title: normalizedTitle,
            reason: normalizedReason,
          }),
        },
      )
      if (
        catalogMetadata
        && (
          !('request_type' in received)
          || received.request_type !== 'BULK_CATALOG_METADATA'
        )
      ) throw new Error('서버가 예상하지 않은 변경요청 형식을 반환했습니다.')
      const value = catalogMetadata
        ? boundedCatalogMetadataChangeRequest(received as TypedCatalogMetadataChangeRequest)
        : received
      if (
        controller.signal.aborted
        || expectedGeneration !== generation.current
        || intent !== candidatePreviewIntent.current
        || (
          !catalogMetadata
          && (
            !('items' in value)
            || value.items.length !== 1
            || value.items[0]?.target_asset_id !== candidatePreview.target_asset_id
          )
        )
      ) return
      setCreatedChangeRequest(value)
    } catch (next) {
      if (
        !controller.signal.aborted
        && expectedGeneration === generation.current
        && intent === candidatePreviewIntent.current
      ) setError(next)
    } finally {
      finishOperation(controller)
      if (candidatePreviewController.current === controller) {
        candidatePreviewController.current = undefined
      }
      if (
        expectedGeneration === generation.current
        && intent === candidatePreviewIntent.current
      ) setCandidateCreateBusy(false)
    }
  }

  const createPreparation = async () => {
    if (
      !record
      || record.state !== 'ACCEPTED'
      || !isTypedDescriptionProfile(record.content_profile)
      || !preparationLoaded
    ) return
    const expectedIntent = preparationIntent.current + 1
    preparationIntent.current = expectedIntent
    const { controller, expectedGeneration } = beginOperation()
    setPreparationBusy(true)
    setError(undefined)
    try {
      const created = await client.request<UploadPreparation>(
        `/uploads/${record.id}/preparations`,
        {
          method: 'POST',
          idempotencyKey: newIdempotencyKey('upload-preparation'),
          ifMatch: `"${record.version}"`,
          signal: controller.signal,
        },
      )
      if (
        expectedGeneration === generation.current
        && expectedIntent === preparationIntent.current
      ) {
        preparationPollDelay.current = 1_000
        preparationPollAttempts.current = 0
        preparationPollStartedAt.current = Date.now()
        setPreparationPollingStopped(false)
        setPreparation(created)
        setPreparationLoaded(true)
        setCandidatePage(undefined)
        setCandidateCursorStack([])
        clearCandidateCommand()
      }
    } catch (next) {
      if (
        !controller.signal.aborted
        && expectedGeneration === generation.current
        && expectedIntent === preparationIntent.current
      ) setError(next)
    } finally {
      finishOperation(controller)
      if (
        expectedGeneration === generation.current
        && expectedIntent === preparationIntent.current
      ) setPreparationBusy(false)
    }
  }

  const downloadCatalogMetadataTemplate = async () => {
    if (!isCatalogMetadataProfile(contentProfile) || templateBusy) return
    const profile = contentProfile
    const { controller, expectedGeneration } = beginOperation()
    setTemplateBusy(true)
    setError(undefined)
    try {
      const downloaded = await client.download(
        `/uploads/profiles/${profile}/template`,
        { signal: controller.signal },
      )
      if (
        controller.signal.aborted
        || expectedGeneration !== generation.current
        || profile !== contentProfile
      ) return
      const url = URL.createObjectURL(downloaded.blob)
      try {
        const anchor = document.createElement('a')
        anchor.href = url
        anchor.download = downloaded.filename
        document.body.append(anchor)
        try {
          anchor.click()
        } finally {
          anchor.remove()
        }
      } finally {
        URL.revokeObjectURL(url)
      }
    } catch (next) {
      if (!controller.signal.aborted && expectedGeneration === generation.current) setError(next)
    } finally {
      finishOperation(controller)
      if (expectedGeneration === generation.current) setTemplateBusy(false)
    }
  }

  return (
    <div className="registration-bulk-workbench">
      <aside className="registration-bulk-sidebar panel">
        <header><div><span className="eyebrow">Quarantine first</span><h2>업로드 큐</h2></div><button type="button" aria-label="목록 새로고침" disabled={busy} onClick={() => void load()}><RefreshCw size={14} /></button></header>
        <form className="registration-upload-form" onSubmit={(event) => void upload(event)}>
          <label
            className="registration-dropzone"
            htmlFor={inputId}
            aria-disabled={busy}
            onDragOver={(event) => event.preventDefault()}
            onDrop={dropFile}
          >
            <FileUp size={25} aria-hidden="true" />
            <strong>{file?.name ?? '파일을 놓거나 선택하세요'}</strong>
            <span>PDF · CSV · JSON · Parquet · YAML · XLSX</span>
          </label>
          <input
            className="sr-only"
            id={inputId}
            type="file"
            disabled={busy}
            accept={profileAccept(contentProfile)}
            onChange={(event) => selectFile(event.target.files?.[0])}
          />
          <label>등록 프로파일<select aria-describedby={isTypedDescriptionProfile(contentProfile) ? profileHintId : undefined} disabled={busy} value={contentProfile} onChange={(event) => selectProfile(event.target.value as UploadContentProfile)}><option value="FORMAT_ONLY_V1">형식 검증만</option><option value="CATALOG_METADATA_ROWS_CSV_V1">카탈로그 메타데이터 CSV</option><option value="CATALOG_METADATA_ROWS_XLSX_V1">카탈로그 메타데이터 Excel (.xlsx)</option><option value="DATASET_DESCRIPTION_CSV_V1">Dataset 설명 CSV (호환)</option><option value="DATASET_DESCRIPTION_XLSX_V1">Dataset 설명 Excel (.xlsx, 호환)</option></select></label>
          {isCatalogMetadataProfile(contentProfile) && (
            <>
              <p className="registration-profile-hint" id={profileHintId}>
                테이블·컬럼 설명, 도메인, 용어, 태그 변경 전용입니다. 서버 버전과 일치하는
                10열 템플릿을 사용하세요. 서버가 현재 자산과 통제 어휘를 다시 확인하며
                업로드/준비만으로는 변경요청 또는 DataHub 반영이 생성되지 않습니다.
                {' '}
                <button
                  className="button button-secondary"
                  disabled={templateBusy}
                  onClick={() => void downloadCatalogMetadataTemplate()}
                  type="button"
                >
                  {templateBusy ? '템플릿 받는 중…' : '서버 템플릿 받기'}
                </button>
              </p>
            </>
          )}
          {!isCatalogMetadataProfile(contentProfile) && isTypedDescriptionProfile(contentProfile) && (
            <p className="registration-profile-hint" id={profileHintId}>
              기존 ACTIVE Dataset 설명 변경 준비 전용 · 고정 헤더: asset_id, platform,
              database_name, schema_name, table_name, description · 업로드/준비는 변경 요청이나
              DataHub 반영 완료가 아닙니다.
            </p>
          )}
          <label>분류등급<select disabled={busy} value={classification} onChange={(event) => setClassification(event.target.value)}><option>PUBLIC</option><option>INTERNAL</option><option>CONFIDENTIAL</option><option>RESTRICTED</option></select></label>
          <button className="button" disabled={!file || busy}>{busy ? '처리 중…' : '검증 업로드 시작'}</button>
          <progress className="progress-track" aria-label="업로드 진행률" max={100} value={Math.round(progress * 100)} />
          <p className="muted" aria-live="polite">{status}</p>
        </form>
        <div className="registration-recent-list">
          <h3>최근 등록 <span>{records.length}</span></h3>
          <div className="compact-list">
            {records.map((item) => <button type="button" disabled={busy} aria-pressed={record?.id === item.id} className={record?.id === item.id ? 'selected' : ''} key={item.id} onClick={() => selectRecord(item)}><span><strong>{item.display_name}</strong><small>{item.size_bytes.toLocaleString()} bytes</small></span><span className="badge">{item.state}</span></button>)}
            {!records.length && <p className="muted">등록 이력이 없습니다.</p>}
          </div>
        </div>
      </aside>

      <main className="registration-bulk-detail panel">
        <header><div><span className="eyebrow">Validated workflow</span><h2>{record?.display_name ?? '등록 상세'}</h2></div>{record && <span className="badge">{record.state}</span>}</header>
        <ErrorNotice error={error} />
        <WorkflowState
          record={record}
          fileSelected={Boolean(file)}
          preparation={preparation}
          preparationLoaded={preparationLoaded}
          preparationBusy={preparationBusy}
        />
        {!record && <div className="registration-empty-editor">왼쪽에서 파일을 선택하고 명시적으로 업로드를 시작하세요. 브라우저는 전체 파일을 메모리에 적재하지 않습니다.</div>}
        {record && <section className="registration-upload-summary">
          <dl className="summary-list">
            <div><dt>Upload ID</dt><dd><code>{record.id}</code></dd></div>
            <div><dt>Version</dt><dd>{record.version}</dd></div>
            <div><dt>Size</dt><dd>{record.size_bytes.toLocaleString()} bytes</dd></div>
            <div><dt>Content type</dt><dd>{record.content_type}</dd></div>
            <div><dt>Profile</dt><dd>{profileLabel(record.content_profile)}</dd></div>
            <div><dt>Classification</dt><dd>{record.classification}</dd></div>
            <div><dt>Expires</dt><dd>{record.expires_at}</dd></div>
          </dl>
          {record.last_error_code && <p className="notice notice-error">실패 코드: {record.last_error_code}</p>}
          <h3>검증 결과</h3>
          {Object.keys(record.validation_summary).length > 0 ? <dl className="summary-list">{Object.entries(record.validation_summary).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{displaySummaryValue(value)}</dd></div>)}</dl> : <p className="muted">검증 요약이 아직 생성되지 않았습니다.</p>}
        </section>}
        {record?.state === 'ACCEPTED' && record.content_profile === 'FORMAT_ONLY_V1' && (
          <section className="notice registration-binding-pending" role="status">
            <strong>이 업로드는 형식 검증 전용입니다.</strong>
            <span>
              accepted content로 변경 요청을 만들지 않습니다. Dataset 설명을 변경하려면 새 업로드에서
              Dataset 설명 CSV 또는 Excel 프로파일을 명시적으로 선택하세요.
            </span>
          </section>
        )}
        {record?.state === 'ACCEPTED' && isTypedDescriptionProfile(record.content_profile) && (
          <PreparationPanel
            preparation={preparation}
            loaded={preparationLoaded}
            busy={preparationBusy}
            pollingStopped={preparationPollingStopped}
            onCreate={() => void createPreparation()}
            onRefresh={() => void loadPreparations(record)}
            candidatePage={candidatePage}
            candidatesBusy={candidatesBusy}
            candidateHasPrevious={candidateCursorStack.length > 0}
            onLoadCandidates={resetCandidatePages}
            onNextCandidates={nextCandidatePage}
            onPreviousCandidates={previousCandidatePage}
            selectedCandidate={selectedCandidate}
            candidatePreview={candidatePreview}
            candidatePreviewBusy={candidatePreviewBusy}
            candidateCreateBusy={candidateCreateBusy}
            candidateTitle={candidateTitle}
            candidateReason={candidateReason}
            createdChangeRequest={createdChangeRequest}
            onSelectCandidate={(candidate) => { void openCandidatePreview(candidate) }}
            onCandidateTitleChange={(value) => {
              candidateCreateIdempotency.current = undefined
              setCandidateTitle(value)
            }}
            onCandidateReasonChange={(value) => {
              candidateCreateIdempotency.current = undefined
              setCandidateReason(value)
            }}
            onCreateCandidateChangeRequest={() => { void createCandidateChangeRequest() }}
          />
        )}
        {record?.state === 'ACCEPTED' && isTypedDescriptionProfile(record.content_profile) && (
          <PreparationStatusBar
            preparation={preparation}
            loaded={preparationLoaded}
            busy={preparationBusy}
          />
        )}
      </main>
    </div>
  )
}

type WorkflowStatus = 'idle' | 'available' | 'pending' | 'complete' | 'failed'

function PreparationPanel({
  preparation,
  loaded,
  busy,
  pollingStopped,
  onCreate,
  onRefresh,
  candidatePage,
  candidatesBusy,
  candidateHasPrevious,
  onLoadCandidates,
  onNextCandidates,
  onPreviousCandidates,
  selectedCandidate,
  candidatePreview,
  candidatePreviewBusy,
  candidateCreateBusy,
  candidateTitle,
  candidateReason,
  createdChangeRequest,
  onSelectCandidate,
  onCandidateTitleChange,
  onCandidateReasonChange,
  onCreateCandidateChangeRequest,
}: {
  preparation?: UploadPreparation
  loaded: boolean
  busy: boolean
  pollingStopped: boolean
  onCreate: () => void
  onRefresh: () => void
  candidatePage?: TypedCandidatePage
  candidatesBusy: boolean
  candidateHasPrevious: boolean
  onLoadCandidates: () => void
  onNextCandidates: () => void
  onPreviousCandidates: () => void
  selectedCandidate?: TypedCandidate
  candidatePreview?: TypedCandidatePreview
  candidatePreviewBusy: boolean
  candidateCreateBusy: boolean
  candidateTitle: string
  candidateReason: string
  createdChangeRequest?: TypedChangeRequest
  onSelectCandidate: (candidate: TypedCandidate) => void
  onCandidateTitleChange: (value: string) => void
  onCandidateReasonChange: (value: string) => void
  onCreateCandidateChangeRequest: () => void
}) {
  return (
    <section
      className="registration-preparation-panel"
      aria-labelledby="bulk-preparation-title"
      aria-busy={busy}
    >
      <header>
        <div>
          <span className="eyebrow">Bulk Preview</span>
          <h3 id="bulk-preparation-title">Dataset 설명 미리보기 준비</h3>
        </div>
        <span className="badge">{preparation?.state ?? 'NOT STARTED'}</span>
      </header>
      {!preparation && (
        <div className="registration-preparation-empty">
          <p>
            검증·승격된 바이트와 현재 manifest 버전을 서버가 다시 고정한 뒤에만 후보 준비를
            시작합니다. 브라우저는 CSV 행을 해석하거나 변경 내용을 제출하지 않습니다.
          </p>
          <button
            className="button"
            type="button"
            disabled={busy}
            onClick={loaded ? onCreate : onRefresh}
          >
            {busy ? '상태 확인 중…' : loaded ? '미리보기 준비' : '준비 상태 확인'}
          </button>
        </div>
      )}
      {preparation && (
        <>
          <dl className="summary-list registration-preparation-summary">
            <div><dt>Preparation</dt><dd><code>{preparation.id}</code></dd></div>
            <div><dt>Source version</dt><dd>{preparation.source_manifest_version}</dd></div>
            <div><dt>Attempts</dt><dd>{preparation.attempts}</dd></div>
            <div><dt>Rows</dt><dd>{preparation.rows_processed.toLocaleString()} / {preparation.total_rows?.toLocaleString() ?? '미확정'}</dd></div>
            <div><dt>Updated</dt><dd>{preparation.updated_at}</dd></div>
            <div><dt>Version</dt><dd>{preparation.version}</dd></div>
          </dl>
          <div className="registration-preparation-actions">
            <button className="button button-secondary" type="button" disabled={busy} onClick={onRefresh}>
              <RefreshCw size={13} aria-hidden="true" />
              {busy ? '확인 중…' : '상태 새로고침'}
            </button>
          </div>
          {pollingStopped && ['QUEUED', 'PREPARING'].includes(preparation.state) && (
            <p className="notice" role="status">
              자동 상태 확인을 중단했습니다. 최신 상태는 위 버튼으로 명시적으로 확인하세요.
            </p>
          )}
          {preparation.last_error_code && (
            <p className="notice notice-error" role="alert">
              준비 실패 코드: {preparation.last_error_code}
            </p>
          )}
          {preparation.state === 'READY' && (
            <CandidatePreviewPanel
              page={candidatePage}
              busy={candidatesBusy}
              hasPrevious={candidateHasPrevious}
              onLoad={onLoadCandidates}
              onNext={onNextCandidates}
              onPrevious={onPreviousCandidates}
              selectedCandidate={selectedCandidate}
              preview={candidatePreview}
              previewBusy={candidatePreviewBusy}
              createBusy={candidateCreateBusy}
              title={candidateTitle}
              reason={candidateReason}
              createdChangeRequest={createdChangeRequest}
              onSelect={onSelectCandidate}
              onTitleChange={onCandidateTitleChange}
              onReasonChange={onCandidateReasonChange}
              onCreate={onCreateCandidateChangeRequest}
            />
          )}
          {['FAILED', 'CANCELLED', 'STALE'].includes(preparation.state) && (
            <p className="notice registration-binding-pending" role="status">
              이 결과를 브라우저에서 재사용하거나 수정하지 않습니다. STALE 상태는 새 immutable
              upload가 필요하며, worker 재처리는 별도 통제 명령으로만 제공됩니다.
            </p>
          )}
        </>
      )}
    </section>
  )
}

function CandidatePreviewPanel({
  page,
  busy,
  hasPrevious,
  onLoad,
  onNext,
  onPrevious,
  selectedCandidate,
  preview,
  previewBusy,
  createBusy,
  title,
  reason,
  createdChangeRequest,
  onSelect,
  onTitleChange,
  onReasonChange,
  onCreate,
}: {
  page?: TypedCandidatePage
  busy: boolean
  hasPrevious: boolean
  onLoad: () => void
  onNext: () => void
  onPrevious: () => void
  selectedCandidate?: TypedCandidate
  preview?: TypedCandidatePreview
  previewBusy: boolean
  createBusy: boolean
  title: string
  reason: string
  createdChangeRequest?: TypedChangeRequest
  onSelect: (candidate: TypedCandidate) => void
  onTitleChange: (value: string) => void
  onReasonChange: (value: string) => void
  onCreate: () => void
}) {
  const catalogMetadata = page ? isCatalogMetadataPage(page) : false
  return (
    <section className="registration-candidate-preview" aria-label="등록 후보 미리보기" aria-busy={busy}>
      <header>
        <div>
          <span className="eyebrow">Authorized candidate evidence</span>
          <h4>{catalogMetadata ? '카탈로그 메타데이터 후보' : 'Dataset 설명 후보'}</h4>
        </div>
        <button className="button button-secondary" type="button" disabled={busy} onClick={onLoad}>
          {busy ? '후보 확인 중…' : page ? '후보 새로고침' : '후보 조회'}
        </button>
      </header>
      {!page ? (
        <p className="notice registration-binding-pending" role="status">
          서버가 현재 권한·분류·대상 identity를 다시 검사한 후보만 표시합니다. 이 목록은 읽기 전용이며,
          후보를 브라우저에서 수정하거나 원시 변경 JSON으로 제출할 수 없습니다.
        </p>
      ) : (
        <>
          <div className="registration-candidate-table-frame">
            {isCatalogMetadataPage(page) ? (
              <table>
                <caption>권한이 확인된 카탈로그 메타데이터 후보</caption>
                <thead><tr><th scope="col">#</th><th scope="col">대상</th><th scope="col">변경 유형</th><th scope="col">범위</th><th scope="col">등급</th><th scope="col">Source version</th><th scope="col">검토</th></tr></thead>
                <tbody>
                  {page.items.map((candidate) => <tr key={candidate.id}>
                    <td>{candidate.ordinal}</td>
                    <td title={`${candidate.submitted_identity.platform}.${candidate.submitted_identity.database_name}.${candidate.submitted_identity.schema_name}.${candidate.submitted_identity.table_name}`}><strong>{candidate.submitted_identity.table_name}</strong><small>{candidate.submitted_identity.platform} · {candidate.submitted_identity.database_name}.{candidate.submitted_identity.schema_name}</small></td>
                    <td><strong>{catalogMetadataRecordLabel(candidate.record_kind)}</strong><small>{candidate.operation_count.toLocaleString()}건</small></td>
                    <td>{candidate.field_path_sample.length ? candidate.field_path_sample.join(', ') : `통제 참조 ${candidate.controlled_reference_count.toLocaleString()}건`}{candidate.row_summary_truncated ? ' 외' : ''}</td>
                    <td><span className="badge">{candidate.current_target.classification}</span></td>
                    <td title={candidate.current_target.source_version}><code>{candidate.current_target.source_version}</code></td>
                    <td>
                      <button
                        className="button button-secondary"
                        type="button"
                        disabled={busy || previewBusy || createBusy}
                        aria-pressed={selectedCandidate?.id === candidate.id}
                        onClick={() => onSelect(candidate)}
                      >
                        검토 및 변경요청
                      </button>
                    </td>
                  </tr>)}
                  {!page.items.length && <tr><td colSpan={7}>현재 권한 범위에서 표시할 후보가 없습니다.</td></tr>}
                </tbody>
              </table>
            ) : (
              <table>
                <caption>권한이 확인된 Dataset 설명 후보</caption>
                <thead><tr><th scope="col">#</th><th scope="col">대상</th><th scope="col">제안 설명</th><th scope="col">등급</th><th scope="col">Source version</th><th scope="col">검토</th></tr></thead>
                <tbody>
                  {page.items.map((candidate) => <tr key={candidate.id}>
                    <td>{candidate.ordinal}</td>
                    <td title={`${candidate.submitted_identity.platform}.${candidate.submitted_identity.database_name}.${candidate.submitted_identity.schema_name}.${candidate.submitted_identity.table_name}`}><strong>{candidate.submitted_identity.table_name}</strong><small>{candidate.submitted_identity.platform} · {candidate.submitted_identity.database_name}.{candidate.submitted_identity.schema_name}</small></td>
                    <td title={candidate.proposed_description}>{candidate.proposed_description || '(설명 삭제)'}</td>
                    <td><span className="badge">{candidate.current_target.classification}</span></td>
                    <td title={candidate.current_target.source_version}><code>{candidate.current_target.source_version}</code></td>
                    <td>
                      <button
                        className="button button-secondary"
                        type="button"
                        disabled={busy || previewBusy || createBusy}
                        aria-pressed={selectedCandidate?.id === candidate.id}
                        onClick={() => onSelect(candidate)}
                      >
                        검토 및 변경요청
                      </button>
                    </td>
                  </tr>)}
                  {!page.items.length && <tr><td colSpan={6}>현재 권한 범위에서 표시할 후보가 없습니다.</td></tr>}
                </tbody>
              </table>
            )}
          </div>
          <dl className="registration-candidate-receipt">
            <div><dt>Receipt SHA-256</dt><dd><code>{page.receipt.receipt_hash}</code></dd></div>
            <div><dt>Candidate root</dt><dd><code>{page.receipt.candidate_root_hash}</code></dd></div>
          </dl>
          <div className="registration-preparation-actions" aria-label="후보 페이지 이동">
            <button className="button button-secondary" type="button" disabled={busy || !hasPrevious} onClick={onPrevious}>이전 후보</button>
            <button className="button button-secondary" type="button" disabled={busy} onClick={onLoad}>처음부터</button>
            <button className="button button-secondary" type="button" disabled={busy || !page.page.next_cursor} onClick={onNext}>다음 후보</button>
          </div>
          {selectedCandidate && (
            <section className="registration-candidate-command" aria-label="선택 후보 변경요청">
              <header>
                <div>
                  <span className="eyebrow">Fresh server preview</span>
                  <h5>{selectedCandidate.submitted_identity.table_name}</h5>
                </div>
                {previewBusy && <span className="badge">미리보기 확인 중</span>}
              </header>
              {preview && (
                <>
                  {isCatalogMetadataPreview(preview) ? (
                    <>
                      <dl className="summary-list">
                        <div><dt>변경 유형</dt><dd>{catalogMetadataRecordLabel(preview.record_kind)}</dd></div>
                        <div><dt>작업 수</dt><dd>{preview.operation_count.toLocaleString()}건</dd></div>
                        <div><dt>설명 변경</dt><dd>{preview.description_change_count.toLocaleString()}건</dd></div>
                        <div><dt>현재 통제 참조</dt><dd>{preview.current_reference_count.toLocaleString()}건</dd></div>
                        <div><dt>제안 통제 참조</dt><dd>{preview.proposed_reference_count.toLocaleString()}건</dd></div>
                        <div><dt>Provider source</dt><dd><code>{preview.source_version}</code></dd></div>
                        <div><dt>제안 문서 해시</dt><dd><code>{preview.after_hash}</code></dd></div>
                      </dl>
                      {preview.description_change_sample.length > 0 && (
                        <div className="registration-candidate-table-frame">
                          <table>
                            <caption>
                              설명 변경 표본 {preview.description_change_sample.length.toLocaleString()}건
                              {preview.description_changes_truncated ? ' (일부)' : ''}
                            </caption>
                            <thead><tr><th scope="col">Field</th><th scope="col">현재 설명</th><th scope="col">제안 설명</th></tr></thead>
                            <tbody>
                              {preview.description_change_sample.map((change, index) => (
                                <tr key={`${change.field_path ?? 'table'}-${index}`}>
                                  <td>{change.field_path ?? '(table)'}</td>
                                  <td>{change.current_description ?? '(없음)'}</td>
                                  <td>{change.proposed_description ?? '(삭제)'}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </>
                  ) : (
                    <dl className="summary-list">
                      <div><dt>현재 설명</dt><dd>{preview.current_description || '(없음)'}</dd></div>
                      <div><dt>제안 설명</dt><dd>{preview.proposed_description || '(설명 삭제)'}</dd></div>
                      <div><dt>Provider source</dt><dd><code>{preview.source_version}</code></dd></div>
                      <div><dt>제안 문서 해시</dt><dd><code>{preview.after_hash}</code></dd></div>
                    </dl>
                  )}
                  {!createdChangeRequest ? (
                    <div className="registration-candidate-command-form">
                      <label>
                        변경요청 제목
                        <input
                          value={title}
                          maxLength={500}
                          disabled={createBusy}
                          onChange={(event) => onTitleChange(event.target.value)}
                        />
                      </label>
                      <label>
                        등록 사유
                        <textarea
                          value={reason}
                          maxLength={10_000}
                          rows={3}
                          disabled={createBusy}
                          onChange={(event) => onReasonChange(event.target.value)}
                        />
                      </label>
                      <button
                        className="button"
                        type="button"
                        disabled={createBusy || !title.trim() || !reason.trim()}
                        onClick={onCreate}
                      >
                        {createBusy ? '변경요청 생성 중…' : '검증된 후보로 변경요청 생성'}
                      </button>
                    </div>
                  ) : (
                    <p className="notice notice-success" role="status">
                      변경요청 <strong>{createdChangeRequest.number}</strong>이 {createdChangeRequest.state}
                      상태로 생성되었습니다. 이후 검토·승인·DataHub read-back은 변경관리에서 진행됩니다.
                      이 후보를 수정하지 말고 정정이 필요하면 새 파일을 업로드하세요.
                    </p>
                  )}
                </>
              )}
            </section>
          )}
          {!selectedCandidate && (
            <p className="notice registration-binding-pending" role="status">
              한 후보를 선택하면 서버가 receipt·candidate hash·현재 provider snapshot을 다시 고정합니다.
              브라우저는 URN, Aspect 문서, 분류 또는 스토리지 좌표를 제출하지 않습니다.
            </p>
          )}
        </>
      )}
    </section>
  )
}

function PreparationStatusBar({
  preparation,
  loaded,
  busy,
}: {
  preparation?: UploadPreparation
  loaded: boolean
  busy: boolean
}) {
  const progress = preparationProgress(preparation)
  const failed = Boolean(preparation && ['FAILED', 'CANCELLED', 'STALE'].includes(preparation.state))
  const complete = preparation?.state === 'READY'
  const pending = busy || preparation?.state === 'QUEUED' || preparation?.state === 'PREPARING'
  const determinate = preparationHasDeterminateProgress(preparation)
  const label = preparationStatusLabel(preparation, loaded, busy)
  return (
    <section className="registration-bulk-statusbar" role="status" aria-live="polite" aria-atomic="true" aria-label="Bulk preparation 상태">
      <span className={failed ? 'failed' : complete ? 'complete' : pending ? 'pending' : 'idle'} aria-hidden="true">
        {failed
          ? <XCircle size={22} />
          : complete
            ? <CheckCircle2 size={22} />
            : pending
              ? <LoaderCircle size={22} />
              : <Circle size={22} />}
      </span>
      <div className="registration-bulk-statuscopy">
        <strong>{preparation?.state ?? (busy ? 'LOADING' : loaded ? 'READY TO PREPARE' : 'STATUS REQUIRED')}</strong>
        <small>{label}</small>
      </div>
      <progress
        className="registration-bulk-statusprogress"
        aria-label="후보 준비 진행률"
        max={100}
        value={determinate ? progress : undefined}
        aria-valuetext={determinate ? undefined : '전체 행 수 확인 전'}
      />
      <b>{determinate ? `${progress}%` : '—'}</b>
    </section>
  )
}

function WorkflowState({
  record,
  fileSelected,
  preparation,
  preparationLoaded,
  preparationBusy,
}: {
  record?: UploadRecord
  fileSelected: boolean
  preparation?: UploadPreparation
  preparationLoaded: boolean
  preparationBusy: boolean
}) {
  const state = record?.state
  const uploadComplete = Boolean(state && !['INITIATED', 'UPLOADING'].includes(state))
  const quarantineComplete = Boolean(state && [
    'QUARANTINED', 'VALIDATION_QUEUED', 'VALIDATING', 'ACCEPTED', 'REJECTED',
  ].includes(state))
  const terminalUploadFailure = Boolean(state && ['ABORTED', 'EXPIRED'].includes(state))
  const stages = [
    { key: 'UPLOAD', label: 'Upload', status: terminalUploadFailure ? 'failed' : uploadComplete ? 'complete' : fileSelected || Boolean(record) ? 'pending' : 'idle' },
    { key: 'QUARANTINE', label: 'Quarantine', status: terminalUploadFailure ? 'failed' : quarantineComplete ? 'complete' : state && ['COMPLETION_QUEUED', 'COMPLETING'].includes(state) ? 'pending' : 'idle' },
    { key: 'VALIDATION', label: 'Validation', status: state === 'REJECTED' ? 'failed' : state === 'ACCEPTED' ? 'complete' : state && ['QUARANTINED', 'VALIDATION_QUEUED', 'VALIDATING'].includes(state) ? 'pending' : 'idle' },
    { key: 'PROPOSAL', label: 'Preparation', status: preparationWorkflowStatus(record, preparation, preparationLoaded, preparationBusy) },
  ] satisfies Array<{ key: string; label: string; status: WorkflowStatus }>
  const labels: Record<WorkflowStatus, string> = {
    idle: '대기', available: '준비 가능', pending: '진행 중', complete: '완료', failed: '실패',
  }
  return <ol className="registration-workflow" aria-label="등록 처리 단계">{stages.map((stage) => <li key={stage.key} className={stage.status} aria-current={stage.status === 'pending' || stage.status === 'available' ? 'step' : undefined}>{stage.status === 'complete' ? <CheckCircle2 size={17} /> : stage.status === 'failed' ? <XCircle size={17} /> : stage.status === 'pending' ? <LoaderCircle size={17} /> : <Circle size={17} />}<span><b>{stage.label}</b><small>{labels[stage.status]}</small></span></li>)}</ol>
}

function preparationWorkflowStatus(
  record?: UploadRecord,
  preparation?: UploadPreparation,
  loaded = false,
  busy = false,
): WorkflowStatus {
  if (
    !record
    || record.state !== 'ACCEPTED'
    || !isTypedDescriptionProfile(record.content_profile)
  ) return 'idle'
  if (!loaded) return busy ? 'pending' : 'idle'
  if (!preparation) return 'available'
  if (preparation.state === 'READY') return 'complete'
  if (['FAILED', 'CANCELLED', 'STALE'].includes(preparation.state)) return 'failed'
  return 'pending'
}

function preparationProgress(preparation?: UploadPreparation): number {
  if (!preparation) return 0
  if (preparation.state === 'READY') return 100
  if (!preparation.total_rows || preparation.total_rows <= 0) return 0
  return Math.min(99, Math.round((preparation.rows_processed / preparation.total_rows) * 100))
}

function preparationHasDeterminateProgress(preparation?: UploadPreparation): boolean {
  return preparation?.state === 'READY'
    || Boolean(preparation?.total_rows && preparation.total_rows > 0)
}

function preparationStatusLabel(
  preparation: UploadPreparation | undefined,
  loaded: boolean,
  busy: boolean,
): string {
  if (busy) return '서버에서 최신 상태를 확인하고 있습니다.'
  if (!loaded) return '서버 preparation 상태를 확인해야 작업을 시작할 수 있습니다.'
  if (!preparation) return '검증된 source evidence에서 미리보기 준비를 시작할 수 있습니다.'
  const labels: Record<UploadPreparation['state'], string> = {
    QUEUED: '준비 작업이 대기열에 등록되었습니다.',
    PREPARING: `후보 ${preparation.rows_processed.toLocaleString()}행을 처리했습니다.`,
    READY: `후보 ${preparation.rows_processed.toLocaleString()}행의 증거 준비가 완료되었습니다.`,
    FAILED: `준비 작업이 실패했습니다: ${preparation.last_error_code ?? '원인 미상'}`,
    CANCELLED: '준비 작업이 취소되었습니다.',
    STALE: 'source 또는 실행 lease가 변경되어 이 준비 작업은 사용할 수 없습니다.',
  }
  return labels[preparation.state]
}

function profileLabel(profile: UploadContentProfile): string {
  if (profile === 'CATALOG_METADATA_ROWS_CSV_V1') return '카탈로그 메타데이터 CSV'
  if (profile === 'CATALOG_METADATA_ROWS_XLSX_V1') return '카탈로그 메타데이터 Excel (.xlsx)'
  if (profile === 'DATASET_DESCRIPTION_CSV_V1') return 'Dataset 설명 CSV'
  if (profile === 'DATASET_DESCRIPTION_XLSX_V1') return 'Dataset 설명 Excel (.xlsx)'
  return '형식 검증만'
}

function catalogMetadataRecordLabel(
  recordKind: CatalogMetadataCandidate['record_kind'],
): string {
  const labels: Record<CatalogMetadataCandidate['record_kind'], string> = {
    TABLE_DESCRIPTION: '테이블 설명',
    COLUMN_DESCRIPTION: '컬럼 설명',
    DATASET_DOMAIN: '도메인 지정',
    DATASET_TERM: '용어 추가',
    DATASET_TAG: '태그 추가',
  }
  return labels[recordKind]
}

function isTypedDescriptionCsv(file: Pick<File, 'name' | 'type'>): boolean {
  return file.name.toLowerCase().endsWith('.csv') && supportedContentType(file) === 'text/csv'
}

function isTypedDescriptionXlsx(file: Pick<File, 'name' | 'type'>): boolean {
  return file.name.toLowerCase().endsWith('.xlsx')
    && supportedContentType(file)
      === 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
}

export function validateProfileFile(
  file: Pick<File, 'name' | 'type'>,
  profile: UploadContentProfile,
): void {
  if (profile === 'CATALOG_METADATA_ROWS_CSV_V1' && !isTypedDescriptionCsv(file)) {
    throw new Error('카탈로그 메타데이터 CSV 프로파일은 CSV 파일만 등록할 수 있습니다.')
  }
  if (profile === 'CATALOG_METADATA_ROWS_XLSX_V1' && !isTypedDescriptionXlsx(file)) {
    throw new Error('카탈로그 메타데이터 Excel 프로파일은 .xlsx 파일만 등록할 수 있습니다.')
  }
  if (profile === 'DATASET_DESCRIPTION_CSV_V1' && !isTypedDescriptionCsv(file)) {
    throw new Error('Dataset 설명 CSV 프로파일은 CSV 파일만 등록할 수 있습니다.')
  }
  if (profile === 'DATASET_DESCRIPTION_XLSX_V1' && !isTypedDescriptionXlsx(file)) {
    throw new Error('Dataset 설명 Excel 프로파일은 .xlsx 파일만 등록할 수 있습니다.')
  }
}

export function profileAccept(profile: UploadContentProfile): string {
  if (
    profile === 'CATALOG_METADATA_ROWS_CSV_V1'
    || profile === 'DATASET_DESCRIPTION_CSV_V1'
  ) return '.csv,text/csv'
  if (
    profile === 'CATALOG_METADATA_ROWS_XLSX_V1'
    || profile === 'DATASET_DESCRIPTION_XLSX_V1'
  ) return '.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
  return '.pdf,.csv,.json,.parquet,.yaml,.yml,.xlsx'
}

function displaySummaryValue(value: unknown): string {
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }
  if (value === null || value === undefined) return '—'
  try {
    return JSON.stringify(value)
  } catch {
    return '표시할 수 없는 값'
  }
}

function stateLabel(record: UploadRecord): string {
  const labels: Record<string, string> = {
    COMPLETION_QUEUED: '오브젝트 완료 대기 중',
    COMPLETING: '오브젝트 완료 처리 중',
    QUARANTINED: '격리 완료, 검증 대기 중',
    VALIDATING: '무결성·형식 검증 중',
    ACCEPTED: '검증 통과 및 승인 버킷 승격 완료',
    REJECTED: `검증 거부 (${record.last_error_code ?? '원인 미상'})`,
  }
  return labels[record.state] ?? record.state
}

async function digestFile(
  file: File,
  signal: AbortSignal,
  onProgress: (value: number) => void,
): Promise<string> {
  const hash = await createSHA256()
  hash.init()
  for (let offset = 0; offset < file.size; offset += HASH_CHUNK_SIZE) {
    signal.throwIfAborted()
    const chunk = new Uint8Array(await file.slice(offset, offset + HASH_CHUNK_SIZE).arrayBuffer())
    signal.throwIfAborted()
    hash.update(chunk)
    onProgress(Math.min(1, (offset + chunk.byteLength) / file.size))
  }
  signal.throwIfAborted()
  return hash.digest('hex')
}

export function supportedContentType(file: Pick<File, 'name' | 'type'>): string {
  const extension = file.name.toLowerCase().split('.').pop()
  const byExtension: Record<string, string> = {
    pdf: 'application/pdf',
    csv: 'text/csv',
    json: 'application/json',
    parquet: 'application/x-parquet',
    yaml: 'application/yaml',
    yml: 'application/yaml',
    xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  }
  const value = extension ? byExtension[extension] : undefined
  if (!value) throw new Error('PDF, CSV, JSON, Parquet, YAML 또는 XLSX 파일만 등록할 수 있습니다.')
  return value
}

function abortableDelay(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(resolve, milliseconds)
    signal.addEventListener('abort', () => {
      window.clearTimeout(timeout)
      reject(new DOMException('The operation was aborted.', 'AbortError'))
    }, { once: true })
  })
}
