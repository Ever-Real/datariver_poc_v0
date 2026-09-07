/* global Buffer */
// Dependencies are supplied by bootstrap; this module never constructs a shared client.
export function createInfrastructureAirflow(deps) {
function basicAuthorization(provider) {
  return `Basic ${Buffer.from(`${provider.username}:${provider.password}`).toString('base64')}`
}

function airflowNotConfigured() {
  return Object.assign(new Error('Airflow is not configured.'), {
    statusCode: 503,
    code: 'AIRFLOW_NOT_CONFIGURED',
  })
}

async function airflowV2Token(forceRefresh = false) {
  if (!deps.airflow) throw airflowNotConfigured()
  if (!forceRefresh && deps.airflowAccessToken && deps.airflowAccessTokenExpiresAt > Date.now()) return deps.airflowAccessToken
  const response = await deps.providerFetch(deps.joinProviderUrl(deps.airflow.url, '/auth/token'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: deps.airflow.username, password: deps.airflow.password }),
  })
  await deps.requireOk(response, 'Airflow v2 token')
  const payload = await response.json()
  if (typeof payload.access_token !== 'string' || !payload.access_token.trim()) {
    throw Object.assign(new Error('Airflow v2 returned no access token.'), { statusCode: 502 })
  }
  deps.airflowAccessToken = payload.access_token.trim()
  deps.airflowAccessTokenExpiresAt = Date.now() + 5 * 60 * 1000
  return deps.airflowAccessToken
}

async function airflowFetch(path, options = {}, version = deps.airflowApiVersion) {
  if (!deps.airflow) throw airflowNotConfigured()
  const authorization = version === 'v2'
    ? `Bearer ${await airflowV2Token()}`
    : basicAuthorization(deps.airflow)
  let response = await deps.providerFetch(deps.joinProviderUrl(deps.airflow.url, path), {
    ...options,
    headers: {
      Authorization: authorization,
      'Content-Type': 'application/json',
      ...options.headers,
    },
  })
  if (version === 'v2' && response.status === 401) {
    const refreshed = await airflowV2Token(true)
    response = await deps.providerFetch(deps.joinProviderUrl(deps.airflow.url, path), {
      ...options,
      headers: {
        Authorization: `Bearer ${refreshed}`,
        'Content-Type': 'application/json',
        ...options.headers,
      },
    })
  }
  return response
}

async function detectAirflowApiVersion() {
  if (deps.airflowApiVersion) return deps.airflowApiVersion
  if (!deps.airflow) throw airflowNotConfigured()
  const probes = [
    { version: 'v2', path: '/api/v2/dags?limit=1' },
    { version: 'v1', path: '/api/v1/dags?limit=1' },
  ]
  const statuses = []
  for (const probe of probes) {
    try {
      const response = await airflowFetch(probe.path, {}, probe.version)
      statuses.push(`${probe.version}:${response.status}`)
      if (response.ok) {
        deps.airflowApiVersion = probe.version
        return deps.airflowApiVersion
      }
    } catch (error) {
      statuses.push(`${probe.version}:${error instanceof Error ? error.name : 'NETWORK_ERROR'}`)
    }
  }
  throw Object.assign(
    new Error(`Airflow REST API probe failed (${statuses.join(', ')}).`),
    { detailCode: 'AIRFLOW_REST_API_PROBE_FAILED' },
  )
}

async function airflowDagInventory() {
  const version = await detectAirflowApiVersion()
  const inventory = await deps.collectAllowedAirflowDagStatuses(version, (dagId, selectedVersion) => airflowFetch(
    `/api/${selectedVersion}/dags/${encodeURIComponent(dagId)}`,
    {},
    selectedVersion,
  ), (dagId, selectedVersion) => airflowFetch(
    `/api/${selectedVersion}/dags/${encodeURIComponent(dagId)}/dagRuns?limit=1&order_by=${selectedVersion === 'v1' ? '-execution_date' : '-logical_date'}`,
    {},
    selectedVersion,
  ))
  const observedAt = new Date().toISOString()
  return {
    ...inventory,
    connection: deps.projectAirflowConnectionStatus({
      endpoint: deps.airflow.url,
      apiVersion: version,
      credentialConfigured: Boolean(deps.airflow.username && deps.airflow.password),
      requestTimeoutMs: deps.providerTimeoutMs,
      checkedAt: observedAt,
    }),
    observed_at: observedAt,
  }
}

async function triggerControlledAirflowDag(dagId, runId) {
  const version = await detectAirflowApiVersion()
  const payload = version === 'v2'
    ? { dag_run_id: runId, logical_date: null, conf: {} }
    : { dag_run_id: runId, conf: {} }
  let response
  try {
    response = await airflowFetch(
      `/api/${version}/dags/${encodeURIComponent(dagId)}/dagRuns`,
      { method: 'POST', body: JSON.stringify(payload) },
    )
  } catch (error) {
    throw Object.assign(new Error('Airflow trigger transport outcome is unknown.'), {
      statusCode: 502,
      code: 'AIRFLOW_TRIGGER_OUTCOME_UNKNOWN',
      outcomeUnknown: true,
      cause: error,
    })
  }
  if (response.ok) {
    try {
      return deps.normalizeAirflowRun(await response.json(), dagId, runId)
    } catch (error) {
      throw Object.assign(new Error('Airflow accepted the trigger but its response could not be verified.'), {
        statusCode: 502,
        code: 'AIRFLOW_TRIGGER_OUTCOME_UNKNOWN',
        outcomeUnknown: true,
        cause: error,
      })
    }
  }
  if (response.status === 409) {
    const reconciled = await readAirflowDagRun(dagId, runId, version)
    if (reconciled) return reconciled
  }
  const outcomeUnknown = response.status >= 500 || response.status === 409
  throw Object.assign(new Error('Airflow trigger failed.'), {
    statusCode: 502,
    code: outcomeUnknown ? 'AIRFLOW_TRIGGER_OUTCOME_UNKNOWN' : 'AIRFLOW_TRIGGER_REJECTED',
    outcomeUnknown,
  })
}

