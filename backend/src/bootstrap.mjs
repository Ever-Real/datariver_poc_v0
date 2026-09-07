/* global AbortController, clearTimeout */
import { createHmac, createHash, randomUUID, timingSafeEqual } from 'node:crypto'
import { createReadStream, existsSync, readFileSync, statSync } from 'node:fs'
import { createServer } from 'node:http'
import { extname, join, normalize, resolve, sep } from 'node:path'
import { performance } from 'node:perf_hooks'
import process from 'node:process'
import { fileURLToPath, URL } from 'node:url'
import { inflateRawSync } from 'node:zlib'
import { createPocStateStore } from './infrastructure/state-store.mjs'
import {
  AIRFLOW_EXECUTION_SCOPE,
  AIRFLOW_SYSTEM_ID,
  ALLOWED_AIRFLOW_DAGS,
  collectAllowedAirflowDagStatuses,
  createAirflowControlStore,
  normalizeAirflowDagStatus,
  normalizeAirflowRun,
  projectAirflowConnectionStatus,
} from './infrastructure/airflow-control.mjs'
import {
  changeHistoryAccessCoreProjection,
  changeHistoryDocumentFromSnapshot,
  normalizeChangeHistoryAccessDocument,
  normalizeSecurityGrade,
  privateChangeHistoryAccess,
  requireActiveAccessAdmin,
} from './modules/auth/access-document.mjs'
import {
  authenticatedPocProfile,
  createPocLocalAuthenticator,
  hashPocPassword,
  normalizePocUsername,
} from './modules/auth/local-auth.mjs'
import {
  assertPocRouteAuthorization,
  assertRegistrationAssetMutation,
  authorizationProjection,
  authorizeCoreReplacement,
  buildPocPrincipal,
  canReadAsset,
  canReadRegistrationAsset,
  filterAssetsForPrincipal,
  filterCoreStateForPrincipal,
  getAllowedTableUrnsScope,
  resolvePocRoute,
} from './modules/auth/authorization.mjs'
import {
  createPocChangeHistoryScheduler,
  loadPocChangeHistorySchedulerConfig,
  persistMclRuntimeFailure,
} from './modules/mcl/change-history-scheduler.mjs'
import {
  isMclRuntimeClassification,
  sanitizeMclRecordShape,
} from './modules/mcl/runtime-failure.mjs'
import {
  buildK9GlossaryScrollVariables,
  createK9ManagedGraphs,
  graphReadBackMatches,
  k9GraphAssetDefinition,
} from './modules/k9/managed-graphs.mjs'
import {
  createPocK9Scheduler,
  createPocK9SourceCaptureTask,
  loadPocK9SchedulerConfig,
  nextScheduleBoundary,
} from './modules/k9/scheduler.mjs'
import {
  buildDatahubKnowledgeSourceCapture,
  buildK9SourceInventoryProjection,
} from './modules/k9/source-snapshot.mjs'
import {
  sanitizeK9SourceEligibilityTelemetry,
  selectCanonicalK9SourceInventory,
} from './modules/k9/source-eligibility.mjs'
import { createK9GraphProjectors } from './modules/k9/graph-projector.mjs'
import {
  createK9V2LifecycleReceiptPort,
  publicK9V2LifecycleStatus,
} from './modules/k9/lifecycle-runtime.mjs'
import {
  K9_V2_FAILURE_CODES,
  K9_V2_SOURCE_RUN_MODES,
  sanitizeK9V2FailureDiagnostic,
} from './modules/k9/lifecycle-v2.mjs'
import { createK9V2SemanticLifecycleProjector } from './modules/k9/semantic-runtime.mjs'
import { createPocK9V2RefreshTask } from './modules/k9/v2-refresh.mjs'
import {
  createK9MetadataCollector,
  K9_METADATA_FAILURE_DETAILS,
  normalizeDatahubTagReferences,
  sanitizeK9MetadataSourceProfile,
} from './modules/k9/metadata-collection.mjs'
import {
  createK9LineageTrace,
  K9_LINEAGE_FAILURE_DETAILS,
  sanitizeK9LineageSourceProfile,
} from './modules/k9/lineage-collection.mjs'
import {
  createProviderTransport,
  joinProviderUrl,
  llmEndpoint,
} from './infrastructure/provider-transport.mjs'
import {
  POC_TABLE_SYSTEM_MAPPING_SCOPE,
  activeSystemIdsForTable,
  applyTableSystemMappingCommand,
  normalizeTableSystemMappingDocument,
  securityGradeRank,
  tableAuthoritySnapshot,
  legacyTableTagGrade,
  tableSystemCandidates,
} from './modules/governance/table-system-mappings.mjs'
import {
  POC_CATALOG_EXPORT_MAXIMUM_ROWS,
  createPocCatalogExportStore,
} from './modules/catalog/catalog-export.mjs'
import {
  applyFinalLane,
  applyTestRun,
  applyTransition,
  applyWorkflowLane,
  assertCrTableAccess,
  assertCrWorkflowAction,
  crResponsibleSystemId,
  resolveNewCrResponsibleSystem,
} from './modules/governance/cr-lifecycle.mjs'
import {
  DATAHUB_DATASET_CURRENTNESS_REASONS,
  classifyCurrentDatahubDataset,
  datahubDatasetKind,
  isCurrentDatahubTable,
} from './modules/catalog/datahub-current-table.mjs'
import { isCanonicalDatahubDatasetUrn, tablePolicyCellKey } from './modules/auth/table-data-access.mjs'
import {
  POC_FEATURE_SECURITY_POLICY_SCOPE,
  applyFeatureSecurityPolicyUpdate,
  approvedDefaultFeatureSecurityPolicy,
  featureSecurityAllowed,
  normalizePersistedFeatureSecurityPolicy,
} from './modules/auth/feature-security-policy.mjs'
import {
  boundedLlmProviderDiagnostic,
  boundedLlmProviderFailureCode,
  llmProviderFailureCodes,
  llmProviderFailureStages,
  parseLlmProviderTimeoutMs,
  routingClassifierCompletionTokenBudget,
} from './modules/chat/llm-timeout.mjs'
import {
  POC_SITE_BRANDING_SCOPE,
  applySiteBrandingUpdate,
  normalizeSiteBrandingDocument,
  publicSiteBranding,
  siteBrandingIdempotencyHash,
  siteBrandingRequestHash,
} from './modules/admin/site-branding.mjs'

export { currentDatahubDatasetExists } from './modules/catalog/datahub-current-table.mjs'
export {
  buildDatahubKnowledgeSourceFingerprint,
  buildDatahubKnowledgeSourceSnapshot,
} from './modules/k9/source-snapshot.mjs'

import { createModulesMonitoringApplication } from './modules/monitoring/application.mjs'
import { createInterfacesHttpRequest } from './interfaces/http/request.mjs'
import { createModulesMclChangeHistory } from './modules/mcl/change-history.mjs'
import { createInfrastructureProvider } from './infrastructure/provider.mjs'
import { createModulesCatalogApplication } from './modules/catalog/application.mjs'
import { createInfrastructureAirflow } from './infrastructure/airflow.mjs'
import { createModulesChatApplication } from './modules/chat/application.mjs'
import { createInfrastructureMinio } from './infrastructure/minio.mjs'
import { createModulesRegistrationApplication } from './modules/registration/application.mjs'
import { createInfrastructureNeo4j } from './infrastructure/neo4j.mjs'
import { createModulesKnowledgeApplication } from './modules/knowledge/application.mjs'
import { createModulesK9ReadModel } from './modules/k9/read-model.mjs'
import { createModulesAuthHttp } from './modules/auth/http.mjs'
import { createModulesAdminApplication } from './modules/admin/application.mjs'
import { createModulesGovernanceApplication } from './modules/governance/application.mjs'
import { createInterfacesHttpRouter } from './interfaces/http/router.mjs'
import { createInterfacesHttpStatic } from './interfaces/http/static.mjs'
import { createServerModule } from './server.mjs'

// Lazy bindings preserve shared pool, cache and scheduler state across feature modules.
const {
  monitoringDashboards,
  capabilities,
} = createModulesMonitoringApplication({
  get URL() { return URL },
  get airflow() { return airflow },
  get boundedString() { return boundedString },
  get configuredMonitoringDashboards() { return configuredMonitoringDashboards },
  get datahub() { return datahub },
  get datahubHeaders() { return datahubHeaders },
  get datahubUiUrl() { return datahubUiUrl },
  get detectAirflowApiVersion() { return detectAirflowApiVersion },
  get grafanaEmbedBaseUrl() { return grafanaEmbedBaseUrl },
  get grafanaEmbedEnabled() { return grafanaEmbedEnabled },
  get grafanaEvidenceReference() { return grafanaEvidenceReference },
  get grafanaUiUrl() { return grafanaUiUrl },
  get joinProviderUrl() { return joinProviderUrl },
  get llm() { return llm },
  get llmEndpoint() { return llmEndpoint },
  get llmRequest() { return llmRequest },
  get minio() { return minio },
  get neo4j() { return neo4j },
  get neo4jQuery() { return neo4jQuery },
  get process() { return process },
  get providerFetch() { return providerFetch },
  get requireOk() { return requireOk },
})

const {
  json,
  problem,
  writeEventStream,
  securityHeaders,
  redirectBrowserToCanonicalOrigin,
  unconfiguredPocAuthenticator,
  bodyBuffer,
  bodyJson,
  boundedString,
  accessError,
  hasAccessControlCharacter,
  rejectProtectedAccessClaims,
  rejectProtectedAccessBodyClaims,
  accessIfMatch,
  airflowIdempotencyKey,
  stateIfMatch,
  tableSystemIfMatch,
  featureSecurityPolicyIfMatch,
  siteBrandingIfMatch,
} = createInterfacesHttpRequest({
  get URL() { return URL },
  get configuredMonitoringDashboards() { return configuredMonitoringDashboards },
  get maximumJsonBytes() { return maximumJsonBytes },
  get protectedAccessHeaders() { return protectedAccessHeaders },
  get protectedAccessQueryKeys() { return protectedAccessQueryKeys },
})

const {
  changeHistoryAccess,
  changeHistoryActiveUser,
  changeHistoryPresentation,
  changeHistoryApi,
} = createModulesMclChangeHistory({
  get POC_TABLE_SYSTEM_MAPPING_SCOPE() { return POC_TABLE_SYSTEM_MAPPING_SCOPE },
  get accessError() { return accessError },
  get accessIfMatch() { return accessIfMatch },
  get activeSystemIdsForTable() { return activeSystemIdsForTable },
  get bodyJson() { return bodyJson },
  get boundedString() { return boundedString },
  get canReadAsset() { return canReadAsset },
  get canonicalHash() { return canonicalHash },
  get canonicalJson() { return canonicalJson },
  get changeHistoryAccessCoreProjection() { return changeHistoryAccessCoreProjection },
  get changeHistoryActions() { return changeHistoryActions },
  get changeHistoryCategories() { return changeHistoryCategories },
  get changeHistoryDocumentFromSnapshot() { return changeHistoryDocumentFromSnapshot },
  get changeHistoryOperations() { return changeHistoryOperations },
  get changeHistoryPrecisionValues() { return changeHistoryPrecisionValues },
  get changeHistoryPresentationStages() { return changeHistoryPresentationStages },
  get changeHistoryUnknownCompleteness() { return changeHistoryUnknownCompleteness },
  get crResponsibleSystemId() { return crResponsibleSystemId },
  get datahubInventoryStateScope() { return datahubInventoryStateScope },
  get hasAccessControlCharacter() { return hasAccessControlCharacter },
  get isMclRuntimeClassification() { return isMclRuntimeClassification },
  get json() { return json },
  get normalizeChangeHistoryAccessDocument() { return normalizeChangeHistoryAccessDocument },
  get normalizeTableSystemMappingDocument() { return normalizeTableSystemMappingDocument },
  get privateChangeHistoryAccess() { return privateChangeHistoryAccess },
  get problem() { return problem },
  get process() { return process },
  get rejectProtectedAccessBodyClaims() { return rejectProtectedAccessBodyClaims },
  get rejectProtectedAccessClaims() { return rejectProtectedAccessClaims },
  get requireActiveAccessAdmin() { return requireActiveAccessAdmin },
  get sanitizeMclRecordShape() { return sanitizeMclRecordShape },
  get validDatahubInventory() { return validDatahubInventory },
})

const {
  providerFetch,
  requireOk,
} = createInfrastructureProvider({
  get providerTimeoutMs() { return providerTimeoutMs },
  get providerTransport() { return providerTransport },
})

