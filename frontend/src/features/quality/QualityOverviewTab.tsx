import { useEffect, useId } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ErrorNotice } from '../../components/ErrorNotice'
import { GovernedUnavailable } from '../../components/common/GovernedUnavailable'
import type { QualityOverview } from '../../api/types'
import {
  qualityQueryKey,
} from './qualityApi'
import type { QualityApi, QualitySecurityBoundary } from './qualityApi'
import {
  basisPointsText,
  countText,
  dateTimeText,
  QualityStatus,
} from './QualityShared'
import { isAuthorizationBoundaryError } from './useBoundedQualityRunPolling'

export function QualityOverviewTab({
  api,
  boundary,
  onBoundaryInvalid,
}: {
  api: QualityApi
  boundary: QualitySecurityBoundary
  onBoundaryInvalid: () => void
}) {
  const query = useQuery({
    queryKey: qualityQueryKey(boundary, 'overview', 30),
    queryFn: ({ signal }) => api.overview(signal),
    staleTime: 0,
    gcTime: 30_000,
    retry: false,
  })

  useEffect(() => {
    if (isAuthorizationBoundaryError(query.error)) onBoundaryInvalid()
  }, [onBoundaryInvalid, query.error])

  if (query.isPending) return <p className="quality-loading" role="status">권한 범위의 품질 현황을 불러오는 중입니다.</p>
  if (query.error) return <ErrorNotice error={query.error} />
  if (!query.data) return null
  if (query.data.availability === 'UNAVAILABLE') {
    return <GovernedUnavailable
      title="품질 현황을 계산할 수 없습니다"
      description={query.data.failure_code
        ? `서버 read model이 ${query.data.failure_code} 사유로 UNAVAILABLE을 반환했습니다. 과거 이력은 각 탭에서 별도로 확인할 수 있습니다.`
        : '서버 read model이 UNAVAILABLE을 반환했습니다. 과거 Rule과 실행 이력은 각 탭에서 별도로 확인할 수 있습니다.'}
    />
  }

  return <section className="quality-tab-content" aria-busy={query.isFetching}>
    <OverviewHeader overview={query.data} refreshing={query.isFetching && !query.isPending} />
    {query.data.availability === 'PARTIAL' && <GovernedUnavailable
      compact
      title="일부 품질 현황만 사용할 수 있습니다"
      description="서버가 PARTIAL snapshot을 반환했습니다. 표시된 값은 현재 권한 범위에서 확인된 집계이며 누락값을 브라우저에서 추정하지 않습니다."
    />}
    {query.data.active_rule_set_count === 0 ? (
      <p className="quality-empty" role="status">현재 권한 범위에 활성 품질 Rule Set이 없습니다.</p>
    ) : (
      <>
        <div className="quality-kpi-grid" aria-label="권한 범위 기준 품질 핵심 지표">
          <Kpi label="Score · Pass rate" value={basisPointsText(query.data.score_basis_points)} detail={`${countText(query.data.evaluated_rule_count)}개 Rule 평가`} />
          <Kpi label="Coverage" value={basisPointsText(query.data.coverage_basis_points)} detail={`${countText(query.data.evaluated_rule_set_count)} / ${countText(query.data.active_rule_set_count)} Rule Set`} />
          <Kpi label="PASS" value={countText(query.data.passed_count)} detail="Rule Definition 기준" status="PASS" />
          <Kpi label="WARN" value={countText(query.data.advisory_failed_count)} detail="Advisory failure" status="WARN" />
          <Kpi label="FAIL" value={countText(query.data.blocking_failed_count)} detail="Blocking failure" status="FAIL" />
          <Kpi label="UNKNOWN" value={countText(query.data.unknown_rule_set_count)} detail="Rule Set 기준" status="UNKNOWN" />
        </div>
        <QualityCoverage overview={query.data} />
        <QualityTrend overview={query.data} />
        <QualityResultCountTrend overview={query.data} />
      </>
    )}
  </section>
}

function OverviewHeader({
  overview,
  refreshing,
}: {
  overview: QualityOverview
  refreshing: boolean
}) {
  return <header className="quality-section-header">
    <div>
      <span className="eyebrow">Permission scoped · server aggregate</span>
      <h2>현재 품질 Snapshot</h2>
      <p>기준 시각 {dateTimeText(overview.as_of)} · 권한 유효 기한 {dateTimeText(overview.authorization_valid_until)}</p>
    </div>
    <div className="quality-state-cluster">
      <QualityStatus value={overview.overall_state} />
      <QualityStatus value={overview.freshness} />
      {refreshing && <span role="status">백그라운드 갱신 중</span>}
    </div>
  </header>
}

