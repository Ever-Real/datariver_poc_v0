/* global process, Buffer, setTimeout, clearTimeout */
import KafkaJs from 'kafkajs'
import { SchemaRegistry } from '@kafkajs/confluent-schema-registry'
import SnappyCodec from 'kafkajs-snappy'

import { createPocStateStore } from './poc-state-store.mjs'

const { CompressionCodecs, CompressionTypes, Kafka, logLevel } = KafkaJs

// KafkaJS requires codecs supplied by consumers to be registered before the MCL client connects.
CompressionCodecs[CompressionTypes.Snappy] = SnappyCodec

const SUPPORTED_ASPECTS = new Set([
  'schemaMetadata',
  'editableSchemaMetadata',
  'datasetProperties',
  'globalTags',
  'glossaryTerms',
  'ownership',
])

const GENERIC_ASPECT_JSON_CONTENT_TYPE = 'application/json'

const STORAGE_CATEGORY_BY_ASPECT = {
  schemaMetadata: 'TECHNICAL_SCHEMA',
  editableSchemaMetadata: 'DOCUMENTATION',
  datasetProperties: 'DOCUMENTATION',
  globalTags: 'TAG',
  glossaryTerms: 'GLOSSARY_TERM',
  ownership: 'OWNERSHIP',
}

export function loadPocMclCaptureConfig(environment = process.env) {
  const saslMechanism = optionalString(environment.POC_MCL_KAFKA_SASL_MECHANISM)
  const saslUsername = optionalString(environment.POC_MCL_KAFKA_SASL_USERNAME)
  const saslPassword = optionalString(environment.POC_MCL_KAFKA_SASL_PASSWORD, false)
  const registryUsername = optionalString(environment.POC_MCL_SCHEMA_REGISTRY_USERNAME)
  const registryPassword = optionalString(environment.POC_MCL_SCHEMA_REGISTRY_PASSWORD, false)
  return validateCaptureConfig({
    brokers: requiredString(environment.POC_MCL_KAFKA_BROKERS, 'POC_MCL_KAFKA_BROKERS')
      .split(',').map((broker) => broker.trim()).filter(Boolean),
    clientId: requiredString(environment.POC_MCL_KAFKA_CLIENT_ID, 'POC_MCL_KAFKA_CLIENT_ID'),
    groupId: requiredString(environment.POC_MCL_KAFKA_GROUP_ID, 'POC_MCL_KAFKA_GROUP_ID'),
    topic: requiredString(environment.POC_MCL_KAFKA_TOPIC, 'POC_MCL_KAFKA_TOPIC'),
    sourceIdentityHash: requiredString(
      environment.POC_MCL_SOURCE_IDENTITY_HASH,
      'POC_MCL_SOURCE_IDENTITY_HASH',
    ),
    schemaContractHash: requiredString(
      environment.POC_MCL_SCHEMA_CONTRACT_HASH,
      'POC_MCL_SCHEMA_CONTRACT_HASH',
    ),
    providerName: requiredString(environment.POC_MCL_PROVIDER_NAME, 'POC_MCL_PROVIDER_NAME'),
    providerVersion: requiredString(environment.POC_MCL_PROVIDER_VERSION, 'POC_MCL_PROVIDER_VERSION'),
    kafkaSsl: parseBoolean(environment.POC_MCL_KAFKA_SSL, 'POC_MCL_KAFKA_SSL'),
    kafkaSasl: saslMechanism || saslUsername || saslPassword
      ? { mechanism: saslMechanism, username: saslUsername, password: saslPassword }
      : undefined,
    schemaRegistry: {
      host: requiredString(environment.POC_MCL_SCHEMA_REGISTRY_URL, 'POC_MCL_SCHEMA_REGISTRY_URL'),
      auth: registryUsername || registryPassword
        ? { username: registryUsername, password: registryPassword }
        : undefined,
    },
    maxMessages: parsePositiveInteger(environment.POC_MCL_MAX_MESSAGES, 10_000, 'POC_MCL_MAX_MESSAGES'),
    maxRecordBytes: parsePositiveInteger(
      environment.POC_MCL_MAX_RECORD_BYTES,
      1_048_576,
      'POC_MCL_MAX_RECORD_BYTES',
    ),
    timeoutMs: parsePositiveInteger(environment.POC_MCL_TIMEOUT_MS, 300_000, 'POC_MCL_TIMEOUT_MS'),
  })
}

