import type {
  CatalogAsset,
  CatalogAssetDetail,
  CatalogLineage,
  CatalogPolicyMeta,
  ChangeRequestRecord,
  ChangeRequestSummary,
  ChatEvidence,
  ChatMessage,
  ChatResponse,
  ChatSession,
  KnowledgeAssetOperationalDetail,
  KnowledgeAssetSummary,
  KnowledgeGraph,
  KnowledgeRelease,
  KnowledgeSnapshot,
  QualityAsset,
} from '../api/types'

export const POC_WORKSPACE_ID = '00000000-0000-4000-8000-000000000061'
export const POC_SUBJECT_ID = '00000000-0000-4000-8000-000000000111'
export const POC_CACHE_SCOPE = 'a'.repeat(64)
export const POC_NOW = '2026-08-11T09:00:00.000Z'

export function authorizationWindow() {
  const observedAt = new Date()
  return {
    observed_at: observedAt.toISOString(),
    authorization_valid_until: new Date(observedAt.getTime() + 30_000).toISOString(),
  }
}

export const catalogMeta: CatalogPolicyMeta = {
  observed_at: POC_NOW,
  stale_at: null,
  projection_version: 1,
  policy_version: 'POC_SAMPLE_POLICY_V1',
  classification_policy_version: 1,
  authorization_generation: 1,
}

export const catalogAssets: CatalogAsset[] = [
  {
    id: '00000000-0000-4000-8000-000000000201',
    external_urn: 'urn:li:dataset:poc-wafer-events',
    asset_type: 'DATASET',
    name: 'wafer_inspection_events',
    description: '웨이퍼·Lot·검사 단계별 optical inspection event를 정규화한 sample 자산입니다.',
    platform: 'snowflake',
    database_name: 'MANUFACTURING',
    schema_name: 'QUALITY',
    owner: 'Yield Engineering',
    domain: 'Manufacturing Quality',
    tags: ['gold', 'hourly', 'inspection'],
    terms: ['Wafer', 'Defect', 'Inspection Step'],
    created_at: POC_NOW,
    classification: 'INTERNAL',
    lifecycle: 'ACTIVE',
    observed_at: POC_NOW,
    matches: [{ field: 'NAME', text: 'wafer_inspection_events', matched_terms: [] }],
  },
  {
    id: '00000000-0000-4000-8000-000000000202',
    external_urn: 'urn:li:dataset:poc-lot-genealogy',
    asset_type: 'DATASET',
    name: 'lot_genealogy',
    description: '제조 Lot의 parent/child 및 split 관계를 제공하는 sample 자산입니다.',
    platform: 'postgres',
    database_name: 'MES_CURATED',
    schema_name: 'CORE',
    owner: 'MES Data Office',
    domain: 'Manufacturing Operations',
    tags: ['certified', 'genealogy'],
    terms: ['Lot', 'Split Event'],
    created_at: POC_NOW,
    classification: 'INTERNAL',
    lifecycle: 'ACTIVE',
    observed_at: POC_NOW,
    matches: [{ field: 'NAME', text: 'lot_genealogy', matched_terms: [] }],
  },
  {
    id: '00000000-0000-4000-8000-000000000203',
    external_urn: 'urn:li:dataset:poc-yield-summary',
    asset_type: 'DATASET',
    name: 'yield_summary_daily',
    description: '제품군·Site·공정 단계별 일간 수율 sample 집계입니다.',
    platform: 'databricks',
    database_name: 'ANALYTICS',
    schema_name: 'YIELD',
    owner: 'Yield Analytics',
    domain: 'Executive Analytics',
    tags: ['executive', 'daily'],
    terms: ['First Pass Yield', 'Product Family'],
    created_at: POC_NOW,
    classification: 'CONFIDENTIAL',
    lifecycle: 'ACTIVE',
    observed_at: POC_NOW,
    matches: [{ field: 'NAME', text: 'yield_summary_daily', matched_terms: [] }],
  },
]

