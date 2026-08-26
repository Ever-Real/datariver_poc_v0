export const minimumLlmProviderTimeoutMs = 1_000
export const maximumLlmProviderTimeoutMs = 300_000
export const defaultLlmProviderTimeoutMs = 120_000

export const llmProviderFailureCodes = Object.freeze({
  AUTH: 'POC_LLM_PROVIDER_AUTH_FAILED',
  CONNECTIVITY: 'POC_LLM_PROVIDER_CONNECTIVITY_FAILED',
  CONTRACT: 'POC_LLM_PROVIDER_CONTRACT_FAILED',
  HTTP: 'POC_LLM_PROVIDER_HTTP_FAILED',
  TIMEOUT: 'POC_LLM_PROVIDER_TIMEOUT',
})

export const prepGeneralSmokeClassificationByProductCode = Object.freeze({
  [llmProviderFailureCodes.AUTH]: 'PREP_SMOKE_GENERAL_PROVIDER_AUTH_FAILED',
  [llmProviderFailureCodes.CONNECTIVITY]: 'PREP_SMOKE_GENERAL_PROVIDER_CONNECTIVITY_FAILED',
  [llmProviderFailureCodes.CONTRACT]: 'PREP_SMOKE_GENERAL_PROVIDER_CONTRACT_FAILED',
  [llmProviderFailureCodes.HTTP]: 'PREP_SMOKE_GENERAL_PROVIDER_HTTP_FAILED',
  [llmProviderFailureCodes.TIMEOUT]: 'PREP_SMOKE_GENERAL_PROVIDER_TIMEOUT_FAILED',
})

export function parseLlmProviderTimeoutMs(value) {
  const raw = value === undefined || value === null || String(value).trim() === ''
    ? String(defaultLlmProviderTimeoutMs)
    : String(value).trim()
  if (!/^\d+$/.test(raw)) {
    throw new Error(`POC_LLM_TIMEOUT_MS must be an integer from ${minimumLlmProviderTimeoutMs} through ${maximumLlmProviderTimeoutMs}.`)
  }
  const timeoutMs = Number(raw)
  if (!Number.isSafeInteger(timeoutMs)
    || timeoutMs < minimumLlmProviderTimeoutMs
    || timeoutMs > maximumLlmProviderTimeoutMs) {
    throw new Error(`POC_LLM_TIMEOUT_MS must be an integer from ${minimumLlmProviderTimeoutMs} through ${maximumLlmProviderTimeoutMs}.`)
  }
  return timeoutMs
}

export function prepGeneralSmokeClassification(productCode) {
  return typeof productCode === 'string'
    ? prepGeneralSmokeClassificationByProductCode[productCode]
    : undefined
}
