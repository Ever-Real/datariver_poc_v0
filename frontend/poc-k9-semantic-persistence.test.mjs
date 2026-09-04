import assert from 'node:assert/strict'
import test from 'node:test'

import { createK9SemanticPersistenceV2 } from './poc-k9-semantic-persistence.mjs'

test('exposes the canonical c7c14e0b Semantic projector persistence port', () => {
  const port = createK9SemanticPersistenceV2({
    requireDatabase: async () => { throw new Error('not used') },
    lifecycle: {
      readLifecycle() {},
      stageSemanticBatch() {},
      persistSemanticDesiredManifest() {},
      activateSemanticSnapshot() {},
    },
  })
  assert.deepEqual(Object.keys(port), [
    'withProjectorGenerationLock',
    'readProjectorState',
    'setDesiredSnapshot',
    'readActiveDocumentHashes',
    'readLegacyStagedDocumentHashes',
    'readStagedDocumentHashes',
    'writeEmbeddingBatch',
    'persistDesiredManifest',
    'activateSnapshot',
  ])
  assert.equal('materializeSnapshot' in port, false)
})

test('keeps materialization and stable output bindings distinct at activation', async () => {
  let activation
  const port = createK9SemanticPersistenceV2({
    requireDatabase: async () => { throw new Error('not used') },
    lifecycle: {
      readLifecycle() {},
      stageSemanticBatch() {},
      persistSemanticDesiredManifest() {},
      async activateSemanticSnapshot(value) { activation = value },
    },
  })
  await port.activateSnapshot({
    source_snapshot_id: 'a'.repeat(64),
    binding_hash: 'b'.repeat(64),
    output_binding_hash: 'c'.repeat(64),
    legacy_binding_hash: 'c'.repeat(64),
    materialization_contract: 'DATARIVER_K9_SEMANTIC_MATERIALIZATION_V1',
    semantic_input_contract: 'DATARIVER_K9_SEMANTIC_INPUT_SEGMENTATION_V1',
    pooling_contract: 'DATARIVER_K9_SEMANTIC_WEIGHTED_MEAN_L2_V1',
    maximum_segment_bytes: 8_192,
    document_count: 2,
    staged_count: 1,
    batch_total: 1,
  })
  assert.deepEqual(activation, {
    source_snapshot_id: 'a'.repeat(64),
    binding_hash: 'b'.repeat(64),
    output_binding_hash: 'c'.repeat(64),
    legacy_binding_hash: 'c'.repeat(64),
    materialization_contract: 'DATARIVER_K9_SEMANTIC_MATERIALIZATION_V1',
    semantic_input_contract: 'DATARIVER_K9_SEMANTIC_INPUT_SEGMENTATION_V1',
    pooling_contract: 'DATARIVER_K9_SEMANTIC_WEIGHTED_MEAN_L2_V1',
    maximum_segment_bytes: 8_192,
    expected_desired_count: 2,
    expected_changed_count: 1,
    expected_batch_count: 1,
  })
})
