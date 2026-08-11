/* global AbortSignal, Buffer, URL, URLSearchParams, fetch, process */
import { createHmac, createHash, randomUUID } from 'node:crypto'
import { createReadStream, existsSync, readFileSync, statSync } from 'node:fs'
import { createServer } from 'node:http'
import { extname, join, normalize, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

const sourceDirectory = resolve(fileURLToPath(new URL('.', import.meta.url)))
const staticDirectory = join(sourceDirectory, 'dist-poc')
const environmentFile = resolve(process.env.POC_ENV_FILE || join(sourceDirectory, '../deploy/poc/.env'))
if (existsSync(environmentFile)) process.loadEnvFile(environmentFile)
const maximumJsonBytes = 1024 * 1024
const maximumObjectBytes = 50 * 1024 * 1024
const providerTimeoutMs = 15_000
const allowedAirflowDags = new Set([
  'datariver_bulk_registration_prepare',
  'datariver_catalog_probe',
  'datariver_catalog_sync',
  'datariver_manual_metadata_apply',
  'datariver_quality_dispatch',
  'datariver_semiconductor_seed_ingestion',
])

const datahubCursorTtlMs = 5 * 60 * 1000
const datahubInventoryTtlMs = 30 * 1000
const maximumCursorEntries = 1_024
const maximumInventoryPages = 10_002
const cursorEntries = new Map()
let inventorySnapshot

function optionalUrl(name) {
  const raw = process.env[name]?.trim()
  if (!raw) return undefined
  const value = new URL(raw)
  if (!['http:', 'https:'].includes(value.protocol) || value.username || value.password || value.hash) {
    throw new Error(`${name} must be an http(s) URL without credentials or a fragment.`)
  }
  return value.toString().replace(/\/$/, '')
}

function enabled(name) {
  const raw = process.env[name]?.trim().toLowerCase()
  if (!raw) return false
  if (raw === 'true') return true
  if (raw === 'false') return false
  throw new Error(`${name} must be true or false.`)
}

function stage(prefix) {
  const url = optionalUrl(`${prefix}_URL`)
  const model = process.env[`${prefix}_MODEL`]?.trim()
  const token = process.env[`${prefix}_TOKEN`]?.trim()
  if ([url, model, token].some(Boolean) && ![url, model, token].every(Boolean)) {
    throw new Error(`${prefix}_URL, ${prefix}_MODEL and ${prefix}_TOKEN must be configured together.`)
  }
  return url && model && token ? { url, model, token } : undefined
}

function credentials(prefix, urlName, { allowUrlOmission = false } = {}) {
  const url = optionalUrl(urlName)
  const username = process.env[`${prefix}_USERNAME`]?.trim()
  const password = process.env[`${prefix}_PASSWORD`]?.trim()
  if (!url && allowUrlOmission) return undefined
  if ([url, username, password].some(Boolean) && ![url, username, password].every(Boolean)) {
    throw new Error(`${urlName}, ${prefix}_USERNAME and ${prefix}_PASSWORD must be configured together.`)
  }
  return url && username && password ? { url, username, password } : undefined
}

function tokenProvider(prefix, urlName) {
  const url = optionalUrl(urlName)
  const token = process.env[`${prefix}_TOKEN`]?.trim()
  if ([url, token].some(Boolean) && ![url, token].every(Boolean)) {
    throw new Error(`${urlName} and ${prefix}_TOKEN must be configured together.`)
  }
  return url && token ? { url, token } : undefined
}

const datahub = tokenProvider('DATAHUB_GMS', 'DATAHUB_GMS_URL')
const airflow = credentials('AIRFLOW', 'AIRFLOW_URL')
const minioUrl = optionalUrl('MINIO_URL')
const minioAccessKey = process.env.MINIO_ACCESS_KEY?.trim()
const minioSecretKey = process.env.MINIO_SECRET_KEY?.trim()
if ([minioUrl, minioAccessKey, minioSecretKey].some(Boolean)
  && ![minioUrl, minioAccessKey, minioSecretKey].every(Boolean)) {
  throw new Error('MINIO_URL, MINIO_ACCESS_KEY and MINIO_SECRET_KEY must be configured together.')
}
const minio = minioUrl && minioAccessKey && minioSecretKey ? {
  url: minioUrl,
  accessKey: minioAccessKey,
  secretKey: minioSecretKey,
  region: process.env.MINIO_REGION?.trim() || 'us-east-1',
  buckets: {
    quarantine: process.env.S3_BUCKET_QUARANTINE?.trim() || 'datariver-quarantine',
    accepted: process.env.S3_BUCKET_ACCEPTED?.trim() || 'datariver-accepted',
    exports: process.env.S3_BUCKET_EXPORTS?.trim() || 'datariver-exports',
    filefolder: process.env.S3_BUCKET_FILEFOLDER?.trim() || 'datariver-filefolder',
    infoschema: process.env.S3_BUCKET_INFOSCHEMA?.trim() || 'datariver-infoschema',
  },
} : undefined
const llm = {
  chat: stage('LLM_CHAT'),
  embedding: stage('LLM_EMBEDDING'),
  reranker: stage('LLM_RERANKER'),
}
const neo4j = credentials('NEO4J', 'NEO4J_HTTP_URL', { allowUrlOmission: true })
const datahubUiUrl = optionalUrl('DATAHUB_UI_URL')
const grafanaUiUrl = optionalUrl('UI_GRAFANA_URL')
const grafanaEmbedBaseUrl = optionalUrl('GRAFANA_EMBED_BASE_URL')
const grafanaEmbedEnabled = enabled('GRAFANA_EMBED_ENABLED')
const grafanaEvidenceReference = process.env.GRAFANA_EMBED_EVIDENCE_REFERENCE?.trim()
if (grafanaEmbedEnabled) {
  if (!grafanaUiUrl || !grafanaEmbedBaseUrl || !grafanaEvidenceReference) {
    throw new Error('Grafana embed requires UI_GRAFANA_URL, GRAFANA_EMBED_BASE_URL and GRAFANA_EMBED_EVIDENCE_REFERENCE.')
  }
  if (new URL(grafanaUiUrl).origin !== new URL(grafanaEmbedBaseUrl).origin) {
    throw new Error('UI_GRAFANA_URL and GRAFANA_EMBED_BASE_URL must use the same exact origin.')
  }
}
const runtimeFlags = Object.freeze({
  datahub: Boolean(datahub),
  airflow: Boolean(airflow),
  minio: Boolean(minio),
  llmChat: Boolean(llm.chat),
  llmEmbedding: Boolean(llm.embedding),
  llmReranker: Boolean(llm.reranker),
  neo4j: Boolean(neo4j),
})

function json(response, status, value, extraHeaders = {}) {
  const body = JSON.stringify(value)
  response.writeHead(status, {
    'Cache-Control': 'no-store',
    'Content-Length': Buffer.byteLength(body),
    'Content-Type': 'application/json; charset=utf-8',
    ...securityHeaders(),
    ...extraHeaders,
  })
  response.end(body)
}

function problem(response, status, code, detail) {
  json(response, status, { code, detail, status, title: 'POC integration request failed' })
}

function securityHeaders() {
  const frameSource = grafanaEmbedEnabled && grafanaUiUrl
    ? new URL(grafanaUiUrl).origin
    : "'none'"
  return {
    'Content-Security-Policy': `default-src 'self'; base-uri 'self'; connect-src 'self'; font-src 'self'; form-action 'self'; frame-ancestors 'none'; frame-src ${frameSource}; img-src 'self' data:; object-src 'none'; script-src 'self'; style-src 'self'`,
    'Permissions-Policy': 'camera=(), geolocation=(), microphone=(), payment=(), usb=()',
    'Referrer-Policy': 'no-referrer',
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
  }
}

async function bodyBuffer(request, limit = maximumJsonBytes) {
  const chunks = []
  let size = 0
  for await (const chunk of request) {
    size += chunk.length
    if (size > limit) throw Object.assign(new Error('Request body is too large.'), { statusCode: 413 })
    chunks.push(chunk)
  }
  return Buffer.concat(chunks)
}

async function bodyJson(request) {
  const body = await bodyBuffer(request)
  if (body.length === 0) return {}
  const value = JSON.parse(body.toString('utf8'))
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw Object.assign(new Error('A JSON object is required.'), { statusCode: 400 })
  }
  return value
}

