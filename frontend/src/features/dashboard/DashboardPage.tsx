import { useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Activity,
  ArrowRight,
  BarChart3,
  BookOpen,
  ChevronDown,
  ClipboardList,
  Database,
  Gauge,
  Search,
  ShieldCheck,
  Terminal,
} from 'lucide-react'
import { ApiError, type ApiClient } from '../../api/client'
import type { CatalogSchemaMetric, ChangeRequestStateGroup } from '../../api/types'
import { pageUrl, type Page } from '../../app/navigation'
import { ErrorNotice } from '../../components/ErrorNotice'
import { Dialog } from '../../components/common/Dialog'
import { PageTitle } from '../../components/layout/PageTitle'
import { ChangeHistoryApi } from '../change-history/changeHistoryApi'
import type { ChangeHistorySummary, ChangeHistorySyncStatus } from '../change-history/types'
import { QualityApi, qualityQueryKey } from '../quality/qualityApi'
import { useQualityAuthorizationLease } from '../quality/useQualityAuthorizationLease'
import { isAuthorizationBoundaryError } from '../quality/useBoundedQualityRunPolling'

const dashboardPeriods = ['1W', '1M', '3M'] as const

interface DashboardSummary {
  observed_at: string
  changes_by_state: Record<string, number> | null
  change_request_progress?: {
    total: number | null
    groups: Record<ChangeRequestStateGroup, number | null>
    complete: boolean
  }
  catalog_asset_count: number
  catalog_described_asset_count: number
  catalog_glossary_term_count: number
  catalog_schema_metrics: CatalogSchemaMetric[]
  catalog_schema_metrics_truncated: boolean
}

