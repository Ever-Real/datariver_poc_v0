import { Check } from 'lucide-react'

export interface WorkflowStep {
  id: string
  label: string
  description?: string
}

interface WorkflowStepperProps {
  steps: WorkflowStep[]
  currentIndex: number
  selectedIndex?: number
  onSelect?: (index: number) => void
  allowFutureInspection?: boolean
}

export function WorkflowStepper({
  steps,
  currentIndex,
  selectedIndex = currentIndex,
  onSelect,
  allowFutureInspection = false,
}: WorkflowStepperProps) {
  return (
    <nav aria-label="진행 단계" className="w-full rounded-enterprise border border-slate-300 bg-white px-4 py-3 shadow-sm">
      <ol className="grid grid-cols-1 gap-2 md:grid-cols-4">
        {steps.map((step, index) => {
          const complete = index < currentIndex
          const active = index === currentIndex
          const selected = index === selectedIndex
          const selectable = Boolean(onSelect) && (allowFutureInspection || index <= currentIndex)
          const content = (
            <>
              <span
                aria-hidden="true"
                className={`grid h-8 w-8 shrink-0 place-items-center rounded-full border text-xs font-black ${
                  complete
                    ? 'border-emerald-700 bg-emerald-700 text-white'
                    : active
                      ? 'border-enterprise-blue bg-enterprise-blue text-white'
                      : 'border-slate-300 bg-slate-100 text-slate-500'
                }`}
              >
                {complete ? <Check size={15} strokeWidth={3} /> : index + 1}
              </span>
              <span className="min-w-0 text-left">
                <span className={`block truncate text-xs font-black ${active ? 'text-navy-900' : 'text-slate-600'}`}>
                  {step.label}
                </span>
                {step.description && <span className="mt-0.5 block truncate text-[10px] text-slate-500">{step.description}</span>}
              </span>
            </>
          )
          return (
            <li key={step.id} className={`relative rounded-enterprise ${selected ? 'ring-2 ring-enterprise-blue/30' : ''}`}>
              {selectable ? (
                <button
                  type="button"
                  aria-current={active ? 'step' : undefined}
                  aria-pressed={selected}
                  className="flex min-h-12 w-full items-center gap-3 rounded-enterprise px-2 py-1.5 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-enterprise-blue"
                  onClick={() => onSelect?.(index)}
                >
                  {content}
                </button>
              ) : (
                <div aria-current={active ? 'step' : undefined} className="flex min-h-12 items-center gap-3 px-2 py-1.5">
                  {content}
                </div>
              )}
              {index < steps.length - 1 && (
                <span aria-hidden="true" className="absolute left-[calc(100%-2px)] top-1/2 hidden h-px w-2 bg-slate-300 md:block" />
              )}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
