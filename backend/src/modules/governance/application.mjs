/* global Buffer, structuredClone */
// Dependencies are supplied by bootstrap; this module never constructs a shared client.
export function createModulesGovernanceApplication(deps) {
function crNextId() { return deps.randomUUID() }

function exactCrBodyKeys(body, allowed, required = allowed) {
  const keys = Object.keys(body)
  const unknown = keys.find((key) => !allowed.includes(key))
  const missing = required.find((key) => !Object.hasOwn(body, key))
  if (unknown || missing) {
    throw deps.accessError(400, 'CR_INPUT_INVALID', unknown
      ? `${unknown} is not supported.`
      : `${missing} is required.`)
  }
}

function crBoundedText(value, field, maximum) {
  if (typeof value !== 'string' || !value.trim() || value.length > maximum || deps.hasAccessControlCharacter(value)) {
    throw deps.accessError(400, 'CR_INPUT_INVALID', `${field} is required and must contain at most ${maximum} characters.`)
  }
  return value.trim()
}

function crChangeDocument(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw deps.accessError(400, 'CR_INPUT_INVALID', 'change_document must be an object.')
  }
  if (Buffer.byteLength(JSON.stringify(value)) > 65_536) {
    throw deps.accessError(400, 'CR_INPUT_INVALID', 'change_document is too large.')
  }
  return structuredClone(value)
}

function crColumnIdentity(value) {
  return value.normalize('NFKC').toLocaleLowerCase()
}

function crValidateColumnProposals(changeDocument, currentTable) {
  const requested = changeDocument?.requested
  if (!requested || typeof requested !== 'object' || Array.isArray(requested)
    || requested.columns === undefined) return
  if (!Array.isArray(requested.columns) || requested.columns.length > 500) {
    throw deps.accessError(400, 'CR_COLUMN_INPUT_INVALID', 'Column proposals must be a bounded array.')
  }
  const currentFields = new Set((Array.isArray(currentTable?.schema_field_paths)
    ? currentTable.schema_field_paths
    : []).filter((field) => typeof field === 'string').map(crColumnIdentity))
  const observed = new Set()
  for (const [index, rawColumn] of requested.columns.entries()) {
    if (!rawColumn || typeof rawColumn !== 'object' || Array.isArray(rawColumn)) {
      throw deps.accessError(400, 'CR_COLUMN_INPUT_INVALID', `Column proposal ${index + 1} must be an object.`)
    }
    const fieldPath = typeof rawColumn.field_path === 'string' ? rawColumn.field_path.trim() : ''
    if (!/^[\p{L}_][\p{L}\p{N}_$]{0,254}$/u.test(fieldPath)) {
      throw deps.accessError(400, 'CR_COLUMN_NAME_INVALID', `Column proposal ${index + 1} has an invalid name.`)
    }
    const identity = crColumnIdentity(fieldPath)
    if (observed.has(identity)) {
      throw deps.accessError(409, 'CR_COLUMN_DUPLICATE', 'Column proposal names must be unique.')
    }
    observed.add(identity)
    const proposalKind = rawColumn.proposal_kind ?? 'EXISTING'
    if (!['EXISTING', 'NEW'].includes(proposalKind)) {
      throw deps.accessError(400, 'CR_COLUMN_INPUT_INVALID', `Column proposal ${index + 1} has an invalid kind.`)
    }
    if (proposalKind === 'NEW' && currentFields.has(identity)) {
      throw deps.accessError(409, 'CR_COLUMN_EXISTS', 'A proposed new column conflicts with the current DataHub schema.')
    }
    if (proposalKind === 'EXISTING' && !currentFields.has(identity)) {
      throw deps.accessError(409, 'CR_COLUMN_NOT_FOUND', 'A selected existing column is no longer in the current DataHub schema.')
    }
    const columnRequested = rawColumn.requested
    if (!columnRequested || typeof columnRequested !== 'object' || Array.isArray(columnRequested)) {
      throw deps.accessError(400, 'CR_COLUMN_INPUT_INVALID', `Column proposal ${index + 1} has no requested snapshot.`)
    }
    const dataType = typeof columnRequested.data_type === 'string'
      ? columnRequested.data_type.trim()
      : ''
    if ((proposalKind === 'NEW' && !dataType)
      || dataType.length > 200
      || (dataType && (!/^[\p{L}][\p{L}\p{N}_ (),.[\]]*$/u.test(dataType)
        || deps.hasAccessControlCharacter(dataType)))) {
      throw deps.accessError(400, 'CR_COLUMN_TYPE_INVALID', `Column proposal ${index + 1} has an invalid data type.`)
    }
    if (columnRequested.nullable !== undefined && typeof columnRequested.nullable !== 'boolean') {
      throw deps.accessError(400, 'CR_COLUMN_INPUT_INVALID', `Column proposal ${index + 1} has invalid nullability.`)
    }
    if (columnRequested.ordinal !== undefined && columnRequested.ordinal !== null
      && (!Number.isSafeInteger(columnRequested.ordinal)
        || columnRequested.ordinal < 1 || columnRequested.ordinal > 100_000)) {
      throw deps.accessError(400, 'CR_COLUMN_INPUT_INVALID', `Column proposal ${index + 1} has an invalid placement.`)
    }
  }
}

