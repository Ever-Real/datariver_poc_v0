export type KnowledgeStudioStep = 'basic' | 'tbox' | 'abox'

export interface KnowledgeStudioLocation {
  draftId?: string
  assetId?: string
  intent?: string
  step: KnowledgeStudioStep
  valid: boolean
}

const steps = new Set<KnowledgeStudioStep>(['basic', 'tbox', 'abox'])

function isHex(value: string | undefined): boolean {
  if (!value) return false
  return (value >= '0' && value <= '9')
    || (value >= 'a' && value <= 'f')
    || (value >= 'A' && value <= 'F')
}

export function isUuid(value: string): boolean {
  if (value.length !== 36) return false
  const hyphens = new Set([8, 13, 18, 23])
  for (let index = 0; index < value.length; index += 1) {
    if (hyphens.has(index)) {
      if (value[index] !== '-') return false
    } else if (!isHex(value[index])) return false
  }
  return true
}

export function knowledgeStudioLocationFromHref(
  href = window.location.href,
): KnowledgeStudioLocation {
  const params = new URL(href).searchParams
  const draft = params.get('draft')
  const asset = params.get('asset_id')
  const intent = params.get('intent')
  const candidateStep = params.get('step') ?? 'basic'
  const step = steps.has(candidateStep as KnowledgeStudioStep)
    ? candidateStep as KnowledgeStudioStep
    : 'basic'
  const draftValid = draft === null || isUuid(draft)
  const assetValid = asset === null || isUuid(asset)
  const stepValid = steps.has(candidateStep as KnowledgeStudioStep)
  const draftRequired = step !== 'basic'
  return {
    draftId: draftValid && draft !== null ? draft : undefined,
    assetId: assetValid && asset !== null ? asset : undefined,
    intent: intent !== null ? intent : undefined,
    step,
    valid: (
      draftValid
      && assetValid
      && stepValid
      && !(draft !== null && asset !== null)
      && (!draftRequired || draft !== null)
    ),
  }
}

export function knowledgeStudioUrl(
  options: {
    draftId?: string
    assetId?: string
    intent?: string
    step?: KnowledgeStudioStep
    href?: string
  } = {},
): string {
  const url = new URL(options.href ?? window.location.href)
  url.searchParams.set('page', 'knowledge-studio')
  url.searchParams.delete('q')
  url.searchParams.delete('asset')
  url.searchParams.delete('drawerTab')
  if (options.draftId) url.searchParams.set('draft', options.draftId)
  else url.searchParams.delete('draft')
  if (options.assetId && !options.draftId) url.searchParams.set('asset_id', options.assetId)
  else url.searchParams.delete('asset_id')
  if (options.intent && !options.draftId) url.searchParams.set('intent', options.intent)
  else url.searchParams.delete('intent')
  const step = options.step ?? 'basic'
  if (step === 'basic' && !options.draftId) url.searchParams.delete('step')
  else url.searchParams.set('step', step)
  return `${url.pathname}${url.search}${url.hash}`
}