export function DashboardPage({
  client,
  workspaceId,
  subjectId,
  securityEpoch,
  authorizationRevision,
  onNavigate,
  onStartChat,
}: {
  client: ApiClient
  workspaceId: string
  subjectId: string
  securityEpoch: number
  authorizationRevision: number
  onNavigate: (page: Page) => void
  onStartChat?: (question: string) => void
}) {
  const [summary, setSummary] = useState<DashboardSummary>()
  const [error, setError] = useState<unknown>()
  const [loading, setLoading] = useState(true)
  const [expandedPlatforms, setExpandedPlatforms] = useState<Record<string, boolean>>({})
  const [assetDistributionOpen, setAssetDistributionOpen] = useState(false)
  const [homeQuestion, setHomeQuestion] = useState('')
  const changeHistoryApi = useMemo(() => new ChangeHistoryApi(client), [client])
  const [currentWeekStart, setCurrentWeekStart] = useState(currentKstWeekStart)
  const changeSummaryQuery = useQuery({
    queryKey: [
      'change-history', 'home-current-week', workspaceId, subjectId,
      securityEpoch, authorizationRevision, currentWeekStart,
    ],
    queryFn: ({ signal }) => changeHistoryApi.summary(currentWeekStart, signal),
    staleTime: 0,
    gcTime: 30_000,
    retry: false,
  })
  const qualityApi = useMemo(() => new QualityApi(client), [client])
  const qualityLease = useQualityAuthorizationLease({
    api: qualityApi,
    workspaceId,
    subjectId,
    securityEpoch,
    authorizationRevision,
  })
  const qualityBoundary = qualityLease.boundary
  const qualityQuery = useQuery({
    queryKey: qualityBoundary
      ? qualityQueryKey(qualityBoundary, 'dashboard')
      : ['quality', 'home-dashboard', workspaceId, subjectId, securityEpoch, authorizationRevision],
    queryFn: ({ signal }) => {
      if (!qualityBoundary) throw new Error('품질 권한 lease가 준비되지 않았습니다.')
      return qualityApi.dashboard(qualityBoundary.cacheScope, signal)
    },
    enabled: Boolean(
      qualityBoundary
      && qualityLease.axis('read_access')?.state === 'AVAILABLE',
    ),
    staleTime: 0,
    gcTime: 30_000,
    retry: false,
  })
  const quality = qualityQuery.data
  const qualityLoading = qualityLease.loading || (qualityQuery.isPending && qualityQuery.fetchStatus !== 'idle')
  const invalidateQualityLease = qualityLease.invalidate

  const refresh = useCallback(async () => {
    setError(undefined)
    setLoading(true)
    try {
      const summaryResult = await client.request<DashboardSummary>('/operations/dashboard')
      setSummary(summaryResult)
    } catch (next) {
      setError(next)
    } finally {
      setLoading(false)
    }
  }, [client])

  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => {
    if (isAuthorizationBoundaryError(qualityQuery.error)) invalidateQualityLease()
  }, [invalidateQualityLease, qualityQuery.error])

  const platformMetrics = useMemo(
    () => groupMetricsByPlatform(summary?.catalog_schema_metrics ?? []),
    [summary?.catalog_schema_metrics],
  )
  const descriptionCoverage = summary && summary.catalog_asset_count > 0
    ? Math.round((summary.catalog_described_asset_count / summary.catalog_asset_count) * 100)
    : undefined
  const qualityCoverage = quality?.table_coverage_basis_points == null
    ? undefined
    : Math.round(quality.table_coverage_basis_points / 100)
  const managedIndicatorNames = quality?.managed_rule_sets.map((rule) => rule.name).join(' · ')
  const submitHomeQuestion = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const question = homeQuestion.trim()
    if (question.length < 2 || !onStartChat) return
    onStartChat(question)
  }

  return (
    <section className="dashboard-page">
      <PageTitle
        icon="OP"
        title="Governance Dashboard"
        description="데이터 자산 현황과 운영 상태를 현재 Workspace의 서버 검증 결과로 표시합니다."
        actions={(
          <div className="dashboard-title-actions">
            <div className="dashboard-periods" aria-label="기간 집계 상태" title="현재 DataRiver read model은 시점별 집계를 제공하지 않습니다.">
              {dashboardPeriods.map((period) => <button key={period} type="button" disabled>{period}</button>)}
            </div>
            <button
              className="button button-secondary"
              type="button"
              onClick={() => {
                void refresh()
                const nextWeekStart = currentKstWeekStart()
                if (nextWeekStart === currentWeekStart) void changeSummaryQuery.refetch()
                else setCurrentWeekStart(nextWeekStart)
                qualityLease.refresh()
              }}
              disabled={loading || changeSummaryQuery.isFetching || qualityLease.loading}
            >
              새로고침
            </button>
          </div>
        )}
      />
      <form className="dashboard-chat-search" role="search" onSubmit={submitHomeQuestion}>
        <label className="sr-only" htmlFor="dashboard-chat-question">Chat에 질문하기</label>
        <Search size={19} aria-hidden="true" />
        <input
          id="dashboard-chat-question"
          type="search"
          value={homeQuestion}
          onChange={(event) => setHomeQuestion(event.target.value)}
          placeholder="데이터에 대해 질문하세요"
          autoComplete="off"
          disabled={!onStartChat}
        />
        <button type="submit" disabled={!onStartChat || homeQuestion.trim().length < 2} aria-label="새 Chat에서 질문하기">
          <ArrowRight size={18} aria-hidden="true" />
        </button>
      </form>
      <p className="dashboard-contract-note">현재 시점 Snapshot · 기간별 이력은 수집 계약이 준비되기 전까지 비활성화됩니다.</p>
      <ErrorNotice error={error ?? qualityLease.error ?? qualityQuery.error} />

      <div className="dashboard-stat-grid" aria-busy={loading}>
        <DashboardStatCard
          title="Total Datasets"
          value={summary?.catalog_asset_count}
          unit="Assets"
          icon={<Database size={20} />}
          description={descriptionCoverage == null ? '설명 완성도: 수집 데이터 없음' : `설명 완성도 ${descriptionCoverage}%`}
          onActivate={() => setAssetDistributionOpen(true)}
          onNavigate={onNavigate}
        />
        <DashboardStatCard
          title="Business Glossary"
          value={summary?.catalog_glossary_term_count}
          unit="Terms"
          icon={<BookOpen size={20} />}
          description="현재 용어사전의 조회 가능한 용어"
          page="glossary"
          onNavigate={onNavigate}
        />
        <DashboardStatCard
          title="Data Quality"
          value={qualityCoverage}
          unit="%"
          icon={<Gauge size={20} />}
          description={quality
            ? `룰셋 적용 ${quality.covered_table_count.toLocaleString()} / ${quality.table_count.toLocaleString()} 테이블`
            : '품질 대시보드 집계 중'}
          page="quality"
          onNavigate={onNavigate}
        />
        <ChangeRequestProgress
          value={summary?.change_request_progress}
          loading={loading && !summary}
        />
        <DashboardSection title="이번 주 데이터 변경" icon={<Activity size={16} />} wide>
          <CurrentWeekChangeSummary
            summary={changeSummaryQuery.data}
            loading={changeSummaryQuery.isPending}
            error={changeSummaryQuery.error}
          />
        </DashboardSection>
      </div>

      <Dialog
        open={assetDistributionOpen}
        title="Asset Distribution & Health Metrics by Database"
        description="현재 권한 범위의 활성·비삭제 데이터셋을 플랫폼과 스키마별로 표시합니다."
        size="workspace"
        onRequestClose={() => setAssetDistributionOpen(false)}
        footer={<button className="button button-secondary" type="button" onClick={() => setAssetDistributionOpen(false)}>닫기</button>}
      >
        <AssetDistribution
          loading={loading && !summary}
          platformMetrics={platformMetrics}
          truncated={summary?.catalog_schema_metrics_truncated ?? false}
          expandedPlatforms={expandedPlatforms}
          onToggle={(platform) => setExpandedPlatforms((current) => ({ ...current, [platform]: !current[platform] }))}
        />
      </Dialog>

      <div className="dashboard-bottom-grid">
        <DashboardSection title="Governance Center" icon={<Activity size={16} />}>
          <nav className="dashboard-quick-actions" aria-label="Governance shortcuts">
            <QuickAction page="catalog" onNavigate={onNavigate} icon={<Search size={18} />} label="Catalog Search" description="메타데이터 전역 검색" />
            <QuickAction page="change-management" onNavigate={onNavigate} icon={<ClipboardList size={18} />} label="CR" description="변경요청 생명주기와 증거" />
            <QuickAction page="governance" onNavigate={onNavigate} icon={<ShieldCheck size={18} />} label="Governance" description="정책과 거버넌스 문서" />
            <QuickAction page="quality" onNavigate={onNavigate} icon={<BarChart3 size={18} />} label="Quality Management" description="품질 현황과 검증 결과" />
            <QuickAction page="chat" onNavigate={onNavigate} icon={<Terminal size={18} />} label="AI Copilot" description="증거 기반 질의 지원" />
          </nav>
        </DashboardSection>

        <DashboardSection title="Data Quality Dashboard" icon={<BarChart3 size={16} />}>
          {qualityLoading && !quality ? <DashboardLoading label="품질 대시보드를 조회하고 있습니다." /> : quality && (
            <div className="quality-dashboard-kpis dashboard-quality-kpis" aria-label="홈 품질 대시보드 핵심 지표">
              <QualityFact icon={<Database size={18} />} label="전체 스키마" value={quality.schema_count.toLocaleString()} detail={`${quality.table_count.toLocaleString()} tables`} />
              <QualityFact icon={<ShieldCheck size={18} />} label="품질 룰셋" value={quality.active_rule_set_count.toLocaleString()} detail={`공통 템플릿 ${quality.common_rule_template_count.toLocaleString()}개`} />
              <QualityFact icon={<Gauge size={18} />} label="룰셋 적용 테이블" value={basisPointsText(quality.table_coverage_basis_points)} detail={`${quality.covered_table_count.toLocaleString()} / ${quality.table_count.toLocaleString()} tables`} />
              <QualityFact icon={<BarChart3 size={18} />} label="기본 품질 지표" value={quality.managed_rule_sets.length.toLocaleString()} detail={managedIndicatorNames || '서버 정의 없음'} />
            </div>
          )}
        </DashboardSection>
      </div>
    </section>
  )
}

