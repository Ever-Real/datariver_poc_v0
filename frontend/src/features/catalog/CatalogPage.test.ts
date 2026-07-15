import { describe, expect, it } from 'vitest'
import { validCatalogQuery } from './CatalogPage'

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
