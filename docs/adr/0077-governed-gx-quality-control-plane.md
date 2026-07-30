# ADR-0077: Governed GX quality control plane

- Status: Accepted
- Date: 2026-07-30
- Owners: Product, Data Architecture, Data Platform, Security/Governance
- Refines: ADR-0001, ADR-0002, ADR-0003, ADR-0006, ADR-0008, ADR-0009, ADR-0010,
  ADR-0013, ADR-0014, ADR-0021, ADR-0024, ADR-0039, ADR-0041

## Context

DataRiver currently exposes only a bounded table-profile summary from DataHub. The fixed asset
query reads `rowCount`, `columnCount`, `sizeInBytes` and `timestampMillis`; it has no field-profile
projection, versioned quality rules, Great Expectations (GX) execution boundary, canonical
validation run, or quality dashboard read model. The React Quality route therefore correctly
reports that no executable contract is available.

DataHub profile observations and source validation answer different questions. A DataHub profile is
provider-owned descriptive evidence that can be stale, sampled or unavailable. A GX validation is
an execution against an exact approved source binding and rule version. Neither Airflow task
success nor a readable DataHub profile proves that the data passed validation.

Running GX inside the API or Airflow would mix browser, orchestration and source credentials, let
orchestrator state masquerade as business state, and couple API availability to source scans.
Accepting arbitrary GX configuration, SQL, Python, datasource URLs, row conditions or plugin names
would also create query-injection, SSRF, resource-exhaustion and code-execution paths.

The checked-in PostgreSQL DataHub recipe is not field-profile evidence. It combines
`profile_table_level_only: true` with `include_field_null_count: true`, a combination rejected by
the pinned DataHub v1.6 profiling configuration. The existing asset query also accepts both
`FULL_TABLE_SNAPSHOT` and `SAMPLE` while omitting `partitionSpec`, so the returned limit-one profile
does not preserve full-versus-sample provenance. Target field-profile collection must therefore be
introduced and verified as a separate contract.

## Decision

### Canonical ownership and context boundary

Add a `Quality` bounded context inside the modular monolith. It owns a future dedicated `quality`
PostgreSQL schema and communicates with Catalog and Integration through application ports and
events; it never writes another context's tables directly.

- PostgreSQL owns rule-set intent, immutable rule versions, review/activation/revocation evidence,
  materialized schedule/due-window state, canonical validation-run state, attempts, normalized
  results, events, score-policy pins and audit bindings.
- DataHub remains canonical for provider-produced profile observations. Catalog owns only a
  bounded, workspace-protected, rebuildable profile projection with explicit provenance and
  freshness.
- GX is a pinned execution adapter and compiler target, not a configuration, workflow or result
  system of record.
- Airflow schedules and dispatches bounded work. Its task state is never a validation-run state or
  quality outcome.
- Redis delivery is a wake-up channel recovered from the PostgreSQL outbox and owns no work.
- Object storage is outside the v1 quality path. GX Data Docs, raw validation documents and quality
  result files are not written to the upload/filefolder bucket.
- Quality results are not written back to DataHub in v1. A future provider-write contract requires
  a separate ADR, typed aspect ownership and read-back evidence.

### Runtime, identity and credential separation

Introduce a separately deployed `quality-worker`. Only that process may load GX and resolve a
source-database credential. The API, browser, relay and Airflow receive no source endpoint,
connection string, source credential or GX filesystem path. DataHub remains a different existing
connector boundary: only the fixed typed DataHub adapter and an optional Catalog Profile collector
may receive its least-privilege read token. The browser, Airflow and quality worker never receive
that token.

Airflow uses a short-lived OIDC service identity with only `quality.dispatch`. A quality worker
uses a different OIDC Subject, purpose group and NOBYPASSRLS database role with only
`quality.execute`. A browser or human token cannot enter either service boundary.

Phase 2 introduces a third, independently deployed `catalog-profile-collector` identity with only
`catalog.profile.collect`, a separate NOBYPASSRLS database role and a fixed projection-write
function. That process, or the existing fixed typed DataHub API adapter when serving an authorized
read, may hold the least-privilege DataHub read token. Neither can resolve a source-database
credential or mutate Quality state. The quality worker never receives a DataHub token.

