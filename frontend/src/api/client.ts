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

export class StaleSecurityContextError extends Error {
  constructor() {
    super('인증 또는 워크스페이스 컨텍스트가 변경되어 이전 요청 결과를 폐기했습니다.')
    this.name = 'StaleSecurityContextError'
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

export interface ApiDownload {
  blob: Blob
  filename: string
  etag?: string
}

export interface ApiEventStreamEvent {
  event: string
  data: unknown
}

export type ApiEventStreamHandler = (event: ApiEventStreamEvent) => void

export type AccessTokenRenewer = () => Promise<string | undefined>

interface SecurityBoundary {
  workspace: string
  securityEpoch: number
}

export class ApiClient {
  constructor(
    private readonly baseUrl: string,
    private readonly accessToken: () => string | undefined,
    private readonly workspaceId: () => string,
    private readonly renewAccessToken?: AccessTokenRenewer,
    private readonly securityEpoch: () => number = () => 0,
  ) {}

  async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    return (await this.requestWithMeta<T>(path, options)).data
  }

  async requestWithMeta<T>(path: string, options: RequestOptions = {}): Promise<ApiResponse<T>> {
    const token = this.accessToken()
    if (!token) throw new Error('로그인이 필요합니다.')
    const workspace = this.workspaceId()
    if (!workspace) throw new Error('워크스페이스 ID를 입력하세요.')
    const boundary = { workspace, securityEpoch: this.securityEpoch() }
    let response = await this.fetchAuthorized(path, options, token, workspace)
    this.assertCurrent(boundary)
    if (response.status === 401 && this.canRetryAfterRenewal(options) && this.renewAccessToken) {
      const renewedToken = await this.renewAccessToken()
      this.assertCurrent(boundary)
      if (renewedToken) {
        response = await this.fetchAuthorized(path, options, renewedToken, workspace)
        this.assertCurrent(boundary)
      }
    }
    if (!response.ok) {
      const problem = await parseProblem(response)
      this.assertCurrent(boundary)
      throw new ApiError(problem)
    }
    const data = response.status === 204 ? undefined as T : await response.json() as T
    this.assertCurrent(boundary)
    return { data, etag: response.headers.get('ETag') ?? undefined }
  }

  async requestEventStream<T>(
    path: string,
    options: RequestOptions,
    onEvent: ApiEventStreamHandler,
  ): Promise<T> {
    const token = this.accessToken()
    if (!token) throw new Error('로그인이 필요합니다.')
    const workspace = this.workspaceId()
    if (!workspace) throw new Error('워크스페이스 ID를 입력하세요.')
    const boundary = { workspace, securityEpoch: this.securityEpoch() }
    const headers = new Headers(options.headers)
    headers.set('Accept', 'text/event-stream')
    const response = await this.fetchAuthorized(
      path,
      { ...options, cache: 'no-store', headers },
      token,
      workspace,
    )
    this.assertCurrent(boundary)
    if (!response.ok) {
      const problem = await parseProblem(response)
      this.assertCurrent(boundary)
      throw new ApiError(problem)
    }
    if (response.body === null) {
      throw new Error('서버가 Chat 진행 상태 스트림을 열지 못했습니다.')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let result: T | undefined
    let receivedResult = false
    try {
      while (!receivedResult) {
        const { done, value } = await reader.read()
        this.assertCurrent(boundary)
        buffer += decoder.decode(value, { stream: !done }).replace(/\r\n?/g, '\n')
        const frames = buffer.split('\n\n')
        buffer = done ? '' : (frames.pop() ?? '')
        for (const frame of frames) {
          const event = parseEventStreamFrame(frame)
          if (!event) continue
          if (event.event === 'error') {
            throw new Error(eventStreamErrorDetail(event.data))
          }
          if (event.event === 'result') {
            result = event.data as T
            receivedResult = true
            break
          }
          onEvent(event)
          this.assertCurrent(boundary)
        }
        if (done && !receivedResult) {
          throw new Error('서버가 Chat 최종 결과를 반환하지 않았습니다.')
        }
      }
    } finally {
      if (!receivedResult) {
        await reader.cancel().catch(() => undefined)
      }
      reader.releaseLock()
    }
    this.assertCurrent(boundary)
    return result as T
  }

  async download(
    path: string,
    options: Pick<RequestOptions, 'signal'> = {},
  ): Promise<ApiDownload> {
    const token = this.accessToken()
    if (!token) throw new Error('로그인이 필요합니다.')
    const workspace = this.workspaceId()
    if (!workspace) throw new Error('워크스페이스 ID를 입력하세요.')
    const boundary = { workspace, securityEpoch: this.securityEpoch() }
    const requestOptions: RequestOptions = {
      method: 'GET',
      cache: 'no-store',
      signal: options.signal,
      headers: {
        Accept: 'application/octet-stream,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'Cache-Control': 'no-store',
      },
    }
    let response = await this.fetchAuthorized(path, requestOptions, token, workspace)
    this.assertCurrent(boundary)
    if (response.status === 401 && this.renewAccessToken) {
      const renewedToken = await this.renewAccessToken()
      this.assertCurrent(boundary)
      if (renewedToken) {
        response = await this.fetchAuthorized(path, requestOptions, renewedToken, workspace)
        this.assertCurrent(boundary)
      }
    }
    if (!response.ok) {
      const problem = await parseProblem(response)
      this.assertCurrent(boundary)
      throw new ApiError(problem)
    }
    const blob = await response.blob()
    this.assertCurrent(boundary)
    return {
      blob,
      filename: downloadFilename(response.headers.get('Content-Disposition')),
      etag: response.headers.get('ETag') ?? undefined,
    }
  }

  private assertCurrent(expected: SecurityBoundary): void {
    if (
      this.workspaceId() !== expected.workspace
      || this.securityEpoch() !== expected.securityEpoch
    ) {
      throw new StaleSecurityContextError()
    }
  }

  private async fetchAuthorized(
    path: string,
    options: RequestOptions,
    token: string,
    workspace: string,
  ): Promise<Response> {
    const headers = new Headers(options.headers)
    headers.set('Authorization', `Bearer ${token}`)
    headers.set('X-Workspace-Id', workspace)
    if (!headers.has('Accept')) headers.set('Accept', 'application/json')
    if (options.body && !(options.body instanceof FormData)) {
      headers.set('Content-Type', 'application/json')
    }
    if (options.idempotencyKey) headers.set('Idempotency-Key', options.idempotencyKey)
    if (options.ifMatch) headers.set('If-Match', options.ifMatch)
    return fetch(`${this.baseUrl}${path}`, { ...options, headers })
  }

  private canRetryAfterRenewal(options: RequestOptions): boolean {
    const method = (options.method ?? 'GET').toUpperCase()
    // A retry must be safe even if the browser receives a response after the
    // server has already accepted work. Reads are intrinsically safe; writes
    // need the application's durable idempotency boundary.
    return method === 'GET' || method === 'HEAD' || Boolean(options.idempotencyKey)
  }
}

function parseEventStreamFrame(frame: string): ApiEventStreamEvent | undefined {
  let event = 'message'
  const dataLines: string[] = []
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) {
      event = line.slice('event:'.length).trim() || 'message'
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice('data:'.length).trimStart())
    }
  }
  if (dataLines.length === 0) return undefined
  try {
    return { event, data: JSON.parse(dataLines.join('\n')) as unknown }
  } catch {
    throw new Error('서버가 유효하지 않은 Chat 진행 상태를 반환했습니다.')
  }
}

function eventStreamErrorDetail(value: unknown): string {
  if (
    value
    && typeof value === 'object'
    && 'detail' in value
    && typeof value.detail === 'string'
  ) {
    return value.detail
  }
  return 'Chat 응답 처리 중 문제가 발생했습니다. 다시 시도하세요.'
}

function downloadFilename(contentDisposition: string | null): string {
  const encoded = contentDisposition?.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  const quoted = contentDisposition?.match(/filename="([^"]+)"/i)?.[1]
  const plain = contentDisposition?.match(/filename=([^;]+)/i)?.[1]
  let candidate = encoded ?? quoted ?? plain ?? 'download'
  if (encoded) {
    try {
      candidate = decodeURIComponent(encoded)
    } catch {
      candidate = 'download'
    }
  }
  const basename = candidate.trim().replaceAll('\\', '/').split('/').at(-1) ?? 'download'
  const safe = [...basename]
    .filter((character) => character.charCodeAt(0) >= 32 && character !== '\u007f')
    .join('')
    .slice(0, 255)
  return safe || 'download'
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

export async function sha256Text(value: string): Promise<string> {
  const encoded = new TextEncoder().encode(value)
  const digest = await crypto.subtle.digest('SHA-256', encoded)
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
}
