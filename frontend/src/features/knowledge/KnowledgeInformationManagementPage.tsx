import { Braces, Database, Network, RefreshCw, Settings2, Tags } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import type { ApiClient } from '../../api/client'
import { KnowledgePropertyProfilePanel } from './KnowledgePropertyProfilePanel'
import { KnowledgeAssetInstancePanel } from './KnowledgeAssetInstancePanel'
import { KnowledgeDeliveryPolicyPanel } from './KnowledgeDeliveryPolicyPanel'
import { DomainManagementPanel } from './studio/basic/DomainManagementDialog'
import {
  listKnowledgeStudioDomains,
  type KnowledgeStudioDomainOption,
} from './studio/knowledgeStudioApi'

export function KnowledgeInformationManagementPage({
  client,
  onStepUp,
  onPasswordReauth,
  onEnroll,
  hardwareWebauthnEnabled,
  onEditAsset,
  initialTab = 'DOMAINS',
  initialAssetId,
  initialChangesetId,
}: {
  client: ApiClient
  onStepUp?: () => Promise<void>
  onPasswordReauth?: () => Promise<void>
  onEnroll?: () => Promise<void>
  hardwareWebauthnEnabled?: boolean
  onEditAsset?: (assetId: string) => void
  initialTab?: 'DOMAINS' | 'PROFILES' | 'INSTANCES' | 'DELIVERY'
  initialAssetId?: string
  initialChangesetId?: string
}) {
  const [activeTab, setActiveTab] = useState<
    'DOMAINS' | 'PROFILES' | 'INSTANCES' | 'DELIVERY'
  >(initialTab)
  const [domains, setDomains] = useState<KnowledgeStudioDomainOption[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)

  const reload = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    setError('')
    try {
      const items = await listKnowledgeStudioDomains(client, 'INTERNAL', undefined, signal)
      setDomains(items)
      return items
    } catch (caught) {
      if (signal?.aborted) return []
      setError(caught instanceof Error ? caught.message : '업무 도메인을 불러오지 못했습니다.')
      return []
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [client])

  useEffect(() => {
    const controller = new AbortController()
    void reload(controller.signal)
    return () => controller.abort()
  }, [reload, revision])

  useEffect(() => {
    setActiveTab(initialTab)
  }, [initialTab])

  return (
    <section className="grid min-h-[520px] content-start gap-4 rounded-enterprise border border-slate-300 bg-white p-5 shadow-sm">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 pb-4">
        <div className="flex items-start gap-3">
          <span className="grid size-10 shrink-0 place-items-center rounded-enterprise bg-blue-50 text-enterprise-blue">
            <Settings2 size={20} aria-hidden="true" />
          </span>
          <div>
            <span className="text-[10px] font-black tracking-[.14em] text-enterprise-blue uppercase">
              Knowledge controlled information
            </span>
            <h2 className="my-1 text-lg font-black text-navy-900">정보 관리</h2>
            <p className="m-0 max-w-3xl text-xs leading-5 text-slate-500">
              Knowledge Studio와 동일한 PostgreSQL 정본 및 API로 업무 도메인과 발행된
              Property 프로파일, A-Box Release와 API·Chat routing 정책을 관리합니다.
              구조 편집은 Studio, 인스턴스 변경은 typed Changeset으로 분리됩니다.
            </p>
          </div>
        </div>
        {activeTab === 'DOMAINS' && (
          <button
            type="button"
            className="button button-secondary"
            disabled={loading}
            onClick={() => setRevision((current) => current + 1)}
          >
            <RefreshCw size={14} aria-hidden="true" />
            새로고침
          </button>
        )}
      </header>
      <nav className="flex flex-wrap gap-2 border-b border-slate-200 pb-3" aria-label="정보 관리 구분">
        {[
          { id: 'DOMAINS' as const, label: '업무 도메인', icon: Database },
          { id: 'PROFILES' as const, label: 'Property 프로파일', icon: Tags },
          { id: 'INSTANCES' as const, label: '인스턴스·적재', icon: Network },
          { id: 'DELIVERY' as const, label: 'API & Chat routing', icon: Braces },
        ].map((tab) => {
          const Icon = tab.icon
          const active = activeTab === tab.id
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={active}
              className={`button ${active ? '' : 'button-secondary'}`}
              onClick={() => setActiveTab(tab.id)}
            >
              <Icon size={13} aria-hidden="true" />
              {tab.label}
            </button>
          )
        })}
      </nav>
      {activeTab === 'DOMAINS' && (
        <>
          {error && (
            <div role="alert" className="rounded-enterprise border border-red-200 bg-red-50 p-3 text-xs text-red-800">
              {error}
              <button
                type="button"
                className="ml-3 font-black underline"
                onClick={() => setRevision((current) => current + 1)}
              >
                다시 시도
              </button>
            </div>
          )}
          <DomainManagementPanel
            client={client}
            items={domains}
            loading={loading}
            onChanged={async () => {
              await reload()
            }}
            onStepUp={onStepUp}
            onPasswordReauth={onPasswordReauth}
            onEnroll={onEnroll}
            hardwareWebauthnEnabled={hardwareWebauthnEnabled}
          />
        </>
      )}
      {activeTab === 'PROFILES' && <KnowledgePropertyProfilePanel client={client} />}
      {activeTab === 'INSTANCES' && (
        <KnowledgeAssetInstancePanel
          client={client}
          onEditAsset={onEditAsset ?? (() => undefined)}
          initialAssetId={initialAssetId}
          initialChangesetId={initialChangesetId}
        />
      )}
      {activeTab === 'DELIVERY' && <KnowledgeDeliveryPolicyPanel client={client} />}
    </section>
  )
}
