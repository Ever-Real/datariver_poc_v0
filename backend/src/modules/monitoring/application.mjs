
// Dependencies are supplied by bootstrap; this module never constructs a shared client.
export function createModulesMonitoringApplication(deps) {
function monitoringDashboards() {
  const raw = deps.process.env.MONITORING_DASHBOARDS_JSON?.trim()
  const parsed = raw ? JSON.parse(raw) : undefined
  const source = Array.isArray(parsed) && parsed.length > 0 ? parsed : deps.grafanaUiUrl ? [{
    id: 'poc-grafana-dashboard', label: 'Grafana', url: deps.grafanaUiUrl, height_px: 900,
  }] : parsed ?? []
  if (!Array.isArray(source) || source.length > 8) {
    throw new Error('MONITORING_DASHBOARDS_JSON must be an array with at most 8 dashboards.')
  }
  const ids = new Set()
  return source.map((item, index) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) {
      throw new Error(`Monitoring dashboard ${index + 1} must be an object.`)
    }
    const id = deps.boundedString(item.id, 100).trim()
    const label = deps.boundedString(item.label, 80).trim()
    const url = optionalDashboardUrl(item.url, `MONITORING_DASHBOARDS_JSON[${index}].url`)
    const height = Number(item.height_px ?? 900)
    if (!/^[a-zA-Z][a-zA-Z0-9_-]{1,99}$/.test(id) || ids.has(id) || !label) {
      throw new Error(`Monitoring dashboard ${index + 1} has an invalid or duplicate id/label.`)
    }
    if (!Number.isInteger(height) || height < 480 || height > 2_000) {
      throw new Error(`Monitoring dashboard ${index + 1} height_px must be between 480 and 2000.`)
    }
    ids.add(id)
    const embedAvailable = Boolean(
      deps.grafanaEmbedEnabled
      && deps.grafanaEmbedBaseUrl
      && deps.grafanaEvidenceReference
      && new deps.URL(url).origin === new deps.URL(deps.grafanaEmbedBaseUrl).origin,
    )
    return {
      id, label, url, height_px: height,
      embed_state: embedAvailable ? 'AVAILABLE' : 'DISABLED',
      ...(embedAvailable ? { embed_url: url } : {}),
    }
  })
}

function optionalDashboardUrl(raw, name) {
  if (typeof raw !== 'string' || !raw.trim()) throw new Error(`${name} is required.`)
  const value = new deps.URL(raw.trim())
  if (!['http:', 'https:'].includes(value.protocol) || value.username || value.password || value.hash) {
    throw new Error(`${name} must be an http(s) URL without credentials or a fragment.`)
  }
  return value.toString()
}

async function providerState(name, enabled, probe) {
  if (!enabled) return { name, state: 'disabled', observed_at: new Date().toISOString(), latency_ms: null, detail_code: 'NOT_CONFIGURED' }
  const started = Date.now()
  try {
    const detailCode = await probe()
    return { name, state: 'available', observed_at: new Date().toISOString(), latency_ms: Date.now() - started, detail_code: detailCode || 'LIVE' }
  } catch (error) {
    return {
      name,
      state: 'unavailable',
      observed_at: new Date().toISOString(),
      latency_ms: Date.now() - started,
      detail_code: error?.detailCode || 'PROBE_FAILED',
    }
  }
}

async function capabilities() {
  const items = await Promise.all([
    providerState('DataHub', Boolean(deps.datahub), async () => {
      await deps.requireOk(await deps.providerFetch(deps.joinProviderUrl(deps.datahub.url, '/config'), { headers: deps.datahubHeaders() }), 'DataHub')
      return 'LIVE'
    }),
    providerState('Airflow', Boolean(deps.airflow), async () => `AIRFLOW_API_${(await deps.detectAirflowApiVersion()).toUpperCase()}`),
    providerState('MinIO', Boolean(deps.minio), async () => {
      await deps.requireOk(await deps.providerFetch(deps.joinProviderUrl(deps.minio.url, '/minio/health/live')), 'MinIO')
      return 'LIVE'
    }),
    providerState('LLM Chat', Boolean(deps.llm.chat), async () => {
      await deps.requireOk(await deps.providerFetch(deps.llmEndpoint(deps.llm.chat, '/models'), { headers: { Authorization: `Bearer ${deps.llm.chat.token}` } }), 'LLM Chat')
      return 'LIVE'
    }),
    providerState('LLM Embedding', Boolean(deps.llm.embedding), async () => {
      await deps.requireOk(await deps.providerFetch(deps.llmEndpoint(deps.llm.embedding, '/models'), { headers: { Authorization: `Bearer ${deps.llm.embedding.token}` } }), 'LLM Embedding')
      return 'LIVE'
    }),
    providerState('LLM Reranker', Boolean(deps.llm.reranker), async () => {
      const payload = await deps.llmRequest(deps.llm.reranker, '/rerank', {
        model: deps.llm.reranker.model,
        query: 'DataRiver capability probe',
        documents: ['DataRiver capability probe'],
        top_n: 1,
      })
      const results = payload.results || payload.data
      if (!Array.isArray(results)) throw new Error('LLM Reranker returned no ordered results.')
    }),
    providerState('Neo4j', Boolean(deps.neo4j), async () => {
      await deps.neo4jQuery('RETURN 1')
      return 'LIVE'
    }),
  ])
  const grafanaAvailable = Boolean(
    deps.grafanaEmbedEnabled && deps.grafanaUiUrl && deps.grafanaEmbedBaseUrl && deps.grafanaEvidenceReference,
  )
  return {
    items,
    external_system_links: deps.datahubUiUrl ? [{ id: 'datahub', label: 'DataHub', url: deps.datahubUiUrl }] : [],
    grafana_embed: grafanaAvailable
      ? { state: 'AVAILABLE', url: deps.grafanaUiUrl }
      : { state: deps.grafanaUiUrl ? 'DISABLED' : 'NOT_CONFIGURED' },
    monitoring_configuration: { version: 1, items: deps.configuredMonitoringDashboards },
    deployment_tier: 'SINGLE_NODE_PILOT',
  }
}

return { monitoringDashboards, optionalDashboardUrl, providerState, capabilities }
}
