import { ArrowRight, Info, Save } from 'lucide-react'
import type {
  KnowledgeClassification,
  KnowledgeStudioBasicInformation,
  KnowledgeStudioDomainOption,
} from '../knowledgeStudioApi'

const classifications: KnowledgeClassification[] = [
  'PUBLIC',
  'INTERNAL',
  'CONFIDENTIAL',
  'RESTRICTED',
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

export function basicInformationValid(value: KnowledgeStudioBasicInformation): boolean {
  return (
    value.name.length >= 1
    && value.name.length <= 255
    && value.name === value.name.trim()
    && !endpointAliasError(value.endpoint_alias)
    && Boolean(value.domain_id)
    && Boolean(value.domain_source_version)
  )
}

interface BasicInformationStepProps {
  value: KnowledgeStudioBasicInformation
  domains: KnowledgeStudioDomainOption[]
  domainsLoading: boolean
  domainQuery: string
  busy: boolean
  saveStatus: string
  onChange: (value: KnowledgeStudioBasicInformation) => void
  onDomainQueryChange: (value: string) => void
  onSave: () => void
  onContinue: () => void
}

export function BasicInformationStep({
  value,
  domains,
  domainsLoading,
  domainQuery,
  busy,
  saveStatus,
  onChange,
  onDomainQueryChange,
  onSave,
  onContinue,
}: BasicInformationStepProps) {
  const aliasError = value.endpoint_alias
    ? endpointAliasError(value.endpoint_alias)
    : undefined
  const valid = basicInformationValid(value)

  return <div className="mx-auto grid max-w-5xl gap-5">
    <section className="rounded-enterprise border border-slate-300 bg-white p-5 shadow-sm">
      <header className="mb-5">
        <span className="text-[10px] font-black tracking-[.14em] text-enterprise-blue uppercase">
          Step 1 · Asset contract
        </span>
        <h2 className="my-1 text-lg font-black text-navy-900">기본정보 등록</h2>
        <p className="m-0 max-w-3xl text-xs leading-5 text-slate-500">
          이름, API 식별자, 통제된 업무 도메인과 보안등급만 정의합니다.
          Graph type과 lifecycle은 서버 정책이 관리합니다.
        </p>
      </header>
      <div className="grid gap-4 md:grid-cols-2">
        <label className="grid gap-1 text-xs font-black text-navy-900">
          지식 그래프 이름
          <input
            aria-label="지식 그래프 이름"
            required
            maxLength={255}
            value={value.name}
            onChange={(event) => onChange({ ...value, name: event.target.value })}
            placeholder="예: 반도체 소재 지식 그래프"
          />
          <small className="font-normal text-slate-500">레지스트리와 검색에 표시되는 이름입니다.</small>
        </label>
        <label className="grid gap-1 text-xs font-black text-navy-900">
          Endpoint alias
          <input
            aria-label="Endpoint alias"
            required
            maxLength={100}
            aria-invalid={Boolean(aliasError)}
            value={value.endpoint_alias}
            onChange={(event) => onChange({ ...value, endpoint_alias: event.target.value })}
            placeholder="semiconductor_materials"
          />
          <small className={aliasError ? 'font-normal text-red-700' : 'font-normal text-slate-500'}>
            {aliasError ?? '발행 후 하위 그래프 REST/GraphQL API 식별자로 사용됩니다.'}
          </small>
        </label>
        <label className="grid gap-1 text-xs font-black text-navy-900">
          업무 도메인
          <input
            type="search"
            maxLength={200}
            aria-label="업무 도메인 검색"
            value={domainQuery}
            onChange={(event) => onDomainQueryChange(event.target.value)}
            placeholder="도메인 이름 검색"
          />
          <select
            aria-label="업무 도메인"
            required
            disabled={domainsLoading}
            value={value.domain_id}
            onChange={(event) => {
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
          </select>
          <small className="font-normal text-slate-500">
            active DOMAIN UUID와 source version을 서버가 함께 고정합니다.
          </small>
        </label>
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