export function createPocMclCapture({
  config,
  stateStore = createPocStateStore(),
  kafka,
  schemaRegistry,
  clock = () => new Date(),
} = {}) {
  const normalizedConfig = validateCaptureConfig(config ?? loadPocMclCaptureConfig())
  const kafkaClient = kafka ?? new Kafka({
    brokers: normalizedConfig.brokers,
    clientId: normalizedConfig.clientId,
    ssl: normalizedConfig.kafkaSsl,
    sasl: normalizedConfig.kafkaSasl,
    logLevel: logLevel.NOTHING,
  })
  const registry = schemaRegistry ?? new SchemaRegistry(normalizedConfig.schemaRegistry)
  return {
    run: () => runBoundedCapture({
      config: normalizedConfig,
      stateStore,
      kafka: kafkaClient,
      schemaRegistry: registry,
      clock,
    }),
  }
}

export async function decodeConfluentMcl(buffer, schemaRegistry, maxRecordBytes) {
  if (!Buffer.isBuffer(buffer) || buffer.length < 6 || buffer.length > maxRecordBytes) {
    throw new Error('The MCL record is absent or outside the configured byte bound.')
  }
  const decoded = await schemaRegistry.decode(buffer)
  if (!isRecordObject(decoded)) throw new Error('The decoded MCL record is not an object.')
  return decoded
}

export function normalizeMclRecord(record, {
  detectedAt,
  maxDocumentBytes = 16_384,
  maxItems = 1000,
} = {}) {
  if (!isRecordObject(record)) throw new Error('The decoded MCL record is invalid.')
  const aspectName = boundedString(record.aspectName, 'aspectName', 255)
  if (!SUPPORTED_ASPECTS.has(aspectName)) {
    return { aspectName, normalizedCategory: null, supported: false, events: [] }
  }
  const assetUrn = boundedString(record.entityUrn, 'entityUrn', 4096)
  const current = decodeAspectDocument(record.aspect, 'aspect', maxDocumentBytes)
  const previous = decodeAspectDocument(record.previousAspectValue, 'previousAspectValue', maxDocumentBytes)
  if (current === null && previous === null) {
    throw new Error('A supported MCL record has neither current nor previous aspect evidence.')
  }
  const evidence = {
    assetUrn,
    sourceAspect: aspectName,
    actorRef: optionalBoundedString(record.created?.actor, 'created.actor', 1000),
    sourceOccurredAt: normalizeOccurredAt(record.created?.time),
    detectedAt: explicitUtcTimestamp(detectedAt, 'detectedAt'),
    normalizedCategory: aspectName === 'schemaMetadata' ? 'SCHEMA_CHANGE' : 'METADATA_CHANGE',
    storageCategory: STORAGE_CATEGORY_BY_ASPECT[aspectName],
  }
  const events = aspectName === 'schemaMetadata'
    ? normalizeSchemaMetadata(current, previous, evidence, maxItems)
    : aspectName === 'editableSchemaMetadata'
      ? normalizeEditableSchemaMetadata(current, previous, evidence, maxItems)
      : aspectName === 'datasetProperties'
        ? normalizeDatasetProperties(current, previous, evidence, maxItems)
        : normalizeCollectionAspect(aspectName, current, previous, evidence, maxItems)
  if (events.length > maxItems) throw new Error('The supported MCL record exceeds the event fan-out bound.')
  return {
    aspectName,
    normalizedCategory: evidence.normalizedCategory,
    supported: true,
    events,
  }
}

