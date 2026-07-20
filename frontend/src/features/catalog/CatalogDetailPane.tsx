import { useEffect, useRef, useState } from 'react'
import { Check, Copy, Network, X } from 'lucide-react'
import type { ApiClient } from '../../api/client'
import type { CatalogAssetDetail, CatalogLineage } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { AccordionItem } from '../../components/common/Accordion'
import { BadgeScroller } from '../../components/common/ControlledVocabularyInput'
import { TruncatedText } from '../../components/common/TruncatedText'
import { CatalogLineageGraph } from './CatalogLineageGraph'

function valueOf(document: Record<string, unknown>, ...keys: string[]): string {
  for (const key of keys) {
    const value = document[key]
    if (typeof value === 'string' && value) return value
  }
  return '—'
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

function formatObservedValue(value: unknown, unit?: string): string {
  if (typeof value === 'number' && Number.isFinite(value)) return `${value.toLocaleString()}${unit ?? ''}`
  if (typeof value === 'string' && value.trim()) return `${value}${unit ?? ''}`
  return 'DataHub 미관측'
}

function fieldValues(field: Record<string, unknown>, key: 'globalTags' | 'glossaryTerms'): string[] {
  return key === 'globalTags'
    ? referenceValues(field[key], 'tags', 'tag')
    : referenceValues(field[key], 'terms', 'term')
}

export function CatalogDetailPane({
  client,
  assetId,
  onClose,
  onDetailLoaded,
  onSelectAsset,
  onResizeWidth,
  width,
}: {
  client: ApiClient
  assetId: string
  onClose: () => void
  onDetailLoaded?: (detail?: CatalogAssetDetail) => void
  onSelectAsset?: (assetId: string) => void
  onResizeWidth?: (width: number) => void
  width?: number
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
  const lineageController = useRef<AbortController | null>(null)
  const copyFeedbackTimer = useRef<number | undefined>(undefined)

  useEffect(() => {
    const controller = new AbortController()
    lineageController.current?.abort()
    onDetailLoaded?.(undefined)
    setLoading(true); setError(undefined); setDetail(undefined); setLineage(undefined)
    void client.request<CatalogAssetDetail>(`/catalog/assets/${assetId}`, { signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted) {
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
  }, [assetId, client, onDetailLoaded])

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
    if (copyFeedbackTimer.current) window.clearTimeout(copyFeedbackTimer.current)
    copyFeedbackTimer.current = window.setTimeout(() => setCopied(false), 2_000)
  }

  const startResize = (event: React.PointerEvent<HTMLButtonElement>) => {
    if (!onResizeWidth || window.innerWidth < 1320) return
    event.preventDefault()
    const startX = event.clientX
    const startWidth = width ?? 550
    const move = (next: PointerEvent) => onResizeWidth(startWidth + startX - next.clientX)
    const stop = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', stop)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', stop, { once: true })
  }

  return <>
    <aside className="catalog-detail panel" aria-label="카탈로그 상세">
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
        <TruncatedText value={detail.external_urn} className="catalog-detail-urn" />
        <button type="button" className="catalog-urn-copy" onClick={() => void copyUrn()} aria-label="URN 복사" title={copied ? 'Copied!' : 'URN 복사'}>{copied ? <Check size={13} /> : <Copy size={13} />}<span>{copied ? 'Copied!' : 'Copy'}</span></button>
      </div>
      <div className="catalog-detail-tabs" role="tablist" aria-label="상세 정보 보기">
        <button aria-controls="catalog-metadata-panel" aria-selected={activeTab === 'metadata'} className={activeTab === 'metadata' ? 'active' : ''} id="catalog-metadata-tab" onClick={() => showTab('metadata')} role="tab" type="button">Table Details</button>
        <button aria-controls="catalog-lineage-panel" aria-selected={activeTab === 'lineage'} className={activeTab === 'lineage' ? 'active' : ''} id="catalog-lineage-tab" onClick={() => showTab('lineage')} role="tab" type="button">Lineage</button>
      </div>
      <section aria-labelledby="catalog-metadata-tab" hidden={activeTab !== 'metadata'} id="catalog-metadata-panel" role="tabpanel">
        <AccordionItem itemId="details" title="Table details" summary={`${detail.schema_fields.length} fields`} expanded={expanded.has('details')} onToggle={() => toggle('details')}>
          <dl className="catalog-detail-properties">
            <div><dt>Platform</dt><dd>{detail.platform ?? '—'}</dd></div>
            <div><dt>Database</dt><dd>{detail.database_name ?? '—'}</dd></div>
            <div><dt>Schema</dt><dd>{detail.schema_name ?? '—'}</dd></div>
            <div><dt>Domain</dt><dd>{detail.domain ?? '—'}</dd></div>
            <div><dt>Owner</dt><dd>{ownerValues(detail.ownership).join(', ') || detail.owner || '—'}</dd></div>
            <div><dt>Rows</dt><dd>{formatObservedValue(detail.quality.rowCount ?? detail.quality.rows)}</dd></div>
            <div><dt>Size</dt><dd>{formatObservedValue(detail.quality.sizeInBytes ?? detail.quality.size, ' B')}</dd></div>
            <div><dt>Created Date</dt><dd>{detail.created_at ? new Date(detail.created_at).toLocaleString() : 'DataHub 미관측'}</dd></div>
            <div className="wide"><dt>Description</dt><dd>{detail.description ?? '설명이 등록되지 않았습니다.'}</dd></div>
            <div className="metadata-vocabulary"><dt>Terms</dt><dd><BadgeScroller label="테이블 Terms" values={referenceValues({ terms: detail.glossary_terms }, 'terms', 'term').length ? referenceValues({ terms: detail.glossary_terms }, 'terms', 'term') : detail.terms ?? []} /></dd></div>
            <div className="metadata-vocabulary"><dt>Tags</dt><dd><BadgeScroller label="테이블 Tags" values={detail.tags} /></dd></div>
          </dl>
        </AccordionItem>
        <AccordionItem itemId="columns" title="Column metadata" summary={`${detail.schema_fields.length} columns`} expanded={expanded.has('columns')} onToggle={() => toggle('columns')}>
          <div className="catalog-schema-table">
            <table><caption className="sr-only">스키마 필드</caption><thead><tr><th>Column</th><th>Type</th><th>Description</th><th>Terms</th><th>Tags</th></tr></thead>
              <tbody>{detail.schema_fields.map((field, index) => <tr key={`${valueOf(field, 'fieldPath', 'name')}-${index}`}><td><TruncatedText value={valueOf(field, 'fieldPath', 'name')} /></td><td>{valueOf(field, 'nativeDataType', 'type')}</td><td><TruncatedText value={valueOf(field, 'description')} /></td><td><BadgeScroller label={`${valueOf(field, 'fieldPath', 'name')} Terms`} values={fieldValues(field, 'glossaryTerms')} /></td><td><BadgeScroller label={`${valueOf(field, 'fieldPath', 'name')} Tags`} values={fieldValues(field, 'globalTags')} /></td></tr>)}</tbody>
            </table>
            {detail.schema_fields.length === 0 && <div className="catalog-detail-state">스키마 필드가 등록되지 않았습니다.</div>}
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
}
