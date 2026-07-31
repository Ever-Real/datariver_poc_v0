import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient } from '../../api/client'
import type { AdminReadContext, SystemConfigurationEntry } from '../../api/types'
import { AdminApi } from './adminApi'
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

function renderAdmin(request: ReturnType<typeof vi.fn>) {
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
      requestConfirmation={vi.fn()}
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

  it('tests a configured connector only through the deployment-owned route', async () => {
    const request = vi.fn((path: string, options?: RequestInit) => {
      if (path === '/admin/system-configuration') {
        return Promise.resolve(inventory([deploymentEntry]))
      }
      if (
        path === '/admin/system-configuration/DATAHUB_GMS/test-deployment'
        && options?.method === 'POST'
      ) {
        return Promise.resolve({
          system_id: 'DATAHUB_GMS',
          status: 'AVAILABLE',
          scope: 'HTTP_HEALTH',
          latency_ms: 12,
          detail: 'fixed deployment probe passed',
          configuration_version: null,
          tested_at: '2026-07-20T09:01:00Z',
        })
      }
      throw new Error(`unexpected request: ${path}`)
    })

    renderAdmin(request)
    fireEvent.click(await screen.findByRole('button', { name: '연결 테스트' }))

    expect(
      await screen.findByRole('status', { name: 'DataHub GMS 연결 테스트 결과' }),
    ).toHaveTextContent(
      '연결 가능 · HTTP_HEALTH · 12ms',
    )
    expect(request).toHaveBeenCalledWith(
      '/admin/system-configuration/DATAHUB_GMS/test-deployment',
      { method: 'POST' },
    )
  })

  it('tests and applies the live connection state without copying a host command', async () => {
    const writeText = vi.fn(() => Promise.resolve())
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
    const request = vi.fn((path: string, options?: RequestInit) => {
      if (path === '/admin/system-configuration') {
        return Promise.resolve(inventory([deploymentEntry]))
      }
      if (
        path === '/admin/system-configuration/DATAHUB_GMS/test-deployment'
        && options?.method === 'POST'
      ) {
        return Promise.resolve({
          system_id: 'DATAHUB_GMS',
          status: 'AVAILABLE',
          scope: 'HTTP_HEALTH',
          latency_ms: 8,
          detail: 'fixed deployment probe passed',
          configuration_version: null,
          tested_at: '2026-07-20T09:01:00Z',
        })
      }
      throw new Error(`unexpected request: ${path}`)
    })

    renderAdmin(request)
    fireEvent.click(await screen.findByRole('button', { name: '테스트 후 반영' }))

    expect(await screen.findByRole('status', { name: '현재 연결 상태: 연결됨' })).toHaveTextContent(
      '연결됨',
    )
    expect(
      screen.getByRole('status', { name: 'DataHub GMS 연결 테스트 결과' }),
    ).toHaveTextContent('정상 연결됨')
    expect(writeText).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: '연결됨' })).toBeDisabled()
  })

  it('shows an error state when the test-and-apply probe fails', async () => {
    const writeText = vi.fn(() => Promise.resolve())
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
    const request = vi.fn((path: string, options?: RequestInit) => {
      if (path === '/admin/system-configuration') {
        return Promise.resolve(inventory([deploymentEntry]))
      }
      if (
        path === '/admin/system-configuration/DATAHUB_GMS/test-deployment'
        && options?.method === 'POST'
      ) {
        return Promise.resolve({
          system_id: 'DATAHUB_GMS',
          status: 'UNAVAILABLE',
          scope: 'HTTP_HEALTH',
          latency_ms: 8,
          detail: 'fixed deployment probe failed',
          configuration_version: null,
          tested_at: '2026-07-20T09:01:00Z',
        })
      }
      throw new Error(`unexpected request: ${path}`)
    })

    renderAdmin(request)
    fireEvent.click(await screen.findByRole('button', { name: '테스트 후 반영' }))

    expect(
      await screen.findByRole('status', { name: 'DataHub GMS 연결 테스트 결과' }),
    ).toHaveTextContent('연결 불가')
    expect(writeText).not.toHaveBeenCalled()
    expect(screen.getByRole('status', { name: '현재 연결 상태: 오류' })).toHaveTextContent(
      '오류',
    )
    expect(screen.getByRole('button', { name: '테스트 후 반영' })).toBeInTheDocument()
  })

  it('shows a connecting state while the test-and-apply probe is pending', async () => {
    let resolveProbe:
      | ((value: {
          system_id: string
          status: 'AVAILABLE'
          scope: 'HTTP_HEALTH'
          latency_ms: number
          detail: string
          configuration_version: null
          tested_at: string
        }) => void)
      | undefined
    const pendingProbe = new Promise<{
      system_id: string
      status: 'AVAILABLE'
      scope: 'HTTP_HEALTH'
      latency_ms: number
      detail: string
      configuration_version: null
      tested_at: string
    }>((resolve) => {
      resolveProbe = resolve
    })
    const request = vi.fn((path: string) => {
      if (path === '/admin/system-configuration') {
        return Promise.resolve(inventory([deploymentEntry]))
      }
      if (path === '/admin/system-configuration/DATAHUB_GMS/test-deployment') {
        return pendingProbe
      }
      throw new Error(`unexpected request: ${path}`)
    })

    renderAdmin(request)
    fireEvent.click(await screen.findByRole('button', { name: '테스트 후 반영' }))

    expect(
      await screen.findByRole('status', { name: '현재 연결 상태: 연결중' }),
    ).toHaveTextContent('연결중')

    resolveProbe?.({
      system_id: 'DATAHUB_GMS',
      status: 'AVAILABLE',
      scope: 'HTTP_HEALTH',
      latency_ms: 8,
      detail: 'fixed deployment probe passed',
      configuration_version: null,
      tested_at: '2026-07-20T09:01:00Z',
    })
    expect(await screen.findByRole('status', { name: '현재 연결 상태: 연결됨' })).toBeVisible()
  })

  it('shows a green connected badge on the Core Systems navigation after applying', async () => {
    const coreEntry = { ...deploymentEntry, is_core: true }
    const request = vi.fn((path: string) => {
      if (path === '/admin/system-configuration') {
        return Promise.resolve(inventory([coreEntry]))
      }
      if (path === '/admin/system-configuration/DATAHUB_GMS/test-deployment') {
        return Promise.resolve({
          system_id: 'DATAHUB_GMS',
          status: 'AVAILABLE',
          scope: 'HTTP_HEALTH',
          latency_ms: 8,
          detail: 'fixed deployment probe passed',
          configuration_version: null,
          tested_at: '2026-07-20T09:01:00Z',
        })
      }
      throw new Error(`unexpected request: ${path}`)
    })

    renderAdmin(request)
    fireEvent.click(await screen.findByRole('button', { name: 'DataHub GMS 테스트 후 반영' }))

    expect((await screen.findByText('Core Dashboard')).closest('button')).toHaveTextContent('연결됨')
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
      if (path === '/admin/system-configuration') {
        return Promise.resolve(inventory(llmEntries))
      }
      throw new Error(`unexpected request: ${path}`)
    })

    renderAdmin(request)

    expect(await screen.findByRole('tab', { name: /LLM Models/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Chat Model' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    fireEvent.click(screen.getByRole('button', { name: 'Reranker' }))
    expect(screen.getByRole('button', { name: 'Reranker' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(screen.getByRole('heading', { name: 'LLM · Reranker' })).toBeInTheDocument()
  })

  it('separates an available model transport from missing governed Chat binding', async () => {
    const request = vi.fn((path: string) => {
      if (path === '/admin/system-configuration') {
        return Promise.resolve(
          inventory([
            {
              ...deploymentEntry,
              system_id: 'LLM_CHAT_MODEL',
              label: 'LLM · Chat model',
              state: 'GOVERNED_PROFILE_REQUIRED',
            },
          ]),
        )
      }
      throw new Error(`unexpected request: ${path}`)
    })

    renderAdmin(request)

    expect(await screen.findByText('추론 승인 필요')).toBeInTheDocument()
    expect(
      screen.getByText(/승인된 추론 프로필 UUID 및 활성 분류정책 연결이 필요합니다/),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '테스트 후 반영' })).toBeEnabled()
  })
})
