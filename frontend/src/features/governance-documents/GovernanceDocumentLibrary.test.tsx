import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient, RequestOptions } from '../../api/client'
import { GovernanceDocumentLibrary } from './GovernanceDocumentLibrary'

describe('GovernanceDocumentLibrary capability boundary', () => {
  it('does not request a document list when read capability is denied', async () => {
    const request = vi.fn((
      path: string,
      options?: RequestOptions,
    ): Promise<unknown> => {
      void path
      void options
      return Promise.resolve(capability('DENIED'))
    })
    renderLibrary(request)

    expect(await screen.findByText('문서 열람이 허용되지 않았습니다')).toBeInTheDocument()
    expect(request).toHaveBeenCalledTimes(1)
    const firstCall = request.mock.calls[0]
    expect(firstCall?.[0]).toBe('/governance/documents/capability')
    expect(firstCall?.[1]?.cache).toBe('no-store')
    expect(firstCall?.[1]?.signal).toBeInstanceOf(AbortSignal)
  })

  it('renders only the permission-pruned server summary list after capability succeeds', async () => {
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      void options
      if (path === '/governance/documents/capability') {
        return Promise.resolve(capability('AVAILABLE'))
      }
      if (path === '/governance/documents?limit=25&kind=DOCUMENT') {
        return Promise.resolve({
          items: [{
            document_id: 'document-one',
            workspace_id: 'workspace-one',
            kind: 'DOCUMENT',
            category: 'POLICY',
            title: '개인정보 처리 정책',
            summary: '개인정보 처리 기준',
            classification: 1,
            state: 'ACTIVE',
            owner_subject_id: 'subject-one',
            current_published_version_id: 'version-one',
            current_version_number: 3,
            created_at: now,
            updated_at: now,
            version: 3,
            allowed_actions: ['read'],
          }],
          page: { next_cursor: null, limit: 25 },
          cache_scope: cacheScope,
          observed_at: now,
          authorization_valid_until: validUntil,
        })
      }
      throw new Error(`unexpected request: ${path}`)
    })
    renderLibrary(request)

    expect(await screen.findByRole('cell', { name: '개인정보 처리 정책' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: 'v3' })).toBeInTheDocument()
    const requestedPaths = request.mock.calls.map((call) => String(call[0]))
    expect(requestedPaths.some((path) => path.includes('/versions'))).toBe(false)
    expect(requestedPaths.some((path) => path.includes('/content'))).toBe(false)
  })

  it('exposes document authoring and Template selection for an entitled steward', async () => {
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/governance/documents/capability') {
        const value = capability('AVAILABLE')
        value.axes = value.axes.map((axis) => ({
          ...axis,
          state: ['read', 'create', 'edit', 'template_manage'].includes(axis.id)
            ? 'AVAILABLE'
            : 'DENIED',
        }))
        return Promise.resolve(value)
      }
      if (path === '/governance/documents?limit=25&kind=DOCUMENT') {
        return Promise.resolve({
          items: [],
          page: { next_cursor: null, limit: 25 },
          cache_scope: cacheScope,
          observed_at: now,
          authorization_valid_until: validUntil,
        })
      }
      if (path === '/governance/documents?limit=25&kind=TEMPLATE') {
        return Promise.resolve({
          items: [],
          page: { next_cursor: null, limit: 25 },
          cache_scope: cacheScope,
          observed_at: now,
          authorization_valid_until: validUntil,
        })
      }
      throw new Error(`unexpected request: ${path}`)
    })
    renderLibrary(request)

    const create = await screen.findByRole('button', { name: '문서 작성' })
    const selectTemplate = screen.getByRole('button', { name: '템플릿 선택' })
    expect(screen.getByRole('button', { name: '템플릿 작성' })).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: '문서 관리 capability' })).not.toBeInTheDocument()
    fireEvent.click(selectTemplate)
    expect(screen.getByRole('combobox', { name: '대상' })).toHaveValue('TEMPLATE')
    fireEvent.click(create)
    expect(
      await screen.findByRole('combobox', { name: '게시 템플릿 선택' }),
    ).toBeInTheDocument()
    const editor = await screen.findByRole('textbox', { name: '문서 본문' })
    const sidebar = screen.getByLabelText('문서 속성과 가져오기 설정')
    expect(editor.compareDocumentPosition(sidebar) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBe(Node.DOCUMENT_POSITION_FOLLOWING)
    expect(editor.closest('.governance-editor-content')).toBeInTheDocument()
  })

  it('keeps the editor open for Esc/backdrop and confirms only the explicit Cancel action', async () => {
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/governance/documents/capability') {
        const value = capability('AVAILABLE')
        value.axes = value.axes.map((axis) => ({
          ...axis,
          state: 'AVAILABLE',
        }))
        return Promise.resolve(value)
      }
      if (path.startsWith('/governance/documents')) {
        return Promise.resolve({
          items: [],
          page: { next_cursor: null, limit: 25 },
          cache_scope: cacheScope,
          observed_at: now,
          authorization_valid_until: validUntil,
        })
      }
      return Promise.resolve({})
    })
    renderLibrary(request)

    const create = await screen.findByRole('button', { name: '문서 작성' })
    fireEvent.click(create)
    const editor = await screen.findByRole('textbox', { name: '문서 본문' })

    fireEvent.focus(editor)
    const blockStyle = await screen.findByRole('combobox', { name: '문단 스타일' })
    fireEvent.change(blockStyle, { target: { value: 'heading-2' } })

    const dialog = screen.getByRole('dialog', { name: '문서 작성' })
    const cancel = screen.getByRole('button', { name: '취소' })
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)

    fireEvent.keyDown(dialog, { key: 'Escape' })
    fireEvent.click(dialog)
    expect(confirmSpy).not.toHaveBeenCalled()
    expect(screen.getByRole('dialog', { name: '문서 작성' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '문서 작성 닫기' })).not.toBeInTheDocument()

    fireEvent.click(cancel)
    expect(confirmSpy).toHaveBeenCalledWith('저장하지 않은 변경 사항이 있습니다. 취소하시겠습니까?')
    expect(screen.getByRole('dialog', { name: '문서 작성' })).toBeInTheDocument()

    confirmSpy.mockReturnValue(true)
    fireEvent.click(cancel)
    expect(screen.queryByRole('dialog', { name: '문서 작성' })).not.toBeInTheDocument()

    confirmSpy.mockRestore()
  })
})