function CurrentWeekChangeSummary({
  summary,
  loading,
  error,
}: {
  summary?: ChangeHistorySummary
  loading: boolean
  error: unknown
}) {
  if (loading && !summary) return <DashboardLoading label="이번 주 데이터 변경 요약을 조회하고 있습니다." />
  if (error || !summary) {
    return (
      <div className="dashboard-audit-unavailable" role="alert">
        <ShieldCheck size={18} aria-hidden="true" />
        <div>
          <strong>이번 주 데이터 변경을 표시할 수 없습니다.</strong>
          <p>{changeSummaryUnavailableText(error)}</p>
          <div className="dashboard-operation-grid" aria-label="사용할 수 없는 이번 주 변경 집계">
            <OperationFact label="전체 변경" value="—" />
            <OperationFact label="스키마 변경" value="—" />
            <OperationFact label="메타데이터 변경" value="—" />
          </div>
        </div>
      </div>
    )
  }

  const incompleteHistory = !historyGuaranteedFromWeekStart(summary)
    || summary.sync_status !== 'CONTIGUOUS_CAPTURE_RECORDED'
  return (
    <div aria-label="현재 사용자 권한 범위의 이번 주 데이터 변경">
      <p className="dashboard-contract-note">
        현재 사용자가 열람할 수 있으며 시스템에 정확히 연결된 테이블만 집계합니다.
        동일한 원본 변경에서 파생된 중복 항목은 한 건으로 계산합니다.
      </p>
      <p>
        집계 구간 <strong>{`[${summary.week_start} 00:00, ${summary.week_end_exclusive} 00:00) KST (${summary.timezone})`}</strong>
      </p>
      <div className="dashboard-operation-grid" aria-label="이번 주 중복 제거 데이터 변경 집계">
        <OperationFact label="전체 변경" value={summary.total_count.toLocaleString()} />
        <OperationFact label="스키마 변경" value={summary.schema_change_count.toLocaleString()} />
        <OperationFact label="메타데이터 변경" value={summary.metadata_change_count.toLocaleString()} />
      </div>
      <div className="dashboard-capabilities" aria-label="변경 이력 캡처 및 동기화 상태">
        <StatusFact label="캡처 상태" value={summary.capture_state} />
        <StatusFact label="동기화 상태" value={summary.sync_status} />
      </div>
      {summary.time_unknown_count > 0 && (
        <p className="notice" role="status">
          발생 시각 미확정 {summary.time_unknown_count.toLocaleString()}건은 이번 주 합계에서 제외되었습니다.
        </p>
      )}
      {incompleteHistory && (
        <p className="notice" role="status">
          이 주의 시작부터 연속된 완전한 이력은 보장되지 않습니다. 완전성 보장 시작: {formatKstTimestamp(summary.ledger_guarantee_from)}
        </p>
      )}
    </div>
  )
}

