/* global Buffer */
// Dependencies are supplied by bootstrap; this module never constructs a shared client.
export function createModulesMclChangeHistory(deps) {
async function changeHistoryAccess(request, response, url, context) {
  deps.rejectProtectedAccessClaims(request, url)
  if (!['GET', 'PUT'].includes(request.method || '')) {
    return deps.problem(response, 405, 'METHOD_NOT_ALLOWED', 'Change-history access supports only GET and PUT.')
  }
  if (context.subject.error) throw context.subject.error
  const subjectId = context.subject.subjectId
  const snapshot = await context.stateStore.readChangeHistoryAccess()
  if (request.method === 'GET') {
    if (snapshot.access.value === null) throw deps.accessError(503, 'ACCESS_NOT_CONFIGURED', 'Change-history access is not provisioned.')
    const document = deps.changeHistoryDocumentFromSnapshot(snapshot)
    deps.requireActiveAccessAdmin(document, subjectId)
    return deps.json(response, 200, { ...document, version: snapshot.access.version }, { ETag: `"${snapshot.access.version}"` })
  }
  const expectedVersion = deps.accessIfMatch(request)
  if (expectedVersion !== snapshot.access.version) throw deps.accessError(409, 'ACCESS_VERSION_STALE', 'The access version is stale.')
  if (snapshot.access.value !== null) {
    deps.requireActiveAccessAdmin(deps.changeHistoryDocumentFromSnapshot(snapshot), subjectId)
  }
  const body = await deps.bodyJson(request)
  deps.rejectProtectedAccessBodyClaims(body)
  const document = deps.normalizeChangeHistoryAccessDocument(body)
  deps.requireActiveAccessAdmin(document, subjectId)
  const result = await context.stateStore.writeChangeHistoryAccess({
    expectedAccessVersion: snapshot.access.version,
    expectedCoreVersion: snapshot.core.version,
    accessValue: deps.privateChangeHistoryAccess(document),
    coreValue: deps.changeHistoryAccessCoreProjection(snapshot.core.value, document, snapshot.access.version + 1),
  })
  return deps.json(response, 200, { ...document, version: result.accessVersion }, { ETag: `"${result.accessVersion}"` })
}

function changeHistoryActiveUser(document, subjectId) {
  const user = document.users.find((item) => item.subject_id === subjectId)
  if (!user?.active) throw deps.accessError(403, 'SUBJECT_FORBIDDEN', 'The session subject is missing or inactive.')
  return user
}

function changeHistoryAssignee(system, document) {
  const unassigned = { subject_id: null, responsibility: 'UNASSIGNED', system_id: system.system_id, priority: null, basis: 'CURRENT_POC_PROJECTION' }
  if (system.resolution !== 'RESOLVED') return unassigned
  const activeUsers = new Set(document.users.filter((user) => user.active).map((user) => user.subject_id))
  for (const responsibility of ['DATA_STEWARD', 'DEVELOPER']) {
    const candidates = document.system_assignments.filter((item) => item.active
      && item.system_id === system.system_id && item.responsibility === responsibility
      && activeUsers.has(item.subject_id)).sort((left, right) => left.priority - right.priority)
    if (!candidates.length) continue
    const winners = candidates.filter((item) => item.priority === candidates[0].priority)
    if (winners.length !== 1) return unassigned
    return { subject_id: winners[0].subject_id, responsibility, system_id: system.system_id, priority: winners[0].priority, basis: 'CURRENT_POC_PROJECTION' }
  }
  // The normalized OWNERSHIP payload has no reviewed owner-ref extraction contract yet.
  // Preserve stored provider_owner_refs for a future bounded adapter, but fail closed today.
  return unassigned
}

function changeHistoryLinkState(links) {
  let primary = null
  const candidates = new Map()
  for (const link of [...links].sort((left, right) => Number(left.link_version) - Number(right.link_version))) {
    const target = { change_request_id: link.change_request_id, change_request_round: Number(link.change_request_round) }
    if (link.action === 'SET_PRIMARY') primary = target
    if (link.action === 'CLEAR_PRIMARY' && primary?.change_request_id === link.change_request_id) primary = null
    if (link.action === 'ADD_CANDIDATE') candidates.set(link.change_request_id, target)
    if (link.action === 'REMOVE_CANDIDATE') candidates.delete(link.change_request_id)
  }
  const latest = links.reduce((current, link) => !current || Number(link.link_version) > Number(current.link_version) ? link : current, null)
  return {
    primary,
    candidates: [...candidates.values()].sort((left, right) => left.change_request_id.localeCompare(right.change_request_id)),
    etag: latest ? `"${latest.event_hash}"` : '"0"',
    link_version: Number(latest?.link_version ?? 0),
  }
}

function changeHistoryPrecision(event, projection) {
  if (event.topic_contract !== 'MetadataChangeLog_Versioned_v1') return null
  const sources = Array.isArray(projection.sources) ? projection.sources : []
  const sourceMatches = sources.filter((source) => source.source_identity_hash === event.source_identity_hash
    && source.provider_name === 'DataHub' && /^[0-9a-f]{64}$/.test(String(source.schema_contract_hash || '')))
  if (sourceMatches.length !== 1) return null
  const checkpoints = Array.isArray(projection.checkpoints) ? projection.checkpoints : []
  const matches = checkpoints.filter((checkpoint) => checkpoint.source_identity_hash === event.source_identity_hash
    && checkpoint.topic_contract === event.topic_contract
    && Number(checkpoint.source_partition) === Number(event.source_partition))
  if (matches.length !== 1) return null
  const sourceOffset = Number(event.source_offset)
  const firstExactOffset = Number(matches[0].first_exact_offset)
  const nextOffset = Number(matches[0].next_offset)
  return Number.isSafeInteger(sourceOffset) && Number.isSafeInteger(firstExactOffset) && Number.isSafeInteger(nextOffset)
    && sourceOffset >= firstExactOffset && sourceOffset < nextOffset
    ? 'EXACT_MCL'
    : null
}

function changeHistoryLinkedCr(target, core, targetsById, eventSystemId) {
  if (!target) return null
  const cr = changeHistoryCr(core, target.change_request_id)
  if (!cr || cr.active === false || ['REJECTED', 'CANCELLED'].includes(cr.state)
    || Number(cr.current_round_number) !== Number(target.change_request_round)
    || deps.crResponsibleSystemId(cr) !== eventSystemId
    || !changeManagementRecordTargets(cr, targetsById)) return null
  return cr
}

function changeHistoryAuthorizedCurrent(current, core, targetsById, eventSystemId) {
  return {
    ...current,
    primary: changeHistoryLinkedCr(current.primary, core, targetsById, eventSystemId)
      ? current.primary
      : null,
    candidates: current.candidates.filter((candidate) => (
      changeHistoryLinkedCr(candidate, core, targetsById, eventSystemId)
    )),
  }
}

function changeHistoryRow(event, projection, document, target, targetsById) {
  const systemResolution = target.system_resolution
    ?? (target.system_id ? 'RESOLVED' : 'UNMAPPED')
  const system = {
    resolution: systemResolution,
    system_id: systemResolution === 'RESOLVED' ? target.system_id : null,
    provider_context: target.locator,
  }
  const assignee = changeHistoryAssignee(system, document)
  const links = projection.links.filter((link) => link.ledger_event_identity === event.event_identity)
  const current = changeHistoryAuthorizedCurrent(
    changeHistoryLinkState(links),
    projection.core.value,
    targetsById,
    system.system_id,
  )
  return {
    event,
    system,
    assignee,
    locator: target.locator,
    precision: changeHistoryPrecision(event, projection),
    links,
    current,
  }
}

function changeHistoryCrPresentationStage(cr) {
  if (!cr || cr.active === false || ['REJECTED', 'CANCELLED'].includes(cr.state)) return 'UNLINKED'
  if (cr.state === 'REGISTERED') return 'RECEIVED'
  if (cr.state === 'IN_REVIEW') {
    const rounds = Array.isArray(cr.rounds) ? cr.rounds : []
    const currentRound = rounds.find((round) => round?.id === cr.current_round_id)
    const transitions = (Array.isArray(cr.transitions) ? cr.transitions : [])
      .filter((transition) => transition?.round_id === cr.current_round_id)
    const enteredReview = transitions.some((transition) => transition?.to_state === 'IN_REVIEW')
    const resubmitted = Number(cr.current_round_number) > 1
      || currentRound?.revision_kind === 'EDITED'
      || transitions.some((transition) => transition?.from_state === 'CHANGES_REQUESTED'
        && (transition?.to_state === 'IN_REVIEW'
          || (transition?.to_state === 'REGISTERED' && enteredReview)))
    return resubmitted ? 'RECHECK' : 'RECEIVED'
  }
  if (cr.state === 'CHANGES_REQUESTED') return 'RECHECK'
  if (['TESTING', 'APPLY_QUEUED', 'APPLYING', 'APPLY_FAILED'].includes(cr.state)) return 'TESTING'
  if (cr.state === 'FINAL_REVIEW') return 'FINAL_REVIEW'
  if (['APPLIED', 'COMPLETED'].includes(cr.state)) return 'COMPLETED'
  return 'UNLINKED'
}

function changeHistoryRowPresentationStage(row, core) {
  return row.current.primary
    ? changeHistoryCrPresentationStage(changeHistoryCr(core, row.current.primary.change_request_id))
    : 'UNLINKED'
}

function changeHistoryAllowedLinkActions(row, principal) {
  if (!principal.capabilitySet.has('change.execute') || row.system.resolution !== 'RESOLVED') return []
  if (principal.globalSystemMutation || principal.systemIds.has(row.system.system_id)) {
    return [...deps.changeHistoryActions.keys()]
  }
  return []
}

function changeHistoryPresentationRecord(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : null
}

function changeHistoryPresentationValue(value) {
  if (value === null || value === undefined || value === '') return null
  const rendered = typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'
    ? String(value)
    : JSON.stringify(value)
  if (rendered === undefined) return null
  return rendered.length <= 500 ? rendered : `${rendered.slice(0, 497)}…`
}

function changeHistoryPresentation(row) {
  const event = row.event
  const before = changeHistoryPresentationRecord(event.before_data)
  const after = changeHistoryPresentationRecord(event.after_data)
  const fieldName = deps.boundedString(after?.field_path, 900) || deps.boundedString(before?.field_path, 900) || null
  const targetKind = (fieldName
    || String(event.normalized_entity_key).startsWith('field:')
    || String(event.normalized_entity_key).startsWith('field-metadata:'))
    ? 'COLUMN'
    : 'TABLE'
  const lifecycle = event.category === 'LIFECYCLE' && ['entity', 'status'].includes(event.source_aspect)
  const columnLifecycle = targetKind === 'COLUMN'
    && event.category === 'TECHNICAL_SCHEMA'
    && event.source_aspect === 'schemaMetadata'
  const presentationChangeType = lifecycle && event.operation === 'CREATE' ? 'TABLE_CREATE'
    : lifecycle && event.operation === 'DELETE' ? 'TABLE_DELETE'
      : columnLifecycle && event.operation === 'CREATE' ? 'COLUMN_CREATE'
        : columnLifecycle && event.operation === 'DELETE' ? 'COLUMN_DELETE'
          : targetKind === 'COLUMN' ? 'COLUMN_CHANGE' : 'TABLE_CHANGE'
  const fields = []
  const addField = (field, beforeValue, afterValue) => {
    const beforeText = changeHistoryPresentationValue(beforeValue)
    const afterText = changeHistoryPresentationValue(afterValue)
    if (beforeText === afterText) return
    fields.push({ field, before: beforeText, after: afterText })
  }
  if (!['TABLE_CREATE', 'TABLE_DELETE', 'COLUMN_CREATE', 'COLUMN_DELETE'].includes(presentationChangeType)) {
    if (event.category === 'DOCUMENTATION') {
      addField('DESCRIPTION', before?.description, after?.description)
      addField('PROPERTY', before?.custom_properties, after?.custom_properties)
    } else if (event.category === 'TAG') {
      addField('TAG', before?.tag_urn, after?.tag_urn)
    } else if (event.category === 'GLOSSARY_TERM') {
      addField('GLOSSARY_TERM', before?.term_urn, after?.term_urn)
    } else if (event.category === 'DOMAIN') {
      addField('DOMAIN', before?.domain_urn, after?.domain_urn)
    } else if (event.category === 'OWNERSHIP') {
      addField('OWNER', before && {
        owner_urn: before.owner_urn ?? null,
        ownership_type: before.ownership_type ?? null,
      }, after && {
        owner_urn: after.owner_urn ?? null,
        ownership_type: after.ownership_type ?? null,
      })
    } else if (event.category === 'TECHNICAL_SCHEMA' && targetKind === 'COLUMN') {
      addField('TYPE', before && {
        native_data_type: before.native_data_type ?? null,
        logical_type: before.logical_type ?? null,
      }, after && {
        native_data_type: after.native_data_type ?? null,
        logical_type: after.logical_type ?? null,
      })
      addField('NULLABLE', before?.nullable, after?.nullable)
      addField('DESCRIPTION', before?.description, after?.description)
    } else if (event.category === 'TECHNICAL_SCHEMA') {
      addField('SCHEMA', before, after)
    }
    if (fields.length === 0 && (before !== null || after !== null)) addField('PROPERTY', before, after)
  }
  return {
    target_kind: targetKind,
    field_name: fieldName,
    presentation_change_type: presentationChangeType,
    change_summary: `${event.operation} · ${event.category}`,
    change_detail: fields.slice(0, 8),
  }
}

function changeHistoryPublicRow(row, detail = false) {
  const event = row.event
  return {
    event_id: event.event_identity,
    transaction_id: event.normalized_change_transaction_id,
    asset_urn: event.asset_urn,
    entity_key: event.normalized_entity_key,
    category: event.category,
    change_type: event.category === 'TECHNICAL_SCHEMA' && event.source_aspect === 'schemaMetadata'
      ? 'SCHEMA_CHANGE'
      : 'METADATA_CHANGE',
    source_aspect: event.source_aspect,
    operation: event.operation,
    precision: row.precision,
    source_occurred_at: event.source_occurred_at,
    detected_at: event.detected_at,
    captured_at: event.captured_at,
    system: row.system,
    locator: row.locator,
    assignee: row.assignee,
    current_stage: row.current_stage,
    allowed_link_actions: row.allowed_link_actions,
    current_primary: row.current.primary,
    current_candidates: row.current.candidates,
    link_version: row.current.link_version,
    ...changeHistoryPresentation(row),
    ...(detail ? { before: event.before_data, after: event.after_data } : {}),
  }
}

function changeHistoryPublicLinkEvent(link) {
  return {
    link_event_identity: link.link_event_identity,
    event_hash: link.event_hash,
    ledger_event_identity: link.ledger_event_identity,
    link_version: Number(link.link_version),
    link_kind: link.link_kind,
    action: link.action,
    change_request_id: link.change_request_id,
    change_request_round: Number(link.change_request_round),
    prior_link_hash: link.prior_link_hash,
    reason: link.reason,
    policy_hash: link.policy_hash,
    basis_hash: link.basis_hash,
    actor_ref: link.actor_ref,
    occurred_at: link.occurred_at,
    captured_at: link.captured_at,
  }
}

function changeHistoryCanDisplayLink(link, core, targetsById) {
  const cr = changeHistoryCr(core, link.change_request_id)
  return Boolean(cr && changeManagementRecordTargets(cr, targetsById))
}

function changeHistoryPageParameters(parameters) {
  const rawLimit = parameters.get('limit') ?? '50'
  if (!/^\d+$/.test(rawLimit)) throw deps.accessError(400, 'PAGE_INVALID', 'limit must be an integer.')
  const limit = Number(rawLimit)
  if (limit < 1 || limit > 100) throw deps.accessError(400, 'PAGE_INVALID', 'limit must be between 1 and 100.')
  let cursor = null
  const token = parameters.get('cursor')
  if (token) {
    try {
      const parsed = JSON.parse(Buffer.from(token, 'base64url').toString('utf8'))
      if (!Array.isArray(parsed) || parsed.length !== 2 || parsed.some((item) => typeof item !== 'string' || item.length > 255)) throw new Error()
      cursor = parsed
    } catch { throw deps.accessError(400, 'CURSOR_INVALID', 'The change-history cursor is invalid.') }
  }
  return { limit, cursor }
}

function changeHistoryPage(rows, parameters, keyOf) {
  const { limit, cursor } = changeHistoryPageParameters(parameters)
  const visible = cursor ? rows.filter((row) => deps.canonicalJson(keyOf(row)) < deps.canonicalJson(cursor)) : rows
  const items = visible.slice(0, limit)
  return {
    items,
    next_cursor: visible.length > limit ? Buffer.from(deps.canonicalJson(keyOf(items.at(-1))), 'utf8').toString('base64url') : null,
    limit,
  }
}

function changeHistoryProjectionAuthority(projection, context) {
  if (context.subject.error) throw context.subject.error
  if (projection.access.value === null) throw deps.accessError(503, 'ACCESS_NOT_CONFIGURED', 'Change-history access is not provisioned.')
  if (!deps.validDatahubInventory(projection.catalog?.value)) {
    throw deps.accessError(503, 'CATALOG_PROJECTION_REQUIRED', 'A complete current PostgreSQL catalog projection is required for System resolution.')
  }
  const catalogIds = projection.catalog.value.items.map((item) => item.id)
  if (new Set(catalogIds).size !== catalogIds.length) {
    throw deps.accessError(503, 'CATALOG_PROJECTION_INVALID', 'The current catalog projection contains duplicate asset identities.')
  }
  const document = deps.changeHistoryDocumentFromSnapshot(projection)
  return { document, user: changeHistoryActiveUser(document, context.subject.subjectId) }
}

function changeHistoryCr(core, id) {
  const records = Array.isArray(core?.changeRecords) ? core.changeRecords : []
  return records.find((item) => item && item.id === id)
}

function assertChangeHistoryCrBinding(cr, roundNumber, systemId, targetsById) {
  const target = cr ? { change_request_id: cr.id, change_request_round: roundNumber } : null
  if (!changeHistoryLinkedCr(target, { changeRecords: cr ? [cr] : [] }, targetsById, systemId)) {
    throw deps.accessError(409, 'CR_BINDING_DRIFT', 'The change request is no longer bound to the event System.')
  }
}

function changeHistoryMutationHeaders(request) {
  const idempotencyKey = request.headers['idempotency-key']
  if (typeof idempotencyKey !== 'string' || !idempotencyKey.trim() || idempotencyKey.length > 200) {
    throw deps.accessError(428, 'IDEMPOTENCY_KEY_REQUIRED', 'A bounded Idempotency-Key is required.')
  }
  const value = request.headers['if-match']
  if (typeof value !== 'string') throw deps.accessError(428, 'IF_MATCH_REQUIRED', 'If-Match is required.')
  if (value !== '"0"' && !/^"[0-9a-f]{64}"$/.test(value)) throw deps.accessError(400, 'IF_MATCH_INVALID', 'If-Match must be "0" or a quoted link event hash.')
  return { idempotencyKey: idempotencyKey.trim(), priorLinkHash: value === '"0"' ? null : value.slice(1, -1) }
}

function changeHistoryCommandBody(body) {
  deps.rejectProtectedAccessBodyClaims(body)
  const keys = Object.keys(body)
  const allowed = ['action', 'change_request_id', 'change_request_round', 'reason']
  if (keys.some((key) => !allowed.includes(key)) || allowed.some((key) => !Object.hasOwn(body, key))) {
    throw deps.accessError(400, 'LINK_COMMAND_INVALID', 'The link command has missing or unknown fields.')
  }
  const action = typeof body.action === 'string' ? body.action : ''
  const linkKind = deps.changeHistoryActions.get(action)
  const changeRequestId = typeof body.change_request_id === 'string' ? body.change_request_id.trim() : ''
  const reason = typeof body.reason === 'string' ? body.reason.trim() : ''
  if (!linkKind || !changeRequestId || changeRequestId.length > 200
    || !Number.isSafeInteger(body.change_request_round) || body.change_request_round < 1
    || !reason || reason.length > 2000) {
    throw deps.accessError(400, 'LINK_COMMAND_INVALID', 'The link command is outside its typed bounds.')
  }
  return { action, linkKind, changeRequestId, changeRequestRound: body.change_request_round, reason }
}

function changeHistoryWeekBounds(weekStart) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(weekStart || '')) {
    throw deps.accessError(400, 'WEEK_START_INVALID', 'week_start must be YYYY-MM-DD.')
  }
  const dayMilliseconds = 24 * 60 * 60 * 1000
  const kstOffsetMilliseconds = 9 * 60 * 60 * 1000
  const start = new Date(`${weekStart}T00:00:00+09:00`)
  const kstDayNumber = (start.getTime() + kstOffsetMilliseconds) / dayMilliseconds
  const kstWeekday = ((kstDayNumber + 3) % 7 + 7) % 7
  const normalizedKstDate = Number.isFinite(start.getTime())
    ? new Date(start.getTime() + kstOffsetMilliseconds).toISOString().slice(0, 10)
    : undefined
  if (normalizedKstDate !== weekStart || kstWeekday !== 0) {
    throw deps.accessError(400, 'WEEK_START_INVALID', 'week_start must be a valid KST Monday.')
  }
  const end = new Date(start.getTime() + 7 * dayMilliseconds)
  return {
    start,
    end,
    week_end_exclusive: new Date(end.getTime() + kstOffsetMilliseconds).toISOString().slice(0, 10),
  }
}

