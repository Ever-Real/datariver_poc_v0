import { ArrowRight, Info, Plus, Save } from 'lucide-react'
import { useEffect, useState } from 'react'
import type {
  KnowledgeClassification,
  KnowledgeStudioBasicInformation,
  KnowledgeStudioDomainOption,
  KnowledgeStudioDraft,
} from '../knowledgeStudioApi'

const classifications: KnowledgeClassification[] = [
  'normal',
  'credential',
  'restricted',
]

export function endpointAliasError(value: string): string | undefined {
  if (value.length < 3 || value.length > 100) return '3~100자로 입력하세요.'
  const first = value[0]
  if (!first || first < 'a' || first > 'z') return '소문자 영문으로 시작해야 합니다.'
  for (const character of value.slice(1)) {
    const letter = character >= 'a' && character <= 'z'
    const digit = character >= '0' && character <= '9'
    if (!(letter || digit || character === '_')) {
      return '소문자 영문, 숫자, underscore(_)만 사용할 수 있습니다.'
    }
  }
  return undefined
}

export function parseEndpointAliases(value: string): string[] {
  return [...new Set(
    value
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean),
  )]
}

export function endpointAliasesError(values: string[]): string | undefined {
  if (values.length === 0) return 'Endpoint alias를 하나 이상 입력하세요.'
  if (values.length > 10) return 'Endpoint alias는 최대 10개까지 입력할 수 있습니다.'
  for (const value of values) {
    const error = endpointAliasError(value)
    if (error) return `'${value}': ${error}`
  }
  return undefined
}

export function basicInformationValid(value: KnowledgeStudioBasicInformation): boolean {
  const aliases = value.endpoint_aliases?.length
    ? value.endpoint_aliases
    : value.endpoint_alias
      ? [value.endpoint_alias]
      : []
  return (
    value.name.length >= 1
    && value.name.length <= 255
    && value.name === value.name.trim()
    && !endpointAliasesError(aliases)
    && value.endpoint_alias === aliases[0]
    && Boolean(value.domain_id)
    && Boolean(value.domain_source_version)
  )
}

interface BasicInformationStepProps {
  value: KnowledgeStudioBasicInformation
  domains: KnowledgeStudioDomainOption[]
  domainsLoading: boolean
  domainsError?: string
  domainQuery: string
  busy: boolean
  saveStatus: string
  onChange: (value: KnowledgeStudioBasicInformation) => void
  onDomainQueryChange: (value: string) => void
  onRetryDomains?: () => void
  onCreateDomain: (displayName: string) => Promise<void>
  onSave: () => void
  onContinue: () => void
  serverDraft?: Pick<
    KnowledgeStudioDraft,
    'managed_intent' | 'managed_graph_type' | 'accepted_proposal_id' | 'accepted_proposal_hash'
  >
}

