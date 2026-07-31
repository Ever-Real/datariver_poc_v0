import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type {
  Capability,
  DeploymentEnvironment,
  SystemConfigurationEntry,
  SystemConfigurationTestResult,
} from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { useRovingTabs } from '../../components/common/useRovingTabs'
import { CapabilityObservation } from '../monitoring/CapabilityObservation'
import type { AdminSectionProps } from './MembershipAdmin'

const llmSystemIds = new Set<SystemConfigurationEntry['system_id']>([
  'LLM_CHAT_MODEL',
  'LLM_EMBEDDING',
  'LLM_RERANKER',
])

type SystemTabId = SystemConfigurationEntry['system_id'] | 'LLM_MODELS' | 'CORE_DASHBOARD'
type ConnectionState = 'DISCONNECTED' | 'CONNECTING' | 'ERROR' | 'CONNECTED'

function llmTabLabel(systemId: SystemConfigurationEntry['system_id']) {
  if (systemId === 'LLM_CHAT_MODEL') return 'Chat Model'
  if (systemId === 'LLM_EMBEDDING') return 'Embedding'
  return 'Reranker'
}

function stateLabel(state: SystemConfigurationEntry['state']) {
  if (state === 'CONFIGURED') return '구성됨'
  if (state === 'GOVERNED_PROFILE_REQUIRED') return '추론 승인 필요'
  return '미구성'
}

function testStatusLabel(
  status: SystemConfigurationTestResult['status'],
  connectionState: ConnectionState,
) {
  if (status === 'AVAILABLE') {
    return connectionState === 'CONNECTED' ? '정상 연결됨' : '연결 가능'
  }
  if (status === 'AUTHENTICATION_REQUIRED') return '인증 확인 필요'
  return '연결 불가'
}

function connectionStateLabel(state: ConnectionState) {
  if (state === 'CONNECTING') return '연결중'
  if (state === 'ERROR') return '오류'
  if (state === 'CONNECTED') return '연결됨'
  return '미연결'
}

function connectionStateClass(state: ConnectionState) {
  if (state === 'CONNECTING') return 'badge-connecting'
  if (state === 'ERROR') return 'badge-error'
  if (state === 'CONNECTED') return 'badge-connected'
  return 'badge-soft'
}

function aggregateConnectionState(
  entries: SystemConfigurationEntry[],
  states: Partial<Record<SystemConfigurationEntry['system_id'], ConnectionState>>,
): ConnectionState {
  const probeable = entries.filter(
    (item) => item.runtime_supported && item.state !== 'NOT_CONFIGURED',
  )
  if (probeable.length === 0) return 'DISCONNECTED'
  const values = probeable.map((item) => states[item.system_id] ?? 'DISCONNECTED')
  if (values.includes('ERROR')) return 'ERROR'
  if (values.includes('CONNECTING')) return 'CONNECTING'
  return values.every((value) => value === 'CONNECTED') ? 'CONNECTED' : 'DISCONNECTED'
}

function applyMethodLabel(method: DeploymentEnvironment['apply_method']) {
  if (method === 'WORKFLOW_UPDATE_RESTART') return '관리형 업데이트·재시작 workflow'
  if (method === 'SOURCE_HOST_UPDATE') return '준비 PC source-host 업데이트'
  if (method === 'SOURCE_HOST_RESTART') return 'source-host 사전검증·재시작'
  if (method === 'PILOT_REDEPLOY') return 'source-free Pilot 재배포'
  return '운영자 절차 미등록'
}