function renderLibrary(
  request: (path: string, options?: RequestOptions) => Promise<unknown>,
) {
  const client = {
    request: request as unknown as ApiClient['request'],
    requestWithMeta: vi.fn(),
  } as unknown as ApiClient
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <GovernanceDocumentLibrary client={client} />
    </QueryClientProvider>,
  )
}

function capability(readState: 'AVAILABLE' | 'DENIED') {
  return {
    contract_version: 'GOVERNANCE_DOCUMENT_CAPABILITY_V1',
    observed_at: now,
    valid_until: validUntil,
    cache_scope: cacheScope,
    axes: [
      'read',
      'create',
      'edit',
      'review',
      'publish',
      'archive',
      'template_manage',
      'artifact_storage',
      'knowledge_projection',
    ].map((id) => ({
      id,
      state: id === 'read' ? readState : 'DENIED',
      reason_code: id === 'read' && readState === 'DENIED' ? 'PERMISSION_DENIED' : null,
    })),
    limits: {
      max_html_bytes: 1_000_000,
      max_attachment_bytes: 10_000_000,
      max_attachments_per_version: 25,
    },
  }
}

const now = new Date(Date.now() - 1_000).toISOString()
const validUntil = new Date(Date.now() + 30_000).toISOString()
const cacheScope = 'a'.repeat(64)
