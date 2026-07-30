import { useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import type {
  QualityAsset,
  QualityCapabilityAxis,
  QualityRuleDefinition,
  QualityRuleSetSummary,
  QualityRuleSetVersionSummary,
} from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { CursorPagination } from '../../components/common/CursorPagination'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import { Dialog } from '../../components/common/Dialog'
import {
  qualityQueryKey,
} from './qualityApi'
import type { QualityApi, QualitySecurityBoundary } from './qualityApi'
import {
  countText,
  dateTimeText,
  optionalText,
  QualityAxisLock,
  QualityStatus,
} from './QualityShared'
import { isAuthorizationBoundaryError } from './useBoundedQualityRunPolling'
import { useQualityCursorPage } from './useQualityCursorPage'

export function QualityRuleSetsTab({
  api,
  boundary,
  axes,
  selectedRuleSetId,
  onSelectedRuleSet,
  onBoundaryInvalid,
}: {
  api: QualityApi
  boundary: QualitySecurityBoundary
  axes: Map<string, QualityCapabilityAxis>
  selectedRuleSetId?: string
  onSelectedRuleSet: (id?: string) => void
  onBoundaryInvalid: () => void
}) {
  const rules = useQualityCursorPage({
    boundary,
    resource: 'rule-sets',
    load: (cursor, signal) => api.ruleSets(cursor, signal),
    onBoundaryInvalid,
  })
  const assets = useQualityCursorPage({
    boundary,
    resource: 'assets',
    load: (cursor, signal) => api.assets(cursor, signal),
    onBoundaryInvalid,
  })
  const definitions = useQuery({
    queryKey: qualityQueryKey(boundary, 'rule-definitions'),
    queryFn: ({ signal }) => api.ruleDefinitions(signal),
    staleTime: 0,
    gcTime: 30_000,
    retry: false,
  })
  const detail = useQuery({
    queryKey: qualityQueryKey(
      boundary,
      'rule-set-detail',
      selectedRuleSetId,
    ),
    queryFn: ({ signal }) => api.ruleSet(
      selectedRuleSetId ?? '',
      boundary.cacheScope,
      signal,
    ),
    enabled: Boolean(selectedRuleSetId),
    staleTime: 0,
    gcTime: 30_000,
    retry: false,
  })

  useEffect(() => {
    if (isAuthorizationBoundaryError(definitions.error)) onBoundaryInvalid()
  }, [definitions.error, onBoundaryInvalid])
  useEffect(() => {
    if (!isAuthorizationBoundaryError(detail.error)) return
    onSelectedRuleSet(undefined)
    onBoundaryInvalid()
  }, [detail.error, onBoundaryInvalid, onSelectedRuleSet])
  const selectedSummary = detail.data?.rule_set
    ?? rules.data?.items.find((item) => item.rule_set_id === selectedRuleSetId)

  const ruleColumns = useMemo<ColumnDef<QualityRuleSetSummary>[]>(() => [
    { accessorKey: 'name', header: 'Rule Set', size: 210, enableSorting: false },
    { accessorKey: 'asset_name', header: '대상 자산', size: 180, enableSorting: false },
    { accessorKey: 'state', header: '상태', size: 100, enableSorting: false, cell: ({ row }) => <QualityStatus value={row.original.state} /> },
    { accessorKey: 'active_version_number', header: '활성 버전', size: 90, enableSorting: false, cell: ({ row }) => row.original.active_version_number ? `v${row.original.active_version_number}` : '—' },
    { accessorKey: 'active_version_state', header: '버전 상태', size: 120, enableSorting: false, cell: ({ row }) => <QualityStatus value={row.original.active_version_state} /> },
    { accessorKey: 'rule_count', header: 'Rule 수', size: 80, enableSorting: false, cell: ({ row }) => countText(row.original.rule_count) },
    { accessorKey: 'updated_at', header: '최근 변경', size: 170, enableSorting: false, cell: ({ row }) => dateTimeText(row.original.updated_at) },
  ], [])
  const assetColumns = useMemo<ColumnDef<QualityAsset>[]>(() => [
    { accessorKey: 'name', header: '자산', size: 190, enableSorting: false },
    { accessorKey: 'platform', header: 'Platform', size: 100, enableSorting: false, cell: ({ row }) => optionalText(row.original.platform) },
    { accessorKey: 'database_name', header: 'Database', size: 120, enableSorting: false, cell: ({ row }) => optionalText(row.original.database_name) },
    { accessorKey: 'schema_name', header: 'Schema', size: 120, enableSorting: false, cell: ({ row }) => optionalText(row.original.schema_name) },
    { accessorKey: 'classification', header: '등급', size: 100, enableSorting: false },
    { accessorKey: 'profile_readiness', header: 'Profile', size: 120, enableSorting: false, cell: ({ row }) => <QualityStatus value={row.original.profile_readiness} /> },
    { accessorKey: 'active_rule_set_count', header: '활성 Rule Set', size: 110, enableSorting: false, cell: ({ row }) => countText(row.original.active_rule_set_count) },
  ], [])

  return <section className="quality-tab-content">
    <header className="quality-section-header">
      <div><span className="eyebrow">Immutable versions · maker-checker</span><h2>Rule Set 관리</h2><p>현재 권한 범위의 서버 Rule Set과 대상 readiness를 조회합니다.</p></div>
    </header>
    <div className="quality-capability-locks" aria-label="Rule 관리 capability">
      <QualityAxisLock axis={axes.get('rule_authoring')} title="Rule 작성 잠김" />
      <QualityAxisLock axis={axes.get('activation')} title="독립 활성화 잠김" />
      <QualityAxisLock axis={axes.get('scheduling')} title="예약 실행 잠김" />
    </div>
    {definitions.error && <ErrorNotice error={definitions.error} />}
    <section className="panel quality-list-panel" aria-labelledby="quality-rule-set-list-title">
      <header><div><span className="eyebrow">Server cursor page</span><h3 id="quality-rule-set-list-title">Rule Sets</h3></div></header>
      {rules.error && <ErrorNotice error={rules.error} />}
      <DenseDataTable
        caption="품질 Rule Set 목록"
        columns={ruleColumns}
        data={rules.data?.items ?? []}
        getRowId={(row) => row.rule_set_id}
        loading={rules.isPending}
        emptyMessage="현재 권한 범위에서 조회 가능한 Rule Set이 없습니다."
        selectedRowId={selectedRuleSetId}
        onRowActivate={(row) => {
          onSelectedRuleSet(row.rule_set_id)
        }}
      />
      <CursorPagination {...rules.pagination} label="품질 Rule Set 페이지 탐색" />
    </section>
    <section className="panel quality-list-panel" aria-labelledby="quality-asset-list-title">
      <header><div><span className="eyebrow">Profile readiness · permission scoped</span><h3 id="quality-asset-list-title">대상 자산</h3></div></header>
      {axes.get('profile_readiness')?.state !== 'AVAILABLE' && <QualityAxisLock axis={axes.get('profile_readiness')} title="Profile 상세 readiness 잠김" />}
      {assets.error && <ErrorNotice error={assets.error} />}
      <DenseDataTable
        caption="품질 대상 자산 목록"
        columns={assetColumns}
        data={assets.data?.items ?? []}
        getRowId={(row) => row.asset_id}
        loading={assets.isPending}
        emptyMessage="현재 권한 범위에서 조회 가능한 품질 대상 자산이 없습니다."
      />
      <CursorPagination {...assets.pagination} label="품질 대상 자산 페이지 탐색" />
    </section>
    <section className="panel quality-rule-contract" aria-labelledby="quality-rule-contract-title">
      <header><div><span className="eyebrow">Typed allowlist</span><h3 id="quality-rule-contract-title">지원 Rule 계약</h3></div></header>
      {definitions.isPending ? <p role="status">Rule 계약을 확인하는 중입니다.</p> : (
        definitions.data?.items.length
          ? <ul>{definitions.data.items.map((definition) => <li key={definition.kind}>
            <QualityStatus value={definition.available ? 'AVAILABLE' : 'UNAVAILABLE'} />
            <strong>{definition.kind}</strong>
            {!definition.available && <span>{definition.reason_code ?? '비활성'}</span>}
          </li>)}</ul>
          : <p className="quality-empty" role="status">서버가 제공한 typed Rule 계약이 없습니다.</p>
      )}
    </section>
    <Dialog
      open={Boolean(selectedRuleSetId)}
      title={selectedSummary ? `${selectedSummary.name} · Rule Set` : 'Rule Set'}
      description="선택 시 권한 범위 안의 immutable version과 typed Rule을 지연 조회합니다."
      onRequestClose={() => {
        onSelectedRuleSet(undefined)
      }}
    >
      {detail.isPending && <p className="quality-loading" role="status">Rule Set 상세를 확인하는 중입니다.</p>}
      {detail.error && <ErrorNotice error={detail.error} />}
      {detail.data && <>
        <dl className="quality-detail-list">
          <div><dt>대상 자산</dt><dd>{detail.data.rule_set.asset_name}</dd></div>
          <div><dt>Lifecycle</dt><dd><QualityStatus value={detail.data.rule_set.state} /></dd></div>
          <div><dt>활성 버전</dt><dd>{detail.data.rule_set.active_version_number ? `v${detail.data.rule_set.active_version_number}` : '—'}</dd></div>
          <div><dt>버전 상태</dt><dd><QualityStatus value={detail.data.rule_set.active_version_state} /></dd></div>
          <div><dt>Rule 수</dt><dd>{countText(detail.data.rule_set.rule_count)}</dd></div>
          <div><dt>최근 변경</dt><dd>{dateTimeText(detail.data.rule_set.updated_at)}</dd></div>
        </dl>
        <RuleSetVersions versions={detail.data.versions} />
        <RuleSetDefinitions definitions={detail.data.definitions} />
      </>}
    </Dialog>
  </section>
}

function RuleSetVersions({ versions }: { versions: QualityRuleSetVersionSummary[] }) {
  return <section className="quality-results" aria-labelledby="quality-rule-version-title">
    <h3 id="quality-rule-version-title">버전 이력</h3>
    {versions.length === 0
      ? <p className="quality-empty" role="status">저장된 Rule Set 버전이 없습니다.</p>
      : <ul className="quality-history-list">{versions.map((version) => <li key={version.version_id}>
        <strong>v{version.version_number}</strong>
        <QualityStatus value={version.state} />
        <span>{countText(version.rule_count)}개 Rule</span>
        <span>{version.schedule_mode}</span>
        <span>{dateTimeText(version.updated_at)}</span>
      </li>)}</ul>}
  </section>
}

function RuleSetDefinitions({ definitions }: { definitions: QualityRuleDefinition[] }) {
  return <section className="quality-results" aria-labelledby="quality-rule-definition-title">
    <h3 id="quality-rule-definition-title">Typed Rule Definitions</h3>
    {definitions.length === 0
      ? <p className="quality-empty" role="status">저장된 typed Rule이 없습니다.</p>
      : <ol className="quality-history-list">{definitions.map((definition) => <li key={definition.rule_definition_id}>
        <strong>{definition.field_identifier}</strong>
        <span>{definition.kind}</span>
        <QualityStatus value={definition.severity} />
      </li>)}</ol>}
  </section>
}