const schemaFields: Record<string, Array<Record<string, unknown>>> = {
  [catalogAssets[0]!.id]: [
    { field_path: 'wafer_id', native_data_type: 'VARCHAR(32)', description: 'Sample wafer identifier', nullable: false },
    { field_path: 'lot_id', native_data_type: 'VARCHAR(24)', description: 'Manufacturing lot identifier', nullable: false },
    { field_path: 'inspection_ts', native_data_type: 'TIMESTAMP', description: 'Inspection timestamp in UTC', nullable: false },
    { field_path: 'defect_code', native_data_type: 'VARCHAR(16)', description: 'Controlled defect taxonomy code', nullable: true },
    { field_path: 'defect_count', native_data_type: 'INTEGER', description: 'Observed sample defect count', nullable: false },
  ],
  [catalogAssets[1]!.id]: [
    { field_path: 'lot_id', native_data_type: 'VARCHAR(24)', description: 'Current lot identifier', nullable: false },
    { field_path: 'parent_lot_id', native_data_type: 'VARCHAR(24)', description: 'Parent lot before a split', nullable: true },
    { field_path: 'operation_id', native_data_type: 'VARCHAR(18)', description: 'Manufacturing operation', nullable: false },
  ],
  [catalogAssets[2]!.id]: [
    { field_path: 'business_date', native_data_type: 'DATE', description: 'Reporting date', nullable: false },
    { field_path: 'product_family', native_data_type: 'VARCHAR(40)', description: 'Sample product family', nullable: false },
    { field_path: 'stage_yield', native_data_type: 'DECIMAL(7,4)', description: 'Sample stage yield ratio', nullable: false },
  ],
}

export function catalogDetail(assetId: string, fieldOffset = 0): CatalogAssetDetail {
  const asset = catalogAssets.find((item) => item.id === assetId) ?? catalogAssets[0]!
  const fields = schemaFields[asset.id] ?? []
  return {
    ...asset,
    ownership: [{ owner: asset.owner, type: 'TECHNICAL_OWNER' }],
    glossary_terms: (asset.terms ?? []).map((term) => ({ urn: `urn:poc:term:${term}`, name: term })),
    tags: asset.tags ?? [],
    schema_fields: fields.slice(fieldOffset, fieldOffset + 100),
    schema_fields_total: fields.length,
    schema_fields_available: fields.length,
    schema_fields_truncated: false,
    schema_fields_total_exact: true,
    schema_fields_offset: fieldOffset,
    schema_fields_limit: 100,
    schema_fields_has_more: fieldOffset + 100 < fields.length,
    quality: { score_basis_points: asset.id === catalogAssets[0]!.id ? 9875 : 9600 },
    projection_source_version: 'poc-projection-v1',
    source_version: 'poc-provider-v1',
  }
}

export function catalogLineage(assetId: string): CatalogLineage {
  const center = catalogAssets.find((item) => item.id === assetId) ?? catalogAssets[0]!
  const nodes = [center, ...catalogAssets.filter((item) => item.id !== center.id).slice(0, 2)]
  return {
    center_asset_id: center.id,
    nodes,
    edges: nodes.length > 1 ? [{ source_asset_id: nodes[1]!.id, target_asset_id: center.id }] : [],
    direction: 'BOTH',
    depth: 2,
    truncated: false,
    meta: catalogMeta,
  }
}

export const qualityAsset: QualityAsset = {
  asset_id: catalogAssets[0]!.id,
  name: catalogAssets[0]!.name,
  platform: catalogAssets[0]!.platform,
  database_name: catalogAssets[0]!.database_name,
  schema_name: catalogAssets[0]!.schema_name,
  classification: 'INTERNAL',
  lifecycle: 'ACTIVE',
  profile_readiness: 'READY',
  profile_observed_at: POC_NOW,
  active_rule_set_count: 1,
  latest_run_state: 'SUCCEEDED',
  latest_quality_outcome: 'PASS',
  latest_score_basis_points: 9875,
}

