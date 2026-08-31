# ADR-0133: Decouple K9 source capture, graph projection, and semantic projection

- Status: Accepted; implementation and PREP runtime acceptance pending
- Date: 2026-08-31
- Owners: Control Plane, Data Architecture, Knowledge Platform, Security Architecture
- Refines: ADR-0127, ADR-0128, ADR-0130, ADR-0132
- Does not authorize: PREP access, PREP deployment, state reset, resecret, manual DDL, source mutation, or origin/main promotion

## Context

The legacy K9 refresh path captures DataHub metadata, materializes the catalog semantic index,
builds a source snapshot, and then publishes the managed Lineage and Metadata graphs in one
strongly ordered operation. A semantic failure therefore prevents a durable source capture and
causes retries to repeat expensive, already verified DataHub collection and graph work. The
existing source snapshot also includes semantic-generation inputs, so source identity and a
derived projector lifecycle are circularly coupled.

In PREP this coupling repeatedly hid the exact semantic failure behind aggregate smoke status and
made recovery repeat glossary resolution and dangling-reference accounting even after those stages
had completed successfully. The K9 REQUIRED smoke gate remains necessary: it protects source
consistency, LKG ownership, and authorization. Its implementation must become a persisted-readiness
validator rather than the owner of repeated materialization.

## Decision

Adopt an additive V2 lifecycle centered on one immutable, source-only identity:

```text
DataHub source capture
  -> immutable Source Snapshot X
  -> Lineage Projector receipt(X)
  -> Metadata Projector receipt(X)
  -> Semantic Projector receipt(X)
  -> Aggregate Readiness(X)
```

`source_snapshot_id` is derived only from canonical authorized/current source state, normalization
and source contract versions, and relevant K9 policy pins. It excludes projector generations,
provider latency, active pointers, attempt timestamps, progress, and readiness results. The same
canonical source therefore always produces the same snapshot identity.

Each projector records a durable desired snapshot, active snapshot, status, attempt, bounded
failure diagnostic, and progress. Required states are `PENDING`, `RUNNING`, `READY`, and `FAILED`.
A projector may activate X only after its complete materialization for X succeeds. Failed or
incomplete materializations remain inactive and the existing active/LKG pointer is preserved.

Aggregate K9 readiness for REQUIRED mode is deliberately simple:

```text
SOURCE_READY(X)
AND LINEAGE_READY(X)
AND METADATA_READY(X)
AND SEMANTIC_READY(X)
```

Projector success is not a prerequisite for another projector's materialization. Initial execution
may remain sequential until concurrency safety is proven; lifecycle independence does not require
parallel execution.

## Resume contract

If Semantic fails for X while Lineage and Metadata are READY for X, a retry reuses Source Snapshot
X and the completed graph receipts. It must not recollect DataHub inventory, repeat direct glossary
resolution or dangling accounting, or reproject either graph. Equivalent single-projector resume
rules apply to Lineage and Metadata failures.

Smoke reads the persisted V2 source/projector receipts and validates aggregate readiness. It does
not start an implicit second source refresh. Safe read-only MCL and GENERAL diagnostics may continue
after K9 failure, but their visibility never weakens REQUIRED-mode acceptance.

## Persistence and migration

V2 tables/receipts are Product-owned, forward-only, transactional, additive, and idempotent. Legacy
receipts, accepted markers, graph LKG, semantic active pointers, PostgreSQL rows, Neo4j data, Redis
state, and failed attempts remain readable and are never reset or rewritten.

Legacy state may be adopted as READY only when existing Lineage, Metadata, and Semantic identities
prove the same canonical source generation and V2 `source_snapshot_id` can be reconstructed
deterministically. Otherwise the lifecycle records `LEGACY_LKG_PRESERVED / NEW_SNAPSHOT_REQUIRED`,
keeps all active pointers intact, and starts a new V2 source capture.

## Fail-closed boundaries

The design continues to reject authorization or classification failure, malformed provider
responses, identity contradictions, source inconsistency, projector materialization failure,
promotion failure, mixed snapshot IDs, and LKG ownership failure. It does not add a fail-open path,
timeout increase, reset, resecret, fuzzy mapping, or DataHub mutation.

Semantic diagnostics are bounded and typed at the actual call path (binding/catalog projection,
provider request/response, vector contract, generation lock, materialization, and active-pointer
verification). Receipts and operator status never persist raw text, vectors, URNs, tokens, or
secrets.

## Release gate

No PREP release may be prepared until V2 persistence, source identity, all three projector
lifecycles, resume/adoption, aggregate readiness, smoke/status, the Actual-PREP-shaped retry test,
and the full applicable regression are proven. PREP deployment remains a manual operator action
through the existing `sync`, `status`, and `deploy` command surface.

