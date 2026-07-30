import { useCallback, useEffect, useState } from 'react'
import { BookOpen, CheckCircle2, Eye, FileText, RefreshCw, Shield, Workflow } from 'lucide-react'
import type { ApiClient } from '../../api/client'
import type { AdminOperation, ClassificationAccessPolicy, LegalHold, RetentionPolicy } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { PageTitle } from '../../components/layout/PageTitle'

type DocumentId = 'CLASSIFICATION' | 'RETENTION' | 'LEGAL_HOLD'
type ViewMode = 'TEXT' | 'FLOW'

const documents: Array<{ id: DocumentId; title: string; description: string; icon: typeof Shield }> = [
  { id: 'CLASSIFICATION', title: '데이터 분류·접근 정책', description: '검색·Chat 허용 경계', icon: Shield },
  { id: 'RETENTION', title: '보존·파기 정책', description: '보존 기간과 승인 상태', icon: FileText },
  { id: 'LEGAL_HOLD', title: 'Legal Hold 관리', description: '파기 보류와 release 요청', icon: Workflow },
]
const defaultDocument = documents[0]!

interface PolicyData {
  classification: ClassificationAccessPolicy | null
  retention: RetentionPolicy | null
  holds: LegalHold[]
  readAllowed: boolean
}

export function PolicyGovernancePage({ client, mayReadPolicies = false, allowedOperations }: { client: ApiClient; mayReadPolicies?: boolean; allowedOperations?: readonly AdminOperation[] }) {
  const [active, setActive] = useState<DocumentId>('CLASSIFICATION')
  const [viewMode, setViewMode] = useState<ViewMode>('TEXT')
  const [data, setData] = useState<PolicyData>({ classification: null, retention: null, holds: [], readAllowed: false })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>()

  const refresh = useCallback(async () => {
    setLoading(true); setError(undefined)
    if (!mayReadPolicies) {
      setData({ classification: null, retention: null, holds: [], readAllowed: false })
      setLoading(false)
      return
    }
    const allowed = new Set(allowedOperations)
    const canReadClassification = allowedOperations === undefined || allowed.has('CLASSIFICATION_POLICY_READ')
    const canReadRetention = allowedOperations === undefined || allowed.has('RETENTION_POLICY_READ')
    const canReadHolds = allowedOperations === undefined || allowed.has('LEGAL_HOLD_READ')
    const [classification, retention, holds] = await Promise.allSettled([
      canReadClassification ? client.request<ClassificationAccessPolicy | null>('/admin/classification-access/policies/current') : Promise.resolve(null),
      canReadRetention ? client.request<RetentionPolicy | null>('/admin/retention/policies/current') : Promise.resolve(null),
      canReadHolds ? client.request<{ items: LegalHold[] }>('/admin/retention/legal-holds?limit=20') : Promise.resolve({ items: [] }),
    ])
    const failure = [classification, retention, holds].find((result) => result.status === 'rejected')
    if (failure?.status === 'rejected') setError(failure.reason)
    setData({
      classification: classification.status === 'fulfilled' ? classification.value : null,
      retention: retention.status === 'fulfilled' ? retention.value : null,
      holds: holds.status === 'fulfilled' ? holds.value.items : [],
      readAllowed: true,
    })
    setLoading(false)
  }, [allowedOperations, client, mayReadPolicies])

  useEffect(() => { void refresh() }, [refresh])
  const document = documents.find((item) => item.id === active) ?? defaultDocument

  return <section className="policy-governance-page">
    <PageTitle icon="GV" eyebrow="Policy governance" title="거버넌스" description="v0.3의 문서 목차·본문·워크플로우 구조로 실제 정책·보존·Legal Hold read model을 확인합니다." actions={<button type="button" className="button button-secondary" disabled={loading} onClick={() => void refresh()}><RefreshCw size={13} />새로고침</button>} />
    <ErrorNotice error={error} />
    <div className="policy-governance-workspace" aria-busy={loading}>
      <aside className="policy-document-tree panel" aria-label="거버넌스 문서 목차">
        <header><BookOpen size={16} /><div><span className="eyebrow">Governance library</span><h2>가이드라인 목록</h2></div></header>
        <nav>{documents.map(({ id, title, description, icon: Icon }) => <button key={id} type="button" className={active === id ? 'active' : ''} onClick={() => setActive(id)}><span><Icon size={15} /></span><div><strong>{title}</strong><small>{description}</small></div></button>)}</nav>
        <footer><Shield size={13} /><span>정책 수치와 상태는 서버 응답에서만 표시됩니다.</span></footer>
      </aside>
      <main className="policy-document-main panel">
        <header className="policy-document-toolbar"><div role="tablist" aria-label="문서 보기 방식"><button type="button" role="tab" aria-selected={viewMode === 'TEXT'} className={viewMode === 'TEXT' ? 'active' : ''} onClick={() => setViewMode('TEXT')}><FileText size={13} />문서 뷰어</button><button type="button" role="tab" aria-selected={viewMode === 'FLOW'} className={viewMode === 'FLOW' ? 'active' : ''} onClick={() => setViewMode('FLOW')}><Workflow size={13} />워크플로우 맵</button></div><span>{loading ? '동기화 중' : '서버 read model'}</span></header>
        {viewMode === 'TEXT' ? <PolicyDocumentView document={document} data={data} loading={loading} /> : <PolicyWorkflowView document={document} data={data} loading={loading} />}
      </main>
    </div>
  </section>
}