function Kpi({
  label,
  value,
  detail,
  status,
}: {
  label: string
  value: string
  detail: string
  status?: string
}) {
  return <article className="quality-kpi">
    <span>{label}</span>
    <strong>{value}</strong>
    <small>{status ? <QualityStatus value={status} /> : detail}</small>
    {status && <small>{detail}</small>}
  </article>
}

function QualityTrend({ overview }: { overview: QualityOverview }) {
  const titleId = useId()
  const descriptionId = useId()
  const points = overview.trend
    .map((point, index) => {
      if (point.score_basis_points === null) return undefined
      const x = overview.trend.length <= 1
        ? 300
        : 20 + index * (560 / (overview.trend.length - 1))
      const y = 140 - point.score_basis_points * 0.012
      return { x, y, point }
    })
    .filter((point): point is NonNullable<typeof point> => Boolean(point))
  const polyline = points.map((point) => `${point.x},${point.y}`).join(' ')

  return <section className="quality-trend panel" aria-labelledby={titleId}>
    <header>
      <div><span className="eyebrow">Last 30 days · maximum 90 points</span><h3 id={titleId}>품질 Score 추이</h3></div>
      <span>Score와 pass rate는 동일한 서버 KPI입니다.</span>
    </header>
    {overview.trend.length === 0 ? (
      <p className="quality-empty" role="status">표시할 완료 실행 추이가 없습니다.</p>
    ) : (
      <>
        <div className="quality-chart-scroll" tabIndex={0} aria-label="품질 Score 추이 차트 스크롤 영역">
          <svg viewBox="0 0 600 160" role="img" aria-labelledby={`${titleId} ${descriptionId}`}>
            <desc id={descriptionId}>각 기간별 서버 계산 Score를 0에서 100 퍼센트 축에 표시합니다. 동일 수치는 아래 표에서도 제공됩니다.</desc>
            {[20, 80, 140].map((y, index) => <g key={y}>
              <line x1="20" x2="580" y1={y} y2={y} className="quality-chart-grid" />
              <text x="2" y={y + 4}>{100 - index * 50}</text>
            </g>)}
            {polyline && <polyline points={polyline} className="quality-chart-line" />}
            {points.map(({ x, y, point }) => <circle key={point.bucket_start} cx={x} cy={y} r="4">
              <title>{dateTimeText(point.bucket_start)} · {basisPointsText(point.score_basis_points)}</title>
            </circle>)}
          </svg>
        </div>
        <div className="quality-table-scroll" tabIndex={0} aria-label="품질 Score 추이 표 스크롤 영역">
          <table className="quality-trend-table">
            <caption>품질 Score 추이 차트와 동일한 서버 집계 수치</caption>
            <thead><tr><th scope="col">기간</th><th scope="col">Score</th><th scope="col">PASS</th><th scope="col">Advisory fail</th><th scope="col">Blocking fail</th><th scope="col">평가 Rule</th></tr></thead>
            <tbody>{overview.trend.map((point) => <tr key={point.bucket_start}>
              <th scope="row">{dateTimeText(point.bucket_start)}</th>
              <td>{basisPointsText(point.score_basis_points)}</td>
              <td>{countText(point.passed_count)}</td>
              <td>{countText(point.advisory_failed_count)}</td>
              <td>{countText(point.blocking_failed_count)}</td>
              <td>{countText(point.evaluated_rule_count)}</td>
            </tr>)}</tbody>
          </table>
        </div>
      </>
    )}
  </section>
}

