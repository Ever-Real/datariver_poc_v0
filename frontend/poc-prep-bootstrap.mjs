import { createHash, randomBytes } from 'node:crypto'
import process from 'node:process'
import { fileURLToPath } from 'node:url'
import { resolve } from 'node:path'

import {
  bootstrapLocalHumanAccount,
  readBootstrapPasswordFile,
} from './poc-bootstrap-local-user.mjs'
import { changeHistoryDocumentFromSnapshot } from './poc-access-document.mjs'
import { normalizePocUsername } from './poc-local-auth.mjs'
import { createPocStateStore } from './poc-state-store.mjs'
import { computeK9PolicyHash, K9_POLICIES } from './poc-k9-managed-graphs.mjs'

function prepError(code, message) {
  return Object.assign(new Error(message), { code })
}

function required(value, name) {
  const normalized = typeof value === 'string' ? value.trim() : ''
  if (!normalized) throw prepError('PREP_IDENTITY_CONFIG_MISSING', `${name} is required.`)
  return normalized
}

function serviceSpecification(environment) {
  const mcpWorkspaceId = required(environment.POC_MCP_WORKSPACE_ID, 'POC_MCP_WORKSPACE_ID')
  const mcpSubjectId = required(environment.POC_MCP_SUBJECT_ID, 'POC_MCP_SUBJECT_ID')
  if (!required(environment.POC_MCP_SERVICE_TOKEN, 'POC_MCP_SERVICE_TOKEN')) {
    throw prepError('PREP_MCP_TOKEN_MISSING', 'MCP service authentication is not configured.')
  }
  const k9Enabled = environment.POC_K9_SCHEDULER_ENABLED?.trim().toLowerCase() === 'true'
  const services = [{
    name: 'MCP',
    subjectId: mcpSubjectId,
    username: 'prep39083-mcp-service',
    role: 'developer',
  }]
  if (k9Enabled) {
    const workspaceId = required(environment.POC_K9_WORKSPACE_ID, 'POC_K9_WORKSPACE_ID')
    const k9SubjectId = required(environment.POC_K9_SYSTEM_SUBJECT_ID, 'POC_K9_SYSTEM_SUBJECT_ID')
    required(environment.POC_K9_STUDIO_DATABASE_URL, 'POC_K9_STUDIO_DATABASE_URL')
    if (workspaceId !== mcpWorkspaceId) {
      throw prepError('PREP_WORKSPACE_DRIFT', 'K9 and MCP must use the same canonical PREP Workspace.')
    }
    if (k9SubjectId === mcpSubjectId) {
      throw prepError('PREP_SERVICE_SUBJECT_COLLISION', 'K9 and MCP Subjects must remain distinct.')
    }
    services.unshift({
      name: 'K9',
      subjectId: k9SubjectId,
      username: 'prep39083-k9-system',
      role: 'manager',
    })
  }
  return Object.freeze({
    workspaceId: mcpWorkspaceId,
    k9Mode: k9Enabled ? 'REQUIRED' : 'DEFERRED',
    services: Object.freeze(services.map((service) => Object.freeze(service))),
  })
}
function usersFromSnapshot(snapshot) {
  return snapshot.access.value === null
    ? []
    : changeHistoryDocumentFromSnapshot(snapshot).users
}

function credentialFor(credentials, subjectId) {
  return credentials.find((credential) => credential.subjectId === subjectId)
}

function verifyService(users, credentials, specification) {
  const usersBySubject = users.filter((user) => user.subject_id === specification.subjectId)
  const credentialsBySubject = credentials.filter(
    (credential) => credential.subjectId === specification.subjectId,
  )
  const credentialsByUsername = credentials.filter(
    (credential) => credential.usernameNormalized === specification.username,
  )
  if (usersBySubject.length === 0 && credentialsBySubject.length === 0
    && credentialsByUsername.length === 0) {
    return Object.freeze({ status: 'ABSENT', name: specification.name })
  }
  if (usersBySubject.length !== 1 || credentialsBySubject.length !== 1
    || credentialsByUsername.length !== 1
    || credentialsBySubject[0] !== credentialsByUsername[0]) {
    throw prepError(
      'PREP_SERVICE_IDENTITY_DRIFT',
      `${specification.name} service identity is incomplete or duplicated.`,
    )
  }
  const user = usersBySubject[0]
  const credential = credentialsBySubject[0]
  if (user.username !== specification.username || user.role !== specification.role || !user.active
    || user.max_security_grade !== 'normal' || !credential.loginEnabled
    || credential.mustChangePassword || credential.activeSessionCount !== 0) {
    throw prepError(
      'PREP_SERVICE_IDENTITY_DRIFT',
      `${specification.name} service identity differs from its canonical target-local contract.`,
    )
  }
  return Object.freeze({
    status: 'PRESENT',
    name: specification.name,
    subject_id: specification.subjectId,
    username: specification.username,
    role: specification.role,
  })
}

