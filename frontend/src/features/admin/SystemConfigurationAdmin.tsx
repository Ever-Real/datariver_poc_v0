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
  if (state === 'AVAILABLE') return '사용 가능'
  if (state === 'DISABLED') return '비활성'
  if (state === 'NOT_CONFIGURED') return '미구성'
  return '해당 없음'
}

export function SystemConfigurationAdmin(props: AdminSectionProps) {
  const { api, context, reportError, requestConfirmation } = props
  const [items, setItems] = useState<SystemConfigurationEntry[]>([])
  const [selectedId, setSelectedId] = useState<SystemConfigurationEntry['system_id']>()
  const [draft, setDraft] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<unknown>()

  const load = useCallback(async () => {
    setLoading(true); setError(undefined)
    try {
      const next = await api.listSystemConfiguration()
      setItems(next)
      setSelectedId((current) => current && next.some((item) => item.system_id === current)
        ? current : next[0]?.system_id)
    } catch (next) { setError(next); reportError(next) } finally { setLoading(false) }
  }, [api, reportError])

  useEffect(() => { void load() }, [load])
  const selected = useMemo(
    () => items.find((item) => item.system_id === selectedId),
    [items, selectedId],
  )
  useEffect(() => { setDraft(selected?.configuration_yaml ?? '') }, [selected])

  const canUpdate = context?.allowed_operations.includes('SYSTEM_CONFIGURATION_UPDATE') ?? false
  const save = () => {
    if (!selected || !draft.trim() || !canUpdate || saving) return
    requestConfirmation({
      title: `${selected.label} 설정 저장`,
      summary: [`${selected.system_id}`, `v${selected.version}`, '민감한 값은 저장 후에도 마스킹됩니다.'],
      execute: async () => {
        setSaving(true)
        try {
          const saved = await api.updateSystemConfiguration(selected.system_id, draft, selected.version)
          setItems((current) => current.map((item) => item.system_id === saved.system_id ? saved : item))
          setDraft(saved.configuration_yaml)
        } catch (next) { setError(next); reportError(next); throw next } finally { setSaving(false) }
      },
    })
  }

  return <section className="panel admin-system-settings">
    <div className="section-heading"><div><h3>시스템 설정</h3><p className="muted">시스템별 YAML 연결 정보를 한 곳에서 확인합니다. 비밀번호·토큰·키 값은 조회 시 항상 마스킹됩니다.</p></div><button className="button button-secondary" onClick={() => void load()} type="button">새로고침</button></div>
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
            <div><dt>관리 경로</dt><dd>{selected.management_plane === 'DEVELOPMENT_DATABASE' ? '개발 DB 설정' : selected.management_plane === 'DEPLOYMENT' ? '배포 설정' : '승인 Provider profile'}</dd></div>
            <div><dt>Embed</dt><dd>{embedLabel(selected.embedding_state)}</dd></div>
            <div><dt>Version</dt><dd>v{selected.version}</dd></div>
          </dl>
          {canUpdate ? <label className="form-field"><span>YAML connection settings</span><textarea aria-label={`${selected.label} YAML 설정`} className="admin-system-yaml" onChange={(event) => setDraft(event.target.value)} spellCheck="false" value={draft} /><small>마스킹된 <code>********</code> 값은 그대로 저장하면 기존 값이 유지됩니다. 변경할 값만 새 값으로 교체하세요.</small></label> : <p className="callout">이 환경에서는 설정 YAML을 편집할 수 없습니다. 배포 설정과 승인 Provider profile을 사용하세요.</p>}
          {canUpdate && <div className="action-row"><button className="button" disabled={!draft.trim() || saving} onClick={save} type="button">{saving ? '저장 중…' : 'YAML 저장'}</button></div>}
        </>}
      </section>
    </div>
    <ErrorNotice error={error} />
  </section>
}
