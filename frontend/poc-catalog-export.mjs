/* global Buffer */
import { createHash, randomUUID } from 'node:crypto'

export const POC_CATALOG_EXPORT_MAXIMUM_ROWS = 10_000
const maximumArtifactBytes = 16 * 1024 * 1024
const maximumArtifacts = 4
const artifactTtlMs = 10 * 60 * 1000
const csvHeaders = Object.freeze([
  'asset_id', 'external_urn', 'platform', 'database_name', 'schema_name', 'name',
  'asset_type', 'classification', 'lifecycle', 'description', 'source_version', 'observed_at',
])

function exportError(code, message, statusCode = 400) {
  return Object.assign(new Error(message), { code, statusCode })
}

function safeCell(value) {
  const text = value === null || value === undefined ? '' : String(value)
  for (const character of text) {
    const code = character.codePointAt(0)
    if (code === 0 || (code < 0x20 && !['\t', '\r', '\n'].includes(character))) {
      throw exportError('EXPORT_CSV_INVALID_VALUE', 'Catalog export contains a prohibited control character.')
    }
  }
  if (['\t', '\r', '\n'].includes(text[0])) return `'${text}`
  const first = [...text].find((character) => !/\s/u.test(character)) || ''
  return '=+-@'.includes(first) ? `'${text}` : text
}

function rowValues(row) {
  return csvHeaders.map((key) => safeCell(row?.[key]))
}

function csvRecord(values) {
  const value = `${values.map((item) => {
    const text = String(item)
    return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text
  }).join(',')}\r\n`
  const bytes = Buffer.from(value, 'utf8')
  if (bytes.length > 1024 * 1024) {
    throw exportError('EXPORT_CSV_RECORD_LIMIT', 'A Catalog export row exceeds the safety limit.')
  }
  return bytes
}

function encodeCsv(rows) {
  return boundedArtifact(Buffer.concat([
    Buffer.from([0xef, 0xbb, 0xbf]),
    csvRecord(csvHeaders),
    ...rows.map((row) => csvRecord(rowValues(row))),
  ]))
}

function xmlText(value) {
  const text = String(value)
  if ([...text].length > 32_767) {
    throw exportError('EXPORT_CELL_LIMIT', 'A Catalog export cell exceeds the XLSX safety limit.')
  }
  return text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
}

function columnName(index) {
  let value = ''
  for (let current = index; current > 0;) {
    const next = Math.floor((current - 1) / 26)
    value = String.fromCharCode(65 + ((current - 1) % 26)) + value
    current = next
  }
  return value
}

function worksheetRow(number, values) {
  const cells = values.map((value, index) => (
    `<c r="${columnName(index + 1)}${number}" t="inlineStr"><is><t xml:space="preserve">${xmlText(value)}</t></is></c>`
  )).join('')
  return `<row r="${number}">${cells}</row>`
}

function crc32(buffer) {
  let crc = 0xffffffff
  for (const byte of buffer) {
    crc ^= byte
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1))
  }
  return (crc ^ 0xffffffff) >>> 0
}

function storedZip(entries) {
  const localParts = []
  const centralParts = []
  let offset = 0
  for (const [name, value] of entries) {
    const nameBytes = Buffer.from(name, 'utf8')
    const data = Buffer.isBuffer(value) ? value : Buffer.from(value, 'utf8')
    const checksum = crc32(data)
    const local = Buffer.alloc(30)
    local.writeUInt32LE(0x04034b50, 0)
    local.writeUInt16LE(20, 4)
    local.writeUInt16LE(0x0800, 6)
    local.writeUInt16LE(0, 8)
    local.writeUInt16LE(0, 10)
    local.writeUInt16LE(0x21, 12)
    local.writeUInt32LE(checksum, 14)
    local.writeUInt32LE(data.length, 18)
    local.writeUInt32LE(data.length, 22)
    local.writeUInt16LE(nameBytes.length, 26)
    local.writeUInt16LE(0, 28)
    localParts.push(local, nameBytes, data)

    const central = Buffer.alloc(46)
    central.writeUInt32LE(0x02014b50, 0)
    central.writeUInt16LE(20, 4)
    central.writeUInt16LE(20, 6)
    central.writeUInt16LE(0x0800, 8)
    central.writeUInt16LE(0, 10)
    central.writeUInt16LE(0, 12)
    central.writeUInt16LE(0x21, 14)
    central.writeUInt32LE(checksum, 16)
    central.writeUInt32LE(data.length, 20)
    central.writeUInt32LE(data.length, 24)
    central.writeUInt16LE(nameBytes.length, 28)
    central.writeUInt32LE(offset, 42)
    centralParts.push(central, nameBytes)
    offset += local.length + nameBytes.length + data.length
  }
  const centralDirectory = Buffer.concat(centralParts)
  const end = Buffer.alloc(22)
  end.writeUInt32LE(0x06054b50, 0)
  end.writeUInt16LE(entries.length, 8)
  end.writeUInt16LE(entries.length, 10)
  end.writeUInt32LE(centralDirectory.length, 12)
  end.writeUInt32LE(offset, 16)
  return boundedArtifact(Buffer.concat([...localParts, centralDirectory, end]))
}