function boundedString(value, maximum, fallback = '') {
  return typeof value === 'string' && value.length <= maximum ? value : fallback
}

function joinProviderUrl(base, suffix) {
  return `${base.replace(/\/$/, '')}/${suffix.replace(/^\//, '')}`
}

async function providerFetch(url, options = {}) {
  return fetch(url, {
    ...options,
    redirect: 'error',
    signal: AbortSignal.timeout(providerTimeoutMs),
  })
}

async function requireOk(response, label) {
  if (!response.ok) throw new Error(`${label} returned HTTP ${response.status}.`)
  return response
}

const datahubSearchQuery = `
query DataRiverPocCatalog($input: ScrollAcrossEntitiesInput!) {
  scrollAcrossEntities(input: $input) {
    nextScrollId count total
    searchResults {
      entity {
        urn type
        ... on Dataset {
          name
          platform { urn name }
          properties { name description created customProperties { key value } }
          editableProperties { description }
          browsePathV2 {
            path {
              name
              entity {
                urn type
                ... on Container {
                  properties { name qualifiedName }
                  subTypes { typeNames }
                }
              }
            }
          }
          domain { domain { urn } }
          ownership { owners { owner { ... on CorpUser { urn } ... on CorpGroup { urn } } } }
          globalTags: tags { tags { tag { name properties { name } } } }
          glossaryTerms { terms { term { urn name } } }
          schemaMetadata {
            fields {
              fieldPath label type nativeDataType description
              globalTags { tags { tag { urn name properties { name } } } }
              glossaryTerms { terms { term { urn name } } }
            }
          }
        }
      }
    }
  }
}`

const datahubAssetQuery = `
query DataRiverPocAsset($urn: String!) {
  entity(urn: $urn) {
    urn type
    ... on Dataset {
      name
      platform { urn name }
      properties { name description created }
      editableProperties { description }
      browsePathV2 {
        path {
          name
          entity {
            urn type
            ... on Container {
              properties { name qualifiedName }
              subTypes { typeNames }
            }
          }
        }
      }
      domain { domain { urn } }
      ownership { owners { owner { ... on CorpUser { urn } ... on CorpGroup { urn } } type } }
      globalTags: tags { tags { tag { urn name properties { name } } } }
      glossaryTerms { terms { term { urn name } } }
      schemaMetadata {
        fields {
          fieldPath label type nativeDataType description
          globalTags { tags { tag { urn name properties { name } } } }
          glossaryTerms { terms { term { urn name } } }
        }
      }
    }
  }
}`

const datahubLineageQuery = `
query DataRiverPocLineage($urn: String!, $input: LineageInput!) {
  dataset(urn: $urn) {
    lineage(input: $input) { total relationships { entity { urn type } } }
  }
}`

async function datahubGraphql(query, variables) {
  if (!datahub) throw Object.assign(new Error('DataHub is not configured.'), { statusCode: 503 })
  const response = await providerFetch(joinProviderUrl(datahub.url, '/api/graphql'), {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${datahub.token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ query, variables }),
  })
  await requireOk(response, 'DataHub')
  const payload = await response.json()
  if (payload.errors?.length) throw new Error('DataHub rejected the fixed POC GraphQL query.')
  return payload.data
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

