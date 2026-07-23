import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type {
  AdminReadContext,
  ClassificationAccessPolicy,
  ClassificationAccessPolicyProposal,
  InferenceProviderProfile,
  RestrictedSearchGrant,
  WorkspaceMembershipSummary,
} from '../../api/types'
import type { AdminApi } from './adminApi'
import type { PendingAdminMutation } from './AdminMutationConfirmDialog'
import {
  ClassificationPolicyAdmin,
  InferenceProviderProfileAdmin,
  RestrictedSearchGrantAdmin,
} from './ClassificationAccessAdmin'
import { getAdminMessages } from './messages'

const context: AdminReadContext = {
  subject_id: 'checker-one',
  workspace_id: 'workspace-one',
  display_name: 'Checker',
  authentication_assurance: 'HARDWARE_WEBAUTHN',
  fallback_enabled: false,
  allowed_operations: [
    'CLASSIFICATION_POLICY_READ', 'CLASSIFICATION_POLICY_PROPOSE',
    'CLASSIFICATION_POLICY_DECIDE', 'INFERENCE_PROVIDER_PROFILE_READ',
    'INFERENCE_PROVIDER_PROFILE_DECIDE', 'INFERENCE_PROVIDER_PROFILE_REVOKE',
    'RESTRICTED_SEARCH_GRANT_READ', 'RESTRICTED_SEARCH_GRANT_PROPOSE',
    'RESTRICTED_SEARCH_GRANT_DECIDE', 'RESTRICTED_SEARCH_GRANT_REVOKE',
  ],
  action_vocabulary: [],
}

function policy(state: ClassificationAccessPolicy['state'] = 'ACTIVE'): ClassificationAccessPolicy {
  return {
    policy_id: 'policy-one', policy_number: 7, required_jurisdiction: 'runtime-jurisdiction',
    restricted_search_grant_maximum_days: 30,
    rules: [
      { classification: 'PUBLIC', search_mode: 'ABAC', chat_mode: 'DENY', provider_profile_version_id: null },
      { classification: 'INTERNAL', search_mode: 'ABAC', chat_mode: 'DENY', provider_profile_version_id: null },
      { classification: 'CONFIDENTIAL', search_mode: 'DENY', chat_mode: 'DENY', provider_profile_version_id: null },
      { classification: 'RESTRICTED', search_mode: 'EXPLICIT_GRANT_ONLY', chat_mode: 'DENY', provider_profile_version_id: null },
    ],
    payload_hash: 'a'.repeat(64), requester_id: 'maker-one', request_reason: 'reviewed policy',
    state, checker_id: state === 'PROPOSED' ? null : 'checker-one', decision_reason: null,
    decided_at: null, superseded_by: null, supersede_reason: null, superseded_at: null,
    version: state === 'PROPOSED' ? 1 : 2,
  }
}

function provider(state: InferenceProviderProfile['state'] = 'APPROVED'): InferenceProviderProfile {
  return {
    provider_profile_version_id: 'profile-one', profile_key: 'runtime-profile', profile_version: 3,
    kind: 'INTERNAL', provider_identity: 'runtime-provider', model_identity: 'runtime-model',
    deployment_identity: 'runtime-deployment', jurisdiction: 'runtime-jurisdiction',
    region: 'runtime-region', maximum_classification: 'CONFIDENTIAL',
    residency_attestation: {
      fingerprint: 'b'.repeat(64), observed_at: '2025-01-01T00:00:00Z', expires_at: '2999-01-01T00:00:00Z',
    },
    zero_retention_attestation: {
      fingerprint: 'c'.repeat(64), observed_at: '2025-01-01T00:00:00Z', expires_at: '2999-01-01T00:00:00Z',
    },
    payload_hash: 'd'.repeat(64), maker_id: 'maker-one', proposal_reason: 'operator registry review',
    proposed_at: '2025-01-01T00:00:00Z', state, checker_id: state === 'PROPOSED' ? null : 'checker-one',
    decision_reason: null, decided_at: null, revoked_by: null, revocation_reason: null,
    revoked_at: null, version: state === 'PROPOSED' ? 1 : 2,
  }
}

