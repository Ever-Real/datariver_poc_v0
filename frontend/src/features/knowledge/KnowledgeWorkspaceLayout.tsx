import { BookOpen, Boxes, MessageSquareText } from 'lucide-react'
import type { ReactNode } from 'react'
import type { Page } from '../../app/navigation'

export type KnowledgeWorkspaceSection = 'REGISTRY' | 'INSTANCES' | 'CHAT' | 'STUDIO'

const items: Array<{
  section: KnowledgeWorkspaceSection
  title: string
  description: string
  icon: typeof BookOpen
  nested?: boolean
}> = [
  { section: 'REGISTRY', title: '지식 레지스트리', description: '에셋 관리 및 이력', icon: BookOpen },
  {
    section: 'INSTANCES',
    title: '지식 인스턴스 관리',
    description: 'URN 기반 Property 상세 메타',
    icon: Boxes,
    nested: true,
  },
  { section: 'CHAT', title: '지식 챗', description: '별도 GraphRAG 질의', icon: MessageSquareText },
]

export function KnowledgeWorkspaceLayout({
  activeSection,
  onNavigate,
  children,
}: {
  activeSection: KnowledgeWorkspaceSection
  onNavigate: (page: Page) => void
  children: ReactNode
}) {
  const select = (section: KnowledgeWorkspaceSection) => {
    if (section === 'CHAT') {
      onNavigate('knowledge-chat')
      return
    }
    if (section === 'INSTANCES') {
      onNavigate('knowledge-instances')
      return
    }
    onNavigate('knowledge')
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
            className={`flex gap-3 rounded-enterprise border p-3 text-left transition-colors ${item.nested ? 'ml-5 border-l-4' : ''} ${active ? 'border-enterprise-blue bg-blue-50 text-navy-900' : 'border-slate-200 bg-slate-50 hover:border-slate-300 hover:bg-white'}`}
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
    </aside>
    <main className="min-w-0">{children}</main>
  </div>
}
