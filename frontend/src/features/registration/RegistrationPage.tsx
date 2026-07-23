import { useEffect, useState } from 'react'
import { PencilLine, UploadCloud } from 'lucide-react'
import type { ApiClient } from '../../api/client'
import type { CatalogAssetDetail } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { PageTitle } from '../../components/layout/PageTitle'
import { CatalogResourceTree } from '../catalog/CatalogResourceTree'
import { RegistrationBulkWorkbench } from './RegistrationBulkWorkbench'
import { RegistrationManualWorkbench } from './RegistrationManualWorkbench'

type RegistrationMode = 'MANUAL' | 'BULK'

export async function loadCompleteAssetDetail(
  client: ApiClient,
  assetId: string,
  signal: AbortSignal,
): Promise<CatalogAssetDetail> {
  const first = await client.request<CatalogAssetDetail>(
    `/catalog/assets/${assetId}?field_offset=0&field_limit=200`,
    { signal },
  )
  const fields = [...first.schema_fields]
  let page = first
  while (
    page.schema_fields_has_more
    && fields.length < first.schema_fields_available
  ) {
    const offset = fields.length
    page = await client.request<CatalogAssetDetail>(
      `/catalog/assets/${assetId}?field_offset=${offset}&field_limit=200&field_source_version=${encodeURIComponent(first.source_version)}`,
      { signal },
    )
    if (
      page.id !== first.id
      || page.source_version !== first.source_version
      || page.schema_fields_offset !== offset
    ) {
      throw new Error('컬럼 페이지의 원본 버전 또는 위치가 변경되었습니다.')
    }
    fields.push(...page.schema_fields)
  }
  if (fields.length !== first.schema_fields_available) {
    throw new Error('전체 컬럼 메타데이터를 검증된 페이지로 불러오지 못했습니다.')
  }
  return {
    ...first,
    schema_fields: fields,
    schema_fields_offset: 0,
    schema_fields_limit: fields.length,
    schema_fields_has_more: false,
  }
}

export function RegistrationPage({ client }: { client: ApiClient }) {
  const [mode, setMode] = useState<RegistrationMode>('MANUAL')
  const [selectedAssetId, setSelectedAssetId] = useState<string>()
  const [selectedAssetDetail, setSelectedAssetDetail] = useState<CatalogAssetDetail>()
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [detailError, setDetailError] = useState<unknown>()

  useEffect(() => {
    setSelectedAssetId(undefined)
    setSelectedAssetDetail(undefined)
    setLoadingDetail(false)
    setDetailError(undefined)
  }, [client])

  useEffect(() => {
    if (!selectedAssetId) {
      setSelectedAssetDetail(undefined)
      setLoadingDetail(false)
      setDetailError(undefined)
      return
    }
    let active = true
    const controller = new AbortController()
    setLoadingDetail(true)
    setSelectedAssetDetail(undefined)
    setDetailError(undefined)
    void loadCompleteAssetDetail(client, selectedAssetId, controller.signal)
      .then((detail) => { if (active) setSelectedAssetDetail(detail) })
      .catch((error: unknown) => {
        if (active && !controller.signal.aborted) setDetailError(error)
      })
      .finally(() => { if (active) setLoadingDetail(false) })
    return () => { active = false; controller.abort() }
  }, [client, selectedAssetId])

  return (
    <section className="registration-page">
      <PageTitle
        icon="RG"
        eyebrow="Governed registration"
        title="데이터 등록"
        description="단건 검토와 대량 업로드를 분리하고, 모든 변경은 권한 검사와 변경관리 승인을 거칩니다."
      />
      <div className="registration-mode-tabs" role="tablist" aria-label="등록 방식">
        <button
          type="button"
          role="tab"
          id="registration-manual-tab"
          aria-controls="registration-manual-panel"
          aria-selected={mode === 'MANUAL'}
          tabIndex={mode === 'MANUAL' ? 0 : -1}
          className={mode === 'MANUAL' ? 'active' : ''}
          onClick={() => setMode('MANUAL')}
          title="단건 검토"
        ><PencilLine size={13} />MANUAL</button>
        <button
          type="button"
          role="tab"
          id="registration-bulk-tab"
          aria-controls="registration-bulk-panel"
          aria-selected={mode === 'BULK'}
          tabIndex={mode === 'BULK' ? 0 : -1}
          className={mode === 'BULK' ? 'active' : ''}
          onClick={() => setMode('BULK')}
          title="일괄 등록"
        ><UploadCloud size={13} />BULK</button>
      </div>

      {mode === 'MANUAL' ? (
        <div className="registration-manual-workbench" id="registration-manual-panel" role="tabpanel" aria-labelledby="registration-manual-tab">
          <CatalogResourceTree
            client={client}
            selectedAssetId={selectedAssetId}
            onSelectAsset={(assetId) => {
              setSelectedAssetId(assetId)
            }}
          />
          <div>
            <RegistrationManualWorkbench
              client={client}
              asset={selectedAssetDetail}
              loading={loadingDetail}
              onClose={() => setSelectedAssetId(undefined)}
            />
            <ErrorNotice error={detailError} />
          </div>
        </div>
      ) : (
        <div id="registration-bulk-panel" role="tabpanel" aria-labelledby="registration-bulk-tab">
          <RegistrationBulkWorkbench client={client} />
        </div>
      )}
    </section>
  )
}
