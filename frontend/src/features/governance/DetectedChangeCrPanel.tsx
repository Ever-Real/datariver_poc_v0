import { useCallback, useEffect, useId, useMemo, useRef, useState, type FormEvent } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { X } from 'lucide-react'
import type { ApiClient, ApiResponse } from '../../api/client'
import type { ChangeRequestSummary } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import { ChangeHistoryApi } from '../change-history/changeHistoryApi'
import type {
  ChangeHistoryEventDetail,
  ChangeHistoryEvent,
  ChangeHistoryEventPage,
  ChangeHistoryChangeType,
  ChangeHistoryLinkAction,
  ChangeHistoryLinkPage,
  ChangeHistoryStage,
  ChangeHistoryWeeklySummary,
} from '../change-history/types'
import './changeHistoryCr.css'

const EVENT_LIMIT = 50

const weeklyFilters: Array<{
  key: 'total_count' | 'unlinked_count' | 'received_count' | 'recheck_count' | 'testing_count' | 'final_review_count' | 'completed_count'
  label: string
  linkState?: 'UNLINKED'
  stage?: ChangeHistoryStage
}> = [
  { key: 'total_count', label: '전체' },
  { key: 'unlinked_count', label: 'CR 미연결', linkState: 'UNLINKED' },
  { key: 'received_count', label: '접수 완료', stage: 'RECEIVED' },
  { key: 'recheck_count', label: '재검토', stage: 'RECHECK' },
  { key: 'testing_count', label: '변경 / TEST', stage: 'TESTING' },
  { key: 'final_review_count', label: '완료검토', stage: 'FINAL_REVIEW' },
  { key: 'completed_count', label: '완료', stage: 'COMPLETED' },
]

interface FreshResponse<T> extends ApiResponse<T> {
  etag: string
}

interface FreshDetail {
  event: FreshResponse<ChangeHistoryEventDetail>
  links: FreshResponse<ChangeHistoryLinkPage>
}

type WeeklyFilterKey = (typeof weeklyFilters)[number]['key']

export interface DetectedChangeSelection {
  platform: string
  databaseName: string
  schemaName: string
  systemId: string | null
  systemResolution: 'RESOLVED' | 'UNMAPPED' | 'AMBIGUOUS'
  systemName: string | null
  dateFrom: string
  dateTo: string
}

export interface DetectedChangeDateRange {
  from: string
  to: string
}

const eventColumns: ColumnDef<ChangeHistoryEvent>[] = [
  { accessorKey: 'source_occurred_at', header: '발생 시각', size: 150, enableSorting: false, cell: ({ row }) => row.original.source_occurred_at ? formatKst(row.original.source_occurred_at) : '시간 미상' },
  { id: 'change', header: '변경', size: 190, enableSorting: false, cell: ({ row }) => `${row.original.category} · ${row.original.operation}` },
  { id: 'target', header: '대상', size: 210, enableSorting: false, cell: ({ row }) => row.original.locator?.asset_name ?? row.original.entity_key },
  { accessorKey: 'current_stage', header: '단계', size: 120, enableSorting: false },
  { id: 'cr', header: 'CR', size: 180, enableSorting: false, cell: ({ row }) => row.original.current_primary ? `${row.original.current_primary.change_request_id} · round ${row.original.current_primary.change_request_round}` : '미연결' },
]

const historyColumns: ColumnDef<ChangeHistoryEvent>[] = [
  { id: 'platform', header: '플랫폼', size: 90, enableSorting: false, meta: { className: 'detected-change-ellipsis' }, cell: ({ row }) => <span title={row.original.locator?.platform ?? ''}>{row.original.locator?.platform ?? '없음'}</span> },
  { id: 'schema', header: '스키마', size: 130, enableSorting: false, meta: { className: 'detected-change-ellipsis' }, cell: ({ row }) => <span title={row.original.locator?.schema_name ?? ''}>{row.original.locator?.schema_name ?? '없음'}</span> },
  { id: 'change_date', header: '변경일', size: 110, enableSorting: false, meta: { className: 'detected-change-nowrap' }, cell: ({ row }) => formatKstDate(row.original.source_occurred_at ?? row.original.detected_at) },
  { id: 'presentation_change_type', header: '변경유형', size: 130, enableSorting: false, meta: { className: 'detected-change-nowrap' }, cell: ({ row }) => presentationChangeTypeLabel(row.original.presentation_change_type) },
  { id: 'table', header: '테이블명', size: 160, enableSorting: false, meta: { className: 'detected-change-ellipsis' }, cell: ({ row }) => <span title={row.original.locator?.asset_name ?? row.original.entity_key}>{row.original.locator?.asset_name ?? row.original.entity_key}</span> },
  { id: 'summary', header: '변경요약', size: 150, enableSorting: false, meta: { className: 'detected-change-wrap' }, cell: ({ row }) => <span title={row.original.change_summary}>{row.original.change_summary}</span> },
  { id: 'detail', header: '변경내용', size: 230, enableSorting: false, meta: { className: 'detected-change-wrap detected-change-detail-cell' }, cell: ({ row }) => {
    const detail = presentationChangeDetail(row.original)
    return <span title={detail}>{detail}</span>
  } },
]

