import type { PocCapability, PocRole } from '../api/types'

export const primaryNavigation = [
  { id: 'catalog', label: '검색', badge: undefined },
  { id: 'change-management', label: '변경관리', badge: undefined },
  { id: 'monitoring', label: '모니터링', badge: undefined },
  { id: 'governance', label: '거버넌스', badge: undefined },
  { id: 'chat', label: 'Chat', badge: 'Beta' },
] as const

export type PrimaryPage = typeof primaryNavigation[number]['id']
export type Page =
  | PrimaryPage
  | 'dashboard'
  | 'sharing'
  | 'admin'
  | 'registration'
  | 'knowledge'
  | 'quality'
  | 'knowledge-chat'
  | 'knowledge-instances'
  | 'knowledge-profiles'
  | 'knowledge-studio'
  | 'glossary'
  | 'profile'

const pageIds = new Set<Page>([
  ...primaryNavigation.map(({ id }) => id),
  'dashboard',
  'sharing',
  'admin',
  'registration',
  'knowledge',
  'quality',
  'knowledge-chat',
  'knowledge-instances',
  'knowledge-profiles',
  'knowledge-studio',
  'glossary',
  'profile',
])

const pocPageCapabilities: Partial<Record<Page, PocCapability>> = {
  catalog: 'catalog.read',
  registration: 'catalog.read',
  'change-management': 'change.read',
  quality: 'quality.read',
  knowledge: 'knowledge.read',
  'knowledge-chat': 'knowledge.read',
  'knowledge-instances': 'knowledge.read',
  'knowledge-profiles': 'knowledge.read',
  'knowledge-studio': 'knowledge.manage',
  glossary: 'catalog.manage',
  monitoring: 'monitoring.read',
  governance: 'knowledge.read',
  chat: 'chat.query',
  admin: 'admin.manage',
}

export function pocCapabilityForPage(page: Page): PocCapability | undefined {
  return pocPageCapabilities[page]
}

export function pocRoleAllowsPage(page: Page, role: PocRole | undefined): boolean {
  if (page === 'registration') {
    return role === 'data_steward' || role === 'manager' || role === 'admin'
  }
  return true
}

export function pocAuthorizationAllowsPage(
  page: Page,
  capabilities: readonly PocCapability[],
  role: PocRole | undefined,
): boolean {
  const required = pocCapabilityForPage(page)
  return pocRoleAllowsPage(page, role) && (!required || capabilities.includes(required))
}

export function pocNavigationForCapabilities(
  capabilities: readonly PocCapability[],
  role?: PocRole,
): typeof primaryNavigation[number][] {
  return primaryNavigation.filter(({ id }) => pocAuthorizationAllowsPage(id, capabilities, role))
}

export function pageFromLocation(href = window.location.href): Page {
  const candidate = new URL(href).searchParams.get('page')
  return candidate && pageIds.has(candidate as Page) ? candidate as Page : 'dashboard'
}

export function pageUrl(page: Page, options: { query?: string; href?: string } = {}): string {
  const url = new URL(options.href ?? window.location.href)
  url.searchParams.set('page', page)

  if (page === 'catalog') {
    if (options.query !== undefined) {
      if (options.query) url.searchParams.set('q', options.query)
      else url.searchParams.delete('q')
    }
  } else {
    url.searchParams.delete('catalogAsset')
  }

  if (page !== 'knowledge') {
    url.searchParams.delete('asset')
    url.searchParams.delete('drawerTab')
  }
  if (page !== 'knowledge-studio') {
    url.searchParams.delete('draft')
    url.searchParams.delete('step')
    url.searchParams.delete('asset_id')
  }
  return `${url.pathname}${url.search}${url.hash}`
}
