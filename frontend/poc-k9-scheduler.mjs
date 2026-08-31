/* global clearTimeout, process, setTimeout */

import {
  K9_METADATA_FAILURE_DETAILS,
  sanitizeK9MetadataSourceProfile,
} from './poc-k9-metadata-collection.mjs'

const DEFAULT_TIME_ZONE = 'Asia/Seoul'
const DEFAULT_REFRESH_MODE = 'DAILY'
const DEFAULT_SCHEDULE_HOUR = 2
const DEFAULT_SCHEDULE_MINUTE = 0
const DEFAULT_LOCK_NAME = 'datariver:poc:k9-scheduler:v1'
const MAX_TIMER_DELAY_MS = 2_147_000_000
const supportedRefreshModes = new Set(['DAILY', 'HOURLY', 'MANUAL', 'EVENT_DRIVEN'])
const supportedClassificationCeilings = new Set(['PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED'])
const canonicalManagedIntents = Object.freeze(['metadata-lineage', 'data-glossary'])
const supportedSourceFailureStages = new Set([
  'INVENTORY',
  'INVENTORY_PROJECTION',
  'LINEAGE_COLLECTION',
  'METADATA_COLLECTION',
  'RUNTIME_IDENTITY',
])
const supportedSourceFailureDetails = new Set([
  'CONNECTIVITY',
  'TIMEOUT',
  'HTTP_4XX',
  'HTTP_5XX',
  'GRAPHQL',
  'CONTRACT',
  'EMPTY_SOURCE',
  'INTERNAL_TRANSFORM',
  ...K9_METADATA_FAILURE_DETAILS,
])
const retryableSourceFailureDetails = new Set(['CONNECTIVITY', 'TIMEOUT', 'HTTP_5XX'])
const SOURCE_RETRY_DELAY_MS = 1_000
const SOURCE_MAX_ATTEMPTS = 2
const SOURCE_CONSISTENCY_MAX_COMPARISONS = 2
const SOURCE_CONSISTENCY_RETRY_DELAY_MS = 1_000
const supportedK9FailureCodes = new Set([
  'K9_DATAHUB_SOURCE_FAILED',
  'K9_FAILURE_STATE_PERSISTENCE_FAILED',
  'K9_LINEAGE_REFRESH_FAILED',
  'K9_METADATA_REFRESH_FAILED',
  'K9_NEO4J_PROJECTION_FAILED',
  'K9_POLICY_PIN_DRIFT_FAILED',
  'K9_PROMOTION_FAILED',
  'K9_REFRESH_FAILED',
  'K9_SEMANTIC_INDEX_FAILED',
  'K9_SOURCE_SNAPSHOT_FAILED',
  'K9_SOURCE_DRIFT_RETRY_EXHAUSTED',
  'K9_SYSTEM_SUBJECT_FAILED',
])

function boundedK9FailureCode(value, fallback = 'K9_REFRESH_FAILED') {
  return typeof value === 'string' && supportedK9FailureCodes.has(value) ? value : fallback
}

async function k9RefreshStage(failureCode, action) {
  try {
    return await action()
  } catch {
    throw Object.assign(new Error(failureCode), { k9FailureCode: failureCode })
  }
}

function errorChain(error) {
  const chain = []
  let current = error
  while (current && typeof current === 'object' && chain.length < 4 && !chain.includes(current)) {
    chain.push(current)
    current = current.cause
  }
  return chain
}

function datahubSourceFailureDetail(error) {
  const chain = errorChain(error)
  const explicit = chain.find((item) => supportedSourceFailureDetails.has(item?.k9SourceFailureDetailCode))
  if (explicit) return explicit.k9SourceFailureDetailCode
  if (chain.some((item) => item?.name === 'TimeoutError')) return 'TIMEOUT'

  const httpClass = chain.map((item) => (
    item?.providerHttpClass || item?.inventoryDiagnostic?.provider_http_class
  )).find((value) => value === '4xx' || value === '5xx')
  if (httpClass) return httpClass === '4xx' ? 'HTTP_4XX' : 'HTTP_5XX'
  const statusCode = chain.map((item) => Number(item?.statusCode))
    .find((value) => Number.isInteger(value) && value >= 400 && value <= 599)
  if (statusCode) return statusCode < 500 ? 'HTTP_4XX' : 'HTTP_5XX'

  if (chain.some((item) => item?.providerFailureKind === 'GRAPHQL'
    || String(item?.code || '').includes('GRAPHQL'))) return 'GRAPHQL'
  if (chain.some((item) => ['RESPONSE_JSON', 'CONTRACT'].includes(item?.providerFailureKind)
    || String(item?.code || '').includes('CONTRACT'))) return 'CONTRACT'
  if (chain.some((item) => item?.providerFailureKind === 'TRANSPORT')) return 'CONNECTIVITY'
  if (chain.some((item) => [
    'PREP_DATAHUB_INVENTORY_QUERY_FAILED',
    'PREP_DATAHUB_INVENTORY_PAGE_FAILED',
  ].includes(item?.code))) return 'CONNECTIVITY'
  return 'INTERNAL_TRANSFORM'
}

