/* global Buffer */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { URL } from 'node:url'

import { SchemaRegistry, SchemaType } from '@kafkajs/confluent-schema-registry'
import KafkaJs from 'kafkajs'
import avro from 'avsc'
import SnappyCodec from 'kafkajs-snappy'

import {
  createPocMclCapture,
  decodeConfluentMcl,
  normalizeMclRecord,
} from './poc-mcl-capture.mjs'

const { CompressionCodecs, CompressionTypes } = KafkaJs

const SOURCE_HASH = 'a'.repeat(64)
const SCHEMA_HASH = 'b'.repeat(64)
const TOPIC = 'MetadataChangeLog_Versioned_v1'
const REGISTRY_ID = 17
const SCHEMA_FIELD_LOGICAL_TYPES = [
  'BooleanType', 'FixedType', 'StringType', 'BytesType', 'NumberType', 'DateType', 'TimeType',
  'EnumType', 'NullType', 'MapType', 'ArrayType', 'UnionType', 'RecordType',
]
const MCL_SCHEMA = {
  type: 'record',
  name: 'MetadataChangeLog',
  fields: [
    { name: 'entityUrn', type: 'string' },
    { name: 'aspectName', type: 'string' },
    {
      name: 'aspect',
      type: ['null', {
        type: 'record',
        name: 'GenericAspect',
        fields: [
          { name: 'contentType', type: 'string' },
          { name: 'value', type: 'bytes' },
        ],
      }],
      default: null,
    },
    { name: 'previousAspectValue', type: ['null', 'GenericAspect'], default: null },
    {
      name: 'created',
      type: {
        type: 'record',
        name: 'AuditStamp',
        fields: [
          { name: 'actor', type: ['null', 'string'], default: null },
          { name: 'time', type: ['null', 'long'], default: null },
        ],
      },
    },
  ],
}

function schemaFieldType(logicalType) {
  return { type: { [`com.linkedin.schema.${logicalType}`]: {} } }
}

test('registers the pure-JavaScript Snappy codec at the MCL Kafka boundary', async () => {
  assert.equal(CompressionCodecs[CompressionTypes.Snappy], SnappyCodec)
  const codec = CompressionCodecs[CompressionTypes.Snappy]()
  const payload = Buffer.from('bounded MCL Snappy decode')
  const compressed = await codec.compress({ buffer: payload })
  assert.deepEqual(await codec.decompress(compressed), payload)
})

function schemaRegistry() {
  const registry = new SchemaRegistry({ host: 'http://schema-registry.invalid' })
  registry.cache.setSchema(REGISTRY_ID, SchemaType.AVRO, avro.Type.forSchema(MCL_SCHEMA))
  return registry
}

async function framedMcl(overrides = {}) {
  const registry = schemaRegistry()
  const record = {
    entityUrn: 'urn:li:dataset:(urn:li:dataPlatform:postgres,db.schema.table,PROD)',
    aspectName: 'schemaMetadata',
    aspect: {
      contentType: 'application/json',
      value: Buffer.from(JSON.stringify({
        fields: [
          { fieldPath: 'id', nativeDataType: 'bigint', type: schemaFieldType('NumberType'), nullable: false },
          { fieldPath: 'name', nativeDataType: 'varchar', type: schemaFieldType('StringType'), nullable: true },
        ],
      })),
    },
    previousAspectValue: {
      contentType: 'application/json',
      value: Buffer.from(JSON.stringify({
        fields: [{ fieldPath: 'id', nativeDataType: 'integer', type: schemaFieldType('NumberType'), nullable: false }],
      })),
    },
    created: { actor: 'urn:li:corpuser:builder', time: 1_786_634_800_000 },
    ...overrides,
  }
  return { registry, buffer: await registry.encode(REGISTRY_ID, record) }
}

function captureConfig(overrides = {}) {
  return {
    brokers: ['kafka.invalid:9092'],
    clientId: 'datariver-poc-mcl',
    groupId: 'datariver-poc-mcl-capture',
    topic: TOPIC,
    sourceIdentityHash: SOURCE_HASH,
    schemaContractHash: SCHEMA_HASH,
    providerName: 'DataHub',
    providerVersion: 'contract-test',
    kafkaSsl: false,
    schemaRegistry: { host: 'http://schema-registry.invalid' },
    maxMessages: 100,
    maxRecordBytes: 65_536,
    timeoutMs: 2000,
    ...overrides,
  }
}

