const DISCOVERY_CLASSIFICATION = /^PREP_MCL_DISCOVERY_[A-Z0-9_]+_FAILED$/
const DIAGNOSTIC_IDENTIFIER = /^[A-Z][A-Z0-9_]{0,79}$/

const CAPTURE_CLASSIFICATION_BY_STAGE = Object.freeze({
  SCHEDULER_RUNTIME: 'PREP_MCL_CAPTURE_RUNTIME_UNEXPECTED_FAILED',
  CAPTURE_INITIALIZATION: 'PREP_MCL_CAPTURE_DURABLE_STORE_FAILED',
  KAFKA_ADMIN_CONSTRUCTION: 'PREP_MCL_CAPTURE_KAFKA_ADMIN_FAILED',
  KAFKA_ADMIN_CONNECT: 'PREP_MCL_CAPTURE_KAFKA_ADMIN_FAILED',
  KAFKA_WATERMARK_READ: 'PREP_MCL_CAPTURE_WATERMARK_FAILED',
  KAFKA_WATERMARK_VALIDATION: 'PREP_MCL_CAPTURE_WATERMARK_CONTRACT_FAILED',
  CAPTURE_BOUNDARY_PERSISTENCE: 'PREP_MCL_CAPTURE_BOUNDARY_PERSISTENCE_FAILED',
  CAPTURE_BOUNDARY_VALIDATION: 'PREP_MCL_CAPTURE_BOUNDARY_CONTRACT_FAILED',
  RETENTION_CHECK: 'PREP_MCL_CAPTURE_HISTORY_GAP_BLOCKED',
  CHECKPOINT_VALIDATION: 'PREP_MCL_CAPTURE_CHECKPOINT_CONTRACT_FAILED',
  KAFKA_CONSUMER_CONSTRUCTION: 'PREP_MCL_CAPTURE_KAFKA_CONSUMER_FAILED',
  KAFKA_CONSUMER_CONNECT: 'PREP_MCL_CAPTURE_KAFKA_CONSUMER_FAILED',
  KAFKA_CONSUMER_SUBSCRIBE: 'PREP_MCL_CAPTURE_KAFKA_CONSUMER_FAILED',
  KAFKA_CONSUMER_GROUP_LISTENER: 'PREP_MCL_CAPTURE_KAFKA_CONSUMER_FAILED',
  KAFKA_CONSUMER_SEEK: 'PREP_MCL_CAPTURE_KAFKA_CONSUMER_FAILED',
  KAFKA_CONSUMER_RUN: 'PREP_MCL_CAPTURE_KAFKA_CONSUMER_FAILED',
  KAFKA_CONSUMER_PAUSE: 'PREP_MCL_CAPTURE_KAFKA_CONSUMER_FAILED',
  CAPTURE_WAIT: 'PREP_MCL_CAPTURE_TIMEOUT_FAILED',
  MESSAGE_OFFSET_VALIDATION: 'PREP_MCL_CAPTURE_OFFSET_CONTRACT_FAILED',
  SCHEMA_DECODE: 'PREP_MCL_CAPTURE_SCHEMA_DECODE_FAILED',
  RECORD_NORMALIZATION: 'PREP_MCL_CAPTURE_RECORD_CONTRACT_FAILED',
  DURABLE_APPEND: 'PREP_MCL_CAPTURE_DURABLE_APPEND_FAILED',
  KAFKA_CONSUMER_CLEANUP: 'PREP_MCL_CAPTURE_KAFKA_CLEANUP_FAILED',
  KAFKA_ADMIN_CLEANUP: 'PREP_MCL_CAPTURE_KAFKA_CLEANUP_FAILED',
  CAPTURE_EXECUTION: 'PREP_MCL_CAPTURE_EXECUTION_FAILED',
  CAPTURE_RESULT_VALIDATION: 'PREP_MCL_CAPTURE_CONTRACT_FAILED',
  CAPTURE_STATUS_PERSISTENCE: 'PREP_MCL_CAPTURE_STATUS_PERSISTENCE_FAILED',
  CAPTURE_PROGRESS_VALIDATION: 'PREP_MCL_CAPTURE_PROGRESS_FAILED',
  CATALOG_RECONCILIATION: 'PREP_MCL_CAPTURE_CATALOG_RECONCILIATION_FAILED',
  SCHEDULER_STATE: 'PREP_MCL_CAPTURE_SCHEDULER_STATE_FAILED',
})

const CAPTURE_CLASSIFICATIONS = new Set(Object.values(CAPTURE_CLASSIFICATION_BY_STAGE))

export function isMclRuntimeClassification(value) {
  return CAPTURE_CLASSIFICATIONS.has(value) || DISCOVERY_CLASSIFICATION.test(value)
}

export function mclCaptureFailure(error, { stage, detailCode }) {
  if (isMclRuntimeClassification(error?.code || '')) return error
  const classification = CAPTURE_CLASSIFICATION_BY_STAGE[stage]
  if (!classification || !DIAGNOSTIC_IDENTIFIER.test(detailCode)) {
    throw new Error('The MCL capture failure classification contract is invalid.')
  }
  return Object.assign(
    new Error('MCL runtime capture failed at a classified stage.', error instanceof Error ? { cause: error } : undefined),
    { code: classification, mclStage: stage, mclDetailCode: detailCode },
  )
}

export function mclRuntimeFailureDiagnostic(error, {
  fallbackClassification = CAPTURE_CLASSIFICATION_BY_STAGE.SCHEDULER_RUNTIME,
  fallbackStage = 'SCHEDULER_RUNTIME',
  fallbackDetailCode = 'UNCLASSIFIED_ERROR',
} = {}) {
  const candidate = typeof error?.code === 'string' ? error.code : ''
  const trustedCandidate = isMclRuntimeClassification(candidate)
  const classification = trustedCandidate ? candidate : fallbackClassification
  if (!isMclRuntimeClassification(classification)) {
    throw new Error('The fallback MCL runtime classification is invalid.')
  }
  const historyGap = classification === 'PREP_MCL_CAPTURE_HISTORY_GAP_BLOCKED'
  const discoveryReason = classification.startsWith('PREP_MCL_DISCOVERY_')
    ? classification.slice('PREP_MCL_DISCOVERY_'.length, -'_FAILED'.length)
    : null
  const candidateStage = trustedCandidate && typeof error?.mclStage === 'string' ? error.mclStage : ''
  const candidateDetail = trustedCandidate && typeof error?.mclDetailCode === 'string' ? error.mclDetailCode : ''
  const failureStage = DIAGNOSTIC_IDENTIFIER.test(candidateStage)
    ? candidateStage
    : historyGap
      ? 'RETENTION_CHECK'
      : discoveryReason && DIAGNOSTIC_IDENTIFIER.test(`DISCOVERY_${discoveryReason}`)
        ? `DISCOVERY_${discoveryReason}`
        : fallbackStage
  const failureDetailCode = DIAGNOSTIC_IDENTIFIER.test(candidateDetail)
    ? candidateDetail
    : historyGap
      ? 'CHECKPOINT_BEHIND_LOW_WATERMARK'
      : discoveryReason && DIAGNOSTIC_IDENTIFIER.test(discoveryReason)
        ? discoveryReason
        : fallbackDetailCode
  if (!DIAGNOSTIC_IDENTIFIER.test(failureStage)
    || !DIAGNOSTIC_IDENTIFIER.test(failureDetailCode)) {
    throw new Error('The fallback MCL runtime diagnostic is invalid.')
  }
  return Object.freeze({ classification, failureStage, failureDetailCode })
}
