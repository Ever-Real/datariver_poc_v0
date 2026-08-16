import assert from 'node:assert/strict'
import test from 'node:test'

import {
  POC_DATA_SECURITY_FEATURES,
  POC_FEATURE_SECURITY_GRADES,
  POC_FEATURE_SECURITY_ROLES,
  applyFeatureSecurityPolicyUpdate,
  approvedDefaultFeatureSecurityPolicy,
  featureAvailableForRole,
  featureSecurityAllowed,
  normalizeFeatureSecurityPolicy,
} from './poc-feature-security-policy.mjs'

test('defines and exhaustively evaluates exactly 120 fixed feature-role-grade cells', () => {
  const policy = approvedDefaultFeatureSecurityPolicy()
  assert.equal(POC_DATA_SECURITY_FEATURES.length, 8)
  assert.equal(POC_FEATURE_SECURITY_ROLES.length, 5)
  assert.equal(POC_FEATURE_SECURITY_GRADES.length, 3)
  assert.equal(policy.cells.length, 120)
  for (const feature of POC_DATA_SECURITY_FEATURES) {
    for (const role of POC_FEATURE_SECURITY_ROLES) {
      for (const grade of POC_FEATURE_SECURITY_GRADES) {
        const expected = role === 'admin'
          || (featureAvailableForRole(feature, role) && grade === 'normal')
        assert.equal(featureSecurityAllowed(policy, feature, role, grade), expected, `${feature}/${role}/${grade}`)
      }
    }
  }
})

test('accepts only one complete fixed shape and preserves immutable role/admin invariants', () => {
  const policy = approvedDefaultFeatureSecurityPolicy()
  assert.deepEqual(normalizeFeatureSecurityPolicy(policy), policy)
  assert.throws(() => normalizeFeatureSecurityPolicy({ ...policy, cells: policy.cells.slice(1) }), {
    code: 'FEATURE_SECURITY_POLICY_INVALID',
  })
  assert.throws(() => normalizeFeatureSecurityPolicy({
    ...policy,
    cells: policy.cells.map((cell, index) => index === 0 ? { ...cell, feature: 'unknown' } : cell),
  }), { code: 'FEATURE_SECURITY_POLICY_INVALID' })
  assert.throws(() => normalizeFeatureSecurityPolicy({
    ...policy,
    cells: policy.cells.map((cell, index) => index === 1 ? policy.cells[0] : cell),
  }), { code: 'FEATURE_SECURITY_POLICY_INVALID' })
  assert.throws(() => normalizeFeatureSecurityPolicy({
    ...policy,
    cells: policy.cells.map((cell) => cell.role === 'admin' ? { ...cell, allow: false } : cell),
  }), { code: 'FEATURE_SECURITY_ADMIN_INVARIANT' })
  assert.throws(() => normalizeFeatureSecurityPolicy({
    ...policy,
    cells: policy.cells.map((cell) => (
      cell.feature === 'quality' && cell.role === 'viewer' && cell.grade === 'normal'
        ? { ...cell, allow: true }
        : cell
    )),
  }), { code: 'FEATURE_SECURITY_ROLE_INVARIANT' })
})

test('applies a bounded server-attributed update without accepting free-form keys', () => {
  const policy = approvedDefaultFeatureSecurityPolicy()
  const cells = policy.cells.map((cell) => (
    cell.feature === 'catalog' && cell.role === 'viewer' && cell.grade === 'credential'
      ? { ...cell, allow: true }
      : cell
  ))
  const updated = applyFeatureSecurityPolicyUpdate(policy, {
    cells,
    reason: 'permit reviewed credential Catalog metadata',
  }, 'admin-subject', '2026-08-16T13:00:00.000Z')
  assert.equal(featureSecurityAllowed(updated, 'catalog', 'viewer', 'credential'), true)
  assert.equal(updated.updated_by, 'admin-subject')
  assert.throws(() => applyFeatureSecurityPolicyUpdate(policy, {
    cells, reason: 'short', custom: true,
  }, 'admin-subject'), { code: 'FEATURE_SECURITY_POLICY_INVALID' })
})
