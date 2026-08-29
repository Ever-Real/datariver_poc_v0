/* global Buffer, structuredClone */
import { createHash, randomUUID } from 'node:crypto'

export const POC_SITE_BRANDING_SCOPE = 'site-branding-v1'
export const POC_SITE_BRANDING_DEFAULT_NAME = 'DataRiver'
export const POC_SITE_BRANDING_MAX_LOGO_BYTES = 512 * 1024
export const POC_SITE_BRANDING_MAX_FAVICON_BYTES = 128 * 1024

const assetKinds = Object.freeze({
  logo: new Set(['image/png', 'image/jpeg']),
  favicon: new Set(['image/png', 'image/x-icon']),
})
const maximumDimension = 4096
const maximumReceipts = 32
const assetIdPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

function brandingError(code, message, statusCode = 400) {
  return Object.assign(new Error(message), { code, statusCode })
}

function brandingStateError() {
  return brandingError('SITE_BRANDING_STATE_INVALID', 'Stored site branding is malformed.', 503)
}

function exactKeys(value, expected) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const keys = Object.keys(value).sort()
  const sorted = [...expected].sort()
  return keys.length === sorted.length && keys.every((key, index) => key === sorted[index])
}

function validSiteName(value) {
  return typeof value === 'string' && value === value.trim() && value.length >= 1 && value.length <= 80
    && ![...value].some((character) => {
      const code = character.codePointAt(0)
      return code <= 0x1f || code === 0x7f
    })
}

function crc32(buffer) {
  let crc = 0xffffffff
  for (const byte of buffer) {
    crc ^= byte
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1))
  }
  return (crc ^ 0xffffffff) >>> 0
}

function validatePng(bytes) {
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])
  if (bytes.length < 45 || !bytes.subarray(0, 8).equals(signature)) return false
  let offset = 8
  let chunks = 0
  let sawHeader = false
  while (offset + 12 <= bytes.length && chunks < 10_000) {
    const length = bytes.readUInt32BE(offset)
    const end = offset + 12 + length
    if (end > bytes.length) return false
    const type = bytes.subarray(offset + 4, offset + 8)
    if (![...type].every((byte) => (byte >= 65 && byte <= 90) || (byte >= 97 && byte <= 122))) return false
    const body = bytes.subarray(offset + 4, offset + 8 + length)
    if (crc32(body) !== bytes.readUInt32BE(offset + 8 + length)) return false
    const name = type.toString('ascii')
    if (!sawHeader) {
      if (name !== 'IHDR' || length !== 13) return false
      const width = bytes.readUInt32BE(offset + 8)
      const height = bytes.readUInt32BE(offset + 12)
      if (width < 1 || height < 1 || width > maximumDimension || height > maximumDimension) return false
      sawHeader = true
    } else if (name === 'IHDR') return false
    offset = end
    chunks += 1
    if (name === 'IEND') return length === 0 && offset === bytes.length
  }
  return false
}

function validateJpeg(bytes) {
  if (bytes.length < 20 || bytes[0] !== 0xff || bytes[1] !== 0xd8) return false
  let offset = 2
  let sawFrame = false
  let inScan = false
  while (offset < bytes.length) {
    if (inScan) {
      while (offset < bytes.length) {
        if (bytes[offset] !== 0xff) { offset += 1; continue }
        let markerOffset = offset
        while (bytes[markerOffset] === 0xff) markerOffset += 1
        if (markerOffset >= bytes.length) return false
        if (bytes[markerOffset] === 0x00 || (bytes[markerOffset] >= 0xd0 && bytes[markerOffset] <= 0xd7)) {
          offset = markerOffset + 1
          continue
        }
        offset = markerOffset - 1
        inScan = false
        break
      }
      if (inScan) return false
    }
    if (bytes[offset] !== 0xff) return false
    while (bytes[offset] === 0xff) offset += 1
    if (offset >= bytes.length) return false
    const marker = bytes[offset]
    offset += 1
    if (marker === 0xd9) return sawFrame && offset === bytes.length
    if (marker === 0xd8 || marker === 0x00 || (marker >= 0xd0 && marker <= 0xd7)) return false
    if (offset + 2 > bytes.length) return false
    const length = bytes.readUInt16BE(offset)
    if (length < 2 || offset + length > bytes.length) return false
    const frameMarker = (marker >= 0xc0 && marker <= 0xc3)
      || (marker >= 0xc5 && marker <= 0xc7)
      || (marker >= 0xc9 && marker <= 0xcb)
      || (marker >= 0xcd && marker <= 0xcf)
    if (frameMarker) {
      if (length < 8) return false
      const height = bytes.readUInt16BE(offset + 3)
      const width = bytes.readUInt16BE(offset + 5)
      if (width < 1 || height < 1 || width > maximumDimension || height > maximumDimension) return false
      sawFrame = true
    }
    offset += length
    if (marker === 0xda) inScan = true
  }
  return false
}

