/* global Buffer */
// Dependencies are supplied by bootstrap; this module never constructs a shared client.
export function createModulesRegistrationApplication(deps) {
function zipEntries(buffer) {
  let eocd = -1
  for (let offset = buffer.length - 22; offset >= Math.max(0, buffer.length - 65_557); offset -= 1) {
    if (buffer.readUInt32LE(offset) === 0x06054b50) { eocd = offset; break }
  }
  if (eocd < 0) throw Object.assign(new Error('The XLSX ZIP directory is missing.'), { statusCode: 400 })
  const count = buffer.readUInt16LE(eocd + 10)
  let offset = buffer.readUInt32LE(eocd + 16)
  const entries = new Map()
  for (let index = 0; index < count; index += 1) {
    if (buffer.readUInt32LE(offset) !== 0x02014b50) {
      throw Object.assign(new Error('The XLSX ZIP directory is invalid.'), { statusCode: 400 })
    }
    const method = buffer.readUInt16LE(offset + 10)
    const compressedSize = buffer.readUInt32LE(offset + 20)
    const uncompressedSize = buffer.readUInt32LE(offset + 24)
    const nameLength = buffer.readUInt16LE(offset + 28)
    const extraLength = buffer.readUInt16LE(offset + 30)
    const commentLength = buffer.readUInt16LE(offset + 32)
    const localOffset = buffer.readUInt32LE(offset + 42)
    const name = buffer.subarray(offset + 46, offset + 46 + nameLength).toString('utf8')
    if (buffer.readUInt32LE(localOffset) !== 0x04034b50) {
      throw Object.assign(new Error('The XLSX ZIP entry is invalid.'), { statusCode: 400 })
    }
    const localNameLength = buffer.readUInt16LE(localOffset + 26)
    const localExtraLength = buffer.readUInt16LE(localOffset + 28)
    const start = localOffset + 30 + localNameLength + localExtraLength
    const compressed = buffer.subarray(start, start + compressedSize)
    const content = method === 0 ? compressed : method === 8 ? deps.inflateRawSync(compressed) : undefined
    if (!content || content.length !== uncompressedSize || content.length > deps.maximumObjectBytes) {
      throw Object.assign(new Error('The XLSX entry compression or size is unsupported.'), { statusCode: 400 })
    }
    entries.set(name, content)
    offset += 46 + nameLength + extraLength + commentLength
  }
  return entries
}

function xmlText(value) {
  return value
    .replace(/<[^>]+>/g, '')
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'").replace(/&amp;/g, '&')
}

function xlsxRows(buffer) {
  const entries = zipEntries(buffer)
  const worksheet = entries.get('xl/worksheets/sheet1.xml')?.toString('utf8')
  if (!worksheet || worksheet.includes('<f')) {
    throw Object.assign(new Error('The XLSX first worksheet is missing or contains formulas.'), { statusCode: 400 })
  }
  const sharedXml = entries.get('xl/sharedStrings.xml')?.toString('utf8') || ''
  const shared = [...sharedXml.matchAll(/<si\b[^>]*>([\s\S]*?)<\/si>/g)].map((match) => (
    [...match[1].matchAll(/<t\b[^>]*>([\s\S]*?)<\/t>/g)].map((part) => xmlText(part[1])).join('')
  ))
  const rows = []
  for (const rowMatch of worksheet.matchAll(/<row\b[^>]*>([\s\S]*?)<\/row>/g)) {
    const cells = []
    for (const cell of rowMatch[1].matchAll(/<c\b([^>]*)>([\s\S]*?)<\/c>/g)) {
      const reference = cell[1].match(/\br="([A-Z]+)\d+"/)?.[1]
      if (!reference) continue
      let column = 0
      for (const character of reference) column = column * 26 + character.charCodeAt(0) - 64
      const type = cell[1].match(/\bt="([^"]+)"/)?.[1]
      const inline = cell[2].match(/<is\b[^>]*>([\s\S]*?)<\/is>/)?.[1]
      const raw = cell[2].match(/<v\b[^>]*>([\s\S]*?)<\/v>/)?.[1]
      const value = type === 's' ? shared[Number(raw)] : inline !== undefined ? xmlText(inline) : xmlText(raw ?? '')
      cells[column - 1] = value
    }
    rows.push(deps.catalogMetadataHeaders.map((_, index) => cells[index] ?? ''))
  }
  return rows
}