function OperationFact({ label, value }: { label: string; value: string }) {
  return <div className="dashboard-operation-fact"><small>{label}</small><strong>{value}</strong></div>
}

function StatusFact({ label, value }: { label: string; value: ChangeHistorySyncStatus }) {
  const healthy = value === 'CONTIGUOUS_CAPTURE_RECORDED'
  return (
    <span className={`dashboard-capability ${healthy ? 'state-healthy' : 'state-unavailable'}`}>
      <i aria-hidden="true" /><b>{label}</b><small>{syncStatusLabel(value)}</small>
    </span>
  )
}

const changeRequestGroups: ReadonlyArray<{
  group: ChangeRequestStateGroup
  label: string
  description: string
}> = [
  { group: 'REGISTERED', label: '접수 대기', description: 'REGISTERED' },
  { group: 'IN_PROGRESS', label: '검토·진행', description: '검토, 테스트, 적용 진행·보완' },
  { group: 'COMPLETED', label: '적용·완료', description: 'APPLIED, COMPLETED' },
  { group: 'CLOSED', label: '반려·종료', description: 'REJECTED, CANCELLED' },
]

function ChangeRequestProgress({
  value,
  loading,
}: {
  value?: DashboardSummary['change_request_progress']
  loading: boolean
}) {
  const countText = (count?: number | null) => count == null
    ? loading ? '…' : 'UNKNOWN'
    : count.toLocaleString()
  return (
    <article className="dashboard-change-progress" aria-busy={loading}>
      <header>
        <span className="dashboard-stat-icon"><ClipboardList size={20} /></span>
        <div>
          <p>Change Request Progress</p>
          <span>{value && !value.complete
            ? 'UNKNOWN · 안전한 집계 한도를 초과해 전체성을 확인할 수 없습니다.'
            : '현재 권한 범위의 서버 검증 Snapshot · 기간 추세는 read model 준비 전까지 제공하지 않습니다.'}</span>
        </div>
        <a href={pageUrl('change-management', { changeRequestStateGroup: '' })}>
          <strong>{countText(value?.total)}</strong><small>Total requests</small>
        </a>
      </header>
      <nav aria-label="Change Request 진행 그룹">
        {changeRequestGroups.map(({ group, label, description }) => (
          <a key={group} href={pageUrl('change-management', { changeRequestStateGroup: group })}>
            <span><strong>{label}</strong><small>{description}</small></span>
            <b>{countText(value?.groups[group])}</b>
            <ArrowRight size={15} aria-hidden="true" />
          </a>
        ))}
      </nav>
    </article>
  )
}

