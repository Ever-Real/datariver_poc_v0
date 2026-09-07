import { useEffect, useMemo, useState } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import type {
  QualityCapabilityAxis,
  QualityExpectationResult,
  QualityRunSummary,
} from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { CursorPagination } from '../../components/common/CursorPagination'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import { Dialog } from '../../components/common/Dialog'
import type { QualityApi, QualitySecurityBoundary } from './qualityApi'
import {
  basisPointsText,
  countText,
  dateTimeText,
  optionalText,
  QualityAxisLock,
  QualityStatus,
} from './QualityShared'
import { useBoundedQualityRunPolling } from './useBoundedQualityRunPolling'
import { useQualityCursorPage } from './useQualityCursorPage'

export function QualityRunsTab({
  api,
  boundary,
  axes,
  selectedRunId,
  onSelectedRun,
  onBoundaryInvalid,
}: {
  api: QualityApi
  boundary: QualitySecurityBoundary
  axes: Map<string, QualityCapabilityAxis>
  selectedRunId?: string
  onSelectedRun: (id?: string) => void
  onBoundaryInvalid: () => void
}) {
  const [selected, setSelected] = useState<QualityRunSummary>()
  const runs = useQualityCursorPage({
    boundary,
    resource: 'runs',
    load: (cursor, signal) => api.runs(cursor, signal),
    onBoundaryInvalid,
  })

  useEffect(() => {
    const requested = runs.data?.items.find((item) => item.run_id === selectedRunId)
    setSelected(requested)
    if (selectedRunId && runs.data && !requested) onSelectedRun(undefined)
  }, [onSelectedRun, runs.data, selectedRunId])

  const poll = useBoundedQualityRunPolling({
    api,
    boundary,
    selectedRun: selected,
    onBoundaryInvalid,
  })
  const current = poll.run ?? selected
  const columns = useMemo<ColumnDef<QualityRunSummary>[]>(() => [
    { accessorKey: 'asset_name', header: '대상 자산', size: 180, enableSorting: false },
    { accessorKey: 'rule_set_name', header: 'Rule Set', size: 190, enableSorting: false },
    { accessorKey: 'trigger_kind', header: 'Trigger', size: 100, enableSorting: false },
    { accessorKey: 'state', header: '실행 상태', size: 130, enableSorting: false, cell: ({ row }) => <QualityStatus value={row.original.state} /> },
    { accessorKey: 'quality_outcome', header: '품질 결과', size: 120, enableSorting: false, cell: ({ row }) => <QualityStatus value={row.original.quality_outcome} /> },
    { accessorKey: 'score_basis_points', header: 'Score', size: 90, enableSorting: false, cell: ({ row }) => basisPointsText(row.original.score_basis_points) },
    { accessorKey: 'created_at', header: '접수 시각', size: 170, enableSorting: false, cell: ({ row }) => dateTimeText(row.original.created_at) },
    { accessorKey: 'completed_at', header: '완료 시각', size: 170, enableSorting: false, cell: ({ row }) => dateTimeText(row.original.completed_at) },
  ], [])

  return <section className="quality-tab-content">
    <header className="quality-section-header">
      <div><span className="eyebrow">Durable canonical runs</span><h2>실행 이력</h2><p>실행 상태와 품질 결과를 서로 다른 축으로 표시합니다.</p></div>
    </header>
    <div className="quality-capability-locks">
      <QualityAxisLock axis={axes.get('manual_execution')} title="수동 실행 잠김" />
      <QualityAxisLock axis={axes.get('scheduling')} title="예약 실행 잠김" />
      <QualityAxisLock axis={axes.get('operations')} title="운영 상세 잠김" />
    </div>
    <section className="panel quality-list-panel" aria-labelledby="quality-run-list-title">
      <header><div><span className="eyebrow">Server cursor page</span><h3 id="quality-run-list-title">Validation Runs</h3></div></header>
      {runs.error && <ErrorNotice error={runs.error} />}
      <DenseDataTable
        caption="품질 실행 이력"
        columns={columns}
        data={runs.data?.items ?? []}
        getRowId={(row) => row.run_id}
        loading={runs.isPending}
        emptyMessage="현재 권한 범위에서 조회 가능한 실행 이력이 없습니다."
        selectedRowId={selected?.run_id}
        onRowActivate={(row) => {
          setSelected(row)
          onSelectedRun(row.run_id)
        }}
      />
      <CursorPagination {...runs.pagination} label="품질 실행 이력 페이지 탐색" />
    </section>
    <Dialog
      open={Boolean(current)}
      title={current ? `${current.asset_name} · 실행 상세` : '실행 상세'}
      description="선택한 non-terminal Run만 제한적으로 상태를 갱신합니다."
      size="large"
      onRequestClose={() => {
        setSelected(undefined)
        onSelectedRun(undefined)
      }}
      footer={poll.stopped && current ? <button type="button" className="button button-secondary" onClick={poll.refresh}>상태 수동 새로고침</button> : undefined}
    >
      {current && <>
        <div className="quality-run-axis-summary" aria-label="실행과 품질 상태">
          <div><span>실행 상태</span><QualityStatus value={current.state} /></div>
          <div><span>품질 결과</span><QualityStatus value={current.quality_outcome} /></div>
          <div><span>Score</span><strong>{basisPointsText(current.score_basis_points)}</strong></div>
        </div>
        <dl className="quality-detail-list">
          <div><dt>Rule Set</dt><dd>{current.rule_set_name}</dd></div>
          <div><dt>Trigger</dt><dd>{current.trigger_kind}</dd></div>
          <div><dt>PASS</dt><dd>{countText(current.passed_count)}</dd></div>
          <div><dt>Advisory fail</dt><dd>{countText(current.advisory_failed_count)}</dd></div>
          <div><dt>Blocking fail</dt><dd>{countText(current.blocking_failed_count)}</dd></div>
          <div><dt>접수</dt><dd>{dateTimeText(current.created_at)}</dd></div>
          <div><dt>완료</dt><dd>{dateTimeText(current.completed_at)}</dd></div>
          <div><dt>실패 코드</dt><dd>{optionalText(current.failure_code)}</dd></div>
        </dl>
        {poll.polling && <p className="quality-poll-state">선택 Run 상태 확인 중 · {poll.attempts}/20</p>}
        {poll.stopped && <p className="quality-poll-stopped" role="status">자동 상태 확인이 종료되었습니다. Run 종료를 의미하지 않습니다.</p>}
        {poll.error && <ErrorNotice error={poll.error} />}
        <QualityRunResults
          api={api}
          boundary={boundary}
          runId={current.run_id}
          onBoundaryInvalid={onBoundaryInvalid}
        />
      </>}
    </Dialog>
  </section>
}

