export function isCanonicalDatahubDatasetUrn(value) {
  return typeof value === 'string'
    && value.length <= 4_096
    && value.startsWith('urn:li:dataset:(')
    && value.endsWith(')')
}

export function tablePolicyCellKey(feature, role, grade) {
  return `${feature}\u0000${role}\u0000${grade}`
}

const tableCapabilityByFeature = Object.freeze({
  catalog: 'catalog.read',
  chat: 'chat.query',
  change: 'change.read',
  registration: 'catalog.execute',
  knowledge: 'knowledge.read',
  quality: 'quality.read',
  monitoring: 'monitoring.read',
  governance: 'change.read',
})

export function evaluateTableDataAccess(principal, tableUrn, feature = 'catalog') {
  if (!principal || !isCanonicalDatahubDatasetUrn(tableUrn)) return false
  if (principal.role === 'admin') return true
  const capability = tableCapabilityByFeature[feature]
  if (!capability) return false
  return principal.activeTableGrantUrns instanceof Set
    && principal.activeTableGrantUrns.has(tableUrn)
    && principal.capabilitySet instanceof Set
    && principal.capabilitySet.has(capability)
}