function changeHistoryKstDate(value, field) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) {
    throw deps.accessError(400, 'DATE_RANGE_INVALID', `${field} must be YYYY-MM-DD.`)
  }
  const date = new Date(`${value}T00:00:00+09:00`)
  const normalized = Number.isFinite(date.getTime())
    ? new Date(date.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10)
    : undefined
  if (normalized !== value) {
    throw deps.accessError(400, 'DATE_RANGE_INVALID', `${field} must be a valid KST date.`)
  }
  return date
}

function changeHistoryDateBounds(parameters) {
  const weekStart = parameters.get('week_start')
  const dateFrom = parameters.get('date_from')
  const dateTo = parameters.get('date_to')
  if (weekStart && (dateFrom || dateTo)) {
    throw deps.accessError(400, 'DATE_RANGE_INVALID', 'week_start cannot be combined with date_from or date_to.')
  }
  if (weekStart) return changeHistoryWeekBounds(weekStart)
  if (!dateFrom && !dateTo) return null
  if (!dateFrom || !dateTo) {
    throw deps.accessError(400, 'DATE_RANGE_INVALID', 'date_from and date_to must be supplied together.')
  }
  const start = changeHistoryKstDate(dateFrom, 'date_from')
  const inclusiveEnd = changeHistoryKstDate(dateTo, 'date_to')
  if (start.getTime() > inclusiveEnd.getTime()) {
    throw deps.accessError(400, 'DATE_RANGE_INVALID', 'date_from must not be after date_to.')
  }
  return { start, end: new Date(inclusiveEnd.getTime() + 24 * 60 * 60 * 1000) }
}

