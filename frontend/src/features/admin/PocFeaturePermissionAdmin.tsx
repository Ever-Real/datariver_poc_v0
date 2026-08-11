import { useMemo } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { DenseDataTable } from '../../components/common/DenseDataTable'

interface PocFeaturePermission {
  id: string
  area: string
  feature: string
  operations: string
  currentAccess: 'OPEN'
  futureControl: string
}

const permissions: PocFeaturePermission[] = [
  { id: 'catalog', area: '검색', feature: '검색·상세·계보·Resource Tree', operations: 'read / search / lineage', currentAccess: 'OPEN', futureControl: '자산·분류·System 범위' },
  { id: 'registration', area: '등록관리', feature: '수동 등록·메타데이터 변경 요청', operations: 'create / edit / submit', currentAccess: 'OPEN', futureControl: '등록자·Data Steward' },
  { id: 'change', area: '변경관리', feature: 'CR 등록·검토·반려·재상신·테스트·결재', operations: 'create / review / test / approve', currentAccess: 'OPEN', futureControl: 'Maker/Checker·System 책임' },
  { id: 'quality', area: '품질관리', feature: '현황·이력·규칙·실행', operations: 'read / author / run', currentAccess: 'OPEN', futureControl: '자산·품질 운영 역할' },
  { id: 'knowledge', area: '지식관리', feature: 'Registry·Studio·정보관리·Release', operations: 'read / create / edit / publish', currentAccess: 'OPEN', futureControl: 'Domain·분류·Reviewer' },
  { id: 'governance', area: '거버넌스', feature: '문서·Template·검토·발행·Archive', operations: 'read / create / review / publish', currentAccess: 'OPEN', futureControl: 'Maker/Checker·분류 범위' },
  { id: 'chat', area: 'Chat', feature: '자동·일반·벡터·그래프 라우팅', operations: 'query / retrieve / cite', currentAccess: 'OPEN', futureControl: '근거 자산·Graph scope' },
  { id: 'monitoring', area: '모니터링', feature: 'Dashboard 링크·iframe', operations: 'read / configure', currentAccess: 'OPEN', futureControl: '운영자 승인' },
  { id: 'users', area: 'POC USER', feature: '사용자·업무 역할 관리', operations: 'read / create / update', currentAccess: 'OPEN', futureControl: 'Identity Admin' },
  { id: 'systems', area: 'POC USER', feature: 'System 추가·담당자·Schema scope', operations: 'read / create / assign', currentAccess: 'OPEN', futureControl: 'System Admin' },
  { id: 'dictionary', area: 'POC USER', feature: 'DataHub 용어사전 조회', operations: 'read / search', currentAccess: 'OPEN', futureControl: 'Glossary Steward' },
]

export function PocFeaturePermissionAdmin() {
  const columns = useMemo<ColumnDef<PocFeaturePermission>[]>(() => [
    { accessorKey: 'area', header: '메뉴', size: 120 },
    { accessorKey: 'feature', header: '기능', size: 280 },
    { accessorKey: 'operations', header: 'Operation', size: 230 },
    { accessorKey: 'currentAccess', header: '현재 POC', size: 110, cell: () => <span className="badge">OPEN</span> },
    { accessorKey: 'futureControl', header: '향후 권한 기준', size: 230 },
  ], [])

  return <section className="panel" aria-label="POC 기능별 권한 현황">
    <div className="section-heading">
      <div>
        <span className="eyebrow">POC open-access inventory</span>
        <h3>기능별 권한 현황</h3>
        <p className="muted">현재 POC에서는 아래 기능을 모두 열어 둡니다. 이 표는 향후 Admin 전환 시 기능별 권한 설정의 기준 목록입니다.</p>
      </div>
    </div>
    <DenseDataTable
      caption="POC 기능별 권한 현황"
      columns={columns}
      data={permissions}
      getRowId={(item) => item.id}
    />
  </section>
}
