import type { ReactNode } from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AdminReadContext } from './api/types'

interface MutableAuth {
  user: {
    access_token: string
    profile: { sub: string; name: string }
  }
  profile: {
    subject: string
    display_name: string
    default_workspace_id: string
    roles: string[]
    authentication_assurance: 'PASSWORD'
    workspace_selection_enabled: boolean
    hardware_webauthn_enabled: boolean
  }
  securityEpoch: number
  authorizationRevision: number
  readSecurityEpoch: () => number
  loading: boolean
  notice: undefined
  renewAccessToken: () => Promise<string | undefined>
  signIn: () => Promise<void>
  signOut: () => Promise<void>
  beginWebAuthnEnrollment: () => Promise<void>
  beginStepUp: () => Promise<void>
  beginPasswordReauth: () => Promise<void>
  beginPasswordChange: () => Promise<void>
  clearNotice: () => void
}

const appTest = vi.hoisted(() => {
  const request = vi.fn()
  return {
    auth: {} as MutableAuth,
    client: { request },
    request,
  }
})

vi.mock('./auth/AuthProvider', () => ({
  useAuth: () => appTest.auth,
}))

vi.mock('./api/useStableApiClient', () => ({
  useStableApiClient: () => appTest.client,
}))

vi.mock('./components/layout/AppShell', () => ({
  AppShell: ({
    adminContextStatus,
    children,
  }: {
    adminContextStatus?: string
    children: ReactNode
  }) => (
    <div>
      <span data-testid="admin-status">{adminContextStatus}</span>
      {children}
    </div>
  ),
}))

vi.mock('./features/admin/AdminPage', () => ({
  AdminPage: ({
    initialContext,
    suspended,
  }: {
    initialContext: AdminReadContext
    suspended?: boolean
  }) => (
    <section data-testid="admin-page" hidden={suspended}>
      <span>{initialContext.display_name}</span>
      <input aria-label="Admin draft" defaultValue="" />
    </section>
  ),
}))

vi.mock('./features/knowledge/KnowledgeWorkspacePage', () => ({
  KnowledgeWorkspacePage: ({ page }: { page: string }) => (
    <section aria-label="Knowledge workspace route">{page}</section>
  ),
}))

import { App } from './App'

const WORKSPACE_ONE = '00000000-0000-4000-8000-000000000100'
const WORKSPACE_TWO = '00000000-0000-4000-8000-000000000200'

