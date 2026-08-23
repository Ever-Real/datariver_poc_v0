import test from 'node:test'
import assert from 'node:assert/strict'
import { cp, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import {
  K10_MANIFEST_SCHEMA,
  K10_REFERENCE_SCHEMA,
  K1_K9_PORTABILITY_MATRIX,
  K9_EVIDENCE_CONTENT_SHA256,
  K9_EVIDENCE_PATH,
  K9_EVIDENCE_SHA,
  K9_INPUT_PRODUCT_SHA,
  PORTABILITY_CLASSIFICATIONS,
  buildKnowledgeManifest,
  prepareKnowledgeBundle,
  runThreeStageSimulation,
  validateKnowledgeManifest,
  validateTargetReferences,
  verifyTransferBundle,
} from './poc-k10-portability.mjs'

async function temporaryDirectory(prefix) {
  return mkdtemp(join(tmpdir(), prefix))
}

test('K10 manifest separately binds the accepted K9 input Product, canonical Evidence, and non-secret artifacts', async () => {
  const manifest = await buildKnowledgeManifest()
  assert.equal(manifest.schema, K10_MANIFEST_SCHEMA)
  assert.equal(manifest.input_product_sha, K9_INPUT_PRODUCT_SHA)
  assert.deepEqual(manifest.canonical_evidence, {
    git_sha: K9_EVIDENCE_SHA,
    path: K9_EVIDENCE_PATH,
    bundle_path: 'knowledge-evidence/DEV-KNOWLEDGE-K9-MANAGED-GRAPHS-RUNTIME.md',
    sha256: K9_EVIDENCE_CONTENT_SHA256,
    size_bytes: 8300,
  })
  assert.deepEqual(manifest.required_migrations.map(({ revision }) => revision), ['002', '003'])
  assert.deepEqual(manifest.managed_graph_pins.map(({ managed_intent }) => managed_intent), ['metadata-lineage', 'data-glossary'])
  assert.equal(manifest.schedule_intent.execution, 'TRIGGER_ONLY')
  assert.equal(manifest.schedule_intent.enabled_by_default, false)
  assert.deepEqual(manifest.portability_matrix, K1_K9_PORTABILITY_MATRIX)
  assert.ok(manifest.portability_matrix.every(({ classification }) => PORTABILITY_CLASSIFICATIONS.includes(classification)))
  assert.equal(JSON.stringify(manifest).includes('-----BEGIN PRIVATE KEY-----'), false)
  await assert.doesNotReject(validateKnowledgeManifest(manifest, { expectedInputProductSha: K9_INPUT_PRODUCT_SHA }))
})

test('K10 transfer verification is read-only and rejects missing/corrupt artifacts, wrong Product/pin, and classification drift', async () => {
  const root = await temporaryDirectory('datariver-k10-transfer-test-')
  try {
    const prepared = join(root, 'prepared')
    await prepareKnowledgeBundle({ outputDir: prepared })
    await assert.rejects(verifyTransferBundle({ bundleRoot: prepared }), /independently supplied expected input Product SHA/)
    const verified = await verifyTransferBundle({ bundleRoot: prepared, expectedInputProductSha: K9_INPUT_PRODUCT_SHA })
    assert.deepEqual({
      stage: verified.stage,
      mutations: verified.bundle_mutations,
      database: verified.database_materializations,
      neo4j: verified.neo4j_materializations,
      secrets: verified.runtime_secret_files,
    }, { stage: 'TRANSFER_PC', mutations: 0, database: 0, neo4j: 0, secrets: 0 })

    const cases = [
      ['missing artifact', (manifest, bundle) => rm(join(bundle, 'knowledge-artifacts/frontend/poc-k9-scheduler.mjs')), /Missing artifact file/],
      ['corrupt artifact', (manifest, bundle) => writeFile(join(bundle, 'knowledge-artifacts/frontend/poc-k9-scheduler.mjs'), 'corrupt\n'), /Artifact integrity mismatch/],
      ['wrong Product', (manifest) => { manifest.input_product_sha = '0'.repeat(40) }, /Input Product SHA mismatch/],
      ['wrong Evidence provenance', (manifest) => { manifest.canonical_evidence.git_sha = '0'.repeat(40) }, /Canonical K9 Evidence provenance mismatch/],
      ['corrupt Evidence artifact', (manifest, bundle) => writeFile(join(bundle, 'knowledge-evidence/DEV-KNOWLEDGE-K9-MANAGED-GRAPHS-RUNTIME.md'), 'corrupt\n'), /Canonical K9 Evidence artifact integrity mismatch/],
      ['wrong exact pin', (manifest) => { manifest.managed_graph_pins[0].mapping_hash = '0'.repeat(64) }, /K9 exact pin mismatch/],
      ['classification violation', (manifest) => { manifest.portability_matrix[0].classification = 'TRANSFERABLE_SECRET' }, /Classification violation/],
    ]
    for (const [name, mutate, expected] of cases) {
      const bundle = join(root, name.replaceAll(' ', '-'))
      await cp(prepared, bundle, { recursive: true })
      const manifestPath = join(bundle, 'knowledge-portability-manifest.json')
      const manifest = JSON.parse(await readFile(manifestPath, 'utf8'))
      await mutate(manifest, bundle)
      await writeFile(manifestPath, `${JSON.stringify(manifest)}\n`)
      await assert.rejects(verifyTransferBundle({ bundleRoot: bundle, expectedInputProductSha: K9_INPUT_PRODUCT_SHA }), expected)
    }
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})

test('K10 target reference validation fails closed before runtime when a secret reference is missing', async () => {
  await assert.rejects(validateTargetReferences({
    schema: K10_REFERENCE_SCHEMA,
    environment: {
      POC_K9_SCHEDULER_TIME_ZONE: 'Asia/Seoul',
      POC_K9_SYSTEM_SUBJECT_ID: 'k9-subject',
      POC_K9_WORKSPACE_ID: 'workspace',
      POC_MCP_SUBJECT_ID: 'mcp-subject',
      POC_MCP_WORKSPACE_ID: 'workspace',
    },
    secret_files: {},
  }), /target secret files keys do not match/)
})

test('K10 three-stage simulation materializes and replays both K9 graphs, recovers, and cleans all disposable state', async () => {
  const receipt = await runThreeStageSimulation()
  assert.equal(receipt.prep.secrets_included, 0)
  assert.equal(receipt.prep.input_product_sha, K9_INPUT_PRODUCT_SHA)
  assert.equal(receipt.prep.evidence_sha, K9_EVIDENCE_SHA)
  assert.equal(receipt.transfer.bundle_mutations, 0)
  assert.equal(receipt.transfer.database_materializations, 0)
  assert.equal(receipt.transfer.neo4j_materializations, 0)
  assert.deepEqual(receipt.target.migrations_applied, ['002', '003'])
  assert.deepEqual(receipt.target.lineage, { first: 'RUN', replay: 'NO_OP' })
  assert.deepEqual(receipt.target.glossary, { first: 'RUN', replay: 'NO_OP' })
  assert.deepEqual(receipt.target.negatives, { wrong_workspace: 'DENIED', classification_violation: 'FAILURE' })
  assert.equal(receipt.target.recovery, 'PREPARING_TO_FAILURE_AND_STAGING_REMOVED')
  assert.ok(receipt.target.cleanup.pre_cleanup.policies > 0)
  assert.ok(receipt.target.cleanup.pre_cleanup.runs > 0)
  assert.ok(receipt.target.cleanup.pre_cleanup.neo4j_namespaces > 0)
  assert.deepEqual(receipt.target.cleanup.post_cleanup, {
    policies: 0, runs: 0, neo4j_namespaces: 0, neo4j_nodes: 0,
  })
  assert.ok(receipt.cleanup.pre_cleanup_files > 0)
  assert.deepEqual(receipt.cleanup, {
    pre_cleanup_files: receipt.cleanup.pre_cleanup_files,
    post_cleanup_files: 0,
    temporary_root_exists: false,
  })
})
