import { remediationKind } from '../api/client'

export interface AssuranceActions {
  onStepUp: () => Promise<void>
  onPasswordReauth: () => Promise<void>
  onEnroll: () => Promise<void>
}

export type RequiredAssurance = 'HARDWARE' | 'PASSWORD'

export function AssuranceNotice({
  error,
  onStepUp,
  onPasswordReauth,
  onEnroll,
  requiredAssurance = 'HARDWARE',
}: { error?: unknown; requiredAssurance?: RequiredAssurance } & AssuranceActions) {
  const remediation = remediationKind(error)
  if (!remediation) return null

  if (remediation === 'FALLBACK_UNAVAILABLE') {
    return (
      <div className="notice notice-error" role="alert">
        <strong>관리자 비밀번호 예외 경로를 사용할 수 없습니다.</strong>
        <span>이 작업은 조직 인증 정책이 허용한 WebAuthn 보안키로 인증해야 합니다. 특정 USB 장치만을 전제로 하지 않으며, 비밀번호 예외 경로는 두 명의 적격 관리자와 Maker-Checker 절차가 운영 검증된 환경에서만 별도로 제공됩니다.</span>
        <div className="action-row">
          <button className="button" onClick={() => void onStepUp()}>보안키로 인증</button>
        </div>
      </div>
    )
  }

  const passwordReauth = remediation === 'REAUTH_REQUIRED' && requiredAssurance === 'PASSWORD'

  return (
    <div className="notice notice-error" role="alert">
      <strong>{remediation === 'FIDO2_REQUIRED'
        ? 'WebAuthn 보안키 인증이 필요합니다.'
        : passwordReauth
          ? '비밀번호 재인증이 필요합니다.'
          : '보안키 재인증이 필요합니다.'}</strong>
      <span>인증 후 작업은 자동 실행되지 않습니다. 돌아온 화면에서 대상과 내용을 다시 확인하세요.</span>
      <div className="action-row">
        <button
          className="button"
          onClick={() => void (passwordReauth ? onPasswordReauth() : onStepUp())}
        >
          {passwordReauth ? '비밀번호로 재인증' : '보안키로 인증'}
        </button>
        {remediation === 'FIDO2_REQUIRED' && (
          <button className="button button-secondary" onClick={() => void onEnroll()}>
            보안키 등록
          </button>
        )}
      </div>
    </div>
  )
}
