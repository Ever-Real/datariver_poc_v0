# Atomic Sharing invocation PRD and execution checklist

## Purpose

Close master-backlog item `R5-BE-05` without turning an API-product invocation into a quota leak,
an RLS bypass, an unbounded result cache or a long database transaction around an external
provider. ADR-0045 is authoritative for the decisions below.

## Canonical ownership and dependencies

| Concern | Canonical owner | Failure posture |
|---|---|---|
| Product/version/grant | PostgreSQL `sharing` schema | fail closed |
| Governed graph/release/lineage | PostgreSQL `knowledge` schema | fail closed; Neo4j is not consulted |
| Workspace Subject and policy | PostgreSQL IAM/AuthZ/Retention | revalidate on first call and replay |
| Usage/result/month aggregate | PostgreSQL `sharing` schema | one transaction or no effect |
| Redis, object storage, Airflow, DataHub | none for invocation | never required by these surfaces |
| External LLM | prohibited in this UoW | future durable worker contract |

## Functional contract

- [x] New grants bind an active `SERVICE_ACCOUNT` Subject, its issuer and exact client identifier.
- [x] Legacy client-only grants remain visible evidence but are non-invokable; an explicit active
      legacy-to-V2 binding preserves its grant identifier and historical usage.
- [x] Snapshot, Neighbors and deterministic local Chat use explicit operation identifiers.
- [x] The authorization-only reservation route returns `410` and records zero usage.
- [x] Typed payload defaults are explicit; Neighbor edge-type order is canonical.
- [x] Same key and exact current binding returns the stored result with the same invocation ID.
- [x] Same key with changed payload, Subject, permission fingerprint, client, version, release,
      surface or scope returns a conflict and does not execute.
- [x] Replay rechecks current ABAC, active Subject/service membership, grant, version, governed
      lineage and unexpired result disclosure.
- [x] Failed validation/read/build/serialization/timeout/size/persistence consumes zero quota.
- [x] Result JSON is at most 1 MiB and the product timeout is at most 30 seconds.

## Persistence and security contract

- [x] `api_invocations` stores immutable minimal binding/quota/result-hash evidence with a
      separate `AUDIT_EVIDENCE` policy/hash/deadline.
- [x] `api_invocation_results` stores the exact typed JSON separately with classification and
      exact retention policy/hash/deadline.
- [x] `api_invocation_monthly_usage` stores one UTC-month aggregate per grant.
- [x] Existing rows become `LEGACY_USAGE_V1` without fabricated fields or results.
- [x] Existing grants become `LEGACY_CLIENT_V1`; new grants are `SUBJECT_CLIENT_V2`.
- [x] Grant and invocation evidence foreign keys use `RESTRICT`, not cascade deletion.
- [x] V2 rows have complete database-enforced shapes; a result is exactly one-to-one with a ledger.
- [x] Evidence/result mutation is rejected.
- [x] `datariver_app` has no direct read/write privilege on the three invocation tables.
- [x] Fixed functions and the deferred exact-result trigger have pinned search paths, no PUBLIC
      execute and exact context checks; invocation functions also pin UTC.
- [x] Product → current version → grant lock order is common to invoke, revoke and publish.
- [x] PostgreSQL `clock_timestamp()` owns validity, rate and UTC-month boundaries.

## Retention contract

- [x] Minimal ledger is `AUDIT_EVIDENCE`.
- [x] Snapshot/Neighbors body is `OBJECT_DATA`; Chat body is `CHAT_CONTENT`.
- [x] First execution binds the current effective active `POLICY_BOOK_V2` body-class and
      `AUDIT_EVIDENCE` rules separately.
- [x] Replay duration is the rule's minimum permitted period.
- [x] Replay is denied at the deadline or after policy/current-evidence drift.
- [x] No test or documentation claims physical deletion, WORM promotion or production retention
      conformance; governed result purge remains an explicit execution gate.

## TDD matrix

### Unit and HTTP

- [x] Binding hash changes for every security/resource/payload dimension and ignores only
      correlation/key values.
- [x] Reordered Neighbor edge sets hash identically.
- [x] Completed replay skips the executor and returns the exact stored document.
- [x] Changed or legacy binding fails closed.
- [x] Invalid surface/template/bounds and result oversize record nothing.
- [ ] Timeout rolls back; rate-limit response has stable `429` semantics.
- [x] Authorization-only route is `410`.
- [ ] Grant creation rejects missing, human, inactive, expired or cross-Workspace consumer Subjects.