function DashboardStatCard({
  title,
  value,
  unit,
  icon,
  description,
  page,
  onActivate,
  onNavigate,
  unavailable = false,
}: {
  title: string
  value?: number
  unit: string
  icon: ReactNode
  description: string
  page?: Page
  onActivate?: () => void
  onNavigate: (page: Page) => void
  unavailable?: boolean
}) {
  const content = (
    <>
      <span className="dashboard-stat-icon">{icon}</span>
      <p>{title}</p>
      <div><strong>{unavailable ? '—' : value == null ? '…' : value.toLocaleString()}</strong><small>{unit}</small></div>
      <span className={unavailable ? 'dashboard-stat-unavailable' : 'dashboard-stat-detail'}>{description}</span>
    </>
  )
  if (onActivate) return <button className="dashboard-stat-card" type="button" onClick={onActivate}>{content}</button>
  if (!page) return <article className="dashboard-stat-card">{content}</article>
  return <a className="dashboard-stat-card" href={pageUrl(page)} onClick={(event) => { event.preventDefault(); onNavigate(page) }}>{content}</a>
}

function AssetDistribution({
  loading,
  platformMetrics,
  truncated,
  expandedPlatforms,
  onToggle,
}: {
  loading: boolean
  platformMetrics: ReturnType<typeof groupMetricsByPlatform>
  truncated: boolean
  expandedPlatforms: Record<string, boolean>
  onToggle: (platform: string) => void
}) {
  const [selectedMetric, setSelectedMetric] = useState<CatalogSchemaMetric | undefined>()

  if (loading) return <DashboardLoading label="DataHub projection을 조회하고 있습니다." />
  if (platformMetrics.length === 0) {
    return <p className="dashboard-empty">현재 Workspace에 표시할 비삭제 DataHub projection이 없습니다.</p>
  }

  if (selectedMetric) {
    return (
      <div className="dashboard-schema-subview">
        <header className="dashboard-schema-subview-header">
          <button className="button button-secondary" onClick={() => setSelectedMetric(undefined)} type="button">
            이전
          </button>
          <h3>스키마 상세 정보</h3>
        </header>
        <SchemaMetricCard metric={selectedMetric} />
      </div>
    )
  }

  return (
    <>
      <div className="dashboard-platforms">
        {platformMetrics.map(({ platform, metrics }) => {
          const expanded = expandedPlatforms[platform] ?? false
          const assetCount = metrics.reduce((total, metric) => total + metric.asset_count, 0)
          return (
            <article className={`dashboard-platform ${expanded ? 'expanded' : ''}`} key={platform}>
              <button
                className="dashboard-platform-header"
                type="button"
                aria-expanded={expanded}
                onClick={() => onToggle(platform)}
              >
                <span className="dashboard-platform-icon"><Database size={14} /></span>
                <span className="dashboard-platform-title"><small>Platform</small><strong>{platform}</strong></span>
                <span className="dashboard-platform-total"><b>{assetCount.toLocaleString()}</b><small>Assets</small></span>
                <ChevronDown size={16} aria-hidden="true" />
              </button>
              {expanded && <div className="dashboard-schema-list">{metrics.map((metric) => <SchemaMetricCard key={metricKey(metric)} metric={metric} onClick={() => setSelectedMetric(metric)} />)}</div>}
            </article>
          )
        })}
      </div>
      {truncated && <p className="notice">플랫폼/스키마 항목은 안전한 화면 한도(200개)까지만 표시됩니다. 전체 탐색은 검색 화면을 사용하세요.</p>}
    </>
  )
}

