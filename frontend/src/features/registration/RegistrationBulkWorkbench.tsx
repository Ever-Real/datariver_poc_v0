import { createSHA256 } from 'hash-wasm'
import {
  CheckCircle2,
  Circle,
  FileUp,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
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
import type { ChangeRequestRecord, UploadRecord } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'

const HASH_CHUNK_SIZE = 4 * 1024 * 1024
const TERMINAL_STATES = new Set(['ACCEPTED', 'REJECTED', 'ABORTED', 'EXPIRED'])
const DEFAULT_ASPECT_DOCUMENT = '{\n  "description": ""\n}'
const ALLOWED_ASPECTS = [
  'datasetProperties',
  'domains',
  'globalTags',
  'glossaryTerms',
  'ownership',
  'schemaMetadata',
] as const

export function RegistrationBulkWorkbench({ client }: { client: ApiClient }) {
  const inputId = useId()
  const [file, setFile] = useState<File>()
  const [classification, setClassification] = useState('INTERNAL')
  const [progress, setProgress] = useState(0)
  const [status, setStatus] = useState('파일을 선택하세요.')
  const [record, setRecord] = useState<UploadRecord>()
  const [records, setRecords] = useState<UploadRecord[]>([])
  const [error, setError] = useState<unknown>()
  const [busy, setBusy] = useState(false)
  const [targetRef, setTargetRef] = useState('')
  const [aspectName, setAspectName] = useState<(typeof ALLOWED_ASPECTS)[number]>('datasetProperties')
  const [beforeHash, setBeforeHash] = useState('')
  const [aspectDocument, setAspectDocument] = useState(DEFAULT_ASPECT_DOCUMENT)
  const [proposal, setProposal] = useState<ChangeRequestRecord>()
  const [proposalBusy, setProposalBusy] = useState(false)
  const generation = useRef(0)
  const controllers = useRef(new Set<AbortController>())
  const proposalInFlight = useRef(false)
  const proposalIntent = useRef<{ fingerprint: string; key: string } | undefined>(undefined)
  const loadIntent = useRef(0)

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
      ) setRecords(value.items)
    } catch (next) {
      if (!controller.signal.aborted && expectedGeneration === generation.current) setError(next)
    } finally {
      finishOperation(controller)
    }
  }, [beginOperation, client, finishOperation])

  useEffect(() => {
    const activeControllers = controllers.current
    generation.current += 1
    activeControllers.forEach((controller) => controller.abort())
    activeControllers.clear()
    setFile(undefined); setClassification('INTERNAL'); setProgress(0)
    setStatus('파일을 선택하세요.'); setRecord(undefined); setRecords([])
    setError(undefined); setBusy(false); setProposal(undefined); setProposalBusy(false)
    proposalInFlight.current = false; proposalIntent.current = undefined; loadIntent.current += 1
    setTargetRef(''); setAspectName('datasetProperties'); setBeforeHash('')
    setAspectDocument(DEFAULT_ASPECT_DOCUMENT)
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
  ): Promise<boolean> => {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      const current = await client.request<UploadRecord>(`/uploads/${uploadId}`, {
        signal: controller.signal,
      })
      if (expectedGeneration !== generation.current) return false
      setRecord(current)
      setRecords((values) => [current, ...values.filter((item) => item.id !== current.id)])
      setStatus(stateLabel(current))
      if (TERMINAL_STATES.has(current.state)) return true
      await abortableDelay(1000, controller.signal)
    }
    if (expectedGeneration === generation.current) {
      setStatus('검증이 계속 진행 중입니다. 최근 등록 목록에서 상태를 새로고침하세요.')
    }
    return false
  }

  const upload = async (event: FormEvent) => {
    event.preventDefault()
    if (!file) return
    const { controller, expectedGeneration } = beginOperation()
    setBusy(true); setError(undefined); setProgress(0); setProposal(undefined)
    try {
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
      if (terminal && expectedGeneration === generation.current) setProgress(1)
    } catch (next) {
      if (!controller.signal.aborted && expectedGeneration === generation.current) {
        setError(next); setStatus('업로드 또는 검증 상태 확인 실패')
      }
    } finally {
      finishOperation(controller)
      if (expectedGeneration === generation.current) setBusy(false)
    }
  }

  const createProposal = async (event: FormEvent) => {
    event.preventDefault()
    if (!record || record.state !== 'ACCEPTED' || proposalBusy || proposalInFlight.current) return
    proposalInFlight.current = true
    const { controller, expectedGeneration } = beginOperation()
    setError(undefined); setProposalBusy(true)
    try {
      const document = JSON.parse(aspectDocument) as Record<string, unknown>
      const fingerprint = JSON.stringify({
        uploadId: record.id,
        targetRef,
        aspectName,
        beforeHash,
        document,
      })
      if (proposalIntent.current?.fingerprint !== fingerprint) {
        proposalIntent.current = {
          fingerprint,
          key: newIdempotencyKey('registration-proposal'),
        }
      }
      const value = await client.request<ChangeRequestRecord>(
        `/uploads/${record.id}/registration-proposals`,
        {
          method: 'POST',
          idempotencyKey: proposalIntent.current.key,
          signal: controller.signal,
          body: JSON.stringify({
            target_ref: targetRef,
            aspect_name: aspectName,
            before_hash: beforeHash,
            after_document: document,
            title: `${record.display_name} 메타데이터 등록`,
            description: '검증된 업로드를 근거로 DataHub 메타데이터 변경을 제안합니다.',
          }),
        },
      )
      if (expectedGeneration === generation.current) setProposal(value)
    } catch (next) {
      if (!controller.signal.aborted && expectedGeneration === generation.current) setError(next)
    } finally {
      finishOperation(controller)
      proposalInFlight.current = false
      if (expectedGeneration === generation.current) setProposalBusy(false)
    }
  }

  const selectFile = (next?: File) => {
    if (busy || proposalBusy) return
    setFile(next); setProgress(0); setRecord(undefined); setProposal(undefined)
    proposalIntent.current = undefined
    setStatus(next ? `${next.name} 업로드 준비됨` : '파일을 선택하세요.')
  }

  const dropFile = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault()
    if (busy || proposalBusy) return
    selectFile(event.dataTransfer.files[0])
  }

  const selectRecord = (next: UploadRecord) => {
    if (busy || proposalBusy) return
    setRecord(next); setProposal(undefined); setTargetRef(''); setBeforeHash('')
    setAspectName('datasetProperties'); setAspectDocument(DEFAULT_ASPECT_DOCUMENT)
    proposalIntent.current = undefined
  }

  return (
    <div className="registration-bulk-workbench">
      <aside className="registration-bulk-sidebar panel">
        <header><div><span className="eyebrow">Quarantine first</span><h2>업로드 큐</h2></div><button type="button" aria-label="목록 새로고침" disabled={busy || proposalBusy} onClick={() => void load()}><RefreshCw size={14} /></button></header>
        <form className="registration-upload-form" onSubmit={(event) => void upload(event)}>
          <label
            className="registration-dropzone"
            htmlFor={inputId}
            aria-disabled={busy || proposalBusy}
            onDragOver={(event) => event.preventDefault()}
            onDrop={dropFile}
          >
            <FileUp size={25} aria-hidden="true" />
            <strong>{file?.name ?? '파일을 놓거나 선택하세요'}</strong>
            <span>CSV · JSON · Parquet · YAML · XLSX</span>
          </label>
          <input
            className="sr-only"
            id={inputId}
            type="file"
            disabled={busy || proposalBusy}
            accept=".csv,.json,.parquet,.yaml,.yml,.xlsx"
            onChange={(event) => selectFile(event.target.files?.[0])}
          />
          <label>분류등급<select disabled={busy || proposalBusy} value={classification} onChange={(event) => setClassification(event.target.value)}><option>PUBLIC</option><option>INTERNAL</option><option>CONFIDENTIAL</option><option>RESTRICTED</option></select></label>
          <button className="button" disabled={!file || busy}>{busy ? '처리 중…' : '검증 업로드 시작'}</button>
          <div className="progress-track" role="progressbar" aria-label="업로드 진행률" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress * 100)}><span style={{ width: `${Math.round(progress * 100)}%` }} /></div>
          <p className="muted" aria-live="polite">{status}</p>
        </form>
        <div className="registration-recent-list">
          <h3>최근 등록 <span>{records.length}</span></h3>
          <div className="compact-list">
            {records.map((item) => <button type="button" disabled={busy || proposalBusy} aria-pressed={record?.id === item.id} className={record?.id === item.id ? 'selected' : ''} key={item.id} onClick={() => selectRecord(item)}><span><strong>{item.display_name}</strong><small>{item.size_bytes.toLocaleString()} bytes</small></span><span className="badge">{item.state}</span></button>)}
            {!records.length && <p className="muted">등록 이력이 없습니다.</p>}
          </div>
        </div>
      </aside>

      <main className="registration-bulk-detail panel">
        <header><div><span className="eyebrow">Validated workflow</span><h2>{record?.display_name ?? '등록 상세'}</h2></div>{record && <span className="badge">{record.state}</span>}</header>
        <ErrorNotice error={error} />
        <WorkflowState record={record} fileSelected={Boolean(file)} proposalCreated={Boolean(proposal)} />
        {!record && <div className="registration-empty-editor">왼쪽에서 파일을 선택하고 명시적으로 업로드를 시작하세요. 브라우저는 전체 파일을 메모리에 적재하지 않습니다.</div>}
        {record && <section className="registration-upload-summary">
          <dl className="summary-list">
            <div><dt>Upload ID</dt><dd><code>{record.id}</code></dd></div>
            <div><dt>Version</dt><dd>{record.version}</dd></div>
            <div><dt>Size</dt><dd>{record.size_bytes.toLocaleString()} bytes</dd></div>
            <div><dt>Content type</dt><dd>{record.content_type}</dd></div>
            <div><dt>Classification</dt><dd>{record.classification}</dd></div>
            <div><dt>Expires</dt><dd>{record.expires_at}</dd></div>
          </dl>
          {record.last_error_code && <p className="notice notice-error">실패 코드: {record.last_error_code}</p>}
          <h3>검증 결과</h3>
          {Object.keys(record.validation_summary).length > 0 ? <dl className="summary-list">{Object.entries(record.validation_summary).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{displaySummaryValue(value)}</dd></div>)}</dl> : <p className="muted">검증 요약이 아직 생성되지 않았습니다.</p>}
        </section>}
        {record?.state === 'ACCEPTED' && <form className="form-stack registration-proposal-form" onSubmit={(event) => void createProposal(event)}>
          <header><ShieldCheck size={18} /><div><h3>고급 DataHub 변경 제안</h3><p>현재 자산의 원본 hash가 필요한 통합·복구용 임시 경로이며 일반 등록 완료로 간주하지 않습니다.</p></div></header>
          <label>대상 URN<input disabled={proposalBusy} value={targetRef} onChange={(event) => setTargetRef(event.target.value)} placeholder="urn:li:dataset:(...)" pattern="urn:li:dataset:.+" required /></label>
          <label>Aspect<select disabled={proposalBusy} value={aspectName} onChange={(event) => setAspectName(event.target.value as (typeof ALLOWED_ASPECTS)[number])}>{ALLOWED_ASPECTS.map((aspect) => <option key={aspect}>{aspect}</option>)}</select></label>
          <label>원본 Aspect SHA-256<input disabled={proposalBusy} value={beforeHash} onChange={(event) => setBeforeHash(event.target.value)} pattern="[0-9a-f]{64}" minLength={64} maxLength={64} required /></label>
          <label>Aspect JSON<textarea disabled={proposalBusy} className="code-editor" value={aspectDocument} onChange={(event) => setAspectDocument(event.target.value)} required /></label>
          <p className="callout">대상은 현재 워크스페이스의 권한 필터된 로컬 자산이어야 하며, 제안은 변경관리 승인과 DataHub 재조회 검증을 거쳐야 합니다.</p>
          <button className="button" disabled={proposalBusy}>{proposalBusy ? '생성 중…' : '변경요청 생성'}</button>
          {proposal && <p>생성됨: <strong>{proposal.number}</strong> · {proposal.state}</p>}
        </form>}
      </main>
    </div>
  )
}

