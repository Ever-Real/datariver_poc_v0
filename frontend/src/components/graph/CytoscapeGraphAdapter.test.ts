import { describe, expect, it } from 'vitest'
import type { CatalogLineage, KnowledgeSnapshot } from '../../api/types'
import {
  catalogLineageToReadGraph,
  canonicalNodeGroup,
  cytoscapeLayout,
  lineageRoleGaps,
  knowledgeSnapshotToReadGraph,
  mergeReadGraphs,
  nodeGroupColor,
  toCytoscapeElements,
} from './CytoscapeGraphAdapter'

const lineage: CatalogLineage = {
  center_asset_id: 'table:current',
  direction: 'BOTH',
  depth: 2,
  truncated: false,
  meta: { projection_version: 9, policy_version: 'policy-9' },
  nodes: [
    { id: 'table:upstream', external_urn: 'urn:li:dataset:upstream', asset_type: 'TABLE', name: 'upstream', classification: 'INTERNAL', lifecycle: 'ACTIVE', observed_at: '2026-08-24T00:00:00Z', matches: [] },
    { id: 'table:current', external_urn: 'urn:li:dataset:current', asset_type: 'TABLE', name: 'current', classification: 'INTERNAL', lifecycle: 'ACTIVE', observed_at: '2026-08-24T00:00:00Z', matches: [] },
    { id: 'table:downstream', external_urn: 'urn:li:dataset:downstream', asset_type: 'TABLE', name: 'downstream', classification: 'INTERNAL', lifecycle: 'ACTIVE', observed_at: '2026-08-24T00:00:00Z', matches: [] },
  ],
  edges: [
    { source_asset_id: 'table:upstream', target_asset_id: 'table:current' },
    { source_asset_id: 'table:current', target_asset_id: 'table:downstream' },
  ],
}

const snapshot: KnowledgeSnapshot = {
  release: {
    id: 'release-1',
    graph_id: 'graph-1',
    release_no: 1,
    ontology_version_id: 'ontology-1',
    content_hash: 'hash',
    node_count: 2,
    edge_count: 1,
    published_by: 'subject',
    published_at: '2026-08-24T00:00:00Z',
  },
  nodes: [
    { id: 'node-a', entity_type: 'TABLE', properties: { name: 'A' }, classification: 1, provenance: [] },
    { id: 'node-b', entity_type: 'GLOSSARY_TERM', properties: { display_name: 'Business B' }, classification: 1, provenance: [] },
  ],
  edges: [
    { id: 'edge-a-b', source_id: 'node-a', target_id: 'node-b', edge_type: 'HAS_TERM', properties: {}, classification: 1, provenance: [] },
  ],
  filtered: true,
}

describe('Cytoscape graph adapter', () => {
  it('maps Catalog lineage with canonical stable identities and directional roles', () => {
    const first = catalogLineageToReadGraph(lineage)
    const second = catalogLineageToReadGraph(structuredClone(lineage))

    expect(first.nodes.map(({ id, role, lineageDepth }) => [id, role, lineageDepth])).toEqual([
      ['table:upstream', 'UPSTREAM', 1],
      ['table:current', 'ROOT', 0],
      ['table:downstream', 'DOWNSTREAM', 1],
    ])
    expect(first.edges.map((edge) => edge.id)).toEqual(second.edges.map((edge) => edge.id))
    expect(first.edges[0]?.id).toContain('table%3Aupstream')
    expect(toCytoscapeElements(first).map((element) => element.data.id)).toContain('table:current')
  })

  it('preserves canonical managed node, edge, provenance and root identities', () => {
    const graph = knowledgeSnapshotToReadGraph(snapshot, 'METADATA_MASTER', 'node-b')
    const elements = toCytoscapeElements(graph)

    expect(graph.nodes[1]).toMatchObject({ id: 'node-b', label: 'Business B', role: 'ROOT' })
    expect(graph.edges[0]).toMatchObject({ id: 'edge-a-b', source: 'node-a', target: 'node-b' })
    expect(elements.find((element) => element.data.id === 'edge-a-b')?.data).toMatchObject({ source: 'node-a', target: 'node-b' })
    expect(elements.find((element) => element.data.id === 'node-b')?.data).toMatchObject({
      shape: 'ellipse',
      nodeGroup: 'GLOSSARY_TERM',
      groupColor: nodeGroupColor('GLOSSARY_TERM'),
      canvasLabel: 'Business B',
      lineageDepth: 0,
    })
  })

  it('derives stable visual groups only from platform-generic entity types', () => {
    expect(canonicalNodeGroup('DATASET')).toBe('DATASET')
    expect(canonicalNodeGroup('TABLE')).toBe('DATASET')
    expect(canonicalNodeGroup('SCHEMA_FIELD')).toBe('COLUMN')
    expect(canonicalNodeGroup('GLOSSARY_TERM')).toBe('GLOSSARY_TERM')
    expect(canonicalNodeGroup('UNIT_OF_MEASURE')).toBe('UNIT')
    expect(canonicalNodeGroup('organization_specific_entity')).toBe('ENTITY')
  })

  it('projects managed lineage visually from upstream left to downstream right without changing edge identity', () => {
    const graph = knowledgeSnapshotToReadGraph(snapshot, 'LINEAGE', 'node-a')
    expect(graph.nodes.map(({ id, role }) => [id, role])).toEqual([
      ['node-a', 'ROOT'],
      ['node-b', 'UPSTREAM'],
    ])
    expect(graph.edges[0]).toMatchObject({ id: 'edge-a-b', source: 'node-b', target: 'node-a' })
  })

  it('rejects duplicate identities and missing canonical endpoints before rendering', () => {
    const graph = knowledgeSnapshotToReadGraph(snapshot, 'SEMANTIC')
    expect(() => toCytoscapeElements({ ...graph, nodes: [...graph.nodes, graph.nodes[0]!] })).toThrow(/Duplicate/)
    expect(() => toCytoscapeElements({ ...graph, nodes: graph.nodes.slice(0, 1) })).toThrow(/missing canonical endpoint/)
  })

  it('uses graph-type layout configuration and merges expansions by canonical identity', () => {
    expect(cytoscapeLayout('LINEAGE')).toMatchObject({ name: 'cola', fit: false, randomize: false })
    expect(cytoscapeLayout('METADATA_MASTER')).toMatchObject({ name: 'cola', animate: true, fit: false, randomize: false })

    const base = knowledgeSnapshotToReadGraph(snapshot, 'METADATA_MASTER', 'node-a')
    const merged = mergeReadGraphs(base, [{
      ...base,
      nodes: [{ ...base.nodes[1]!, label: 'Updated B' }],
      edges: base.edges,
    }])
    expect(merged.nodes).toHaveLength(2)
    expect(merged.edges).toHaveLength(1)
    expect(merged.nodes.find((node) => node.id === 'node-b')?.label).toBe('Business B')
  })

  it('turns canonical lineage roles into upstream-root-downstream Cola constraints', () => {
    const graph = catalogLineageToReadGraph(lineage)

    expect(lineageRoleGaps(graph)).toEqual([
      { axis: 'x', leftId: 'table:upstream', rightId: 'table:current', gap: 190, equality: true },
      { axis: 'x', leftId: 'table:current', rightId: 'table:downstream', gap: 190, equality: true },
    ])
    expect(lineageRoleGaps({ ...graph, kind: 'METADATA_MASTER' })).toEqual([])
  })
})
