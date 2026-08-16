# DEV PHASE 1C-4 / PHASE 1D read-only discovery evidence

## Identity and scope

- Fresh observation: `2026-08-17T00:27:42+09:00` (`Asia/Seoul`)
- Repository baseline / preceding Evidence SHA: `e9bcafca8d5859ce06bf58c3bee324b757f20603`
- Product SHA: `9df97f4975a990819db655b74b09e709dc6d5aad`
- Deployed OCI revision: `9df97f4975a990819db655b74b09e709dc6d5aad`
- Runtime: `datariver-poc-web-1`, image `datariver-poc:local`, image ID
  `sha256:178eb3b0affcca18eafcbc3396e422d0334ea22521370e0a37b14263d31d80ea`,
  health `healthy`
- Environment: authoritative loopback-only DEV; PREP/OPS were not read or mutated
- Mutation boundary: no Product source/config/schema/DB/runtime mutation, rebuild, restart, push,
  publication, G1/G2/G3/G4 action, PHASE 1C-4 implementation or PHASE 1D implementation

This document records the autonomous read-only queue after the PHASE 1C-3 closeout. It does not
reuse PHASE 1C-3 runtime PASS as evidence that the discovered PHASE 1C-4/1D behavior is implemented.

## Orca / AGY lifecycle and model receipts

- Orca Run: `run_5ee8b27373ef`
- A fresh launcher check exposed both exact identifiers `claude-sonnet-4-6` and
  `gemini-3.1-pro-high`. No security-sensitive Product mutation was authorized in this queue, so no
  Claude-specific mutating task was started or silently substituted.
- CR / data-enforcement discovery: task `task_0109c8098143`, dispatch
  `ctx_89950a71a97e`, requested and effective model `Gemini 3.1 Pro (High)`, read-only, completed.
- System-authority / migration / backlog discovery: task `task_e9bae20a568f`, dispatch
  `ctx_85d63e77d76b`, requested and effective model `Gemini 3.1 Pro (High)`, read-only, completed.
- Worker reports were supplemental only. The coordinator re-read the authoritative Node source and
  corrected the first report's overbroad statement that CR lifecycle routes were absent: the POC
  lifecycle exists in the browser adapter and persists through a coarse Node state gateway.
- Four previously settled AGY terminals and the two discovery terminals above were closed after
  preserving receipts. Three orphaned, zero-CPU Node test processes in this worktree were terminated
  by exact PID after their settled parent/ownership was confirmed. No active worker in another
  worktree was terminated.
- Orca reported 94 managed worktrees (`90` in progress, `2` completed, `2` in review). None was
  removed because clean/unique-commit/evidence-lineage safety was not proven for every candidate:
  `WORKTREE_REVIEW_REQUIRED`.

## PHASE 1C-4 current behavior and gap

### Existing behavior

- `frontend/src/poc/pocApi.ts:2319-2339` implements browser-side CR intake, revision and list
  operations.
- `frontend/src/poc/pocApi.ts:2437-2533` implements browser-side transitions, approvals, test runs
  and completion checks, then writes the whole projected state through `persistCore()`.
- `frontend/src/poc/pocApi.ts:1517-1548` sends that projection to `PUT /poc-api/state/core` with CAS.
- `frontend/poc-authorization.mjs:45-67,295-355` centrally classifies changed core keys, checks the
  caller capability and preserves hidden/System-scoped rows. It blocks new non-Admin Change records
  without a server-resolved route and rejects client System rebinding.
- Exact Node Change History and CR-link endpoints remain in
  `frontend/poc-authorization.mjs:100-106` and `frontend/poc-server.mjs:965-1105`.

### Gap against the approved policy

- The browser lifecycle uses the compatibility constant `POC_SUBJECT_ID` for approval, test and
  transition actors (`frontend/src/poc/pocApi.ts:2453-2468,2476-2488,2521-2528`) instead of the
  current request principal.
- One `FINAL` approval record currently represents Developer, Data Steward and global Admin
  authorities together (`frontend/src/poc/pocApi.ts:2461-2467`). It is not three independent current
  Developer / Data Steward / Manager lanes bound to the exact responsible System.
- The coarse whole-state replacement validates capability and legacy System scope, but it does not
  own stage-specific current-role/current-assignment lane authorization.
