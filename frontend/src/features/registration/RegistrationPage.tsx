import { useEffect, useRef, useState } from 'react'
import { PencilLine, UploadCloud } from 'lucide-react'
import type { ApiClient } from '../../api/client'
import type {
  CatalogAssetDetail,
  RegistrationOperatorCapability,
} from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { GovernedUnavailable } from '../../components/common/GovernedUnavailable'
import { PageTitle } from '../../components/layout/PageTitle'
import { CatalogResourceTree } from '../catalog/CatalogResourceTree'
import { RegistrationBulkWorkbench } from './RegistrationBulkWorkbench'
import { RegistrationManualWorkbench } from './RegistrationManualWorkbench'

type RegistrationMode = 'MANUAL' | 'BULK'

const MANUAL_FIELD_PAGE_SIZE = 100

export async function loadAssetDetailPage(
  client: ApiClient,
  assetId: string,
  fieldOffset: number,
  expectedProviderSourceVersion: string | undefined,
  expectedProjectionSourceVersion: string | undefined,
  signal: AbortSignal,
): Promise<CatalogAssetDetail> {
  const query = new URLSearchParams({
    field_offset: String(fieldOffset),
    field_limit: String(MANUAL_FIELD_PAGE_SIZE),
  })
  if (expectedProviderSourceVersion) {
    query.set('field_source_version', expectedProviderSourceVersion)
  }
  const page = await client.request<CatalogAssetDetail>(
    `/catalog/assets/${assetId}?${query.toString()}`,
    { signal },
  )
  if (
    page.id !== assetId
    || page.schema_fields_offset !== fieldOffset
    || (expectedProviderSourceVersion && page.source_version !== expectedProviderSourceVersion)
    || (
      expectedProjectionSourceVersion
      && page.projection_source_version !== expectedProjectionSourceVersion
    )
  ) {
    throw new Error('컬럼 페이지의 자산, 원본 버전 또는 위치가 변경되었습니다.')
  }
  return page
}

export function RegistrationPage({ client }: { client: ApiClient }) {
  const [mode, setMode] = useState<RegistrationMode>('MANUAL')
  const [selectedAssetId, setSelectedAssetId] = useState<string>()
  const [selectedAssetDetail, setSelectedAssetDetail] = useState<CatalogAssetDetail>()
  const [fieldOffset, setFieldOffset] = useState(0)
  const snapshotRef = useRef<{
    providerSourceVersion: string
    projectionSourceVersion: string
  } | undefined>(undefined)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [detailError, setDetailError] = useState<unknown>()
  const [capability, setCapability] = useState<RegistrationOperatorCapability>()
  const [capabilityError, setCapabilityError] = useState<unknown>()

  useEffect(() => {
    let active = true
    const controller = new AbortController()
    setCapability(undefined)
    setCapabilityError(undefined)
    setSelectedAssetId(undefined)
    setSelectedAssetDetail(undefined)
    setFieldOffset(0)
    snapshotRef.current = undefined
    setLoadingDetail(false)
    setDetailError(undefined)
    void client.request<RegistrationOperatorCapability>(
      '/uploads/operator-capability',
      { signal: controller.signal },
    )
      .then((value) => {
        if (active) setCapability(value)
      })
      .catch((error: unknown) => {
        if (active && !controller.signal.aborted) setCapabilityError(error)
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [client])

  useEffect(() => {
    if (!selectedAssetId) {
      setSelectedAssetDetail(undefined)
      setFieldOffset(0)
      snapshotRef.current = undefined
      setLoadingDetail(false)
      setDetailError(undefined)
      return
    }
    let active = true
    const controller = new AbortController()
    setLoadingDetail(true)
    setDetailError(undefined)
    void loadAssetDetailPage(
      client,
      selectedAssetId,
      fieldOffset,
      fieldOffset === 0 ? undefined : snapshotRef.current?.providerSourceVersion,
      fieldOffset === 0 ? undefined : snapshotRef.current?.projectionSourceVersion,
      controller.signal,
    )
      .then((detail) => {
        if (!active) return
        if (fieldOffset === 0) {
          snapshotRef.current = {
            providerSourceVersion: detail.source_version,
            projectionSourceVersion: detail.projection_source_version,
          }
        }
        setSelectedAssetDetail(detail)
      })
      .catch((error: unknown) => {
        if (active && !controller.signal.aborted) setDetailError(error)
      })
      .finally(() => { if (active) setLoadingDetail(false) })
    return () => { active = false; controller.abort() }
  }, [client, fieldOffset, selectedAssetId])

  return (
    <section className="registration-page">
      <PageTitle
        icon="RG"
        eyebrow="Governed registration"
        title="데이터 등록"
        description="단건 검토와 대량 업로드를 분리하고, 모든 변경은 권한 검사와 변경관리 승인을 거칩니다."
      />
      {capabilityError ? (
        <>
          <GovernedUnavailable
            title="등록 권한을 확인할 수 없습니다"
            description="서버에서 현재 세션의 등록 운영자 자격을 확인하지 못했습니다. 권한 확인 전에는 조회·업로드·저장 기능을 제공하지 않습니다."
          />
          <ErrorNotice error={capabilityError} />
        </>
      ) : !capability ? (
        <p role="status">등록 권한 확인 중…</p>
      ) : !capability.eligible ? (
        <GovernedUnavailable
          title="등록 작업 권한이 없습니다"
          description="활성 상태의 Admin 또는 Data Steward만 Manual/Bulk 등록과 변경요청 생성을 수행할 수 있습니다."
        />
      ) : (
        <>
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
              setSelectedAssetDetail(undefined)
              setSelectedAssetId(assetId)
              setFieldOffset(0)
              snapshotRef.current = undefined
            }}
          />
          <div>
            <RegistrationManualWorkbench
              client={client}
              asset={selectedAssetDetail}
              loading={loadingDetail}

              onClose={() => setSelectedAssetId(undefined)}
              onPreviousFieldPage={() => {
                setFieldOffset((current) => Math.max(0, current - MANUAL_FIELD_PAGE_SIZE))
              }}
              onNextFieldPage={() => {
                setFieldOffset((current) => current + MANUAL_FIELD_PAGE_SIZE)
              }}
            />
            <ErrorNotice error={detailError} />
          </div>
        </div>
      ) : (
        <div id="registration-bulk-panel" role="tabpanel" aria-labelledby="registration-bulk-tab">
          <RegistrationBulkWorkbench client={client} />
        </div>
      )}
        </>
      )}
    </section>
  )
}