function QualityCoverage({ overview }: { overview: QualityOverview }) {
  const titleId = useId()
  const coverage = overview.coverage_basis_points

  return <section className="quality-trend panel" aria-labelledby={titleId}>
    <header>
      <div>
        <span className="eyebrow">Current snapshot · Rule Set grain</span>
        <h3 id={titleId}>현재 Rule Set Coverage</h3>
      </div>
      <span>서버가 계산한 현재 권한 범위의 coverage입니다.</span>
    </header>
    {coverage === null ? (
      <p className="quality-empty" role="status">서버가 현재 coverage 비율을 제공하지 않았습니다.</p>
    ) : (
      <div className="quality-coverage-visual">
        <progress
          className="quality-coverage-progress"
          aria-label="현재 Rule Set coverage"
          max={10_000}
          value={coverage}
        />
        <strong>{basisPointsText(coverage)}</strong>
      </div>
    )}
    <div className="quality-table-scroll" tabIndex={0} aria-label="현재 Rule Set coverage 표 스크롤 영역">
      <table className="quality-trend-table">
        <caption>현재 Rule Set coverage 막대와 동일한 서버 집계 수치</caption>
        <thead>
          <tr>
            <th scope="col">Coverage</th>
            <th scope="col">활성 Rule Set</th>
            <th scope="col">평가 Rule Set</th>
            <th scope="col">UNKNOWN Rule Set</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <th scope="row">{basisPointsText(coverage)}</th>
            <td>{countText(overview.active_rule_set_count)}</td>
            <td>{countText(overview.evaluated_rule_set_count)}</td>
            <td>{countText(overview.unknown_rule_set_count)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
}

function QualityResultCountTrend({ overview }: { overview: QualityOverview }) {
  const titleId = useId()
  const descriptionId = useId()
  const maximum = Math.max(
    0,
    ...overview.trend.flatMap((point) => [
      point.passed_count,
      point.advisory_failed_count,
      point.blocking_failed_count,
    ]),
  )
  const chartLeft = 44
  const chartWidth = 536
  const chartBottom = 140
  const chartHeight = 110
  const groupWidth = overview.trend.length > 0 ? chartWidth / overview.trend.length : chartWidth
  const barWidth = Math.max(1, Math.min(12, groupWidth / 4))
  const barHeight = (value: number) => maximum === 0 ? 0 : value / maximum * chartHeight
  const series = [
    { key: 'passed_count', label: 'PASS', fill: '#2f855a', legendClass: 'legend-color-passed_count' },
    { key: 'advisory_failed_count', label: 'Advisory fail', fill: '#b7791f', legendClass: 'legend-color-advisory_failed_count' },
    { key: 'blocking_failed_count', label: 'Blocking fail', fill: '#c53030', legendClass: 'legend-color-blocking_failed_count' },
  ] as const

  return <section className="quality-trend panel" aria-labelledby={titleId}>
    <header>
      <div>
        <span className="eyebrow">Last 30 days · Rule result grain</span>
        <h3 id={titleId}>품질 Rule 결과 건수 추이</h3>
      </div>
      <span>PASS, Advisory fail, Blocking fail은 동일한 Rule 단위입니다.</span>
    </header>
    {overview.trend.length === 0 ? (
      <p className="quality-empty" role="status">표시할 완료 Rule 결과 추이가 없습니다.</p>
    ) : (
      <>
        <div className="quality-chart-scroll" tabIndex={0} aria-label="품질 Rule 결과 건수 추이 차트 스크롤 영역">
          <div className="quality-result-count-legend" aria-hidden="true">
            {series.map((item) => <span key={item.key}>
              <i className={item.legendClass} />{item.label}
            </span>)}
          </div>
          <svg viewBox="0 0 600 160" role="img" aria-labelledby={`${titleId} ${descriptionId}`}>
            <desc id={descriptionId}>각 기간의 서버 집계 PASS, Advisory fail, Blocking fail Rule 건수를 나란한 막대로 표시합니다. 동일 수치는 아래 표에서도 제공됩니다.</desc>
            <line x1={chartLeft} x2={chartLeft + chartWidth} y1={chartBottom} y2={chartBottom} className="quality-chart-grid" />
            <text x="2" y={chartBottom + 4}>0</text>
            <text x="2" y={chartBottom - chartHeight + 4}>{countText(maximum)}</text>
            {overview.trend.flatMap((point, pointIndex) => {
              const center = chartLeft + pointIndex * groupWidth + groupWidth / 2
              return series.map((item, seriesIndex) => {
                const value = point[item.key]
                const height = barHeight(value)
                const x = center + (seriesIndex - 1.5) * barWidth
                return <rect
                  key={`${point.bucket_start}:${item.key}`}
                  x={x}
                  y={chartBottom - height}
                  width={barWidth}
                  height={height}
                  fill={item.fill}
                >
                  <title>{dateTimeText(point.bucket_start)} · {item.label} {countText(value)}</title>
                </rect>
              })
            })}
          </svg>
        </div>
        <div className="quality-table-scroll" tabIndex={0} aria-label="품질 Rule 결과 건수 추이 표 스크롤 영역">
          <table className="quality-trend-table">
            <caption>품질 Rule 결과 건수 추이 차트와 동일한 서버 집계 수치</caption>
            <thead>
              <tr>
                <th scope="col">기간</th>
                <th scope="col">PASS</th>
                <th scope="col">Advisory fail</th>
                <th scope="col">Blocking fail</th>
                <th scope="col">평가 Rule</th>
              </tr>
            </thead>
            <tbody>{overview.trend.map((point) => <tr key={point.bucket_start}>
              <th scope="row">{dateTimeText(point.bucket_start)}</th>
              <td>{countText(point.passed_count)}</td>
              <td>{countText(point.advisory_failed_count)}</td>
              <td>{countText(point.blocking_failed_count)}</td>
              <td>{countText(point.evaluated_rule_count)}</td>
            </tr>)}</tbody>
          </table>
        </div>
      </>
    )}
  </section>
}
