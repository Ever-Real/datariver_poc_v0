import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, type ApiClient } from '../../api/client'
import type { QualityCapabilityAxis } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { AccordionItem } from '../../components/common/Accordion'
import { CatalogResourceTree } from '../catalog/CatalogResourceTree'
import { QualityFieldDrawer } from './QualityFieldDrawer'
import { QualityFieldBulkApplyDialog } from './QualityFieldBulkApplyDialog'
import type { QualityAssetField, QualityAssetFieldWorkspace } from './qualityFieldTypes'
import { qualityBoundaryPrefix, qualityQueryKey, type QualityApi, type QualitySecurityBoundary } from './qualityApi'
import {
  basisPointsText,
  countText,
  dateTimeText,
  QualityStatus,
} from './QualityShared'
import { isAuthorizationBoundaryError } from './useBoundedQualityRunPolling'
import './qualityFields.css'

export function QualityAssetsTab({
  client,
  api,
  boundary,
  axes,
  selectedAssetId,
  onSelectedAsset,
  onBoundaryInvalid,
}: {
  client: ApiClient
  api: QualityApi
  boundary: QualitySecurityBoundary
  axes: ReadonlyMap<string, QualityCapabilityAxis>
  selectedAssetId?: string
  onSelectedAsset: (assetId?: string) => void
  onBoundaryInvalid: () => void
}) {
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
    const resourceNotFound = workspace.error instanceof ApiError
      && workspace.error.problem.status === 404
    if (!resourceNotFound && isAuthorizationBoundaryError(workspace.error)) {
      onBoundaryInvalid()
    }
  }, [onBoundaryInvalid, workspace.error])
  return <section className="quality-asset-workspace">
    <CatalogResourceTree
      client={client}
      selectedAssetId={selectedAssetId}
      onSelectAsset={onSelectedAsset}
      searchable
      searchIdPrefix="quality-asset"
      searchLabel="품질 자산 검색"
    />

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
      {!workspace.error && workspace.data && <AssetInspector
        value={workspace.data}
        api={api}
        boundary={boundary}
        axes={axes}
        onBoundaryInvalid={onBoundaryInvalid}
      />}
    </section>
  </section>
}

function AssetInspector({
  value,
  api,
  boundary,
  axes,
  onBoundaryInvalid,
}: {
  value: QualityAssetFieldWorkspace
  api: QualityApi
  boundary: QualitySecurityBoundary
  axes: ReadonlyMap<string, QualityCapabilityAxis>
  onBoundaryInvalid: () => void
}) {
  const [expanded, setExpanded] = useState(new Set(['rules', 'runs', 'trend']))
  const [selectedField, setSelectedField] = useState<QualityAssetField>()
  const toggle = (id: string) => setExpanded((current) => {
    const next = new Set(current)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })
  const latestRun = value.runs[0]

  useEffect(() => { setSelectedField(undefined) }, [value.asset.asset_id])

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
    <FieldExplorer
      value={value}
      api={api}
      boundary={boundary}
      axes={axes}
      onOpenField={setSelectedField}
      onBoundaryInvalid={onBoundaryInvalid}
    />
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
    <QualityFieldDrawer
      open={Boolean(selectedField)}
      api={api}
      boundary={boundary}
      assetId={value.asset.asset_id}
      field={selectedField}
      onClose={() => setSelectedField(undefined)}
      onBoundaryInvalid={onBoundaryInvalid}
    />
  </>
}

