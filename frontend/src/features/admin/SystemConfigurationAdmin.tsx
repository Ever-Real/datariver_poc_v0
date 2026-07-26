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

type SystemTabId = SystemConfigurationEntry['system_id'] | 'LLM_MODELS' | 'CORE_DASHBOARD'

function llmTabLabel(systemId: SystemConfigurationEntry['system_id']) {
  if (systemId === 'LLM_CHAT_MODEL') return 'Chat Model'
  if (systemId === 'LLM_EMBEDDING') return 'Embedding'
  return 'Reranker'
}

function stateLabel(state: SystemConfigurationEntry['state']) {
  if (state === 'CONFIGURED') return '구성됨'
  return '미구성'
}

function testStatusLabel(status: SystemConfigurationTestResult['status']) {
  if (status === 'AVAILABLE') return '연결 가능'
  if (status === 'AUTHENTICATION_REQUIRED') return '인증 확인 필요'
  return '연결 불가'
}

export function SystemConfigurationAdmin(props: AdminSectionProps) {
  const { api, reportError } = props
  const [items, setItems] = useState<SystemConfigurationEntry[]>([])
  const [selectedId, setSelectedId] = useState<
    SystemConfigurationEntry['system_id'] | 'CORE_DASHBOARD' | undefined
  >()
  const [loading, setLoading] = useState(true)
  const [testingId, setTestingId] = useState<SystemConfigurationEntry['system_id']>()
  const [testResults, setTestResults] = useState<
    Partial<Record<SystemConfigurationEntry['system_id'], SystemConfigurationTestResult>>
  >({})
  const [copiedId, setCopiedId] = useState<SystemConfigurationEntry['system_id']>()
  const [error, setError] = useState<unknown>()
  const loadRequest = useRef<{ generation: number; controller?: AbortController }>({
    generation: 0,
  })

  const load = useCallback(async () => {
    loadRequest.current.controller?.abort()
    const controller = new AbortController()
    const generation = loadRequest.current.generation + 1
    loadRequest.current = { generation, controller }
    setLoading(true)
    setError(undefined)
    try {
      const next = await api.listSystemConfiguration(controller.signal)
      if (controller.signal.aborted || loadRequest.current.generation !== generation) return
      setItems(next)
      setSelectedId((current) => {
        if (current === 'CORE_DASHBOARD' && next.some((item) => item.is_core)) return current
        if (current && next.some((item) => item.system_id === current)) return current
        return next.some((item) => item.is_core) ? 'CORE_DASHBOARD' : next[0]?.system_id
      })
    } catch (next) {
      if (!controller.signal.aborted) {
        setError(next)
        reportError(next)
      }
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
  const coreItems = useMemo(() => items.filter((item) => item.is_core), [items])
  const ordinaryItems = useMemo(
    () => items.filter((item) => !llmSystemIds.has(item.system_id) && !item.is_core),
    [items],
  )
  const llmSelected = Boolean(selected && llmSystemIds.has(selected.system_id))
  const systemTabIds = useMemo<SystemTabId[]>(
    () => [
      ...(coreItems.length > 0 ? (['CORE_DASHBOARD'] as const) : []),
      ...ordinaryItems.map((item) => item.system_id),
      ...(llmItems.length > 0 ? (['LLM_MODELS'] as const) : []),
    ],
    [coreItems.length, llmItems.length, ordinaryItems],
  )
  const activeSystemTab: SystemTabId | undefined =
    selectedId === 'CORE_DASHBOARD'
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

  const testConnection = async (item: SystemConfigurationEntry) => {
    if (testingId || item.state !== 'CONFIGURED' || !item.runtime_supported) return
    setTestingId(item.system_id)
    setError(undefined)
    try {
      const result = await api.testDeploymentSystemConfiguration(item.system_id)
      setTestResults((current) => ({ ...current, [item.system_id]: result }))
    } catch (next) {
      setError(next)
      reportError(next)
    } finally {
      setTestingId(undefined)
    }
  }

  const copyEnvironmentTemplate = async (item: SystemConfigurationEntry) => {
    if (!item.environment_template) return
    try {
      await navigator.clipboard.writeText(`${item.environment_template.trimEnd()}\n`)
      setCopiedId(item.system_id)
    } catch (next) {
      setError(next)
      reportError(next)
    }
  }

  const renderTestResult = (item: SystemConfigurationEntry) => {
    const result = testResults[item.system_id]
    if (!result) return null
    return (
      <p
        className={`callout m-0 ${
          result.status === 'AVAILABLE' ? 'border-l-green-600' : 'border-l-amber-600'
        }`}
        role="status"
      >
        <strong>{testStatusLabel(result.status)}</strong> · {result.scope} · {result.latency_ms}ms
        <br />
        {result.detail}
      </p>
    )
  }

  return (
    <section className="panel admin-system-settings">
      <div className="section-heading">
        <div>
          <h3>시스템 설정</h3>
          <p className="muted">
            실행 설정은 선택한 <code>.env</code>와 배포 secret에서만 읽습니다. 이 화면에서는
            현재 적용값을 확인하고 고정 연결 테스트만 수행할 수 있습니다.
          </p>
        </div>
        <button className="button button-secondary" onClick={() => void load()} type="button">
          새로고침
        </button>
      </div>
      <div className="admin-system-settings-workspace">
        <nav aria-label="설정 시스템 목록" className="admin-system-settings-list" role="tablist">
          {coreItems.length > 0 && (
            <h4 className="text-xs font-bold text-slate-500 uppercase mt-4 mb-2 ml-3 px-3">
              Core Systems
            </h4>
          )}
          {coreItems.length > 0 && (
            <button
              {...systemTabs.tabProps('CORE_DASHBOARD')}
              className={selectedId === 'CORE_DASHBOARD' || selected?.is_core ? 'active' : ''}
              onClick={() => selectSystemTab('CORE_DASHBOARD')}
              type="button"
            >
              <span
                className={`badge ${
                  coreItems.every((item) => item.state === 'CONFIGURED') ? '' : 'badge-soft'
                }`}
              >
                {coreItems.filter((item) => item.state === 'CONFIGURED').length}/{coreItems.length}
              </span>
              <strong>Core Dashboard</strong>
            </button>
          )}
          {ordinaryItems.length > 0 && (
            <h4 className="text-xs font-bold text-slate-500 uppercase mt-4 mb-2 ml-3 px-3">
              Extensions
            </h4>
          )}
          {ordinaryItems.map((item) => (
            <button
              {...systemTabs.tabProps(item.system_id)}
              className={selected?.system_id === item.system_id ? 'active' : ''}
              key={item.system_id}
              onClick={() => setSelectedId(item.system_id)}
              type="button"
            >
              <span className={`badge ${item.state === 'CONFIGURED' ? '' : 'badge-soft'}`}>
                {stateLabel(item.state)}
              </span>
              <strong>{item.label}</strong>
            </button>
          ))}
          {llmItems.length > 0 && (
            <h4 className="text-xs font-bold text-slate-500 uppercase mt-4 mb-2 ml-3 px-3">
              AI Models
            </h4>
          )}
          {llmItems.length > 0 && (
            <button
              {...systemTabs.tabProps('LLM_MODELS')}
              className={llmSelected ? 'active' : ''}
              onClick={() => selectSystemTab('LLM_MODELS')}
              type="button"
            >
              <span
                className={`badge ${
                  llmItems.every((item) => item.state === 'CONFIGURED') ? '' : 'badge-soft'
                }`}
              >
                {llmItems.filter((item) => item.state === 'CONFIGURED').length}/{llmItems.length}
              </span>
              <strong>LLM Models</strong>
            </button>
          )}
          {!loading && items.length === 0 && <p>표시 가능한 설정 항목이 없습니다.</p>}
        </nav>

        <section
          {...(activeSystemTab ? systemTabs.panelProps(activeSystemTab) : {})}
          aria-live="polite"
          className="admin-system-settings-detail"
        >
          {loading ? (
            <p className="muted">서버 구성 상태를 불러오는 중입니다.</p>
          ) : selectedId === 'CORE_DASHBOARD' || (!selected && coreItems.length > 0) ? (
            <div>
              <header className="mb-6">
                <span className="eyebrow">Read-only inventory</span>
                <h4>Core Systems</h4>
                <p className="muted" style={{ fontSize: 11 }}>
                  API 프로세스가 시작할 때 읽은 배포 환경의 상태입니다.
                </p>
              </header>
              <div className="grid gap-3">
                {coreItems.map((item) => (
                  <div
                    key={item.system_id}
                    className="p-4 border border-slate-200 rounded-lg bg-white shadow-sm"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <h5 className="font-bold text-slate-800 text-sm">{item.label}</h5>
                        <span
                          className={`badge ${
                            item.state === 'CONFIGURED' ? '' : 'badge-soft'
                          }`}
                        >
                          {stateLabel(item.state)}
                        </span>
                      </div>
                      <button
                        className="button button-secondary"
                        disabled={
                          Boolean(testingId)
                          || item.state !== 'CONFIGURED'
                          || !item.runtime_supported
                        }
                        onClick={() => void testConnection(item)}
                        type="button"
                      >
                        {testingId === item.system_id
                          ? '테스트 중…'
                          : item.runtime_supported
                            ? '연결 테스트'
                            : '설정 그룹'}
                      </button>
                    </div>
                    {renderTestResult(item)}
                  </div>
                ))}
              </div>
            </div>
          ) : !selected ? (
            <p className="muted">왼쪽에서 시스템을 선택하세요.</p>
          ) : (
            <>
              <header>
                <span className="eyebrow">{selected.system_id}</span>
                <h4>{selected.label}</h4>
                <p className="muted" style={{ fontSize: 11 }}>
                  {selected.description}
                </p>
              </header>

              {llmSelected && (
                <div className="admin-system-llm-tabs" role="group" aria-label="LLM 모델 상태">
                  {llmItems.map((item) => (
                    <button
                      key={item.system_id}
                      type="button"
                      aria-pressed={selected.system_id === item.system_id}
                      className={`button ${
                        selected.system_id === item.system_id ? '' : 'button-secondary'
                      }`}
                      onClick={() => setSelectedId(item.system_id)}
                    >
                      {llmTabLabel(item.system_id)}
                    </button>
                  ))}
                </div>
              )}

              <dl className="summary-list">
                <div>
                  <dt>구성 상태</dt>
                  <dd>
                    <span className="badge">{stateLabel(selected.state)}</span>
                  </dd>
                </div>
                <div>
                  <dt>설정 원천</dt>
                  <dd>배포 환경 · secret 파일</dd>
                </div>
                <div>
                  <dt>런타임 반영</dt>
                  <dd>업데이트·재시작 workflow</dd>
                </div>
              </dl>

              <p className="callout">
                이 화면은 호스트의 <code>.env</code> 파일을 읽거나 수정하지 않습니다. 선택한 환경
                파일을 변경한 뒤 <code>workflow_update_restart.py</code>를 실행해야 반영됩니다.
              </p>

              <section
                className="rounded-enterprise border border-slate-300 bg-slate-50 p-3"
                aria-label={`${selected.label} 환경 변수 템플릿`}
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="eyebrow">.env 옵션 템플릿</span>
                  <button
                    className="button button-secondary"
                    disabled={!selected.environment_template}
                    onClick={() => void copyEnvironmentTemplate(selected)}
                    type="button"
                  >
                    {copiedId === selected.system_id ? '복사됨' : '템플릿 복사'}
                  </button>
                </div>
                <pre className="m-0 overflow-auto whitespace-pre-wrap text-[11px] leading-5 text-slate-700">
                  {selected.environment_template || '이 시스템에 노출할 환경 변수 옵션이 없습니다.'}
                </pre>
              </section>

              {selected.effective_configuration_yaml && (
                <section
                  className="rounded-enterprise border border-slate-300 bg-slate-50 p-3"
                  aria-label={`${selected.label} 현재 적용 설정`}
                >
                  <span className="eyebrow">현재 API 적용값 (비밀값 제외)</span>
                  <pre className="m-0 overflow-auto whitespace-pre-wrap text-[11px] leading-5 text-slate-700">
                    {selected.effective_configuration_yaml}
                  </pre>
                </section>
              )}

              <div className="action-row">
                <button
                  className="button button-secondary"
                  disabled={
                    Boolean(testingId)
                    || selected.state !== 'CONFIGURED'
                    || !selected.runtime_supported
                  }
                  onClick={() => void testConnection(selected)}
                  type="button"
                >
                  {testingId === selected.system_id
                    ? '연결 확인 중…'
                    : selected.runtime_supported
                      ? '연결 테스트'
                      : '연결 테스트 없음'}
                </button>
              </div>
              {renderTestResult(selected)}
              <small className="muted">
                전체 옵션 설명: <code>docs/41_DEPLOYMENT_ENVIRONMENT_CONFIGURATION.md</code>
              </small>
            </>
          )}
        </section>
      </div>
      <ErrorNotice error={error} />
    </section>
  )
}
