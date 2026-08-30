import { Dialog } from '../../components/common/Dialog'
import { ApiError } from '../../api/client'
import { ErrorNotice } from '../../components/ErrorNotice'
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
  error,
  messages,
  onCancel,
  onConfirm,
}: {
  mutation?: PendingAdminMutation
  busy: boolean
  error?: unknown
  messages: AdminMessages
  onCancel: () => void
  onConfirm: () => void
}) {
  if (!mutation) return null
  const isConflict = error instanceof ApiError && error.problem?.status === 409

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
      <ErrorNotice error={error} />
      {isConflict && <p className="callout">{messages.versionConflict}</p>}
    </Dialog>
  )
}
