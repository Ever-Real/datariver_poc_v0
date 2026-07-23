import { useMemo, useState } from 'react'
import { useRovingTabs } from '../../components/common/useRovingTabs'
import {
  ClassificationPolicyAdmin,
  InferenceProviderProfileAdmin,
  RestrictedSearchGrantAdmin,
} from './ClassificationAccessAdmin'
import { FallbackQueueAdmin, MembershipAccessAdmin, MembershipRenewalAdmin, type AdminSectionProps } from './MembershipAdmin'
import { RoleAccessAdmin } from './RoleAccessAdmin'
import { SystemDirectoryAdmin } from './SystemDirectoryAdmin'

type AccessView = 'users' | 'systems' | 'policies' | 'recovery'
type UserView = 'directory' | 'roles' | 'renewals'
type PolicyView = 'classification' | 'restrictedGrants' | 'providers'

function initialAccessView(): AccessView {
  const parameters = new URL(window.location.href).searchParams
  const requested = parameters.get('adminView') ?? parameters.get('adminSection')
  if (requested === 'systems') return 'systems'
  if (['classification', 'providers', 'restrictedGrants', 'policies'].includes(requested ?? '')) return 'policies'
  if (requested === 'fallback' || requested === 'recovery') return 'recovery'
  return 'users'
}

function initialUserView(): UserView {
  const parameters = new URL(window.location.href).searchParams
  if (parameters.get('adminDetail') === 'roles' || parameters.get('adminSection') === 'roles') return 'roles'
  if (parameters.get('adminDetail') === 'renewals') return 'renewals'
  return 'directory'
}

function initialPolicyView(): PolicyView {
  const parameters = new URL(window.location.href).searchParams
  const requested = parameters.get('adminDetail') ?? parameters.get('adminSection')
  if (requested === 'providers') return 'providers'
  if (requested === 'restrictedGrants') return 'restrictedGrants'
  return 'classification'
}

function updateLocation(view: AccessView, detail?: UserView | PolicyView) {
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
  const views = useMemo(() => {
    const next: Array<{ id: AccessView; label: string; description: string }> = []
    if (operations.has('MEMBERSHIP_ACCESS_READ')) {
      next.push(
        { id: 'users', label: 'USERS', description: '사용자 멤버십과 Role' },
        { id: 'systems', label: 'SYSTEMS', description: '시스템 담당자와 우선순위' },
      )
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
  }, [operations])
  const [requestedView, setRequestedView] = useState<AccessView>(initialAccessView)
  const [userView, setUserView] = useState<UserView>(initialUserView)
  const [policyView, setPolicyView] = useState<PolicyView>(initialPolicyView)
  const view = views.some((item) => item.id === requestedView) ? requestedView : views[0]?.id
  const userViews = [
    { id: 'directory' as const, label: '사용자' },
    { id: 'roles' as const, label: 'Role 정의·할당' },
    operations.has('MEMBERSHIP_RENEWAL_READ')
      && { id: 'renewals' as const, label: '계정 갱신 승인' },
  ].filter((item): item is { id: UserView; label: string } => Boolean(item))
  const activeUserView = userViews.some((item) => item.id === userView)
    ? userView
    : userViews[0]?.id
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
    updateLocation(next, next === 'users' ? activeUserView : next === 'policies' ? activePolicyView : undefined)
  }
  const selectUserView = (next: UserView) => {
    setUserView(next); updateLocation('users', next)
  }
  const selectPolicyView = (next: PolicyView) => {
    setPolicyView(next); updateLocation('policies', next)
  }
  const accessTabs = useRovingTabs({
    ids: views.map((item) => item.id),
    activeId: view,
    idPrefix: 'admin-access',
    onSelect: selectView,
  })
  const userTabs = useRovingTabs({
    ids: userViews.map((item) => item.id),
    activeId: activeUserView,
    idPrefix: 'admin-users',
    onSelect: selectUserView,
  })
  const policyTabs = useRovingTabs({
    ids: policyViews.map((item) => item.id),
    activeId: activePolicyView,
    idPrefix: 'admin-policies',
    onSelect: selectPolicyView,
  })

  return <div className="grid gap-3">
    <section className="panel border-l-4 border-l-blue-700 bg-slate-50">
      <span className="eyebrow">Accounts &amp; authorization</span>
      <h2 className="mb-1 mt-1 text-base text-navy-900">계정/권한</h2>
      <p className="m-0 text-xs leading-5 text-slate-600">사용자, 시스템 담당자, 간편 Role과 필수 보안정책을 한 곳에서 관리합니다. 실제 접근 판단은 계속 서버 ABAC와 현재 Workspace 범위가 수행합니다.</p>
    </section>
    <div className="flex flex-wrap gap-1 border-b border-slate-300" role="tablist" aria-label="계정/권한 관리 영역">
      {views.map((item) => <button key={item.id} {...accessTabs.tabProps(item.id)} type="button" aria-label={item.label} className={`min-w-40 border border-b-0 px-3 py-2 text-left text-xs font-black ${view === item.id ? 'border-blue-700 bg-blue-700 text-white' : 'border-slate-300 bg-slate-100 text-slate-600'}`} onClick={() => selectView(item.id)}><span className="block">{item.label}</span><small className="mt-0.5 block text-[9px] font-bold opacity-75">{item.description}</small></button>)}
    </div>
    {view === 'users' && <section {...accessTabs.panelProps('users')} className="grid gap-3">
      <div className="flex gap-1" role="tablist" aria-label="사용자 권한 관리 방식">
        {userViews.map((item) => <button key={item.id} {...userTabs.tabProps(item.id)} type="button" className={`button ${activeUserView === item.id ? '' : 'button-secondary'}`} onClick={() => selectUserView(item.id)}>{item.label}</button>)}
      </div>
      {activeUserView === 'directory' && <div {...userTabs.panelProps('directory')}><MembershipAccessAdmin {...props} /></div>}
      {activeUserView === 'roles' && <div {...userTabs.panelProps('roles')}><RoleAccessAdmin {...props} /></div>}
      {activeUserView === 'renewals' && <div {...userTabs.panelProps('renewals')}><MembershipRenewalAdmin {...props} /></div>}
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
    {view === 'recovery' && <section {...accessTabs.panelProps('recovery')} className="grid gap-3"><p className="callout m-0">보안키를 사용할 수 없는 검증된 예외 상황에서만 Maker와 Checker가 분리된 일회성 변경을 처리합니다.</p><FallbackQueueAdmin {...props} /></section>}
  </div>
}
