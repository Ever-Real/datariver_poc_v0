import { useCallback, useEffect, useMemo, useState } from 'react'
import type { SystemConfigurationEntry, SystemConfigurationTestResult } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import type { AdminSectionProps } from './MembershipAdmin'

const llmSystemIds = new Set<SystemConfigurationEntry['system_id']>([
  'LLM_CHAT_MODEL',
  'LLM_EMBEDDING',
  'LLM_RERANKER',
])

function llmTabLabel(systemId: SystemConfigurationEntry['system_id']) {
  if (systemId === 'LLM_CHAT_MODEL') return 'Chat Model'
  if (systemId === 'LLM_EMBEDDING') return 'Embedding'
  return 'Reranker'
}

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

function activationLabel(state: SystemConfigurationEntry['activation_state']) {
  const labels: Record<SystemConfigurationEntry['activation_state'], string> = {
    NOT_CONFIGURED: '미저장',
    SAVED_UNTESTED: '저장됨 · TEST 필요',
    TEST_NOT_AVAILABLE: 'TEST 미통과',
    TESTED: 'TEST 통과 · 활성화 가능',
    ACTIVATED_RESTART_REQUIRED: '활성화됨 · 재시작 필요',
    APPLIED_TO_API_PROCESS: '현재 API 적용됨',
    RUNTIME_NOT_IMPLEMENTED: '런타임 소비자 미구현',
  }
  return labels[state]
}

