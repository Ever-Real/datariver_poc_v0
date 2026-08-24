import { useEffect, useMemo, useRef, useState } from 'react'
import type { ApiClient } from '../../api/client'
import type { CatalogLineage } from '../../api/types'
import { CytoscapeReadGraph } from '../../components/graph/CytoscapeReadGraph'
import { catalogLineageToReadGraph, mergeReadGraphs } from '../../components/graph/CytoscapeGraphAdapter'

export function CatalogLineageGraph({
  client,
  lineage,
  onSelectAsset,
}: {
  client: ApiClient
  lineage: CatalogLineage
  onSelectAsset: (assetId: string) => void
}) {
  const [expansions, setExpansions] = useState<Record<string, CatalogLineage>>({})
  const controllers = useRef(new Set<AbortController>())
  useEffect(() => {
    const active = controllers.current
    setExpansions({})
    return () => {
      active.forEach((controller) => controller.abort())
      active.clear()
    }
  }, [lineage.center_asset_id])
  const graph = useMemo(() => mergeReadGraphs(
    catalogLineageToReadGraph(lineage),
    Object.values(expansions).map(catalogLineageToReadGraph),
  ), [expansions, lineage])
  const expand = async (nodeId: string, request: { direction: 'UPSTREAM' | 'DOWNSTREAM'; depth: 2 }) => {
    const key = `${request.direction}:${nodeId}`
    if (expansions[key]) return
    const controller = new AbortController()
    controllers.current.add(controller)
    try {
      const snapshot = await client.request<CatalogLineage>(
        `/catalog/assets/${nodeId}/lineage?direction=${request.direction}&depth=${request.depth}`,
        { cache: 'no-store', signal: controller.signal },
      )
      if (!controller.signal.aborted) setExpansions((current) => ({ ...current, [key]: snapshot }))
    } finally {
      controllers.current.delete(controller)
    }
  }
  const collapse = (nodeId: string) => setExpansions((current) => Object.fromEntries(
    Object.entries(current).filter(([key]) => !key.endsWith(`:${nodeId}`)),
  ))
  return (
    <CytoscapeReadGraph
      ariaLabel="권한 필터링된 DataHub Lineage 그래프"
      boundNotice={lineage.truncated ? '서버 조회 한도에 따라 일부 관계가 생략되었습니다.' : undefined}
      graph={graph}
      height={420}
      onActivateNode={onSelectAsset}
      onCollapseNode={collapse}
      onExpandNode={expand}
      selectedElementId={lineage.center_asset_id}
      visualProfile="SEARCH_LINEAGE_CLASSIC"
    />
  )
}
