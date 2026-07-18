import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  Activity,
  ArrowRight,
  BookOpen,
  ChevronDown,
  ClipboardList,
  Clock3,
  Database,
  HardDrive,
  Layers,
  Network,
  Search,
  ShieldCheck,
  Terminal,
} from 'lucide-react'
import type { ApiClient } from '../../api/client'
import type { Capability, CatalogSchemaMetric, OperationsSummary } from '../../api/types'
import { pageUrl, type Page } from '../../app/navigation'
import { ErrorNotice } from '../../components/ErrorNotice'
import { PageTitle } from '../../components/layout/PageTitle'

const dashboardPeriods = ['1W', '1M', '3M'] as const

export function DashboardPage({
  client,
  onNavigate,
}: {
  client: ApiClient
  onNavigate: (page: Page) => void
}) {
  const [capabilities, setCapabilities] = useState<Capability[]>([])
  const [summary, setSummary] = useState<OperationsSummary>()
  const [error, setError] = useState<unknown>()
  const [loading, setLoading] = useState(true)
  const [expandedPlatforms, setExpandedPlatforms] = useState<Record<string, boolean>>({})

  const refresh = useCallback(async () => {
    setError(undefined)
    setLoading(true)
    try {
      const [capabilityResult, summaryResult] = await Promise.all([
        client.request<{ items: Capability[] }>('/capabilities'),
        client.request<OperationsSummary>('/operations/summary'),
      ])
      setCapabilities(capabilityResult.items)
      setSummary(summaryResult)
    } catch (next) {
      setError(next)
    } finally {
      setLoading(false)
    }
  }, [client])

  useEffect(() => { void refresh() }, [refresh])

  const platformMetrics = useMemo(
    () => groupMetricsByPlatform(summary?.catalog_schema_metrics ?? []),
    [summary?.catalog_schema_metrics],
  )
  const descriptionCoverage = summary && summary.catalog_asset_count > 0
    ? Math.round((summary.catalog_described_asset_count / summary.catalog_asset_count) * 100)
    : undefined
  const changes = summary?.changes_by_state ?? {}
  const reviewingChanges = countStates(changes, ['IN_REVIEW', 'TESTING', 'FINAL_REVIEW', 'APPLY_QUEUED', 'APPLYING'])

  return (
    <section className="dashboard-page">
      <PageTitle
        icon="OP"
        eyebrow="Governance dashboard"
        title="Governance Dashboard"
        description="데이터 자산 현황과 운영 상태를 현재 Workspace의 서버 검증 결과로 표시합니다."
        actions={(
          <div className="dashboard-title-actions">
            <div className="dashboard-periods" aria-label="기간 집계 상태" title="현재 DataRiver read model은 시점별 집계를 제공하지 않습니다.">
              {dashboardPeriods.map((period) => <button key={period} type="button" disabled>{period}</button>)}
            </div>
            <button className="button button-secondary" type="button" onClick={() => void refresh()} disabled={loading}>
              새로고침
            </button>
          </div>
        )}
      />
      <p className="dashboard-contract-note">현재 시점 Snapshot · 기간별 이력은 수집 계약이 준비되기 전까지 비활성화됩니다.</p>
      <ErrorNotice error={error} />

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
          unit="Terms"
          icon={<BookOpen size={20} />}
          description="현재 projection 계약에서는 집계하지 않음"
          unavailable
          page="knowledge"
          onNavigate={onNavigate}
        />
        <DashboardStatCard
          title="Data Quality"
          unit="Score"
          icon={<ShieldCheck size={20} />}
          description="검증된 품질 점수 read model이 아직 없음"
          unavailable
          page="quality"
          onNavigate={onNavigate}
        />
        <DashboardStatCard
          title="CR Status"
          value={sumValues(changes)}
          unit="Requests"
          icon={<ClipboardList size={20} />}
          description={`신규 ${changes.REGISTERED ?? 0} · 검토/적용 ${reviewingChanges} · 완료 ${changes.APPLIED ?? 0}`}
          page="change-management"
          onNavigate={onNavigate}
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
            <QuickAction page="knowledge" onNavigate={onNavigate} icon={<Network size={18} />} label="Knowledge Graph" description="지식관리 및 온톨로지" />
            <QuickAction page="registration" onNavigate={onNavigate} icon={<HardDrive size={18} />} label="Dataset Registration" description="신규 데이터셋 일괄 등록" />
            <QuickAction page="change-management" onNavigate={onNavigate} icon={<Activity size={18} />} label="Change Management" description="CR 생명주기와 증거" />
            <QuickAction page="chat" onNavigate={onNavigate} icon={<Terminal size={18} />} label="AI Copilot" description="증거 기반 질의 지원" />
          </nav>
        </DashboardSection>

        <DashboardSection title="Metadata Audit Summary" icon={<Clock3 size={16} />}>
          <div className="dashboard-audit-unavailable" role="status">
            <Clock3 size={22} aria-hidden="true" />
            <div>
              <strong>감사 원장 요약은 별도 권한으로 보호됩니다.</strong>
              <p>현재 `operations.read` 계약은 감사 이벤트 행을 제공하지 않습니다. 감사 조회 권한과 전용 read model이 준비될 때까지 이 화면에서 로그를 임의로 표시하지 않습니다.</p>
            </div>
          </div>
          <div className="dashboard-operation-grid">
            <OperationFact label="업로드" values={summary?.uploads_by_state} />
            <OperationFact label="작업" values={summary?.jobs_by_state} />
            <OperationFact label="Outbox 대기" value={summary?.unpublished_outbox_events} />
            <OperationFact label="Dead letter" value={summary?.dead_lettered_outbox_events} error={(summary?.dead_lettered_outbox_events ?? 0) > 0} />
          </div>
          <div className="dashboard-capabilities" aria-label="의존성 상태">
            {capabilities.map((capability) => <CapabilityFact key={capability.name} capability={capability} />)}
            {!loading && capabilities.length === 0 && <span className="muted">표시할 capability 결과가 없습니다.</span>}
          </div>
        </DashboardSection>
      </div>
    </section>
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
  const descriptionCoverage = metric.asset_count > 0
    ? Math.round((metric.described_asset_count / metric.asset_count) * 100)
    : undefined
  const hierarchy = [metric.database_name, metric.schema_name].filter(Boolean).join(' / ') || '미분류 스키마'
  return (
    <article className="dashboard-schema-card">
      <header><strong title={hierarchy}>{hierarchy}</strong><span>{metric.asset_count.toLocaleString()} Assets</span></header>
      <div className="dashboard-schema-metrics">
        <MetricTile label="Desc" value={descriptionCoverage == null ? '—' : `${descriptionCoverage}%`} />
        <MetricTile label="Tag" value="미수집" unavailable />
        <MetricTile label="Term" value="미수집" unavailable />
      </div>
    </article>
  )
}

function MetricTile({ label, value, unavailable = false }: { label: string; value: string; unavailable?: boolean }) {
  return <div className={unavailable ? 'metric-tile unavailable' : 'metric-tile'}><small>{label}</small><strong>{value}</strong></div>
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

function OperationFact({ label, values, value, error = false }: { label: string; values?: Record<string, number>; value?: number; error?: boolean }) {
  const display = values ? sumValues(values) : value
  return <div className={error ? 'dashboard-operation-fact error' : 'dashboard-operation-fact'}><small>{label}</small><strong>{display == null ? '…' : display.toLocaleString()}</strong></div>
}

function CapabilityFact({ capability }: { capability: Capability }) {
  return <span className={`dashboard-capability state-${capability.state}`}><i /><b>{capability.name}</b><small>{capability.state}</small></span>
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

function sumValues(values: Record<string, number>): number {
  return Object.values(values).reduce((total, value) => total + value, 0)
}

function countStates(values: Record<string, number>, states: string[]): number {
  return states.reduce((total, state) => total + (values[state] ?? 0), 0)
}
