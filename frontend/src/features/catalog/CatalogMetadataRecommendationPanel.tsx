import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { newIdempotencyKey, type ApiClient } from '../../api/client'
import type {
  CatalogAssetDetail,
  CatalogMetadataRecommendation,
  CatalogMetadataRecommendationApproval,
  CatalogMetadataRecommendationPreview,
  CatalogMetadataVocabularyItem,
  CatalogMetadataVocabularyPage,
} from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { Dialog } from '../../components/common/Dialog'

const PAGE_LIMIT = 20
const MAXIMUM_SELECTION = 100
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

function fieldPath(field: Record<string, unknown>): string | undefined {
  for (const key of ['fieldPath', 'field_path', 'name']) {
    const value = field[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return undefined
}

function boundedVocabularyPage(
  value: CatalogMetadataVocabularyPage,
  kind: 'TAG' | 'TERM',
): CatalogMetadataVocabularyPage {
  if (
    !Array.isArray(value.items)
    || value.items.length > PAGE_LIMIT
    || value.items.some((item) => (
      item.kind !== kind
      || !UUID_PATTERN.test(item.id)
      || !item.display_name?.trim()
      || item.display_name.length > 500
    ))
    || value.page.limit < 1
    || value.page.limit > PAGE_LIMIT
  ) throw new Error('추천 어휘 응답이 요청한 범위와 일치하지 않습니다.')
  return value
}

function boundedRecommendations(
  value: CatalogMetadataRecommendationPreview,
  assetId: string,
  selectedVocabulary: Set<string>,
): CatalogMetadataRecommendationPreview {
  if (
    value.auto_application !== 'DISABLED_NEEDS_DECISION'
    || !Array.isArray(value.items)
    || value.items.length > MAXIMUM_SELECTION
    || value.items.some((item) => (
      item.asset_id !== assetId
      || !selectedVocabulary.has(item.vocabulary_id)
      || !UUID_PATTERN.test(item.recommendation_id)
      || !Number.isFinite(item.confidence)
      || item.confidence < 0
      || item.confidence > 1
      || item.state !== 'NEEDS_DECISION'
      || !Array.isArray(item.evidence)
      || item.evidence.length < 1
      || item.evidence.length > 10
    ))
  ) throw new Error('추천 결과가 요청한 자산과 통제 어휘 범위를 벗어났습니다.')
  return value
}

function boundedApproval(
  value: CatalogMetadataRecommendationApproval,
  expected: CatalogMetadataRecommendation[],
): CatalogMetadataRecommendationApproval {
  const expectedIds = new Set(expected.map((item) => item.recommendation_id))
  if (
    value.auto_application !== 'DISABLED_NEEDS_DECISION'
    || !UUID_PATTERN.test(value.change_request_id)
    || !Array.isArray(value.items)
    || value.items.length !== expectedIds.size
    || value.items.some((item) => (
      !expectedIds.has(item.recommendation_id)
      || item.state !== 'APPROVED'
      || item.change_request_id !== value.change_request_id
    ))
    || new Set(value.items.map((item) => item.recommendation_id)).size !== value.items.length
  ) throw new Error('승인 결과가 확인한 추천 및 Change Request 범위와 일치하지 않습니다.')
  return value
}

function boundedRejection(
  value: CatalogMetadataRecommendation,
  expected: CatalogMetadataRecommendation,
): CatalogMetadataRecommendation {
  if (
    value.recommendation_id !== expected.recommendation_id
    || value.asset_id !== expected.asset_id
    || value.vocabulary_id !== expected.vocabulary_id
    || value.state !== 'REJECTED'
    || value.version <= expected.version
  ) throw new Error('반려 결과가 확인한 추천 범위와 일치하지 않습니다.')
  return value
}

function approvalTitle(assetName: string): string {
  return `${assetName.trim().slice(0, 470)} 메타데이터 추천 검토`
}

export function CatalogMetadataRecommendationPanel({
  client,
  detail,
}: {
  client: ApiClient
  detail: CatalogAssetDetail
}) {
  const [kind, setKind] = useState<'TAG' | 'TERM'>('TAG')
  const [queryInput, setQueryInput] = useState('')
  const [query, setQuery] = useState('')
  const [vocabularyPage, setVocabularyPage] = useState<CatalogMetadataVocabularyPage>()
  const [cursorStack, setCursorStack] = useState<string[]>([])
  const [vocabularyBusy, setVocabularyBusy] = useState(false)
  const [vocabularyError, setVocabularyError] = useState<unknown>()
  const [selectedVocabulary, setSelectedVocabulary] = useState<Map<string, CatalogMetadataVocabularyItem>>(new Map())
  const [targetFieldPath, setTargetFieldPath] = useState('')
  const [recommendations, setRecommendations] = useState<CatalogMetadataRecommendation[]>([])
  const [selectedRecommendations, setSelectedRecommendations] = useState<Set<string>>(new Set())
  const [previewBusy, setPreviewBusy] = useState(false)
  const [previewAttempted, setPreviewAttempted] = useState(false)
  const [previewError, setPreviewError] = useState<unknown>()
  const [decisionBusy, setDecisionBusy] = useState(false)
  const [decisionError, setDecisionError] = useState<unknown>()
  const [decisionReason, setDecisionReason] = useState('검토 후 메타데이터 변경 요청을 생성합니다.')
  const [confirmation, setConfirmation] = useState<
    { kind: 'APPROVE'; recommendations: CatalogMetadataRecommendation[]; idempotencyKey: string }
    | { kind: 'REJECT'; recommendations: [CatalogMetadataRecommendation]; idempotencyKey: string }
  >()
  const [changeRequestId, setChangeRequestId] = useState<string>()
  const activeRequest = useRef<AbortController | undefined>(undefined)
  const previewIdempotencyKey = useRef<string | undefined>(undefined)

  const fields = useMemo(() => [...new Set(detail.schema_fields.flatMap((field) => {
    const value = fieldPath(field)
    return value ? [value] : []
  }))].sort((left, right) => left.localeCompare(right)), [detail.schema_fields])
  const vocabularyById = useMemo(() => new Map([
    ...selectedVocabulary.entries(),
    ...(vocabularyPage?.items ?? []).map((item) => [item.id, item] as const),
  ]), [selectedVocabulary, vocabularyPage])

  const loadVocabulary = async (cursor?: string) => {
    activeRequest.current?.abort()
    const controller = new AbortController()
    activeRequest.current = controller
    setVocabularyBusy(true)
    setVocabularyError(undefined)
    try {
      const parameters = new URLSearchParams({ kind, limit: String(PAGE_LIMIT) })
      if (query) parameters.set('q', query)
      if (cursor) parameters.set('cursor', cursor)
      const value = await client.request<CatalogMetadataVocabularyPage>(
        `/uploads/metadata-vocabulary?${parameters.toString()}`,
        { cache: 'no-store', signal: controller.signal },
      )
      if (!controller.signal.aborted) setVocabularyPage(boundedVocabularyPage(value, kind))
    } catch (error) {
      if (!controller.signal.aborted) setVocabularyError(error)
    } finally {
      if (activeRequest.current === controller) activeRequest.current = undefined
      if (!controller.signal.aborted) setVocabularyBusy(false)
    }
  }

  useEffect(() => {
    setVocabularyPage(undefined)
    setCursorStack([])
    void loadVocabulary()
    return () => activeRequest.current?.abort()
    // The current kind/query define one exact bounded server-side vocabulary search.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, query])

  useEffect(() => {
    setRecommendations([])
    setSelectedRecommendations(new Set())
    setChangeRequestId(undefined)
    setPreviewAttempted(false)
    previewIdempotencyKey.current = undefined
  }, [detail.id, detail.source_version, targetFieldPath, selectedVocabulary])

  const submitVocabularySearch = (event: FormEvent) => {
    event.preventDefault()
    const normalized = queryInput.trim().slice(0, 200)
    setQueryInput(normalized)
    setQuery(normalized)
  }

  const toggleVocabulary = (item: CatalogMetadataVocabularyItem, checked: boolean) => {
    setSelectedVocabulary((current) => {
      const next = new Map(current)
      if (!checked) next.delete(item.id)
      else if (next.size < MAXIMUM_SELECTION) next.set(item.id, item)
      return next
    })
  }

  const preview = async () => {
    if (!selectedVocabulary.size) return
    setPreviewBusy(true)
    setPreviewAttempted(true)
    setPreviewError(undefined)
    setDecisionError(undefined)
    try {
      const value = await client.request<CatalogMetadataRecommendationPreview>(
        `/catalog/assets/${encodeURIComponent(detail.id)}/metadata-recommendation-previews`,
        {
          method: 'POST',
          cache: 'no-store',
          idempotencyKey: previewIdempotencyKey.current ??= newIdempotencyKey('catalog-metadata-recommendation-preview'),
          body: JSON.stringify({
            source_version: detail.source_version,
            field_path: targetFieldPath || null,
            vocabulary_ids: [...selectedVocabulary.keys()].sort(),
          }),
        },
      )
      const bounded = boundedRecommendations(value, detail.id, new Set(selectedVocabulary.keys()))
      setRecommendations(bounded.items)
      setSelectedRecommendations(new Set(bounded.items.map((item) => item.recommendation_id)))
    } catch (error) {
      setPreviewError(error)
    } finally {
      setPreviewBusy(false)
    }
  }

  const decide = async () => {
    if (!confirmation || !decisionReason.trim()) return
    setDecisionBusy(true)
    setDecisionError(undefined)
    try {
      if (confirmation.kind === 'APPROVE') {
        const value = await client.request<CatalogMetadataRecommendationApproval>(
          '/catalog/metadata-recommendations/approve',
          {
            method: 'POST',
            cache: 'no-store',
            idempotencyKey: confirmation.idempotencyKey,
            body: JSON.stringify({
              targets: confirmation.recommendations.map((item) => ({
                recommendation_id: item.recommendation_id,
                expected_version: item.version,
              })),
              title: approvalTitle(detail.name),
              reason: decisionReason.trim(),
            }),
          },
        )
        const bounded = boundedApproval(value, confirmation.recommendations)
        setChangeRequestId(bounded.change_request_id)
        setRecommendations((current) => current.map((item) => (
          bounded.items.find((updated) => updated.recommendation_id === item.recommendation_id) ?? item
        )))
      } else {
        const item = confirmation.recommendations[0]
        const value = await client.request<CatalogMetadataRecommendation>(
          `/catalog/metadata-recommendations/${encodeURIComponent(item.recommendation_id)}/reject`,
          {
            method: 'POST',
            cache: 'no-store',
            idempotencyKey: confirmation.idempotencyKey,
            body: JSON.stringify({ expected_version: item.version, reason: decisionReason.trim() }),
          },
        )
        const bounded = boundedRejection(value, item)
        setRecommendations((current) => current.map((candidate) => (
          candidate.recommendation_id === bounded.recommendation_id ? bounded : candidate
        )))
      }
      setConfirmation(undefined)
      setSelectedRecommendations(new Set())
    } catch (error) {
      setDecisionError(error)
    } finally {
      setDecisionBusy(false)
    }
  }

  const selectedForApproval = recommendations.filter((item) => (
    item.state === 'NEEDS_DECISION' && selectedRecommendations.has(item.recommendation_id)
  ))

  return <div className="catalog-recommendation-panel">
    <p className="muted">현재 권한 범위의 자산 정보와 선택한 통제 어휘를 비교합니다. 자동 적용은 비활성화되어 있습니다.</p>
    <label>추천 대상
      <select value={targetFieldPath} onChange={(event) => setTargetFieldPath(event.target.value)}>
        <option value="">현재 테이블</option>
        {fields.map((field) => <option key={field} value={field}>{field}</option>)}
      </select>
    </label>
    <form className="catalog-recommendation-search" onSubmit={submitVocabularySearch}>
      <label>어휘 종류
        <select value={kind} onChange={(event) => setKind(event.target.value as 'TAG' | 'TERM')}>
          <option value="TAG">태그</option><option value="TERM">용어</option>
        </select>
      </label>
      <label>표시명 검색
        <input maxLength={200} value={queryInput} onChange={(event) => setQueryInput(event.target.value)} />
      </label>
      <button className="button button-secondary" disabled={vocabularyBusy} type="submit">검색</button>
    </form>
    <ErrorNotice error={vocabularyError} />
    <div aria-label="추천 어휘 선택" className="catalog-recommendation-vocabulary">
      {vocabularyBusy && <p role="status">통제 어휘를 불러오는 중입니다.</p>}
      {!vocabularyBusy && vocabularyPage?.items.map((item) => <label key={item.id}>
        <input
          aria-label={item.display_name}
          checked={selectedVocabulary.has(item.id)}
          disabled={!selectedVocabulary.has(item.id) && selectedVocabulary.size >= MAXIMUM_SELECTION}
          onChange={(event) => toggleVocabulary(item, event.target.checked)}
          type="checkbox"
        />
        <span>{item.display_name}</span><small>{item.kind}</small>
      </label>)}
      {!vocabularyBusy && vocabularyPage?.items.length === 0 && <p>검색 조건에 맞는 통제 어휘가 없습니다.</p>}
    </div>
    <nav aria-label="추천 어휘 페이지" className="catalog-recommendation-pagination">
      <button className="button button-secondary" disabled={vocabularyBusy || cursorStack.length === 0} onClick={() => {
        const next = cursorStack.slice(0, -1); setCursorStack(next); void loadVocabulary(next.at(-1))
      }} type="button">이전</button>
      <button className="button button-secondary" disabled={vocabularyBusy || !vocabularyPage?.page.next_cursor} onClick={() => {
        const cursor = vocabularyPage?.page.next_cursor
        if (!cursor) return
        setCursorStack((current) => [...current, cursor].slice(-50)); void loadVocabulary(cursor)
      }} type="button">다음</button>
    </nav>
    {selectedVocabulary.size > 0 && <div className="catalog-recommendation-selected" aria-label="선택한 통제 어휘">
      {[...selectedVocabulary.values()].map((item) => <button key={item.id} className="badge badge-soft" onClick={() => toggleVocabulary(item, false)} type="button">{item.display_name} ×</button>)}
    </div>}
    <button className="button button-primary" disabled={previewBusy || selectedVocabulary.size === 0} onClick={() => void preview()} type="button">
      {previewBusy ? '추천 분석 중…' : `추천 미리보기 (${selectedVocabulary.size})`}
    </button>
    <ErrorNotice error={previewError} />
    {previewAttempted && !previewBusy && selectedVocabulary.size > 0 && recommendations.length === 0 && !previewError && <p className="muted">현재 메타데이터와 충분히 유사한 새 추천이 없습니다.</p>}
    {recommendations.length > 0 && <div className="catalog-recommendation-results" aria-label="메타데이터 추천 결과">
      {recommendations.map((item) => <article key={item.recommendation_id}>
        <label>
          <input checked={selectedRecommendations.has(item.recommendation_id)} disabled={item.state !== 'NEEDS_DECISION'} onChange={(event) => setSelectedRecommendations((current) => {
            const next = new Set(current); if (event.target.checked) next.add(item.recommendation_id); else next.delete(item.recommendation_id); return next
          })} type="checkbox" />
          <strong>{vocabularyById.get(item.vocabulary_id)?.display_name ?? '확인된 통제 어휘'}</strong>
        </label>
        <span className="badge">신뢰도 {Math.round(item.confidence * 100)}%</span>
        <p>{item.reason}</p>
        <ul>{item.evidence.map((evidence) => <li key={evidence}>{evidence}</li>)}</ul>
        <div><span className="badge badge-soft">{item.state}</span>{item.state === 'NEEDS_DECISION' && <button className="button button-secondary" onClick={() => setConfirmation({ kind: 'REJECT', recommendations: [item], idempotencyKey: newIdempotencyKey('catalog-metadata-recommendation-reject') })} type="button">반려</button>}</div>
      </article>)}
      <button className="button button-primary" disabled={selectedForApproval.length === 0 || selectedForApproval.length > MAXIMUM_SELECTION} onClick={() => setConfirmation({ kind: 'APPROVE', recommendations: selectedForApproval, idempotencyKey: newIdempotencyKey('catalog-metadata-recommendation-approve') })} type="button">선택 승인 요청 ({selectedForApproval.length})</button>
    </div>}
    <ErrorNotice error={decisionError} />
    {changeRequestId && <p role="status">변경 요청 <code>{changeRequestId}</code>을 생성했습니다. 적용은 Governance 승인 절차에서 진행됩니다.</p>}
    <Dialog
      open={Boolean(confirmation)}
      title={confirmation?.kind === 'APPROVE' ? '추천 승인 요청 확인' : '추천 반려 확인'}
      description={confirmation ? `${confirmation.recommendations.length}개 추천을 검토합니다.` : undefined}
      onRequestClose={() => { if (!decisionBusy) setConfirmation(undefined) }}
      footer={<>
        <button className="button button-secondary" disabled={decisionBusy} onClick={() => setConfirmation(undefined)} type="button">취소</button>
        <button className="button button-primary" disabled={decisionBusy || !decisionReason.trim()} onClick={() => void decide()} type="button">{decisionBusy ? '처리 중…' : '확인'}</button>
      </>}
    >
      <label>검토 사유<textarea maxLength={2000} value={decisionReason} onChange={(event) => setDecisionReason(event.target.value)} /></label>
      <p className="muted">승인은 메타데이터를 즉시 변경하지 않고 감사 가능한 Change Request를 생성합니다.</p>
    </Dialog>
  </div>
}
