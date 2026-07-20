import type { CatalogAsset, CatalogLineage } from '../../api/types'

export const LINEAGE_NODE_WIDTH = 248
export const LINEAGE_NODE_HEIGHT = 58
const HORIZONTAL_GAP = 36
const VERTICAL_GAP = 58
export const LINEAGE_CANVAS_PADDING = 24
const MAXIMUM_NODES_PER_ROW = 3
const ROLE_ORDER = ['UPSTREAM_2', 'UPSTREAM_1', 'CENTER', 'DOWNSTREAM_1', 'DOWNSTREAM_2', 'RELATED'] as const

export const LINEAGE_ROLE_LABELS = {
  UPSTREAM_2: 'U·2',
  UPSTREAM_1: 'U·1',
  CENTER: 'CURRENT',
  DOWNSTREAM_1: 'D·1',
  DOWNSTREAM_2: 'D·2',
  RELATED: 'RELATED',
} as const

export type LineageNodeRole = keyof typeof LINEAGE_ROLE_LABELS

export interface PositionedLineageNode {
  asset: CatalogAsset
  role: LineageNodeRole
  x: number
  y: number
}

export interface LineageLayout {
  height: number
  width: number
  nodes: PositionedLineageNode[]
}

function distancesFrom(start: string, adjacency: Map<string, string[]>): Map<string, number> {
  const distances = new Map<string, number>([[start, 0]])
  const queue = [start]
  while (queue.length) {
    const current = queue.shift()
    if (!current) continue
    const distance = distances.get(current) ?? 0
    for (const adjacent of adjacency.get(current) ?? []) {
      if (distances.has(adjacent)) continue
      distances.set(adjacent, distance + 1)
      queue.push(adjacent)
    }
  }
  return distances
}

function roleFor(
  assetId: string,
  centerAssetId: string,
  upstreamDistances: Map<string, number>,
  downstreamDistances: Map<string, number>,
): LineageNodeRole {
  if (assetId === centerAssetId) return 'CENTER'
  const upstream = upstreamDistances.get(assetId)
  if (upstream === 1) return 'UPSTREAM_1'
  if (upstream && upstream >= 2) return 'UPSTREAM_2'
  const downstream = downstreamDistances.get(assetId)
  if (downstream === 1) return 'DOWNSTREAM_1'
  if (downstream && downstream >= 2) return 'DOWNSTREAM_2'
  return 'RELATED'
}

export function layoutLineage(lineage: CatalogLineage): LineageLayout {
  const upstream = new Map<string, string[]>()
  const downstream = new Map<string, string[]>()
  for (const edge of lineage.edges) {
    upstream.set(edge.target_asset_id, [...(upstream.get(edge.target_asset_id) ?? []), edge.source_asset_id])
    downstream.set(edge.source_asset_id, [...(downstream.get(edge.source_asset_id) ?? []), edge.target_asset_id])
  }
  const upstreamDistances = distancesFrom(lineage.center_asset_id, upstream)
  const downstreamDistances = distancesFrom(lineage.center_asset_id, downstream)
  const byRole = new Map<LineageNodeRole, CatalogAsset[]>(ROLE_ORDER.map((role) => [role, []]))
  for (const asset of lineage.nodes) {
    byRole.get(roleFor(asset.id, lineage.center_asset_id, upstreamDistances, downstreamDistances))?.push(asset)
  }
  for (const assets of byRole.values()) assets.sort((left, right) => left.name.localeCompare(right.name))

  const maximumColumns = Math.max(1, ...Array.from(byRole.values(), (assets) => Math.min(assets.length, MAXIMUM_NODES_PER_ROW)))
  const width = Math.max(720, LINEAGE_CANVAS_PADDING * 2 + maximumColumns * LINEAGE_NODE_WIDTH + Math.max(0, maximumColumns - 1) * HORIZONTAL_GAP)
  const nodes: PositionedLineageNode[] = []
  let rowY = LINEAGE_CANVAS_PADDING
  for (const role of ROLE_ORDER) {
    const assets = byRole.get(role) ?? []
    for (let index = 0; index < assets.length; index += MAXIMUM_NODES_PER_ROW) {
      const row = assets.slice(index, index + MAXIMUM_NODES_PER_ROW)
      const rowWidth = row.length * LINEAGE_NODE_WIDTH + Math.max(0, row.length - 1) * HORIZONTAL_GAP
      const startX = Math.max(LINEAGE_CANVAS_PADDING, Math.round((width - rowWidth) / 2))
      row.forEach((asset, columnIndex) => nodes.push({
        asset,
        role,
        x: startX + columnIndex * (LINEAGE_NODE_WIDTH + HORIZONTAL_GAP),
        y: rowY,
      }))
      rowY += LINEAGE_NODE_HEIGHT + VERTICAL_GAP
    }
  }
  const height = Math.max(460, rowY - VERTICAL_GAP + LINEAGE_CANVAS_PADDING)
  return { height, width, nodes }
}
