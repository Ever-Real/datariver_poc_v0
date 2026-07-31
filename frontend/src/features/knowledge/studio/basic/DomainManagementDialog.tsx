import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from '@tanstack/react-table'
import { Check, Pencil, Plus, Trash2, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ApiClient } from '../../../../api/client'
import type { KnowledgeAssetPage } from '../../../../api/types'
import { AssuranceNotice } from '../../../../components/AssuranceNotice'
import { Dialog } from '../../../../components/common/Dialog'
import { listKnowledgeAssetsByDomain } from '../../knowledgeRegistryApi'
import {
  createKnowledgeStudioManagedDomain,
  deleteKnowledgeStudioManagedDomain,
  newKnowledgeStudioIdempotencyKey,
  updateKnowledgeStudioManagedDomain,
  type KnowledgeStudioDomainOption,
  type KnowledgeStudioManagedDomain,
} from '../knowledgeStudioApi'

interface DomainManagementPanelProps {
  client: ApiClient
  items: KnowledgeStudioDomainOption[]
  loading: boolean
  onChanged: (
    selected?: KnowledgeStudioManagedDomain,
    archivedId?: string,
  ) => Promise<void>
  onStepUp?: () => Promise<void>
  onPasswordReauth?: () => Promise<void>
  onEnroll?: () => Promise<void>
  hardwareWebauthnEnabled?: boolean
}

interface DomainManagementDialogProps extends DomainManagementPanelProps {
  open: boolean
  onRequestClose: () => void
}

const columnHelper = createColumnHelper<KnowledgeStudioDomainOption>()

function activeReleaseLabel(asset: KnowledgeAssetPage['items'][number]): string {
  const labels = []
  if (asset.active_studio_release_no !== null) {
    labels.push(`T-Box v${asset.active_studio_release_no}`)
  }
  if (asset.active_release_no !== null) {
    labels.push(`A-Box v${asset.active_release_no}`)
  }
  return labels.join(' / ') || '—'
}

