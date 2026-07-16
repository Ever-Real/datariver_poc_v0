import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { UserManager, WebStorageStateStore, type User } from 'oidc-client-ts'
import { readRedirectState, signinRedirectArgs, type AuthIntent } from './redirectState'

export interface AuthNotice {
  kind: 'INFO' | 'ERROR'
  message: string
}

interface AuthValue {
  user?: User
  loading: boolean
  notice?: AuthNotice
  signIn: () => Promise<void>
  signOut: () => Promise<void>
  beginWebAuthnEnrollment: () => Promise<void>
  beginStepUp: () => Promise<void>
  clearNotice: () => void
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
  const [notice, setNotice] = useState<AuthNotice>()

  useEffect(() => {
    let active = true
    const initialize = async () => {
      try {
        const params = new URLSearchParams(window.location.search)
        const callback = params.has('state') && (params.has('code') || params.has('error'))
        const actionStatus = params.get('kc_action_status')
        const next = callback ? await manager.signinRedirectCallback() : await manager.getUser()
        if (callback && next) {
          const state = readRedirectState(next.state)
          window.history.replaceState({}, document.title, state.returnTo)
          if (active && state.intent === 'STEP_UP') {
            setNotice({
              kind: 'INFO',
              message: '보안키 인증 응답을 받았습니다. 작업 대상과 내용을 다시 확인한 뒤 실행하세요.',
            })
          }
          if (active && state.intent === 'WEBAUTHN_ENROLLMENT') {
            setNotice({
              kind: actionStatus === 'cancelled' ? 'ERROR' : 'INFO',
              message: actionStatus === 'cancelled'
                ? '보안키 등록이 취소되었습니다.'
                : '보안키 등록 응답을 받았습니다. 고위험 작업 전에 보안키 인증을 진행하세요.',
            })
          }
        }
        if (active && next && !next.expired) setUser(next)
      } catch {
        if (active) {
          setNotice({ kind: 'ERROR', message: '인증 응답을 검증하지 못했습니다. 다시 로그인하세요.' })
          window.history.replaceState({}, document.title, '/')
        }
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

  const beginRedirect = useCallback(async (intent: AuthIntent) => {
    try {
      const highAssuranceAcr = String(import.meta.env.VITE_OIDC_HIGH_ASSURANCE_ACR || '')
      await manager.signinRedirect(signinRedirectArgs(intent, { highAssuranceAcr }))
    } catch (error) {
      setNotice({
        kind: 'ERROR',
        message: error instanceof Error ? error.message : '인증 요청을 시작하지 못했습니다.',
      })
    }
  }, [manager])

  const value = useMemo<AuthValue>(() => ({
    user,
    loading,
    notice,
    signIn: () => beginRedirect('SIGN_IN'),
    signOut: () => manager.signoutRedirect(),
    beginWebAuthnEnrollment: () => beginRedirect('WEBAUTHN_ENROLLMENT'),
    beginStepUp: () => beginRedirect('STEP_UP'),
    clearNotice: () => setNotice(undefined),
  }), [beginRedirect, loading, manager, notice, user])

  return <AuthContext value={value}>{children}</AuthContext>
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('AuthProvider가 필요합니다.')
  return value
}
