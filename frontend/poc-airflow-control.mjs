import { createHash } from 'node:crypto'

// This is the canonical SystemConfigurationId, not an AF-04 domain System UUID linkage.
export const AIRFLOW_SYSTEM_ID = 'AIRFLOW'
export const AIRFLOW_CONTROL_SCOPE = 'airflow-control-v1'

export const AIRFLOW_DAGS = Object.freeze([
  'datariver_bulk_registration_prepare',
  'datariver_catalog_probe',
  'datariver_catalog_sync',
  'datariver_manual_metadata_apply',
  'datariver_quality_dispatch',
])

export const ALLOWED_AIRFLOW_DAGS = new Set(AIRFLOW_DAGS)

const RECEIPT_LIMIT = 500
const AUDIT_EVENT_LIMIT = 12
const RECEIPT_STATES = new Set(['PENDING', 'RECONCILE_REQUIRED', 'ACCEPTED', 'FAILED'])
const OPERATIONS = new Set(['TRIGGER', 'PAUSE', 'UNPAUSE'])
const RUN_STATES = new Set([
  'DEFERRED', 'FAILED', 'NONE', 'QUEUED', 'REMOVED', 'RESTARTING', 'RUNNING',
  'SCHEDULED', 'SKIPPED', 'SUCCESS', 'UP_FOR_RESCHEDULE', 'UP_FOR_RETRY', 'UPSTREAM_FAILED',
])

function controlError(statusCode, code, message) {
  return Object.assign(new Error(message), { statusCode, code })
}

