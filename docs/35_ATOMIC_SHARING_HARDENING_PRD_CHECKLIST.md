# Phase 6C atomic Sharing hardening PRD and execution checklist

## Purpose

Close master-backlog item `R5-BE-05H` by proving the failure, identity, replay and lock boundaries
left open by Phase 6B. This package does not change the Sharing architecture or schema:
ADR-0045 and revision `0055` remain authoritative.

## Invariants

- A timeout, serialization error or failure at any result/month/commit persistence boundary consumes
  no quota and leaves no invocation or replay body.
- A consumer grant can bind only an active, non-expiring `SERVICE_ACCOUNT` Subject in the same
  Workspace; issuer and client remain part of the invocation binding.
- Fixed database functions reject absent or mismatched Workspace/Subject context before reading or
  writing evidence.
- Replay rechecks the current product version, grant, governed lineage, permission fingerprint,
  active retention policy and body-retention deadline before disclosure.
- Invoke, revoke and publish use the same product-first lock order. A concurrent operation observes
  either a wholly valid old state or a wholly valid new state, never a partial transition.
- Sanitized domain errors and Sharing result responses are `private, no-store`. Quota responses use
  stable problem JSON and an integer `Retry-After`.

## TDD acceptance matrix

| ID | Acceptance check | Result |
|---|---|---|
| H-01 | Contract timeout and non-canonical result serialization roll back; `429` is stable, retryable and non-cacheable | PASS |
| H-02 | Missing, human, inactive, expired-membership and cross-Workspace Subjects cannot create grants or side effects | PASS |
| H-03 | App role cannot prepare or complete with missing/wrong Workspace or Subject context and has no direct evidence-table privilege | PASS |
| H-04 | Injected result insert, monthly aggregate write and deferred commit failures leave ledger/result/month counts at zero | PASS |
| H-05 | Permission, current version, expired grant, corrupt lineage, superseded policy and expired result deadline deny replay without executing | PASS |
| H-06 | Invoke-first and mutation-first revoke/publish interleavings are proven with `pg_blocking_pids`; they terminate without deadlock or partial evidence | PASS |

## Executed local evidence — 2026-07-24

- Focused source tests: `39` passed (`38` atomic domain/persistence plus one HTTP problem-response
  contract).
- Isolated PostgreSQL 17: `13` tests passed through the repository clean-room harness. The suite
  includes three precommit fault points, the complete grant-Subject negative matrix, missing/wrong
  security context, result-expiry and state-drift replay denial, exact RPM/month quota behavior and
  both directions of revoke/publish interleaving.
- Whole backend: Ruff format/lint, strict mypy over `374` source/test files, static verification and
  `1,419 passed / 97 environment-gated skipped`.
- Whole frontend regression: TypeScript, zero-warning ESLint, `46 files / 244 tests` and production
  build passed; Phase 6C changes no frontend source.
- Schema/migration: no schema change. The harness rechecked canonical/additive/downgrade paths,
  `alembic check`, and canonical SHA-256
  `ffc0abb58b3f4550bcc5d1524ffd9cd954076d0bf73112cab19fc7b3252e7c2f`.
- Final independent SQL/security, persistence/test and traceability reviews each report `P0=0`,
  `P1=0`. The reviews found and closed a strict-mypy cleanup error and a UTC-rollover
  `Retry-After` overstatement before the focused Phase 6C commit.

## External gates

- [ ] Run the exact release on the preparation PC under WSL `linux/amd64`.
- [ ] Exercise real Keycloak service-Subject provisioning, issuer/client binding, revocation and
      token rotation with accountable identities.
- [ ] Capture representative target graph-size, lock-wait, latency, load and soak evidence.
- [ ] Implement and accept the governed physical purge path before claiming result-body erasure or
      production retention conformance.
