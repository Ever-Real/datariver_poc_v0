import { useState } from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const oidc = vi.hoisted(() => ({
  addAccessTokenExpiring: vi.fn(),
  addUserLoaded: vi.fn(),
  addUserUnloaded: vi.fn(),
  getUser: vi.fn(),
  removeUserLoaded: vi.fn(),
  removeUserUnloaded: vi.fn(),
  removeAccessTokenExpiring: vi.fn(),
  signinSilent: vi.fn(),
  signinRedirect: vi.fn(),
  signinRedirectCallback: vi.fn(),
  signoutRedirect: vi.fn(),
  InMemoryWebStorage: vi.fn(function InMemoryWebStorage() {
    return {}
  }),
  WebStorageStateStore: vi.fn(function WebStorageStateStore() {
    return {}
  }),
}))

vi.mock('oidc-client-ts', () => ({
  UserManager: vi.fn(function UserManager() {
    return {
      events: {
        addAccessTokenExpiring: oidc.addAccessTokenExpiring,
        addUserLoaded: oidc.addUserLoaded,
        addUserUnloaded: oidc.addUserUnloaded,
        removeAccessTokenExpiring: oidc.removeAccessTokenExpiring,
        removeUserLoaded: oidc.removeUserLoaded,
        removeUserUnloaded: oidc.removeUserUnloaded,
      },
      getUser: oidc.getUser,
      signinSilent: oidc.signinSilent,
      signinRedirect: oidc.signinRedirect,
      signinRedirectCallback: oidc.signinRedirectCallback,
      signoutRedirect: oidc.signoutRedirect,
    }
  }),
  InMemoryWebStorage: oidc.InMemoryWebStorage,
  WebStorageStateStore: oidc.WebStorageStateStore,
}))

import { AuthProvider, useAuth } from './AuthProvider'
import { useStableApiClient } from '../api/useStableApiClient'

function Harness() {
  const auth = useAuth()
  if (auth.loading) return <span>loading</span>
  return (
    <div>
      {auth.notice && <span>{auth.notice.message}</span>}
      {auth.profile && <span>{auth.profile.display_name}:{auth.profile.roles.join(',')}</span>}
      <span data-testid="security-epoch">{auth.securityEpoch}</span>
      <span data-testid="authorization-revision">{auth.authorizationRevision}</span>
      <button onClick={() => void auth.signIn()}>sign in</button>
      <button onClick={() => void auth.beginPasswordReauth()}>password reauth</button>
      <button onClick={() => void auth.beginPasswordChange()}>password change</button>
      <button onClick={() => void auth.beginWebAuthnEnrollment()}>enroll WebAuthn</button>
      <button onClick={() => void auth.beginStepUp()}>step up WebAuthn</button>
      <button onClick={() => void auth.renewAccessToken()}>renew access token</button>
      <button onClick={() => void auth.signOut()}>sign out</button>
    </div>
  )
}

function ApiBoundaryHarness() {
  const auth = useAuth()
  const [result, setResult] = useState('')
  const client = useStableApiClient(
    '/api/v1',
    auth.user?.access_token,
    'workspace-one',
    auth.renewAccessToken,
    auth.readSecurityEpoch,
  )
  if (auth.loading) return <span>loading</span>
  return (
    <div>
      {auth.profile && <span>{auth.profile.display_name}</span>}
      <span>{result}</span>
      <button onClick={() => {
        void client.request('/resource')
          .then(() => setResult('success'))
          .catch((error: unknown) => {
            setResult(error instanceof Error ? error.name : 'unknown')
          })
      }}>request resource</button>
    </div>
  )
}

