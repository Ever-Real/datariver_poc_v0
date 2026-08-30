import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Box, ChevronDown, ChevronRight, Database, Layers3, RefreshCw, Table2 } from 'lucide-react'
import type { ApiClient } from '../../api/client'
import type { CatalogAsset, CatalogSearch, CatalogTreeNode, CatalogTreePage } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { CursorPagination } from '../../components/common/CursorPagination'
import { TruncatedText } from '../../components/common/TruncatedText'
import { GlobalCatalogSearch } from '../../components/layout/GlobalCatalogSearch'

interface Branch {
  items: CatalogTreeNode[]
  nextCursor?: string
}

const maximumBranchPageItems = 200
const maximumExpandedBranches = 8
const treeRowHeight = 26
const treeRowOverscan = 8
const defaultTreeViewportHeight = 520
const treeSpacerRowCounts = [8_192, 4_096, 2_048, 1_024, 512, 256, 128, 64, 32, 16, 8, 4, 2, 1] as const

function spacerRowCounts(rowCount: number): number[] {
  const spacers: number[] = []
  let remaining = rowCount
  for (const size of treeSpacerRowCounts) {
    while (remaining >= size) {
      spacers.push(size)
      remaining -= size
    }
  }
  return spacers
}

function uniqueNodes(
  existing: CatalogTreeNode[],
  appended: CatalogTreeNode[],
): CatalogTreeNode[] {
  const seen = new Set(existing.map((node) => node.id))
  const unique = [...existing]
  for (const node of appended) {
    if (seen.has(node.id)) continue
    seen.add(node.id)
    unique.push(node)
  }
  return unique
}

function withoutBranchTree(branches: Record<string, Branch>, rootKey: string): Record<string, Branch> {
  const next = { ...branches }
  const pending = [rootKey]
  while (pending.length > 0) {
    const key = pending.pop()
    if (!key) continue
    const branch = next[key]
    if (branch) {
      for (const node of branch.items) {
        if (next[node.id]) pending.push(node.id)
      }
    }
    delete next[key]
  }
  return next
}

function branchTreeKeys(branches: Record<string, Branch>, rootKey: string): Set<string> {
  const keys = new Set([rootKey])
  const pending = [rootKey]
  while (pending.length > 0) {
    const key = pending.pop()
    if (!key) continue
    for (const node of branches[key]?.items ?? []) {
      if (!keys.has(node.id)) {
        keys.add(node.id)
        if (branches[node.id]) pending.push(node.id)
      }
    }
  }
  return keys
}

function branchKey(node?: CatalogTreeNode): string {
  return node?.id ?? 'ROOT'
}

function treePath(node: CatalogTreeNode): string {
  const parameters = new URLSearchParams({ parent_kind: node.kind, limit: '200' })
  if (node.platform) parameters.set('platform', node.platform)
  if (node.database_name) parameters.set('database', node.database_name)
  if (node.schema_name) parameters.set('schema', node.schema_name)
  return parameters.toString()
}

function NodeIcon({ kind }: { kind: CatalogTreeNode['kind'] }) {
  const props = { size: 13, 'aria-hidden': true as const }
  if (kind === 'PLATFORM') return <Layers3 {...props} />
  if (kind === 'DATABASE') return <Database {...props} />
  if (kind === 'SCHEMA') return <Box {...props} />
  return <Table2 {...props} />
}

