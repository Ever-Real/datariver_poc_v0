import { useEffect, useMemo, useRef, useState } from 'react'
import { Columns3, Database, Save, ShieldCheck } from 'lucide-react'
import { newIdempotencyKey, type ApiClient } from '../../api/client'
import type {
  CatalogAssetDetail,
  ManualMetadataSubmissionReport,
  ManualMetadataColumn,
  ManualMetadataSubmission,
} from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { ControlledVocabularyInput } from '../../components/common/ControlledVocabularyInput'
import { schemaDescriptionFields } from './RegistrationColumnDescriptionEditor'

interface EditableColumn extends ManualMetadataColumn {
  dataType: string
  logicalName: string | null
}

const MANUAL_POLL_MAX_ATTEMPTS = 20
const MANUAL_POLL_MAX_ELAPSED_MS = 120_000

function tokenValues(value: unknown, collection: 'tags' | 'terms'): string[] {
  if (!value || typeof value !== 'object') return []
  const nested = (value as Record<string, unknown>)[collection]
  if (!Array.isArray(nested)) return []
  const key = collection === 'tags' ? 'tag' : 'term'
  return nested.flatMap((entry) => {
    const candidate = entry && typeof entry === 'object' ? (entry as Record<string, unknown>)[key] : undefined
    if (typeof candidate === 'string') return [candidate]
    if (candidate && typeof candidate === 'object') {
      const document = candidate as Record<string, unknown>
      const label = document.name ?? document.urn
      return typeof label === 'string' ? [label] : []
    }
    return []
  })
}

function tableTerms(asset: CatalogAssetDetail): string[] {
  return asset.glossary_terms.flatMap((entry) => {
    const term = entry.term
    if (typeof term === 'string') return [term]
    if (term && typeof term === 'object') {
      const document = term as Record<string, unknown>
      const label = document.name ?? document.urn
      return typeof label === 'string' ? [label] : []
    }
    return []
  })
}

function unique(values: string[], maximum = 100): string[] {
  return values.map((value) => value.trim()).filter(Boolean).filter((value, index, all) => all.indexOf(value) === index).slice(0, maximum)
}

