# DEV PHASE 1D autonomous provider and security-grade E2E evidence

## Baseline

- Observation date: `2026-08-17` (`Asia/Seoul`)
- Authoritative worktree:
  `/Users/everreal/orca/workspaces/datariver_poc_v0/dev-core-t04-validation`
- Branch: `Ever-Real/dev-core-t04-validation`
- Pre-evidence HEAD: `d2db04104b7210daa31f6999e8d448f8c3550224`
- Product SHA: `2f247107d28716aeba3cfe3fa201fb040ac437e3`
- Deployed OCI revision: `2f247107d28716aeba3cfe3fa201fb040ac437e3`
- Authoritative runtime: Node POC, not legacy FastAPI
- Canonical DEV origin: `http://127.0.0.1:39083`
- Web: healthy, loopback-bound, `GET /healthz` returned `ok`
- Product source changes in this continuation: none

This continuation held the verified local Table-enforcement implementation fixed. It repaired only
existing DEV runtime bindings, exercised the existing provider and disposable-entity contracts,
and reduced the remaining PHASE 1D gaps. It did not redesign authentication, authorization, Chat,
graph, Knowledge or Quality architecture.

Read-only baseline and post-cleanup observations were refreshed rather than copied from historical
evidence:

- inspection `admin`: active, login-enabled, role `admin`, maximum grade `restricted`, failed
  attempts 0, not locked, one active session, zero Table grants, zero Responsible-System assignments;
- login-enabled credentials: 1; active sessions: 1; active User↔Table grants: 0;
- fixed feature-security policy: version 24, schema version 1, 120 cells, reason
  `Restore reviewed DEV feature security policy`;
- active Table↔System mappings: 0;
- MCL ledger/checkpoint/CR-link/source: `46 / 2 / 4 / 2`;
- current local projection: 2,002 Dataset assets, including 1,002 canonical `TABLE` assets;
- active embedding generation: 2,002 rows under the current provider binding.

The policy version advanced through bounded temporary Allow/Deny verification and exact restoration.
The reviewed cell content is restored: Catalog/viewer is Allow for `normal` and Deny for
`credential` and `restricted`. Historical disabled users and policy versions were not deleted.

No password, password hash, cookie, session token, provider token, subject identifier, disposable
Table identity, provider model name or sensitive metadata value is recorded in this evidence.

## PHASE 1D Coverage Matrix

| Surface | Enforcement location | Pre-filter | Canonical surface status | Boundary |
|---|---|---:|---|---|
| Catalog | request principal + current local inventory | Yes | `COMPLETE_RUNTIME_VERIFIED` | Current normalized projection |
| Search | authorized inventory before match/sort/page | Yes | `COMPLETE_RUNTIME_VERIFIED` | Current normalized projection |
| Tree | authorized inventory before hierarchy/count | Yes | `COMPLETE_RUNTIME_VERIFIED` | Current normalized projection |
| Detail | current identity and Table decision before projection | Yes | `COMPLETE_RUNTIME_VERIFIED` | Unauthorized identity is 404 |
| autocomplete | authorized inventory before term matching | Yes | `COMPLETE_RUNTIME_VERIFIED` | Current normalized projection |
| facet/count | authorized inventory before aggregation | Yes | `COMPLETE_RUNTIME_VERIFIED` | Raw global totals hidden |
| dashboard | authorized inventory before aggregate | Yes | `COMPLETE_RUNTIME_VERIFIED` | Table-bound aggregate |
| Monitoring | `monitoring` Table scope before aggregate | Yes | `COMPLETE_RUNTIME_VERIFIED` | Table-bound read surface |
| Governance | Table helper on Table-bound records | Bounded | `PARTIAL` | Unbound documents are not Table ACL resources |
| Vector PostgreSQL | allowed URNs in SQL `WHERE` before distance order | Yes | `COMPLETE_RUNTIME_VERIFIED` | Current DEV provider/runtime sample |
| Vector memory | allowed candidates before cosine/sort | Yes | `COMPLETE_RUNTIME_VERIFIED` | Focused runtime test |
| AUTO | authorized scope before metadata routing/retrieval | Yes | `COMPLETE_RUNTIME_VERIFIED` | Bounded metadata AUTO path |
| Chat context | authorization-filtered evidence before composition | Yes | `COMPLETE_RUNTIME_VERIFIED` | Metadata path; General remains unscoped |
| citation | citations derived from authorized evidence | Yes | `COMPLETE_RUNTIME_VERIFIED` | Bounded metadata path |
| Lineage | center before call, neighbors after provider result | Partial | `PARTIAL` | Provider cannot prefilter every traversal |
| Neo4j | non-Admin short-circuit before traversal | Yes, fail-closed | `PARTIAL` | Canonical DataHub Table URN provenance absent |
| Registration | Responsible-System business scope + Table seam | Bounded | `SOURCE_VERIFIED` | Not general-read authority |
| Knowledge | Table-bound seam only | Bounded | `PARTIAL` | Unbound resources need their own future policy |
| Quality | route/menu and Table-helper seam | Bounded | `BLOCKED` | GX rule→run→result runtime unavailable |

