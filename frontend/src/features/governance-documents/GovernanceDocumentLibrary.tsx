import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { ApiError, newIdempotencyKey, type ApiClient } from '../../api/client'
import {
  AssuranceNotice,
  type AssuranceActions,
} from '../../components/AssuranceNotice'
import { ErrorNotice } from '../../components/ErrorNotice'
import { CursorPagination } from '../../components/common/CursorPagination'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import { Dialog } from '../../components/common/Dialog'
import { GovernedUnavailable } from '../../components/common/GovernedUnavailable'
import { GovernanceHtmlEditor } from './GovernanceHtmlEditor'
import { governanceMarkupFromFile } from './governanceDocumentMarkup'
import {
  GovernanceDocumentsApi,
  governanceDocumentQueryKey,
} from './governanceDocumentsApi'
import { SafeGovernanceHtml } from './SafeGovernanceHtml'
import type {
  GovernanceDocumentAction,
  GovernanceDocumentAttachment,
  GovernanceDocumentBlueprint,
  GovernanceDocumentCapability,
  GovernanceDocumentCapabilityAxis,
  GovernanceDocumentCategory,
  GovernanceDocumentCommandResponse,
  GovernanceDocumentDetail,
  GovernanceDocumentKind,
  GovernanceDocumentState,
  GovernanceDocumentSummary,
  GovernanceDocumentVersion,
} from './types'
import './governanceDocuments.css'

type EditorMode = 'CREATE' | 'CREATE_VERSION'
type ReviewDecision = 'APPROVE' | 'REJECT'

const PAGE_SIZE = 25
const CATEGORIES: Array<{ value: GovernanceDocumentCategory; label: string }> = [
  { value: 'POLICY', label: '정책' },
  { value: 'STANDARD_TERMINOLOGY', label: '표준어 사전' },
  { value: 'SECURITY_GUIDE', label: '보안 가이드' },
  { value: 'OTHER', label: '기타' },
]

export function GovernanceDocumentLibrary({
  client,
  assurance,
}: {
  client: ApiClient
  assurance?: AssuranceActions
}) {
  const api = useMemo(() => new GovernanceDocumentsApi(client), [client])
  const capability = useQuery({
    queryKey: ['governance-documents', 'capability'],
    queryFn: ({ signal }) => api.capability(signal),
    staleTime: 0,
    gcTime: 30_000,
    retry: false,
  })
  const [leaseExpired, setLeaseExpired] = useState(false)

  useEffect(() => {
    setLeaseExpired(false)
    if (!capability.data) return
    const delay = Date.parse(capability.data.valid_until) - Date.now()
    if (delay <= 0) {
      setLeaseExpired(true)
      return
    }
    const timer = window.setTimeout(() => setLeaseExpired(true), delay)
    return () => window.clearTimeout(timer)
  }, [capability.data])

  if (capability.isPending) {
    return <p className="governance-documents-loading" role="status">문서 접근 권한을 확인하는 중입니다.</p>
  }
  if (capability.error) {
    return <>
      <ErrorNotice error={capability.error} />
      <GovernedUnavailable
        title="문서 접근 권한을 확인할 수 없습니다"
        description="서버 capability가 검증되기 전에는 거버넌스 문서를 요청하지 않습니다."
      />
    </>
  }
  const readAxis = capability.data?.axes.find((axis) => axis.id === 'read')
  if (!capability.data || leaseExpired || readAxis?.state !== 'AVAILABLE') {
    return <GovernedUnavailable
      title={leaseExpired ? '문서 접근 권한이 만료되었습니다' : '문서 열람이 허용되지 않았습니다'}
      description={leaseExpired
        ? '권한을 새로고침한 뒤 문서 목록을 다시 요청하세요.'
        : capabilityReason(readAxis)}
    />
  }
  return <GovernanceDocumentWorkspace
    api={api}
    capability={capability.data}
    assurance={assurance}
    onRefreshCapability={() => void capability.refetch()}
  />
}

