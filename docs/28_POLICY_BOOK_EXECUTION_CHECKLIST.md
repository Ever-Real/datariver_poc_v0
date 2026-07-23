# Policy Book and Admin execution checklist

Status values are `DONE`, `PENDING`, `BLOCKED` and `NOT APPLICABLE`. A checked source test is not
target-environment production evidence.

## Phase gates

| Phase | Scope | Status | Exit condition |
|---|---|---|---|
| 1 | RBAC/data-policy DB model and backend contract | DONE | all Phase 1 gates passed; user approved on 2026-07-23 |
| 2 | Retention scheduler/executor boundary | DONE | local source/DB gates and independent P0/P1 reviews pass; target activation gates remain blocked |
| 3 | Admin UI integration and placeholder closure | PENDING | Phase 2 exit report, all Admin rows below resolved and browser tests pass |

## Phase 1 checklist

- [x] Inventory current ABAC, classification policy, RLS, Role and Admin assurance boundaries.
- [x] Add Red tests for missing-rule deny, partial-treatment denial and incoherent rule rejection.
- [x] Add typed No/Partial/Full, residency and processing-purpose domain contract.
- [x] Add immutable Role-version data-rule rows with canonical hashes.
- [x] Add normalized current Role assignment and append-only assignment events.
- [x] Record assignment/removal in the membership mutation transaction; record initial Keycloak Role.
- [x] Preserve current Role rules when the pre-Phase-3 Admin editor omits the new field; require an
  explicit empty array to clear rules into fail-closed missing state; reject explicit `null` in both
  runtime validation and OpenAPI.
- [x] Normalize scope arrays before storage and hashing so the immutable hash is independent of
  caller order and exactly represents the stored document.
- [x] Preserve existing membership ABAC as runtime authority and treat legacy markers as
  non-authority; reject manual `datariver-role-*` marker edits that could diverge from normalized
  assignment evidence.
- [x] Match the server marker against the locked Role row, and reject exact same
  Role/version/canonical-access reassignment instead of emitting a misleading `REASSIGNED` event;
  exclude the optimistic expected membership version from that semantic access hash.
- [x] Require recent hardware WebAuthn for Role mutation, bind the high-risk policy-decision ID into
  the outbox event and recheck the actor under membership row lock inside the mutation transaction.
- [x] Add `0041` compatibility migration, forced RLS and least-privilege grants without delete;
  fingerprint column length/timezone/default, CHECK SQL, FK target/delete action, index columns and
  exact RLS policy predicates, and fail closed on malformed all-three state.
- [x] Run a self-contained actual PostgreSQL service/UoW transition and prove exact-Role no-op,
  stale-version and exact SQLSTATE/constraint DB-evidence failure roll membership, current
  assignment, events, outbox and idempotency back together; use a non-transactional DB marker to
  prove the failing event insert was reached.
- [x] Regenerate canonical `0001` twice with no diff and verify the single Alembic head.
- [x] Run Ruff, strict mypy, relevant/full pytest and `scripts/verify_static.py`.
- [x] Verify clean-clone/Compose documentation and arm64/amd64 source parity.
- [x] Commit Phase 1; obtain explicit approval before Phase 2.
- [x] Publish the accumulated Phase 1/2 branch to `origin/codex/admin-policy-rbac`; PR creation and
  merge remain separate review actions.

Executed 2026-07-23 evidence: 804 backend tests plus one environment-gated PostgreSQL test skipped in
the default suite, that PostgreSQL test separately passing against an isolated real database, strict
mypy across 279 source files, Ruff format/lint across 286 files, static verification, 170 frontend
tests plus lint/build, deterministic
generated `0001` SHA-256
`3d0b199681d72965e191f044e36c648c34a725adbe03a8420be03afcc6f3f1b4`, isolated empty-DB
`0001 -> 0041`, live Mac arm64 `0040 -> 0041` and non-destructive compatibility replay,
forced-RLS/grant/constraint inspection, same-name malformed CHECK/RLS-policy rejection, direct
application-role negative grants/RLS probes, self-provisioning actual SQL transition/no-op/rollback
evidence with exact forced-error identity,
current-source API readiness, and a cache-only `linux/amd64` Docker build.
Independent test, security/CI and release reviewers' P1 findings were corrected and rerun. The
actual Windows/WSL target migration and runtime acceptance remain a target-machine gate; no result
here is presented as that evidence.

Nonblocking defense-in-depth remains explicit: the application Role has only bounded assignment
columns plus append-only event grants, but PostgreSQL does not yet force their one-to-one pairing
through a DB-owned function. The normal API has no raw SQL path and the transaction tests cover the
supported UoW; a future function-only write boundary can further limit damage from a compromised app
credential. Additional positive HTTP/real-DB Role CRUD cases are retained in the Phase 3 validation
row rather than overstated as current browser evidence.