function sourceResultFailureDetail(failureStage, value) {
  if (failureStage === 'INVENTORY') {
    if (!Array.isArray(value)) return 'CONTRACT'
    if (value.length === 0) return 'EMPTY_SOURCE'
  } else if (failureStage === 'INVENTORY_PROJECTION') {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return 'CONTRACT'
  } else if (['LINEAGE_COLLECTION', 'METADATA_COLLECTION'].includes(failureStage)) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return 'CONTRACT'
  } else if (failureStage === 'RUNTIME_IDENTITY') {
    if (!value || typeof value !== 'object' || Array.isArray(value)
      || typeof value.version !== 'string' || !value.version.trim() || value.version.length > 200
      || (value.commit !== null && value.commit !== undefined
        && (typeof value.commit !== 'string' || value.commit.length > 200))) return 'CONTRACT'
  }
  return null
}

async function datahubSourceStage(failureStage, action, sourceRetryWait) {
  if (!supportedSourceFailureStages.has(failureStage)) throw new Error('The K9 source failure stage is invalid.')
  for (let attempt = 1; attempt <= SOURCE_MAX_ATTEMPTS; attempt += 1) {
    try {
      const value = await action({ attempt })
      const invalidDetail = sourceResultFailureDetail(failureStage, value)
      if (invalidDetail) {
        throw Object.assign(new Error('The K9 DataHub source result is invalid.'), {
          k9SourceFailureDetailCode: invalidDetail,
        })
      }
      return value
    } catch (error) {
      const failureDetailCode = datahubSourceFailureDetail(error)
      if (attempt < SOURCE_MAX_ATTEMPTS && retryableSourceFailureDetails.has(failureDetailCode)) {
        try {
          await sourceRetryWait(SOURCE_RETRY_DELAY_MS, { failureStage, failureDetailCode, attempt })
          continue
        } catch {
          // A retry clock failure cannot expose its exception or turn a
          // bounded provider failure into an unclassified scheduler error.
        }
      }
      const metadataProfile = failureStage === 'METADATA_COLLECTION'
        ? errorChain(error).map((item) => sanitizeK9MetadataSourceProfile(item?.k9MetadataSourceProfile))
          .find(Boolean) || null
        : null
      throw Object.assign(new Error('K9_DATAHUB_SOURCE_FAILED'), {
        k9FailureCode: 'K9_DATAHUB_SOURCE_FAILED',
        k9SourceDiagnostic: Object.freeze({
          failureStage,
          failureDetailCode,
          ...(metadataProfile ? { metadataProfile } : {}),
        }),
      })
    }
  }
  throw new Error('The bounded K9 DataHub source retry was exhausted.')
}

async function defaultSourceRetryWait(delayMs) {
  await new Promise((resolvePromise) => setTimeout(resolvePromise, delayMs))
}

async function collectStableK9Source({
  resolveAuthContext,
  currentInventory,
  inventoryProjection,
  collectLineage,
  collectMetadata,
  runtimeIdentity,
  sourceIdentity,
  sourceRetryWait,
}) {
  const liveAuth = await k9RefreshStage('K9_SYSTEM_SUBJECT_FAILED', resolveAuthContext)
  const collectCandidate = async () => {
    const inventory = await datahubSourceStage('INVENTORY', currentInventory, sourceRetryWait)
    const projection = await datahubSourceStage('INVENTORY_PROJECTION', inventoryProjection, sourceRetryWait)
    const [lineageSource, metadataSource, datahubIdentity] = await Promise.all([
      datahubSourceStage(
        'LINEAGE_COLLECTION',
        () => collectLineage(liveAuth.authorityPin, inventory),
        sourceRetryWait,
      ),
      datahubSourceStage(
        'METADATA_COLLECTION',
        ({ attempt }) => collectMetadata(liveAuth.authorityPin, inventory, { retryAttempt: attempt }),
        sourceRetryWait,
      ),
      datahubSourceStage('RUNTIME_IDENTITY', runtimeIdentity, sourceRetryWait),
    ])
    const identity = await k9RefreshStage('K9_SOURCE_SNAPSHOT_FAILED', () => sourceIdentity({
      inventoryProjection: projection,
      datahubIdentity,
      lineageSource,
      metadataSource,
    }))
    const sourceSnapshotId = identity?.snapshot?.source_snapshot_id || identity?.source_fingerprint_id
    if (typeof sourceSnapshotId !== 'string' || !/^[0-9a-f]{64}$/.test(sourceSnapshotId)) {
      throw Object.assign(new Error('K9_SOURCE_SNAPSHOT_FAILED'), {
        k9FailureCode: 'K9_SOURCE_SNAPSHOT_FAILED',
      })
    }
    return {
      inventory, projection, lineageSource, metadataSource, datahubIdentity,
      identity, sourceSnapshotId,
    }
  }

  let priorCandidate = await collectCandidate()
  let stableCandidate
  for (let comparison = 1; comparison <= SOURCE_CONSISTENCY_MAX_COMPARISONS; comparison += 1) {
    const nextCandidate = await collectCandidate()
    if (priorCandidate.sourceSnapshotId === nextCandidate.sourceSnapshotId) {
      stableCandidate = nextCandidate
      break
    }
    priorCandidate = nextCandidate
    if (comparison < SOURCE_CONSISTENCY_MAX_COMPARISONS) {
      try {
        await sourceRetryWait(SOURCE_CONSISTENCY_RETRY_DELAY_MS, {
          failureStage: 'SOURCE_CONSISTENCY',
          failureDetailCode: 'SOURCE_DRIFT',
          attempt: comparison,
        })
      } catch {
        // Retry-clock failures never expose provider details or permit a
        // mixed candidate to be promoted.
      }
    }
  }
  if (!stableCandidate) {
    throw Object.assign(new Error('K9_SOURCE_DRIFT_RETRY_EXHAUSTED'), {
      k9FailureCode: 'K9_SOURCE_DRIFT_RETRY_EXHAUSTED',
    })
  }
  return Object.freeze({ liveAuth, ...stableCandidate })
}

