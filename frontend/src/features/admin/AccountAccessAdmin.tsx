import { useMemo, useState } from 'react'
import { Dialog } from '../../components/common/Dialog'
import { useRovingTabs } from '../../components/common/useRovingTabs'
import {
  ClassificationPolicyAdmin,
  InferenceProviderProfileAdmin,
  RestrictedSearchGrantAdmin,
} from './ClassificationAccessAdmin'
import {
  FallbackQueueAdmin,
  MembershipAccessAdmin,
  MembershipRenewalAdmin,
  type AdminSectionProps,
} from './MembershipAdmin'
import { RoleManagementDialog } from './RoleAccessAdmin'
import { SystemDirectoryAdmin } from './SystemDirectoryAdmin'

type AccessView = 'users' | 'systems' | 'policies' | 'recovery'
type PolicyView = 'classification' | 'restrictedGrants' | 'providers'

function initialAccessView(): AccessView {
  const requested = new URL(window.location.href).searchParams.get('adminView')
  if (requested === 'systems') return 'systems'
  if (requested === 'policies') return 'policies'
  if (requested === 'recovery') return 'recovery'
  return 'users'
}

function initialPolicyView(): PolicyView {
  const requested = new URL(window.location.href).searchParams.get('adminDetail')
  if (requested === 'providers') return 'providers'
  if (requested === 'restrictedGrants') return 'restrictedGrants'
  return 'classification'
}

function updateLocation(view: AccessView, detail?: PolicyView) {
  const url = new URL(window.location.href)
  url.searchParams.set('page', 'admin')
  url.searchParams.set('adminSection', 'memberships')
  url.searchParams.set('adminView', view)
  if (detail) url.searchParams.set('adminDetail', detail)
  else url.searchParams.delete('adminDetail')
  window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
}

