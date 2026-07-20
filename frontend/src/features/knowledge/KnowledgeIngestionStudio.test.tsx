import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiClient, RequestOptions } from '../../api/client'
import type { KnowledgeGraph, UploadRecord } from '../../api/types'
import { KnowledgeIngestionStudio } from './KnowledgeIngestionStudio'
import { validateKnowledgePdf } from './KnowledgeSourceUpload'

vi.mock('hash-wasm', () => ({
  createSHA256: vi.fn(() => Promise.resolve({
    init: vi.fn(),
    update: vi.fn(),
    digest: vi.fn(() => 'a'.repeat(64)),
  })),
}))

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
  classification: 'CONFIDENTIAL',
  active_release_id: 'release-1',
  version: 3,
}

function uploadRecord(state: string, version: number, lastErrorCode: string | null = null): UploadRecord {
  return {
    id: 'upload-1',
    display_name: 'semiconductor-outlook.pdf',
    state,
    size_bytes: 24,
    content_type: 'application/pdf',
    sha256: 'a'.repeat(64),
    classification: 'CONFIDENTIAL',
    content_profile: 'FORMAT_ONLY_V1',
    expires_at: '2026-07-22T00:00:00Z',
    version,
    recommended_part_size_bytes: 16 * 1024 * 1024,
    validation_summary: state === 'ACCEPTED' ? { media_type: 'application/pdf' } : {},
    last_error_code: lastErrorCode,
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('KnowledgeIngestionStudio', () => {
  it('enforces the 50 MiB PDF source boundary before hashing', () => {
    expect(() => validateKnowledgePdf({
      name: 'oversized.pdf',
      type: 'application/pdf',
      size: 50 * 1024 * 1024 + 1,
    })).toThrow('최대 50 MiB')
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

  it('runs the governed PDF upload, analysis, and verified projection request sequence', async () => {
    const calls: Array<[string, RequestOptions | undefined]> = []
    const request = vi.fn((path: string, options?: RequestOptions) => {
      calls.push([path, options])
      if (path === '/knowledge/graphs') return Promise.resolve([graph])
      if (path === '/knowledge/graphs/graph-1/changesets') return Promise.resolve([])
      if (path === '/knowledge/graphs/graph-1/releases') return Promise.resolve([{
        id: 'release-1', graph_id: 'graph-1', release_no: 2, ontology_version_id: 'ontology-1',
        content_hash: 'b'.repeat(64), node_count: 12, edge_count: 7,
        published_at: '2026-07-21T01:00:00Z',
      }])
      if (path === '/uploads' && options?.method === 'POST') {
        return Promise.resolve(uploadRecord('INITIATED', 1))
      }
      if (path === '/uploads/upload-1/parts') return Promise.resolve({ url: 'https://objects.test/part-1' })
      if (path === '/uploads/upload-1/complete') {
        return Promise.resolve(uploadRecord('VALIDATION_QUEUED', 2))
      }
      if (path === '/uploads/upload-1' && !options?.method) {
        return Promise.resolve(uploadRecord('ACCEPTED', 3))
      }
      if (path === '/knowledge/graphs/graph-1/sources/upload-1/analyze') {
        return Promise.resolve({
          source_snapshot_id: 'snapshot-1', changeset_id: 'changeset-2', page_count: 105,
          proposed_node_count: 32, proposed_edge_count: 19, evidence_hash: 'c'.repeat(64),
          embedding_model: 'bge-m3:latest', extraction_model: 'datariver-gemma4-dev:0.1',
        })
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
    const input = await screen.findByLabelText('지식 PDF 소스')
    await waitFor(() => expect(input).toBeEnabled())
    const file = new File(['%PDF-1.6\nverified-content'], 'semiconductor-outlook.pdf', {
      type: 'application/pdf',
    })
    fireEvent.change(input, { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: 'PDF 검증 업로드 시작' }))

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

    const paths = calls.map(([path]) => path)
    const initiatedIndex = paths.indexOf('/uploads')
    const partIndex = paths.indexOf('/uploads/upload-1/parts')
    const completeIndex = paths.indexOf('/uploads/upload-1/complete')
    const pollIndex = paths.indexOf('/uploads/upload-1')
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
      content_type: 'application/pdf',
      content_profile: 'FORMAT_ONLY_V1',
      classification: 'CONFIDENTIAL',
      sha256: 'a'.repeat(64),
    })
    const completeOptions = calls[completeIndex]?.[1]
    expect(completeOptions?.ifMatch).toBe('"1"')
    expect(jsonBody(completeOptions)).toEqual({
      parts: [{ part_number: 1, etag: 'part-etag-1' }],
    })
    expect(jsonBody(calls[analyzeIndex]?.[1])).toEqual({
      title: 'semiconductor-outlook.pdf 지식 추출 제안',
    })
    expect(calls[projectIndex]?.[1]?.method).toBe('POST')
  })

  it('rejects a non-PDF source before initiating a governed upload', async () => {
    const request = vi.fn((path: string) => {
      if (path === '/knowledge/graphs') return Promise.resolve([graph])
      if (path === '/knowledge/graphs/graph-1/changesets') return Promise.resolve([])
      if (path === '/knowledge/graphs/graph-1/releases') return Promise.resolve([])
      throw new Error(`Unexpected request: ${path}`)
    })
    render(<KnowledgeIngestionStudio client={{ request } as unknown as ApiClient} />)
    fireEvent.click(screen.getByRole('button', { name: /MODE B/ }))
    const input = await screen.findByLabelText('지식 PDF 소스')
    await waitFor(() => expect(input).toBeEnabled())
    fireEvent.change(input, {
      target: { files: [new File(['not a pdf'], 'notes.txt', { type: 'text/plain' })] },
    })

    expect(await screen.findByText(/application\/pdf 형식의 \.pdf 파일만/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'PDF 검증 업로드 시작' })).toBeDisabled()
    expect(request.mock.calls.some(([path]) => path === '/uploads')).toBe(false)
  })

  it('surfaces object-storage failures and never calls analysis', async () => {
    const request = vi.fn((path: string, options?: RequestOptions) => {
      if (path === '/knowledge/graphs') return Promise.resolve([graph])
      if (path === '/knowledge/graphs/graph-1/changesets') return Promise.resolve([])
      if (path === '/knowledge/graphs/graph-1/releases') return Promise.resolve([])
      if (path === '/uploads' && options?.method === 'POST') {
        return Promise.resolve(uploadRecord('INITIATED', 1))
      }
      if (path === '/uploads/upload-1/parts') return Promise.resolve({ url: 'https://objects.test/part-1' })
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(null, { status: 503 }))))

    render(<KnowledgeIngestionStudio client={{ request } as unknown as ApiClient} />)
    fireEvent.click(screen.getByRole('button', { name: /MODE B/ }))
    const input = await screen.findByLabelText('지식 PDF 소스')
    await waitFor(() => expect(input).toBeEnabled())
    fireEvent.change(input, {
      target: { files: [new File(['%PDF-1.6'], 'semiconductor-outlook.pdf', { type: 'application/pdf' })] },
    })
    fireEvent.click(screen.getByRole('button', { name: 'PDF 검증 업로드 시작' }))

    expect(await screen.findByText('오브젝트 스토리지 업로드 실패 (503)')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'LLM 추출 제안 생성' })).toBeDisabled()
    expect(request.mock.calls.some(([path]) => path.includes('/analyze'))).toBe(false)
  })
})