const {
  datahubGraphql,
  datahubRefreshGraphql,
  datahubRuntimeIdentity,
  datahubHeaders,
  canonicalJson,
  canonicalHash,
  manualMetadataAspectComparableDocument,
  applyManualMetadata,
  urnTail,
  publicDatahubAsset,
  customPropertyReferences,
  structuredPropertyReferences,
  datasetAsset,
  datahubInventory,
  currentDatahubInventory,
  datahubEmbeddingInventory,
  validDatahubInventory,
  startDatahubInventoryRefresh,
  currentDatahubTables,
  datahubCatalog,
  datahubCatalogLocate,
  catalogDatabaseBranchLabel,
  datahubTree,
  datahubFacets,
  datahubDashboard,
  createCatalogExport,
  datahubProfileCoverage,
  datahubSystems,
  datahubGlossaryAssignments,
  glossaryAssignmentCountsFromInventory,
  datahubGlossaryAssignmentBatchCounts,
  reconcileDatahubGlossaryScrollPage,
  datahubGlossary,
  datahubGlossarySmokeTarget,
  datahubSchemaFields,
  datahubCatalogDetailBase,
  datahubCatalogDetailSchema,
  datahubCatalogDetailQuality,
  datahubAssetAll,
  datahubAsset,
  knowledgeCatalogSearch,
  knowledgeCatalogDetail,
  datahubLineageProjectionOptions,
  datahubLineage,
} = createModulesCatalogApplication({
  get DATAHUB_DATASET_CURRENTNESS_REASONS() { return DATAHUB_DATASET_CURRENTNESS_REASONS },
  get accessError() { return accessError },
  get allowedDataHubAspects() { return allowedDataHubAspects },
  get backgroundLaunchesStopped() { return backgroundLaunchesStopped },
  get bodyJson() { return bodyJson },
  get boundedString() { return boundedString },
  get canReadAsset() { return canReadAsset },
  get catalogEmbeddingBindingHash() { return catalogEmbeddingBindingHash },
  get catalogEmbeddingRefreshStartedAt() { return catalogEmbeddingRefreshStartedAt },
  set catalogEmbeddingRefreshStartedAt(value) { catalogEmbeddingRefreshStartedAt = value },
  get catalogEmbeddingSnapshot() { return catalogEmbeddingSnapshot },
  set catalogEmbeddingSnapshot(value) { catalogEmbeddingSnapshot = value },
  get catalogExportClassifications() { return catalogExportClassifications },
  get catalogExportFilterFields() { return catalogExportFilterFields },
  get catalogSearchFieldNames() { return catalogSearchFieldNames },
  get classifyCurrentDatahubDataset() { return classifyCurrentDatahubDataset },
  get createHash() { return createHash },
  get cursorEntries() { return cursorEntries },
  get datahub() { return datahub },
  get datahubAssetQuery() { return datahubAssetQuery },
  get datahubCacheScope() { return datahubCacheScope },
  get datahubCatalogDetailBaseQuery() { return datahubCatalogDetailBaseQuery },
  get datahubCatalogDetailQualityQuery() { return datahubCatalogDetailQualityQuery },
  get datahubCatalogDetailSchemaQuery() { return datahubCatalogDetailSchemaQuery },
  get datahubCurrentEntitiesQuery() { return datahubCurrentEntitiesQuery },
  get datahubCursorTtlMs() { return datahubCursorTtlMs },
  get datahubDatasetKind() { return datahubDatasetKind },
  get datahubEmbeddingInventoryQuery() { return datahubEmbeddingInventoryQuery },
  get datahubGlossaryAssignmentsQuery() { return datahubGlossaryAssignmentsQuery },
  get datahubGlossaryQuery() { return datahubGlossaryQuery },
  get datahubGlossarySmokeDiscoveryQuery() { return datahubGlossarySmokeDiscoveryQuery },
  get datahubGlossarySmokeTargetQuery() { return datahubGlossarySmokeTargetQuery },
  get datahubGlossaryTermByUrnQuery() { return datahubGlossaryTermByUrnQuery },
  get datahubInventoryCacheKey() { return datahubInventoryCacheKey },
  get datahubInventoryFailureRetryMs() { return datahubInventoryFailureRetryMs },
  get datahubInventoryStateScope() { return datahubInventoryStateScope },
  get datahubInventoryTtlMs() { return datahubInventoryTtlMs },
  get datahubLineageQuery() { return datahubLineageQuery },
  get datahubRuntimeIdentityPromise() { return datahubRuntimeIdentityPromise },
  set datahubRuntimeIdentityPromise(value) { datahubRuntimeIdentityPromise = value },
  get filterAssetsForPrincipal() { return filterAssetsForPrincipal },
  get hasAccessControlCharacter() { return hasAccessControlCharacter },
  get inventoryDiagnosticPhases() { return inventoryDiagnosticPhases },
  get inventoryRefreshDiagnostic() { return inventoryRefreshDiagnostic },
  set inventoryRefreshDiagnostic(value) { inventoryRefreshDiagnostic = value },
  get inventoryRefreshFailedAt() { return inventoryRefreshFailedAt },
  set inventoryRefreshFailedAt(value) { inventoryRefreshFailedAt = value },
  get inventoryRefreshLastError() { return inventoryRefreshLastError },
  set inventoryRefreshLastError(value) { inventoryRefreshLastError = value },
  get inventoryRefreshPromise() { return inventoryRefreshPromise },
  set inventoryRefreshPromise(value) { inventoryRefreshPromise = value },
  get inventoryRefreshRetryAt() { return inventoryRefreshRetryAt },
  set inventoryRefreshRetryAt(value) { inventoryRefreshRetryAt = value },
  get inventorySnapshot() { return inventorySnapshot },
  set inventorySnapshot(value) { inventorySnapshot = value },
  get isCanonicalDatahubDatasetUrn() { return isCanonicalDatahubDatasetUrn },
  get isCanonicalDatahubSchemaFieldUrn() { return isCanonicalDatahubSchemaFieldUrn },
  get isCurrentDatahubTable() { return isCurrentDatahubTable },
  get joinProviderUrl() { return joinProviderUrl },
  get legacyTableTagGrade() { return legacyTableTagGrade },
  get llm() { return llm },
  get maximumCatalogQueryTermLength() { return maximumCatalogQueryTermLength },
  get maximumCatalogQueryTerms() { return maximumCatalogQueryTerms },
  get maximumCursorEntries() { return maximumCursorEntries },
  get maximumInventoryPages() { return maximumInventoryPages },
  get maximumJsonBytes() { return maximumJsonBytes },
  get normalizeDatahubTagReferences() { return normalizeDatahubTagReferences },
  get pocStateStore() { return pocStateStore },
  get providerFetch() { return providerFetch },
  get providerTimeoutMs() { return providerTimeoutMs },
  get queueCatalogEmbeddingRefresh() { return queueCatalogEmbeddingRefresh },
  get randomUUID() { return randomUUID },
  get requireOk() { return requireOk },
  get serverBackgroundAbortController() { return serverBackgroundAbortController },
  get sha256() { return sha256 },
  get supportedDatahubClassifications() { return supportedDatahubClassifications },
})

const {
  basicAuthorization,
  detectAirflowApiVersion,
  airflowDagInventory,
  triggerControlledAirflowDag,
  isAirflowTriggerOutcomeUnknown,
  isAirflowDagTransitionOutcomeUnknown,
  bestEffortAirflowReceiptWrite,
  triggerAirflowDag,
  readAirflowDagRun,
  setAirflowDagPaused,
} = createInfrastructureAirflow({
  get airflow() { return airflow },
  get airflowAccessToken() { return airflowAccessToken },
  set airflowAccessToken(value) { airflowAccessToken = value },
  get airflowAccessTokenExpiresAt() { return airflowAccessTokenExpiresAt },
  set airflowAccessTokenExpiresAt(value) { airflowAccessTokenExpiresAt = value },
  get airflowApiVersion() { return airflowApiVersion },
  set airflowApiVersion(value) { airflowApiVersion = value },
  get collectAllowedAirflowDagStatuses() { return collectAllowedAirflowDagStatuses },
  get joinProviderUrl() { return joinProviderUrl },
  get normalizeAirflowDagStatus() { return normalizeAirflowDagStatus },
  get normalizeAirflowRun() { return normalizeAirflowRun },
  get projectAirflowConnectionStatus() { return projectAirflowConnectionStatus },
  get providerFetch() { return providerFetch },
  get providerTimeoutMs() { return providerTimeoutMs },
  get requireOk() { return requireOk },
})

const {
  llmRequest,
  chatMemoryPayload,
  compactChatMemory,
  parseChatRouteDecision,
  datahubChatEvidence,
  catalogEmbeddingBindingHash,
  catalogEmbeddingDocument,
  scheduleCatalogEmbeddingRefresh,
  queueCatalogEmbeddingRefresh,
  catalogEmbeddingStatus,
  metadataMasterCandidateContext,
  managedGraphNodeSupportsDirection,
  publicChatEvidence,
  publicChatDiscovery,
  currentChatDiscovery,
  currentChatHistoryMessages,
  persistedChatMemory,
  persistedChatWorkflow,
  writeApprovedAnswerStream,
  liveChat,
} = createModulesChatApplication({
  get METADATA_MASTER_DATA_NODE_TYPES() { return METADATA_MASTER_DATA_NODE_TYPES },
  get accessError() { return accessError },
  get backgroundLaunchesStopped() { return backgroundLaunchesStopped },
  get boundedLlmProviderDiagnostic() { return boundedLlmProviderDiagnostic },
  get boundedLlmProviderFailureCode() { return boundedLlmProviderFailureCode },
  get boundedString() { return boundedString },
  get canReadAsset() { return canReadAsset },
  get canonicalHash() { return canonicalHash },
  get canonicalJson() { return canonicalJson },
  get catalogEmbeddingBatchSize() { return catalogEmbeddingBatchSize },
  get catalogEmbeddingLastError() { return catalogEmbeddingLastError },
  set catalogEmbeddingLastError(value) { catalogEmbeddingLastError = value },
  get catalogEmbeddingRefreshIntervalMs() { return catalogEmbeddingRefreshIntervalMs },
  get catalogEmbeddingRefreshPromise() { return catalogEmbeddingRefreshPromise },
  set catalogEmbeddingRefreshPromise(value) { catalogEmbeddingRefreshPromise = value },
  get catalogEmbeddingRefreshStartedAt() { return catalogEmbeddingRefreshStartedAt },
  set catalogEmbeddingRefreshStartedAt(value) { catalogEmbeddingRefreshStartedAt = value },
  get catalogEmbeddingRefreshTimer() { return catalogEmbeddingRefreshTimer },
  set catalogEmbeddingRefreshTimer(value) { catalogEmbeddingRefreshTimer = value },
  get catalogEmbeddingSnapshot() { return catalogEmbeddingSnapshot },
  set catalogEmbeddingSnapshot(value) { catalogEmbeddingSnapshot = value },
  get catalogSearchFieldNames() { return catalogSearchFieldNames },
  get chatRouteIntents() { return chatRouteIntents },
  get datahub() { return datahub },
  get datahubAssetAll() { return datahubAssetAll },
  get datahubCacheScope() { return datahubCacheScope },
  get datahubCatalog() { return datahubCatalog },
  get datahubEmbeddingInventory() { return datahubEmbeddingInventory },
  get datahubGraphql() { return datahubGraphql },
  get datahubInventory() { return datahubInventory },
  get datahubInventoryStateScope() { return datahubInventoryStateScope },
  get datahubLineageQuery() { return datahubLineageQuery },
  get datasetAsset() { return datasetAsset },
  get filterAssetsForPrincipal() { return filterAssetsForPrincipal },
  get getAllowedTableUrnsScope() { return getAllowedTableUrnsScope },
  get inventorySnapshot() { return inventorySnapshot },
  get isCanonicalDatahubDatasetUrn() { return isCanonicalDatahubDatasetUrn },
  get k9GraphAssetDefinition() { return k9GraphAssetDefinition },
  get k9V2LifecycleRequested() { return k9V2LifecycleRequested },
  get knowledgeChatScope() { return knowledgeChatScope },
  get knowledgeGraphRag() { return knowledgeGraphRag },
  get knowledgeProjectionError() { return knowledgeProjectionError },
  get llm() { return llm },
  get llmEndpoint() { return llmEndpoint },
  get llmProviderFailureCodes() { return llmProviderFailureCodes },
  get llmProviderFailureStages() { return llmProviderFailureStages },
  get llmProviderTimeoutMs() { return llmProviderTimeoutMs },
  get managedK9Assets() { return managedK9Assets },
  get maximumCatalogQueryTermLength() { return maximumCatalogQueryTermLength },
  get maximumCatalogQueryTerms() { return maximumCatalogQueryTerms },
  get maximumChatEvidenceItems() { return maximumChatEvidenceItems },
  get maximumChatMemoryCharacters() { return maximumChatMemoryCharacters },
  get maximumChatMemorySummaryCharacters() { return maximumChatMemorySummaryCharacters },
  get maximumChatMemoryTurnAnswerCharacters() { return maximumChatMemoryTurnAnswerCharacters },
  get maximumChatMemoryTurnQuestionCharacters() { return maximumChatMemoryTurnQuestionCharacters },
  get maximumChatMemoryTurns() { return maximumChatMemoryTurns },
  get maximumChatQuestionCharacters() { return maximumChatQuestionCharacters },
  get minimumChatDiscoveryItems() { return minimumChatDiscoveryItems },
  get performance() { return performance },
  get pocStateStore() { return pocStateStore },
  get process() { return process },
  get providerFetch() { return providerFetch },
  get publicDatahubAsset() { return publicDatahubAsset },
  get reconcileK9SemanticGeneration() { return reconcileK9SemanticGeneration },
  get routingClassifierCompletionTokenBudget() { return routingClassifierCompletionTokenBudget },
  get serverBackgroundAbortController() { return serverBackgroundAbortController },
  get sha256() { return sha256 },
  get validDatahubInventory() { return validDatahubInventory },
  get writeEventStream() { return writeEventStream },
})

const {
  sha256,
  minioObject,
} = createInfrastructureMinio({
  get URL() { return URL },
  get createHash() { return createHash },
  get createHmac() { return createHmac },
  get minio() { return minio },
  get providerFetch() { return providerFetch },
  get requireOk() { return requireOk },
})

