import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type {
  CatalogAsset,
  CatalogAssetDetail,
  CatalogSearch,
  ChangeRequestRecord,
  ClassificationPolicySummary,
  KnowledgeAssetOperationalDetail,
  KnowledgeAssetPage,
  KnowledgeAssetVersionHistoryPage,
  KnowledgeDeliveryPolicy,
  SystemConfigurationEntry,
  SystemConfigurationTestResult,
  WorkspaceMembershipSummary,
} from '../api/types'
import type {
  KnowledgeStudioDraft,
  KnowledgeStudioRelease,
} from '../features/knowledge/studio/knowledgeStudioApi'
import { QualityApi } from '../features/quality/qualityApi'
import { GovernanceDocumentsApi } from '../features/governance-documents/governanceDocumentsApi'
import type { ChangeHistoryAccessDocument } from '../features/change-history/types'
import {
  changeRequestDashboardProgress,
  configurePocAuthorization,
  isResubmittedReviewForOverview,
  resetPocMemory,
  useStableApiClient,
} from './pocApi'
import { POC_SUBJECT_ID, POC_WORKSPACE_ID } from './pocContracts'

describe('POC change-request dashboard progress', () => {
  it('maps every canonical state into the same four presentation groups', () => {
    const progress = changeRequestDashboardProgress([
      { state: 'REGISTERED' },
      { state: 'IN_REVIEW' },
      { state: 'TESTING' },
      { state: 'FINAL_REVIEW' },
      { state: 'APPLY_QUEUED' },
      { state: 'APPLYING' },
      { state: 'APPLIED' },
      { state: 'APPLY_FAILED' },
      { state: 'COMPLETED' },
      { state: 'CHANGES_REQUESTED' },
      { state: 'REJECTED' },
      { state: 'CANCELLED' },
    ])

    expect(progress.change_request_progress).toEqual({
      total: 12,
      groups: { REGISTERED: 1, IN_PROGRESS: 7, COMPLETED: 2, CLOSED: 2 },
      complete: true,
    })
  })

  it('fails the presentation aggregate closed for an unknown persisted state', () => {
    const progress = changeRequestDashboardProgress([
      { state: 'UNKNOWN_LEGACY' as ChangeRequestRecord['state'] },
    ])

    expect(progress).toEqual({
      changes_by_state: null,
      change_request_progress: {
        total: null,
        groups: { REGISTERED: null, IN_PROGRESS: null, COMPLETED: null, CLOSED: null },
        complete: false,
      },
    })
  })
})

const meta = {
  observed_at: '2026-08-11T10:00:00.000Z',
  stale_at: null,
  projection_version: 1,
  policy_version: 'POC_LIVE_PROVIDER_V1',
  classification_policy_version: 1,
  authorization_generation: 1,
}

const liveAssets: CatalogAsset[] = [
  {
    id: 'urn:li:dataset:(urn:li:dataPlatform:postgres,FACTORY.QUALITY.wafer_events,PROD)',
    external_urn: 'urn:li:dataset:(urn:li:dataPlatform:postgres,FACTORY.QUALITY.wafer_events,PROD)',
    asset_type: 'DATASET',
    name: 'wafer_events',
    description: 'Live wafer inspection events',
    platform: 'postgres',
    database_name: 'FACTORY',
    schema_name: 'QUALITY',
    owner: 'quality',
    domain: 'manufacturing',
    tags: ['gold'],
    terms: ['Wafer'],
    classification: 'INTERNAL',
    lifecycle: 'ACTIVE',
    observed_at: meta.observed_at,
    matches: [{ field: 'NAME', text: 'wafer_events', matched_terms: ['wafer'] }],
  },
  {
    id: 'urn:li:dataset:(urn:li:dataPlatform:snowflake,ANALYTICS.YIELD.daily_yield,PROD)',
    external_urn: 'urn:li:dataset:(urn:li:dataPlatform:snowflake,ANALYTICS.YIELD.daily_yield,PROD)',
    asset_type: 'DATASET',
    name: 'daily_yield',
    description: 'Live daily yield',
    platform: 'snowflake',
    database_name: 'ANALYTICS',
    schema_name: 'YIELD',
    owner: 'yield',
    domain: 'manufacturing',
    tags: ['certified'],
    terms: ['Yield'],
    classification: 'INTERNAL',
    lifecycle: 'ACTIVE',
    observed_at: meta.observed_at,
    matches: [{ field: 'NAME', text: 'daily_yield', matched_terms: [] }],
  },
]

