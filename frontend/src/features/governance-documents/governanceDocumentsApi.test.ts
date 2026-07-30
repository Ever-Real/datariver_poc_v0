import { describe, expect, it, vi } from 'vitest'
import type { ApiClient, RequestOptions } from '../../api/client'
import { GovernanceDocumentsApi } from './governanceDocumentsApi'

describe('GovernanceDocumentsApi', () => {
  it('requires an ETag and matching permission cache scope for document detail', async () => {
    const requestWithMeta = vi.fn().mockResolvedValue({
      data: {
        item: { document: { document_id: 'document-one', version: 1 } },
        cache_scope: cacheScope,
        observed_at: now,
        authorization_valid_until: validUntil,
      },
    })
    const api = new GovernanceDocumentsApi({
      request: vi.fn(),
      requestWithMeta,
    })

    await expect(api.document('document-one', cacheScope)).rejects.toThrow('변경 버전')
  })

  it('sends review and archive commands with aggregate If-Match and idempotency', async () => {
    const calls: Array<[string, RequestOptions]> = []
    const requestWithMeta = vi.fn((path: string, options: RequestOptions = {}) => {
      calls.push([path, options])
      return Promise.resolve({ data: command(), etag: '"4"' })
    })
    const api = new GovernanceDocumentsApi({
      request: vi.fn(),
      requestWithMeta: requestWithMeta as unknown as ApiClient['requestWithMeta'],
    })

    await api.reviewVersion(
      'document-one',
      'version-one',
      3,
      { decision: 'APPROVE', reason: '독립 검토 완료' },
      'governance-review-key',
    )
    await api.archiveDocument(
      'document-one',
      4,
      '보존 이력은 유지하고 목록에서 종료',
      'governance-archive-key',
    )

    expect(calls[0]).toEqual([
      '/governance/documents/document-one/versions/version-one/reviews',
      expect.objectContaining({
        method: 'POST',
        ifMatch: '"3"',
        idempotencyKey: 'governance-review-key',
        body: JSON.stringify({ decision: 'APPROVE', reason: '독립 검토 완료' }),
      }),
    ])
    expect(calls[1]).toEqual([
      '/governance/documents/document-one/archive',
      expect.objectContaining({
        method: 'POST',
        ifMatch: '"4"',
        idempotencyKey: 'governance-archive-key',
        body: JSON.stringify({ reason: '보존 이력은 유지하고 목록에서 종료' }),
      }),
    ])
  })

  it('keeps HTML, Markdown and Word imports on the version multipart command', async () => {
    const calls: Array<[string, RequestOptions]> = []
    const requestWithMeta = vi.fn((path: string, options: RequestOptions = {}) => {
      calls.push([path, options])
      return Promise.resolve({ data: command(), etag: '"2"' })
    })
    const api = new GovernanceDocumentsApi({
      request: vi.fn(),
      requestWithMeta: requestWithMeta as unknown as ApiClient['requestWithMeta'],
    })
    const file = new File(['# 정책'], 'policy.md', { type: 'text/markdown' })

    await api.importVersion(
      'document-one',
      1,
      file,
      '개인정보 처리 정책',
      '전사 개인정보 처리',
      'governance-import-key',
    )

    const call = calls[0]
    expect(call?.[0]).toBe('/governance/documents/document-one/versions')
    expect(call?.[1]).toEqual(expect.objectContaining({
      method: 'POST',
      ifMatch: '"1"',
      idempotencyKey: 'governance-import-key',
    }))
    expect(call?.[1].body).toBeInstanceOf(FormData)
    const body = call?.[1].body
    expect(body instanceof FormData ? body.get('file') : undefined).toBe(file)
    expect(body instanceof FormData ? body.get('title') : undefined).toBe('개인정보 처리 정책')
    expect(body instanceof FormData ? body.get('applicability_scope') : undefined).toBe('전사 개인정보 처리')
  })

  it('does not invent If-Match for aggregate creation and requires response ETag', async () => {
    const calls: Array<[string, RequestOptions]> = []
    const requestWithMeta = vi.fn((path: string, options: RequestOptions = {}) => {
      calls.push([path, options])
      return Promise.resolve({ data: command(), etag: '"1"' })
    })
    const api = new GovernanceDocumentsApi({
      request: vi.fn(),
      requestWithMeta: requestWithMeta as unknown as ApiClient['requestWithMeta'],
    })

    await api.createDocument({
      kind: 'DOCUMENT',
      category: 'POLICY',
      title: '개인정보 처리 정책',
      summary: '',
      classification: 1,
      applicability_scope: '전사',
      sanitized_html: '<p>정책</p>',
      source_template_version_id: null,
    }, 'governance-create-key')

    expect(calls[0]?.[0]).toBe('/governance/documents')
    expect(calls[0]?.[1].idempotencyKey).toBe('governance-create-key')
    expect(calls[0]?.[1].ifMatch).toBeUndefined()
  })

  it('loads the controlled policy, terminology and security template blueprints', async () => {
    const request = vi.fn().mockResolvedValue({
      contract_version: 'GOVERNANCE_DOCUMENT_BLUEPRINTS_V1',
      items: [
        blueprint('policy-v1', 'POLICY'),
        blueprint('standard-terminology-v1', 'STANDARD_TERMINOLOGY'),
        blueprint('security-guide-v1', 'SECURITY_GUIDE'),
      ],
    })
    const api = new GovernanceDocumentsApi({
      request,
      requestWithMeta: vi.fn(),
    })

    const value = await api.templateBlueprints()

    expect(value.items).toHaveLength(3)
    expect(request).toHaveBeenCalledWith(
      '/governance/documents/template-blueprints',
      expect.objectContaining({ cache: 'no-store' }),
    )
  })
})

function command() {
  return {
    item: {
      document: {
        document_id: 'document-one',
        version: 4,
      },
      versions: [],
      reviews: [],
      attachments: [],
    },
  }
}

const now = '2026-07-31T00:00:00Z'
const validUntil = '2026-07-31T00:00:30Z'
const cacheScope = 'a'.repeat(64)

function blueprint(
  blueprintId: string,
  category: 'POLICY' | 'STANDARD_TERMINOLOGY' | 'SECURITY_GUIDE',
) {
  return {
    blueprint_id: blueprintId,
    blueprint_version: 'GOVERNANCE_DOCUMENT_BLUEPRINTS_V1',
    category,
    title: blueprintId,
    summary: '통제된 기본 양식',
    applicability_scope: '전사',
    sanitized_html: '<h1>양식</h1>',
    content_sha256: 'b'.repeat(64),
    sanitizer_policy_version: 'GOVERNANCE_HTML_SANITIZER_V1',
    sanitizer_policy_sha256: 'c'.repeat(64),
  }
}
