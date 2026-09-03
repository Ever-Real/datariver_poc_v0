# ADR-0135: K9 source payload chunk persistence and verified-head promotion

- Status: Accepted for implementation; PREP runtime acceptance pending
- Date: 2026-09-03
- Owners: Control Plane, Data Architecture, Knowledge Platform
- Refines: ADR-0133
- Does not authorize: PREP access, PREP deployment, reset, manual DDL, source recapture changes, or `origin/main` promotion

## Context

K9 V2 first captures one stable canonical DataHub source and then persists four immutable payloads
before moving the lifecycle desired head. The original V6 contract stored each canonical payload in
one JSONB row and rejected any serialized payload above 67,108,864 bytes. Actual PREP completed its
stable source candidates and then failed at `SOURCE_RECEIPT` before a source receipt existed. The
old broad boundary retained neither the payload kind and byte count nor the SQLSTATE/constraint, so
the exact historical byte count cannot be reconstructed from its durable receipt.

The monolithic size check is the only source-volume-dependent pre-database boundary after a valid
capture, and a PREP-shaped metadata payload reproduces it above 64 MiB. Raising the JSONB limit
would retain the same scaling and diagnostic failure mode.

## Decision

Keep one canonical K9 V2 persistence path. New source payloads are canonical-JSON UTF-8 encoded and
split deterministically into 1 MiB immutable chunks. The existing payload row stores only a bounded
manifest containing the payload root hash, total bytes, chunk size/count, and ordered chunk hashes.
Chunks are inserted in bounded 16-chunk SQL batches. Existing monolithic V6 payload rows remain
readable; no payload is written in both representations.

`source_snapshot_id` and each payload hash continue to derive from canonical source content, not
from chunk boundaries, attempt timing, retries, or persistence results. Read-back verifies every
chunk hash, the ordered root hash, byte count, canonical JSON, and snapshot-bound payload hash.

Persistence uses two fail-closed phases:

1. atomically persist and read back the immutable snapshot, manifests, and chunks, then record a
   mutable `VERIFIED` staging pointer;
2. under the lifecycle lock, atomically move the desired head and mark that staging pointer
   `CONSUMED`.

A `VERIFIED` staging pointer is not a Source receipt and cannot make Source or aggregate K9 READY.
If head promotion fails after evidence verification, the next run reconstructs the exact staged
source and retries persistence without DataHub source collection. Partial or unverified chunks are
never promoted.

## Diagnostics and bounds

The outer scheduler code remains `K9_V2_SOURCE_RECEIPT_PERSISTENCE_FAILED`, with an allowlisted
substage, payload kind, canonical byte count, configured bound, SQLSTATE class, and constraint
name. It never retains SQL, rows, source JSON, URNs, names, stack traces, endpoints, or secrets.

The V8 bound is 1 GiB per canonical payload (`1,024 x 1 MiB` chunks). It is an explicit Product
resource bound, not a PREP count special case. Crossing it remains a typed, non-promotable failure.
No timeout, DataHub source semantics, Source consistency candidate algorithm, projector ordering,
authorization, MCL state, LKG, or semantic pointer changes under this decision.

## Migration and rollback

Migration `010` adds only `poc_k9_source_payload_chunks_v2`, the mutable
`poc_k9_source_staging_v2` pointer, an immutable-chunk trigger, index, and exact V8 schema receipt.
It is transactional and forward-only. Existing snapshots, payloads, receipts, lifecycle heads,
accepted state, PostgreSQL rows, Neo4j/LKG state, and semantic pointers are preserved. Rollback is
non-acceptance with the prior active pointers; it is never row deletion or reset.
