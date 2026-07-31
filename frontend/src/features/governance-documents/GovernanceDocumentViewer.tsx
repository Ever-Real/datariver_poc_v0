import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BookOpen, Download, RefreshCw } from 'lucide-react'
import type { ApiClient } from '../../api/client'
import { ErrorNotice } from '../../components/ErrorNotice'
import { GovernedUnavailable } from '../../components/common/GovernedUnavailable'
import {
  GovernanceDocumentsApi,
  governanceDocumentQueryKey,
} from './governanceDocumentsApi'
import { SafeGovernanceHtml } from './SafeGovernanceHtml'
import type {
  GovernanceDocumentCapability,
  GovernanceDocumentExport,
  GovernanceDocumentSummary,
  GovernanceDocumentVersion,
} from './types'

const VIEWER_LIMIT = 100

export function GovernanceDocumentViewer({
  client,
  onCapability,
}: {
  client: ApiClient
  onCapability?: (value: GovernanceDocumentCapability) => void
}) {
  const api = useMemo(() => new GovernanceDocumentsApi(client), [client])
  const capability = useQuery({
    queryKey: ['governance-documents', 'capability'],
    queryFn: ({ signal }) => api.capability(signal),
    staleTime: 0,
    gcTime: 30_000,
    retry: false,
  })
  const readAvailable = capability.data?.axes.some(
    (axis) => axis.id === 'read' && axis.state === 'AVAILABLE',
  ) ?? false
  const documents = useQuery({
    queryKey: governanceDocumentQueryKey(
      capability.data?.cache_scope ?? 'pending',
      'documents',
      'DOCUMENT',
      'ACTIVE',
      VIEWER_LIMIT,
    ),
    queryFn: ({ signal }) => api.documents(capability.data?.cache_scope ?? '', {
      kind: 'DOCUMENT',
      state: 'ACTIVE',
      limit: VIEWER_LIMIT,
      signal,
    }),
    enabled: readAvailable,
    staleTime: 0,
    gcTime: 30_000,
    retry: false,
  })
  const [selectedDocumentId, setSelectedDocumentId] = useState<string>()
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<unknown>()
  const detail = useQuery({
    queryKey: governanceDocumentQueryKey(
      capability.data?.cache_scope ?? 'pending',
      'document-detail',
      selectedDocumentId,
    ),
    queryFn: ({ signal }) => api.document(
      selectedDocumentId ?? '',
      capability.data?.cache_scope ?? '',
      signal,
    ),
    enabled: readAvailable && Boolean(selectedDocumentId),
    staleTime: 0,
    gcTime: 30_000,
    retry: false,
  })

  useEffect(() => {
    if (capability.data) onCapability?.(capability.data)
  }, [capability.data, onCapability])
  useEffect(() => {
    const items = documents.data?.items ?? []
    setSelectedDocumentId((current) => (
      items.some((item) => item.document_id === current)
        ? current
        : items[0]?.document_id
    ))
  }, [documents.data?.items])

  if (capability.isPending) {
    return <p className="governance-documents-loading" role="status">문서 조회 권한을 확인하는 중입니다.</p>
  }
  if (capability.error) {
    return <>
      <ErrorNotice error={capability.error} />
      <GovernedUnavailable
        title="문서 조회 권한을 확인할 수 없습니다"
        description="서버 capability가 검증되기 전에는 거버넌스 문서를 요청하지 않습니다."
      />
    </>
  }
  if (!capability.data || !readAvailable) {
    return <GovernedUnavailable
      title="문서 조회가 허용되지 않았습니다"
      description="현재 Workspace에서 게시된 거버넌스 문서를 읽을 권한이 없습니다."
    />
  }

  const currentDetail = detail.data?.data.item
  const publishedVersion = currentDetail
    ? published(currentDetail.document.current_published_version_id, currentDetail.versions)
    : undefined

  const exportDocument = async () => {
    if (!currentDetail || !publishedVersion) return
    setExporting(true)
    setExportError(undefined)
    try {
      const value = await api.exportDocument(
        currentDetail.document.document_id,
        capability.data.cache_scope,
        publishedVersion.version_id,
      )
      downloadExport(value)
    } catch (error) {
      setExportError(error)
    } finally {
      setExporting(false)
    }
  }

  return <section className="governance-document-viewer">
    <header className="governance-documents-header">
      <div>
        <span className="eyebrow">Approved governance documents</span>
        <h2>문서 조회</h2>
        <p>결재가 완료된 ACTIVE 문서의 현재 게시 버전과 승인 메타데이터만 표시합니다.</p>
      </div>
      <button
        type="button"
        className="button button-secondary"
        disabled={documents.isFetching}
        onClick={() => void documents.refetch()}
      >
        <RefreshCw size={13} /> 새로고침
      </button>
    </header>
    {documents.error && <ErrorNotice error={documents.error} />}
    {detail.error && <ErrorNotice error={detail.error} />}
    {Boolean(exportError) && <ErrorNotice error={exportError} />}
    <div className="policy-governance-workspace" aria-busy={documents.isFetching || detail.isFetching}>
      <aside className="policy-document-tree panel" aria-label="게시된 거버넌스 문서">
        <header>
          <BookOpen size={16} />
          <div><span className="eyebrow">Published library</span><h2>가이드라인 목록</h2></div>
        </header>
        <nav>
          {(documents.data?.items ?? []).map((item) => <DocumentNavigationItem
            key={item.document_id}
            item={item}
            active={item.document_id === selectedDocumentId}
            onSelect={setSelectedDocumentId}
          />)}
        </nav>
        {!documents.isPending && documents.data?.items.length === 0 && <p className="policy-document-tree-empty">
          승인·게시된 문서가 없습니다. 문서 관리에서 작성·결재를 완료하면 여기에 표시됩니다.
        </p>}
        <footer>문서 관리에서 승인·게시된 현재 버전을 서버에서 직접 조회합니다.</footer>
      </aside>
      <main className="policy-document-main panel">
        {detail.isPending && selectedDocumentId && <p role="status">게시 문서를 불러오는 중입니다.</p>}
        {!selectedDocumentId && <div className="policy-empty"><p>표시할 ACTIVE 문서가 없습니다.</p></div>}
        {currentDetail && publishedVersion && <article className="policy-document-view">
          <header className="governance-viewer-title">
            <div>
              <span className="eyebrow">{categoryLabel(currentDetail.document.category)}</span>
              <h1>{publishedVersion.title}</h1>
              <p>{publishedVersion.summary}</p>
            </div>
            <button
              type="button"
              className="button button-secondary"
              disabled={exporting}
              onClick={() => void exportDocument()}
            >
              <Download size={13} /> {exporting ? '내보내는 중' : '내용·메타데이터 내보내기'}
            </button>
          </header>
          <dl className="governance-document-meta governance-viewer-meta">
            <div><dt>문서 생성일</dt><dd>{dateTime(currentDetail.document.created_at)}</dd></div>
            <div><dt>수정일</dt><dd>{dateTime(currentDetail.document.updated_at)}</dd></div>
            <div><dt>초기 등록자</dt><dd>{shortId(currentDetail.document.owner_subject_id)}</dd></div>
            <div><dt>현재 버전</dt><dd>{publishedVersion.version_tag}</dd></div>
            <div><dt>버전 작성자</dt><dd>{shortId(publishedVersion.author_id)}</dd></div>
            <div><dt>승인자</dt><dd>{publishedVersion.reviewed_by ? shortId(publishedVersion.reviewed_by) : '—'}</dd></div>
            <div><dt>결재 상태</dt><dd><span className="badge">ACTIVE</span></dd></div>
            <div><dt>게시일</dt><dd>{publishedVersion.published_at ? dateTime(publishedVersion.published_at) : '—'}</dd></div>
            <div><dt>상위 문서</dt><dd>{currentDetail.parent_document?.title ?? '—'}</dd></div>
            <div><dt>하위 문서</dt><dd>{currentDetail.child_documents.map((item) => item.title).join(', ') || '—'}</dd></div>
          </dl>
          <SafeGovernanceHtml
            html={publishedVersion.sanitized_html}
            contentHash={publishedVersion.content_sha256}
            sanitizerPolicyVersion={`${publishedVersion.sanitizer_policy_version}:${publishedVersion.sanitizer_policy_sha256}`}
          />
        </article>}
      </main>
    </div>
  </section>
}

