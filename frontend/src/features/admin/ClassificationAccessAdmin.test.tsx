import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type {
  AdminReadContext,
  ClassificationAccessPolicy,
  ClassificationAccessPolicyProposal,
  InferenceProviderProfile,
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
  it('starts without runtime defaults and exposes exactly four immutable classification rows', async () => {
    const api = {
      listClassificationAccessPolicies: vi.fn(() => Promise.resolve([])),
      getCurrentClassificationAccessPolicy: vi.fn(() => Promise.resolve(null)),
      listInferenceProviderProfiles: vi.fn(() => Promise.resolve([])),
    }
    render(<ClassificationPolicyAdmin {...props(api)} />)

    await waitFor(() => expect(api.listClassificationAccessPolicies).toHaveBeenCalledOnce())
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
      listClassificationAccessPolicies: vi.fn(() => Promise.resolve([])),
      getCurrentClassificationAccessPolicy: vi.fn(() => Promise.resolve(null)),
      listInferenceProviderProfiles: vi.fn(() => Promise.resolve([])),
      proposeClassificationAccessPolicy,
    }
    const requestConfirmation = vi.fn()
    render(<ClassificationPolicyAdmin {...props(api, requestConfirmation)} />)
    await waitFor(() => expect(api.listClassificationAccessPolicies).toHaveBeenCalledOnce())

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
})

describe('InferenceProviderProfileAdmin', () => {
  it('is read/decision/revocation only and displays server-supplied runtime metadata', async () => {
    const api = { listInferenceProviderProfiles: vi.fn(() => Promise.resolve([provider()])) }
    render(<InferenceProviderProfileAdmin {...props(api)} />)

    expect(await screen.findByText('runtime-provider')).toBeInTheDocument()
    expect(screen.getByText('runtime-region')).toBeInTheDocument()
    expect(screen.getByText('runtime-jurisdiction')).toBeInTheDocument()
    expect(screen.getByText(/endpoint와 secret은 이 화면에서 등록하거나 변경할 수 없습니다/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /제안/ })).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/url|endpoint|secret|api key/i)).not.toBeInTheDocument()
  })
})

describe('RestrictedSearchGrantAdmin', () => {
  it('shows the active-policy maximum while leaving subject and scope unselected', async () => {
    const api = {
      listRestrictedSearchGrants: vi.fn(() => Promise.resolve([])),
      listMemberships: vi.fn(() => Promise.resolve([{
        subject_id: 'subject-one', display_name: 'Engineer', subject_active: true,
        membership_active: true, department_id: null, job_function: 'ENGINEER',
        clearance: 'RESTRICTED', membership_version: 1, email: null, last_login_at: null,
        last_login_ip: null, owned_table_count: 0, change_request_count: 0,
        access_expires_at: '2027-01-20T00:00:00Z',
        renewal_eligible_at: '2026-12-21T00:00:00Z', access_expired: false,
        renewal_request_eligible: false,
        pending_renewal_request_id: null,
      } satisfies WorkspaceMembershipSummary])),
      listSystems: vi.fn(() => Promise.resolve([])),
      getCurrentClassificationAccessPolicy: vi.fn(() => Promise.resolve(policy())),
    }
    render(<RestrictedSearchGrantAdmin {...props(api)} />)

    expect(await screen.findByText(/현재 활성 정책의 최대 허용 기간: 30 days/)).toBeInTheDocument()
    expect(screen.getByLabelText('대상 사용자')).toHaveValue('')
    expect(screen.getByLabelText('범위')).toHaveValue('')
    expect(screen.queryByLabelText(/policy.*id|policy.*hash/i)).not.toBeInTheDocument()
  })
})