const {
  canReadBulkPreparation,
  bulkPreparationProjection,
  visibleRegistrationCandidates,
  executeBulkPreparation,
  bulkCandidatePreview,
} = createModulesRegistrationApplication({
  get POC_TABLE_SYSTEM_MAPPING_SCOPE() { return POC_TABLE_SYSTEM_MAPPING_SCOPE },
  get accessError() { return accessError },
  get activeSystemIdsForTable() { return activeSystemIdsForTable },
  get bulkPreparations() { return bulkPreparations },
  get canReadRegistrationAsset() { return canReadRegistrationAsset },
  get canonicalHash() { return canonicalHash },
  get catalogMetadataHeaders() { return catalogMetadataHeaders },
  get datahubAsset() { return datahubAsset },
  get datahubInventory() { return datahubInventory },
  get inflateRawSync() { return inflateRawSync },
  get legacyTableTagGrade() { return legacyTableTagGrade },
  get maximumObjectBytes() { return maximumObjectBytes },
  get minio() { return minio },
  get minioObject() { return minioObject },
  get randomUUID() { return randomUUID },
  get sha256() { return sha256 },
})

const {
  neo4jQuery,
  neo4jGraph,
} = createInfrastructureNeo4j({
  get basicAuthorization() { return basicAuthorization },
  get joinProviderUrl() { return joinProviderUrl },
  get neo4j() { return neo4j },
  get providerFetch() { return providerFetch },
  get providerTimeoutMs() { return providerTimeoutMs },
})

const {
  knowledgeProjectionError,
  isCanonicalDatahubSchemaFieldUrn,
  knowledgeABoxIngestionApi,
  knowledgeProjectionApi,
  knowledgeChatNotFound,
  knowledgeChatScope,
  knowledgeVisualizationRoot,
  selectManagedKnowledgeVisualization,
  knowledgeChatSnapshot,
  knowledgeGraphRag,
  mcpHandler,
  knowledgeChatApi,
} = createModulesKnowledgeApplication({
  get accessError() { return accessError },
  get assertManagedK9AssetAccess() { return assertManagedK9AssetAccess },
  get assertPocRouteAuthorization() { return assertPocRouteAuthorization },
  get authenticatedPocProfile() { return authenticatedPocProfile },
  get authenticatedRequestContext() { return authenticatedRequestContext },
  get bodyJson() { return bodyJson },
  get boundedString() { return boundedString },
  get canReadAsset() { return canReadAsset },
  get canonicalHash() { return canonicalHash },
  get datahubAssetAll() { return datahubAssetAll },
  get exactBodyKeys() { return exactBodyKeys },
  get exactServiceToken() { return exactServiceToken },
  get featureSecurityAllowed() { return featureSecurityAllowed },
  get graphReadBackMatches() { return graphReadBackMatches },
  get hasAccessControlCharacter() { return hasAccessControlCharacter },
  get isCanonicalDatahubDatasetUrn() { return isCanonicalDatahubDatasetUrn },
  get json() { return json },
  get knowledgeChatEvidenceVersion() { return knowledgeChatEvidenceVersion },
  get knowledgeChatPromptVersion() { return knowledgeChatPromptVersion },
  get knowledgeProjectionReceiptContract() { return knowledgeProjectionReceiptContract },
  get knowledgeSourceIdentityContract() { return knowledgeSourceIdentityContract },
  get knowledgeSourceManifest() { return knowledgeSourceManifest },
  get llm() { return llm },
  get llmRequest() { return llmRequest },
  get managedK9Assets() { return managedK9Assets },
  get managedK9LifecycleStatus() { return managedK9LifecycleStatus },
  get managedK9ScopeFromRow() { return managedK9ScopeFromRow },
  get mcpReadToolCapabilities() { return mcpReadToolCapabilities },
  get neo4jQuery() { return neo4jQuery },
  get problem() { return problem },
  get providerTimeoutMs() { return providerTimeoutMs },
  get rejectProtectedAccessClaims() { return rejectProtectedAccessClaims },
  get resolvePocRoute() { return resolvePocRoute },
  get securityGradeRank() { return securityGradeRank },
  get tablePolicyCellKey() { return tablePolicyCellKey },
})

const {
  managedK9SchedulerReadModel,
  managedK9AssetSummary,
  assertManagedK9AssetAccess,
  authorizeManagedK9Release,
  managedK9Assets,
  managedK9LifecycleStatus,
  managedK9ScopeFromRow,
} = createModulesK9ReadModel({
  get K9_V2_SOURCE_RUN_MODES() { return K9_V2_SOURCE_RUN_MODES },
  get canReadAsset() { return canReadAsset },
  get catalogEmbeddingBindingHash() { return catalogEmbeddingBindingHash },
  get isCanonicalDatahubDatasetUrn() { return isCanonicalDatahubDatasetUrn },
  get k9GraphAssetDefinition() { return k9GraphAssetDefinition },
  get k9ServiceCeilingToGrade() { return k9ServiceCeilingToGrade },
  get k9SourceFailureDetails() { return k9SourceFailureDetails },
  get k9SourceFailureStages() { return k9SourceFailureStages },
  get k9V2FailureCodes() { return k9V2FailureCodes },
  get knowledgeChatNotFound() { return knowledgeChatNotFound },
  get knowledgeProjectionError() { return knowledgeProjectionError },
  get nextScheduleBoundary() { return nextScheduleBoundary },
  get publicK9V2LifecycleStatus() { return publicK9V2LifecycleStatus },
  get sanitizeK9LineageSourceProfile() { return sanitizeK9LineageSourceProfile },
  get sanitizeK9MetadataSourceProfile() { return sanitizeK9MetadataSourceProfile },
  get sanitizeK9SourceEligibilityTelemetry() { return sanitizeK9SourceEligibilityTelemetry },
  get sanitizeK9V2FailureDiagnostic() { return sanitizeK9V2FailureDiagnostic },
})

const {
  authenticatedRequestContext,
  exactServiceToken,
  exactBodyKeys,
  normalizedSecurityGrade,
  normalizedResponsibleSystems,
  confirmedCurrentTables,
  authRoute,
} = createModulesAuthHttp({
  get accessError() { return accessError },
  get approvedDefaultFeatureSecurityPolicy() { return approvedDefaultFeatureSecurityPolicy },
  get assertPocRouteAuthorization() { return assertPocRouteAuthorization },
  get authenticatedPocProfile() { return authenticatedPocProfile },
  get authorizationProjection() { return authorizationProjection },
  get bodyJson() { return bodyJson },
  get boundedString() { return boundedString },
  get buildPocPrincipal() { return buildPocPrincipal },
  get changeHistoryActiveUser() { return changeHistoryActiveUser },
  get changeHistoryDocumentFromSnapshot() { return changeHistoryDocumentFromSnapshot },
  get json() { return json },
  get normalizePersistedFeatureSecurityPolicy() { return normalizePersistedFeatureSecurityPolicy },
  get normalizeSecurityGrade() { return normalizeSecurityGrade },
  get problem() { return problem },
  get resolvePocRoute() { return resolvePocRoute },
  get timingSafeEqual() { return timingSafeEqual },
})

const {
  adminUsersApi,
  tableSystemMappingApi,
  adminSystemsApi,
  featureSecurityPolicyApi,
  siteBrandingApi,
} = createModulesAdminApplication({
  get POC_FEATURE_SECURITY_POLICY_SCOPE() { return POC_FEATURE_SECURITY_POLICY_SCOPE },
  get POC_SITE_BRANDING_SCOPE() { return POC_SITE_BRANDING_SCOPE },
  get POC_TABLE_SYSTEM_MAPPING_SCOPE() { return POC_TABLE_SYSTEM_MAPPING_SCOPE },
  get accessError() { return accessError },
  get accessIfMatch() { return accessIfMatch },
  get applyFeatureSecurityPolicyUpdate() { return applyFeatureSecurityPolicyUpdate },
  get applySiteBrandingUpdate() { return applySiteBrandingUpdate },
  get applyTableSystemMappingCommand() { return applyTableSystemMappingCommand },
  get bodyJson() { return bodyJson },
  get boundedString() { return boundedString },
  get canonicalHash() { return canonicalHash },
  get changeHistoryAccessCoreProjection() { return changeHistoryAccessCoreProjection },
  get changeHistoryDocumentFromSnapshot() { return changeHistoryDocumentFromSnapshot },
  get confirmedCurrentTables() { return confirmedCurrentTables },
  get datahubInventory() { return datahubInventory },
  get exactBodyKeys() { return exactBodyKeys },
  get featureSecurityPolicyIfMatch() { return featureSecurityPolicyIfMatch },
  get hasAccessControlCharacter() { return hasAccessControlCharacter },
  get hashPocPassword() { return hashPocPassword },
  get json() { return json },
  get normalizeChangeHistoryAccessDocument() { return normalizeChangeHistoryAccessDocument },
  get normalizePersistedFeatureSecurityPolicy() { return normalizePersistedFeatureSecurityPolicy },
  get normalizePocUsername() { return normalizePocUsername },
  get normalizeSiteBrandingDocument() { return normalizeSiteBrandingDocument },
  get normalizeTableSystemMappingDocument() { return normalizeTableSystemMappingDocument },
  get normalizedResponsibleSystems() { return normalizedResponsibleSystems },
  get normalizedSecurityGrade() { return normalizedSecurityGrade },
  get privateChangeHistoryAccess() { return privateChangeHistoryAccess },
  get problem() { return problem },
  get publicSiteBranding() { return publicSiteBranding },
  get randomUUID() { return randomUUID },
  get rejectProtectedAccessBodyClaims() { return rejectProtectedAccessBodyClaims },
  get requireActiveAccessAdmin() { return requireActiveAccessAdmin },
  get siteBrandingIdempotencyHash() { return siteBrandingIdempotencyHash },
  get siteBrandingIfMatch() { return siteBrandingIfMatch },
  get siteBrandingRequestHash() { return siteBrandingRequestHash },
  get tableAuthoritySnapshot() { return tableAuthoritySnapshot },
  get tableSystemCandidates() { return tableSystemCandidates },
  get tableSystemIfMatch() { return tableSystemIfMatch },
})

const {
  bulkCandidateChangeRequestApi,
  crCreateApi,
  applyReportApi,
  crCommandApi,
} = createModulesGovernanceApplication({
  get POC_TABLE_SYSTEM_MAPPING_SCOPE() { return POC_TABLE_SYSTEM_MAPPING_SCOPE },
  get accessError() { return accessError },
  get activeSystemIdsForTable() { return activeSystemIdsForTable },
  get applyFinalLane() { return applyFinalLane },
  get applyTestRun() { return applyTestRun },
  get applyTransition() { return applyTransition },
  get applyWorkflowLane() { return applyWorkflowLane },
  get assertCrTableAccess() { return assertCrTableAccess },
  get assertCrWorkflowAction() { return assertCrWorkflowAction },
  get bodyJson() { return bodyJson },
  get bulkCandidatePreview() { return bulkCandidatePreview },
  get bulkPreparations() { return bulkPreparations },
  get canReadBulkPreparation() { return canReadBulkPreparation },
  get canonicalHash() { return canonicalHash },
  get crResponsibleSystemId() { return crResponsibleSystemId },
  get hasAccessControlCharacter() { return hasAccessControlCharacter },
  get json() { return json },
  get legacyTableTagGrade() { return legacyTableTagGrade },
  get normalizeTableSystemMappingDocument() { return normalizeTableSystemMappingDocument },
  get problem() { return problem },
  get randomUUID() { return randomUUID },
  get rejectProtectedAccessBodyClaims() { return rejectProtectedAccessBodyClaims },
  get rejectProtectedAccessClaims() { return rejectProtectedAccessClaims },
  get resolveNewCrResponsibleSystem() { return resolveNewCrResponsibleSystem },
  get stateIfMatch() { return stateIfMatch },
  get supportedDatahubClassifications() { return supportedDatahubClassifications },
  get visibleRegistrationCandidates() { return visibleRegistrationCandidates },
})

