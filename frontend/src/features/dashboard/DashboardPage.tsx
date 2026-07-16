import { useCallback, useEffect, useState } from 'react'
import type { ApiClient } from '../../api/client'
import type { Capability, OperationsSummary } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'

export function DashboardPage({ client }: { client: ApiClient }) {
  const [capabilities, setCapabilities] = useState<Capability[]>([])
  const [summary, setSummary] = useState<OperationsSummary>()
  const [error, setError] = useState<unknown>()

  const refresh = useCallback(async () => {
    setError(undefined)
    try {
      const [capabilityResult, summaryResult] = await Promise.all([
        client.request<{ items: Capability[] }>('/capabilities'),
        client.request<OperationsSummary>('/operations/summary'),
      ])
      setCapabilities(capabilityResult.items)
      setSummary(summaryResult)
    } catch (next) {
      setError(next)
    }
  }, [client])

  useEffect(() => { void refresh() }, [refresh])

  return (
    <section>
      <div className="page-heading">
        <div><p className="eyebrow">운영 관제</p><h2>플랫폼 상태</h2></div>
        <button className="button button-secondary" onClick={() => void refresh()}>새로고침</button>
      </div>
      <ErrorNotice error={error} />
      <div className="metric-grid">
        {capabilities.map((item) => (
          <article className="metric-card" key={item.name}>
            <span className={`status-dot status-${item.state}`} />
            <h3>{item.name}</h3>
            <strong>{item.state}</strong>
            <small>{item.latency_ms == null ? '지연시간 없음' : `${item.latency_ms} ms`}</small>
          </article>
        ))}
      </div>
      {summary && (
        <div className="panel-grid">
          <StatePanel title="업로드" values={summary.uploads_by_state} />
          <StatePanel title="변경 요청" values={summary.changes_by_state} />
          <StatePanel title="작업" values={summary.jobs_by_state} />
          <article className="panel">
            <p className="eyebrow">Outbox</p>
            <h3>{summary.unpublished_outbox_events.toLocaleString()}건 대기</h3>
            <p>최장 대기 {summary.oldest_unpublished_age_seconds ?? 0}초</p>
            <p className={summary.dead_lettered_outbox_events ? 'notice notice-error' : 'muted'}>
              Dead letter {summary.dead_lettered_outbox_events.toLocaleString()}건
            </p>
          </article>
          <article className="panel">
            <p className="eyebrow">보존 자동화</p>
            <h3>안전 잠금</h3>
            <p className="notice">WORM 검증과 승인 워크플로우가 준비될 때까지 자동 삭제가 중지됩니다.</p>
          </article>
        </div>
      )}
    </section>
  )
}

function StatePanel({ title, values }: { title: string; values: Record<string, number> }) {
  return (
    <article className="panel">
      <p className="eyebrow">{title}</p>
      {Object.keys(values).length === 0 ? <p className="muted">현재 항목 없음</p> : (
        <ul className="state-list">
          {Object.entries(values).map(([name, count]) => <li key={name}><span>{name}</span><strong>{count}</strong></li>)}
        </ul>
      )}
    </article>
  )
}
