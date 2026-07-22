import { useCallback, useEffect, useState } from 'react'
import { Database, KeyRound, Save, ShieldCheck, UserRound } from 'lucide-react'
import type { ApiClient } from '../../api/client'
import type { AuthenticatedProfile, Capability, ExternalSystemLink, MembershipRenewalRequest, WorkspaceMembershipSummary } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { GovernedUnavailable } from '../../components/common/GovernedUnavailable'
import { PageTitle } from '../../components/layout/PageTitle'

function capabilityState(items: Capability[], name: string): string {
  return items.find((item) => item.name.toLowerCase().includes(name.toLowerCase()))?.state ?? '관측값 없음'
}

export function ProfilePage({
  profile,
  client,
  workspace,
  capabilities,
  externalSystemLinks,
  onPasswordChange,
  onPasswordReauth,
}: {
  profile: AuthenticatedProfile
  client: ApiClient
  workspace: string
  capabilities: Capability[]
  externalSystemLinks: ExternalSystemLink[]
  onPasswordChange: () => void
  onPasswordReauth: () => void
}) {
  const dataHubLink = externalSystemLinks.find((link) => link.system_id === 'datahub')
  const [membership, setMembership] = useState<WorkspaceMembershipSummary>()
  const [renewals, setRenewals] = useState<MembershipRenewalRequest[]>([])
  const [renewalReason, setRenewalReason] = useState('')
  const [renewalBusy, setRenewalBusy] = useState(false)
  const [renewalError, setRenewalError] = useState<unknown>()
  const loadRenewal = useCallback(async () => {
    setRenewalError(undefined)
    try {
      const [summary, history] = await Promise.all([
        client.request<WorkspaceMembershipSummary>('/admin/workspace-memberships/me/summary'),
        client.request<{ items: MembershipRenewalRequest[] }>('/admin/membership-renewals/me?limit=100'),
      ])
      setMembership(summary); setRenewals(history.items)
    } catch (error) { setRenewalError(error) }
  }, [client])
  useEffect(() => { void loadRenewal() }, [loadRenewal])
  const pendingRenewal = renewals.find((item) => item.state === 'PENDING')
  const renewalOpen = Boolean(
    membership?.renewal_request_eligible
    && !pendingRenewal,
  )
  const requestRenewal = async () => {
    if (!renewalOpen || !renewalReason.trim() || renewalBusy) return
    setRenewalBusy(true); setRenewalError(undefined)
    try {
      await client.request('/admin/membership-renewals/me', {
        method: 'POST',
        idempotencyKey: `profile-renewal-${crypto.randomUUID()}`,
        body: JSON.stringify({ reason: renewalReason.trim() }),
      })
      setRenewalReason(''); await loadRenewal()
    } catch (error) { setRenewalError(error) } finally { setRenewalBusy(false) }
  }
  return <section className="grid gap-4">
    <PageTitle icon="ME" eyebrow="Verified identity profile" title="내 프로필" description="인증 시스템이 검증한 사용자 정보와 현재 Workspace 범위만 표시합니다." />
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
      <section className="rounded-enterprise border border-slate-300 bg-white p-5 shadow-sm">
        <header className="mb-5 flex items-center gap-3 border-b border-slate-200 pb-4"><span className="grid h-11 w-11 place-items-center rounded-full bg-navy-900 text-white"><UserRound size={21} /></span><div><span className="text-[10px] font-black tracking-[.14em] text-enterprise-blue uppercase">Basic information</span><h2 className="my-1 text-lg font-black text-navy-900">{profile.display_name}</h2><p className="m-0 text-xs text-slate-500">{profile.subject}</p></div></header>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="grid gap-1 text-xs font-bold">이름<input readOnly value={profile.display_name} /></label>
          <label className="grid gap-1 text-xs font-bold">닉네임<input readOnly value="인증 프로필 미제공" /></label>
          <label className="grid gap-1 text-xs font-bold">Email<input readOnly value={profile.email ?? '인증 프로필 미제공'} /></label>
          <label className="grid gap-1 text-xs font-bold">Department<input readOnly value="인증 프로필 미제공" /></label>
          <label className="grid gap-1 text-xs font-bold">현재 Workspace<input readOnly value={workspace || '선택되지 않음'} /></label>
          <label className="grid gap-1 text-xs font-bold">Workspace 운영 모드<input readOnly value={profile.workspace_selection_enabled === false ? '단일 Workspace · 전환 비활성' : 'Workspace 전환 허용'} /></label>
          <label className="grid gap-1 text-xs font-bold">인증 보증<input readOnly value={profile.authentication_assurance} /></label>
          <label className="grid gap-1 text-xs font-bold">WebAuthn<input readOnly value={profile.hardware_webauthn_enabled === false ? '비활성 · 고위험 작업 차단' : '활성'} /></label>
          <label className="grid gap-1 text-xs font-bold md:col-span-2">역할<input readOnly value={profile.roles.join(', ') || '역할 없음'} /></label>
        </div>
        <div className="mt-5 flex flex-wrap gap-2">
          {profile.password_change_supported && <button type="button" className="button" onClick={onPasswordChange}><KeyRound size={14} /> 비밀번호 변경</button>}
          <button type="button" className="button button-secondary" onClick={onPasswordReauth}><KeyRound size={14} /> 비밀번호 재인증</button>
          <button type="button" className="button" disabled title="사용자 프로필 수정은 조직 인증 시스템이 관리합니다."><Save size={14} /> 변경사항 저장</button>
        </div>
        <div className="mt-4"><GovernedUnavailable compact title="자격 증명은 인증 시스템 관리 영역입니다" description={profile.password_change_supported ? 'DataRiver에서 변경 절차를 시작하면 인증 화면에서만 새 비밀번호를 입력한 뒤 이 화면으로 돌아옵니다. DataRiver는 비밀번호를 저장하거나 로그에 남기지 않습니다.' : '이 배포의 인증 시스템은 DataRiver 내 비밀번호 변경 절차를 제공하지 않습니다. 이름·이메일·비밀번호는 조직의 승인된 계정 관리 절차를 따릅니다.'} /></div>
        <section className="mt-4 grid gap-2 rounded-enterprise border border-slate-300 bg-slate-50 p-4" aria-labelledby="membership-renewal-title">
          <div><span className="text-[10px] font-black tracking-[.14em] text-enterprise-blue uppercase">Workspace access renewal</span><h3 className="mb-1 mt-1 text-sm font-black text-navy-900" id="membership-renewal-title">6개월 계정 갱신</h3></div>
          {!membership ? <p className="m-0 text-xs text-slate-500">현재 멤버십 만료 정보를 확인하는 중입니다.</p> : <dl className="summary-list"><div><dt>가입일</dt><dd>{membership.joined_at ? new Date(membership.joined_at).toLocaleDateString() : '—'}</dd></div><div><dt>현재 만료일</dt><dd>{membership.access_expires_at ? new Date(membership.access_expires_at).toLocaleDateString() : '운영자 관리 계정'}</dd></div><div><dt>신청 가능일</dt><dd>{membership.renewal_eligible_at ? new Date(membership.renewal_eligible_at).toLocaleDateString() : '해당 없음'}</dd></div></dl>}
          {pendingRenewal ? <p className="callout m-0">{new Date(pendingRenewal.requested_expires_at).toLocaleDateString()}까지의 갱신 승인을 기다리고 있습니다. 모든 전역 Admin의 승인함에 표시됩니다.</p> : membership?.access_expires_at ? <><label className="grid gap-1 text-xs font-bold">갱신 신청 사유<textarea className="min-h-20" maxLength={4000} disabled={!renewalOpen || renewalBusy} value={renewalReason} onChange={(event) => setRenewalReason(event.target.value)} /></label><div className="flex justify-end"><button type="button" className="button" disabled={!renewalOpen || !renewalReason.trim() || renewalBusy} onClick={() => void requestRenewal()}>{renewalBusy ? '신청 중…' : '6개월 갱신 신청'}</button></div>{!renewalOpen && <p className="m-0 text-[10px] text-slate-500">갱신 신청은 만료 30일 전부터 가능하며, 만료 후에는 Workspace 접근이 중지됩니다.</p>}</> : null}
          <ErrorNotice error={renewalError} />
        </section>
      </section>
      <aside className="grid content-start gap-3">
        <article className="rounded-enterprise border border-slate-300 bg-white p-4 shadow-sm"><div className="flex items-center gap-2 text-xs font-black text-navy-900"><Database size={16} className="text-enterprise-blue" /> Assigned System</div><strong className="mt-3 block text-2xl text-navy-900">—</strong><p className="mb-0 text-[10px] leading-5 text-slate-500">현재 사용자 전용 시스템 할당 조회 API가 없습니다.</p></article>
        <article className="rounded-enterprise border border-slate-300 bg-white p-4 shadow-sm"><div className="flex items-center gap-2 text-xs font-black text-navy-900"><Database size={16} className="text-enterprise-blue" /> Owned Datasets</div><strong className="mt-3 block text-2xl text-navy-900">—</strong><p className="mb-0 text-[10px] leading-5 text-slate-500">현재 사용자 전용 소유 데이터셋 조회 API가 없습니다.</p></article>
        <article className="rounded-enterprise border border-slate-300 bg-white p-4 shadow-sm"><div className="flex items-center gap-2 text-xs font-black text-navy-900"><ShieldCheck size={16} className="text-enterprise-blue" /> DataHub Integration</div><span className="badge mt-3">{capabilityState(capabilities, 'datahub')}</span>{dataHubLink ? <a className="mt-3 block text-xs font-bold text-enterprise-blue" href={dataHubLink.url} target="_blank" rel="noreferrer">서버 승인 DataHub 링크 열기</a> : <p className="mb-0 mt-3 text-[10px] leading-5 text-slate-500">서버가 승인한 DataHub 외부 링크가 없습니다.</p>}</article>
      </aside>
    </div>
  </section>
}
