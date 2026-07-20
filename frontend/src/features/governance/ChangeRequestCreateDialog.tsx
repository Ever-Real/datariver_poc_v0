import { useEffect, useMemo, useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import { ApiError, newIdempotencyKey, type ApiClient } from '../../api/client'
import type { CatalogAsset, CatalogAssetDetail, CatalogSearch, ChangeRequestRecord } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { ControlledVocabularyInput } from '../../components/common/ControlledVocabularyInput'
import { Dialog } from '../../components/common/Dialog'
import { schemaDescriptionFields } from '../registration/RegistrationColumnDescriptionEditor'

const MAXIMUM_ATTACHMENT_BYTES = 10 * 1024 * 1024

type ColumnDraft = {
  field_path: string
  data_type: string
  description: string
  requested_change: string
  tags: string[]
  terms: string[]
}
type ExistingTarget = {
  kind: 'EXISTING'
  asset: CatalogAssetDetail
  description: string
  requested_change: string
  tags: string[]
  terms: string[]
  columns: ColumnDraft[]
}
type ManualTarget = {
  kind: 'MANUAL'
  database_name: string
  schema_name: string
  table_name: string
  owner: string
  description: string
  requested_change: string
  tags: string[]
  terms: string[]
  columns: ColumnDraft[]
}
type TargetDraft = ExistingTarget | ManualTarget

function defaultDueDate(): string {
  const value = new Date()
  value.setDate(value.getDate() + 14)
  return value.toISOString().slice(0, 10)
}

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

function unique(values: string[]): string[] {
  return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean))).slice(0, 100)
}

function assetLabel(asset: CatalogAsset): string {
  return [asset.platform, asset.database_name, asset.schema_name, asset.name]
    .filter((value): value is string => Boolean(value))
    .join(' · ')
}

function tokens(value: unknown, collection: 'tags' | 'terms'): string[] {
  if (!value || typeof value !== 'object') return []
  const nested = (value as Record<string, unknown>)[collection]
  if (!Array.isArray(nested)) return []
  const key = collection === 'tags' ? 'tag' : 'term'
  return nested.flatMap((entry) => {
    const candidate = entry && typeof entry === 'object'
      ? (entry as Record<string, unknown>)[key]
      : undefined
    if (typeof candidate === 'string') return [candidate]
    if (candidate && typeof candidate === 'object') {
      const document = candidate as Record<string, unknown>
      const label = document.name ?? document.urn
      return typeof label === 'string' ? [label] : []
    }
    return []
  })
}

function termValues(asset: CatalogAssetDetail): string[] {
  return asset.glossary_terms.flatMap((value) => tokens({ terms: [value] }, 'terms'))
}

