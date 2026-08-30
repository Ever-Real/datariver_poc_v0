import { createSHA256 } from 'hash-wasm'
import {
  CheckCircle2,
  FileUp,
  LoaderCircle,
  MessageSquareText,
  Network,
  RefreshCw,
  Sparkles,
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
  KnowledgeGraph,
  KnowledgeProjectionReceipt,
  KnowledgeRelease,
  KnowledgeSourceJob,
  KnowledgeSourceJobPage,
  UploadRecord,
} from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'

const MAX_KNOWLEDGE_SOURCE_SIZE_BYTES = 50 * 1024 * 1024
const HASH_CHUNK_SIZE = 4 * 1024 * 1024
const KNOWLEDGE_SOURCE_ACCEPT = [
  '.pdf',
  '.csv',
  '.txt',
  '.json',
  '.xml',
  '.html',
  '.htm',
  '.docx',
  '.xlsx',
  '.pptx',
].join(',')
const KNOWLEDGE_SOURCE_PROFILES: Record<string, ReadonlySet<string>> = {
  '.pdf': new Set(['application/pdf']),
  '.csv': new Set(['text/csv', 'application/csv', 'text/plain']),
  '.txt': new Set(['text/plain']),
  '.json': new Set(['application/json', 'text/json']),
  '.xml': new Set(['application/xml', 'text/xml']),
  '.html': new Set(['text/html', 'application/xhtml+xml']),
  '.htm': new Set(['text/html', 'application/xhtml+xml']),
  '.docx': new Set([
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  ]),
  '.xlsx': new Set([
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  ]),
  '.pptx': new Set([
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  ]),
}
const ANALYSIS_HISTORY_PAGE_LIMIT = 100
const MAX_KNOWLEDGE_PROMPT_CHARACTERS = 100_000
const TERMINAL_UPLOAD_STATES = new Set(['ACCEPTED', 'REJECTED', 'ABORTED', 'EXPIRED'])
const TERMINAL_ANALYSIS_STATES = new Set(['SUCCEEDED', 'FAILED', 'STALE', 'CANCELLED'])

type KnowledgeSourceInputMode = 'FILE' | 'PROMPT'

interface KnowledgeSourceUploadProps {
  client: ApiClient
  graph?: KnowledgeGraph
  onAnalysisCreated?: (changesetId: string) => void | Promise<void>
  onOpenChangeset?: (changesetId: string) => void | Promise<void>
}