function changeHistoryInBounds(row, bounds) {
  if (!bounds) return true
  const occurredAt = row.event.source_occurred_at
  return Boolean(occurredAt)
    && Date.parse(occurredAt) >= bounds.start.getTime()
    && Date.parse(occurredAt) < bounds.end.getTime()
}

function changeHistoryTransactionStage(transactionRows, core) {
  const primaryKeys = new Set(transactionRows.map((row) => row.current.primary && deps.canonicalJson(row.current.primary)).filter(Boolean))
  if (transactionRows.some((row) => !row.current.primary) || primaryKeys.size !== 1) return 'UNLINKED'
  const primary = JSON.parse([...primaryKeys][0])
  return changeHistoryCrPresentationStage(changeHistoryCr(core, primary.change_request_id))
}

function changeManagementSchemaKey(platform, databaseName, schemaName, systemId, systemResolution = systemId ? 'RESOLVED' : 'UNMAPPED') {
  return JSON.stringify([platform.toLowerCase(), databaseName, schemaName, systemId, systemResolution])
}

function changeHistoryCurrentTableAuthority(catalog, mappingDocument, document, principal) {
  const activeSystemIds = new Set(document.systems.filter((system) => system.active)
    .map((system) => system.system_id))
  const systems = new Map(document.systems.map((system) => [system.system_id, system]))
  const targetsById = new Map()
  const eventTargetsById = new Map()
  const addTarget = (assetId, locator, historical = false) => {
    const mappedSystemIds = deps.activeSystemIdsForTable(mappingDocument, assetId, activeSystemIds)
    const systemId = mappedSystemIds.length === 1 ? mappedSystemIds[0] : null
    const systemResolution = mappedSystemIds.length === 1 ? 'RESOLVED'
      : mappedSystemIds.length > 1 ? 'AMBIGUOUS'
        : 'UNMAPPED'
    const eventTarget = {
      asset_id: assetId,
      key: changeManagementSchemaKey(
        locator.platform,
        locator.database_name,
        locator.schema_name,
        systemId,
        systemResolution,
      ),
      locator,
      system_id: systemId,
      system_resolution: systemResolution,
      ...(historical ? { historical: true } : {}),
    }
    eventTargetsById.set(assetId, eventTarget)
    if (systemResolution === 'RESOLVED' && systems.get(systemId)?.active) {
      targetsById.set(assetId, eventTarget)
    }
  }
  for (const asset of catalog.items) {
    const assetId = asset?.id
    if (asset?.dataset_kind !== 'TABLE' || !deps.canReadAsset(principal, asset, 'change')) continue
    if (typeof asset.platform !== 'string' || typeof asset.database_name !== 'string'
      || typeof asset.schema_name !== 'string') continue
    const locator = {
      platform: asset.platform.trim().toLowerCase(),
      database_name: asset.database_name.trim(),
      schema_name: asset.schema_name.trim(),
      asset_name: typeof asset.name === 'string' && asset.name.trim() ? asset.name.trim() : null,
    }
    if (!locator.platform || !locator.database_name || !locator.schema_name) continue
    addTarget(assetId, locator)
  }
  for (const snapshot of mappingDocument.asset_snapshots) {
    if (eventTargetsById.has(snapshot.table_identity)) continue
    const historicalAsset = {
      id: snapshot.table_identity,
      dataset_kind: snapshot.dataset_kind,
      security_grade: snapshot.security_grade,
    }
    if (!deps.canReadAsset(principal, historicalAsset, 'change')) continue
    const locator = {
      platform: snapshot.platform,
      database_name: snapshot.database_name,
      schema_name: snapshot.schema_name,
      asset_name: snapshot.asset_name,
    }
    addTarget(snapshot.table_identity, locator, true)
  }
  return { targetsById, eventTargetsById }
}