async function runBoundedCapture({ config, stateStore, kafka, schemaRegistry, clock }) {
  if (typeof stateStore?.initializeChangeHistoryCaptureBoundaries !== 'function'
    || typeof stateStore?.appendChangeHistoryCapture !== 'function') {
    throw new Error('The durable POC change-history store is unavailable.')
  }
  const admin = kafka.admin()
  let consumer
  let adminConnected = false
  let consumerConnected = false
  try {
    await admin.connect()
    adminConnected = true
    const offsets = await admin.fetchTopicOffsets(config.topic)
    if (!Array.isArray(offsets) || offsets.length < 1) {
      throw new Error('The configured MCL topic has no readable partition inventory.')
    }
    const watermarks = offsets.map((offset) => {
      const partition = nonnegativeInteger(offset.partition, 'partition')
      const low = kafkaOffset(offset.low, 'low watermark')
      const high = kafkaOffset(offset.high, 'high watermark')
      if (high < low) throw new Error('The Kafka partition watermark range is invalid.')
      return { partition, low, high }
    }).sort((left, right) => left.partition - right.partition)
    if (new Set(watermarks.map(({ partition }) => partition)).size !== watermarks.length) {
      throw new Error('The configured MCL topic returned a duplicate partition inventory.')
    }
    const checkpoints = await stateStore.initializeChangeHistoryCaptureBoundaries({
      sourceIdentityHash: config.sourceIdentityHash,
      providerName: config.providerName,
      providerVersion: config.providerVersion,
      schemaContractHash: config.schemaContractHash,
      topicContract: config.topic,
      partitions: watermarks.map(({ partition, high }) => ({ partition, boundary: high })),
    })
    if (!Array.isArray(checkpoints) || checkpoints.length !== watermarks.length) {
      throw new Error('The durable MCL capture boundary inventory is invalid.')
    }
    const checkpointByPartition = new Map(checkpoints.map((checkpoint) => [
      nonnegativeInteger(checkpoint.partition, 'checkpoint partition'),
      kafkaOffset(checkpoint.nextOffset, 'durable checkpoint'),
    ]))
    if (checkpointByPartition.size !== watermarks.length) {
      throw new Error('The durable MCL capture boundary inventory is invalid.')
    }
    const targets = []
    let boundedMessageCount = 0
    for (const { partition, low, high } of watermarks) {
      const resume = checkpointByPartition.get(partition)
      if (resume === undefined) throw new Error('The durable MCL capture boundary inventory is invalid.')
      if (!Number.isSafeInteger(resume) || resume < low) {
        throw new Error('The durable checkpoint is behind Kafka retention; capture stopped with a history gap.')
      }
      if (resume > high) throw new Error('The durable checkpoint is ahead of the captured Kafka high watermark.')
      boundedMessageCount += high - resume
      if (boundedMessageCount > config.maxMessages) {
        throw new Error('The captured Kafka window exceeds the configured message bound.')
      }
      targets.push({ partition, low, high, next: resume, processed: 0, ledgerEvents: 0 })
    }
    const pending = new Map(targets.filter((target) => target.next < target.high)
      .map((target) => [target.partition, target]))
    if (pending.size === 0) return captureResult(config.topic, targets)

    consumer = kafka.consumer({
      groupId: config.groupId,
      allowAutoTopicCreation: false,
      maxBytesPerPartition: config.maxRecordBytes,
      maxBytes: Math.max(config.maxRecordBytes, config.maxRecordBytes * pending.size),
    })
    await consumer.connect()
    consumerConnected = true
    await consumer.subscribe({ topic: config.topic, fromBeginning: true })

    let resolveCompletion
    let rejectCompletion
    const completion = new Promise((resolve, reject) => {
      resolveCompletion = resolve
      rejectCompletion = reject
    })
    const timer = setTimeout(() => {
      rejectCompletion(new Error('The bounded MCL capture timed out before reaching its captured high watermark.'))
    }, config.timeoutMs)
    const removeGroupJoinListener = consumer.on(consumer.events.GROUP_JOIN, () => {
      for (const target of pending.values()) {
        consumer.seek({ topic: config.topic, partition: target.partition, offset: String(target.next) })
      }
    })
    try {
      await consumer.run({
        autoCommit: false,
        partitionsConsumedConcurrently: pending.size,
        eachMessage: async ({ partition, message }) => {
          const target = pending.get(partition)
          if (!target) return
          try {
            const offset = kafkaOffset(message.offset, 'message offset')
            if (offset < target.next || offset >= target.high) return
            if (offset !== target.next) throw new Error('The MCL partition has a non-contiguous offset gap.')
            const decoded = await decodeConfluentMcl(message.value, schemaRegistry, config.maxRecordBytes)
            const normalized = normalizeMclRecord(decoded, { detectedAt: clock().toISOString() })
            const capture = await stateStore.appendChangeHistoryCapture({
              sourceIdentityHash: config.sourceIdentityHash,
              providerName: config.providerName,
              providerVersion: config.providerVersion,
              schemaContractHash: config.schemaContractHash,
              topicContract: config.topic,
              partition,
              offset,
              events: normalized.events.map(toPersistenceEvent),
            })
            if (capture.nextOffset !== offset + 1) {
              throw new Error('The durable checkpoint did not advance to the expected offset.')
            }
            target.next = capture.nextOffset
            target.processed += 1
            target.ledgerEvents += capture.eventIdentities.length
            if (target.next === target.high) {
              pending.delete(partition)
              consumer.pause([{ topic: config.topic, partitions: [partition] }])
              if (pending.size === 0) resolveCompletion()
            }
          } catch (error) {
            rejectCompletion(error)
            throw error
          }
        },
      })
      await completion
    } finally {
      removeGroupJoinListener()
      clearTimeout(timer)
      await consumer.stop()
    }
    return captureResult(config.topic, targets)
  } finally {
    if (consumerConnected) await consumer.disconnect()
    if (adminConnected) await admin.disconnect()
  }
}