A deployment-owned, immutable source manifest maps a server-resolved local asset/System/platform
identity to an opaque connection-profile ID, profile version and configuration hash. The worker
manifest alone maps that identity to an allowlisted endpoint and mounted `file:` secret reference.
PostgreSQL may pin the non-secret profile identity/version/hash; it never stores a password, token
or connection string. Historical Admin external-service-profile rows remain audit-only and are not
a runtime resolver. A separate deployment-approved workload profile ID/version/hash pins the
complete source-access hard timeout, per-statement timeout, cancel/connection-close margins,
pool/concurrency and scan budgets. It is part of the immutable Rule Set Version binding.

The source principal is read-only and restricted to approved relations. The connector enforces a
read-only transaction, server-owned quoted identifiers, statement/lock/execution bounds, source
concurrency and workload budgets, cancellation, exact host/port/scheme allowlisting, DNS/IP
revalidation and metadata/link-local/reserved-address SSRF controls. An approved private source
address is permitted only through the exact deployment manifest. Missing workload or egress
approval makes execution unavailable; portable source code supplies no production scan budget.

### Typed rules, lifecycle and authorization

The v1 server contract recognizes only `NOT_NULL`, typed `RANGE` and capability-gated `REGEX`.
Clients submit a local asset UUID, a server-returned field identifier, a rule kind, severity and the
kind-specific typed parameters. They cannot submit an external URN, relation identifier, GX
expectation name, raw kwargs, suite/checkpoint document, datasource, BatchRequest, SQL, GraphQL,
Python, module/plugin path or row condition.

A server-owned, versioned compiler converts the typed rule into an allowlisted GX 1.19.1
expectation. Dynamic custom Expectations, imports, Actions and plugin discovery are disabled.
`REGEX` is advertised as unavailable unless the complete connector/compiler path proves bounded
execution with an approved linear-time-compatible grammar. Backtracking regex execution is not
accepted merely because a pattern length is bounded.

Rule-set edits create immutable versions. Version lifecycle is:

```text
PROPOSED -> APPROVED -> ACTIVE -> SUPERSEDED
         \-> REJECTED
ACTIVE -> REVOKED
```

A rule-set aggregate may be logically `ARCHIVED`; no rule/version/decision row is physically
deleted. At most one version per rule set is ACTIVE. Activation and revocation use optimistic
concurrency, a durable idempotency key and recent deployment-approved hardware WebAuthn. The author
cannot review or activate their own version, and service identities cannot propose, review,
activate or revoke. Activation rejects a version with zero Rule Definitions. Archive requires its
dedicated Action, optimistic fence and idempotency after any ACTIVE version is revoked; because it
is a reversible visibility transition with no evidence deletion, v1 does not add a separate
WebAuthn requirement to archive.

Rule versions select either `MANUAL_ONLY` or one server-advertised, deployment-approved schedule
profile ID/version/hash; clients cannot submit cron text. Activation materializes the canonical
schedule row and due window. The immutable schedule profile resolves to a normalized, versioned
payload with a closed cadence grammar: `FIXED_INTERVAL_V1` uses a bounded integer seconds interval
and UTC anchor; `DAILY_LOCAL_TIME_V1` uses a typed local wall-clock time, IANA timezone and explicit
`EARLIER_OFFSET/LATER_OFFSET` ambiguous-time plus `SKIP/SHIFT_FORWARD` nonexistent-time policies.
Both pin late grace, missed-window policy, bounded catch-up, scheduler evaluator contract version
and tzdb artifact version/hash. PostgreSQL stores this immutable input/history per Rule Set Version;
only schedule state and due cursor are mutable through fixed functions. Airflow does not calculate
them. A pure scheduler evaluates them against database time while holding the schedule row lock.
The missed-window vocabulary is closed:

- `SKIP_MISSED_V1` records and advances past windows for which dispatch database time is later than
  `due_at + late_grace`; non-late due windows are created oldest-first within the caps.
- `LATEST_ONLY_V1` creates only the newest window with `due_at <= dispatch database time`, marks it
  late when beyond grace, records older windows as skipped, and advances past that newest window.