function changeManagementBaseOverview(targetsById, document) {
  const systems = new Map(document.systems.map((system) => [system.system_id, system]))
  const overview = new Map()
  for (const target of targetsById.values()) {
    if (overview.has(target.key)) continue
    const system = systems.get(target.system_id)
    if (!system?.active) continue
    const { locator, system_id: systemId, key } = target
    overview.set(key, {
      platform: locator.platform,
      database_name: locator.database_name,
      schema_name: locator.schema_name,
      system_id: systemId,
      system_resolution: 'RESOLVED',
      system_code: system.code,
      system_name: system.name,
      assignees: [],
      event_count: 0,
      unprogressed_event_count: 0,
      pending_count: 0,
      total_count: 0,
      received_count: 0,
      recheck_count: 0,
      testing_count: 0,
      final_review_count: 0,
      completed_count: 0,
    })
  }
  return overview
}

function changeManagementEventOverview(rows, core, document, overview) {
  const systems = new Map(document.systems.map((system) => [system.system_id, system]))
  const transactions = new Map()
  for (const row of rows) {
    const transactionId = row.event.normalized_change_transaction_id
    const values = transactions.get(transactionId) ?? []
    values.push(row)
    transactions.set(transactionId, values)
  }
  const stageByTransaction = new Map([...transactions].map(([transactionId, values]) => (
    [transactionId, changeHistoryTransactionStage(values, core)]
  )))
  const transactionIdsBySchema = new Map()
  for (const row of rows) {
    if (!row.locator) continue
    const systemId = row.system.resolution === 'RESOLVED' ? row.system.system_id : null
    const key = changeManagementSchemaKey(
      row.locator.platform,
      row.locator.database_name,
      row.locator.schema_name,
      systemId,
      row.system.resolution,
    )
    if (!overview.has(key)) {
      const system = systems.get(systemId)
      overview.set(key, {
        platform: row.locator.platform,
        database_name: row.locator.database_name,
        schema_name: row.locator.schema_name,
        system_id: systemId,
        system_resolution: row.system.resolution,
        system_code: system?.code ?? null,
        system_name: system?.name ?? null,
        assignees: [],
        event_count: 0,
        unprogressed_event_count: 0,
        pending_count: 0,
        total_count: 0,
        received_count: 0,
        recheck_count: 0,
        testing_count: 0,
        final_review_count: 0,
        completed_count: 0,
      })
    }
    const transactionIds = transactionIdsBySchema.get(key) ?? new Set()
    transactionIds.add(row.event.normalized_change_transaction_id)
    transactionIdsBySchema.set(key, transactionIds)
  }
  for (const [key, transactionIds] of transactionIdsBySchema) {
    const overviewRow = overview.get(key)
    overviewRow.event_count = transactionIds.size
    overviewRow.unprogressed_event_count = [...transactionIds]
      .filter((transactionId) => stageByTransaction.get(transactionId) === 'UNLINKED').length
  }
  return overview
}

function changeManagementCrCreatedInBounds(record, bounds) {
  if (!bounds) return true
  const createdAt = Date.parse(record.created_at)
  return Number.isFinite(createdAt)
    && createdAt >= bounds.start.getTime()
    && createdAt < bounds.end.getTime()
}

function changeManagementRecordTargets(record, targetsById) {
  if (record?.active === false) return null
  const responsibleSystemId = deps.crResponsibleSystemId(record)
  const items = Array.isArray(record?.items) ? record.items : []
  if (!responsibleSystemId || items.length === 0) return null
  const targets = []
  for (const item of items) {
    const target = typeof item?.target_asset_id === 'string'
      ? targetsById.get(item.target_asset_id)
      : undefined
    if (!target || target.system_id !== responsibleSystemId
      || item.target_system_id !== target.system_id
      || item.routing_system_id !== target.system_id) return null
    targets.push(target)
  }
  return targets
}

function changeManagementAddCrCounts(overview, visibleRecords) {
  for (const { record, targets } of visibleRecords) {
    if (record.active === false || ['REJECTED', 'CANCELLED'].includes(record.state)) continue
    const stage = changeHistoryCrPresentationStage(record)
    for (const key of new Set(targets.map((target) => target.key))) {
      const row = overview.get(key)
      if (!row) continue
      row.total_count += 1
      if (record.state === 'REGISTERED') row.pending_count += 1
      if (stage === 'RECEIVED') row.received_count += 1
      if (stage === 'RECHECK') row.recheck_count += 1
      if (stage === 'TESTING') row.testing_count += 1
      if (stage === 'FINAL_REVIEW') row.final_review_count += 1
      if (stage === 'COMPLETED') row.completed_count += 1
    }
  }
}

function changeManagementPriorityOneAssignees(record, document) {
  const systemId = deps.crResponsibleSystemId(record)
  if (!systemId) return []
  const users = new Map(document.users.filter((user) => user.active)
    .map((user) => [user.subject_id, user]))
  const assignments = document.system_assignments.filter((assignment) => assignment.active
    && assignment.system_id === systemId && assignment.priority === 1
    && users.has(assignment.subject_id))
    .sort((left, right) => left.responsibility.localeCompare(right.responsibility)
      || left.subject_id.localeCompare(right.subject_id))
  const seenSubjects = new Set()
  const displayNames = []
  for (const assignment of assignments) {
    if (seenSubjects.has(assignment.subject_id)) continue
    seenSubjects.add(assignment.subject_id)
    const displayName = users.get(assignment.subject_id)?.display_name
    if (typeof displayName === 'string' && displayName.trim()) displayNames.push(displayName)
  }
  return displayNames
}

