import { UnavailableCapability } from '../../components/UnavailableCapability'
import { PageTitle } from '../../components/layout/PageTitle'

export function QualityPage() {
  return <section>
    <PageTitle icon="DQ" eyebrow="Data quality" title="품질관리" description="검증 규칙, 실행 결과와 품질 이슈를 권한 범위 안에서 관리합니다." />
    <UnavailableCapability title="품질 read model 준비 중" reason="현재 v1 API에는 품질 규칙·실행·이슈 계약이 없습니다. 실제 계약과 권한 검증 전에는 레거시 고정값을 표시하지 않습니다." />
  </section>
}
