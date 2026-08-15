import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type {
  CatalogAsset,
  CatalogAssetDetail,
  CatalogSearch,
  ChangeRequestRecord,
  ClassificationPolicySummary,
  SystemConfigurationEntry,
  SystemConfigurationTestResult,
  WorkspaceMembershipSummary,
} from '../api/types'
import { QualityApi } from '../features/quality/qualityApi'
import { GovernanceDocumentsApi } from '../features/governance-documents/governanceDocumentsApi'
import { resetPocMemory, useStableApiClient } from './pocApi'

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
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, options?: RequestInit) => {
    const requestUrl = input instanceof Request ? input.url : input.toString()
    const url = new URL(requestUrl, 'https://poc.invalid')
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
    if (url.pathname === '/poc-api/llm/chat/compact') {
      return Promise.resolve(json({ summary: 'wafer_events 계보를 확인한 대화', compacted_turn_count: 5 }))
    }
    if (url.pathname === '/poc-api/llm/chat/stream') {
      const result = {
        answer: 'wafer_events는 source_events의 영향을 받습니다. [1]',
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
          extraction_method: 'DATAHUB_GMS_LINEAGE',
          retrieval_method: 'GRAPH',
        }],
      }
      const frames = [
        { event: 'workflow', data: { stage: 'ROUTING', status: 'IN_PROGRESS', detail_code: 'ROUTING_IN_PROGRESS' } },
        { event: 'workflow', data: { stage: 'ROUTING', status: 'COMPLETED', detail_code: 'GRAPH_ROUTE_SELECTED' } },
        { event: 'workflow', data: { stage: 'RETRIEVAL', status: 'COMPLETED', detail_code: 'GRAPH_RETRIEVAL_COMPLETED' } },
        { event: 'result', data: result },
      ].map((frame) => `event: ${frame.event}\ndata: ${JSON.stringify(frame.data)}\n\n`).join('')
      return Promise.resolve(new Response(frames, {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
      }))
    }
    throw new Error(`Unexpected POC gateway request: ${url.pathname}`)
  }))
}

describe('POC live-provider compatibility adapter', () => {
  beforeEach(() => {
    resetPocMemory()
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

  it('resolves an opaque active System through its exact schema scopes and preserves provider-platform routing', async () => {
    const client = useStableApiClient()
    const system = await client.request<{ system_id: string }>('/admin/systems', {
      method: 'POST',
      body: JSON.stringify({
        code: 'FAB', name: 'Fabrication', description: 'Canonical business System',
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
    const workspace = await api.assetWorkspace(liveAssets[0]!.id, 'a'.repeat(64))
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

  it('carries bounded same-session question and answer memory and compacts every five turns', async () => {
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

    await vi.waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([input]) => (
      new URL(input instanceof Request ? input.url : input.toString(), 'https://poc.invalid').pathname
        === '/poc-api/llm/chat/compact'
    ))).toBe(true))
    const compactCall = vi.mocked(fetch).mock.calls.find(([input]) => (
      new URL(input instanceof Request ? input.url : input.toString(), 'https://poc.invalid').pathname
        === '/poc-api/llm/chat/compact'
    ))
    const compactBodySource = compactCall?.[1]?.body
    if (typeof compactBodySource !== 'string') throw new Error('Expected a JSON compaction request body')
    const compactBody = JSON.parse(compactBodySource) as {
      memory: { recent_turns: unknown[] }
    }
    expect(compactBody.memory.recent_turns).toHaveLength(5)
    await new Promise((resolve) => window.setTimeout(resolve, 0))

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
    const sixthBody = JSON.parse(sixthBodySource) as {
      memory: { summary: string; compacted_turn_count: number; recent_turns: unknown[] }
    }
    expect(sixthBody.memory).toEqual({
      summary: 'wafer_events 계보를 확인한 대화',
      compacted_turn_count: 5,
      recent_turns: [],
    })
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
    expect(context.action_vocabulary).toContain('change.edit')

    const provisioned = await client.request<{ temporary_password_required: boolean }>('/admin/identity-users', {
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

    const system = await client.request<{ system_id: string; code: string }>('/admin/systems', {
      method: 'POST', body: JSON.stringify({ code: 'MES', name: 'Manufacturing Execution', description: 'POC system' }),
    })
    expect(system.code).toBe('MES')
    const systems = await client.request<{ items: Array<{ system_id: string }> }>('/admin/systems?limit=25')
    expect(systems.items.map((item) => item.system_id)).toContain(system.system_id)

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

    const importedHtml = await api.importDocument({
      file: new File(['<style>.policy{color:#123456;padding:12px;position:fixed}</style><h1 class="policy">HTML 정책</h1><p><strong>서식</strong> 본문</p><script>alert(1)</script>'], 'policy.html', { type: 'text/html' }),
      kind: 'DOCUMENT', category: 'POLICY', title: 'HTML 가져오기', summary: 'HTML import',
      classification: 1, applicabilityScope: 'POC', parentDocumentId: null,
    }, 'governance-html-import')
    expect(importedHtml.item.versions[0]?.sanitized_html).toContain('>HTML 정책</h1>')
    expect(importedHtml.item.versions[0]?.sanitized_html).toContain('<strong>서식</strong>')
    expect(importedHtml.item.versions[0]?.sanitized_html).toContain('data-governance-style="color:#123456;padding:12px"')
    expect(importedHtml.item.versions[0]?.sanitized_html).not.toContain('position')
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

  it('creates Knowledge Studio state only from user input and live DataHub sources', async () => {
    const client = useStableApiClient()
    expect((await client.request<{ items: unknown[] }>('/knowledge/domains')).items).toEqual([])
    const domain = await client.request<{ id: string; source_version: string }>('/knowledge/domains', {
      method: 'POST', body: JSON.stringify({ display_name: 'Manufacturing' }),
    })
    const draft = await client.request<{ id: string; state: string }>('/knowledge/studio/drafts', {
      method: 'POST',
      body: JSON.stringify({
        name: 'Manufacturing ontology', endpoint_alias: 'manufacturing_ontology',
        endpoint_aliases: ['manufacturing_ontology'], domain_id: domain.id,
        domain_source_version: domain.source_version, classification: 'INTERNAL',
      }),
    })
    expect(draft.state).toBe('DRAFT')
    const sources = await client.request<{ items: Array<{ id: string }> }>(`/knowledge/studio/drafts/${draft.id}/tbox/catalog-sources?q=wafer`)
    expect(sources.items[0]?.id).toBe(liveAssets[0]!.id)
  })
})
