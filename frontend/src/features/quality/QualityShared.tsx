import type { ReactNode } from 'react'
import type { QualityCapabilityAxis } from '../../api/types'
import { GovernedUnavailable } from '../../components/common/GovernedUnavailable'

export function basisPointsText(value: number | null | undefined): string {
  if (value === null || value === undefined) return '평가 없음'
  return `${(value / 100).toLocaleString('ko-KR', {
    minimumFractionDigits: value % 100 === 0 ? 0 : 2,
    maximumFractionDigits: 2,
  })}%`
}

export function countText(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : value.toLocaleString('ko-KR')
}

export function dateTimeText(value: string | null | undefined): string {
  if (!value) return '—'
  const parsed = new Date(value)
  return Number.isFinite(parsed.getTime()) ? parsed.toLocaleString('ko-KR') : '—'
}

export function optionalText(value: string | null | undefined): string {
  return value?.trim() || '—'
}

export function QualityStatus({
  value,
}: {
  value: string | null | undefined
}) {
  const label = value || 'UNKNOWN'
  return <span className={`quality-status quality-status-${label.toLowerCase().replaceAll('_', '-')}`}>
    <span aria-hidden="true">{statusSymbol(label)}</span>{label}
  </span>
}

export function QualityAxisLock({
  axis,
  title,
  children,
}: {
  axis: QualityCapabilityAxis | undefined
  title: string
  children?: ReactNode
}) {
  if (axis?.state === 'AVAILABLE') return <>{children}</>
  return <GovernedUnavailable
    compact
    title={title}
    description={axis?.reason_code
      ? `서버 capability가 ${axis.reason_code} 사유로 이 기능을 열지 않았습니다.`
      : '현재 권한 또는 배포 준비 상태에서 이 기능을 사용할 수 없습니다.'}
  />
}

function statusSymbol(value: string): string {
  if (['PASS', 'SUCCEEDED', 'AVAILABLE', 'READY', 'COMPLETE', 'CURRENT', 'ACTIVE'].includes(value)) return '✓'
  if (['WARN', 'ADVISORY_FAIL', 'PARTIAL', 'STALE', 'RETRY_WAIT'].includes(value)) return '△'
  if (['FAIL', 'FAILED', 'BLOCKING_FAIL', 'CANCELLED', 'DENIED'].includes(value)) return '×'
  if (['RUNNING', 'QUEUED', 'CANCEL_REQUESTED'].includes(value)) return '↻'
  return '?'
}
