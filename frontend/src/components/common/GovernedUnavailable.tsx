import { LockKeyhole } from 'lucide-react'

interface GovernedUnavailableProps {
  title: string
  description: string
  compact?: boolean
}

export function GovernedUnavailable({ title, description, compact = false }: GovernedUnavailableProps) {
  return (
    <section
      role="status"
      className={`rounded-enterprise border border-amber-300 bg-amber-50 text-amber-950 ${compact ? 'px-3 py-2' : 'p-4'}`}
    >
      <div className="flex items-start gap-3">
        <LockKeyhole className="mt-0.5 shrink-0 text-amber-700" size={compact ? 15 : 18} aria-hidden="true" />
        <div>
          <h3 className="m-0 text-xs font-black">{title}</h3>
          <p className="mt-1 mb-0 text-[11px] leading-5 text-amber-900">{description}</p>
        </div>
      </div>
    </section>
  )
}
