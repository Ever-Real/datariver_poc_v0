import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient } from '../../api/client'
import { CatalogExportControl, safeCatalogExportDownloadUrl } from './CatalogExportControl'

const completed = {
  export_id: '00000000-0000-4000-8000-000000000401',
  job_id: '00000000-0000-4000-8000-000000000402',
  state: 'COMPLETED',
  last_error_code: null,
  row_count: 42,
  size_bytes: 2048,
  content_sha256: 'a'.repeat(64),
  display_name: 'catalog-export.csv',
  created_at: '2026-07-17T00:00:00Z',
  completed_at: '2026-07-17T00:00:01Z',
  access_until: '2026-07-18T00:00:00Z',
}

describe('CatalogExportControl', () => {
  it('places separate compact CSV and Excel actions in the search toolbar', async () => {
    const request = vi.fn((path: string, _options?: { body: string }) => {
      void _options
      if (path.endsWith('/download')) {
        return Promise.resolve({ url: 'https://objects.example.test/export.xlsx?signature=short', expires_seconds: 60 })
      }
      return Promise.resolve({
        export_id: completed.export_id, job_id: completed.job_id, state: 'COMPLETED',
      })
    })
    const navigate = vi.fn()
    render(<CatalogExportControl
      client={{ request } as unknown as ApiClient}
      compact
      workerEnabled
      query="wafer"
      navigate={navigate}
    />)

    expect(screen.getByRole('button', { name: 'CSV 저장' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Excel 저장' }))
    await waitFor(() => expect(request).toHaveBeenCalled())
    const [, options] = request.mock.calls[0] ?? []
    expect(JSON.parse(options?.body ?? '{}')).toMatchObject({ format: 'XLSX' })

    expect(await screen.findByRole('button', { name: 'XLSX 다운로드' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'XLSX 다운로드' }))
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('https://objects.example.test/export.xlsx?signature=short'))
  })

  it('fails closed with an explicit operator explanation when the worker is disabled', () => {
    const request = vi.fn()
    render(<CatalogExportControl
      client={{ request } as unknown as ApiClient}
      workerEnabled={false}
      query="wafer"
    />)

    expect(screen.getByRole('button', { name: 'CSV 생성' })).toBeDisabled()
    expect(screen.getByText(/catalog\.export 권한 또는 운영자의 분리된 DB/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'CSV 생성' }))
    expect(request).not.toHaveBeenCalled()
  })

  it('keeps RESTRICTED search results non-exportable even when the worker is enabled', () => {
    render(<CatalogExportControl
      client={{ request: vi.fn() } as unknown as ApiClient}
      workerEnabled
      query="restricted"
      classification="RESTRICTED"
    />)

    expect(screen.getByRole('button', { name: 'CSV 생성' })).toBeDisabled()
    expect(screen.getByText(/CSV 내보내기와 XLSX 내보내기가 금지/)).toBeInTheDocument()
  })

  it('shows queued, running, and completed server states before requesting a download URL', async () => {
    const navigate = vi.fn()
    const request = vi.fn((path: string, options?: { method?: string }) => {
      if (path === '/catalog/exports' && options?.method === 'POST') {
        return Promise.resolve({
          export_id: completed.export_id, job_id: completed.job_id, state: 'QUEUED',
        })
      }
      if (path.endsWith('/download')) {
        return Promise.resolve({
          url: 'https://objects.example.test/export.csv?signature=short', expires_seconds: 60,
        })
      }
      const statusReads = request.mock.calls.filter(([calledPath]) => (
        String(calledPath).includes(`/catalog/exports/${completed.export_id}`)
        && !String(calledPath).endsWith('/download')
      )).length
      return Promise.resolve(
        statusReads === 1 ? { ...completed, state: 'RUNNING', completed_at: null } : completed,
      )
    })
    render(<CatalogExportControl
      client={{ request } as unknown as ApiClient}
      workerEnabled
      query="wafer yield"
      platform="snowflake"
      classification="INTERNAL"
      navigate={navigate}
      pollMilliseconds={5}
    />)

    fireEvent.click(screen.getByRole('button', { name: 'CSV 생성' }))
    expect(await screen.findByText('대기 중')).toBeInTheDocument()

    expect(await screen.findByText('생성 중')).toBeInTheDocument()
    expect(await screen.findByText('완료')).toBeInTheDocument()
    expect(screen.getByText('42 rows')).toBeInTheDocument()
    expect(screen.getByText('2.0 KiB')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'CSV 다운로드' }))
    await waitFor(() => expect(navigate).toHaveBeenCalledWith(
      'https://objects.example.test/export.csv?signature=short',
    ))
    expect(request.mock.calls.some(([path]) => String(path).includes('/catalog/assets'))).toBe(false)
  })

  it('requests a server-managed XLSX artifact when Excel is selected', async () => {
    const request = vi.fn().mockResolvedValue({
      export_id: completed.export_id, job_id: completed.job_id, state: 'QUEUED',
    })
    render(<CatalogExportControl
      client={{ request } as unknown as ApiClient}
      workerEnabled
      query="wafer"
    />)

    fireEvent.change(screen.getByRole('combobox', { name: '내보내기 형식' }), {
      target: { value: 'XLSX' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'XLSX 생성' }))

    await waitFor(() => expect(request).toHaveBeenCalled())
    const [, options] = request.mock.calls[0] as [string, { body: string }]
    expect(JSON.parse(options.body)).toMatchObject({ format: 'XLSX' })
  })

  it('stops polling and exposes the server error code after a failed job', async () => {
    const request = vi.fn().mockResolvedValue({
      export_id: completed.export_id,
      job_id: completed.job_id,
      state: 'FAILED',
    })
    render(<CatalogExportControl
      client={{ request } as unknown as ApiClient}
      workerEnabled
      query="wafer"
    />)

    fireEvent.click(screen.getByRole('button', { name: 'CSV 생성' }))
    expect(await screen.findByText('실패')).toBeInTheDocument()
    expect(request).toHaveBeenCalledOnce()
  })

  it('states the complete-result ceiling and explains an over-limit failure', async () => {
    const request = vi.fn().mockResolvedValue({
      ...completed,
      state: 'FAILED',
      last_error_code: 'EXPORT_ROW_LIMIT',
      completed_at: null,
    })
    render(<CatalogExportControl
      client={{ request } as unknown as ApiClient}
      compact
      workerEnabled
      maximumRows={250_000}
      query="wafer"
    />)

    expect(screen.getByText(/전체 허용 결과/)).toHaveTextContent('최대 250,000건')
    fireEvent.click(screen.getByRole('button', { name: 'CSV 저장' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      '검색 결과가 내보내기 한도(최대 250,000건)를 초과했습니다.',
    )
  })

  it('explains the typed artifact byte ceiling instead of exposing only a worker code', async () => {
    const request = vi.fn().mockResolvedValue({
      ...completed,
      state: 'FAILED',
      last_error_code: 'EXPORT_BYTE_LIMIT',
      completed_at: null,
    })
    render(<CatalogExportControl
      client={{ request } as unknown as ApiClient}
      compact
      workerEnabled
      maximumRows={250_000}
      query="wafer"
    />)

    fireEvent.click(screen.getByRole('button', { name: 'CSV 저장' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      '생성된 파일이 서버 내보내기 용량 한도를 초과했습니다.',
    )
  })

  it('clears the prior workspace export and ignores its late response when the client changes', async () => {
    let finishOldRequest: ((value: unknown) => void) | undefined
    const oldRequest = vi.fn(() => new Promise((resolve) => { finishOldRequest = resolve }))
    const newRequest = vi.fn()
    const view = render(<CatalogExportControl
      client={{ request: oldRequest } as unknown as ApiClient}
      workerEnabled
      query="wafer"
    />)

    fireEvent.click(screen.getByRole('button', { name: 'CSV 생성' }))
    expect(screen.getByRole('button', { name: '요청 중…' })).toBeDisabled()
    view.rerender(<CatalogExportControl
      client={{ request: newRequest } as unknown as ApiClient}
      workerEnabled
      query="yield"
    />)
    expect(screen.getByRole('button', { name: 'CSV 생성' })).toBeEnabled()

    finishOldRequest?.({ export_id: completed.export_id, job_id: completed.job_id, state: 'COMPLETED' })
    await Promise.resolve()

    expect(screen.queryByRole('button', { name: 'CSV 다운로드' })).not.toBeInTheDocument()
    expect(screen.queryByText('완료')).not.toBeInTheDocument()
    expect(newRequest).not.toHaveBeenCalled()
  })

  it('clears an export receipt when the bound search request changes', async () => {
    const request = vi.fn().mockResolvedValue(completed)
    const client = { request } as unknown as ApiClient
    const view = render(<CatalogExportControl
      client={client}
      workerEnabled
      query="wafer"
      platform="snowflake"
    />)

    fireEvent.click(screen.getByRole('button', { name: 'CSV 생성' }))
    expect(await screen.findByRole('button', { name: 'CSV 다운로드' })).toBeInTheDocument()

    view.rerender(<CatalogExportControl
      client={client}
      workerEnabled
      query="yield"
      platform="snowflake"
    />)

    expect(screen.queryByRole('button', { name: 'CSV 다운로드' })).not.toBeInTheDocument()
    expect(screen.queryByText('완료')).not.toBeInTheDocument()
  })

  it('removes download access and ignores a late download URL after capability revocation', async () => {
    let finishDownload: ((value: unknown) => void) | undefined
    const navigate = vi.fn()
    const request = vi.fn((path: string) => {
      if (path.endsWith('/download')) {
        return new Promise((resolve) => { finishDownload = resolve })
      }
      return Promise.resolve({
        export_id: completed.export_id, job_id: completed.job_id, state: 'COMPLETED',
      })
    })
    const client = { request } as unknown as ApiClient
    const view = render(<CatalogExportControl
      client={client}
      workerEnabled
      query="wafer"
      navigate={navigate}
    />)

    fireEvent.click(screen.getByRole('button', { name: 'CSV 생성' }))
    fireEvent.click(await screen.findByRole('button', { name: 'CSV 다운로드' }))
    view.rerender(<CatalogExportControl
      client={client}
      workerEnabled={false}
      query="wafer"
      navigate={navigate}
    />)

    expect(screen.queryByRole('button', { name: /CSV 다운로드/ })).not.toBeInTheDocument()
    expect(screen.queryByText('완료')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'CSV 생성' })).toBeDisabled()
    finishDownload?.({ url: 'https://objects.example.test/late.csv', expires_seconds: 60 })
    await Promise.resolve()
    expect(navigate).not.toHaveBeenCalled()
  })
})

describe('safeCatalogExportDownloadUrl', () => {
  it('accepts only browser HTTP download targets', () => {
    expect(safeCatalogExportDownloadUrl('https://objects.example.test/export.csv'))
      .toBe('https://objects.example.test/export.csv')
    expect(() => safeCatalogExportDownloadUrl('javascript:alert(1)')).toThrow(/허용되지 않은/)
  })
})