export function SystemConfigurationAdmin(props: AdminSectionProps) {
  const { api, reportError } = props
  const [items, setItems] = useState<SystemConfigurationEntry[]>([])
  const [capabilities, setCapabilities] = useState<Capability[]>([])
  const [deploymentEnvironment, setDeploymentEnvironment] = useState<DeploymentEnvironment>()
  const [selectedId, setSelectedId] = useState<
    SystemConfigurationEntry['system_id'] | 'CORE_DASHBOARD' | undefined
  >()
  const [loading, setLoading] = useState(true)
  const [capabilitiesLoading, setCapabilitiesLoading] = useState(true)
  const [testingId, setTestingId] = useState<SystemConfigurationEntry['system_id']>()
  const [testResults, setTestResults] = useState<
    Partial<Record<SystemConfigurationEntry['system_id'], SystemConfigurationTestResult>>
  >({})
  const [connectionStates, setConnectionStates] = useState<
    Partial<Record<SystemConfigurationEntry['system_id'], ConnectionState>>
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
      setItems(next.items)
      setDeploymentEnvironment(next.deployment_environment)
      setConnectionStates({})
      setTestResults({})
      setSelectedId((current) => {
        if (current === 'CORE_DASHBOARD' && next.items.some((item) => item.is_core)) return current
        if (current && next.items.some((item) => item.system_id === current)) return current
        return next.items.some((item) => item.is_core) ? 'CORE_DASHBOARD' : next.items[0]?.system_id
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

  const loadCapabilities = useCallback(async (signal?: AbortSignal) => {
    setCapabilitiesLoading(true)
    try {
      const next = await api.getCapabilities(signal)
      if (!signal?.aborted) setCapabilities(next.items)
    } catch (next) {
      if (!signal?.aborted) {
        setCapabilities([])
        setError(next)
        reportError(next)
      }
    } finally {
      if (!signal?.aborted) setCapabilitiesLoading(false)
    }
  }, [api, reportError])

  useEffect(() => {
    const controller = new AbortController()
    void loadCapabilities(controller.signal)
    return () => controller.abort()
  }, [loadCapabilities])

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
  const coreConnectionState = aggregateConnectionState(coreItems, connectionStates)
  const llmConnectionState = aggregateConnectionState(llmItems, connectionStates)
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
  const activeConnectionState: ConnectionState =
    selectedId === 'CORE_DASHBOARD'
      ? coreConnectionState
      : llmSelected
        ? llmConnectionState
        : selected
          ? connectionStates[selected.system_id] ?? 'DISCONNECTED'
          : 'DISCONNECTED'
  const selectSystemTab = (id: SystemTabId) => {
    setSelectedId(id === 'LLM_MODELS' ? llmItems[0]?.system_id : id)
  }
  const systemTabs = useRovingTabs({
    ids: systemTabIds,
    activeId: activeSystemTab,
    idPrefix: 'admin-system-config',
    onSelect: selectSystemTab,
  })

  const testConnection = async (
    item: SystemConfigurationEntry,
    applyOnSuccess = false,
  ): Promise<SystemConfigurationTestResult | undefined> => {
    if (testingId || item.state === 'NOT_CONFIGURED' || !item.runtime_supported) return undefined
    setTestingId(item.system_id)
    if (applyOnSuccess) {
      setConnectionStates((current) => ({ ...current, [item.system_id]: 'CONNECTING' }))
    }
    setError(undefined)
    try {
      const result = await api.testDeploymentSystemConfiguration(item.system_id)
      setTestResults((current) => ({ ...current, [item.system_id]: result }))
      if (applyOnSuccess) {
        setConnectionStates((current) => ({
          ...current,
          [item.system_id]: result.status === 'AVAILABLE' ? 'CONNECTED' : 'ERROR',
        }))
      }
      return result
    } catch (next) {
      if (applyOnSuccess) {
        setConnectionStates((current) => ({ ...current, [item.system_id]: 'ERROR' }))
      }
      setError(next)
      reportError(next)
      return undefined
    } finally {
      setTestingId(undefined)
    }
  }

  const testAndApplyConnection = async (item: SystemConfigurationEntry) => {
    await testConnection(item, true)
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
    const connectionState = connectionStates[item.system_id] ?? 'DISCONNECTED'
    return (
      <p
        aria-label={`${item.label} 연결 테스트 결과`}
        className={`callout m-0 ${
          result.status === 'AVAILABLE' ? 'border-l-green-600' : 'border-l-amber-600'
        }`}
        role="status"
      >
        <strong>{testStatusLabel(result.status, connectionState)}</strong> · {result.scope} ·{' '}
        {result.latency_ms}ms
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
        <div className="admin-system-connection-summary">
          <span
            aria-label={`현재 연결 상태: ${connectionStateLabel(activeConnectionState)}`}
            className={`badge connection-status-badge ${connectionStateClass(activeConnectionState)}`}
            role="status"
          >
            {connectionStateLabel(activeConnectionState)}
          </span>
          <button
            className="button button-secondary"
            onClick={() => {
              void load()
              void loadCapabilities()
            }}
            type="button"
          >
            새로고침
          </button>
        </div>
      </div>
      {deploymentEnvironment && (
        <section
          aria-label="현재 배포 환경"
          className="mb-4 grid gap-3 rounded-enterprise border border-slate-300 bg-slate-50 p-4"
        >
          <dl className="summary-list">
            <div>
              <dt>현재 적용 환경 파일</dt>
              <dd>
                <code>{deploymentEnvironment.environment_file}</code>
              </dd>
            </div>
            <div>
              <dt>운영 프로필</dt>
              <dd>
                <code>{deploymentEnvironment.operator_profile}</code>
              </dd>
            </div>
            <div>
              <dt>재적용 방식</dt>
              <dd>{applyMethodLabel(deploymentEnvironment.apply_method)}</dd>
            </div>
          </dl>
          {deploymentEnvironment.apply_command && (
            <pre className="m-0 overflow-auto whitespace-pre-wrap text-[11px] leading-5 text-slate-700">
              {deploymentEnvironment.apply_command}
            </pre>
          )}
        </section>
      )}
      <CapabilityObservation items={capabilities} loading={capabilitiesLoading} />
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
                className={`badge ${connectionStateClass(coreConnectionState)}`}
              >
                {connectionStateLabel(coreConnectionState)}
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
              <span
                className={`badge ${connectionStateClass(
                  connectionStates[item.system_id] ?? 'DISCONNECTED',
                )}`}
              >
                {connectionStateLabel(connectionStates[item.system_id] ?? 'DISCONNECTED')}
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
                className={`badge ${connectionStateClass(llmConnectionState)}`}
              >
                {connectionStateLabel(llmConnectionState)}
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
                          || item.state === 'NOT_CONFIGURED'
                          || !item.runtime_supported
                          || connectionStates[item.system_id] === 'CONNECTED'
                        }
                        aria-label={`${item.label} 테스트 후 반영`}
                        onClick={() => void testAndApplyConnection(item)}
                        type="button"
                      >
                        {testingId === item.system_id
                          ? '테스트 중…'
                          : connectionStates[item.system_id] === 'CONNECTED'
                            ? '연결됨'
                            : item.runtime_supported
                              ? '테스트 후 반영'
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
                  <dd>
                    <code>{deploymentEnvironment?.environment_file ?? '.env'}</code> · secret 파일
                  </dd>
                </div>
                <div>
                  <dt>런타임 반영</dt>
                  <dd>업데이트·재시작 workflow</dd>
                </div>
              </dl>

              <p className="callout">
                연결 테스트는 현재 API에 이미 적용된 값을 확인합니다. <strong>테스트 후 반영</strong>
                은 고정 서버 검증이 성공한 연결을 이 화면의 현재 연결 상태로 즉시 반영합니다.
                환경값 자체를 바꿀 때만 운영 workflow로 프로세스를 재시작해야 합니다.
              </p>

              {selected.state === 'GOVERNED_PROFILE_REQUIRED' && (
                <p className="callout border-l-amber-600" role="note">
                  모델 연결과 별도로 Chat 사용에는 이 실행 모델과 일치하는 승인된 추론 프로필
                  UUID 및 활성 분류정책 연결이 필요합니다. 개발·준비 환경에서는 명시적 governed
                  Chat bootstrap을 실행하세요.
                </p>
              )}

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
                    || selected.state === 'NOT_CONFIGURED'
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
                <button
                  className="button"
                  disabled={
                    Boolean(testingId)
                    || selected.state === 'NOT_CONFIGURED'
                    || !selected.runtime_supported
                    || connectionStates[selected.system_id] === 'CONNECTED'
                  }
                  onClick={() => void testAndApplyConnection(selected)}
                  type="button"
                >
                  {testingId === selected.system_id
                    ? '현재값 테스트 중…'
                    : connectionStates[selected.system_id] === 'CONNECTED'
                      ? '연결됨'
                      : '테스트 후 반영'}
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
