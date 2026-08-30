import { useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Activity,
  ArrowRight,
  BarChart3,
  BookOpen,
  ClipboardList,
  Database,
  Gauge,
  Search,
  ShieldCheck,
} from 'lucide-react'
import { ApiError, type ApiClient } from '../../api/client'
import type { CatalogSchemaMetric, ChangeRequestStateGroup } from '../../api/types'
import { pageUrl, type Page } from '../../app/navigation'
import { ErrorNotice } from '../../components/ErrorNotice'
import { PageTitle } from '../../components/layout/PageTitle'
import { ChangeHistoryApi } from '../change-history/changeHistoryApi'
import type { ChangeHistorySummary } from '../change-history/types'
import { QualityApi, qualityQueryKey } from '../quality/qualityApi'
import type { QualityDashboard } from '../quality/qualityDashboardTypes'
import { useQualityAuthorizationLease } from '../quality/useQualityAuthorizationLease'
import { isAuthorizationBoundaryError } from '../quality/useBoundedQualityRunPolling'

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
        title="홈"
        description="현재 권한 범위의 데이터와 운영 현황을 확인합니다."
        actions={(
          <div className="dashboard-title-actions">
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
      <ErrorNotice error={error ?? qualityLease.error ?? qualityQuery.error} />

      <div className="dashboard-stat-grid" aria-busy={loading}>
        <DashboardStatCard
          title="Total Datasets"
          value={summary?.catalog_asset_count}
          unit="Assets"
          icon={<Database size={20} />}
          description={descriptionCoverage == null ? '설명 완성도: 수집 데이터 없음' : `설명 완성도 ${descriptionCoverage}%`}
          page="catalog"
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
          changeSummary={changeSummaryQuery.data}
          changeSummaryError={changeSummaryQuery.error}
          loading={loading && !summary}
          onNavigate={onNavigate}
        />
      </div>

      <div className="dashboard-analytics-grid">
        <DashboardSection title="전체 Dataset 1주 trend" icon={<Activity size={16} />}>
          <UnavailableAnalytics
            code="HISTORICAL_DATASET_COUNT_SOURCE_UNAVAILABLE"
            message="정확한 7일 Dataset 이력 source가 아직 없습니다. 현재 수치를 과거 값으로 복제하지 않습니다."
          />
        </DashboardSection>
        <DashboardSection title="Schema별 metadata 등록 현황" icon={<Database size={16} />}>
          <SchemaCoverageAnalytics
            loading={loading && !summary}
            platformMetrics={platformMetrics}
            truncated={summary?.catalog_schema_metrics_truncated ?? false}
          />
        </DashboardSection>
        <DashboardSection title="Data Quality Dashboard" icon={<BarChart3 size={16} />}>
          <QualityAnalytics loading={qualityLoading && !quality} quality={quality} managedIndicatorNames={managedIndicatorNames} />
        </DashboardSection>
        <DashboardSection title="최근 7일 변경 대비 CR 처리율" icon={<ClipboardList size={16} />}>
          <UnavailableAnalytics
            code="CHANGE_TO_CR_7_DAY_SOURCE_UNAVAILABLE"
            message="rolling 7일 event→CR exact relation 집계가 없어 처리율을 추정하지 않습니다."
          />
        </DashboardSection>
      </div>
    </section>
  )
}

function ChangeRequestProgress({
  value,
  changeSummary,
  changeSummaryError,
  loading,
  onNavigate,
}: {
  value?: DashboardSummary['change_request_progress']
  changeSummary?: ChangeHistorySummary
  changeSummaryError: unknown
  loading: boolean
  onNavigate: (page: Page) => void
}) {
  const countText = (count?: number | null) => count == null
    ? loading ? '…' : 'UNKNOWN'
    : count.toLocaleString()
  const changeCount = (count?: number) => changeSummaryError || count == null ? '—' : count.toLocaleString()
  const completeCount = value?.groups.COMPLETED
  const inProgressCount = value?.groups.IN_PROGRESS
  return (
    <a
      aria-busy={loading}
      className="dashboard-stat-card dashboard-change-summary-card"
      href={pageUrl('change-management', { changeRequestStateGroup: '' })}
      onClick={(event) => { event.preventDefault(); onNavigate('change-management') }}
    >
      <span className="dashboard-stat-icon"><ClipboardList size={20} /></span>
      <p>Change Request Progress</p>
      <div className="dashboard-stat-primary"><strong>{countText(value?.total)}</strong><small>Requests</small></div>
      <span className="dashboard-stat-detail">
        {value && !value.complete
          ? '전체성 확인 불가'
          : `진행 ${countText(inProgressCount)} · 완료 ${countText(completeCount)}`}
      </span>
      <dl className="dashboard-change-facts" aria-label="이번 주 변경 현황">
        <div><dt>전체 변경</dt><dd>{changeCount(changeSummary?.total_count)}</dd></div>
        <div><dt>스키마</dt><dd>{changeCount(changeSummary?.schema_change_count)}</dd></div>
        <div><dt>메타데이터</dt><dd>{changeCount(changeSummary?.metadata_change_count)}</dd></div>
      </dl>
      {Boolean(changeSummaryError) && <span className="sr-only">{changeSummaryUnavailableText(changeSummaryError)}</span>}
    </a>
  )
}

