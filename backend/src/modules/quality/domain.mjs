// Pure DataHub profile/assertion projection; missing optional metadata remains absent.
export function nonNegativeInteger(value) {
  if (Number.isSafeInteger(value) && value >= 0) return value
  if (typeof value !== 'string') return undefined
  const normalized = value.trim().replaceAll(',', '')
  if (!/^\d+$/.test(normalized)) return undefined
  const parsed = Number(normalized)
  return Number.isSafeInteger(parsed) ? parsed : undefined
}

export function datahubCustomPropertyValue(properties, keys) {
  const allowlist = new Set(keys.map((key) => key.toLocaleLowerCase()))
  for (const item of properties?.customProperties || []) {
    if (typeof item?.key !== 'string' || !allowlist.has(item.key.trim().toLocaleLowerCase())) continue
    const value = nonNegativeInteger(item.value)
    if (value !== undefined) return value
  }
  return undefined
}

export function isFullTableProfile(profile) {
  const partitionType = String(profile?.partitionSpec?.type || '').toUpperCase()
  const partition = String(profile?.partitionSpec?.partition || '').toUpperCase()
  if (partitionType === 'QUERY' || partition.startsWith('SAMPLE')) return false
  return !partitionType || partitionType === 'FULL_TABLE'
}

export function datahubProfileQuality(value, properties) {
  const profile = (Array.isArray(value) ? value : [])
    .filter((item) => item && typeof item === 'object' && isFullTableProfile(item))
    .filter((item) => ['rowCount', 'columnCount', 'sizeInBytes']
      .some((key) => nonNegativeInteger(item[key]) !== undefined))
    .sort((left, right) => Number(right.timestampMillis || 0) - Number(left.timestampMillis || 0))[0]
  const quality = {}
  if (profile) {
    for (const key of ['rowCount', 'columnCount', 'sizeInBytes']) {
      const metric = nonNegativeInteger(profile[key])
      if (metric !== undefined) quality[key] = metric
    }
    if (Number.isFinite(profile.timestampMillis) && profile.timestampMillis >= 0) {
      quality.profiledAt = new Date(profile.timestampMillis).toISOString()
    }
    quality.profileKind = 'FULL'
  }
  const propertyMetrics = {
    rowCount: datahubCustomPropertyValue(properties, [
      'row_count', 'rowCount', 'rows', 'num_rows', 'datariver.row_count',
    ]),
    sizeInBytes: datahubCustomPropertyValue(properties, [
      'size_in_bytes', 'sizeInBytes', 'size_bytes', 'datariver.size_in_bytes',
    ]),
  }
  for (const [key, metric] of Object.entries(propertyMetrics)) {
    if (quality[key] === undefined && metric !== undefined) {
      quality[key] = metric
      quality[`${key}Source`] = 'DATASET_PROPERTIES_ALLOWLIST'
    } else if (quality[key] !== undefined) {
      quality[`${key}Source`] = 'DATASET_PROFILE_FULL_TABLE'
    }
  }
  return quality
}

export function datahubAssertionQuality(connection) {
  if (!connection || !Number.isSafeInteger(connection.total) || connection.total < 0) return {}
  const assertions = Array.isArray(connection.assertions) ? connection.assertions : []
  const latest = assertions.flatMap((assertion) => (
    Array.isArray(assertion?.runEvents?.runEvents)
      ? assertion.runEvents.runEvents.map((run) => ({ assertion, run }))
      : []
  )).sort((left, right) => Number(right.run?.timestampMillis || 0) - Number(left.run?.timestampMillis || 0))[0]
  return {
    assertionTotal: connection.total,
    assertionReturned: assertions.length,
    assertionTruncated: assertions.length < connection.total,
    assertionSourceTypes: [...new Set(assertions
      .map((assertion) => assertion?.info?.source?.type)
      .filter((value) => typeof value === 'string' && value.trim()))].sort(),
    ...(latest ? {
        latestAssertionStatus: latest.run.status || null,
        latestAssertionResult: latest.run.result?.type || null,
        latestAssertionObservedAt: Number.isFinite(latest.run.timestampMillis)
          ? new Date(latest.run.timestampMillis).toISOString()
          : null,
      } : {}),
  }
}
