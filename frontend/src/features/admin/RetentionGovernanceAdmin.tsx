import { useMemo, useState } from 'react'
import { useRovingTabs } from '../../components/common/useRovingTabs'
import { ErasureAdmin } from './ErasureAdmin'
import type { AdminSectionProps } from './MembershipAdmin'
import { LegalHoldAdmin, RetentionPolicyAdmin } from './RetentionAdmin'

type RetentionView = 'policy' | 'holds' | 'erasure'

function initialView(): RetentionView {
  const parameters = new URL(window.location.href).searchParams
  const requested = parameters.get('adminView') ?? parameters.get('adminSection')
  if (requested === 'holds') return 'holds'
  if (requested === 'erasure') return 'erasure'
  return 'policy'
}

export function RetentionGovernanceAdmin(props: AdminSectionProps) {
  const operations = useMemo(() => new Set(props.context?.allowed_operations ?? []), [props.context])
  const views = [
    operations.has('RETENTION_POLICY_READ') && { id: 'policy' as const, label: '보존정책' },
    operations.has('LEGAL_HOLD_READ') && { id: 'holds' as const, label: 'Legal Hold' },
    operations.has('ERASURE_READ') && { id: 'erasure' as const, label: '파기 검토' },
  ].filter((item): item is { id: RetentionView; label: string } => Boolean(item))
  const [requested, setRequested] = useState<RetentionView>(initialView)
  const active = views.some((item) => item.id === requested) ? requested : views[0]?.id
  const select = (next: RetentionView) => {
    setRequested(next)
    const url = new URL(window.location.href)
    url.searchParams.set('page', 'admin')
    url.searchParams.set('adminSection', 'retention')
    url.searchParams.set('adminView', next)
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
  }
  const tabs = useRovingTabs({
    ids: views.map((item) => item.id),
    activeId: active,
    idPrefix: 'admin-retention',
    onSelect: select,
  })

  return <div className="grid gap-3">
    <section className="panel border-l-4 border-l-blue-700 bg-slate-50">
      <span className="eyebrow">Retention &amp; erasure governance</span>
      <h2 className="mb-1 mt-1 text-base text-navy-900">보존·파기 거버넌스</h2>
      <p className="m-0 text-xs leading-5 text-slate-600">이 화면은 문서 사본이 아니라 PostgreSQL이 정본인 승인 업무입니다. Legal Hold가 만료와 파기보다 우선하며, 파기 승인은 검토 증거일 뿐 실제 삭제를 실행하지 않습니다.</p>
    </section>
    <section className="grid gap-3 rounded-enterprise border border-slate-300 bg-white p-4 shadow-sm" aria-labelledby="retention-workflow-title">
      <div>
        <span className="eyebrow">Operating model</span>
        <h3 className="mb-1 mt-1 text-sm font-black text-navy-900" id="retention-workflow-title">보존·예외보존·파기 Workflow</h3>
        <p className="m-0 text-xs leading-5 text-slate-600">세 탭은 같은 기능이 아니라 하나의 수명주기에서 서로 다른 결정을 담당합니다. 여기서 PostgreSQL은 정책과 승인 증거의 정본이며, 대상 데이터 저장소를 PostgreSQL로 제한한다는 뜻이 아닙니다.</p>
      </div>
      <ol className="retention-workflow-map">
        <li><span>1</span><div><strong>보존정책</strong><small>Chat, 완료 작업, 감사 증거, 업로드 객체 같은 DataRiver 데이터 클래스별 기본 보존기간을 버전으로 제안·승인합니다.</small></div></li>
        <li><span>2</span><div><strong>만료 후보 판정</strong><small>기한 도달은 후보 상태일 뿐 삭제 권한이 아닙니다. 현재 자동 삭제와 파티션 제거는 항상 <code>DISABLED_NOT_READY</code>입니다.</small></div></li>
        <li><span>3</span><div><strong>Legal Hold 우선</strong><small>감사·분쟁·조사처럼 특별 보존 사유가 있으면 Workspace, 사용자 또는 Resource 범위에 Hold를 걸어 만료와 파기를 차단합니다.</small></div></li>
        <li><span>4</span><div><strong>파기 검토</strong><small>사용자 데이터, Chat 세션 또는 업로드 객체의 명시적 파기 요청을 Maker와 별도 Checker가 검토합니다. 승인도 아직 실제 삭제는 아닙니다.</small></div></li>
      </ol>
      <div className="grid gap-2 md:grid-cols-3" aria-label="보존·파기 운영 예시">
        <article className="rounded-enterprise border border-slate-200 bg-slate-50 p-3"><strong className="text-xs text-navy-900">일반 보존 예시</strong><p className="mb-0 mt-1 text-[10px] leading-4 text-slate-600">활성 정책의 Chat 보존기간으로 새 세션의 기한을 계산해 기록합니다. 기한이 지나도 현재 버전은 자동 삭제하지 않습니다.</p></article>
        <article className="rounded-enterprise border border-slate-200 bg-slate-50 p-3"><strong className="text-xs text-navy-900">특별 보존 예시</strong><p className="mb-0 mt-1 text-[10px] leading-4 text-slate-600">감사 조사와 관련된 사용자 또는 Resource에 Legal Hold를 배치하면 일반 만료보다 우선해 파기 검토를 차단합니다.</p></article>
        <article className="rounded-enterprise border border-slate-200 bg-slate-50 p-3"><strong className="text-xs text-navy-900">파기 검토 예시</strong><p className="mb-0 mt-1 text-[10px] leading-4 text-slate-600">업로드 객체 삭제 요청은 서버가 대상 버전·소유자·등급·활성 정책·Hold를 다시 읽고 독립 승인 증거만 남깁니다.</p></article>
      </div>
      <p className="callout m-0">외부 Oracle·PostgreSQL·Snowflake 등의 원본 테이블 수명주기 실행은 아직 계약에 없습니다. 원본 테이블명이나 SQL을 브라우저에서 받아 삭제하지 않으며, 향후 각 Connector의 정본 ID와 실행 증거를 갖춘 별도 Workflow가 필요합니다.</p>
    </section>
    <div className="flex flex-wrap gap-1 border-b border-slate-300 pb-2" role="tablist" aria-label="보존·파기 업무">
      {views.map((item) => <button key={item.id} {...tabs.tabProps(item.id)} type="button" className={`button ${active === item.id ? '' : 'button-secondary'}`} onClick={() => select(item.id)}>{item.label}</button>)}
    </div>
    {active === 'policy' && <div {...tabs.panelProps('policy')}><RetentionPolicyAdmin {...props} /></div>}
    {active === 'holds' && <div {...tabs.panelProps('holds')}><LegalHoldAdmin {...props} /></div>}
    {active === 'erasure' && <div {...tabs.panelProps('erasure')}><ErasureAdmin {...props} /></div>}
  </div>
}