function PolicyDocumentView({ document, data, loading }: { document: { id: DocumentId; title: string; description: string }; data: PolicyData; loading: boolean }) {
  return <article className="policy-document-view">
    <section className="policy-document-meta"><div><dt>문서</dt><dd>{document.title}</dd></div><div><dt>화면 갱신 시각</dt><dd>{new Date().toLocaleString()}</dd></div><div><dt>소유 범위</dt><dd>현재 Workspace</dd></div><div><dt>상태</dt><dd><span className="badge">{loading ? 'LOADING' : 'LIVE READ'}</span></dd></div></section>
    <header><span className="eyebrow">{document.description}</span><h1>{document.title}</h1></header>
    {loading ? <PolicyEmpty text="서버 정책 read model을 불러오는 중입니다." /> : !data.readAllowed ? <PolicyEmpty text="이 정책 read model은 보안 관리자 권한이 있는 사용자에게만 표시됩니다." /> : document.id === 'CLASSIFICATION' ? <ClassificationDocument policy={data.classification} /> : document.id === 'RETENTION' ? <RetentionDocument policy={data.retention} /> : <LegalHoldDocument holds={data.holds} />}
  </article>
}

function ClassificationDocument({ policy }: { policy: ClassificationAccessPolicy | null }) {
  if (!policy) return <PolicyEmpty text="현재 사용자에게 표시 가능한 활성 분류·접근 정책이 없습니다." />
  return <section className="policy-body"><p>분류별 검색과 Chat의 허용 범위는 이 활성 정책과 서버 ABAC 결정에 따라 제한됩니다.</p><dl className="policy-fact-grid"><div><dt>정책 번호</dt><dd>{policy.policy_number}</dd></div><div><dt>상태</dt><dd>{policy.state}</dd></div><div><dt>관할</dt><dd>{policy.required_jurisdiction}</dd></div><div><dt>제한 검색 최대 기간</dt><dd>{policy.restricted_search_grant_maximum_days}일</dd></div></dl><h2>분류별 제어</h2><div className="policy-rule-table"><div className="policy-rule-head"><span>Classification</span><span>Search</span><span>Chat</span><span>Provider profiles</span></div>{policy.rules.map((rule) => <div key={rule.classification}><strong>{rule.classification}</strong><span>{rule.search_mode}</span><span>{rule.chat_mode}</span><code>composition: {rule.provider_profile_version_id ?? '—'}<br />embedding: {rule.embedding_provider_profile_version_id ?? '—'}<br />reranker: {rule.reranker_provider_profile_version_id ?? '—'}</code></div>)}</div></section>
}