export async function inspectPrepBootstrap({ stateStore, environment = process.env }) {
  const specification = serviceSpecification(environment)
  const [snapshot, credentials] = await Promise.all([
    stateStore.readChangeHistoryAccess(),
    stateStore.listLocalCredentialAdministration(),
  ])
  const users = usersFromSnapshot(snapshot)
  const administratorRecords = users.filter((user) => user.role === 'admin')
  const administrators = administratorRecords.flatMap((user) => {
    const credential = credentialFor(credentials, user.subject_id)
    return user.active && credential?.loginEnabled && !credential.mustChangePassword
      ? [{ subject_id: user.subject_id, username: credential.usernameNormalized }]
      : []
  })
  if (administratorRecords.length > 0 && administrators.length === 0) {
    throw prepError(
      'PREP_ADMIN_IDENTITY_DRIFT',
      'Administrator records exist but none is an enabled canonical local administrator.',
    )
  }
  return Object.freeze({
    status: 'READY',
    workspace_id: specification.workspaceId,
    k9_mode: specification.k9Mode,
    administrators,
    administrator_record_count: administratorRecords.length,
    user_record_count: users.length,
    services: specification.services.map((service) => verifyService(users, credentials, service)),
  })
}

export async function inspectPrepOwnedPartial({ stateStore, environment = process.env }) {
  const inspected = await inspectPrepBootstrap({ stateStore, environment })
  const [footprint, accessSnapshot] = await Promise.all([
    stateStore.inspectPrepDeploymentFootprint(),
    stateStore.readChangeHistoryAccess(),
  ])
  const accessDocument = changeHistoryDocumentFromSnapshot(accessSnapshot)
  const core = accessSnapshot.core.value
  const allowedCoreKeys = new Set([
    'adminMemberships', 'adminSystems', 'adminSystemSchemaScopes', 'adminSystemAssignees',
  ])
  if (accessDocument.systems.length !== 0 || accessDocument.system_schema_scopes.length !== 0
    || accessDocument.system_assignments.length !== 0
    || !core || typeof core !== 'object' || Array.isArray(core)
    || Object.keys(core).some((key) => !allowedCoreKeys.has(key))) {
    throw prepError(
      'PREP_LEGACY_PARTIAL_BUSINESS_STATE_PRESENT',
      'The legacy partial deployment access/core state exceeds its exact bootstrap projection.',
    )
  }
  const expectedIdentityCount = 1 + inspected.services.length
  if (inspected.administrator_record_count !== 1 || inspected.administrators.length !== 1
    || inspected.user_record_count !== expectedIdentityCount
    || inspected.services.some((service) => service.status !== 'PRESENT')
    || footprint.table_counts.poc_local_credentials !== expectedIdentityCount
    || footprint.active_session_count !== 0) {
    throw prepError(
      'PREP_LEGACY_PARTIAL_IDENTITY_DRIFT',
      'The legacy partial deployment is not limited to its canonical administrator/service identities.',
    )
  }
  const allowedRowTables = new Set([
    'poc_state',
    'poc_catalog_embedding',
    'poc_local_credentials',
    'poc_local_sessions',
    'poc_k9_managed_graph_policies',
    'poc_k9_refresh_runs',
  ])
  const unexpectedRows = Object.entries(footprint.table_counts).filter(
    ([table, count]) => !allowedRowTables.has(table) && count !== 0,
  )
  const unexpectedScopes = footprint.state_scopes.filter((scope) => (
    !['core', 'change-history-access-v1'].includes(scope)
    && !scope.startsWith('catalog-embedding-')
    && scope !== 'k9-scheduler-v1:datariver:poc:k9-scheduler:v1'
  ))
  if (unexpectedRows.length || unexpectedScopes.length) {
    throw prepError(
      'PREP_LEGACY_PARTIAL_BUSINESS_STATE_PRESENT',
      'The legacy partial deployment contains state outside its exact bootstrap/runtime footprint.',
    )
  }
  const policies = await stateStore.listK9ManagedGraphAssets()
  const expectedPolicies = inspected.k9_mode === 'REQUIRED'
    ? Object.values(K9_POLICIES).map((base) => {
        const policy = {
          ...base,
          subject_id: required(environment.POC_K9_SYSTEM_SUBJECT_ID, 'POC_K9_SYSTEM_SUBJECT_ID'),
          workspace_id: required(environment.POC_K9_WORKSPACE_ID, 'POC_K9_WORKSPACE_ID'),
        }
        return { ...policy, policy_hash: computeK9PolicyHash(policy) }
      })
    : []
  const policyFields = [
    'graph_id', 'name', 'status', 'classification', 'ontology_version_id', 'studio_release_id',
    'publication_version', 'schedule', 'managed_intent', 'accepted_proposal_id', 'subject_id',
    'workspace_id', 'policy_hash', 'tbox_hash', 'contract_hash', 'proposal_hash', 'source_hash',
    'mapping_hash',
  ]
  if (policies.length !== expectedPolicies.length || policies.some((policy) => {
    const expected = expectedPolicies.find((item) => item.graph_id === policy.graph_id)
    return !expected || policyFields.some((field) => policy[field] !== expected[field])
  })) {
    throw prepError(
      'PREP_LEGACY_PARTIAL_K9_DRIFT',
      'The legacy partial deployment K9 state differs from its canonical bootstrap footprint.',
    )
  }
  const expectedByGraph = new Map(expectedPolicies.map((policy) => [policy.graph_id, policy]))
  const allowedNamespaces = new Set()
  const unexpectedRun = footprint.k9_runs.find((run) => {
    const policy = expectedByGraph.get(run.graph_id)
    if (run.active_release_pointer) allowedNamespaces.add(run.active_release_pointer)
    return !policy || run.policy_hash !== policy.policy_hash
      || !['PREPARING', 'RUN', 'NO_OP', 'FAILED'].includes(run.status)
      || (run.active_release_pointer !== null
        && !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$/u.test(run.active_release_pointer))
  })
  for (const policy of policies) {
    if (policy.active_release_pointer && !allowedNamespaces.has(policy.active_release_pointer)) {
      throw prepError(
        'PREP_LEGACY_PARTIAL_K9_RUN_DRIFT',
        'The legacy partial deployment has a K9 active pointer without its canonical run.',
      )
    }
  }
  if (unexpectedRun || (inspected.k9_mode === 'DEFERRED' && footprint.k9_runs.length !== 0)) {
    throw prepError(
      'PREP_LEGACY_PARTIAL_K9_RUN_DRIFT',
      'The legacy partial deployment contains a K9 run outside its canonical policy contract.',
    )
  }
  return Object.freeze({
    ...inspected,
    status: 'OWNED_PARTIAL',
    footprint: {
      active_session_count: footprint.active_session_count,
      derived_embedding_rows: footprint.table_counts.poc_catalog_embedding,
      k9_policy_count: policies.length,
      k9_run_count: footprint.k9_runs.length,
      neo4j_namespaces: [...allowedNamespaces].sort(),
    },
  })
}

