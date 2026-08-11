import { describe, expect, it, vi } from 'vitest'
import { installPocRandomUuidCompatibility, pocRandomUuid } from './pocUuidCompat'

describe('POC UUID compatibility', () => {
  it('creates RFC 4122 version-4 identifiers using getRandomValues only', () => {
    const fill = vi.fn((bytes: Uint8Array<ArrayBuffer>) => { bytes.fill(0x2a) })
    expect(pocRandomUuid(fill)).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
    expect(fill).toHaveBeenCalledOnce()
  })

  it('installs randomUUID for an insecure-context POC Crypto surface', () => {
    const provider = {
      getRandomValues<T extends Exclude<BufferSource, ArrayBuffer>>(bytes: T): T {
        new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength).fill(0x11)
        return bytes
      },
    } as Crypto
    installPocRandomUuidCompatibility(provider)
    expect(provider.randomUUID()).toMatch(/^[0-9a-f-]{36}$/)
  })
})
