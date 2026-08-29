import { describe, expect, it, vi } from 'vitest'
import type { CatalogExportCreateRequest } from '../../api/types'
import { CatalogExportApi, catalogExportCapability } from './catalogExportApi'

describe('CatalogExportApi', () => {
  it('discovers export availability through its separately authorized endpoint and fails closed', async () => {
    const allowed = vi.fn().mockResolvedValue({ enabled: true, maximum_rows: 250_000 })
    const denied = vi.fn().mockRejectedValue(new Error('forbidden'))

    await expect(catalogExportCapability({ request: allowed })).resolves.toEqual({
      enabled: true, maximum_rows: 250_000,
    })
    await expect(catalogExportCapability({ request: denied })).resolves.toEqual({
      enabled: false, maximum_rows: 0,
    })
    expect(allowed).toHaveBeenCalledWith('/catalog/export-capability')
    expect(denied).toHaveBeenCalledWith('/catalog/export-capability')
  })

  it('fails closed when the server omits the explicit export row ceiling', async () => {
    const malformed = vi.fn().mockResolvedValue({ enabled: true })

    await expect(catalogExportCapability({ request: malformed })).resolves.toEqual({
      enabled: false, maximum_rows: 0,
    })
  })

  it('creates a server-managed CSV export with one idempotency key', async () => {
    const request = vi.fn().mockResolvedValue({
      export_id: 'export-one', job_id: 'job-one', state: 'QUEUED',
    })
    const api = new CatalogExportApi({ request })
    const payload: CatalogExportCreateRequest = {
      q: 'wafer yield',
      platform: 'snowflake',
      classification: 'INTERNAL',
      sort: 'NAME_ASC',
      format: 'CSV',
    }

    await api.create(payload, 'catalog-export-operation-one')

    expect(request).toHaveBeenCalledWith('/catalog/exports', {
      method: 'POST',
      idempotencyKey: 'catalog-export-operation-one',
      body: JSON.stringify(payload),
    })
  })

  it('reads status and requests a server-issued download URL without fetching rows', async () => {
    const request = vi.fn().mockResolvedValue({})
    const api = new CatalogExportApi({ request })

    await api.get('export/one')
    await api.download('export/one')

    expect(request.mock.calls).toEqual([
      ['/catalog/exports/export%2Fone'],
      ['/catalog/exports/export%2Fone/download', { method: 'POST' }],
    ])
    expect(request.mock.calls.some(([path]) => String(path).includes('/catalog/assets'))).toBe(false)
  })
})
