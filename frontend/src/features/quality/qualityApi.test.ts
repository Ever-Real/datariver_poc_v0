import { describe, expect, it, vi } from 'vitest'
import { QualityApi } from './qualityApi'

describe('QualityApi authorization contracts', () => {
  it('rejects a capability lease longer than 30 seconds', async () => {
    const api = new QualityApi({
      request: vi.fn().mockResolvedValue({
        contract_version: 'QUALITY_CAPABILITY_V1',
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
})

const capabilityAxes = [
  'read_access',
  'profile_readiness',
  'rule_authoring',
  'activation',
  'manual_execution',
  'scheduling',
  'operations',
].map((id) => ({ id, state: 'AVAILABLE' }))
const cacheScope = 'a'.repeat(64)
