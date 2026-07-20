export interface SafeCypherNode {
  id: string
  label: string
}

export interface SafeCypherEdge {
  id: string
  source: string
  target: string
  relation: string
}

export interface SafeCypherParseResult {
  nodes: SafeCypherNode[]
  edges: SafeCypherEdge[]
  error?: string
}

const identifier = '[A-Za-z][A-Za-z0-9_]{0,63}'
const nodePattern = new RegExp(`^CREATE\\s+\\((${identifier}):(${identifier})\\)\\s*;?$`, 'i')
const edgePattern = new RegExp(`^CREATE\\s+\\((${identifier})\\)-\\[:(${identifier})\\]->\\((${identifier})\\)\\s*;?$`, 'i')

export function parseSafeCypherDraft(source: string): SafeCypherParseResult {
  if (source.length > 50_000) return { nodes: [], edges: [], error: '입력은 50,000자 이하여야 합니다.' }
  const statements = source.split(/\r?\n/)
    .map((line) => line.replace(/\/\/.*$/, '').trim())
    .filter(Boolean)
  const nodes: SafeCypherNode[] = []
  const aliases = new Map<string, SafeCypherNode>()
  const pendingEdges: Array<{ sourceAlias: string; targetAlias: string; relation: string; line: number }> = []

  for (const [index, statement] of statements.entries()) {
    const node = nodePattern.exec(statement)
    if (node) {
      const alias = node[1]
      const label = node[2]
      if (!alias || !label) continue
      if (aliases.has(alias)) return { nodes, edges: [], error: `${index + 1}번째 문장의 alias '${alias}'가 중복됩니다.` }
      // The server contract requires UUID stable_entity_id values. Aliases remain local parser
      // symbols only and are never sent as entity identifiers.
      const value = { id: crypto.randomUUID(), label }
      aliases.set(alias, value)
      nodes.push(value)
      continue
    }
    const edge = edgePattern.exec(statement)
    if (edge) {
      const [, sourceAlias, relation, targetAlias] = edge
      if (sourceAlias && relation && targetAlias) pendingEdges.push({ sourceAlias, targetAlias, relation: relation.toUpperCase(), line: index + 1 })
      continue
    }
    return { nodes, edges: [], error: `${index + 1}번째 문장은 허용된 CREATE 노드/관계 형식이 아닙니다.` }
  }

  if (nodes.length > 100 || pendingEdges.length > 200) {
    return { nodes: [], edges: [], error: '로컬 초안은 노드 100개, 관계 200개까지 허용합니다.' }
  }
  const edges: SafeCypherEdge[] = []
  for (const edge of pendingEdges) {
    const source = aliases.get(edge.sourceAlias)
    const target = aliases.get(edge.targetAlias)
    if (!source || !target) {
      return { nodes, edges: [], error: `${edge.line}번째 관계가 선언되지 않은 노드 alias를 참조합니다.` }
    }
    edges.push({
      id: crypto.randomUUID(),
      source: source.id,
      target: target.id,
      relation: edge.relation,
    })
  }
  return { nodes, edges }
}

export function formatSafeCypherDraft(nodes: SafeCypherNode[], edges: SafeCypherEdge[]): string {
  const aliases = new Map(nodes.map((node, index) => [node.id, `n${index}`]))
  const nodeLines = nodes.map((node, index) => `CREATE (n${index}:${node.label})`)
  const edgeLines = edges.flatMap((edge) => {
    const source = aliases.get(edge.source)
    const target = aliases.get(edge.target)
    return source && target ? [`CREATE (${source})-[:${edge.relation}]->(${target})`] : []
  })
  return [...nodeLines, ...edgeLines].join('\n')
}
