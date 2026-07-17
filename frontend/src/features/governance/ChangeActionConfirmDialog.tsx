import { useCallback, useEffect, useRef } from 'react'
import type { ChangeRequestRecord } from '../../api/types'
import { Dialog } from '../../components/common/Dialog'
import { changeStateLabel, type ChangeActionHint } from './changePresentation'

interface ChangeActionConfirmDialogProps {
  action?: ChangeActionHint
  changeRequest?: ChangeRequestRecord
  reason: string
  busy: boolean
  onReasonChange: (reason: string) => void
  onCancel: () => void
  onConfirm: () => void
}

export function ChangeActionConfirmDialog({
  action,
  changeRequest,
  reason,
  busy,
  onReasonChange,
  onCancel,
  onConfirm,
}: ChangeActionConfirmDialogProps) {
  const busyRef = useRef(busy)
  useEffect(() => {
    busyRef.current = busy
  }, [busy])
  const requestClose = useCallback(() => {
    if (!busyRef.current) onCancel()
  }, [onCancel])
  const reasonValid = reason.trim().length > 0 && reason.length <= 4000

  return (
    <Dialog
      open={Boolean(action && changeRequest)}
      title="변경관리 명령 확인"
      description="현재 요청 버전과 수행할 명령을 확인한 뒤 명시적으로 제출하세요."
      onRequestClose={requestClose}
      footer={<>
        <button type="button" className="button button-secondary" disabled={busy} onClick={requestClose}>취소</button>
        <button type="button" className={`button ${action?.tone === 'danger' ? 'button-danger' : ''}`.trim()} disabled={busy || !reasonValid} onClick={onConfirm}>
          {busy ? '서버 확인 중…' : '확인 후 제출'}
        </button>
      </>}
    >
      {action && changeRequest && <div className="governance-confirm-dialog">
        <dl className="governance-summary-grid compact">
          <div className="wide"><dt>변경 요청</dt><dd>{changeRequest.number} · {changeRequest.title}</dd></div>
          <div><dt>현재 상태</dt><dd>{changeStateLabel(changeRequest.state)} · {changeRequest.state}</dd></div>
          <div><dt>현재 버전</dt><dd>{changeRequest.version}</dd></div>
          <div className="wide"><dt>제출할 명령</dt><dd>{action.label}</dd></div>
        </dl>
        <label htmlFor="governance-action-reason">판단 사유</label>
        <textarea
          id="governance-action-reason"
          value={reason}
          maxLength={4000}
          disabled={busy}
          aria-describedby="governance-action-reason-help"
          onChange={(event) => onReasonChange(event.target.value)}
        />
        <p id="governance-action-reason-help" className="governance-field-help">
          필수 · 최대 4,000자. 서버가 최신 버전, 현재 대상 권한, 승인 수와 요청자 분리를 다시 검사합니다.
        </p>
        <div className="notice governance-server-authority" role="note">
          <strong>거부 또는 재인증 뒤 자동으로 다시 제출되지 않습니다.</strong>
          <span>충돌 시 최신 상세를 불러오며 입력한 사유는 유지됩니다. 내용을 다시 확인하고 명령 버튼부터 새로 선택해야 합니다.</span>
        </div>
      </div>}
    </Dialog>
  )
}
