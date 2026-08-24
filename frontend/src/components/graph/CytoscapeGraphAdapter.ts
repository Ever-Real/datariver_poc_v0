import type { ElementDefinition, LayoutOptions } from 'cytoscape'
import type {
  CatalogAsset,
  CatalogLineage,
  KnowledgeGraphEdge,
  KnowledgeGraphNode,
  KnowledgeSnapshot,
} from '../../api/types'

export type ReadGraphKind = 'LINEAGE' | 'METADATA_MASTER' | 'SEMANTIC'
export type ReadGraphRole = 'ROOT' | 'UPSTREAM' | 'DOWNSTREAM' | 'NEUTRAL'

export interface ReadGraphNode {
  id: string
  label: string
  subtitle?: string
  entityType: string
  role?: ReadGraphRole
  properties: Record<string, unknown>
  provenance: unknown[]
}

export interface ReadGraphEdge {
  id: string
  source: string
  target: string
  label: string
  relationType: string
  properties: Record<string, unknown>
  provenance: unknown[]
}

export interface ReadGraphModel {
  kind: ReadGraphKind
  rootId?: string
  nodes: ReadGraphNode[]
  edges: ReadGraphEdge[]
}

function displayValue(properties: Record<string, unknown>, fallback: string): string {
  const value = properties.display_name ?? properties.business_name ?? properties.name
  return typeof value === 'string' || typeof value === 'number' ? String(value) : fallback
}

function lineageDistances(start: string, edges: CatalogLineage['edges'], direction: 'UPSTREAM' | 'DOWNSTREAM') {
  const adjacency = new Map<string, string[]>()
  for (const edge of edges) {
    const source = direction === 'UPSTREAM' ? edge.target_asset_id : edge.source_asset_id
    const target = direction === 'UPSTREAM' ? edge.source_asset_id : edge.target_asset_id
    adjacency.set(source, [...(adjacency.get(source) ?? []), target])
  }
  const distances = new Map<string, number>([[start, 0]])
  const queue = [start]
  while (queue.length > 0) {
    const current = queue.shift()
    if (!current) continue
    const nextDistance = (distances.get(current) ?? 0) + 1
    for (const target of adjacency.get(current) ?? []) {
      if (distances.has(target)) continue
      distances.set(target, nextDistance)
      queue.push(target)
    }
  }
  return distances
}

function catalogNodeProperties(asset: CatalogAsset): Record<string, unknown> {
  return {
    external_urn: asset.external_urn,
    platform: asset.platform ?? null,
    database_name: asset.database_name ?? null,
    schema_name: asset.schema_name ?? null,
    classification: asset.classification,
    lifecycle: asset.lifecycle,
    description: asset.description ?? null,
  }
}

export function catalogLineageToReadGraph(lineage: CatalogLineage): ReadGraphModel {
  const upstream = lineageDistances(lineage.center_asset_id, lineage.edges, 'UPSTREAM')
  const downstream = lineageDistances(lineage.center_asset_id, lineage.edges, 'DOWNSTREAM')
  return {
    kind: 'LINEAGE',
    rootId: lineage.center_asset_id,
    nodes: lineage.nodes.map((asset) => ({
      id: asset.id,
      label: asset.name,
      subtitle: [asset.platform, asset.database_name, asset.schema_name].filter(Boolean).join(' · ')
        || asset.asset_type,
      entityType: asset.asset_type,
      role: asset.id === lineage.center_asset_id
        ? 'ROOT'
        : upstream.has(asset.id)
          ? 'UPSTREAM'
          : downstream.has(asset.id)
            ? 'DOWNSTREAM'
            : 'NEUTRAL',
      properties: catalogNodeProperties(asset),
      provenance: [{
        source_ref: asset.external_urn,
        source_locator: asset.external_urn,
        source_version: lineage.meta.projection_version,
        method: 'DATAHUB_LINEAGE',
      }],
    })),
    edges: lineage.edges.map((edge) => ({
      id: `LINEAGE:${encodeURIComponent(edge.source_asset_id)}:${encodeURIComponent(edge.target_asset_id)}`,
      source: edge.source_asset_id,
      target: edge.target_asset_id,
      label: 'LINEAGE',
      relationType: 'LINEAGE',
      properties: {},
      provenance: [{
        source_ref: `${edge.source_asset_id}->${edge.target_asset_id}`,
        source_version: lineage.meta.projection_version,
        method: 'DATAHUB_LINEAGE',
      }],
    })),
  }
}

