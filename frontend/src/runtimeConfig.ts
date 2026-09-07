export interface BrowserRuntimeConfig {
  apiBaseUrl: string
  oidcAuthority: string
  oidcClientId: string
  oidcRedirectUri: string
  oidcHighAssuranceAcr: string
  oidcPasswordReauthAcr: string
}

declare global {
  interface Window {
    __DATARIVER_CONFIG__?: Partial<BrowserRuntimeConfig>
  }
}

function selected(runtimeValue: string | undefined, buildValue: string | undefined, fallback = ''): string {
  return runtimeValue?.trim() || buildValue?.trim() || fallback
}

function buildSetting(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined
}

export function publicRuntimeConfig(): BrowserRuntimeConfig {
  const runtime = window.__DATARIVER_CONFIG__ ?? {}
  return {
    apiBaseUrl: selected(runtime.apiBaseUrl, buildSetting(import.meta.env.VITE_API_BASE_URL), '/api/v1'),
    oidcAuthority: selected(runtime.oidcAuthority, buildSetting(import.meta.env.VITE_OIDC_AUTHORITY)),
    oidcClientId: selected(runtime.oidcClientId, buildSetting(import.meta.env.VITE_OIDC_CLIENT_ID)),
    oidcRedirectUri: selected(runtime.oidcRedirectUri, buildSetting(import.meta.env.VITE_OIDC_REDIRECT_URI), window.location.origin),
    oidcHighAssuranceAcr: selected(runtime.oidcHighAssuranceAcr, buildSetting(import.meta.env.VITE_OIDC_HIGH_ASSURANCE_ACR)),
    oidcPasswordReauthAcr: selected(runtime.oidcPasswordReauthAcr, buildSetting(import.meta.env.VITE_OIDC_PASSWORD_REAUTH_ACR)),
  }
}