/**
 * Captures one source-only immutable V2 snapshot after the existing two-candidate consistency
 * fence. An interrupted persisted capture is reconstructed from its already-normalized payloads;
 * no DataHub call is made in that resume path.
 */
export function createPocK9SourceCaptureTask({
  resolveAuthContext,
  currentInventory,
  inventoryProjection,
  collectLineage,
  collectMetadata,
  runtimeIdentity,
  buildSourceCapture,
  sourceRetryWait = defaultSourceRetryWait,
} = {}) {
  const requiredFunctions = [
    resolveAuthContext, currentInventory, inventoryProjection, collectLineage,
    collectMetadata, runtimeIdentity, buildSourceCapture, sourceRetryWait,
  ]
  if (requiredFunctions.some((value) => typeof value !== 'function')) {
    throw new Error('The POC K9 source capture dependencies are incomplete.')
  }
  return async function captureK9Source({ currentReceipt } = {}) {
    if (currentReceipt && ['PENDING', 'RUNNING'].includes(currentReceipt.status)
      && currentReceipt.source_snapshot?.source_snapshot_id === currentReceipt.source_snapshot_id
      && currentReceipt.source_payloads) {
      return Object.freeze({ ...currentReceipt, status: 'READY' })
    }
    const captured = await collectStableK9Source({
      resolveAuthContext,
      currentInventory,
      inventoryProjection,
      collectLineage,
      collectMetadata,
      runtimeIdentity,
      sourceIdentity: buildSourceCapture,
      sourceRetryWait,
    })
    const sourceCapture = captured.identity
    if (!sourceCapture?.snapshot || !sourceCapture?.source_payloads
      || sourceCapture.snapshot.source_snapshot_id !== captured.sourceSnapshotId) {
      throw Object.assign(new Error('K9_SOURCE_SNAPSHOT_FAILED'), {
        k9FailureCode: 'K9_SOURCE_SNAPSHOT_FAILED',
      })
    }
    return Object.freeze({
      status: 'READY',
      source_snapshot_id: captured.sourceSnapshotId,
      source_snapshot: sourceCapture.snapshot,
      source_payloads: sourceCapture.source_payloads,
      // This execution-only context is deliberately ignored by the durable receipt port.
      // It permits the legacy caller to retain its current behavior during additive adoption.
      capture_context: Object.freeze({
        liveAuth: captured.liveAuth,
        inventory: captured.inventory,
        projection: captured.projection,
        lineageSource: captured.lineageSource,
        metadataSource: captured.metadataSource,
        datahubIdentity: captured.datahubIdentity,
      }),
    })
  }
}

