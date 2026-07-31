import { useEffect, useMemo, useState } from 'react'
import type { ApiClient } from '../../api/client'
import type { AdminOperation } from '../../api/types'
import type { AssuranceActions } from '../../components/AssuranceNotice'
import { useRovingTabs } from '../../components/common/useRovingTabs'
import { PageTitle } from '../../components/layout/PageTitle'
import { GovernanceDocumentLibrary } from '../governance-documents/GovernanceDocumentLibrary'
import { GovernanceDocumentViewer } from '../governance-documents/GovernanceDocumentViewer'
import type { GovernanceDocumentCapability } from '../governance-documents/types'

type GovernancePrimaryTab = 'DOCUMENT_VIEW' | 'DOCUMENT_MANAGEMENT'

const allTabs = [
  { id: 'DOCUMENT_VIEW', label: '문서 조회' },
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
  const managementAvailable = capability?.axes.some((axis) => (
    ['create', 'edit', 'review', 'publish', 'archive', 'template_manage'].includes(axis.id)
    && axis.state === 'AVAILABLE'
  )) ?? false
  const tabs = useMemo(
    () => managementAvailable ? allTabs : allTabs.filter((tab) => tab.id === 'DOCUMENT_VIEW'),
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
        : <GovernanceDocumentLibrary client={client} assurance={assurance} />}
    </div>
  </section>
}
