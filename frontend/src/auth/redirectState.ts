import type { SigninRedirectArgs } from 'oidc-client-ts'

export const AUTH_REDIRECT_STATE_VERSION = 1 as const

export type AuthIntent = 'SIGN_IN' | 'WEBAUTHN_ENROLLMENT' | 'STEP_UP' | 'PASSWORD_REAUTH'

export interface AuthRedirectState {
  version: typeof AUTH_REDIRECT_STATE_VERSION
  intent: AuthIntent
  returnTo: string
}

const intents = new Set<AuthIntent>([
  'SIGN_IN',
  'WEBAUTHN_ENROLLMENT',
  'STEP_UP',
  'PASSWORD_REAUTH',
])

export function safeReturnTo(value: unknown, origin = window.location.origin): string {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')) return '/'
  if (value.includes('\\')) return '/'
  try {
    const base = new URL(origin)
    const candidate = new URL(value, base)
    if (candidate.origin !== base.origin) return '/'
    return `${candidate.pathname}${candidate.search}${candidate.hash}`
  } catch {
    return '/'
  }
}

export function currentReturnTo(): string {
  return safeReturnTo(`${window.location.pathname}${window.location.search}${window.location.hash}`)
}

/**
 * Removes protocol response parameters while retaining the already-safe local
 * navigation state. This lets a top-level SSO redirect return to the selected
 * workspace and page without treating that selection as an authorization fact.
 */
export function callbackReturnTo(href = window.location.href): string {
  const url = new URL(href, window.location.origin)
  for (const parameter of [
    'code',
    'state',
    'session_state',
    'iss',
    'error',
    'error_description',
    'error_uri',
    'kc_action_status',
  ]) {
    url.searchParams.delete(parameter)
  }
  return safeReturnTo(`${url.pathname}${url.search}${url.hash}`)
}

export function redirectState(intent: AuthIntent, returnTo = currentReturnTo()): AuthRedirectState {
  return { version: AUTH_REDIRECT_STATE_VERSION, intent, returnTo: safeReturnTo(returnTo) }
}

export function readRedirectState(value: unknown): AuthRedirectState {
  if (!value || typeof value !== 'object') return redirectState('SIGN_IN', '/')
  const candidate = value as Partial<AuthRedirectState>
  if (candidate.version !== AUTH_REDIRECT_STATE_VERSION || !candidate.intent || !intents.has(candidate.intent)) {
    return redirectState('SIGN_IN', '/')
  }
  return redirectState(candidate.intent, candidate.returnTo)
}

export function signinRedirectArgs(
  intent: AuthIntent,
  options: {
    returnTo?: string
    highAssuranceAcr?: string
    passwordReauthAcr?: string
  } = {},
): SigninRedirectArgs {
  const state = redirectState(intent, options.returnTo)
  if (intent === 'STEP_UP') {
    const acr = requiredAcr(options.highAssuranceAcr, '고위험 인증')
    return { state, acr_values: acr, max_age: 0 }
  }
  if (intent === 'PASSWORD_REAUTH') {
    const acr = requiredAcr(options.passwordReauthAcr, '비밀번호 재인증')
    return { state, acr_values: acr, max_age: 0 }
  }
  if (intent === 'WEBAUTHN_ENROLLMENT') {
    return {
      state,
      max_age: 0,
      extraQueryParams: { kc_action: 'webauthn-register:skip_if_exists' },
    }
  }
  return { state }
}

function requiredAcr(value: string | undefined, label: string): string {
  const acr = value?.trim()
  if (!acr || /\s/.test(acr)) throw new Error(`${label} ACR이 안전하게 설정되지 않았습니다.`)
  return acr
}