export const qualityRuleSet = {
  rule_set_id: 'poc-quality-rule-set-1',
  asset_id: qualityAsset.asset_id,
  asset_name: qualityAsset.name,
  name: 'Wafer inspection essentials',
  state: 'ACTIVE',
  active_version_id: 'poc-quality-rule-version-1',
  active_version_number: 1,
  active_version_state: 'ACTIVE',
  rule_count: 2,
  created_at: POC_NOW,
  updated_at: POC_NOW,
  version: 1,
}

export const qualityRun = {
  run_id: 'poc-quality-run-1',
  rule_set_id: qualityRuleSet.rule_set_id,
  rule_set_name: qualityRuleSet.name,
  asset_id: qualityAsset.asset_id,
  asset_name: qualityAsset.name,
  trigger_kind: 'MANUAL',
  state: 'SUCCEEDED',
  quality_outcome: 'PASS',
  passed_count: 79,
  advisory_failed_count: 0,
  blocking_failed_count: 1,
  score_basis_points: 9875,
  created_at: POC_NOW,
  completed_at: '2026-08-11T09:00:02.000Z',
  failure_code: null,
  version: 1,
}

export const scorePolicy = {
  policy_id: 'UNWEIGHTED_RULE_PASS_RATE_V1',
  policy_version: 1,
  policy_hash: 'd'.repeat(64),
  calculation: 'passed / (passed + advisory_failed + blocking_failed)',
  pass_condition: 'evaluated > 0 and advisory_failed = 0 and blocking_failed = 0',
  warn_condition: 'blocking_failed = 0 and advisory_failed > 0',
  fail_condition: 'blocking_failed > 0',
  unknown_condition: 'evaluated = 0',
} as const

export const qualityAuthoring = {
  state: 'READY',
  reason_code: null,
  source_version: 'poc-provider-v1',
  schema_hash: 'c'.repeat(64),
  fields: [{
    field_identifier: 'wafer_id',
    display_path: 'wafer_id',
    logical_type: 'STRING',
    supported_rule_kinds: ['NOT_NULL'],
  }],
} as const

export const changeSummary: ChangeRequestSummary = {
  id: '00000000-0000-4000-8000-000000000401',
  number: 'CR-POC-06111-001',
  request_type: 'CATALOG_METADATA',
  title: 'Wafer inspection 설명 및 용어 정비',
  state: 'IN_REVIEW',
  requester_id: POC_SUBJECT_ID,
  requester_department_id: null,
  current_round_number: 1,
  created_at: POC_NOW,
  requested_due_date: '2026-08-18T00:00:00.000Z',
  priority: 'NORMAL',
  urgency: 'NORMAL',
  classification: 'INTERNAL',
  version: 1,
  item_count: 1,
  first_item: {
    target_ref: catalogAssets[0]!.external_urn,
    aspect_name: 'datasetProperties',
    operation: 'UPSERT',
  },
}