function changeManagementSummaryItem(record, targets, document) {
  const first = Array.isArray(record.items) ? record.items[0] : null
  const locator = targets[0]?.locator
  const requester = document.users.find((user) => user.subject_id === record.requester_id)
  return {
    id: record.id,
    number: record.number,
    request_type: record.request_type,
    title: record.title,
    state: record.state,
    requester_id: record.requester_id,
    requester_name: requester?.display_name || null,
    requester_department_id: record.requester_department_id ?? null,
    current_round_number: Number(record.current_round_number || 1),
    created_at: record.created_at,
    requested_due_date: record.requested_due_date ?? null,
    priority: record.priority ?? null,
    urgency: record.urgency ?? null,
    classification: record.classification,
    version: Number(record.version || 1),
    item_count: Array.isArray(record.items) ? record.items.length : 0,
    target_schema_name: locator.schema_name,
    assignee_names: changeManagementPriorityOneAssignees(record, document),
    first_item: {
      target_ref: first?.target_ref ?? '',
      aspect_name: first?.aspect_name ?? '',
      operation: first?.operation ?? '',
    },
  }
}

function changeManagementOverviewRows(overview) {
  return [...overview.values()].sort((left, right) => (
    changeManagementSchemaKey(left.platform, left.database_name, left.schema_name, left.system_id, left.system_resolution)
      .localeCompare(changeManagementSchemaKey(right.platform, right.database_name, right.schema_name, right.system_id, right.system_resolution))
  ))
}

function changeHistoryWeeklySummary(rows, core, document, weekStart) {
  const bounds = changeHistoryWeekBounds(weekStart)
  const inWeek = rows.filter((row) => row.event.source_occurred_at
    && Date.parse(row.event.source_occurred_at) >= bounds.start.getTime()
    && Date.parse(row.event.source_occurred_at) < bounds.end.getTime())
  const unknown = new Set(rows.filter((row) => !row.event.source_occurred_at)
    .map((row) => row.event.normalized_change_transaction_id)).size
  const transactions = new Map()
  for (const row of inWeek) {
    const list = transactions.get(row.event.normalized_change_transaction_id) ?? []
    list.push(row)
    transactions.set(row.event.normalized_change_transaction_id, list)
  }
  const counts = { unlinked_count: 0, received_count: 0, recheck_count: 0, testing_count: 0, final_review_count: 0, completed_count: 0 }
  for (const transactionRows of transactions.values()) {
    const stage = changeHistoryTransactionStage(transactionRows, core)
    counts[`${stage.toLowerCase()}_count`] += 1
  }
  return {
    week_start: weekStart,
    week_end_exclusive: bounds.week_end_exclusive,
    timezone: 'Asia/Seoul',
    as_of: new Date().toISOString(),
    policy_version: document.policy.version,
    policy_hash: deps.canonicalHash(document),
    count_unit: 'DISTINCT_NORMALIZED_CHANGE_TRANSACTION',
    total_count: transactions.size,
    ...counts,
    time_unknown_count: unknown,
    inWeek,
    transactions,
  }
}

function changeHistoryFilterValue(parameters, name, maximum = 255) {
  const raw = parameters.get(name)
  if (raw === null) return null
  const value = raw.trim()
  if (!value || value.length > maximum || deps.hasAccessControlCharacter(value)) {
    throw deps.accessError(400, 'FILTER_INVALID', `The ${name} change-history filter is invalid.`)
  }
  return value
}

function changeHistoryMaximumTimestamp(values) {
  const timestamps = values.filter((value) => Number.isFinite(Date.parse(value)))
    .sort((left, right) => Date.parse(right) - Date.parse(left))
  return timestamps[0] ?? null
}

function changeHistoryMinimumTimestamp(values) {
  const timestamps = values.filter((value) => Number.isFinite(Date.parse(value)))
    .sort((left, right) => Date.parse(left) - Date.parse(right))
  return timestamps[0] ?? null
}

function changeHistorySourceSummary(projection, rows, configuredHash) {
  const sources = Array.isArray(projection.sources) ? projection.sources : []
  let effectiveRows = rows
  let relevantSources
  if (configuredHash != null) {
    // Syntactically-valid configured source hash: use it exclusively for operational status.
    // Fail closed if it does not match any stored source.
    const configuredSources = sources.filter((source) => source.source_identity_hash === configuredHash)
    if (configuredSources.length !== 1) return {
      capture_state: 'SOURCE_NOT_CONFIGURED', sync_status: 'SOURCE_NOT_CONFIGURED',
      first_mcl_offsets: null, last_successful_capture_at: null, ledger_guarantee_from: null,
      ...deps.changeHistoryUnknownCompleteness,
    }
    const configuredSource = configuredSources[0]
    relevantSources = [configuredSource]
    effectiveRows = rows.filter((row) => row.event.source_identity_hash === configuredHash)
  } else {
    // Fallback: derive sources from all historical rows (preserves SOURCE_AMBIGUOUS behaviour).
    const referencedSourceIds = new Set(rows.map((row) => row.event.source_identity_hash).filter(Boolean))
    relevantSources = referencedSourceIds.size
      ? sources.filter((source) => referencedSourceIds.has(source.source_identity_hash))
      : sources
  }
  if (relevantSources.length === 0) return {
    capture_state: 'SOURCE_NOT_CONFIGURED', sync_status: 'SOURCE_NOT_CONFIGURED',
    first_mcl_offsets: null, last_successful_capture_at: null, ledger_guarantee_from: null,
    ...deps.changeHistoryUnknownCompleteness,
  }
  if (relevantSources.length !== 1) return {
    capture_state: 'SOURCE_AMBIGUOUS', sync_status: 'SOURCE_AMBIGUOUS',
    first_mcl_offsets: null, last_successful_capture_at: null, ledger_guarantee_from: null,
    ...deps.changeHistoryUnknownCompleteness,
  }
  const source = relevantSources[0]
  const checkpoints = (Array.isArray(projection.checkpoints) ? projection.checkpoints : [])
    .filter((checkpoint) => checkpoint.source_identity_hash === source.source_identity_hash)
  const gapReceipts = (Array.isArray(projection.gapReceipts) ? projection.gapReceipts : [])
    .filter((receipt) => receipt.source_identity_hash === source.source_identity_hash
      && receipt.reason === 'RETENTION_EXPIRED')
  if (!checkpoints.length) return {
    capture_state: 'CHECKPOINT_NOT_AVAILABLE', sync_status: 'CHECKPOINT_NOT_AVAILABLE',
    first_mcl_offsets: null, last_successful_capture_at: null, ledger_guarantee_from: null,
    ...deps.changeHistoryUnknownCompleteness,
  }
  const validOffsets = checkpoints.every((checkpoint) => Number.isSafeInteger(Number(checkpoint.source_partition))
    && Number.isSafeInteger(Number(checkpoint.first_exact_offset))
    && Number.isSafeInteger(Number(checkpoint.next_offset))
    && Number(checkpoint.next_offset) >= Number(checkpoint.first_exact_offset))
  if (!validOffsets) return {
    capture_state: 'CHECKPOINT_INVALID', sync_status: 'CHECKPOINT_INVALID',
    first_mcl_offsets: null, last_successful_capture_at: null, ledger_guarantee_from: null,
    ...deps.changeHistoryUnknownCompleteness,
  }
  const advanced = checkpoints.every((checkpoint) => Number(checkpoint.next_offset) > Number(checkpoint.first_exact_offset)
    && Number.isFinite(Date.parse(checkpoint.last_captured_at)))
  const firstMclOffsets = checkpoints.map((checkpoint) => ({
    partition: Number(checkpoint.source_partition),
    offset: Number(checkpoint.first_exact_offset),
  })).sort((left, right) => left.partition - right.partition)
  const exactCapturedAt = effectiveRows.filter((row) => row.precision === 'EXACT_MCL').map((row) => row.event.captured_at)
  const captureStatus = projection.captureStatus?.value
  const runtimeCaptureState = captureStatus?.contract === 'DATARIVER_CHANGE_HISTORY_CAPTURE_STATUS_V1'
    && captureStatus.source_identity_hash === source.source_identity_hash
    && ['CONTIGUOUS_CAPTURE_RECORDED', 'CAPTURE_CATCHING_UP', 'CAPTURE_CAUGHT_UP', 'HISTORY_GAP_BLOCKED']
      .includes(captureStatus.state)
    ? captureStatus.state
    : null
  const latestGapByPartition = new Map()
  for (const receipt of gapReceipts) {
    const partition = Number(receipt.source_partition)
    const start = Number(receipt.new_segment_start)
    const high = Number(receipt.observed_high_watermark)
    if (!Number.isSafeInteger(partition) || partition < 0
      || !Number.isSafeInteger(start) || start < 0
      || !Number.isSafeInteger(high) || high < start) continue
    const current = latestGapByPartition.get(partition)
    if (!current || start > current.start) latestGapByPartition.set(partition, { start, high })
  }
  const retainedGapCaughtUp = checkpoints.every((checkpoint) => {
    const gap = latestGapByPartition.get(Number(checkpoint.source_partition))
    return !gap || Number(checkpoint.next_offset) >= gap.high
  })
  // A receipt is durable before its checkpoint advances. An older READY status
  // must not make the replacement exact segment appear current after interruption.
  const captureState = gapReceipts.length > 0 && !retainedGapCaughtUp
    ? 'CAPTURE_CATCHING_UP'
    : runtimeCaptureState ?? (advanced ? 'CONTIGUOUS_CAPTURE_RECORDED' : 'CAPTURE_PENDING')
  const exactCurrentSegments = checkpoints.map((checkpoint) => ({
    partition: Number(checkpoint.source_partition),
    start_offset: latestGapByPartition.get(Number(checkpoint.source_partition))?.start
      ?? Number(checkpoint.first_exact_offset),
    next_offset: Number(checkpoint.next_offset),
    status: 'EXACT_AFTER_GAP',
  })).map((segment) => ({
    ...segment,
    status: latestGapByPartition.has(segment.partition) ? 'EXACT_AFTER_GAP' : 'EXACT',
  })).sort((left, right) => left.partition - right.partition)
  return {
    capture_state: captureState,
    sync_status: captureState,
    first_mcl_offsets: firstMclOffsets,
    last_successful_capture_at: advanced
      ? changeHistoryMinimumTimestamp(checkpoints.map((checkpoint) => checkpoint.last_captured_at))
      : null,
    // One continuity-wide guarantee cannot span an observed retention gap.
    // Exact coverage remains explicit in exact_current_segments.
    ledger_guarantee_from: advanced && gapReceipts.length === 0
      ? changeHistoryMinimumTimestamp(exactCapturedAt) : null,
    history_completeness: gapReceipts.length > 0 ? 'DEGRADED_GAP' : 'EXACT',
    history_gap_reason: gapReceipts.length > 0 ? 'RETENTION_EXPIRED' : null,
    history_gap_count: gapReceipts.length,
    exact_current_segments: exactCurrentSegments,
  }
}

