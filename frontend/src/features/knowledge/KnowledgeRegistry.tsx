import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
} from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { Edit3, Network, Plus, Trash2, X } from 'lucide-react'
import type { ApiClient } from '../../api/client'
import type {
  KnowledgeAssetOperationalDetail,
  KnowledgeAssetPage,
  KnowledgeAssetSummary,
  KnowledgeAssetVersionHistoryItem,
  KnowledgeAssetVersionHistoryPage,
  KnowledgeRelease,
} from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { AccordionItem } from '../../components/common/Accordion'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import { Dialog } from '../../components/common/Dialog'
import { archiveKnowledgeAsset, KNOWLEDGE_ARCHIVE_CONFIRMATION } from './knowledgeRegistryApi'
import { KnowledgeManagedGraphExplorer } from './KnowledgeManagedGraphExplorer'

const DEFAULT_DRAWER_MAX_WIDTH = 672
const DRAWER_MIN_WIDTH = 440
const DRAWER_WIDTH_TOKENS = [440, 464, 488, 512, 536, 560, 584, 608, 632, 656, 672] as const
const DRAWER_RESIZING_CLASS = 'knowledge-registry-resizing'

function nearestDrawerWidth(value: number, maximum = DEFAULT_DRAWER_MAX_WIDTH): number {
  const available = DRAWER_WIDTH_TOKENS.filter((width) => width <= maximum)
  const candidates = available.length ? available : [DRAWER_WIDTH_TOKENS[0]]
  return candidates.reduce((nearest, width) => (
    Math.abs(width - value) < Math.abs(nearest - value) ? width : nearest
  ))
}

function localTime(value: string | undefined): string {
  if (!value) return '—'
  const timestamp = new Date(value)
  return Number.isNaN(timestamp.valueOf()) ? value : timestamp.toLocaleString('ko-KR')
}

function actorLabel(
  name: string | null,
  email: string | null,
  id: string | null,
): string {
  return name ?? email ?? id ?? '—'
}

function versionKindLabel(kind: KnowledgeAssetVersionHistoryItem['kind']): string {
  const labels: Record<KnowledgeAssetVersionHistoryItem['kind'], string> = {
    STUDIO_RELEASE: 'T-Box / Mapping',
    INSTANCE_RELEASE: 'A-Box Release',
    CHANGESET: 'Changeset',
  }
  return labels[kind]
}

function countRecordLabel(value: Record<string, number> | undefined): string {
  if (!value) return '—'
  const entries = Object.entries(value).sort(([left], [right]) => left.localeCompare(right))
  return entries.length ? entries.map(([name, count]) => `${name}: ${count}`).join(' · ') : '—'
}

