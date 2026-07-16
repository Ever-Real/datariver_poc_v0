import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const oidc = vi.hoisted(() => ({
  addUserLoaded: vi.fn(),
  addUserUnloaded: vi.fn(),
  getUser: vi.fn(),
  removeUserLoaded: vi.fn(),
  removeUserUnloaded: vi.fn(),
  signinRedirect: vi.fn(),
  signinRedirectCallback: vi.fn(),
  signoutRedirect: vi.fn(),
}))

vi.mock('oidc-client-ts', () => ({
  UserManager: vi.fn(function UserManager() {
    return {
      events: {
        addUserLoaded: oidc.addUserLoaded,
        addUserUnloaded: oidc.addUserUnloaded,
        removeUserLoaded: oidc.removeUserLoaded,
        removeUserUnloaded: oidc.removeUserUnloaded,
      },
      getUser: oidc.getUser,
      signinRedirect: oidc.signinRedirect,
      signinRedirectCallback: oidc.signinRedirectCallback,
      signoutRedirect: oidc.signoutRedirect,
    }
  }),
  WebStorageStateStore: vi.fn(function WebStorageStateStore() {
    return {}
  }),
}))

import { AuthProvider, useAuth } from './AuthProvider'

function Harness() {
  const auth = useAuth()
  if (auth.loading) return <span>loading</span>
  return (
    <div>
      {auth.notice && <span>{auth.notice.message}</span>}
      <button onClick={() => void auth.beginPasswordReauth()}>password reauth</button>
    </div>
  )
}

describe('AuthProvider password reauthentication', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubEnv('VITE_OIDC_PASSWORD_REAUTH_ACR', 'password-reauth')
    vi.stubEnv('VITE_OIDC_HIGH_ASSURANCE_ACR', 'hardware')
    window.history.replaceState({}, '', '/')
    oidc.getUser.mockResolvedValue(undefined)
    oidc.signinRedirect.mockResolvedValue(undefined)
    oidc.signinRedirectCallback.mockResolvedValue(undefined)
  })

  it('starts a deployment-configured fresh password redirect', async () => {
    render(<AuthProvider><Harness /></AuthProvider>)
    fireEvent.click(await screen.findByRole('button', { name: 'password reauth' }))

    expect(oidc.signinRedirect).toHaveBeenCalledWith({
      acr_values: 'password-reauth',
      max_age: 0,
      state: { version: 1, intent: 'PASSWORD_REAUTH', returnTo: '/' },
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
})
