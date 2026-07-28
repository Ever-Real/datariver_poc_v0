import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiClient } from '../../../api/client'
import {
  advanceKnowledgeStudioDraft,
  autosaveKnowledgeStudioDraft,
  createKnowledgeStudioDraft,
  createKnowledgeStudioEditDraft,
  discardKnowledgeStudioDraft,
  listKnowledgeStudioDomains,
  preflightKnowledgeStudioABox,
  previewKnowledgeStudioBinding,
  publishKnowledgeStudioDraft,
  submitKnowledgeStudioReview,
  type KnowledgeStudioBasicInformation,
} from './knowledgeStudioApi'

function requestUrl(input: RequestInfo | URL | undefined): string {
  if (!input) return ''
  if (typeof input === 'string') return input
  return input instanceof URL ? input.toString() : input.url
}

const payload: KnowledgeStudioBasicInformation = {
  name: '반도체 소재 그래프',
  endpoint_alias: 'semiconductor_materials',
  domain_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3af',
  domain_source_version: 'domain-v3',
  classification: 'INTERNAL',
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

    await listKnowledgeStudioDomains(client, 'INTERNAL')
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
      '/knowledge/domains?classification=INTERNAL&limit=100',
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
})
