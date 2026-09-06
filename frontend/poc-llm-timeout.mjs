export const minimumLlmProviderTimeoutMs = 1_000
export const maximumLlmProviderTimeoutMs = 300_000
export const defaultLlmProviderTimeoutMs = 120_000
export const routingClassifierCompletionTokenBudget = 1_024

export const llmProviderFailureCodes = Object.freeze({
  AUTH: 'POC_LLM_PROVIDER_AUTH_FAILED',
  CONNECTIVITY: 'POC_LLM_PROVIDER_CONNECTIVITY_FAILED',
  CONTRACT: 'POC_LLM_PROVIDER_CONTRACT_FAILED',
  HTTP: 'POC_LLM_PROVIDER_HTTP_FAILED',
  TIMEOUT: 'POC_LLM_PROVIDER_TIMEOUT',
})

export const llmProviderFailureStages = Object.freeze({
  ROUTING_CLASSIFIER: 'ROUTING_CLASSIFIER',
  GENERAL_COMPOSER: 'GENERAL_COMPOSER',
  EVIDENCE_COMPOSER: 'EVIDENCE_COMPOSER',
})

const llmProviderFailureClassByCode = Object.freeze({
  [llmProviderFailureCodes.AUTH]: 'AUTH',
  [llmProviderFailureCodes.CONNECTIVITY]: 'CONNECTIVITY',
  [llmProviderFailureCodes.CONTRACT]: 'CONTRACT',
  [llmProviderFailureCodes.HTTP]: 'HTTP',
  [llmProviderFailureCodes.TIMEOUT]: 'TIMEOUT',
})
const llmProviderFailureStageSet = new Set(Object.values(llmProviderFailureStages))
const llmProviderHttpClasses = new Set(['HTTP_4XX', 'HTTP_5XX', 'HTTP_OTHER'])

export function boundedLlmProviderFailureCode(value) {
  return Object.hasOwn(llmProviderFailureClassByCode, value)
    ? value
    : llmProviderFailureCodes.CONTRACT
}

function boundedProviderHttpClass(status) {
  if (!Number.isInteger(status) || status < 100 || status > 999) return null
  if (status >= 400 && status <= 499) return 'HTTP_4XX'
  if (status >= 500 && status <= 599) return 'HTTP_5XX'
  return 'HTTP_OTHER'
}

export function boundedLlmProviderDiagnostic(stage, error) {
  if (!llmProviderFailureStageSet.has(stage)) {
    throw new Error('The LLM provider failure stage is not bounded.')
  }
  const code = boundedLlmProviderFailureCode(error?.code)
  return Object.freeze({
    contract: 'DATARIVER_POC_LLM_PROVIDER_DIAGNOSTIC_V1',
    stage,
    provider_class: llmProviderFailureClassByCode[code],
    provider_http_class: boundedProviderHttpClass(error?.providerStatus),
  })
}

export function sanitizeLlmProviderDiagnostic(value) {
  if (!value || value.contract !== 'DATARIVER_POC_LLM_PROVIDER_DIAGNOSTIC_V1'
    || !llmProviderFailureStageSet.has(value.stage)
    || !Object.values(llmProviderFailureClassByCode).includes(value.provider_class)
    || !(value.provider_http_class === null || llmProviderHttpClasses.has(value.provider_http_class))) {
    return null
  }
  return {
    contract: value.contract,
    stage: value.stage,
    provider_class: value.provider_class,
    provider_http_class: value.provider_http_class,
  }
}

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
