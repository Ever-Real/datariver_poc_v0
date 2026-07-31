import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from 'react'
import { Braces, RefreshCw, Route, Save, ShieldCheck } from 'lucide-react'
import { newIdempotencyKey, type ApiClient } from '../../api/client'
import type {
  KnowledgeAssetSummary,
  KnowledgeDeliveryPolicy,
} from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import type { ColumnDef } from '@tanstack/react-table'
import { listAllKnowledgeAssets } from './knowledgeRegistryApi'

interface PolicyForm {
  apiEnabled: boolean
  chatEnabled: boolean
  priority: string
  anyTerms: string
  allTerms: string
  excludedTerms: string
}

const EMPTY_FORM: PolicyForm = {
  apiEnabled: false,
  chatEnabled: false,
  priority: '100',
  anyTerms: '',
  allTerms: '',
  excludedTerms: '',
}

function formFromAsset(asset?: KnowledgeAssetSummary): PolicyForm {
  const policy = asset?.delivery_policy
  if (!policy) return EMPTY_FORM
  return {
    apiEnabled: policy.api_enabled,
    chatEnabled: policy.chat_enabled,
    priority: String(policy.priority),
    anyTerms: policy.match_any_terms.join(', '),
    allTerms: policy.match_all_terms.join(', '),
    excludedTerms: policy.excluded_terms.join(', '),
  }
}

