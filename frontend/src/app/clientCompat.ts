type RemediationKind = 'FIDO2_REQUIRED' | 'REAUTH_REQUIRED' | 'FALLBACK_UNAVAILABLE'

interface ProblemDetails {
  type: string
  title: string
  status: number
  detail: string
  code: string
  request_id: string
  remediation?: { kind: RemediationKind }
}

export class ApiError extends Error {
  readonly problem: ProblemDetails

  constructor(problem: ProblemDetails) {
    super(problem.detail)
    this.name = 'ApiError'
    this.problem = problem
  }
}

export class StaleSecurityContextError extends Error {
  constructor() {
    super('POC 화면 상태가 변경되어 이전 요청 결과를 폐기했습니다.')
    this.name = 'StaleSecurityContextError'
  }
}

export function remediationKind(error: unknown): RemediationKind | undefined {
  return error instanceof ApiError ? error.problem.remediation?.kind : undefined
}

let idempotencySequence = 0

export function newIdempotencyKey(prefix: string): string {
  idempotencySequence += 1
  return `${prefix}-poc-${idempotencySequence.toString().padStart(4, '0')}`
}

export function sha256Text(value: string): Promise<string> {
  let hash = 2166136261
  for (const character of value) {
    hash ^= character.charCodeAt(0)
    hash = Math.imul(hash, 16777619)
  }
  const word = (hash >>> 0).toString(16).padStart(8, '0')
  return Promise.resolve(word.repeat(8))
}
