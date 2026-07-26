import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { SystemConfigurationEntry, SystemConfigurationTestResult } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { useRovingTabs } from '../../components/common/useRovingTabs'
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
type SystemTabId = SystemConfigurationEntry['system_id'] | 'LLM_MODELS' | 'CORE_DASHBOARD'

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
    DEPLOYMENT_MANAGED: '배포 환경·secret 관리',
    RUNTIME_NOT_IMPLEMENTED: '런타임 소비자 미구현',
  }
  return labels[state]
}

/** YAML 텍스트에서 key: value 맵을 추출 */
function parseYamlSimple(yaml: string): Record<string, string> {
  const result: Record<string, string> = {}
  for (const line of yaml.split('\n')) {
    if (!line.trim() || line.trim().startsWith('#')) continue
    const match = line.match(/^([a-zA-Z0-9_-]+):\s*(.*)$/)
    if (match?.[1]) result[match[1]] = match[2] ?? ''
  }
  return result
}

/** 맵에서 YAML 텍스트를 재구성 (주석/빈줄은 원본에서 유지) */
function applyValuesToYaml(yaml: string, updates: Record<string, string>): string {
  return yaml.split('\n').map((line) => {
    if (!line.trim() || line.trim().startsWith('#')) return line
    const match = line.match(/^([a-zA-Z0-9_-]+):\s*(.*)$/)
    if (match?.[1] && match[1] in updates) {
      return `${match[1]}: ${updates[match[1]]}`
    }
    return line
  }).join('\n')
}

/** connection_mode 등 알려진 enum 필드 */
const CONNECTION_MODE_OPTIONS = ['LOCAL_OLLAMA', 'INTRANET_OPENAI_COMPATIBLE'] as const

/** 특정 키가 드롭다운 선택 대상인지 */
function isDropdownKey(key: string): boolean {
  return key === 'connection_mode'
}

/** 드롭다운 옵션 가져오기 */
function getDropdownOptions(key: string): string[] {
  if (key === 'connection_mode') return [...CONNECTION_MODE_OPTIONS]
  return []
}

/** YAML 모드에서 각 시스템 타입별 가이드 주석 추가 */
function enrichYamlWithComments(yaml: string, systemId: string): string {
  const commentMap: Record<string, Record<string, string>> = {
    LLM_CHAT_MODEL: {
      connection_mode: '# 로컬 Ollama: LOCAL_OLLAMA | 사내 서버: INTRANET_OPENAI_COMPATIBLE',
      base_url: '# 예: http://host.docker.internal:11434 (로컬 Ollama)',
      model: '# 예: llama3.1:8b (Ollama) 또는 gpt-4o-mini',
      timeout_seconds: '# 요청 타임아웃(초). 기본값: 120',
      context_tokens: '# 최대 컨텍스트 토큰 수. 기본값: 8192',
    },
    LLM_EMBEDDING: {
      connection_mode: '# LOCAL_OLLAMA 또는 INTRANET_OPENAI_COMPATIBLE',
      base_url: '# 예: http://host.docker.internal:11434',
      model: '# 예: nomic-embed-text:latest',
      dimensions: '# 임베딩 차원 수. 모델에 따라 다름 (예: 768, 1536)',
    },
    POSTGRESQL: {
      host: '# 예: localhost 또는 postgres (Docker Compose 서비스명)',
      port: '# 기본값: 5432',
      database: '# 데이터베이스 이름',
    },
    REDIS_CACHE: {
      host: '# 예: localhost 또는 valkey-cache',
      port: '# 기본값: 6379',
      db: '# Redis DB 번호 (0~15)',
    },
  }
  const guide = commentMap[systemId] ?? {}
  if (Object.keys(guide).length === 0) return yaml
  return yaml.split('\n').map((line) => {
    if (!line.trim() || line.trim().startsWith('#')) return line
    const match = line.match(/^([a-zA-Z0-9_-]+):/)
    if (match?.[1] && guide[match[1]]) {
      return `${guide[match[1]]}\n${line}`
    }
    return line
  }).join('\n')
}

function getPlaceholder(systemId: string, key: string): string {
  if (systemId === 'LLM_CHAT_MODEL' || systemId === 'LLM_EMBEDDING' || systemId === 'LLM_RERANKER') {
    if (key === 'base_url') return 'http://host.docker.internal:11434 (로컬 Ollama)'
    if (key === 'model') return systemId === 'LLM_EMBEDDING' ? 'nomic-embed-text:latest' : 'llama3.1:8b'
  }
  return `${key} 입력`
}

