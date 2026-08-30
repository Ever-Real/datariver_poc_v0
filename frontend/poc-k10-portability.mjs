/* global console, process, structuredClone */
import { createHash } from 'node:crypto'
import {
  chmod,
  cp,
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  realpath,
  rm,
  stat,
  writeFile,
} from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { execFileSync } from 'node:child_process'

export const K10_MANIFEST_SCHEMA = 'DATARIVER_KNOWLEDGE_PORTABILITY_V1'
export const K10_REFERENCE_SCHEMA = 'DATARIVER_KNOWLEDGE_TARGET_REFERENCES_V1'
export const K9_INPUT_PRODUCT_SHA = 'b1f384979b289cddfd946ec6791c6718e70f1f3d'
export const K9_EVIDENCE_SHA = 'd45432f3e6773474442706c54f7cc9b67c2648d6'
export const K9_EVIDENCE_PATH = '.orchestration/evidence/DEV-KNOWLEDGE-K9-MANAGED-GRAPHS-RUNTIME.md'
export const K9_EVIDENCE_CONTENT_SHA256 = 'bdb267e29712b4490a99a61e667139ab269a0b748d84c07ed777a21ae01c6b06'

export const PORTABILITY_CLASSIFICATIONS = Object.freeze([
  'PORTABLE_IMMUTABLE_ARTIFACT',
  'ENVIRONMENT_LOCAL_CONFIGURATION',
  'ENVIRONMENT_LOCAL_SECRET',
  'REGENERATED_FROM_CANONICAL_SOURCE',
  'PERSISTENT_RUNTIME_STATE',
  'NON_PORTABLE_DISPOSABLE_STATE',
])

export const K1_K9_PORTABILITY_MATRIX = Object.freeze([
  { id: 'product.source', phase: 'K1-K9', state: 'Reviewed Product source and frozen dependency locks', classification: 'PORTABLE_IMMUTABLE_ARTIFACT', recovery: 'Verify exact Product SHA and artifact checksums before use.' },
  { id: 'k1.datahub_urns', phase: 'K1', state: 'Exact DataHub URNs retained in canonical Knowledge records', classification: 'PERSISTENT_RUNTIME_STATE', recovery: 'Restore PostgreSQL and reconcile against the configured DataHub source.' },
  { id: 'k1.studio_state', phase: 'K1', state: 'Knowledge Studio drafts, releases, projection receipts and CAS versions in poc_state.core', classification: 'PERSISTENT_RUNTIME_STATE', recovery: 'Restore PostgreSQL; never reconstruct accepted lifecycle state from Neo4j.' },
  { id: 'k1.datahub_projection', phase: 'K1', state: 'DataHub identities and provider projection derived from canonical source', classification: 'REGENERATED_FROM_CANONICAL_SOURCE', recovery: 'Re-run the bounded provider reconciliation.' },
  { id: 'k1.neo4j_projection', phase: 'K1', state: 'Knowledge graph query projection in Neo4j', classification: 'NON_PORTABLE_DISPOSABLE_STATE', recovery: 'Discard and rebuild from the exact published release.' },
  { id: 'k2.asset_versions', phase: 'K2', state: 'Registry Asset/version lifecycle, release hashes and version history', classification: 'PERSISTENT_RUNTIME_STATE', recovery: 'Restore PostgreSQL and verify immutable release hashes.' },
  { id: 'k3.tbox', phase: 'K3', state: 'Typed T-Box blocks, elements, ETags and CAS state', classification: 'PERSISTENT_RUNTIME_STATE', recovery: 'Restore PostgreSQL and resume only from the current fenced version.' },
  { id: 'k4.proposal_pins', phase: 'K4', state: 'Accepted proposal identities and immutable source/mapping pins', classification: 'PERSISTENT_RUNTIME_STATE', recovery: 'Restore accepted pins; reject a proposal whose source fingerprint drifted.' },
  { id: 'k4.proposal_selection', phase: 'K4', state: 'Bounded DataHub proposal selection results before acceptance', classification: 'REGENERATED_FROM_CANONICAL_SOURCE', recovery: 'Repeat the bounded proposal job against the configured source.' },
  { id: 'k5.migration_002', phase: 'K5', state: 'Numbered POC Knowledge ingestion migration 002', classification: 'PORTABLE_IMMUTABLE_ARTIFACT', recovery: 'Verify checksum and apply in order before runtime bootstrap.' },
  { id: 'k5.source_jobs', phase: 'K5', state: 'Knowledge source rows, jobs, exact release and T-Box pins', classification: 'PERSISTENT_RUNTIME_STATE', recovery: 'Restore PostgreSQL and replay only through the existing fenced recovery path.' },
  { id: 'k5.neo4j_stage', phase: 'K5', state: 'A-Box staging and derived Neo4j materialization', classification: 'NON_PORTABLE_DISPOSABLE_STATE', recovery: 'Remove incomplete namespaces and rebuild from the persistent receipt.' },
  { id: 'k6.graphrag_contract', phase: 'K6', state: 'Release-scoped read-only snapshot, GraphRAG and citation implementation', classification: 'PORTABLE_IMMUTABLE_ARTIFACT', recovery: 'Restore the exact Product artifact and revalidate the release pin.' },
  { id: 'k6.provider_config', phase: 'K6', state: 'Provider endpoints, selected models and allowlisted origins', classification: 'ENVIRONMENT_LOCAL_CONFIGURATION', recovery: 'Provision from the target-approved ignored environment.' },
  { id: 'k6.provider_secrets', phase: 'K6', state: 'Chat, embedding and reranker credentials', classification: 'ENVIRONMENT_LOCAL_SECRET', recovery: 'Provision or rotate only through the target secret store.' },
  { id: 'k7.delivery_policy', phase: 'K7', state: 'Delivery Policy versions, ETags and exact release/projection bindings', classification: 'PERSISTENT_RUNTIME_STATE', recovery: 'Restore PostgreSQL and revalidate policy, release and projection before use.' },
  { id: 'k7.policy_code', phase: 'K7', state: 'Version-fenced policy routing and fallback/concealment implementation', classification: 'PORTABLE_IMMUTABLE_ARTIFACT', recovery: 'Restore the exact Product artifact.' },
  { id: 'k8.mcp_contract', phase: 'K8', state: 'Fixed read-only MCP endpoint with exactly two Knowledge tools', classification: 'PORTABLE_IMMUTABLE_ARTIFACT', recovery: 'Restore the exact Product artifact; do not synthesize a browser UI.' },
  { id: 'k8.identity_config', phase: 'K8', state: 'Dedicated MCP Subject and Workspace references', classification: 'ENVIRONMENT_LOCAL_CONFIGURATION', recovery: 'Resolve target-local identities and recheck active membership.' },
  { id: 'k8.service_token', phase: 'K8', state: 'Dedicated MCP bearer credential', classification: 'ENVIRONMENT_LOCAL_SECRET', recovery: 'Provision or rotate outside the artifact bundle.' },
  { id: 'k9.migration_003', phase: 'K9', state: 'Numbered POC managed-graph migration 003', classification: 'PORTABLE_IMMUTABLE_ARTIFACT', recovery: 'Verify checksum and apply in order before policy reconciliation.' },
  { id: 'k9.exact_pins', phase: 'K9', state: 'Exact Product-owned graph, ontology, release, T-Box, contract, proposal, source and mapping pins', classification: 'PORTABLE_IMMUTABLE_ARTIFACT', recovery: 'Reject local policy drift before materialization.' },
  { id: 'k9.policies_runs', phase: 'K9', state: 'Managed graph policies, active pointers, run receipts and scheduler boundary', classification: 'PERSISTENT_RUNTIME_STATE', recovery: 'Restore PostgreSQL, reconcile two policies and replay from the last durable boundary.' },
  { id: 'k9.source_snapshots', phase: 'K9', state: 'Bounded Lineage and Glossary source snapshots', classification: 'REGENERATED_FROM_CANONICAL_SOURCE', recovery: 'Collect again through the private authenticated Product seams.' },
  { id: 'k9.neo4j_namespaces', phase: 'K9', state: 'K9 active and staging Neo4j namespaces', classification: 'NON_PORTABLE_DISPOSABLE_STATE', recovery: 'Clean PREPARING/orphan namespaces and deterministically rebuild.' },
  { id: 'k9.runtime_config', phase: 'K9', state: 'Scheduler, time zone, System Subject and Workspace', classification: 'ENVIRONMENT_LOCAL_CONFIGURATION', recovery: 'Reconcile the built-in DAILY policy and target-local identities.' },
  { id: 'k9.runtime_secrets', phase: 'K9', state: 'Neo4j credential', classification: 'ENVIRONMENT_LOCAL_SECRET', recovery: 'Provision the target-local secret reference and never place values in the manifest.' },
])