const {
  api,
} = createInterfacesHttpRouter({
  get AIRFLOW_EXECUTION_SCOPE() { return AIRFLOW_EXECUTION_SCOPE },
  get AIRFLOW_SYSTEM_ID() { return AIRFLOW_SYSTEM_ID },
  get ALLOWED_AIRFLOW_DAGS() { return ALLOWED_AIRFLOW_DAGS },
  get POC_CATALOG_EXPORT_MAXIMUM_ROWS() { return POC_CATALOG_EXPORT_MAXIMUM_ROWS },
  get POC_TABLE_SYSTEM_MAPPING_SCOPE() { return POC_TABLE_SYSTEM_MAPPING_SCOPE },
  get accessError() { return accessError },
  get activeSystemIdsForTable() { return activeSystemIdsForTable },
  get adminSystemsApi() { return adminSystemsApi },
  get adminUsersApi() { return adminUsersApi },
  get airflow() { return airflow },
  get airflowIdempotencyKey() { return airflowIdempotencyKey },
  get allowedPocStateScopes() { return allowedPocStateScopes },
  get applyManualMetadata() { return applyManualMetadata },
  get applyReportApi() { return applyReportApi },
  get assertRegistrationAssetMutation() { return assertRegistrationAssetMutation },
  get authorizeCoreReplacement() { return authorizeCoreReplacement },
  get bestEffortAirflowReceiptWrite() { return bestEffortAirflowReceiptWrite },
  get bodyBuffer() { return bodyBuffer },
  get bodyJson() { return bodyJson },
  get boundedString() { return boundedString },
  get bulkCandidateChangeRequestApi() { return bulkCandidateChangeRequestApi },
  get bulkCandidatePreview() { return bulkCandidatePreview },
  get bulkPreparationProjection() { return bulkPreparationProjection },
  get bulkPreparations() { return bulkPreparations },
  get bulkRegistrationDagId() { return bulkRegistrationDagId },
  get bulkTemplatePath() { return bulkTemplatePath },
  get canReadAsset() { return canReadAsset },
  get canReadBulkPreparation() { return canReadBulkPreparation },
  get canonicalHash() { return canonicalHash },
  get capabilities() { return capabilities },
  get catalogEmbeddingStatus() { return catalogEmbeddingStatus },
  get catalogMetadataHeaders() { return catalogMetadataHeaders },
  get changeHistoryAccess() { return changeHistoryAccess },
  get changeHistoryApi() { return changeHistoryApi },
  get chatMemoryPayload() { return chatMemoryPayload },
  get compactChatMemory() { return compactChatMemory },
  get crCommandApi() { return crCommandApi },
  get crCreateApi() { return crCreateApi },
  get createAirflowControlStore() { return createAirflowControlStore },
  get createCatalogExport() { return createCatalogExport },
  get createReadStream() { return createReadStream },
  get currentChatDiscovery() { return currentChatDiscovery },
  get currentChatHistoryMessages() { return currentChatHistoryMessages },
  get datahub() { return datahub },
  get datahubAsset() { return datahubAsset },
  get datahubAssetAll() { return datahubAssetAll },
  get datahubCatalog() { return datahubCatalog },
  get datahubCatalogDetailBase() { return datahubCatalogDetailBase },
  get datahubCatalogDetailQuality() { return datahubCatalogDetailQuality },
  get datahubCatalogDetailSchema() { return datahubCatalogDetailSchema },
  get datahubCatalogLocate() { return datahubCatalogLocate },
  get datahubDashboard() { return datahubDashboard },
  get datahubFacets() { return datahubFacets },
  get datahubGlossary() { return datahubGlossary },
  get datahubGlossaryAssignmentBatchCounts() { return datahubGlossaryAssignmentBatchCounts },
  get datahubGlossaryAssignments() { return datahubGlossaryAssignments },
  get datahubGlossarySmokeTarget() { return datahubGlossarySmokeTarget },
  get datahubLineage() { return datahubLineage },
  get datahubLineageProjectionOptions() { return datahubLineageProjectionOptions },
  get datahubProfileCoverage() { return datahubProfileCoverage },
  get datahubSystems() { return datahubSystems },
  get datahubTree() { return datahubTree },
  get exactBodyKeys() { return exactBodyKeys },
  get executeBulkPreparation() { return executeBulkPreparation },
  get existsSync() { return existsSync },
  get featureSecurityPolicyApi() { return featureSecurityPolicyApi },
  get filterCoreStateForPrincipal() { return filterCoreStateForPrincipal },
  get isAirflowDagTransitionOutcomeUnknown() { return isAirflowDagTransitionOutcomeUnknown },
  get isAirflowTriggerOutcomeUnknown() { return isAirflowTriggerOutcomeUnknown },
  get json() { return json },
  get knowledgeABoxIngestionApi() { return knowledgeABoxIngestionApi },
  get knowledgeCatalogDetail() { return knowledgeCatalogDetail },
  get knowledgeCatalogSearch() { return knowledgeCatalogSearch },
  get knowledgeChatApi() { return knowledgeChatApi },
  get knowledgeProjectionApi() { return knowledgeProjectionApi },
  get liveChat() { return liveChat },
  get maximumChatQuestionCharacters() { return maximumChatQuestionCharacters },
  get maximumObjectBytes() { return maximumObjectBytes },
  get minio() { return minio },
  get minioObject() { return minioObject },
  get neo4jGraph() { return neo4jGraph },
  get persistedChatMemory() { return persistedChatMemory },
  get persistedChatWorkflow() { return persistedChatWorkflow },
  get problem() { return problem },
  get publicChatDiscovery() { return publicChatDiscovery },
  get publicChatEvidence() { return publicChatEvidence },
  get randomUUID() { return randomUUID },
  get readFileSync() { return readFileSync },
  get securityHeaders() { return securityHeaders },
  get sha256() { return sha256 },
  get siteBrandingApi() { return siteBrandingApi },
  get statSync() { return statSync },
  get stateIfMatch() { return stateIfMatch },
  get tableSystemMappingApi() { return tableSystemMappingApi },
  get triggerAirflowDag() { return triggerAirflowDag },
  get visibleRegistrationCandidates() { return visibleRegistrationCandidates },
  get writeApprovedAnswerStream() { return writeApprovedAnswerStream },
  get writeEventStream() { return writeEventStream },
})

const {
  serveStatic,
} = createInterfacesHttpStatic({
  get createReadStream() { return createReadStream },
  get existsSync() { return existsSync },
  get extname() { return extname },
  get join() { return join },
  get mimeTypes() { return mimeTypes },
  get normalize() { return normalize },
  get problem() { return problem },
  get readFileSync() { return readFileSync },
  get resolve() { return resolve },
  get securityHeaders() { return securityHeaders },
  get sep() { return sep },
  get statSync() { return statSync },
  get staticDirectory() { return staticDirectory },
})

const {
  createPocServer,
} = createServerModule({
  get URL() { return URL },
  get api() { return api },
  get assertPocRouteAuthorization() { return assertPocRouteAuthorization },
  get authRoute() { return authRoute },
  get authenticatedRequestContext() { return authenticatedRequestContext },
  get createPocCatalogExportStore() { return createPocCatalogExportStore },
  get createServer() { return createServer },
  get currentDatahubInventory() { return currentDatahubInventory },
  get currentDatahubTables() { return currentDatahubTables },
  get datahubChatEvidence() { return datahubChatEvidence },
  get defaultAirflowControlProvider() { return defaultAirflowControlProvider },
  get exactServiceToken() { return exactServiceToken },
  get knowledgeChatScope() { return knowledgeChatScope },
  get knowledgeChatSnapshot() { return knowledgeChatSnapshot },
  get knowledgeGraphRag() { return knowledgeGraphRag },
  get mcpHandler() { return mcpHandler },
  get pocStateStore() { return pocStateStore },
  set pocStateStore(value) { pocStateStore = value },
  get problem() { return problem },
  get process() { return process },
  get redirectBrowserToCanonicalOrigin() { return redirectBrowserToCanonicalOrigin },
  get rejectProtectedAccessClaims() { return rejectProtectedAccessClaims },
  get resolvePocRoute() { return resolvePocRoute },
  get runtimeFlags() { return runtimeFlags },
  get securityHeaders() { return securityHeaders },
  get serveStatic() { return serveStatic },
  get siteBrandingApi() { return siteBrandingApi },
  get stateChangingMethods() { return stateChangingMethods },
  get unconfiguredPocAuthenticator() { return unconfiguredPocAuthenticator },
})

export { changeHistoryPresentation, manualMetadataAspectComparableDocument, publicDatahubAsset, startDatahubInventoryRefresh, catalogDatabaseBranchLabel, glossaryAssignmentCountsFromInventory, reconcileDatahubGlossaryScrollPage, datahubLineageProjectionOptions, parseChatRouteDecision, metadataMasterCandidateContext, managedGraphNodeSupportsDirection, managedK9SchedulerReadModel, managedK9AssetSummary, authorizeManagedK9Release, knowledgeVisualizationRoot, selectManagedKnowledgeVisualization, createPocServer }

const sourceDirectory = resolve(fileURLToPath(new URL('.', import.meta.url)))
const staticDirectory = resolve(sourceDirectory, '../../frontend/dist')
const environmentFile = resolve(process.env.POC_ENV_FILE || join(sourceDirectory, '../../deploy/.env.prep'))
if (existsSync(environmentFile)) process.loadEnvFile(environmentFile)
const providerTransport = createProviderTransport(process.env)
const maximumJsonBytes = 1024 * 1024
const maximumObjectBytes = 50 * 1024 * 1024
const providerTimeoutMs = 15_000
const llmProviderTimeoutMs = parseLlmProviderTimeoutMs(process.env.POC_LLM_TIMEOUT_MS)
const bulkRegistrationDagId = process.env.AIRFLOW_DAG_ID?.trim() || 'datariver_bulk_registration_prepare'
if (!ALLOWED_AIRFLOW_DAGS.has(bulkRegistrationDagId) || bulkRegistrationDagId !== 'datariver_bulk_registration_prepare') {
  throw new Error('AIRFLOW_DAG_ID must select the reviewed datariver_bulk_registration_prepare DAG.')
}
const allowedDataHubAspects = new Set([
  'datasetProperties',
  'domains',
  'globalTags',
  'glossaryTerms',
  'schemaMetadata',
])

const datahubCursorTtlMs = 5 * 60 * 1000
const datahubInventoryTtlMs = 15 * 60 * 1000
const datahubInventoryFailureRetryMs = 60 * 1000
const maximumCursorEntries = 1_024
const maximumInventoryPages = 10_002
const catalogEmbeddingBatchSize = 32
const catalogEmbeddingRefreshIntervalMs = 15 * 60 * 1000
const maximumCatalogQueryTerms = 12
const maximumCatalogQueryTermLength = 120
const maximumChatEvidenceItems = 20
const minimumChatDiscoveryItems = 8
const maximumChatQuestionCharacters = 12_000
const maximumChatMemoryCharacters = 16_000
const maximumChatMemorySummaryCharacters = 5_000
const maximumChatMemoryTurns = 5
const maximumChatMemoryTurnQuestionCharacters = 900
const maximumChatMemoryTurnAnswerCharacters = 1_300
const catalogSearchFieldNames = new Set(['SCHEMA', 'TABLE', 'COLUMN', 'TAG', 'TERM', 'DESCRIPTION'])
const supportedDatahubClassifications = new Set(['PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED'])
const cursorEntries = new Map()
let inventorySnapshot
let inventoryRefreshPromise
let inventoryRefreshFailedAt
let inventoryRefreshRetryAt = 0
let inventoryRefreshDiagnostic
let inventoryRefreshLastError
let catalogEmbeddingSnapshot
let catalogEmbeddingRefreshPromise
let catalogEmbeddingRefreshStartedAt = 0
let catalogEmbeddingLastError
let catalogEmbeddingRefreshTimer
let serverBackgroundAbortController
let backgroundLaunchesStopped = false
let k9V2LifecycleRequested = false
let reconcileK9SemanticGeneration = async () => ({ status: 'unavailable' })
const bulkPreparations = new Map()
const bulkTemplatePath = join(sourceDirectory, '../assets/datariver-catalog-metadata-rows.xlsx')
const catalogMetadataHeaders = [
  'record_kind', 'asset_id', 'platform', 'database_name', 'schema_name',
  'table_name', 'field_path', 'operation', 'value_text', 'controlled_ref',
]

function optionalUrl(name) {
  const raw = process.env[name]?.trim()
  if (!raw) return undefined
  const value = new URL(raw)
  if (!['http:', 'https:'].includes(value.protocol) || value.username || value.password || value.hash) {
    throw new Error(`${name} must be an http(s) URL without credentials or a fragment.`)
  }
  return value.toString().replace(/\/$/, '')
}

function enabled(name) {
  const raw = process.env[name]?.trim().toLowerCase()
  if (!raw) return false
  if (raw === 'true') return true
  if (raw === 'false') return false
  throw new Error(`${name} must be true or false.`)
}

function stage(prefix) {
  const url = optionalUrl(`${prefix}_URL`)
  const model = process.env[`${prefix}_MODEL`]?.trim()
  const token = process.env[`${prefix}_TOKEN`]?.trim()
  if ([url, model, token].some(Boolean) && ![url, model, token].every(Boolean)) {
    throw new Error(`${prefix}_URL, ${prefix}_MODEL and ${prefix}_TOKEN must be configured together.`)
  }
  return url && model && token ? { url, model, token } : undefined
}

function credentials(prefix, urlName, { allowUrlOmission = false } = {}) {
  const url = optionalUrl(urlName)
  const username = process.env[`${prefix}_USERNAME`]?.trim()
  const password = process.env[`${prefix}_PASSWORD`]?.trim()
  if (!url && allowUrlOmission) return undefined
  if ([url, username, password].some(Boolean) && ![url, username, password].every(Boolean)) {
    throw new Error(`${urlName}, ${prefix}_USERNAME and ${prefix}_PASSWORD must be configured together.`)
  }
  return url && username && password ? { url, username, password } : undefined
}

function tokenProvider(prefix, urlName, { allowMissingToken = false } = {}) {
  const url = optionalUrl(urlName)
  const token = process.env[`${prefix}_TOKEN`]?.trim()
  if (token && !url) {
    throw new Error(`${urlName} and ${prefix}_TOKEN must be configured together.`)
  }
  if (url && !token && !allowMissingToken) {
    throw new Error(`${urlName} and ${prefix}_TOKEN must be configured together.`)
  }
  return url ? { url, token } : undefined
}