export function createPocK9RefreshTask({
  resolveAuthContext,
  currentInventory,
  inventoryProjection,
  collectLineage,
  collectMetadata,
  runtimeIdentity,
  ensureSemanticIndex,
  sourceFingerprint,
  buildSourceSnapshot,
  managedGraphs,
  sourceRetryWait = defaultSourceRetryWait,
} = {}) {
  const requiredFunctions = [
    resolveAuthContext,
    currentInventory,
    inventoryProjection,
    collectLineage,
    collectMetadata,
    runtimeIdentity,
    ensureSemanticIndex,
    sourceFingerprint,
    buildSourceSnapshot,
    managedGraphs?.recordRefreshFailure,
    managedGraphs?.triggerLineagePublish,
    managedGraphs?.triggerGlossaryPublish,
    sourceRetryWait,
  ]
  if (requiredFunctions.some((value) => typeof value !== 'function')) {
    throw new Error('The POC K9 refresh task dependencies are incomplete.')
  }

  return async function triggerK9Refresh() {
    let lineage
    let glossary
    let unfinishedIntents = [...canonicalManagedIntents]

    const failure = async (candidateCode, candidateDiagnostic) => {
      let failureCode = boundedK9FailureCode(candidateCode)
      const sourceDiagnostic = failureCode === 'K9_DATAHUB_SOURCE_FAILED'
        && supportedSourceFailureStages.has(candidateDiagnostic?.failureStage)
        && supportedSourceFailureDetails.has(candidateDiagnostic?.failureDetailCode)
        ? {
            failureStage: candidateDiagnostic.failureStage,
            failureDetailCode: candidateDiagnostic.failureDetailCode,
            ...(candidateDiagnostic.failureStage === 'METADATA_COLLECTION'
              && sanitizeK9MetadataSourceProfile(candidateDiagnostic.metadataProfile)
              ? { metadataProfile: sanitizeK9MetadataSourceProfile(candidateDiagnostic.metadataProfile) }
              : {}),
          }
        : null
      try {
        if (unfinishedIntents.length) {
          if (sourceDiagnostic) {
            await managedGraphs.recordRefreshFailure(failureCode, unfinishedIntents, sourceDiagnostic)
          } else {
            await managedGraphs.recordRefreshFailure(failureCode, unfinishedIntents)
          }
        }
      } catch {
        failureCode = 'K9_FAILURE_STATE_PERSISTENCE_FAILED'
      }
      return {
        status: 'FAILURE',
        reason: failureCode,
        failureCode,
        ...(sourceDiagnostic && failureCode === 'K9_DATAHUB_SOURCE_FAILED' ? sourceDiagnostic : {}),
        lineage,
        glossary,
      }
    }

    try {
      const stableCandidate = await collectStableK9Source({
        resolveAuthContext,
        currentInventory,
        inventoryProjection,
        collectLineage,
        collectMetadata,
        runtimeIdentity,
        sourceIdentity: sourceFingerprint,
        sourceRetryWait,
      })
      const {
        liveAuth,
        inventory,
        projection,
        lineageSource,
        metadataSource,
        datahubIdentity,
      } = stableCandidate
      // A failed source read must not promote a semantic generation that the
      // managed graph LKG cannot reference. Promote only after every fixed
      // DataHub source stage has completed successfully.
      const semanticIndex = await k9RefreshStage(
        'K9_SEMANTIC_INDEX_FAILED',
        () => ensureSemanticIndex(inventory, projection),
      )
      const sourceSnapshot = await k9RefreshStage('K9_SOURCE_SNAPSHOT_FAILED', () => buildSourceSnapshot({
        inventoryProjection: projection,
        datahubIdentity,
        lineageSource,
        metadataSource,
        semanticIndex,
      }))
      lineageSource.source_snapshot = sourceSnapshot
      metadataSource.source_snapshot = sourceSnapshot

      lineage = await k9RefreshStage('K9_LINEAGE_REFRESH_FAILED', () => (
        managedGraphs.triggerLineagePublish(liveAuth, async () => lineageSource)
      ))
      if (lineage?.status === 'FAILURE') {
        unfinishedIntents = ['data-glossary']
        return await failure(lineage.failureCode)
      }

      unfinishedIntents = ['data-glossary']
      glossary = await k9RefreshStage('K9_METADATA_REFRESH_FAILED', () => (
        managedGraphs.triggerGlossaryPublish(liveAuth, async () => metadataSource)
      ))
      if (glossary?.status === 'FAILURE') {
        // triggerGlossaryPublish already finalized its own durable run.
        unfinishedIntents = []
        return await failure(glossary.failureCode)
      }

      return {
        status: 'SUCCESS',
        source_snapshot: sourceSnapshot,
        semantic_index: semanticIndex,
        ...(sanitizeK9MetadataSourceProfile(metadataSource.source_profile)
          ? { metadataProfile: sanitizeK9MetadataSourceProfile(metadataSource.source_profile) }
          : {}),
        lineage,
        glossary,
      }
    } catch (error) {
      return await failure(error?.k9FailureCode, error?.k9SourceDiagnostic)
    }
  }
}