function DomainAssetDrilldown({
  client,
  domain,
  onRequestClose,
}: {
  client: ApiClient
  domain: KnowledgeStudioDomainOption
  onRequestClose: () => void
}) {
  const [page, setPage] = useState<KnowledgeAssetPage>()
  const [cursor, setCursor] = useState<string | null>(null)
  const [cursorHistory, setCursorHistory] = useState<Array<string | null>>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError('')
    setPage(undefined)
    void listKnowledgeAssetsByDomain(client, domain.id, cursor, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setPage(result)
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) {
          setError(caught instanceof Error
            ? caught.message
            : '도메인 Asset 목록을 불러오지 못했습니다.')
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [client, cursor, domain.id])

  const previousPage = () => {
    if (cursorHistory.length === 0) return
    setCursor(cursorHistory[cursorHistory.length - 1] ?? null)
    setCursorHistory((current) => current.slice(0, -1))
  }
  const nextPage = () => {
    if (!page?.next_cursor) return
    setCursorHistory((current) => [...current, cursor])
    setCursor(page.next_cursor)
  }

  return (
    <Dialog
      open
      size="large"
      compactHeight
      title={`${domain.display_name} · 조회 가능 Asset`}
      description="관리 정본의 소속 Asset 수와 별개로, 현재 사용자의 KG_READ·등급·도메인 권한 범위에 있는 활성 Asset만 표시합니다."
      onRequestClose={onRequestClose}
      footer={(
        <>
          <button
            type="button"
            className="button button-secondary"
            disabled={loading || cursorHistory.length === 0}
            onClick={previousPage}
          >
            이전
          </button>
          <button
            type="button"
            className="button button-secondary"
            disabled={loading || !page?.next_cursor}
            onClick={nextPage}
          >
            다음
          </button>
          <button type="button" className="button" onClick={onRequestClose}>닫기</button>
        </>
      )}
    >
      {loading ? (
        <p role="status" className="m-0 text-xs text-slate-600">
          서버 권한 범위에서 Asset을 조회하는 중입니다.
        </p>
      ) : error ? (
        <section role="alert" className="rounded-enterprise border border-red-200 bg-red-50 p-4 text-xs text-red-800">
          <strong className="block text-sm">도메인 Asset 조회를 사용할 수 없습니다.</strong>
          <p className="mb-0 mt-1">{error}</p>
        </section>
      ) : (
        <div className="max-h-[48vh] overflow-auto rounded-enterprise border border-slate-200">
          <table className="w-full border-collapse text-left text-xs">
            <thead className="sticky top-0 bg-slate-100">
              <tr>
                {['Asset', '상태', '등급', '활성 Release'].map((label) => (
                  <th key={label} className="border-b border-slate-200 px-3 py-2 text-[9px] font-black tracking-wide text-slate-500 uppercase">
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {page?.items.map((asset) => (
                <tr key={asset.id} className="border-b border-slate-100 last:border-0">
                  <td className="px-3 py-2">
                    <strong className="block text-navy-900">{asset.name}</strong>
                    <small className="text-[9px] text-slate-400">{asset.slug}</small>
                  </td>
                  <td className="px-3 py-2">{asset.status}</td>
                  <td className="px-3 py-2">{asset.classification}</td>
                  <td className="px-3 py-2">{activeReleaseLabel(asset)}</td>
                </tr>
              ))}
              {page?.items.length === 0 && (
                <tr>
                  <td colSpan={4} className="p-8 text-center text-xs text-slate-500">
                    현재 조회 권한 범위에 표시할 활성 Asset이 없습니다.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </Dialog>
  )
}

interface DomainNameCellProps {
  domain: KnowledgeStudioDomainOption
  editing: boolean
  disabled: boolean
  onSave: (domain: KnowledgeStudioDomainOption, name: string) => Promise<void>
  onCancel: () => void
}

function DomainNameCell({
  domain,
  editing,
  disabled,
  onSave,
  onCancel,
}: DomainNameCellProps) {
  const [name, setName] = useState(domain.display_name)

  useEffect(() => setName(domain.display_name), [domain.display_name, editing])

  if (!editing) {
    return <strong className="text-xs text-navy-900">{domain.display_name}</strong>
  }
  return (
    <div className="flex min-w-48 gap-1">
      <input
        autoFocus
        aria-label={`${domain.display_name} 도메인명 수정`}
        className="input min-w-0 flex-1 py-1 text-xs"
        value={name}
        maxLength={200}
        disabled={disabled}
        onChange={(event) => setName(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault()
            void onSave(domain, name)
          } else if (event.key === 'Escape') {
            onCancel()
          }
        }}
      />
      <button
        type="button"
        className="rounded p-1 text-emerald-700"
        aria-label={`${domain.display_name} 도메인 수정 저장`}
        disabled={disabled || !name.trim()}
        onClick={() => void onSave(domain, name)}
      >
        <Check size={13} />
      </button>
      <button
        type="button"
        className="rounded p-1 text-slate-500"
        aria-label={`${domain.display_name} 도메인 수정 취소`}
        disabled={disabled}
        onClick={onCancel}
      >
        <X size={13} />
      </button>
    </div>
  )
}

export function DomainManagementPanel({
  client,
  items,
  loading,
  onChanged,
  onStepUp,
  onPasswordReauth,
  onEnroll,
  hardwareWebauthnEnabled,
}: DomainManagementPanelProps) {
  const [newName, setNewName] = useState('')
  const [editingId, setEditingId] = useState('')
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  const [managementError, setManagementError] = useState<unknown>()
  const [assetDomain, setAssetDomain] = useState<KnowledgeStudioDomainOption>()

  const createDomain = async () => {
    const name = newName.trim()
    if (!name || busy) return
    setBusy(true)
    setManagementError(undefined)
    try {
      const created = await createKnowledgeStudioManagedDomain(
        client,
        name,
        newKnowledgeStudioIdempotencyKey(),
      )
      await onChanged(created)
      setNewName('')
      setStatus(`'${created.display_name}' 도메인을 등록했습니다.`)
    } catch (error) {
      setManagementError(error)
      setStatus(error instanceof Error ? error.message : '도메인을 등록하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  const saveDomain = useCallback(async (
    domain: KnowledgeStudioDomainOption,
    rawName: string,
  ) => {
    const name = rawName.trim()
    if (!name || name === domain.display_name) {
      setEditingId('')
      return
    }
    if (!domain.managed || domain.version === undefined) {
      setStatus('외부에서 동기화된 도메인은 DataRiver Studio에서 수정할 수 없습니다.')
      return
    }
    setBusy(true)
    setManagementError(undefined)
    try {
      const updated = await updateKnowledgeStudioManagedDomain(
        client,
        domain.id,
        name,
        domain.version,
        newKnowledgeStudioIdempotencyKey(),
      )
      await onChanged(updated)
      setEditingId('')
      setStatus(`'${updated.display_name}' 도메인을 수정했습니다.`)
    } catch (error) {
      setManagementError(error)
      setStatus(error instanceof Error ? error.message : '도메인을 수정하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }, [client, onChanged])

  const archiveDomain = useCallback(async (domain: KnowledgeStudioDomainOption) => {
    if (!domain.managed || domain.version === undefined) {
      setStatus('외부에서 동기화된 도메인은 DataRiver Studio에서 비활성화할 수 없습니다.')
      return
    }
    if (
      !window.confirm(`'${domain.display_name}' 도메인을 삭제(비활성화)하시겠습니까?`)
    ) return
    setBusy(true)
    setManagementError(undefined)
    try {
      await deleteKnowledgeStudioManagedDomain(
        client,
        domain.id,
        domain.version,
        newKnowledgeStudioIdempotencyKey(),
      )
      await onChanged(undefined, domain.id)
      setStatus(`'${domain.display_name}' 도메인을 비활성화했습니다.`)
    } catch (error) {
      setManagementError(error)
      setStatus(error instanceof Error ? error.message : '도메인을 삭제하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }, [client, onChanged])

  const columns = useMemo(() => [
    columnHelper.accessor('display_name', {
      header: '도메인명',
      cell: ({ row }) => (
        <DomainNameCell
          domain={row.original}
          editing={editingId === row.original.id}
          disabled={busy}
          onSave={saveDomain}
          onCancel={() => setEditingId('')}
        />
      ),
    }),
    columnHelper.accessor('created_by', {
      header: '생성자',
      cell: ({ row }) => {
        const domain = row.original
        const creator = domain.creator_display_name
          ?? domain.creator_email
          ?? (domain.created_by ? '사용자 정보 없음' : 'SYSTEM')
        return (
          <span
            className="grid text-[10px] text-slate-600"
            title={domain.creator_email}
          >
            <span>{creator}</span>
            {domain.creator_display_name && domain.creator_email && (
              <small className="text-[9px] text-slate-400">{domain.creator_email}</small>
            )}
          </span>
        )
      },
    }),
    columnHelper.accessor('asset_count', {
      header: '소속 Asset (관리 정본)',
      cell: ({ getValue, row }) => (
        <button
          type="button"
          className="font-bold text-enterprise-blue underline decoration-dotted underline-offset-2"
          aria-label={`${row.original.display_name} 도메인의 조회 가능 Asset 보기`}
          onClick={() => setAssetDomain(row.original)}
        >
          {getValue() ?? '—'}
        </button>
      ),
    }),
    columnHelper.accessor('created_at', {
      header: '생성일',
      cell: ({ getValue }) => (
        <time className="whitespace-nowrap text-[10px] text-slate-600">
          {getValue() ? new Date(getValue()!).toLocaleDateString('ko-KR') : '—'}
        </time>
      ),
    }),
    columnHelper.display({
      id: 'actions',
      header: '작업',
      cell: ({ row }) => (
        <div className="flex gap-1">
          <button
            type="button"
            className="rounded p-1 text-enterprise-blue hover:bg-blue-50"
            aria-label={`${row.original.display_name} 도메인 수정`}
            disabled={busy || !row.original.managed || row.original.version === undefined}
            onClick={() => {
              setEditingId(row.original.id)
            }}
          >
            <Pencil size={13} />
          </button>
          <button
            type="button"
            className="rounded p-1 text-red-700 hover:bg-red-50"
            aria-label={`${row.original.display_name} 도메인 삭제`}
            disabled={busy || !row.original.managed || row.original.version === undefined}
            onClick={() => void archiveDomain(row.original)}
          >
            <Trash2 size={13} />
          </button>
        </div>
      ),
    }),
  ], [archiveDomain, busy, editingId, saveDomain])
  const tableData = useMemo(
    () => [...items].sort(compareDomains),
    [items],
  )

  // TanStack Table owns mutable table methods; React Compiler must not memoize this hook.
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: tableData,
    columns,
    getCoreRowModel: getCoreRowModel(),
  })

  return (
    <>
      <section aria-label="업무 도메인 관리" className="grid gap-3">
      <form
        className="mb-3 flex gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          void createDomain()
        }}
      >
        <input
          aria-label="새 도메인명"
          className="input min-w-0 flex-1"
          value={newName}
          maxLength={200}
          placeholder="새 업무 도메인"
          disabled={busy}
          onChange={(event) => setNewName(event.target.value)}
        />
        <button type="submit" className="button" disabled={busy || !newName.trim()}>
          <Plus size={13} /> 추가
        </button>
      </form>
      <div className="max-h-[52vh] overflow-auto rounded-enterprise border border-slate-200">
        <table className="w-full border-collapse text-left text-xs">
          <thead className="sticky top-0 bg-slate-100">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th key={header.id} className="border-b border-slate-200 px-3 py-2 text-[9px] font-black tracking-wide text-slate-500 uppercase">
                    {header.isPlaceholder
                      ? null
                      : flexRender(header.column.columnDef.header, header.getContext())}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} className="border-b border-slate-100 last:border-0">
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="px-3 py-2">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
            {!busy && !loading && items.length === 0 && (
              <tr>
                <td colSpan={5} className="p-8 text-center text-xs text-slate-500">
                  등록된 도메인이 없습니다.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <p role="status" className="mb-0 mt-3 min-h-5 text-xs text-slate-600">
        {busy || loading ? 'PostgreSQL 도메인 정본을 동기화하는 중…' : status}
      </p>
      {managementError !== undefined && onStepUp && onPasswordReauth && onEnroll && (
        <AssuranceNotice
          error={managementError}
          requiredAssurance="PASSWORD"
          onStepUp={onStepUp}
          onPasswordReauth={onPasswordReauth}
          onEnroll={onEnroll}
          hardwareWebauthnEnabled={hardwareWebauthnEnabled}
        />
      )}
      </section>
      {assetDomain && (
        <DomainAssetDrilldown
          client={client}
          domain={assetDomain}
          onRequestClose={() => setAssetDomain(undefined)}
        />
      )}
    </>
  )
}

export function DomainManagementDialog({
  client,
  open,
  items,
  loading,
  onRequestClose,
  onChanged,
  onStepUp,
  onPasswordReauth,
  onEnroll,
  hardwareWebauthnEnabled,
}: DomainManagementDialogProps) {
  return (
    <Dialog
      open={open}
      title="도메인 관리"
      description="Workspace의 등록된 업무 도메인을 관리합니다. 삭제는 기존 Asset 참조를 보존하는 비활성화입니다."
      onRequestClose={onRequestClose}
      footer={(
        <button type="button" className="button" onClick={onRequestClose}>
          닫기
        </button>
      )}
    >
      <DomainManagementPanel
        client={client}
        items={items}
        loading={loading}
        onChanged={onChanged}
        onStepUp={onStepUp}
        onPasswordReauth={onPasswordReauth}
        onEnroll={onEnroll}
        hardwareWebauthnEnabled={hardwareWebauthnEnabled}
      />
    </Dialog>
  )
}

function compareDomains(
  left: KnowledgeStudioDomainOption,
  right: KnowledgeStudioDomainOption,
): number {
  return left.display_name.localeCompare(right.display_name, 'ko')
}
