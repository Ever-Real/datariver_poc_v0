import { describe, expect, it, vi } from 'vitest'
import { QualityApi } from './qualityApi'

describe('QualityApi authorization contracts', () => {
  it('rejects a capability lease longer than 30 seconds', async () => {
    const api = new QualityApi({
      request: vi.fn().mockResolvedValue({
        contract_version: 'QUALITY_CAPABILITY_V2',
        observed_at: '2026-07-30T00:00:00Z',
        valid_until: '2026-07-30T00:00:31Z',
        cache_scope: cacheScope,
        axes: capabilityAxes,
      }),
    })

    await expect(api.capability()).rejects.toThrow('lease')
  })

  it('rejects an exact Run response bound to another permission cache scope', async () => {
    const api = new QualityApi({
      request: vi.fn().mockResolvedValue({
        item: {
          run_id: 'run-one',
        },
        cache_scope: 'b'.repeat(64),
        observed_at: '2026-07-30T00:00:00Z',
        authorization_valid_until: '2026-07-30T00:00:30Z',
      }),
    })

    await expect(api.run('run-one', cacheScope)).rejects.toThrow('현재 상태')
  })

  it('binds asset authoring detail to the expected cache scope and server field allowlist', async () => {
    const request = vi.fn().mockResolvedValue({
      item: { asset_id: 'asset-one' },
      authoring: {
        state: 'READY',
        reason_code: null,
        source_version: 'source-version-one',
        schema_hash: 'c'.repeat(64),
        fields: [{
          field_identifier: 'orders.amount',
          display_path: 'orders.amount',
          logical_type: 'DECIMAL',
          supported_rule_kinds: ['NOT_NULL', 'RANGE'],
        }],
      },
      cache_scope: cacheScope,
      observed_at: '2026-07-30T00:00:00Z',
      authorization_valid_until: '2026-07-30T00:00:30Z',
    })
    const api = new QualityApi({ request })

    const result = await api.asset('asset-one', cacheScope)

    expect(result.authoring.fields[0]?.field_identifier).toBe('orders.amount')
    expect(request).toHaveBeenCalledWith('/quality/assets/asset-one', {
      cache: 'no-store',
      signal: undefined,
    })
  })

  it('sends one atomic batch proposal with its idempotency boundary', async () => {
    const request = vi.fn().mockResolvedValue({
      items: [
        { asset_id: 'asset-one', rule_set_id: 'rules-one', version_id: 'version-one', version: 1 },
        { asset_id: 'asset-two', rule_set_id: 'rules-two', version_id: 'version-two', version: 1 },
      ],
      replayed: false,
    })
    const api = new QualityApi({ request })
    const payload = {
      name_prefix: '핵심 주문',
      asset_ids: ['asset-one', 'asset-two'],
      rules: [{
        field_identifier: 'orders.amount',
        kind: 'RANGE' as const,
        severity: 'BLOCKING' as const,
        parameters: {
          value_type: 'DECIMAL',
          min_value: '0',
          max_value: '100',
          inclusive_min: true,
          inclusive_max: true,
        },
      }],
    }

    await api.proposeRuleSets(payload, 'quality-proposal-key')

    expect(request).toHaveBeenCalledTimes(1)
    expect(request).toHaveBeenCalledWith('/quality/rule-sets', {
      method: 'POST',
      cache: 'no-store',
      signal: undefined,
      idempotencyKey: 'quality-proposal-key',
      body: JSON.stringify(payload),
    })
  })

  it('loads one permission-bound quality summary batch for catalog results', async () => {
    const request = vi.fn().mockResolvedValue({
      items: [{
        asset_id: 'asset-one',
        name: 'orders',
        classification: 'INTERNAL',
        lifecycle: 'ACTIVE',
        profile_readiness: 'READY',
        profile_observed_at: '2026-07-30T00:00:00Z',
        active_rule_set_count: 1,
        latest_run_state: 'SUCCEEDED',
        latest_quality_outcome: 'PASS',
        latest_score_basis_points: 9_875,
      }],
      cache_scope: cacheScope,
      observed_at: '2026-07-30T00:00:00Z',
      authorization_valid_until: '2026-07-30T00:00:30Z',
    })
    const api = new QualityApi({ request })

    const result = await api.assetSummaries(['asset-one'], cacheScope)

    expect(result.items[0]?.latest_score_basis_points).toBe(9_875)
    expect(request).toHaveBeenCalledWith('/quality/assets/summary-batch', {
      method: 'POST',
      cache: 'no-store',
      signal: undefined,
      body: JSON.stringify({ asset_ids: ['asset-one'] }),
    })
  })

  it('accepts only a permission-bound three-indicator dashboard contract', async () => {
    const request = vi.fn().mockResolvedValue(dashboard())
    const api = new QualityApi({ request })

    const result = await api.dashboard(cacheScope)

    expect(result.schemas[0]?.indicators.map((item) => item.indicator_id)).toEqual([
      'ACCURACY',
      'COMPLETENESS',
      'TIMELINESS',
    ])
    expect(request).toHaveBeenCalledWith('/quality/dashboard', {
      cache: 'no-store',
      signal: undefined,
    })
  })

  it('creates and maps a reusable common rule through bounded batch routes', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({ template_id: 'template-one', replayed: false })
      .mockResolvedValueOnce({
        items: [
          { asset_id: 'asset-one', rule_set_id: 'rules-one', version_id: 'version-one', version: 1 },
          { asset_id: 'asset-two', rule_set_id: 'rules-two', version_id: 'version-two', version: 1 },
        ],
        replayed: false,
      })
    const api = new QualityApi({ request })
    const template = {
      name: 'Not null',
      rules: [{
        field_identifier: 'email',
        kind: 'NOT_NULL' as const,
        severity: 'BLOCKING' as const,
        parameters: {},
      }],
    }

    await api.createCommonRuleTemplate(template, 'template-key')
    await api.mapCommonRuleTemplate(
      'template-one',
      ['asset-one', 'asset-two'],
      'mapping-key',
    )

    expect(request.mock.calls[0]).toEqual([
      '/quality/common-rule-templates',
      expect.objectContaining({
        method: 'POST',
        idempotencyKey: 'template-key',
        body: JSON.stringify(template),
      }),
    ])
    expect(request.mock.calls[1]).toEqual([
      '/quality/common-rule-templates/template-one/mappings',
      expect.objectContaining({
        method: 'POST',
        idempotencyKey: 'mapping-key',
        body: JSON.stringify({ asset_ids: ['asset-one', 'asset-two'] }),
      }),
    ])
  })

  it('binds the authorized asset cursor to exact metadata scope filters', async () => {
    const request = vi.fn().mockResolvedValue({
      items: [],
      page: { next_cursor: null, limit: 25 },
      cache_scope: cacheScope,
      observed_at: '2026-07-30T00:00:00Z',
      authorization_valid_until: '2026-07-30T00:00:30Z',
    })
    const api = new QualityApi({ request })

    await api.assets(undefined, undefined, {
      query: 'event',
      platform: 'postgres',
      database: 'analytics',
      schema: 'public',
    })

    expect(request).toHaveBeenCalledWith(
      '/quality/assets?limit=25&q=event&platform=postgres&database=analytics&schema=public',
      { cache: 'no-store', signal: undefined },
    )
  })

  it('sends server-scoped field targets and parameter overrides as one atomic mapping', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({
        items: [
          { asset_id: 'asset-one', rule_set_id: 'rules-one', version_id: 'version-one', version: 1 },
        ],
        replayed: false,
      })
      .mockResolvedValueOnce({
        items: [
          { asset_id: 'asset-one', rule_set_id: 'rules-two', version_id: 'version-two', version: 1 },
        ],
        replayed: false,
      })
    const api = new QualityApi({ request })
    const proposal = {
      name_prefix: '금액 품질',
      targets: [{
        asset_id: 'asset-one',
        rules: [{
          field_identifier: 'orders.amount',
          kind: 'RANGE' as const,
          severity: 'ADVISORY' as const,
          parameters: {
            value_type: 'DECIMAL',
            min_value: '0',
            max_value: '1000',
            inclusive_min: true,
            inclusive_max: true,
          },
        }],
      }],
    }
    const mapping = {
      targets: [{
        asset_id: 'asset-one',
        bindings: [{
          template_rule_ordinal: 2,
          field_identifier: 'orders.amount',
          parameters_override: proposal.targets[0]?.rules[0]?.parameters,
        }],
      }],
    }

    await api.proposeTargetedRuleSets(proposal, 'targeted-rule-key')
    await api.mapCommonRuleTemplate('template-one', mapping, 'targeted-template-key')

    expect(request.mock.calls[0]).toEqual([
      '/quality/rule-sets',
      expect.objectContaining({
        method: 'POST',
        idempotencyKey: 'targeted-rule-key',
        body: JSON.stringify(proposal),
      }),
    ])
    expect(request.mock.calls[1]).toEqual([
      '/quality/common-rule-templates/template-one/mappings',
      expect.objectContaining({
        method: 'POST',
        idempotencyKey: 'targeted-template-key',
        body: JSON.stringify(mapping),
      }),
    ])
  })

  it('accepts a field workspace only when the V1 policy and field identity are bound', async () => {
    const request = vi.fn().mockResolvedValue({
      item: {
        asset_id: 'asset-one',
        field: {
          field_identifier: 'orders.amount',
          display_path: 'orders.amount',
          logical_type: 'DECIMAL',
          supported_rule_kinds: ['NOT_NULL', 'RANGE'],
        },
        rules: [],
        runs: [],
        trend: [],
        score_policy: scorePolicy(),
      },
      cache_scope: cacheScope,
      observed_at: '2026-07-30T00:00:00Z',
      authorization_valid_until: '2026-07-30T00:00:30Z',
    })
    const api = new QualityApi({ request })

    const result = await api.fieldWorkspace('asset-one', 'orders.amount', cacheScope)

    expect(result.score_policy.warn_condition).toContain('advisory_failed > 0')
    expect(request).toHaveBeenCalledWith(
      '/quality/assets/asset-one/fields/orders.amount/workspace?days=30',
      { cache: 'no-store', signal: undefined },
    )
  })

  it('uses plural lifecycle routes with quoted version preconditions', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({
        rule_set_id: 'rules-one',
        version_id: 'version-one',
        state: 'APPROVED',
        version: 3,
      })
      .mockResolvedValueOnce({
        rule_set_id: 'rules-one',
        version_id: 'version-one',
        state: 'ACTIVE',
        version: 4,
      })
      .mockResolvedValueOnce({
        run_id: 'run-one',
        state: 'QUEUED',
        created_at: '2026-07-30T00:00:00Z',
        replayed: false,
      })
    const api = new QualityApi({ request })

    await api.reviewRuleVersion(
      'rules-one',
      'version-one',
      2,
      { decision: 'APPROVE', reason: '검토 완료' },
      'quality-review-key',
    )
    await api.activateRuleVersion(
      'rules-one',
      'version-one',
      3,
      'quality-activation-key',
    )
    await api.requestManualRun('rules-one', 'quality-run-key')

    expect(request.mock.calls[0]).toEqual([
      '/quality/rule-sets/rules-one/versions/version-one/reviews',
      expect.objectContaining({
        method: 'POST',
        ifMatch: '"2"',
        idempotencyKey: 'quality-review-key',
        body: JSON.stringify({ decision: 'APPROVE', reason: '검토 완료' }),
      }),
    ])
    expect(request.mock.calls[1]).toEqual([
      '/quality/rule-sets/rules-one/versions/version-one/activations',
      expect.objectContaining({
        method: 'POST',
        ifMatch: '"3"',
        idempotencyKey: 'quality-activation-key',
      }),
    ])
    expect(request.mock.calls[2]).toEqual([
      '/quality/runs',
      expect.objectContaining({
        method: 'POST',
        idempotencyKey: 'quality-run-key',
        body: JSON.stringify({ rule_set_id: 'rules-one' }),
      }),
    ])
  })
})

