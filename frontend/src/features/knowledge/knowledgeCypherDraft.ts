export interface SafeCypherNode {
  id: string
  label: string
  alias?: string
}

export interface SafeCypherEdge {
  id: string
  source: string
  target: string
  relation: string
  sourceAlias?: string
  targetAlias?: string
}

export interface SafeCypherNodeDeclaration {
  kind: 'NODE'
  alias: string
  label: string
  line: number
}

export interface SafeCypherRelationDeclaration {
  kind: 'RELATION'
  sourceAlias: string
  targetAlias: string
  relation: string
  line: number
}

export interface SafeCypherProgram {
  kind: 'PROGRAM'
  statements: Array<SafeCypherNodeDeclaration | SafeCypherRelationDeclaration>
}

export interface SafeCypherParseResult {
  nodes: SafeCypherNode[]
  edges: SafeCypherEdge[]
  ast?: SafeCypherProgram
  error?: string
  diagnostic?: {
    message: string
    line: number
    column: number
  }
}

type TokenKind =
  | 'CREATE'
  | 'IDENTIFIER'
  | 'LPAREN'
  | 'RPAREN'
  | 'LBRACKET'
  | 'RBRACKET'
  | 'COLON'
  | 'DASH'
  | 'ARROW'
  | 'SEMICOLON'
  | 'NEWLINE'
  | 'EOF'

interface Token {
  kind: TokenKind
  value: string
  line: number
  column: number
}

class CypherSubsetError extends Error {
  readonly line: number
  readonly column: number

  constructor(message: string, line: number, column = 1) {
    super(message)
    this.line = line
    this.column = column
  }
}

export function isSafeCypherIdentifier(value: string): boolean {
  if (value.length < 1 || value.length > 64) return false
  if (!isAsciiLetter(value[0])) return false
  for (let index = 1; index < value.length; index += 1) {
    const character = value[index]
    if (!(isAsciiLetter(character) || isAsciiDigit(character) || character === '_')) {
      return false
    }
  }
  return true
}

function isAsciiLetter(value: string | undefined): boolean {
  if (!value) return false
  return (value >= 'A' && value <= 'Z') || (value >= 'a' && value <= 'z')
}

function isAsciiDigit(value: string | undefined): boolean {
  return Boolean(value && value >= '0' && value <= '9')
}

function isIdentifierContinuation(value: string | undefined): boolean {
  return isAsciiLetter(value) || isAsciiDigit(value) || value === '_'
}

function lexCypherSubset(source: string): Token[] {
  const tokens: Token[] = []
  let index = 0
  let line = 1
  let column = 1

  const push = (kind: TokenKind, value: string, tokenLine = line, tokenColumn = column) => {
    tokens.push({ kind, value, line: tokenLine, column: tokenColumn })
  }

  while (index < source.length) {
    const character = source[index]
    if (character === ' ' || character === '\t') {
      index += 1
      column += 1
      continue
    }
    if (character === '\r' || character === '\n') {
      const tokenLine = line
      const tokenColumn = column
      if (character === '\r' && source[index + 1] === '\n') index += 1
      index += 1
      line += 1
      column = 1
      push('NEWLINE', '\n', tokenLine, tokenColumn)
      continue
    }
    if (character === '/' && source[index + 1] === '/') {
      index += 2
      column += 2
      while (index < source.length && source[index] !== '\r' && source[index] !== '\n') {
        index += 1
        column += 1
      }
      continue
    }
    if (isAsciiLetter(character)) {
      const tokenLine = line
      const tokenColumn = column
      const start = index
      while (isIdentifierContinuation(source[index])) {
        index += 1
        column += 1
      }
      const value = source.slice(start, index)
      if (value.length > 64) {
        throw new CypherSubsetError(
          `${tokenLine}번째 줄 ${tokenColumn}번째 식별자는 64자를 초과할 수 없습니다.`,
          tokenLine,
          tokenColumn,
        )
      }
      push(value.toUpperCase() === 'CREATE' ? 'CREATE' : 'IDENTIFIER', value, tokenLine, tokenColumn)
      continue
    }

    const singleCharacterKinds: Partial<Record<string, TokenKind>> = {
      '(': 'LPAREN',
      ')': 'RPAREN',
      '[': 'LBRACKET',
      ']': 'RBRACKET',
      ':': 'COLON',
      ';': 'SEMICOLON',
    }
    const singleKind = singleCharacterKinds[character ?? '']
    if (singleKind) {
      push(singleKind, character ?? '')
      index += 1
      column += 1
      continue
    }
    if (character === '-' && source[index + 1] === '>') {
      push('ARROW', '->')
      index += 2
      column += 2
      continue
    }
    if (character === '-') {
      push('DASH', '-')
      index += 1
      column += 1
      continue
    }
    throw new CypherSubsetError(
      `${line}번째 줄 ${column}번째 문자는 안전한 CREATE subset에서 허용되지 않습니다.`,
      line,
      column,
    )
  }
  push('EOF', '')
  return tokens
}

