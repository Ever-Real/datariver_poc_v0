import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiClient, RequestOptions } from '../../api/client'
import type {
  KnowledgeChangeSet,
  KnowledgeGraph,
  KnowledgeSourceJob,
  UploadRecord,
} from '../../api/types'
import { KnowledgeIngestionStudio } from './KnowledgeIngestionStudio'
import {
  createKnowledgePromptDocument,
  validateKnowledgeDocument,
  validateKnowledgePdf,
} from './KnowledgeSourceUpload'

function jsonBody(options?: RequestOptions): Record<string, unknown> {
  if (typeof options?.body !== 'string') throw new Error('Expected a JSON request body.')
  return JSON.parse(options.body) as Record<string, unknown>
}

const graph: KnowledgeGraph = {
  id: 'graph-1',
  slug: 'semiconductor',
  name: 'Semiconductor',
  graph_type: 'CURATED_KNOWLEDGE',
  status: 'ACTIVE',
  classification: 'INTERNAL',
  active_release_id: 'release-1',
  version: 3,
}

function uploadRecord(
  state: string,
  version: number,
  lastErrorCode: string | null = null,
  classification: KnowledgeGraph['classification'] = graph.classification,
): UploadRecord {
  return {
    id: 'upload-1',
    display_name: 'semiconductor-outlook.pdf',
    state,
    size_bytes: 24,
    content_type: 'application/pdf',
    sha256: 'a'.repeat(64),
    classification,
    content_profile: 'KNOWLEDGE_SOURCE_DOCUMENT_V1',
    expires_at: '2026-07-22T00:00:00Z',
    version,
    recommended_part_size_bytes: 16 * 1024 * 1024,
    validation_summary: state === 'ACCEPTED' ? { media_type: 'application/pdf' } : {},
    last_error_code: lastErrorCode,
  }
}

