# DEV PHASE 1D closeout and gap-reduction evidence

## Baseline

- Observation date: `2026-08-17` (`Asia/Seoul`)
- Authoritative worktree:
  `/Users/everreal/orca/workspaces/datariver_poc_v0/dev-core-t04-validation`
- Branch: `Ever-Real/dev-core-t04-validation`
- Pre-evidence HEAD: `afd27fee2193e2ae35a1292ea6f15383d0ea8225`
- Product SHA: `2f247107d28716aeba3cfe3fa201fb040ac437e3`
- Deployed OCI revision: `2f247107d28716aeba3cfe3fa201fb040ac437e3`
- Authoritative runtime: Node POC, not legacy FastAPI
- Canonical DEV origin: `http://127.0.0.1:39083`
- Web: container health `healthy`; `GET /healthz` returned `ok`
- Git worktree: clean before evidence authoring

The Product source was not changed in this closeout. The already verified bounded enforcement was
held fixed while request hydration, security-grade samples, provider reachability and graph
provenance were investigated. No historical PASS was used after a Product change because there was
no Product change; the source tests and runtime/state observations below were nevertheless rerun at
the exact current Product and deployed revision.

Inspection `admin` was independently re-observed as active, login-enabled, role `admin`, maximum
grade `restricted`, failed attempts 0, not locked, one active session, zero active Table grants and
zero active Responsible-System assignments. Its password was not read, reset, reconstructed or
logged. User browser confirmation remains pending.

Cleanup/state invariants at closeout:

- login-enabled local credentials: 1 (inspection `admin` only)
- active local sessions: 1 (inspection `admin` only)
- active User↔Table grants: 0
- closeout Chat disposable account: inactive, login-disabled, sessions/grants/System assignments 0
- fixed feature-security policy: state version 16, schema version 1, 120 cells, reason
  `Restore reviewed DEV feature security policy`
- MCL ledger/checkpoint/CR-link/source: `46 / 2 / 4 / 2`

No password, session token, subject identifier, Table identity, provider model name or provider
credential is recorded in this evidence.

## PHASE 1D Coverage Matrix

| Surface | Enforcement location | Pre-filter | Canonical surface status | Blocker / boundary |
|---|---|---:|---|---|
| Catalog | request principal hydration + local inventory filter | Yes | `COMPLETE_RUNTIME_VERIFIED` | Current normalized projection only |
| Search | authorized inventory before match/sort/page | Yes | `COMPLETE_RUNTIME_VERIFIED` | Current normalized projection only |
| Tree | authorized inventory before hierarchy/count | Yes | `COMPLETE_RUNTIME_VERIFIED` | Current normalized projection only |
| Detail | current asset check before projection | Yes | `COMPLETE_RUNTIME_VERIFIED` | Unauthorized identity is 404 |
| autocomplete | authorized inventory before term matching | Yes | `COMPLETE_RUNTIME_VERIFIED` | Current normalized projection only |
| facet/count | authorized inventory before aggregation | Yes | `COMPLETE_RUNTIME_VERIFIED` | No raw global totals for non-Admin |
| dashboard | authorized inventory before aggregates | Yes | `COMPLETE_RUNTIME_VERIFIED` | Current normalized projection only |
| Monitoring | `monitoring` feature scope before aggregate | Yes | `COMPLETE_RUNTIME_VERIFIED` | Table-bound monitoring projection |
| Governance | `governance` feature check on Table-bound records | Yes for Table-bound | `PARTIAL` | Unbound documents are `UNBOUND_NON_TABLE_RESOURCE` |
| Vector PG | exact allowed URNs in SQL `WHERE` before distance order | Yes | `IMPLEMENTED_NOT_VERIFIED` | DataHub binding/sample unavailable for external Product E2E |
| Vector memory | allowed candidates before cosine/sort | Yes | `COMPLETE_RUNTIME_VERIFIED` | Focused runtime test passed |
| AUTO | Chat-authorized scope before metadata routing/retrieval | Yes | `PARTIAL` | Authorization boundary verified; actual Product provider E2E not completed |
| Chat context | authorized evidence rechecked before context | Yes | `PARTIAL` | General Chat is intentionally not Table-scoped; metadata E2E remains open |
| citation | citations derived from authorized evidence only | Yes | `PARTIAL` | Exact/mock path verified; actual external Product E2E remains open |
| Lineage | authorize center, then filter each returned neighbor | Center before call; neighbors after provider result | `PARTIAL` | Provider cannot prefilter every traversal/total |
| Neo4j | non-Admin short-circuits to empty graph evidence | Yes, fail-closed | `PARTIAL` | Fail-closed safety is verified; canonical URN provenance is absent |
| Registration | Responsible-System business scope plus Table helper seam | Bounded | `SOURCE_VERIFIED` | Not a general-read scope; no new runtime slice claimed |
| Knowledge | Table-bound seam only | Bounded | `PARTIAL` | Unbound Knowledge objects are not Table ACL resources |
| Quality | route capability and Table helper seam | Bounded | `BLOCKED` | GX `rule → run → result` runtime unavailable |