function csvRows(buffer) {
  const text = buffer.toString('utf8').replace(/^\uFEFF/, '')
  const rows = []
  let row = []
  let value = ''
  let quoted = false
  for (let index = 0; index <= text.length; index += 1) {
    const character = text[index] ?? '\n'
    if (quoted) {
      if (character === '"' && text[index + 1] === '"') { value += '"'; index += 1 }
      else if (character === '"') quoted = false
      else value += character
    } else if (character === '"') quoted = true
    else if (character === ',') { row.push(value); value = '' }
    else if (character === '\n') {
      row.push(value.replace(/\r$/, '')); value = ''
      if (row.some((item) => item !== '')) rows.push(row)
      row = []
    } else value += character
  }
  if (quoted) throw Object.assign(new Error('The CSV contains an unclosed quote.'), { statusCode: 400 })
  return rows
}

function bulkCandidateKind(recordKind) {
  return {
    TABLE_DESCRIPTION: 'TABLE_DESCRIPTION_UPDATE',
    COLUMN_DESCRIPTION: 'COLUMN_DESCRIPTION_UPDATE',
    DATASET_DOMAIN: 'DATASET_DOMAIN_UPDATE',
    DATASET_TERM: 'DATASET_TERM_ADD',
    DATASET_TAG: 'DATASET_TAG_ADD',
  }[recordKind]
}

async function compileBulkCandidates(bytes, profile) {
  const rows = profile === 'CATALOG_METADATA_ROWS_XLSX_V1' ? xlsxRows(bytes) : csvRows(bytes)
  if (rows.length < 2 || rows.length > 10_001 || JSON.stringify(rows[0]) !== JSON.stringify(deps.catalogMetadataHeaders)) {
    throw Object.assign(new Error('The bulk metadata file header or row count is invalid.'), { statusCode: 400 })
  }
  const inventoryItems = await deps.datahubInventory()
  const inventoryById = new Map(inventoryItems.map((item) => [item.id, item]))
  const candidates = []
  for (const [index, values] of rows.slice(1).entries()) {
    if (values.length !== deps.catalogMetadataHeaders.length) {
      throw Object.assign(new Error(`Bulk row ${index + 2} has an invalid column count.`), { statusCode: 400 })
    }
    const row = Object.fromEntries(deps.catalogMetadataHeaders.map((header, column) => [header, String(values[column] ?? '').trim()]))
    const candidateKind = bulkCandidateKind(row.record_kind)
    if (!candidateKind || !['SET', 'CLEAR', 'ADD'].includes(row.operation)) {
      throw Object.assign(new Error(`Bulk row ${index + 2} has an unsupported operation.`), { statusCode: 400 })
    }
    if (!/^urn:li:dataset:\(.+\)$/.test(row.asset_id)) {
      throw Object.assign(new Error(`Bulk row ${index + 2} requires a live DataHub dataset URN.`), { statusCode: 400 })
    }
    const detail = inventoryById.get(row.asset_id)
    if (!detail) {
      throw Object.assign(new Error(`Bulk row ${index + 2} asset is not found in the current inventory.`), { statusCode: 409 })
    }
    if (detail.dataset_kind !== 'TABLE') {
      throw Object.assign(new Error(`Bulk row ${index + 2} asset must be a TABLE.`), { statusCode: 409 })
    }
    const identity = [detail.platform, detail.database_name, detail.schema_name, detail.name]
    if (JSON.stringify(identity) !== JSON.stringify([row.platform, row.database_name, row.schema_name, row.table_name])) {
      throw Object.assign(new Error(`Bulk row ${index + 2} identity does not match DataHub.`), { statusCode: 409 })
    }
    if (row.record_kind === 'COLUMN_DESCRIPTION'
      && !(detail.schema_fields || []).some((field) => field.fieldPath === row.field_path)) {
      throw Object.assign(new Error(`Bulk row ${index + 2} column does not exist in DataHub.`), { statusCode: 409 })
    }
    if (['DATASET_DOMAIN', 'DATASET_TERM', 'DATASET_TAG'].includes(row.record_kind)) {
      const prefix = row.record_kind === 'DATASET_DOMAIN' ? 'urn:li:domain:'
        : row.record_kind === 'DATASET_TERM' ? 'urn:li:glossaryTerm:' : 'urn:li:tag:'
      const operationAllowed = row.record_kind === 'DATASET_DOMAIN'
        ? ['SET', 'CLEAR'].includes(row.operation)
        : row.operation === 'ADD'
      if (!operationAllowed
        || (row.operation !== 'CLEAR' && !row.controlled_ref.startsWith(prefix))) {
        throw Object.assign(new Error(`Bulk row ${index + 2} controlled reference is invalid.`), { statusCode: 400 })
      }
    }
    const createdAt = new Date().toISOString()
    candidates.push({
      id: deps.randomUUID(), ordinal: index + 1, evidence_version: 'CATALOG_METADATA_CANDIDATE_V3',
      record_kind: row.record_kind, candidate_kind: candidateKind, operation_count: 1,
      field_path_sample: row.field_path ? [row.field_path] : [],
      controlled_reference_count: row.controlled_ref ? 1 : 0, row_summary_truncated: false,
      submitted_identity: {
        platform: row.platform, database_name: row.database_name, schema_name: row.schema_name,
        table_name: row.table_name, identity_hash: deps.canonicalHash(identity),
      },
      candidate_hash: deps.canonicalHash(row), created_at: createdAt,
      current_target: {
        id: detail.id, asset_type: 'DATASET', name: detail.name, platform: detail.platform,
        database_name: detail.database_name, schema_name: detail.schema_name,
        dataset_kind: detail.dataset_kind, security_grade: deps.legacyTableTagGrade(detail),
        classification: detail.classification, lifecycle: 'ACTIVE', source_version: detail.source_version,
        observed_at: detail.observed_at,
      },
      row,
    })
  }
  return candidates
}