- Change History routing and assignee resolution still consume legacy schema-to-System resolution;
  PHASE 1C-4 owns its incremental exact-mapping cutover.

### Smallest future implementation boundary

Preserve the current CR state/history contract, hashes and append-only Change History linkage. Add
bounded server commands for the existing lifecycle operations, derive the actor from the
request-scoped principal, bind one exact responsible System, and enforce current Developer/Steward
workflow plus three independent final lanes. Do not introduce a generic workflow engine. Product
mutation remains `HOLD_PHASE1C4_PRODUCT_MUTATION_SCOPE` pending the user's next authorization.

## PHASE 1D data-enforcement discovery

### Reusable seams

- The request principal already rehydrates Role, responsible Systems and maximum security grade on
  every request (`frontend/poc-authorization.mjs:149-176`).
- Exact User↔Table grants already persist in `poc_user_table_grants`; Admin management uses the
  current-provider Table predicate (`frontend/poc-state-store.mjs:1068-1148`).
- Catalog search/tree/facet/dashboard paths already call one server predicate before local
  search/count/sort (`frontend/poc-server.mjs:2196-2318`). This seam can consume the future effective
  Table decision without changing feature architecture.
- The fixed feature policy is one bounded 120-cell CAS document; it is management state only.

### Open enforcement gaps

- `frontend/poc-authorization.mjs:189-227` still treats Responsible System / legacy schema mapping as
  Catalog read scope. Viewer retains global System read. The request decision does not load or test
  the current subject's explicit Table grants, calculated Table grade or fixed feature-policy cell.
- Vector SQL ranks the whole current embedding generation before any principal filter
  (`frontend/poc-state-store.mjs:1368-1405`); only afterwards does
  `frontend/poc-server.mjs:3737-3762` filter an over-fetched ranked list. PHASE 1D must constrain the
  candidate set before vector ordering/limit in both PostgreSQL and memory adapters.
- Neo4j executes an unrestricted `MATCH ... LIMIT 100` traversal
  (`frontend/poc-server.mjs:4246-4270`). Non-global callers currently receive no graph while global
  callers can receive the full projection (`frontend/poc-server.mjs:3856-3868,5143-5145`). A
  server-owned node-to-Table identity seam and query-time allowed set are required; a post-LIMIT
  filter is not equivalent.
- Chat builds the LLM context directly from the current evidence list
  (`frontend/poc-server.mjs:3901-3927`). The effective Table decision therefore must precede
  retrieval/ranking/traversal and context construction.
- Change/Monitoring/Governance reads still use legacy Responsible-System-derived visibility instead
  of explicit Table grant + grade. Registration/Knowledge/Quality largely persist virtual
  browser/core state and must revalidate every referenced Table URN at the server hydration/command
  boundary. Responsible System remains an additional workflow constraint only where approved.

PHASE 1D remains `BACKLOG`; the read-only discovery is complete, but no cross-feature enforcement
PASS is claimed. Product mutation remains `HOLD_PHASE1D_PRODUCT_MUTATION_SCOPE`.

## Exact / legacy System authority

`docs/adr/0126-poc-security-hardening-and-fixed-feature-policy.md:52-90` remains accurate:

- exact Table URN ↔ System is the final current mapping authority;
- legacy `system_schema_scopes` is compatibility/history only and never a Table read grant;
- exact rows, including inactive history, suppress legacy fallback; exact and legacy are never
  unioned; exact wins and records bounded provenance/conflict;
- exact Admin writes never dual-write legacy;
- PHASE 1C-4 owns Change routing cutover and PHASE 1D owns Catalog/retrieval cutover;
- physical deletion/retirement is not authorized until measured legacy fallback use is zero.

The shared exact-first resolver already exists in `frontend/poc-table-system-mappings.mjs:120-147`.
No broad consumer cutover or physical deletion occurred in this read-only queue.

## Migration contract audit

- Clean volumes execute `deploy/poc/postgres-init/001-poc-state.sql` once through the Compose-mounted
  `docker-entrypoint-initdb.d` directory (`deploy/poc/docker-compose.poc.yaml:138-152`).
- Existing volumes require the documented operator reapply; Node startup independently executes
  bounded `CREATE TABLE/INDEX IF NOT EXISTS` statements
  (`frontend/poc-state-store.mjs:340-375`).