`COMPLETE_RUNTIME_VERIFIED` applies only to each named bounded surface. PHASE 1D overall remains
`PARTIAL`.

## AND Truth-table Evidence

The unchanged load-bearing helper remains `evaluateTableDataAccess` in
`frontend/poc-table-data-access.mjs`. Request construction reads the current access document,
active exact grants and fixed policy once, then builds Set membership in
`frontend/poc-authorization.mjs`.

The focused source/runtime matrix remains logical AND:

| Grant | Grade | Fixed cell | Result |
|---:|---:|---:|---|
| false | allow | allow | DENY |
| true | deny | allow | DENY |
| true | allow | deny | DENY |
| true | allow | allow | ALLOW |

Fresh focused tests also passed inactive user, malformed identity, unresolved/invalid grade,
unknown feature shape, non-current/non-TABLE identity, immediate grant removal, grade downgrade and
policy Allow→Deny. Responsible System did not affect the general-read decision.

## Admin Integrity Evidence

The disposable higher-grade runtime matrix confirmed that Admin could read a valid current
restricted canonical Table without a grant and despite a normal configured maximum grade. The
unchanged focused negatives still reject malformed/ghost identities, non-TABLE input for TABLE-only
operations, unknown routes, stale CAS and wrong Origin/CSRF. Admin is an application data bypass,
not an identity, input, route or integrity bypass.

The inspection admin credential was not read, reset, reconstructed, disabled, deleted or session-
revoked. Browser-origin diagnosis was not repeated. A noncanonical `localhost` GET was re-observed
only as the expected no-store 307 to the canonical address.

## no-N+1 Evidence

Fresh ephemeral instrumentation exercised the real Node request hydration and Catalog route with
generated canonical Table projections. It changed no Product file and retained no runtime state.

| Tables evaluated | Access reads | Grant reads | Policy reads | Projection reads | Provider calls |
|---:|---:|---:|---:|---:|---:|
| 10 | 1 | 1 | 1 | 1 | 0 |
| 100 | 1 | 1 | 1 | 1 | 0 |
| 1,002 | 1 | 1 | 1 | 1 | 0 |

Authorization lookup count is not O(Table count). No permission snapshot is stored in the session,
and general Catalog reads do not issue one targeted DataHub lookup per Table.

## Security-grade Runtime Sample

No existing business Table was retagged. A unique DEV-only disposable canonical DataHub Dataset was
created with one schema field and no business data, using the existing aspect-ingestion contract.
It was never added to the current local Catalog projection. Exact `globalTags` aspects were used;
substring matching was not used. The existing asset cache entry was invalidated after each tag
change so the actual Product Detail path observed current metadata.

The final actual Product matrix passed:

```text
normal user / normal Table             → 200
normal user / credential Table         → 404
credential user / credential Table     → 200
credential user / restricted Table     → 404
restricted user / restricted Table     → 200
Admin / restricted Table, no grant     → 200
credential + restricted tags           → restricted precedence
credential user / both tags            → 404
restricted policy Allow → Deny          → 404
restricted policy Deny → Allow          → 200
live-session restricted → credential    → 404
live-session credential → restricted    → 200
immediate grant removal                 → 404
```

The asset was then tombstoned with `status.removed=true`, its tags were cleared, and no hard delete
was performed. All disposable users are inactive and login-disabled with zero active sessions,
grants and System assignments. The exact original feature-policy content was restored.

Two earlier attempts to change this sparse disposable asset through Product
`/poc-api/datahub/manual-metadata` returned 502 because real DataHub normalized empty domain and
glossary aspects differently from the Product's exact multi-aspect receipt expectation. No matrix
PASS was claimed from those attempts; each attempt was cleaned before retry. This is a distinct
provider-compatibility risk, not an authorization failure.

Status: higher-grade canonical Table enforcement is `COMPLETE_RUNTIME_VERIFIED` for this bounded
DEV lifecycle. The sparse empty-aspect manual-metadata compatibility remains `PARTIAL`.

## Provider Root Cause and Binding

The prior `ECONNREFUSED` and absent DataHub Product path were binding/runtime issues, not Table
authorization defects.

