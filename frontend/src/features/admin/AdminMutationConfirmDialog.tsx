import { useEffect, useRef } from 'react'
import type { AdminMessages } from './messages'

export interface PendingAdminMutation {
  title: string
  summary: string[]
  execute: () => Promise<void>
}

export function AdminMutationConfirmDialog({
  mutation,
  busy,
  messages,
  onCancel,
  onConfirm,
}: {
  mutation?: PendingAdminMutation
  busy: boolean
  messages: AdminMessages
  onCancel: () => void
  onConfirm: () => void
}) {
  const cancelRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!mutation) return
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    cancelRef.current?.focus()
    return () => previous?.focus()
  }, [mutation])

  useEffect(() => {
    if (!mutation) return
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) onCancel()
    }
    window.addEventListener('keydown', escape)
    return () => window.removeEventListener('keydown', escape)
  }, [busy, mutation, onCancel])

  if (!mutation) return null
  return (
    <div className="dialog-backdrop">
      <section className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="admin-confirm-title">
        <p className="eyebrow">{messages.confirmTitle}</p>
        <h3 id="admin-confirm-title">{mutation.title}</h3>
        <ul>{mutation.summary.map((line) => <li key={line}>{line}</li>)}</ul>
        <p className="callout">{messages.versionConflict}</p>
        <div className="action-row">
          <button ref={cancelRef} className="button button-secondary" disabled={busy} onClick={onCancel}>
            {messages.cancel}
          </button>
          <button className="button" disabled={busy} onClick={onConfirm}>
            {busy ? messages.working : messages.confirm}
          </button>
        </div>
      </section>
    </div>
  )
}
