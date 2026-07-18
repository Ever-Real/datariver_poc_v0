import { useEffect, useMemo, useRef, useState } from 'react'
import { Columns3, Database, Save, ShieldCheck } from 'lucide-react'
import { newIdempotencyKey, type ApiClient } from '../../api/client'
import type {
  CatalogAssetDetail,
  CatalogVocabulary,
  ManualMetadataColumn,
  ManualMetadataSubmission,
} from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { schemaDescriptionFields } from './RegistrationColumnDescriptionEditor'

type VocabularyKind = 'TAG' | 'TERM' | 'DOMAIN'

interface EditableColumn extends ManualMetadataColumn {
  dataType: string
}

interface TokenInputProps {
  client: ApiClient
  kind: VocabularyKind
  values: string[]
  onChange: (values: string[]) => void
  label: string
  maxItems?: number
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

function TokenInput({ client, kind, values, onChange, label, maxItems = 100 }: TokenInputProps) {
  const [input, setInput] = useState('')
  const [options, setOptions] = useState<string[]>([])
  const [open, setOpen] = useState(false)
  const requestRef = useRef<AbortController | undefined>(undefined)

  useEffect(() => {
    if (!input.trim()) { setOptions([]); return }
    const controller = new AbortController()
    requestRef.current?.abort()
    requestRef.current = controller
    const timeout = window.setTimeout(() => {
      void client.request<CatalogVocabulary>(`/catalog/vocabulary?kind=${kind}&q=${encodeURIComponent(input)}&limit=12`, { signal: controller.signal })
        .then((result) => { if (!controller.signal.aborted) setOptions(result.items.filter((item) => !values.includes(item))) })
        .catch(() => { if (!controller.signal.aborted) setOptions([]) })
    }, 160)
    return () => { controller.abort(); window.clearTimeout(timeout) }
  }, [client, input, kind, values])

  const commit = (raw: string) => {
    const additions = raw.split(',').map((part) => part.trim()).filter(Boolean)
    if (!additions.length) return
    onChange(unique([...values, ...additions], maxItems))
    setInput('')
    setOptions([])
  }

  return <div className="registration-token-input" onBlur={() => window.setTimeout(() => setOpen(false), 120)}>
    <div className="registration-token-values" aria-label={label}>
      {values.map((value) => <span className="badge badge-soft" key={value}>{value}<button type="button" aria-label={`${value} 제거`} onMouseDown={(event) => event.preventDefault()} onClick={() => onChange(values.filter((item) => item !== value))}>×</button></span>)}
      {values.length < maxItems && <input value={input} onFocus={() => setOpen(true)} onChange={(event) => { setInput(event.target.value); setOpen(true) }} onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ',' || event.key === 'Tab') { if (input.trim()) { event.preventDefault(); commit(input) } }
      }} placeholder={values.length ? '추가…' : '입력 또는 검색…'} />}
    </div>
    {open && (options.length > 0 || input.trim()) && <div className="registration-token-menu" role="listbox" aria-label={`${label} 추천`}>
      {options.map((option) => <button type="button" role="option" key={option} onMouseDown={(event) => { event.preventDefault(); commit(option) }}>{option}</button>)}
      {input.trim() && !options.some((option) => option === input.trim()) && <button type="button" role="option" onMouseDown={(event) => { event.preventDefault(); commit(input) }}><strong>{input.trim()}</strong> 새 항목으로 추가</button>}
    </div>}
  </div>
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
        description: field.description ?? '',
        tags: unique(tokenValues(source?.globalTags ?? source?.tags, 'tags')),
        terms: unique(tokenValues(source?.glossaryTerms ?? source?.terms, 'terms')),
      }
    }))
    setSubmission(undefined)
    setError(undefined)
  }, [asset?.id, asset?.source_version, asset?.description, asset?.domain, asset?.tags, asset?.glossary_terms, asset?.schema_fields, fields])

  const updateColumn = (fieldPath: string, next: Partial<EditableColumn>) => {
    setColumns((current) => current.map((column) => column.field_path === fieldPath ? { ...column, ...next } : column))
    setSubmission(undefined)
  }

  const save = async () => {
    if (!asset || submitting || !columns.length) return
    setSubmitting(true)
    setError(undefined)
    try {
      const result = await client.request<ManualMetadataSubmission>('/registration/manual-submissions', {
        method: 'POST',
        idempotencyKey: newIdempotencyKey('manual-metadata'),
        body: JSON.stringify({
          asset_id: asset.id,
          source_version: asset.source_version,
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
      <section className="registration-v03-properties" aria-labelledby="manual-properties-title"><header><div><Database size={14} aria-hidden="true" /><h3 id="manual-properties-title">Table Properties</h3></div><div className="registration-header-actions"><button className="button button-primary" type="button" onClick={() => void save()} disabled={submitting}><Save size={13} />{submitting ? 'SAVING…' : 'SAVE'}</button><button className="button button-quiet" type="button" onClick={onClose}>선택 해제</button></div></header>
        <div className="dense-table-frame"><table className="dense-table registration-properties-table registration-edit-table"><thead><tr><th>Platform</th><th>Database</th><th>Schema</th><th>Table Name</th><th>Domain</th><th>Description</th><th>Term</th><th>Tag</th></tr></thead><tbody><tr>
          <td>{asset.platform ?? '—'}</td><td>{asset.database_name ?? '—'}</td><td>{asset.schema_name ?? '—'}</td><td><strong>{asset.name}</strong><small>{asset.asset_type}</small></td>
          <td><TokenInput client={client} kind="DOMAIN" values={domain} maxItems={1} label="테이블 Domain" onChange={setDomain} /></td><td><input aria-label="테이블 Description" value={description} onChange={(event) => { setDescription(event.target.value); setSubmission(undefined) }} /></td><td><TokenInput client={client} kind="TERM" values={terms} label="테이블 Terms" onChange={(next) => { setTerms(next); setSubmission(undefined) }} /></td><td><TokenInput client={client} kind="TAG" values={tags} label="테이블 Tags" onChange={(next) => { setTags(next); setSubmission(undefined) }} /></td>
        </tr></tbody></table></div>
      </section>
      <section className="registration-v03-columns" aria-labelledby="manual-columns-title"><header><span aria-hidden="true" /><h3 id="manual-columns-title"><Columns3 size={14} aria-hidden="true" />Column Schema Specifications</h3></header><div className="dense-table-frame"><table className="dense-table registration-columns-table registration-edit-table"><thead><tr><th>Column Name</th><th>Type</th><th>Logical Name / Description</th><th>Term</th><th>Tag</th></tr></thead><tbody>{columns.map((column) => <tr key={column.field_path}><td><code>{column.field_path}</code></td><td>{column.dataType || '—'}</td><td><input aria-label={`${column.field_path} Description`} value={column.description} onChange={(event) => updateColumn(column.field_path, { description: event.target.value })} /></td><td><TokenInput client={client} kind="TERM" values={column.terms} label={`${column.field_path} Terms`} onChange={(next) => updateColumn(column.field_path, { terms: next })} /></td><td><TokenInput client={client} kind="TAG" values={column.tags} label={`${column.field_path} Tags`} onChange={(next) => updateColumn(column.field_path, { tags: next })} /></td></tr>)}{!columns.length && <tr><td colSpan={5} className="empty-cell">DataHub가 반환한 컬럼 메타데이터가 없습니다.</td></tr>}</tbody></table></div></section>
      <p className="registration-manual-handoff">SAVE는 변경 이력과 CSV 영수증을 저장한 뒤, 구성된 Airflow 적용 대기열에 제출합니다. 브라우저는 DataHub·MinIO·Airflow 자격증명에 접근하지 않습니다.</p>
      {submission && <p className="registration-description-success" role="status">제출 #{submission.serial_number}이 {submission.row_count}개 행으로 저장되었습니다. 상태: {submission.state}</p>}
      <ErrorNotice error={error} />
    </div>}
  </main>
}
