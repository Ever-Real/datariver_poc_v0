import { Activity, ShieldCheck } from 'lucide-react'
import type { Capability } from '../../api/types'

export function CapabilityObservation({
  items,
  loading = false,
}: {
  items: Capability[]
  loading?: boolean
}) {
  return (
    <section className="monitoring-capabilities" aria-labelledby="capability-title">
      <header>
        <Activity size={16} aria-hidden="true" />
        <div>
          <p className="eyebrow">Current server observation</p>
          <h2 id="capability-title">Platform capability state</h2>
        </div>
      </header>
      {loading ? (
        <p className="monitoring-capability-state">상태를 불러오는 중입니다.</p>
      ) : items.length === 0 ? (
        <p className="monitoring-capability-state">
          서버가 표시 가능한 capability 결과를 반환하지 않았습니다.
        </p>
      ) : (
        <ul>
          {items.map((capability) => (
            <li key={capability.name}>
              <span
                className={`status-dot status-${capability.state}`}
                aria-hidden="true"
              />
              <strong>{capability.name}</strong>
              <span className="badge">{capability.state}</span>
              <small>
                {capability.latency_ms == null
                  ? '지연시간 미수집'
                  : `${capability.latency_ms} ms`}
              </small>
              <time dateTime={capability.observed_at}>{capability.observed_at}</time>
            </li>
          ))}
        </ul>
      )}
      <footer>
        <ShieldCheck size={13} aria-hidden="true" />
        capability 상태와 외부 주소는 모두 서버 응답에서만 옵니다.
      </footer>
    </section>
  )
}
