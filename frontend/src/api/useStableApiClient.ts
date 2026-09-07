import { useLayoutEffect, useMemo, useState } from 'react'
import { ApiClient, type AccessTokenRenewer } from './client'

class LatestApiClientInputs {
  private accessToken: string | undefined
  private workspaceId: string
  private renewAccessToken: AccessTokenRenewer
  private securityEpoch: () => number

  constructor(
    accessToken: string | undefined,
    workspaceId: string,
    renewAccessToken: AccessTokenRenewer,
    securityEpoch: () => number,
  ) {
    this.accessToken = accessToken
    this.workspaceId = workspaceId
    this.renewAccessToken = renewAccessToken
    this.securityEpoch = securityEpoch
  }

  update(
    accessToken: string | undefined,
    workspaceId: string,
    renewAccessToken: AccessTokenRenewer,
    securityEpoch: () => number,
  ) {
    this.accessToken = accessToken
    this.workspaceId = workspaceId
    this.renewAccessToken = renewAccessToken
    this.securityEpoch = securityEpoch
  }

  readAccessToken = () => this.accessToken
  readWorkspaceId = () => this.workspaceId
  readSecurityEpoch = () => this.securityEpoch()
  renew = () => this.renewAccessToken()
}

/**
 * Keep one API client for the lifetime of the application while allowing its
 * request-time authentication and workspace inputs to change. Token renewal
 * must not recreate every feature client and trigger a full set of data-load
 * effects.
 */
export function useStableApiClient(
  baseUrl: string,
  accessToken: string | undefined,
  workspaceId: string,
  renewAccessToken: AccessTokenRenewer,
  securityEpoch: () => number,
): ApiClient {
  const [inputs] = useState(() => new LatestApiClientInputs(
    accessToken,
    workspaceId,
    renewAccessToken,
    securityEpoch,
  ))

  useLayoutEffect(() => {
    inputs.update(accessToken, workspaceId, renewAccessToken, securityEpoch)
  }, [accessToken, inputs, renewAccessToken, securityEpoch, workspaceId])

  return useMemo(() => new ApiClient(
    baseUrl,
    inputs.readAccessToken,
    inputs.readWorkspaceId,
    inputs.renew,
    inputs.readSecurityEpoch,
  ), [baseUrl, inputs])
}
