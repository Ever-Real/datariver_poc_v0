import { useMemo, useState } from 'react'
import { ArrowRight, Info, Save } from 'lucide-react'

const classifications = ['PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED'] as const

function endpointAliasError(value: string): string | undefined {
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

export function BasicInformationStep() {
  const [name, setName] = useState('')
  const [endpointAlias, setEndpointAlias] = useState('')
  const [classification, setClassification] = useState<(typeof classifications)[number]>('INTERNAL')
  const aliasError = useMemo(
    () => endpointAlias ? endpointAliasError(endpointAlias) : undefined,
    [endpointAlias],
  )

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
            required
            maxLength={255}
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="예: 반도체 소재 지식 그래프"
          />
          <small className="font-normal text-slate-500">레지스트리와 검색에 표시되는 이름입니다.</small>
        </label>
        <label className="grid gap-1 text-xs font-black text-navy-900">
          Endpoint alias
          <input
            required
            maxLength={100}
            aria-invalid={Boolean(aliasError)}
            value={endpointAlias}
            onChange={(event) => setEndpointAlias(event.target.value)}
            placeholder="semiconductor_materials"
          />
          <small className={aliasError ? 'font-normal text-red-700' : 'font-normal text-slate-500'}>
            {aliasError ?? '발행 후 하위 그래프 REST/GraphQL API 식별자로 사용됩니다.'}
          </small>
        </label>
        <label className="grid gap-1 text-xs font-black text-navy-900">
          업무 도메인
          <select disabled value="">
            <option value="">통제 vocabulary 조회 API 연결 전</option>
          </select>
          <small className="font-normal text-slate-500">
            브라우저 임의 문자열 대신 active DOMAIN UUID와 source version을 서버에서 선택합니다.
          </small>
        </label>
        <label className="grid gap-1 text-xs font-black text-navy-900">
          보안등급
          <select
            value={classification}
            onChange={(event) => setClassification(
              event.target.value as (typeof classifications)[number],
            )}
          >
            {classifications.map((value) => <option key={value}>{value}</option>)}
          </select>
          <small className="font-normal text-slate-500">T-Box와 A-Box가 넘을 수 없는 최대 분류 envelope입니다.</small>
        </label>
      </div>
      <div className="mt-5 flex items-start gap-2 rounded-enterprise border border-blue-200 bg-blue-50 p-3 text-xs text-blue-950">
        <Info size={15} className="mt-0.5 shrink-0" />
        <p className="m-0 leading-5">
          생성된 Draft는 자동 저장되며 명시적으로 Discard하기 전까지 만료되지 않습니다.
          현재 스캐폴드는 저장 계약을 선행 표시하며 Studio Draft command API 연결 전에는
          저장 성공을 가장하지 않습니다.
        </p>
      </div>
      <footer className="mt-5 flex flex-wrap justify-end gap-2 border-t border-slate-200 pt-4">
        <button type="button" className="button button-secondary" disabled title="Studio Draft command API 연결 후 활성화됩니다.">
          <Save size={14} /> 임시 저장
        </button>
        <button type="button" className="button" disabled title="서버 Draft 생성과 domain pin이 완료되어야 이동할 수 있습니다.">
          Draft 생성 후 Graph Builder <ArrowRight size={14} />
        </button>
      </footer>
    </section>
  </div>
}