function stateStoreDouble(initial = {}, { failOffset, failBoundary = false } = {}) {
  const checkpoints = new Map(Object.entries(initial).map(([partition, offset]) => [Number(partition), offset]))
  const captures = []
  return {
    checkpoints,
    captures,
    async initializeChangeHistoryCaptureBoundaries({ partitions }) {
      if (failBoundary) throw new Error('simulated durable boundary failure')
      const requested = partitions.map(({ partition }) => partition).sort((left, right) => left - right)
      if (checkpoints.size === 0) {
        for (const { partition, boundary } of partitions) checkpoints.set(partition, boundary)
      } else if (checkpoints.size !== requested.length
        || [...checkpoints.keys()].sort((left, right) => left - right)
          .some((partition, index) => partition !== requested[index])) {
        throw new Error('simulated partition topology change')
      }
      return requested.map((partition) => ({ partition, nextOffset: checkpoints.get(partition) }))
    },
    async readChangeHistoryCheckpoint({ partition }) {
      return checkpoints.get(partition) ?? null
    },
    async appendChangeHistoryCapture(capture) {
      if (capture.offset === failOffset) throw new Error('simulated durable DB failure')
      const expected = checkpoints.get(capture.partition) ?? capture.offset
      if (expected !== capture.offset) throw new Error('simulated checkpoint gap')
      captures.push(capture)
      checkpoints.set(capture.partition, capture.offset + 1)
      return {
        sourceEventIdentity: 'c'.repeat(64),
        eventIdentities: capture.events.map((_, index) => String(index).padStart(64, '0')),
        nextOffset: capture.offset + 1,
        replayed: false,
      }
    },
  }
}

function kafkaDouble(partitions, messages) {
  let consumerCreates = 0
  const state = { stopped: false, disconnected: false, consumerCreates }
  return {
    state,
    admin() {
      return {
        async connect() {},
        async fetchTopicOffsets(topic) {
          assert.equal(topic, TOPIC)
          return partitions
        },
        async disconnect() {},
      }
    },
    consumer(options) {
      consumerCreates += 1
      state.consumerCreates = consumerCreates
      assert.equal(options.groupId, 'datariver-poc-mcl-capture')
      let handler
      const seeks = new Map()
      let started = false
      const groupJoinListeners = new Set()
      const dispatch = async () => {
        for (const [partition, offset] of seeks) {
          for (const message of messages.get(partition) ?? []) {
            if (Number(message.offset) >= Number(offset)) await handler({ partition, message })
          }
        }
      }
      return {
        async connect() {},
        async subscribe(subscription) {
          assert.deepEqual(subscription, { topic: TOPIC, fromBeginning: true })
        },
        async run(options) {
          assert.equal(options.autoCommit, false)
          handler = options.eachMessage
          for (const listener of groupJoinListeners) listener({})
        },
        events: { GROUP_JOIN: 'consumer.group_join' },
        on(event, listener) {
          assert.equal(event, 'consumer.group_join')
          groupJoinListeners.add(listener)
          return () => groupJoinListeners.delete(listener)
        },
        seek({ partition, offset }) {
          seeks.set(partition, offset)
          if (!started && seeks.size === partitions.filter((item) => Number(item.high) > 0).length) {
            started = true
            dispatch().catch(() => undefined)
          }
        },
        pause() {},
        async stop() { state.stopped = true },
        async disconnect() { state.disconnected = true },
      }
    },
  }
}

test('decodes an actual Confluent-framed Avro MCL and fans one record into bounded schema events', async () => {
  const { registry, buffer } = await framedMcl()
  const decoded = await decodeConfluentMcl(buffer, registry, 65_536)
  const normalized = normalizeMclRecord(decoded, { detectedAt: '2026-08-14T01:00:00.000Z' })
  assert.equal(buffer[0], 0)
  assert.equal(buffer.readInt32BE(1), REGISTRY_ID)
  assert.equal(normalized.normalizedCategory, 'SCHEMA_CHANGE')
  assert.equal(normalized.events.length, 2)
  assert.deepEqual(normalized.events.map((event) => [event.entityKey, event.operation]), [
    ['field:id', 'UPDATE'],
    ['field:name', 'CREATE'],
  ])
  assert.ok(normalized.events.every((event) => event.storageCategory === 'TECHNICAL_SCHEMA'))
})