class CypherSubsetParser {
  private cursor = 0

  constructor(private readonly tokens: Token[]) {}

  parseProgram(): SafeCypherProgram {
    const statements: SafeCypherProgram['statements'] = []
    this.consumeSeparators()
    while (this.peek().kind !== 'EOF') {
      statements.push(this.parseCreate())
      const next = this.peek()
      if (next.kind !== 'NEWLINE' && next.kind !== 'SEMICOLON' && next.kind !== 'EOF') {
        throw this.expected('줄바꿈, 세미콜론 또는 입력 끝', next)
      }
      this.consumeSeparators()
    }
    return { kind: 'PROGRAM', statements }
  }

  private parseCreate(): SafeCypherNodeDeclaration | SafeCypherRelationDeclaration {
    const create = this.take('CREATE', 'CREATE')
    this.take('LPAREN', '(')
    const sourceAlias = this.take('IDENTIFIER', '노드 alias').value
    if (this.peek().kind === 'COLON') {
      this.advance()
      const label = this.take('IDENTIFIER', '노드 label').value
      this.take('RPAREN', ')')
      return { kind: 'NODE', alias: sourceAlias, label, line: create.line }
    }

    this.take('RPAREN', ')')
    this.take('DASH', '-')
    this.take('LBRACKET', '[')
    this.take('COLON', ':')
    const relation = this.take('IDENTIFIER', '관계 유형').value
    this.take('RBRACKET', ']')
    this.take('ARROW', '->')
    this.take('LPAREN', '(')
    const targetAlias = this.take('IDENTIFIER', '대상 노드 alias').value
    this.take('RPAREN', ')')
    return {
      kind: 'RELATION',
      sourceAlias,
      targetAlias,
      relation: relation.toUpperCase(),
      line: create.line,
    }
  }

  private consumeSeparators() {
    while (this.peek().kind === 'NEWLINE' || this.peek().kind === 'SEMICOLON') this.advance()
  }

  private take(kind: TokenKind, expected: string): Token {
    const token = this.peek()
    if (token.kind !== kind) throw this.expected(expected, token)
    this.advance()
    return token
  }

  private expected(expected: string, token: Token): CypherSubsetError {
    return new CypherSubsetError(
      `${token.line}번째 줄 ${token.column}번째에서 ${expected}이(가) 필요합니다.`,
      token.line,
      token.column,
    )
  }

  private peek(): Token {
    return this.tokens[this.cursor] ?? this.tokens[this.tokens.length - 1]!
  }

  private advance() {
    this.cursor += 1
  }
}

export function parseSafeCypherAst(source: string): SafeCypherProgram {
  return new CypherSubsetParser(lexCypherSubset(source)).parseProgram()
}

function priorAliases(previous?: Pick<SafeCypherParseResult, 'nodes' | 'edges'>) {
  const nodeIdByAlias = new Map<string, string>()
  const aliasByNodeId = new Map<string, string>()
  for (const [index, node] of (previous?.nodes ?? []).entries()) {
    const alias = node.alias && isSafeCypherIdentifier(node.alias) ? node.alias : `n${index}`
    if (nodeIdByAlias.has(alias)) continue
    nodeIdByAlias.set(alias, node.id)
    aliasByNodeId.set(node.id, alias)
  }

  const exactEdgeId = new Map<string, string>()
  const edgeIdsByEndpoints = new Map<string, string[]>()
  for (const edge of previous?.edges ?? []) {
    const sourceAlias = edge.sourceAlias ?? aliasByNodeId.get(edge.source)
    const targetAlias = edge.targetAlias ?? aliasByNodeId.get(edge.target)
    if (!sourceAlias || !targetAlias) continue
    exactEdgeId.set(edgeIdentity(sourceAlias, edge.relation, targetAlias), edge.id)
    const endpointKey = endpointIdentity(sourceAlias, targetAlias)
    edgeIdsByEndpoints.set(endpointKey, [...(edgeIdsByEndpoints.get(endpointKey) ?? []), edge.id])
  }
  return { nodeIdByAlias, exactEdgeId, edgeIdsByEndpoints }
}

function edgeIdentity(sourceAlias: string, relation: string, targetAlias: string): string {
  return `${sourceAlias}\u0000${relation}\u0000${targetAlias}`
}

function endpointIdentity(sourceAlias: string, targetAlias: string): string {
  return `${sourceAlias}\u0000${targetAlias}`
}

