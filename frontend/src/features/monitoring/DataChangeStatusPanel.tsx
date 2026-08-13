import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { RefreshCw, Search } from 'lucide-react'
import type { ApiClient } from '../../api/client'
import { ErrorNotice } from '../../components/ErrorNotice'
import { Dialog } from '../../components/common/Dialog'
import { ChangeHistoryApi } from '../change-history/changeHistoryApi'
import type {
  ChangeHistoryCategory,
  ChangeHistoryChangeType,
  ChangeHistoryEvent,
  ChangeHistoryEventDetail,
  ChangeHistoryEventFilters,
  ChangeHistoryEventPage,
  ChangeHistoryLinkPage,
  ChangeHistoryOperation,
  ChangeHistoryPrecision,
  ChangeHistoryStage,
  ChangeHistorySummary,
  ChangeHistorySyncStatus,
} from '../change-history/types'
import './dataChangeStatus.css'

const EVENT_LIMIT = 50

const categoryOptions: Array<[ChangeHistoryCategory, string]> = [
  ['TECHNICAL_SCHEMA', '기술 스키마'],
  ['DOCUMENTATION', '문서'],
  ['TAG', '태그'],
  ['GLOSSARY_TERM', '용어'],
  ['OWNERSHIP', '소유권'],
]
const precisionOptions: Array<[ChangeHistoryPrecision, string]> = [
  ['EXACT_TIMELINE', '정확한 Timeline'],
  ['EXACT_MCL', '정확한 MCL'],
  ['DRIFT_DETECTED', 'Drift 감지'],
  ['BACKFILLED_BEST_EFFORT', '과거 이력 (best effort)'],
  ['INITIAL_BASELINE', '초기 기준선'],
]
const operationOptions: Array<[ChangeHistoryOperation, string]> = [
  ['CREATE', '생성'],
  ['UPDATE', '수정'],
  ['UPSERT', '갱신'],
  ['DELETE', '삭제'],
  ['ADD', '추가'],
  ['REMOVE', '제거'],
]
const stageOptions: Array<[ChangeHistoryStage, string]> = [
  ['UNLINKED', 'CR 미연결'],
  ['RECEIVED', '접수 완료'],
  ['RECHECK', '재검토'],
  ['TESTING', '변경 / TEST'],
  ['FINAL_REVIEW', '완료검토'],
  ['COMPLETED', '완료'],
]

interface FilterDraft {
  weekStart: string
  changeType: '' | ChangeHistoryChangeType
  category: '' | ChangeHistoryCategory
  precision: '' | ChangeHistoryPrecision
  operation: '' | ChangeHistoryOperation
  platform: string
  databaseName: string
  schemaName: string
  systemId: string
  assigneeSubjectId: string
  linkState: '' | 'LINKED' | 'UNLINKED'
  stage: '' | ChangeHistoryStage
}

interface DetailState {
  event: ChangeHistoryEventDetail
  links: ChangeHistoryLinkPage
}