test('captures multiple partitions to captured high watermarks and resumes only from durable DB checkpoints', async () => {
  const schema = await framedMcl()
  const unsupported = await framedMcl({
    aspectName: 'unsupportedAspect',
    aspect: { contentType: 'application/json', value: Buffer.from('{not-json') },
  })
  const ownership = await framedMcl({
    aspectName: 'ownership',
    aspect: {
      contentType: 'application/json',
      value: Buffer.from(JSON.stringify({
        owners: [{ owner: 'urn:li:corpuser:owner', type: 'TECHNICAL_OWNER' }],
      })),
    },
    previousAspectValue: null,
  })
  const messages = new Map([
    [0, [{ offset: '0', value: schema.buffer }, { offset: '1', value: unsupported.buffer }]],
    [1, [{ offset: '0', value: ownership.buffer }]],
  ])
  const kafka = kafkaDouble([
    { partition: 0, low: '0', high: '2', offset: '0' },
    { partition: 1, low: '0', high: '1', offset: '0' },
  ], messages)
  const store = stateStoreDouble({ 0: 0, 1: 0 })
  const capture = createPocMclCapture({
    config: captureConfig(),
    stateStore: store,
    kafka,
    schemaRegistry: schema.registry,
    clock: () => new Date('2026-08-14T01:00:00.000Z'),
  })
  const result = await capture.run()
  assert.deepEqual(result.partitions.map((item) => [item.partition, item.nextOffset]), [[0, 2], [1, 1]])
  assert.deepEqual(store.captures.map((item) => [item.partition, item.offset, item.events.length]), [
    [0, 0, 2],
    [0, 1, 0],
    [1, 0, 1],
  ])
  assert.equal(kafka.state.stopped, true)
  assert.equal(kafka.state.disconnected, true)

  const restartKafka = kafkaDouble([
    { partition: 0, low: '0', high: '2', offset: '0' },
    { partition: 1, low: '0', high: '1', offset: '0' },
  ], messages)
  const restart = createPocMclCapture({
    config: captureConfig(),
    stateStore: store,
    kafka: restartKafka,
    schemaRegistry: schema.registry,
  })
  const restarted = await restart.run()
  assert.deepEqual(restarted.partitions.map((item) => item.nextOffset), [2, 1])
  assert.equal(restartKafka.state.consumerCreates, 0)
  assert.equal(store.captures.length, 3)
})

test('fails safe on malformed supported MCL and on DB failure without advancing its durable checkpoint', async () => {
  const malformed = await framedMcl({
    aspect: { contentType: 'application/json', value: Buffer.from('{not-json') },
  })
  const decoded = await decodeConfluentMcl(malformed.buffer, malformed.registry, 65_536)
  assert.throws(
    () => normalizeMclRecord(decoded, { detectedAt: '2026-08-14T01:00:00.000Z' }),
    /not valid bounded JSON/,
  )

  const valid = await framedMcl()
  const store = stateStoreDouble({ 0: 0 }, { failOffset: 0 })
  const kafka = kafkaDouble(
    [{ partition: 0, low: '0', high: '1', offset: '0' }],
    new Map([[0, [{ offset: '0', value: valid.buffer }]]]),
  )
  const capture = createPocMclCapture({
    config: captureConfig(),
    stateStore: store,
    kafka,
    schemaRegistry: valid.registry,
    clock: () => new Date('2026-08-14T01:00:00.000Z'),
  })
  await assert.rejects(capture.run(), /simulated durable DB failure/)
  assert.equal(store.checkpoints.get(0), 0)
  assert.equal(store.captures.length, 0)
})

