import { useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  Activity,
  ArrowRight,
  BarChart2,
  BookOpen,
  Check,
  CheckCircle,
  ChevronLeft,
  ChevronRight,
  Circle,
  ClipboardList,
  Columns,
  Database,
  FileCheck,
  GitBranch,
  MessageSquare,
  Monitor,
  Network,
  PlayCircle,
  RotateCcw,
  Search,
  Send,
  Server,
  Shield,
  Sparkles,
  Table,
  Tag,
} from 'lucide-react'
import { primaryNavigation, type Page } from '../app/navigation'
import { DataRiverMark } from '../components/layout/DataRiverMark'
import { PageTitle } from '../components/layout/PageTitle'
import {
  advanceChange,
  advanceQualityRun,
  advanceRegistration,
  createPocSession,
  qualityRunProgress,
  searchPocAssets,
  type ChangeState,
  type PocSession,
  type QualityRunState,
  type RegistrationState,
} from './pocApi'
import {
  capabilityFixtures,
  knowledgeSources,
  monitoringMetrics,
  pocAssets,
  qualityRuleSets,
  type PocAsset,
} from './pocFixtures'
import {
  routeDefinition,
  routeFromHash,
  routeHash,
  type PocRoute,
} from './pocRoutes'
import { PocBanner } from './components/PocBanner'

const routeTitleIcons: Record<PocRoute, string> = {
  overview: 'OP',
  catalog: 'SR',
  registration: 'RG',
  changes: 'CR',
  metadata: 'SR',
  knowledge: 'KG',
  quality: 'DQ',
  'quality-run': 'DQ',
  chat: 'AI',
  monitoring: 'MO',
}

const registrationLabels: Record<RegistrationState, string> = {
  REQUESTED: '요청 접수',
  VALIDATED: '검증 완료',
  COMPLETED: '등록 완료',
}

const changeLabels: Record<ChangeState, string> = {
  DRAFT: '초안',
  IN_REVIEW: '검토 중',
  APPROVED: '승인됨',
}

const qualityRunLabels: Record<QualityRunState, string> = {
  QUEUED: '대기 중',
  RUNNING: '실행 중',
  COMPLETED: '완료',
}

function StatusPill({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'good' | 'warn' | 'sample' }) {
  return <span className={`poc-status poc-status-${tone}`}>{children}</span>
}

function SimulatedLabel() {
  return <span className="simulated-label">SIMULATED</span>
}

function PageIntro({ route }: { route: PocRoute }) {
  const definition = routeDefinition(route)
  return (
    <PageTitle
      icon={routeTitleIcons[route]}
      eyebrow={definition.eyebrow}
      title={definition.title}
      description={definition.description}
      actions={<div className="poc-title-actions"><span className="badge badge-soft">06111 UI</span><SimulatedLabel /></div>}
    />
  )
}

function PocTopNavigation({
  route,
  onNavigate,
  onSearch,
}: {
  route: PocRoute
  onNavigate: (route: PocRoute) => void
  onSearch: (query: string) => void
}) {
  const [navigation, setNavigation] = useState<HTMLElement | null>(null)
  const [query, setQuery] = useState('')
  const activePage = shellPageForRoute(route)

  return (
    <header className="top-navigation poc-top-navigation">
      <button className="top-brand" type="button" onClick={() => onNavigate('overview')} aria-label="DataRiver 홈">
        <span className="top-brand-mark" aria-hidden="true"><DataRiverMark /></span>
        <span>DataRiver</span>
      </button>
      <nav className="primary-navigation" aria-label="주 메뉴">
        <button className="navigation-scroll navigation-scroll-left" type="button" aria-label="이전 메뉴" onClick={() => navigation?.scrollBy({ left: -240, behavior: 'smooth' })}><ChevronLeft size={14} /></button>
        <div className="primary-navigation-track" ref={setNavigation}>
          {primaryNavigation.map(({ id, label, badge }) => (
            <button
              type="button"
              key={id}
              className={activePage === id ? 'active' : ''}
              aria-current={activePage === id ? 'page' : undefined}
              onClick={() => onNavigate(routeForShellPage(id))}
            >
              <span>{label}</span>
              {badge && <small>{badge}</small>}
            </button>
          ))}
        </div>
        <button className="navigation-scroll navigation-scroll-right" type="button" aria-label="다음 메뉴" onClick={() => navigation?.scrollBy({ left: 240, behavior: 'smooth' })}><ChevronRight size={14} /></button>
      </nav>
      <div className="global-search-wrap">
        <form
          className="global-search"
          role="search"
          onSubmit={(event) => {
            event.preventDefault()
            const trimmed = query.trim()
            if (trimmed) onSearch(trimmed)
          }}
        >
          <Search className="global-search-icon" size={16} aria-hidden="true" />
          <label className="sr-only" htmlFor="poc-global-search">전체 카탈로그 검색</label>
          <input id="poc-global-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="전체 카탈로그 검색" autoComplete="off" />
          <button type="submit">검색</button>
        </form>
      </div>
      <div className="profile-menu poc-nav-status" aria-label="POC 상태">
        <span className="poc-nav-environment">STATIC POC</span>
        <span>NO AUTH</span>
      </div>
    </header>
  )
}