function validateIco(bytes) {
  if (bytes.length < 22 || bytes.readUInt16LE(0) !== 0 || bytes.readUInt16LE(2) !== 1) return false
  const count = bytes.readUInt16LE(4)
  const directoryEnd = 6 + count * 16
  if (count < 1 || count > 16 || directoryEnd > bytes.length) return false
  const ranges = []
  for (let index = 0; index < count; index += 1) {
    const entry = 6 + index * 16
    const width = bytes[entry] || 256
    const height = bytes[entry + 1] || 256
    const size = bytes.readUInt32LE(entry + 8)
    const offset = bytes.readUInt32LE(entry + 12)
    if (width > 256 || height > 256 || size < 16 || offset < directoryEnd || offset + size > bytes.length) return false
    const image = bytes.subarray(offset, offset + size)
    const png = validatePng(image)
    if (!png) {
      const dibHeader = image.readUInt32LE(0)
      if (![40, 108, 124].includes(dibHeader) || dibHeader > image.length) return false
      const dibWidth = image.readInt32LE(4)
      const doubledHeight = image.readInt32LE(8)
      const planes = image.readUInt16LE(12)
      const bitCount = image.readUInt16LE(14)
      const compression = image.length >= 20 ? image.readUInt32LE(16) : 0
      if (dibWidth < 1 || doubledHeight < 2 || doubledHeight % 2 !== 0 || dibWidth > 256 || doubledHeight > 512
        || planes !== 1 || ![1, 4, 8, 24, 32].includes(bitCount) || ![0, 3].includes(compression)) return false
      const imageHeight = doubledHeight / 2
      if (dibWidth !== width || imageHeight !== height) return false
      const colorsUsed = dibHeader >= 40 ? image.readUInt32LE(32) : 0
      const paletteEntries = bitCount <= 8 ? (colorsUsed || 2 ** bitCount) : 0
      if (paletteEntries > 256 || (compression === 3 && bitCount < 16)) return false
      const masksSize = dibHeader === 40 && compression === 3 ? 12 : 0
      const paletteSize = paletteEntries * 4
      const xorSize = Math.ceil(dibWidth * bitCount / 32) * 4 * imageHeight
      const andSize = Math.ceil(dibWidth / 32) * 4 * imageHeight
      if (dibHeader + masksSize + paletteSize + xorSize + andSize !== image.length) return false
    }
    ranges.push([offset, offset + size])
  }
  ranges.sort((left, right) => left[0] - right[0])
  if (ranges.some((range, index) => index > 0 && range[0] < ranges[index - 1][1])) return false
  return ranges.at(-1)[1] === bytes.length
}

function decodeBase64(value, maximumBytes) {
  if (typeof value !== 'string' || value.length < 4 || value.length > Math.ceil(maximumBytes / 3) * 4
    || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value)) {
    throw brandingError('SITE_BRANDING_ASSET_ENCODING_INVALID', 'Branding asset data must be canonical bounded base64.')
  }
  const bytes = Buffer.from(value, 'base64')
  if (!bytes.length || bytes.length > maximumBytes || bytes.toString('base64') !== value) {
    throw brandingError('SITE_BRANDING_ASSET_SIZE_INVALID', 'Branding asset decoded size is outside the allowed bound.', 413)
  }
  return bytes
}

