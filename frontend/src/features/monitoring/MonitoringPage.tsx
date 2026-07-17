import { useCallback, useEffect, useState } from 'react'
import { Activity, ExternalLink, Monitor, RefreshCw, ShieldCheck } from 'lucide-react'
import type { ApiClient } from '../../api/client'
import type { CapabilitiesResponse, Capability, ExternalSystemLink } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { PageTitle } from '../../components/layout/PageTitle'

export function MonitoringPage({ client }: { client: ApiClient }) {
  const [capabilities, setCapabilities] = useState<Capability[]>([])
  const [links, setLinks] = useState<ExternalSystemLink[]>([])
  const [error, setError] = useState<unknown>()
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    setError(undefined)
    setLoading(true)
    try {
      const response = await client.request<CapabilitiesResponse>('/capabilities')
      setCapabilities(response.items)
      setLinks(response.external_system_links)
    } catch (next) {
      setError(next)
    } finally {
      setLoading(false)
    }
  }, [client])

  useEffect(() => { void refresh() }, [refresh])

  const grafana = links.find((link) => link.system_id === 'grafana')
  return (
    <section className="monitoring-page">
      <PageTitle
        icon="MO"
        eyebrow="Infrastructure monitoring"
        title="Infrastructure Monitoring"
        description="서버가 검증한 플랫폼 capability와 관측성 링크만 표시합니다."
        actions={(
          <div className="monitoring-title-actions">
            <button className="button button-secondary" type="button" onClick={() => void refresh()} disabled={loading}><RefreshCw size={14} />새로고침</button>
            {grafana ? (
              <a className="button" href={grafana.url} target="_blank" rel="noopener noreferrer"><ExternalLink size={14} />{grafana.label} 열기</a>
            ) : (
              <button className="button button-secondary" type="button" disabled title="서버가 Grafana 외부 링크를 제공하지 않았습니다."><ExternalLink size={14} />Grafana 링크 없음</button>
            )}
          </div>
        )}
      />
      <ErrorNotice error={error} />
      <div className="monitoring-frame" aria-busy={loading}>
        {loading ? (
          <div className="monitoring-frame-state"><span className="loader" /><p>플랫폼 상태를 조회하고 있습니다.</p></div>
        ) : grafana ? (
          <div className="monitoring-approved-link">
            <span><Monitor size={35} aria-hidden="true" /></span>
            <div>
              <p className="eyebrow">Approved external observability</p>
              <h2>{grafana.label}</h2>
              <p>이 링크는 서버 allowlist 검증을 거친 외부 관측성 화면입니다. 현재 배포에는 Grafana SSO·CSP sandbox 증거가 없으므로, 세션/프레임 경계를 우회하는 iframe 대신 새 창에서 엽니다.</p>
              <a className="button" href={grafana.url} target="_blank" rel="noopener noreferrer"><ExternalLink size={14} />{grafana.label} 열기</a>
            </div>
          </div>
        ) : (
          <div className="monitoring-frame-state">
            <Monitor size={38} aria-hidden="true" />
            <div><h2>승인된 Grafana 링크가 없습니다.</h2><p>운영자가 서버의 `UI_GRAFANA_URL`을 허용된 HTTPS 주소로 구성하면 이 화면에 검증된 직접 링크가 나타납니다. 브라우저에서 임의 주소를 입력하거나 iframe을 생성하지 않습니다.</p></div>
          </div>
        )}
      </div>
      <section className="monitoring-capabilities" aria-labelledby="capability-title">
        <header><Activity size={16} aria-hidden="true" /><div><p className="eyebrow">Current server observation</p><h2 id="capability-title">Platform capability state</h2></div></header>
        {loading ? <p className="monitoring-capability-state">상태를 불러오는 중입니다.</p> : capabilities.length === 0 ? <p className="monitoring-capability-state">서버가 표시 가능한 capability 결과를 반환하지 않았습니다.</p> : (
          <ul>
            {capabilities.map((capability) => (
              <li key={capability.name}>
                <span className={`status-dot status-${capability.state}`} aria-hidden="true" />
                <strong>{capability.name}</strong>
                <span className="badge">{capability.state}</span>
                <small>{capability.latency_ms == null ? '지연시간 미수집' : `${capability.latency_ms} ms`}</small>
                <time dateTime={capability.observed_at}>{capability.observed_at}</time>
              </li>
            ))}
          </ul>
        )}
        <footer><ShieldCheck size={13} aria-hidden="true" /> capability 상태와 외부 주소는 모두 서버 응답에서만 옵니다.</footer>
      </section>
    </section>
  )
}
