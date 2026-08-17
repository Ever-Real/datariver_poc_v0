// PHASE 1C-4: Server-authoritative CR lifecycle — pure functions, no I/O.
// Lane records are persisted in cr.approval_lanes inside the existing core CAS document.

import { createHash } from 'node:crypto'
import { Buffer } from 'node:buffer'

export const CR_FINAL_LANES = Object.freeze(['DEVELOPER', 'DATA_STEWARD', 'MANAGER'])
const LANE_ROLE = Object.freeze({ DEVELOPER: 'developer', DATA_STEWARD: 'data_steward', MANAGER: 'manager' })
function crErr(statusCode, code, msg) { return Object.assign(new Error(msg), { statusCode, code }) }
function assertStr(v, f) {
  if (typeof v !== 'string' || !v.trim() || v.length > 2000) throw crErr(400, 'CR_INPUT_INVALID', `${f} is required (max 2000).`)
  return v.trim()
}
function assertApproved(decision) {
  if (decision !== 'APPROVED') throw crErr(400, 'CR_DECISION_INVALID', 'decision must be APPROVED.')
}
function boundedObject(value, field) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw crErr(400, 'CR_INPUT_INVALID', `${field} must be an object.`)
  }
  const serialized = JSON.stringify(value)
  if (Buffer.byteLength(serialized) > 16_384) {
    throw crErr(400, 'CR_INPUT_INVALID', `${field} is too large.`)
  }
  return value
}
function valueHash(value) {
  return createHash('sha256').update(JSON.stringify(value)).digest('hex')
}
function activeLanes(cr) {
  return (Array.isArray(cr.approval_lanes) ? cr.approval_lanes : []).filter((l) => l?.round_id === cr.current_round_id)
}
function mkLane(id, stage, kind, decision, principal, systemId, reason, occurredAt, roundId) {
  return { id, stage, lane_kind: kind, decision, actor_subject_id: principal.subjectId, actor_role: principal.role, responsible_system_id: systemId, reason, occurred_at: occurredAt, round_id: roundId }
}
function approvalAuthority(kind, systemId) {
  return {
    kind: kind === 'DEVELOPER'
      ? 'SYSTEM_DEVELOPER'
      : kind === 'DATA_STEWARD' ? 'SYSTEM_DATA_STEWARD' : 'SYSTEM_MANAGER',
    system_id: systemId,
  }
}
function appendApprovalProjection(cr, lane) {
  const approvals = Array.isArray(cr.approvals) ? cr.approvals : []
  approvals.push({
    id: lane.id,
    stage: lane.stage,
    decision: lane.decision,
    actor_id: lane.actor_subject_id,
    reason: lane.reason,
    occurred_at: lane.occurred_at,
    round_id: lane.round_id,
    authorities: [approvalAuthority(lane.lane_kind, lane.responsible_system_id)],
  })
  cr.approvals = approvals
}

// Requirement 2: table grant + grade + feature policy cell check.
export function assertCrTableAccess({ principal, tableUrn, tableGrade, grantedTableUrns, featurePolicyDocument, featureSecurityAllowed, securityGradeRank }) {
  const isAdmin = principal.role === 'admin'
  if (!isAdmin && !(grantedTableUrns instanceof Set && grantedTableUrns.has(tableUrn)))
    throw crErr(403, 'TABLE_GRANT_REQUIRED', 'An explicit active Table grant is required.')
  if (!isAdmin && tableGrade && typeof securityGradeRank === 'function'
    && securityGradeRank(tableGrade) > securityGradeRank(principal.maxSecurityGrade))
    throw crErr(403, 'SECURITY_GRADE_FORBIDDEN', 'Table security grade exceeds subject maximum.')
  if (featurePolicyDocument && typeof featureSecurityAllowed === 'function'
    && !featureSecurityAllowed(featurePolicyDocument, 'change', principal.role, tableGrade || 'normal'))
    throw crErr(403, 'FEATURE_POLICY_DENIED', 'Change feature is disabled for this role and classification.')
}

// Requirement 3: exact Table-System only, no legacy fallback.
export function resolveNewCrResponsibleSystem({ tableUrn, requestedSystemId, mappingDocument, activeSystemIds, activeSystemIdsForTable }) {
  const exact = activeSystemIdsForTable(mappingDocument, tableUrn, activeSystemIds)
  if (!exact.length) throw crErr(409, 'CR_SYSTEM_UNRESOLVED', 'No active exact Table-System mapping; cannot create Change Request.')
  if (exact.length > 1) {
    if (!requestedSystemId || !exact.includes(requestedSystemId)) throw crErr(409, 'CR_SYSTEM_AMBIGUOUS', 'Multiple exact bindings exist; specify responsible_system_id.')
    return requestedSystemId
  }
  if (requestedSystemId && requestedSystemId !== exact[0]) throw crErr(409, 'CR_SYSTEM_MISMATCH', 'responsible_system_id does not match the exact mapping.')
  return exact[0]
}

