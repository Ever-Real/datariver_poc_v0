# DEV PHASE 1C-2H / PHASE 1C-3 security hardening runtime evidence

## Identity and scope

- Fresh observation: `2026-08-17T00:11:06+09:00` (`Asia/Seoul`)
- Product SHA: `9df97f4975a990819db655b74b09e709dc6d5aad`
- Deployed OCI revision: `9df97f4975a990819db655b74b09e709dc6d5aad`
- Runtime: `datariver-poc-web-1`, image `datariver-poc:local`, health `healthy`
- Environment: authoritative local DEV only; PREP/OPS were not read or mutated
- Git/release: no push, merge, publication, G1/G2/G3/G4 approval, or PREP/OPS action

This evidence covers PHASE 1C-2H and the PHASE 1C-3 **management state**. It does not claim
PHASE 1C-4 CR realignment or PHASE 1D pre-retrieval Table/grade enforcement.

## AGY receipts

- Orca Run: `run_5ee8b27373ef`
- Backend hardening worker: task `task_237f12c2ced7`, dispatch `ctx_d064452bfd67`, AGY
  `gemini-3.1-pro-high`, effort `high`; completed and coordinator-reviewed.
- Provider/migration audit: task `task_9643b985f5d4`; read-only, completed.
- Frontend worker: task `task_0ecfdc8fb794`, AGY `gemini-3.1-pro-high`, effort `high`;
  `AGY_TUI_HUNG_AFTER_TEST`. Its draft was not accepted as evidence until coordinator review,
  contract repairs, full tests, rebuild and runtime browser verification.
- Fresh read-only Validator: task `task_82850b7b7a56`, dispatch `ctx_6243f836400e`, AGY
  `gemini-3.1-pro-high`, effort `high`; Product/runtime verdict `PASS`, no repository files modified.
  The low-level controlled fallback dispatch lacked an Orca lifecycle capability, so the valid
  report message `msg_9268c354c518` was rejected with `dispatch_capability_invalid`; the Task was
  closed by explicit manual recovery preserving the report and limitation.
- `worker-start --agent agy` returned `agent_unconfigured`. The same path was not retried. The
  controlled fallback launched the confirmed AGY model ID directly in the current worktree.
- Claude Sonnet 4.6 was checked once through the launcher earlier in the Run and was not available
  for a usable worker; it was not retried. Gemini 3.1 Pro High remained fixed per assigned task.

## PHASE 1C-2H result

### Canonical security grade

`frontend/poc-access-document.mjs` is the single backend authority for:

```text
normal (0) < credential (1) < restricted (2)
```

It normalizes, ranks and compares grades, rejects invalid grades, performs exact normalized
DataHub tag identity matching, and gives `restricted` precedence when both canonical tags exist.
Substring lookalikes remain `normal`. Frontend code displays the canonical API value and Korean
label; it does not independently decide authorization.

### Current Table decision

`frontend/poc-datahub-current-table.mjs` is shared by Catalog normalization and targeted Admin
confirmation. It rejects VIEW/MATERIALIZED_VIEW, deleted/ghost/aspect-less/malformed entities,
mismatched URNs and unavailable provider confirmation. Catalog GET may retain its bounded last-good
contract; Admin Table-grant/System-mapping mutation requires a current targeted provider result and
fails closed.

### Admin/session invariants

- Last-Admin protection uses the existing PostgreSQL transaction, advisory lock, row/version CAS
  and atomic access/core update. Concurrent destructive Admin changes cannot both commit.
- Password replacement and all-session revocation are one state-store transaction. Tests cover two
  sessions becoming invalid, old-password rejection, new-password success and rollback ordering.
- No role, System, Table grant or grade snapshot was added to the session.

## System mapping authority transition

The current authority is exact dataset Table URN ↔ System. `system_schema_scopes` remains a bounded
compatibility/history fallback, not a Table grant. The shared resolver in
`frontend/poc-table-system-mappings.mjs` applies:

```text
any exact row exists (including inactive history)
→ exact active rows only; provenance EXACT

no exact row exists and compatibility is enabled
→ one unambiguous active legacy result; provenance LEGACY_FALLBACK

otherwise
→ no mapping
```

Exact and legacy results are never unioned; exact wins conflicts; Admin exact writes do not
dual-write legacy scopes. Consumer cutover remains incremental: PHASE 1C-4 owns CR/workflow and
PHASE 1D owns Catalog/retrieval. Retire legacy only after fallback usage is observed at zero.

## Migration audit

- Clean volumes run `deploy/poc/postgres-init/001-poc-state.sql` once through PostgreSQL init.
- Existing volumes require an operator to reapply the idempotent SQL; Node startup also runs bounded
  `CREATE TABLE/INDEX IF NOT EXISTS` in `frontend/poc-state-store.mjs`.
- There is no ordered migration ledger, checksum, schema advisory-lock contract or changed-checksum
  rejection. `IF NOT EXISTS` cannot reconcile changed definitions.