## Phase 2 exit checklist — local exit complete; target profile remains off

- [x] Write scheduler eligibility and lease tests before implementation.
- [x] Define bounded batches, deterministic ordering, starvation-free eligibility scanning, lease
  fencing, read-only recovery before every expired-write-lease revalidation, a three-fence
  persistent recovery budget and job-bound idempotent retry.
- [x] Require exact ACTIVE policy/hash, expiry, classification, canonical target version and owner,
  with an explicit V2 class-rule/legacy-deadline mapping.
- [x] Recheck Workspace/resource/subject Legal Holds before claim, archive and final receipt; no
  destructive action exists in Phase 2.
- [x] Use a separate archive port, endpoint, bucket, secret and NOBYPASSRLS runtime principal;
  reconcile roles for existing PostgreSQL volumes.
- [x] Require full content checksum, object version and compliance-retention read-back receipt; fix
  S3 Base64/DB HEX mismatch, bind the stored capability challenge to the actual probe bytes, and
  reuse a command-deterministic locked version before or after an ambiguous PutObject response.
- [x] Commit the exact capability attestation before evidence write, bind its UUID in object
  metadata, require provider `LastModified`, use conditional create with SDK retries disabled and
  prove cold-restart recovery performs no capability probe or PutObject.
- [x] Treat provider `LastModified` as the uncertain whole-second interval `[t, t+1s)`; require the
  exact capability, policy lifecycle, V2 effective interval and execution-authorisation deadline to
  cover the complete interval and fail closed on same-second activation, supersession or expiry.
- [x] Atomically consume approved erasure intent; enforce maker/checker/owner/executor separation in
  both domain and DB evidence and classify the custom manifest as erasure-execution evidence.
- [x] Prove duplicate planning/claim, expired and exhausted lease handling, stale fence, post-claim
  hold race, Role revocation, inactive Subject/Workspace, membership-action drift and stale target
  fail closed.
- [x] Keep physical delete/partition drop disabled until target restore and provider conformance pass.
- [x] Add container-internal operations metrics with bounded labels, distinguish success/retry/blocked
  outcomes, and document and test the default-off switch through the final pre-receipt boundary.

Superseded 2026-07-23 candidate evidence: `835` backend tests passed with the two explicitly gated PostgreSQL
tests skipped by the default run; each gated test then passed against a disposable PostgreSQL 17
database using its real least-privilege roles. The Phase 2 test proved concurrent planning and claim
yield exactly one winner, lease expiry produces epoch 2, the epoch-1 claim loses authority, a hold
placed after claim blocks revalidation, release restores it, and checker Role revocation blocks the
job with destructive effect count zero. A fresh volume migrated `0001 -> 0042`; the additive
`0041 -> 0042` compatibility path and forced-RLS/column-grant inspection also passed. Ruff format and
lint passed over `307` files, strict mypy passed over `290` source/test files,
`scripts/verify_static.py` passed, both base/profile Compose configurations validated, and canonical
`0001` regenerated twice at SHA-256
`8d4d2f36c8f01af3a7694eadac022d6517078ecc20d9fc55f1f7273c958e2ef7`.

That evidence predates the reopened remediation and is not a current-source exit claim. The current
source now passes `865` default backend tests with `28` explicitly gated PostgreSQL cases skipped;
the gated Phase 1 case passes `1/1` and the gated Phase 2 cases pass `27/27` separately against
PostgreSQL 17 with the application, scheduler, archive and owner roles. The final focused retention
subset passes `110/110`. Ruff format covers `299` files, Ruff lint passes, strict mypy covers `292`
source files, static verification passes, and the frontend passes TypeScript, zero-warning ESLint,
`39` files / `170` tests and production build. Fresh `0001 -> 0042`, stripped additive
`0041 -> 0042`, malformed same-vocabulary source-CHECK rejection, base/profile Compose parsing and
POSIX shell syntax pass. Canonical `0001` regenerates twice at SHA-256
`24bbb8c8d895ab20d65dffb39783ee62562e7ea3b140477eee418dd3277fcc7a`. A separate PostgreSQL 17
existing-volume rehearsal applied `0042` before scheduler/archive roles existed, then ran the actual
role reconciliation. It exposed and corrected a SQL-heredoc comment defect, after which NOBYPASSRLS,
allowed SELECT/INSERT/bounded UPDATE, absent broad UPDATE/DELETE and direct DELETE denial all passed.
The final PostgreSQL run additionally proves every expired lease enters reconciliation before
governance drift, recovery lookup failures stop after three persisted fences, and a cold process
links the exact pre-write attestation/receipt with zero additional provider writes.
This Mac host has no
`pwsh`, so final PowerShell parsing remains part of the Windows/WSL target gate.

