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
  kind: 'APPROVAL' | 'TRANSITION'
  label: string
  stage?: 'REVIEW' | 'FINAL'
  decision?: 'APPROVED'
  targetState?: ChangeRequestState
  tone?: 'primary' | 'danger' | 'neutral'
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
  label: '검토 승인 기록',
  stage: 'REVIEW',
  decision: 'APPROVED',
}

const finalApproval: ChangeActionHint = {
  id: 'approval-final',
  kind: 'APPROVAL',
  label: '최종 승인 기록',
  stage: 'FINAL',
  decision: 'APPROVED',
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
    case 'IN_REVIEW':
      return [
        reviewApproval,
        transition('TESTING', '변경 / 테스트로 이동', 'primary'),
        transition('FINAL_REVIEW', '최종 검토로 이동'),
        transition('CHANGES_REQUESTED', '보완 요청', 'danger'),
        transition('REJECTED', '반려', 'danger'),
        transition('CANCELLED', '요청 취소', 'danger'),
      ]
    case 'TESTING':
      return [
        transition('IN_REVIEW', '검토로 되돌리기'),
        transition('FINAL_REVIEW', '최종 검토 요청', 'primary'),
        transition('CHANGES_REQUESTED', '보완 요청', 'danger'),
        transition('REJECTED', '반려', 'danger'),
        transition('CANCELLED', '요청 취소', 'danger'),
      ]
    case 'FINAL_REVIEW':
      return [
        finalApproval,
        transition('APPLY_QUEUED', '적용 대기열 등록', 'primary'),
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
        transition('REGISTERED', '보완 후 재등록', 'primary'),
        transition('CANCELLED', '요청 취소', 'danger'),
      ]
    default:
      return []
  }
}
