import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiClient } from '../../../api/client'
import {
  advanceKnowledgeStudioDraft,
  autosaveKnowledgeStudioDraft,
  cancelKnowledgeStudioTBoxProposalJob,
  cancelKnowledgeStudioIngestion,
  completeKnowledgeStudioSourceUpload,
  createKnowledgeStudioRelationIngestion,
  createKnowledgeStudioDraft,
  createKnowledgeStudioEditDraft,
  createKnowledgeStudioTBoxAssetReleaseProposal,
  createKnowledgeStudioTBoxProposalJob,
  createKnowledgeStudioManagedDomain,
  discardKnowledgeStudioDraft,
  getKnowledgeStudioSourceUpload,
  getKnowledgeStudioTBoxProposalJob,
  getResumableKnowledgeStudioDraft,
  initiateKnowledgeStudioSourceUpload,
  listKnowledgeStudioTBoxProposalJobs,
  listKnowledgeStudioDomains,
  listKnowledgeStudioManagedDomains,
  preflightKnowledgeStudioABox,
  presignKnowledgeStudioSourceUploadPart,
  previewKnowledgeStudioBinding,
  previewKnowledgeStudioRelation,
  publishKnowledgeStudioDraft,
  retryKnowledgeStudioTBoxProposalJob,
  retryKnowledgeStudioIngestion,
  searchKnowledgeStudioTBoxCatalogSources,
  searchKnowledgeStudioTBoxAssetReleases,
  submitKnowledgeStudioReview,
  uploadKnowledgeStudioSourceUploadPart,
  type KnowledgeStudioBasicInformation,
} from './knowledgeStudioApi'

function requestUrl(input: RequestInfo | URL | undefined): string {
  if (!input) return ''
  if (typeof input === 'string') return input
  return input instanceof URL ? input.toString() : input.url
}

function jsonResponse(value: unknown, etag?: string, status = 200): Response {
  const headers = new Headers({ 'Content-Type': 'application/json' })
  if (etag) headers.set('ETag', etag)
  return new Response(JSON.stringify(value), { status, headers })
}

const payload: KnowledgeStudioBasicInformation = {
  name: '반도체 소재 그래프',
  endpoint_alias: 'semiconductor_materials',
  endpoint_aliases: ['semiconductor_materials', 'materials_kg'],
  domain_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3af',
  domain_source_version: 'domain-v3',
  classification: 'normal',
}

function draftResponse(version: number): Record<string, unknown> {
  return {
    id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3b0',
    author_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3b1',
    kind: 'CREATE',
    state: 'DRAFT',
    current_step: 'BASIC',
    ...payload,
    last_autosaved_at: '2026-07-28T01:00:00Z',
    version,
    created_at: '2026-07-28T01:00:00Z',
    updated_at: '2026-07-28T01:00:00Z',
  }
}

afterEach(() => vi.unstubAllGlobals())

