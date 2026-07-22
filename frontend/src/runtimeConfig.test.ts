import { afterEach, describe, expect, it, vi } from 'vitest'
import { publicRuntimeConfig } from './runtimeConfig'

describe('public runtime configuration', () => {
  afterEach(() => {
    delete window.__DATARIVER_CONFIG__
    vi.unstubAllEnvs()
  })

  it('lets one built artifact use a deployment-specific runtime OIDC origin', () => {
    vi.stubEnv('VITE_OIDC_AUTHORITY', 'https://build-host.invalid/realms/datariver')
    window.__DATARIVER_CONFIG__ = {
      apiBaseUrl: '/api/v1',
      oidcAuthority: 'https://identity.wsl.example.test/realms/datariver',
      oidcClientId: 'datariver-web',
      oidcRedirectUri: 'https://catalog.wsl.example.test',
      oidcHighAssuranceAcr: 'hardware',
      oidcPasswordReauthAcr: 'password',
    }

    expect(publicRuntimeConfig()).toEqual({
      apiBaseUrl: '/api/v1',
      oidcAuthority: 'https://identity.wsl.example.test/realms/datariver',
      oidcClientId: 'datariver-web',
      oidcRedirectUri: 'https://catalog.wsl.example.test',
      oidcHighAssuranceAcr: 'hardware',
      oidcPasswordReauthAcr: 'password',
    })
  })
})
