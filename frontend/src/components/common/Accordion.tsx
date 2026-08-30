import { useId, type ReactNode } from 'react'

interface AccordionItemProps {
  itemId: string
  focusKey?: string
  title: ReactNode
  summary?: ReactNode
  expanded: boolean
  children: ReactNode
  onToggle: () => void
}

export function AccordionItem({
  itemId,
  focusKey,
  title,
  summary,
  expanded,
  children,
  onToggle,
}: AccordionItemProps) {
  const prefix = useId()
  const buttonId = `${prefix}-${itemId}-button`
  const panelId = `${prefix}-${itemId}-panel`

  return (
    <section className={`accordion-item ${expanded ? 'expanded' : ''}`}>
      <h3 className="accordion-heading">
        <button
          id={buttonId}
          data-catalog-focus-key={focusKey}
          type="button"
          aria-expanded={expanded}
          aria-controls={panelId}
          onClick={onToggle}
        >
          <span className="accordion-title">{title}</span>
          {summary && <span className="accordion-summary">{summary}</span>}
          <span className="accordion-indicator" aria-hidden="true">{expanded ? '−' : '+'}</span>
        </button>
      </h3>
      <div
        id={panelId}
        role="region"
        aria-labelledby={buttonId}
        className="accordion-panel"
        hidden={!expanded}
      >
        {children}
      </div>
    </section>
  )
}
