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
import type { KnowledgeGraph, KnowledgeRelease, KnowledgeSnapshot } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { AccordionItem } from '../../components/common/Accordion'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import { Dialog } from '../../components/common/Dialog'
import { FlowCanvas, type FlowCanvasEdge, type FlowCanvasNode } from '../../components/common/FlowCanvas'
import { archiveKnowledgeAsset, KNOWLEDGE_ARCHIVE_CONFIRMATION } from './knowledgeRegistryApi'

const DEFAULT_DRAWER_MAX_WIDTH = 672
const DRAWER_MIN_WIDTH = 440

function nodeLabel(properties: Record<string, unknown>, fallback: string): string {
  const candidate = properties.name ?? properties.display_name
  return typeof candidate === 'string' || typeof candidate === 'number'
    ? String(candidate)
    : fallback
}

function localTime(value: string | undefined): string {
  if (!value) return '—'
  const timestamp = new Date(value)
  return Number.isNaN(timestamp.valueOf()) ? value : timestamp.toLocaleString('ko-KR')
}

export function KnowledgeRegistry({
  client,
  onCreate,
  onEdit,
}: {
  client: ApiClient
  onCreate: () => void
  onEdit: (assetId: string) => void
}) {
  const registryRootRef = useRef<HTMLDivElement>(null)
  const resizeRef = useRef<{ startX: number; startWidth: number } | undefined>(undefined)
  const [graphs, setGraphs] = useState<KnowledgeGraph[]>([])
  const [selectedId, setSelectedId] = useState<string>()
  const [focusedReleaseId, setFocusedReleaseId] = useState<string>()
  const [releases, setReleases] = useState<KnowledgeRelease[]>([])
  const [snapshot, setSnapshot] = useState<KnowledgeSnapshot>()
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [archiving, setArchiving] = useState(false)
  const [archiveTarget, setArchiveTarget] = useState<KnowledgeGraph>()
  const [error, setError] = useState<unknown>()
  const [expandedSections, setExpandedSections] = useState(
    () => new Set(['version-history', 'graph-preview']),
  )
  const [drawerWidth, setDrawerWidth] = useState(() => (
    typeof window === 'undefined'
      ? DEFAULT_DRAWER_MAX_WIDTH
      : Math.min(DEFAULT_DRAWER_MAX_WIDTH, window.innerWidth * 0.48)
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
    const { minimum, maximum } = drawerBounds()
    return Math.min(maximum, Math.max(minimum, value))
  }, [drawerBounds])

  useEffect(() => {
    const move = (event: globalThis.PointerEvent) => {
      const resize = resizeRef.current
      if (!resize) return
      setDrawerWidth(clampDrawerWidth(resize.startWidth + resize.startX - event.clientX))
    }
    const stop = () => {
      resizeRef.current = undefined
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    const resize = () => {
      const nextLimits = drawerBounds()
      setDrawerLimits(nextLimits)
      setDrawerWidth((current) => Math.min(
        nextLimits.maximum,
        Math.max(nextLimits.minimum, current),
      ))
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
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
  }, [clampDrawerWidth, drawerBounds])

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(undefined)
    try {
      const result = await client.request<KnowledgeGraph[]>('/knowledge/graphs')
      setGraphs(result)
      setSelectedId((current) => (
        current && result.some((graph) => graph.id === current) ? current : undefined
      ))
    } catch (next) {
      setError(next)
    } finally {
      setLoading(false)
    }
  }, [client])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const selected = graphs.find((graph) => graph.id === selectedId)
  const focusedRelease = releases.find((release) => release.id === focusedReleaseId)

  useEffect(() => {
    if (!selected) {
      setReleases([])
      setFocusedReleaseId(undefined)
      setSnapshot(undefined)
      return
    }
    const controller = new AbortController()
    setDetailLoading(true)
    setError(undefined)
    setReleases([])
    setSnapshot(undefined)
    void client.request<KnowledgeRelease[]>(
      `/knowledge/graphs/${selected.id}/releases`,
      { cache: 'no-store', signal: controller.signal },
    )
      .then((nextReleases) => {
        if (controller.signal.aborted) return
        setReleases(nextReleases)
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

  useEffect(() => {
    if (!selected || !focusedReleaseId) {
      setSnapshot(undefined)
      return
    }
    const controller = new AbortController()
    setDetailLoading(true)
    setError(undefined)
    setSnapshot(undefined)
    void client.request<KnowledgeSnapshot>(
      `/knowledge/graphs/${selected.id}/releases/${focusedReleaseId}/snapshot?maximum_nodes=200`,
      { cache: 'no-store', signal: controller.signal },
    )
      .then((nextSnapshot) => {
        if (!controller.signal.aborted) setSnapshot(nextSnapshot)
      })
      .catch((next) => {
        if (!controller.signal.aborted) setError(next)
      })
      .finally(() => {
        if (!controller.signal.aborted) setDetailLoading(false)
      })
    return () => controller.abort()
  }, [client, focusedReleaseId, selected])

  const flowNodes = useMemo<FlowCanvasNode[]>(() => (snapshot?.nodes ?? []).map((node) => ({
    id: node.id,
    label: nodeLabel(node.properties, node.id),
    subtitle: `${node.entity_type} · 근거 ${node.provenance.length}`,
    kind: 'neutral',
  })), [snapshot])
  const flowEdges = useMemo<FlowCanvasEdge[]>(() => (snapshot?.edges ?? []).map((edge) => ({
    id: edge.id,
    source: edge.source_id,
    target: edge.target_id,
    label: edge.edge_type,
  })), [snapshot])

  const columns = useMemo<ColumnDef<KnowledgeGraph>[]>(() => [
    {
      accessorKey: 'id',
      header: 'ID',
      size: 250,
      enableSorting: false,
      cell: ({ row }) => <code className="text-[10px]">{row.original.id}</code>,
    },
    {
      accessorKey: 'name',
      header: 'Name',
      size: 220,
      cell: ({ row }) => <strong>{row.original.name}</strong>,
    },
    {
      id: 'domain',
      header: 'Domain',
      size: 170,
      accessorFn: (graph) => graph.domain_name ?? '기록 없음 (legacy)',
    },
    {
      accessorKey: 'status',
      header: 'Status',
      size: 110,
      cell: ({ row }) => <span className="badge badge-soft">{row.original.status}</span>,
    },
    {
      accessorKey: 'version',
      header: 'Version',
      size: 80,
      cell: ({ row }) => `v${row.original.version}`,
    },
    {
      id: 'actions',
      header: 'Actions',
      size: 120,
      enableSorting: false,
      cell: ({ row }) => (
        <div className="flex gap-1" onClick={(event) => event.stopPropagation()}>
          <button
            type="button"
            className="button button-secondary"
            title="Knowledge Studio에서 편집"
            aria-label={`${row.original.name} 에셋 편집`}
            onClick={() => onEdit(row.original.id)}
          >
            <Edit3 size={13} />
          </button>
          <button
            type="button"
            className="button button-secondary"
            title="지식 에셋 아카이빙"
            aria-label={`${row.original.name} 에셋 삭제`}
            onClick={() => setArchiveTarget(row.original)}
          >
            <Trash2 size={13} />
          </button>
        </div>
      ),
    },
  ], [onEdit])

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
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
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
      await archiveKnowledgeAsset(client, archiveTarget)
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
          ['오늘 추가된 노드', '집계 API 미제공'],
          ['오늘 추가된 관계', '집계 API 미제공'],
          ['수행된 적재 작업', '작업 API 미제공'],
        ].map(([label, value]) => (
          <article
            key={label}
            className="rounded-enterprise border border-slate-300 bg-white px-4 py-3 shadow-sm"
          >
            <span className="block text-[10px] font-black tracking-wide text-slate-500 uppercase">
              {label}
            </span>
            <strong className="mt-1 block text-sm text-navy-900">
              — <small className="font-normal text-slate-500">{value}</small>
            </strong>
          </article>
        ))}
      </div>
      <section className="rounded-enterprise border border-slate-300 bg-white p-4 shadow-sm">
        <header className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div>
            <span className="text-[10px] font-black tracking-[.14em] text-enterprise-blue uppercase">
              Asset list
            </span>
            <h2 className="my-1 text-lg font-black text-navy-900">지식 레지스트리</h2>
          </div>
          <button className="button" type="button" onClick={onCreate}>
            <Plus size={14} /> 에셋 추가
          </button>
        </header>
        <ErrorNotice error={error} />
        <div className="grid gap-4">
          <DenseDataTable
            caption="지식 에셋 목록"
            columns={columns}
            data={graphs}
            getRowId={(graph) => graph.id}
            loading={loading}
            selectedRowId={selectedId}
            onRowActivate={(graph) => setSelectedId(graph.id)}
          />
          {!selected && (
            <div className="grid min-h-36 place-items-center rounded-enterprise border border-dashed border-slate-300 bg-slate-50 text-center text-xs text-slate-500">
              <div>
                <Network className="mx-auto mb-2" />
                <p>에셋을 선택하면 우측 상세 패널을 엽니다.</p>
              </div>
            </div>
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
            className="fixed right-3 top-[68px] bottom-3 z-50 overflow-y-auto rounded-enterprise border border-slate-400 bg-white p-5 shadow-2xl max-md:right-0 max-md:top-0 max-md:bottom-0 max-md:w-full!"
            style={{ width: drawerWidth, maxWidth: 'calc(100vw - 12px)' }}
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
                  <dt className="text-[10px] font-black text-slate-500">Domain</dt>
                  <dd className="m-0">{selected.domain_name ?? '기록 없음 (legacy)'}</dd>
                </div>
                <div>
                  <dt className="text-[10px] font-black text-slate-500">Nodes</dt>
                  <dd className="m-0">{focusedRelease?.node_count ?? '—'}</dd>
                </div>
                <div>
                  <dt className="text-[10px] font-black text-slate-500">Edges</dt>
                  <dd className="m-0">{focusedRelease?.edge_count ?? '—'}</dd>
                </div>
                <div>
                  <dt className="text-[10px] font-black text-slate-500">Focused version</dt>
                  <dd className="m-0">
                    {focusedRelease ? `Release v${focusedRelease.release_no}` : '—'}
                  </dd>
                </div>
                <div>
                  <dt className="text-[10px] font-black text-slate-500">Creator</dt>
                  <dd className="m-0 break-all">{focusedRelease?.published_by ?? '—'}</dd>
                </div>
                <div>
                  <dt className="text-[10px] font-black text-slate-500">Created At</dt>
                  <dd className="m-0">{localTime(focusedRelease?.published_at)}</dd>
                </div>
              </dl>
              <AccordionItem
                itemId="version-history"
                title="버전 이력"
                summary={`${releases.length} releases`}
                expanded={expandedSections.has('version-history')}
                onToggle={() => toggleSection('version-history')}
              >
                {releases.length ? (
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
                        {[...releases]
                          .sort((left, right) => right.release_no - left.release_no)
                          .map((release) => {
                            const current = release.id === selected.active_release_id
                            const focused = release.id === focusedReleaseId
                            return (
                              <tr
                                key={release.id}
                                className={`border-b border-slate-200 ${
                                  focused ? 'bg-blue-50' : 'hover:bg-slate-50'
                                }`}
                              >
                                <td className="p-2 font-bold">v{release.release_no}</td>
                                <td className="p-2">
                                  {current
                                    ? (
                                        <span className="rounded-full bg-emerald-100 px-2 py-1 text-[10px] font-black text-emerald-800">
                                          CURRENT
                                        </span>
                                      )
                                    : <span className="text-slate-500">HISTORICAL</span>}
                                </td>
                                <td className="max-w-36 truncate p-2" title={release.published_by}>
                                  {release.published_by}
                                </td>
                                <td className="whitespace-nowrap p-2">
                                  {localTime(release.published_at)}
                                </td>
                                <td className="p-2">
                                  <button
                                    type="button"
                                    className="button button-secondary"
                                    aria-pressed={focused}
                                    onClick={() => setFocusedReleaseId(release.id)}
                                  >
                                    {focused ? '포커스됨' : '미리보기'}
                                  </button>
                                </td>
                              </tr>
                            )
                          })}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="m-0 text-xs text-slate-500">발행된 릴리스가 없습니다.</p>
                )}
              </AccordionItem>
              <AccordionItem
                itemId="graph-preview"
                title="그래프 미리보기"
                summary={detailLoading
                  ? '불러오는 중'
                  : snapshot
                    ? `${snapshot.nodes.length} nodes`
                    : '미발행'}
                expanded={expandedSections.has('graph-preview')}
                onToggle={() => toggleSection('graph-preview')}
              >
                <FlowCanvas
                  ariaLabel="선택 버전 그래프 미리보기"
                  nodes={flowNodes}
                  edges={flowEdges}
                  height={420}
                  showMiniMap
                />
              </AccordionItem>
              <AccordionItem
                itemId="ingestion-history"
                title="Ingestion 기록과 연결 Source"
                summary="read API 연결 전"
                expanded={expandedSections.has('ingestion-history')}
                onToggle={() => toggleSection('ingestion-history')}
              >
                <p className="m-0 text-xs text-slate-500">
                  Version-pinned binding/run summary API가 연결된 뒤 표시합니다.
                </p>
              </AccordionItem>
              <AccordionItem
                itemId="typed-api"
                title="Endpoint API"
                summary="capability 확인 필요"
                expanded={expandedSections.has('typed-api')}
                onToggle={() => toggleSection('typed-api')}
              >
                <p className="m-0 text-xs text-slate-500">
                  서버가 허용한 상대 경로만 표시하며 provider URL, credential 또는 Bolt 주소는
                  노출하지 않습니다.
                </p>
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
