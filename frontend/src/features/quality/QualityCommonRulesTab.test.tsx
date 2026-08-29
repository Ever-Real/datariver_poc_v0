import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type {
  QualityAsset,
  QualityCapabilityAxis,
  QualityCommonRuleTemplate,
  QualityListResponse,
} from '../../api/types'
import type { ApiClient } from '../../api/client'
import { QualityApi, type QualitySecurityBoundary } from './qualityApi'
import { QualityCommonRulesTab } from './QualityCommonRulesTab'

describe('QualityCommonRulesTab', () => {
  it('searches, checks compatibility, and maps multiple tables atomically', async () => {
    const request = vi.fn().mockImplementation((path: string, options?: RequestInit) => {
      if (path === '/quality/common-rule-templates') {
        return Promise.resolve({
          items: [template],
          cache_scope: boundary.cacheScope,
          observed_at: now,
          authorization_valid_until: validUntil,
        })
      }
      if (path === '/quality/common-rule-templates/template-one') {
        return Promise.resolve({
          item: { template, mappings: [] },
          cache_scope: boundary.cacheScope,
          observed_at: now,
          authorization_valid_until: validUntil,
        })
      }
      if (path === '/quality/assets?limit=100') return Promise.resolve(list(assets, 100))
      if (path === '/quality/assets/asset-one' || path === '/quality/assets/asset-two') {
        const assetId = path.endsWith('one') ? 'asset-one' : 'asset-two'
        return Promise.resolve({
          item: assets.find((asset) => asset.asset_id === assetId),
          authoring: {
            state: 'READY',
            reason_code: null,
            source_version: `source-${assetId}`,
            schema_hash: 'c'.repeat(64),
            fields: [{
              field_identifier: 'email',
              display_path: 'email',
              logical_type: 'STRING',
              supported_rule_kinds: ['NOT_NULL'],
            }],
          },
          cache_scope: boundary.cacheScope,
          observed_at: now,
          authorization_valid_until: validUntil,
        })
      }
      if (
        path === '/quality/common-rule-templates/template-one/mappings'
        && options?.method === 'POST'
      ) {
        return Promise.resolve({
          items: [
            {
              asset_id: 'asset-one',
              rule_set_id: 'rules-one',
              version_id: 'version-one',
              version: 1,
            },
            {
              asset_id: 'asset-two',
              rule_set_id: 'rules-two',
              version_id: 'version-two',
              version: 1,
            },
          ],
          replayed: false,
        })
      }
      throw new Error(`unexpected request: ${path}`)
    })
    renderTab(request)

    fireEvent.click(await screen.findByRole('button', { name: '여러 테이블에 적용' }))
    fireEvent.click(await screen.findByRole('checkbox', { name: '고객 선택' }))
    fireEvent.click(screen.getByRole('checkbox', { name: '고객 이력 선택' }))
    const firstField = await screen.findByRole('checkbox', { name: '고객 email 선택' })
    const secondField = screen.getByRole('checkbox', { name: '고객 이력 email 선택' })
    fireEvent.click(firstField)
    fireEvent.click(secondField)
    const next = screen.getByRole('button', { name: '다음: 파라미터 입력' })
    await waitFor(() => expect(next).toBeEnabled())
    expect(screen.getAllByText('적용 가능')).toHaveLength(2)
    fireEvent.click(next)
    const apply = await screen.findByRole('button', { name: '룰 적용' })
    expect(screen.getByText(/스케줄 등록은 현재 read-only/)).toBeInTheDocument()
    fireEvent.click(apply)

    await screen.findByText('2개 테이블에 적용했습니다.')
    const mappingCall = request.mock.calls.find(([path, options]) => (
      path === '/quality/common-rule-templates/template-one/mappings'
      && (options as RequestInit | undefined)?.method === 'POST'
    ))
    const mappingOptions = mappingCall?.[1] as {
      body?: string
      idempotencyKey?: string
    }
    expect(JSON.parse(mappingOptions.body ?? '')).toEqual({
      targets: [
        {
          asset_id: 'asset-one',
          bindings: [{
            template_rule_ordinal: 1,
            field_identifier: 'email',
          }],
        },
        {
          asset_id: 'asset-two',
          bindings: [{
            template_rule_ordinal: 1,
            field_identifier: 'email',
          }],
        },
      ],
    })
    expect(mappingOptions.idempotencyKey).toMatch(/^quality-template-field-map-/)
  })

  it('keeps template creation usable while explaining deployment mapping readiness', async () => {
    const request = vi.fn().mockImplementation((path: string) => {
      if (path === '/quality/common-rule-templates') {
        return Promise.resolve({
          items: [template],
          cache_scope: boundary.cacheScope,
          observed_at: now,
          authorization_valid_until: validUntil,
        })
      }
      if (path === '/quality/common-rule-templates/template-one') {
        return Promise.resolve({
          item: { template, mappings: [] },
          cache_scope: boundary.cacheScope,
          observed_at: now,
          authorization_valid_until: validUntil,
        })
      }
      throw new Error(`unexpected request: ${path}`)
    })
    const axes = availableAxes.map((axis) => axis.id === 'rule_authoring'
      ? {
          ...axis,
          state: 'UNAVAILABLE' as const,
          reason_code: 'FIELD_IDENTITY_MAPPING_UNAVAILABLE',
        }
      : axis)

    renderTab(request, axes)

    expect(await screen.findByText('공통 룰은 만들 수 있고, 일괄 적용은 준비 중입니다')).toBeInTheDocument()
    expect(screen.getByText('FIELD_IDENTITY_MAPPING_UNAVAILABLE')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '공통 룰 만들기' })).toBeEnabled()
    expect(await screen.findByRole('button', { name: '적용 준비 필요' })).toBeDisabled()
  })

  it('previews a bounded exact metadata scope and selects only filtered compatible fields', async () => {
    const filteredPath = '/quality/assets?limit=100&q=event&platform=postgres&database=analytics&schema=public'
    const typedAssets: QualityAsset[] = [{
      ...assets[0]!,
      name: '이벤트',
      platform: 'postgres',
      database_name: 'analytics',
      schema_name: 'public',
    }]
    const request = vi.fn().mockImplementation((path: string) => {
      if (path === '/quality/common-rule-templates') {
        return Promise.resolve({
          items: [template],
          cache_scope: boundary.cacheScope,
          observed_at: now,
          authorization_valid_until: validUntil,
        })
      }
      if (path === '/quality/common-rule-templates/template-one') {
        return Promise.resolve({
          item: { template, mappings: [] },
          cache_scope: boundary.cacheScope,
          observed_at: now,
          authorization_valid_until: validUntil,
        })
      }
      if (path === '/quality/assets?limit=100') return Promise.resolve(list([], 100))
      if (path === filteredPath) return Promise.resolve(list(typedAssets, 100))
      if (path === '/quality/assets/asset-one') {
        return Promise.resolve({
          item: typedAssets[0],
          authoring: {
            state: 'READY',
            reason_code: null,
            source_version: 'source-one',
            schema_hash: 'c'.repeat(64),
            fields: [
              {
                field_identifier: 'event_name',
                display_path: 'event_name',
                logical_type: 'STRING',
                supported_rule_kinds: ['NOT_NULL'],
              },
              {
                field_identifier: 'event_count',
                display_path: 'event_count',
                logical_type: 'INTEGER',
                supported_rule_kinds: ['NOT_NULL', 'RANGE'],
              },
            ],
          },
          cache_scope: boundary.cacheScope,
          observed_at: now,
          authorization_valid_until: validUntil,
        })
      }
      throw new Error(`unexpected request: ${path}`)
    })
    renderTab(request)

    fireEvent.click(await screen.findByRole('button', { name: '여러 테이블에 적용' }))
    fireEvent.change(screen.getByLabelText('테이블 검색'), { target: { value: 'event' } })
    fireEvent.change(screen.getByLabelText('Platform'), { target: { value: 'postgres' } })
    fireEvent.change(screen.getByLabelText('Database'), { target: { value: 'analytics' } })
    fireEvent.change(screen.getByLabelText('스키마'), { target: { value: 'public' } })
    fireEvent.click(screen.getByRole('button', { name: '검색' }))

    fireEvent.click(await screen.findByRole('checkbox', { name: '이벤트 선택' }))
    await screen.findByRole('checkbox', { name: '이벤트 event_name 선택' })
    fireEvent.change(screen.getByLabelText('타입'), { target: { value: 'STRING' } })
    fireEvent.click(screen.getByRole('button', { name: '필터 결과 전체 선택' }))

    expect(screen.getByRole('checkbox', { name: '이벤트 event_name 선택' })).toBeChecked()
    expect(screen.queryByRole('checkbox', { name: '이벤트 event_count 선택' })).not.toBeInTheDocument()
    expect(screen.getByText(/nullable 조건은 provider가 검증 가능한/)).toBeInTheDocument()
    expect(request).toHaveBeenCalledWith(filteredPath, expect.anything())
  })
})