function canReadBulkPreparation(principal, entry) {
  return principal.role === 'admin' || entry?.creatorSubjectId === principal.subjectId
}

function bulkPreparationProjection(preparation, visibleCandidateCount) {
  const projection = { ...preparation }
  if (preparation.state === 'READY' && Number.isInteger(visibleCandidateCount)) {
    projection.rows_processed = visibleCandidateCount
    projection.total_rows = visibleCandidateCount
  }
  return projection
}

async function currentRegistrationCandidates(context, candidates) {
  const urns = [...new Set(candidates.map((candidate) => candidate.current_target.id))]
  if (urns.length === 0) return []
  const current = []
  try {
    for (let offset = 0; offset < urns.length; offset += 2_000) {
      current.push(...await context.currentDatahubTables(urns.slice(offset, offset + 2_000)))
    }
  } catch {
    throw deps.accessError(503, 'REGISTRATION_CURRENT_TABLES_UNAVAILABLE', 'Current DataHub Table confirmation is unavailable.')
  }
  const currentById = new Map(current.map((asset) => [asset.id, asset]))
  return candidates.flatMap((candidate) => {
    const target = currentById.get(candidate.current_target.id)
    return target ? [{
      ...candidate,
      current_target: { ...candidate.current_target, ...target },
    }] : []
  })
}

async function visibleRegistrationCandidates(entry, context, candidates = entry.candidates) {
  const currentCandidates = await currentRegistrationCandidates(context, candidates)
  if (context.principal.role === 'admin') {
    return currentCandidates.filter((candidate) => (
      deps.canReadRegistrationAsset(context.principal, candidate.current_target, new Set())
    ))
  }
  const mappingSnapshot = await context.stateStore.read(deps.POC_TABLE_SYSTEM_MAPPING_SCOPE)
  const activeSystemIds = new Set((context.accessDocument.systems ?? [])
    .filter((system) => system.active)
    .map((system) => system.system_id))
  return currentCandidates.filter((candidate) => {
    const mapped = deps.activeSystemIdsForTable(mappingSnapshot.value, candidate.current_target.id, activeSystemIds)
    return deps.canReadRegistrationAsset(context.principal, candidate.current_target, new Set(mapped))
  })
}