function tagNames(entity) {
  return (entity.globalTags?.tags || []).map((item) => item.tag?.properties?.name || item.tag?.name).filter(Boolean)
}

function datasetAsset(entity) {
  const identity = datasetIdentity(entity)
  const tags = tagNames(entity)
  const classificationTag = tags.find((tag) => tag.toUpperCase().startsWith('CLASSIFICATION:'))
  const classification = classificationTag?.split(':').at(-1)?.toUpperCase() || 'INTERNAL'
  const owner = urnTail(entity.ownership?.owners?.[0]?.owner?.urn) || 'DataHub'
  const domain = urnTail(entity.domain?.domain?.urn) || ''
  const description = entity.editableProperties?.description || entity.properties?.description || ''
  return {
    id: entity.urn,
    external_urn: entity.urn,
    asset_type: entity.type || 'DATASET',
    name: identity.tableName,
    description,
    platform: entity.platform?.name || urnTail(entity.platform?.urn),
    database_name: identity.databaseName,
    schema_name: identity.schemaName,
    owner,
    domain,
    tags,
    terms: (entity.glossaryTerms?.terms || []).map((item) => item.term?.name).filter(Boolean),
    created_at: entity.properties?.created ? new Date(Number(entity.properties.created)).toISOString() : null,
    classification,
    lifecycle: 'ACTIVE',
    observed_at: new Date().toISOString(),
    matches: [{ field: 'NAME', text: identity.tableName, matched_terms: [] }],
  }
}

function catalogMeta() {
  const now = new Date().toISOString()
  return {
    observed_at: now,
    stale_at: null,
    projection_version: 1,
    policy_version: 'POC_LIVE_PROVIDER_V1',
    classification_policy_version: 1,
    authorization_generation: 1,
  }
}

function pruneCursorEntries() {
  const now = Date.now()
  for (const [key, entry] of cursorEntries) {
    if (entry.expiresAt <= now) cursorEntries.delete(key)
  }
  while (cursorEntries.size >= maximumCursorEntries) {
    const oldest = cursorEntries.keys().next().value
    if (!oldest) break
    cursorEntries.delete(oldest)
  }
}

function issueCursor(scope, value) {
  pruneCursorEntries()
  const token = randomUUID()
  cursorEntries.set(token, { scope, value, expiresAt: Date.now() + datahubCursorTtlMs })
  return token
}

function cursorValue(token, scope) {
  if (!token) return undefined
  pruneCursorEntries()
  const entry = cursorEntries.get(token)
  if (!entry || entry.scope !== scope) {
    throw Object.assign(new Error('The POC cursor is invalid, expired or belongs to a different query.'), { statusCode: 400 })
  }
  return entry.value
}

async function datahubCatalogPage(query, limit, providerCursor) {
  const input = {
    types: ['DATASET'],
    query,
    count: limit,
    keepAlive: '1m',
    sortInput: { sortCriteria: [{ field: 'urn', sortOrder: 'ASCENDING' }] },
    searchFlags: { skipAggregates: true, skipHighlighting: true },
  }
  if (providerCursor) input.scrollId = providerCursor
  const data = await datahubGraphql(datahubSearchQuery, {
    input,
  })
  const page = data.scrollAcrossEntities
  const items = (page?.searchResults || []).map((item) => datasetAsset(item.entity))
  const nextProviderCursor = typeof page?.nextScrollId === 'string' && page.nextScrollId
    ? page.nextScrollId
    : undefined
  if (nextProviderCursor && nextProviderCursor === providerCursor) {
    throw Object.assign(new Error('DataHub returned a repeated scroll cursor.'), { statusCode: 502 })
  }
  return { items, total: Number(page?.total ?? items.length), nextProviderCursor }
}

async function datahubInventory() {
  const now = Date.now()
  if (inventorySnapshot?.expiresAt > now) return inventorySnapshot.items
  if (inventorySnapshot?.promise) return inventorySnapshot.promise
  const promise = (async () => {
    const items = []
    const observed = new Set()
    let providerCursor
    for (let pageNumber = 0; pageNumber < maximumInventoryPages; pageNumber += 1) {
      const page = await datahubCatalogPage('*', 100, providerCursor)
      for (const item of page.items) {
        if (!observed.has(item.id)) {
          observed.add(item.id)
          items.push(item)
        }
      }
      if (!page.nextProviderCursor) {
        inventorySnapshot = { items, expiresAt: Date.now() + datahubInventoryTtlMs }
        return items
      }
      providerCursor = page.nextProviderCursor
    }
    throw Object.assign(new Error('DataHub inventory exceeded the configured reconciliation page bound.'), { statusCode: 503 })
  })()
  inventorySnapshot = { promise, expiresAt: 0 }
  try {
    return await promise
  } catch (error) {
    inventorySnapshot = undefined
    throw error
  }
}

