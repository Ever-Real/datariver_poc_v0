import { nonNegativeInteger, datahubCustomPropertyValue, isFullTableProfile, datahubProfileQuality, datahubAssertionQuality } from '../quality/domain.mjs'
/* global Buffer, URLSearchParams, structuredClone */
// Dependencies are supplied by bootstrap; this module never constructs a shared client.
export function createModulesCatalogApplication(deps) {
function boundedDatahubGraphqlDiagnostic(errors) {
  if (!Array.isArray(errors) || errors.length === 0) return null
  const first = errors.find((value) => value && typeof value === 'object') || {}
  const rawClass = first.extensions?.code || first.extensions?.type || 'UNCLASSIFIED'
  const errorClass = String(rawClass).toUpperCase().replace(/[^A-Z0-9_]/g, '_').slice(0, 64)
  const path = Array.isArray(first.path)
    ? first.path.slice(0, 8).map((value) => String(value).replace(/[^A-Za-z0-9_]/g, '_').slice(0, 32)).join('.')
    : null
  return Object.freeze({
    error_class: /^[A-Z][A-Z0-9_]{0,63}$/.test(errorClass) ? errorClass : 'UNCLASSIFIED',
    path: path && /^[A-Za-z0-9_.]{1,160}$/.test(path) ? path : null,
    error_count: Math.min(errors.length, 1000),
  })
}

async function datahubGraphql(query, variables, timeoutMs = deps.providerTimeoutMs, signal) {
  if (!deps.datahub) throw Object.assign(new Error('DataHub is not configured.'), { statusCode: 503 })
  let response
  try {
    response = await deps.providerFetch(deps.joinProviderUrl(deps.datahub.url, '/api/graphql'), {
      method: 'POST',
      headers: {
        ...(deps.datahub.token ? { Authorization: `Bearer ${deps.datahub.token}` } : {}),
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ query, variables }),
      timeoutMs,
      signal,
    })
  } catch (error) {
    throw Object.assign(error, { providerFailureKind: error?.providerFailureKind || 'TRANSPORT' })
  }
  try {
    await deps.requireOk(response, 'DataHub')
  } catch (error) {
    throw Object.assign(error, {
      providerFailureKind: 'HTTP',
      providerHttpClass: `${Math.floor(response.status / 100)}xx`,
    })
  }
  let payload
  try {
    payload = await response.json()
  } catch (error) {
    throw Object.assign(error, { providerFailureKind: 'RESPONSE_JSON' })
  }
  if (payload.errors?.length) {
    throw Object.assign(new Error('DataHub rejected the fixed POC GraphQL query.'), {
      providerFailureKind: 'GRAPHQL',
      providerGraphqlDiagnostic: boundedDatahubGraphqlDiagnostic(payload.errors),
    })
  }
  return payload.data
}

function glossarySmokeProviderDetail(error) {
  if (['TimeoutError', 'AbortError'].includes(error?.name)) return 'TIMEOUT'
  if (error?.providerFailureKind === 'HTTP') {
    if (error?.providerHttpClass === '4xx') return 'HTTP_4XX'
    if (error?.providerHttpClass === '5xx') return 'HTTP_5XX'
    return 'HTTP_OTHER'
  }
  if (error?.providerFailureKind === 'GRAPHQL') return 'GRAPHQL'
  if (error?.providerFailureKind === 'RESPONSE_JSON') return 'CONTRACT'
  if (error?.providerFailureKind === 'TRANSPORT') return 'CONNECTIVITY'
  return 'CONTRACT'
}

function glossarySmokeFailure(code, substage, operation, reason, {
  statusCode = 502,
  terminal = true,
  cause,
} = {}) {
  const nestedErrorCode = cause ? glossarySmokeProviderDetail(cause) : reason
  return Object.assign(new Error('Bounded DataHub GlossaryTerm smoke verification failed.'), {
    statusCode,
    code,
    diagnostic: {
      terminal,
      substage,
      endpoint: 'DATAHUB_GRAPHQL',
      operation,
      sanitized_reason: reason,
      nested_error_code: nestedErrorCode,
    },
  })
}

async function datahubRefreshGraphql(query, variables, signal) {
  for (let attempt = 1; attempt <= 2; attempt += 1) {
    try {
      return await datahubGraphql(query, variables, 60_000, signal)
    } catch (error) {
      if (error && typeof error === 'object') error.providerRetryAttempt = attempt
      if (signal?.aborted || attempt === 2
        || !['TimeoutError', 'AbortError'].includes(error?.name)) throw error
    }
  }
  throw new Error('The bounded DataHub refresh retry was exhausted.')
}

async function datahubRuntimeIdentity() {
  if (!deps.datahubRuntimeIdentityPromise) {
    deps.datahubRuntimeIdentityPromise = (async () => {
      if (!deps.datahub) {
        throw Object.assign(new Error('DataHub runtime identity is not configured.'), {
          providerFailureKind: 'CONTRACT',
        })
      }
      let response
      try {
        response = await deps.providerFetch(deps.joinProviderUrl(deps.datahub.url, '/config'), {
          headers: datahubHeaders(),
        })
      } catch (error) {
        throw Object.assign(error, { providerFailureKind: error?.providerFailureKind || 'TRANSPORT' })
      }
      try {
        await deps.requireOk(response, 'DataHub configuration')
      } catch (error) {
        throw Object.assign(error, {
          providerFailureKind: 'HTTP',
          providerHttpClass: `${Math.floor(response.status / 100)}xx`,
        })
      }
      let payload
      try {
        payload = await response.json()
      } catch (error) {
        throw Object.assign(error, { providerFailureKind: 'RESPONSE_JSON' })
      }
      const release = payload?.versions?.['acryldata/datahub']
      if (typeof release?.version !== 'string' || !release.version.trim()) {
        throw Object.assign(new Error('DataHub did not expose a canonical runtime version.'), {
          providerFailureKind: 'CONTRACT',
        })
      }
      return Object.freeze({
        version: release.version.trim(),
        commit: typeof release.commit === 'string' && release.commit.trim() ? release.commit.trim() : null,
      })
    })().catch((error) => {
      deps.datahubRuntimeIdentityPromise = undefined
      throw error
    })
  }
  return deps.datahubRuntimeIdentityPromise
}

function datahubHeaders(extra = {}) {
  return {
    ...(deps.datahub?.token ? { Authorization: `Bearer ${deps.datahub.token}` } : {}),
    ...extra,
  }
}

function datahubAssetCacheKey(urn) {
  return `datahub-asset-v3:${deps.datahubCacheScope}:${deps.createHash('sha256').update(urn).digest('hex')}`
}

function datahubAssetBaseCacheKey(urn) {
  return `datahub-asset-base-v1:${deps.datahubCacheScope}:${deps.createHash('sha256').update(urn).digest('hex')}`
}

async function invalidateDatahubCaches(urn) {
  if (deps.inventorySnapshot) deps.inventorySnapshot.expiresAt = 0
  deps.catalogEmbeddingSnapshot = undefined
  deps.catalogEmbeddingRefreshStartedAt = 0
  await Promise.allSettled([
    deps.pocStateStore.cacheDelete(deps.datahubInventoryCacheKey),
    ...(urn ? [
      deps.pocStateStore.cacheDelete(datahubAssetCacheKey(urn)),
      deps.pocStateStore.cacheDelete(datahubAssetBaseCacheKey(urn)),
    ] : []),
  ])
  if (deps.datahub) void startDatahubInventoryRefresh().catch(() => undefined)
}

