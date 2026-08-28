import assert from 'node:assert/strict'
import { mock, test } from 'node:test'

import {
  createK9MetadataCollector,
  normalizeDatahubTagReferences,
} from './poc-k9-metadata-collection.mjs'

const authorityPin = { classification_ceiling: 'INTERNAL' }
const tagUrn = 'urn:li:tag:shared'
const termUrn = 'urn:li:glossaryTerm:shared'
function tagReference({ urn = tagUrn, name, description = '', nameSource = 'LEGACY' }) {
  return { urn, name, description, _k9_name_source: nameSource }
}

function dataset(suffix, overrides = {}) {
  return {
    external_urn: `urn:li:dataset:(urn:li:dataPlatform:postgres,test.${suffix},PROD)`,
    dataset_kind: 'TABLE',
    classification: 'INTERNAL',
    name: suffix,
    tag_references: [],
    glossary_terms: [],
    schema_fields: [],
    ...overrides,
  }
}

function glossaryTerm(overrides = {}) {
  return {
    urn: termUrn,
    type: 'GLOSSARY_TERM',
    properties: { name: 'Shared', description: 'Shared term' },
    tableAssignments: { total: 0 },
    columnAssignments: { total: 0 },
    parentNodes: { nodes: [] },
    outgoingRelationships: { total: 0, relationships: [] },
    ...overrides,
  }
}

function glossaryNode(suffix, overrides = {}) {
  return {
    urn: `urn:li:glossaryNode:${suffix}`,
    type: 'GLOSSARY_NODE',
    properties: { name: suffix, description: '' },
    parentNodes: { nodes: [] },
    outgoingRelationships: { total: 0, relationships: [] },
    ...overrides,
  }
}

function page(searchResults, { total = searchResults.length, nextScrollId = null } = {}) {
  return { scrollAcrossEntities: { total, nextScrollId, searchResults } }
}

function fixture({ pages = [page([])], relationshipPages = [], dependencyOverrides = {} } = {}) {
  const glossaryPages = [...pages]
  const remainingRelationshipPages = [...relationshipPages]
  const refreshGraphql = mock.fn(async (query) => {
    if (query === 'GLOSSARY') return glossaryPages.shift()
    if (query === 'RELATIONSHIPS') return remainingRelationshipPages.shift()
    throw new Error('Unexpected query')
  })
  const collector = createK9MetadataCollector({
    refreshGraphql,
    glossaryQuery: 'GLOSSARY',
    relationshipsQuery: 'RELATIONSHIPS',
    buildScrollVariables: (scrollId) => ({ scrollId }),
    schemaFields: (item) => item.schema_fields,
    sourceClassification: (item) => item.classification,
    assetUrn: (item) => item.external_urn,
    metadataProperties: (item, field) => ({ name: field?.fieldPath || item.name }),
    customProperties: () => [],
    structuredProperties: () => [],
    tagNameSource: (reference) => reference?._k9_name_source,
    urnTail: (urn) => urn.split(':').at(-1),
    ...dependencyOverrides,
  })
  return { collector, refreshGraphql }
}

async function failureDetail(collector, inventory = [dataset('one')]) {
  return (await failureRecord(collector, inventory)).detail
}

async function failureRecord(collector, inventory = [dataset('one')], context) {
  try {
    await collector(authorityPin, inventory, context)
  } catch (error) {
    return {
      detail: error?.k9SourceFailureDetailCode,
      profile: error?.k9MetadataSourceProfile,
    }
  }
  assert.fail('Expected metadata collection to fail')
}

