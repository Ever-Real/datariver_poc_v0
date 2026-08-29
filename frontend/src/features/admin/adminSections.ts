import type { AdminOperation, AdminReadContext } from '../../api/types'

const primarySections = [
  'memberships', 'siteManagement', 'featurePermissions', 'systemSettings', 'retention', 'auditLogs', 'dictionary'
] as const satisfies readonly AdminSection[]

export type AdminSection =
  | 'memberships' | 'systems' | 'systemSettings' | 'roles' | 'fallback'
  | 'classification' | 'providers' | 'restrictedGrants'
  | 'retention' | 'holds' | 'erasure'
  | 'auditLogs' | 'metadataLogs' | 'securityLogs' | 'dictionary' | 'featurePermissions' | 'siteManagement'

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
  auditLogs: ['MEMBERSHIP_ACCESS_READ'],
  metadataLogs: ['MEMBERSHIP_ACCESS_READ'],
  securityLogs: ['MEMBERSHIP_ACCESS_READ'],
  dictionary: ['MEMBERSHIP_ACCESS_READ'],
  featurePermissions: ['MEMBERSHIP_ACCESS_READ'],
  siteManagement: ['MEMBERSHIP_ACCESS_READ'],
}

export function allowedAdminSections(context: AdminReadContext): AdminSection[] {
  const allowed = new Set(context.allowed_operations)
  return primarySections.filter((section) => {
    if (section === 'featurePermissions' || section === 'siteManagement') {
      return context.action_vocabulary.includes('POC_LOCAL_ACCOUNT_ADMIN_V1')
    }
    if (section === 'memberships') {
      return [
        'MEMBERSHIP_ACCESS_READ', 'CLASSIFICATION_POLICY_READ', 'INFERENCE_PROVIDER_PROFILE_READ',
        'RESTRICTED_SEARCH_GRANT_READ', 'FALLBACK_REQUEST_READ',
      ].some((operation) => allowed.has(operation as AdminOperation))
    }
    if (section === 'retention') {
      return ['RETENTION_POLICY_READ', 'LEGAL_HOLD_READ', 'ERASURE_READ']
        .some((operation) => allowed.has(operation as AdminOperation))
    }
    const readOperation = sectionOperations[section][0]
    return readOperation ? allowed.has(readOperation) : false
  })
}

export function adminSectionFromLocation(): AdminSection {
  const value = new URL(window.location.href).searchParams.get('adminSection')
  if (value === 'metadataLogs' || value === 'securityLogs') return 'auditLogs'
  if (['systems', 'roles', 'fallback', 'classification', 'providers', 'restrictedGrants'].includes(value ?? '')) {
    return 'memberships'
  }
  if (value === 'holds' || value === 'erasure') return 'retention'
  return primarySections.includes(value as typeof primarySections[number])
    ? value as typeof primarySections[number]
    : 'memberships'
}