// POC_DATAHUB_ALLOW_NO_TOKEN=true is a DEV-only explicit opt-in that permits a locally
// auth-disabled GMS to run without a token. It must not be set in PREP or OPS environments.
// Omitting or setting it to false (the default) enforces fail-closed: a GMS URL without a
// token is rejected at startup. PREP/OPS deployments always set DATAHUB_GMS_TOKEN so this
// flag is irrelevant in those environments and their secret-file contract is unchanged.
const datahubAllowNoToken = enabled('POC_DATAHUB_ALLOW_NO_TOKEN')
const datahub = tokenProvider('DATAHUB_GMS', 'DATAHUB_GMS_URL', { allowMissingToken: datahubAllowNoToken })
const knowledgeSourceManifest = (() => {
  const raw = process.env.POC_KNOWLEDGE_SOURCE_MANIFEST?.trim()
  if (!raw) return new Map()
  let value
  try { value = JSON.parse(raw) } catch { throw new Error('POC_KNOWLEDGE_SOURCE_MANIFEST must be valid JSON.') }
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('POC_KNOWLEDGE_SOURCE_MANIFEST must be an object keyed by exact DataHub Table URN.')
  }
  const entries = new Map()
  for (const [assetUrn, item] of Object.entries(value)) {
    if (!isCanonicalDatahubDatasetUrn(assetUrn) || !item || typeof item !== 'object' || Array.isArray(item)) {
      throw new Error('POC_KNOWLEDGE_SOURCE_MANIFEST contains an invalid Table entry.')
    }
    const manifestRef = typeof item.manifest_ref === 'string' ? item.manifest_ref.trim() : ''
    const sourceVersion = typeof item.source_version === 'string' ? item.source_version.trim() : ''
    const secretRef = typeof item.secret_ref === 'string' ? item.secret_ref.trim() : ''
    if (!manifestRef || manifestRef.length > 255 || !sourceVersion || sourceVersion.length > 255
      || !secretRef || secretRef.length > 255) {
      throw new Error('POC_KNOWLEDGE_SOURCE_MANIFEST entries require bounded manifest_ref/source_version/secret_ref.')
    }
    entries.set(assetUrn, Object.freeze({ manifestRef, sourceVersion, secretRef }))
  }
  return entries
})()
const datahubCacheScope = datahub ? sha256(datahub.url).slice(0, 16) : 'disabled'
const datahubInventoryCacheKey = `datahub-inventory-v5:${datahubCacheScope}`
const datahubInventoryStateScope = `catalog-inventory-v1:${datahubCacheScope}`
const airflow = credentials('AIRFLOW', 'AIRFLOW_URL')
const minioUrl = optionalUrl('MINIO_URL')
const minioAccessKey = process.env.MINIO_ACCESS_KEY?.trim()
const minioSecretKey = process.env.MINIO_SECRET_KEY?.trim()
if ([minioUrl, minioAccessKey, minioSecretKey].some(Boolean)
  && ![minioUrl, minioAccessKey, minioSecretKey].every(Boolean)) {
  throw new Error('MINIO_URL, MINIO_ACCESS_KEY and MINIO_SECRET_KEY must be configured together.')
}
const minio = minioUrl && minioAccessKey && minioSecretKey ? {
  url: minioUrl,
  accessKey: minioAccessKey,
  secretKey: minioSecretKey,
  region: process.env.MINIO_REGION?.trim() || 'us-east-1',
  buckets: {
    quarantine: process.env.S3_BUCKET_QUARANTINE?.trim() || 'datariver-quarantine',
    accepted: process.env.S3_BUCKET_ACCEPTED?.trim() || 'datariver-accepted',
    exports: process.env.S3_BUCKET_EXPORTS?.trim() || 'datariver-exports',
    filefolder: process.env.S3_BUCKET_FILEFOLDER?.trim() || 'datariver-filefolder',
    infoschema: process.env.S3_BUCKET_INFOSCHEMA?.trim() || 'datariver-infoschema',
  },
} : undefined
const llm = {
  chat: stage('LLM_CHAT'),
  embedding: stage('LLM_EMBEDDING'),
  reranker: stage('LLM_RERANKER'),
}
const neo4j = credentials('NEO4J', 'NEO4J_HTTP_URL', { allowUrlOmission: true })
const datahubUiUrl = optionalUrl('DATAHUB_UI_URL')
const grafanaUiUrl = optionalUrl('UI_GRAFANA_URL')
const grafanaEmbedBaseUrl = optionalUrl('GRAFANA_EMBED_BASE_URL')
const grafanaEmbedEnabled = enabled('GRAFANA_EMBED_ENABLED')
const grafanaEvidenceReference = process.env.GRAFANA_EMBED_EVIDENCE_REFERENCE?.trim()
if (grafanaEmbedEnabled) {
  if (!grafanaUiUrl || !grafanaEmbedBaseUrl || !grafanaEvidenceReference) {
    throw new Error('Grafana embed requires UI_GRAFANA_URL, GRAFANA_EMBED_BASE_URL and GRAFANA_EMBED_EVIDENCE_REFERENCE.')
  }
  if (new URL(grafanaUiUrl).origin !== new URL(grafanaEmbedBaseUrl).origin) {
    throw new Error('UI_GRAFANA_URL and GRAFANA_EMBED_BASE_URL must use the same exact origin.')
  }
}

const configuredMonitoringDashboards = monitoringDashboards()
const runtimeFlags = Object.freeze({
  datahub: Boolean(datahub),
  airflow: Boolean(airflow),
  minio: Boolean(minio),
  llmChat: Boolean(llm.chat),
  llmEmbedding: Boolean(llm.embedding),
  llmReranker: Boolean(llm.reranker),
  neo4j: Boolean(neo4j),
  pocState: true,
})
let pocStateStore = createPocStateStore()
const allowedPocStateScopes = new Set(['core', 'knowledge', 'governance'])
const protectedAccessHeaders = new Set([
  'x-subject-id', 'x-subject-role', 'x-role', 'x-system-id', 'x-responsibility',
  'x-priority', 'x-actor-ref', 'x-policy-hash', 'x-basis-hash', 'x-occurred-at',
])
const protectedAccessQueryKeys = new Set([
  'subject_id', 'active_subject_id', 'role', 'system_id', 'responsibility', 'priority',
  'actor_ref', 'policy_hash', 'basis_hash', 'occurred_at',
])
const stateChangingMethods = new Set(['DELETE', 'PATCH', 'POST', 'PUT'])

const changeHistoryActions = new Map([
  ['SET_PRIMARY', 'PRIMARY'], ['CLEAR_PRIMARY', 'PRIMARY'],
  ['ADD_CANDIDATE', 'CANDIDATE'], ['REMOVE_CANDIDATE', 'CANDIDATE'],
])
const changeHistoryCategories = new Set(['TECHNICAL_SCHEMA', 'DOCUMENTATION', 'TAG', 'GLOSSARY_TERM', 'DOMAIN', 'OWNERSHIP', 'LIFECYCLE'])
const changeHistoryOperations = new Set(['CREATE', 'UPDATE', 'UPSERT', 'DELETE', 'ADD', 'REMOVE'])
const changeHistoryPresentationStages = new Set(['UNLINKED', 'RECEIVED', 'RECHECK', 'TESTING', 'FINAL_REVIEW', 'COMPLETED'])
const changeHistoryPrecisionValues = ['EXACT_TIMELINE', 'EXACT_MCL', 'DRIFT_DETECTED', 'BACKFILLED_BEST_EFFORT', 'INITIAL_BASELINE']

const changeHistoryUnknownCompleteness = Object.freeze({
  history_completeness: 'UNKNOWN',
  history_gap_reason: null,
  history_gap_count: 0,
  exact_current_segments: [],
})

const datahubEmbeddingInventoryQuery = `
query DataRiverPocCatalogEmbeddingInventory($input: ScrollAcrossEntitiesInput!) {
  scrollAcrossEntities(input: $input) {
    nextScrollId count total
    searchResults {
      entity {
        urn type
        ... on Dataset {
          exists
          status { removed }
          name
          subTypes { typeNames }
          platform { urn name }
          properties { name qualifiedName description created customProperties { key value } }
          editableProperties { description }
          container { urn properties { name qualifiedName description customProperties { key value } } subTypes { typeNames } }
          dataPlatformInstance {
            urn instanceId
            properties { name description customProperties { key value } }
          }
          browsePathV2 {
            path {
              name
              entity {
                urn type
                ... on Container {
                  properties { name qualifiedName }
                  subTypes { typeNames }
                }
              }
            }
          }
          domain { domain { urn properties { name description } } }
          structuredProperties {
            properties {
              structuredProperty {
                urn
                definition { qualifiedName displayName description cardinality }
              }
              values {
                ... on StringValue { stringValue }
                ... on NumberValue { numberValue }
              }
              associatedUrn
            }
          }
          ownership { owners { owner { ... on CorpUser { urn } ... on CorpGroup { urn } } type } }
          globalTags: tags { tags { tag { urn name properties { name description } } } }
          glossaryTerms { terms { term { urn name properties { name description } } } }
          schemaMetadata(version: 0) {
            fields {
              fieldPath label type nativeDataType description nullable isPartOfKey isPartitioningKey jsonPath
              globalTags { tags { tag { urn name properties { name description } } } }
              glossaryTerms { terms { term { urn name properties { name description } } } }
              schemaFieldEntity {
                urn type
                globalTags: tags { tags { tag { urn name properties { name description } } } }
                glossaryTerms { terms { term { urn name properties { name description } } } }
                structuredProperties {
                  properties {
                    structuredProperty {
                      urn
                      definition { qualifiedName displayName description cardinality }
                    }
                    values {
                      ... on StringValue { stringValue }
                      ... on NumberValue { numberValue }
                    }
                    associatedUrn
                  }
                }
              }
            }
          }
          fineGrainedLineages {
            upstreams { urn path }
            downstreams { urn path }
            query
            transformOperation
          }
          editableSchemaMetadata {
            editableSchemaFieldInfo {
              fieldPath description
              globalTags { tags { tag { urn name properties { name description } } } }
              glossaryTerms { terms { term { urn name properties { name description } } } }
            }
          }
          latestFullTableProfile: datasetProfiles(limit: 10) {
            rowCount columnCount sizeInBytes timestampMillis
            partitionSpec { type partition }
          }
        }
      }
    }
  }
}`

const datahubAssetQuery = `
query DataRiverPocAsset($urn: String!) {
  entity(urn: $urn) {
    urn type
    ... on Dataset {
      exists
      status { removed }
      name
      subTypes { typeNames }
      platform { urn name }
      properties { name qualifiedName description created customProperties { key value } }
      editableProperties { description }
      browsePathV2 {
        path {
          name
          entity {
            urn type
            ... on Container {
              properties { name qualifiedName }
              subTypes { typeNames }
            }
          }
        }
      }
      domain { domain { urn properties { name description } } }
      structuredProperties {
        properties {
          structuredProperty {
            urn
            definition { qualifiedName displayName description cardinality }
          }
          values {
            ... on StringValue { stringValue }
            ... on NumberValue { numberValue }
          }
          associatedUrn
        }
      }
      ownership { owners { owner { ... on CorpUser { urn } ... on CorpGroup { urn } } type } }
      globalTags: tags { tags { tag { urn name properties { name description } } } }
      glossaryTerms { terms { term { urn name properties { name description } } } }
      schemaMetadata(version: 0) {
        fields {
          fieldPath label type nativeDataType description nullable isPartOfKey isPartitioningKey jsonPath
          globalTags { tags { tag { urn name properties { name description } } } }
          glossaryTerms { terms { term { urn name properties { name description } } } }
          schemaFieldEntity {
            urn type
            globalTags: tags { tags { tag { urn name properties { name description } } } }
            glossaryTerms { terms { term { urn name properties { name description } } } }
            structuredProperties {
              properties {
                structuredProperty {
                  urn
                  definition { qualifiedName displayName description cardinality }
                }
                values {
                  ... on StringValue { stringValue }
                  ... on NumberValue { numberValue }
                }
                associatedUrn
              }
            }
          }
        }
      }
      fineGrainedLineages {
        upstreams { urn path }
        downstreams { urn path }
        query
        transformOperation
      }
      editableSchemaMetadata {
        editableSchemaFieldInfo {
          fieldPath description
          globalTags { tags { tag { urn name properties { name description } } } }
          glossaryTerms { terms { term { urn name properties { name description } } } }
        }
      }
      latestFullTableProfile: datasetProfiles(limit: 10) {
        rowCount columnCount sizeInBytes timestampMillis
        partitionSpec { type partition }
      }
      assertions(start: 0, count: 100) {
        start count total
        assertions {
          urn
          info { type source { type } }
          runEvents(status: COMPLETE, limit: 1) {
            total failed succeeded
            runEvents { timestampMillis status result { type } }
          }
        }
      }
    }
  }
}`

const datahubCatalogDetailBaseQuery = `
query DataRiverPocDetailBase($urn: String!) {
  entity(urn: $urn) {
    urn type
    ... on Dataset {
      exists
      status { removed }
      name
      subTypes { typeNames }
      platform { urn name }
      properties { name qualifiedName description created customProperties { key value } }
      editableProperties { description }
      container { urn properties { name qualifiedName description customProperties { key value } } subTypes { typeNames } }
      dataPlatformInstance {
        urn instanceId
        properties { name description customProperties { key value } }
      }
      browsePathV2 {
        path {
          name
          entity {
            urn type
            ... on Container {
              properties { name qualifiedName }
              subTypes { typeNames }
            }
          }
        }
      }
      domain { domain { urn properties { name description } } }
      ownership { owners { owner { ... on CorpUser { urn } ... on CorpGroup { urn } } type } }
      globalTags: tags { tags { tag { urn name properties { name description } } } }
      glossaryTerms { terms { term { urn name properties { name description } } } }
    }
  }
}`

const datahubCatalogDetailSchemaQuery = `
query DataRiverPocDetailSchema($urn: String!) {
  entity(urn: $urn) {
    urn type
    ... on Dataset {
      schemaMetadata(version: 0) {
        fields {
          fieldPath label type nativeDataType description nullable isPartOfKey isPartitioningKey jsonPath
          globalTags { tags { tag { urn name properties { name description } } } }
          glossaryTerms { terms { term { urn name properties { name description } } } }
          schemaFieldEntity {
            urn type
            globalTags: tags { tags { tag { urn name properties { name description } } } }
            glossaryTerms { terms { term { urn name properties { name description } } } }
            structuredProperties {
              properties {
                structuredProperty { urn definition { qualifiedName displayName description cardinality } }
                values { ... on StringValue { stringValue } ... on NumberValue { numberValue } }
                associatedUrn
              }
            }
          }
        }
      }
      editableSchemaMetadata {
        editableSchemaFieldInfo {
          fieldPath description
          globalTags { tags { tag { urn name properties { name description } } } }
          glossaryTerms { terms { term { urn name properties { name description } } } }
        }
      }
    }
  }
}`