export function k9SemanticReconciliationGeneration(semanticGeneration, managedGraphAssets) {
  if (semanticGeneration == null) return null
  if (typeof semanticGeneration !== 'string' || !/^[0-9a-f]{64}$/.test(semanticGeneration)) {
    throw new Error('The active K9 semantic generation is invalid.')
  }
  if (!Array.isArray(managedGraphAssets)) {
    throw new Error('The managed K9 graph generation snapshot is unavailable.')
  }
  const aligned = canonicalManagedIntents.every((managedIntent) => {
    const matches = managedGraphAssets.filter((row) => row?.managed_intent === managedIntent)
    return matches.length === 1
      && Boolean(matches[0].active_release_pointer)
      && matches[0].active_manifest?.source_snapshot?.catalog_generation === semanticGeneration
  })
  return aligned ? null : semanticGeneration
}

export function loadPocK9SchedulerConfig(environment = process.env) {
  const requested = parseBoolean(environment.POC_K9_SCHEDULER_ENABLED, false)
  const systemSubjectId = environment.POC_K9_SYSTEM_SUBJECT_ID?.trim()
  const workspaceId = environment.POC_K9_WORKSPACE_ID?.trim()
  const timeZone = environment.POC_K9_SCHEDULER_TIME_ZONE?.trim() || DEFAULT_TIME_ZONE
  const refreshMode = (environment.POC_K9_REFRESH_MODE?.trim().toUpperCase() || DEFAULT_REFRESH_MODE)
  const scheduleHour = boundedInteger(environment.POC_K9_SCHEDULE_HOUR, DEFAULT_SCHEDULE_HOUR, 0, 23, 'POC_K9_SCHEDULE_HOUR')
  const scheduleMinute = boundedInteger(environment.POC_K9_SCHEDULE_MINUTE, DEFAULT_SCHEDULE_MINUTE, 0, 59, 'POC_K9_SCHEDULE_MINUTE')
  const classificationCeiling = environment.POC_K9_CLASSIFICATION_CEILING?.trim().toUpperCase() || 'INTERNAL'

  if (requested) {
    if (!systemSubjectId || !workspaceId) {
      throw new Error('K9 scheduler is enabled but required K9 subject or workspace configuration is missing')
    }
  }

  validateTimeZone(timeZone)
  if (!supportedRefreshModes.has(refreshMode)) throw new Error('POC_K9_REFRESH_MODE must be DAILY, HOURLY, MANUAL, or EVENT_DRIVEN.')
  if (!supportedClassificationCeilings.has(classificationCeiling)) {
    throw new Error('POC_K9_CLASSIFICATION_CEILING must be PUBLIC, INTERNAL, CONFIDENTIAL, or RESTRICTED.')
  }

  const timerEnabled = requested && ['DAILY', 'HOURLY'].includes(refreshMode)
  const schedule = refreshMode === 'DAILY'
    ? `${String(scheduleHour).padStart(2, '0')}:${String(scheduleMinute).padStart(2, '0')} ${timeZone}`
    : refreshMode === 'HOURLY'
      ? `hourly at minute ${String(scheduleMinute).padStart(2, '0')} ${timeZone}`
      : refreshMode

  return Object.freeze({
    enabled: timerEnabled,
    requested,
    disabledReason: !requested ? 'DISABLED' : (!timerEnabled ? `${refreshMode}_ONLY` : null),
    refreshMode,
    scheduleHour,
    scheduleMinute,
    schedule,
    classificationCeiling,
    timeZone,
    lockName: DEFAULT_LOCK_NAME,
    systemSubjectId,
    workspaceId,
  })
}

