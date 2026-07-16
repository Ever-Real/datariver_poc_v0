import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient, RequestOptions } from '../../api/client'
import type { ChangeRequestRecord, UploadRecord } from '../../api/types'
import { RegistrationPage } from './RegistrationPage'

const emptyTree = {
  items: [],
  page: { limit: 100 },
  meta: {
    policy_version: 'test',
    source_watermark: 1,
    observed_at: '2026-01-01T00:00:00Z',
  },
}

function clientWith(
  request: (path: string, options?: RequestOptions) => Promise<unknown>,
): ApiClient {
  return { request: vi.fn(request) } as unknown as ApiClient
}

function uploadRecord(
  state = 'ACCEPTED',
  displayName = 'catalog.csv',
): UploadRecord {
  return {
    id: 'upload-1',
    display_name: displayName,
    state,
    size_bytes: 128,
    content_type: 'text/csv',
    sha256: 'a'.repeat(64),
    classification: 'INTERNAL',
    expires_at: '2026-01-02T00:00:00Z',
    version: 3,
    recommended_part_size_bytes: 5_242_880,
    validation_summary: { rows: 2 },
    last_error_code: null,
  }
}

describe('Registration workbench', () => {
  it('opens in a read-only manual catalog workbench', async () => {
    const request = vi.fn((path: string, options?: RequestOptions) => {
      void path
      void options
      return Promise.resolve(emptyTree)
    })

    render(<RegistrationPage client={clientWith(request)} />)

    expect(screen.getByRole('tab', { name: /MANUAL/ })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('READ ONLY')).toBeInTheDocument()
    expect(screen.getByText(/typed metadata API/)).toBeInTheDocument()
    await waitFor(() => expect(request.mock.calls.some(([path, options]) => (
      path.startsWith('/catalog/tree/nodes?') && options?.signal instanceof AbortSignal
    ))).toBe(true))
  })

  it('loads upload history only after the bulk workbench is selected', async () => {
    const request = vi.fn((path: string, options?: RequestOptions) => {
      void options
      return Promise.resolve(path.startsWith('/uploads') ? { items: [] } : emptyTree)
    })

    render(<RegistrationPage client={clientWith(request)} />)
    fireEvent.click(screen.getByRole('tab', { name: /BULK/ }))

    expect(screen.getByRole('tab', { name: /BULK/ })).toHaveAttribute('aria-selected', 'true')
    await waitFor(() => expect(request.mock.calls.some(([path, options]) => (
      path === '/uploads?limit=50' && options?.signal instanceof AbortSignal
    ))).toBe(true))
  })

  it('aborts the prior workspace client request when the security boundary changes', async () => {
    let priorSignal: AbortSignal | undefined
    const firstClient = clientWith((path, options) => {
      if (path.startsWith('/catalog/tree')) return Promise.resolve(emptyTree)
      priorSignal = options?.signal ?? undefined
      return new Promise((_resolve, reject) => {
        priorSignal?.addEventListener(
          'abort',
          () => reject(new DOMException('aborted', 'AbortError')),
          { once: true },
        )
      })
    })
    const secondClient = clientWith((path) => Promise.resolve(
      path.startsWith('/uploads') ? { items: [] } : emptyTree,
    ))
    const view = render(<RegistrationPage client={firstClient} />)
    fireEvent.click(screen.getByRole('tab', { name: /BULK/ }))
    await waitFor(() => expect(priorSignal).toBeDefined())

    view.rerender(<RegistrationPage client={secondClient} />)

    await waitFor(() => expect(priorSignal?.aborted).toBe(true))
    expect(screen.queryByText('업로드 또는 검증 상태 확인 실패')).not.toBeInTheDocument()
  })

  it('requires the current aspect hash before an accepted upload can become a proposal', async () => {
    const upload = uploadRecord()
    const request = vi.fn((path: string, options?: RequestOptions) => {
      void options
      return Promise.resolve(path.startsWith('/uploads') ? { items: [upload] } : emptyTree)
    })

    render(<RegistrationPage client={clientWith(request)} />)
    fireEvent.click(screen.getByRole('tab', { name: /BULK/ }))
    const historyItem = await screen.findByRole('button', { name: /catalog.csv/ })
    fireEvent.click(historyItem)

    const beforeHash = screen.getByLabelText('원본 Aspect SHA-256')
    expect(beforeHash).toBeRequired()
    expect(beforeHash).toHaveAttribute('pattern', '[0-9a-f]{64}')
    expect(screen.getByRole('option', { name: 'schemaMetadata' })).toBeInTheDocument()
  })

  it('purges all bulk form values when the workspace client changes', async () => {
    const firstUpload = uploadRecord('ACCEPTED', 'catalog-a.csv')
    const secondUpload = uploadRecord('ACCEPTED', 'catalog-b.csv')
    const firstClient = clientWith((path) => Promise.resolve(
      path.startsWith('/uploads') ? { items: [firstUpload] } : emptyTree,
    ))
    const secondClient = clientWith((path) => Promise.resolve(
      path.startsWith('/uploads') ? { items: [secondUpload] } : emptyTree,
    ))
    const view = render(<RegistrationPage client={firstClient} />)
    fireEvent.click(screen.getByRole('tab', { name: /BULK/ }))
    fireEvent.click(await screen.findByRole('button', { name: /catalog-a.csv/ }))
    fireEvent.change(screen.getByLabelText('대상 URN'), {
      target: { value: 'urn:li:dataset:workspace-a' },
    })
    fireEvent.change(screen.getByLabelText('원본 Aspect SHA-256'), {
      target: { value: 'b'.repeat(64) },
    })
    fireEvent.change(screen.getByLabelText('분류등급'), {
      target: { value: 'CONFIDENTIAL' },
    })

    view.rerender(<RegistrationPage client={secondClient} />)
    fireEvent.click(await screen.findByRole('button', { name: /catalog-b.csv/ }))

    expect(screen.getByLabelText('대상 URN')).toHaveValue('')
    expect(screen.getByLabelText('원본 Aspect SHA-256')).toHaveValue('')
    expect(screen.getByLabelText('분류등급')).toHaveValue('INTERNAL')
  })

  it('prevents duplicate proposals and locks record switching while one is in flight', async () => {
    const upload = uploadRecord()
    let resolveProposal: ((value: ChangeRequestRecord) => void) | undefined
    const proposalPromise = new Promise<ChangeRequestRecord>((resolve) => {
      resolveProposal = resolve
    })
    const request = vi.fn((path: string, options?: RequestOptions): Promise<unknown> => {
      void options
      if (path.endsWith('/registration-proposals')) return proposalPromise
      return Promise.resolve(path.startsWith('/uploads') ? { items: [upload] } : emptyTree)
    })
    render(<RegistrationPage client={clientWith(request)} />)
    fireEvent.click(screen.getByRole('tab', { name: /BULK/ }))
    const historyItem = await screen.findByRole('button', { name: /catalog.csv/ })
    fireEvent.click(historyItem)
    fireEvent.change(screen.getByLabelText('대상 URN'), {
      target: { value: 'urn:li:dataset:test' },
    })
    fireEvent.change(screen.getByLabelText('원본 Aspect SHA-256'), {
      target: { value: 'b'.repeat(64) },
    })
    const submit = screen.getByRole('button', { name: '변경요청 생성' })
    fireEvent.click(submit)
    fireEvent.click(submit)

    await waitFor(() => expect(request.mock.calls.filter(
      ([path]) => path.endsWith('/registration-proposals'),
    )).toHaveLength(1))
    expect(historyItem).toBeDisabled()
    expect(screen.getByRole('button', { name: '생성 중…' })).toBeDisabled()

    await act(async () => {
      resolveProposal?.({
        id: 'change-1', number: 'CR-1', request_type: 'DATA_REGISTRATION',
        title: '등록', description: '', state: 'REGISTERED', requester_id: 'subject-1',
        classification: 'INTERNAL', version: 1, items: [], approvals: [], transitions: [],
      })
      await proposalPromise
    })
    const proposalStage = screen.getByText('Proposal').closest('li')
    expect(proposalStage).not.toBeNull()
    expect(within(proposalStage as HTMLElement).getByText('완료')).toBeInTheDocument()
  })

  it('renders rejected validation as failure rather than completion', async () => {
    const rejected = uploadRecord('REJECTED', 'rejected.csv')
    const request = vi.fn((path: string, options?: RequestOptions) => {
      void options
      return Promise.resolve(path.startsWith('/uploads') ? { items: [rejected] } : emptyTree)
    })
    render(<RegistrationPage client={clientWith(request)} />)
    fireEvent.click(screen.getByRole('tab', { name: /BULK/ }))
    fireEvent.click(await screen.findByRole('button', { name: /rejected.csv/ }))

    const validationStage = screen.getByText('Validation').closest('li')
    expect(validationStage).not.toBeNull()
    expect(validationStage).toHaveClass('failed')
    expect(within(validationStage as HTMLElement).getByText('실패')).toBeInTheDocument()
  })
})
