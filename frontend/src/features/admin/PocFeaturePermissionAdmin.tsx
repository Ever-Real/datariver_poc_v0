import { useCallback, useEffect, useState, useMemo } from 'react'
import type { AdminApi, VersionedPocFeatureSecurityPolicy } from './adminApi'
import type { PocFeatureSecurityCell } from '../../api/types'
import type { PendingAdminMutation } from './AdminMutationConfirmDialog'

export const POC_FEATURES: Record<string, { area: string; feature: string }> = {
  catalog: { area: '검색', feature: '검색·상세·계보·Resource Tree' },
  registration: { area: '등록관리', feature: '수동 등록·메타데이터 변경 요청' },
  change: { area: '변경관리', feature: 'CR 등록·검토·보완요청·수정 재요청·테스트·결재' },
  quality: { area: '품질관리', feature: '현황·이력·규칙·실행' },
  knowledge: { area: '지식관리', feature: 'Registry·Studio·정보관리·Release' },
  governance: { area: '거버넌스', feature: '문서·Template·검토·발행·Archive' },
  chat: { area: 'Chat', feature: '자동·일반·벡터·그래프 라우팅' },
  monitoring: { area: '모니터링', feature: 'Dashboard 링크·iframe' },
}

export const POC_ROLES: Record<string, string> = {
  viewer: 'Viewer',
  developer: 'Developer',
  data_steward: 'Data Steward',
  manager: 'Manager',
  admin: 'Admin',
}

export const SECURITY_GRADES: Record<string, string> = {
  normal: '일반',
  credential: '대외비',
  restricted: '극비',
}

const GOVERNED_ROLES = new Set(['data_steward', 'manager', 'admin'])

// Display-only mirror of the fixed backend vocabulary. The server validates
// every submitted cell and remains the authorization authority.
function featureAvailableForRole(feature: string, role: string) {
  if (role === 'admin') return true
  if (feature === 'registration') return role === 'data_steward'
  if (['knowledge', 'quality'].includes(feature)) return GOVERNED_ROLES.has(role)
  return true
}

export interface PocFeaturePermissionAdminProps {
  api: AdminApi
  requestConfirmation: (pending: PendingAdminMutation) => void
  reportError: (error: unknown) => void
  keyFor: (intent: string, prefix: string) => string
  clearKey: (intent: string) => void
}

export function PocFeaturePermissionAdmin({
  api, requestConfirmation, reportError, keyFor, clearKey
}: PocFeaturePermissionAdminProps) {
  const [policy, setPolicy] = useState<VersionedPocFeatureSecurityPolicy>()
  const [draft, setDraft] = useState<PocFeatureSecurityCell[]>()
  const [reason, setReason] = useState('')

  const load = useCallback(async () => {
    try {
      const p = await api.getFeatureSecurityPolicy()
      setPolicy(p)
      setDraft(p.cells)
    } catch (err) {
      reportError(err)
    }
  }, [api, reportError])

  useEffect(() => { void load() }, [load])

  const hasChanges = useMemo(() => {
    if (!policy || !draft) return false
    return JSON.stringify(policy.cells) !== JSON.stringify(draft)
  }, [policy, draft])

  const handleToggle = (f: string, r: string, g: string, val: boolean) => {
    if (!draft) return
    if (r === 'admin' || !featureAvailableForRole(f, r)) return

    setDraft(draft.map(c =>
      c.feature === f && c.role === r && c.grade === g ? { ...c, allow: val } : c
    ))
  }

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault()
    const normalizedReason = reason.trim()
    if (!policy || !draft || normalizedReason.length < 10) return
    const idempotencyKey = keyFor('save-feature-policy', 'fp-')
    requestConfirmation({
      title: '기능 권한 정책 저장',
      summary: [
        `고정 정책 cell ${draft.length}개`,
        `변경 사유: ${normalizedReason}`,
      ],
      execute: async () => {
        await api.updateFeatureSecurityPolicy(
          { cells: draft, reason: normalizedReason },
          policy.etag,
          idempotencyKey,
        )
        clearKey('save-feature-policy')
        setReason('')
        await load()
      },
    })
  }

  if (!policy || !draft) return null

  // Extract unique elements in their canonical order from the backend response
  const canonicalFeatures = Array.from(new Set(draft.map(c => c.feature)))
  const canonicalGrades = Array.from(new Set(draft.map(c => c.grade)))
  const canonicalRoles = Array.from(new Set(draft.map(c => c.role)))

  return <section className="panel admin-feature-permissions" aria-label="기능 권한 정책">
    <div className="section-heading">
      <div>
        <span className="eyebrow">POC Feature Security Policy</span>
        <h3>기능 권한 정책 (v{policy.version})</h3>
        <p className="muted">
          자산 등급별 POC 접속 역할을 허용합니다. (Admin은 전역으로 강제 허용됩니다.)
          {policy.updated_at && ` (최근 업데이트: ${policy.updated_at} / ${policy.updated_by} - ${policy.reason})`}
        </p>
      </div>
    </div>

    <div className="table-responsive">
      <table className="data-table">
        <thead>
          <tr>
            <th>분야</th>
            <th>기능</th>
            <th>등급</th>
            {canonicalRoles.map(r => <th key={r}>{POC_ROLES[r] ?? r}</th>)}
          </tr>
        </thead>
        <tbody>
          {canonicalFeatures.map((feature) => {
            const fVal = POC_FEATURES[feature] ?? { area: feature, feature: feature }
            return canonicalGrades.map((grade, gIdx) => {
              const gVal = SECURITY_GRADES[grade] ?? grade
              return (
                <tr key={`${feature}-${grade}`}>
                  {gIdx === 0 && <td rowSpan={canonicalGrades.length}><strong>{fVal.area}</strong></td>}
                  {gIdx === 0 && <td rowSpan={canonicalGrades.length}><small>{fVal.feature}</small></td>}
                  <td>{gVal}</td>
                  {canonicalRoles.map(role => {
                    const cell = draft.find(c => c.feature === feature && c.role === role && c.grade === grade)
                    const checked = role === 'admin' ? true : (cell?.allow ?? false)
                    const disabled = role === 'admin' || !featureAvailableForRole(feature, role)
                    return (
                      <td key={role} className="align-center">
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={disabled}
                          onChange={(e) => handleToggle(feature, role, grade, e.target.checked)}
                          aria-label={`${fVal.area} ${fVal.feature} - ${gVal} - ${POC_ROLES[role] ?? role}`}
                        />
                      </td>
                    )
                  })}
                </tr>
              )
            })
          })}
        </tbody>
      </table>
    </div>

    {hasChanges && <form onSubmit={handleSave} className="form-layout mt-4">
      <div className="field-group">
        <label htmlFor="feature-policy-reason">변경 사유</label>
        <input
          id="feature-policy-reason"
          type="text"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          required
          minLength={10}
          maxLength={1000}
          placeholder="정책 변경 사유를 입력하세요"
          className="input"
        />
      </div>
      <div className="action-row">
        <button type="button" className="button button-secondary" onClick={() => { setDraft(policy.cells); setReason('') }}>취소</button>
        <button type="submit" className="button button-primary" disabled={reason.trim().length < 10}>저장</button>
      </div>
    </form>}
  </section>
}
