/* global AbortSignal */
// Dependencies are supplied by bootstrap; this module never constructs a shared client.
export function createInfrastructureProvider(deps) {
async function providerFetch(url, options = {}) {
  const { timeoutMs = deps.providerTimeoutMs, ...fetchOptions } = options
  const timeoutSignal = AbortSignal.timeout(timeoutMs)
  return deps.providerTransport.fetch(url, {
    ...fetchOptions,
    redirect: 'error',
    signal: fetchOptions.signal
      ? AbortSignal.any([fetchOptions.signal, timeoutSignal])
      : timeoutSignal,
  })
}

async function requireOk(response, label) {
  if (!response.ok) throw new Error(`${label} returned HTTP ${response.status}.`)
  return response
}

return { providerFetch, requireOk }
}