function json(value: unknown) {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

function installGatewayMock() {
  let knowledgeProjectionReceipt: Record<string, unknown> | null = null
  let knowledgeIngestionReceipt: Record<string, unknown> | null = null
  let coreState: Record<string, unknown> | null = null
  let coreVersion = 1
  let access: ChangeHistoryAccessDocument & { version: number } = {
    schema_version: 1,
    active_subject_id: 'checkpoint-admin',
    policy: {
      version: 1,
      priority_order: 'ASCENDING',
      fallback: ['DATA_STEWARD', 'DEVELOPER', 'DATAHUB_OWNER', 'UNASSIGNED'],
    },
    users: [{
      subject_id: 'checkpoint-admin', role: 'admin', active: true, provider_owner_refs: [],
      username: 'checkpoint-admin', display_name: 'Checkpoint Admin', email: 'admin@poc.invalid',
      first_name: 'Checkpoint', last_name: 'Admin', department_id: null, job_function: 'admin',
    }],
    systems: [],
    system_schema_scopes: [],
    system_assignments: [],
    version: 1,
  }
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, options?: RequestInit) => {
    const requestUrl = input instanceof Request ? input.url : input.toString()
    const url = new URL(requestUrl, 'https://poc.invalid')
    if (url.pathname === '/poc-api/state/core') {
      if ((options?.method ?? 'GET') === 'PUT') {
        if (new Headers(options?.headers).get('If-Match') !== `"${coreVersion}"`) {
          return Promise.resolve(new Response(JSON.stringify({ detail: 'stale' }), {
            status: 409,
            headers: { 'Content-Type': 'application/json' },
          }))
        }
        if (typeof options?.body !== 'string') throw new Error('Expected core state JSON')
        coreState = (JSON.parse(options.body) as { value: Record<string, unknown> }).value
        coreVersion += 1
      }
      return Promise.resolve(new Response(JSON.stringify({ value: coreState, version: coreVersion }), {
        status: 200,
        headers: { 'Content-Type': 'application/json', ETag: `"${coreVersion}"` },
      }))
    }
    if (url.pathname === '/api/v1/change-history/access') {
      if ((options?.method ?? 'GET') === 'PUT') {
        const headers = new Headers(options?.headers)
        if (headers.get('If-Match') !== `"${access.version}"`) {
          return Promise.resolve(new Response(JSON.stringify({ detail: 'stale' }), { status: 409 }))
        }
        if (typeof options?.body !== 'string') throw new Error('Expected a JSON access document body')
        const body = JSON.parse(options.body) as ChangeHistoryAccessDocument
        access = { ...body, version: access.version + 1 }
      }
      return Promise.resolve(new Response(JSON.stringify(access), {
        status: 200,
        headers: { 'Content-Type': 'application/json', ETag: `"${access.version}"` },
      }))
    }
    if (url.pathname === '/api/v1/admin/systems' && (options?.method ?? 'GET') === 'POST') {
      if (typeof options?.body !== 'string') throw new Error('Expected a System create JSON body')
      const body = JSON.parse(options.body) as Record<string, unknown>
      if ('code' in body) throw new Error('System code must not be supplied by the browser')
      if (typeof body.name !== 'string' || typeof body.description !== 'string') {
        throw new Error('Expected validated System name and description')
      }
      const system = {
        system_id: 'system-generated-test-identity',
        code: 'MANUFACTURING_EXECUTION_TEST',
        name: body.name,
        description: body.description,
        active: true,
        version: 1,
      }
      access = { ...access, systems: [...access.systems, system], version: access.version + 1 }
      return Promise.resolve(new Response(JSON.stringify(system), {
        status: 201,
        headers: { 'Content-Type': 'application/json', ETag: `"${access.version}"` },
      }))
    }
    if (url.pathname.startsWith('/api/v1/change-history/') || url.pathname.includes('/change-history')) {
      const headers = new Headers(options?.headers)
      return Promise.resolve(new Response(JSON.stringify({
        path: `${url.pathname}${url.search}`,
        method: options?.method ?? 'GET',
        body: typeof options?.body === 'string' ? JSON.parse(options.body) as unknown : null,
        idempotency_key: headers.get('Idempotency-Key'),
        if_match: headers.get('If-Match'),
      }), { status: 200, headers: { 'Content-Type': 'application/json', ETag: '"server-etag"' } }))
    }
    if (/^\/api\/v1\/change-requests\/(?!summaries$)[^/]+$/.test(url.pathname)) {
      return Promise.resolve(json({
        id: decodeURIComponent(url.pathname.split('/').at(-1) ?? ''),
        title: 'Authoritative change request detail',
        gateway_path: url.pathname,
      }))
    }
    if (/^\/poc-api\/bulk\/uploads\/[^/]+\/preparations\/[^/]+\/metadata-candidates\/[^/]+\/change-request$/.test(url.pathname)) {
      const headers = new Headers(options?.headers)
      return Promise.resolve(json({
        path: url.pathname,
        method: options?.method ?? 'GET',
        body: typeof options?.body === 'string' ? JSON.parse(options.body) as unknown : null,
        idempotency_key: headers.get('Idempotency-Key'),
        if_match: headers.get('If-Match'),
      }))
    }
    if (url.pathname === '/poc-api/knowledge/catalog') {
      const query = (url.searchParams.get('q') ?? '*').toLocaleLowerCase()
      const matching = liveAssets.filter((asset) => (
        query === '*' || [asset.name, asset.description].join(' ').toLocaleLowerCase().includes(query)
      ))
      return Promise.resolve(json({
        items: matching.map((asset) => ({
          id: asset.id,
          name: asset.name,
          asset_type: 'TABLE',
          platform: asset.platform,
          database_name: asset.database_name,
          schema_name: asset.schema_name,
          classification: asset.id.includes('daily_yield') ? 'restricted' : 'normal',
          source_version: 'datahub-live',
          projection_source_version: 'datahub-live-poc',
          field_paths: [],
          fields_truncated: false,
          domain: asset.domain,
          tags: asset.tags,
          glossary_terms: asset.terms,
          description: asset.description,
          description_truncated: false,
          field_metadata: [],
          selection_fingerprint: null,
        })),
        page: { next_cursor: null, limit: Number(url.searchParams.get('limit') ?? 25) },
      }))
    }
    if (url.pathname === '/poc-api/datahub/catalog') {
      const query = (url.searchParams.get('q') ?? '*').toLocaleLowerCase()
      const matching = liveAssets.filter((asset) => (
        (query === '*' || [asset.name, asset.description].join(' ').toLocaleLowerCase().includes(query))
        && (!url.searchParams.get('platform') || asset.platform === url.searchParams.get('platform'))
        && (!url.searchParams.get('database') || asset.database_name === url.searchParams.get('database'))
        && (!url.searchParams.get('schema') || asset.schema_name === url.searchParams.get('schema'))
      ))
      const requestedLimit = Number(url.searchParams.get('limit') ?? 100)
      const offset = url.searchParams.get('cursor') === 'opaque-page-2' ? 1 : 0
      const items = matching.slice(offset, offset + requestedLimit)
      const nextCursor = offset + requestedLimit < matching.length ? 'opaque-page-2' : null
      return Promise.resolve(json({
        items,
        page: { next_cursor: nextCursor, limit: requestedLimit },
        total: matching.length,
        total_exact: true,
        meta,
        match_mode: 'ALL',
      } satisfies CatalogSearch))
    }
    if (url.pathname === '/poc-api/datahub/dashboard') {
      return Promise.resolve(json({
        observed_at: meta.observed_at,
        changes_by_state: {},
        catalog_asset_count: liveAssets.length,
        catalog_described_asset_count: liveAssets.length,
        catalog_glossary_term_count: 2,
        catalog_schema_metrics: liveAssets.map((asset) => ({
          platform: asset.platform,
          database_name: asset.database_name,
          schema_name: asset.schema_name,
          asset_count: 1,
        })),
        catalog_schema_metrics_truncated: false,
      }))
    }
    if (url.pathname === '/poc-api/datahub/tree') {
      const parentKind = url.searchParams.get('parent_kind') ?? 'ROOT'
      const items = parentKind === 'ROOT'
        ? liveAssets.map((asset) => ({
            id: `PLATFORM:${asset.platform}`,
            kind: 'PLATFORM',
            label: asset.platform,
            asset_count: 1,
            has_children: true,
            platform: asset.platform,
          }))
        : []
      return Promise.resolve(json({ items, page: { next_cursor: null, limit: 100 }, meta }))
    }
    if (url.pathname === '/poc-api/datahub/systems') {
      return Promise.resolve(json({
        items: liveAssets.map((asset) => ({ id: asset.platform, name: asset.platform })),
        page: { next_cursor: null, limit: 100 },
      }))
    }
    if (url.pathname === '/poc-api/knowledge/catalog/asset') {
      const asset = liveAssets.find((item) => item.id === url.searchParams.get('urn')) ?? liveAssets[0]!
      const fieldUrn = `urn:li:schemaField:(${asset.id},wafer_id)`
      return Promise.resolve(json({
        dataset: {
          id: asset.id,
          name: asset.name,
          asset_type: 'TABLE',
          platform: asset.platform,
          database_name: asset.database_name,
          schema_name: asset.schema_name,
          classification: asset.id.includes('daily_yield') ? 'restricted' : 'normal',
          source_version: 'datahub-live',
          projection_source_version: 'datahub-live-poc',
          field_paths: ['wafer_id'],
          fields_truncated: false,
          domain: asset.domain,
          tags: asset.tags,
          glossary_terms: asset.terms,
          description: asset.description,
          description_truncated: false,
          field_metadata: [{
            field_path: 'wafer_id',
            field_urn: fieldUrn,
            field_type: null,
            native_data_type: 'VARCHAR',
            description: 'Wafer identifier',
            description_truncated: false,
            tags: ['identifier'],
            tags_truncated: false,
            glossary_terms: ['Wafer ID'],
            terms_truncated: false,
          }],
          selection_fingerprint: 'f'.repeat(64),
        },
        observed_at: meta.observed_at,
      }))
    }
    if (url.pathname === '/poc-api/datahub/asset') {
      const asset = liveAssets.find((item) => item.id === url.searchParams.get('urn')) ?? liveAssets[0]!
      return Promise.resolve(json({
        ...asset,
        ownership: [],
        glossary_terms: [],
        schema_fields: [{
          fieldPath: 'wafer_id',
          nativeDataType: 'VARCHAR',
          description: 'Wafer identifier',
          globalTags: { tags: [{ tag: { name: 'identifier' } }] },
          glossaryTerms: { terms: [{ term: { name: 'Wafer ID' } }] },
        }],
        schema_fields_total: 1,
        schema_fields_available: 1,
        schema_fields_truncated: false,
        schema_fields_total_exact: true,
        schema_fields_offset: 0,
        schema_fields_limit: 100,
        schema_fields_has_more: false,
        quality: null,
        projection_source_version: 'datahub-live-poc',
        source_version: 'datahub-live',
      }))
    }
    if (url.pathname === '/poc-api/datahub/lineage') {
      return Promise.resolve(json({
        center_asset_id: url.searchParams.get('urn'),
        nodes: [],
        edges: [],
        direction: url.searchParams.get('direction') ?? 'BOTH',
        depth: Number(url.searchParams.get('depth') ?? 1),
        truncated: false,
        meta,
      }))
    }
    if (url.pathname === '/poc-api/datahub/manual-metadata') {
      return Promise.resolve(json({
        urn: liveAssets[0]!.id,
        reports: ['datasetProperties', 'domains', 'globalTags', 'glossaryTerms', 'schemaMetadata']
          .map((aspectName, index) => ({
            aspect_name: aspectName,
            aspect_ordinal: index + 1,
            outcome: 'APPLIED_VERIFIED',
            before_hash: `before-${index}`,
            expected_hash: `expected-${index}`,
            observed_hash: `expected-${index}`,
            write_attempted: true,
            failure_code: null,
            provider_version: '0',
            provider_response_hash: `provider-${index}`,
            observed_at: meta.observed_at,
          })),
      }))
    }
    if (/^\/poc-api\/change-requests\/[^/]+\/apply-report$/.test(url.pathname)) {
      return Promise.resolve(json({
        change_request_id: decodeURIComponent(url.pathname.split('/')[3] ?? ''),
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
      }))
    }
    if (url.pathname === '/poc-api/knowledge/projections') {
      if ((options?.method ?? 'GET') === 'POST') {
        const body = JSON.parse(typeof options?.body === 'string' ? options.body : '{}') as { draft_id?: string }
        knowledgeProjectionReceipt = {
          contract_version: 'KNOWLEDGE_PROJECTION_RECEIPT_V1',
          id: `knowledge-projection:${body.draft_id}`,
          draft_id: body.draft_id,
          graph_id: 'knowledge-k1-graph',
          studio_release_id: 'knowledge-k1-release',
          requested_by: 'live-test-admin',
          state: 'SUCCESS',
          progress_percent: 100,
          current_stage: 'NEO4J_PROJECTION',
          vector_target_count: 0,
          attempt_count: 1,
          maximum_attempts: 1,
          result_changeset_id: null,
          result_evidence_hash: 'a'.repeat(64),
          error_code: null,
          allowed_actions: [],
          version: 1,
          created_at: meta.observed_at,
          updated_at: meta.observed_at,
          started_at: meta.observed_at,
          finished_at: meta.observed_at,
          node_count: 2,
          edge_count: 1,
          duplicate_count: 0,
          provenance: [{
            knowledge_entity_id: 'knowledge:table',
            external_urn: liveAssets[0]!.id,
            entity_kind: 'TABLE',
            parent_table_urn: null,
            source_type: 'DATAHUB_SYNC',
            target_stable_element_ids: ['wafer-class'],
          }],
        }
        return Promise.resolve(new Response(JSON.stringify(knowledgeProjectionReceipt), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        }))
      }
      return Promise.resolve(json({
        items: knowledgeProjectionReceipt ? [knowledgeProjectionReceipt] : [],
        page: { limit: 100 },
      }))
    }
    if (url.pathname === '/poc-api/knowledge/graphs') {
      return Promise.resolve(json([{
        id: 'knowledge-k6-graph', slug: 'knowledge-k6', name: 'K6 verified Asset',
        graph_type: 'CURATED_KNOWLEDGE', status: 'ACTIVE', classification: 'credential',
        active_release_id: 'knowledge-k6-release', version: 3,
      }]))
    }
    if (url.pathname === '/poc-api/knowledge/graphs/knowledge-k6-graph/releases') {
      return Promise.resolve(json([{
        id: 'knowledge-k6-release', graph_id: 'knowledge-k6-graph', release_no: 1,
        ontology_version_id: 'knowledge-k6-tbox', content_hash: 'c'.repeat(64),
        node_count: 2, edge_count: 1, published_by: 'knowledge-reviewer',
        published_at: meta.observed_at,
      }]))
    }
    if (url.pathname === '/poc-api/knowledge/graphs/knowledge-k6-graph/releases/knowledge-k6-release/snapshot') {
      return Promise.resolve(json({
        release: {
          id: 'knowledge-k6-release', graph_id: 'knowledge-k6-graph', release_no: 1,
          ontology_version_id: 'knowledge-k6-tbox', content_hash: 'c'.repeat(64),
          node_count: 2, edge_count: 1, published_by: 'knowledge-reviewer',
          published_at: meta.observed_at,
        },
        nodes: [{ id: 'node-a', entity_type: 'Wafer', properties: { name: 'W-001' }, classification: 1, provenance: [] }],
        edges: [], filtered: true,
      }))
    }
    if (url.pathname === '/poc-api/knowledge/graphs/knowledge-k6-graph/releases/knowledge-k6-release/graphrag') {
      const body = JSON.parse(typeof options?.body === 'string' ? options.body : '{}') as { question?: string }
      return Promise.resolve(json({
        release: { id: 'knowledge-k6-release', graph_id: 'knowledge-k6-graph', release_no: 1 },
        nodes: [{ id: 'node-a', entity_type: 'Wafer', properties: { name: 'W-001' }, classification: 1, provenance: [] }],
        edges: [], truncated: false, answer: `bounded: ${body.question}`,
        citations: [],
        model_audit: {
          provider: 'OPENAI_COMPATIBLE', model: 'live-test',
          prompt_version: 'knowledge-graphrag-v1', tool_schema_version: 'knowledge-evidence-v1',
        },
      }))
    }
    if (/^\/poc-api\/knowledge\/studio\/drafts\/[^/]+\/abox\/previews$/.test(url.pathname)) {
      return Promise.resolve(json({
        job_id: 'knowledge-ingestion:preview-live-test',
        status: 'READY',
        draft_version: 4,
        binding_version: 1,
        target_stable_element_id: 'wafer-class',
        pinned_tbox_version: 3,
        node_count: 2,
        relation_count: 0,
        source: { asset_urn: liveAssets[0]!.id, source_version: 'source-v1', manifest_ref: 'live-test-v1' },
        dry_run: true,
        sample_size: 2,
        graph: { nodes: [], edges: [] },
        rejected: [],
        unmapped: [],
        evidence: [],
        provenance: [],
      }))
    }
    if (/^\/poc-api\/knowledge\/studio\/drafts\/[^/]+\/abox\/ingestions$/.test(url.pathname)) {
      if ((options?.method ?? 'GET') === 'POST') {
        const body = JSON.parse(typeof options?.body === 'string' ? options.body : '{}') as { preview_job_id?: string }
        if (body.preview_job_id !== 'knowledge-ingestion:preview-live-test') throw new Error('Expected exact preview receipt')
        knowledgeIngestionReceipt = {
          id: 'knowledge-ingestion:live-test',
          state: 'SUCCESS',
          node_count: 2,
          duplicate_count: 0,
          result_evidence_hash: 'a'.repeat(64),
          provenance: [{ source_type: 'DETERMINISTIC_ENRICHER' }],
        }
        return Promise.resolve(new Response(JSON.stringify(knowledgeIngestionReceipt), {
          status: 201, headers: { 'Content-Type': 'application/json' },
        }))
      }
      return Promise.resolve(json({ items: knowledgeIngestionReceipt ? [knowledgeIngestionReceipt] : [] }))
    }
    if (/^\/poc-api\/minio\/uploads\/[^/]+\/parts\/1$/.test(url.pathname)) {
      return Promise.resolve(new Response(null, { status: 200, headers: { ETag: '"poc-etag"' } }))
    }
    if (/^\/poc-api\/minio\/uploads\/[^/]+\/complete$/.test(url.pathname)) {
      return Promise.resolve(json({ state: 'STORED' }))
    }
    if (url.pathname === '/poc-api/capabilities') {
      return Promise.resolve(json({
        items: [
          { name: 'DataHub', state: 'available', observed_at: meta.observed_at, latency_ms: 4, detail_code: 'LIVE' },
          { name: 'Airflow', state: 'available', observed_at: meta.observed_at, latency_ms: 5, detail_code: 'LIVE' },
        ],
        external_system_links: [],
        grafana_embed: { state: 'DISABLED' },
        monitoring_configuration: { version: 1, items: [] },
        deployment_tier: 'SINGLE_NODE_PILOT',
      }))
    }
    if (url.pathname === '/poc-api/llm/chat/stream') {
      const requestBody = JSON.parse(typeof options?.body === 'string' ? options.body : '{}') as { session_id?: string }
      const result = {
        session_id: requestBody.session_id ?? 'server-session-1',
        request_message_id: crypto.randomUUID(),
        response_message_id: crypto.randomUUID(),
        answer: 'wafer_events는 source_events의 영향을 받습니다. [1]',
        persistence: 'PERSISTED',
        route: {
          requested_mode: 'AUTO',
          selected_mode: 'GRAPH',
          reason: 'GRAPH_INTENT',
          adapter_state: 'READY',
        },
        workflow: [
          { stage: 'ROUTING', status: 'COMPLETED', detail_code: 'GRAPH_ROUTE_SELECTED' },
          { stage: 'RETRIEVAL', status: 'COMPLETED', detail_code: 'GRAPH_RETRIEVAL_COMPLETED' },
        ],
        evidence: [{
          id: liveAssets[0]!.id,
          external_urn: liveAssets[0]!.external_urn,
          name: liveAssets[0]!.name,
          description: 'source_events → wafer_events',
          classification: 'INTERNAL',
          platform: 'postgres',
          domain: 'manufacturing',
          source_version: 'datahub-live',
          evidence_type: 'DATAHUB_LINEAGE',
          source_type: 'DATAHUB_LINEAGE',
          extraction_method: 'DATAHUB_GMS_LINEAGE',
          retrieval_method: 'GRAPH',
        }],
      }
      const frames = [
        { event: 'workflow', data: { stage: 'ROUTING', status: 'IN_PROGRESS', detail_code: 'ROUTING_IN_PROGRESS' } },
        { event: 'workflow', data: { stage: 'ROUTING', status: 'COMPLETED', detail_code: 'GRAPH_ROUTE_SELECTED' } },
        { event: 'workflow', data: { stage: 'RETRIEVAL', status: 'COMPLETED', detail_code: 'GRAPH_RETRIEVAL_COMPLETED' } },
        { event: 'answer_delta', data: { delta: 'wafer_events는 source_events의 ' } },
        { event: 'answer_delta', data: { delta: '영향을 받습니다. [1]' } },
        { event: 'result', data: result },
      ].map((frame) => `event: ${frame.event}\ndata: ${JSON.stringify(frame.data)}\n\n`).join('')
      return Promise.resolve(new Response(frames, {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
      }))
    }
    if (url.pathname === '/poc-api/knowledge/managed-assets') {
      return Promise.resolve(json({ items: [], next_cursor: null, limit: 25 }))
    }
    throw new Error(`Unexpected POC gateway request: ${url.pathname}`)
  }))
}

function configureKnowledgeActor(
  subjectId: string,
  boundaryRevision: number,
  capabilities: Array<'knowledge.read' | 'knowledge.manage' | 'knowledge.review'> = [
    'knowledge.read', 'knowledge.manage', 'knowledge.review',
  ],
) {
  configurePocAuthorization({
    policy_version: 'POC_PROFILE_CAPABILITIES_V1',
    role: capabilities.length === 1 ? 'viewer' : 'admin',
    capabilities,
    system_scope: 'GLOBAL',
    system_ids: [],
  }, `${subjectId}|${boundaryRevision}`)
}

