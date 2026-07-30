import { useMemo } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import type { QualityIssueSummary } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { CursorPagination } from '../../components/common/CursorPagination'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import type { QualityApi, QualitySecurityBoundary } from './qualityApi'
import {
  countText,
  dateTimeText,
  QualityStatus,
} from './QualityShared'
import { useQualityCursorPage } from './useQualityCursorPage'

export function QualityIssuesTab({
  api,
  boundary,
  onBoundaryInvalid,
}: {
  api: QualityApi
  boundary: QualitySecurityBoundary
  onBoundaryInvalid: () => void
}) {
  const issues = useQualityCursorPage({
    boundary,
    resource: 'issues',
    load: (cursor, signal) => api.issues(cursor, signal),
    onBoundaryInvalid,
  })
  const columns = useMemo<ColumnDef<QualityIssueSummary>[]>(() => [
    { accessorKey: 'asset_name', header: '대상 자산', size: 190, enableSorting: false },
    { accessorKey: 'field_identifier', header: 'Field ID', size: 180, enableSorting: false },
    { accessorKey: 'kind', header: 'Rule', size: 100, enableSorting: false },
    { accessorKey: 'severity', header: 'Severity', size: 110, enableSorting: false },
    {
      accessorKey: 'outcome',
      header: '결과',
      size: 150,
      enableSorting: false,
      cell: ({ row }) => <QualityStatus value={row.original.outcome} />,
    },
    {
      accessorKey: 'occurrence_count',
      header: '발생',
      size: 90,
      enableSorting: false,
      cell: ({ row }) => countText(row.original.occurrence_count),
    },
    {
      accessorKey: 'last_observed_at',
      header: '최근 관측',
      size: 170,
      enableSorting: false,
      cell: ({ row }) => dateTimeText(row.original.last_observed_at),
    },
  ], [])

  return <section className="quality-tab-content">
    <header className="quality-section-header">
      <div>
        <span className="eyebrow">Server aggregation · no client inference</span>
        <h2>품질 이슈</h2>
        <p>서버가 권한 범위 안에서 집계한 실패 Rule만 표시합니다.</p>
      </div>
    </header>
    <section className="panel quality-list-panel" aria-labelledby="quality-issue-list-title">
      <header>
        <div>
          <span className="eyebrow">Opaque issue identifiers</span>
          <h3 id="quality-issue-list-title">Observed Issues</h3>
        </div>
      </header>
      {issues.error && <ErrorNotice error={issues.error} />}
      <DenseDataTable
        caption="권한 범위의 품질 이슈 집계"
        columns={columns}
        data={issues.data?.items ?? []}
        getRowId={(row) => row.issue_id}
        loading={issues.isPending}
        emptyMessage="현재 권한 범위에서 관측된 품질 이슈가 없습니다."
      />
      <CursorPagination {...issues.pagination} label="품질 이슈 페이지 탐색" />
    </section>
  </section>
}