function validateAssetInput(value, kind) {
  if (!exactKeys(value, ['mime_type', 'data_base64'])) {
    throw brandingError('SITE_BRANDING_ASSET_INVALID', `${kind} must contain only mime_type and data_base64.`)
  }
  const mimeType = value.mime_type
  if (!assetKinds[kind].has(mimeType)) {
    throw brandingError('SITE_BRANDING_ASSET_MIME_INVALID', `${kind} MIME type is not allowed.`)
  }
  const maximumBytes = kind === 'logo' ? POC_SITE_BRANDING_MAX_LOGO_BYTES : POC_SITE_BRANDING_MAX_FAVICON_BYTES
  const bytes = decodeBase64(value.data_base64, maximumBytes)
  const valid = mimeType === 'image/png' ? validatePng(bytes)
    : mimeType === 'image/jpeg' ? validateJpeg(bytes)
      : validateIco(bytes)
  if (!valid) {
    throw brandingError('SITE_BRANDING_ASSET_CONTENT_INVALID', `${kind} content does not match its declared safe raster format.`)
  }
  return {
    asset_id: randomUUID(),
    mime_type: mimeType,
    byte_size: bytes.length,
    data_base64: value.data_base64,
  }
}

function normalizeStoredAsset(value, kind) {
  if (value === null) return null
  if (!exactKeys(value, ['asset_id', 'mime_type', 'byte_size', 'data_base64'])
    || typeof value.asset_id !== 'string' || !assetIdPattern.test(value.asset_id)) {
    throw brandingStateError()
  }
  try {
    const validated = validateAssetInput({ mime_type: value.mime_type, data_base64: value.data_base64 }, kind)
    if (validated.byte_size !== value.byte_size) throw brandingStateError()
    return { ...validated, asset_id: value.asset_id }
  } catch (error) {
    if (error?.code === 'SITE_BRANDING_STATE_INVALID') throw error
    throw brandingStateError()
  }
}

function normalizePublicAsset(value, kind) {
  if (value === null) return null
  if (!exactKeys(value, ['asset_id', 'mime_type', 'byte_size', 'data_url'])
    || typeof value.asset_id !== 'string' || !assetIdPattern.test(value.asset_id)
    || typeof value.data_url !== 'string' || typeof value.mime_type !== 'string'
    || !value.data_url.startsWith(`data:${value.mime_type};base64,`)) {
    throw brandingStateError()
  }
  try {
    const dataBase64 = value.data_url.slice(`data:${value.mime_type};base64,`.length)
    const validated = validateAssetInput({ mime_type: value.mime_type, data_base64: dataBase64 }, kind)
    if (validated.byte_size !== value.byte_size) throw brandingStateError()
    return {
      asset_id: value.asset_id,
      mime_type: validated.mime_type,
      byte_size: validated.byte_size,
      data_url: value.data_url,
    }
  } catch (error) {
    if (error?.code === 'SITE_BRANDING_STATE_INVALID') throw error
    throw brandingStateError()
  }
}

function normalizePublicProjection(value) {
  if (!exactKeys(value, ['site_name', 'logo', 'favicon']) || !validSiteName(value.site_name)) {
    throw brandingStateError()
  }
  return {
    site_name: value.site_name,
    logo: normalizePublicAsset(value.logo, 'logo'),
    favicon: normalizePublicAsset(value.favicon, 'favicon'),
  }
}

export function defaultSiteBrandingDocument() {
  return {
    schema_version: 1,
    site_name: POC_SITE_BRANDING_DEFAULT_NAME,
    logo: null,
    favicon: null,
    updated_at: null,
    updated_by: null,
    idempotency_receipts: [],
  }
}

export function normalizeSiteBrandingDocument(value) {
  if (value === null || value === undefined) return defaultSiteBrandingDocument()
  if (!exactKeys(value, [
    'schema_version', 'site_name', 'logo', 'favicon', 'updated_at', 'updated_by', 'idempotency_receipts',
  ]) || value.schema_version !== 1 || !validSiteName(value.site_name)
    || (value.updated_at !== null && typeof value.updated_at !== 'string')
    || (value.updated_by !== null && typeof value.updated_by !== 'string')
    || !Array.isArray(value.idempotency_receipts) || value.idempotency_receipts.length > maximumReceipts) {
    throw brandingError('SITE_BRANDING_STATE_INVALID', 'Stored site branding is malformed.', 503)
  }
  const receipts = value.idempotency_receipts.map((receipt) => {
    if (!exactKeys(receipt, ['key_hash', 'request_hash', 'version', 'projection'])
      || !/^[0-9a-f]{64}$/.test(receipt.key_hash) || !/^[0-9a-f]{64}$/.test(receipt.request_hash)
      || !Number.isSafeInteger(receipt.version) || receipt.version < 1) {
      throw brandingStateError()
    }
    return {
      key_hash: receipt.key_hash,
      request_hash: receipt.request_hash,
      version: receipt.version,
      projection: normalizePublicProjection(receipt.projection),
    }
  })
  return {
    schema_version: 1,
    site_name: value.site_name,
    logo: normalizeStoredAsset(value.logo, 'logo'),
    favicon: normalizeStoredAsset(value.favicon, 'favicon'),
    updated_at: value.updated_at,
    updated_by: value.updated_by,
    idempotency_receipts: receipts,
  }
}