function grant(id: string, scopeId: string): RestrictedSearchGrant {
  return {
    grant_id: id,
    classification_policy_id: 'policy-one',
    classification_policy_hash: 'a'.repeat(64),
    subject_id: 'subject-one',
    scope: 'SYSTEM',
    scope_id: scopeId,
    purpose: `Review ${scopeId}`,
    valid_from: '2026-07-01T00:00:00Z',
    expires_at: '2026-07-20T00:00:00Z',
    payload_hash: 'd'.repeat(64),
    requester_id: 'maker-one',
    request_reason: 'Security review',
    state: 'PENDING',
    checker_id: null,
    decision_reason: null,
    decided_at: null,
    revoked_by: null,
    revocation_reason: null,
    revoked_at: null,
    version: 1,
  }
}

function props(api: Partial<AdminApi>, requestConfirmation = vi.fn()) {
  return {
    api: api as AdminApi,
    context,
    messages: getAdminMessages('ko'),
    requestConfirmation,
    keyFor: vi.fn(() => 'stable-operation-key'),
    clearKey: vi.fn(),
    reportError: vi.fn(),
    onStepUp: vi.fn(() => Promise.resolve()),
    onPasswordReauth: vi.fn(() => Promise.resolve()),
    onEnroll: vi.fn(() => Promise.resolve()),
  }
}