function changeHistorySummary(projection, rows, core, document, weekStart) {
  const weekly = changeHistoryWeeklySummary(rows, core, document, weekStart)
  const transactionEntries = [...weekly.transactions.values()]
  const schemaTransactions = transactionEntries.filter((items) => items.some((row) => row.event.category === 'TECHNICAL_SCHEMA'
    && row.event.source_aspect === 'schemaMetadata')).length
  const metadataTransactions = transactionEntries.filter((items) => items.some((row) => !(row.event.category === 'TECHNICAL_SCHEMA'
    && row.event.source_aspect === 'schemaMetadata'))).length
  const precisionCounts = Object.fromEntries(deps.changeHistoryPrecisionValues.map((precision) => [precision, 0]))
  const categoryCounts = Object.fromEntries([...deps.changeHistoryCategories].map((category) => [category, 0]))
  const operationCounts = Object.fromEntries([...deps.changeHistoryOperations].map((operation) => [operation, 0]))
  for (const transactionRows of transactionEntries) {
    const transactionPrecisions = new Set(transactionRows.map((row) => row.precision).filter(Boolean))
    const transactionCategories = new Set(transactionRows.map((row) => row.event.category))
    const transactionOperations = new Set(transactionRows.map((row) => row.event.operation))
    for (const precision of transactionPrecisions) precisionCounts[precision] += 1
    for (const category of transactionCategories) categoryCounts[category] += 1
    for (const operation of transactionOperations) operationCounts[operation] += 1
  }
  const rawConfiguredHash = deps.process.env.POC_MCL_SOURCE_IDENTITY_HASH?.trim()
  const configuredHash = (rawConfiguredHash && /^[0-9a-f]{64}$/i.test(rawConfiguredHash))
    ? rawConfiguredHash.toLowerCase()
    : null
  const source = changeHistorySourceSummary(projection, rows, configuredHash)
  const runtimeStatus = projection.runtimeStatus?.value
  const runtimeFailure = runtimeStatus?.contract === 'DATARIVER_CHANGE_HISTORY_RUNTIME_STATUS_V1'
    && ['DISCOVERY_FAILED', 'CAPTURE_FAILED'].includes(runtimeStatus.state)
    && deps.isMclRuntimeClassification(runtimeStatus.classification)
    ? runtimeStatus
    : null
  const runtimeFailureStage = /^[A-Z][A-Z0-9_]{0,79}$/.test(runtimeFailure?.failure_stage || '')
    ? runtimeFailure.failure_stage
    : null
  const runtimeFailureDetailCode = /^[A-Z][A-Z0-9_]{0,79}$/.test(runtimeFailure?.failure_detail_code || '')
    ? runtimeFailure.failure_detail_code
    : null
  const runtimeFailureRecordShape = runtimeFailureStage === 'RECORD_NORMALIZATION'
    ? deps.sanitizeMclRecordShape(runtimeFailure?.record_shape)
    : null
  const occurred = rows.map((row) => row.event.source_occurred_at)
  const detected = rows.map((row) => row.event.detected_at)
  const captured = rows.map((row) => row.event.captured_at)
  const { inWeek: _inWeek, transactions: _transactions, ...weeklyPublic } = weekly
  void _inWeek
  void _transactions
  return {
    ...weeklyPublic,
    schema_change_count: schemaTransactions,
    metadata_change_count: metadataTransactions,
    event_count: weekly.inWeek.length,
    distinct_asset_count: new Set(weekly.inWeek.map((row) => row.event.asset_urn)).size,
    precision_counts: precisionCounts,
    category_counts: categoryCounts,
    operation_counts: operationCounts,
    capture_state: runtimeFailure?.state || source.capture_state,
    sync_status: runtimeFailure?.state || source.sync_status,
    capture_failure_classification: runtimeFailure?.classification || null,
    capture_failure_stage: runtimeFailureStage,
    capture_failure_detail_code: runtimeFailureDetailCode,
    capture_failure_record_shape: runtimeFailureRecordShape,
    source_generation: projection.catalog.value.source_generation,
    source_observed_at: projection.catalog.value.observed_at,
    source_occurred_at: changeHistoryMaximumTimestamp(occurred),
    detected_at: changeHistoryMaximumTimestamp(detected),
    captured_at: changeHistoryMaximumTimestamp(captured),
    effective_week_start: weekStart,
    history_available_from: changeHistoryMinimumTimestamp([...occurred, ...detected]),
    ledger_guarantee_from: source.ledger_guarantee_from,
    first_exact_capture_at: source.ledger_guarantee_from,
    first_timeline_checkpoint: null,
    first_mcl_offsets: source.first_mcl_offsets,
    last_successful_capture_at: source.last_successful_capture_at,
    history_completeness: source.history_completeness || 'UNKNOWN',
    history_gap_reason: source.history_gap_reason || null,
    history_gap_count: Number.isSafeInteger(source.history_gap_count) ? source.history_gap_count : 0,
    exact_current_segments: Array.isArray(source.exact_current_segments)
      ? source.exact_current_segments : [],
  }
}