function GovernanceDocumentWorkspace({
  api,
  capability,
  assurance,
  onRefreshCapability,
}: {
  api: GovernanceDocumentsApi
  capability: GovernanceDocumentCapability
  assurance?: AssuranceActions
  onRefreshCapability: () => void
}) {
  const queryClient = useQueryClient()
  const [cursorStack, setCursorStack] = useState<Array<string | undefined>>([undefined])
  const [pageIndex, setPageIndex] = useState(0)
  const [queryInput, setQueryInput] = useState('')
  const [query, setQuery] = useState('')
  const [kind, setKind] = useState<GovernanceDocumentKind>('DOCUMENT')
  const [includeArchived, setIncludeArchived] = useState(false)
  const [selectedDocumentId, setSelectedDocumentId] = useState<string>()
  const [selectedVersionId, setSelectedVersionId] = useState<string>()
  const [editorMode, setEditorMode] = useState<EditorMode>()
  const [editorKind, setEditorKind] = useState<GovernanceDocumentKind>('DOCUMENT')
  const [title, setTitle] = useState('')
  const [summary, setSummary] = useState('')
  const [editorCategory, setEditorCategory] = useState<GovernanceDocumentCategory>('POLICY')
  const [classification, setClassification] = useState(1)
  const [applicabilityScope, setApplicabilityScope] = useState('')
  const [parentDocumentId, setParentDocumentId] = useState('')
  const [templateVersionId, setTemplateVersionId] = useState('')
  const [blueprintId, setBlueprintId] = useState('')
  const [editorInitialHtml, setEditorInitialHtml] = useState('<p></p>')
  const [editorContentRevision, setEditorContentRevision] = useState(0)
  const [importFile, setImportFile] = useState<File>()
  const [editorAttachmentFile, setEditorAttachmentFile] = useState<File>()
  const [reviewDecision, setReviewDecision] = useState<ReviewDecision>()
  const [reviewReason, setReviewReason] = useState('')
  const [archiveOpen, setArchiveOpen] = useState(false)
  const [archiveReason, setArchiveReason] = useState('')
  const [attachmentFile, setAttachmentFile] = useState<File>()
  const [knowledgeQuery, setKnowledgeQuery] = useState('')
  const [knowledgeSearch, setKnowledgeSearch] = useState('')
  const [busy, setBusy] = useState(false)
  const [mutationError, setMutationError] = useState<unknown>()
  const [notice, setNotice] = useState<string>()
  const editorHtml = useRef('')
  const cursor = cursorStack[pageIndex]
  const axis = useCallback((id: GovernanceDocumentCapabilityAxis['id']) => (
    capability.axes.find((candidate) => candidate.id === id)
  ), [capability.axes])

  useEffect(() => {
    setCursorStack([undefined])
    setPageIndex(0)
    setSelectedDocumentId(undefined)
    setSelectedVersionId(undefined)
  }, [includeArchived, kind, query])

  const documents = useQuery({
    queryKey: governanceDocumentQueryKey(
      capability.cache_scope,
      'documents',
      kind,
      query,
      includeArchived,
      cursor,
      PAGE_SIZE,
    ),
    queryFn: ({ signal }) => api.documents(capability.cache_scope, {
      cursor,
      query,
      kind,
      includeArchived,
      limit: PAGE_SIZE,
      signal,
    }),
    staleTime: 0,
    gcTime: 30_000,
    retry: false,
  })
  const detail = useQuery({
    queryKey: governanceDocumentQueryKey(
      capability.cache_scope,
      'document-detail',
      selectedDocumentId,
    ),
    queryFn: ({ signal }) => api.document(
      selectedDocumentId ?? '',
      capability.cache_scope,
      signal,
    ),
    enabled: Boolean(selectedDocumentId),
    staleTime: 0,
    gcTime: 30_000,
    retry: false,
  })
  const templates = useQuery({
    queryKey: governanceDocumentQueryKey(
      capability.cache_scope,
      'templates',
      PAGE_SIZE,
    ),
    queryFn: ({ signal }) => api.documents(capability.cache_scope, {
      kind: 'TEMPLATE',
      limit: PAGE_SIZE,
      signal,
    }),
    enabled: Boolean(editorMode === 'CREATE' && editorKind === 'DOCUMENT'),
    staleTime: 0,
    gcTime: 30_000,
    retry: false,
  })
  const parentCandidates = useQuery({
    queryKey: governanceDocumentQueryKey(
      capability.cache_scope,
      'documents',
      'parent-candidates',
      100,
    ),
    queryFn: ({ signal }) => api.documents(capability.cache_scope, {
      kind: 'DOCUMENT',
      limit: 100,
      signal,
    }),
    enabled: Boolean(editorMode && editorKind === 'DOCUMENT'),
    staleTime: 0,
    gcTime: 30_000,
    retry: false,
  })
  const blueprints = useQuery({
    queryKey: governanceDocumentQueryKey(
      capability.cache_scope,
      'template-blueprints',
    ),
    queryFn: ({ signal }) => api.templateBlueprints(signal),
    enabled: Boolean(editorMode === 'CREATE'),
    staleTime: 5 * 60_000,
    gcTime: 5 * 60_000,
    retry: false,
  })
  const knowledge = useQuery({
    queryKey: governanceDocumentQueryKey(
      capability.cache_scope,
      'knowledge-evidence',
      knowledgeSearch,
    ),
    queryFn: ({ signal }) => api.knowledgeEvidence(
      capability.cache_scope,
      knowledgeSearch,
      signal,
    ),
    enabled: knowledgeSearch.length >= 2
      && axis('knowledge_projection')?.state === 'AVAILABLE',
    staleTime: 30_000,
    gcTime: 30_000,
    retry: false,
  })

  const currentDetail = detail.data?.data.item
  const selectedVersion = currentDetail?.versions.find((version) => (
    version.version_id === selectedVersionId
  ))
  const allowed = useCallback((action: GovernanceDocumentAction) => (
    currentDetail?.document.allowed_actions.includes(action) ?? false
  ), [currentDetail])

  useEffect(() => {
    if (!currentDetail) return
    setSelectedVersionId((current) => {
      if (currentDetail.versions.some((version) => version.version_id === current)) return current
      return currentDetail.document.current_published_version_id
        ?? currentDetail.versions[0]?.version_id
    })
  }, [currentDetail])
  useEffect(() => {
    setSelectedVersionId(undefined)
    setMutationError(undefined)
    setNotice(undefined)
    setAttachmentFile(undefined)
  }, [selectedDocumentId])

  const invalidateDocument = async (documentId?: string) => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: governanceDocumentQueryKey(capability.cache_scope, 'documents'),
      }),
      queryClient.invalidateQueries({
        queryKey: governanceDocumentQueryKey(capability.cache_scope, 'templates'),
      }),
      ...(documentId ? [queryClient.invalidateQueries({
        queryKey: governanceDocumentQueryKey(
          capability.cache_scope,
          'document-detail',
          documentId,
        ),
      })] : []),
    ])
  }
  const execute = async (
    operation: () => Promise<GovernanceDocumentCommandResponse | GovernanceDocumentAttachment>,
    success: string,
  ) => {
    setBusy(true)
    setMutationError(undefined)
    setNotice(undefined)
    try {
      const result = await operation()
      const documentId = 'item' in result
        ? result.item.document.document_id
        : result.document_id
      await invalidateDocument(documentId)
      setNotice(success)
      return result
    } catch (error) {
      setMutationError(error)
      if (error instanceof ApiError && error.problem.status === 409 && selectedDocumentId) {
        await queryClient.invalidateQueries({
          queryKey: governanceDocumentQueryKey(
            capability.cache_scope,
            'document-detail',
            selectedDocumentId,
          ),
        })
      }
      return undefined
    } finally {
      setBusy(false)
    }
  }
  const openCreate = (nextKind: GovernanceDocumentKind, template?: GovernanceDocumentSummary) => {
    setEditorKind(nextKind)
    setTitle('')
    setSummary('')
    setEditorCategory(template?.category ?? 'POLICY')
    setClassification(template?.classification ?? 1)
    setApplicabilityScope('')
    setParentDocumentId('')
    setTemplateVersionId(template?.current_published_version_id ?? '')
    setBlueprintId('')
    setImportFile(undefined)
    setEditorAttachmentFile(undefined)
    editorHtml.current = '<p></p>'
    setEditorInitialHtml('<p></p>')
    setEditorContentRevision((current) => current + 1)
    setMutationError(undefined)
    setEditorMode('CREATE')
  }
  const openNewVersion = () => {
    if (!selectedVersion) return
    setTitle(selectedVersion.title)
    setSummary(selectedVersion.summary)
    setApplicabilityScope(selectedVersion.applicability_scope)
    setParentDocumentId(selectedVersion.parent_document_id ?? '')
    setBlueprintId('')
    setImportFile(undefined)
    setEditorAttachmentFile(undefined)
    editorHtml.current = selectedVersion.sanitized_html
    setEditorInitialHtml(selectedVersion.sanitized_html)
    setEditorContentRevision((current) => current + 1)
    setMutationError(undefined)
    setEditorMode('CREATE_VERSION')
  }
  const applyBlueprint = (nextBlueprintId: string) => {
    setBlueprintId(nextBlueprintId)
    const blueprint = blueprints.data?.items.find(
      (candidate) => candidate.blueprint_id === nextBlueprintId,
    )
    if (!blueprint) {
      editorHtml.current = '<p></p>'
      setEditorInitialHtml('<p></p>')
      setEditorContentRevision((current) => current + 1)
      return
    }
    setTitle(blueprint.title)
    setSummary(blueprint.summary)
    setEditorCategory(blueprint.category)
    setApplicabilityScope(blueprint.applicability_scope)
    setTemplateVersionId('')
    setParentDocumentId('')
    editorHtml.current = blueprint.sanitized_html
    setEditorInitialHtml(blueprint.sanitized_html)
    setEditorContentRevision((current) => current + 1)
  }
  const saveEditor = async () => {
    if (editorMode === 'CREATE') {
      const canCreate = editorKind === 'TEMPLATE'
        ? axis('template_manage')?.state === 'AVAILABLE'
        : axis('create')?.state === 'AVAILABLE'
      if (!title.trim() || !canCreate) return
      const saved = await execute(
        () => importFile
          ? api.importDocument({
            file: importFile,
            kind: editorKind,
            category: editorCategory,
            title: title.trim(),
            summary: summary.trim(),
            classification,
            applicabilityScope: applicabilityScope.trim(),
            parentDocumentId: editorKind === 'DOCUMENT' ? parentDocumentId || null : null,
          }, newIdempotencyKey('governance-document-import'))
          : api.createDocument({
            kind: editorKind,
            category: editorCategory,
            title: title.trim(),
            summary: summary.trim(),
            classification,
            applicability_scope: applicabilityScope.trim(),
            sanitized_html: templateVersionId ? null : editorHtml.current,
            source_template_version_id: templateVersionId || null,
            parent_document_id: editorKind === 'DOCUMENT' ? parentDocumentId || null : null,
          }, newIdempotencyKey('governance-document-create')),
        editorKind === 'TEMPLATE'
          ? '거버넌스 문서 Template을 생성했습니다.'
          : '거버넌스 문서를 생성했습니다.',
      )
      if (saved && 'item' in saved) {
        const draft = saved.item.versions.find((version) => version.state === 'DRAFT')
        setSelectedDocumentId(saved.item.document.document_id)
        if (editorAttachmentFile && draft) {
          await execute(
            () => api.uploadAttachment(
              saved.item.document.document_id,
              draft.version_id,
              saved.item.document.version,
              editorAttachmentFile,
              newIdempotencyKey('governance-document-attachment'),
            ),
            '문서와 별첨을 각각 불변 Object로 저장했습니다.',
          )
        }
        setEditorMode(undefined)
      }
      return
    }
    if (
      !currentDetail
      || !selectedVersion
      || !title.trim()
      || !allowed('create_version')
      || axis('edit')?.state !== 'AVAILABLE'
    ) return
    const saved = await execute(
      () => importFile
        ? api.importVersion(
          currentDetail.document.document_id,
          currentDetail.document.version,
          importFile,
          title.trim(),
          applicabilityScope.trim(),
          parentDocumentId || null,
          newIdempotencyKey('governance-document-import'),
        )
        : api.createVersion(
          currentDetail.document.document_id,
          currentDetail.document.version,
          {
            title: title.trim(),
            applicability_scope: applicabilityScope.trim(),
            sanitized_html: editorHtml.current,
            parent_document_id: parentDocumentId || null,
          },
          newIdempotencyKey('governance-document-version'),
        ),
      '새 immutable 문서 버전을 저장했습니다.',
    )
    if (saved) {
      if ('item' in saved) {
        const draft = saved.item.versions.find((version) => version.state === 'DRAFT')
        if (editorAttachmentFile && draft) {
          await execute(
            () => api.uploadAttachment(
              saved.item.document.document_id,
              draft.version_id,
              saved.item.document.version,
              editorAttachmentFile,
              newIdempotencyKey('governance-document-attachment'),
            ),
            '새 immutable 버전과 별첨을 저장했습니다.',
          )
        }
      }
      setEditorMode(undefined)
      setSelectedVersionId(undefined)
    }
  }
  const submit = async () => {
    if (
      !currentDetail
      || !selectedVersion
      || selectedVersion.state !== 'DRAFT'
      || !allowed('submit')
      || axis('edit')?.state !== 'AVAILABLE'
    ) return
    await execute(
      () => api.submitVersion(
        currentDetail.document.document_id,
        selectedVersion.version_id,
        currentDetail.document.version,
        newIdempotencyKey('governance-document-submit'),
      ),
      '선택 버전을 결재 상신했습니다.',
    )
  }
  const review = async () => {
    if (
      !currentDetail
      || !selectedVersion
      || selectedVersion.state !== 'IN_REVIEW'
      || !reviewDecision
      || !reviewReason.trim()
      || axis('review')?.state !== 'AVAILABLE'
      || !allowed('review')
      || (reviewDecision === 'APPROVE' && (
        axis('publish')?.state !== 'AVAILABLE' || !allowed('publish')
      ))
    ) return
    const saved = await execute(
      () => api.reviewVersion(
        currentDetail.document.document_id,
        selectedVersion.version_id,
        currentDetail.document.version,
        { decision: reviewDecision, reason: reviewReason.trim() },
        newIdempotencyKey('governance-document-review'),
      ),
      reviewDecision === 'APPROVE'
        ? '문서 버전을 승인·게시했습니다.'
        : '문서 버전을 반려했습니다.',
    )
    if (saved) {
      setReviewDecision(undefined)
      setReviewReason('')
    }
  }
  const archive = async () => {
    if (
      !currentDetail
      || !archiveReason.trim()
      || !allowed('archive')
      || axis('archive')?.state !== 'AVAILABLE'
    ) return
    const saved = await execute(
      () => api.archiveDocument(
        currentDetail.document.document_id,
        currentDetail.document.version,
        archiveReason.trim(),
        newIdempotencyKey('governance-document-archive'),
      ),
      '문서를 Archive 처리했습니다. 저장된 버전과 Object는 물리 삭제되지 않습니다.',
    )
    if (saved) {
      setArchiveOpen(false)
      setArchiveReason('')
      setSelectedDocumentId(undefined)
    }
  }
  const uploadAttachment = async () => {
    if (
      !currentDetail
      || !selectedVersion
      || !attachmentFile
      || attachmentFile.size > capability.limits.max_attachment_bytes
      || selectedVersionAttachments(currentDetail, selectedVersion.version_id).length
        >= capability.limits.max_attachments_per_version
      || !allowed('add_attachment')
      || axis('artifact_storage')?.state !== 'AVAILABLE'
    ) return
    const saved = await execute(
      () => api.uploadAttachment(
        currentDetail.document.document_id,
        selectedVersion.version_id,
        currentDetail.document.version,
        attachmentFile,
        newIdempotencyKey('governance-document-attachment'),
      ),
      '첨부파일의 저장 증빙을 등록했습니다.',
    )
    if (saved) setAttachmentFile(undefined)
  }
  const downloadAttachment = async (attachment: GovernanceDocumentAttachment) => {
    if (!currentDetail || !allowed('download_attachment')) return
    setBusy(true)
    setMutationError(undefined)
    setNotice(undefined)
    try {
      const value = await api.downloadAttachment(
        currentDetail.document.document_id,
        attachment.attachment_id,
      )
      const anchor = document.createElement('a')
      anchor.href = value.url
      anchor.download = value.attachment.original_name
      anchor.rel = 'noopener noreferrer'
      document.body.append(anchor)
      anchor.click()
      anchor.remove()
      setNotice('정확한 Object Version의 제한시간 다운로드를 시작했습니다.')
    } catch (error) {
      setMutationError(error)
    } finally {
      setBusy(false)
    }
  }

  const columns = useMemo<ColumnDef<GovernanceDocumentSummary>[]>(() => [
    { accessorKey: 'title', header: '문서명', size: 260, enableSorting: false },
    { accessorKey: 'category', header: '유형', size: 130, enableSorting: false, cell: ({ row }) => categoryLabel(row.original.category) },
    { accessorKey: 'state', header: '상태', size: 110, enableSorting: false, cell: ({ row }) => <DocumentStatus value={row.original.state} /> },
    { accessorKey: 'current_version_number', header: '게시 버전', size: 90, enableSorting: false, cell: ({ row }) => row.original.current_version_number === null ? '—' : `v${row.original.current_version_number}` },
    { accessorKey: 'classification', header: '분류', size: 100, enableSorting: false, cell: ({ row }) => classificationLabel(row.original.classification) },
    { accessorKey: 'updated_at', header: '최근 변경', size: 170, enableSorting: false, cell: ({ row }) => dateTime(row.original.updated_at) },
  ], [])

  return <section className="governance-document-library">
    <header className="governance-documents-header">
      <div>
        <span className="eyebrow">Immutable document versions</span>
        <h2>문서 관리</h2>
        <p>권한이 허용한 문서·버전만 조회하며, Archive는 객체나 버전을 물리 삭제하지 않습니다.</p>
      </div>
      <div className="action-row">
        <button type="button" className="button button-secondary" disabled={documents.isFetching} onClick={() => {
          onRefreshCapability()
          void documents.refetch()
        }}>권한·목록 새로고침</button>
        {axis('create')?.state === 'AVAILABLE' && <>
          <button type="button" className="button" onClick={() => openCreate('DOCUMENT')}>문서 작성</button>
          <button type="button" className="button button-secondary" onClick={() => setKind('TEMPLATE')}>템플릿 선택</button>
        </>}
        {axis('template_manage')?.state === 'AVAILABLE' && <button type="button" className="button button-secondary" onClick={() => openCreate('TEMPLATE')}>템플릿 작성</button>}
      </div>
    </header>
    {documents.error && <ErrorNotice error={documents.error} />}
    {notice && <p className="notice notice-success" role="status">{notice}</p>}
    <section className="panel governance-document-list-panel" aria-labelledby="governance-document-list-title">
      <header>
        <div><span className="eyebrow">Permission-pruned cursor page</span><h3 id="governance-document-list-title">{kind === 'DOCUMENT' ? '문서 목록' : 'Template 목록'}</h3></div>
        <form className="governance-document-filters" onSubmit={(event) => {
          event.preventDefault()
          setQuery(queryInput.trim())
        }}>
          <label>대상<select value={kind} onChange={(event) => setKind(event.target.value as GovernanceDocumentKind)}><option value="DOCUMENT">문서</option><option value="TEMPLATE">Template</option></select></label>
          <label>검색<input type="search" value={queryInput} onChange={(event) => setQueryInput(event.target.value)} /></label>
          {axis('archive')?.state === 'AVAILABLE' && <label className="governance-inline-check"><input type="checkbox" checked={includeArchived} onChange={(event) => setIncludeArchived(event.target.checked)} />Archive 포함</label>}
          <button type="submit" className="button button-secondary">적용</button>
        </form>
      </header>
      <DenseDataTable
        caption="거버넌스 문서 목록"
        columns={columns}
        data={documents.data?.items ?? []}
        getRowId={(row) => row.document_id}
        loading={documents.isPending}
        emptyMessage="현재 권한 범위에서 조회 가능한 문서가 없습니다."
        selectedRowId={selectedDocumentId}
        onRowActivate={(row) => setSelectedDocumentId(row.document_id)}
      />
      <CursorPagination
        page={pageIndex + 1}
        pageSize={PAGE_SIZE}
        pageSizeOptions={[PAGE_SIZE]}
        itemCount={documents.data?.items.length}
        canPrevious={pageIndex > 0}
        canNext={Boolean(documents.data?.page.next_cursor)}
        onPrevious={() => setPageIndex((current) => Math.max(0, current - 1))}
        onNext={() => {
          const next = documents.data?.page.next_cursor
          if (!next) return
          setCursorStack((current) => [...current.slice(0, pageIndex + 1), next])
          setPageIndex((current) => current + 1)
        }}
        onPageSizeChange={() => undefined}
        label="거버넌스 문서 페이지 탐색"
      />
    </section>
    {axis('knowledge_projection')?.state === 'AVAILABLE' && <KnowledgeEvidencePanel
      query={knowledgeQuery}
      search={knowledgeSearch}
      loading={knowledge.isFetching}
      error={knowledge.error}
      items={knowledge.data?.items ?? []}
      onQuery={setKnowledgeQuery}
      onSearch={() => setKnowledgeSearch(knowledgeQuery.trim())}
    />}
    <DocumentDetailDialog
      open={Boolean(selectedDocumentId)}
      detail={currentDetail}
      detailEtag={detail.data?.etag}
      detailLoading={detail.isPending}
      detailError={detail.error}
      selectedVersion={selectedVersion}
      selectedVersionId={selectedVersionId}
      onSelectedVersion={setSelectedVersionId}
      attachmentFile={attachmentFile}
      maximumAttachmentBytes={capability.limits.max_attachment_bytes}
      maximumAttachments={capability.limits.max_attachments_per_version}
      attachmentAvailable={axis('artifact_storage')?.state === 'AVAILABLE' && allowed('add_attachment')}
      downloadAvailable={allowed('download_attachment')}
      busy={busy}
      mutationError={mutationError}
      notice={notice}
      canCreateVersion={axis('edit')?.state === 'AVAILABLE' && allowed('create_version')}
      canSubmit={axis('edit')?.state === 'AVAILABLE' && allowed('submit')}
      canReview={axis('review')?.state === 'AVAILABLE' && allowed('review')}
      canPublish={axis('publish')?.state === 'AVAILABLE' && allowed('publish')}
      canArchive={axis('archive')?.state === 'AVAILABLE' && allowed('archive')}
      canInstantiate={axis('create')?.state === 'AVAILABLE' && allowed('instantiate_template')}
      onCreateVersion={openNewVersion}
      onSubmit={() => void submit()}
      onReview={(decision) => {
        setReviewDecision(decision)
        setReviewReason('')
        setMutationError(undefined)
      }}
      onArchive={() => {
        setArchiveReason('')
        setArchiveOpen(true)
      }}
      onInstantiate={() => {
        if (currentDetail) openCreate('DOCUMENT', currentDetail.document)
      }}
      onAttachmentFile={setAttachmentFile}
      onUploadAttachment={() => void uploadAttachment()}
      onDownloadAttachment={(attachment) => void downloadAttachment(attachment)}
      onClose={() => {
        if (!busy) setSelectedDocumentId(undefined)
      }}
    />
    <EditorDialog
      key={`${editorMode ?? 'closed'}:${selectedVersionId ?? (blueprintId || 'blank')}:${editorContentRevision}`}
      mode={editorMode}
      kind={editorKind}
      title={title}
      summary={summary}
      category={editorCategory}
      classification={classification}
      applicabilityScope={applicabilityScope}
      templates={(templates.data?.items ?? []).filter((template) => (
        template.category === editorCategory
        && template.current_published_version_id
        && template.allowed_actions.includes('instantiate_template')
      ))}
      blueprints={(blueprints.data?.items ?? []).filter((blueprint) => (
        blueprint.purpose === (
          editorKind === 'TEMPLATE' ? 'TEMPLATE' : 'STARTER_DOCUMENT'
        )
      ))}
      blueprintId={blueprintId}
      templateVersionId={templateVersionId}
      initialHtml={editorInitialHtml}
      editorKey={`${editorMode ?? 'closed'}:${selectedVersionId ?? (blueprintId || 'blank')}:${editorContentRevision}`}
      importFile={importFile}
      attachmentFile={editorAttachmentFile}
      parentDocumentId={parentDocumentId}
      parentDocuments={(parentCandidates.data?.items ?? []).filter((item) => (
        item.kind === 'DOCUMENT'
        && item.state !== 'ARCHIVED'
        && item.document_id !== currentDetail?.document.document_id
      ))}
      maximumHtmlBytes={capability.limits.max_html_bytes}
      maximumImportBytes={capability.limits.max_attachment_bytes}
      attachmentAvailable={axis('artifact_storage')?.state === 'AVAILABLE'}
      busy={busy}
      error={mutationError}
      onTitle={setTitle}
      onSummary={setSummary}
      onCategory={(value) => {
        setEditorCategory(value)
        setTemplateVersionId('')
        setBlueprintId('')
      }}
      onClassification={setClassification}
      onApplicabilityScope={setApplicabilityScope}
      onParentDocument={setParentDocumentId}
      onTemplateVersion={(value) => {
        setTemplateVersionId(value)
        setBlueprintId('')
      }}
      onBlueprint={applyBlueprint}
      onHtmlChange={useCallback((value: string) => {
        editorHtml.current = value
      }, [])}
      onMarkupImported={(value) => {
        editorHtml.current = value
        setEditorInitialHtml(value)
        setEditorContentRevision((current) => current + 1)
      }}
      onImportFile={setImportFile}
      onAttachmentFile={setEditorAttachmentFile}
      onSubmit={() => void saveEditor()}
      onClose={() => {
        if (!busy) setEditorMode(undefined)
      }}
    />
    <ReviewDialog
      decision={reviewDecision}
      reason={reviewReason}
      busy={busy}
      error={mutationError}
      assurance={assurance}
      onReason={setReviewReason}
      onSubmit={() => void review()}
      onClose={() => {
        if (!busy) setReviewDecision(undefined)
      }}
    />
    <ArchiveDialog
      open={archiveOpen}
      reason={archiveReason}
      busy={busy}
      error={mutationError}
      assurance={assurance}
      onReason={setArchiveReason}
      onSubmit={() => void archive()}
      onClose={() => {
        if (!busy) setArchiveOpen(false)
      }}
    />
  </section>
}

