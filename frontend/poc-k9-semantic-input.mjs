/* global Buffer */
import { computeSha256 } from './poc-knowledge-k9-contracts.mjs'

export const K9_SEMANTIC_INPUT_SEGMENTATION_CONTRACT_V1 =
  'DATARIVER_K9_SEMANTIC_INPUT_SEGMENTATION_V1'
export const K9_SEMANTIC_VECTOR_POOLING_CONTRACT_V1 =
  'DATARIVER_K9_SEMANTIC_WEIGHTED_MEAN_L2_V1'
export const K9_SEMANTIC_MATERIALIZATION_CONTRACT_V1 =
  'DATARIVER_K9_SEMANTIC_MATERIALIZATION_V1'
export const K9_SEMANTIC_MAX_SEGMENT_BYTES_V1 = 8_192
export const K9_SEMANTIC_PROVIDER_INPUT_BATCH_SIZE_V1 = 32

const hashPattern = /^[0-9a-f]{64}$/u

export class K9SemanticInputContractError extends Error {
  constructor(kind) {
    super('The Semantic input materialization contract is invalid.')
    this.name = 'K9SemanticInputContractError'
    this.kind = kind
  }
}

export const K9_SEMANTIC_MATERIALIZATION_DESCRIPTOR_V1 = Object.freeze({
  contract: K9_SEMANTIC_MATERIALIZATION_CONTRACT_V1,
  segmentation: Object.freeze({
    contract: K9_SEMANTIC_INPUT_SEGMENTATION_CONTRACT_V1,
    maximum_utf8_bytes: K9_SEMANTIC_MAX_SEGMENT_BYTES_V1,
    boundary_algorithm: 'PARAGRAPH_NEWLINE_WHITESPACE_LAST_HALF_V1',
    fallback_boundary_algorithm: 'UTF8_CODE_POINT_HARD_BOUNDARY_V1',
  }),
  pooling: Object.freeze({
    contract: K9_SEMANTIC_VECTOR_POOLING_CONTRACT_V1,
    algorithm: 'UTF8_BYTE_WEIGHTED_MEAN_THEN_L2_NORMALIZE_V1',
    single_segment: 'PROVIDER_VECTOR_UNCHANGED',
  }),
  provider_batch: Object.freeze({
    order: 'DOCUMENT_THEN_SEGMENT_ORDINAL',
    maximum_inputs: K9_SEMANTIC_PROVIDER_INPUT_BATCH_SIZE_V1,
    http_400_fallback: 'DETERMINISTIC_INPUT_COUNT_BISECTION_V1',
  }),
})

export function k9SemanticMaterializationHash(outputBindingHash) {
  const normalized = String(outputBindingHash || '').trim().toLowerCase()
  if (!hashPattern.test(normalized)) {
    throw new TypeError('The Semantic output binding hash is invalid.')
  }
  return computeSha256({
    output_binding_hash: normalized,
    materialization: K9_SEMANTIC_MATERIALIZATION_DESCRIPTOR_V1,
  })
}

function utf8ByteLength(value) {
  return Buffer.byteLength(value, 'utf8')
}

function nextSegmentEnd(content, start) {
  let cursor = start
  let bytes = 0
  let safeEnd = start
  let paragraphEnd = null
  let newlineEnd = null
  let whitespaceEnd = null
  let previous = ''
  const preferredMinimum = Math.floor(K9_SEMANTIC_MAX_SEGMENT_BYTES_V1 / 2)

  for (const codePoint of content.slice(start)) {
    const codePointBytes = utf8ByteLength(codePoint)
    if (bytes + codePointBytes > K9_SEMANTIC_MAX_SEGMENT_BYTES_V1) break
    bytes += codePointBytes
    cursor += codePoint.length
    safeEnd = cursor
    if (bytes >= preferredMinimum) {
      if (previous === '\n' && codePoint === '\n') paragraphEnd = cursor
      if (codePoint === '\n') newlineEnd = cursor
      if (/\s/u.test(codePoint)) whitespaceEnd = cursor
    }
    previous = codePoint
  }
  if (safeEnd === content.length) return safeEnd
  return paragraphEnd ?? newlineEnd ?? whitespaceEnd ?? safeEnd
}

export function segmentK9SemanticInput(content) {
  if (typeof content !== 'string' || content.length === 0) {
    throw new K9SemanticInputContractError('CONTENT')
  }
  if (utf8ByteLength(content) <= K9_SEMANTIC_MAX_SEGMENT_BYTES_V1) {
    return Object.freeze([content])
  }
  const segments = []
  let start = 0
  while (start < content.length) {
    const end = nextSegmentEnd(content, start)
    if (end <= start) throw new K9SemanticInputContractError('SEGMENTATION')
    const segment = content.slice(start, end)
    if (utf8ByteLength(segment) > K9_SEMANTIC_MAX_SEGMENT_BYTES_V1) {
      throw new K9SemanticInputContractError('SEGMENTATION')
    }
    segments.push(segment)
    start = end
  }
  if (segments.join('') !== content) throw new K9SemanticInputContractError('SEGMENTATION')
  return Object.freeze(segments)
}

export function k9SemanticInputPlan(content) {
  const segments = segmentK9SemanticInput(content)
  const segmentBytes = Object.freeze(segments.map(utf8ByteLength))
  return Object.freeze({
    contract: K9_SEMANTIC_INPUT_SEGMENTATION_CONTRACT_V1,
    segments,
    segment_bytes: segmentBytes,
    segment_count: segments.length,
    legacy_compatible: segments.length === 1,
  })
}

export function poolK9SemanticVectors(segments, vectors) {
  if (!Array.isArray(segments) || !Array.isArray(vectors)
    || segments.length === 0 || segments.length !== vectors.length) {
    throw new K9SemanticInputContractError('COUNT')
  }
  const dimension = vectors[0]?.length
  if (!Number.isSafeInteger(dimension) || dimension < 1
    || vectors.some((vector) => !Array.isArray(vector) || vector.length !== dimension)) {
    throw new K9SemanticInputContractError('DIMENSION')
  }
  if (vectors.some((vector) => vector.some((value) => (
    typeof value !== 'number' || !Number.isFinite(value)
  )))) {
    throw new K9SemanticInputContractError('FINITE')
  }
  if (vectors.length === 1) return Object.freeze([...vectors[0]])

  const weights = segments.map(utf8ByteLength)
  const totalWeight = weights.reduce((total, value) => total + value, 0)
  if (!Number.isSafeInteger(totalWeight) || totalWeight < 1) {
    throw new K9SemanticInputContractError('WEIGHT')
  }
  const mean = Array.from({ length: dimension }, (_value, index) => (
    vectors.reduce((total, vector, vectorIndex) => (
      total + (vector[index] * weights[vectorIndex])
    ), 0) / totalWeight
  ))
  if (mean.some((value) => !Number.isFinite(value))) {
    throw new K9SemanticInputContractError('FINITE')
  }
  const norm = Math.hypot(...mean)
  if (!Number.isFinite(norm) || norm <= 0) {
    throw new K9SemanticInputContractError('FINITE')
  }
  const pooled = mean.map((value) => value / norm)
  if (pooled.some((value) => !Number.isFinite(value))) {
    throw new K9SemanticInputContractError('FINITE')
  }
  return Object.freeze(pooled)
}