export function ChangeRequestCreateDialog({
  open,
  client,
  onClose,
  onCreated,
}: {
  open: boolean
  client: ApiClient
  onClose: () => void
  onCreated: (changeRequest: ChangeRequestRecord) => void
}) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<CatalogAsset[]>([])
  const [searching, setSearching] = useState(false)
  const [targets, setTargets] = useState<TargetDraft[]>([])
  const [title, setTitle] = useState('')
  const [systemName, setSystemName] = useState('')
  const [requestDate, setRequestDate] = useState(today)
  const [department, setDepartment] = useState('')
  const [requestSummary, setRequestSummary] = useState('')
  const [dueDate, setDueDate] = useState(defaultDueDate)
  const [priority, setPriority] = useState<'LOW' | 'NORMAL' | 'HIGH' | 'CRITICAL'>('NORMAL')
  const [urgency, setUrgency] = useState<'NORMAL' | 'URGENT' | 'EMERGENCY'>('NORMAL')
  const [security, setSecurity] = useState<'PUBLIC' | 'INTERNAL' | 'CONFIDENTIAL' | 'RESTRICTED'>('INTERNAL')
  const [files, setFiles] = useState<File[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [created, setCreated] = useState<ChangeRequestRecord>()
  const [error, setError] = useState<unknown>()
  const searchController = useRef<AbortController | undefined>(undefined)
  const submitController = useRef<AbortController | undefined>(undefined)

  useEffect(() => {
    if (!open || query.trim().length < 2) {
      setResults([])
      setSearching(false)
      return
    }
    const controller = new AbortController()
    searchController.current?.abort()
    searchController.current = controller
    const timer = window.setTimeout(() => {
      setSearching(true)
      void client.request<CatalogSearch>(
        `/catalog/assets?q=${encodeURIComponent(query.trim())}&limit=12`,
        { signal: controller.signal },
      )
        .then((value) => { if (!controller.signal.aborted) setResults(value.items) })
        .catch((next) => { if (!controller.signal.aborted) setError(next) })
        .finally(() => { if (!controller.signal.aborted) setSearching(false) })
    }, 220)
    return () => { controller.abort(); window.clearTimeout(timer) }
  }, [client, open, query])

  useEffect(() => () => {
    searchController.current?.abort()
    submitController.current?.abort()
  }, [])

  const reset = () => {
    searchController.current?.abort()
    submitController.current?.abort()
    setQuery('')
    setResults([])
    setTargets([])
    setTitle('')
    setSystemName('')
    setRequestDate(today())
    setDepartment('')
    setRequestSummary('')
    setDueDate(defaultDueDate())
    setPriority('NORMAL')
    setUrgency('NORMAL')
    setSecurity('INTERNAL')
    setFiles([])
    setCreated(undefined)
    setSubmitting(false)
    setError(undefined)
  }

  const requestClose = () => {
    if (submitting) return
    reset()
    onClose()
  }

  const addExisting = (summary: CatalogAsset) => {
    if (targets.some((target) => target.kind === 'EXISTING' && target.asset.id === summary.id)) {
      setError(new Error('이미 추가한 테이블입니다.'))
      return
    }
    const controller = new AbortController()
    setError(undefined)
    void client.request<CatalogAssetDetail>(`/catalog/assets/${summary.id}`, { signal: controller.signal })
      .then((asset) => {
        if (controller.signal.aborted) return
        setTargets((current) => [...current, {
          kind: 'EXISTING',
          asset,
          description: asset.description ?? '',
          requested_change: '',
          tags: unique(asset.tags ?? []),
          terms: unique(termValues(asset)),
          columns: [],
        }])
        setQuery('')
        setResults([])
        if (!systemName.trim() && asset.platform) setSystemName(asset.platform)
      })
      .catch((next) => { if (!controller.signal.aborted) setError(next) })
  }

  const addManual = () => setTargets((current) => [...current, {
    kind: 'MANUAL', database_name: '', schema_name: '', table_name: '', owner: '', description: '', requested_change: '', tags: [], terms: [], columns: [],
  }])
  const updateTarget = (index: number, patch: Partial<TargetDraft>) => {
    setTargets((current) => current.map((target, targetIndex) => targetIndex === index
      ? { ...target, ...patch } as TargetDraft
      : target))
  }
  const updateColumn = (targetIndex: number, columnIndex: number, patch: Partial<ColumnDraft>) => {
    setTargets((current) => current.map((target, index) => index !== targetIndex ? target : {
      ...target,
      columns: target.columns.map((column, itemIndex) => itemIndex === columnIndex ? { ...column, ...patch } : column),
    }))
  }
  const fieldOptions = (target: ExistingTarget) => schemaDescriptionFields(target.asset.schema_fields)
    .filter((field) => !target.columns.some((column) => column.field_path === field.fieldPath))
  const addExistingColumn = (targetIndex: number, fieldPath: string) => {
    const target = targets[targetIndex]
    if (!fieldPath || !target || target.kind !== 'EXISTING') return
    const field = schemaDescriptionFields(target.asset.schema_fields).find((value) => value.fieldPath === fieldPath)
    const source = target.asset.schema_fields.find((value) => value.fieldPath === fieldPath)
    if (!field) return
    updateTarget(targetIndex, {
      columns: [...target.columns, {
        field_path: field.fieldPath,
        data_type: field.dataType ?? '',
        description: field.description ?? '',
        requested_change: '',
        tags: unique(tokens((source as Record<string, unknown>)?.globalTags ?? (source as Record<string, unknown>)?.tags, 'tags')),
        terms: unique(tokens((source as Record<string, unknown>)?.glossaryTerms ?? (source as Record<string, unknown>)?.terms, 'terms')),
      }],
    })
  }
  const addManualColumn = (targetIndex: number) => {
    const target = targets[targetIndex]
    if (target) updateTarget(targetIndex, {
      columns: [...target.columns, { field_path: '', data_type: '', description: '', requested_change: '', tags: [], terms: [] }],
    })
  }
  const removeColumn = (targetIndex: number, columnIndex: number) => {
    const target = targets[targetIndex]
    if (target) updateTarget(targetIndex, { columns: target.columns.filter((_, index) => index !== columnIndex) })
  }
  const addFiles = (event: ChangeEvent<HTMLInputElement>) => {
    const next = Array.from(event.target.files ?? [])
    if (next.some((file) => file.size > MAXIMUM_ATTACHMENT_BYTES)) {
      setError(new Error('첨부파일은 파일당 10 MiB 이하만 등록할 수 있습니다.'))
      event.target.value = ''
      return
    }
    setFiles((current) => [...current, ...next])
    event.target.value = ''
  }
  const canSubmit = title.trim() && systemName.trim() && requestSummary.trim() && targets.length > 0
    && targets.every((target) => target.kind === 'EXISTING' || target.table_name.trim())
  const targetPayload = (target: TargetDraft) => target.kind === 'EXISTING'
    ? { kind: 'EXISTING', asset_id: target.asset.id, description: target.description, requested_change: target.requested_change, tags: target.tags, terms: target.terms, columns: target.columns }
    : { kind: 'MANUAL', database_name: target.database_name, schema_name: target.schema_name, table_name: target.table_name, owner: target.owner, description: target.description, requested_change: target.requested_change, tags: target.tags, terms: target.terms, columns: target.columns }
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!canSubmit || submitting || created) return
    const controller = new AbortController()
    submitController.current?.abort()
    submitController.current = controller
    setSubmitting(true)
    setError(undefined)
    try {
      const changeRequest = await client.request<ChangeRequestRecord>('/change-requests/intake', {
        method: 'POST',
        signal: controller.signal,
        idempotencyKey: newIdempotencyKey('change-request-intake'),
        body: JSON.stringify({
          title: title.trim(), system_name: systemName.trim(), request_date: requestDate || null,
          request_department: department.trim(), request_reason: requestSummary.trim(), request_content: '',
          requested_due_date: dueDate || null, priority, urgency, security_level: security,
          targets: targets.map(targetPayload),
        }),
      })
      for (const file of files) {
        const body = new FormData()
        body.set('kind', 'REQUEST')
        body.set('file', file)
        await client.request(`/change-requests/${changeRequest.id}/attachments`, {
          method: 'POST', signal: controller.signal, body,
        })
      }
      if (!controller.signal.aborted) {
        setCreated(changeRequest)
        onCreated(changeRequest)
      }
    } catch (next) {
      if (!controller.signal.aborted) {
        setError(next instanceof ApiError && next.problem.status === 412
          ? new Error('대상 원본이 변경되었습니다. 다시 선택 후 재시도하세요.')
          : next)
      }
    } finally {
      if (!controller.signal.aborted) setSubmitting(false)
    }
  }
  const selectedFieldOptions = useMemo(() => targets.map((target) => target.kind === 'EXISTING' ? fieldOptions(target) : []), [targets])

  return <Dialog
    description="기존 테이블은 서버가 현재 DataHub 원본을 재검증하고, 신규 테이블은 감사 가능한 제안으로 기록합니다."
    footer={<><button className="button button-secondary" disabled={submitting} onClick={requestClose} type="button">닫기</button>{!created && <button className="button" disabled={submitting || !canSubmit} form="change-request-create-form" type="submit">{submitting ? '등록 중…' : '신규 CR 등록'}</button>}</>}
    onRequestClose={requestClose}
    open={open}
    size="workspace"
    title="신규 CR 신청"
  >
    <form className="governance-create-form governance-intake-form" id="change-request-create-form" onSubmit={(event) => void submit(event)}>
      {created ? <div className="notice" role="status"><strong>{created.number}</strong> 변경 요청을 등록했습니다. 개발 담당자는 검토, 변경/TEST, 최종검토 단계를 진행할 수 있습니다.</div> : <>
        <fieldset>
          <legend>CR 기본 정보</legend>
          <div className="governance-create-grid">
            <label className="wide">CR명<input maxLength={500} onChange={(event) => setTitle(event.target.value)} required value={title} /></label>
            <label>관련 시스템명<input maxLength={100} onChange={(event) => setSystemName(event.target.value)} required value={systemName} /></label>
            <label>요청일자<input onChange={(event) => setRequestDate(event.target.value)} type="date" value={requestDate} /></label>
            <label>요청부서<input maxLength={500} onChange={(event) => setDepartment(event.target.value)} value={department} /></label>
            <label>요청 납기<input onChange={(event) => setDueDate(event.target.value)} type="date" value={dueDate} /></label>
            <label>중요도<select onChange={(event) => setPriority(event.target.value as typeof priority)} value={priority}><option value="LOW">낮음</option><option value="NORMAL">보통</option><option value="HIGH">높음</option><option value="CRITICAL">최우선</option></select></label>
            <label>긴급도<select onChange={(event) => setUrgency(event.target.value as typeof urgency)} value={urgency}><option value="NORMAL">일반</option><option value="URGENT">긴급</option><option value="EMERGENCY">비상</option></select></label>
            <label>보안등급<select onChange={(event) => setSecurity(event.target.value as typeof security)} value={security}><option value="PUBLIC">Public</option><option value="INTERNAL">Internal</option><option value="CONFIDENTIAL">Confidential</option><option value="RESTRICTED">Restricted</option></select></label>
            <label className="wide">요청 사유 / 요청 내용<textarea maxLength={10_000} onChange={(event) => setRequestSummary(event.target.value)} required value={requestSummary} /></label>
          </div>
        </fieldset>
        <fieldset>
          <legend>관련 테이블</legend>
          <div className="governance-intake-search"><label>기존 테이블 검색<input minLength={2} onChange={(event) => setQuery(event.target.value)} placeholder="테이블명, 스키마 또는 설명을 두 글자 이상 입력" value={query} /></label><button className="button button-secondary" onClick={addManual} type="button">신규 테이블 추가</button></div>
          {searching && <p className="muted">실데이터를 검색하는 중입니다.</p>}
          {results.length > 0 && <ul className="governance-create-search-results">{results.map((result) => <li key={result.id}><button onClick={() => addExisting(result)} type="button"><strong>{result.name}</strong><span>{assetLabel(result)}</span></button></li>)}</ul>}
          <div className="governance-intake-targets">
            {targets.map((target, targetIndex) => <section className="governance-intake-target" key={target.kind === 'EXISTING' ? target.asset.id : `manual-${targetIndex}`}>
              <header className="governance-intake-target-header"><div className="governance-intake-identity"><span className="badge">테이블</span><strong title={target.kind === 'EXISTING' ? target.asset.name : target.table_name}>{target.kind === 'EXISTING' ? target.asset.name : target.table_name || '테이블명 입력'}</strong><small>{target.kind === 'EXISTING' ? '기존' : '신규'}</small></div><button className="button button-secondary" onClick={() => setTargets((current) => current.filter((_, index) => index !== targetIndex))} type="button">삭제</button></header>
              {target.kind === 'EXISTING' ? <div className="governance-intake-grid">
                <label>Schema<input readOnly title={target.asset.schema_name ?? ''} value={target.asset.schema_name ?? ''} /></label><label>Table<input readOnly title={target.asset.name} value={target.asset.name} /></label><label>Owner<input readOnly title={target.asset.owner ?? ''} value={target.asset.owner ?? ''} /></label>
                <label>테이블 설명<input className="governance-intake-text-input" onChange={(event) => updateTarget(targetIndex, { description: event.target.value })} title={target.description} value={target.description} /></label>
                <label>Terms<ControlledVocabularyInput client={client} kind="TERM" label={`${target.asset.name} Terms`} onChange={(values) => updateTarget(targetIndex, { terms: values })} values={target.terms} /></label>
                <label>Tags<ControlledVocabularyInput client={client} kind="TAG" label={`${target.asset.name} Tags`} onChange={(values) => updateTarget(targetIndex, { tags: values })} values={target.tags} /></label>
                <label>요청/변경내용<input className="governance-intake-text-input" onChange={(event) => updateTarget(targetIndex, { requested_change: event.target.value })} title={target.requested_change} value={target.requested_change} /></label>
                <label className="governance-intake-column-add">+ 컬럼 추가<select aria-label={`${target.asset.name} 컬럼 추가`} onChange={(event) => addExistingColumn(targetIndex, event.target.value)} value=""><option value="">컬럼 선택</option>{(selectedFieldOptions[targetIndex] ?? []).map((field) => <option key={field.fieldPath} value={field.fieldPath}>{field.fieldPath} · {field.dataType ?? ''}</option>)}</select></label>
              </div> : <div className="governance-intake-grid">
                <label>Schema<input onChange={(event) => updateTarget(targetIndex, { schema_name: event.target.value })} title={target.schema_name} value={target.schema_name} /></label><label>테이블명<input onChange={(event) => updateTarget(targetIndex, { table_name: event.target.value })} required title={target.table_name} value={target.table_name} /></label><label>Owner<input onChange={(event) => updateTarget(targetIndex, { owner: event.target.value })} title={target.owner} value={target.owner} /></label>
                <label>테이블 설명<input className="governance-intake-text-input" onChange={(event) => updateTarget(targetIndex, { description: event.target.value })} title={target.description} value={target.description} /></label>
                <label>Terms<ControlledVocabularyInput client={client} kind="TERM" label={`신규 ${targetIndex + 1} Terms`} onChange={(values) => updateTarget(targetIndex, { terms: values })} values={target.terms} /></label>
                <label>Tags<ControlledVocabularyInput client={client} kind="TAG" label={`신규 ${targetIndex + 1} Tags`} onChange={(values) => updateTarget(targetIndex, { tags: values })} values={target.tags} /></label>
                <label>요청/변경내용<input className="governance-intake-text-input" onChange={(event) => updateTarget(targetIndex, { requested_change: event.target.value })} title={target.requested_change} value={target.requested_change} /></label>
                <div className="governance-intake-column-add"><span>+ 컬럼 추가</span><button className="button button-secondary" onClick={() => addManualColumn(targetIndex)} type="button">추가</button></div>
              </div>}
              <div className="governance-intake-columns">
                {target.columns.length > 0 && <div className="dense-table-frame governance-intake-columns-frame"><table className="dense-table governance-intake-columns-table"><thead><tr><th aria-hidden="true" className="governance-column-spacer" /><th>항목</th><th>Type</th><th>Description</th><th>Term</th><th>Tag</th><th>요청/변경내용</th><th>관리</th></tr></thead><tbody>{target.columns.map((column, columnIndex) => <tr key={`${column.field_path}-${columnIndex}`}>
                  <td aria-hidden="true" className="governance-column-spacer" /><td className="governance-column-name-cell"><span aria-hidden="true" className="governance-column-branch" /><div className="governance-column-identity"><span className="badge">컬럼</span>{target.kind === 'EXISTING' ? <code title={column.field_path}>{column.field_path}</code> : <input className="governance-intake-text-input" onChange={(event) => updateColumn(targetIndex, columnIndex, { field_path: event.target.value })} title={column.field_path} value={column.field_path} />}<small>{target.kind === 'EXISTING' ? '변경' : '신규'}</small></div></td>
                  <td>{target.kind === 'EXISTING' ? <span title={column.data_type || '—'}>{column.data_type || '—'}</span> : <input className="governance-intake-text-input" onChange={(event) => updateColumn(targetIndex, columnIndex, { data_type: event.target.value })} title={column.data_type} value={column.data_type} />}</td>
                  <td><input className="governance-intake-text-input" onChange={(event) => updateColumn(targetIndex, columnIndex, { description: event.target.value })} title={column.description} value={column.description} /></td>
                  <td><ControlledVocabularyInput client={client} kind="TERM" label={`${column.field_path || '신규'} Terms`} onChange={(values) => updateColumn(targetIndex, columnIndex, { terms: values })} values={column.terms} /></td>
                  <td><ControlledVocabularyInput client={client} kind="TAG" label={`${column.field_path || '신규'} Tags`} onChange={(values) => updateColumn(targetIndex, columnIndex, { tags: values })} values={column.tags} /></td>
                  <td><input className="governance-intake-text-input" onChange={(event) => updateColumn(targetIndex, columnIndex, { requested_change: event.target.value })} title={column.requested_change} value={column.requested_change} /></td>
                  <td><button className="button button-secondary" onClick={() => removeColumn(targetIndex, columnIndex)} type="button">삭제</button></td>
                </tr>)}</tbody></table></div>}
              </div>
            </section>)}
          </div>
          {!targets.length && <p className="muted">기존 테이블을 검색해 선택하거나 신규 테이블을 추가하세요.</p>}
        </fieldset>
        <fieldset><legend>요청 첨부파일</legend><label className="governance-create-file">복수 파일 첨부 (파일당 최대 10 MiB)<input multiple onChange={addFiles} type="file" /></label>{files.length > 0 && <ul className="governance-create-files">{files.map((file, index) => <li key={`${file.name}-${file.lastModified}-${index}`}><span>{file.name} · {Math.ceil(file.size / 1024).toLocaleString()} KiB</span><button className="button button-secondary" onClick={() => setFiles((current) => current.filter((_, itemIndex) => itemIndex !== index))} type="button">제거</button></li>)}</ul>}</fieldset>
      </>}
      <ErrorNotice error={error} />
    </form>
  </Dialog>
}