test('persists earliest retained fresh boundaries before consume and fails closed on retention, topology, or boundary failure', async () => {
  const fixture = await framedMcl()
  const nonemptyStore = stateStoreDouble()
  const nonemptyKafka = kafkaDouble([
    { partition: 0, low: '0', high: '2', offset: '0' },
    { partition: 1, low: '0', high: '1', offset: '0' },
  ], new Map([
    [0, [{ offset: '0', value: fixture.buffer }, { offset: '1', value: fixture.buffer }]],
    [1, [{ offset: '0', value: fixture.buffer }]],
  ]))
  const nonemptyResult = await createPocMclCapture({
    config: captureConfig(),
    stateStore: nonemptyStore,
    kafka: nonemptyKafka,
    schemaRegistry: fixture.registry,
  }).run()
  assert.deepEqual([...nonemptyStore.checkpoints.entries()], [[0, 2], [1, 1]])
  assert.deepEqual(nonemptyResult.partitions.map((item) => item.nextOffset), [2, 1])
  assert.equal(nonemptyKafka.state.consumerCreates, 1)
  assert.equal(nonemptyResult.caughtUp, true)

  const emptyKafka = kafkaDouble(
    [{ partition: 0, low: '100', high: '100', offset: '100' }],
    new Map(),
  )
  const store = stateStoreDouble()
  const emptyCapture = createPocMclCapture({
    config: captureConfig(),
    stateStore: store,
    kafka: emptyKafka,
    schemaRegistry: schemaRegistry(),
  })
  const emptyResult = await emptyCapture.run()
  assert.equal(store.checkpoints.get(0), 100)
  assert.equal(emptyResult.partitions[0].nextOffset, 100)
  assert.equal(emptyKafka.state.consumerCreates, 0)

  const concurrentStore = stateStoreDouble()
  const concurrentKafka = [0, 1].map(() => kafkaDouble(
    [{ partition: 0, low: '100', high: '100', offset: '100' }],
    new Map(),
  ))
  const concurrentResults = await Promise.all(concurrentKafka.map((kafka) => createPocMclCapture({
    config: captureConfig(),
    stateStore: concurrentStore,
    kafka,
    schemaRegistry: schemaRegistry(),
  }).run()))
  assert.deepEqual(concurrentResults.map((result) => result.partitions[0].nextOffset), [100, 100])
  assert.equal(concurrentStore.checkpoints.get(0), 100)
  assert.ok(concurrentKafka.every((kafka) => kafka.state.consumerCreates === 0))

  const retainedKafka = kafkaDouble(
    [{ partition: 0, low: '150', high: '150', offset: '150' }],
    new Map(),
  )
  await assert.rejects(createPocMclCapture({
    config: captureConfig(),
    stateStore: store,
    kafka: retainedKafka,
    schemaRegistry: schemaRegistry(),
  }).run(), /behind Kafka retention/)
  assert.equal(store.checkpoints.get(0), 100)
  assert.equal(retainedKafka.state.consumerCreates, 0)

  const changedKafka = kafkaDouble([
    { partition: 0, low: '100', high: '100', offset: '100' },
    { partition: 1, low: '0', high: '0', offset: '0' },
  ], new Map())
  await assert.rejects(createPocMclCapture({
    config: captureConfig(),
    stateStore: store,
    kafka: changedKafka,
    schemaRegistry: schemaRegistry(),
  }).run(), /partition topology change/)
  assert.equal(changedKafka.state.consumerCreates, 0)

  const missingStore = stateStoreDouble({ 0: 100, 1: 0 })
  const missingKafka = kafkaDouble(
    [{ partition: 0, low: '100', high: '100', offset: '100' }],
    new Map(),
  )
  await assert.rejects(createPocMclCapture({
    config: captureConfig(),
    stateStore: missingStore,
    kafka: missingKafka,
    schemaRegistry: schemaRegistry(),
  }).run(), /partition topology change/)
  assert.equal(missingKafka.state.consumerCreates, 0)

  const failedStore = stateStoreDouble({}, { failBoundary: true })
  const failedKafka = kafkaDouble(
    [{ partition: 0, low: '0', high: '1', offset: '0' }],
    new Map(),
  )
  await assert.rejects(createPocMclCapture({
    config: captureConfig(),
    stateStore: failedStore,
    kafka: failedKafka,
    schemaRegistry: schemaRegistry(),
  }).run(), /simulated durable boundary failure/)
  assert.equal(failedStore.checkpoints.size, 0)
  assert.equal(failedKafka.state.consumerCreates, 0)
})