export function DetectedChangeCrPanel({
  client,
  changeRequests,
  selection,
  dateRange,
  onClose,
}: {
  client: ApiClient
  changeRequests: ChangeRequestSummary[]
  selection?: DetectedChangeSelection
  dateRange?: DetectedChangeDateRange
  onClose?: () => void
  onManageTableSystemMappings?: () => void
}) {
  const api = useMemo(() => new ChangeHistoryApi(client), [client])
  const headingId = useId()
  const weekStart = useMemo(() => currentKstWeekStart(), [])
  const [weekly, setWeekly] = useState<ChangeHistoryWeeklySummary>()
  const [page, setPage] = useState<ChangeHistoryEventPage>()
  const [eventCursor, setEventCursor] = useState<string>()
  const [eventCursorStack, setEventCursorStack] = useState<string[]>([])
  const [activeFilterKey, setActiveFilterKey] = useState<WeeklyFilterKey>('total_count')
  const [activeChangeType, setActiveChangeType] = useState<'' | ChangeHistoryChangeType>('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>()
  const [detail, setDetail] = useState<FreshDetail>()
  const [detailLoading, setDetailLoading] = useState(false)
  const [action, setAction] = useState<ChangeHistoryLinkAction | ''>('')
  const [targetKey, setTargetKey] = useState('')
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false)
  const [actionError, setActionError] = useState<unknown>()
  const loadController = useRef<AbortController | undefined>(undefined)
  const detailController = useRef<AbortController | undefined>(undefined)

  const fetchEvents = useCallback(async (filterKey: WeeklyFilterKey, signal?: AbortSignal, cursor?: string) => {
    if (selection) {
      return api.events({
        dateFrom: selection.dateFrom,
        dateTo: selection.dateTo,
        platform: selection.platform,
        databaseName: selection.databaseName,
        schemaName: selection.schemaName,
        systemId: selection.systemId ?? undefined,
        systemResolution: selection.systemResolution,
        limit: EVENT_LIMIT,
        cursor,
      }, signal)
    }
    if (dateRange) {
      return api.events({
        dateFrom: dateRange.from,
        dateTo: dateRange.to,
        changeType: activeChangeType || undefined,
        limit: EVENT_LIMIT,
        cursor,
      }, signal)
    }
    const filter = weeklyFilters.find((candidate) => candidate.key === filterKey)
    return api.events({
      weekStart,
      linkState: filter?.linkState,
      stage: filter?.stage,
      limit: EVENT_LIMIT,
      cursor,
    }, signal)
  }, [activeChangeType, api, dateRange, selection, weekStart])

  const load = useCallback(async () => {
    loadController.current?.abort()
    const controller = new AbortController()
    loadController.current = controller
    setLoading(true)
    setError(undefined)
    setWeekly(undefined)
    setPage(undefined)
    setEventCursor(undefined)
    setEventCursorStack([])
    try {
      const [weeklyResult, eventResult] = selection || dateRange
        ? [undefined, await fetchEvents(activeFilterKey, controller.signal)]
        : await Promise.all([
          api.weekly(weekStart, controller.signal),
          fetchEvents(activeFilterKey, controller.signal),
        ])
      if (controller.signal.aborted) return
      setWeekly(weeklyResult)
      setPage(eventResult)
    } catch (loadError) {
      if (!controller.signal.aborted) setError(loadError)
    } finally {
      if (loadController.current === controller) {
        loadController.current = undefined
        setLoading(false)
      }
    }
  }, [activeFilterKey, api, dateRange, fetchEvents, selection, weekStart])

  useEffect(() => {
    void load()
    if (selection) document.body.classList.add('catalog-overlay-open')
    return () => {
      loadController.current?.abort()
      detailController.current?.abort()
      if (selection) document.body.classList.remove('catalog-overlay-open')
    }
  }, [load, selection])

  const chooseFilter = (filterKey: WeeklyFilterKey) => {
    if (loading || filterKey === activeFilterKey) return
    setActiveFilterKey(filterKey)
  }

  const changeEventPage = async (cursor: string | undefined, direction: 'next' | 'previous') => {
    if (loading || (direction === 'next' && !cursor)) return
    loadController.current?.abort()
    const controller = new AbortController()
    loadController.current = controller
    setLoading(true)
    setError(undefined)
    try {
      const nextPage = await fetchEvents(activeFilterKey, controller.signal, cursor)
      if (controller.signal.aborted) return
      setPage(nextPage)
      if (direction === 'next') {
        setEventCursorStack((current) => [...current, eventCursor ?? ''])
      } else {
        setEventCursorStack((current) => current.slice(0, -1))
      }
      setEventCursor(cursor)
    } catch (pageError) {
      if (!controller.signal.aborted) setError(pageError)
    } finally {
      if (loadController.current === controller) {
        loadController.current = undefined
        setLoading(false)
      }
    }
  }

  const loadDetail = useCallback(async (eventId: string) => {
    detailController.current?.abort()
    const controller = new AbortController()
    detailController.current = controller
    setDetail(undefined)
    setDetailLoading(true)
    setAction('')
    setTargetKey('')
    setReason('')
    setActionError(undefined)
    try {
      const [event, links] = await Promise.all([
        api.event(eventId, controller.signal),
        api.links(eventId, { limit: EVENT_LIMIT, signal: controller.signal }),
      ])
      if (!controller.signal.aborted) setDetail(freshDetail(event, links))
    } catch (detailError) {
      if (!controller.signal.aborted) setActionError(detailError)
    } finally {
      if (detailController.current === controller) {
        detailController.current = undefined
        setDetailLoading(false)
      }
    }
  }, [api])

  const targetOptions = useMemo(() => {
    if (!detail || !action) return []
    const authorizedCurrentTargets = changeRequests.map((request) => ({
      change_request_id: request.id,
      change_request_round: request.current_round_number,
    }))
    if (action === 'CLEAR_PRIMARY') {
      return authorizedCurrentTargets.filter((target) => sameTarget(target, detail.links.data.current_primary))
    }
    if (action === 'REMOVE_CANDIDATE') {
      return authorizedCurrentTargets.filter((target) => detail.links.data.current_candidates.some(
        (candidate) => sameTarget(target, candidate),
      ))
    }
    return authorizedCurrentTargets
  }, [action, changeRequests, detail])

  useEffect(() => {
    setTargetKey(targetOptions.length === 1 && targetOptions[0] ? targetValue(targetOptions[0]) : '')
  }, [targetOptions])

  const submit = async (formEvent: FormEvent) => {
    formEvent.preventDefault()
    if (!detail || !action || saving || reason.trim().length === 0) return
    if (!detail.event.data.allowed_link_actions.includes(action)) return
    const target = targetOptions.find((candidate) => targetValue(candidate) === targetKey)
    if (!target) return
    setSaving(true)
    setActionError(undefined)
    try {
      await api.linkEvent(
        detail.event.data.event_id,
        { action, ...target, reason: reason.trim() },
        detail.event.etag,
        crypto.randomUUID(),
      )
      const eventId = detail.event.data.event_id
      const [event, links, nextPage] = await Promise.all([
        api.event(eventId),
        api.links(eventId, { limit: EVENT_LIMIT }),
        fetchEvents(activeFilterKey, undefined, eventCursor),
      ])
      setDetail(freshDetail(event, links))
      setPage(nextPage)
      if (!selection) setWeekly(await api.weekly(weekStart))
      setAction('')
      setTargetKey('')
      setReason('')
    } catch (submitError) {
      setActionError(submitError)
    } finally {
      setSaving(false)
    }
  }

  const allowedActions = detail?.event.data.allowed_link_actions ?? []

  const content = (
    <section className="detected-change-cr" aria-labelledby={headingId} aria-busy={loading}>
      <header className="detected-change-cr-header">
        <div>
          <span className="governance-kicker">Detected Change → CR</span>
          <h2 id={headingId}>{selection ? `${selection.schemaName} 이벤트` : dateRange ? 'Schema / Metadata 감지 변경 이력' : '감지 변경과 CR 연결'}</h2>
          <p>{selection ? `${selection.systemName ?? '시스템 미지정'} · ${selection.dateFrom}–${selection.dateTo} · 서버 권한 범위` : dateRange ? `${dateRange.from}–${dateRange.to} · Monitoring과 동일한 canonical change ledger · 서버 권한 범위` : 'KST 주간 원장에서 서버 권한 필터가 적용된 이벤트를 조회하고 현재 CR round에 연결합니다.'}</p>
        </div>
        <div className="detected-change-header-actions"><button className="button button-secondary" type="button" disabled={loading} onClick={() => void load()}>새로고침</button>{selection && <button type="button" aria-label="이벤트 상세 닫기" onClick={onClose}><X size={16} /></button>}</div>
      </header>
      <ErrorNotice error={error} />
      {!selection && !dateRange && weekly && (
        <div className="detected-change-weekly" aria-label="주간 변경 7개 집계">
          {weeklyFilters.map((card) => (
            <button key={card.key} type="button" className={activeFilterKey === card.key ? 'active' : ''} aria-pressed={activeFilterKey === card.key} onClick={() => chooseFilter(card.key)}>
              <span>{card.label}</span><strong>{weekly[card.key].toLocaleString()}</strong>
            </button>
          ))}
        </div>
      )}
      {dateRange && !selection ? <div className="detected-change-type-filters" role="group" aria-label="감지 변경 유형 필터">
        {([['', '전체'], ['SCHEMA_CHANGE', 'Schema Change'], ['METADATA_CHANGE', 'Metadata Change']] as const).map(([value, label]) => <button
          key={value || 'ALL'}
          type="button"
          aria-pressed={activeChangeType === value}
          className={activeChangeType === value ? 'active' : ''}
          disabled={loading}
          onClick={() => setActiveChangeType(value)}
        >{label}</button>)}
      </div> : null}
      <p className="detected-change-window">{selection || dateRange ? `${page?.total.toLocaleString() ?? 0}개 권한 행 · 현재 페이지 최대 ${EVENT_LIMIT}건` : `${weekStart} · 서버 이벤트 최대 ${EVENT_LIMIT}건`}</p>
      {loading && !page ? <p role="status">변경 이벤트를 불러오는 중입니다.</p> : null}
      {(selection || dateRange) && page ? <DenseDataTable
        caption={selection ? `${selection.schemaName} 권한 범위의 감지 변경 이벤트` : '현재 기간과 권한 범위의 Schema 및 Metadata 감지 변경 이력'}
        columns={selection ? eventColumns : historyColumns}
        data={page.items}
        getRowId={(event) => event.event_id}
        emptyMessage={changeHistoryEmptyMessage(page, Boolean(selection))}
        onRowActivate={(event) => void loadDetail(event.event_id)}
        className={dateRange && !selection ? 'detected-change-history-table' : undefined}
        fitContainer={Boolean(dateRange && !selection)}
      /> : page ? (
        <div className="detected-change-table-wrap">
          <table>
            <caption>권한 범위의 감지 변경 이벤트</caption>
            <thead><tr><th>감지 시각</th><th>변경</th><th>대상</th><th>단계</th><th>CR</th></tr></thead>
            <tbody>{page.items.length ? page.items.map((event) => (
              <tr key={event.event_id}>
                <td><button type="button" className="detected-change-event" onClick={() => void loadDetail(event.event_id)}>{formatKst(event.detected_at)}</button></td>
                <td>{event.category} · {event.operation}</td>
                <td title={event.asset_urn}>{event.locator?.asset_name ?? event.entity_key}</td>
                <td>{event.current_stage}</td>
                <td>{event.current_primary ? `${event.current_primary.change_request_id} · round ${event.current_primary.change_request_round}` : '미연결'}</td>
              </tr>
            )) : <tr><td colSpan={5}>{changeHistoryEmptyMessage(page, false)}</td></tr>}</tbody>
          </table>
        </div>
      ) : null}
      {(selection || dateRange) && page ? <nav className="detected-change-pagination" aria-label="이벤트 페이지 이동">
        <button className="button button-secondary" type="button" disabled={loading || !eventCursorStack.length} onClick={() => void changeEventPage(eventCursorStack.at(-1) || undefined, 'previous')}>이전</button>
        <button className="button button-secondary" type="button" disabled={loading || !page.next_cursor} onClick={() => void changeEventPage(page.next_cursor ?? undefined, 'next')}>다음</button>
      </nav> : null}
      {detailLoading ? <p role="status">최신 이벤트와 CR 연결 ETag를 확인하는 중입니다.</p> : null}
      <ErrorNotice error={actionError} />
      {detail ? (
        <section className="detected-change-linker" aria-label="선택 이벤트 CR 연결">
          <header><strong>{detail.event.data.locator?.asset_name ?? detail.event.data.entity_key}</strong><small>{detail.event.data.change_type} · {detail.event.data.operation} · {formatKst(detail.event.data.detected_at)}</small></header>
          <dl className="detected-change-event-detail">
            <div><dt>System / Database / Schema</dt><dd>{[detail.event.data.system.system_id ?? '시스템 미지정', detail.event.data.locator?.database_name, detail.event.data.locator?.schema_name].filter(Boolean).join(' · ')}</dd></div>
            <div><dt>Source / Provenance</dt><dd>DataHub · {detail.event.data.source_aspect} · {detail.event.data.precision ?? 'precision 미지정'}</dd></div>
            <div><dt>Before</dt><dd><pre>{formatDiff(detail.event.data.before)}</pre></dd></div>
            <div><dt>After</dt><dd><pre>{formatDiff(detail.event.data.after)}</pre></dd></div>
          </dl>
          <small className="detected-change-etag">event ETag {detail.event.etag} · link ETag {detail.links.etag}</small>
          {allowedActions.length === 0 ? <p>현재 권한과 이벤트 상태에서 허용된 연결 작업이 없습니다.</p> : (
            <form onSubmit={(event) => void submit(event)}>
              <label>허용 작업<select aria-label="허용 작업" value={action} onChange={(event) => setAction(event.target.value as ChangeHistoryLinkAction | '')} disabled={saving}><option value="">선택</option>{allowedActions.map((value) => <option key={value} value={value}>{actionLabel(value)}</option>)}</select></label>
              <label>현재 round CR 대상<select aria-label="현재 round CR 대상" value={targetKey} onChange={(event) => setTargetKey(event.target.value)} disabled={!action || saving}><option value="">선택</option>{targetOptions.map((target) => <option key={targetValue(target)} value={targetValue(target)}>{requestLabel(target, changeRequests)}</option>)}</select></label>
              {action && targetOptions.length === 0 ? <p className="detected-change-target-empty">현재 권한의 CR 목록에서 일치하는 current round 대상을 찾을 수 없습니다.</p> : null}
              <label>연결 사유<textarea aria-label="연결 사유" value={reason} onChange={(event) => setReason(event.target.value)} maxLength={2000} rows={2} disabled={saving} /></label>
              <button className="button" type="submit" disabled={saving || !action || !targetKey || !reason.trim()}>{saving ? '저장 중' : '연결 이력 저장'}</button>
            </form>
          )}
        </section>
      ) : null}
    </section>
  )
  return selection ? <>
    <button type="button" className="catalog-detail-backdrop" aria-label="이벤트 상세 닫기" onClick={onClose} />
    <aside className="catalog-detail catalog-detail--overlay panel detected-change-drawer" role="complementary" aria-label={`${selection.schemaName} 이벤트 상세`}>
      {content}
    </aside>
  </> : content
}