export function BasicInformationStep({
  value,
  domains,
  domainsLoading,
  domainsError,
  domainQuery,
  busy,
  saveStatus,
  onChange,
  onDomainQueryChange,
  onRetryDomains,
  onCreateDomain,
  onSave,
  onContinue,
  serverDraft,
}: BasicInformationStepProps) {
  const [directDomain, setDirectDomain] = useState(false)
  const [domainCreating, setDomainCreating] = useState(false)
  const [aliasInput, setAliasInput] = useState(
    (value.endpoint_aliases?.length ? value.endpoint_aliases : [value.endpoint_alias])
      .filter(Boolean)
      .join(', '),
  )
  const aliases = value.endpoint_aliases?.length
    ? value.endpoint_aliases
    : value.endpoint_alias
      ? [value.endpoint_alias]
      : []
  const aliasError = endpointAliasesError(aliases)
  const valid = basicInformationValid(value)

  useEffect(() => {
    const serialized = (value.endpoint_aliases?.length
      ? value.endpoint_aliases
      : [value.endpoint_alias]
    ).filter(Boolean).join(', ')
    if (serialized && parseEndpointAliases(aliasInput).join(',') !== serialized.replaceAll(' ', '')) {
      setAliasInput(serialized)
    }
  }, [aliasInput, value.endpoint_alias, value.endpoint_aliases])

  const registerDirectDomain = async () => {
    const name = domainQuery.trim()
    if (!name || domainCreating) return
    setDomainCreating(true)
    try {
      await onCreateDomain(name)
      setDirectDomain(false)
      onDomainQueryChange('')
    } finally {
      setDomainCreating(false)
    }
  }

  return <div className="mx-auto grid max-w-5xl gap-5">
    <section className="rounded-enterprise border border-slate-300 bg-white p-5 shadow-sm">
      <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <span className="text-[10px] font-black tracking-[.14em] text-enterprise-blue uppercase">
            Step 1 · Asset contract
          </span>
          <h2 className="my-1 text-lg font-black text-navy-900">기본정보 등록</h2>
          <p className="m-0 max-w-3xl text-xs leading-5 text-slate-500">
            이름, API 식별자, 통제된 업무 도메인과 보안등급만 정의합니다.
            Graph type과 lifecycle은 서버 정책이 관리합니다.
          </p>
        </div>
      </header>
      {serverDraft?.managed_intent && (
        <section className="rounded-enterprise border border-blue-200 bg-blue-50 p-5 text-sm text-blue-950">
          <strong>Managed Intent: {serverDraft.managed_intent}</strong><br />
          Graph Type: {serverDraft.managed_graph_type}<br />
          Proposal: {serverDraft.accepted_proposal_id} ({serverDraft.accepted_proposal_hash})
        </section>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        <label className="grid gap-1 text-xs font-black text-navy-900">
          지식 그래프 이름
          <input
            aria-label="지식 그래프 이름"
            required
            maxLength={255}
            value={value.name}
            onChange={(event) => onChange({ ...value, name: event.target.value })}
            placeholder="예: 공급망 운영 지식 그래프"
          />
          <small className="font-normal text-slate-500">레지스트리와 검색에 표시되는 이름입니다.</small>
        </label>
        <label className="grid gap-1 text-xs font-black text-navy-900 md:col-span-2">
          설명
          <textarea
            aria-label="지식 그래프 설명"
            maxLength={2_000}
            rows={3}
            value={value.description ?? ''}
            onChange={(event) => onChange({ ...value, description: event.target.value })}
            placeholder="이 지식 그래프의 목적과 다루는 범위를 설명하세요."
          />
          <small className="font-normal text-slate-500">레지스트리 목록과 상세 화면에 표시됩니다.</small>
        </label>
        <label className="grid gap-1 text-xs font-black text-navy-900">
          <span className="flex items-center gap-1">
            API Endpoint 별칭
            <span
              className="inline-flex text-enterprise-blue"
              title="발행된 지식 그래프를 API와 GraphRAG 라우팅에서 안정적으로 찾는 URL-safe 식별자입니다."
              aria-label="API Endpoint 별칭 설명"
            >
              <Info size={12} aria-hidden="true" />
            </span>
          </span>
          <input
            aria-label="Endpoint alias"
            required
            maxLength={1_020}
            aria-invalid={Boolean(aliasError)}
            value={aliasInput}
            onChange={(event) => {
              const raw = event.target.value
              const nextAliases = parseEndpointAliases(raw)
              setAliasInput(raw)
              onChange({
                ...value,
                endpoint_alias: nextAliases[0] ?? '',
                endpoint_aliases: nextAliases,
              })
            }}
            placeholder="supply_chain_operations, operations_kg"
          />
          <small className={aliasError ? 'font-normal text-red-700' : 'font-normal text-slate-500'}>
            {aliasError ?? (
              'API·GraphRAG에서 이 자산을 찾는 고정 식별자입니다. 콤마로 여러 별칭을 '
              + '등록할 수 있고, 첫 번째 값이 발행 후 대표 주소가 됩니다.'
            )}
          </small>
        </label>
        <fieldset className="grid gap-1 border-0 p-0 text-xs font-black text-navy-900 md:col-span-2">
          <legend className="mb-1">업무 도메인</legend>
          <div className="grid gap-2 md:grid-cols-[2fr_1fr]">
            <select
              aria-label="업무 도메인"
              required
              disabled={domainsLoading}
              value={directDomain ? '__DIRECT__' : value.domain_id}
              onChange={(event) => {
                if (event.target.value === '__DIRECT__') {
                  setDirectDomain(true)
                  onChange({
                    ...value,
                    domain_id: '',
                    domain_source_version: '',
                  })
                  return
                }
                setDirectDomain(false)
                onDomainQueryChange('')
                const selected = domains.find((domain) => domain.id === event.target.value)
                onChange({
                  ...value,
                  domain_id: selected?.id ?? '',
                  domain_source_version: selected?.source_version ?? '',
                })
              }}
            >
              <option value="">{domainsLoading ? '도메인 불러오는 중…' : '업무 도메인 선택'}</option>
              {value.domain_id && !domains.some((domain) => domain.id === value.domain_id) && (
                <option value={value.domain_id}>현재 선택된 도메인 (version pinned)</option>
              )}
              {domains.map((domain) => (
                <option key={domain.id} value={domain.id}>{domain.display_name}</option>
              ))}
              <option value="__DIRECT__">직접 입력</option>
            </select>
            <div className="flex gap-1">
              <input
                aria-label="직접 입력 도메인명"
                className="min-w-0 flex-1"
                maxLength={200}
                disabled={!directDomain || domainCreating}
                value={domainQuery}
                onChange={(event) => onDomainQueryChange(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault()
                    void registerDirectDomain()
                  }
                }}
                placeholder={directDomain ? '새 도메인명' : '직접 입력 선택 시 활성화'}
              />
              <button
                type="button"
                className="button px-2"
                aria-label="직접 입력 도메인 등록"
                disabled={!directDomain || !domainQuery.trim() || domainCreating}
                onClick={() => void registerDirectDomain()}
              >
                <Plus size={13} />
              </button>
            </div>
          </div>
          <small className="font-normal text-slate-500">
            active DOMAIN UUID와 source version을 서버가 함께 고정합니다.
          </small>
          {domainsError && (
            <div
              className="mt-1 flex flex-wrap items-center justify-between gap-2 rounded border border-red-200 bg-red-50 p-2 text-red-900"
              role="alert"
            >
              <span className="font-normal">{domainsError}</span>
              <button
                type="button"
                className="button button-secondary px-2 py-1 text-[10px]"
                disabled={domainsLoading}
                onClick={onRetryDomains}
              >
                업무 도메인 다시 불러오기
              </button>
            </div>
          )}
        </fieldset>
        <label className="grid gap-1 text-xs font-black text-navy-900">
          보안등급
          <select
            aria-label="보안등급"
            value={value.classification}
            onChange={(event) => {
              onDomainQueryChange('')
              onChange({
                ...value,
                classification: event.target.value as KnowledgeClassification,
                domain_id: '',
                domain_source_version: '',
              })
            }}
          >
            {classifications.map((classification) => (
              <option key={classification}>{classification}</option>
            ))}
          </select>
          <small className="font-normal text-slate-500">T-Box와 A-Box가 넘을 수 없는 최대 분류 envelope입니다.</small>
        </label>
      </div>
      <div className="mt-5 flex items-start gap-2 rounded-enterprise border border-blue-200 bg-blue-50 p-3 text-xs text-blue-950">
        <Info size={15} className="mt-0.5 shrink-0" />
        <p className="m-0 leading-5">
          생성된 Draft는 자동 저장되며 명시적으로 Discard하기 전까지 만료되지 않습니다.
          변경 중인 입력은 먼저 브라우저의 동일 origin 전용 복구 큐에 기록되고,
          1.5초 디바운스 후 서버 Draft로 저장됩니다. {saveStatus}
        </p>
      </div>
      <footer className="mt-5 flex flex-wrap justify-end gap-2 border-t border-slate-200 pt-4">
        <button
          type="button"
          className="button button-secondary"
          disabled={busy || !valid}
          onClick={onSave}
        >
          <Save size={14} /> {busy ? '저장 중…' : '지금 저장'}
        </button>
        <button
          type="button"
          className="button"
          disabled={busy || !valid}
          onClick={onContinue}
        >
          저장 후 Graph Builder <ArrowRight size={14} />
        </button>
      </footer>
    </section>
  </div>
}