test('backfills a new source from the earliest retained offset in bounded durable batches', async () => {
  const fixture = await framedMcl()
  const store = stateStoreDouble()
  const messages = new Map([[0, [0, 1, 2].map((offset) => ({
    offset: String(offset), value: fixture.buffer,
  }))]])
  const offsets = [{ partition: 0, low: '0', high: '3', offset: '0' }]
  const first = await createPocMclCapture({
    config: captureConfig({ maxMessages: 2 }), stateStore: store,
    kafka: kafkaDouble(offsets, messages), schemaRegistry: fixture.registry,
  }).run()
  assert.equal(first.caughtUp, false)
  assert.equal(first.partitions[0].nextOffset, 2)
  assert.equal(store.checkpoints.get(0), 2)

  const second = await createPocMclCapture({
    config: captureConfig({ maxMessages: 2 }), stateStore: store,
    kafka: kafkaDouble(offsets, messages), schemaRegistry: fixture.registry,
  }).run()
  assert.equal(second.caughtUp, true)
  assert.equal(second.partitions[0].nextOffset, 3)
  assert.equal(store.checkpoints.get(0), 3)
})

test('accepts only the exact DataHub GenericAspect JSON content type', () => {
  const record = {
    entityUrn: 'urn:li:dataset:(urn:li:dataPlatform:postgres,db.schema.table,PROD)',
    aspectName: 'datasetProperties',
    aspect: {
      contentType: 'application/json',
      value: Buffer.from(JSON.stringify({ description: 'bounded' })),
    },
    previousAspectValue: null,
    created: { actor: null, time: null },
  }
  assert.equal(normalizeMclRecord(record, {
    detectedAt: '2026-08-14T01:00:00.000Z',
  }).supported, true)
  for (const aspect of [
    { value: Buffer.from('{}') },
    { contentType: 'application/avro', value: Buffer.from('{}') },
    { contentType: 'text/plain', value: Buffer.from('{}') },
  ]) {
    assert.throws(() => normalizeMclRecord({ ...record, aspect }, {
      detectedAt: '2026-08-14T01:00:00.000Z',
    }), /supported GenericAspect JSON content type/)
  }
})

test('normalizes empty descriptions to null only at MCL description call sites', () => {
  const detectedAt = '2026-08-14T01:00:00.000Z'
  const base = {
    entityUrn: 'urn:li:dataset:(urn:li:dataPlatform:postgres,db.schema.table,PROD)',
    previousAspectValue: null,
    created: { actor: null, time: null },
  }
  const normalizedSchema = normalizeMclRecord({
    ...base,
    aspectName: 'schemaMetadata',
    aspect: { contentType: 'application/json', value: Buffer.from(JSON.stringify({
      fields: [{ fieldPath: 'id', nativeDataType: 'varchar', type: schemaFieldType('StringType'), description: '' }],
    })) },
  }, { detectedAt })
  assert.equal(normalizedSchema.events[0].afterData.description, null)

  const normalizedEditableFields = normalizeMclRecord({
    ...base,
    aspectName: 'editableSchemaMetadata',
    aspect: { contentType: 'application/json', value: Buffer.from(JSON.stringify({
      editableSchemaFieldInfo: [
        { fieldPath: 'id', description: '' },
        { fieldPath: 'name', description: '' },
      ],
    })) },
  }, { detectedAt })
  assert.deepEqual(normalizedEditableFields.events.map((event) => event.afterData.description), [null, null])

  const normalizedEditableTopLevel = normalizeMclRecord({
    ...base,
    aspectName: 'editableSchemaMetadata',
    aspect: { contentType: 'application/json', value: Buffer.from(JSON.stringify({ description: '' })) },
  }, { detectedAt })
  assert.equal(normalizedEditableTopLevel.events[0].afterData.description, null)

  const normalizedDataset = normalizeMclRecord({
    ...base,
    aspectName: 'datasetProperties',
    aspect: { contentType: 'application/json', value: Buffer.from(JSON.stringify({ description: '   ' })) },
  }, { detectedAt })
  assert.equal(normalizedDataset.events[0].afterData.description, '   ')
})