- Current DEV exposes nine public base tables; no schema-migration ledger table exists. The sanitized
  schema-only fingerprint at this observation was
  `b81ac62705d74c84fc9bbc4b57446324566a4530ae302edc31974e49cd697610`.
- Current `001-poc-state.sql` SHA-256 was
  `b13340ef90abc46f1fd0e16d503640d2acea6d2151628248d6de8a225f4c54d6`.
- There is no ordered migration ID, checksum/applied-at ledger, changed-checksum rejection or
  migration-level advisory lock. `IF NOT EXISTS` cannot reconcile changed definitions.

`POC_SCHEMA_MIGRATION_CONTRACT` therefore remains `PARTIAL`. The safe separate-slice plan is to
reconcile and freeze `001` as the clean-install baseline, then add numbered additive migrations with
ID/checksum/applied-at, transaction/advisory lock, already-applied detection and changed-checksum
rejection. Empty install, current DEV upgrade, repeat apply, recovery/forward-fix and startup without
data loss must all pass before implementation is accepted. No migration runner, squash, delete,
reset or PREP/OPS apply occurred here.

## Fresh runtime observation

- Web health: HTTP `200`; exact OCI revision equals Product SHA.
- Loopback binds retained: Web `127.0.0.1:39083`, Airflow `127.0.0.1:18888`, DataRiver-owned
  PostgreSQL/Redis/Neo4j and connector MinIO on loopback. A second-host negative probe remains
  `TARGET_RECHECK_REQUIRED`.
- Sanitized DB counts: credentials `52` historical / `0` enabled; active sessions `0`; active
  User↔Table grants `0`; active exact Table↔System mappings `0`; MCL ledger/checkpoints/CR links
  `46 / 2 / 4`.
- Bounded CAS observations: access version/bytes `92 / 14132`; feature policy `6 / 10047`;
  Table↔System mapping `4 / 466`.
- No test account, credential, session, Table grant or mapping was created by this discovery.

## Major backlog refresh

Current source/runtime evidence preserves these states:

- Vector provider and Chat/vector deleted-current target: `TARGET_RECHECK_REQUIRED`
- DEV GX / end-to-end Quality integration: `BACKLOG` (existing seams do not prove execution)
- Chat router/refinement: `BACKLOG`; existing authentication boundary is preserved
- Knowledge and Quality feature delivery: `PARTIAL` where browser/seams exist; external/full
  execution remains separately blocked or backlogged
- Timeline initial backfill: `BACKLOG`
- Modular Product Architecture: `BACKLOG`
- secret-file contract, tracked Dockerfile drift, browserless fallback, Vite chunk advisory and
  reproducible deployment acceptance: `BACKLOG`
- actual KST midnight wall-clock: `TARGET_RECHECK_REQUIRED`
- PREP: `TARGET_RECHECK_REQUIRED`; OPS: `UNKNOWN` / not executed

## HOLD queue and canonical status

- `HOLD_INSPECTION_ADMIN_PASSWORD_POLICY_REJECTED`: preserve the frozen password policy; no bypass
- `HOLD_G1_G2_NOT_APPROVED`: no push/publication
- `HOLD_PREP_G3` and `HOLD_OPS_G4`: no target mutation
- `HOLD_PHASE1C4_PRODUCT_MUTATION_SCOPE`: discovery complete; implementation not authorized by the
  current termination boundary
- `HOLD_PHASE1D_PRODUCT_MUTATION_SCOPE`: discovery complete; implementation not authorized by the
  current termination boundary
- `WORKTREE_REVIEW_REQUIRED`: no worktree removal without complete ownership/lineage proof

Canonical statuses:

- PHASE 1C-3: `COMPLETE_RUNTIME_VERIFIED` at Product `9df97f4...`
- PHASE 1C-4: `BACKLOG`; read-only gap discovery complete
- PHASE 1D: `BACKLOG`; read-only enforcement discovery complete
- `POC_SCHEMA_MIGRATION_CONTRACT`: `PARTIAL`
- overall autonomous continuation: `PARTIAL`

The next smallest Product mutation is PHASE 1C-4 only, after the user authorizes that bounded slice.
