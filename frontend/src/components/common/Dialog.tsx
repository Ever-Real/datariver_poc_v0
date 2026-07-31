import { useEffect, useId, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

type DialogCloseReason = 'BACKDROP' | 'CANCEL' | 'CLOSE_BUTTON'

interface DialogProps {
  open: boolean
  title: string
  description?: string
  size?: 'medium' | 'large' | 'workspace'
  compactHeight?: boolean
  children: ReactNode
  footer?: ReactNode
  onRequestClose: (reason: DialogCloseReason) => void
}

const FOCUSABLE = [
  'a[href]', 'button:not([disabled])', 'input:not([disabled])', 'select:not([disabled])',
  'textarea:not([disabled])', '[tabindex]:not([tabindex="-1"])',
].join(',')

export function Dialog({
  open,
  title,
  description,
  size = 'medium',
  compactHeight = false,
  children,
  footer,
  onRequestClose,
}: DialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const onRequestCloseRef = useRef(onRequestClose)
  const titleId = useId()
  const descriptionId = useId()

  // Consumers often create their close handler inline.  Keep the current
  // handler without tearing down and reopening a modal on every keystroke.
  // Reopening would restore focus and then move it to the first control.
  useEffect(() => {
    onRequestCloseRef.current = onRequestClose
  }, [onRequestClose])

  useEffect(() => {
    if (!open) return
    const dialog = dialogRef.current
    if (!dialog) return
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    if (typeof dialog.showModal === 'function') dialog.showModal()
    else dialog.setAttribute('open', '')

    const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE))
    ;(focusable[0] ?? dialog).focus()

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onRequestCloseRef.current('CANCEL')
        return
      }
      if (event.key !== 'Tab') return
      const candidates = Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE))
      if (candidates.length === 0) {
        event.preventDefault()
        dialog.focus()
        return
      }
      const first = candidates[0]
      const last = candidates[candidates.length - 1]
      if (!first || !last) return
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault(); last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus()
      }
    }
    dialog.addEventListener('keydown', handleKeyDown)
    return () => {
      dialog.removeEventListener('keydown', handleKeyDown)
      if (dialog.open && typeof dialog.close === 'function') dialog.close()
      else dialog.removeAttribute('open')
      previousFocus?.focus()
    }
  }, [open])

  if (!open) return null
  return createPortal(
    <dialog
      ref={dialogRef}
      className={`app-dialog app-dialog-${size}${compactHeight ? ' app-dialog-fit' : ''}`}
      aria-modal="true"
      aria-labelledby={titleId}
      aria-describedby={description ? descriptionId : undefined}
      tabIndex={-1}
      onCancel={(event) => { event.preventDefault(); onRequestCloseRef.current('CANCEL') }}
      onClick={(event) => { if (event.target === event.currentTarget) onRequestCloseRef.current('BACKDROP') }}
    >
      <section className="app-dialog-surface">
        <header className="app-dialog-header">
          <div>
            <h2 id={titleId}>{title}</h2>
            {description && <p id={descriptionId}>{description}</p>}
          </div>
          <button type="button" className="app-dialog-close" aria-label={`${title} 닫기`} onClick={() => onRequestCloseRef.current('CLOSE_BUTTON')}>×</button>
        </header>
        <div className="app-dialog-body">{children}</div>
        {footer && <footer className="app-dialog-footer">{footer}</footer>}
      </section>
    </dialog>,
    document.body,
  )
}
