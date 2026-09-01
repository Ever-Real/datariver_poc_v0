import assert from 'node:assert/strict'
import test from 'node:test'
import {
  assertCrTableAccess,
  resolveNewCrResponsibleSystem,
  assertCrWorkflowAction,
  assertFinalLaneAccess,
  hasCurrentStageApproval,
  applyWorkflowLane,
  applyFinalLane,
  applyTransition,
  applyTestRun,
  crResponsibleSystemId,
} from './poc-cr-lifecycle.mjs'

function principal(role, systemIds, globalSystemMutation = false, maxSecurityGrade = 'normal') {
  return {
    subjectId: 'test-subject',
    role,
    systemIds: new Set(systemIds),
    globalSystemMutation,
    maxSecurityGrade,
    capabilitySet: new Set(role === 'admin' ? [] : ['change.read']),
  }
}

test('assertCrTableAccess enforces explicit grant and change capability without TAG-derived grade authority', () => {
  const p = principal('developer', ['system-a'])

  // Wrong System / No explicit grant
  assert.throws(
    () => assertCrTableAccess({
      principal: p, tableUrn: 'urn:table:1', grantedTableUrns: new Set(),
    }),
    { code: 'TABLE_GRANT_REQUIRED' }
  )

  // Explicit grant allowed
  assert.doesNotThrow(() => assertCrTableAccess({
    principal: p, tableUrn: 'urn:table:1', grantedTableUrns: new Set(['urn:table:1']),
  }))

  // Missing capability still fails closed.
  assert.throws(
    () => assertCrTableAccess({
      principal: { ...p, capabilitySet: new Set() },
      tableUrn: 'urn:table:1', grantedTableUrns: new Set(['urn:table:1']),
    }),
    { code: 'CAPABILITY_REQUIRED' }
  )

  // CR classification remains business metadata and never changes Table authority here.
  for (const tableGrade of ['normal', 'credential', 'restricted', 'invalid']) {
    assert.doesNotThrow(() => assertCrTableAccess({
      principal: p, tableUrn: 'urn:table:1', tableGrade,
      grantedTableUrns: new Set(['urn:table:1']),
    }))
  }
})

test('resolveNewCrResponsibleSystem resolves exact active mapping', () => {
  const activeSystemIdsForTable = (doc, urn, active) => {
    if (urn === 'urn:table:1') return active.filter(id => id === 'system-a')
    if (urn === 'urn:table:2') return active.filter(id => id === 'system-a' || id === 'system-b')
    return []
  }

  // Exact single match
  assert.equal(
    resolveNewCrResponsibleSystem({
      tableUrn: 'urn:table:1', requestedSystemId: null, mappingDocument: {},
      activeSystemIds: ['system-a'], activeSystemIdsForTable
    }),
    'system-a'
  )

  // Ambiguous match requires requestedSystemId
  assert.throws(
    () => resolveNewCrResponsibleSystem({
      tableUrn: 'urn:table:2', requestedSystemId: null, mappingDocument: {},
      activeSystemIds: ['system-a', 'system-b'], activeSystemIdsForTable
    }),
    { code: 'CR_SYSTEM_AMBIGUOUS' }
  )

  // Ambiguous match resolved with requestedSystemId
  assert.equal(
    resolveNewCrResponsibleSystem({
      tableUrn: 'urn:table:2', requestedSystemId: 'system-b', mappingDocument: {},
      activeSystemIds: ['system-a', 'system-b'], activeSystemIdsForTable
    }),
    'system-b'
  )

  // Mismatch
  assert.throws(
    () => resolveNewCrResponsibleSystem({
      tableUrn: 'urn:table:1', requestedSystemId: 'system-b', mappingDocument: {},
      activeSystemIds: ['system-a'], activeSystemIdsForTable
    }),
    { code: 'CR_SYSTEM_MISMATCH' }
  )

  // Unresolved
  assert.throws(
    () => resolveNewCrResponsibleSystem({
      tableUrn: 'urn:table:3', requestedSystemId: null, mappingDocument: {},
      activeSystemIds: ['system-a'], activeSystemIdsForTable
    }),
    { code: 'CR_SYSTEM_UNRESOLVED' }
  )
})

