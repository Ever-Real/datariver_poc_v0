import type { ApiClient } from '../../api/client'
import type {
  QualityAsset,
  QualityAssetAuthoring,
  QualityAssetDetailResponse,
  QualityAssetSummaryBatchResponse,
  QualityCapability,
  QualityCommonRuleTemplateCreateRequest,
  QualityCommonRuleTemplateCreateResponse,
  QualityCommonRuleTemplateDetail,
  QualityCommonRuleTemplateListResponse,
  QualityExpectationResult,
  QualityIssueSummary,
  QualityListResponse,
  QualityManualRunResponse,
  QualityOverview,
  QualityResourceResponse,
  QualityRuleBatchProposalRequest,
  QualityRuleBatchProposalResponse,
  QualityRuleDefinitionCatalog,
  QualityRuleReviewRequest,
  QualityRuleSetDetail,
  QualityRuleSetSummary,
  QualityRuleVersionCommandResponse,
  QualityRunSummary,
  QualityAuthoringField,
} from '../../api/types'
import type { QualityDashboard } from './qualityDashboardTypes'
import type {
  QualityAssetFieldWorkspace,
  QualityFieldWorkspace,
  QualityTargetedRuleProposalRequest,
  QualityTemplateMappingRequest,
} from './qualityFieldTypes'

export interface QualitySecurityBoundary {
  workspaceId: string
  subjectId: string
  securityEpoch: number
  authorizationRevision: number
  cacheScope: string
}

export type QualityAssetPreviewResponse = QualityListResponse<QualityAsset>