function QualityRunResults({
  api,
  boundary,
  runId,
  onBoundaryInvalid,
}: {
  api: QualityApi
  boundary: QualitySecurityBoundary
  runId: string
  onBoundaryInvalid: () => void
}) {
  const results = useQualityCursorPage({
    boundary,
    resource: 'run-results',
    scope: [runId],
    load: (cursor, signal) => api.runResults(runId, cursor, signal),
    onBoundaryInvalid,
  })
  const columns = useMemo<ColumnDef<QualityExpectationResult>[]>(() => [
    { accessorKey: 'field_identifier', header: 'Field ID', size: 180, enableSorting: false },
    { accessorKey: 'kind', header: 'Rule', size: 100, enableSorting: false },
    { accessorKey: 'severity', header: 'Severity', size: 100, enableSorting: false },
    { accessorKey: 'outcome', header: '결과', size: 140, enableSorting: false, cell: ({ row }) => <QualityStatus value={row.original.outcome} /> },
    { accessorKey: 'evaluated_count', header: '평가', size: 90, enableSorting: false, cell: ({ row }) => countText(row.original.evaluated_count) },
    { accessorKey: 'missing_count', header: 'Null', size: 90, enableSorting: false, cell: ({ row }) => countText(row.original.missing_count) },
    { accessorKey: 'unexpected_count', header: 'Unexpected', size: 100, enableSorting: false, cell: ({ row }) => countText(row.original.unexpected_count) },
    { accessorKey: 'duration_ms', header: '소요(ms)', size: 90, enableSorting: false, cell: ({ row }) => countText(row.original.duration_ms) },
  ], [])
  return <section className="quality-results" aria-labelledby="quality-run-results-title">
    <h3 id="quality-run-results-title">정규화 Rule 결과</h3>
    {results.error && <ErrorNotice error={results.error} />}
    <DenseDataTable
      caption="선택한 품질 실행의 정규화 결과"
      columns={columns}
      data={results.data?.items ?? []}
      getRowId={(row) => row.result_id}
      loading={results.isPending}
      emptyMessage="저장된 정규화 결과가 없습니다."
    />
    <CursorPagination {...results.pagination} label="품질 실행 결과 페이지 탐색" />
  </section>
}
