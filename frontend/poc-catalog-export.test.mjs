import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createPocCatalogExportStore } from './poc-catalog-export.mjs'

const row = (name = 'synthetic') => ({
  asset_id: 'urn:li:dataset:(urn:li:dataPlatform:postgres,synthetic.one,PROD)',
  external_urn: 'urn:li:dataset:(urn:li:dataPlatform:postgres,synthetic.one,PROD)',
  platform: 'postgres', database_name: 'synthetic', schema_name: 'public', name,
  asset_type: 'DATASET', classification: 'INTERNAL', lifecycle: 'ACTIVE',
  description: '설명', source_version: 'datahub-live', observed_at: '2026-08-30T00:00:00.000Z',
})

test('CSV and XLSX artifacts are bounded, formula-safe, owner-bound, and idempotent', () => {
  let instant = new Date('2026-08-30T00:00:00.000Z')
  const store = createPocCatalogExportStore({ now: () => instant })
  const common = { ownerId: 'subject-a', idempotencyKey: 'catalog-export-key-0001', requestHash: 'a'.repeat(64) }
  const csv = store.create({ ...common, format: 'CSV', rows: [row('=FORMULA')] })
  const csvFile = store.file('subject-a', csv.export_id)
  assert.equal(csv.state, 'COMPLETED')
  assert.equal(csv.row_count, 1)
  assert.equal(csvFile.bytes.subarray(0, 3).toString('hex'), 'efbbbf')
  assert.match(csvFile.bytes.toString('utf8'), /'=FORMULA/)
  assert.equal(store.create({ ...common, format: 'CSV', rows: [row('=FORMULA')] }).export_id, csv.export_id)
  assert.throws(() => store.file('subject-b', csv.export_id), /not found/)
  assert.throws(() => store.create({ ...common, requestHash: 'b'.repeat(64), format: 'CSV', rows: [] }), /already bound/)

  const xlsx = store.create({ ...common, idempotencyKey: 'catalog-export-key-0002', format: 'XLSX', rows: [row()] })
  const xlsxFile = store.file('subject-a', xlsx.export_id)
  assert.equal(xlsxFile.bytes.readUInt32LE(0), 0x04034b50)
  assert.match(xlsxFile.bytes.toString('utf8'), /xl\/worksheets\/sheet1\.xml/)
  assert.match(xlsxFile.bytes.toString('utf8'), /설명/)

  instant = new Date('2026-08-30T00:11:00.000Z')
  assert.throws(() => store.status('subject-a', csv.export_id), /not found/)
})