type WorkflowStatus = 'idle' | 'pending' | 'complete' | 'failed'

function WorkflowState({
  record,
  fileSelected,
  proposalCreated,
}: {
  record?: UploadRecord
  fileSelected: boolean
  proposalCreated: boolean
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
    { key: 'PROPOSAL', label: 'Proposal', status: proposalCreated ? 'complete' : state === 'ACCEPTED' ? 'pending' : 'idle' },
  ] satisfies Array<{ key: string; label: string; status: WorkflowStatus }>
  const labels: Record<WorkflowStatus, string> = {
    idle: '대기', pending: '진행 중', complete: '완료', failed: '실패',
  }
  return <ol className="registration-workflow" aria-label="등록 처리 단계">{stages.map((stage) => <li key={stage.key} className={stage.status} aria-current={stage.status === 'pending' ? 'step' : undefined}>{stage.status === 'complete' ? <CheckCircle2 size={17} /> : stage.status === 'failed' ? <XCircle size={17} /> : stage.status === 'pending' ? <LoaderCircle size={17} /> : <Circle size={17} />}<span><b>{stage.label}</b><small>{labels[stage.status]}</small></span></li>)}</ol>
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
    csv: 'text/csv',
    json: 'application/json',
    parquet: 'application/x-parquet',
    yaml: 'application/yaml',
    yml: 'application/yaml',
    xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  }
  const value = extension ? byExtension[extension] : undefined
  if (!value) throw new Error('CSV, JSON, Parquet, YAML 또는 XLSX 파일만 등록할 수 있습니다.')
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