describe('ClassificationPolicyAdmin', () => {
  it('does not let an older policy load overwrite a newer refresh', async () => {
    const oldPolicies = deferred<ReturnType<typeof page<ClassificationAccessPolicy>>>()
    const oldPolicy = {
      ...policy('PROPOSED'),
      policy_id: 'old-policy',
      policy_number: 8,
      request_reason: 'Old policy response',
    }
    const newPolicy = {
      ...policy('PROPOSED'),
      policy_id: 'new-policy',
      policy_number: 9,
      request_reason: 'New policy response',
    }
    const api = {
      listClassificationAccessPolicyPage: vi.fn()
        .mockImplementationOnce(() => oldPolicies.promise)
        .mockResolvedValue(page([newPolicy])),
      getCurrentClassificationAccessPolicy: vi.fn(() => Promise.resolve(null)),
      listInferenceProviderProfilePage: vi.fn(() => Promise.resolve(page([]))),
    }
    const view = render(<ClassificationPolicyAdmin {...props(api)} />)

    await waitFor(() => {
      expect(api.listClassificationAccessPolicyPage).toHaveBeenCalledOnce()
      expect(api.listInferenceProviderProfilePage).toHaveBeenCalledOnce()
    })
    const initialListSignal = (
      api.listClassificationAccessPolicyPage.mock.calls[0]?.[0] as { signal: AbortSignal }
    ).signal
    const providerCalls = api.listInferenceProviderProfilePage.mock.calls as unknown as Array<
      [{ signal: AbortSignal }]
    >
    const initialAuxiliarySignal = providerCalls[0]![0].signal
    fireEvent.click(screen.getByRole('button', { name: '새로고침' }))
    expect(await screen.findByText('New policy response')).toBeInTheDocument()
    await waitFor(() => {
      expect(api.listClassificationAccessPolicyPage).toHaveBeenCalledTimes(2)
      expect(api.listInferenceProviderProfilePage).toHaveBeenCalledTimes(2)
    })
    const refreshListSignal = (
      api.listClassificationAccessPolicyPage.mock.calls[1]?.[0] as { signal: AbortSignal }
    ).signal
    const refreshAuxiliarySignal = providerCalls[1]![0].signal
    expect(initialListSignal.aborted).toBe(true)
    expect(initialAuxiliarySignal.aborted).toBe(true)
    expect(refreshListSignal.aborted).toBe(false)
    expect(refreshAuxiliarySignal.aborted).toBe(false)

    await act(async () => {
      oldPolicies.resolve(page([oldPolicy]))
      await oldPolicies.promise
    })

    expect(screen.getByText('New policy response')).toBeInTheDocument()
    expect(screen.queryByText('Old policy response')).not.toBeInTheDocument()
    view.unmount()
    expect(refreshListSignal.aborted).toBe(true)
    expect(refreshAuxiliarySignal.aborted).toBe(true)
  })

  it('starts without runtime defaults and exposes exactly four immutable classification rows', async () => {
    const api = {
      listClassificationAccessPolicyPage: vi.fn(() => Promise.resolve(page([]))),
      getCurrentClassificationAccessPolicy: vi.fn(() => Promise.resolve(null)),
      listInferenceProviderProfilePage: vi.fn(() => Promise.resolve(page([]))),
    }
    render(<ClassificationPolicyAdmin {...props(api)} />)

    await waitFor(() => expect(api.listClassificationAccessPolicyPage).toHaveBeenCalledOnce())
    expect(screen.getByLabelText('승인 관할')).toHaveValue('')
    expect(screen.getByLabelText('RESTRICTED Grant 최대 일수')).toHaveValue(null)
    expect(screen.getByRole('table', { name: '데이터 분류 접근 정책' })).toBeInTheDocument()
    for (const classification of ['PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED']) {
      expect(screen.getByRole('row', { name: new RegExp(`^${classification}`) })).toBeInTheDocument()
      expect(screen.getByLabelText(`${classification} Search 모드`)).toBeInTheDocument()
      expect(screen.getByLabelText(`${classification} Chat 모드`)).toBeInTheDocument()
    }
    expect(screen.getByLabelText('RESTRICTED Chat 모드')).toHaveValue('DENY')
    expect(screen.getByLabelText('RESTRICTED Chat 모드')).toHaveAttribute('readonly')
    expect(screen.queryByDisplayValue(/provider|region|jurisdiction/i)).not.toBeInTheDocument()
  })

  it('does not call the policy API until the explicit confirmation executes', async () => {
    const created = policy('PROPOSED')
    const proposeClassificationAccessPolicy = vi.fn((
      proposal: ClassificationAccessPolicyProposal,
      idempotencyKey: string,
    ) => {
      void proposal; void idempotencyKey
      return Promise.resolve(created)
    })
    const api = {
      listClassificationAccessPolicyPage: vi.fn(() => Promise.resolve(page([]))),
      getCurrentClassificationAccessPolicy: vi.fn(() => Promise.resolve(null)),
      listInferenceProviderProfilePage: vi.fn(() => Promise.resolve(page([]))),
      proposeClassificationAccessPolicy,
    }
    const requestConfirmation = vi.fn()
    render(<ClassificationPolicyAdmin {...props(api, requestConfirmation)} />)
    await waitFor(() => expect(api.listClassificationAccessPolicyPage).toHaveBeenCalledOnce())

    fireEvent.change(screen.getByLabelText('승인 관할'), { target: { value: 'operator-approved-zone' } })
    fireEvent.change(screen.getByLabelText('RESTRICTED Grant 최대 일수'), { target: { value: '30' } })
    fireEvent.change(screen.getByLabelText('사유'), { target: { value: 'security review' } })
    fireEvent.click(screen.getByRole('button', { name: '정책 제안' }))

    expect(proposeClassificationAccessPolicy).not.toHaveBeenCalled()
    expect(requestConfirmation).toHaveBeenCalledOnce()
    const mutation = requestConfirmation.mock.calls[0]?.[0] as PendingAdminMutation
    await act(() => mutation.execute())
    expect(proposeClassificationAccessPolicy).toHaveBeenCalledOnce()
    expect(proposeClassificationAccessPolicy.mock.calls[0]?.[0].rules).toHaveLength(4)
  })

  it('preserves an explicitly selected provider when a later server page omits it', async () => {
    const api = {
      listClassificationAccessPolicyPage: vi.fn(() => Promise.resolve(page([]))),
      getCurrentClassificationAccessPolicy: vi.fn(() => Promise.resolve(null)),
      listInferenceProviderProfilePage: vi.fn(
        ({ profileKey }: { profileKey?: string }) => Promise.resolve(
          profileKey ? page([]) : page([provider()]),
        ),
      ),
    }
    render(<ClassificationPolicyAdmin {...props(api)} />)
    await waitFor(() => expect(api.listInferenceProviderProfilePage).toHaveBeenCalled())

    fireEvent.change(screen.getByLabelText('승인 관할'), {
      target: { value: 'runtime-jurisdiction' },
    })
    fireEvent.change(screen.getByLabelText('PUBLIC Chat 모드'), {
      target: { value: 'INTERNAL_APPROVED_ONLY' },
    })
    const providerSelect = screen.getByLabelText('PUBLIC 승인 Provider profile')
    fireEvent.change(providerSelect, { target: { value: 'profile-one' } })
    expect(providerSelect).toHaveValue('profile-one')

    fireEvent.change(screen.getByLabelText('승인 Provider profile key 검색'), {
      target: { value: 'other-profile' },
    })
    await waitFor(() => expect(api.listInferenceProviderProfilePage).toHaveBeenLastCalledWith(
      expect.objectContaining({ profileKey: 'other-profile' }),
    ))

    expect(screen.getByLabelText('PUBLIC 승인 Provider profile')).toHaveValue('profile-one')
    expect(screen.getByRole('option', { name: /runtime-profile v3/ })).toBeInTheDocument()
  })

  it('does not expose policy mutation controls from a read-only admin context', async () => {
    const requestConfirmation = vi.fn()
    const api = {
      listClassificationAccessPolicyPage: vi.fn(() => Promise.resolve(page([]))),
      getCurrentClassificationAccessPolicy: vi.fn(() => Promise.resolve(null)),
      listInferenceProviderProfilePage: vi.fn(() => Promise.resolve(page([]))),
      proposeClassificationAccessPolicy: vi.fn(),
    }
    const readOnly = {
      ...context,
      authentication_assurance: 'PASSWORD' as const,
      allowed_operations: ['CLASSIFICATION_POLICY_READ'] as const,
    }

    render(<ClassificationPolicyAdmin
      {...props(api, requestConfirmation)}
      context={{ ...readOnly, allowed_operations: [...readOnly.allowed_operations] }}
    />)
    await waitFor(() => expect(api.listClassificationAccessPolicyPage).toHaveBeenCalledOnce())

    expect(screen.getByRole('button', { name: '정책 제안' })).toBeDisabled()
    expect(screen.getByText(/WebAuthn 인증 후 정책을 제안/)).toBeInTheDocument()
    expect(requestConfirmation).not.toHaveBeenCalled()
    expect(api.proposeClassificationAccessPolicy).not.toHaveBeenCalled()
  })
})