test('assertCrWorkflowAction denies admin and wrong system, allows developer/steward', () => {
  // Admin denied
  assert.throws(
    () => assertCrWorkflowAction({ principal: principal('admin', ['system-a']), responsibleSystemId: 'system-a', crId: '1' }),
    { code: 'CR_ADMIN_WORKFLOW_DENIED' }
  )

  // Wrong system
  assert.throws(
    () => assertCrWorkflowAction({ principal: principal('developer', ['system-b']), responsibleSystemId: 'system-a', crId: '1' }),
    { code: 'CR_SYSTEM_FORBIDDEN' }
  )

  // Role forbidden
  assert.throws(
    () => assertCrWorkflowAction({ principal: principal('viewer', ['system-a']), responsibleSystemId: 'system-a', crId: '1' }),
    { code: 'CR_ROLE_FORBIDDEN' }
  )

  // Allowed
  assert.doesNotThrow(() => assertCrWorkflowAction({ principal: principal('developer', ['system-a']), responsibleSystemId: 'system-a', crId: '1' }))
  assert.doesNotThrow(() => assertCrWorkflowAction({ principal: principal('data_steward', ['system-a']), responsibleSystemId: 'system-a', crId: '1' }))
})

test('assertFinalLaneAccess enforces manager final lane, denies admin and wrong system', () => {
  assert.throws(
    () => assertFinalLaneAccess({ principal: principal('admin', ['system-a']), responsibleSystemId: 'system-a', crId: '1' }),
    { code: 'CR_ADMIN_LANE_DENIED' }
  )

  assert.throws(
    () => assertFinalLaneAccess({ principal: principal('viewer', ['system-a']), responsibleSystemId: 'system-a', crId: '1' }),
    { code: 'CR_ROLE_FORBIDDEN' }
  )

  assert.equal(
    assertFinalLaneAccess({ principal: principal('manager', ['system-a']), responsibleSystemId: 'system-a', crId: '1' }),
    'MANAGER'
  )

  assert.equal(
    assertFinalLaneAccess({ principal: principal('developer', ['system-a']), responsibleSystemId: 'system-a', crId: '1' }),
    'DEVELOPER'
  )
})

test('applyWorkflowLane applies developer/steward review and test approvals', () => {
  let cr = { id: '1', state: 'IN_REVIEW', current_round_id: 'r1', approval_lanes: [] }
  const dev = principal('developer', ['system-a'])

  // Developer review
  const res1 = applyWorkflowLane({ cr, stage: 'REVIEW', principal: dev, responsibleSystemId: 'system-a', decision: 'APPROVED', reason: 'ok', occurredAt: '2026-08-17T00:00Z', nextId: () => 'l1' })
  assert.equal(res1.idempotent, false)
  assert.equal(cr.approval_lanes.length, 1)
  assert.equal(cr.approvals.length, 1)
  assert.deepEqual(cr.approvals[0].authorities, [{ kind: 'SYSTEM_DEVELOPER', system_id: 'system-a' }])
  assert.equal(hasCurrentStageApproval(cr, 'REVIEW'), true)

  // Duplicate developer review is idempotent
  const res2 = applyWorkflowLane({ cr, stage: 'REVIEW', principal: dev, responsibleSystemId: 'system-a', decision: 'APPROVED', reason: 'ok again', occurredAt: '2026-08-17T00:01Z', nextId: () => 'l2' })
  assert.equal(res2.idempotent, true)
  assert.equal(cr.approval_lanes.length, 1)

  // State mismatch
  cr.state = 'TESTING'
  assert.throws(
    () => applyWorkflowLane({ cr, stage: 'REVIEW', principal: dev, responsibleSystemId: 'system-a', decision: 'APPROVED', reason: 'ok', occurredAt: '2026-08-17T00:02Z', nextId: () => 'l3' }),
    { code: 'CR_STATE_MISMATCH' }
  )
})