export function AccountAccessAdmin(props: AdminSectionProps) {
  const { context, messages } = props
  const operations = useMemo(() => new Set(context?.allowed_operations ?? []), [context])
  const canReadMemberships = operations.has('MEMBERSHIP_ACCESS_READ')
  const canReadRenewals = operations.has('MEMBERSHIP_RENEWAL_READ')
  const [roleManagementOpen, setRoleManagementOpen] = useState(false)
  const [renewalsOpen, setRenewalsOpen] = useState(false)
  const views = useMemo(() => {
    const next: Array<{ id: AccessView; label: string; description: string }> = []
    if (canReadMemberships || canReadRenewals) {
      next.push({ id: 'users', label: 'USERS', description: '사용자와 Role을 한 곳에서 관리' })
    }
    if (canReadMemberships) {
      next.push({ id: 'systems', label: 'SYSTEMS', description: '시스템 담당자와 우선순위' })
    }
    if ([
      'CLASSIFICATION_POLICY_READ', 'INFERENCE_PROVIDER_PROFILE_READ', 'RESTRICTED_SEARCH_GRANT_READ',
    ].some((operation) => operations.has(operation as never))) {
      next.push({ id: 'policies', label: '보안정책', description: '분류·예외·AI Provider 승인' })
    }
    if (operations.has('FALLBACK_REQUEST_READ')) {
      next.push({ id: 'recovery', label: '예외 승인', description: '비밀번호 Maker-Checker 복구 경로' })
    }
    return next
  }, [canReadMemberships, canReadRenewals, operations])
  const [requestedView, setRequestedView] = useState<AccessView>(initialAccessView)
  const [policyView, setPolicyView] = useState<PolicyView>(initialPolicyView)
  const view = views.some((item) => item.id === requestedView) ? requestedView : views[0]?.id
  const policyViews = [
    operations.has('CLASSIFICATION_POLICY_READ') && { id: 'classification' as const, label: messages.classification },
    operations.has('RESTRICTED_SEARCH_GRANT_READ') && { id: 'restrictedGrants' as const, label: messages.restrictedGrants },
    operations.has('INFERENCE_PROVIDER_PROFILE_READ') && { id: 'providers' as const, label: messages.providers },
  ].filter((item): item is { id: PolicyView; label: string } => Boolean(item))
  const activePolicyView = policyViews.some((item) => item.id === policyView)
    ? policyView
    : policyViews[0]?.id
  const selectView = (next: AccessView) => {
    setRequestedView(next)
    updateLocation(next, next === 'policies' ? activePolicyView : undefined)
  }
  const selectPolicyView = (next: PolicyView) => {
    setPolicyView(next)
    updateLocation('policies', next)
  }
  const accessTabs = useRovingTabs({
    ids: views.map((item) => item.id), activeId: view, idPrefix: 'admin-access', onSelect: selectView,
  })
  const policyTabs = useRovingTabs({
    ids: policyViews.map((item) => item.id), activeId: activePolicyView,
    idPrefix: 'admin-policies', onSelect: selectPolicyView,
  })

  return <div className="grid gap-2">
    <section aria-label="계정/권한 요약" className="panel admin-access-summary border-l-4 border-l-blue-700 bg-slate-50">
      <span className="eyebrow">Accounts &amp; authorization</span>
      <h2 className="mb-1 mt-1 text-base text-navy-900">계정/권한</h2>
      <p className="m-0 text-xs leading-5 text-slate-600">사용자 계정과 Role은 서버가 검증한 Workspace 범위에서만 관리합니다.</p>
    </section>
    <div className="admin-access-tabs flex flex-wrap gap-1 border-b border-slate-300" role="tablist" aria-label="계정/권한 관리 영역">
      {views.map((item) => <button key={item.id} {...accessTabs.tabProps(item.id)} type="button" aria-label={item.label} className={`min-w-36 border border-b-0 px-3 py-1.5 text-left text-[11px] font-black ${view === item.id ? 'border-navy-900 bg-navy-900 text-white' : 'border-slate-300 bg-slate-100 text-slate-600'}`} onClick={() => selectView(item.id)}><span className="block">{item.label}</span><small className="block text-[8px] font-bold leading-3 opacity-75">{item.description}</small></button>)}
    </div>
    {view === 'users' && <section {...accessTabs.panelProps('users')} aria-label="사용자 관리">
      {canReadMemberships && <MembershipAccessAdmin {...props} onOpenRoleManagement={() => setRoleManagementOpen(true)} onOpenRenewals={canReadRenewals ? () => setRenewalsOpen(true) : undefined} />}
      {!canReadMemberships && canReadRenewals && <button type="button" className="button" onClick={() => setRenewalsOpen(true)}>계정 갱신</button>}
    </section>}
    {view === 'systems' && <section {...accessTabs.panelProps('systems')}><SystemDirectoryAdmin {...props} /></section>}
    {view === 'policies' && <section {...accessTabs.panelProps('policies')} className="grid gap-3">
      <p className="callout m-0">분류정책은 기본 접근 경계를, RESTRICTED 예외 승인은 Search에만 적용되는 기간 제한 승인을 관리합니다. AI Provider 승인은 접속정보가 아니라 운영 적격성 증거와 철회 이력이며 시스템 설정과 분리됩니다.</p>
      <div className="flex flex-wrap gap-1" role="tablist" aria-label="보안정책 종류">
        {policyViews.map((item) => <button key={item.id} {...policyTabs.tabProps(item.id)} type="button" className={`button ${activePolicyView === item.id ? '' : 'button-secondary'}`} onClick={() => selectPolicyView(item.id)}>{item.label}</button>)}
      </div>
      {activePolicyView === 'classification' && <div {...policyTabs.panelProps('classification')}><ClassificationPolicyAdmin {...props} /></div>}
      {activePolicyView === 'restrictedGrants' && <div {...policyTabs.panelProps('restrictedGrants')}><RestrictedSearchGrantAdmin {...props} /></div>}
      {activePolicyView === 'providers' && <div {...policyTabs.panelProps('providers')}><InferenceProviderProfileAdmin {...props} /></div>}
    </section>}
    {view === 'recovery' && <section {...accessTabs.panelProps('recovery')} className="grid gap-3"><FallbackQueueAdmin {...props} /></section>}
    <RoleManagementDialog open={roleManagementOpen} onRequestClose={() => setRoleManagementOpen(false)} {...props} />
    <Dialog open={renewalsOpen} size="large" title="계정 갱신" description="서버가 계산한 계정 갱신 요청을 검토합니다." onRequestClose={() => setRenewalsOpen(false)} footer={<button type="button" className="button button-secondary" onClick={() => setRenewalsOpen(false)}>닫기</button>}>
      {canReadRenewals && <MembershipRenewalAdmin {...props} />}
    </Dialog>
  </div>
}