describe('InferenceProviderProfileAdmin', () => {
  it('does not let an older provider load overwrite a newer refresh', async () => {
    const oldProfiles = deferred<ReturnType<typeof page<InferenceProviderProfile>>>()
    const oldProfile = {
      ...provider(),
      provider_profile_version_id: 'old-profile',
      profile_key: 'old-profile',
      provider_identity: 'old-provider',
    }
    const newProfile = {
      ...provider(),
      provider_profile_version_id: 'new-profile',
      profile_key: 'new-profile',
      provider_identity: 'new-provider',
    }
    const api = {
      listInferenceProviderProfilePage: vi.fn()
        .mockImplementationOnce(() => oldProfiles.promise)
        .mockResolvedValue(page([newProfile])),
    }
    const view = render(<InferenceProviderProfileAdmin {...props(api)} />)

    await waitFor(() => expect(api.listInferenceProviderProfilePage).toHaveBeenCalledOnce())
    const initialSignal = (
      api.listInferenceProviderProfilePage.mock.calls[0]?.[0] as { signal: AbortSignal }
    ).signal
    fireEvent.click(screen.getByRole('button', { name: '새로고침' }))
    expect(await screen.findByText('new-provider')).toBeInTheDocument()
    const refreshSignal = (
      api.listInferenceProviderProfilePage.mock.calls[1]?.[0] as { signal: AbortSignal }
    ).signal
    expect(initialSignal.aborted).toBe(true)
    expect(refreshSignal.aborted).toBe(false)

    await act(async () => {
      oldProfiles.resolve(page([oldProfile]))
      await oldProfiles.promise
    })

    expect(screen.getByText('new-provider')).toBeInTheDocument()
    expect(screen.queryByText('old-provider')).not.toBeInTheDocument()
    view.unmount()
    expect(refreshSignal.aborted).toBe(true)
  })

  it('is read/decision/revocation only and displays server-supplied runtime metadata', async () => {
    const api = {
      listInferenceProviderProfilePage: vi.fn(() => Promise.resolve(page([provider()]))),
    }
    render(<InferenceProviderProfileAdmin {...props(api)} />)

    expect(await screen.findByText('runtime-provider')).toBeInTheDocument()
    expect(screen.getByText('runtime-region')).toBeInTheDocument()
    expect(screen.getByText('runtime-jurisdiction')).toBeInTheDocument()
    expect(screen.getByText(/endpoint와 secret은 이 화면에서 등록하거나 변경할 수 없습니다/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /제안/ })).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/url|endpoint|secret|api key/i)).not.toBeInTheDocument()
  })

  it('binds an exact profile-key filter and resets a cursor page to the first page', async () => {
    const second = { ...provider(), provider_profile_version_id: 'profile-two' }
    const filtered = {
      ...provider(),
      provider_profile_version_id: 'filtered-profile',
      profile_key: 'approved-chat',
    }
    const api = {
      listInferenceProviderProfilePage: vi.fn()
        .mockResolvedValueOnce(page([provider()], 'provider-cursor'))
        .mockResolvedValueOnce(page([second]))
        .mockResolvedValueOnce(page([filtered])),
    }
    render(<InferenceProviderProfileAdmin {...props(api)} />)

    await screen.findByText('runtime-provider')
    fireEvent.click(screen.getByRole('button', { name: '다음' }))
    await waitFor(() => expect(api.listInferenceProviderProfilePage).toHaveBeenCalledTimes(2))
    fireEvent.change(screen.getByLabelText('프로파일 키 검색'), {
      target: { value: ' approved-chat ' },
    })
    fireEvent.click(screen.getByRole('button', { name: '검색' }))
    expect((await screen.findAllByText(/approved-chat/)).length).toBeGreaterThan(0)

    const requestedPages = api.listInferenceProviderProfilePage.mock.calls.map(
      ([options]) => {
        const pageOptions = options as {
          profileKey?: string
          state?: string
          cursor?: string
          limit: number
          signal: AbortSignal
        }
        return {
          profileKey: pageOptions.profileKey,
          state: pageOptions.state,
          cursor: pageOptions.cursor,
          limit: pageOptions.limit,
        }
      },
    )
    expect(requestedPages).toEqual([
      { profileKey: undefined, state: undefined, cursor: undefined, limit: 25 },
      { profileKey: undefined, state: undefined, cursor: 'provider-cursor', limit: 25 },
      { profileKey: 'approved-chat', state: undefined, cursor: undefined, limit: 25 },
    ])
    expect(screen.getByText('페이지 1')).toBeInTheDocument()
  })
})

