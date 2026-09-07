/* global AbortController, Buffer, DOMException */
// Dependencies are supplied by bootstrap; this module never constructs a shared client.
export function createInterfacesHttpRouter(deps) {
async function api(request, response, url, context) {
  if (url.pathname === '/api/v1/site-branding') {
    return deps.siteBrandingApi(request, response, context)
  }
  if (url.pathname === '/api/v1/admin/users' || /^\/api\/v1\/admin\/users\//.test(url.pathname)) {
    return deps.adminUsersApi(request, response, url, context)
  }
  if (url.pathname === '/api/v1/admin/table-system-mappings') {
    return deps.tableSystemMappingApi(request, response, url, context)
  }
  if (url.pathname === '/api/v1/admin/systems') {
    return deps.adminSystemsApi(request, response, context)
  }
  if (url.pathname === '/api/v1/admin/feature-security-policy') {
    return deps.featureSecurityPolicyApi(request, response, context)
  }
  if (url.pathname === '/api/v1/change-history/access') {
    return deps.changeHistoryAccess(request, response, url, context)
  }
  if (url.pathname === '/api/v1/change-history/events'
    || url.pathname === '/api/v1/change-history/summary'
    || url.pathname === '/api/v1/change-history/weekly'
    || url.pathname === '/api/v1/change-requests/summaries'
    || /^\/api\/v1\/change-history\/events\//.test(url.pathname)
    || /^\/api\/v1\/change-requests\/[^/]+$/.test(url.pathname)
    || /^\/api\/v1\/change-requests\/[^/]+\/change-history$/.test(url.pathname)) {
    return deps.changeHistoryApi(request, response, url, context)
  }
  if (request.method === 'POST' && url.pathname === '/api/v1/registration/bulk-preparations/execute') {
    return deps.json(response, 200, await deps.executeBulkPreparation())
  }
  if (request.method === 'POST' && /^\/poc-api\/bulk\/uploads\/[a-zA-Z0-9_-]+\/preparations\/[^/]+\/metadata-candidates\/[^/]+\/change-request$/.test(url.pathname)) {
    return deps.bulkCandidateChangeRequestApi(request, response, url, context)
  }
  if (request.method === 'POST' && url.pathname === '/poc-api/change-requests') {
    return deps.crCreateApi(request, response, url, context)
  }
  if (/^\/poc-api\/change-requests\/[^/]+\/apply-report$/.test(url.pathname)) {
    return deps.applyReportApi(request, response, url, context)
  }
  if (/^\/poc-api\/change-requests\/[^/]+$/.test(url.pathname)
    || /^\/poc-api\/change-requests\/[^/]+\/commands$/.test(url.pathname)) {
    return deps.crCommandApi(request, response, url, context)
  }
  const stateMatch = url.pathname.match(/^\/poc-api\/state\/([a-z]+)$/)
  if (stateMatch && deps.allowedPocStateScopes.has(stateMatch[1])) {
    const scope = stateMatch[1]
    if (request.method === 'GET') {
      if (scope !== 'core' && !context.principal.capabilitySet.has('knowledge.read')) {
        throw deps.accessError(403, 'CAPABILITY_REQUIRED', 'knowledge.read is required.')
      }
      const snapshot = await context.stateStore.read(scope)
      return deps.json(response, 200, {
        ...snapshot,
        value: scope === 'core' ? deps.filterCoreStateForPrincipal(context.principal, snapshot.value) : snapshot.value,
      }, { ETag: `"${snapshot.version}"` })
    }
    if (request.method === 'PUT') {
      const body = await deps.bodyJson(request)
      if (!Object.hasOwn(body, 'value')) return deps.problem(response, 400, 'STATE_VALUE_REQUIRED', 'A state value is required.')
      if (scope === 'core') {
        const expectedVersion = deps.stateIfMatch(request)
        const current = await context.stateStore.read(scope)
        if (current.version !== expectedVersion) throw deps.accessError(409, 'STATE_VERSION_STALE', 'The core state version is stale.')
        const authorized = deps.authorizeCoreReplacement(context.principal, current.value, body.value)
        const version = await context.stateStore.writeIfVersion(scope, authorized.value, expectedVersion)
        return deps.json(response, 200, { version }, { ETag: `"${version}"` })
      }
      if (!context.principal.capabilitySet.has('knowledge.manage')) {
        throw deps.accessError(403, 'CAPABILITY_REQUIRED', 'knowledge.manage is required.')
      }
      return deps.json(response, 200, { version: await context.stateStore.write(scope, body.value) })
    }
    return deps.problem(response, 405, 'METHOD_NOT_ALLOWED', 'POC state supports only GET and PUT.')
  }
  if (request.method === 'GET' && url.pathname === '/poc-api/capabilities') return deps.json(response, 200, await deps.capabilities())
  if (request.method === 'GET' && url.pathname === '/poc-api/knowledge/catalog') {
    return deps.json(response, 200, await deps.knowledgeCatalogSearch(url.searchParams, context.principal))
  }
  if (request.method === 'GET' && url.pathname === '/poc-api/knowledge/catalog/asset') {
    return deps.json(response, 200, await deps.knowledgeCatalogDetail(url.searchParams, context.principal))
  }
  if (request.method === 'GET' && url.pathname === '/poc-api/datahub/catalog') return deps.json(response, 200, await deps.datahubCatalog(url.searchParams, context.principal))
  if (request.method === 'GET' && url.pathname === '/poc-api/datahub/catalog/export-capability') {
    return deps.json(response, 200, { enabled: true, maximum_rows: deps.POC_CATALOG_EXPORT_MAXIMUM_ROWS })
  }
  if (request.method === 'POST' && url.pathname === '/poc-api/datahub/catalog/exports') {
    return deps.json(response, 201, await deps.createCatalogExport(request, context))
  }
  const catalogExportFileMatch = url.pathname.match(/^\/poc-api\/datahub\/catalog\/exports\/([^/]+)\/file$/)
  if (request.method === 'GET' && catalogExportFileMatch) {
    const artifact = context.catalogExportStore.file(context.principal.subjectId, decodeURIComponent(catalogExportFileMatch[1]))
    response.writeHead(200, {
      ...deps.securityHeaders(),
      'Cache-Control': 'no-store',
      'Content-Type': artifact.format === 'XLSX'
        ? 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        : 'text/csv; charset=utf-8',
      'Content-Length': artifact.bytes.length,
      'Content-Disposition': `attachment; filename="${artifact.displayName}"; filename*=UTF-8''${encodeURIComponent(artifact.displayName)}`,
      ETag: `"${artifact.contentSha256}"`,
    })
    return response.end(artifact.bytes)
  }
  const catalogExportDownloadMatch = url.pathname.match(/^\/poc-api\/datahub\/catalog\/exports\/([^/]+)\/download$/)
  if (request.method === 'POST' && catalogExportDownloadMatch) {
    return deps.json(response, 200, context.catalogExportStore.download(
      context.principal.subjectId,
      decodeURIComponent(catalogExportDownloadMatch[1]),
    ))
  }
  const catalogExportStatusMatch = url.pathname.match(/^\/poc-api\/datahub\/catalog\/exports\/([^/]+)$/)
  if (request.method === 'GET' && catalogExportStatusMatch) {
    return deps.json(response, 200, context.catalogExportStore.status(
      context.principal.subjectId,
      decodeURIComponent(catalogExportStatusMatch[1]),
    ))
  }
  if (request.method === 'GET' && url.pathname === '/poc-api/datahub/catalog/locate') return deps.json(response, 200, await deps.datahubCatalogLocate(url.searchParams, context.principal))
  if (request.method === 'GET' && url.pathname === '/poc-api/datahub/tree') return deps.json(response, 200, await deps.datahubTree(url.searchParams, context.principal))
  if (request.method === 'GET' && url.pathname === '/poc-api/datahub/facets') return deps.json(response, 200, await deps.datahubFacets(url.searchParams, context.principal))
  if (request.method === 'GET' && url.pathname === '/poc-api/datahub/dashboard') return deps.json(response, 200, await deps.datahubDashboard(context.principal))
  if (request.method === 'GET' && url.pathname === '/poc-api/datahub/profile-coverage') return deps.json(response, 200, await deps.datahubProfileCoverage(context.principal))
  if (request.method === 'GET' && url.pathname === '/poc-api/datahub/vector-index') return deps.json(response, 200, deps.catalogEmbeddingStatus(context.principal))
  if (request.method === 'GET' && url.pathname === '/poc-api/datahub/systems') return deps.json(response, 200, await deps.datahubSystems(context.principal))
  if (request.method === 'GET' && url.pathname === '/poc-api/datahub/glossary') return deps.json(response, 200, await deps.datahubGlossary(url.searchParams, context.principal))
  if (request.method === 'GET' && url.pathname === '/poc-api/datahub/glossary/smoke-target') return deps.json(response, 200, await deps.datahubGlossarySmokeTarget(url.searchParams))
  if (request.method === 'GET' && url.pathname === '/poc-api/datahub/glossary/assignments') return deps.json(response, 200, await deps.datahubGlossaryAssignments(url.searchParams, context.principal))
  if (request.method === 'POST' && url.pathname === '/poc-api/datahub/glossary/assignments/batch-counts') {
    return deps.json(response, 200, await deps.datahubGlossaryAssignmentBatchCounts(await deps.bodyJson(request), context.principal))
  }
  if (request.method === 'GET' && url.pathname === '/poc-api/chat/sessions') {
    const rawLimit = url.searchParams.get('limit') ?? '50'
    if (!/^\d+$/.test(rawLimit) || Number(rawLimit) < 1 || Number(rawLimit) > 100) {
      return deps.problem(response, 400, 'CHAT_PAGE_INVALID', 'Chat session limit must be between 1 and 100.')
    }
    return deps.json(response, 200, await context.stateStore.listChatSessions(context.principal.subjectId, Number(rawLimit)))
  }
  const chatMessagesMatch = url.pathname.match(/^\/poc-api\/chat\/sessions\/([^/]+)\/messages$/)
  if (request.method === 'GET' && chatMessagesMatch) {
    const sessionId = decodeURIComponent(chatMessagesMatch[1])
    if (url.searchParams.has('discovery_message_id') || url.searchParams.has('cursor')) {
      if ([...url.searchParams.keys()].some((key) => !['discovery_message_id', 'cursor'].includes(key))) {
        return deps.problem(response, 400, 'CHAT_DISCOVERY_PAGE_INVALID', 'Chat discovery pagination accepts only its message and server cursor.')
      }
      const messageId = deps.boundedString(url.searchParams.get('discovery_message_id'), 200).trim()
      const cursor = url.searchParams.get('cursor')
      const messages = await context.stateStore.listChatMessages(
        context.principal.subjectId, sessionId, 500,
      )
      const message = messages.find((item) => item.id === messageId
        && item.role === 'assistant' && item.discovery_json)
      if (!message) {
        throw deps.accessError(404, 'CHAT_DISCOVERY_NOT_FOUND', 'The Chat discovery result was not found.')
      }
      return deps.json(response, 200, await deps.currentChatDiscovery(
        message.discovery_json, context.principal, cursor,
      ))
    }
    if ([...url.searchParams.keys()].some((key) => key !== 'limit')) {
      return deps.problem(response, 400, 'CHAT_PAGE_INVALID', 'Chat history accepts only a numeric limit.')
    }
    const rawLimit = url.searchParams.get('limit') ?? '200'
    if (!/^\d+$/.test(rawLimit) || Number(rawLimit) < 1 || Number(rawLimit) > 500) {
      return deps.problem(response, 400, 'CHAT_PAGE_INVALID', 'Chat message limit must be between 1 and 500.')
    }
    return deps.json(response, 200, await deps.currentChatHistoryMessages(
      context, sessionId, Number(rawLimit),
    ))
  }
  const chatFavoriteMatch = url.pathname.match(/^\/poc-api\/chat\/sessions\/([^/]+)\/favorite$/)
  if (request.method === 'PATCH' && chatFavoriteMatch) {
    const body = await deps.bodyJson(request)
    return deps.json(response, 200, await context.stateStore.setChatSessionFavorite(
      context.principal.subjectId,
      decodeURIComponent(chatFavoriteMatch[1]),
      body.is_favorite,
      body.expected_version,
    ))
  }
  const chatSessionMatch = url.pathname.match(/^\/poc-api\/chat\/sessions\/([^/]+)$/)
  if (request.method === 'DELETE' && chatSessionMatch) {
    const expectedVersion = Number(url.searchParams.get('expected_version'))
    await context.stateStore.archiveChatSession(
      context.principal.subjectId, decodeURIComponent(chatSessionMatch[1]), expectedVersion,
    )
    return deps.json(response, 200, {})
  }
  if (request.method === 'GET' && url.pathname === '/poc-api/datahub/asset') {
    const urn = deps.boundedString(url.searchParams.get('urn'), 4096)
    const detailScope = (url.searchParams.get('detail_scope') || 'FULL').trim().toUpperCase()
    if (detailScope === 'BASE') {
      return deps.json(response, 200, await deps.datahubCatalogDetailBase(urn, context.principal))
    }
    if (detailScope === 'SCHEMA') {
      return deps.json(response, 200, await deps.datahubCatalogDetailSchema(
        urn,
        context.principal,
        Number(url.searchParams.get('field_offset') || 0),
        Number(url.searchParams.get('field_limit') || 100),
        deps.boundedString(url.searchParams.get('field_source_version'), 200).trim(),
      ))
    }
    if (detailScope === 'QUALITY') {
      return deps.json(response, 200, await deps.datahubCatalogDetailQuality(
        urn,
        context.principal,
        deps.boundedString(url.searchParams.get('source_version'), 200).trim(),
      ))
    }
    if (detailScope !== 'FULL') {
      throw deps.accessError(400, 'CATALOG_DETAIL_SCOPE_INVALID', 'Catalog detail_scope must be BASE, SCHEMA, QUALITY, or FULL.')
    }
    const asset = await deps.datahubAsset(
      urn,
      Number(url.searchParams.get('field_offset') || 0),
      Number(url.searchParams.get('field_limit') || 100),
    )
    if (!deps.canReadAsset(context.principal, asset, 'catalog')) {
      throw deps.accessError(404, 'CATALOG_ASSET_NOT_FOUND', 'The DataHub asset was not found in the current Table scope.')
    }
    return deps.json(response, 200, asset)
  }
  if (request.method === 'GET' && url.pathname === '/poc-api/datahub/lineage') {
    const projection = deps.datahubLineageProjectionOptions(url.searchParams)
    return deps.json(response, 200, await deps.datahubLineage(
      deps.boundedString(url.searchParams.get('urn'), 4096), context.principal, projection,
    ))
  }
  if (request.method === 'POST' && url.pathname === '/poc-api/datahub/manual-metadata') {
    const body = await deps.bodyJson(request)
    const target = await deps.datahubAssetAll(deps.boundedString(body.asset_id, 4096))
    let currentTargets
    try {
      currentTargets = await context.currentDatahubTables([target.id || target.urn])
    } catch {
      throw deps.accessError(503, 'REGISTRATION_CURRENT_TABLES_UNAVAILABLE', 'Current DataHub Table confirmation is unavailable.')
    }
    const currentTarget = currentTargets.find((asset) => asset.id === (target.id || target.urn))
    const authorizedTarget = currentTarget
      ? { ...target, ...currentTarget }
      : { ...target, dataset_kind: undefined, security_grade: undefined }
    let mappedSystemIds = new Set()
    if (context.principal.role !== 'admin') {
      const mappingSnapshot = await context.stateStore.read(deps.POC_TABLE_SYSTEM_MAPPING_SCOPE)
      const activeSystemIds = new Set((context.accessDocument.systems ?? [])
        .filter((system) => system.active)
        .map((system) => system.system_id))
      mappedSystemIds = new Set(deps.activeSystemIdsForTable(
        mappingSnapshot.value,
        target.id || target.urn,
        activeSystemIds,
      ))
    }
    deps.assertRegistrationAssetMutation(context.principal, authorizedTarget, mappedSystemIds)
    return deps.json(response, 200, await deps.applyManualMetadata(body))
  }
  if (request.method === 'GET' && url.pathname === '/poc-api/templates/catalog-metadata.xlsx') {
    if (!deps.existsSync(deps.bulkTemplatePath)) return deps.problem(response, 404, 'TEMPLATE_NOT_FOUND', 'The bulk metadata template is missing.')
    const size = deps.statSync(deps.bulkTemplatePath).size
    response.writeHead(200, {
      ...deps.securityHeaders(),
      'Cache-Control': 'no-store',
      'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      'Content-Length': size,
      'Content-Disposition': 'attachment; filename="datariver-catalog-metadata-rows.xlsx"',
      ETag: `"${deps.sha256(deps.readFileSync(deps.bulkTemplatePath))}"`,
    })
    return deps.createReadStream(deps.bulkTemplatePath).pipe(response)
  }
  if (request.method === 'GET' && url.pathname === '/poc-api/templates/catalog-metadata.csv') {
    const content = Buffer.from(`${deps.catalogMetadataHeaders.join(',')}\n`, 'utf8')
    response.writeHead(200, {
      ...deps.securityHeaders(),
      'Cache-Control': 'no-store',
      'Content-Type': 'text/csv; charset=utf-8',
      'Content-Length': content.length,
      'Content-Disposition': 'attachment; filename="datariver-catalog-metadata-rows.csv"',
      ETag: `"${deps.sha256(content)}"`,
    })
    return response.end(content)
  }
  if (request.method === 'POST' && url.pathname === '/poc-api/bulk/preparations') {
    if (!deps.minio || !deps.datahub || !deps.airflow) {
      return deps.problem(response, 503, 'BULK_PROVIDER_NOT_CONFIGURED', 'Bulk preparation requires DataHub, MinIO and Airflow.')
    }
    const body = await deps.bodyJson(request)
    const uploadId = deps.boundedString(body.upload_id, 100).trim()
    const profile = deps.boundedString(body.content_profile, 100).trim()
    const sourceHash = deps.boundedString(body.source_sha256, 64).trim()
    const objectKey = deps.boundedString(body.object_key, 1_000).trim()
    if (!/^[a-zA-Z0-9_-]{1,100}$/.test(uploadId)
      || !['CATALOG_METADATA_ROWS_CSV_V1', 'CATALOG_METADATA_ROWS_XLSX_V1'].includes(profile)
      || !/^[0-9a-f]{64}$/.test(sourceHash)
      || !new RegExp(`^bulk-registration/${uploadId}/catalog-metadata-source\\.(csv|xlsx)$`).test(objectKey)) {
      return deps.problem(response, 400, 'BULK_PREPARATION_INVALID', 'The bulk preparation receipt is invalid.')
    }
    const existing = deps.bulkPreparations.get(uploadId)
    if (existing) {
      if (!deps.canReadBulkPreparation(context.principal, existing)) {
        return deps.problem(response, 404, 'BULK_PREPARATION_NOT_FOUND', 'The bulk preparation was not found.')
      }
      const visibleCandidates = existing.preparation.state === 'READY'
        ? await deps.visibleRegistrationCandidates(existing, context)
        : []
      return deps.json(response, 200, deps.bulkPreparationProjection(existing.preparation, visibleCandidates.length))
    }
    const now = new Date().toISOString()
    const preparation = {
      id: deps.randomUUID(), upload_id: uploadId, content_profile: profile,
      source_manifest_version: 1, source_sha256: sourceHash,
      configuration_hash: deps.canonicalHash(deps.catalogMetadataHeaders), state: 'QUEUED', attempts: 0,
      rows_processed: 0, total_rows: null, last_error_code: null,
      created_at: now, updated_at: now, version: 1,
    }
    deps.bulkPreparations.set(uploadId, {
      preparation,
      creatorSubjectId: context.principal.subjectId,
      objectKey,
      candidates: [],
      receipt: null,
    })
    const run = await deps.triggerAirflowDag(deps.bulkRegistrationDagId, {
      dag_run_id: `poc-bulk-${uploadId}-${Date.now()}`,
      conf: { poc: true, upload_id: uploadId },
    })
    return deps.json(response, 202, { ...deps.bulkPreparationProjection(preparation), airflow: await run.json() })
  }
  const bulkList = url.pathname.match(/^\/poc-api\/bulk\/uploads\/([a-zA-Z0-9_-]+)\/preparations$/)
  if (request.method === 'GET' && bulkList) {
    const entry = deps.bulkPreparations.get(bulkList[1])
    if (entry && !deps.canReadBulkPreparation(context.principal, entry)) {
      return deps.problem(response, 404, 'BULK_PREPARATION_NOT_FOUND', 'The bulk preparation was not found.')
    }
    const visibleCandidates = entry?.preparation.state === 'READY'
      ? await deps.visibleRegistrationCandidates(entry, context)
      : []
    return deps.json(response, 200, {
      items: entry ? [deps.bulkPreparationProjection(entry.preparation, visibleCandidates.length)] : [],
    })
  }
  const bulkCandidates = url.pathname.match(/^\/poc-api\/bulk\/uploads\/([a-zA-Z0-9_-]+)\/preparations\/([^/]+)\/metadata-candidates$/)
  if (request.method === 'GET' && bulkCandidates) {
    const entry = deps.bulkPreparations.get(bulkCandidates[1])
    if (!entry || entry.preparation.id !== bulkCandidates[2]
      || entry.preparation.state !== 'READY' || !entry.receipt
      || !deps.canReadBulkPreparation(context.principal, entry)) {
      return deps.problem(response, 404, 'BULK_CANDIDATES_NOT_READY', 'Bulk candidates are not ready.')
    }
    const requested = Number(url.searchParams.get('limit') || 20)
    const limit = Math.min(50, Math.max(1, Number.isInteger(requested) ? requested : 20))
    const offset = Math.max(0, Number(url.searchParams.get('cursor') || 0))
    const visibleCandidates = await deps.visibleRegistrationCandidates(entry, context)
    const items = visibleCandidates.slice(offset, offset + limit)
      .map((candidate) => Object.fromEntries(Object.entries(candidate).filter(([key]) => key !== 'row')))
    const rootHash = deps.canonicalHash(visibleCandidates.map((item) => item.candidate_hash))
    const receipt = {
      ...entry.receipt,
      item_count: visibleCandidates.length,
      candidate_count: visibleCandidates.length,
      candidate_root_hash: rootHash,
      receipt_hash: deps.canonicalHash([entry.preparation.id, rootHash]),
    }
    return deps.json(response, 200, {
      items,
      page: { limit, ...(offset + items.length < visibleCandidates.length ? { next_cursor: String(offset + items.length) } : {}) },
      receipt,
      meta: { projection_version: 1, policy_version: 'POC_LIVE_PROVIDER_V1', classification_policy_version: 1, authorization_generation: 1 },
    })
  }
  const bulkPreview = url.pathname.match(/^\/poc-api\/bulk\/uploads\/([a-zA-Z0-9_-]+)\/preparations\/([^/]+)\/metadata-candidates\/([^/]+)\/preview$/)
  if (request.method === 'GET' && bulkPreview) {
    const entry = deps.bulkPreparations.get(bulkPreview[1])
    const candidate = entry?.candidates.find((item) => item.id === bulkPreview[3])
    if (!entry || entry.preparation.id !== bulkPreview[2] || !candidate
      || !deps.canReadBulkPreparation(context.principal, entry)) {
      return deps.problem(response, 404, 'BULK_CANDIDATE_NOT_FOUND', 'The bulk candidate was not found.')
    }
    const visibleCandidates = await deps.visibleRegistrationCandidates(entry, context, [candidate])
    if (visibleCandidates.length !== 1) {
      return deps.problem(response, 404, 'BULK_CANDIDATE_NOT_FOUND', 'The bulk candidate was not found.')
    }
    return deps.json(response, 200, await deps.bulkCandidatePreview(entry, visibleCandidates[0]))
  }
  if (request.method === 'POST' && url.pathname === '/poc-api/llm/chat') {
    const body = await deps.bodyJson(request)
    if (typeof body.question !== 'string' || body.question.length > deps.maximumChatQuestionCharacters) {
      return deps.problem(response, 400, 'QUESTION_INVALID', `Question must be a string of at most ${deps.maximumChatQuestionCharacters} characters.`)
    }
    const question = body.question
    const mode = ['AUTO', 'GENERAL', 'VECTOR', 'GRAPH'].includes(body.mode) ? body.mode : 'AUTO'
    const memory = deps.chatMemoryPayload(body.memory)
    if (!question.trim()) return deps.problem(response, 400, 'QUESTION_REQUIRED', 'A non-empty question is required.')
    const result = await deps.liveChat(question, mode, undefined, memory, context)
    return deps.json(response, 200, {
      ...result,
      discovery: deps.publicChatDiscovery(result.discovery),
    })
  }
  if (request.method === 'POST' && url.pathname === '/poc-api/llm/chat/compact') {
    const body = await deps.bodyJson(request)
    const memory = deps.chatMemoryPayload(body.memory)
    if (!memory) return deps.problem(response, 400, 'CHAT_MEMORY_REQUIRED', 'Bounded Chat memory is required.')
    return deps.json(response, 200, await deps.compactChatMemory(memory))
  }
  if (request.method === 'POST' && url.pathname === '/poc-api/llm/chat/stream') {
    const body = await deps.bodyJson(request)
    if (typeof body.question !== 'string' || body.question.length > deps.maximumChatQuestionCharacters) {
      return deps.problem(response, 400, 'QUESTION_INVALID', `Question must be a string of at most ${deps.maximumChatQuestionCharacters} characters.`)
    }
    const question = body.question
    const mode = ['AUTO', 'GENERAL', 'VECTOR', 'GRAPH'].includes(body.mode) ? body.mode : 'AUTO'
    if (body.session_id !== undefined && (
      typeof body.session_id !== 'string' || !body.session_id.trim() || body.session_id.length > 200
    )) {
      return deps.problem(response, 400, 'CHAT_SESSION_INVALID', 'Chat session ID must be a non-empty string of at most 200 characters.')
    }
    const requestedSessionId = deps.boundedString(body.session_id, 200).trim()
    const sessionId = requestedSessionId || deps.randomUUID()
    let memory
    if (requestedSessionId) {
      memory = deps.persistedChatMemory(await context.stateStore.listChatMessages(
        context.principal.subjectId, requestedSessionId, 200,
      ))
    }
    if (!question.trim()) return deps.problem(response, 400, 'QUESTION_REQUIRED', 'A non-empty question is required.')
    response.writeHead(200, {
      'Cache-Control': 'no-cache, no-store',
      Connection: 'keep-alive',
      'Content-Type': 'text/event-stream; charset=utf-8',
      'X-Accel-Buffering': 'no',
      ...deps.securityHeaders(),
    })
    response.flushHeaders?.()
    const controller = new AbortController()
    const abortDownstream = () => controller.abort(new DOMException('The Chat client disconnected.', 'AbortError'))
    request.once('aborted', abortDownstream)
    response.once('close', abortDownstream)
    try {
      const result = await deps.liveChat(
        question, mode, (step) => deps.writeEventStream(response, 'workflow', step), memory, context, controller.signal,
      )
      const evidence = deps.publicChatEvidence(result.evidence)
      await deps.writeApprovedAnswerStream(response, result.answer, controller.signal)
      controller.signal.throwIfAborted()
      deps.writeEventStream(response, 'workflow', {
        stage: 'PERSISTENCE', status: 'IN_PROGRESS', detail_code: 'POSTGRES_ACCOUNT_HISTORY_IN_PROGRESS',
      })
      const createdAt = new Date().toISOString()
      const requestMessageId = deps.randomUUID()
      const responseMessageId = deps.randomUUID()
      const workflow = deps.persistedChatWorkflow(result.workflow)
      const discovery = deps.publicChatDiscovery(result.discovery)
      await context.stateStore.appendChatTurn({
        subjectId: context.principal.subjectId,
        sessionId,
        requestMessageId,
        responseMessageId,
        question: question.trim(),
        answer: result.answer,
        title: question.trim().slice(0, 240),
        evidence,
        discovery,
        route: result.route,
        workflow,
        createdAt,
      })
      controller.signal.throwIfAborted()
      deps.writeEventStream(response, 'workflow', {
        stage: 'PERSISTENCE', status: 'COMPLETED', detail_code: 'POSTGRES_ACCOUNT_HISTORY_PERSISTED',
      })
      deps.writeEventStream(response, 'result', {
        session_id: sessionId,
        request_message_id: requestMessageId,
        response_message_id: responseMessageId,
        answer: result.answer,
        persistence: 'PERSISTED',
        route: result.route,
        workflow,
        evidence,
        discovery,
        performance: result.performance,
      })
    } catch (error) {
      if (!controller.signal.aborted) deps.writeEventStream(response, 'error', {
        detail: error instanceof Error ? error.message : 'Chat provider request failed.',
      })
    }
    return response.end()
  }
  if (request.method === 'GET' && url.pathname === '/poc-api/airflow/operations') {
    if (!context.stateStore.configured?.postgres) {
      throw deps.accessError(503, 'AIRFLOW_RECEIPT_STORE_REQUIRED', 'Durable PostgreSQL Airflow receipts are required.')
    }
    const rawLimit = url.searchParams.get('limit') ?? '50'
    if ([...url.searchParams.keys()].some((key) => key !== 'limit') || !/^\d+$/.test(rawLimit)) {
      return deps.problem(response, 400, 'AIRFLOW_RECEIPT_QUERY_INVALID', 'Airflow receipt query accepts only a numeric limit.')
    }
    const items = await deps.createAirflowControlStore(context.stateStore).listReceipts(Number(rawLimit))
    return deps.json(response, 200, { system_id: deps.AIRFLOW_SYSTEM_ID, items })
  }
  if (request.method === 'GET' && url.pathname === '/poc-api/airflow/dags') {
    if (url.search) return deps.problem(response, 400, 'AIRFLOW_DAG_QUERY_INVALID', 'Airflow DAG inventory does not accept query parameters.')
    const inventory = await context.airflowProvider.inventory()
    if (inventory.system_id !== deps.AIRFLOW_SYSTEM_ID
      || inventory.execution_scope !== deps.AIRFLOW_EXECUTION_SCOPE
      || inventory.items?.some((item) => item.system_id !== deps.AIRFLOW_SYSTEM_ID
        || item.execution_scope !== deps.AIRFLOW_EXECUTION_SCOPE
        || !deps.ALLOWED_AIRFLOW_DAGS.has(item.dag_id))) {
      throw deps.accessError(503, 'AIRFLOW_SYSTEM_IDENTITY_INVALID', 'Airflow inventory has an invalid System or DAG identity.')
    }
    return deps.json(response, 200, inventory)
  }
  const airflowMatch = url.pathname.match(/^\/poc-api\/airflow\/dags\/([^/]+)\/runs$/)
  if (request.method === 'POST' && airflowMatch) {
    const dagId = decodeURIComponent(airflowMatch[1])
    if (!deps.ALLOWED_AIRFLOW_DAGS.has(dagId)) return deps.problem(response, 400, 'DAG_NOT_ALLOWED', 'The DAG is not allowlisted for this Product.')
    if (url.search) return deps.problem(response, 400, 'AIRFLOW_DAG_QUERY_INVALID', 'Airflow DAG triggers do not accept query parameters.')
    if (!context.stateStore.configured?.postgres) {
      throw deps.accessError(503, 'AIRFLOW_RECEIPT_STORE_REQUIRED', 'Durable PostgreSQL Airflow receipts are required before provider contact.')
    }
    const body = await deps.bodyJson(request)
    deps.exactBodyKeys(body, [], [])
    const control = deps.createAirflowControlStore(context.stateStore)
    const claim = await control.claimTrigger({
      subjectId: context.principal.subjectId,
      dagId,
      idempotencyKey: deps.airflowIdempotencyKey(request),
    })
    if (claim.action === 'REPLAY') {
      if (claim.receipt.state === 'FAILED') {
        throw deps.accessError(502, claim.receipt.failure_code, 'The prior Airflow trigger was rejected.')
      }
      return deps.json(response, 200, { replayed: true, receipt: claim.receipt })
    }
    if (claim.action === 'RECONCILE') {
      let run
      try {
        run = await context.airflowProvider.readRun(dagId, claim.receipt.run_id)
      } catch {
        await deps.bestEffortAirflowReceiptWrite(() => control.requireReconciliation(
          claim.receipt.operation_id, 'AIRFLOW_RUN_RECONCILIATION_FAILED',
        ))
        throw deps.accessError(502, 'AIRFLOW_RUN_RECONCILIATION_FAILED', 'The Airflow run could not be reconciled.')
      }
      if (run) {
        try {
          const receipt = await control.acceptTrigger(claim.receipt.operation_id, run.state)
          return deps.json(response, 200, { replayed: true, reconciled: true, run, receipt })
        } catch {
          await deps.bestEffortAirflowReceiptWrite(() => control.requireReconciliation(
            claim.receipt.operation_id, 'AIRFLOW_TRIGGER_OUTCOME_UNKNOWN',
          ))
          throw deps.accessError(502, 'AIRFLOW_TRIGGER_OUTCOME_UNKNOWN', 'The reconciled Airflow run receipt could not be finalized.')
        }
      }
    }
    let run
    try {
      run = await context.airflowProvider.trigger(dagId, claim.receipt.run_id)
    } catch (error) {
      if (deps.isAirflowTriggerOutcomeUnknown(error)) {
        await deps.bestEffortAirflowReceiptWrite(() => control.requireReconciliation(
          claim.receipt.operation_id, 'AIRFLOW_TRIGGER_OUTCOME_UNKNOWN',
        ))
        throw deps.accessError(502, 'AIRFLOW_TRIGGER_OUTCOME_UNKNOWN', 'The Airflow trigger outcome requires reconciliation.')
      }
      await deps.bestEffortAirflowReceiptWrite(() => control.failTrigger(
        claim.receipt.operation_id, 'AIRFLOW_TRIGGER_REJECTED',
      ))
      throw deps.accessError(502, 'AIRFLOW_TRIGGER_REJECTED', 'The Airflow trigger was rejected.')
    }
    let receipt
    try {
      receipt = await control.acceptTrigger(claim.receipt.operation_id, run.state)
    } catch {
      await deps.bestEffortAirflowReceiptWrite(() => control.requireReconciliation(
        claim.receipt.operation_id, 'AIRFLOW_TRIGGER_OUTCOME_UNKNOWN',
      ))
      throw deps.accessError(502, 'AIRFLOW_TRIGGER_OUTCOME_UNKNOWN', 'Airflow accepted the trigger but its receipt could not be finalized.')
    }
    return deps.json(response, claim.action === 'TRIGGER' ? 202 : 200, {
      replayed: claim.action !== 'TRIGGER',
      reconciled: claim.action === 'RECONCILE',
      run,
      receipt,
    })
  }
  const airflowDagMatch = url.pathname.match(/^\/poc-api\/airflow\/dags\/([^/]+)$/)
  if (request.method === 'PATCH' && airflowDagMatch) {
    const dagId = decodeURIComponent(airflowDagMatch[1])
    if (!deps.ALLOWED_AIRFLOW_DAGS.has(dagId)) return deps.problem(response, 400, 'DAG_NOT_ALLOWED', 'The DAG is not allowlisted for this Product.')
    if (url.search) return deps.problem(response, 400, 'AIRFLOW_DAG_QUERY_INVALID', 'Airflow DAG transitions do not accept query parameters.')
    if (!context.stateStore.configured?.postgres) {
      throw deps.accessError(503, 'AIRFLOW_RECEIPT_STORE_REQUIRED', 'Durable PostgreSQL Airflow receipts are required before provider contact.')
    }
    const body = await deps.bodyJson(request)
    deps.exactBodyKeys(body, ['action'])
    if (!['PAUSE', 'UNPAUSE'].includes(body.action)) {
      return deps.problem(response, 400, 'AIRFLOW_PAUSE_ACTION_INVALID', 'Airflow DAG action must be PAUSE or UNPAUSE.')
    }
    const control = deps.createAirflowControlStore(context.stateStore)
    const claim = await control.claimDagTransition({
      subjectId: context.principal.subjectId,
      dagId,
      idempotencyKey: deps.airflowIdempotencyKey(request),
      operation: body.action,
    })
    if (claim.action === 'REPLAY') {
      if (claim.receipt.state === 'FAILED') {
        throw deps.accessError(502, claim.receipt.failure_code, 'The prior Airflow DAG transition was rejected.')
      }
      return deps.json(response, 200, {
        system_id: deps.AIRFLOW_SYSTEM_ID,
        action: body.action,
        replayed: true,
        receipt: claim.receipt,
      })
    }
    let dag
    try {
      dag = await context.airflowProvider.setPaused(dagId, body.action === 'PAUSE')
    } catch (error) {
      if (deps.isAirflowDagTransitionOutcomeUnknown(error)) {
        await deps.bestEffortAirflowReceiptWrite(() => control.requireDagTransitionReconciliation(
          claim.receipt.operation_id, 'AIRFLOW_DAG_TRANSITION_OUTCOME_UNKNOWN',
        ))
        throw deps.accessError(502, 'AIRFLOW_DAG_TRANSITION_OUTCOME_UNKNOWN', 'The Airflow DAG transition requires reconciliation.')
      }
      await deps.bestEffortAirflowReceiptWrite(() => control.failDagTransition(
        claim.receipt.operation_id, 'AIRFLOW_DAG_TRANSITION_REJECTED',
      ))
      throw deps.accessError(502, 'AIRFLOW_DAG_TRANSITION_REJECTED', 'The Airflow DAG transition was rejected.')
    }
    let receipt
    try {
      receipt = await control.acceptDagTransition(claim.receipt.operation_id)
    } catch {
      await deps.bestEffortAirflowReceiptWrite(() => control.requireDagTransitionReconciliation(
        claim.receipt.operation_id, 'AIRFLOW_DAG_TRANSITION_OUTCOME_UNKNOWN',
      ))
      throw deps.accessError(502, 'AIRFLOW_DAG_TRANSITION_OUTCOME_UNKNOWN', 'Airflow applied the DAG transition but its receipt could not be finalized.')
    }
    return deps.json(response, claim.action === 'TRANSITION' ? 202 : 200, {
      system_id: deps.AIRFLOW_SYSTEM_ID,
      action: body.action,
      replayed: claim.action !== 'TRANSITION',
      reconciled: claim.action === 'RECONCILE',
      dag,
      receipt,
    })
  }
  const minioPart = url.pathname.match(/^\/poc-api\/minio\/uploads\/([a-zA-Z0-9_-]+)\/parts\/(\d+)$/)
  if (request.method === 'PUT' && minioPart) {
    if (!deps.minio) return deps.problem(response, 503, 'MINIO_NOT_CONFIGURED', 'MinIO is not configured.')
    const partNumber = Number(minioPart[2])
    if (!Number.isInteger(partNumber) || partNumber < 1 || partNumber > 100) {
      return deps.problem(response, 400, 'PART_NUMBER_INVALID', 'Part number must be between 1 and 100.')
    }
    const body = await deps.bodyBuffer(request, deps.maximumObjectBytes)
    const key = `poc-uploads/${minioPart[1]}/part-${partNumber}`
    const contentType = deps.boundedString(request.headers['content-type'], 255, 'application/octet-stream')
    const upstream = await deps.minioObject('PUT', deps.minio.buckets.quarantine, key, body, contentType)
    response.writeHead(200, { ETag: upstream.headers.get('etag') || `"${deps.sha256(body)}"`, ...deps.securityHeaders() })
    return response.end()
  }
  const minioComplete = url.pathname.match(/^\/poc-api\/minio\/uploads\/([a-zA-Z0-9_-]+)\/complete$/)
  if (request.method === 'POST' && minioComplete) {
    if (!deps.minio) return deps.problem(response, 503, 'MINIO_NOT_CONFIGURED', 'MinIO is not configured.')
    const body = await deps.bodyJson(request)
    const parts = Number(body.part_count || 1)
    if (!Number.isInteger(parts) || parts < 1 || parts > 100) {
      return deps.problem(response, 400, 'PART_COUNT_INVALID', 'Part count must be between 1 and 100.')
    }
    const chunks = []
    let size = 0
    for (let part = 1; part <= parts; part += 1) {
      const upstream = await deps.minioObject('GET', deps.minio.buckets.quarantine, `poc-uploads/${minioComplete[1]}/part-${part}`)
      const chunk = Buffer.from(await upstream.arrayBuffer())
      size += chunk.length
      if (size > deps.maximumObjectBytes) throw Object.assign(new Error('Completed upload is too large.'), { statusCode: 413 })
      chunks.push(chunk)
    }
    const object = Buffer.concat(chunks)
    const displayName = deps.boundedString(body.display_name, 255, 'upload.bin').replace(/[^a-zA-Z0-9._-]/g, '_')
    const filefolder = body.target_bucket === 'filefolder'
    const extension = displayName.toLocaleLowerCase().endsWith('.xlsx') ? 'xlsx' : 'csv'
    const bucket = filefolder ? deps.minio.buckets.filefolder : deps.minio.buckets.accepted
    const key = filefolder
      ? `bulk-registration/${minioComplete[1]}/catalog-metadata-source.${extension}`
      : `poc-accepted/${minioComplete[1]}/${displayName}`
    await deps.minioObject('PUT', bucket, key, object, deps.boundedString(body.content_type, 255, 'application/octet-stream'))
    return deps.json(response, 200, { bucket, key, size_bytes: object.length, sha256: deps.sha256(object) })
  }
  const minioAccepted = url.pathname.match(/^\/poc-api\/minio\/accepted\/([a-zA-Z0-9_-]+)\/([^/]+)$/)
  if (request.method === 'GET' && minioAccepted) {
    if (!deps.minio) return deps.problem(response, 503, 'MINIO_NOT_CONFIGURED', 'MinIO is not configured.')
    const displayName = decodeURIComponent(minioAccepted[2]).replace(/[^a-zA-Z0-9._-]/g, '_')
    const key = `poc-accepted/${minioAccepted[1]}/${displayName}`
    const upstream = await deps.minioObject('GET', deps.minio.buckets.accepted, key)
    const object = Buffer.from(await upstream.arrayBuffer())
    if (object.length > deps.maximumObjectBytes) throw Object.assign(new Error('Stored object is too large.'), { statusCode: 413 })
    response.writeHead(200, {
      ...deps.securityHeaders(),
      'Content-Type': upstream.headers.get('content-type') || 'application/octet-stream',
      'Content-Length': String(object.length),
      'Content-Disposition': `attachment; filename*=UTF-8''${encodeURIComponent(displayName)}`,
    })
    return response.end(object)
  }
  if (/^\/poc-api\/knowledge\/studio\/drafts\/[^/]+\/abox\/(previews|ingestions)$/.test(url.pathname)) {
    return deps.knowledgeABoxIngestionApi(request, response, url, context)
  }
  if (url.pathname === '/poc-api/knowledge/projections') {
    return deps.knowledgeProjectionApi(request, response, url, context)
  }
  if (url.pathname === '/poc-api/knowledge/managed-assets'
    || /^\/poc-api\/knowledge\/managed-assets\/[^/]+\/(detail|versions)$/.test(url.pathname)
    || url.pathname === '/poc-api/knowledge/graphs'
    || /^\/poc-api\/knowledge\/graphs\/[^/]+\/releases(?:\/[^/]+\/(?:snapshot|graphrag))?$/.test(url.pathname)) {
    return deps.knowledgeChatApi(request, response, url, context)
  }

  if (request.method === 'GET' && url.pathname === '/poc-api/neo4j/graph') {
    return deps.json(response, 200, context.principal.role === 'admin' ? await deps.neo4jGraph() : { nodes: [], edges: [] })
  }
  return deps.problem(response, 404, 'NOT_FOUND', 'The POC gateway route does not exist.')
}

return { api }
}
