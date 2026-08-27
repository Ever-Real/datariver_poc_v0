/* global AbortSignal, Buffer, process */
import { createHash } from 'node:crypto'
import KafkaJs from 'kafkajs'

import { createProviderTransport, joinProviderUrl } from './poc-provider-transport.mjs'

const { Kafka, logLevel } = KafkaJs
const VERSIONED_MCL_TOPIC = /(?:^|[._-])MetadataChangeLog_Versioned_v1$/u
const DISCOVERY_TIMEOUT_MS = 60_000

function required(value, name) {
  const normalized = typeof value === 'string' ? value.trim() : ''
  if (!normalized) throw discoveryError('CONFIG', `${name} is required.`)
  return normalized
}

function optional(value) {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}

function sha256(value) {
  return createHash('sha256').update(value, 'utf8').digest('hex')
}

function discoveryError(reason, message, cause) {
  return Object.assign(new Error(message, cause ? { cause } : undefined), {
    code: `PREP_MCL_DISCOVERY_${reason}_FAILED`,
    reason,
  })
}

function kafkaConnection(environment) {
  const mechanism = optional(environment.POC_MCL_KAFKA_SASL_MECHANISM)
  const username = optional(environment.POC_MCL_KAFKA_SASL_USERNAME)
  const password = optional(environment.POC_MCL_KAFKA_SASL_PASSWORD)
  if ([mechanism, username, password].some(Boolean) && ![mechanism, username, password].every(Boolean)) {
    throw discoveryError('CONFIG', 'Kafka SASL mechanism, username and password must be configured together.')
  }
  return {
    brokers: required(environment.POC_MCL_KAFKA_BROKERS, 'POC_MCL_KAFKA_BROKERS')
      .split(',').map((value) => value.trim()).filter(Boolean),
    ssl: String(environment.POC_MCL_KAFKA_SSL || 'false').trim().toLowerCase() === 'true',
    sasl: mechanism ? { mechanism, username, password } : undefined,
  }
}

function basicAuthorization(environment) {
  const username = optional(environment.POC_MCL_SCHEMA_REGISTRY_USERNAME)
  const password = optional(environment.POC_MCL_SCHEMA_REGISTRY_PASSWORD)
  if (Boolean(username) !== Boolean(password)) {
    throw discoveryError('CONFIG', 'Schema Registry username and password must be configured together.')
  }
  return username ? `Basic ${Buffer.from(`${username}:${password}`, 'utf8').toString('base64')}` : undefined
}

async function jsonRequest(providerTransport, url, headers = {}) {
  let response
  try {
    response = await providerTransport.fetch(url, {
      headers,
      redirect: 'error',
      signal: AbortSignal.timeout(DISCOVERY_TIMEOUT_MS),
    })
  } catch (error) {
    throw discoveryError('REGISTRY_CONNECTIVITY', 'Schema Registry discovery request failed.', error)
  }
  if (!response.ok) return { ok: false, status: response.status }
  const body = await response.json().catch(() => null)
  if (body === null) throw discoveryError('REGISTRY_CONTRACT', 'Schema Registry returned invalid JSON.')
  return { ok: true, body }
}

async function registryCandidate(providerTransport, baseUrl, authorization, topic, kind) {
  const headers = authorization ? { Authorization: authorization } : {}
  const subjects = await jsonRequest(providerTransport, joinProviderUrl(baseUrl, '/subjects'), headers)
  if (!subjects.ok) return null
  if (!Array.isArray(subjects.body) || !subjects.body.every((value) => typeof value === 'string')) {
    throw discoveryError('REGISTRY_CONTRACT', 'Schema Registry subjects response is invalid.')
  }
  const expected = `${topic}-value`
  const matches = subjects.body.filter((subject) => subject === expected)
  if (matches.length !== 1) {
    throw discoveryError(
      matches.length ? 'REGISTRY_AMBIGUOUS' : 'REGISTRY_SUBJECT',
      'Schema Registry did not expose exactly one canonical MCL value subject.',
    )
  }
  const latest = await jsonRequest(
    providerTransport,
    joinProviderUrl(baseUrl, `/subjects/${encodeURIComponent(expected)}/versions/latest`),
    headers,
  )
  if (!latest?.ok || typeof latest.body?.schema !== 'string' || !latest.body.schema.trim()) {
    throw discoveryError('REGISTRY_CONTRACT', 'Schema Registry latest MCL schema response is invalid.')
  }
  return {
    host: baseUrl.replace(/\/$/u, ''),
    subject: expected,
    schema: latest.body.schema,
    schemaId: Number.isSafeInteger(latest.body.id) ? latest.body.id : null,
    schemaVersion: Number.isSafeInteger(latest.body.version) ? latest.body.version : null,
    schemaType: optional(latest.body.schemaType) || 'AVRO',
    kind,
    authorization,
  }
}

async function discoverRegistry(providerTransport, environment, topic) {
  const datahubUrl = required(environment.DATAHUB_GMS_URL, 'DATAHUB_GMS_URL')
  const datahubToken = required(environment.DATAHUB_GMS_TOKEN, 'DATAHUB_GMS_TOKEN')
  const internal = await registryCandidate(
    providerTransport,
    joinProviderUrl(datahubUrl, '/schema-registry/api'),
    `Bearer ${datahubToken}`,
    topic,
    'DATAHUB_GMS_INTERNAL',
  )
  if (internal) return internal
  const externalUrl = optional(environment.POC_MCL_SCHEMA_REGISTRY_URL)
  if (!externalUrl) {
    throw discoveryError('REGISTRY_UNAVAILABLE', 'DataHub internal Schema Registry was unavailable and no external Registry is configured.')
  }
  const external = await registryCandidate(
    providerTransport,
    externalUrl,
    basicAuthorization(environment),
    topic,
    'EXTERNAL_CONFLUENT',
  )
  if (!external) throw discoveryError('REGISTRY_UNAVAILABLE', 'The configured external Schema Registry is unavailable.')
  return external
}

