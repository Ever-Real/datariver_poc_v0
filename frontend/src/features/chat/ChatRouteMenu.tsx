import { useEffect, useRef, useState } from 'react'
import { Check, ChevronDown, Route } from 'lucide-react'
import type { ChatMode } from '../../api/types'

export interface ChatRouteOption {
  value: ChatMode
  label: string
  description: string
}

export function ChatRouteMenu({
  disabled,
  onChange,
  options,
  value,
}: {
  disabled: boolean
  onChange: (value: ChatMode) => void
  options: ChatRouteOption[]
  value: ChatMode
}) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const selected = options.find((option) => option.value === value) ?? options[0]

  useEffect(() => {
    if (!open) return
    const closeOutside = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', closeOutside)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('mousedown', closeOutside)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [open])

  return (
    <div className="chat-route-menu" ref={rootRef}>
      <span className="chat-composer-label" id="chat-route-label">검색 경로</span>
      <button
        aria-label="검색 경로"
        aria-controls="chat-route-options"
        aria-expanded={open}
        aria-haspopup="listbox"
        className="chat-route-trigger"
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
        type="button"
      >
        <Route aria-hidden="true" size={15} />
        <span id="chat-route-value">{selected?.label ?? value}</span>
        <ChevronDown aria-hidden="true" className={open ? 'rotate-180' : ''} size={14} />
      </button>
      {open && (
        <div
          aria-label="검색 경로 선택"
          className="chat-route-options"
          id="chat-route-options"
          role="listbox"
        >
          {options.map((option) => (
            <button
              aria-label={`검색 경로 ${option.label}`}
              aria-selected={option.value === value}
              className={option.value === value ? 'is-selected' : ''}
              key={option.value}
              onClick={() => {
                onChange(option.value)
                setOpen(false)
              }}
              role="option"
              type="button"
            >
              <span>
                <strong>{option.label}</strong>
                <small>{option.description}</small>
              </span>
              {option.value === value && <Check aria-hidden="true" size={15} />}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