function captureResult(topic, targets) {
  return {
    topic,
    bounded: true,
    partitions: targets.map(({ partition, low, high, next, processed, ledgerEvents }) => ({
      partition,
      lowWatermark: low,
      capturedHighWatermark: high,
      nextOffset: next,
      processedRecords: processed,
      ledgerEvents,
    })),
  }
}

function toPersistenceEvent(event) {
  const persistenceEvent = { ...event, category: event.storageCategory }
  delete persistenceEvent.normalizedCategory
  delete persistenceEvent.storageCategory
  return persistenceEvent
}

function normalizeSchemaMetadata(current, previous, evidence, maximum) {
  const currentFields = schemaFieldMap(current, maximum)
  const previousFields = schemaFieldMap(previous, maximum)
  if (currentFields.size || previousFields.size) return diffMaps(currentFields, previousFields, evidence)
  return singletonDiff('schema', schemaSummary(current), schemaSummary(previous), evidence)
}

function normalizeEditableSchemaMetadata(current, previous, evidence, maximum) {
  const currentFields = editableSchemaFieldMap(current, maximum)
  const previousFields = editableSchemaFieldMap(previous, maximum)
  if (currentFields.size || previousFields.size) return diffMaps(currentFields, previousFields, evidence)
  return singletonDiff(
    'editable-schema',
    current === null ? null : { description: optionalDocumentString(current.description, 'description', 4096) },
    previous === null ? null : { description: optionalDocumentString(previous.description, 'description', 4096) },
    evidence,
  )
}

function normalizeDatasetProperties(current, previous, evidence, maximum) {
  const snapshot = (document) => document === null ? null : {
    description: optionalDocumentString(document.description, 'description', 4096),
    custom_properties: normalizedStringMap(document.customProperties, maximum),
  }
  return singletonDiff('dataset-properties', snapshot(current), snapshot(previous), evidence)
}

function normalizeCollectionAspect(aspectName, current, previous, evidence, maximum) {
  const currentItems = collectionMap(aspectName, current, maximum)
  const previousItems = collectionMap(aspectName, previous, maximum)
  const events = []
  for (const key of [...new Set([...currentItems.keys(), ...previousItems.keys()])].sort()) {
    const beforeData = previousItems.get(key) ?? null
    const afterData = currentItems.get(key) ?? null
    if (stableJson(beforeData) === stableJson(afterData)) continue
    events.push(semanticEvent(`item:${key}`, beforeData, afterData, evidence, afterData ? 'ADD' : 'REMOVE'))
  }
  return events
}

