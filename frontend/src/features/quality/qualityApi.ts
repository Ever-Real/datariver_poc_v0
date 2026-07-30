import type { ApiClient } from '../../api/client'
import type {
  QualityAsset,
  QualityCapability,
  QualityExpectationResult,
  QualityIssueSummary,
  QualityListResponse,
  QualityOverview,
  QualityResourceResponse,
  QualityRuleDefinitionCatalog,
  QualityRuleSetDetail,
  QualityRuleSetSummary,
  QualityRunSummary,
} from '../../api/types'

export interface QualitySecurityBoundary {
  workspaceId: string
  subjectId: string
  securityEpoch: number
  authorizationRevision: number
  cacheScope: string
}

export type QualityResource =
  | 'overview'
  | 'assets'
  | 'rule-definitions'
  | 'rule-sets'
  | 'rule-set-detail'
  | 'runs'
  | 'run-results'
  | 'issues'

export function qualityQueryKey(
  boundary: QualitySecurityBoundary,
  resource: QualityResource,
  ...scope: readonly unknown[]
) {
  return [
    'quality',
    boundary.workspaceId,
    boundary.subjectId,
    boundary.securityEpoch,
    boundary.authorizationRevision,
    boundary.cacheScope,
    resource,
    ...scope,
  ] as const
}

export function qualityBoundaryPrefix(boundary: QualitySecurityBoundary) {
  return [
    'quality',
    boundary.workspaceId,
    boundary.subjectId,
    boundary.securityEpoch,
    boundary.authorizationRevision,
    boundary.cacheScope,
  ] as const
}

export class QualityApi {
  constructor(private readonly client: Pick<ApiClient, 'request'>) {}

  async capability(signal?: AbortSignal): Promise<QualityCapability> {
    const value = await this.client.request<QualityCapability>('/quality/capability', {
      cache: 'no-store',
      signal,
    })
    assertCapability(value)
    return value
  }

  async overview(signal?: AbortSignal): Promise<QualityOverview> {
    const value = await this.client.request<QualityOverview>('/quality/overview?days=30', {
      cache: 'no-store',
      signal,
    })
    assertOverview(value)
    return value
  }

  async ruleDefinitions(signal?: AbortSignal): Promise<QualityRuleDefinitionCatalog> {
    const catalog = await this.client.request<QualityRuleDefinitionCatalog>(
      '/quality/rule-definitions',
      { cache: 'no-store', signal },
    )
    if (
      !catalog
      || catalog.contract_version !== 'QUALITY_TYPED_RULES_V1'
      || !Array.isArray(catalog.items)
      || catalog.items.length > 3
      || new Set(catalog.items.map((item) => item.kind)).size !== catalog.items.length
      || catalog.items.some((item) => (
        !['NOT_NULL', 'RANGE', 'REGEX'].includes(item.kind)
        || typeof item.available !== 'boolean'
        || !item.parameter_contract
        || typeof item.parameter_contract !== 'object'
        || Array.isArray(item.parameter_contract)
      ))
    ) {
      throw new Error('품질 Rule 정의 계약이 올바르지 않습니다.')
    }
    return catalog
  }

  assets(cursor?: string, signal?: AbortSignal) {
    return this.list<QualityAsset>('/quality/assets', { cursor, signal })
  }

  ruleSets(cursor?: string, signal?: AbortSignal) {
    return this.list<QualityRuleSetSummary>('/quality/rule-sets', { cursor, signal })
  }

  async ruleSet(
    ruleSetId: string,
    expectedCacheScope: string,
    signal?: AbortSignal,
  ): Promise<QualityRuleSetDetail> {
    const value = await this.client.request<QualityResourceResponse<QualityRuleSetDetail>>(
      `/quality/rule-sets/${encodeURIComponent(ruleSetId)}`,
      { cache: 'no-store', signal },
    )
    const detail = value?.item
    if (
      !detail
      || detail.rule_set?.rule_set_id !== ruleSetId
      || !Array.isArray(detail.versions)
      || !Array.isArray(detail.definitions)
      || value.cache_scope !== expectedCacheScope
      || !validDate(value.observed_at)
      || !validDate(value.authorization_valid_until)
    ) {
      throw new Error('선택한 품질 Rule Set 상세를 확인할 수 없습니다.')
    }
    return detail
  }

  runs(cursor?: string, signal?: AbortSignal) {
    return this.list<QualityRunSummary>('/quality/runs', { cursor, signal })
  }

  async run(
    runId: string,
    expectedCacheScope: string,
    signal?: AbortSignal,
  ): Promise<QualityRunSummary> {
    const value = await this.client.request<QualityResourceResponse<QualityRunSummary>>(
      `/quality/runs/${encodeURIComponent(runId)}`,
      { cache: 'no-store', signal },
    )
    const run = value?.item
    if (
      !run
      || run.run_id !== runId
      || value.cache_scope !== expectedCacheScope
      || !validDate(value.observed_at)
      || !validDate(value.authorization_valid_until)
    ) {
      throw new Error('선택한 품질 실행의 현재 상태를 확인할 수 없습니다.')
    }
    return run
  }

