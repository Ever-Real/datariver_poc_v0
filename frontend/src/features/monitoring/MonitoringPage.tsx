import { useCallback, useEffect, useState } from 'react'
import { Activity, ExternalLink, Monitor, RefreshCw, ShieldCheck } from 'lucide-react'
import type { ApiClient } from '../../api/client'
import type { CapabilitiesResponse, Capability, ExternalSystemLink, GrafanaEmbed } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { PageTitle } from '../../components/layout/PageTitle'

export function MonitoringPage({ client }: { client: ApiClient }) {
  const [capabilities, setCapabilities] = useState<Capability[]>([])
  const [links, setLinks] = useState<ExternalSystemLink[]>([])
  const [grafanaEmbed, setGrafanaEmbed] = useState<GrafanaEmbed>({ state: 'NOT_CONFIGURED' })
  const [error, setError] = useState<unknown>()
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    setError(undefined)
    setLoading(true)
    try {
      const response = await client.request<CapabilitiesResponse>('/capabilities')
      setCapabilities(response.items)
      setLinks(response.external_system_links)
      setGrafanaEmbed(response.grafana_embed)
    } catch (next) {
      setError(next)
    } finally {
      setLoading(false)
    }
  }, [client])

  useEffect(() => { void refresh() }, [refresh])

  const grafana = links.find((link) => link.system_id === 'grafana')
  const embeddedGrafanaUrl = grafanaEmbed.state === 'AVAILABLE' ? grafanaEmbed.url : undefined
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
        ) : embeddedGrafanaUrl ? (
          <div className="monitoring-approved-embed">
            <div className="monitoring-embed-notice">
              <span><Monitor size={20} aria-hidden="true" /></span>
              <p>서버가 현재 환경의 Grafana 주소를 확인하여, 이 세션에서는 sandboxed dashboard를 표시합니다.</p>
              {grafana && <a className="button button-secondary" href={grafana.url} target="_blank" rel="noopener noreferrer"><ExternalLink size={14} />새 창으로 열기</a>}
            </div>
            <iframe className="monitoring-grafana-frame" loading="lazy" referrerPolicy="no-referrer" sandbox="allow-forms allow-same-origin allow-scripts" src={embeddedGrafanaUrl} title="Grafana Dashboard" />
          </div>
        ) : grafana ? (
          <div className="monitoring-approved-link">
            <span><Monitor size={35} aria-hidden="true" /></span>
            <div>
              <p className="eyebrow">Approved external observability</p>
              <h2>{grafana.label}</h2>
              <p>이 링크는 서버가 제공한 외부 관측성 화면입니다. iframe을 사용할 수 없는 환경에서는 세션/프레임 경계를 우회하지 않고 새 창에서 엽니다.</p>
              <a className="button" href={grafana.url} target="_blank" rel="noopener noreferrer"><ExternalLink size={14} />{grafana.label} 열기</a>
            </div>
          </div>
        ) : (
          <div className="monitoring-frame-state">
            <Monitor size={38} aria-hidden="true" />
            <div><h2>Grafana 링크가 없습니다.</h2><p>관리자가 시스템 설정에서 Grafana URL을 저장하거나 배포 설정을 제공하면 이 화면에 서버가 제공한 링크가 나타납니다.</p></div>
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
