import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ApiClient } from '../../api/client'
import type { QualityCapabilityAxis } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { GovernedUnavailable } from '../../components/common/GovernedUnavailable'
import { useRovingTabs } from '../../components/common/useRovingTabs'
import { PageTitle } from '../../components/layout/PageTitle'
import { QualityAssetsTab } from './QualityAssetsTab'
import { QualityCommonRulesTab } from './QualityCommonRulesTab'
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
  { id: 'assets', label: '자산별 품질 현황 및 이력' },
  { id: 'templates', label: '공통 룰셋 관리' },
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

  const navigate = useCallback((next: QualityLocation) => {
    window.history.pushState({}, '', qualityUrl(next))
    setLocation(next)
  }, [])
  const navigateTab = useCallback(
    (tab: QualityTab) => navigate({ tab }),
    [navigate],
  )
  const tabs = useRovingTabs({
    ids: qualityTabIds,
    activeId: location.tab,
    idPrefix: 'quality-primary',
    onSelect: navigateTab,
  })

  return <section className="quality-page quality-page-user-centric">
    <PageTitle
      icon="DQ"
      eyebrow="Data quality · at a glance"
      title="품질관리"
      description="테이블별 품질 상태를 바로 확인하고, 공통 룰을 여러 자산에 간편하게 적용합니다."
      actions={<button
        type="button"
        className="button button-secondary"
        onClick={lease.refresh}
        disabled={lease.loading}
      >
        새로고침
      </button>}
    />
    {lease.loading && <p className="quality-loading" role="status">품질 정보를 준비하는 중입니다.</p>}
    {!lease.loading && Boolean(lease.error) && <>
      <ErrorNotice error={lease.error} />
      <GovernedUnavailable
        title="품질 정보를 불러올 수 없습니다"
        description="잠시 후 새로고침하거나 품질 열람 권한을 확인해 주세요."
      />
    </>}
    {!lease.loading && !lease.error && !lease.capability && <GovernedUnavailable
      title="품질 Workspace를 확인할 수 없습니다"
      description="검증된 Workspace와 사용자 식별자가 준비된 뒤 다시 시도해 주세요."
    />}
    {lease.capability && lease.axis('read_access')?.state !== 'AVAILABLE' && (
      <GovernedUnavailable
        title="품질 데이터 열람 권한이 없습니다"
        description={capabilityReason(lease.axis('read_access'))}
      />
    )}
    {lease.capability && lease.boundary && lease.axis('read_access')?.state === 'AVAILABLE' && <>
      <section className="quality-lease-summary" aria-label="품질 데이터 기준 시각">
        <QualityStatus value="AVAILABLE" />
        <span>최근 확인 {dateTimeText(lease.capability.observed_at)}</span>
      </section>
      <nav className="quality-tabs quality-tabs-simple" role="tablist" aria-label="품질관리 영역">
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
        {location.tab === 'assets'
          ? <QualityAssetsTab
            api={api}
            boundary={lease.boundary}
            selectedAssetId={location.assetId}
            onSelectedAsset={(assetId) => navigate({
              tab: 'assets',
              ...(assetId ? { assetId } : {}),
            })}
            onBoundaryInvalid={lease.invalidate}
          />
          : <QualityCommonRulesTab
            api={api}
            boundary={lease.boundary}
            axes={new Map(lease.capability.axes.map((axis) => [axis.id, axis]))}
            selectedTemplateId={location.templateId}
            onSelectedTemplate={(templateId) => navigate({
              tab: 'templates',
              ...(templateId ? { templateId } : {}),
            })}
            onBoundaryInvalid={lease.invalidate}
          />}
      </div>
    </>}
  </section>
}

function capabilityReason(axis: QualityCapabilityAxis | undefined): string {
  return axis?.reason_code
    ? `현재 권한 정책(${axis.reason_code})에서는 품질 정보를 표시할 수 없습니다.`
    : '현재 사용자에게 품질 데이터 열람 권한이 없습니다.'
}
