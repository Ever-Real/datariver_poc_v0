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
  created_at: '2026-07-17T01:02:03Z',
  requested_due_date: null,
  priority: null,
  urgency: null,
  classification: 'INTERNAL',
  version: 3,
  items: [],
  approvals: [],
  transitions: [],
} satisfies ChangeRequestRecord

describe('change request presentation', () => {
  it('labels an explicit change request and offers only re-registration or cancellation', () => {
    expect(changeStateLabel('CHANGES_REQUESTED')).toBe('보완 요청')
    expect(changeActionHints(changesRequested).map((hint) => hint.targetState)).toEqual([
      'REGISTERED',
      'CANCELLED',
    ])
  })
})