test('DataHub v1.6.0 tag provenance survives persistence and restart-style serialization', async () => {
  const seededTagUrn = 'urn:li:tag:datariver_classification_internal'
  const realDatahubTag = (properties) => normalizeDatahubTagReferences({ globalTags: { tags: [{ tag: {
    urn: seededTagUrn,
    name: 'datariver_classification_internal',
    properties,
  } }] } })
  const rich = realDatahubTag({
    name: 'CLASSIFICATION:INTERNAL',
    description: 'Canonical classification tag',
  })[0]
  const sparse = realDatahubTag(null)[0]
  const richRoot = dataset('rich-root', { tag_references: [rich] })
  const sparseField = dataset('sparse-field', { schema_fields: [{
    fieldPath: 'field', globalTags: { tags: [{ tag: {
      urn: seededTagUrn, name: 'datariver_classification_internal', properties: null,
    } }] },
  }] })
  const sparseRoot = dataset('sparse-root', { tag_references: [sparse] })
  const richField = dataset('rich-field', { schema_fields: [{
    fieldPath: 'field', globalTags: { tags: [{ tag: {
      urn: seededTagUrn,
      name: 'datariver_classification_internal',
      properties: { name: 'CLASSIFICATION:INTERNAL', description: 'Canonical classification tag' },
    } }] },
  }] })

  const persistedForward = JSON.parse(JSON.stringify([richRoot, sparseField]))
  const persistedReverse = globalThis.structuredClone([sparseRoot, richField])
  assert.equal(persistedForward[0].tag_references[0]._k9_name_source, 'PROPERTIES')
  assert.equal(persistedReverse[0].tag_references[0]._k9_name_source, 'LEGACY')
  const forward = await fixture().collector(authorityPin, persistedForward)
  const reverse = await fixture().collector(authorityPin, persistedReverse)

  assert.deepEqual(forward.tags, [{
    urn: seededTagUrn,
    name: 'CLASSIFICATION:INTERNAL',
    description: 'Canonical classification tag',
  }])
  assert.deepEqual(reverse.tags, forward.tags)
  assert.equal(JSON.stringify({ forward, reverse }).includes('name_source'), false)
  assert.equal(JSON.stringify({ forward, reverse }).includes('PROPERTIES'), false)
  assert.equal(JSON.stringify({ forward, reverse }).includes('LEGACY'), false)
})

test('identical non-empty tag observations are accepted', async () => {
  const reference = tagReference({ name: 'Shared', description: 'Same', nameSource: 'PROPERTIES' })
  const inventory = [dataset('identical', {
    tag_references: [reference],
    schema_fields: [{ fieldPath: 'field', globalTags: { tags: [{ tag: {
      urn: tagUrn, name: 'Shared', properties: { name: 'Shared', description: 'Same' },
    } }] } }],
  })]
  assert.deepEqual((await fixture().collector(authorityPin, inventory)).tags, [{
    urn: tagUrn,
    name: 'Shared',
    description: 'Same',
  }])
})

test('differing rich tag names or non-empty descriptions fail closed as TAG_IDENTITY_CONFLICT', async () => {
  for (const [first, conflicting] of [
    [
      tagReference({ name: 'Shared', description: 'Same', nameSource: 'PROPERTIES' }),
      tagReference({ name: 'Different', description: 'Same', nameSource: 'PROPERTIES' }),
    ],
    [
      tagReference({ name: 'Shared', description: 'Same', nameSource: 'PROPERTIES' }),
      tagReference({ name: 'Shared', description: 'Different', nameSource: 'PROPERTIES' }),
    ],
  ]) {
    const inventory = JSON.parse(JSON.stringify([dataset('conflict', {
      tag_references: [first, conflicting],
    })]))
    assert.equal(await failureDetail(fixture().collector, inventory), 'TAG_IDENTITY_CONFLICT')
  }
})

test('differing legacy names for one exact tag URN fail closed as TAG_IDENTITY_CONFLICT', async () => {
  const inventory = [dataset('legacy-conflict', { tag_references: [
    tagReference({ name: 'legacy-one', nameSource: 'LEGACY' }),
    tagReference({ name: 'legacy-two', nameSource: 'LEGACY' }),
  ] })]
  assert.equal(await failureDetail(fixture().collector, inventory), 'TAG_IDENTITY_CONFLICT')
})

