import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import { ApiError, newIdempotencyKey, type ApiClient } from '../../api/client'
import type {
  CatalogAsset,
  CatalogAssetDetail,
  CatalogDescriptionPreview,
  CatalogSearch,
  ChangeRequestRecord,
} from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { Dialog } from '../../components/common/Dialog'

const MAXIMUM_ATTACHMENT_BYTES = 10 * 1024 * 1024

function defaultDueDate(): string {
  const value = new Date()
  value.setDate(value.getDate() + 14)
  return value.toISOString().slice(0, 10)
}

function formatAsset(asset: CatalogAsset): string {
  return [asset.platform, asset.database_name, asset.schema_name, asset.name]
    .filter((value): value is string => Boolean(value))
    .join(' · ')
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
  const [asset, setAsset] = useState<CatalogAssetDetail>()
  const [assetLoading, setAssetLoading] = useState(false)
  const [title, setTitle] = useState('')
  const [reason, setReason] = useState('')
  const [description, setDescription] = useState('')
  const [dueDate, setDueDate] = useState(defaultDueDate)
  const [priority, setPriority] = useState<'LOW' | 'NORMAL' | 'HIGH' | 'CRITICAL'>('NORMAL')
  const [urgency, setUrgency] = useState<'NORMAL' | 'URGENT' | 'EMERGENCY'>('NORMAL')
  const [files, setFiles] = useState<File[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [created, setCreated] = useState<ChangeRequestRecord>()
  const [error, setError] = useState<unknown>()
  const searchController = useRef<AbortController | undefined>(undefined)
  const assetController = useRef<AbortController | undefined>(undefined)
  const submitController = useRef<AbortController | undefined>(undefined)

  useEffect(() => {
    if (!open) return
    return () => {
      searchController.current?.abort()
      assetController.current?.abort()
      submitController.current?.abort()
    }
  }, [open])

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
      void client.request<CatalogSearch>(`/catalog/assets?q=${encodeURIComponent(query.trim())}&limit=10`, {
        signal: controller.signal,
      }).then((value) => {
        if (!controller.signal.aborted) setResults(value.items)
      }).catch((next: unknown) => {
        if (!controller.signal.aborted) setError(next)
      }).finally(() => {
        if (!controller.signal.aborted) setSearching(false)
      })
    }, 250)
    return () => {
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [client, open, query])

  const selectAsset = (summary: CatalogAsset) => {
    const controller = new AbortController()
    assetController.current?.abort()
    assetController.current = controller
    setAssetLoading(true)
    setError(undefined)
    void client.request<CatalogAssetDetail>(`/catalog/assets/${summary.id}`, { signal: controller.signal })
      .then((value) => {
        if (controller.signal.aborted) return
        setAsset(value)
        setTitle(`${value.name} 설명 변경`)
        setDescription(value.description ?? '')
        setQuery(formatAsset(value))
        setResults([])
      })
      .catch((next: unknown) => {
        if (!controller.signal.aborted) setError(next)
      })
      .finally(() => {
        if (!controller.signal.aborted) setAssetLoading(false)
      })
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

  const reset = () => {
    searchController.current?.abort()
    assetController.current?.abort()
    submitController.current?.abort()
    setQuery('')
    setResults([])
    setSearching(false)
    setAsset(undefined)
    setAssetLoading(false)
    setTitle('')
    setReason('')
    setDescription('')
    setDueDate(defaultDueDate())
    setPriority('NORMAL')
    setUrgency('NORMAL')
    setFiles([])
    setSubmitting(false)
    setCreated(undefined)
    setError(undefined)
  }

  const requestClose = () => {
    if (submitting) return
    reset()
    onClose()
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!asset || submitting || created) return
    if (!title.trim() || !reason.trim()) {
      setError(new Error('변경 요청 제목과 요청 사유를 입력하세요.'))
      return
    }
    if (description === (asset.description ?? '')) {
      setError(new Error('현재 설명과 다른 제안 설명을 입력하세요.'))
      return
    }
    const controller = new AbortController()
    submitController.current?.abort()
    submitController.current = controller
    setSubmitting(true)
    setError(undefined)
    try {
      const preview = await client.request<CatalogDescriptionPreview>(
        `/catalog/assets/${asset.id}/description-previews`,
        { method: 'POST', signal: controller.signal, body: JSON.stringify({ description }) },
      )
      if (controller.signal.aborted || preview.asset_id !== asset.id) return
      const changeRequest = await client.request<ChangeRequestRecord>(
        `/catalog/assets/${asset.id}/description-change-requests`,
        {
          method: 'POST',
          signal: controller.signal,
          idempotencyKey: newIdempotencyKey('change-request-create'),
          ifMatch: preview.preview_etag,
          body: JSON.stringify({
            description,
            title: title.trim(),
            change_description: reason.trim(),
            requested_due_date: dueDate || null,
            priority,
            urgency,
          }),
        },
      )
      if (controller.signal.aborted) return
      for (const file of files) {
        const body = new FormData()
        body.set('kind', 'REQUEST')
        body.set('file', file)
        await client.request(`/change-requests/${changeRequest.id}/attachments`, {
          method: 'POST',
          signal: controller.signal,
          body,
        })
      }
      if (controller.signal.aborted) return
      setCreated(changeRequest)
      onCreated(changeRequest)
    } catch (next) {
      if (!controller.signal.aborted) {
        if (next instanceof ApiError && next.problem.status === 412) {
          setError(new Error('DataHub 원본이 변경되었습니다. 대상 정보를 다시 선택한 뒤 재시도하세요.'))
        } else {
          setError(next)
        }
      }
    } finally {
      if (!controller.signal.aborted) setSubmitting(false)
    }
  }

  return (
    <Dialog
      open={open}
      size="workspace"
      title="신규 CR 신청"
      description="등록관리와 독립된 변경 요청입니다. 선택한 DataHub 테이블의 현재 원본을 서버에서 검증한 뒤 요청을 생성합니다."
      onRequestClose={requestClose}
      footer={<>
        <button type="button" className="button button-secondary" disabled={submitting} onClick={requestClose}>닫기</button>
        {!created && <button type="submit" form="change-request-create-form" className="button" disabled={submitting || !asset}> {submitting ? '등록 중…' : '신규 CR 등록'} </button>}
      </>}
    >
      <form id="change-request-create-form" className="governance-create-form" onSubmit={(event) => void submit(event)}>
        {created ? <div className="notice" role="status"><strong>{created.number}</strong> 변경 요청을 등록했습니다. 목록에서 검토·변경/TEST·완료검토 단계를 진행할 수 있습니다.</div> : <>
          <fieldset>
            <legend>대상 데이터셋</legend>
            <label>
              DataHub 테이블 검색
              <input value={query} minLength={2} maxLength={500} onChange={(event) => setQuery(event.target.value)} placeholder="테이블명, 스키마 또는 설명을 2자 이상 입력" disabled={submitting} />
            </label>
            {searching && <p className="muted">실데이터를 검색하는 중입니다.</p>}
            {results.length > 0 && <ul className="governance-create-search-results">
              {results.map((result) => <li key={result.id}><button type="button" disabled={submitting} onClick={() => selectAsset(result)}><strong>{result.name}</strong><span>{formatAsset(result)}</span></button></li>)}
            </ul>}
            {assetLoading && <p className="muted">선택한 테이블의 현재 메타데이터를 확인하는 중입니다.</p>}
            {asset && <dl className="governance-create-target"><div><dt>선택 대상</dt><dd>{formatAsset(asset)}</dd></div><div><dt>등급</dt><dd>{asset.classification}</dd></div><div className="wide"><dt>URN</dt><dd><code>{asset.external_urn}</code></dd></div></dl>}
          </fieldset>
          <fieldset disabled={!asset || submitting}>
            <legend>변경 요청</legend>
            <div className="governance-create-grid">
              <label className="wide">CR명<input value={title} maxLength={500} onChange={(event) => setTitle(event.target.value)} required /></label>
              <label>요청 납기<input type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} /></label>
              <label>중요도<select value={priority} onChange={(event) => setPriority(event.target.value as typeof priority)}><option value="LOW">낮음</option><option value="NORMAL">보통</option><option value="HIGH">높음</option><option value="CRITICAL">최우선</option></select></label>
              <label>긴급도<select value={urgency} onChange={(event) => setUrgency(event.target.value as typeof urgency)}><option value="NORMAL">일반</option><option value="URGENT">긴급</option><option value="EMERGENCY">비상</option></select></label>
              <label className="wide">요청 사유<textarea value={reason} maxLength={10000} onChange={(event) => setReason(event.target.value)} required /></label>
              <label className="wide">제안 설명<textarea value={description} maxLength={10000} onChange={(event) => setDescription(event.target.value)} required /></label>
            </div>
          </fieldset>
          <fieldset disabled={submitting}>
            <legend>요청 첨부파일</legend>
            <label className="governance-create-file">복수 파일 첨부 (파일당 최대 10 MiB)<input type="file" multiple onChange={addFiles} /></label>
            {files.length > 0 && <ul className="governance-create-files">{files.map((file, index) => <li key={`${file.name}-${file.lastModified}-${index}`}><span>{file.name} · {Math.ceil(file.size / 1024).toLocaleString()} KiB</span><button type="button" className="button button-secondary" onClick={() => setFiles((current) => current.filter((_, itemIndex) => itemIndex !== index))}>제거</button></li>)}</ul>}
          </fieldset>
        </>}
        <ErrorNotice error={error} />
      </form>
    </Dialog>
  )
}
