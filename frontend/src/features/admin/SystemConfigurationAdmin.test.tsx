import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient } from '../../api/client'
import type { AdminReadContext, SystemConfigurationEntry } from '../../api/types'
import { AdminApi } from './adminApi'
import type { PendingAdminMutation } from './AdminMutationConfirmDialog'
import { getAdminMessages } from './messages'
import { SystemConfigurationAdmin } from './SystemConfigurationAdmin'

const initialEntry: SystemConfigurationEntry = {
  system_id: 'DATAHUB_GMS',
  label: 'DataHub GMS',
  state: 'NOT_CONFIGURED',
  management_plane: 'DEVELOPMENT_DATABASE',
  secret_reference_configured: false,
  embedding_state: 'NOT_APPLICABLE',
  configuration_yaml: '',
  template_yaml: 'base_url: ""\noptions:\n  timeout_seconds: 30\n',
  display_yaml: '',
  version: 0,
  configured_at: null,
  runtime_supported: true,
  restart_scope: 'API_AND_WORKERS',
  activation_state: 'NOT_CONFIGURED',
  tested_version: null,
  test_status: null,
  tested_at: null,
  activated_version: null,
  activated_at: null,
  applied_version: null,
}

const savedEntry: SystemConfigurationEntry = {
  ...initialEntry,
  state: 'CONFIGURED',
  secret_reference_configured: true,
  configuration_yaml: 'base_url: http://datahub-gms:8080\nsecret_references:\n  token: file:/run/secrets/datahub_token\n',
  display_yaml: 'base_url: http://datahub-gms:8080\nsecret_references:\n  token: file:/run/secrets/datahub_token\noptions:\n  timeout_seconds: 30\n',
  version: 1,
  configured_at: '2026-07-20T09:00:00Z',
  activation_state: 'SAVED_UNTESTED',
}

