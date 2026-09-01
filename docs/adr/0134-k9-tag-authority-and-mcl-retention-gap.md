# ADR-0134: DataHub TAG authority separation and durable MCL retention gaps

- Status: Accepted
- Date: 2026-09-01
- Owners: Product, Security, Data, Application, Operations
- Preserves: exact Table grants, role/capability and Workspace boundaries, current/removed filtering,
  K9 LKG, append-only MCL ledger/checkpoints, and ADR-0133 lifecycle isolation
- Supersedes: ADR-0126 only where free-form DataHub Table TAGs were proposed as a Table
  authorization grade or retrieval authority

## Context

Actual PREP exposed two independent mismatches between a defensive implementation and the real
operational contract. All 1,892 current canonical Datasets lacked an exact controlled
`CLASSIFICATION:*` TAG, so the former K9 eligibility rule excluded the entire source. Separately, an
MCL checkpoint had fallen behind Kafka's retained low watermark while 357 exact historical ledger
events remained durable. Treating either condition as a permanent deploy blocker provides no safe
recovery path.

## DataHub TAG decision

DataHub TAG is descriptive taxonomy, search/display metadata and metadata-quality telemetry. It is
not K9 source-inclusion authority and is not Table read authorization authority. The Product never
fuzzily maps, corrects, aliases or defaults free-form TAG values into security state.

K9 source eligibility is the canonical current Dataset contract: exact Dataset identity, supported
TABLE/VIEW/MATERIALIZED_VIEW kind, and current/non-removed lifecycle. Classification resolution
(`EXACT`, `MISSING`, `MULTIPLE`, `INVALID`) remains bounded telemetry and may participate in a
metadata fingerprint, but it cannot remove an otherwise eligible Dataset. A source containing 1,892
current Datasets and 1,892 missing classification observations therefore remains eligible.

Table reads are authorized at request time by explicit Product-owned state: active role/capability,
Workspace boundary, exact active Table grant and exact applicable System scope. Admin behavior and
MCP service/user grant intersection remain unchanged. A Table with no explicit Product-owned grade
is not asserted to be `normal`; grade is simply not a Table authorization input. Arbitrary
`restricted`, `credential`, `confidential`, `critical`, `CLASSIFICATION:*` or misspelled TAG changes
cannot grant or revoke Table access.

Explicit Product-owned Knowledge classifications and the Change Request classification workflow
remain separate resource/business contracts. The existing bounded grade-keyed feature-policy
document may continue to govern resources that have an explicit Product-owned grade, but it is not
combined with a TAG-derived Table grade. Legacy TAG-grade helpers may be retained only for
historical/admin display compatibility and must have no authorization or K9 eligibility caller.

## MCL retention-gap decision

When an exact stored checkpoint is below Kafka's low watermark, the missing interval is
irrecoverable from that provider. The Product does not reset a checkpoint, delete historical rows,
or claim exact continuity. Instead it transactionally performs:

```text
lock exact checkpoint
→ append immutable RETENTION_EXPIRED gap receipt
→ verify receipt
→ advance checkpoint to observed low watermark
→ commit
→ capture retained records into a new exact segment
```

The receipt binds the source and partition, previous checkpoint, low/high watermarks, missing
interval, prior exact-segment identity, new segment start, observation time and contract version.
Receipt failure or checkpoint-fence loss rolls back the entire transition. Exact replay is
idempotent and cannot create a duplicate receipt.

MCL readiness has two independent dimensions:

```text
current capture READY + history EXACT        → MCL READY
current capture READY + history DEGRADED_GAP → MCL DEGRADED_GAP
current capture not READY                    → MCL FAILED/PENDING
```

`DEGRADED_GAP` can satisfy deployment acceptance only after the receipt is durable and the retained
range reaches its captured high watermark. It is never rendered as `PASS` or `EXACT`, and queries
that require continuous history must expose the gap. Existing ledger events, checkpoints and source
identity are preserved.

## Persistence and operations

Migration `009-poc-change-history-retention-gap.sql` adds only the append-only gap-receipt surface.
It is forward-only, transactional and idempotent. V7 schema integrity recognizes the exact V6
ancestor and preserves every existing row. No reset, resecret, manual DDL, volume deletion or
receipt rewrite is authorized.

`./scripts/prep39083 status` and smoke expose current capture separately from historical
completeness. A durable gap is a persistent warning, while current-capture failure remains a deploy
blocker. K9 V2 source and projector receipts remain independent under ADR-0133.

## Consequences

- Table visibility cannot be changed accidentally by free-form business taxonomy.
- Exact grants and capabilities remain fail-closed; removing TAG authority does not widen an
  ungranted user's view.
- A real Kafka retention loss stays auditable without making the Product permanently undeployable.
- Previous exact history and LKG remain available; continuity is never fabricated.
