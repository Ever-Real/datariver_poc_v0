import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient } from '../../api/client'
import { PolicyGovernancePage } from './PolicyGovernancePage'

describe('PolicyGovernancePage', () => {
  it('shows document viewing without duplicate role policy or document management', async () => {
    const request = vi.fn((path: string) => {
      if (path === '/governance/documents/capability') {
        return Promise.resolve(capability(false))
      }
      if (path === '/governance/documents?limit=100&kind=DOCUMENT&state=ACTIVE') {
        return Promise.resolve(documentList())
      }
      throw new Error(`unexpected request: ${path}`)
    })

    renderPage(request)

    expect(await screen.findByRole('tab', { name: '문서 조회' })).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: '역할별 권한 정책' })).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: '문서 관리' })).not.toBeInTheDocument()
    expect(await screen.findByText(/승인·게시된 문서가 없습니다/)).toBeInTheDocument()
  })

  it('renames both tabs and opens the separately authorized management workspace', async () => {
    const request = vi.fn((path: string) => {
      if (path === '/governance/documents/capability') {
        return Promise.resolve(capability(true))
      }
      if (path === '/governance/documents?limit=100&kind=DOCUMENT&state=ACTIVE') {
        return Promise.resolve(documentList())
      }
      if (path === '/governance/documents?limit=25&kind=DOCUMENT') {
        return Promise.resolve({ ...documentList(), page: { next_cursor: null, limit: 25 } })
      }
      throw new Error(`unexpected request: ${path}`)
    })

    renderPage(request)

    const management = await screen.findByRole('tab', { name: '문서 관리' })
    expect(screen.getByRole('tab', { name: '문서 조회' })).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: '정책 현황' })).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: '문서 라이브러리' })).not.toBeInTheDocument()
    fireEvent.click(management)

    expect(await screen.findByRole('heading', { name: '문서 관리' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '문서 작성' })).toBeInTheDocument()
  })

  it('renders the current published body and metadata from the managed document API', async () => {
    const request = vi.fn((path: string) => {
      if (path === '/governance/documents/capability') {
        return Promise.resolve(capability(false))
      }
      if (path === '/governance/documents?limit=100&kind=DOCUMENT&state=ACTIVE') {
        return Promise.resolve(documentList([documentSummary]))
      }
      throw new Error(`unexpected request: ${path}`)
    })
    const requestWithMeta = vi.fn((path: string) => {
      if (path === '/governance/documents/document-one') {
        return Promise.resolve({
          data: {
            item: {
              document: documentSummary,
              versions: [publishedVersion],
              reviews: [],
              attachments: [{
                attachment_id: 'attachment-one',
                workspace_id: 'workspace-one',
                document_id: 'document-one',
                document_version_id: 'version-one',
                serial_number: 1,
                storage_filename: null,
                original_name: '분류 기준.pdf',
                content_type: 'application/pdf',
                size_bytes: 128,
                content_sha256: 'f'.repeat(64),
                uploaded_by: 'author-one',
                created_at: now,
              }],
              parent_document: null,
              child_documents: [],
              subject_display_names: {
                'author-one': '문서 담당자',
                'reviewer-one': '문서 승인자',
              },
            },
            cache_scope: cacheScope,
            observed_at: now,
            authorization_valid_until: validUntil,
          },
          etag: '"3"',
        })
      }
      throw new Error(`unexpected metadata request: ${path}`)
    })

    renderPage(request, requestWithMeta)

    expect(await screen.findByRole('heading', { name: '데이터 분류·접근 정책' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '승인 본문' })).toBeInTheDocument()
    expect(screen.getByText('v1')).toBeInTheDocument()
    const metadata = screen.getByLabelText('게시 문서 정보')
    expect(Array.from(metadata.querySelectorAll('dt'), (term) => term.textContent)).toEqual([
      '문서 생성일', '게시일', '현재 버전', '작성자', '첨부파일',
    ])
    expect(metadata).toHaveTextContent('문서 담당자')
    expect(metadata.querySelector('.governance-viewer-attachments')).toHaveTextContent('분류 기준.pdf')
    expect(screen.getByText('ACTIVE')).toBeInTheDocument()
    expect(screen.getAllByText('문서 담당자')).not.toHaveLength(0)
    expect(screen.getByText('문서 승인자')).toBeInTheDocument()
  })
})

