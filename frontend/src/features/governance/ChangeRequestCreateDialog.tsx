import { Plus, Trash2, X } from 'lucide-react'
import { Fragment, useEffect, useMemo, useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import { ApiError, newIdempotencyKey, type ApiClient } from '../../api/client'
import type { CatalogAsset, CatalogAssetDetail, CatalogSearch, ChangeRequestRecord } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { Dialog } from '../../components/common/Dialog'
import { schemaDescriptionFields } from '../registration/RegistrationColumnDescriptionEditor'
import {
  attachmentSelectionError,
  uploadAndFinalizeAttachment,
} from './attachmentUploads'

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
  requesterName,
  requesterEmail,
  onClose,
  onCreated,
}: {
  open: boolean
  client: ApiClient
  requesterName: string
  requesterEmail?: string
  onClose: () => void
  onCreated: (changeRequest: ChangeRequestRecord) => void
}) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<CatalogAsset[]>([])
  const [searching, setSearching] = useState(false)
  const [targets, setTargets] = useState<TargetDraft[]>([])
  const [title, setTitle] = useState('')
  const [systemId, setSystemId] = useState('')
  const [systems, setSystems] = useState<Array<{ id: string; code: string; name: string }>>([])
  const [requestDate, setRequestDate] = useState(today)
  const [department, setDepartment] = useState('')
  const [requestSummary, setRequestSummary] = useState('')
  const [requestContent, setRequestContent] = useState('')
  const [dueDate, setDueDate] = useState(defaultDueDate)
  const [priority, setPriority] = useState<'LOW' | 'NORMAL' | 'HIGH' | 'CRITICAL'>('NORMAL')
  const [urgency, setUrgency] = useState<'NORMAL' | 'URGENT' | 'EMERGENCY'>('NORMAL')
  const [security, setSecurity] = useState<'PUBLIC' | 'INTERNAL' | 'CONFIDENTIAL' | 'RESTRICTED'>('INTERNAL')
  const [files, setFiles] = useState<File[]>([])
  const [systemsLoading, setSystemsLoading] = useState(false)
  const [submissionAttempted, setSubmissionAttempted] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [created, setCreated] = useState<ChangeRequestRecord>()
  const [error, setError] = useState<unknown>()
  const searchController = useRef<AbortController | undefined>(undefined)
  const detailController = useRef<AbortController | undefined>(undefined)
  const submitController = useRef<AbortController | undefined>(undefined)
  const registeredRequest = useRef<ChangeRequestRecord | undefined>(undefined)
  const registrationReported = useRef(false)

  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    setSystemsLoading(true)
    void client.request<{ items: Array<{ id: string; code: string; name: string }> }>(
      '/change-requests/systems', { signal: controller.signal },
    ).then((value) => {
      if (controller.signal.aborted) return
      setSystems(value.items)
      setSystemId((current) => current || value.items[0]?.id || '')
    }).catch((next) => { if (!controller.signal.aborted) setError(next) })
      .finally(() => { if (!controller.signal.aborted) setSystemsLoading(false) })
    return () => controller.abort()
  }, [client, open])

  useEffect(() => {
    if (!open || !systemId || query.trim().length < 2) {
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
        `/change-requests/targets?system_id=${encodeURIComponent(systemId)}&q=${encodeURIComponent(query.trim())}&limit=12`,
        { signal: controller.signal },
      )
        .then((value) => { if (!controller.signal.aborted) setResults(value.items) })
        .catch((next) => { if (!controller.signal.aborted) setError(next) })
        .finally(() => { if (!controller.signal.aborted) setSearching(false) })
    }, 220)
    return () => { controller.abort(); window.clearTimeout(timer) }
  }, [client, open, query, systemId])

  useEffect(() => () => {
    searchController.current?.abort()
    detailController.current?.abort()
    submitController.current?.abort()
  }, [])

  const reset = () => {
    searchController.current?.abort()
    detailController.current?.abort()
    submitController.current?.abort()
    setQuery('')
    setResults([])
    setTargets([])
    setTitle('')
    setSystemId('')
    setSystems([])
    setRequestDate(today())
    setDepartment('')
    setRequestSummary('')
    setRequestContent('')
    setDueDate(defaultDueDate())
    setPriority('NORMAL')
    setUrgency('NORMAL')
    setSecurity('INTERNAL')
    setFiles([])
    setSystemsLoading(false)
    setSubmissionAttempted(false)
    setCreated(undefined)
    setSubmitting(false)
    setError(undefined)
    registeredRequest.current = undefined
    registrationReported.current = false
  }

  const requestClose = () => {
    const registered = registeredRequest.current
    const mustReport = Boolean(registered) && !registrationReported.current
    reset()
    if (registered && mustReport) onCreated(registered)
    onClose()
  }

  const addExisting = (summary: CatalogAsset) => {
    if (targets.some((target) => target.kind === 'EXISTING' && target.asset.id === summary.id)) {
      setError(new Error('이미 추가한 테이블입니다.'))
      return
    }
    const controller = new AbortController()
    detailController.current?.abort()
    detailController.current = controller
    setError(undefined)
    void client.request<CatalogAssetDetail>(
      `/change-requests/targets/${summary.id}?system_id=${encodeURIComponent(systemId)}`,
      { signal: controller.signal },
    )
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
      })
      .catch((next) => { if (!controller.signal.aborted) setError(next) })
  }

  const changeSystem = (nextSystemId: string) => {
    searchController.current?.abort()
    detailController.current?.abort()
    setSystemId(nextSystemId)
    setQuery('')
    setResults([])
    setTargets([])
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
    const combined = [...files, ...next]
    const selectionError = attachmentSelectionError(combined)
    if (selectionError) {
      setError(selectionError)
      event.target.value = ''
      return
    }
    setFiles(combined)
    event.target.value = ''
  }
  const missingSubmitRequirements = [
    !title.trim() ? '변경요청 제목' : '',
    !systemId ? '관련 시스템' : '',
    !requestSummary.trim() ? '요청사유' : '',
    targets.length === 0 ? '변경 대상 테이블' : '',
    targets.some((target) => target.kind === 'MANUAL' && !target.table_name.trim())
      ? '신규 테이블명'
      : '',
    targets.some((target) => target.columns.some((column) => !column.field_path.trim()))
      ? '추가한 컬럼명'
      : '',
  ].filter(Boolean)
  const canSubmit = !systemsLoading && missingSubmitRequirements.length === 0
  const submissionHint = !submissionAttempted || canSubmit
    ? ''
    : systemsLoading
      ? '관련 시스템을 불러오는 중입니다.'
      : systems.length === 0 && !systemId
        ? '등록 가능한 활성 시스템이 없습니다. 관리자에게 시스템 등록 또는 접근 범위 할당을 요청하세요.'
        : `필수 항목을 입력하세요: ${missingSubmitRequirements.join(', ')}`
  const targetPayload = (target: TargetDraft) => target.kind === 'EXISTING'
    ? { kind: 'EXISTING', asset_id: target.asset.id, description: target.description, requested_change: target.requested_change, tags: target.tags, terms: target.terms, columns: target.columns }
    : { kind: 'MANUAL', database_name: target.database_name, schema_name: target.schema_name, table_name: target.table_name, owner: target.owner, description: target.description, requested_change: target.requested_change, tags: target.tags, terms: target.terms, columns: target.columns }
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setSubmissionAttempted(true)
    if (!canSubmit || submitting || created) return
    const controller = new AbortController()
    submitController.current?.abort()
    submitController.current = controller
    setSubmitting(true)
    setError(undefined)
    let changeRequest: ChangeRequestRecord | undefined
    try {
      changeRequest = await client.request<ChangeRequestRecord>('/change-requests/intake', {
        method: 'POST',
        signal: controller.signal,
        idempotencyKey: newIdempotencyKey('change-request-intake'),
        body: JSON.stringify({
          title: title.trim(), system_id: systemId, request_date: requestDate || null,
          request_department: department.trim(), request_reason: requestSummary.trim(), request_content: requestContent.trim(),
          requested_due_date: dueDate || null, priority, urgency, security_level: security,
          targets: targets.map(targetPayload),
        }),
      })
      if (!controller.signal.aborted) {
        registeredRequest.current = changeRequest
        setCreated(changeRequest)
      }
      for (const file of files) {
        await uploadAndFinalizeAttachment(
          client,
          changeRequest.id,
          'REQUEST',
          file,
          { signal: controller.signal },
        )
      }
      if (!controller.signal.aborted) {
        registrationReported.current = true
        onCreated(changeRequest)
      }
    } catch (next) {
      if (!controller.signal.aborted) {
        if (changeRequest) {
          const detail = next instanceof Error ? next.message : '알 수 없는 오류'
          setError(new Error(
            `${changeRequest.number} 변경 요청은 등록되었지만 첨부파일 처리가 완료되지 않았습니다. `
              + `상세 화면에서 상태를 다시 확인하세요. (${detail})`,
          ))
        } else {
          setError(next instanceof ApiError && next.problem.status === 412
            ? new Error('대상 원본이 변경되었습니다. 다시 선택 후 재시도하세요.')
            : next)
        }
      }
    } finally {
      if (!controller.signal.aborted) setSubmitting(false)
    }
  }
  const selectedFieldOptions = useMemo(() => targets.map((target) => target.kind === 'EXISTING' ? fieldOptions(target) : []), [targets])
  const downloadTemplate = () => {
    const template = [
      'record_type,table_name,column_name,schema_name,logical_name,remarks,data_type',
      'TABLE,,,,,,',
      'COLUMN,,,,,,',
    ].join('\n')
    const url = URL.createObjectURL(new Blob([template], { type: 'text/csv;charset=utf-8' }))
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = 'change-request-target-template.csv'
    anchor.click()
    URL.revokeObjectURL(url)
  }

  return <Dialog
    description="기존 테이블은 서버가 현재 DataHub 원본을 재검증하고, 신규 테이블은 감사 가능한 제안으로 기록합니다."
    footer={<>
      {submissionHint && <span className="governance-create-submit-hint" role="status">{submissionHint}</span>}
      <button className="button button-secondary" onClick={requestClose} type="button">취소</button>
      {!created && <button className="button" disabled={submitting} form="change-request-create-form" type="submit">{submitting ? '제출 중…' : 'CR 제출'}</button>}
    </>}
    onRequestClose={requestClose}
    open={open}
    size="workspace"
    title="신규 CR 신청"
  >
    <form className="governance-create-form governance-intake-form" id="change-request-create-form" noValidate onSubmit={(event) => void submit(event)}>
      {created ? <div className="notice" role="status"><strong>{created.number}</strong> 변경 요청을 등록했습니다. 개발 담당자는 검토, 변경/TEST, 최종검토 단계를 진행할 수 있습니다.</div> : <>
        <fieldset>
          <legend>CR 기본 정보</legend>
          <div className="governance-create-grid">
            <label className="wide">변경요청 제목<input maxLength={500} onChange={(event) => setTitle(event.target.value)} placeholder="예: A 테이블 컬럼 추가 및 용어 표준화" required value={title} /></label>
            <label>요청자<input readOnly title={requesterEmail ?? requesterName} value={requesterEmail ? `${requesterName} · ${requesterEmail}` : requesterName} /></label>
            <label>관련 시스템<select onChange={(event) => changeSystem(event.target.value)} required value={systemId}><option value="">시스템 선택</option>{systems.map((system) => <option key={system.id} value={system.id}>{system.name} · {system.code}</option>)}</select></label>
            <label>요청일자<input onChange={(event) => setRequestDate(event.target.value)} type="date" value={requestDate} /></label>
            <label>요청부서<input maxLength={500} onChange={(event) => setDepartment(event.target.value)} placeholder="인증 프로필에 부서 정보가 없어 직접 입력" value={department} /></label>
            <label>요청 납기<input onChange={(event) => setDueDate(event.target.value)} type="date" value={dueDate} /></label>
            <label>중요도<select onChange={(event) => setPriority(event.target.value as typeof priority)} value={priority}><option value="LOW">낮음</option><option value="NORMAL">보통</option><option value="HIGH">높음</option><option value="CRITICAL">최우선</option></select></label>
            <label>긴급도<select onChange={(event) => setUrgency(event.target.value as typeof urgency)} value={urgency}><option value="NORMAL">일반</option><option value="URGENT">긴급</option><option value="EMERGENCY">비상</option></select></label>
            <label>보안등급<select onChange={(event) => setSecurity(event.target.value as typeof security)} value={security}><option value="PUBLIC">Public</option><option value="INTERNAL">Internal</option><option value="CONFIDENTIAL">Confidential</option><option value="RESTRICTED">Restricted</option></select></label>
            <label className="wide">요청내용<textarea className="min-h-24 resize-y" maxLength={10_000} onChange={(event) => setRequestContent(event.target.value)} value={requestContent} /></label>
            <label className="wide">요청사유<textarea className="governance-request-reason" maxLength={10_000} onChange={(event) => setRequestSummary(event.target.value)} placeholder="예: B 데이터 연동을 위한 스키마 확장" required rows={1} value={requestSummary} /></label>
          </div>
        </fieldset>
        <fieldset>
          <legend>TARGET SELECTION</legend>
          <div className="governance-target-controls">
            <div className="governance-intake-search"><label>변경 대상 검색<input minLength={2} onChange={(event) => setQuery(event.target.value)} placeholder="변경할 테이블을 검색하거나 수동으로 추가하세요." value={query} /></label></div>
            <div className="governance-target-actions"><button className="button button-secondary" type="button" onClick={downloadTemplate}>양식 다운로드</button><button className="button button-secondary" type="button" disabled title="서버 검증형 CR 엑셀 파서 API가 아직 없습니다.">엑셀 업로드</button></div>
          </div>
          {searching && <p className="muted">실데이터를 검색하는 중입니다.</p>}
          {results.length > 0 && <ul className="governance-create-search-results">{results.map((result) => <li key={result.id}><button onClick={() => addExisting(result)} type="button"><strong>{result.name}</strong><span>{assetLabel(result)}</span></button></li>)}</ul>}
          {targets.length > 0 && <div className="governance-target-table-frame">
            <table aria-label="변경 대상 테이블 및 컬럼" className="governance-target-table">
              <colgroup><col className="governance-target-name-column" /><col className="governance-target-schema-column" /><col className="governance-target-description-column" /><col className="governance-target-remarks-column" /><col className="governance-target-action-column" /></colgroup>
              <thead><tr><th>TABLE / COLUMN NAME</th><th>SCHEMA</th><th>DESC (LOGICAL NAME)</th><th>비고 (REMARKS)</th><th><span className="sr-only">관리</span></th></tr></thead>
              <tbody>{targets.map((target, targetIndex) => {
                const tableName = target.kind === 'EXISTING' ? target.asset.name : target.table_name
                const schemaName = target.kind === 'EXISTING' ? target.asset.schema_name ?? '' : target.schema_name
                return <Fragment key={target.kind === 'EXISTING' ? target.asset.id : `manual-${targetIndex}`}>
                  <tr className="governance-target-table-row">
                    <td className="governance-target-name-cell"><div className="governance-target-name-control">
                      {target.kind === 'EXISTING' ? <span className="governance-target-add-column governance-target-column-picker"><Plus aria-hidden="true" size={14} /><select aria-label={`${target.asset.name} 컬럼 추가`} onChange={(event) => addExistingColumn(targetIndex, event.target.value)} title="컬럼 추가" value=""><option value="">컬럼 선택</option>{(selectedFieldOptions[targetIndex] ?? []).map((field) => <option key={field.fieldPath} value={field.fieldPath}>{field.fieldPath} · {field.dataType ?? ''}</option>)}</select></span> : <button aria-label={`${tableName || `신규 테이블 ${targetIndex + 1}`} 컬럼 추가`} className="governance-target-add-column" onClick={() => addManualColumn(targetIndex)} title="컬럼 추가" type="button"><Plus aria-hidden="true" size={14} /></button>}
                      {target.kind === 'EXISTING' ? <strong title={tableName}>{tableName}</strong> : <input aria-label={`신규 테이블 ${targetIndex + 1} 테이블명`} onChange={(event) => updateTarget(targetIndex, { table_name: event.target.value })} placeholder="Table Name" required title={target.table_name} value={target.table_name} />}
                    </div></td>
                    <td>{target.kind === 'EXISTING' ? <span title={schemaName}>{schemaName || '—'}</span> : <input aria-label={`신규 테이블 ${targetIndex + 1} 스키마`} onChange={(event) => updateTarget(targetIndex, { schema_name: event.target.value })} placeholder="Schema" title={target.schema_name} value={target.schema_name} />}</td>
                    <td><input aria-label={`${tableName || `신규 테이블 ${targetIndex + 1}`} 설명`} onChange={(event) => updateTarget(targetIndex, { description: event.target.value })} placeholder="테이블 설명" title={target.description} value={target.description} /></td>
                    <td><input aria-label={`${tableName || `신규 테이블 ${targetIndex + 1}`} 비고`} onChange={(event) => updateTarget(targetIndex, { requested_change: event.target.value })} placeholder="테이블 작업 내용 (예: 신규 생성)" title={target.requested_change} value={target.requested_change} /></td>
                    <td className="governance-target-action-cell"><button aria-label={`${tableName || `신규 테이블 ${targetIndex + 1}`} 삭제`} className="governance-target-remove" onClick={() => setTargets((current) => current.filter((_, index) => index !== targetIndex))} title="테이블 삭제" type="button"><Trash2 size={15} /></button></td>
                  </tr>
                  {target.columns.map((column, columnIndex) => <tr className="governance-target-column-row" key={`column-${columnIndex}`}>
                    <td className="governance-target-column-name-cell"><span aria-hidden="true" className="governance-target-column-branch" />{target.kind === 'EXISTING' ? <code title={column.field_path}>{column.field_path}</code> : <input aria-label={`${tableName || `신규 테이블 ${targetIndex + 1}`} 컬럼 ${columnIndex + 1} 이름`} onChange={(event) => updateColumn(targetIndex, columnIndex, { field_path: event.target.value })} placeholder="Column Name" title={column.field_path} value={column.field_path} />}</td>
                    <td aria-label="컬럼 스키마 공란" />
                    <td><input aria-label={`${column.field_path || `컬럼 ${columnIndex + 1}`} 설명`} onChange={(event) => updateColumn(targetIndex, columnIndex, { description: event.target.value })} placeholder="컬럼 설명" title={column.description} value={column.description} /></td>
                    <td><input aria-label={`${column.field_path || `컬럼 ${columnIndex + 1}`} 비고`} onChange={(event) => updateColumn(targetIndex, columnIndex, { requested_change: event.target.value })} placeholder="비고 (예: 컬럼 타입 변경)" title={column.requested_change} value={column.requested_change} /></td>
                    <td className="governance-target-action-cell"><button aria-label={`${column.field_path || `컬럼 ${columnIndex + 1}`} 삭제`} className="governance-target-remove" onClick={() => removeColumn(targetIndex, columnIndex)} title="컬럼 삭제" type="button"><X size={14} /></button></td>
                  </tr>)}
                </Fragment>
              })}</tbody>
            </table>
          </div>}
          {!targets.length && <p className="muted">기존 테이블을 검색해 선택하거나 신규 테이블을 추가하세요.</p>}
          <button className="governance-target-add-manual" onClick={addManual} type="button"><Plus size={14} /> ADD NEW TABLE MANUALLY</button>
        </fieldset>
        <fieldset><legend>Attachments · 증빙 자료</legend><label className="governance-create-file">클릭하거나 파일을 드래그하세요. (파일당 최대 10 MiB)<input multiple onChange={addFiles} type="file" /></label>{files.length > 0 && <ul className="governance-create-files">{files.map((file, index) => <li key={`${file.name}-${file.lastModified}-${index}`}><span>{file.name} · {Math.ceil(file.size / 1024).toLocaleString()} KiB</span><button className="button button-secondary" onClick={() => setFiles((current) => current.filter((_, itemIndex) => itemIndex !== index))} type="button">제거</button></li>)}</ul>}</fieldset>
      </>}
      <ErrorNotice error={error} />
    </form>
  </Dialog>
}