// Requirement 4: dev/steward workflow action; admin denied.
export function assertCrWorkflowAction({ principal, responsibleSystemId, crId }) {
  if (principal.role === 'admin') throw crErr(403, 'CR_ADMIN_WORKFLOW_DENIED', 'Admin cannot perform developer/steward workflow actions.')
  if (!['developer', 'data_steward'].includes(principal.role)) throw crErr(403, 'CR_ROLE_FORBIDDEN', `Only developer/data_steward may act on CR ${crId}.`)
  if (!principal.systemIds.has(responsibleSystemId)) throw crErr(403, 'CR_SYSTEM_FORBIDDEN', `Not assigned to responsible System for CR ${crId}.`)
}

// Resolve responsible system from CR round; null for legacy.
export function crResponsibleSystemId(cr) {
  const round = Array.isArray(cr?.rounds) ? cr.rounds.find((r) => r?.id === cr.current_round_id) : null
  return round?.selected_system_id ?? cr?.responsible_system_id ?? null
}

export function hasCurrentStageApproval(cr, stage) { return activeLanes(cr).some((l) => l.stage === stage && l.decision === 'APPROVED') }
export function getFinalLaneStatus(cr, kind) {
  const rec = activeLanes(cr).find((l) => l.stage === 'FINAL' && l.lane_kind === kind && l.decision === 'APPROVED')
  return { satisfied: Boolean(rec), record: rec }
}
export function allFinalLanesSatisfied(cr) { return CR_FINAL_LANES.every((k) => getFinalLaneStatus(cr, k).satisfied) }

// Requirement 5: identifies which FINAL lane the principal owns; admin denied.
export function assertFinalLaneAccess({ principal, responsibleSystemId, crId }) {
  if (principal.role === 'admin') throw crErr(403, 'CR_ADMIN_LANE_DENIED', 'Admin does not satisfy any FINAL lane.')
  const entry = Object.entries(LANE_ROLE).find(([, r]) => r === principal.role)
  if (!entry) throw crErr(403, 'CR_ROLE_FORBIDDEN', `Role ${principal.role} has no FINAL lane.`)
  if (!principal.systemIds.has(responsibleSystemId)) throw crErr(403, 'CR_SYSTEM_FORBIDDEN', `Not assigned to responsible System for CR ${crId}.`)
  return entry[0]
}

// Requirement 6: REVIEW/TEST single-lane; idempotent if already approved.
export function applyWorkflowLane({ cr, stage, principal, responsibleSystemId, decision, reason, occurredAt, nextId }) {
  reason = assertStr(reason, 'reason')
  assertApproved(decision)
  if (!['REVIEW', 'TEST'].includes(stage)) throw crErr(400, 'CR_STAGE_INVALID', 'stage must be REVIEW or TEST.')
  const required = stage === 'REVIEW' ? 'IN_REVIEW' : 'TESTING'
  if (cr.state !== required) throw crErr(409, 'CR_STATE_MISMATCH', `${stage} approval requires state ${required}; got ${cr.state}.`)
  if (hasCurrentStageApproval(cr, stage)) return { cr, idempotent: true }
  const lanes = Array.isArray(cr.approval_lanes) ? cr.approval_lanes : []
  const lane = mkLane(nextId(), stage, principal.role === 'developer' ? 'DEVELOPER' : 'DATA_STEWARD', decision, principal, responsibleSystemId, reason, occurredAt, cr.current_round_id)
  lanes.push(lane)
  cr.approval_lanes = lanes
  appendApprovalProjection(cr, lane)
  return { cr, idempotent: false }
}

// Requirement 5+6: 3 independent FINAL lanes; idempotent per lane.
export function applyFinalLane({ cr, principal, responsibleSystemId, decision, reason, occurredAt, nextId }) {
  reason = assertStr(reason, 'reason')
  assertApproved(decision)
  if (cr.state !== 'FINAL_REVIEW') throw crErr(409, 'CR_STATE_MISMATCH', `FINAL lane requires FINAL_REVIEW; got ${cr.state}.`)
  const kind = assertFinalLaneAccess({ principal, responsibleSystemId, crId: cr.id })
  if (getFinalLaneStatus(cr, kind).satisfied) return { cr, laneKind: kind, idempotent: true, allSatisfied: allFinalLanesSatisfied(cr) }
  const lanes = Array.isArray(cr.approval_lanes) ? cr.approval_lanes : []
  const lane = mkLane(nextId(), 'FINAL', kind, decision, principal, responsibleSystemId, reason, occurredAt, cr.current_round_id)
  lanes.push(lane)
  cr.approval_lanes = lanes
  appendApprovalProjection(cr, lane)
  return { cr, laneKind: kind, idempotent: false, allSatisfied: allFinalLanesSatisfied(cr) }
}

