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

export function currentDatahubDatasetExists(entity, expectedUrn) {
  return Boolean(entity
    && typeof expectedUrn === 'string'
    && expectedUrn.startsWith('urn:li:dataset:(')
    && entity.urn === expectedUrn
    && entity.type === 'DATASET'
    && (entity.properties != null || entity.schemaMetadata != null))
}

export function isCurrentDatahubTable(entity, expectedUrn) {
  return currentDatahubDatasetExists(entity, expectedUrn) && datahubDatasetKind(entity) === 'TABLE'
}