async function executeBulkPreparation() {
  const entry = [...deps.bulkPreparations.values()].find((item) => item.preparation.state === 'QUEUED')
  if (!entry) return { processed: false }
  const preparation = entry.preparation
  Object.assign(preparation, { state: 'PREPARING', attempts: preparation.attempts + 1, updated_at: new Date().toISOString(), version: preparation.version + 1 })
  try {
    const upstream = await deps.minioObject('GET', deps.minio.buckets.filefolder, entry.objectKey)
    const bytes = Buffer.from(await upstream.arrayBuffer())
    if (deps.sha256(bytes) !== preparation.source_sha256) {
      throw Object.assign(new Error('The filefolder object hash does not match the accepted upload.'), { statusCode: 409 })
    }
    entry.candidates = await compileBulkCandidates(bytes, preparation.content_profile)
    const rootHash = deps.canonicalHash(entry.candidates.map((item) => item.candidate_hash))
    const now = new Date().toISOString()
    entry.receipt = {
      id: deps.randomUUID(), preparation_id: preparation.id, manifest_version: 1,
      source_sha256: preparation.source_sha256, content_profile: preparation.content_profile,
      parser_version: 'poc-live-catalog-metadata-parser-v1', scanner_version: 'poc-integrity-v1',
      schema_version: 'catalog-metadata-rows-schema-v1', configuration_hash: deps.canonicalHash(deps.catalogMetadataHeaders),
      item_count: entry.candidates.length, candidate_count: entry.candidates.length,
      candidate_root_hash: rootHash, receipt_hash: deps.canonicalHash([preparation.id, rootHash]),
      observed_at: now, created_at: now,
    }
    Object.assign(preparation, {
      state: 'READY', rows_processed: entry.candidates.length, total_rows: entry.candidates.length,
      updated_at: now, version: preparation.version + 1,
    })
    return { processed: true, state: 'READY', item_count: entry.candidates.length, preparation_id: preparation.id }
  } catch (error) {
    Object.assign(preparation, {
      state: 'FAILED', last_error_code: error?.detailCode || 'BULK_PREPARATION_FAILED',
      updated_at: new Date().toISOString(), version: preparation.version + 1,
    })
    throw error
  }
}

async function bulkCandidatePreview(entry, candidate) {
  const detail = await deps.datahubAsset(candidate.current_target.id)
  const row = candidate.row
  const field = row.field_path ? detail.schema_fields.find((item) => item.fieldPath === row.field_path) : undefined
  const currentDescription = row.record_kind === 'TABLE_DESCRIPTION' ? detail.description ?? null
    : row.record_kind === 'COLUMN_DESCRIPTION' ? field?.description ?? null : null
  const proposedDescription = ['TABLE_DESCRIPTION', 'COLUMN_DESCRIPTION'].includes(row.record_kind)
    ? row.operation === 'CLEAR' ? null : row.value_text : null
  const currentReferences = row.record_kind === 'DATASET_DOMAIN' ? (detail.domain ? [detail.domain] : [])
    : row.record_kind === 'DATASET_TERM' ? detail.glossary_terms.map((item) => item.urn).filter(Boolean)
      : row.record_kind === 'DATASET_TAG' ? detail.tags : []
  const proposedReferences = row.controlled_ref
    ? row.operation === 'ADD' ? [...new Set([...currentReferences, row.controlled_ref])] : [row.controlled_ref]
    : row.operation === 'CLEAR' ? [] : currentReferences
  const beforeHash = deps.canonicalHash({ currentDescription, currentReferences })
  const afterHash = deps.canonicalHash({ proposedDescription, proposedReferences })
  return {
    candidate_id: candidate.id, target_asset_id: detail.id,
    platform: detail.platform, database_name: detail.database_name, schema_name: detail.schema_name,
    table_name: detail.name, record_kind: candidate.record_kind, candidate_kind: candidate.candidate_kind,
    operation_count: 1,
    description_change_count: ['TABLE_DESCRIPTION', 'COLUMN_DESCRIPTION'].includes(row.record_kind) ? 1 : 0,
    description_change_sample: ['TABLE_DESCRIPTION', 'COLUMN_DESCRIPTION'].includes(row.record_kind) ? [{
      field_path: row.field_path || null, current_description: currentDescription,
      proposed_description: proposedDescription,
    }] : [],
    description_changes_truncated: false, current_reference_count: currentReferences.length,
    proposed_reference_count: proposedReferences.length, before_hash: beforeHash, after_hash: afterHash,
    source_version: detail.source_version, observed_at: new Date().toISOString(), preview_etag: `"${beforeHash}"`,
  }
}

return { zipEntries, xmlText, xlsxRows, csvRows, bulkCandidateKind, compileBulkCandidates, canReadBulkPreparation, bulkPreparationProjection, currentRegistrationCandidates, visibleRegistrationCandidates, executeBulkPreparation, bulkCandidatePreview }
}