const datahubCatalogDetailQualityQuery = `
query DataRiverPocDetailQuality($urn: String!) {
  entity(urn: $urn) {
    urn type
    ... on Dataset {
      latestFullTableProfile: datasetProfiles(limit: 10) {
        rowCount columnCount sizeInBytes timestampMillis
        partitionSpec { type partition }
      }
      assertions(start: 0, count: 100) {
        start count total
        assertions {
          urn
          info { type source { type } }
          runEvents(status: COMPLETE, limit: 1) {
            total failed succeeded
            runEvents { timestampMillis status result { type } }
          }
        }
      }
    }
  }
}`

const datahubCurrentEntitiesQuery = `
query DataRiverPocCurrentTables($urns: [String!]!) {
  entities(urns: $urns, checkForExistence: true) {
    urn type
    ... on Dataset {
      exists
      status { removed }
      subTypes { typeNames }
      properties { customProperties { key value } }
      schemaMetadata(version: 0) { name }
      globalTags: tags {
        tags { tag { urn name properties { name } } }
      }
    }
  }
}`

const datahubLineageQuery = `
query DataRiverPocLineage($urn: String!, $input: LineageInput!) {
  dataset(urn: $urn) {
    lineage(input: $input) {
      start
      count
      total
      filtered
      relationships {
        type
        entity {
          urn type
          ... on Dataset {
            exists
            status { removed }
            name
            subTypes { typeNames }
            platform { urn name }
            properties { name qualifiedName description created customProperties { key value } }
            editableProperties { description }
            browsePathV2 {
              path {
                name
                entity {
                  urn type
                  ... on Container {
                    properties { name qualifiedName }
                    subTypes { typeNames }
                  }
                }
              }
            }
            domain { domain { urn properties { name description } } }
            ownership { owners { owner { ... on CorpUser { urn } ... on CorpGroup { urn } } } }
            globalTags: tags { tags { tag { urn name properties { name } } } }
            glossaryTerms { terms { term { urn name } } }
          }
        }
        createdActor { urn }
        createdOn
        updatedActor { urn }
        updatedOn
        degree
        isManual
        paths { path { urn type } }
      }
    }
  }
}`

const datahubK9GlossaryQuery = `
query DataRiverK9Glossary($input: ScrollAcrossEntitiesInput!) {
  scrollAcrossEntities(input: $input) {
    nextScrollId count total
    searchResults {
      entity {
        urn type
        ... on GlossaryTerm {
          hierarchicalName
          properties { name description }
          glossaryTermInfo { name description termSource sourceRef sourceUrl customProperties { key value } }
          domain { domain { urn properties { name description } } }
          structuredProperties {
            properties {
              structuredProperty { urn definition { qualifiedName displayName description cardinality } }
              values {
                ... on StringValue { stringValue }
                ... on NumberValue { numberValue }
              }
              associatedUrn
            }
          }
          parentNodes {
            nodes {
              urn type
              ... on GlossaryNode { properties { name description } }
            }
          }
          tableAssignments: relationships(input: {
            types: ["TermedWith"]
            direction: INCOMING
            start: 0
            count: 0
            includeSoftDelete: false
          }) { total }
          columnAssignments: relationships(input: {
            types: ["SchemaFieldWithGlossaryTerm"]
            direction: INCOMING
            start: 0
            count: 0
            includeSoftDelete: false
          }) { total }
          outgoingRelationships: relationships(input: {
            types: []
            direction: OUTGOING
            start: 0
            count: 100
            includeSoftDelete: false
          }) {
            total
            relationships {
              type direction
              entity {
                urn type
                ... on GlossaryTerm { properties { name } }
                ... on GlossaryNode { properties { name } }
              }
            }
          }
        }
        ... on GlossaryNode {
          properties { name description customProperties { key value } }
          structuredProperties {
            properties {
              structuredProperty { urn definition { qualifiedName displayName description cardinality } }
              values {
                ... on StringValue { stringValue }
                ... on NumberValue { numberValue }
              }
              associatedUrn
            }
          }
          parentNodes {
            nodes {
              urn type
              ... on GlossaryNode { properties { name description } }
            }
          }
          outgoingRelationships: relationships(input: {
            types: []
            direction: OUTGOING
            start: 0
            count: 100
            includeSoftDelete: false
          }) {
            total
            relationships {
              type direction
              entity {
                urn type
                ... on GlossaryTerm { properties { name } }
                ... on GlossaryNode { properties { name } }
              }
            }
          }
        }
      }
    }
  }
}`

const datahubGlossaryQuery = `
query DataRiverPocGlossary($input: ScrollAcrossEntitiesInput!) {
  scrollAcrossEntities(input: $input) {
    nextScrollId count total
    searchResults {
      entity {
        urn type
        ... on GlossaryTerm {
          hierarchicalName
          properties { name description }
          parentNodes {
            nodes {
              urn type
              ... on GlossaryNode { properties { name description } }
            }
          }
        }
      }
    }
  }
}`

const datahubGlossaryTermByUrnQuery = `
query DataRiverPocGlossaryTermByUrn($urn: String!) {
  entity(urn: $urn) {
    urn type
    ... on GlossaryTerm {
      exists
      status { removed }
      hierarchicalName
      properties { name description }
      glossaryTermInfo { name description termSource sourceRef sourceUrl customProperties { key value } }
      domain { domain { urn properties { name description } } }
      structuredProperties {
        properties {
          structuredProperty { urn definition { qualifiedName displayName description cardinality } }
          values {
            ... on StringValue { stringValue }
            ... on NumberValue { numberValue }
          }
          associatedUrn
        }
      }
      parentNodes {
        nodes {
          urn type
          ... on GlossaryNode { properties { name description } }
        }
      }
      tableAssignments: relationships(input: {
        types: ["TermedWith"]
        direction: INCOMING
        start: 0
        count: 0
        includeSoftDelete: false
      }) { total }
      columnAssignments: relationships(input: {
        types: ["SchemaFieldWithGlossaryTerm"]
        direction: INCOMING
        start: 0
        count: 0
        includeSoftDelete: false
      }) { total }
      outgoingRelationships: relationships(input: {
        types: []
        direction: OUTGOING
        start: 0
        count: 100
        includeSoftDelete: false
      }) {
        total
        relationships {
          type direction
          entity {
            urn type
            ... on GlossaryTerm { properties { name } }
            ... on GlossaryNode { properties { name } }
          }
        }
      }
    }
  }
}`

const datahubK9GlossaryTermsByUrnsQuery = `
query DataRiverK9GlossaryTermsByUrns($urns: [String!]!) {
  entities(urns: $urns, checkForExistence: false) {
    urn type
    ... on GlossaryTerm {
      exists
      status { removed }
      hierarchicalName
      properties { name description }
      glossaryTermInfo { name description termSource sourceRef sourceUrl customProperties { key value } }
      domain { domain { urn properties { name description } } }
      structuredProperties {
        properties {
          structuredProperty { urn definition { qualifiedName displayName description cardinality } }
          values {
            ... on StringValue { stringValue }
            ... on NumberValue { numberValue }
          }
          associatedUrn
        }
      }
      parentNodes {
        nodes {
          urn type
          ... on GlossaryNode { properties { name description } }
        }
      }
      tableAssignments: relationships(input: {
        types: ["TermedWith"]
        direction: INCOMING
        start: 0
        count: 0
        includeSoftDelete: false
      }) { total }
      columnAssignments: relationships(input: {
        types: ["SchemaFieldWithGlossaryTerm"]
        direction: INCOMING
        start: 0
        count: 0
        includeSoftDelete: false
      }) { total }
      outgoingRelationships: relationships(input: {
        types: []
        direction: OUTGOING
        start: 0
        count: 100
        includeSoftDelete: false
      }) {
        total
        relationships {
          type direction
          entity {
            urn type
            ... on GlossaryTerm { properties { name } }
            ... on GlossaryNode { properties { name } }
          }
        }
      }
    }
  }
}`

const datahubGlossarySmokeDiscoveryQuery = `
query DataRiverPocGlossarySmokeDiscovery($input: ScrollAcrossEntitiesInput!) {
  scrollAcrossEntities(input: $input) {
    searchResults { entity { urn type } }
  }
}`

const datahubGlossarySmokeTargetQuery = `
query DataRiverPocGlossarySmokeTarget($urn: String!) {
  entityExists(urn: $urn)
  entity(urn: $urn) {
    urn type
    ... on GlossaryTerm {
      exists
      status { removed }
      hierarchicalName
      properties { name description }
      glossaryTermInfo { name description }
    }
  }
}`

const datahubEntityRelationshipsQuery = `
query DataRiverPocEntityRelationships($urn: String!, $input: RelationshipsInput!) {
  entity(urn: $urn) {
    urn type
    relationships(input: $input) {
      start count total
      relationships { type direction entity { urn type } }
    }
  }
}`

const datahubGlossaryAssignmentsQuery = `
query DataRiverPocGlossaryAssignments($urn: String!, $input: RelationshipsInput!) {
  entity(urn: $urn) {
    urn type
    ... on GlossaryTerm {
      relationships(input: $input) {
        start count total
        relationships {
          entity {
            urn type
            ... on Dataset {
              name
              platform { urn name }
              properties { name customProperties { key value } }
              browsePathV2 {
                path {
                  name
                  entity {
                    urn type
                    ... on Container {
                      properties { name qualifiedName }
                      subTypes { typeNames }
                    }
                  }
                }
              }
              glossaryTerms { terms { term { urn name } } }
              schemaMetadata {
                fields {
                  fieldPath
                  glossaryTerms { terms { term { urn name } } }
                  schemaFieldEntity {
                    glossaryTerms { terms { term { urn name } } }
                  }
                }
              }
              editableSchemaMetadata {
                editableSchemaFieldInfo {
                  fieldPath
                  glossaryTerms { terms { term { urn name } } }
                }
              }
            }
          }
        }
      }
    }
  }
}`

let datahubRuntimeIdentityPromise

const inventoryDiagnosticPhases = new Set([
  'PAGE_FETCH',
  'ENTITY_EXTRACTION',
  'ENTITY_NORMALIZATION',
  'INVENTORY_VALIDATION',
  'DEDUPLICATION',
  'SNAPSHOT_PERSISTENCE',
  'SNAPSHOT_PROMOTION',
  'AUTHORIZATION_PROJECTION',
  'RESPONSE_BUILD',
])

const catalogExportClassifications = new Set(['PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED'])
const catalogExportFilterFields = Object.freeze([
  'asset_type', 'platform', 'database_name', 'schema_name', 'domain',
  'search_fields', 'classification', 'lifecycle',
])

let airflowApiVersion
let airflowAccessToken
let airflowAccessTokenExpiresAt = 0

// Registration owns this separate service-only execution contract. It is not
// reachable through the administrator Airflow control routes above.

const chatRouteIntents = new Set([
  'GENERAL_CONVERSATION',
  'CATALOG_INVENTORY',
  'EXACT_METADATA',
  'SEMANTIC_DISCOVERY',
  'SEMANTIC_SIMILARITY',
  'LINEAGE',
  'IMPACT_ANALYSIS',
  'RELATIONSHIP',
  'MIXED_DISCOVERY_GRAPH',
  'AMBIGUOUS',
])

const METADATA_MASTER_DATA_NODE_TYPES = new Set([
  'class.dataset', 'class.table', 'class.view', 'class.column',
])

const knowledgeSourceIdentityContract = 'KNOWLEDGE_SOURCE_IDENTITY_V1'
const knowledgeProjectionReceiptContract = 'KNOWLEDGE_PROJECTION_RECEIPT_V1'

const knowledgeChatPromptVersion = 'knowledge-graphrag-v1'
const knowledgeChatEvidenceVersion = 'knowledge-evidence-v1'

// Product-owned service/graph policy only. This map must never classify a Table
// from DataHub TAG metadata or participate in per-Table inclusion.
const k9ServiceCeilingToGrade = Object.freeze({
  PUBLIC: 'normal',
  INTERNAL: 'normal',
  CONFIDENTIAL: 'credential',
  RESTRICTED: 'restricted',
})
const k9SourceFailureStages = new Set([
  'INVENTORY',
  'INVENTORY_PROJECTION',
  'LINEAGE_COLLECTION',
  'METADATA_COLLECTION',
  'RUNTIME_IDENTITY',
])
const k9SourceFailureDetails = new Set([
  'CONNECTIVITY',
  'TIMEOUT',
  'HTTP_4XX',
  'HTTP_5XX',
  'GRAPHQL',
  'CONTRACT',
  'EMPTY_SOURCE',
  'INTERNAL_TRANSFORM',
  ...K9_LINEAGE_FAILURE_DETAILS,
  ...K9_METADATA_FAILURE_DETAILS,
])
const k9V2FailureCodes = new Set(K9_V2_FAILURE_CODES)

const mcpReadToolCapabilities = Object.freeze({
  metadata_search: 'catalog.read',
  knowledge_graph_assets: 'knowledge.read',
  knowledge_lineage_traversal: 'knowledge.read',
  knowledge_release_snapshot: 'knowledge.read',
  knowledge_release_graphrag: 'knowledge.read',
})

// CR intake: POST /poc-api/change-requests — any active role with change.read.

// CR command (lifecycle mutations): POST /poc-api/change-requests/:id/commands
// CR read: GET /poc-api/change-requests/:id

const mimeTypes = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.woff2': 'font/woff2',
}

function defaultAirflowControlProvider() {
  return Object.freeze({
    inventory: airflowDagInventory,
    readRun: readAirflowDagRun,
    setPaused: setAirflowDagPaused,
    trigger: triggerControlledAirflowDag,
  })
}

export function resolvePocServerHost(environment = process.env) {
  return environment.POC_SERVER_HOST?.trim() || '127.0.0.1'
}