| Provider stage | Classification | Current result |
|---|---|---|
| DataHub | `MISSING_REQUIRED_BINDING` corrected | Web URL present; local auth-disabled contract needs no token; config and GraphQL direct 200 |
| Chat | `CONFIGURATION_ERROR` corrected | existing endpoint bound; direct 200 and Product composition 200 |
| Embedding | `CONFIGURATION_ERROR` plus stalled local inference | existing endpoint recovered; 1- and 32-input probes 200; Product generation 2,002 rows |
| Reranker | `PORT/URL_BINDING` plus physical batch mismatch | existing service/endpoint; actual Product reranking completed |

The reranker accepted short direct probes but returned 500 for real Product metadata documents
because the existing local process physical micro-batch was 512 while documents exceeded that
bound. The same existing service was restarted with its supported runtime micro-batch environment
set to 1,024. No provider, model, version, container or service architecture was added.

The Web was recreated with the existing image and final loopback binding. The first recreate
briefly inherited the Compose default host port 39080 because the host-only `POC_PORT` value was
not in the container environment. It was immediately corrected to `127.0.0.1:39083` before any
acceptance result was counted. Final health, canonical redirect and OCI revision all passed.

Bindings and the reranker batch override are current DEV runtime configuration, not a tracked
Product change. A future unreviewed recreate/restart could lose them; restart reproducibility is a
remaining operational evidence risk and is not presented as a permanent Product configuration
closure.

## Vector / AUTO / Chat

An actual Product run used two explicitly granted current Tables and one ungranted current Table:

- Catalog returned exactly the two authorized Tables; direct Detail for the third identity was 404.
- explicit Vector returned two authorized evidence items through `PGVECTOR_COSINE`; the ungranted
  identity was absent.
- reranking reported `RERANKING_COMPLETED` after the bounded runtime repair.
- AUTO selected the metadata Vector path, used the same two authorized evidence items, completed
  reranking and produced citations bound only to those items.
- after immediate grant removal, Catalog returned zero and Vector returned no evidence with
  `NO_LIVE_EVIDENCE`; provider unavailability was not confused with empty authorization scope.

This confirms the source ordering for the bounded external runtime:

```text
authorized URNs → PostgreSQL WHERE → vector distance order
authorized scope → AUTO signal/retrieval → reranker → context → citation
```

A separate disposable viewer exercised actual Product General Chat: login 200, Chat 200, selected
mode `GENERAL`, evidence count 0, live-provider composition completed and a nonempty answer was
returned. It was then disabled with zero active sessions/grants. General Chat therefore remains
independent of Table access; metadata authorization was not applied to it artificially.

## Neo4j Provenance

Read-only Neo4j inspection found three `PocEntity` nodes with only `entity_type`, opaque `id` and
`name`; the two relationships had no canonical identity properties. No node or relationship held
an exact DataHub Dataset/Table URN, and no PostgreSQL↔Neo4j identity bridge or stable Table/Column
distinction was present.

Classification: `NEEDS_KNOWLEDGE_PHASE`.

The safe current behavior remains non-Admin empty graph evidence before traversal. Full traversal
followed by hiding was not introduced, and no temporary graph identity or graph ACL framework was
created. Fail-closed safety is runtime-verified; the overall Neo4j surface remains `PARTIAL`.

## Remaining Provider / Graph Risks

- Direct DataHub lineage on one authorized current center returned upstream and downstream Dataset
  neighbors. Node POC authorizes the center before the call and filters every neighbor; non-Admin
  output sets `truncated=false` rather than exposing a raw provider total. The provider still cannot
  prefilter every traversal, so Lineage remains `PARTIAL`.
- Sparse disposable manual-metadata writes can fail the exact multi-aspect read-back receipt when
  DataHub returns empty domain/glossary shapes. No business metadata was changed to work around it.
- Deleted/current-missing Tables still lack authoritative current grade and fail closed for
  non-Admin. No tombstone security framework was added.
- `VIEW` and `MATERIALIZED_VIEW` remain outside the grantable `TABLE` identity.
- Table-bound Governance/Knowledge records can use the existing Table seam. Unbound documents
  remain `UNBOUND_NON_TABLE_RESOURCE`; no generic resource ACL was created.
- Quality route/menu and Table helper seams are source-verified, but unavailable GX runtime keeps
  rule→GX→result verification `BLOCKED`.

## Tests and Build Gates

All commands used the unchanged Product `2f247107...` source:

| Gate | Result |
|---|---|
| Focused authorization/provider/catalog tests | PASS — 33/33 |
| Node POC full suite | PASS — 97/97 |
| Catalog performance/reconciliation | PASS — 5/5 |
| Frontend full suite | PASS — 87 files, 592/592 |
| Lint | PASS |
| Typecheck | PASS |
| Production build | PASS; pre-existing bundle-size advisory only |
| Repository static verifier | PASS |
| Compose no-interpolate render | PASS |
| Auth-weakening/hardcoding scan | PASS; test-only localStorage spoof cases excluded from authority |
| `git diff --check` | PASS |