export function DataChangeStatusPanel({ client }: { client: ApiClient }) {
  const api = useMemo(() => new ChangeHistoryApi(client), [client])
  const defaultWeekStart = useMemo(() => currentKstWeekStart(), [])
  const [draft, setDraft] = useState<FilterDraft>(() => emptyFilterDraft(defaultWeekStart))
  const [filters, setFilters] = useState<ChangeHistoryEventFilters>({
    weekStart: defaultWeekStart,
    limit: EVENT_LIMIT,
  })
  const [summary, setSummary] = useState<ChangeHistorySummary>()
  const [page, setPage] = useState<ChangeHistoryEventPage>()
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<unknown>()
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null)
  const [detail, setDetail] = useState<DetailState>()
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<unknown>()
  const loadRequest = useRef<AbortController | null>(null)
  const detailRequest = useRef<AbortController | null>(null)

  const load = useCallback(async (nextFilters: ChangeHistoryEventFilters) => {
    loadRequest.current?.abort()
    const controller = new AbortController()
    loadRequest.current = controller
    setLoading(true)
    setLoadError(undefined)
    setSummary(undefined)
    setPage(undefined)
    const weekStart = nextFilters.weekStart ?? defaultWeekStart
    const [summaryResult, eventsResult] = await Promise.allSettled([
      api.summary(weekStart, controller.signal),
      api.events({ ...nextFilters, weekStart, limit: EVENT_LIMIT }, controller.signal),
    ])
    if (controller.signal.aborted) return
    if (summaryResult.status === 'fulfilled') setSummary(summaryResult.value)
    if (eventsResult.status === 'fulfilled') setPage(eventsResult.value)
    if (summaryResult.status === 'rejected') setLoadError(summaryResult.reason)
    else if (eventsResult.status === 'rejected') setLoadError(eventsResult.reason)
    if (loadRequest.current === controller) {
      loadRequest.current = null
      setLoading(false)
    }
  }, [api, defaultWeekStart])

  useEffect(() => {
    void load(filters)
    return () => loadRequest.current?.abort()
  }, [filters, load])

  useEffect(() => () => detailRequest.current?.abort(), [])

  const applyFilters = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!isMondayDate(draft.weekStart)) {
      setLoadError(new Error('조회 주는 KST 기준 월요일을 선택하세요.'))
      return
    }
    setFilters(toEventFilters(draft))
  }

  const resetFilters = () => {
    const next = emptyFilterDraft(defaultWeekStart)
    setDraft(next)
    setFilters(toEventFilters(next))
  }

  const openDetail = async (eventId: string) => {
    detailRequest.current?.abort()
    const controller = new AbortController()
    detailRequest.current = controller
    setSelectedEventId(eventId)
    setDetail(undefined)
    setDetailError(undefined)
    setDetailLoading(true)
    const [eventResult, linksResult] = await Promise.allSettled([
      api.event(eventId, controller.signal),
      api.links(eventId, { limit: EVENT_LIMIT, signal: controller.signal }),
    ])
    if (controller.signal.aborted) return
    if (eventResult.status === 'fulfilled' && linksResult.status === 'fulfilled') {
      setDetail({ event: eventResult.value.data, links: linksResult.value.data })
    } else if (eventResult.status === 'rejected') {
      setDetailError(eventResult.reason)
    } else if (linksResult.status === 'rejected') {
      setDetailError(linksResult.reason)
    }
    if (detailRequest.current === controller) {
      detailRequest.current = null
      setDetailLoading(false)
    }
  }

  const closeDetail = () => {
    detailRequest.current?.abort()
    detailRequest.current = null
    setSelectedEventId(null)
    setDetail(undefined)
    setDetailError(undefined)
    setDetailLoading(false)
  }

  return (
    <section className="data-change-status-panel" aria-busy={loading}>
      <header className="data-change-status-header">
        <div>
          <p className="eyebrow">Authoritative change ledger</p>
          <h2>데이터 변경현황</h2>
          <p>ChangeHistoryApi가 권한 범위에서 반환한 서버 원장만 표시합니다.</p>
        </div>
        <button
          className="button button-secondary"
          type="button"
          disabled={loading}
          onClick={() => void load(filters)}
        >
          <RefreshCw size={14} />
          변경현황 새로고침
        </button>
      </header>

      <ErrorNotice error={loadError} />
      {loading && !summary && !page && (
        <div className="data-change-loading" role="status">
          <span className="loader" />
          <p>변경 원장 요약과 이벤트를 조회하고 있습니다.</p>
        </div>
      )}
      {summary && <SummaryView summary={summary} />}

      <FilterForm
        draft={draft}
        loading={loading}
        onChange={setDraft}
        onReset={resetFilters}
        onSubmit={applyFilters}
      />

      {page && <EventTable page={page} onOpenDetail={(eventId) => void openDetail(eventId)} />}

      <Dialog
        open={selectedEventId !== null}
        title="변경 이벤트 상세"
        description="서버가 반환한 bounded semantic diff와 append-only CR 연결 이력입니다."
        size="large"
        onRequestClose={closeDetail}
        footer={(
          <button className="button button-secondary" type="button" onClick={closeDetail}>
            닫기
          </button>
        )}
      >
        {detailLoading && (
          <div className="data-change-loading" role="status">
            <span className="loader" />
            <p>이벤트 상세와 CR 연결 이력을 조회하고 있습니다.</p>
          </div>
        )}
        <ErrorNotice error={detailError} />
        {detail && <DetailView detail={detail} />}
      </Dialog>
    </section>
  )
}

