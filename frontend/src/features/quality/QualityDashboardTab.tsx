import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { BarChart3, Database, Gauge, ShieldCheck } from 'lucide-react'
import type {
  QualityDashboardIndicator,
  QualityDashboardRisk,
  QualityIndicatorId,
  QualityManagedRuleSet,
  QualitySchemaDashboard,
} from './qualityDashboardTypes'
import { ErrorNotice } from '../../components/ErrorNotice'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import { Dialog } from '../../components/common/Dialog'
import {
  basisPointsText,
  countText,
  dateTimeText,
  optionalText,
  QualityStatus,
} from './QualityShared'
import {
  qualityQueryKey,
  type QualityApi,
  type QualitySecurityBoundary,
} from './qualityApi'
import { isAuthorizationBoundaryError } from './useBoundedQualityRunPolling'

const indicatorLabels: Record<QualityIndicatorId, string> = {
  ACCURACY: '정확성',
  COMPLETENESS: '완전성',
  TIMELINESS: '적시성',
}
const indicatorIds: QualityIndicatorId[] = ['ACCURACY', 'COMPLETENESS', 'TIMELINESS']

interface AnalysisSelection {
  schemaId: string
  indicatorId: QualityIndicatorId
}

export function QualityDashboardTab({
  api,
  boundary,
  onOpenTemplates,
  onBoundaryInvalid,
}: {
  api: QualityApi
  boundary: QualitySecurityBoundary
  onOpenTemplates: () => void
  onBoundaryInvalid: () => void
}) {
  const [analysis, setAnalysis] = useState<AnalysisSelection>()
  const query = useQuery({
    queryKey: qualityQueryKey(boundary, 'dashboard'),
    queryFn: ({ signal }) => api.dashboard(boundary.cacheScope, signal),
    staleTime: 0,
    gcTime: 30_000,
    retry: false,
  })

  useEffect(() => {
    if (isAuthorizationBoundaryError(query.error)) onBoundaryInvalid()
  }, [onBoundaryInvalid, query.error])
  const managedRules = useMemo(
    () => new Map(
      query.data?.managed_rule_sets.map((item) => [item.indicator_id, item]) ?? [],
    ),
    [query.data?.managed_rule_sets],
  )

  const columns = useMemo<ColumnDef<QualitySchemaDashboard>[]>(() => [
    {
      id: 'schema',
      header: 'Schema',
      size: 250,
      accessorFn: (row) => schemaPath(row),
      cell: ({ row }) => <div className="quality-dashboard-schema-cell">
        <strong>{optionalText(row.original.schema_name)}</strong>
        <small>{[row.original.platform, row.original.database_name].filter(Boolean).join(' · ') || '위치 정보 없음'}</small>
      </div>,
    },
    {
      accessorKey: 'table_count',
      header: 'Tables',
      size: 90,
      cell: ({ row }) => countText(row.original.table_count),
    },
    {
      id: 'accuracy',
      header: '정확성',
      size: 150,
      enableSorting: false,
      cell: ({ row }) => <IndicatorButton
        indicator={indicator(row.original, 'ACCURACY')}
        calculation={managedRules.get('ACCURACY')?.calculation}
        onClick={() => setAnalysis({
          schemaId: row.original.schema_id,
          indicatorId: 'ACCURACY',
        })}
      />,
    },
    {
      id: 'completeness',
      header: '완전성',
      size: 150,
      enableSorting: false,
      cell: ({ row }) => <IndicatorButton
        indicator={indicator(row.original, 'COMPLETENESS')}
        calculation={managedRules.get('COMPLETENESS')?.calculation}
        onClick={() => setAnalysis({
          schemaId: row.original.schema_id,
          indicatorId: 'COMPLETENESS',
        })}
      />,
    },
    {
      id: 'timeliness',
      header: '적시성',
      size: 150,
      enableSorting: false,
      cell: ({ row }) => <IndicatorButton
        indicator={indicator(row.original, 'TIMELINESS')}
        calculation={managedRules.get('TIMELINESS')?.calculation}
        onClick={() => setAnalysis({
          schemaId: row.original.schema_id,
          indicatorId: 'TIMELINESS',
        })}
      />,
    },
    {
      id: 'coverage',
      header: 'Rule 적용',
      size: 120,
      accessorFn: (row) => row.table_count
        ? row.covered_table_count / row.table_count
        : 0,
      cell: ({ row }) => basisPointsText(
        ratioBasisPoints(row.original.covered_table_count, row.original.table_count),
      ),
    },
  ], [managedRules])

  if (query.isPending) {
    return <p className="quality-loading" role="status">품질 대시보드를 불러오는 중입니다.</p>
  }
  if (query.error) return <ErrorNotice error={query.error} />
  if (!query.data) return null
  const selectedSchema = analysis
    ? query.data.schemas.find((schema) => schema.schema_id === analysis.schemaId)
    : undefined

  return <section className="quality-dashboard" aria-busy={query.isFetching}>
    <header className="quality-section-header">
      <div>
        <span className="eyebrow">Permission scoped · server facts</span>
        <h2>품질 대시보드</h2>
        <p>스키마별 테이블 수와 정확성·완전성·적시성을 같은 기준 시각으로 비교합니다.</p>
      </div>
      <span className="quality-dashboard-asof">기준 {dateTimeText(query.data.as_of)}</span>
    </header>
    <section className="quality-dashboard-kpis" aria-label="품질 대시보드 핵심 지표">
      <DashboardKpi icon={<Database size={18} />} label="전체 스키마" value={countText(query.data.schema_count)} detail={`${countText(query.data.table_count)} tables`} />
      <DashboardKpi icon={<ShieldCheck size={18} />} label="품질 룰셋" value={countText(query.data.active_rule_set_count)} detail={`공통 템플릿 ${countText(query.data.common_rule_template_count)}개`} />
      <DashboardKpi icon={<Gauge size={18} />} label="룰셋 적용 테이블" value={basisPointsText(query.data.table_coverage_basis_points)} detail={`${countText(query.data.covered_table_count)} / ${countText(query.data.table_count)} tables`} tooltip="활성 룰셋이 하나 이상 적용된 테이블은 적용 완료(100%)로 세고, 적용 테이블 수를 전체 테이블 수로 나눕니다." />
      <DashboardKpi icon={<BarChart3 size={18} />} label="기본 품질 지표" value={countText(query.data.managed_rule_sets.length)} detail="정확성 · 완전성 · 적시성" />
    </section>
    <section className="quality-managed-rules" aria-labelledby="quality-managed-rules-title">
      <header>
        <div>
          <span className="eyebrow">Platform managed · versioned definition</span>
          <h3 id="quality-managed-rules-title">플랫폼 기본 Rule set</h3>
        </div>
        <button className="button button-secondary" type="button" onClick={onOpenTemplates}>
          대상 필드 지정
        </button>
      </header>
      <div>
        {query.data.managed_rule_sets.map((rule) => <ManagedRuleCard key={rule.indicator_id} rule={rule} />)}
      </div>
    </section>
    {query.data.schemas_truncated && (
      <p className="callout" role="status">권한 범위의 스키마가 500개를 넘어 첫 500개만 표시합니다.</p>
    )}
    <section className="panel quality-dashboard-schema-panel" aria-labelledby="quality-schema-status-title">
      <header>
        <div>
          <span className="eyebrow">Schema comparison · click a metric</span>
          <h3 id="quality-schema-status-title">스키마별 품질 정상률</h3>
        </div>
        <span>{countText(query.data.schemas.length)}개 표시</span>
      </header>
      <DenseDataTable
        caption="스키마별 테이블 수와 품질 지표"
        columns={columns}
        data={query.data.schemas}
        getRowId={(row) => row.schema_id}
        emptyMessage="표시할 권한 범위의 스키마가 없습니다."
      />
    </section>
    {selectedSchema && analysis && <QualityAnalysisDialog
      open
      schema={selectedSchema}
      definitions={query.data.managed_rule_sets}
      activeIndicatorId={analysis.indicatorId}
      onIndicator={(indicatorId) => setAnalysis({
        schemaId: selectedSchema.schema_id,
        indicatorId,
      })}
      onOpenTemplates={() => {
        setAnalysis(undefined)
        onOpenTemplates()
      }}
      onClose={() => setAnalysis(undefined)}
    />}
  </section>
}

