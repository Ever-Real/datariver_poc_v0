# ADR-0137: K9 Semantic input segmentation and selective vector compatibility

- Status: Accepted for implementation; PREP runtime acceptance pending
- Date: 2026-09-04
- Owners: Control Plane, Data Architecture, Knowledge Platform
- Refines: ADR-0130, ADR-0133
- Does not authorize: PREP access, Source recapture, graph reprojection, timeout widening, provider-specific asset exceptions, or manual Semantic state cleanup

## Context

K9 Semantic V2 historically sent each immutable catalog document as one provider embedding input.
Actual PREP proved that one real 21,466-byte document was rejected with HTTP 400 even though
deterministic prefixes through 16 KiB were accepted and a synthetic input of comparable byte size
was accepted. The result proves a per-input provider size or token boundary, but does not establish
an exact byte or token limit and does not authorize a provider-specific threshold.

The durable desired Source Y, Lineage(Y), and Metadata(Y) are already valid. Semantic correction
must resume Y without creating Source Z, and it must preserve compatible vectors already staged or
active for unchanged short documents. PostgreSQL retrieval uses pgvector cosine distance, so a
multi-segment document needs one deterministic cosine-compatible final vector.

## Decision

Adopt `DATARIVER_K9_SEMANTIC_INPUT_SEGMENTATION_V1` with a conservative Product-owned envelope of
8,192 UTF-8 bytes per provider input. This is a safety envelope, not a claim about provider token
capacity. Identical content always yields the same segments. A maximal UTF-8-safe window prefers,
within its latter half, the last paragraph boundary, then newline, then whitespace; otherwise it
uses the maximal code-point boundary. Segment concatenation must equal the original content. A
document inside the envelope remains one segment and its provider input is byte-for-byte unchanged.

Provider units are ordered by document identity and then segment ordinal. Calls retain the bounded
32-input maximum. An HTTP 400 for multiple bounded units is bisected deterministically by unit
count; a bounded single-unit HTTP 400 is terminal and typed. Content is never recursively rewritten.

Adopt `DATARIVER_K9_SEMANTIC_WEIGHTED_MEAN_L2_V1` for multi-segment pooling. Segment vectors are
weighted by segment UTF-8 byte length, averaged, and L2-normalized for cosine retrieval. Dimensions
must agree and every input/output value must be finite. A single segment returns the provider vector
unchanged. Only the final document vector is persisted or exposed; segment identities are not
catalog or search identities.

## Durable identity and selective reuse

The existing provider/output binding remains the active search binding. A separate immutable
materialization hash binds that output binding to the segmentation, pooling, ordering, batch, and
HTTP-400 planning contracts. Existing V2 manifest, batch, and staging tables use the materialization
hash as their immutable namespace; no second write path or schema is introduced.

The effective vector-source identity is the document content `source_hash` together with the
materialization hash. Legacy active or staged vectors have no segmentation proof. They are reusable
only when the current document produces exactly one segment, because that provider input is exactly
the legacy input. A current-contract active pointer proves compatibility for both single- and
multi-segment documents. New staging evidence under the materialization hash proves the current
contract. Thus unchanged short documents are reused, while oversized documents are selectively
rebuilt; the contract does not force a full index rebuild.

Activation remains one transaction. It resolves every desired document from current-contract
staging, compatible legacy single-segment staging, or a compatible active vector, verifies exact
cardinality and vector dimensions, writes one vector per original document under the stable output
binding, and advances the active pointer. The pointer records the materialization, segmentation,
and pooling contracts. Incomplete staging cannot advance it. Immutable legacy evidence is neither
updated nor deleted.

Crash before a final document batch is staged may repeat uncommitted provider calls. Crash after a
batch commit reuses that exact contiguous document batch. It cannot duplicate the final vector,
recapture Source, rerun graph projectors, or create another snapshot. A READY rerun makes zero
provider calls.

## Doctor contract

PREP EMBEDDING preflight performs one bounded synthetic `POST /embeddings` with the configured
runtime endpoint, model, transport, proxy, CA, token, and timeout. READY requires an HTTP success,
exactly one indexed vector, a bounded non-zero dimension, and finite values. The vector is never
persisted or printed. This proves endpoint/model/vector compatibility but intentionally does not
duplicate long-document segmentation acceptance.

## Safety

Source Y and its receipts, Lineage and Metadata receipts, graph LKGs, MCL evidence, provider
configuration, authorization, and retrieval identities are unchanged. No DataHub or Neo4j call is
introduced during Semantic retry. No PREP-specific content, URN, model, endpoint, or observed
20-KiB rejection boundary is hardcoded.
