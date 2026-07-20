import type { AdminOperation, AdminReadContext } from '../../api/types'

const sections = [
  'memberships', 'systems', 'systemSettings', 'roles', 'fallback', 'classification', 'providers', 'restrictedGrants',
  'retention', 'holds', 'erasure',
] as const

export type AdminSection = typeof sections[number]

const sectionOperations: Record<AdminSection, readonly AdminOperation[]> = {
  memberships: ['MEMBERSHIP_ACCESS_READ', 'MEMBERSHIP_ACCESS_UPDATE'],
  systems: ['MEMBERSHIP_ACCESS_READ'],
  systemSettings: ['SYSTEM_CONFIGURATION_READ'],
  roles: ['MEMBERSHIP_ACCESS_READ', 'MEMBERSHIP_ACCESS_UPDATE'],
  fallback: ['FALLBACK_REQUEST_READ', 'FALLBACK_REQUEST_CREATE', 'FALLBACK_REQUEST_DECIDE', 'FALLBACK_REQUEST_CONSUME'],
  classification: ['CLASSIFICATION_POLICY_READ', 'CLASSIFICATION_POLICY_PROPOSE', 'CLASSIFICATION_POLICY_DECIDE'],
  providers: ['INFERENCE_PROVIDER_PROFILE_READ', 'INFERENCE_PROVIDER_PROFILE_DECIDE', 'INFERENCE_PROVIDER_PROFILE_REVOKE'],
  restrictedGrants: ['RESTRICTED_SEARCH_GRANT_READ', 'RESTRICTED_SEARCH_GRANT_PROPOSE', 'RESTRICTED_SEARCH_GRANT_DECIDE', 'RESTRICTED_SEARCH_GRANT_REVOKE'],
  retention: ['RETENTION_POLICY_READ', 'RETENTION_POLICY_MANAGE'],
  holds: ['LEGAL_HOLD_READ', 'LEGAL_HOLD_PLACE', 'LEGAL_HOLD_RELEASE'],
  erasure: ['ERASURE_READ', 'ERASURE_REQUEST', 'ERASURE_APPROVE'],
}

export function allowedAdminSections(context: AdminReadContext): AdminSection[] {
  const allowed = new Set(context.allowed_operations)
  return sections.filter((section) => {
    const readOperation = sectionOperations[section][0]
    return readOperation ? allowed.has(readOperation) : false
  })
}

export function adminSectionFromLocation(): AdminSection {
  const value = new URL(window.location.href).searchParams.get('adminSection')
  return sections.includes(value as AdminSection) ? value as AdminSection : 'memberships'
}