function adminSubjectId(username) {
  const suffix = createHash('sha256').update(username, 'utf8').digest('hex').slice(0, 20)
  return `prep39083-admin-${suffix}`
}

export async function reconcilePrepBootstrap({
  stateStore,
  environment = process.env,
  administrator,
  randomPassword = () => randomBytes(48).toString('base64url'),
}) {
  let inspected = await inspectPrepBootstrap({ stateStore, environment })
  const specification = serviceSpecification(environment)
  const created = []
  if (inspected.administrators.length === 0) {
    if (!administrator?.username || !administrator?.password) {
      throw prepError(
        'PREP_ADMIN_REQUIRED',
        'No PREP administrator exists; one username and hidden password are required.',
      )
    }
    const username = normalizePocUsername(administrator.username)
    await bootstrapLocalHumanAccount({
      stateStore,
      subjectId: adminSubjectId(username),
      username,
      role: 'admin',
      password: administrator.password,
      setActiveSubject: true,
    })
    created.push('ADMIN')
  }
  for (const service of specification.services) {
    inspected = await inspectPrepBootstrap({ stateStore, environment })
    const current = inspected.services.find((item) => item.name === service.name)
    if (current?.status === 'PRESENT') continue
    await bootstrapLocalHumanAccount({
      stateStore,
      subjectId: service.subjectId,
      username: service.username,
      role: service.role,
      password: randomPassword(),
    })
    created.push(service.name)
  }
  inspected = await inspectPrepBootstrap({ stateStore, environment })
  if (inspected.administrators.length < 1
    || inspected.services.some((service) => service.status !== 'PRESENT')) {
    throw prepError('PREP_BOOTSTRAP_INCOMPLETE', 'Target-local identity reconciliation is incomplete.')
  }
  return Object.freeze({ ...inspected, created })
}

