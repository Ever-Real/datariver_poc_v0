import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { QualityRunSummary } from '../../api/types'
import { QualityApi, type QualitySecurityBoundary } from './qualityApi'
import { useBoundedQualityRunPolling } from './useBoundedQualityRunPolling'

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('useBoundedQualityRunPolling', () => {
  it('reads immediately, follows the 1 second first delay, and stops at a terminal run', async () => {
    vi.useFakeTimers()
    const request = vi.fn()
      .mockResolvedValueOnce(runResponse({ state: 'RUNNING' }))
      .mockResolvedValueOnce(runResponse({ state: 'SUCCEEDED', quality_outcome: 'PASS' }))
    const api = new QualityApi({ request })
    renderHarness(api)

    await settle()
    expect(request).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('attempts')).toHaveTextContent('1')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(999)
    })
    expect(request).toHaveBeenCalledTimes(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1)
    })
    expect(request).toHaveBeenCalledTimes(2)
    expect(screen.getByTestId('state')).toHaveTextContent('SUCCEEDED')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000)
    })
    expect(request).toHaveBeenCalledTimes(2)
  })
})

function renderHarness(api: QualityApi) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const boundary: QualitySecurityBoundary = {
    workspaceId: 'workspace-one',
    subjectId: 'subject-one',
    securityEpoch: 7,
    authorizationRevision: 11,
    cacheScope,
  }
  return render(
    <QueryClientProvider client={queryClient}>
      <PollingHarness api={api} boundary={boundary} />
    </QueryClientProvider>,
  )
}

function PollingHarness({
  api,
  boundary,
}: {
  api: QualityApi
  boundary: QualitySecurityBoundary
}) {
  const polling = useBoundedQualityRunPolling({
    api,
    boundary,
    selectedRun: selectedRunFixture,
    onBoundaryInvalid,
  })
  return <>
    <span data-testid="attempts">{polling.attempts}</span>
    <span data-testid="state">{polling.run?.state}</span>
  </>
}

const selectedRunFixture = run()
const onBoundaryInvalid = vi.fn()

function run(
  overrides: Partial<QualityRunSummary> = {},
): QualityRunSummary {
  return {
    run_id: 'run-one',
    rule_set_id: 'rule-set-one',
    rule_set_name: 'Customer completeness',
    asset_id: 'asset-one',
    asset_name: 'customer',
    trigger_kind: 'MANUAL',
    state: 'QUEUED',
    quality_outcome: 'UNKNOWN',
    score_basis_points: null,
    passed_count: null,
    advisory_failed_count: null,
    blocking_failed_count: null,
    created_at: '2026-07-30T00:00:00Z',
    completed_at: null,
    failure_code: null,
    version: 1,
    ...overrides,
  }
}

function runResponse(overrides: Partial<QualityRunSummary>) {
  return {
    item: run(overrides),
    cache_scope: cacheScope,
    observed_at: '2026-07-30T00:00:00Z',
    authorization_valid_until: '2026-07-30T00:00:30Z',
  }
}

async function settle() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}

const cacheScope = 'a'.repeat(64)
