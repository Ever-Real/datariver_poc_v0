function customProperty(entity, key) {
  const match = (entity?.properties?.customProperties || []).find((item) => item?.key === key)
  return typeof match?.value === 'string' && match.value.trim() ? match.value.trim() : ''
}

export function datahubDatasetKind(entity) {
  const candidates = [
    ...(Array.isArray(entity?.subTypes?.typeNames) ? entity.subTypes.typeNames : []),
    customProperty(entity, 'datariver.seed.object_kind'),
    customProperty(entity, 'object_kind'),
  ].map((value) => String(value || '').trim().toLocaleUpperCase()).filter(Boolean)
  if (candidates.some((value) => value.includes('MATERIALIZED') && value.includes('VIEW'))) {
    return 'MATERIALIZED_VIEW'
  }
  if (candidates.some((value) => value.includes('VIEW'))) return 'VIEW'
  return 'TABLE'
}

export const DATAHUB_DATASET_CURRENTNESS_REASONS = Object.freeze([
  'DATASET_ENTITY_EXISTS_FALSE',
  'DATASET_EXISTS_FALSE',
  'DATASET_STATUS_REMOVED',
  'DATASET_CURRENTNESS_CONTRADICTORY',
  'DATASET_CURRENT_ASPECTS_ABSENT',
])

export function classifyCurrentDatahubDataset(entity, expectedUrn, signals = {}) {
  if (!entity
    || typeof expectedUrn !== 'string'
    || !expectedUrn.startsWith('urn:li:dataset:(')
    || entity.urn !== expectedUrn
    || entity.type !== 'DATASET') {
    return Object.freeze({ current: false, reason: 'DATASET_IDENTITY_INVALID' })
  }
  const hasEntityExists = Object.hasOwn(signals, 'entityExists')
  if (hasEntityExists && typeof signals.entityExists !== 'boolean') {
    return Object.freeze({ current: false, reason: 'DATASET_CURRENTNESS_SIGNAL_INVALID' })
  }
  if (entity.exists !== undefined && entity.exists !== null && typeof entity.exists !== 'boolean') {
    return Object.freeze({ current: false, reason: 'DATASET_CURRENTNESS_SIGNAL_INVALID' })
  }
  if (entity.status !== undefined && entity.status !== null
    && (typeof entity.status !== 'object' || Array.isArray(entity.status)
      || (entity.status.removed !== undefined && entity.status.removed !== null
        && typeof entity.status.removed !== 'boolean'))) {
    return Object.freeze({ current: false, reason: 'DATASET_CURRENTNESS_SIGNAL_INVALID' })
  }
  if (hasEntityExists && signals.entityExists === false) {
    return Object.freeze({
      current: false,
      reason: entity.exists === true
        ? 'DATASET_CURRENTNESS_CONTRADICTORY'
        : 'DATASET_ENTITY_EXISTS_FALSE',
    })
  }
  if (entity.exists === false) {
    return Object.freeze({
      current: false,
      reason: hasEntityExists && signals.entityExists === true
        ? 'DATASET_CURRENTNESS_CONTRADICTORY'
        : 'DATASET_EXISTS_FALSE',
    })
  }
  if (entity.status?.removed === true) {
    return Object.freeze({ current: false, reason: 'DATASET_STATUS_REMOVED' })
  }
  if (entity.properties == null && entity.schemaMetadata == null) {
    return Object.freeze({ current: false, reason: 'DATASET_CURRENT_ASPECTS_ABSENT' })
  }
  return Object.freeze({ current: true, reason: null })
}

export function currentDatahubDatasetExists(entity, expectedUrn, signals) {
  return classifyCurrentDatahubDataset(entity, expectedUrn, signals).current
}

export function isCurrentDatahubTable(entity, expectedUrn, signals) {
  return currentDatahubDatasetExists(entity, expectedUrn, signals) && datahubDatasetKind(entity) === 'TABLE'
}