describe('SystemConfigurationAdmin', () => {
  it('starts from the server template, supports version zero creation, and displays only the server-redacted summary', async () => {
    const request = vi.fn((path: string, options?: RequestInit & { ifMatch?: string }) => {
      if (path === '/admin/system-configuration') return Promise.resolve({ items: [initialEntry] })
      if (path === '/admin/system-configuration/DATAHUB_GMS' && options?.method === 'PUT') {
        return Promise.resolve(savedEntry)
      }
      if (path === '/admin/system-configuration/DATAHUB_GMS/test' && options?.method === 'POST') {
        return Promise.resolve({
          system_id: 'DATAHUB_GMS', status: 'AVAILABLE', scope: 'HTTP_HEALTH',
          latency_ms: 12, detail: 'The saved configuration passed its fixed server-side probe.',
          configuration_version: 1, tested_at: '2026-07-20T09:01:00Z',
        })
      }
      throw new Error(`unexpected request: ${path}`)
    })
    const api = new AdminApi(
      { request, requestWithMeta: vi.fn() } as unknown as Pick<ApiClient, 'request' | 'requestWithMeta'>,
    )
    const context: AdminReadContext = {
      subject_id: 'administrator',
      workspace_id: 'workspace-one',
      display_name: 'Administrator',
      authentication_assurance: 'HARDWARE_WEBAUTHN',
      fallback_enabled: false,
      allowed_operations: ['SYSTEM_CONFIGURATION_READ', 'SYSTEM_CONFIGURATION_UPDATE'],
      action_vocabulary: [],
    }
    let pending: PendingAdminMutation | undefined

    render(<SystemConfigurationAdmin
      api={api}
      context={context}
      messages={getAdminMessages('ko')}
      requestConfirmation={(next) => { pending = next }}
      keyFor={vi.fn(() => 'unused')}
      clearKey={vi.fn()}
      reportError={vi.fn()}
      onStepUp={vi.fn(() => Promise.resolve())}
      onPasswordReauth={vi.fn(() => Promise.resolve())}
      onEnroll={vi.fn(() => Promise.resolve())}
    />)

    const editor = await screen.findByRole('textbox', { name: 'DataHub GMS YAML 설정' })
    await waitFor(() => expect(editor).toHaveValue(initialEntry.template_yaml))
    fireEvent.change(editor, {
      target: { value: 'base_url: http://datahub-gms:8080\noptions:\n  timeout_seconds: 30\n' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'SAVE' }))
    expect(pending?.title).toBe('DataHub GMS 설정 저장')
    if (!pending) throw new Error('confirmation was not requested')
    const mutation = pending

    await act(async () => { await mutation.execute() })
    await waitFor(() => expect(request).toHaveBeenCalledWith(
      '/admin/system-configuration/DATAHUB_GMS',
      expect.objectContaining({ method: 'PUT', ifMatch: '"0"' }),
    ))

    const summary = await screen.findByRole('region', { name: 'DataHub GMS 저장된 비밀 제외 설정' })
    expect(within(summary).getByText(/base_url: http:\/\/datahub-gms:8080/)).toBeInTheDocument()
    expect(within(summary).getByText(/token: file:\/run\/secrets\/datahub_token/)).toBeInTheDocument()
    expect(within(summary).queryByText(/stored-token/)).not.toBeInTheDocument()
    const testConnection = screen.getByRole('button', { name: 'TEST' })
    await waitFor(() => expect(testConnection).toBeEnabled())
    fireEvent.click(testConnection)
    expect(await screen.findByRole('status')).toHaveTextContent('AVAILABLE · HTTP_HEALTH · 12ms')
  })

  it('activates only the exact TEST-passed version and explains the required restart', async () => {
    const testedEntry: SystemConfigurationEntry = {
      ...savedEntry,
      activation_state: 'TESTED',
      tested_version: 1,
      test_status: 'AVAILABLE',
      tested_at: '2026-07-20T09:01:00Z',
    }
    const activatedEntry: SystemConfigurationEntry = {
      ...testedEntry,
      activation_state: 'ACTIVATED_RESTART_REQUIRED',
      activated_version: 1,
      activated_at: '2026-07-20T09:02:00Z',
    }
    const request = vi.fn((path: string, options?: RequestInit & { ifMatch?: string }) => {
      if (path === '/admin/system-configuration') return Promise.resolve({ items: [testedEntry] })
      if (path === '/admin/system-configuration/DATAHUB_GMS/activate'
        && options?.method === 'POST') return Promise.resolve(activatedEntry)
      throw new Error(`unexpected request: ${path}`)
    })
    const api = new AdminApi(
      { request, requestWithMeta: vi.fn() } as unknown as Pick<ApiClient, 'request' | 'requestWithMeta'>,
    )
    const context: AdminReadContext = {
      subject_id: 'administrator', workspace_id: 'workspace-one', display_name: 'Administrator',
      authentication_assurance: 'HARDWARE_WEBAUTHN', fallback_enabled: false,
      allowed_operations: [
        'SYSTEM_CONFIGURATION_READ', 'SYSTEM_CONFIGURATION_UPDATE',
        'SYSTEM_CONFIGURATION_ACTIVATE',
      ],
      action_vocabulary: [],
    }
    let pending: PendingAdminMutation | undefined

    render(<SystemConfigurationAdmin
      api={api} context={context} messages={getAdminMessages('ko')}
      requestConfirmation={(next) => { pending = next }} keyFor={vi.fn(() => 'unused')}
      clearKey={vi.fn()} reportError={vi.fn()}
      onStepUp={vi.fn(() => Promise.resolve())}
      onPasswordReauth={vi.fn(() => Promise.resolve())}
      onEnroll={vi.fn(() => Promise.resolve())}
    />)

    const activate = await screen.findByRole('button', { name: 'ACTIVATE' })
    expect(activate).toBeEnabled()
    fireEvent.click(activate)
    expect(pending?.title).toBe('DataHub GMS 설정 활성화')
    if (!pending) throw new Error('activation confirmation was not requested')
    const mutation = pending
    await act(async () => { await mutation.execute() })

    await waitFor(() => expect(request).toHaveBeenCalledWith(
      '/admin/system-configuration/DATAHUB_GMS/activate',
      expect.objectContaining({ method: 'POST', ifMatch: '"1"' }),
    ))
    expect(await screen.findByText(/API와 이 연결을 사용하는 Worker를 재시작하세요/))
      .toBeInTheDocument()
  })

  it('groups Chat, Embedding, and Reranker under one LLM menu with model tabs', async () => {
    const llmSpecs: Array<[SystemConfigurationEntry['system_id'], string]> = [
      ['LLM_CHAT_MODEL', 'LLM · Chat model'],
      ['LLM_EMBEDDING', 'LLM · Embedding'],
      ['LLM_RERANKER', 'LLM · Reranker'],
    ]
    const llmEntries: SystemConfigurationEntry[] = llmSpecs.map(([systemId, label]) => ({
      ...initialEntry,
      system_id: systemId,
      label,
    }))
    const request = vi.fn((path: string) => {
      if (path === '/admin/system-configuration') return Promise.resolve({ items: llmEntries })
      throw new Error(`unexpected request: ${path}`)
    })
    const api = new AdminApi(
      { request, requestWithMeta: vi.fn() } as unknown as Pick<ApiClient, 'request' | 'requestWithMeta'>,
    )
    const context: AdminReadContext = {
      subject_id: 'administrator', workspace_id: 'workspace-one', display_name: 'Administrator',
      authentication_assurance: 'HARDWARE_WEBAUTHN', fallback_enabled: false,
      allowed_operations: ['SYSTEM_CONFIGURATION_READ'], action_vocabulary: [],
    }

    render(<SystemConfigurationAdmin
      api={api} context={context} messages={getAdminMessages('ko')}
      requestConfirmation={vi.fn()} keyFor={vi.fn(() => 'unused')} clearKey={vi.fn()}
      reportError={vi.fn()} onStepUp={vi.fn(() => Promise.resolve())}
      onPasswordReauth={vi.fn(() => Promise.resolve())} onEnroll={vi.fn(() => Promise.resolve())}
    />)

    expect(await screen.findByRole('tab', { name: /LLM Models/ })).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'LLM · Chat model' })).not.toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Chat Model' })).toHaveAttribute('aria-selected', 'true')
    fireEvent.click(screen.getByRole('tab', { name: 'Reranker' }))
    expect(screen.getByRole('tab', { name: 'Reranker' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('heading', { name: 'LLM · Reranker' })).toBeInTheDocument()
  })
})
