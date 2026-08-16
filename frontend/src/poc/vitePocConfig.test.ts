import { describe, expect, it } from 'vitest'

import { pocDevelopmentHost } from '../../vite.poc.config'

describe('POC development listener containment', () => {
  it('defaults to loopback', () => {
    expect(pocDevelopmentHost({})).toBe('127.0.0.1')
  })

  it('preserves an explicit Docker-compatible override', () => {
    expect(pocDevelopmentHost({ POC_SERVER_HOST: ' 0.0.0.0 ' })).toBe('0.0.0.0')
  })
})
