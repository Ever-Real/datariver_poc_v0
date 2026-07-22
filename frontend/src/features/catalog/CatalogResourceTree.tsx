import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Box, ChevronDown, ChevronRight, Database, Layers3, Table2 } from 'lucide-react'
import type { ApiClient } from '../../api/client'
import type { CatalogTreeNode, CatalogTreePage } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { TruncatedText } from '../../components/common/TruncatedText'

interface Branch {
  items: CatalogTreeNode[]
  nextCursor?: string
  truncated?: boolean
}

const maximumBranchItems = 200
const maximumExpandedBranches = 8

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
      if (branches[node.id] && !keys.has(node.id)) {
        keys.add(node.id)
        pending.push(node.id)
      }
    }
  }
  return keys
}

function branchKey(node?: CatalogTreeNode): string {
  return node?.id ?? 'ROOT'
}

function treePath(node: CatalogTreeNode): string {
  const parameters = new URLSearchParams({ parent_kind: node.kind, limit: '100' })
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
}: {
  client: ApiClient
  selectedAssetId?: string
  onSelectAsset: (assetId: string) => void
}) {
  const [branches, setBranches] = useState<Record<string, Branch>>({})
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState<Set<string>>(new Set())
  const [error, setError] = useState<unknown>()
  const generation = useRef(0)
  const controllers = useRef(new Map<string, AbortController>())
  const activeBranchKeys = useRef(new Set<string>())
  const expandedOrder = useRef<string[]>([])

  const loadBranch = useCallback(async (
    parent?: CatalogTreeNode,
    append = false,
    expectedGeneration = generation.current,
  ) => {
    const key = branchKey(parent)
    if (controllers.current.has(key)) return
    const controller = new AbortController()
    controllers.current.set(key, controller)
    setLoading((current) => new Set(current).add(key)); setError(undefined)
    try {
      const parameters = new URLSearchParams(parent ? treePath(parent) : 'parent_kind=ROOT&limit=100')
      const cursor = append ? branches[key]?.nextCursor : undefined
      if (cursor) parameters.set('cursor', cursor)
      const page = await client.request<CatalogTreePage>(`/catalog/tree/nodes?${parameters}`, {
        signal: controller.signal,
      })
      if (expectedGeneration !== generation.current) return
      if (key !== 'ROOT' && !activeBranchKeys.current.has(key)) return
      setBranches((current) => {
        const items = (append ? [...(current[key]?.items ?? []), ...page.items] : page.items)
          .slice(0, maximumBranchItems)
        const truncated = Boolean(page.page.next_cursor) && items.length >= maximumBranchItems
        return {
          ...current,
          [key]: {
            items,
            ...(!truncated && page.page.next_cursor ? { nextCursor: page.page.next_cursor } : {}),
            ...(truncated ? { truncated: true } : {}),
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
  }, [branches, client])

  useEffect(() => {
    const activeControllers = controllers.current
    generation.current += 1
    const currentGeneration = generation.current
    activeControllers.forEach((controller) => controller.abort())
    activeControllers.clear()
    activeBranchKeys.current.clear()
    expandedOrder.current = []
    setBranches({}); setExpanded(new Set()); setLoading(new Set()); setError(undefined)
    void loadBranch(undefined, false, currentGeneration)
    return () => {
      generation.current += 1
      activeControllers.forEach((controller) => controller.abort())
      activeControllers.clear()
    }
    // The Resource Tree is a standalone authorized hierarchy.  Search filters
    // never narrow it or mutate the active Search Results filter state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client])

  const toggle = (node: CatalogTreeNode) => {
    if (node.kind === 'ASSET') { if (node.asset) onSelectAsset(node.asset.id); return }
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
      | { type: 'MORE'; parent: CatalogTreeNode; depth: number }
      | { type: 'LIMIT'; parent: CatalogTreeNode; depth: number }
    > = []
    const visit = (items: CatalogTreeNode[], depth: number) => {
      for (const node of items) {
        flattened.push({ type: 'NODE', node, depth })
        if (expanded.has(node.id)) {
          visit(branches[node.id]?.items ?? [], depth + 1)
          if (branches[node.id]?.nextCursor) {
            flattened.push({ type: 'MORE', parent: node, depth: depth + 1 })
          }
          if (branches[node.id]?.truncated) {
            flattened.push({ type: 'LIMIT', parent: node, depth: depth + 1 })
          }
        }
      }
    }
    visit(branches.ROOT?.items ?? [], 0)
    return flattened
  }, [branches, expanded])

  return <aside className="catalog-tree panel" aria-label="Resource Tree">
    <header><div><span className="eyebrow">Canonical hierarchy</span><h2>Resource Tree</h2></div><span>{rows.length}</span></header>
    <ErrorNotice error={error} />
    <div className="catalog-tree-rows" aria-busy={loading.size > 0}>
      {rows.map((row) => {
        if (row.type === 'LIMIT') return <div
          key={`${row.parent.id}-limit`}
          className="catalog-tree-state"
          style={{ paddingLeft: `${8 + row.depth * 12}px` }}
        >메모리 보호를 위해 이 분기의 200개 항목만 표시합니다. 검색을 사용하세요.</div>
        if (row.type === 'MORE') return <button
          key={`${row.parent.id}-more`}
          type="button"
          className="tree-load-more"
          style={{ paddingLeft: `${8 + row.depth * 12}px` }}
          onClick={() => void loadBranch(row.parent, true)}
        ><span className="tree-expander" /><span>+</span><span>하위 항목 더 보기</span></button>
        const { node, depth } = row
        const isExpanded = expanded.has(node.id)
        return <button
          key={node.id}
          type="button"
          className={`${node.asset?.id === selectedAssetId ? 'selected' : ''} tree-kind-${node.kind.toLowerCase()}`}
          style={{ paddingLeft: `${8 + depth * 12}px` }}
          aria-expanded={node.has_children ? isExpanded : undefined}
          onClick={() => toggle(node)}
        >
          <span className="tree-expander" aria-hidden="true">{node.has_children ? (isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />) : null}</span>
          <NodeIcon kind={node.kind} />
          <TruncatedText value={node.label} />
          <span className="tree-count">{node.asset_count.toLocaleString()}</span>
        </button>
      })}
      {loading.has('ROOT') && <div className="catalog-tree-state">계층을 불러오는 중입니다.</div>}
      {!loading.has('ROOT') && rows.length === 0 && <div className="catalog-tree-state">표시할 권한 범위의 계층이 없습니다.</div>}
    </div>
    {branches.ROOT?.nextCursor && <button className="tree-more" type="button" onClick={() => void loadBranch(undefined, true)}>플랫폼 더 보기</button>}
    {branches.ROOT?.truncated && <p className="catalog-tree-state">메모리 보호를 위해 플랫폼 200개만 표시합니다.</p>}
  </aside>
}
