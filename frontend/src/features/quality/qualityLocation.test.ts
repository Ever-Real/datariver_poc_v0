import { afterEach, describe, expect, it } from 'vitest'
import {
  qualityLocationFromHref,
  qualityUrl,
  sanitizeQualityUrl,
} from './qualityLocation'

afterEach(() => window.history.replaceState({}, '', '/'))

describe('qualityLocation', () => {
  it('keeps only the allowlisted quality route state', () => {
    const href = 'https://example.test/?page=quality&workspace=w-1&qualityTab=templates&templateId=template%2F1&token=secret'

    expect(qualityLocationFromHref(href)).toEqual({
      tab: 'templates',
      templateId: 'template/1',
    })
    expect(sanitizeQualityUrl(href)).toBe(
      '/?page=quality&workspace=w-1&qualityTab=templates&templateId=template%2F1',
    )
  })

  it('drops invalid tabs, oversized opaque identifiers and cross-tab identifiers', () => {
    const oversized = 'x'.repeat(201)
    const href = `https://example.test/?page=quality&qualityTab=unknown&assetId=asset-1&templateId=${oversized}`

    expect(qualityLocationFromHref(href)).toEqual({ tab: 'assets', assetId: 'asset-1' })
    expect(sanitizeQualityUrl(href)).toBe('/?page=quality&assetId=asset-1')
  })

  it('does not preserve a selected row when switching tabs', () => {
    const href = 'https://example.test/?page=quality&assetId=asset-1'
    expect(qualityUrl({ tab: 'templates' }, href)).toBe(
      '/?page=quality&qualityTab=templates',
    )
  })
})
