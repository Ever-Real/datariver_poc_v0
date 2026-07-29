import { Boxes, Link2 } from 'lucide-react'

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
          <h2 className="my-1 text-lg font-black text-navy-900">지식 인스턴스 관리</h2>
          <p className="m-0 max-w-3xl text-xs leading-5 text-slate-500">
            발행된 T-Box Property URN을 기준으로 동의어, 단위, 데이터 프로필과 A-Box
            바인딩 상세를 관리할 독립 화면입니다.
          </p>
        </div>
      </header>
      <div className="grid place-items-center rounded-enterprise border border-dashed border-slate-300 bg-slate-50 px-6 py-20 text-center">
        <div className="max-w-xl">
          <Link2 size={26} className="mx-auto text-slate-400" aria-hidden="true" />
          <h3 className="mb-2 mt-4 text-sm font-black text-navy-900">URN 참조 관리 영역</h3>
          <p className="m-0 text-xs leading-5 text-slate-500">
            현재 Phase에서는 Route와 독립 수명주기 경계만 제공합니다. Graph Builder는
            Property 이름과 타입만 유지하며, 세부 프로필은 향후 별도 권한·ETag 계약을
            통해 이 화면에 연결됩니다.
          </p>
        </div>
      </div>
    </section>
  )
}
