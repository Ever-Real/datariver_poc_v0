export const primaryNavigation = [
  { id: 'catalog', label: '검색', badge: undefined },
  { id: 'registration', label: '등록관리', badge: undefined },
  { id: 'change-management', label: '변경관리', badge: undefined },
  { id: 'quality', label: '품질관리', badge: 'Beta' },
  { id: 'knowledge', label: '지식관리', badge: undefined },
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
  | 'knowledge-chat'
  | 'knowledge-studio'
  | 'profile'

const pageIds = new Set<Page>([
  ...primaryNavigation.map(({ id }) => id),
  'dashboard',
  'sharing',
  'admin',
  'knowledge-chat',
  'knowledge-studio',
  'profile',
])

export function pageFromLocation(href = window.location.href): Page {
  const candidate = new URL(href).searchParams.get('page')
  return candidate && pageIds.has(candidate as Page) ? candidate as Page : 'dashboard'
}

export function pageUrl(page: Page, options: { query?: string; href?: string } = {}): string {
  const url = new URL(options.href ?? window.location.href)
  url.searchParams.set('page', page)
  if (page === 'catalog' && options.query) url.searchParams.set('q', options.query)
  else url.searchParams.delete('q')
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
