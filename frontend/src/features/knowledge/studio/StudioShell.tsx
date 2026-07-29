import { ArrowLeft, Check, Database, Network, Settings2 } from 'lucide-react'
import { useEffect, useRef, type ReactNode } from 'react'
import type { KnowledgeStudioStep } from '../routes/knowledgeLocation'

const steps: Array<{
  id: KnowledgeStudioStep
  number: number
  title: string
  description: string
  icon: typeof Settings2
}> = [
  { id: 'basic', number: 1, title: '기본정보', description: 'Asset identity와 정책', icon: Settings2 },
  { id: 'tbox', number: 2, title: 'Graph Builder', description: 'T-Box schema', icon: Network },
  { id: 'abox', number: 3, title: 'Data Enricher', description: 'A-Box mapping', icon: Database },
]

export function StudioShell({
  step,
  draftId,
  saveStatus,
  onBack,
  children,
}: {
  step: KnowledgeStudioStep
  draftId?: string
  saveStatus?: string
  onBack: () => void
  children: ReactNode
}) {
  const activeIndex = steps.findIndex((item) => item.id === step)
  const dialogRef = useRef<HTMLElement>(null)
  const onBackRef = useRef(onBack)

  useEffect(() => {
    onBackRef.current = onBack
  }, [onBack])

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    dialog.focus()
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onBackRef.current()
        return
      }
      if (event.key !== 'Tab') return
      const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), '
        + 'textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
      ))
      if (focusable.length === 0) {
        event.preventDefault()
        dialog.focus()
        return
      }
      const first = focusable[0]
      const last = focusable.at(-1)
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last?.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first?.focus()
      }
    }
    dialog.addEventListener('keydown', onKeyDown)
    return () => dialog.removeEventListener('keydown', onKeyDown)
  }, [])

  return <section
    ref={dialogRef}
    role="dialog"
    aria-modal="true"
    aria-labelledby="knowledge-studio-title"
    tabIndex={-1}
    className="min-h-[calc(100vh-190px)] overflow-hidden rounded-enterprise border border-slate-300 bg-slate-50 shadow-sm outline-none"
  >
    <header className="border-b border-slate-300 bg-white px-5 py-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <button type="button" className="button button-secondary" onClick={onBack}>
            <ArrowLeft size={15} /> 레지스트리
          </button>
          <div className="min-w-0">
            <span className="text-[10px] font-black tracking-[.16em] text-enterprise-blue uppercase">
              Full-screen Studio Mode
            </span>
            <h1 id="knowledge-studio-title" className="my-1 truncate text-xl font-black text-navy-900">Knowledge Studio</h1>
            <p className="m-0 text-xs text-slate-500">
              {draftId ? `Draft ${draftId}` : '새 Asset · 저장 전'}
            </p>
          </div>
        </div>
        <span className="badge badge-soft" title={saveStatus}>
          {draftId ? '자동 저장 대상' : '초안 생성 전'}
        </span>
      </div>
      <ol className="mt-5 grid gap-2 p-0 md:grid-cols-3" aria-label="Knowledge Studio 단계">
        {steps.map((item, index) => {
          const Icon = item.icon
          const active = item.id === step
          const completed = index < activeIndex
          return <li
            key={item.id}
            aria-current={active ? 'step' : undefined}
            className={`flex items-center gap-3 rounded-enterprise border px-4 py-3 ${
              active
                ? 'border-enterprise-blue bg-blue-50 text-navy-900'
                : completed
                  ? 'border-emerald-300 bg-emerald-50 text-emerald-950'
                  : 'border-slate-200 bg-slate-50 text-slate-500'
            }`}
          >
            <span className={`grid size-8 shrink-0 place-items-center rounded-full ${
              active ? 'bg-enterprise-blue text-white' : completed ? 'bg-emerald-600 text-white' : 'bg-slate-200'
            }`}>
              {completed ? <Check size={15} /> : <Icon size={15} />}
            </span>
            <span>
              <small className="block text-[9px] font-black tracking-wide uppercase">Step {item.number}</small>
              <strong className="block text-xs">{item.title}</strong>
              <small className="block text-[10px]">{item.description}</small>
            </span>
          </li>
        })}
      </ol>
    </header>
    <div className="p-5">{children}</div>
  </section>
}