function SummaryView({ summary }: { summary: ChangeHistorySummary }) {
  const weeklyCounts: Array<[string, number]> = [
    ['CR 미연결', summary.unlinked_count],
    ['접수 완료', summary.received_count],
    ['재검토', summary.recheck_count],
    ['변경 / TEST', summary.testing_count],
    ['완료검토', summary.final_review_count],
    ['완료', summary.completed_count],
  ]
  return (
    <div className="data-change-summary">
      <section className="data-change-kpis" aria-label="변경 이력 원장 상태">
        <SummaryFact label="last successful sync" value={formatTimestamp(summary.last_successful_capture_at)} />
        <SummaryFact label="source generation" value={summary.source_generation} code />
        <SummaryFact label="Schema Change" value={formatCount(summary.schema_change_count)} />
        <SummaryFact label="Metadata Change" value={formatCount(summary.metadata_change_count)} />
        <SummaryFact label="CR 미연결" value={formatCount(summary.unlinked_count)} />
        <SummaryFact label="DataHub 상태" value={syncStateLabel(summary.capture_state)} />
        <SummaryFact label="Sync 상태" value={syncStateLabel(summary.sync_status)} />
        <SummaryFact label="history available from" value={formatTimestamp(summary.history_available_from)} />
        <SummaryFact label="ledger guarantee from" value={formatTimestamp(summary.ledger_guarantee_from)} />
      </section>
      <div className="data-change-summary-grid">
        <section className="data-change-trend" aria-labelledby="data-change-weekly-title">
          <header>
            <div>
              <p className="eyebrow">KST weekly transactions</p>
              <h3 id="data-change-weekly-title">주간 변경 요약</h3>
            </div>
            <span>{summary.week_start} – {summary.week_end_exclusive}</span>
          </header>
          <div className="data-change-type-totals">
            <span>전체 <strong>{formatCount(summary.total_count)}</strong></span>
            <span>Schema <strong>{formatCount(summary.schema_change_count)}</strong></span>
            <span>Metadata <strong>{formatCount(summary.metadata_change_count)}</strong></span>
          </div>
          <ul>
            {weeklyCounts.map(([label, count]) => (
              <li key={label}>
                <span>{label}</span>
                <meter min={0} max={Math.max(summary.total_count, 1)} value={count}>{count}</meter>
                <strong>{formatCount(count)}</strong>
              </li>
            ))}
          </ul>
          <p className="data-change-as-of">
            집계 기준 <time dateTime={summary.as_of}>{formatTimestamp(summary.as_of)}</time>
            {summary.time_unknown_count > 0 && ` · 시간 미확정 ${formatCount(summary.time_unknown_count)}`}
          </p>
        </section>
        <section className="data-change-precision" aria-labelledby="data-change-precision-title">
          <p className="eyebrow">Declared source precision</p>
          <h3 id="data-change-precision-title">정밀도 범위</h3>
          <dl>
            {precisionOptions.map(([value, label]) => (
              <div key={value}>
                <dt>{label}</dt>
                <dd>{formatCount(summary.precision_counts[value])}</dd>
              </div>
            ))}
          </dl>
        </section>
      </div>
    </div>
  )
}

function SummaryFact({
  label,
  value,
  code = false,
}: {
  label: string
  value: string
  code?: boolean
}) {
  return (
    <div>
      <span>{label}</span>
      {code ? <code>{value}</code> : <strong>{value}</strong>}
    </div>
  )
}

