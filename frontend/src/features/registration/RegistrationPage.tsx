import { createSHA256 } from 'hash-wasm'
import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { newIdempotencyKey, type ApiClient } from '../../api/client'
import type { ChangeRequestRecord, UploadRecord } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { PageTitle } from '../../components/layout/PageTitle'

const HASH_CHUNK_SIZE = 4 * 1024 * 1024
const TERMINAL_STATES = new Set(['ACCEPTED', 'REJECTED', 'ABORTED', 'EXPIRED'])

export function RegistrationPage({ client }: { client: ApiClient }) {
  const [file, setFile] = useState<File>()
  const [classification, setClassification] = useState('INTERNAL')
  const [progress, setProgress] = useState(0)
  const [status, setStatus] = useState('파일을 선택하세요.')
  const [record, setRecord] = useState<UploadRecord>()
  const [records, setRecords] = useState<UploadRecord[]>([])
  const [error, setError] = useState<unknown>()
  const [busy, setBusy] = useState(false)
  const [targetRef, setTargetRef] = useState('')
  const [aspectName, setAspectName] = useState('datasetProperties')
  const [aspectDocument, setAspectDocument] = useState('{\n  "description": ""\n}')
  const [proposal, setProposal] = useState<ChangeRequestRecord>()

  const load = useCallback(async () => {
    try {
      const value = await client.request<{ items: UploadRecord[] }>('/uploads?limit=50')
      setRecords(value.items)
    } catch (next) { setError(next) }
  }, [client])

  useEffect(() => { void load() }, [load])

  const poll = async (uploadId: string) => {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      const current = await client.request<UploadRecord>(`/uploads/${uploadId}`)
      setRecord(current)
      setRecords((values) => [current, ...values.filter((item) => item.id !== current.id)])
      setStatus(stateLabel(current))
      if (TERMINAL_STATES.has(current.state)) return
      await delay(1000)
    }
    setStatus('검증이 계속 진행 중입니다. 최근 등록 목록에서 상태를 새로고침하세요.')
  }

  const upload = async (event: FormEvent) => {
    event.preventDefault()
    if (!file) return
    setBusy(true); setError(undefined); setProgress(0)
    try {
      setStatus('SHA-256 계산 중')
      const sha256 = await digestFile(file, (value) => setProgress(value * 0.15))
      const contentType = supportedContentType(file)
      const initiated = await client.request<UploadRecord>('/uploads', {
        method: 'POST',
        idempotencyKey: newIdempotencyKey('upload-init'),
        body: JSON.stringify({
          display_name: file.name,
          size_bytes: file.size,
          content_type: contentType,
          sha256,
          classification,
        }),
      })
      setRecord(initiated)
      const partSize = initiated.recommended_part_size_bytes
      const completed: Array<{ part_number: number; etag: string }> = []
      const partCount = Math.ceil(file.size / partSize)
      for (let index = 0; index < partCount; index += 1) {
        const partNumber = index + 1
        setStatus(`${partNumber}/${partCount} 파트 업로드 중`)
        const signed = await client.request<{ url: string }>(`/uploads/${initiated.id}/parts`, {
          method: 'POST',
          body: JSON.stringify({ part_number: partNumber }),
        })
        const response = await fetch(signed.url, {
          method: 'PUT',
          body: file.slice(index * partSize, Math.min(file.size, (index + 1) * partSize)),
        })
        if (!response.ok) throw new Error(`오브젝트 스토리지 업로드 실패 (${response.status})`)
        const etag = response.headers.get('ETag')?.replaceAll('"', '')
        if (!etag) throw new Error('오브젝트 스토리지 응답에서 ETag를 읽을 수 없습니다. CORS 설정을 확인하세요.')
        completed.push({ part_number: partNumber, etag })
        setProgress(0.15 + (partNumber / partCount) * 0.8)
      }
      const queued = await client.request<UploadRecord>(`/uploads/${initiated.id}/complete`, {
        method: 'POST',
        idempotencyKey: newIdempotencyKey('upload-complete'),
        ifMatch: `"${initiated.version}"`,
        body: JSON.stringify({ parts: completed }),
      })
      setRecord(queued); setProgress(0.97); setStatus('무결성·형식 검증 대기 중')
      await poll(queued.id)
      setProgress(1)
    } catch (next) { setError(next); setStatus('업로드 또는 검증 상태 확인 실패') } finally { setBusy(false) }
  }

  const createProposal = async (event: FormEvent) => {
    event.preventDefault()
    if (!record || record.state !== 'ACCEPTED') return
    setError(undefined)
    try {
      const document = JSON.parse(aspectDocument) as Record<string, unknown>
      const value = await client.request<ChangeRequestRecord>(`/uploads/${record.id}/registration-proposals`, {
        method: 'POST', idempotencyKey: newIdempotencyKey('registration-proposal'),
        body: JSON.stringify({
          target_ref: targetRef, aspect_name: aspectName, after_document: document,
          title: `${record.display_name} 메타데이터 등록`,
          description: '검증된 업로드를 근거로 DataHub 메타데이터 변경을 제안합니다.',
        }),
      })
      setProposal(value)
    } catch (next) { setError(next) }
  }

  return (
    <section>
      <PageTitle
        icon="RG"
        eyebrow="Quarantine-first"
        title="데이터 등록"
        description="업로드를 격리·검증한 뒤 승인 가능한 메타데이터 변경 제안으로 전환합니다."
        actions={<button className="button button-secondary" onClick={() => void load()}>목록 새로고침</button>}
      />
      <div className="panel-grid">
        <form className="panel form-stack" onSubmit={(event) => void upload(event)}>
          <label>등록 파일<input type="file" accept=".csv,.json,.parquet,.yaml,.yml,.xlsx" onChange={(event) => setFile(event.target.files?.[0])} required /></label>
          <label>분류등급<select value={classification} onChange={(event) => setClassification(event.target.value)}><option>PUBLIC</option><option>INTERNAL</option><option>CONFIDENTIAL</option><option>RESTRICTED</option></select></label>
          <button className="button" disabled={!file || busy}>{busy ? '처리 중…' : '업로드 시작'}</button>
          <div className="progress-track"><span style={{ width: `${Math.round(progress * 100)}%` }} /></div>
          <p className="muted" aria-live="polite">{status}</p>
        </form>
        <div className="panel">
          <h3>최근 등록</h3>
          <div className="compact-list">
            {records.map((item) => <button className={record?.id === item.id ? 'selected' : ''} key={item.id} onClick={() => setRecord(item)}><span><strong>{item.display_name}</strong><small>{item.size_bytes.toLocaleString()} bytes</small></span><span className="badge">{item.state}</span></button>)}
            {!records.length && <p className="muted">등록 이력이 없습니다.</p>}
          </div>
        </div>
      </div>
      <ErrorNotice error={error} />
      {record && <article className="result-card"><span className="badge">{record.state}</span><h3>{record.display_name}</h3><p>버전 {record.version} · {record.size_bytes.toLocaleString()} bytes · {record.content_type}</p>{record.last_error_code && <p className="notice notice-error">실패 코드: {record.last_error_code}</p>}{Object.keys(record.validation_summary).length > 0 && <dl className="summary-list">{Object.entries(record.validation_summary).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>)}</dl>}<code>{record.id}</code>{record.state === 'ACCEPTED' && <form className="form-stack governance-detail" onSubmit={(event) => void createProposal(event)}><h3>DataHub 등록 제안</h3><label>대상 URN<input value={targetRef} onChange={(event) => setTargetRef(event.target.value)} placeholder="urn:li:dataset:(...)" pattern="urn:li:.+" required /></label><label>Aspect<select value={aspectName} onChange={(event) => setAspectName(event.target.value)}><option>datasetProperties</option><option>globalTags</option><option>glossaryTerms</option><option>ownership</option></select></label><label>Aspect JSON<textarea className="code-editor" value={aspectDocument} onChange={(event) => setAspectDocument(event.target.value)} required /></label><p className="callout">제안은 변경관리의 검토·승인·DataHub 재조회 검증을 거친 뒤에만 반영됩니다.</p><button className="button">변경요청 생성</button>{proposal && <p>생성됨: <strong>{proposal.number}</strong> · {proposal.state}</p>}</form>}</article>}
    </section>
  )
}

