import type { ColumnDef } from '@tanstack/react-table'
import { Archive, Pencil, Plus, RefreshCw, Search } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ApiClient } from '../../api/client'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import { Dialog } from '../../components/common/Dialog'
import {
  archiveKnowledgePropertyProfile,
  createKnowledgePropertyProfile,
  listKnowledgePropertyProfiles,
  newKnowledgeStudioIdempotencyKey,
  updateKnowledgePropertyProfile,
  type KnowledgePropertyProfileItem,
  type KnowledgePropertyProfileValues,
} from './studio/knowledgeStudioApi'

interface ProfileEditorProps {
  item: KnowledgePropertyProfileItem
  busy: boolean
  onCancel: () => void
  onSave: (values: KnowledgePropertyProfileValues) => Promise<void>
}

function ProfileEditor({ item, busy, onCancel, onSave }: ProfileEditorProps) {
  const [description, setDescription] = useState(item.profile?.description ?? '')
  const [unit, setUnit] = useState(item.profile?.unit ?? '')
  const [synonyms, setSynonyms] = useState(item.profile?.synonyms.join(', ') ?? '')
  const values = useMemo<KnowledgePropertyProfileValues>(() => ({
    description: description.trim() || undefined,
    unit: unit.trim() || undefined,
    synonyms: [...new Set(
      synonyms
        .split(',')
        .map((value) => value.trim())
        .filter(Boolean),
    )],
  }), [description, synonyms, unit])
  const valid = Boolean(values.description || values.unit || values.synonyms.length > 0)

  return (
    <Dialog
      open
      size="large"
      title={`${item.property_name} Property 프로파일`}
      description={`${item.graph_name} · Release ${item.release_no} · ${item.property_urn}`}
      onRequestClose={() => {
        if (!busy) onCancel()
      }}
      footer={(
        <>
          <button type="button" className="button button-secondary" disabled={busy} onClick={onCancel}>
            취소
          </button>
          <button
            type="button"
            className="button"
            disabled={busy || !valid}
            onClick={() => void onSave(values)}
          >
            {item.profile ? '변경 저장' : '프로파일 생성'}
          </button>
        </>
      )}
    >
      <div className="grid gap-4 md:grid-cols-2">
        <label className="grid gap-1 text-xs font-bold text-slate-700">
          단위
          <input
            autoFocus
            className="input"
            value={unit}
            maxLength={100}
            placeholder="예: kg, ms, °C"
            disabled={busy}
            onChange={(event) => setUnit(event.target.value)}
          />
        </label>
        <label className="grid gap-1 text-xs font-bold text-slate-700">
          동의어
          <input
            className="input"
            value={synonyms}
            maxLength={2_000}
            placeholder="쉼표로 구분: 고객번호, Customer ID"
            disabled={busy}
            onChange={(event) => setSynonyms(event.target.value)}
          />
          <span className="text-[10px] font-medium text-slate-500">
            쉼표 단위로 정규화되며 중복은 제거됩니다. 최대 50개입니다.
          </span>
        </label>
        <label className="grid gap-1 text-xs font-bold text-slate-700 md:col-span-2">
          상세 설명
          <textarea
            className="input min-h-28 resize-y"
            value={description}
            maxLength={2_000}
            placeholder="Property의 업무 의미와 사용 범위를 기록합니다."
            disabled={busy}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
      </div>
    </Dialog>
  )
}

