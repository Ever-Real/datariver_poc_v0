import { describe, expect, it } from 'vitest'
import {
  formatSafeCypherAst,
  formatSafeCypherDraft,
  parseSafeCypherAst,
  parseSafeCypherDraft,
} from './knowledgeCypherDraft'

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
    expect(formatSafeCypherDraft(result.nodes, result.edges)).toContain('CREATE (p)-[:MADE_FROM]->(m)')
  })

  it('builds and formats an AST without executing or rewriting raw query text', () => {
    const ast = parseSafeCypherAst('CREATE (p:Product); CREATE (m:Material)\nCREATE (p)-[:MADE_FROM]->(m)')
    expect(ast.statements.map((statement) => statement.kind)).toEqual(['NODE', 'NODE', 'RELATION'])
    expect(formatSafeCypherAst(ast)).toContain('CREATE (p)-[:MADE_FROM]->(m)')
  })

  it('preserves stable node and edge identity across AST round trips and renames', () => {
    const initial = parseSafeCypherDraft(`
      CREATE (p:Product)
      CREATE (m:Material)
      CREATE (p)-[:MADE_FROM]->(m)
    `)
    const updated = parseSafeCypherDraft(`
      CREATE (p:FinishedProduct)
      CREATE (m:Material)
      CREATE (p)-[:USES_MATERIAL]->(m)
    `, initial)
    expect(updated.nodes.map((node) => node.id)).toEqual(initial.nodes.map((node) => node.id))
    expect(updated.edges[0]?.id).toBe(initial.edges[0]?.id)
  })

  it('rejects properties, queries and undeclared aliases instead of passing through raw Cypher', () => {
    expect(parseSafeCypherDraft("CREATE (p:Product {secret: 'x'})").error).toMatch(/허용되지 않습니다/)
    expect(parseSafeCypherDraft('MATCH (n) RETURN n').error).toMatch(/CREATE/)
    expect(parseSafeCypherDraft('CALL db.labels()').error).toMatch(/CREATE/)
    expect(parseSafeCypherDraft('LOAD CSV FROM "https://example.invalid/data.csv"').error).toMatch(/CREATE/)
    expect(parseSafeCypherDraft(`CREATE (p:${'A'.repeat(65)})`).error).toMatch(/64자/)
    expect(parseSafeCypherDraft('CREATE (p:Product)\nCREATE (p)-[:USES]->(missing)').error).toMatch(/선언되지 않은/)
  })
})