test('declared malformed tag shape, name, or persisted provenance fails closed without truncation', async () => {
  for (const entity of [
    { globalTags: { tags: {} } },
    { globalTags: { tags: [{ tag: { urn: tagUrn, name: null, properties: null } }] } },
    { globalTags: { tags: [{ tag: { urn: tagUrn, name: 'legacy', properties: {} } }] } },
  ]) {
    assert.throws(
      () => normalizeDatahubTagReferences(entity),
      (error) => error?.k9SourceFailureDetailCode === 'METADATA_NORMALIZATION_FAILED',
    )
  }
  for (const reference of [
    tagReference({ name: undefined }),
    { urn: tagUrn, name: 'Shared', description: '', _k9_name_source: 'UNBOUNDED' },
    { urn: tagUrn, name: 'Shared', description: null, _k9_name_source: 'PROPERTIES' },
  ]) {
    assert.equal(await failureDetail(fixture().collector, [dataset('malformed-tag', {
      tag_references: [reference],
    })]), 'METADATA_NORMALIZATION_FAILED')
  }
  assert.equal(await failureDetail(fixture().collector, [dataset('malformed-column-tag', {
    schema_fields: [{
      fieldPath: 'field',
      globalTags: { tags: [{ tag: { urn: tagUrn, name: 'legacy', properties: {} } }] },
    }],
  })]), 'METADATA_NORMALIZATION_FAILED')
})

test('malformed glossary envelopes and total drift have bounded distinct details', async () => {
  assert.equal(await failureDetail(fixture({ pages: [{ scrollAcrossEntities: { total: '1', searchResults: [] } }] }).collector),
    'GLOSSARY_RESPONSE_MALFORMED')
  assert.equal(await failureDetail(fixture({ pages: [
    page([{ entity: glossaryNode('one') }], { total: 2, nextScrollId: 'next' }),
    page([{ entity: glossaryNode('two') }], { total: 3 }),
  ] }).collector), 'GLOSSARY_TOTAL_DRIFT')
})

test('missing, repeated, and nonterminal glossary cursors fail as GLOSSARY_CURSOR_STALLED', async () => {
  const scenarios = [
    [page([{ entity: glossaryNode('one') }], { total: 2 })],
    [
      page([{ entity: glossaryNode('one') }], { total: 3, nextScrollId: 'same' }),
      page([{ entity: glossaryNode('two') }], { total: 3, nextScrollId: 'same' }),
    ],
    [page([{ entity: glossaryNode('one') }], { total: 1, nextScrollId: 'unexpected' })],
  ]
  for (const pages of scenarios) {
    assert.equal(await failureDetail(fixture({ pages }).collector), 'GLOSSARY_CURSOR_STALLED')
  }
})

test('bounded glossary page ceiling fails as GLOSSARY_CURSOR_STALLED', async () => {
  let index = 0
  const refreshGraphql = async () => {
    const current = index++
    return page([{ entity: glossaryNode(String(current)) }], {
      total: 20_000,
      nextScrollId: `cursor-${current}`,
    })
  }
  const { collector } = fixture({ dependencyOverrides: { refreshGraphql } })
  assert.equal(await failureDetail(collector), 'GLOSSARY_CURSOR_STALLED')
  assert.equal(index, 10002)
})

test('relationship page malformed and early termination fail as GLOSSARY_RELATION_PAGE_INCOMPLETE', async () => {
  const firstRelationship = { type: 'RelatedTerms', entity: glossaryNode('target') }
  const term = glossaryTerm({ outgoingRelationships: { total: 2, relationships: [firstRelationship] } })
  for (const relationshipPage of [
    { entity: { urn: termUrn, type: 'GLOSSARY_TERM', relationships: {
      total: 2, start: 0, relationships: [firstRelationship],
    } } },
    { entity: { urn: termUrn, type: 'GLOSSARY_TERM', relationships: {
      total: 2, start: 1, relationships: [],
    } } },
  ]) {
    const { collector } = fixture({
      pages: [page([{ entity: term }])],
      relationshipPages: [relationshipPage],
    })
    assert.equal(await failureDetail(collector), 'GLOSSARY_RELATION_PAGE_INCOMPLETE')
  }
})

test('relationship count overshoot fails as GLOSSARY_RELATION_COUNT_MISMATCH', async () => {
  const relationship = { type: 'RelatedTerms', entity: glossaryNode('target') }
  const term = glossaryTerm({ outgoingRelationships: { total: 1, relationships: [relationship, relationship] } })
  assert.equal(await failureDetail(fixture({ pages: [page([{ entity: term }])] }).collector),
    'GLOSSARY_RELATION_COUNT_MISMATCH')
})

