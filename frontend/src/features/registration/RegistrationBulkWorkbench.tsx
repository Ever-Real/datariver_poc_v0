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
  UploadContentProfile,
  UploadPreparation,
  UploadRegistrationCandidatePage,
  UploadRecord,
} from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'

const HASH_CHUNK_SIZE = 4 * 1024 * 1024
const TERMINAL_STATES = new Set(['ACCEPTED', 'REJECTED', 'ABORTED', 'EXPIRED'])
const TYPED_DESCRIPTION_PROFILES = new Set<UploadContentProfile>([
  'DATASET_DESCRIPTION_CSV_V1',
  'DATASET_DESCRIPTION_XLSX_V1',
])

function isTypedDescriptionProfile(profile: UploadContentProfile): boolean {
  return TYPED_DESCRIPTION_PROFILES.has(profile)
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
  const [candidatePage, setCandidatePage] = useState<UploadRegistrationCandidatePage>()
  const [candidatesBusy, setCandidatesBusy] = useState(false)
  const [error, setError] = useState<unknown>()
  const [busy, setBusy] = useState(false)
  const generation = useRef(0)
  const controllers = useRef(new Set<AbortController>())
  const loadIntent = useRef(0)
  const preparationIntent = useRef(0)
  const candidateIntent = useRef(0)

  const beginOperation = useCallback(() => {
    const controller = new AbortController()
    controllers.current.add(controller)
    return { controller, expectedGeneration: generation.current }
  }, [])

  const finishOperation = useCallback((controller: AbortController) => {
    controllers.current.delete(controller)
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
    setPreparation(undefined)
    setPreparationLoaded(false)
    setCandidatePage(undefined)
    setCandidatesBusy(false)
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
  }, [beginOperation, client, finishOperation])

  useEffect(() => {
    const activeControllers = controllers.current
    generation.current += 1
    activeControllers.forEach((controller) => controller.abort())
    activeControllers.clear()
    setFile(undefined); setClassification('INTERNAL'); setContentProfile('FORMAT_ONLY_V1')
    setProgress(0)
    setStatus('파일을 선택하세요.'); setRecord(undefined); setRecords([])
    setPreparation(undefined); setPreparationLoaded(false); setPreparationBusy(false)
    setCandidatePage(undefined); setCandidatesBusy(false)
    setError(undefined); setBusy(false); loadIntent.current += 1; preparationIntent.current += 1; candidateIntent.current += 1
    void load()
    return () => {
      generation.current += 1
      activeControllers.forEach((controller) => controller.abort())
      activeControllers.clear()
    }
  }, [client, load])

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

  const loadCandidates = async () => {
    if (!record || !preparation || preparation.state !== 'READY' || candidatesBusy) return
    const expectedIntent = candidateIntent.current + 1
    candidateIntent.current = expectedIntent
    const { controller, expectedGeneration } = beginOperation()
    setCandidatesBusy(true)
    setError(undefined)
    try {
      const value = await client.request<UploadRegistrationCandidatePage>(
        `/uploads/${record.id}/preparations/${preparation.id}/candidates?limit=20`,
        { signal: controller.signal },
      )
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
        setPreparation(created)
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
            accept={contentProfile === 'DATASET_DESCRIPTION_CSV_V1'
              ? '.csv,text/csv'
              : contentProfile === 'DATASET_DESCRIPTION_XLSX_V1'
                ? '.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
              : '.pdf,.csv,.json,.parquet,.yaml,.yml,.xlsx'}
            onChange={(event) => selectFile(event.target.files?.[0])}
          />
          <label>등록 프로파일<select aria-describedby={isTypedDescriptionProfile(contentProfile) ? profileHintId : undefined} disabled={busy} value={contentProfile} onChange={(event) => selectProfile(event.target.value as UploadContentProfile)}><option value="FORMAT_ONLY_V1">형식 검증만</option><option value="DATASET_DESCRIPTION_CSV_V1">Dataset 설명 CSV</option><option value="DATASET_DESCRIPTION_XLSX_V1">Dataset 설명 Excel (.xlsx)</option></select></label>
          {isTypedDescriptionProfile(contentProfile) && (
            <p className="registration-profile-hint" id={profileHintId}>
              기존 ACTIVE Dataset 설명 변경 준비 전용 · 고정 헤더: asset_id, platform,
              database_name, schema_name, table_name, description · 업로드/준비는 변경 요청이나
              DataHub 반영 완료가 아닙니다.
            </p>
          )}
          <label>분류등급<select disabled={busy} value={classification} onChange={(event) => setClassification(event.target.value)}><option>PUBLIC</option><option>INTERNAL</option><option>CONFIDENTIAL</option><option>RESTRICTED</option></select></label>
          <button className="button" disabled={!file || busy}>{busy ? '처리 중…' : '검증 업로드 시작'}</button>
          <div className="progress-track" role="progressbar" aria-label="업로드 진행률" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress * 100)}><span style={{ width: `${Math.round(progress * 100)}%` }} /></div>
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
            onCreate={() => void createPreparation()}
            onRefresh={() => void loadPreparations(record)}
            candidatePage={candidatePage}
            candidatesBusy={candidatesBusy}
            onLoadCandidates={() => void loadCandidates()}
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
  onCreate,
  onRefresh,
  candidatePage,
  candidatesBusy,
  onLoadCandidates,
}: {
  preparation?: UploadPreparation
  loaded: boolean
  busy: boolean
  onCreate: () => void
  onRefresh: () => void
  candidatePage?: UploadRegistrationCandidatePage
  candidatesBusy: boolean
  onLoadCandidates: () => void
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
          {preparation.last_error_code && (
            <p className="notice notice-error" role="alert">
              준비 실패 코드: {preparation.last_error_code}
            </p>
          )}
          {preparation.state === 'READY' && (
            <CandidatePreviewPanel
              page={candidatePage}
              busy={candidatesBusy}
              onLoad={onLoadCandidates}
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
  onLoad,
}: {
  page?: UploadRegistrationCandidatePage
  busy: boolean
  onLoad: () => void
}) {
  return (
    <section className="registration-candidate-preview" aria-label="등록 후보 미리보기" aria-busy={busy}>
      <header>
        <div>
          <span className="eyebrow">Authorized candidate evidence</span>
          <h4>Dataset 설명 후보</h4>
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
            <table>
              <caption>권한이 확인된 Dataset 설명 후보</caption>
              <thead><tr><th scope="col">#</th><th scope="col">대상</th><th scope="col">제안 설명</th><th scope="col">등급</th><th scope="col">Source version</th></tr></thead>
              <tbody>
                {page.items.map((candidate) => <tr key={candidate.id}>
                  <td>{candidate.ordinal}</td>
                  <td title={`${candidate.submitted_identity.platform}.${candidate.submitted_identity.database_name}.${candidate.submitted_identity.schema_name}.${candidate.submitted_identity.table_name}`}><strong>{candidate.submitted_identity.table_name}</strong><small>{candidate.submitted_identity.platform} · {candidate.submitted_identity.database_name}.{candidate.submitted_identity.schema_name}</small></td>
                  <td title={candidate.proposed_description}>{candidate.proposed_description || '(설명 삭제)'}</td>
                  <td><span className="badge">{candidate.current_target.classification}</span></td>
                  <td title={candidate.current_target.source_version}><code>{candidate.current_target.source_version}</code></td>
                </tr>)}
                {!page.items.length && <tr><td colSpan={5}>현재 권한 범위에서 표시할 후보가 없습니다.</td></tr>}
              </tbody>
            </table>
          </div>
          <dl className="registration-candidate-receipt">
            <div><dt>Receipt SHA-256</dt><dd><code>{page.receipt.receipt_hash}</code></dd></div>
            <div><dt>Candidate root</dt><dd><code>{page.receipt.candidate_root_hash}</code></dd></div>
          </dl>
          <p className="notice registration-binding-pending" role="status">
            후보별 변경요청 생성은 receipt·candidate hash·현재 provider snapshot을 함께 고정하는 typed 서버 명령으로만 열립니다. 현재 화면은 해당 증거를 검토하는 읽기 전용 단계입니다.
          </p>
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
      <div
        className="registration-bulk-statusprogress"
        role="progressbar"
        aria-label="후보 준비 진행률"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={determinate ? progress : undefined}
        aria-valuetext={determinate ? undefined : '전체 행 수 확인 전'}
      >
        <span style={{ width: `${progress}%` }} />
      </div>
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
  if (profile === 'DATASET_DESCRIPTION_CSV_V1') return 'Dataset 설명 CSV'
  if (profile === 'DATASET_DESCRIPTION_XLSX_V1') return 'Dataset 설명 Excel (.xlsx)'
  return '형식 검증만'
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
  if (profile === 'DATASET_DESCRIPTION_CSV_V1' && !isTypedDescriptionCsv(file)) {
    throw new Error('Dataset 설명 CSV 프로파일은 CSV 파일만 등록할 수 있습니다.')
  }
  if (profile === 'DATASET_DESCRIPTION_XLSX_V1' && !isTypedDescriptionXlsx(file)) {
    throw new Error('Dataset 설명 Excel 프로파일은 .xlsx 파일만 등록할 수 있습니다.')
  }
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
