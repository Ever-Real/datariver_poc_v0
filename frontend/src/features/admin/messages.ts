export type AdminMessageKey =
  | 'eyebrow' | 'title' | 'refresh' | 'memberships' | 'systems' | 'systemSettings' | 'roles' | 'fallback' | 'retention' | 'holds' | 'erasure'
  | 'classification' | 'providers' | 'restrictedGrants'
  | 'auditLogs' | 'metadataLogs' | 'securityLogs' | 'dictionary'
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
  | 'classificationPolicyProposal' | 'classificationPolicyHistory' | 'currentPolicy'
  | 'jurisdiction' | 'grantMaximumDays' | 'classificationMatrix' | 'searchMode' | 'chatMode'
  | 'providerProfile' | 'chooseProvider' | 'noEligibleProvider' | 'providerHistory'
  | 'providerReadOnly' | 'providerDecision' | 'revoke' | 'revocationReason'
  | 'residencyAttestation' | 'zeroRetentionAttestation' | 'restrictedGrantProposal'
  | 'restrictedGrantHistory' | 'subject' | 'purpose' | 'validFrom' | 'activePolicyRequired'
  | 'restrictedGrantDisabled' | 'browserTimezone' | 'grantMaximumHint'

export type AdminMessages = Record<AdminMessageKey, string>

const ko: AdminMessages = {
  eyebrow: 'Governed administration', title: '관리자 및 데이터 거버넌스', refresh: '새로고침',
  memberships: '계정/권한', systems: 'SYSTEMS · 시스템', systemSettings: '시스템 설정', roles: '간편 Role', fallback: '비밀번호 예외 승인', retention: '보존·파기 거버넌스', holds: 'Legal Hold', erasure: '파기 검토',
  classification: '데이터 분류 접근', providers: 'AI Provider 승인', restrictedGrants: 'RESTRICTED 예외 승인',
  auditLogs: 'Audit/Log 조회', metadataLogs: '메타데이터 변경 로그', securityLogs: '시스템 보안 로그', dictionary: '용어사전',
  adminContext: '현재 관리자 컨텍스트', currentAssurance: '인증 보증', fallbackState: '비밀번호 예외 경로',
  enabled: '활성', disabled: '비활성', members: '워크스페이스 멤버', selectMember: '편집할 멤버를 선택하세요.',
  accessDocument: '세부 Access 문서 (고급)', active: '멤버십 활성', clearance: '허용 등급', groups: '그룹',
  allowedActions: '허용 Action', deniedActions: '거부 Action', systemScopes: '허용 System UUID',
  domainScopes: '허용 Domain UUID', directUpdate: '보안키로 직접 변경', fallbackRequest: '비밀번호 Maker 요청',
  reason: '사유', hardwareAuth: '보안키로 인증', passwordReauth: '비밀번호로 재인증',
  fallbackDisabled: '비밀번호 예외 경로는 운영 검증이 완료된 환경에서만 활성화됩니다.',
  recentRequests: '최근 요청', approve: '승인', reject: '거부', consume: '승인된 변경 적용',
  expiresAt: '만료', payloadHash: '데이터 이벤트 해시', policyProposal: '보존정책 제안',
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
  classificationPolicyProposal: '분류 접근정책 제안', classificationPolicyHistory: '분류 접근정책 이력',
  currentPolicy: '현재 적용 정책', jurisdiction: '승인 관할', grantMaximumDays: 'RESTRICTED Grant 최대 일수',
  classificationMatrix: '고정 분류등급 정책', searchMode: 'Search 모드', chatMode: 'Chat 모드',
  providerProfile: '승인 Provider profile', chooseProvider: 'Provider profile을 선택하세요',
  noEligibleProvider: '현재 정책 조건에 적격한 승인 Provider profile이 없습니다.',
  providerHistory: 'Provider profile 이력',
  providerReadOnly: 'Provider endpoint와 secret은 이 화면에서 등록하거나 변경할 수 없습니다.',
  providerDecision: 'Provider profile 판단', revoke: '즉시 철회', revocationReason: '철회 사유',
  residencyAttestation: 'Residency attestation', zeroRetentionAttestation: 'Zero-retention attestation',
  restrictedGrantProposal: 'RESTRICTED Search grant 제안', restrictedGrantHistory: 'RESTRICTED Search grant 이력',
  subject: '대상 사용자', purpose: '접근 목적', validFrom: '유효 시작',
  activePolicyRequired: '활성 분류 접근정책이 있어야 grant를 제안할 수 있습니다.',
  restrictedGrantDisabled: '현재 정책은 RESTRICTED Search explicit grant를 허용하지 않습니다.',
  browserTimezone: '브라우저 시간대', grantMaximumHint: '현재 활성 정책의 최대 허용 기간',
}