const REQUIRED_ARTIFACT_PATHS = Object.freeze([
  'frontend/poc-k10-portability.mjs',
  'frontend/poc-knowledge-k9-contracts.mjs',
  'frontend/poc-table-data-access.mjs',
  'frontend/poc-table-system-mappings.mjs',
  'frontend/poc-access-document.mjs',
  'frontend/poc-k9-managed-graphs.mjs',
  'frontend/poc-k9-scheduler.mjs',
  'frontend/poc-state-store.mjs',
  'frontend/poc-server.mjs',
  'deploy/poc/postgres-init/002-poc-knowledge-ingestion.sql',
  'deploy/poc/postgres-init/003-poc-k9-managed-graphs.sql',
  'docs/adr/0127-k9-canonical-managed-graph-contracts.md',
])

const REQUIRED_SECRET_REFERENCES = Object.freeze([
  { key: 'POC_MCP_SERVICE_TOKEN', owner: 'K8 MCP service authentication', required_on: 'TARGET_WHEN_MCP_ENABLED' },
  { key: 'NEO4J_PASSWORD', owner: 'Derived graph adapter', required_on: 'TARGET_WHEN_K9_ENABLED' },
  { key: 'POC_POSTGRES_PASSWORD', owner: 'Persistent POC state adapter', required_on: 'TARGET' },
])

const EXPECTED_K9_PINS = Object.freeze([
  Object.freeze({
    graph_id: '01a02d2a-f8a0-7658-b5da-890eccdccf44',
    name: 'CATALOG_MIRROR',
    ontology_version_id: '01a02d2a-f8a9-74d2-b0d4-125601c37f49',
    studio_release_id: '01a02d2a-f8ad-789f-acb0-7df3ea3d0ef0',
    publication_version: 6,
    schedule: '02:00 Asia/Seoul',
    managed_intent: 'metadata-lineage',
    accepted_proposal_id: 'contract.semantic.metadata-lineage',
    classification: 'INTERNAL',
    tbox_hash: '9e6e5982bceb8a85572768f746c901c84e5a5dfe28dcb3fb70e5c25acf4c799b',
    contract_hash: '187bae99322f03deedc6daaf3c3d6546c798afb8b2f1423e90e21b3b2da1ace9',
    proposal_hash: '9b6a5e0e07624df4520d333b5d673fbe77f7ab84b0f352bbe3c647b262523e96',
    source_hash: '8d8cba3f1b46f997e234207f956238bf4a87e752d7566c20bb41a1e08d2a5feb',
    mapping_hash: 'f923778369eda84d0b2942d7fd1b1b837f64125fc3a2f5dd4dc72bcdc9d99bf3',
  }),
  Object.freeze({
    graph_id: '01a02d2a-f90d-74fe-bd96-aa596276cb87',
    name: 'CURATED_KNOWLEDGE',
    ontology_version_id: '01a02d2a-f90f-7ba3-8e7c-af7153e123cc',
    studio_release_id: '01a02d2a-f910-73b7-a2f0-a8f5e4698e88',
    publication_version: 6,
    schedule: '02:00 Asia/Seoul',
    managed_intent: 'data-glossary',
    accepted_proposal_id: 'contract.semantic.data-glossary',
    classification: 'INTERNAL',
    tbox_hash: '9e6e5982bceb8a85572768f746c901c84e5a5dfe28dcb3fb70e5c25acf4c799b',
    contract_hash: '243e22c403146ac713a2f86a0714859122836d2ca5ccd581e9998c1d2a4eac43',
    proposal_hash: '670ac1d49ab091debe23bc706cc479576af226ea55d73fa5ffd2c1a4993836d1',
    source_hash: '12cba3de9e71c2453d94c2f625839593d627ea60f6143097a49a9d3782a089d8',
    mapping_hash: 'ed3160311a3058f9e61bc8478b07175d96b6fe3c035b55fb4fe94455a6098e7f',
  }),
])

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const ARTIFACT_DIRECTORY = 'knowledge-artifacts'
const EVIDENCE_DIRECTORY = 'knowledge-evidence'
const MANIFEST_FILE = 'knowledge-portability-manifest.json'
const HASH_PATTERN = /^[0-9a-f]{64}$/
const GIT_SHA_PATTERN = /^[0-9a-f]{40}$/

