/* global process, Buffer, setTimeout, clearTimeout */
import KafkaJs from 'kafkajs'
import { SchemaRegistry } from '@kafkajs/confluent-schema-registry'
import SnappyCodec from 'kafkajs-snappy'
import { createHash } from 'node:crypto'

import {
  mclCaptureFailure,
  mclRecordNormalizationFailure,
  mclRecordNormalizationLocus,
  sanitizeMclRecordShape,
} from './poc-mcl-runtime-failure.mjs'
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
  'domains',
  'ownership',
  'status',
])

const GENERIC_ASPECT_JSON_CONTENT_TYPE = 'application/json'
const DEFAULT_MAX_DOCUMENT_BYTES = 1_048_576
const LOGICAL_TYPE_BY_DATAHUB_DISCRIMINATOR = Object.freeze({
  'com.linkedin.schema.BooleanType': 'BooleanType',
  'com.linkedin.schema.FixedType': 'FixedType',
  'com.linkedin.schema.StringType': 'StringType',
  'com.linkedin.schema.BytesType': 'BytesType',
  'com.linkedin.schema.NumberType': 'NumberType',
  'com.linkedin.schema.DateType': 'DateType',
  'com.linkedin.schema.TimeType': 'TimeType',
  'com.linkedin.schema.EnumType': 'EnumType',
  'com.linkedin.schema.NullType': 'NullType',
  'com.linkedin.schema.MapType': 'MapType',
  'com.linkedin.schema.ArrayType': 'ArrayType',
  'com.linkedin.schema.UnionType': 'UnionType',
  'com.linkedin.schema.RecordType': 'RecordType',
})

const STORAGE_CATEGORY_BY_ASPECT = {
  schemaMetadata: 'TECHNICAL_SCHEMA',
  editableSchemaMetadata: 'DOCUMENTATION',
  datasetProperties: 'DOCUMENTATION',
  globalTags: 'TAG',
  glossaryTerms: 'GLOSSARY_TERM',
  domains: 'DOMAIN',
  ownership: 'OWNERSHIP',
  status: 'LIFECYCLE',
}
async function captureStage(task, stage, detailCode) {
  try {
    return await task()
  } catch (error) {
    throw mclCaptureFailure(error, { stage, detailCode })
  }
}