test('normalizes DataHub domains as explicit bounded metadata changes', () => {
  const aspect = (value) => ({
    contentType: 'application/json',
    value: Buffer.from(JSON.stringify(value)),
  })
  const normalized = normalizeMclRecord({
    entityUrn: 'urn:li:dataset:(urn:li:dataPlatform:postgres,db.schema.table,DEV)',
    aspectName: 'domains',
    previousAspectValue: aspect({ domains: ['urn:li:domain:legacy'] }),
    aspect: aspect({ domains: ['urn:li:domain:current'] }),
    created: { actor: 'urn:li:corpuser:data-steward', time: 1_787_680_000_000 },
  }, { detectedAt: '2026-08-26T00:00:00.000Z' })

  assert.equal(normalized.normalizedCategory, 'METADATA_CHANGE')
  assert.deepEqual(normalized.events.map((event) => [event.storageCategory, event.sourceAspect, event.operation]), [
    ['DOMAIN', 'domains', 'ADD'],
    ['DOMAIN', 'domains', 'REMOVE'],
  ])
  assert.deepEqual(normalized.events.map((event) => event.afterData ?? event.beforeData), [
    { domain_urn: 'urn:li:domain:current' },
    { domain_urn: 'urn:li:domain:legacy' },
  ])
})

test('emits description changes around empty values and treats null and empty as equivalent', () => {
  const detectedAt = '2026-08-14T01:00:00.000Z'
  const base = {
    entityUrn: 'urn:li:dataset:(urn:li:dataPlatform:postgres,db.schema.table,PROD)',
    aspectName: 'editableSchemaMetadata',
    created: { actor: null, time: null },
  }
  const document = (description) => ({
    contentType: 'application/json',
    value: Buffer.from(JSON.stringify({
      editableSchemaFieldInfo: [{ fieldPath: 'id', ...(description === undefined ? {} : { description }) }],
    })),
  })
  const emptyToText = normalizeMclRecord({
    ...base,
    aspect: document('documented'),
    previousAspectValue: document(''),
  }, { detectedAt })
  assert.deepEqual(emptyToText.events.map((event) => [event.beforeData.description, event.afterData.description]), [
    [null, 'documented'],
  ])

  const textToEmpty = normalizeMclRecord({
    ...base,
    aspect: document(''),
    previousAspectValue: document('documented'),
  }, { detectedAt })
  assert.deepEqual(textToEmpty.events.map((event) => [event.beforeData.description, event.afterData.description]), [
    ['documented', null],
  ])

  const nullToEmpty = normalizeMclRecord({
    ...base,
    aspect: document(''),
    previousAspectValue: document(undefined),
  }, { detectedAt })
  assert.deepEqual(nullToEmpty.events, [])
})

test('rejects non-string and over-bound MCL descriptions', () => {
  const detectedAt = '2026-08-14T01:00:00.000Z'
  const base = {
    entityUrn: 'urn:li:dataset:(urn:li:dataPlatform:postgres,db.schema.table,PROD)',
    aspectName: 'datasetProperties',
    previousAspectValue: null,
    created: { actor: null, time: null },
  }
  const record = (description) => ({
    ...base,
    aspect: { contentType: 'application/json', value: Buffer.from(JSON.stringify({ description })) },
  })
  assert.throws(() => normalizeMclRecord(record('x'.repeat(4097)), { detectedAt }), /description is outside its string bound/)
  assert.throws(() => normalizeMclRecord(record(1), { detectedAt }), /description is outside its string bound/)
})

