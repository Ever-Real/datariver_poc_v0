/* global Response, URL */
import assert from 'node:assert/strict'
import test from 'node:test'

import { discoverPocMclSource } from './poc-mcl-discovery.mjs'

function kafka(topics = ['MetadataChangeLog_Versioned_v1']) {
  const state = { connected: 0, disconnected: 0 }
  return {
    state,
    admin() {
      return {
        async connect() { state.connected += 1 },
        async disconnect() { state.disconnected += 1 },
        async describeCluster() { return { clusterId: 'generic-datahub-cluster' } },
        async listTopics() { return topics },
      }
    },
  }
}

function transport({ internal = true } = {}) {
  const requests = []
  return {
    requests,
    async fetch(url, options = {}) {
      requests.push({ url, authorization: options.headers?.Authorization || null })
      const path = new URL(url).pathname
      if (path === '/config') return Response.json({ versions: { 'acryldata/datahub': { version: '1.2.3' } } })
      if (path === '/schema-registry/api/subjects') {
        return internal
          ? Response.json(['MetadataChangeLog_Versioned_v1-value'])
          : Response.json({}, { status: 404 })
      }
      if (path.endsWith('/subjects/MetadataChangeLog_Versioned_v1-value/versions/latest')) {
        return Response.json({ id: 17, version: 4, schemaType: 'AVRO', schema: '{"type":"record","name":"MCL","fields":[]}' })
      }
      if (path === '/registry/subjects') return Response.json(['MetadataChangeLog_Versioned_v1-value'])
      return Response.json({}, { status: 404 })
    },
  }
}

const environment = {
  DATAHUB_GMS_URL: 'https://datahub.example.test',
  DATAHUB_GMS_TOKEN: 'datahub-secret',
  POC_MCL_KAFKA_BROKERS: 'kafka.internal:9092',
  POC_MCL_KAFKA_SSL: 'true',
}

test('discovers cluster, exact versioned MCL topic, internal Registry schema and source identity', async () => {
  const provider = transport()
  const result = await discoverPocMclSource({
    environment, providerTransport: provider, kafka: kafka(), clock: () => new Date('2026-08-27T00:00:00Z'),
  })
  assert.equal(result.captureConfig.topic, 'MetadataChangeLog_Versioned_v1')
  assert.equal(result.captureConfig.providerVersion, '1.2.3')
  assert.match(result.captureConfig.sourceIdentityHash, /^[a-f0-9]{64}$/)
  assert.equal(result.receipt.registry_kind, 'DATAHUB_GMS_INTERNAL')
  assert.match(result.receipt.kafka_cluster_id_hash, /^[a-f0-9]{64}$/)
  assert.equal(JSON.stringify(result.receipt).includes('datahub-secret'), false)
  assert.equal(provider.requests.some((item) => item.authorization === 'Bearer datahub-secret'), true)
})

test('rejects missing or ambiguous supported versioned MCL topics', async () => {
  await assert.rejects(
    discoverPocMclSource({ environment, providerTransport: transport(), kafka: kafka([]) }),
    { code: 'PREP_MCL_DISCOVERY_TOPIC_NOT_FOUND_FAILED' },
  )
  await assert.rejects(
    discoverPocMclSource({
      environment, providerTransport: transport(),
      kafka: kafka(['MetadataChangeLog_Versioned_v1', 'team.MetadataChangeLog_Versioned_v1']),
    }),
    { code: 'PREP_MCL_DISCOVERY_TOPIC_AMBIGUOUS_FAILED' },
  )
})

test('uses explicitly configured external Registry only when GMS internal discovery is unavailable', async () => {
  const provider = transport({ internal: false })
  const result = await discoverPocMclSource({
    environment: {
      ...environment,
      POC_MCL_SCHEMA_REGISTRY_URL: 'https://registry.example.test/registry',
      POC_MCL_SCHEMA_REGISTRY_USERNAME: 'registry-user',
      POC_MCL_SCHEMA_REGISTRY_PASSWORD: 'registry-secret',
    },
    providerTransport: provider,
    kafka: kafka(),
  })
  assert.equal(result.receipt.registry_kind, 'EXTERNAL_CONFLUENT')
  assert.deepEqual(result.captureConfig.schemaRegistry.auth, {
    username: 'registry-user', password: 'registry-secret',
  })
  assert.equal(JSON.stringify(result.receipt).includes('registry-secret'), false)
})