function DocumentNavigationItem({
  item,
  active,
  onSelect,
}: {
  item: GovernanceDocumentSummary
  active: boolean
  onSelect: (documentId: string) => void
}) {
  return <button
    type="button"
    className={active ? 'active' : ''}
    onClick={() => onSelect(item.document_id)}
  >
    <span><BookOpen size={15} /></span>
    <div><strong>{item.title}</strong><small>{item.summary || categoryLabel(item.category)}</small></div>
  </button>
}

function published(
  versionId: string | null,
  versions: GovernanceDocumentVersion[],
): GovernanceDocumentVersion | undefined {
  return versions.find((version) => version.version_id === versionId && version.state === 'PUBLISHED')
}

function downloadExport(value: GovernanceDocumentExport) {
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `governance_${safeFilename(value.document.title)}_${value.selected_version.version_tag}.json`
  anchor.click()
  URL.revokeObjectURL(url)
}

function safeFilename(value: string) {
  return value.normalize('NFKC').replace(/[^\p{L}\p{N}_-]+/gu, '_').replace(/^_+|_+$/g, '') || 'document'
}

function categoryLabel(value: GovernanceDocumentSummary['category']) {
  return {
    POLICY: '정책',
    STANDARD_TERMINOLOGY: '표준어 사전',
    SECURITY_GUIDE: '보안 가이드',
    OTHER: '기타',
  }[value]
}

function dateTime(value: string) {
  return new Intl.DateTimeFormat('ko-KR', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

function shortId(value: string) {
  return value.length > 12 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value
}
