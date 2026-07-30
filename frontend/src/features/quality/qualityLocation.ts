export type QualityTab = 'overview' | 'rules' | 'runs' | 'issues'

export interface QualityLocation {
  tab: QualityTab
  ruleSetId?: string
  runId?: string
}

const qualityTabs = new Set<QualityTab>(['overview', 'rules', 'runs', 'issues'])
const qualityUrlKeys = new Set(['page', 'workspace', 'qualityTab', 'ruleSetId', 'runId'])

export function qualityLocationFromHref(href = window.location.href): QualityLocation {
  const parameters = new URL(href).searchParams
  const requestedTab = parameters.get('qualityTab')
  const tab = requestedTab && qualityTabs.has(requestedTab as QualityTab)
    ? requestedTab as QualityTab
    : 'overview'
  const ruleSetId = boundedOpaqueId(parameters.get('ruleSetId'))
  const runId = boundedOpaqueId(parameters.get('runId'))
  return {
    tab,
    ...(ruleSetId ? { ruleSetId } : {}),
    ...(runId ? { runId } : {}),
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
  if (tab === 'overview') url.searchParams.delete('qualityTab')
  else url.searchParams.set('qualityTab', tab)
  setOpaqueParameter(url, 'ruleSetId', next.ruleSetId)
  setOpaqueParameter(url, 'runId', next.runId)
  if (tab !== 'rules') url.searchParams.delete('ruleSetId')
  if (tab !== 'runs') url.searchParams.delete('runId')
  return `${url.pathname}${url.search}${url.hash}`
}

export function sanitizeQualityUrl(href = window.location.href): string {
  const location = qualityLocationFromHref(href)
  return qualityUrl(location, href)
}

function boundedOpaqueId(value: string | null): string | undefined {
  const normalized = value?.trim()
  if (!normalized || normalized.length > 200) return undefined
  return normalized
}

function setOpaqueParameter(
  url: URL,
  key: 'ruleSetId' | 'runId',
  value: string | undefined,
): void {
  const bounded = boundedOpaqueId(value ?? null)
  if (bounded) url.searchParams.set(key, bounded)
  else url.searchParams.delete(key)
}
