import type { ChangeRequestRecord, ChangeRequestState } from '../../api/types'

export const changeStateOptions: ReadonlyArray<{ value: '' | ChangeRequestState; label: string }> = [
  { value: '', label: '전체 상태' },
  { value: 'REGISTERED', label: '접수' },
  { value: 'IN_REVIEW', label: '검토 중' },
  { value: 'TESTING', label: '변경 / 테스트' },
  { value: 'FINAL_REVIEW', label: '최종 검토' },
  { value: 'APPLY_QUEUED', label: '적용 대기' },
  { value: 'APPLYING', label: '적용 중' },
  { value: 'APPLIED', label: '적용 완료' },
  { value: 'COMPLETED', label: '완료' },
  { value: 'APPLY_FAILED', label: '적용 실패' },
  { value: 'CHANGES_REQUESTED', label: '보완 요청' },
  { value: 'REJECTED', label: '반려' },
  { value: 'CANCELLED', label: '취소' },
]

const stateLabels = new Map(changeStateOptions
  .filter((option): option is { value: ChangeRequestState; label: string } => option.value !== '')
  .map((option) => [option.value, option.label]))

export function changeStateLabel(state: ChangeRequestState): string {
  return stateLabels.get(state) ?? state
}

export interface ChangeActionHint {
  id: string
  kind: 'APPROVAL' | 'TRANSITION' | 'INTAKE_COMPLETE'
  label: string
  stage?: 'REVIEW' | 'TEST' | 'FINAL'
  decision?: 'APPROVED'
  targetState?: ChangeRequestState
  tone?: 'primary' | 'danger' | 'neutral'
  disabledReason?: string
}

const transition = (
  targetState: ChangeRequestState,
  label: string,
  tone: ChangeActionHint['tone'] = 'neutral',
): ChangeActionHint => ({
  id: `transition-${targetState.toLowerCase()}`,
  kind: 'TRANSITION',
  label,
  targetState,
  tone,
})

const reviewApproval: ChangeActionHint = {
  id: 'approval-review',
  kind: 'APPROVAL',
  label: '검토 승인 및 변경 / 테스트로 이동',
  stage: 'REVIEW',
  decision: 'APPROVED',
}

const testApproval: ChangeActionHint = {
  id: 'approval-test',
  kind: 'APPROVAL',
  label: '승인 요청',
  stage: 'TEST',
  decision: 'APPROVED',
  tone: 'primary',
}

const finalApproval: ChangeActionHint = {
  id: 'approval-final',
  kind: 'APPROVAL',
  label: '최종 승인 기록',
  stage: 'FINAL',
  decision: 'APPROVED',
  tone: 'primary',
}

const intakeCompletion: ChangeActionHint = {
  id: 'intake-complete',
  kind: 'INTAKE_COMPLETE',
  label: '수동 변경 완료 기록',
  tone: 'primary',
}

/**
 * State-derived presentation hints only. The API remains authoritative for current target scope,
 * actor separation, assurance and approval prerequisites on every command.
 */
export function changeActionHints(changeRequest: ChangeRequestRecord): ChangeActionHint[] {
  switch (changeRequest.state) {
    case 'REGISTERED':
      return [
        transition('IN_REVIEW', '검토 시작', 'primary'),
        transition('CANCELLED', '요청 취소', 'danger'),
      ]
    case 'IN_REVIEW': {
      const reviewApproved = changeRequest.approvals.some((approval) => (
        approval.round_id === changeRequest.current_round_id
        && approval.stage === 'REVIEW'
        && approval.decision === 'APPROVED'
      ))
      return [
        reviewApproved
          ? transition('TESTING', '변경 / 테스트로 이동', 'primary')
          : reviewApproval,
        transition('CHANGES_REQUESTED', '보완 요청', 'danger'),
        transition('CANCELLED', '요청 취소', 'danger'),
      ]
    }
    case 'TESTING': {
      const testPassed = changeRequest.test_runs.some((run) => (
        run.round_id === changeRequest.current_round_id && run.state === 'PASSED'
      ))
      const testApproved = changeRequest.approvals.some((approval) => (
        approval.round_id === changeRequest.current_round_id
        && approval.stage === 'TEST'
        && approval.decision === 'APPROVED'
      ))
      return [
        transition('CHANGES_REQUESTED', '보완 요청', 'danger'),
        testPassed
          ? testApproved
            ? transition('FINAL_REVIEW', '승인 요청', 'primary')
            : testApproval
          : testApproval,
      ]
    }
    case 'FINAL_REVIEW':
      return [
        finalApproval,
        ...(changeRequest.request_type === 'CHANGE_INTAKE'
          ? [intakeCompletion]
          : [transition('APPLY_QUEUED', '적용 대기열 등록', 'primary')]),
        transition('CHANGES_REQUESTED', '보완 요청', 'danger'),
        transition('REJECTED', '반려', 'danger'),
        transition('CANCELLED', '요청 취소', 'danger'),
      ]
    case 'APPLY_FAILED':
      return [
        transition('APPLY_QUEUED', '적용 재시도 요청', 'primary'),
        transition('CANCELLED', '요청 취소', 'danger'),
      ]
    case 'CHANGES_REQUESTED':
      return [
        transition('CANCELLED', '요청 취소', 'danger'),
      ]
    default:
      return []
  }
}
