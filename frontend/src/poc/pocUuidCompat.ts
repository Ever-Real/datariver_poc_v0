function byteHex(value: number): string {
  return value.toString(16).padStart(2, '0')
}

type FillRandomValues = (bytes: Uint8Array<ArrayBuffer>) => void

export function pocRandomUuid(
  fillRandomValues: FillRandomValues = (bytes) => { globalThis.crypto.getRandomValues(bytes) },
): `${string}-${string}-${string}-${string}-${string}` {
  const bytes = new Uint8Array(16)
  fillRandomValues(bytes)
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80
  const hex = Array.from(bytes, byteHex).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

export function installPocRandomUuidCompatibility(cryptoProvider: Crypto = globalThis.crypto): void {
  if (typeof cryptoProvider.randomUUID === 'function') return
  Object.defineProperty(cryptoProvider, 'randomUUID', {
    configurable: true,
    value: () => pocRandomUuid((bytes) => { cryptoProvider.getRandomValues(bytes) }),
  })
}