function sha256(value) {
  return createHash('sha256').update(value, 'utf8').digest('hex')
}

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(',')}}`
  }
  return JSON.stringify(value)
}

function boundedString(value, name, maximum) {
  if (typeof value !== 'string' || !value.trim() || value.length > maximum) {
    throw controlError(400, 'AIRFLOW_CONTROL_INVALID', `${name} is invalid.`)
  }
  return value.trim()
}

function exactKeys(value, allowed, required = allowed) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const keys = Object.keys(value)
  return required.every((key) => keys.includes(key)) && keys.every((key) => allowed.includes(key))
}

function timestamp(value, fieldName) {
  if (value === undefined || value === null || value === '') return null
  if (typeof value !== 'string' || !Number.isFinite(Date.parse(value))) {
    throw controlError(502, 'AIRFLOW_DAG_CONTRACT_INVALID', `Airflow ${fieldName} is invalid.`)
  }
  return new Date(Date.parse(value)).toISOString()
}

function allowedDagId(value) {
  const dagId = boundedString(value, 'dag_id', 200)
  if (!ALLOWED_AIRFLOW_DAGS.has(dagId)) {
    throw controlError(400, 'DAG_NOT_ALLOWED', 'The DAG is not allowlisted for this Product.')
  }
  return dagId
}

function normalizedRunState(value) {
  if (value === undefined || value === null || value === '') return 'NONE'
  if (typeof value !== 'string' || !RUN_STATES.has(value.trim().toUpperCase())) {
    throw controlError(502, 'AIRFLOW_RUN_CONTRACT_INVALID', 'Airflow returned an unsupported run state.')
  }
  return value.trim().toUpperCase()
}

export function normalizeAirflowDagStatus(payload, expectedDagId, version) {
  const dagId = allowedDagId(expectedDagId)
  if (!['v1', 'v2'].includes(version)) {
    throw new TypeError('Airflow DAG status requires an explicit supported API version.')
  }
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)
    || payload.dag_id !== dagId || typeof payload.is_paused !== 'boolean') {
    throw controlError(502, 'AIRFLOW_DAG_CONTRACT_INVALID', 'Airflow returned an incompatible DAG status document.')
  }
  const nextLogicalDate = timestamp(
    version === 'v2' ? payload.next_dagrun_logical_date : payload.next_dagrun,
    'next DAG logical date',
  )
  const nextRunAfter = timestamp(
    version === 'v2' ? payload.next_dagrun_run_after : payload.next_dagrun_create_after,
    'next DAG run-after time',
  )
  return {
    system_id: AIRFLOW_SYSTEM_ID,
    dag_id: dagId,
    state: 'READY',
    paused: payload.is_paused,
    next_logical_date: nextLogicalDate,
    next_run_at: nextRunAfter,
    last_parsed_at: timestamp(payload.last_parsed_time ?? payload.last_parsed, 'last parsed time'),
  }
}

export function normalizeAirflowRun(payload, expectedDagId, expectedRunId = null) {
  const dagId = allowedDagId(expectedDagId)
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    throw controlError(502, 'AIRFLOW_RUN_CONTRACT_INVALID', 'Airflow returned an incompatible run document.')
  }
  const runId = payload.dag_run_id ?? payload.run_id
  if (typeof runId !== 'string' || !runId || runId.length > 250
    || (payload.dag_id !== undefined && payload.dag_id !== dagId)
    || (expectedRunId !== null && runId !== expectedRunId)) {
    throw controlError(502, 'AIRFLOW_RUN_CONTRACT_INVALID', 'Airflow returned a mismatched run identity.')
  }
  return {
    system_id: AIRFLOW_SYSTEM_ID,
    dag_id: dagId,
    run_id: runId,
    state: normalizedRunState(payload.state),
    logical_date: timestamp(payload.logical_date ?? payload.execution_date, 'logical date'),
    started_at: timestamp(payload.start_date ?? payload.start_time, 'run start'),
    ended_at: timestamp(payload.end_date ?? payload.end_time, 'run end'),
  }
}

export function normalizeAirflowLatestRunPage(payload, dagId) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    throw controlError(502, 'AIRFLOW_RUN_CONTRACT_INVALID', 'Airflow returned an incompatible run list.')
  }
  const rows = payload.dag_runs ?? payload.dagRuns
  if (!Array.isArray(rows) || rows.length > 1) {
    throw controlError(502, 'AIRFLOW_RUN_CONTRACT_INVALID', 'Airflow run state exceeded the one-row bound.')
  }
  return rows.length ? normalizeAirflowRun(rows[0], dagId) : null
}

export async function collectAllowedAirflowDagStatuses(version, fetchDag, fetchLatestRun) {
  if (!['v1', 'v2'].includes(version) || typeof fetchDag !== 'function'
    || typeof fetchLatestRun !== 'function') {
    throw new TypeError('Airflow DAG inventory requires supported bounded provider functions.')
  }
  const items = await Promise.all(AIRFLOW_DAGS.map(async (dagId) => {
    const response = await fetchDag(dagId, version)
    if (response.status === 404) {
      return {
        system_id: AIRFLOW_SYSTEM_ID,
        dag_id: dagId,
        state: 'MISSING',
        paused: null,
        next_logical_date: null,
        next_run_at: null,
        last_parsed_at: null,
        latest_run: null,
      }
    }
    if (!response.ok) throw controlError(502, 'AIRFLOW_DAG_READ_FAILED', 'Airflow DAG status is unavailable.')
    const status = normalizeAirflowDagStatus(await response.json(), dagId, version)
    const runResponse = await fetchLatestRun(dagId, version)
    if (!runResponse.ok) throw controlError(502, 'AIRFLOW_RUN_READ_FAILED', 'Airflow run status is unavailable.')
    return { ...status, latest_run: normalizeAirflowLatestRunPage(await runResponse.json(), dagId) }
  }))
  return { system_id: AIRFLOW_SYSTEM_ID, api_mode: version.toUpperCase(), items }
}

function normalizeAuditEvent(value) {
  if (!exactKeys(value, ['event', 'at', 'code'], ['event', 'at'])) {
    throw controlError(503, 'AIRFLOW_RECEIPT_STATE_INVALID', 'Stored Airflow audit state is invalid.')
  }
  const event = boundedString(value.event, 'audit event', 40)
  const at = timestamp(value.at, 'audit timestamp')
  const code = value.code === undefined ? undefined : boundedString(value.code, 'audit code', 80)
  return { event, at, ...(code ? { code } : {}) }
}

function normalizeReceipt(value) {
  const keys = [
    'operation_id', 'idempotency_key_hash', 'request_hash', 'operation', 'system_id',
    'dag_id', 'actor_subject_id', 'provider_run_id', 'target_paused', 'state', 'provider_state',
    'failure_code', 'created_at', 'updated_at', 'audit_events',
  ]
  if (!exactKeys(value, keys, keys)) {
    throw controlError(503, 'AIRFLOW_RECEIPT_STATE_INVALID', 'Stored Airflow receipt is malformed.')
  }
  const hashes = ['operation_id', 'idempotency_key_hash', 'request_hash']
  if (hashes.some((key) => typeof value[key] !== 'string' || !/^[0-9a-f]{64}$/.test(value[key]))
    || !OPERATIONS.has(value.operation) || value.system_id !== AIRFLOW_SYSTEM_ID
    || !RECEIPT_STATES.has(value.state) || !Array.isArray(value.audit_events)
    || value.audit_events.length < 1 || value.audit_events.length > AUDIT_EVENT_LIMIT) {
    throw controlError(503, 'AIRFLOW_RECEIPT_STATE_INVALID', 'Stored Airflow receipt violates its contract.')
  }
  const dagId = allowedDagId(value.dag_id)
  const providerRunId = value.provider_run_id === null
    ? null
    : boundedString(value.provider_run_id, 'provider_run_id', 250)
  const actorSubjectId = boundedString(value.actor_subject_id, 'actor_subject_id', 255)
  const providerState = value.provider_state === null ? null : normalizedRunState(value.provider_state)
  const failureCode = value.failure_code === null
    ? null
    : boundedString(value.failure_code, 'failure_code', 80)
  const expectedPaused = value.operation === 'PAUSE'
    ? true
    : value.operation === 'UNPAUSE' ? false : null
  if ((value.operation === 'TRIGGER' && (providerRunId === null || value.target_paused !== null))
    || (value.operation !== 'TRIGGER'
      && (providerRunId !== null || value.target_paused !== expectedPaused))) {
    throw controlError(503, 'AIRFLOW_RECEIPT_STATE_INVALID', 'Stored Airflow receipt target is invalid.')
  }
  return {
    ...value,
    dag_id: dagId,
    provider_run_id: providerRunId,
    target_paused: expectedPaused,
    actor_subject_id: actorSubjectId,
    provider_state: providerState,
    failure_code: failureCode,
    created_at: timestamp(value.created_at, 'receipt creation'),
    updated_at: timestamp(value.updated_at, 'receipt update'),
    audit_events: value.audit_events.map(normalizeAuditEvent),
  }
}

function normalizeDocument(value) {
  if (value === null) return { schema_version: 1, receipts: [] }
  if (!exactKeys(value, ['schema_version', 'receipts']) || value.schema_version !== 1
    || !Array.isArray(value.receipts) || value.receipts.length > RECEIPT_LIMIT) {
    throw controlError(503, 'AIRFLOW_RECEIPT_STATE_INVALID', 'Stored Airflow control state is invalid.')
  }
  const receipts = value.receipts.map(normalizeReceipt)
  if (new Set(receipts.map((item) => item.operation_id)).size !== receipts.length) {
    throw controlError(503, 'AIRFLOW_RECEIPT_STATE_INVALID', 'Stored Airflow receipts contain duplicate identities.')
  }
  return { schema_version: 1, receipts }
}

function receiptProjection(receipt) {
  return {
    operation_id: receipt.operation_id,
    operation: receipt.operation,
    system_id: receipt.system_id,
    dag_id: receipt.dag_id,
    run_id: receipt.provider_run_id,
    target_paused: receipt.target_paused,
    state: receipt.state,
    provider_state: receipt.provider_state,
    failure_code: receipt.failure_code,
    created_at: receipt.created_at,
    updated_at: receipt.updated_at,
    audit_events: receipt.audit_events,
  }
}

function idempotencyKey(value) {
  const key = boundedString(value, 'Idempotency-Key', 200)
  if (key.length < 16 || [...key].some((character) => {
    const code = character.codePointAt(0)
    return code < 0x21 || code > 0x7e
  })) {
    throw controlError(400, 'AIRFLOW_IDEMPOTENCY_KEY_INVALID', 'Idempotency-Key must contain 16-200 visible ASCII characters.')
  }
  return key
}

function receiptIdentity(subjectId, key) {
  return sha256(canonicalJson({ subject_id: subjectId, idempotency_key: key }))
}

function providerRunIdentity(operationId) {
  return `datariver__${operationId.slice(0, 48)}`
}

export function createAirflowControlStore(stateStore, { now = () => new Date().toISOString() } = {}) {
  if (!stateStore || typeof stateStore.read !== 'function' || typeof stateStore.writeIfVersion !== 'function') {
    throw new TypeError('Airflow control requires the Product state store CAS contract.')
  }

  async function mutate(operationId, action) {
    for (let attempt = 0; attempt < 8; attempt += 1) {
      const snapshot = await stateStore.read(AIRFLOW_CONTROL_SCOPE)
      const document = normalizeDocument(snapshot.value)
      const index = document.receipts.findIndex((item) => item.operation_id === operationId)
      const next = action(document, index)
      if (!next.write) return next.result
      try {
        await stateStore.writeIfVersion(AIRFLOW_CONTROL_SCOPE, next.document, snapshot.version)
        return next.result
      } catch (error) {
        if (error?.code !== 'STATE_VERSION_STALE') throw error
      }
    }
    throw controlError(503, 'AIRFLOW_RECEIPT_CONTENTION', 'Airflow receipt state is temporarily contended.')
  }

  async function claimOperation({
    subjectId: subjectIdValue,
    dagId: dagIdValue,
    idempotencyKey: keyValue,
    operation: operationValue,
  }) {
    const subjectId = boundedString(subjectIdValue, 'subject_id', 255)
    const dagId = allowedDagId(dagIdValue)
    const key = idempotencyKey(keyValue)
    if (!OPERATIONS.has(operationValue)) {
      throw controlError(400, 'AIRFLOW_OPERATION_INVALID', 'The Airflow operation is invalid.')
    }
    const operation = operationValue
    const targetPaused = operation === 'PAUSE' ? true : operation === 'UNPAUSE' ? false : null
    const operationId = receiptIdentity(subjectId, key)
    const keyHash = sha256(key)
    const requestHash = sha256(canonicalJson({
      operation,
      system_id: AIRFLOW_SYSTEM_ID,
      dag_id: dagId,
      target_paused: targetPaused,
    }))
    return mutate(operationId, (document, index) => {
      if (index >= 0) {
        const receipt = document.receipts[index]
        if (receipt.idempotency_key_hash !== keyHash || receipt.request_hash !== requestHash
          || receipt.actor_subject_id !== subjectId || receipt.dag_id !== dagId) {
          throw controlError(409, 'AIRFLOW_IDEMPOTENCY_CONFLICT', 'Idempotency-Key is already bound to another Airflow operation.')
        }
        return {
          write: false,
          result: {
            action: ['ACCEPTED', 'FAILED'].includes(receipt.state) ? 'REPLAY' : 'RECONCILE',
            receipt: receiptProjection(receipt),
          },
        }
      }
      if (document.receipts.length >= RECEIPT_LIMIT) {
        throw controlError(503, 'AIRFLOW_RECEIPT_CAPACITY_REACHED', 'Airflow receipt capacity requires operator retention handling.')
      }
      const at = new Date(Date.parse(now())).toISOString()
      const receipt = {
        operation_id: operationId,
        idempotency_key_hash: keyHash,
        request_hash: requestHash,
        operation,
        system_id: AIRFLOW_SYSTEM_ID,
        dag_id: dagId,
        actor_subject_id: subjectId,
        provider_run_id: operation === 'TRIGGER' ? providerRunIdentity(operationId) : null,
        target_paused: targetPaused,
        state: 'PENDING',
        provider_state: null,
        failure_code: null,
        created_at: at,
        updated_at: at,
        audit_events: [{ event: 'REQUEST_ACCEPTED', at }],
      }
      return {
        write: true,
        document: { schema_version: 1, receipts: [...document.receipts, receipt] },
        result: {
          action: operation === 'TRIGGER' ? 'TRIGGER' : 'TRANSITION',
          receipt: receiptProjection(receipt),
        },
      }
    })
  }

  async function transition(operationIdValue, state, event, { providerState = null, failureCode = null } = {}) {
    const operationId = boundedString(operationIdValue, 'operation_id', 64)
    return mutate(operationId, (document, index) => {
      if (index < 0) throw controlError(404, 'AIRFLOW_RECEIPT_NOT_FOUND', 'The Airflow receipt was not found.')
      const current = document.receipts[index]
      if (['ACCEPTED', 'FAILED'].includes(current.state)) return { write: false, result: receiptProjection(current) }
      const at = new Date(Date.parse(now())).toISOString()
      const next = {
        ...current,
        state,
        provider_state: providerState,
        failure_code: failureCode,
        updated_at: at,
        audit_events: [...current.audit_events, {
          event,
          at,
          ...(failureCode ? { code: failureCode } : {}),
        }].slice(-AUDIT_EVENT_LIMIT),
      }
      const receipts = [...document.receipts]
      receipts[index] = next
      return {
        write: true,
        document: { schema_version: 1, receipts },
        result: receiptProjection(next),
      }
    })
  }

  return Object.freeze({
    claimTrigger(command) {
      return claimOperation({ ...command, operation: 'TRIGGER' })
    },
    claimDagTransition(command) {
      return claimOperation(command)
    },
    acceptTrigger(operationId, providerState) {
      return transition(operationId, 'ACCEPTED', 'PROVIDER_ACCEPTED', {
        providerState: normalizedRunState(providerState),
      })
    },
    requireReconciliation(operationId, failureCode) {
      return transition(operationId, 'RECONCILE_REQUIRED', 'PROVIDER_OUTCOME_UNKNOWN', {
        failureCode: boundedString(failureCode, 'failure_code', 80),
      })
    },
    failTrigger(operationId, failureCode) {
      return transition(operationId, 'FAILED', 'PROVIDER_REJECTED', {
        failureCode: boundedString(failureCode, 'failure_code', 80),
      })
    },
    acceptDagTransition(operationId) {
      return transition(operationId, 'ACCEPTED', 'PROVIDER_ACCEPTED')
    },
    requireDagTransitionReconciliation(operationId, failureCode) {
      return transition(operationId, 'RECONCILE_REQUIRED', 'PROVIDER_OUTCOME_UNKNOWN', {
        failureCode: boundedString(failureCode, 'failure_code', 80),
      })
    },
    failDagTransition(operationId, failureCode) {
      return transition(operationId, 'FAILED', 'PROVIDER_REJECTED', {
        failureCode: boundedString(failureCode, 'failure_code', 80),
      })
    },
    async listReceipts(limit = 50) {
      if (!Number.isSafeInteger(limit) || limit < 1 || limit > 100) {
        throw controlError(400, 'AIRFLOW_RECEIPT_LIMIT_INVALID', 'Airflow receipt limit must be between 1 and 100.')
      }
      const snapshot = await stateStore.read(AIRFLOW_CONTROL_SCOPE)
      const document = normalizeDocument(snapshot.value)
      return document.receipts
        .slice()
        .sort((left, right) => right.created_at.localeCompare(left.created_at)
          || right.operation_id.localeCompare(left.operation_id))
        .slice(0, limit)
        .map(receiptProjection)
    },
  })
}