function targetValue(target: { change_request_id: string; change_request_round: number }) {
  return JSON.stringify([target.change_request_id, target.change_request_round])
}

function changeHistoryEmptyMessage(page: ChangeHistoryEventPage, selection: boolean) {
  if (page.empty_state_reason === 'NO_LEDGER_EVENTS') {
    return '현재 canonical change ledger에 감지 이벤트가 없습니다.'
  }
  if (page.empty_state_reason === 'EVENTS_EXIST_BUT_NOT_AUTHORIZED') {
    return page.empty_state_detail === 'NO_EXACT_MAPPING'
      ? '연결된 시스템 정보 없음'
      : '감지 이벤트는 존재하지만 현재 계정의 권한 범위에는 표시할 수 있는 행이 없습니다.'
  }
  return selection
    ? '선택한 스키마·시스템·기간 필터에 일치하는 이벤트가 없습니다.'
    : '선택한 기간 또는 변경 유형 필터에 일치하는 감지 이력이 없습니다.'
}

function freshDetail(
  event: ApiResponse<ChangeHistoryEventDetail>,
  links: ApiResponse<ChangeHistoryLinkPage>,
): FreshDetail {
  if (!event.etag || !links.etag || event.etag !== links.etag) {
    throw new Error('이벤트와 CR 연결 이력의 최신 ETag가 일치하지 않습니다. 다시 조회해 주세요.')
  }
  return {
    event: { ...event, etag: event.etag },
    links: { ...links, etag: links.etag },
  }
}