test('normalizes DataHub v1.6 field metadata as bounded source-aspect tag and term deltas', () => {
  const detectedAt = '2026-08-15T00:00:00.000Z'
  const aspect = (value) => ({ contentType: 'application/json', value: Buffer.from(JSON.stringify(value)) })
  const base = {
    entityUrn: 'urn:li:dataset:(urn:li:dataPlatform:postgres,db.schema.table,PROD)',
    aspectName: 'schemaMetadata',
    created: { actor: null, time: null },
  }
  const normalized = normalizeMclRecord({
    ...base,
    previousAspectValue: aspect({ fields: [{
      fieldPath: 'customer_id', nativeDataType: 'integer', nullable: false, type: schemaFieldType('NumberType'),
      globalTags: { tags: [{ tag: 'urn:li:tag:legacy' }] },
      glossaryTerms: { terms: [{ urn: 'urn:li:glossaryTerm:legacy' }] },
    }] }),
    aspect: aspect({ fields: [{
      fieldPath: 'customer_id', nativeDataType: 'bigint', nullable: true, type: schemaFieldType('StringType'),
      globalTags: { tags: [{ tag: 'urn:li:tag:current' }] },
      glossaryTerms: { terms: [{ urn: 'urn:li:glossaryTerm:current' }] },
    }] }),
  }, { detectedAt })
  assert.deepEqual(normalized.events.map((event) => [event.storageCategory, event.sourceAspect, event.operation]), [
    ['TECHNICAL_SCHEMA', 'schemaMetadata', 'UPDATE'],
    ['TAG', 'schemaMetadata', 'ADD'],
    ['TAG', 'schemaMetadata', 'REMOVE'],
    ['GLOSSARY_TERM', 'schemaMetadata', 'ADD'],
    ['GLOSSARY_TERM', 'schemaMetadata', 'REMOVE'],
  ])
  assert.deepEqual(normalized.events[0].afterData, {
    field_path: 'customer_id', native_data_type: 'bigint', logical_type: 'StringType', description: null, nullable: true,
  })

  const editable = normalizeMclRecord({
    ...base,
    aspectName: 'editableSchemaMetadata',
    previousAspectValue: aspect({ editableSchemaFieldInfo: [] }),
    aspect: aspect({ editableSchemaFieldInfo: [{
      fieldPath: 'customer_id', globalTags: { tags: [{ tag: 'urn:li:tag:curated' }] },
      glossaryTerms: { terms: [{ urn: 'urn:li:glossaryTerm:pii' }] },
    }] }),
  }, { detectedAt })
  assert.deepEqual(editable.events.map((event) => [event.storageCategory, event.sourceAspect, event.operation]), [
    ['DOCUMENTATION', 'editableSchemaMetadata', 'CREATE'],
    ['TAG', 'editableSchemaMetadata', 'ADD'],
    ['GLOSSARY_TERM', 'editableSchemaMetadata', 'ADD'],
  ])
  const bounded = normalizeMclRecord({
    ...base,
    previousAspectValue: aspect({ fields: [] }),
    aspect: aspect({ fields: [{
      fieldPath: 'p'.repeat(900), nativeDataType: 'text', nullable: false, type: schemaFieldType('StringType'),
      globalTags: { tags: [{ tag: `urn:li:tag:${'t'.repeat(989)}` }] },
    }] }),
  }, { detectedAt }).events.find((event) => event.storageCategory === 'TAG')
  assert.match(bounded.entityKey, /^field-metadata:[0-9a-f]{64}$/)
  assert.ok(bounded.entityKey.length <= 1000)
  assert.equal(bounded.afterData.field_path.length, 900)
  assert.equal(bounded.afterData.tag_urn.length, 1000)
})

test('normalizes every supported DataHub v1.6 SchemaFieldDataType discriminator', () => {
  const detectedAt = '2026-08-15T00:00:00.000Z'
  const normalized = normalizeMclRecord({
    entityUrn: 'urn:li:dataset:(urn:li:dataPlatform:postgres,db.schema.table,PROD)',
    aspectName: 'schemaMetadata',
    previousAspectValue: null,
    created: { actor: null, time: null },
    aspect: { contentType: 'application/json', value: Buffer.from(JSON.stringify({
      fields: SCHEMA_FIELD_LOGICAL_TYPES.map((logicalType, index) => ({
        fieldPath: `field_${String(index).padStart(2, '0')}`,
        nativeDataType: logicalType,
        type: schemaFieldType(logicalType),
      })),
    })) },
  }, { detectedAt })
  assert.deepEqual(normalized.events.map((event) => [event.afterData.logical_type, event.afterData.nullable]),
    SCHEMA_FIELD_LOGICAL_TYPES.map((logicalType) => [logicalType, false]))
})