`COMPLETE_RUNTIME_VERIFIED` above applies to the named local surface, not to PHASE 1D overall.

## AND Truth-table Evidence

The load-bearing helper is `evaluateTableDataAccess` in
`frontend/poc-table-data-access.mjs`; request construction is in `authenticatedRequestContext` /
`buildPocPrincipal`, and route use is through `canReadAsset`, `filterAssetsForPrincipal`,
`getAllowedTableUrnsScope` and `assertAssetMutation`.

Focused tests in `frontend/poc-table-data-access.test.mjs` fix the conjunction:

| Grant | Grade ceiling | Fixed cell | Result |
|---:|---:|---:|---|
| false | allow | allow | DENY |
| true | deny | allow | DENY |
| true | allow | deny/missing | DENY |
| true | allow | allow | ALLOW |

The same focused file verifies malformed identity, unresolved/invalid grade, non-TABLE denial for a
TABLE-only mutation, immediate grant removal, grade downgrade, policy change and Responsible System
having no general-read effect. `frontend/poc-server.auth.test.mjs` verifies that a formerly valid
session is rejected immediately after the current access user becomes inactive. The fixed-policy
tests reject an unknown feature and any non-120-cell shape. The current-Table helper tests preserve
one canonical Dataset/TABLE predicate for Catalog and targeted Admin mutations.

Focused command:

```text
node --test poc-table-data-access.test.mjs poc-authorization.test.mjs poc-server.providers.test.mjs
→ PASS 28/28
```

This is logical `AND`, never grant-or-policy fallback.

## Admin Integrity Evidence

The focused Admin negatives establish the intended split:

- a valid canonical Table may bypass explicit grant, maximum grade and feature data restriction;
- malformed dataset URN and invalid/unresolved grade fail closed in the Table decision;
- a TABLE-only mutation rejects VIEW/non-TABLE input even for Admin;
- unknown routes remain 404 and are not granted by role;
- stale policy/access/state CAS remains 409;
- wrong Origin/CSRF remains 403;
- an inactive current subject remains 403.

No new Admin policy layer was added. Application-wide data access is not an input, route, CAS,
Origin/CSRF or data-integrity bypass.

## no-N+1 Evidence

Small ephemeral instrumentation wrapped the current state-store methods and local projection while
executing the same request hydration/filter path. It did not change Product source or add an
observability framework.

| Canonical Tables evaluated | Grant DB reads | Policy reads | Access reads | Projection reads | Provider calls |
|---:|---:|---:|---:|---:|---:|
| 10 | 1 | 1 | 1 | 1 | 0 |
| 100 | 1 | 1 | 1 | 1 | 0 |
| 1,002 (current full TABLE inventory) | 1 | 1 | 1 | 1 | 0 |

The request hydrates the current access authority, active grants and fixed policy once, then uses
`Set` membership. It does not store a permission snapshot in the session and does not perform one
grant/policy/DataHub query per Table.

## Security-grade Runtime Sample

The current projection contained 2,002 Dataset assets: 1,002 `TABLE` and 1,000 `VIEW`. Exact
canonical grade resolution for the 1,002 current Tables was:

```text
normal       1,002
credential       0
restricted       0
```

Read-only DataHub checks used the exact tag URNs for `credential` and `restricted`, not substring
search. Both tag entities existed, but each had zero current Table relationships. No existing
disposable tagged-Table lifecycle, test-only provider fixture, or safe DEV entity lifecycle was
found. Business Tables were not retagged and no fake production dataset was created.

Status: `SECURITY_GRADE_RUNTIME_SAMPLE_REQUIRED`. The grade-order implementation and focused tests
are verified; an actual canonical higher-grade Table E2E is `IMPLEMENTED_NOT_VERIFIED`.

## Provider Root Cause

The previous `ECONNREFUSED` was separated from Table authorization.

| Stage | Root cause classification | Finding | Current direct contract |
|---|---|---|---|
| Chat | `CONFIGURATION_ERROR` | Web used container-local `127.0.0.1:11434`; the existing host provider was reachable through Docker's host name | POST 200, expected shape |
| Embedding | `CONFIGURATION_ERROR` | Same container-loopback URL drift | POST 200, expected shape |
| Reranker | `CONFIGURATION_ERROR` + `SERVICE_NOT_RUNNING` + `MISSING_REQUIRED_BINDING` | URL drift plus the existing tracked local reranker manager was not running | Existing service started; POST 200, expected shape |