function assetMatches(asset, searchParameters) {
  const query = boundedString(searchParameters.get('q'), 500, '*').trim().toLowerCase()
  const searchable = [
    asset.name, asset.description, asset.platform, asset.database_name, asset.schema_name,
    asset.owner, asset.domain, ...(asset.tags || []), ...(asset.terms || []),
  ].filter(Boolean).join(' ').toLowerCase()
  const exact = (parameter, value) => {
    const expected = searchParameters.get(parameter)
    return !expected || expected === value
  }
  return (query === '' || query === '*' || searchable.includes(query))
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

function offsetPage(items, searchParameters, scope, defaultLimit = 100) {
  const requested = Number(searchParameters.get('limit') || defaultLimit)
  const limit = Math.min(100, Math.max(1, Number.isFinite(requested) ? requested : defaultLimit))
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

async function datahubCatalog(searchParameters) {
  const query = boundedString(searchParameters.get('q'), 500, '*') || '*'
  const requested = Number(searchParameters.get('limit') || 50)
  const limit = Math.min(100, Math.max(1, Number.isFinite(requested) ? requested : 50))
  const filterKeys = ['asset_type', 'platform', 'database', 'schema', 'domain', 'classification', 'lifecycle']
  const hasExactFilter = filterKeys.some((key) => searchParameters.has(key))
  if (hasExactFilter) {
    const allItems = (await datahubInventory()).filter((item) => assetMatches(item, searchParameters))
    const scope = parameterScope('catalog-filtered', searchParameters, ['q', ...filterKeys, 'search_fields', 'limit'])
    const page = offsetPage(allItems, searchParameters, scope, limit)
    return {
      ...page,
      total: allItems.length,
      total_exact: true,
      meta: catalogMeta(),
      match_mode: 'ALL',
    }
  }
  const scope = parameterScope('catalog-provider', searchParameters, ['q', 'search_fields', 'limit'])
  const providerCursor = cursorValue(searchParameters.get('cursor'), scope)
  const page = await datahubCatalogPage(query, limit, providerCursor)
  return {
    items: page.items,
    page: {
      next_cursor: page.nextProviderCursor ? issueCursor(scope, page.nextProviderCursor) : null,
      limit,
    },
    total: page.total,
    total_exact: true,
    meta: catalogMeta(),
    match_mode: 'ALL',
  }
}

function uniqueValues(values) {
  return [...new Set(values.filter((value) => typeof value === 'string' && value.trim()))]
    .sort((left, right) => left.localeCompare(right))
}

async function datahubTree(searchParameters) {
  const assets = await datahubInventory()
  const parentKind = searchParameters.get('parent_kind') || 'ROOT'
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
      has_children: assets.some((asset) => asset.platform === value && asset.database_name),
      platform: value,
    }))
  } else if (parentKind === 'PLATFORM') {
    items = uniqueValues(assets
      .filter((asset) => asset.platform === platform)
      .map((asset) => asset.database_name)).map((value) => ({
      id: `DATABASE:${platform}:${value}`,
      kind: 'DATABASE',
      label: value,
      asset_count: assets.filter((asset) => asset.platform === platform && asset.database_name === value).length,
      has_children: assets.some((asset) => asset.platform === platform && asset.database_name === value && asset.schema_name),
      platform,
      database_name: value,
    }))
  } else if (parentKind === 'DATABASE') {
    items = uniqueValues(assets
      .filter((asset) => asset.platform === platform && asset.database_name === databaseName)
      .map((asset) => asset.schema_name)).map((value) => ({
      id: `SCHEMA:${platform}:${databaseName}:${value}`,
      kind: 'SCHEMA',
      label: value,
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
        asset,
      }))
  } else {
    throw Object.assign(new Error('Unsupported DataHub hierarchy parent kind.'), { statusCode: 400 })
  }
  const scope = parameterScope('catalog-tree', searchParameters, ['parent_kind', 'platform', 'database', 'schema', 'limit'])
  return { ...offsetPage(items, searchParameters, scope), meta: catalogMeta() }
}

function facetCounts(values) {
  const counts = new Map()
  for (const value of values) {
    if (typeof value === 'string' && value) counts.set(value, (counts.get(value) || 0) + 1)
  }
  return [...counts].map(([value, count]) => ({ value, count }))
    .sort((left, right) => left.value.localeCompare(right.value))
}

async function datahubFacets(searchParameters) {
  const assets = (await datahubInventory()).filter((asset) => assetMatches(asset, searchParameters))
  return {
    asset_types: facetCounts(assets.map((item) => item.asset_type)),
    platforms: facetCounts(assets.map((item) => item.platform)),
    classifications: facetCounts(assets.map((item) => item.classification)),
    databases: facetCounts(assets.map((item) => item.database_name)),
    schemas: facetCounts(assets.map((item) => item.schema_name)),
    domains: facetCounts(assets.map((item) => item.domain)),
    lifecycles: facetCounts(assets.map((item) => item.lifecycle)),
    meta: catalogMeta(),
  }
}

async function datahubDashboard() {
  const assets = await datahubInventory()
  const schemaMetrics = new Map()
  const glossaryTerms = new Set()
  for (const asset of assets) {
    const key = [asset.platform, asset.database_name, asset.schema_name].join('\u0000')
    const current = schemaMetrics.get(key) || {
      platform: asset.platform,
      database_name: asset.database_name,
      schema_name: asset.schema_name,
      asset_count: 0,
      described_asset_count: 0,
    }
    current.asset_count += 1
    if (asset.description?.trim()) current.described_asset_count += 1
    schemaMetrics.set(key, current)
    for (const term of asset.terms || []) glossaryTerms.add(term)
  }
  return {
    observed_at: new Date().toISOString(),
    changes_by_state: {},
    catalog_asset_count: assets.length,
    catalog_described_asset_count: assets.filter((asset) => asset.description?.trim()).length,
    catalog_glossary_term_count: glossaryTerms.size,
    catalog_schema_metrics: [...schemaMetrics.values()].slice(0, 200),
    catalog_schema_metrics_truncated: schemaMetrics.size > 200,
  }
}

async function datahubSystems() {
  return {
    items: uniqueValues((await datahubInventory()).map((asset) => asset.platform)).map((platform, index) => ({
      id: platform,
      code: platform.toUpperCase().replace(/[^A-Z0-9]+/g, '_') || `DATAHUB_${index + 1}`,
      name: platform,
    })),
  }
}

