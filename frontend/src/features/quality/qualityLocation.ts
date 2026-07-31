export type QualityTab = 'assets' | 'templates'

export interface QualityLocation {
  tab: QualityTab
  assetId?: string
  templateId?: string
}

const qualityTabs = new Set<QualityTab>(['assets', 'templates'])
const qualityUrlKeys = new Set([
  'page',
  'workspace',
  'qualityTab',
  'assetId',
  'templateId',
])

export function qualityLocationFromHref(href = window.location.href): QualityLocation {
  const parameters = new URL(href).searchParams
  const requestedTab = parameters.get('qualityTab')
  const tab = requestedTab && qualityTabs.has(requestedTab as QualityTab)
    ? requestedTab as QualityTab
    : 'assets'
  const assetId = boundedOpaqueId(parameters.get('assetId'))
  const templateId = boundedOpaqueId(parameters.get('templateId'))
  return {
    tab,
    ...(tab === 'assets' && assetId ? { assetId } : {}),
    ...(tab === 'templates' && templateId ? { templateId } : {}),
  }
}

export function qualityUrl(
  next: Partial<QualityLocation>,
  href = window.location.href,
): string {
  const url = new URL(href)
  for (const key of [...url.searchParams.keys()]) {
    if (!qualityUrlKeys.has(key)) url.searchParams.delete(key)
  }
  url.searchParams.set('page', 'quality')
  const tab = next.tab ?? qualityLocationFromHref(href).tab
  if (tab === 'assets') url.searchParams.delete('qualityTab')
  else url.searchParams.set('qualityTab', tab)
  setOpaqueParameter(url, 'assetId', tab === 'assets' ? next.assetId : undefined)
  setOpaqueParameter(
    url,
    'templateId',
    tab === 'templates' ? next.templateId : undefined,
  )
  return `${url.pathname}${url.search}${url.hash}`
}

export function sanitizeQualityUrl(href = window.location.href): string {
  return qualityUrl(qualityLocationFromHref(href), href)
}

function boundedOpaqueId(value: string | null): string | undefined {
  const normalized = value?.trim()
  if (!normalized || normalized.length > 200) return undefined
  return normalized
}

function setOpaqueParameter(
  url: URL,
  key: 'assetId' | 'templateId',
  value: string | undefined,
): void {
  const bounded = boundedOpaqueId(value ?? null)
  if (bounded) url.searchParams.set(key, bounded)
  else url.searchParams.delete(key)
}
