import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Eye, GitPullRequest, Tags } from 'lucide-react'
import { ApiError, newIdempotencyKey, type ApiClient } from '../../api/client'
import type {
  CatalogAssetDetail,
  CatalogControlledMetadataAspect,
  CatalogControlledMetadataPreview,
  ChangeRequestRecord,
} from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'

const SHA256_PATTERN = /^[0-9a-f]{64}$/
const QUOTED_SHA256_ETAG_PATTERN = /^"[0-9a-f]{64}"$/

const aspectOptions: Array<{ value: CatalogControlledMetadataAspect; label: string; prefix: string; hint: string }> = [
  { value: 'domains', label: 'Domain', prefix: 'urn:li:domain:', hint: '한 개의 DataHub Domain URN만 지정할 수 있습니다.' },
  { value: 'globalTags', label: 'Tag', prefix: 'urn:li:tag:', hint: '한 줄에 하나의 DataHub Tag URN을 입력합니다.' },
  { value: 'glossaryTerms', label: 'Term', prefix: 'urn:li:glossaryTerm:', hint: '한 줄에 하나의 DataHub Glossary Term URN을 입력합니다.' },
]
const defaultAspect = { value: 'domains' as const, label: 'Domain', prefix: 'urn:li:domain:', hint: '한 개의 DataHub Domain URN만 지정할 수 있습니다.' }

function refsFromText(value: string): string[] {
  return value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean)
}

function isSourceDrift(error: unknown): boolean {
  return error instanceof ApiError && (error.problem.status === 409 || error.problem.status === 412)
}

function sourceTerms(asset: CatalogAssetDetail): string[] {
  return asset.glossary_terms.flatMap((item) => {
    const term = item.term
    if (term && typeof term === 'object' && 'urn' in term && typeof term.urn === 'string') return [term.urn]
    if (typeof item.urn === 'string') return [item.urn]
    return []
  })
}

