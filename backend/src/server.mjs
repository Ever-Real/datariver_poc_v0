
// Dependencies are supplied by bootstrap; this module never constructs a shared client.
export function createServerModule(deps) {
function createPocServer({
  stateStore,
  authenticator = deps.unconfiguredPocAuthenticator(),
  airflowProvider,
  airflowServiceToken = deps.process.env.POC_AIRFLOW_SERVICE_TOKEN || '',
  mcpServiceToken = deps.process.env.POC_MCP_SERVICE_TOKEN || '',
  mcpSubjectId = deps.process.env.POC_MCP_SUBJECT_ID || '',
  mcpWorkspaceId = deps.process.env.POC_MCP_WORKSPACE_ID || '',
  mcpMetadataSearch = deps.datahubChatEvidence,
  mcpKnowledgeChatScope = deps.knowledgeChatScope,
  mcpKnowledgeChatSnapshot = deps.knowledgeChatSnapshot,
  mcpKnowledgeGraphRag = deps.knowledgeGraphRag,
  mcpUserTimeoutMs = 60_000,
  currentDatahubInventory: currentDatahubInventoryProvider = deps.currentDatahubInventory,
  currentDatahubTables: currentDatahubTablesProvider = deps.currentDatahubTables,
  catalogExportStore = deps.createPocCatalogExportStore(),
  k9SchedulerConfig = null,
  k9SchedulerStatus = null,
} = {}) {
  if (!Number.isSafeInteger(mcpUserTimeoutMs) || mcpUserTimeoutMs < 1 || mcpUserTimeoutMs > 60_000) {
    throw new Error('MCP user timeout must be between 1 and 60,000 ms.')
  }
  if (stateStore) deps.pocStateStore = stateStore
  const baseContext = {
    stateStore: stateStore ?? deps.pocStateStore,
    airflowProvider: airflowProvider ?? deps.defaultAirflowControlProvider(),
    currentDatahubInventory: currentDatahubInventoryProvider,
    currentDatahubTables: currentDatahubTablesProvider,
    catalogExportStore,
    k9SchedulerConfig,
    k9SchedulerStatus,
  }
  return deps.createServer(async (request, response) => {
    try {
      const url = new deps.URL(request.url || '/', 'http://poc.invalid')
      if (url.pathname === '/healthz') {
        if (!['GET', 'HEAD'].includes(request.method || '')) {
          return deps.problem(response, 405, 'METHOD_NOT_ALLOWED', 'Liveness supports only GET and HEAD.')
        }
        response.writeHead(200, { 'Content-Type': 'text/plain; charset=utf-8', ...deps.securityHeaders() })
        return response.end(request.method === 'HEAD' ? undefined : 'ok\n')
      }
      if (url.pathname === '/poc-runtime-config.js') {
        if (!['GET', 'HEAD'].includes(request.method || '')) {
          return deps.problem(response, 405, 'METHOD_NOT_ALLOWED', 'Runtime configuration supports only GET and HEAD.')
        }
        const body = `globalThis.__DATARIVER_POC_RUNTIME__=${JSON.stringify(deps.runtimeFlags)};\n`
        response.writeHead(200, { 'Cache-Control': 'no-store', 'Content-Type': 'text/javascript; charset=utf-8', ...deps.securityHeaders() })
        return response.end(request.method === 'HEAD' ? undefined : body)
      }
      if (url.pathname === '/auth/login' && ['GET', 'HEAD'].includes(request.method || '')) {
        if (deps.redirectBrowserToCanonicalOrigin(request, response, url, authenticator)) return
        return deps.serveStatic(request, response, url)
      }
      if (url.pathname === '/auth' || url.pathname.startsWith('/auth/')) {
        return await deps.authRoute(request, response, url, baseContext, authenticator)
      }
      if (url.pathname === '/api/v1/site-branding' && request.method === 'GET') {
        deps.assertPocRouteAuthorization(deps.resolvePocRoute(request.method, url.pathname))
        deps.rejectProtectedAccessClaims(request, url)
        return await deps.siteBrandingApi(request, response, baseContext)
      }
      if (url.pathname === '/api/v1/registration/bulk-preparations/execute') {
        deps.assertPocRouteAuthorization(deps.resolvePocRoute(request.method, url.pathname))
        deps.exactServiceToken(request, airflowServiceToken)
        return await deps.api(request, response, url, baseContext)
      }
      if (url.pathname === '/api/v1/mcp') {
        return await deps.mcpHandler(request, response, url, baseContext, mcpServiceToken, mcpSubjectId, mcpWorkspaceId, mcpMetadataSearch, mcpKnowledgeChatScope, mcpKnowledgeChatSnapshot, mcpKnowledgeGraphRag)
      }
      if (url.pathname === '/api/v1/mcp/user') {
        return await deps.mcpHandler(
          request, response, url, baseContext, mcpServiceToken, mcpSubjectId, mcpWorkspaceId,
          mcpMetadataSearch, mcpKnowledgeChatScope, mcpKnowledgeChatSnapshot, mcpKnowledgeGraphRag,
          { authenticator, userAuthenticated: true, timeoutMs: mcpUserTimeoutMs },
        )
      }
      if (url.pathname === '/poc-api' || url.pathname.startsWith('/poc-api/')
        || url.pathname === '/api/v1' || url.pathname.startsWith('/api/v1/')) {
        const authentication = await authenticator.authenticate(request)
        const requestContext = await deps.authenticatedRequestContext(baseContext, authentication)
        deps.assertPocRouteAuthorization(deps.resolvePocRoute(request.method, url.pathname), requestContext.principal)
        deps.rejectProtectedAccessClaims(request, url, {
          allowSystemFilter: url.pathname.startsWith('/api/v1/change-history/')
            || url.pathname === '/api/v1/admin/table-system-mappings'
            || /^\/api\/v1\/admin\/users\/[^/]+\/table-grants$/.test(url.pathname),
        })
        if (deps.stateChangingMethods.has(request.method || '')) authenticator.assertOrigin(request)
        return await deps.api(request, response, url, requestContext)
      }
      if (!['GET', 'HEAD'].includes(request.method || '')) return deps.problem(response, 405, 'METHOD_NOT_ALLOWED', 'Only static GET/HEAD is supported.')
      if (deps.redirectBrowserToCanonicalOrigin(request, response, url, authenticator)) return
      return deps.serveStatic(request, response, url)
    } catch (error) {
      if (response.headersSent) return response.end()
      const status = Number(error?.statusCode) || (error instanceof SyntaxError ? 400 : 502)
      const code = error?.statusCode && typeof error?.code === 'string' ? error.code : 'POC_PROVIDER_ERROR'
      return deps.problem(
        response,
        status,
        code,
        error instanceof Error ? error.message : 'Provider request failed.',
        error?.diagnostic || error?.inventoryDiagnostic,
      )
    }
  })
}

return { createPocServer }
}
