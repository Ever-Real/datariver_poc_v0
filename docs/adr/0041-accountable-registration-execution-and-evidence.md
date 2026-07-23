# ADR-0041: Accountable registration execution and bounded provider evidence

- Status: Accepted
- Date: 2026-07-23
- Refines: ADR-0016, ADR-0017, ADR-0021, ADR-0022

## Context

Manual and BULK registration start with an accountable human action but complete through fallible
object storage, Airflow and DataHub. Passing a DataHub credential or browser OIDC token through this
chain would expose provider authority, make retry identity unstable and couple DataRiver sessions to
provider session lifetime. Treating an accepted provider write as success would also lose the
required evidence that all intended metadata is observable after the write.

The development host is `linux/arm64`; the preparation host is `linux/amd64` and may use externally
operated MinIO, Airflow and DataHub. The contract must therefore depend on typed protocols and
durable evidence rather than container co-location.

## Decision

### Identity and authorization

Only an active human security administrator or Data Steward may enter either Registration
workbench. DataRiver validates its own current OIDC subject and membership before returning any
Registration resource or accepting a command. An initial private/no-store operator-capability call
lets the browser fail closed before loading those resources. A Data Steward can read only their
Manual submission history; a security administrator may explicitly select the bounded workspace
scope.

The initiating human remains the accountable requester in PostgreSQL and audit evidence. Airflow
uses a separate short-lived DataRiver service identity in the `registration-workers` group with
`catalog.sync`; the server-owned DataHub adapter uses a separately scoped service principal.
Neither credential is returned to the browser, stored in a registration payload or delegated from
the human session. This resolves the request for “individual DataHub authentication” as accountable
DataRiver human authorization plus provider-side least-privilege execution evidence, not browser
possession of a DataHub token. A future federated on-behalf-of provider flow requires a new ADR and
must preserve retry, revocation and non-disclosure properties.

### Manual execution

The Manual Save command creates one immutable PostgreSQL intent and one conditional-create S3 CSV
receipt named `UPLOAD_METADATA_MANUAL_YYMMDD_SERIAL.csv`. Concurrent same-key writers cannot
overwrite one another. The worker claims at most one eligible row using database time, a monotonic
lease epoch and a stored lease-token hash. Attempts are capped at 20 and a workspace may have only
one APPLYING submission per asset.

An attempt records one ordered report for every allowlisted aspect it reaches:
`datasetProperties`, `domains`, `globalTags`, `glossaryTerms` and `schemaMetadata`. A failure before
the first provider step may therefore have zero reports, and a later failure retains the reached
prefix without inventing `SKIPPED` provider evidence. Success requires exactly all five expected
hashes to equal a fresh provider read-back. Attempt and aspect evidence is
append-only except for the bounded RUNNING-to-terminal attempt transition. API responses expose
only hashes, versions, states and sanitized failure codes. History uses keyset cursors and returns
25 rows by default, at most 100.

Expired final attempts are terminalized and flushed before a claimant scans onward. Manual work is
FIFO per asset, so a newer edit cannot overtake an older `QUEUED` or `APPLYING` submission for the
same dataset. The database rejects direct terminal-attempt inserts: a new attempt must start
`RUNNING` and exactly match the persisted current submission lease, epoch, token, owner and attempt
number.

### Authenticated worker-call receipts

Manual and BULK Airflow calls use a stable authenticated worker subject, run ID and bounded call
ordinal. `0047` stores only their canonical request/idempotency hashes. The RUNNING call receipt is
created in the same transaction as the canonical claim, and its response is completed in the same
transaction as the canonical state change; a committed replay therefore cannot repeat the effect.
A newer claim proactively completes an expired older call as SUPERSEDED. Attempts alone are not
sufficient evidence: the database requires a distinct, higher canonical claim receipt for every
supersession. Raw run IDs and lease tokens are never persisted.

### BULK execution

Preparation accepts at most 16 MiB and 10,000 rows for the executable
`DATASET_DESCRIPTION_CSV_V1` and `DATASET_DESCRIPTION_XLSX_V1` profiles. The worker uses
database-time claim/retry fencing and publishes
an immutable receipt only after the accepted object identity, SHA-256, parser configuration and
ordered candidate root agree. Candidate pages remain bounded and authorization-pruned.
XLSX ZIP/XML parsing and candidate serialization execute off the event loop. Candidate rows use a
gzip attempt-local spool with a 256 KiB memory threshold, a 64 MiB storage cap and bounded replay
batches rather than a full in-memory tuple.

One V2 dataset-description candidate may preview exactly one current ACTIVE DATASET. The server
re-reads the current typed DataHub aspect, preserves unknown provider fields, binds the immutable
candidate/receipt/object-locator SHA-256 and current target/source evidence in an opaque preview
ETag, and rejects no-op or stale creation. Candidate-to-Change-Request binding, the single
server-authored change item, request and outbox event commit in one unit of work. Unique constraints
prevent one candidate or Change Request from acquiring multiple content bindings. New-table,
new-column and arbitrary-aspect rows remain outside this contract.

### Bounded Change Request and reporting reads