function schemaFieldMap(document, maximum) {
  if (document === null) return new Map()
  const fields = boundedArray(document.fields, 'schemaMetadata.fields', maximum)
  const result = new Map()
  for (const field of fields) {
    if (!isPlainObject(field)) throw new Error('A schemaMetadata field is invalid.')
    const path = boundedString(field.fieldPath, 'schemaMetadata.fieldPath', 900)
    if (result.has(path)) throw new Error('A schemaMetadata field path is duplicated.')
    result.set(path, {
      field_path: path,
      native_data_type: optionalDocumentString(field.nativeDataType, 'nativeDataType', 500),
      description: optionalDocumentString(field.description, 'description', 4096),
      nullable: typeof field.nullable === 'boolean' ? field.nullable : null,
    })
  }
  return result
}

function editableSchemaFieldMap(document, maximum) {
  if (document === null) return new Map()
  const fields = boundedArray(document.editableSchemaFieldInfo, 'editableSchemaFieldInfo', maximum)
  const result = new Map()
  for (const field of fields) {
    if (!isPlainObject(field)) throw new Error('An editable schema field is invalid.')
    const path = boundedString(field.fieldPath, 'editableSchemaFieldInfo.fieldPath', 900)
    if (result.has(path)) throw new Error('An editable schema field path is duplicated.')
    result.set(path, {
      field_path: path,
      description: optionalDocumentString(field.description, 'description', 4096),
    })
  }
  return result
}

function schemaSummary(document) {
  if (document === null) return null
  return {
    schema_name: optionalDocumentString(document.schemaName, 'schemaName', 1000),
    platform: optionalDocumentString(document.platform, 'platform', 1000),
    version: Number.isSafeInteger(document.version) ? document.version : null,
  }
}

function collectionMap(aspectName, document, maximum) {
  if (document === null) return new Map()
  const collectionName = aspectName === 'globalTags' ? 'tags'
    : aspectName === 'glossaryTerms' ? 'terms' : 'owners'
  const items = boundedArray(document[collectionName], `${aspectName}.${collectionName}`, maximum)
  const result = new Map()
  for (const item of items) {
    if (!isPlainObject(item)) throw new Error(`An ${aspectName} item is invalid.`)
    const normalized = aspectName === 'globalTags'
      ? { tag_urn: boundedString(item.tag, 'globalTags.tag', 1000) }
      : aspectName === 'glossaryTerms'
        ? { term_urn: boundedString(item.urn, 'glossaryTerms.urn', 1000) }
        : {
            owner_urn: boundedString(item.owner, 'ownership.owner', 1000),
            ownership_type: boundedString(item.type, 'ownership.type', 500),
          }
    const key = stableJson(normalized)
    if (result.has(key)) throw new Error(`An ${aspectName} item is duplicated.`)
    result.set(key, normalized)
  }
  return result
}

function diffMaps(current, previous, evidence) {
  const events = []
  for (const key of [...new Set([...current.keys(), ...previous.keys()])].sort()) {
    const beforeData = previous.get(key) ?? null
    const afterData = current.get(key) ?? null
    if (stableJson(beforeData) === stableJson(afterData)) continue
    events.push(semanticEvent(`field:${key}`, beforeData, afterData, evidence))
  }
  return events
}

function singletonDiff(key, current, previous, evidence) {
  if (stableJson(current) === stableJson(previous)) return []
  return [semanticEvent(key, previous, current, evidence)]
}