function publicAsset(asset) {
  return asset ? {
    asset_id: asset.asset_id,
    mime_type: asset.mime_type,
    byte_size: asset.byte_size,
    data_url: `data:${asset.mime_type};base64,${asset.data_base64}`,
  } : null
}

export function publicSiteBranding(document) {
  return {
    site_name: document.site_name,
    logo: publicAsset(document.logo),
    favicon: publicAsset(document.favicon),
  }
}

function resolveAsset(value, kind, current) {
  if (value === null) return null
  if (exactKeys(value, ['asset_id'])) {
    if (!current || value.asset_id !== current.asset_id) {
      throw brandingError('SITE_BRANDING_ASSET_REFERENCE_INVALID', `${kind} asset reference is not current.`)
    }
    return current
  }
  return validateAssetInput(value, kind)
}

export function siteBrandingRequestHash(body) {
  const canonicalize = (value) => {
    if (Array.isArray(value)) return value.map(canonicalize)
    if (!value || typeof value !== 'object') return value
    return Object.fromEntries(Object.entries(value)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, nested]) => [key, canonicalize(nested)]))
  }
  const canonical = canonicalize(body)
  return createHash('sha256').update(JSON.stringify(canonical), 'utf8').digest('hex')
}

export function siteBrandingIdempotencyHash(key) {
  return createHash('sha256').update(key, 'utf8').digest('hex')
}

export function applySiteBrandingUpdate(current, body, { actor, idempotencyKey, version, occurredAt }) {
  if (!exactKeys(body, ['site_name', 'logo', 'favicon', 'restore_default'])
    || typeof body.restore_default !== 'boolean') {
    throw brandingError('SITE_BRANDING_INPUT_INVALID', 'Site branding requires the exact fixed fields.')
  }
  const keyHash = siteBrandingIdempotencyHash(idempotencyKey)
  const requestHash = siteBrandingRequestHash(body)
  const replay = current.idempotency_receipts.find((receipt) => receipt.key_hash === keyHash)
  if (replay) {
    if (replay.request_hash !== requestHash) {
      throw brandingError('SITE_BRANDING_IDEMPOTENCY_CONFLICT', 'The Idempotency-Key is already bound to another site branding request.', 409)
    }
    return { replay: true, version: replay.version, projection: structuredClone(replay.projection), document: current }
  }
  let next
  if (body.restore_default) {
    if (body.site_name !== null || body.logo !== null || body.favicon !== null) {
      throw brandingError('SITE_BRANDING_INPUT_INVALID', 'Default restore requires null site_name, logo and favicon fields.')
    }
    next = defaultSiteBrandingDocument()
  } else {
    if (typeof body.site_name !== 'string' || !body.site_name.trim() || body.site_name.length > 80
      || [...body.site_name].some((character) => {
        const code = character.codePointAt(0)
        return code <= 0x1f || code === 0x7f
      })) {
      throw brandingError('SITE_BRANDING_NAME_INVALID', 'Site name must contain 1-80 visible characters.')
    }
    next = {
      ...defaultSiteBrandingDocument(),
      site_name: body.site_name.trim(),
      logo: resolveAsset(body.logo, 'logo', current.logo),
      favicon: resolveAsset(body.favicon, 'favicon', current.favicon),
    }
  }
  next.updated_at = occurredAt
  next.updated_by = actor
  const projection = publicSiteBranding(next)
  next.idempotency_receipts = [...current.idempotency_receipts, {
    key_hash: keyHash,
    request_hash: requestHash,
    version,
    projection,
  }].slice(-maximumReceipts)
  return { replay: false, version, projection, document: next }
}