describe('AuthProvider password reauthentication', () => {
  afterEach(() => vi.unstubAllGlobals())

  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubEnv('VITE_OIDC_AUTHORITY', 'https://idp.example.test/realms/datariver')
    vi.stubEnv('VITE_OIDC_CLIENT_ID', 'datariver-web')
    vi.stubEnv('VITE_OIDC_REDIRECT_URI', 'https://catalog.example.test')
    vi.stubEnv('VITE_OIDC_PASSWORD_REAUTH_ACR', 'password-reauth')
    vi.stubEnv('VITE_OIDC_HIGH_ASSURANCE_ACR', 'hardware')
    window.history.replaceState({}, '', '/')
    oidc.getUser.mockResolvedValue(undefined)
    oidc.signinSilent.mockResolvedValue(undefined)
    oidc.signinRedirect.mockResolvedValue(undefined)
    oidc.signinRedirectCallback.mockResolvedValue(undefined)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        subject: 'subject-one', display_name: 'DataRiver Admin', email: 'admin@example.test',
        roles: ['administrator'], authentication_assurance: 'PASSWORD', authentication_time: '2026-07-17T00:00:00Z',
        workspace_selection_enabled: true, hardware_webauthn_enabled: true,
      }),
    }))
  })

  it('starts a deployment-configured fresh password redirect', async () => {
    render(<AuthProvider><Harness /></AuthProvider>)
    fireEvent.click(await screen.findByRole('button', { name: 'password reauth' }))

    expect(oidc.InMemoryWebStorage).toHaveBeenCalledOnce()
    expect(oidc.WebStorageStateStore).toHaveBeenCalledTimes(2)
    expect(oidc.WebStorageStateStore).toHaveBeenNthCalledWith(2, {
      store: window.sessionStorage,
      prefix: 'datariver.oidc.transaction.',
    })
    expect(oidc.signinRedirect).toHaveBeenLastCalledWith({
      acr_values: 'password-reauth',
      max_age: 0,
      state: { version: 1, intent: 'PASSWORD_REAUTH', returnTo: '/' },
    })
  })

  it('starts a branded identity password-change action without receiving the password', async () => {
    render(<AuthProvider><Harness /></AuthProvider>)
    fireEvent.click(await screen.findByRole('button', { name: 'password change' }))

    expect(oidc.signinRedirect).toHaveBeenLastCalledWith({
      max_age: 0,
      extraQueryParams: { kc_action: 'UPDATE_PASSWORD' },
      state: { version: 1, intent: 'PASSWORD_CHANGE', returnTo: '/' },
    })
  })

  it('returns to DataRiver and reports a completed password change', async () => {
    window.history.replaceState(
      {},
      '',
      '/?state=callback&code=authorization-code&kc_action_status=success',
    )
    oidc.signinRedirectCallback.mockResolvedValue({
      access_token: 'not-a-real-token', expired: false, profile: { sub: 'subject-one' },
      state: { version: 1, intent: 'PASSWORD_CHANGE', returnTo: '/?page=profile' },
    })

    render(<AuthProvider><Harness /></AuthProvider>)

    expect(await screen.findByText('비밀번호가 변경되었습니다.')).toBeInTheDocument()
    expect(`${window.location.pathname}${window.location.search}`).toBe('/?page=profile')
    expect(oidc.signinRedirect).not.toHaveBeenCalled()
  })

  it('shows a redirecting state immediately when custom sign-in is selected', async () => {
    render(<AuthProvider><Harness /></AuthProvider>)
    fireEvent.click(await screen.findByRole('button', { name: 'sign in' }))

    expect(await screen.findByText('loading')).toBeInTheDocument()
    expect(oidc.signinRedirect).toHaveBeenLastCalledWith({
      state: { version: 1, intent: 'SIGN_IN', returnTo: '/' },
    })
  })

  it('restores the URL and only shows guidance after the callback', async () => {
    window.history.replaceState({}, '', '/?state=callback&code=authorization-code')
    oidc.signinRedirectCallback.mockResolvedValue({
      access_token: 'not-a-real-token',
      expired: false,
      profile: { sub: 'subject-one' },
      state: {
        version: 1,
        intent: 'PASSWORD_REAUTH',
        returnTo: '/?page=admin#fallback',
      },
    })

    render(<AuthProvider><Harness /></AuthProvider>)

    expect(await screen.findByText(/작업은 자동 실행되지 않았습니다/)).toBeInTheDocument()
    expect(`${window.location.pathname}${window.location.search}${window.location.hash}`).toBe(
      '/?page=admin#fallback',
    )
    expect(oidc.signinRedirectCallback).toHaveBeenCalledOnce()
    expect(oidc.signinRedirect).not.toHaveBeenCalled()
  })

  it('hydrates verified server profile after an in-memory OIDC callback', async () => {
    window.history.replaceState({}, '', '/?state=callback&code=authorization-code')
    oidc.signinRedirectCallback.mockResolvedValue({
      access_token: 'not-a-real-token', expired: false, profile: { sub: 'subject-one' },
      state: { version: 1, intent: 'SIGN_IN', returnTo: '/' },
    })

    render(<AuthProvider><Harness /></AuthProvider>)

    expect(await screen.findByText('DataRiver Admin:administrator')).toBeInTheDocument()
    expect(fetch).toHaveBeenCalledWith('/api/v1/auth/me', expect.objectContaining({
      headers: { Authorization: 'Bearer not-a-real-token', Accept: 'application/json' },
    }))
  })

  it('stops after one rejected silent SSO probe and exposes explicit sign-in', async () => {
    window.history.replaceState({}, '', '/?state=callback&error=login_required')

    render(<AuthProvider><Harness /></AuthProvider>)

    expect(await screen.findByText(/기존 로그인 세션을 찾지 못했습니다/)).toBeInTheDocument()
    expect(oidc.signinRedirect).not.toHaveBeenCalled()
    expect(`${window.location.pathname}${window.location.search}${window.location.hash}`).toBe('/')
  })

  it('uses a top-level Keycloak SSO probe on reload without persistent browser state', async () => {
    window.history.replaceState({}, '', '/?workspace=00000000-0000-4000-8000-000000000100&page=catalog')
    render(<AuthProvider><Harness /></AuthProvider>)

    await screen.findByRole('button', { name: 'password reauth' })
    expect(oidc.signinRedirect).toHaveBeenCalledWith({
      state: {
        version: 1,
        intent: 'SIGN_IN',
        returnTo: '/?workspace=00000000-0000-4000-8000-000000000100&page=catalog',
      },
      extraQueryParams: { prompt: 'none' },
    })
  })

  it('renews in memory before expiry, then rehydrates the server-verified profile', async () => {
    oidc.getUser.mockResolvedValue({
      access_token: 'old-token', expired: false, session_state: 'session-one',
      profile: { sub: 'subject-one' },
    })
    oidc.signinSilent.mockResolvedValue({
      access_token: 'new-token', expired: false, session_state: 'session-one',
      profile: { sub: 'subject-one' },
    })
    render(<AuthProvider><Harness /></AuthProvider>)

    await screen.findByText('DataRiver Admin:administrator')
    const initialEpoch = screen.getByTestId('security-epoch').textContent
    const initialRevision = screen.getByTestId('authorization-revision').textContent
    const expiring = oidc.addAccessTokenExpiring.mock.calls[0]?.[0] as (() => void) | undefined
    expect(expiring).toBeTypeOf('function')
    expiring?.()

    await waitFor(() => expect(oidc.signinSilent).toHaveBeenCalledOnce())
    await waitFor(() => expect(fetch).toHaveBeenLastCalledWith('/api/v1/auth/me', expect.objectContaining({
      headers: { Authorization: 'Bearer new-token', Accept: 'application/json' },
    })))
    expect(screen.getByTestId('security-epoch')).toHaveTextContent(initialEpoch ?? '')
    await waitFor(() => {
      expect(screen.getByTestId('authorization-revision').textContent).not.toBe(initialRevision)
    })
  })

  it('advances the security epoch when renewed claims change the admin context', async () => {
    oidc.getUser.mockResolvedValue({
      access_token: 'old-token', expired: false, session_state: 'session-one',
      profile: { sub: 'subject-one' },
    })
    oidc.signinSilent.mockResolvedValue({
      access_token: 'step-up-token', expired: false, session_state: 'session-one',
      profile: { sub: 'subject-one' },
    })
    vi.stubGlobal('fetch', vi.fn((_, init?: RequestInit) => {
      const authorization = new Headers(init?.headers).get('Authorization')
      const steppedUp = authorization === 'Bearer step-up-token'
      return Promise.resolve(new Response(JSON.stringify({
        subject: 'subject-one',
        display_name: 'DataRiver Admin',
        roles: ['administrator'],
        authentication_assurance: steppedUp ? 'HARDWARE_WEBAUTHN' : 'PASSWORD',
        authentication_time: steppedUp ? '2026-07-17T00:05:00Z' : '2026-07-17T00:00:00Z',
        workspace_selection_enabled: true,
        hardware_webauthn_enabled: true,
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    }))
    render(<AuthProvider><Harness /></AuthProvider>)

    await screen.findByText('DataRiver Admin:administrator')
    const initialEpoch = screen.getByTestId('security-epoch').textContent
    const expiring = oidc.addAccessTokenExpiring.mock.calls[0]?.[0] as (() => void) | undefined
    expiring?.()

    await waitFor(() => {
      expect(screen.getByTestId('security-epoch').textContent).not.toBe(initialEpoch)
    })
  })

  it('discards an older profile hydration after a newer OIDC session wins', async () => {
    const oldProfile = deferred<Response>()
    oidc.getUser.mockResolvedValue({
      access_token: 'old-token', expired: false, session_state: 'old-session',
      profile: { sub: 'subject-old' },
    })
    vi.stubGlobal('fetch', vi.fn((_, init?: RequestInit) => {
      const authorization = new Headers(init?.headers).get('Authorization')
      if (authorization === 'Bearer old-token') return oldProfile.promise
      if (authorization === 'Bearer new-token') {
        return Promise.resolve(new Response(JSON.stringify({
          subject: 'subject-new',
          display_name: 'New Administrator',
          roles: ['administrator'],
          authentication_assurance: 'PASSWORD',
          authentication_time: '2026-07-17T00:10:00Z',
          workspace_selection_enabled: true,
          hardware_webauthn_enabled: true,
        }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      }
      throw new Error(`unexpected authorization: ${authorization}`)
    }))
    render(<AuthProvider><Harness /></AuthProvider>)
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
    const loaded = oidc.addUserLoaded.mock.calls[0]?.[0] as ((user: unknown) => void) | undefined
    loaded?.({
      access_token: 'new-token', expired: false, session_state: 'new-session',
      profile: { sub: 'subject-new' },
    })
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2))

    oldProfile.resolve(new Response(JSON.stringify({
      subject: 'subject-old',
      display_name: 'Old Administrator',
      roles: ['administrator'],
      authentication_assurance: 'PASSWORD',
      authentication_time: '2026-07-17T00:00:00Z',
      workspace_selection_enabled: true,
      hardware_webauthn_enabled: true,
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))

    expect(await screen.findByText('New Administrator:administrator')).toBeInTheDocument()
    expect(screen.queryByText('Old Administrator:administrator')).not.toBeInTheDocument()
  })

  it('rejects a server profile whose subject differs from the verified OIDC user', async () => {
    oidc.getUser.mockResolvedValue({
      access_token: 'subject-mismatch', expired: false, session_state: 'session-one',
      profile: { sub: 'subject-one' },
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      subject: 'subject-two',
      display_name: 'Wrong Subject',
      roles: ['administrator'],
      authentication_assurance: 'PASSWORD',
      workspace_selection_enabled: true,
      hardware_webauthn_enabled: true,
    }), { status: 200, headers: { 'Content-Type': 'application/json' } })))

    render(<AuthProvider><Harness /></AuthProvider>)

    expect(await screen.findByText(/인증 응답을 검증하지 못했습니다/)).toBeInTheDocument()
    expect(screen.queryByText('Wrong Subject:administrator')).not.toBeInTheDocument()
  })

  it('does not resurrect a profile whose hydration completes after unload', async () => {
    const profile = deferred<Response>()
    oidc.getUser.mockResolvedValue({
      access_token: 'old-token', expired: false, session_state: 'old-session',
      profile: { sub: 'subject-old' },
    })
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(profile.promise))
    render(<AuthProvider><Harness /></AuthProvider>)
    await waitFor(() => expect(fetch).toHaveBeenCalledOnce())
    const unloaded = oidc.addUserUnloaded.mock.calls[0]?.[0] as (() => void) | undefined
    unloaded?.()

    profile.resolve(new Response(JSON.stringify({
      subject: 'subject-old',
      display_name: 'Old Administrator',
      roles: ['administrator'],
      authentication_assurance: 'PASSWORD',
      workspace_selection_enabled: true,
      hardware_webauthn_enabled: true,
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))

    await Promise.resolve()
    expect(screen.queryByText('Old Administrator:administrator')).not.toBeInTheDocument()
  })

  it('invalidates authenticated memory before starting sign-out redirect', async () => {
    oidc.getUser.mockResolvedValue({
      access_token: 'token', expired: false, session_state: 'session-one',
      profile: { sub: 'subject-one' },
    })
    oidc.signoutRedirect.mockImplementation(() => new Promise(() => undefined))
    render(<AuthProvider><Harness /></AuthProvider>)
    await screen.findByText('DataRiver Admin:administrator')

    fireEvent.click(screen.getByRole('button', { name: 'sign out' }))

    await waitFor(() => {
      expect(screen.queryByText('DataRiver Admin:administrator')).not.toBeInTheDocument()
    })
    expect(oidc.signoutRedirect).toHaveBeenCalledOnce()
  })

  it('keeps a newer loaded session when an older renewal later fails', async () => {
    const renewal = deferred<never>()
    oidc.getUser.mockResolvedValue({
      access_token: 'old-token', expired: false, session_state: 'old-session',
      profile: { sub: 'subject-old' },
    })
    oidc.signinSilent.mockReturnValue(renewal.promise)
    vi.stubGlobal('fetch', vi.fn((_, init?: RequestInit) => {
      const authorization = new Headers(init?.headers).get('Authorization')
      const isNew = authorization === 'Bearer new-token'
      return Promise.resolve(new Response(JSON.stringify({
        subject: isNew ? 'subject-new' : 'subject-old',
        display_name: isNew ? 'New Administrator' : 'Old Administrator',
        roles: ['administrator'],
        authentication_assurance: 'PASSWORD',
        authentication_time: isNew ? '2026-07-17T01:00:00Z' : '2026-07-17T00:00:00Z',
        workspace_selection_enabled: true,
        hardware_webauthn_enabled: true,
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    }))
    render(<AuthProvider><Harness /></AuthProvider>)
    await screen.findByText('Old Administrator:administrator')
    fireEvent.click(screen.getByRole('button', { name: 'renew access token' }))
    await waitFor(() => expect(oidc.signinSilent).toHaveBeenCalledOnce())
    const loaded = oidc.addUserLoaded.mock.calls[0]?.[0] as ((user: unknown) => void) | undefined
    loaded?.({
      access_token: 'new-token', expired: false, session_state: 'new-session',
      profile: { sub: 'subject-new' },
    })
    renewal.reject(new Error('old renewal rejected'))

    expect(await screen.findByText('New Administrator:administrator')).toBeInTheDocument()
    expect(screen.queryByText('Old Administrator:administrator')).not.toBeInTheDocument()
    expect(screen.queryByText(/인증 세션을 갱신하지 못했습니다/)).not.toBeInTheDocument()
  })

  it('keeps a newer loaded session when the initial user lookup later fails', async () => {
    const initialLookup = deferred<never>()
    oidc.getUser.mockReturnValue(initialLookup.promise)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      subject: 'subject-new',
      display_name: 'New Administrator',
      roles: ['administrator'],
      authentication_assurance: 'PASSWORD',
      authentication_time: '2026-07-17T01:00:00Z',
      workspace_selection_enabled: true,
      hardware_webauthn_enabled: true,
    }), { status: 200, headers: { 'Content-Type': 'application/json' } })))
    render(<AuthProvider><Harness /></AuthProvider>)
    const loaded = oidc.addUserLoaded.mock.calls[0]?.[0] as ((user: unknown) => void) | undefined
    loaded?.({
      access_token: 'new-token', expired: false, session_state: 'new-session',
      profile: { sub: 'subject-new' },
    })
    await waitFor(() => expect(fetch).toHaveBeenCalledOnce())
    initialLookup.reject(new Error('old lookup rejected'))

    expect(await screen.findByText('New Administrator:administrator')).toBeInTheDocument()
    expect(screen.queryByText(/인증 응답을 검증하지 못했습니다/)).not.toBeInTheDocument()
  })

  it('does not publish a callback user after an unload event wins', async () => {
    const callback = deferred<{
      access_token: string
      expired: boolean
      session_state: string
      profile: { sub: string }
      state: { version: number; intent: string; returnTo: string }
    }>()
    window.history.replaceState({}, '', '/?state=callback&code=authorization-code')
    oidc.signinRedirectCallback.mockReturnValue(callback.promise)
    render(<AuthProvider><Harness /></AuthProvider>)
    const unloaded = oidc.addUserUnloaded.mock.calls[0]?.[0] as (() => void) | undefined
    unloaded?.()
    callback.resolve({
      access_token: 'callback-token',
      expired: false,
      session_state: 'callback-session',
      profile: { sub: 'subject-callback' },
      state: { version: 1, intent: 'SIGN_IN', returnTo: '/' },
    })

    await screen.findByRole('button', { name: 'sign in' })
    expect(fetch).not.toHaveBeenCalled()
    expect(screen.queryByText('DataRiver Admin:administrator')).not.toBeInTheDocument()
  })

  it('ignores a renewal UserLoaded event after sign-out invalidates the session', async () => {
    const renewal = deferred<{
      access_token: string
      expired: boolean
      session_state: string
      profile: { sub: string }
    }>()
    oidc.getUser.mockResolvedValue({
      access_token: 'old-token', expired: false, session_state: 'old-session',
      profile: { sub: 'subject-one' },
    })
    oidc.signinSilent.mockReturnValue(renewal.promise)
    oidc.signoutRedirect.mockImplementation(() => new Promise(() => undefined))
    render(<AuthProvider><Harness /></AuthProvider>)
    await screen.findByText('DataRiver Admin:administrator')
    fireEvent.click(screen.getByRole('button', { name: 'renew access token' }))
    await waitFor(() => expect(oidc.signinSilent).toHaveBeenCalledOnce())
    fireEvent.click(screen.getByRole('button', { name: 'sign out' }))
    const loaded = oidc.addUserLoaded.mock.calls[0]?.[0] as ((user: unknown) => void) | undefined
    const oldRenewedUser = {
      access_token: 'old-renewed-token',
      expired: false,
      session_state: 'old-session',
      profile: { sub: 'subject-one' },
    }
    loaded?.(oldRenewedUser)
    renewal.resolve(oldRenewedUser)

    await waitFor(() => expect(oidc.signoutRedirect).toHaveBeenCalledOnce())
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(screen.queryByText('DataRiver Admin:administrator')).not.toBeInTheDocument()
  })

  it('blocks a same-turn 401 retry when renewed security facts advance the ref epoch', async () => {
    oidc.getUser.mockResolvedValue({
      access_token: 'old-token', expired: false, session_state: 'session-one',
      profile: { sub: 'subject-one' },
    })
    oidc.signinSilent.mockResolvedValue({
      access_token: 'step-up-token', expired: false, session_state: 'session-one',
      profile: { sub: 'subject-one' },
    })
    let resourceRequests = 0
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string'
        ? input
        : input instanceof URL
          ? input.href
          : input.url
      if (url.endsWith('/auth/me')) {
        const steppedUp = new Headers(init?.headers).get('Authorization') === 'Bearer step-up-token'
        return Promise.resolve(new Response(JSON.stringify({
          subject: 'subject-one',
          display_name: 'Administrator',
          roles: ['administrator'],
          authentication_assurance: steppedUp ? 'HARDWARE_WEBAUTHN' : 'PASSWORD',
          authentication_time: steppedUp ? '2026-07-17T01:00:00Z' : '2026-07-17T00:00:00Z',
          workspace_selection_enabled: true,
          hardware_webauthn_enabled: true,
        }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      }
      if (url.endsWith('/resource')) {
        resourceRequests += 1
        return Promise.resolve(resourceRequests === 1
          ? new Response(JSON.stringify({ detail: 'expired' }), { status: 401 })
          : new Response(JSON.stringify({ value: 'must-not-retry' }), {
              status: 200,
              headers: { 'Content-Type': 'application/json' },
            }))
      }
      throw new Error(`unexpected request: ${url}`)
    }))
    render(<AuthProvider><ApiBoundaryHarness /></AuthProvider>)
    await screen.findByText('Administrator')

    fireEvent.click(screen.getByRole('button', { name: 'request resource' }))

    expect(await screen.findByText('StaleSecurityContextError')).toBeInTheDocument()
    expect(resourceRequests).toBe(1)
  })

  it('fails closed when silent renewal returns a different subject', async () => {
    oidc.getUser.mockResolvedValue({
      access_token: 'old-token', expired: false, session_state: 'old-session',
      profile: { sub: 'subject-old' },
    })
    oidc.signinSilent.mockResolvedValue({
      access_token: 'wrong-token', expired: false, session_state: 'new-session',
      profile: { sub: 'subject-new' },
    })
    vi.stubGlobal('fetch', vi.fn((_, init?: RequestInit) => {
      const authorization = new Headers(init?.headers).get('Authorization')
      return Promise.resolve(new Response(JSON.stringify({
        subject: authorization === 'Bearer old-token' ? 'subject-old' : 'subject-new',
        display_name: 'Administrator',
        roles: ['administrator'],
        authentication_assurance: 'PASSWORD',
        workspace_selection_enabled: true,
        hardware_webauthn_enabled: true,
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    }))
    render(<AuthProvider><Harness /></AuthProvider>)
    await screen.findByText('Administrator:administrator')
    fireEvent.click(screen.getByRole('button', { name: 'renew access token' }))

    expect(await screen.findByText(/인증 세션을 갱신하지 못했습니다/)).toBeInTheDocument()
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(screen.queryByText('Administrator:administrator')).not.toBeInTheDocument()
  })

  it('clears the previous identity when a newer UserLoaded profile cannot be verified', async () => {
    oidc.getUser.mockResolvedValue({
      access_token: 'old-token', expired: false, session_state: 'old-session',
      profile: { sub: 'subject-old' },
    })
    vi.stubGlobal('fetch', vi.fn((_, init?: RequestInit) => {
      const authorization = new Headers(init?.headers).get('Authorization')
      if (authorization === 'Bearer rejected-token') {
        return Promise.resolve(new Response(JSON.stringify({ detail: 'rejected' }), { status: 401 }))
      }
      return Promise.resolve(new Response(JSON.stringify({
        subject: 'subject-old',
        display_name: 'Old Administrator',
        roles: ['administrator'],
        authentication_assurance: 'PASSWORD',
        workspace_selection_enabled: true,
        hardware_webauthn_enabled: true,
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    }))
    render(<AuthProvider><Harness /></AuthProvider>)
    await screen.findByText('Old Administrator:administrator')
    const loaded = oidc.addUserLoaded.mock.calls[0]?.[0] as ((user: unknown) => void) | undefined
    loaded?.({
      access_token: 'rejected-token', expired: false, session_state: 'new-session',
      profile: { sub: 'subject-new' },
    })

    expect(await screen.findByText(/인증 응답을 검증하지 못했습니다/)).toBeInTheDocument()
    expect(screen.queryByText('Old Administrator:administrator')).not.toBeInTheDocument()
  })

  it('returns to the existing custom login state when renewal fails', async () => {
    oidc.getUser.mockResolvedValue({
      access_token: 'old-token', expired: false, profile: { sub: 'subject-one' },
    })
    oidc.signinSilent.mockRejectedValue(new Error('refresh rejected'))
    render(<AuthProvider><Harness /></AuthProvider>)

    fireEvent.click(await screen.findByRole('button', { name: 'renew access token' }))

    expect(await screen.findByText(/인증 세션을 갱신하지 못했습니다/)).toBeInTheDocument()
    expect(oidc.signinRedirect).not.toHaveBeenCalled()
  })

  it('does not start enrollment or step-up when the server disables WebAuthn', async () => {
    oidc.getUser.mockResolvedValue({
      access_token: 'token', expired: false, profile: { sub: 'subject-one' },
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        subject: 'subject-one', display_name: 'DataRiver Admin',
        roles: ['administrator'], authentication_assurance: 'PASSWORD',
        workspace_selection_enabled: false, hardware_webauthn_enabled: false,
      }),
    }))
    render(<AuthProvider><Harness /></AuthProvider>)

    await screen.findByText('DataRiver Admin:administrator')
    fireEvent.click(screen.getByRole('button', { name: 'enroll WebAuthn' }))
    expect(await screen.findByText(/WebAuthn이 비활성화/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'step up WebAuthn' }))
    expect(oidc.signinRedirect).not.toHaveBeenCalled()
  })
})

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((accept, decline) => {
    resolve = accept
    reject = decline
  })
  return { promise, reject, resolve }
}