function FilterForm({
  draft,
  loading,
  onChange,
  onReset,
  onSubmit,
}: {
  draft: FilterDraft
  loading: boolean
  onChange: (next: FilterDraft) => void
  onReset: () => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
}) {
  const update = <K extends keyof FilterDraft>(field: K, value: FilterDraft[K]) => {
    onChange({ ...draft, [field]: value })
  }
  return (
    <form className="data-change-filters" onSubmit={onSubmit}>
      <header>
        <div>
          <p className="eyebrow">Server-side filters</p>
          <h3>변경 이력 필터</h3>
        </div>
        <p>입력값은 로컬 선별 없이 권한 적용된 서버 조회에 전달됩니다.</p>
      </header>
      <div className="data-change-filter-grid">
        <label>
          주 시작일 (KST 월요일)
          <input type="date" value={draft.weekStart} onChange={(event) => update('weekStart', event.target.value)} />
        </label>
        <label>
          변경 유형
          <select value={draft.changeType} onChange={(event) => update('changeType', event.target.value as FilterDraft['changeType'])}>
            <option value="">전체</option>
            <option value="SCHEMA_CHANGE">Schema Change</option>
            <option value="METADATA_CHANGE">Metadata Change</option>
          </select>
        </label>
        <SelectFilter label="카테고리" value={draft.category} options={categoryOptions} onChange={(value) => update('category', value as FilterDraft['category'])} />
        <SelectFilter label="정밀도" value={draft.precision} options={precisionOptions} onChange={(value) => update('precision', value as FilterDraft['precision'])} />
        <SelectFilter label="작업" value={draft.operation} options={operationOptions} onChange={(value) => update('operation', value as FilterDraft['operation'])} />
        <TextFilter label="플랫폼" value={draft.platform} onChange={(value) => update('platform', value)} />
        <TextFilter label="데이터베이스" value={draft.databaseName} onChange={(value) => update('databaseName', value)} />
        <TextFilter label="스키마" value={draft.schemaName} onChange={(value) => update('schemaName', value)} />
        <TextFilter label="시스템 ID" value={draft.systemId} onChange={(value) => update('systemId', value)} />
        <TextFilter label="담당자 ID" value={draft.assigneeSubjectId} onChange={(value) => update('assigneeSubjectId', value)} />
        <label>
          CR 연결 상태
          <select value={draft.linkState} onChange={(event) => update('linkState', event.target.value as FilterDraft['linkState'])}>
            <option value="">전체</option>
            <option value="LINKED">연결됨</option>
            <option value="UNLINKED">미연결</option>
          </select>
        </label>
        <SelectFilter label="단계" value={draft.stage} options={stageOptions} onChange={(value) => update('stage', value as FilterDraft['stage'])} />
      </div>
      <div className="data-change-filter-actions">
        <button className="button" type="submit" disabled={loading}>
          <Search size={14} />
          필터 적용
        </button>
        <button className="button button-secondary" type="button" disabled={loading} onClick={onReset}>
          초기화
        </button>
      </div>
    </form>
  )
}

function SelectFilter({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: Array<[string, string]>
  onChange: (value: string) => void
}) {
  return (
    <label>
      {label}
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">전체</option>
        {options.map(([optionValue, optionLabel]) => (
          <option key={optionValue} value={optionValue}>{optionLabel}</option>
        ))}
      </select>
    </label>
  )
}

function TextFilter({
  label,
  value,
  onChange,
}: {
  label: string
  value: string
  onChange: (value: string) => void
}) {
  return (
    <label>
      {label}
      <input value={value} maxLength={255} onChange={(event) => onChange(event.target.value)} />
    </label>
  )
}