async function discoverProviderVersion(providerTransport, environment) {
  const url = required(environment.DATAHUB_GMS_URL, 'DATAHUB_GMS_URL')
  const token = required(environment.DATAHUB_GMS_TOKEN, 'DATAHUB_GMS_TOKEN')
  const result = await jsonRequest(providerTransport, joinProviderUrl(url, '/config'), {
    Authorization: `Bearer ${token}`,
  })
  const versions = result?.ok ? result.body?.versions : null
  const version = optional(versions?.['acryldata/datahub']?.version)
    || optional(result?.body?.version)
  if (!version) throw discoveryError('PROVIDER_VERSION', 'DataHub provider version could not be discovered.')
  return version
}

export async function discoverPocMclSource({
  environment = process.env,
  providerTransport,
  kafka,
  clock = () => new Date(),
} = {}) {
  const connection = kafkaConnection(environment)
  const transport = providerTransport ?? createProviderTransport(environment)
  const ownsTransport = !providerTransport
  const kafkaClient = kafka ?? new Kafka({
    ...connection,
    clientId: environment.POC_MCL_KAFKA_CLIENT_ID?.trim() || 'datariver-prep39083-mcl-v1',
    logLevel: logLevel.NOTHING,
  })
  const admin = kafkaClient.admin()
  let connected = false
  try {
    await admin.connect()
    connected = true
    const [cluster, topics, providerVersion] = await Promise.all([
      admin.describeCluster(),
      admin.listTopics(),
      discoverProviderVersion(transport, environment),
    ])
    const clusterId = required(cluster?.clusterId, 'Kafka cluster ID')
    if (!Array.isArray(topics)) throw discoveryError('TOPIC_CONTRACT', 'Kafka topic inventory is invalid.')
    const topicMatches = topics.filter((topic) => typeof topic === 'string' && VERSIONED_MCL_TOPIC.test(topic))
    if (topicMatches.length !== 1) {
      throw discoveryError(topicMatches.length ? 'TOPIC_AMBIGUOUS' : 'TOPIC_NOT_FOUND', 'Kafka did not expose exactly one supported versioned MCL topic.')
    }
    const topic = topicMatches[0]
    const registry = await discoverRegistry(transport, environment, topic)
    const schemaContractHash = sha256(registry.schema)
    const providerName = 'DataHub'
    const descriptor = [
      `provider_name=${providerName}`,
      `provider_version=${providerVersion}`,
      `kafka_cluster_id=${clusterId}`,
      `topic=${topic}`,
      `schema_subject=${registry.subject}`,
      `schema_contract_hash=${schemaContractHash}`,
      '',
    ].join('\n')
    const sourceIdentityHash = sha256(descriptor)
    const captureConfig = {
      brokers: connection.brokers,
      clientId: environment.POC_MCL_KAFKA_CLIENT_ID?.trim() || 'datariver-prep39083-mcl-v1',
      groupId: environment.POC_MCL_KAFKA_GROUP_ID?.trim() || 'datariver-prep39083-mcl-capture-v1',
      topic,
      sourceIdentityHash,
      schemaContractHash,
      providerName,
      providerVersion,
      kafkaSsl: connection.ssl,
      kafkaSasl: connection.sasl,
      schemaRegistry: {
        host: registry.host,
        ...(registry.kind === 'EXTERNAL_CONFLUENT' && registry.authorization
          ? { auth: {
              username: required(environment.POC_MCL_SCHEMA_REGISTRY_USERNAME, 'POC_MCL_SCHEMA_REGISTRY_USERNAME'),
              password: required(environment.POC_MCL_SCHEMA_REGISTRY_PASSWORD, 'POC_MCL_SCHEMA_REGISTRY_PASSWORD'),
            } }
          : {}),
        ...(registry.kind === 'DATAHUB_GMS_INTERNAL' ? { bearerToken: required(environment.DATAHUB_GMS_TOKEN, 'DATAHUB_GMS_TOKEN') } : {}),
      },
      maxMessages: Number(environment.POC_MCL_MAX_MESSAGES || 10_000),
      maxRecordBytes: Number(environment.POC_MCL_MAX_RECORD_BYTES || 1_048_576),
      timeoutMs: Number(environment.POC_MCL_TIMEOUT_MS || 300_000),
    }
    return Object.freeze({
      captureConfig,
      receipt: Object.freeze({
        contract: 'DATARIVER_MCL_DISCOVERY_V1',
        provider_name: providerName,
        provider_version: providerVersion,
        kafka_cluster_id_hash: sha256(clusterId),
        topic,
        schema_subject: registry.subject,
        schema_id: registry.schemaId,
        schema_version: registry.schemaVersion,
        schema_type: registry.schemaType,
        schema_contract_hash: schemaContractHash,
        source_identity_hash: sourceIdentityHash,
        registry_kind: registry.kind,
        discovered_at: clock().toISOString(),
      }),
    })
  } catch (error) {
    if (error?.code?.startsWith('PREP_MCL_DISCOVERY_')) throw error
    throw discoveryError('KAFKA_CONNECTIVITY', 'Kafka MCL discovery failed.', error)
  } finally {
    if (connected) await admin.disconnect().catch(() => undefined)
    if (ownsTransport) await transport.close()
  }
}
