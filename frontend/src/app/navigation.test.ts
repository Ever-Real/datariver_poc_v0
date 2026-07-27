import { describe, expect, it } from 'vitest'
import { pageFromLocation, pageUrl } from './navigation'

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
})