export async function startPocServer({ stateStore } = {}) {
  if (!existsSync(join(staticDirectory, 'index.html'))) throw new Error('Run npm run build before starting the server.')
  const serverStateStore = stateStore ?? pocStateStore
  if (stateStore) pocStateStore = stateStore
  const authenticator = createPocLocalAuthenticator({ stateStore: serverStateStore })
  serverBackgroundAbortController = new AbortController()
  backgroundLaunchesStopped = false
  k9V2LifecycleRequested = false
  reconcileK9SemanticGeneration = async () => ({ status: 'unavailable' })
  const backgroundSignal = serverBackgroundAbortController.signal
  const schedulerConfig = loadPocChangeHistorySchedulerConfig()
  let captureMcl
  if (schedulerConfig.enabled) {
    const { discoverPocMclSource } = await import('./modules/mcl/discovery.mjs')
    const { createPocMclCapture } = await import('./modules/mcl/capture.mjs')
    try {
      const discovery = await discoverPocMclSource({ providerTransport })
      for (const [name, value] of Object.entries({
        POC_MCL_KAFKA_TOPIC: discovery.captureConfig.topic,
        POC_MCL_SOURCE_IDENTITY_HASH: discovery.captureConfig.sourceIdentityHash,
        POC_MCL_SCHEMA_CONTRACT_HASH: discovery.captureConfig.schemaContractHash,
        POC_MCL_PROVIDER_NAME: discovery.captureConfig.providerName,
        POC_MCL_PROVIDER_VERSION: discovery.captureConfig.providerVersion,
        POC_MCL_SCHEMA_REGISTRY_URL: discovery.captureConfig.schemaRegistry.host,
      })) process.env[name] = String(value)
      await serverStateStore.write('mcl-discovery-v1', discovery.receipt)
      await serverStateStore.writeChangeHistoryRuntimeStatus({
        state: 'READY', observedAt: new Date().toISOString(),
      })
      const capture = createPocMclCapture({ config: discovery.captureConfig, stateStore: serverStateStore })
      captureMcl = () => capture.run()
    } catch (error) {
      const diagnostic = await persistMclRuntimeFailure({
        stateStore: serverStateStore,
        error,
        fallbackClassification: 'PREP_MCL_DISCOVERY_RUNTIME_UNEXPECTED_FAILED',
        fallbackStage: 'DISCOVERY_RUNTIME',
        fallbackDetailCode: 'UNCLASSIFIED_DISCOVERY_ERROR',
      })
      captureMcl = async () => {
        throw Object.assign(new Error('MCL runtime discovery is unavailable.'), {
          code: diagnostic.classification,
          mclStage: diagnostic.failureStage,
          mclDetailCode: diagnostic.failureDetailCode,
        })
      }
    }
  }
  const scheduler = createPocChangeHistoryScheduler({
    config: schedulerConfig,
    stateStore: serverStateStore,
    captureMcl,
    reconcileCatalog: () => startDatahubInventoryRefresh({ signal: backgroundSignal }),
    async onCaptureState(status) {
      await serverStateStore.writeChangeHistoryCaptureStatus(status)
      if (status.state === 'HISTORY_GAP_BLOCKED') {
        await serverStateStore.writeChangeHistoryRuntimeStatus({
          state: 'CAPTURE_FAILED',
          classification: 'PREP_MCL_CAPTURE_HISTORY_GAP_BLOCKED',
          failureStage: 'RETENTION_CHECK',
          failureDetailCode: 'CHECKPOINT_BEHIND_LOW_WATERMARK',
          observedAt: status.observedAt,
        })
      } else {
        await serverStateStore.writeChangeHistoryRuntimeStatus({
          state: 'READY', observedAt: status.observedAt,
        })
      }
    },
    async onError(error) {
      try {
        const diagnostic = await persistMclRuntimeFailure({
          stateStore: serverStateStore,
          error,
        })
        process.stderr.write(`POC change-history scheduler: ${diagnostic.classification}\n`)
      } catch {
        process.stderr.write('POC change-history scheduler: PREP_MCL_CAPTURE_DIAGNOSTIC_PERSIST_FAILED\n')
      }
    },
  })

  const k9SchedulerConfig = loadPocK9SchedulerConfig()
  k9V2LifecycleRequested = k9SchedulerConfig.requested
  const k9Neo4jAdapter = {
    run: async (stmt, params) => {
      // Managed refresh performs bounded batches plus an exact large read-back
      // validation. Keep interactive Neo4j calls at the normal provider bound,
      // while allowing only this versioned staging adapter enough time to
      // validate and atomically promote a complete projection.
      const result = await neo4jQuery(stmt, params, 60_000)
      return result.map(r => r.row)
    }
  }
  const k9 = createK9ManagedGraphs({
    stateStore: pocStateStore,
    neo4j: k9Neo4jAdapter,
    schedule: k9SchedulerConfig.schedule,
    classificationCeiling: k9SchedulerConfig.classificationCeiling,
    log: { warn: (msg) => process.stderr.write(`K9 warning: ${msg}\n`) },
  })

  const k9ClassificationRanks = Object.freeze({
    PUBLIC: 0,
    INTERNAL: 1,
    CONFIDENTIAL: 2,
    RESTRICTED: 3,
  })

  function k9AssetUrn(item) {
    const urn = item?.external_urn || item?.urn || item?.id
    if (!isCanonicalDatahubDatasetUrn(urn)) throw new Error('Invalid DataHub identity in K9 source inventory')
    return urn
  }

  function k9ProjectionClassification(_item, ceiling) {
    if (!Object.hasOwn(k9ClassificationRanks, ceiling)) throw new Error('Unknown K9 classification ceiling')
    // This is an explicit Product-owned graph projection label. Free-form
    // DataHub TAG values never decide source inclusion or Table authorization.
    return ceiling
  }

  function k9MetadataProperties(asset, field) {
    const source = field || asset
    const datasetUrn = k9AssetUrn(asset)
    const properties = {
      external_urn: field?.urn || datasetUrn,
      dataset_urn: field ? datasetUrn : undefined,
      parent_table_id: field ? `TABLE:${datasetUrn}` : undefined,
      name: field?.fieldPath || asset.name,
      qualified_name: field ? `${asset.qualified_name || asset.name}.${field.fieldPath}` : asset.qualified_name || asset.name,
      platform: asset.platform,
      dataset_kind: asset.dataset_kind,
      database_name: asset.database_name,
      schema_name: asset.schema_name,
      description: source.description || '',
      domain: asset.domain || '',
      business_name: field?.label || asset.name,
      data_type: field?.type || undefined,
      native_data_type: field?.nativeDataType || undefined,
      nullable: field ? field.nullable !== false : undefined,
      is_part_of_key: field?.isPartOfKey === true || undefined,
      is_partitioning_key: field?.isPartitioningKey === true || undefined,
      json_path: field?.jsonPath || undefined,
      custom_properties: field ? undefined : asset.custom_properties,
      structured_properties: field ? field.structured_properties : asset.structured_properties,
      tags: [...new Set(field
        ? (field.globalTags?.tags || []).map((item) => item.tag?.properties?.name || item.tag?.name).filter(Boolean)
        : asset.tags || [])].sort(),
      terms: [...new Set(field
        ? (field.glossaryTerms?.terms || []).map((item) => item.term?.properties?.name || item.term?.name).filter(Boolean)
        : asset.terms || [])].sort(),
      source_aspects: field
        ? ['schemaMetadata', 'editableSchemaMetadata', 'globalTags', 'glossaryTerms', 'structuredProperties']
        : ['datasetProperties', 'editableDatasetProperties', 'globalTags', 'glossaryTerms', 'domains', 'structuredProperties'],
    }
    return Object.fromEntries(Object.entries(properties).filter(([, value]) => (
      value !== undefined && value !== null && value !== ''
      && (!Array.isArray(value) || value.length > 0)
    )))
  }

  async function collectLineageInventorySeam(authorityPin, inventory, { reportProgress = null } = {}) {
    if (!inventory || !inventory.length) throw new Error('Incomplete inventory')
    const authorizedInventory = inventory.flatMap((item) => {
      const classification = k9ProjectionClassification(item, authorityPin.classification_ceiling)
      return [{ item, classification }]
    })
    const authorizedByUrn = new Map(authorizedInventory.map((entry) => [k9AssetUrn(entry.item), entry]))
    const nodes = []
    const edges = []
    const edgeMap = new Map()
    const nodeSet = new Set()
    const columnNodeMap = new Map()
    const completeness_metadata = { per_asset: {} }
    let processedAssetCount = 0
    const publishLineageProgress = () => {
      processedAssetCount += 1
      if (typeof reportProgress !== 'function') return
      try {
        reportProgress({ completed: processedAssetCount, total: authorizedInventory.length })
      } catch {
        // Execution-only progress must not alter lineage capture correctness.
      }
    }

    const registerLineageEdge = (source, target, relationship, sourceEntityUrn) => {
      const key = `${source}->${target}`
      const observation = {
        source: 'DataHub',
        source_aspect: 'upstreamLineage',
        source_relationship_type: relationship?.type || 'TRANSFORMED',
        explicit_or_inferred: 'EXPLICIT',
        confidence: 1,
        source_entity_urn: sourceEntityUrn,
        observed_at: relationship?.updatedOn || relationship?.createdOn || null,
        created_actor: relationship?.createdActor?.urn || null,
        updated_actor: relationship?.updatedActor?.urn || null,
        is_manual: relationship?.isManual === true,
        degree: relationship?.degree || null,
        lineage_paths: (relationship?.paths || []).map((path) => (
          (path.path || []).map((entity) => ({ urn: entity.urn, type: entity.type }))
        )),
        lineage_level: 'TABLE',
      }
      const existing = edgeMap.get(key)
      if (existing) {
        const observations = [...(existing.properties.lineage_observations || []), observation]
        const unique = new Map(observations.map((item) => [canonicalJson(item), item]))
        existing.properties.lineage_observations = [...unique.entries()]
          .sort(([left], [right]) => left.localeCompare(right))
          .map(([, item]) => item)
      } else {
        edgeMap.set(key, {
          source_asset_id: source,
          target_asset_id: target,
          properties: { ...observation, lineage_observations: [observation] },
        })
      }
    }

    const registerColumnNode = (datasetUrn, path) => {
      if (!isCanonicalDatahubDatasetUrn(datasetUrn) || typeof path !== 'string' || !path.trim()) return null
      const authorized = authorizedByUrn.get(datasetUrn)
      if (!authorized) return null
      const field = datahubSchemaFields(authorized.item).find((candidate) => candidate.fieldPath === path.trim())
      if (!field) return null
      const id = `COLUMN:${datasetUrn}:${path.trim()}`
      if (!columnNodeMap.has(id)) {
        columnNodeMap.set(id, {
          id,
          classification: authorized.classification,
          properties: k9MetadataProperties(authorized.item, field),
        })
      }
      return id
    }

    for (const { item, classification } of authorizedInventory) {
      if (!['TABLE', 'VIEW', 'MATERIALIZED_VIEW'].includes(item.dataset_kind)) {
        publishLineageProgress()
        continue
      }
      const itemUrn = k9AssetUrn(item)

      const nodeId = 'TABLE:' + itemUrn
      if (nodeSet.has(nodeId)) throw new Error('Duplicate node identity: ' + nodeId)
      nodeSet.add(nodeId)
      nodes.push({
        id: nodeId,
        classification,
        ...k9MetadataProperties(item),
      })

      completeness_metadata.per_asset[itemUrn] = {}
      for (const direction of ['UPSTREAM', 'DOWNSTREAM']) {
        const trace = createK9LineageTrace({
          assetIdentity: itemUrn,
          direction,
          requestedCount: 100,
          maximumPages: 10_002,
          totalAssetCount: authorizedInventory.length,
          processedAssetCount,
        })
        while (true) {
          const start = trace.nextStart
          const data = await datahubRefreshGraphql(datahubLineageQuery, {
            urn: itemUrn,
            input: { direction, start, count: 100, separateSiblings: false, includeGhostEntities: false }
          }, serverBackgroundAbortController?.signal)
          const lineage = data?.dataset?.lineage
          const page = trace.observePage(lineage)
          for (const rel of page.relationships) {
            if (!rel || typeof rel !== 'object' || Array.isArray(rel)
              || typeof rel.type !== 'string' || !rel.type
              || !rel.entity || typeof rel.entity !== 'object' || Array.isArray(rel.entity)
              || typeof rel.entity.urn !== 'string' || !rel.entity.urn
              || typeof rel.entity.type !== 'string' || !rel.entity.type) {
              trace.rejectMalformedRelationship()
            }
            if (rel.entity.type === 'DATASET') {
              if (!isCanonicalDatahubDatasetUrn(rel.entity.urn)) trace.rejectMalformedRelationship()
              const relAsset = datasetAsset(rel.entity)
              if (relAsset && authorizedByUrn.has(rel.entity.urn)
                && ['TABLE', 'VIEW', 'MATERIALIZED_VIEW'].includes(relAsset.dataset_kind)) {
                const source = direction === 'UPSTREAM' ? 'TABLE:' + rel.entity.urn : 'TABLE:' + itemUrn
                const target = direction === 'UPSTREAM' ? 'TABLE:' + itemUrn : 'TABLE:' + rel.entity.urn
                const edgeKey = `${source}->${target}`
                const observationDisposition = trace.observeRelationship({
                  observationIdentity: canonicalHash({ edge_key: edgeKey, relationship: rel }),
                  edgeIdentity: edgeKey,
                })
                if (observationDisposition === 'EXACT_DUPLICATE') continue
                registerLineageEdge(source, target, rel, itemUrn)
                trace.recordProjectableTableEdge()
              } else {
                trace.recordOutsideSourceScope()
              }
            } else {
              trace.recordOutsideSourceScope()
            }
          }
          if (page.done) break
        }
        const completedTrace = trace.complete()
        completeness_metadata.per_asset[itemUrn][direction] = {
          returned: completedTrace.returned,
          filtered: completedTrace.filtered,
          total: completedTrace.total,
          pages: completedTrace.pages,
        }
      }

      for (const fine of item.fine_grained_lineages || []) {
        for (const upstream of fine.upstreams || []) {
          const upstreamId = registerColumnNode(upstream.urn, upstream.path)
          if (!upstreamId) continue
          for (const downstream of fine.downstreams || []) {
            const downstreamId = registerColumnNode(downstream.urn, downstream.path)
            if (!downstreamId) continue
            const key = `${upstreamId}->${downstreamId}`
            const observation = {
              source_entity_urn: itemUrn,
              source_relationship_type: fine.transform_operation || 'COLUMN_TRANSFORM',
              transformation_query: fine.query || null,
            }
            const existing = edgeMap.get(key)
            if (existing) {
              const observations = [...(existing.properties.lineage_observations || []), observation]
              const unique = new Map(observations.map((item) => [canonicalJson(item), item]))
              existing.properties.lineage_observations = [...unique.entries()]
                .sort(([left], [right]) => left.localeCompare(right))
                .map(([, item]) => item)
              continue
            }
            edgeMap.set(key, {
              source_asset_id: upstreamId,
              target_asset_id: downstreamId,
              properties: {
                source: 'DataHub',
                source_aspect: 'fineGrainedLineages',
                source_relationship_type: fine.transform_operation || 'COLUMN_TRANSFORM',
                explicit_or_inferred: 'EXPLICIT',
                confidence: 1,
                source_entity_urn: itemUrn,
                observed_at: null,
                lineage_level: 'COLUMN',
                transformation_query: fine.query || null,
                lineage_observations: [observation],
              },
            })
          }
        }
      }
      publishLineageProgress()
    }
    nodes.push(...columnNodeMap.values())
    edges.push(...edgeMap.values())
    edges.sort((a, b) => a.source_asset_id.localeCompare(b.source_asset_id) || a.target_asset_id.localeCompare(b.target_asset_id))
    return {
      authority_pin: authorityPin,
      direction: 'BOTH',
      depth: 1,
      truncated: false,
      completeness_metadata,
      nodes,
      column_nodes: [...columnNodeMap.values()],
      edges,
    }
  }

  let reportK9RefreshProgress = () => false

  async function collectGlossaryInventorySeam(authorityPin, inventory, {
    retryAttempt = 1,
    reportSourceProgress = null,
  } = {}) {
    const collectMetadata = createK9MetadataCollector({
      refreshGraphql: datahubRefreshGraphql,
      glossaryQuery: datahubK9GlossaryQuery,
      glossaryTermsQuery: datahubK9GlossaryTermsByUrnsQuery,
      relationshipsQuery: datahubEntityRelationshipsQuery,
      buildScrollVariables: buildK9GlossaryScrollVariables,
      schemaFields: datahubSchemaFields,
      sourceClassification: k9ProjectionClassification,
      assetUrn: k9AssetUrn,
      metadataProperties: k9MetadataProperties,
      customProperties: customPropertyReferences,
      structuredProperties: structuredPropertyReferences,
      tagNameSource: (reference) => reference?._k9_name_source,
      urnTail,
      signal: serverBackgroundAbortController?.signal,
    })
    return collectMetadata(authorityPin, inventory, {
      sourceGeneration: inventorySnapshot?.projection?.source_generation || null,
      retryAttempt,
      reportProgress: (progress) => {
        if (typeof reportSourceProgress === 'function') {
          reportSourceProgress({
            completed: progress?.completed_resolution_count,
            total: progress?.total,
            batch_number: progress?.batch_number,
            batch_total: progress?.batch_total,
          })
        }
      },
      reportDatasetProgress: typeof reportSourceProgress === 'function'
        ? (progress) => reportSourceProgress(progress)
        : null,
    })
  }

  async function resolveLiveK9AuthCtx() {
    const k9SubjectId = process.env.POC_K9_SYSTEM_SUBJECT_ID?.trim()
    const k9WorkspaceId = process.env.POC_K9_WORKSPACE_ID?.trim()
    const mcpSubjectId = process.env.POC_MCP_SUBJECT_ID?.trim()
    if (!k9SubjectId || !k9WorkspaceId) throw new Error('K9 system subject or workspace configuration missing')
    if (k9SubjectId === mcpSubjectId) throw new Error('K9 system subject must not be the same as MCP service subject')

    const localCreds = await pocStateStore.listLocalCredentialAdministration()
    const k9Creds = localCreds.filter(c => c.subjectId === k9SubjectId)
    if (k9Creds.length !== 1) throw new Error('Zero or duplicate K9 credentials for subject ID')
    const k9Cred = k9Creds[0]
    if (!k9Cred.loginEnabled || (k9Cred.lockedUntil && Date.parse(k9Cred.lockedUntil) > Date.now())) {
      throw new Error('K9 system subject login is disabled or currently locked')
    }
    if (k9Cred.mustChangePassword) throw new Error('K9 system subject requires password change')

    const snapshot = await pocStateStore.readChangeHistoryAccess()
    if (snapshot.access.value === null) throw new Error('Access not provisioned')
    const document = changeHistoryDocumentFromSnapshot(snapshot)
    const user = changeHistoryActiveUser(document, k9SubjectId)
    if (user.role !== 'manager') throw new Error('K9 system subject is not a manager')
    const requiredGrade = k9ServiceCeilingToGrade[k9SchedulerConfig.classificationCeiling]
    if (!requiredGrade || securityGradeRank(user.max_security_grade || 'normal') < securityGradeRank(requiredGrade)) {
      throw new Error('K9 system subject security grade is below the configured classification ceiling')
    }
    if (k9Cred.activeSessionCount !== 0) throw new Error('K9 system subject must not have active sessions')

    const principal = { ...user, subjectId: user.subject_id }
    const authorizationFingerprint = canonicalHash({
      subject_id: user.subject_id,
      active: user.active,
      role: user.role,
      max_security_grade: user.max_security_grade,
      classification_ceiling: k9SchedulerConfig.classificationCeiling,
    })

    return {
      principal,
      workspaceId: k9WorkspaceId,
      authorityPin: {
        subject_id: k9SubjectId,
        workspace_id: k9WorkspaceId,
        classification_ceiling: k9SchedulerConfig.classificationCeiling,
        projection_version: 2,
        policy_version: 'POC_DATAHUB_SEMANTIC_MODEL_V2',
        classification_policy_version: 1,
        authorization_generation: snapshot.access.version,
        authorization_fingerprint: authorizationFingerprint,
      }
    }
  }

  let reportK9LifecycleTransition = () => false
  let triggerK9Refresh
  if (k9SchedulerConfig.requested) {
    const lifecycle = Object.freeze({
      readLifecycle: (...args) => pocStateStore.readK9SnapshotLifecycleV2(...args),
      readStagedSourceEvidence: (...args) => pocStateStore.readK9StagedSourceEvidenceV2(...args),
      setDesiredSnapshot: (...args) => pocStateStore.setK9DesiredSourceSnapshotV2(...args),
      appendProjectorReceipt: (...args) => pocStateStore.appendK9ProjectorReceiptV2(...args),
      promoteActiveSnapshot: (...args) => pocStateStore.promoteK9ActiveSourceSnapshotV2(...args),
    })
    const receipts = createK9V2LifecycleReceiptPort({ lifecycle })
    let latestK9SourceEligibility = null
    const captureSource = createPocK9SourceCaptureTask({
      resolveAuthContext: resolveLiveK9AuthCtx,
      // K9 projects the canonical current Dataset scope. TAG classification is
      // bounded quality telemetry; exact grants remain request-time authority.
      currentInventory: async (liveAuth) => {
        const selection = selectCanonicalK9SourceInventory(await currentDatahubInventory(), {
          classificationCeiling: liveAuth.authorityPin.classification_ceiling,
        })
        latestK9SourceEligibility = selection.telemetry
        if (selection.items.length === 0) {
          throw Object.assign(new Error('The canonical K9 source inventory is empty.'), {
            k9SourceFailureDetailCode: 'EMPTY_SOURCE',
            k9SourceEligibility: selection.telemetry,
          })
        }
        return selection.items
      },
      inventoryProjection: (_liveAuth, inventory) => buildK9SourceInventoryProjection({
        items: inventory,
        sourceScope: 'DATARIVER_K9_AUTHORIZED_INVENTORY_V2',
        eligibility: latestK9SourceEligibility,
      }),
      collectLineage: collectLineageInventorySeam,
      collectMetadata: collectGlossaryInventorySeam,
      runtimeIdentity: datahubRuntimeIdentity,
      buildSourceCapture: buildDatahubKnowledgeSourceCapture,
      reportProgress: (progress) => reportK9RefreshProgress(progress),
    })
    const graphProjectors = createK9GraphProjectors({
      persistence: lifecycle,
      managedGraphs: k9,
      resolveAuthContext: resolveLiveK9AuthCtx,
    })
    const bindingHash = catalogEmbeddingBindingHash()
    if (!bindingHash || !llm.embedding) {
      throw new Error('The configured K9 V2 lifecycle requires an Embedding provider binding.')
    }
    const semanticProjector = createK9V2SemanticLifecycleProjector({
      bindingHash,
      model: llm.embedding.model,
      lifecycle,
      semanticPersistence: pocStateStore.k9SemanticPersistenceV2,
      renderDocument: catalogEmbeddingDocument,
      projectMetadata: publicDatahubAsset,
      provider: {
        embed: ({ model, input, signal }) => llmRequest(
          llm.embedding,
          '/embeddings',
          { model, input },
          llmProviderTimeoutMs,
          signal,
        ),
      },
    })
    triggerK9Refresh = createPocK9V2RefreshTask({
      captureSource,
      receipts,
      projectors: Object.freeze({ ...graphProjectors, SEMANTIC: semanticProjector }),
      onTransition: (event) => reportK9LifecycleTransition(event),
    })
  }

  const reportK9SchedulerError = (error) => {
    process.stderr.write(`POC K9 scheduler: ${error instanceof Error ? error.message : String(error)}\n`)
  }

  const k9Scheduler = createPocK9Scheduler({
    config: k9SchedulerConfig,
    stateStore: pocStateStore,
    triggerK9Refresh,
    // V2 projector receipts bind directly to source_snapshot_id. The legacy
    // cross-generation reconciler remains readable but is not part of V2.
    resolveReconciliationGeneration: async () => null,
    onError: reportK9SchedulerError,
  })
  reportK9RefreshProgress = (progress) => k9Scheduler.updateProgress(progress)
  reportK9LifecycleTransition = (event) => k9Scheduler.updateLifecycleProgress(event)

  if (k9SchedulerConfig.requested) {
    const liveAuth = await resolveLiveK9AuthCtx()
    await k9.bootstrapK9Policies(liveAuth)
    await k9.performRestartRecovery()
  }

  // Start the refresh attempt before the HTTP listener becomes observable. The
  // managed-assets read model can then distinguish a retained terminal result
  // from the descendant Product's active, non-destructive retry.
  await k9Scheduler.start()
  const server = createPocServer({
    stateStore: serverStateStore,
    authenticator,
    k9SchedulerConfig,
    k9SchedulerStatus: () => k9Scheduler.currentAttempt(),
  })
  const host = resolvePocServerHost()
  const port = Number(process.env.POC_SERVER_PORT || process.env.POC_PORT || 39080)
  await new Promise((resolvePromise) => server.listen(port, host, resolvePromise))
  process.stdout.write(`DataRiver listening on http://${host}:${port}\n`)
  if (datahub && pocStateStore.configured.postgres) {
    void datahubInventory({ signal: backgroundSignal }).catch(() => undefined)
  }
  if (datahub && llm.embedding) scheduleCatalogEmbeddingRefresh()
  await scheduler.start()

  let stopping
  server.stopPoc = () => {
    if (!stopping) {
      backgroundLaunchesStopped = true
      reconcileK9SemanticGeneration = async () => ({ status: 'unavailable' })
      const serverClosed = server.listening
        ? new Promise((resolvePromise, reject) => server.close((error) => (
            error ? reject(error) : resolvePromise()
          )))
        : Promise.resolve()
      if (catalogEmbeddingRefreshTimer !== undefined) {
        clearTimeout(catalogEmbeddingRefreshTimer)
        catalogEmbeddingRefreshTimer = undefined
      }
      serverBackgroundAbortController.abort()
      const inventoryBackground = inventoryRefreshPromise
      const embeddingBackground = catalogEmbeddingRefreshPromise
      stopping = (async () => {
        await Promise.allSettled([
          serverClosed,
          scheduler.stop(),
          k9Scheduler.stop(),
          inventoryBackground,
          embeddingBackground,
        ])
        await pocStateStore.close?.()
      })()
    }
    return stopping
  }
  server.triggerChangeHistoryScheduler = (scheduledFor) => scheduler.triggerManual(scheduledFor)
  server.triggerK9Scheduler = (scheduledFor) => k9Scheduler.triggerManual(scheduledFor)
  server.on('close', () => { void server.stopPoc() })
  return server
}

if (resolve(process.argv[1] || '') === resolve(fileURLToPath(import.meta.url))) {
  startPocServer().then((server) => {
    let shuttingDown = false
    const shutdown = async () => {
      if (shuttingDown) return
      shuttingDown = true
      await server.stopPoc()
    }
    process.once('SIGINT', () => { void shutdown() })
    process.once('SIGTERM', () => { void shutdown() })
  }).catch((error) => {
    process.stderr.write(`${error instanceof Error ? error.stack : String(error)}\n`)
    process.exitCode = 1
  })
}