export type QualityResource =
  | 'overview'
  | 'dashboard'
  | 'assets'
  | 'asset-detail'
  | 'asset-workspace'
  | 'field-workspace'
  | 'asset-summaries'
  | 'common-rule-templates'
  | 'common-rule-template-detail'
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

  async dashboard(
    expectedCacheScope: string,
    signal?: AbortSignal,
  ): Promise<QualityDashboard> {
    const value = await this.client.request<QualityDashboard>('/quality/dashboard', {
      cache: 'no-store',
      signal,
    })
    if (!validDashboard(value, expectedCacheScope)) {
      throw new Error('품질 대시보드 계약이 올바르지 않습니다.')
    }
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

  assets(
    cursor?: string,
    signal?: AbortSignal,
    filters?: {
      query?: string
      platform?: string
      database?: string
      schema?: string
      limit?: number
    },
  ) {
    return this.list<QualityAsset>('/quality/assets', {
      cursor,
      signal,
      limit: filters?.limit,
      parameters: {
        ...(filters?.query ? { q: filters.query } : {}),
        ...(filters?.platform ? { platform: filters.platform } : {}),
        ...(filters?.database ? { database: filters.database } : {}),
        ...(filters?.schema ? { schema: filters.schema } : {}),
      },
    })
  }

  async assetPreview(
    cursor: string | undefined,
    signal: AbortSignal | undefined,
    filters: {
      query?: string
      platform?: string
      database?: string
      schema?: string
      limit: number
    },
  ): Promise<QualityAssetPreviewResponse> {
    const value = await this.assets(cursor, signal, filters)
    if (!cursor && (
      !Number.isSafeInteger(value.page.total_count)
      || Number(value.page.total_count) < value.items.length
    )) {
      throw new Error('인가된 품질 대상 전체 건수를 확인할 수 없습니다.')
    }
    if (cursor && value.page.total_count != null) {
      throw new Error('후속 품질 미리보기 페이지가 전체 건수를 다시 계산했습니다.')
    }
    return value
  }

  async assetSummaries(
    assetIds: readonly string[],
    expectedCacheScope: string,
    signal?: AbortSignal,
  ): Promise<QualityAssetSummaryBatchResponse> {
    const value = await this.client.request<QualityAssetSummaryBatchResponse>(
      '/quality/assets/summary-batch',
      {
        method: 'POST',
        cache: 'no-store',
        signal,
        body: JSON.stringify({ asset_ids: assetIds }),
      },
    )
    if (
      !validReadMetadata(value, expectedCacheScope)
      || !Array.isArray(value.items)
      || value.items.length > assetIds.length
      || value.items.some((item) => !assetIds.includes(item.asset_id))
    ) {
      throw new Error('검색 결과의 품질 요약 계약이 올바르지 않습니다.')
    }
    return value
  }

  async asset(
    assetId: string,
    expectedCacheScope: string,
    signal?: AbortSignal,
  ): Promise<QualityAssetDetailResponse> {
    const value = await this.client.request<QualityAssetDetailResponse>(
      `/quality/assets/${encodeURIComponent(assetId)}`,
      { cache: 'no-store', signal },
    )
    if (
      value?.item?.asset_id !== assetId
      || value.cache_scope !== expectedCacheScope
      || !validDate(value.observed_at)
      || !validDate(value.authorization_valid_until)
      || !validAuthoring(value)
    ) {
      throw new Error('선택한 품질 자산의 작성 계약을 확인할 수 없습니다.')
    }
    return value
  }

  async assetWorkspace(
    assetId: string,
    expectedCacheScope: string,
    signal?: AbortSignal,
  ): Promise<QualityAssetFieldWorkspace> {
    const value = await this.client.request<QualityResourceResponse<QualityAssetFieldWorkspace>>(
      `/quality/assets/${encodeURIComponent(assetId)}/workspace?days=30`,
      { cache: 'no-store', signal },
    )
    if (
      !validReadMetadata(value, expectedCacheScope)
      || value.item?.asset?.asset_id !== assetId
      || !Array.isArray(value.item.rule_sets)
      || value.item.rule_sets.length > 50
      || !Array.isArray(value.item.runs)
      || value.item.runs.length > 50
      || !Array.isArray(value.item.trend)
      || value.item.trend.length > 90
      || !validWorkspaceAuthoring(value.item)
      || !validScorePolicy(value.item.score_policy)
      || !Array.isArray(value.item.fields)
      || value.item.fields.length > 1_000
      || new Set(value.item.fields.map((field) => field.field_identifier)).size
        !== value.item.fields.length
      || value.item.fields.some((field) => !validAssetField(field))
    ) {
      throw new Error('자산별 품질 현황 계약이 올바르지 않습니다.')
    }
    return value.item
  }

  async fieldWorkspace(
    assetId: string,
    fieldIdentifier: string,
    expectedCacheScope: string,
    signal?: AbortSignal,
  ): Promise<QualityFieldWorkspace> {
    const value = await this.client.request<QualityResourceResponse<QualityFieldWorkspace>>(
      `/quality/assets/${encodeURIComponent(assetId)}/fields/${encodeURIComponent(fieldIdentifier)}/workspace?days=30`,
      { cache: 'no-store', signal },
    )
    if (
      !validReadMetadata(value, expectedCacheScope)
      || value.item?.asset_id !== assetId
      || value.item?.field?.field_identifier !== fieldIdentifier
      || !validAuthoringField(value.item.field)
      || !validScorePolicy(value.item.score_policy)
      || !Array.isArray(value.item.rules)
      || value.item.rules.length > 200
      || value.item.rules.some((rule) => (
        !validIdentifier(rule.rule_definition_id)
        || !validIdentifier(rule.rule_set_id)
        || !validIdentifier(rule.version_id)
        || !['PROPOSED', 'APPROVED', 'ACTIVE'].includes(rule.version_state)
        || !['NOT_NULL', 'RANGE'].includes(rule.kind)
        || !['BLOCKING', 'ADVISORY'].includes(rule.severity)
      ))
      || !Array.isArray(value.item.runs)
      || value.item.runs.length > 50
      || value.item.runs.some((run) => !validFieldRun(run))
      || !Array.isArray(value.item.trend)
      || value.item.trend.length > 90
      || value.item.trend.some((point) => !validTrendPoint(point))
    ) {
      throw new Error('필드별 품질 현황 계약이 올바르지 않습니다.')
    }
    return value.item
  }

  async commonRuleTemplates(
    expectedCacheScope: string,
    signal?: AbortSignal,
  ): Promise<QualityCommonRuleTemplateListResponse> {
    const value = await this.client.request<QualityCommonRuleTemplateListResponse>(
      '/quality/common-rule-templates',
      { cache: 'no-store', signal },
    )
    if (
      !validReadMetadata(value, expectedCacheScope)
      || !Array.isArray(value.items)
      || value.items.length > 100
      || value.items.some((item) => !validCommonTemplate(item))
    ) {
      throw new Error('공통 룰셋 목록 계약이 올바르지 않습니다.')
    }
    return value
  }

  async commonRuleTemplate(
    templateId: string,
    expectedCacheScope: string,
    signal?: AbortSignal,
  ): Promise<QualityCommonRuleTemplateDetail> {
    const value = await this.client.request<QualityResourceResponse<QualityCommonRuleTemplateDetail>>(
      `/quality/common-rule-templates/${encodeURIComponent(templateId)}`,
      { cache: 'no-store', signal },
    )
    if (
      !validReadMetadata(value, expectedCacheScope)
      || value.item?.template?.template_id !== templateId
      || !validCommonTemplate(value.item.template)
      || !Array.isArray(value.item.mappings)
      || value.item.mappings.length > 500
    ) {
      throw new Error('공통 룰셋 상세 계약이 올바르지 않습니다.')
    }
    return value.item
  }

  async createCommonRuleTemplate(
    payload: QualityCommonRuleTemplateCreateRequest,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<QualityCommonRuleTemplateCreateResponse> {
    const value = await this.client.request<QualityCommonRuleTemplateCreateResponse>(
      '/quality/common-rule-templates',
      {
        method: 'POST',
        cache: 'no-store',
        signal,
        idempotencyKey,
        body: JSON.stringify(payload),
      },
    )
    if (!validIdentifier(value?.template_id) || typeof value.replayed !== 'boolean') {
      throw new Error('공통 룰셋 생성 응답이 올바르지 않습니다.')
    }
    return value
  }

  async mapCommonRuleTemplate(
    templateId: string,
    targets: string[] | QualityTemplateMappingRequest,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<QualityRuleBatchProposalResponse> {
    const assetIds = Array.isArray(targets)
      ? targets
      : targets.targets.map((target) => target.asset_id)
    const value = await this.client.request<QualityRuleBatchProposalResponse>(
      `/quality/common-rule-templates/${encodeURIComponent(templateId)}/mappings`,
      {
        method: 'POST',
        cache: 'no-store',
        signal,
        idempotencyKey,
        body: JSON.stringify(Array.isArray(targets) ? { asset_ids: targets } : targets),
      },
    )
    assertProposal(value, assetIds)
    return value
  }

  ruleSets(cursor?: string, signal?: AbortSignal) {
    return this.list<QualityRuleSetSummary>('/quality/rule-sets', { cursor, signal })
  }

  async proposeRuleSets(
    payload: QualityRuleBatchProposalRequest,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<QualityRuleBatchProposalResponse> {
    const value = await this.client.request<QualityRuleBatchProposalResponse>(
      '/quality/rule-sets',
      {
        method: 'POST',
        cache: 'no-store',
        signal,
        idempotencyKey,
        body: JSON.stringify(payload),
      },
    )
    assertProposal(value, payload.asset_ids)
    return value
  }

  async proposeTargetedRuleSets(
    payload: QualityTargetedRuleProposalRequest,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<QualityRuleBatchProposalResponse> {
    const value = await this.client.request<QualityRuleBatchProposalResponse>(
      '/quality/rule-sets',
      {
        method: 'POST',
        cache: 'no-store',
        signal,
        idempotencyKey,
        body: JSON.stringify(payload),
      },
    )
    assertProposal(value, payload.targets.map((target) => target.asset_id))
    return value
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

  async reviewRuleVersion(
    ruleSetId: string,
    versionId: string,
    expectedVersion: number,
    payload: QualityRuleReviewRequest,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<QualityRuleVersionCommandResponse> {
    return this.ruleVersionCommand(
      `/quality/rule-sets/${encodeURIComponent(ruleSetId)}/versions/${encodeURIComponent(versionId)}/reviews`,
      ruleSetId,
      versionId,
      expectedVersion,
      idempotencyKey,
      signal,
      payload,
    )
  }

  async activateRuleVersion(
    ruleSetId: string,
    versionId: string,
    expectedVersion: number,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<QualityRuleVersionCommandResponse> {
    return this.ruleVersionCommand(
      `/quality/rule-sets/${encodeURIComponent(ruleSetId)}/versions/${encodeURIComponent(versionId)}/activations`,
      ruleSetId,
      versionId,
      expectedVersion,
      idempotencyKey,
      signal,
    )
  }

  async requestManualRun(
    ruleSetId: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<QualityManualRunResponse> {
    const value = await this.client.request<QualityManualRunResponse>('/quality/runs', {
      method: 'POST',
      cache: 'no-store',
      signal,
      idempotencyKey,
      body: JSON.stringify({ rule_set_id: ruleSetId }),
    })
    if (
      !validIdentifier(value?.run_id)
      || ![
        'QUEUED',
        'RUNNING',
        'RETRY_WAIT',
        'CANCEL_REQUESTED',
        'SUCCEEDED',
        'FAILED',
        'STALE',
        'CANCELLED',
      ].includes(value.state)
      || !validDate(value.created_at)
      || typeof value.replayed !== 'boolean'
    ) {
      throw new Error('품질 수동 실행 응답이 올바르지 않습니다.')
    }
    return value
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

  private async ruleVersionCommand(
    path: string,
    ruleSetId: string,
    versionId: string,
    expectedVersion: number,
    idempotencyKey: string,
    signal?: AbortSignal,
    payload?: QualityRuleReviewRequest,
  ): Promise<QualityRuleVersionCommandResponse> {
    const value = await this.client.request<QualityRuleVersionCommandResponse>(path, {
      method: 'POST',
      cache: 'no-store',
      signal,
      idempotencyKey,
      ifMatch: `"${expectedVersion}"`,
      body: payload ? JSON.stringify(payload) : undefined,
    })
    if (
      value?.rule_set_id !== ruleSetId
      || value.version_id !== versionId
      || !['PROPOSED', 'APPROVED', 'REJECTED', 'ACTIVE', 'SUPERSEDED', 'REVOKED']
        .includes(value.state)
      || !Number.isSafeInteger(value.version)
      || value.version < 1
    ) {
      throw new Error('품질 Rule 버전 명령 응답이 올바르지 않습니다.')
    }
    return value
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
    'review',
    'activation',
    'manual_execution',
    'scheduling',
    'operations',
  ])
  if (
    !value
    || value.contract_version !== 'QUALITY_CAPABILITY_V2'
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

function validDashboard(
  value: QualityDashboard,
  expectedCacheScope: string,
): boolean {
  const indicatorIds = new Set(['ACCURACY', 'COMPLETENESS', 'TIMELINESS'])
  return Boolean(
    value
    && value.contract_version === 'QUALITY_DASHBOARD_V1'
    && validReadMetadata(value, expectedCacheScope)
    && validDate(value.as_of)
    && [
      value.schema_count,
      value.table_count,
      value.active_rule_set_count,
      value.common_rule_template_count,
      value.covered_table_count,
    ].every(nonnegative)
    && validBasisPoints(value.table_coverage_basis_points)
    && Array.isArray(value.managed_rule_sets)
    && value.managed_rule_sets.length === indicatorIds.size
    && new Set(value.managed_rule_sets.map((item) => item.indicator_id)).size === indicatorIds.size
    && value.managed_rule_sets.every((item) => (
      indicatorIds.has(item.indicator_id)
      && item.contract_version === 'QUALITY_MANAGED_INDICATORS_V1'
      && ['FIELD', 'TABLE'].includes(item.target_grain)
      && Array.isArray(item.rule_kinds)
      && item.rule_kinds.every((kind) => ['NOT_NULL', 'RANGE', 'REGEX'].includes(kind))
      && Boolean(item.name)
      && Boolean(item.definition)
      && Boolean(item.calculation)
    ))
    && Array.isArray(value.schemas)
    && value.schemas.length <= 500
    && value.schemas.every((schema) => (
      validCacheScope(schema.schema_id)
      && nonnegative(schema.table_count)
      && nonnegative(schema.covered_table_count)
      && Array.isArray(schema.indicators)
      && schema.indicators.length === indicatorIds.size
      && new Set(schema.indicators.map((item) => item.indicator_id)).size === indicatorIds.size
      && schema.indicators.every((indicator) => (
        indicatorIds.has(indicator.indicator_id)
        && [
          indicator.counted_target_count,
          indicator.target_count,
          indicator.risk_count,
          indicator.evaluated_value_count,
        ].every(nonnegative)
        && validBasisPoints(indicator.coverage_basis_points)
        && validBasisPoints(indicator.score_basis_points)
        && ['PASS', 'WARN', 'FAIL', 'UNKNOWN'].includes(indicator.outcome)
        && ['FACTS_ONLY', 'LLM_GENERATED', 'UNAVAILABLE'].includes(indicator.report_state)
        && typeof indicator.report_summary === 'string'
        && indicator.report_summary.length > 0
        && indicator.report_summary.length <= 2_000
        && Array.isArray(indicator.risks)
        && indicator.risks.length <= 50
        && indicator.risks.every((risk) => (
          validCacheScope(risk.risk_id)
          && validIdentifier(risk.asset_id)
          && Boolean(risk.asset_name)
          && ['BLOCKING', 'ADVISORY'].includes(risk.severity)
          && ['ADVISORY_FAIL', 'BLOCKING_FAIL'].includes(risk.outcome)
          && validBasisPoints(risk.score_basis_points)
          && (risk.evaluated_count === null || nonnegative(risk.evaluated_count))
          && (risk.failed_count === null || nonnegative(risk.failed_count))
          && (risk.observed_at === null || validDate(risk.observed_at))
          && Boolean(risk.detail)
        ))
      ))
    ))
    && typeof value.schemas_truncated === 'boolean',
  )
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

function validAuthoring(value: QualityAssetDetailResponse): boolean {
  return validAuthoringDocument(value.authoring)
}

function validWorkspaceAuthoring(value: { authoring?: QualityAssetAuthoring }): boolean {
  return validAuthoringDocument(value.authoring)
}

function validAuthoringDocument(authoring: QualityAssetAuthoring | undefined): boolean {
  const logicalTypes = new Set(['STRING', 'INTEGER', 'DECIMAL', 'DATE', 'TIMESTAMP', 'BOOLEAN', 'OTHER'])
  if (
    !authoring
    || !['READY', 'UNAVAILABLE'].includes(authoring.state)
    || typeof authoring.source_version !== 'string'
    || !authoring.source_version
    || (
      authoring.schema_hash !== null
      && !/^[0-9a-f]{64}$/.test(authoring.schema_hash)
    )
    || !Array.isArray(authoring.fields)
    || authoring.fields.length > 10_000
    || new Set(authoring.fields.map((field) => field.field_identifier)).size !== authoring.fields.length
    || authoring.fields.some((field) => !validAuthoringField(field, logicalTypes))
  ) {
    return false
  }
  return authoring.state === 'READY'
    ? authoring.schema_hash !== null && authoring.fields.length > 0
    : authoring.fields.length === 0 && typeof authoring.reason_code === 'string'
}

function validAuthoringField(
  field: QualityAuthoringField,
  logicalTypes = new Set(['STRING', 'INTEGER', 'DECIMAL', 'DATE', 'TIMESTAMP', 'BOOLEAN', 'OTHER']),
): boolean {
  return validIdentifier(field.field_identifier)
    && validIdentifier(field.display_path)
    && logicalTypes.has(field.logical_type)
    && Array.isArray(field.supported_rule_kinds)
    && field.supported_rule_kinds.length <= 2
    && new Set(field.supported_rule_kinds).size === field.supported_rule_kinds.length
    && field.supported_rule_kinds.every((kind) => ['NOT_NULL', 'RANGE'].includes(kind))
}

function validAssetField(field: QualityAssetFieldWorkspace['fields'][number]): boolean {
  const counts = [
      field.configured_rule_count,
      field.active_rule_count,
      field.evaluated_rule_count,
      field.passed_count,
      field.advisory_failed_count,
      field.blocking_failed_count,
    ]
  return validAuthoringField(field)
    && counts.every(nonnegative)
    && field.active_rule_count <= field.configured_rule_count
    && field.evaluated_rule_count === (
      field.passed_count + field.advisory_failed_count + field.blocking_failed_count
    )
    && validBasisPoints(field.latest_score_basis_points)
    && ['PASS', 'WARN', 'FAIL', 'UNKNOWN'].includes(field.latest_quality_outcome)
    && (field.latest_evaluated_at === null || validDate(field.latest_evaluated_at))
}

function validScorePolicy(value: QualityAssetFieldWorkspace['score_policy'] | undefined): boolean {
  return Boolean(
    value
    && value.policy_id === 'UNWEIGHTED_RULE_PASS_RATE_V1'
    && value.policy_version === 1
    && validCacheScope(value.policy_hash)
    && value.calculation === 'passed / (passed + advisory_failed + blocking_failed)'
    && value.pass_condition === 'evaluated > 0 and advisory_failed = 0 and blocking_failed = 0'
    && value.warn_condition === 'blocking_failed = 0 and advisory_failed > 0'
    && value.fail_condition === 'blocking_failed > 0'
    && value.unknown_condition === 'evaluated = 0',
  )
}

function validFieldRun(run: QualityFieldWorkspace['runs'][number]): boolean {
  const counts = [
    run.passed_count,
    run.advisory_failed_count,
    run.blocking_failed_count,
    run.evaluated_value_count,
    run.missing_count,
    run.unexpected_count,
  ]
  return validIdentifier(run.run_id)
    && validIdentifier(run.rule_set_id)
    && validIdentifier(run.rule_set_name)
    && [
      'QUEUED',
      'RUNNING',
      'RETRY_WAIT',
      'CANCEL_REQUESTED',
      'SUCCEEDED',
      'FAILED',
      'STALE',
      'CANCELLED',
    ].includes(run.state)
    && ['PASS', 'WARN', 'FAIL', 'UNKNOWN'].includes(run.run_quality_outcome)
    && ['PASS', 'WARN', 'FAIL', 'UNKNOWN'].includes(run.field_quality_outcome)
    && validBasisPoints(run.score_basis_points)
    && counts.every(nonnegative)
    && validDate(run.created_at)
    && (run.completed_at === null || validDate(run.completed_at))
    && (run.failure_code === null || validIdentifier(run.failure_code))
}

function validTrendPoint(point: QualityFieldWorkspace['trend'][number]): boolean {
  return validDate(point.bucket_start)
    && validBasisPoints(point.score_basis_points)
    && [
      point.passed_count,
      point.advisory_failed_count,
      point.blocking_failed_count,
      point.evaluated_rule_count,
    ].every(nonnegative)
    && point.evaluated_rule_count === (
      point.passed_count + point.advisory_failed_count + point.blocking_failed_count
    )
}

function validReadMetadata(
  value: {
    cache_scope?: string
    observed_at?: string
    authorization_valid_until?: string
  } | null | undefined,
  expectedCacheScope: string,
): boolean {
  return Boolean(
    value
    && value.cache_scope === expectedCacheScope
    && validDate(value.observed_at ?? '')
    && validDate(value.authorization_valid_until ?? ''),
  )
}

function validCommonTemplate(
  value: {
    template_id?: string
    name?: string
    rules?: Array<{
      field_identifier?: string
      kind?: string
      severity?: string
      parameters?: unknown
    }>
    mapping_count?: number
    created_at?: string
    updated_at?: string
  } | null | undefined,
): boolean {
  return Boolean(
    value
    && validIdentifier(value.template_id ?? '')
    && validIdentifier(value.name ?? '')
    && Array.isArray(value.rules)
    && value.rules.length > 0
    && value.rules.length <= 100
    && value.rules.every((rule) => (
      validIdentifier(rule.field_identifier ?? '')
      && ['NOT_NULL', 'RANGE'].includes(rule.kind ?? '')
      && ['BLOCKING', 'ADVISORY'].includes(rule.severity ?? '')
      && typeof rule.parameters === 'object'
      && rule.parameters !== null
      && !Array.isArray(rule.parameters)
    ))
    && Number.isSafeInteger(value.mapping_count)
    && (value.mapping_count ?? -1) >= 0
    && validDate(value.created_at ?? '')
    && validDate(value.updated_at ?? ''),
  )
}

function assertProposal(
  value: QualityRuleBatchProposalResponse,
  requestedAssetIds: readonly string[],
): void {
  if (
    !value
    || typeof value.replayed !== 'boolean'
    || !Array.isArray(value.items)
    || value.items.length !== requestedAssetIds.length
    || new Set(value.items.map((item) => item.asset_id)).size !== value.items.length
    || value.items.some((item) => (
      !requestedAssetIds.includes(item.asset_id)
      || !validIdentifier(item.rule_set_id)
      || !validIdentifier(item.version_id)
      || !Number.isSafeInteger(item.version)
      || item.version < 1
    ))
  ) {
    throw new Error('품질 Rule 일괄 제안 응답이 올바르지 않습니다.')
  }
}

function validIdentifier(value: string): boolean {
  return typeof value === 'string' && value.length > 0 && value.length <= 255
}

function validBasisPoints(value: number | null): boolean {
  return value === null || (Number.isInteger(value) && value >= 0 && value <= 10_000)
}

function nonnegative(value: unknown): boolean {
  return Number.isSafeInteger(value) && Number(value) >= 0
}

function validDate(value: string): boolean {
  return typeof value === 'string' && Number.isFinite(Date.parse(value))
}

function validCacheScope(value: string): boolean {
  return typeof value === 'string' && /^[0-9a-f]{64}$/.test(value)
}
