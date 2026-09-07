import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronLeft, Network, X } from 'lucide-react'
import type { ApiClient } from '../../api/client'
import type {
  CatalogAssetBaseDetail,
  CatalogAssetDetail,
  CatalogAssetQualityDetail,
  CatalogAssetSchemaDetail,
  CatalogLineage,
  QualityAsset,
} from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { AccordionItem } from '../../components/common/Accordion'
import { BadgeScroller } from '../../components/common/ControlledVocabularyInput'
import { TruncatedText } from '../../components/common/TruncatedText'
import { CatalogLineageGraph } from './CatalogLineageGraph'
import type { CytoscapeViewport } from '../../components/graph/CytoscapeReadGraph'
import { CatalogMetadataRecommendationPanel } from './CatalogMetadataRecommendationPanel'
import { CatalogEmptyValue } from './CatalogEmptyValue'
import { basisPointsText, dateTimeText, QualityStatus } from '../quality/QualityShared'

function valueOf(document: Record<string, unknown>, ...keys: string[]): string | undefined {
  for (const key of keys) {
    const value = document[key]
    if (typeof value === 'string' && value) return value
  }
  return undefined
}

function referenceValues(value: unknown, collection: string, reference: string): string[] {
  const document = value as Record<string, unknown> | undefined
  const items = document?.[collection]
  if (!Array.isArray(items)) return []
  return [...new Set(items.flatMap((item) => {
    const target = (item as Record<string, unknown> | undefined)?.[reference] as Record<string, unknown> | undefined
    const label = target?.name ?? target?.urn
    return typeof label === 'string' && label ? [label] : []
  }))]
}

function ownerValues(ownership: Array<Record<string, unknown>>): string[] {
  return [...new Set(ownership.flatMap((entry) => {
    const owner = entry.owner as Record<string, unknown> | undefined
    const value = owner?.displayName ?? owner?.username ?? owner?.urn
    return typeof value === 'string' && value ? [value] : []
  }))]
}

function formatObservedValue(value: unknown, unit?: string): string | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return `${value.toLocaleString()}${unit ?? ''}`
  if (typeof value === 'string' && value.trim()) return `${value}${unit ?? ''}`
  return undefined
}

function detailText(value: string | null | undefined, truncated = false) {
  if (!value?.trim()) return <CatalogEmptyValue />
  return <span>{value}{truncated && <span aria-label="일부만 표시" title="응답 크기 제한으로 일부 내용만 표시됩니다."> …</span>}</span>
}

function providerMissing(label: string, title: string) {
  return <span className="catalog-provider-missing" title={title}>{label}</span>
}

function fieldValues(field: Record<string, unknown>, key: 'globalTags' | 'glossaryTerms'): string[] {
  return key === 'globalTags'
    ? referenceValues(field[key], 'tags', 'tag')
    : referenceValues(field[key], 'terms', 'term')
}

function fieldFlag(field: Record<string, unknown>, key: string): boolean {
  return field[key] === true
}

const allowedDetailInteractionSelector = [
  '[data-catalog-detail-interaction]',
  'dialog[open]',
  '[role="listbox"]',
  '[role="tooltip"]',
  '.controlled-vocabulary-menu',
  '.catalog-results tbody tr.interactive',
].join(',')

function detailInteractionIsAllowed(event: Event, panel: HTMLElement | null): boolean {
  return event.composedPath().some((entry) => (
    entry === panel
    || (entry instanceof Node && Boolean(panel?.contains(entry)))
    || (entry instanceof Element && entry.matches(allowedDetailInteractionSelector))
  ))
}

function documentHasSelection(): boolean {
  const selection = document.getSelection()
  return Boolean(selection && !selection.isCollapsed)
}

export function snapDetailWidth(raw: number): number {
  const buckets = [320, 400, 480, 550, 640, 720, 800, 900]
  let closest = 320
  let minDiff = Infinity
  for (const b of buckets) {
    const diff = Math.abs(b - raw)
    if (diff < minDiff) {
      minDiff = diff
      closest = b
    }
  }
  return closest
}

export interface CatalogDetailViewState {
  activeTab: 'metadata' | 'lineage'
  expandedSections: string[]
  fieldOffset: number
  scrollTop: number
  focusKey?: string
  selectedLineageNodeId?: string
  lineageViewport?: CytoscapeViewport
}