function encodeXlsx(rows) {
  const worksheet = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>${[
    worksheetRow(1, csvHeaders),
    ...rows.map((row, index) => worksheetRow(index + 2, rowValues(row))),
  ].join('')}</sheetData></worksheet>`
  return storedZip([
    ['[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>'],
    ['_rels/.rels', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'],
    ['xl/workbook.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Catalog" sheetId="1" r:id="rId1"/></sheets></workbook>'],
    ['xl/_rels/workbook.xml.rels', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'],
    ['xl/styles.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts><fills count="1"><fill><patternFill patternType="none"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="1"><xf xfId="0"/></cellXfs></styleSheet>'],
    ['xl/worksheets/sheet1.xml', worksheet],
  ])
}

function boundedArtifact(value) {
  if (value.length > maximumArtifactBytes) {
    throw exportError('EXPORT_BYTE_LIMIT', 'The Catalog export exceeds the bounded artifact size.')
  }
  return value
}

function publicStatus(record) {
  return {
    export_id: record.exportId,
    job_id: record.jobId,
    state: 'COMPLETED',
    last_error_code: null,
    row_count: record.rowCount,
    size_bytes: record.bytes.length,
    content_sha256: record.contentSha256,
    display_name: record.displayName,
    created_at: record.createdAt,
    completed_at: record.createdAt,
    access_until: record.accessUntil,
  }
}

export function createPocCatalogExportStore({ now = () => new Date() } = {}) {
  const records = new Map()
  const receipts = new Map()
  const purge = () => {
    const instant = now().getTime()
    for (const [id, record] of records) {
      if (Date.parse(record.accessUntil) <= instant) records.delete(id)
    }
    for (const [key, id] of receipts) if (!records.has(id)) receipts.delete(key)
  }
  const owned = (ownerId, exportId) => {
    purge()
    const record = records.get(exportId)
    if (!record || record.ownerId !== ownerId) throw exportError('CATALOG_EXPORT_NOT_FOUND', 'Catalog export was not found.', 404)
    return record
  }
  return {
    create({ ownerId, idempotencyKey, requestHash, format, rows }) {
      purge()
      if (!ownerId || typeof idempotencyKey !== 'string' || idempotencyKey.length < 16
        || idempotencyKey.length > 200 || /[\u0000-\u001f\u007f]/.test(idempotencyKey)) {
        throw exportError('CATALOG_EXPORT_IDEMPOTENCY_KEY_INVALID', 'A bounded Idempotency-Key is required.', 428)
      }
      if (!Array.isArray(rows) || rows.length > POC_CATALOG_EXPORT_MAXIMUM_ROWS) {
        throw exportError('EXPORT_ROW_LIMIT', 'The Catalog export exceeds the bounded row count.', 413)
      }
      const receiptKey = `${ownerId}\u0000${idempotencyKey}`
      const priorId = receipts.get(receiptKey)
      if (priorId) {
        const prior = records.get(priorId)
        if (prior?.requestHash !== requestHash) throw exportError('CATALOG_EXPORT_IDEMPOTENCY_CONFLICT', 'The Idempotency-Key is already bound to another export.', 409)
        if (prior) return publicStatus(prior)
      }
      while (records.size >= maximumArtifacts) records.delete(records.keys().next().value)
      const bytes = format === 'XLSX' ? encodeXlsx(rows) : encodeCsv(rows)
      const createdAt = now().toISOString()
      const exportId = randomUUID()
      const record = {
        exportId,
        jobId: `poc-catalog-export:${exportId}`,
        ownerId,
        requestHash,
        format,
        bytes,
        rowCount: rows.length,
        contentSha256: createHash('sha256').update(bytes).digest('hex'),
        displayName: `datariver-catalog-${createdAt.slice(0, 10)}.${format.toLowerCase()}`,
        createdAt,
        accessUntil: new Date(Date.parse(createdAt) + artifactTtlMs).toISOString(),
      }
      records.set(exportId, record)
      receipts.set(receiptKey, exportId)
      return publicStatus(record)
    },
    status(ownerId, exportId) { return publicStatus(owned(ownerId, exportId)) },
    download(ownerId, exportId) {
      const record = owned(ownerId, exportId)
      return { url: `/poc-api/datahub/catalog/exports/${encodeURIComponent(exportId)}/file`, expires_seconds: Math.max(1, Math.floor((Date.parse(record.accessUntil) - now().getTime()) / 1000)) }
    },
    file(ownerId, exportId) { return owned(ownerId, exportId) },
  }
}
