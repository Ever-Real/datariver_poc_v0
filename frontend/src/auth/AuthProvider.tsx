import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { InMemoryWebStorage, UserManager, WebStorageStateStore, type User } from 'oidc-client-ts'
import type { AuthenticatedProfile } from '../api/types'
import {
  callbackReturnTo,
  readRedirectState,
  redirectState,
  signinRedirectArgs,
  type AuthIntent,
} from './redirectState'

export interface AuthNotice {
  kind: 'INFO' | 'ERROR'
  message: string
}

interface AuthValue {
  user?: User
  profile?: AuthenticatedProfile
  loading: boolean
  notice?: AuthNotice
  signIn: () => Promise<void>
  signOut: () => Promise<void>
  beginWebAuthnEnrollment: () => Promise<void>
  beginStepUp: () => Promise<void>
  beginPasswordReauth: () => Promise<void>
  clearNotice: () => void
}

const AuthContext = createContext<AuthValue | undefined>(undefined)

function createManager(): UserManager {
  const authority = String(import.meta.env.VITE_OIDC_AUTHORITY || '').trim()
  const clientId = String(import.meta.env.VITE_OIDC_CLIENT_ID || '').trim()
  if (!authority || !clientId) throw new Error('OIDC 공개 설정이 누락되었습니다.')
  const configuredRedirectUri = String(import.meta.env.VITE_OIDC_REDIRECT_URI || window.location.origin)
  const configuredOrigin = new URL(configuredRedirectUri).origin
  // Keycloak has an exact browser-origin redirect allowlist. Keep that origin,
  // but bind the redirect path/query to the safe current return path so a
  // top-level prompt=none SSO round-trip does not drop the workspace selector.
  const redirectUri = new URL(callbackReturnTo(), configuredOrigin).toString()
  return new UserManager({
    authority,
    client_id: clientId,
    redirect_uri: redirectUri,
    post_logout_redirect_uri: window.location.origin,
    response_type: 'code',
    scope: 'openid profile email',
    // Access/refresh tokens and the selected user must not survive in browser
    // storage. The OIDC library keeps only its separate, short-lived PKCE
    // transaction state across the redirect.
    userStore: new WebStorageStateStore({ store: new InMemoryWebStorage() }),
    automaticSilentRenew: false,
    monitorSession: true,
  })
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const manager = useMemo(() => createManager(), [])
  const [user, setUser] = useState<User>()
  const [profile, setProfile] = useState<AuthenticatedProfile>()
  const [loading, setLoading] = useState(true)
  const [notice, setNotice] = useState<AuthNotice>()
  const mounted = useRef(false)
  const callbackInProgress = useRef(false)
  const ssoProbeStarted = useRef(false)

  useEffect(() => {
    mounted.current = true
    const hydrate = async (next: User) => {
      if (!next.access_token || next.expired) return false
      const response = await fetch(`${String(import.meta.env.VITE_API_BASE_URL || '/api/v1')}/auth/me`, {
        headers: { Authorization: `Bearer ${next.access_token}`, Accept: 'application/json' },
      })
      if (!response.ok) throw new Error('서버가 현재 인증 세션을 확인하지 못했습니다.')
      const value = await response.json() as AuthenticatedProfile
      if (mounted.current) {
        setUser(next)
        setProfile(value)
      }
      return true
    }
    const initialize = async () => {
      try {
        const params = new URLSearchParams(window.location.search)
        const callback = params.has('state') && (params.has('code') || params.has('error'))
        const actionStatus = params.get('kc_action_status')
        if (callback && params.has('error')) {
          // The silent SSO probe is allowed once per app load. Mark its
          // rejection before cleaning the callback URL so React StrictMode
          // does not immediately launch another top-level redirect.
          ssoProbeStarted.current = true
          if (mounted.current) {
            setNotice({
              kind: 'INFO',
              message: '기존 로그인 세션을 찾지 못했습니다. 계속하려면 Sign In을 선택하세요.',
            })
          }
          window.history.replaceState({}, document.title, callbackReturnTo())
          return
        }
        if (callback) {
          if (callbackInProgress.current) return
          callbackInProgress.current = true
        }
        const next = callback ? await manager.signinRedirectCallback() : await manager.getUser()
        if (callback && next) {
          const state = readRedirectState(next.state)
          const callbackPath = callbackReturnTo()
          const returnTo = state.returnTo === '/' && callbackPath !== '/' ? callbackPath : state.returnTo
          window.history.replaceState({}, document.title, returnTo)
          if (mounted.current && state.intent === 'STEP_UP') {
            setNotice({
              kind: 'INFO',
              message: '보안키 인증 응답을 받았습니다. 작업 대상과 내용을 다시 확인한 뒤 실행하세요.',
            })
          }
          if (mounted.current && state.intent === 'PASSWORD_REAUTH') {
            setNotice({
              kind: 'INFO',
              message: '비밀번호 재인증 응답을 받았습니다. 작업은 자동 실행되지 않았습니다. 대상과 내용을 다시 확인한 뒤 실행하세요.',
            })
          }
          if (mounted.current && state.intent === 'WEBAUTHN_ENROLLMENT') {
            setNotice({
              kind: actionStatus === 'cancelled' ? 'ERROR' : 'INFO',
              message: actionStatus === 'cancelled'
                ? '보안키 등록이 취소되었습니다.'
                : '보안키 등록 응답을 받았습니다. 고위험 작업 전에 보안키 인증을 진행하세요.',
            })
          }
        }
        if (next && !next.expired && await hydrate(next)) return
        if (!callback) {
          if (ssoProbeStarted.current) return
          ssoProbeStarted.current = true
          // A top-level prompt=none redirect reuses the Keycloak SSO cookie
          // without persisting a bearer token or any role in browser storage.
          await manager.signinRedirect({
            state: redirectState('SIGN_IN'),
            extraQueryParams: { prompt: 'none' },
          })
          return
        }
      } catch {
        if (mounted.current) {
          setNotice({ kind: 'ERROR', message: '인증 응답을 검증하지 못했습니다. 다시 로그인하세요.' })
          window.history.replaceState({}, document.title, callbackReturnTo())
        }
      } finally {
        if (mounted.current) setLoading(false)
      }
    }
    const loaded = (next: User) => { void hydrate(next) }
    const unloaded = () => { setUser(undefined); setProfile(undefined) }
    manager.events.addUserLoaded(loaded)
    manager.events.addUserUnloaded(unloaded)
    void initialize()
    return () => {
      mounted.current = false
      manager.events.removeUserLoaded(loaded)
      manager.events.removeUserUnloaded(unloaded)
    }
  }, [manager])

  const beginRedirect = useCallback(async (intent: AuthIntent) => {
    try {
      const highAssuranceAcr = String(import.meta.env.VITE_OIDC_HIGH_ASSURANCE_ACR || '')
      const passwordReauthAcr = String(import.meta.env.VITE_OIDC_PASSWORD_REAUTH_ACR || '')
      await manager.signinRedirect(signinRedirectArgs(intent, {
        highAssuranceAcr,
        passwordReauthAcr,
      }))
    } catch (error) {
      setNotice({
        kind: 'ERROR',
        message: error instanceof Error ? error.message : '인증 요청을 시작하지 못했습니다.',
      })
    }
  }, [manager])

  const value = useMemo<AuthValue>(() => ({
    user,
    profile,
    loading,
    notice,
    signIn: () => beginRedirect('SIGN_IN'),
    signOut: () => manager.signoutRedirect(),
    beginWebAuthnEnrollment: () => beginRedirect('WEBAUTHN_ENROLLMENT'),
    beginStepUp: () => beginRedirect('STEP_UP'),
    beginPasswordReauth: () => beginRedirect('PASSWORD_REAUTH'),
    clearNotice: () => setNotice(undefined),
  }), [beginRedirect, loading, manager, notice, profile, user])

  return <AuthContext value={value}>{children}</AuthContext>
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('AuthProvider가 필요합니다.')
  return value
}
