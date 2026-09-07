import type { ReactNode } from 'react'
import { Activity, Bot, DatabaseZap, FileCheck2, GitPullRequest, LibraryBig, Network, Search, Settings2, ShieldCheck, Share2 } from 'lucide-react'

const titleIcons: Record<string, ReactNode> = {
  AD: <Settings2 size={24} />, AI: <Bot size={24} />, API: <Share2 size={24} />,
  CR: <GitPullRequest size={24} />, DQ: <FileCheck2 size={24} />, GV: <ShieldCheck size={24} />,
  KG: <Network size={24} />, MO: <Activity size={24} />, OP: <Activity size={24} />,
  RG: <DatabaseZap size={24} />, SR: <Search size={24} />, PL: <LibraryBig size={24} />,
}

interface PageTitleProps {
  icon: string
  eyebrow?: string
  title: string
  description: string
  actions?: ReactNode
}

export function PageTitle({ icon, eyebrow, title, description, actions }: PageTitleProps) {
  return (
    <header className="page-title">
      <span className="page-title-icon" aria-hidden="true">{titleIcons[icon] ?? icon}</span>
      <div className="page-title-copy">
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1>{title}</h1>
        <p title={description}>{description}</p>
      </div>
      {actions && <div className="page-title-actions">{actions}</div>}
    </header>
  )
}