Change Request lists return scalar summaries through keyset pagination. Exact detail is fetched
only after selection and is hard-capped at 200 items, 600 approvals, 200 transitions, 50 rounds and
200 test runs. Apply reports expose at most 200 item results and 20 attempts and require the same
fresh authorized Change Request read. The browser cancels stale history, detail, candidate and
report requests and retains bounded cursor history.

The published `/api/v1/change-requests` full-record response remains available for compatibility.
The current browser uses the additive `/api/v1/change-requests/summaries` keyset endpoint. Switching
requests aborts an in-flight attachment upload and a late response is ignored unless its exact
request generation and request ID remain current.

### Governed provider apply

`0048` makes the DataHub apply lease, attempt and Change Request transition one database-fenced
contract. A completed apply job is excluded before selection and cannot return to RUNNING.
Non-governance roles cannot move a request into or out of APPLYING, APPLIED or APPLY_FAILED.
Exact constraint definitions, trigger configuration and per-column grants are rechecked on
migration re-entry. A completed job bound to a request outside APPLIED is a corruption signal and
blocks the upgrade instead of being silently normalized.

### Private attachment evidence

An attachment POST does not create finalized evidence. `0049` first makes `(bucket, object_key)`
globally unique. The browser sends a fresh upload UUID; `0050` uses that exact UUID to record a
current-authorized, current-round precommit before the object write and returns `202 STARTED`. The
app role cannot directly UPDATE the intent or INSERT the attachment.

The existing upload role remains BYPASSRLS for its older cross-workspace duties, so it receives no
table privilege at all on the attachment intent ledger. It can only execute a SECURITY DEFINER
`FOR UPDATE SKIP LOCKED` function that returns one due STARTED intent, followed by bounded
attestation/defer functions. It verifies provider HEAD metadata, reads at most 10 MiB of bytes and
recomputes the full SHA-256 before STORED may be recorded. This table-privilege boundary remains
effective even when that role bypasses RLS.

The initiating human then finalizes through the app function. That transaction locks and rechecks
the current membership/action/deny rules, classification clearance, System/Domain scope, TEST
Developer assignment, catalog target binding and exact CR version, revision round, state and
monotonic time. Only then does it atomically insert the immutable attachment and move the intent to
FINALIZED. Replaying a finalized request after a lost response repeats those current checks and
returns the existing immutable attachment.

Ambiguous object-store outcomes are never blindly deleted. The exact client UUID lets the browser
recover a lost POST through the individual private/no-store status endpoint. An explicit recovery
list requires the current round and filters `STORED` in SQL before its ten-row bound, preventing old
rounds from starving current work without exposing bucket or object key. Network, 408 and 5xx
delivery results are treated as ambiguous; deterministic 4xx responses are not replayed. Polling
stops after 20 reads or 120 seconds, pauses while the document is hidden and aborts on request
context cancellation. Partial recovery refreshes successful rows and reports the remaining error.
Selection is capped at 10 files, 10 MiB each and 32 MiB aggregate.

## Migration and activation

Alembic `0046` adds Manual claim fencing, retry scheduling, apply attempts, five-aspect reports,
preparation retry scheduling, typed-binding uniqueness and Change Request keyset indexes. The
evidence tables use forced workspace RLS, owner/Admin/service-reader restrictions, append-only
triggers and column-bounded runtime grants. A partially present or definition-drifted contract
fails closed. Existing APPLYING Manual rows must be quiesced and resolved before upgrade.

`0047` adds immutable worker-call receipts and exact receipt/state-history re-entry checks. `0048`
adds the governance apply lease and terminal-state database fences. `0049` installs the global
attachment object identity, and `0050` installs the attachment precommit ledger, claim/attestation/
finalization functions and exact column/index/constraint/grant contract. These revisions are
forward-only evidence migrations; operators must not guess a downgrade after a failed contract
check.

Database roles must be created by the repository role initializer before Alembic runs. Revision
`0025` additionally requires the configured PostgreSQL export-password secret file; a blank-host
bootstrap that omits either prerequisite is invalid.

## Consequences

- DataHub is still the canonical applied metadata provider; PostgreSQL stores intent, workflow and
  verification evidence.
- Airflow is a scheduler, not a source of truth. A disabled or unavailable DAG leaves durable work
  queued and visible.
- Manual and BULK Airflow calls carry a stable run ID plus bounded call ordinal. A committed
  run-call response is replayed for 24 hours after authentication/authorization, while pre-commit
  crashes remain governed by the canonical lease and provider reconciliation.
- Attachment finalization depends on the upload worker. If it is stopped, the durable intent
  remains STARTED and queryable; it is not shown as a finalized attachment.
- A post-write object integrity mismatch may leave an unreferenced object for operator
  reconciliation. A bounded read-only DB/S3 reconciliation utility classifies exact references,
  missing references, mismatches and unreferenced exact-metadata candidates, but never deletes or
  mutates either side. The application does not issue an unsafe unconditional delete that could
  remove a concurrent replacement.
- Current local source, PostgreSQL and isolated MinIO checks do not satisfy the target gate.
  Acceptance still requires exact-commit OIDC multi-role journeys and real external
  Airflow→DataRiver→DataHub five-aspect read-back plus target MinIO/S3 conditional-create, HEAD,
  full-read-after-write and checksum conformance on the preparation topology.