- `CATCH_UP_OLDEST_FIRST_V1` creates due windows in `(due_at, schedule_id, window_key)` order up to
  the per-schedule and dispatch caps; unprocessed windows remain due for the next call.

The receipt pins the database-time cutoff. Skipped count/range hashes and late status are evidence,
not quality outcomes. `late_grace` is a bounded non-negative duration used only by the rules above;
it never changes the canonical UTC window key.

Changing cadence/timezone/catch-up, tzdb/evaluator or source workload-profile ID/version/hash
requires a new Rule Set Version and independent activation rather than editing scheduler state.
Activation atomically makes any prior ACTIVE version/schedule SUPERSEDED/INACTIVE, creates the new
ACTIVE schedule and appends audit/outbox evidence. A partial unique constraint permits one ACTIVE
schedule per Rule Set. Revocation or Rule Set archive atomically makes its schedule INACTIVE. V1
has no mutable per-schedule pause/resume command. Each scheduled Run is unique on workspace,
schedule Version and its evaluator-produced canonical UTC window key.

The dedicated Actions are:

- `quality.read`, `quality.profile.read`;
- `quality.rule.propose`, `quality.rule.review`, `quality.rule.activate`,
  `quality.rule.revoke`, `quality.rule.archive`;
- `quality.run.request`, `quality.run.cancel`, `quality.run.retry`, `quality.operations.read`,
  `quality.audit.read`;
- service-only `quality.dispatch`, `quality.execute` and `catalog.profile.collect`.

These Actions do not replace workspace membership, classification clearance, System/Domain scope,
lifecycle, explicit deny, Policy Book restrictions or forced PostgreSQL RLS. UI role names and
hidden buttons are never authority.

The server creates an immutable target binding from the current local asset, System/Domain,
classification, lifecycle, provider/schema source version and connection-profile
identity/version/hash plus workload-profile ID/version/hash. The browser cannot supply binding
fields. Creation, review, activation, manual enqueue, worker claim immediately before source
access, and result completion revalidate the applicable current target, policy and exact
version/hash.

A manual run additionally reauthorizes its human requester before the source call. A scheduled run
does not impersonate the original author: its current authority is the still-ACTIVE, unrevoked
independently activated version plus the current target/policy and authenticated dispatch/worker
service identities.

### Durable execution and result semantics

Run enqueue, the minimal outbox event, audit binding and idempotent response commit atomically.
Workers claim with database time, `FOR UPDATE SKIP LOCKED`, a monotonic lease epoch, a random token
stored only as a SHA-256 hash, an exact worker identity and an append-only RUNNING attempt. The Run
stores the current attempt ID, lease epoch, lease-token hash, lease owner, `lease_until`,
`heartbeat_at`, `next_attempt_at` and source-start time. Immediately before source access, the
worker renews with database time and freezes a source-start fence and source-access deadline. The
approved hard timeout for the complete source-access window—from the first GX statement until the
source transaction/connection is closed—plus cancel/reconciliation and completion margins must be
strictly less than the frozen remaining lease. Lease renewal is prohibited throughout that window.
Before every GX/source statement the worker rechecks the current control-plane epoch/token/expiry;
the statement receives a source-server `statement_timeout` that also fits inside the remaining
source-access deadline and lease. Thus a stalled old process cannot start a later statement after
its fence changed, and an already running statement is ended by the source server before reclaim.
A new claim cannot start before database time passes `lease_until`. Reclaim atomically terminalizes
the expired attempt as SUPERSEDED, increments the epoch and creates the next attempt. Missing
hard-timeout, per-statement timeout, cancellation or connection-close proof disables execution
rather than allowing overlapping scans. Completion accepts only the exact current
run/attempt/epoch/token/worker/expiry and commits normalized results, summary, attempt, run and
event evidence atomically. A stale worker cannot publish.

