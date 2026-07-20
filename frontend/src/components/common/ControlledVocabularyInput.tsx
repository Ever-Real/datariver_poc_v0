import { ChevronLeft, ChevronRight, Plus } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { ApiClient } from '../../api/client'
import type { CatalogVocabulary } from '../../api/types'

export type VocabularyKind = 'TAG' | 'TERM' | 'DOMAIN'

interface BadgeScrollerProps {
  values: readonly string[]
  label: string
  onRemove?: (value: string) => void
  className?: string
  controls?: boolean
}

export function BadgeScroller({ values, label, onRemove, className = '', controls = true }: BadgeScrollerProps) {
  const trackRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<{ pointerId: number; startX: number; startScrollLeft: number } | undefined>(undefined)

  const scroll = (left: number) => trackRef.current?.scrollBy({ left, behavior: 'smooth' })
  const startDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    if ((event.target as HTMLElement).closest('button')) return
    const track = trackRef.current
    if (!track) return
    dragRef.current = { pointerId: event.pointerId, startX: event.clientX, startScrollLeft: track.scrollLeft }
    track.setPointerCapture(event.pointerId)
  }
  const moveDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current
    const track = trackRef.current
    if (!drag || drag.pointerId !== event.pointerId || !track) return
    track.scrollLeft = drag.startScrollLeft - (event.clientX - drag.startX)
  }
  const endDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    if (dragRef.current?.pointerId !== event.pointerId) return
    dragRef.current = undefined
    if (trackRef.current?.hasPointerCapture(event.pointerId)) trackRef.current.releasePointerCapture(event.pointerId)
  }

  if (!values.length) return <span className={`badge-scroller-empty ${className}`.trim()}>—</span>

  return <div className={`badge-scroller ${className}`.trim()} aria-label={label}>
    {controls && <button aria-label={`${label} 이전 항목`} className="badge-scroller-arrow badge-scroller-arrow-left" onClick={(event) => { event.stopPropagation(); scroll(-140) }} type="button"><ChevronLeft size={12} /></button>}
    <div
      className="badge-scroller-track"
      onPointerCancel={endDrag}
      onPointerDown={startDrag}
      onPointerMove={moveDrag}
      onPointerUp={endDrag}
      ref={trackRef}
    >
      {values.map((value) => <span className="badge badge-soft" key={value} title={value}>{value}{onRemove && <button aria-label={`${value} 제거`} onClick={(event) => { event.stopPropagation(); onRemove(value) }} onPointerDown={(event) => event.stopPropagation()} type="button">×</button>}</span>)}
    </div>
    {controls && <button aria-label={`${label} 다음 항목`} className="badge-scroller-arrow badge-scroller-arrow-right" onClick={(event) => { event.stopPropagation(); scroll(140) }} type="button"><ChevronRight size={12} /></button>}
  </div>
}