function DashboardKpi({
  icon,
  label,
  value,
  detail,
  tooltip,
}: {
  icon: ReactNode
  label: string
  value: string
  detail: string
  tooltip?: string
}) {
  return <article className="quality-dashboard-kpi" title={tooltip}>
    <span className="quality-dashboard-kpi-icon" aria-hidden="true">{icon}</span>
    <div><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>
  </article>
}

function ManagedRuleCard({ rule }: { rule: QualityManagedRuleSet }) {
  return <article className={`quality-managed-rule quality-managed-rule-${rule.indicator_id.toLowerCase()}`}>
    <header>
      <strong>{rule.name}</strong>
      <span>기본 제공</span>
    </header>
    <p>{rule.definition}</p>
    <small title={rule.calculation}>계산식 · {rule.calculation}</small>
  </article>
}

function IndicatorButton({
  indicator: value,
  calculation,
  onClick,
}: {
  indicator: QualityDashboardIndicator
  calculation?: string
  onClick: () => void
}) {
  return <button
    type="button"
    className="quality-dashboard-indicator"
    onClick={(event) => {
      event.stopPropagation()
      onClick()
    }}
    title={calculation
      ? `${indicatorLabels[value.indicator_id]} · ${calculation}`
      : `${indicatorLabels[value.indicator_id]} 계산식과 위험 테이블 보기`}
  >
    <QualityStatus value={value.outcome} />
    <strong>{basisPointsText(value.score_basis_points)}</strong>
  </button>
}