async function changeHistoryApi(request, response, url, context) {
  deps.rejectProtectedAccessClaims(request, url, { allowSystemFilter: true })
  const projection = await context.stateStore.readChangeHistoryProjection({ catalogScope: deps.datahubInventoryStateScope })
  const { document } = changeHistoryProjectionAuthority(projection, context)
  const mappingSnapshot = await context.stateStore.read(deps.POC_TABLE_SYSTEM_MAPPING_SCOPE)
  const mappingDocument = deps.normalizeTableSystemMappingDocument(mappingSnapshot.value)
  const currentTableAuthority = changeHistoryCurrentTableAuthority(
    projection.catalog.value,
    mappingDocument,
    document,
    context.principal,
  )
  const rows = projection.events.map((event) => {
    const target = currentTableAuthority.eventTargetsById.get(event.asset_urn)
    return target
      ? changeHistoryRow(event, projection, document, target, currentTableAuthority.targetsById)
      : null
  })
    .filter(Boolean)
    .map((row) => ({
      ...row,
      current_stage: changeHistoryRowPresentationStage(row, projection.core.value),
      allowed_link_actions: changeHistoryAllowedLinkActions(row, context.principal),
    }))
    .sort((left, right) => String(right.event.source_occurred_at || right.event.detected_at).localeCompare(String(left.event.source_occurred_at || left.event.detected_at))
      || right.event.event_identity.localeCompare(left.event.event_identity))
  const eventLinksMatch = url.pathname.match(/^\/api\/v1\/change-history\/events\/([0-9a-f]{64})\/cr-links$/)
  const eventCommandMatch = url.pathname.match(/^\/api\/v1\/change-history\/events\/([0-9a-f]{64})\/cr-link-events$/)
  const eventMatch = url.pathname.match(/^\/api\/v1\/change-history\/events\/([0-9a-f]{64})$/)
  const changeRequestMatch = url.pathname.match(/^\/api\/v1\/change-requests\/([^/]+)$/)
  const reverseMatch = url.pathname.match(/^\/api\/v1\/change-requests\/([^/]+)\/change-history$/)

  if (request.method === 'GET' && url.pathname === '/api/v1/change-requests/summaries') {
    const bounds = changeHistoryDateBounds(url.searchParams)
    const requestedState = url.searchParams.get('state')
    const allowedStates = new Set([
      'REGISTERED', 'IN_REVIEW', 'CHANGES_REQUESTED', 'TESTING', 'FINAL_REVIEW',
      'APPLY_QUEUED', 'APPLYING', 'APPLIED', 'APPLY_FAILED', 'REJECTED', 'CANCELLED', 'COMPLETED',
    ])
    if (requestedState && !allowedStates.has(requestedState)) {
      throw deps.accessError(400, 'FILTER_INVALID', 'The change-request state filter is invalid.')
    }
    const rawLimit = url.searchParams.get('limit') ?? '25'
    if (!/^\d+$/.test(rawLimit) || Number(rawLimit) < 1 || Number(rawLimit) > 50) {
      throw deps.accessError(400, 'PAGE_INVALID', 'limit must be between 1 and 50.')
    }
    const visibleRecords = (Array.isArray(projection.core.value?.changeRecords)
      ? projection.core.value.changeRecords
      : []).filter((record) => changeManagementCrCreatedInBounds(record, bounds))
      .map((record) => ({
        record,
        targets: changeManagementRecordTargets(record, currentTableAuthority.targetsById),
      }))
      .filter((entry) => entry.targets !== null)
    const overview = changeManagementEventOverview(
      rows.filter((row) => changeHistoryInBounds(row, bounds)),
      projection.core.value,
      document,
      changeManagementBaseOverview(currentTableAuthority.targetsById, document),
    )
    changeManagementAddCrCounts(overview, visibleRecords)
    const overviewRows = changeManagementOverviewRows(overview)
    const filteredRecords = visibleRecords.filter(({ record }) => !requestedState || record.state === requestedState)
      .sort((left, right) => String(right.record.created_at).localeCompare(String(left.record.created_at))
        || String(right.record.id).localeCompare(String(left.record.id)))
    const page = changeHistoryPage(filteredRecords, url.searchParams, ({ record }) => (
      [String(record.created_at || ''), String(record.id || '')]
    ))
    const items = page.items.map(({ record, targets }) => changeManagementSummaryItem(record, targets, document))
    return deps.json(response, 200, {
      items,
      overview: overviewRows.slice(0, 100),
      overview_truncated: overviewRows.length > 100,
      page: { next_cursor: page.next_cursor, limit: page.limit },
    })
  }

  if (request.method === 'GET' && changeRequestMatch) {
    const crId = decodeURIComponent(changeRequestMatch[1])
    const cr = changeHistoryCr(projection.core.value, crId)
    if (!cr || !changeManagementRecordTargets(cr, currentTableAuthority.targetsById)) {
      throw deps.accessError(404, 'CHANGE_REQUEST_NOT_FOUND', 'The change request was not found.')
    }
    return deps.json(response, 200, cr, { 'Cache-Control': 'private, no-store' })
  }

  if (request.method === 'GET' && url.pathname === '/api/v1/change-history/events') {
    const bounds = changeHistoryDateBounds(url.searchParams)
    const changeType = changeHistoryFilterValue(url.searchParams, 'change_type', 32)
    const category = changeHistoryFilterValue(url.searchParams, 'category', 32)
    const precision = changeHistoryFilterValue(url.searchParams, 'precision', 32)
    const operation = changeHistoryFilterValue(url.searchParams, 'operation', 32)
    const platform = changeHistoryFilterValue(url.searchParams, 'platform', 100)?.toLowerCase() ?? null
    const databaseName = changeHistoryFilterValue(url.searchParams, 'database_name')
    const schemaName = changeHistoryFilterValue(url.searchParams, 'schema_name')
    const systemId = changeHistoryFilterValue(url.searchParams, 'system_id')
    const systemResolution = changeHistoryFilterValue(url.searchParams, 'system_resolution', 32)
    const assigneeId = changeHistoryFilterValue(url.searchParams, 'assignee_subject_id')
    const linkState = changeHistoryFilterValue(url.searchParams, 'link_state', 32)
    const stage = changeHistoryFilterValue(url.searchParams, 'stage', 32)
    if ((changeType && !['SCHEMA_CHANGE', 'METADATA_CHANGE'].includes(changeType))
      || (category && !deps.changeHistoryCategories.has(category))
      || (precision && !deps.changeHistoryPrecisionValues.includes(precision))
      || (operation && !deps.changeHistoryOperations.has(operation))
      || (systemResolution && !['RESOLVED', 'UNMAPPED', 'AMBIGUOUS'].includes(systemResolution))
      || (linkState && !['LINKED', 'UNLINKED'].includes(linkState))
      || (stage && !deps.changeHistoryPresentationStages.has(stage))) {
      throw deps.accessError(400, 'FILTER_INVALID', 'A change-history filter is invalid.')
    }
    const filtered = rows.filter((row) => changeHistoryInBounds(row, bounds)
      && (!changeType || (changeType === 'SCHEMA_CHANGE') === (row.event.category === 'TECHNICAL_SCHEMA' && row.event.source_aspect === 'schemaMetadata'))
      && (!category || row.event.category === category)
      && (!precision || row.precision === precision)
      && (!operation || row.event.operation === operation)
      && (!platform || row.locator?.platform === platform)
      && (!databaseName || row.locator?.database_name === databaseName)
      && (!schemaName || row.locator?.schema_name === schemaName)
      && (!systemId || row.system.system_id === systemId)
      && (!systemResolution || row.system.resolution === systemResolution)
      && (!assigneeId || row.assignee.subject_id === assigneeId)
      && (!linkState || (linkState === 'LINKED') === Boolean(row.current.primary))
      && (!stage || row.current_stage === stage))
    const page = changeHistoryPage(filtered, url.searchParams, (row) => [String(row.event.source_occurred_at || row.event.detected_at), row.event.event_identity])
    const eventAssetIds = new Set(projection.events.map((event) => event.asset_urn))
    const activeSystemIds = new Set(document.systems
      .filter((system) => system.active)
      .map((system) => system.system_id))
    const activeEventExactMappings = mappingDocument.bindings.filter((binding) => (
      binding.active
      && eventAssetIds.has(binding.table_identity)
      && activeSystemIds.has(binding.system_id)
    )).length
    const emptyStateReason = filtered.length ? null
      : projection.events.length === 0 ? 'NO_LEDGER_EVENTS'
      : rows.length === 0 ? 'EVENTS_EXIST_BUT_NOT_AUTHORIZED'
      : 'FILTER_DATE_RANGE_EMPTY'
    return deps.json(response, 200, {
      items: page.items.map((row) => changeHistoryPublicRow(row)),
      next_cursor: page.next_cursor,
      limit: page.limit,
      total: filtered.length,
      empty_state_reason: emptyStateReason,
      empty_state_detail: emptyStateReason === 'EVENTS_EXIST_BUT_NOT_AUTHORIZED'
        ? activeEventExactMappings === 0 ? 'NO_EXACT_MAPPING' : 'AUTHORIZATION_SCOPE'
        : null,
    })
  }
  if (request.method === 'GET' && eventMatch) {
    const row = rows.find((item) => item.event.event_identity === eventMatch[1])
    if (!row) throw deps.accessError(404, 'CHANGE_HISTORY_EVENT_NOT_FOUND', 'The change-history event was not found.')
    return deps.json(response, 200, changeHistoryPublicRow(row, true), { ETag: row.current.etag })
  }
  if (request.method === 'GET' && eventLinksMatch) {
    const row = rows.find((item) => item.event.event_identity === eventLinksMatch[1])
    if (!row) throw deps.accessError(404, 'CHANGE_HISTORY_EVENT_NOT_FOUND', 'The change-history event was not found.')
    const history = row.links.filter((link) => changeHistoryCanDisplayLink(
      link,
      projection.core.value,
      currentTableAuthority.targetsById,
    )).sort((left, right) => Number(right.link_version) - Number(left.link_version))
    const page = changeHistoryPage(history, url.searchParams, (link) => [String(link.occurred_at), String(link.link_event_identity)])
    return deps.json(response, 200, {
      current_primary: row.current.primary,
      current_candidates: row.current.candidates,
      items: page.items.map(changeHistoryPublicLinkEvent),
      next_cursor: page.next_cursor,
      limit: page.limit,
    }, { ETag: row.current.etag })
  }
  if (request.method === 'POST' && eventCommandMatch) {
    const row = rows.find((item) => item.event.event_identity === eventCommandMatch[1])
    if (!row) throw deps.accessError(404, 'CHANGE_HISTORY_EVENT_NOT_FOUND', 'The change-history event was not found.')
    if (row.system.resolution !== 'RESOLVED') throw deps.accessError(409, 'SYSTEM_MAPPING_UNRESOLVED', 'The event does not resolve to exactly one active business System.')
    const { idempotencyKey, priorLinkHash } = changeHistoryMutationHeaders(request)
    const command = changeHistoryCommandBody(await deps.bodyJson(request))
    const cr = changeHistoryCr(projection.core.value, command.changeRequestId)
    assertChangeHistoryCrBinding(cr, command.changeRequestRound, row.system.system_id, currentTableAuthority.targetsById)
    const replay = await context.stateStore.readChangeHistoryCrLinkReplay?.({
      idempotencyKey, ledgerEventIdentity: row.event.event_identity, linkKind: command.linkKind,
      action: command.action, changeRequestId: command.changeRequestId,
      changeRequestRound: command.changeRequestRound, reason: command.reason,
    })
    if (replay) {
      return deps.json(response, 200, {
        link_event_identity: replay.linkEventIdentity, event_hash: replay.eventHash,
        link_version: replay.linkVersion, replayed: true,
        event_id: row.event.event_identity, change_request_id: command.changeRequestId,
        change_request_round: command.changeRequestRound, action: command.action,
      }, { ETag: `"${replay.eventHash}"` })
    }
    if (priorLinkHash !== (row.current.etag === '"0"' ? null : row.current.etag.slice(1, -1))) {
      throw deps.accessError(409, 'LINK_VERSION_STALE', 'The link version is stale.')
    }
    if (command.action === 'CLEAR_PRIMARY' && row.current.primary?.change_request_id !== command.changeRequestId) {
      throw deps.accessError(409, 'LINK_STATE_CONFLICT', 'The requested primary link is not current.')
    }
    const candidateIds = new Set(row.current.candidates.map((item) => item.change_request_id))
    if ((command.action === 'ADD_CANDIDATE' && candidateIds.has(command.changeRequestId))
      || (command.action === 'REMOVE_CANDIDATE' && !candidateIds.has(command.changeRequestId))) {
      throw deps.accessError(409, 'LINK_STATE_CONFLICT', 'The requested candidate link state is already current.')
    }
    const policyHash = deps.canonicalHash(document)
    const basis = {
      subject_id: context.principal.subjectId,
      role: context.principal.role,
      system: row.system,
      assignee: row.assignee,
      access_version: projection.access.version,
      core_version: projection.core.version,
    }
    const result = await context.stateStore.appendChangeHistoryCrLink({
      ledgerEventIdentity: row.event.event_identity,
      linkKind: command.linkKind,
      action: command.action,
      changeRequestId: command.changeRequestId,
      changeRequestRound: command.changeRequestRound,
      priorLinkHash,
      reason: command.reason,
      policyHash,
      basisHash: deps.canonicalHash(basis),
      actorRef: context.principal.subjectId,
      occurredAt: new Date().toISOString(),
      idempotencyKey,
      expectedAccessVersion: projection.access.version,
      expectedCoreVersion: projection.core.version,
      expectedCoreHash: deps.canonicalHash(projection.core.value),
      expectedCatalogScope: deps.datahubInventoryStateScope,
      expectedCatalogVersion: projection.catalog.version,
      expectedCatalogHash: deps.canonicalHash(projection.catalog.value),
    })
    return deps.json(response, result.replayed ? 200 : 201, {
      link_event_identity: result.linkEventIdentity, event_hash: result.eventHash,
      link_version: result.linkVersion, replayed: result.replayed,
      event_id: row.event.event_identity, change_request_id: command.changeRequestId,
      change_request_round: command.changeRequestRound, action: command.action,
    }, { ETag: `"${result.eventHash}"` })
  }
  if (request.method === 'GET' && reverseMatch) {
    const crId = decodeURIComponent(reverseMatch[1])
    const cr = changeHistoryCr(projection.core.value, crId)
    if (!cr || !changeManagementRecordTargets(cr, currentTableAuthority.targetsById)) {
      throw deps.accessError(404, 'CHANGE_REQUEST_NOT_FOUND', 'The change request was not found.')
    }
    const linked = rows.filter((row) => row.links.some((link) => link.change_request_id === crId))
    const page = changeHistoryPage(linked, url.searchParams, (row) => [String(row.event.source_occurred_at || row.event.detected_at), row.event.event_identity])
    return deps.json(response, 200, { change_request_id: crId, items: page.items.map((row) => changeHistoryPublicRow(row)), next_cursor: page.next_cursor, limit: page.limit })
  }
  if (request.method === 'GET' && url.pathname === '/api/v1/change-history/weekly') {
    const weekStart = url.searchParams.get('week_start')
    const { inWeek: _inWeek, transactions: _transactions, ...summary } = changeHistoryWeeklySummary(
      rows,
      projection.core.value,
      document,
      weekStart,
    )
    void _inWeek
    void _transactions
    return deps.json(response, 200, summary)
  }
  if (request.method === 'GET' && url.pathname === '/api/v1/change-history/summary') {
    return deps.json(response, 200, changeHistorySummary(
      projection,
      rows,
      projection.core.value,
      document,
      url.searchParams.get('week_start'),
    ))
  }
  return deps.problem(response, 405, 'METHOD_NOT_ALLOWED', 'The change-history route does not support this method.')
}