function RetentionDocument({ policy }: { policy: RetentionPolicy | null }) {
  if (!policy) return <PolicyEmpty text="현재 사용자에게 표시 가능한 활성 보존 정책이 없습니다." />
  const entries = [
    ['완료 운영 데이터', `${policy.rules.completed_operation_days}일`], ['Chat 콘텐츠', `${policy.rules.chat_content_days}일`], ['온라인 감사 증거', `${policy.rules.audit_online_months}개월`], ['불변 아카이브', `${policy.rules.immutable_archive_years}년`],
  ]
  return <section className="policy-body"><p>보존·파기 조건은 Maker-Checker 승인과 Legal Hold 상태를 통과해야 하며, 브라우저가 직접 파기할 수 없습니다.</p><dl className="policy-fact-grid"><div><dt>정책 번호</dt><dd>{policy.policy_number}</dd></div><div><dt>상태</dt><dd>{policy.state}</dd></div><div><dt>계약</dt><dd>{policy.contract_version}</dd></div><div><dt>Partition automation</dt><dd>{policy.partition_automation_state}</dd></div><div><dt>Deletion automation</dt><dd>{policy.deletion_automation_state}</dd></div></dl><h2>보존 규칙</h2><div className="policy-retention-list">{entries.map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}</div>{policy.contract && <><h2>데이터 클래스 계약</h2><div className="policy-retention-list">{policy.contract.class_rules.map((rule) => <div key={rule.data_class}><span>{rule.data_class}</span><strong>{rule.minimum}–{rule.maximum} {rule.unit} · {rule.archive_disposition}</strong></div>)}</div></>}</section>
}

function LegalHoldDocument({ holds }: { holds: LegalHold[] }) {
  if (holds.length === 0) return <PolicyEmpty text="현재 권한 범위에 활성 또는 조회 가능한 Legal Hold가 없습니다." />
  return <section className="policy-body"><p>Legal Hold는 보존 자동화보다 우선하며, 해제도 별도의 request/decision 경로를 따릅니다.</p><div className="policy-rule-table"><div className="policy-rule-head"><span>Data class</span><span>Scope</span><span>State</span><span>Reason</span></div>{holds.map((hold) => <div key={hold.hold_id}><strong>{hold.data_class}</strong><span>{hold.scope}</span><span><i className={`policy-state-${hold.state.toLowerCase()}`} />{hold.state}</span><code>{hold.reason}</code></div>)}</div></section>
}

function PolicyWorkflowView({ document, data, loading }: { document: { id: DocumentId; title: string }; data: PolicyData; loading: boolean }) {
  const state = document.id === 'CLASSIFICATION'
    ? data.classification?.state
    : document.id === 'RETENTION'
      ? data.retention?.state
      : data.holds.length > 0
        ? `${data.holds.filter((hold) => hold.state === 'ACTIVE').length} ACTIVE / ${data.holds.length} VISIBLE`
        : undefined
  return <section className="policy-flow-view"><header><span className="eyebrow">{document.title}</span><h2>Current governed state</h2><p>이 화면은 서버가 제공하는 현재 상태만 표시합니다. 전체 lifecycle 이력은 감사 read model이 제공될 때까지 추정하지 않습니다.</p></header><div className="policy-flow-canvas"><div className={`policy-flow-node ${state ? 'current' : ''}`}><span>1</span><strong>{loading ? '조회 중' : state ?? '상태 없음'}</strong></div></div><footer><Eye size={13} /> {loading ? '상태를 불러오는 중입니다.' : state ? `서버 현재 상태: ${state}` : '현재 상태는 서버에서 확인되지 않았습니다.'}</footer></section>
}

function PolicyEmpty({ text }: { text: string }) { return <div className="policy-empty"><CheckCircle2 size={27} /><p>{text}</p></div> }
