export const K9_METADATA_FAILURE_DETAILS = Object.freeze([
  'TAG_IDENTITY_CONFLICT',
  'GLOSSARY_RESPONSE_MALFORMED',
  'GLOSSARY_TOTAL_DRIFT',
  'GLOSSARY_CURSOR_STALLED',
  'GLOSSARY_RELATION_PAGE_INCOMPLETE',
  'GLOSSARY_RELATION_COUNT_MISMATCH',
  'METADATA_IDENTITY_CONFLICT',
  'GLOSSARY_ASSIGNMENT_COUNT_MISMATCH',
  'METADATA_NORMALIZATION_FAILED',
])

const supportedMetadataFailureDetails = new Set(K9_METADATA_FAILURE_DETAILS)
const supportedTagNameSources = new Set(['LEGACY', 'PROPERTIES'])

function metadataFailure(detailCode, cause) {
  if (!supportedMetadataFailureDetails.has(detailCode)) {
    throw new Error('The K9 metadata failure detail is invalid.')
  }
  return Object.assign(
    new Error('The bounded K9 metadata collection invariant failed.', cause ? { cause } : undefined),
    { k9SourceFailureDetailCode: detailCode },
  )
}

function providerFailure(error) {
  return error?.providerFailureKind
    || error?.providerHttpClass
    || Number.isInteger(error?.statusCode)
    || ['TimeoutError', 'AbortError'].includes(error?.name)
    || String(error?.code || '').includes('GRAPHQL')
    || String(error?.code || '').includes('CONTRACT')
}

function nonNegativeSafeInteger(value) {
  return Number.isSafeInteger(value) && value >= 0
}

function boundedTagNameSource(value) {
  if (value === null || value === undefined) return 'LEGACY'
  if (supportedTagNameSources.has(value)) return value
  throw metadataFailure('METADATA_NORMALIZATION_FAILED')
}

function canonicalTagObservation(reference, nameSource) {
  if (typeof reference?.urn !== 'string' || !reference.urn
    || typeof reference?.name !== 'string' || !reference.name) {
    throw metadataFailure('METADATA_NORMALIZATION_FAILED')
  }
  if (typeof reference.description !== 'string') {
    throw metadataFailure('METADATA_NORMALIZATION_FAILED')
  }
  return {
    urn: reference.urn,
    name: reference.name,
    name_source: boundedTagNameSource(nameSource),
    description: reference.description || '',
  }
}

export function normalizeDatahubTagReferences(entity) {
  const declaredReferences = entity?.globalTags?.tags
  if (declaredReferences === null || declaredReferences === undefined) return []
  if (!Array.isArray(declaredReferences)) throw metadataFailure('METADATA_NORMALIZATION_FAILED')
  return declaredReferences.map((item) => {
    const tag = item?.tag
    const properties = tag?.properties
    const hasProperties = properties !== null && properties !== undefined
    if (hasProperties && (typeof properties !== 'object' || Array.isArray(properties))) {
      throw metadataFailure('METADATA_NORMALIZATION_FAILED')
    }
    const propertiesName = properties?.name
    if (hasProperties && (typeof propertiesName !== 'string' || !propertiesName)) {
      throw metadataFailure('METADATA_NORMALIZATION_FAILED')
    }
    const name = propertiesName || tag?.name
    if (typeof tag?.urn !== 'string' || !tag.urn || typeof name !== 'string' || !name) {
      throw metadataFailure('METADATA_NORMALIZATION_FAILED')
    }
    const description = properties?.description
    if (description !== null && description !== undefined && typeof description !== 'string') {
      throw metadataFailure('METADATA_NORMALIZATION_FAILED')
    }
    return {
      urn: tag.urn,
      name,
      description: description || '',
      _k9_name_source: propertiesName ? 'PROPERTIES' : 'LEGACY',
    }
  })
}

function mergeCanonicalTagObservation(existing, reference, nameSource) {
  const incoming = canonicalTagObservation(reference, nameSource)
  if (!incoming) return existing || null
  if (!existing) return incoming
  if (existing.urn !== incoming.urn
    || (existing.name !== incoming.name && existing.name_source === incoming.name_source)
    || (existing.description && incoming.description && existing.description !== incoming.description)) {
    throw metadataFailure('TAG_IDENTITY_CONFLICT')
  }
  const preferredName = existing.name_source === 'PROPERTIES'
    ? existing
    : incoming.name_source === 'PROPERTIES' ? incoming : existing
  return {
    urn: existing.urn,
    name: preferredName.name,
    name_source: preferredName.name_source,
    description: existing.description || incoming.description,
  }
}