describe('RestrictedSearchGrantAdmin', () => {
  it('does not let an older grant load overwrite a newer refresh', async () => {
    const oldGrants = deferred<ReturnType<typeof page<RestrictedSearchGrant>>>()
    const oldGrant = grant('old-grant', 'old-scope')
    const newGrant = grant('new-grant', 'new-scope')
    const api = {
      listRestrictedSearchGrantPage: vi.fn()
        .mockImplementationOnce(() => oldGrants.promise)
        .mockResolvedValue(page([newGrant])),
      listMembershipPage: vi.fn(() => Promise.resolve(page([]))),
      listSystemPage: vi.fn(() => Promise.resolve(page([]))),
      getCurrentClassificationAccessPolicy: vi.fn(() => Promise.resolve(policy())),
    }
    const view = render(<RestrictedSearchGrantAdmin {...props(api)} />)

    await waitFor(() => expect(api.listRestrictedSearchGrantPage).toHaveBeenCalledOnce())
    const initialGrantSignal = (
      api.listRestrictedSearchGrantPage.mock.calls[0]?.[0] as { signal: AbortSignal }
    ).signal
    fireEvent.click(screen.getByRole('button', { name: '새로고침' }))
    expect((await screen.findAllByText(/new-scope/)).length).toBeGreaterThan(0)
    const refreshGrantSignal = (
      api.listRestrictedSearchGrantPage.mock.calls[1]?.[0] as { signal: AbortSignal }
    ).signal
    expect(initialGrantSignal.aborted).toBe(true)
    expect(refreshGrantSignal.aborted).toBe(false)

    await act(async () => {
      oldGrants.resolve(page([oldGrant]))
      await oldGrants.promise
    })

    expect(screen.getAllByText(/new-scope/).length).toBeGreaterThan(0)
    expect(screen.queryByText(/old-scope/)).not.toBeInTheDocument()
    view.unmount()
    expect(refreshGrantSignal.aborted).toBe(true)
  })

  it('shows the active-policy maximum while leaving subject and scope unselected', async () => {
    const api = {
      listRestrictedSearchGrantPage: vi.fn(() => Promise.resolve(page([]))),
      listMembershipPage: vi.fn(() => Promise.resolve(page([{
        subject_id: 'subject-one', display_name: 'Engineer', subject_active: true,
        membership_active: true, department_id: null, job_function: 'ENGINEER',
        clearance: 'RESTRICTED', membership_version: 1, email: null, last_login_at: null,
        last_login_ip: null, owned_table_count: 0, change_request_count: 0,
        access_expires_at: '2027-01-20T00:00:00Z',
        renewal_eligible_at: '2026-12-21T00:00:00Z', access_expired: false,
        renewal_request_eligible: false,
        pending_renewal_request_id: null,
      } satisfies WorkspaceMembershipSummary]))),
      listSystemPage: vi.fn(() => Promise.resolve(page([]))),
      getCurrentClassificationAccessPolicy: vi.fn(() => Promise.resolve(policy())),
    }
    render(<RestrictedSearchGrantAdmin {...props(api)} />)

    expect(await screen.findByText(/현재 활성 정책의 최대 허용 기간: 30 days/)).toBeInTheDocument()
    expect(screen.getByLabelText('대상 사용자')).toHaveValue('')
    expect(screen.getByLabelText('범위')).toHaveValue('')
    expect(screen.queryByLabelText(/policy.*id|policy.*hash/i)).not.toBeInTheDocument()
  })

  it('searches bounded active member and system selectors instead of hiding later rows', async () => {
    const api = {
      listRestrictedSearchGrantPage: vi.fn(() => Promise.resolve(page([]))),
      listMembershipPage: vi.fn(() => Promise.resolve(page([]))),
      listSystemPage: vi.fn(() => Promise.resolve(page([]))),
      getCurrentClassificationAccessPolicy: vi.fn(() => Promise.resolve(policy())),
    }
    render(<RestrictedSearchGrantAdmin {...props(api)} />)
    await waitFor(() => expect(api.listMembershipPage).toHaveBeenCalledOnce())

    fireEvent.change(screen.getByLabelText('대상 사용자 검색'), {
      target: { value: ' engineer@example.test ' },
    })
    fireEvent.change(screen.getByLabelText('범위'), { target: { value: 'SYSTEM' } })
    fireEvent.change(screen.getByLabelText('시스템 검색'), {
      target: { value: ' fabrication ' },
    })

    await waitFor(() => expect(api.listMembershipPage).toHaveBeenLastCalledWith(expect.objectContaining({
      query: 'engineer@example.test',
      status: 'ACTIVE',
      limit: 25,
    })))
    const memberCalls = api.listMembershipPage.mock.calls as unknown as Array<
      [{ signal: unknown }]
    >
    expect(memberCalls.at(-1)?.[0].signal).toBeInstanceOf(AbortSignal)
    await waitFor(() => expect(api.listSystemPage).toHaveBeenLastCalledWith(expect.objectContaining({
      query: 'fabrication',
      status: 'ACTIVE',
      limit: 25,
    })))
    const systemCalls = api.listSystemPage.mock.calls as unknown as Array<
      [{ signal: unknown }]
    >
    expect(systemCalls.at(-1)?.[0].signal).toBeInstanceOf(AbortSignal)
  })
})

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((next) => { resolve = next })
  return { promise, resolve }
}

function page<T>(items: T[], nextCursor: string | null = null) {
  return { items, nextCursor, limit: 25 }
}
