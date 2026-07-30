import { Boxes, Database, Link2, Tags } from 'lucide-react'

export function KnowledgeInstanceManagementPage() {
  return (
    <section className="grid min-h-[520px] content-start gap-4 rounded-enterprise border border-slate-300 bg-white p-5 shadow-sm">
      <header className="flex items-start gap-3 border-b border-slate-200 pb-4">
        <span className="grid size-10 shrink-0 place-items-center rounded-enterprise bg-blue-50 text-enterprise-blue">
          <Boxes size={20} aria-hidden="true" />
        </span>
        <div>
          <span className="text-[10px] font-black tracking-[.14em] text-enterprise-blue uppercase">
            Knowledge instance workspace
          </span>
          <h2 className="my-1 text-lg font-black text-navy-900">
            인스턴스 관리 · 지식 자산 프로파일
          </h2>
          <p className="m-0 max-w-3xl text-xs leading-5 text-slate-500">
            발행된 T-Box Property URN을 기준으로 동의어, 단위, 데이터 프로필과 A-Box
            바인딩 상세를 관리할 독립 화면입니다.
          </p>
        </div>
      </header>
      <div className="grid gap-3 md:grid-cols-3">
        {[
          {
            icon: Link2,
            title: 'Property URN Resolver',
            text: '발행된 Studio Release의 Property URN을 선택하는 읽기 경계입니다.',
          },
          {
            icon: Tags,
            title: 'Semantic Profile',
            text: '동의어·단위·설명은 T-Box topology와 분리된 ETag aggregate로 관리합니다.',
          },
          {
            icon: Database,
            title: 'A-Box Binding',
            text: '프로필은 원본 인스턴스를 복제하지 않고 승인된 binding을 참조합니다.',
          },
        ].map((item) => {
          const Icon = item.icon
          return (
            <article key={item.title} className="rounded-enterprise border border-slate-200 bg-slate-50 p-4">
              <Icon size={18} className="text-enterprise-blue" aria-hidden="true" />
              <h3 className="mb-1 mt-3 text-xs font-black text-navy-900">{item.title}</h3>
              <p className="m-0 text-[11px] leading-5 text-slate-500">{item.text}</p>
            </article>
          )
        })}
      </div>
      <div className="grid place-items-center rounded-enterprise border border-dashed border-slate-300 bg-slate-50 px-6 py-14 text-center">
        <div className="max-w-2xl">
          <Link2 size={24} className="mx-auto text-slate-400" aria-hidden="true" />
          <h3 className="mb-2 mt-4 text-sm font-black text-navy-900">독립 CRUD 계약 진입점</h3>
          <p className="m-0 text-xs leading-5 text-slate-500">
            이 Route가 Property 프로파일의 독립 수명주기와 권한 경계입니다. 현재 승인된
            ADR은 프로파일 테이블을 아직 정의하지 않으므로 가짜 CRUD를 노출하지 않습니다.
            Graph Builder는 계속 이름과 기본 타입만 저장합니다.
          </p>
        </div>
      </div>
    </section>
  )
}