export function SystemConfigurationAdmin(props: AdminSectionProps) {
  const { api, context, reportError, requestConfirmation } = props
  const [items, setItems] = useState<SystemConfigurationEntry[]>([])
  const [selectedId, setSelectedId] = useState<SystemConfigurationEntry['system_id']>()
  const [draft, setDraft] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<SystemConfigurationTestResult>()
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
  const llmItems = useMemo(
    () => items.filter((item) => llmSystemIds.has(item.system_id)),
    [items],
  )
  const ordinaryItems = useMemo(
    () => items.filter((item) => !llmSystemIds.has(item.system_id)),
    [items],
  )
  const llmSelected = selected ? llmSystemIds.has(selected.system_id) : false
  useEffect(() => {
    setDraft(selected?.configuration_yaml || selected?.template_yaml || '')
    setTestResult(undefined)
  }, [selected])

  const canUpdate = context?.allowed_operations.includes('SYSTEM_CONFIGURATION_UPDATE') ?? false
  const canActivate = context?.allowed_operations.includes('SYSTEM_CONFIGURATION_ACTIVATE') ?? false
  const save = () => {
    if (!selected || !draft.trim() || !canUpdate || saving) return
    requestConfirmation({
      title: `${selected.label} 설정 저장`,
      summary: [`${selected.system_id}`, `v${selected.version}`, '비밀 값은 제출하지 않고 Docker secret 파일의 참조명만 저장합니다.'],
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
  const savedDocument = selected?.configuration_yaml || selected?.template_yaml || ''
  const dirty = Boolean(selected && draft !== savedDocument)
  const testSavedConfiguration = async () => {
    if (!selected || selected.version === 0 || dirty || testing) return
    setTesting(true); setTestResult(undefined); setError(undefined)
    try {
      const result = await api.testSystemConfiguration(selected.system_id)
      setTestResult(result)
      setItems((current) => current.map((item) => item.system_id === selected.system_id ? {
        ...item,
        activation_state: !item.runtime_supported
          ? 'RUNTIME_NOT_IMPLEMENTED'
          : result.status === 'AVAILABLE' ? 'TESTED' : 'TEST_NOT_AVAILABLE',
        tested_version: result.configuration_version,
        test_status: result.status,
        tested_at: result.tested_at,
      } : item))
    } catch (next) { setError(next); reportError(next) } finally { setTesting(false) }
  }
  const activate = () => {
    if (!selected || !canActivate || selected.activation_state !== 'TESTED') return
    requestConfirmation({
      title: `${selected.label} 설정 활성화`,
      summary: [
        `${selected.system_id} · v${selected.version}`,
        '현재 TEST를 통과한 정확한 버전을 다음 프로세스 시작 설정으로 선택합니다.',
        selected.restart_scope === 'API_AND_WORKERS' ? '활성화 후 API와 관련 Worker를 재시작해야 합니다.' : '활성화 후 API를 재시작해야 합니다.',
      ],
      execute: async () => {
        const activated = await api.activateSystemConfiguration(selected.system_id, selected.version)
        setItems((current) => current.map((item) => item.system_id === activated.system_id ? activated : item))
      },
    })
  }

  return <section className="panel admin-system-settings">
    <div className="section-heading"><div><h3>시스템 설정</h3><p className="muted">개발 환경의 시스템별 주소·모델·비민감 옵션을 YAML로 관리합니다. 실행 시크릿은 운영자 관리 영역에 남습니다.</p></div><button className="button button-secondary" onClick={() => void load()} type="button">새로고침</button></div>
    <div className="admin-system-settings-workspace">
      <nav aria-label="설정 시스템 목록" className="admin-system-settings-list" role="tablist">
        {ordinaryItems.map((item) => <button aria-selected={selected?.system_id === item.system_id} className={selected?.system_id === item.system_id ? 'active' : ''} key={item.system_id} onClick={() => setSelectedId(item.system_id)} role="tab" type="button"><span className={`badge ${item.state === 'CONFIGURED' ? '' : 'badge-soft'}`}>{item.state}</span><strong>{item.label}</strong></button>)}
        {llmItems.length > 0 && <button aria-selected={llmSelected} className={llmSelected ? 'active' : ''} onClick={() => setSelectedId((llmSelected ? selectedId : llmItems[0]?.system_id) ?? llmItems[0]?.system_id)} role="tab" type="button"><span className={`badge ${llmItems.every((item) => item.state === 'CONFIGURED') ? '' : 'badge-soft'}`}>{llmItems.filter((item) => item.state === 'CONFIGURED').length}/{llmItems.length}</span><strong>LLM Models</strong></button>}
        {!loading && items.length === 0 && <p>표시 가능한 설정 항목이 없습니다.</p>}
      </nav>
      <section aria-live="polite" className="admin-system-settings-detail">
        {loading ? <p className="muted">서버 구성 상태를 불러오는 중입니다.</p> : !selected ? <p className="muted">왼쪽에서 시스템을 선택하세요.</p> : <>
          <header className="flex items-start justify-between gap-3"><div><span className="eyebrow">{selected.system_id}</span><h4>{selected.label}</h4></div>{canUpdate && <button className="button button-secondary" disabled={!selected.template_yaml} onClick={() => setDraft(selected.template_yaml)} type="button">샘플 양식 복원</button>}</header>
          {llmSelected && <div className="admin-system-llm-tabs" role="tablist" aria-label="LLM 모델 설정">
            {llmItems.map((item) => <button key={item.system_id} type="button" role="tab" aria-selected={selected.system_id === item.system_id} className={`button ${selected.system_id === item.system_id ? '' : 'button-secondary'}`} onClick={() => setSelectedId(item.system_id)}>{llmTabLabel(item.system_id)}</button>)}
          </div>}
          <dl className="summary-list">
            <div><dt>구성 상태</dt><dd><span className="badge">{stateLabel(selected.state)}</span></dd></div>
            <div><dt>관리 경로</dt><dd>{selected.management_plane === 'DEVELOPMENT_DATABASE' ? '개발 DB 설정' : selected.management_plane === 'DEPLOYMENT' ? '배포 설정' : '승인 Provider profile'}</dd></div>
            <div><dt>Embed</dt><dd>{embedLabel(selected.embedding_state)}</dd></div>
            <div><dt>Version</dt><dd>v{selected.version}</dd></div>
            <div><dt>적용 수명주기</dt><dd><span className="badge">{activationLabel(selected.activation_state)}</span></dd></div>
            <div><dt>TEST 버전</dt><dd>{selected.tested_version ? `v${selected.tested_version} · ${selected.test_status}` : '—'}</dd></div>
            <div><dt>활성 버전</dt><dd>{selected.activated_version ? `v${selected.activated_version}` : '—'}</dd></div>
            <div><dt>현재 API 적용 버전</dt><dd>{selected.applied_version ? `v${selected.applied_version}` : '—'}</dd></div>
          </dl>
          {canUpdate ? <>
            {!selected.configuration_yaml && <p className="callout">아직 저장된 설정이 없어 서버가 관리하는 비밀 없는 샘플 양식을 표시합니다. 실제 주소와 비민감 옵션을 입력한 뒤 저장하세요.</p>}
            <label className="form-field admin-system-yaml-field"><span>YAML connection settings</span><textarea aria-label={`${selected.label} YAML 설정`} className="admin-system-yaml" onChange={(event) => { setDraft(event.target.value); setTestResult(undefined) }} spellCheck="false" value={draft} /><small>비밀번호·토큰·API 키 값은 이 화면에서 제출할 수 없습니다. <code>file:/run/secrets/&lt;name&gt;</code> 형식의 Docker secret 참조명만 입력하세요.</small></label>
          </> : <p className="callout">이 환경에서는 설정 YAML을 편집할 수 없습니다. 배포 설정과 승인 Provider profile을 사용하세요.</p>}
          {selected.display_yaml && <section className="rounded-enterprise border border-slate-300 bg-slate-50 p-3" aria-label={`${selected.label} 저장된 비밀 제외 설정`}><span className="eyebrow">Saved non-secret configuration</span><h5 className="mb-2 mt-1 text-xs text-navy-900">저장된 설정 요약</h5><pre className="m-0 overflow-auto whitespace-pre-wrap text-[11px] leading-5 text-slate-700">{selected.display_yaml}</pre><small className="mt-2 block text-[9px] text-slate-500">실제 실행 시크릿은 포함하지 않습니다. 표시된 <code>secret_references</code>는 Docker secret 파일의 참조명입니다.</small></section>}
          {testResult && <p className={`callout m-0 ${testResult.status === 'AVAILABLE' ? 'border-l-green-600' : 'border-l-amber-600'}`} role="status"><strong>{testResult.status}</strong> · {testResult.scope} · {testResult.latency_ms}ms<br />{testResult.detail}</p>}
          {canUpdate && <div className="action-row"><button className="button button-secondary" disabled={selected.version === 0 || dirty || testing} title={selected.version === 0 ? '먼저 설정을 SAVE하세요.' : dirty ? '변경사항을 SAVE한 뒤 저장된 설정을 TEST하세요.' : '저장된 설정의 서버 고정 probe를 실행합니다.'} onClick={() => void testSavedConfiguration()} type="button">{testing ? 'TESTING…' : 'TEST'}</button><button className="button button-secondary" disabled={!canActivate || selected.activation_state !== 'TESTED'} title={!selected.runtime_supported ? '현재 아키텍처에 이 설정을 소비하는 런타임 어댑터가 없습니다.' : !canActivate ? '활성화에는 최근 WebAuthn 보증이 필요합니다.' : 'TEST를 통과한 현재 버전만 활성화할 수 있습니다.'} onClick={activate} type="button">ACTIVATE</button><button className="button" disabled={!draft.trim() || saving || !dirty} onClick={save} type="button">{saving ? '저장 중…' : 'SAVE'}</button></div>}
          {selected.activation_state === 'ACTIVATED_RESTART_REQUIRED' && <p className="callout m-0">활성 버전은 저장되었지만 실행 중인 프로세스에는 아직 적용되지 않았습니다. {selected.restart_scope === 'API_AND_WORKERS' ? 'API와 이 연결을 사용하는 Worker' : 'API'}를 재시작하세요.</p>}
          {selected.activation_state === 'APPLIED_TO_API_PROCESS' && selected.restart_scope === 'API_AND_WORKERS' && <p className="callout m-0">현재 API는 이 버전을 시작 시 로드했습니다. 관련 Worker도 동일한 배포 설정으로 재시작해야 하며, 이 화면은 Worker 적용 완료를 추정하지 않습니다.</p>}
        </>}
      </section>
    </div>
    <ErrorNotice error={error} />
  </section>
}