Airflow dispatch replay is fenced before a Run necessarily exists. A dispatch receipt is keyed by
workspace, authenticated service Subject and call-ID hash and may represent no work or several
scheduled Runs; a separate ordinal mapping links any created Runs. Under one transaction, dispatch
locks a deterministic keyset no larger than the deployment-approved
`max_due_schedules_per_dispatch`, materializes no more than
`max_created_runs_per_dispatch` unique scheduled-window Runs/outbox rows, advances only processed
`next_due_at` values, and commits the bounded response hash/receipt. These required runtime values
have source-enforced safe maxima but no portable capacity default; missing approval makes
dispatch/scheduling unavailable. An execution-call receipt is separately bound to one exact Run
claim. Neither receipt stores a raw bearer token or external DAG URL.

Execution state and quality outcome are separate:

```text
QUEUED -> RUNNING -> SUCCEEDED
                  |-> RETRY_WAIT -> RUNNING
                  |-> FAILED
                  |-> STALE
                  \-> CANCEL_REQUESTED -> CANCELLED | FAILED | STALE
QUEUED | RETRY_WAIT -> CANCELLED
```

`SUCCEEDED` means the validation execution completed and has exactly one sanitized result for every
Rule Definition in the non-empty active Version; its independent quality outcome is `PASS`, `WARN`
or `FAIL`. `UNKNOWN` belongs to a non-success Run or to an aggregate with no contributing
successful Rule result. Missing/duplicate results cannot complete as `SUCCEEDED`; an expectation
violation is not an infrastructure failure.
`POST .../retries` never reopens a terminal Run. It creates a new idempotent Run with
`retry_of_run_id`, pins the same immutable Rule Set Version, and repeats current target,
authorization, source, schedule/workload and retention checks. The predecessor remains immutable.

Attempt state is the closed vocabulary `RUNNING`, `SUCCEEDED`, `RETRYABLE_FAILED`, `FAILED`,
`STALE`, `CANCELLED`, `SUPERSEDED`. `QUEUED` has no current attempt; Run `RUNNING` and an in-flight
`CANCEL_REQUESTED` point to `RUNNING`; `RETRY_WAIT` points to `RETRYABLE_FAILED`; Run
`SUCCEEDED/FAILED/STALE` points to the matching attempt. Run `CANCELLED` points to no attempt when
cancelled before first claim, `CANCELLED` when cancelled in flight, or `RETRYABLE_FAILED` when
cancelled during retry wait. A SUPERSEDED attempt is never current after reclaim. Only a
`SUCCEEDED` current attempt can own canonical expectation results.

The version payload is immutable, while lifecycle columns may change only through fixed
`SECURITY DEFINER` transition functions with pinned `search_path`, current RLS/authorization,
optimistic fence and idempotency checks. Ordinary roles have no direct version UPDATE. Review
decisions use the closed vocabulary `APPROVE` or `REJECT`; activation and revocation are distinct
high-assurance commands. The activation function changes the prior ACTIVE version to SUPERSEDED,
changes the approved candidate to ACTIVE, transitions schedules, and appends decision/audit/outbox
evidence in one transaction. Append-only Rule command events retain the exact
activate/revoke/archive/supersede actor, assurance and target/schedule/retention hashes.

GX output passes an allowlist sanitizer before any persistence or logging. V1 retains only exact
rule/run/version/source/compiler/GX hashes, boolean success, bounded evaluated/missing/unexpected
counts and percentages, duration, observation time and a bounded failure code. It discards
unexpected rows, values and indexes, rendered/generated SQL, queries, samples, exception text and
connection data. Sanitizer or shape failure is a fail-closed execution failure and persists no raw
result.

### DataHub profile projection

Use a separate fixed GraphQL query/adapter rather than widening the general asset-detail request.
The query accepts only a server-owned URN variable and retains the existing version enforcement,
bulkhead, circuit breaker and response-size bound. It preserves profile kind, profiled time,
observed time, normalized `FULL/SAMPLE/PARTITION/QUERY/UNKNOWN` provenance, provider contract and
source watermark. Raw partition names/specifications are not stored, cached, logged or returned.