export function changeRecord(state = changeSummary.state, version = changeSummary.version): ChangeRequestRecord {
  return {
    ...changeSummary,
    state,
    version,
    description: 'Synthetic fixture를 이용해 기존 변경관리 상세 화면과 상태 전이를 시연합니다.',
    requester_department_id: null,
    current_round_id: '00000000-0000-4000-8000-000000000402',
    revision_allowed: true,
    items: [{
      id: '00000000-0000-4000-8000-000000000403',
      target_type: 'DATASET',
      target_ref: catalogAssets[0]!.external_urn,
      aspect_name: 'datasetProperties',
      operation: 'UPSERT',
      before_hash: '1'.repeat(64),
      after_hash: '2'.repeat(64),
      after_document: { description: 'Approved sample description' },
      target_asset_id: catalogAssets[0]!.id,
      target_asset_type: 'DATASET',
      target_system_id: null,
      target_domain_id: null,
      target_owner_department_id: null,
      target_classification: 'INTERNAL',
      target_lifecycle: 'ACTIVE',
      target_source_version: 'poc-provider-v1',
      target_observed_at: POC_NOW,
      target_binding_hash: '3'.repeat(64),
      routing_system_id: null,
    }],
    approvals: [],
    transitions: [],
    rounds: [{
      id: '00000000-0000-4000-8000-000000000402',
      round_number: 1,
      submitted_by: POC_SUBJECT_ID,
      submitted_at: POC_NOW,
      closed_at: null,
      evidence_hash: '4'.repeat(64),
      revision_kind: 'INITIAL',
      title: changeSummary.title,
      request_date: '2026-08-11',
      request_department: 'Yield Engineering',
      request_reason: 'Sample metadata quality improvement',
      request_content: 'Update the sample description and terms.',
      requested_due_date: changeSummary.requested_due_date,
      priority: changeSummary.priority,
      urgency: changeSummary.urgency,
      classification: changeSummary.classification,
      selected_system_id: null,
    }],
    test_runs: [],
  }
}

export const knowledgeAsset: KnowledgeAssetSummary = {
  id: '00000000-0000-4000-8000-000000000501',
  slug: 'yield-excursion-knowledge',
  name: 'Yield Excursion Knowledge',
  graph_type: 'SEMANTIC_KNOWLEDGE',
  status: 'ACTIVE',
  classification: 'INTERNAL',
  domain_id: null,
  domain_name: 'Manufacturing Quality',
  creator_name: 'POC Sample User',
  creator_email: 'sample.user@poc.invalid',
  editor_name: 'POC Sample User',
  editor_email: 'sample.user@poc.invalid',
  active_studio_release_id: '00000000-0000-4000-8000-000000000502',
  active_studio_release_no: 1,
  active_release_id: '00000000-0000-4000-8000-000000000503',
  active_release_no: 1,
  class_count: 3,
  property_count: 8,
  relationship_count: 2,
  binding_count: 1,
  source_count: 2,
  node_count: 3,
  edge_count: 2,
  projection_state: 'VERIFIED',
  created_at: POC_NOW,
  updated_at: POC_NOW,
  version: 1,
  delivery_policy: null,
}

export const knowledgeGraph: KnowledgeGraph = {
  id: knowledgeAsset.id,
  slug: knowledgeAsset.slug,
  name: knowledgeAsset.name,
  graph_type: knowledgeAsset.graph_type,
  status: knowledgeAsset.status,
  classification: knowledgeAsset.classification,
  domain_name: knowledgeAsset.domain_name ?? undefined,
  active_release_id: knowledgeAsset.active_release_id ?? undefined,
  created_by: POC_SUBJECT_ID,
  updated_by: POC_SUBJECT_ID,
  created_at: POC_NOW,
  updated_at: POC_NOW,
  version: 1,
}

export const knowledgeRelease: KnowledgeRelease = {
  id: knowledgeAsset.active_release_id!,
  graph_id: knowledgeAsset.id,
  release_no: 1,
  ontology_version_id: knowledgeAsset.active_studio_release_id!,
  content_hash: '5'.repeat(64),
  node_count: 3,
  edge_count: 2,
  published_by: POC_SUBJECT_ID,
  published_at: POC_NOW,
  publisher_name: 'POC Sample User',
  publisher_email: 'sample.user@poc.invalid',
}

const provenance = [{
  source_ref: catalogAssets[0]!.external_urn,
  source_locator: 'poc://catalog/wafer-inspection-events',
  source_version: 'sample-v1',
  method: 'SYNTHETIC_FIXTURE',
  confidence: 1,
}]