function renderTab(
  request: ReturnType<typeof vi.fn>,
  axisValues: QualityCapabilityAxis[] = availableAxes,
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const api = new QualityApi({
    request: request as unknown as ApiClient['request'],
  })
  const axes = new Map(axisValues.map((axis) => [axis.id, axis]))
  return render(
    <QueryClientProvider client={queryClient}>
      <QualityCommonRulesTab
        api={api}
        boundary={boundary}
        axes={axes}
        selectedTemplateId="template-one"
        onSelectedTemplate={vi.fn()}
        onBoundaryInvalid={vi.fn()}
      />
    </QueryClientProvider>,
  )
}

function list<T>(items: T[], limit: number): QualityListResponse<T> {
  return {
    items,
    page: { next_cursor: null, limit },
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
const template: QualityCommonRuleTemplate = {
  template_id: 'template-one',
  name: '이메일 필수값',
  description: '고객 이메일을 필수로 검사',
  rules: [{
    field_identifier: 'email',
    kind: 'NOT_NULL',
    severity: 'BLOCKING',
    parameters: {},
  }],
  mapping_count: 0,
  created_at: now,
  updated_at: now,
}
const assets: QualityAsset[] = [
  {
    asset_id: 'asset-one',
    name: '고객',
    platform: 'snowflake',
    database_name: 'analytics',
    schema_name: 'customer',
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
    name: '고객 이력',
    platform: 'snowflake',
    database_name: 'analytics',
    schema_name: 'customer_history',
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