describe('App authentication-bound Admin orchestration', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.history.replaceState({}, '', `/?page=admin&workspace=${WORKSPACE_ONE}`)
    Object.assign(appTest.auth, {
      user: {
        access_token: 'token-one',
        profile: { sub: 'external-subject', name: 'Administrator' },
      },
      profile: {
        subject: 'external-subject',
        display_name: 'Administrator',
        default_workspace_id: WORKSPACE_ONE,
        roles: ['administrator'],
        authentication_assurance: 'PASSWORD',
        workspace_selection_enabled: true,
        hardware_webauthn_enabled: true,
      },
      securityEpoch: 1,
      authorizationRevision: 1,
      readSecurityEpoch: () => appTest.auth.securityEpoch,
      loading: false,
      notice: undefined,
      renewAccessToken: vi.fn().mockResolvedValue('token-one'),
      signIn: vi.fn().mockResolvedValue(undefined),
      signOut: vi.fn().mockResolvedValue(undefined),
      beginWebAuthnEnrollment: vi.fn().mockResolvedValue(undefined),
      beginStepUp: vi.fn().mockResolvedValue(undefined),
      beginPasswordReauth: vi.fn().mockResolvedValue(undefined),
      beginPasswordChange: vi.fn().mockResolvedValue(undefined),
      clearNotice: vi.fn(),
    })
  })

  it('revalidates same-session Admin access without losing a draft unless context changes', async () => {
    const firstResponse = deferred<AdminReadContext>()
    const secondResponse = deferred<AdminReadContext>()
    const thirdResponse = deferred<AdminReadContext>()
    const fourthResponse = deferred<AdminReadContext>()
    const adminResponses = [firstResponse, secondResponse, thirdResponse, fourthResponse]
    appTest.request.mockImplementation((path: string) => {
      if (path === '/admin/me') {
        const next = adminResponses.shift()
        if (!next) throw new Error('unexpected /admin/me request')
        return next.promise
      }
      if (path === '/capabilities') {
        return Promise.resolve({
          items: [],
          external_system_links: [],
          grafana_embed: { state: 'DISABLED' },
          deployment_tier: 'SINGLE_NODE_PILOT',
        })
      }
      if (path === '/catalog/export-capability') return Promise.resolve({ enabled: false })
      throw new Error(`unexpected request: ${path}`)
    })
    const view = render(<App />)
    const first = adminContext()
    firstResponse.resolve(first)
    await screen.findByText('Administrator')
    const draft = screen.getByRole('textbox', { name: 'Admin draft' })
    fireEvent.change(draft, { target: { value: 'unsaved policy draft' } })

    appTest.auth.authorizationRevision = 2
    view.rerender(<App />)
    await waitFor(() => expect(screen.getByTestId('admin-page')).not.toBeVisible())
    secondResponse.resolve({ ...first })
    await waitFor(() => expect(screen.getByTestId('admin-page')).toBeVisible())
    expect(screen.getByRole('textbox', { name: 'Admin draft' })).toHaveValue(
      'unsaved policy draft',
    )
    expect(appTest.request.mock.calls.filter(([path]) => path === '/capabilities')).toHaveLength(1)

    appTest.auth.authorizationRevision = 3
    view.rerender(<App />)
    thirdResponse.resolve({
      ...first,
      allowed_operations: ['RETENTION_POLICY_READ'],
    })
    await waitFor(() => expect(screen.getByTestId('admin-page')).toBeVisible())
    expect(screen.getByRole('textbox', { name: 'Admin draft' })).toHaveValue('')

    appTest.auth.authorizationRevision = 4
    view.rerender(<App />)
    fourthResponse.resolve({ ...first, workspace_id: WORKSPACE_TWO })
    await waitFor(() => expect(screen.queryByTestId('admin-page')).not.toBeInTheDocument())
    expect(screen.getByTestId('admin-status')).toHaveTextContent('denied')

    const adminCalls = appTest.request.mock.calls.filter(([path]) => path === '/admin/me')
    expect(adminCalls).toHaveLength(4)
    for (const [, options] of adminCalls) {
      const requestOptions = options as RequestInit | undefined
      expect(requestOptions?.cache).toBe('no-store')
      expect(requestOptions?.signal).toBeInstanceOf(AbortSignal)
    }
  })

  it('synchronizes the controlled page after an OIDC callback restores its return URL', async () => {
    window.history.replaceState({}, '', '/')
    const profile = appTest.auth.profile
    appTest.auth.profile = undefined as unknown as MutableAuth['profile']
    appTest.auth.loading = true
    appTest.request.mockImplementation((path: string) => {
      if (path === '/admin/me') return Promise.resolve(adminContext())
      if (path === '/capabilities') {
        return Promise.resolve({
          items: [],
          external_system_links: [],
          grafana_embed: { state: 'DISABLED' },
          deployment_tier: 'SINGLE_NODE_PILOT',
        })
      }
      if (path === '/catalog/export-capability') return Promise.resolve({ enabled: false })
      throw new Error(`unexpected request: ${path}`)
    })
    const view = render(<App />)

    window.history.replaceState(
      {},
      '',
      `/?page=knowledge-studio&workspace=${WORKSPACE_ONE}`,
    )
    appTest.auth.profile = profile
    appTest.auth.loading = false
    view.rerender(<App />)

    expect(await screen.findByRole('region', {
      name: 'Knowledge workspace route',
    })).toHaveTextContent('knowledge-studio')
  })
})

function adminContext(): AdminReadContext {
  return {
    subject_id: '00000000-0000-4000-8000-000000000001',
    workspace_id: WORKSPACE_ONE,
    display_name: 'Administrator',
    authentication_assurance: 'PASSWORD',
    fallback_enabled: false,
    allowed_operations: ['MEMBERSHIP_ACCESS_READ'],
    action_vocabulary: ['catalog.read'],
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((accept) => { resolve = accept })
  return { promise, resolve }
}