function DashboardStatCard({
  title,
  value,
  unit,
  icon,
  description,
  page,
  onNavigate,
  unavailable = false,
}: {
  title: string
  value?: number
  unit: string
  icon: ReactNode
  description: string
  page?: Page
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
  if (!page) return <article className="dashboard-stat-card">{content}</article>
  return <a className="dashboard-stat-card" href={pageUrl(page)} onClick={(event) => { event.preventDefault(); onNavigate(page) }}>{content}</a>
}

function SchemaCoverageAnalytics({
  loading,
  platformMetrics,
  truncated,
}: {
  loading: boolean
  platformMetrics: ReturnType<typeof groupMetricsByPlatform>
  truncated: boolean
}) {
  if (loading) return <DashboardLoading label="metadata 등록 현황을 조회하고 있습니다." />
  const metrics = platformMetrics
    .flatMap(({ metrics: items }) => items)
    .sort((left, right) => right.asset_count - left.asset_count || metricKey(left).localeCompare(metricKey(right)))
  if (platformMetrics.length === 0) {
    return <p className="dashboard-empty">현재 권한 범위에 표시할 Dataset이 없습니다.</p>
  }

  return (
    <div className="dashboard-schema-coverage" aria-label="자산 수 상위 Schema metadata 등록률">
      <p>자산 수 상위 {Math.min(metrics.length, 3).toLocaleString()}개 Schema</p>
      <div>
        {metrics.slice(0, 3).map((metric) => <SchemaCoverageRow key={metricKey(metric)} metric={metric} />)}
      </div>
      {(metrics.length > 3 || truncated) && <small>{truncated ? '서버가 제공한 bounded schema 집계의' : '현재 집계의'} 상위 항목입니다.</small>}
    </div>
  )
}

function DashboardSection({
  title,
  icon,
  children,
}: {
  title: string
  icon: ReactNode
  children: ReactNode
}) {
  return (
    <section className="dashboard-section">
      <header><span>{icon}</span><h2>{title}</h2></header>
      <div className="dashboard-section-body">{children}</div>
    </section>
  )
}

function SchemaCoverageRow({ metric }: { metric: CatalogSchemaMetric }) {
  const descriptionCoverage = coveragePresentation('설명 보유 자산', metric.described_asset_count, metric.asset_count)
  const tagCoverage = coveragePresentation('태그 1개 이상 보유 자산', metric.tagged_asset_count, metric.asset_count)
  const termCoverage = coveragePresentation('용어 1개 이상 연결 자산', metric.term_asset_count, metric.asset_count)
  const hierarchy = [metric.database_name, metric.schema_name].filter(Boolean).join(' / ') || '미분류 스키마'
  return (
    <article className="dashboard-schema-coverage-row">
      <span><strong title={hierarchy}>{hierarchy}</strong><small>{metric.asset_count.toLocaleString()} Dataset</small></span>
      <MetricTile label="설명" {...descriptionCoverage} />
      <MetricTile label="Term" {...termCoverage} />
      <MetricTile label="Tag" {...tagCoverage} />
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

function QualityAnalytics({
  loading,
  quality,
  managedIndicatorNames,
}: {
  loading: boolean
  quality?: QualityDashboard
  managedIndicatorNames?: string
}) {
  if (loading) return <DashboardLoading label="품질 현황을 조회하고 있습니다." />
  if (!quality) return <p className="dashboard-empty">현재 권한 범위의 품질 현황을 사용할 수 없습니다.</p>
  const riskCount = quality.schemas.reduce(
    (total, schema) => total + schema.indicators.reduce((sum, indicator) => sum + indicator.risk_count, 0),
    0,
  )
  return (
    <div className="dashboard-analytics-facts" aria-label="품질 대시보드 핵심 지표">
      <div><small>Coverage</small><strong>{basisPointsText(quality.table_coverage_basis_points)}</strong></div>
      <div><small>룰셋</small><strong>{quality.active_rule_set_count.toLocaleString()}</strong></div>
      <div><small>위험 신호</small><strong>{riskCount.toLocaleString()}</strong></div>
      <p>{quality.covered_table_count.toLocaleString()} / {quality.table_count.toLocaleString()} tables · {managedIndicatorNames || '관리 지표 없음'}</p>
    </div>
  )
}

function UnavailableAnalytics({ code, message }: { code: string; message: string }) {
  return (
    <div className="dashboard-analytics-unavailable" role="status">
      <ShieldCheck size={18} aria-hidden="true" />
      <p>{message}</p>
      <code>{code}</code>
    </div>
  )
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

function changeSummaryUnavailableText(error: unknown): string {
  if (error instanceof ApiError && [401, 403].includes(error.problem.status)) {
    return '현재 사용자에게 이번 주 데이터 변경을 열람할 권한이 없습니다. 다른 데이터 카드에는 영향을 주지 않습니다.'
  }
  return '권한 필터가 적용된 변경 이력을 현재 사용할 수 없습니다. 0건으로 해석하지 않습니다.'
}
