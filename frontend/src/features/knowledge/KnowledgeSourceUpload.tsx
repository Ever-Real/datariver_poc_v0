import { createSHA256 } from 'hash-wasm'
import { CheckCircle2, FileUp, LoaderCircle, Network, RefreshCw, Sparkles } from 'lucide-react'
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
  KnowledgeGraph,
  KnowledgeProjectionReceipt,
  KnowledgeRelease,
  KnowledgeSourceAnalyzeResult,
  UploadRecord,
} from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'

const HASH_CHUNK_SIZE = 4 * 1024 * 1024
const MAX_PDF_SIZE_BYTES = 50 * 1024 * 1024
const TERMINAL_UPLOAD_STATES = new Set(['ACCEPTED', 'REJECTED', 'ABORTED', 'EXPIRED'])

interface KnowledgeSourceUploadProps {
  client: ApiClient
  graph?: KnowledgeGraph
  onAnalysisCreated?: () => void | Promise<void>
}

export function KnowledgeSourceUpload({
  client,
  graph,
  onAnalysisCreated,
}: KnowledgeSourceUploadProps) {
  const inputId = useId()
  const [file, setFile] = useState<File>()
  const [title, setTitle] = useState('')
  const [record, setRecord] = useState<UploadRecord>()
  const [analysis, setAnalysis] = useState<KnowledgeSourceAnalyzeResult>()
  const [releases, setReleases] = useState<KnowledgeRelease[]>([])
  const [selectedReleaseId, setSelectedReleaseId] = useState('')
  const [projection, setProjection] = useState<KnowledgeProjectionReceipt>()
  const [progress, setProgress] = useState(0)
  const [status, setStatus] = useState('PDF 파일을 선택하세요.')
  const [uploadBusy, setUploadBusy] = useState(false)
  const [analysisBusy, setAnalysisBusy] = useState(false)
  const [projectionBusy, setProjectionBusy] = useState(false)
  const [releaseBusy, setReleaseBusy] = useState(false)
  const [error, setError] = useState<unknown>()
  const generation = useRef(0)
  const controllers = useRef(new Set<AbortController>())

  const beginOperation = useCallback(() => {
    const controller = new AbortController()
    controllers.current.add(controller)
    return { controller, expectedGeneration: generation.current }
  }, [])

  const finishOperation = useCallback((controller: AbortController) => {
    controllers.current.delete(controller)
  }, [])

  const loadReleases = useCallback(async () => {
    if (!graph) {
      setReleases([])
      setSelectedReleaseId('')
      return
    }
    const { controller, expectedGeneration } = beginOperation()
    setReleaseBusy(true)
    try {
      const result = await client.request<KnowledgeRelease[]>(
        `/knowledge/graphs/${graph.id}/releases`,
        { signal: controller.signal },
      )
      if (expectedGeneration !== generation.current) return
      setReleases(result)
      setSelectedReleaseId((current) => {
        if (current && result.some((release) => release.id === current)) return current
        if (graph.active_release_id && result.some((release) => release.id === graph.active_release_id)) {
          return graph.active_release_id
        }
        return result.at(-1)?.id ?? ''
      })
    } catch (next) {
      if (!controller.signal.aborted && expectedGeneration === generation.current) setError(next)
    } finally {
      finishOperation(controller)
      if (expectedGeneration === generation.current) setReleaseBusy(false)
    }
  }, [beginOperation, client, finishOperation, graph])

  useEffect(() => {
    const activeControllers = controllers.current
    generation.current += 1
    activeControllers.forEach((controller) => controller.abort())
    activeControllers.clear()
    setFile(undefined)
    setTitle('')
    setRecord(undefined)
    setAnalysis(undefined)
    setProjection(undefined)
    setProgress(0)
    setStatus(graph ? 'PDF 파일을 선택하세요.' : '대상 지식 에셋을 선택하세요.')
    setError(undefined)
    setUploadBusy(false)
    setAnalysisBusy(false)
    setProjectionBusy(false)
    void loadReleases()
    return () => {
      generation.current += 1
      activeControllers.forEach((controller) => controller.abort())
      activeControllers.clear()
    }
  }, [client, graph, loadReleases])

  const pollUpload = async (
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
      setStatus(uploadStateLabel(current))
      if (TERMINAL_UPLOAD_STATES.has(current.state)) return current
      await abortableDelay(1000, controller.signal)
    }
    if (expectedGeneration === generation.current) {
      setStatus('검증이 계속 진행 중입니다. 잠시 후 다시 시도하세요.')
    }
    return undefined
  }

  const upload = async (event: FormEvent) => {
    event.preventDefault()
    if (!file || !graph) return
    const { controller, expectedGeneration } = beginOperation()
    setUploadBusy(true)
    setError(undefined)
    setAnalysis(undefined)
    setProjection(undefined)
    setProgress(0)
    try {
      validateKnowledgePdf(file)
      setStatus('SHA-256 계산 중')
      const sha256 = await digestFile(file, controller.signal, (value) => {
        if (expectedGeneration === generation.current) setProgress(value * 0.15)
      })
      const initiated = await client.request<UploadRecord>('/uploads', {
        method: 'POST',
        idempotencyKey: newIdempotencyKey('knowledge-source-upload'),
        signal: controller.signal,
        body: JSON.stringify({
          display_name: file.name,
          size_bytes: file.size,
          content_type: 'application/pdf',
          sha256,
          classification: graph.classification,
          content_profile: 'FORMAT_ONLY_V1',
        }),
      })
      if (expectedGeneration !== generation.current) return
      setRecord(initiated)
      const partSize = initiated.recommended_part_size_bytes
      const partCount = Math.ceil(file.size / partSize)
      const parts: Array<{ part_number: number; etag: string }> = []
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
        if (!etag) {
          throw new Error('오브젝트 스토리지 응답에서 ETag를 읽을 수 없습니다. CORS 설정을 확인하세요.')
        }
        parts.push({ part_number: partNumber, etag })
        setProgress(0.15 + (partNumber / partCount) * 0.8)
      }
      const queued = await client.request<UploadRecord>(`/uploads/${initiated.id}/complete`, {
        method: 'POST',
        idempotencyKey: newIdempotencyKey('knowledge-source-complete'),
        ifMatch: `"${initiated.version}"`,
        signal: controller.signal,
        body: JSON.stringify({ parts }),
      })
      if (expectedGeneration !== generation.current) return
      setRecord(queued)
      setProgress(0.97)
      setStatus('무결성·PDF 형식 검증 대기 중')
      const terminal = await pollUpload(queued.id, controller, expectedGeneration)
      if (terminal && expectedGeneration === generation.current) setProgress(1)
    } catch (next) {
      if (!controller.signal.aborted && expectedGeneration === generation.current) {
        setError(next)
        setStatus('PDF 업로드 또는 검증 실패')
      }
    } finally {
      finishOperation(controller)
      if (expectedGeneration === generation.current) setUploadBusy(false)
    }
  }

  const analyze = async () => {
    if (!graph || record?.state !== 'ACCEPTED' || !title.trim()) return
    const { controller, expectedGeneration } = beginOperation()
    setAnalysisBusy(true)
    setError(undefined)
    setAnalysis(undefined)
    setProjection(undefined)
    try {
      const result = await client.request<KnowledgeSourceAnalyzeResult>(
        `/knowledge/graphs/${graph.id}/sources/${record.id}/analyze`,
        {
          method: 'POST',
          signal: controller.signal,
          body: JSON.stringify({ title: title.trim() }),
        },
      )
      if (expectedGeneration !== generation.current) return
      setAnalysis(result)
      setStatus('LLM 추출 제안이 DRAFT changeset으로 생성되었습니다.')
      await onAnalysisCreated?.()
    } catch (next) {
      if (!controller.signal.aborted && expectedGeneration === generation.current) setError(next)
    } finally {
      finishOperation(controller)
      if (expectedGeneration === generation.current) setAnalysisBusy(false)
    }
  }

  const project = async () => {
    if (!graph || !selectedReleaseId) return
    const { controller, expectedGeneration } = beginOperation()
    setProjectionBusy(true)
    setError(undefined)
    setProjection(undefined)
    try {
      const result = await client.request<KnowledgeProjectionReceipt>(
        `/knowledge/graphs/${graph.id}/releases/${selectedReleaseId}/project`,
        { method: 'POST', signal: controller.signal },
      )
      if (expectedGeneration === generation.current) setProjection(result)
    } catch (next) {
      if (!controller.signal.aborted && expectedGeneration === generation.current) setError(next)
    } finally {
      finishOperation(controller)
      if (expectedGeneration === generation.current) setProjectionBusy(false)
    }
  }

  const selectFile = (next?: File) => {
    if (uploadBusy || analysisBusy) return
    setError(undefined)
    setRecord(undefined)
    setAnalysis(undefined)
    setProjection(undefined)
    setProgress(0)
    if (!next) {
      setFile(undefined)
      setStatus('PDF 파일을 선택하세요.')
      return
    }
    try {
      validateKnowledgePdf(next)
      setFile(next)
      setTitle((current) => current.trim() ? current : `${next.name} 지식 추출 제안`)
      setStatus(`${next.name} 업로드 준비됨`)
    } catch (nextError) {
      setFile(undefined)
      setStatus('유효한 PDF 파일이 필요합니다.')
      setError(nextError)
    }
  }

  const dropFile = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault()
    selectFile(event.dataTransfer.files[0])
  }

  return <div className="grid gap-4">
    <section className="grid gap-4 rounded-enterprise border border-slate-300 bg-white p-4 shadow-sm lg:grid-cols-[minmax(0,1fr)_minmax(280px,0.65fr)]">
      <form className="grid gap-3" onSubmit={(event) => void upload(event)}>
        <header>
          <span className="text-[10px] font-black tracking-[.14em] text-enterprise-blue uppercase">Governed PDF source</span>
          <h3 className="my-1 text-base font-black text-navy-900">PDF 검증 업로드</h3>
          <p className="m-0 text-xs text-slate-500">최대 50 MiB · application/pdf · FORMAT_ONLY_V1</p>
        </header>
        <label
          className="grid min-h-36 place-items-center rounded-enterprise border border-dashed border-enterprise-blue bg-blue-50 p-5 text-center text-xs font-bold text-enterprise-blue"
          htmlFor={inputId}
          aria-disabled={!graph || uploadBusy}
          onDragOver={(event) => event.preventDefault()}
          onDrop={dropFile}
        >
          <span><FileUp className="mx-auto mb-2" />{file?.name ?? 'PDF 파일을 드래그하거나 클릭하세요.'}<small className="mt-1 block font-normal text-slate-500">브라우저는 SHA-256을 증분 계산하고 원문은 오브젝트 스토리지로 직접 전송합니다.</small></span>
        </label>
        <input
          id={inputId}
          className="sr-only"
          aria-label="지식 PDF 소스"
          type="file"
          accept=".pdf,application/pdf"
          disabled={!graph || uploadBusy}
          onChange={(event) => selectFile(event.target.files?.[0])}
        />
        <button className="button" disabled={!graph || !file || uploadBusy || analysisBusy}>
          {uploadBusy ? <LoaderCircle size={14} className="animate-spin" /> : <FileUp size={14} />}
          {uploadBusy ? '검증 중…' : 'PDF 검증 업로드 시작'}
        </button>
        <div className="h-2 overflow-hidden rounded-full bg-slate-200" role="progressbar" aria-label="지식 PDF 업로드 진행률" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress * 100)}><span className="block h-full bg-enterprise-blue transition-[width]" style={{ width: `${Math.round(progress * 100)}%` }} /></div>
        <p className="m-0 text-xs text-slate-600" aria-live="polite">{status}</p>
        {record && <dl className="grid gap-2 text-xs sm:grid-cols-2">
          <div><dt className="font-black text-slate-500">Upload ID</dt><dd className="m-0 break-all"><code>{record.id}</code></dd></div>
          <div><dt className="font-black text-slate-500">State</dt><dd className="m-0"><span className="badge badge-soft">{record.state}</span></dd></div>
          <div><dt className="font-black text-slate-500">SHA-256</dt><dd className="m-0 break-all"><code>{record.sha256}</code></dd></div>
          <div><dt className="font-black text-slate-500">Classification</dt><dd className="m-0">{record.classification}</dd></div>
        </dl>}
      </form>

      <div className="grid content-start gap-3">
        <header>
          <span className="text-[10px] font-black tracking-[.14em] text-enterprise-blue uppercase">Typed LLM proposal</span>
          <h3 className="my-1 text-base font-black text-navy-900">PDF 분석 및 Changeset 생성</h3>
        </header>
        <label className="grid gap-1 text-xs font-black text-navy-900">제안 제목<input maxLength={500} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="분석 근거를 식별할 제목" /></label>
        <button type="button" className="button" disabled={record?.state !== 'ACCEPTED' || !title.trim() || analysisBusy || uploadBusy} onClick={() => void analyze()}>
          {analysisBusy ? <LoaderCircle size={14} className="animate-spin" /> : <Sparkles size={14} />}
          {analysisBusy ? 'LLM 분석 중…' : 'LLM 추출 제안 생성'}
        </button>
        {record && record.state !== 'ACCEPTED' && TERMINAL_UPLOAD_STATES.has(record.state) && <p className="notice notice-error" role="status">검증 상태가 {record.state}이므로 분석을 실행하지 않습니다.{record.last_error_code ? ` 오류 코드: ${record.last_error_code}` : ''}</p>}
        {analysis && <section className="grid gap-3 rounded-enterprise border border-emerald-300 bg-emerald-50 p-3" aria-label="지식 소스 분석 증거">
          <div className="flex items-center gap-2 text-emerald-800"><CheckCircle2 size={18} /><strong>DRAFT changeset 생성 완료</strong></div>
          <dl className="grid gap-2 text-xs sm:grid-cols-2">
            <div><dt className="font-black text-slate-500">Source snapshot</dt><dd className="m-0 break-all"><code>{analysis.source_snapshot_id}</code></dd></div>
            <div><dt className="font-black text-slate-500">Changeset</dt><dd className="m-0 break-all"><code>{analysis.changeset_id}</code></dd></div>
            <div><dt className="font-black text-slate-500">Pages</dt><dd className="m-0">{analysis.page_count.toLocaleString()}</dd></div>
            <div><dt className="font-black text-slate-500">Proposed graph</dt><dd className="m-0">{analysis.proposed_node_count.toLocaleString()} nodes · {analysis.proposed_edge_count.toLocaleString()} edges</dd></div>
            <div><dt className="font-black text-slate-500">Embedding model</dt><dd className="m-0 break-all">{analysis.embedding_model}</dd></div>
            <div><dt className="font-black text-slate-500">Extraction model</dt><dd className="m-0 break-all">{analysis.extraction_model}</dd></div>
            <div className="sm:col-span-2"><dt className="font-black text-slate-500">Evidence SHA-256</dt><dd className="m-0 break-all"><code>{analysis.evidence_hash}</code></dd></div>
          </dl>
          <p className="m-0 text-xs text-emerald-900">제안은 바로 Neo4j에 반영되지 않습니다. Mode A의 검토·릴리스 발행을 통과해야 합니다.</p>
        </section>}
      </div>
    </section>

    <section className="grid gap-3 rounded-enterprise border border-slate-300 bg-white p-4 shadow-sm">
      <header className="flex flex-wrap items-center justify-between gap-2"><div><span className="text-[10px] font-black tracking-[.14em] text-enterprise-blue uppercase">Verified Neo4j projection</span><h3 className="my-1 text-base font-black text-navy-900">발행 릴리스 Shadow 적재</h3></div><button type="button" className="button button-secondary" disabled={!graph || releaseBusy || projectionBusy} onClick={() => void loadReleases()}><RefreshCw size={13} /> 릴리스 새로고침</button></header>
      <div className="flex flex-wrap items-end gap-2">
        <label className="grid min-w-72 flex-1 gap-1 text-xs font-black text-navy-900">발행 릴리스<select value={selectedReleaseId} disabled={!graph || releaseBusy || projectionBusy} onChange={(event) => { setSelectedReleaseId(event.target.value); setProjection(undefined) }}><option value="">{releaseBusy ? '릴리스 조회 중…' : '릴리스 선택'}</option>{releases.map((release) => <option key={release.id} value={release.id}>Release v{release.release_no} · {release.node_count} nodes · {release.edge_count} edges</option>)}</select></label>
        <button type="button" className="button" disabled={!selectedReleaseId || projectionBusy || releaseBusy} onClick={() => void project()}>{projectionBusy ? <LoaderCircle size={14} className="animate-spin" /> : <Network size={14} />}{projectionBusy ? 'Shadow 검증 중…' : 'Neo4j Shadow 적재·검증'}</button>
      </div>
      {!releaseBusy && releases.length === 0 && <p className="m-0 text-xs text-slate-500">선택한 에셋에 발행된 릴리스가 없습니다. DRAFT changeset은 검토·승인·발행 후에만 프로젝션할 수 있습니다.</p>}
      {projection && <section className="grid gap-2 rounded-enterprise border border-emerald-300 bg-emerald-50 p-3" aria-label="Neo4j 프로젝션 영수증">
        <div className="flex items-center gap-2 text-emerald-800"><CheckCircle2 size={18} /><strong>{projection.state}</strong></div>
        <dl className="grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-3"><div><dt className="font-black text-slate-500">Deployment</dt><dd className="m-0 break-all"><code>{projection.deployment_id}</code></dd></div><div><dt className="font-black text-slate-500">Release</dt><dd className="m-0 break-all"><code>{projection.release_id}</code></dd></div><div><dt className="font-black text-slate-500">Counts</dt><dd className="m-0">{projection.node_count.toLocaleString()} nodes · {projection.edge_count.toLocaleString()} edges</dd></div><div className="sm:col-span-2 lg:col-span-3"><dt className="font-black text-slate-500">Release hash</dt><dd className="m-0 break-all"><code>{projection.release_hash}</code></dd></div></dl>
      </section>}
      <ErrorNotice error={error} />
    </section>
  </div>
}

