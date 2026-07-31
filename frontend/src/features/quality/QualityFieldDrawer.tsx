import { useEffect, useId, useMemo, useRef } from 'react'
import { createPortal } from 'react-dom'
import { useQuery } from '@tanstack/react-query'
import { ErrorNotice } from '../../components/ErrorNotice'
import { qualityQueryKey, type QualityApi, type QualitySecurityBoundary } from './qualityApi'
import type { QualityAssetField, QualityFieldWorkspace } from './qualityFieldTypes'
import { basisPointsText, countText, dateTimeText, QualityStatus } from './QualityShared'
import { isAuthorizationBoundaryError } from './useBoundedQualityRunPolling'

const focusableSelector = [
  'button:not([disabled])',
  'a[href]',
  'input:not([disabled])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

export function QualityFieldDrawer({
  open,
  api,
  boundary,
  assetId,
  field,
  onClose,
  onBoundaryInvalid,
}: {
  open: boolean
  api: QualityApi
  boundary: QualitySecurityBoundary
  assetId: string
  field?: QualityAssetField
  onClose: () => void
  onBoundaryInvalid: () => void
}) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const closeRef = useRef(onClose)
  const titleId = useId()
  const workspace = useQuery({
    queryKey: qualityQueryKey(boundary, 'field-workspace', assetId, field?.field_identifier),
    queryFn: ({ signal }) => api.fieldWorkspace(
      assetId,
      field?.field_identifier ?? '',
      boundary.cacheScope,
      signal,
    ),
    enabled: open && Boolean(field),
    staleTime: 0,
    gcTime: 30_000,
    retry: false,
  })

  useEffect(() => { closeRef.current = onClose }, [onClose])
  useEffect(() => {
    if (isAuthorizationBoundaryError(workspace.error)) onBoundaryInvalid()
  }, [onBoundaryInvalid, workspace.error])
  useEffect(() => {
    if (!open) return
    const dialog = dialogRef.current
    if (!dialog) return
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    if (typeof dialog.showModal === 'function') dialog.showModal()
    else dialog.setAttribute('open', '')
    ;(dialog.querySelector<HTMLElement>(focusableSelector) ?? dialog).focus()
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        closeRef.current()
        return
      }
      if (event.key !== 'Tab') return
      const candidates = Array.from(dialog.querySelectorAll<HTMLElement>(focusableSelector))
      const first = candidates[0]
      const last = candidates.at(-1)
      if (!first || !last) {
        event.preventDefault()
        dialog.focus()
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault(); last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus()
      }
    }
    dialog.addEventListener('keydown', keydown)
    return () => {
      dialog.removeEventListener('keydown', keydown)
      if (dialog.open && typeof dialog.close === 'function') dialog.close()
      previous?.focus()
    }
  }, [open])

  if (!open || !field) return null
  return createPortal(
    <dialog
      ref={dialogRef}
      className="quality-field-drawer"
      aria-modal="true"
      aria-labelledby={titleId}
      tabIndex={-1}
      onCancel={(event) => { event.preventDefault(); onClose() }}
      onClick={(event) => { if (event.target === event.currentTarget) onClose() }}
    >
      <section className="quality-field-drawer-surface">
        <header className="quality-field-drawer-header">
          <div>
            <span className="eyebrow">Field quality detail</span>
            <h2 id={titleId}>{field.display_path}</h2>
            <p>{field.logical_type} · server field ID {field.field_identifier}</p>
          </div>
          <button type="button" aria-label={`${field.display_path} 상세 닫기`} onClick={onClose}>×</button>
        </header>
        <div className="quality-field-drawer-body">
          <section className="quality-field-drawer-score" aria-label="필드 최신 품질 요약">
            <div><span>필드 점수</span><strong>{basisPointsText(field.latest_score_basis_points)}</strong></div>
            <QualityStatus value={field.latest_quality_outcome} />
            <div><span>활성 룰</span><strong>{countText(field.active_rule_count)}</strong></div>
            <div><span>설정 룰</span><strong>{countText(field.configured_rule_count)}</strong></div>
          </section>
          {workspace.isPending && <p className="quality-loading" role="status">필드 품질 이력을 불러오는 중입니다.</p>}
          {workspace.error && <ErrorNotice error={workspace.error} />}
          {workspace.data && <>
            <ScorePolicy value={workspace.data.score_policy} />
            <section className="quality-field-drawer-section">
              <header><h3>적용·제안된 룰</h3><span>{countText(workspace.data.rules.length)}개</span></header>
              {workspace.data.rules.length === 0
                ? <p className="quality-empty">이 필드에 설정된 룰이 없습니다.</p>
                : <ul className="quality-field-rule-list">{workspace.data.rules.map((rule) => <li key={rule.rule_definition_id}>
                  <div><strong>{rule.rule_set_name}</strong><small>v{rule.version_number} · {rule.kind}</small></div>
                  <QualityStatus value={rule.version_state} />
                  <span>{rule.severity === 'BLOCKING' ? '차단 실패' : '권고 실패'}</span>
                </li>)}</ul>}
            </section>
            <section className="quality-field-drawer-section">
              <header><h3>필드 검사 이력</h3><span>최근 {countText(workspace.data.runs.length)}건</span></header>
              {workspace.data.runs.length === 0
                ? <p className="quality-empty">이 필드를 평가한 실행 이력이 없습니다.</p>
                : <div className="quality-compact-table-scroll"><table className="quality-compact-table">
                  <thead><tr><th>검사 시각</th><th>룰셋</th><th>실행</th><th>필드 결과</th><th>점수</th><th>평가 값</th><th>결측</th><th>범위 이탈</th></tr></thead>
                  <tbody>{workspace.data.runs.map((run) => <tr key={run.run_id}>
                    <td>{dateTimeText(run.completed_at ?? run.created_at)}</td>
                    <td>{run.rule_set_name}</td>
                    <td><QualityStatus value={run.state} /></td>
                    <td><QualityStatus value={run.field_quality_outcome} /></td>
                    <td>{basisPointsText(run.score_basis_points)}</td>
                    <td>{countText(run.evaluated_value_count)}</td>
                    <td>{countText(run.missing_count)}</td>
                    <td>{countText(run.unexpected_count)}</td>
                  </tr>)}</tbody>
                </table></div>}
            </section>
            <FieldTrend points={workspace.data.trend} />
          </>}
        </div>
      </section>
    </dialog>,
    document.body,
  )
}