function semanticEvent(entityKey, beforeData, afterData, evidence, forcedOperation) {
  const operation = forcedOperation ?? (beforeData === null ? 'CREATE' : afterData === null ? 'DELETE' : 'UPDATE')
  return {
    assetUrn: evidence.assetUrn,
    entityKey,
    normalizedCategory: evidence.normalizedCategory,
    storageCategory: evidence.storageCategory,
    sourceAspect: evidence.sourceAspect,
    operation,
    beforeData,
    afterData,
    actorRef: evidence.actorRef,
    sourceOccurredAt: evidence.sourceOccurredAt,
    detectedAt: evidence.detectedAt,
  }
}

function decodeAspectDocument(container, field, maximumBytes) {
  if (container == null) return null
  if (!isRecordObject(container)
    || !Object.hasOwn(container, 'value')
    || container.contentType !== GENERIC_ASPECT_JSON_CONTENT_TYPE) {
    throw new Error(`${field} does not use the supported GenericAspect JSON content type.`)
  }
  let value = container.value
  if (Buffer.isBuffer(value) || value instanceof Uint8Array) {
    const bytes = Buffer.from(value)
    if (bytes.length < 2 || bytes.length > maximumBytes) throw new Error(`${field} is outside the byte bound.`)
    value = bytes.toString('utf8')
  }
  if (typeof value === 'string') {
    if (Buffer.byteLength(value, 'utf8') > maximumBytes) throw new Error(`${field} is outside the byte bound.`)
    try {
      value = JSON.parse(value)
    } catch {
      throw new Error(`${field} is not valid bounded JSON.`)
    }
  }
  if (!isPlainObject(value)) throw new Error(`${field} is not a decoded aspect object.`)
  if (Buffer.byteLength(stableJson(value), 'utf8') > maximumBytes) {
    throw new Error(`${field} is outside the byte bound.`)
  }
  return value
}

function validateCaptureConfig(config) {
  if (!isPlainObject(config)) throw new Error('The MCL capture configuration is invalid.')
  if (!Array.isArray(config.brokers) || config.brokers.length < 1 || config.brokers.length > 20) {
    throw new Error('The MCL Kafka broker list is invalid.')
  }
  const kafkaSasl = config.kafkaSasl === undefined ? undefined : {
    mechanism: ['plain', 'scram-sha-256', 'scram-sha-512'].includes(config.kafkaSasl?.mechanism)
      ? config.kafkaSasl.mechanism
      : (() => { throw new Error('The MCL Kafka SASL mechanism is invalid.') })(),
    username: boundedString(config.kafkaSasl.username, 'kafkaSasl.username', 1000),
    password: boundedSecret(config.kafkaSasl.password, 'kafkaSasl.password'),
  }
  if (!isPlainObject(config.schemaRegistry)) throw new Error('The Schema Registry configuration is invalid.')
  const registryAuth = config.schemaRegistry.auth === undefined ? undefined : {
    username: boundedString(config.schemaRegistry.auth?.username, 'schemaRegistry.auth.username', 1000),
    password: boundedSecret(config.schemaRegistry.auth?.password, 'schemaRegistry.auth.password'),
  }
  return {
    brokers: config.brokers.map((broker) => boundedString(broker, 'broker', 1000)),
    clientId: boundedString(config.clientId, 'clientId', 255),
    groupId: boundedString(config.groupId, 'groupId', 255),
    topic: boundedString(config.topic, 'topic', 255),
    sourceIdentityHash: sha256String(config.sourceIdentityHash, 'sourceIdentityHash'),
    schemaContractHash: sha256String(config.schemaContractHash, 'schemaContractHash'),
    providerName: boundedString(config.providerName, 'providerName', 100),
    providerVersion: boundedString(config.providerVersion, 'providerVersion', 100),
    kafkaSsl: typeof config.kafkaSsl === 'boolean'
      ? config.kafkaSsl
      : (() => { throw new Error('kafkaSsl must be a boolean.') })(),
    kafkaSasl,
    schemaRegistry: {
      host: boundedString(config.schemaRegistry.host, 'schemaRegistry.host', 2000),
      auth: registryAuth,
    },
    maxMessages: positiveInteger(config.maxMessages, 'maxMessages'),
    maxRecordBytes: positiveInteger(config.maxRecordBytes, 'maxRecordBytes'),
    timeoutMs: positiveInteger(config.timeoutMs, 'timeoutMs'),
  }
}

