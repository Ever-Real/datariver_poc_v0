import { useEffect, useRef, useState } from 'react'
import { Network, X } from 'lucide-react'
import type { ApiClient } from '../../api/client'
import type { CatalogAssetDetail, CatalogLineage } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { AccordionItem } from '../../components/common/Accordion'
import { BadgeScroller } from '../../components/common/ControlledVocabularyInput'
import { TruncatedText } from '../../components/common/TruncatedText'
import { CatalogLineageGraph } from './CatalogLineageGraph'
import { CatalogEmptyValue } from './CatalogEmptyValue'

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

function fieldValues(field: Record<string, unknown>, key: 'globalTags' | 'glossaryTerms'): string[] {
  return key === 'globalTags'
    ? referenceValues(field[key], 'tags', 'tag')
    : referenceValues(field[key], 'terms', 'term')
}

function fieldFlag(field: Record<string, unknown>, key: string): boolean {
  return field[key] === true
}

export function CatalogDetailPane({
  client,
  assetId,
  onClose,
  onDetailLoaded,
  onSelectAsset,
  onResizeWidth,
  width,
  asOverlay = false,
}: {
  client: ApiClient
  assetId: string
  onClose: () => void
  onDetailLoaded?: (detail?: CatalogAssetDetail) => void
  onSelectAsset?: (assetId: string) => void
  onResizeWidth?: (width: number) => void
  width?: number
  /** true이면 오버레이(fixed positioning) 방식으로 렌더링 */
  asOverlay?: boolean
}) {
  const [detail, setDetail] = useState<CatalogAssetDetail>()
  const [lineage, setLineage] = useState<CatalogLineage>()
  const [expanded, setExpanded] = useState(new Set(['details', 'columns']))
  const [activeTab, setActiveTab] = useState<'metadata' | 'lineage'>('metadata')
  const [loading, setLoading] = useState(true)
  const [lineageLoading, setLineageLoading] = useState(false)
  const [error, setError] = useState<unknown>()
  const [lineageError, setLineageError] = useState<unknown>()
  const [copied, setCopied] = useState(false)
  const [toastVisible, setToastVisible] = useState(false)
  const [fieldOffset, setFieldOffset] = useState(0)
  const lineageController = useRef<AbortController | null>(null)
  const copyFeedbackTimer = useRef<number | undefined>(undefined)
  const pagedAssetId = useRef(assetId)
  const fieldSourceVersion = useRef<string | undefined>(undefined)

  useEffect(() => {
    if (!asOverlay) return
    const handleClickOutside = (event: MouseEvent) => {
      // panel 외부 영역 클릭 시 닫기
      const target = event.target as Node
      const panel = document.querySelector('.catalog-detail.panel')
      if (panel && !panel.contains(target)) {
        onClose()
      }
    }
    // mousedown으로 캡처 (클릭이 뒤쪽 요소에 전달되기 전에 먼저 닫힘)
    document.addEventListener('mousedown', handleClickOutside)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [asOverlay, onClose])

  useEffect(() => {
    if (pagedAssetId.current !== assetId) {
      pagedAssetId.current = assetId
      fieldSourceVersion.current = undefined
      if (fieldOffset !== 0) {
        setFieldOffset(0)
        return
      }
    }
    const controller = new AbortController()
    lineageController.current?.abort()
    onDetailLoaded?.(undefined)
    setLoading(true); setError(undefined); setDetail(undefined); setLineage(undefined)
    const fieldQuery = fieldOffset > 0
      ? `?${new URLSearchParams({
        field_offset: String(fieldOffset),
        field_limit: '100',
        ...(fieldSourceVersion.current ? { field_source_version: fieldSourceVersion.current } : {}),
      })}`
      : ''
    void client.request<CatalogAssetDetail>(`/catalog/assets/${assetId}${fieldQuery}`, { signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted) {
          if (fieldOffset === 0) fieldSourceVersion.current = value.source_version
          setDetail(value)
          onDetailLoaded?.(value)
        }
      })
      .catch((next: unknown) => { if (!controller.signal.aborted) setError(next) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => {
      controller.abort()
      lineageController.current?.abort()
      if (copyFeedbackTimer.current) window.clearTimeout(copyFeedbackTimer.current)
    }
  }, [assetId, client, fieldOffset, onDetailLoaded])


  const toggle = (section: string) => {
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(section)) next.delete(section); else next.add(section)
      return next
    })
  }

  const showTab = (tab: 'metadata' | 'lineage') => {
    setActiveTab(tab)
    if (tab === 'lineage' && !lineage && !lineageLoading) {
      const controller = new AbortController()
      lineageController.current?.abort()
      lineageController.current = controller
      setLineageLoading(true); setLineageError(undefined)
      void client.request<CatalogLineage>(`/catalog/assets/${assetId}/lineage?direction=BOTH&depth=2`, {
        signal: controller.signal,
      }).then((value) => { if (!controller.signal.aborted) setLineage(value) }).catch((next: unknown) => {
        if (!controller.signal.aborted) setLineageError(next)
      }).finally(() => {
        if (!controller.signal.aborted) setLineageLoading(false)
      })
    }
  }

  const copyUrn = async () => {
    if (!detail) return
    try {
      await navigator.clipboard.writeText(detail.external_urn)
    } catch {
      const input = document.createElement('textarea')
      input.value = detail.external_urn
      input.setAttribute('readonly', '')
      input.style.position = 'fixed'
      input.style.opacity = '0'
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
    const move = (next: PointerEvent) => onResizeWidth(startWidth + startX - next.clientX)
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
          className="catalog-detail-backdrop"
          aria-hidden="true"
          style={{ pointerEvents: 'none' }}
        />
      )}
      {/* URN 복사 Toast 알림 */}
      {toastVisible && (
        <div className="catalog-urn-toast" role="status" aria-live="polite">
          ✓ URN이 클립보드에 복사되었습니다
        </div>
      )}
      <aside
        className={`catalog-detail panel${asOverlay ? ' catalog-detail--overlay' : ''}`}
        aria-label="카탈로그 상세"
        style={{ width: width ? `${width}px` : undefined }}
      >
      {onResizeWidth && <button aria-label="상세 패널 너비 조절" className="catalog-detail-resizer" onKeyDown={(event) => {
        if (event.key === 'ArrowLeft') { event.preventDefault(); onResizeWidth((width ?? 550) + 24) }
        if (event.key === 'ArrowRight') { event.preventDefault(); onResizeWidth((width ?? 550) - 24) }
      }} onPointerDown={startResize} title="왼쪽으로 끌어 상세 폭 조절" type="button" />}
      <header>
        <div><span className="eyebrow">Authorized detail</span><h2>{detail?.name ?? '상세 정보'}</h2></div>
        <button type="button" aria-label="상세 닫기" onClick={onClose}><X size={16} /></button>
      </header>
      <div className="catalog-detail-scroll">
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
      <div className="catalog-detail-tabs" role="tablist" aria-label="상세 정보 보기">
        <button aria-controls="catalog-metadata-panel" aria-selected={activeTab === 'metadata'} className={activeTab === 'metadata' ? 'active' : ''} id="catalog-metadata-tab" onClick={() => showTab('metadata')} role="tab" type="button">Table Details</button>
        <button aria-controls="catalog-lineage-panel" aria-selected={activeTab === 'lineage'} className={activeTab === 'lineage' ? 'active' : ''} id="catalog-lineage-tab" onClick={() => showTab('lineage')} role="tab" type="button">Lineage</button>
      </div>
      <section aria-labelledby="catalog-metadata-tab" hidden={activeTab !== 'metadata'} id="catalog-metadata-panel" role="tabpanel">
        <AccordionItem itemId="details" title="Table details" summary={`${detail.schema_fields_total ?? detail.schema_fields.length} fields`} expanded={expanded.has('details')} onToggle={() => toggle('details')}>
          <dl className="catalog-detail-properties">
            <div><dt>Platform</dt><dd>{detailText(detail.platform)}</dd></div>
            <div><dt>Database</dt><dd>{detailText(detail.database_name)}</dd></div>
            <div><dt>Schema</dt><dd>{detailText(detail.schema_name)}</dd></div>
            <div><dt>Domain</dt><dd>{detailText(detail.domain)}</dd></div>
            <div><dt>Owner</dt><dd>{detailText(ownerValues(detail.ownership).join(', ') || detail.owner, detail.ownership_truncated)}</dd></div>
            <div><dt>Rows</dt><dd>{detailText(formatObservedValue(detail.quality.rowCount ?? detail.quality.rows))}</dd></div>
            <div><dt>Size</dt><dd>{detailText(formatObservedValue(detail.quality.sizeInBytes ?? detail.quality.size, ' B'))}</dd></div>
            <div><dt>Created Date</dt><dd>{detailText(detail.created_at ? new Date(detail.created_at).toLocaleString() : undefined)}</dd></div>
            <div className="wide"><dt>Description</dt><dd>{detailText(detail.description, detail.description_truncated)}</dd></div>
            <div className="metadata-vocabulary"><dt>Terms</dt><dd><BadgeScroller label="테이블 Terms" values={detail.terms ?? []} truncated={detail.terms_truncated} /></dd></div>
            <div className="metadata-vocabulary"><dt>Tags</dt><dd><BadgeScroller label="테이블 Tags" values={detail.tags} truncated={detail.tags_truncated} /></dd></div>
          </dl>
        </AccordionItem>
        <AccordionItem itemId="columns" title="Column metadata" summary={`${detail.schema_fields_total ?? detail.schema_fields.length} columns`} expanded={expanded.has('columns')} onToggle={() => toggle('columns')}>
          <div className="catalog-schema-table">
            {detail.schema_fields_truncated && <div className="catalog-detail-state" role="status">원본 {detail.schema_fields_total_exact ? '' : '최소 '}{detail.schema_fields_total.toLocaleString()}개 중 메모리 보호 상한인 {detail.schema_fields_available.toLocaleString()}개 컬럼만 제공합니다.</div>}
            <table><caption className="sr-only">스키마 필드</caption><thead><tr><th>Column</th><th>Type</th><th>Description</th><th>Terms</th><th>Tags</th></tr></thead>
              <tbody>{detail.schema_fields.map((field, index) => {
                const fieldName = valueOf(field, 'fieldPath', 'name')
                const type = valueOf(field, 'nativeDataType', 'type')
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
              <button className="button button-secondary" disabled={(detail.schema_fields_offset ?? 0) === 0} onClick={() => setFieldOffset(Math.max(0, (detail.schema_fields_offset ?? 0) - (detail.schema_fields_limit ?? 100)))} type="button">이전 컬럼</button>
              <span>{(detail.schema_fields_offset ?? 0) + 1}–{(detail.schema_fields_offset ?? 0) + detail.schema_fields.length} / {detail.schema_fields_available ?? detail.schema_fields_total}</span>
              <button className="button button-secondary" disabled={!detail.schema_fields_has_more} onClick={() => setFieldOffset((detail.schema_fields_offset ?? 0) + (detail.schema_fields_limit ?? 100))} type="button">다음 컬럼</button>
            </nav>}
          </div>
        </AccordionItem>
      </section>
      <section aria-labelledby="catalog-lineage-tab" hidden={activeTab !== 'lineage'} id="catalog-lineage-panel" role="tabpanel">
        {lineageLoading && <div className="catalog-detail-state">권한 필터링된 lineage를 불러오는 중입니다.</div>}
        <ErrorNotice error={lineageError} />
        {lineage && <div className="catalog-lineage">
          <div className="catalog-lineage-summary"><Network size={15} /><span>{lineage.nodes.length} nodes · {lineage.edges.length} edges</span>{lineage.truncated && <b>일부 경로 생략</b>}</div>
          <CatalogLineageGraph
            lineage={lineage}
            onSelectAsset={onSelectAsset ?? (() => undefined)}
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
