# ADR-0045: Atomic API-product invocation results

- Status: Accepted
- Date: 2026-07-24
- Owners: Product, Data Governance, Security, Data Architecture

## Context

API-product invocation previously inserted and committed one usage row before it checked the
surface contract, read the pinned Knowledge release or built the response. Request RLS attributes
are transaction-local, so that commit also removed the Workspace and Subject context before the
Knowledge read. A first request could therefore consume quota and then fail as if the governed
release did not exist, while a same-key retry followed a different transaction path.

The legacy invocation key was bound only to a grant. It did not bind the payload, caller, effective
permission scope, product version or release, and no completed result was stored. One OAuth client
identifier can also be shared by several human browser users. Client-only binding is therefore not
an entitlement boundary and could disclose a result produced at another Subject's clearance.

Finally, monthly quota can be as high as 100 million calls. Counting the entire month's ledger for
every request is not an acceptable low-resource execution plan.

## Decision

### Exact consumer identity

A new consumer grant is `SUBJECT_CLIENT_V2` and binds all of the following:

- one active Workspace membership whose `job_function` is `SERVICE_ACCOUNT`;
- the Subject's immutable OIDC issuer;
- the token authorized-party/client identifier;
- one published product version, its fixed scopes and classification ceiling.

Legacy client-only grants remain honest `LEGACY_CLIENT_V1` evidence and cannot invoke the V2
result-bearing surfaces. When an owner explicitly creates the same product-version/client grant
with an eligible Subject, an active legacy row is bound in place to `SUBJECT_CLIENT_V2`; its grant
identifier and historical usage remain intact and an audit event records the transition. A revoked
legacy row may coexist with a new subject-bound grant because legacy and V2 uniqueness are separate
partial indexes. Invocation still runs the current ABAC decision on every request and replay; the
grant never replaces Workspace membership, current Subject state or policy.

### One bounded transaction

The three current fixed surfaces are local PostgreSQL/in-process operations:

- `SNAPSHOT_V1`;
- `NEIGHBORS_V1`;
- `CHAT_LOCAL_V1`, which remains deterministic and makes no provider call.

For these surfaces only, one request transaction:

1. authorizes the current Subject;
2. locks the published product, current version and exact grant in that stable order;
3. uses PostgreSQL time to recheck service Subject, issuer, client, grant state/period/scope,
   classification, current version and governed release lineage;
4. computes a request binding over Workspace, Subject, issuer/client, effective permission
   fingerprint, grant/product/version/graph/release, release/contract hash, surface/scope and the
   normalized typed payload;
5. returns a stored completed result for the same key and exact binding without executing the
   surface again, or rejects a changed/legacy binding;
6. resolves and share-locks the active retention rule, then checks the rolling-minute ledger and
   the current UTC-month aggregate;
7. builds and validates the typed response while the same RLS context and locks remain active;
8. atomically inserts one immutable usage ledger row, one classified result row and the monthly
   aggregate update, then commits once.

Any contract, release, execution, timeout, serialization, size or persistence failure rolls the
transaction back and consumes no quota. Replay reauthorizes current state but does not consume
quota again. Revocation, product-version change, lineage drift, Subject/permission change or result
expiry prevents disclosure of the stored body.

The standalone `POST /api-products/{id}/authorize-invocation` reservation endpoint is retired with
`410 Gone`; authorization without a completed result must never consume quota.

External LLM or provider calls are prohibited inside this lock-holding transaction. A future
provider-backed Sharing surface requires a durable reserve/execute/settle worker design with
leases, rather than extending this unit of work across the network.

### Canonical input and result bounds

The request ID and idempotency key are evidence/correlation inputs but are excluded from the
request-content hash. New raw idempotency keys are not persisted; their SHA-256 value is used in
the unique ledger key. Neighbor edge types are sorted and every defaulted request field is included.

The uncompressed canonical JSON result hard limit is 1 MiB. The existing 500-node and 30-second
contract ceilings remain, and execution uses the smaller product timeout. A response that exceeds
the byte limit is rejected before ledger/result insertion. This bounds replay storage, but does
not by itself bound every intermediate property allocation; representative-volume load evidence
remains a target acceptance gate.

The application role has no direct `SELECT`, `INSERT`, `UPDATE` or `DELETE` privilege on the
invocation ledger, result or monthly aggregate. Fixed `SECURITY DEFINER` functions with a pinned
`search_path` and UTC timezone, current Workspace/Subject checks, exact typed parameters and no
PUBLIC execution privilege own preparation and completion. The deferred exact-result trigger also
runs as a pinned, non-PUBLIC security-definer capability so commit-time validation does not require
granting the application role result-table access. Database constraints enforce complete V2 shapes
and result size, immutable triggers reject evidence mutation, and grant/result foreign keys use
`RESTRICT` rather than cascade deletion. All three HTTP result surfaces send
`Cache-Control: private, no-store`.

### Retention and classification

The minimal ledger/hash is `AUDIT_EVIDENCE`. The full replay body is stored separately:

- Snapshot and Neighbors results are `OBJECT_DATA`;
- Chat answer and evidence are `CHAT_CONTENT`;
- classification is the conservative API-product graph envelope.

Every first execution binds the exact active/effective `POLICY_BOOK_V2` policy and matching class
rules. The immutable ledger stores a separate `AUDIT_EVIDENCE` policy/hash/deadline binding, while
the result row and its mirrored ledger fields store the `OBJECT_DATA` or `CHAT_CONTENT` binding.
DataRiver chooses each rule's **minimum** permitted duration because the body is a duplicate
operational replay artifact and the ledger is minimal audit evidence, not a new source of truth.
Replay stops at the body deadline or when that policy is no longer current. The audit binding and
result hash remain independently governable after the body becomes unavailable.

This decision does not authorize physical deletion, WORM promotion or retention bypass. Governed
purge of expired result bodies remains disabled until the existing Legal-Hold, archive and
maker-checker deletion gates support this target. Target acceptance must report this as an open
retention-execution gate; source tests may prove disclosure expiry but may not claim physical
erasure.

### Legacy evidence

Existing invocation rows become `LEGACY_USAGE_V1`. No Subject, request, result, lineage or retention
facts are fabricated. They continue to count as historical usage in the applicable time window,
cannot be replayed, and a colliding legacy raw key returns a conflict requiring a new key.

## Consequences

- Quota and replay evidence represent completed responses, not attempts.
- Lost HTTP responses can be retried without repeating local work.
- Calls for the same grant serialize while response construction is in progress; calls for
  different grants can proceed concurrently.
- The UTC-month aggregate makes monthly admission O(1); rolling RPM remains a bounded indexed scan
  of at most the configured 10,000 recent calls.
- Existing client-only grants and authorization-only callers must migrate deliberately; explicit
  binding preserves an active legacy grant's identifier and usage evidence.
- Response-bearing storage increases sensitivity and database size; the 1 MiB cap, minimum-policy
  deadline and future governed purge are mandatory parts of the contract.