function normalizedStringMap(value, maximum) {
  if (value == null) return {}
  if (!isPlainObject(value) || Object.keys(value).length > maximum) {
    throw new Error('datasetProperties.customProperties is outside its item bound.')
  }
  return Object.fromEntries(Object.keys(value).sort().map((key) => [
    boundedString(key, 'customProperties key', 500),
    boundedString(value[key], 'customProperties value', 4096, false),
  ]))
}

function boundedArray(value, field, maximum) {
  if (value == null) return []
  if (!Array.isArray(value) || value.length > maximum) throw new Error(`${field} is outside its item bound.`)
  return value
}

function normalizeOccurredAt(value) {
  if (value == null) return null
  if (typeof value === 'number' && Number.isSafeInteger(value) && value >= 0) return new Date(value).toISOString()
  if (typeof value === 'string' && /^\d+$/.test(value)) {
    const milliseconds = Number(value)
    if (Number.isSafeInteger(milliseconds)) return new Date(milliseconds).toISOString()
  }
  return explicitUtcTimestamp(value, 'created.time')
}

function explicitUtcTimestamp(value, field) {
  if (typeof value !== 'string' || !value.endsWith('Z')) throw new Error(`${field} is not an explicit UTC timestamp.`)
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) throw new Error(`${field} is not a valid UTC timestamp.`)
  return parsed.toISOString()
}

function kafkaOffset(value, field) {
  const parsed = typeof value === 'number' ? value : Number(value)
  return nonnegativeInteger(parsed, field)
}

function stableJson(value) {
  if (value === undefined) return 'null'
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`
  if (isPlainObject(value)) {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(',')}}`
  }
  return JSON.stringify(value)
}

function isPlainObject(value) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false
  const prototype = Object.getPrototypeOf(value)
  return prototype === Object.prototype || prototype === null
}

function isRecordObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    && !Buffer.isBuffer(value) && !(value instanceof Uint8Array)
}

function boundedString(value, field, maximum, trimmed = true) {
  if (typeof value !== 'string' || value.length < 1 || value.length > maximum
    || (trimmed && value.trim() !== value)) throw new Error(`${field} is outside its string bound.`)
  return value
}

function optionalBoundedString(value, field, maximum) {
  return value == null ? null : boundedString(value, field, maximum)
}

function optionalDocumentString(value, field, maximum) {
  return value == null ? null : boundedString(value, field, maximum, false)
}

function boundedSecret(value, field) {
  if (typeof value !== 'string' || value.length < 1 || value.length > 8192) {
    throw new Error(`${field} is absent or outside its secret bound.`)
  }
  return value
}

function sha256String(value, field) {
  if (typeof value !== 'string' || !/^[0-9a-f]{64}$/.test(value)) {
    throw new Error(`${field} is not a lowercase SHA-256 value.`)
  }
  return value
}

function nonnegativeInteger(value, field) {
  if (!Number.isSafeInteger(value) || value < 0) throw new Error(`${field} is not a non-negative integer.`)
  return value
}

function positiveInteger(value, field) {
  if (!Number.isSafeInteger(value) || value < 1) throw new Error(`${field} is not a positive integer.`)
  return value
}

function requiredString(value, field) {
  if (typeof value !== 'string' || !value.trim()) throw new Error(`${field} is required.`)
  return value.trim()
}

function optionalString(value, trimmed = true) {
  if (typeof value !== 'string' || !value) return undefined
  return trimmed ? value.trim() || undefined : value
}

function parseBoolean(value, field) {
  if (value === undefined || value === '') return false
  if (value === 'true') return true
  if (value === 'false') return false
  throw new Error(`${field} must be true or false.`)
}

function parsePositiveInteger(value, fallback, field) {
  if (value === undefined || value === '') return fallback
  const parsed = Number(value)
  if (!Number.isSafeInteger(parsed) || parsed < 1) throw new Error(`${field} must be a positive integer.`)
  return parsed
}
