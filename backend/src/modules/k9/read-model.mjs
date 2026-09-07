
// Dependencies are supplied by bootstrap; this module never constructs a shared client.
export function createModulesK9ReadModel(deps) {
function managedK9SourceDiagnostic(errorMessage) {
  const matched = /^K9_DATAHUB_SOURCE_FAILED: failure_stage=([A-Z0-9_]+); failure_detail_code=([A-Z0-9_]+)\.$/
    .exec(errorMessage || '')
  return matched && deps.k9SourceFailureStages.has(matched[1]) && deps.k9SourceFailureDetails.has(matched[2])
    ? { failure_stage: matched[1], failure_detail_code: matched[2] }
    : null
}

function isoValue(value) {
  if (value instanceof Date) return value.toISOString()
  return typeof value === 'string' ? value : null
}

function schedulerTimestamp(value) {
  if (typeof value !== 'string' || value.length > 64) return null
  const timestamp = Date.parse(value)
  return Number.isFinite(timestamp) ? new Date(timestamp).toISOString() : null
}

function managedK9SchedulerReadModel(
  schedulerConfig,
  schedulerReceiptSnapshot = null,
  activeRefreshAttempt = null,
  now = new Date(),
) {
  if (!schedulerConfig) {
    return {
      scheduler_status: 'UNAVAILABLE', scheduler_requested: false, scheduler_timer_enabled: false,
      schedule: null, schedule_timezone: null, next_scheduled_run: null,
      last_successful_schedule: null, scheduler_current_attempt: null,
      scheduler_last_completed_attempt: null, scheduler_last_attempt: null,
    }
  }
  const receipt = schedulerReceiptSnapshot?.value
  const durableAttempt = receipt?.last_attempt
  const durableStatus = ['SUCCESS', 'FAILURE'].includes(durableAttempt?.status) ? durableAttempt.status : null
  const durableTrigger = ['scheduled', 'manual'].includes(durableAttempt?.trigger) ? durableAttempt.trigger : null
  const durableReason = durableStatus === 'FAILURE'
    && typeof durableAttempt?.reason === 'string'
    && /^K9_[A-Z0-9_]+$/.test(durableAttempt.reason)
    ? durableAttempt.reason : null
  const durableLifecycleMode = deps.K9_V2_SOURCE_RUN_MODES.includes(durableAttempt?.lifecycle_mode)
    ? durableAttempt.lifecycle_mode : null
  const durableExecutionId = /^[0-9a-f]{64}$/u.test(durableAttempt?.execution_id || '')
    ? durableAttempt.execution_id : null
  const durableExpectedSourceSnapshotId = /^[0-9a-f]{64}$/u.test(
    durableAttempt?.expected_source_snapshot_id || '',
  ) ? durableAttempt.expected_source_snapshot_id : null
  const durableSuccessorSourceSnapshotId = /^[0-9a-f]{64}$/u.test(
    durableAttempt?.successor_source_snapshot_id || '',
  ) ? durableAttempt.successor_source_snapshot_id : null
  const durableSourceCorrectionIdentity = durableExecutionId && durableExpectedSourceSnapshotId
    && ((durableLifecycleMode === 'SOURCE_CORRECTION_RECAPTURE'
      && durableSuccessorSourceSnapshotId === null)
      || (durableLifecycleMode === 'RESUME' && durableSuccessorSourceSnapshotId !== null))
    ? {
        lifecycle_mode: durableLifecycleMode,
        execution_id: durableExecutionId,
        expected_source_snapshot_id: durableExpectedSourceSnapshotId,
        source_correction_phase: durableSuccessorSourceSnapshotId ? 'SUCCESSOR_BOUND' : 'CLAIMED',
        ...(durableSuccessorSourceSnapshotId
          ? { successor_source_snapshot_id: durableSuccessorSourceSnapshotId } : {}),
      }
    : null
  const durableV2Diagnostic = durableReason && deps.k9V2FailureCodes.has(durableReason)
    ? deps.sanitizeK9V2FailureDiagnostic({
        code: durableReason,
        stage: durableAttempt.failure_stage,
        failure_detail_code: durableAttempt.failure_detail_code,
        ...Object.fromEntries([
          'persistence_substage', 'payload_kind', 'payload_bytes',
          'configured_limit_bytes', 'sqlstate_class', 'constraint_name',
        ].filter((field) => Object.hasOwn(durableAttempt || {}, field))
          .map((field) => [field, durableAttempt[field]])),
      })
    : null
  const schedulerLastAttempt = durableStatus ? {
    status: durableStatus,
    scheduled_for: schedulerTimestamp(durableAttempt.scheduled_for),
    completed_at: schedulerTimestamp(durableAttempt.completed_at),
    trigger: durableTrigger,
    ...(durableSourceCorrectionIdentity || {}),
    ...(durableReason ? { reason: durableReason } : {}),
    ...(durableReason === 'K9_DATAHUB_SOURCE_FAILED'
      && deps.k9SourceFailureStages.has(durableAttempt.failure_stage)
      && deps.k9SourceFailureDetails.has(durableAttempt.failure_detail_code)
      ? {
          failure_stage: durableAttempt.failure_stage,
          failure_detail_code: durableAttempt.failure_detail_code,
          ...(deps.sanitizeK9LineageSourceProfile(durableAttempt.lineage_source_profile)
            ? { lineage_source_profile: deps.sanitizeK9LineageSourceProfile(durableAttempt.lineage_source_profile) }
            : {}),
          ...(deps.sanitizeK9SourceEligibilityTelemetry(durableAttempt.source_eligibility)
            ? { source_eligibility: deps.sanitizeK9SourceEligibilityTelemetry(durableAttempt.source_eligibility) }
            : {}),
        }
      : {}),
    ...(durableV2Diagnostic ? {
      failure_stage: durableV2Diagnostic.stage,
      failure_detail_code: durableV2Diagnostic.failure_detail_code,
      ...Object.fromEntries([
        'persistence_substage', 'payload_kind', 'payload_bytes',
        'configured_limit_bytes', 'sqlstate_class', 'constraint_name',
      ].filter((field) => Object.hasOwn(durableV2Diagnostic, field))
        .map((field) => [field, durableV2Diagnostic[field]])),
    } : {}),
  } : null
  const refreshRunning = activeRefreshAttempt?.status === 'RUNNING'
  const activeTrigger = ['scheduled', 'manual'].includes(activeRefreshAttempt?.trigger)
    ? activeRefreshAttempt.trigger : null
  const activeStage = /^[A-Z][A-Z0-9_]{0,95}$/.test(activeRefreshAttempt?.stage || '')
    ? activeRefreshAttempt.stage : null
  const activeDetail = /^[A-Z][A-Z0-9_]{0,95}$/.test(activeRefreshAttempt?.detail || '')
    ? activeRefreshAttempt.detail : null
  const activeCount = (value) => Number.isSafeInteger(value) && value >= 0 ? value : 0
  const activeProgress = Object.hasOwn(activeRefreshAttempt || {}, 'completed')
  const activeLifecycleMode = deps.K9_V2_SOURCE_RUN_MODES.includes(activeRefreshAttempt?.lifecycle_mode)
    ? activeRefreshAttempt.lifecycle_mode : null
  const activeExecutionId = /^[0-9a-f]{64}$/u.test(activeRefreshAttempt?.execution_id || '')
    ? activeRefreshAttempt.execution_id : null
  const activeExpectedSourceSnapshotId = /^[0-9a-f]{64}$/u.test(
    activeRefreshAttempt?.expected_source_snapshot_id || '',
  ) ? activeRefreshAttempt.expected_source_snapshot_id : null
  const activeSuccessorSourceSnapshotId = /^[0-9a-f]{64}$/u.test(
    activeRefreshAttempt?.successor_source_snapshot_id || '',
  ) ? activeRefreshAttempt.successor_source_snapshot_id : null
  const activeSourceCorrectionIdentity = activeExecutionId && activeExpectedSourceSnapshotId
    && ((activeLifecycleMode === 'SOURCE_CORRECTION_RECAPTURE'
      && activeSuccessorSourceSnapshotId === null)
      || (activeLifecycleMode === 'RESUME' && activeSuccessorSourceSnapshotId !== null))
    ? {
        lifecycle_mode: activeLifecycleMode,
        execution_id: activeExecutionId,
        expected_source_snapshot_id: activeExpectedSourceSnapshotId,
        source_correction_phase: activeSuccessorSourceSnapshotId ? 'SUCCESSOR_BOUND' : 'CLAIMED',
        ...(activeSuccessorSourceSnapshotId
          ? { successor_source_snapshot_id: activeSuccessorSourceSnapshotId } : {}),
      }
    : null
  const schedulerCurrentAttempt = refreshRunning ? {
    status: 'RUNNING',
    scheduled_for: schedulerTimestamp(activeRefreshAttempt.scheduled_for),
    trigger: activeTrigger,
    started_at: schedulerTimestamp(activeRefreshAttempt.started_at),
    observed_at: schedulerTimestamp(activeRefreshAttempt.observed_at),
    ...(activeSourceCorrectionIdentity || {}),
    ...(activeStage ? { stage: activeStage } : {}),
    ...(activeDetail ? { detail: activeDetail } : {}),
    ...(activeProgress ? {
      completed: activeCount(activeRefreshAttempt.completed),
      total: activeCount(activeRefreshAttempt.total),
      candidate_number: activeCount(activeRefreshAttempt.candidate_number),
      candidate_total: activeCount(activeRefreshAttempt.candidate_total),
      batch_number: activeCount(activeRefreshAttempt.batch_number),
      batch_total: activeCount(activeRefreshAttempt.batch_total),
    } : {}),
  } : null
  const nextScheduledRun = schedulerConfig.enabled
    ? deps.nextScheduleBoundary(
      now,
      schedulerConfig.timeZone,
      schedulerConfig.scheduleHour,
      schedulerConfig.scheduleMinute,
      schedulerConfig.refreshMode,
    ).toISOString()
    : null
  return {
    scheduler_status: refreshRunning
      ? 'RUNNING'
      : (!schedulerConfig.requested ? 'DISABLED' : (schedulerConfig.enabled ? 'SCHEDULED' : 'ON_DEMAND')),
    scheduler_requested: Boolean(schedulerConfig.requested),
    scheduler_timer_enabled: Boolean(schedulerConfig.enabled),
    schedule: schedulerConfig.schedule,
    schedule_timezone: schedulerConfig.timeZone,
    next_scheduled_run: nextScheduledRun,
    last_successful_schedule: schedulerTimestamp(receipt?.last_successful_schedule),
    scheduler_current_attempt: schedulerCurrentAttempt,
    scheduler_last_completed_attempt: schedulerLastAttempt,
    // Backward-compatible historical alias. New orchestration and smoke code
    // must use the explicit current/completed fields above.
    scheduler_last_attempt: schedulerLastAttempt,
  }
}

function managedK9AssetSummary(
  row,
  semanticIndex,
  schedulerConfig,
  includeQualityMetrics = false,
  activeRefreshAttempt = null,
  schedulerReceiptSnapshot = null,
  now = new Date(),
) {
  const definition = deps.k9GraphAssetDefinition(row.graph_id)
  if (!definition) throw deps.knowledgeProjectionError(409, 'K9_ASSET_DEFINITION_MISSING', 'The managed graph Asset definition is missing.')
  const manifest = row.active_manifest && typeof row.active_manifest === 'object'
    ? row.active_manifest
    : {}
  const sourceSnapshot = manifest.source_snapshot && typeof manifest.source_snapshot === 'object'
    ? manifest.source_snapshot
    : {}
  const qualityMetrics = manifest.quality_metrics && typeof manifest.quality_metrics === 'object'
    ? manifest.quality_metrics
    : null
  const semanticIndexMatchesSnapshot = Boolean(row.active_release_pointer) && semanticIndex?.ready && (
    !sourceSnapshot.catalog_generation
    || semanticIndex.generation === sourceSnapshot.catalog_generation
  )
  const refreshRunning = activeRefreshAttempt?.status === 'RUNNING'
  const storedLatestResult = row.latest_result === 'RUN' ? 'SUCCESS' : (row.latest_result || 'NOT_RUN')
  const latestResult = refreshRunning ? 'RUNNING' : storedLatestResult
  const storedFailureCode = !refreshRunning && latestResult === 'FAILURE'
    ? /^((?:K9_)[A-Z0-9_]+):/.exec(row.latest_error_message || '')?.[1] || 'K9_REFRESH_FAILED'
    : null
  const latestSourceEligibility = deps.sanitizeK9SourceEligibilityTelemetry(
    row.latest_manifest?.failure_diagnostic?.source_eligibility,
  )
  const baseSourceDiagnostic = storedFailureCode === 'K9_DATAHUB_SOURCE_FAILED'
    ? managedK9SourceDiagnostic(row.latest_error_message) : null
  const sourceDiagnostic = storedFailureCode === 'K9_DATAHUB_SOURCE_FAILED'
    && (baseSourceDiagnostic || latestSourceEligibility)
    ? {
        ...(baseSourceDiagnostic || {}),
        ...(latestSourceEligibility ? { source_eligibility: latestSourceEligibility } : {}),
      }
    : null
  const latestFailureProfile = deps.sanitizeK9MetadataSourceProfile(
    row.latest_manifest?.failure_diagnostic?.metadata_source_profile,
  )
  const latestLineageFailureProfile = deps.sanitizeK9LineageSourceProfile(
    row.latest_manifest?.failure_diagnostic?.lineage_source_profile,
  )
  const activeMetadataProfile = deps.sanitizeK9MetadataSourceProfile(sourceSnapshot.metadata_source_profile)
  const activeDirectResolution = activeMetadataProfile?.direct_resolution
  const activeAssignments = activeMetadataProfile?.assignments
  const sourceWarning = activeDirectResolution?.dangling_unique_terms > 0 ? {
    code: 'DANGLING_GLOSSARY_ASSIGNMENTS',
    dangling_unique_terms: activeDirectResolution.dangling_unique_terms,
    dangling_assignment_references: activeDirectResolution.dangling_assignment_references,
    absent: activeDirectResolution.dangling_absent_count,
    does_not_exist: activeDirectResolution.dangling_does_not_exist_count,
    removed: activeDirectResolution.dangling_removed_count,
  } : null
  const assignmentScope = activeAssignments ? {
    provider_incoming_table_total: activeAssignments.provider_incoming_table_total,
    provider_incoming_column_total: activeAssignments.provider_incoming_column_total,
    k9_scoped_table_reference_total: activeAssignments.raw_table_refs,
    k9_scoped_column_reference_total: activeAssignments.raw_column_refs,
    provider_scope_relation: activeAssignments.provider_scope_relation,
  } : null
  const status = row.active_release_pointer
    ? (latestResult === 'FAILURE' ? 'READY_WITH_REFRESH_FAILURE' : 'READY')
    : (latestResult === 'FAILURE' ? 'FAILED' : 'PENDING')
  const scheduler = managedK9SchedulerReadModel(
    schedulerConfig, schedulerReceiptSnapshot, activeRefreshAttempt, now,
  )
  return {
    id: row.graph_id,
    slug: `managed-${row.managed_intent}`,
    name: definition.display_name,
    description: definition.description,
    display_version: Number(row.publication_version || 1),
    graph_type: definition.graph_type,
    canonical_graph_type: row.name,
    status,
    classification: row.classification,
    domain_id: null,
    domain_name: null,
    creator_name: 'Knowledge Studio',
    creator_email: null,
    editor_name: 'DataHub managed refresh',
    editor_email: null,
    active_studio_release_id: row.studio_release_id,
    active_studio_release_no: Number(row.publication_version || 1),
    active_release_id: row.active_release_pointer || null,
    active_release_no: row.active_release_pointer ? 1 : null,
    class_count: 0,
    property_count: 0,
    relationship_count: 0,
    binding_count: 0,
    source_count: row.active_release_pointer ? 1 : 0,
    node_count: Number(manifest.node_count || 0),
    edge_count: Number(manifest.edge_count || 0),
    projection_state: status,
    created_at: isoValue(row.created_at) || isoValue(row.updated_at) || new Date(0).toISOString(),
    updated_at: isoValue(row.active_completed_at) || isoValue(row.updated_at) || new Date(0).toISOString(),
    version: Number(row.publication_version || 1),
    delivery_policy: null,
    managed: true,
    source: definition.source,
    is_default: definition.is_default,
    refresh_mode: schedulerConfig?.refreshMode || 'DAILY',
    ...scheduler,
    next_refresh: scheduler.next_scheduled_run,
    last_refresh: isoValue(row.latest_completed_at),
    last_result: latestResult,
    last_error_code: storedFailureCode,
    refresh_attempt: refreshRunning ? activeRefreshAttempt : null,
    ...(sourceDiagnostic || {}),
    metadata_source_profile: includeQualityMetrics
      ? latestFailureProfile || activeMetadataProfile
      : null,
    lineage_source_profile: latestLineageFailureProfile,
    k9_source_warning: sourceWarning,
    k9_assignment_scope: assignmentScope,
    semantic_index_status: semanticIndexMatchesSnapshot ? 'READY' : 'PENDING',
    semantic_index_contract: semanticIndex?.contract || null,
    semantic_index_generation: semanticIndex?.generation || null,
    semantic_index_binding_hash: semanticIndex?.bindingHash || null,
    graph_model_version: Number(manifest.model_version || 1),
    source_snapshot_id: sourceSnapshot.source_snapshot_id || null,
    source_eligibility: deps.sanitizeK9SourceEligibilityTelemetry(sourceSnapshot.source_eligibility),
    source_snapshot_observed_at: sourceSnapshot.observed_at || null,
    source_catalog_generation: sourceSnapshot.catalog_generation || null,
    source_datahub_version: sourceSnapshot.datahub_version || null,
    source_datahub_commit: sourceSnapshot.datahub_commit || null,
    active_projection: row.active_release_pointer || null,
    lineage_source: definition.graph_type === 'LINEAGE' ? 'DataHub upstreamLineage / fineGrainedLineages' : null,
    quality_metrics: includeQualityMetrics ? qualityMetrics : null,
    supported_intents: definition.supported_intents,
    semantic_capabilities: definition.semantic_capabilities,
    supported_entity_types: definition.supported_entity_types,
    active_input_snapshot_hash: row.active_input_snapshot_hash || null,
  }
}

function assertManagedK9AssetAccess(context) {
  if (context.principal?.role === 'admin') return
  if (!context.principal?.capabilitySet?.has('knowledge.read')
    || !(context.principal.activeTableGrantUrns instanceof Set)
    || context.principal.activeTableGrantUrns.size === 0) {
    throw deps.knowledgeChatNotFound()
  }
}

function managedK9NodeDatasetUrn(node) {
  const properties = node?.properties && typeof node.properties === 'object'
    ? node.properties
    : {}
  const candidate = properties.dataset_urn || properties.external_urn
  return deps.isCanonicalDatahubDatasetUrn(candidate) ? candidate : null
}

function authorizeManagedK9Release(principal, canonicalRelease, { knowledgeAdapter = null } = {}) {
  if (principal?.role === 'admin') return canonicalRelease
  const nodes = Array.isArray(canonicalRelease?.nodes) ? canonicalRelease.nodes : []
  const edges = Array.isArray(canonicalRelease?.edges) ? canonicalRelease.edges : []
  const dataNodeIds = new Set()
  const allowedNodeIds = new Set()
  for (const node of nodes) {
    const datasetUrn = managedK9NodeDatasetUrn(node)
    if (!datasetUrn) continue
    dataNodeIds.add(node.id)
    const serviceTableAllowed = knowledgeAdapter === 'MCP'
      && principal.capabilitySet?.has('knowledge.read')
      && principal.activeTableGrantUrns?.has(datasetUrn)
    if (serviceTableAllowed || (knowledgeAdapter !== 'MCP' && deps.canReadAsset(principal, {
      id: datasetUrn,
      dataset_kind: 'TABLE',
    }, 'knowledge'))) {
      allowedNodeIds.add(node.id)
    }
  }
  // Non-data semantic nodes are visible only when they are attached to a Table or
  // Column that is already authorized. Data nodes are never admitted transitively.
  let changed = true
  while (changed) {
    changed = false
    for (const edge of edges) {
      const sourceAllowed = allowedNodeIds.has(edge.source)
      const targetAllowed = allowedNodeIds.has(edge.target)
      if (sourceAllowed && !dataNodeIds.has(edge.target) && !allowedNodeIds.has(edge.target)) {
        allowedNodeIds.add(edge.target)
        changed = true
      }
      if (targetAllowed && !dataNodeIds.has(edge.source) && !allowedNodeIds.has(edge.source)) {
        allowedNodeIds.add(edge.source)
        changed = true
      }
    }
  }
  return {
    ...canonicalRelease,
    nodes: nodes.filter((node) => allowedNodeIds.has(node.id)),
    edges: edges.filter((edge) => allowedNodeIds.has(edge.source) && allowedNodeIds.has(edge.target)),
  }
}

async function managedK9Assets(context) {
  if (typeof context.stateStore.listK9ManagedGraphAssets !== 'function') return []
  let rows
  try {
    rows = await context.stateStore.listK9ManagedGraphAssets()
  } catch (error) {
    if (!context.stateStore.configured?.postgres) return []
    throw error
  }
  const bindingHash = deps.catalogEmbeddingBindingHash()
  const semanticIndexGeneration = bindingHash
    ? await context.stateStore.catalogEmbeddingActiveGeneration(bindingHash)
    : null
  const semanticIndex = {
    ready: Boolean(bindingHash && semanticIndexGeneration),
    contract: 'POC_DATAHUB_SEMANTIC_DOCUMENT_V3',
    bindingHash: bindingHash || null,
    generation: semanticIndexGeneration || null,
  }
  const activeRefreshAttempt = typeof context.k9SchedulerStatus === 'function'
    ? context.k9SchedulerStatus()
    : null
  const schedulerReceiptSnapshot = context.k9SchedulerConfig?.lockName
    && typeof context.stateStore.readK9SchedulerReceipt === 'function'
    ? await context.stateStore.readK9SchedulerReceipt(context.k9SchedulerConfig.lockName)
    : null
  return rows.flatMap((row) => {
    try {
      assertManagedK9AssetAccess(context)
      return [managedK9AssetSummary(
        row,
        semanticIndex,
        context.k9SchedulerConfig,
        context.principal.role === 'admin',
        activeRefreshAttempt,
        schedulerReceiptSnapshot,
      )]
    } catch (error) {
      if (error?.code === 'KNOWLEDGE_GRAPH_NOT_FOUND') return []
      throw error
    }
  })
}

async function managedK9LifecycleStatus(context) {
  if (typeof context.stateStore.readK9SnapshotLifecycleV2 !== 'function') {
    return deps.publicK9V2LifecycleStatus(null)
  }
  try {
    return deps.publicK9V2LifecycleStatus(await context.stateStore.readK9SnapshotLifecycleV2())
  } catch (error) {
    if (!context.stateStore.configured?.postgres) return deps.publicK9V2LifecycleStatus(null)
    throw error
  }
}

function managedK9ScopeFromRow(context, row, requestedReleaseId) {
  assertManagedK9AssetAccess(context)
  if (!row.active_release_pointer || !row.active_canonical_release
    || (requestedReleaseId && requestedReleaseId !== row.active_release_pointer)) {
    throw deps.knowledgeChatNotFound()
  }
  const activeCanonicalRelease = row.active_canonical_release
  if (!activeCanonicalRelease || typeof activeCanonicalRelease !== 'object'
    || activeCanonicalRelease.manifest?.graph_id !== row.graph_id
    || activeCanonicalRelease.manifest?.policy_hash !== row.policy_hash
    || activeCanonicalRelease.manifest?.input_snapshot_hash !== row.active_input_snapshot_hash
    || !Array.isArray(activeCanonicalRelease.nodes)
    || !Array.isArray(activeCanonicalRelease.edges)) {
    throw deps.knowledgeProjectionError(409, 'K9_ACTIVE_RELEASE_INVALID', 'The active managed graph release is inconsistent.')
  }
  const canonicalRelease = authorizeManagedK9Release(context.principal, activeCanonicalRelease, {
    knowledgeAdapter: context.knowledgeAdapter,
  })
  const definition = deps.k9GraphAssetDefinition(row.graph_id)
  const grade = deps.k9ServiceCeilingToGrade[row.classification]
  return Object.freeze({
    managed: true,
    graphId: row.graph_id,
    studioReleaseId: row.active_release_pointer,
    studioAuthorityReleaseId: row.studio_release_id,
    namespace: row.active_release_pointer,
    policy: row,
    canonicalRelease,
    projectionEvidenceHash: row.active_input_snapshot_hash,
    draft: {
      name: definition.display_name,
      endpoint_alias: `managed-${row.managed_intent}`,
      classification: grade,
      author_id: row.subject_id,
      published_by: row.subject_id,
      created_at: isoValue(row.created_at),
      updated_at: isoValue(row.active_completed_at) || isoValue(row.updated_at),
    },
    release: {
      id: row.active_release_pointer,
      release_no: Number(row.publication_version || 1),
      ontology_version_id: row.ontology_version_id,
      contract_hash: row.active_release_hash || row.active_input_snapshot_hash,
      published_by: row.subject_id,
      published_at: isoValue(row.active_completed_at) || isoValue(row.updated_at),
    },
  })
}

return { managedK9SourceDiagnostic, isoValue, schedulerTimestamp, managedK9SchedulerReadModel, managedK9AssetSummary, assertManagedK9AssetAccess, managedK9NodeDatasetUrn, authorizeManagedK9Release, managedK9Assets, managedK9LifecycleStatus, managedK9ScopeFromRow }
}