function installLegacyGovernanceHydration(
  adminMemberships: Array<{ subject_id: string; display_name: string }>,
) {
  ;(globalThis as typeof globalThis & { __DATARIVER_POC_RUNTIME__?: Record<string, boolean> })
    .__DATARIVER_POC_RUNTIME__ = { pocState: true }
  const observedAt = '2026-08-30T00:00:00.000Z'
  const documentId = 'legacy-governance-document'
  const versionId = 'legacy-governance-version'
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
    const url = new URL(input instanceof Request ? input.url : String(input), 'https://poc.invalid')
    if (url.pathname !== '/poc-api/state/core') throw new Error(`Unexpected request: ${url.pathname}`)
    return Promise.resolve(new Response(JSON.stringify({
      value: {
        adminMemberships,
        governanceDocuments: [{
          document_id: documentId, workspace_id: POC_WORKSPACE_ID, kind: 'DOCUMENT', category: 'POLICY',
          title: 'Legacy governance document', summary: '', classification: 1, state: 'ACTIVE',
          owner_subject_id: POC_SUBJECT_ID, current_published_version_id: versionId,
          current_version_number: 1, created_at: observedAt, updated_at: observedAt, version: 1,
          allowed_actions: ['read'],
        }],
        governanceVersions: [{
          version_id: versionId, workspace_id: POC_WORKSPACE_ID, document_id: documentId,
          version_number: 1, version_tag: 'v1', state: 'PUBLISHED', title: 'Legacy governance document',
          summary: '', applicability_scope: '', sanitized_html: '<p>Legacy</p>', plain_text: 'Legacy',
          content_sha256: 'a'.repeat(64), size_bytes: 13, sanitizer_policy_version: 'POC_SANITIZER_V1',
          sanitizer_policy_sha256: 'b'.repeat(64), source_format: 'HTML', source_template_version_id: null,
          parent_document_id: null, author_id: POC_SUBJECT_ID, submitted_at: observedAt,
          reviewed_by: POC_SUBJECT_ID, reviewed_at: observedAt, published_at: observedAt,
          artifact_state: 'STORED', knowledge_state: 'READY', created_at: observedAt, version: 1,
        }],
        governanceReviews: [{
          review_id: 'legacy-governance-review', workspace_id: POC_WORKSPACE_ID, document_id: documentId,
          document_version_id: versionId, decision: 'APPROVE', reviewer_id: POC_SUBJECT_ID,
          reason: '', policy_decision_id: 'legacy-policy', authentication_assurance: 'LOCAL_PASSWORD_SESSION',
          created_at: observedAt,
        }],
        governanceAttachments: [],
      },
      version: 1,
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json', ETag: '"1"' },
    }))
  }))
}