function DocumentDetailDialog({
  open,
  detail,
  detailEtag,
  detailLoading,
  detailError,
  selectedVersion,
  selectedVersionId,
  onSelectedVersion,
  attachmentFile,
  maximumAttachmentBytes,
  maximumAttachments,
  attachmentAvailable,
  downloadAvailable,
  busy,
  mutationError,
  notice,
  canCreateVersion,
  canSubmit,
  canReview,
  canPublish,
  canArchive,
  canInstantiate,
  onCreateVersion,
  onSubmit,
  onReview,
  onArchive,
  onInstantiate,
  onAttachmentFile,
  onUploadAttachment,
  onDownloadAttachment,
  onClose,
}: {
  open: boolean
  detail?: GovernanceDocumentDetail
  detailEtag?: string
  detailLoading: boolean
  detailError: unknown
  selectedVersion?: GovernanceDocumentVersion
  selectedVersionId?: string
  onSelectedVersion: (id: string) => void
  attachmentFile?: File
  maximumAttachmentBytes: number
  maximumAttachments: number
  attachmentAvailable: boolean
  downloadAvailable: boolean
  busy: boolean
  mutationError: unknown
  notice?: string
  canCreateVersion: boolean
  canSubmit: boolean
  canReview: boolean
  canPublish: boolean
  canArchive: boolean
  canInstantiate: boolean
  onCreateVersion: () => void
  onSubmit: () => void
  onReview: (decision: ReviewDecision) => void
  onArchive: () => void
  onInstantiate: () => void
  onAttachmentFile: (file?: File) => void
  onUploadAttachment: () => void
  onDownloadAttachment: (attachment: GovernanceDocumentAttachment) => void
  onClose: () => void
}) {
  const attachments = detail && selectedVersion
    ? selectedVersionAttachments(detail, selectedVersion.version_id)
    : []
  const reviews = detail && selectedVersion
    ? detail.reviews.filter((review) => review.document_version_id === selectedVersion.version_id)
    : []
  const attachmentLimitReached = attachments.length >= maximumAttachments
  return <Dialog
    open={open}
    title={detail?.document.title ?? '거버넌스 문서'}
    description="canonical HTML, immutable 버전 이력, 결재 상태와 첨부 증빙을 확인합니다."
    size="workspace"
    onRequestClose={onClose}
  >
    {detailLoading && <p role="status">문서 상세를 불러오는 중입니다.</p>}
    {Boolean(detailError) && <ErrorNotice error={detailError} />}
    {Boolean(mutationError) && <ErrorNotice error={mutationError} />}
    {notice && <p className="notice notice-success" role="status">{notice}</p>}
    {detail && <>
      <dl className="governance-document-meta">
        <div><dt>구분·유형</dt><dd>{detail.document.kind} · {categoryLabel(detail.document.category)}</dd></div>
        <div><dt>문서 상태</dt><dd><DocumentStatus value={detail.document.state} /></dd></div>
        <div><dt>게시 버전</dt><dd>{detail.document.current_version_number === null ? '—' : `v${detail.document.current_version_number}`}</dd></div>
        <div><dt>서버 변경 조건</dt><dd>{detailEtag ? 'ETag 확인됨' : 'ETag 없음 · 변경 잠김'}</dd></div>
        <div><dt>분류</dt><dd>{classificationLabel(detail.document.classification)}</dd></div>
        <div><dt>소유자</dt><dd>{subjectName(detail, detail.document.owner_subject_id)}</dd></div>
        <div><dt>생성일</dt><dd>{dateTime(detail.document.created_at)}</dd></div>
        <div><dt>수정일</dt><dd>{dateTime(detail.document.updated_at)}</dd></div>
        <div><dt>상위 문서</dt><dd>{detail.parent_document?.title ?? '—'}</dd></div>
        <div><dt>하위 문서</dt><dd>{detail.child_documents.map((item) => item.title).join(', ') || '—'}</dd></div>
      </dl>
      <div className="action-row">
        {canCreateVersion && detailEtag && <button type="button" className="button" disabled={busy || !selectedVersion} onClick={onCreateVersion}>수정</button>}
        {canSubmit && detailEtag && selectedVersion?.state === 'DRAFT' && <button type="button" className="button" disabled={busy} onClick={onSubmit}>결재 상신</button>}
        {canReview && canPublish && detailEtag && selectedVersion?.state === 'IN_REVIEW' && <button type="button" className="button" disabled={busy} onClick={() => onReview('APPROVE')}>승인·게시</button>}
        {canReview && detailEtag && selectedVersion?.state === 'IN_REVIEW' && <button type="button" className="button button-secondary" disabled={busy} onClick={() => onReview('REJECT')}>반려</button>}
        {canInstantiate && detail.document.kind === 'TEMPLATE' && selectedVersion?.state === 'PUBLISHED' && <button type="button" className="button button-secondary" disabled={busy} onClick={onInstantiate}>이 템플릿으로 문서 생성</button>}
        {canArchive && detailEtag && <button type="button" className="button button-danger" disabled={busy || detail.document.state === 'ARCHIVED'} onClick={onArchive}>삭제(Archive)</button>}
      </div>
      <div className="governance-document-detail-grid">
        <section className="governance-version-list" aria-labelledby="governance-version-list-title">
          <h3 id="governance-version-list-title">버전 이력</h3>
          {detail.versions.length === 0
            ? <p role="status">조회 가능한 버전이 없습니다.</p>
            : <ul>{detail.versions.map((version) => <li key={version.version_id}>
              <button
                type="button"
                className={selectedVersionId === version.version_id ? 'active' : ''}
                aria-current={selectedVersionId === version.version_id ? 'true' : undefined}
                onClick={() => onSelectedVersion(version.version_id)}
              >
                <strong>{version.version_tag}</strong>
                <DocumentStatus value={version.state} />
                <span>{version.source_format}</span>
                <small>{dateTime(version.created_at)}</small>
                <small>수정자 {subjectName(detail, version.author_id)}</small>
                <small>Object {version.artifact_state} · Knowledge {version.knowledge_state}</small>
              </button>
            </li>)}</ul>}
        </section>
        <section className="governance-document-content" aria-labelledby="governance-document-content-title">
          <header>
            <div><span className="eyebrow">Sanitized canonical HTML</span><h3 id="governance-document-content-title">{selectedVersion ? `${selectedVersion.version_tag} 본문` : '문서 본문'}</h3></div>
            {selectedVersion && <span>{formatBytes(selectedVersion.size_bytes)} · {selectedVersion.sanitizer_policy_version}</span>}
          </header>
          {!selectedVersion && <p role="status">표시할 버전을 선택하세요.</p>}
          {selectedVersion && <>
            <dl className="governance-document-meta governance-version-meta">
              <div><dt>버전 수정자</dt><dd>{subjectName(detail, selectedVersion.author_id)}</dd></div>
              <div><dt>버전 생성일</dt><dd>{dateTime(selectedVersion.created_at)}</dd></div>
              <div><dt>결재 상태</dt><dd>{selectedVersion.state}</dd></div>
              <div><dt>결재 상신일</dt><dd>{selectedVersion.submitted_at ? dateTime(selectedVersion.submitted_at) : '—'}</dd></div>
              <div><dt>결재자</dt><dd>{selectedVersion.reviewed_by ? subjectName(detail, selectedVersion.reviewed_by) : '—'}</dd></div>
              <div><dt>결재일</dt><dd>{selectedVersion.reviewed_at ? dateTime(selectedVersion.reviewed_at) : '—'}</dd></div>
              <div><dt>적용 범위</dt><dd>{selectedVersion.applicability_scope || '—'}</dd></div>
              <div><dt>상위 문서 연결</dt><dd>{selectedVersion.parent_document_id ? shortId(selectedVersion.parent_document_id) : '—'}</dd></div>
            </dl>
            <SafeGovernanceHtml
              html={selectedVersion.sanitized_html}
              contentHash={selectedVersion.content_sha256}
              sanitizerPolicyVersion={`${selectedVersion.sanitizer_policy_version}:${selectedVersion.sanitizer_policy_sha256}`}
            />
          </>}
        </section>
      </div>
      <section className="governance-document-attachments" aria-labelledby="governance-document-attachments-title">
        <header><h3 id="governance-document-attachments-title">선택 버전 첨부파일</h3></header>
        {attachments.length === 0
          ? <p role="status">등록된 첨부파일이 없습니다.</p>
          : <ul>{attachments.map((attachment) => <li key={attachment.attachment_id}>
            <strong>{attachment.original_name}</strong>
            <span>별첨 #{String(attachment.serial_number).padStart(3, '0')}</span>
            <span>{attachment.storage_filename ?? 'legacy object name'}</span>
            <span>{attachment.content_type}</span>
            <span>{formatBytes(attachment.size_bytes)}</span>
            <span>{dateTime(attachment.created_at)}</span>
            {downloadAvailable && <button
              type="button"
              className="button button-secondary"
              disabled={busy}
              onClick={() => onDownloadAttachment(attachment)}
            >다운로드</button>}
          </li>)}</ul>}
        {attachmentAvailable && selectedVersion && <div className="governance-attachment-input">
          <label>첨부파일<input type="file" disabled={busy || attachmentLimitReached} onChange={(event) => onAttachmentFile(event.target.files?.[0])} /></label>
          <small>최대 {formatBytes(maximumAttachmentBytes)} · 버전당 {maximumAttachments}개</small>
          <button type="button" className="button button-secondary" disabled={busy || attachmentLimitReached || !attachmentFile || attachmentFile.size > maximumAttachmentBytes} onClick={onUploadAttachment}>첨부 증빙 등록</button>
          {attachmentLimitReached && <p role="alert">이 버전의 첨부파일 허용 개수에 도달했습니다.</p>}
          {attachmentFile && attachmentFile.size > maximumAttachmentBytes && <p role="alert">선택한 파일이 서버 허용 크기를 초과합니다.</p>}
        </div>}
      </section>
      <section className="governance-document-attachments" aria-labelledby="governance-document-reviews-title">
        <header><h3 id="governance-document-reviews-title">선택 버전 결재 이력</h3></header>
        {reviews.length === 0
          ? <p role="status">기록된 결재가 없습니다.</p>
          : <ul>{reviews.map((review) => <li key={review.review_id}>
            <strong>{review.decision}</strong>
            <span>{review.reason}</span>
            <span>{subjectName(detail, review.reviewer_id)}</span>
            <span>{dateTime(review.created_at)}</span>
          </li>)}</ul>}
      </section>
    </>}
  </Dialog>
}

