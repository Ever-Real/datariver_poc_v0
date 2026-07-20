import { useCallback, useEffect, useMemo, useState } from 'react'
import type { SystemConfigurationEntry } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import type { AdminSectionProps } from './MembershipAdmin'

function stateLabel(state: SystemConfigurationEntry['state']) {
  if (state === 'CONFIGURED') return '구성됨'
  if (state === 'GOVERNED_PROFILE_REQUIRED') return '승인 Provider profile 필요'
  return '미구성'
}

function embedLabel(state: SystemConfigurationEntry['embedding_state']) {
  if (state === 'AVAILABLE') return '승인됨'
  if (state === 'DISABLED') return '비활성'
  if (state === 'NOT_CONFIGURED') return '미구성'
  return '해당 없음'
}

export function SystemConfigurationAdmin({ api, reportError }: AdminSectionProps) {
  const [items, setItems] = useState<SystemConfigurationEntry[]>([])
  const [selectedId, setSelectedId] = useState<SystemConfigurationEntry['system_id']>()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>()

  const load = useCallback(async () => {
    setLoading(true); setError(undefined)
    try {
      const next = await api.listSystemConfiguration()
      setItems(next)
      setSelectedId((current) => current && next.some((item) => item.system_id === current)
        ? current
        : next[0]?.system_id)
    } catch (next) { setError(next); reportError(next) } finally { setLoading(false) }
  }, [api, reportError])

  useEffect(() => { void load() }, [load])
  const selected = useMemo(
    () => items.find((item) => item.system_id === selectedId),
    [items, selectedId],
  )

  return <section className="panel admin-system-settings">
    <div className="section-heading"><div><h3>시스템 설정</h3><p className="muted">서버가 판정한 구성 상태만 표시합니다. URL·비밀번호·secret reference는 반환하지 않습니다.</p></div><button className="button button-secondary" onClick={() => void load()} type="button">새로고침</button></div>
    <div className="admin-system-settings-workspace">
      <nav aria-label="설정 시스템 목록" className="admin-system-settings-list" role="tablist">
        {items.map((item) => <button aria-selected={selected?.system_id === item.system_id} className={selected?.system_id === item.system_id ? 'active' : ''} key={item.system_id} onClick={() => setSelectedId(item.system_id)} role="tab" type="button"><span className={`badge ${item.state === 'CONFIGURED' ? '' : 'badge-soft'}`}>{item.state}</span><strong>{item.label}</strong></button>)}
        {!loading && items.length === 0 && <p>표시 가능한 설정 항목이 없습니다.</p>}
      </nav>
      <section aria-live="polite" className="admin-system-settings-detail">
        {loading ? <p className="muted">서버 구성 상태를 불러오는 중입니다.</p> : !selected ? <p className="muted">왼쪽에서 시스템을 선택하세요.</p> : <>
          <header><span className="eyebrow">{selected.system_id}</span><h4>{selected.label}</h4></header>
          <dl className="summary-list">
            <div><dt>구성 상태</dt><dd><span className="badge">{stateLabel(selected.state)}</span></dd></div>
            <div><dt>관리 경로</dt><dd>{selected.management_plane === 'DEPLOYMENT' ? '운영 배포 설정' : '승인 Provider profile'}</dd></div>
            <div><dt>Secret</dt><dd>{selected.secret_reference_configured ? 'secret reference 구성됨' : '해당 없음 또는 미구성'}</dd></div>
            <div><dt>Embed</dt><dd>{embedLabel(selected.embedding_state)}</dd></div>
          </dl>
          <p className="callout">이 화면은 YAML·endpoint·password를 편집하거나 연결을 시험하지 않습니다. 인프라 접속정보는 운영 secret manager와 배포 검토에서, LLM은 승인 Provider profile 변경 절차에서 관리합니다.</p>
        </>}
      </section>
    </div>
    <ErrorNotice error={error} />
  </section>
}
