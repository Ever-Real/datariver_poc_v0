import { useEffect, useState } from 'react'
import { FileStack, LockKeyhole, PencilLine, UploadCloud } from 'lucide-react'
import type { ApiClient } from '../../api/client'
import { PageTitle } from '../../components/layout/PageTitle'
import { CatalogDetailPane } from '../catalog/CatalogDetailPane'
import { CatalogResourceTree } from '../catalog/CatalogResourceTree'
import { RegistrationBulkWorkbench } from './RegistrationBulkWorkbench'

type RegistrationMode = 'MANUAL' | 'BULK'

export function RegistrationPage({ client }: { client: ApiClient }) {
  const [mode, setMode] = useState<RegistrationMode>('MANUAL')
  const [selectedAssetId, setSelectedAssetId] = useState<string>()

  useEffect(() => setSelectedAssetId(undefined), [client])

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
        ><PencilLine size={15} />MANUAL <small>단건 검토</small></button>
        <button
          type="button"
          role="tab"
          id="registration-bulk-tab"
          aria-controls="registration-bulk-panel"
          aria-selected={mode === 'BULK'}
          tabIndex={mode === 'BULK' ? 0 : -1}
          className={mode === 'BULK' ? 'active' : ''}
          onClick={() => setMode('BULK')}
        ><UploadCloud size={15} />BULK <small>일괄 등록</small></button>
      </div>

      {mode === 'MANUAL' ? (
        <div className="registration-manual-workbench" id="registration-manual-panel" role="tabpanel" aria-labelledby="registration-manual-tab">
          <CatalogResourceTree
            client={client}
            query=""
            selectedAssetId={selectedAssetId}
            onSelectAsset={setSelectedAssetId}
          />
          <main className="registration-editor-panel panel">
            <header>
              <div><span className="eyebrow">Manual workbench</span><h2>메타데이터 검토</h2></div>
              <span className="badge badge-soft"><LockKeyhole size={11} />READ ONLY</span>
            </header>
            <div className="registration-editor-intro">
              <FileStack size={22} aria-hidden="true" />
              <div>
                <strong>권한 범위의 자산을 선택하세요.</strong>
                <p>현재 화면에서는 설명·컬럼·태그와 bounded lineage를 확인할 수 있습니다.</p>
              </div>
            </div>
            <p className="notice registration-typed-api-notice">
              단건 편집은 typed metadata API와 검증 규칙이 연결될 때까지 잠겨 있습니다.
              원시 Aspect JSON을 브라우저에서 직접 쓰지 않습니다.
            </p>
            {selectedAssetId ? (
              <CatalogDetailPane
                client={client}
                assetId={selectedAssetId}
                onClose={() => setSelectedAssetId(undefined)}
              />
            ) : (
              <div className="registration-empty-editor">왼쪽 Resource Tree에서 테이블을 선택하면 현재 검증된 projection을 표시합니다.</div>
            )}
          </main>
        </div>
      ) : (
        <div id="registration-bulk-panel" role="tabpanel" aria-labelledby="registration-bulk-tab">
          <RegistrationBulkWorkbench client={client} />
        </div>
      )}
    </section>
  )
}