export function knowledgeSnapshotToReadGraph(
  snapshot: Pick<KnowledgeSnapshot, 'nodes' | 'edges'>,
  kind: ReadGraphKind,
  rootId?: string,
): ReadGraphModel {
  return {
    kind,
    rootId,
    nodes: snapshot.nodes.map((node: KnowledgeGraphNode) => ({
      id: node.id,
      label: displayValue(node.properties, node.id),
      subtitle: `${node.entity_type} · 근거 ${node.provenance.length}`,
      entityType: node.entity_type,
      role: node.id === rootId ? 'ROOT' : 'NEUTRAL',
      properties: node.properties,
      provenance: node.provenance,
    })),
    edges: snapshot.edges.map((edge: KnowledgeGraphEdge) => ({
      id: edge.id,
      source: edge.source_id,
      target: edge.target_id,
      label: edge.edge_type,
      relationType: edge.edge_type,
      properties: edge.properties,
      provenance: edge.provenance,
    })),
  }
}

export function mergeReadGraphs(base: ReadGraphModel, additions: ReadGraphModel[]): ReadGraphModel {
  const nodes = new Map(base.nodes.map((node) => [node.id, node]))
  const edges = new Map(base.edges.map((edge) => [edge.id, edge]))
  for (const addition of additions) {
    for (const node of addition.nodes) nodes.set(node.id, node)
    for (const edge of addition.edges) edges.set(edge.id, edge)
  }
  return { ...base, nodes: [...nodes.values()], edges: [...edges.values()] }
}

function nodeShape(entityType: string): string {
  const normalized = entityType.toLocaleUpperCase()
  if (normalized.includes('COLUMN') || normalized.includes('PROPERTY')) return 'round-rectangle'
  if (normalized.includes('TERM') || normalized.includes('TAG') || normalized.includes('CONCEPT')) return 'diamond'
  if (normalized.includes('DOMAIN') || normalized.includes('CONTAINER')) return 'hexagon'
  return 'rectangle'
}

export function toCytoscapeElements(graph: ReadGraphModel): ElementDefinition[] {
  const nodeIds = new Set<string>()
  const edgeIds = new Set<string>()
  const elements: ElementDefinition[] = []
  for (const node of graph.nodes) {
    if (!node.id || nodeIds.has(node.id)) throw new Error(`Duplicate or empty graph node identity: ${node.id || '(empty)'}`)
    nodeIds.add(node.id)
    elements.push({
      group: 'nodes',
      data: {
        id: node.id,
        label: node.label,
        canvasLabel: `${node.label}\n${node.entityType}`,
        subtitle: node.subtitle ?? '',
        entityType: node.entityType,
        role: node.role ?? 'NEUTRAL',
        shape: nodeShape(node.entityType),
      },
    })
  }
  for (const edge of graph.edges) {
    if (!edge.id || edgeIds.has(edge.id)) throw new Error(`Duplicate or empty graph edge identity: ${edge.id || '(empty)'}`)
    if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) {
      throw new Error(`Graph edge ${edge.id} references a missing canonical endpoint.`)
    }
    edgeIds.add(edge.id)
    elements.push({
      group: 'edges',
      data: {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        label: edge.label,
        relationType: edge.relationType,
      },
    })
  }
  return elements
}

export function cytoscapeLayout(kind: ReadGraphKind): LayoutOptions {
  if (kind === 'LINEAGE') {
    return {
      name: 'breadthfirst',
      directed: true,
      direction: 'rightward',
      circle: false,
      spacingFactor: 1.35,
      padding: 36,
      animate: false,
    }
  }
  return {
    name: 'cose',
    animate: false,
    fit: true,
    padding: 36,
    nodeRepulsion: 7600,
    idealEdgeLength: 120,
    edgeElasticity: 120,
    gravity: 0.28,
    numIter: 700,
    randomize: true,
  }
}