## Runtime Evidence and Regression

- Product SHA equals deployed OCI revision exactly.
- Web is healthy at the canonical loopback origin; noncanonical browser GET remains a no-store 307.
- DataHub, Chat, Embedding and Reranker are bound in the current Web runtime without exposing
  credentials.
- Product General, Vector and AUTO requests completed through the current providers.
- security-grade tag/grant/grade/policy decisions were observed through the real Product Detail
  path, including immediate live-session changes.
- current local Catalog projection remains 2,002 and contains zero disposable security-grade
  assets; active embedding generation contains 2,002 current rows.
- inspection admin, fixed policy content, active grant/mapping cleanup and MCL counts remained
  intact after every runtime slice.

The full test and state observations protect login/session, inspection admin, User↔Table grants,
fixed policy, System mapping, PHASE 1C-4 three-lane CR workflow, Change History, MCL,
Catalog/Search/Tree, Monitoring/Governance, Airflow exact service routing and 401/403/404 semantics.
PHASE 1C-4 was not redesigned or repeated.

## AGY Usage

- Orca orchestration Run: `run_1fcc6d143e87`
- Neo4j/lineage discovery: requested/effective Gemini 3.1 Pro High, read only, completed
- Knowledge/Governance/Quality discovery: requested/effective Gemini 3.1 Pro High, read only,
  completed; suggestions to redo completed 1C-4/1D cutover were rejected after coordinator review
- Secret-bearing provider/runtime and disposable-account work: CONTROL_PLANE coordinator only
- Critical Product mutation worker: none; no Product mutation was required, so Claude-first
  mutation dispatch was not started
- Independent validator: not duplicated because Product source did not change; all exact-source
  suites and runtime gates above were freshly rerun

No worker received a password, cookie, token or provider secret. No duplicate mutating worker or
second CONTROL_PLANE was used.

## Overengineering Check

```text
new tables       0
new dependencies 0
new services     0
new capabilities 0 (still exactly 15)
new frameworks   0
```

There is no new IAM, ACL framework, policy DSL, graph policy layer, provider architecture, auth
service, session permission snapshot, migration, legacy deletion or broad refactor.

## Product SHA

`2f247107d28716aeba3cfe3fa201fb040ac437e3` (unchanged)

## Evidence SHA

The Evidence SHA is the separate commit containing this file, `CURRENT.md` and the master backlog.
Its exact hash is reported after the commit is created; it is not a Product SHA.

## Canonical Status by Surface

- local Catalog/Search/Tree/Detail/autocomplete/facet/count/dashboard/Monitoring:
  `COMPLETE_RUNTIME_VERIFIED`
- request-time AND helper, Admin data/integrity split and no-N+1 hydration:
  `COMPLETE_RUNTIME_VERIFIED`
- security-grade tagged canonical Table E2E: `COMPLETE_RUNTIME_VERIFIED`
- PostgreSQL vector and memory pre-ranking: `COMPLETE_RUNTIME_VERIFIED`
- bounded metadata AUTO/context/citation and Product General Chat: `COMPLETE_RUNTIME_VERIFIED`
- current DEV provider binding/E2E: `COMPLETE_RUNTIME_VERIFIED`; restart reproducibility remains an
  operational risk
- sparse empty-aspect manual-metadata compatibility: `PARTIAL`
- DataHub lineage/provider traversal and totals: `PARTIAL`
- Neo4j fail-closed safety: `COMPLETE_RUNTIME_VERIFIED`; canonical pre-traversal provenance:
  `BLOCKED`, so the overall Neo4j surface is `PARTIAL`
- Table-bound Governance/Registration seam: `SOURCE_VERIFIED`; unbound resources: `PARTIAL`
- Quality authorization seam: `SOURCE_VERIFIED`; GX runtime: `BLOCKED`

## PHASE 1D Overall Status

`PARTIAL`

The local enforcement, actual higher-grade Table matrix and bounded external Vector/AUTO/Chat path
are now runtime-verified. Provider-wide traversal, Neo4j canonical provenance, sparse multi-aspect
provider compatibility, deleted-grade history, unbound resources and GX runtime are not all
closed. They are not promoted to false PASS results.

## Next Smallest Slice

The smallest next Product-independent slice is a deterministic restart/recreate receipt for the
existing DEV provider bindings and reranker batch setting, without adding a service, provider,
model or tracked secret. Separately, a bounded provider-compatibility test can characterize empty
domain/glossary read-back for sparse manual metadata without modifying a business Table.

Neo4j canonical URN provenance belongs in a later separately authorized Phase 4-aligned identity
slice. PHASE 1E/1F, migration, GX, Knowledge, Quality, Chat Router redesign and legacy deletion do
not start automatically.