function crOptionalText(value, field, maximum) {
  if (value === undefined || value === null || value === '') return ''
  if (typeof value !== 'string' || value.length > maximum || deps.hasAccessControlCharacter(value)) {
    throw deps.accessError(400, 'CR_INPUT_INVALID', `${field} must contain at most ${maximum} characters.`)
  }
  return value.trim()
}

function crOptionalDate(value, field) {
  if (value === undefined || value === null || value === '') return null
  const match = typeof value === 'string' ? value.match(/^(\d{4})-(\d{2})-(\d{2})$/) : null
  const parsed = match ? new Date(`${value}T00:00:00.000Z`) : null
  if (!match || !parsed || Number.isNaN(parsed.getTime())
    || parsed.getUTCFullYear() !== Number(match[1])
    || parsed.getUTCMonth() + 1 !== Number(match[2])
    || parsed.getUTCDate() !== Number(match[3])) {
    throw deps.accessError(400, 'CR_INPUT_INVALID', `${field} must be an ISO calendar date.`)
  }
  return value
}

async function bulkCandidateChangeRequestApi(request, response, url, context) {
  deps.rejectProtectedAccessClaims(request, url)
  if (request.method !== 'POST') return deps.problem(response, 405, 'METHOD_NOT_ALLOWED', 'CR create supports POST only.')

  const match = url.pathname.match(/^\/poc-api\/bulk\/uploads\/([a-zA-Z0-9_-]+)\/preparations\/([^/]+)\/metadata-candidates\/([^/]+)\/change-request$/)
  const uploadId = match[1]
  const prepId = match[2]
  const candidateId = match[3]

  const entry = deps.bulkPreparations.get(uploadId)
  if (!entry || entry.preparation.id !== prepId || entry.preparation.state !== 'READY' || !entry.receipt || !deps.canReadBulkPreparation(context.principal, entry)) {
    return deps.problem(response, 404, 'BULK_CANDIDATE_NOT_READY', 'Bulk candidate not ready or not found.')
  }
  const candidate = entry.candidates.find((item) => item.id === candidateId)
  if (!candidate) return deps.problem(response, 404, 'BULK_CANDIDATE_NOT_FOUND', 'Candidate not found.')

  const visibleCandidates = await deps.visibleRegistrationCandidates(entry, context, [candidate])
  if (visibleCandidates.length !== 1) return deps.problem(response, 404, 'BULK_CANDIDATE_NOT_FOUND', 'Candidate not found.')

  const preview = await deps.bulkCandidatePreview(entry, candidate)
  const expectedEtag = request.headers['if-match']
  if (!expectedEtag) return deps.problem(response, 428, 'PRECONDITION_REQUIRED', 'If-Match header is required.')
  if (typeof expectedEtag !== 'string' || !/^"[0-9a-f]{64}"$/.test(expectedEtag)) {
    return deps.problem(response, 400, 'PRECONDITION_INVALID', 'If-Match must be one quoted SHA-256 preview ETag.')
  }
  if (expectedEtag !== preview.preview_etag) {
    return deps.problem(response, 412, 'PRECONDITION_FAILED', 'The bulk candidate preview is stale.')
  }

  const idempotencyKeyHeader = request.headers['idempotency-key']
  if (typeof idempotencyKeyHeader !== 'string' || !idempotencyKeyHeader.trim() || idempotencyKeyHeader.length > 200 || deps.hasAccessControlCharacter(idempotencyKeyHeader)) {
    return deps.problem(response, 428, 'PRECONDITION_REQUIRED', 'Idempotency-Key is required and bounded.')
  }
  const idempotencyKey = idempotencyKeyHeader.trim()

  const body = await deps.bodyJson(request)
  exactCrBodyKeys(body, ['title', 'reason'])
  const title = crBoundedText(body.title, 'title', 500)
  const reason = crBoundedText(body.reason, 'reason', 2_000)

  const tableUrn = preview.target_asset_id
  const tableGrade = visibleCandidates[0].current_target.security_grade
  const aspectName = preview.record_kind === 'COLUMN_DESCRIPTION' ? 'schemaMetadata'
    : preview.record_kind === 'TABLE_DESCRIPTION' ? 'datasetProperties'
      : preview.record_kind === 'DATASET_DOMAIN' ? 'domains'
        : preview.record_kind === 'DATASET_TERM' ? 'glossaryTerms' : 'globalTags'

  const mappingSnapshot = await context.stateStore.read(deps.POC_TABLE_SYSTEM_MAPPING_SCOPE)
  const activeSystemIds = new Set((context.accessDocument.systems ?? []).filter((s) => s?.active).map((s) => s.system_id))
  const mappedSystemIds = new Set(deps.activeSystemIdsForTable(mappingSnapshot.value, tableUrn, activeSystemIds))

  if (mappedSystemIds.size !== 1) {
    return deps.problem(response, 403, 'MAPPING_INTEGRITY_VIOLATION', 'A single active Table-to-System mapping is required.')
  }
  const resolvedSystemId = [...mappedSystemIds][0]

  const requestHash = deps.canonicalHash({
    actor: context.principal.subjectId,
    uploadId,
    preparationId: prepId,
    receiptHash: entry.receipt.receipt_hash,
    candidateId,
    candidateHash: candidate.candidate_hash,
    previewEtag: expectedEtag,
    aspectName,
    beforeHash: preview.before_hash,
    afterHash: preview.after_hash,
    sourceVersion: preview.source_version,
    tableGrade,
    resolvedSystemId,
    title,
    reason,
  })
  const idempotencyHash = deps.canonicalHash(idempotencyKey)

  let attempts = 0
  while (attempts++ < 10) {
    const snapshot = await context.stateStore.read('core')
    const core = snapshot.value ?? {}
    const bindings = Array.isArray(core.bulkRegistrationCandidateBindings) ? core.bulkRegistrationCandidateBindings : []

    const existingByKey = bindings.find(b => b.idempotency_key_hash === idempotencyHash)
    if (existingByKey) {
      if (existingByKey.request_hash !== requestHash || existingByKey.candidate_id !== candidateId) {
        return deps.problem(response, 409, 'CONFLICT', 'Idempotency key collision with different request.')
      }
      const existingCr = core.changeRecords?.find(cr => cr.id === existingByKey.change_request_id)
      if (existingCr) {
        return deps.json(response, 200, { id: existingCr.id, number: existingCr.number, request_type: existingCr.request_type, state: existingCr.state }, { ETag: `"${snapshot.version}"` })
      }
      return deps.problem(response, 409, 'CONFLICT', 'Idempotency collision with missing CR.')
    }

    const existingByCandidate = bindings.find((binding) => (
      binding.upload_id === uploadId
      && binding.preparation_id === prepId
      && binding.candidate_id === candidateId
      && binding.idempotency_key_hash !== idempotencyHash
    ))
    if (existingByCandidate) {
      return deps.problem(response, 409, 'CONFLICT', 'Candidate already bound to a different change request.')
    }

    const roundId = deps.randomUUID()
    const occurredAt = new Date().toISOString()
    const crId = deps.randomUUID()

    const target = { kind: 'EXISTING', asset_id: tableUrn }
    const sample = Array.isArray(preview.description_change_sample) ? preview.description_change_sample[0] : undefined
    if (preview.record_kind === 'TABLE_DESCRIPTION') target.description = sample?.proposed_description ?? ''
    if (preview.record_kind === 'COLUMN_DESCRIPTION') target.columns = [{
      field_path: sample?.field_path,
      description: sample?.proposed_description ?? '',
      requested_change: reason,
    }]

    const changeDocument = { targets: [target] }

    const newCr = {
      id: crId,
      number: `CR-${crId.slice(0, 8).toUpperCase()}`,
      request_type: 'BULK_CATALOG_METADATA',
      title,
      description: reason,
      state: 'REGISTERED',
      requester_id: context.principal.subjectId,
      requester_department_id: null,
      current_round_id: roundId,
      current_round_number: 1,
      revision_allowed: false,
      created_at: occurredAt,
      requested_due_date: null,
      priority: 'NORMAL',
      urgency: 'NORMAL',
      classification: tableGrade,
      version: 1,
      items: [{
        id: deps.randomUUID(),
        target_type: 'DATASET',
        target_ref: tableUrn,
        aspect_name: aspectName,
        operation: 'UPSERT',
        after_document: changeDocument,
        target_asset_id: tableUrn,
        target_asset_type: 'DATASET',
        target_system_id: resolvedSystemId,
        target_domain_id: null,
        target_owner_department_id: null,
        target_classification: tableGrade,
        target_lifecycle: 'ACTIVE',
        target_source_version: preview.source_version || 'poc-bulk',
        target_observed_at: occurredAt,
        target_binding_hash: deps.canonicalHash({
          table_urn: tableUrn,
          responsible_system_id: resolvedSystemId,
          security_grade: tableGrade,
          aspect_name: aspectName,
          before_hash: preview.before_hash,
          after_hash: preview.after_hash,
          receipt_hash: entry.receipt.receipt_hash,
          candidate_hash: candidate.candidate_hash,
        }),
        routing_system_id: resolvedSystemId,
      }],
      approvals: [],
      transitions: [],
      approval_lanes: [],
      test_runs: [],
      rounds: [{
        id: roundId, round_number: 1,
        submitted_by: context.principal.subjectId,
        submitted_at: occurredAt,
        closed_at: null,
        evidence_hash: deps.canonicalHash({
          table_urn: tableUrn,
          responsible_system_id: resolvedSystemId,
          title,
          description: reason,
          change_document: changeDocument,
          aspect_name: aspectName,
          before_hash: preview.before_hash,
          after_hash: preview.after_hash,
          receipt_hash: entry.receipt.receipt_hash,
          candidate_hash: candidate.candidate_hash,
        }),
        revision_kind: 'INITIAL',
        title,
        request_date: null,
        request_department: '',
        request_reason: reason.slice(0, 2_000),
        request_content: reason,
        requested_due_date: null,
        priority: 'NORMAL',
        urgency: 'NORMAL',
        classification: tableGrade,
        selected_system_id: resolvedSystemId,
      }],
    }

    const newBinding = {
      idempotency_key_hash: idempotencyHash,
      request_hash: requestHash,
      upload_id: uploadId,
      preparation_id: prepId,
      receipt_hash: entry.receipt.receipt_hash,
      candidate_id: candidateId,
      candidate_hash: candidate.candidate_hash,
      change_request_id: crId,
      created_at: occurredAt,
    }

    const changeRecords = Array.isArray(core.changeRecords) ? [...core.changeRecords, newCr] : [newCr]
    const updatedBindings = [...bindings, newBinding]
    const updatedCore = { ...core, changeRecords, bulkRegistrationCandidateBindings: updatedBindings, sequence: (typeof core.sequence === 'number' ? core.sequence : 0) + 1 }

    try {
      const newVersion = await context.stateStore.writeIfVersion('core', updatedCore, snapshot.version)
      return deps.json(response, 201, { id: newCr.id, number: newCr.number, request_type: newCr.request_type, state: newCr.state }, { ETag: `"${newVersion}"` })
    } catch (err) {
      if (err.code === 'STATE_VERSION_STALE') continue
      throw err
    }
  }
  return deps.problem(response, 409, 'STATE_VERSION_STALE', 'The core state version is stale.')
}

