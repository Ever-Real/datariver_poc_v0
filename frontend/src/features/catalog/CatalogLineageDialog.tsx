import { ExternalLink } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { ApiClient } from '../../api/client'
import type { CatalogDataHubEmbed } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { Dialog } from '../../components/common/Dialog'

export function CatalogLineageDialog({
  client,
  assetId,
  onClose,
}: {
  client: ApiClient
  assetId?: string
  onClose: () => void
}) {
  const [embed, setEmbed] = useState<CatalogDataHubEmbed>()
  const [error, setError] = useState<unknown>()

  useEffect(() => {
    if (!assetId) return
    const controller = new AbortController()
    setEmbed(undefined)
    setError(undefined)
    void client.request<CatalogDataHubEmbed>(`/catalog/assets/${assetId}/datahub-lineage-embed`, {
      signal: controller.signal,
    }).then((value) => {
      if (!controller.signal.aborted) setEmbed(value)
    }).catch((next: unknown) => {
      if (!controller.signal.aborted) setError(next)
    })
    return () => controller.abort()
  }, [assetId, client])

  const url = embed?.state === 'AVAILABLE' ? embed.url : undefined
  return (
    <Dialog
      description="선택한 자산에 대해 서버가 권한을 확인한 실제 DataHub Lineage 화면입니다. DataRiver 인증정보나 DataHub 서비스 토큰은 브라우저에 전달하지 않습니다."
      onRequestClose={onClose}
      open={Boolean(assetId)}
      size="workspace"
      title="DataHub System Lineage"
    >
      <div className="datahub-lineage-dialog">
        {!embed && !error && <p className="catalog-detail-state">DataHub 표시 권한을 확인하는 중입니다.</p>}
        <ErrorNotice error={error} />
        {embed?.state === 'UNAVAILABLE' && <p className="catalog-detail-state">{embed.reason_code === 'DISABLED' ? '이 환경에서는 실제 DataHub Lineage 화면 연결이 활성화되어 있지 않습니다.' : '이 환경에 허용된 DataHub 화면 origin이 설정되지 않았습니다.'}</p>}
        {url && <>
          <iframe className="datahub-lineage-frame" referrerPolicy="no-referrer" sandbox="allow-forms allow-same-origin allow-scripts" src={url} title="DataHub System Lineage" />
          <a className="button button-secondary datahub-lineage-external" href={url} rel="noopener noreferrer" target="_blank"><ExternalLink size={13} />새 탭에서 DataHub 열기</a>
        </>}
      </div>
    </Dialog>
  )
}