function DashboardSection({
  title,
  icon,
  children,
  wide = false,
}: {
  title: string
  icon: ReactNode
  children: ReactNode
  wide?: boolean
}) {
  return (
    <section className={`dashboard-section${wide ? ' dashboard-change-progress' : ''}`}>
      <header><span>{icon}</span><h2>{title}</h2></header>
      <div className="dashboard-section-body">{children}</div>
    </section>
  )
}

function SchemaMetricCard({ metric, onClick }: { metric: CatalogSchemaMetric; onClick?: () => void }) {
  const descriptionCoverage = coveragePresentation('설명 보유 자산', metric.described_asset_count, metric.asset_count)
  const tagCoverage = coveragePresentation('태그 1개 이상 보유 자산', metric.tagged_asset_count, metric.asset_count)
  const termCoverage = coveragePresentation('용어 1개 이상 연결 자산', metric.term_asset_count, metric.asset_count)
  const hierarchy = [metric.database_name, metric.schema_name].filter(Boolean).join(' / ') || '미분류 스키마'

  if (onClick) {
    return (
      <button className="dashboard-schema-card" onClick={onClick} type="button">
        <header><strong title={hierarchy}>{hierarchy}</strong><span>{metric.asset_count.toLocaleString()} Assets</span></header>
        <div className="dashboard-schema-metrics">
          <MetricTile label="Desc" {...descriptionCoverage} />
          <MetricTile label="Tag" {...tagCoverage} />
          <MetricTile label="Term" {...termCoverage} />
        </div>
      </button>
    )
  }

  return (
    <article className="dashboard-schema-card">
      <header><strong title={hierarchy}>{hierarchy}</strong><span>{metric.asset_count.toLocaleString()} Assets</span></header>
      <div className="dashboard-schema-metrics">
        <MetricTile label="Desc" {...descriptionCoverage} />
        <MetricTile label="Tag" {...tagCoverage} />
        <MetricTile label="Term" {...termCoverage} />
      </div>
    </article>
  )
}

function coveragePresentation(label: string, numerator: number, denominator: number) {
  const explanation = `${label}(분자) ${numerator.toLocaleString()}개 / 현재 Workspace 내 이 항목의 활성·비삭제 자산(분모) ${denominator.toLocaleString()}개`
  return {
    value: denominator > 0 ? `${Math.round((numerator / denominator) * 100)}%` : 'UNKNOWN',
    explanation: denominator > 0 ? explanation : `${explanation} · 분모가 0이므로 계산할 수 없습니다.`,
  }
}

