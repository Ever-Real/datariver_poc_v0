export const primaryNavigation = [
  { id: 'dashboard', label: '운영' },
  { id: 'catalog', label: '검색' },
  { id: 'registration', label: '등록' },
  { id: 'governance', label: '변경관리' },
  { id: 'knowledge', label: '지식그래프' },
  { id: 'sharing', label: 'API 공유' },
  { id: 'chat', label: 'Chat' },
] as const

export type PrimaryPage = typeof primaryNavigation[number]['id']
export type Page = PrimaryPage | 'admin'

const pageIds = new Set<Page>([
  ...primaryNavigation.map(({ id }) => id),
  'admin',
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
  return `${url.pathname}${url.search}${url.hash}`
}

