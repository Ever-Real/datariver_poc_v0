import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useStableApiClient } from './useStableApiClient'

afterEach(() => vi.unstubAllGlobals())

describe('useStableApiClient', () => {
  it('keeps feature client identity stable while requests use renewed credentials', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ state: 'ready' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)
    const firstRenew = vi.fn().mockResolvedValue('first-renewed-token')
    const secondRenew = vi.fn().mockResolvedValue('second-renewed-token')
    const hook = renderHook(
      ({ token, workspace, renew, readSecurityEpoch }) => useStableApiClient(
        '/api/v1',
        token,
        workspace,
        renew,
        readSecurityEpoch,
      ),
      {
        initialProps: {
          token: 'token-one',
          workspace: 'workspace-one',
          renew: firstRenew,
          readSecurityEpoch: () => 1,
        },
      },
    )
    const originalClient = hook.result.current

    hook.rerender({
      token: 'token-two',
      workspace: 'workspace-two',
      renew: secondRenew,
      readSecurityEpoch: () => 2,
    })

    expect(hook.result.current).toBe(originalClient)
    await act(async () => {
      await hook.result.current.request('/capabilities')
    })
    const request = fetchMock.mock.calls[0]
    const headers = new Headers((request?.[1] as RequestInit | undefined)?.headers)
    expect(headers.get('Authorization')).toBe('Bearer token-two')
    expect(headers.get('X-Workspace-Id')).toBe('workspace-two')
    expect(firstRenew).not.toHaveBeenCalled()
    expect(secondRenew).not.toHaveBeenCalled()
  })
})