export function KnowledgeRegistry({
  client,
  onCreate,
  onEdit,
  canManage = false,
  canArchive = false,
}: {
  client: ApiClient
  onCreate: (intent?: string) => void
  onEdit: (assetId: string, status: string) => void
  canManage?: boolean
  canArchive?: boolean
}) {
  const registryRootRef = useRef<HTMLDivElement>(null)
  const resizeRef = useRef<{ startX: number; startWidth: number } | undefined>(undefined)
  const archiveRetryRef = useRef<{
    assetId: string
    version: number
    key: string
  } | undefined>(undefined)
  const [assets, setAssets] = useState<KnowledgeAssetSummary[]>([])
  const [detail, setDetail] = useState<KnowledgeAssetOperationalDetail>()
  const [query, setQuery] = useState('')
  const [appliedQuery, setAppliedQuery] = useState('')
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [pageCursor, setPageCursor] = useState<string | null>(null)
  const [cursorHistory, setCursorHistory] = useState<Array<string | null>>([])
  const [selectedId, setSelectedId] = useState<string>()
  const [focusedReleaseId, setFocusedReleaseId] = useState<string>()
  const [releases, setReleases] = useState<KnowledgeRelease[]>([])
  const [versionHistory, setVersionHistory] = useState<KnowledgeAssetVersionHistoryPage>()
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [archiving, setArchiving] = useState(false)
  const [archiveTarget, setArchiveTarget] = useState<KnowledgeAssetSummary>()
  const [error, setError] = useState<unknown>()
  const [expandedSections, setExpandedSections] = useState(
    () => new Set(['version-history', 'graph-preview']),
  )
  const [drawerWidth, setDrawerWidth] = useState(() => (
    typeof window === 'undefined'
      ? DEFAULT_DRAWER_MAX_WIDTH
      : nearestDrawerWidth(window.innerWidth * 0.48)
  ))
  const [drawerLimits, setDrawerLimits] = useState({
    minimum: DRAWER_MIN_WIDTH,
    maximum: DEFAULT_DRAWER_MAX_WIDTH,
  })

  const drawerBounds = useCallback(() => {
    if (typeof window === 'undefined') {
      return { minimum: DRAWER_MIN_WIDTH, maximum: DEFAULT_DRAWER_MAX_WIDTH }
    }
    const contentLeft = registryRootRef.current?.getBoundingClientRect().left ?? 0
    const maximum = Math.max(320, window.innerWidth - contentLeft - 12)
    return { minimum: Math.min(DRAWER_MIN_WIDTH, maximum), maximum }
  }, [])

  const clampDrawerWidth = useCallback((value: number) => {
    const { maximum } = drawerBounds()
    return nearestDrawerWidth(value, maximum)
  }, [drawerBounds])

  useEffect(() => {
    const move = (event: globalThis.PointerEvent) => {
      const resize = resizeRef.current
      if (!resize) return
      setDrawerWidth(clampDrawerWidth(resize.startWidth + resize.startX - event.clientX))
    }
    const stop = () => {
      resizeRef.current = undefined
      document.body.classList.remove(DRAWER_RESIZING_CLASS)
    }
    const resize = () => {
      const nextLimits = drawerBounds()
      const maximum = nearestDrawerWidth(nextLimits.maximum, nextLimits.maximum)
      setDrawerLimits({ minimum: Math.min(DRAWER_MIN_WIDTH, maximum), maximum })
      setDrawerWidth((current) => nearestDrawerWidth(current, nextLimits.maximum))
    }
    resize()
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', stop)
    window.addEventListener('pointercancel', stop)
    window.addEventListener('resize', resize)
    return () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', stop)
      window.removeEventListener('pointercancel', stop)
      window.removeEventListener('resize', resize)
      document.body.classList.remove(DRAWER_RESIZING_CLASS)
    }
  }, [clampDrawerWidth, drawerBounds])

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(undefined)
    try {
      const parameters = new URLSearchParams({
        limit: '25',
        sort: 'UPDATED_DESC',
      })
      if (appliedQuery) parameters.set('q', appliedQuery)
      if (pageCursor) parameters.set('cursor', pageCursor)
      const result = await client.request<KnowledgeAssetPage>(
        `/knowledge/registry/assets?${parameters}`,
      )
      setAssets(result.items)
      setNextCursor(result.next_cursor)
      setSelectedId((current) => (
        current && result.items.some((asset) => asset.id === current) ? current : undefined
      ))
    } catch (next) {
      setError(next)
    } finally {
      setLoading(false)
    }
  }, [appliedQuery, client, pageCursor])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const selected = assets.find((asset) => asset.id === selectedId)
  const focusedRelease = releases.find((release) => release.id === focusedReleaseId)

  useEffect(() => {
    if (!selected) {
      setDetail(undefined)
      setReleases([])
      setVersionHistory(undefined)
      setFocusedReleaseId(undefined)
      return
    }
    const controller = new AbortController()
    setDetailLoading(true)
    setError(undefined)
    setReleases([])
    setVersionHistory(undefined)
    setDetail(undefined)
    void Promise.all([
      client.request<KnowledgeRelease[]>(
        `/knowledge/graphs/${selected.id}/releases`,
        { cache: 'no-store', signal: controller.signal },
      ),
      client.request<KnowledgeAssetOperationalDetail>(
        `/knowledge/registry/assets/${selected.id}/detail`,
        { cache: 'no-store', signal: controller.signal },
      ),
      client.request<KnowledgeAssetVersionHistoryPage>(
        `/knowledge/registry/assets/${selected.id}/versions?limit=50`,
        { cache: 'no-store', signal: controller.signal },
      ),
    ])
      .then(([nextReleases, nextDetail, nextVersionHistory]) => {
        if (controller.signal.aborted) return
        setDetail(nextDetail)
        setReleases(nextReleases)
        setVersionHistory(nextVersionHistory)
        setFocusedReleaseId(
          selected.active_release_id
          ?? nextReleases.reduce<KnowledgeRelease | undefined>(
            (latest, release) => (
              !latest || release.release_no > latest.release_no ? release : latest
            ),
            undefined,
          )?.id,
        )
      })
      .catch((next) => {
        if (!controller.signal.aborted) setError(next)
      })
      .finally(() => {
        if (!controller.signal.aborted) setDetailLoading(false)
      })
    return () => controller.abort()
  }, [client, selected])

  const columns = useMemo<ColumnDef<KnowledgeAssetSummary>[]>(() => [
    {
      id: 'ordinal',
      header: 'No',
      size: 60,
      enableSorting: false,
      cell: ({ row }) => row.index + 1,
    },
    {
      accessorKey: 'name',
      header: '지식그래프명',
      size: 220,
      enableSorting: false,
      cell: ({ row }) => <strong>{row.original.name}</strong>,
    },
    {
      id: 'graph_type',
      header: 'Type',
      size: 150,
      enableSorting: false,
      cell: ({ row }) => row.original.graph_type,
    },
    {
      id: 'source',
      header: 'Source',
      size: 100,
      enableSorting: false,
      cell: ({ row }) => row.original.source ?? 'Studio',
    },
    {
      id: 'default',
      header: 'Default',
      size: 80,
      enableSorting: false,
      cell: ({ row }) => row.original.is_default ? 'Yes' : '—',
    },
    {
      id: 'version',
      header: 'Version',
      size: 140,
      enableSorting: false,
      cell: ({ row }) => {
        const status = row.original.status
        let badgeColor = 'bg-slate-100 text-slate-800'
        if (status === 'ACTIVE' || status === 'READY') badgeColor = 'bg-emerald-100 text-emerald-800'
        if (status === 'READY_WITH_REFRESH_FAILURE') badgeColor = 'bg-orange-100 text-orange-800'
        if (status === 'FAILED') badgeColor = 'bg-red-100 text-red-800'
        if (status === 'DRAFT') badgeColor = 'bg-amber-100 text-amber-800'
        if (status === 'ARCHIVED') badgeColor = 'bg-slate-200 text-slate-600'
        return (
          <div className="flex items-center gap-2">
            <span>v{row.original.display_version ?? row.original.version}</span>
            <span className={`rounded-sm px-1.5 py-0.5 text-[9px] font-bold ${badgeColor}`}>
              {status}
            </span>
          </div>
        )
      },
    },
    {
      id: 'counts',
      header: 'Nodes / Edges',
      size: 120,
      enableSorting: false,
      cell: ({ row }) => `${row.original.node_count} / ${row.original.edge_count}`,
    },
    {
      id: 'refresh',
      header: 'Refresh',
      size: 180,
      enableSorting: false,
      cell: ({ row }) => row.original.managed
        ? `${row.original.refresh_mode ?? '—'} · ${row.original.scheduler_status ?? 'UNAVAILABLE'}`
        : 'MANUAL',
    },
    {
      id: 'description',
      header: '설명',
      size: 250,
      enableSorting: false,
      cell: ({ row }) => (
        <span className="truncate block w-full" title={row.original.description ?? ''}>
          {row.original.description ?? '—'}
        </span>
      ),
    },
    {
      id: 'updated_at',
      header: '최근 수정일',
      size: 160,
      enableSorting: false,
      cell: ({ row }) => localTime(row.original.updated_at),
    },
    {
      id: 'creator',
      header: '생성자',
      size: 140,
      enableSorting: false,
      cell: ({ row }) => <span className="truncate block w-full">{actorLabel(row.original.creator_name, row.original.creator_email, null)}</span>,
    },
    {
      id: 'editor',
      header: '최근 수정자',
      size: 140,
      enableSorting: false,
      cell: ({ row }) => <span className="truncate block w-full">{actorLabel(row.original.editor_name, row.original.editor_email, null)}</span>,
    },
    {
      id: 'actions',
      header: '편집',
      size: 100,
      enableSorting: false,
      cell: ({ row }) => (
        <div className="flex gap-1" onClick={(event) => event.stopPropagation()}>
          {canManage && !row.original.managed && row.original.status !== 'ARCHIVED' && (
            <button
              type="button"
              className="button button-secondary"
              title="Knowledge Studio에서 편집"
              aria-label={`${row.original.name} 에셋 편집`}
              onClick={() => onEdit(
                row.original.status === 'DRAFT'
                  ? row.original.draft_id ?? row.original.id
                  : row.original.id,
                row.original.status,
              )}
            >
              <Edit3 size={13} />
            </button>
          )}
          {canArchive && !row.original.managed && row.original.status !== 'ARCHIVED' && row.original.active_studio_release_id && (
            <button
              type="button"
              className="button button-secondary"
              title="지식 에셋 아카이빙"
              aria-label={`${row.original.name} 에셋 아카이빙`}
              onClick={() => setArchiveTarget(row.original)}
            >
              <Trash2 size={13} />
            </button>
          )}
          {!canManage && !canArchive && <span className="text-[10px] text-slate-500">읽기 전용</span>}
        </div>
      ),
    },
  ], [canArchive, canManage, onEdit])

  const toggleSection = (itemId: string) => {
    setExpandedSections((current) => {
      const next = new Set(current)
      if (next.has(itemId)) next.delete(itemId)
      else next.add(itemId)
      return next
    })
  }

  const beginResize = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return
    resizeRef.current = { startX: event.clientX, startWidth: drawerWidth }
    document.body.classList.add(DRAWER_RESIZING_CLASS)
    event.currentTarget.setPointerCapture(event.pointerId)
    event.preventDefault()
  }

  const resizeWithKeyboard = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
    event.preventDefault()
    setDrawerWidth((current) => clampDrawerWidth(
      current + (event.key === 'ArrowLeft' ? 24 : -24),
    ))
  }

  const archive = async () => {
    if (!archiveTarget || archiving) return
    setArchiving(true)
    setError(undefined)
    try {
      if (
        archiveRetryRef.current?.assetId !== archiveTarget.id
        || archiveRetryRef.current.version !== archiveTarget.version
      ) {
        archiveRetryRef.current = {
          assetId: archiveTarget.id,
          version: archiveTarget.version,
          key: crypto.randomUUID(),
        }
      }
      await archiveKnowledgeAsset(client, archiveTarget, archiveRetryRef.current.key)
      archiveRetryRef.current = undefined
      if (selectedId === archiveTarget.id) setSelectedId(undefined)
      setArchiveTarget(undefined)
      await refresh()
    } catch (next) {
      setError(next)
    } finally {
      setArchiving(false)
    }
  }

  return (
    <div ref={registryRootRef} className="grid gap-4">
      <div className="grid gap-2 sm:grid-cols-3">
        {[
          ['현재 페이지 Assets', String(assets.length)],
          ['활성 인스턴스', String(assets.filter((item) => item.active_release_id).length)],
          ['검증된 Projection', String(assets.filter(
            (item) => ['SHADOW_VERIFIED', 'READY', 'READY_WITH_REFRESH_FAILURE'].includes(
              item.projection_state ?? '',
            ),
          ).length)],
        ].map(([label, value]) => (
          <article
            key={label}
            className="rounded-enterprise border border-slate-300 bg-white px-4 py-3 shadow-sm"
          >
            <span className="block text-[10px] font-black tracking-wide text-slate-500 uppercase">
              {label}
            </span>
            <strong className="mt-1 block text-sm text-navy-900">
              {value}
            </strong>
          </article>
        ))}
      </div>
      <section className="rounded-enterprise border border-slate-300 bg-white p-4 shadow-sm">
        <header className="mb-3 flex flex-wrap items-end justify-between gap-3">
          <div>
            <span className="text-[10px] font-black tracking-[.14em] text-enterprise-blue uppercase">
              Asset list
            </span>
            <h2 className="my-1 text-lg font-black text-navy-900">지식 레지스트리</h2>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <label className="grid gap-1 text-xs font-bold text-navy-900">
              Asset 검색
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key !== 'Enter') return
                  setAppliedQuery(query.trim())
                  setPageCursor(null)
                  setCursorHistory([])
                }}
                placeholder="이름, alias, 도메인"
              />
            </label>
            <button
              className="button button-secondary"
              type="button"
              onClick={() => {
                setAppliedQuery(query.trim())
                setPageCursor(null)
                setCursorHistory([])
              }}
            >
              검색
            </button>
            {canManage && (
              <button className="button" type="button" onClick={() => onCreate()}>
                <Plus size={14} /> 일반 에셋 추가
              </button>
            )}
          </div>
        </header>
        <ErrorNotice error={error} />
        <div className="grid gap-4">
          {assets.length === 0 && !loading ? (
            <div className="flex flex-col items-center justify-center rounded-enterprise border border-dashed border-slate-300 bg-slate-50 py-12 text-center px-4">
              <Network size={32} className="text-slate-400 mb-3" />
              <h3 className="text-sm font-bold text-navy-900 mb-1">등록된 지식 에셋이 없습니다</h3>
              <p className="max-w-md text-xs text-slate-500 mb-4">
                지식 레지스트리는 기업의 도메인 지식을 관리하는 곳입니다. 새로운 에셋을 생성하여 DRAFT 버전을 만들고, 검토를 거쳐 활성화(ACTIVE)하세요.
                <br />
                활성화된 에셋을 직접 수정하면 새로운 DRAFT 버전이 생성되며, 기존 ACTIVE 버전은 유지됩니다. (최대 1개 활성 허용)
              </p>
              {canManage ? (
                <div className="grid justify-items-center gap-2">
                  <button className="button button-primary" type="button" onClick={() => onCreate()}>
                    <Plus size={14} /> 일반 에셋 추가
                  </button>
                  <p className="m-0 max-w-xl text-xs text-slate-500">
                    Metadata Lineage와 Data Glossary 기본 graph는 승인된 managed policy bootstrap이 동일 identity로 생성합니다. 일반 Studio 생성으로 중복 default graph를 만들지 않습니다.
                  </p>
                </div>
              ) : (
                <p className="m-0 text-xs font-semibold text-slate-600">현재 계정은 레지스트리를 조회할 수 있지만 새 Asset을 만들 수 없습니다.</p>
              )}
            </div>
          ) : (
            <>
              <DenseDataTable
                caption="지식 에셋 목록"
                columns={columns}
                data={assets}
                getRowId={(asset) => asset.id}
                loading={loading}
                selectedRowId={selectedId}
                onRowActivate={(asset) => setSelectedId(asset.id)}
              />
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  className="button button-secondary"
                  disabled={loading || cursorHistory.length === 0}
                  onClick={() => {
                    const next = [...cursorHistory]
                    setPageCursor(next.pop() ?? null)
                    setCursorHistory(next)
                  }}
                >
                  이전
                </button>
                <button
                  type="button"
                  className="button button-secondary"
                  disabled={loading || !nextCursor}
                  onClick={() => {
                    if (!nextCursor) return
                    setCursorHistory((current) => [...current, pageCursor])
                    setPageCursor(nextCursor)
                  }}
                >
                  다음
                </button>
              </div>
              {!selected && (
                <div className="grid min-h-36 place-items-center rounded-enterprise border border-dashed border-slate-300 bg-slate-50 text-center text-xs text-slate-500">
                  <div>
                    <Network className="mx-auto mb-2" />
                    <p>에셋을 선택하면 우측 상세 패널을 엽니다.</p>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </section>

      {selected && (
        <>
          <div
            className="fixed inset-0 z-40 bg-navy-950/35"
            aria-hidden="true"
            onClick={() => setSelectedId(undefined)}
          />
          <aside
            className={`knowledge-registry-drawer knowledge-registry-drawer-width-${drawerWidth} fixed right-3 top-[68px] bottom-3 z-50 overflow-y-auto rounded-enterprise border border-slate-400 bg-white p-5 shadow-2xl max-md:right-0 max-md:top-0 max-md:bottom-0 max-md:w-full!`}
            aria-label={`${selected.name} 지식 에셋 상세`}
          >
            <div
              role="separator"
              aria-label="상세 패널 너비 조절"
              aria-orientation="vertical"
              aria-valuemin={Math.round(drawerLimits.minimum)}
              aria-valuemax={Math.round(drawerLimits.maximum)}
              aria-valuenow={Math.round(drawerWidth)}
              tabIndex={0}
              className="absolute inset-y-0 left-0 z-10 w-2 cursor-col-resize touch-none border-l-2 border-transparent transition-colors hover:border-enterprise-blue focus:border-enterprise-blue focus:outline-none max-md:hidden"
              onPointerDown={beginResize}
              onKeyDown={resizeWithKeyboard}
            />
            <header className="mb-4 flex items-start justify-between gap-3 border-b border-slate-200 pb-4">
              <div className="min-w-0">
                <span className="text-[10px] font-black tracking-[.14em] text-enterprise-blue uppercase">
                  Authorized asset detail
                </span>
                <h2 className="my-1 truncate text-xl font-black text-navy-900">{selected.name}</h2>
                <p className="m-0 truncate text-xs text-slate-500">{selected.id}</p>
              </div>
              <button
                type="button"
                className="button button-secondary"
                aria-label="에셋 상세 닫기"
                onClick={() => setSelectedId(undefined)}
              >
                <X size={15} />
              </button>
            </header>
            <div className="grid gap-4">
              <dl className="grid grid-cols-2 gap-3 rounded-enterprise border border-slate-200 bg-slate-50 p-4 text-xs md:grid-cols-3">
                <div>
                  <dt className="text-[10px] font-black text-slate-500">ID</dt>
                  <dd className="m-0 break-all">{selected.id}</dd>
                </div>
                <div>
                  <dt className="text-[10px] font-black text-slate-500">Domain</dt>
                  <dd className="m-0 break-all">{selected.domain_name ?? '기록 없음 (legacy)'}</dd>
                </div>
                <div>
                  <dt className="text-[10px] font-black text-slate-500">보안 분류</dt>
                  <dd className="m-0">{selected.classification}</dd>
                </div>
                <div>
                  <dt className="text-[10px] font-black text-slate-500">Status</dt>
                  <dd className="m-0">{selected.status}</dd>
                </div>
                <div>
                  <dt className="text-[10px] font-black text-slate-500">Type / Default</dt>
                  <dd className="m-0">{selected.graph_type} / {selected.is_default ? 'Yes' : 'No'}</dd>
                </div>
                <div>
                  <dt className="text-[10px] font-black text-slate-500">Source</dt>
                  <dd className="m-0">{selected.source ?? 'Knowledge Studio'}</dd>
                </div>
                <div>
                  <dt className="text-[10px] font-black text-slate-500">Current Version</dt>
                  <dd className="m-0">
                    {focusedRelease ? `Release v${focusedRelease.release_no}` : `v${selected.display_version ?? selected.version}`}
                  </dd>
                </div>
                <div>
                  <dt className="text-[10px] font-black text-slate-500">Nodes / Edges</dt>
                  <dd className="m-0">{focusedRelease?.node_count ?? selected.node_count} / {focusedRelease?.edge_count ?? selected.edge_count}</dd>
                </div>
                {selected.managed && (
                  <>
                    <div>
                      <dt className="text-xs font-black text-slate-500">Scheduler Status</dt>
                      <dd className="m-0">{selected.scheduler_status ?? 'UNAVAILABLE'}</dd>
                    </div>
                    <div>
                      <dt className="text-xs font-black text-slate-500">Configured Mode / Schedule</dt>
                      <dd className="m-0">{selected.refresh_mode} / {selected.schedule ?? '—'}</dd>
                    </div>
                    <div>
                      <dt className="text-xs font-black text-slate-500">Schedule Timezone</dt>
                      <dd className="m-0">{selected.schedule_timezone ?? '—'}</dd>
                    </div>
                    <div>
                      <dt className="text-xs font-black text-slate-500">Last Published Refresh</dt>
                      <dd className="m-0">{localTime(selected.last_refresh ?? undefined)}</dd>
                    </div>
                    <div>
                      <dt className="text-xs font-black text-slate-500">Next Scheduled Boundary</dt>
                      <dd className="m-0">{localTime(selected.next_scheduled_run ?? undefined)}</dd>
                    </div>
                    <div>
                      <dt className="text-xs font-black text-slate-500">Last Successful Boundary</dt>
                      <dd className="m-0">{localTime(selected.last_successful_schedule ?? undefined)}</dd>
                    </div>
                    <div>
                      <dt className="text-xs font-black text-slate-500">Last Scheduler Attempt</dt>
                      <dd className="m-0">
                        {selected.scheduler_last_attempt
                          ? `${selected.scheduler_last_attempt.status} · ${localTime(selected.scheduler_last_attempt.completed_at ?? undefined)} · ${selected.scheduler_last_attempt.trigger ?? '—'}${selected.scheduler_last_attempt.reason ? ` · ${selected.scheduler_last_attempt.reason}` : ''}`
                          : 'NOT_RUN'}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs font-black text-slate-500">Last Graph Result</dt>
                      <dd className="m-0">{selected.last_result ?? 'NOT_RUN'}</dd>
                    </div>
                    <div>
                      <dt className="text-[10px] font-black text-slate-500">Semantic / Vector Index</dt>
                      <dd className="m-0">{selected.semantic_index_status ?? 'PENDING'}</dd>
                    </div>
                    <div>
                      <dt className="text-[10px] font-black text-slate-500">Graph Model</dt>
                      <dd className="m-0">v{selected.graph_model_version ?? 1}</dd>
                    </div>
                    <div>
                      <dt className="text-[10px] font-black text-slate-500">Source Snapshot</dt>
                      <dd className="m-0 break-all">{selected.source_snapshot_id ?? '—'}</dd>
                    </div>
                    <div>
                      <dt className="text-[10px] font-black text-slate-500">Snapshot Observed</dt>
                      <dd className="m-0">{localTime(selected.source_snapshot_observed_at ?? undefined)}</dd>
                    </div>
                    <div>
                      <dt className="text-[10px] font-black text-slate-500">Active Projection</dt>
                      <dd className="m-0 break-all">{selected.active_projection ?? '—'}</dd>
                    </div>
                    <div>
                      <dt className="text-[10px] font-black text-slate-500">DataHub Source</dt>
                      <dd className="m-0 break-all">
                        {selected.source_datahub_version ?? '—'}{selected.source_datahub_commit ? ` / ${selected.source_datahub_commit}` : ''}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-[10px] font-black text-slate-500">Semantic Generation</dt>
                      <dd className="m-0 break-all">{selected.semantic_index_generation ?? '—'}</dd>
                    </div>
                    {selected.lineage_source && (
                      <div className="col-span-2 md:col-span-3">
                        <dt className="text-[10px] font-black text-slate-500">Lineage Source</dt>
                        <dd className="m-0">{selected.lineage_source}</dd>
                      </div>
                    )}
                    {selected.quality_metrics && (
                      <>
                        <div className="col-span-2 md:col-span-3">
                          <dt className="text-[10px] font-black text-slate-500">Nodes by Type</dt>
                          <dd className="m-0 break-words">{countRecordLabel(selected.quality_metrics.entity_count_by_type)}</dd>
                        </div>
                        <div className="col-span-2 md:col-span-3">
                          <dt className="text-[10px] font-black text-slate-500">Edges by Type</dt>
                          <dd className="m-0 break-words">{countRecordLabel(selected.quality_metrics.relation_count_by_type)}</dd>
                        </div>
                        <div>
                          <dt className="text-[10px] font-black text-slate-500">Explicit / Inferred</dt>
                          <dd className="m-0">{selected.quality_metrics.explicit_edge_count} / {selected.quality_metrics.inferred_edge_count}</dd>
                        </div>
                        <div>
                          <dt className="text-[10px] font-black text-slate-500">Units Explicit / Candidate</dt>
                          <dd className="m-0">{selected.quality_metrics.unit_explicit_count} / {selected.quality_metrics.unit_inferred_count}</dd>
                        </div>
                        <div>
                          <dt className="text-[10px] font-black text-slate-500">Duplicate Nodes / Edges</dt>
                          <dd className="m-0">{selected.quality_metrics.duplicate_node_count} / {selected.quality_metrics.duplicate_edge_count}</dd>
                        </div>
                        <div>
                          <dt className="text-[10px] font-black text-slate-500">Orphans / Pairwise Cliques</dt>
                          <dd className="m-0">{selected.quality_metrics.orphan_node_count} / {selected.quality_metrics.pairwise_clique_count}</dd>
                        </div>
                        <div>
                          <dt className="text-[10px] font-black text-slate-500">Average / Maximum Degree</dt>
                          <dd className="m-0">{selected.quality_metrics.average_degree} / {selected.quality_metrics.maximum_degree}</dd>
                        </div>
                        <div>
                          <dt className="text-[10px] font-black text-slate-500">Lineage Table / Column Edges</dt>
                          <dd className="m-0">{selected.quality_metrics.lineage_table_edge_count} / {selected.quality_metrics.lineage_column_edge_count}</dd>
                        </div>
                        {selected.quality_metrics.reconciliation && (
                          <div className="col-span-2 md:col-span-3">
                            <dt className="text-[10px] font-black text-slate-500">Snapshot Diff · Added / Removed / Changed</dt>
                            <dd className="m-0">
                              Nodes {selected.quality_metrics.reconciliation.nodes.added} / {selected.quality_metrics.reconciliation.nodes.removed} / {selected.quality_metrics.reconciliation.nodes.changed}
                              {' · '}Edges {selected.quality_metrics.reconciliation.edges.added} / {selected.quality_metrics.reconciliation.edges.removed} / {selected.quality_metrics.reconciliation.edges.changed}
                            </dd>
                          </div>
                        )}
                        <div className="col-span-2 md:col-span-3">
                          <dt className="text-[10px] font-black text-slate-500">Inference Evidence</dt>
                          <dd className="m-0">
                            Inferred relations retain extraction method, confidence and source text in graph relation detail.
                          </dd>
                        </div>
                      </>
                    )}
                    <div className="col-span-2 md:col-span-3">
                      <dt className="text-[10px] font-black text-slate-500">Semantic Capabilities</dt>
                      <dd className="m-0">{selected.semantic_capabilities?.join(', ') || '—'}</dd>
                    </div>
                  </>
                )}
                <div>
                  <dt className="text-[10px] font-black text-slate-500">Creator</dt>
                  <dd className="m-0 break-all">
                    {actorLabel(selected.creator_name, selected.creator_email, null)}
                  </dd>
                </div>
                <div>
                  <dt className="text-[10px] font-black text-slate-500">Editor</dt>
                  <dd className="m-0 break-all">
                    {actorLabel(selected.editor_name, selected.editor_email, null)}
                  </dd>
                </div>
                <div className="col-span-2 md:col-span-3">
                  <dt className="text-[10px] font-black text-slate-500">Description</dt>
                  <dd className="m-0">{selected.description ?? '설명이 없습니다.'}</dd>
                </div>
              </dl>
              <AccordionItem
                itemId="version-history"
                title="버전 이력"
                summary={`${versionHistory?.items.length ?? 0} events`}
                expanded={expandedSections.has('version-history')}
                onToggle={() => toggleSection('version-history')}
              >
                {versionHistory?.items.length ? (
                  <div className="overflow-x-auto">
                    <table className="w-full border-collapse text-left text-xs">
                      <thead>
                        <tr className="border-b border-slate-300 text-[10px] font-black text-slate-500 uppercase">
                          <th className="p-2">Version</th>
                          <th className="p-2">Status</th>
                          <th className="p-2">Creator</th>
                          <th className="p-2">Created At</th>
                          <th className="p-2">Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {versionHistory.items.map((item) => {
                          const focused = item.kind === 'INSTANCE_RELEASE'
                            && item.instance_release_id === focusedReleaseId
                          const canPreview = item.kind === 'INSTANCE_RELEASE'
                            && item.instance_release_id !== null
                          return (
                            <tr
                              key={`${item.kind}:${item.id}`}
                              className={`border-b border-slate-200 ${
                                focused ? 'bg-blue-50' : 'hover:bg-slate-50'
                              }`}
                            >
                              <td className="p-2">
                                <strong className="block">{item.version_label}</strong>
                                <small className="mt-0.5 block text-[10px] text-slate-500">
                                  {versionKindLabel(item.kind)}
                                  {item.title ? ` · ${item.title}` : ''}
                                </small>
                                {item.content_hash && (
                                  <code
                                    className="mt-0.5 block max-w-40 truncate text-[9px] text-slate-400"
                                    title={item.content_hash}
                                  >
                                    {item.content_hash}
                                  </code>
                                )}
                              </td>
                              <td className="p-2">
                                <span className="badge badge-soft">{item.status}</span>
                                {item.is_current && (
                                  <span className="ml-1 rounded-full bg-emerald-100 px-2 py-1 text-[10px] font-black text-emerald-800">
                                    CURRENT
                                  </span>
                                )}
                                {item.kind === 'INSTANCE_RELEASE'
                                  && item.node_count !== null
                                  && item.edge_count !== null && (
                                  <small className="mt-1 block text-[10px] text-slate-500">
                                    {item.node_count} nodes · {item.edge_count} edges
                                  </small>
                                )}
                              </td>
                              <td
                                className="max-w-36 truncate p-2"
                                title={actorLabel(
                                  item.author_name,
                                  item.author_email,
                                  item.author_id,
                                )}
                              >
                                {actorLabel(item.author_name, item.author_email, item.author_id)}
                              </td>
                              <td className="whitespace-nowrap p-2">
                                {localTime(item.created_at)}
                              </td>
                              <td className="min-w-40 p-2">
                                {canPreview
                                  ? (
                                      <button
                                        type="button"
                                        className="button button-secondary"
                                        aria-pressed={focused}
                                        onClick={() => {
                                          if (item.instance_release_id) {
                                            setFocusedReleaseId(item.instance_release_id)
                                          }
                                        }}
                                      >
                                        {focused ? '포커스됨' : '미리보기'}
                                      </button>
                                    )
                                  : (
                                      <div className="grid gap-0.5 text-[10px] text-slate-500">
                                        <span>
                                          검토 {actorLabel(
                                            item.reviewer_name,
                                            item.reviewer_email,
                                            item.reviewed_by,
                                          )}
                                        </span>
                                        <span>
                                          발행 {actorLabel(
                                            item.publisher_name,
                                            item.publisher_email,
                                            item.published_by,
                                          )}
                                        </span>
                                      </div>
                                    )}
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                    {versionHistory.next_cursor && (
                      <p className="mb-0 mt-2 text-[10px] text-slate-500">
                        최근 {versionHistory.limit}건만 표시합니다. 이전 이력은 다음 페이지에서
                        계속 조회할 수 있습니다.
                      </p>
                    )}
                  </div>
                ) : (
                  <p className="m-0 text-xs text-slate-500">버전 이력이 없습니다.</p>
                )}
              </AccordionItem>
              <AccordionItem
                itemId="graph-preview"
                title="그래프 미리보기"
                summary={detailLoading
                  ? '불러오는 중'
                  : focusedReleaseId
                    ? `${selected.node_count ?? 0} canonical nodes`
                    : '미발행'}
                expanded={expandedSections.has('graph-preview')}
                onToggle={() => toggleSection('graph-preview')}
              >
                {focusedReleaseId
                  ? <KnowledgeManagedGraphExplorer
                    key={`${selected.id}:${focusedReleaseId}`}
                    client={client}
                    graphId={selected.id}
                    graphType={selected.graph_type}
                    releaseId={focusedReleaseId}
                  />
                  : <p className="m-0 text-xs text-slate-500">발행된 graph release가 없어 read-only visualization을 열 수 없습니다.</p>}
              </AccordionItem>
              <AccordionItem
                itemId="ingestion-history"
                title="Ingestion 기록과 연결 Source"
                summary={`${detail?.bindings.length ?? 0} bindings`}
                expanded={expandedSections.has('ingestion-history')}
                onToggle={() => toggleSection('ingestion-history')}
              >
                {detail?.bindings.length ? (
                  <div className="overflow-x-auto">
                    <table className="w-full border-collapse text-left text-xs">
                      <thead>
                        <tr className="border-b border-slate-300 text-[10px] font-black text-slate-500 uppercase">
                          <th className="p-2">Target</th>
                          <th className="p-2">Source</th>
                          <th className="p-2">Version</th>
                          <th className="p-2">Rules</th>
                        </tr>
                      </thead>
                      <tbody>
                        {detail.bindings.map((binding) => (
                          <tr key={binding.id} className="border-b border-slate-200">
                            <td className="p-2 font-bold">{binding.target_stable_element_id}</td>
                            <td className="p-2">
                              {binding.source_name}
                              <small className="block text-slate-500">{binding.source_kind}</small>
                            </td>
                            <td className="p-2">{binding.source_version}</td>
                            <td className="p-2">{binding.mapping_rule_count}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="m-0 text-xs text-slate-500">
                    활성 Studio Release에 발행된 A-Box Binding이 없습니다.
                  </p>
                )}
              </AccordionItem>
              <AccordionItem
                itemId="projection-history"
                title="Projection 동기화"
                summary={selected.projection_state ?? 'NOT_RUN'}
                expanded={expandedSections.has('projection-history')}
                onToggle={() => toggleSection('projection-history')}
              >
                {detail?.projections.filter(
                  (projection) => !focusedReleaseId || projection.release_id === focusedReleaseId,
                ).length ? (
                  <ul className="m-0 grid list-none gap-2 p-0 text-xs">
                    {detail.projections
                      .filter(
                        (projection) => (
                          !focusedReleaseId || projection.release_id === focusedReleaseId
                        ),
                      )
                      .map((projection) => (
                      <li key={projection.id} className="rounded border border-slate-200 p-3">
                        <strong>{projection.adapter} · {projection.state}</strong>
                        <small className="mt-1 block text-slate-500">
                          {projection.node_count ?? 0} nodes · {projection.edge_count ?? 0} edges
                          {' · '}{localTime(projection.verified_at ?? projection.updated_at)}
                        </small>
                        {projection.error_code && (
                          <span className="mt-1 block text-red-700">{projection.error_code}</span>
                        )}
                      </li>
                      ))}
                  </ul>
                ) : (
                  <p className="m-0 text-xs text-slate-500">
                    아직 PostgreSQL Release를 검증한 Projection receipt가 없습니다.
                  </p>
                )}
              </AccordionItem>
              <AccordionItem
                itemId="typed-api"
                title="Endpoint API"
                summary={selected.delivery_policy?.api_enabled ? 'ENABLED' : 'DISABLED'}
                expanded={expandedSections.has('typed-api')}
                onToggle={() => toggleSection('typed-api')}
              >
                {selected.delivery_policy?.api_enabled ? (
                  <div className="grid gap-2 text-xs">
                    <p className="m-0 text-slate-500">
                      OIDC와 KG ABAC를 통과한 호출자에게만 활성 Release 상대 경로를 반환합니다.
                    </p>
                    <code className="overflow-x-auto rounded bg-slate-100 p-3">
                      GET /api/v1/knowledge/assets/by-alias/{selected.slug}
                    </code>
                    <code className="overflow-x-auto rounded bg-slate-100 p-3">
                      GET /api/v1/knowledge/graphs/{selected.id}/releases/
                      {selected.active_release_id ?? '{active-release}'}/snapshot
                    </code>
                  </div>
                ) : (
                  <p className="m-0 text-xs text-slate-500">
                    정보 관리의 API &amp; Chat routing에서 이 Asset의 API 제공을 활성화할 수
                    있습니다.
                  </p>
                )}
              </AccordionItem>
            </div>
          </aside>
        </>
      )}
      <Dialog
        open={Boolean(archiveTarget)}
        title="지식 자산 아카이빙"
        description={KNOWLEDGE_ARCHIVE_CONFIRMATION}
        onRequestClose={() => {
          if (!archiving) setArchiveTarget(undefined)
        }}
        footer={(
          <>
            <button
              type="button"
              className="button button-secondary"
              disabled={archiving}
              onClick={() => setArchiveTarget(undefined)}
            >
              취소
            </button>
            <button
              type="button"
              className="button"
              disabled={archiving}
              onClick={() => void archive()}
            >
              {archiving ? '아카이빙 중…' : '아카이빙'}
            </button>
          </>
        )}
      >
        <p className="m-0 text-sm leading-6 text-slate-600">
          발행 릴리스와 감사 증거는 삭제하지 않습니다. 선택한 에셋은 레지스트리와 신규 질의
          대상에서 제외되며, 서버에 수행자와 사유가 기록됩니다.
        </p>
      </Dialog>
    </div>
  )
}
