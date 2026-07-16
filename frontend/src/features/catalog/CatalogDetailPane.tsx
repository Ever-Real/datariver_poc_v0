import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowDownToLine, ArrowUpFromLine, Network, X } from 'lucide-react'
import type { ApiClient } from '../../api/client'
import type { CatalogAssetDetail, CatalogLineage } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { AccordionItem } from '../../components/common/Accordion'
import { TruncatedText } from '../../components/common/TruncatedText'

function valueOf(document: Record<string, unknown>, ...keys: string[]): string {
  for (const key of keys) {
    const value = document[key]
    if (typeof value === 'string' && value) return value
  }
  return '—'
}

export function CatalogDetailPane({
  client,
  assetId,
  onClose,
}: {
  client: ApiClient
  assetId: string
  onClose: () => void
}) {
  const [detail, setDetail] = useState<CatalogAssetDetail>()
  const [lineage, setLineage] = useState<CatalogLineage>()
  const [expanded, setExpanded] = useState(new Set(['details']))
  const [loading, setLoading] = useState(true)
  const [lineageLoading, setLineageLoading] = useState(false)
  const [error, setError] = useState<unknown>()
  const [lineageError, setLineageError] = useState<unknown>()
  const lineageController = useRef<AbortController | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    lineageController.current?.abort()
    setLoading(true); setError(undefined); setDetail(undefined); setLineage(undefined)
    void client.request<CatalogAssetDetail>(`/catalog/assets/${assetId}`, { signal: controller.signal })
      .then((value) => { if (!controller.signal.aborted) setDetail(value) })
      .catch((next: unknown) => { if (!controller.signal.aborted) setError(next) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => {
      controller.abort()
      lineageController.current?.abort()
    }
  }, [assetId, client])

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

  const nodeById = useMemo(
    () => new Map(lineage?.nodes.map((node) => [node.id, node]) ?? []),
    [lineage],
  )

  return <aside className="catalog-detail panel" aria-label="카탈로그 상세">
    <header>
      <div><span className="eyebrow">Authorized detail</span><h2>{detail?.name ?? '상세 정보'}</h2></div>
      <button type="button" aria-label="상세 닫기" onClick={onClose}><X size={16} /></button>
    </header>
    {loading && <div className="catalog-detail-state">상세 정보를 불러오는 중입니다.</div>}
    <ErrorNotice error={error} />
    {detail && <div className="catalog-detail-body">
      <div className="catalog-detail-badges"><span className="badge">{detail.asset_type}</span><span className="badge badge-soft">{detail.classification}</span>{detail.stale_at && <span className="badge badge-warning">STALE</span>}</div>
      <TruncatedText value={detail.external_urn} className="catalog-detail-urn" />
      <AccordionItem itemId="details" title="Table details" summary={`${detail.schema_fields.length} fields`} expanded={expanded.has('details')} onToggle={() => toggle('details')}>
        <dl className="catalog-detail-properties">
          <div><dt>Platform</dt><dd>{detail.platform ?? '—'}</dd></div>
          <div><dt>Database</dt><dd>{detail.database_name ?? '—'}</dd></div>
          <div><dt>Schema</dt><dd>{detail.schema_name ?? '—'}</dd></div>
          <div><dt>Source version</dt><dd><TruncatedText value={detail.source_version} /></dd></div>
          <div className="wide"><dt>Description</dt><dd>{detail.description ?? '설명이 등록되지 않았습니다.'}</dd></div>
          <div className="wide"><dt>Tags</dt><dd>{detail.tags.length ? detail.tags.join(', ') : '—'}</dd></div>
        </dl>
        <div className="catalog-schema-table">
          <table><caption className="sr-only">스키마 필드</caption><thead><tr><th>Name</th><th>Type</th><th>Description</th></tr></thead>
            <tbody>{detail.schema_fields.map((field, index) => <tr key={`${valueOf(field, 'fieldPath', 'name')}-${index}`}><td><TruncatedText value={valueOf(field, 'fieldPath', 'name')} /></td><td>{valueOf(field, 'type', 'nativeDataType')}</td><td><TruncatedText value={valueOf(field, 'description')} /></td></tr>)}</tbody>
          </table>
          {detail.schema_fields.length === 0 && <div className="catalog-detail-state">스키마 필드가 등록되지 않았습니다.</div>}
        </div>
      </AccordionItem>
      <AccordionItem itemId="lineage" title="Lineage" summary="2-hop bounded" expanded={expanded.has('lineage')} onToggle={() => toggle('lineage')}>
        {lineageLoading && <div className="catalog-detail-state">권한 필터링된 lineage를 불러오는 중입니다.</div>}
        <ErrorNotice error={lineageError} />
        {lineage && <div className="catalog-lineage">
          <div className="catalog-lineage-summary"><Network size={15} /><span>{lineage.nodes.length} nodes · {lineage.edges.length} edges</span>{lineage.truncated && <b>일부 경로 생략</b>}</div>
          <ul>{lineage.edges.map((edge) => {
            const source = nodeById.get(edge.source_asset_id)
            const target = nodeById.get(edge.target_asset_id)
            return <li key={`${edge.source_asset_id}-${edge.target_asset_id}`}><ArrowUpFromLine size={12} /><TruncatedText value={source?.name ?? edge.source_asset_id} /><span aria-hidden="true">→</span><ArrowDownToLine size={12} /><TruncatedText value={target?.name ?? edge.target_asset_id} /></li>
          })}</ul>
          {lineage.edges.length === 0 && <div className="catalog-detail-state">표시 가능한 연결 관계가 없습니다.</div>}
        </div>}
      </AccordionItem>
    </div>}
  </aside>
}
