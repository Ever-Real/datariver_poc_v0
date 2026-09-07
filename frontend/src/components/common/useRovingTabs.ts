import { useCallback, useRef, type KeyboardEvent } from 'react'

interface RovingTabsOptions<T extends string> {
  ids: readonly T[]
  activeId: T | undefined
  idPrefix: string
  onSelect: (id: T) => void
}

export function useRovingTabs<T extends string>({
  ids,
  activeId,
  idPrefix,
  onSelect,
}: RovingTabsOptions<T>) {
  const buttons = useRef(new Map<T, HTMLButtonElement>())
  const selectAndFocus = useCallback((id: T) => {
    onSelect(id)
    buttons.current.get(id)?.focus()
  }, [onSelect])
  const onKeyDown = useCallback((event: KeyboardEvent<HTMLButtonElement>, id: T) => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) {
      return
    }
    event.preventDefault()
    const current = Math.max(0, ids.indexOf(id))
    const nextIndex = event.key === 'Home'
      ? 0
      : event.key === 'End'
        ? ids.length - 1
        : event.key === 'ArrowLeft' || event.key === 'ArrowUp'
          ? (current - 1 + ids.length) % ids.length
          : (current + 1) % ids.length
    const next = ids[nextIndex]
    if (next) selectAndFocus(next)
  }, [ids, selectAndFocus])

  return {
    tabProps: (id: T) => ({
      id: `${idPrefix}-tab-${id}`,
      role: 'tab' as const,
      tabIndex: activeId === id ? 0 : -1,
      'aria-selected': activeId === id,
      'aria-controls': `${idPrefix}-panel-${id}`,
      ref: (element: HTMLButtonElement | null) => {
        if (element) buttons.current.set(id, element)
        else buttons.current.delete(id)
      },
      onKeyDown: (event: KeyboardEvent<HTMLButtonElement>) => onKeyDown(event, id),
    }),
    panelProps: (id: T) => ({
      id: `${idPrefix}-panel-${id}`,
      role: 'tabpanel' as const,
      'aria-labelledby': `${idPrefix}-tab-${id}`,
      tabIndex: 0,
    }),
  }
}