function QualityAnalysisDialog({
  open,
  schema,
  definitions,
  activeIndicatorId,
  onIndicator,
  onOpenTemplates,
  onClose,
}: {
  open: boolean
  schema: QualitySchemaDashboard
  definitions: QualityManagedRuleSet[]
  activeIndicatorId: QualityIndicatorId
  onIndicator: (indicatorId: QualityIndicatorId) => void
  onOpenTemplates: () => void
  onClose: () => void
}) {
  const value = indicator(schema, activeIndicatorId)
  const definition = definitions.find((item) => item.indicator_id === activeIndicatorId)
  const [expandedRiskId, setExpandedRiskId] = useState<string>()
  const riskColumns = useMemo<ColumnDef<QualityDashboardRisk>[]>(() => [
    { accessorKey: 'asset_name', header: 'Risk table', size: 210 },
    {
      accessorKey: 'field_identifier',
      header: 'Field',
      size: 180,
      cell: ({ row }) => row.original.field_identifier || 'Table profile',
    },
    {
      accessorKey: 'severity',
      header: 'Risk limit',
      size: 120,
      cell: ({ row }) => <QualityStatus value={row.original.severity} />,
    },
    {
      accessorKey: 'score_basis_points',
      header: '품질 수치',
      size: 110,
      cell: ({ row }) => basisPointsText(row.original.score_basis_points),
    },
    {
      accessorKey: 'observed_at',
      header: '최근 평가',
      size: 170,
      cell: ({ row }) => dateTimeText(row.original.observed_at),
    },
  ], [])

  useEffect(() => setExpandedRiskId(undefined), [activeIndicatorId])

  return <Dialog
    open={open}
    title={`${schemaPath(schema)} · 품질 분석`}
    description="왼쪽 지표를 전환해 동일 스키마의 계산 근거와 위험 필드를 비교합니다."
    size="large"
    onRequestClose={onClose}
    footer={<button className="button button-secondary" type="button" onClick={onClose}>닫기</button>}
  >
    <div className="quality-analysis-layout">
      <nav className="quality-analysis-tabs" aria-label="품질 분석 지표">
        {indicatorIds.map((indicatorId) => <button
          key={indicatorId}
          type="button"
          className={indicatorId === activeIndicatorId ? 'active' : ''}
          aria-pressed={indicatorId === activeIndicatorId}
          onClick={() => onIndicator(indicatorId)}
        >
          <span>{indicatorLabels[indicatorId]}</span>
          <QualityStatus value={indicator(schema, indicatorId).outcome} />
        </button>)}
      </nav>
      <section className="quality-analysis-body">
        <header className="quality-analysis-summary">
          <div>
            <span className="eyebrow">{definition?.contract_version}</span>
            <h3>{indicatorLabels[activeIndicatorId]} 분석</h3>
            <p>{definition?.definition}</p>
            {definition?.target_grain === 'FIELD' && (
              <button className="button button-secondary" type="button" onClick={onOpenTemplates}>
                컬럼 타입·호환 필드로 대상 지정
              </button>
            )}
          </div>
          <ScoreGauge value={value.score_basis_points} label={indicatorLabels[activeIndicatorId]} />
        </header>
        <div className="quality-analysis-facts">
          <Fact label={definition?.target_grain === 'TABLE' ? 'count된 테이블' : 'count된 필드'} value={countText(value.counted_target_count)} />
          <Fact label={definition?.target_grain === 'TABLE' ? '대상 테이블' : '대상 필드'} value={countText(value.target_count)} />
          <Fact label="대상 비율" value={basisPointsText(value.coverage_basis_points)} />
          <Fact label="위험 항목" value={countText(value.risk_count)} />
        </div>
        <section className="quality-analysis-report">
          <header>
            <div><span className="eyebrow">Evidence-bounded report</span><h4>평가결과 레포트</h4></div>
            <span>{value.report_state === 'LLM_GENERATED'
              ? 'LLM 생성'
              : value.report_state === 'UNAVAILABLE'
                ? '권한 제한'
                : '서버 사실 요약'}</span>
          </header>
          <p>{value.report_summary}</p>
          {value.report_state === 'FACTS_ONLY' && (
            <small>승인된 Quality 전용 LLM 경로가 연결되기 전에는 서버가 검증한 집계만 표시하며, LLM 문장처럼 추정하지 않습니다.</small>
          )}
          {definition && <small>계산식 · {definition.calculation}</small>}
        </section>
        <section className="quality-analysis-risks" aria-labelledby="quality-analysis-risk-title">
          <header>
            <div><span className="eyebrow">Latest successful evidence</span><h4 id="quality-analysis-risk-title">Risk가 있는 테이블</h4></div>
            <strong>{countText(value.risk_count)}개</strong>
          </header>
          <DenseDataTable
            caption={`${indicatorLabels[activeIndicatorId]} 위험 테이블`}
            columns={riskColumns}
            data={value.risks}
            getRowId={(row) => row.risk_id}
            expandedRowId={expandedRiskId}
            onRowActivate={(row) => setExpandedRiskId((current) => current === row.risk_id ? undefined : row.risk_id)}
            renderExpandedRow={(row) => <RiskDetail risk={row} />}
            emptyMessage="최근 성공 실행 기준으로 표시할 위험 테이블이 없습니다."
          />
          {value.risk_count > value.risks.length && (
            <small>성능 보호를 위해 최근 위험 {countText(value.risks.length)}건만 상세 표시합니다.</small>
          )}
        </section>
      </section>
    </div>
  </Dialog>
}

