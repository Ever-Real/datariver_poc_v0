import { describe, expect, it } from 'vitest'
import type { ChangeRequestRecord } from '../../api/types'
import { changeActionHints, changeStateLabel } from './changePresentation'

const changesRequested = {
  id: 'c3cf0d9d-8a6f-40f9-96b5-38f76f1fb2d4',
  number: 'CR-FAB-260717-7F2A',
  request_type: 'METADATA_CHANGE',
  title: 'Column description correction',
  description: 'Correct the asset description.',
  state: 'CHANGES_REQUESTED',
  requester_id: '4963d725-b788-4db4-80b1-5761d96ff994',
  requester_department_id: null,
  current_round_id: 'round-1',
  current_round_number: 1,
  revision_allowed: false,
  created_at: '2026-07-17T01:02:03Z',
  requested_due_date: null,
  priority: null,
  urgency: null,
  classification: 'INTERNAL',
  version: 3,
  items: [],
  approvals: [],
  transitions: [],
  rounds: [{
    id: 'round-1', round_number: 1, submitted_by: '4963d725-b788-4db4-80b1-5761d96ff994',
    submitted_at: '2026-07-17T01:02:03Z', closed_at: null, evidence_hash: 'a'.repeat(64),
    revision_kind: 'LEGACY', title: 'Column description correction', request_date: null,
    request_department: '', request_reason: 'Correct the asset description.', request_content: '',
    requested_due_date: null, priority: null, urgency: null, classification: 'INTERNAL',
    selected_system_id: null,
  }],
  test_runs: [],
} satisfies ChangeRequestRecord

describe('change request presentation', () => {
  it('labels a change request and never offers the removed direct re-registration transition', () => {
    expect(changeStateLabel('CHANGES_REQUESTED')).toBe('보완 요청')
    expect(changeActionHints(changesRequested).map((hint) => hint.targetState)).toEqual([
      'CANCELLED',
    ])
  })

  it('keeps terminal rejection out of review and resumes an already approved review', () => {
    const review = {
      ...changesRequested,
      state: 'IN_REVIEW',
      approvals: [],
    } satisfies ChangeRequestRecord
    expect(changeActionHints(review).map((hint) => hint.label)).toEqual([
      '검토 승인 및 변경 / 테스트로 이동',
      '보완 요청',
      '요청 취소',
    ])

    const approved = {
      ...review,
      approvals: [{
        id: 'approval-review', stage: 'REVIEW', decision: 'APPROVED', actor_id: 'reviewer',
        reason: '승인', occurred_at: '2026-07-17T02:03:04Z', round_id: review.current_round_id,
        authorities: [{ kind: 'SYSTEM_DEVELOPER', system_id: null }],
      }],
    } satisfies ChangeRequestRecord
    expect(changeActionHints(approved)[0]).toMatchObject({
      kind: 'TRANSITION',
      targetState: 'TESTING',
    })
  })

  it('shows only the final approval request after the current round test is passed and approved', () => {
    const testing = {
      ...changesRequested,
      state: 'TESTING',
      approvals: [{
        id: 'approval-test', stage: 'TEST', decision: 'APPROVED', actor_id: 'tester',
        reason: '테스트 승인', occurred_at: '2026-07-17T02:03:04Z', round_id: changesRequested.current_round_id,
        authorities: [{ kind: 'SYSTEM_DEVELOPER', system_id: null }],
      }],
      test_runs: [{
        id: 'test-run', round_id: changesRequested.current_round_id, system_id: 'system',
        attachment_id: 'attachment', state: 'PASSED', plan_hash: 'a'.repeat(64),
        result_hash: 'b'.repeat(64), bounded_summary: {}, recorded_by: 'tester',
        occurred_at: '2026-07-17T02:02:00Z',
      }],
    } satisfies ChangeRequestRecord

    expect(changeActionHints(testing)).toEqual([
      expect.objectContaining({ label: '최종 승인 요청', targetState: 'FINAL_REVIEW' }),
    ])
  })

  it('offers the same single final approval request when a passed test still needs TEST approval', () => {
    const testing = {
      ...changesRequested,
      state: 'TESTING',
      approvals: [],
      test_runs: [{
        id: 'test-run', round_id: changesRequested.current_round_id, system_id: 'system',
        attachment_id: 'attachment', state: 'PASSED', plan_hash: 'a'.repeat(64),
        result_hash: 'b'.repeat(64), bounded_summary: {}, recorded_by: 'tester',
        occurred_at: '2026-07-17T02:02:00Z',
      }],
    } satisfies ChangeRequestRecord

    expect(changeActionHints(testing)).toEqual([
      expect.objectContaining({ label: '최종 승인 요청', kind: 'APPROVAL', stage: 'TEST' }),
    ])
  })
})