export function createPocK9Scheduler({
  config = loadPocK9SchedulerConfig(),
  stateStore,
  triggerK9Refresh,
  clock = () => new Date(),
  setTimer = setTimeout,
  clearTimer = clearTimeout,
  onError = () => undefined,
  resolveReconciliationGeneration = async () => null,
} = {}) {
  if (!stateStore || typeof stateStore.runK9Scheduler !== 'function') {
    throw new Error('The POC K9 scheduler state store is unavailable.')
  }
  if (config.requested && (!stateStore.configured?.postgres || typeof triggerK9Refresh !== 'function')) {
    throw new Error('The configured POC K9 refresh policy requires PostgreSQL and the refresh trigger.')
  }
  if (typeof resolveReconciliationGeneration !== 'function') {
    throw new Error('The POC K9 semantic reconciliation resolver is invalid.')
  }

  let timer
  let stopped = false
  let activeRun
  let activeAttempt
  let activeReconciliationGeneration = null
  let pendingReconciliation
  let pendingReconciliationRun

  const updateProgress = (value) => {
    if (!activeAttempt || !value || typeof value !== 'object' || Array.isArray(value)) return false
    const integer = (candidate) => Number.isSafeInteger(candidate) && candidate >= 0 ? candidate : 0
    const providerClass = [
      'CONNECTIVITY', 'TIMEOUT', 'HTTP_4XX', 'HTTP_5XX', 'HTTP_OTHER',
      'GRAPHQL', 'CONTRACT',
    ].includes(value.provider_failure_class) ? value.provider_failure_class : null
    activeAttempt = Object.freeze({
      ...activeAttempt,
      stage: 'METADATA_COLLECTION',
      detail: 'DIRECT_GLOSSARY_RESOLUTION',
      direct_resolution_total: integer(value.total),
      batch_size: integer(value.batch_size),
      batch_total: integer(value.batch_total),
      batch_number: integer(value.batch_number),
      batch_requested_count: integer(value.batch_requested_count),
      batch_response_count: integer(value.batch_response_count),
      batch_elapsed_ms: integer(value.batch_elapsed_ms),
      completed_resolution_count: integer(value.completed_resolution_count),
      dangling_unique_terms: integer(value.dangling_unique_terms),
      dangling_assignment_references: integer(value.dangling_assignment_references),
      retry_attempt: integer(value.retry_attempt),
      provider_failure_class: providerClass,
    })
    return true
  }

  const updateLifecycleProgress = (value) => {
    if (!activeAttempt || !value || typeof value !== 'object' || Array.isArray(value)) return false
    const projectorId = ['LINEAGE', 'METADATA', 'SEMANTIC'].includes(value.projector_id)
      ? value.projector_id
      : null
    const status = ['RUNNING', 'READY', 'FAILED'].includes(value.status) ? value.status : null
    const stage = value.stage === 'SOURCE'
      ? 'SOURCE_CAPTURE'
      : value.stage === 'PROJECTOR' && projectorId
        ? `${projectorId}_PROJECTOR`
        : value.stage === 'READINESS' ? 'AGGREGATE_READINESS' : null
    if (!stage || !status) return false
    const diagnosticCode = typeof value.diagnostic?.code === 'string'
      && /^[A-Z][A-Z0-9_]{0,95}$/.test(value.diagnostic.code)
      ? value.diagnostic.code
      : null
    const diagnosticDetail = typeof value.diagnostic?.failure_detail_code === 'string'
      && /^[A-Z][A-Z0-9_]{0,95}$/.test(value.diagnostic.failure_detail_code)
      ? value.diagnostic.failure_detail_code
      : diagnosticCode
    const staleMetadataFields = new Set([
      'stage', 'detail', 'projector_id', 'failure_detail_code', 'direct_resolution_total',
      'batch_size', 'batch_total', 'batch_number', 'batch_requested_count',
      'batch_response_count', 'batch_elapsed_ms', 'completed_resolution_count',
      'dangling_unique_terms', 'dangling_assignment_references', 'retry_attempt',
      'provider_failure_class',
    ])
    const baseAttempt = Object.fromEntries(Object.entries(activeAttempt)
      .filter(([key]) => !staleMetadataFields.has(key)))
    activeAttempt = Object.freeze({
      ...baseAttempt,
      stage,
      detail: projectorId ? `${projectorId}_${status}` : status,
      ...(projectorId ? { projector_id: projectorId } : {}),
      ...(diagnosticDetail ? { failure_detail_code: diagnosticDetail } : {}),
    })
    return true
  }

  const execute = async (
    scheduledFor,
    trigger,
    reconciliationGeneration,
    lifecycleMode,
  ) => stateStore.runK9Scheduler({
    lockName: config.lockName,
    scheduledFor: scheduledFor.toISOString(),
    trigger,
    ...(reconciliationGeneration ? { reconciliationGeneration } : {}),
  }, async () => {
    return await triggerK9Refresh({
      systemSubjectId: config.systemSubjectId,
      workspaceId: config.workspaceId,
      lifecycleMode,
    })
  })

  const trigger = (options = {}) => {
    if (!config.requested) return Promise.resolve({ status: 'disabled', reason: config.disabledReason })
    const scheduledFor = options.scheduledFor === undefined
      ? currentScheduleBoundary(clock(), config.timeZone, config.scheduleHour, config.scheduleMinute, config.refreshMode)
      : validScheduleBoundary(options.scheduledFor, config)
    const triggerType = options.trigger === 'manual' ? 'manual' : 'scheduled'
    const lifecycleMode = options.lifecycleMode === 'RESUME' ? 'RESUME' : 'REFRESH'
    const reconciliationGeneration = options.reconciliationGeneration == null
      ? null
      : options.reconciliationGeneration
    if (reconciliationGeneration !== null
      && (typeof reconciliationGeneration !== 'string' || !/^[0-9a-f]{64}$/.test(reconciliationGeneration))) {
      throw new Error('The requested K9 semantic reconciliation generation is invalid.')
    }

    if (!activeRun) {
      activeReconciliationGeneration = reconciliationGeneration
      activeAttempt = Object.freeze({
        status: 'RUNNING',
        scheduled_for: scheduledFor.toISOString(),
        trigger: triggerType,
      })
      activeRun = execute(
        scheduledFor, triggerType, reconciliationGeneration, lifecycleMode,
      ).finally(() => {
        activeRun = undefined
        activeAttempt = undefined
        activeReconciliationGeneration = null
      })
    }
    return activeRun
  }

  const reconciliationRequest = (reconciliationGeneration) => ({
    scheduledFor: config.enabled
      ? currentScheduleBoundary(clock(), config.timeZone, config.scheduleHour, config.scheduleMinute, config.refreshMode)
      : clock(),
    trigger: config.enabled ? 'scheduled' : 'manual',
    reconciliationGeneration,
  })

  const drainPendingReconciliation = async (predecessor) => {
    try {
      try {
        await predecessor
      } catch {
        // A newer observed semantic generation must be reconciled even when
        // the run it superseded failed.
      }
      let result
      while (pendingReconciliation) {
        const requested = pendingReconciliation
        const reconciliationGeneration = await resolveReconciliationGeneration()
        if (pendingReconciliation !== requested) continue
        pendingReconciliation = undefined
        if (!reconciliationGeneration) {
          result = { status: 'already_aligned' }
          continue
        }
        try {
          result = await trigger({
            ...requested.request,
            reconciliationGeneration,
          })
        } catch (error) {
          if (!pendingReconciliation) throw error
        }
      }
      return result
    } finally {
      pendingReconciliationRun = undefined
    }
  }

  const triggerReconciliation = (reconciliationGeneration) => {
    const request = reconciliationRequest(reconciliationGeneration)
    if (activeRun && activeReconciliationGeneration === reconciliationGeneration) return activeRun
    if (!activeRun && !pendingReconciliationRun) return trigger(request)

    if (pendingReconciliation?.candidateGeneration !== reconciliationGeneration) {
      pendingReconciliation = { candidateGeneration: reconciliationGeneration, request }
    }
    if (!pendingReconciliationRun) {
      pendingReconciliationRun = drainPendingReconciliation(activeRun)
    }
    return pendingReconciliationRun
  }

  const scheduleNext = () => {
    if (stopped || !config.enabled) return
    const now = clock()
    const next = nextScheduleBoundary(now, config.timeZone, config.scheduleHour, config.scheduleMinute, config.refreshMode)
    const delay = Math.min(Math.max(1, next.getTime() - now.getTime()), MAX_TIMER_DELAY_MS)
    timer = setTimer(async () => {
      timer = undefined
      try {
        if (delay < next.getTime() - clock().getTime()) return scheduleNext()
        await trigger({ scheduledFor: next, trigger: 'scheduled' })
      } catch (error) {
        onError(error)
      } finally {
        scheduleNext()
      }
    }, delay)
  }

  return {
    config,
    updateProgress,
    updateLifecycleProgress,
    currentAttempt() {
      return activeAttempt || null
    },
    async start() {
      if (stopped || !config.requested) return { status: 'disabled', reason: config.disabledReason }
      if (!config.enabled) return { status: 'idle', mode: config.refreshMode }
      let reconciliationGeneration = null
      try {
        reconciliationGeneration = await resolveReconciliationGeneration()
      } catch (error) {
        onError(error)
      }
      void trigger({
        trigger: 'scheduled',
        // The scheduler receipt suppresses a same-boundary deploy replay before
        // this callback runs. When a new schedule boundary is genuinely due,
        // retain REFRESH so source drift is still discovered. Incomplete V2
        // lifecycles independently reuse their immutable source receipt.
        lifecycleMode: 'REFRESH',
        reconciliationGeneration,
      }).catch(onError)
      scheduleNext()
      return { status: 'started' }
    },
    async reconcileSemanticGeneration(candidateGeneration) {
      if (stopped || !config.requested) return { status: 'disabled', reason: config.disabledReason }
      const reconciliationGeneration = await resolveReconciliationGeneration(candidateGeneration)
      if (!reconciliationGeneration) return { status: 'already_aligned' }
      return triggerReconciliation(reconciliationGeneration)
    },
    triggerManual(scheduledFor) {
      return trigger({ scheduledFor, trigger: 'manual' })
    },
    async stop() {
      stopped = true
      if (timer !== undefined) clearTimer(timer)
      timer = undefined
      await (pendingReconciliationRun || activeRun)
    },
  }
}

