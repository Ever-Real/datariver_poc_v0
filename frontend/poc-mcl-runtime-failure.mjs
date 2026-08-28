const DISCOVERY_CLASSIFICATION = /^PREP_MCL_DISCOVERY_[A-Z0-9_]+_FAILED$/
const DIAGNOSTIC_IDENTIFIER = /^[A-Z][A-Z0-9_]{0,79}$/
const SHAPE_IDENTIFIER = /^[A-Za-z][A-Za-z0-9_]{0,63}$/

export const MCL_RECORD_NORMALIZATION_LOCI = Object.freeze([
  'ENTITY_URN_INVALID',
  'ASPECT_NAME_INVALID',
  'CREATED_TIME_INVALID',
  'CREATED_ACTOR_INVALID',
  'ASPECT_CONTENT_TYPE_INVALID',
  'ASPECT_JSON_INVALID',
  'ASPECT_SIZE_LIMIT_EXCEEDED',
  'CURRENT_PREVIOUS_EVIDENCE_MISSING',
  'ENTITY_LIFECYCLE_CONTRACT_INVALID',
  'SCHEMA_FIELD_CONTRACT_INVALID',
  'SCHEMA_FIELD_DUPLICATE',
  'LOGICAL_TYPE_CONTRACT_INVALID',
  'COLLECTION_ITEM_CONTRACT_INVALID',
  'COLLECTION_ITEM_DUPLICATE',
  'DOCUMENT_FIELD_CONTRACT_INVALID',
  'EVENT_FANOUT_LIMIT_EXCEEDED',
  'OTHER_NORMALIZATION_CONTRACT_INVALID',
])

const MCL_RECORD_NORMALIZATION_LOCUS_SET = new Set(MCL_RECORD_NORMALIZATION_LOCI)
const SHAPE_TYPE_CLASSES = new Set([
  'NULL', 'UNDEFINED', 'BOOLEAN', 'NUMBER', 'STRING', 'BIGINT', 'OBJECT', 'FUNCTION', 'SYMBOL', 'OTHER',
])
const SHAPE_TIME_REPRESENTATIONS = new Set(['NUMBER', 'STRING', 'LONG_OBJECT', 'NULL', 'OTHER'])
const SHAPE_CONTENT_TYPES = new Set(['APPLICATION_JSON', 'MISSING', 'OTHER'])
const SHAPE_CHANGE_TYPES = new Set([
  'UPSERT', 'CREATE', 'UPDATE', 'DELETE', 'PATCH', 'RESTATE', 'CREATE_ENTITY',
  'MISSING', 'OTHER',
])
const MCL_RECORD_SHAPE_CONTRACT = 'DATARIVER_MCL_REJECTED_RECORD_SHAPE_V1'

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

export function mclCaptureFailure(error, { stage, detailCode, recordShape } = {}) {
  if (isMclRuntimeClassification(error?.code || '')) return error
  const classification = CAPTURE_CLASSIFICATION_BY_STAGE[stage]
  if (!classification || !DIAGNOSTIC_IDENTIFIER.test(detailCode)) {
    throw new Error('The MCL capture failure classification contract is invalid.')
  }
  if (stage === 'RECORD_NORMALIZATION' && !MCL_RECORD_NORMALIZATION_LOCUS_SET.has(detailCode)) {
    throw new Error('The MCL record normalization detail contract is invalid.')
  }
  const failure = Object.assign(
    new Error('MCL runtime capture failed at a classified stage.', error instanceof Error ? { cause: error } : undefined),
    { code: classification, mclStage: stage, mclDetailCode: detailCode },
  )
  const sanitizedShape = sanitizeMclRecordShape(recordShape)
  if (sanitizedShape && sanitizedShape.rejection_locus !== detailCode) {
    throw new Error('The MCL rejected-record shape conflicts with its failure detail.')
  }
  if (stage === 'RECORD_NORMALIZATION' && sanitizedShape) failure.mclRecordShape = sanitizedShape
  return failure
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
  const recordShape = trustedCandidate && failureStage === 'RECORD_NORMALIZATION'
    ? sanitizeMclRecordShape(error?.mclRecordShape)
    : null
  return Object.freeze({
    classification,
    failureStage,
    failureDetailCode,
    ...(recordShape ? { recordShape } : {}),
  })
}

