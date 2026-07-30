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
  asset_count: 0,
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
})
