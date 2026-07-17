import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Eye, GitPullRequest } from 'lucide-react'
import { ApiError, newIdempotencyKey, type ApiClient } from '../../api/client'
import type {
  CatalogAssetDetail,
  CatalogColumnDescriptionPreview,
  ChangeRequestRecord,
} from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'

const SHA256_PATTERN = /^[0-9a-f]{64}$/
const QUOTED_SHA256_ETAG_PATTERN = /^"[0-9a-f]{64}"$/

export interface SchemaDescriptionField {
  fieldPath: string
  description: string | null
  dataType: string | null
}

export function schemaDescriptionFields(
  fields: Array<Record<string, unknown>>,
): SchemaDescriptionField[] {
  const seen = new Set<string>()
  const values: SchemaDescriptionField[] = []
  for (const value of fields) {
    const fieldPath = value.fieldPath
    if (typeof fieldPath !== 'string' || !fieldPath || seen.has(fieldPath)) continue
    const description = value.description
    const dataType = value.nativeDataType ?? value.dataType
    if (description !== undefined && description !== null && typeof description !== 'string') continue
    values.push({
      fieldPath,
      description: typeof description === 'string' ? description : null,
      dataType: typeof dataType === 'string' ? dataType : null,
    })
    seen.add(fieldPath)
  }
  return values
}

function displayDescription(value: string | null): string {
  return value === '' || value === null ? '(빈 설명)' : value
}

function isSourceDrift(error: unknown): boolean {
  return error instanceof ApiError && (error.problem.status === 409 || error.problem.status === 412)
}