test('exact duplicate term, node, parent edge, and assignment observations dedupe idempotently', async () => {
  const duplicateTerm = await fixture({ pages: [page([
    { entity: glossaryTerm() }, { entity: glossaryTerm() },
  ])] }).collector(authorityPin, [dataset('term-dedupe')])
  assert.equal(duplicateTerm.terms.length, 1)
  assert.equal(duplicateTerm.source_profile.glossary_scroll.duplicate_term_observation_count, 1)
  assert.equal(duplicateTerm.source_profile.identity_resolution.exact_duplicate_observation_count, 1)

  const duplicateNode = await fixture({ pages: [page([
    { entity: glossaryNode('duplicate') }, { entity: glossaryNode('duplicate') },
  ])] }).collector(authorityPin, [dataset('node-dedupe')])
  assert.equal(duplicateNode.parent_nodes.length, 1)
  assert.equal(duplicateNode.source_profile.glossary_scroll.duplicate_node_observation_count, 1)

  const parent = { urn: 'urn:li:glossaryNode:parent' }
  const duplicateParent = await fixture({ pages: [page([{ entity: glossaryTerm({
    parentNodes: { nodes: [parent, parent] },
  }) }])] }).collector(authorityPin, [dataset('term-parent-dedupe')])
  assert.equal(duplicateParent.term_parent_edges.length, 1)
  assert.equal(duplicateParent.source_profile.identity_resolution.exact_duplicate_observation_count, 1)

  const duplicateNodeParent = await fixture({ pages: [page([{ entity: glossaryNode('child', {
    parentNodes: { nodes: [parent, parent] },
  }) }])] }).collector(authorityPin, [dataset('node-parent-dedupe')])
  assert.equal(duplicateNodeParent.node_parent_edges.length, 1)
  assert.equal(duplicateNodeParent.source_profile.identity_resolution.exact_duplicate_observation_count, 1)

  const duplicateAssignmentInventory = [dataset('duplicate-assignment', {
    glossary_terms: [{ urn: termUrn }, { urn: termUrn }],
  })]
  const duplicateAssignment = await fixture({ pages: [page([{ entity: glossaryTerm({
    tableAssignments: { total: 1 },
  }) }])] }).collector(authorityPin, duplicateAssignmentInventory)
  assert.equal(duplicateAssignment.table_assignments.length, 1)
  assert.equal(duplicateAssignment.source_profile.assignments.observed_table_assignment_total, 2)
  assert.equal(duplicateAssignment.source_profile.assignments.duplicate_assignment_observation_count, 1)
  assert.deepEqual(duplicateAssignment.completeness_metadata.per_assignment[termUrn].TABLE, {
    fetched: 1, total: 1,
  })
})

test('assignment to a Term outside the complete glossary snapshot remains a contradiction', async () => {
  const unknownTermInventory = [dataset('unknown', {
    glossary_terms: [{ urn: 'urn:li:glossaryTerm:unknown' }],
  })]
  const failed = await failureRecord(fixture().collector, unknownTermInventory)
  assert.equal(failed.detail, 'ASSIGNMENT_TERM_OUTSIDE_SNAPSHOT')
  assert.equal(failed.profile.identity_resolution.failure.classification, 'CONTRADICTION')
})

