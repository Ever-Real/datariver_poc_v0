import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiClient } from '../../api/client'
import { KnowledgeInformationManagementPage } from './KnowledgeInformationManagementPage'
import type { KnowledgePropertyProfile } from './studio/knowledgeStudioApi'

const elementId = '019fa57b-52de-74c0-9f5e-06ae7b1bf3b7'
const profileId = '019fa57b-52de-74c0-9f5e-06ae7b1bf3b8'

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input
  return input instanceof URL ? input.href : input.url
}

function item(profile: KnowledgePropertyProfile | null) {
  return {
    graph_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3b4',
    graph_name: '고객 지식 그래프',
    studio_release_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3b5',
    release_no: 3,
    ontology_version_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3b6',
    ontology_element_id: elementId,
    stable_property_id: 'property.customer.name',
    property_name: '고객명',
    owner_class_id: 'class.customer',
    data_type: 'STRING',
    property_urn: `urn:uuid:${elementId}`,
    profile,
  }
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('KnowledgeInformationManagementPage', () => {
  it('consolidates real Property profile create, update and archive operations', async () => {
    let profile: KnowledgePropertyProfile | null = null
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const path = requestUrl(input)
      const method = init?.method ?? 'GET'
      if (path.includes('/knowledge/domains?')) {
        return Promise.resolve(json({ items: [] }))
      }
      if (path.includes('/knowledge/property-profiles?') && method === 'GET') {
        return Promise.resolve(json({ items: [item(profile)] }))
      }
      if (path.endsWith('/knowledge/property-profiles') && method === 'POST') {
        profile = {
          id: profileId,
          description: '고객의 정식 명칭',
          unit: '명',
          synonyms: ['고객명', 'Customer name'],
          lifecycle: 'ACTIVE',
          created_by: '019fa57b-52de-74c0-9f5e-06ae7b1bf3b2',
          updated_by: '019fa57b-52de-74c0-9f5e-06ae7b1bf3b2',
          archived_by: null,
          created_at: '2026-07-31T01:02:03Z',
          updated_at: '2026-07-31T01:02:03Z',
          archived_at: null,
          version: 1,
        }
        return Promise.resolve(json(profile, 201))
      }
      if (path.endsWith(`/knowledge/property-profiles/${profileId}`) && method === 'PATCH') {
        profile = { ...profile!, unit: '고객', version: 2 }
        return Promise.resolve(json(profile))
      }
      if (path.endsWith(`/knowledge/property-profiles/${profileId}`) && method === 'DELETE') {
        const archived = {
          ...profile!,
          lifecycle: 'ARCHIVED',
          archived_by: '019fa57b-52de-74c0-9f5e-06ae7b1bf3b2',
          archived_at: '2026-07-31T02:00:00Z',
          version: 3,
        } satisfies KnowledgePropertyProfile
        profile = null
        return Promise.resolve(json(archived))
      }
      return Promise.reject(new Error(`Unexpected request: ${method} ${path}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    render(
      <KnowledgeInformationManagementPage
        client={new ApiClient('/api/v1', () => 'token', () => 'workspace')}
      />,
    )

    fireEvent.click(await screen.findByRole('tab', { name: 'Property 프로파일' }))
    const profileTable = await screen.findByRole('table', {
      name: 'Knowledge Property 프로파일',
    })
    fireEvent.click(await screen.findByRole('button', { name: '고객명 프로파일 생성' }))
    const createEditor = screen.getByRole('dialog', { name: '고객명 Property 프로파일' })
    fireEvent.change(within(createEditor).getByLabelText('단위'), { target: { value: '명' } })
    fireEvent.change(within(createEditor).getByLabelText(/동의어/), {
      target: { value: '고객명, Customer name, 고객명' },
    })
    fireEvent.change(within(createEditor).getByLabelText('상세 설명'), {
      target: { value: '고객의 정식 명칭' },
    })
    fireEvent.click(within(createEditor).getByRole('button', { name: '프로파일 생성' }))

    await screen.findByRole('button', { name: '고객명 프로파일 수정' })
    const createCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')
    const createBody = createCall?.[1]?.body
    expect(typeof createBody).toBe('string')
    if (typeof createBody !== 'string') throw new Error('Expected a JSON request body.')
    expect(JSON.parse(createBody)).toEqual({
      ontology_element_id: elementId,
      description: '고객의 정식 명칭',
      unit: '명',
      synonyms: ['고객명', 'Customer name'],
    })

    fireEvent.click(screen.getByRole('button', { name: '고객명 프로파일 수정' }))
    const updateEditor = screen.getByRole('dialog', { name: '고객명 Property 프로파일' })
    fireEvent.change(within(updateEditor).getByLabelText('단위'), {
      target: { value: '고객' },
    })
    fireEvent.click(within(updateEditor).getByRole('button', { name: '변경 저장' }))

    await waitFor(() => {
      const updateCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH')
      expect(new Headers(updateCall?.[1]?.headers).get('If-Match')).toBe('"1"')
    })
    await waitFor(() => expect(within(profileTable).getByText('고객')).toBeInTheDocument())
    fireEvent.click(await screen.findByRole('button', { name: '고객명 프로파일 비활성화' }))

    await waitFor(() => {
      const archiveCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'DELETE')
      expect(new Headers(archiveCall?.[1]?.headers).get('If-Match')).toBe('"2"')
    })
    expect(await screen.findByRole('button', { name: '고객명 프로파일 생성' })).toBeEnabled()
  })

  it('reuses the same idempotency key after a committed response is lost', async () => {
    let committed = false
    const createKeys: string[] = []
    const createdProfile: KnowledgePropertyProfile = {
      id: profileId,
      description: '고객 식별값',
      unit: null,
      synonyms: [],
      lifecycle: 'ACTIVE',
      created_by: '019fa57b-52de-74c0-9f5e-06ae7b1bf3b2',
      updated_by: '019fa57b-52de-74c0-9f5e-06ae7b1bf3b2',
      archived_by: null,
      created_at: '2026-07-31T01:02:03Z',
      updated_at: '2026-07-31T01:02:03Z',
      archived_at: null,
      version: 1,
    }
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const path = requestUrl(input)
      const method = init?.method ?? 'GET'
      if (path.includes('/knowledge/domains?')) {
        return Promise.resolve(json({ items: [] }))
      }
      if (path.includes('/knowledge/property-profiles?') && method === 'GET') {
        return Promise.resolve(json({ items: [item(committed ? createdProfile : null)] }))
      }
      if (path.endsWith('/knowledge/property-profiles') && method === 'POST') {
        createKeys.push(new Headers(init?.headers).get('Idempotency-Key') ?? '')
        if (!committed) {
          committed = true
          return Promise.reject(new Error('응답 연결이 끊어졌습니다.'))
        }
        return Promise.resolve(json(createdProfile, 201))
      }
      return Promise.reject(new Error(`Unexpected request: ${method} ${path}`))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(
      <KnowledgeInformationManagementPage
        client={new ApiClient('/api/v1', () => 'token', () => 'workspace')}
      />,
    )

    fireEvent.click(await screen.findByRole('tab', { name: 'Property 프로파일' }))
    fireEvent.click(await screen.findByRole('button', { name: '고객명 프로파일 생성' }))
    const editor = screen.getByRole('dialog', { name: '고객명 Property 프로파일' })
    fireEvent.change(within(editor).getByLabelText('상세 설명'), {
      target: { value: '고객 식별값' },
    })
    fireEvent.click(within(editor).getByRole('button', { name: '프로파일 생성' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('응답 연결이 끊어졌습니다.')

    fireEvent.click(within(editor).getByRole('button', { name: '프로파일 생성' }))

    await waitFor(() => expect(createKeys).toHaveLength(2))
    expect(createKeys[0]).not.toBe('')
    expect(createKeys[1]).toBe(createKeys[0])
    expect(await screen.findByRole('button', { name: '고객명 프로파일 수정' })).toBeEnabled()
  })
})