function OverviewPage({ onNavigate }: { onNavigate: (route: PocRoute) => void }) {
  const walkthrough = [
    { route: 'catalog' as const, icon: <Search size={18} />, label: 'Catalog Search', description: '샘플 자산 검색과 상세' },
    { route: 'registration' as const, icon: <ClipboardList size={18} />, label: 'Registration', description: '등록 요청 상태 전환' },
    { route: 'changes' as const, icon: <GitBranch size={18} />, label: 'Change Management', description: '초안·검토·승인 시연' },
    { route: 'metadata' as const, icon: <Database size={18} />, label: 'Metadata & Lineage', description: '테이블·컬럼·계보 조회' },
    { route: 'knowledge' as const, icon: <BookOpen size={18} />, label: 'Knowledge', description: '근거와 게시 흐름' },
    { route: 'quality' as const, icon: <FileCheck size={18} />, label: 'Quality Control', description: 'Rule Set과 품질 지표' },
    { route: 'quality-run' as const, icon: <PlayCircle size={18} />, label: 'Quality Run', description: '실행 진행과 결과' },
    { route: 'chat' as const, icon: <MessageSquare size={18} />, label: 'Chat', description: '근거 연결 sample 답변' },
    { route: 'monitoring' as const, icon: <Monitor size={18} />, label: 'Monitoring', description: 'synthetic 운영 지표' },
  ]
  return (
    <section className="dashboard-page">
      <PageIntro route="overview" />
      <p className="dashboard-contract-note">현재 시점 Static POC · synthetic fixture만 표시 · 모든 상태는 새로고침 시 초기화됩니다.</p>
      <div className="dashboard-stat-grid" aria-label="Sample platform summary">
        <a className="dashboard-stat-card" href={routeHash('catalog')} onClick={(event) => { event.preventDefault(); onNavigate('catalog') }}><span className="dashboard-stat-icon"><Database size={20} /></span><p>Catalog assets</p><div><strong>4</strong><small>tables</small></div><span className="dashboard-stat-detail">synthetic fixture</span></a>
        <a className="dashboard-stat-card" href={routeHash('quality')} onClick={(event) => { event.preventDefault(); onNavigate('quality') }}><span className="dashboard-stat-icon"><FileCheck size={20} /></span><p>Quality posture</p><div><strong>96.4</strong><small>%</small></div><span className="dashboard-stat-detail">sample score</span></a>
        <a className="dashboard-stat-card" href={routeHash('changes')} onClick={(event) => { event.preventDefault(); onNavigate('changes') }}><span className="dashboard-stat-icon"><GitBranch size={20} /></span><p>Governed flows</p><div><strong>3</strong><small>flows</small></div><span className="dashboard-stat-detail">memory only</span></a>
        <a className="dashboard-stat-card" href={routeHash('monitoring')} onClick={(event) => { event.preventDefault(); onNavigate('monitoring') }}><span className="dashboard-stat-icon"><Shield size={20} /></span><p>External calls</p><div><strong>0</strong><small>calls</small></div><span className="dashboard-stat-detail">application design</span></a>
      </div>
      <section className="dashboard-section poc-capability-section">
        <header><span><Activity size={16} /></span><h2>POC Capability Map</h2></header>
        <div className="dashboard-section-body"><div className="dashboard-capabilities">{capabilityFixtures.map((capability) => <span className={`dashboard-capability ${capability.status === 'AVAILABLE' ? 'state-healthy' : 'state-degraded'}`} key={capability.name}><i /><b>{capability.name}</b><small>{capability.detail} · {capability.status}</small></span>)}</div></div>
      </section>
      <div className="dashboard-bottom-grid">
        <section className="dashboard-section">
          <header><span><Activity size={16} /></span><h2>Static Walkthrough</h2></header>
          <div className="dashboard-section-body"><nav className="dashboard-quick-actions" aria-label="POC walkthrough shortcuts">{walkthrough.map((item) => <a href={routeHash(item.route)} key={item.route} onClick={(event) => { event.preventDefault(); onNavigate(item.route) }}><span>{item.icon}</span><span><strong>{item.label}</strong><small>{item.description}</small></span><ArrowRight size={15} /></a>)}</nav></div>
        </section>
        <section className="dashboard-section">
          <header><span><Shield size={16} /></span><h2>Demonstration Boundary</h2></header>
          <div className="dashboard-section-body poc-boundary-grid"><div className="dashboard-audit-unavailable"><Shield size={20} /><div><strong>NO AUTH / SAMPLE DATA</strong><p>인증·인가·RLS·provider 연결을 시연하거나 증명하지 않습니다.</p></div></div><div className="dashboard-operation-grid"><span className="dashboard-operation-fact"><small>Persistence</small><strong>NONE</strong></span><span className="dashboard-operation-fact"><small>Canonical data</small><strong>NONE</strong></span><span className="dashboard-operation-fact"><small>Integration</small><strong>SIMULATED</strong></span><span className="dashboard-operation-fact"><small>Runtime</small><strong>STATIC</strong></span></div></div>
        </section>
      </div>
    </section>
  )
}