const en: AdminMessages = {
  eyebrow: 'Governed administration', title: 'Administration and data governance', refresh: 'Refresh',
  memberships: 'Accounts & access', systems: 'Systems', systemSettings: 'System settings', roles: 'Quick roles', fallback: 'Password exception approvals', retention: 'Retention & erasure governance', holds: 'Legal Hold', erasure: 'Erasure review',
  classification: 'Data classification access', providers: 'AI provider approvals', restrictedGrants: 'RESTRICTED exception approvals',
  auditLogs: 'Audit/Log review', metadataLogs: 'Metadata change log', securityLogs: 'System security log', dictionary: 'Terminology dictionary',
  adminContext: 'Current administrator context', currentAssurance: 'Authentication assurance',
  fallbackState: 'Password fallback', enabled: 'Enabled', disabled: 'Disabled', members: 'Workspace members',
  selectMember: 'Select a member to edit.', accessDocument: 'Detailed access document (advanced)', active: 'Membership active',
  clearance: 'Clearance', groups: 'Groups', allowedActions: 'Allowed actions', deniedActions: 'Denied actions',
  systemScopes: 'Allowed system UUIDs', domainScopes: 'Allowed domain UUIDs', directUpdate: 'Update with security key',
  fallbackRequest: 'Create password maker request', reason: 'Reason', hardwareAuth: 'Authenticate with security key',
  passwordReauth: 'Reauthenticate with password', fallbackDisabled: 'Password fallback is enabled only after operational verification.',
  recentRequests: 'Recent requests', approve: 'Approve', reject: 'Reject', consume: 'Apply approved change',
  expiresAt: 'Expires', payloadHash: 'Data Event Hash', policyProposal: 'Propose retention policy',
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
  classificationPolicyProposal: 'Propose classification access policy',
  classificationPolicyHistory: 'Classification access policy history', currentPolicy: 'Current policy',
  jurisdiction: 'Approved jurisdiction', grantMaximumDays: 'Maximum RESTRICTED grant days',
  classificationMatrix: 'Fixed classification policy', searchMode: 'Search mode', chatMode: 'Chat mode',
  providerProfile: 'Approved provider profile', chooseProvider: 'Select a provider profile',
  noEligibleProvider: 'No approved provider profile is eligible for the current policy conditions.',
  providerHistory: 'Provider profile history',
  providerReadOnly: 'Provider endpoints and secrets cannot be registered or changed on this screen.',
  providerDecision: 'Provider profile decision', revoke: 'Revoke immediately',
  revocationReason: 'Revocation reason', residencyAttestation: 'Residency attestation',
  zeroRetentionAttestation: 'Zero-retention attestation',
  restrictedGrantProposal: 'Propose RESTRICTED Search grant',
  restrictedGrantHistory: 'RESTRICTED Search grant history', subject: 'Subject', purpose: 'Purpose',
  validFrom: 'Valid from', activePolicyRequired: 'An active classification policy is required.',
  restrictedGrantDisabled: 'The current policy does not permit explicit RESTRICTED Search grants.',
  browserTimezone: 'Browser time zone', grantMaximumHint: 'Maximum allowed by the active policy',
}

export function getAdminMessages(locale = globalThis.navigator?.language ?? 'ko'): AdminMessages {
  return locale.toLowerCase().startsWith('ko') ? ko : en
}