test('applyFinalLane requires FINAL_REVIEW state, handles 3 independent lanes, duplicate is idempotent', () => {
  let cr = { id: '1', state: 'FINAL_REVIEW', current_round_id: 'r1', approval_lanes: [] }
  const dev = principal('developer', ['system-a'])
  const steward = principal('data_steward', ['system-a'])
  const manager = principal('manager', ['system-a'])

  // 1 lane complete (Developer)
  const res1 = applyFinalLane({ cr, principal: dev, responsibleSystemId: 'system-a', decision: 'APPROVED', reason: 'ok', occurredAt: '2026-08-17T00:00Z', nextId: () => 'l1' })
  assert.equal(res1.allSatisfied, false)
  assert.equal(res1.laneKind, 'DEVELOPER')
  assert.equal(res1.idempotent, false)

  // 2 lanes complete (Steward)
  const res2 = applyFinalLane({ cr, principal: steward, responsibleSystemId: 'system-a', decision: 'APPROVED', reason: 'ok', occurredAt: '2026-08-17T00:00Z', nextId: () => 'l2' })
  assert.equal(res2.allSatisfied, false)
  assert.equal(res2.laneKind, 'DATA_STEWARD')

  // Duplicate steward is idempotent
  const res3 = applyFinalLane({ cr, principal: steward, responsibleSystemId: 'system-a', decision: 'APPROVED', reason: 'ok again', occurredAt: '2026-08-17T00:00Z', nextId: () => 'l3' })
  assert.equal(res3.allSatisfied, false)
  assert.equal(res3.idempotent, true)

  // 3 lanes complete (Manager)
  const res4 = applyFinalLane({ cr, principal: manager, responsibleSystemId: 'system-a', decision: 'APPROVED', reason: 'ok', occurredAt: '2026-08-17T00:00Z', nextId: () => 'l4' })
  assert.equal(res4.allSatisfied, true)
  assert.equal(res4.laneKind, 'MANAGER')
  assert.deepEqual(cr.approvals.map((approval) => approval.authorities[0].kind), [
    'SYSTEM_DEVELOPER', 'SYSTEM_DATA_STEWARD', 'SYSTEM_MANAGER',
  ])

  assert.throws(
    () => applyFinalLane({
      cr: { id: '2', state: 'FINAL_REVIEW', current_round_id: 'r1', approval_lanes: [] },
      principal: manager,
      responsibleSystemId: 'system-a',
      decision: 'DENIED',
      reason: 'Unsupported decision',
      occurredAt: '2026-08-17T00:00Z',
      nextId: () => 'l5',
    }),
    { code: 'CR_DECISION_INVALID' },
  )
})

test('applyTransition ensures stage prerequisites and completes exactly once', () => {
  let cr = { id: '1', state: 'IN_REVIEW', current_round_id: 'r1', approval_lanes: [] }
  const dev = principal('developer', ['system-a'])

  // Cannot go to TESTING without REVIEW approval
  assert.throws(
    () => applyTransition({ cr, targetState: 'TESTING', reason: 'go', principal: dev, occurredAt: '2026-08-17T00:00Z', nextId: () => 't1' }),
    { code: 'CR_REVIEW_APPROVAL_REQUIRED' }
  )

  cr.approval_lanes.push({ stage: 'REVIEW', decision: 'APPROVED', round_id: 'r1' })
  applyTransition({ cr, targetState: 'TESTING', reason: 'go', principal: dev, occurredAt: '2026-08-17T00:00Z', nextId: () => 't1' })
  assert.equal(cr.state, 'TESTING')

  // Cannot go to FINAL_REVIEW without TEST approval and PASSED test run
  assert.throws(
    () => applyTransition({ cr, targetState: 'FINAL_REVIEW', reason: 'go', principal: dev, occurredAt: '2026-08-17T00:00Z', nextId: () => 't2' }),
    { code: 'CR_TEST_APPROVAL_REQUIRED' }
  )

  cr.approval_lanes.push({ stage: 'TEST', decision: 'APPROVED', round_id: 'r1' })
  cr.test_runs = [{ round_id: 'r1', state: 'PASSED' }]
  applyTransition({ cr, targetState: 'FINAL_REVIEW', reason: 'go', principal: dev, occurredAt: '2026-08-17T00:00Z', nextId: () => 't2' })
  assert.equal(cr.state, 'FINAL_REVIEW')

  // Cannot complete without all final lanes
  assert.throws(
    () => applyTransition({ cr, targetState: 'COMPLETED', reason: 'go', principal: dev, occurredAt: '2026-08-17T00:00Z', nextId: () => 't3' }),
    { code: 'CR_FINAL_LANES_INCOMPLETE' }
  )

  cr.approval_lanes.push({ stage: 'FINAL', lane_kind: 'DEVELOPER', decision: 'APPROVED', round_id: 'r1' })
  cr.approval_lanes.push({ stage: 'FINAL', lane_kind: 'DATA_STEWARD', decision: 'APPROVED', round_id: 'r1' })
  cr.approval_lanes.push({ stage: 'FINAL', lane_kind: 'MANAGER', decision: 'APPROVED', round_id: 'r1' })

  // Now completes
  applyTransition({ cr, targetState: 'COMPLETED', reason: 'go', principal: dev, occurredAt: '2026-08-17T00:00Z', nextId: () => 't4' })
  assert.equal(cr.state, 'COMPLETED')

  // Cannot transition out of COMPLETED
  assert.throws(
    () => applyTransition({ cr, targetState: 'CANCELLED', reason: 'go', principal: dev, occurredAt: '2026-08-17T00:00Z', nextId: () => 't5' }),
    { code: 'CR_TRANSITION_INVALID' }
  )
})

