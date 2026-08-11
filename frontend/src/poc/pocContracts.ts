import type { CatalogPolicyMeta, ChatResponse } from '../api/types'

export const POC_WORKSPACE_ID = '00000000-0000-4000-8000-000000000061'
export const POC_SUBJECT_ID = '00000000-0000-4000-8000-000000000111'
export const POC_CACHE_SCOPE = 'a'.repeat(64)
export const POC_NOW = '2026-08-11T09:00:00.000Z'

export function authorizationWindow() {
  const observedAt = new Date()
  return {
    observed_at: observedAt.toISOString(),
    authorization_valid_until: new Date(observedAt.getTime() + 30_000).toISOString(),
  }
}

export const catalogMeta: CatalogPolicyMeta = {
  observed_at: POC_NOW,
  stale_at: null,
  projection_version: 1,
  policy_version: 'POC_EMPTY_CATALOG_V1',
  classification_policy_version: 1,
  authorization_generation: 1,
}

export const scorePolicy = {
  policy_id: 'UNWEIGHTED_RULE_PASS_RATE_V1',
  policy_version: 1,
  policy_hash: 'd'.repeat(64),
  calculation: 'passed / (passed + advisory_failed + blocking_failed)',
  pass_condition: 'evaluated > 0 and advisory_failed = 0 and blocking_failed = 0',
  warn_condition: 'blocking_failed = 0 and advisory_failed > 0',
  fail_condition: 'blocking_failed > 0',
  unknown_condition: 'evaluated = 0',
} as const

export const chatWorkflow = [
  'AUTHORIZATION',
  'BUDGET_RESERVATION',
  'ROUTING',
  'RETRIEVAL',
  'RERANKING',
  'COMPOSITION',
  'CITATION_VALIDATION',
  'PERSISTENCE',
].map((stage) => ({
  stage,
  status: 'COMPLETED',
  detail_code: 'POC_LIVE_PROVIDER',
})) as ChatResponse['workflow']