function sameTarget(
  left: { change_request_id: string; change_request_round: number },
  right: { change_request_id: string; change_request_round: number } | null,
) {
  return right !== null
    && left.change_request_id === right.change_request_id
    && left.change_request_round === right.change_request_round
}

function requestLabel(target: { change_request_id: string; change_request_round: number }, requests: ChangeRequestSummary[]) {
  const request = requests.find((candidate) => candidate.id === target.change_request_id)
  return `${request?.number ?? target.change_request_id} · round ${target.change_request_round}`
}

function actionLabel(action: ChangeHistoryLinkAction) {
  return ({ SET_PRIMARY: 'Primary 지정', CLEAR_PRIMARY: 'Primary 해제', ADD_CANDIDATE: 'Candidate 추가', REMOVE_CANDIDATE: 'Candidate 제거' })[action]
}

function formatKst(value: string) {
  return new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', dateStyle: 'short', timeStyle: 'short' }).format(new Date(value))
}

function formatKstDate(value: string) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(new Date(value))
}

function presentationChangeTypeLabel(value: ChangeHistoryEvent['presentation_change_type']) {
  return ({
    TABLE_CREATE: '테이블생성',
    TABLE_DELETE: '테이블삭제',
    TABLE_CHANGE: '테이블변경',
    COLUMN_CREATE: '컬럼추가',
    COLUMN_DELETE: '컬럼삭제',
    COLUMN_CHANGE: '컬럼변경',
  })[value]
}

