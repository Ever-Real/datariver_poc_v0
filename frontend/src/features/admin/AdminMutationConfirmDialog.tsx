import { Dialog } from '../../components/common/Dialog'
import type { AdminMessages } from './messages'

export interface PendingAdminMutation {
  title: string
  summary: string[]
  execute: () => Promise<void>
  contextEpoch?: string
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
  if (!mutation) return null
  return (
    <Dialog
      open
      title={mutation.title}
      description={messages.confirmTitle}
      onRequestClose={() => { if (!busy) onCancel() }}
      footer={<>
        <button className="button button-secondary" disabled={busy} onClick={onCancel}>
          {messages.cancel}
        </button>
        <button className="button" disabled={busy} onClick={onConfirm}>
          {busy ? messages.working : messages.confirm}
        </button>
      </>}
    >
      <ul>{mutation.summary.map((line) => <li key={line}>{line}</li>)}</ul>
      <p className="callout">{messages.versionConflict}</p>
    </Dialog>
  )
}