export function validateKnowledgePdf(file: Pick<File, 'name' | 'type' | 'size'>): void {
  if (!file.name.toLowerCase().endsWith('.pdf') || (file.type && file.type !== 'application/pdf')) {
    throw new Error('Knowledge 소스는 application/pdf 형식의 .pdf 파일만 등록할 수 있습니다.')
  }
  if (file.size < 1) throw new Error('빈 PDF 파일은 등록할 수 없습니다.')
  if (file.size > MAX_PDF_SIZE_BYTES) throw new Error('Knowledge PDF는 최대 50 MiB까지 등록할 수 있습니다.')
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

function uploadStateLabel(record: UploadRecord): string {
  const labels: Record<string, string> = {
    COMPLETION_QUEUED: '오브젝트 완료 대기 중',
    COMPLETING: '오브젝트 완료 처리 중',
    QUARANTINED: '격리 완료, 검증 대기 중',
    VALIDATION_QUEUED: 'PDF 형식 검증 대기 중',
    VALIDATING: '무결성·PDF 형식 검증 중',
    ACCEPTED: '검증 통과 및 승인 버킷 승격 완료',
    REJECTED: `검증 거부 (${record.last_error_code ?? '원인 미상'})`,
    ABORTED: '업로드 중단',
    EXPIRED: '업로드 만료',
  }
  return labels[record.state] ?? record.state
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
