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

function Harness() {
  const auth = useAuth()
  if (auth.loading) return <span>loading</span>
  return (
    <div>
      {auth.notice && <span>{auth.notice.message}</span>}
      {auth.profile && <span>{auth.profile.display_name}:{auth.profile.roles.join(',')}</span>}
      <button onClick={() => void auth.signIn()}>sign in</button>
      <button onClick={() => void auth.beginPasswordReauth()}>password reauth</button>
      <button onClick={() => void auth.renewAccessToken()}>renew access token</button>
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
      }),
    }))
  })

  it('starts a deployment-configured fresh password redirect', async () => {
    render(<AuthProvider><Harness /></AuthProvider>)
    fireEvent.click(await screen.findByRole('button', { name: 'password reauth' }))

    expect(oidc.InMemoryWebStorage).toHaveBeenCalledOnce()
    expect(oidc.WebStorageStateStore).toHaveBeenCalledOnce()
    expect(oidc.signinRedirect).toHaveBeenLastCalledWith({
      acr_values: 'password-reauth',
      max_age: 0,
      state: { version: 1, intent: 'PASSWORD_REAUTH', returnTo: '/' },
    })
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
      access_token: 'old-token', expired: false, profile: { sub: 'subject-one' },
    })
    oidc.signinSilent.mockResolvedValue({
      access_token: 'new-token', expired: false, profile: { sub: 'subject-one' },
    })
    render(<AuthProvider><Harness /></AuthProvider>)

    await screen.findByText('DataRiver Admin:administrator')
    const expiring = oidc.addAccessTokenExpiring.mock.calls[0]?.[0] as (() => void) | undefined
    expect(expiring).toBeTypeOf('function')
    expiring?.()

    await waitFor(() => expect(oidc.signinSilent).toHaveBeenCalledOnce())
    await waitFor(() => expect(fetch).toHaveBeenLastCalledWith('/api/v1/auth/me', expect.objectContaining({
      headers: { Authorization: 'Bearer new-token', Accept: 'application/json' },
    })))
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
})
