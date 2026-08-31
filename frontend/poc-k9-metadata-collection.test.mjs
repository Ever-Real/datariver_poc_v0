import assert from 'node:assert/strict'
import { mock, test } from 'node:test'

import {
  createK9MetadataCollector,
  normalizeDatahubTagReferences,
  validateK9ScopedAssignmentCompleteness,
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
    exists: true,
    status: { removed: false },
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

function fixture({
  pages = [page([])],
  directTerms = [],
  relationshipPages = [],
  dependencyOverrides = {},
} = {}) {
  const glossaryPages = [...pages]
  const remainingDirectTerms = [...directTerms]
  const remainingRelationshipPages = [...relationshipPages]
  const refreshGraphql = mock.fn(async (query, variables) => {
    if (query === 'GLOSSARY') return glossaryPages.shift()
    if (query === 'TERMS') {
      const requested = Array.isArray(variables?.urns) ? variables.urns : []
      const responses = remainingDirectTerms.splice(0, requested.length)
      if (responses.length !== requested.length) return {}
      return { entities: responses.map((response) => response?.entity) }
    }
    if (query === 'RELATIONSHIPS') return remainingRelationshipPages.shift()
    throw new Error('Unexpected query')
  })
  const collector = createK9MetadataCollector({
    refreshGraphql,
    glossaryQuery: 'GLOSSARY',
    glossaryTermsQuery: 'TERMS',
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
    raw: 2,
    projectable: 2,
    dangling: 0,
    unique_projected: 1,
    duplicates: 1,
    provider_incoming_total: 1,
  })
})

test('search snapshot omission resolves the exact Term and preserves its assignment', async () => {
  const unknownTermInventory = [dataset('unknown', {
    glossary_terms: [{ urn: termUrn, name: 'Shared', description: '' }],
  })]
  const result = await fixture({
    directTerms: [{ entity: glossaryTerm({ tableAssignments: { total: 1 } }) }],
  }).collector(authorityPin, unknownTermInventory)
  assert.equal(result.table_assignments.length, 1)
  assert.equal(result.table_assignments[0].term_urn, termUrn)
  assert.equal(result.terms.length, 1)
  const { raw_reference_hash: rawReferenceHash, dangling_reference_hash: danglingHash,
    ...assignmentProfile } = result.source_profile.assignments
  assert.match(rawReferenceHash, /^[0-9a-f]{64}$/)
  assert.equal(danglingHash, null)
  assert.deepEqual(assignmentProfile, {
    declared_table_assignment_total: 1,
    observed_table_assignment_total: 1,
    declared_column_assignment_total: 0,
    observed_column_assignment_total: 0,
    provider_incoming_table_total: 1,
    provider_incoming_column_total: 0,
    raw_table_refs: 1,
    raw_column_refs: 0,
    projectable_table_refs: 1,
    projectable_column_refs: 0,
    dangling_table_refs: 0,
    dangling_column_refs: 0,
    unique_projected_table_edges: 1,
    unique_projected_column_edges: 0,
    duplicate_table_refs: 0,
    duplicate_column_refs: 0,
    provider_scope_relation: 'EQUAL',
    term_outside_snapshot_count: 1,
    duplicate_assignment_observation_count: 0,
    missing_term_reference_count: 1,
    direct_term_resolution_attempt_count: 1,
    direct_term_resolution_recovered_count: 1,
    direct_term_resolution_dangling_count: 0,
    table_missing_term_count: 1,
    column_missing_term_count: 0,
    source_consistency_conflict_count: 0,
  })
})

test('direct Term hydration merges sparse and rich assignment observations deterministically', async () => {
  const direct = glossaryTerm({
    properties: { name: 'Shared', description: '' },
    tableAssignments: { total: 1 },
  })
  const sparse = { urn: termUrn, name: 'Shared', description: '' }
  const rich = { urn: termUrn, name: 'Shared', description: 'Richer optional metadata' }
  const collect = async (references) => fixture({ directTerms: [{ entity: direct }] }).collector(
    authorityPin,
    [dataset('direct-order', { glossary_terms: references })],
  )
  const forward = await collect([sparse, rich])
  const reverse = await collect([rich, sparse])
  assert.deepEqual(forward, reverse)
  assert.equal(forward.terms[0].description, 'Richer optional metadata')
  assert.equal(forward.table_assignments.length, 1)
  assert.equal(forward.source_profile.assignments.direct_term_resolution_attempt_count, 1)
})