export const defaultCatalogDetailViewState: CatalogDetailViewState = {
  activeTab: 'metadata',
  expandedSections: ['details', 'columns'],
  fieldOffset: 0,
  scrollTop: 0,
}

export function CatalogDetailPane({
  client,
  assetId,
  onClose,
  onPrevious,
  onDetailLoaded,
  onSelectAsset,
  onResizeWidth,
  width,
  qualitySummary,
  showQualityEvidence = false,
  qualityReadAvailable = false,
  qualityLoading = false,
  asOverlay = false,
  asModal = false,
  initialViewState = defaultCatalogDetailViewState,
  onViewStateChange,
}: {
  client: ApiClient
  assetId: string
  onClose: () => void
  onPrevious?: () => void
  onDetailLoaded?: (detail?: CatalogAssetDetail) => void
  onSelectAsset?: (assetId: string, sourceViewState?: CatalogDetailViewState) => void
  onResizeWidth?: (width: number) => void
  width?: number
  qualitySummary?: QualityAsset
  showQualityEvidence?: boolean
  qualityReadAvailable?: boolean
  qualityLoading?: boolean
  /** true이면 오버레이(fixed positioning) 방식으로 렌더링 */
  asOverlay?: boolean
  /** true이면 document portal 안의 중앙 모달 surface를 채웁니다. */
  asModal?: boolean
  initialViewState?: CatalogDetailViewState
  onViewStateChange?: (state: CatalogDetailViewState) => void
}) {
  const [expanded, setExpanded] = useState(new Set(initialViewState.expandedSections))
  const [activeTab, setActiveTab] = useState<'metadata' | 'lineage'>(initialViewState.activeTab)
  const [copied, setCopied] = useState(false)
  const [toastVisible, setToastVisible] = useState(false)
  const [fieldOffset, setFieldOffset] = useState(initialViewState.fieldOffset)
  const copyFeedbackTimer = useRef<number | undefined>(undefined)
  const panelRef = useRef<HTMLElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const viewStateRef = useRef<CatalogDetailViewState>({
    ...initialViewState,
    expandedSections: [...initialViewState.expandedSections],
  })
  const pagedAssetId = useRef(assetId)

  const updateViewState = useCallback((patch: Partial<CatalogDetailViewState>) => {
    const next = { ...viewStateRef.current, ...patch }
    viewStateRef.current = next
    onViewStateChange?.(next)
  }, [onViewStateChange])

  const { data: baseDetail, isFetching: loading, error } = useQuery({
    queryKey: ['catalog', 'asset-detail-base', assetId],
    queryFn: ({ signal }) => client.request<CatalogAssetBaseDetail>(
      `/catalog/assets/${assetId}`, {
        signal,
        headers: { 'X-DataRiver-Detail-Scope': 'BASE' },
      },
    ),
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
  })
  const embeddedDetail = baseDetail as Partial<CatalogAssetDetail> | undefined
  const baseIncludesSchema = Array.isArray(embeddedDetail?.schema_fields)
  const baseIncludesQuality = Boolean(embeddedDetail?.quality && typeof embeddedDetail.quality === 'object')

  const { data: schemaDetail, isFetching: schemaLoading, error: schemaError } = useQuery({
    queryKey: ['catalog', 'asset-detail-schema', assetId, fieldOffset, baseDetail?.source_version],
    queryFn: ({ signal }) => client.request<CatalogAssetSchemaDetail>(
      `/catalog/assets/${assetId}?${new URLSearchParams({
        detail_scope: 'SCHEMA',
        field_offset: String(fieldOffset),
        field_limit: '100',
        field_source_version: baseDetail?.source_version ?? '',
      })}`,
      { signal },
    ),
    enabled: Boolean(baseDetail && expanded.has('columns') && !baseIncludesSchema),
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
  })

  const { data: qualityDetail, isFetching: detailQualityLoading, error: detailQualityError } = useQuery({
    queryKey: ['catalog', 'asset-detail-quality', assetId, baseDetail?.source_version],
    queryFn: ({ signal }) => client.request<CatalogAssetQualityDetail>(
      `/catalog/assets/${assetId}?${new URLSearchParams({
        detail_scope: 'QUALITY', source_version: baseDetail?.source_version ?? '',
      })}`,
      { signal },
    ),
    enabled: Boolean(baseDetail && expanded.has('details') && !baseIncludesQuality),
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
  })

  const detail = useMemo<CatalogAssetDetail | undefined>(() => baseDetail ? {
    ...baseDetail,
    schema_fields: schemaDetail?.schema_fields ?? embeddedDetail?.schema_fields ?? [],
    schema_fields_total: schemaDetail?.schema_fields_total ?? embeddedDetail?.schema_fields_total ?? 0,
    schema_fields_available: schemaDetail?.schema_fields_available ?? embeddedDetail?.schema_fields_available ?? 0,
    schema_fields_truncated: schemaDetail?.schema_fields_truncated ?? embeddedDetail?.schema_fields_truncated ?? false,
    schema_fields_total_exact: schemaDetail?.schema_fields_total_exact ?? embeddedDetail?.schema_fields_total_exact ?? true,
    schema_fields_offset: schemaDetail?.schema_fields_offset ?? embeddedDetail?.schema_fields_offset ?? fieldOffset,
    schema_fields_limit: schemaDetail?.schema_fields_limit ?? embeddedDetail?.schema_fields_limit ?? 100,
    schema_fields_has_more: schemaDetail?.schema_fields_has_more ?? embeddedDetail?.schema_fields_has_more ?? false,
    quality: qualityDetail?.quality ?? embeddedDetail?.quality ?? {},
  } : undefined, [baseDetail, embeddedDetail, fieldOffset, qualityDetail?.quality, schemaDetail])

  // onDetailLoaded 콜백 처리
  useEffect(() => {
    if (detail) onDetailLoaded?.(detail)
    else onDetailLoaded?.(undefined)
  }, [detail, onDetailLoaded])

  useEffect(() => {
    if (!detail || !scrollRef.current) return
    if (typeof scrollRef.current.scrollTo === 'function') {
      scrollRef.current.scrollTo({ top: initialViewState.scrollTop })
    } else {
      const descriptor = Object.getOwnPropertyDescriptor(scrollRef.current, 'scrollTop')
      if (!descriptor || descriptor.writable) scrollRef.current.scrollTop = initialViewState.scrollTop
    }
    const focusTarget = initialViewState.focusKey
      ? [...(panelRef.current?.querySelectorAll<HTMLElement>('[data-catalog-focus-key]') ?? [])]
        .find((element) => element.dataset.catalogFocusKey === initialViewState.focusKey)
      : undefined
    focusTarget?.focus()
  }, [detail, initialViewState.focusKey, initialViewState.scrollTop])

  useEffect(() => {
    updateViewState({ expandedSections: [...expanded] })
  }, [expanded, updateViewState])

  const { data: lineage, isFetching: lineageLoading, error: lineageError } = useQuery({
    queryKey: ['catalog', 'lineage', assetId],
    queryFn: async ({ signal }) => client.request<CatalogLineage>(`/catalog/assets/${assetId}/lineage?direction=BOTH&depth=2`, { signal }),
    enabled: activeTab === 'lineage',
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
  })

  const onCloseRef = useRef(onClose)
  useEffect(() => {
    onCloseRef.current = onClose
  }, [onClose])

  useEffect(() => {
    if (!asOverlay && !asModal) return
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
    let pointerStart: { x: number; y: number } | undefined
    let dragged = false
    let suppressClick = false
    let clickListenerAttached = false
    let disposed = false

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onCloseRef.current()
      }
    }

    const handlePointerDown = (event: PointerEvent) => {
      if (!event.isPrimary || event.button !== 0) return
      pointerStart = { x: event.clientX, y: event.clientY }
      dragged = false
    }

    const handlePointerMove = (event: PointerEvent) => {
      if (!pointerStart) return
      if (
        Math.abs(event.clientX - pointerStart.x) > 4
        || Math.abs(event.clientY - pointerStart.y) > 4
      ) dragged = true
    }

    const handlePointerUp = () => {
      if (dragged) {
        suppressClick = true
        window.setTimeout(() => { suppressClick = false }, 0)
      }
      pointerStart = undefined
      dragged = false
    }

    const handleClickOutside = (event: MouseEvent) => {
      if (!asOverlay) return
      if (suppressClick || documentHasSelection()) return
      if (!detailInteractionIsAllowed(event, panelRef.current)) onCloseRef.current()
    }

    document.addEventListener('keydown', handleKeyDown)
    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('pointermove', handlePointerMove)
    document.addEventListener('pointerup', handlePointerUp)
    queueMicrotask(() => {
      if (disposed) return
      document.addEventListener('click', handleClickOutside)
      clickListenerAttached = true
    })
    return () => {
      disposed = true
      document.removeEventListener('keydown', handleKeyDown)
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('pointermove', handlePointerMove)
      document.removeEventListener('pointerup', handlePointerUp)
      if (clickListenerAttached) document.removeEventListener('click', handleClickOutside)
      if (opener?.isConnected) opener.focus()
    }
  }, [asOverlay, asModal])

  useEffect(() => {
    if (pagedAssetId.current !== assetId) {
      pagedAssetId.current = assetId
      if (fieldOffset !== 0) {
        setFieldOffset(0)
      }
    }
  }, [assetId, fieldOffset])


  const toggle = (section: string) => {
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(section)) next.delete(section); else next.add(section)
      return next
    })
  }

  const showTab = (tab: 'metadata' | 'lineage') => {
    setActiveTab(tab)
    updateViewState({ activeTab: tab, focusKey: `${tab}-tab` })
  }

  const selectLineageAsset = (assetId: string) => {
    // Capture the parent lineage subview before replacing this detail pane.
    // This is synchronous so Previous cannot race a pending React render.
    const sourceViewState: CatalogDetailViewState = {
      ...viewStateRef.current,
      activeTab: 'lineage',
      selectedLineageNodeId: assetId,
      focusKey: 'lineage-tab',
    }
    viewStateRef.current = sourceViewState
    setActiveTab('lineage')
    onViewStateChange?.(sourceViewState)
    onSelectAsset?.(assetId, sourceViewState)
  }

  const copyUrn = async () => {
    if (!detail) return
    try {
      await navigator.clipboard.writeText(detail.external_urn)
    } catch {
      const input = document.createElement('textarea')
      input.value = detail.external_urn
      input.setAttribute('readonly', '')
      input.className = 'catalog-copy-fallback'
      document.body.append(input)
      input.select()
      document.execCommand('copy')
      input.remove()
    }
    setCopied(true)
    setToastVisible(true)
    if (copyFeedbackTimer.current) window.clearTimeout(copyFeedbackTimer.current)
    copyFeedbackTimer.current = window.setTimeout(() => { setCopied(false); setToastVisible(false) }, 2_000)
  }

  const startResize = (event: React.PointerEvent<HTMLButtonElement>) => {
    if (!onResizeWidth) return
    event.preventDefault()
    const target = event.currentTarget
    target.setPointerCapture(event.pointerId)
    const startX = event.clientX
    const startWidth = width ?? 550
    const move = (next: PointerEvent) => onResizeWidth(snapDetailWidth(startWidth + startX - next.clientX))
    const stop = (stopEvent: PointerEvent) => {
      target.releasePointerCapture(stopEvent.pointerId)
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', stop)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', stop, { once: true })
  }

  // 오버레이 모드에서는 Backdrop + fixed aside로 렌더링
  return (
    <>
      {/* Backdrop: 오버레이 모드에서 배경 dimming + 본문 스크롤 잠금 */}
      {asOverlay && (
        <div
          className="catalog-detail-backdrop catalog-detail-backdrop--inert"
          aria-hidden="true"
        />
      )}
      {/* URN 복사 Toast 알림 */}
      {toastVisible && (
        <div className="catalog-urn-toast" role="status" aria-live="polite">
          ✓ URN이 클립보드에 복사되었습니다
        </div>
      )}
      <aside
        ref={panelRef}
        className={`catalog-detail panel${asOverlay ? ' catalog-detail--overlay' : ''}${asModal ? ' catalog-detail--modal' : ''} ${width ? `catalog-detail-w${snapDetailWidth(width)}` : ''}`}
        aria-label="카탈로그 상세"
        onFocusCapture={(event) => {
          const key = event.target.closest<HTMLElement>('[data-catalog-focus-key]')?.dataset.catalogFocusKey
          if (key) updateViewState({ focusKey: key })
        }}
      >
      {onResizeWidth && <button aria-label="상세 패널 너비 조절" className="catalog-detail-resizer" onKeyDown={(event) => {
        if (event.key === 'ArrowLeft') { event.preventDefault(); onResizeWidth(snapDetailWidth((width ?? 550) + 50)) }
        if (event.key === 'ArrowRight') { event.preventDefault(); onResizeWidth(snapDetailWidth((width ?? 550) - 50)) }
      }} onPointerDown={startResize} title="왼쪽으로 끌어 상세 폭 조절" type="button" />}
      <header>
        <div><span className="eyebrow">Authorized detail</span><h2>{detail?.name ?? '상세 정보'}</h2></div>
        <div className="catalog-detail-header-actions">
          <button className="button button-secondary" data-catalog-focus-key="previous" disabled={!onPrevious} onClick={onPrevious} type="button"><ChevronLeft size={14} aria-hidden="true" />이전</button>
          <button type="button" data-catalog-focus-key="close" aria-label="상세 닫기" onClick={onClose}><X size={16} /></button>
        </div>
      </header>
      <div ref={scrollRef} className="catalog-detail-scroll" onScroll={(event) => updateViewState({ scrollTop: event.currentTarget.scrollTop })}>
      {loading && <div className="catalog-detail-state">상세 정보를 불러오는 중입니다.</div>}
      <ErrorNotice error={error} />
      {detail && <div className="catalog-detail-body">
        <div className="catalog-detail-identity">
          <div className="catalog-detail-badges"><span className="badge">{detail.asset_type}</span><span className="badge badge-soft">{detail.classification}</span>{detail.stale_at && <span className="badge badge-warning">STALE</span>}</div>
          {/* URN 텍스트 자체를 클릭하면 복사 */}
          <button
            type="button"
            className={`catalog-detail-urn catalog-detail-urn--clickable${copied ? ' copied' : ''}`}
            onClick={() => void copyUrn()}
            title={copied ? '✓ 복사됨!' : 'URN 클릭 시 클립보드에 복사'}
            aria-label="URN 복사 (클릭)"
          >
            <TruncatedText value={detail.external_urn} />
          </button>
        </div>
        {showQualityEvidence && <section
          className="catalog-quality-evidence"
          aria-label="최근 품질 검사 Evidence"
        >
          <div>
            <span className="eyebrow">Latest quality evidence</span>
            <strong>최근 품질 점수</strong>
          </div>
          {qualityLoading
            ? <div className="catalog-quality-evidence-value empty">
              <b>확인 중…</b>
            </div>
            : !qualityReadAvailable
              ? <div className="catalog-quality-evidence-value empty">
                <b>표시 불가</b>
                <small>품질 열람 권한이 있을 때 최근 결과를 표시합니다.</small>
              </div>
              : qualitySummary?.latest_quality_outcome
            ? <div className="catalog-quality-evidence-value">
              <b>{basisPointsText(qualitySummary.latest_score_basis_points)}</b>
              <QualityStatus value={qualitySummary.latest_quality_outcome} />
              <small>최근 완료 검사 {qualitySummary.latest_run_state ?? '—'}</small>
            </div>
            : <div className="catalog-quality-evidence-value empty">
              <b>검사 이력 없음</b>
              <small>최근 품질 실행 결과가 아직 없습니다.</small>
            </div>}
          {qualitySummary?.profile_observed_at && (
            <small>Profile 관측 {dateTimeText(qualitySummary.profile_observed_at)}</small>
          )}
        </section>}
      <div className="catalog-detail-tabs" role="tablist" aria-label="상세 정보 보기">
        <button aria-controls="catalog-metadata-panel" aria-selected={activeTab === 'metadata'} className={activeTab === 'metadata' ? 'active' : ''} data-catalog-focus-key="metadata-tab" id="catalog-metadata-tab" onClick={() => showTab('metadata')} role="tab" type="button">Table Details</button>
        <button aria-controls="catalog-lineage-panel" aria-selected={activeTab === 'lineage'} className={activeTab === 'lineage' ? 'active' : ''} data-catalog-focus-key="lineage-tab" id="catalog-lineage-tab" onClick={() => showTab('lineage')} role="tab" type="button">Lineage</button>
      </div>
      <section aria-labelledby="catalog-metadata-tab" hidden={activeTab !== 'metadata'} id="catalog-metadata-panel" role="tabpanel">
        <AccordionItem itemId="details" focusKey="details-accordion" title="Table details" summary={`${detail.schema_fields_total ?? detail.schema_fields.length} fields`} expanded={expanded.has('details')} onToggle={() => toggle('details')}>
          {detailQualityLoading && <div className="catalog-detail-state" role="status">프로필과 assertion을 불러오는 중입니다.</div>}
          <ErrorNotice error={detailQualityError} />
          <dl className="catalog-detail-properties">
            <div><dt>Platform</dt><dd>{detailText(detail.platform)}</dd></div>
            <div><dt>Database</dt><dd>{detailText(detail.database_name)}</dd></div>
            <div><dt>Schema</dt><dd>{detailText(detail.schema_name)}</dd></div>
            <div><dt>Domain</dt><dd>{detailText(detail.domain)}</dd></div>
            <div><dt>Owner</dt><dd>{detailText(ownerValues(detail.ownership).join(', ') || detail.owner, detail.ownership_truncated)}</dd></div>
            <div><dt>Rows</dt><dd>{formatObservedValue(detail.quality?.rowCount ?? detail.quality?.rows)
              ? detailText(formatObservedValue(detail.quality?.rowCount ?? detail.quality?.rows))
              : providerMissing('Profile 미수집', 'DataHub full-table DatasetProfile 또는 허용된 row-count 속성에 관측값이 없습니다.')}</dd></div>
            <div><dt>Size</dt><dd>{formatObservedValue(detail.quality?.sizeInBytes ?? detail.quality?.size, ' B')
              ? detailText(formatObservedValue(detail.quality?.sizeInBytes ?? detail.quality?.size, ' B'))
              : providerMissing('Profile 미수집', 'DataHub full-table DatasetProfile 또는 허용된 byte-size 속성에 관측값이 없습니다.')}</dd></div>
            <div><dt>Created Date</dt><dd>{detail.created_at
              ? detailText(new Date(detail.created_at).toLocaleString())
              : providerMissing('메타데이터 미등록', 'DataHub DatasetProperties의 created 또는 허용된 생성일 속성에 관측값이 없습니다.')}</dd></div>
            <div className="wide"><dt>Description</dt><dd>{detailText(detail.description, detail.description_truncated)}</dd></div>
            <div className="metadata-vocabulary"><dt>Terms</dt><dd><BadgeScroller label="테이블 Terms" values={detail.terms ?? []} truncated={detail.terms_truncated} /></dd></div>
            <div className="metadata-vocabulary"><dt>Tags</dt><dd><BadgeScroller label="테이블 Tags" values={detail.tags} truncated={detail.tags_truncated} /></dd></div>
          </dl>
        </AccordionItem>
        <AccordionItem itemId="columns" focusKey="columns-accordion" title="Column metadata" summary={`${detail.schema_fields_total ?? detail.schema_fields.length} columns`} expanded={expanded.has('columns')} onToggle={() => toggle('columns')}>
          {schemaLoading && <div className="catalog-detail-state" role="status">컬럼 메타데이터를 불러오는 중입니다.</div>}
          <ErrorNotice error={schemaError} />
          <div className="catalog-schema-table">
            {detail.schema_fields_truncated && <div className="catalog-detail-state" role="status">원본 {detail.schema_fields_total_exact ? '' : '최소 '}{detail.schema_fields_total.toLocaleString()}개 중 메모리 보호 상한인 {detail.schema_fields_available.toLocaleString()}개 컬럼만 제공합니다.</div>}
            <table><caption className="sr-only">스키마 필드</caption><thead><tr><th>Column</th><th>Type</th><th>Description</th><th>Terms</th><th>Tags</th></tr></thead>
              <tbody>{detail.schema_fields.map((field, index) => {
                const fieldName = valueOf(field, 'fieldPath', 'field_path', 'name')
                const type = valueOf(field, 'nativeDataType', 'native_data_type', 'type')
                const description = valueOf(field, 'description')
                const typeTruncated = field.nativeDataType
                  ? fieldFlag(field, 'nativeDataType_truncated')
                  : fieldFlag(field, 'type_truncated')
                return (
                  <tr key={`${fieldName ?? 'unknown'}-${index}`}>
                    <td>{fieldName ? <TruncatedText value={fieldName} /> : <CatalogEmptyValue />}</td>
                    {/* type 필드: 한 줄 ellipsis + hover tooltip */}
                    <td>
                      {type
                        ? <span className="catalog-schema-type" title={typeTruncated ? `${type} (잘림)` : type}>{type}{typeTruncated && <span aria-label="일부만 표시"> …</span>}</span>
                        : <CatalogEmptyValue />}
                    </td>
                    <td title={typeof description === 'string' ? description : undefined}>{detailText(description, fieldFlag(field, 'description_truncated'))}</td>
                    <td><BadgeScroller label={`${fieldName ?? 'Column'} Terms`} values={fieldValues(field, 'glossaryTerms')} truncated={fieldFlag(field, 'terms_truncated')} /></td>
                    <td><BadgeScroller label={`${fieldName ?? 'Column'} Tags`} values={fieldValues(field, 'globalTags')} truncated={fieldFlag(field, 'tags_truncated')} /></td>
                  </tr>
                )
              })}</tbody>
            </table>
            {detail.schema_fields.length === 0 && <div className="catalog-detail-state">스키마 필드가 등록되지 않았습니다.</div>}
            {(detail.schema_fields_available ?? detail.schema_fields_total ?? detail.schema_fields.length) > detail.schema_fields.length && <nav aria-label="컬럼 페이지 탐색" className="pagination-bar">
              <button className="button button-secondary" disabled={(detail.schema_fields_offset ?? 0) === 0} onClick={() => { const next = Math.max(0, (detail.schema_fields_offset ?? 0) - (detail.schema_fields_limit ?? 100)); setFieldOffset(next); updateViewState({ fieldOffset: next }) }} type="button">이전 컬럼</button>
              <span>{(detail.schema_fields_offset ?? 0) + 1}–{(detail.schema_fields_offset ?? 0) + detail.schema_fields.length} / {detail.schema_fields_available ?? detail.schema_fields_total}</span>
              <button className="button button-secondary" disabled={!detail.schema_fields_has_more} onClick={() => { const next = (detail.schema_fields_offset ?? 0) + (detail.schema_fields_limit ?? 100); setFieldOffset(next); updateViewState({ fieldOffset: next }) }} type="button">다음 컬럼</button>
            </nav>}
          </div>
        </AccordionItem>
        <AccordionItem itemId="recommendations" focusKey="recommendations-accordion" title="Metadata recommendations" summary="review required" expanded={expanded.has('recommendations')} onToggle={() => toggle('recommendations')}>
          {expanded.has('recommendations') && <CatalogMetadataRecommendationPanel client={client} detail={detail} />}
        </AccordionItem>
      </section>
      <section aria-labelledby="catalog-lineage-tab" hidden={activeTab !== 'lineage'} id="catalog-lineage-panel" role="tabpanel">
        {lineageLoading && <div className="catalog-detail-state">권한 필터링된 lineage를 불러오는 중입니다.</div>}
        <ErrorNotice error={lineageError} />
        {lineage && <div className="catalog-lineage">
          <div className="catalog-lineage-summary"><Network size={15} /><span>{lineage.nodes.length} nodes · {lineage.edges.length} edges</span>{lineage.truncated && <b>일부 경로 생략</b>}</div>
          <CatalogLineageGraph
            client={client}
            lineage={lineage}
            onSelectAsset={selectLineageAsset}
            selectedNodeId={initialViewState.selectedLineageNodeId}
            initialViewport={initialViewState.lineageViewport}
            onSelectedNodeChange={(selectedLineageNodeId) => updateViewState({ selectedLineageNodeId })}
            onViewportChange={(lineageViewport) => updateViewState({ lineageViewport })}
          />
          {lineage.edges.length === 0 && <div className="catalog-detail-state">표시 가능한 연결 관계가 없습니다.</div>}
        </div>}
      </section>
      </div>}
      </div>
      </aside>
    </>
  )
}
