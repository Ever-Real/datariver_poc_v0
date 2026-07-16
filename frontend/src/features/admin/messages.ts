export type AdminMessageKey =
  | 'eyebrow' | 'title' | 'refresh' | 'memberships' | 'fallback' | 'retention' | 'holds' | 'erasure'
  | 'adminContext' | 'currentAssurance' | 'fallbackState' | 'enabled' | 'disabled'
  | 'members' | 'selectMember' | 'accessDocument' | 'active' | 'clearance' | 'groups'
  | 'allowedActions' | 'deniedActions' | 'systemScopes' | 'domainScopes' | 'directUpdate'
  | 'fallbackRequest' | 'reason' | 'hardwareAuth' | 'passwordReauth' | 'fallbackDisabled'
  | 'recentRequests' | 'approve' | 'reject' | 'consume' | 'expiresAt' | 'payloadHash'
  | 'policyProposal' | 'completedDays' | 'chatDays' | 'auditMonths' | 'archiveYears'
  | 'propose' | 'policyHistory' | 'automationDisabled' | 'holdPlacement' | 'dataClass'
  | 'scope' | 'scopeId' | 'placeHold' | 'holdHistory' | 'requestRelease'
  | 'releaseDecision' | 'confirmTitle' | 'confirm' | 'cancel' | 'working' | 'empty'
  | 'noErasure' | 'versionConflict' | 'makerCannotCheck' | 'select' | 'erasureRequest'
  | 'erasureDecision' | 'erasureHistory' | 'erasureNonExecuting' | 'targetType'
  | 'targetId' | 'targetVersion' | 'reviewTtlSeconds' | 'requestReview'

export type AdminMessages = Record<AdminMessageKey, string>

const ko: AdminMessages = {
  eyebrow: 'Governed administration', title: '관리자 및 보존 거버넌스', refresh: '새로고침',
  memberships: '계정·권한', fallback: 'Maker-Checker', retention: '보존정책', holds: 'Legal Hold', erasure: '파기 검토',
  adminContext: '현재 관리자 컨텍스트', currentAssurance: '인증 보증', fallbackState: '비밀번호 예외 경로',
  enabled: '활성', disabled: '비활성', members: '워크스페이스 멤버', selectMember: '편집할 멤버를 선택하세요.',
  accessDocument: '전체 Access 문서', active: '멤버십 활성', clearance: '허용 등급', groups: '그룹',
  allowedActions: '허용 Action', deniedActions: '거부 Action', systemScopes: '허용 System UUID',
  domainScopes: '허용 Domain UUID', directUpdate: '보안키로 직접 변경', fallbackRequest: '비밀번호 Maker 요청',
  reason: '사유', hardwareAuth: '보안키로 인증', passwordReauth: '비밀번호로 재인증',
  fallbackDisabled: '비밀번호 예외 경로는 운영 검증이 완료된 환경에서만 활성화됩니다.',
  recentRequests: '최근 요청', approve: '승인', reject: '거부', consume: '승인된 변경 적용',
  expiresAt: '만료', payloadHash: 'Payload hash', policyProposal: '보존정책 제안',
  completedDays: '완료 작업 온라인 보존일', chatDays: 'Chat 콘텐츠 보존일', auditMonths: '감사 온라인 보존개월',
  archiveYears: '불변 아카이브 보존년', propose: '정책 제안', policyHistory: '정책 이력',
  automationDisabled: '삭제 및 파티션 자동화는 준비 완료 전까지 비활성입니다.', holdPlacement: 'Legal Hold 배치',
  dataClass: '데이터 클래스', scope: '범위', scopeId: '범위 UUID', placeHold: 'Legal Hold 배치',
  holdHistory: 'Legal Hold 이력', requestRelease: '해제 요청', releaseDecision: '해제 판단',
  confirmTitle: '고위험 작업 확인', confirm: '확인 후 실행', cancel: '취소', working: '처리 중…',
  empty: '조회 가능한 항목이 없습니다.', noErasure: '이 화면은 삭제·파기 실행을 제공하지 않습니다.',
  versionConflict: '버전 충돌 시 새로고침 후 전체 내용을 다시 검토해야 합니다.',
  makerCannotCheck: 'Maker와 Checker는 달라야 합니다.', select: '선택',
  erasureRequest: '파기 검토 요청', erasureDecision: '파기 검토 판단', erasureHistory: '파기 검토 이력',
  erasureNonExecuting: '승인은 검토 증거일 뿐입니다. 실제 삭제·파기·자동 실행은 비활성입니다.',
  targetType: '대상 유형', targetId: '대상 UUID', targetVersion: '대상 버전',
  reviewTtlSeconds: '검토 유효시간(초)', requestReview: '검토 요청',
}

const en: AdminMessages = {
  eyebrow: 'Governed administration', title: 'Administration and retention governance', refresh: 'Refresh',
  memberships: 'Accounts & access', fallback: 'Maker-Checker', retention: 'Retention policies', holds: 'Legal Hold', erasure: 'Erasure review',
  adminContext: 'Current administrator context', currentAssurance: 'Authentication assurance',
  fallbackState: 'Password fallback', enabled: 'Enabled', disabled: 'Disabled', members: 'Workspace members',
  selectMember: 'Select a member to edit.', accessDocument: 'Complete access document', active: 'Membership active',
  clearance: 'Clearance', groups: 'Groups', allowedActions: 'Allowed actions', deniedActions: 'Denied actions',
  systemScopes: 'Allowed system UUIDs', domainScopes: 'Allowed domain UUIDs', directUpdate: 'Update with security key',
  fallbackRequest: 'Create password maker request', reason: 'Reason', hardwareAuth: 'Authenticate with security key',
  passwordReauth: 'Reauthenticate with password', fallbackDisabled: 'Password fallback is enabled only after operational verification.',
  recentRequests: 'Recent requests', approve: 'Approve', reject: 'Reject', consume: 'Apply approved change',
  expiresAt: 'Expires', payloadHash: 'Payload hash', policyProposal: 'Propose retention policy',
  completedDays: 'Completed operation online days', chatDays: 'Chat content days', auditMonths: 'Audit online months',
  archiveYears: 'Immutable archive years', propose: 'Propose policy', policyHistory: 'Policy history',
  automationDisabled: 'Deletion and partition automation remain disabled until all gates pass.',
  holdPlacement: 'Place Legal Hold', dataClass: 'Data class', scope: 'Scope', scopeId: 'Scope UUID',
  placeHold: 'Place Legal Hold', holdHistory: 'Legal Hold history', requestRelease: 'Request release',
  releaseDecision: 'Release decision', confirmTitle: 'Confirm high-risk operation', confirm: 'Review and execute',
  cancel: 'Cancel', working: 'Working…', empty: 'No authorized items are available.',
  noErasure: 'This screen does not provide deletion or erasure execution.',
  versionConflict: 'On a version conflict, refresh and review the complete document again.',
  makerCannotCheck: 'Maker and checker must be different.', select: 'Select',
  erasureRequest: 'Request erasure review', erasureDecision: 'Erasure review decision',
  erasureHistory: 'Erasure review history',
  erasureNonExecuting: 'Approval is review evidence only. Delete, erasure and automation remain disabled.',
  targetType: 'Target type', targetId: 'Target UUID', targetVersion: 'Target version',
  reviewTtlSeconds: 'Review lifetime (seconds)', requestReview: 'Request review',
}

export function getAdminMessages(locale = globalThis.navigator?.language ?? 'ko'): AdminMessages {
  return locale.toLowerCase().startsWith('ko') ? ko : en
}
