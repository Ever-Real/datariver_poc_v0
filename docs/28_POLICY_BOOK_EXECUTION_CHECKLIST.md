# Policy Book and Admin execution checklist

Status values are `DONE`, `PENDING`, `BLOCKED` and `NOT APPLICABLE`. A checked source test is not
target-environment production evidence.

## Phase gates

| Phase | Scope | Status | Exit condition |
|---|---|---|---|
| 1 | RBAC/data-policy DB model and backend contract | READY FOR USER APPROVAL | all Phase 1 gates pass, commit is reviewable, user approves |
| 2 | Retention scheduler/executor boundary | PENDING APPROVAL | Phase 1 approval, TDD implementation and destructive-safety evidence |
| 3 | Admin UI integration and placeholder closure | PENDING APPROVAL | Phase 2 approval, all Admin rows below resolved and browser tests pass |

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
- [ ] Push the Phase 1 branch after the GitHub destination trust/egress approval is accepted.

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

## Phase 2 planned checklist — do not execute before approval

- [ ] Write scheduler eligibility and lease tests before implementation.
- [ ] Define bounded batches, deterministic ordering, lease fencing and idempotent retry.
- [ ] Require exact ACTIVE policy/hash, expiry, classification, canonical target version and owner.
- [ ] Recheck Workspace/resource/subject Legal Holds before claim, archive and destructive action.
- [ ] Use a separate archive port, endpoint, bucket, secret and NOBYPASSRLS runtime principal.
- [ ] Require full content checksum, object version and compliance-retention read-back receipt.
- [ ] Atomically consume approved erasure intent; maker/checker/executor cannot collapse into one actor.
- [ ] Prove crash/restart, duplicate delivery, lease expiry, hold race and stale target fail closed.
- [ ] Keep physical delete/partition drop disabled until target restore and provider conformance pass.
- [ ] Add operations metrics with bounded labels and a kill switch defaulting to disabled.

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