export function currentScheduleBoundary(
  now,
  timeZone = DEFAULT_TIME_ZONE,
  hour = DEFAULT_SCHEDULE_HOUR,
  minute = DEFAULT_SCHEDULE_MINUTE,
  refreshMode = DEFAULT_REFRESH_MODE,
) {
  if (refreshMode === 'HOURLY') return hourlyBoundary(now, timeZone, minute)
  if (refreshMode !== 'DAILY') throw new Error('The configured refresh mode does not have a timer boundary.')
  const currentBoundary = boundaryOfZonedDate(zonedDate(now, timeZone), timeZone, hour, minute)
  if (now.getTime() < currentBoundary.getTime()) {
    // If it is before today's configured time, use yesterday's boundary.
    const yesterday = new Date(currentBoundary.getTime() - 24 * 60 * 60 * 1000)
    return boundaryOfZonedDate(zonedDate(yesterday, timeZone), timeZone, hour, minute)
  }
  return currentBoundary
}

export function nextScheduleBoundary(
  now,
  timeZone = DEFAULT_TIME_ZONE,
  hour = DEFAULT_SCHEDULE_HOUR,
  minute = DEFAULT_SCHEDULE_MINUTE,
  refreshMode = DEFAULT_REFRESH_MODE,
) {
  const current = currentScheduleBoundary(now, timeZone, hour, minute, refreshMode)
  if (refreshMode === 'HOURLY') return new Date(current.getTime() + 60 * 60 * 1000)
  // Resolve tomorrow in the configured zone rather than assuming a fixed DST day.
  const tomorrow = new Date(current.getTime() + 25 * 60 * 60 * 1000)
  return boundaryOfZonedDate(zonedDate(tomorrow, timeZone), timeZone, hour, minute)
}

