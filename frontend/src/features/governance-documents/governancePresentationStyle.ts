const maximumPresentationCharacters = 256

const allowedValues: Readonly<Record<string, ReadonlySet<string>>> = {
  'font-size': new Set(['10px', '12px', '14px', '16px', '18px', '24px', '32px']),
  'padding-left': new Set(['2em', '4em', '6em', '8em', '10em', '12em']),
  'text-align': new Set(['center', 'right']),
  'background-color': new Set(['#f4f8fa', '#fff3f2', '#eff9f2', '#fff9e9']),
}

const propertyOrder = ['font-size', 'padding-left', 'text-align', 'background-color'] as const

export function safeGovernancePresentation(
  value: string | null | undefined,
  options: { allowBackground?: boolean } = {},
): string {
  if (!value) return ''
  const declarations = new Map<string, string>()
  for (const raw of value.slice(0, maximumPresentationCharacters).replace(/\/\*[\s\S]*?\*\//g, '').split(';')) {
    const delimiter = raw.indexOf(':')
    if (delimiter <= 0) continue
    const property = raw.slice(0, delimiter).trim().toLocaleLowerCase()
    const candidate = raw.slice(delimiter + 1).trim().toLocaleLowerCase()
    if (property === 'background-color' && !options.allowBackground) continue
    if (allowedValues[property]?.has(candidate)) declarations.set(property, candidate)
  }
  return propertyOrder
    .flatMap((property) => {
      const candidate = declarations.get(property)
      return candidate ? [`${property}:${candidate}`] : []
    })
    .join(';')
}

export function mergeGovernancePresentations(...values: Array<string | null | undefined>): string {
  return safeGovernancePresentation(values.filter(Boolean).join(';'))
}

export function mergeGovernanceTableCellPresentations(
  ...values: Array<string | null | undefined>
): string {
  return safeGovernancePresentation(values.filter(Boolean).join(';'), { allowBackground: true })
}
