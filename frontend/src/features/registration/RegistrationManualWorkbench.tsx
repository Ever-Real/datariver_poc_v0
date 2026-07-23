import { useEffect, useMemo, useState } from 'react'
import { Columns3, Database, Save, ShieldCheck } from 'lucide-react'
import { newIdempotencyKey, type ApiClient } from '../../api/client'
import type {
  CatalogAssetDetail,
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
export function RegistrationManualWorkbench({ client, asset, loading, onClose }: {
  client: ApiClient
  asset?: CatalogAssetDetail
  loading: boolean
  onClose: () => void
}) {
  const fields = useMemo(() => asset ? schemaDescriptionFields(asset.schema_fields) : [], [asset])
  const [description, setDescription] = useState('')
  const [domain, setDomain] = useState<string[]>([])
  const [tags, setTags] = useState<string[]>([])
  const [terms, setTerms] = useState<string[]>([])
  const [columns, setColumns] = useState<EditableColumn[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [submission, setSubmission] = useState<ManualMetadataSubmission>()
  const [error, setError] = useState<unknown>()
  const incompleteColumns = Boolean(
    asset
    && (
      asset.schema_fields_has_more
      || asset.schema_fields.length < asset.schema_fields_available
    )
  )
  const clippedEditableSource = Boolean(
    asset
    && (
      asset.description_truncated
      || asset.tags_truncated
      || asset.terms_truncated
      || asset.schema_fields_truncated
      || !asset.schema_fields_total_exact
      || asset.schema_fields.some((field) => (
        field.description_truncated === true
        || field.tags_truncated === true
        || field.terms_truncated === true
      ))
    )
  )

  useEffect(() => {
    setDescription(asset?.description ?? '')
    setDomain(asset?.domain ? [asset.domain] : [])
    setTags(unique(asset?.tags ?? []))
    setTerms(unique(asset ? tableTerms(asset) : []))
    setColumns(fields.map((field) => {
      const source = asset?.schema_fields.find((item) => item.fieldPath === field.fieldPath)
      return {
        field_path: field.fieldPath,
        dataType: field.dataType ?? '',
        logicalName: field.logicalName,
        description: field.description ?? '',
        tags: unique(tokenValues(source?.globalTags ?? source?.tags, 'tags')),
        terms: unique(tokenValues(source?.glossaryTerms ?? source?.terms, 'terms')),
      }
    }))
    setSubmission(undefined)
    setError(undefined)
  }, [asset, fields])

  const updateColumn = (fieldPath: string, next: Partial<EditableColumn>) => {
    setColumns((current) => current.map((column) => column.field_path === fieldPath ? { ...column, ...next } : column))
    setSubmission(undefined)
  }

  const save = async () => {
    if (
      !asset
      || submitting
      || !columns.length
      || incompleteColumns
      || clippedEditableSource
    ) return
    setSubmitting(true)
    setError(undefined)
    try {
      const result = await client.request<ManualMetadataSubmission>('/registration/manual-submissions', {
        method: 'POST',
        idempotencyKey: newIdempotencyKey('manual-metadata'),
        body: JSON.stringify({
          asset_id: asset.id,
          source_version: asset.projection_source_version,
          description,
          domain: domain[0] ?? null,
          tags,
          terms,
          columns: columns.map(({ field_path, description: columnDescription, tags: columnTags, terms: columnTerms }) => ({
            field_path, description: columnDescription, tags: columnTags, terms: columnTerms,
          })),
        }),
      })
      setSubmission(result)
    } catch (next) { setError(next) } finally { setSubmitting(false) }
  }

  return <main className="registration-editor-panel panel" aria-busy={loading || submitting}>
    <header><div><span className="eyebrow">Manual workbench</span><h2>Metadata Registration</h2></div><span className="badge badge-soft"><ShieldCheck size={11} />GOVERNED</span></header>
    {loading && <div className="registration-empty-editor">선택한 자산의 검증된 메타데이터를 불러오는 중입니다.</div>}
    {!loading && !asset && <div className="registration-empty-editor registration-v03-empty"><Database size={31} aria-hidden="true" /><strong>Resource Tree에서 테이블을 선택하세요.</strong><span>선택한 테이블의 실제 DataHub 속성과 컬럼 스키마를 같은 화면에서 편집합니다.</span></div>}
    {!loading && asset && <div className="registration-v03-body">
      <section className="registration-v03-properties" aria-labelledby="manual-properties-title"><header><div><Database size={14} aria-hidden="true" /><h3 id="manual-properties-title">Table Properties</h3></div><div className="registration-header-actions"><button className="button button-primary" type="button" onClick={() => void save()} disabled={submitting || incompleteColumns || clippedEditableSource}><Save size={13} />{submitting ? 'SAVING…' : 'SAVE'}</button><button className="button button-quiet" type="button" onClick={onClose}>선택 해제</button></div></header>
        <div className="dense-table-frame"><table className="dense-table registration-properties-table registration-edit-table"><colgroup><col className="registration-prop-platform" /><col className="registration-prop-database" /><col className="registration-prop-schema" /><col className="registration-prop-table" /><col className="registration-prop-domain" /><col className="registration-prop-description" /><col className="registration-prop-term" /><col className="registration-prop-tag" /></colgroup><thead><tr><th>Platform</th><th>Database</th><th>Schema</th><th>Table Name</th><th>Domain</th><th>Description</th><th>Term</th><th>Tag</th></tr></thead><tbody><tr>
          <td title={asset.platform ?? '—'}>{asset.platform ?? '—'}</td><td title={asset.database_name ?? '—'}>{asset.database_name ?? '—'}</td><td title={asset.schema_name ?? '—'}>{asset.schema_name ?? '—'}</td><td title={asset.name}><strong>{asset.name}</strong><small>{asset.asset_type}</small></td>
          <td><ControlledVocabularyInput client={client} kind="DOMAIN" values={domain} maxItems={1} label="테이블 Domain" onChange={setDomain} /></td><td><input aria-label="테이블 Description" title={description} value={description} onChange={(event) => { setDescription(event.target.value); setSubmission(undefined) }} /></td><td><ControlledVocabularyInput client={client} kind="TERM" values={terms} label="테이블 Terms" onChange={(next) => { setTerms(next); setSubmission(undefined) }} /></td><td><ControlledVocabularyInput client={client} kind="TAG" values={tags} label="테이블 Tags" onChange={(next) => { setTags(next); setSubmission(undefined) }} /></td>
        </tr></tbody></table></div>
      </section>
      {(incompleteColumns || clippedEditableSource) && <p className="registration-description-error" role="alert">{incompleteColumns ? '전체 컬럼 페이지를 불러오기 전에는 저장할 수 없습니다.' : '원본 메타데이터가 응답 상한으로 잘려 있어 안전하게 수정할 수 없습니다.'}</p>}
      <section className="registration-v03-columns" aria-labelledby="manual-columns-title"><header><span aria-hidden="true" /><h3 id="manual-columns-title"><Columns3 size={14} aria-hidden="true" />Column Schema Specifications</h3></header><div className="dense-table-frame"><table className="dense-table registration-columns-table registration-edit-table"><colgroup><col className="registration-column-name" /><col className="registration-column-type" /><col className="registration-column-logical-name" /><col className="registration-column-description" /><col className="registration-column-term" /><col className="registration-column-tag" /></colgroup><thead><tr><th>Column Name</th><th>Type</th><th>Logical Name</th><th>Description</th><th>Term</th><th>Tag</th></tr></thead><tbody>{columns.map((column) => <tr key={column.field_path}><td><code title={column.field_path}>{column.field_path}</code></td><td title={column.dataType || '—'}>{column.dataType || '—'}</td><td title={column.logicalName ?? 'DataHub label 미지정'}>{column.logicalName ?? '—'}</td><td><input aria-label={`${column.field_path} Description`} title={column.description} value={column.description} onChange={(event) => updateColumn(column.field_path, { description: event.target.value })} /></td><td><ControlledVocabularyInput client={client} kind="TERM" values={column.terms} label={`${column.field_path} Terms`} onChange={(next) => updateColumn(column.field_path, { terms: next })} /></td><td><ControlledVocabularyInput client={client} kind="TAG" values={column.tags} label={`${column.field_path} Tags`} onChange={(next) => updateColumn(column.field_path, { tags: next })} /></td></tr>)}{!columns.length && <tr><td colSpan={6} className="empty-cell">DataHub가 반환한 컬럼 메타데이터가 없습니다.</td></tr>}</tbody></table></div></section>
      <p className="registration-manual-handoff">SAVE는 변경 이력과 CSV 영수증을 저장한 뒤, 구성된 Airflow 적용 대기열에 제출합니다. 브라우저는 DataHub·MinIO·Airflow 자격증명에 접근하지 않습니다.</p>
      {submission && <p className="registration-description-success" role="status">제출 #{submission.serial_number}이 {submission.row_count}개 행으로 저장되었습니다. 상태: {submission.state}</p>}
      <ErrorNotice error={error} />
    </div>}
  </main>
}