export function RegistrationColumnDescriptionEditor({
  client,
  asset,
}: {
  client: ApiClient
  asset: CatalogAssetDetail
}) {
  const fields = schemaDescriptionFields(asset.schema_fields)
  const [fieldPath, setFieldPath] = useState(fields[0]?.fieldPath ?? '')
  const selected = fields.find((field) => field.fieldPath === fieldPath) ?? fields[0]
  const [description, setDescription] = useState(selected?.description ?? '')
  const [title, setTitle] = useState(selected ? `${selected.fieldPath} 컬럼 설명 변경` : '')
  const [changeDescription, setChangeDescription] = useState('')
  const [preview, setPreview] = useState<CatalogColumnDescriptionPreview>()
  const [proposal, setProposal] = useState<ChangeRequestRecord>()
  const [error, setError] = useState<unknown>()
  const [drifted, setDrifted] = useState(false)
  const [busy, setBusy] = useState<'PREVIEW' | 'CREATE'>()
  const requestController = useRef<AbortController | null>(null)
  const requestGuard = useRef(false)
  const generation = useRef(0)
  const idempotencyKey = useRef<string | undefined>(undefined)

  useEffect(() => {
    generation.current += 1
    requestController.current?.abort()
    requestGuard.current = false
    const initial = schemaDescriptionFields(asset.schema_fields)[0]
    setFieldPath(initial?.fieldPath ?? '')
    setDescription(initial?.description ?? '')
    setTitle(initial ? `${initial.fieldPath} 컬럼 설명 변경` : '')
    setChangeDescription('')
    setPreview(undefined)
    setProposal(undefined)
    setError(undefined)
    setDrifted(false)
    setBusy(undefined)
    idempotencyKey.current = undefined
    return () => {
      generation.current += 1
      requestController.current?.abort()
    }
  }, [asset.id, asset.schema_fields, asset.source_version, client])

  const invalidate = () => {
    generation.current += 1
    requestController.current?.abort()
    requestGuard.current = false
    setBusy(undefined)
    setPreview(undefined)
    setProposal(undefined)
    setError(undefined)
    setDrifted(false)
    idempotencyKey.current = undefined
  }

  const selectField = (nextFieldPath: string) => {
    const next = fields.find((field) => field.fieldPath === nextFieldPath)
    invalidate()
    setFieldPath(nextFieldPath)
    setDescription(next?.description ?? '')
    setTitle(next ? `${next.fieldPath} 컬럼 설명 변경` : '')
  }

  const previewChange = async () => {
    if (!selected || requestGuard.current || proposal || !title.trim() || !changeDescription.trim()) {
      if (!title.trim() || !changeDescription.trim()) {
        setError(new Error('제목과 변경 사유를 입력한 뒤 미리보기를 실행하세요.'))
      }
      return
    }
    requestGuard.current = true
    setBusy('PREVIEW')
    setPreview(undefined)
    setError(undefined)
    setDrifted(false)
    const controller = new AbortController()
    requestController.current?.abort()
    requestController.current = controller
    const expectedGeneration = generation.current
    try {
      const value = await client.request<CatalogColumnDescriptionPreview>(
        `/catalog/assets/${asset.id}/column-description-previews`,
        {
          method: 'POST',
          signal: controller.signal,
          body: JSON.stringify({ field_path: selected.fieldPath, description }),
        },
      )
      if (controller.signal.aborted || expectedGeneration !== generation.current) return
      if (
        value.asset_id !== asset.id
        || value.target_ref !== asset.external_urn
        || value.aspect_name !== 'schemaMetadata'
        || value.field_path !== selected.fieldPath
        || value.proposed_description !== description
        || !SHA256_PATTERN.test(value.before_hash)
        || !SHA256_PATTERN.test(value.after_hash)
        || !QUOTED_SHA256_ETAG_PATTERN.test(value.preview_etag)
        || !value.source_version
      ) throw new Error('서버가 컬럼 또는 hash가 일치하지 않는 미리보기를 반환했습니다.')
      if (value.current_description === value.proposed_description || value.before_hash === value.after_hash) {
        throw new Error('현재 원본 컬럼 설명과 동일하여 변경 요청을 만들 수 없습니다.')
      }
      setPreview(value)
    } catch (next) {
      if (!controller.signal.aborted && expectedGeneration === generation.current) setError(next)
    } finally {
      if (expectedGeneration === generation.current) {
        requestGuard.current = false
        setBusy(undefined)
      }
    }
  }

  const submitChange = async (event: FormEvent) => {
    event.preventDefault()
    if (!selected || requestGuard.current || !preview || proposal) return
    if (preview.field_path !== selected.fieldPath || preview.proposed_description !== description) {
      setPreview(undefined)
      setError(new Error('컬럼 또는 설명이 미리보기 이후 변경되었습니다. 미리보기를 다시 실행하세요.'))
      return
    }
    requestGuard.current = true
    setBusy('CREATE')
    setError(undefined)
    setDrifted(false)
    const controller = new AbortController()
    requestController.current?.abort()
    requestController.current = controller
    const expectedGeneration = generation.current
    const requestKey = idempotencyKey.current ?? newIdempotencyKey('column-description-change')
    idempotencyKey.current = requestKey
    try {
      const value = await client.request<ChangeRequestRecord>(
        `/catalog/assets/${asset.id}/column-description-change-requests`,
        {
          method: 'POST',
          idempotencyKey: requestKey,
          ifMatch: preview.preview_etag,
          signal: controller.signal,
          body: JSON.stringify({
            field_path: selected.fieldPath,
            description,
            title,
            change_description: changeDescription,
          }),
        },
      )
      if (!controller.signal.aborted && expectedGeneration === generation.current) setProposal(value)
    } catch (next) {
      if (!controller.signal.aborted && expectedGeneration === generation.current) {
        if (isSourceDrift(next)) {
          setPreview(undefined)
          idempotencyKey.current = undefined
          setDrifted(true)
        }
        setError(next)
      }
    } finally {
      if (expectedGeneration === generation.current) {
        requestGuard.current = false
        setBusy(undefined)
      }
    }
  }

  if (!fields.length) return null

  const locked = Boolean(busy || proposal)
  return (
    <section className="registration-description-editor registration-column-description-editor" aria-labelledby="column-description-editor-title" aria-busy={Boolean(busy)}>
      <header>
        <div><span className="eyebrow">Typed schemaMetadata change</span><h3 id="column-description-editor-title">컬럼 설명 변경 제안</h3></div>
        <span className="badge badge-soft">{asset.classification}</span>
      </header>
      <form className="form-stack" onSubmit={(event) => void submitChange(event)}>
        <p className="callout">대상 컬럼과 설명만 서버가 live schemaMetadata에서 다시 검증합니다. 타입·nullable·태그·용어·원시 Aspect JSON은 이 화면에서 변경할 수 없습니다.</p>
        <label htmlFor="column-description-field">대상 컬럼
          <select id="column-description-field" value={selected?.fieldPath ?? ''} disabled={locked} onChange={(event) => selectField(event.target.value)}>
            {fields.map((field) => <option key={field.fieldPath} value={field.fieldPath}>{field.fieldPath}{field.dataType ? ` · ${field.dataType}` : ''}</option>)}
          </select>
        </label>
        <label htmlFor="column-description-title">변경 요청 제목
          <input id="column-description-title" value={title} maxLength={500} disabled={locked} required onChange={(event) => { invalidate(); setTitle(event.target.value) }} />
        </label>
        <label htmlFor="column-description-reason">변경 사유
          <textarea id="column-description-reason" value={changeDescription} maxLength={10_000} disabled={locked} required onChange={(event) => { invalidate(); setChangeDescription(event.target.value) }} />
        </label>
        <label htmlFor="column-description-value">제안 컬럼 설명
          <textarea id="column-description-value" value={description} maxLength={10_000} disabled={locked} onChange={(event) => { invalidate(); setDescription(event.target.value) }} />
        </label>
        <p className="registration-description-status">{description === '' ? '빈 설명은 기존 컬럼 설명 삭제 제안입니다.' : `${description.length.toLocaleString()}자 입력됨`}</p>
        <div className="registration-description-actions">
          <button className="button button-secondary" type="button" disabled={locked || !title.trim() || !changeDescription.trim()} onClick={() => void previewChange()}><Eye size={14} aria-hidden="true" />{busy === 'PREVIEW' ? '미리보기 확인 중…' : '변경 미리보기'}</button>
          <button className="button" type="submit" disabled={locked || !preview}><GitPullRequest size={14} aria-hidden="true" />{busy === 'CREATE' ? '생성 중…' : '변경요청 생성'}</button>
        </div>
        {drifted && <div className="notice registration-source-warning" role="alert">미리보기 이후 DataHub 원본 또는 컬럼 구성이 변경되었습니다. 새 미리보기를 실행하세요.</div>}
        <ErrorNotice error={error} />
        {preview && <section className="registration-description-preview" aria-label="컬럼 설명 변경 미리보기" aria-live="polite"><header><strong>검증된 컬럼 변경 비교</strong><span className="badge">PREVIEW</span></header><dl><div><dt>Field path</dt><dd><code>{preview.field_path}</code></dd></div><div><dt>Source version</dt><dd><code>{preview.source_version}</code></dd></div><div className="wide"><dt>Before SHA-256</dt><dd><code>{preview.before_hash}</code></dd></div><div className="wide"><dt>After SHA-256</dt><dd><code>{preview.after_hash}</code></dd></div><div className="wide description-before"><dt>현재 원본 설명</dt><dd>{displayDescription(preview.current_description)}</dd></div><div className="wide description-after"><dt>제안 설명</dt><dd>{displayDescription(preview.proposed_description)}</dd></div></dl></section>}
        {proposal && <div className="notice registration-description-success" role="status"><strong>{proposal.number} 변경 요청을 생성했습니다.</strong><span>상태: {proposal.state}. 검토·승인 전에는 DataHub에 적용되지 않습니다.</span></div>}
      </form>
    </section>
  )
}