- No migration runner, squash, reset, PREP/OPS apply or schema rewrite was implemented here.
- Recommendation: freeze current `001` as the reconciled clean-install baseline, then introduce
  separately validated numbered additive `002`, `003`, ... migrations with ID/checksum/applied_at,
  transaction/advisory lock and changed-checksum rejection. That slice must prove empty install,
  current DEV upgrade, repeat apply, recovery/forward-fix and startup without data loss.

`POC_SCHEMA_MIGRATION_CONTRACT` therefore remains `PARTIAL`.

## PHASE 1C-3 result

`frontend/poc-feature-security-policy.mjs` owns a bounded fixed vocabulary:

```text
8 features × 5 roles × 3 grades = 120 cells
```

Features are Catalog, Chat, Change, Registration, Knowledge, Quality, Monitoring and Governance.
The server rejects unknown/missing/duplicate cells, invalid roles/grades/features, non-booleans,
stale CAS and invariant violations. Admin cells are immutable Allow; role-ineligible cells are
immutable Deny. Storage is one bounded `poc_state` CAS scope `feature-security-policy-v1`; it stores
no User, Table, System, custom role, expression, inheritance or wildcard.

Exact Admin GET/PUT routes use the existing `admin.manage` capability. The fixed Admin UI shows the
current version, canonical Korean labels, immutable cells, bounded reason and stale-CAS behavior.
The POC browser gateway forwards the exact route. PHASE 1D enforcement is deliberately not active.

## Tests and runtime evidence

Coordinator commands against the final Product:

| Command / probe | Result |
|---|---|
| `npm test -- --run` | PASS — 87 files, 591 tests |
| `npm run test:poc-server` | PASS — 80 tests |
| `npm run typecheck` | PASS |
| `npm run lint` | PASS |
| `npm run build:poc` | PASS; existing `>500 kB` advisory remains |
| focused hardening/policy/adapter suites | PASS |
| `git diff --check` | PASS |
| OCI revision/health inspect | revision equals Product; healthy |
| real browser Admin policy screen | versioned 120-cell matrix rendered; canonical labels and immutable cells verified; edit reason gating/cancel verified without policy mutation |

Final representative DEV runtime matrix, using official bootstrap/Admin API and temporary random
passwords that were never recorded in evidence:

```json
{"policy_cells":120,"policy_stale_cas":true,"anonymous_denied":true,"non_admin_denied":5,"role_count":5,"grade_count":3,"system_variants":3,"table_grant_variants":3,"concurrent_sessions_revoked":true,"old_password_rejected":true,"new_password_accepted":true,"spoof_denied":true,"cleanup":true}
```

Current-Product regression returned 200 for Catalog, Tree, Dashboard, Change History, Change
summary, core state and feature policy. Unknown API returned 404. General Chat returned provider 502,
not 401/403, so the authentication boundary passed while provider availability remains separate.

Sanitized final DB observation:

- credentials: 52 historical rows, 0 enabled
- sessions: 74 historical rows, 0 active
- User↔Table grants: 19 historical rows, 0 active
- feature policy: version 6, 120 cells
- MCL ledger/checkpoints/CR links/sources: 46 / 2 / 4 / 2, unchanged

All validation credentials were disabled, sessions revoked and active grants removed. Access users
and history were preserved.

## Security negatives

- anonymous protected API: 401
- non-Admin policy API across all five roles: 403
- stale policy CAS: conflict
- unknown/missing policy key/cell and mutable Admin deny: rejected
- role/grade/System/Table-grant client spoof: no authority change
- concurrent last-Admin destructive operations: at most one commits; at least one active Admin remains
- password reset: all prior sessions become 401; old password fails; new password succeeds
- unknown API: JSON 404, not SPA HTML

## Inspection Admin decision

The requested weak inspection credential was submitted only to the official operator path. The
frozen minimum-password contract rejected it atomically with reason
`INSPECTION_ADMIN_PASSWORD_POLICY_REJECTED`. It was not written to source, config, migration, seed,
dashboard, log or evidence. The username remains present only as a disabled DEV access/credential
history record; no enabled inspection credential remains. The password policy was not weakened.

## Network and regression

- Web: `127.0.0.1:39083`; Airflow: `127.0.0.1:18888`
- DataRiver-owned PostgreSQL/Redis/Neo4j and connector MinIO remain loopback/private
- no stale DataRiver Node `0.0.0.0` listener was observed
- a real second-host negative probe was not performed: `TARGET_RECHECK_REQUIRED`
- login/session, request principal, access CAS, User↔Table grant, System master, exact mapping,
  Catalog/Search/Tree, Change/CR, Monitoring, Chat auth boundary, Airflow service route and MCL counts
  retained their existing behavior
- provider/GX/vector blockers were not reclassified as authorization failures

## Canonical status

- PHASE 1C-2H: `COMPLETE_RUNTIME_VERIFIED`
- PHASE 1C-3 management state/API/UI: `COMPLETE_RUNTIME_VERIFIED`
- Overall requested task: `PARTIAL` because the exact inspection credential is safely rejected and
  PHASE 1D enforcement is explicitly outside this slice
- PHASE 1C-4: `BACKLOG`
- PHASE 1D: `BACKLOG`

The next smallest implementation slice is PHASE 1C-4 only.
