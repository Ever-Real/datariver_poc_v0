# DEV PHASE 1C-2 User Table Access Runtime Evidence

- Canonical status: `COMPLETE_RUNTIME_VERIFIED`
- Product SHA: `f78f30fbcf0a5468ec2ce9893d06825ddd030369`
- Fresh observation: `2026-08-16T21:12:35+09:00` (KST)
- Target: authoritative local DEV Node POC
- Evidence SHA: the commit containing this file; reported separately after commit

## Corrective Gate

| Check | Result | Evidence |
| --- | --- | --- |
| Security ordering | `FIX_REQUIRED`, corrected | The Product uses `normal(0) < credential(1) < restricted(2)` and Korean labels `일반 / 대외비 / 극비`. Exact normalized DataHub Tag identity/name matching gives `restricted` precedence over `credential`. Backend tests cover ordering, exact matching and dual-tag precedence. |
| Current Table lookup | `TARGETED_AVAILABLE` | The existing DataHub GraphQL `entities(urns)` helper confirms only selected exact Dataset URNs in bounded batches. A live-provider ghost Dataset shell with no properties/schema aspects was found and is now rejected. Unknown/non-current/non-Table identities fail before a grant or mapping write. |
| Legacy mapping | `ACTIVE` | `system_schema_scopes` remains a Change/Catalog compatibility input. Exact Table↔System bindings are the canonical new mapping for Admin management; no dual-write or deletion was introduced. |
| Table-System CAS | `SAFE_CURRENT_SCALE` | Read-only DB observation: scope `table-system-mappings-v1`, version 4, 466 serialized bytes, one retained binding and zero active bindings. Explicit User↔Table grants were not added to this whole-document CAS. |

## Storage Decision

The Product adds one bounded domain relation, `poc_user_table_grants`, keyed by exact `(subject_id, table_urn)`. It stores no Role, capability, System, grade policy, deny rule or inheritance. This avoids growing the access-document CAS for approximately 1,002 current Tables while leaving the existing access document as the only Role/System authority.

The existing access user gains one additive scalar, `max_security_grade`, defaulting to `normal`. Existing Responsible System assignments and priority are reused. Credentials and sessions remain authentication-only.

The additive DDL is present in both current POC schema paths:

- `deploy/poc/postgres-init/001-poc-state.sql`
- `frontend/poc-state-store.mjs`

No migration squash, legacy table deletion, UUID rekey or broad schema normalization was performed.

## Implemented Admin Functions

Exact `admin.manage` routes:

- `GET/POST /api/v1/admin/users`
- `PATCH /api/v1/admin/users/:subject_id`
- `GET/PATCH /api/v1/admin/users/:subject_id/table-grants`
- `PUT /api/v1/admin/users/:subject_id/credential`
- `POST /api/v1/admin/users/:subject_id/sessions/revoke`

They support human user creation, canonical Role, active/inactive, maximum grade, Responsible System/priority, explicit exact-Table grants, Argon2id credential reset/enable/disable and session revoke. Client Role, subject, System, grant and grade values do not replace the authenticated Admin principal. Last-Admin/self-lockout guards remain fail-closed.

The Admin UI provides search, Schema/System/grade filters, calculated grade and current System display, checkbox/Shift selection, filtered-result selection, grant add/remove, credential/session actions and current Responsible System priority. A separate UI-only marker (`POC_LOCAL_ACCOUNT_ADMIN_V1`) selects this screen without re-enabling the retired misleading `POC_OPEN_ACCESS_V1` feature table.

PHASE 1D cross-feature default-deny filtering is intentionally not enabled in this slice.

## Static Validation

Executed against the Product SHA:

```text
cd frontend && npm run test:poc-server
68 passed, 0 failed

cd frontend && npm test -- --run
86 files, 587 tests passed

cd frontend && npm run typecheck
PASS

cd frontend && npm run lint
PASS (zero warnings)

cd frontend && npm run build:poc
PASS
```

The build retains the existing Vite chunk-size warning as an independent backlog item.

## Authoritative DEV Runtime

Repository, image and running container revision matched exactly:

```text
f78f30fbcf0a5468ec2ce9893d06825ddd030369
```

- Web image digest: `sha256:da9132b0c931ecac70a7b15d5c466c28cd330d9a5e6d8493fc10368df865e499`
- Container health: healthy
- `/healthz`: 200
- Web publish: `127.0.0.1:39083 -> 8080`
- Web-only replacement used `docker compose up -d --no-deps web`; supporting services were not recreated.

Authenticated read smoke:

```text
/auth/me                                             200 JSON
/poc-api/capabilities                                200 JSON
/poc-api/datahub/catalog?limit=5                     200 JSON
/poc-api/datahub/tree                                200 JSON
/poc-api/datahub/facets                              200 JSON
/poc-api/datahub/dashboard                           200 JSON
/poc-api/state/core                                  200 JSON
/api/v1/change-history/events?limit=5                200 JSON
/api/v1/change-history/summary?week_start=2026-08-10 200 JSON
```

Browser runtime verified the local-account Admin list and detail dialog, all three grade labels, Responsible System/read-grant separation text, credential/session section, exact Table access section and filtered-result bulk selection over 1,002 current Table rows. The old `Feature access / OPEN` tab was absent.

## Security / Negative Runtime

Disposable human accounts and passwords were created only for DEV validation. Passwords/cookies were never printed or committed; the temporary secret files were removed. Final credentials are disabled and sessions revoked while access/history identities are preserved.

Observed results:

```text
anonymous protected Catalog                          401
authenticated unknown API                            404 JSON
Airflow exact service route without service token    401
non-Admin direct/spoofed Admin API                    403
unknown or ghost Table grant                         rejected; no active write
duplicate grant                                      idempotent/no duplicate
User A grant != User B grant                         isolated
credential disable                                   login denied; sessions revoked
credential reset/re-enable                           new password verified
explicit session revoke                              immediate
```

Final sanitized DB observation:

```text
credential rows=32, login_enabled=0, active_sessions=0
grant rows=7 (retained lifecycle history), active_grants=0
MCL ledger=46, checkpoints=2, CR-link events=4
```

One non-current Table grant accepted during validation exposed the DataHub ghost-shell behavior. The Product now requires current Dataset aspects; that validation grant was removed and remains only as inactive lifecycle history.

## Regression / Network

- PHASE 1A login/session, PHASE 1B capability/route gate and PHASE 1C-1 System/Table CAS passed their full backend suite.
- Catalog/Search/Tree/Monitoring core and Change History runtime reads returned JSON 200.
- Airflow remains an exact service-token route; missing token is denied.
- MCL ledger/checkpoints and CR-link history counts were unchanged.
- Web, Airflow, Neo4j, PostgreSQL, Redis and external connector ports remain loopback-bound or private.
- No remote host was available for an independent network-denial probe; that target-only observation remains `TARGET_RECHECK_REQUIRED` and does not replace the local DEV containment evidence.

## Scope Boundary / Remaining

- Feature × Role × Security Grade policy is `BACKLOG` for PHASE 1C-3.
- CR responsible-System/approval alignment is not changed.
- Catalog/Search/Chat/Knowledge/Quality/Monitoring/Governance default-deny Table filtering is not activated until PHASE 1D.
- No GX, Chat Router, Knowledge or Quality engine work is included.

## Overengineering Check

- New tables: 1 bounded User↔Table domain relation
- New dependencies: 0
- New capabilities: 0; total remains 15
- New services/containers: 0
- Generic ACL/policy engine: no
- Workspace/OIDC/Keycloak/FastAPI authentication dependency: no