async function crCreateApi(request, response, url, context) {
  deps.rejectProtectedAccessClaims(request, url)
  if (request.method !== 'POST') return deps.problem(response, 405, 'METHOD_NOT_ALLOWED', 'CR create supports POST only.')
  const body = await deps.bodyJson(request)
  deps.rejectProtectedAccessBodyClaims(body, { allowPriority: true })
  exactCrBodyKeys(body, [
    'table_urn', 'responsible_system_id', 'title', 'request_date', 'request_department',
    'request_reason', 'request_content', 'requested_due_date', 'priority', 'urgency',
    'security_level', 'change_document',
  ])
  const tableUrn = crBoundedText(body.table_urn, 'table_urn', 4_096)
  const requestedSystemId = crBoundedText(body.responsible_system_id, 'responsible_system_id', 200)
  const title = crBoundedText(body.title, 'title', 500)
  const requestDate = crOptionalDate(body.request_date, 'request_date')
  const requestDepartment = crOptionalText(body.request_department, 'request_department', 500)
  const requestReason = crBoundedText(body.request_reason, 'request_reason', 2_000)
  const requestContent = crOptionalText(body.request_content, 'request_content', 10_000)
  const requestedDueDate = crOptionalDate(body.requested_due_date, 'requested_due_date')
  const priority = ['LOW', 'NORMAL', 'HIGH', 'CRITICAL'].includes(body.priority) ? body.priority : null
  const urgency = ['NORMAL', 'URGENT', 'EMERGENCY'].includes(body.urgency) ? body.urgency : null
  const requestedClassification = ['PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED'].includes(body.security_level)
    ? body.security_level
    : null
  if (!priority || !urgency || !requestedClassification) {
    throw deps.accessError(400, 'CR_INPUT_INVALID', 'priority, urgency, and security_level must use supported values.')
  }
  const changeDocument = crChangeDocument(body.change_document)

  // Table access: grant + grade + feature policy cell.
  const grantedSet = new Set((await context.stateStore.listUserTableGrants(context.principal.subjectId)).map((g) => g.tableUrn))
  const mappingSnapshot = await context.stateStore.read(deps.POC_TABLE_SYSTEM_MAPPING_SCOPE)
  const mappingDocument = deps.normalizeTableSystemMappingDocument(mappingSnapshot.value)
  let tables
  try {
    tables = await context.currentDatahubTables([tableUrn], { includeClassificationErrors: true })
  } catch {
    return deps.problem(response, 503, 'PROVIDER_UNAVAILABLE', 'DataHub is unavailable.')
  }
  const asset = tables.find((item) => item?.id === tableUrn)
  if (!asset || asset.dataset_kind !== 'TABLE') {
    return deps.problem(response, 400, 'CR_TABLE_INVALID', 'Target must be an active current TABLE.')
  }
  if (asset.classification_status === 'MULTIPLE') {
    return deps.problem(response, 409, 'CR_CLASSIFICATION_MULTIPLE', 'The current DataHub Table has multiple classification tags. Submission is blocked.')
  }
  if (asset.classification_status === 'INVALID'
    || (asset.classification !== undefined && asset.classification !== null
      && asset.classification !== '' && !deps.supportedDatahubClassifications.has(asset.classification))) {
    return deps.problem(response, 409, 'CR_CLASSIFICATION_INVALID', 'The current DataHub Table classification is invalid. Submission is blocked.')
  }
  if (asset.classification_status === 'MISSING' || asset.classification === undefined
    || asset.classification === null || asset.classification === '') {
    return deps.problem(response, 409, 'CR_CLASSIFICATION_MISSING', 'The current DataHub Table has no classification tag. Submission is blocked.')
  }
  const tableClassification = asset.classification
  // Retained only in the immutable CR business snapshot/compatibility hash.
  // It is not consulted by assertCrTableAccess or any Table read boundary.
  const tableGrade = typeof asset.security_grade === 'string'
    ? asset.security_grade : deps.legacyTableTagGrade(asset)
  if (requestedClassification !== tableClassification) {
    return deps.problem(response, 409, 'CR_CLASSIFICATION_MISMATCH', 'The requested classification must match the current DataHub Table classification.')
  }
  crValidateColumnProposals(changeDocument, asset)
  deps.assertCrTableAccess({ principal: context.principal, tableUrn, grantedTableUrns: grantedSet })

  // Exact Table-System resolution.
  const activeSystemIds = new Set((context.accessDocument.systems ?? []).filter((s) => s?.active).map((s) => s.system_id))
  const resolvedSystemId = deps.resolveNewCrResponsibleSystem({ tableUrn, requestedSystemId, mappingDocument, activeSystemIds, activeSystemIdsForTable: deps.activeSystemIdsForTable })

  // Build and CAS-write the new CR into core.
  const snapshot = await context.stateStore.read('core')
  const expectedVersion = deps.stateIfMatch(request)
  if (snapshot.version !== expectedVersion) return deps.problem(response, 409, 'STATE_VERSION_STALE', 'The core state version is stale.')
  const core = snapshot.value ?? {}
  const roundId = deps.randomUUID()
  const occurredAt = new Date().toISOString()
  const crId = deps.randomUUID()
  const newCr = {
    id: crId,
    number: `CR-${crId.slice(0, 8).toUpperCase()}`,
    request_type: 'CHANGE_INTAKE',
    title,
    description: requestContent,
    state: 'REGISTERED',
    requester_id: context.principal.subjectId,
    requester_department_id: null,
    current_round_id: roundId,
    current_round_number: 1,
    revision_allowed: false,
    created_at: occurredAt,
    requested_due_date: requestedDueDate,
    priority,
    urgency,
    classification: tableClassification,
    version: 1,
    items: [{
      id: deps.randomUUID(),
      target_type: 'DATASET',
      target_ref: tableUrn,
      aspect_name: 'datasetProperties',
      operation: 'UPSERT',
      after_document: changeDocument,
      target_asset_id: tableUrn,
      target_asset_type: 'DATASET',
      target_system_id: resolvedSystemId,
      target_domain_id: null,
      target_owner_department_id: null,
      target_classification: tableClassification,
      target_lifecycle: 'ACTIVE',
      target_source_version: 'poc-manual',
      target_observed_at: occurredAt,
      target_binding_hash: deps.canonicalHash({ table_urn: tableUrn, responsible_system_id: resolvedSystemId, security_grade: tableGrade }),
      routing_system_id: resolvedSystemId,
    }],
    approvals: [],
    transitions: [],
    approval_lanes: [],
    test_runs: [],
    rounds: [{
      id: roundId, round_number: 1,
      submitted_by: context.principal.subjectId,
      submitted_at: occurredAt,
      closed_at: null,
      evidence_hash: deps.canonicalHash({
        table_urn: tableUrn, responsible_system_id: resolvedSystemId, title,
        request_date: requestDate, request_department: requestDepartment,
        request_reason: requestReason, request_content: requestContent,
        requested_due_date: requestedDueDate, priority, urgency,
        classification: tableClassification, change_document: changeDocument,
      }),
      revision_kind: 'INITIAL',
      title,
      request_date: requestDate,
      request_department: requestDepartment,
      request_reason: requestReason,
      request_content: requestContent,
      requested_due_date: requestedDueDate,
      priority,
      urgency,
      classification: tableClassification,
      selected_system_id: resolvedSystemId,
    }],
  }
  const changeRecords = Array.isArray(core.changeRecords) ? [...core.changeRecords, newCr] : [newCr]
  const updatedCore = { ...core, changeRecords, sequence: (typeof core.sequence === 'number' ? core.sequence : 0) + 1 }
  const newVersion = await context.stateStore.writeIfVersion('core', updatedCore, expectedVersion)
  return deps.json(response, 201, { version: newVersion, change_request: newCr }, { ETag: `"${newVersion}"` })
}

