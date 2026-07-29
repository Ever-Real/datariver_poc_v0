import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from '@tanstack/react-table'
import { Check, Pencil, Plus, Trash2, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ApiClient } from '../../../../api/client'
import { Dialog } from '../../../../components/common/Dialog'
import {
  createKnowledgeStudioManagedDomain,
  deleteKnowledgeStudioManagedDomain,
  listKnowledgeStudioManagedDomains,
  newKnowledgeStudioIdempotencyKey,
  updateKnowledgeStudioManagedDomain,
  type KnowledgeStudioManagedDomain,
} from '../knowledgeStudioApi'

interface DomainManagementDialogProps {
  client: ApiClient
  open: boolean
  onRequestClose: () => void
  onChanged: (selected?: KnowledgeStudioManagedDomain, archivedId?: string) => void
}

const columnHelper = createColumnHelper<KnowledgeStudioManagedDomain>()

interface DomainNameCellProps {
  domain: KnowledgeStudioManagedDomain
  editing: boolean
  disabled: boolean
  onSave: (domain: KnowledgeStudioManagedDomain, name: string) => Promise<void>
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

export function DomainManagementDialog({
  client,
  open,
  onRequestClose,
  onChanged,
}: DomainManagementDialogProps) {
  const [items, setItems] = useState<KnowledgeStudioManagedDomain[]>([])
  const [newName, setNewName] = useState('')
  const [editingId, setEditingId] = useState('')
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')

  const load = useCallback(async () => {
    setBusy(true)
    try {
      setItems(await listKnowledgeStudioManagedDomains(client))
      setStatus('')
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '도메인 목록을 불러오지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }, [client])

  useEffect(() => {
    if (open) void load()
  }, [load, open])

  const createDomain = async () => {
    const name = newName.trim()
    if (!name || busy) return
    setBusy(true)
    try {
      const created = await createKnowledgeStudioManagedDomain(
        client,
        name,
        newKnowledgeStudioIdempotencyKey(),
      )
      setItems((current) => [...current, created].sort(compareDomains))
      setNewName('')
      setStatus(`'${created.display_name}' 도메인을 등록했습니다.`)
      onChanged(created)
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '도메인을 등록하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  const saveDomain = useCallback(async (
    domain: KnowledgeStudioManagedDomain,
    rawName: string,
  ) => {
    const name = rawName.trim()
    if (!name || name === domain.display_name) {
      setEditingId('')
      return
    }
    setBusy(true)
    try {
      const updated = await updateKnowledgeStudioManagedDomain(
        client,
        domain.id,
        name,
        domain.version,
        newKnowledgeStudioIdempotencyKey(),
      )
      setItems((current) => (
        current.map((item) => item.id === updated.id ? updated : item).sort(compareDomains)
      ))
      setEditingId('')
      setStatus(`'${updated.display_name}' 도메인을 수정했습니다.`)
      onChanged(updated)
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '도메인을 수정하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }, [client, onChanged])

  const archiveDomain = useCallback(async (domain: KnowledgeStudioManagedDomain) => {
    if (
      !window.confirm(`'${domain.display_name}' 도메인을 삭제(비활성화)하시겠습니까?`)
    ) return
    setBusy(true)
    try {
      await deleteKnowledgeStudioManagedDomain(
        client,
        domain.id,
        domain.version,
        newKnowledgeStudioIdempotencyKey(),
      )
      setItems((current) => current.filter((item) => item.id !== domain.id))
      setStatus(`'${domain.display_name}' 도메인을 비활성화했습니다.`)
      onChanged(undefined, domain.id)
    } catch (error) {
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
      cell: ({ getValue }) => (
        <span className="text-[10px] text-slate-600">{getValue() ?? 'SYSTEM'}</span>
      ),
    }),
    columnHelper.accessor('asset_count', {
      header: '소속 Asset',
      cell: ({ getValue }) => <span className="font-bold">{getValue()}</span>,
    }),
    columnHelper.accessor('created_at', {
      header: '생성일',
      cell: ({ getValue }) => (
        <time className="whitespace-nowrap text-[10px] text-slate-600">
          {new Date(getValue()).toLocaleDateString('ko-KR')}
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
            disabled={busy}
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
            disabled={busy}
            onClick={() => void archiveDomain(row.original)}
          >
            <Trash2 size={13} />
          </button>
        </div>
      ),
    }),
  ], [archiveDomain, busy, editingId, saveDomain])

  // TanStack Table owns mutable table methods; React Compiler must not memoize this hook.
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: items,
    columns,
    getCoreRowModel: getCoreRowModel(),
  })

  return (
    <Dialog
      open={open}
      title="도메인 관리"
      description="Workspace의 등록된 업무 도메인을 관리합니다. 삭제는 기존 Asset 참조를 보존하는 비활성화입니다."
      onRequestClose={() => {
        if (!busy) onRequestClose()
      }}
      footer={(
        <button type="button" className="button" disabled={busy} onClick={onRequestClose}>
          닫기
        </button>
      )}
    >
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
            {!busy && items.length === 0 && (
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
        {busy ? '처리 중…' : status}
      </p>
    </Dialog>
  )
}

function compareDomains(
  left: KnowledgeStudioManagedDomain,
  right: KnowledgeStudioManagedDomain,
): number {
  return left.display_name.localeCompare(right.display_name, 'ko')
}
