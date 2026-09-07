import { useCallback, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import type { ApiClient } from '../../api/client'
import { CatalogDetailPane } from '../catalog/CatalogDetailPane'

export function EvidenceModal({
  assetId,
  client,
  onClose,
  onSelectAsset,
  returnFocus,
}: {
  assetId: string
  client: ApiClient
  onClose: () => void
  onSelectAsset: (assetId: string) => void
  returnFocus: React.RefObject<HTMLButtonElement | null>
}) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const close = useCallback(() => {
    onClose()
    globalThis.requestAnimationFrame(() => returnFocus.current?.focus())
  }, [onClose, returnFocus])

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    const focusable = dialog.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), '
      + 'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )
    ;(focusable[0] ?? dialog).focus()
    const containFocus = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        close()
        return
      }
      if (event.key !== 'Tab' || focusable.length === 0) return
      const first = focusable.item(0)
      const last = focusable.item(focusable.length - 1)
      if (!first || !last) return
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    dialog.addEventListener('keydown', containFocus)
    return () => dialog.removeEventListener('keydown', containFocus)
  }, [close])

  if (typeof document === 'undefined') return null
  return createPortal(
    <div
      aria-label="근거 테이블 상세와 Lineage"
      aria-modal="true"
      className="chat-evidence-modal"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) close()
      }}
      ref={dialogRef}
      role="dialog"
      tabIndex={-1}
    >
      <div className="chat-evidence-modal-surface">
        <CatalogDetailPane
          asModal
          assetId={assetId}
          client={client}
          key={assetId}
          onClose={close}
          onSelectAsset={onSelectAsset}
        />
      </div>
    </div>,
    document.body,
  )
}
