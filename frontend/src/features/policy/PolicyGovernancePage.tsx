import { useEffect, useMemo, useState } from 'react'
import type { ApiClient } from '../../api/client'
import type { AdminOperation, ProfileRolePolicy } from '../../api/types'
import type { AssuranceActions } from '../../components/AssuranceNotice'
import { useRovingTabs } from '../../components/common/useRovingTabs'
import { PageTitle } from '../../components/layout/PageTitle'
import { GovernanceDocumentLibrary } from '../governance-documents/GovernanceDocumentLibrary'
import { GovernanceDocumentViewer } from '../governance-documents/GovernanceDocumentViewer'
import type { GovernanceDocumentCapability } from '../governance-documents/types'

type GovernancePrimaryTab = 'DOCUMENT_VIEW' | 'ROLE_POLICY' | 'DOCUMENT_MANAGEMENT'

const allTabs = [
  { id: 'DOCUMENT_VIEW', label: '문서 조회' },
  { id: 'ROLE_POLICY', label: '역할별 권한 정책' },
  { id: 'DOCUMENT_MANAGEMENT', label: '문서 관리' },
] as const satisfies ReadonlyArray<{ id: GovernancePrimaryTab; label: string }>

export function PolicyGovernancePage({
  client,
  assurance,
}: {
  client: ApiClient
  mayReadPolicies?: boolean
  allowedOperations?: readonly AdminOperation[]
  assurance?: AssuranceActions
}) {
  const [primaryTab, setPrimaryTab] = useState<GovernancePrimaryTab>('DOCUMENT_VIEW')
  const [capability, setCapability] = useState<GovernanceDocumentCapability>()
  const [profileRolePolicy, setProfileRolePolicy] = useState<ProfileRolePolicy>()
  const [profileRolePolicyError, setProfileRolePolicyError] = useState(false)
  const managementAvailable = capability?.axes.some((axis) => (
    ['create', 'edit', 'review', 'publish', 'archive', 'template_manage'].includes(axis.id)
    && axis.state === 'AVAILABLE'
  )) ?? false
  const tabs = useMemo(
    () => managementAvailable
      ? allTabs
      : allTabs.filter((tab) => tab.id !== 'DOCUMENT_MANAGEMENT'),
    [managementAvailable],
  )
  const tabIds = tabs.map((tab) => tab.id)
  const primaryTabs = useRovingTabs({
    ids: tabIds,
    activeId: primaryTab,
    idPrefix: 'governance-primary',
    onSelect: setPrimaryTab,
  })

  useEffect(() => {
    if (!managementAvailable && primaryTab === 'DOCUMENT_MANAGEMENT') {
      setPrimaryTab('DOCUMENT_VIEW')
    }
  }, [managementAvailable, primaryTab])

  useEffect(() => {
    if (primaryTab !== 'ROLE_POLICY' || profileRolePolicy) return
    const controller = new AbortController()
    void client.request<ProfileRolePolicy>('/admin/profile-role-policy', {
      cache: 'no-store',
      signal: controller.signal,
    }).then((value) => {
      setProfileRolePolicy(value)
      setProfileRolePolicyError(false)
    }).catch(() => {
      if (!controller.signal.aborted) setProfileRolePolicyError(true)
    })
    return () => controller.abort()
  }, [client, primaryTab, profileRolePolicy])

  return <section className="policy-governance-page">
    <PageTitle
      icon="GV"
      eyebrow="Policy governance"
      title="거버넌스"
      description="승인·게시된 문서를 조회하고, 권한이 있는 사용자는 불변 버전과 결재 흐름으로 관리합니다."
    />
    <nav className="governance-primary-tabs" role="tablist" aria-label="거버넌스 영역">
      {tabs.map((tab) => <button
        key={tab.id}
        {...primaryTabs.tabProps(tab.id)}
        type="button"
        className={primaryTab === tab.id ? 'active' : ''}
        onClick={() => setPrimaryTab(tab.id)}
      >
        {tab.label}
      </button>)}
    </nav>
    <div {...primaryTabs.panelProps(primaryTab)} className="governance-primary-panel">
      {primaryTab === 'DOCUMENT_VIEW'
        ? <GovernanceDocumentViewer client={client} onCapability={setCapability} />
        : primaryTab === 'ROLE_POLICY'
          ? <section className="panel grid gap-3" aria-label="역할별 서비스 권한 정책">
            <div className="section-heading"><div><h2>사용자 프로필 권한 정책</h2><p className="muted">서비스 권한은 서버 정책으로 일괄 부여되며, 데이터 조회 등급과 System 담당 범위는 별도로 적용됩니다.</p></div>{profileRolePolicy && <span className="badge badge-soft">{profileRolePolicy.policy_version}</span>}</div>
            {profileRolePolicyError && <p className="notice notice-error m-0">역할별 권한 정책을 불러오지 못했습니다.</p>}
            {!profileRolePolicy && !profileRolePolicyError && <p className="muted">정책을 불러오는 중입니다.</p>}
            {profileRolePolicy && <div className="dense-table-frame"><table className="dense-data-table"><caption className="sr-only">사용자 역할별 서비스 권한</caption><thead><tr><th>프로필 권한</th><th>설명</th><th>서비스별 권한</th><th>System 담당</th><th>삭제·이력 원칙</th></tr></thead><tbody>{profileRolePolicy.items.map((item) => <tr key={item.tier}><td><strong>{item.label}</strong><small>{item.tier}</small></td><td>{item.description}</td><td>{item.services.map((service) => <div className="mb-2" key={service.service_key}><strong>{service.service_label}</strong><small>{service.action_labels.join(' · ')}</small></div>)}</td><td>{item.assignable_to_system ? 'Engineer / Steward 배정 가능' : '배정 제외'}</td><td>{item.lifecycle_note}</td></tr>)}</tbody></table></div>}
          </section>
          : <GovernanceDocumentLibrary client={client} assurance={assurance} />}
    </div>
  </section>
}
