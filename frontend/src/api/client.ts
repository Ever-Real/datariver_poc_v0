export type RemediationKind = 'FIDO2_REQUIRED' | 'REAUTH_REQUIRED' | 'FALLBACK_UNAVAILABLE'

export interface ProblemDetails {
  type: string
  title: string
  status: number
  detail: string
  code: string
  request_id: string
  remediation?: { kind: RemediationKind }
}

const remediationKinds = new Set<RemediationKind>([
  'FIDO2_REQUIRED',
  'REAUTH_REQUIRED',
  'FALLBACK_UNAVAILABLE',
])

export class ApiError extends Error {
  readonly problem: ProblemDetails

  constructor(problem: ProblemDetails) {
    super(problem.detail)
    this.name = 'ApiError'
    this.problem = problem
  }
}

export interface RequestOptions extends RequestInit {
  idempotencyKey?: string
  ifMatch?: string
}

export interface ApiResponse<T> {
  data: T
  etag?: string
}

export class ApiClient {
  constructor(
    private readonly baseUrl: string,
    private readonly accessToken: () => string | undefined,
    private readonly workspaceId: () => string,
  ) {}

  async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    return (await this.requestWithMeta<T>(path, options)).data
  }

  async requestWithMeta<T>(path: string, options: RequestOptions = {}): Promise<ApiResponse<T>> {
    const token = this.accessToken()
    if (!token) throw new Error('로그인이 필요합니다.')
    const workspace = this.workspaceId()
    if (!workspace) throw new Error('워크스페이스 ID를 입력하세요.')
    const headers = new Headers(options.headers)
    headers.set('Authorization', `Bearer ${token}`)
    headers.set('X-Workspace-Id', workspace)
    headers.set('Accept', 'application/json')
    if (options.body && !(options.body instanceof FormData)) {
      headers.set('Content-Type', 'application/json')
    }
    if (options.idempotencyKey) headers.set('Idempotency-Key', options.idempotencyKey)
    if (options.ifMatch) headers.set('If-Match', options.ifMatch)
    const response = await fetch(`${this.baseUrl}${path}`, { ...options, headers })
    if (!response.ok) {
      throw new ApiError(await parseProblem(response))
    }
    const data = response.status === 204 ? undefined as T : await response.json() as T
    return { data, etag: response.headers.get('ETag') ?? undefined }
  }
}

export async function parseProblem(response: Response): Promise<ProblemDetails> {
  const fallback: ProblemDetails = {
    type: 'urn:datariver:problem:unexpected_response',
    title: '요청 실패',
    status: response.status,
    detail: `서버가 ${response.status} 상태를 반환했습니다.`,
    code: 'unexpected_response',
    request_id: response.headers.get('X-Request-Id') ?? 'unknown',
  }
  try {
    const value = (await response.json()) as Record<string, unknown>
    const rawRemediation = value.remediation
    const kind = rawRemediation && typeof rawRemediation === 'object'
      ? (rawRemediation as { kind?: unknown }).kind
      : undefined
    const remediation = typeof kind === 'string' && remediationKinds.has(kind as RemediationKind)
      ? { kind: kind as RemediationKind }
      : undefined
    return {
      type: typeof value.type === 'string' ? value.type : fallback.type,
      title: typeof value.title === 'string' ? value.title : fallback.title,
      status: response.status,
      detail: typeof value.detail === 'string' ? value.detail : fallback.detail,
      code: typeof value.code === 'string' ? value.code : fallback.code,
      request_id: typeof value.request_id === 'string' ? value.request_id : fallback.request_id,
      remediation,
    }
  } catch {
    return fallback
  }
}

export function remediationKind(error: unknown): RemediationKind | undefined {
  return error instanceof ApiError ? error.problem.remediation?.kind : undefined
}

export function newIdempotencyKey(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`
}