test('staged profiler reports only bounded counts after exact duplicate term dedupe', async () => {
  const privateTerm = glossaryTerm({
    properties: { name: 'private-business-term', description: 'private-business-description' },
    tableAssignments: { total: 1 },
    columnAssignments: { total: 1 },
  })
  const inventory = [dataset('profile', {
    tag_references: [
      tagReference({ urn: 'urn:li:tag:first', name: 'first' }),
      tagReference({ urn: 'urn:li:tag:second', name: 'second' }),
    ],
    glossary_terms: [{ urn: termUrn }],
    schema_fields: [{
      fieldPath: 'private-field',
      globalTags: { tags: [{ tag: { urn: 'urn:li:tag:column', name: 'column', properties: null } }] },
      glossaryTerms: { terms: [{ term: { urn: termUrn } }] },
    }],
  })]
  const result = await fixture({
    pages: [page([{ entity: privateTerm }, { entity: globalThis.structuredClone(privateTerm) }])],
  }).collector(
    authorityPin,
    inventory,
    { sourceGeneration: 'a'.repeat(64) },
  )
  const profile = result.source_profile
  assert.deepEqual(profile.inventory, {
    total_dataset_count: 1,
    table_count: 1,
    view_count: 0,
    materialized_view_count: 0,
    total_column_count: 1,
    table_tag_observation_count: 2,
    column_tag_observation_count: 1,
    table_glossary_term_observation_count: 1,
    column_glossary_term_observation_count: 1,
    non_empty: true,
  })
  assert.deepEqual(profile.glossary_scroll, {
    provider_reported_total: 2,
    pages_fetched: 1,
    entities_fetched: 2,
    unique_term_count: 1,
    unique_node_count: 0,
    duplicate_term_observation_count: 1,
    duplicate_node_observation_count: 0,
    cursor_progression_status: 'COMPLETE',
    completion_status: true,
  })
  assert.equal(profile.relationships.glossary_entities_inspected, 2)
  assert.equal(profile.identity_resolution.exact_duplicate_observation_count, 1)
  assert.equal(profile.identity_resolution.failure, null)
  const serialized = JSON.stringify(profile)
  for (const forbidden of [
    termUrn,
    'private-business-term',
    'private-business-description',
    'private-field',
    'urn:li:tag:first',
  ]) assert.equal(serialized.includes(forbidden), false)
})

test('profiler distinguishes compatible sparse-rich observations from structural contradiction', async () => {
  const sparse = glossaryTerm({ properties: { name: 'Shared', description: '' } })
  const rich = glossaryTerm({ properties: { name: 'Display Shared', description: 'Richer optional metadata' } })
  const compatible = await fixture({ pages: [page([
    { entity: sparse }, { entity: rich },
  ])] }).collector(authorityPin, [dataset('compatible')])
  assert.equal(compatible.terms.length, 1)
  assert.equal(compatible.terms[0].name, 'Display Shared')
  assert.equal(compatible.terms[0].description, 'Richer optional metadata')
  assert.equal(compatible.source_profile.identity_resolution.compatible_sparse_rich_observation_count, 1)
  assert.equal(compatible.source_profile.identity_resolution.failure, null)

  const contradictory = await failureRecord(fixture({ pages: [page([
    { entity: glossaryTerm() },
    { entity: glossaryNode('contradiction', { urn: termUrn }) },
  ])] }).collector)
  assert.equal(contradictory.detail, 'RELATION_IDENTITY_CONFLICT')
  assert.equal(contradictory.profile.identity_resolution.failure.classification, 'CONTRADICTION')
})

test('sparse-rich Term and Node merge is deterministic across observation order', async () => {
  const sparseTerm = glossaryTerm({ properties: { name: 'Term', description: '' } })
  const richTerm = glossaryTerm({ properties: { name: 'Display Term', description: 'Rich term description' } })
  const sparseNode = glossaryNode('node', { properties: { name: 'Node', description: '' } })
  const richNode = glossaryNode('node', { properties: { name: 'Display Node', description: 'Rich node description' } })
  const collect = async (entities) => fixture({
    pages: [page(entities.map((entity) => ({ entity })))],
  }).collector(authorityPin, [dataset('order')], { sourceGeneration: 'd'.repeat(64) })

  const forward = await collect([sparseTerm, richTerm, sparseNode, richNode])
  const reverse = await collect([richNode, sparseNode, richTerm, sparseTerm])

  assert.deepEqual(forward, reverse)
  assert.deepEqual(forward.terms.map(({ name, description }) => ({ name, description })), [{
    name: 'Display Term', description: 'Rich term description',
  }])
  assert.deepEqual(forward.parent_nodes.map(({ name, description }) => ({ name, description })), [{
    name: 'Display Node', description: 'Rich node description',
  }])
  assert.equal(forward.source_profile.identity_resolution.compatible_sparse_rich_observation_count, 2)
})

test('same Term URN with mutually exclusive Domain identity remains fail closed', async () => {
  const withDomain = (suffix) => glossaryTerm({
    domain: { domain: {
      urn: `urn:li:domain:${suffix}`,
      properties: { name: suffix, description: '' },
    } },
  })
  const failed = await failureRecord(fixture({ pages: [page([
    { entity: withDomain('one') }, { entity: withDomain('two') },
  ])] }).collector)
  assert.equal(failed.detail, 'DUPLICATE_TERM_IDENTITY')
  assert.equal(failed.profile.identity_resolution.failure.classification, 'CONTRADICTION')
})