function publicTag(value) {
  return { urn: value.urn, name: value.name, description: value.description }
}

function requiredFunction(value, label) {
  if (typeof value !== 'function') throw new Error(`The ${label} dependency is unavailable.`)
  return value
}

export function createK9MetadataCollector({
  refreshGraphql,
  glossaryQuery,
  relationshipsQuery,
  buildScrollVariables,
  schemaFields,
  sourceClassification,
  assetUrn,
  metadataProperties,
  customProperties,
  structuredProperties,
  tagNameSource,
  urnTail,
  signal,
} = {}) {
  const fetchGraphql = requiredFunction(refreshGraphql, 'GraphQL refresh')
  const scrollVariables = requiredFunction(buildScrollVariables, 'glossary scroll')
  const fieldsFor = requiredFunction(schemaFields, 'schema field')
  const classificationFor = requiredFunction(sourceClassification, 'source classification')
  const urnFor = requiredFunction(assetUrn, 'asset URN')
  const propertiesFor = requiredFunction(metadataProperties, 'metadata properties')
  const customPropertiesFor = requiredFunction(customProperties, 'custom properties')
  const structuredPropertiesFor = requiredFunction(structuredProperties, 'structured properties')
  const tagNameSourceFor = requiredFunction(tagNameSource, 'tag name source')
  const tailFor = requiredFunction(urnTail, 'URN tail')

  async function collect(authorityPin, inventory) {
    if (!Array.isArray(inventory) || inventory.length === 0) {
      throw metadataFailure('METADATA_NORMALIZATION_FAILED')
    }
    const table_nodes = []
    const column_nodes = []
    const table_column_edges = []
    const tags = new Map()
    const domains = new Map()
    const containers = new Map()
    const platform_instances = new Map()
    const table_tag_assignments = []
    const column_tag_assignments = []
    const table_domain_assignments = []
    const table_container_assignments = []
    const table_platform_instance_assignments = []
    const metadataAssignmentSet = new Set()

    const registerMetadataAssignment = (collection, sourceId, targetId) => {
      const key = `${sourceId}->${targetId}`
      if (metadataAssignmentSet.has(key)) return
      metadataAssignmentSet.add(key)
      collection.push({ source_id: sourceId, target_id: targetId })
    }

    const registerTag = (reference, explicitNameSource) => {
      const nameSource = boundedTagNameSource(explicitNameSource || tagNameSourceFor(reference))
      const value = canonicalTagObservation(reference, nameSource)
      tags.set(value.urn, mergeCanonicalTagObservation(tags.get(value.urn), value, nameSource))
      return value.urn
    }

    for (const item of inventory) {
      const classification = classificationFor(item, authorityPin.classification_ceiling)
      if (!classification || !['TABLE', 'VIEW', 'MATERIALIZED_VIEW'].includes(item.dataset_kind)) continue
      const canonicalAssetUrn = urnFor(item)
      const tableId = `TABLE:${canonicalAssetUrn}`
      table_nodes.push({ id: tableId, classification, properties: propertiesFor(item) })
      for (const reference of item.tag_references || []) {
        const tagId = registerTag(reference)
        if (tagId) registerMetadataAssignment(table_tag_assignments, tableId, tagId)
      }
      if (item.domain_reference?.urn) {
        domains.set(item.domain_reference.urn, item.domain_reference)
        registerMetadataAssignment(table_domain_assignments, tableId, item.domain_reference.urn)
      }
      if (item.container_reference?.urn) {
        containers.set(item.container_reference.urn, item.container_reference)
        registerMetadataAssignment(table_container_assignments, tableId, item.container_reference.urn)
      }
      if (item.platform_instance_reference?.urn) {
        platform_instances.set(item.platform_instance_reference.urn, item.platform_instance_reference)
        registerMetadataAssignment(table_platform_instance_assignments, tableId, item.platform_instance_reference.urn)
      }
      for (const field of fieldsFor(item)) {
        const columnId = `COLUMN:${canonicalAssetUrn}:${field.fieldPath}`
        column_nodes.push({ id: columnId, classification, properties: propertiesFor(item, field) })
        table_column_edges.push({ table_id: tableId, column_id: columnId })
        for (const reference of normalizeDatahubTagReferences(field)) {
          const tagId = registerTag(reference)
          if (tagId) registerMetadataAssignment(column_tag_assignments, columnId, tagId)
        }
      }
    }

    let nextScrollId = null
    const seenScrollIds = new Set()
    let fetchedTerms = 0
    let pages = 0
    const terms = []
    const parent_nodes = []
    const term_parent_edges = []
    const node_parent_edges = []
    const glossary_relationships = []
    const table_assignments = []
    const column_assignments = []
    const termSet = new Set()
    const nodeSet = new Set()
    const assignmentSet = new Set()
    const termParentEdgeSet = new Set()
    const nodeParentEdgeSet = new Set()
    const glossaryRelationshipSet = new Set()
    const assignmentTotals = new Map()
    const completeness_metadata = { fetched: 0, total: 0, per_assignment: {} }
    let lastTotal = -1

    const explicitOutgoingRelationships = async (entity) => {
      const first = entity.outgoingRelationships
      const total = first === null || first === undefined ? 0 : first.total
      if (!nonNegativeSafeInteger(total) || (first && !Array.isArray(first.relationships))) {
        throw metadataFailure('GLOSSARY_RELATION_PAGE_INCOMPLETE')
      }
      const relationships = [...(first?.relationships || [])]
      if (relationships.length > total) throw metadataFailure('GLOSSARY_RELATION_COUNT_MISMATCH')
      let start = relationships.length
      while (start < total) {
        const data = await fetchGraphql(relationshipsQuery, {
          urn: entity.urn,
          input: { types: [], direction: 'OUTGOING', start, count: 100, includeSoftDelete: false },
        }, signal)
        if (data?.entity?.urn !== entity.urn || data.entity.type !== entity.type) {
          throw metadataFailure('METADATA_IDENTITY_CONFLICT')
        }
        const page = data.entity.relationships
        if (!page || !nonNegativeSafeInteger(page.total) || !nonNegativeSafeInteger(page.start)
          || page.total !== total || page.start !== start || !Array.isArray(page.relationships)) {
          throw metadataFailure('GLOSSARY_RELATION_PAGE_INCOMPLETE')
        }
        const items = page.relationships
        if (items.length === 0) throw metadataFailure('GLOSSARY_RELATION_PAGE_INCOMPLETE')
        if (relationships.length + items.length > total) {
          throw metadataFailure('GLOSSARY_RELATION_COUNT_MISMATCH')
        }
        relationships.push(...items)
        start += items.length
      }
      if (relationships.length !== total) throw metadataFailure('GLOSSARY_RELATION_COUNT_MISMATCH')
      return relationships
    }

    while (true) {
      if (pages >= 10002) throw metadataFailure('GLOSSARY_CURSOR_STALLED')
      const data = await fetchGraphql(glossaryQuery, scrollVariables(nextScrollId), signal)
      pages += 1
      const scroll = data?.scrollAcrossEntities
      if (!scroll || typeof scroll !== 'object' || !nonNegativeSafeInteger(scroll.total)
        || !Array.isArray(scroll.searchResults)) {
        throw metadataFailure('GLOSSARY_RESPONSE_MALFORMED')
      }
      const rawNextScrollId = scroll.nextScrollId
      if (rawNextScrollId !== null && rawNextScrollId !== undefined
        && (typeof rawNextScrollId !== 'string' || !rawNextScrollId)) {
        throw metadataFailure('GLOSSARY_RESPONSE_MALFORMED')
      }
      if (lastTotal !== -1 && scroll.total !== lastTotal) throw metadataFailure('GLOSSARY_TOTAL_DRIFT')
      lastTotal = scroll.total
      const results = scroll.searchResults
      if (results.length === 0) {
        if (fetchedTerms < scroll.total || rawNextScrollId) throw metadataFailure('GLOSSARY_CURSOR_STALLED')
        break
      }
      for (const result of results) {
        const entity = result?.entity
        if (!entity || typeof entity !== 'object' || typeof entity.urn !== 'string'
          || !['GLOSSARY_TERM', 'GLOSSARY_NODE'].includes(entity.type)) {
          throw metadataFailure('GLOSSARY_RESPONSE_MALFORMED')
        }
        if (entity.type === 'GLOSSARY_TERM') {
          if (termSet.has(entity.urn)) throw metadataFailure('METADATA_IDENTITY_CONFLICT')
          termSet.add(entity.urn)
          const termInfo = entity.glossaryTermInfo || entity.properties || {}
          terms.push({
            urn: entity.urn,
            name: termInfo.name || entity.properties?.name || '',
            description: termInfo.description || entity.properties?.description || '',
            term_source: termInfo.termSource || entity.properties?.termSource || null,
            source_ref: termInfo.sourceRef || entity.properties?.sourceRef || null,
            source_url: termInfo.sourceUrl || entity.properties?.sourceUrl || null,
            custom_properties: customPropertiesFor(termInfo),
            structured_properties: structuredPropertiesFor(entity.structuredProperties),
            domain_reference: entity.domain?.domain?.urn ? {
              urn: entity.domain.domain.urn,
              name: entity.domain.domain.properties?.name || tailFor(entity.domain.domain.urn),
              description: entity.domain.domain.properties?.description || '',
            } : null,
          })
          const tableTotal = entity.tableAssignments?.total
          const columnTotal = entity.columnAssignments?.total
          if (!nonNegativeSafeInteger(tableTotal) || !nonNegativeSafeInteger(columnTotal)) {
            throw metadataFailure('GLOSSARY_ASSIGNMENT_COUNT_MISMATCH')
          }
          assignmentTotals.set(entity.urn, { TABLE: tableTotal, COLUMN: columnTotal })
          for (const parentNode of entity.parentNodes?.nodes || []) {
            const edgeKey = `${entity.urn}->${parentNode.urn}`
            if (termParentEdgeSet.has(edgeKey)) throw metadataFailure('METADATA_IDENTITY_CONFLICT')
            termParentEdgeSet.add(edgeKey)
            term_parent_edges.push({ term_urn: entity.urn, parent_urn: parentNode.urn })
          }
          for (const relationship of await explicitOutgoingRelationships(entity)) {
            if (!['GLOSSARY_TERM', 'GLOSSARY_NODE'].includes(relationship.entity?.type)
              || typeof relationship.entity?.urn !== 'string') continue
            const relationKey = `${entity.urn}->${relationship.entity.urn}->${relationship.type}`
            if (glossaryRelationshipSet.has(relationKey)) continue
            glossaryRelationshipSet.add(relationKey)
            glossary_relationships.push({
              source_urn: entity.urn,
              target_urn: relationship.entity.urn,
              source_type: entity.type,
              target_type: relationship.entity.type,
              relationship_type: relationship.type,
            })
          }
        } else {
          if (nodeSet.has(entity.urn)) throw metadataFailure('METADATA_IDENTITY_CONFLICT')
          nodeSet.add(entity.urn)
          parent_nodes.push({
            urn: entity.urn,
            name: entity.properties?.name || '',
            description: entity.properties?.description || '',
            custom_properties: customPropertiesFor(entity.properties),
            structured_properties: structuredPropertiesFor(entity.structuredProperties),
          })
          for (const parentNode of entity.parentNodes?.nodes || []) {
            const edgeKey = `${entity.urn}->${parentNode.urn}`
            if (nodeParentEdgeSet.has(edgeKey)) throw metadataFailure('METADATA_IDENTITY_CONFLICT')
            nodeParentEdgeSet.add(edgeKey)
            node_parent_edges.push({ child_urn: entity.urn, parent_urn: parentNode.urn })
          }
          for (const relationship of await explicitOutgoingRelationships(entity)) {
            if (!['GLOSSARY_TERM', 'GLOSSARY_NODE'].includes(relationship.entity?.type)
              || typeof relationship.entity?.urn !== 'string') continue
            const relationKey = `${entity.urn}->${relationship.entity.urn}->${relationship.type}`
            if (glossaryRelationshipSet.has(relationKey)) continue
            glossaryRelationshipSet.add(relationKey)
            glossary_relationships.push({
              source_urn: entity.urn,
              target_urn: relationship.entity.urn,
              source_type: entity.type,
              target_type: relationship.entity.type,
              relationship_type: relationship.type,
            })
          }
        }
      }
      fetchedTerms += results.length
      nextScrollId = rawNextScrollId || null
      if (!nextScrollId && fetchedTerms < scroll.total) throw metadataFailure('GLOSSARY_CURSOR_STALLED')
      if (nextScrollId) {
        if (seenScrollIds.has(nextScrollId)) throw metadataFailure('GLOSSARY_CURSOR_STALLED')
        seenScrollIds.add(nextScrollId)
      }
      if (fetchedTerms >= scroll.total) {
        if (fetchedTerms !== scroll.total || nextScrollId) throw metadataFailure('GLOSSARY_CURSOR_STALLED')
        break
      }
    }
    completeness_metadata.fetched = fetchedTerms
    completeness_metadata.total = lastTotal === -1 ? 0 : lastTotal
    if (fetchedTerms !== completeness_metadata.total) throw metadataFailure('GLOSSARY_CURSOR_STALLED')

    const observedAssignmentTotals = new Map([...termSet].map((urn) => [urn, { TABLE: 0, COLUMN: 0 }]))
    const registerAssignment = (type, termUrn, item, field, classification) => {
      if (!termSet.has(termUrn)) throw metadataFailure('METADATA_IDENTITY_CONFLICT')
      observedAssignmentTotals.get(termUrn)[type] += 1
      if (!classification || !['TABLE', 'VIEW', 'MATERIALIZED_VIEW'].includes(item.dataset_kind)) return
      const assignId = type === 'TABLE'
        ? `TABLE:${urnFor(item)}`
        : `COLUMN:${urnFor(item)}:${field.fieldPath}`
      const assignKey = `${assignId}->${termUrn}`
      if (assignmentSet.has(assignKey)) throw metadataFailure('METADATA_IDENTITY_CONFLICT')
      assignmentSet.add(assignKey)
      const assignment = {
        id: assignId,
        term_urn: termUrn,
        classification,
        properties: propertiesFor(item, field),
      }
      if (type === 'TABLE') table_assignments.push(assignment)
      else column_assignments.push(assignment)
    }

    for (const item of inventory) {
      const classification = classificationFor(item, authorityPin.classification_ceiling)
      for (const term of item.glossary_terms || []) {
        if (term?.urn) registerAssignment('TABLE', term.urn, item, null, classification)
      }
      for (const field of fieldsFor(item)) {
        for (const reference of field.glossaryTerms?.terms || []) {
          if (reference.term?.urn) registerAssignment('COLUMN', reference.term.urn, item, field, classification)
        }
      }
    }

    for (const termUrn of termSet) {
      const expected = assignmentTotals.get(termUrn)
      const observed = observedAssignmentTotals.get(termUrn)
      completeness_metadata.per_assignment[termUrn] = {
        TABLE: { fetched: observed.TABLE, total: expected.TABLE },
        COLUMN: { fetched: observed.COLUMN, total: expected.COLUMN },
      }
      if (observed.TABLE !== expected.TABLE || observed.COLUMN !== expected.COLUMN) {
        throw metadataFailure('GLOSSARY_ASSIGNMENT_COUNT_MISMATCH')
      }
    }

    return {
      authority_pin: authorityPin,
      completeness_metadata,
      table_nodes,
      column_nodes,
      table_column_edges,
      terms,
      parent_nodes,
      table_assignments,
      column_assignments,
      term_parent_edges,
      node_parent_edges,
      glossary_relationships,
      tags: [...tags.values()].map(publicTag).sort((left, right) => left.urn.localeCompare(right.urn)),
      domains: [...domains.values()].sort((left, right) => left.urn.localeCompare(right.urn)),
      containers: [...containers.values()].sort((left, right) => left.urn.localeCompare(right.urn)),
      platform_instances: [...platform_instances.values()].sort((left, right) => left.urn.localeCompare(right.urn)),
      table_tag_assignments,
      column_tag_assignments,
      table_domain_assignments,
      table_container_assignments,
      table_platform_instance_assignments,
    }
  }

  return async function collectK9Metadata(authorityPin, inventory) {
    try {
      return await collect(authorityPin, inventory)
    } catch (error) {
      if (error?.k9SourceFailureDetailCode || providerFailure(error)) throw error
      throw metadataFailure('METADATA_NORMALIZATION_FAILED', error)
    }
  }
}
