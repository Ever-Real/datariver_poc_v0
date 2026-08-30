import { describe, expect, it } from 'vitest'
import {
  changeRequestStateGroupFromLocation,
  pageFromLocation,
  pageUrl,
  pocAuthorizationAllowsPage,
  pocCapabilityForPage,
  pocNavigationForCapabilities,
} from './navigation'

describe('navigation contract', () => {
  it('keeps Monitoring and canonical Change Management hard-reload routes distinct', () => {
    expect(pageFromLocation('https://catalog.example/?page=knowledge')).toBe('knowledge')
    expect(pageFromLocation('https://catalog.example/?page=knowledge-studio')).toBe('knowledge-studio')
    expect(pageFromLocation('https://catalog.example/?page=change-management')).toBe('change-management')
    expect(pageFromLocation('https://catalog.example/?page=monitoring')).toBe('monitoring')
    expect(pageFromLocation('https://catalog.example/?page=admin&adminSection=dictionary')).toBe('glossary')
    expect(pageFromLocation('https://catalog.example/?page=admin&adminSection=poc-glossary')).toBe('glossary')
    expect(pageFromLocation('https://catalog.example/?page=not-a-page')).toBe('dashboard')
  })

  it('builds a direct Change Management bookmark with the current workspace intact', () => {
    expect(pageUrl('change-management', {
      href: 'https://catalog.example/app?page=monitoring&workspace=workspace-1',
    })).toBe('/app?page=change-management&workspace=workspace-1')
  })

  it('builds and validates bounded Change Request group deep links', () => {
    expect(pageUrl('change-management', {
      changeRequestStateGroup: 'IN_PROGRESS',
      href: 'https://catalog.example/app?page=dashboard&workspace=workspace-1',
    })).toBe('/app?page=change-management&workspace=workspace-1&crStateGroup=IN_PROGRESS')
    expect(changeRequestStateGroupFromLocation(
      'https://catalog.example/app?page=change-management&crStateGroup=IN_PROGRESS',
    )).toBe('IN_PROGRESS')
    expect(changeRequestStateGroupFromLocation(
      'https://catalog.example/app?page=change-management&crStateGroup=OPEN',
    )).toBeUndefined()
    expect(pageUrl('dashboard', {
      href: 'https://catalog.example/app?page=change-management&crStateGroup=CLOSED',
    })).toBe('/app?page=dashboard')
  })

  it('encodes a global query without preloading catalog data', () => {
    expect(pageUrl('catalog', {
      query: '웨이퍼 A&B',
      href: 'https://catalog.example/app?page=dashboard#result',
    })).toBe('/app?page=catalog&q=%EC%9B%A8%EC%9D%B4%ED%8D%BC+A%26B#result')

    // Explicit empty query removes q
    expect(pageUrl('catalog', {
      query: '',
      href: 'https://catalog.example/app?page=catalog&q=stale',
    })).toBe('/app?page=catalog')

    // Omitted query preserves existing q
    expect(pageUrl('catalog', {
      href: 'https://catalog.example/app?page=catalog&q=preserve',
    })).toBe('/app?page=catalog&q=preserve')

    // Leaving catalog preserves q but deletes catalogAsset
    expect(pageUrl('dashboard', {
      href: 'https://catalog.example/app?page=catalog&q=stale&catalogAsset=asset-1',
    })).toBe('/app?page=dashboard&q=stale')
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
      'governance', 'glossary', 'chat',
    ])
    expect(pocCapabilityForPage('glossary')).toBe('catalog.read')
    expect(pocCapabilityForPage('registration')).toBe('catalog.read')
    expect(pocCapabilityForPage('knowledge-studio')).toBe('knowledge.manage')
    expect(pocCapabilityForPage('admin')).toBe('admin.manage')
    expect(pocCapabilityForPage('dashboard')).toBeUndefined()
  })

  it('keeps Registration out of top navigation while preserving its direct-page role gate', () => {
    const managerCapabilities = ['catalog.read', 'catalog.execute', 'catalog.manage'] as const
    expect(pocNavigationForCapabilities(managerCapabilities, 'manager').map(({ id }) => id))
      .toEqual(['catalog', 'glossary'])
    expect(pocNavigationForCapabilities(managerCapabilities, 'data_steward').map(({ id }) => id))
      .toEqual(['catalog', 'glossary'])
    expect(pocNavigationForCapabilities(managerCapabilities, 'admin').map(({ id }) => id))
      .toEqual(['catalog', 'glossary'])
    expect(pocAuthorizationAllowsPage('registration', managerCapabilities, 'manager')).toBe(true)
    expect(pocAuthorizationAllowsPage('registration', managerCapabilities, 'data_steward')).toBe(true)
    expect(pocAuthorizationAllowsPage('registration', managerCapabilities, 'admin')).toBe(true)
    expect(pocAuthorizationAllowsPage('registration', managerCapabilities, 'viewer')).toBe(false)
    expect(pocAuthorizationAllowsPage('registration', managerCapabilities, 'developer')).toBe(false)
  })
})