type AssetTab = 'details' | 'columns' | 'lineage'

function AssetDetailView({
  asset,
  tab,
  onTabChange,
  glossaryActionApplied,
  onGlossaryAction,
}: {
  asset: PocAsset
  tab: AssetTab
  onTabChange: (tab: AssetTab) => void
  glossaryActionApplied: boolean
  onGlossaryAction?: () => void
}) {
  return (
    <article className="asset-detail">
      <header className="asset-detail-header">
        <div>
          <div className="asset-kind"><Table size={15} aria-hidden="true" /> DATASET</div>
          <h2>{asset.name}</h2>
          <p>{asset.platform} · {asset.database}.{asset.schema}</p>
        </div>
        <div className="asset-score"><span>Quality</span><strong>{asset.quality}</strong><small>/ 100</small></div>
      </header>
      <div className="detail-tabs" role="tablist" aria-label="Asset details">
        <button type="button" role="tab" aria-selected={tab === 'details'} onClick={() => onTabChange('details')}><Table size={15} />Table details</button>
        <button type="button" role="tab" aria-selected={tab === 'columns'} onClick={() => onTabChange('columns')}><Columns size={15} />Columns</button>
        <button type="button" role="tab" aria-selected={tab === 'lineage'} onClick={() => onTabChange('lineage')}><Network size={15} />Lineage</button>
      </div>

      {tab === 'details' && (
        <div className="detail-body">
          <p className="detail-description">{asset.description}</p>
          <dl className="detail-facts">
            <div><dt>Domain</dt><dd>{asset.domain}</dd></div>
            <div><dt>Owner</dt><dd>{asset.owner}</dd></div>
            <div><dt>Rows</dt><dd>{asset.rows}</dd></div>
            <div><dt>Size</dt><dd>{asset.size}</dd></div>
            <div><dt>Freshness</dt><dd>{asset.freshness}</dd></div>
            <div><dt>Classification</dt><dd>{asset.classification}</dd></div>
          </dl>
          <div className="term-grid">
            <div><h3><Tag size={15} /> Tags</h3><div className="chip-row">{asset.tags.map((tag) => <span className="data-chip" key={tag}>{tag}</span>)}</div></div>
            <div><h3><BookOpen size={15} /> Glossary terms</h3><div className="chip-row">{asset.terms.map((term) => <span className="data-chip data-chip-teal" key={term}>{term}</span>)}</div></div>
          </div>
        </div>
      )}

      {tab === 'columns' && (
        <div className="table-scroll">
          <table className="poc-table">
            <thead><tr><th>Column</th><th>Type</th><th>Description</th><th>Nullable</th><th>Quality</th></tr></thead>
            <tbody>{asset.columns.map((column) => (
              <tr key={column.name}>
                <td><code>{column.name}</code></td><td>{column.type}</td><td>{column.description}</td>
                <td>{column.nullable ? 'Yes' : 'No'}</td><td><strong>{column.quality}%</strong></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}

      {tab === 'lineage' && (
        <div className="lineage-panel">
          <div className="lineage-legend"><span><i className="lineage-dot lineage-dot-upstream" />Upstream</span><span><i className="lineage-dot lineage-dot-current" />Current</span><span><i className="lineage-dot lineage-dot-downstream" />Downstream</span></div>
          <div className="lineage-flow">
            <div className="lineage-column">
              <span className="lineage-stage">UPSTREAM</span>
              {asset.upstream.map((node) => <div className="lineage-node lineage-upstream" key={node}><Database size={15} />{node}</div>)}
            </div>
            <ChevronRight className="lineage-arrow" aria-hidden="true" />
            <div className="lineage-column"><span className="lineage-stage">CURRENT</span><div className="lineage-node lineage-current"><Table size={15} />{asset.name}</div></div>
            <ChevronRight className="lineage-arrow" aria-hidden="true" />
            <div className="lineage-column">
              <span className="lineage-stage">DOWNSTREAM</span>
              {asset.downstream.map((node) => <div className="lineage-node lineage-downstream" key={node}><BarChart2 size={15} />{node}</div>)}
            </div>
          </div>
        </div>
      )}

      {onGlossaryAction && (
        <footer className="simulated-action-bar">
          <div><SimulatedLabel /><span>관리 작업은 이 브라우저 메모리에서만 바뀝니다.</span></div>
          <button className="poc-button poc-button-secondary" type="button" onClick={onGlossaryAction} disabled={glossaryActionApplied}>
            {glossaryActionApplied ? <><Check size={16} /> 용어 연결됨 (sample)</> : 'Glossary term 연결 시연'}
          </button>
        </footer>
      )}
    </article>
  )
}

function CatalogPage({ initialQuery = '' }: { initialQuery?: string }) {
  const [query, setQuery] = useState(initialQuery)
  const [domain, setDomain] = useState('ALL')
  const [selectedId, setSelectedId] = useState<string>(pocAssets[0].id)
  const [tab, setTab] = useState<AssetTab>('details')
  const domains = useMemo(() => ['ALL', ...new Set(pocAssets.map((asset) => asset.domain))], [])
  const results = useMemo(() => searchPocAssets(query, domain), [domain, query])
  const selected = results.find((asset) => asset.id === selectedId) ?? results[0]

  return (
    <>
      <PageIntro route="catalog" />
      <section className="catalog-toolbar" aria-label="Catalog search controls">
        <label className="search-field"><Search size={18} aria-hidden="true" /><span className="sr-only">Search sample assets</span><input aria-label="Search sample assets" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="asset, owner, term or column" /></label>
        <label className="select-field"><span>Domain</span><select aria-label="Filter by domain" value={domain} onChange={(event) => setDomain(event.target.value)}>{domains.map((item) => <option value={item} key={item}>{item === 'ALL' ? 'All domains' : item}</option>)}</select></label>
        <div className="result-count"><strong>{results.length}</strong><span>sample assets</span></div>
      </section>
      <div className="catalog-layout">
        <section className="result-list" aria-label="Search results">
          {results.map((asset) => (
            <button className="result-card" data-selected={selected?.id === asset.id} type="button" key={asset.id} onClick={() => { setSelectedId(asset.id); setTab('details') }}>
              <span className="result-icon"><Table size={19} /></span>
              <span className="result-copy"><strong>{asset.name}</strong><small>{asset.platform} · {asset.database}.{asset.schema}</small><span>{asset.description}</span><i>{asset.domain}</i></span>
              <span className="result-quality"><strong>{asset.quality}</strong><small>quality</small></span>
            </button>
          ))}
          {results.length === 0 && <div className="empty-state"><Search size={28} /><h2>No sample result</h2><p>검색어 또는 Domain 필터를 바꿔 보세요.</p></div>}
        </section>
        {selected ? <AssetDetailView asset={selected} tab={tab} onTabChange={setTab} glossaryActionApplied={false} /> : <div className="asset-detail empty-detail">선택할 sample asset이 없습니다.</div>}
      </div>
    </>
  )
}

function WorkflowStepper<State extends string>({ states, current, labels }: { states: readonly State[]; current: State; labels: Record<State, string> }) {
  const currentIndex = states.indexOf(current)
  return (
    <ol className="workflow-stepper">
      {states.map((state, index) => (
        <li className={index < currentIndex ? 'is-complete' : index === currentIndex ? 'is-current' : ''} key={state}>
          <span>{index < currentIndex ? <Check size={16} /> : index + 1}</span>
          <div><strong>{labels[state]}</strong><small>{index < currentIndex ? '완료' : index === currentIndex ? '현재 상태' : '대기'}</small></div>
        </li>
      ))}
    </ol>
  )
}

function RegistrationPage({ session, updateSession, resetSession }: SessionPageProps) {
  const terminal = session.registration === 'COMPLETED'
  return (
    <>
      <PageIntro route="registration" />
      <section className="workflow-layout">
        <article className="workflow-card">
          <header className="workflow-card-header"><div><span className="record-id">REG-SAMPLE-0142</span><h2>Wafer inspection event stream</h2><p>MANUAL · Snowflake · Manufacturing Quality</p></div><StatusPill tone={terminal ? 'good' : 'sample'}>{registrationLabels[session.registration]}</StatusPill></header>
          <WorkflowStepper states={['REQUESTED', 'VALIDATED', 'COMPLETED']} current={session.registration} labels={registrationLabels} />
          <div className="evidence-list">
            <div><CheckCircle size={18} /><span><strong>Required metadata</strong><small>Owner, domain and description supplied</small></span></div>
            <div><CheckCircle size={18} /><span><strong>Fixture schema</strong><small>5 columns · deterministic local validation</small></span></div>
            <div><Shield size={18} /><span><strong>Sensitive data</strong><small>No source values or provider response included</small></span></div>
          </div>
          <footer className="workflow-footer">
            <span><SimulatedLabel /> No DataHub command is sent.</span>
            <div><button className="icon-button" type="button" aria-label="Reset registration demo" onClick={resetSession}><RotateCcw size={16} /></button><button className="poc-button poc-button-primary" type="button" disabled={terminal} onClick={() => updateSession({ registration: advanceRegistration(session.registration) })}>{terminal ? '시연 완료' : '다음 단계'} <ArrowRight size={16} /></button></div>
          </footer>
        </article>
        <aside className="context-card"><p className="eyebrow">Sample validation</p><h2>Ready for walkthrough</h2><div className="context-score"><strong>5/5</strong><span>fixture fields valid</span></div><ul><li><Check />Name convention</li><li><Check />Ownership present</li><li><Check />Classification set</li><li><Check />Schema shape</li><li><Check />Description quality</li></ul></aside>
      </section>
    </>
  )
}

function ChangePage({ session, updateSession, resetSession }: SessionPageProps) {
  const terminal = session.change === 'APPROVED'
  return (
    <>
      <PageIntro route="changes" />
      <section className="workflow-layout">
        <article className="workflow-card">
          <header className="workflow-card-header"><div><span className="record-id">CR-SAMPLE-0088 · REV 1</span><h2>Add “inspection severity” glossary term</h2><p>Requested by Sample Data Steward · independent review illustrated</p></div><StatusPill tone={terminal ? 'good' : 'warn'}>{changeLabels[session.change]}</StatusPill></header>
          <WorkflowStepper states={['DRAFT', 'IN_REVIEW', 'APPROVED']} current={session.change} labels={changeLabels} />
          <div className="change-diff">
            <div><span className="diff-label">TARGET</span><code>wafer_inspection_events.defect_code</code></div>
            <div><span className="diff-label">CHANGE</span><p><del>Defect taxonomy code</del><ins>Inspection severity and defect taxonomy code</ins></p></div>
            <div><span className="diff-label">EVIDENCE</span><p>Sample glossary reference · sanitized fixture · no provider read-back</p></div>
          </div>
          <footer className="workflow-footer"><span><SimulatedLabel /> Approval does not claim application.</span><div><button className="icon-button" type="button" aria-label="Reset change demo" onClick={resetSession}><RotateCcw size={16} /></button><button className="poc-button poc-button-primary" type="button" disabled={terminal} onClick={() => updateSession({ change: advanceChange(session.change) })}>{session.change === 'DRAFT' ? '검토 제출' : session.change === 'IN_REVIEW' ? '승인 시연' : '시연 완료'} <ArrowRight size={16} /></button></div></footer>
        </article>
        <aside className="context-card review-card"><p className="eyebrow">Review signals</p><h2>Governance context</h2><dl><div><dt>Risk</dt><dd>Low</dd></div><div><dt>Data class</dt><dd>Internal</dd></div><div><dt>Impacted assets</dt><dd>1 sample</dd></div><div><dt>Maker / checker</dt><dd>Illustrated</dd></div></dl><div className="review-note"><Shield size={18} /><p>Identity, assurance and authorization are unavailable in this no-auth POC.</p></div></aside>
      </section>
    </>
  )
}

function MetadataPage({ session, updateSession }: SessionPageProps) {
  const [assetId, setAssetId] = useState<string>(pocAssets[0].id)
  const [tab, setTab] = useState<AssetTab>('details')
  const asset = pocAssets.find((item) => item.id === assetId) ?? pocAssets[0]
  return (
    <>
      <PageIntro route="metadata" />
      <section className="metadata-toolbar"><div><Database size={18} /><span><strong>Sample metadata explorer</strong><small>DataHub-style presentation; not a DataHub session</small></span></div><label className="select-field"><span>Dataset</span><select aria-label="Select metadata dataset" value={assetId} onChange={(event) => { setAssetId(event.target.value); setTab('details') }}>{pocAssets.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label></section>
      <AssetDetailView asset={asset} tab={tab} onTabChange={setTab} glossaryActionApplied={session.glossaryActionApplied} onGlossaryAction={() => updateSession({ glossaryActionApplied: true })} />
    </>
  )
}

function KnowledgePage({ session, updateSession, resetSession }: SessionPageProps) {
  return (
    <>
      <PageIntro route="knowledge" />
      <section className="knowledge-layout">
        <article className="knowledge-graph-card"><div className="section-heading compact"><div><p className="eyebrow">Sample evidence graph</p><h2>Yield excursion knowledge</h2></div><StatusPill tone={session.knowledgePublished ? 'good' : 'warn'}>{session.knowledgePublished ? 'PUBLISHED (sample)' : 'DRAFT (sample)'}</StatusPill></div><div className="knowledge-graph"><div className="knowledge-node knowledge-center"><Sparkles size={21} /><strong>Yield excursion</strong><span>Knowledge Asset</span></div><div className="knowledge-node knowledge-node-a"><BookOpen size={17} /><strong>Response guide</strong><span>Document</span></div><div className="knowledge-node knowledge-node-b"><Database size={17} /><strong>Inspection events</strong><span>Dataset</span></div><div className="knowledge-node knowledge-node-c"><Tag size={17} /><strong>Defect</strong><span>Glossary term</span></div><div className="graph-link graph-link-a" /><div className="graph-link graph-link-b" /><div className="graph-link graph-link-c" /></div><footer className="workflow-footer"><span><SimulatedLabel /> No graph or object provider is contacted.</span><div><button className="icon-button" aria-label="Reset knowledge demo" type="button" onClick={resetSession}><RotateCcw size={16} /></button><button className="poc-button poc-button-primary" type="button" disabled={session.knowledgePublished} onClick={() => updateSession({ knowledgePublished: true })}>{session.knowledgePublished ? '시연 완료' : '게시 시연'} <ArrowRight size={16} /></button></div></footer></article>
        <section className="source-list"><div className="section-heading compact"><div><p className="eyebrow">Evidence inventory</p><h2>Connected sample sources</h2></div><span className="section-note">3 items</span></div>{knowledgeSources.map((source) => <article className="source-row" key={source.title}><span className="source-icon"><BookOpen size={18} /></span><div><h3>{source.title}</h3><p>{source.kind} · {source.version}</p></div><span className="source-evidence">{source.evidence}<small>evidence</small></span><StatusPill tone={source.state === 'PUBLISHED' ? 'good' : 'warn'}>{source.state}</StatusPill></article>)}</section>
      </section>
    </>
  )
}

function QualityPage() {
  return (
    <>
      <PageIntro route="quality" />
      <section className="quality-summary"><article><span className="quality-icon"><Shield size={20} /></span><div><small>Overall sample score</small><strong>96.4%</strong><p>+1.8 points from prior fixture</p></div></article><article><span className="quality-icon"><FileCheck size={20} /></span><div><small>Active Rule Sets</small><strong>2</strong><p>1 sample draft</p></div></article><article><span className="quality-icon"><Table size={20} /></span><div><small>Covered assets</small><strong>6</strong><p>synthetic coverage</p></div></article><article><span className="quality-icon"><Activity size={20} /></span><div><small>Open issues</small><strong>3</strong><p>sanitized counts</p></div></article></section>
      <section className="section-block quality-table-card"><div className="section-heading"><div><p className="eyebrow">Rule Set inventory</p><h2>Quality definitions</h2></div><SimulatedLabel /></div><div className="table-scroll"><table className="poc-table"><thead><tr><th>Rule Set</th><th>Owner</th><th>Rules</th><th>Coverage</th><th>Latest score</th><th>Status</th></tr></thead><tbody>{qualityRuleSets.map((ruleSet) => <tr key={ruleSet.name}><td><strong>{ruleSet.name}</strong></td><td>{ruleSet.owner}</td><td>{ruleSet.rules}</td><td>{ruleSet.coverage}</td><td><strong>{ruleSet.score}%</strong></td><td><StatusPill tone={ruleSet.status === 'ACTIVE' ? 'good' : 'warn'}>{ruleSet.status}</StatusPill></td></tr>)}</tbody></table></div></section>
      <section className="rule-preview-grid"><article><span className="rule-kind">COMPLETENESS</span><h3>wafer_id must not be null</h3><p>Required identifier on every sample inspection event.</p><footer><span>Observed 100%</span><StatusPill tone="good">PASS</StatusPill></footer></article><article><span className="rule-kind">VALIDITY</span><h3>defect_count is non-negative</h3><p>Bounded numeric rule illustrated over sanitized results.</p><footer><span>Observed 99.8%</span><StatusPill tone="good">PASS</StatusPill></footer></article><article><span className="rule-kind">FRESHNESS</span><h3>inspection data within 30 min</h3><p>Fixture watermark compared with a sample threshold.</p><footer><span>Observed 12 min</span><StatusPill tone="good">PASS</StatusPill></footer></article></section>
    </>
  )
}

function QualityRunPage({ session, updateSession, resetSession }: SessionPageProps) {
  const progress = qualityRunProgress(session.qualityRun)
  const terminal = session.qualityRun === 'COMPLETED'
  return (
    <>
      <PageIntro route="quality-run" />
      <section className="run-layout">
        <article className="run-card">
          <header><div><span className="record-id">RUN-SAMPLE-20260811-01</span><h2>Wafer inspection essentials</h2><p>Manual sample execution · 8 deterministic checks</p></div><StatusPill tone={terminal ? 'good' : 'sample'}>{qualityRunLabels[session.qualityRun]}</StatusPill></header>
          <div className="run-progress"><div className="progress-label"><span>Sample execution progress</span><strong>{progress}%</strong></div><div className="progress-track" role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}><span className={`progress-fill progress-${progress}`} /></div></div>
          <ol className="run-events"><li className="is-done"><CheckCircle /><div><strong>Fixture snapshot pinned</strong><span>Synthetic asset and Rule Set selected</span></div><time>00:00</time></li><li className={session.qualityRun !== 'QUEUED' ? 'is-done' : 'is-next'}>{session.qualityRun !== 'QUEUED' ? <CheckCircle /> : <Circle />}<div><strong>Checks evaluated</strong><span>Local deterministic result set only</span></div><time>00:04</time></li><li className={terminal ? 'is-done' : 'is-next'}>{terminal ? <CheckCircle /> : <Circle />}<div><strong>Sanitized results assembled</strong><span>No unexpected rows or source values retained</span></div><time>00:07</time></li></ol>
          {terminal && <div className="run-results"><article><strong>8</strong><span>checks</span></article><article><strong>7</strong><span>passed</span></article><article><strong>1</strong><span>warning</span></article><article><strong>0</strong><span>raw rows</span></article></div>}
          <footer className="workflow-footer"><span><SimulatedLabel /> No source, worker or Airflow execution occurred.</span><div><button className="icon-button" type="button" aria-label="Reset quality run demo" onClick={resetSession}><RotateCcw size={16} /></button><button className="poc-button poc-button-primary" type="button" disabled={terminal} onClick={() => updateSession({ qualityRun: advanceQualityRun(session.qualityRun) })}>{session.qualityRun === 'QUEUED' ? '실행 시작' : session.qualityRun === 'RUNNING' ? '결과 완료' : '시연 완료'} <ArrowRight size={16} /></button></div></footer>
        </article>
        <aside className="result-safety-card"><Shield size={24} /><p className="eyebrow">Result safety</p><h2>Sanitized by design</h2><p>이 화면의 실패 수와 결과는 fixture입니다. 원본 행, 값, 인덱스, query, credential 또는 provider 오류가 포함되지 않습니다.</p><dl><div><dt>Execution</dt><dd>SIMULATED</dd></div><div><dt>Canonical result</dt><dd>NONE</dd></div><div><dt>Persistence</dt><dd>NONE</dd></div></dl></aside>
      </section>
    </>
  )
}

function ChatPage({ session, updateSession, resetSession }: SessionPageProps) {
  const [question, setQuestion] = useState('최근 wafer inspection 품질 상태와 근거를 알려줘')
  return (
    <>
      <PageIntro route="chat" />
      <section className="chat-shell">
        <header><div className="chat-avatar"><Sparkles size={20} /></div><div><h2>DataRiver Evidence Chat</h2><p><SimulatedLabel /> canned response · no model connection</p></div><StatusPill tone="sample">SAMPLE SESSION</StatusPill></header>
        <div className="chat-messages" aria-live="polite">
          <div className="chat-message chat-message-user"><span>Sample user</span><p>{question || '질문을 입력하세요.'}</p></div>
          {session.chatAnswered ? <div className="chat-message chat-message-assistant"><span><Sparkles size={14} /> Simulated answer</span><p>샘플 <strong>wafer_inspection_events</strong>의 품질 점수는 <strong>97/100</strong>이며, 최신 fixture watermark는 12분 전입니다. 8개 sample check 중 7개가 통과했고 1개는 경고로 표시됩니다. 이 답변은 아래 synthetic evidence에만 연결되어 있으며 실제 시스템 상태를 증명하지 않습니다.</p><div className="citation-row"><button type="button">[1] wafer_inspection_events</button><button type="button">[2] Wafer inspection essentials</button><button type="button">[3] RUN-SAMPLE-20260811-01</button></div></div> : <div className="chat-placeholder"><MessageSquare size={26} /><p>Send the sample question to reveal a deterministic answer.</p></div>}
        </div>
        <footer className="chat-composer"><label><span className="sr-only">Sample chat question</span><input aria-label="Sample chat question" value={question} onChange={(event) => setQuestion(event.target.value)} /></label><button className="icon-button" type="button" aria-label="Reset chat demo" onClick={resetSession}><RotateCcw size={17} /></button><button className="poc-button poc-button-primary" type="button" onClick={() => updateSession({ chatAnswered: true })} disabled={!question.trim() || session.chatAnswered}><Send size={16} />{session.chatAnswered ? '답변 표시됨' : 'Sample 답변'}</button></footer>
      </section>
    </>
  )
}

function MonitoringPage() {
  return (
    <>
      <PageIntro route="monitoring" />
      <section className="monitoring-grid">{monitoringMetrics.map((metric) => <article className="monitor-card" key={metric.label}><header><span>{metric.label}</span><StatusPill tone="sample">SIMULATED</StatusPill></header><strong>{metric.value}</strong><p>{metric.note}</p><div className="mini-track"><span className={`mini-fill metric-${metric.level}`} /></div></article>)}</section>
      <section className="monitor-layout">
        <article className="activity-chart"><div className="section-heading compact"><div><p className="eyebrow">Synthetic traffic</p><h2>Catalog activity · 24h</h2></div><span className="section-note">sample requests</span></div><div className="bar-chart" aria-label="Synthetic catalog activity bar chart"><span className="bar-42" /><span className="bar-51" /><span className="bar-44" /><span className="bar-63" /><span className="bar-58" /><span className="bar-76" /><span className="bar-68" /><span className="bar-84" /><span className="bar-72" /><span className="bar-91" /><span className="bar-78" /><span className="bar-67" /></div><div className="chart-axis"><span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>24:00</span></div></article>
        <article className="dependency-card"><div className="section-heading compact"><div><p className="eyebrow">Component posture</p><h2>Presentation states</h2></div><SimulatedLabel /></div><ul><li><span className="dependency-icon"><Server size={17} /></span><div><strong>Static Web</strong><small>This container only</small></div><StatusPill tone="good">AVAILABLE</StatusPill></li><li><span className="dependency-icon"><Database size={17} /></span><div><strong>Catalog data</strong><small>Local fixture module</small></div><StatusPill tone="sample">SAMPLE</StatusPill></li><li><span className="dependency-icon"><GitBranch size={17} /></span><div><strong>Governance</strong><small>Memory-only transitions</small></div><StatusPill tone="sample">SIMULATED</StatusPill></li><li><span className="dependency-icon"><MessageSquare size={17} /></span><div><strong>Model provider</strong><small>No connection configured</small></div><StatusPill>NOT CONNECTED</StatusPill></li></ul></article>
      </section>
    </>
  )
}

type SessionPageProps = {
  session: PocSession
  updateSession: (change: Partial<PocSession>) => void
  resetSession: () => void
}

function shellPageForRoute(route: PocRoute): Page {
  if (route === 'overview') return 'dashboard'
  if (route === 'changes') return 'change-management'
  if (route === 'metadata') return 'catalog'
  if (route === 'quality-run') return 'quality'
  return route
}

function routeForShellPage(page: Page): PocRoute {
  if (page === 'catalog') return 'catalog'
  if (page === 'registration') return 'registration'
  if (page === 'change-management' || page === 'governance') return 'changes'
  if (page === 'quality') return 'quality'
  if (page === 'knowledge' || page.startsWith('knowledge-')) return 'knowledge'
  if (page === 'monitoring') return 'monitoring'
  if (page === 'chat') return 'chat'
  return 'overview'
}

export function PocApp() {
  const [route, setRoute] = useState<PocRoute>(routeFromHash)
  const [session, setSession] = useState<PocSession>(createPocSession)
  const [catalogQuery, setCatalogQuery] = useState('')

  useEffect(() => {
    const onLocationChange = () => setRoute(routeFromHash())
    window.addEventListener('hashchange', onLocationChange)
    window.addEventListener('popstate', onLocationChange)
    return () => {
      window.removeEventListener('hashchange', onLocationChange)
      window.removeEventListener('popstate', onLocationChange)
    }
  }, [])

  const navigate = (next: PocRoute) => {
    const nextHash = routeHash(next)
    if (window.location.hash !== nextHash) window.history.pushState({}, '', nextHash)
    setRoute(next)
    window.scrollTo?.({ top: 0, behavior: 'smooth' })
  }
  const updateSession = (change: Partial<PocSession>) => setSession((current) => ({ ...current, ...change }))
  const resetSession = () => setSession(createPocSession())

  return (
    <div className="poc-app">
      <PocBanner />
      <div className="app-shell">
        <a className="skip-link" href="#main-content">본문으로 건너뛰기</a>
        <PocTopNavigation
          route={route}
          onNavigate={navigate}
          onSearch={(query) => { setCatalogQuery(query); navigate('catalog') }}
        />
        <main className="workspace" id="main-content">
          <div className="page-content">
            {route === 'overview' && <OverviewPage onNavigate={navigate} />}
            {route === 'catalog' && <CatalogPage key={catalogQuery} initialQuery={catalogQuery} />}
            {route === 'registration' && <RegistrationPage session={session} updateSession={updateSession} resetSession={resetSession} />}
            {route === 'changes' && <ChangePage session={session} updateSession={updateSession} resetSession={resetSession} />}
            {route === 'metadata' && <MetadataPage session={session} updateSession={updateSession} resetSession={resetSession} />}
            {route === 'knowledge' && <KnowledgePage session={session} updateSession={updateSession} resetSession={resetSession} />}
            {route === 'quality' && <QualityPage />}
            {route === 'quality-run' && <QualityRunPage session={session} updateSession={updateSession} resetSession={resetSession} />}
            {route === 'chat' && <ChatPage session={session} updateSession={updateSession} resetSession={resetSession} />}
            {route === 'monitoring' && <MonitoringPage />}
          </div>
        </main>
        <footer className="deployment-footer">[Environment: Static POC · No Auth · Sample Data]</footer>
      </div>
    </div>
  )
}
