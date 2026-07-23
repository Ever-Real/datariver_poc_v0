import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import type { ApiClient, RequestOptions } from '../../api/client'
import { CatalogMetadataVocabularyBrowser } from './CatalogMetadataVocabularyBrowser'

it('replaces bounded vocabulary pages and never renders provider identities', async () => {
  const writeText = vi.fn(() => Promise.resolve())
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText },
  })
  const request = vi.fn((path: string, options?: RequestOptions) => {
    expect(options?.cache).toBe('no-store')
    if (path.includes('cursor=next-page')) {
      return Promise.resolve({
        items: [{
          id: '01900000-0000-7000-8000-000000000002',
          kind: 'TAG',
          display_name: 'Restricted',
          source_version: 'b'.repeat(64),
          provider_ref: 'urn:li:tag:must-not-render',
        }],
        page: { limit: 20 },
      })
    }
    return Promise.resolve({
      items: [{
        id: '01900000-0000-7000-8000-000000000001',
        kind: 'TAG',
        display_name: 'Business Critical',
        source_version: 'a'.repeat(64),
        provider_ref: 'urn:li:tag:must-not-render',
      }],
      page: { limit: 20, next_cursor: 'next-page' },
    })
  })
  const client = { request } as unknown as ApiClient

  render(<CatalogMetadataVocabularyBrowser client={client} />)

  await waitFor(() => expect(screen.getByText('Business Critical')).toBeInTheDocument())
  expect(screen.getByText('01900000-0000-7000-8000-000000000001')).toBeInTheDocument()
  expect(screen.queryByText(/urn:li:/)).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Business Critical UUID 복사' }))
  await waitFor(() => expect(screen.getByRole('button', {
    name: 'Business Critical UUID 복사',
  })).toHaveTextContent('복사됨'))
  expect(writeText).toHaveBeenCalledWith('01900000-0000-7000-8000-000000000001')

  fireEvent.click(screen.getByRole('button', { name: '다음 어휘 페이지' }))

  await waitFor(() => expect(screen.getByText('Restricted')).toBeInTheDocument())
  expect(screen.queryByText('Business Critical')).not.toBeInTheDocument()
  expect(screen.queryByText(/urn:li:/)).not.toBeInTheDocument()
  expect(request).toHaveBeenLastCalledWith(
    '/uploads/metadata-vocabulary?kind=TAG&limit=20&cursor=next-page',
    expect.objectContaining({ cache: 'no-store' }),
  )
})

it('binds a search to its kind and discards an older late response', async () => {
  let resolveOld: ((value: unknown) => void) | undefined
  const request = vi.fn((path: string) => {
    if (path.includes('kind=TAG')) {
      return new Promise((resolve) => {
        resolveOld = resolve
      })
    }
    return Promise.resolve({
      items: [{
        id: '01900000-0000-7000-8000-000000000003',
        kind: 'DOMAIN',
        display_name: 'Finance',
        source_version: 'c'.repeat(64),
      }],
      page: { limit: 20 },
    })
  })
  const client = { request } as unknown as ApiClient

  render(<CatalogMetadataVocabularyBrowser client={client} />)
  fireEvent.change(screen.getByLabelText('어휘 종류'), { target: { value: 'DOMAIN' } })

  await waitFor(() => expect(screen.getByText('Finance')).toBeInTheDocument())
  resolveOld?.({
    items: [{
      id: '01900000-0000-7000-8000-000000000004',
      kind: 'TAG',
      display_name: 'Late Tag',
      source_version: 'd'.repeat(64),
    }],
    page: { limit: 20 },
  })
  await Promise.resolve()

  expect(screen.queryByText('Late Tag')).not.toBeInTheDocument()
  expect(screen.getByText('Finance')).toBeInTheDocument()
})

it('fails closed when the server returns a cross-kind item', async () => {
  const client = {
    request: vi.fn(() => Promise.resolve({
      items: [{
        id: '01900000-0000-7000-8000-000000000005',
        kind: 'DOMAIN',
        display_name: 'Wrong Kind',
        source_version: 'e'.repeat(64),
      }],
      page: { limit: 20 },
    })),
  } as unknown as ApiClient

  render(<CatalogMetadataVocabularyBrowser client={client} />)

  await waitFor(() => {
    expect(screen.getByText('통제 어휘 응답이 요청 범위와 일치하지 않습니다.')).toBeInTheDocument()
  })
  expect(screen.queryByText('Wrong Kind')).not.toBeInTheDocument()
})
