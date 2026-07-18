import { useEffect, useRef, useState } from 'react'
import { Check, Copy, Network, X } from 'lucide-react'
import type { ApiClient } from '../../api/client'
import type { CatalogAssetDetail, CatalogLineage } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { AccordionItem } from '../../components/common/Accordion'
import { TruncatedText } from '../../components/common/TruncatedText'
import { CatalogLineageGraph } from './CatalogLineageGraph'
import { DataHubLineageDialog } from './DataHubLineageDialog'

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
}: {
  client: ApiClient
  assetId: string
  onClose: () => void
  onDetailLoaded?: (detail?: CatalogAssetDetail) => void
  onSelectAsset?: (assetId: string) => void
}) {
  const [detail, setDetail] = useState<CatalogAssetDetail>()
  const [lineage, setLineage] = useState<CatalogLineage>()
  const [expanded, setExpanded] = useState(new Set(['details', 'columns']))
  const [loading, setLoading] = useState(true)
  const [lineageLoading, setLineageLoading] = useState(false)
  const [error, setError] = useState<unknown>()
  const [lineageError, setLineageError] = useState<unknown>()
  const [copied, setCopied] = useState(false)
  const [explorerAssetId, setExplorerAssetId] = useState<string>()
  const lineageController = useRef<AbortController | null>(null)
  const copyFeedbackTimer = useRef<number | undefined>(undefined)

  useEffect(() => {
    const controller = new AbortController()
    lineageController.current?.abort()
    onDetailLoaded?.(undefined)
    setLoading(true); setError(undefined); setDetail(undefined); setLineage(undefined); setExplorerAssetId(undefined)
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
    if (section === 'lineage' && !lineage && !lineageLoading) {
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

  return <>
    <aside className="catalog-detail panel" aria-label="카탈로그 상세">
    <header>
      <div><span className="eyebrow">Authorized detail</span><h2>{detail?.name ?? '상세 정보'}</h2></div>
      <button type="button" aria-label="상세 닫기" onClick={onClose}><X size={16} /></button>
    </header>
    {loading && <div className="catalog-detail-state">상세 정보를 불러오는 중입니다.</div>}
    <ErrorNotice error={error} />
    {detail && <div className="catalog-detail-body">
      <div className="catalog-detail-badges"><span className="badge">{detail.asset_type}</span><span className="badge badge-soft">{detail.classification}</span>{detail.stale_at && <span className="badge badge-warning">STALE</span>}</div>
      <div className="catalog-detail-urn-row">
        <TruncatedText value={detail.external_urn} className="catalog-detail-urn" />
        <button type="button" className="catalog-urn-copy" onClick={() => void copyUrn()} aria-label="URN 복사" title={copied ? 'Copied!' : 'URN 복사'}>{copied ? <Check size={13} /> : <Copy size={13} />}<span>{copied ? 'Copied!' : 'Copy'}</span></button>
      </div>
      <AccordionItem itemId="details" title="Table details" summary={`${detail.schema_fields.length} fields`} expanded={expanded.has('details')} onToggle={() => toggle('details')}>
        <dl className="catalog-detail-properties">
          <div><dt>Platform</dt><dd>{detail.platform ?? '—'}</dd></div>
          <div><dt>Database</dt><dd>{detail.database_name ?? '—'}</dd></div>
          <div><dt>Schema</dt><dd>{detail.schema_name ?? '—'}</dd></div>
          <div><dt>Created Date</dt><dd>{detail.created_at ? new Date(detail.created_at).toLocaleString() : 'DataHub 미관측'}</dd></div>
          <div><dt>Owner</dt><dd>{ownerValues(detail.ownership).join(', ') || detail.owner || '—'}</dd></div>
          <div><dt>Domain</dt><dd>{detail.domain ?? '—'}</dd></div>
          <div><dt>Source version</dt><dd><TruncatedText value={detail.source_version} /></dd></div>
          <div className="wide"><dt>Description</dt><dd>{detail.description ?? '설명이 등록되지 않았습니다.'}</dd></div>
          <div className="wide"><dt>Terms</dt><dd>{referenceValues({ terms: detail.glossary_terms }, 'terms', 'term').join(', ') || detail.terms?.join(', ') || '—'}</dd></div>
          <div className="wide"><dt>Tags</dt><dd>{detail.tags.length ? detail.tags.join(', ') : '—'}</dd></div>
          <div><dt>Size</dt><dd>{formatObservedValue(detail.quality.sizeInBytes ?? detail.quality.size, ' B')}</dd></div>
          <div><dt>Rows</dt><dd>{formatObservedValue(detail.quality.rowCount ?? detail.quality.rows)}</dd></div>
        </dl>
      </AccordionItem>
      <AccordionItem itemId="columns" title="Column metadata" summary={`${detail.schema_fields.length} columns`} expanded={expanded.has('columns')} onToggle={() => toggle('columns')}>
        <div className="catalog-schema-table">
          <table><caption className="sr-only">스키마 필드</caption><thead><tr><th>Column</th><th>Type</th><th>Description</th><th>Terms</th><th>Tags</th></tr></thead>
            <tbody>{detail.schema_fields.map((field, index) => <tr key={`${valueOf(field, 'fieldPath', 'name')}-${index}`}><td><TruncatedText value={valueOf(field, 'fieldPath', 'name')} /></td><td>{valueOf(field, 'nativeDataType', 'type')}</td><td><TruncatedText value={valueOf(field, 'description')} /></td><td><TruncatedText value={fieldValues(field, 'glossaryTerms').join(', ') || '—'} /></td><td><TruncatedText value={fieldValues(field, 'globalTags').join(', ') || '—'} /></td></tr>)}</tbody>
          </table>
          {detail.schema_fields.length === 0 && <div className="catalog-detail-state">스키마 필드가 등록되지 않았습니다.</div>}
        </div>
      </AccordionItem>
      <AccordionItem itemId="lineage" title="Lineage" summary="2-hop bounded" expanded={expanded.has('lineage')} onToggle={() => toggle('lineage')}>
        {lineageLoading && <div className="catalog-detail-state">권한 필터링된 lineage를 불러오는 중입니다.</div>}
        <ErrorNotice error={lineageError} />
        {lineage && <div className="catalog-lineage">
          <div className="catalog-lineage-summary"><Network size={15} /><span>{lineage.nodes.length} nodes · {lineage.edges.length} edges</span>{lineage.truncated && <b>일부 경로 생략</b>}</div>
          <CatalogLineageGraph
            lineage={lineage}
            onOpenDataHubLineage={setExplorerAssetId}
            onSelectAsset={onSelectAsset ?? (() => undefined)}
          />
          {lineage.edges.length === 0 && <div className="catalog-detail-state">표시 가능한 연결 관계가 없습니다.</div>}
        </div>}
      </AccordionItem>
    </div>}
    </aside>
    <DataHubLineageDialog client={client} assetId={explorerAssetId} onClose={() => setExplorerAssetId(undefined)} />
  </>
}
