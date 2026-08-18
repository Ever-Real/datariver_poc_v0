import { describe, expect, it } from 'vitest'
import {
  pageFromLocation,
  pageUrl,
  pocAuthorizationAllowsPage,
  pocCapabilityForPage,
  pocNavigationForCapabilities,
} from './navigation'

describe('navigation contract', () => {
  it('rejects unknown pages and preserves only typed destinations', () => {
    expect(pageFromLocation('https://catalog.example/?page=knowledge')).toBe('knowledge')
    expect(pageFromLocation('https://catalog.example/?page=knowledge-studio')).toBe('knowledge-studio')
    expect(pageFromLocation('https://catalog.example/?page=change-management')).toBe('change-management')
    expect(pageFromLocation('https://catalog.example/?page=monitoring')).toBe('monitoring')
    expect(pageFromLocation('https://catalog.example/?page=not-a-page')).toBe('dashboard')
  })

  it('encodes a global query without preloading catalog data', () => {
    expect(pageUrl('catalog', {
      query: '웨이퍼 A&B',
      href: 'https://catalog.example/app?page=dashboard#result',
    })).toBe('/app?page=catalog&q=%EC%9B%A8%EC%9D%B4%ED%8D%BC+A%26B#result')
    expect(pageUrl('dashboard', {
      href: 'https://catalog.example/app?page=catalog&q=stale',
    })).toBe('/app?page=dashboard')
  })

  it('cleans only Knowledge-owned route state when leaving its surfaces', () => {
    expect(pageUrl('knowledge-studio', {
      href: 'https://catalog.example/app?page=knowledge&workspace=ws&asset=asset-1&drawerTab=api',
    })).toBe('/app?page=knowledge-studio&workspace=ws')
    expect(pageUrl('monitoring', {
      href: 'https://catalog.example/app?page=knowledge-studio&workspace=ws&draft=draft-1&step=tbox&monitorTab=jobs',
    })).toBe('/app?page=monitoring&workspace=ws&monitorTab=jobs')
  })

  it('derives POC navigation and direct-page requirements from server capabilities', () => {
    expect(pocNavigationForCapabilities([
      'catalog.read', 'chat.query', 'change.read', 'quality.read',
      'knowledge.read', 'monitoring.read',
    ], 'viewer').map(({ id }) => id)).toEqual([
      'catalog', 'change-management', 'monitoring',
      'governance', 'chat',
    ])
    expect(pocCapabilityForPage('registration')).toBe('catalog.execute')
    expect(pocCapabilityForPage('knowledge-studio')).toBe('knowledge.manage')
    expect(pocCapabilityForPage('admin')).toBe('admin.manage')
    expect(pocCapabilityForPage('dashboard')).toBeUndefined()
  })

  it('keeps Registration out of top navigation while preserving its direct-page role gate', () => {
    const managerCapabilities = ['catalog.read', 'catalog.execute', 'catalog.manage'] as const
    expect(pocNavigationForCapabilities(managerCapabilities, 'manager').map(({ id }) => id))
      .toEqual(['catalog'])
    expect(pocNavigationForCapabilities(managerCapabilities, 'data_steward').map(({ id }) => id))
      .toEqual(['catalog'])
    expect(pocNavigationForCapabilities(managerCapabilities, 'admin').map(({ id }) => id))
      .toEqual(['catalog'])
    expect(pocAuthorizationAllowsPage('registration', managerCapabilities, 'manager')).toBe(false)
    expect(pocAuthorizationAllowsPage('registration', managerCapabilities, 'data_steward')).toBe(true)
    expect(pocAuthorizationAllowsPage('registration', managerCapabilities, 'admin')).toBe(true)
  })
})