// Requirement 4: transition with principal as actor; removes POC_SUBJECT_ID.
export function applyTransition({ cr, targetState, reason, principal, occurredAt, nextId }) {
  reason = assertStr(reason, 'reason')
  const prev = cr.state
  const legal = { REGISTERED: ['IN_REVIEW', 'CANCELLED'], IN_REVIEW: ['TESTING', 'CHANGES_REQUESTED', 'REJECTED', 'CANCELLED'], TESTING: ['IN_REVIEW', 'FINAL_REVIEW', 'CHANGES_REQUESTED', 'REJECTED', 'CANCELLED'], FINAL_REVIEW: ['COMPLETED', 'CHANGES_REQUESTED', 'REJECTED', 'CANCELLED'], APPLY_FAILED: ['APPLY_QUEUED', 'CANCELLED'], CHANGES_REQUESTED: ['CANCELLED'] }
  if (!(legal[prev] ?? []).includes(targetState)) throw crErr(409, 'CR_TRANSITION_INVALID', `Transition ${prev} -> ${targetState} not permitted.`)
  if (prev === 'IN_REVIEW' && targetState === 'TESTING' && !hasCurrentStageApproval(cr, 'REVIEW')) throw crErr(409, 'CR_REVIEW_APPROVAL_REQUIRED', 'REVIEW approval required before TESTING.')
  if (prev === 'TESTING' && targetState === 'FINAL_REVIEW') {
    const passed = Array.isArray(cr.test_runs) && cr.test_runs.some((r) => r?.round_id === cr.current_round_id && r?.state === 'PASSED')
    if (!passed || !hasCurrentStageApproval(cr, 'TEST')) throw crErr(409, 'CR_TEST_APPROVAL_REQUIRED', 'PASSED test run and TEST approval required before FINAL_REVIEW.')
  }
  if (prev === 'FINAL_REVIEW' && targetState === 'COMPLETED' && !allFinalLanesSatisfied(cr)) throw crErr(409, 'CR_FINAL_LANES_INCOMPLETE', 'All three FINAL lanes must be approved.')
  cr.state = targetState
  if (targetState === 'CHANGES_REQUESTED' && cr.request_type === 'CHANGE_INTAKE') cr.revision_allowed = true
  if (['REJECTED', 'CANCELLED', 'COMPLETED'].includes(targetState)) cr.revision_allowed = false
  const t = Array.isArray(cr.transitions) ? cr.transitions : []
  t.push({ id: nextId(), from_state: prev, to_state: targetState, actor_id: principal.subjectId, reason, occurred_at: occurredAt, round_id: cr.current_round_id })
  cr.transitions = t
  return { cr, previousState: prev }
}

// Requirement 4: test-run with principal as recorder; removes POC_SUBJECT_ID.
export function applyTestRun({ cr, attachmentId, state, boundedSummary, principal, responsibleSystemId, occurredAt, nextId, changeAttachments }) {
  if (cr.state !== 'TESTING') throw crErr(409, 'CR_STATE_MISMATCH', `Test run requires TESTING; got ${cr.state}.`)
  if (!['PASSED', 'FAILED'].includes(state)) throw crErr(400, 'CR_TEST_STATE_INVALID', 'state must be PASSED or FAILED.')
  const summary = boundedObject(boundedSummary, 'bounded_summary')
  const atts = (changeAttachments instanceof Map ? changeAttachments.get(cr.id) : []) ?? []
  const att = atts.find((a) => a?.id === attachmentId && a?.round_id === cr.current_round_id && a?.kind === 'TEST')
  if (!att) throw crErr(400, 'CR_TEST_ATTACHMENT_REQUIRED', 'A current-round TEST attachment is required.')
  const runs = Array.isArray(cr.test_runs) ? cr.test_runs : []
  runs.push({
    id: nextId(),
    round_id: cr.current_round_id,
    system_id: responsibleSystemId,
    attachment_id: att.id,
    state,
    plan_hash: valueHash({ cr_id: cr.id, round_id: cr.current_round_id, attachment_id: att.id }),
    result_hash: valueHash({ state, bounded_summary: summary }),
    bounded_summary: summary,
    recorded_by: principal.subjectId,
    occurred_at: occurredAt,
  })
  cr.test_runs = runs
  return { cr }
}
