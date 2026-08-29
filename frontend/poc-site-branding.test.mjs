/* global Buffer, structuredClone */
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  POC_SITE_BRANDING_MAX_LOGO_BYTES,
  applySiteBrandingUpdate,
  defaultSiteBrandingDocument,
  normalizeSiteBrandingDocument,
  publicSiteBranding,
} from './poc-site-branding.mjs'

const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
const jpeg = '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAf/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAH/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAEFAqf/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAEDAQE/Aaf/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAECAQE/Aaf/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAY/Aqf/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAE/IV//2gAMAwEAAgADAAAAEP/EABQRAQAAAAAAAAAAAAAAAAAAABD/2gAIAQMBAT8QH//EABQRAQAAAAAAAAAAAAAAAAAAABD/2gAIAQIBAT8QH//EABQQAQAAAAAAAAAAAAAAAAAAABD/2gAIAQEAAT8QH//Z'
const commandContext = {
  actor: 'generic-admin',
  idempotencyKey: 'generic-branding-request',
  version: 1,
  occurredAt: '2026-08-29T00:00:00.000Z',
}

function update(overrides = {}, context = commandContext) {
  return applySiteBrandingUpdate(defaultSiteBrandingDocument(), {
    site_name: 'Generic Portal',
    logo: { mime_type: 'image/png', data_base64: png },
    favicon: null,
    restore_default: false,
    ...overrides,
  }, context)
}

function pngIco() {
  const image = Buffer.from(png, 'base64')
  const header = Buffer.alloc(22)
  header.writeUInt16LE(1, 2)
  header.writeUInt16LE(1, 4)
  header[6] = 1
  header[7] = 1
  header.writeUInt16LE(1, 10)
  header.writeUInt16LE(32, 12)
  header.writeUInt32LE(image.length, 14)
  header.writeUInt32LE(header.length, 18)
  return Buffer.concat([header, image]).toString('base64')
}

function dibIco() {
  const image = Buffer.alloc(48)
  image.writeUInt32LE(40, 0)
  image.writeInt32LE(1, 4)
  image.writeInt32LE(2, 8)
  image.writeUInt16LE(1, 12)
  image.writeUInt16LE(32, 14)
  image.writeUInt32LE(4, 20)
  image.set([0x00, 0x00, 0xff, 0xff], 40)
  const header = Buffer.alloc(22)
  header.writeUInt16LE(1, 2)
  header.writeUInt16LE(1, 4)
  header[6] = 1
  header[7] = 1
  header.writeUInt16LE(1, 10)
  header.writeUInt16LE(32, 12)
  header.writeUInt32LE(image.length, 14)
  header.writeUInt32LE(header.length, 18)
  return Buffer.concat([header, image]).toString('base64')
}

test('stores a random raster identity and exposes only the safe public projection', () => {
  const applied = update()
  assert.match(applied.projection.logo.asset_id, /^[0-9a-f-]{36}$/)
  assert.equal(applied.projection.logo.mime_type, 'image/png')
  assert.equal(applied.projection.logo.data_url, `data:image/png;base64,${png}`)
  assert.deepEqual(Object.keys(applied.projection).sort(), ['favicon', 'logo', 'site_name'])
  assert.equal(Object.hasOwn(applied.projection, 'updated_by'), false)
  assert.deepEqual(publicSiteBranding(normalizeSiteBrandingDocument(applied.document)), applied.projection)
})

test('accepts a bounded ICO whose exact directory entry contains one validated PNG', () => {
  const applied = update({ favicon: { mime_type: 'image/x-icon', data_base64: pngIco() } })
  assert.equal(applied.projection.favicon.mime_type, 'image/x-icon')
  assert.equal(applied.projection.favicon.byte_size, 90)
})