test('absent, nonexistent, and removed direct Terms are accounted and excluded without ghost nodes', async () => {
  const urns = {
    absent: 'urn:li:glossaryTerm:a-absent',
    active: 'urn:li:glossaryTerm:b-active',
    nonexistent: 'urn:li:glossaryTerm:c-nonexistent',
    removed: 'urn:li:glossaryTerm:d-removed',
  }
  const inventory = [dataset('dangling-mixed', {
    glossary_terms: [
      { urn: urns.absent },
      { urn: urns.active },
      { urn: urns.active },
      { urn: urns.nonexistent },
      { urn: urns.nonexistent },
    ],
    schema_fields: [{
      fieldPath: 'field',
      glossaryTerms: { terms: [
        { term: { urn: urns.active } },
        { term: { urn: urns.removed } },
      ] },
    }],
  })]
  const result = await fixture({ directTerms: [
    { entity: null },
    { entity: glossaryTerm({
      urn: urns.active,
      tableAssignments: { total: 1 },
      columnAssignments: { total: 1 },
    }) },
    { entity: glossaryTerm({ urn: urns.nonexistent, exists: false }) },
    { entity: glossaryTerm({ urn: urns.removed, status: { removed: true } }) },
  ] }).collector(authorityPin, inventory)
  assert.deepEqual(result.terms.map((term) => term.urn), [urns.active])
  assert.equal(result.table_assignments.length, 1)
  assert.equal(result.column_assignments.length, 1)
  assert.equal(JSON.stringify(result).includes(urns.absent), false)
  assert.equal(JSON.stringify(result).includes(urns.nonexistent), false)
  assert.equal(JSON.stringify(result).includes(urns.removed), false)
  assert.deepEqual(result.source_profile.direct_resolution, {
    total: 4,
    total_unique_terms: 4,
    recovered_unique_terms: 1,
    dangling_unique_terms: 3,
    recovered_assignment_references: 3,
    dangling_assignment_references: 4,
    dangling_absent_count: 1,
    dangling_does_not_exist_count: 1,
    dangling_removed_count: 1,
    dangling_incompatible_type_count: 0,
    batch_size: 250,
    batch_total: 1,
    batch_number: 1,
    batch_requested_count: 4,
    batch_response_count: 4,
    batch_elapsed_ms: 0,
    completed_resolution_count: 4,
    retry_attempt: 0,
    provider_failure_class: null,
    graphql_error_class: null,
    graphql_error_path: null,
    failing_identity_hash: null,
    first_dangling_identity_hash: result.source_profile.direct_resolution.first_dangling_identity_hash,
  })
  assert.match(result.source_profile.direct_resolution.first_dangling_identity_hash, /^[0-9a-f]{64}$/)
  assert.match(result.source_profile.assignments.dangling_reference_hash, /^[0-9a-f]{64}$/)
  const rerun = await fixture({ directTerms: [
    { entity: null },
    { entity: glossaryTerm({
      urn: urns.active,
      tableAssignments: { total: 1 },
      columnAssignments: { total: 1 },
    }) },
    { entity: glossaryTerm({ urn: urns.nonexistent, exists: false }) },
    { entity: glossaryTerm({ urn: urns.removed, status: { removed: true } }) },
  ] }).collector(authorityPin, inventory)
  assert.deepEqual(rerun, result)
})