function sourceJob(
  state: KnowledgeSourceJob['state'],
  version: number,
  overrides: Partial<KnowledgeSourceJob> = {},
): KnowledgeSourceJob {
  return {
    id: 'source-job-1',
    graph_id: graph.id,
    source_snapshot_id: 'snapshot-1',
    upload_id: 'upload-1',
    title: 'semiconductor-outlook.pdf 지식 추출 제안',
    state,
    stage: state === 'SUCCEEDED' || state === 'CANCELLED' ? 'COMPLETED' : 'QUEUED',
    progress: {},
    attempt_count: state === 'QUEUED' ? 0 : 1,
    maximum_attempts: 3,
    next_attempt_at: '2026-07-22T00:00:00Z',
    last_failure_code: null,
    version,
    created_at: '2026-07-22T00:00:00Z',
    updated_at: '2026-07-22T00:00:00Z',
    completed_at: state === 'SUCCEEDED' || state === 'CANCELLED'
      ? '2026-07-22T00:01:00Z'
      : null,
    result: state === 'SUCCEEDED' ? {
      changeset_id: 'changeset-2',
      page_count: 105,
      proposed_node_count: 32,
      proposed_edge_count: 19,
      evidence_hash: 'c'.repeat(64),
      embedding_model: 'bge-m3:latest',
      extraction_model: 'datariver-gemma4-dev:0.1',
    } : null,
    ...overrides,
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('KnowledgeIngestionStudio', () => {
  it('enforces the 50 MiB PDF source boundary before hashing', () => {
    expect(() => validateKnowledgePdf({
      name: 'oversized.pdf',
      type: 'application/pdf',
      size: 50 * 1024 * 1024 + 1,
    })).toThrow('최대 50 MiB')
  })

  it('accepts the governed A-Box document allowlist and canonicalizes browser MIME aliases', () => {
    expect(validateKnowledgeDocument({
      name: 'customers.csv',
      type: 'application/csv',
      size: 128,
    })).toBe('text/csv')
    expect(validateKnowledgeDocument({
      name: 'policy.docx',
      type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      size: 256,
    })).toBe('application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    expect(() => validateKnowledgeDocument({
      name: 'legacy.doc',
      type: 'application/msword',
      size: 128,
    })).toThrow(/지원 형식/)
  })

  it('turns a bounded natural-language A-Box request into a governed TXT source', () => {
    const source = createKnowledgePromptDocument('  고객 김하늘은 서울 지점에 소속됩니다.  ')

    expect(source.name).toBe('knowledge-prompt.txt')
    expect(source.type).toBe('text/plain')
    expect(source.lastModified).toBe(0)
    expect(source.size).toBeGreaterThan(0)
    expect(validateKnowledgeDocument(source)).toBe('text/plain')
    expect(() => createKnowledgePromptDocument('   ')).toThrow('자연어 입력을 작성')
    expect(() => createKnowledgePromptDocument('x'.repeat(100_001))).toThrow('최대 100,000자')
  })

  it('uses the backend REVIEW state and a light enterprise mode selector', async () => {
    const request = vi.fn((path: string) => {
      if (path === '/knowledge/graphs') return Promise.resolve([{
        id: 'graph-1', slug: 'semiconductor', name: 'Semiconductor',
        graph_type: 'CURATED_KNOWLEDGE', status: 'DRAFT', classification: 'CONFIDENTIAL',
        active_release_id: null, version: 1,
      }])
      if (path === '/knowledge/graphs/graph-1/changesets') return Promise.resolve([{
        id: 'changeset-1', graph_id: 'graph-1', base_release_id: null,
        ontology_version_id: 'ontology-1', title: 'PwC extraction proposal', state: 'REVIEW',
        author_id: 'author-1', reviewed_by: null, review_reason: null,
        published_release_id: null, version: 2, created_at: '2026-07-21T00:00:00Z',
        updated_at: '2026-07-21T00:00:00Z', operations: [], validations: [],
      }])
      throw new Error(`Unexpected request: ${path}`)
    })
    render(<KnowledgeIngestionStudio client={{ request } as unknown as ApiClient} />)

    const modeA = screen.getByRole('button', { name: /MODE A/ })
    expect(modeA.parentElement).toHaveClass('bg-white')
    expect(modeA.parentElement).not.toHaveClass('bg-navy-900')
    fireEvent.click(await screen.findByRole('tab', { name: '직접 정의' }))

    expect(await screen.findByText('PwC extraction proposal')).toBeInTheDocument()
    expect(screen.getByText('REVIEW')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '승인' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '반려' })).toBeInTheDocument()
  })

  it('runs the governed source upload, analysis, and verified projection request sequence', async () => {
    const calls: Array<[string, RequestOptions | undefined]> = []
    let analysisSucceeded = false
    const generatedChangeset: KnowledgeChangeSet = {
      id: 'changeset-2',
      graph_id: graph.id,
      base_release_id: graph.active_release_id ?? null,
      ontology_version_id: 'ontology-1',
      title: 'semiconductor-outlook.pdf 지식 추출 제안',
      state: 'DRAFT',
      author_id: 'author-1',
      reviewed_by: null,
      review_reason: null,
      published_release_id: null,
      version: 1,
      created_at: '2026-07-22T00:01:00Z',
      updated_at: '2026-07-22T00:01:00Z',
      operations: [],
      validations: [],
    }
    const request = vi.fn((path: string, options?: RequestOptions) => {
      calls.push([path, options])
      if (path === '/knowledge/graphs') return Promise.resolve([graph])
      if (path === '/knowledge/graphs/graph-1/changesets') {
        return Promise.resolve(analysisSucceeded ? [generatedChangeset] : [])
      }
      if (path === '/knowledge/graphs/graph-1/releases') return Promise.resolve([{
        id: 'release-1', graph_id: 'graph-1', release_no: 2, ontology_version_id: 'ontology-1',
        content_hash: 'b'.repeat(64), node_count: 12, edge_count: 7,
        published_at: '2026-07-21T01:00:00Z',
      }])
      if (path === '/knowledge/graphs/graph-1/source-analysis-jobs?limit=100') {
        return Promise.resolve({ items: [], next_cursor: null })
      }
      if (path === '/knowledge/graphs/graph-1/source-uploads' && options?.method === 'POST') {
        return Promise.resolve(uploadRecord('INITIATED', 1))
      }
      if (path === '/knowledge/graphs/graph-1/source-uploads/upload-1/parts') return Promise.resolve({ url: 'https://objects.test/part-1' })
      if (path === '/knowledge/graphs/graph-1/source-uploads/upload-1/complete') {
        return Promise.resolve(uploadRecord('VALIDATION_QUEUED', 2))
      }
      if (path === '/knowledge/graphs/graph-1/source-uploads/upload-1' && !options?.method) {
        return Promise.resolve(uploadRecord('ACCEPTED', 3))
      }
      if (path === '/knowledge/graphs/graph-1/sources/upload-1/analyze') {
        return Promise.resolve(sourceJob('QUEUED', 1))
      }
      if (path === '/knowledge/graphs/graph-1/source-analysis-jobs/source-job-1') {
        analysisSucceeded = true
        return Promise.resolve(sourceJob('SUCCEEDED', 2))
      }
      if (path === '/knowledge/graphs/graph-1/releases/release-1/project') {
        return Promise.resolve({
          deployment_id: 'deployment-1', release_id: 'release-1', release_hash: 'b'.repeat(64),
          node_count: 12, edge_count: 7, state: 'SHADOW_VERIFIED',
        })
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(null, {
      status: 200,
      headers: { ETag: '"part-etag-1"' },
    }))))

    render(<KnowledgeIngestionStudio client={{ request } as unknown as ApiClient} />)
    fireEvent.click(screen.getByRole('button', { name: /MODE B/ }))
    await screen.findByRole('button', { name: 'LLM 자연어 입력' })
    await waitFor(() => expect(screen.getByLabelText('지식 문서 소스')).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'LLM 자연어 입력' }))
    fireEvent.change(await screen.findByLabelText('A-Box로 제안할 자연어 입력'), {
      target: { value: '고객 김하늘은 서울 지점에 소속됩니다.' },
    })
    fireEvent.click(screen.getByRole('button', { name: '검증 원천으로 준비' }))
    fireEvent.click(screen.getByRole('button', { name: '문서 검증 업로드 시작' }))

    expect(await screen.findByText('ACCEPTED')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: 'LLM 추출 제안 생성' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'LLM 추출 제안 생성' }))

    const analysis = await screen.findByLabelText('지식 소스 분석 증거')
    expect(within(analysis).getByText('snapshot-1')).toBeInTheDocument()
    expect(within(analysis).getByText('changeset-2')).toBeInTheDocument()
    expect(within(analysis).getByText('105')).toBeInTheDocument()
    expect(within(analysis).getByText('32 nodes · 19 edges')).toBeInTheDocument()
    expect(within(analysis).getByText('bge-m3:latest')).toBeInTheDocument()
    expect(within(analysis).getByText('datariver-gemma4-dev:0.1')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Neo4j Shadow 적재·검증' }))
    const receipt = await screen.findByLabelText('Neo4j 프로젝션 영수증')
    expect(within(receipt).getByText('SHADOW_VERIFIED')).toBeInTheDocument()
    expect(within(receipt).getByText('deployment-1')).toBeInTheDocument()

    fireEvent.click(within(analysis).getByRole('button', { name: 'DRAFT 검토로 이동' }))
    const directTab = await screen.findByRole('tab', { name: '직접 정의' })
    await waitFor(() => expect(directTab).toHaveAttribute('aria-selected', 'true'))
    expect(screen.getByRole('combobox', { name: 'DRAFT changeset' })).toHaveValue('changeset-2')

    const paths = calls.map(([path]) => path)
    const initiatedIndex = paths.indexOf('/knowledge/graphs/graph-1/source-uploads')
    const partIndex = paths.indexOf('/knowledge/graphs/graph-1/source-uploads/upload-1/parts')
    const completeIndex = paths.indexOf('/knowledge/graphs/graph-1/source-uploads/upload-1/complete')
    const pollIndex = paths.indexOf('/knowledge/graphs/graph-1/source-uploads/upload-1')
    const analyzeIndex = paths.indexOf('/knowledge/graphs/graph-1/sources/upload-1/analyze')
    const projectIndex = paths.indexOf('/knowledge/graphs/graph-1/releases/release-1/project')
    expect(initiatedIndex).toBeGreaterThan(-1)
    expect(partIndex).toBeGreaterThan(initiatedIndex)
    expect(completeIndex).toBeGreaterThan(partIndex)
    expect(pollIndex).toBeGreaterThan(completeIndex)
    expect(analyzeIndex).toBeGreaterThan(pollIndex)
    expect(projectIndex).toBeGreaterThan(analyzeIndex)

    const initiateBody = jsonBody(calls[initiatedIndex]?.[1])
    expect(initiateBody).toMatchObject({
      display_name: 'knowledge-prompt.txt',
      content_type: 'text/plain',
      sha256: '5a18199859c968c2b0b850d46e7ae1fa7ed7330b410b280bc81b2b5eab896ccf',
    })
    expect(initiateBody).not.toHaveProperty('classification')
    expect(initiateBody).not.toHaveProperty('content_profile')
    const completeOptions = calls[completeIndex]?.[1]
    expect(completeOptions?.ifMatch).toBe('"1"')
    expect(jsonBody(completeOptions)).toEqual({
      parts: [{ part_number: 1, etag: 'part-etag-1' }],
    })
    expect(jsonBody(calls[analyzeIndex]?.[1])).toEqual({
      title: 'LLM 입력 텍스트 지식 추출 제안',
    })
    expect(calls[analyzeIndex]?.[1]?.idempotencyKey).toMatch(/^knowledge-source-analysis-/)
    expect(paths.indexOf('/knowledge/graphs/graph-1/source-analysis-jobs/source-job-1'))
      .toBeGreaterThan(analyzeIndex)
    expect(calls[projectIndex]?.[1]?.method).toBe('POST')
  })

  it('resumes an active analysis job and sends versioned idempotent cancellation', async () => {
    const calls: Array<[string, RequestOptions | undefined]> = []
    const request = vi.fn((path: string, options?: RequestOptions) => {
      calls.push([path, options])
      if (path === '/knowledge/graphs') return Promise.resolve([graph])
      if (path === '/knowledge/graphs/graph-1/changesets') return Promise.resolve([])
      if (path === '/knowledge/graphs/graph-1/releases') return Promise.resolve([])
      if (path === '/knowledge/graphs/graph-1/source-analysis-jobs?limit=100') {
        return Promise.resolve({ items: [sourceJob('QUEUED', 7)], next_cursor: null })
      }
      if (path === '/knowledge/graphs/graph-1/source-analysis-jobs/source-job-1') {
        return Promise.resolve(sourceJob('RUNNING', 8, {
          stage: 'PARSED',
          progress: { completed_pages: 2, total_pages: 10 },
        }))
      }
      if (path === '/knowledge/graphs/graph-1/source-analysis-jobs/source-job-1/cancel') {
        return Promise.resolve(sourceJob('CANCELLED', 9))
      }
      throw new Error(`Unexpected request: ${path}`)
    })

    render(<KnowledgeIngestionStudio client={{ request } as unknown as ApiClient} />)
    fireEvent.click(screen.getByRole('button', { name: /MODE B/ }))

    const selectedJob = await screen.findByLabelText('지식 소스 분석 작업')
    await waitFor(() => expect(within(selectedJob).getByText('RUNNING')).toBeInTheDocument())
    expect(screen.getByText('2/10 evidence segments')).toBeInTheDocument()
    fireEvent.change(screen.getByPlaceholderText('감사 로그에 남을 사유'), {
      target: { value: '운영자가 잘못된 소스 선택을 확인함' },
    })
    fireEvent.click(screen.getByRole('button', { name: '작업 취소' }))
    await waitFor(() => expect(within(selectedJob).getByText('CANCELLED')).toBeInTheDocument())

    const cancelCall = calls.find(([path]) => (
      path === '/knowledge/graphs/graph-1/source-analysis-jobs/source-job-1/cancel'
    ))
    expect(cancelCall?.[1]).toMatchObject({
      method: 'POST',
      ifMatch: '"8"',
    })
    expect(cancelCall?.[1]?.idempotencyKey)
      .toMatch(/^knowledge-source-analysis-cancel-/)
    expect(jsonBody(cancelCall?.[1])).toEqual({
      reason: '운영자가 잘못된 소스 선택을 확인함',
    })
  })

  it('renders at most one owner-scoped history page and follows its opaque cursor', async () => {
    const calls: string[] = []
    const active = sourceJob('RUNNING', 4, {
      id: 'active-job',
      title: '실행 중 분석',
    })
    const request = vi.fn((path: string) => {
      calls.push(path)
      if (path === '/knowledge/graphs') return Promise.resolve([graph])
      if (path === '/knowledge/graphs/graph-1/changesets') return Promise.resolve([])
      if (path === '/knowledge/graphs/graph-1/releases') return Promise.resolve([])
      if (path === '/knowledge/graphs/graph-1/source-analysis-jobs?limit=100') {
        return Promise.resolve({
          items: [active, sourceJob('SUCCEEDED', 2, { id: 'recent-job', title: '최근 완료' })],
          next_cursor: 'older/cursor',
        })
      }
      if (
        path
        === '/knowledge/graphs/graph-1/source-analysis-jobs?limit=100&cursor=older%2Fcursor'
      ) {
        return Promise.resolve({
          items: [sourceJob('SUCCEEDED', 2, { id: 'old-job', title: '오래된 완료' })],
          next_cursor: null,
        })
      }
      if (path === '/knowledge/graphs/graph-1/source-analysis-jobs/active-job') {
        return Promise.resolve({ ...active, state: 'CANCELLED', stage: 'COMPLETED' })
      }
      throw new Error(`Unexpected request: ${path}`)
    })

    render(<KnowledgeIngestionStudio client={{ request } as unknown as ApiClient} />)
    fireEvent.click(screen.getByRole('button', { name: /MODE B/ }))

    const history = await screen.findByLabelText('최근 지식 소스 분석 작업')
    expect(within(history).getByText('실행 중 분석')).toBeInTheDocument()
    fireEvent.click(within(history).getByRole('button', { name: '더 오래된 작업' }))
    expect(await within(history).findByText('오래된 완료')).toBeInTheDocument()
    expect(calls).toContain(
      '/knowledge/graphs/graph-1/source-analysis-jobs?limit=100&cursor=older%2Fcursor',
    )
  })

  it('restarts polling for the same nonterminal job after the bounded window expires', async () => {
    vi.useFakeTimers()
    let pollCalls = 0
    const running = sourceJob('RUNNING', 4)
    const request = vi.fn((path: string) => {
      if (path === '/knowledge/graphs') return Promise.resolve([graph])
      if (path === '/knowledge/graphs/graph-1/changesets') return Promise.resolve([])
      if (path === '/knowledge/graphs/graph-1/releases') return Promise.resolve([])
      if (path === '/knowledge/graphs/graph-1/source-analysis-jobs?limit=100') {
        return Promise.resolve({ items: [running], next_cursor: null })
      }
      if (path === '/knowledge/graphs/graph-1/source-analysis-jobs/source-job-1') {
        pollCalls += 1
        return Promise.resolve(running)
      }
      throw new Error(`Unexpected request: ${path}`)
    })

    render(<KnowledgeIngestionStudio client={{ request } as unknown as ApiClient} />)
    fireEvent.click(screen.getByRole('button', { name: /MODE B/ }))
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })
    expect(screen.getByLabelText('지식 소스 분석 작업')).toBeInTheDocument()
    for (let second = 0; second < 121; second += 1) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1_000)
      })
    }

    const resume = screen.getByRole('button', { name: '확인 다시 시작' })
    expect(pollCalls).toBe(120)
    fireEvent.click(resume)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(pollCalls).toBeGreaterThan(120)
  })

  it('pauses resumed-job polling while the browser tab is hidden', async () => {
    const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
    const request = vi.fn((path: string) => {
      if (path === '/knowledge/graphs') return Promise.resolve([graph])
      if (path === '/knowledge/graphs/graph-1/changesets') return Promise.resolve([])
      if (path === '/knowledge/graphs/graph-1/releases') return Promise.resolve([])
      if (path === '/knowledge/graphs/graph-1/source-analysis-jobs?limit=100') {
        return Promise.resolve({ items: [sourceJob('QUEUED', 1)], next_cursor: null })
      }
      if (path === '/knowledge/graphs/graph-1/source-analysis-jobs/source-job-1') {
        return Promise.resolve(sourceJob('SUCCEEDED', 2))
      }
      throw new Error(`Unexpected request: ${path}`)
    })

    render(<KnowledgeIngestionStudio client={{ request } as unknown as ApiClient} />)
    fireEvent.click(screen.getByRole('button', { name: /MODE B/ }))
    const queuedJob = await screen.findByLabelText('지식 소스 분석 작업')
    expect(within(queuedJob).getAllByText('QUEUED')).toHaveLength(2)
    expect(request.mock.calls.some(([path]) => (
      path === '/knowledge/graphs/graph-1/source-analysis-jobs/source-job-1'
    ))).toBe(false)

    visibility.mockReturnValue('visible')
    document.dispatchEvent(new Event('visibilitychange'))
    expect(await screen.findByLabelText('지식 소스 분석 증거')).toBeInTheDocument()
  })

  it('disables governed source ingestion for CONFIDENTIAL graphs', async () => {
    const confidentialGraph = { ...graph, classification: 'CONFIDENTIAL' as const }
    const request = vi.fn((path: string) => {
      if (path === '/knowledge/graphs') return Promise.resolve([confidentialGraph])
      if (path === '/knowledge/graphs/graph-1/changesets') return Promise.resolve([])
      if (path === '/knowledge/graphs/graph-1/releases') return Promise.resolve([])
      if (path === '/knowledge/graphs/graph-1/source-analysis-jobs?limit=100') {
        return Promise.resolve({ items: [], next_cursor: null })
      }
      throw new Error(`Unexpected request: ${path}`)
    })

    render(<KnowledgeIngestionStudio client={{ request } as unknown as ApiClient} />)
    fireEvent.click(screen.getByRole('button', { name: /MODE B/ }))

    expect(await screen.findByText(/PUBLIC\/INTERNAL 소스만 허용/)).toBeInTheDocument()
    expect(screen.getByLabelText('지식 문서 소스')).toBeDisabled()
    expect(screen.getByRole('button', { name: '문서 검증 업로드 시작' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'LLM 추출 제안 생성' })).toBeDisabled()
    expect(request.mock.calls.some(([path]) => path.endsWith('/source-uploads'))).toBe(false)
  })

  it('rejects a source outside the document allowlist before initiating an upload', async () => {
    const request = vi.fn((path: string) => {
      if (path === '/knowledge/graphs') return Promise.resolve([graph])
      if (path === '/knowledge/graphs/graph-1/changesets') return Promise.resolve([])
      if (path === '/knowledge/graphs/graph-1/releases') return Promise.resolve([])
      if (path === '/knowledge/graphs/graph-1/source-analysis-jobs?limit=100') {
        return Promise.resolve({ items: [], next_cursor: null })
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    render(<KnowledgeIngestionStudio client={{ request } as unknown as ApiClient} />)
    fireEvent.click(screen.getByRole('button', { name: /MODE B/ }))
    const input = await screen.findByLabelText('지식 문서 소스')
    await waitFor(() => expect(input).toBeEnabled())
    fireEvent.change(input, {
      target: { files: [new File(['binary'], 'notes.exe', { type: 'application/octet-stream' })] },
    })

    expect(await screen.findByText(/지원 형식은 PDF/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '문서 검증 업로드 시작' })).toBeDisabled()
    expect(request.mock.calls.some(([path]) => path.endsWith('/source-uploads'))).toBe(false)
  })

  it('surfaces object-storage failures and never calls analysis', async () => {
    const request = vi.fn((path: string, options?: RequestOptions) => {
      if (path === '/knowledge/graphs') return Promise.resolve([graph])
      if (path === '/knowledge/graphs/graph-1/changesets') return Promise.resolve([])
      if (path === '/knowledge/graphs/graph-1/releases') return Promise.resolve([])
      if (path === '/knowledge/graphs/graph-1/source-analysis-jobs?limit=100') {
        return Promise.resolve({ items: [], next_cursor: null })
      }
      if (path === '/knowledge/graphs/graph-1/source-uploads' && options?.method === 'POST') {
        return Promise.resolve(uploadRecord('INITIATED', 1))
      }
      if (path === '/knowledge/graphs/graph-1/source-uploads/upload-1/parts') return Promise.resolve({ url: 'https://objects.test/part-1' })
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(null, { status: 503 }))))

    render(<KnowledgeIngestionStudio client={{ request } as unknown as ApiClient} />)
    fireEvent.click(screen.getByRole('button', { name: /MODE B/ }))
    const input = await screen.findByLabelText('지식 문서 소스')
    await waitFor(() => expect(input).toBeEnabled())
    fireEvent.change(input, {
      target: { files: [new File(['%PDF-1.6'], 'semiconductor-outlook.pdf', { type: 'application/pdf' })] },
    })
    fireEvent.click(screen.getByRole('button', { name: '문서 검증 업로드 시작' }))

    expect(await screen.findByText('오브젝트 스토리지 업로드 실패 (503)')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'LLM 추출 제안 생성' })).toBeDisabled()
    expect(request.mock.calls.some(([path]) => path.includes('/analyze'))).toBe(false)
  })
})
