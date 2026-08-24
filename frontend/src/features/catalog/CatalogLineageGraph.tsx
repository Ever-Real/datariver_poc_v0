import { useMemo } from 'react'
import type { CatalogLineage } from '../../api/types'
import { CytoscapeReadGraph } from '../../components/graph/CytoscapeReadGraph'
import { catalogLineageToReadGraph } from '../../components/graph/CytoscapeGraphAdapter'

export function CatalogLineageGraph({
  lineage,
  onSelectAsset,
}: {
  lineage: CatalogLineage
  onSelectAsset: (assetId: string) => void
}) {
  const graph = useMemo(() => catalogLineageToReadGraph(lineage), [lineage])
  return (
    <CytoscapeReadGraph
      ariaLabel="권한 필터링된 DataHub Lineage 그래프"
      boundNotice={lineage.truncated ? '서버 조회 한도에 따라 일부 관계가 생략되었습니다.' : undefined}
      graph={graph}
      height={420}
      onActivateNode={onSelectAsset}
      onSelectNode={onSelectAsset}
      selectedElementId={lineage.center_asset_id}
    />
  )
}