The corrected DEV runtime uses the existing contracts:

```text
Chat/Embedding  http://host.docker.internal:11434/v1
Reranker        http://host.docker.internal:11435/v1
```

Current lightweight re-probes returned 200 for the host provider version endpoint and reranker
health. No provider/model/version was added or upgraded. The temporary attempted Compose
`extra_hosts` edit was removed because Docker Desktop already resolves the reviewed host name; the
tracked Product tree stayed unchanged.

`DATAHUB_GMS_URL` and `DATAHUB_GMS_TOKEN` are absent in the Web runtime. This is a distinct
`MISSING_REQUIRED_BINDING` for direct DataHub-dependent Product E2E, while the normalized local
current projection remains available. It is not reported as an authorization failure.

## Vector / AUTO / Chat

- PostgreSQL vector source uses exact authorized URNs in `WHERE` before vector-distance
  `ORDER BY`.
- Memory vector focused runtime filters unauthorized candidates before cosine/sort; an unauthorized
  exact vector match never enters the ranked result.
- Empty non-Admin scope returns no candidates before inventory/embedding/provider work. Tests also
  prove that the question embedding is not called in this condition, distinguishing empty scope
  from provider unavailability.
- Metadata AUTO, reranking input, context and citations are built from authorized scope. Exact and
  mock-provider tests show no unauthorized identity in evidence or response serialization.
- General Chat remains independent of Table grants when the classified route needs no metadata.

The direct provider contracts are now healthy, but an attempted actual Product Chat E2E was
interrupted after the validation worker proposed an unsafe literal credential. The temporary file
was deleted, the disposable account was disabled and cleaned, the task was marked failed, and no
result from that attempt is counted. Actual Product Chat/AUTO external E2E is therefore
`IMPLEMENTED_NOT_VERIFIED`, not PASS. No Product, container configuration, policy or inspection
admin state was changed by that aborted attempt.

## Neo4j Provenance

Read-only Neo4j inspection found three `PocEntity` nodes. Their only properties were `entity_type`,
`id` and `name`; relationships were one `HAS_INSPECTION` and one `OBSERVES`. No node property held
an exact `urn:li:dataset:(...)` value. No PostgreSQL↔Neo4j identity map, stable DataHub Table key or
proven Table/Column distinction exists.

The safe current behavior remains:

```text
non-Admin metadata graph request
→ no pre-traversal canonical Table provenance
→ empty graph evidence
```

Full traversal followed by hiding is not used. A temporary Neo4j ACL/identity scheme was not
created. Canonical graph identity/provenance should be considered with the existing Phase 4
Knowledge Graph identity work, then implemented only as a separately authorized bounded slice.

## Remaining Provider/Graph Risks

- DataHub lineage authorizes the center before provider calls and filters returned neighbors, but
  the provider cannot prefilter every traversal or total. No raw unauthorized totals are returned
  to non-Admin callers; endpoints whose existence leakage cannot be bounded remain `PARTIAL`.
- Glossary assignments filter Table-bound results and compute non-Admin totals after filtering.
  The general glossary list is an unbound non-Table resource.
- Deleted/current-missing Tables have no authoritative current grade and remain fail-closed for
  non-Admin. No tombstone/history security framework was introduced.
- `VIEW` and `MATERIALIZED_VIEW` are not grantable TABLE identities for non-Admin under the current
  policy.
- Table-bound Governance/Knowledge objects may use the Table seam. Unbound documents are classified
  `UNBOUND_NON_TABLE_RESOURCE`; they are not forcibly mapped to a Table.
- Quality route/menu and Table-helper seams are source-verified, but unavailable GX runtime keeps
  rule→GX→result verification `BLOCKED`.

## Tests

All commands ran at Product `2f247107...`:

| Gate | Result |
|---|---|
| Focused Table/authorization/provider tests | PASS — 28/28 |
| Node POC full suite | PASS — 97/97 |
| Frontend full suite | PASS — 87 files, 592/592 |
| Lint | PASS |
| Typecheck | PASS |
| Production build | PASS; pre-existing bundle-size advisory only |
| Static verifier | PASS |
| Compose no-interpolate render | PASS |
| `git diff --check` | PASS |

## Runtime Evidence

- Product SHA and deployed OCI revision are exact matches.
- Web container health is `healthy`; loopback `GET /healthz` is `ok`.
- Chat, embedding and reranker direct provider request shapes each returned 200 after the bounded
  DEV configuration repair.