test('exact duplicate relationship identity dedupes with complete provider accounting', async () => {
  const relationship = { type: 'RelatedTerms', entity: glossaryNode('target') }
  const collected = await fixture({ pages: [page([{ entity: glossaryTerm({
    outgoingRelationships: { total: 2, relationships: [relationship, globalThis.structuredClone(relationship)] },
  }) }])] }).collector(authorityPin, [dataset('relationship-dedupe')])
  assert.equal(collected.glossary_relationships.length, 1)
  assert.equal(collected.source_profile.relationships.provider_relationship_total, 2)
  assert.equal(collected.source_profile.relationships.relationships_fetched, 2)
  assert.equal(collected.source_profile.relationships.duplicate_relationship_observations, 1)
  assert.equal(collected.source_profile.identity_resolution.exact_duplicate_observation_count, 1)
})

test('relationship response identity mismatch has an exact contradiction locus', async () => {
  const firstRelationship = { type: 'RelatedTerms', entity: glossaryNode('target') }
  const term = glossaryTerm({ outgoingRelationships: { total: 2, relationships: [firstRelationship] } })
  const failed = await failureRecord(fixture({
    pages: [page([{ entity: term }])],
    relationshipPages: [{ entity: {
      urn: 'urn:li:glossaryTerm:other',
      type: 'GLOSSARY_TERM',
      relationships: { total: 2, start: 1, relationships: [firstRelationship] },
    } }],
  }).collector)
  assert.equal(failed.detail, 'RELATION_ENTITY_IDENTITY_MISMATCH')
  assert.equal(failed.profile.relationships.response_entity_identity_mismatch_count, 1)
  assert.equal(failed.profile.identity_resolution.failure.classification, 'CONTRADICTION')
})

test('malformed and mismatched assignment totals fail as GLOSSARY_ASSIGNMENT_COUNT_MISMATCH', async () => {
  const malformed = fixture({ pages: [page([{ entity: glossaryTerm({
    tableAssignments: { total: null },
  }) }])] }).collector
  assert.equal(await failureDetail(malformed), 'GLOSSARY_ASSIGNMENT_COUNT_MISMATCH')

  const mismatched = fixture({ pages: [page([{ entity: glossaryTerm({
    tableAssignments: { total: 1 },
  }) }])] }).collector
  assert.equal(await failureDetail(mismatched), 'GLOSSARY_ASSIGNMENT_COUNT_MISMATCH')
})

test('unexpected local normalization failure is bounded while provider classification is preserved', async () => {
  const normalization = fixture({ dependencyOverrides: {
    sourceClassification: () => { throw new Error('raw local detail') },
  } }).collector
  assert.equal(await failureDetail(normalization), 'METADATA_NORMALIZATION_FAILED')

  const providerError = Object.assign(new Error('raw provider body'), { providerFailureKind: 'GRAPHQL' })
  const provider = fixture({ dependencyOverrides: {
    refreshGraphql: async () => { throw providerError },
  } }).collector
  await assert.rejects(() => provider(authorityPin, [dataset('provider')]), (error) => error === providerError)
})

test('successful collection preserves exact assignments and completeness', async () => {
  const inventory = [dataset('success', {
    glossary_terms: [{ urn: termUrn }],
    schema_fields: [{
      fieldPath: 'column',
      glossaryTerms: { terms: [{ term: { urn: termUrn } }] },
      globalTags: { tags: [] },
    }],
  })]
  const { collector } = fixture({ pages: [page([{ entity: glossaryTerm({
    tableAssignments: { total: 1 }, columnAssignments: { total: 1 },
  }) }])] })
  const result = await collector(authorityPin, inventory)
  assert.deepEqual(result.completeness_metadata, {
    fetched: 1,
    total: 1,
    per_assignment: {
      [termUrn]: { TABLE: { fetched: 1, total: 1 }, COLUMN: { fetched: 1, total: 1 } },
    },
  })
  assert.deepEqual(result.table_assignments.map((item) => item.term_urn), [termUrn])
  assert.deepEqual(result.column_assignments.map((item) => item.term_urn), [termUrn])
})