function EditorDialog({
  mode,
  kind,
  title,
  summary,
  category,
  classification,
  applicabilityScope,
  templates,
  blueprints,
  blueprintId,
  templateVersionId,
  initialHtml,
  editorKey,
  importFile,
  attachmentFile,
  parentDocumentId,
  parentDocuments,
  maximumHtmlBytes,
  maximumImportBytes,
  attachmentAvailable,
  busy,
  error,
  onTitle,
  onSummary,
  onCategory,
  onClassification,
  onApplicabilityScope,
  onParentDocument,
  onTemplateVersion,
  onBlueprint,
  onHtmlChange,
  onMarkupImported,
  onImportFile,
  onAttachmentFile,
  onSubmit,
  onClose,
}: {
  mode?: EditorMode
  kind: GovernanceDocumentKind
  title: string
  summary: string
  category: GovernanceDocumentCategory
  classification: number
  applicabilityScope: string
  templates: GovernanceDocumentSummary[]
  blueprints: GovernanceDocumentBlueprint[]
  blueprintId: string
  templateVersionId: string
  initialHtml: string
  editorKey: string
  importFile?: File
  attachmentFile?: File
  parentDocumentId: string
  parentDocuments: GovernanceDocumentSummary[]
  maximumHtmlBytes: number
  maximumImportBytes: number
  attachmentAvailable: boolean
  busy: boolean
  error: unknown
  onTitle: (value: string) => void
  onSummary: (value: string) => void
  onCategory: (value: GovernanceDocumentCategory) => void
  onClassification: (value: number) => void
  onApplicabilityScope: (value: string) => void
  onParentDocument: (value: string) => void
  onTemplateVersion: (value: string) => void
  onBlueprint: (value: string) => void
  onHtmlChange: (value: string) => void
  onMarkupImported: (value: string) => void
  onImportFile: (file?: File) => void
  onAttachmentFile: (file?: File) => void
  onSubmit: () => void
  onClose: () => void
}) {
  const [htmlBytes, setHtmlBytes] = useState(() => utf8Bytes(initialHtml))
  const [currentHtml, setCurrentHtml] = useState(initialHtml)
  const [importFeedback, setImportFeedback] = useState<string>()
  const [importError, setImportError] = useState<unknown>()
  const [importing, setImporting] = useState(false)
  const [initialSnapshot] = useState(() => mode ? {
    title,
    summary,
    applicabilityScope,
    html: initialHtml,
    category,
    classification,
    templateVersionId,
    blueprintId,
    parentDocumentId,
    importFile,
    attachmentFile,
  } : null)

  useEffect(() => {
    setHtmlBytes(utf8Bytes(initialHtml))
    setCurrentHtml(initialHtml)
  }, [initialHtml, mode])
  
  const isDirty = initialSnapshot !== null && (
    title !== initialSnapshot.title ||
    summary !== initialSnapshot.summary ||
    applicabilityScope !== initialSnapshot.applicabilityScope ||
    currentHtml !== initialSnapshot.html ||
    category !== initialSnapshot.category ||
    classification !== initialSnapshot.classification ||
    templateVersionId !== initialSnapshot.templateVersionId ||
    blueprintId !== initialSnapshot.blueprintId ||
    parentDocumentId !== initialSnapshot.parentDocumentId ||
    importFile !== initialSnapshot.importFile ||
    attachmentFile !== initialSnapshot.attachmentFile
  )

  const requestCancel = () => {
    if (isDirty && !window.confirm('저장하지 않은 변경 사항이 있습니다. 취소하시겠습니까?')) return
    onClose()
  }

  const importValid = !importFile
    || (importFile.size <= maximumImportBytes && supportedImport(importFile))
  const attachmentValid = !attachmentFile || attachmentFile.size <= maximumImportBytes
  const createValid = Boolean(
    title.trim()
    && importValid
    && attachmentValid
    && (
      templateVersionId
      || importFile
      || htmlBytes <= maximumHtmlBytes
    ),
  )
  const selectImport = async (file?: File) => {
    setImportFeedback(undefined)
    setImportError(undefined)
    if (!file) {
      onImportFile(undefined)
      return
    }
    const name = file.name.toLocaleLowerCase()
    if (name.endsWith('.docx')) {
      onImportFile(file)
      setImportFeedback('Word 파일은 저장 시 서버 변환·sanitize 경계에서 처리합니다.')
      return
    }
    onImportFile(undefined)
    setImporting(true)
    try {
      const imported = await governanceMarkupFromFile(file)
      onMarkupImported(imported.html)
      setCurrentHtml(imported.html)
      setHtmlBytes(utf8Bytes(imported.html))
      setImportFeedback(`${imported.format === 'MARKDOWN' ? 'Markdown' : 'HTML'} 서식을 안전한 편집 본문으로 불러왔습니다. 저장 전에 아래에서 수정할 수 있습니다.`)
    } catch (next) {
      setImportError(next)
    } finally {
      setImporting(false)
    }
  }
  return <Dialog
    open={Boolean(mode)}
    title={mode === 'CREATE' ? (kind === 'TEMPLATE' ? '템플릿 작성' : '문서 작성') : '새 immutable 버전'}
    description={mode === 'CREATE'
      ? '선택한 exact Template version 또는 안전한 HTML 편집 결과로 생성합니다.'
      : '현재 본문을 편집하거나 HTML·Markdown·Word 파일을 서버 변환 경계로 가져옵니다.'}
    size="workspace"
    showCloseButton={false}
    onRequestClose={() => undefined}
    footer={<>
      <button type="button" className="button button-secondary" disabled={busy} onClick={requestCancel}>취소</button>
      <button type="button" className="button" disabled={busy || importing || !createValid} onClick={onSubmit}>{busy ? '저장 중…' : '저장'}</button>
    </>}
  >
    {Boolean(error) && <ErrorNotice error={error} />}
    {Boolean(importError) && <ErrorNotice error={importError} />}
    <div className="governance-editor-layout">
      <main className="governance-editor-main">
        <header><div><span className="eyebrow">Safe document canvas</span><h3>문서 본문</h3></div><span>{formatBytes(htmlBytes)} / {formatBytes(maximumHtmlBytes)}</span></header>
        {!templateVersionId && !importFile && <GovernanceHtmlEditor
          key={editorKey}
          initialHtml={initialHtml}
          disabled={busy || importing}
          onHtmlChange={(value) => {
            setCurrentHtml(value)
            setHtmlBytes(utf8Bytes(value))
            onHtmlChange(value)
          }}
        />}
        {htmlBytes > maximumHtmlBytes && !templateVersionId && !importFile && <p role="alert">편집한 HTML이 서버 허용 크기를 초과합니다.</p>}
        {templateVersionId && <p className="callout">선택한 exact Template version을 서버가 복제합니다. 브라우저는 Template HTML을 재작성하지 않습니다.</p>}
        {importFile && <div className="governance-import-pending"><strong>{importFile.name}</strong><p>Word 문서는 저장할 때 서버에서 변환되므로 편집 preview가 제공되지 않습니다.</p></div>}
      </main>
      <aside className="governance-editor-sidebar" aria-label="문서 속성과 가져오기 설정">
        <details className="governance-editor-card" open>
          <summary><span>01</span><span><strong>문서 정보</strong><small>식별과 게시 범위를 설정합니다.</small></span></summary>
          <div className="governance-editor-fields">
            <label>버전 제목<input required maxLength={500} value={title} disabled={busy} onChange={(event) => onTitle(event.target.value)} /></label>
            {mode === 'CREATE' && <>
              <label>유형<select value={category} disabled={busy} onChange={(event) => onCategory(event.target.value as GovernanceDocumentCategory)}>{CATEGORIES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
              <label>분류<select value={classification} disabled={busy} onChange={(event) => onClassification(Number(event.target.value))}><option value={0}>PUBLIC</option><option value={1}>INTERNAL</option><option value={2}>CONFIDENTIAL</option><option value={3}>RESTRICTED</option></select></label>
              <label>요약<textarea maxLength={2000} value={summary} disabled={busy} onChange={(event) => onSummary(event.target.value)} /></label>
            </>}
            {kind === 'DOCUMENT' && <label>상위 문서<select value={parentDocumentId} disabled={busy} onChange={(event) => onParentDocument(event.target.value)}><option value="">상위 문서 없음</option>{parentDocuments.map((parent) => <option key={parent.document_id} value={parent.document_id}>{parent.title}</option>)}</select></label>}
            <label>적용 범위<textarea maxLength={4000} value={applicabilityScope} disabled={busy} onChange={(event) => onApplicabilityScope(event.target.value)} />
              <small>필요한 경우 `dataset:참조` 또는 `term:용어`를 선언하세요.</small>
            </label>
          </div>
        </details>
        {mode === 'CREATE' && <details className="governance-editor-card">
          <summary><span>02</span><span><strong>시작 양식</strong><small>승인된 구조를 선택하거나 빈 문서로 시작합니다.</small></span></summary>
          <div className="governance-editor-fields">
            {kind === 'TEMPLATE' && <label>기본 양식<select value={blueprintId} disabled={busy} onChange={(event) => onBlueprint(event.target.value)}><option value="">빈 템플릿</option>{blueprints.map((blueprint) => <option key={blueprint.blueprint_id} value={blueprint.blueprint_id}>{categoryLabel(blueprint.category)} · {blueprint.title}</option>)}</select></label>}
            {kind === 'DOCUMENT' && <>
              <label>기본 관리 문서<select value={blueprintId} disabled={busy} onChange={(event) => onBlueprint(event.target.value)}><option value="">빈 문서</option>{blueprints.map((blueprint) => <option key={blueprint.blueprint_id} value={blueprint.blueprint_id}>{blueprint.title}</option>)}</select></label>
              <label>게시 템플릿 선택<select value={templateVersionId} disabled={busy} onChange={(event) => onTemplateVersion(event.target.value)}><option value="">사용하지 않음</option>{templates.map((template) => <option key={template.document_id} value={template.current_published_version_id ?? ''}>{template.title} · v{template.current_version_number}</option>)}</select></label>
            </>}
          </div>
        </details>}
        <details className="governance-editor-card governance-editor-import-card">
          <summary><span>03</span><span><strong>파일 가져오기</strong><small>HTML·Markdown은 즉시 편집 가능한 안전한 본문으로 변환합니다.</small></span></summary>
          <label className="governance-file-drop">HTML·Markdown·Word 선택
            <input
              type="file"
              accept=".html,text/html,.md,text/markdown,.docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              disabled={busy || importing}
              onChange={(event) => void selectImport(event.target.files?.[0])}
            />
            <small>최대 {formatBytes(maximumImportBytes)} · script/style/iframe은 제거됩니다.</small>
          </label>
          {importing && <p role="status">문서 서식을 변환하는 중입니다…</p>}
          {importFeedback && <p className="notice notice-success" role="status">{importFeedback}</p>}
          {importFile && !supportedImport(importFile) && <p role="alert">HTML, Markdown 또는 DOCX 파일만 가져올 수 있습니다.</p>}
          {importFile && importFile.size > maximumImportBytes && <p role="alert">선택한 파일이 서버의 가져오기 허용 크기를 초과합니다.</p>}
        </details>
        {kind === 'DOCUMENT' && <details className="governance-editor-card governance-editor-attachment">
          <summary><span>04</span><span><strong>별첨 등록</strong><small>본문과 분리된 불변 Object로 저장합니다.</small></span></summary>
          <label>별첨 파일<input type="file" disabled={busy || !attachmentAvailable} onChange={(event) => onAttachmentFile(event.target.files?.[0])} /></label>
          {!attachmentAvailable && <small>현재 Object Storage capability가 준비되지 않아 별첨을 선택할 수 없습니다.</small>}
          {attachmentFile && <small>{attachmentFile.name} · {formatBytes(attachmentFile.size)}</small>}
          {attachmentFile && !attachmentValid && <p role="alert">선택한 별첨이 서버 허용 크기를 초과합니다.</p>}
        </details>}
      </aside>
    </div>
  </Dialog>
}

function ReviewDialog({
  decision,
  reason,
  busy,
  error,
  assurance,
  onReason,
  onSubmit,
  onClose,
}: {
  decision?: ReviewDecision
  reason: string
  busy: boolean
  error: unknown
  assurance?: AssuranceActions
  onReason: (value: string) => void
  onSubmit: () => void
  onClose: () => void
}) {
  return <Dialog
    open={Boolean(decision)}
    title={decision === 'APPROVE' ? '문서 버전 승인·게시' : '문서 버전 반려'}
    description="현재 선택한 immutable 버전에만 결재 판단을 기록합니다."
    onRequestClose={onClose}
    footer={<>
      <button type="button" className="button button-secondary" disabled={busy} onClick={onClose}>취소</button>
      <button type="button" className="button" disabled={busy || !reason.trim()} onClick={onSubmit}>판단 기록</button>
    </>}
  >
    {assurance && <AssuranceNotice error={error} {...assurance} />}
    {Boolean(error) && <ErrorNotice error={error} />}
    <label>결재 사유<textarea required maxLength={4000} value={reason} disabled={busy} onChange={(event) => onReason(event.target.value)} /></label>
  </Dialog>
}

function ArchiveDialog({
  open,
  reason,
  busy,
  error,
  assurance,
  onReason,
  onSubmit,
  onClose,
}: {
  open: boolean
  reason: string
  busy: boolean
  error: unknown
  assurance?: AssuranceActions
  onReason: (value: string) => void
  onSubmit: () => void
  onClose: () => void
}) {
  return <Dialog
    open={open}
    title="거버넌스 문서 삭제(Archive)"
    description="목록의 활성 상태만 종료합니다. 감사·복구를 위해 기존 버전과 Object Storage 객체는 물리 삭제하지 않습니다."
    onRequestClose={onClose}
    footer={<>
      <button type="button" className="button button-secondary" disabled={busy} onClick={onClose}>취소</button>
      <button type="button" className="button button-danger" disabled={busy || !reason.trim()} onClick={onSubmit}>삭제(Archive) 확인</button>
    </>}
  >
    {assurance && <AssuranceNotice error={error} {...assurance} />}
    {Boolean(error) && <ErrorNotice error={error} />}
    <label>삭제(Archive) 사유<textarea required maxLength={4000} value={reason} disabled={busy} onChange={(event) => onReason(event.target.value)} /></label>
  </Dialog>
}

function KnowledgeEvidencePanel({
  query,
  search,
  loading,
  error,
  items,
  onQuery,
  onSearch,
}: {
  query: string
  search: string
  loading: boolean
  error: unknown
  items: Array<{
    chunk_id: string
    document_title: string
    version_tag: string
    excerpt: string
    score_basis_points: number
  }>
  onQuery: (value: string) => void
  onSearch: () => void
}) {
  return <section className="panel governance-document-list-panel" aria-labelledby="governance-evidence-title">
    <header>
      <div><span className="eyebrow">Published knowledge projection</span><h3 id="governance-evidence-title">문서 지식 근거 검색</h3></div>
      <form className="governance-document-filters" onSubmit={(event) => {
        event.preventDefault()
        onSearch()
      }}>
        <label>검색어<input type="search" minLength={2} value={query} onChange={(event) => onQuery(event.target.value)} /></label>
        <button type="submit" className="button button-secondary" disabled={query.trim().length < 2 || loading}>검색</button>
      </form>
    </header>
    {Boolean(error) && <ErrorNotice error={error} />}
    {loading && <p role="status">게시 문서 근거를 검색하는 중입니다.</p>}
    {!loading && search && items.length === 0 && <p role="status">권한 범위에서 일치하는 게시 문서 근거가 없습니다.</p>}
    {items.length > 0 && <ul className="governance-evidence-results">{items.map((item) => <li key={item.chunk_id}>
      <strong>{item.document_title} · {item.version_tag}</strong>
      <span>{item.score_basis_points} bp</span>
      <p>{item.excerpt}</p>
    </li>)}</ul>}
  </section>
}

function selectedVersionAttachments(
  detail: GovernanceDocumentDetail,
  versionId: string,
): GovernanceDocumentAttachment[] {
  return detail.attachments.filter((attachment) => (
    attachment.document_version_id === versionId
  ))
}

function DocumentStatus({ value }: { value: string }) {
  const visibleValue = {
    IN_REVIEW: 'PENDING_APPROVAL',
    PUBLISHED: 'ACTIVE',
    SUPERSEDED: 'SUPERSEDED',
  }[value] ?? value
  return <span className={`governance-document-status status-${value.toLocaleLowerCase().replaceAll('_', '-')}`}>
    <span aria-hidden="true" />
    {visibleValue}
  </span>
}

function capabilityReason(axis?: GovernanceDocumentCapabilityAxis): string {
  if (!axis) return '서버가 문서 열람 capability를 제공하지 않았습니다.'
  return axis.reason_code ?? (axis.state === 'DENIED'
    ? '현재 역할로 열람할 수 없습니다.'
    : '문서 기능을 사용할 수 없습니다.')
}

function categoryLabel(value: GovernanceDocumentCategory): string {
  return CATEGORIES.find((candidate) => candidate.value === value)?.label ?? value
}

function classificationLabel(value: number): string {
  return ['PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED'][value] ?? `LEVEL ${value}`
}

function dateTime(value: string): string {
  const timestamp = Date.parse(value)
  return Number.isFinite(timestamp) ? new Date(timestamp).toLocaleString('ko-KR') : '—'
}

function shortId(value: string): string {
  return value.length > 14 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value
}

function subjectName(detail: GovernanceDocumentDetail, subjectId: string): string {
  const displayName = detail.subject_display_names?.[subjectId]
  return displayName ? `${displayName} (${shortId(subjectId)})` : shortId(subjectId)
}

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value < 0) return '—'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`
  return `${(value / (1024 * 1024)).toFixed(1)} MiB`
}

function utf8Bytes(value: string): number {
  return new TextEncoder().encode(value).byteLength
}

function supportedImport(file: File): boolean {
  const name = file.name.toLocaleLowerCase()
  return (
    name.endsWith('.html')
    || name.endsWith('.htm')
    || name.endsWith('.md')
    || name.endsWith('.docx')
  )
}

export type { GovernanceDocumentState }