export function KnowledgeSourceUpload({
  client,
  graph,
  onAnalysisCreated,
  onOpenChangeset,
}: KnowledgeSourceUploadProps) {
  const inputId = useId()
  const [inputMode, setInputMode] = useState<KnowledgeSourceInputMode>('FILE')
  const [promptText, setPromptText] = useState('')
  const [file, setFile] = useState<File>()
  const [title, setTitle] = useState('')
  const [record, setRecord] = useState<UploadRecord>()
  const [analysisJob, setAnalysisJob] = useState<KnowledgeSourceJob>()
  const [analysisJobs, setAnalysisJobs] = useState<KnowledgeSourceJob[]>([])
  const [analysisHistoryCursor, setAnalysisHistoryCursor] = useState<string | null>(null)
  const [analysisHistoryNextCursor, setAnalysisHistoryNextCursor] = useState<string | null>(null)
  const [analysisPollGeneration, setAnalysisPollGeneration] = useState(0)
  const [analysisPollingExhausted, setAnalysisPollingExhausted] = useState(false)
  const [cancelReason, setCancelReason] = useState('')
  const [releases, setReleases] = useState<KnowledgeRelease[]>([])
  const [selectedReleaseId, setSelectedReleaseId] = useState('')
  const [projection, setProjection] = useState<KnowledgeProjectionReceipt>()
  const [progress, setProgress] = useState(0)
  const [status, setStatus] = useState('지식 소스 문서를 선택하세요.')
  const [uploadBusy, setUploadBusy] = useState(false)
  const [analysisBusy, setAnalysisBusy] = useState(false)
  const [projectionBusy, setProjectionBusy] = useState(false)
  const [releaseBusy, setReleaseBusy] = useState(false)
  const [error, setError] = useState<unknown>()
  const generation = useRef(0)
  const controllers = useRef(new Set<AbortController>())
  const analysisCreatedCallback = useRef(onAnalysisCreated)
  const reportedAnalysisJobs = useRef(new Set<string>())
  const graphId = graph?.id
  const sourceAnalysisEligible = graph
    ? graph.classification === 'PUBLIC' || graph.classification === 'INTERNAL'
    : false

  useEffect(() => {
    analysisCreatedCallback.current = onAnalysisCreated
  }, [onAnalysisCreated])

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
    setInputMode('FILE')
    setPromptText('')
    setFile(undefined)
    setTitle('')
    setRecord(undefined)
    setAnalysisJob(undefined)
    setAnalysisJobs([])
    setAnalysisHistoryCursor(null)
    setAnalysisHistoryNextCursor(null)
    setAnalysisPollGeneration(0)
    setAnalysisPollingExhausted(false)
    setCancelReason('')
    setProjection(undefined)
    setProgress(0)
    setStatus(graph ? '지식 소스 문서를 선택하세요.' : '대상 지식 에셋을 선택하세요.')
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

  useEffect(() => {
    if (!graphId) return
    const { controller, expectedGeneration } = beginOperation()
    void (async () => {
      const cursorQuery = analysisHistoryCursor
        ? `&cursor=${encodeURIComponent(analysisHistoryCursor)}`
        : ''
      const page = await client.request<KnowledgeSourceJobPage>(
        `/knowledge/graphs/${graphId}/source-analysis-jobs?limit=${ANALYSIS_HISTORY_PAGE_LIMIT}${cursorQuery}`,
        { signal: controller.signal },
      )
      if (expectedGeneration !== generation.current) return
      setAnalysisJobs(page.items)
      setAnalysisHistoryNextCursor(page.next_cursor)
      if (!analysisHistoryCursor) {
        setAnalysisJob((current) => (
          page.items.find((item) => item.id === current?.id)
          ?? page.items.find((item) => !TERMINAL_ANALYSIS_STATES.has(item.state))
          ?? page.items[0]
        ))
      }
    })().catch((next: unknown) => {
      if (!controller.signal.aborted && expectedGeneration === generation.current) setError(next)
    }).finally(() => finishOperation(controller))
    return () => controller.abort()
  }, [analysisHistoryCursor, beginOperation, client, finishOperation, graphId])

  const analysisTerminal = analysisJob
    ? TERMINAL_ANALYSIS_STATES.has(analysisJob.state)
    : true

  useEffect(() => {
    const jobId = analysisJob?.id
    if (!graphId || !jobId || analysisTerminal) return
    const { controller, expectedGeneration } = beginOperation()
    setAnalysisBusy(true)
    setAnalysisPollingExhausted(false)
    void (async () => {
      for (let attempt = 0; attempt < 120; attempt += 1) {
        await waitUntilVisible(controller.signal)
        const current = await client.request<KnowledgeSourceJob>(
          `/knowledge/graphs/${graphId}/source-analysis-jobs/${jobId}`,
          { signal: controller.signal },
        )
        if (expectedGeneration !== generation.current) return
        setAnalysisJob(current)
        setAnalysisJobs((items) => (
          items.some((item) => item.id === current.id)
            ? items.map((item) => item.id === current.id ? current : item)
            : items
        ))
        setStatus(analysisJobStateLabel(current))
        if (TERMINAL_ANALYSIS_STATES.has(current.state)) {
          const result = current.result
          if (
            current.state === 'SUCCEEDED'
            && result
            && !reportedAnalysisJobs.current.has(current.id)
          ) {
            reportedAnalysisJobs.current.add(current.id)
            await analysisCreatedCallback.current?.(result.changeset_id)
          }
          return
        }
        await abortableDelay(1000, controller.signal)
      }
      if (expectedGeneration === generation.current) {
        setStatus('분석 작업이 계속 진행 중입니다. 작업 목록에서 다시 이어서 확인할 수 있습니다.')
        setAnalysisPollingExhausted(true)
      }
    })().catch((next: unknown) => {
      if (!controller.signal.aborted && expectedGeneration === generation.current) setError(next)
    }).finally(() => {
      finishOperation(controller)
      if (expectedGeneration === generation.current) setAnalysisBusy(false)
    })
    return () => controller.abort()
  }, [
    analysisJob?.id,
    analysisPollGeneration,
    analysisTerminal,
    beginOperation,
    client,
    finishOperation,
    graphId,
  ])

  const pollUpload = async (
    sourceGraphId: string,
    uploadId: string,
    controller: AbortController,
    expectedGeneration: number,
  ): Promise<UploadRecord | undefined> => {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      const current = await client.request<UploadRecord>(
        `/knowledge/graphs/${sourceGraphId}/source-uploads/${uploadId}`,
        {
          signal: controller.signal,
        },
      )
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
    setAnalysisJob(undefined)
    setProjection(undefined)
    setProgress(0)
    try {
      const contentType = validateKnowledgeDocument(file)
      setStatus('SHA-256 계산 중')
      const sha256 = await digestFile(file, controller.signal, (value) => {
        if (expectedGeneration === generation.current) setProgress(value * 0.15)
      })
      const sourceUploadPath = `/knowledge/graphs/${graph.id}/source-uploads`
      const initiated = await client.request<UploadRecord>(sourceUploadPath, {
        method: 'POST',
        idempotencyKey: newIdempotencyKey('knowledge-source-upload'),
        signal: controller.signal,
        body: JSON.stringify({
          display_name: file.name,
          size_bytes: file.size,
          content_type: contentType,
          sha256,
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
        const signed = await client.request<{ url: string }>(
          `${sourceUploadPath}/${initiated.id}/parts`,
          {
            method: 'POST',
            signal: controller.signal,
            body: JSON.stringify({ part_number: partNumber }),
          },
        )
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
      const queued = await client.request<UploadRecord>(
        `${sourceUploadPath}/${initiated.id}/complete`,
        {
          method: 'POST',
          idempotencyKey: newIdempotencyKey('knowledge-source-complete'),
          ifMatch: `"${initiated.version}"`,
          signal: controller.signal,
          body: JSON.stringify({ parts }),
        },
      )
      if (expectedGeneration !== generation.current) return
      setRecord(queued)
      setProgress(0.97)
      setStatus('무결성·문서 형식 검증 대기 중')
      const terminal = await pollUpload(graph.id, queued.id, controller, expectedGeneration)
      if (terminal && expectedGeneration === generation.current) setProgress(1)
    } catch (next) {
      if (!controller.signal.aborted && expectedGeneration === generation.current) {
        setError(next)
        setStatus('문서 업로드 또는 검증 실패')
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
    setAnalysisJob(undefined)
    setProjection(undefined)
    try {
      const result = await client.request<KnowledgeSourceJob>(
        `/knowledge/graphs/${graph.id}/sources/${record.id}/analyze`,
        {
          method: 'POST',
          idempotencyKey: newIdempotencyKey('knowledge-source-analysis'),
          signal: controller.signal,
          body: JSON.stringify({ title: title.trim() }),
        },
      )
      if (expectedGeneration !== generation.current) return
      setAnalysisJob(result)
      setAnalysisJobs((items) => (
        [result, ...items.filter((item) => item.id !== result.id)]
          .slice(0, ANALYSIS_HISTORY_PAGE_LIMIT)
      ))
      setStatus(analysisJobStateLabel(result))
    } catch (next) {
      if (!controller.signal.aborted && expectedGeneration === generation.current) setError(next)
    } finally {
      finishOperation(controller)
      if (expectedGeneration === generation.current) setAnalysisBusy(false)
    }
  }

  const cancelAnalysis = async () => {
    if (!graph || !analysisJob || analysisTerminal || !cancelReason.trim()) return
    const { controller, expectedGeneration } = beginOperation()
    setError(undefined)
    try {
      const current = await client.request<KnowledgeSourceJob>(
        `/knowledge/graphs/${graph.id}/source-analysis-jobs/${analysisJob.id}/cancel`,
        {
          method: 'POST',
          idempotencyKey: newIdempotencyKey('knowledge-source-analysis-cancel'),
          ifMatch: `"${analysisJob.version}"`,
          signal: controller.signal,
          body: JSON.stringify({ reason: cancelReason.trim() }),
        },
      )
      if (expectedGeneration !== generation.current) return
      setAnalysisJob(current)
      setAnalysisJobs((items) => items.map((item) => item.id === current.id ? current : item))
      setStatus(analysisJobStateLabel(current))
    } catch (next) {
      if (!controller.signal.aborted && expectedGeneration === generation.current) setError(next)
    } finally {
      finishOperation(controller)
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
    setAnalysisJob(undefined)
    setProjection(undefined)
    setProgress(0)
    if (!next) {
      setFile(undefined)
      setStatus('지식 소스 문서를 선택하세요.')
      return
    }
    try {
      validateKnowledgeDocument(next)
      setFile(next)
      setTitle((current) => current.trim() ? current : `${next.name} 지식 추출 제안`)
      setStatus(`${next.name} 업로드 준비됨`)
    } catch (nextError) {
      setFile(undefined)
      setStatus('지원되는 지식 소스 문서가 필요합니다.')
      setError(nextError)
    }
  }

  const selectInputMode = (next: KnowledgeSourceInputMode) => {
    if (uploadBusy || analysisBusy || next === inputMode) return
    setInputMode(next)
    selectFile(undefined)
    setTitle('')
  }

  const preparePromptSource = () => {
    try {
      const promptFile = createKnowledgePromptDocument(promptText)
      selectFile(promptFile)
      setTitle('LLM 입력 텍스트 지식 추출 제안')
      setStatus('자연어 입력을 검증 가능한 TXT 원천으로 준비했습니다.')
    } catch (next) {
      setFile(undefined)
      setError(next)
    }
  }

  const dropFile = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault()
    if (!sourceAnalysisEligible) return
    selectFile(event.dataTransfer.files[0])
  }

  const analysis = analysisJob?.result

  return <div className="grid gap-4">
    <section className="grid gap-4 rounded-enterprise border border-slate-300 bg-white p-4 shadow-sm lg:grid-cols-[minmax(0,1fr)_minmax(280px,0.65fr)]">
      <form className="grid gap-3" onSubmit={(event) => void upload(event)}>
        <header>
          <span className="text-[10px] font-black tracking-[.14em] text-enterprise-blue uppercase">Governed document source</span>
          <h3 className="my-1 text-base font-black text-navy-900">파일 또는 LLM 입력 원천</h3>
          <p className="m-0 text-xs text-slate-500">파일과 자연어 입력 모두 해시된 불변 원천으로 검증한 뒤 같은 A-Box Changeset 경로를 사용합니다.</p>
        </header>
        <div className="flex flex-wrap gap-2" aria-label="A-Box LLM 입력 방식">
          <button
            type="button"
            className={`button ${inputMode === 'FILE' ? '' : 'button-secondary'}`}
            aria-pressed={inputMode === 'FILE'}
            disabled={uploadBusy || analysisBusy}
            onClick={() => selectInputMode('FILE')}
          >
            <FileUp size={13} /> 파일 업로드
          </button>
          <button
            type="button"
            className={`button ${inputMode === 'PROMPT' ? '' : 'button-secondary'}`}
            aria-pressed={inputMode === 'PROMPT'}
            disabled={uploadBusy || analysisBusy}
            onClick={() => selectInputMode('PROMPT')}
          >
            <MessageSquareText size={13} /> LLM 자연어 입력
          </button>
        </div>
        {inputMode === 'FILE' ? (
          <label
            className="grid min-h-36 place-items-center rounded-enterprise border border-dashed border-enterprise-blue bg-blue-50 p-5 text-center text-xs font-bold text-enterprise-blue"
            htmlFor={inputId}
            aria-disabled={!graph || !sourceAnalysisEligible || uploadBusy}
            onDragOver={(event) => event.preventDefault()}
            onDrop={dropFile}
          >
            <span><FileUp className="mx-auto mb-2" />{file?.name ?? '지식 소스 문서를 드래그하거나 클릭하세요.'}<small className="mt-1 block font-normal text-slate-500">PDF, CSV, TXT, JSON, XML, HTML, DOCX, XLSX, PPTX · 최대 50 MiB · DOC/XLS 제외</small></span>
          </label>
        ) : (
          <section className="grid gap-2 rounded-enterprise border border-enterprise-blue bg-blue-50 p-4">
            <label className="grid gap-1 text-xs font-black text-navy-900">
              A-Box로 제안할 자연어 입력
              <textarea
                className="min-h-36 bg-white text-sm leading-6"
                maxLength={MAX_KNOWLEDGE_PROMPT_CHARACTERS}
                value={promptText}
                placeholder="예: 고객 김하늘은 서울 지점의 법인 고객이며 담당자는 이수진입니다."
                disabled={!graph || !sourceAnalysisEligible || uploadBusy || analysisBusy}
                onChange={(event) => setPromptText(event.target.value)}
              />
            </label>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <small className="text-slate-500">
                {promptText.length.toLocaleString()} / {MAX_KNOWLEDGE_PROMPT_CHARACTERS.toLocaleString()}자
              </small>
              <button
                type="button"
                className="button button-secondary"
                disabled={!graph || !sourceAnalysisEligible || !promptText.trim() || uploadBusy || analysisBusy}
                onClick={preparePromptSource}
              >
                <MessageSquareText size={13} /> 검증 원천으로 준비
              </button>
            </div>
            <p className="m-0 text-xs leading-5 text-slate-600">
              입력은 브라우저에서 임의 인스턴스로 변환되지 않습니다. UTF-8 TXT 원천으로 고정·검증되고,
              별도 worker가 T-Box에 맞는 typed DRAFT Changeset만 제안합니다.
            </p>
          </section>
        )}
        <input
          id={inputId}
          className="sr-only"
          aria-label="지식 문서 소스"
          type="file"
          accept={KNOWLEDGE_SOURCE_ACCEPT}
          disabled={!graph || !sourceAnalysisEligible || uploadBusy}
          onChange={(event) => selectFile(event.target.files?.[0])}
        />
        <button className="button" disabled={!graph || !sourceAnalysisEligible || !file || uploadBusy || analysisBusy}>
          {uploadBusy ? <LoaderCircle size={14} className="animate-spin" /> : <FileUp size={14} />}
          {uploadBusy ? '검증 중…' : '문서 검증 업로드 시작'}
        </button>
        <progress className="h-2 w-full appearance-none overflow-hidden rounded-full bg-slate-200 [&::-moz-progress-bar]:bg-enterprise-blue [&::-moz-progress-bar]:transition-all [&::-webkit-progress-bar]:bg-slate-200 [&::-webkit-progress-value]:bg-enterprise-blue [&::-webkit-progress-value]:transition-all" aria-label="지식 문서 업로드 진행률" max={100} value={Math.round(progress * 100)} />
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
          <h3 className="my-1 text-base font-black text-navy-900">문서 분석 및 Changeset 생성</h3>
        </header>
        {graph && !sourceAnalysisEligible && <p className="notice notice-error" role="status">현재 추론 공급자 계약은 PUBLIC/INTERNAL 소스만 허용합니다. {graph.classification} 지식 에셋은 분류를 낮추지 않으며 문서 업로드·분석을 실행하지 않습니다.</p>}
        <label className="grid gap-1 text-xs font-black text-navy-900">제안 제목<input maxLength={500} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="분석 근거를 식별할 제목" /></label>
        <button type="button" className="button" disabled={!sourceAnalysisEligible || record?.state !== 'ACCEPTED' || !title.trim() || analysisBusy || uploadBusy || Boolean(analysisJob && !analysisTerminal)} onClick={() => void analyze()}>
          {analysisBusy ? <LoaderCircle size={14} className="animate-spin" /> : <Sparkles size={14} />}
          {analysisBusy ? 'LLM 분석 작업 확인 중…' : 'LLM 추출 제안 생성'}
        </button>
        {analysisJobs.length > 0 && <section className="grid gap-2 rounded-enterprise border border-slate-300 bg-white p-3" aria-label="최근 지식 소스 분석 작업">
          <strong className="text-xs text-navy-900">내 최근 분석 작업 · 실행 중 우선</strong>
          <div className="grid max-h-48 gap-1 overflow-y-auto">
            {analysisJobs.map((job) => <button
              key={job.id}
              type="button"
              aria-pressed={analysisJob?.id === job.id}
              className={`flex items-center gap-2 rounded border px-2 py-1 text-left text-xs ${analysisJob?.id === job.id ? 'border-enterprise-blue bg-blue-50' : 'border-slate-200 bg-white'}`}
              onClick={() => {
                setAnalysisJob(job)
                setCancelReason('')
                if (!TERMINAL_ANALYSIS_STATES.has(job.state)) {
                  setAnalysisPollGeneration((value) => value + 1)
                }
              }}
            >
              <span className="badge badge-soft">{job.state}</span>
              <span className="min-w-0 flex-1 truncate">{job.title}</span>
              <time dateTime={job.created_at}>{new Date(job.created_at).toLocaleString()}</time>
            </button>)}
          </div>
          <div className="flex gap-2">
            <button type="button" className="button button-secondary" disabled={!analysisHistoryCursor} onClick={() => setAnalysisHistoryCursor(null)}>실행 중·최신으로</button>
            <button type="button" className="button button-secondary" disabled={!analysisHistoryNextCursor} onClick={() => setAnalysisHistoryCursor(analysisHistoryNextCursor)}>더 오래된 작업</button>
          </div>
        </section>}
        {analysisJob && <section className="grid gap-2 rounded-enterprise border border-slate-300 bg-slate-50 p-3" aria-label="지식 소스 분석 작업">
          <div className="flex flex-wrap items-center gap-2 text-xs"><strong>작업 상태</strong><span className="badge badge-soft">{analysisJob.state}</span><span>{analysisJob.stage}</span><span>시도 {analysisJob.attempt_count}/{analysisJob.maximum_attempts}</span></div>
          {analysisJob.progress.total_pages !== undefined && <p className="m-0 text-xs text-slate-600">{analysisJob.progress.completed_pages ?? 0}/{analysisJob.progress.total_pages} evidence segments</p>}
          {analysisJob.last_failure_code && <p className="notice notice-error m-0" role="status">오류 코드: {analysisJob.last_failure_code}</p>}
          {!analysisTerminal && analysisPollingExhausted && <button type="button" className="button button-secondary w-fit" onClick={() => setAnalysisPollGeneration((value) => value + 1)}>확인 다시 시작</button>}
          {!analysisTerminal && <div className="flex flex-wrap items-end gap-2"><label className="grid min-w-64 flex-1 gap-1 text-xs font-black">취소 사유<input maxLength={1000} value={cancelReason} onChange={(event) => setCancelReason(event.target.value)} placeholder="감사 로그에 남을 사유" /></label><button type="button" className="button button-danger" disabled={!cancelReason.trim()} onClick={() => void cancelAnalysis()}>작업 취소</button></div>}
        </section>}
        {record && record.state !== 'ACCEPTED' && TERMINAL_UPLOAD_STATES.has(record.state) && <p className="notice notice-error" role="status">검증 상태가 {record.state}이므로 분석을 실행하지 않습니다.{record.last_error_code ? ` 오류 코드: ${record.last_error_code}` : ''}</p>}
        {analysis && <section className="grid gap-3 rounded-enterprise border border-emerald-300 bg-emerald-50 p-3" aria-label="지식 소스 분석 증거">
          <div className="flex items-center gap-2 text-emerald-800"><CheckCircle2 size={18} /><strong>DRAFT changeset 생성 완료</strong></div>
          <dl className="grid gap-2 text-xs sm:grid-cols-2">
            <div><dt className="font-black text-slate-500">Source snapshot</dt><dd className="m-0 break-all"><code>{analysisJob?.source_snapshot_id}</code></dd></div>
            <div><dt className="font-black text-slate-500">Changeset</dt><dd className="m-0 break-all"><code>{analysis.changeset_id}</code></dd></div>
            <div><dt className="font-black text-slate-500">Evidence segments</dt><dd className="m-0">{analysis.page_count.toLocaleString()}</dd></div>
            <div><dt className="font-black text-slate-500">Proposed graph</dt><dd className="m-0">{analysis.proposed_node_count.toLocaleString()} nodes · {analysis.proposed_edge_count.toLocaleString()} edges</dd></div>
            <div><dt className="font-black text-slate-500">Embedding model</dt><dd className="m-0 break-all">{analysis.embedding_model}</dd></div>
            <div><dt className="font-black text-slate-500">Extraction model</dt><dd className="m-0 break-all">{analysis.extraction_model}</dd></div>
            <div className="sm:col-span-2"><dt className="font-black text-slate-500">Evidence SHA-256</dt><dd className="m-0 break-all"><code>{analysis.evidence_hash}</code></dd></div>
          </dl>
          <p className="m-0 text-xs text-emerald-900">제안은 바로 Neo4j에 반영되지 않습니다. Mode A의 검토·릴리스 발행을 통과해야 합니다.</p>
          {onOpenChangeset && <button
            type="button"
            className="button w-fit"
            onClick={() => void onOpenChangeset(analysis.changeset_id)}
          >
            DRAFT 검토로 이동
          </button>}
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

export function validateKnowledgeDocument(
  file: Pick<File, 'name' | 'type' | 'size'>,
): string {
  const suffix = file.name.toLowerCase().match(/\.[^.]+$/)?.[0] ?? ''
  const acceptedTypes = KNOWLEDGE_SOURCE_PROFILES[suffix]
  if (!acceptedTypes) {
    throw new Error('지원 형식은 PDF, CSV, TXT, JSON, XML, HTML, DOCX, XLSX, PPTX입니다.')
  }
  const declaredType = file.type.trim().toLowerCase()
  if (declaredType && !acceptedTypes.has(declaredType)) {
    throw new Error('파일 확장자와 브라우저가 확인한 문서 형식이 일치하지 않습니다.')
  }
  if (file.size < 1) throw new Error('빈 지식 소스 문서는 등록할 수 없습니다.')
  if (file.size > MAX_KNOWLEDGE_SOURCE_SIZE_BYTES) {
    throw new Error('Knowledge 소스 문서는 최대 50 MiB까지 등록할 수 있습니다.')
  }
  return [...acceptedTypes][0] ?? 'application/octet-stream'
}

export function createKnowledgePromptDocument(prompt: string): File {
  const normalized = prompt.normalize('NFC').replaceAll('\r\n', '\n').trim()
  if (!normalized) throw new Error('LLM 자연어 입력을 작성하세요.')
  if (normalized.length > MAX_KNOWLEDGE_PROMPT_CHARACTERS) {
    throw new Error('LLM 자연어 입력은 최대 100,000자까지 사용할 수 있습니다.')
  }
  return new File([`${normalized}\n`], 'knowledge-prompt.txt', {
    type: 'text/plain',
    lastModified: 0,
  })
}

export function validateKnowledgePdf(file: Pick<File, 'name' | 'type' | 'size'>): void {
  if (!file.name.toLowerCase().endsWith('.pdf')) {
    throw new Error('Knowledge PDF는 .pdf 파일이어야 합니다.')
  }
  validateKnowledgeDocument(file)
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
    VALIDATION_QUEUED: '문서 형식 검증 대기 중',
    VALIDATING: '무결성·문서 형식 검증 중',
    ACCEPTED: '검증 통과 및 승인 버킷 승격 완료',
    REJECTED: `검증 거부 (${record.last_error_code ?? '원인 미상'})`,
    ABORTED: '업로드 중단',
    EXPIRED: '업로드 만료',
  }
  return labels[record.state] ?? record.state
}

function analysisJobStateLabel(job: KnowledgeSourceJob): string {
  const labels: Record<KnowledgeSourceJob['state'], string> = {
    QUEUED: '문서 분석 작업이 대기열에 등록되었습니다.',
    RUNNING: `문서 분석 진행 중 · ${job.stage}`,
    RETRY_WAIT: `일시 오류로 재시도 대기 중 (${job.last_failure_code ?? '원인 미상'})`,
    CANCEL_REQUESTED: '실행 중인 작업에 취소를 요청했습니다.',
    SUCCEEDED: 'LLM 추출 제안이 DRAFT changeset으로 생성되었습니다.',
    FAILED: `문서 분석 실패 (${job.last_failure_code ?? '원인 미상'})`,
    STALE: `고정된 입력 또는 권한이 변경되어 작업을 종료했습니다. (${job.last_failure_code ?? '원인 미상'})`,
    CANCELLED: '문서 분석 작업이 취소되었습니다.',
  }
  return labels[job.state]
}

function waitUntilVisible(signal: AbortSignal): Promise<void> {
  if (signal.aborted) {
    return Promise.reject(new DOMException('The operation was aborted.', 'AbortError'))
  }
  if (document.visibilityState === 'visible') return Promise.resolve()
  return new Promise((resolve, reject) => {
    const onAbort = () => {
      document.removeEventListener('visibilitychange', onVisibility)
      reject(new DOMException('The operation was aborted.', 'AbortError'))
    }
    const onVisibility = () => {
      if (document.visibilityState !== 'visible') return
      signal.removeEventListener('abort', onAbort)
      document.removeEventListener('visibilitychange', onVisibility)
      resolve()
    }
    signal.addEventListener('abort', onAbort, { once: true })
    document.addEventListener('visibilitychange', onVisibility)
  })
}

function abortableDelay(milliseconds: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted) {
    return Promise.reject(new DOMException('The operation was aborted.', 'AbortError'))
  }
  return new Promise((resolve, reject) => {
    const onAbort = () => {
      window.clearTimeout(timeout)
      reject(new DOMException('The operation was aborted.', 'AbortError'))
    }
    const timeout = window.setTimeout(() => {
      signal.removeEventListener('abort', onAbort)
      resolve()
    }, milliseconds)
    signal.addEventListener('abort', onAbort, { once: true })
  })
}