export function projectSafeCypherAst(
  ast: SafeCypherProgram,
  previous?: Pick<SafeCypherParseResult, 'nodes' | 'edges'>,
): SafeCypherParseResult {
  const prior = priorAliases(previous)
  const nodes: SafeCypherNode[] = []
  const nodeByAlias = new Map<string, SafeCypherNode>()
  const relations: SafeCypherRelationDeclaration[] = []

  for (const statement of ast.statements) {
    if (statement.kind === 'RELATION') {
      relations.push(statement)
      continue
    }
    if (nodeByAlias.has(statement.alias)) {
      const message = `${statement.line}번째 문장의 alias '${statement.alias}'가 중복됩니다.`
      return {
        nodes,
        edges: [],
        ast,
        error: message,
        diagnostic: { message, line: statement.line, column: 1 },
      }
    }
    const node = {
      id: prior.nodeIdByAlias.get(statement.alias) ?? crypto.randomUUID(),
      label: statement.label,
      alias: statement.alias,
    }
    nodeByAlias.set(statement.alias, node)
    nodes.push(node)
  }

  if (nodes.length > 100 || relations.length > 200) {
    return { nodes: [], edges: [], ast, error: '로컬 초안은 노드 100개, 관계 200개까지 허용합니다.' }
  }

  const usedRelationKeys = new Set<string>()
  const edges: SafeCypherEdge[] = []
  for (const relation of relations) {
    const source = nodeByAlias.get(relation.sourceAlias)
    const target = nodeByAlias.get(relation.targetAlias)
    if (!source || !target) {
      const message = `${relation.line}번째 관계가 선언되지 않은 노드 alias를 참조합니다.`
      return {
        nodes,
        edges: [],
        ast,
        error: message,
        diagnostic: { message, line: relation.line, column: 1 },
      }
    }
    const exactKey = edgeIdentity(
      relation.sourceAlias,
      relation.relation,
      relation.targetAlias,
    )
    if (usedRelationKeys.has(exactKey)) {
      const message = `${relation.line}번째 관계가 같은 endpoint와 유형으로 중복됩니다.`
      return {
        nodes,
        edges: [],
        ast,
        error: message,
        diagnostic: { message, line: relation.line, column: 1 },
      }
    }
    usedRelationKeys.add(exactKey)
    const endpointCandidates = prior.edgeIdsByEndpoints.get(
      endpointIdentity(relation.sourceAlias, relation.targetAlias),
    ) ?? []
    edges.push({
      id: prior.exactEdgeId.get(exactKey)
        ?? (endpointCandidates.length === 1 ? endpointCandidates[0]! : crypto.randomUUID()),
      source: source.id,
      target: target.id,
      relation: relation.relation,
      sourceAlias: relation.sourceAlias,
      targetAlias: relation.targetAlias,
    })
  }
  return { nodes, edges, ast }
}

export function parseSafeCypherDraft(
  source: string,
  previous?: Pick<SafeCypherParseResult, 'nodes' | 'edges'>,
): SafeCypherParseResult {
  if (source.length > 50_000) {
    return { nodes: [], edges: [], error: '입력은 50,000자 이하여야 합니다.' }
  }
  try {
    return projectSafeCypherAst(parseSafeCypherAst(source), previous)
  } catch (error) {
    if (error instanceof CypherSubsetError) {
      return {
        nodes: [],
        edges: [],
        error: error.message,
        diagnostic: {
          message: error.message,
          line: error.line,
          column: error.column,
        },
      }
    }
    return { nodes: [], edges: [], error: '안전한 CREATE subset을 해석할 수 없습니다.' }
  }
}

export function graphToSafeCypherAst(
  nodes: SafeCypherNode[],
  edges: SafeCypherEdge[],
): SafeCypherProgram {
  const aliasById = new Map<string, string>()
  const usedAliases = new Set<string>()
  const statements: SafeCypherProgram['statements'] = []

  for (const [index, node] of nodes.entries()) {
    let alias = node.alias
    if (!alias || !isSafeCypherIdentifier(alias) || usedAliases.has(alias)) alias = `n${index}`
    usedAliases.add(alias)
    aliasById.set(node.id, alias)
    statements.push({ kind: 'NODE', alias, label: node.label, line: index + 1 })
  }
  for (const edge of edges) {
    const sourceAlias = aliasById.get(edge.source)
    const targetAlias = aliasById.get(edge.target)
    if (!sourceAlias || !targetAlias) continue
    statements.push({
      kind: 'RELATION',
      sourceAlias,
      targetAlias,
      relation: edge.relation,
      line: statements.length + 1,
    })
  }
  return { kind: 'PROGRAM', statements }
}

export function formatSafeCypherAst(ast: SafeCypherProgram): string {
  return ast.statements.map((statement) => {
    if (statement.kind === 'NODE') {
      return `CREATE (${statement.alias}:${statement.label})`
    }
    return `CREATE (${statement.sourceAlias})-[:${statement.relation}]->(${statement.targetAlias})`
  }).join('\n')
}

export function formatSafeCypherDraft(nodes: SafeCypherNode[], edges: SafeCypherEdge[]): string {
  return formatSafeCypherAst(graphToSafeCypherAst(nodes, edges))
}