function ScorePolicy({ value }: { value: QualityFieldWorkspace['score_policy'] }) {
  return <details className="quality-field-policy">
    <summary>상태 산정 기준 · {value.policy_id} v{value.policy_version}</summary>
    <p>점수: 통과 룰 ÷ 평가된 전체 룰. 차단 실패가 하나라도 있으면 FAIL, 차단 실패 없이 권고 실패가 있으면 WARN, 모두 통과하면 PASS, 평가가 없으면 UNKNOWN입니다.</p>
    <code>{value.policy_hash.slice(0, 12)}…</code>
  </details>
}

function FieldTrend({ points }: { points: QualityFieldWorkspace['trend'] }) {
  const plotted = useMemo(() => points.flatMap((point, index) => {
    if (point.score_basis_points === null) return []
    const x = points.length <= 1 ? 220 : 16 + index * (408 / (points.length - 1))
    const y = 112 - point.score_basis_points * 0.0096
    return [{ x, y, point }]
  }), [points])
  return <section className="quality-field-drawer-section">
    <header><h3>필드 점수 추이</h3><span>최근 30일</span></header>
    {plotted.length === 0
      ? <p className="quality-empty">표시할 필드 점수 추이가 없습니다.</p>
      : <svg className="quality-field-trend" viewBox="0 0 440 128" role="img" aria-label="선택 필드의 최근 30일 품질 점수 추이">
        {[16, 64, 112].map((y) => <line key={y} x1="16" x2="424" y1={y} y2={y} />)}
        <polyline points={plotted.map(({ x, y }) => `${x},${y}`).join(' ')} />
        {plotted.map(({ x, y, point }) => <circle key={point.bucket_start} cx={x} cy={y} r="4"><title>{dateTimeText(point.bucket_start)} · {basisPointsText(point.score_basis_points)}</title></circle>)}
      </svg>}
  </section>
}
