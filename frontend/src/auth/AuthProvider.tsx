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
import { publicRuntimeConfig } from '../runtimeConfig'
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
  securityEpoch: number
  authorizationRevision: number
  readSecurityEpoch: () => number
  loading: boolean
  notice?: AuthNotice
  renewAccessToken: () => Promise<string | undefined>
  signIn: () => Promise<void>
  signOut: () => Promise<void>
  beginWebAuthnEnrollment: () => Promise<void>
  beginStepUp: () => Promise<void>
  beginPasswordReauth: () => Promise<void>
  beginPasswordChange: () => Promise<void>
  clearNotice: () => void
}

const AuthContext = createContext<AuthValue | undefined>(undefined)

type HydrationResult = 'APPLIED' | 'STALE' | 'UNUSABLE'

function oidcSubject(user: User): string | undefined {
  const subject = user.profile.sub
  return typeof subject === 'string' && subject.trim() ? subject : undefined
}

function oidcSessionFingerprint(user: User): string {
  const claims = user.profile as Record<string, unknown>
  const sessionMarker = user.session_state
    ?? (typeof claims.sid === 'string' ? claims.sid : undefined)
    ?? (typeof claims.auth_time === 'number' ? String(claims.auth_time) : undefined)
    ?? 'provider-session-unavailable'
  return JSON.stringify([
    typeof claims.iss === 'string' ? claims.iss : '',
    oidcSubject(user) ?? '',
    sessionMarker,
  ])
}

function securityFingerprint(user: User, profile: AuthenticatedProfile): string {
  return JSON.stringify([
    oidcSessionFingerprint(user),
    [...profile.roles].sort(),
    profile.authentication_assurance,
    profile.authentication_time ?? '',
    profile.default_workspace_id ?? '',
    profile.workspace_selection_enabled !== false,
    profile.hardware_webauthn_enabled !== false,
    profile.password_change_supported !== false,
  ])
}

