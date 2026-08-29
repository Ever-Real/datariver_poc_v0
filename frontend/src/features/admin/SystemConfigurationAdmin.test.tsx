import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient } from '../../api/client'
import type { AdminReadContext, SystemConfigurationEntry } from '../../api/types'
import { AdminApi } from './adminApi'
import type { PendingAdminMutation } from './AdminMutationConfirmDialog'
import { getAdminMessages } from './messages'
import { SystemConfigurationAdmin } from './SystemConfigurationAdmin'

const deploymentEntry: SystemConfigurationEntry = {
  system_id: 'DATAHUB_GMS',
  label: 'DataHub GMS',
  category: 'CATALOG',
  requirement: 'CORE_CONNECTOR',
  description: 'Catalog metadata API.',
  connection_requirements: [],
  state: 'CONFIGURED',
  management_plane: 'DEPLOYMENT',
  secret_reference_configured: true,
  embedding_state: 'NOT_APPLICABLE',
  configuration_yaml: '',
  template_yaml: '',
  display_yaml: 'base_url: http://datahub-gms:8080\n',
  environment_template: 'DATAHUB_BASE_URL=\nDATAHUB_SECRET_REF=',
  effective_configuration_yaml: 'base_url: http://datahub-gms:8080\n',
  version: 0,
  configured_at: null,
  runtime_supported: true,
  restart_scope: 'API_AND_WORKERS',
  activation_state: 'DEPLOYMENT_MANAGED',
  tested_version: null,
  test_status: null,
  tested_at: null,
  activated_version: null,
  activated_at: null,
  applied_version: null,
}

const context: AdminReadContext = {
  subject_id: 'administrator',
  workspace_id: 'workspace-one',
  display_name: 'Administrator',
  authentication_assurance: 'PASSWORD',
  fallback_enabled: false,
  allowed_operations: ['SYSTEM_CONFIGURATION_READ'],
  action_vocabulary: [],
}

const deploymentEnvironment = {
  environment_file: '.env.wsl-intranet-development',
  operator_profile: 'wsl-source-host' as const,
  apply_method: 'SOURCE_HOST_UPDATE' as const,
  apply_command:
    './scripts/development_cycle.py prep-update --env-file .env.wsl-intranet-development',
  browser_execution_supported: false as const,
}

function inventory(items: SystemConfigurationEntry[]) {
  return { items, deployment_environment: deploymentEnvironment }
}

function probeResult(
  systemId: SystemConfigurationEntry['system_id'],
  status: 'AVAILABLE' | 'AUTHENTICATION_REQUIRED' | 'UNAVAILABLE' = 'AVAILABLE',
) {
  return {
    system_id: systemId,
    status,
    scope: 'HTTP_HEALTH' as const,
    latency_ms: 8,
    detail: `fixed deployment probe ${status.toLowerCase()}`,
    configuration_version: null,
    tested_at: '2026-07-20T09:01:00Z',
  }
}

function renderAdmin(
  request: ReturnType<typeof vi.fn>,
  requestConfirmation: (mutation: PendingAdminMutation) => void = vi.fn(),
) {
  const routedRequest = (path: string, options?: RequestInit) => {
    if (path === '/capabilities') {
      return Promise.resolve({
        items: [{
          name: 'postgresql',
          state: 'healthy',
          observed_at: '2026-07-31T00:00:00Z',
          latency_ms: 4,
        }],
        external_system_links: [],
        grafana_embed: { state: 'NOT_CONFIGURED' },
        monitoring_configuration: { items: [], version: 0 },
        deployment_tier: 'SINGLE_NODE_PILOT',
      })
    }
    return (request as unknown as (
      path: string,
      options?: RequestInit,
    ) => unknown)(path, options)
  }
  const api = new AdminApi(
    { request: routedRequest, requestWithMeta: vi.fn() } as unknown as Pick<
      ApiClient,
      'request' | 'requestWithMeta'
    >,
  )
  render(
    <SystemConfigurationAdmin
      api={api}
      context={context}
      messages={getAdminMessages('ko')}
      requestConfirmation={requestConfirmation}
      keyFor={vi.fn(() => 'unused')}
      clearKey={vi.fn()}
      reportError={vi.fn()}
      onStepUp={vi.fn(() => Promise.resolve())}
      onPasswordReauth={vi.fn(() => Promise.resolve())}
      onEnroll={vi.fn(() => Promise.resolve())}
    />,
  )
}