return { changeHistoryAccess, changeHistoryActiveUser, changeHistoryAssignee, changeHistoryLinkState, changeHistoryPrecision, changeHistoryLinkedCr, changeHistoryAuthorizedCurrent, changeHistoryRow, changeHistoryCrPresentationStage, changeHistoryRowPresentationStage, changeHistoryAllowedLinkActions, changeHistoryPresentationRecord, changeHistoryPresentationValue, changeHistoryPresentation, changeHistoryPublicRow, changeHistoryPublicLinkEvent, changeHistoryCanDisplayLink, changeHistoryPageParameters, changeHistoryPage, changeHistoryProjectionAuthority, changeHistoryCr, assertChangeHistoryCrBinding, changeHistoryMutationHeaders, changeHistoryCommandBody, changeHistoryWeekBounds, changeHistoryKstDate, changeHistoryDateBounds, changeHistoryInBounds, changeHistoryTransactionStage, changeManagementSchemaKey, changeHistoryCurrentTableAuthority, changeManagementBaseOverview, changeManagementEventOverview, changeManagementCrCreatedInBounds, changeManagementRecordTargets, changeManagementAddCrCounts, changeManagementPriorityOneAssignees, changeManagementSummaryItem, changeManagementOverviewRows, changeHistoryWeeklySummary, changeHistoryFilterValue, changeHistoryMaximumTimestamp, changeHistoryMinimumTimestamp, changeHistorySourceSummary, changeHistorySummary, changeHistoryApi }
}