function ScoreGauge({ value, label }: { value: number | null; label: string }) {
  const degrees = value === null ? 0 : Math.round(value / 10_000 * 360)
  return <div
    className="quality-score-gauge"
    style={{ background: `conic-gradient(var(--blue-700) ${degrees}deg, #e8eef1 ${degrees}deg)` }}
    role="img"
    aria-label={`${label} 품질 수치 ${basisPointsText(value)}`}
  >
    <div><strong>{basisPointsText(value)}</strong><span>품질 수치</span></div>
  </div>
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value}</strong></div>
}

function RiskDetail({ risk }: { risk: QualityDashboardRisk }) {
  return <div className="quality-risk-detail">
    <div><span>필드</span><strong>{risk.field_identifier || 'Table profile'}</strong></div>
    <div><span>결과</span><QualityStatus value={risk.outcome} /></div>
    <div><span>평가 값</span><strong>{countText(risk.evaluated_count)}</strong></div>
    <div><span>실패 값</span><strong>{countText(risk.failed_count)}</strong></div>
    <p>{risk.detail}</p>
  </div>
}

function schemaPath(schema: QualitySchemaDashboard): string {
  return [schema.platform, schema.database_name, schema.schema_name]
    .filter(Boolean)
    .join(' / ') || '미분류 스키마'
}

function indicator(
  schema: QualitySchemaDashboard,
  indicatorId: QualityIndicatorId,
): QualityDashboardIndicator {
  const value = schema.indicators.find((item) => item.indicator_id === indicatorId)
  if (!value) throw new Error(`Missing dashboard indicator: ${indicatorId}`)
  return value
}

function ratioBasisPoints(numerator: number, denominator: number): number | null {
  if (denominator <= 0) return null
  return Math.round(numerator / denominator * 10_000)
}
