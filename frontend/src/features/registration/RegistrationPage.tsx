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
    void client.request<CatalogAssetDetail>(`/catalog/assets/${selectedAssetId}`, { signal: controller.signal })
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
            query=""
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
