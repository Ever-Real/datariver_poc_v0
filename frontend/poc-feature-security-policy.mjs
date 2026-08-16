/* global structuredClone */

import { CHANGE_HISTORY_ACCESS_ROLES, SECURITY_GRADES } from './poc-access-document.mjs'

export const POC_FEATURE_SECURITY_POLICY_SCOPE = 'feature-security-policy-v1'
export const POC_FEATURE_SECURITY_POLICY_SCHEMA_VERSION = 1
export const POC_DATA_SECURITY_FEATURES = Object.freeze([
  'catalog',
  'chat',
  'change',
  'registration',
  'knowledge',
  'quality',
  'monitoring',
  'governance',
])
export const POC_FEATURE_SECURITY_ROLES = CHANGE_HISTORY_ACCESS_ROLES
export const POC_FEATURE_SECURITY_GRADES = SECURITY_GRADES

const featureSet = new Set(POC_DATA_SECURITY_FEATURES)
const roleSet = new Set(POC_FEATURE_SECURITY_ROLES)
const gradeSet = new Set(POC_FEATURE_SECURITY_GRADES)
const governedRoles = new Set(['data_steward', 'manager', 'admin'])

function policyError(code, message) {
  return Object.assign(new Error(message), { statusCode: 400, code })
}

function exactKeys(value, expected, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw policyError('FEATURE_SECURITY_POLICY_INVALID', `${label} must be an object.`)
  }
  const actual = Object.keys(value).sort()
  const wanted = [...expected].sort()
  if (actual.length !== wanted.length || actual.some((key, index) => key !== wanted[index])) {
    throw policyError('FEATURE_SECURITY_POLICY_INVALID', `${label} contains unsupported or missing fields.`)
  }
}

function boundedText(value, maximum, label, minimum = 1) {
  if (typeof value !== 'string') {
    throw policyError('FEATURE_SECURITY_POLICY_INVALID', `${label} must be a string.`)
  }
  const normalized = value.trim()
  if (normalized.length < minimum || normalized.length > maximum
    || [...normalized].some((character) => {
      const point = character.codePointAt(0) ?? 0
      return point <= 31 || point === 127
    })) {
    throw policyError('FEATURE_SECURITY_POLICY_INVALID', `${label} is outside its bounded contract.`)
  }
  return normalized
}

function optionalTimestamp(value, label) {
  if (value === null) return null
  const normalized = boundedText(value, 40, label)
  if (!Number.isFinite(Date.parse(normalized))) {
    throw policyError('FEATURE_SECURITY_POLICY_INVALID', `${label} must be a timestamp or null.`)
  }
  return normalized
}

export function featureAvailableForRole(feature, role) {
  if (!featureSet.has(feature) || !roleSet.has(role)) {
    throw policyError('FEATURE_SECURITY_POLICY_INVALID', 'The feature or role is not canonical.')
  }
  if (role === 'admin') return true
  if (['registration', 'knowledge', 'quality'].includes(feature)) return governedRoles.has(role)
  return true
}

function defaultCell(feature, role, grade) {
  return {
    feature,
    role,
    grade,
    allow: role === 'admin' || (featureAvailableForRole(feature, role) && grade === 'normal'),
  }
}

export function approvedDefaultFeatureSecurityPolicy() {
  return {
    schema_version: POC_FEATURE_SECURITY_POLICY_SCHEMA_VERSION,
    cells: POC_DATA_SECURITY_FEATURES.flatMap((feature) => (
      POC_FEATURE_SECURITY_ROLES.flatMap((role) => (
        POC_FEATURE_SECURITY_GRADES.map((grade) => defaultCell(feature, role, grade))
      ))
    )),
    updated_at: null,
    updated_by: null,
    reason: 'APPROVED_PRODUCT_DEFAULT',
  }
}