function canonicalJson(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value)
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`
  return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(',')}}`
}

function sha256(content) {
  return createHash('sha256').update(content).digest('hex')
}

function assertExactKeys(value, keys, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label} must be an object`)
  const actual = Object.keys(value).sort()
  const expected = [...keys].sort()
  if (canonicalJson(actual) !== canonicalJson(expected)) throw new Error(`${label} keys do not match the K10 contract`)
}

function assertRelativeArtifactPath(value) {
  if (typeof value !== 'string' || value.length === 0 || isAbsolute(value) || value.split('/').includes('..') || value.includes('\\')) {
    throw new Error(`Unsafe artifact path: ${String(value)}`)
  }
}

async function fileEvidence(repoRoot, sourcePath) {
  assertRelativeArtifactPath(sourcePath)
  const content = await readFile(join(repoRoot, sourcePath))
  return {
    path: sourcePath,
    sha256: sha256(content),
    size_bytes: content.length,
    classification: 'PORTABLE_IMMUTABLE_ARTIFACT',
  }
}

function readCanonicalEvidence(repoRoot) {
  const content = execFileSync('git', ['show', `${K9_EVIDENCE_SHA}:${K9_EVIDENCE_PATH}`], {
    cwd: repoRoot,
    encoding: null,
    maxBuffer: 2 * 1024 * 1024,
  })
  if (sha256(content) !== K9_EVIDENCE_CONTENT_SHA256 || content.length !== 8300) throw new Error('Canonical K9 Evidence Git object integrity mismatch')
  return content
}

function canonicalEvidence(repoRoot) {
  const content = readCanonicalEvidence(repoRoot)
  return {
    git_sha: K9_EVIDENCE_SHA,
    path: K9_EVIDENCE_PATH,
    bundle_path: `${EVIDENCE_DIRECTORY}/${basename(K9_EVIDENCE_PATH)}`,
    sha256: sha256(content),
    size_bytes: content.length,
  }
}

export async function buildKnowledgeManifest({ repoRoot = REPO_ROOT } = {}) {
  const evidenceChecksums = []
  for (const sourcePath of REQUIRED_ARTIFACT_PATHS) evidenceChecksums.push(await fileEvidence(repoRoot, sourcePath))
  const byPath = new Map(evidenceChecksums.map((entry) => [entry.path, entry]))
  const migrations = ['002-poc-knowledge-ingestion.sql', '003-poc-k9-managed-graphs.sql'].map((fileName) => {
    const path = `deploy/poc/postgres-init/${fileName}`
    const evidence = byPath.get(path)
    return { revision: fileName.slice(0, 3), path, sha256: evidence.sha256 }
  })
  return {
    schema: K10_MANIFEST_SCHEMA,
    input_product_sha: K9_INPUT_PRODUCT_SHA,
    canonical_evidence: canonicalEvidence(repoRoot),
    artifact_policy: 'NON_SECRET_CHECKSUMMED_ARTIFACTS_ONLY',
    required_migrations: migrations,
    managed_graph_pins: EXPECTED_K9_PINS.map((pin) => ({ ...pin })),
    schedule_intent: {
      cadence: '02:00 Asia/Seoul',
      execution: 'TRIGGER_ONLY',
      enabled_by_default: false,
      durable_boundary_owner: 'poc_state:k9-scheduler-v1',
    },
    portability_matrix: K1_K9_PORTABILITY_MATRIX.map((entry) => ({ ...entry })),
    secret_references: REQUIRED_SECRET_REFERENCES.map((entry) => ({ ...entry })),
    evidence_checksums: evidenceChecksums,
  }
}

function validateK9Pins(actualPins) {
  if (!Array.isArray(actualPins) || actualPins.length !== EXPECTED_K9_PINS.length) throw new Error('K9 exact pin set is incomplete')
  for (let index = 0; index < EXPECTED_K9_PINS.length; index += 1) {
    const expected = EXPECTED_K9_PINS[index]
    const actual = actualPins[index]
    assertExactKeys(actual, Object.keys(expected), `managed_graph_pins[${index}]`)
    if (canonicalJson(actual) !== canonicalJson(expected)) throw new Error(`K9 exact pin mismatch for ${expected.managed_intent}`)
  }
}

function validateClassificationMatrix(matrix) {
  if (!Array.isArray(matrix) || matrix.length !== K1_K9_PORTABILITY_MATRIX.length) throw new Error('K1-K9 portability matrix is incomplete')
  const ids = new Set()
  const phases = new Set()
  for (const entry of matrix) {
    assertExactKeys(entry, ['id', 'phase', 'state', 'classification', 'recovery'], `portability_matrix.${entry?.id || 'unknown'}`)
    if (ids.has(entry.id)) throw new Error(`Duplicate portability state: ${entry.id}`)
    ids.add(entry.id)
    phases.add(entry.phase)
    if (!PORTABILITY_CLASSIFICATIONS.includes(entry.classification)) throw new Error(`Classification violation for ${entry.id}`)
  }
  for (let phase = 1; phase <= 9; phase += 1) {
    if (![...phases].some((value) => value === `K${phase}` || value === 'K1-K9')) throw new Error(`Portability matrix is missing K${phase}`)
  }
  if (canonicalJson(matrix) !== canonicalJson(K1_K9_PORTABILITY_MATRIX)) throw new Error('Portability classification matrix drift')
}

function validateSecretBoundary(manifest) {
  if (canonicalJson(manifest.secret_references) !== canonicalJson(REQUIRED_SECRET_REFERENCES)) throw new Error('Secret reference inventory drift')
  const serialized = canonicalJson(manifest)
  const forbiddenValuePatterns = [
    /postgres(?:ql)?:\/\/[^/@:\s]+:[^/@\s]+@/i,
    /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/,
    /Bearer\s+[A-Za-z0-9._~+/=-]{12,}/i,
  ]
  if (forbiddenValuePatterns.some((pattern) => pattern.test(serialized))) throw new Error('Manifest contains a secret value')
}

export async function validateKnowledgeManifest(manifest, { bundleRoot, expectedInputProductSha } = {}) {
  assertExactKeys(manifest, [
    'schema', 'input_product_sha', 'canonical_evidence', 'artifact_policy', 'required_migrations', 'managed_graph_pins',
    'schedule_intent', 'portability_matrix', 'secret_references', 'evidence_checksums',
  ], 'manifest')
  if (manifest.schema !== K10_MANIFEST_SCHEMA) throw new Error('Knowledge manifest schema mismatch')
  if (!expectedInputProductSha) throw new Error('An independently supplied expected input Product SHA is required')
  if (!GIT_SHA_PATTERN.test(expectedInputProductSha)) throw new Error('Expected input Product SHA must be a full Git SHA')
  if (manifest.input_product_sha !== expectedInputProductSha || manifest.input_product_sha !== K9_INPUT_PRODUCT_SHA) throw new Error('Input Product SHA mismatch')
  assertExactKeys(manifest.canonical_evidence, ['git_sha', 'path', 'bundle_path', 'sha256', 'size_bytes'], 'canonical_evidence')
  const expectedCanonicalEvidence = {
    git_sha: K9_EVIDENCE_SHA,
    path: K9_EVIDENCE_PATH,
    bundle_path: `${EVIDENCE_DIRECTORY}/${basename(K9_EVIDENCE_PATH)}`,
    sha256: K9_EVIDENCE_CONTENT_SHA256,
    size_bytes: 8300,
  }
  if (canonicalJson(manifest.canonical_evidence) !== canonicalJson(expectedCanonicalEvidence)) throw new Error('Canonical K9 Evidence provenance mismatch')
  if (manifest.artifact_policy !== 'NON_SECRET_CHECKSUMMED_ARTIFACTS_ONLY') throw new Error('Artifact policy mismatch')
  assertExactKeys(manifest.schedule_intent, ['cadence', 'execution', 'enabled_by_default', 'durable_boundary_owner'], 'schedule_intent')
  if (canonicalJson(manifest.schedule_intent) !== canonicalJson({
    cadence: '02:00 Asia/Seoul', execution: 'TRIGGER_ONLY', enabled_by_default: false, durable_boundary_owner: 'poc_state:k9-scheduler-v1',
  })) throw new Error('K9 schedule intent drift')
  validateK9Pins(manifest.managed_graph_pins)
  validateClassificationMatrix(manifest.portability_matrix)
  validateSecretBoundary(manifest)
  if (!Array.isArray(manifest.evidence_checksums) || manifest.evidence_checksums.length !== REQUIRED_ARTIFACT_PATHS.length) throw new Error('Evidence checksum inventory is incomplete')
  const evidenceByPath = new Map()
  for (const evidence of manifest.evidence_checksums) {
    assertExactKeys(evidence, ['path', 'sha256', 'size_bytes', 'classification'], `evidence.${evidence?.path || 'unknown'}`)
    assertRelativeArtifactPath(evidence.path)
    if (!REQUIRED_ARTIFACT_PATHS.includes(evidence.path) || evidenceByPath.has(evidence.path)) throw new Error(`Unexpected or duplicate evidence path: ${evidence.path}`)
    if (!HASH_PATTERN.test(evidence.sha256) || !Number.isSafeInteger(evidence.size_bytes) || evidence.size_bytes < 1) throw new Error(`Invalid evidence checksum metadata: ${evidence.path}`)
    if (evidence.classification !== 'PORTABLE_IMMUTABLE_ARTIFACT') throw new Error(`Artifact classification violation: ${evidence.path}`)
    evidenceByPath.set(evidence.path, evidence)
  }
  for (const requiredPath of REQUIRED_ARTIFACT_PATHS) {
    if (!evidenceByPath.has(requiredPath)) throw new Error(`Missing required artifact: ${requiredPath}`)
  }
  if (!Array.isArray(manifest.required_migrations) || manifest.required_migrations.length !== 2) throw new Error('Required migration set must contain 002 and 003')
  for (const [index, revision] of ['002', '003'].entries()) {
    const migration = manifest.required_migrations[index]
    assertExactKeys(migration, ['revision', 'path', 'sha256'], `required_migrations[${index}]`)
    if (migration.revision !== revision || migration.path !== `deploy/poc/postgres-init/${revision}-${revision === '002' ? 'poc-knowledge-ingestion' : 'poc-k9-managed-graphs'}.sql`) throw new Error(`Migration revision mismatch: ${revision}`)
    if (migration.sha256 !== evidenceByPath.get(migration.path).sha256) throw new Error(`Migration checksum mismatch: ${revision}`)
  }
  if (bundleRoot) {
    for (const evidence of manifest.evidence_checksums) {
      const artifactPath = join(bundleRoot, ARTIFACT_DIRECTORY, evidence.path)
      const content = await readFile(artifactPath).catch(() => { throw new Error(`Missing artifact file: ${evidence.path}`) })
      if (content.length !== evidence.size_bytes || sha256(content) !== evidence.sha256) throw new Error(`Artifact integrity mismatch: ${evidence.path}`)
    }
    const evidenceContent = await readFile(join(bundleRoot, manifest.canonical_evidence.bundle_path)).catch(() => { throw new Error('Missing canonical K9 Evidence artifact') })
    if (evidenceContent.length !== manifest.canonical_evidence.size_bytes || sha256(evidenceContent) !== manifest.canonical_evidence.sha256) throw new Error('Canonical K9 Evidence artifact integrity mismatch')
  }
  return {
    status: 'VERIFIED',
    input_product_sha: manifest.input_product_sha,
    evidence_sha: manifest.canonical_evidence.git_sha,
    artifact_count: manifest.evidence_checksums.length,
  }
}

export async function prepareKnowledgeBundle({ outputDir, repoRoot = REPO_ROOT } = {}) {
  if (!outputDir) throw new Error('outputDir is required')
  const manifest = await buildKnowledgeManifest({ repoRoot })
  await mkdir(outputDir, { recursive: false })
  for (const evidence of manifest.evidence_checksums) {
    const target = join(outputDir, ARTIFACT_DIRECTORY, evidence.path)
    await mkdir(dirname(target), { recursive: true })
    await cp(join(repoRoot, evidence.path), target, { dereference: false, errorOnExist: true })
  }
  const canonicalEvidenceTarget = join(outputDir, manifest.canonical_evidence.bundle_path)
  await mkdir(dirname(canonicalEvidenceTarget), { recursive: true })
  await writeFile(canonicalEvidenceTarget, readCanonicalEvidence(repoRoot), { mode: 0o644, flag: 'wx' })
  await writeFile(join(outputDir, MANIFEST_FILE), `${canonicalJson(manifest)}\n`, { encoding: 'utf8', mode: 0o644, flag: 'wx' })
  await validateKnowledgeManifest(manifest, { bundleRoot: outputDir, expectedInputProductSha: K9_INPUT_PRODUCT_SHA })
  return {
    stage: 'PREP_LIKE',
    input_product_sha: manifest.input_product_sha,
    evidence_sha: manifest.canonical_evidence.git_sha,
    artifact_count: manifest.evidence_checksums.length,
    secrets_included: 0,
  }
}

async function loadManifest(bundleRoot) {
  const raw = await readFile(join(bundleRoot, MANIFEST_FILE), 'utf8').catch(() => { throw new Error(`Missing ${MANIFEST_FILE}`) })
  let manifest
  try {
    manifest = JSON.parse(raw)
  } catch {
    throw new Error('Knowledge manifest is not valid JSON')
  }
  return manifest
}

async function directorySnapshot(root) {
  const entries = []
  async function visit(directory) {
    const names = await readdir(directory, { withFileTypes: true })
    for (const name of names.sort((left, right) => left.name.localeCompare(right.name))) {
      const fullPath = join(directory, name.name)
      const itemPath = relative(root, fullPath).split(sep).join('/')
      if (name.isDirectory()) await visit(fullPath)
      else if (name.isFile()) entries.push({ path: itemPath, sha256: sha256(await readFile(fullPath)) })
      else throw new Error(`Artifact bundle contains a non-file entry: ${itemPath}`)
    }
  }
  await visit(root)
  return entries
}

export async function verifyTransferBundle({ bundleRoot, expectedInputProductSha } = {}) {
  if (!bundleRoot) throw new Error('bundleRoot is required')
  const before = await directorySnapshot(bundleRoot)
  const manifest = await loadManifest(bundleRoot)
  const validation = await validateKnowledgeManifest(manifest, { bundleRoot, expectedInputProductSha })
  const after = await directorySnapshot(bundleRoot)
  if (canonicalJson(before) !== canonicalJson(after)) throw new Error('Transfer verification mutated the artifact bundle')
  const runtimeMarkers = before.filter(({ path }) => /(?:postgres|neo4j|runtime-state|secret)/i.test(basename(path)))
  if (runtimeMarkers.length !== 0) throw new Error('Transfer bundle contains a runtime materialization marker')
  return {
    stage: 'TRANSFER_PC',
    ...validation,
    bundle_mutations: 0,
    database_materializations: 0,
    neo4j_materializations: 0,
    runtime_secret_files: 0,
  }
}

function isPathInside(child, parent) {
  const childPath = resolve(child)
  const parentPath = resolve(parent)
  return childPath === parentPath || childPath.startsWith(`${parentPath}${sep}`)
}

export async function validateTargetReferences(referenceDocument, { bundleRoot } = {}) {
  assertExactKeys(referenceDocument, ['schema', 'environment', 'secret_files'], 'target references')
  if (referenceDocument.schema !== K10_REFERENCE_SCHEMA) throw new Error('Target reference schema mismatch')
  const expectedEnvironmentKeys = [
    'POC_K9_SCHEDULER_TIME_ZONE', 'POC_K9_SYSTEM_SUBJECT_ID', 'POC_K9_WORKSPACE_ID',
    'POC_MCP_SUBJECT_ID', 'POC_MCP_WORKSPACE_ID',
  ]
  assertExactKeys(referenceDocument.environment, expectedEnvironmentKeys, 'target environment')
  for (const key of expectedEnvironmentKeys) {
    if (typeof referenceDocument.environment[key] !== 'string' || referenceDocument.environment[key].trim().length === 0) throw new Error(`Missing target configuration reference: ${key}`)
  }
  if (referenceDocument.environment.POC_K9_SCHEDULER_TIME_ZONE !== 'Asia/Seoul') throw new Error('K9 scheduler time zone mismatch')
  if (referenceDocument.environment.POC_K9_SYSTEM_SUBJECT_ID === referenceDocument.environment.POC_MCP_SUBJECT_ID) throw new Error('K9 and MCP Subjects must remain distinct')
  assertExactKeys(referenceDocument.secret_files, REQUIRED_SECRET_REFERENCES.map(({ key }) => key), 'target secret files')
  for (const { key } of REQUIRED_SECRET_REFERENCES) {
    const secretPath = referenceDocument.secret_files[key]
    if (typeof secretPath !== 'string' || !isAbsolute(secretPath)) throw new Error(`Missing secret reference: ${key}`)
    const resolvedPath = await realpath(secretPath).catch(() => { throw new Error(`Missing secret reference: ${key}`) })
    if (bundleRoot && isPathInside(resolvedPath, bundleRoot)) throw new Error(`Secret reference crosses the artifact boundary: ${key}`)
    const metadata = await stat(resolvedPath)
    if (!metadata.isFile() || metadata.size < 1 || (metadata.mode & 0o077) !== 0) throw new Error(`Secret reference is not an owner-only non-empty file: ${key}`)
  }
  return true
}

function createSimulationStateStore() {
  const policies = new Map()
  const runs = new Map()
  return {
    async ensureK9Policies(values) {
      for (const value of values) policies.set(value.graph_id, structuredClone(value))
    },
    async getK9Policy(graphId) { return policies.get(graphId) || null },
    async getK9PreparingRuns() { return [...runs.values()].filter((run) => run.status === 'PREPARING') },
    async getK9OrphanRuns() { return [] },
    async createK9PreparingRun(run) { runs.set(run.run_id, { ...structuredClone(run), status: 'PREPARING' }) },
    async getLastK9Run(graphId) {
      return [...runs.values()].reverse().find((run) => run.graph_id === graphId && ['RUN', 'NO_OP'].includes(run.status)) || null
    },
    async finalizeK9RunNoOp(runId, activePointer) {
      const run = runs.get(runId)
      const prior = [...runs.values()].reverse().find((candidate) => candidate.graph_id === run.graph_id && candidate.status === 'RUN')
      Object.assign(run, {
        status: 'NO_OP', active_release_pointer: activePointer,
        input_snapshot_hash: prior.input_snapshot_hash, manifest: prior.manifest, canonical_release: prior.canonical_release,
      })
    },
    async finalizeK9RunFailure(runId, errorMessage) { Object.assign(runs.get(runId), { status: 'FAILURE', error_message: errorMessage }) },
    async executeK9Transaction(graphId, runId, manifestPayload, canonicalRelease, activePointer, manifestHash, inputSnapshotHash, policyHash) {
      Object.assign(runs.get(runId), {
        status: 'RUN', manifest: structuredClone(manifestPayload), canonical_release: structuredClone(canonicalRelease),
        active_release_pointer: activePointer, manifest_hash: manifestHash, input_snapshot_hash: inputSnapshotHash, policy_hash: policyHash,
      })
      Object.assign(policies.get(graphId), { active_release_pointer: activePointer, active_release_hash: manifestHash })
      return true
    },
    seedPreparingRun(run) { runs.set(run.run_id, { ...structuredClone(run), status: 'PREPARING' }) },
    cleanupSimulation() {
      policies.clear()
      runs.clear()
    },
    observation() {
      return {
        policy_count: policies.size,
        run_count: runs.size,
        run_status_counts: [...runs.values()].reduce((counts, run) => ({ ...counts, [run.status]: (counts[run.status] || 0) + 1 }), {}),
      }
    },
  }
}

function createSimulationNeo4j() {
  const namespaces = new Map()
  const ensureNamespace = (namespace) => {
    if (!namespaces.has(namespace)) namespaces.set(namespace, { nodes: new Map(), edges: [], release: null })
    return namespaces.get(namespace)
  }
  return {
    async run(query, parameters = {}) {
      if (query.startsWith('CREATE CONSTRAINT ') || query.startsWith('CREATE INDEX ')) return []
      if (query.includes('DETACH DELETE')) {
        namespaces.delete(parameters.namespace || parameters.ns)
        return []
      }
      if (query.includes('CREATE (n:K9Node:K9Release')) {
        ensureNamespace(parameters.ns).release = { hash: parameters.hash, policy: parameters.policy }
        return []
      }
      if (query.includes('UNWIND $nodes AS node')) {
        for (const node of parameters.nodes) {
          ensureNamespace(parameters.ns).nodes.set(node.id, {
            id: node.id,
            type: node.type,
            classification: node.classification,
            properties: node.properties,
          })
        }
        return []
      }
      if (query.includes('UNWIND $edges AS edge')) {
        for (const edge of parameters.edges) {
          ensureNamespace(parameters.ns).edges.push({
            source: edge.source,
            target: edge.target,
            type: edge.type,
            properties: edge.properties,
          })
        }
        return []
      }
      if (query.includes('CREATE (n:K9Node')) {
        ensureNamespace(parameters.ns).nodes.set(parameters.id, {
          id: parameters.id, type: parameters.type, classification: parameters.classification, properties: parameters.props,
        })
        return []
      }
      if (query.includes('CREATE (source)-[r:K9Edge')) {
        ensureNamespace(parameters.ns).edges.push({ source: parameters.sourceId, target: parameters.targetId, type: parameters.type, properties: parameters.props })
        return []
      }
      if (query.includes('RETURN n.id AS id')) {
        return [...ensureNamespace(parameters.ns).nodes.values()].sort((left, right) => left.id.localeCompare(right.id)).map((node) => [node.id, node.type, node.classification, node.properties])
      }
      if (query.includes('RETURN source.id AS source')) {
        return ensureNamespace(parameters.ns).edges.sort((left, right) => left.source.localeCompare(right.source) || left.target.localeCompare(right.target) || left.type.localeCompare(right.type)).map((edge) => [edge.source, edge.target, edge.type, edge.properties])
      }
      if (query.includes('MATCH (n:K9Release)')) {
        const release = ensureNamespace(parameters.ns).release
        return release ? [[release.hash, release.policy]] : []
      }
      throw new Error('Unexpected K10 Neo4j simulation query')
    },
    seedNamespace(namespace) { ensureNamespace(namespace).nodes.set('recovery-marker', { id: 'recovery-marker' }) },
    cleanupSimulation() { namespaces.clear() },
    observation() { return { namespace_count: namespaces.size, node_count: [...namespaces.values()].reduce((count, value) => count + value.nodes.size, 0) } },
  }
}

function authorityPin(environment) {
  return {
    projection_version: 1,
    policy_version: 'POC_LIVE_PROVIDER_V1',
    classification_policy_version: 1,
    authorization_generation: 1,
    workspace_id: environment.POC_K9_WORKSPACE_ID,
    subject_id: environment.POC_K9_SYSTEM_SUBJECT_ID,
    classification_ceiling: 'INTERNAL',
  }
}

async function applySimulationMigrations(bundleRoot, manifest) {
  const ledger = new Map()
  const requiredMarkers = new Map([
    ['002', ['poc_knowledge_ingestion_jobs', 'poc_knowledge_source_rows']],
    ['003', ['poc_k9_managed_graph_policies', 'poc_k9_refresh_runs']],
  ])
  for (const migration of manifest.required_migrations) {
    if (ledger.has(migration.revision)) throw new Error(`Duplicate target migration: ${migration.revision}`)
    const sql = await readFile(join(bundleRoot, ARTIFACT_DIRECTORY, migration.path), 'utf8')
    if (sha256(sql) !== migration.sha256) throw new Error(`Target migration checksum mismatch: ${migration.revision}`)
    for (const marker of requiredMarkers.get(migration.revision) || []) {
      if (!sql.includes(`CREATE TABLE IF NOT EXISTS ${marker}`)) throw new Error(`Target migration ${migration.revision} is missing ${marker}`)
    }
    ledger.set(migration.revision, migration.sha256)
  }
  return [...ledger.keys()]
}

const LINEAGE_TABLE_A = 'TABLE:urn:li:dataset:(urn:li:dataPlatform:postgres,k10.orders,PROD)'
const LINEAGE_TABLE_B = 'TABLE:urn:li:dataset:(urn:li:dataPlatform:postgres,k10.customers,PROD)'

export async function simulateTargetRuntime({ bundleRoot, referencesPath, expectedInputProductSha } = {}) {
  const manifest = await loadManifest(bundleRoot)
  await validateKnowledgeManifest(manifest, { bundleRoot, expectedInputProductSha })
  const references = JSON.parse(await readFile(referencesPath, 'utf8'))
  await validateTargetReferences(references, { bundleRoot })
  const migrationsApplied = await applySimulationMigrations(bundleRoot, manifest)
  const modulePath = join(bundleRoot, ARTIFACT_DIRECTORY, 'frontend/poc-k9-managed-graphs.mjs')
  const { createK9ManagedGraphs } = await import(`${pathToFileURL(modulePath).href}?k10=${Date.now()}`)
  const stateStore = createSimulationStateStore()
  const neo4j = createSimulationNeo4j()
  const k9 = createK9ManagedGraphs({ stateStore, neo4j, log: { info() {}, warn() {} } })
  const environment = references.environment
  const previousSubject = process.env.POC_K9_SYSTEM_SUBJECT_ID
  const previousWorkspace = process.env.POC_K9_WORKSPACE_ID
  process.env.POC_K9_SYSTEM_SUBJECT_ID = environment.POC_K9_SYSTEM_SUBJECT_ID
  process.env.POC_K9_WORKSPACE_ID = environment.POC_K9_WORKSPACE_ID
  const context = { principal: { subjectId: environment.POC_K9_SYSTEM_SUBJECT_ID }, workspaceId: environment.POC_K9_WORKSPACE_ID }
  let targetReceipt
  let preCleanup
  let postCleanup
  try {
    await k9.bootstrapK9Policies(context)
    const lineageCollector = async () => ({
      authority_pin: authorityPin(environment),
      nodes: [
        { id: LINEAGE_TABLE_A, external_urn: LINEAGE_TABLE_A.slice(6), classification: 'INTERNAL' },
        { id: LINEAGE_TABLE_B, external_urn: LINEAGE_TABLE_B.slice(6), classification: 'INTERNAL' },
      ],
      edges: [{ source_asset_id: LINEAGE_TABLE_A, target_asset_id: LINEAGE_TABLE_B }],
    })
    const glossaryCollector = async () => ({
      authority_pin: authorityPin(environment),
      terms: [{ urn: 'urn:li:glossaryTerm:k10.customer', name: 'Customer', description: 'K10 portability fixture' }],
      parent_nodes: [{ urn: 'urn:li:glossaryNode:k10', name: 'K10' }],
      term_parent_edges: [{ term_urn: 'urn:li:glossaryTerm:k10.customer', parent_urn: 'urn:li:glossaryNode:k10' }],
      node_parent_edges: [],
      table_assignments: [{ id: LINEAGE_TABLE_B, term_urn: 'urn:li:glossaryTerm:k10.customer', classification: 'INTERNAL' }],
      column_assignments: [],
    })
    const lineageRun = await k9.triggerLineagePublish(context, lineageCollector)
    const glossaryRun = await k9.triggerGlossaryPublish(context, glossaryCollector)
    const lineageReplay = await k9.triggerLineagePublish(context, lineageCollector)
    const glossaryReplay = await k9.triggerGlossaryPublish(context, glossaryCollector)
    if (lineageRun.status !== 'RUN' || glossaryRun.status !== 'RUN'
      || lineageReplay.status !== 'NO_OP' || glossaryReplay.status !== 'NO_OP') {
      throw new Error(`K9 target materialization or replay failed (${[
        lineageRun, glossaryRun, lineageReplay, glossaryReplay,
      ].map((result) => [result.status, result.reason_code || result.reason].filter(Boolean).join(':')).join('/')})`)
    }

    let wrongWorkspaceDenied = false
    try {
      await k9.triggerLineagePublish({ principal: context.principal, workspaceId: 'wrong-workspace' }, lineageCollector)
    } catch (error) {
      wrongWorkspaceDenied = /mismatched K9 workspace/.test(error.message)
    }
    if (!wrongWorkspaceDenied) throw new Error('Wrong Workspace path did not fail closed')

    const classificationResult = await k9.triggerLineagePublish(context, async () => ({
      authority_pin: authorityPin(environment),
      nodes: [{ id: LINEAGE_TABLE_A, classification: 'CONFIDENTIAL' }], edges: [],
    }))
    if (classificationResult.status !== 'FAILURE'
      || !/Classification exceeds ceiling/.test(classificationResult.reason)) {
      throw new Error(`Classification violation did not fail closed (${[
        classificationResult.status,
        classificationResult.reason_code || classificationResult.reason,
      ].filter(Boolean).join(':')})`)
    }

    const recoveryRunId = '00000000-0000-4000-8000-000000000001'
    const recoveryNamespace = 'k9_stage_00000000000040008000000000000001'
    stateStore.seedPreparingRun({ run_id: recoveryRunId, graph_id: manifest.managed_graph_pins[0].graph_id, policy_hash: '0'.repeat(64), input_snapshot_hash: '1'.repeat(64) })
    neo4j.seedNamespace(recoveryNamespace)
    await k9.performRestartRecovery()
    const state = stateStore.observation()
    const graph = neo4j.observation()
    if (state.policy_count !== 2 || state.run_status_counts.PREPARING || graph.namespace_count !== 2) throw new Error('Restart recovery did not converge to the two active namespaces')
    preCleanup = {
      policies: state.policy_count,
      runs: state.run_count,
      neo4j_namespaces: graph.namespace_count,
      neo4j_nodes: graph.node_count,
    }
    targetReceipt = {
      stage: 'TARGET',
      input_product_sha: manifest.input_product_sha,
      evidence_sha: manifest.canonical_evidence.git_sha,
      migrations_applied: migrationsApplied,
      policies_reconciled: state.policy_count,
      lineage: { first: lineageRun.status, replay: lineageReplay.status },
      glossary: { first: glossaryRun.status, replay: glossaryReplay.status },
      negatives: { wrong_workspace: 'DENIED', classification_violation: classificationResult.status },
      recovery: 'PREPARING_TO_FAILURE_AND_STAGING_REMOVED',
    }
  } finally {
    stateStore.cleanupSimulation()
    neo4j.cleanupSimulation()
    const state = stateStore.observation()
    const graph = neo4j.observation()
    postCleanup = {
      policies: state.policy_count,
      runs: state.run_count,
      neo4j_namespaces: graph.namespace_count,
      neo4j_nodes: graph.node_count,
    }
    if (previousSubject === undefined) delete process.env.POC_K9_SYSTEM_SUBJECT_ID
    else process.env.POC_K9_SYSTEM_SUBJECT_ID = previousSubject
    if (previousWorkspace === undefined) delete process.env.POC_K9_WORKSPACE_ID
    else process.env.POC_K9_WORKSPACE_ID = previousWorkspace
  }
  if (Object.values(postCleanup).some((count) => count !== 0)) throw new Error('Target simulation cleanup did not reach zero')
  return { ...targetReceipt, cleanup: { pre_cleanup: preCleanup, post_cleanup: postCleanup } }
}

async function provisionSimulationReferences(root) {
  const secretRoot = join(root, 'target-local-secrets')
  await mkdir(secretRoot, { recursive: true, mode: 0o700 })
  const secretFiles = {}
  for (const { key } of REQUIRED_SECRET_REFERENCES) {
    const secretPath = join(secretRoot, key.toLowerCase())
    await writeFile(secretPath, `k10-local-simulation-${key.toLowerCase()}\n`, { mode: 0o600, flag: 'wx' })
    await chmod(secretPath, 0o600)
    secretFiles[key] = secretPath
  }
  const referenceDocument = {
    schema: K10_REFERENCE_SCHEMA,
    environment: {
      POC_K9_SCHEDULER_TIME_ZONE: 'Asia/Seoul',
      POC_K9_SYSTEM_SUBJECT_ID: 'k10-target-k9-system-subject',
      POC_K9_WORKSPACE_ID: '00000000-0000-0000-0000-000000000100',
      POC_MCP_SUBJECT_ID: 'k10-target-mcp-service-subject',
      POC_MCP_WORKSPACE_ID: '00000000-0000-0000-0000-000000000100',
    },
    secret_files: secretFiles,
  }
  const referencesPath = join(root, 'target-references.json')
  await writeFile(referencesPath, `${canonicalJson(referenceDocument)}\n`, { mode: 0o600, flag: 'wx' })
  return referencesPath
}

export async function runThreeStageSimulation({ temporaryBase = tmpdir(), repoRoot = REPO_ROOT } = {}) {
  const simulationRoot = await mkdtemp(join(temporaryBase, 'datariver-k10-'))
  let receipt
  let preCleanupFiles
  try {
    const prepBundle = join(simulationRoot, 'prep-bundle')
    const transferBundle = join(simulationRoot, 'transfer-bundle')
    const targetBundle = join(simulationRoot, 'target-bundle')
    const prep = await prepareKnowledgeBundle({ outputDir: prepBundle, repoRoot })
    await cp(prepBundle, transferBundle, { recursive: true, errorOnExist: true })
    const transfer = await verifyTransferBundle({ bundleRoot: transferBundle, expectedInputProductSha: K9_INPUT_PRODUCT_SHA })
    await cp(transferBundle, targetBundle, { recursive: true, errorOnExist: true })
    const referencesPath = await provisionSimulationReferences(simulationRoot)
    const target = await simulateTargetRuntime({ bundleRoot: targetBundle, referencesPath, expectedInputProductSha: K9_INPUT_PRODUCT_SHA })
    receipt = { schema: 'DATARIVER_K10_THREE_STAGE_SIMULATION_V1', prep, transfer, target }
    preCleanupFiles = (await directorySnapshot(simulationRoot)).length
  } finally {
    await rm(simulationRoot, { recursive: true, force: true })
  }
  let cleanupRootExists = true
  try { await lstat(simulationRoot) } catch { cleanupRootExists = false }
  if (cleanupRootExists) throw new Error('K10 simulation temporary root was not removed')
  const cleanup = {
    pre_cleanup_files: preCleanupFiles,
    post_cleanup_files: 0,
    temporary_root_exists: false,
  }
  if (cleanup.post_cleanup_files !== 0 || cleanup.temporary_root_exists) throw new Error('K10 simulation file cleanup did not reach zero')
  return { ...receipt, cleanup }
}

function parseArguments(args) {
  const [command, ...rest] = args
  const options = {}
  for (let index = 0; index < rest.length; index += 2) {
    const key = rest[index]
    const value = rest[index + 1]
    if (!key?.startsWith('--') || value === undefined) throw new Error(`Invalid argument: ${key || ''}`)
    options[key.slice(2)] = value
  }
  return { command, options }
}

async function main() {
  const { command, options } = parseArguments(process.argv.slice(2))
  let result
  if (command === 'prepare') result = await prepareKnowledgeBundle({ outputDir: resolve(options.output) })
  else if (command === 'transfer-verify') result = await verifyTransferBundle({ bundleRoot: resolve(options.bundle), expectedInputProductSha: options['product-sha'] })
  else if (command === 'target-simulate') result = await simulateTargetRuntime({ bundleRoot: resolve(options.bundle), referencesPath: resolve(options.references), expectedInputProductSha: options['product-sha'] })
  else if (command === 'simulate') result = await runThreeStageSimulation({ temporaryBase: options['temporary-base'] ? resolve(options['temporary-base']) : tmpdir() })
  else throw new Error('Usage: poc-k10-portability.mjs prepare|transfer-verify|target-simulate|simulate [options]')
  console.log(canonicalJson(result))
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    console.error(`K10 portability: ${error.message}`)
    process.exitCode = 1
  })
}
