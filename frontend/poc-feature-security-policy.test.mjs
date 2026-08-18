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
  normalizePersistedFeatureSecurityPolicy,
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
  const invalidPolicy = {
    ...policy,
    cells: policy.cells.map((cell) => (
      cell.feature === 'quality' && cell.role === 'viewer' && cell.grade === 'normal'
        ? { ...cell, allow: true }
        : cell
    )),
  }
  assert.throws(() => normalizeFeatureSecurityPolicy(invalidPolicy), { code: 'FEATURE_SECURITY_ROLE_INVARIANT' })
  assert.throws(() => normalizePersistedFeatureSecurityPolicy(invalidPolicy), { code: 'FEATURE_SECURITY_ROLE_INVARIANT' })
  const legacyManagerRegistrationPolicy = {
    ...policy,
    cells: policy.cells.map((cell) => (
      cell.feature === 'registration' && cell.role === 'manager'
        ? { ...cell, allow: true }
        : cell
    )),
  }
  assert.throws(() => normalizeFeatureSecurityPolicy(legacyManagerRegistrationPolicy), { code: 'FEATURE_SECURITY_ROLE_INVARIANT' })
  const projected = normalizePersistedFeatureSecurityPolicy(legacyManagerRegistrationPolicy)
  assert.equal(
    projected.cells.find((c) => c.feature === 'registration' && c.role === 'manager' && c.grade === 'normal').allow,
    false,
  )
  assert.throws(() => applyFeatureSecurityPolicyUpdate(policy, { cells: legacyManagerRegistrationPolicy.cells, reason: 'a'.repeat(10) }, 'test'), { code: 'FEATURE_SECURITY_ROLE_INVARIANT' })
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
