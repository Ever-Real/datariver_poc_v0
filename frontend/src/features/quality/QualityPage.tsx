import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ApiClient } from '../../api/client'
import type { QualityCapabilityAxis } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { GovernedUnavailable } from '../../components/common/GovernedUnavailable'
import { useRovingTabs } from '../../components/common/useRovingTabs'
import { PageTitle } from '../../components/layout/PageTitle'
import { QualityIssuesTab } from './QualityIssuesTab'
import { QualityOverviewTab } from './QualityOverviewTab'
import { QualityRuleSetsTab } from './QualityRuleSetsTab'
import { QualityRunsTab } from './QualityRunsTab'
import { QualityApi } from './qualityApi'
import {
  qualityLocationFromHref,
  qualityUrl,
  sanitizeQualityUrl,
  type QualityLocation,
  type QualityTab,
} from './qualityLocation'
import { QualityStatus, dateTimeText } from './QualityShared'
import { useQualityAuthorizationLease } from './useQualityAuthorizationLease'

const qualityTabs = [
  { id: 'overview', label: '현황' },
  { id: 'rules', label: 'Rule Sets' },
  { id: 'runs', label: '실행 이력' },
  { id: 'issues', label: '이슈' },
] as const satisfies ReadonlyArray<{ id: QualityTab; label: string }>
const qualityTabIds = qualityTabs.map((tab) => tab.id)

export function QualityPage({
  client,
  workspaceId,
  subjectId,
  securityEpoch,
  authorizationRevision,
}: {
  client: ApiClient
  workspaceId: string
  subjectId: string
  securityEpoch: number
  authorizationRevision: number
}) {
  const api = useMemo(() => new QualityApi(client), [client])
  const [location, setLocation] = useState<QualityLocation>(qualityLocationFromHref)
  const lease = useQualityAuthorizationLease({
    api,
    workspaceId,
    subjectId,
    securityEpoch,
    authorizationRevision,
  })

  useEffect(() => {
    const sanitized = sanitizeQualityUrl()
    const current = `${window.location.pathname}${window.location.search}${window.location.hash}`
    if (current !== sanitized) window.history.replaceState({}, '', sanitized)
    setLocation(qualityLocationFromHref())
    const restore = () => setLocation(qualityLocationFromHref())
    window.addEventListener('popstate', restore)
    return () => window.removeEventListener('popstate', restore)
  }, [])

  const navigateTab = useCallback((tab: QualityTab) => {
    const next: QualityLocation = { tab }
    window.history.pushState({}, '', qualityUrl(next))
    setLocation(next)
  }, [])
  const selectRuleSet = useCallback((ruleSetId?: string) => {
    const next: QualityLocation = { tab: 'rules', ...(ruleSetId ? { ruleSetId } : {}) }
    window.history.pushState({}, '', qualityUrl(next))
    setLocation(next)
  }, [])
  const selectRun = useCallback((runId?: string) => {
    const next: QualityLocation = { tab: 'runs', ...(runId ? { runId } : {}) }
    window.history.pushState({}, '', qualityUrl(next))
    setLocation(next)
  }, [])
  const tabs = useRovingTabs({
    ids: qualityTabIds,
    activeId: location.tab,
    idPrefix: 'quality-primary',
    onSelect: navigateTab,
  })

  return <section className="quality-page">
    <PageTitle
      icon="DQ"
      eyebrow="Data quality · permission scoped"
      title="품질관리"
      description="검증 Rule, 실행 결과와 품질 이슈를 서버가 허용한 범위 안에서 관리합니다."
      actions={<button
        type="button"
        className="button button-secondary"
        onClick={lease.refresh}
        disabled={lease.loading}
      >
        권한·현황 새로고침
      </button>}
    />
    {lease.loading && <p className="quality-loading" role="status">품질 접근 권한을 확인하는 중입니다.</p>}
    {!lease.loading && Boolean(lease.error) && <>
      <ErrorNotice error={lease.error} />
      <GovernedUnavailable
        title="품질 접근 권한을 확인할 수 없습니다"
        description="권한 capability가 검증되기 전에는 품질 데이터 요청을 시작하지 않습니다."
      />
    </>}
    {!lease.loading && !lease.error && !lease.capability && <GovernedUnavailable
      title="품질 Workspace를 확인할 수 없습니다"
      description="검증된 Workspace와 사용자 식별자가 준비된 뒤 다시 시도해 주세요."
    />}
    {lease.capability && lease.axis('read_access')?.state !== 'AVAILABLE' && (
      <GovernedUnavailable
        title="품질 데이터 열람이 허용되지 않았습니다"
        description={capabilityReason(lease.axis('read_access'))}
      />
    )}
    {lease.capability && lease.boundary && lease.axis('read_access')?.state === 'AVAILABLE' && <>
      <section className="quality-lease-summary" aria-label="품질 권한 상태">
        <QualityStatus value="AVAILABLE" />
        <span>관측 {dateTimeText(lease.capability.observed_at)}</span>
        <span>유효 {dateTimeText(lease.capability.valid_until)}</span>
      </section>
      <nav className="quality-tabs" role="tablist" aria-label="품질관리 영역">
        {qualityTabs.map((tab) => <button
          key={tab.id}
          {...tabs.tabProps(tab.id)}
          type="button"
          className={location.tab === tab.id ? 'active' : ''}
          onClick={() => navigateTab(tab.id)}
        >
          {tab.label}
        </button>)}
      </nav>
      <div className="quality-tab-panel" {...tabs.panelProps(location.tab)}>
        <QualityActiveTab
          api={api}
          boundary={lease.boundary}
          axes={new Map(lease.capability.axes.map((axis) => [axis.id, axis]))}
          location={location}
          onSelectedRuleSet={selectRuleSet}
          onSelectedRun={selectRun}
          onBoundaryInvalid={lease.invalidate}
        />
      </div>
    </>}
  </section>
}

function QualityActiveTab({
  api,
  boundary,
  axes,
  location,
  onSelectedRuleSet,
  onSelectedRun,
  onBoundaryInvalid,
}: {
  api: QualityApi
  boundary: NonNullable<ReturnType<typeof useQualityAuthorizationLease>['boundary']>
  axes: Map<string, QualityCapabilityAxis>
  location: QualityLocation
  onSelectedRuleSet: (id?: string) => void
  onSelectedRun: (id?: string) => void
  onBoundaryInvalid: () => void
}) {
  if (location.tab === 'rules') return <QualityRuleSetsTab
    api={api}
    boundary={boundary}
    axes={axes}
    selectedRuleSetId={location.ruleSetId}
    onSelectedRuleSet={onSelectedRuleSet}
    onBoundaryInvalid={onBoundaryInvalid}
  />
  if (location.tab === 'runs') return <QualityRunsTab
    api={api}
    boundary={boundary}
    axes={axes}
    selectedRunId={location.runId}
    onSelectedRun={onSelectedRun}
    onBoundaryInvalid={onBoundaryInvalid}
  />
  if (location.tab === 'issues') return <QualityIssuesTab
    api={api}
    boundary={boundary}
    onBoundaryInvalid={onBoundaryInvalid}
  />
  return <QualityOverviewTab
    api={api}
    boundary={boundary}
    onBoundaryInvalid={onBoundaryInvalid}
  />
}

function capabilityReason(axis: QualityCapabilityAxis | undefined): string {
  return axis?.reason_code
    ? `서버 capability가 ${axis.reason_code} 사유로 품질 데이터 열람을 허용하지 않았습니다.`
    : '현재 사용자에게 품질 데이터 열람 권한이 없습니다.'
}
