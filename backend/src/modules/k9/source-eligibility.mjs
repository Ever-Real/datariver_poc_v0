export const K9_SOURCE_ELIGIBILITY_CONTRACT = 'DATARIVER_K9_SOURCE_ELIGIBILITY_V1'

const canonicalDatasetKinds = new Set(['TABLE', 'VIEW', 'MATERIALIZED_VIEW'])
const classificationStates = new Set(['EXACT', 'MISSING', 'MULTIPLE', 'INVALID'])

function canonicalDatasetUrn(value) {
  return typeof value === 'string'
    && value.length <= 4_096
    && value.startsWith('urn:li:dataset:(')
    && value.endsWith(')')
}

function classificationState(item) {
  const state = item?.classification_resolution?.status
  return classificationStates.has(state) ? state : 'INVALID'
}

export function selectCanonicalK9SourceInventory(items, { classificationCeiling = null } = {}) {
  if (!Array.isArray(items)) throw new Error('The K9 provider/current inventory is invalid.')
  const eligibleItems = []
  const telemetry = {
    contract: K9_SOURCE_ELIGIBILITY_CONTRACT,
    provider_current_inventory_count: items.length,
    canonical_current_count: 0,
    eligible_source_count: 0,
    invalid_identity_count: 0,
    unsupported_kind_count: 0,
    classification_exact_count: 0,
    classification_missing_count: 0,
    classification_multiple_count: 0,
    classification_invalid_count: 0,
    classification_ceiling: typeof classificationCeiling === 'string' ? classificationCeiling : null,
    classification_authority: false,
  }
  for (const item of items) {
    if (!canonicalDatasetUrn(item?.id || item?.urn || item?.external_urn)) {
      telemetry.invalid_identity_count += 1
      continue
    }
    if (!canonicalDatasetKinds.has(item?.dataset_kind)) {
      telemetry.unsupported_kind_count += 1
      continue
    }
    telemetry.canonical_current_count += 1
    telemetry[`classification_${classificationState(item).toLowerCase()}_count`] += 1
    eligibleItems.push(item)
  }
  telemetry.eligible_source_count = eligibleItems.length
  if (telemetry.provider_current_inventory_count !== telemetry.canonical_current_count
    + telemetry.invalid_identity_count + telemetry.unsupported_kind_count
    || telemetry.canonical_current_count !== telemetry.classification_exact_count
      + telemetry.classification_missing_count + telemetry.classification_multiple_count
      + telemetry.classification_invalid_count
    || telemetry.eligible_source_count !== telemetry.canonical_current_count) {
    throw new Error('The K9 source eligibility accounting invariant failed.')
  }
  return Object.freeze({
    items: Object.freeze([...eligibleItems]),
    telemetry: Object.freeze(telemetry),
  })
}

export function sanitizeK9SourceEligibilityTelemetry(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)
    || value.contract !== K9_SOURCE_ELIGIBILITY_CONTRACT
    || value.classification_authority !== false
    || (value.classification_ceiling !== null
      && !['PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED'].includes(value.classification_ceiling))) return null
  const countFields = [
    'provider_current_inventory_count', 'canonical_current_count', 'eligible_source_count',
    'invalid_identity_count', 'unsupported_kind_count', 'classification_exact_count',
    'classification_missing_count', 'classification_multiple_count', 'classification_invalid_count',
  ]
  if (countFields.some((field) => !Number.isSafeInteger(value[field])
    || value[field] < 0 || value[field] > 1_000_000_000)) return null
  const normalized = Object.freeze({
    contract: K9_SOURCE_ELIGIBILITY_CONTRACT,
    ...Object.fromEntries(countFields.map((field) => [field, value[field]])),
    classification_ceiling: value.classification_ceiling,
    classification_authority: false,
  })
  if (normalized.provider_current_inventory_count !== normalized.canonical_current_count
    + normalized.invalid_identity_count + normalized.unsupported_kind_count
    || normalized.canonical_current_count !== normalized.classification_exact_count
      + normalized.classification_missing_count + normalized.classification_multiple_count
      + normalized.classification_invalid_count
    || normalized.eligible_source_count !== normalized.canonical_current_count) return null
  return normalized
}