  runResults(runId: string, cursor?: string, signal?: AbortSignal) {
    return this.list<QualityExpectationResult>(
      `/quality/runs/${encodeURIComponent(runId)}/results`,
      { cursor, signal },
    )
  }

  issues(cursor?: string, signal?: AbortSignal) {
    return this.list<QualityIssueSummary>('/quality/issues', { cursor, signal })
  }

  private async list<T>(
    path: string,
    options: {
      cursor?: string
      limit?: number
      parameters?: Record<string, string>
      signal?: AbortSignal
    },
  ): Promise<QualityListResponse<T>> {
    const limit = options.limit ?? 25
    const parameters = new URLSearchParams({
      limit: String(limit),
      ...options.parameters,
    })
    if (options.cursor) parameters.set('cursor', options.cursor)
    const value = await this.client.request<QualityListResponse<T>>(
      `${path}?${parameters.toString()}`,
      { cache: 'no-store', signal: options.signal },
    )
    assertList(value, limit)
    return value
  }
}

function assertCapability(value: QualityCapability): void {
  const ids = new Set([
    'read_access',
    'profile_readiness',
    'rule_authoring',
    'activation',
    'manual_execution',
    'scheduling',
    'operations',
  ])
  if (
    !value
    || value.contract_version !== 'QUALITY_CAPABILITY_V1'
    || !validDate(value.observed_at)
    || !validDate(value.valid_until)
    || !validCacheScope(value.cache_scope)
    || !Array.isArray(value.axes)
    || value.axes.length !== ids.size
    || new Set(value.axes.map((axis) => axis.id)).size !== ids.size
    || value.axes.some((axis) => (
      !ids.has(axis.id)
      || !['AVAILABLE', 'DENIED', 'UNAVAILABLE'].includes(axis.state)
    ))
  ) {
    throw new Error('품질 capability 계약이 올바르지 않습니다.')
  }
  const observedAt = Date.parse(value.observed_at)
  const validUntil = Date.parse(value.valid_until)
  if (validUntil <= observedAt || validUntil - observedAt > 30_000) {
    throw new Error('품질 capability 권한 lease가 허용 범위를 벗어났습니다.')
  }
}

function assertOverview(value: QualityOverview): void {
  const counts = [
    value?.active_rule_set_count,
    value?.evaluated_rule_set_count,
    value?.unknown_rule_set_count,
    value?.passed_count,
    value?.advisory_failed_count,
    value?.blocking_failed_count,
    value?.evaluated_rule_count,
  ]
  if (
    !value
    || !['AVAILABLE', 'PARTIAL', 'UNAVAILABLE'].includes(value.availability)
    || !['CURRENT', 'STALE', 'UNKNOWN'].includes(value.freshness)
    || !['PASS', 'WARN', 'FAIL', 'UNKNOWN'].includes(value.overall_state)
    || !validDate(value.as_of)
    || !validDate(value.authorization_valid_until)
    || counts.some((count) => !Number.isSafeInteger(count) || count < 0)
    || !validBasisPoints(value.score_basis_points)
    || !validBasisPoints(value.coverage_basis_points)
    || !Array.isArray(value.trend)
    || value.trend.length > 90
    || value.trend.some((point) => (
      !validDate(point.bucket_start)
      || !validBasisPoints(point.score_basis_points)
      || [point.passed_count, point.advisory_failed_count, point.blocking_failed_count, point.evaluated_rule_count]
        .some((count) => !Number.isSafeInteger(count) || count < 0)
    ))
  ) {
    throw new Error('품질 현황 계약이 올바르지 않습니다.')
  }
}

function assertList<T>(value: QualityListResponse<T>, requestedLimit: number): void {
  if (
    !value
    || !Array.isArray(value.items)
    || value.items.length > requestedLimit
    || !value.page
    || value.page.limit !== requestedLimit
    || (
      value.page.next_cursor !== null
      && (
        typeof value.page.next_cursor !== 'string'
        || !value.page.next_cursor
        || value.page.next_cursor.length > 2_000
      )
    )
    || !validCacheScope(value.cache_scope)
    || !validDate(value.observed_at)
    || !validDate(value.authorization_valid_until)
  ) {
    throw new Error('품질 목록 계약이 올바르지 않습니다.')
  }
}

function validBasisPoints(value: number | null): boolean {
  return value === null || (Number.isInteger(value) && value >= 0 && value <= 10_000)
}

function validDate(value: string): boolean {
  return typeof value === 'string' && Number.isFinite(Date.parse(value))
}

function validCacheScope(value: string): boolean {
  return typeof value === 'string' && /^[0-9a-f]{64}$/.test(value)
}
