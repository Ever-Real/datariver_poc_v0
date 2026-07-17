import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiClient, RequestOptions } from '../../api/client'
import type {
  UploadContentProfile,
  UploadPreparation,
  UploadRecord,
} from '../../api/types'
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
  contentProfile: UploadContentProfile = 'FORMAT_ONLY_V1',
): UploadRecord {
  return {
    id: 'upload-1',
    display_name: displayName,
    state,
    size_bytes: 128,
    content_type: 'text/csv',
    sha256: 'a'.repeat(64),
    classification: 'INTERNAL',
    content_profile: contentProfile,
    expires_at: '2026-01-02T00:00:00Z',
    version: 3,
    recommended_part_size_bytes: 5_242_880,
    validation_summary: { rows: 2 },
    last_error_code: null,
  }
}

function preparationRecord(
  state: UploadPreparation['state'] = 'QUEUED',
): UploadPreparation {
  return {
    id: 'preparation-1',
    upload_id: 'upload-1',
    content_profile: 'DATASET_DESCRIPTION_CSV_V1',
    source_manifest_version: 3,
    source_sha256: 'a'.repeat(64),
    configuration_hash: 'b'.repeat(64),
    state,
    attempts: 0,
    rows_processed: 0,
    total_rows: null,
    last_error_code: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    version: 1,
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Registration workbench', () => {
  it('opens in a governed manual catalog workbench', async () => {
    const request = vi.fn((path: string, options?: RequestOptions) => {
      void path
      void options
      return Promise.resolve(emptyTree)
    })

    render(<RegistrationPage client={clientWith(request)} />)

    expect(screen.getByRole('tab', { name: /MANUAL/ })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('GOVERNED')).toBeInTheDocument()
    expect(screen.getByText(/원본 hash 미리보기/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Aspect JSON')).not.toBeInTheDocument()
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

  it('discards an in-flight preparation read when the workspace client changes', async () => {
    const typed = uploadRecord(
      'ACCEPTED',
      'dataset-description.csv',
      'DATASET_DESCRIPTION_CSV_V1',
    )
    const generic = uploadRecord('ACCEPTED', 'generic.csv')
    let preparationSignal: AbortSignal | undefined
    const firstClient = clientWith((path, options) => {
      if (path.startsWith('/catalog/tree')) return Promise.resolve(emptyTree)
      if (path === '/uploads?limit=50') return Promise.resolve({ items: [typed] })
      if (path === '/uploads/upload-1/preparations?limit=20') {
        preparationSignal = options?.signal ?? undefined
        return new Promise((_resolve, reject) => {
          preparationSignal?.addEventListener(
            'abort',
            () => reject(new DOMException('aborted', 'AbortError')),
            { once: true },
          )
        })
      }
      throw new Error(`unexpected request: ${path}`)
    })
    const secondClient = clientWith((path) => Promise.resolve(
      path === '/uploads?limit=50' ? { items: [generic] } : emptyTree,
    ))

    const view = render(<RegistrationPage client={firstClient} />)
    fireEvent.click(screen.getByRole('tab', { name: /BULK/ }))
    fireEvent.click(await screen.findByRole('button', { name: /dataset-description.csv/ }))
    await waitFor(() => expect(preparationSignal).toBeDefined())

    view.rerender(<RegistrationPage client={secondClient} />)

    await waitFor(() => expect(preparationSignal?.aborted).toBe(true))
    fireEvent.click(await screen.findByRole('button', { name: /generic.csv/ }))
    expect(screen.getByText(/형식 검증 전용/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Bulk preparation 상태')).not.toBeInTheDocument()
  })

  it('keeps accepted uploads read-only until typed accepted-content binding exists', async () => {
    const upload = uploadRecord()
    const request = vi.fn((path: string, options?: RequestOptions) => {
      void options
      return Promise.resolve(path.startsWith('/uploads') ? { items: [upload] } : emptyTree)
    })

    render(<RegistrationPage client={clientWith(request)} />)
    fireEvent.click(screen.getByRole('tab', { name: /BULK/ }))
    const historyItem = await screen.findByRole('button', { name: /catalog.csv/ })
    fireEvent.click(historyItem)

    expect(screen.getByText(/형식 검증 전용/)).toBeInTheDocument()
    expect(screen.queryByLabelText('대상 URN')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Aspect JSON')).not.toBeInTheDocument()
    expect(request.mock.calls.some(([path]) => path.includes('/registration-proposals'))).toBe(false)
    const bindingStage = within(screen.getByRole('list', { name: '등록 처리 단계' }))
      .getByText('Preparation').closest('li')
    expect(bindingStage).not.toBeNull()
    expect(within(bindingStage as HTMLElement).getByText('대기')).toBeInTheDocument()
  })

  it('binds the selected typed profile to upload initiation', async () => {
    const initiated = uploadRecord(
      'INITIATED',
      'dataset-description.csv',
      'DATASET_DESCRIPTION_CSV_V1',
    )
    const accepted = { ...initiated, state: 'ACCEPTED', version: 3 }
    const request = vi.fn((path: string, options?: RequestOptions) => {
      if (path.startsWith('/catalog/tree')) return Promise.resolve(emptyTree)
      if (path === '/uploads?limit=50') return Promise.resolve({ items: [] })
      if (path === '/uploads' && options?.method === 'POST') return Promise.resolve(initiated)
      if (path === '/uploads/upload-1/parts') return Promise.resolve({ url: 'https://object.test/part' })
      if (path === '/uploads/upload-1/complete') return Promise.resolve(accepted)
      if (path === '/uploads/upload-1') return Promise.resolve(accepted)
      if (path === '/uploads/upload-1/preparations?limit=20') return Promise.resolve({ items: [] })
      throw new Error(`unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ ETag: '"part-etag"' }),
    }))

    render(<RegistrationPage client={clientWith(request)} />)
    fireEvent.click(screen.getByRole('tab', { name: /BULK/ }))
    fireEvent.change(screen.getByLabelText('등록 프로파일'), {
      target: { value: 'DATASET_DESCRIPTION_CSV_V1' },
    })
    const input = document.querySelector<HTMLInputElement>('input[type="file"]')
    expect(input).not.toBeNull()
    fireEvent.change(input as HTMLInputElement, {
      target: {
        files: [new File(['description'], 'dataset-description.csv', { type: 'text/csv' })],
      },
    })
    fireEvent.click(screen.getByRole('button', { name: '검증 업로드 시작' }))

    await waitFor(() => expect(request.mock.calls.some(([path, options]) => {
      if (path !== '/uploads' || options?.method !== 'POST' || typeof options.body !== 'string') {
        return false
      }
      const body = JSON.parse(options.body) as Record<string, unknown>
      return body.content_profile === 'DATASET_DESCRIPTION_CSV_V1'
    })).toBe(true))
    await screen.findByRole('button', { name: '미리보기 준비' })
  })

  it('creates only a server-owned preparation from an accepted typed upload', async () => {
    const upload = uploadRecord(
      'ACCEPTED',
      'dataset-description.csv',
      'DATASET_DESCRIPTION_CSV_V1',
    )
    const queued = preparationRecord()
    const request = vi.fn((path: string, options?: RequestOptions) => {
      if (path.startsWith('/catalog/tree')) return Promise.resolve(emptyTree)
      if (path === '/uploads?limit=50') return Promise.resolve({ items: [upload] })
      if (path === '/uploads/upload-1/preparations?limit=20') {
        return Promise.resolve({ items: [] })
      }
      if (path === '/uploads/upload-1/preparations' && options?.method === 'POST') {
        return Promise.resolve(queued)
      }
      throw new Error(`unexpected request: ${path}`)
    })

    render(<RegistrationPage client={clientWith(request)} />)
    fireEvent.click(screen.getByRole('tab', { name: /BULK/ }))
    fireEvent.click(await screen.findByRole('button', { name: /dataset-description.csv/ }))
    fireEvent.click(await screen.findByRole('button', { name: '미리보기 준비' }))

    expect((await screen.findAllByText('QUEUED')).length).toBeGreaterThan(0)
    const createCall = request.mock.calls.find(([path, options]) => (
      path === '/uploads/upload-1/preparations' && options?.method === 'POST'
    ))
    expect(createCall).toBeDefined()
    expect(createCall?.[1]?.ifMatch).toBe('"3"')
    expect(createCall?.[1]?.idempotencyKey).toMatch(/^upload-preparation-/)
    expect(createCall?.[1]?.body).toBeUndefined()
    expect(screen.getByLabelText('Bulk preparation 상태')).toHaveTextContent('준비 작업이 대기열에 등록되었습니다.')
    const bindingStage = within(screen.getByRole('list', { name: '등록 처리 단계' }))
      .getByText('Preparation').closest('li')
    expect(bindingStage).not.toBeNull()
    expect(within(bindingStage as HTMLElement).getByText('진행 중')).toBeInTheDocument()
    expect(request.mock.calls.some(([path]) => path.includes('/registration-proposals'))).toBe(false)
  })

  it('renders determinate server progress without inventing completion', async () => {
    const upload = uploadRecord(
      'ACCEPTED',
      'dataset-description.csv',
      'DATASET_DESCRIPTION_CSV_V1',
    )
    const preparing = {
      ...preparationRecord('PREPARING'),
      attempts: 1,
      rows_processed: 25,
      total_rows: 100,
    }
    const request = vi.fn((path: string) => {
      if (path.startsWith('/catalog/tree')) return Promise.resolve(emptyTree)
      if (path === '/uploads?limit=50') return Promise.resolve({ items: [upload] })
      if (path === '/uploads/upload-1/preparations?limit=20') {
        return Promise.resolve({ items: [preparing] })
      }
      throw new Error(`unexpected request: ${path}`)
    })

    render(<RegistrationPage client={clientWith(request)} />)
    fireEvent.click(screen.getByRole('tab', { name: /BULK/ }))
    fireEvent.click(await screen.findByRole('button', { name: /dataset-description.csv/ }))

    const progress = await screen.findByRole('progressbar', { name: '후보 준비 진행률' })
    expect(progress).toHaveAttribute('aria-valuenow', '25')
    expect(screen.getByLabelText('Bulk preparation 상태')).toHaveTextContent('후보 25행을 처리했습니다.')
    const bindingStage = within(screen.getByRole('list', { name: '등록 처리 단계' }))
      .getByText('Preparation').closest('li')
    expect(bindingStage).toHaveClass('pending')
  })

  it.each(['READY', 'FAILED', 'STALE'] as const)(
    'keeps %s preparation evidence non-executable',
    async (state) => {
      const upload = uploadRecord(
        'ACCEPTED',
        'dataset-description.csv',
        'DATASET_DESCRIPTION_CSV_V1',
      )
      const preparation = {
        ...preparationRecord(state),
        rows_processed: state === 'READY' ? 2 : 0,
        total_rows: state === 'READY' ? 2 : null,
        last_error_code: state === 'FAILED' ? 'PARSER_REJECTED' : null,
      }
      const request = vi.fn((path: string) => {
        if (path.startsWith('/catalog/tree')) return Promise.resolve(emptyTree)
        if (path === '/uploads?limit=50') return Promise.resolve({ items: [upload] })
        if (path === '/uploads/upload-1/preparations?limit=20') {
          return Promise.resolve({ items: [preparation] })
        }
        throw new Error(`unexpected request: ${path}`)
      })

      render(<RegistrationPage client={clientWith(request)} />)
      fireEvent.click(screen.getByRole('tab', { name: /BULK/ }))
      fireEvent.click(await screen.findByRole('button', { name: /dataset-description.csv/ }))

      expect((await screen.findAllByText(state)).length).toBeGreaterThan(0)
      expect(screen.queryByRole('button', { name: /UPDATE|변경 요청 생성|후보 실행/ })).not.toBeInTheDocument()
      expect(request.mock.calls.some(([path]) => (
        path.includes('/registration-proposals') || path.includes('/candidates')
      ))).toBe(false)
    },
  )

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
    fireEvent.change(screen.getByLabelText('분류등급'), {
      target: { value: 'CONFIDENTIAL' },
    })
    fireEvent.change(screen.getByLabelText('등록 프로파일'), {
      target: { value: 'DATASET_DESCRIPTION_CSV_V1' },
    })

    view.rerender(<RegistrationPage client={secondClient} />)
    fireEvent.click(await screen.findByRole('button', { name: /catalog-b.csv/ }))

    expect(screen.getByLabelText('분류등급')).toHaveValue('INTERNAL')
    expect(screen.getByLabelText('등록 프로파일')).toHaveValue('FORMAT_ONLY_V1')
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