function renderPage(
  request: (path: string) => Promise<unknown>,
  requestWithMeta: (path: string) => Promise<unknown> = vi.fn(),
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const client = {
    request: request as unknown as ApiClient['request'],
    requestWithMeta: requestWithMeta as unknown as ApiClient['requestWithMeta'],
  } as unknown as ApiClient
  return render(
    <QueryClientProvider client={queryClient}>
      <PolicyGovernancePage client={client} />
    </QueryClientProvider>,
  )
}

function capability(management: boolean) {
  return {
    contract_version: 'GOVERNANCE_DOCUMENT_CAPABILITY_V1',
    observed_at: new Date(Date.now() - 1_000).toISOString(),
    valid_until: new Date(Date.now() + 30_000).toISOString(),
    cache_scope: cacheScope,
    axes: [
      'read',
      'create',
      'edit',
      'review',
      'publish',
      'archive',
      'template_manage',
      'artifact_storage',
      'knowledge_projection',
    ].map((id) => ({
      id,
      state: id === 'read' || management ? 'AVAILABLE' : 'DENIED',
      reason_code: id === 'read' || management ? null : 'PERMISSION_DENIED',
    })),
    limits: {
      max_html_bytes: 1_000_000,
      max_attachment_bytes: 10_000_000,
      max_attachments_per_version: 25,
    },
  }
}

function documentList(items: unknown[] = []) {
  return {
    items,
    page: { next_cursor: null, limit: 100 },
    cache_scope: cacheScope,
    observed_at: new Date(Date.now() - 1_000).toISOString(),
    authorization_valid_until: new Date(Date.now() + 30_000).toISOString(),
  }
}

const cacheScope = 'a'.repeat(64)
const now = '2026-07-31T00:00:00Z'
const validUntil = '2099-07-31T00:00:30Z'
const documentSummary = {
  document_id: 'document-one',
  workspace_id: 'workspace-one',
  kind: 'DOCUMENT',
  category: 'POLICY',
  title: '데이터 분류·접근 정책',
  summary: '승인된 관리 문서',
  classification: 1,
  state: 'ACTIVE',
  owner_subject_id: 'author-one',
  current_published_version_id: 'version-one',
  current_version_number: 1,
  created_at: now,
  updated_at: now,
  version: 3,
  allowed_actions: ['read'],
}
const publishedVersion = {
  version_id: 'version-one',
  workspace_id: 'workspace-one',
  document_id: 'document-one',
  version_number: 1,
  version_tag: 'v1',
  state: 'PUBLISHED',
  title: '데이터 분류·접근 정책',
  summary: '승인된 관리 문서',
  applicability_scope: '전사',
  sanitized_html: '<h2>승인 본문</h2><p>분류 기준을 적용합니다.</p>',
  plain_text: '승인 본문 분류 기준을 적용합니다.',
  content_sha256: 'b'.repeat(64),
  size_bytes: 42,
  sanitizer_policy_version: 'GOVERNANCE_HTML_SANITIZER_V1',
  sanitizer_policy_sha256: 'c'.repeat(64),
  source_format: 'HTML',
  source_template_version_id: null,
  parent_document_id: null,
  author_id: 'author-one',
  submitted_at: now,
  reviewed_by: 'reviewer-one',
  reviewed_at: now,
  published_at: now,
  artifact_state: 'STORED',
  knowledge_state: 'READY',
  created_at: now,
  version: 1,
}