The profile remains OFF. No maintained WORM target was supplied, so real provider conformance,
off-host restore, WSL `linux/amd64` crash/low-resource soak and operations-owner acceptance remain
external gates. Source-level review can only approve the disabled archive-only code boundary; these
gates still block activating the profile in that environment and can never authorize deletion.
Independent security and contract reviews found no remaining P0/P1 after the recovery, exact-version
read-back and whole-second policy-boundary remediations. The accepted local scope keeps separate
aggregates/roles and the terminal `ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED` state. Before HA scale-out,
operators must also bind the configured worker-principal fingerprint to independently verified
provider identity evidence and rehearse simultaneous same-workspace capability probes; these are
nonblocking local-source risks, not production acceptance.

Phase 2 implementation was committed as `ca24c07` and published on
`origin/codex/admin-policy-rbac`. This is source publication only; it is not a PR, merge, release or
target-profile activation.

## Admin function inventory and Phase 3 plan

| Area / function | Current backend | Current UI | Planned validation or implementation |
|---|---|---|---|
| Admin eligibility and `/admin/me` | Implemented | Implemented | negative tests for non-admin, expired/service/weak assurance |
| User bounded list/search | Implemented | Implemented | cursor/page bound and no cross-workspace counts |
| Governed Keycloak user creation | Implemented, optional | Implemented | provider rollback/retry and normalized Role evidence |
| User detail/access document | Implemented | Implemented | stale ETag, self-edit and last-two-admin negative tests |
| Role list/create/update/deactivate | Phase 1 contract implemented | Existing editor lacks new rules | add four-class rule editor and missing-rule warning |
| Role assignment/removal | Phase 1 normalized evidence | Existing selector | display exact Role version and evidence status |
| Manual/fallback edit of a Role-bound member | Backend deliberately rejects reserved markers | Existing editor can submit the marker and receive a fail-closed error | Phase 3 must disable the manual form, explain that Role removal is required first and regression-test the transition |
| User profile edit from Admin | No dedicated contract | Placeholder | define bounded identity/profile contract or explicit unavailable state |
| User-owned table drill-down | Summary count only | Placeholder | server-paged authorized table endpoint; never load all rows |
| User change-request drill-down | Summary count only | Placeholder | server-paged authorized CR endpoint |
| Membership renewal | Implemented | Implemented | requester/checker/expiry race regression |
| System Developer/Steward assignments | Implemented | Implemented | full replacement, priorities and lane-separation regression |
| Classification Search/Chat policy | Implemented | Implemented | policy generation/cache revocation negative tests |
| RESTRICTED explicit grants | Implemented | Implemented | scope/expiry/revocation and no-Chat regression |
| Inference provider approval/revoke | Implemented | Implemented | immutable profile and credential non-disclosure regression |
| Password fallback workflow | Implemented, optional | Implemented | two-person, five-minute, one-use and self-change negative tests |
| System Settings inventory/versions | Implemented | Implemented | deployment-managed versus development-write state clarity |
| System Settings SAVE/TEST/ACTIVATE | Development only | Implemented | fixed probe, secret-reference and restart-required states |
| Retention policy | Implemented review only | Implemented | Phase 2 execution status/evidence; no implied deletion |
| Legal Hold place/release | Implemented | Implemented | hold precedence and independent release evidence |
| Erasure request/review | Implemented, non-executing | Implemented | Phase 2 consume/execution evidence kept separate |
| Metadata change audit search/export | Missing bounded API | Disabled placeholder | define masked, paged, immutable evidence query/export |
| Security audit search/export | Missing bounded API | Disabled placeholder | define separately authorized masked query/export |
| Enterprise dictionary projection | Read vocabulary exists | Read/client export only | define canonical mapping CRUD, approval and server export or mark out of scope |
| Monitoring links | Implemented via settings | Implemented | URL allowlist/sandbox/degraded state tests |

## Phase 3 UI rules

- Every table is server-paged/cursor-bounded; closing or changing a filter aborts and discards stale
  requests. The browser never accumulates the enterprise catalog or audit history.
- Disabled functionality names its missing API/assurance/configuration. It never displays fabricated
  rows or a control that silently closes.
- Mutation controls are rendered from server operations but still rely on backend authorization.
- Credentials remain mounted secrets; UI forms accept only approved secret reference names.
- Each row above ends as implemented with tests, explicitly unavailable with reason, or a separately
  approved backlog decision.
