import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { ApiClient } from '../../api/client'
import type { QualityAsset, QualityAssetWorkspace } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { AccordionItem } from '../../components/common/Accordion'
import { CursorPagination } from '../../components/common/CursorPagination'
import { GlobalCatalogSearch } from '../../components/layout/GlobalCatalogSearch'
import { CatalogResourceTree } from '../catalog/CatalogResourceTree'
import { qualityQueryKey, type QualityApi, type QualitySecurityBoundary } from './qualityApi'
import {
  basisPointsText,
  countText,
  dateTimeText,
  QualityStatus,
} from './QualityShared'
import { isAuthorizationBoundaryError } from './useBoundedQualityRunPolling'
import { useQualityCursorPage } from './useQualityCursorPage'

export function QualityAssetsTab({
  client,
  api,
  boundary,
  selectedAssetId,
  onSelectedAsset,
  onBoundaryInvalid,
}: {
  client: ApiClient
  api: QualityApi
  boundary: QualitySecurityBoundary
  selectedAssetId?: string
  onSelectedAsset: (assetId?: string) => void
  onBoundaryInvalid: () => void
}) {
  const [query, setQuery] = useState('')
  const assets = useQualityCursorPage({
    boundary,
    resource: 'assets',
    scope: [query],
    load: (cursor, signal) => api.assets(cursor, signal, { query }),
    onBoundaryInvalid,
  })
  const workspace = useQuery({
    queryKey: qualityQueryKey(boundary, 'asset-workspace', selectedAssetId),
    queryFn: ({ signal }) => api.assetWorkspace(
      selectedAssetId ?? '',
      boundary.cacheScope,
      signal,
    ),
    enabled: Boolean(selectedAssetId),
    staleTime: 0,
    gcTime: 30_000,
    retry: false,
  })

  useEffect(() => {
    if (isAuthorizationBoundaryError(workspace.error)) onBoundaryInvalid()
  }, [onBoundaryInvalid, workspace.error])
  return <section className="quality-asset-workspace">
    <aside className="quality-asset-directory panel" aria-label="품질 대상 자산 목록">
      <header>
        <div>
          <span className="eyebrow">Schema · table directory</span>
          <h2>자산 선택</h2>
        </div>
        <span>{query ? `${countText(assets.data?.items.length)}개 검색` : '계층 선택'}</span>
      </header>
      <div className="quality-asset-global-search">
        <GlobalCatalogSearch
          client={client}
          idPrefix="quality-asset"
          searchLabel="품질 자산 검색"
          inputLabel="품질 자산 검색"
          placeholder="스키마·테이블·컬럼 검색..."
          maxLength={200}
          onSearch={(value) => {
            setQuery(value)
            onSelectedAsset(undefined)
          }}
        />
      </div>
      {query ? <>
        <header className="quality-asset-search-result-header">
          <strong>“{query}” 검색 결과</strong>
          <button className="button button-secondary" type="button" onClick={() => setQuery('')}>전체 계층 보기</button>
        </header>
        {assets.error && <ErrorNotice error={assets.error} />}
        {assets.isPending && <p className="quality-loading" role="status">자산을 불러오는 중입니다.</p>}
        {!assets.isPending && assets.data?.items.length === 0 && (
          <p className="quality-empty">검색 조건에 맞는 품질 자산이 없습니다.</p>
        )}
        <div className="quality-asset-list">
          {assets.data?.items.map((asset) => <AssetButton
            key={asset.asset_id}
            asset={asset}
            selected={asset.asset_id === selectedAssetId}
            onSelect={() => onSelectedAsset(asset.asset_id)}
          />)}
        </div>
        <CursorPagination {...assets.pagination} label="품질 자산 페이지 탐색" />
      </> : <CatalogResourceTree
        client={client}
        selectedAssetId={selectedAssetId}
        onSelectAsset={onSelectedAsset}
      />}
    </aside>

    <section className="quality-asset-inspector panel" aria-live="polite">
      {!selectedAssetId && (
        <div className="quality-asset-placeholder">
          <strong>확인할 테이블을 선택하세요</strong>
          <span>적용 룰셋, 최근 검사 이력과 점수 추이를 한 화면에서 확인할 수 있습니다.</span>
        </div>
      )}
      {workspace.isPending && selectedAssetId && (
        <p className="quality-loading" role="status">선택한 자산의 품질 현황을 불러오는 중입니다.</p>
      )}
      {workspace.error && <ErrorNotice error={workspace.error} />}
      {workspace.data && <AssetInspector value={workspace.data} />}
    </section>
  </section>
}

function AssetButton({
  asset,
  selected,
  onSelect,
}: {
  asset: QualityAsset
  selected: boolean
  onSelect: () => void
}) {
  return <button
    type="button"
    className={`quality-asset-item${selected ? ' selected' : ''}`}
    aria-pressed={selected}
    onClick={onSelect}
  >
    <span className="quality-asset-item-main">
      <strong>{asset.name}</strong>
      <small>
        {[asset.platform, asset.database_name, asset.schema_name]
          .filter(Boolean)
          .join(' · ') || '위치 정보 없음'}
      </small>
    </span>
    <span className="quality-asset-item-score">
      <QualityStatus value={asset.latest_quality_outcome} />
      <b>{basisPointsText(asset.latest_score_basis_points)}</b>
    </span>
  </button>
}

