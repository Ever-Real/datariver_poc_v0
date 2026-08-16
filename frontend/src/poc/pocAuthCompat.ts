import { useCallback, useEffect, useRef, useState } from 'react'
import type { AuthenticatedProfile } from '../api/types'

const genericLoginFailure = '로그인할 수 없습니다. 아이디와 비밀번호를 확인하세요.'
const genericSessionFailure = '인증 상태를 확인하지 못했습니다. 다시 시도하세요.'

type JsonRecord = Record<string, unknown>

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function readString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}

function readStringArray(value: unknown): string[] | undefined {
  if (!Array.isArray(value) || value.some((item) => !readString(item))) return undefined
  return value.map((item) => readString(item) as string)
}

function localProfile(value: unknown): AuthenticatedProfile {
  if (!isRecord(value)) throw new Error('Invalid local session response.')
  const subject = readString(value.subject)
  const displayName = readString(value.display_name)
  const roles = readStringArray(value.roles)
  const defaultWorkspaceId = readString(value.default_workspace_id)
  if (
    !subject
    || !displayName
    || !roles?.length
    || value.authentication_assurance !== 'PASSWORD'
    || !defaultWorkspaceId
    || value.workspace_selection_enabled !== false
    || value.hardware_webauthn_enabled !== false
    || value.password_change_supported !== false
  ) {
    throw new Error('Incomplete local session response.')
  }
  return {
    subject,
    display_name: displayName,
    email: readString(value.email),
    roles,
    authentication_assurance: value.authentication_assurance,
    default_workspace_id: defaultWorkspaceId,
    workspace_selection_enabled: value.workspace_selection_enabled,
    hardware_webauthn_enabled: value.hardware_webauthn_enabled,
    password_change_supported: value.password_change_supported,
  }
}

async function readProfile(response: Response): Promise<AuthenticatedProfile> {
  return localProfile(await response.json())
}

export function useAuth() {
  const [profile, setProfile] = useState<AuthenticatedProfile>()
  const [loading, setLoading] = useState(true)
  const [notice, setNotice] = useState<{ kind: 'ERROR'; message: string }>()
  const [securityEpoch, setSecurityEpoch] = useState(0)
  const [authorizationRevision, setAuthorizationRevision] = useState(0)
  const securityEpochRef = useRef(0)
  const mounted = useRef(true)

  const applyProfile = useCallback((next: AuthenticatedProfile) => {
    if (!mounted.current) return
    setProfile(next)
    setAuthorizationRevision((current) => current + 1)
  }, [])

  const clearSession = useCallback(() => {
    securityEpochRef.current += 1
    if (!mounted.current) return
    setProfile(undefined)
    setSecurityEpoch(securityEpochRef.current)
  }, [])

  const hydrate = useCallback(async (signal?: AbortSignal) => {
    const response = await fetch('/auth/me', {
      cache: 'no-store',
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
      signal,
    })
    if (response.status === 401 || response.status === 403) {
      clearSession()
      return false
    }
    if (!response.ok) throw new Error('Local session lookup failed.')
    applyProfile(await readProfile(response))
    return true
  }, [applyProfile, clearSession])

  useEffect(() => {
    mounted.current = true
    const controller = new AbortController()
    void hydrate(controller.signal)
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') return
        clearSession()
        if (mounted.current) setNotice({ kind: 'ERROR', message: genericSessionFailure })
      })
      .finally(() => {
        if (mounted.current && !controller.signal.aborted) setLoading(false)
      })
    return () => {
      mounted.current = false
      controller.abort()
    }
  }, [clearSession, hydrate])

  const signInWithCredentials = useCallback(async (username: string, password: string) => {
    setLoading(true)
    setNotice(undefined)
    try {
      const response = await fetch('/auth/login', {
        method: 'POST',
        cache: 'no-store',
        credentials: 'same-origin',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ username, password }),
      })
      if (!response.ok) throw new Error('Local login failed.')
      applyProfile(await readProfile(response))
    } catch {
      clearSession()
      if (mounted.current) setNotice({ kind: 'ERROR', message: genericLoginFailure })
    } finally {
      if (mounted.current) setLoading(false)
    }
  }, [applyProfile, clearSession])

  const signOut = useCallback(async () => {
    setLoading(true)
    setNotice(undefined)
    try {
      const response = await fetch('/auth/logout', {
        method: 'POST',
        cache: 'no-store',
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
      })
      if (!response.ok && response.status !== 401) throw new Error('Local logout failed.')
      clearSession()
    } catch {
      if (mounted.current) setNotice({ kind: 'ERROR', message: genericSessionFailure })
    } finally {
      if (mounted.current) setLoading(false)
    }
  }, [clearSession])

  const renewAccessToken = useCallback(async () => {
    try {
      await hydrate()
    } catch {
      clearSession()
    }
    return undefined
  }, [clearSession, hydrate])

  const noAuthenticationAction = useCallback(() => Promise.resolve(undefined), [])
  const readSecurityEpoch = useCallback(() => securityEpochRef.current, [])
  const clearNotice = useCallback(() => setNotice(undefined), [])
  const user = profile ? {
    profile: {
      sub: profile.subject,
      name: profile.display_name,
      email: profile.email,
    },
  } : undefined

  return {
    isLocalSession: true as const,
    user,
    profile,
    securityEpoch,
    authorizationRevision,
    readSecurityEpoch,
    loading,
    notice,
    renewAccessToken,
    signIn: noAuthenticationAction,
    signInWithCredentials,
    signOut,
    beginWebAuthnEnrollment: noAuthenticationAction,
    beginStepUp: noAuthenticationAction,
    beginPasswordReauth: noAuthenticationAction,
    beginPasswordChange: noAuthenticationAction,
    clearNotice,
  }
}