function FieldExplorer({
  value,
  api,
  boundary,
  axes,
  onOpenField,
  onBoundaryInvalid,
}: {
  value: QualityAssetFieldWorkspace
  api: QualityApi
  boundary: QualitySecurityBoundary
  axes: ReadonlyMap<string, QualityCapabilityAxis>
  onOpenField: (field: QualityAssetField) => void
  onBoundaryInvalid: () => void
}) {
  const queryClient = useQueryClient()
  const [query, setQuery] = useState('')
  const [logicalType, setLogicalType] = useState('ALL')
  const [selected, setSelected] = useState(new Set<string>())
  const [bulkOpen, setBulkOpen] = useState(false)
  const lastIndex = useRef<number | undefined>(undefined)
  const fields = useMemo(() => value.fields.filter((field) => (
    (!query || `${field.display_path} ${field.field_identifier}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()))
    && (logicalType === 'ALL' || field.logical_type === logicalType)
  )), [logicalType, query, value.fields])

  useEffect(() => {
    setQuery('')
    setLogicalType('ALL')
    setSelected(new Set())
    setBulkOpen(false)
    lastIndex.current = undefined
  }, [value.asset.asset_id])

  const toggle = (field: QualityAssetField, index: number, checked: boolean, shiftKey: boolean) => {
    setSelected((current) => {
      const next = new Set(current)
      if (shiftKey && lastIndex.current !== undefined) {
        const start = Math.min(lastIndex.current, index)
        const end = Math.max(lastIndex.current, index)
        fields.slice(start, end + 1).forEach((candidate) => {
          if (checked) {
            if (next.has(candidate.field_identifier) || next.size < 100) {
              next.add(candidate.field_identifier)
            }
          } else next.delete(candidate.field_identifier)
        })
      } else if (checked && next.size < 100) next.add(field.field_identifier)
      else next.delete(field.field_identifier)
      return next
    })
    lastIndex.current = index
  }

  return <section className="quality-field-explorer" aria-labelledby="quality-field-explorer-title">
    <header>
      <div><span className="eyebrow">Field explorer</span><h3 id="quality-field-explorer-title">필드별 품질 관리</h3></div>
      <span>{countText(value.fields.length)}개 필드</span>
    </header>
    {value.authoring.state !== 'READY' ? <div className="callout" role="status">
      현재 deployment field binding을 확인할 수 없습니다. {value.authoring.reason_code ?? 'AUTHORING_TARGET_UNAVAILABLE'}
    </div> : <>
      <div className="quality-field-toolbar">
        <label>필드 검색<input value={query} maxLength={255} onChange={(event) => setQuery(event.target.value)} placeholder="필드명 또는 field ID" /></label>
        <label>타입<select value={logicalType} onChange={(event) => setLogicalType(event.target.value)}>
          <option value="ALL">전체 타입</option>
          {[...new Set(value.fields.map((field) => field.logical_type))].sort().map((type) => <option key={type}>{type}</option>)}
        </select></label>
        <button type="button" className="button" disabled={selected.size === 0 || axes.get('rule_authoring')?.state !== 'AVAILABLE'} onClick={() => setBulkOpen(true)}>
          선택 필드에 룰 적용 ({countText(selected.size)})
        </button>
      </div>
      {axes.get('rule_authoring')?.state !== 'AVAILABLE' && <p className="quality-field-readiness" role="status">
        룰 적용 준비 필요 · {axes.get('rule_authoring')?.reason_code ?? 'QUALITY_RULE_PROPOSE_DENIED'}
      </p>}
      {selected.size === 100 && <p className="quality-field-readiness" role="status">
        한 테이블에서 한 번에 선택할 수 있는 최대 100개 필드에 도달했습니다.
      </p>}
      <div className="quality-field-grid-scroll">
        <table className="quality-field-grid">
          <thead><tr><th>선택</th><th>필드</th><th>타입</th><th>설정/활성 룰</th><th>최근 점수</th><th>상태</th><th>최근 평가</th></tr></thead>
          <tbody>{fields.map((field, index) => <tr key={field.field_identifier} tabIndex={0} onClick={() => onOpenField(field)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onOpenField(field) } }}>
            <td onClick={(event) => event.stopPropagation()}><input
              type="checkbox"
              aria-label={`${field.display_path} 선택`}
              checked={selected.has(field.field_identifier)}
              onClick={(event) => event.stopPropagation()}
              onChange={(event) => toggle(field, index, event.target.checked, event.nativeEvent instanceof MouseEvent && event.nativeEvent.shiftKey)}
            /></td>
            <td><strong>{field.display_path}</strong><small>{field.field_identifier}</small></td>
            <td>{field.logical_type}</td>
            <td>{countText(field.configured_rule_count)} / {countText(field.active_rule_count)}</td>
            <td>{basisPointsText(field.latest_score_basis_points)}</td>
            <td><QualityStatus value={field.latest_quality_outcome} /></td>
            <td>{dateTimeText(field.latest_evaluated_at)}</td>
          </tr>)}</tbody>
        </table>
        {fields.length === 0 && <p className="quality-empty">검색 조건에 맞는 필드가 없습니다.</p>}
      </div>
      <QualityFieldBulkApplyDialog
        open={bulkOpen}
        api={api}
        boundary={boundary}
        axes={axes}
        selections={value.fields.filter((field) => selected.has(field.field_identifier)).map((field) => ({
          asset_id: value.asset.asset_id,
          asset_name: value.asset.name,
          platform: value.asset.platform,
          database_name: value.asset.database_name,
          schema_name: value.asset.schema_name,
          field_identifier: field.field_identifier,
          display_path: field.display_path,
          logical_type: field.logical_type,
          supported_rule_kinds: field.supported_rule_kinds,
        }))}
        onClose={() => setBulkOpen(false)}
        onApplied={async () => {
          setBulkOpen(false)
          setSelected(new Set())
          await queryClient.invalidateQueries({ queryKey: qualityBoundaryPrefix(boundary) })
        }}
        onBoundaryInvalid={onBoundaryInvalid}
      />
    </>}
  </section>
}

function AssetTrend({ value }: { value: QualityAssetFieldWorkspace }) {
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
