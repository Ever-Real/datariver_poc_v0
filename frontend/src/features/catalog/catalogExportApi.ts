import type { ApiClient } from '../../api/client'
import type {
  CatalogExportCapability,
  CatalogExportCreateRequest,
  CatalogExportCreateResponse,
  CatalogExportDownload,
  CatalogExportStatus,
} from '../../api/types'

type CatalogExportApiClient = Pick<ApiClient, 'request'>

export class CatalogExportApi {
  constructor(private readonly client: CatalogExportApiClient) {}

  capability() {
    return this.client.request<CatalogExportCapability>('/catalog/export-capability')
  }

  create(payload: CatalogExportCreateRequest, idempotencyKey: string) {
    return this.client.request<CatalogExportCreateResponse>('/catalog/exports', {
      method: 'POST',
      idempotencyKey,
      body: JSON.stringify(payload),
    })
  }

  get(exportId: string) {
    return this.client.request<CatalogExportStatus>(
      `/catalog/exports/${encodeURIComponent(exportId)}`,
    )
  }

  download(exportId: string) {
    return this.client.request<CatalogExportDownload>(
      `/catalog/exports/${encodeURIComponent(exportId)}/download`,
      { method: 'POST' },
    )
  }
}

export async function catalogExportCapabilityEnabled(client: CatalogExportApiClient) {
  try {
    return (await new CatalogExportApi(client).capability()).enabled === true
  } catch {
    return false
  }
}
