import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
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
  Layers,
  Search,
  ShieldCheck,
  Terminal,
} from 'lucide-react'
import type { ApiClient } from '../../api/client'
import type { CatalogSchemaMetric, ChangeRequestStateGroup } from '../../api/types'
import { pageUrl, type Page } from '../../app/navigation'
import { ErrorNotice } from '../../components/ErrorNotice'
import { PageTitle } from '../../components/layout/PageTitle'
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
}: {
  client: ApiClient
  workspaceId: string
  subjectId: string
  securityEpoch: number
  authorizationRevision: number
  onNavigate: (page: Page) => void
}) {
  const [summary, setSummary] = useState<DashboardSummary>()
  const [error, setError] = useState<unknown>()
  const [loading, setLoading] = useState(true)
  const [expandedPlatforms, setExpandedPlatforms] = useState<Record<string, boolean>>({})
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
                qualityLease.refresh()
              }}
              disabled={loading || qualityLease.loading}
            >
              새로고침
            </button>
          </div>
        )}
      />
      <p className="dashboard-contract-note">현재 시점 Snapshot · 기간별 이력은 수집 계약이 준비되기 전까지 비활성화됩니다.</p>
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
          description="활성화된 서버 동기화 용어"
          page="governance"
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
      </div>

      <DashboardSection title="Asset Distribution & Health Metrics by Database" icon={<Layers size={16} />}>
        {loading && !summary ? <DashboardLoading label="DataHub projection을 조회하고 있습니다." /> : (
          <>
            {platformMetrics.length === 0 ? (
              <p className="dashboard-empty">현재 Workspace에 표시할 비삭제 DataHub projection이 없습니다.</p>
            ) : (
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
                        onClick={() => setExpandedPlatforms((current) => ({ ...current, [platform]: !expanded }))}
                      >
                        <span className="dashboard-platform-icon"><Database size={14} /></span>
                        <span className="dashboard-platform-title"><small>Platform</small><strong>{platform}</strong></span>
                        <span className="dashboard-platform-total"><b>{assetCount.toLocaleString()}</b><small>Assets</small></span>
                        <ChevronDown size={16} aria-hidden="true" />
                      </button>
                      {expanded && (
                        <div className="dashboard-schema-list">
                          {metrics.map((metric) => <SchemaMetricCard key={metricKey(metric)} metric={metric} />)}
                        </div>
                      )}
                    </article>
                  )
                })}
              </div>
            )}
            {summary?.catalog_schema_metrics_truncated && (
              <p className="notice">플랫폼/스키마 항목은 안전한 화면 한도(200개)까지만 표시됩니다. 전체 탐색은 검색 화면을 사용하세요.</p>
            )}
          </>
        )}
      </DashboardSection>

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
  onNavigate,
  unavailable = false,
}: {
  title: string
  value?: number
  unit: string
  icon: ReactNode
  description: string
  page: Page
  onNavigate: (page: Page) => void
  unavailable?: boolean
}) {
  return (
    <a
      className="dashboard-stat-card"
      href={pageUrl(page)}
      onClick={(event) => { event.preventDefault(); onNavigate(page) }}
    >
      <span className="dashboard-stat-icon">{icon}</span>
      <p>{title}</p>
      <div><strong>{unavailable ? '—' : value == null ? '…' : value.toLocaleString()}</strong><small>{unit}</small></div>
      <span className={unavailable ? 'dashboard-stat-unavailable' : 'dashboard-stat-detail'}>{description}</span>
    </a>
  )
}

function DashboardSection({ title, icon, children }: { title: string; icon: ReactNode; children: ReactNode }) {
  return (
    <section className="dashboard-section">
      <header><span>{icon}</span><h2>{title}</h2></header>
      <div className="dashboard-section-body">{children}</div>
    </section>
  )
}

function SchemaMetricCard({ metric }: { metric: CatalogSchemaMetric }) {
  const descriptionCoverage = coveragePresentation('설명 보유 자산', metric.described_asset_count, metric.asset_count)
  const tagCoverage = coveragePresentation('태그 1개 이상 보유 자산', metric.tagged_asset_count, metric.asset_count)
  const termCoverage = coveragePresentation('용어 1개 이상 연결 자산', metric.term_asset_count, metric.asset_count)
  const hierarchy = [metric.database_name, metric.schema_name].filter(Boolean).join(' / ') || '미분류 스키마'
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