export function KnowledgePropertyProfilePanel({ client }: { client: ApiClient }) {
  const [items, setItems] = useState<KnowledgePropertyProfileItem[]>([])
  const [queryInput, setQueryInput] = useState('')
  const [query, setQuery] = useState('')
  const [editing, setEditing] = useState<KnowledgePropertyProfileItem>()
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const [revision, setRevision] = useState(0)
  const idempotencyAttemptRef = useRef<{ fingerprint: string; key: string } | undefined>(undefined)

  const idempotencyKeyFor = (fingerprint: string): string => {
    const current = idempotencyAttemptRef.current
    if (current?.fingerprint === fingerprint) return current.key
    const next = { fingerprint, key: newKnowledgeStudioIdempotencyKey() }
    idempotencyAttemptRef.current = next
    return next.key
  }

  const reload = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    setError('')
    try {
      const next = await listKnowledgePropertyProfiles(client, query, signal)
      setItems(next)
      setStatus(`활성 Release의 Property ${next.length}건을 조회했습니다.`)
    } catch (caught) {
      if (!signal?.aborted) {
        setError(caught instanceof Error ? caught.message : 'Property 프로파일을 불러오지 못했습니다.')
      }
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [client, query])

  useEffect(() => {
    const controller = new AbortController()
    void reload(controller.signal)
    return () => controller.abort()
  }, [reload, revision])

  const save = async (values: KnowledgePropertyProfileValues) => {
    if (!editing || busy) return
    setBusy(true)
    setError('')
    try {
      if (editing.profile) {
        const fingerprint = JSON.stringify([
          'UPDATE',
          editing.profile.id,
          editing.profile.version,
          values,
        ])
        await updateKnowledgePropertyProfile(
          client,
          editing.profile.id,
          editing.profile.version,
          values,
          idempotencyKeyFor(fingerprint),
        )
      } else {
        const fingerprint = JSON.stringify([
          'CREATE',
          editing.ontology_element_id,
          values,
        ])
        await createKnowledgePropertyProfile(
          client,
          editing.ontology_element_id,
          values,
          idempotencyKeyFor(fingerprint),
        )
      }
      idempotencyAttemptRef.current = undefined
      setEditing(undefined)
      setRevision((current) => current + 1)
      setStatus(`${editing.property_name} 프로파일을 PostgreSQL 정본에 저장했습니다.`)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Property 프로파일을 저장하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  const archive = useCallback(async (item: KnowledgePropertyProfileItem) => {
    if (!item.profile || item.profile.lifecycle !== 'ACTIVE' || busy) return
    if (!window.confirm(`'${item.property_name}' Property 프로파일을 비활성화하시겠습니까?`)) return
    setBusy(true)
    setError('')
    try {
      const fingerprint = JSON.stringify([
        'ARCHIVE',
        item.profile.id,
        item.profile.version,
      ])
      await archiveKnowledgePropertyProfile(
        client,
        item.profile.id,
        item.profile.version,
        idempotencyKeyFor(fingerprint),
      )
      idempotencyAttemptRef.current = undefined
      setRevision((current) => current + 1)
      setStatus(`${item.property_name} 프로파일을 비활성화했습니다.`)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Property 프로파일을 비활성화하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }, [busy, client])

  const columns = useMemo<ColumnDef<KnowledgePropertyProfileItem>[]>(() => [
    {
      accessorKey: 'graph_name',
      header: 'Asset / Release',
      size: 190,
      cell: ({ row }) => (
        <span className="grid min-w-0">
          <strong className="truncate text-xs text-navy-900">{row.original.graph_name}</strong>
          <small className="text-[10px] text-slate-500">Release {row.original.release_no}</small>
        </span>
      ),
    },
    {
      accessorKey: 'property_name',
      header: 'Property',
      size: 210,
      cell: ({ row }) => (
        <span className="grid min-w-0" title={row.original.property_urn}>
          <strong className="truncate text-xs text-navy-900">{row.original.property_name}</strong>
          <small className="truncate text-[10px] text-slate-500">
            {row.original.owner_class_id} · {row.original.data_type}
          </small>
        </span>
      ),
    },
    {
      id: 'unit',
      accessorFn: (row) => row.profile?.unit ?? '',
      header: 'Unit',
      size: 100,
      cell: ({ row }) => row.original.profile?.unit || '—',
    },
    {
      id: 'synonyms',
      accessorFn: (row) => row.profile?.synonyms.join(', ') ?? '',
      header: '동의어',
      size: 240,
      cell: ({ row }) => (
        <span
          className="block max-w-60 truncate"
          title={row.original.profile?.synonyms.join(', ') ?? ''}
        >
          {row.original.profile?.synonyms.join(', ') || '—'}
        </span>
      ),
    },
    {
      id: 'lifecycle',
      accessorFn: (row) => row.profile?.lifecycle ?? '미등록',
      header: '상태',
      size: 100,
      cell: ({ row }) => (
        <span className="rounded bg-slate-100 px-2 py-1 text-[9px] font-black text-slate-600">
          {row.original.profile?.lifecycle ?? '미등록'}
        </span>
      ),
    },
    {
      id: 'actions',
      header: '작업',
      size: 110,
      enableSorting: false,
      cell: ({ row }) => {
        const active = row.original.profile?.lifecycle !== 'ARCHIVED'
        return (
          <div className="flex gap-1">
            <button
              type="button"
              className="rounded p-1 text-enterprise-blue hover:bg-blue-50"
              aria-label={`${row.original.property_name} 프로파일 ${row.original.profile ? '수정' : '생성'}`}
              disabled={busy || !active}
              onClick={(event) => {
                event.stopPropagation()
                setEditing(row.original)
              }}
            >
              {row.original.profile ? <Pencil size={13} /> : <Plus size={13} />}
            </button>
            <button
              type="button"
              className="rounded p-1 text-red-700 hover:bg-red-50"
              aria-label={`${row.original.property_name} 프로파일 비활성화`}
              disabled={busy || !row.original.profile || !active}
              onClick={(event) => {
                event.stopPropagation()
                void archive(row.original)
              }}
            >
              <Archive size={13} />
            </button>
          </div>
        )
      },
    },
  ], [archive, busy])

  return (
    <section aria-label="Property 프로파일 관리" className="grid gap-3">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="m-0 text-sm font-black text-navy-900">Property 프로파일</h3>
          <p className="mb-0 mt-1 text-xs leading-5 text-slate-500">
            활성 Studio Release의 immutable Property를 URN으로 참조하여 설명·단위·동의어를 별도 관리합니다.
          </p>
        </div>
        <button
          type="button"
          className="button button-secondary"
          disabled={loading || busy}
          onClick={() => setRevision((current) => current + 1)}
        >
          <RefreshCw size={13} /> 새로고침
        </button>
      </header>
      <form
        className="flex min-w-0 gap-2"
        role="search"
        onSubmit={(event) => {
          event.preventDefault()
          setQuery(queryInput.trim())
        }}
      >
        <input
          aria-label="Property 프로파일 검색"
          className="input min-w-0 flex-1"
          value={queryInput}
          maxLength={200}
          placeholder="Asset, Property 이름 또는 식별자 검색"
          onChange={(event) => setQueryInput(event.target.value)}
        />
        <button type="submit" className="button" disabled={loading}>
          <Search size={13} /> 검색
        </button>
      </form>
      {error && (
        <div role="alert" className="rounded-enterprise border border-red-200 bg-red-50 p-3 text-xs text-red-800">
          {error}
          <button type="button" className="ml-3 font-black underline" onClick={() => setRevision((value) => value + 1)}>
            다시 시도
          </button>
        </div>
      )}
      <DenseDataTable
        caption="Knowledge Property 프로파일"
        columns={columns}
        data={items}
        getRowId={(item) => item.ontology_element_id}
        loading={loading}
        emptyMessage="현재 권한 범위의 활성 Release Property가 없습니다."
      />
      <p role="status" className="m-0 min-h-5 text-xs text-slate-600">
        {busy ? 'Property 프로파일 정본을 갱신하는 중…' : status}
      </p>
      {editing && (
        <ProfileEditor
          key={editing.ontology_element_id}
          item={editing}
          busy={busy}
          onCancel={() => setEditing(undefined)}
          onSave={save}
        />
      )}
    </section>
  )
}