export function CatalogResourceTree({
  client,
  selectedAssetId,
  onSelectAsset,
  onSelectScope,
  searchable = false,
  searchIdPrefix = 'resource-tree',
  searchLabel = 'Resource Tree 검색',
  onRefresh,
}: {
  client: ApiClient
  selectedAssetId?: string
  onSelectAsset: (assetId: string, asset?: CatalogAsset) => void
  onSelectScope?: (node: CatalogTreeNode) => void
  searchable?: boolean
  searchIdPrefix?: string
  searchLabel?: string
  onRefresh?: () => void
}) {
  const [branches, setBranches] = useState<Record<string, Branch>>({})
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState<Set<string>>(new Set())
  const [error, setError] = useState<unknown>()
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResult, setSearchResult] = useState<CatalogSearch>()
  const [searchLoading, setSearchLoading] = useState(false)
  const [searchCursors, setSearchCursors] = useState<Array<string | undefined>>([undefined])
  const [searchPageIndex, setSearchPageIndex] = useState(0)
  const [searchResetGeneration, setSearchResetGeneration] = useState(0)
  const [hierarchyRefreshGeneration, setHierarchyRefreshGeneration] = useState(0)
  const [treeViewport, setTreeViewport] = useState({
    height: defaultTreeViewportHeight,
    scrollTop: 0,
  })
  const [retainedRowKey, setRetainedRowKey] = useState<string>()
  const generation = useRef(0)
  const controllers = useRef(new Map<string, AbortController>())
  const activeBranchKeys = useRef(new Set<string>())
  const expandedOrder = useRef<string[]>([])
  const hierarchyRows = useRef<HTMLDivElement>(null)

  const loadBranch = useCallback(async (
    parent?: CatalogTreeNode,
    cursor?: string,
    expectedGeneration = generation.current,
    forceCurrent = false,
  ) => {
    const key = branchKey(parent)
    if (controllers.current.has(key)) return
    const controller = new AbortController()
    controllers.current.set(key, controller)
    setLoading((current) => new Set(current).add(key)); setError(undefined)
    try {
      const parameters = new URLSearchParams(parent ? treePath(parent) : 'parent_kind=ROOT&limit=200')
      if (!parent && forceCurrent) parameters.set('refresh', 'true')
      if (cursor !== undefined) parameters.set('cursor', cursor)
      const page = await client.request<CatalogTreePage>(`/catalog/tree/nodes?${parameters}`, {
        signal: controller.signal,
      })
      if (expectedGeneration !== generation.current) return
      if (key !== 'ROOT' && !activeBranchKeys.current.has(key)) return
      if (page.page.limit > maximumBranchPageItems || page.items.length > page.page.limit) {
        throw new Error('Resource Tree 응답이 요청한 페이지 제한을 초과했습니다.')
      }
      if (cursor !== undefined && page.page.next_cursor === cursor) {
        setBranches((current) => {
          const branch = current[key]
          if (!branch) return current
          return { ...current, [key]: { items: branch.items } }
        })
        throw new Error('Resource Tree 응답의 다음 커서가 진행되지 않았습니다.')
      }
      setBranches((current) => {
        const existing = current[key]?.items ?? []
        const mergedItems = uniqueNodes(cursor === undefined ? [] : existing, page.items)
        return {
          ...current,
          [key]: {
            items: mergedItems,
            ...(page.page.next_cursor ? { nextCursor: page.page.next_cursor } : {}),
          },
        }
      })
    } catch (next) {
      if (!controller.signal.aborted && expectedGeneration === generation.current) setError(next)
    } finally {
      if (controllers.current.get(key) === controller) controllers.current.delete(key)
      if (expectedGeneration === generation.current && !controllers.current.has(key)) {
        setLoading((current) => { const next = new Set(current); next.delete(key); return next })
      }
    }
  }, [client])

  const appendBranch = (parent: CatalogTreeNode | undefined) => {
    const key = branchKey(parent)
    const branch = branches[key]
    if (!branch || !branch.nextCursor || controllers.current.has(key)) return
    void loadBranch(parent, branch.nextCursor)
  }

  useEffect(() => {
    const activeControllers = controllers.current
    generation.current += 1
    const currentGeneration = generation.current
    activeControllers.forEach((controller) => controller.abort())
    activeControllers.clear()
    activeBranchKeys.current.clear()
    expandedOrder.current = []
    if (hierarchyRows.current) hierarchyRows.current.scrollTop = 0
    setTreeViewport((current) => ({ ...current, scrollTop: 0 }))
    setRetainedRowKey(undefined)
    setBranches({}); setExpanded(new Set()); setLoading(new Set()); setError(undefined)
    void loadBranch(undefined, undefined, currentGeneration, hierarchyRefreshGeneration > 0)
    return () => {
      generation.current += 1
      activeControllers.forEach((controller) => controller.abort())
      activeControllers.clear()
    }
    // The Resource Tree is a standalone authorized hierarchy.  Search filters
    // never narrow it or mutate the active Search Results filter state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, hierarchyRefreshGeneration])

  useEffect(() => {
    if (!searchable || !searchQuery) {
      setSearchResult(undefined)
      setSearchLoading(false)
      return
    }
    const controller = new AbortController()
    const parameters = new URLSearchParams({ q: searchQuery, limit: '25' })
    const cursor = searchCursors[searchPageIndex]
    if (cursor) parameters.set('cursor', cursor)
    setSearchLoading(true)
    setError(undefined)
    void client.request<CatalogSearch>(`/catalog/assets?${parameters.toString()}`, {
      signal: controller.signal,
    }).then((value) => {
      if (!controller.signal.aborted) setSearchResult(value)
    }).catch((next: unknown) => {
      if (!controller.signal.aborted) setError(next)
    }).finally(() => {
      if (!controller.signal.aborted) setSearchLoading(false)
    })
    return () => controller.abort()
  }, [client, searchCursors, searchPageIndex, searchQuery, searchable])

  useEffect(() => {
    const element = hierarchyRows.current
    if (!element || searchQuery) return
    const measure = () => {
      setTreeViewport((current) => ({
        ...current,
        height: element.clientHeight || defaultTreeViewportHeight,
      }))
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [searchQuery])

  /**
   * ROOT 브랜치 로드 완료 후 1단계 노드를 자동으로 펼침.
   * 하위 항목이 있는 플랫폼 노드를 최대 maximumExpandedBranches 개까지 자동 확장합니다.
   */
  useEffect(() => {
    const rootItems = branches.ROOT?.items
    if (!rootItems || rootItems.length === 0) return
    // 아직 아무것도 펼쳐지지 않았을 때만 자동 확장 (사용자 조작 후에는 재실행하지 않음)
    if (expanded.size > 0) return
    const toExpand = rootItems
      .filter((node) => node.has_children && node.kind !== 'ASSET')
      .slice(0, maximumExpandedBranches)
    if (toExpand.length === 0) return
    const keys = toExpand.map((node) => node.id)
    keys.forEach((key) => activeBranchKeys.current.add(key))
    expandedOrder.current = keys
    setExpanded(new Set(keys))
    // 각 1단계 노드의 하위 항목 사전 로드
    toExpand.forEach((node) => { if (!branches[node.id]) void loadBranch(node) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [branches.ROOT])

  const toggle = (node: CatalogTreeNode) => {
    if (node.kind === 'ASSET') return
    const key = branchKey(node)
    const isExpanded = expanded.has(key)
    if (isExpanded) {
      const removed = branchTreeKeys(branches, key)
      removed.forEach((removedKey) => {
        activeBranchKeys.current.delete(removedKey)
        controllers.current.get(removedKey)?.abort()
        controllers.current.delete(removedKey)
      })
      expandedOrder.current = expandedOrder.current.filter((item) => !removed.has(item))
      setExpanded((current) => new Set([...current].filter((item) => !removed.has(item))))
      setBranches((current) => withoutBranchTree(current, key))
      return
    }

    let evicted: string | undefined
    if (expandedOrder.current.length >= maximumExpandedBranches) {
      evicted = expandedOrder.current.shift()
    }
    const evictedKeys = evicted ? branchTreeKeys(branches, evicted) : new Set<string>()
    evictedKeys.forEach((removedKey) => {
      activeBranchKeys.current.delete(removedKey)
      controllers.current.get(removedKey)?.abort()
      controllers.current.delete(removedKey)
    })
    expandedOrder.current = expandedOrder.current.filter((item) => !evictedKeys.has(item))
    activeBranchKeys.current.add(key)
    expandedOrder.current.push(key)
    setExpanded((current) => {
      const next = new Set(current)
      evictedKeys.forEach((removedKey) => next.delete(removedKey))
      next.add(key)
      return next
    })
    if (evicted) setBranches((current) => withoutBranchTree(current, evicted))
    if (!branches[key]) void loadBranch(node)
  }

  const rows = useMemo(() => {
    const flattened: Array<
      { type: 'NODE'; node: CatalogTreeNode; depth: number }
      | { type: 'PAGINATION'; parent: CatalogTreeNode; depth: number }
    > = []
    const visit = (items: CatalogTreeNode[], depth: number) => {
      for (const node of items) {
        flattened.push({ type: 'NODE', node, depth })
        if (expanded.has(node.id)) {
          visit(branches[node.id]?.items ?? [], depth + 1)
          const branch = branches[node.id]
          if (branch && branch.nextCursor) {
            flattened.push({ type: 'PAGINATION', parent: node, depth: depth + 1 })
          }
        }
      }
    }
    visit(branches.ROOT?.items ?? [], 0)
    return flattened
  }, [branches, expanded])

  const visibleRows = useMemo(() => {
    const maximumScrollTop = Math.max(0, rows.length * treeRowHeight - treeViewport.height)
    const scrollTop = Math.min(treeViewport.scrollTop, maximumScrollTop)
    const first = Math.max(0, Math.floor(scrollTop / treeRowHeight) - treeRowOverscan)
    const last = Math.min(
      rows.length,
      Math.ceil((scrollTop + treeViewport.height) / treeRowHeight) + treeRowOverscan,
    )
    const indexes = new Set(Array.from({ length: Math.max(0, last - first) }, (_, offset) => first + offset))
    if (retainedRowKey) {
      const retainedIndex = rows.findIndex((row) => (
        row.type === 'NODE' ? row.node.id : `${row.parent.id}-pagination`
      ) === retainedRowKey)
      if (retainedIndex >= 0) indexes.add(retainedIndex)
    }
    return [...indexes].sort((left, right) => left - right).map((index) => ({ index, row: rows[index]! }))
  }, [retainedRowKey, rows, treeViewport])

  const windowRows = useMemo(() => {
    const rendered: Array<
      { type: 'ROW'; index: number; row: (typeof rows)[number] }
      | { type: 'SPACER'; key: string; rowCount: number }
    > = []
    let nextRowIndex = 0
    let spacerIndex = 0
    const appendSpacers = (rowCount: number) => {
      for (const size of spacerRowCounts(rowCount)) {
        rendered.push({
          type: 'SPACER',
          key: `spacer-${nextRowIndex}-${spacerIndex}`,
          rowCount: size,
        })
        spacerIndex += 1
      }
    }
    for (const visible of visibleRows) {
      appendSpacers(visible.index - nextRowIndex)
      rendered.push({ type: 'ROW', ...visible })
      nextRowIndex = visible.index + 1
    }
    appendSpacers(rows.length - nextRowIndex)
    return rendered
  }, [rows, visibleRows])

  const resetSearch = () => {
    setSearchQuery('')
    setSearchResult(undefined)
    setSearchCursors([undefined])
    setSearchPageIndex(0)
    setSearchResetGeneration((current) => current + 1)
  }
  const rootBranch = branches.ROOT

  return <aside className="catalog-tree panel" aria-label="Resource Tree">
    <header><div><span className="eyebrow">Canonical hierarchy</span><h2>Resource Tree</h2></div><div className="catalog-tree-header-actions"><span>{searchQuery ? searchResult?.total ?? 0 : rows.filter((row) => row.type === 'NODE').length}</span><button
      aria-label="현재 DataHub 기준으로 Resource Tree 새로고침"
      className="button button-secondary"
      disabled={loading.size > 0}
      onClick={() => {
        onRefresh?.()
        setHierarchyRefreshGeneration((current) => current + 1)
      }}
      type="button"
    ><RefreshCw size={12} aria-hidden="true" />새로고침</button></div></header>
    {searchable && <div className="catalog-tree-search">
      <GlobalCatalogSearch
        key={`${searchIdPrefix}-${searchResetGeneration}`}
        client={client}
        idPrefix={searchIdPrefix}
        searchLabel={searchLabel}
        inputLabel={searchLabel}
        placeholder="스키마·테이블·컬럼 검색..."
        maxLength={200}
        onSearch={(value) => {
          setSearchQuery(value)
          setSearchCursors([undefined])
          setSearchPageIndex(0)
        }}
      />
      {searchQuery && <div className="catalog-tree-search-heading">
        <strong>“{searchQuery}” 검색 결과</strong>
        <button className="button button-secondary" type="button" onClick={resetSearch}>전체 계층 보기</button>
      </div>}
    </div>}
    <ErrorNotice error={error} />
    {searchQuery ? <>
      <div className="catalog-tree-search-results" aria-busy={searchLoading}>
        {searchResult?.items.map((asset) => <button
          key={asset.id}
          type="button"
          className={asset.id === selectedAssetId ? 'selected' : ''}
          onClick={() => onSelectAsset(asset.id, asset)}
        >
          <Table2 size={13} aria-hidden="true" />
          <span><TruncatedText value={asset.name} /><small>{[asset.platform, asset.database_name, asset.schema_name].filter(Boolean).join(' · ') || '위치 정보 없음'}</small></span>
        </button>)}
        {searchLoading && <div className="catalog-tree-state" role="status">검색 중입니다.</div>}
        {!searchLoading && searchResult?.items.length === 0 && <div className="catalog-tree-state">검색 조건에 맞는 자산이 없습니다.</div>}
      </div>
      <CursorPagination
        page={searchPageIndex + 1}
        pageSize={25}
        pageSizeOptions={[25]}
        itemCount={searchResult?.items.length ?? 0}
        canPrevious={searchPageIndex > 0}
        canNext={Boolean(searchResult?.page.next_cursor)}
        onPrevious={() => setSearchPageIndex((current) => Math.max(0, current - 1))}
        onNext={() => {
          const cursor = searchResult?.page.next_cursor
          if (!cursor) return
          setSearchCursors((current) => [...current.slice(0, searchPageIndex + 1), cursor])
          setSearchPageIndex((current) => current + 1)
        }}
        onPageSizeChange={() => undefined}
        label="Resource Tree 검색 결과 페이지 탐색"
      />
    </> : <div
      ref={hierarchyRows}
      className="catalog-tree-rows"
      aria-busy={loading.size > 0}
      onBlurCapture={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setRetainedRowKey(undefined)
      }}
      onFocusCapture={(event) => {
        setRetainedRowKey((event.target as HTMLElement).closest<HTMLElement>('[data-tree-row-key]')?.dataset.treeRowKey)
      }}
      onScroll={(event) => {
        const element = event.currentTarget
        setTreeViewport({
          height: element.clientHeight || defaultTreeViewportHeight,
          scrollTop: element.scrollTop,
        })
      }}
    >
      {rows.length > 0 && <div className="catalog-tree-window">
      {windowRows.map((windowRow) => {
        if (windowRow.type === 'SPACER') return <div
          key={windowRow.key}
          aria-hidden="true"
          className={`tree-row-spacer tree-row-spacer-${windowRow.rowCount}`}
        />
        const { index, row } = windowRow
        if (row.type === 'PAGINATION') {
          const branch = branches[row.parent.id]
          if (!branch) return null
          const isLoading = loading.has(row.parent.id)
          return <div
            key={`${row.parent.id}-pagination`}
            className={`tree-node-row tree-depth-${Math.min(row.depth, 3)}`}
            data-tree-row-index={index}
            data-tree-row-key={`${row.parent.id}-pagination`}
          >
            <span className="tree-expander-placeholder" aria-hidden="true" />
            <button
              type="button"
              className="tree-more-button"
              aria-label={`${row.parent.label} 하위 항목 ${isLoading ? '불러오는 중' : '더 보기'}`}
              disabled={isLoading || !branch.nextCursor}
              onClick={() => appendBranch(row.parent)}
            >
              {isLoading ? '불러오는 중…' : '더 보기'}
            </button>
          </div>
        }
        const { node, depth } = row
        const isExpanded = expanded.has(node.id)
        const isSelected = Boolean(node.asset?.id && node.asset.id === selectedAssetId)
        return <div
          key={node.id}
          className={`tree-node-row ${isSelected ? 'selected' : ''} tree-kind-${node.kind.toLowerCase()} tree-depth-${Math.min(depth, 3)}`}
          data-tree-row-index={index}
          data-tree-row-key={node.id}
        >
          {node.has_children ? <button
            aria-expanded={isExpanded}
            aria-label={`${node.label} 하위 항목 ${isExpanded ? '접기' : '펼치기'}`}
            className="tree-expander"
            onClick={() => toggle(node)}
            type="button"
          >{isExpanded ? <ChevronDown size={12} aria-hidden="true" /> : <ChevronRight size={12} aria-hidden="true" />}</button> : <span className="tree-expander-placeholder" aria-hidden="true" />}
          <NodeIcon kind={node.kind} />
          {node.kind === 'ASSET' && node.asset ? <button
            aria-pressed={isSelected}
            className="tree-title"
            onClick={() => onSelectAsset(node.asset!.id, node.asset ?? undefined)}
            type="button"
          ><TruncatedText value={node.label} /></button> : onSelectScope ? <button
            className="tree-title"
            onClick={() => onSelectScope(node)}
            type="button"
          ><TruncatedText value={node.label} /></button> : <span className="tree-title"><TruncatedText value={node.label} /></span>}
          <span className="tree-count">{node.asset_count.toLocaleString()}</span>
        </div>
      })}
      </div>}
      {loading.has('ROOT') && <div className="catalog-tree-state">계층을 불러오는 중입니다.</div>}
      {!loading.has('ROOT') && rows.length === 0 && <div className="catalog-tree-state">표시할 권한 범위의 계층이 없습니다.</div>}
    </div>}
    {!searchQuery && rootBranch && (
      rootBranch.nextCursor
    ) && <div className="tree-node-row tree-root-pagination">
      <span className="tree-expander-placeholder" aria-hidden="true" />
      <button
        type="button"
        className="tree-more-button"
        aria-label={`플랫폼 ${loading.has('ROOT') ? '불러오는 중' : '더 보기'}`}
        disabled={loading.has('ROOT') || !rootBranch.nextCursor}
        onClick={() => appendBranch(undefined)}
      >
        {loading.has('ROOT') ? '불러오는 중…' : '더 보기'}
      </button>
    </div>}
  </aside>
}