test('wrong direct entity type fails closed without exposing its identity', async () => {
  const inventory = [dataset('wrong-type', { glossary_terms: [{ urn: termUrn }] })]
  const failed = await failureRecord(fixture({ directTerms: [{ entity: {
    urn: termUrn,
    type: 'GLOSSARY_NODE',
  } }] }).collector, inventory)
  assert.equal(failed.detail, 'DANGLING_GLOSSARY_ASSIGNMENT')
  assert.equal(failed.profile.identity_resolution.failure.classification, 'CONTRADICTION')
  assert.equal(failed.profile.direct_resolution.dangling_incompatible_type_count, 1)
  assert.equal(failed.profile.direct_resolution.dangling_unique_terms, 1)
  assert.equal(failed.profile.direct_resolution.dangling_assignment_references, 1)
  assert.match(failed.profile.direct_resolution.first_dangling_identity_hash, /^[0-9a-f]{64}$/)
  assert.equal(JSON.stringify(failed.profile).includes(termUrn), false)
})

test('direct Term provider failures preserve every existing bounded provider family', async () => {
  for (const properties of [
    { providerFailureKind: 'TRANSPORT' },
    { name: 'TimeoutError' },
    { providerFailureKind: 'HTTP', providerHttpClass: '4xx' },
    { providerFailureKind: 'HTTP', providerHttpClass: '5xx' },
    { providerFailureKind: 'GRAPHQL' },
    { providerFailureKind: 'CONTRACT' },
  ]) {
    const providerError = Object.assign(new Error('private provider body'), properties)
    const collector = fixture({ dependencyOverrides: {
      refreshGraphql: async (query) => {
        if (query === 'GLOSSARY') return page([])
        throw providerError
      },
    } }).collector
    await assert.rejects(
      () => collector(authorityPin, [dataset('direct-provider', { glossary_terms: [{ urn: termUrn }] })]),
      (error) => {
        assert.equal(error, providerError)
        assert.equal(error.k9MetadataSourceProfile.direct_resolution.batch_number, 1)
        assert.equal(error.k9MetadataSourceProfile.direct_resolution.batch_requested_count, 1)
        assert.equal(error.k9MetadataSourceProfile.direct_resolution.failing_identity_hash.length, 64)
        assert.equal(JSON.stringify(error.k9MetadataSourceProfile).includes(termUrn), false)
        return true
      },
    )
  }
})

test('direct Term progress is derived from completed provider batches and contains no identities', async () => {
  const count = 501
  const references = Array.from({ length: count }, (_, index) => ({
    urn: `urn:li:glossaryTerm:progress-${String(index).padStart(4, '0')}`,
  }))
  const directTerms = references.map((reference) => ({ entity: glossaryTerm({
    urn: reference.urn,
    properties: { name: 'bounded', description: '' },
    tableAssignments: { total: 1 },
  }) }))
  const progress = []
  const { collector } = fixture({ directTerms })
  await collector(
    authorityPin,
    [dataset('progress', { glossary_terms: references })],
    { retryAttempt: 2, reportProgress: (value) => progress.push(value) },
  )
  assert.equal(progress.at(-1).total, count)
  assert.equal(progress.at(-1).batch_total, 3)
  assert.equal(progress.at(-1).batch_number, 3)
  assert.equal(progress.at(-1).completed_resolution_count, count)
  assert.equal(progress.at(-1).retry_attempt, 2)
  assert.equal(progress.some((value) => value.completed_resolution_count > count), false)
  assert.equal(JSON.stringify(progress).includes('urn:li:'), false)
})

