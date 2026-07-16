import { describe, expect, it } from 'vitest'
import { readRedirectState, redirectState, safeReturnTo, signinRedirectArgs } from './redirectState'

describe('OIDC redirect state', () => {
  it('preserves only same-origin relative return paths', () => {
    expect(safeReturnTo('/?page=governance#request', 'https://catalog.example')).toBe(
      '/?page=governance#request',
    )
    expect(safeReturnTo('//evil.example/path', 'https://catalog.example')).toBe('/')
    expect(safeReturnTo('https://evil.example/path', 'https://catalog.example')).toBe('/')
    expect(safeReturnTo('/\\evil.example/path', 'https://catalog.example')).toBe('/')
  })

  it('round-trips only versioned authentication intent and safe navigation state', () => {
    expect(readRedirectState(redirectState('STEP_UP', '/?page=sharing'))).toEqual({
      version: 1,
      intent: 'STEP_UP',
      returnTo: '/?page=sharing',
    })
    expect(readRedirectState({ version: 99, intent: 'STEP_UP', returnTo: '//evil.example' })).toEqual(
      { version: 1, intent: 'SIGN_IN', returnTo: '/' },
    )
  })

  it('builds explicit WebAuthn enrollment and fresh step-up requests', () => {
    expect(signinRedirectArgs('WEBAUTHN_ENROLLMENT', { returnTo: '/?page=dashboard' })).toMatchObject({
      max_age: 0,
      extraQueryParams: { kc_action: 'webauthn-register:skip_if_exists' },
      state: { version: 1, intent: 'WEBAUTHN_ENROLLMENT', returnTo: '/?page=dashboard' },
    })
    expect(
      signinRedirectArgs('STEP_UP', {
        returnTo: '/?page=governance',
        highAssuranceAcr: '2',
      }),
    ).toMatchObject({
      acr_values: '2',
      max_age: 0,
      state: { version: 1, intent: 'STEP_UP', returnTo: '/?page=governance' },
    })
  })

  it('fails closed when step-up ACR is missing or ambiguous', () => {
    expect(() => signinRedirectArgs('STEP_UP')).toThrow('ACR')
    expect(() => signinRedirectArgs('STEP_UP', { highAssuranceAcr: '2 gold' })).toThrow('ACR')
  })
})
