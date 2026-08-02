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
})
