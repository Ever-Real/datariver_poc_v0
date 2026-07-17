import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ChangeRequestRecord } from '../../api/types'
import { AssuranceNotice, type AssuranceActions } from '../../components/AssuranceNotice'
import { ErrorNotice } from '../../components/ErrorNotice'
import { AccordionItem } from '../../components/common/Accordion'
import { Dialog } from '../../components/common/Dialog'
import { TruncatedText } from '../../components/common/TruncatedText'
import { changeActionHints, changeStateLabel, type ChangeActionHint } from './changePresentation'

interface ChangeRequestDetailDialogProps extends AssuranceActions {
  open: boolean
  fallback?: ChangeRequestRecord
  value?: ChangeRequestRecord
  loading: boolean
  busy: boolean
  error?: unknown
  actionError?: unknown
  onClose: () => void
  onRefresh: () => void
  onAction: (action: ChangeActionHint) => void
}

function display(value: string | null | undefined): string {
  return value && value.trim() ? value : '—'
}

function eventTime(value: string): string {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('ko-KR', { hour12: false })
}

export function ChangeRequestDetailDialog({
  open,
  fallback,
  value,
  loading,
  busy,
  error,
  actionError,
  onClose,
  onRefresh,
  onAction,
  onStepUp,
  onPasswordReauth,
  onEnroll,
}: ChangeRequestDetailDialogProps) {
  const [expanded, setExpanded] = useState(() => new Set(['target', 'approvals', 'transitions']))
  const current = value ?? fallback
  const visibleError = actionError ?? error
  const hints = useMemo(() => value ? changeActionHints(value) : [], [value])
  const busyRef = useRef(busy)

  useEffect(() => {
    busyRef.current = busy
  }, [busy])

  useEffect(() => {
    setExpanded(new Set(['target', 'approvals', 'transitions']))
  }, [current?.id])

  const requestClose = useCallback(() => {
    if (!busyRef.current) onClose()
  }, [onClose])
  const toggle = (key: string) => setExpanded((previous) => {
    const next = new Set(previous)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    return next
  })

  return (
    <Dialog
      open={open}
      size="workspace"
      title={current ? `${current.number} · ${current.title}` : '변경 요청 상세'}
      description="현재 권한으로 서버가 다시 확인한 변경 요청과 불변 승인·전이 증거입니다."
      onRequestClose={requestClose}
      footer={<>
        <button type="button" className="button button-secondary" disabled={busy || loading} onClick={onRefresh}>상세 새로고침</button>
        <button type="button" className="button button-secondary" disabled={busy} onClick={requestClose}>닫기</button>
      </>}
    >
      <div className="governance-detail-dialog">
        {loading && (
          <div className="governance-detail-state" role="status" aria-live="polite">
            변경 요청을 다시 인가하고 불러오는 중입니다.
          </div>
        )}
        <AssuranceNotice
          error={visibleError}
          onStepUp={onStepUp}
          onPasswordReauth={onPasswordReauth}
          onEnroll={onEnroll}
        />
        <ErrorNotice error={visibleError} />

        {value && !loading && <>
          <section aria-labelledby="change-summary-heading">
            <div className="governance-section-heading">
              <div>
                <span className="governance-kicker">Request summary</span>
                <h3 id="change-summary-heading">요청 개요</h3>
              </div>
              <span className={`badge governance-state state-${value.state.toLowerCase()}`}>
                {changeStateLabel(value.state)} · {value.state}
              </span>
            </div>
            <dl className="governance-summary-grid">
              <div><dt>요청 유형</dt><dd>{value.request_type}</dd></div>
              <div><dt>분류등급</dt><dd>{value.classification}</dd></div>
              <div><dt>요청자</dt><dd><TruncatedText value={value.requester_id} /></dd></div>
              <div><dt>집계 버전</dt><dd>{value.version}</dd></div>
              <div className="wide"><dt>요청 설명</dt><dd>{display(value.description)}</dd></div>
            </dl>
          </section>

          <section className="governance-evidence-stack" aria-label="변경 요청 증거">
            <AccordionItem
              itemId="target"
              title="대상 및 원본 증거"
              summary={`${value.items.length}개 변경 항목`}
              expanded={expanded.has('target')}
              onToggle={() => toggle('target')}
            >
              {value.items.length === 0 && <p className="muted">표시 가능한 변경 항목이 없습니다.</p>}
              {value.items.map((item, index) => (
                <article className="governance-target-evidence" key={item.id}>
                  <header>
                    <strong>항목 {index + 1} · {item.aspect_name}</strong>
                    <span>{item.operation}</span>
                  </header>
                  <dl className="governance-summary-grid compact">
                    <div><dt>자산 ID</dt><dd><TruncatedText value={display(item.target_asset_id)} /></dd></div>
                    <div><dt>자산 유형</dt><dd>{display(item.target_asset_type)}</dd></div>
                    <div><dt>대상 등급</dt><dd>{display(item.target_classification)}</dd></div>
                    <div><dt>Lifecycle</dt><dd>{display(item.target_lifecycle)}</dd></div>
                    <div><dt>시스템 범위</dt><dd><TruncatedText value={display(item.target_system_id)} /></dd></div>
                    <div><dt>도메인 범위</dt><dd><TruncatedText value={display(item.target_domain_id)} /></dd></div>
                    <div><dt>원본 버전</dt><dd><TruncatedText value={display(item.target_source_version)} /></dd></div>
                    <div><dt>관측 시각</dt><dd>{item.target_observed_at ? <time dateTime={item.target_observed_at}>{eventTime(item.target_observed_at)}</time> : '—'}</dd></div>
                    <div className="wide"><dt>대상 식별자 · 읽기 전용</dt><dd><TruncatedText value={item.target_ref} /></dd></div>
                    <div className="wide"><dt>변경 전 / 변경 후 SHA-256</dt><dd><TruncatedText value={`${display(item.before_hash)} → ${display(item.after_hash)}`} /></dd></div>
                    <div className="wide"><dt>대상 binding SHA-256</dt><dd><TruncatedText value={display(item.target_binding_hash)} /></dd></div>
                  </dl>
                </article>
              ))}
            </AccordionItem>

            <AccordionItem
              itemId="approvals"
              title="승인 증거"
              summary={`${value.approvals.length}건`}
              expanded={expanded.has('approvals')}
              onToggle={() => toggle('approvals')}
            >
              {value.approvals.length === 0
                ? <p className="muted">기록된 승인 판단이 없습니다.</p>
                : <ol className="governance-audit-list">
                  {value.approvals.map((approval) => <li key={approval.id}>
                    <div><strong>{approval.stage} · {approval.decision}</strong><time dateTime={approval.occurred_at}>{eventTime(approval.occurred_at)}</time></div>
                    <p>{approval.reason}</p>
                    <TruncatedText value={`판단 주체 ${approval.actor_id}`} />
                  </li>)}
                </ol>}
            </AccordionItem>

            <AccordionItem
              itemId="transitions"
              title="상태 전이 이력"
              summary={`${value.transitions.length}건`}
              expanded={expanded.has('transitions')}
              onToggle={() => toggle('transitions')}
            >
              {value.transitions.length === 0
                ? <p className="muted">기록된 상태 전이가 없습니다.</p>
                : <ol className="governance-audit-list">
                  {value.transitions.map((transition) => <li key={transition.id}>
                    <div><strong>{changeStateLabel(transition.from_state)} → {changeStateLabel(transition.to_state)}</strong><time dateTime={transition.occurred_at}>{eventTime(transition.occurred_at)}</time></div>
                    <p>{transition.reason}</p>
                    <TruncatedText value={`수행 주체 ${transition.actor_id}`} />
                  </li>)}
                </ol>}
            </AccordionItem>
          </section>

          <section className="governance-command-panel" aria-labelledby="change-command-heading">
            <div className="governance-section-heading">
              <div>
                <span className="governance-kicker">Governed commands</span>
                <h3 id="change-command-heading">검토 및 상태 명령</h3>
              </div>
            </div>
            <div className="notice governance-server-authority" role="note">
              <strong>화면의 명령은 현재 상태를 기준으로 한 힌트입니다.</strong>
              <span>서버가 클릭할 때마다 현재 대상 권한, 요청자 분리, 강한 인증과 필요한 승인 수를 최종 판단합니다. 인증 후에도 작업은 자동 재실행되지 않습니다.</span>
            </div>
            {hints.length > 0
              ? <div className="governance-command-actions" aria-label="사용 가능한 상태 기반 명령 힌트">
                {hints.map((hint) => <button
                  type="button"
                  key={hint.id}
                  className={`button ${hint.tone === 'primary' ? '' : 'button-secondary'} ${hint.tone === 'danger' ? 'button-danger' : ''}`.trim()}
                  disabled={busy}
                  onClick={() => onAction(hint)}
                >
                  {hint.label}
                </button>)}
              </div>
              : <p className="governance-command-empty">이 상태에서 브라우저가 시작할 수 있는 명령이 없습니다.</p>}
          </section>
        </>}
      </div>
    </Dialog>
  )
}