/** v0.3-shaped inputs, backed by an independent manual-submission contract. */
export function RegistrationManualWorkbench({
  client,
  asset,
  loading,
  onClose,
  onPreviousFieldPage = () => undefined,
  onNextFieldPage = () => undefined,
}: {
  client: ApiClient
  asset?: CatalogAssetDetail
  loading: boolean
  onClose: () => void
  onPreviousFieldPage?: () => void
  onNextFieldPage?: () => void
}) {
  const fields = useMemo(() => asset ? schemaDescriptionFields(asset.schema_fields) : [], [asset])
  const [description, setDescription] = useState('')
  const [domain, setDomain] = useState<string[]>([])
  const [tags, setTags] = useState<string[]>([])
  const [terms, setTerms] = useState<string[]>([])
  const [columnEdits, setColumnEdits] = useState<Record<string, ManualMetadataColumn>>({})
  const [submitting, setSubmitting] = useState(false)
  const [submission, setSubmission] = useState<ManualMetadataSubmission>()
  const [report, setReport] = useState<ManualMetadataSubmissionReport>()
  const [pollingStopped, setPollingStopped] = useState(false)
  const [pollRun, setPollRun] = useState(0)
  const [error, setError] = useState<unknown>()
  const boundaryGeneration = useRef(0)
  const draftRevision = useRef(0)
  const saveController = useRef<AbortController | null>(null)
  const pollingController = useRef<AbortController | null>(null)
  const activeSnapshotKey = useRef<string | undefined>(undefined)
  const activeFieldPageKey = useRef<string | undefined>(undefined)
  const clippedEditableSource = Boolean(
    asset
    && (
      asset.description_truncated
      || asset.tags_truncated
      || asset.terms_truncated
      || asset.schema_fields_truncated
      || !asset.schema_fields_total_exact
      || Boolean(asset.stale_at)
      || asset.schema_fields.some((field) => (
        field.description_truncated === true
        || field.tags_truncated === true
        || field.terms_truncated === true
      ))
    )
  )
  const columns = useMemo(() => fields.map((field) => {
    const source = asset?.schema_fields.find((item) => item.fieldPath === field.fieldPath)
    const baseline: EditableColumn = {
      field_path: field.fieldPath,
      dataType: field.dataType ?? '',
      logicalName: field.logicalName,
      description: field.description ?? '',
      tags: unique(tokenValues(source?.globalTags ?? source?.tags, 'tags')),
      terms: unique(tokenValues(source?.glossaryTerms ?? source?.terms, 'terms')),
    }
    const edit = columnEdits[field.fieldPath]
    return edit ? { ...baseline, ...edit } : baseline
  }), [asset, columnEdits, fields])
  const snapshotKey = asset
    ? `${asset.id}:${asset.projection_source_version}:${asset.source_version}`
    : undefined
  const fieldPageKey = asset
    ? `${snapshotKey}:${asset.schema_fields_offset}`
    : undefined

  useEffect(() => {
    if (activeSnapshotKey.current === snapshotKey) return
    activeSnapshotKey.current = snapshotKey
    boundaryGeneration.current += 1
    draftRevision.current += 1
    saveController.current?.abort()
    pollingController.current?.abort()
    setSubmitting(false)
    setDescription(asset?.description ?? '')
    setDomain(asset?.domain ? [asset.domain] : [])
    setTags(unique(asset?.tags ?? []))
    setTerms(unique(asset ? tableTerms(asset) : []))
    setColumnEdits({})
    setSubmission(undefined)
    setReport(undefined)
    setPollingStopped(false)
    setError(undefined)
  }, [asset, snapshotKey])

  useEffect(() => {
    if (activeFieldPageKey.current === fieldPageKey) return
    if (activeFieldPageKey.current !== undefined) {
      draftRevision.current += 1
      setSubmission(undefined)
    }
    activeFieldPageKey.current = fieldPageKey
  }, [fieldPageKey])

  useEffect(() => () => {
    boundaryGeneration.current += 1
    saveController.current?.abort()
    pollingController.current?.abort()
  }, [])

  useEffect(() => {
    const submissionId = submission?.id
    const sourceVersion = submission?.source_version
    if (!submissionId || !sourceVersion) return
    const controller = new AbortController()
    pollingController.current?.abort()
    pollingController.current = controller
    const generation = boundaryGeneration.current
    let timeout: ReturnType<typeof setTimeout> | undefined
    let delay = 750
    let attempts = 0
    const startedAt = Date.now()
    setPollingStopped(false)
    const poll = () => {
      if (
        attempts >= MANUAL_POLL_MAX_ATTEMPTS
        || Date.now() - startedAt >= MANUAL_POLL_MAX_ELAPSED_MS
        || document.visibilityState === 'hidden'
      ) {
        setPollingStopped(true)
        return
      }
      timeout = setTimeout(() => {
        attempts += 1
        void client.request<ManualMetadataSubmissionReport>(
          `/registration/manual-submissions/${submissionId}`,
          { signal: controller.signal },
        ).then((next) => {
          if (
            controller.signal.aborted
            || generation !== boundaryGeneration.current
            || next.submission.id !== submissionId
            || next.submission.source_version !== sourceVersion
          ) return
          setSubmission(next.submission)
          setReport(next)
          if (next.submission.state !== 'APPLIED' && next.submission.state !== 'FAILED') {
            delay = Math.min(delay * 2, 10_000)
            poll()
          } else {
            setPollingStopped(false)
          }
        }).catch((next: unknown) => {
          if (!controller.signal.aborted && generation === boundaryGeneration.current) {
            setError(next)
            setPollingStopped(true)
          }
        })
      }, delay)
    }
    poll()
    return () => {
      controller.abort()
      if (pollingController.current === controller) pollingController.current = null
      if (timeout) clearTimeout(timeout)
    }
  }, [
    client,
    pollRun,
    submission?.id,
    submission?.source_version,
  ])

  const updateColumn = (fieldPath: string, next: Partial<EditableColumn>) => {
    const current = columns.find((column) => column.field_path === fieldPath)
    const field = fields.find((value) => value.fieldPath === fieldPath)
    const source = asset?.schema_fields.find((item) => item.fieldPath === fieldPath)
    if (!current || !field) return
    draftRevision.current += 1
    const updated = { ...current, ...next }
    const baseline: ManualMetadataColumn = {
      field_path: fieldPath,
      description: field.description ?? '',
      tags: unique(tokenValues(source?.globalTags ?? source?.tags, 'tags')),
      terms: unique(tokenValues(source?.glossaryTerms ?? source?.terms, 'terms')),
    }
    setColumnEdits((existing) => {
      const copy = { ...existing }
      if (
        updated.description === baseline.description
        && JSON.stringify(updated.tags) === JSON.stringify(baseline.tags)
        && JSON.stringify(updated.terms) === JSON.stringify(baseline.terms)
      ) {
        delete copy[fieldPath]
      } else {
        copy[fieldPath] = {
          field_path: fieldPath,
          description: updated.description,
          tags: updated.tags,
          terms: updated.terms,
        }
      }
      return copy
    })
    setSubmission(undefined)
  }

  const save = async () => {
    if (
      !asset
      || submitting
      || clippedEditableSource
    ) return
    const generation = boundaryGeneration.current
    const revision = draftRevision.current
    const assetId = asset.id
    const sourceVersion = asset.projection_source_version
    saveController.current?.abort()
    const controller = new AbortController()
    saveController.current = controller
    setSubmitting(true)
    setError(undefined)
    try {
      const result = await client.request<ManualMetadataSubmission>('/registration/manual-submissions', {
        method: 'POST',
        signal: controller.signal,
        idempotencyKey: newIdempotencyKey('manual-metadata'),
        body: JSON.stringify({
          asset_id: asset.id,
          source_version: asset.projection_source_version,
          provider_source_version: asset.source_version,
          description,
          domain: domain[0] ?? null,
          tags,
          terms,
          column_edits: Object.values(columnEdits).sort(
            (left, right) => left.field_path.localeCompare(right.field_path),
          ),
        }),
      })
      if (
        controller.signal.aborted
        || generation !== boundaryGeneration.current
        || revision !== draftRevision.current
        || asset.id !== assetId
        || asset.projection_source_version !== sourceVersion
        || result.source_version !== sourceVersion
      ) return
      setSubmission(result)
      setReport(undefined)
      setPollingStopped(false)
      setPollRun((current) => current + 1)
    } catch (next) {
      if (
        !controller.signal.aborted
        && generation === boundaryGeneration.current
        && revision === draftRevision.current
      ) setError(next)
    } finally {
      if (!controller.signal.aborted && generation === boundaryGeneration.current) {
        setSubmitting(false)
      }
    }
  }

  const refreshCurrentSubmission = () => {
    if (!submission) return
    setPollingStopped(false)
    setPollRun((current) => current + 1)
  }

  const changeDraft = <T,>(setter: (value: T) => void, value: T) => {
    draftRevision.current += 1
    setter(value)
    setSubmission(undefined)
  }

  const moveFieldPage = (move: () => void) => {
    draftRevision.current += 1
    setSubmission(undefined)
    move()
  }

  return <main className="registration-editor-panel panel" aria-busy={loading || submitting}>
    <header><div><span className="eyebrow">Manual workbench</span><h2>Metadata Registration</h2></div><span className="badge badge-soft"><ShieldCheck size={11} />GOVERNED</span></header>
    {loading && <div className="registration-empty-editor">선택한 자산의 검증된 메타데이터를 불러오는 중입니다.</div>}
    {!loading && !asset && <div className="registration-v03-body registration-v03-empty-workbench">
      <section className="registration-v03-properties" aria-labelledby="manual-properties-title"><header><div><Database size={14} aria-hidden="true" /><h3 id="manual-properties-title">Table Properties</h3></div></header><div className="registration-empty-editor registration-v03-empty"><strong>Resource Tree에서 테이블을 선택하세요.</strong><span>선택한 테이블의 실제 DataHub 속성이 이 영역에 표시됩니다.</span></div></section>
      <section className="registration-v03-columns" aria-labelledby="manual-columns-title"><header><span aria-hidden="true" /><h3 id="manual-columns-title"><Columns3 size={14} aria-hidden="true" />Column Schema Specifications</h3></header><div className="registration-empty-editor registration-v03-empty"><strong>선택된 컬럼 스키마가 없습니다.</strong><span>테이블을 선택하면 권한 내 컬럼과 편집 가능한 메타데이터가 이 영역에 표시됩니다.</span></div></section>
    </div>}
    {!loading && asset && <div className="registration-v03-body">
      <section className="registration-v03-properties" aria-labelledby="manual-properties-title"><header><div><Database size={14} aria-hidden="true" /><h3 id="manual-properties-title">Table Properties</h3></div></header>
        <div className="dense-table-frame"><table className="dense-table registration-properties-table registration-edit-table"><colgroup><col className="registration-prop-platform" /><col className="registration-prop-database" /><col className="registration-prop-schema" /><col className="registration-prop-table" /><col className="registration-prop-domain" /><col className="registration-prop-description" /><col className="registration-prop-term" /><col className="registration-prop-tag" /></colgroup><thead><tr><th>Platform</th><th>Database</th><th>Schema</th><th>Table Name</th><th>Domain</th><th>Description</th><th>Term</th><th>Tag</th></tr></thead><tbody><tr>
          <td title={asset.platform ?? '—'}>{asset.platform ?? '—'}</td><td title={asset.database_name ?? '—'}>{asset.database_name ?? '—'}</td><td title={asset.schema_name ?? '—'}>{asset.schema_name ?? '—'}</td><td title={asset.name}><strong>{asset.name}</strong><small>{asset.asset_type}</small></td>
          <td><ControlledVocabularyInput client={client} kind="DOMAIN" values={domain} maxItems={1} label="테이블 Domain" onChange={(next) => changeDraft(setDomain, next)} /></td><td><input aria-label="테이블 Description" title={description} value={description} onChange={(event) => changeDraft(setDescription, event.target.value)} /></td><td><ControlledVocabularyInput client={client} kind="TERM" values={terms} label="테이블 Terms" onChange={(next) => changeDraft(setTerms, next)} /></td><td><ControlledVocabularyInput client={client} kind="TAG" values={tags} label="테이블 Tags" onChange={(next) => changeDraft(setTags, next)} /></td>
        </tr></tbody></table></div>
      </section>
      {clippedEditableSource && <p className="registration-description-error" role="alert">원본 메타데이터가 잘렸거나 stale 상태이므로 안전하게 수정할 수 없습니다.</p>}
      <section className="registration-v03-columns" aria-labelledby="manual-columns-title"><header><span aria-hidden="true" /><h3 id="manual-columns-title"><Columns3 size={14} aria-hidden="true" />Column Schema Specifications</h3><div className="registration-header-actions"><span>{asset.schema_fields_offset + 1}–{asset.schema_fields_offset + asset.schema_fields.length} / {asset.schema_fields_available}</span><button className="button button-quiet" type="button" onClick={() => moveFieldPage(onPreviousFieldPage)} disabled={loading || asset.schema_fields_offset === 0}>이전</button><button className="button button-quiet" type="button" onClick={() => moveFieldPage(onNextFieldPage)} disabled={loading || !asset.schema_fields_has_more}>다음</button></div></header><div className="dense-table-frame registration-columns-scroll"><table className="dense-table registration-columns-table registration-edit-table"><colgroup><col className="registration-column-name" /><col className="registration-column-type" /><col className="registration-column-logical-name" /><col className="registration-column-description" /><col className="registration-column-term" /><col className="registration-column-tag" /></colgroup><thead><tr><th>Column Name</th><th>Type</th><th>Logical Name</th><th>Description</th><th>Term</th><th>Tag</th></tr></thead><tbody>{columns.map((column) => <tr key={column.field_path}><td><code title={column.field_path}>{column.field_path}</code></td><td title={column.dataType || '—'}>{column.dataType || '—'}</td><td title={column.logicalName ?? 'DataHub label 미지정'}>{column.logicalName ?? '—'}</td><td><input aria-label={`${column.field_path} Description`} title={column.description} value={column.description} onChange={(event) => updateColumn(column.field_path, { description: event.target.value })} /></td><td><ControlledVocabularyInput client={client} kind="TERM" values={column.terms} label={`${column.field_path} Terms`} onChange={(next) => updateColumn(column.field_path, { terms: next })} /></td><td><ControlledVocabularyInput client={client} kind="TAG" values={column.tags} label={`${column.field_path} Tags`} onChange={(next) => updateColumn(column.field_path, { tags: next })} /></td></tr>)}{!columns.length && <tr><td colSpan={6} className="empty-cell">DataHub가 반환한 컬럼 메타데이터가 없습니다.</td></tr>}</tbody></table></div></section>
      <p className="registration-manual-handoff">SAVE는 변경 이력과 CSV 영수증을 저장한 뒤, 구성된 Airflow 적용 대기열에 제출합니다. 브라우저는 DataHub·MinIO·Airflow 자격증명에 접근하지 않습니다.</p>
      {submission && <div className="registration-description-success" role="status">제출 #{submission.serial_number}이 {submission.row_count}개 행으로 저장되었습니다. 상태: {submission.state}{pollingStopped && submission.state !== 'APPLIED' && submission.state !== 'FAILED' && <button className="button button-quiet" type="button" onClick={refreshCurrentSubmission}>상태 새로고침</button>}</div>}

      {report && <section className="registration-manual-report" aria-labelledby="manual-report-title"><header><h3 id="manual-report-title">제출 #{report.submission.serial_number} 적용 증거</h3></header>
        {report.attempts.map((attempt) => <div key={attempt.id} className="registration-manual-attempt"><strong>시도 {attempt.attempt_no}: {attempt.state}</strong>{attempt.failure_code && <span> · {attempt.failure_code}</span>}<ul>{attempt.aspects.map((aspect) => <li key={`${attempt.id}-${aspect.aspect_ordinal}`}>{aspect.aspect_ordinal}. {aspect.aspect_name} · {aspect.outcome} · {aspect.failure_code ?? (aspect.expected_hash && aspect.expected_hash === aspect.observed_hash ? '검증 일치' : '검증 불일치')}</li>)}</ul></div>)}
        {!report.attempts.length && <p>아직 실행 증거가 없습니다.</p>}
      </section>}
      <ErrorNotice error={error} />
    </div>}
    {!loading && asset && <footer className="registration-workbench-actions"><button className="button button-quiet" type="button" onClick={onClose}>선택 해제</button><button className="button button-primary" type="button" onClick={() => void save()} disabled={submitting || clippedEditableSource}><Save size={13} />{submitting ? 'SAVING…' : 'SAVE'}</button></footer>}
  </main>
}