### Actual PostgreSQL and concurrency

- [x] First app-role call retains transaction-local RLS through Knowledge read and completion.
- [ ] Missing/wrong Workspace or Subject context cannot prepare, complete or disclose a result.
- [x] App direct `SELECT/INSERT/UPDATE/DELETE` on invocation tables is denied.
- [x] Same key/same binding concurrency executes once, stores once and returns equal results.
- [x] Same key/different binding concurrency yields one success and one conflict.
- [x] RPM=1 and monthly=1 concurrent boundaries admit exactly one different-key request.
- [x] Rolling 59/61-second and prior/current UTC-month boundaries use database time.
- [ ] Every injected precommit failure leaves ledger/result/month aggregate unchanged.
- [x] Response-loss retry replays and revoked grant or changed Subject/issuer denies disclosure.
- [ ] Expired grant, new current version, corrupt lineage, changed permission fingerprint and
      expired/policy-drifted retention deny disclosure in one actual-PostgreSQL matrix.
- [ ] Invoke/revoke/publish interleavings terminate without deadlock and expose only a wholly valid
      old or new state.
- [x] Legacy usage still contributes to the matching time window but cannot replay.

### Migration and source gates

- [x] Additive `0054 → 0055` preserves legacy rows and installs exact grants/functions/triggers.
- [x] Downgrade refuses while V2 evidence/grants exist and restores the legacy schema/privilege
      contract when neither exists.
- [x] Empty canonical `0001` and additive head have matching metadata and controlled SQL.
- [x] Canonical generation is byte-identical on two runs and `alembic check` is clean.
- [x] Ruff format/lint, strict mypy, relevant/full Pytest and `scripts/verify_static.py` pass.
- [x] Frontend type/lint/test/build pass for the exact consumer-Subject grant form change.
- [x] Independent data/security/test and final P0/P1 audits are dispositioned.

## Executed local evidence — 2026-07-24

- Whole backend: `1,417 passed / 93 environment-gated skipped`; Ruff format/lint, strict mypy over
  `374` files and static verification passed.
- Focused source: `37` unit/persistence tests passed.
- Isolated PostgreSQL 17: the repository-owned clean-room harness passed `9` atomic invocation
  tests, including exact replay,
  same/different-key concurrency, zero-usage failure, app-role denial, immutable/orphan evidence,
  oversized invalid JSON rejection before parse, membership-lock serialization, concurrent
  RPM/month quota and DB-clock boundaries, legacy usage/replay, permission/product/retention drift
  and independent audit/body retention bindings.
- Migration: additive `0054 -> 0055` preserved three seeded legacy invocation IDs, honest
  `LEGACY_USAGE_V1` evidence and exact Jan/Feb UTC-month sums without a fabricated result. Empty
  canonical `0001 -> 0055`, no-evidence downgrade, evidence downgrade refusal and seven
  fail-closed RLS/trigger/role-assumption/role-attribute/object-owner probes passed; `alembic check`
  is clean.
- Canonical `0001`: two identical generations, SHA-256
  `ffc0abb58b3f4550bcc5d1524ffd9cd954076d0bf73112cab19fc7b3252e7c2f`.
- Frontend: TypeScript, zero-warning ESLint, `46 files / 244 tests` and production build passed.
- Reproduction: `DATARIVER_SHARING_VERIFY_CONFIRM=1
  scripts/verify_atomic_sharing_postgres.sh`; it refuses a pre-existing container, uses only fixed
  disposable databases/roles, keeps secrets in a mode-0600 temporary directory and removes the
  container and secrets on exit.
- Independent closure: final SQL/security, persistence/test and governance/traceability re-audits
  each reported `P0=0`, `P1=0` after the trust-root and seeded legacy-backfill P1 findings were
  corrected and rerun.

The still-unchecked source-matrix items above are explicitly transferred to follow-up
`R5-BE-05H`; they are not substituted with unexecuted claims or a production-completion statement.
The target-only checks below remain `EXTERNAL_GATE`.

## Target-only acceptance gates

- [ ] WSL `linux/amd64` migration and app-role execution.
- [ ] Real Keycloak service Subject, issuer/client binding, revocation and token rotation.
- [ ] Representative graph-property result-size/load/lock-wait/soak evidence on the preparation PC.
- [ ] Accountable retention-operation acceptance for physically purging expired replay bodies.