test('direct Term response contract and resolution batches remain bounded', async () => {
  const malformed = fixture({ directTerms: [{}] }).collector
  await assert.rejects(
    () => malformed(authorityPin, [dataset('malformed-direct', { glossary_terms: [{ urn: termUrn }] })]),
    (error) => error?.providerFailureKind === 'CONTRACT',
  )

  for (const count of [999, 1_000, 1_001, 2_501]) {
    const references = Array.from({ length: count }, (_, index) => ({
      urn: `urn:li:glossaryTerm:bounded-${String(index).padStart(5, '0')}`,
    }))
    const directTerms = references.map((reference) => ({ entity: glossaryTerm({
      urn: reference.urn,
      properties: { name: reference.urn.split(':').at(-1), description: '' },
      tableAssignments: { total: 1 },
    }) }))
    const { collector, refreshGraphql } = fixture({ directTerms })
    const result = await collector(
      authorityPin,
      [dataset(`bounded-direct-${count}`, { glossary_terms: [...references].reverse() })],
    )
    assert.equal(result.terms.length, count)
    assert.equal(result.table_assignments.length, count)
    assert.equal(new Set(result.terms.map((term) => term.urn)).size, count)
    assert.deepEqual(result.terms.map((term) => term.urn), references.map((term) => term.urn))
    assert.equal(result.source_profile.assignments.missing_term_reference_count, count)
    assert.equal(result.source_profile.assignments.direct_term_resolution_attempt_count, count)
    assert.equal(result.source_profile.assignments.direct_term_resolution_recovered_count, count)
    const batches = refreshGraphql.mock.calls
      .filter((call) => call.arguments[0] === 'TERMS')
      .map((call) => call.arguments[1].urns)
    assert.equal(batches.length, Math.ceil(count / 250))
    assert.equal(batches.every((batch) => batch.length > 0 && batch.length <= 250), true)
    assert.deepEqual(batches.flat(), references.map((reference) => reference.urn))
  }
})