test('accepts an ordinary JPEG logo and an exact DIB-backed ICO favicon', () => {
  const applied = update({
    logo: { mime_type: 'image/jpeg', data_base64: jpeg },
    favicon: { mime_type: 'image/x-icon', data_base64: dibIco() },
  })
  assert.equal(applied.projection.logo.mime_type, 'image/jpeg')
  assert.equal(applied.projection.logo.byte_size, 516)
  assert.equal(applied.projection.favicon.mime_type, 'image/x-icon')
  assert.equal(applied.projection.favicon.byte_size, 70)
})

test('rejects malformed base64, mismatched magic, SVG MIME and decoded oversize', () => {
  const cases = [
    [{ logo: { mime_type: 'image/png', data_base64: 'not-base64!' } }, 'SITE_BRANDING_ASSET_ENCODING_INVALID'],
    [{ logo: { mime_type: 'image/jpeg', data_base64: png } }, 'SITE_BRANDING_ASSET_CONTENT_INVALID'],
    [{ logo: { mime_type: 'image/svg+xml', data_base64: Buffer.from('<svg/>').toString('base64') } }, 'SITE_BRANDING_ASSET_MIME_INVALID'],
    [{ logo: { mime_type: 'image/png', data_base64: Buffer.alloc(POC_SITE_BRANDING_MAX_LOGO_BYTES + 1).toString('base64') } }, 'SITE_BRANDING_ASSET_SIZE_INVALID'],
  ]
  for (const [body, code] of cases) assert.throws(() => update(body), { code })
})

test('rejects valid image bytes with a trailing polyglot payload', () => {
  const bytes = Buffer.concat([Buffer.from(png, 'base64'), Buffer.from('<script>generic()</script>')])
  assert.throws(() => update({
    logo: { mime_type: 'image/png', data_base64: bytes.toString('base64') },
  }), { code: 'SITE_BRANDING_ASSET_CONTENT_INVALID' })
})

test('requires exact fields and current asset references', () => {
  assert.throws(() => applySiteBrandingUpdate(defaultSiteBrandingDocument(), {
    site_name: 'Generic Portal', logo: null, favicon: null, restore_default: false, filename: '../logo.png',
  }, commandContext), { code: 'SITE_BRANDING_INPUT_INVALID' })
  assert.throws(() => update({ logo: { asset_id: 'not-current' } }), {
    code: 'SITE_BRANDING_ASSET_REFERENCE_INVALID',
  })
})

test('restores defaults through CAS-compatible input and preserves durable replay results', () => {
  const first = update()
  const replay = applySiteBrandingUpdate(first.document, {
    restore_default: false,
    favicon: null,
    logo: { data_base64: png, mime_type: 'image/png' },
    site_name: 'Generic Portal',
  }, commandContext)
  assert.equal(replay.replay, true)
  assert.deepEqual(replay.projection, first.projection)
  assert.throws(() => applySiteBrandingUpdate(first.document, {
    site_name: null, logo: null, favicon: null, restore_default: true,
  }, commandContext), { code: 'SITE_BRANDING_IDEMPOTENCY_CONFLICT' })

  const restored = applySiteBrandingUpdate(first.document, {
    site_name: null, logo: null, favicon: null, restore_default: true,
  }, { ...commandContext, idempotencyKey: 'generic-restore-request', version: 2 })
  assert.deepEqual(restored.projection, { site_name: 'DataRiver', logo: null, favicon: null })
})

test('normalizes every durable replay projection and fails closed on copied or incoherent state', () => {
  const applied = update()
  const invalidDocuments = [
    structuredClone(applied.document),
    structuredClone(applied.document),
    structuredClone(applied.document),
  ]
  invalidDocuments[0].idempotency_receipts[0].projection.updated_by = 'must-not-leak'
  invalidDocuments[1].idempotency_receipts[0].projection.logo.byte_size += 1
  invalidDocuments[2].idempotency_receipts[0].projection.logo.data_url = `data:image/jpeg;base64,${png}`
  for (const document of invalidDocuments) {
    assert.throws(() => normalizeSiteBrandingDocument(document), {
      code: 'SITE_BRANDING_STATE_INVALID', statusCode: 503,
    })
  }
})