export function SystemConfigurationAdmin(props: AdminSectionProps) {
  const { api, context, reportError, requestConfirmation } = props
  const [items, setItems] = useState<SystemConfigurationEntry[]>([])
  const [selectedId, setSelectedId] = useState<SystemConfigurationEntry['system_id'] | 'CORE_DASHBOARD' | undefined>('CORE_DASHBOARD')
  const [draft, setDraft] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<SystemConfigurationTestResult>()
  const [error, setError] = useState<unknown>()
  // Form Mode를 기본값으로 설정
  const [viewMode, setViewMode] = useState<'YAML' | 'FORM'>('FORM')
  const loadRequest = useRef<{ generation: number; controller?: AbortController }>({
    generation: 0,
  })

  const load = useCallback(async () => {
    loadRequest.current.controller?.abort()
    const controller = new AbortController()
    const generation = loadRequest.current.generation + 1
    loadRequest.current = { generation, controller }
    setLoading(true); setError(undefined)
    try {
      const next = await api.listSystemConfiguration(controller.signal)
      if (controller.signal.aborted || loadRequest.current.generation !== generation) return
      setItems(next)
      setSelectedId((current) => current && (next.some((item) => item.system_id === current) || current === 'CORE_DASHBOARD')
        ? current : next[0]?.system_id)
    } catch (next) {
      if (!controller.signal.aborted) { setError(next); reportError(next) }
    } finally {
      if (!controller.signal.aborted && loadRequest.current.generation === generation) {
        setLoading(false)
      }
    }
  }, [api, reportError])

  useEffect(() => {
    void load()
    return () => loadRequest.current.controller?.abort()
  }, [load])

  const selected = useMemo(
    () => items.find((item) => item.system_id === selectedId),
    [items, selectedId],
  )
  const llmItems = useMemo(
    () => items.filter((item) => llmSystemIds.has(item.system_id)),
    [items],
  )
  const coreItems = useMemo(
    () => items.filter((item) => item.is_core),
    [items],
  )
  const ordinaryItems = useMemo(
    () => items.filter((item) => !llmSystemIds.has(item.system_id) && !item.is_core),
    [items],
  )
  const llmSelected = selectedId !== 'CORE_DASHBOARD' && selected ? llmSystemIds.has(selected.system_id) : false
  const systemTabIds = useMemo<SystemTabId[]>(() => [
    ...(coreItems.length > 0 ? ['CORE_DASHBOARD' as const] : []),
    ...ordinaryItems.map((item) => item.system_id),
    ...(llmItems.length > 0 ? ['LLM_MODELS' as const] : []),
  ], [coreItems.length, llmItems.length, ordinaryItems])
  const activeSystemTab: SystemTabId | undefined = selectedId === 'CORE_DASHBOARD' 
    ? 'CORE_DASHBOARD' 
    : llmSelected
      ? 'LLM_MODELS'
      : selected?.system_id ?? (coreItems.length > 0 ? 'CORE_DASHBOARD' : undefined)
  const selectSystemTab = (id: SystemTabId) => {
    setSelectedId(id === 'LLM_MODELS' ? llmItems[0]?.system_id : id)
  }
  const systemTabs = useRovingTabs({
    ids: systemTabIds,
    activeId: activeSystemTab,
    idPrefix: 'admin-system-config',
    onSelect: selectSystemTab,
  })
  useEffect(() => {
    setDraft(selected?.configuration_yaml || selected?.template_yaml || '')
    setTestResult(undefined)
  }, [selected])

  const canUpdate = context?.allowed_operations.includes('SYSTEM_CONFIGURATION_UPDATE') ?? false
  const canActivate = context?.allowed_operations.includes('SYSTEM_CONFIGURATION_ACTIVATE') ?? false
  const restartInstruction = selected?.restart_scope === 'API_AND_WORKERS'
    ? 'API와 관련 Worker를 재시작해야 합니다.'
    : selected?.restart_scope === 'WORKERS_ONLY'
      ? '관련 Worker를 재시작해야 합니다.'
      : 'API를 재시작해야 합니다.'
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
  
  const testDraftConfiguration = async (systemIdToTest?: string) => {
    const idToTest = systemIdToTest ?? selected?.system_id
    const itemToTest = items.find(i => i.system_id === idToTest)
    const isCurrentSelected = idToTest === selected?.system_id
    if (!itemToTest || testing) return
    setTesting(true); 
    if (isCurrentSelected) { setTestResult(undefined); setError(undefined) }
    try {
      // Use draft if it's the currently selected item and it's dirty, else use the item's saved yaml (or template)
      const yamlToTest = (isCurrentSelected && dirty) ? draft : (itemToTest.configuration_yaml || itemToTest.template_yaml || '')
      const result = await api.testDraftSystemConfiguration(itemToTest.system_id, yamlToTest)
      if (isCurrentSelected) setTestResult(result)
      setItems((current) => current.map((item) => item.system_id === itemToTest.system_id ? {
        ...item,
        activation_state: item.activation_state === 'DEPLOYMENT_MANAGED'
          ? 'DEPLOYMENT_MANAGED'
          : !item.runtime_supported
          ? 'RUNTIME_NOT_IMPLEMENTED'
          : result.status === 'AVAILABLE' ? 'TESTED' : 'TEST_NOT_AVAILABLE',
        tested_version: isCurrentSelected && dirty ? item.version : result.configuration_version,
        test_status: result.status,
        tested_at: result.tested_at,
      } : item))
    } catch (next) { 
      if (isCurrentSelected) { setError(next); reportError(next) }
      else reportError(next)
    } finally { setTesting(false) }
  }
  
  const testSavedConfiguration = testDraftConfiguration // Alias for compatibility with existing JSX if needed
  const activate = () => {
    if (!selected || !canActivate || selected.activation_state !== 'TESTED') return
    requestConfirmation({
      title: `${selected.label} 설정 활성화`,
      summary: [
        `${selected.system_id} · v${selected.version}`,
        '현재 TEST를 통과한 정확한 버전을 다음 프로세스 시작 설정으로 선택합니다.',
        `활성화 후 ${restartInstruction}`,
      ],
      execute: async () => {
        const activated = await api.activateSystemConfiguration(selected.system_id, selected.version)
        setItems((current) => current.map((item) => item.system_id === activated.system_id ? activated : item))
      },
    })
  }

  /** Form Mode: connection_requirements 기반 구조화된 폼 렌더링 */
  const renderFormMode = () => {
    if (!selected) return null
    const currentValues = parseYamlSimple(draft)
    const requirements = selected.connection_requirements ?? []

    const handleFieldChange = (key: string, value: string) => {
      const updated = { ...currentValues, [key]: value }
      setDraft(applyValuesToYaml(draft || Object.entries(updated).map(([k, v]) => `${k}: ${v}`).join('\n'), updated))
      setTestResult(undefined)
    }

    // connection_requirements가 있으면 구조화된 폼, 없으면 YAML 필드 기반
    if (requirements.length > 0) {
      return (
        <div className="admin-system-form-structured">
          {requirements.map((req) => {
            const isSecret = req.secret
            const isRequired = req.required
            const isDropdown = isDropdownKey(req.key)
            const currentVal = currentValues[req.key] ?? ''
            return (
              <label key={req.key} className="admin-system-form-field-row">
                <span className="admin-system-form-label">
                  {req.label}
                  {isRequired && <span className="admin-system-form-required" aria-label="필수">*</span>}
                  {isSecret && <span className="admin-system-form-secret-badge">🔑 secret 참조</span>}
                </span>
                {isSecret ? (
                  <div>
                    <input
                      type="text"
                      className="admin-system-form-input"
                      value={currentVal}
                      placeholder={req.example ?? `file:/run/secrets/${req.key}`}
                      onChange={(e) => handleFieldChange(req.key, e.target.value)}
                    />
                    <small className="admin-system-form-hint">
                      실제 비밀값이 아닌 Docker secret 파일 참조명을 입력하세요 (예: <code>file:/run/secrets/{req.key}</code>)
                    </small>
                  </div>
                ) : isDropdown ? (
                  <select
                    className="admin-system-form-input"
                    value={currentVal}
                    onChange={(e) => handleFieldChange(req.key, e.target.value)}
                  >
                    <option value="">-- 선택 --</option>
                    {getDropdownOptions(req.key).map((opt) => (
                      <option key={opt} value={opt}>{opt}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    className="admin-system-form-input"
                    value={currentVal}
                    placeholder={req.example ?? `${req.key} 값 입력`}
                    onChange={(e) => handleFieldChange(req.key, e.target.value)}
                  />
                )}
              </label>
            )
          })}
          <small className="admin-system-form-hint-global">
            비밀번호·토큰·API 키 값은 이 화면에서 제출할 수 없습니다. <code>file:/run/secrets/&lt;name&gt;</code> 형식의 Docker secret 참조명만 입력하세요.
          </small>
        </div>
      )
    }

    // connection_requirements 없을 경우 YAML 키 기반 폼
    return (
      <div className="admin-system-form-yaml-based">
        {draft.split('\n').map((line, idx) => {
          if (!line.trim() || line.trim().startsWith('#')) {
            return <div key={idx} className="admin-system-form-comment">{line || '\u00A0'}</div>
          }
          const match = line.match(/^([a-zA-Z0-9_-]+):\s*(.*)$/)
          if (!match) return <div key={idx} className="admin-system-form-unparseable">{line}</div>
          const [, key, val] = match
          const isDropdown = isDropdownKey(key!)
          return (
            <label key={idx} className="admin-system-form-field-row">
              <span className="admin-system-form-label">{key}</span>
              {isDropdown ? (
                <select
                  className="admin-system-form-input"
                  value={val ?? ''}
                  onChange={(e) => {
                    const newLines = draft.split('\n')
                    newLines[idx] = `${key}: ${e.target.value}`
                    setDraft(newLines.join('\n'))
                    setTestResult(undefined)
                  }}
                >
                  <option value="">-- 선택 --</option>
                  {getDropdownOptions(key!).map((opt) => (
                    <option key={opt} value={opt}>{opt}</option>
                  ))}
                </select>
              ) : (
                <input
                  type="text"
                  className="admin-system-form-input"
                  value={val ?? ''}
                  placeholder={getPlaceholder(selected.system_id, key!)}
                  onChange={(e) => {
                    const newLines = draft.split('\n')
                    newLines[idx] = `${key}: ${e.target.value}`
                    setDraft(newLines.join('\n'))
                    setTestResult(undefined)
                  }}
                />
              )}
            </label>
          )
        })}
        <small className="admin-system-form-hint-global">
          비밀번호·토큰·API 키 값은 이 화면에서 제출할 수 없습니다.
        </small>
      </div>
    )
  }

  return <section className="panel admin-system-settings">
    <div className="section-heading"><div><h3>시스템 설정</h3><p className="muted">연결 주소·모델·옵션을 관리합니다. 실행 시크릿(비밀번호/API 키)은 Docker secret 파일로 별도 관리됩니다.</p></div><button className="button button-secondary" onClick={() => void load()} type="button">새로고침</button></div>
    <div className="admin-system-settings-workspace">
      <nav aria-label="설정 시스템 목록" className="admin-system-settings-list" role="tablist">
        {coreItems.length > 0 && <h4 className="text-xs font-bold text-slate-500 uppercase mt-4 mb-2 ml-3 px-3">Core Systems</h4>}
        {coreItems.length > 0 && <button {...systemTabs.tabProps('CORE_DASHBOARD')} className={selectedId === 'CORE_DASHBOARD' || (selected?.is_core) ? 'active' : ''} onClick={() => selectSystemTab('CORE_DASHBOARD')} type="button"><span className={`badge ${coreItems.every((item) => item.state === 'CONFIGURED') ? '' : 'badge-soft'}`}>{coreItems.filter((item) => item.state === 'CONFIGURED').length}/{coreItems.length}</span><strong>Core Dashboard</strong></button>}
        {ordinaryItems.length > 0 && <h4 className="text-xs font-bold text-slate-500 uppercase mt-4 mb-2 ml-3 px-3">Extensions</h4>}
        {ordinaryItems.map((item) => <button {...systemTabs.tabProps(item.system_id)} className={selected?.system_id === item.system_id ? 'active' : ''} key={item.system_id} onClick={() => setSelectedId(item.system_id)} type="button"><span className={`badge ${item.state === 'CONFIGURED' ? '' : 'badge-soft'}`}>{stateLabel(item.state)}</span><strong>{item.label}</strong></button>)}
        {llmItems.length > 0 && <h4 className="text-xs font-bold text-slate-500 uppercase mt-4 mb-2 ml-3 px-3">AI Models</h4>}
        {llmItems.length > 0 && <button {...systemTabs.tabProps('LLM_MODELS')} className={llmSelected ? 'active' : ''} onClick={() => selectSystemTab('LLM_MODELS')} type="button"><span className={`badge ${llmItems.every((item) => item.state === 'CONFIGURED') ? '' : 'badge-soft'}`}>{llmItems.filter((item) => item.state === 'CONFIGURED').length}/{llmItems.length}</span><strong>LLM Models</strong></button>}
        {!loading && items.length === 0 && <p>표시 가능한 설정 항목이 없습니다.</p>}
      </nav>
      <section {...(activeSystemTab ? systemTabs.panelProps(activeSystemTab) : {})} aria-live="polite" className="admin-system-settings-detail">
        {loading ? <p className="muted">서버 구성 상태를 불러오는 중입니다.</p> : (selectedId === 'CORE_DASHBOARD' || (!selected && coreItems.length > 0)) ? (
          <div>
            <header className="flex items-start justify-between gap-3 mb-6"><div><span className="eyebrow">Dashboard</span><h4>Core Systems</h4><p className="muted" style={{ fontSize: 11 }}>배포 환경 변수로 관리되는 핵심 인프라 시스템의 상태를 한눈에 확인하고 테스트합니다.</p></div></header>
            <div className="grid gap-3">
              {coreItems.map(item => (
                <div key={item.system_id} className="flex items-center justify-between p-4 border border-slate-200 rounded-lg bg-white shadow-sm">
                  <div>
                    <h5 className="font-bold text-slate-800 text-sm">{item.label}</h5>
                    <div className="flex gap-2 mt-2 text-xs">
                      <span className={`badge ${item.state === 'CONFIGURED' ? '' : 'badge-soft'}`}>{stateLabel(item.state)}</span>
                      {item.test_status && <span className={`badge ${item.test_status === 'AVAILABLE' ? 'badge-soft' : 'badge-warning'}`}>{item.test_status}</span>}
                    </div>
                  </div>
                  <button className="button button-secondary" disabled={testing} onClick={() => void testDraftConfiguration(item.system_id)} type="button">{testing ? '테스트 중...' : '연결 테스트'}</button>
                </div>
              ))}
            </div>
          </div>
        ) : !selected ? <p className="muted">왼쪽에서 시스템을 선택하세요.</p> : <>
          <header className="flex items-start justify-between gap-3"><div><span className="eyebrow">{selected.system_id}</span><h4>{selected.label}</h4><p className="muted" style={{ fontSize: 11 }}>{selected.description}</p></div>{canUpdate && !selected.is_core && <button className="button button-secondary" disabled={!selected.template_yaml} onClick={() => setDraft(selected.template_yaml)} type="button">샘플 양식 복원</button>}</header>
          {llmSelected && <div className="admin-system-llm-tabs" role="group" aria-label="LLM 모델 설정">
            {llmItems.map((item) => <button key={item.system_id} type="button" aria-pressed={selected.system_id === item.system_id} className={`button ${selected.system_id === item.system_id ? '' : 'button-secondary'}`} onClick={() => setSelectedId(item.system_id)}>{llmTabLabel(item.system_id)}</button>)}
          </div>}
          <dl className="summary-list">
            <div><dt>구성 상태</dt><dd><span className="badge">{stateLabel(selected.state)}</span></dd></div>
            <div><dt>관리 경로</dt><dd>{selected.management_plane === 'DEVELOPMENT_DATABASE' ? '개발 DB 설정' : selected.management_plane === 'DEPLOYMENT' ? '배포 설정' : '승인 Provider profile'}</dd></div>
            <div><dt>Embedding</dt><dd>{embedLabel(selected.embedding_state)}</dd></div>
            <div><dt>버전</dt><dd>v{selected.version}</dd></div>
            <div><dt>적용 수명주기</dt><dd><span className="badge">{activationLabel(selected.activation_state)}</span></dd></div>
            <div><dt>TEST 버전</dt><dd>{selected.tested_version ? `v${selected.tested_version} · ${selected.test_status}` : '—'}</dd></div>
            <div><dt>활성 버전</dt><dd>{selected.activated_version ? `v${selected.activated_version}` : '—'}</dd></div>
            <div><dt>현재 적용 버전</dt><dd>{selected.applied_version ? `v${selected.applied_version}` : '—'}</dd></div>
          </dl>
          {selected.is_core ? <p className="callout">이 코어 시스템 환경은 배포 환경 변수(.env)를 통해 관리됩니다. 아래 양식에서 직접 편집할 수 없습니다.</p> : canUpdate ? <>
            {!selected.configuration_yaml && <p className="callout">아직 저장된 설정이 없습니다. 실제 주소와 비민감 옵션을 입력한 뒤 저장하세요.</p>}
            {/* 버튼 순서: Form Mode (기본) | YAML Mode */}
            <div className="flex gap-2 mb-3">
              <button type="button" className={`button ${viewMode === 'FORM' ? '' : 'button-secondary'}`} onClick={() => setViewMode('FORM')}>폼 편집</button>
              <button type="button" className={`button ${viewMode === 'YAML' ? '' : 'button-secondary'}`} onClick={() => setViewMode('YAML')}>YAML 편집</button>
            </div>
            {viewMode === 'FORM' ? (
              renderFormMode()
            ) : (
              <label className="form-field admin-system-yaml-field">
                <span>YAML 연결 설정</span>
                <textarea
                  aria-label={`${selected.label} YAML 설정`}
                  className="admin-system-yaml"
                  onChange={(event) => { setDraft(event.target.value); setTestResult(undefined) }}
                  spellCheck="false"
                  value={enrichYamlWithComments(draft, selected.system_id)}
                />
                <small>비밀번호·토큰·API 키 값은 이 화면에서 제출할 수 없습니다. <code>file:/run/secrets/&lt;name&gt;</code> 형식의 Docker secret 참조명만 입력하세요.</small>
              </label>
            )}
          </> : <p className="callout">이 환경에서는 설정을 직접 편집할 수 없습니다. 배포 설정과 승인 Provider profile을 사용하세요.</p>}
          {selected.display_yaml && <section className="rounded-enterprise border border-slate-300 bg-slate-50 p-3" aria-label={`${selected.label} 저장된 비밀 제외 설정`}><span className="eyebrow">저장된 설정 요약 (비밀값 제외)</span><pre className="m-0 overflow-auto whitespace-pre-wrap text-[11px] leading-5 text-slate-700">{selected.display_yaml}</pre><small className="mt-2 block text-[9px] text-slate-500">실제 실행 시크릿은 포함하지 않습니다.</small></section>}
          {testResult && <p className={`callout m-0 ${testResult.status === 'AVAILABLE' ? 'border-l-green-600' : 'border-l-amber-600'}`} role="status"><strong>{testResult.status}</strong> · {testResult.scope} · {testResult.latency_ms}ms<br />{testResult.detail}</p>}
          {<div className="action-row"><button className="button button-secondary" disabled={selected.version === 0 || dirty || testing} title={selected.version === 0 ? '먼저 설정을 저장하세요.' : dirty ? '변경사항을 저장한 뒤 TEST하세요.' : '저장된 설정의 연결 상태를 확인합니다.'} onClick={() => void testSavedConfiguration()} type="button">{testing ? '연결 확인 중…' : '연결 테스트'}</button>{canUpdate && !selected.is_core && <><button className="button button-secondary" disabled={!canActivate || selected.activation_state !== 'TESTED'} title={!selected.runtime_supported ? '현재 아키텍처에 이 설정을 소비하는 런타임 어댑터가 없습니다.' : !canActivate ? '활성화에는 최근 보안키 인증이 필요합니다.' : 'TEST를 통과한 현재 버전만 활성화할 수 있습니다.'} onClick={activate} type="button">활성화</button><button className="button" disabled={!draft.trim() || saving || !dirty} onClick={save} type="button">{saving ? '저장 중…' : '저장'}</button></>}</div>}
          {selected.activation_state === 'DEPLOYMENT_MANAGED' && <p className="callout m-0">이 연결은 배포 환경 변수와 secret 파일을 기준으로 적용됩니다.</p>}
          {selected.activation_state === 'ACTIVATED_RESTART_REQUIRED' && <p className="callout m-0">활성 버전이 저장되었지만 실행 중인 프로세스에 아직 적용되지 않았습니다. {restartInstruction}</p>}
          {selected.activation_state === 'APPLIED_TO_API_PROCESS' && selected.restart_scope === 'API_AND_WORKERS' && <p className="callout m-0">현재 API에 이 버전이 적용되었습니다. 관련 Worker도 동일한 설정으로 재시작하세요.</p>}
        </>}
      </section>
    </div>
    <ErrorNotice error={error} />
  </section>
}
