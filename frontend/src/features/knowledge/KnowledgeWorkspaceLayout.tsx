import { BookOpen, DatabaseZap, MessageSquareText } from 'lucide-react'
import type { ReactNode } from 'react'
import type { Page } from '../../app/navigation'

export type KnowledgeWorkspaceSection = 'REGISTRY' | 'INGESTION' | 'CHAT'

const items: Array<{
  section: KnowledgeWorkspaceSection
  title: string
  description: string
  icon: typeof BookOpen
}> = [
  { section: 'REGISTRY', title: '지식 레지스트리', description: '에셋 관리 및 이력', icon: BookOpen },
  { section: 'INGESTION', title: '데이터 적재', description: '온톨로지 정의 및 머지', icon: DatabaseZap },
  { section: 'CHAT', title: '지식 챗', description: '별도 GraphRAG 질의', icon: MessageSquareText },
]

export function KnowledgeWorkspaceLayout({
  activeSection,
  onLocalSection,
  onNavigate,
  children,
}: {
  activeSection: KnowledgeWorkspaceSection
  onLocalSection?: (section: Exclude<KnowledgeWorkspaceSection, 'CHAT'>) => void
  onNavigate: (page: Page) => void
  children: ReactNode
}) {
  const select = (section: KnowledgeWorkspaceSection) => {
    if (section === 'CHAT') {
      onNavigate('knowledge-chat')
      return
    }
    if (activeSection === 'CHAT') {
      onNavigate('knowledge')
      return
    }
    onLocalSection?.(section)
  }

  return <div className="grid gap-4 xl:grid-cols-[280px_minmax(0,1fr)]">
    <aside className="grid content-start gap-3 rounded-enterprise border border-slate-300 bg-white p-4 text-slate-700 shadow-sm">
      <div>
        <span className="text-[10px] font-black tracking-[.16em] text-enterprise-blue uppercase">Knowledge workspace</span>
        <h2 className="my-1 text-base font-black text-navy-900">작업 메뉴</h2>
      </div>
      <nav className="grid gap-2" aria-label="지식관리 메뉴">
        {items.map((item) => {
          const Icon = item.icon
          const active = activeSection === item.section
          return <button
            key={item.section}
            type="button"
            aria-current={active ? 'page' : undefined}
            className={`flex gap-3 rounded-enterprise border p-3 text-left transition-colors ${active ? 'border-enterprise-blue bg-blue-50 text-navy-900' : 'border-slate-200 bg-slate-50 hover:border-slate-300 hover:bg-white'}`}
            onClick={() => select(item.section)}
          >
            <Icon size={18} className={`mt-0.5 shrink-0 ${active ? 'text-enterprise-blue' : 'text-slate-500'}`} />
            <span>
              <strong className="block text-xs">{item.title}</strong>
              <small className="mt-1 block leading-4 text-slate-500">{item.description}</small>
            </span>
          </button>
        })}
      </nav>
      {activeSection === 'INGESTION' && <div className="mt-4 border-t border-slate-200 pt-4 text-[10px] leading-5 text-slate-500">작업 모드는 본문에서 MODE A · Ontology Builder 또는 MODE B · Data Enricher로 선택합니다.</div>}
    </aside>
    <main className="min-w-0">{children}</main>
  </div>
}