describe('POC live-provider compatibility adapter', () => {
  beforeEach(() => {
    resetPocMemory()
    configurePocAuthorization({
      policy_version: 'POC_PROFILE_CAPABILITIES_V1',
      role: 'admin',
      capabilities: [
        'catalog.read', 'catalog.execute', 'catalog.manage', 'chat.query', 'change.read',
        'change.execute', 'change.manage',
        'quality.read', 'quality.execute', 'quality.manage', 'knowledge.read',
        'knowledge.manage', 'knowledge.review', 'monitoring.read', 'admin.manage',
      ],
      system_scope: 'GLOBAL',
      system_ids: [],
    }, 'live-test-admin')
    ;(globalThis as typeof globalThis & { __DATARIVER_POC_RUNTIME__?: Record<string, boolean> })
      .__DATARIVER_POC_RUNTIME__ = {
        datahub: true,
        airflow: true,
        llmChat: true,
        llmEmbedding: true,
        llmReranker: true,
        neo4j: true,
        minio: true,
      }
    installGatewayMock()
  })

  it('classifies IN_REVIEW resubmission from edited-round or transition evidence', () => {
    const initial = {
      state: 'IN_REVIEW' as const,
      current_round_id: 'round-1',
      current_round_number: 1,
      rounds: [{ id: 'round-1', revision_kind: 'INITIAL' as const }],
      transitions: [{
        round_id: 'round-1', from_state: 'REGISTERED' as const, to_state: 'IN_REVIEW' as const,
      }],
    }
    expect(isResubmittedReviewForOverview(initial)).toBe(false)
    expect(isResubmittedReviewForOverview({
      ...initial,
      rounds: [{ id: 'round-1', revision_kind: 'EDITED' }],
    })).toBe(true)
    expect(isResubmittedReviewForOverview({
      ...initial,
      transitions: [
        { round_id: 'round-1', from_state: 'CHANGES_REQUESTED', to_state: 'REGISTERED' },
        { round_id: 'round-1', from_state: 'REGISTERED', to_state: 'IN_REVIEW' },
      ],
    })).toBe(true)
    expect(isResubmittedReviewForOverview({
      ...initial,
      transitions: [{
        round_id: 'round-1', from_state: 'CHANGES_REQUESTED', to_state: 'IN_REVIEW',
      }],
    })).toBe(true)
  })

  it('fails viewer mutations closed while keeping read presentation capabilities', async () => {
    configurePocAuthorization({
      policy_version: 'POC_PROFILE_CAPABILITIES_V1',
      role: 'viewer',
      capabilities: [
        'catalog.read', 'chat.query', 'change.read', 'quality.read',
        'knowledge.read', 'monitoring.read',
      ],
      system_scope: 'GLOBAL',
      system_ids: [],
    }, 'viewer-boundary')
    const client = useStableApiClient()

    await expect(client.request('/knowledge/domains', {
      method: 'POST', body: JSON.stringify({ display_name: 'forged write' }),
    })).rejects.toThrow(/권한/)
    await expect(client.request<{ items: unknown[] }>('/knowledge/domains'))
      .resolves.toMatchObject({ items: [] })
    await expect(client.request('/unclassified-client-route'))
      .rejects.toThrow(/미분류 POC API/)
  })

  it('presents manager Knowledge manage/review without inventing Admin authority', async () => {
    configurePocAuthorization({
      policy_version: 'POC_PROFILE_CAPABILITIES_V1',
      role: 'manager',
      capabilities: [
        'catalog.read', 'catalog.execute', 'catalog.manage', 'chat.query', 'change.read',
        'change.execute', 'change.manage',
        'quality.read', 'quality.execute', 'quality.manage', 'knowledge.read',
        'knowledge.manage', 'knowledge.review', 'monitoring.read',
      ],
      system_scope: 'ASSIGNED',
      system_ids: ['system-one'],
    }, 'manager-boundary')
    const context = await useStableApiClient().request<{
      allowed_operations: string[]
      action_vocabulary: string[]
    }>('/admin/me')

    expect(context.allowed_operations).toEqual([])
    expect(context.action_vocabulary).toEqual(expect.arrayContaining([
      'knowledge.manage', 'knowledge.review',
    ]))
    expect(context.action_vocabulary).not.toContain('admin.manage')
  })

  it('preserves manager Catalog capabilities, allows Registration reads, but denies Registration mutations', async () => {
    configurePocAuthorization({
      policy_version: 'POC_PROFILE_CAPABILITIES_V1',
      role: 'manager',
      capabilities: ['catalog.read', 'catalog.execute', 'catalog.manage'],
      system_scope: 'ASSIGNED',
      system_ids: ['system-one'],
    }, 'manager-registration-boundary')
    const client = useStableApiClient()

    await expect(client.request<{ eligible: boolean; can_view_registration: boolean; reason_code: string }>('/uploads/operator-capability'))
      .resolves.toMatchObject({
        eligible: false,
        can_view_registration: true,
        reason_code: 'READ_ONLY',
      })
    await expect(client.request('/uploads')).resolves.toHaveProperty('items')
    await expect(client.request('/registration/manual-submissions')).resolves.toHaveProperty('items')
    await expect(client.request('/uploads/upload-1/preparations/preparation-1/metadata-candidates'))
      .rejects.toThrow(/Manager는 등록 실행이력/)
    await expect(client.request(`/catalog/assets/${liveAssets[0]!.id}/description-previews`, {
      method: 'POST', body: JSON.stringify({ description: 'forged manager registration write' }),
    })).rejects.toThrow(/Data Steward 또는 Admin/)
    await expect(client.request<CatalogSearch>('/catalog/assets?q=*&limit=1'))
      .resolves.toMatchObject({ items: [expect.objectContaining({ name: 'wafer_events' })] })
  })

  it('denies Registration reads and mutations to viewer despite Catalog read access', async () => {
    configurePocAuthorization({
      policy_version: 'POC_PROFILE_CAPABILITIES_V1',
      role: 'viewer',
      capabilities: ['catalog.read'],
      system_scope: 'ASSIGNED',
      system_ids: [],
    }, 'viewer-registration-boundary')
    const client = useStableApiClient()

    await expect(client.request('/uploads/operator-capability')).rejects.toThrow(/Data Steward, Manager 또는 Admin/)
    await expect(client.request('/uploads')).rejects.toThrow(/Data Steward, Manager 또는 Admin/)
    await expect(client.request('/registration/manual-submissions')).rejects.toThrow(/Data Steward, Manager 또는 Admin/)
    await expect(client.request('/registration/manual-submissions', {
      method: 'POST', body: JSON.stringify({}),
    })).rejects.toThrow(/권한|Data Steward 또는 Admin/)
  })

  it('keeps the Registration adapter available to Data Steward', async () => {
    configurePocAuthorization({
      policy_version: 'POC_PROFILE_CAPABILITIES_V1',
      role: 'data_steward',
      capabilities: ['catalog.read', 'catalog.execute', 'catalog.manage'],
      system_scope: 'ASSIGNED',
      system_ids: ['system-one'],
    }, 'steward-registration-boundary')

    await expect(useStableApiClient().request<{ eligible: boolean; can_view_registration: boolean; reason_code: string }>('/uploads/operator-capability'))
      .resolves.toMatchObject({
        eligible: true,
        can_view_registration: true,
        reason_code: 'ELIGIBLE',
      })
  })

  it('forwards the fixed feature security policy through the authenticated Node gateway', async () => {
    configurePocAuthorization({
      policy_version: 'POC_PROFILE_CAPABILITIES_V1',
      role: 'admin', capabilities: ['admin.manage'],
      system_scope: 'GLOBAL', system_ids: [],
    }, 'feature-security-policy-admin')
    const request = vi.fn((input: RequestInfo | URL) => {
      const url = new URL(input instanceof Request ? input.url : String(input), 'https://poc.invalid')
      expect(url.pathname).toBe('/api/v1/admin/feature-security-policy')
      return Promise.resolve(new Response(JSON.stringify({
        version: 0,
        schema_version: 1,
        cells: [],
        updated_at: null,
        updated_by: null,
        reason: 'APPROVED_PRODUCT_DEFAULT',
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json', ETag: '"0"' },
      }))
    })
    vi.stubGlobal('fetch', request)

    const response = await useStableApiClient().requestWithMeta<{ version: number }>(
      '/admin/feature-security-policy',
    )

    expect(response.data.version).toBe(0)
    expect(response.etag).toBe('"0"')
    expect(request).toHaveBeenCalledTimes(1)
  })

  it('resets singleton POC memory when the authenticated subject boundary changes', async () => {
    configurePocAuthorization({
      policy_version: 'POC_PROFILE_CAPABILITIES_V1',
      role: 'manager', capabilities: ['knowledge.read', 'knowledge.manage'],
      system_scope: 'ASSIGNED', system_ids: ['system-one'],
    }, 'subject-a:0')
    const client = useStableApiClient()
    await client.request('/knowledge/domains', {
      method: 'POST', body: JSON.stringify({ display_name: 'Subject A private draft' }),
    })
    expect((await client.request<{ items: unknown[] }>('/knowledge/domains')).items).toHaveLength(1)

    configurePocAuthorization({
      policy_version: 'POC_PROFILE_CAPABILITIES_V1',
      role: 'viewer', capabilities: ['knowledge.read'],
      system_scope: 'GLOBAL', system_ids: [],
    }, 'subject-b:1')

    expect((await client.request<{ items: unknown[] }>('/knowledge/domains')).items).toEqual([])
  })

  it('hydrates core state version and sends exact If-Match on persistence', async () => {
    ;(globalThis as typeof globalThis & { __DATARIVER_POC_RUNTIME__?: Record<string, boolean> })
      .__DATARIVER_POC_RUNTIME__ = { pocState: true }
    let writes = 0
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, options?: RequestInit) => {
      const url = new URL(input instanceof Request ? input.url : String(input), 'https://poc.invalid')
      if (url.pathname !== '/poc-api/state/core') throw new Error(`Unexpected request: ${url.pathname}`)
      if ((options?.method ?? 'GET') === 'GET') {
        return Promise.resolve(new Response(JSON.stringify({ value: null, version: 7 }), {
          status: 200, headers: { 'Content-Type': 'application/json', ETag: '"7"' },
        }))
      }
      writes += 1
      expect(new Headers(options?.headers).get('If-Match')).toBe('"7"')
      return Promise.resolve(new Response(JSON.stringify({ version: 8 }), {
        status: 200, headers: { 'Content-Type': 'application/json', ETag: '"8"' },
      }))
    }))
    configurePocAuthorization({
      policy_version: 'POC_PROFILE_CAPABILITIES_V1',
      role: 'manager', capabilities: ['knowledge.read', 'knowledge.manage'],
      system_scope: 'ASSIGNED', system_ids: ['system-one'],
    }, 'cas-subject:0')

    await useStableApiClient().request('/knowledge/domains', {
      method: 'POST', body: JSON.stringify({ display_name: 'CAS draft' }),
    })
    expect(writes).toBe(1)
  })

  afterEach(() => {
    delete (globalThis as typeof globalThis & { __DATARIVER_POC_RUNTIME__?: Record<string, boolean> })
      .__DATARIVER_POC_RUNTIME__
    vi.unstubAllGlobals()
  })

  it('uses DataHub assets for dashboard, suggestions, hierarchy and CR target selection', async () => {
    const client = useStableApiClient()
    const dashboard = await client.request<{
      catalog_asset_count: number
      catalog_glossary_term_count: number
      catalog_schema_metrics: Array<{ platform?: string }>
    }>('/operations/dashboard')
    expect(dashboard.catalog_asset_count).toBe(2)
    expect(dashboard.catalog_glossary_term_count).toBe(2)
    expect(dashboard.catalog_schema_metrics.map((item) => item.platform)).toEqual(['postgres', 'snowflake'])

    const suggestions = await client.request<{ items: CatalogAsset[] }>('/catalog/suggestions?q=wafer&limit=8')
    expect(suggestions.items.map((item) => item.name)).toEqual(['wafer_events'])

    const root = await client.request<{ items: Array<{ label: string }> }>('/catalog/tree/nodes?parent_kind=ROOT&limit=100')
    expect(root.items.map((item) => item.label)).toEqual(['postgres', 'snowflake'])

    const systems = await client.request<{ items: Array<{ id: string }> }>('/change-requests/systems')
    expect(systems.items.map((item) => item.id)).toEqual(['postgres', 'snowflake'])
    const targets = await client.request<CatalogSearch>('/change-requests/targets?system_id=postgres&q=wafer&limit=12')
    expect(targets.items.map((item) => item.name)).toEqual(['wafer_events'])
    const detail = await client.request<CatalogAssetDetail>(`/change-requests/targets/${targets.items[0]!.id}?system_id=postgres`)
    expect(detail.schema_fields[0]).toMatchObject({ fieldPath: 'wafer_id' })
    expect(detail.schema_fields[0]?.globalTags).toEqual({ tags: [{ tag: { name: 'identifier' } }] })
    expect(detail.schema_fields[0]?.glossaryTerms).toEqual({ terms: [{ term: { name: 'Wafer ID' } }] })
  })

  it('forwards bounded lineage direction and depth through the POC gateway', async () => {
    const lineage = await useStableApiClient().request<{ direction: string; depth: number }>(
      `/catalog/assets/${liveAssets[0]!.id}/lineage?direction=DOWNSTREAM&depth=2`,
    )

    expect(lineage).toMatchObject({ direction: 'DOWNSTREAM', depth: 2 })
    const requestUrl = vi.mocked(fetch).mock.calls
      .map(([input]) => new URL(input instanceof Request ? input.url : String(input), 'https://poc.invalid'))
      .find((url) => url.pathname === '/poc-api/datahub/lineage')
    expect(requestUrl?.searchParams.get('direction')).toBe('DOWNSTREAM')
    expect(requestUrl?.searchParams.get('depth')).toBe('2')
  })

  it('resolves an opaque active System through its exact schema scopes and preserves provider-platform routing', async () => {
    const client = useStableApiClient()
    const system = await client.request<{ system_id: string }>('/admin/systems', {
      method: 'POST',
      idempotencyKey: 'system-create-exact-schema-scope',
      body: JSON.stringify({
        name: 'Fabrication', description: 'Canonical business System',
      }),
    })
    expect(system.system_id).not.toBe('postgres')
    await client.request(`/admin/systems/${system.system_id}/schema-scopes`, {
      method: 'PATCH',
      body: JSON.stringify({ upsert_asset_ids: [liveAssets[0]!.id] }),
    })

    const controller = new AbortController()
    const targets = await client.request<CatalogSearch>(
      `/change-requests/targets?system_id=${system.system_id}&q=wafer&limit=12`,
      { signal: controller.signal },
    )
    expect(targets.items.map((item) => item.name)).toEqual(['wafer_events'])
    const scopedCatalogCall = vi.mocked(fetch).mock.calls.find(([input]) => {
      const requestUrl = input instanceof Request ? input.url : input.toString()
      const url = new URL(requestUrl, 'https://poc.invalid')
      return url.pathname === '/poc-api/datahub/catalog'
        && url.searchParams.get('q') === 'wafer'
        && url.searchParams.get('database') === 'FACTORY'
    })
    expect(scopedCatalogCall).toBeDefined()
    const scopedInput = scopedCatalogCall?.[0]
    if (!scopedInput) throw new Error('Expected a schema-scoped DataHub catalog request')
    const scopedUrl = new URL(
      scopedInput instanceof Request ? scopedInput.url : scopedInput.toString(),
      'https://poc.invalid',
    )
    expect(Object.fromEntries(scopedUrl.searchParams)).toMatchObject({
      platform: 'postgres', database: 'FACTORY', schema: 'QUALITY',
    })
    expect(scopedUrl.searchParams.get('platform')).not.toBe(system.system_id)
    expect(scopedCatalogCall?.[1]?.signal).toBe(controller.signal)

    const detail = await client.request<CatalogAssetDetail>(
      `/change-requests/targets/${targets.items[0]!.id}?system_id=${system.system_id}`,
      { signal: controller.signal },
    )
    expect(detail.name).toBe('wafer_events')
    await expect(client.request(
      `/change-requests/targets/${liveAssets[1]!.id}?system_id=${system.system_id}`,
    )).rejects.toThrow('활성 스키마 범위가 일치하지 않습니다')

    const scopes = await client.request<{ items: Array<{ scope_id: string }> }>(
      `/admin/systems/${system.system_id}/schema-scopes`,
    )
    await client.request(`/admin/systems/${system.system_id}/schema-scopes`, {
      method: 'PATCH',
      body: JSON.stringify({ deactivate_scope_ids: [scopes.items[0]!.scope_id] }),
    })
    await expect(client.request<CatalogSearch>(
      `/change-requests/targets?system_id=${system.system_id}&q=wafer&limit=12`,
    )).resolves.toMatchObject({ items: [], total: 0 })
    await expect(client.request(
      `/change-requests/targets/${liveAssets[0]!.id}?system_id=${system.system_id}`,
    )).rejects.toThrow('활성 스키마 범위가 일치하지 않습니다')

    const legacy = await client.request<CatalogSearch>(
      '/change-requests/targets?system_id=snowflake&q=yield&limit=12',
    )
    expect(legacy.items.map((item) => item.name)).toEqual(['daily_yield'])
    await expect(client.request<CatalogAssetDetail>(
      `/change-requests/targets/${legacy.items[0]!.id}?system_id=snowflake`,
    )).resolves.toMatchObject({ name: 'daily_yield', platform: 'snowflake' })
  })

  it('fills the ten-column CR overview with initial/resubmitted stages and excludes terminal rejection', async () => {
    const client = useStableApiClient()
    const system = await client.request<{ system_id: string }>('/admin/systems', {
      method: 'POST', idempotencyKey: 'system-create-change-overview',
      body: JSON.stringify({ name: 'Overview System', description: '' }),
    })
    await client.request(`/admin/systems/${system.system_id}/schema-scopes`, {
      method: 'PATCH',
      body: JSON.stringify({ upsert_asset_ids: [liveAssets[0]!.id] }),
    })
    let current = await client.request<ChangeRequestRecord>('/change-requests/intake', {
      method: 'POST',
      body: JSON.stringify({
        title: 'Overview mapping', system_id: system.system_id, request_date: '2026-08-15',
        request_department: 'Control Plane', request_reason: 'verify mapping',
        request_content: 'verify overview', priority: 'NORMAL', urgency: 'NORMAL',
        security_level: 'INTERNAL', targets: [{ kind: 'EXISTING', asset_id: liveAssets[0]!.id }],
      }),
    })
    const overview = async () => (await client.request<{
      overview: Array<{
        total_count: number
        pending_count: number
        received_count: number
        recheck_count: number
        testing_count: number
        final_review_count: number
        completed_count: number
      }>
    }>('/change-requests/summaries?limit=25')).overview[0]!
    await expect(overview()).resolves.toMatchObject({
      total_count: 1, pending_count: 1, received_count: 1, recheck_count: 0,
    })
    current = await client.request<ChangeRequestRecord>(`/change-requests/${current.id}/transitions`, {
      method: 'POST', body: JSON.stringify({ target_state: 'IN_REVIEW', reason: 'initial review', if_match: current.version }),
    })
    await expect(overview()).resolves.toMatchObject({ received_count: 1, recheck_count: 0 })
    current = await client.request<ChangeRequestRecord>(`/change-requests/${current.id}/transitions`, {
      method: 'POST', body: JSON.stringify({ target_state: 'CHANGES_REQUESTED', reason: 'repair', if_match: current.version }),
    })
    current = await client.request<ChangeRequestRecord>(`/change-requests/${current.id}/revisions`, {
      method: 'POST',
      body: JSON.stringify({
        title: 'Overview mapping resubmitted', system_id: system.system_id,
        request_reason: 'resubmit', request_content: 'repaired', priority: 'NORMAL', urgency: 'NORMAL',
        security_level: 'INTERNAL', targets: [{ kind: 'EXISTING', asset_id: liveAssets[0]!.id }],
        if_match: current.version,
      }),
    })
    current = await client.request<ChangeRequestRecord>(`/change-requests/${current.id}/transitions`, {
      method: 'POST', body: JSON.stringify({ target_state: 'IN_REVIEW', reason: 'resubmitted review', if_match: current.version }),
    })
    await expect(overview()).resolves.toMatchObject({ received_count: 0, recheck_count: 1 })
    await client.request(`/change-requests/${current.id}/transitions`, {
      method: 'POST', body: JSON.stringify({ target_state: 'REJECTED', reason: 'terminal rejection', if_match: current.version }),
    })
    await expect(overview()).resolves.toMatchObject({
      total_count: 0, pending_count: 0, received_count: 0, recheck_count: 0,
      testing_count: 0, final_review_count: 0, completed_count: 0,
    })
  })

  it('forwards logical change-history paths and mutation fences to the authoritative Node API', async () => {
    const client = useStableApiClient()
    const list = await client.request<{ path: string }>('/change-history/events?limit=25')
    expect(list.path).toBe('/api/v1/change-history/events?limit=25')
    const summary = await client.request<{ path: string }>('/change-history/summary?week_start=2026-08-10')
    expect(summary.path).toBe('/api/v1/change-history/summary?week_start=2026-08-10')
    const mutation = await client.requestWithMeta<{
      path: string
      method: string
      body: Record<string, unknown>
      idempotency_key: string
      if_match: string
    }>('/change-history/events/abc/cr-link-events', {
      method: 'POST', idempotencyKey: 'request-key', ifMatch: '"0"',
      body: JSON.stringify({ action: 'SET_PRIMARY' }),
    })
    expect(mutation.data).toMatchObject({
      path: '/api/v1/change-history/events/abc/cr-link-events', method: 'POST',
      body: { action: 'SET_PRIMARY' }, idempotency_key: 'request-key', if_match: '"0"',
    })
    expect(mutation.etag).toBe('"server-etag"')
    const reverse = await client.request<{ path: string }>('/change-requests/cr-1/change-history?limit=10')
    expect(reverse.path).toBe('/api/v1/change-requests/cr-1/change-history?limit=10')
  })

  it('loads bare CR detail through the authoritative gateway without hydrated browser state', async () => {
    ;(globalThis as typeof globalThis & { __DATARIVER_POC_RUNTIME__?: Record<string, boolean> })
      .__DATARIVER_POC_RUNTIME__ = { pocState: true }
    resetPocMemory()

    const detail = await useStableApiClient().request<{
      id: string
      title: string
      gateway_path: string
    }>('/change-requests/cr-hard-reload')

    expect(detail).toEqual({
      id: 'cr-hard-reload',
      title: 'Authoritative change request detail',
      gateway_path: '/api/v1/change-requests/cr-hard-reload',
    })
  })

  it('proxies a bulk candidate command with its preview and idempotency fences', async () => {
    const client = useStableApiClient()
    const response = await client.request<{
      path: string
      method: string
      body: Record<string, string>
      idempotency_key: string
      if_match: string
    }>('/uploads/upload-1/preparations/preparation-1/metadata-candidates/candidate-1/change-request', {
      method: 'POST',
      idempotencyKey: 'bulk-command-1',
      ifMatch: `"${'a'.repeat(64)}"`,
      body: JSON.stringify({ title: 'Governed bulk metadata', reason: 'Create one governed CR.' }),
    })
    expect(response).toEqual({
      path: '/poc-api/bulk/uploads/upload-1/preparations/preparation-1/metadata-candidates/candidate-1/change-request',
      method: 'POST',
      body: { title: 'Governed bulk metadata', reason: 'Create one governed CR.' },
      idempotency_key: 'bulk-command-1',
      if_match: `"${'a'.repeat(64)}"`,
    })
  })

  it('creates typed registration previews, CRs and user-generated manual history from live metadata', async () => {
    const client = useStableApiClient()
    const preview = await client.request<{
      asset_id: string
      proposed_description: string
      preview_etag: string
    }>(`/catalog/assets/${liveAssets[0]!.id}/description-previews`, {
      method: 'POST',
      body: JSON.stringify({ description: 'Updated live description' }),
    })
    expect(preview.asset_id).toBe(liveAssets[0]!.id)
    expect(preview.proposed_description).toBe('Updated live description')
    expect(preview.preview_etag).toMatch(/^"[0-9a-f]{64}"$/)

    const proposal = await client.request<ChangeRequestRecord>(`/catalog/assets/${liveAssets[0]!.id}/description-change-requests`, {
      method: 'POST',
      ifMatch: preview.preview_etag,
      body: JSON.stringify({
        description: preview.proposed_description,
        title: 'Live description proposal',
        change_description: 'DataHub description correction',
      }),
    })
    expect(proposal.state).toBe('REGISTERED')
    expect(proposal.items[0]).toMatchObject({ target_asset_id: liveAssets[0]!.id, aspect_name: 'datasetProperties' })

    const submission = await client.request<{ id: string; state: string; row_count: number }>('/registration/manual-submissions', {
      method: 'POST',
      body: JSON.stringify({
        asset_id: liveAssets[0]!.id,
        source_version: 'datahub-live-poc',
        provider_source_version: 'datahub-live',
        description: 'User-authored description',
        column_edits: [{ field_path: 'wafer_id', description: 'User-authored column description' }],
      }),
    })
    expect(submission).toMatchObject({ state: 'APPLIED', row_count: 2 })
    const report = await client.request<{ submission: { id: string }; attempts: unknown[] }>(`/registration/manual-submissions/${submission.id}`)
    expect(report.submission.id).toBe(submission.id)
    expect(report.attempts).toHaveLength(1)
  })

  it('passes the opaque DataHub cursor so search previous and next pages can be loaded', async () => {
    const client = useStableApiClient()
    const first = await client.request<CatalogSearch>('/catalog/assets?q=*&limit=1')
    expect(first.items.map((item) => item.name)).toEqual(['wafer_events'])
    expect(first.page.next_cursor).toBe('opaque-page-2')

    const second = await client.request<CatalogSearch>('/catalog/assets?q=*&limit=1&cursor=opaque-page-2')
    expect(second.items.map((item) => item.name)).toEqual(['daily_yield'])
    expect(second.page.next_cursor).toBeNull()
  })

  it('creates and transitions a browser-memory CR with selected live targets', async () => {
    const client = useStableApiClient()
    const created = await client.request<ChangeRequestRecord>('/change-requests/intake', {
      method: 'POST',
      body: JSON.stringify({
        title: 'Live target description change',
        system_id: 'postgres',
        request_date: '2026-08-11',
        request_department: 'Quality',
        request_reason: 'POC verification',
        request_content: 'Update description',
        priority: 'NORMAL',
        urgency: 'NORMAL',
        security_level: 'INTERNAL',
        targets: [{ kind: 'EXISTING', asset_id: liveAssets[0]!.id, description: 'updated' }],
      }),
    })
    expect(created.state).toBe('REGISTERED')
    expect(created.items[0]?.target_asset_id).toBe(liveAssets[0]!.id)

    const summaries = await client.request<{ items: Array<{ id: string }> }>('/change-requests/summaries?limit=25')
    expect(summaries.items[0]?.id).toBe(created.id)
    let current = await client.request<ChangeRequestRecord>(`/change-requests/${created.id}/transitions`, {
      method: 'POST', body: JSON.stringify({ target_state: 'IN_REVIEW', reason: 'submit POC CR', if_match: created.version }),
    })
    expect(current.state).toBe('IN_REVIEW')

    current = await client.request<ChangeRequestRecord>(`/change-requests/${created.id}/approvals`, {
      method: 'POST', body: JSON.stringify({ stage: 'REVIEW', decision: 'APPROVED', reason: 'reviewed', if_match: current.version }),
    })
    expect(current.approvals.at(-1)).toMatchObject({ stage: 'REVIEW', decision: 'APPROVED' })

    current = await client.request<ChangeRequestRecord>(`/change-requests/${created.id}/transitions`, {
      method: 'POST', body: JSON.stringify({ target_state: 'TESTING', reason: 'start test', if_match: current.version }),
    })
    expect(current.state).toBe('TESTING')

    const formData = new FormData()
    formData.set('upload_id', 'poc-test-upload')
    formData.set('kind', 'TEST')
    formData.set('file', new File(['passed'], 'test-result.txt', { type: 'text/plain' }))
    const upload = await client.request<{ finalize_url: string }>(`/change-requests/${created.id}/attachments`, {
      method: 'POST', body: formData,
    })
    await client.request(upload.finalize_url, { method: 'POST' })
    const attachmentPage = await client.request<{ items: Array<{ id: string }> }>(`/change-requests/${created.id}/attachments/page`)

    current = await client.request<ChangeRequestRecord>(`/change-requests/${created.id}/test-runs`, {
      method: 'POST',
      body: JSON.stringify({
        attachment_id: attachmentPage.items[0]!.id,
        system_id: 'postgres',
        state: 'PASSED',
        bounded_summary: { result: 'passed' },
        if_match: current.version,
      }),
    })
    current = await client.request<ChangeRequestRecord>(`/change-requests/${created.id}/approvals`, {
      method: 'POST', body: JSON.stringify({ stage: 'TEST', decision: 'APPROVED', reason: 'passed', if_match: current.version }),
    })
    expect(current.approvals.at(-1)).toMatchObject({ stage: 'TEST', decision: 'APPROVED' })

    current = await client.request<ChangeRequestRecord>(`/change-requests/${created.id}/transitions`, {
      method: 'POST', body: JSON.stringify({ target_state: 'FINAL_REVIEW', reason: 'test complete', if_match: current.version }),
    })
    current = await client.request<ChangeRequestRecord>(`/change-requests/${created.id}/approvals`, {
      method: 'POST', body: JSON.stringify({ stage: 'FINAL', decision: 'APPROVED', reason: 'approved', if_match: current.version }),
    })
    current = await client.request<ChangeRequestRecord>(`/change-requests/${created.id}/complete-intake`, {
      method: 'POST', body: JSON.stringify({ reason: 'complete', if_match: current.version }),
    })
    expect(current.state).toBe('COMPLETED')
  })

  it('returns a contract-valid live DataHub quality workspace without fabricated runs', async () => {
    const client = useStableApiClient()
    const api = new QualityApi(client)
    const capability = await api.capability()
    const definitions = await api.ruleDefinitions()
    const workspace = await api.assetWorkspace(liveAssets[0]!.id, 'a'.repeat(64))
    expect(capability.axes.find((axis) => axis.id === 'manual_execution')).toMatchObject({
      state: 'UNAVAILABLE',
      reason_code: 'QUALITY_CONTROL_PLANE_NOT_CONFIGURED',
    })
    expect(definitions.items.find((item) => item.kind === 'REGEX')).toMatchObject({
      available: false,
      reason_code: 'QUALITY_REGEX_EXECUTION_UNAVAILABLE',
      parameter_contract: {},
    })
    expect(workspace.asset.asset_id).toBe(liveAssets[0]!.id)
    expect(workspace.authoring).toMatchObject({
      state: 'UNAVAILABLE',
      reason_code: 'QUALITY_CONTROL_PLANE_NOT_CONFIGURED',
      fields: [],
    })
    expect(workspace.fields).toEqual([
      expect.objectContaining({
        field_identifier: 'wafer_id',
        latest_quality_outcome: 'UNKNOWN',
      }),
    ])
    expect(workspace.rule_sets).toEqual([])
    expect(workspace.runs).toEqual([])
    await expect(api.requestManualRun('rule-set-not-persisted', 'manual-run-deny-test')).rejects.toThrow(
      'canonical Run/outbox',
    )
    expect(vi.mocked(fetch).mock.calls.some(([input]) => {
      const url = input instanceof Request ? input.url : input instanceof URL ? input.href : input
      return url.includes('datariver_quality_dispatch')
    })).toBe(false)
  })

  it('preserves server-selected graph routing and lineage evidence in Chat', async () => {
    const client = useStableApiClient()
    const workflow: unknown[] = []
    const response = await client.requestEventStream<{
      route: { selected_mode: string; reason: string }
      evidence: Array<{ source_type: string; retrieval_method: string }>
    }>(
      '/chat/query/stream',
      { method: 'POST', body: JSON.stringify({ question: 'upstream 계보 영향은?', mode: 'AUTO' }) },
      (event) => workflow.push(event.data),
    )
    expect(response.route).toMatchObject({ selected_mode: 'GRAPH', reason: 'GRAPH_INTENT' })
    expect(response.evidence[0]).toMatchObject({
      source_type: 'DATAHUB_LINEAGE',
      retrieval_method: 'GRAPH',
    })
    expect(workflow).toEqual(expect.arrayContaining([
      expect.objectContaining({ stage: 'ROUTING', status: 'IN_PROGRESS' }),
    ]))
  })

  it('forwards only the server session identity while PostgreSQL owns bounded continuity memory', async () => {
    const client = useStableApiClient()
    let sessionId: string | undefined
    for (let index = 1; index <= 5; index += 1) {
      const result = await client.requestEventStream<{ session_id: string }>(
        '/chat/query/stream',
        {
          method: 'POST',
          body: JSON.stringify({
            ...(sessionId ? { session_id: sessionId } : {}),
            question: `${index}번째 wafer_events 질문`,
            mode: 'AUTO',
          }),
        },
        () => undefined,
      )
      sessionId = result.session_id
    }

    await client.requestEventStream(
      '/chat/query/stream',
      { method: 'POST', body: JSON.stringify({ session_id: sessionId, question: '그 테이블은?', mode: 'AUTO' }) },
      () => undefined,
    )
    const streamCalls = vi.mocked(fetch).mock.calls.filter(([input]) => (
      new URL(input instanceof Request ? input.url : input.toString(), 'https://poc.invalid').pathname
        === '/poc-api/llm/chat/stream'
    ))
    const sixthBodySource = streamCalls.at(-1)?.[1]?.body
    if (typeof sixthBodySource !== 'string') throw new Error('Expected a JSON Chat request body')
    const sixthBody = JSON.parse(sixthBodySource) as Record<string, unknown>
    expect(sixthBody.session_id).toBe('server-session-1')
    expect(sixthBody).not.toHaveProperty('memory')
    expect(vi.mocked(fetch).mock.calls.some(([input]) => (
      new URL(input instanceof Request ? input.url : input.toString(), 'https://poc.invalid').pathname
        === '/poc-api/llm/chat/compact'
    ))).toBe(false)
  })

  it('rejects a Chat question beyond 12,000 characters before a provider request', async () => {
    const client = useStableApiClient()
    const fetchCalls = vi.mocked(fetch).mock.calls.length
    await expect(client.requestEventStream(
      '/chat/query/stream',
      { method: 'POST', body: JSON.stringify({ question: '가'.repeat(12_001), mode: 'AUTO' }) },
      () => undefined,
    )).rejects.toThrow('12,000자')
    expect(vi.mocked(fetch).mock.calls).toHaveLength(fetchCalls)
  })

  it('supports review changes requested, immutable revision and resubmission in a new round', async () => {
    const client = useStableApiClient()
    let current = await client.request<ChangeRequestRecord>('/change-requests/intake', {
      method: 'POST',
      body: JSON.stringify({
        title: 'Revision flow', system_id: 'postgres', request_reason: 'verify revision',
        request_content: 'first draft', priority: 'NORMAL', urgency: 'NORMAL',
        security_level: 'INTERNAL', targets: [{ kind: 'EXISTING', asset_id: liveAssets[0]!.id }],
      }),
    })
    current = await client.request<ChangeRequestRecord>(`/change-requests/${current.id}/transitions`, {
      method: 'POST', body: JSON.stringify({ target_state: 'IN_REVIEW', reason: 'submit', if_match: current.version }),
    })
    current = await client.request<ChangeRequestRecord>(`/change-requests/${current.id}/transitions`, {
      method: 'POST', body: JSON.stringify({ target_state: 'CHANGES_REQUESTED', reason: 'fix description', if_match: current.version }),
    })
    expect(current.state).toBe('CHANGES_REQUESTED')
    expect(current.revision_allowed).toBe(true)

    current = await client.request<ChangeRequestRecord>(`/change-requests/${current.id}/revisions`, {
      method: 'POST',
      body: JSON.stringify({
        title: 'Revision flow', system_id: 'postgres', request_reason: 'verify revision',
        request_content: 'corrected draft', priority: 'NORMAL', urgency: 'NORMAL',
        security_level: 'INTERNAL', targets: [{ kind: 'EXISTING', asset_id: liveAssets[0]!.id }],
        if_match: current.version,
      }),
    })
    expect(current.state).toBe('REGISTERED')
    expect(current.current_round_number).toBe(2)
    expect(current.rounds.map((round) => round.revision_kind)).toEqual(['INITIAL', 'EDITED'])
  })

  it('exposes POC user creation and redacted system settings without Keycloak', async () => {
    const client = useStableApiClient()
    const context = await client.request<{
      allowed_operations: string[]
      action_vocabulary: string[]
    }>('/admin/me')
    expect(context.allowed_operations).toEqual(expect.arrayContaining([
      'IDENTITY_USER_PROVISION', 'MEMBERSHIP_ACCESS_READ', 'SYSTEM_CONFIGURATION_READ',
    ]))
    expect(context.action_vocabulary).toContain('change.manage')
    expect(context.action_vocabulary).toContain('POC_LOCAL_ACCOUNT_ADMIN_V1')
    expect(context.action_vocabulary).not.toContain('POC_OPEN_ACCESS_V1')

    const provisioned = await client.request<{
      subject_id: string
      temporary_password_required: boolean
      membership_version: number
    }>('/admin/identity-users', {
      method: 'POST',
      body: JSON.stringify({
        username: 'poc.viewer', email: 'poc.viewer@poc.invalid',
        first_name: 'POC', last_name: 'Viewer', job_function: 'data_steward', temporary_password: '',
      }),
    })
    expect(provisioned.temporary_password_required).toBe(false)
    const memberships = await client.request<{ items: WorkspaceMembershipSummary[] }>('/admin/workspace-memberships?limit=25')
    expect(memberships.items.map((item) => item.email)).toContain('poc.viewer@poc.invalid')
    expect(memberships.items.find((item) => item.email === 'poc.viewer@poc.invalid')).toMatchObject({
      job_function: 'data_steward', effective_profile_role: 'ENGINEER_STEWARD',
    })

    const profile = await client.requestWithMeta<{
      email: string
      first_name: string
      last_name: string
      membership_version: number
    }>(`/admin/workspace-memberships/${provisioned.subject_id}/identity-profile`)
    expect(profile.etag).toBe(`"${provisioned.membership_version}"`)
    const updatedProfile = await client.request<{
      email: string
      display_name: string
      membership_version: number
    }>(`/admin/workspace-memberships/${provisioned.subject_id}/identity-profile`, {
      method: 'PUT', ifMatch: profile.etag,
      body: JSON.stringify({
        email: 'updated.viewer@poc.invalid', first_name: 'Updated', last_name: 'Viewer',
        department_id: null, job_function: 'data_steward',
      }),
    })
    expect(updatedProfile).toMatchObject({
      email: 'updated.viewer@poc.invalid', display_name: 'Updated Viewer',
    })
    const roleUpdate = await client.request<{
      active: boolean
      role: string
      membership_version: number
    }>(`/admin/workspace-memberships/${provisioned.subject_id}/access-authority`, {
      method: 'PUT', ifMatch: `"${updatedProfile.membership_version}"`,
      body: JSON.stringify({ active: true, role: 'developer' }),
    })
    expect(roleUpdate).toMatchObject({ active: true, role: 'developer' })

    const system = await client.request<{ system_id: string; code: string }>('/admin/systems', {
      method: 'POST', idempotencyKey: 'system-create-manufacturing-execution',
      body: JSON.stringify({ name: 'Manufacturing Execution', description: 'POC system' }),
    })
    expect(system.code).toBe('MANUFACTURING_EXECUTION_TEST')
    const systems = await client.request<{ items: Array<{ system_id: string }> }>('/admin/systems?limit=25')
    expect(systems.items.map((item) => item.system_id)).toContain(system.system_id)
    const assignment = await client.request<{ system_version: number }>(`/admin/systems/${system.system_id}/assignees`, {
      method: 'PATCH', ifMatch: '"1"',
      body: JSON.stringify({
        upserts: [{ subject_id: provisioned.subject_id, responsibility: 'DEVELOPER', priority: 2 }],
        removals: [],
      }),
    })
    expect(assignment.system_version).toBe(2)
    await expect(client.request<{ items: Array<{ responsibility: string; priority: number }> }>(
      `/admin/systems/${system.system_id}/assignees`,
    )).resolves.toMatchObject({ items: [{ responsibility: 'DEVELOPER', priority: 2 }] })

    const latestProfile = await client.requestWithMeta<{ membership_version: number }>(
      `/admin/workspace-memberships/${provisioned.subject_id}/identity-profile`,
    )
    const stewardUpdate = await client.request<{ membership_version: number }>(
      `/admin/workspace-memberships/${provisioned.subject_id}/access-authority`, {
        method: 'PUT', ifMatch: latestProfile.etag,
        body: JSON.stringify({ active: true, role: 'data_steward' }),
      },
    )
    await client.request(`/admin/systems/${system.system_id}/assignees`, {
      method: 'PATCH', ifMatch: '"2"',
      body: JSON.stringify({
        upserts: [{ subject_id: provisioned.subject_id, responsibility: 'DATA_STEWARD', priority: 3 }],
        removals: [],
      }),
    })
    const inactive = await client.request<{ membership_version: number }>(
      `/admin/workspace-memberships/${provisioned.subject_id}/access-authority`, {
        method: 'PUT', ifMatch: `"${stewardUpdate.membership_version + 1}"`,
        body: JSON.stringify({ active: false, role: 'data_steward' }),
      },
    )
    await expect(client.request(`/admin/workspace-memberships/${provisioned.subject_id}/access-authority`, {
      method: 'PUT', ifMatch: `"${inactive.membership_version}"`,
      body: JSON.stringify({ active: true, role: 'viewer' }),
    })).resolves.toMatchObject({ active: true, role: 'viewer' })

    const archivedSystem = await client.request<{
      system_id: string
      name: string
      active: boolean
      version: number
    }>(`/admin/systems/${system.system_id}`, {
      method: 'PATCH', ifMatch: '"3"',
      body: JSON.stringify({ name: 'Manufacturing Execution Updated', description: 'Archived POC system', active: false }),
    })
    expect(archivedSystem).toMatchObject({
      system_id: system.system_id,
      name: 'Manufacturing Execution Updated',
      active: false,
      version: 4,
    })
    await expect(client.request<{ items: Array<{ active: boolean }> }>(
      `/admin/systems/${system.system_id}/assignees`,
    )).resolves.toMatchObject({ items: [] })

    const settings = await client.request<{ items: SystemConfigurationEntry[] }>('/admin/system-configuration')
    expect(settings.items.find((item) => item.system_id === 'DATAHUB_GMS')?.state).toBe('CONFIGURED')
    expect(settings.items.find((item) => item.system_id === 'S3_STORAGE')?.environment_template)
      .toContain('S3_BUCKET_INFOSCHEMA=')
    expect(JSON.stringify(settings)).not.toContain('temporary_password')
    const probe = await client.request<SystemConfigurationTestResult>('/admin/system-configuration/AIRFLOW/test-deployment', { method: 'POST' })
    expect(probe.status).toBe('AVAILABLE')
  })

  it('renders the existing redacted security-policy contract without fabricated governed records', async () => {
    const client = useStableApiClient()
    const summary = await client.request<ClassificationPolicySummary>(
      '/admin/classification-access/policies/current/summary',
    )
    expect(summary).toEqual({
      state: 'STATIC_FLOOR',
      rules: [
        { classification: 'PUBLIC', search_mode: 'ABAC', chat_mode: 'INTERNAL_APPROVED_ONLY' },
        { classification: 'INTERNAL', search_mode: 'ABAC', chat_mode: 'INTERNAL_APPROVED_ONLY' },
        { classification: 'CONFIDENTIAL', search_mode: 'ABAC', chat_mode: 'DENY' },
        { classification: 'RESTRICTED', search_mode: 'DENY', chat_mode: 'DENY' },
      ],
    })
    expect(await client.request('/admin/classification-access/policies/current')).toBeNull()
    expect(await client.request<{ items: unknown[] }>('/admin/inference/provider-profiles?limit=25'))
      .toEqual(expect.objectContaining({ items: [] }))
    expect(await client.request<{ items: unknown[] }>(
      '/admin/classification-access/restricted-search-grants?limit=25',
    )).toEqual(expect.objectContaining({ items: [] }))
  })

  it('provides open POC governance lifecycle contracts without seeded documents', async () => {
    const api = new GovernanceDocumentsApi(useStableApiClient())
    const capability = await api.capability()
    expect(capability.axes.some((axis) => axis.state === 'DENIED')).toBe(false)
    expect((await api.documents(capability.cache_scope, { kind: 'DOCUMENT', limit: 25 })).items).toEqual([])
    expect((await api.templateBlueprints()).items).toHaveLength(6)

    const created = await api.createDocument({
      kind: 'DOCUMENT', category: 'POLICY', title: 'POC 데이터 정책', summary: '검토 흐름',
      classification: 1, applicability_scope: 'POC', sanitized_html: '<p>정책 본문</p>',
      source_template_version_id: null, parent_document_id: null,
    }, 'governance-create')
    const draft = created.item.versions[0]!
    const submitted = await api.submitVersion(
      created.item.document.document_id, draft.version_id, created.item.document.version, 'governance-submit',
    )
    const reviewed = await api.reviewVersion(
      created.item.document.document_id, draft.version_id, submitted.item.document.version,
      { decision: 'APPROVE', reason: 'POC 검토 완료' }, 'governance-review',
    )
    expect(reviewed.item.document.state).toBe('ACTIVE')
    expect(reviewed.item.versions[0]?.state).toBe('PUBLISHED')
    expect(reviewed.item.subject_display_names[reviewed.item.document.owner_subject_id]).toBe('POC User')
    expect(reviewed.item.subject_display_names[reviewed.item.versions[0]!.author_id]).toBe('POC User')
    expect(reviewed.item.subject_display_names[reviewed.item.versions[0]!.reviewed_by!]).toBe('POC User')

    const importedHtml = await api.importDocument({
      file: new File(['<style>.policy{color:#123456;padding:12px;position:fixed}</style><h1 class="policy">HTML 정책</h1><p><strong>서식</strong> 본문</p><script>alert(1)</script>'], 'policy.html', { type: 'text/html' }),
      kind: 'DOCUMENT', category: 'POLICY', title: 'HTML 가져오기', summary: 'HTML import',
      classification: 1, applicabilityScope: 'POC', parentDocumentId: null,
    }, 'governance-html-import')
    expect(importedHtml.item.versions[0]?.sanitized_html).toContain('>HTML 정책</h1>')
    expect(importedHtml.item.versions[0]?.sanitized_html).toContain('<strong>서식</strong>')
    expect(importedHtml.item.versions[0]?.sanitized_html).not.toContain('data-governance-style')
    expect(importedHtml.item.versions[0]?.sanitized_html).not.toMatch(/color|padding|position/)
    expect(importedHtml.item.versions[0]?.sanitized_html).not.toMatch(/script|alert/i)

    const importedMarkdown = await api.importDocument({
      file: new File(['# Markdown 정책\n\n- 승인\n- 변경 이력'], 'policy.md', { type: 'text/markdown' }),
      kind: 'DOCUMENT', category: 'POLICY', title: 'Markdown 가져오기', summary: 'Markdown import',
      classification: 1, applicabilityScope: 'POC', parentDocumentId: null,
    }, 'governance-markdown-import')
    expect(importedMarkdown.item.versions[0]?.source_format).toBe('MARKDOWN')
    expect(importedMarkdown.item.versions[0]?.sanitized_html).toContain('<h1>Markdown 정책</h1>')
    expect(importedMarkdown.item.versions[0]?.sanitized_html).toContain('<ul><li>승인</li><li>변경 이력</li></ul>')
  })

  it('keeps a referenced legacy POC document actor present after core hydration drops its membership', async () => {
    installLegacyGovernanceHydration([])

    const detail = await useStableApiClient().request<{ item: { subject_display_names: Record<string, string> } }>(
      '/governance/documents/legacy-governance-document',
    )

    expect(detail.item.subject_display_names).toEqual({ [POC_SUBJECT_ID]: 'POC User' })
  })

  it('prefers a hydrated membership display name over the legacy POC document fallback', async () => {
    installLegacyGovernanceHydration([{ subject_id: POC_SUBJECT_ID, display_name: 'Persisted POC Operator' }])

    const detail = await useStableApiClient().request<{ item: { subject_display_names: Record<string, string> } }>(
      '/governance/documents/legacy-governance-document',
    )

    expect(detail.item.subject_display_names).toEqual({ [POC_SUBJECT_ID]: 'Persisted POC Operator' })
  })

  it('gives stewards bounded Governance document management without Knowledge manage/review', async () => {
    configurePocAuthorization({
      policy_version: 'POC_PROFILE_CAPABILITIES_V1',
      role: 'data_steward',
      capabilities: ['knowledge.read', 'change.manage'],
      system_scope: 'ASSIGNED',
      system_ids: [],
    }, 'governance-steward')
    const api = new GovernanceDocumentsApi(useStableApiClient())
    const capability = await api.capability()
    const states = new Map(capability.axes.map((axis) => [axis.id, axis.state]))
    expect(states.get('read')).toBe('AVAILABLE')
    expect(states.get('create')).toBe('AVAILABLE')
    expect(states.get('edit')).toBe('AVAILABLE')
    expect(states.get('archive')).toBe('AVAILABLE')
    expect(states.get('review')).toBe('DENIED')
    expect(states.get('publish')).toBe('DENIED')

    const created = await api.createDocument({
      kind: 'DOCUMENT', category: 'POLICY', title: 'Steward 정책', summary: '최소 문서 관리',
      classification: 1, applicability_scope: 'DEV', sanitized_html: '<p>초안</p>',
      source_template_version_id: null, parent_document_id: null,
    }, 'governance-steward-create')
    expect(created.item.document.allowed_actions).toEqual(expect.arrayContaining(['read', 'create_version', 'archive']))
    expect(created.item.document.allowed_actions).not.toEqual(expect.arrayContaining(['submit', 'review', 'publish', 'add_attachment']))
    await expect(api.submitVersion(
      created.item.document.document_id,
      created.item.versions[0]!.version_id,
      created.item.document.version,
      'governance-steward-submit',
    )).rejects.toThrow(/권한/)
    const archived = await api.archiveDocument(
      created.item.document.document_id,
      created.item.document.version,
      'DEV cleanup',
      'governance-steward-archive',
    )
    expect(archived.item.document.state).toBe('ARCHIVED')

    configurePocAuthorization({
      policy_version: 'POC_PROFILE_CAPABILITIES_V1',
      role: 'developer',
      capabilities: ['knowledge.read', 'change.execute'],
      system_scope: 'ASSIGNED',
      system_ids: [],
    }, 'governance-developer')
    const readOnlyApi = new GovernanceDocumentsApi(useStableApiClient())
    const readOnlyCapability = await readOnlyApi.capability()
    expect(readOnlyCapability.axes.find((axis) => axis.id === 'read')?.state).toBe('AVAILABLE')
    expect(readOnlyCapability.axes.find((axis) => axis.id === 'create')?.state).toBe('DENIED')
    await expect(readOnlyApi.createDocument({
      kind: 'DOCUMENT', category: 'POLICY', title: 'Forbidden', summary: '', classification: 1,
      applicability_scope: '', sanitized_html: '<p>deny</p>', source_template_version_id: null,
      parent_document_id: null,
    }, 'governance-developer-create')).rejects.toThrow(/권한/)
  })

  it('creates Knowledge Studio state only from user input and live DataHub sources', async () => {
    const client = useStableApiClient()
    expect((await client.request<{ items: unknown[] }>('/knowledge/domains')).items).toEqual([])
    await expect(client.request('/knowledge/studio/drafts/resumable?endpoint_alias=missing'))
      .rejects.toMatchObject({
        problem: { status: 404, code: 'KNOWLEDGE_RESUMABLE_DRAFT_NOT_FOUND' },
      })
    const domain = await client.request<{ id: string; source_version: string }>('/knowledge/domains', {
      method: 'POST', body: JSON.stringify({ display_name: 'Manufacturing' }),
    })
    const draft = await client.request<{ id: string; state: string; author_id: string }>('/knowledge/studio/drafts', {
      method: 'POST',
      body: JSON.stringify({
        name: 'Manufacturing ontology', endpoint_alias: 'manufacturing_ontology',
        endpoint_aliases: ['manufacturing_ontology'], domain_id: domain.id,
        domain_source_version: domain.source_version, classification: 'INTERNAL',
      }),
    })
    expect(draft.state).toBe('DRAFT')
    expect(draft.author_id).toBe('live-test-admin')
    const tbox = await client.request<{ blocks: Array<{ kind: string }> }>(
      `/knowledge/studio/drafts/${draft.id}/tbox`,
    )
    expect(tbox.blocks).toEqual([expect.objectContaining({ kind: 'DIRECT' })])
    const sources = await client.request<{ items: Array<{ id: string }> }>(`/knowledge/studio/drafts/${draft.id}/tbox/catalog-sources?q=wafer`)
    expect(sources.items[0]?.id).toBe(liveAssets[0]!.id)
  })

  it('projects a published Knowledge draft through the bounded K1 gateway receipt', async () => {
    ;(globalThis as typeof globalThis & { __DATARIVER_POC_RUNTIME__?: Record<string, boolean> })
      .__DATARIVER_POC_RUNTIME__ = { pocState: true }
    const client = useStableApiClient()
    const domain = await client.request<{ id: string; source_version: string }>('/knowledge/domains', {
      method: 'POST', body: JSON.stringify({ display_name: 'K1 Disposable Domain' }),
    })
    const draft = await client.request<{ id: string }>('/knowledge/studio/drafts', {
      method: 'POST',
      body: JSON.stringify({
        name: 'K1 Disposable Asset',
        endpoint_alias: 'k1_disposable_asset',
        endpoint_aliases: ['k1_disposable_asset'],
        domain_id: domain.id,
        domain_source_version: domain.source_version,
        classification: 'INTERNAL',
      }),
    })
    const tbox = await client.request<{
      blocks: Array<{ id: string }>
    }>(`/knowledge/studio/drafts/${draft.id}/tbox/blocks`, {
      method: 'POST', body: JSON.stringify({ kind: 'DIRECT', title: 'K1 typed layer' }),
    })
    const blockId = tbox.blocks[0]!.id
    await client.request(`/knowledge/studio/drafts/${draft.id}/tbox/blocks/${blockId}/operations`, {
      method: 'POST',
      body: JSON.stringify({ operations: [{
        operation: 'UPSERT_ELEMENT',
        stable_element_id: 'wafer-class',
        element: { kind: 'CLASS', canonical_name: 'wafer', display_name: 'Wafer' },
      }] }),
    })
    await client.request(`/knowledge/studio/drafts/${draft.id}/abox/bindings/wafer-class`, {
      method: 'PATCH',
      body: JSON.stringify({
        source_asset_id: liveAssets[0]!.id,
        rules: [{ source_field_path: 'wafer_id', target_stable_element_id: 'wafer-class' }],
      }),
    })
    configureKnowledgeActor('k1-independent-reviewer', 1)
    await client.request(`/knowledge/studio/drafts/${draft.id}/publish`, {
      method: 'POST', body: JSON.stringify({ review_reason: 'K1 focused adapter verification' }),
    })

    const preview = await client.request<{ job_id: string }>(
      `/knowledge/studio/drafts/${draft.id}/abox/previews`, {
        method: 'POST',
        body: JSON.stringify({ target_stable_element_id: 'wafer-class', sample_limit: 5 }),
      },
    )
    const created = await client.request<{
      state: string
      node_count: number
      duplicate_count: number
      provenance: Array<{ source_type: string }>
    }>(`/knowledge/studio/drafts/${draft.id}/abox/ingestions`, {
      method: 'POST',
      body: JSON.stringify({
        preview_job_id: preview.job_id,
        target_stable_element_id: 'wafer-class',
      }),
      idempotencyKey: 'knowledge-k1-projection',
    })
    expect(created).toMatchObject({ state: 'SUCCESS', node_count: 2, duplicate_count: 0 })
    expect(created.provenance[0]?.source_type).toBe('DETERMINISTIC_ENRICHER')

    const reloaded = await client.request<{
      items: Array<{ id: string; result_evidence_hash: string }>
    }>(`/knowledge/studio/drafts/${draft.id}/abox/ingestions`)
    expect(reloaded.items).toHaveLength(1)
    expect(reloaded.items[0]?.result_evidence_hash).toBe('a'.repeat(64))
  })

  it('forwards Knowledge Chat list, pinned snapshot, and GraphRAG through the Node authority', async () => {
    ;(globalThis as typeof globalThis & { __DATARIVER_POC_RUNTIME__?: Record<string, boolean> })
      .__DATARIVER_POC_RUNTIME__ = { pocState: true }
    const client = useStableApiClient()
    const graphs = await client.request<Array<{ id: string }>>('/knowledge/graphs')
    expect(graphs.map((item) => item.id)).toEqual(['knowledge-k6-graph'])
    const releases = await client.request<Array<{ id: string }>>('/knowledge/graphs/knowledge-k6-graph/releases')
    expect(releases.map((item) => item.id)).toEqual(['knowledge-k6-release'])
    const snapshot = await client.request<{ nodes: Array<{ id: string }>; filtered: boolean }>(
      '/knowledge/graphs/knowledge-k6-graph/releases/knowledge-k6-release/snapshot?maximum_nodes=200',
    )
    expect(snapshot).toMatchObject({ filtered: true, nodes: [{ id: 'node-a' }] })
    const answer = await client.request<{ answer: string; model_audit: { prompt_version: string } }>(
      '/knowledge/graphs/knowledge-k6-graph/releases/knowledge-k6-release/graphrag', {
        method: 'POST', body: JSON.stringify({ question: '관계를 알려줘' }),
      },
    )
    expect(answer.answer).toBe('bounded: 관계를 알려줘')
    expect(answer.model_audit.prompt_version).toBe('knowledge-graphrag-v1')
    const gatewayFetch = vi.mocked(fetch)
    expect(gatewayFetch).toHaveBeenCalledWith(
      '/poc-api/knowledge/graphs/knowledge-k6-graph/releases/knowledge-k6-release/graphrag',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('persists and validates the bounded K3 T-Box shape with draft fencing', async () => {
    ;(globalThis as typeof globalThis & { __DATARIVER_POC_RUNTIME__?: Record<string, boolean> })
      .__DATARIVER_POC_RUNTIME__ = { pocState: true }
    let client = useStableApiClient()
    const domain = await client.request<{ id: string; source_version: string }>('/knowledge/domains', {
      method: 'POST', body: JSON.stringify({ display_name: 'K3 Test Domain' }),
    })
    const draft = await client.request<{ id: string; version: number }>('/knowledge/studio/drafts', {
      method: 'POST',
      body: JSON.stringify({
        name: 'K3 Test Asset',
        endpoint_alias: 'k3_test_asset',
        domain_id: domain.id,
        domain_source_version: domain.source_version,
        classification: 'INTERNAL',
      }),
    })
    const initial = await client.request<{
      blocks: Array<{ id: string }>
    }>(`/knowledge/studio/drafts/${draft.id}/tbox`)
    const blockId = initial.blocks[0]!.id
    const operations = [
      {
        operation: 'UPSERT_ELEMENT',
        stable_element_id: 'class:person',
        element: {
          stable_element_id: 'class:person', kind: 'CLASS', canonical_name: 'Person',
          display_name: 'Person', aliases: ['Human'], vector_index_enabled: false,
        },
      },
      {
        operation: 'UPSERT_ELEMENT',
        stable_element_id: 'class:asset',
        element: {
          stable_element_id: 'class:asset', kind: 'CLASS', canonical_name: 'Asset',
          display_name: 'Asset', parent_stable_element_id: 'class:person',
          aliases: [], vector_index_enabled: false,
        },
      },
      {
        operation: 'UPSERT_ELEMENT',
        stable_element_id: 'relation:owns',
        element: {
          stable_element_id: 'relation:owns', kind: 'RELATION', canonical_name: 'OWNS',
          display_name: 'Owns', source_stable_element_id: 'class:person',
          target_stable_element_id: 'class:asset', direction: 'BIDIRECTED',
          cardinality: 'MANY_TO_MANY', aliases: ['possesses'], vector_index_enabled: false,
        },
      },
      {
        operation: 'UPSERT_ELEMENT',
        stable_element_id: 'property:owns:confidence',
        element: {
          stable_element_id: 'property:owns:confidence', kind: 'PROPERTY',
          canonical_name: 'confidence', display_name: 'Confidence',
          owner_relation_stable_element_id: 'relation:owns', data_type: 'FLOAT',
          nullable: false, value_cardinality: 'SINGLE', unit: 'ratio',
          aliases: [], vector_index_enabled: false,
        },
      },
    ]
    const saved = await client.request<{
      draft: { version: number }
      blocks: Array<{ elements: Array<Record<string, unknown>> }>
    }>(`/knowledge/studio/drafts/${draft.id}/tbox/blocks/${blockId}/operations`, {
      method: 'POST',
      ifMatch: `"${draft.version}"`,
      body: JSON.stringify({ operations }),
    })
    expect(saved.draft.version).toBe(2)
    expect(saved.blocks[0]!.elements.find((item) => item.stable_element_id === 'relation:owns'))
      .toMatchObject({ direction: 'BIDIRECTED', cardinality: 'MANY_TO_MANY' })

    const layered = await client.request<{
      draft: { version: number }
      blocks: Array<{ id: string }>
    }>(`/knowledge/studio/drafts/${draft.id}/tbox/blocks`, {
      method: 'POST', body: JSON.stringify({ kind: 'DIRECT', title: 'K3 Layer 2', weight: 10 }),
    })
    const secondBlockId = layered.blocks.at(-1)!.id
    const layeredSaved = await client.request<{
      draft: { version: number }
    }>(`/knowledge/studio/drafts/${draft.id}/tbox/blocks/${secondBlockId}/operations`, {
      method: 'POST',
      ifMatch: `"${layered.draft.version}"`,
      body: JSON.stringify({
        operations: [{
          operation: 'UPSERT_ELEMENT',
          stable_element_id: 'relation:layered',
          element: {
            stable_element_id: 'relation:layered', kind: 'RELATION',
            canonical_name: 'LAYERED', display_name: 'Layered',
            source_stable_element_id: 'class:person', target_stable_element_id: 'class:asset',
            direction: 'DIRECTED', cardinality: 'ONE_TO_MANY', aliases: [],
            vector_index_enabled: false,
          },
        }],
      }),
    })
    expect(layeredSaved.draft.version).toBe(4)

    configureKnowledgeActor('k3-reloader', 1)
    client = useStableApiClient()
    const reloaded = await client.request<{
      blocks: Array<{ elements: Array<Record<string, unknown>> }>
    }>(`/knowledge/studio/drafts/${draft.id}/tbox`)
    expect(reloaded.blocks[0]!.elements.find((item) => (
      item.stable_element_id === 'property:owns:confidence'
    ))).toMatchObject({
      owner_relation_stable_element_id: 'relation:owns',
      data_type: 'FLOAT',
      value_cardinality: 'SINGLE',
      unit: 'ratio',
    })

    await expect(client.request(
      `/knowledge/studio/drafts/${draft.id}/tbox/blocks/${blockId}/operations`,
      { method: 'POST', ifMatch: '"3"', body: JSON.stringify({ operations }) },
    )).rejects.toThrow('데이터가 변경되었습니다.')
    const invalid = structuredClone(operations)
    ;(invalid[3]!.element as Record<string, unknown>).data_type = 'EXECUTABLE'
    await expect(client.request(
      `/knowledge/studio/drafts/${draft.id}/tbox/blocks/${blockId}/operations`,
      { method: 'POST', ifMatch: '"4"', body: JSON.stringify({ operations: invalid }) },
    )).rejects.toThrow('지원하지 않는 Property 데이터 타입')

    configureKnowledgeActor('k3-read-only', 1, ['knowledge.read'])
    client = useStableApiClient()
    await expect(client.request(
      `/knowledge/studio/drafts/${draft.id}/tbox/blocks/${blockId}/operations`,
      { method: 'POST', ifMatch: '"4"', body: JSON.stringify({ operations }) },
    )).rejects.toThrow(/권한/)
  })

  it('manages K2 knowledge asset lifecycle: drafts, publish constraints, edit, and archive', async () => {
    ;(globalThis as typeof globalThis & { __DATARIVER_POC_RUNTIME__?: Record<string, boolean> })
      .__DATARIVER_POC_RUNTIME__ = { pocState: true }
    const client = useStableApiClient()

    const domain = await client.request<{ id: string; source_version: string }>('/knowledge/domains', {
      method: 'POST', body: JSON.stringify({ display_name: 'K2 Test Domain' }),
    })

    const draft = await client.request<{ id: string; version: number; materialized_graph_id?: string; endpoint_alias: string }>('/knowledge/studio/drafts', {
      method: 'POST',
      body: JSON.stringify({ name: 'K2 Test Asset', endpoint_alias: 'k2_test_asset', domain_id: domain.id, domain_source_version: domain.source_version, classification: 'INTERNAL' })
    })

    // Pre-publish registry
    let registry = await client.request<KnowledgeAssetPage>('/knowledge/registry/assets')
    let asset = registry.items.find((item) => item.id === draft.id)
    expect(asset).toBeDefined()
    expect(asset?.status).toBe('DRAFT')

    // Pre-publish detail
    const detailRes = await client.request<KnowledgeAssetOperationalDetail>(`/knowledge/registry/assets/${draft.id}/detail`)
    expect(detailRes.asset.status).toBe('DRAFT')

    await expect(client.request(`/knowledge/studio/drafts/${draft.id}/publish`, {
      method: 'POST', body: JSON.stringify({ review_reason: 'test' }), ifMatch: `"${draft.version}"`,
    })).rejects.toThrow('작성자는 직접 승인/발행할 수 없습니다.')

    configureKnowledgeActor('k2-independent-reviewer', 1)
    const publishRes = await client.request<{ draft: KnowledgeStudioDraft; release: KnowledgeStudioRelease }>(`/knowledge/studio/drafts/${draft.id}/publish`, {
      method: 'POST', body: JSON.stringify({ review_reason: 'approved' }), ifMatch: `"${draft.version}"`,
    })

    const graphId = publishRes.draft.materialized_graph_id
    expect(graphId).toBeDefined()

    registry = await client.request<KnowledgeAssetPage>('/knowledge/registry/assets')
    asset = registry.items.find((item) => item.id === graphId)
    expect(asset).toBeDefined()
    expect(asset?.status).toBe('ACTIVE')
    expect(asset?.creator_name).toBe('live-test-admin')
    expect(asset?.editor_name).toBe('k2-independent-reviewer')
    expect(asset?.display_version).toBe(1)

    const deliveryBody = JSON.stringify({
      api_enabled: false,
      chat_enabled: true,
      priority: 700,
      match_any_terms: ['품질 관계'],
      match_all_terms: [],
      excluded_terms: ['임시'],
    })
    const deliveryPolicy = await client.request<KnowledgeDeliveryPolicy>(
      `/knowledge/registry/assets/${graphId}/delivery-policy`,
      { method: 'PUT', body: deliveryBody, idempotencyKey: 'k7-policy-create' },
    )
    expect(deliveryPolicy.version).toBe(1)
    expect(deliveryPolicy.graph_id).toBe(graphId)
    expect(deliveryPolicy.match_any_terms).toEqual(['품질 관계'])
    const replayedPolicy = await client.request<KnowledgeDeliveryPolicy>(
      `/knowledge/registry/assets/${graphId}/delivery-policy`,
      { method: 'PUT', body: deliveryBody, idempotencyKey: 'k7-policy-create' },
    )
    expect(replayedPolicy.version).toBe(1)
    registry = await client.request<KnowledgeAssetPage>('/knowledge/registry/assets')
    expect(registry.items.find((item) => item.id === graphId)?.delivery_policy?.id).toBe(deliveryPolicy.id)
    await expect(client.request(
      `/knowledge/registry/assets/${graphId}/delivery-policy`,
      {
        method: 'PUT', body: deliveryBody, ifMatch: '"0"',
        idempotencyKey: 'k7-policy-stale',
      },
    )).rejects.toThrow('데이터가 변경되었습니다.')

    configureKnowledgeActor('k2-editor', 1)
    const editDraft = await client.request<{ id: string; version: number }>(`/knowledge/studio/drafts/from-asset/${graphId}`, {
      method: 'POST'
    })
    expect(editDraft.id).not.toBe(draft.id)

    registry = await client.request<KnowledgeAssetPage>('/knowledge/registry/assets')
    asset = registry.items.find((item) => item.id === graphId)
    expect(asset?.status).toBe('DRAFT')
    expect(asset?.draft_id).toBe(editDraft.id)
    expect(asset?.display_version).toBe(2)
    expect(asset?.creator_name).toBe('live-test-admin')
    expect(asset?.editor_name).toBe('k2-editor')

    const initialEditVersion = editDraft.version
    const savedEdit = await client.request<{ version: number; author_id: string }>(`/knowledge/studio/drafts/${editDraft.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ description: 'K2 edited description', author_id: 'forged-author' }),
      ifMatch: `"${initialEditVersion}"`,
    })
    expect(savedEdit.author_id).toBe('k2-editor')
    await expect(client.request(`/knowledge/studio/drafts/${editDraft.id}`, {
      method: 'PATCH', body: JSON.stringify({ description: 'stale write' }), ifMatch: `"${initialEditVersion}"`,
    })).rejects.toThrow('데이터가 변경되었습니다.')

    // The active Registry version remains authoritative while a new Draft is edited.
    const activeVersions = await client.request<KnowledgeAssetVersionHistoryPage>(
      `/knowledge/registry/assets/${graphId}/versions`,
    )
    expect(activeVersions.items.some((item) => item.status === 'ACTIVE')).toBe(true)

    const versions = await client.request<KnowledgeAssetVersionHistoryPage>(`/knowledge/registry/assets/${graphId}/versions`)
    expect(versions.items.length).toBeGreaterThanOrEqual(2)

    configureKnowledgeActor('k2-read-only', 1, ['knowledge.read'])
    await expect(client.request(`/knowledge/graphs/${graphId}/archive`, {
      method: 'POST', ifMatch: `"${savedEdit.version}"`,
    })).rejects.toThrow(/권한/)

    configureKnowledgeActor('k2-independent-reviewer', 2)
    await expect(client.request(`/knowledge/graphs/${graphId}/archive`, {
      method: 'POST', ifMatch: `"0"`,
    })).rejects.toThrow('데이터가 변경되었습니다.')

    const archived = await client.request<{ status: string }>(`/knowledge/graphs/${graphId}/archive`, {
      method: 'POST', ifMatch: `"${savedEdit.version}"`,
    })
    expect(archived.status).toBe('ARCHIVED')

    registry = await client.request<KnowledgeAssetPage>('/knowledge/registry/assets')
    asset = registry.items.find((item) => item.id === graphId)
    expect(asset?.status).toBe('ARCHIVED')
  })

  it('proxies the apply-report route to the live POC server', async () => {
    const client = useStableApiClient()
    const response = await client.request<{ change_request_id: string; state: string }>(
      '/change-requests/proxy-test-1/apply-report'
    )
    expect(response.change_request_id).toBe('proxy-test-1')
    expect(response.state).toBe('NOT_STARTED')
  })

  it('creates and applies a Catalog T-Box proposal job without external LLM/A-Box dependencies', async () => {
    ;(globalThis as typeof globalThis & { __DATARIVER_POC_RUNTIME__?: Record<string, boolean> })
      .__DATARIVER_POC_RUNTIME__ = { datahub: true, pocState: true }
    configureKnowledgeActor('k4-admin', 1, ['knowledge.manage', 'knowledge.read'])
    const client = useStableApiClient()

    const domain = await client.request<{ id: string; source_version: string }>('/knowledge/domains', {
      method: 'POST', body: JSON.stringify({ display_name: 'Test Domain' }),
    })
    const draftRes = await client.requestWithMeta<KnowledgeStudioDraft>('/knowledge/studio/drafts', {
      method: 'POST',
      body: JSON.stringify({
        name: 'Catalog Proposal Draft',
        endpoint_alias: 'catalog_proposal_draft',
        domain_id: domain.id,
        domain_source_version: domain.source_version,
        classification: 'normal',
      }),
    })
    const draftId = draftRes.data.id
    const tbox = await client.request<{ blocks: Array<{ id: string }> }>(
      `/knowledge/studio/drafts/${draftId}/tbox`,
    )
    const blockId = tbox.blocks[0]!.id
    const assetId = 'urn:li:dataset:(urn:li:dataPlatform:postgres,FACTORY.QUALITY.wafer_events,PROD)'
    const columnUrn = `urn:li:schemaField:(${assetId},wafer_id)`
    const jobPath = `/knowledge/studio/drafts/${draftId}/tbox/proposal-jobs`
    const jobBody = JSON.stringify({
      input_kind: 'CATALOG_SCHEMA',
      asset_id: assetId,
      selected_field_paths: ['wafer_id'],
      expected_selection_fingerprint: 'f'.repeat(64),
      target_block_id: blockId,
      mode: 'MERGE_INTO_CURRENT',
    })
    await expect(client.request(jobPath, {
      method: 'POST',
      ifMatch: draftRes.etag,
      body: JSON.stringify({ ...JSON.parse(jobBody), expected_selection_fingerprint: '0'.repeat(64) }),
    })).rejects.toThrow(/변경되었습니다/)
    await expect(client.request(jobPath, {
      method: 'POST',
      ifMatch: draftRes.etag,
      body: JSON.stringify({
        ...JSON.parse(jobBody),
        asset_id: liveAssets[1]!.id,
      }),
    })).rejects.toThrow(/보안등급/)
    const jobRes = await client.request<{
      id: string
      state: string
      stage: string
      result_proposal_id: string
    }>(jobPath, {
      method: 'POST',
      ifMatch: draftRes.etag,
      idempotencyKey: 'k4-catalog-job',
      body: jobBody,
    })
    expect(jobRes.state).toBe('SUCCEEDED')
    expect(jobRes.stage).toBe('COMPLETED')
    const replay = await client.request<{ id: string }>(jobPath, {
      method: 'POST',
      ifMatch: draftRes.etag,
      idempotencyKey: 'k4-catalog-job',
      body: jobBody,
    })
    expect(replay.id).toBe(jobRes.id)
    const proposalId = jobRes.result_proposal_id
    const proposalRes = await client.request<{
      state: string
      elements: Array<{ kind: string; metadata_reference_urn: string }>
      source_reference: {
        table_urn: string
        selected_column_urns: string[]
        pipeline_evidence: { cypher_execution: boolean }
      }
    }>(`/knowledge/studio/drafts/${draftId}/tbox/proposals/${proposalId}`)
    expect(proposalRes.state).toBe('READY')
    expect(proposalRes.elements.map((item) => item.kind)).toEqual(['CLASS', 'PROPERTY'])
    expect(proposalRes.elements.map((item) => item.metadata_reference_urn)).toEqual([assetId, columnUrn])
    expect(proposalRes.source_reference).toMatchObject({
      table_urn: assetId,
      selected_column_urns: [columnUrn],
      pipeline_evidence: { cypher_execution: false },
    })
    const ingestionPath = `/knowledge/studio/drafts/${draftId}/abox/ingestions`
    expect((await client.request<{ items: unknown[] }>(ingestionPath)).items).toEqual([])
    const applyPath = `/knowledge/studio/drafts/${draftId}/tbox/proposals/${proposalId}/apply`
    const applyBody = JSON.stringify({
      merge_strategy: 'RESOLVE',
      element_overrides: [],
      resolutions: [],
      excluded_stable_element_ids: [],
    })
    await expect(client.request(applyPath, {
      method: 'POST', ifMatch: '"0"', idempotencyKey: 'k4-apply', body: applyBody,
    })).rejects.toThrow(/변경되었습니다/)
    const applyRes = await client.request<{
      draft: { version: number }
      blocks: Array<{ elements: Array<{ canonical_name: string; kind: string; metadata_reference_urn: string }> }>
    }>(applyPath, {
      method: 'POST',
      ifMatch: draftRes.etag,
      idempotencyKey: 'k4-apply',
      body: applyBody,
    })
    expect(applyRes.blocks[0]!.elements.map((item) => item.kind)).toEqual(['CLASS', 'PROPERTY'])
    expect(applyRes.blocks[0]!.elements[1]).toMatchObject({
      canonical_name: 'wafer_id', metadata_reference_urn: columnUrn,
    })
    expect((await client.request<{ items: unknown[] }>(ingestionPath)).items).toEqual([])

    const reloaded = await client.request<{
      blocks: Array<{ elements: Array<{ stable_element_id: string }> }>
    }>(`/knowledge/studio/drafts/${draftId}/tbox`)
    expect(reloaded.blocks[0]!.elements).toHaveLength(2)
    expect(reloaded.blocks[0]!.elements.every((item) => item.stable_element_id.length > 0)).toBe(true)
    const persisted = await (await fetch('/poc-api/state/core')).json() as {
      value: { knowledgeTBoxProposals: Array<{ id: string; state: string }> }
    }
    expect(persisted.value.knowledgeTBoxProposals).toContainEqual(
      expect.objectContaining({ id: proposalId, state: 'APPLIED' }),
    )

    configureKnowledgeActor('k4-reader', 1, ['knowledge.read'])
    await expect(client.request(jobPath, {
      method: 'POST', ifMatch: `"${applyRes.draft.version}"`, body: jobBody,
    })).rejects.toThrow(/권한/)
  })
})
