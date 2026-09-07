
// Dependencies are supplied by bootstrap; this module never constructs a shared client.
export function createInfrastructureNeo4j(deps) {
async function neo4jQuery(statement, parameters = {}, timeoutMs = deps.providerTimeoutMs, signal) {
  if (!deps.neo4j) throw Object.assign(new Error('Neo4j is not configured.'), { statusCode: 503 })
  let response
  try {
    response = await deps.providerFetch(deps.joinProviderUrl(deps.neo4j.url, '/db/neo4j/tx/commit'), {
      method: 'POST',
      headers: { Authorization: deps.basicAuthorization(deps.neo4j), 'Content-Type': 'application/json' },
      body: JSON.stringify({ statements: [{ statement, parameters, resultDataContents: ['row'] }] }),
      timeoutMs,
      signal,
    })
  } catch (error) {
    throw Object.assign(new Error('Neo4j transport failed.'), {
      neo4jHttpClass: 'TRANSPORT',
      neo4jErrorClass: ['TimeoutError', 'AbortError'].includes(error?.name) ? 'TIMEOUT' : 'TRANSPORT',
    })
  }
  if (!response.ok) {
    throw Object.assign(new Error(`Neo4j returned HTTP ${response.status}.`), {
      neo4jHttpClass: response.status >= 500 ? 'HTTP_5XX' : 'HTTP_4XX',
      neo4jErrorClass: response.status === 401 || response.status === 403 ? 'AUTH' : 'HTTP',
    })
  }
  let payload
  try {
    payload = await response.json()
  } catch {
    throw Object.assign(new Error('Neo4j response was not valid JSON.'), {
      neo4jHttpClass: 'HTTP_2XX', neo4jErrorClass: 'RESPONSE_CONTRACT',
    })
  }
  if (!payload || !Array.isArray(payload.errors) || !Array.isArray(payload.results)) {
    throw Object.assign(new Error('Neo4j response contract is invalid.'), {
      neo4jHttpClass: 'HTTP_2XX', neo4jErrorClass: 'RESPONSE_CONTRACT',
    })
  }
  if (payload.errors.length) {
    const code = typeof payload.errors[0]?.code === 'string' ? payload.errors[0].code : ''
    const errorClass = code.startsWith('Neo.ClientError.Security.') ? 'AUTH'
      : code.startsWith('Neo.ClientError.') ? 'CLIENT'
        : code.startsWith('Neo.TransientError.') ? 'TRANSIENT'
          : code.startsWith('Neo.DatabaseError.') ? 'DATABASE' : 'UNKNOWN'
    throw Object.assign(new Error(`Neo4j query failed: ${code || 'UNKNOWN'}`), {
      neo4jHttpClass: 'HTTP_2XX', neo4jErrorClass: errorClass,
    })
  }
  return payload.results?.[0]?.data || []
}

async function neo4jGraph() {
  const rows = await neo4jQuery(`
    MATCH (source)-[relation]->(target)
    RETURN coalesce(source.id, source.urn, elementId(source)),
           coalesce(source.name, source.label, source.urn, elementId(source)),
           coalesce(source.entity_type, head(labels(source)), 'ENTITY'),
           type(relation),
           coalesce(target.id, target.urn, elementId(target)),
           coalesce(target.name, target.label, target.urn, elementId(target)),
           coalesce(target.entity_type, head(labels(target)), 'ENTITY')
    ORDER BY source.id, target.id
    LIMIT 100
  `)
  const nodes = new Map()
  const edges = []
  for (const item of rows) {
    const row = item.row || []
    if (!row[0]) continue
    nodes.set(row[0], { id: row[0], name: row[1], entity_type: row[2] || 'CLASS' })
    if (row[4]) {
      nodes.set(row[4], { id: row[4], name: row[5], entity_type: row[6] || 'CLASS' })
      edges.push({ id: `${row[0]}-${row[3]}-${row[4]}`, source_id: row[0], target_id: row[4], edge_type: row[3] })
    }
  }
  return { nodes: [...nodes.values()], edges }
}

return { neo4jQuery, neo4jGraph }
}
