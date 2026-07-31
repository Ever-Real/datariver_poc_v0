import { Boxes, Database, RefreshCw, Settings2, Tags } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import type { ApiClient } from '../../api/client'
import { KnowledgePropertyProfilePanel } from './KnowledgePropertyProfilePanel'
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
}: {
  client: ApiClient
  onStepUp?: () => Promise<void>
  onPasswordReauth?: () => Promise<void>
  onEnroll?: () => Promise<void>
}) {
  const [activeTab, setActiveTab] = useState<'DOMAINS' | 'PROFILES' | 'ASSETS'>('DOMAINS')
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
              Property 프로파일을 관리합니다. 변경 결과는 신규 자산 선택과 활성 Release
              상세에 즉시 반영됩니다.
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
          { id: 'ASSETS' as const, label: 'Asset 관리 설계', icon: Boxes },
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
          />
        </>
      )}
      {activeTab === 'PROFILES' && <KnowledgePropertyProfilePanel client={client} />}
      {activeTab === 'ASSETS' && (
        <section className="grid gap-4" aria-label="Knowledge Asset 관리 설계">
          <div className="rounded-enterprise border border-blue-200 bg-blue-50 p-4">
            <h3 className="m-0 text-sm font-black text-navy-900">Asset 관리 화면 경계</h3>
            <p className="mb-0 mt-2 text-xs leading-5 text-slate-600">
              Registry가 조회·생성·버전 포커싱을 담당하고, 정보 관리는 발행된 Release의
              Property 프로파일과 업무 도메인을 담당합니다. A-Box 원본 데이터와 Neo4j를
              이 화면에서 직접 수정하지 않습니다.
            </p>
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            {[
              ['Asset / Release', 'Asset 선택 후 활성·과거 Release와 immutable T-Box Property를 조회합니다.'],
              ['Property Profiles', 'Property URN 기준 설명·단위·동의어를 ETag aggregate로 관리합니다.'],
              ['Projection Sync', '향후 Outbox receipt를 기준으로 PostgreSQL→Neo4j Projection 상태만 조회합니다.'],
            ].map(([title, description]) => (
              <article key={title} className="rounded-enterprise border border-slate-200 bg-slate-50 p-4">
                <strong className="text-xs text-navy-900">{title}</strong>
                <p className="mb-0 mt-2 text-[11px] leading-5 text-slate-500">{description}</p>
              </article>
            ))}
          </div>
          <p className="m-0 text-[11px] leading-5 text-slate-500">
            현재 구현 범위는 Domain CRUD와 Property Profile CRUD입니다. A-Box Binding 및
            Projection receipt 탭은 별도 승인된 정본·worker 계약이 추가된 뒤 활성화합니다.
          </p>
        </section>
      )}
    </section>
  )
}
