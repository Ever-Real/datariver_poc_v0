import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { newIdempotencyKey, type ApiClient } from '../../api/client'
import type { KnowledgeGraph } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'

export function KnowledgePage({ client }: { client: ApiClient }) {
  const [graphs, setGraphs] = useState<KnowledgeGraph[]>([])
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [error, setError] = useState<unknown>()

  const refresh = useCallback(async () => {
    try { setGraphs(await client.request<KnowledgeGraph[]>('/knowledge/graphs')) }
    catch (next) { setError(next) }
  }, [client])
  useEffect(() => { void refresh() }, [refresh])

  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError(undefined)
    try {
      await client.request<KnowledgeGraph>('/knowledge/graphs', {
        method: 'POST', idempotencyKey: newIdempotencyKey('graph-create'),
        body: JSON.stringify({
          slug, name, graph_type: 'CURATED_KNOWLEDGE', classification: 'INTERNAL',
          ontology: {
            entity_types: ['Company', 'Facility', 'Material', 'Process', 'Product', 'Technology'],
            edge_types: ['SUPPLIES', 'LOCATED_IN', 'USES', 'PRODUCES', 'DEPENDS_ON'],
          },
        }),
      })
      setName(''); setSlug(''); await refresh()
    } catch (next) { setError(next) }
  }

  return (
    <section>
      <div className="page-heading"><div><p className="eyebrow">Immutable Releases</p><h2>지식그래프 관리</h2></div></div>
      <form className="inline-form panel" onSubmit={(event) => void submit(event)}>
        <label>그래프 이름<input value={name} onChange={(event) => setName(event.target.value)} required /></label>
        <label>Slug<input value={slug} onChange={(event) => setSlug(event.target.value.toLowerCase())} pattern="[a-z][a-z0-9-]{2,99}" required /></label>
        <button className="button">생성</button>
      </form>
      <ErrorNotice error={error} />
      <div className="result-list">{graphs.map((graph) => <article className="result-card" key={graph.id}><div><span className="badge">{graph.status}</span><span className="badge badge-soft">{graph.classification}</span></div><h3>{graph.name}</h3><p>{graph.graph_type} · v{graph.version}</p><code>{graph.active_release_id || '아직 게시된 릴리스 없음'}</code></article>)}</div>
    </section>
  )
}
