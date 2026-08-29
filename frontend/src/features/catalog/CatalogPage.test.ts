import { describe, expect, it } from 'vitest'
import { boundedDetailHistory, validCatalogQuery } from './CatalogPage'

describe('validCatalogQuery', () => {
  it('allows an empty browse and queries of at least two trimmed characters', () => {
    expect(validCatalogQuery('')).toBe(true)
    expect(validCatalogQuery('  ')).toBe(true)
    expect(validCatalogQuery('수율')).toBe(true)
  })

  it('rejects a one-character query before calling the API', () => {
    expect(validCatalogQuery('x')).toBe(false)
    expect(validCatalogQuery(' x ')).toBe(false)
  })
})

describe('boundedDetailHistory', () => {
  it('retains only the latest twenty detail identities', () => {
    const history = Array.from({ length: 25 }, (_, index) => `asset-${index}`)
      .reduce(boundedDetailHistory, [])

    expect(history).toHaveLength(20)
    expect(history[0]).toBe('asset-5')
    expect(history.at(-1)).toBe('asset-24')
  })
})
