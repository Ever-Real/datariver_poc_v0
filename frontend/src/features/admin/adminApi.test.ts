import { describe, expect, it, vi } from 'vitest'
import type { AdminAccessRequest, ErasureRequest, LegalHold, RetentionPolicy, WorkspaceMembershipAccess } from '../../api/types'
import { AdminApi } from './adminApi'

function mockClient() {
  const request = vi.fn()
  const requestWithMeta = vi.fn()
  return {
    request,
    requestWithMeta,
    api: new AdminApi({ request, requestWithMeta }),
  }
}

const access: WorkspaceMembershipAccess = {
  subject_id: 'subject-one', display_name: 'User', subject_active: true, department_id: null,
  job_function: 'ENGINEER', membership_version: 3,
  access: {
    active: true, clearance: 'INTERNAL', groups: ['engineers'], allowed_actions: ['catalog.read'],
    denied_actions: [], allowed_system_ids: [], allowed_domain_ids: [],
  },
}

describe('AdminApi', () => {
  it('requires the membership ETag to match the body version', async () => {
    const { api, requestWithMeta } = mockClient()
    requestWithMeta.mockResolvedValueOnce({ data: access, etag: '"3"' })
      .mockResolvedValueOnce({ data: access, etag: '"2"' })

    await expect(api.getMembershipAccess('subject-one')).resolves.toMatchObject({ etag: '"3"' })
    await expect(api.getMembershipAccess('subject-one')).rejects.toThrow(/ETag/)
  })

  it('sends an exact direct update with If-Match and one idempotency key', async () => {
    const { api, request } = mockClient()
    request.mockResolvedValue({ target_subject_id: 'subject-one', membership_version: 4, payload_hash: 'a'.repeat(64) })

    await api.updateMembership('subject-one', access.access, '"3"', 'admin-direct-operation-key')

    expect(request).toHaveBeenCalledOnce()
    expect(request).toHaveBeenCalledWith('/admin/workspace-memberships/subject-one/access', {
      method: 'PUT', ifMatch: '"3"', idempotencyKey: 'admin-direct-operation-key',
      body: JSON.stringify(access.access),
    })
  })

  it('binds fallback decisions and consume to the aggregate version and approved hash', async () => {
    const { api, request } = mockClient()
    const fallback = {
      id: 'request-one', version: 2, payload_hash: 'b'.repeat(64),
    } as AdminAccessRequest
    request.mockResolvedValue(fallback)

    await api.decideFallbackRequest(fallback, 'APPROVED', 'checked', 'fallback-decision-key')
    await api.consumeFallbackRequest(fallback, 'fallback-consume-key')

    expect(request.mock.calls[0]?.[1]).toMatchObject({ ifMatch: '"2"', idempotencyKey: 'fallback-decision-key' })
    expect(request.mock.calls[1]?.[1]).toMatchObject({
      ifMatch: '"2"', idempotencyKey: 'fallback-consume-key',
      body: JSON.stringify({ confirmed_payload_hash: 'b'.repeat(64) }),
    })
  })

  it('exposes retention and Legal Hold governance without any destructive route', async () => {
    const { api, request } = mockClient()
    const policy = { policy_id: 'policy-one', version: 1 } as RetentionPolicy
    const hold = { hold_id: 'hold-one', version: 1 } as LegalHold
    request.mockResolvedValue({})

    await api.proposeRetentionPolicy({ completed_operation_days: 1, chat_content_days: 1, audit_online_months: 1, immutable_archive_years: 1 }, 'reason', 'policy-key')
    await api.decideRetentionPolicy(policy, 'APPROVED', 'reason', 'policy-decision-key')
    await api.placeLegalHold('AUDIT_EVIDENCE', 'WORKSPACE', null, 'reason', 'hold-key')
    await api.requestLegalHoldRelease(hold, 'reason', 'hold-release-key')
    await api.decideLegalHoldRelease(hold, 'APPROVED', 'reason', 'hold-decision-key')

    const paths = request.mock.calls.map((call) => String(call[0]))
    expect(paths).toEqual([
      '/admin/retention/policies',
      '/admin/retention/policies/policy-one/decisions',
      '/admin/retention/legal-holds',
      '/admin/retention/legal-holds/hold-one/release-requests',
      '/admin/retention/legal-holds/hold-one/release-decisions',
    ])
    expect(paths.join(' ')).not.toMatch(/delet|destroy|execute/i)
  })

  it('binds erasure review to response ETags without exposing execution', async () => {
    const { api, request, requestWithMeta } = mockClient()
    const erasure = {
      erasure_request_id: 'request-one', target_type: 'UPLOAD_OBJECT', target_id: 'target-one',
      version: 1, state: 'PENDING', execution_state: 'DISABLED_NOT_READY',
    } as ErasureRequest
    request.mockResolvedValue({ items: [erasure] })
    requestWithMeta.mockResolvedValue({ data: erasure, etag: '"1"' })

    await api.listErasureRequests()
    const created = await api.requestErasure(
      'UPLOAD_OBJECT', 'target-one', 'review', 3600, 'erasure-create-key',
    )
    await api.getErasureRequest('request-one')
    await api.decideErasure(created, 'APPROVED', 'checked', 'erasure-decision-key')

    const paths = [
      ...request.mock.calls.map((call) => String(call[0])),
      ...requestWithMeta.mock.calls.map((call) => String(call[0])),
    ]
    expect(paths).toContain('/admin/retention/erasure-requests?limit=100')
    expect(paths).toContain('/admin/retention/erasure-requests')
    expect(paths).toContain('/admin/retention/erasure-requests/request-one')
    expect(paths).toContain('/admin/retention/erasure-requests/request-one/decisions')
    expect(paths.join(' ')).not.toMatch(/delete|destroy|execute|consume/i)
    expect(requestWithMeta.mock.calls.at(-1)?.[1]).toMatchObject({
      ifMatch: '"1"', idempotencyKey: 'erasure-decision-key',
    })
  })
})
