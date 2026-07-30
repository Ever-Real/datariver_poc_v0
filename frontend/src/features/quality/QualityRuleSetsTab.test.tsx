import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type {
  QualityAsset,
  QualityCapabilityAxis,
  QualityListResponse,
} from '../../api/types'
import type { ApiClient } from '../../api/client'
import { QualityRuleSetsTab } from './QualityRuleSetsTab'
import { QualityApi, type QualitySecurityBoundary } from './qualityApi'

describe('QualityRuleSetsTab authoring boundary', () => {
  it('submits selected assets once using only their common server field identifier', async () => {
    const request = vi.fn().mockImplementation((path: string, options?: RequestInit) => {
      if (path === '/quality/rule-definitions') {
        return Promise.resolve({
          contract_version: 'QUALITY_TYPED_RULES_V1',
          items: [
            { kind: 'NOT_NULL', available: true, reason_code: null, parameter_contract: {} },
            { kind: 'RANGE', available: true, reason_code: null, parameter_contract: {} },
            { kind: 'REGEX', available: false, reason_code: 'DISABLED', parameter_contract: {} },
          ],
        })
      }
      if (path === '/quality/rule-sets?limit=25') return Promise.resolve(list([]))
      if (path === '/quality/assets?limit=25') return Promise.resolve(list(assets))
      if (path === '/quality/assets/asset-one' || path === '/quality/assets/asset-two') {
        const assetId = path.endsWith('one') ? 'asset-one' : 'asset-two'
        return Promise.resolve({
          item: assets.find((asset) => asset.asset_id === assetId),
          authoring: {
            state: 'READY',
            reason_code: null,
            source_version: `${assetId}-source`,
            schema_hash: 'c'.repeat(64),
            fields: [{
              field_identifier: 'orders.amount',
              display_path: 'orders.amount',
              logical_type: 'DECIMAL',
              supported_rule_kinds: ['NOT_NULL', 'RANGE'],
            }],
          },
          cache_scope: boundary.cacheScope,
          observed_at: now,
          authorization_valid_until: validUntil,
        })
      }
      if (path === '/quality/rule-sets' && options?.method === 'POST') {
        return Promise.resolve({
          items: [
            { asset_id: 'asset-one', rule_set_id: 'rules-one', version_id: 'version-one', version: 1 },
            { asset_id: 'asset-two', rule_set_id: 'rules-two', version_id: 'version-two', version: 1 },
          ],
          replayed: false,
        })
      }
      throw new Error(`unexpected request: ${path}`)
    })
    renderRuleSets(request, availableAxes)

    fireEvent.click(await screen.findByRole('checkbox', { name: '주문 선택' }))
    fireEvent.click(screen.getByRole('checkbox', { name: '주문 이력 선택' }))
    const open = screen.getByRole('button', { name: '2개 자산에 Rule 제안' })
    await waitFor(() => expect(open).toBeEnabled())
    fireEvent.click(open)
    fireEvent.change(screen.getByLabelText('Rule Set 이름 접두어'), {
      target: { value: '핵심 주문 품질' },
    })
    fireEvent.click(screen.getByRole('button', { name: '일괄 제안 저장' }))

    await waitFor(() => expect(request.mock.calls.some(([path, options]) => (
      path === '/quality/rule-sets'
      && (options as RequestInit | undefined)?.method === 'POST'
    ))).toBe(true))
    const proposalCall = request.mock.calls.find(([path, options]) => (
      path === '/quality/rule-sets'
      && (options as RequestInit | undefined)?.method === 'POST'
    ))
    const proposalOptions = proposalCall?.[1] as {
      body?: string
      idempotencyKey?: string
    }
    expect(JSON.parse(proposalOptions.body ?? '')).toEqual({
      name_prefix: '핵심 주문 품질',
      asset_ids: ['asset-one', 'asset-two'],
      rules: [{
        field_identifier: 'orders.amount',
        kind: 'NOT_NULL',
        severity: 'BLOCKING',
        parameters: {},
      }],
    })
    expect(proposalOptions.idempotencyKey).toMatch(/^quality-rule-proposal-/)
    expect(request.mock.calls.filter(([path, options]) => (
      path === '/quality/rule-sets'
      && (options as RequestInit | undefined)?.method === 'POST'
    ))).toHaveLength(1)
  })

  it('fails closed when the rule authoring capability is unavailable', async () => {
    const request = vi.fn().mockImplementation((path: string) => {
      if (path === '/quality/rule-definitions') {
        return Promise.resolve({
          contract_version: 'QUALITY_TYPED_RULES_V1',
          items: [],
        })
      }
      if (path === '/quality/rule-sets?limit=25') return Promise.resolve(list([]))
      if (path === '/quality/assets?limit=25') return Promise.resolve(list(assets))
      throw new Error(`unexpected request: ${path}`)
    })
    const denied = availableAxes.map((axis) => (
      axis.id === 'rule_authoring'
        ? { ...axis, state: 'DENIED' as const, reason_code: 'PERMISSION_DENIED' }
        : axis
    ))
    renderRuleSets(request, denied)

    const checkbox = await screen.findByRole('checkbox', { name: '주문 선택' })
    expect(checkbox).toBeDisabled()
    expect(screen.queryByRole('button', { name: /자산에 Rule 제안/ })).not.toBeInTheDocument()
    expect(request.mock.calls.some(([path]) => String(path).startsWith('/quality/assets/asset-'))).toBe(false)
  })
})

function renderRuleSets(
  request: ReturnType<typeof vi.fn>,
  axes: QualityCapabilityAxis[],
) {
  const api = new QualityApi({
    request: request as unknown as ApiClient['request'],
  })
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <QualityRuleSetsTab
        api={api}
        boundary={boundary}
        axes={new Map(axes.map((axis) => [axis.id, axis]))}
        onSelectedRuleSet={vi.fn()}
        onBoundaryInvalid={vi.fn()}
      />
    </QueryClientProvider>,
  )
}

function list<T>(items: T[]): QualityListResponse<T> {
  return {
    items,
    page: { next_cursor: null, limit: 25 },
    cache_scope: boundary.cacheScope,
    observed_at: now,
    authorization_valid_until: validUntil,
  }
}

const now = '2026-07-30T00:00:00Z'
const validUntil = '2026-07-30T00:00:30Z'
const boundary: QualitySecurityBoundary = {
  workspaceId: 'workspace-one',
  subjectId: 'subject-one',
  securityEpoch: 7,
  authorizationRevision: 11,
  cacheScope: 'a'.repeat(64),
}
const assets: QualityAsset[] = [
  {
    asset_id: 'asset-one',
    name: '주문',
    classification: 'INTERNAL',
    lifecycle: 'ACTIVE',
    profile_readiness: 'READY',
    profile_observed_at: now,
    active_rule_set_count: 0,
    latest_run_state: null,
    latest_quality_outcome: null,
    latest_score_basis_points: null,
  },
  {
    asset_id: 'asset-two',
    name: '주문 이력',
    classification: 'INTERNAL',
    lifecycle: 'ACTIVE',
    profile_readiness: 'READY',
    profile_observed_at: now,
    active_rule_set_count: 0,
    latest_run_state: null,
    latest_quality_outcome: null,
    latest_score_basis_points: null,
  },
]
const availableAxes: QualityCapabilityAxis[] = [
  'read_access',
  'profile_readiness',
  'rule_authoring',
  'review',
  'activation',
  'manual_execution',
  'scheduling',
  'operations',
].map((id) => ({
  id: id as QualityCapabilityAxis['id'],
  state: 'AVAILABLE',
}))