const capabilityAxes = [
  'read_access',
  'profile_readiness',
  'rule_authoring',
  'review',
  'activation',
  'manual_execution',
  'scheduling',
  'operations',
].map((id) => ({ id, state: 'AVAILABLE' }))
const cacheScope = 'a'.repeat(64)

function scorePolicy() {
  return {
    policy_id: 'UNWEIGHTED_RULE_PASS_RATE_V1',
    policy_version: 1,
    policy_hash: 'd'.repeat(64),
    calculation: 'passed / (passed + advisory_failed + blocking_failed)',
    pass_condition: 'evaluated > 0 and advisory_failed = 0 and blocking_failed = 0',
    warn_condition: 'blocking_failed = 0 and advisory_failed > 0',
    fail_condition: 'blocking_failed > 0',
    unknown_condition: 'evaluated = 0',
  }
}

function dashboard() {
  const indicators = ['ACCURACY', 'COMPLETENESS', 'TIMELINESS'] as const
  return {
    contract_version: 'QUALITY_DASHBOARD_V1',
    cache_scope: cacheScope,
    observed_at: '2026-07-30T00:00:00Z',
    authorization_valid_until: '2026-07-30T00:00:30Z',
    as_of: '2026-07-30T00:00:00Z',
    schema_count: 1,
    table_count: 2,
    active_rule_set_count: 2,
    common_rule_template_count: 1,
    covered_table_count: 1,
    table_coverage_basis_points: 5_000,
    managed_rule_sets: indicators.map((indicatorId) => ({
      indicator_id: indicatorId,
      name: indicatorId,
      definition: `${indicatorId} definition`,
      calculation: `${indicatorId} calculation`,
      target_grain: indicatorId === 'TIMELINESS' ? 'TABLE' : 'FIELD',
      rule_kinds: indicatorId === 'ACCURACY'
        ? ['RANGE']
        : indicatorId === 'COMPLETENESS'
          ? ['NOT_NULL']
          : [],
      contract_version: 'QUALITY_MANAGED_INDICATORS_V1',
    })),
    schemas: [{
      schema_id: 'b'.repeat(64),
      platform: 'snowflake',
      database_name: 'analytics',
      schema_name: 'manufacturing',
      table_count: 2,
      covered_table_count: 1,
      indicators: indicators.map((indicatorId) => ({
        indicator_id: indicatorId,
        counted_target_count: 1,
        target_count: 2,
        coverage_basis_points: 5_000,
        score_basis_points: 9_000,
        outcome: 'WARN',
        risk_count: 0,
        evaluated_value_count: 100,
        report_state: 'FACTS_ONLY',
        report_reason_code: 'QUALITY_LLM_REPORT_ROUTE_UNAVAILABLE',
        report_summary: '서버가 검증한 사실 요약',
        risks: [],
      })),
    }],
    schemas_truncated: false,
  }
}
