import { useEffect, useMemo, useRef, useState } from 'react'
import { Download } from 'lucide-react'
import { newIdempotencyKey } from '../../api/client'
import type {
  CatalogExportCreateRequest,
  CatalogExportCreateResponse,
  CatalogExportStatus,
  Classification,
} from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { CatalogExportApi } from './catalogExportApi'
import type { ApiClient } from '../../api/client'

const pendingStates = new Set(['QUEUED', 'RUNNING', 'RETRY_WAIT'])

const stateLabels: Record<string, string> = {
  QUEUED: '대기 중',
  RUNNING: '생성 중',
  RETRY_WAIT: '재시도 대기',
  COMPLETED: '완료',
  FAILED: '실패',
}

type ExportRecord = CatalogExportCreateResponse | CatalogExportStatus

interface CatalogExportControlProps {
  client: ApiClient
  workerEnabled: boolean
  query: string
  assetType?: string
  platform?: string
  databaseName?: string
  schemaName?: string
  domain?: string
  searchFields?: string[]
  classification?: Classification
  lifecycle?: 'ACTIVE'
  compact?: boolean
  disabled?: boolean
  navigate?: (url: string) => void
  pollMilliseconds?: number
}

export function CatalogExportControl({
  client,
  workerEnabled,
  query,
  assetType,
  platform,
  databaseName,
  schemaName,
  domain,
  searchFields,
  classification,
  lifecycle,
  compact = false,
  disabled = false,
  navigate = (url) => window.location.assign(url),
  pollMilliseconds = 1_500,
}: CatalogExportControlProps) {
  const api = useMemo(() => new CatalogExportApi(client), [client])
  const [record, setRecord] = useState<ExportRecord>()
  const [exportFormat, setExportFormat] = useState<'CSV' | 'XLSX'>('CSV')
  const [artifactFormat, setArtifactFormat] = useState<'CSV' | 'XLSX'>('CSV')
  const [creating, setCreating] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [error, setError] = useState<unknown>()
  const boundaryGeneration = useRef(0)
  const restricted = classification === 'RESTRICTED'
  const pending = record ? pendingStates.has(record.state) : false

  useEffect(() => {
    boundaryGeneration.current += 1
    setRecord(undefined)
    setArtifactFormat('CSV')
    setCreating(false)
    setDownloading(false)
    setError(undefined)
  }, [assetType, classification, client, databaseName, disabled, domain, lifecycle, platform, query, schemaName, searchFields, workerEnabled])

  useEffect(() => {
    if (disabled || !workerEnabled || !record || !pendingStates.has(record.state)) return
    let active = true
    const timer = window.setTimeout(() => {
      void api.get(record.export_id)
        .then((next) => { if (active) setRecord(next) })
        .catch((next: unknown) => { if (active) setError(next) })
    }, pollMilliseconds)
    return () => { active = false; window.clearTimeout(timer) }
  }, [api, disabled, pollMilliseconds, record, workerEnabled])

  const create = async (requestedFormat = exportFormat) => {
    if (disabled || !workerEnabled || restricted || creating || pending) return
    setExportFormat(requestedFormat)
    setCreating(true)
    setError(undefined)
    const generation = boundaryGeneration.current
    const payload: CatalogExportCreateRequest = {
      q: query,
      ...(assetType ? { asset_type: assetType } : {}),
      ...(platform ? { platform } : {}),
      ...(databaseName ? { database_name: databaseName } : {}),
      ...(schemaName ? { schema_name: schemaName } : {}),
      ...(domain ? { domain } : {}),
      ...(searchFields?.length ? { search_fields: searchFields.join(',') } : {}),
      ...(classification ? { classification } : {}),
      ...(lifecycle ? { lifecycle } : {}),
      sort: 'NAME_ASC',
      format: requestedFormat,
    }
    try {
      const created = await api.create(payload, newIdempotencyKey('catalog-export'))
      if (generation === boundaryGeneration.current) {
        setArtifactFormat(requestedFormat)
        setRecord(created)
      }
    } catch (next) {
      if (generation === boundaryGeneration.current) setError(next)
    } finally {
      if (generation === boundaryGeneration.current) setCreating(false)
    }
  }

  const download = async () => {
    if (disabled || !workerEnabled || !record || record.state !== 'COMPLETED' || downloading) return
    setDownloading(true)
    setError(undefined)
    const generation = boundaryGeneration.current
    try {
      const response = await api.download(record.export_id)
      if (generation === boundaryGeneration.current) {
        navigate(safeCatalogExportDownloadUrl(response.url))
      }
    } catch (next) {
      if (generation === boundaryGeneration.current) setError(next)
    } finally {
      if (generation === boundaryGeneration.current) setDownloading(false)
    }
  }

  const disabledReason = disabled
    ? '검색 대상을 하나 이상 선택해야 Catalog Export를 사용할 수 있습니다.'
    : !workerEnabled
    ? '관리형 Catalog Export를 사용할 수 없습니다. catalog.export 권한 또는 운영자의 분리된 DB·Object Storage 자격증명과 worker 설정을 확인하세요.'
    : restricted
      ? 'RESTRICTED 자산은 Search 명시 권한과 무관하게 CSV 내보내기와 XLSX 내보내기가 금지됩니다.'
      : '현재 검색 조건과 권한 스냅샷을 서버에서 검증한 뒤 CSV 또는 XLSX를 생성합니다.'

  if (compact) return <section className="catalog-export-control catalog-export-control-compact" aria-label="카탈로그 내보내기">
    <p className="sr-only" id="catalog-export-description">{disabledReason}</p>
    <div className="catalog-export-actions">
      <button type="button" className="button button-secondary" title={disabledReason} aria-describedby="catalog-export-description" disabled={disabled || !workerEnabled || restricted || creating || pending} onClick={() => void create('CSV')}><Download size={13} aria-hidden="true" />{creating && exportFormat === 'CSV' ? '요청 중…' : 'CSV 저장'}</button>
      <button type="button" className="button button-secondary" title={disabledReason} aria-describedby="catalog-export-description" disabled={disabled || !workerEnabled || restricted || creating || pending} onClick={() => void create('XLSX')}><Download size={13} aria-hidden="true" />{creating && exportFormat === 'XLSX' ? '요청 중…' : 'Excel 저장'}</button>
      {!disabled && workerEnabled && record?.state === 'COMPLETED' && <button type="button" className="button" disabled={downloading} onClick={() => void download()}><Download size={13} aria-hidden="true" />{downloading ? 'URL 확인 중…' : `${artifactFormat} 다운로드`}</button>}
    </div>
    {!disabled && workerEnabled && record && <div className="catalog-export-status" role="status" aria-live="polite"><span className={`badge badge-soft export-state-${record.state.toLowerCase()}`}>{stateLabels[record.state] ?? record.state}</span></div>}
    <ErrorNotice error={error} />
  </section>

  return <section className="catalog-export-control" aria-label="카탈로그 내보내기">
    <div>
      <strong>Catalog Export</strong>
      <p id="catalog-export-description">{disabledReason}</p>
    </div>
    {!disabled && workerEnabled && record && <div className="catalog-export-status" role="status" aria-live="polite">
      <span className={`badge badge-soft export-state-${record.state.toLowerCase()}`}>
        {stateLabels[record.state] ?? record.state}
      </span>
      {'row_count' in record && record.row_count != null && <span>{record.row_count.toLocaleString()} rows</span>}
      {'size_bytes' in record && record.size_bytes != null && <span>{formatBytes(record.size_bytes)}</span>}
      {'last_error_code' in record && record.last_error_code && <code>{record.last_error_code}</code>}
    </div>}
    <div className="catalog-export-actions">
      <label className="catalog-export-format">형식<select aria-label="내보내기 형식" value={exportFormat} disabled={disabled || creating || pending} onChange={(event) => setExportFormat(event.target.value as 'CSV' | 'XLSX')}><option value="CSV">CSV</option><option value="XLSX">Excel (.xlsx)</option></select></label>
      <button
        type="button"
        className="button button-secondary"
        aria-describedby="catalog-export-description"
        disabled={disabled || !workerEnabled || restricted || creating || pending}
        onClick={() => void create()}
      >
        <Download size={13} aria-hidden="true" />
        {creating ? '요청 중…' : record?.state === 'COMPLETED' ? `새 ${exportFormat} 생성` : `${exportFormat} 생성`}
      </button>
      {!disabled && workerEnabled && record?.state === 'COMPLETED' && <button
        type="button"
        className="button"
        disabled={downloading}
        onClick={() => void download()}
      >
        <Download size={13} aria-hidden="true" />
        {downloading ? 'URL 확인 중…' : `${artifactFormat} 다운로드`}
      </button>}
    </div>
    <ErrorNotice error={error} />
  </section>
}

export function safeCatalogExportDownloadUrl(value: string): string {
  const url = new URL(value, window.location.origin)
  if (url.protocol !== 'https:' && url.protocol !== 'http:') {
    throw new Error('서버가 허용되지 않은 다운로드 URL을 반환했습니다.')
  }
  return url.href
}

function formatBytes(value: number): string {
  if (value < 1_024) return `${value} B`
  if (value < 1_048_576) return `${(value / 1_024).toFixed(1)} KiB`
  return `${(value / 1_048_576).toFixed(1)} MiB`
}