async function applyReportApi(request, response, url, context) {
  if (request.method !== 'GET') {
    return deps.problem(response, 405, 'METHOD_NOT_ALLOWED', 'The apply-report route supports only GET.')
  }
  const match = url.pathname.match(/^\/poc-api\/change-requests\/([^/]+)\/apply-report$/)
  if (!match) return deps.problem(response, 400, 'CR_ID_INVALID', 'Change request id is invalid.')
  const crId = decodeURIComponent(match[1])
  if (!crId || crId.length > 200) return deps.problem(response, 400, 'CR_ID_INVALID', 'Change request id is invalid.')
  deps.rejectProtectedAccessClaims(request, url)

  const snapshot = await context.stateStore.read('core')
  const core = snapshot.value ?? {}
  const changeRecords = Array.isArray(core.changeRecords) ? core.changeRecords : []
  const cr = changeRecords.find((r) => r?.id === crId)

  if (!cr) return deps.problem(response, 404, 'CR_NOT_FOUND', 'The change request was not found.')

  return deps.json(response, 200, {
    change_request_id: cr.id,
    job_id: null,
    state: 'NOT_STARTED',
    attempt_count: 0,
    last_error_code: null,
    expected_hash: null,
    observed_hash: null,
    reconciled: false,
    created_at: null,
    updated_at: null,
    items: [],
    attempts: [],
  }, { 'Cache-Control': 'private, no-store' })
}

