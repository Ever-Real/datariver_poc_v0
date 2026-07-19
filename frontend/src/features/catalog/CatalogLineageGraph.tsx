import { useMemo } from 'react'
import type { CatalogAsset, CatalogLineage } from '../../api/types'

const NODE_WIDTH = 248
const NODE_HEIGHT = 58
const NODE_GAP = 78
const CANVAS_WIDTH = 1_180
const COLUMNS = {
  UPSTREAM: 18,
  CENTER: 314,
  DOWNSTREAM: 610,
  RELATED: 906,
} as const

export type LineageNodeRole = keyof typeof COLUMNS

export interface PositionedLineageNode {
  asset: CatalogAsset
  role: LineageNodeRole
  x: number
  y: number
}

interface LineageLayout {
  height: number
  nodes: PositionedLineageNode[]
}

function reach(
  start: string,
  adjacency: Map<string, string[]>,
  role: Exclude<LineageNodeRole, 'CENTER'>,
  roles: Map<string, LineageNodeRole>,
) {
  const queue = [start]
  while (queue.length) {
    const current = queue.shift()
    if (!current) continue
    for (const adjacent of adjacency.get(current) ?? []) {
      if (roles.has(adjacent)) continue
      roles.set(adjacent, role)
      queue.push(adjacent)
    }
  }
}

export function layoutLineage(lineage: CatalogLineage): LineageLayout {
  const upstream = new Map<string, string[]>()
  const downstream = new Map<string, string[]>()
  for (const edge of lineage.edges) {
    upstream.set(edge.target_asset_id, [...(upstream.get(edge.target_asset_id) ?? []), edge.source_asset_id])
    downstream.set(edge.source_asset_id, [...(downstream.get(edge.source_asset_id) ?? []), edge.target_asset_id])
  }
  const roles = new Map<string, LineageNodeRole>([[lineage.center_asset_id, 'CENTER']])
  reach(lineage.center_asset_id, upstream, 'UPSTREAM', roles)
  reach(lineage.center_asset_id, downstream, 'DOWNSTREAM', roles)
  for (const node of lineage.nodes) if (!roles.has(node.id)) roles.set(node.id, 'RELATED')

  const byRole = new Map<LineageNodeRole, CatalogAsset[]>(
    (Object.keys(COLUMNS) as LineageNodeRole[]).map((role) => [role, []]),
  )
  for (const node of lineage.nodes) byRole.get(roles.get(node.id) ?? 'RELATED')?.push(node)
  for (const nodes of byRole.values()) nodes.sort((left, right) => left.name.localeCompare(right.name))

  const maximumRows = Math.max(1, ...Array.from(byRole.values(), (nodes) => nodes.length))
  const height = Math.max(230, maximumRows * NODE_GAP + 28)
  const nodes = (Object.keys(COLUMNS) as LineageNodeRole[]).flatMap((role) =>
    (byRole.get(role) ?? []).map((asset, index) => ({
      asset,
      role,
      x: COLUMNS[role],
      y: 18 + index * NODE_GAP,
    })),
  )
  return { height, nodes }
}

export function CatalogLineageGraph({
  lineage,
  onSelectAsset,
  onOpenDataHubLineage,
}: {
  lineage: CatalogLineage
  onSelectAsset: (assetId: string) => void
  onOpenDataHubLineage?: (assetId: string) => void
}) {
  const layout = useMemo(() => layoutLineage(lineage), [lineage])
  const byId = useMemo(() => new Map(layout.nodes.map((node) => [node.asset.id, node])), [layout.nodes])

  return (
    <div className="catalog-lineage-graph" aria-label="권한 필터링된 Lineage 그래프">
      <div className="catalog-lineage-canvas" style={{ height: layout.height }}>
        <svg aria-hidden="true" className="catalog-lineage-edges" viewBox={`0 0 ${CANVAS_WIDTH} ${layout.height}`}>
          <defs>
            <marker id="catalog-lineage-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
              <path d="M0,0 L7,3.5 L0,7 Z" />
            </marker>
          </defs>
          {lineage.edges.map((edge) => {
            const source = byId.get(edge.source_asset_id)
            const target = byId.get(edge.target_asset_id)
            if (!source || !target) return null
            const fromX = source.x + NODE_WIDTH
            const fromY = source.y + NODE_HEIGHT / 2
            const toX = target.x
            const toY = target.y + NODE_HEIGHT / 2
            const bend = Math.max(42, Math.abs(toX - fromX) / 2)
            return <path key={`${edge.source_asset_id}-${edge.target_asset_id}`} d={`M ${fromX} ${fromY} C ${fromX + bend} ${fromY}, ${toX - bend} ${toY}, ${toX} ${toY}`} markerEnd="url(#catalog-lineage-arrow)" />
          })}
        </svg>
        {layout.nodes.map((node) => (
          <article
            className={`catalog-lineage-node catalog-lineage-node-${node.role.toLowerCase()}`}
            key={node.asset.id}
            style={{ left: node.x, top: node.y, width: NODE_WIDTH, minHeight: NODE_HEIGHT }}
          >
            <button
              aria-label={`${node.asset.name} 선택`}
              className="catalog-lineage-node-select"
              onClick={() => onSelectAsset(node.asset.id)}
              title={`${node.asset.name} 상세 정보 열기`}
              type="button"
            >
              <span className="catalog-lineage-node-role">{node.role}</span>
              <strong>{node.asset.name}</strong>
              <small>{node.asset.platform ?? 'platform 미지정'} · {node.asset.schema_name ?? node.asset.asset_type}</small>
            </button>
            {onOpenDataHubLineage ? (
              <button
                aria-label={`${node.asset.name} 상세`}
                className="catalog-lineage-node-detail"
                onClick={() => onOpenDataHubLineage(node.asset.id)}
                title="DataHub Lineage 상세 보기"
                type="button"
              >
                상세
              </button>
            ) : null}
          </article>
        ))}
      </div>
    </div>
  )
}
