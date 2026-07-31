import { Profiler } from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiClient } from '../../../../api/client'
import type { KnowledgeStudioDomainOption } from '../knowledgeStudioApi'
import { DomainManagementDialog } from './DomainManagementDialog'

const domains: KnowledgeStudioDomainOption[] = [{
  id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3af',
  display_name: '반도체',
  source_version: 'domain-v3',
  managed: true,
  version: 3,
  created_by: '00000000-0000-4000-8000-000000000101',
  creator_display_name: 'DataRiver Administrator',
  creator_email: 'admin@datariver.local',
  asset_count: 4,
  lifecycle: 'ACTIVE',
  created_at: '2026-07-30T00:00:00Z',
  updated_at: '2026-07-30T00:00:00Z',
}]

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('DomainManagementDialog', () => {
  it('keeps the hidden TanStack table data reference stable without a render loop', async () => {
    let commits = 0
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')

    render(
      <Profiler id="domain-management" onRender={() => { commits += 1 }}>
        <DomainManagementDialog
          client={client}
          open={false}
          items={domains}
          loading={false}
          onRequestClose={vi.fn()}
          onChanged={vi.fn(() => Promise.resolve())}
        />
      </Profiler>,
    )

    await Promise.resolve()
    await Promise.resolve()

    expect(commits).toBe(1)
  })

  it('shows the canonical creator identity and sends fenced rename/archive operations', async () => {
    const updated = {
      ...domains[0]!,
      display_name: '반도체 신설',
      version: 4,
    }
    const fetchMock = vi.fn<typeof fetch>((_input, init) => {
      if (init?.method === 'PATCH') {
        return Promise.resolve(new Response(JSON.stringify(updated), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }))
      }
      if (init?.method === 'DELETE') {
        return Promise.resolve(new Response(null, { status: 204 }))
      }
      return Promise.reject(new Error('Unexpected domain request.'))
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const onChanged = vi.fn(() => Promise.resolve())

    render(
      <DomainManagementDialog
        client={new ApiClient('/api/v1', () => 'token', () => 'workspace')}
        open
        items={domains}
        loading={false}
        onRequestClose={vi.fn()}
        onChanged={onChanged}
      />,
    )

    expect(screen.getByText('DataRiver Administrator')).toBeInTheDocument()
    expect(screen.getByText('admin@datariver.local')).toBeInTheDocument()
    expect(screen.queryByText(domains[0]!.created_by!)).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '반도체 도메인 수정' }))
    fireEvent.change(screen.getByRole('textbox', { name: '반도체 도메인명 수정' }), {
      target: { value: '반도체 신설' },
    })
    fireEvent.click(screen.getByRole('button', { name: '반도체 도메인 수정 저장' }))
    await waitFor(() => expect(onChanged).toHaveBeenCalledWith(updated))

    fireEvent.click(screen.getByRole('button', { name: '반도체 도메인 삭제' }))
    await waitFor(() => expect(onChanged).toHaveBeenCalledWith(undefined, domains[0]!.id))

    const patchHeaders = new Headers(fetchMock.mock.calls[0]?.[1]?.headers)
    const deleteHeaders = new Headers(fetchMock.mock.calls[1]?.[1]?.headers)
    expect(fetchMock.mock.calls[0]?.[1]?.method).toBe('PATCH')
    expect(patchHeaders.get('If-Match')).toBe('"3"')
    expect(patchHeaders.get('Idempotency-Key')).toBeTruthy()
    expect(fetchMock.mock.calls[1]?.[1]?.method).toBe('DELETE')
    expect(deleteHeaders.get('If-Match')).toBe('"3"')
    expect(deleteHeaders.get('Idempotency-Key')).toBeTruthy()
  })

  it('offers explicit password reauthentication for an administrator assurance denial', async () => {
    const fetchMock = vi.fn<typeof fetch>(() => Promise.resolve(new Response(JSON.stringify({
      type: 'urn:datariver:problem:forbidden',
      title: 'Forbidden',
      status: 403,
      detail: 'The requested action is not permitted.',
      code: 'forbidden',
      request_id: 'domain-admin-reauth',
      remediation: { kind: 'REAUTH_REQUIRED' },
    }), {
      status: 403,
      headers: { 'Content-Type': 'application/problem+json' },
    })))
    vi.stubGlobal('fetch', fetchMock)
    const onPasswordReauth = vi.fn(() => Promise.resolve())

    render(
      <DomainManagementDialog
        client={new ApiClient('/api/v1', () => 'token', () => 'workspace')}
        open
        items={domains}
        loading={false}
        onRequestClose={vi.fn()}
        onChanged={vi.fn(() => Promise.resolve())}
        onStepUp={vi.fn(() => Promise.resolve())}
        onPasswordReauth={onPasswordReauth}
        onEnroll={vi.fn(() => Promise.resolve())}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: '반도체 도메인 수정' }))
    fireEvent.change(screen.getByRole('textbox', { name: '반도체 도메인명 수정' }), {
      target: { value: '반도체 재인증' },
    })
    fireEvent.click(screen.getByRole('button', { name: '반도체 도메인 수정 저장' }))

    fireEvent.click(await screen.findByRole('button', { name: '비밀번호로 재인증' }))
    expect(onPasswordReauth).toHaveBeenCalledOnce()
    expect(fetchMock).toHaveBeenCalledOnce()
  })

  it('drills into the server-filtered KG_READ asset page and preserves the domain cursor', async () => {
    const asset = {
      id: '019fa57b-52de-74c0-9f5e-06ae7b1c1001',
      slug: 'semiconductor-knowledge',
      name: '반도체 지식그래프',
      graph_type: 'DOMAIN',
      status: 'PUBLISHED',
      classification: 'INTERNAL',
      domain_id: domains[0]!.id,
      domain_name: domains[0]!.display_name,
      creator_name: 'DataRiver Administrator',
      creator_email: 'admin@datariver.local',
      editor_name: 'DataRiver Administrator',
      editor_email: 'admin@datariver.local',
      active_studio_release_id: '019fa57b-52de-74c0-9f5e-06ae7b1c1002',
      active_studio_release_no: 2,
      active_release_id: '019fa57b-52de-74c0-9f5e-06ae7b1c1003',
      active_release_no: 3,
      class_count: 2,
      property_count: 3,
      relationship_count: 1,
      binding_count: 2,
      source_count: 1,
      node_count: 5,
      edge_count: 4,
      projection_state: 'SHADOW_VERIFIED',
      created_at: '2026-07-30T00:00:00Z',
      updated_at: '2026-07-31T00:00:00Z',
      version: 1,
      delivery_policy: null,
    }
    let requestCount = 0
    const fetchMock = vi.fn<typeof fetch>(() => {
      requestCount += 1
      const page = requestCount === 1
        ? { items: [asset], next_cursor: 'domain-page-2', limit: 25 }
        : { items: [], next_cursor: null, limit: 25 }
      return Promise.resolve(new Response(JSON.stringify(page), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(
      <DomainManagementDialog
        client={new ApiClient('/api/v1', () => 'token', () => 'workspace')}
        open
        items={domains}
        loading={false}
        onRequestClose={vi.fn()}
        onChanged={vi.fn(() => Promise.resolve())}
      />,
    )

    expect(fetchMock).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', {
      name: '반도체 도메인의 조회 가능 Asset 보기',
    }))

    expect(await screen.findByText('반도체 지식그래프')).toBeInTheDocument()
    expect(screen.getByText('T-Box v2 / A-Box v3')).toBeInTheDocument()
    expect(screen.getByText(/관리 정본의 소속 Asset 수와 별개로/)).toBeInTheDocument()
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      `/api/v1/knowledge/registry/assets?domain_id=${domains[0]!.id}&limit=25&sort=NAME_ASC`,
    )

    fireEvent.click(screen.getByRole('button', { name: '다음' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(fetchMock.mock.calls[1]?.[0]).toBe(
      `/api/v1/knowledge/registry/assets?domain_id=${domains[0]!.id}&limit=25&sort=NAME_ASC&cursor=domain-page-2`,
    )
    expect(await screen.findByText('현재 조회 권한 범위에 표시할 활성 Asset이 없습니다.'))
      .toBeInTheDocument()
  })

  it('fails closed without a global registry fallback or fabricated rows', async () => {
    const fetchMock = vi.fn<typeof fetch>(() => Promise.resolve(new Response(JSON.stringify({
      type: 'urn:datariver:problem:forbidden',
      title: 'Forbidden',
      status: 403,
      detail: 'The requested action is not permitted.',
      code: 'forbidden',
      request_id: 'domain-assets-forbidden',
    }), {
      status: 403,
      headers: { 'Content-Type': 'application/problem+json' },
    })))
    vi.stubGlobal('fetch', fetchMock)

    render(
      <DomainManagementDialog
        client={new ApiClient('/api/v1', () => 'token', () => 'workspace')}
        open
        items={domains}
        loading={false}
        onRequestClose={vi.fn()}
        onChanged={vi.fn(() => Promise.resolve())}
      />,
    )

    fireEvent.click(screen.getByRole('button', {
      name: '반도체 도메인의 조회 가능 Asset 보기',
    }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      '도메인 Asset 조회를 사용할 수 없습니다.',
    )
    expect(fetchMock).toHaveBeenCalledOnce()
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      `/api/v1/knowledge/registry/assets?domain_id=${domains[0]!.id}&limit=25&sort=NAME_ASC`,
    )
    expect(screen.queryByRole('row', { name: /가짜|fake/i })).not.toBeInTheDocument()
  })
})