export function RegistrationControlledMetadataEditor({ client, asset }: { client: ApiClient; asset: CatalogAssetDetail }) {
  const [aspect, setAspect] = useState<CatalogControlledMetadataAspect>('domains')
  const [refsText, setRefsText] = useState('')
  const [title, setTitle] = useState(`${asset.name} Domain 변경`)
  const [changeDescription, setChangeDescription] = useState('')
  const [preview, setPreview] = useState<CatalogControlledMetadataPreview>()
  const [proposal, setProposal] = useState<ChangeRequestRecord>()
  const [error, setError] = useState<unknown>()
  const [busy, setBusy] = useState<'PREVIEW' | 'CREATE'>()
  const [drifted, setDrifted] = useState(false)
  const controller = useRef<AbortController | undefined>(undefined)
  const generation = useRef(0)
  const idempotencyKey = useRef<string | undefined>(undefined)
  const selected = aspectOptions.find((item) => item.value === aspect) ?? defaultAspect

  useEffect(() => {
    generation.current += 1
    controller.current?.abort()
    idempotencyKey.current = undefined
    setAspect('domains'); setRefsText(''); setTitle(`${asset.name} Domain 변경`); setChangeDescription('')
    setPreview(undefined); setProposal(undefined); setError(undefined); setBusy(undefined); setDrifted(false)
    return () => { generation.current += 1; controller.current?.abort() }
  }, [asset.id, asset.name, asset.source_version, client])

  const invalidate = () => {
    generation.current += 1
    controller.current?.abort(); idempotencyKey.current = undefined
    setPreview(undefined); setProposal(undefined); setError(undefined); setBusy(undefined); setDrifted(false)
  }

  const changeAspect = (value: CatalogControlledMetadataAspect) => {
    invalidate(); setAspect(value); setRefsText('')
    const option = aspectOptions.find((item) => item.value === value)
    setTitle(`${asset.name} ${option?.label ?? 'Metadata'} 변경`)
  }

  const refs = refsFromText(refsText)
  const invalidRef = refs.find((reference) => !reference.startsWith(selected.prefix))
  const canPreview = title.trim() && changeDescription.trim() && !invalidRef && !busy && !proposal

  const previewChange = async () => {
    if (!canPreview) {
      setError(new Error(invalidRef ? `${selected.prefix} 형식의 URN만 입력할 수 있습니다.` : '제목과 변경 사유를 입력한 뒤 미리보기를 실행하세요.'))
      return
    }
    const request = new AbortController(); controller.current?.abort(); controller.current = request
    const expectedGeneration = generation.current
    setBusy('PREVIEW'); setPreview(undefined); setError(undefined); setDrifted(false)
    try {
      const value = await client.request<CatalogControlledMetadataPreview>(`/catalog/assets/${asset.id}/controlled-metadata-previews`, {
        method: 'POST', signal: request.signal, body: JSON.stringify({ aspect_name: aspect, refs }),
      })
      if (request.signal.aborted || expectedGeneration !== generation.current) return
      if (value.asset_id !== asset.id || value.aspect_name !== aspect || !SHA256_PATTERN.test(value.before_hash) || !SHA256_PATTERN.test(value.after_hash) || !QUOTED_SHA256_ETAG_PATTERN.test(value.preview_etag)) {
        throw new Error('서버가 대상·Aspect·hash가 일치하지 않는 controlled metadata 미리보기를 반환했습니다.')
      }
      setPreview(value)
    } catch (next) { if (!request.signal.aborted && expectedGeneration === generation.current) setError(next) }
    finally { if (expectedGeneration === generation.current) setBusy(undefined) }
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!preview || busy || proposal) return
    const currentRefs = refsFromText(refsText)
    if (preview.aspect_name !== aspect || preview.proposed_refs.join('\n') !== currentRefs.join('\n')) {
      setPreview(undefined); setError(new Error('참조값이 미리보기 이후 변경되었습니다. 미리보기를 다시 실행하세요.')); return
    }
    const request = new AbortController(); controller.current?.abort(); controller.current = request
    const expectedGeneration = generation.current
    const requestKey = idempotencyKey.current ?? newIdempotencyKey('controlled-metadata-change')
    idempotencyKey.current = requestKey
    setBusy('CREATE'); setError(undefined); setDrifted(false)
    try {
      const value = await client.request<ChangeRequestRecord>(`/catalog/assets/${asset.id}/controlled-metadata-change-requests`, {
        method: 'POST', signal: request.signal, idempotencyKey: requestKey, ifMatch: preview.preview_etag,
        body: JSON.stringify({ aspect_name: aspect, refs: currentRefs, title, change_description: changeDescription }),
      })
      if (!request.signal.aborted && expectedGeneration === generation.current) setProposal(value)
    } catch (next) {
      if (!request.signal.aborted && expectedGeneration === generation.current) {
        if (isSourceDrift(next)) { setPreview(undefined); idempotencyKey.current = undefined; setDrifted(true) }
        setError(next)
      }
    } finally { if (expectedGeneration === generation.current) setBusy(undefined) }
  }

  const currentDisplay = aspect === 'globalTags' ? asset.tags : aspect === 'glossaryTerms' ? sourceTerms(asset) : []
  const locked = Boolean(busy || proposal)
  return <section className="registration-description-editor registration-controlled-metadata-editor" aria-labelledby="controlled-metadata-title" aria-busy={Boolean(busy)}>
    <header><div><span className="eyebrow">Controlled DataHub metadata</span><h3 id="controlled-metadata-title">Domain · Term · Tag 변경 제안</h3></div><span className="badge badge-soft">{asset.classification}</span></header>
    <form className="form-stack" onSubmit={(event) => void submit(event)}>
      <p className="callout">현재 metadata는 DataHub 원본 aspect에서 미리보기 시 다시 읽습니다. 승인 전 변경은 DataHub에 적용되지 않으며, 화면은 원시 Aspect JSON을 받지 않습니다.</p>
      <div className="registration-controlled-aspects" role="radiogroup" aria-label="변경할 메타데이터 종류">{aspectOptions.map((option) => <button key={option.value} type="button" role="radio" aria-checked={aspect === option.value} className={aspect === option.value ? 'active' : ''} disabled={locked} onClick={() => changeAspect(option.value)}><Tags size={12} />{option.label}</button>)}</div>
      {currentDisplay.length > 0 && <p className="registration-controlled-current"><strong>Projection 표시값:</strong> {currentDisplay.join(', ')}</p>}
      <label htmlFor="controlled-metadata-refs">제안 {selected.label} 참조 (한 줄에 하나)
        <textarea id="controlled-metadata-refs" value={refsText} disabled={locked} placeholder={`${selected.prefix}...`} onChange={(event) => { invalidate(); setRefsText(event.target.value) }} aria-describedby="controlled-metadata-hint" />
      </label>
      <p id="controlled-metadata-hint" className="registration-description-status">{selected.hint} 비우면 해당 metadata를 제거하도록 제안합니다.</p>
      <label htmlFor="controlled-metadata-title-input">변경 요청 제목<input id="controlled-metadata-title-input" value={title} maxLength={500} disabled={locked} required onChange={(event) => { invalidate(); setTitle(event.target.value) }} /></label>
      <label htmlFor="controlled-metadata-reason">변경 사유<textarea id="controlled-metadata-reason" value={changeDescription} maxLength={10_000} disabled={locked} required onChange={(event) => { invalidate(); setChangeDescription(event.target.value) }} /></label>
      <div className="registration-description-actions"><button className="button button-secondary" type="button" disabled={!canPreview} onClick={() => void previewChange()}><Eye size={14} />{busy === 'PREVIEW' ? '미리보기 확인 중…' : '변경 미리보기'}</button><button className="button" type="submit" disabled={!preview || locked}><GitPullRequest size={14} />{busy === 'CREATE' ? '생성 중…' : '변경요청 생성'}</button></div>
      {drifted && <div className="notice registration-source-warning" role="alert">미리보기 이후 DataHub 원본 metadata가 변경되었습니다. 새 미리보기를 실행하세요.</div>}
      <ErrorNotice error={error} />
      {preview && <section className="registration-description-preview" aria-label="controlled metadata 변경 미리보기"><header><strong>검증된 {selected.label} 변경 비교</strong><span className="badge">PREVIEW</span></header><dl><div><dt>Aspect</dt><dd>{preview.aspect_name}</dd></div><div><dt>Source version</dt><dd><code>{preview.source_version}</code></dd></div><div className="wide"><dt>Before SHA-256</dt><dd><code>{preview.before_hash}</code></dd></div><div className="wide"><dt>After SHA-256</dt><dd><code>{preview.after_hash}</code></dd></div><div className="wide description-before"><dt>현재 원본 참조</dt><dd>{preview.current_refs.join('\n') || '(없음)'}</dd></div><div className="wide description-after"><dt>제안 참조</dt><dd>{preview.proposed_refs.join('\n') || '(제거)'}</dd></div></dl></section>}
      {proposal && <div className="notice registration-description-success" role="status"><strong>{proposal.number} 변경 요청을 생성했습니다.</strong><span>상태: {proposal.state}. Maker-Checker 검토와 DataHub read-back 전에는 적용되지 않습니다.</span></div>}
    </form>
  </section>
}