function terms(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

export function KnowledgeDeliveryPolicyPanel({ client }: { client: ApiClient }) {
  const [assets, setAssets] = useState<KnowledgeAssetSummary[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [form, setForm] = useState<PolicyForm>(EMPTY_FORM)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<unknown>()
  const [status, setStatus] = useState('')
  const pendingSaveRef = useRef<{ fingerprint: string; key: string } | undefined>(undefined)

  const load = useCallback(async () => {
    setLoading(true)
    setError(undefined)
    try {
      const items = await listAllKnowledgeAssets(client)
      setAssets(items)
      setSelectedId((current) => {
        const nextId = current && items.some((item) => item.id === current)
          ? current
          : items[0]?.id ?? ''
        setForm(formFromAsset(items.find((item) => item.id === nextId)))
        return nextId
      })
    } catch (next) {
      setError(next)
    } finally {
      setLoading(false)
    }
  }, [client])

  useEffect(() => {
    void load()
  }, [load])

  const selected = assets.find((item) => item.id === selectedId)

  const columns = useMemo<ColumnDef<KnowledgeAssetSummary>[]>(() => [
    {
      accessorKey: 'name',
      header: 'Asset',
      cell: ({ row }) => (
        <div>
          <strong>{row.original.name}</strong>
          <small className="block text-slate-500">{row.original.slug}</small>
        </div>
      ),
    },
    {
      id: 'api',
      header: 'API',
      cell: ({ row }) => row.original.delivery_policy?.api_enabled ? 'ENABLED' : 'DISABLED',
    },
    {
      id: 'chat',
      header: 'Chat',
      cell: ({ row }) => row.original.delivery_policy?.chat_enabled ? 'ROUTED' : 'OFF',
    },
    {
      id: 'priority',
      header: 'Priority',
      cell: ({ row }) => row.original.delivery_policy?.priority ?? '—',
    },
  ], [])

  const save = async (event: FormEvent) => {
    event.preventDefault()
    if (!selected || saving) return
    setSaving(true)
    setError(undefined)
    setStatus('')
    try {
      const body = JSON.stringify({
        api_enabled: form.apiEnabled,
        chat_enabled: form.chatEnabled,
        priority: Number(form.priority),
        match_any_terms: terms(form.anyTerms),
        match_all_terms: terms(form.allTerms),
        excluded_terms: terms(form.excludedTerms),
      })
      const fingerprint = `${selected.id}:${selected.delivery_policy?.version ?? 0}:${body}`
      if (pendingSaveRef.current?.fingerprint !== fingerprint) {
        pendingSaveRef.current = {
          fingerprint,
          key: newIdempotencyKey('knowledge-delivery-policy'),
        }
      }
      const policy = await client.request<KnowledgeDeliveryPolicy>(
        `/knowledge/registry/assets/${encodeURIComponent(selected.id)}/delivery-policy`,
        {
          method: 'PUT',
          body,
          cache: 'no-store',
          ifMatch: selected.delivery_policy
            ? `"${selected.delivery_policy.version}"`
            : undefined,
          idempotencyKey: pendingSaveRef.current.key,
        },
      )
      setAssets((current) => current.map((item) => (
        item.id === selected.id ? { ...item, delivery_policy: policy } : item
      )))
      pendingSaveRef.current = undefined
      setStatus('API 제공 및 Chat routing 정책을 저장했습니다.')
    } catch (next) {
      setError(next)
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="grid gap-4">
      <header className="flex flex-wrap items-start justify-between gap-3 rounded-enterprise border border-blue-200 bg-blue-50 p-4">
        <div className="flex items-start gap-3">
          <span className="grid size-9 place-items-center rounded bg-white text-enterprise-blue">
            <Route size={18} aria-hidden="true" />
          </span>
          <div>
            <h3 className="m-0 text-sm font-black text-navy-900">API &amp; Chat routing</h3>
            <p className="mb-0 mt-1 max-w-3xl text-xs leading-5 text-slate-600">
              API는 활성 Release의 typed 경로만 제공하며 OIDC·KG ABAC를 우회하지 않습니다.
              Chat은 의미 분류가 GRAPH인 질문에 한해 ANY/ALL/제외 조건과 우선순위로 하나의
              허가된 Asset 범위를 선택합니다.
            </p>
          </div>
        </div>
        <button
          type="button"
          className="button button-secondary"
          disabled={loading}
          onClick={() => void load()}
        >
          <RefreshCw size={13} /> 새로고침
        </button>
      </header>
      <ErrorNotice error={error} />
      {status && (
        <p role="status" className="m-0 rounded border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-800">
          {status}
        </p>
      )}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.05fr)_minmax(360px,.95fr)]">
        <DenseDataTable
          caption="지식 Asset delivery 정책"
          columns={columns}
          data={assets}
          getRowId={(item) => item.id}
          loading={loading}
          selectedRowId={selectedId}
          onRowActivate={(item) => {
            setSelectedId(item.id)
            setForm(formFromAsset(item))
            setStatus('')
            pendingSaveRef.current = undefined
          }}
        />
        <form className="grid content-start gap-3 rounded-enterprise border border-slate-300 bg-slate-50 p-4" onSubmit={(event) => void save(event)}>
          <div>
            <span className="text-[10px] font-black tracking-[.12em] text-enterprise-blue uppercase">
              Selected asset
            </span>
            <h4 className="my-1 text-base font-black text-navy-900">
              {selected?.name ?? 'Asset을 선택하세요'}
            </h4>
            {selected && <code className="text-[11px] text-slate-500">{selected.slug}</code>}
          </div>
          <label className="flex items-center justify-between gap-3 rounded border border-slate-200 bg-white p-3 text-xs font-bold">
            <span>
              외부 서비스 API 제공
              <small className="mt-1 block font-normal text-slate-500">
                alias resolver와 활성 Release 상대 경로를 노출
              </small>
            </span>
            <input
              type="checkbox"
              checked={form.apiEnabled}
              disabled={!selected}
              onChange={(event) => setForm((current) => ({
                ...current,
                apiEnabled: event.target.checked,
              }))}
            />
          </label>
          <label className="flex items-center justify-between gap-3 rounded border border-slate-200 bg-white p-3 text-xs font-bold">
            <span>
              플랫폼 Chat 자동 라우팅
              <small className="mt-1 block font-normal text-slate-500">
                정책 조건이 없으면 활성화할 수 없음
              </small>
            </span>
            <input
              type="checkbox"
              checked={form.chatEnabled}
              disabled={!selected}
              onChange={(event) => setForm((current) => ({
                ...current,
                chatEnabled: event.target.checked,
              }))}
            />
          </label>
          <label className="grid gap-1 text-xs font-bold">
            우선순위 (0–1000)
            <input
              type="number"
              min={0}
              max={1000}
              value={form.priority}
              disabled={!selected}
              onChange={(event) => setForm((current) => ({
                ...current,
                priority: event.target.value,
              }))}
            />
          </label>
          <label className="grid gap-1 text-xs font-bold">
            ANY 조건 · 쉼표 구분
            <input
              value={form.anyTerms}
              disabled={!selected}
              placeholder="우주 시스템, 위성, 발사체"
              onChange={(event) => setForm((current) => ({
                ...current,
                anyTerms: event.target.value,
              }))}
            />
          </label>
          <label className="grid gap-1 text-xs font-bold">
            ALL 조건 · 쉼표 구분
            <input
              value={form.allTerms}
              disabled={!selected}
              placeholder="계보, 영향도"
              onChange={(event) => setForm((current) => ({
                ...current,
                allTerms: event.target.value,
              }))}
            />
          </label>
          <label className="grid gap-1 text-xs font-bold">
            제외 조건 · 쉼표 구분
            <input
              value={form.excludedTerms}
              disabled={!selected}
              onChange={(event) => setForm((current) => ({
                ...current,
                excludedTerms: event.target.value,
              }))}
            />
          </label>
          {selected && (
            <div className="grid gap-1 rounded border border-slate-200 bg-white p-3 text-[11px] text-slate-600">
              <span className="flex items-center gap-1 font-bold text-navy-900">
                <ShieldCheck size={12} /> 제공 경로
              </span>
              <code className="break-all">
                GET /api/v1/knowledge/assets/by-alias/{selected.slug}
              </code>
              <span className="flex items-center gap-1 pt-1 font-bold text-navy-900">
                <Braces size={12} /> raw Cypher/SQL/credential은 계약에 포함되지 않습니다.
              </span>
            </div>
          )}
          <button
            type="submit"
            className="button"
            disabled={!selected || saving || (form.chatEnabled && !terms(form.anyTerms).length && !terms(form.allTerms).length)}
          >
            <Save size={13} /> {saving ? '저장 중…' : '정책 저장'}
          </button>
        </form>
      </div>
    </section>
  )
}