async function datahubAsset(urn, requestedOffset = 0, requestedLimit = 100) {
  const data = await datahubGraphql(datahubAssetQuery, { urn })
  if (!data.entity) throw Object.assign(new Error('DataHub asset was not found.'), { statusCode: 404 })
  const asset = datasetAsset(data.entity)
  const fields = data.entity.schemaMetadata?.fields || []
  const fieldOffset = Math.max(0, Number.isInteger(requestedOffset) ? requestedOffset : 0)
  const fieldLimit = Math.min(100, Math.max(1, Number.isInteger(requestedLimit) ? requestedLimit : 100))
  const pageFields = fields.slice(fieldOffset, fieldOffset + fieldLimit)
  return {
    ...asset,
    ownership: (data.entity.ownership?.owners || []).map((item) => ({
      owner: urnTail(item.owner?.urn),
      type: item.type || 'TECHNICAL_OWNER',
    })),
    glossary_terms: (data.entity.glossaryTerms?.terms || []).map((item) => ({
      urn: item.term?.urn,
      name: item.term?.name,
    })),
    schema_fields: pageFields.map((field) => ({
      fieldPath: field.fieldPath,
      label: field.label || null,
      type: field.type || null,
      nativeDataType: field.nativeDataType || null,
      description: field.description || null,
      globalTags: field.globalTags || { tags: [] },
      glossaryTerms: field.glossaryTerms || { terms: [] },
      nullable: true,
    })),
    schema_fields_total: fields.length,
    schema_fields_available: fields.length,
    schema_fields_truncated: false,
    schema_fields_total_exact: true,
    schema_fields_offset: fieldOffset,
    schema_fields_limit: fieldLimit,
    schema_fields_has_more: fieldOffset + pageFields.length < fields.length,
    // The original Catalog detail contract always exposes an object here.
    // DataHub does not provide the governed Quality projection in this POC,
    // so retain the shape without inventing row/size values.
    quality: {},
    projection_source_version: 'datahub-live-poc',
    source_version: 'datahub-live',
  }
}

async function datahubLineage(urn) {
  const directions = await Promise.all(['UPSTREAM', 'DOWNSTREAM'].map(async (direction) => {
    const data = await datahubGraphql(datahubLineageQuery, {
      urn,
      input: { direction, start: 0, count: 100 },
    })
    return { direction, relationships: data.dataset?.lineage?.relationships || [] }
  }))
  const center = await datahubAsset(urn)
  const nodes = new Map([[urn, center]])
  const edges = []
  for (const group of directions) {
    for (const relationship of group.relationships) {
      const relatedUrn = relationship.entity?.urn
      if (!relatedUrn || nodes.has(relatedUrn)) continue
      const name = urnTail(relatedUrn)
      nodes.set(relatedUrn, {
        id: relatedUrn,
        external_urn: relatedUrn,
        asset_type: relationship.entity?.type || 'DATASET',
        name,
        description: '',
        platform: '', database_name: '', schema_name: '', owner: '', domain: '',
        tags: [], terms: [], created_at: null, classification: 'INTERNAL', lifecycle: 'ACTIVE',
        observed_at: new Date().toISOString(), matches: [],
      })
      edges.push(group.direction === 'UPSTREAM'
        ? { source_asset_id: relatedUrn, target_asset_id: urn }
        : { source_asset_id: urn, target_asset_id: relatedUrn })
    }
  }
  return {
    center_asset_id: urn,
    nodes: [...nodes.values()],
    edges,
    direction: 'BOTH',
    depth: 1,
    truncated: false,
    meta: catalogMeta(),
  }
}

function basicAuthorization(provider) {
  return `Basic ${Buffer.from(`${provider.username}:${provider.password}`).toString('base64')}`
}

async function airflowRequest(path, options = {}) {
  if (!airflow) throw Object.assign(new Error('Airflow is not configured.'), { statusCode: 503 })
  const response = await providerFetch(joinProviderUrl(airflow.url, path), {
    ...options,
    headers: {
      Authorization: basicAuthorization(airflow),
      'Content-Type': 'application/json',
      ...options.headers,
    },
  })
  await requireOk(response, 'Airflow')
  return response
}