The fixed DataHub v1.6 `DatasetProfile` query requests `partitionSpec { type partition }`;
`profileType` is not a field in the pinned schema. The fixed parser maps `FULL_TABLE` with the
canonical full-table marker to FULL, `QUERY` with DataHub v1.6's exact SAMPLE marker or its
sample-row suffix form to SAMPLE, `PARTITION` with a valid bounded partition to PARTITION, and
other valid `QUERY` observations to QUERY. Missing, unsupported or ambiguous input becomes UNKNOWN.
The bounded raw `partition` string is untrusted ingress visible only inside that parser. For
PARTITION/QUERY only, it may compute an
HMAC-SHA-256 fingerprint with a deployment-owned `file:` key and key ID for idempotent provenance.
It then discards the raw string before constructing a DTO. Only the keyed fingerprint/key ID may
leave the parser; an unkeyed digest and raw text are prohibited in storage, cache, logs, traces,
errors or API responses. Unknown or oversized provenance becomes `UNKNOWN/PARTIAL/UNAVAILABLE`.

The v1 normalized allowlist is:

- table: row count, column count, size in bytes and profiled time;
- field: field path, null count/proportion and unique count/proportion.

Non-null count may be derived only when row and null counts refer to the same proven full snapshot.
Sample values, distinct-value frequencies, top values and example rows are never requested,
stored, cached or returned. Min/max/mean/median/stdev, quantiles and histograms remain disabled
until a classification/data-type policy and source workload budget are separately approved.
Contract drift, an oversized response or ambiguous full/sample provenance is explicit
`UNAVAILABLE`/`PARTIAL`, never silently truncated or interpreted as a passing validation.

Profile rows inherit the target classification and System/Domain scope. A DataHub profile is
context and freshness evidence only; it never supplies the GX pass/fail decision.
Snapshot idempotency uses a canonical hash of local asset, profiled time, normalized kind,
provider/query/config/source-watermark hashes, normalized allowlisted payload hash and any keyed
provenance fingerprint. Re-observing the same identity advances only `last_observed_at`; changed
metrics or an HMAC-key rotation creates a new immutable snapshot lineage.

### Dashboard, scoring and client refresh

Every dashboard card, score, count, trend and grid starts from the same authorization-pruned local
asset relation. The denominator contains only currently visible targets. Global totals, hidden
buckets and the difference between global and allowed totals are not returned. Cursors and caches
bind workspace, complete permission fingerprint, policy/generation, System/Domain scope,
rule/profile/source watermark and request shape.

The accepted initial score formula is `UNWEIGHTED_RULE_PASS_RATE_V1`:

```text
evaluated = passed + advisory_failed + blocking_failed
score = pass_rate = 100 * passed / evaluated
```

An aggregate with zero contributing evaluated rules produces `null` and `UNKNOWN`, not zero. Any
blocking failure produces `FAIL`; otherwise any advisory failure produces `WARN`; all evaluated
rules passing produces `PASS`. Weights and business thresholds are not source defaults and require
a new score-policy version.

The current dashboard snapshot first selects the latest terminal Run whose
`rule_set_version_id` equals each authorized Rule Set's current ACTIVE Version at `as_of`. A newly
activated Version cannot inherit a superseded Version's result. A latest `SUCCEEDED` Run
contributes its Rule Definition counts to score; a latest `FAILED`, `STALE` or `CANCELLED` Run, or
no same-Version terminal Run, makes that Rule Set UNKNOWN and cannot be hidden by an older success.
`unknown_rule_set_count` is a Rule Set count, while
passed/advisory-failed/blocking-failed/evaluated counts are Rule Definition counts from the selected
successful Runs. Coverage reports successful evaluated Rule Sets over visible ACTIVE Rule Sets.
Trend data uses bounded completion-time buckets and remains distinct from the current snapshot.

The browser polls only the selected non-terminal run, with bounded backoff, at most 20 reads or 120
seconds, and pauses while hidden. It stops on terminal, authorization/security-context drift,
unmount or bounded failure. Polling expiry does not declare the run terminal. Dashboard-wide
second-level polling and SSE are outside v1.