async function crCommandApi(request, response, url, context) {
  const isCommandPath = /^\/poc-api\/change-requests\/[^/]+\/commands$/.test(url.pathname)
  const crId = decodeURIComponent(url.pathname.replace(/^\/poc-api\/change-requests\//, '').replace(/\/commands$/, ''))
  if (!crId || crId.length > 200) return deps.problem(response, 400, 'CR_ID_INVALID', 'Change request id is invalid.')
  deps.rejectProtectedAccessClaims(request, url)

  const snapshot = await context.stateStore.read('core')
  const core = snapshot.value ?? {}
  const changeRecords = Array.isArray(core.changeRecords) ? core.changeRecords : []
  const cr = changeRecords.find((r) => r?.id === crId)

  // GET remains capability-protected. Responsible System governs workflow actions, not read access.
  if (request.method === 'GET') {
    if (!cr) return deps.problem(response, 404, 'CR_NOT_FOUND', 'The change request was not found.')
    return deps.json(response, 200, { change_request: cr })
  }

  if (!isCommandPath) return deps.problem(response, 405, 'METHOD_NOT_ALLOWED', 'Use POST /commands for mutations.')
  if (request.method !== 'POST') return deps.problem(response, 405, 'METHOD_NOT_ALLOWED', 'CR commands require POST.')
  if (!cr) return deps.problem(response, 404, 'CR_NOT_FOUND', 'The change request was not found.')
  const body = await deps.bodyJson(request)
  deps.rejectProtectedAccessBodyClaims(body)

  if (!Array.isArray(cr.approval_lanes)) {
    return deps.problem(response, 409, 'CR_LEGACY_COMPATIBILITY_ONLY', 'This historical change request remains on the legacy read path.')
  }

  const command = typeof body.command === 'string' ? body.command : ''
  const reason = typeof body.reason === 'string' ? body.reason : ''
  const occurredAt = new Date().toISOString()
  const responsibleSystemId = deps.crResponsibleSystemId(cr)
  if (!responsibleSystemId) return deps.problem(response, 409, 'CR_SYSTEM_UNRESOLVED', 'This change request has no resolved responsible System.')

  const expectedVersion = deps.stateIfMatch(request)
  if (snapshot.version !== expectedVersion) return deps.problem(response, 409, 'STATE_VERSION_STALE', 'The core state version is stale.')
  const updatedCore = structuredClone(core)
  const updatedRecords = updatedCore.changeRecords
  const crIndex = updatedRecords.findIndex((r) => r?.id === crId)
  const crClone = updatedRecords[crIndex]

  let result
  if (command === 'transition') {
    exactCrBodyKeys(body, ['command', 'target_state', 'reason'])
    // Requires developer/data_steward assigned to responsible System.
    deps.assertCrWorkflowAction({ principal: context.principal, responsibleSystemId, crId })
    const targetState = typeof body.target_state === 'string' ? body.target_state : ''
    result = deps.applyTransition({ cr: crClone, targetState, reason, principal: context.principal, occurredAt, nextId: crNextId })
  } else if (command === 'workflow-approval') {
    exactCrBodyKeys(body, ['command', 'stage', 'decision', 'reason'])
    // Requires developer/data_steward assigned to responsible System.
    deps.assertCrWorkflowAction({ principal: context.principal, responsibleSystemId, crId })
    const stage = typeof body.stage === 'string' ? body.stage : ''
    if (!['REVIEW', 'TEST'].includes(stage)) return deps.problem(response, 400, 'CR_COMMAND_INVALID', 'stage must be REVIEW or TEST.')
    const decision = body.decision
    result = deps.applyWorkflowLane({ cr: crClone, stage, principal: context.principal, responsibleSystemId, decision, reason, occurredAt, nextId: crNextId })
  } else if (command === 'final-lane') {
    exactCrBodyKeys(body, ['command', 'decision', 'reason'])
    // assertFinalLaneAccess (inside applyFinalLane) enforces role-to-lane mapping.
    // Manager is a valid FINAL lane — do NOT call assertCrWorkflowAction here.
    const decision = body.decision
    result = deps.applyFinalLane({ cr: crClone, principal: context.principal, responsibleSystemId, decision, reason, occurredAt, nextId: crNextId })
    // Fix 3: when all 3 lanes satisfied, append the COMPLETED transition immediately.
    if (!result.idempotent && result.allSatisfied) {
      deps.applyTransition({ cr: crClone, targetState: 'COMPLETED', reason: 'All three FINAL lanes approved.', principal: context.principal, occurredAt, nextId: crNextId })
    }
  } else if (command === 'test-run') {
    exactCrBodyKeys(body, ['command', 'attachment_id', 'state', 'bounded_summary'])
    deps.assertCrWorkflowAction({ principal: context.principal, responsibleSystemId, crId })
    const attachmentId = typeof body.attachment_id === 'string' ? body.attachment_id : ''
    const runState = body.state
    const boundedSummary = body.bounded_summary
    const changeAttachments = new Map(Array.isArray(core.changeAttachments) ? core.changeAttachments : [])
    result = deps.applyTestRun({ cr: crClone, attachmentId, state: runState, boundedSummary, principal: context.principal, responsibleSystemId, occurredAt, nextId: crNextId, changeAttachments })
  } else {
    return deps.problem(response, 400, 'CR_COMMAND_INVALID', `Unknown command: ${command}. Supported: transition, workflow-approval, final-lane, test-run.`)
  }

  if (result.idempotent) {
    return deps.json(response, 200, { version: snapshot.version, idempotent: true, change_request: crClone }, { ETag: `"${snapshot.version}"` })
  }

  crClone.version = Number.isSafeInteger(crClone.version) ? crClone.version + 1 : 1
  updatedRecords[crIndex] = crClone
  updatedCore.sequence = (typeof core.sequence === 'number' ? core.sequence : 0) + 1
  const newVersion = await context.stateStore.writeIfVersion('core', updatedCore, expectedVersion)
  return deps.json(response, 200, { version: newVersion, change_request: crClone }, { ETag: `"${newVersion}"` })
}

return { crNextId, exactCrBodyKeys, crBoundedText, crChangeDocument, crColumnIdentity, crValidateColumnProposals, crOptionalText, crOptionalDate, bulkCandidateChangeRequestApi, crCreateApi, applyReportApi, crCommandApi }
}