describe('Knowledge Studio API', () => {
  it('uses bounded domain options and fenced idempotent Draft commands', async () => {
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify(draftResponse(1)), {
        status: 201,
        headers: { 'Content-Type': 'application/json', ETag: '"1"' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify(draftResponse(2)), {
        status: 200,
        headers: { 'Content-Type': 'application/json', ETag: '"2"' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        ...draftResponse(3), current_step: 'TBOX',
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json', ETag: '"3"' },
      }))
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')

    await listKnowledgeStudioDomains(client, 'normal')
    await createKnowledgeStudioDraft(client, payload, 'create-key')
    await autosaveKnowledgeStudioDraft(
      client,
      '019fa57b-52de-74c0-9f5e-06ae7b1bf3b0',
      payload,
      '"1"',
      'autosave-key',
    )
    await advanceKnowledgeStudioDraft(
      client,
      '019fa57b-52de-74c0-9f5e-06ae7b1bf3b0',
      '"2"',
      'advance-key',
    )

    expect(requestUrl(fetchMock.mock.calls[0]?.[0])).toContain(
      '/knowledge/domains?classification=normal&limit=100',
    )
    const createHeaders = new Headers(fetchMock.mock.calls[1]?.[1]?.headers)
    expect(createHeaders.get('Idempotency-Key')).toBe('create-key')
    const autosaveHeaders = new Headers(fetchMock.mock.calls[2]?.[1]?.headers)
    expect(autosaveHeaders.get('If-Match')).toBe('"1"')
    expect(autosaveHeaders.get('Idempotency-Key')).toBe('autosave-key')
    const advanceHeaders = new Headers(fetchMock.mock.calls[3]?.[1]?.headers)
    expect(advanceHeaders.get('If-Match')).toBe('"2"')
    expect(advanceHeaders.get('Idempotency-Key')).toBe('advance-key')
  })

  it('opens a published asset through the idempotent edit-Draft contract', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ ...draftResponse(1), kind: 'EDIT' }), {
        status: 201,
        headers: { 'Content-Type': 'application/json', ETag: '"1"' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')
    const assetId = '019fa57b-52de-74c0-9f5e-06ae7b1bf3c0'

    await createKnowledgeStudioEditDraft(client, assetId, 'edit-key')

    expect(requestUrl(fetchMock.mock.calls[0]?.[0])).toContain(
      `/knowledge/studio/drafts/from-asset/${assetId}`,
    )
    const headers = new Headers(fetchMock.mock.calls[0]?.[1]?.headers)
    expect(headers.get('Idempotency-Key')).toBe('edit-key')
    expect(fetchMock.mock.calls[0]?.[1]?.method).toBe('POST')
  })

  it('resumes an author-owned live Draft with its current ETag', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(draftResponse(4)), {
        status: 200,
        headers: { 'Content-Type': 'application/json', ETag: '"4"' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')

    const response = await getResumableKnowledgeStudioDraft(
      client,
      'semiconductor_materials',
    )

    expect(response.etag).toBe('"4"')
    expect(requestUrl(fetchMock.mock.calls[0]?.[0])).toContain(
      '/knowledge/studio/drafts/resumable?endpoint_alias=semiconductor_materials',
    )
    expect(fetchMock.mock.calls[0]?.[1]?.cache).toBe('no-store')
  })

  it('fails closed when a Draft response omits its ETag', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify(draftResponse(1)),
      { status: 201, headers: { 'Content-Type': 'application/json' } },
    )))
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')

    await expect(
      createKnowledgeStudioDraft(client, payload, 'create-key'),
    ).rejects.toThrow(/ETag/)
  })

  it('uses the accepted source-upload lifecycle before creating a fenced 202 Proposal job', async () => {
    const upload = {
      id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3cb',
      display_name: 'schema.csv',
      state: 'INITIATED',
      size_bytes: 12,
      content_type: 'text/csv',
      sha256: 'a'.repeat(64),
      classification: 'normal',
      content_profile: 'KNOWLEDGE_STUDIO_DOCUMENT_V1',
      expires_at: '2026-07-31T03:00:00Z',
      version: 1,
      validation_summary: {},
      last_error_code: null,
      recommended_part_size_bytes: 10 * 1024 * 1024,
    }
    const accepted = {
      ...upload,
      state: 'ACCEPTED',
      version: 5,
      validation_summary: { profile_configuration_hash: 'b'.repeat(64) },
    }
    const job = {
      id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3cc',
      draft_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3b0',
      input_kind: 'DOCUMENT_SCHEMA',
      mode: 'MERGE_INTO_CURRENT',
      target_block_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3ca',
      state: 'QUEUED',
      stage: 'QUEUED',
      progress_percent: 0,
      attempt_count: 0,
      maximum_attempts: 4,
      last_failure_code: null,
      version: 1,
      created_at: '2026-07-31T01:00:00Z',
      updated_at: '2026-07-31T01:00:00Z',
      completed_at: null,
      result_proposal_id: null,
      result_evidence_hash: null,
      supersedes_job_id: null,
    }
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(upload, '"1"', 201))
      .mockResolvedValueOnce(jsonResponse({
        url: 'https://objects.test/upload-part',
        expires_seconds: 900,
      }))
      .mockResolvedValueOnce(new Response(undefined, {
        status: 200,
        headers: { ETag: '"object-etag"' },
      }))
      .mockResolvedValueOnce(jsonResponse({ ...upload, state: 'COMPLETION_QUEUED', version: 2 }, '"2"'))
      .mockResolvedValueOnce(jsonResponse(accepted, '"5"'))
      .mockResolvedValueOnce(jsonResponse(job, '"1"', 202))
      .mockResolvedValueOnce(jsonResponse({
        items: [job],
        page: { next_cursor: null, limit: 20 },
      }))
      .mockResolvedValueOnce(jsonResponse(job, '"1"'))
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')
    const source = await initiateKnowledgeStudioSourceUpload(
      client,
      job.draft_id,
      {
        display_name: upload.display_name,
        size_bytes: upload.size_bytes,
        content_type: upload.content_type,
        sha256: upload.sha256,
      },
      'source-init-key',
    )
    const signed = await presignKnowledgeStudioSourceUploadPart(
      client,
      job.draft_id,
      source.data.id,
      1,
    )
    const part = await uploadKnowledgeStudioSourceUploadPart(
      signed.url,
      new File(['schema bytes'], upload.display_name, { type: upload.content_type }),
    )
    await completeKnowledgeStudioSourceUpload(
      client,
      job.draft_id,
      source.data.id,
      [part],
      source.etag!,
      'source-complete-key',
    )
    const current = await getKnowledgeStudioSourceUpload(client, job.draft_id, source.data.id)
    await createKnowledgeStudioTBoxProposalJob(
      client,
      job.draft_id,
      {
        input_kind: 'DOCUMENT_SCHEMA',
        source_upload_id: current.data.id,
        source_manifest_version: current.data.version,
        target_block_id: job.target_block_id,
        mode: 'MERGE_INTO_CURRENT',
      },
      '"3"',
      'proposal-job-key',
    )
    await listKnowledgeStudioTBoxProposalJobs(client, job.draft_id)
    await getKnowledgeStudioTBoxProposalJob(client, job.draft_id, job.id)

    const paths = fetchMock.mock.calls.map(([input]) => requestUrl(input))
    expect(paths[0]).toContain(`/drafts/${job.draft_id}/source-uploads`)
    expect(paths[1]).toContain(`/source-uploads/${upload.id}/parts`)
    expect(paths[2]).toBe('https://objects.test/upload-part')
    expect(paths[3]).toContain(`/source-uploads/${upload.id}/complete`)
    expect(paths[4]).toContain(`/source-uploads/${upload.id}`)
    expect(paths[5]).toContain('/tbox/proposal-jobs')
    expect(paths[6]).toContain('/tbox/proposal-jobs?limit=20')
    expect(paths[7]).toContain(`/tbox/proposal-jobs/${job.id}`)
    expect(new Headers(fetchMock.mock.calls[0]?.[1]?.headers).get('Idempotency-Key'))
      .toBe('source-init-key')
    const partBody = fetchMock.mock.calls[1]?.[1]?.body
    expect(JSON.parse(typeof partBody === 'string' ? partBody : '{}')).toEqual({
      part_number: 1,
    })
    expect(new Headers(fetchMock.mock.calls[3]?.[1]?.headers).get('If-Match')).toBe('"1"')
    expect(new Headers(fetchMock.mock.calls[5]?.[1]?.headers).get('If-Match')).toBe('"3"')
    expect(new Headers(fetchMock.mock.calls[5]?.[1]?.headers).get('Idempotency-Key'))
      .toBe('proposal-job-key')
  })

  it('sends the server-issued Catalog selection fingerprint as an opaque fence', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValueOnce(jsonResponse({
      id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3cc',
      draft_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3b0',
      input_kind: 'CATALOG_SCHEMA',
      mode: 'APPEND_LAYER',
      target_block_id: null,
      state: 'QUEUED',
      stage: 'QUEUED',
      progress_percent: 0,
      attempt_count: 0,
      maximum_attempts: 4,
      last_failure_code: null,
      version: 1,
      created_at: '2026-08-01T01:00:00Z',
      updated_at: '2026-08-01T01:00:00Z',
      completed_at: null,
      result_proposal_id: null,
      result_evidence_hash: null,
      supersedes_job_id: null,
    }, '"1"', 202))
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')

    await createKnowledgeStudioTBoxProposalJob(
      client,
      '019fa57b-52de-74c0-9f5e-06ae7b1bf3b0',
      {
        input_kind: 'CATALOG_SCHEMA',
        asset_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3d0',
        selected_field_paths: ['order_id'],
        expected_selection_fingerprint: 'f'.repeat(64),
        mode: 'APPEND_LAYER',
      },
      '"2"',
      'catalog-proposal-key',
    )

    const requestBody = fetchMock.mock.calls[0]?.[1]?.body
    expect(JSON.parse(typeof requestBody === 'string' ? requestBody : '{}')).toEqual({
      input_kind: 'CATALOG_SCHEMA',
      asset_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3d0',
      selected_field_paths: ['order_id'],
      expected_selection_fingerprint: 'f'.repeat(64),
      mode: 'APPEND_LAYER',
    })
    expect(new Headers(fetchMock.mock.calls[0]?.[1]?.headers).get('If-Match')).toBe('"2"')
    expect(new Headers(fetchMock.mock.calls[0]?.[1]?.headers).get('Idempotency-Key'))
      .toBe('catalog-proposal-key')
  })

  it('fences Proposal job cancel and retry commands with the current job ETag', async () => {
    const job = {
      id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3cc',
      draft_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3b0',
      input_kind: 'DOCUMENT_SCHEMA',
      mode: 'MERGE_INTO_CURRENT',
      target_block_id: null,
      state: 'CANCEL_REQUESTED',
      stage: 'INFERENCE',
      progress_percent: 55,
      attempt_count: 1,
      maximum_attempts: 4,
      last_failure_code: null,
      version: 2,
      created_at: '2026-07-31T01:00:00Z',
      updated_at: '2026-07-31T01:01:00Z',
      completed_at: null,
      result_proposal_id: null,
      result_evidence_hash: null,
      supersedes_job_id: null,
    }
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(job, '"2"'))
      .mockResolvedValueOnce(jsonResponse({
        ...job,
        id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3cd',
        state: 'QUEUED',
        stage: 'QUEUED',
        version: 1,
        supersedes_job_id: job.id,
      }, '"1"', 202))
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')

    await cancelKnowledgeStudioTBoxProposalJob(
      client,
      job.draft_id,
      job.id,
      'USER_REQUESTED',
      '"1"',
      'cancel-key',
    )
    await retryKnowledgeStudioTBoxProposalJob(
      client,
      job.draft_id,
      job.id,
      '"2"',
      'retry-key',
    )

    const cancelHeaders = new Headers(fetchMock.mock.calls[0]?.[1]?.headers)
    const retryHeaders = new Headers(fetchMock.mock.calls[1]?.[1]?.headers)
    expect(cancelHeaders.get('If-Match')).toBe('"1"')
    expect(cancelHeaders.get('Idempotency-Key')).toBe('cancel-key')
    const cancelBody = fetchMock.mock.calls[0]?.[1]?.body
    expect(JSON.parse(typeof cancelBody === 'string' ? cancelBody : '{}')).toEqual({
      reason: 'USER_REQUESTED',
    })
    expect(retryHeaders.get('If-Match')).toBe('"2"')
    expect(retryHeaders.get('Idempotency-Key')).toBe('retry-key')
  })

  it('uses the unified managed-domain resource', async () => {
    const managedDomain = {
      id: payload.domain_id,
      display_name: '반도체',
      source_version: payload.domain_source_version,
      asset_count: 0,
      lifecycle: 'ACTIVE',
      version: 1,
      created_at: '2026-07-30T01:00:00Z',
      updated_at: '2026-07-30T01:00:00Z',
      managed: true,
    }
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify(managedDomain), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      }))
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')

    await createKnowledgeStudioManagedDomain(client, '반도체', 'domain-create-key')

    expect(requestUrl(fetchMock.mock.calls[0]?.[0])).toContain('/knowledge/domains')
    expect(requestUrl(fetchMock.mock.calls[0]?.[0])).not.toContain('/manage')
  })

  it('lists the bounded managed-domain inventory through the admin resource', async () => {
    const managedDomain = {
      id: payload.domain_id,
      display_name: '반도체',
      source_version: payload.domain_source_version,
      asset_count: 2,
      lifecycle: 'ACTIVE',
      version: 1,
      created_at: '2026-07-30T01:00:00Z',
      updated_at: '2026-07-30T01:00:00Z',
      managed: true,
    }
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ items: [managedDomain] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')

    const items = await listKnowledgeStudioManagedDomains(client)

    expect(items).toEqual([managedDomain])
    expect(requestUrl(fetchMock.mock.calls[0]?.[0])).toContain(
      '/knowledge/domains/manage?limit=100',
    )
    expect(fetchMock.mock.calls[0]?.[1]?.method ?? 'GET').toBe('GET')
    expect(fetchMock.mock.calls[0]?.[1]?.cache).toBe('no-store')
  })

  it('searches exact published T-Box releases and creates a fenced Asset Proposal', async () => {
    const release = {
      graph_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3d0',
      graph_name: 'Enterprise glossary',
      graph_slug: 'enterprise-glossary',
      classification: 'normal',
      domain_name: 'Data Governance',
      studio_release_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3d1',
      release_no: 7,
      state: 'ACTIVE',
      contract_hash: 'a'.repeat(64),
      tbox_hash: 'b'.repeat(64),
      published_at: '2026-07-31T01:00:00Z',
      class_count: 8,
      property_count: 21,
      relationship_count: 6,
    }
    const proposal = {
      id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3d2',
      draft_id: draftResponse(3).id,
      state: 'READY',
      mode: 'MERGE_INTO_CURRENT',
      merge_strategy: 'KEEP_ORIGINAL',
      base_draft_version: 3,
      prompt: 'server-owned exact Asset release import',
      elements: [],
      conflicts: [],
      source_reference: {
        contract_version: 'KNOWLEDGE_STUDIO_ASSET_RELEASE_SOURCE_V1',
        studio_release_id: release.studio_release_id,
        tbox_hash: release.tbox_hash,
      },
      version: 1,
      created_at: '2026-07-31T01:00:00Z',
      updated_at: '2026-07-31T01:00:00Z',
    }
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        items: [release],
        page: { next_cursor: null, limit: 50 },
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify(proposal), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      }))
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')
    const draftId = String(proposal.draft_id)

    await searchKnowledgeStudioTBoxAssetReleases(client, draftId, 'glossary')
    await createKnowledgeStudioTBoxAssetReleaseProposal(
      client,
      draftId,
      {
        studio_release_id: release.studio_release_id,
        tbox_hash: release.tbox_hash,
        target_block_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3d3',
        mode: 'MERGE_INTO_CURRENT',
      },
      '"3"',
    )

    expect(requestUrl(fetchMock.mock.calls[0]?.[0])).toContain(
      '/tbox/asset-releases?q=glossary&limit=50',
    )
    expect(fetchMock.mock.calls[0]?.[1]?.cache).toBe('no-store')
    expect(requestUrl(fetchMock.mock.calls[1]?.[0])).toContain(
      '/tbox/asset-release-proposals',
    )
    const proposalHeaders = new Headers(fetchMock.mock.calls[1]?.[1]?.headers)
    expect(proposalHeaders.get('If-Match')).toBe('"3"')
    const proposalBody = fetchMock.mock.calls[1]?.[1]?.body
    expect(JSON.parse(typeof proposalBody === 'string' ? proposalBody : '{}')).toEqual({
      studio_release_id: release.studio_release_id,
      tbox_hash: release.tbox_hash,
      target_block_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3d3',
      mode: 'MERGE_INTO_CURRENT',
    })
  })

  it('continues the governed catalog search with the opaque server cursor', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValueOnce(jsonResponse({
      items: [],
      page: { next_cursor: null, limit: 50 },
    }))
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')

    await searchKnowledgeStudioTBoxCatalogSources(
      client,
      String(draftResponse(3).id),
      'wafer process',
      { cursor: 'opaque-catalog-cursor' },
    )

    const url = requestUrl(fetchMock.mock.calls[0]?.[0])
    expect(url).toContain('/tbox/catalog-sources?')
    expect(url).toContain('q=wafer+process')
    expect(url).toContain('limit=50')
    expect(url).toContain('cursor=opaque-catalog-cursor')
    expect(fetchMock.mock.calls[0]?.[1]?.cache).toBe('no-store')
  })

  it('fences dry-run preview and pre-flight reads without sending provider queries', async () => {
    const preview = {
      status: 'READY',
      draft_version: 3,
      binding_version: 1,
      target_stable_element_id: 'class.employee',
      dry_run: true,
      sample_size: 1,
      graph: { nodes: [], edges: [] },
      evidence: [],
    }
    const preflight = {
      status: 'PASS',
      valid: true,
      draft_version: 3,
      checked_at: '2026-07-28T08:00:00Z',
      receipt_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3c0',
      contract_hash: 'a'.repeat(64),
      evidence: [],
    }
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify(preview), {
        status: 200,
        headers: { 'Content-Type': 'application/json', ETag: '"3"' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify(preflight), {
        status: 200,
        headers: { 'Content-Type': 'application/json', ETag: '"3"' },
      }))
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')

    await previewKnowledgeStudioBinding(
      client,
      '019fa57b-52de-74c0-9f5e-06ae7b1bf3b0',
      'class.employee',
      '"3"',
      5,
    )
    await preflightKnowledgeStudioABox(
      client,
      '019fa57b-52de-74c0-9f5e-06ae7b1bf3b0',
      '"3"',
      'preflight-key',
    )

    const previewCall = fetchMock.mock.calls[0]
    expect(requestUrl(previewCall?.[0])).toContain('/abox/previews')
    expect(previewCall?.[1]?.method).toBe('POST')
    expect(new Headers(previewCall?.[1]?.headers).get('If-Match')).toBe('"3"')
    expect(new Headers(previewCall?.[1]?.headers).get('Idempotency-Key')).toBeNull()
    expect(JSON.parse(previewCall?.[1]?.body as string)).toEqual({
      target_stable_element_id: 'class.employee',
      sample_limit: 5,
    })
    expect(JSON.stringify(previewCall?.[1]?.body)).not.toMatch(/query|cypher|external_urn/)

    const preflightCall = fetchMock.mock.calls[1]
    expect(requestUrl(preflightCall?.[0])).toContain('/abox/preflight')
    expect(preflightCall?.[1]?.method).toBe('POST')
    expect(new Headers(preflightCall?.[1]?.headers).get('If-Match')).toBe('"3"')
    expect(new Headers(preflightCall?.[1]?.headers).get('Idempotency-Key')).toBe('preflight-key')
    expect(preflightCall?.[1]?.body).toBeUndefined()
  })

  it('pins the bounded Relation preview and confirmation to one stable T-Box identity', async () => {
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({
        status: 'READY', plan_mode: 'RELATION', relation_stable_element_id: 'relation.owns',
      }, '"1"'))
      .mockResolvedValueOnce(jsonResponse({ id: 'knowledge-ingestion:relation', state: 'SUCCESS' }))
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')

    await previewKnowledgeStudioRelation(client, 'draft-1', 'relation.owns', '"7"', 5)
    await createKnowledgeStudioRelationIngestion(
      client, 'draft-1', '"7"', 'relation-confirm-key', 'preview-1', 'relation.owns',
    )

    expect(JSON.parse(fetchMock.mock.calls[0]?.[1]?.body as string)).toEqual({
      relation_stable_element_id: 'relation.owns', sample_limit: 5,
    })
    expect(new Headers(fetchMock.mock.calls[0]?.[1]?.headers).get('If-Match')).toBe('"7"')
    expect(JSON.parse(fetchMock.mock.calls[1]?.[1]?.body as string)).toEqual({
      preview_job_id: 'preview-1', relation_stable_element_id: 'relation.owns',
    })
    expect(new Headers(fetchMock.mock.calls[1]?.[1]?.headers).get('Idempotency-Key')).toBe('relation-confirm-key')
  })

  it('uses fenced idempotent maker-checker lifecycle commands', async () => {
    const release = {
      id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3c1',
      graph_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3c2',
      ontology_version_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3c3',
      release_no: 1,
      state: 'ACTIVE',
      contract_version: 'KNOWLEDGE_STUDIO_RELEASE_V1',
      contract_hash: 'a'.repeat(64),
      tbox_hash: 'b'.repeat(64),
      abox_hash: 'c'.repeat(64),
      reviewed_by: '019fa57b-52de-74c0-9f5e-06ae7b1bf3c4',
      published_by: '019fa57b-52de-74c0-9f5e-06ae7b1bf3c4',
      published_at: '2026-07-28T09:00:00Z',
    }
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        ...draftResponse(4), state: 'REVIEW', current_step: 'ABOX',
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json', ETag: '"4"' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        draft: {
          ...draftResponse(5), state: 'PUBLISHED', current_step: 'ABOX',
        },
        release,
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json', ETag: '"5"' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        ...draftResponse(6), state: 'DISCARDED', current_step: 'ABOX',
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json', ETag: '"6"' },
      }))
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')
    const draftId = '019fa57b-52de-74c0-9f5e-06ae7b1bf3b0'

    await submitKnowledgeStudioReview(client, draftId, '"3"', 'review-key')
    await publishKnowledgeStudioDraft(
      client,
      draftId,
      'Schema와 source access evidence를 검토함',
      '"4"',
      'publish-key',
    )
    await discardKnowledgeStudioDraft(client, draftId, '"5"', 'discard-key')

    const [reviewCall, publishCall, discardCall] = fetchMock.mock.calls
    expect(requestUrl(reviewCall?.[0])).toContain('/submit-review')
    expect(new Headers(reviewCall?.[1]?.headers).get('Idempotency-Key')).toBe('review-key')
    expect(requestUrl(publishCall?.[0])).toContain('/publish')
    expect(new Headers(publishCall?.[1]?.headers).get('If-Match')).toBe('"4"')
    expect(new Headers(publishCall?.[1]?.headers).get('Idempotency-Key')).toBe('publish-key')
    expect(JSON.parse(publishCall?.[1]?.body as string)).toEqual({
      review_reason: 'Schema와 source access evidence를 검토함',
    })
    expect(requestUrl(discardCall?.[0])).toContain('/discard')
    expect(new Headers(discardCall?.[1]?.headers).get('Idempotency-Key')).toBe('discard-key')
  })

  it('uses the job version fence and idempotency key for ingestion cancel and retry', async () => {
    const job = {
      id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3d0',
      draft_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3b0',
      graph_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3d1',
      studio_release_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3d2',
      requested_by: '019fa57b-52de-74c0-9f5e-06ae7b1bf3b3',
      state: 'CANCELLED',
      progress_percent: 0,
      current_stage: 'COMPLETED',
      vector_target_count: 0,
      attempt_count: 1,
      maximum_attempts: 3,
      result_changeset_id: null,
      result_evidence_hash: null,
      error_code: null,
      allowed_actions: ['RETRY'],
      version: 4,
      created_at: '2026-07-31T01:00:00Z',
      updated_at: '2026-07-31T01:01:00Z',
      started_at: '2026-07-31T01:00:05Z',
      finished_at: '2026-07-31T01:01:00Z',
    }
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify(job), {
        status: 200,
        headers: { 'Content-Type': 'application/json', ETag: '"4"' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        ...job,
        state: 'PENDING',
        current_stage: 'QUEUED',
        allowed_actions: ['CANCEL'],
        version: 5,
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json', ETag: '"5"' },
      }))
    vi.stubGlobal('fetch', fetchMock)
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')

    await cancelKnowledgeStudioIngestion(
      client,
      job.draft_id,
      job.id,
      3,
      '  운영자가 원천 변경을 확인함  ',
      'cancel-key',
    )
    await retryKnowledgeStudioIngestion(
      client,
      job.draft_id,
      job.id,
      4,
      'retry-key',
    )

    const [cancelCall, retryCall] = fetchMock.mock.calls
    expect(requestUrl(cancelCall?.[0])).toContain(`/abox/ingestions/${job.id}/cancel`)
    expect(new Headers(cancelCall?.[1]?.headers).get('If-Match')).toBe('"3"')
    expect(new Headers(cancelCall?.[1]?.headers).get('Idempotency-Key')).toBe('cancel-key')
    expect(JSON.parse(cancelCall?.[1]?.body as string)).toEqual({
      reason: '운영자가 원천 변경을 확인함',
    })
    expect(requestUrl(retryCall?.[0])).toContain(`/abox/ingestions/${job.id}/retry`)
    expect(new Headers(retryCall?.[1]?.headers).get('If-Match')).toBe('"4"')
    expect(new Headers(retryCall?.[1]?.headers).get('Idempotency-Key')).toBe('retry-key')
    expect(retryCall?.[1]?.body).toBeUndefined()
  })
})