function parseArguments(argv) {
  const [action, ...rest] = argv
  if (!['inspect', 'inspect-owned-partial', 'reconcile'].includes(action)) {
    throw prepError('PREP_BOOTSTRAP_INPUT_INVALID', 'Action must be inspect, inspect-owned-partial or reconcile.')
  }
  const values = {}
  const allowed = new Set(['--admin-username', '--admin-password-file'])
  for (let index = 0; index < rest.length; index += 1) {
    const option = rest[index]
    if (!allowed.has(option) || !rest[index + 1] || rest[index + 1].startsWith('--')) {
      throw prepError('PREP_BOOTSTRAP_INPUT_INVALID', `${option} is invalid.`)
    }
    if (values[option]) throw prepError('PREP_BOOTSTRAP_INPUT_INVALID', `${option} is duplicated.`)
    values[option] = rest[index + 1]
    index += 1
  }
  if (Boolean(values['--admin-username']) !== Boolean(values['--admin-password-file'])) {
    throw prepError(
      'PREP_BOOTSTRAP_INPUT_INVALID',
      '--admin-username and --admin-password-file must be supplied together.',
    )
  }
  return { action, username: values['--admin-username'], passwordFile: values['--admin-password-file'] }
}

async function main() {
  const arguments_ = parseArguments(process.argv.slice(2))
  const stateStore = createPocStateStore()
  if (!stateStore.configured.postgres) {
    throw prepError('PREP_POSTGRES_REQUIRED', 'PREP bootstrap requires Compose PostgreSQL configuration.')
  }
  try {
    if (arguments_.action === 'inspect') {
      process.stdout.write(`${JSON.stringify(await inspectPrepBootstrap({ stateStore }))}\n`)
      return
    }
    if (arguments_.action === 'inspect-owned-partial') {
      process.stdout.write(`${JSON.stringify(await inspectPrepOwnedPartial({ stateStore }))}\n`)
      return
    }
    const administrator = arguments_.username
      ? {
          username: arguments_.username,
          password: await readBootstrapPasswordFile(resolve(arguments_.passwordFile)),
        }
      : undefined
    process.stdout.write(`${JSON.stringify(await reconcilePrepBootstrap({ stateStore, administrator }))}\n`)
  } finally {
    await stateStore.close?.()
  }
}

if (resolve(process.argv[1] || '') === resolve(fileURLToPath(import.meta.url))) {
  main().catch((error) => {
    const code = error?.code === '28P01'
      ? 'PREP_LOCAL_DB_CREDENTIAL_MISMATCH'
      : (typeof error?.code === 'string' ? error.code : 'PREP_BOOTSTRAP_FAILED')
    const message = code === 'PREP_LOCAL_DB_CREDENTIAL_MISMATCH'
      ? 'Compose application credentials do not authenticate to the existing PostgreSQL volume.'
      : (error instanceof Error ? error.message : 'PREP bootstrap failed.')
    process.stderr.write(`${JSON.stringify({ status: 'FAILED', code, reason: message })}\n`)
    process.exitCode = 2
  })
}