function presentationChangeDetail(event: ChangeHistoryEvent) {
  const tableName = event.locator?.asset_name ?? event.entity_key
  if (event.presentation_change_type === 'TABLE_CREATE') return `테이블 ${tableName} 생성`
  if (event.presentation_change_type === 'TABLE_DELETE') return `테이블 ${tableName} 삭제`
  if (event.presentation_change_type === 'COLUMN_CREATE') return `컬럼 ${event.field_name ?? '이름 없음'} 생성`
  if (event.presentation_change_type === 'COLUMN_DELETE') return `컬럼 ${event.field_name ?? '이름 없음'} 삭제`
  const fieldLabels: Record<ChangeHistoryEvent['change_detail'][number]['field'], string> = {
    DESCRIPTION: 'Desc', TAG: 'Tag', GLOSSARY_TERM: 'Term', OWNER: 'Owner', DOMAIN: 'Domain',
    TYPE: 'Type', NULLABLE: 'Nullable', SCHEMA: 'Schema', PROPERTY: 'Property',
  }
  const prefix = event.target_kind === 'COLUMN' ? `${event.field_name ?? '컬럼 이름 없음'} ` : ''
  const changes = event.change_detail.map((change) => (
    `${prefix}${fieldLabels[change.field]} 기존(${change.before ?? '없음'})에서 변경(${change.after ?? '없음'})`
  ))
  return changes.length ? changes.join(' · ') : event.change_summary
}

function formatDiff(value: Record<string, unknown> | null) {
  return value === null ? '없음' : JSON.stringify(value, null, 2)
}

function currentKstWeekStart() {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date())
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]))
  const date = new Date(`${values.year}-${values.month}-${values.day}T00:00:00Z`)
  const daysSinceMonday = (date.getUTCDay() + 6) % 7
  date.setUTCDate(date.getUTCDate() - daysSinceMonday)
  return date.toISOString().slice(0, 10)
}