function createManager(): UserManager {
  const config = publicRuntimeConfig()
  const authority = config.oidcAuthority
  const clientId = config.oidcClientId
  if (!authority || !clientId) throw new Error('인증 공개 설정이 누락되었습니다.')
  const configuredRedirectUri = config.oidcRedirectUri
  const configuredOrigin = new URL(configuredRedirectUri).origin
  // Keycloak has an exact browser-origin redirect allowlist. Keep that origin,
  // but bind the redirect path/query to the safe current return path so a
  // top-level prompt=none SSO round-trip does not drop the workspace selector.
  const redirectUri = new URL(callbackReturnTo(), configuredOrigin).toString()
  return new UserManager({
    authority,
    client_id: clientId,
    redirect_uri: redirectUri,
    silent_redirect_uri: new URL('/oidc-silent-callback.html', configuredOrigin).toString(),
    post_logout_redirect_uri: window.location.origin,
    response_type: 'code',
    scope: 'openid profile email',
    // Access/refresh tokens and the selected user must not survive in browser
    // storage. The only persisted browser value is the short-lived PKCE
    // transaction required to validate the redirect. Keep it scoped to this
    // tab: oidc-client-ts otherwise defaults this state to a persistent browser store.
    userStore: new WebStorageStateStore({ store: new InMemoryWebStorage() }),
    stateStore: new WebStorageStateStore({
      store: window.sessionStorage,
      prefix: 'datariver.oidc.transaction.',
    }),
    // Renewal is coordinated by AuthProvider so an expiring-token event and a
    // concurrent API 401 share one in-memory renewal promise.
    automaticSilentRenew: false,
    monitorSession: true,
  })
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const manager = useMemo(() => createManager(), [])
  const [user, setUser] = useState<User>()
  const [profile, setProfile] = useState<AuthenticatedProfile>()
  const [securityEpoch, setSecurityEpoch] = useState(0)
  const [authorizationRevision, setAuthorizationRevision] = useState(0)
  const [loading, setLoading] = useState(true)
  const [notice, setNotice] = useState<AuthNotice>()
  const mounted = useRef(false)
  const callbackInProgress = useRef(false)
  const ssoProbeStarted = useRef(false)
  const renewalInProgress = useRef<Promise<string | undefined> | undefined>(undefined)
  const renewalAuthenticationGeneration = useRef<number | undefined>(undefined)
  const renewalLoadedUser = useRef<User | undefined>(undefined)
  const hydrationGeneration = useRef(0)
  const hydrationController = useRef<AbortController | undefined>(undefined)
  const securityEpochRef = useRef(0)
  const authenticationGenerationRef = useRef(0)
  const acceptedOidcSession = useRef<string | undefined>(undefined)
  const acceptedFingerprint = useRef<string | undefined>(undefined)
  const acceptedProfile = useRef<AuthenticatedProfile | undefined>(undefined)

  const advanceSecurityEpoch = useCallback(() => {
    securityEpochRef.current += 1
    if (mounted.current) setSecurityEpoch(securityEpochRef.current)
  }, [])

  const invalidateHydration = useCallback(() => {
    hydrationGeneration.current += 1
    hydrationController.current?.abort()
    hydrationController.current = undefined
  }, [])

  const clearAuthenticatedMemory = useCallback(() => {
    authenticationGenerationRef.current += 1
    invalidateHydration()
    acceptedOidcSession.current = undefined
    acceptedFingerprint.current = undefined
    acceptedProfile.current = undefined
    advanceSecurityEpoch()
    if (mounted.current) {
      setUser(undefined)
      setProfile(undefined)
    }
  }, [advanceSecurityEpoch, invalidateHydration])

  const hydrate = useCallback(async (
    next: User,
    expectedSubject?: string,
  ): Promise<HydrationResult> => {
    const subject = oidcSubject(next)
    if (!next.access_token || next.expired || !subject) return 'UNUSABLE'
    if (expectedSubject && subject !== expectedSubject) {
      throw new Error('OIDC 갱신 주체가 현재 인증 주체와 일치하지 않습니다.')
    }
    hydrationController.current?.abort()
    const controller = new AbortController()
    const generation = hydrationGeneration.current + 1
    hydrationGeneration.current = generation
    hydrationController.current = controller
    try {
      const response = await fetch(`${publicRuntimeConfig().apiBaseUrl}/auth/me`, {
        cache: 'no-store',
        signal: controller.signal,
        headers: { Authorization: `Bearer ${next.access_token}`, Accept: 'application/json' },
      })
      if (!response.ok) throw new Error('서버가 현재 인증 세션을 확인하지 못했습니다.')
      const value = await response.json() as AuthenticatedProfile
      if (value.subject !== subject || (expectedSubject && value.subject !== expectedSubject)) {
        throw new Error('서버 인증 프로필의 주체가 OIDC 주체와 일치하지 않습니다.')
      }
      if (!mounted.current || hydrationGeneration.current !== generation) return 'STALE'
      const fingerprint = securityFingerprint(next, value)
      if (
        acceptedFingerprint.current !== undefined
        && acceptedFingerprint.current !== fingerprint
      ) {
        advanceSecurityEpoch()
      }
      acceptedOidcSession.current = oidcSessionFingerprint(next)
      acceptedFingerprint.current = fingerprint
      acceptedProfile.current = value
      setUser(next)
      setProfile(value)
      setAuthorizationRevision((current) => current + 1)
      return 'APPLIED'
    } catch (error) {
      if (!mounted.current || hydrationGeneration.current !== generation) return 'STALE'
      throw error
    } finally {
      if (hydrationGeneration.current === generation) hydrationController.current = undefined
    }
  }, [advanceSecurityEpoch])

  const acceptExternalUser = useCallback(async (next: User) => {
    clearAuthenticatedMemory()
    try {
      const result = await hydrate(next)
      if (result === 'UNUSABLE') throw new Error('인증 이벤트에 사용할 access token이 없습니다.')
    } catch {
      if (mounted.current) {
        setNotice({ kind: 'ERROR', message: '인증 응답을 검증하지 못했습니다. 다시 로그인하세요.' })
      }
    }
  }, [clearAuthenticatedMemory, hydrate])

  const renewAccessToken = useCallback((): Promise<string | undefined> => {
    if (renewalInProgress.current) return renewalInProgress.current
    const startedEpoch = securityEpochRef.current
    const startedSubject = acceptedProfile.current?.subject
    const startedAuthenticationGeneration = authenticationGenerationRef.current
    if (!startedSubject) {
      clearAuthenticatedMemory()
      if (mounted.current) {
        setNotice({
          kind: 'INFO',
          message: '검증된 인증 프로필이 없어 세션을 갱신하지 않았습니다. 다시 로그인하세요.',
        })
      }
      return Promise.resolve(undefined)
    }
    renewalAuthenticationGeneration.current = startedAuthenticationGeneration
    renewalLoadedUser.current = undefined
    const renewal = (async () => {
      try {
        const next = await manager.signinSilent()
        const queued = renewalLoadedUser.current
        renewalLoadedUser.current = undefined
        if (queued && queued.access_token !== next?.access_token) {
          await acceptExternalUser(queued)
          return undefined
        }
        if (
          securityEpochRef.current !== startedEpoch
          || acceptedProfile.current?.subject !== startedSubject
        ) {
          return undefined
        }
        if (
          !next
          || !next.access_token
          || next.expired
          || await hydrate(next, startedSubject) !== 'APPLIED'
        ) {
          throw new Error('인증 갱신 응답에 사용할 access token이 없습니다.')
        }
        return next.access_token
      } catch {
        const queued = renewalLoadedUser.current
        renewalLoadedUser.current = undefined
        if (queued) {
          await acceptExternalUser(queued)
          return undefined
        }
        if (
          securityEpochRef.current === startedEpoch
          && acceptedProfile.current?.subject === startedSubject
        ) {
          clearAuthenticatedMemory()
          if (!mounted.current) return undefined
          setNotice({
            kind: 'INFO',
            message: '인증 세션을 갱신하지 못했습니다. 계속하려면 Sign In을 선택하세요.',
          })
        }
        return undefined
      } finally {
        renewalAuthenticationGeneration.current = undefined
        renewalInProgress.current = undefined
      }
    })()
    renewalInProgress.current = renewal
    return renewal
  }, [acceptExternalUser, clearAuthenticatedMemory, hydrate, manager])

  useEffect(() => {
    mounted.current = true
    const initialize = async () => {
      const initializationEpoch = securityEpochRef.current
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
        if (securityEpochRef.current !== initializationEpoch) return
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
          if (mounted.current && state.intent === 'PASSWORD_CHANGE') {
            setNotice({
              kind: actionStatus === 'cancelled' ? 'ERROR' : 'INFO',
              message: actionStatus === 'success'
                ? '비밀번호가 변경되었습니다.'
                : actionStatus === 'cancelled'
                  ? '비밀번호 변경이 취소되었습니다.'
                  : '비밀번호 변경 절차가 종료되었지만 완료 여부를 확인하지 못했습니다.',
            })
          }
        }
        if (next && !next.expired) {
          const result = await hydrate(next)
          if (result === 'APPLIED' || result === 'STALE') return
        }
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
        if (securityEpochRef.current !== initializationEpoch) return
        if (mounted.current) {
          clearAuthenticatedMemory()
          setNotice({ kind: 'ERROR', message: '인증 응답을 검증하지 못했습니다. 다시 로그인하세요.' })
          window.history.replaceState({}, document.title, callbackReturnTo())
        }
      } finally {
        callbackInProgress.current = false
        if (mounted.current) setLoading(false)
      }
    }
    const loaded = (next: User) => {
      if (callbackInProgress.current) return
      if (renewalInProgress.current) {
        if (
          renewalAuthenticationGeneration.current
          !== authenticationGenerationRef.current
        ) {
          return
        }
        if (
          acceptedOidcSession.current !== undefined
          && oidcSessionFingerprint(next) === acceptedOidcSession.current
        ) {
          renewalLoadedUser.current = next
          return
        }
        void acceptExternalUser(next)
        return
      }
      void acceptExternalUser(next)
    }
    const unloaded = () => {
      renewalLoadedUser.current = undefined
      clearAuthenticatedMemory()
    }
    const expiring = () => { void renewAccessToken() }
    manager.events.addUserLoaded(loaded)
    manager.events.addUserUnloaded(unloaded)
    manager.events.addAccessTokenExpiring(expiring)
    void initialize()
    return () => {
      mounted.current = false
      invalidateHydration()
      manager.events.removeUserLoaded(loaded)
      manager.events.removeUserUnloaded(unloaded)
      manager.events.removeAccessTokenExpiring(expiring)
    }
  }, [
    acceptExternalUser,
    clearAuthenticatedMemory,
    hydrate,
    invalidateHydration,
    manager,
    renewAccessToken,
  ])

  const beginRedirect = useCallback(async (intent: AuthIntent) => {
    if (
      (intent === 'STEP_UP' || intent === 'WEBAUTHN_ENROLLMENT')
      && profile?.hardware_webauthn_enabled === false
    ) {
      setNotice({
        kind: 'ERROR',
        message: '이 환경에서는 WebAuthn이 비활성화되어 있습니다. WebAuthn 보증이 필요한 고위험 작업은 실행할 수 없습니다.',
      })
      return
    }
    // An explicit user action must visibly leave the custom login surface at
    // once.  The browser navigation is performed by oidc-client-ts; if it
    // rejects synchronously, restore the same custom surface with guidance.
    setLoading(true)
    setNotice(undefined)
    try {
      const config = publicRuntimeConfig()
      const highAssuranceAcr = config.oidcHighAssuranceAcr
      const passwordReauthAcr = config.oidcPasswordReauthAcr
      await manager.signinRedirect(signinRedirectArgs(intent, {
        highAssuranceAcr,
        passwordReauthAcr,
      }))
    } catch (error) {
      if (mounted.current) setLoading(false)
      setNotice({
        kind: 'ERROR',
        message: error instanceof Error ? error.message : '인증 요청을 시작하지 못했습니다.',
      })
    }
  }, [manager, profile?.hardware_webauthn_enabled])

  const signOut = useCallback(async () => {
    renewalLoadedUser.current = undefined
    clearAuthenticatedMemory()
    await manager.signoutRedirect()
  }, [clearAuthenticatedMemory, manager])

  const readSecurityEpoch = useCallback(() => securityEpochRef.current, [])

  const value = useMemo<AuthValue>(() => ({
    user,
    profile,
    securityEpoch,
    authorizationRevision,
    readSecurityEpoch,
    renewAccessToken,
    loading,
    notice,
    signIn: () => beginRedirect('SIGN_IN'),
    signOut,
    beginWebAuthnEnrollment: () => beginRedirect('WEBAUTHN_ENROLLMENT'),
    beginStepUp: () => beginRedirect('STEP_UP'),
    beginPasswordReauth: () => beginRedirect('PASSWORD_REAUTH'),
    beginPasswordChange: () => beginRedirect('PASSWORD_CHANGE'),
    clearNotice: () => setNotice(undefined),
  }), [
    authorizationRevision,
    beginRedirect,
    loading,
    notice,
    profile,
    readSecurityEpoch,
    renewAccessToken,
    securityEpoch,
    signOut,
    user,
  ])

  return <AuthContext value={value}>{children}</AuthContext>
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('AuthProvider가 필요합니다.')
  return value
}