test('Actual-PREP-scale dangling references complete all batches with exact unique/reference accounting', async () => {
  const uniqueCount = 1_486
  const referenceCount = 75_431
  const urns = Array.from({ length: uniqueCount }, (_, index) => (
    `urn:li:glossaryTerm:prep-scale-${String(index).padStart(4, '0')}`
  ))
  const references = Array.from({ length: referenceCount }, (_, index) => ({
    urn: urns[index % uniqueCount],
  }))
  const directTerms = urns.map((urn) => ({ entity: glossaryTerm({ urn, exists: false }) }))
  const { collector, refreshGraphql } = fixture({ directTerms })
  const result = await collector(authorityPin, [dataset('prep-scale', { glossary_terms: references })])
  assert.equal(result.terms.length, 0)
  assert.equal(result.table_assignments.length, 0)
  assert.equal(result.source_profile.direct_resolution.total_unique_terms, uniqueCount)
  assert.equal(result.source_profile.direct_resolution.recovered_unique_terms, 0)
  assert.equal(result.source_profile.direct_resolution.dangling_unique_terms, uniqueCount)
  assert.equal(result.source_profile.direct_resolution.recovered_assignment_references, 0)
  assert.equal(result.source_profile.direct_resolution.dangling_assignment_references, referenceCount)
  assert.equal(result.source_profile.direct_resolution.dangling_does_not_exist_count, uniqueCount)
  assert.equal(result.source_profile.direct_resolution.completed_resolution_count, uniqueCount)
  assert.equal(result.source_profile.assignments.raw_table_refs, referenceCount)
  assert.equal(result.source_profile.assignments.projectable_table_refs, 0)
  assert.equal(result.source_profile.assignments.dangling_table_refs, referenceCount)
  assert.equal(result.source_profile.assignments.unique_projected_table_edges, 0)
  assert.equal(result.source_profile.assignments.duplicate_table_refs, 0)
  assert.equal(result.source_profile.assignments.provider_scope_relation, 'GLOBAL_SMALLER')
  assert.equal(refreshGraphql.mock.calls.filter((call) => call.arguments[0] === 'TERMS').length, 6)
  assert.equal(JSON.stringify(result.source_profile).includes('urn:li:'), false)
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

test('malformed provider totals fail while cross-scope totals remain advisory', async () => {
  const malformed = fixture({ pages: [page([{ entity: glossaryTerm({
    tableAssignments: { total: null },
  }) }])] }).collector
  assert.equal(await failureDetail(malformed), 'GLOSSARY_ASSIGNMENT_COUNT_MISMATCH')

  const globalGreater = await fixture({ pages: [page([{ entity: glossaryTerm({
    tableAssignments: { total: 7 },
  }) }])] }).collector(authorityPin, [dataset('provider-global', {
    glossary_terms: [{ urn: termUrn }],
  })])
  assert.equal(globalGreater.table_assignments.length, 1)
  assert.equal(globalGreater.source_profile.assignments.provider_incoming_table_total, 7)
  assert.equal(globalGreater.source_profile.assignments.raw_table_refs, 1)
  assert.equal(globalGreater.source_profile.assignments.provider_scope_relation, 'GLOBAL_GREATER')

  const globalSmaller = await fixture({ pages: [page([{ entity: glossaryTerm() }])] })
    .collector(authorityPin, [dataset('provider-smaller', {
      glossary_terms: [{ urn: termUrn }],
    })])
  assert.equal(globalSmaller.table_assignments.length, 1)
  assert.equal(globalSmaller.source_profile.assignments.provider_scope_relation, 'GLOBAL_SMALLER')
})

test('K9 assignment scope excludes unsupported and unauthorized inventory references', async () => {
  const result = await fixture({ pages: [page([{ entity: glossaryTerm({
    tableAssignments: { total: 3 },
  }) }])] }).collector(authorityPin, [
    dataset('eligible', { glossary_terms: [{ urn: termUrn }] }),
    dataset('unsupported', { dataset_kind: 'CHART', glossary_terms: [{ urn: termUrn }] }),
    dataset('unauthorized', { classification: null, glossary_terms: [{ urn: termUrn }] }),
  ])
  assert.equal(result.table_assignments.length, 1)
  assert.equal(result.source_profile.assignments.raw_table_refs, 1)
  assert.equal(result.source_profile.assignments.provider_incoming_table_total, 3)
  assert.equal(result.source_profile.assignments.provider_scope_relation, 'GLOBAL_GREATER')
})

test('column-only scoped assignment completeness uses the same raw universe', async () => {
  const result = await fixture({ pages: [page([{ entity: glossaryTerm({
    columnAssignments: { total: 1 },
  }) }])] }).collector(authorityPin, [dataset('column-only', {
    schema_fields: [{
      fieldPath: 'field',
      glossaryTerms: { terms: [{ term: { urn: termUrn } }] },
    }],
  })])
  assert.equal(result.column_assignments.length, 1)
  assert.equal(result.source_profile.assignments.raw_column_refs, 1)
  assert.equal(result.source_profile.assignments.projectable_column_refs, 1)
  assert.equal(result.source_profile.assignments.unique_projected_column_edges, 1)
  assert.equal(result.source_profile.assignments.provider_scope_relation, 'EQUAL')
})

test('same-scope assignment accounting contradiction remains fail closed with bounded diagnostics', () => {
  const profile = {
    contract: 'DATARIVER_K9_METADATA_SOURCE_PROFILE_V1',
    assignments: {
      raw_table_refs: 2,
      raw_column_refs: 0,
      projectable_table_refs: 1,
      projectable_column_refs: 0,
      dangling_table_refs: 0,
      dangling_column_refs: 0,
      unique_projected_table_edges: 1,
      unique_projected_column_edges: 0,
      duplicate_table_refs: 0,
      duplicate_column_refs: 0,
    },
  }
  assert.throws(
    () => validateK9ScopedAssignmentCompleteness(profile, { tableEdgeCount: 1, columnEdgeCount: 0 }),
    (error) => error?.k9SourceFailureDetailCode === 'GLOSSARY_ASSIGNMENT_COUNT_MISMATCH'
      && error?.k9MetadataSourceProfile?.assignments?.raw_table_refs === 2,
  )
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
      [termUrn]: {
        TABLE: {
          raw: 1, projectable: 1, dangling: 0, unique_projected: 1, duplicates: 0,
          provider_incoming_total: 1,
        },
        COLUMN: {
          raw: 1, projectable: 1, dangling: 0, unique_projected: 1, duplicates: 0,
          provider_incoming_total: 1,
        },
      },
    },
  })
  assert.deepEqual(result.table_assignments.map((item) => item.term_urn), [termUrn])
  assert.deepEqual(result.column_assignments.map((item) => item.term_urn), [termUrn])
})
