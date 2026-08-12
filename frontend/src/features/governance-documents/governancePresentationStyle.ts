import type { CSSProperties } from 'react'

const maximumPresentationCharacters = 2_000

const enumeratedValues: Record<string, ReadonlySet<string>> = {
  'align-items': new Set(['start', 'end', 'center', 'stretch', 'baseline', 'flex-start', 'flex-end']),
  display: new Set(['block', 'inline', 'inline-block', 'flex', 'inline-flex', 'grid']),
  'flex-direction': new Set(['row', 'row-reverse', 'column', 'column-reverse']),
  'flex-wrap': new Set(['nowrap', 'wrap']),
  'font-style': new Set(['normal', 'italic', 'oblique']),
  'justify-content': new Set(['start', 'end', 'center', 'space-between', 'space-around', 'space-evenly', 'flex-start', 'flex-end']),
  'list-style-type': new Set(['disc', 'circle', 'square', 'decimal', 'lower-alpha', 'upper-alpha', 'none']),
  overflow: new Set(['visible', 'hidden', 'auto']),
  'text-align': new Set(['left', 'right', 'center', 'justify', 'start', 'end']),
  'text-decoration': new Set(['none', 'underline', 'line-through']),
  'text-transform': new Set(['none', 'uppercase', 'lowercase', 'capitalize']),
  'white-space': new Set(['normal', 'pre', 'pre-wrap', 'pre-line']),
}

const lengthProperties = new Set([
  'border-radius', 'border-width', 'font-size', 'gap', 'letter-spacing',
  'margin', 'margin-top', 'margin-right', 'margin-bottom', 'margin-left',
  'max-width', 'padding', 'padding-top', 'padding-right', 'padding-bottom',
  'padding-left', 'text-indent', 'width',
])
const colorProperties = new Set(['background', 'background-color', 'border-color', 'color'])
const borderStyles = new Set(['none', 'solid', 'dashed', 'dotted', 'double'])

export function safeGovernancePresentation(value: string | null | undefined): string {
  if (!value) return ''
  const declarations = new Map<string, string>()
  for (const raw of value.slice(0, maximumPresentationCharacters).replace(/\/\*[\s\S]*?\*\//g, '').split(';')) {
    const delimiter = raw.indexOf(':')
    if (delimiter <= 0) continue
    const property = raw.slice(0, delimiter).trim().toLocaleLowerCase()
    const candidate = raw.slice(delimiter + 1).trim()
    const normalized = safeValue(property, candidate)
    if (normalized) declarations.set(property, normalized)
  }
  return [...declarations].map(([property, candidate]) => `${property}:${candidate}`).join(';')
}

export function mergeGovernancePresentations(...values: Array<string | null | undefined>): string {
  return safeGovernancePresentation(values.filter(Boolean).join(';'))
}

export function governancePresentationReactStyle(value: string | null): CSSProperties | undefined {
  const safe = safeGovernancePresentation(value)
  if (!safe) return undefined
  const style: Record<string, string> = {}
  for (const declaration of safe.split(';')) {
    const [property, candidate] = declaration.split(':', 2)
    if (!property || !candidate) continue
    const reactProperty = property.replace(/-([a-z])/g, (_, letter: string) => letter.toUpperCase())
    style[reactProperty] = candidate
  }
  return style
}

function safeValue(property: string, value: string): string | undefined {
  const normalized = value.trim().toLocaleLowerCase().replace(/\s+/g, ' ')
  if (!normalized || normalized.length > 120
    || /(?:url\s*\(|expression\s*\(|var\s*\(|calc\s*\(|@import|javascript:|[{}<>\\])/i.test(normalized)) return undefined
  if (enumeratedValues[property]?.has(normalized)) return normalized
  if (colorProperties.has(property) && safeColor(normalized)) {
    return property === 'background' ? normalized : normalized
  }
  if (lengthProperties.has(property)) return safeLengths(property, normalized)
  if (property === 'font-weight' && /^(?:normal|bold|[1-9]00)$/.test(normalized)) return normalized
  if (property === 'line-height') return safeLineHeight(normalized)
  if (property === 'border-style' && borderStyles.has(normalized)) return normalized
  if (property === 'border' || /^border-(?:top|right|bottom|left)$/.test(property)) {
    const parts = normalized.split(' ')
    return parts.length >= 1 && parts.length <= 3
      && parts.every((part) => safeLengthToken(part, false) || borderStyles.has(part) || safeColor(part))
      ? normalized
      : undefined
  }
  if (property === 'grid-template-columns') {
    const tokens = normalized.split(' ')
    return tokens.length <= 6 && tokens.every((token) => /^(?:[1-6]fr|[1-9][0-9]{0,2}px|[1-9][0-9]?%)$/.test(token))
      ? normalized
      : undefined
  }
  return undefined
}

function safeLengths(property: string, value: string): string | undefined {
  const tokens = value.split(' ')
  if (tokens.length > 4) return undefined
  const negativeAllowed = property.startsWith('margin') || property === 'letter-spacing' || property === 'text-indent'
  return tokens.every((token) => safeLengthToken(token, negativeAllowed)) ? value : undefined
}

function safeLengthToken(value: string, negativeAllowed: boolean): boolean {
  if (value === '0' || value === 'auto') return true
  const match = /^(-?\d+(?:\.\d+)?)(px|rem|em|%|ch)$/.exec(value)
  if (!match || (!negativeAllowed && value.startsWith('-'))) return false
  const amount = Math.abs(Number(match[1]))
  const unit = match[2]
  if (!Number.isFinite(amount)) return false
  if (unit === '%') return amount <= 100
  if (unit === 'rem' || unit === 'em') return amount <= 10
  if (unit === 'ch') return amount <= 160
  return amount <= 512
}

function safeLineHeight(value: string): string | undefined {
  if (/^\d(?:\.\d{1,2})?$/.test(value) && Number(value) <= 4) return value
  return safeLengthToken(value, false) ? value : undefined
}

function safeColor(value: string): boolean {
  return /^(?:transparent|currentcolor|#[0-9a-f]{3,8}|[a-z]{3,24})$/.test(value)
    || /^(?:rgb|rgba|hsl|hsla)\([0-9.,% +\-]+\)$/.test(value)
}