export function ControlledVocabularyInput({
  client,
  kind,
  values,
  onChange,
  label,
  maxItems = 100,
}: {
  client: ApiClient
  kind: VocabularyKind
  values: string[]
  onChange: (values: string[]) => void
  label: string
  maxItems?: number
}) {
  const rootRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const trackRef = useRef<HTMLDivElement>(null)
  const requestRef = useRef<AbortController | undefined>(undefined)
  const canProposeNew = kind === 'TAG' || kind === 'TERM'
  const [input, setInput] = useState('')
  const [options, setOptions] = useState<string[]>([])
  const [open, setOpen] = useState(false)
  const [loadingOptions, setLoadingOptions] = useState(false)
  const [lookupFailed, setLookupFailed] = useState(false)
  const [menuPosition, setMenuPosition] = useState<{ left: number; top: number; width: number }>()

  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    requestRef.current?.abort()
    requestRef.current = controller
    const query = input.trim()
    setLoadingOptions(true)
    setLookupFailed(false)
    const timeout = window.setTimeout(() => {
      const parameters = new URLSearchParams({ kind })
      if (query) parameters.set('q', query)
      parameters.set('limit', '12')
      void client.request<CatalogVocabulary>(`/catalog/vocabulary?${parameters.toString()}`, { signal: controller.signal })
        .then((result) => {
          if (!controller.signal.aborted) setOptions(result.items.filter((item) => !values.includes(item)))
        })
        .catch(() => {
          if (!controller.signal.aborted) {
            setOptions([])
            setLookupFailed(true)
          }
        })
        .finally(() => { if (!controller.signal.aborted) setLoadingOptions(false) })
    }, query ? 160 : 0)
    return () => { controller.abort(); window.clearTimeout(timeout) }
  }, [client, input, kind, open, values])

  useEffect(() => () => requestRef.current?.abort(), [])

  useEffect(() => {
    if (!open) { setMenuPosition(undefined); return }
    const updatePosition = () => {
      const rectangle = rootRef.current?.getBoundingClientRect()
      if (!rectangle) return
      setMenuPosition({ left: rectangle.left, top: rectangle.bottom + 2, width: Math.max(rectangle.width, 220) })
    }
    updatePosition()
    window.addEventListener('resize', updatePosition)
    window.addEventListener('scroll', updatePosition, true)
    return () => { window.removeEventListener('resize', updatePosition); window.removeEventListener('scroll', updatePosition, true) }
  }, [open])

  const appendValues = (candidates: readonly string[]): boolean => {
    const available = Array.from(new Set(candidates.map((value) => value.trim()).filter(Boolean)))
      .filter((value) => !values.includes(value))
      .slice(0, Math.max(0, maxItems - values.length))
    if (!available.length) return false
    onChange([...values, ...available])
    return true
  }
  const commit = (value: string) => {
    if (!appendValues([value])) return
    setInput('')
    setOptions([])
    setOpen(false)
    inputRef.current?.focus()
  }
  const selectFirst = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (!input.trim()) return
    if (event.key === ',') {
      event.preventDefault()
      if (canProposeNew) commit(input)
      return
    }
    if (!['Enter', 'Tab'].includes(event.key)) return
    event.preventDefault()
    if (options[0]) {
      commit(options[0])
    } else if (canProposeNew) {
      commit(input.trim())
    }
  }
  const scrollValues = (left: number) => {
    const track = trackRef.current
    if (!track) return
    if (typeof track.scrollBy === 'function') {
      track.scrollBy({ left, behavior: 'smooth' })
    } else {
      track.scrollLeft += left
    }
  }
  const menu = open && menuPosition && typeof document !== 'undefined'
    ? createPortal(
      <div className="controlled-vocabulary-menu" role="listbox" aria-label={`${label} 검색 결과`} style={menuPosition}>
        <input aria-label={label} autoFocus onBlur={() => window.setTimeout(() => setOpen(false), 120)} onChange={(event) => {
          const chunks = event.target.value.split(',')
          if (chunks.length > 1 && canProposeNew) appendValues(chunks.slice(0, -1))
          setInput(chunks.at(-1) ?? '')
        }} onKeyDown={selectFirst} placeholder="등록된 항목 검색 또는 신규 입력" ref={inputRef} value={input} />
        {input.trim() ? <>
          {loadingOptions && <p role="status">등록된 항목을 찾는 중입니다.</p>}
          {!loadingOptions && options.map((option) => <button key={option} onMouseDown={(event) => { event.preventDefault(); commit(option) }} role="option" type="button">{option}</button>)}
          {!loadingOptions && !options.length && <p role="status">{lookupFailed ? '등록된 항목을 불러오지 못했습니다. 키워드를 다시 입력해 주세요.' : `등록된 ${kind === 'TAG' ? 'Tag' : kind === 'TERM' ? 'Term' : 'Domain'}이 없습니다.`}</p>}
          {canProposeNew && <button aria-label={`${input.trim()} 신규 제안값으로 추가`} onMouseDown={(event) => { event.preventDefault(); commit(input.trim()) }} role="option" type="button"><strong>{input.trim()}</strong> 신규 제안값으로 추가</button>}
        </> : <>
          {loadingOptions && <p role="status">등록된 항목을 불러오는 중입니다.</p>}
          {!loadingOptions && options.map((option) => <button key={option} onMouseDown={(event) => { event.preventDefault(); commit(option) }} role="option" type="button">{option}</button>)}
          {!loadingOptions && !options.length && <p role="status">{lookupFailed ? '등록된 항목을 불러오지 못했습니다. 키워드를 입력해 다시 시도하세요.' : '키워드로 등록된 항목을 찾거나 새 제안값을 입력하세요.'}</p>}
        </>}
      </div>,
      document.body,
    )
    : null

  return <div className="controlled-vocabulary-input" ref={rootRef}>
    <div className="controlled-vocabulary-row">
      <button aria-label={`${label} 이전 항목`} className="controlled-vocabulary-arrow" disabled={!values.length} onClick={() => scrollValues(-140)} type="button"><ChevronLeft size={10} /></button>
      <div aria-label={`${label} 선택된 값`} className="controlled-vocabulary-track" ref={trackRef}>
        {values.map((value) => <span className="badge badge-soft" key={value} title={value}>{value}<button aria-label={`${value} 제거`} onClick={(event) => { event.stopPropagation(); onChange(values.filter((item) => item !== value)) }} onPointerDown={(event) => event.stopPropagation()} type="button">×</button></span>)}
      </div>
      <button aria-label={`${label} 다음 항목`} className="controlled-vocabulary-arrow" disabled={!values.length} onClick={() => scrollValues(140)} type="button"><ChevronRight size={10} /></button>
      {values.length < maxItems && <button aria-label={`${label} 추가`} className="controlled-vocabulary-add" onClick={() => { setInput(''); setOptions([]); setLookupFailed(false); setOpen(true); window.setTimeout(() => inputRef.current?.focus()) }} title={`${label} 추가`} type="button"><Plus size={11} /></button>}
    </div>
    {menu}
  </div>
}