test('fails closed for malformed DataHub v1.6 SchemaFieldDataType, nativeDataType, nullable, tag, and term shapes', () => {
  const detectedAt = '2026-08-15T00:00:00.000Z'
  const record = (field) => ({
    entityUrn: 'urn:li:dataset:(urn:li:dataPlatform:postgres,db.schema.table,PROD)',
    aspectName: 'schemaMetadata', previousAspectValue: null, created: { actor: null, time: null },
    aspect: { contentType: 'application/json', value: Buffer.from(JSON.stringify({ fields: [field] })) },
  })
  const valid = { fieldPath: 'id', nativeDataType: 'bigint', nullable: false, type: schemaFieldType('NumberType') }
  const withoutNativeDataType = { ...valid }
  delete withoutNativeDataType.nativeDataType
  for (const invalid of [
    { ...valid, type: 'NUMBER' },
    { ...valid, type: { 'com.linkedin.schema.NumberType': {} } },
    { ...valid, type: {} },
    { ...valid, type: { type: {} } },
    { ...valid, type: { type: { 'com.linkedin.schema.NumberType': {}, 'com.linkedin.schema.StringType': {} } } },
    { ...valid, type: { type: { 'com.linkedin.schema.UnknownType': {} } } },
    { ...valid, type: { type: { toString: {} } } },
    { ...valid, type: { type: { 'com.linkedin.schema.NumberType': null } } },
    { ...valid, type: { type: { 'com.linkedin.schema.NumberType': {} }, extra: {} } },
    withoutNativeDataType,
    { ...valid, nativeDataType: '' },
    { ...valid, nativeDataType: 1 },
    { ...valid, nativeDataType: 'x'.repeat(501) },
    { ...valid, nullable: 'false' },
    { ...valid, globalTags: { tags: [{ tag: 1 }] } },
    { ...valid, glossaryTerms: { terms: [{ urn: 1 }] } },
  ]) assert.throws(() => normalizeMclRecord(record(invalid), { detectedAt }))
})

test('does not infer field or asset renames and emits only exact status.removed transitions', () => {
  const detectedAt = '2026-08-15T00:00:00.000Z'
  const aspect = (value) => ({ contentType: 'application/json', value: Buffer.from(JSON.stringify(value)) })
  const base = {
    entityUrn: 'urn:li:dataset:(urn:li:dataPlatform:postgres,db.schema.table,PROD)',
    aspectName: 'schemaMetadata', created: { actor: null, time: null },
  }
  const fieldRename = normalizeMclRecord({
    ...base,
    previousAspectValue: aspect({ fields: [{ fieldPath: 'old_name', nativeDataType: 'text', nullable: false, type: schemaFieldType('StringType') }] }),
    aspect: aspect({ fields: [{ fieldPath: 'new_name', nativeDataType: 'text', nullable: false, type: schemaFieldType('StringType') }] }),
  }, { detectedAt })
  assert.deepEqual(fieldRename.events.map((event) => [event.entityKey, event.operation]), [
    ['field:new_name', 'CREATE'], ['field:old_name', 'DELETE'],
  ])
  const status = (previous, current) => normalizeMclRecord({
    ...base, aspectName: 'status', previousAspectValue: previous == null ? null : aspect(previous), aspect: current == null ? null : aspect(current),
  }, { detectedAt })
  assert.deepEqual(status({ removed: false }, { removed: true }).events.map((event) => event.operation), ['DELETE'])
  assert.deepEqual(status({ removed: true }, { removed: false }).events.map((event) => event.operation), ['CREATE'])
  assert.deepEqual(status(null, { removed: false }).events, [], 'initial status is not inferred as asset CREATE')
  assert.deepEqual(status(null, { removed: true }).events, [], 'ambiguous initial tombstone is not synthesized')
  assert.throws(() => status({ removed: false }, { removed: 'true' }), /status.removed/)

  const entityLifecycle = (changeType) => normalizeMclRecord({
    entityUrn: base.entityUrn, entityType: 'dataset', changeType, aspectName: '', created: { actor: null, time: null },
  }, { detectedAt })
  assert.deepEqual(entityLifecycle('CREATE_ENTITY').events.map((event) => [event.storageCategory, event.sourceAspect, event.operation]), [
    ['LIFECYCLE', 'entity', 'CREATE'],
  ])
  assert.deepEqual(entityLifecycle('DELETE').events.map((event) => event.operation), ['DELETE'])
  assert.deepEqual(entityLifecycle('UPSERT').events, [], 'entity UPSERT is not inferred as CREATE')
  assert.throws(() => normalizeMclRecord({
    entityUrn: base.entityUrn, entityType: 'chart', changeType: 'CREATE', aspectName: '', created: { actor: null, time: null },
  }, { detectedAt }), /dataset entity lifecycle/)
})

test('contains no raw-payload or credential logging path', () => {
  const source = readFileSync(new URL('./poc-mcl-capture.mjs', import.meta.url), 'utf8')
  assert.doesNotMatch(source, /console\.(?:log|info|warn|error)/)
  assert.doesNotMatch(source, /JSON\.stringify\((?:record|decoded|config)\)/)
  assert.match(source, /logLevel\.NOTHING/)
})