function normalizationStep(task, locus) {
  try {
    return task()
  } catch (error) {
    throw mclRecordNormalizationFailure(error, locus)
  }
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
  const registryOptions = normalizedConfig.schemaRegistry.bearerToken
    ? {
        ...normalizedConfig.schemaRegistry,
        middlewares: [() => ({
          request(request) {
            return request.enhance({ headers: { Authorization: `Bearer ${normalizedConfig.schemaRegistry.bearerToken}` } })
          },
        })],
      }
    : normalizedConfig.schemaRegistry
  delete registryOptions.bearerToken
  const registry = schemaRegistry ?? new SchemaRegistry(registryOptions)
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

export function profileMclRecordShape(record, {
  partition,
  offset,
  rejectionLocus,
  maxDocumentBytes = DEFAULT_MAX_DOCUMENT_BYTES,
} = {}) {
  const currentShape = profileAspectDocument(record?.aspect, maxDocumentBytes)
  const previousShape = profileAspectDocument(record?.previousAspectValue, maxDocumentBytes)
  const profile = {
    contract: 'DATARIVER_MCL_REJECTED_RECORD_SHAPE_V1',
    partition,
    offset,
    entity_type: boundedShapeIdentifier(record?.entityType),
    aspect_name: boundedShapeIdentifier(record?.aspectName),
    change_type: boundedShapeChangeType(record?.changeType),
    aspect_present: record?.aspect != null,
    previous_aspect_value_present: record?.previousAspectValue != null,
    aspect_content_type: currentShape.contentType,
    previous_aspect_content_type: previousShape.contentType,
    created_type: shapeType(record?.created),
    created_time_type: shapeType(record?.created?.time),
    created_time_representation: createdTimeRepresentation(record?.created?.time),
    created_actor_type: shapeType(record?.created?.actor),
    current_aspect_decoded_object: currentShape.decodedObject,
    previous_aspect_decoded_object: previousShape.decodedObject,
    current_collection_item_count: profileCollectionItemCount(record?.aspectName, currentShape.document),
    previous_collection_item_count: profileCollectionItemCount(record?.aspectName, previousShape.document),
    rejection_locus: rejectionLocus,
  }
  return sanitizeMclRecordShape(profile)
}

export function normalizeMclRecord(record, {
  detectedAt,
  maxDocumentBytes = DEFAULT_MAX_DOCUMENT_BYTES,
  maxItems = 1000,
} = {}) {
  if (!isRecordObject(record)) {
    throw mclRecordNormalizationFailure(
      new Error('The decoded MCL record is invalid.'),
      'OTHER_NORMALIZATION_CONTRACT_INVALID',
    )
  }
  const aspectName = typeof record.aspectName === 'string' ? record.aspectName : undefined
  const assetUrn = normalizationStep(
    () => boundedString(record.entityUrn, 'entityUrn', 4096),
    'ENTITY_URN_INVALID',
  )
  if (record.aspectName != null && typeof record.aspectName !== 'string') {
    throw mclRecordNormalizationFailure(
      new Error('aspectName is outside its string bound.'),
      'ASPECT_NAME_INVALID',
    )
  }
  if (aspectName === undefined || aspectName === '') {
    return normalizeEntityLifecycle(record, assetUrn, detectedAt)
  }
  if (aspectName.trim() !== aspectName || aspectName.length > 255) {
    throw mclRecordNormalizationFailure(
      new Error('aspectName is outside its string bound.'),
      'ASPECT_NAME_INVALID',
    )
  }
  if (!SUPPORTED_ASPECTS.has(aspectName)) {
    return { aspectName, normalizedCategory: null, supported: false, events: [] }
  }
  const current = decodeAspectDocument(record.aspect, 'aspect', maxDocumentBytes)
  const previous = decodeAspectDocument(record.previousAspectValue, 'previousAspectValue', maxDocumentBytes)
  if (current === null && previous === null) {
    throw mclRecordNormalizationFailure(
      new Error('A supported MCL record has neither current nor previous aspect evidence.'),
      'CURRENT_PREVIOUS_EVIDENCE_MISSING',
    )
  }
  const evidence = {
    assetUrn,
    sourceAspect: aspectName,
    actorRef: normalizationStep(
      () => optionalBoundedString(record.created?.actor, 'created.actor', 1000),
      'CREATED_ACTOR_INVALID',
    ),
    sourceOccurredAt: normalizationStep(
      () => normalizeOccurredAt(record.created?.time),
      'CREATED_TIME_INVALID',
    ),
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
        : aspectName === 'status'
          ? normalizeStatus(current, previous, evidence)
          : normalizeCollectionAspect(aspectName, current, previous, evidence, maxItems)
  if (events.length > maxItems) {
    throw mclRecordNormalizationFailure(
      new Error('The supported MCL record exceeds the event fan-out bound.'),
      'EVENT_FANOUT_LIMIT_EXCEEDED',
    )
  }
  return {
    aspectName,
    normalizedCategory: evidence.normalizedCategory,
    supported: true,
    events,
  }
}

function normalizeEntityLifecycle(record, assetUrn, detectedAt) {
  return normalizationStep(() => {
    const entityType = boundedString(record.entityType, 'entityType', 255)
    const changeType = boundedString(record.changeType, 'changeType', 255)
    if (entityType !== 'dataset') {
      throw new Error('Only exact DataHub dataset entity lifecycle records are supported.')
    }
    const operation = changeType === 'CREATE' || changeType === 'CREATE_ENTITY'
      ? 'CREATE'
      : changeType === 'DELETE' ? 'DELETE' : undefined
    if (changeType !== 'CREATE' && changeType !== 'CREATE_ENTITY' && changeType !== 'DELETE' && changeType !== 'UPSERT') {
      throw new Error('The DataHub entity lifecycle changeType is unsupported.')
    }
    if (!operation) return { aspectName: null, normalizedCategory: 'METADATA_CHANGE', supported: true, events: [] }
    const evidence = {
      assetUrn,
      sourceAspect: 'entity',
      actorRef: normalizationStep(
        () => optionalBoundedString(record.created?.actor, 'created.actor', 1000),
        'CREATED_ACTOR_INVALID',
      ),
      sourceOccurredAt: normalizationStep(
        () => normalizeOccurredAt(record.created?.time),
        'CREATED_TIME_INVALID',
      ),
      detectedAt: explicitUtcTimestamp(detectedAt, 'detectedAt'),
      normalizedCategory: 'METADATA_CHANGE',
      storageCategory: 'LIFECYCLE',
    }
    return {
      aspectName: null,
      normalizedCategory: evidence.normalizedCategory,
      supported: true,
      events: [semanticEvent(
        'asset:lifecycle:entity',
        operation === 'DELETE' ? { entity_type: entityType } : null,
        operation === 'CREATE' ? { entity_type: entityType } : null,
        evidence,
        operation,
      )],
    }
  }, 'ENTITY_LIFECYCLE_CONTRACT_INVALID')
}

async function runBoundedCapture({ config, stateStore, kafka, schemaRegistry, clock }) {
  if (typeof stateStore?.initializeChangeHistoryCaptureBoundaries !== 'function'
    || typeof stateStore?.recordChangeHistoryRetentionGapAndAdvanceBoundary !== 'function'
    || typeof stateStore?.appendChangeHistoryCapture !== 'function') {
    throw mclCaptureFailure(undefined, {
      stage: 'CAPTURE_INITIALIZATION', detailCode: 'DURABLE_STORE_UNAVAILABLE',
    })
  }
  let admin
  try {
    admin = kafka.admin()
  } catch (error) {
    throw mclCaptureFailure(error, {
      stage: 'KAFKA_ADMIN_CONSTRUCTION', detailCode: 'ADMIN_CONSTRUCTION_REJECTED',
    })
  }
  let consumer
  let adminConnected = false
  let consumerConnected = false
  let primaryError
  let cleanupFailure
  let result
  const executeCapture = async () => {
    await captureStage(
      () => admin.connect(),
      'KAFKA_ADMIN_CONNECT',
      'ADMIN_CONNECT_REJECTED',
    )
    adminConnected = true
    const offsets = await captureStage(
      () => admin.fetchTopicOffsets(config.topic),
      'KAFKA_WATERMARK_READ',
      'TOPIC_OFFSETS_REJECTED',
    )
    if (!Array.isArray(offsets) || offsets.length < 1) {
      throw mclCaptureFailure(undefined, {
        stage: 'KAFKA_WATERMARK_VALIDATION', detailCode: 'PARTITION_INVENTORY_EMPTY',
      })
    }
    let watermarks
    try {
      watermarks = offsets.map((offset) => {
        const partition = nonnegativeInteger(offset.partition, 'partition')
        const low = kafkaOffset(offset.low, 'low watermark')
        const high = kafkaOffset(offset.high, 'high watermark')
        if (high < low) throw new Error('The Kafka partition watermark range is invalid.')
        return { partition, low, high }
      }).sort((left, right) => left.partition - right.partition)
    } catch (error) {
      throw mclCaptureFailure(error, {
        stage: 'KAFKA_WATERMARK_VALIDATION', detailCode: 'PARTITION_WATERMARK_INVALID',
      })
    }
    if (new Set(watermarks.map(({ partition }) => partition)).size !== watermarks.length) {
      throw mclCaptureFailure(undefined, {
        stage: 'KAFKA_WATERMARK_VALIDATION', detailCode: 'PARTITION_INVENTORY_DUPLICATE',
      })
    }
    const checkpoints = await captureStage(
      () => stateStore.initializeChangeHistoryCaptureBoundaries({
        sourceIdentityHash: config.sourceIdentityHash,
        providerName: config.providerName,
        providerVersion: config.providerVersion,
        schemaContractHash: config.schemaContractHash,
        topicContract: config.topic,
        // A new source begins at Kafka's earliest retained offset. Existing
        // checkpoints are immutable here and are never reset by rediscovery.
        partitions: watermarks.map(({ partition, low }) => ({ partition, boundary: low })),
      }),
      'CAPTURE_BOUNDARY_PERSISTENCE',
      'BOUNDARY_WRITE_REJECTED',
    )
    if (!Array.isArray(checkpoints) || checkpoints.length !== watermarks.length) {
      throw mclCaptureFailure(undefined, {
        stage: 'CAPTURE_BOUNDARY_VALIDATION', detailCode: 'BOUNDARY_INVENTORY_INVALID',
      })
    }
    let checkpointByPartition
    try {
      checkpointByPartition = new Map(checkpoints.map((checkpoint) => {
        const partition = nonnegativeInteger(checkpoint.partition, 'checkpoint partition')
        const nextOffset = kafkaOffset(checkpoint.nextOffset, 'durable checkpoint')
        const gapReceiptCount = checkpoint.gapReceiptCount === undefined
          ? 0 : nonnegativeInteger(checkpoint.gapReceiptCount, 'gap receipt count')
        const currentSegmentStart = checkpoint.currentSegmentStart === undefined
          ? null : kafkaOffset(checkpoint.currentSegmentStart, 'current segment start')
        return [partition, { nextOffset, gapReceiptCount, currentSegmentStart }]
      }))
    } catch (error) {
      throw mclCaptureFailure(error, {
        stage: 'CAPTURE_BOUNDARY_VALIDATION', detailCode: 'BOUNDARY_VALUE_INVALID',
      })
    }
    if (checkpointByPartition.size !== watermarks.length) {
      throw mclCaptureFailure(undefined, {
        stage: 'CAPTURE_BOUNDARY_VALIDATION', detailCode: 'BOUNDARY_PARTITION_DUPLICATE',
      })
    }
    const targets = []
    let remainingBudget = config.maxMessages
    for (const { partition, low, high } of watermarks) {
      const checkpoint = checkpointByPartition.get(partition)
      if (checkpoint === undefined) {
        throw mclCaptureFailure(undefined, {
          stage: 'CAPTURE_BOUNDARY_VALIDATION', detailCode: 'BOUNDARY_PARTITION_MISSING',
        })
      }
      let resume = checkpoint.nextOffset
      let gapReceiptCount = checkpoint.gapReceiptCount
      let currentSegmentStart = checkpoint.currentSegmentStart
      if (resume < low) {
        const gap = await captureStage(
          () => stateStore.recordChangeHistoryRetentionGapAndAdvanceBoundary({
            sourceIdentityHash: config.sourceIdentityHash,
            topicContract: config.topic,
            partition,
            previousNextOffset: resume,
            lowWatermark: low,
            highWatermark: high,
            observedAt: clock().toISOString(),
          }),
          'RETENTION_GAP_PERSISTENCE',
          'GAP_RECEIPT_OR_BOUNDARY_WRITE_REJECTED',
        )
        if (gap?.reason !== 'RETENTION_EXPIRED'
          || gap?.newSegmentStart !== low
          || gap?.lowWatermark !== low) {
          throw mclCaptureFailure(undefined, {
            stage: 'RETENTION_GAP_VALIDATION', detailCode: 'GAP_RECEIPT_INVALID',
          })
        }
        resume = low
        gapReceiptCount += gap.replayed ? 0 : 1
        currentSegmentStart = low
      }
      if (resume > high) {
        throw mclCaptureFailure(undefined, {
          stage: 'CHECKPOINT_VALIDATION', detailCode: 'CHECKPOINT_AHEAD_OF_HIGH_WATERMARK',
        })
      }
      const targetHigh = Math.min(high, resume + remainingBudget)
      remainingBudget -= targetHigh - resume
      targets.push({
        partition, low, high: targetHigh, sourceHigh: high, next: resume,
        processed: 0, ledgerEvents: 0, gapReceiptCount, currentSegmentStart,
      })
    }
    const pending = new Map(targets.filter((target) => target.next < target.high)
      .map((target) => [target.partition, target]))
    if (pending.size === 0) return captureResult(config, targets)

    try {
      consumer = kafka.consumer({
        groupId: config.groupId,
        allowAutoTopicCreation: false,
        maxBytesPerPartition: config.maxRecordBytes,
        maxBytes: Math.max(config.maxRecordBytes, config.maxRecordBytes * pending.size),
      })
    } catch (error) {
      throw mclCaptureFailure(error, {
        stage: 'KAFKA_CONSUMER_CONSTRUCTION', detailCode: 'CONSUMER_CONSTRUCTION_REJECTED',
      })
    }
    await captureStage(
      () => consumer.connect(),
      'KAFKA_CONSUMER_CONNECT',
      'CONSUMER_CONNECT_REJECTED',
    )
    consumerConnected = true
    await captureStage(
      () => consumer.subscribe({ topic: config.topic, fromBeginning: true }),
      'KAFKA_CONSUMER_SUBSCRIBE',
      'CONSUMER_SUBSCRIBE_REJECTED',
    )

    let resolveCompletion
    let rejectCompletion
    const completion = new Promise((resolve, reject) => {
      resolveCompletion = resolve
      rejectCompletion = reject
    })
    const timer = setTimeout(() => {
      rejectCompletion(mclCaptureFailure(undefined, {
        stage: 'CAPTURE_WAIT', detailCode: 'CAPTURE_HIGH_WATERMARK_TIMEOUT',
      }))
    }, config.timeoutMs)
    let removeGroupJoinListener
    try {
      removeGroupJoinListener = consumer.on(consumer.events.GROUP_JOIN, () => {
        try {
          for (const target of pending.values()) {
            consumer.seek({ topic: config.topic, partition: target.partition, offset: String(target.next) })
          }
        } catch (error) {
          rejectCompletion(mclCaptureFailure(error, {
            stage: 'KAFKA_CONSUMER_SEEK', detailCode: 'CONSUMER_SEEK_REJECTED',
          }))
        }
      })
    } catch (error) {
      clearTimeout(timer)
      throw mclCaptureFailure(error, {
        stage: 'KAFKA_CONSUMER_GROUP_LISTENER', detailCode: 'GROUP_LISTENER_REJECTED',
      })
    }
    let innerCleanupFailure
    try {
      await captureStage(
        () => consumer.run({
          autoCommit: false,
          partitionsConsumedConcurrently: pending.size,
          eachMessage: async ({ partition, message }) => {
            const target = pending.get(partition)
            if (!target) return
            try {
              let offset
              try {
                offset = kafkaOffset(message.offset, 'message offset')
                if (offset !== target.next && offset >= target.next && offset < target.high) {
                  throw new Error('The MCL partition has a non-contiguous offset gap.')
                }
              } catch (error) {
                throw mclCaptureFailure(error, {
                  stage: 'MESSAGE_OFFSET_VALIDATION', detailCode: 'MESSAGE_OFFSET_INVALID',
                })
              }
              if (offset < target.next || offset >= target.high) return
              const decoded = await captureStage(
                () => decodeConfluentMcl(message.value, schemaRegistry, config.maxRecordBytes),
                'SCHEMA_DECODE',
                'MCL_RECORD_DECODE_REJECTED',
              )
              let normalized
              try {
                normalized = normalizeMclRecord(decoded, {
                  detectedAt: clock().toISOString(),
                  maxDocumentBytes: config.maxRecordBytes,
                })
              } catch (error) {
                const rejectionLocus = mclRecordNormalizationLocus(error)
                throw mclCaptureFailure(error, {
                  stage: 'RECORD_NORMALIZATION',
                  detailCode: rejectionLocus,
                  recordShape: profileMclRecordShape(decoded, {
                    partition,
                    offset,
                    rejectionLocus,
                    maxDocumentBytes: config.maxRecordBytes,
                  }),
                })
              }
              const capture = await captureStage(
                () => stateStore.appendChangeHistoryCapture({
                  sourceIdentityHash: config.sourceIdentityHash,
                  providerName: config.providerName,
                  providerVersion: config.providerVersion,
                  schemaContractHash: config.schemaContractHash,
                  topicContract: config.topic,
                  partition,
                  offset,
                  events: normalized.events.map(toPersistenceEvent),
                }),
                'DURABLE_APPEND',
                'LEDGER_WRITE_REJECTED',
              )
              if (capture.nextOffset !== offset + 1 || !Array.isArray(capture.eventIdentities)) {
                throw mclCaptureFailure(undefined, {
                  stage: 'CHECKPOINT_VALIDATION', detailCode: 'CHECKPOINT_ADVANCE_INVALID',
                })
              }
              target.next = capture.nextOffset
              target.processed += 1
              target.ledgerEvents += capture.eventIdentities.length
              if (target.next === target.high) {
                pending.delete(partition)
                try {
                  consumer.pause([{ topic: config.topic, partitions: [partition] }])
                } catch (error) {
                  throw mclCaptureFailure(error, {
                    stage: 'KAFKA_CONSUMER_PAUSE', detailCode: 'CONSUMER_PAUSE_REJECTED',
                  })
                }
                if (pending.size === 0) resolveCompletion()
              }
            } catch (error) {
              rejectCompletion(error)
              throw error
            }
          },
        }),
        'KAFKA_CONSUMER_RUN',
        'CONSUMER_RUN_REJECTED',
      )
      await completion
    } finally {
      try {
        removeGroupJoinListener()
      } catch (error) {
        innerCleanupFailure = mclCaptureFailure(error, {
          stage: 'KAFKA_CONSUMER_CLEANUP', detailCode: 'GROUP_LISTENER_REMOVAL_REJECTED',
        })
      }
      clearTimeout(timer)
      try {
        await consumer.stop()
      } catch (error) {
        innerCleanupFailure ||= mclCaptureFailure(error, {
          stage: 'KAFKA_CONSUMER_CLEANUP', detailCode: 'CONSUMER_STOP_REJECTED',
        })
      }
    }
    if (innerCleanupFailure) throw innerCleanupFailure
    return captureResult(config, targets)
  }
  try {
    result = await executeCapture()
  } catch (error) {
    primaryError = error
  } finally {
    if (consumerConnected) {
      try {
        await consumer.disconnect()
      } catch (error) {
        cleanupFailure = mclCaptureFailure(error, {
          stage: 'KAFKA_CONSUMER_CLEANUP', detailCode: 'CONSUMER_DISCONNECT_REJECTED',
        })
      }
    }
    if (adminConnected) {
      try {
        await admin.disconnect()
      } catch (error) {
        cleanupFailure ||= mclCaptureFailure(error, {
          stage: 'KAFKA_ADMIN_CLEANUP', detailCode: 'ADMIN_DISCONNECT_REJECTED',
        })
      }
    }
  }
  if (primaryError) throw primaryError
  if (cleanupFailure) throw cleanupFailure
  return result
}

function captureResult(config, targets) {
  const degraded = targets.some(({ gapReceiptCount }) => gapReceiptCount > 0)
  return {
    topic: config.topic,
    sourceIdentityHash: config.sourceIdentityHash,
    bounded: true,
    caughtUp: targets.every(({ next, sourceHigh }) => next === sourceHigh),
    historyCompleteness: degraded ? 'DEGRADED_GAP' : 'EXACT',
    partitions: targets.map(({
      partition, low, high, sourceHigh, next, processed, ledgerEvents,
      gapReceiptCount, currentSegmentStart,
    }) => ({
      partition,
      lowWatermark: low,
      capturedHighWatermark: high,
      sourceHighWatermark: sourceHigh,
      nextOffset: next,
      processedRecords: processed,
      ledgerEvents,
      historyCompleteness: gapReceiptCount > 0 ? 'DEGRADED_GAP' : 'EXACT',
      gapReceiptCount,
      exactCurrentSegmentStart: currentSegmentStart,
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
  if (currentFields.size || previousFields.size) {
    return [
      ...diffMaps(currentFields, previousFields, evidence),
      ...diffFieldMetadata(current, previous, evidence, maximum, 'schemaMetadata'),
    ]
  }
  return singletonDiff('schema', schemaSummary(current), schemaSummary(previous), evidence)
}

function normalizeEditableSchemaMetadata(current, previous, evidence, maximum) {
  const currentFields = editableSchemaFieldMap(current, maximum)
  const previousFields = editableSchemaFieldMap(previous, maximum)
  return [
    ...diffMaps(currentFields, previousFields, evidence),
    ...diffFieldMetadata(current, previous, evidence, maximum, 'editableSchemaMetadata'),
  ]
}

function normalizeDatasetProperties(current, previous, evidence, maximum) {
  return normalizationStep(() => {
    const snapshot = (document) => document === null ? null : {
      description: optionalDescription(document.description, 'description', 4096),
      custom_properties: normalizedStringMap(document.customProperties, maximum),
    }
    return singletonDiff('dataset-properties', snapshot(current), snapshot(previous), evidence)
  }, 'DOCUMENT_FIELD_CONTRACT_INVALID')
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
  return normalizationStep(() => {
    const fields = requiredBoundedArray(document.fields, 'schemaMetadata.fields', maximum)
    const result = new Map()
    for (const field of fields) {
      if (!isPlainObject(field)) throw new Error('A schemaMetadata field is invalid.')
      const path = boundedString(field.fieldPath, 'schemaMetadata.fieldPath', 900)
      if (result.has(path)) {
        throw mclRecordNormalizationFailure(
          new Error('A schemaMetadata field path is duplicated.'),
          'SCHEMA_FIELD_DUPLICATE',
        )
      }
      result.set(path, {
        field_path: path,
        native_data_type: boundedString(field.nativeDataType, 'nativeDataType', 500),
        logical_type: logicalType(field.type),
        description: optionalDescription(field.description, 'description', 4096),
        nullable: nullableValue(field.nullable),
      })
    }
    return result
  }, 'SCHEMA_FIELD_CONTRACT_INVALID')
}

function diffFieldMetadata(current, previous, evidence, maximum, sourceAspect) {
  const currentTags = fieldMetadataMap(current, maximum, sourceAspect, 'globalTags')
  const previousTags = fieldMetadataMap(previous, maximum, sourceAspect, 'globalTags')
  const currentTerms = fieldMetadataMap(current, maximum, sourceAspect, 'glossaryTerms')
  const previousTerms = fieldMetadataMap(previous, maximum, sourceAspect, 'glossaryTerms')
  return [
    ...diffMetadataMaps(currentTags, previousTags, evidence, sourceAspect, 'TAG', 'tag_urn'),
    ...diffMetadataMaps(currentTerms, previousTerms, evidence, sourceAspect, 'GLOSSARY_TERM', 'term_urn'),
  ]
}

function fieldMetadataMap(document, maximum, sourceAspect, metadataName) {
  if (document === null) return new Map()
  return normalizationStep(() => {
    const fields = sourceAspect === 'schemaMetadata'
      ? requiredBoundedArray(document.fields, 'schemaMetadata.fields', maximum)
      : requiredBoundedArray(document.editableSchemaFieldInfo, 'editableSchemaFieldInfo', maximum)
    const result = new Map()
    for (const field of fields) {
      if (!isPlainObject(field)) throw new Error(`A ${sourceAspect} field is invalid.`)
      const path = boundedString(field.fieldPath, `${sourceAspect}.fieldPath`, 900)
      const items = metadataName === 'globalTags'
        ? boundedArray(field.globalTags?.tags, `${sourceAspect}.globalTags.tags`, maximum)
        : boundedArray(field.glossaryTerms?.terms, `${sourceAspect}.glossaryTerms.terms`, maximum)
      for (const item of items) {
        if (!isPlainObject(item)) throw new Error(`A ${sourceAspect} ${metadataName} item is invalid.`)
        const normalized = metadataName === 'globalTags'
          ? { field_path: path, tag_urn: boundedString(item.tag, `${sourceAspect}.globalTags.tag`, 1000) }
          : { field_path: path, term_urn: boundedString(item.urn, `${sourceAspect}.glossaryTerms.urn`, 1000) }
        const key = stableJson(normalized)
        if (result.has(key)) {
          throw mclRecordNormalizationFailure(
            new Error(`A ${sourceAspect} ${metadataName} item is duplicated.`),
            'COLLECTION_ITEM_DUPLICATE',
          )
        }
        result.set(key, normalized)
      }
    }
    return result
  }, 'COLLECTION_ITEM_CONTRACT_INVALID')
}

function diffMetadataMaps(current, previous, evidence, sourceAspect, category, keyName) {
  const events = []
  for (const key of [...new Set([...current.keys(), ...previous.keys()])].sort()) {
    const beforeData = previous.get(key) ?? null
    const afterData = current.get(key) ?? null
    if (stableJson(beforeData) === stableJson(afterData)) continue
    const metadata = afterData ?? beforeData
    events.push(semanticEvent(
      fieldMetadataEntityKey(metadata, keyName),
      beforeData,
      afterData,
      { ...evidence, sourceAspect, normalizedCategory: 'METADATA_CHANGE', storageCategory: category },
      afterData ? 'ADD' : 'REMOVE',
    ))
  }
  return events
}

function fieldMetadataEntityKey(metadata, keyName) {
  return `field-metadata:${sha256(stableJson([metadata.field_path, keyName, metadata[keyName]]))}`
}

function editableSchemaFieldMap(document, maximum) {
  if (document === null) return new Map()
  return normalizationStep(() => {
    const fields = requiredBoundedArray(document.editableSchemaFieldInfo, 'editableSchemaFieldInfo', maximum)
    const result = new Map()
    for (const field of fields) {
      if (!isPlainObject(field)) throw new Error('An editable schema field is invalid.')
      const path = boundedString(field.fieldPath, 'editableSchemaFieldInfo.fieldPath', 900)
      if (result.has(path)) {
        throw mclRecordNormalizationFailure(
          new Error('An editable schema field path is duplicated.'),
          'SCHEMA_FIELD_DUPLICATE',
        )
      }
      result.set(path, {
        field_path: path,
        description: optionalDescription(field.description, 'description', 4096),
      })
    }
    return result
  }, 'SCHEMA_FIELD_CONTRACT_INVALID')
}

function normalizeStatus(current, previous, evidence) {
  return normalizationStep(() => {
    if (current === null || previous === null) {
      if (current !== null) statusRemoved(current)
      if (previous !== null) statusRemoved(previous)
      return []
    }
    const beforeRemoved = statusRemoved(previous)
    const afterRemoved = statusRemoved(current)
    if (beforeRemoved === afterRemoved) return []
    return [semanticEvent(
      'asset:lifecycle:removed',
      { removed: beforeRemoved },
      { removed: afterRemoved },
      evidence,
      afterRemoved ? 'DELETE' : 'CREATE',
    )]
  }, 'ENTITY_LIFECYCLE_CONTRACT_INVALID')
}

function statusRemoved(document) {
  if (!isPlainObject(document) || (document.removed !== undefined && typeof document.removed !== 'boolean')) {
    throw new Error('status.removed must be an explicit boolean.')
  }
  return document.removed ?? false
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
  return normalizationStep(() => {
    const collectionName = aspectName === 'globalTags' ? 'tags'
      : aspectName === 'glossaryTerms' ? 'terms'
        : aspectName === 'domains' ? 'domains' : 'owners'
    const items = requiredBoundedArray(document[collectionName], `${aspectName}.${collectionName}`, maximum)
    const result = new Map()
    for (const item of items) {
      if (aspectName !== 'domains' && !isPlainObject(item)) throw new Error(`An ${aspectName} item is invalid.`)
      const normalized = aspectName === 'globalTags'
        ? { tag_urn: boundedString(item.tag, 'globalTags.tag', 1000) }
        : aspectName === 'glossaryTerms'
          ? { term_urn: boundedString(item.urn, 'glossaryTerms.urn', 1000) }
          : aspectName === 'domains'
            ? { domain_urn: boundedString(item, 'domains.domains', 1000) }
          : {
              owner_urn: boundedString(item.owner, 'ownership.owner', 1000),
              ownership_type: boundedString(item.type, 'ownership.type', 500),
            }
      const key = stableJson(normalized)
      if (result.has(key)) {
        throw mclRecordNormalizationFailure(
          new Error(`An ${aspectName} item is duplicated.`),
          'COLLECTION_ITEM_DUPLICATE',
        )
      }
      result.set(key, normalized)
    }
    return result
  }, 'COLLECTION_ITEM_CONTRACT_INVALID')
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

function logicalType(value) {
  return normalizationStep(() => {
    if (!isPlainObject(value) || Object.keys(value).length !== 1 || !Object.hasOwn(value, 'type')) {
      throw new Error('schemaMetadata.type must be a single supported union discriminator.')
    }
    const union = value.type
    if (!isPlainObject(union)) throw new Error('schemaMetadata.type must be a single supported union discriminator.')
    const keys = Object.keys(union)
    const discriminator = keys[0]
    if (keys.length !== 1 || !Object.hasOwn(LOGICAL_TYPE_BY_DATAHUB_DISCRIMINATOR, discriminator)
      || !isPlainObject(union[discriminator])) {
      throw new Error('schemaMetadata.type must be a single supported union discriminator.')
    }
    return LOGICAL_TYPE_BY_DATAHUB_DISCRIMINATOR[discriminator]
  }, 'LOGICAL_TYPE_CONTRACT_INVALID')
}

function nullableValue(value) {
  if (value === undefined) return false
  if (typeof value !== 'boolean') throw new Error('schemaMetadata.nullable must be a boolean.')
  return value
}

function decodeAspectDocument(container, field, maximumBytes) {
  if (container == null) return null
  if (!isRecordObject(container)
    || !Object.hasOwn(container, 'value')
    || container.contentType !== GENERIC_ASPECT_JSON_CONTENT_TYPE) {
    throw mclRecordNormalizationFailure(
      new Error(`${field} does not use the supported GenericAspect JSON content type.`),
      'ASPECT_CONTENT_TYPE_INVALID',
    )
  }
  let value = container.value
  if (Buffer.isBuffer(value) || value instanceof Uint8Array) {
    const bytes = Buffer.from(value)
    if (bytes.length < 2 || bytes.length > maximumBytes) {
      throw mclRecordNormalizationFailure(
        new Error(`${field} is outside the byte bound.`),
        'ASPECT_SIZE_LIMIT_EXCEEDED',
      )
    }
    value = bytes.toString('utf8')
  }
  if (typeof value === 'string') {
    if (Buffer.byteLength(value, 'utf8') > maximumBytes) {
      throw mclRecordNormalizationFailure(
        new Error(`${field} is outside the byte bound.`),
        'ASPECT_SIZE_LIMIT_EXCEEDED',
      )
    }
    try {
      value = JSON.parse(value)
    } catch {
      throw mclRecordNormalizationFailure(
        new Error(`${field} is not valid bounded JSON.`),
        'ASPECT_JSON_INVALID',
      )
    }
  }
  if (!isPlainObject(value)) {
    throw mclRecordNormalizationFailure(
      new Error(`${field} is not a decoded aspect object.`),
      'ASPECT_JSON_INVALID',
    )
  }
  if (Buffer.byteLength(stableJson(value), 'utf8') > maximumBytes) {
    throw mclRecordNormalizationFailure(
      new Error(`${field} is outside the byte bound.`),
      'ASPECT_SIZE_LIMIT_EXCEEDED',
    )
  }
  return value
}

function profileAspectDocument(container, maximumBytes) {
  const contentType = container == null
    ? 'MISSING'
    : container?.contentType === GENERIC_ASPECT_JSON_CONTENT_TYPE
      ? 'APPLICATION_JSON'
      : 'OTHER'
  if (container == null || contentType !== 'APPLICATION_JSON' || !Object.hasOwn(container, 'value')) {
    return { contentType, decodedObject: false, document: null }
  }
  let value = container.value
  try {
    if (Buffer.isBuffer(value) || value instanceof Uint8Array) {
      const bytes = Buffer.from(value)
      if (bytes.length < 2 || bytes.length > maximumBytes) {
        return { contentType, decodedObject: false, document: null }
      }
      value = bytes.toString('utf8')
    }
    if (typeof value === 'string') {
      if (Buffer.byteLength(value, 'utf8') > maximumBytes) {
        return { contentType, decodedObject: false, document: null }
      }
      value = JSON.parse(value)
    }
    const decodedObject = isPlainObject(value)
      && Buffer.byteLength(stableJson(value), 'utf8') <= maximumBytes
    return { contentType, decodedObject, document: decodedObject ? value : null }
  } catch {
    return { contentType, decodedObject: false, document: null }
  }
}

function profileCollectionItemCount(aspectName, document) {
  if (!isPlainObject(document)) return null
  const collection = aspectName === 'schemaMetadata' ? document.fields
    : aspectName === 'editableSchemaMetadata' ? document.editableSchemaFieldInfo
      : aspectName === 'globalTags' ? document.tags
        : aspectName === 'glossaryTerms' ? document.terms
          : aspectName === 'domains' ? document.domains
            : aspectName === 'ownership' ? document.owners
              : null
  return Array.isArray(collection) && collection.length <= 1_000_000 ? collection.length : null
}

function boundedShapeIdentifier(value) {
  if (value == null || value === '') return 'MISSING'
  return typeof value === 'string' && /^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(value)
    ? value
    : 'MALFORMED'
}

function boundedShapeChangeType(value) {
  if (value == null || value === '') return 'MISSING'
  return ['UPSERT', 'CREATE', 'UPDATE', 'DELETE', 'PATCH', 'RESTATE', 'CREATE_ENTITY'].includes(value)
    ? value
    : 'OTHER'
}

function shapeType(value) {
  if (value === null) return 'NULL'
  if (value === undefined) return 'UNDEFINED'
  const type = typeof value
  return ['boolean', 'number', 'string', 'bigint', 'object', 'function', 'symbol'].includes(type)
    ? type.toUpperCase()
    : 'OTHER'
}

function createdTimeRepresentation(value) {
  if (value == null) return 'NULL'
  if (typeof value === 'number') return 'NUMBER'
  if (typeof value === 'string') return 'STRING'
  if (isRecordObject(value)
    && Number.isInteger(value.low)
    && Number.isInteger(value.high)
    && (value.unsigned === undefined || typeof value.unsigned === 'boolean')) return 'LONG_OBJECT'
  return 'OTHER'
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
  const registryBearerToken = config.schemaRegistry.bearerToken === undefined
    ? undefined
    : boundedSecret(config.schemaRegistry.bearerToken, 'schemaRegistry.bearerToken')
  if (registryAuth && registryBearerToken) {
    throw new Error('Schema Registry Basic and Bearer authentication cannot both be configured.')
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
      bearerToken: registryBearerToken,
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

function requiredBoundedArray(value, field, maximum) {
  if (!Array.isArray(value) || value.length > maximum) throw new Error(`${field} is outside its item bound.`)
  return value
}

function normalizeOccurredAt(value) {
  if (value == null) return null
  if (typeof value === 'number' && validEpochMilliseconds(value)) return new Date(value).toISOString()
  if (typeof value === 'string' && /^\d+$/.test(value)) {
    const milliseconds = Number(value)
    if (validEpochMilliseconds(milliseconds)) return new Date(milliseconds).toISOString()
  }
  return explicitUtcTimestamp(value, 'created.time')
}

function validEpochMilliseconds(value) {
  return Number.isSafeInteger(value) && value >= 0 && value <= 8_640_000_000_000_000
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

function sha256(value) {
  return createHash('sha256').update(value).digest('hex')
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

function optionalDescription(value, field, maximum) {
  if (value == null || value === '') return null
  if (typeof value !== 'string' || value.length > maximum) {
    throw new Error(`${field} is outside its string bound.`)
  }
  return value
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
