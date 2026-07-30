import { RefreshCw, Settings2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import type { ApiClient } from '../../api/client'
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
              Knowledge Studio와 동일한 PostgreSQL 정본 및 API로 업무 도메인을 관리합니다.
              변경 결과는 신규 자산의 업무 도메인 선택 목록에 즉시 반영됩니다.
            </p>
          </div>
        </div>
        <button
          type="button"
          className="button button-secondary"
          disabled={loading}
          onClick={() => setRevision((current) => current + 1)}
        >
          <RefreshCw size={14} aria-hidden="true" />
          새로고침
        </button>
      </header>
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
    </section>
  )
}