function normalizeCells(value) {
  const expectedCount = POC_DATA_SECURITY_FEATURES.length
    * POC_FEATURE_SECURITY_ROLES.length
    * POC_FEATURE_SECURITY_GRADES.length
  if (!Array.isArray(value) || value.length !== expectedCount) {
    throw policyError('FEATURE_SECURITY_POLICY_INVALID', `cells must contain exactly ${expectedCount} fixed entries.`)
  }
  const observed = new Set()
  const cells = value.map((raw, index) => {
    exactKeys(raw, ['feature', 'role', 'grade', 'allow'], `cells[${index}]`)
    const feature = boundedText(raw.feature, 40, `cells[${index}].feature`)
    const role = boundedText(raw.role, 32, `cells[${index}].role`)
    const grade = boundedText(raw.grade, 20, `cells[${index}].grade`)
    if (!featureSet.has(feature) || !roleSet.has(role) || !gradeSet.has(grade) || typeof raw.allow !== 'boolean') {
      throw policyError('FEATURE_SECURITY_POLICY_INVALID', `cells[${index}] is outside the fixed policy vocabulary.`)
    }
    const key = `${feature}\u0000${role}\u0000${grade}`
    if (observed.has(key)) {
      throw policyError('FEATURE_SECURITY_POLICY_INVALID', `cells[${index}] duplicates a fixed policy cell.`)
    }
    observed.add(key)
    if (role === 'admin' && !raw.allow) {
      throw policyError('FEATURE_SECURITY_ADMIN_INVARIANT', 'The application admin data row is immutable Allow.')
    }
    if (!featureAvailableForRole(feature, role) && raw.allow) {
      throw policyError('FEATURE_SECURITY_ROLE_INVARIANT', 'A role-ineligible feature row must remain Deny.')
    }
    return { feature, role, grade, allow: raw.allow }
  })
  const byKey = new Map(cells.map((cell) => [`${cell.feature}\u0000${cell.role}\u0000${cell.grade}`, cell]))
  return POC_DATA_SECURITY_FEATURES.flatMap((feature) => (
    POC_FEATURE_SECURITY_ROLES.flatMap((role) => (
      POC_FEATURE_SECURITY_GRADES.map((grade) => byKey.get(`${feature}\u0000${role}\u0000${grade}`))
    ))
  ))
}

export function normalizeFeatureSecurityPolicy(value) {
  if (value === null || value === undefined) return approvedDefaultFeatureSecurityPolicy()
  exactKeys(value, ['schema_version', 'cells', 'updated_at', 'updated_by', 'reason'], 'feature security policy')
  if (value.schema_version !== POC_FEATURE_SECURITY_POLICY_SCHEMA_VERSION) {
    throw policyError('FEATURE_SECURITY_POLICY_INVALID', 'The feature security policy schema version is unsupported.')
  }
  const updatedAt = optionalTimestamp(value.updated_at, 'updated_at')
  const updatedBy = value.updated_by === null ? null : boundedText(value.updated_by, 255, 'updated_by')
  if ((updatedAt === null) !== (updatedBy === null)) {
    throw policyError('FEATURE_SECURITY_POLICY_INVALID', 'updated_at and updated_by must both be null or both be present.')
  }
  return {
    schema_version: POC_FEATURE_SECURITY_POLICY_SCHEMA_VERSION,
    cells: normalizeCells(value.cells),
    updated_at: updatedAt,
    updated_by: updatedBy,
    reason: boundedText(value.reason, 1_000, 'reason'),
  }
}

export function applyFeatureSecurityPolicyUpdate(current, command, actor, now = new Date().toISOString()) {
  normalizeFeatureSecurityPolicy(current)
  exactKeys(command, ['cells', 'reason'], 'feature security policy command')
  const changedAt = optionalTimestamp(now, 'now')
  const changedBy = boundedText(actor, 255, 'actor')
  const reason = boundedText(command.reason, 1_000, 'reason', 10)
  return {
    schema_version: POC_FEATURE_SECURITY_POLICY_SCHEMA_VERSION,
    cells: normalizeCells(structuredClone(command.cells)),
    updated_at: changedAt,
    updated_by: changedBy,
    reason,
  }
}

export function featureSecurityAllowed(document, feature, role, grade) {
  const normalized = normalizeFeatureSecurityPolicy(document)
  const cell = normalized.cells.find((item) => (
    item.feature === feature && item.role === role && item.grade === grade
  ))
  if (!cell) throw policyError('FEATURE_SECURITY_POLICY_INVALID', 'The requested fixed policy cell is missing.')
  return cell.allow
}
