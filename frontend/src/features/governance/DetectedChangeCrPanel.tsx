import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import type { ApiClient, ApiResponse } from '../../api/client'
import type { ChangeRequestSummary } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { ChangeHistoryApi } from '../change-history/changeHistoryApi'
import type {
  ChangeHistoryEventDetail,
  ChangeHistoryEventPage,
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

export function DetectedChangeCrPanel({
  client,
  changeRequests,
}: {
  client: ApiClient
  changeRequests: ChangeRequestSummary[]
}) {
  const api = useMemo(() => new ChangeHistoryApi(client), [client])
  const weekStart = useMemo(() => currentKstWeekStart(), [])
  const [weekly, setWeekly] = useState<ChangeHistoryWeeklySummary>()
  const [page, setPage] = useState<ChangeHistoryEventPage>()
  const [activeFilterKey, setActiveFilterKey] = useState<WeeklyFilterKey>('total_count')
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

  const fetchEvents = useCallback(async (filterKey: WeeklyFilterKey, signal?: AbortSignal) => {
    const filter = weeklyFilters.find((candidate) => candidate.key === filterKey)
    return api.events({
      weekStart,
      linkState: filter?.linkState,
      stage: filter?.stage,
      limit: EVENT_LIMIT,
    }, signal)
  }, [api, weekStart])

  const load = useCallback(async () => {
    loadController.current?.abort()
    const controller = new AbortController()
    loadController.current = controller
    setLoading(true)
    setError(undefined)
    setWeekly(undefined)
    setPage(undefined)
    try {
      const [weeklyResult, eventResult] = await Promise.all([
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
  }, [activeFilterKey, api, fetchEvents, weekStart])

  useEffect(() => {
    void load()
    return () => {
      loadController.current?.abort()
      detailController.current?.abort()
    }
  }, [load])

  const chooseFilter = (filterKey: WeeklyFilterKey) => {
    if (loading || filterKey === activeFilterKey) return
    setActiveFilterKey(filterKey)
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
      const [event, links, nextWeekly, nextPage] = await Promise.all([
        api.event(eventId),
        api.links(eventId, { limit: EVENT_LIMIT }),
        api.weekly(weekStart),
        fetchEvents(activeFilterKey),
      ])
      setDetail(freshDetail(event, links))
      setWeekly(nextWeekly)
      setPage(nextPage)
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

  return (
    <section className="detected-change-cr" aria-labelledby="detected-change-cr-title" aria-busy={loading}>
      <header className="detected-change-cr-header">
        <div>
          <span className="governance-kicker">Detected Change → CR</span>
          <h2 id="detected-change-cr-title">감지 변경과 CR 연결</h2>
          <p>KST 주간 원장에서 서버 권한 필터가 적용된 이벤트를 조회하고 현재 CR round에 연결합니다.</p>
        </div>
        <button className="button button-secondary" type="button" disabled={loading} onClick={() => void load()}>새로고침</button>
      </header>
      <ErrorNotice error={error} />
      {weekly && (
        <div className="detected-change-weekly" aria-label="주간 변경 7개 집계">
          {weeklyFilters.map((card) => (
            <button key={card.key} type="button" className={activeFilterKey === card.key ? 'active' : ''} aria-pressed={activeFilterKey === card.key} onClick={() => chooseFilter(card.key)}>
              <span>{card.label}</span><strong>{weekly[card.key].toLocaleString()}</strong>
            </button>
          ))}
        </div>
      )}
      <p className="detected-change-window">{weekStart} · 서버 이벤트 최대 {EVENT_LIMIT}건</p>
      {loading && !page ? <p role="status">변경 이벤트를 불러오는 중입니다.</p> : null}
      {page ? (
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
            )) : <tr><td colSpan={5}>선택한 주간 단계에 조회 가능한 이벤트가 없습니다.</td></tr>}</tbody>
          </table>
        </div>
      ) : null}
      {detailLoading ? <p role="status">최신 이벤트와 CR 연결 ETag를 확인하는 중입니다.</p> : null}
      <ErrorNotice error={actionError} />
      {detail ? (
        <section className="detected-change-linker" aria-label="선택 이벤트 CR 연결">
          <header><strong>{detail.event.data.entity_key}</strong><small>event ETag {detail.event.etag} · link ETag {detail.links.etag}</small></header>
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
}

function targetValue(target: { change_request_id: string; change_request_round: number }) {
  return JSON.stringify([target.change_request_id, target.change_request_round])
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

function currentKstWeekStart() {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date())
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]))
  const date = new Date(`${values.year}-${values.month}-${values.day}T00:00:00Z`)
  const daysSinceMonday = (date.getUTCDay() + 6) % 7
  date.setUTCDate(date.getUTCDate() - daysSinceMonday)
  return date.toISOString().slice(0, 10)
}