- Current DataHub binding remains absent and is explicitly separated from provider health and
  authorization scope.
- Current normalized inventory and exact tag/provenance observations were read only.
- No validation credential remains active; global active Table grants remain zero.

## Regression

The full Node and frontend suites plus state/runtime observations protect login/session, inspection
admin, User↔Table grant, fixed feature policy, System mapping, three-lane CR, Change History, MCL,
Catalog/Search/Tree, Monitoring/Governance, Airflow service routing and 401/403/404 semantics. The
Product tree remained unchanged, so PHASE 1C-4 was not redesigned or repeated.

## AGY Usage

- Orca orchestration Run: `run_ef517dcbe650`
- Provider discovery: Gemini 3.1 Pro High, read only, completed
- Graph discovery: Gemini 3.1 Pro High, read only, completed
- Coverage discovery: Gemini 3.1 Pro High, read only, completed; its report was independently
  source-reviewed rather than accepted verbatim
- Critical DEV repair: requested and effective Claude Sonnet 4.6 (Thinking), authoritative
  worktree/HEAD verified, no unsupported effort option used
- Claude reached an explicit Individual quota exhaustion after the provider repair and partial
  disposable validation. Its ownership was fenced without discarding work.
- Cleanup continuation: requested/effective Gemini 3.1 Pro High; coordinator independently
  rechecked cleanup because the worker summary contained inaccurate admin/session observations.
- Product Chat runtime task: Gemini 3.1 Pro High, failed and not counted after the unsafe credential
  proposal was interrupted.

No duplicate mutating worker or validator was launched. Because Product source did not change, the
existing exact-Product independent Validator was not duplicated; current tests and discovery were
rerun at the same exact Product/deployed SHA.

## Overengineering Check

```text
new tables       0
new dependencies 0
new services     0
new capabilities 0 (still exactly 15)
new frameworks   0
```

No generic IAM/ACL/policy engine, graph policy framework, provider abstraction, session permission
snapshot, N+1 authorization loop, migration, legacy deletion or broad refactor was added.

## Product SHA

`2f247107d28716aeba3cfe3fa201fb040ac437e3` (unchanged)

## Evidence SHA

The Evidence SHA is the separate commit containing this file, `CURRENT.md` and the master backlog;
its exact hash is reported after the commit is created. It is not a Product SHA.

## Canonical Status by Surface

- Local Catalog/Search/Tree/Detail/autocomplete/facet/count/dashboard/Monitoring:
  `COMPLETE_RUNTIME_VERIFIED`
- Request-time AND helper, Admin data/integrity split and memory pre-ranking:
  `COMPLETE_RUNTIME_VERIFIED`
- Security-grade tagged canonical Table E2E: `IMPLEMENTED_NOT_VERIFIED` —
  `SECURITY_GRADE_RUNTIME_SAMPLE_REQUIRED`
- PostgreSQL external vector Product runtime: `IMPLEMENTED_NOT_VERIFIED`
- AUTO/metadata Chat/context/citation actual Product provider E2E: `IMPLEMENTED_NOT_VERIFIED`
- Table-bound Governance/Registration seams: `SOURCE_VERIFIED`; their broader surface remains
  `PARTIAL`
- DataHub lineage/provider traversal and totals: `PARTIAL`
- Neo4j fail-closed safety: `COMPLETE_RUNTIME_VERIFIED`; canonical pre-traversal provenance:
  `BLOCKED`, so the overall Neo4j surface is `PARTIAL`
- Unbound Knowledge/Governance resources: `PARTIAL`
- Quality authorization seam: `SOURCE_VERIFIED`; GX runtime: `BLOCKED`

## PHASE 1D Overall Status

`PARTIAL`

Provider URL drift was repaired and graph/grade blockers were made precise, but higher-grade
canonical runtime, DataHub-bound external vector/AUTO, provider-wide traversal, Neo4j canonical
provenance, unbound resources and GX runtime are not all closed. They are not converted into false
PASS results.

## Next Smallest Slice

The smallest next Product-independent gate is to provide a reviewed DEV `DATAHUB_GMS_URL` and
credential binding plus an already approved disposable/test canonical TABLE lifecycle containing
one exact `credential` or `restricted` tag. Then rerun only the higher-grade AND matrix and actual
external vector/AUTO/citation negatives at the same exact Product/deployed SHA, followed by cleanup.

Neo4j canonical URN provenance should remain a separate later slice aligned with Phase 4 graph
identity. PHASE 1E/1F, migration, GX, Knowledge, Quality, Chat Router redesign and legacy deletion
do not start automatically.