test('applyTestRun requires TESTING state and current-round TEST attachment', () => {
  let cr = { id: '1', state: 'IN_REVIEW', current_round_id: 'r1', test_runs: [] }
  const dev = principal('developer', ['system-a'])
  const changeAttachments = new Map([
    ['1', [{ id: 'att-1', round_id: 'r1', kind: 'TEST' }, { id: 'att-2', round_id: 'r0', kind: 'TEST' }]]
  ])

  // Wrong state
  assert.throws(
    () => applyTestRun({ cr, attachmentId: 'att-1', state: 'PASSED', boundedSummary: {}, principal: dev, responsibleSystemId: 'system-a', occurredAt: '2026-08-17T00:00Z', nextId: () => 'run1', changeAttachments }),
    { code: 'CR_STATE_MISMATCH' }
  )

  cr.state = 'TESTING'
  assert.throws(
    () => applyTestRun({ cr, attachmentId: 'att-1', state: 'UNKNOWN', boundedSummary: {}, principal: dev, responsibleSystemId: 'system-a', occurredAt: '2026-08-17T00:00Z', nextId: () => 'run1', changeAttachments }),
    { code: 'CR_TEST_STATE_INVALID' },
  )
  // Missing attachment
  assert.throws(
    () => applyTestRun({ cr, attachmentId: 'att-missing', state: 'PASSED', boundedSummary: {}, principal: dev, responsibleSystemId: 'system-a', occurredAt: '2026-08-17T00:00Z', nextId: () => 'run1', changeAttachments }),
    { code: 'CR_TEST_ATTACHMENT_REQUIRED' }
  )

  // Wrong round attachment
  assert.throws(
    () => applyTestRun({ cr, attachmentId: 'att-2', state: 'PASSED', boundedSummary: {}, principal: dev, responsibleSystemId: 'system-a', occurredAt: '2026-08-17T00:00Z', nextId: () => 'run1', changeAttachments }),
    { code: 'CR_TEST_ATTACHMENT_REQUIRED' }
  )

  // Success
  applyTestRun({ cr, attachmentId: 'att-1', state: 'FAILED', boundedSummary: { detail: 'test' }, principal: dev, responsibleSystemId: 'system-a', occurredAt: '2026-08-17T00:00Z', nextId: () => 'run1', changeAttachments })
  assert.equal(cr.test_runs.length, 1)
  assert.equal(cr.test_runs[0].state, 'FAILED')
})

test('spoofed lane kind is ignored because role is derived from token', () => {
  const cr = { id: '1', state: 'FINAL_REVIEW', current_round_id: 'r1', approval_lanes: [] }
  const dev = principal('developer', ['system-a'])

  // Developer applies final lane
  const result = applyFinalLane({ cr, principal: dev, responsibleSystemId: 'system-a', decision: 'APPROVED', reason: 'ok', occurredAt: '2026-08-17T00:00Z', nextId: () => 'l1' })
  // Even if dev tries to submit an API request, the derived lane is DEVELOPER, not MANAGER
  assert.equal(result.laneKind, 'DEVELOPER')
})

test('legacy read compatibility for pure functions', () => {
  // Modern CR
  assert.equal(crResponsibleSystemId({ current_round_id: 'r1', rounds: [{ id: 'r1', selected_system_id: 'system-a' }] }), 'system-a')
  // Legacy CR fallback
  assert.equal(crResponsibleSystemId({ responsible_system_id: 'system-b' }), 'system-b')
  // No system
  assert.equal(crResponsibleSystemId({}), null)
})
