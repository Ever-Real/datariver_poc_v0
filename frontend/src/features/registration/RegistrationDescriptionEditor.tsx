import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Eye, GitPullRequest } from 'lucide-react'
import { ApiError, newIdempotencyKey, type ApiClient } from '../../api/client'
import type {
  CatalogAssetDetail,
  CatalogDescriptionPreview,
  ChangeRequestRecord,
} from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'

const SHA256_PATTERN = /^[0-9a-f]{64}$/
const QUOTED_SHA256_ETAG_PATTERN = /^"[0-9a-f]{64}"$/

function isSourceDrift(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false
  const code = error.problem.code.toLowerCase()
  return error.problem.status === 409
    || error.problem.status === 412
    || code.includes('conflict')
    || code.includes('mismatch')
    || code.includes('stale')
    || code.includes('drift')
}

function descriptionValue(value: string | null): string {
  return value === '' || value === null ? '(빈 설명)' : value
}

export function RegistrationDescriptionEditor({
  client,
  asset,
}: {
  client: ApiClient
  asset: CatalogAssetDetail
}) {
  const [description, setDescription] = useState(asset.description ?? '')
  const [title, setTitle] = useState(`${asset.name} 설명 변경`)
  const [changeDescription, setChangeDescription] = useState('')
  const [preview, setPreview] = useState<CatalogDescriptionPreview>()
  const [proposal, setProposal] = useState<ChangeRequestRecord>()
  const [error, setError] = useState<unknown>()
  const [drifted, setDrifted] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [idempotencyKey, setIdempotencyKey] = useState<string>()
  const previewController = useRef<AbortController | null>(null)
  const submitController = useRef<AbortController | null>(null)
  const previewingGuard = useRef(false)
  const submittingGuard = useRef(false)
  const generation = useRef(0)

  useEffect(() => {
    generation.current += 1
    previewController.current?.abort()
    submitController.current?.abort()
    previewingGuard.current = false
    submittingGuard.current = false
    setDescription(asset.description ?? '')
    setTitle(`${asset.name} 설명 변경`)
    setChangeDescription('')
    setPreview(undefined)
    setProposal(undefined)
    setError(undefined)
    setDrifted(false)
    setPreviewing(false)
    setSubmitting(false)
    setIdempotencyKey(undefined)
    return () => {
      generation.current += 1
      previewController.current?.abort()
      submitController.current?.abort()
    }
  }, [asset.classification, asset.description, asset.id, asset.name, asset.source_version, client])

  const invalidateIntent = () => {
    generation.current += 1
    previewController.current?.abort()
    submitController.current?.abort()
    previewingGuard.current = false
    submittingGuard.current = false
    setPreviewing(false)
    setSubmitting(false)
    setPreview(undefined)
    setProposal(undefined)
    setIdempotencyKey(undefined)
    setError(undefined)
    setDrifted(false)
  }

  const previewDescription = async () => {
    if (previewingGuard.current || submittingGuard.current || proposal) return
    if (!title.trim() || !changeDescription.trim()) {
      setError(new Error('제목과 변경 사유를 입력한 뒤 미리보기를 실행하세요.'))
      return
    }
    previewingGuard.current = true
    setPreviewing(true)
    setPreview(undefined)
    setProposal(undefined)
    setIdempotencyKey(undefined)
    setError(undefined)
    setDrifted(false)
    const controller = new AbortController()
    previewController.current?.abort()
    previewController.current = controller
    const expectedGeneration = generation.current
    const proposedDescription = description
    try {
      const value = await client.request<CatalogDescriptionPreview>(
        `/catalog/assets/${asset.id}/description-previews`,
        {
          method: 'POST',
          signal: controller.signal,
          body: JSON.stringify({ description: proposedDescription }),
        },
      )
      if (controller.signal.aborted || expectedGeneration !== generation.current) return
      if (
        value.asset_id !== asset.id
        || value.target_ref !== asset.external_urn
        || value.aspect_name !== 'datasetProperties'
        || value.proposed_description !== proposedDescription
        || !SHA256_PATTERN.test(value.before_hash)
        || !SHA256_PATTERN.test(value.after_hash)
        || !QUOTED_SHA256_ETAG_PATTERN.test(value.preview_etag)
        || !value.source_version
      ) {
        throw new Error('서버가 자산 또는 hash가 일치하지 않는 미리보기를 반환했습니다.')
      }
      if (value.current_description === value.proposed_description || value.before_hash === value.after_hash) {
        throw new Error('현재 원본 설명과 동일하여 변경 요청을 만들 수 없습니다.')
      }
      setPreview(value)
    } catch (next) {
      if (!controller.signal.aborted && expectedGeneration === generation.current) setError(next)
    } finally {
      if (expectedGeneration === generation.current) {
        previewingGuard.current = false
        setPreviewing(false)
      }
    }
  }

  const submitProposal = async (event: FormEvent) => {
    event.preventDefault()
    if (submittingGuard.current || previewingGuard.current || proposal || !preview) return
    if (!title.trim() || !changeDescription.trim()) {
      setError(new Error('제목과 변경 사유를 입력하세요.'))
      return
    }
    if (preview.proposed_description !== description) {
      setPreview(undefined)
      setIdempotencyKey(undefined)
      setError(new Error('설명이 미리보기 이후 변경되었습니다. 미리보기를 다시 실행하세요.'))
      return
    }
    submittingGuard.current = true
    setSubmitting(true)
    setError(undefined)
    setDrifted(false)
    const controller = new AbortController()
    submitController.current?.abort()
    submitController.current = controller
    const expectedGeneration = generation.current
    const requestKey = idempotencyKey ?? newIdempotencyKey('description-change')
    setIdempotencyKey(requestKey)
    try {
      const value = await client.request<ChangeRequestRecord>(
        `/catalog/assets/${asset.id}/description-change-requests`,
        {
          method: 'POST',
          idempotencyKey: requestKey,
          ifMatch: preview.preview_etag,
          signal: controller.signal,
          body: JSON.stringify({
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
          setIdempotencyKey(undefined)
          setDrifted(true)
        }
        setError(next)
      }
    } finally {
      if (expectedGeneration === generation.current) {
        submittingGuard.current = false
        setSubmitting(false)
      }
    }
  }

  const projectedDescription = asset.description ?? ''
  const matchesProjection = description === projectedDescription
  const canPreview = title.trim().length > 0 && changeDescription.trim().length > 0
  const locked = submitting || Boolean(proposal)

  return (
    <section className="registration-description-editor" aria-labelledby="description-editor-title" aria-busy={previewing || submitting}>
      <header>
        <div>
          <span className="eyebrow">Typed metadata change</span>
          <h3 id="description-editor-title">설명 변경 제안</h3>
        </div>
        <span className="badge badge-soft">{asset.classification}</span>
      </header>
      <form className="form-stack" onSubmit={(event) => void submitProposal(event)}>
        <p className="callout" id="description-change-guidance">
          설명은 원문 그대로 처리됩니다. 빈 값은 설명 삭제 제안이며, DataHub의 현재 원본과 완전히 같은 제안은 서버가 거부합니다.
          제목·사유·설명을 수정하면 이전 미리보기와 제출 의도는 무효화됩니다.
        </p>
        {asset.stale_at && (
          <p className="notice registration-source-warning" role="status">
            화면의 projection이 stale 상태입니다. 미리보기에서 DataHub 원본과 source version을 다시 검증합니다.
          </p>
        )}
        <label htmlFor="description-change-title">
          변경 요청 제목
          <input
            id="description-change-title"
            value={title}
            maxLength={500}
            disabled={locked}
            onChange={(event) => { invalidateIntent(); setTitle(event.target.value) }}
            required
          />
        </label>
        <label htmlFor="description-change-reason">
          변경 사유
          <textarea
            id="description-change-reason"
            value={changeDescription}
            maxLength={10000}
            disabled={locked}
            onChange={(event) => { invalidateIntent(); setChangeDescription(event.target.value) }}
            required
          />
        </label>
        <label htmlFor="description-change-value">
          제안 설명
          <textarea
            id="description-change-value"
            value={description}
            maxLength={10000}
            disabled={locked}
            aria-describedby="description-change-guidance description-change-status"
            onChange={(event) => { invalidateIntent(); setDescription(event.target.value) }}
          />
        </label>
        <p className="registration-description-status" id="description-change-status">
          {matchesProjection
            ? '화면의 projection과 동일합니다. live 원본 검증 전에는 no-op 여부를 확정하지 않습니다.'
            : description === ''
              ? '빈 설명으로 변경하여 기존 설명을 삭제하도록 제안합니다.'
              : `${description.length.toLocaleString()}자 입력됨`}
        </p>
        <div className="registration-description-actions">
          <button
            className="button button-secondary"
            type="button"
            disabled={!canPreview || previewing || submitting || Boolean(proposal)}
            onClick={() => void previewDescription()}
          >
            <Eye size={14} aria-hidden="true" />{previewing ? '미리보기 확인 중…' : '변경 미리보기'}
          </button>
          <button className="button" type="submit" disabled={!preview || previewing || submitting || Boolean(proposal)}>
            <GitPullRequest size={14} aria-hidden="true" />{submitting ? '생성 중…' : '변경요청 생성'}
          </button>
        </div>

        {drifted && (
          <div className="notice registration-source-warning" role="alert">
            미리보기 이후 DataHub 원본이 변경되었습니다. 현재 오류를 확인하고 새 미리보기를 실행하세요.
          </div>
        )}
        <ErrorNotice error={error} />

        {preview && (
          <section className="registration-description-preview" aria-label="설명 변경 미리보기" aria-live="polite">
            <header><strong>검증된 변경 비교</strong><span className="badge">PREVIEW</span></header>
            {(preview.current_description ?? '') !== projectedDescription && (
              <p className="notice registration-source-warning" role="status">
                DataHub 원본 설명이 화면의 projection과 다릅니다. 아래 원본 값을 기준으로 요청합니다.
              </p>
            )}
            <dl>
              <div><dt>Aspect</dt><dd>{preview.aspect_name}</dd></div>
              <div><dt>Source version</dt><dd><code>{preview.source_version}</code></dd></div>
              <div><dt>Observed</dt><dd><time dateTime={preview.observed_at}>{preview.observed_at}</time></dd></div>
              <div className="wide"><dt>Before SHA-256</dt><dd><code>{preview.before_hash}</code></dd></div>
              <div className="wide"><dt>After SHA-256</dt><dd><code>{preview.after_hash}</code></dd></div>
              <div className="wide description-before"><dt>현재 원본 설명</dt><dd>{descriptionValue(preview.current_description)}</dd></div>
              <div className="wide description-after"><dt>제안 설명</dt><dd>{descriptionValue(preview.proposed_description)}</dd></div>
            </dl>
          </section>
        )}

        {proposal && (
          <div className="notice registration-description-success" role="status" aria-live="polite">
            <strong>{proposal.number} 변경 요청을 생성했습니다.</strong>
            <span>상태: {proposal.state}. 변경관리의 검토·승인 전에는 DataHub에 적용되지 않습니다.</span>
          </div>
        )}
      </form>
    </section>
  )
}