function MetricTile({ label, value, explanation }: { label: string; value: string; explanation: string }) {
  return <div className="metric-tile" role="group" aria-label={explanation} title={explanation}><small>{label}</small><strong>{value}</strong></div>
}

function QuickAction({
  page,
  onNavigate,
  icon,
  label,
  description,
}: {
  page: Page
  onNavigate: (page: Page) => void
  icon: ReactNode
  label: string
  description: string
}) {
  return <a href={pageUrl(page)} onClick={(event) => { event.preventDefault(); onNavigate(page) }}><span>{icon}</span><span><strong>{label}</strong><small>{description}</small></span><ArrowRight size={15} aria-hidden="true" /></a>
}

function QualityFact({ icon, label, value, detail }: { icon: ReactNode; label: string; value: string; detail: string }) {
  return <article className="quality-dashboard-kpi">
    <span className="quality-dashboard-kpi-icon" aria-hidden="true">{icon}</span>
    <div><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>
  </article>
}

function DashboardLoading({ label }: { label: string }) {
  return <p className="dashboard-loading"><span className="loader" />{label}</p>
}

function groupMetricsByPlatform(metrics: CatalogSchemaMetric[]) {
  const grouped = new Map<string, CatalogSchemaMetric[]>()
  for (const metric of metrics) {
    const platform = metric.platform || '미분류 플랫폼'
    const current = grouped.get(platform) ?? []
    current.push(metric)
    grouped.set(platform, current)
  }
  return [...grouped.entries()].map(([platform, groupedMetrics]) => ({ platform, metrics: groupedMetrics }))
}

function metricKey(metric: CatalogSchemaMetric): string {
  return [metric.platform, metric.database_name, metric.schema_name].map((part) => part ?? '').join('\u0000')
}

function basisPointsText(value: number | null): string {
  if (value == null) return '근거 없음'
  return `${(value / 100).toLocaleString(undefined, { maximumFractionDigits: 2 })}%`
}

function currentKstWeekStart(now = new Date()): string {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Seoul',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(now)
  const year = Number(parts.find((part) => part.type === 'year')?.value)
  const month = Number(parts.find((part) => part.type === 'month')?.value)
  const day = Number(parts.find((part) => part.type === 'day')?.value)
  const calendarDate = new Date(Date.UTC(year, month - 1, day))
  calendarDate.setUTCDate(calendarDate.getUTCDate() - ((calendarDate.getUTCDay() + 6) % 7))
  return calendarDate.toISOString().slice(0, 10)
}

function historyGuaranteedFromWeekStart(summary: ChangeHistorySummary): boolean {
  if (summary.ledger_guarantee_from === null) return false
  return Date.parse(summary.ledger_guarantee_from)
    <= Date.parse(`${summary.week_start}T00:00:00+09:00`)
}

function formatKstTimestamp(value: string | null): string {
  if (value === null) return '기록 없음'
  return new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(value))
}

function syncStatusLabel(value: ChangeHistorySyncStatus): string {
  const labels: Record<ChangeHistorySyncStatus, string> = {
    SOURCE_NOT_CONFIGURED: '소스 미구성',
    SOURCE_AMBIGUOUS: '소스 모호',
    CHECKPOINT_NOT_AVAILABLE: '체크포인트 없음',
    CHECKPOINT_INVALID: '체크포인트 오류',
    CAPTURE_PENDING: '캡처 대기',
    CONTIGUOUS_CAPTURE_RECORDED: '연속 캡처 기록됨',
    DISCOVERY_FAILED: '소스 탐색 실패',
    CAPTURE_FAILED: '캡처 실패',
  }
  return labels[value]
}

function changeSummaryUnavailableText(error: unknown): string {
  if (error instanceof ApiError && [401, 403].includes(error.problem.status)) {
    return '현재 사용자에게 이번 주 데이터 변경을 열람할 권한이 없습니다. 다른 데이터 카드에는 영향을 주지 않습니다.'
  }
  return '권한 필터가 적용된 변경 이력을 현재 사용할 수 없습니다. 0건으로 해석하지 않습니다.'
}