function stateLabel(record: UploadRecord): string {
  const labels: Record<string, string> = {
    COMPLETION_QUEUED: '오브젝트 완료 대기 중', COMPLETING: '오브젝트 완료 처리 중',
    QUARANTINED: '격리 완료, 검증 대기 중', VALIDATING: '무결성·형식 검증 중',
    ACCEPTED: '검증 통과 및 승인 버킷 승격 완료', REJECTED: `검증 거부 (${record.last_error_code ?? '원인 미상'})`,
  }
  return labels[record.state] ?? record.state
}

async function digestFile(file: File, onProgress: (value: number) => void): Promise<string> {
  const hash = await createSHA256()
  hash.init()
  for (let offset = 0; offset < file.size; offset += HASH_CHUNK_SIZE) {
    const chunk = new Uint8Array(await file.slice(offset, offset + HASH_CHUNK_SIZE).arrayBuffer())
    hash.update(chunk)
    onProgress(Math.min(1, (offset + chunk.byteLength) / file.size))
  }
  return hash.digest('hex')
}

export function supportedContentType(file: Pick<File, 'name' | 'type'>): string {
  const extension = file.name.toLowerCase().split('.').pop()
  const byExtension: Record<string, string> = {
    csv: 'text/csv', json: 'application/json', parquet: 'application/x-parquet',
    yaml: 'application/yaml', yml: 'application/yaml',
    xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  }
  const value = extension ? byExtension[extension] : undefined
  if (!value) throw new Error('CSV, JSON, Parquet, YAML 또는 XLSX 파일만 등록할 수 있습니다.')
  return value
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds))
}