function AssetInspector({ value }: { value: QualityAssetWorkspace }) {
  const [expanded, setExpanded] = useState(new Set(['rules', 'runs', 'trend']))
  const toggle = (id: string) => setExpanded((current) => {
    const next = new Set(current)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })
  const latestRun = value.runs[0]

  return <>
    <header className="quality-asset-hero">
      <div>
        <span className="eyebrow">Asset quality at a glance</span>
        <h2>{value.asset.name}</h2>
        <p>
          {[value.asset.platform, value.asset.database_name, value.asset.schema_name]
            .filter(Boolean)
            .join(' · ') || '위치 정보 없음'}
        </p>
      </div>
      <div className="quality-asset-hero-score">
        <span>최근 품질 점수</span>
        <strong>{basisPointsText(value.asset.latest_score_basis_points)}</strong>
        <QualityStatus value={value.asset.latest_quality_outcome} />
      </div>
    </header>
    <div className="quality-asset-summary-strip">
      <div><span>적용 룰셋</span><strong>{countText(value.rule_sets.length)}</strong></div>
      <div><span>최근 실행</span><strong>{latestRun ? dateTimeText(latestRun.completed_at ?? latestRun.created_at) : '없음'}</strong></div>
      <div><span>실행 상태</span><QualityStatus value={latestRun?.state} /></div>
      <div><span>Profile</span><QualityStatus value={value.asset.profile_readiness} /></div>
    </div>
    <div className="quality-asset-accordions">
      <AccordionItem
        itemId="rules"
        title="적용된 룰셋"
        summary={`${countText(value.rule_sets.length)}개`}
        expanded={expanded.has('rules')}
        onToggle={() => toggle('rules')}
      >
        {value.rule_sets.length === 0
          ? <p className="quality-empty">이 자산에 적용된 룰셋이 없습니다.</p>
          : <ul className="quality-simple-list">{value.rule_sets.map((ruleSet) => <li key={ruleSet.rule_set_id}>
            <div><strong>{ruleSet.name}</strong><small>최근 변경 {dateTimeText(ruleSet.updated_at)}</small></div>
            <span>{countText(ruleSet.rule_count)} rules</span>
            <QualityStatus value={ruleSet.active_version_state ?? ruleSet.state} />
          </li>)}</ul>}
      </AccordionItem>
      <AccordionItem
        itemId="runs"
        title="최근 품질 검사 이력"
        summary={`${countText(value.runs.length)}건`}
        expanded={expanded.has('runs')}
        onToggle={() => toggle('runs')}
      >
        {value.runs.length === 0
          ? <p className="quality-empty">실행된 품질 검사가 없습니다.</p>
          : <div className="quality-compact-table-scroll">
            <table className="quality-compact-table">
              <thead><tr><th>검사 시각</th><th>룰셋</th><th>실행</th><th>결과</th><th>점수</th></tr></thead>
              <tbody>{value.runs.map((run) => <tr key={run.run_id}>
                <td>{dateTimeText(run.completed_at ?? run.created_at)}</td>
                <td>{run.rule_set_name}</td>
                <td><QualityStatus value={run.state} /></td>
                <td><QualityStatus value={run.quality_outcome} /></td>
                <td>{basisPointsText(run.score_basis_points)}</td>
              </tr>)}</tbody>
            </table>
          </div>}
      </AccordionItem>
      <AccordionItem
        itemId="trend"
        title="품질 점수 추이"
        summary="최근 30일"
        expanded={expanded.has('trend')}
        onToggle={() => toggle('trend')}
      >
        <AssetTrend value={value} />
      </AccordionItem>
    </div>
  </>
}

function AssetTrend({ value }: { value: QualityAssetWorkspace }) {
  const points = useMemo(() => value.trend.flatMap((point, index) => {
    if (point.score_basis_points === null) return []
    const x = value.trend.length <= 1 ? 280 : 18 + index * (524 / (value.trend.length - 1))
    const y = 126 - point.score_basis_points * 0.0108
    return [{ x, y, point }]
  }), [value.trend])
  if (points.length === 0) {
    return <p className="quality-empty">표시할 품질 점수 추이가 없습니다.</p>
  }
  return <div className="quality-asset-trend">
    <svg viewBox="0 0 560 145" role="img" aria-label="최근 30일 품질 점수 추이">
      {[18, 72, 126].map((y) => <line key={y} x1="18" x2="542" y1={y} y2={y} />)}
      <polyline points={points.map(({ x, y }) => `${x},${y}`).join(' ')} />
      {points.map(({ x, y, point }) => <circle key={point.bucket_start} cx={x} cy={y} r="4">
        <title>{dateTimeText(point.bucket_start)} · {basisPointsText(point.score_basis_points)}</title>
      </circle>)}
    </svg>
    <div className="quality-trend-labels">
      <span>{dateTimeText(points[0]?.point.bucket_start)}</span>
      <strong>{basisPointsText(points.at(-1)?.point.score_basis_points)}</strong>
      <span>{dateTimeText(points.at(-1)?.point.bucket_start)}</span>
    </div>
    <small>통과율 기반 점수 · 최근 성공 실행 기준</small>
  </div>
}