describe('SystemConfigurationAdmin', () => {
  it('shows only deployment values and an env template without browser-side editors', async () => {
    const request = vi.fn((path: string) => {
      if (path === '/admin/system-configuration') {
        return Promise.resolve(inventory([deploymentEntry]))
      }
      if (path.endsWith('/test-deployment')) return Promise.resolve(probeResult('DATAHUB_GMS'))
      throw new Error(`unexpected request: ${path}`)
    })

    renderAdmin(request)

    expect(await screen.findByRole('region', { name: '현재 배포 환경' })).toHaveTextContent(
      '.env.wsl-intranet-development',
    )
    expect(screen.getByText('준비 PC source-host 업데이트')).toBeInTheDocument()
    expect(
      screen.getByRole('region', { name: 'DataHub GMS 환경 변수 템플릿' }),
    ).toHaveTextContent('DATAHUB_BASE_URL=')
    expect(screen.getByRole('region', { name: 'DataHub GMS 현재 적용 설정' })).toHaveTextContent(
      'base_url: http://datahub-gms:8080',
    )
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '저장' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '활성화' })).not.toBeInTheDocument()
    expect(await screen.findByText('Platform capability state')).toBeInTheDocument()
    expect(screen.getByText('postgresql')).toBeInTheDocument()
    expect(screen.getByText('4 ms')).toBeInTheDocument()
    expect(request).toHaveBeenCalledWith(
      '/admin/system-configuration',
      expect.objectContaining({ cache: 'no-store' }),
    )
  })

  it('copies only the server-owned env option template', async () => {
    const writeText = vi.fn(() => Promise.resolve())
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
    const request = vi.fn((path: string) => {
      if (path === '/admin/system-configuration') {
        return Promise.resolve(inventory([deploymentEntry]))
      }
      if (path.endsWith('/test-deployment')) return Promise.resolve(probeResult('DATAHUB_GMS'))
      throw new Error(`unexpected request: ${path}`)
    })

    renderAdmin(request)
    fireEvent.click(await screen.findByRole('button', { name: '템플릿 복사' }))

    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(
        'DATAHUB_BASE_URL=\nDATAHUB_SECRET_REF=\n',
      ),
    )
    expect(screen.getByRole('button', { name: '복사됨' })).toBeInTheDocument()
  })

  it('automatically runs the deployment-owned probe for a configured connector', async () => {
    const request = vi.fn((path: string, options?: RequestInit) => {
      if (path === '/admin/system-configuration') {
        return Promise.resolve(inventory([deploymentEntry]))
      }
      if (
        path === '/admin/system-configuration/DATAHUB_GMS/test-deployment'
        && options?.method === 'POST'
      ) {
        return Promise.resolve({ ...probeResult('DATAHUB_GMS'), latency_ms: 12 })
      }
      throw new Error(`unexpected request: ${path}`)
    })

    renderAdmin(request)

    expect(
      await screen.findByRole('status', { name: 'DataHub GMS 연결 테스트 결과' }),
    ).toHaveTextContent('정상 연결됨 · HTTP_HEALTH · 12ms')
    expect(screen.getByRole('status', { name: '현재 연결 상태: 연결됨' })).toBeInTheDocument()
    expect(request).toHaveBeenCalledWith(
      '/admin/system-configuration/DATAHUB_GMS/test-deployment',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('reflects the fixed probe only as the current-page connection state', async () => {
    const writeText = vi.fn(() => Promise.resolve())
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
    const request = vi.fn((path: string) => {
      if (path === '/admin/system-configuration') return Promise.resolve(inventory([deploymentEntry]))
      if (path.endsWith('/test-deployment')) return Promise.resolve(probeResult('DATAHUB_GMS'))
      throw new Error(`unexpected request: ${path}`)
    })

    renderAdmin(request)

    expect(await screen.findByRole('status', { name: '현재 연결 상태: 연결됨' })).toHaveTextContent(
      '연결됨',
    )
    expect(screen.getByRole('status', { name: 'DataHub GMS 연결 테스트 결과' })).toHaveTextContent(
      '정상 연결됨',
    )
    expect(writeText).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: '연결 확인' })).toBeEnabled()
  })

  it('reruns the automatic probe after refreshing the inventory', async () => {
    const request = vi.fn((path: string) => {
      if (path === '/admin/system-configuration') return Promise.resolve(inventory([deploymentEntry]))
      if (path.endsWith('/test-deployment')) return Promise.resolve(probeResult('DATAHUB_GMS'))
      throw new Error(`unexpected request: ${path}`)
    })

    renderAdmin(request)
    expect(await screen.findByRole('status', { name: '현재 연결 상태: 연결됨' })).toBeVisible()

    fireEvent.click(screen.getByRole('button', { name: '새로고침' }))
    await waitFor(() => {
      expect(request.mock.calls.filter(([path]) => path.endsWith('/test-deployment'))).toHaveLength(2)
    })
    expect(screen.getByRole('status', { name: '현재 연결 상태: 연결됨' })).toBeVisible()
  })

  it('shows an error state when the fixed connection probe fails', async () => {
    const writeText = vi.fn(() => Promise.resolve())
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
    const request = vi.fn((path: string) => {
      if (path === '/admin/system-configuration') return Promise.resolve(inventory([deploymentEntry]))
      if (path.endsWith('/test-deployment')) {
        return Promise.resolve(probeResult('DATAHUB_GMS', 'UNAVAILABLE'))
      }
      throw new Error(`unexpected request: ${path}`)
    })

    renderAdmin(request)

    expect(
      await screen.findByRole('status', { name: 'DataHub GMS 연결 테스트 결과' }),
    ).toHaveTextContent('연결 불가')
    expect(writeText).not.toHaveBeenCalled()
    expect(screen.getByRole('status', { name: '현재 연결 상태: 오류' })).toHaveTextContent('오류')
    expect(screen.getByRole('button', { name: '연결 확인' })).toBeInTheDocument()
  })

  it('shows a checking state while the automatic fixed connection probe is pending', async () => {
    const pendingProbe = deferred<ReturnType<typeof probeResult>>()
    const request = vi.fn((path: string) => {
      if (path === '/admin/system-configuration') return Promise.resolve(inventory([deploymentEntry]))
      if (path.endsWith('/test-deployment')) return pendingProbe.promise
      throw new Error(`unexpected request: ${path}`)
    })

    renderAdmin(request)

    expect(await screen.findByRole('status', { name: '현재 연결 상태: 확인 중' })).toBeVisible()
    expect(screen.getByRole('button', { name: '연결 확인' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '연결 확인' }))
    expect(request.mock.calls.filter(([path]) => path.endsWith('/test-deployment'))).toHaveLength(1)

    pendingProbe.resolve(probeResult('DATAHUB_GMS'))
    expect(await screen.findByRole('status', { name: '현재 연결 상태: 연결됨' })).toBeVisible()
  })

  it('shows a green connected badge on the Core Systems navigation after probing', async () => {
    const coreEntry = { ...deploymentEntry, is_core: true }
    const request = vi.fn((path: string) => {
      if (path === '/admin/system-configuration') return Promise.resolve(inventory([coreEntry]))
      if (path.endsWith('/test-deployment')) return Promise.resolve(probeResult('DATAHUB_GMS'))
      throw new Error(`unexpected request: ${path}`)
    })

    renderAdmin(request)

    expect((await screen.findByText('Core Dashboard')).closest('button')).toHaveTextContent('연결됨')
  })

  it('shows only the server-reviewed Airflow DAG inventory and refreshes it', async () => {
    const airflowEntry = {
      ...deploymentEntry,
      system_id: 'AIRFLOW' as const,
      label: 'Airflow',
      effective_configuration_yaml: 'base_url: https://canonical-airflow.example.internal\n',
      version: 4,
      activation_state: 'DEPLOYMENT_MANAGED' as const,
    }
    let inventoryCall = 0
    let triggerCall = 0
    let pending: PendingAdminMutation | undefined
    const request = vi.fn((path: string) => {
      if (path === '/admin/system-configuration') return Promise.resolve(inventory([airflowEntry]))
      if (path.endsWith('/test-deployment')) return Promise.resolve(probeResult('AIRFLOW'))
      if (path === '/poc-api/airflow/dags/datariver_catalog_sync/runs') {
        triggerCall += 1
        return Promise.resolve({
          replayed: false,
          receipt: {
            operation_id: 'a'.repeat(64), operation: 'TRIGGER', system_id: 'AIRFLOW',
            dag_id: 'datariver_catalog_sync', run_id: 'datariver__run', state: 'ACCEPTED',
            target_paused: null, provider_state: 'QUEUED', failure_code: null,
            created_at: '2026-08-29T12:00:00Z', updated_at: '2026-08-29T12:00:00Z',
            audit_events: [],
          },
        })
      }
      if (path === '/poc-api/airflow/dags') {
        inventoryCall += 1
        return Promise.resolve({
          system_id: 'AIRFLOW',
          api_mode: 'V2',
          observed_at: '2026-08-29T12:00:00Z',
          items: [
            {
              system_id: 'AIRFLOW',
              dag_id: 'datariver_catalog_sync',
              state: 'READY',
              paused: false,
              next_logical_date: '2026-08-30T02:00:00Z',
              next_run_at: '2026-08-30T02:00:00Z',
              last_parsed_at: '2026-08-29T11:59:00Z',
              latest_run: {
                system_id: 'AIRFLOW', dag_id: 'datariver_catalog_sync', run_id: 'scheduled__1',
                state: 'SUCCESS', logical_date: '2026-08-29T00:00:00Z',
                started_at: null, ended_at: null,
              },
            },
            {
              system_id: 'AIRFLOW',
              dag_id: 'datariver_quality_dispatch',
              state: 'MISSING',
              paused: null,
              next_logical_date: null,
              next_run_at: null,
              last_parsed_at: null,
              latest_run: null,
            },
          ],
        })
      }
      throw new Error(`unexpected request: ${path}`)
    })

    renderAdmin(request, (next) => { pending = next })

    await screen.findByText('datariver_catalog_sync')
    const table = screen.getByRole('table', { name: '검토된 Airflow DAG 목록' })
    expect(table).toHaveTextContent('datariver_catalog_sync')
    expect(table).toHaveTextContent('사용 가능')
    expect(table).toHaveTextContent('datariver_quality_dispatch')
    expect(table).toHaveTextContent('찾을 수 없음')
    expect(screen.getByRole('status', { name: 'Airflow DAG 조회 정보' })).toHaveTextContent('API V2')
    expect(screen.getByRole('note')).toHaveTextContent('멱등성·감사·실패 조정 receipt')
    expect(screen.getByLabelText('Canonical Airflow 시스템 구성')).toHaveTextContent('구성 IDAIRFLOW')
    expect(screen.getByText('/admin/system-configuration')).toBeVisible()
    expect(screen.getByText('DEPLOYMENT_MANAGED')).toBeVisible()

    fireEvent.click(screen.getByRole('button', { name: 'DAG 실행' }))
    expect(triggerCall).toBe(0)
    expect(pending?.summary).toEqual(expect.arrayContaining([
      'System configuration ID: AIRFLOW',
      '검토된 DAG: datariver_catalog_sync',
      '작업: TRIGGER',
    ]))
    if (!pending) throw new Error('Airflow confirmation was not requested')
    const confirmed = pending
    await act(async () => { await Promise.all([confirmed.execute(), confirmed.execute()]) })
    await waitFor(() => expect(triggerCall).toBe(1))
    expect(await screen.findByText(/실행이 접수되었습니다/)).toBeVisible()

    fireEvent.click(screen.getByRole('button', { name: 'DAG 상태 새로고침' }))
    await waitFor(() => expect(inventoryCall).toBeGreaterThanOrEqual(3))
    expect(request).toHaveBeenCalledWith(
      '/poc-api/airflow/dags',
      expect.objectContaining({ cache: 'no-store' }),
    )
  })

  it('shows a bounded Airflow DAG inventory error without provider fallback', async () => {
    const airflowEntry = {
      ...deploymentEntry,
      system_id: 'AIRFLOW' as const,
      label: 'Airflow',
    }
    const request = vi.fn((path: string) => {
      if (path === '/admin/system-configuration') return Promise.resolve(inventory([airflowEntry]))
      if (path.endsWith('/test-deployment')) return Promise.resolve(probeResult('AIRFLOW'))
      if (path === '/poc-api/airflow/dags') throw new Error('Airflow DAG 상태를 불러오지 못했습니다.')
      throw new Error(`unexpected request: ${path}`)
    })

    renderAdmin(request)

    expect(await screen.findByRole('alert')).toHaveTextContent('Airflow DAG 상태를 불러오지 못했습니다.')
    expect(screen.getByRole('table', { name: '검토된 Airflow DAG 목록' })).toHaveTextContent(
      '현재 조회 가능한 검토된 DAG가 없습니다.',
    )
  })

  it('groups Chat, Embedding, and Reranker under one read-only LLM menu', async () => {
    const llmSpecs: Array<[SystemConfigurationEntry['system_id'], string]> = [
      ['LLM_CHAT_MODEL', 'LLM · Chat model'],
      ['LLM_EMBEDDING', 'LLM · Embedding'],
      ['LLM_RERANKER', 'LLM · Reranker'],
    ]
    const llmEntries = llmSpecs.map(([systemId, label]) => ({
      ...deploymentEntry,
      system_id: systemId,
      label,
    }))
    const request = vi.fn((path: string) => {
      if (path === '/admin/system-configuration') return Promise.resolve(inventory(llmEntries))
      const systemId = path.split('/').at(-2) as SystemConfigurationEntry['system_id']
      if (path.endsWith('/test-deployment')) return Promise.resolve(probeResult(systemId))
      throw new Error(`unexpected request: ${path}`)
    })

    renderAdmin(request)

    expect(await screen.findByRole('tab', { name: /LLM Models/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Chat Model/ })).toHaveAttribute('aria-pressed', 'true')
    expect(await screen.findByRole('status', { name: 'Chat Model 연결 상태: 연결됨' })).toBeVisible()
    expect(screen.getByRole('status', { name: 'Embedding 연결 상태: 연결됨' })).toBeVisible()
    expect(screen.getByRole('status', { name: 'Reranker 연결 상태: 연결됨' })).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: /Reranker/ }))
    expect(screen.getByRole('button', { name: /Reranker/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('heading', { name: 'LLM · Reranker' })).toBeInTheDocument()
  })

  it('tracks Chat, Embedding, and Reranker probe states independently', async () => {
    const llmSpecs: Array<[SystemConfigurationEntry['system_id'], string]> = [
      ['LLM_CHAT_MODEL', 'LLM · Chat model'],
      ['LLM_EMBEDDING', 'LLM · Embedding'],
      ['LLM_RERANKER', 'LLM · Reranker'],
    ]
    const llmEntries = llmSpecs.map(([systemId, label]) => ({ ...deploymentEntry, system_id: systemId, label }))
    const request = vi.fn((path: string) => {
      if (path === '/admin/system-configuration') return Promise.resolve(inventory(llmEntries))
      if (path.includes('LLM_CHAT_MODEL')) return Promise.resolve(probeResult('LLM_CHAT_MODEL'))
      if (path.includes('LLM_EMBEDDING')) return Promise.resolve(probeResult('LLM_EMBEDDING', 'AUTHENTICATION_REQUIRED'))
      if (path.includes('LLM_RERANKER')) return Promise.resolve(probeResult('LLM_RERANKER', 'UNAVAILABLE'))
      throw new Error(`unexpected request: ${path}`)
    })

    renderAdmin(request)

    expect(await screen.findByRole('status', { name: 'Chat Model 연결 상태: 연결됨' })).toBeVisible()
    expect(screen.getByRole('status', { name: 'Embedding 연결 상태: 인증 확인 필요' })).toBeVisible()
    expect(screen.getByRole('status', { name: 'Reranker 연결 상태: 오류' })).toBeVisible()
  })

  it('defers an unconfigured governed Chat binding and disables its probe', async () => {
    const request = vi.fn((path: string) => {
      if (path === '/admin/system-configuration') {
        return Promise.resolve(inventory([{ ...deploymentEntry, system_id: 'LLM_CHAT_MODEL', label: 'LLM · Chat model', state: 'GOVERNED_PROFILE_REQUIRED' }]))
      }
      throw new Error(`unexpected request: ${path}`)
    })

    renderAdmin(request)

    expect(await screen.findAllByText('추론 승인 필요')).toHaveLength(2)
    expect(screen.getByText(/승인된 추론 프로필 UUID 및 활성 분류정책 연결이 필요합니다/)).toBeInTheDocument()
    expect(screen.getByRole('status', { name: 'Chat Model 연결 상태: 확인 보류' })).toBeVisible()
    expect(screen.getByRole('button', { name: '연결 확인' })).toBeDisabled()
    expect(request.mock.calls.some(([path]) => path.endsWith('/test-deployment'))).toBe(false)
  })

  it('limits automatic probes to three and skips unconfigured or unsupported entries', async () => {
    const ids: SystemConfigurationEntry['system_id'][] = ['DATAHUB_GMS', 'POSTGRESQL', 'REDIS_CACHE', 'S3_STORAGE']
    const probes = new Map(ids.map((id) => [id, deferred<ReturnType<typeof probeResult>>()]))
    let active = 0
    let maximumActive = 0
    const entries = [
      ...ids.map((systemId) => ({ ...deploymentEntry, system_id: systemId, label: systemId })),
      { ...deploymentEntry, system_id: 'AIRFLOW' as const, label: 'AIRFLOW', state: 'NOT_CONFIGURED' as const },
      { ...deploymentEntry, system_id: 'NEO4J' as const, label: 'NEO4J', runtime_supported: false },
    ]
    const request = vi.fn((path: string) => {
      if (path === '/admin/system-configuration') return Promise.resolve(inventory(entries))
      if (path.endsWith('/test-deployment')) {
        const systemId = path.split('/').at(-2) as SystemConfigurationEntry['system_id']
        active += 1
        maximumActive = Math.max(maximumActive, active)
        return probes.get(systemId)?.promise.finally(() => { active -= 1 })
      }
      throw new Error(`unexpected request: ${path}`)
    })

    renderAdmin(request)
    await waitFor(() => expect(request.mock.calls.filter(([path]) => path.endsWith('/test-deployment'))).toHaveLength(3))
    expect(maximumActive).toBe(3)
    probes.get('DATAHUB_GMS')?.resolve(probeResult('DATAHUB_GMS'))
    await waitFor(() => expect(request.mock.calls.filter(([path]) => path.endsWith('/test-deployment'))).toHaveLength(4))
    probes.get('POSTGRESQL')?.resolve(probeResult('POSTGRESQL', 'AUTHENTICATION_REQUIRED'))
    probes.get('REDIS_CACHE')?.reject(new Error('provider request failed'))
    probes.get('S3_STORAGE')?.resolve(probeResult('S3_STORAGE', 'UNAVAILABLE'))

    expect(await screen.findByRole('status', { name: '현재 연결 상태: 연결됨' })).toBeVisible()
    expect(await screen.findByRole('tab', { name: /인증 확인 필요POSTGRESQL/ })).toBeVisible()
    expect(screen.getByRole('tab', { name: /오류REDIS_CACHE/ })).toBeVisible()
    expect(screen.getByRole('tab', { name: /오류S3_STORAGE/ })).toBeVisible()
    expect(screen.getByRole('tab', { name: /확인 보류AIRFLOW/ })).toBeVisible()
    expect(screen.getByRole('tab', { name: /확인 보류NEO4J/ })).toBeVisible()
    expect(request.mock.calls.some(([path]) => path.includes('/AIRFLOW/test-deployment'))).toBe(false)
    expect(request.mock.calls.some(([path]) => path.includes('/NEO4J/test-deployment'))).toBe(false)
  })

  it('does not let an aborted older probe overwrite a refreshed generation', async () => {
    const oldProbe = deferred<ReturnType<typeof probeResult>>()
    const newProbe = deferred<ReturnType<typeof probeResult>>()
    let probeCall = 0
    const request = vi.fn((path: string) => {
      if (path === '/admin/system-configuration') return Promise.resolve(inventory([deploymentEntry]))
      if (path.endsWith('/test-deployment')) {
        probeCall += 1
        return probeCall === 1 ? oldProbe.promise : newProbe.promise
      }
      throw new Error(`unexpected request: ${path}`)
    })

    renderAdmin(request)
    expect(await screen.findByRole('status', { name: '현재 연결 상태: 확인 중' })).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: '새로고침' }))
    await waitFor(() => expect(probeCall).toBe(2))
    newProbe.resolve(probeResult('DATAHUB_GMS'))
    expect(await screen.findByRole('status', { name: '현재 연결 상태: 연결됨' })).toBeVisible()
    oldProbe.resolve(probeResult('DATAHUB_GMS', 'UNAVAILABLE'))
    await waitFor(() => expect(screen.getByRole('status', { name: '현재 연결 상태: 연결됨' })).toBeVisible())
  })
})

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((next, fail) => {
    resolve = next
    reject = fail
  })
  return { promise, reject, resolve }
}
