import { describe, expect, it } from 'vitest'
import { formatSafeCypherDraft, parseSafeCypherDraft } from './knowledgeCypherDraft'

describe('safe local Cypher draft subset', () => {
  it('parses only declared CREATE nodes and relationships into a typed local draft', () => {
    const result = parseSafeCypherDraft(`
      // local T-Box draft
      CREATE (p:Product)
      CREATE (m:Material)
      CREATE (p)-[:MADE_FROM]->(m)
    `)
    expect(result.error).toBeUndefined()
    expect(result.nodes.map((node) => node.label)).toEqual(['Product', 'Material'])
    expect(result.nodes.every((node) => /^[0-9a-f-]{36}$/i.test(node.id))).toBe(true)
    expect(result.edges).toEqual([expect.objectContaining({
      source: result.nodes[0]?.id, target: result.nodes[1]?.id, relation: 'MADE_FROM',
    })])
    expect(result.edges.every((edge) => /^[0-9a-f-]{36}$/i.test(edge.id))).toBe(true)
    expect(formatSafeCypherDraft(result.nodes, result.edges)).toContain('CREATE (n0)-[:MADE_FROM]->(n1)')
  })

  it('rejects properties, queries and undeclared aliases instead of passing through raw Cypher', () => {
    expect(parseSafeCypherDraft("CREATE (p:Product {secret: 'x'})").error).toMatch(/허용된 CREATE/)
    expect(parseSafeCypherDraft('MATCH (n) RETURN n').error).toMatch(/허용된 CREATE/)
    expect(parseSafeCypherDraft('CREATE (p:Product)\nCREATE (p)-[:USES]->(missing)').error).toMatch(/선언되지 않은/)
  })
})
