import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useAuth } from './pocAuthCompat'

const profile = {
  subject: 'operator-1',
  display_name: 'Local Operator',
  email: 'operator@local',
  roles: ['data_steward'],
  authentication_assurance: 'PASSWORD',
  default_workspace_id: '00000000-0000-4000-8000-000000000061',
  workspace_selection_enabled: false,
  hardware_webauthn_enabled: false,
  password_change_supported: true,
  must_change_password: false,
  authorization: {
    policy_version: 'POC_PROFILE_CAPABILITIES_V1',
    role: 'data_steward',
    capabilities: [
      'catalog.read', 'catalog.execute', 'catalog.manage', 'chat.query', 'change.read',
      'change.execute', 'change.manage',
      'quality.read', 'quality.execute', 'quality.manage', 'knowledge.read',
      'monitoring.read',
    ],
    system_scope: 'ASSIGNED',
    system_ids: ['system-one'],
  },
}

function jsonResponse(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function requestPath(input: RequestInfo | URL) {
  return input instanceof Request ? new URL(input.url).pathname : new URL(String(input), window.location.origin).pathname
}

describe('POC local-session authentication adapter', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it.each([401, 403])('shows the anonymous state when hard-reload hydration returns %s', async (status) => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}, status))
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useAuth())

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.user).toBeUndefined()
    expect(result.current.profile).toBeUndefined()
    expect(result.current.notice).toBeUndefined()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/auth/me')
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({
      cache: 'no-store',
      credentials: 'same-origin',
    })
  })

  it('hydrates a hard-reloaded browser from the server-held session profile', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(profile))
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useAuth())

    await waitFor(() => expect(result.current.profile?.subject).toBe(profile.subject))
    expect(result.current.user?.profile).toEqual({
      sub: profile.subject,
      name: profile.display_name,
      email: profile.email,
    })
    expect(result.current.user).not.toHaveProperty('access_token')
    expect(result.current.profile).toEqual(profile)
  })

  it('advances the security epoch when hydration changes the server-held subject', async () => {
    const nextProfile = {
      ...profile,
      subject: 'operator-2',
      display_name: 'Second Operator',
      authorization: {
        ...profile.authorization,
        role: 'manager' as const,
        capabilities: [
          ...profile.authorization.capabilities,
          'knowledge.manage' as const,
          'knowledge.review' as const,
        ],
      },
    }
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(profile))
      .mockResolvedValueOnce(jsonResponse(nextProfile))
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useAuth())
    await waitFor(() => expect(result.current.profile?.subject).toBe('operator-1'))

    await act(() => result.current.renewAccessToken())

    expect(result.current.profile?.subject).toBe('operator-2')
    expect(result.current.securityEpoch).toBe(1)
  })

  it('fails closed when the server profile contains an unknown capability', async () => {
    const invalid = {
      ...profile,
      authorization: {
        ...profile.authorization,
        capabilities: [...profile.authorization.capabilities, 'admin.from-local-storage'],
      },
    }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(invalid)))

    const { result } = renderHook(() => useAuth())

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.profile).toBeUndefined()
    expect(result.current.notice?.kind).toBe('ERROR')
  })

  it('logs in with same-origin credentials and sends no client authority or Authorization claims', async () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem')
    const fetchMock = vi.fn((input: RequestInfo | URL, _options?: RequestInit) => {
      void _options
      return Promise.resolve(
        requestPath(input) === '/auth/me' ? jsonResponse({}, 401) : jsonResponse(profile),
      )
    })
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useAuth())
    await waitFor(() => expect(result.current.loading).toBe(false))

    await act(() => result.current.signInWithCredentials('operator', 'correct horse'))

    expect(result.current.profile).toEqual(profile)
    expect(setItem).not.toHaveBeenCalled()
    const loginCall = fetchMock.mock.calls.find(([input]) => requestPath(input) === '/auth/login')
    expect(loginCall).toBeDefined()
    const options = loginCall?.[1] as RequestInit
    expect(options).toMatchObject({
      method: 'POST',
      cache: 'no-store',
      credentials: 'same-origin',
      body: JSON.stringify({ username: 'operator', password: 'correct horse' }),
    })
    const headers = new Headers(options.headers)
    expect(headers.get('Authorization')).toBeNull()
    expect(headers.get('X-Subject-Id')).toBeNull()
    expect(headers.get('X-Role')).toBeNull()
    expect(headers.get('X-System-Id')).toBeNull()
    expect(typeof options.body).toBe('string')
    expect(Object.keys(JSON.parse(options.body as string) as object).sort()).toEqual([
      'password', 'username',
    ])
  })

  it.each([401, 403])('uses the same generic login error for a %s response', async (status) => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => Promise.resolve(
      requestPath(input) === '/auth/me'
        ? jsonResponse({}, 401)
        : jsonResponse({ detail: status === 401 ? 'unknown username' : 'inactive account' }, status),
    ))
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useAuth())
    await waitFor(() => expect(result.current.loading).toBe(false))

    await act(() => result.current.signInWithCredentials('operator', 'wrong'))

    expect(result.current.user).toBeUndefined()
    expect(result.current.notice).toEqual({
      kind: 'ERROR',
      message: '로그인할 수 없습니다. 아이디와 비밀번호를 확인하세요.',
    })
  })

  it('distinguishes an exact Origin rejection from a credential failure', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => Promise.resolve(
      requestPath(input) === '/auth/me'
        ? jsonResponse({}, 401)
        : jsonResponse({ code: 'ORIGIN_FORBIDDEN' }, 403),
    ))
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useAuth())
    await waitFor(() => expect(result.current.loading).toBe(false))

    await act(() => result.current.signInWithCredentials('operator', 'correct horse'))

    expect(result.current.user).toBeUndefined()
    expect(result.current.notice).toEqual({
      kind: 'ERROR',
      message: '접속 주소가 허용된 DEV 주소와 다릅니다. 안내된 127.0.0.1 주소로 다시 접속하세요.',
    })
  })

  it('logs out through the server and clears only in-memory session state', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, _options?: RequestInit) => {
      void _options
      return Promise.resolve(
        requestPath(input) === '/auth/logout'
          ? jsonResponse({ ok: true })
          : jsonResponse(profile),
      )
    })
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useAuth())
    await waitFor(() => expect(result.current.user).toBeDefined())

    await act(() => result.current.signOut())

    expect(result.current.user).toBeUndefined()
    const logoutCall = fetchMock.mock.calls.find(([input]) => requestPath(input) === '/auth/logout')
    expect(logoutCall?.[1]).toMatchObject({
      method: 'POST',
      cache: 'no-store',
      credentials: 'same-origin',
    })
    expect(new Headers((logoutCall?.[1] as RequestInit).headers).get('Authorization')).toBeNull()
  })

  it('changes a local password with same-origin credentials and requires a fresh login', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, _options?: RequestInit) => {
      void _options
      return Promise.resolve(
        requestPath(input) === '/auth/password'
          ? jsonResponse({ ok: true, reauthentication_required: true })
          : jsonResponse(profile),
      )
    })
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useAuth())
    await waitFor(() => expect(result.current.user).toBeDefined())

    await act(() => result.current.changeLocalPassword({
      currentPassword: 'current password value',
      newPassword: 'new password value',
      confirmation: 'new password value',
    }))

    expect(result.current.user).toBeUndefined()
    expect(result.current.notice).toEqual({
      kind: 'INFO',
      message: '비밀번호가 변경되었습니다. 새 비밀번호로 다시 로그인하세요.',
    })
    const changeCall = fetchMock.mock.calls.find(([input]) => requestPath(input) === '/auth/password')
    expect(changeCall?.[1]).toMatchObject({
      method: 'POST', cache: 'no-store', credentials: 'same-origin',
      body: JSON.stringify({
        current_password: 'current password value',
        new_password: 'new password value',
        new_password_confirmation: 'new password value',
      }),
    })
    expect(new Headers((changeCall?.[1] as RequestInit).headers).get('Authorization')).toBeNull()
  })
})
