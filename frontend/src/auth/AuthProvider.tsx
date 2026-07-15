import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { UserManager, WebStorageStateStore, type User } from 'oidc-client-ts'

interface AuthValue {
  user?: User
  loading: boolean
  signIn: () => Promise<void>
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthValue | undefined>(undefined)

function createManager(): UserManager {
  return new UserManager({
    authority: String(import.meta.env.VITE_OIDC_AUTHORITY),
    client_id: String(import.meta.env.VITE_OIDC_CLIENT_ID),
    redirect_uri: String(import.meta.env.VITE_OIDC_REDIRECT_URI || window.location.origin),
    post_logout_redirect_uri: window.location.origin,
    response_type: 'code',
    scope: 'openid profile email',
    userStore: new WebStorageStateStore({ store: window.sessionStorage }),
    automaticSilentRenew: false,
    monitorSession: true,
  })
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const manager = useMemo(() => createManager(), [])
  const [user, setUser] = useState<User>()
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    const initialize = async () => {
      try {
        const params = new URLSearchParams(window.location.search)
        const next = params.has('code') && params.has('state')
          ? await manager.signinRedirectCallback()
          : await manager.getUser()
        if (params.has('code')) window.history.replaceState({}, document.title, '/')
        if (active && next && !next.expired) setUser(next)
      } finally {
        if (active) setLoading(false)
      }
    }
    const loaded = (next: User) => setUser(next)
    const unloaded = () => setUser(undefined)
    manager.events.addUserLoaded(loaded)
    manager.events.addUserUnloaded(unloaded)
    void initialize()
    return () => {
      active = false
      manager.events.removeUserLoaded(loaded)
      manager.events.removeUserUnloaded(unloaded)
    }
  }, [manager])

  const value = useMemo<AuthValue>(() => ({
    user,
    loading,
    signIn: () => manager.signinRedirect(),
    signOut: () => manager.signoutRedirect(),
  }), [loading, manager, user])

  return <AuthContext value={value}>{children}</AuthContext>
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('AuthProvider가 필요합니다.')
  return value
}
