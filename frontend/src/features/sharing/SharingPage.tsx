import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import { newIdempotencyKey, type ApiClient } from '../../api/client'
import type { ApiProduct, ConsumerGrant, KnowledgeGraph } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'

type Surface = 'SNAPSHOT' | 'NEIGHBORS' | 'CHAT'

const surfaceScope: Record<Surface, string> = {
  SNAPSHOT: 'snapshot.read',
  NEIGHBORS: 'neighbors.query',
  CHAT: 'chat.query',
}

export function SharingPage({ client }: { client: ApiClient }) {
  const [products, setProducts] = useState<ApiProduct[]>([])
  const [graphs, setGraphs] = useState<KnowledgeGraph[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [grants, setGrants] = useState<ConsumerGrant[]>([])
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [graphId, setGraphId] = useState('')
  const [surface, setSurface] = useState<Surface>('NEIGHBORS')
  const [consumerClientId, setConsumerClientId] = useState('')
  const [error, setError] = useState<unknown>()

  const selected = useMemo(
    () => products.find((product) => product.id === selectedId),
    [products, selectedId],
  )
  const selectedGraph = graphs.find((graph) => graph.id === graphId)

  const refresh = useCallback(async () => {
    try {
      const [nextProducts, nextGraphs] = await Promise.all([
        client.request<ApiProduct[]>('/api-products'),
        client.request<KnowledgeGraph[]>('/knowledge/graphs'),
      ])
      setProducts(nextProducts)
      setGraphs(nextGraphs.filter((graph) => Boolean(graph.active_release_id)))
      setSelectedId((current) => current || nextProducts[0]?.id || '')
    } catch (next) { setError(next) }
  }, [client])

  const refreshGrants = useCallback(async () => {
    if (!selectedId) { setGrants([]); return }
    try { setGrants(await client.request<ConsumerGrant[]>(`/api-products/${selectedId}/grants`)) }
    catch (next) { setError(next) }
  }, [client, selectedId])

  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => { void refreshGrants() }, [refreshGrants])

  const createProduct = async (event: FormEvent) => {
    event.preventDefault(); setError(undefined)
    if (!selectedGraph?.active_release_id) return
    const scope = surfaceScope[surface]
    try {
      await client.request<ApiProduct>('/api-products', {
        method: 'POST', idempotencyKey: newIdempotencyKey('api-product-create'),
        body: JSON.stringify({
          slug, name, description: `${selectedGraph.name} 릴리스 기반 관리형 API`,
          graph_id: selectedGraph.id, release_id: selectedGraph.active_release_id,
          surface,
          contract: {
            scopes: [scope], query_template: `${surface.toLowerCase()}-v1`,
            response_schema: { type: 'object', additionalProperties: false },
          },
          maximum_hops: surface === 'NEIGHBORS' ? 2 : 1,
          maximum_nodes: surface === 'NEIGHBORS' ? 200 : 500, timeout_ms: 5000,
        }),
      })
      setName(''); setSlug(''); await refresh()
    } catch (next) { setError(next) }
  }

  const publish = async (product: ApiProduct) => {
    const draft = product.versions.find((version) => version.state === 'DRAFT')
    if (!draft) return
    setError(undefined)
    try {
      await client.request<ApiProduct>(`/api-products/${product.id}/versions/${draft.id}/publish`, {
        method: 'POST', ifMatch: String(product.version),
      })
      await refresh()
    } catch (next) { setError(next) }
  }

  const createGrant = async (event: FormEvent) => {
    event.preventDefault(); setError(undefined)
    if (!selected?.current_version_id) return
    const current = selected.versions.find((version) => version.id === selected.current_version_id)
    if (!current) return
    const now = new Date()
    const expires = new Date(now.getTime() + 30 * 24 * 60 * 60 * 1000)
    try {
      await client.request<ConsumerGrant>(`/api-products/${selected.id}/grants`, {
        method: 'POST', idempotencyKey: newIdempotencyKey('consumer-grant-create'),
        body: JSON.stringify({
          consumer_client_id: consumerClientId,
          scopes: current.contract.scopes ?? [surfaceScope[current.surface]],
          maximum_classification: selected.classification,
          requests_per_minute: 60, monthly_quota: 100000,
          valid_from: now.toISOString(), expires_at: expires.toISOString(),
        }),
      })
      setConsumerClientId(''); await refreshGrants()
    } catch (next) { setError(next) }
  }

  return (
    <section>
      <div className="page-heading"><div><p className="eyebrow">Release-pinned contracts</p><h2>API 공유 관리</h2></div></div>
      <div className="panel-grid governance-grid">
        <form className="form-stack panel" onSubmit={(event) => void createProduct(event)}>
          <h3>API Product 초안</h3>
          <label>이름<input value={name} onChange={(event) => setName(event.target.value)} required /></label>
          <label>Slug<input value={slug} onChange={(event) => setSlug(event.target.value.toLowerCase())} pattern="[a-z][a-z0-9-]{2,99}" required /></label>
          <label>게시된 지식그래프<select value={graphId} onChange={(event) => setGraphId(event.target.value)} required><option value="">선택</option>{graphs.map((graph) => <option key={graph.id} value={graph.id}>{graph.name}</option>)}</select></label>
          <label>API 표면<select value={surface} onChange={(event) => setSurface(event.target.value as Surface)}><option value="NEIGHBORS">이웃 분석</option><option value="SNAPSHOT">스냅샷</option><option value="CHAT">CHAT</option></select></label>
          <p className="callout">계약은 선택한 불변 릴리스에 고정되며 임의 SQL/Cypher는 허용하지 않습니다.</p>
          <button className="button">초안 생성</button>
        </form>
        <div className="panel">
          <h3>Product 목록</h3>
          <div className="compact-list">{products.map((product) => <button className={selectedId === product.id ? 'selected' : ''} key={product.id} onClick={() => setSelectedId(product.id)}><span><strong>{product.name}</strong><small>{product.slug} · {product.classification}</small></span><span className="badge">{product.state}</span></button>)}</div>
        </div>
      </div>
      <ErrorNotice error={error} />
      {selected && <article className="result-card governance-detail">
        <div><span className="badge">{selected.state}</span><span className="badge badge-soft">v{selected.version}</span></div>
        <h3>{selected.name}</h3><code>{selected.graph_id}</code>
        <div className="action-row">{selected.versions.some((version) => version.state === 'DRAFT') && <button className="button" onClick={() => void publish(selected)}>강한 인증으로 게시</button>}</div>
        {selected.current_version_id && <form className="inline-form" onSubmit={(event) => void createGrant(event)}><label>OIDC Consumer client_id<input value={consumerClientId} onChange={(event) => setConsumerClientId(event.target.value)} pattern="[A-Za-z0-9._:-]+" required /></label><label>기본 정책<input value="60 RPM · 월 100,000회 · 30일" readOnly /></label><button className="button">Grant 생성</button></form>}
        <div className="result-list">{grants.map((grant) => <div className="panel" key={grant.id}><span className="badge">{grant.state}</span><h3>{grant.consumer_client_id}</h3><p>{grant.scopes.join(', ')} · {grant.requests_per_minute} RPM</p><small>{new Date(grant.expires_at).toLocaleString()} 만료</small></div>)}</div>
      </article>}
    </section>
  )
}
