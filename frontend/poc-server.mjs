/* global AbortSignal, Buffer, URL, URLSearchParams, fetch, process */
import { createHmac, createHash } from 'node:crypto'
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

function optionalUrl(name) {
  const raw = process.env[name]?.trim()
  if (!raw) return undefined
  const value = new URL(raw)
  if (!['http:', 'https:'].includes(value.protocol) || value.username || value.password || value.hash) {
    throw new Error(`${name} must be an http(s) URL without credentials or a fragment.`)
  }
  return value.toString().replace(/\/$/, '')
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
  return {
    'Content-Security-Policy': "default-src 'self'; base-uri 'self'; connect-src 'self'; font-src 'self'; form-action 'self'; frame-ancestors 'none'; frame-src 'none'; img-src 'self' data:; object-src 'none'; script-src 'self'; style-src 'self'",
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
    count total
    searchResults {
      entity {
        urn type
        ... on Dataset {
          name
          platform { urn name }
          properties { name description created }
          editableProperties { description }
          browsePathV2 { path { name } }
          domain { domain { urn } }
          ownership { owners { owner { ... on CorpUser { urn } ... on CorpGroup { urn } } } }
          globalTags: tags { tags { tag { name properties { name } } } }
          glossaryTerms { terms { term { urn name } } }
          schemaMetadata { fields { fieldPath } }
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
      browsePathV2 { path { name } }
      domain { domain { urn } }
      ownership { owners { owner { ... on CorpUser { urn } ... on CorpGroup { urn } } type } }
      globalTags: tags { tags { tag { urn name properties { name } } } }
      glossaryTerms { terms { term { urn name } } }
      schemaMetadata { fields { fieldPath label type nativeDataType description } }
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

function datasetIdentity(entity) {
  const match = typeof entity.urn === 'string'
    ? entity.urn.match(/^urn:li:dataset:\([^,]+,([^,]+),[^)]+\)$/)
    : undefined
  const qualifiedName = match?.[1] || ''
  const parts = qualifiedName.split('.').filter(Boolean)
  const path = entity.browsePathV2?.path?.map((item) => item.name).filter(Boolean) || []
  return {
    databaseName: path.at(-3) || parts.at(-3) || '',
    schemaName: path.at(-2) || parts.at(-2) || '',
    tableName: entity.name || entity.properties?.name || parts.at(-1) || urnTail(entity.urn),
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

async function datahubCatalog(searchParameters) {
  const query = boundedString(searchParameters.get('q'), 500, '*') || '*'
  const limit = Math.min(100, Math.max(1, Number(searchParameters.get('limit') || 50)))
  const data = await datahubGraphql(datahubSearchQuery, {
    input: {
      types: ['DATASET'],
      query,
      count: limit,
      keepAlive: '1m',
      searchFlags: { skipAggregates: true, skipHighlighting: true },
    },
  })
  const page = data.scrollAcrossEntities
  const items = (page?.searchResults || []).map((item) => datasetAsset(item.entity))
  return {
    items,
    page: { next_cursor: null, limit },
    total: Number(page?.total ?? items.length),
    total_exact: true,
    meta: catalogMeta(),
    match_mode: 'ALL',
  }
}

async function datahubAsset(urn) {
  const data = await datahubGraphql(datahubAssetQuery, { urn })
  if (!data.entity) throw Object.assign(new Error('DataHub asset was not found.'), { statusCode: 404 })
  const asset = datasetAsset(data.entity)
  const fields = data.entity.schemaMetadata?.fields || []
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
    schema_fields: fields.map((field) => ({
      field_path: field.fieldPath,
      label: field.label || null,
      type: field.type || null,
      native_data_type: field.nativeDataType || null,
      description: field.description || null,
      nullable: true,
    })),
    schema_fields_total: fields.length,
    schema_fields_available: fields.length,
    schema_fields_truncated: false,
    schema_fields_total_exact: true,
    schema_fields_offset: 0,
    schema_fields_limit: 100,
    schema_fields_has_more: false,
    quality: null,
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

async function seedNeo4j() {
  if (!neo4j) return
  await neo4jQuery(`
    MERGE (w:PocEntity {id: 'wafer'}) SET w.name = 'Wafer', w.entity_type = 'CLASS'
    MERGE (i:PocEntity {id: 'inspection'}) SET i.name = 'Inspection', i.entity_type = 'CLASS'
    MERGE (d:PocEntity {id: 'defect'}) SET d.name = 'Defect', d.entity_type = 'CLASS'
    MERGE (w)-[:HAS_INSPECTION]->(i)
    MERGE (i)-[:OBSERVES]->(d)
  `)
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
    providerState('LLM Reranker', Boolean(llm.reranker), async () => requireOk(await providerFetch(llm.reranker.url, { headers: { Authorization: `Bearer ${llm.reranker.token}` } }), 'LLM Reranker')),
    providerState('Neo4j', Boolean(neo4j), async () => neo4jQuery('RETURN 1')),
  ])
  return {
    items,
    external_system_links: datahubUiUrl ? [{ id: 'datahub', label: 'DataHub', url: datahubUiUrl }] : [],
    grafana_embed: { state: 'DISABLED' },
    monitoring_configuration: { version: 1, items: [] },
    deployment_tier: 'SINGLE_NODE_PILOT',
  }
}

async function api(request, response, url) {
  if (request.method === 'GET' && url.pathname === '/poc-api/capabilities') return json(response, 200, await capabilities())
  if (request.method === 'GET' && url.pathname === '/poc-api/datahub/catalog') return json(response, 200, await datahubCatalog(url.searchParams))
  if (request.method === 'GET' && url.pathname === '/poc-api/datahub/asset') return json(response, 200, await datahubAsset(boundedString(url.searchParams.get('urn'), 4096)))
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
  await seedNeo4j()
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
