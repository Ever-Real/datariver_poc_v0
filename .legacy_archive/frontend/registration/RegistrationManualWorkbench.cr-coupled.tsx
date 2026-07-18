import { useEffect, useMemo, useState } from 'react'
import { Columns3, Database, FilePenLine, ShieldCheck, Tags } from 'lucide-react'
import type { ApiClient } from '../../../frontend/src/api/client'
import type { CatalogAssetDetail } from '../../../frontend/src/api/types'
import { RegistrationColumnDescriptionEditor, schemaDescriptionFields } from '../../../frontend/src/features/registration/RegistrationColumnDescriptionEditor'
import { RegistrationControlledMetadataEditor } from '../../../frontend/src/features/registration/RegistrationControlledMetadataEditor'
import { RegistrationDescriptionEditor } from '../../../frontend/src/features/registration/RegistrationDescriptionEditor'

interface RegistrationManualWorkbenchProps {
  client: ApiClient
  asset?: CatalogAssetDetail
  loading: boolean
  onClose: () => void
}

function fieldText(field: Record<string, unknown>, ...keys: string[]): string {
  for (const key of keys) {
    const value = field[key]
    if (typeof value === 'string' && value.trim()) return value
  }
  return '—'
}

function compactList(value: unknown): string {
  if (!Array.isArray(value)) return '—'
  const labels = value.flatMap((item) => {
    if (typeof item === 'string' && item.trim()) return [item]
    if (item && typeof item === 'object') return [fieldText(item as Record<string, unknown>, 'name', 'urn')]
    return []
  }).filter((item) => item !== '—')
  return labels.join(', ') || '—'
}

export function RegistrationManualWorkbench({ client, asset, loading, onClose }: RegistrationManualWorkbenchProps) {
  const [editor, setEditor] = useState<'DESCRIPTION' | 'COLUMN' | 'CONTROLLED'>()

  useEffect(() => { setEditor(undefined) }, [asset?.id])
  const columns = useMemo(() => (asset ? schemaDescriptionFields(asset.schema_fields) : []), [asset])

  return (
    <main className="registration-editor-panel panel" aria-busy={loading}>
      <header><div><span className="eyebrow">Manual workbench</span><h2>Metadata Registration</h2></div><span className="badge badge-soft"><ShieldCheck size={11} />GOVERNED</span></header>
      {loading && <div className="registration-empty-editor">선택한 자산의 검증된 메타데이터를 불러오는 중입니다.</div>}
      {!loading && !asset && <div className="registration-empty-editor registration-v03-empty"><Database size={31} aria-hidden="true" /><strong>Resource Tree에서 테이블을 선택하세요.</strong><span>선택한 테이블의 속성과 컬럼 스키마를 같은 화면에서 검토합니다.</span></div>}
      {!loading && asset && <div className="registration-v03-body">
        <section className="registration-v03-properties" aria-labelledby="manual-properties-title">
          <header><div><Database size={14} aria-hidden="true" /><h3 id="manual-properties-title">Table Properties</h3></div><button className="button button-quiet" type="button" onClick={onClose}>선택 해제</button></header>
          <div className="dense-table-frame"><table className="dense-table registration-properties-table"><thead><tr><th>Platform</th><th>Database</th><th>Schema</th><th>Table Name</th><th>Domain</th><th>Description</th><th>Term</th><th>Tag</th></tr></thead><tbody><tr>
            <td>{asset.platform ?? '—'}</td><td>{asset.database_name ?? '—'}</td><td>{asset.schema_name ?? '—'}</td><td><strong>{asset.name}</strong><small>{asset.asset_type}</small></td><td>{asset.domain ?? '—'}</td>
            <td className="registration-description-cell"><span>{asset.description || '—'}</span><button type="button" title="설명 변경" onClick={() => setEditor('DESCRIPTION')}><FilePenLine size={13} aria-hidden="true" />변경 제안</button></td><td>{compactList(asset.terms ?? asset.glossary_terms)}</td><td>{compactList(asset.tags)}</td>
          </tr></tbody></table></div>
          <div className="registration-v03-actions" role="group" aria-label="메타데이터 변경 제안"><button className="button button-secondary" type="button" onClick={() => setEditor('DESCRIPTION')}><FilePenLine size={13} aria-hidden="true" />설명 변경</button><button className="button button-secondary" type="button" onClick={() => setEditor('CONTROLLED')}><Tags size={13} aria-hidden="true" />Domain · Term · Tag 제안</button></div>
        </section>
        <section className="registration-v03-columns" aria-labelledby="manual-columns-title"><header><span aria-hidden="true" /><h3 id="manual-columns-title"><Columns3 size={14} aria-hidden="true" />Column Schema Specifications</h3></header><div className="dense-table-frame"><table className="dense-table registration-columns-table"><thead><tr><th>Column Name</th><th>Type</th><th>Logical Name / Description</th><th>Term</th><th>Tag</th><th>Action</th></tr></thead><tbody>{columns.length ? columns.map((column) => { const source = asset.schema_fields.find((field) => field.fieldPath === column.fieldPath) ?? {}; return <tr key={column.fieldPath}><td><code>{column.fieldPath}</code></td><td>{column.dataType ?? '—'}</td><td>{column.description || '—'}</td><td>{compactList(source.glossaryTerms)}</td><td>{compactList(source.tags)}</td><td><button className="button button-quiet" type="button" onClick={() => setEditor('COLUMN')}>변경 제안</button></td></tr> }) : <tr><td colSpan={6} className="empty-cell">DataHub가 반환한 컬럼 메타데이터가 없습니다.</td></tr>}</tbody></table></div></section>
        {editor === 'DESCRIPTION' && <RegistrationDescriptionEditor client={client} asset={asset} />}
        {editor === 'COLUMN' && <RegistrationColumnDescriptionEditor client={client} asset={asset} />}
        {editor === 'CONTROLLED' && <RegistrationControlledMetadataEditor client={client} asset={asset} />}
      </div>}
    </main>
  )
}