Capability and cached reads have an independent authorization lease. The server returns a
permission/policy-bound cache scope and a validity no greater than 30 seconds. At expiry the browser
first hides and purges all Quality data, then revalidates capability; it does not keep displaying
the expired snapshot. Visible-tab capability revalidation is an authorization check, not dashboard
data polling. Subject, workspace, security epoch, authorization revision, focus/manual refresh,
`401/403/404` and stale-cursor/cache-scope responses also abort requests and purge Quality memory.
Resource query freshness can never outlive the capability lease, and no Quality response is
persisted in browser storage. The target revocation acceptance bound is therefore 30 seconds in a
continuously visible client, subject to a stricter deployment policy.

### Retention and deletion

Rule versions/decisions, profile snapshots, normalized results and audit evidence use separate
governed `QUALITY_RULE`, `QUALITY_PROFILE`, `QUALITY_RESULT` and `QUALITY_AUDIT` retention kinds.
Rule Sets, Runs, Profile Snapshots and run-independent dispatch receipts are governed roots that
pin the applicable policy ID/version/hash, computed deadline, data kind and resolved Legal Hold
generation/hash. Child versions/rules/schedules/attempts/results/events/receipts either pin their
own kind where it differs or inherit the exact root binding through a composite foreign key.
Dispatch receipts resolve workspace-scoped `QUALITY_AUDIT` holds even when no Run is created.
Quality Rule Sets, Runs and Profile Snapshots are typed resource Legal Hold targets. The Quality
schema migration must extend the retention kind/target allowlists and store
`QUALITY_RULE`, `QUALITY_RESULT` and `QUALITY_AUDIT` pins; the Phase 2 Catalog migration does the
same for `QUALITY_PROFILE`. Creation, claim immediately before source access, and result completion
revalidate the exact policy/hold binding. Drift after source access makes the Run STALE/UNKNOWN and
publishes no canonical result. These bindings and target kinds are enablement prerequisites, not a
later purge enhancement. Until that contract and destructive control plane are implemented,
there is no application, Airflow, worker, object-lifecycle or TTL path that physically deletes,
truncates, detaches or drops quality evidence. Legal Hold and ambiguous hold state always prevent a
future purge. Raw GX values are not retained in the first place.

### Dependency and activation baseline

The approved GX compiler/runtime target is exactly `great-expectations==1.19.1`; automatic minor
upgrade is prohibited. The published package declares Apache-2.0 and Python `>=3.10,<3.14`, which
is compatible in principle with DataRiver's Python 3.12 baseline. Phase 1 may add it only to the
isolated quality-worker dependency profile after the frozen lock, transitive license/SBOM,
vulnerability scan, PostgreSQL driver compatibility and arm64/amd64 offline-artifact checks pass.
The API and Airflow images must not acquire the GX dependency.

PostgreSQL is the only v1 execution datasource. Oracle and every other connector report
`DISABLED_NOT_READY` until a separate driver, dialect, rule-semantic, read-only, workload and live
target contract passes. Validation is full-table only in v1; sampling is not represented as full
quality evidence. A target without an approved full-scan budget is unavailable rather than sampled
implicitly.

Feature capability, the worker and the Airflow DAG are disabled/paused by default. No source query
is allowed until service identities, RLS/roles, source manifest/secret, egress, workload,
retention binding, sanitizer, PostgreSQL migration and crash/reclaim tests have passed.

## Consequences

- Quality intent and evidence remain durable and auditable without making GX, Airflow, Redis,
  DataHub or object storage canonical.
- API latency and credentials are isolated from source scans, while disabled dependencies produce
  honest capability states.
- The strict typed contract intentionally supports fewer GX features than the library exposes.
- Field profiles require a corrected, target-verified DataHub recipe and a new fixed adapter; the
  current recipe and asset query cannot be promoted as evidence.
- Full-table PostgreSQL validation may be unavailable for sources without an approved workload
  budget. The system does not silently weaken such validation by sampling.
- Schema, worker, dependency, Airflow and UI implementation remain Phase 1 and later work. This ADR
  approves their boundary; it does not claim they exist.

## References

- [GX Core overview](https://docs.greatexpectations.io/docs/core/introduction/gx_overview/)
- [GX compatibility reference](https://docs.greatexpectations.io/docs/help/compatibility_reference/)
- [GX 1.19.1 package metadata](https://pypi.org/project/great-expectations/1.19.1/)
