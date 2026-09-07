/* global AbortSignal, Buffer, URL, process */
import { createHash } from 'node:crypto'
import { isIP } from 'node:net'
import KafkaJs from 'kafkajs'

import { createProviderTransport, joinProviderUrl } from './poc-provider-transport.mjs'

const { Kafka, logLevel } = KafkaJs
const VERSIONED_MCL_TOPIC = /(?:^|[._-])MetadataChangeLog_Versioned_v1$/u
const DISCOVERY_TIMEOUT_MS = 60_000
const KAFKA_CONNECTION_TIMEOUT_MS = 10_000
const KAFKA_REQUEST_TIMEOUT_MS = 30_000
const KAFKA_DISCOVERY_RETRY = Object.freeze({
  initialRetryTime: 300,
  maxRetryTime: 5_000,
  retries: 2,
})
const KAFKA_SASL_MECHANISMS = new Set(['plain', 'scram-sha-256', 'scram-sha-512'])

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

function isDiscoveryError(error) {
  return typeof error?.code === 'string' && error.code.startsWith('PREP_MCL_DISCOVERY_')
}

function brokerEndpoint(value) {
  if (!value || value.includes('://') || /[/?#\s]/u.test(value)) {
    throw discoveryError('CONFIG', 'Kafka brokers must use host:port syntax without a URL scheme.')
  }
  let portText
  if (value.startsWith('[')) {
    const match = /^\[([^\]]+)\]:(\d+)$/u.exec(value)
    if (!match || isIP(match[1]) !== 6) throw discoveryError('CONFIG', 'Kafka IPv6 brokers must use [address]:port syntax.')
    portText = match[2]
  } else {
    const separator = value.lastIndexOf(':')
    if (separator <= 0 || value.indexOf(':') !== separator) {
      throw discoveryError('CONFIG', 'Kafka brokers must use host:port syntax.')
    }
    const host = value.slice(0, separator)
    portText = value.slice(separator + 1)
    if (!/^[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$/u.test(host)) {
      throw discoveryError('CONFIG', 'Kafka broker host syntax is invalid.')
    }
  }
  const port = Number(portText)
  if (!/^\d+$/u.test(portText) || !Number.isInteger(port) || port < 1 || port > 65_535) {
    throw discoveryError('CONFIG', 'Kafka broker port is invalid.')
  }
  return value
}

function kafkaConnection(environment) {
  const mechanism = optional(environment.POC_MCL_KAFKA_SASL_MECHANISM)?.toLowerCase()
  const username = optional(environment.POC_MCL_KAFKA_SASL_USERNAME)
  const password = optional(environment.POC_MCL_KAFKA_SASL_PASSWORD)
  if ([mechanism, username, password].some(Boolean) && ![mechanism, username, password].every(Boolean)) {
    throw discoveryError('CONFIG', 'Kafka SASL mechanism, username and password must be configured together.')
  }
  if (mechanism && !KAFKA_SASL_MECHANISMS.has(mechanism)) {
    throw discoveryError('CONFIG', 'Kafka SASL mechanism is not supported by the reviewed PREP contract.')
  }
  const sslText = optional(environment.POC_MCL_KAFKA_SSL)?.toLowerCase() || 'false'
  if (!['true', 'false'].includes(sslText)) {
    throw discoveryError('CONFIG', 'POC_MCL_KAFKA_SSL must be exactly true or false.')
  }
  const brokerText = required(environment.POC_MCL_KAFKA_BROKERS, 'POC_MCL_KAFKA_BROKERS')
  const brokers = brokerText.split(',').map((value) => value.trim())
  if (brokers.some((value) => !value)) throw discoveryError('CONFIG', 'Kafka broker inventory contains an empty endpoint.')
  return {
    brokers: brokers.map(brokerEndpoint),
    ssl: sslText === 'true',
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

function providerUrl(baseUrl, path, reason = 'REGISTRY_CONFIG') {
  try {
    const joined = joinProviderUrl(baseUrl, path)
    const parsed = new URL(joined)
    if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password) {
      throw new Error('invalid provider URL')
    }
    return parsed.toString()
  } catch (error) {
    throw discoveryError(reason, 'Provider URL configuration is invalid.', error)
  }
}

async function jsonRequest(providerTransport, url, headers = {}, {
  connectivity = 'REGISTRY_CONNECTIVITY',
  contract = 'REGISTRY_CONTRACT',
  label = 'Schema Registry',
} = {}) {
  let response
  try {
    response = await providerTransport.fetch(url, {
      headers,
      redirect: 'error',
      signal: AbortSignal.timeout(DISCOVERY_TIMEOUT_MS),
    })
  } catch (error) {
    if (isDiscoveryError(error)) throw error
    throw discoveryError(connectivity, `${label} discovery request failed.`, error)
  }
  if (!response.ok) return { ok: false, status: response.status }
  const body = await response.json().catch(() => null)
  if (body === null) throw discoveryError(contract, `${label} returned invalid JSON.`)
  return { ok: true, body }
}

async function registryCandidate(providerTransport, baseUrl, authorization, topic, kind) {
  const headers = authorization ? { Authorization: authorization } : {}
  const subjects = await jsonRequest(providerTransport, providerUrl(baseUrl, '/subjects'), headers)
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
    providerUrl(baseUrl, `/subjects/${encodeURIComponent(expected)}/versions/latest`),
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
    providerUrl(datahubUrl, '/schema-registry/api'),
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
  const result = await jsonRequest(providerTransport, providerUrl(url, '/config', 'CONFIG'), {
    Authorization: `Bearer ${token}`,
  }, {
    connectivity: 'PROVIDER_CONNECTIVITY', contract: 'PROVIDER_CONTRACT', label: 'DataHub provider version',
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
  createKafka = (options) => new Kafka(options),
  clock = () => new Date(),
} = {}) {
  let transport
  let ownsTransport = false
  let admin
  let connected = false
  let primaryError
  let cleanupError
  let discoveryResult
  try {
    let connection
    try {
      connection = kafkaConnection(environment)
    } catch (error) {
      if (isDiscoveryError(error)) throw error
      throw discoveryError('CONFIG', 'Kafka MCL discovery configuration is invalid.', error)
    }
    try {
      transport = providerTransport ?? createProviderTransport(environment)
      ownsTransport = !providerTransport
    } catch (error) {
      throw discoveryError('TRANSPORT_CONFIG', 'MCL provider transport configuration is invalid.', error)
    }
    let kafkaClient
    try {
      kafkaClient = kafka ?? createKafka({
        ...connection,
        clientId: environment.POC_MCL_KAFKA_CLIENT_ID?.trim() || 'datariver-prep39083-mcl-v1',
        connectionTimeout: KAFKA_CONNECTION_TIMEOUT_MS,
        requestTimeout: KAFKA_REQUEST_TIMEOUT_MS,
        retry: KAFKA_DISCOVERY_RETRY,
        logLevel: logLevel.NOTHING,
      })
    } catch (error) {
      throw discoveryError('KAFKA_CLIENT', 'Kafka client construction failed.', error)
    }
    try {
      admin = kafkaClient.admin()
    } catch (error) {
      throw discoveryError('KAFKA_ADMIN', 'Kafka admin construction failed.', error)
    }
    try {
      await admin.connect()
    } catch (error) {
      throw discoveryError('KAFKA_CONNECTIVITY', 'Kafka admin connection failed.', error)
    }
    connected = true
    let cluster
    try {
      cluster = await admin.describeCluster()
    } catch (error) {
      throw discoveryError('KAFKA_CLUSTER', 'Kafka cluster discovery failed.', error)
    }
    let topics
    try {
      topics = await admin.listTopics()
    } catch (error) {
      throw discoveryError('TOPIC_CONNECTIVITY', 'Kafka topic discovery failed.', error)
    }
    const providerVersion = await discoverProviderVersion(transport, environment)
    const clusterId = optional(cluster?.clusterId)
    if (!clusterId) throw discoveryError('KAFKA_CLUSTER_CONTRACT', 'Kafka cluster discovery returned no cluster identity.')
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
    discoveryResult = Object.freeze({
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
    primaryError = isDiscoveryError(error)
      ? error : discoveryError('UNEXPECTED', 'MCL discovery failed unexpectedly.', error)
  } finally {
    if (connected) {
      try {
        await admin.disconnect()
      } catch (error) {
        cleanupError = discoveryError('KAFKA_DISCONNECT', 'Kafka admin cleanup failed.', error)
      }
    }
    if (ownsTransport && transport) {
      try {
        await transport.close()
      } catch (error) {
        cleanupError ||= discoveryError('TRANSPORT_CLEANUP', 'MCL provider transport cleanup failed.', error)
      }
    }
  }
  if (primaryError) throw primaryError
  if (cleanupError) throw cleanupError
  return discoveryResult
}
