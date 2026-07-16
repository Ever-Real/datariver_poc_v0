import { UnavailableCapability } from '../../components/UnavailableCapability'
import { PageTitle } from '../../components/layout/PageTitle'

export function MonitoringPage() {
  return <section>
    <PageTitle icon="MO" eyebrow="Operations" title="모니터링" description="DataRiver 상태와 승인된 관측성 대시보드를 한 화면에서 확인합니다." />
    <UnavailableCapability title="승인된 Grafana embed 미구성" reason="서버 소유 allowlist descriptor, 인증 경계와 CSP 검증이 완료될 때까지 임의 URL iframe을 생성하지 않습니다." />
  </section>
}