function datahubAspectDocument(payload) {
  const aspect = payload?.aspect
  if (!aspect || typeof aspect !== 'object' || Array.isArray(aspect)) return {}
  const values = Object.values(aspect)
  const document = values.length === 1 ? values[0] : undefined
  if (!document || typeof document !== 'object' || Array.isArray(document)) return {}
  return structuredClone(document)
}

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(',')}}`
  }
  return JSON.stringify(value)
}

function canonicalHash(value) {
  return deps.sha256(canonicalJson(value))
}

function malformedDatahubReadback(aspectName) {
  return Object.assign(new Error(`DataHub ${aspectName} read-back is malformed.`), {
    statusCode: 502,
    detailCode: 'DATAHUB_READBACK_MALFORMED',
  })
}

function plainDocument(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const prototype = Object.getPrototypeOf(value)
  return prototype === Object.prototype || prototype === null
}

function validAuditStamp(value) {
  if (!plainDocument(value)) return false
  const allowedKeys = new Set(['actor', 'time', 'impersonator', 'message'])
  if (Object.keys(value).some((key) => !allowedKeys.has(key))) return false
  if (typeof value.actor !== 'string' || !value.actor.startsWith('urn:li:')) return false
  if (!Number.isSafeInteger(value.time) || value.time < 0) return false
  return ['impersonator', 'message'].every((key) => (
    !(key in value) || value[key] === null || typeof value[key] === 'string'
  ))
}

function manualMetadataAspectComparableDocument(aspectName, document, {
  observed = false,
  absent = false,
} = {}) {
  if (!plainDocument(document)) throw malformedDatahubReadback(aspectName)
  if (absent) {
    if (!observed || Object.keys(document).length !== 0) throw malformedDatahubReadback(aspectName)
    if (aspectName === 'domains') return { domains: [] }
    if (aspectName === 'glossaryTerms') return { terms: [] }
    return structuredClone(document)
  }
  if (aspectName === 'domains') {
    const keys = Object.keys(document)
    if (keys.length !== 1 || keys[0] !== 'domains' || !Array.isArray(document.domains)) {
      throw malformedDatahubReadback(aspectName)
    }
    return structuredClone(document)
  }
  if (aspectName === 'glossaryTerms') {
    const keys = Object.keys(document)
    if (!keys.includes('terms') || !Array.isArray(document.terms)
        || keys.some((key) => key !== 'terms' && key !== 'auditStamp')
        || ('auditStamp' in document && !validAuditStamp(document.auditStamp))
        || (observed && !('auditStamp' in document))) {
      throw malformedDatahubReadback(aspectName)
    }
    return { terms: structuredClone(document.terms) }
  }
  return structuredClone(document)
}

function manualMetadataAspectHash(aspectName, document, options) {
  return canonicalHash(manualMetadataAspectComparableDocument(aspectName, document, options))
}

async function datahubReadAspect(urn, aspectName) {
  if (!deps.datahub || !deps.allowedDataHubAspects.has(aspectName)) {
    throw Object.assign(new Error('DataHub aspect is not configured or allowlisted.'), { statusCode: 503 })
  }
  const response = await deps.providerFetch(
    `${deps.joinProviderUrl(deps.datahub.url, `/aspects/${encodeURIComponent(urn)}`)}?aspect=${encodeURIComponent(aspectName)}&version=0`,
    { headers: datahubHeaders() },
  )
  if (response.status === 404) return { document: {}, version: 'absent' }
  await deps.requireOk(response, `DataHub ${aspectName} read`)
  const payload = await response.json()
  return {
    document: datahubAspectDocument(payload),
    version: deps.boundedString(payload.version, 255, String(payload.version ?? 'unknown')),
  }
}

async function datahubApplyAspect(urn, aspectName, document, idempotencyKey) {
  if (!deps.datahub || !deps.allowedDataHubAspects.has(aspectName)) {
    throw Object.assign(new Error('DataHub aspect is not configured or allowlisted.'), { statusCode: 503 })
  }
  if (!/^urn:li:dataset:\(.+\)$/.test(urn) || urn.length > 4_096) {
    throw Object.assign(new Error('A valid DataHub dataset URN is required.'), { statusCode: 400 })
  }
  const encoded = canonicalJson(document)
  if (Buffer.byteLength(encoded) > deps.maximumJsonBytes) {
    throw Object.assign(new Error('The DataHub aspect exceeds the POC write boundary.'), { statusCode: 413 })
  }
  const proposal = {
    proposal: {
      entityType: 'dataset',
      entityUrn: urn,
      changeType: 'UPSERT',
      aspectName,
      aspect: { value: encoded, contentType: 'application/json' },
    },
  }
  const response = await deps.providerFetch(deps.joinProviderUrl(deps.datahub.url, '/aspects?action=ingestProposal'), {
    method: 'POST',
    headers: datahubHeaders({
      'Content-Type': 'application/json',
      'Idempotency-Key': idempotencyKey,
    }),
    body: JSON.stringify(proposal),
  })
  await deps.requireOk(response, `DataHub ${aspectName} write`)
  const confirmation = await response.json().catch(() => ({}))
  const observed = await datahubReadAspect(urn, aspectName)
  const expectedHash = manualMetadataAspectHash(aspectName, document)
  const observedHash = manualMetadataAspectHash(aspectName, observed.document, {
    observed: true,
    absent: observed.version === 'absent',
  })
  if (observedHash !== expectedHash) {
    throw Object.assign(new Error(`DataHub ${aspectName} read-back did not match the applied document.`), {
      statusCode: 502,
      detailCode: 'DATAHUB_READBACK_MISMATCH',
    })
  }
  await invalidateDatahubCaches(urn)
  return {
    expected_hash: expectedHash,
    observed_hash: observedHash,
    provider_version: observed.version,
    provider_response_hash: deps.sha256(JSON.stringify(confirmation)),
  }
}

function controlledUrn(value, prefix) {
  const candidate = deps.boundedString(value, 1_000).trim()
  if (!candidate) return undefined
  if (candidate.startsWith('urn:li:')) {
    if (!candidate.startsWith(prefix)) {
      throw Object.assign(new Error(`Controlled metadata must use ${prefix}.`), { statusCode: 400 })
    }
    return candidate
  }
  return `${prefix}${encodeURIComponent(candidate)}`
}

function uniqueControlledUrns(values, prefix, maximum = 100) {
  if (!Array.isArray(values) || values.length > maximum) {
    throw Object.assign(new Error('Controlled metadata exceeds the bounded item count.'), { statusCode: 400 })
  }
  return [...new Set(values.map((value) => controlledUrn(value, prefix)).filter(Boolean))]
}

async function applyManualMetadata(body) {
  const urn = deps.boundedString(body.asset_id, 4_096).trim()
  if (!/^urn:li:dataset:\(.+\)$/.test(urn)) {
    throw Object.assign(new Error('Manual metadata requires a live DataHub dataset URN.'), { statusCode: 400 })
  }
  const entity = await datahubEntity(urn)
  if (!entity) throw Object.assign(new Error('The DataHub asset was not found.'), { statusCode: 404 })
  const edits = Array.isArray(body.column_edits) ? body.column_edits : []
  if (edits.length > 1_000) {
    throw Object.assign(new Error('Manual metadata exceeds the bounded column edit count.'), { statusCode: 400 })
  }
  const aspectInputs = [
    ['datasetProperties', async (current) => {
      const description = deps.boundedString(body.description, 10_000)
      if (description) current.description = description
      else delete current.description
      return current
    }],
    ['domains', async (current) => {
      const domain = body.domain === null ? undefined : controlledUrn(body.domain, 'urn:li:domain:')
      current.domains = domain ? [domain] : []
      return current
    }],
    ['globalTags', async (current) => {
      current.tags = uniqueControlledUrns(body.tags ?? [], 'urn:li:tag:').map((tag) => ({ tag }))
      return current
    }],
    ['glossaryTerms', async (current) => {
      current.terms = uniqueControlledUrns(body.terms ?? [], 'urn:li:glossaryTerm:').map((urnValue) => ({ urn: urnValue }))
      return current
    }],
    ['schemaMetadata', async (current) => {
      if (!Array.isArray(current.fields)) {
        throw Object.assign(new Error('DataHub schemaMetadata has no editable fields.'), { statusCode: 409 })
      }
      const byPath = new Map(current.fields.map((field) => [field?.fieldPath, field]))
      const observed = new Set()
      for (const raw of edits) {
        if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
          throw Object.assign(new Error('A manual column edit is invalid.'), { statusCode: 400 })
        }
        const fieldPath = deps.boundedString(raw.field_path, 2_000).trim()
        const field = byPath.get(fieldPath)
        if (!field || observed.has(fieldPath)) {
          throw Object.assign(new Error(`DataHub column is missing or duplicated: ${fieldPath}`), { statusCode: 409 })
        }
        observed.add(fieldPath)
        const description = deps.boundedString(raw.description, 10_000)
        if (description) field.description = description
        else delete field.description
        const tags = uniqueControlledUrns(raw.tags ?? [], 'urn:li:tag:')
        if (field.globalTags || tags.length) field.globalTags = { tags: tags.map((tag) => ({ tag })) }
        const terms = uniqueControlledUrns(raw.terms ?? [], 'urn:li:glossaryTerm:')
        if (field.glossaryTerms || terms.length) {
          field.glossaryTerms = {
            ...(field.glossaryTerms?.auditStamp ? { auditStamp: field.glossaryTerms.auditStamp } : {}),
            terms: terms.map((urnValue) => ({ urn: urnValue })),
          }
        }
      }
      return current
    }],
  ]
  const reports = []
  for (const [index, [aspectName, mutate]] of aspectInputs.entries()) {
    const current = await datahubReadAspect(urn, aspectName)
    const beforeHash = manualMetadataAspectHash(aspectName, current.document, {
      observed: true,
      absent: current.version === 'absent',
    })
    const expected = await mutate(structuredClone(current.document))
    const expectedHash = manualMetadataAspectHash(aspectName, expected)
    if (beforeHash === expectedHash) {
      reports.push({
        aspect_name: aspectName, aspect_ordinal: index + 1,
        outcome: 'ALREADY_MATCHED', before_hash: beforeHash,
        expected_hash: beforeHash, observed_hash: beforeHash, write_attempted: false,
        failure_code: null, provider_version: current.version, provider_response_hash: null,
        observed_at: new Date().toISOString(),
      })
      continue
    }
    const receipt = await datahubApplyAspect(urn, aspectName, expected, `poc-manual-${deps.randomUUID()}`)
    reports.push({
      aspect_name: aspectName, aspect_ordinal: index + 1,
      outcome: 'APPLIED_VERIFIED', before_hash: beforeHash,
      ...receipt, write_attempted: true, failure_code: null,
      observed_at: new Date().toISOString(),
    })
  }
  await invalidateDatahubCaches(urn)
  return { urn, reports }
}

function urnTail(value) {
  if (typeof value !== 'string') return ''
  return value.split(':').at(-1)?.replace(/[()]/g, '') || value
}

function containerKind(entry) {
  const entity = entry?.entity
  if (entity?.type !== 'CONTAINER') return undefined
  const names = (entity.subTypes?.typeNames || [])
    .map((value) => String(value).toLowerCase().replace(/[^a-z0-9]/g, ''))
  if (names.some((value) => value === 'database' || value.endsWith('database'))) return 'DATABASE'
  if (names.some((value) => value === 'schema' || value.endsWith('schema'))) return 'SCHEMA'
  return undefined
}

function customProperty(entity, key) {
  const match = (entity.properties?.customProperties || []).find((item) => item?.key === key)
  return typeof match?.value === 'string' && match.value.trim() ? match.value.trim() : ''
}

function readablePathName(value) {
  if (typeof value !== 'string' || !value.trim() || value.startsWith('urn:li:')) return ''
  return value.trim()
}

function containerDisplayName(entry) {
  const properties = entry?.entity?.properties
  const explicit = readablePathName(properties?.name)
  if (explicit) return explicit
  const qualified = readablePathName(properties?.qualifiedName)
  if (qualified) return qualified.split(/[./]/).filter(Boolean).at(-1) || qualified
  return readablePathName(entry?.name)
}

function datasetIdentity(entity) {
  const match = typeof entity.urn === 'string'
    ? entity.urn.match(/^urn:li:dataset:\([^,]+,([^,]+),[^)]+\)$/)
    : undefined
  const qualifiedName = match?.[1] || ''
  const parts = qualifiedName.split('.').filter(Boolean)
  const path = entity.browsePathV2?.path || []
  const databaseNames = path
    .filter((entry) => containerKind(entry) === 'DATABASE')
    .map(containerDisplayName)
    .filter(Boolean)
  const schemaNames = path
    .filter((entry) => containerKind(entry) === 'SCHEMA')
    .map(containerDisplayName)
    .filter(Boolean)
  const untypedNames = path
    .filter((entry) => entry?.entity?.type !== 'CONTAINER')
    .map((entry) => entry?.name)
    .filter((value) => typeof value === 'string' && value.trim() && !value.startsWith('urn:li:'))
  const propertyName = typeof entity.properties?.name === 'string' && !entity.properties.name.startsWith('urn:li:')
    ? entity.properties.name
    : ''
  const entityName = typeof entity.name === 'string' && !entity.name.startsWith('urn:li:')
    ? entity.name
    : ''
  return {
    databaseName: databaseNames.length === 1
      ? databaseNames[0]
      : customProperty(entity, 'datariver.seed.database_name') || parts.at(-3) || '',
    schemaName: schemaNames.length === 1
      ? schemaNames[0]
      : untypedNames.length === 1 ? untypedNames[0] : parts.at(-2) || '',
    tableName: propertyName || entityName || parts.at(-1) || urnTail(entity.urn),
  }
}

function tagReferences(entity) {
  return deps.normalizeDatahubTagReferences(entity)
}

function publicDatahubAsset(asset) {
  if (!asset || typeof asset !== 'object' || Array.isArray(asset)) return asset
  return {
    ...asset,
    tag_references: (asset.tag_references || []).map((reference) => ({
      urn: reference.urn,
      name: reference.name,
      description: reference.description,
    })),
  }
}

function customPropertyReferences(properties) {
  return (properties?.customProperties || []).flatMap((item) => (
    typeof item?.key === 'string' && item.key.trim()
      && typeof item?.value === 'string' && item.value.trim()
      ? [{ key: item.key.trim(), value: item.value.trim() }]
      : []
  )).sort((left, right) => left.key.localeCompare(right.key) || left.value.localeCompare(right.value))
}

function structuredPropertyReferences(value) {
  return (value?.properties || []).flatMap((item) => {
    const property = item?.structuredProperty
    const urn = typeof property?.urn === 'string' ? property.urn : ''
    const qualifiedName = typeof property?.definition?.qualifiedName === 'string'
      ? property.definition.qualifiedName.trim()
      : ''
    if (!urn || !qualifiedName) return []
    const values = (item.values || []).flatMap((candidate) => {
      if (typeof candidate?.stringValue === 'string') return [candidate.stringValue]
      if (typeof candidate?.numberValue === 'number' && Number.isFinite(candidate.numberValue)) {
        return [candidate.numberValue]
      }
      return []
    })
    return [{
      urn,
      qualified_name: qualifiedName,
      display_name: property.definition?.displayName || qualifiedName,
      description: property.definition?.description || '',
      cardinality: property.definition?.cardinality || null,
      values,
      associated_urn: item.associatedUrn || null,
    }]
  }).sort((left, right) => left.urn.localeCompare(right.urn))
}

function datahubCreatedAt(properties) {
  const customProperties = new Map((properties?.customProperties || []).flatMap((item) => (
    typeof item?.key === 'string' && typeof item?.value === 'string'
      ? [[item.key.trim().toLocaleLowerCase(), item.value.trim()]]
      : []
  )))
  const candidates = [
    properties?.created,
    ...[
      'created_at', 'createdat', 'created_date', 'creation_date',
      'table_created_at', 'datariver.created_at',
    ].map((key) => customProperties.get(key)),
  ]
  for (const candidate of candidates) {
    if (typeof candidate === 'number' || (typeof candidate === 'string' && /^\d+$/.test(candidate.trim()))) {
      const raw = Number(candidate)
      const milliseconds = raw < 10_000_000_000 ? raw * 1_000 : raw
      const parsed = new Date(milliseconds)
      if (raw > 0 && Number.isFinite(parsed.getTime())) return parsed.toISOString()
      continue
    }
    if (typeof candidate === 'string' && candidate.trim()) {
      const parsed = new Date(candidate.trim())
      if (Number.isFinite(parsed.getTime())) return parsed.toISOString()
    }
  }
  return null
}

function datasetAsset(entity) {
  const identity = datasetIdentity(entity)
  const tagReferencesValue = tagReferences(entity)
  const tags = tagReferencesValue.map((item) => item.name)
  const classificationValues = tagReferencesValue
    .filter((reference) => reference.name.trim().toUpperCase().startsWith('CLASSIFICATION:'))
    .map((reference) => reference.name.slice(reference.name.indexOf(':') + 1).trim().toUpperCase())
  const classificationStatus = classificationValues.length === 0
    ? 'MISSING'
    : classificationValues.length > 1
      ? 'MULTIPLE'
      : deps.supportedDatahubClassifications.has(classificationValues[0]) ? 'EXACT' : 'INVALID'
  const exactClassification = classificationStatus === 'EXACT' ? classificationValues[0] : null
  const classification = exactClassification || ''
  const owner = urnTail(entity.ownership?.owners?.[0]?.owner?.urn) || 'DataHub'
  const domainEntity = entity.domain?.domain
  const domain = domainEntity?.properties?.name || urnTail(domainEntity?.urn) || ''
  const description = entity.editableProperties?.description || entity.properties?.description || ''
  const container = entity.container
  const platformInstance = entity.dataPlatformInstance
  return {
    id: entity.urn,
    external_urn: entity.urn,
    asset_type: entity.type || 'DATASET',
    dataset_kind: deps.datahubDatasetKind(entity),
    name: identity.tableName,
    qualified_name: entity.properties?.qualifiedName || identity.tableName,
    description,
    platform: entity.platform?.name || urnTail(entity.platform?.urn),
    database_name: identity.databaseName,
    schema_name: identity.schemaName,
    owner,
    domain,
    domain_reference: domainEntity?.urn ? {
      urn: domainEntity.urn,
      name: domain,
      description: domainEntity.properties?.description || '',
    } : null,
    container_reference: container?.urn ? {
      urn: container.urn,
      name: container.properties?.name || urnTail(container.urn),
      qualified_name: container.properties?.qualifiedName || '',
      description: container.properties?.description || '',
      custom_properties: customPropertyReferences(container.properties),
      sub_types: [...new Set(container.subTypes?.typeNames || [])].sort(),
    } : null,
    platform_instance_reference: platformInstance?.urn ? {
      urn: platformInstance.urn,
      instance_id: platformInstance.instanceId || '',
      name: platformInstance.properties?.name || platformInstance.instanceId || urnTail(platformInstance.urn),
      description: platformInstance.properties?.description || '',
      custom_properties: customPropertyReferences(platformInstance.properties),
    } : null,
    custom_properties: customPropertyReferences(entity.properties),
    structured_properties: structuredPropertyReferences(entity.structuredProperties),
    tags,
    tag_references: tagReferencesValue,
    terms: (entity.glossaryTerms?.terms || []).map((item) => item.term?.properties?.name || item.term?.name).filter(Boolean),
    term_references: (entity.glossaryTerms?.terms || []).flatMap((item) => (
      item.term?.urn && (item.term?.properties?.name || item.term?.name)
        ? [{
            urn: item.term.urn,
            name: item.term.properties?.name || item.term.name,
            description: item.term.properties?.description || '',
          }]
        : []
    )),
    fine_grained_lineages: (entity.fineGrainedLineages || []).map((item) => ({
      upstreams: (item.upstreams || []).map((reference) => ({ urn: reference.urn, path: reference.path })),
      downstreams: (item.downstreams || []).map((reference) => ({ urn: reference.urn, path: reference.path })),
      query: item.query || null,
      transform_operation: item.transformOperation || null,
    })),
    created_at: datahubCreatedAt(entity.properties),
    classification,
    classification_resolution: {
      status: classificationStatus,
      values: [...classificationValues],
      value: exactClassification,
    },
    lifecycle: 'ACTIVE',
    observed_at: new Date().toISOString(),
    matches: [],
  }
}

function catalogMeta({ projection = false } = {}) {
  const now = new Date().toISOString()
  const current = projection ? deps.inventorySnapshot?.projection : undefined
  return {
    observed_at: current?.observed_at || now,
    stale_at: current && deps.inventorySnapshot.expiresAt <= Date.now()
      ? new Date(deps.inventorySnapshot.expiresAt).toISOString()
      : null,
    projection_version: 1,
    policy_version: 'POC_LIVE_PROVIDER_V1',
    classification_policy_version: 1,
    authorization_generation: 1,
    ...(current ? {
      projection_source: deps.pocStateStore.configured.postgres
        ? 'POSTGRES_CURRENT_PROJECTION'
        : 'PROCESS_MEMORY_CURRENT_PROJECTION',
      source_generation: current.source_generation,
      refresh_state: deps.inventoryRefreshFailedAt ? 'DEGRADED_LAST_GOOD' : 'CURRENT_OR_REFRESHING',
      ...(deps.inventoryRefreshDiagnostic || current.refresh_diagnostics
        ? { inventory_refresh: deps.inventoryRefreshDiagnostic || current.refresh_diagnostics }
        : {}),
    } : {}),
  }
}

function pruneCursorEntries() {
  const now = Date.now()
  for (const [key, entry] of deps.cursorEntries) {
    if (entry.expiresAt <= now) deps.cursorEntries.delete(key)
  }
  while (deps.cursorEntries.size >= deps.maximumCursorEntries) {
    const oldest = deps.cursorEntries.keys().next().value
    if (!oldest) break
    deps.cursorEntries.delete(oldest)
  }
}

function issueCursor(scope, value) {
  pruneCursorEntries()
  const token = deps.randomUUID()
  deps.cursorEntries.set(token, { scope, value, expiresAt: Date.now() + deps.datahubCursorTtlMs })
  return token
}

function cursorValue(token, scope) {
  if (!token) return undefined
  pruneCursorEntries()
  const entry = deps.cursorEntries.get(token)
  if (!entry || entry.scope !== scope) {
    throw Object.assign(new Error('The POC cursor is invalid, expired or belongs to a different query.'), { statusCode: 400 })
  }
  return entry.value
}

async function datahubCatalogPage(providerCursor, signal, pageNumber, progressDiagnostic) {
  const input = {
    types: ['DATASET'],
    query: '*',
    count: 250,
    keepAlive: '1m',
    sortInput: { sortCriteria: [{ field: 'urn', sortOrder: 'ASCENDING' }] },
    searchFlags: { skipAggregates: true, skipHighlighting: true },
  }
  if (providerCursor) input.scrollId = providerCursor
  const pageStartedAt = Date.now()
  deps.inventoryRefreshDiagnostic = boundedInventoryDiagnostic({
    ...progressDiagnostic,
    phase: 'PAGE_FETCH',
    page_number: pageNumber,
    elapsed_ms: Date.now() - progressDiagnostic.started_at,
  })
  let data
  try {
    data = await datahubGraphql(deps.datahubEmbeddingInventoryQuery, { input }, 60_000, signal)
  } catch (error) {
    if (signal?.aborted || ['AbortError', 'TimeoutError'].includes(error?.name) && signal?.aborted) throw error
    const code = error?.providerFailureKind === 'GRAPHQL'
      ? 'PREP_DATAHUB_INVENTORY_GRAPHQL_FAILED'
      : error?.providerFailureKind === 'RESPONSE_JSON'
        ? 'PREP_DATAHUB_INVENTORY_CONTRACT_FAILED'
        : pageNumber === 1
          ? 'PREP_DATAHUB_INVENTORY_QUERY_FAILED'
          : 'PREP_DATAHUB_INVENTORY_PAGE_FAILED'
    throw inventoryFailure(code, 'PAGE_FETCH', 'DataHub inventory page retrieval failed.', {
      ...progressDiagnostic,
      page_number: pageNumber,
      elapsed_ms: Date.now() - progressDiagnostic.started_at,
      provider_http_class: error?.providerHttpClass,
    }, error)
  }
  const page = data?.scrollAcrossEntities
  if (!page || typeof page !== 'object' || !Array.isArray(page.searchResults)) {
    throw inventoryFailure(
      'PREP_DATAHUB_INVENTORY_CONTRACT_FAILED',
      'ENTITY_EXTRACTION',
      'DataHub inventory returned a malformed entity page.',
      {
        ...progressDiagnostic,
        page_number: pageNumber,
        extraction_reason: 'SEARCH_RESULT_ENVELOPE_INVALID',
        elapsed_ms: Date.now() - progressDiagnostic.started_at,
      },
    )
  }
  const searchResultEnvelopeCount = page.searchResults.length
  const pageDiagnostic = {
    ...progressDiagnostic,
    page_number: pageNumber,
    raw_search_result_count: progressDiagnostic.processed_count + searchResultEnvelopeCount,
    provider_metadata_count: page.count,
    search_result_envelope_count: searchResultEnvelopeCount,
    elapsed_ms: Date.now() - progressDiagnostic.started_at,
  }
  if (!Number.isSafeInteger(page.count) || page.count < 0) {
    throw inventoryFailure(
      'PREP_DATAHUB_INVENTORY_CONTRACT_FAILED',
      'ENTITY_EXTRACTION',
      'DataHub inventory returned invalid provider page-count metadata.',
      {
        ...pageDiagnostic,
        extraction_reason: 'PAGE_RESULT_COUNT_CONTRACT',
      },
    )
  }
  const items = []
  let skippedNoncurrentCount = 0
  const skippedNoncurrentReasons = Object.fromEntries(
    deps.DATAHUB_DATASET_CURRENTNESS_REASONS.map((reason) => [reason, 0]),
  )
  let normalizationMs = 0
  const extractionDiagnostic = (reason) => ({
    ...pageDiagnostic,
    extraction_reason: reason,
  })
  for (const result of page.searchResults) {
    if (!result || typeof result !== 'object' || Array.isArray(result)) {
      throw inventoryFailure(
        'PREP_DATAHUB_INVENTORY_CONTRACT_FAILED',
        'ENTITY_EXTRACTION',
        'DataHub inventory contains a malformed SearchResult envelope.',
        extractionDiagnostic('SEARCH_RESULT_ENVELOPE_INVALID'),
      )
    }
    const entity = result?.entity
    if (entity === null || entity === undefined) {
      throw inventoryFailure(
        'PREP_DATAHUB_INVENTORY_CONTRACT_FAILED',
        'ENTITY_EXTRACTION',
        'DataHub inventory contains a SearchResult without its required entity.',
        extractionDiagnostic('SEARCH_RESULT_ENTITY_ABSENT'),
      )
    }
    if (typeof entity !== 'object' || Array.isArray(entity) || entity.type !== 'DATASET') {
      throw inventoryFailure(
        'PREP_DATAHUB_INVENTORY_CONTRACT_FAILED',
        'ENTITY_EXTRACTION',
        'DataHub inventory contains a SearchResult with an invalid entity type.',
        extractionDiagnostic('SEARCH_RESULT_ENTITY_TYPE_INVALID'),
      )
    }
    if (!deps.isCanonicalDatahubDatasetUrn(entity.urn)) {
      throw inventoryFailure(
        'PREP_DATAHUB_INVENTORY_CONTRACT_FAILED',
        'ENTITY_EXTRACTION',
        'DataHub inventory contains a Dataset without a canonical identity.',
        extractionDiagnostic('SEARCH_RESULT_DATASET_URN_INVALID'),
      )
    }
    const currentness = deps.classifyCurrentDatahubDataset(entity, entity.urn)
    if (currentness.reason === 'DATASET_CURRENTNESS_SIGNAL_INVALID') {
      throw inventoryFailure(
        'PREP_DATAHUB_INVENTORY_CONTRACT_FAILED',
        'ENTITY_EXTRACTION',
        'DataHub inventory contains malformed Dataset currentness signals.',
        extractionDiagnostic('DATASET_CURRENTNESS_SIGNAL_INVALID'),
      )
    }
    if (!currentness.current) {
      skippedNoncurrentCount += 1
      skippedNoncurrentReasons[currentness.reason] += 1
      continue
    }
    const normalizationStartedAt = Date.now()
    try {
      items.push(detailedDatasetAsset(entity))
    } catch (error) {
      throw inventoryFailure(
        'PREP_DATAHUB_INVENTORY_NORMALIZATION_FAILED',
        'ENTITY_NORMALIZATION',
        'DataHub inventory Dataset normalization failed.',
        pageDiagnostic,
        error,
      )
    } finally {
      normalizationMs += Date.now() - normalizationStartedAt
    }
  }
  const rawNextProviderCursor = page?.nextScrollId
  if (rawNextProviderCursor !== null && rawNextProviderCursor !== undefined
    && (typeof rawNextProviderCursor !== 'string' || !rawNextProviderCursor)) {
    throw inventoryFailure(
      'PREP_DATAHUB_INVENTORY_CONTRACT_FAILED',
      'INVENTORY_VALIDATION',
      'DataHub inventory returned a malformed scroll cursor.',
      { ...progressDiagnostic, page_number: pageNumber, elapsed_ms: Date.now() - progressDiagnostic.started_at },
    )
  }
  const nextProviderCursor = rawNextProviderCursor || undefined
  if (nextProviderCursor && nextProviderCursor === providerCursor) {
    throw inventoryFailure(
      'PREP_DATAHUB_INVENTORY_CONTRACT_FAILED',
      'INVENTORY_VALIDATION',
      'DataHub inventory returned a repeated scroll cursor.',
      { ...progressDiagnostic, page_number: pageNumber, elapsed_ms: Date.now() - progressDiagnostic.started_at },
    )
  }
  return {
    items,
    total: page.total,
    rawCount: searchResultEnvelopeCount,
    providerMetadataCount: page.count,
    searchResultEnvelopeCount,
    skippedNoncurrentCount,
    skippedNoncurrentReasons,
    unresolvedSearchResultCount: 0,
    nextProviderCursor,
    pageFetchMs: Date.now() - pageStartedAt,
    normalizationMs,
  }
}

async function datahubInventory({ signal = deps.serverBackgroundAbortController?.signal } = {}) {
  const now = Date.now()
  if (deps.inventorySnapshot?.expiresAt > now) return deps.inventorySnapshot.items
  if (!deps.inventorySnapshot) {
    const stored = await storedDatahubInventory()
    if (stored) deps.inventorySnapshot = inventorySnapshotFrom(stored)
  }
  if (deps.inventorySnapshot) {
    if (deps.inventorySnapshot.expiresAt <= now && deps.inventoryRefreshRetryAt <= now) {
      void startDatahubInventoryRefresh({ signal }).catch(() => undefined)
    }
    return deps.inventorySnapshot.items
  }
  if (!deps.inventoryRefreshPromise && deps.inventoryRefreshRetryAt > now) {
    if (deps.inventoryRefreshLastError?.inventoryTerminal) throw deps.inventoryRefreshLastError
    throw Object.assign(new Error('The Catalog projection refresh recently failed; retry later.'), {
      statusCode: 503,
      code: deps.inventoryRefreshLastError?.code || 'PREP_DATAHUB_INVENTORY_PAGE_FAILED',
      inventoryDiagnostic: deps.inventoryRefreshLastError?.inventoryDiagnostic || deps.inventoryRefreshDiagnostic,
    })
  }
  const refresh = startDatahubInventoryRefresh({ signal })
  if (deps.pocStateStore.configured.postgres) {
    void refresh.catch(() => undefined)
    throw Object.assign(new Error('The PostgreSQL Catalog projection is warming; retry shortly.'), {
      statusCode: 503,
      code: 'DATAHUB_INVENTORY_WARMING',
      inventoryDiagnostic: deps.inventoryRefreshDiagnostic,
    })
  }
  return (await refresh).items
}

async function currentDatahubInventory({ signal = deps.serverBackgroundAbortController?.signal } = {}) {
  if (!deps.datahub) {
    throw Object.assign(new Error('DataHub is not configured for current Table identity validation.'), { statusCode: 503 })
  }
  if (deps.inventoryRefreshPromise) return (await deps.inventoryRefreshPromise).items
  return (await startDatahubInventoryRefresh({ signal, deferSemanticIndex: true })).items
}

async function datahubEmbeddingInventory(options) {
  return datahubInventory(options)
}

async function datahubHierarchyInventory() {
  return datahubInventory()
}

function validDatahubInventory(value) {
  return value?.projection_version === 1
    && value.source_scope === deps.datahubCacheScope
    && typeof value.source_generation === 'string'
    && Number.isFinite(Date.parse(value.observed_at))
    && Array.isArray(value.items)
    && value.items.every((item) => item && typeof item.id === 'string')
}

function inventorySnapshotFrom(projection) {
  const observedAt = Date.parse(projection.observed_at)
  return {
    items: projection.items,
    projection,
    expiresAt: observedAt + deps.datahubInventoryTtlMs,
  }
}

async function storedDatahubInventory() {
  if (deps.pocStateStore.configured.postgres) {
    try {
      const stored = await deps.pocStateStore.read(deps.datahubInventoryStateScope)
      return validDatahubInventory(stored.value) ? stored.value : undefined
    } catch {
      // A valid Redis value is only a bounded availability fallback when the
      // authoritative PostgreSQL projection cannot be read at all.
    }
  }
  try {
    const cached = await deps.pocStateStore.cacheGet(deps.datahubInventoryCacheKey)
    if (validDatahubInventory(cached)) return cached
  } catch {
    // Redis is optional; PostgreSQL is the durable current read model.
  }
  if (deps.pocStateStore.configured.postgres) return undefined
  const stored = await deps.pocStateStore.read(deps.datahubInventoryStateScope)
  return validDatahubInventory(stored.value) ? stored.value : undefined
}

function datahubInventoryProjection(items, refreshDiagnostics) {
  const sorted = [...items].sort((left, right) => left.id.localeCompare(right.id))
  const sourceGeneration = deps.sha256(sorted.map((item) => {
    const generationItem = { ...item }
    delete generationItem.observed_at
    delete generationItem.matches
    return `${item.id}:${canonicalHash(generationItem)}`
  }).join('\n'))
  return {
    projection_version: 1,
    source_scope: deps.datahubCacheScope,
    source_generation: sourceGeneration,
    observed_at: new Date().toISOString(),
    items: sorted,
    ...(refreshDiagnostics ? { refresh_diagnostics: refreshDiagnostics } : {}),
  }
}

function boundedInventoryDiagnostic(value = {}) {
  const result = {
    phase: deps.inventoryDiagnosticPhases.has(value.phase) ? value.phase : 'INVENTORY_VALIDATION',
    page_number: Number.isSafeInteger(value.page_number) && value.page_number >= 0 ? value.page_number : 0,
    processed_count: Number.isSafeInteger(value.processed_count) && value.processed_count >= 0 ? value.processed_count : 0,
    expected_total: Number.isSafeInteger(value.expected_total) && value.expected_total >= 0 ? value.expected_total : null,
    normalized_count: Number.isSafeInteger(value.normalized_count) && value.normalized_count >= 0 ? value.normalized_count : 0,
    skipped_noncurrent_count: Number.isSafeInteger(value.skipped_noncurrent_count) && value.skipped_noncurrent_count >= 0
      ? value.skipped_noncurrent_count : 0,
    duplicate_count: Number.isSafeInteger(value.duplicate_count) && value.duplicate_count >= 0 ? value.duplicate_count : 0,
    unresolved_search_result_count: Number.isSafeInteger(value.unresolved_search_result_count)
      && value.unresolved_search_result_count >= 0 ? value.unresolved_search_result_count : 0,
    elapsed_ms: Number.isSafeInteger(value.elapsed_ms) && value.elapsed_ms >= 0 ? value.elapsed_ms : 0,
    error_class: typeof value.error_class === 'string' && /^[A-Z0-9_]{1,80}$/.test(value.error_class)
      ? value.error_class : null,
    terminal: value.terminal === true,
  }
  if (Number.isSafeInteger(value.raw_search_result_count) && value.raw_search_result_count >= 0) {
    result.raw_search_result_count = value.raw_search_result_count
  }
  if (Number.isSafeInteger(value.provider_metadata_count) && value.provider_metadata_count >= 0) {
    result.provider_metadata_count = value.provider_metadata_count
  }
  if (Number.isSafeInteger(value.search_result_envelope_count) && value.search_result_envelope_count >= 0) {
    result.search_result_envelope_count = value.search_result_envelope_count
  }
  const extractionReasons = new Set([
    'PAGE_RESULT_COUNT_CONTRACT',
    'SEARCH_RESULT_ENVELOPE_INVALID',
    'SEARCH_RESULT_ENTITY_ABSENT',
    'SEARCH_RESULT_ENTITY_TYPE_INVALID',
    'SEARCH_RESULT_DATASET_URN_INVALID',
    'DATASET_CURRENTNESS_SIGNAL_INVALID',
    'DATASET_CURRENT_ASPECTS_ABSENT',
  ])
  if (extractionReasons.has(value.extraction_reason)) result.extraction_reason = value.extraction_reason
  const filteredNoncurrentReasons = {}
  for (const reason of deps.DATAHUB_DATASET_CURRENTNESS_REASONS) {
    const count = value.filtered_noncurrent_reasons?.[reason]
    if (Number.isSafeInteger(count) && count > 0) filteredNoncurrentReasons[reason] = count
  }
  if (Object.keys(filteredNoncurrentReasons).length > 0) {
    result.filtered_noncurrent_reasons = filteredNoncurrentReasons
  }
  if (typeof value.provider_http_class === 'string' && /^[1-5]xx$/.test(value.provider_http_class)) {
    result.provider_http_class = value.provider_http_class
  }
  if (Number.isSafeInteger(value.page_fetch_ms) && value.page_fetch_ms >= 0) result.page_fetch_ms = value.page_fetch_ms
  if (Number.isSafeInteger(value.normalization_ms) && value.normalization_ms >= 0) result.normalization_ms = value.normalization_ms
  if (Number.isSafeInteger(value.snapshot_persistence_ms) && value.snapshot_persistence_ms >= 0) {
    result.snapshot_persistence_ms = value.snapshot_persistence_ms
  }
  return result
}

function inventoryFailure(code, phase, message, diagnostic = {}, cause) {
  const terminal = ![
    'PREP_DATAHUB_INVENTORY_QUERY_FAILED',
    'PREP_DATAHUB_INVENTORY_PAGE_FAILED',
  ].includes(code)
  const safeDiagnostic = boundedInventoryDiagnostic({
    ...diagnostic,
    phase,
    terminal,
    error_class: code,
  })
  return Object.assign(new Error(message, cause ? { cause } : undefined), {
    statusCode: 502,
    code,
    inventoryTerminal: terminal,
    inventoryDiagnostic: safeDiagnostic,
  })
}

function stableInventoryItemHash(item) {
  const stable = { ...item }
  delete stable.observed_at
  delete stable.matches
  return canonicalHash(stable)
}

function startDatahubInventoryRefresh({
  signal = deps.serverBackgroundAbortController?.signal,
  deferSemanticIndex = false,
} = {}) {
  if (deps.inventoryRefreshPromise) return deps.inventoryRefreshPromise
  if (deps.backgroundLaunchesStopped) {
    return Promise.reject(Object.assign(new Error('The POC background lifecycle is stopping.'), { name: 'AbortError' }))
  }
  signal?.throwIfAborted()
  deps.inventoryRefreshPromise = (async () => {
    const startedAt = Date.now()
    const items = []
    const observed = new Map()
    const providerCursors = new Set()
    let providerTotal
    let providerCursor
    let terminalConfirmationPending = false
    let processedCount = 0
    let skippedNoncurrentCount = 0
    const skippedNoncurrentReasons = Object.fromEntries(
      deps.DATAHUB_DATASET_CURRENTNESS_REASONS.map((reason) => [reason, 0]),
    )
    let duplicateCount = 0
    let unresolvedSearchResultCount = 0
    let providerMetadataCount = 0
    let searchResultEnvelopeCount = 0
    let pageFetchMs = 0
    let normalizationMs = 0
    let pageCount = 0
    const progressDiagnostic = () => ({
      started_at: startedAt,
      processed_count: processedCount,
      raw_search_result_count: processedCount,
      expected_total: providerTotal,
      normalized_count: observed.size,
      skipped_noncurrent_count: skippedNoncurrentCount,
      filtered_noncurrent_reasons: skippedNoncurrentReasons,
      duplicate_count: duplicateCount,
      unresolved_search_result_count: unresolvedSearchResultCount,
      provider_metadata_count: providerMetadataCount,
      search_result_envelope_count: searchResultEnvelopeCount,
    })
    const commit = async () => {
      signal?.throwIfAborted()
      const accountingTotal = observed.size + skippedNoncurrentCount + duplicateCount + unresolvedSearchResultCount
      if (processedCount !== providerTotal || processedCount !== accountingTotal) {
        throw inventoryFailure(
          'PREP_DATAHUB_INVENTORY_CONTRACT_FAILED',
          'INVENTORY_VALIDATION',
          'DataHub inventory reconciliation accounting is incomplete.',
          { ...progressDiagnostic(), page_number: pageCount, elapsed_ms: Date.now() - startedAt },
        )
      }
      const refreshDiagnostics = boundedInventoryDiagnostic({
        ...progressDiagnostic(),
        phase: 'SNAPSHOT_PERSISTENCE',
        page_number: pageCount,
        page_fetch_ms: pageFetchMs,
        normalization_ms: normalizationMs,
        elapsed_ms: Date.now() - startedAt,
      })
      deps.inventoryRefreshDiagnostic = refreshDiagnostics
      let projection
      try {
        projection = datahubInventoryProjection(items, refreshDiagnostics)
      } catch (error) {
        throw inventoryFailure(
          'PREP_DATAHUB_INVENTORY_PROMOTION_FAILED',
          'SNAPSHOT_PROMOTION',
          'DataHub inventory projection generation failed.',
          { ...progressDiagnostic(), page_number: pageCount, elapsed_ms: Date.now() - startedAt },
          error,
        )
      }
      const persistenceStartedAt = Date.now()
      try {
        await deps.pocStateStore.write(deps.datahubInventoryStateScope, projection)
      } catch (error) {
        throw inventoryFailure(
          'PREP_DATAHUB_INVENTORY_PROMOTION_FAILED',
          'SNAPSHOT_PERSISTENCE',
          'DataHub inventory projection persistence failed.',
          {
            ...progressDiagnostic(),
            page_number: pageCount,
            elapsed_ms: Date.now() - startedAt,
            snapshot_persistence_ms: Date.now() - persistenceStartedAt,
          },
          error,
        )
      }
      deps.inventorySnapshot = inventorySnapshotFrom(projection)
      deps.inventoryRefreshDiagnostic = boundedInventoryDiagnostic({
        ...progressDiagnostic(),
        phase: 'SNAPSHOT_PROMOTION',
        page_number: pageCount,
        page_fetch_ms: pageFetchMs,
        normalization_ms: normalizationMs,
        snapshot_persistence_ms: Date.now() - persistenceStartedAt,
        elapsed_ms: Date.now() - startedAt,
      })
      deps.inventoryRefreshFailedAt = undefined
      deps.inventoryRefreshRetryAt = 0
      deps.inventoryRefreshLastError = undefined
      try {
        await deps.pocStateStore.cacheSet(deps.datahubInventoryCacheKey, projection, deps.datahubInventoryTtlMs / 1_000)
      } catch { /* Redis is optional. */ }
      if (deps.llm.embedding && !deferSemanticIndex) {
        deps.catalogEmbeddingSnapshot = undefined
        deps.catalogEmbeddingRefreshStartedAt = 0
        deps.queueCatalogEmbeddingRefresh()
      }
      return deps.inventorySnapshot
    }
    for (let pageNumber = 0; pageNumber < deps.maximumInventoryPages; pageNumber += 1) {
      const pageOrdinal = pageNumber + 1
      const page = await datahubCatalogPage(providerCursor, signal, pageOrdinal, progressDiagnostic())
      pageCount = pageOrdinal
      pageFetchMs += page.pageFetchMs
      normalizationMs += page.normalizationMs
      providerMetadataCount = page.providerMetadataCount
      searchResultEnvelopeCount = page.searchResultEnvelopeCount
      if (!Number.isSafeInteger(page.total) || page.total < 0) {
        throw inventoryFailure(
          'PREP_DATAHUB_INVENTORY_CONTRACT_FAILED',
          'INVENTORY_VALIDATION',
          'DataHub inventory returned a malformed total.',
          { ...progressDiagnostic(), page_number: pageOrdinal, elapsed_ms: Date.now() - startedAt },
        )
      }
      if (providerTotal === undefined) providerTotal = page.total
      if (page.total !== providerTotal) {
        throw inventoryFailure(
          'PREP_DATAHUB_INVENTORY_CONTRACT_FAILED',
          'INVENTORY_VALIDATION',
          'DataHub changed its inventory total during the scroll.',
          { ...progressDiagnostic(), page_number: pageOrdinal, elapsed_ms: Date.now() - startedAt },
        )
      }
      processedCount += page.rawCount
      unresolvedSearchResultCount += page.unresolvedSearchResultCount
      skippedNoncurrentCount += page.skippedNoncurrentCount
      for (const reason of deps.DATAHUB_DATASET_CURRENTNESS_REASONS) {
        skippedNoncurrentReasons[reason] += page.skippedNoncurrentReasons[reason]
      }
      for (const item of page.items) {
        if (typeof item.id !== 'string' || !item.id) {
          throw inventoryFailure(
            'PREP_DATAHUB_INVENTORY_NORMALIZATION_FAILED',
            'ENTITY_NORMALIZATION',
            'DataHub inventory normalization produced an invalid identity.',
            { ...progressDiagnostic(), page_number: pageOrdinal, elapsed_ms: Date.now() - startedAt },
          )
        }
        const itemHash = stableInventoryItemHash(item)
        if (!observed.has(item.id)) {
          observed.set(item.id, itemHash)
          items.push(item)
        } else {
          duplicateCount += 1
          if (observed.get(item.id) !== itemHash) {
            throw inventoryFailure(
              'PREP_DATAHUB_INVENTORY_CONTRACT_FAILED',
              'DEDUPLICATION',
              'DataHub inventory returned conflicting metadata for one Dataset identity.',
              { ...progressDiagnostic(), page_number: pageOrdinal, elapsed_ms: Date.now() - startedAt },
            )
          }
        }
      }
      deps.inventoryRefreshDiagnostic = boundedInventoryDiagnostic({
        ...progressDiagnostic(),
        phase: 'INVENTORY_VALIDATION',
        page_number: pageOrdinal,
        page_fetch_ms: pageFetchMs,
        normalization_ms: normalizationMs,
        elapsed_ms: Date.now() - startedAt,
      })
      const accountingTotal = observed.size + skippedNoncurrentCount + duplicateCount + unresolvedSearchResultCount
      if (processedCount > providerTotal || processedCount !== accountingTotal) {
        throw inventoryFailure(
          'PREP_DATAHUB_INVENTORY_CONTRACT_FAILED',
          'INVENTORY_VALIDATION',
          'DataHub inventory reconciliation accounting exceeded or lost provider results.',
          { ...progressDiagnostic(), page_number: pageOrdinal, elapsed_ms: Date.now() - startedAt },
        )
      }
      if (page.nextProviderCursor) {
        if (providerCursors.has(page.nextProviderCursor)) {
          throw inventoryFailure(
            'PREP_DATAHUB_INVENTORY_CONTRACT_FAILED',
            'INVENTORY_VALIDATION',
            'DataHub inventory returned a repeated scroll cursor.',
            { ...progressDiagnostic(), page_number: pageOrdinal, elapsed_ms: Date.now() - startedAt },
          )
        }
        providerCursors.add(page.nextProviderCursor)
      }
      if (terminalConfirmationPending) {
        if (page.rawCount !== 0 || page.nextProviderCursor) {
          throw inventoryFailure(
            'PREP_DATAHUB_INVENTORY_CONTRACT_FAILED',
            'INVENTORY_VALIDATION',
            'DataHub inventory returned an invalid terminal confirmation page.',
            { ...progressDiagnostic(), page_number: pageOrdinal, elapsed_ms: Date.now() - startedAt },
          )
        }
        return commit()
      }
      if (!page.nextProviderCursor) {
        if (processedCount !== providerTotal) {
          throw inventoryFailure(
            'PREP_DATAHUB_INVENTORY_CONTRACT_FAILED',
            'INVENTORY_VALIDATION',
            'DataHub ended its scroll before the complete raw inventory was observed.',
            { ...progressDiagnostic(), page_number: pageOrdinal, elapsed_ms: Date.now() - startedAt },
          )
        }
        return commit()
      }
      if (processedCount === providerTotal) terminalConfirmationPending = true
      providerCursor = page.nextProviderCursor
    }
    throw inventoryFailure(
      'PREP_DATAHUB_INVENTORY_CONTRACT_FAILED',
      'INVENTORY_VALIDATION',
      'DataHub inventory exceeded the bounded reconciliation page safety limit.',
      { ...progressDiagnostic(), page_number: pageCount, elapsed_ms: Date.now() - startedAt },
    )
  })().catch((error) => {
    deps.inventoryRefreshFailedAt = new Date().toISOString()
    deps.inventoryRefreshRetryAt = Date.now() + deps.datahubInventoryFailureRetryMs
    deps.inventoryRefreshLastError = error
    deps.inventoryRefreshDiagnostic = error?.inventoryDiagnostic || boundedInventoryDiagnostic({
      phase: 'INVENTORY_VALIDATION',
      error_class: 'PREP_DATAHUB_INVENTORY_CONTRACT_FAILED',
      terminal: true,
    })
    throw error
  }).finally(() => {
    deps.inventoryRefreshPromise = undefined
  })
  return deps.inventoryRefreshPromise
}

async function datahubEntity(urn) {
  const cacheKey = datahubAssetCacheKey(urn)
  try {
    const cached = await deps.pocStateStore.cacheGet(cacheKey)
    if (cached && typeof cached === 'object') return cached
  } catch { /* optional cache */ }
  const data = await datahubGraphql(deps.datahubAssetQuery, { urn })
  if (data.entity) {
    try { await deps.pocStateStore.cacheSet(cacheKey, data.entity, 60) } catch { /* optional cache */ }
  }
  return data.entity
}

async function datahubCatalogDetailBaseEntity(urn) {
  const cacheKey = datahubAssetBaseCacheKey(urn)
  try {
    const cached = await deps.pocStateStore.cacheGet(cacheKey)
    if (cached && typeof cached === 'object') return cached
  } catch { /* optional cache */ }
  const data = await datahubGraphql(deps.datahubCatalogDetailBaseQuery, { urn })
  if (data.entity) {
    try { await deps.pocStateStore.cacheSet(cacheKey, data.entity, 60) } catch { /* optional cache */ }
  }
  return data.entity
}

async function currentDatahubTables(tableUrns, { signal, includeClassificationErrors = false } = {}) {
  if (!Array.isArray(tableUrns) || tableUrns.length < 1 || tableUrns.length > 2_000) {
    throw new Error('Current Table confirmation requires 1-2000 identities.')
  }
  const requested = [...new Set(tableUrns)]
  if (requested.length !== tableUrns.length) throw new Error('Current Table confirmation identities must be unique.')
  const confirmed = []
  for (let offset = 0; offset < requested.length; offset += 250) {
    const batch = requested.slice(offset, offset + 250)
    const data = await datahubGraphql(deps.datahubCurrentEntitiesQuery, { urns: batch }, 30_000, signal)
    if (!Array.isArray(data?.entities) || data.entities.length !== batch.length) {
      throw new Error('DataHub returned an invalid current entity confirmation.')
    }
    data.entities.forEach((entity, index) => {
      if (!deps.isCurrentDatahubTable(entity, batch[index], { entityExists: entity !== null })) return
      const references = tagReferences(entity)
      const classificationTags = references.filter((reference) => (
        reference.name.trim().toUpperCase().startsWith('CLASSIFICATION:')
      ))
      const classificationValues = classificationTags.map((reference) => reference.name
        .slice(reference.name.indexOf(':') + 1).trim().toUpperCase())
      const classificationStatus = classificationValues.length === 0
        ? 'MISSING'
        : classificationValues.length > 1
          ? 'MULTIPLE'
          : deps.supportedDatahubClassifications.has(classificationValues[0]) ? 'EXACT' : 'INVALID'
      const classification = classificationStatus === 'EXACT' ? classificationValues[0] : null
      confirmed.push({
        id: entity.urn,
        dataset_kind: 'TABLE',
        // Retained only for CR/admin business snapshots and display compatibility.
        // Table authorization never consumes this free-form TAG-derived value.
        security_grade: deps.legacyTableTagGrade({ tag_references: references }),
        classification,
        classification_status: classificationStatus,
        classification_values: classificationValues,
        schema_field_paths: datahubSchemaFields(entity).map((field) => field.fieldPath),
      })
    })
  }
  void includeClassificationErrors
  return confirmed
}

function catalogSearchFields(searchParameters) {
  const raw = deps.boundedString(searchParameters.get('search_fields'), 100).trim()
  if (!raw) return [...deps.catalogSearchFieldNames]
  const fields = [...new Set(raw.split(',').map((value) => value.trim().toUpperCase()).filter(Boolean))]
  if (!fields.length || fields.some((field) => !deps.catalogSearchFieldNames.has(field))) {
    throw Object.assign(new Error('Catalog search fields are invalid.'), { statusCode: 400 })
  }
  return fields
}

function catalogQueryTerms(query) {
  const values = String(query || '').trim().split(/\s+/u).filter(Boolean)
  const terms = []
  const observed = new Set()
  for (const value of values) {
    if (value.length > deps.maximumCatalogQueryTermLength) {
      throw Object.assign(new Error(`Each catalog search term must be at most ${deps.maximumCatalogQueryTermLength} characters.`), { statusCode: 400 })
    }
    const folded = value.normalize('NFKC').toLocaleLowerCase()
    if (!observed.has(folded)) {
      observed.add(folded)
      terms.push({ value, folded })
    }
  }
  if (terms.length > deps.maximumCatalogQueryTerms) {
    throw Object.assign(new Error(`Catalog search accepts at most ${deps.maximumCatalogQueryTerms} unique terms.`), { statusCode: 400 })
  }
  return terms
}

function catalogSearchValues(asset, fields) {
  const enabled = new Set(fields)
  const columnNames = (asset.schema_fields || [])
    .map((field) => field?.fieldPath || field?.label)
    .filter((value) => typeof value === 'string' && value.trim())
  return [
    ['NAME', enabled.has('TABLE') ? asset.name : ''],
    ['DESCRIPTION', enabled.has('DESCRIPTION') ? asset.description : ''],
    ['SCHEMA', enabled.has('SCHEMA') ? asset.schema_name : ''],
    ['COLUMN', enabled.has('COLUMN') ? columnNames.join(' · ') : ''],
    ['TAG', enabled.has('TAG') ? (asset.tags || []).join(' · ') : ''],
    ['TERM', enabled.has('TERM') ? (asset.terms || []).join(' · ') : ''],
  ].filter(([, value]) => typeof value === 'string' && value.trim())
}

function catalogMatchContext(value, folded, matchedTerm) {
  if (value.length <= 240) return value
  const position = folded.indexOf(matchedTerm)
  const start = Math.max(0, Math.min(value.length - 238, position - Math.floor((238 - matchedTerm.length) / 2)))
  const end = Math.min(value.length, start + 238)
  return `${start > 0 ? '…' : ''}${value.slice(start, end)}${end < value.length ? '…' : ''}`
}

function catalogMatchFragments(asset, query, fields) {
  const terms = catalogQueryTerms(query)
  if (!terms.length) return []
  const fragments = []
  for (const [field, text] of catalogSearchValues(asset, fields)) {
    const folded = text.normalize('NFKC').toLocaleLowerCase()
    const matched = terms.filter((term) => folded.includes(term.folded))
    if (!matched.length) continue
    if (text.length <= 240) {
      fragments.push({ field, text, matched_terms: matched.map((term) => term.value) })
      continue
    }
    for (const term of matched) {
      fragments.push({
        field,
        text: catalogMatchContext(text, folded, term.folded),
        matched_terms: [term.value],
      })
    }
  }
  return fragments
}

function assetMatches(asset, searchParameters, fields = catalogSearchFields(searchParameters)) {
  const query = deps.boundedString(searchParameters.get('q'), 500, '*').trim()
  const terms = query && query !== '*' ? catalogQueryTerms(query) : []
  const searchable = catalogSearchValues(asset, fields)
    .map(([, value]) => value.normalize('NFKC').toLocaleLowerCase())
  const exact = (parameter, value) => {
    const expected = searchParameters.get(parameter)
    return !expected || expected === value
  }
  return terms.every((term) => searchable.some((value) => value.includes(term.folded)))
    && exact('asset_type', asset.asset_type)
    && exact('platform', asset.platform)
    && exact('database', asset.database_name)
    && exact('schema', asset.schema_name)
    && exact('domain', asset.domain)
    && exact('classification', asset.classification)
    && exact('lifecycle', asset.lifecycle)
}

function parameterScope(prefix, searchParameters, keys) {
  return `${prefix}:${keys.map((key) => `${key}=${searchParameters.get(key) || ''}`).join('&')}`
}

function offsetPage(items, searchParameters, scope, defaultLimit = 100, maxLimit = 100) {
  const requested = Number(searchParameters.get('limit') || defaultLimit)
  const boundedMaxLimit = Math.min(200, Math.max(1, Number.isInteger(maxLimit) ? maxLimit : 100))
  const limit = Math.min(boundedMaxLimit, Math.max(1, Number.isFinite(requested) ? requested : defaultLimit))
  const offset = Number(cursorValue(searchParameters.get('cursor'), scope) ?? 0)
  if (!Number.isInteger(offset) || offset < 0 || offset > items.length) {
    throw Object.assign(new Error('The POC cursor offset is invalid.'), { statusCode: 400 })
  }
  const pageItems = items.slice(offset, offset + limit)
  const nextOffset = offset + pageItems.length
  return {
    items: pageItems,
    page: { next_cursor: nextOffset < items.length ? issueCursor(scope, nextOffset) : null, limit },
  }
}

async function datahubCatalogSelection(searchParameters, principal, feature = 'catalog', { tableOnly = false } = {}) {
  const query = deps.boundedString(searchParameters.get('q'), 500, '*') || '*'
  const requested = Number(searchParameters.get('limit') || 50)
  const limit = Math.min(100, Math.max(1, Number.isFinite(requested) ? requested : 50))
  const filterKeys = ['asset_type', 'platform', 'database', 'schema', 'domain', 'classification', 'lifecycle']
  const fields = catalogSearchFields(searchParameters)
  const requestedUrns = searchParameters.getAll('urn')
  if (requestedUrns.length > 100 || requestedUrns.some((urn) => (
    !urn.startsWith('urn:li:dataset:') || urn.length > 4_096
  ))) {
    throw Object.assign(new Error('Catalog exact URN scope is invalid.'), { statusCode: 400 })
  }
  const exactUrns = new Set(requestedUrns)
  const inventory = await datahubInventory()
  const authorizationStartedAt = Date.now()
  let allItems
  try {
    allItems = (principal ? deps.filterAssetsForPrincipal(principal, inventory, feature) : inventory)
      .filter((item) => !tableOnly || item.dataset_kind === 'TABLE')
      .filter((item) => !exactUrns.size || exactUrns.has(item.id))
      .filter((item) => assetMatches(item, searchParameters, fields))
      .map((item) => publicDatahubAsset({ ...item, matches: catalogMatchFragments(item, query, fields) }))
      .sort((left, right) => left.name.localeCompare(right.name) || left.id.localeCompare(right.id))
  } catch (error) {
    error.inventoryDiagnostic ||= boundedInventoryDiagnostic({
      phase: 'AUTHORIZATION_PROJECTION',
      processed_count: inventory.length,
      normalized_count: 0,
      elapsed_ms: Date.now() - authorizationStartedAt,
      error_class: 'AUTHORIZATION_PROJECTION_FAILED',
      terminal: true,
    })
    throw error
  }
  const scope = `${parameterScope('catalog-projection', searchParameters, ['q', ...filterKeys, 'search_fields', 'limit'])}:urns=${deps.sha256([...exactUrns].sort().join('\n'))}`
  return {
    allItems,
    scope,
    limit,
    requestDiagnostic: boundedInventoryDiagnostic({
      phase: 'AUTHORIZATION_PROJECTION',
      processed_count: inventory.length,
      normalized_count: allItems.length,
      elapsed_ms: Date.now() - authorizationStartedAt,
    }),
  }
}

async function datahubCatalog(searchParameters, principal, feature = 'catalog', options = {}) {
  const responseStartedAt = Date.now()
  const { allItems, scope, limit, requestDiagnostic } = await datahubCatalogSelection(
    searchParameters, principal, feature, options,
  )
  let page
  try {
    page = offsetPage(allItems, searchParameters, scope, limit)
  } catch (error) {
    error.inventoryDiagnostic ||= boundedInventoryDiagnostic({
      phase: 'RESPONSE_BUILD',
      processed_count: allItems.length,
      normalized_count: 0,
      elapsed_ms: Date.now() - responseStartedAt,
      error_class: 'RESPONSE_BUILD_FAILED',
      terminal: true,
    })
    throw error
  }
  return {
    ...page,
    total: allItems.length,
    total_exact: true,
    meta: {
      ...catalogMeta({ projection: true }),
      catalog_request: boundedInventoryDiagnostic({
        ...requestDiagnostic,
        phase: 'RESPONSE_BUILD',
        processed_count: allItems.length,
        normalized_count: page.items.length,
        elapsed_ms: Date.now() - responseStartedAt,
      }),
    },
    match_mode: 'ALL',
  }
}

async function datahubCatalogLocate(searchParameters, principal) {
  const assetId = deps.boundedString(searchParameters.get('asset_id'), 4_096)
  if (!assetId.startsWith('urn:li:dataset:')) {
    throw Object.assign(new Error('Catalog locate requires a canonical DataHub Dataset URN.'), { statusCode: 400 })
  }
  const { allItems, scope, limit } = await datahubCatalogSelection(searchParameters, principal)
  const itemIndex = allItems.findIndex((item) => item.id === assetId)
  if (itemIndex < 0) {
    throw Object.assign(new Error('The requested Catalog asset is not present in the authorized current result set.'), { statusCode: 404 })
  }
  const pageIndex = Math.floor(itemIndex / limit)
  return {
    asset_id: assetId,
    item_index: itemIndex,
    page_index: pageIndex,
    cursors: Array.from({ length: pageIndex + 1 }, (_value, index) => (
      index === 0 ? null : issueCursor(scope, index * limit)
    )),
    meta: catalogMeta({ projection: true }),
  }
}

function uniqueValues(values) {
  return [...new Set(values.filter((value) => typeof value === 'string' && value.trim()))]
    .sort((left, right) => left.localeCompare(right))
}

function hierarchyValues(values) {
  return [...new Set(values
    .map((value) => typeof value === 'string' ? value.trim() : '')
    .filter(Boolean))]
    .sort((left, right) => left.localeCompare(right))
}

function catalogDatabaseBranchLabel(databaseName) {
  return typeof databaseName === 'string' ? databaseName.trim() : ''
}

async function datahubTree(searchParameters, principal) {
  const parentKind = searchParameters.get('parent_kind') || 'ROOT'
  const forceCurrent = searchParameters.get('refresh') === 'true'
  if (forceCurrent && parentKind !== 'ROOT') {
    throw Object.assign(new Error('Catalog hierarchy refresh is supported only at the root.'), { statusCode: 400 })
  }
  const assets = deps.filterAssetsForPrincipal(
    principal,
    forceCurrent ? await currentDatahubInventory() : await datahubHierarchyInventory(),
  )
  const platform = searchParameters.get('platform') || ''
  const databaseName = searchParameters.get('database') || ''
  const schemaName = searchParameters.get('schema') || ''
  let items
  if (parentKind === 'ROOT') {
    items = uniqueValues(assets.map((asset) => asset.platform)).map((value) => ({
      id: `PLATFORM:${value}`,
      kind: 'PLATFORM',
      label: value,
      asset_count: assets.filter((asset) => asset.platform === value).length,
      has_children: assets.some((asset) => asset.platform === value),
      platform: value,
    }))
  } else if (parentKind === 'PLATFORM') {
    items = hierarchyValues(assets
      .filter((asset) => asset.platform === platform)
      .map((asset) => asset.database_name)).map((value) => ({
      id: `DATABASE:${platform}:${value}`,
      kind: 'DATABASE',
      label: catalogDatabaseBranchLabel(value),
      asset_count: assets.filter((asset) => asset.platform === platform && asset.database_name === value).length,
      has_children: assets.some((asset) => asset.platform === platform && asset.database_name === value),
      platform,
      database_name: value,
    }))
  } else if (parentKind === 'DATABASE') {
    items = hierarchyValues(assets
      .filter((asset) => asset.platform === platform && asset.database_name === databaseName)
      .map((asset) => asset.schema_name)).map((value) => ({
      id: `SCHEMA:${platform}:${databaseName}:${value}`,
      kind: 'SCHEMA',
      label: value || '(schema 미지정)',
      asset_count: assets.filter((asset) => asset.platform === platform && asset.database_name === databaseName && asset.schema_name === value).length,
      has_children: assets.some((asset) => asset.platform === platform && asset.database_name === databaseName && asset.schema_name === value),
      platform,
      database_name: databaseName,
      schema_name: value,
    }))
  } else if (parentKind === 'SCHEMA') {
    items = assets
      .filter((asset) => asset.platform === platform && asset.database_name === databaseName && asset.schema_name === schemaName)
      .sort((left, right) => left.name.localeCompare(right.name) || left.id.localeCompare(right.id))
      .map((asset) => ({
        id: `ASSET:${asset.id}`,
        kind: 'ASSET',
        label: asset.name,
        asset_count: 1,
        has_children: false,
        platform,
        database_name: databaseName,
        schema_name: schemaName,
        asset: publicDatahubAsset(asset),
      }))
  } else {
    throw Object.assign(new Error('Unsupported DataHub hierarchy parent kind.'), { statusCode: 400 })
  }
  const scope = parameterScope('catalog-tree', searchParameters, ['parent_kind', 'platform', 'database', 'schema', 'limit'])
  return { ...offsetPage(items, searchParameters, scope, 100, 200), meta: catalogMeta({ projection: true }) }
}

function facetCounts(values) {
  const counts = new Map()
  for (const value of values) {
    if (typeof value === 'string' && value) counts.set(value, (counts.get(value) || 0) + 1)
  }
  return [...counts].map(([value, count]) => ({ value, count }))
    .sort((left, right) => left.value.localeCompare(right.value))
}

async function datahubFacets(searchParameters, principal) {
  const query = deps.boundedString(searchParameters.get('q'), 500, '*') || '*'
  const fields = catalogSearchFields(searchParameters)
  const inventory = fields.includes('COLUMN') && query !== '' && query !== '*'
    ? await datahubEmbeddingInventory()
    : await datahubInventory()
  const assets = deps.filterAssetsForPrincipal(principal, inventory)
    .filter((asset) => assetMatches(asset, searchParameters, fields))
  return {
    asset_types: facetCounts(assets.map((item) => item.asset_type)),
    platforms: facetCounts(assets.map((item) => item.platform)),
    classifications: facetCounts(assets.map((item) => item.classification)),
    databases: facetCounts(assets.map((item) => item.database_name)),
    schemas: facetCounts(assets.map((item) => item.schema_name)),
    domains: facetCounts(assets.map((item) => item.domain)),
    lifecycles: facetCounts(assets.map((item) => item.lifecycle)),
    meta: catalogMeta({ projection: true }),
  }
}

async function datahubDashboard(principal) {
  const [inventory, glossaryPage] = await Promise.all([
    datahubInventory(),
    datahubGlossary(new URLSearchParams({ limit: '1' }), principal),
  ])
  const assets = deps.filterAssetsForPrincipal(principal, inventory, 'monitoring')
  const schemaMetrics = new Map()
  for (const asset of assets) {
    const key = [asset.platform, asset.database_name, asset.schema_name].join('\u0000')
    const current = schemaMetrics.get(key) || {
      platform: asset.platform,
      database_name: asset.database_name,
      schema_name: asset.schema_name,
      asset_count: 0,
      described_asset_count: 0,
      tagged_asset_count: 0,
      term_asset_count: 0,
    }
    current.asset_count += 1
    if (asset.description?.trim()) current.described_asset_count += 1
    if (Array.isArray(asset.tags) && asset.tags.length > 0) current.tagged_asset_count += 1
    if (Array.isArray(asset.terms) && asset.terms.length > 0) current.term_asset_count += 1
    schemaMetrics.set(key, current)
  }
  const meta = catalogMeta({ projection: true })
  return {
    observed_at: meta.observed_at,
    changes_by_state: {},
    catalog_asset_count: assets.length,
    catalog_described_asset_count: assets.filter((asset) => asset.description?.trim()).length,
    catalog_glossary_term_count: glossaryPage.total,
    catalog_schema_metrics: [...schemaMetrics.values()].slice(0, 200),
    catalog_schema_metrics_truncated: schemaMetrics.size > 200,
    meta,
  }
}

function catalogExportRequest(body) {
  if (!body || typeof body !== 'object' || Array.isArray(body)) {
    throw deps.accessError(400, 'CATALOG_EXPORT_INPUT_INVALID', 'A Catalog export request object is required.')
  }
  const allowed = new Set(['q', ...deps.catalogExportFilterFields, 'sort', 'format'])
  if (Object.keys(body).some((key) => !allowed.has(key))
    || typeof body.q !== 'string' || body.q.length > 500
    || body.sort !== 'NAME_ASC' || !['CSV', 'XLSX'].includes(body.format)) {
    throw deps.accessError(400, 'CATALOG_EXPORT_INPUT_INVALID', 'Catalog export filters, sort, or format are invalid.')
  }
  for (const field of deps.catalogExportFilterFields) {
    const value = body[field]
    if (value !== undefined && (typeof value !== 'string' || value.length > 500 || deps.hasAccessControlCharacter(value))) {
      throw deps.accessError(400, 'CATALOG_EXPORT_INPUT_INVALID', `Catalog export ${field} is invalid.`)
    }
  }
  if (body.classification !== undefined && !deps.catalogExportClassifications.has(body.classification)) {
    throw deps.accessError(400, 'CATALOG_EXPORT_INPUT_INVALID', 'Catalog export classification is invalid.')
  }
  if (body.lifecycle !== undefined && body.lifecycle !== 'ACTIVE') {
    throw deps.accessError(400, 'CATALOG_EXPORT_INPUT_INVALID', 'Catalog export lifecycle is invalid.')
  }
  if (body.classification === 'RESTRICTED') {
    throw deps.accessError(403, 'CATALOG_EXPORT_RESTRICTED', 'RESTRICTED assets cannot be exported.')
  }
  return body
}

function catalogExportSearchParameters(body) {
  const parameters = new URLSearchParams({ q: body.q || '*' })
  const mappings = {
    asset_type: 'asset_type', platform: 'platform', database_name: 'database',
    schema_name: 'schema', domain: 'domain', search_fields: 'search_fields',
    classification: 'classification', lifecycle: 'lifecycle',
  }
  for (const [field, parameter] of Object.entries(mappings)) {
    if (body[field]) parameters.set(parameter, body[field])
  }
  return parameters
}

function catalogExportRow(asset) {
  return {
    asset_id: asset.id,
    external_urn: asset.external_urn || asset.id,
    platform: asset.platform || '',
    database_name: asset.database_name || '',
    schema_name: asset.schema_name || '',
    name: asset.name,
    asset_type: asset.asset_type,
    classification: asset.classification,
    lifecycle: asset.lifecycle,
    description: asset.description || '',
    source_version: asset.source_version || 'datahub-live',
    observed_at: asset.observed_at || '',
  }
}

async function createCatalogExport(request, context) {
  const body = catalogExportRequest(await deps.bodyJson(request))
  const idempotencyKey = request.headers['idempotency-key']
  const selection = await datahubCatalogSelection(
    catalogExportSearchParameters(body),
    context.principal,
    'catalog',
  )
  if (selection.allItems.some((asset) => asset.classification === 'RESTRICTED')) {
    throw deps.accessError(403, 'CATALOG_EXPORT_RESTRICTED', 'RESTRICTED assets cannot be exported.')
  }
  const status = context.catalogExportStore.create({
    ownerId: context.principal.subjectId,
    idempotencyKey,
    requestHash: canonicalHash(body),
    format: body.format,
    rows: selection.allItems.map(catalogExportRow),
  })
  return { export_id: status.export_id, job_id: status.job_id, state: status.state }
}

async function datahubProfileCoverage(principal) {
  const bindingHash = deps.catalogEmbeddingBindingHash()
  if (bindingHash && principal.role === 'admin') {
    const projected = await deps.pocStateStore.catalogEmbeddingProfileCoverage(bindingHash, deps.datahubInventoryStateScope)
    if (projected.length) {
      const items = projected.map((item) => ({
        platform: item.platform,
        asset_count: item.asset_count,
        row_count_available: item.row_count_available,
        size_bytes_available: item.size_bytes_available,
        created_at_available: item.created_at_available,
        schema_available: item.schema_available,
      }))
      const observedTimes = projected.map((item) => item.observed_at).filter(Boolean).sort()
      return {
        observed_at: observedTimes.at(-1) || new Date().toISOString(),
        source: 'DATAHUB_GMS_VECTOR_PROJECTION',
        projection_contract: 'POC_DATAHUB_CATALOG_ASSET_V2',
        asset_count: items.reduce((total, item) => total + item.asset_count, 0),
        row_count_available: items.reduce((total, item) => total + item.row_count_available, 0),
        size_bytes_available: items.reduce((total, item) => total + item.size_bytes_available, 0),
        created_at_available: items.reduce((total, item) => total + item.created_at_available, 0),
        schema_available: items.reduce((total, item) => total + item.schema_available, 0),
        items,
      }
    }
  }
  const assets = deps.filterAssetsForPrincipal(principal, await datahubEmbeddingInventory(), 'quality')
  const byPlatform = new Map()
  for (const asset of assets) {
    const platform = asset.platform || 'unknown'
    const current = byPlatform.get(platform) || {
      platform,
      asset_count: 0,
      row_count_available: 0,
      size_bytes_available: 0,
      created_at_available: 0,
      schema_available: 0,
    }
    current.asset_count += 1
    if (Number.isInteger(asset.quality?.rowCount)) current.row_count_available += 1
    if (Number.isInteger(asset.quality?.sizeInBytes)) current.size_bytes_available += 1
    if (asset.created_at) current.created_at_available += 1
    if (Number.isInteger(asset.schema_fields_total) && asset.schema_fields_total > 0) current.schema_available += 1
    byPlatform.set(platform, current)
  }
  const items = [...byPlatform.values()].sort((left, right) => left.platform.localeCompare(right.platform))
  const meta = catalogMeta({ projection: true })
  return {
    observed_at: meta.observed_at,
    source: deps.pocStateStore.configured.postgres
      ? 'POSTGRES_CURRENT_PROJECTION'
      : 'PROCESS_MEMORY_CURRENT_PROJECTION',
    asset_count: assets.length,
    row_count_available: items.reduce((total, item) => total + item.row_count_available, 0),
    size_bytes_available: items.reduce((total, item) => total + item.size_bytes_available, 0),
    created_at_available: items.reduce((total, item) => total + item.created_at_available, 0),
    schema_available: items.reduce((total, item) => total + item.schema_available, 0),
    items,
    meta,
  }
}

async function datahubSystems(principal) {
  return {
    items: uniqueValues(deps.filterAssetsForPrincipal(principal, await datahubHierarchyInventory())
      .map((asset) => asset.platform)).map((platform, index) => ({
      id: platform,
      code: platform.toUpperCase().replace(/[^A-Z0-9]+/g, '_') || `DATAHUB_${index + 1}`,
      name: platform,
    })),
  }
}

async function datahubGlossaryAssignments(searchParameters, principal) {
  const urn = deps.boundedString(searchParameters.get('urn'), 4_096).trim()
  if (!urn.startsWith('urn:li:glossaryTerm:')) {
    throw Object.assign(new Error('A valid DataHub Glossary Term URN is required.'), { statusCode: 400 })
  }
  const targetType = searchParameters.get('target_type')
  if (!['TABLE', 'COLUMN'].includes(targetType)) {
    throw Object.assign(new Error('Glossary target_type must be TABLE or COLUMN.'), { statusCode: 400 })
  }
  const limit = Math.min(50, Math.max(1, Number(searchParameters.get('limit')) || 25))
  const rawCursor = searchParameters.get('cursor') ?? '0'
  if (!/^\d+$/.test(rawCursor) || Number(rawCursor) > 100_000) {
    throw Object.assign(new Error('Glossary assignment cursor is invalid.'), { statusCode: 400 })
  }
  const start = Number(rawCursor)
  const relationshipType = targetType === 'TABLE' ? 'TermedWith' : 'SchemaFieldWithGlossaryTerm'
  const items = []
  const observed = new Set()
  const add = (asset, fieldPath) => {
    const tableQualifiedName = [asset.platform, asset.database_name, asset.schema_name, asset.name]
      .filter(Boolean).join('.')
    const id = targetType === 'TABLE'
      ? `TABLE:${asset.id}`
      : `COLUMN:${asset.id}:${fieldPath}`
    if (observed.has(id)) return
    observed.add(id)
    items.push({
      id,
      target_type: targetType,
      name: fieldPath || asset.name,
      table_name: asset.name,
      field_path: fieldPath || null,
      qualified_name: [tableQualifiedName, fieldPath].filter(Boolean).join('.'),
      platform: asset.platform,
      database_name: asset.database_name,
      schema_name: asset.schema_name,
    })
  }
  let providerStart = 0
  let providerTotal
  for (let pageNumber = 0; pageNumber < deps.maximumInventoryPages; pageNumber += 1) {
    const data = await datahubGraphql(deps.datahubGlossaryAssignmentsQuery, {
      urn,
      input: {
        types: [relationshipType], direction: 'INCOMING', start: providerStart, count: 100,
        includeSoftDelete: false,
      },
    })
    const relationships = data.entity?.relationships
    if (!relationships) {
      throw Object.assign(new Error('DataHub Glossary Term was not found.'), { statusCode: 404 })
    }
    if (!Number.isSafeInteger(relationships.total) || relationships.total < 0
      || (providerTotal !== undefined && relationships.total !== providerTotal)
      || relationships.start !== providerStart || !Array.isArray(relationships.relationships)) {
      throw Object.assign(new Error('DataHub glossary assignments changed during the bounded read.'), { statusCode: 502 })
    }
    providerTotal = relationships.total
    const relationshipDatasetUrns = [...new Set(relationships.relationships.flatMap((relationship) => (
      relationship.entity?.type === 'DATASET' && typeof relationship.entity.urn === 'string'
        ? [relationship.entity.urn]
        : []
    )))]
    const confirmedTables = new Map((relationshipDatasetUrns.length
      ? await currentDatahubTables(relationshipDatasetUrns)
      : []).map((table) => [table.id, table]))
    for (const relationship of relationships.relationships) {
      const entity = relationship.entity
      if (!entity?.urn || entity.type !== 'DATASET') continue
      const confirmed = confirmedTables.get(entity.urn)
      if (!confirmed) continue
      const asset = { ...datasetAsset(entity), ...confirmed }
      if (!deps.canReadAsset(principal, asset, 'governance')) continue
      if (targetType === 'TABLE') {
        add(asset)
        continue
      }
      for (const field of datahubSchemaFields(entity)) {
        const applied = (field.glossaryTerms?.terms || []).some((reference) => reference.term?.urn === urn)
        if (applied) add(asset, field.fieldPath)
      }
    }
    const fetched = relationships.relationships.length
    providerStart += fetched
    if (providerStart >= providerTotal) break
    if (fetched === 0) {
      throw Object.assign(new Error('DataHub glossary assignment pagination stalled.'), { statusCode: 502 })
    }
  }
  if (providerTotal === undefined || providerStart < providerTotal) {
    throw Object.assign(new Error('DataHub glossary assignment pagination exceeded its bound.'), { statusCode: 502 })
  }
  items.sort((left, right) => left.qualified_name.localeCompare(right.qualified_name) || left.id.localeCompare(right.id))
  const pageItems = items.slice(start, start + limit)
  const nextOffset = start + pageItems.length
  return {
    items: pageItems,
    total: items.length,
    page: { next_cursor: nextOffset < items.length ? String(nextOffset) : null, limit },
  }
}

function exactGlossaryTermUrns(value) {
  if (!Array.isArray(value) || value.length < 1 || value.length > 50) {
    throw deps.accessError(400, 'GLOSSARY_ASSIGNMENT_COUNT_SCOPE_INVALID', 'urns must contain between 1 and 50 exact Glossary Term URNs.')
  }
  const urns = value.map((item) => typeof item === 'string' ? item.trim() : '')
  if (urns.some((urn) => urn.length > 4_096
    || !urn.startsWith('urn:li:glossaryTerm:')
    || urn === 'urn:li:glossaryTerm:'
    || deps.hasAccessControlCharacter(urn))
    || new Set(urns).size !== urns.length) {
    throw deps.accessError(400, 'GLOSSARY_ASSIGNMENT_COUNT_SCOPE_INVALID', 'urns must be unique exact Glossary Term URNs.')
  }
  return urns
}

function glossaryAssignmentCountsFromInventory(urns, inventory) {
  const counts = new Map(urns.map((urn) => [urn, {
    urn,
    table_asset_count: 0,
    column_asset_count: 0,
  }]))
  for (const asset of Array.isArray(inventory) ? inventory : []) {
    if (asset?.dataset_kind !== 'TABLE' || typeof asset.id !== 'string') continue
    const tableTerms = new Set([
      ...(Array.isArray(asset.glossary_terms) ? asset.glossary_terms : []),
      ...(Array.isArray(asset.term_references) ? asset.term_references : []),
    ].flatMap((term) => typeof term?.urn === 'string' ? [term.urn] : []))
    for (const termUrn of tableTerms) {
      const count = counts.get(termUrn)
      if (count) count.table_asset_count += 1
    }
    for (const field of Array.isArray(asset.schema_fields) ? asset.schema_fields : []) {
      const fieldTerms = new Set((field?.glossaryTerms?.terms || []).flatMap((reference) => (
        typeof reference?.term?.urn === 'string' ? [reference.term.urn] : []
      )))
      for (const termUrn of fieldTerms) {
        const count = counts.get(termUrn)
        if (count) count.column_asset_count += 1
      }
    }
  }
  return { items: urns.map((urn) => counts.get(urn)) }
}

async function datahubGlossaryAssignmentBatchCounts(body, principal) {
  if (!body || typeof body !== 'object' || Array.isArray(body)
    || Object.keys(body).length !== 1 || !Object.hasOwn(body, 'urns')) {
    throw deps.accessError(400, 'GLOSSARY_ASSIGNMENT_COUNT_SCOPE_INVALID', 'Only the urns field is supported.')
  }
  const urns = exactGlossaryTermUrns(body.urns)
  const inventory = deps.filterAssetsForPrincipal(
    principal,
    await datahubInventory(),
    'governance',
  )
  return glossaryAssignmentCountsFromInventory(urns, inventory)
}

function reconcileDatahubGlossaryScrollPage(page, state = {}) {
  const priorTotal = state.total
  const priorFetched = Number.isSafeInteger(state.fetched) && state.fetched >= 0 ? state.fetched : 0
  const priorCursor = typeof state.cursor === 'string' && state.cursor ? state.cursor : null
  if (!page || typeof page !== 'object' || !Array.isArray(page.searchResults)
    || !Number.isSafeInteger(page.count) || page.count < 0
    || !Number.isSafeInteger(page.total) || page.total < 0
    || page.count !== page.searchResults.length
    || (priorTotal !== undefined && priorTotal !== null && page.total !== priorTotal)) {
    throw Object.assign(new Error('DataHub glossary pagination metadata changed during the bounded read.'), { statusCode: 502 })
  }
  const fetched = priorFetched + page.searchResults.length
  if (fetched > page.total) {
    throw Object.assign(new Error('DataHub glossary pagination exceeded the reported total.'), { statusCode: 502 })
  }
  const cursor = typeof page.nextScrollId === 'string' && page.nextScrollId
    ? page.nextScrollId
    : null
  const complete = fetched === page.total
  if ((!complete && !cursor) || (cursor && cursor === priorCursor)) {
    throw Object.assign(new Error('DataHub glossary pagination did not make progress.'), { statusCode: 502 })
  }
  if (complete && cursor) {
    throw Object.assign(new Error('DataHub glossary pagination continued after the reported total.'), { statusCode: 502 })
  }
  return { total: page.total, fetched, cursor, complete }
}

async function datahubGlossary(searchParameters, principal) {
  if (searchParameters.get('detail') === 'true') {
    return datahubGlossaryDetail(searchParameters, principal)
  }
  const query = deps.boundedString(searchParameters.get('q'), 500).trim()
  const rawLimit = searchParameters.get('limit') ?? '50'
  if (!/^\d+$/.test(rawLimit) || Number(rawLimit) < 1 || Number(rawLimit) > 100) {
    throw Object.assign(new Error('Glossary limit must be between 1 and 100.'), { statusCode: 400 })
  }
  const limit = Number(rawLimit)
  const scope = parameterScope('glossary-live-scroll', searchParameters, ['q', 'limit'])
  const continuation = cursorValue(searchParameters.get('cursor'), scope)
  const providerCursor = continuation?.providerCursor
  const priorScroll = continuation?.scroll ?? { total: undefined, fetched: 0, cursor: null, complete: false }
  const input = {
    types: ['GLOSSARY_TERM'], query: query || '*', count: limit, keepAlive: '5m',
    sortInput: { sortCriteria: [{ field: 'urn', sortOrder: 'ASCENDING' }] },
    searchFlags: { skipAggregates: true, skipHighlighting: true },
    ...(providerCursor ? { scrollId: providerCursor } : {}),
  }
  const data = await datahubGraphql(deps.datahubGlossaryQuery, { input })
  const page = data.scrollAcrossEntities
  if (page?.count > limit) {
    throw Object.assign(new Error('DataHub glossary page exceeded the requested bound.'), { statusCode: 502 })
  }
  const scroll = reconcileDatahubGlossaryScrollPage(page, priorScroll)
  const items = page.searchResults.map((result) => glossaryTermProjection(result.entity, principal, false))
  return {
    items,
    total: scroll.total,
    page: {
      next_cursor: scroll.complete ? null : issueCursor(scope, { providerCursor: scroll.cursor, scroll }),
      limit,
    },
    currentness: {
      source: 'DATAHUB_GMS_LIVE',
      observed_at: new Date().toISOString(),
      atomic_snapshot: false,
    },
  }
}

function glossaryTermProjection(entity, principal, includeDetails) {
  if (!entity?.urn || entity.type !== 'GLOSSARY_TERM') {
    throw Object.assign(new Error('DataHub glossary page contained an invalid term.'), { statusCode: 502 })
  }
  const name = entity.properties?.name || entity.hierarchicalName || urnTail(entity.urn)
  const parents = (entity.parentNodes?.nodes || []).flatMap((node) => (
    node?.urn && node?.properties?.name
      ? [{ urn: node.urn, name: node.properties.name, description: node.properties.description || '' }]
      : []
  )).reverse()
  const tableAssetCount = includeDetails && principal.role === 'admin'
    ? Math.max(0, Number(entity.tableAssignments?.total) || 0)
    : null
  const columnAssetCount = includeDetails && principal.role === 'admin'
    ? Math.max(0, Number(entity.columnAssignments?.total) || 0)
    : null
  const outgoing = includeDetails ? entity.outgoingRelationships : undefined
  const relationshipTotal = Math.max(0, Number(outgoing?.total) || 0)
  const relationshipKeys = new Set()
  const relationships = (outgoing?.relationships || []).flatMap((relationship) => {
    if (!['GLOSSARY_TERM', 'GLOSSARY_NODE'].includes(relationship?.entity?.type)
      || typeof relationship.entity.urn !== 'string') return []
    const key = `${relationship.type}\u0000${relationship.direction}\u0000${relationship.entity.urn}`
    if (relationshipKeys.has(key)) return []
    relationshipKeys.add(key)
    return [{
      type: relationship.type,
      direction: relationship.direction,
      target_urn: relationship.entity.urn,
      target_type: relationship.entity.type,
      target_name: typeof relationship.entity.properties?.name === 'string'
        ? relationship.entity.properties.name
        : null,
    }]
  })
  return {
    urn: entity.urn,
    name,
    hierarchical_name: entity.hierarchicalName || name,
    description: entity.properties?.description || '',
    parent_terms: parents,
    child_terms: [],
    hierarchy_kind: 'LEAF_TERM',
    asset_count: tableAssetCount === null || columnAssetCount === null ? null : tableAssetCount + columnAssetCount,
    table_asset_count: tableAssetCount,
    column_asset_count: columnAssetCount,
    assets: [],
    relationship_count: relationshipTotal,
    relationships,
    relationships_truncated: relationships.length < relationshipTotal,
  }
}

async function datahubGlossaryDetail(searchParameters, principal) {
  const urn = deps.boundedString(searchParameters.get('urn'), 4_096).trim()
  if (!urn.startsWith('urn:li:glossaryTerm:')) {
    throw Object.assign(new Error('A valid DataHub Glossary Term URN is required.'), { statusCode: 400 })
  }
  const data = await datahubGraphql(deps.datahubGlossaryTermByUrnQuery, { urn })
  const entity = data.entity
  if (!entity || entity.urn !== urn || entity.type !== 'GLOSSARY_TERM'
    || entity.exists === false || entity.status?.removed === true) {
    throw Object.assign(new Error('DataHub Glossary Term was not found.'), { statusCode: 404 })
  }
  return glossaryTermProjection(entity, principal, true)
}

async function datahubGlossarySmokeTarget(searchParameters) {
  const rawConfiguredUrn = searchParameters.get('urn')
  const configuredUrn = typeof rawConfiguredUrn === 'string' ? rawConfiguredUrn.trim() : ''
  if (
    (rawConfiguredUrn !== null && rawConfiguredUrn.length > 1000)
    || (
      configuredUrn
      && (
        !configuredUrn.startsWith('urn:li:glossaryTerm:')
        || configuredUrn === 'urn:li:glossaryTerm:'
        || deps.hasAccessControlCharacter(configuredUrn)
      )
    )
  ) {
    throw glossarySmokeFailure(
      'PREP_SMOKE_GLOSSARY_TERM_INPUT_FAILED',
      'TARGET_RESOLUTION',
      'VALIDATE_CONFIGURED_URN',
      'GLOSSARY_TERM_URN_INVALID',
      { statusCode: 400 },
    )
  }

  let targetUrn = configuredUrn
  let selectionSource = 'CONFIGURED'
  if (!targetUrn) {
    selectionSource = 'RUNTIME_DISCOVERED'
    let discovery
    try {
      discovery = await datahubGraphql(deps.datahubGlossarySmokeDiscoveryQuery, {
        input: {
          types: ['GLOSSARY_TERM'],
          query: '*',
          count: 1,
          keepAlive: '1m',
          sortInput: { sortCriteria: [{ field: 'urn', sortOrder: 'ASCENDING' }] },
          searchFlags: { skipAggregates: true, skipHighlighting: true },
        },
      })
    } catch (error) {
      const detail = glossarySmokeProviderDetail(error)
      throw glossarySmokeFailure(
        'PREP_SMOKE_GLOSSARY_TERM_DISCOVERY_FAILED',
        'TARGET_DISCOVERY',
        'SCROLL_GLOSSARY_TERM_CANDIDATE',
        `PROVIDER_${detail}`,
        { terminal: !['CONNECTIVITY', 'TIMEOUT', 'HTTP_5XX'].includes(detail), cause: error },
      )
    }
    const candidate = discovery?.scrollAcrossEntities?.searchResults?.[0]?.entity
    if (!candidate) {
      throw glossarySmokeFailure(
        'PREP_SMOKE_GLOSSARY_TERM_NOT_FOUND_FAILED',
        'TARGET_DISCOVERY',
        'SCROLL_GLOSSARY_TERM_CANDIDATE',
        'NO_GLOSSARY_TERM_CANDIDATE',
        { statusCode: 424 },
      )
    }
    if (candidate.type !== 'GLOSSARY_TERM' || typeof candidate.urn !== 'string'
      || !candidate.urn.startsWith('urn:li:glossaryTerm:')
      || candidate.urn === 'urn:li:glossaryTerm:' || deps.hasAccessControlCharacter(candidate.urn)) {
      throw glossarySmokeFailure(
        'PREP_SMOKE_GLOSSARY_TERM_CONTRACT_FAILED',
        'TARGET_DISCOVERY',
        'SCROLL_GLOSSARY_TERM_CANDIDATE',
        'DISCOVERED_ENTITY_CONTRACT_INVALID',
      )
    }
    targetUrn = candidate.urn
  }

  let lookup
  try {
    lookup = await datahubGraphql(deps.datahubGlossarySmokeTargetQuery, { urn: targetUrn })
  } catch (error) {
    const detail = glossarySmokeProviderDetail(error)
    throw glossarySmokeFailure(
      'PREP_SMOKE_GLOSSARY_TERM_LOOKUP_FAILED',
      'EXACT_ENTITY_LOOKUP',
      'READ_GLOSSARY_TERM_BY_URN',
      `PROVIDER_${detail}`,
      { terminal: !['CONNECTIVITY', 'TIMEOUT', 'HTTP_5XX'].includes(detail), cause: error },
    )
  }
  const entity = lookup?.entity
  if (lookup?.entityExists !== true || !entity || entity.exists !== true || entity.status?.removed === true) {
    throw glossarySmokeFailure(
      'PREP_SMOKE_GLOSSARY_TERM_NOT_FOUND_FAILED',
      'EXACT_ENTITY_LOOKUP',
      'READ_GLOSSARY_TERM_BY_URN',
      'ENTITY_NOT_CURRENT',
      { statusCode: 424 },
    )
  }
  if (entity.urn !== targetUrn || entity.type !== 'GLOSSARY_TERM') {
    throw glossarySmokeFailure(
      'PREP_SMOKE_GLOSSARY_TERM_CONTRACT_FAILED',
      'EXACT_ENTITY_LOOKUP',
      'READ_GLOSSARY_TERM_BY_URN',
      'ENTITY_IDENTITY_OR_TYPE_MISMATCH',
    )
  }
  const basicName = entity.properties?.name || entity.glossaryTermInfo?.name || entity.hierarchicalName
  if (typeof basicName !== 'string' || !basicName.trim()) {
    throw glossarySmokeFailure(
      'PREP_SMOKE_GLOSSARY_TERM_CONTRACT_FAILED',
      'BASIC_METADATA_READ',
      'READ_GLOSSARY_TERM_BASIC_METADATA',
      'BASIC_METADATA_MISSING',
    )
  }
  return {
    contract: 'DATARIVER_PREP_GLOSSARY_TERM_SMOKE_TARGET_V1',
    selection_source: selectionSource,
    urn: targetUrn,
    entity_exists: true,
    entity_type: 'GLOSSARY_TERM',
    glossary_term_exists: true,
    basic_metadata_read: true,
    mutation_performed: false,
  }
}

function mergedMetadataReferences(values, collection, reference) {
  const merged = new Map()
  for (const value of values) {
    for (const item of value?.[collection] || []) {
      const target = item?.[reference]
      const identity = target?.urn || target?.name
      if (identity) merged.set(identity, { [reference]: target })
    }
  }
  return { [collection]: [...merged.values()] }
}

function datahubSchemaFields(entity) {
  if (Array.isArray(entity?.schema_fields)) return entity.schema_fields
  const baseFields = entity.schemaMetadata?.fields || []
  const editableFields = entity.editableSchemaMetadata?.editableSchemaFieldInfo || []
  const orderedPaths = []
  const observedPaths = new Set()
  for (const field of [...baseFields, ...editableFields]) {
    const path = typeof field?.fieldPath === 'string' ? field.fieldPath.trim() : ''
    if (path && !observedPaths.has(path)) {
      observedPaths.add(path)
      orderedPaths.push(path)
    }
  }
  const baseByPath = new Map(baseFields.map((field) => [field?.fieldPath, field]))
  const editableByPath = new Map(editableFields.map((field) => [field?.fieldPath, field]))
  return orderedPaths.map((fieldPath) => {
    const base = baseByPath.get(fieldPath) || {}
    const editable = editableByPath.get(fieldPath) || {}
    const fieldEntity = base.schemaFieldEntity || {}
    return {
      fieldPath,
      urn: fieldEntity.type === 'SCHEMA_FIELD' && typeof fieldEntity.urn === 'string' ? fieldEntity.urn : undefined,
      entityType: fieldEntity.type === 'SCHEMA_FIELD' ? fieldEntity.type : undefined,
      label: base.label || null,
      type: base.type || null,
      nativeDataType: base.nativeDataType || null,
      description: editable.description ?? base.description ?? null,
      globalTags: mergedMetadataReferences(
        [base.globalTags, fieldEntity.globalTags, editable.globalTags], 'tags', 'tag',
      ),
      glossaryTerms: mergedMetadataReferences(
        [base.glossaryTerms, fieldEntity.glossaryTerms, editable.glossaryTerms], 'terms', 'term',
      ),
      structured_properties: structuredPropertyReferences(fieldEntity.structuredProperties),
      nullable: base.nullable ?? true,
      isPartOfKey: base.isPartOfKey ?? false,
      isPartitioningKey: base.isPartitioningKey ?? false,
      jsonPath: base.jsonPath ?? null,
    }
  })
}

function detailedDatasetAsset(entity) {
  const asset = datasetAsset(entity)
  const fields = datahubSchemaFields(entity)
  return {
    ...asset,
    ownership: (entity.ownership?.owners || []).map((item) => ({
      owner: urnTail(item.owner?.urn),
      type: item.type || 'TECHNICAL_OWNER',
    })),
    glossary_terms: (entity.glossaryTerms?.terms || []).map((item) => ({
      urn: item.term?.urn,
      name: item.term?.properties?.name || item.term?.name,
      description: item.term?.properties?.description || '',
    })),
    schema_fields: fields,
    schema_fields_total: fields.length,
    schema_fields_available: fields.length,
    schema_fields_truncated: false,
    schema_fields_total_exact: true,
    schema_fields_offset: 0,
    schema_fields_limit: fields.length,
    schema_fields_has_more: false,
    // DataHub remains authoritative: absent profile values stay absent.
    quality: {
      ...datahubProfileQuality(entity.latestFullTableProfile, entity.properties),
      ...datahubAssertionQuality(entity.assertions),
    },
    projection_source_version: 'datahub-live-poc',
    source_version: 'datahub-live',
  }
}

function baseDatasetAsset(entity) {
  return publicDatahubAsset({
    ...datasetAsset(entity),
    ownership: (entity.ownership?.owners || []).map((item) => ({
      owner: urnTail(item.owner?.urn),
      type: item.type || 'TECHNICAL_OWNER',
    })),
    glossary_terms: (entity.glossaryTerms?.terms || []).map((item) => ({
      urn: item.term?.urn,
      name: item.term?.properties?.name || item.term?.name,
      description: item.term?.properties?.description || '',
    })),
    projection_source_version: 'datahub-live-poc',
    source_version: 'datahub-live',
  })
}

async function authorizedCatalogDetailBase(urn, principal) {
  const entity = await datahubCatalogDetailBaseEntity(urn)
  if (!entity) throw Object.assign(new Error('DataHub asset was not found.'), { statusCode: 404 })
  const asset = baseDatasetAsset(entity)
  if (!deps.canReadAsset(principal, asset, 'catalog')) {
    throw deps.accessError(404, 'CATALOG_ASSET_NOT_FOUND', 'The DataHub asset was not found in the current Table scope.')
  }
  return { entity, asset }
}

async function datahubCatalogDetailBase(urn, principal) {
  return (await authorizedCatalogDetailBase(urn, principal)).asset
}

async function datahubCatalogDetailSchema(urn, principal, requestedOffset = 0, requestedLimit = 100, sourceVersion) {
  await authorizedCatalogDetailBase(urn, principal)
  if (sourceVersion && sourceVersion !== 'datahub-live') {
    throw deps.accessError(409, 'CATALOG_DETAIL_SOURCE_STALE', 'The DataHub detail source version changed; reload the detail.')
  }
  const data = await datahubGraphql(deps.datahubCatalogDetailSchemaQuery, { urn })
  if (!data.entity || data.entity.urn !== urn || data.entity.type !== 'DATASET') {
    throw Object.assign(new Error('DataHub asset schema was not found.'), { statusCode: 404 })
  }
  const fields = datahubSchemaFields(data.entity)
  const fieldOffset = Math.max(0, Number.isInteger(requestedOffset) ? requestedOffset : 0)
  const fieldLimit = Math.min(100, Math.max(1, Number.isInteger(requestedLimit) ? requestedLimit : 100))
  if (fieldOffset > fields.length) {
    throw deps.accessError(409, 'CATALOG_DETAIL_SOURCE_STALE', 'The requested DataHub schema page is no longer current; reload the detail.')
  }
  const pageFields = fields.slice(fieldOffset, fieldOffset + fieldLimit)
  return {
    schema_fields: pageFields,
    schema_fields_total: fields.length,
    schema_fields_available: fields.length,
    schema_fields_truncated: false,
    schema_fields_total_exact: true,
    schema_fields_offset: fieldOffset,
    schema_fields_limit: fieldLimit,
    schema_fields_has_more: fieldOffset + pageFields.length < fields.length,
    source_version: 'datahub-live',
  }
}

async function datahubCatalogDetailQuality(urn, principal, sourceVersion) {
  const { entity: baseEntity } = await authorizedCatalogDetailBase(urn, principal)
  if (sourceVersion && sourceVersion !== 'datahub-live') {
    throw deps.accessError(409, 'CATALOG_DETAIL_SOURCE_STALE', 'The DataHub detail source version changed; reload the detail.')
  }
  const data = await datahubGraphql(deps.datahubCatalogDetailQualityQuery, { urn })
  if (!data.entity || data.entity.urn !== urn || data.entity.type !== 'DATASET') {
    throw Object.assign(new Error('DataHub asset quality detail was not found.'), { statusCode: 404 })
  }
  return {
    quality: {
      ...datahubProfileQuality(data.entity.latestFullTableProfile, baseEntity.properties),
      ...datahubAssertionQuality(data.entity.assertions),
    },
    source_version: 'datahub-live',
  }
}

async function datahubAssetAll(urn) {
  const entity = await datahubEntity(urn)
  if (!entity) throw Object.assign(new Error('DataHub asset was not found.'), { statusCode: 404 })
  return detailedDatasetAsset(entity)
}

async function datahubAsset(urn, requestedOffset = 0, requestedLimit = 100) {
  const asset = await datahubAssetAll(urn)
  const fields = asset.schema_fields
  const fieldOffset = Math.max(0, Number.isInteger(requestedOffset) ? requestedOffset : 0)
  const fieldLimit = Math.min(100, Math.max(1, Number.isInteger(requestedLimit) ? requestedLimit : 100))
  const pageFields = fields.slice(fieldOffset, fieldOffset + fieldLimit)
  return publicDatahubAsset({
    ...asset,
    schema_fields: pageFields,
    schema_fields_offset: fieldOffset,
    schema_fields_limit: fieldLimit,
    schema_fields_has_more: fieldOffset + pageFields.length < fields.length,
  })
}

function knowledgeCatalogField(field) {
  const fieldPath = typeof field?.fieldPath === 'string' ? field.fieldPath : ''
  return {
    field_path: fieldPath,
    field_urn: deps.isCanonicalDatahubSchemaFieldUrn(field?.urn, field?.table_urn)
      ? field.urn
      : null,
    field_type: field?.type ?? null,
    native_data_type: field?.nativeDataType ?? null,
    description: field?.description ?? null,
    description_truncated: false,
    tags: (field?.globalTags?.tags || []).map((item) => item?.tag?.name).filter(Boolean),
    tags_truncated: false,
    glossary_terms: (field?.glossaryTerms?.terms || []).map((item) => item?.term?.name).filter(Boolean),
    terms_truncated: false,
  }
}

function knowledgeCatalogDataset(asset, { detail = false } = {}) {
  const tableUrn = asset?.id || asset?.urn
  if (asset?.dataset_kind !== 'TABLE' || !deps.isCanonicalDatahubDatasetUrn(tableUrn)) {
    throw deps.accessError(404, 'KNOWLEDGE_CATALOG_TABLE_NOT_FOUND', 'The Knowledge Catalog Table was not found.')
  }
  const securityGrade = deps.legacyTableTagGrade(asset)
  const fields = detail
    ? (Array.isArray(asset.schema_fields) ? asset.schema_fields : []).map((field) => ({ ...field, table_urn: tableUrn }))
    : []
  const fieldMetadata = fields.map(knowledgeCatalogField)
  const selectionFingerprint = detail ? canonicalHash({
    contract_version: 'KNOWLEDGE_CATALOG_SELECTION_V1',
    table_urn: tableUrn,
    security_grade: securityGrade,
    source_version: asset.source_version || 'datahub-live',
    projection_source_version: asset.projection_source_version || 'datahub-live-poc',
    fields: fieldMetadata.map((field) => ({
      field_path: field.field_path,
      field_urn: field.field_urn,
      field_type: field.field_type,
      native_data_type: field.native_data_type,
      description: field.description,
      tags: field.tags,
      glossary_terms: field.glossary_terms,
    })),
  }) : null
  return {
    id: tableUrn,
    name: asset.name,
    asset_type: 'TABLE',
    platform: asset.platform,
    database_name: asset.database_name,
    schema_name: asset.schema_name,
    classification: securityGrade,
    source_version: asset.source_version || 'datahub-live',
    projection_source_version: asset.projection_source_version || 'datahub-live-poc',
    field_paths: fieldMetadata.map((field) => field.field_path),
    fields_truncated: Boolean(asset.schema_fields_truncated),
    domain: asset.domain || null,
    tags: Array.isArray(asset.tags) ? asset.tags : [],
    glossary_terms: Array.isArray(asset.terms) ? asset.terms : [],
    description: asset.description || null,
    description_truncated: Boolean(asset.description_truncated),
    field_metadata: fieldMetadata,
    selection_fingerprint: selectionFingerprint,
  }
}

async function knowledgeCatalogSearch(searchParameters, principal) {
  const page = await datahubCatalog(searchParameters, principal, 'knowledge', { tableOnly: true })
  return { ...page, items: page.items.map((asset) => knowledgeCatalogDataset(asset)) }
}

async function knowledgeCatalogDetail(searchParameters, principal) {
  const urn = deps.boundedString(searchParameters.get('urn'), 4_096).trim()
  if (!deps.isCanonicalDatahubDatasetUrn(urn)) {
    throw deps.accessError(404, 'KNOWLEDGE_CATALOG_TABLE_NOT_FOUND', 'The Knowledge Catalog Table was not found.')
  }
  const asset = await datahubAssetAll(urn)
  if (asset.dataset_kind !== 'TABLE' || !deps.canReadAsset(principal, asset, 'knowledge')) {
    throw deps.accessError(404, 'KNOWLEDGE_CATALOG_TABLE_NOT_FOUND', 'The Knowledge Catalog Table was not found.')
  }
  return { dataset: knowledgeCatalogDataset(asset, { detail: true }), observed_at: new Date().toISOString() }
}

function datahubLineageProjectionOptions(searchParameters) {
  const direction = (searchParameters.get('direction') || 'BOTH').trim().toUpperCase()
  const depth = Number(searchParameters.get('depth') || 1)
  if (!['UPSTREAM', 'DOWNSTREAM', 'BOTH'].includes(direction)) {
    throw deps.accessError(400, 'LINEAGE_DIRECTION_INVALID', 'Lineage direction must be UPSTREAM, DOWNSTREAM, or BOTH.')
  }
  if (!Number.isSafeInteger(depth) || depth < 1 || depth > 2) {
    throw deps.accessError(400, 'LINEAGE_DEPTH_INVALID', 'Lineage depth must be 1 or 2.')
  }
  return { direction, depth }
}

async function datahubLineage(urn, principal, { direction = 'BOTH', depth = 1 } = {}) {
  const center = await datahubAsset(urn)
  if (!deps.canReadAsset(principal, center, 'catalog')) {
    throw deps.accessError(404, 'CATALOG_ASSET_NOT_FOUND', 'The DataHub asset was not found in the current Table scope.')
  }
  const requestedDirections = direction === 'BOTH' ? ['UPSTREAM', 'DOWNSTREAM'] : [direction]
  const maximumNodes = 200
  const maximumEdges = 400
  const nodes = new Map([[urn, center]])
  const edges = []
  const edgeIds = new Set()
  let authorizedBoundReached = false
  let providerTruncated = false
  for (const currentDirection of requestedDirections) {
    const visited = new Set([urn])
    let frontier = [urn]
    for (let currentDepth = 1; currentDepth <= depth && frontier.length > 0; currentDepth += 1) {
      const groups = []
      for (let offset = 0; offset < frontier.length; offset += 4) {
        groups.push(...await Promise.all(frontier.slice(offset, offset + 4).map(async (currentUrn) => {
          const data = await datahubGraphql(deps.datahubLineageQuery, {
            urn: currentUrn,
            input: {
              direction: currentDirection,
              start: 0,
              count: 100,
              // A catalog table graph must not split sibling representations or
              // surface DataHub ghost entities as clickable table assets.
              separateSiblings: false,
              includeGhostEntities: false,
            },
          })
          return {
            currentUrn,
            total: Number(data.dataset?.lineage?.total || 0),
            relationships: data.dataset?.lineage?.relationships || [],
          }
        })))
      }
      const nextFrontier = []
      for (const group of groups) {
        if (group.total > group.relationships.length) providerTruncated = true
        for (const relationship of group.relationships) {
          const entity = relationship.entity
          const relatedUrn = entity?.urn
          // The Catalog detail pane can resolve Dataset assets only. Data jobs or
          // processes remain represented by DataHub's Dataset-to-Dataset lineage,
          // rather than by a synthetic view_<hash> placeholder node.
          if (!relatedUrn || relatedUrn === group.currentUrn || entity?.type !== 'DATASET') continue
          const relatedAsset = datasetAsset(entity)
          if (!deps.canReadAsset(principal, relatedAsset, 'catalog')) continue
          if (!nodes.has(relatedUrn)) {
            if (nodes.size >= maximumNodes) {
              authorizedBoundReached = true
              continue
            }
            nodes.set(relatedUrn, relatedAsset)
          }
          const edge = currentDirection === 'UPSTREAM'
            ? { source_asset_id: relatedUrn, target_asset_id: group.currentUrn }
            : { source_asset_id: group.currentUrn, target_asset_id: relatedUrn }
          const edgeId = `${edge.source_asset_id}\u0000${edge.target_asset_id}`
          if (!edgeIds.has(edgeId)) {
            if (edges.length >= maximumEdges) {
              authorizedBoundReached = true
              continue
            }
            edgeIds.add(edgeId)
            edges.push(edge)
          }
          if (!visited.has(relatedUrn)) {
            visited.add(relatedUrn)
            nextFrontier.push(relatedUrn)
          }
        }
      }
      frontier = nextFrontier
    }
  }
  return {
    center_asset_id: urn,
    nodes: [...nodes.values()],
    edges,
    direction,
    depth,
    truncated: authorizedBoundReached || (principal.role === 'admin' && providerTruncated),
    meta: catalogMeta(),
  }
}

return { boundedDatahubGraphqlDiagnostic, datahubGraphql, glossarySmokeProviderDetail, glossarySmokeFailure, datahubRefreshGraphql, datahubRuntimeIdentity, datahubHeaders, datahubAssetCacheKey, datahubAssetBaseCacheKey, invalidateDatahubCaches, datahubAspectDocument, canonicalJson, canonicalHash, malformedDatahubReadback, plainDocument, validAuditStamp, manualMetadataAspectComparableDocument, manualMetadataAspectHash, datahubReadAspect, datahubApplyAspect, controlledUrn, uniqueControlledUrns, applyManualMetadata, urnTail, containerKind, customProperty, readablePathName, containerDisplayName, datasetIdentity, tagReferences, publicDatahubAsset, customPropertyReferences, structuredPropertyReferences, datahubCreatedAt, datasetAsset, catalogMeta, pruneCursorEntries, issueCursor, cursorValue, datahubCatalogPage, datahubInventory, currentDatahubInventory, datahubEmbeddingInventory, datahubHierarchyInventory, validDatahubInventory, inventorySnapshotFrom, storedDatahubInventory, datahubInventoryProjection, boundedInventoryDiagnostic, inventoryFailure, stableInventoryItemHash, startDatahubInventoryRefresh, datahubEntity, datahubCatalogDetailBaseEntity, currentDatahubTables, catalogSearchFields, catalogQueryTerms, catalogSearchValues, catalogMatchContext, catalogMatchFragments, assetMatches, parameterScope, offsetPage, datahubCatalogSelection, datahubCatalog, datahubCatalogLocate, uniqueValues, hierarchyValues, catalogDatabaseBranchLabel, datahubTree, facetCounts, datahubFacets, datahubDashboard, catalogExportRequest, catalogExportSearchParameters, catalogExportRow, createCatalogExport, datahubProfileCoverage, datahubSystems, datahubGlossaryAssignments, exactGlossaryTermUrns, glossaryAssignmentCountsFromInventory, datahubGlossaryAssignmentBatchCounts, reconcileDatahubGlossaryScrollPage, datahubGlossary, glossaryTermProjection, datahubGlossaryDetail, datahubGlossarySmokeTarget, mergedMetadataReferences, datahubSchemaFields, nonNegativeInteger, datahubCustomPropertyValue, isFullTableProfile, datahubProfileQuality, datahubAssertionQuality, detailedDatasetAsset, baseDatasetAsset, authorizedCatalogDetailBase, datahubCatalogDetailBase, datahubCatalogDetailSchema, datahubCatalogDetailQuality, datahubAssetAll, datahubAsset, knowledgeCatalogField, knowledgeCatalogDataset, knowledgeCatalogSearch, knowledgeCatalogDetail, datahubLineageProjectionOptions, datahubLineage }
}
