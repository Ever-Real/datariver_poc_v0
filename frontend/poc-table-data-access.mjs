import { securityGradeRank } from './poc-table-system-mappings.mjs'

export function isCanonicalDatahubDatasetUrn(value) {
  return typeof value === 'string'
    && value.length <= 4_096
    && value.startsWith('urn:li:dataset:(')
    && value.endsWith(')')
}

export function tablePolicyCellKey(feature, role, grade) {
  return `${feature}\u0000${role}\u0000${grade}`
}

export function evaluateTableDataAccess(principal, tableUrn, tableGrade, feature = 'catalog') {
  if (!principal || !isCanonicalDatahubDatasetUrn(tableUrn)) return false
  let tableRank
  try {
    tableRank = securityGradeRank(tableGrade)
  } catch {
    return false
  }
  if (principal.role === 'admin') return true
  let maximumRank
  try {
    maximumRank = securityGradeRank(principal.maxSecurityGrade)
  } catch {
    return false
  }
  return principal.activeTableGrantUrns instanceof Set
    && principal.activeTableGrantUrns.has(tableUrn)
    && tableRank <= maximumRank
    && principal.allowedFeatureSecurityCells instanceof Set
    && principal.allowedFeatureSecurityCells.has(tablePolicyCellKey(feature, principal.role, tableGrade))
}