function validScheduleBoundary(value, config) {
  const date = value instanceof Date ? new Date(value) : new Date(value)
  if (!Number.isFinite(date.getTime())) throw new Error('The manual scheduler timestamp is invalid.')
  if (['MANUAL', 'EVENT_DRIVEN'].includes(config.refreshMode)) return date
  const boundary = currentScheduleBoundary(
    date,
    config.timeZone,
    config.scheduleHour,
    config.scheduleMinute,
    config.refreshMode,
  )
  if (boundary.getTime() !== date.getTime()) {
    throw new Error('A manual scheduler timestamp must be an exact configured refresh boundary.')
  }
  return date
}

function boundaryOfZonedDate(target, timeZone, hour = DEFAULT_SCHEDULE_HOUR, minute = DEFAULT_SCHEDULE_MINUTE) {
  validateTimeZone(timeZone)
  const targetKey = dateKey(target)
  const center = Date.UTC(target.year, target.month - 1, target.day, hour)
  let low = center - 36 * 60 * 60 * 1000
  let high = center + 36 * 60 * 60 * 1000
  while (high - low > 1) {
    const middle = Math.floor((low + high) / 2)
    const zDate = zonedDate(new Date(middle), timeZone)
    const dKey = dateKey(zDate)
    const zTime = zonedTime(new Date(middle), timeZone)
    if (dKey < targetKey || (dKey === targetKey && (zTime.hour < hour || (zTime.hour === hour && zTime.minute < minute)))) low = middle
    else high = middle
  }
  const result = new Date(high)
  const resolvedTime = zonedTime(result, timeZone)
  if (dateKey(zonedDate(result, timeZone)) !== targetKey || resolvedTime.hour !== hour || resolvedTime.minute !== minute) {
    throw new Error('The configured time zone cannot resolve the requested schedule date.')
  }
  return result
}

function hourlyBoundary(value, timeZone, minute) {
  const parts = zonedDateTime(value, timeZone)
  let boundary = boundaryOfZonedDate(parts, timeZone, parts.hour, minute)
  if (boundary.getTime() > value.getTime()) boundary = new Date(boundary.getTime() - 60 * 60 * 1000)
  return boundary
}

function zonedTime(value, timeZone) {
  const parts = zonedDateTime(value, timeZone)
  return { hour: parts.hour, minute: parts.minute }
}

function zonedDateTime(value, timeZone) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: 'numeric',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(value)
  const get = (type) => Number(parts.find((part) => part.type === type)?.value)
  return {
    year: get('year'),
    month: get('month'),
    day: get('day'),
    hour: get('hour') % 24,
    minute: get('minute'),
  }
}

function zonedDate(value, timeZone) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone, year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(value)
  const get = (type) => Number(parts.find((part) => part.type === type)?.value)
  return { year: get('year'), month: get('month'), day: get('day') }
}

function dateKey({ year, month, day }) {
  return year * 10_000 + month * 100 + day
}

function validateTimeZone(timeZone) {
  try {
    new Intl.DateTimeFormat('en-US', { timeZone }).format(new Date(0))
  } catch {
    throw new Error('POC_K9_SCHEDULER_TIME_ZONE must be a valid IANA time zone.')
  }
}

function parseBoolean(raw, fallback) {
  if (raw === undefined || raw === null || String(raw).trim() === '') return fallback
  if (String(raw).trim().toLowerCase() === 'true') return true
  if (String(raw).trim().toLowerCase() === 'false') return false
  throw new Error('POC_K9_SCHEDULER_ENABLED must be true or false.')
}

function boundedInteger(raw, fallback, minimum, maximum, name) {
  if (raw === undefined || raw === null || String(raw).trim() === '') return fallback
  const value = Number(raw)
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    throw new Error(`${name} must be an integer from ${minimum} through ${maximum}.`)
  }
  return value
}