export function mclRecordNormalizationLocus(error) {
  return MCL_RECORD_NORMALIZATION_LOCUS_SET.has(error?.mclNormalizationLocus)
    ? error.mclNormalizationLocus
    : 'OTHER_NORMALIZATION_CONTRACT_INVALID'
}

export function mclRecordNormalizationFailure(error, locus) {
  if (MCL_RECORD_NORMALIZATION_LOCUS_SET.has(error?.mclNormalizationLocus)) return error
  if (!MCL_RECORD_NORMALIZATION_LOCUS_SET.has(locus)) {
    throw new Error('The MCL record normalization locus is invalid.')
  }
  const message = error instanceof Error
    ? error.message
    : 'The MCL record violates a bounded normalization contract.'
  return Object.assign(
    new Error(message, error instanceof Error ? { cause: error } : undefined),
    { mclNormalizationLocus: locus },
  )
}

export function sanitizeMclRecordShape(value) {
  if (!isPlainObject(value) || value.contract !== MCL_RECORD_SHAPE_CONTRACT) return null
  if (!nonnegativeSafeInteger(value.partition) || !nonnegativeSafeInteger(value.offset)) return null
  if (!shapeIdentifier(value.entity_type) || !shapeIdentifier(value.aspect_name)) return null
  if (!SHAPE_CHANGE_TYPES.has(value.change_type)) return null
  if (typeof value.aspect_present !== 'boolean'
    || typeof value.previous_aspect_value_present !== 'boolean') return null
  if (!SHAPE_CONTENT_TYPES.has(value.aspect_content_type)
    || !SHAPE_CONTENT_TYPES.has(value.previous_aspect_content_type)) return null
  if (!SHAPE_TYPE_CLASSES.has(value.created_type)
    || !SHAPE_TYPE_CLASSES.has(value.created_time_type)
    || !SHAPE_TIME_REPRESENTATIONS.has(value.created_time_representation)
    || !SHAPE_TYPE_CLASSES.has(value.created_actor_type)) return null
  if (typeof value.current_aspect_decoded_object !== 'boolean'
    || typeof value.previous_aspect_decoded_object !== 'boolean') return null
  if (!boundedShapeCount(value.current_collection_item_count)
    || !boundedShapeCount(value.previous_collection_item_count)) return null
  if (!MCL_RECORD_NORMALIZATION_LOCUS_SET.has(value.rejection_locus)) return null
  return Object.freeze({
    contract: MCL_RECORD_SHAPE_CONTRACT,
    partition: value.partition,
    offset: value.offset,
    entity_type: value.entity_type,
    aspect_name: value.aspect_name,
    change_type: value.change_type,
    aspect_present: value.aspect_present,
    previous_aspect_value_present: value.previous_aspect_value_present,
    aspect_content_type: value.aspect_content_type,
    previous_aspect_content_type: value.previous_aspect_content_type,
    created_type: value.created_type,
    created_time_type: value.created_time_type,
    created_time_representation: value.created_time_representation,
    created_actor_type: value.created_actor_type,
    current_aspect_decoded_object: value.current_aspect_decoded_object,
    previous_aspect_decoded_object: value.previous_aspect_decoded_object,
    current_collection_item_count: value.current_collection_item_count,
    previous_collection_item_count: value.previous_collection_item_count,
    rejection_locus: value.rejection_locus,
  })
}

function shapeIdentifier(value) {
  return value === 'MISSING' || value === 'MALFORMED' || value === 'UNSUPPORTED'
    || (typeof value === 'string' && SHAPE_IDENTIFIER.test(value))
}

function nonnegativeSafeInteger(value) {
  return Number.isSafeInteger(value) && value >= 0
}

function boundedShapeCount(value) {
  return value === null || (nonnegativeSafeInteger(value) && value <= 1_000_000)
}

function isPlainObject(value) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false
  const prototype = Object.getPrototypeOf(value)
  return prototype === Object.prototype || prototype === null
}
