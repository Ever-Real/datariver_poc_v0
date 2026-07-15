import { describe, expect, it } from 'vitest'
import { supportedContentType } from './RegistrationPage'

describe('supportedContentType', () => {
  it('uses a stable server contract when browsers report alternate parquet MIME types', () => {
    expect(supportedContentType({ name: 'assets.parquet', type: 'application/vnd.apache.parquet' }))
      .toBe('application/x-parquet')
  })

  it('rejects executable extensions even when the browser MIME is empty', () => {
    expect(() => supportedContentType({ name: 'payload.exe', type: '' })).toThrow()
  })
})