async function llmRequest(provider, endpoint, body) {
  if (!provider) throw Object.assign(new Error('The requested LLM stage is not configured.'), { statusCode: 503 })
  const response = await providerFetch(joinProviderUrl(provider.url, endpoint), {
    method: 'POST',
    headers: { Authorization: `Bearer ${provider.token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  await requireOk(response, `LLM ${endpoint}`)
  return response.json()
}

async function liveChat(question) {
  let evidence = []
  if (datahub) {
    const catalog = await datahubCatalog(new URLSearchParams({ q: question, limit: '5' }))
    evidence = catalog.items
  }
  if (llm.embedding) {
    await llmRequest(llm.embedding, '/embeddings', { model: llm.embedding.model, input: question })
  }
  if (llm.reranker && evidence.length > 1) {
    const reranked = await llmRequest(llm.reranker, '/rerank', {
      model: llm.reranker.model,
      query: question,
      documents: evidence.map((item) => `${item.name}\n${item.description}`),
      top_n: Math.min(5, evidence.length),
    })
    const indices = (reranked.results || reranked.data || []).map((item) => Number(item.index))
    const ordered = indices.map((index) => evidence[index]).filter(Boolean)
    if (ordered.length) evidence = ordered
  }
  const context = evidence.map((item, index) => `[${index + 1}] ${item.name}: ${item.description}`).join('\n')
  const completion = await llmRequest(llm.chat, '/chat/completions', {
    model: llm.chat.model,
    stream: false,
    temperature: 0,
    messages: [
      { role: 'system', content: 'Answer only from the supplied DataHub context. State clearly when evidence is insufficient.' },
      { role: 'user', content: `Question: ${question}\n\nDataHub context:\n${context || '(no DataHub evidence)'}` },
    ],
  })
  const answer = completion.choices?.[0]?.message?.content
  if (typeof answer !== 'string' || !answer.trim()) throw new Error('The Chat model returned no answer.')
  return { answer: answer.trim(), evidence }
}

function sha256(value) {
  return createHash('sha256').update(value).digest('hex')
}

function hmac(key, value) {
  return createHmac('sha256', key).update(value).digest()
}

function awsEncode(value) {
  return encodeURIComponent(value).replace(/[!'()*]/g, (character) => `%${character.charCodeAt(0).toString(16).toUpperCase()}`)
}

async function minioObject(method, bucket, key, body = Buffer.alloc(0), contentType = 'application/octet-stream') {
  if (!minio) throw Object.assign(new Error('MinIO is not configured.'), { statusCode: 503 })
  if (!Object.values(minio.buckets).includes(bucket)) throw Object.assign(new Error('Bucket is not allowlisted.'), { statusCode: 400 })
  const endpoint = new URL(minio.url)
  const canonicalPath = `${endpoint.pathname.replace(/\/$/, '')}/${awsEncode(bucket)}/${key.split('/').map(awsEncode).join('/')}`
  const payloadHash = sha256(body)
  const now = new Date()
  const amzDate = now.toISOString().replace(/[:-]|\.\d{3}/g, '')
  const date = amzDate.slice(0, 8)
  const host = endpoint.host
  const signedHeaders = 'host;x-amz-content-sha256;x-amz-date'
  const canonicalHeaders = `host:${host}\nx-amz-content-sha256:${payloadHash}\nx-amz-date:${amzDate}\n`
  const canonicalRequest = `${method}\n${canonicalPath}\n\n${canonicalHeaders}\n${signedHeaders}\n${payloadHash}`
  const scope = `${date}/${minio.region}/s3/aws4_request`
  const stringToSign = `AWS4-HMAC-SHA256\n${amzDate}\n${scope}\n${sha256(canonicalRequest)}`
  const dateKey = hmac(`AWS4${minio.secretKey}`, date)
  const regionKey = hmac(dateKey, minio.region)
  const serviceKey = hmac(regionKey, 's3')
  const signingKey = hmac(serviceKey, 'aws4_request')
  const signature = createHmac('sha256', signingKey).update(stringToSign).digest('hex')
  const url = new URL(endpoint)
  url.pathname = canonicalPath
  const response = await providerFetch(url, {
    method,
    headers: {
      Authorization: `AWS4-HMAC-SHA256 Credential=${minio.accessKey}/${scope}, SignedHeaders=${signedHeaders}, Signature=${signature}`,
      'Content-Type': contentType,
      'x-amz-content-sha256': payloadHash,
      'x-amz-date': amzDate,
    },
    body: ['GET', 'HEAD'].includes(method) ? undefined : body,
  })
  await requireOk(response, 'MinIO')
  return response
}

async function neo4jQuery(statement, parameters = {}) {
  if (!neo4j) throw Object.assign(new Error('Neo4j is not configured.'), { statusCode: 503 })
  const response = await providerFetch(joinProviderUrl(neo4j.url, '/db/neo4j/tx/commit'), {
    method: 'POST',
    headers: { Authorization: basicAuthorization(neo4j), 'Content-Type': 'application/json' },
    body: JSON.stringify({ statements: [{ statement, parameters, resultDataContents: ['row'] }] }),
  })
  await requireOk(response, 'Neo4j')
  const payload = await response.json()
  if (payload.errors?.length) throw new Error(`Neo4j query failed: ${payload.errors[0]?.code || 'UNKNOWN'}`)
  return payload.results?.[0]?.data || []
}

async function neo4jGraph() {
  const rows = await neo4jQuery(`
    MATCH (source:PocEntity)
    OPTIONAL MATCH (source)-[relation]->(target:PocEntity)
    RETURN source.id, source.name, source.entity_type, type(relation), target.id, target.name, target.entity_type
    ORDER BY source.id, target.id
    LIMIT 100
  `)
  const nodes = new Map()
  const edges = []
  for (const item of rows) {
    const row = item.row || []
    nodes.set(row[0], { id: row[0], name: row[1], entity_type: row[2] || 'CLASS' })
    if (row[4]) {
      nodes.set(row[4], { id: row[4], name: row[5], entity_type: row[6] || 'CLASS' })
      edges.push({ id: `${row[0]}-${row[3]}-${row[4]}`, source_id: row[0], target_id: row[4], edge_type: row[3] })
    }
  }
  return { nodes: [...nodes.values()], edges }
}

async function providerState(name, enabled, probe) {
  if (!enabled) return { name, state: 'disabled', observed_at: new Date().toISOString(), latency_ms: null, detail_code: 'NOT_CONFIGURED' }
  const started = Date.now()
  try {
    await probe()
    return { name, state: 'available', observed_at: new Date().toISOString(), latency_ms: Date.now() - started, detail_code: 'LIVE' }
  } catch {
    return { name, state: 'unavailable', observed_at: new Date().toISOString(), latency_ms: Date.now() - started, detail_code: 'PROBE_FAILED' }
  }
}

async function capabilities() {
  const items = await Promise.all([
    providerState('DataHub', Boolean(datahub), async () => requireOk(await providerFetch(joinProviderUrl(datahub.url, '/config'), { headers: { Authorization: `Bearer ${datahub.token}` } }), 'DataHub')),
    providerState('Airflow', Boolean(airflow), async () => airflowRequest('/api/v2/monitor/health')),
    providerState('MinIO', Boolean(minio), async () => requireOk(await providerFetch(joinProviderUrl(minio.url, '/minio/health/live')), 'MinIO')),
    providerState('LLM Chat', Boolean(llm.chat), async () => requireOk(await providerFetch(joinProviderUrl(llm.chat.url, '/models'), { headers: { Authorization: `Bearer ${llm.chat.token}` } }), 'LLM Chat')),
    providerState('LLM Embedding', Boolean(llm.embedding), async () => requireOk(await providerFetch(joinProviderUrl(llm.embedding.url, '/models'), { headers: { Authorization: `Bearer ${llm.embedding.token}` } }), 'LLM Embedding')),
    providerState('LLM Reranker', Boolean(llm.reranker), async () => {
      const payload = await llmRequest(llm.reranker, '/rerank', {
        model: llm.reranker.model,
        query: 'DataRiver capability probe',
        documents: ['DataRiver capability probe'],
        top_n: 1,
      })
      const results = payload.results || payload.data
      if (!Array.isArray(results)) throw new Error('LLM Reranker returned no ordered results.')
    }),
    providerState('Neo4j', Boolean(neo4j), async () => neo4jQuery('RETURN 1')),
  ])
  const grafanaAvailable = Boolean(
    grafanaEmbedEnabled && grafanaUiUrl && grafanaEmbedBaseUrl && grafanaEvidenceReference,
  )
  const monitoringItems = grafanaUiUrl ? [{
    id: 'poc-grafana-dashboard',
    label: 'Grafana',
    url: grafanaUiUrl,
    height_px: 900,
    embed_state: grafanaAvailable ? 'AVAILABLE' : 'DISABLED',
    ...(grafanaAvailable ? { embed_url: grafanaUiUrl } : {}),
  }] : []
  return {
    items,
    external_system_links: datahubUiUrl ? [{ id: 'datahub', label: 'DataHub', url: datahubUiUrl }] : [],
    grafana_embed: grafanaAvailable
      ? { state: 'AVAILABLE', url: grafanaUiUrl }
      : { state: grafanaUiUrl ? 'DISABLED' : 'NOT_CONFIGURED' },
    monitoring_configuration: { version: 1, items: monitoringItems },
    deployment_tier: 'SINGLE_NODE_PILOT',
  }
}

async function api(request, response, url) {
  if (request.method === 'GET' && url.pathname === '/poc-api/capabilities') return json(response, 200, await capabilities())
  if (request.method === 'GET' && url.pathname === '/poc-api/datahub/catalog') return json(response, 200, await datahubCatalog(url.searchParams))
  if (request.method === 'GET' && url.pathname === '/poc-api/datahub/tree') return json(response, 200, await datahubTree(url.searchParams))
  if (request.method === 'GET' && url.pathname === '/poc-api/datahub/facets') return json(response, 200, await datahubFacets(url.searchParams))
  if (request.method === 'GET' && url.pathname === '/poc-api/datahub/dashboard') return json(response, 200, await datahubDashboard())
  if (request.method === 'GET' && url.pathname === '/poc-api/datahub/systems') return json(response, 200, await datahubSystems())
  if (request.method === 'GET' && url.pathname === '/poc-api/datahub/asset') return json(response, 200, await datahubAsset(
    boundedString(url.searchParams.get('urn'), 4096),
    Number(url.searchParams.get('field_offset') || 0),
    Number(url.searchParams.get('field_limit') || 100),
  ))
  if (request.method === 'GET' && url.pathname === '/poc-api/datahub/lineage') return json(response, 200, await datahubLineage(boundedString(url.searchParams.get('urn'), 4096)))
  if (request.method === 'POST' && url.pathname === '/poc-api/llm/chat') {
    const body = await bodyJson(request)
    const question = boundedString(body.question, 4000)
    if (!question.trim()) return problem(response, 400, 'QUESTION_REQUIRED', 'A non-empty question is required.')
    return json(response, 200, await liveChat(question))
  }
  const airflowMatch = url.pathname.match(/^\/poc-api\/airflow\/dags\/([^/]+)\/runs$/)
  if (request.method === 'POST' && airflowMatch) {
    const dagId = decodeURIComponent(airflowMatch[1])
    if (!allowedAirflowDags.has(dagId)) return problem(response, 400, 'DAG_NOT_ALLOWED', 'The DAG is not allowlisted for this POC.')
    const body = await bodyJson(request)
    const runId = `poc-${Date.now()}`
    const upstream = await airflowRequest(`/api/v2/dags/${encodeURIComponent(dagId)}/dagRuns`, {
      method: 'POST',
      body: JSON.stringify({ dag_run_id: runId, conf: { poc: true, ...body.conf } }),
    })
    return json(response, 202, { dag_id: dagId, run_id: runId, upstream: await upstream.json() })
  }
  const minioPart = url.pathname.match(/^\/poc-api\/minio\/uploads\/([a-zA-Z0-9_-]+)\/parts\/(\d+)$/)
  if (request.method === 'PUT' && minioPart) {
    if (!minio) return problem(response, 503, 'MINIO_NOT_CONFIGURED', 'MinIO is not configured.')
    const partNumber = Number(minioPart[2])
    if (!Number.isInteger(partNumber) || partNumber < 1 || partNumber > 100) {
      return problem(response, 400, 'PART_NUMBER_INVALID', 'Part number must be between 1 and 100.')
    }
    const body = await bodyBuffer(request, maximumObjectBytes)
    const key = `poc-uploads/${minioPart[1]}/part-${partNumber}`
    const contentType = boundedString(request.headers['content-type'], 255, 'application/octet-stream')
    const upstream = await minioObject('PUT', minio.buckets.quarantine, key, body, contentType)
    response.writeHead(200, { ETag: upstream.headers.get('etag') || `"${sha256(body)}"`, ...securityHeaders() })
    return response.end()
  }
  const minioComplete = url.pathname.match(/^\/poc-api\/minio\/uploads\/([a-zA-Z0-9_-]+)\/complete$/)
  if (request.method === 'POST' && minioComplete) {
    if (!minio) return problem(response, 503, 'MINIO_NOT_CONFIGURED', 'MinIO is not configured.')
    const body = await bodyJson(request)
    const parts = Number(body.part_count || 1)
    if (!Number.isInteger(parts) || parts < 1 || parts > 100) {
      return problem(response, 400, 'PART_COUNT_INVALID', 'Part count must be between 1 and 100.')
    }
    const chunks = []
    let size = 0
    for (let part = 1; part <= parts; part += 1) {
      const upstream = await minioObject('GET', minio.buckets.quarantine, `poc-uploads/${minioComplete[1]}/part-${part}`)
      const chunk = Buffer.from(await upstream.arrayBuffer())
      size += chunk.length
      if (size > maximumObjectBytes) throw Object.assign(new Error('Completed upload is too large.'), { statusCode: 413 })
      chunks.push(chunk)
    }
    const object = Buffer.concat(chunks)
    const displayName = boundedString(body.display_name, 255, 'upload.bin').replace(/[^a-zA-Z0-9._-]/g, '_')
    const key = `poc-accepted/${minioComplete[1]}/${displayName}`
    await minioObject('PUT', minio.buckets.accepted, key, object, boundedString(body.content_type, 255, 'application/octet-stream'))
    return json(response, 200, { bucket: minio.buckets.accepted, key, size_bytes: object.length, sha256: sha256(object) })
  }
  if (request.method === 'GET' && url.pathname === '/poc-api/neo4j/graph') return json(response, 200, await neo4jGraph())
  return problem(response, 404, 'NOT_FOUND', 'The POC gateway route does not exist.')
}

const mimeTypes = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.woff2': 'font/woff2',
}

function staticFile(requestPath) {
  const decoded = decodeURIComponent(requestPath)
  const normalizedPath = normalize(decoded).replace(/^[/\\]+/, '')
  const candidate = resolve(staticDirectory, normalizedPath || 'poc.html')
  if (!candidate.startsWith(`${staticDirectory}${sep}`)) return undefined
  if (existsSync(candidate) && statSync(candidate).isFile()) return candidate
  return join(staticDirectory, 'poc.html')
}

function serveStatic(request, response, url) {
  const file = staticFile(url.pathname)
  if (!file || !existsSync(file)) return problem(response, 404, 'STATIC_NOT_FOUND', 'POC static build is missing.')
  const extension = extname(file)
  const headers = {
    'Cache-Control': extension === '.html' ? 'no-store' : 'public, max-age=31536000, immutable',
    'Content-Type': mimeTypes[extension] || 'application/octet-stream',
    ...securityHeaders(),
  }
  if (extension === '.html') {
    const body = readFileSync(file, 'utf8').replace('</head>', '  <script src="/poc-runtime-config.js"></script>\n  </head>')
    response.writeHead(200, { ...headers, 'Content-Length': Buffer.byteLength(body) })
    return response.end(request.method === 'HEAD' ? undefined : body)
  }
  const size = statSync(file).size
  response.writeHead(200, { ...headers, 'Content-Length': size })
  if (request.method === 'HEAD') return response.end()
  return createReadStream(file).pipe(response)
}

export function createPocServer() {
  return createServer(async (request, response) => {
    try {
      const url = new URL(request.url || '/', 'http://poc.invalid')
      if (url.pathname === '/healthz') {
        response.writeHead(200, { 'Content-Type': 'text/plain; charset=utf-8', ...securityHeaders() })
        return response.end('ok\n')
      }
      if (url.pathname === '/poc-runtime-config.js') {
        const body = `globalThis.__DATARIVER_POC_RUNTIME__=${JSON.stringify(runtimeFlags)};\n`
        response.writeHead(200, { 'Cache-Control': 'no-store', 'Content-Type': 'text/javascript; charset=utf-8', ...securityHeaders() })
        return response.end(body)
      }
      if (url.pathname.startsWith('/poc-api/')) return await api(request, response, url)
      if (!['GET', 'HEAD'].includes(request.method || '')) return problem(response, 405, 'METHOD_NOT_ALLOWED', 'Only static GET/HEAD is supported.')
      return serveStatic(request, response, url)
    } catch (error) {
      const status = Number(error?.statusCode) || (error instanceof SyntaxError ? 400 : 502)
      return problem(response, status, 'POC_PROVIDER_ERROR', error instanceof Error ? error.message : 'Provider request failed.')
    }
  })
}

export async function startPocServer() {
  if (!existsSync(join(staticDirectory, 'poc.html'))) throw new Error('Run npm run build:poc before starting the POC server.')
  const server = createPocServer()
  const host = process.env.POC_SERVER_HOST?.trim() || '0.0.0.0'
  const port = Number(process.env.POC_SERVER_PORT || process.env.POC_PORT || 39080)
  await new Promise((resolvePromise) => server.listen(port, host, resolvePromise))
  process.stdout.write(`DataRiver POC listening on http://${host}:${port}\n`)
  return server
}

if (resolve(process.argv[1] || '') === resolve(fileURLToPath(import.meta.url))) {
  startPocServer().catch((error) => {
    process.stderr.write(`${error instanceof Error ? error.stack : String(error)}\n`)
    process.exitCode = 1
  })
}
