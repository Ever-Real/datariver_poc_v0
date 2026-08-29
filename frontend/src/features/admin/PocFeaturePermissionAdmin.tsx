import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import type { PocFeatureSecurityCell } from '../../api/types'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import type { AdminApi, VersionedPocFeatureSecurityPolicy } from './adminApi'
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

function cellKey(cell: PocFeatureSecurityCell) {
  return `${cell.feature}:${cell.role}:${cell.grade}`
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : '기능 권한 정책을 불러오지 못했습니다.'
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
  const [draft, setDraft] = useState<PocFeatureSecurityCell[]>([])
  const [reason, setReason] = useState('')
  const [query, setQuery] = useState('')
  const [roleFilter, setRoleFilter] = useState('ALL')
  const [gradeFilter, setGradeFilter] = useState('ALL')
  const [permissionFilter, setPermissionFilter] = useState('ALL')
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const loadGeneration = useRef(0)

  const load = useCallback(async (signal?: AbortSignal) => {
    const generation = ++loadGeneration.current
    setLoading(true)
    setLoadError('')
    try {
      const nextPolicy = await api.getFeatureSecurityPolicy(signal)
      if (generation !== loadGeneration.current) return
      setPolicy(nextPolicy)
      setDraft(nextPolicy.cells)
    } catch (error) {
      if (signal?.aborted || generation !== loadGeneration.current) return
      setLoadError(errorMessage(error))
      reportError(error)
    } finally {
      if (generation === loadGeneration.current) setLoading(false)
    }
  }, [api, reportError])

  useEffect(() => {
    const controller = new AbortController()
    void load(controller.signal)
    return () => controller.abort()
  }, [load])

  const hasChanges = useMemo(() => {
    if (!policy) return false
    return JSON.stringify(policy.cells) !== JSON.stringify(draft)
  }, [policy, draft])

  const handleToggle = useCallback((cell: PocFeatureSecurityCell, allow: boolean) => {
    if (cell.role === 'admin' || !featureAvailableForRole(cell.feature, cell.role)) return
    const key = cellKey(cell)
    setDraft((current) => current.map((candidate) => (
      cellKey(candidate) === key ? { ...candidate, allow } : candidate
    )))
  }, [])

  const handleSave = (event: React.FormEvent) => {
    event.preventDefault()
    const normalizedReason = reason.trim()
    if (!policy || normalizedReason.length < 10) return
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

  const canonicalRoles = useMemo(() => Array.from(new Set(draft.map((cell) => cell.role))), [draft])
  const canonicalGrades = useMemo(() => Array.from(new Set(draft.map((cell) => cell.grade))), [draft])
  const normalizedQuery = query.trim().toLocaleLowerCase()
  const visibleCells = useMemo(() => draft.filter((cell) => {
    if (roleFilter !== 'ALL' && cell.role !== roleFilter) return false
    if (gradeFilter !== 'ALL' && cell.grade !== gradeFilter) return false
    if (permissionFilter === 'ALLOW' && !cell.allow) return false
    if (permissionFilter === 'DENY' && cell.allow) return false
    if (!normalizedQuery) return true
    const feature = POC_FEATURES[cell.feature] ?? { area: cell.feature, feature: cell.feature }
    const searchable = [
      cell.feature, feature.area, feature.feature,
      cell.role, POC_ROLES[cell.role] ?? cell.role,
      cell.grade, SECURITY_GRADES[cell.grade] ?? cell.grade,
      cell.allow ? '허용 allow' : '차단 deny',
    ].join(' ').toLocaleLowerCase()
    return searchable.includes(normalizedQuery)
  }), [draft, gradeFilter, normalizedQuery, permissionFilter, roleFilter])

  const columns = useMemo<ColumnDef<PocFeatureSecurityCell>[]>(() => [
    {
      id: 'area',
      accessorFn: (cell) => POC_FEATURES[cell.feature]?.area ?? cell.feature,
      header: '분야',
      size: 120,
      cell: ({ getValue }) => <strong>{String(getValue())}</strong>,
    },
    {
      id: 'feature',
      accessorFn: (cell) => cell.feature,
      header: '기능 / 모듈',
      size: 280,
      cell: ({ row }) => {
        const feature = POC_FEATURES[row.original.feature]
        return <span className="admin-feature-cell"><strong>{row.original.feature}</strong><span>{feature?.feature ?? row.original.feature}</span></span>
      },
    },
    {
      id: 'role',
      accessorFn: (cell) => cell.role,
      header: '역할',
      size: 150,
      cell: ({ row }) => <span className="admin-feature-cell"><strong>{POC_ROLES[row.original.role] ?? row.original.role}</strong><span>{row.original.role}</span></span>,
    },
    {
      id: 'grade',
      accessorFn: (cell) => cell.grade,
      header: '보안 등급',
      size: 120,
      cell: ({ row }) => <span>{SECURITY_GRADES[row.original.grade] ?? row.original.grade} <small>({row.original.grade})</small></span>,
    },
    {
      id: 'allow',
      accessorFn: (cell) => cell.allow,
      header: '권한 / 유효 상태',
      size: 190,
      cell: ({ row }) => {
        const cell = row.original
        const feature = POC_FEATURES[cell.feature] ?? { area: cell.feature, feature: cell.feature }
        const adminLocked = cell.role === 'admin'
        const unavailable = !featureAvailableForRole(cell.feature, cell.role)
        const checked = adminLocked ? true : cell.allow
        const disabled = adminLocked || unavailable
        const lockReason = adminLocked ? 'Admin 고정' : unavailable ? '기능 역할 제한' : '편집 가능'
        return <label className="admin-feature-permission-toggle">
          <input
            type="checkbox"
            checked={checked}
            disabled={disabled}
            onChange={(event) => handleToggle(cell, event.target.checked)}
            aria-label={`${feature.area} ${feature.feature} - ${SECURITY_GRADES[cell.grade] ?? cell.grade} - ${POC_ROLES[cell.role] ?? cell.role}`}
          />
          <span>{checked ? '허용' : '차단'} · {lockReason}</span>
        </label>
      },
    },
    {
      id: 'policyVersion',
      accessorFn: () => policy?.version ?? -1,
      header: '소스 정책',
      size: 130,
      cell: () => policy ? `v${policy.version} / schema v${policy.schema_version}` : '—',
    },
  ], [handleToggle, policy])

  const filtersActive = Boolean(normalizedQuery) || roleFilter !== 'ALL' || gradeFilter !== 'ALL' || permissionFilter !== 'ALL'

  return <section className="panel admin-feature-permissions" aria-label="기능 권한 정책">
    <div className="section-heading">
      <div>
        <span className="eyebrow">POC Feature Security Policy</span>
        <h3>기능 권한 정책{policy ? ` (v${policy.version})` : ''}</h3>
        <p className="muted">
          자산 등급별 POC 접속 역할을 허용합니다. (Admin은 전역으로 강제 허용됩니다.)
          {policy?.updated_at && ` (최근 업데이트: ${policy.updated_at} / ${policy.updated_by} - ${policy.reason})`}
        </p>
      </div>
      <button type="button" className="button button-secondary" disabled={loading} onClick={() => void load()}>새로고침</button>
    </div>

    {loadError && <div className="notice notice-error" role="alert">
      <span>{loadError}</span>
      <button type="button" className="button button-secondary button-compact" onClick={() => void load()}>다시 시도</button>
    </div>}

    <div className="admin-feature-filters" role="search" aria-label="기능 권한 필터">
      <label>검색<input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="기능, 역할, 등급" /></label>
      <label>역할<select value={roleFilter} onChange={(event) => setRoleFilter(event.target.value)}><option value="ALL">전체</option>{canonicalRoles.map((role) => <option value={role} key={role}>{POC_ROLES[role] ?? role}</option>)}</select></label>
      <label>보안 등급<select value={gradeFilter} onChange={(event) => setGradeFilter(event.target.value)}><option value="ALL">전체</option>{canonicalGrades.map((grade) => <option value={grade} key={grade}>{SECURITY_GRADES[grade] ?? grade}</option>)}</select></label>
      <label>권한 상태<select value={permissionFilter} onChange={(event) => setPermissionFilter(event.target.value)}><option value="ALL">전체</option><option value="ALLOW">허용</option><option value="DENY">차단</option></select></label>
      <button type="button" className="button button-secondary" disabled={!filtersActive} onClick={() => { setQuery(''); setRoleFilter('ALL'); setGradeFilter('ALL'); setPermissionFilter('ALL') }}>필터 초기화</button>
    </div>

    <p className="admin-feature-result-count" role="status">전체 {draft.length}개 중 {visibleCells.length}개 cell</p>
    <DenseDataTable
      caption="기능 권한 정책 cell"
      columns={columns}
      data={visibleCells}
      getRowId={cellKey}
      loading={loading}
      emptyMessage={draft.length === 0 ? '서버가 반환한 정책 cell이 없습니다.' : '필터 조건에 맞는 정책 cell이 없습니다.'}
    />

    {hasChanges && policy && <form onSubmit={handleSave} className="form-layout mt-4">
      <div className="field-group">
        <label htmlFor="feature-policy-reason">변경 사유</label>
        <input
          id="feature-policy-reason"
          type="text"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
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