export const knowledgeSnapshot: KnowledgeSnapshot = {
  release: knowledgeRelease,
  nodes: [
    { id: 'wafer', entity_type: 'CLASS', properties: { name: 'Wafer' }, classification: 1, provenance },
    { id: 'inspection', entity_type: 'CLASS', properties: { name: 'Inspection' }, classification: 1, provenance },
    { id: 'defect', entity_type: 'CLASS', properties: { name: 'Defect' }, classification: 1, provenance },
  ],
  edges: [
    { id: 'edge-1', source_id: 'wafer', target_id: 'inspection', edge_type: 'HAS_INSPECTION', properties: {}, classification: 1, provenance },
    { id: 'edge-2', source_id: 'inspection', target_id: 'defect', edge_type: 'OBSERVES', properties: {}, classification: 1, provenance },
  ],
  filtered: false,
}

export const knowledgeDetail: KnowledgeAssetOperationalDetail = {
  asset: knowledgeAsset,
  schema_elements: [
    { stable_element_id: 'wafer', kind: 'CLASS', display_name: 'Wafer', canonical_name: 'Wafer', data_type: null, source_stable_element_id: null, target_stable_element_id: null },
    { stable_element_id: 'inspection', kind: 'CLASS', display_name: 'Inspection', canonical_name: 'Inspection', data_type: null, source_stable_element_id: null, target_stable_element_id: null },
  ],
  bindings: [],
  projections: [{
    id: 'poc-projection-1',
    release_id: knowledgeRelease.id,
    adapter: 'POC_MEMORY',
    state: 'VERIFIED',
    node_count: 3,
    edge_count: 2,
    verified_at: POC_NOW,
    error_code: null,
    updated_at: POC_NOW,
  }],
}

export const chatEvidence: ChatEvidence = {
  chunk_id: 'poc-evidence-1',
  resource_id: catalogAssets[0]!.id,
  classification: 'INTERNAL',
  system_id: null,
  domain_id: null,
  owner_department_id: null,
  name: catalogAssets[0]!.name,
  description: 'Synthetic catalog and quality evidence.',
  source_type: 'CATALOG_ASSET',
  source_locator: 'poc://catalog/wafer-inspection-events',
  source_version: 'sample-v1',
  content_hash: '6'.repeat(64),
  effective_from: POC_NOW,
  effective_until: null,
  extraction_method: 'SYNTHETIC_FIXTURE',
  rank: 1,
  retrieval_method: 'VECTOR',
}

export const chatWorkflow = [
  'AUTHORIZATION',
  'BUDGET_RESERVATION',
  'ROUTING',
  'RETRIEVAL',
  'RERANKING',
  'COMPOSITION',
  'CITATION_VALIDATION',
  'PERSISTENCE',
].map((stage) => ({ stage, status: 'COMPLETED', detail_code: 'POC_MEMORY_ONLY' })) as ChatResponse['workflow']

export const initialChatSession: ChatSession = {
  id: '00000000-0000-4000-8000-000000000601',
  title: 'Wafer inspection 품질 상태',
  is_favorite: false,
  version: 1,
  created_at: POC_NOW,
  updated_at: POC_NOW,
  message_count: 2,
}

export const initialChatMessages: ChatMessage[] = [
  {
    id: '00000000-0000-4000-8000-000000000602',
    session_id: initialChatSession.id,
    role: 'user',
    content: '최근 wafer inspection 품질 상태와 근거를 알려줘',
    evidence_json: null,
    created_at: POC_NOW,
    route: null,
    workflow: [],
  },
  {
    id: '00000000-0000-4000-8000-000000000603',
    session_id: initialChatSession.id,
    role: 'assistant',
    content: 'Sample `wafer_inspection_events`의 품질 점수는 **98.75%**입니다. 이 답변은 POC fixture 근거만 사용하며 실제 시스템 상태를 의미하지 않습니다.',
    evidence_json: [chatEvidence],
    created_at: POC_NOW,
    route: { requested_mode: 'AUTO', selected_mode: 'VECTOR', reason: 'SEMANTIC_INTENT', adapter_state: 'READY' },
    workflow: chatWorkflow,
  },
]
