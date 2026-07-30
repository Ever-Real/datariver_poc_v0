import { afterEach, describe, expect, it } from 'vitest'
import {
  qualityLocationFromHref,
  qualityUrl,
  sanitizeQualityUrl,
} from './qualityLocation'

afterEach(() => window.history.replaceState({}, '', '/'))

describe('qualityLocation', () => {
  it('keeps only the allowlisted quality route state', () => {
    const href = 'https://example.test/?page=quality&workspace=w-1&qualityTab=runs&runId=run%2F1&token=secret'

    expect(qualityLocationFromHref(href)).toEqual({ tab: 'runs', runId: 'run/1' })
    expect(sanitizeQualityUrl(href)).toBe('/?page=quality&workspace=w-1&qualityTab=runs&runId=run%2F1')
  })

  it('drops invalid tabs, oversized opaque identifiers and cross-tab identifiers', () => {
    const oversized = 'x'.repeat(201)
    const href = `https://example.test/?page=quality&qualityTab=unknown&ruleSetId=rule-1&runId=${oversized}`

    expect(qualityLocationFromHref(href)).toEqual({ tab: 'overview', ruleSetId: 'rule-1' })
    expect(sanitizeQualityUrl(href)).toBe('/?page=quality')
  })

  it('does not preserve a selected row when switching tabs', () => {
    const href = 'https://example.test/?page=quality&qualityTab=runs&runId=run-1'
    expect(qualityUrl({ tab: 'rules' }, href)).toBe('/?page=quality&qualityTab=rules')
  })
})