function isAirflowTriggerOutcomeUnknown(error) {
  return error?.outcomeUnknown === true
    || ['AbortError', 'TimeoutError', 'SyntaxError', 'TypeError'].includes(error?.name)
    || error?.code === 'AIRFLOW_RUN_CONTRACT_INVALID'
}

function isAirflowDagTransitionOutcomeUnknown(error) {
  return error?.outcomeUnknown === true
    || ['AbortError', 'TimeoutError', 'SyntaxError', 'TypeError'].includes(error?.name)
    || error?.code === 'AIRFLOW_DAG_CONTRACT_INVALID'
}

async function bestEffortAirflowReceiptWrite(write) {
  try {
    return await write()
  } catch {
    return null
  }
}

async function triggerAirflowDag(dagId, body) {
  const version = await detectAirflowApiVersion()
  const payload = version === 'v2' ? { logical_date: null, ...body } : body
  const response = await airflowFetch(
    `/api/${version}/dags/${encodeURIComponent(dagId)}/dagRuns`,
    { method: 'POST', body: JSON.stringify(payload) },
  )
  await deps.requireOk(response, `Airflow ${version}`)
  return response
}

async function readAirflowDagRun(dagId, runId, selectedVersion = undefined) {
  const version = selectedVersion ?? await detectAirflowApiVersion()
  const response = await airflowFetch(
    `/api/${version}/dags/${encodeURIComponent(dagId)}/dagRuns/${encodeURIComponent(runId)}`,
    {},
    version,
  )
  if (response.status === 404) return null
  if (!response.ok) {
    throw Object.assign(new Error('Airflow run reconciliation failed.'), {
      statusCode: 502,
      code: 'AIRFLOW_RUN_RECONCILIATION_FAILED',
      outcomeUnknown: true,
    })
  }
  return deps.normalizeAirflowRun(await response.json(), dagId, runId)
}

async function setAirflowDagPaused(dagId, paused) {
  const version = await detectAirflowApiVersion()
  const currentResponse = await airflowFetch(
    `/api/${version}/dags/${encodeURIComponent(dagId)}`,
    {},
    version,
  )
  if (currentResponse.status === 404) {
    throw Object.assign(new Error('The allowlisted Airflow DAG is missing.'), {
      statusCode: 409,
      code: 'AIRFLOW_DAG_MISSING',
    })
  }
  if (!currentResponse.ok) {
    throw Object.assign(new Error('Airflow DAG status read failed.'), {
      statusCode: 502,
      code: 'AIRFLOW_DAG_READ_FAILED',
    })
  }
  const current = deps.normalizeAirflowDagStatus(await currentResponse.json(), dagId, version)
  if (current.paused === paused) return current
  let response
  try {
    response = await airflowFetch(
      `/api/${version}/dags/${encodeURIComponent(dagId)}`,
      { method: 'PATCH', body: JSON.stringify({ is_paused: paused }) },
      version,
    )
  } catch (error) {
    throw Object.assign(new Error('Airflow DAG transition outcome is unknown.'), {
      statusCode: 502,
      code: 'AIRFLOW_DAG_TRANSITION_OUTCOME_UNKNOWN',
      outcomeUnknown: true,
      cause: error,
    })
  }
  if (!response.ok) {
    const outcomeUnknown = response.status >= 500
    throw Object.assign(new Error('Airflow DAG transition failed.'), {
      statusCode: 502,
      code: outcomeUnknown
        ? 'AIRFLOW_DAG_TRANSITION_OUTCOME_UNKNOWN'
        : 'AIRFLOW_DAG_TRANSITION_REJECTED',
      outcomeUnknown,
    })
  }
  let transitioned
  try {
    transitioned = deps.normalizeAirflowDagStatus(await response.json(), dagId, version)
  } catch (error) {
    throw Object.assign(new Error('Airflow accepted the DAG transition but its response could not be verified.'), {
      statusCode: 502,
      code: 'AIRFLOW_DAG_TRANSITION_OUTCOME_UNKNOWN',
      outcomeUnknown: true,
      cause: error,
    })
  }
  if (transitioned.paused !== paused) {
    throw Object.assign(new Error('Airflow did not apply the requested pause transition.'), {
      statusCode: 502,
      code: 'AIRFLOW_DAG_TRANSITION_OUTCOME_UNKNOWN',
      outcomeUnknown: true,
    })
  }
  return transitioned
}

return { basicAuthorization, airflowNotConfigured, airflowV2Token, airflowFetch, detectAirflowApiVersion, airflowDagInventory, triggerControlledAirflowDag, isAirflowTriggerOutcomeUnknown, isAirflowDagTransitionOutcomeUnknown, bestEffortAirflowReceiptWrite, triggerAirflowDag, readAirflowDagRun, setAirflowDagPaused }
}