function EventTable({
  page,
  onOpenDetail,
}: {
  page: ChangeHistoryEventPage
  onOpenDetail: (eventId: string) => void
}) {
  return (
    <section className="data-change-events" aria-labelledby="data-change-events-title">
      <header>
        <div>
          <p className="eyebrow">Authorization-pruned ledger events</p>
          <h3 id="data-change-events-title">변경 이벤트</h3>
        </div>
        <span>총 {formatCount(page.total)}건 · 최대 {EVENT_LIMIT}건 표시</span>
      </header>
      {page.items.length === 0 ? (
        <div className="data-change-empty">
          <h4>변경 이력이 없습니다.</h4>
          <p>선택한 서버 필터에 해당하는 권한 범위의 이벤트가 없습니다.</p>
        </div>
      ) : (
        <div className="data-change-table-scroll">
          <table>
            <thead>
              <tr>
                <th>발생 시각</th>
                <th>정밀도</th>
                <th>카테고리 / 작업</th>
                <th>시스템</th>
                <th>데이터베이스 / 스키마</th>
                <th>Asset / Entity</th>
                <th>담당자</th>
                <th>CR / 단계</th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((event) => (
                <EventRow event={event} key={event.event_id} onOpenDetail={onOpenDetail} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {page.next_cursor && (
        <p className="data-change-page-boundary">다음 이벤트가 있습니다. 추가 페이지는 서버 cursor 조회로만 제공됩니다.</p>
      )}
    </section>
  )
}

function EventRow({
  event,
  onOpenDetail,
}: {
  event: ChangeHistoryEvent
  onOpenDetail: (eventId: string) => void
}) {
  const occurrence = event.source_occurred_at ?? event.detected_at
  return (
    <tr>
      <td>
        <button className="data-change-event-link" type="button" onClick={() => onOpenDetail(event.event_id)}>
          <time dateTime={occurrence}>{formatTimestamp(occurrence)}</time>
          {!event.source_occurred_at && <small>감지 시각 (detected)</small>}
        </button>
      </td>
      <td>{event.precision ? optionLabel(precisionOptions, event.precision) : '정밀도 미제공'}</td>
      <td><strong>{optionLabel(categoryOptions, event.category)}</strong><small>{optionLabel(operationOptions, event.operation)}</small></td>
      <td><strong>{event.system.system_id ?? '시스템 미확정'}</strong><small>{event.system.resolution}</small></td>
      <td><strong>{event.locator?.database_name ?? '—'}</strong><small>{event.locator?.schema_name ?? '—'}</small></td>
      <td><strong>{event.locator?.asset_name ?? event.entity_key}</strong><small>{event.entity_key}</small></td>
      <td><strong>{event.assignee.subject_id ?? '미지정'}</strong><small>{event.assignee.responsibility}</small></td>
      <td><strong>{event.current_primary?.change_request_id ?? 'CR 미연결'}</strong><small>{optionLabel(stageOptions, event.current_stage)}</small></td>
    </tr>
  )
}

function DetailView({ detail }: { detail: DetailState }) {
  const { event, links } = detail
  return (
    <div className="data-change-detail">
      <dl className="data-change-detail-facts">
        <DetailFact label="source aspect" value={event.source_aspect} />
        <DetailFact label="URN" value={event.asset_urn} code />
        <DetailFact label="source occurred" value={formatTimestamp(event.source_occurred_at)} />
        <DetailFact label="detected" value={formatTimestamp(event.detected_at)} />
        <DetailFact label="captured" value={formatTimestamp(event.captured_at)} />
        <DetailFact label="precision" value={event.precision ? optionLabel(precisionOptions, event.precision) : '정밀도 미제공'} />
      </dl>
      <section className="data-change-semantic-diff" aria-labelledby="data-change-diff-title">
        <h3 id="data-change-diff-title">Bounded semantic diff</h3>
        <div>
          <article>
            <h4>Before</h4>
            <pre>{formatSemanticDocument(event.before)}</pre>
          </article>
          <article>
            <h4>After</h4>
            <pre>{formatSemanticDocument(event.after)}</pre>
          </article>
        </div>
      </section>
      <section className="data-change-cr-history" aria-labelledby="data-change-cr-title">
        <h3 id="data-change-cr-title">CR primary / candidate / history</h3>
        <dl>
          <div>
            <dt>Primary</dt>
            <dd>{formatCrLink(links.current_primary)}</dd>
          </div>
          <div>
            <dt>Candidates</dt>
            <dd>{links.current_candidates.length > 0 ? links.current_candidates.map(formatCrLink).join(', ') : '없음'}</dd>
          </div>
        </dl>
        {links.items.length === 0 ? (
          <p>기록된 CR 연결 이력이 없습니다.</p>
        ) : (
          <ol>
            {links.items.map((item) => (
              <li key={item.link_event_identity}>
                <strong>{item.action}</strong>
                <span>{item.change_request_id} · round {item.change_request_round}</span>
                <span>{item.reason}</span>
                <time dateTime={item.occurred_at}>{formatTimestamp(item.occurred_at)}</time>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  )
}

function DetailFact({ label, value, code = false }: { label: string; value: string; code?: boolean }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{code ? <code>{value}</code> : value}</dd>
    </div>
  )
}

function emptyFilterDraft(weekStart: string): FilterDraft {
  return {
    weekStart,
    changeType: '',
    category: '',
    precision: '',
    operation: '',
    platform: '',
    databaseName: '',
    schemaName: '',
    systemId: '',
    assigneeSubjectId: '',
    linkState: '',
    stage: '',
  }
}

function toEventFilters(draft: FilterDraft): ChangeHistoryEventFilters {
  return {
    weekStart: draft.weekStart,
    changeType: draft.changeType || undefined,
    category: draft.category || undefined,
    precision: draft.precision || undefined,
    operation: draft.operation || undefined,
    platform: trimmed(draft.platform),
    databaseName: trimmed(draft.databaseName),
    schemaName: trimmed(draft.schemaName),
    systemId: trimmed(draft.systemId),
    assigneeSubjectId: trimmed(draft.assigneeSubjectId),
    linkState: draft.linkState || undefined,
    stage: draft.stage || undefined,
    limit: EVENT_LIMIT,
  }
}

function trimmed(value: string): string | undefined {
  return value.trim() || undefined
}

function currentKstWeekStart(now = new Date()): string {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Seoul',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(now)
  const year = Number(parts.find((part) => part.type === 'year')?.value)
  const month = Number(parts.find((part) => part.type === 'month')?.value)
  const day = Number(parts.find((part) => part.type === 'day')?.value)
  const calendarDate = new Date(Date.UTC(year, month - 1, day))
  const daysSinceMonday = (calendarDate.getUTCDay() + 6) % 7
  calendarDate.setUTCDate(calendarDate.getUTCDate() - daysSinceMonday)
  return calendarDate.toISOString().slice(0, 10)
}

function isMondayDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const parsed = new Date(`${value}T00:00:00.000Z`)
  return Number.isFinite(parsed.getTime())
    && parsed.toISOString().slice(0, 10) === value
    && parsed.getUTCDay() === 1
}

function formatTimestamp(value: string | null): string {
  if (value === null) return '기록 없음'
  return new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(value))
}

function formatCount(value: number): string {
  return new Intl.NumberFormat('ko-KR').format(value)
}

function syncStateLabel(value: ChangeHistorySyncStatus): string {
  const labels: Record<ChangeHistorySyncStatus, string> = {
    SOURCE_NOT_CONFIGURED: '소스 미구성',
    SOURCE_AMBIGUOUS: '소스 모호',
    CHECKPOINT_NOT_AVAILABLE: '체크포인트 없음',
    CHECKPOINT_INVALID: '체크포인트 오류',
    CAPTURE_PENDING: '캡처 대기',
    CONTIGUOUS_CAPTURE_RECORDED: '연속 캡처 기록됨',
  }
  return labels[value]
}

function optionLabel<T extends string>(options: Array<[T, string]>, value: T): string {
  return options.find(([option]) => option === value)?.[1] ?? value
}

function formatSemanticDocument(value: Record<string, unknown> | null): string {
  return value === null ? '없음' : JSON.stringify(value, null, 2)
}

function formatCrLink(value: { change_request_id: string; change_request_round: number } | null): string {
  return value ? `${value.change_request_id} · round ${value.change_request_round}` : '없음'
}
