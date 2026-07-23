# ADR-0040: DataHub scroll reconciliation and evidence-gated deletion

- Status: Accepted
- Date: 2026-07-23
- Refines: ADR-0007, ADR-0039

## Context

An offset walk over a mutable DataHub search result cannot prove that every asset present when a
reconciliation began was observed. Concurrent insertion or deletion can shift offsets and cause an
existing asset to be missed. Treating that omission as deletion would incorrectly tombstone a
canonical DataHub asset. Offset walking also has a practical ten-thousand-result provider boundary
and does not satisfy the provisional one-million-asset workload.

DataHub v1.6 exposes `scrollAcrossEntities`, but its point-in-time creation setting is disabled by
default. A version match therefore does not prove snapshot consistency. DataRiver must distinguish
safe projection refresh from authority to infer deletion.

## Decision

DataRiver uses one fixed `scrollAcrossEntities` query for `DATASET` entities, deterministic URN
ordering, a bounded page size and a five-minute keepalive. The opaque provider cursor is stored only
in `catalog.sync_runs`; it is never accepted from or returned to a browser, logged, or exposed as a
general GraphQL pass-through. The public sync API retains a monotonically increasing page ordinal.

The first page fixes `expected_total` and `snapshot_consistent`. Every committed page records the
next cursor and distinct `seen_count`. A verified run also freezes the bounded operator evidence
reference, a SHA-256 of the provider origin, expected/allowed versions, enforcement mode and fixed
scroll-query contract, and the observed provider version. A verified first page forces a fresh
version probe instead of reusing the normal capability TTL. A page is rejected if any of those
values or the total drifts, a cursor fails to
advance, progress is absent while unseen rows remain, a URN is duplicated within or across pages, or
the terminal distinct count differs from the first total. Page commits and their complete
idempotency result are transactional, so response-loss replay does not call DataHub again.

Before reading a page from DataHub, the writer acquires a transaction-scoped advisory lock for the
workspace, rechecks the page idempotency key and reserves the ACTIVE run/page. The lock remains held
through the bounded provider call and local commit. Consequently another run cannot fetch a snapshot
in parallel and later apply an older result, and a simultaneous duplicate waits and replays the
committed response. Provider `RESPONSE_TOO_LARGE` halves the requested page size down to one while
retaining the same server-owned cursor. Queue wait, the optional forced provider-version probe,
GraphQL and all adaptive attempts share a fixed, non-configurable 10-second reservation budget. This
expires before both the runtime database's 15-second statement timeout for a duplicate lock waiter
and its 30-second idle-transaction timeout, then rolls back as a retryable dependency failure. Other
failures release or abandon the reservation according to the cursor failure rules.

Cursor expiry or another non-retryable continuation failure abandons the run without tombstones.
A later scheduled run starts from a new first-page cursor. Stale active runs may be abandoned by the
single writer before a new run starts.

Missing DataHub-owned projection rows are tombstoned only when all of the following are true:

1. the provider cursor is terminal;
2. `seen_count == expected_total` and every page reported that total;
3. the process setting `DATAHUB_CATALOG_PIT_VERIFIED=true` was loaded; and
4. `DATAHUB_CATALOG_PIT_EVIDENCE_REFERENCE` identifies accepted operator evidence for this exact
   external deployment; and
5. provider compatibility is fail-closed with `DATAHUB_VERSION_ENFORCEMENT=enforce`.

The default is `false`. Without accepted evidence, a complete refresh still succeeds but returns
`SUPPRESSED_UNVERIFIED_SNAPSHOT`; no missing row is tombstoned. A final, verified reconciliation
returns `APPLIED`, and a continuation returns `NOT_FINAL`.

The Airflow page safety bound is deployment-owned through
`DATARIVER_CATALOG_SYNC_MAX_PAGES` (`1..100002`, default `10002`). At 100 rows per page the default
admits one million assets plus an empty terminal probe. Each task attempt first reads the run's
server-owned public progress and resumes at `next_offset`; an already completed run is not replayed.

## Required activation evidence

The external DataHub owner must prove that point-in-time creation is enabled for the actual search
backend and supported by its exact Elasticsearch/OpenSearch version. The acceptance run must cover
concurrent provider insertion and deletion, cursor expiry, response-loss replay, an exact-multiple
result requiring an empty terminal probe, stable totals and the original URN set. Configuration,
runtime identity, provider version, time, raw result and accountable approval belong in the evidence
reference. Source tests and a DataHub version probe do not satisfy this gate.

## Consequences

- Projection additions and updates remain available when PIT is unverified; only destructive
  inference is suppressed.
- A provider without accepted PIT evidence can leave stale local rows active. This is visible and
  safer than false deletion; operators may rebuild the disposable projection after remediation.
- `catalog.sync_runs` now persists provider cursor, expected total, distinct seen count and snapshot
  assertion. Alembic `0045` abandons legacy active runs whose completion proof cannot be recovered.
- DataHub remains canonical, while the local projection watermark still means only a committed
  local generation and never a provider snapshot certificate.
