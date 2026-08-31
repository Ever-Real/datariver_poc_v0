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
    'readStagedDocumentHashes',
    'writeEmbeddingBatch',
    'persistDesiredManifest',
    'activateSnapshot',
  ])
  assert.equal('materializeSnapshot' in port, false)
})
