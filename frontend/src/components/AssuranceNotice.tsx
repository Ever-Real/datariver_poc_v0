import { remediationKind } from '../api/client'

export interface AssuranceActions {
  onStepUp: () => Promise<void>
  onEnroll: () => Promise<void>
}

export function AssuranceNotice({
  error,
  onStepUp,
  onEnroll,
}: { error?: unknown } & AssuranceActions) {
  const remediation = remediationKind(error)
  if (!remediation) return null

  if (remediation === 'FALLBACK_UNAVAILABLE') {
    return (
      <div className="notice notice-error" role="alert">
        <strong>관리자 비밀번호 예외를 사용할 수 없습니다.</strong>
        <span>Maker-Checker 승인 절차가 제공되기 전에는 USB 보안키로만 이 작업을 수행할 수 있습니다.</span>
      </div>
    )
  }

  return (
    <div className="notice notice-error" role="alert">
      <strong>{remediation === 'FIDO2_REQUIRED' ? 'USB 보안키 인증이 필요합니다.' : '보안키 재인증이 필요합니다.'}</strong>
      <span>인증 후 작업은 자동 실행되지 않습니다. 돌아온 화면에서 대상과 내용을 다시 확인하세요.</span>
      <div className="action-row">
        <button className="button" onClick={() => void onStepUp()}>보안키로 인증</button>
        {remediation === 'FIDO2_REQUIRED' && (
          <button className="button button-secondary" onClick={() => void onEnroll()}>
            보안키 등록
          </button>
        )}
      </div>
    </div>
  )
}
