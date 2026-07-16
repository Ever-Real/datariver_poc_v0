import { UnavailableCapability } from '../../components/UnavailableCapability'
import { PageTitle } from '../../components/layout/PageTitle'

export function PolicyGovernancePage() {
  return <section>
    <PageTitle icon="GV" eyebrow="Policy governance" title="거버넌스" description="정책 문서, 버전, 목차, 관리부서와 승인 이력을 관리합니다." />
    <UnavailableCapability title="버전 정책문서 계약 준비 중" reason="현재 v1 API에는 immutable document version과 draft-review-approve-publish 계약이 없습니다. 하드코딩 문서나 저장되지 않는 편집 화면을 제공하지 않습니다." />
  </section>
}
