# ADR-0126: Node POC security hardening, mapping authority transition, and fixed feature policy

- Status: Accepted for PHASE 1C-2H and PHASE 1C-3 management state
- Date: 2026-08-16
- Owners: Product, Application, Data, Frontend, Operations
- Preserves: ADR-0125 exact Table ↔ System binding and the PHASE 1A/1B session/capability boundary

## Context

The authoritative DEV runtime is the Node POC. Authentication remains the local opaque-session
adapter, while the existing access document remains the sole User/Role/Responsible-System authority.
PHASE 1C-2 added an explicit `poc_user_table_grants` domain relation and a user
`max_security_grade`; it intentionally did not activate cross-feature Table filtering.

This slice hardens four existing contracts before introducing a small, fixed feature security
matrix. It does not create IAM, an ACL engine, a permission database, a policy language, or a new
service.

## Security-grade decision

One backend helper owns the complete product ordering and tag decision:

```text
normal (0) < credential (1) < restricted (2)
```

Exact normalized `restricted` tag identity wins over exact `credential`; unrelated or substring
lookalikes remain `normal`. A supplied invalid grade is rejected with a typed 400 error. The access
document, Table/System candidate projection, and future data decision consume this helper. The
browser receives a canonical machine value and only renders the Korean label; it is not an allow/deny
authority.

## Current DataHub Table decision

Catalog normalization and Admin mutation confirmation share one pure DataHub Dataset contract.
A current Table requires the exact requested dataset URN, `type=DATASET`, at least one required
Dataset aspect (`properties` or `schemaMetadata`), and a normalized kind of `TABLE`. `VIEW`,
`MATERIALIZED_VIEW`, deleted/ghost/aspect-less/malformed entities and mismatched URNs are not current
Tables. Admin grant/mapping writes use targeted current-provider confirmation and fail closed when the
provider is unavailable. Catalog reads may retain their existing bounded last-good availability
contract, but a last-good row is never mutation confirmation.

## Admin and session invariants

Access/core writes retain the PostgreSQL transaction, advisory lock, row lock, and version/CAS
contract. Concurrent updates based on one access version cannot both commit. The HTTP layer also
prohibits self-demotion/deactivation and removal of the final active application Admin. Credential
password replacement and revocation of every session for that subject remain one state-store
transaction; the memory adapter has the same failure ordering for tests. No role, System, grant, or
grade snapshot is added to a session.

## Exact and legacy System authority transition

The final current Table mapping authority is exact dataset URN ↔ System. The legacy
`system_schema_scopes` representation is compatibility/history only and is not a Table read grant.

| Consumer | Current source | Transition classification |
|---|---|---|
| Admin Table ↔ System management | exact `table-system-mappings-v1` | exact authority |
| Admin User Table-grant filters/display | exact mapping plus Catalog Table inventory | exact authority |
| Catalog/Search/Tree/Detail and provider mutations | legacy schema resolver in `poc-authorization.mjs` | legacy compatibility; PHASE 1D cutover |
| Change History/CR routing and assignee display | legacy schema resolver in `poc-server.mjs` | historical/workflow compatibility; PHASE 1C-4 cutover |
| Registration candidates | current Catalog visibility predicate | legacy-derived compatibility; PHASE 1D cutover |
| Monitoring dashboard/profiles | current Catalog visibility predicate | legacy-derived compatibility; PHASE 1D cutover |
| Knowledge/Quality browser state | capability/core boundary; Catalog references inherit current Catalog filter | mixed seam; PHASE 1D cutover |
| Bootstrap/core compatibility projection | access document/core projection | legacy preservation only; no exact dual-write |
| Tests and historical receipts | both representations | explicit fixture/evidence scope |

The shared resolver contract is:

```text
any exact row exists for Table (including inactive history)
→ exact active rows only, provenance EXACT

no exact row exists and compatibility fallback is enabled
→ one active legacy result, provenance LEGACY_FALLBACK

otherwise
→ no mapping
```

Exact and legacy rows are never unioned. Exact/legacy disagreement records a bounded conflict flag;
exact wins. Removing the last exact active row does not revive a legacy mapping because retained exact
history proves that the Table has entered the exact authority. Admin exact writes never dual-write the
legacy schema document.

Consumer cutover is intentionally incremental: inventory the consumer, use the shared exact-first
resolver, run source regression, run DEV runtime regression, measure fallback provenance, then retire
legacy dependency only after observed usage is zero. PHASE 1C-4 owns CR/workflow cutover; PHASE 1D
owns Catalog/retrieval cutover.

## POC schema migration audit

The current POC schema contract is not a versioned migration system:

- a clean PostgreSQL volume runs `deploy/poc/postgres-init/001-poc-state.sql` once through
  `docker-entrypoint-initdb.d`;
- an existing volume requires the operator to reapply that idempotent SQL manually;
- Node startup also executes bounded `CREATE TABLE/INDEX IF NOT EXISTS` statements in
  `frontend/poc-state-store.mjs`;
- no migration ledger, ordered migration ID, checksum, schema advisory lock, or changed-checksum
  rejection exists;
- `poc_user_table_grants`, credentials, and sessions currently exist in both clean-install SQL and
  runtime additive DDL.

`IF NOT EXISTS` does not reconcile a changed column, constraint, function, or index definition. The
dual clean/existing paths can drift, and editing `001` provides no evidence that an existing volume
received the change. Deleting or squashing historical SQL would also break clean bootstrap and any
unrecorded existing-volume upgrade path.

Therefore this task does not implement a migration runner. After the current schema is reconciled,
`001-poc-state.sql` should be frozen as the clean-install baseline. Later DB changes should use
numbered additive `002`, `003`, ... migrations with a minimal ledger containing migration ID,
checksum and `applied_at`, applied under a transaction/advisory lock with already-applied detection
and changed-checksum rejection. That separate slice must prove empty install, current DEV upgrade,
repeat apply, recovery/forward-fix and application startup without data loss. PREP/OPS application is
separately gated.

## Fixed feature security policy

PHASE 1C-3 stores one bounded CAS document in `poc_state` scope
`feature-security-policy-v1`. The fixed vocabulary is eight data-bearing features, five canonical
roles and three grades, exactly 120 boolean cells:

```text
catalog, chat, change, registration, knowledge, quality, monitoring, governance
× viewer, developer, data_steward, manager, admin
× normal, credential, restricted
```

The approved initial policy allows `normal` for role-eligible non-Admin features, denies
`credential` and `restricted` for non-Admins, and allows every grade for Admin. Registration,
Knowledge and Quality are role-eligible only for `data_steward`, `manager`, and `admin`; all other
features are role-eligible for every active role. Admin cells are immutable Allow, and role-ineligible
cells are immutable Deny. The server rejects unknown keys, missing or duplicate cells, non-booleans,
stale CAS, and invariant violations. The UI is a fixed matrix, not a rule builder.

The policy scope stores no User, Table grant, System assignment, free-form expression, inheritance,
or custom Role. Admin account/System/policy consoles are protected by the existing `admin.manage`
capability and are outside the matrix, preventing matrix self-lockout.

PHASE 1C-3 introduces management state and review UI only. PHASE 1D must atomically apply the policy
with explicit Table grant, user maximum grade, and pre-retrieval existence hiding. Until PHASE 1D,
the matrix must not be represented as end-to-end data enforcement.
