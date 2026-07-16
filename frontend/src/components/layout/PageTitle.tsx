import type { ReactNode } from 'react'

interface PageTitleProps {
  icon: string
  eyebrow: string
  title: string
  description: string
  actions?: ReactNode
}

export function PageTitle({ icon, eyebrow, title, description, actions }: PageTitleProps) {
  return (
    <header className="page-title">
      <span className="page-title-icon" aria-hidden="true">{icon}</span>
      <div className="page-title-copy">
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p title={description}>{description}</p>
      </div>
      {actions && <div className="page-title-actions">{actions}</div>}
    </header>
  )
}
