# CURRENT.md — DataRiver Node POC product status

## Current baseline

- Current Product SHA: `038b7ffa6b06666985664d480340b9010fe1fdd9`
- Deployed OCI revision: `038b7ffa6b06666985664d480340b9010fe1fdd9`
- PHASE 1A frozen Product: `618b9713059ba7e31b807ceae3b401766a313668`
- PHASE 1B Product: `e13dbb4f8412937e1d60bd45f83e0e91dc3e91aa`
- PHASE 1C-1 Product: `60f5f270a56130f2ed96236d9286d0903e3360db`
- PHASE 1C-2 Product: `f78f30fbcf0a5468ec2ce9893d06825ddd030369`
- PHASE 1C-3 Product: `9df97f4975a990819db655b74b09e709dc6d5aad`
- PHASE 1C-4 implementation: `65ca6349cc6f3c81a1ef75a48a7bb2b47e5a66c9`
- PHASE 1C-4 browser-origin hardening Product:
  `773cd37e6d48cbba02c999380fe1965a3b9f4e26`
- PHASE 1D bounded Table enforcement implementation:
  `805fe1279f38066c57e054b7720295b9495d9b55`
- PHASE 1D production-image packaging:
  `2f247107d28716aeba3cfe3fa201fb040ac437e3`
- PHASE 1D-R deterministic provider restart/current Product:
  `91ca4db7ca792566b7765f3366036b1d8bed2869`
- MCL current-source operational summary/current Product:
  `6c67242756ac3ee8fef0cf6d5d8084daaa857fa5`
- Registration request-time responsibility Product:
  `d424d0e49e2f5b763a77cd4f2beb438e5345b0fa`
- Registration manual-metadata receipt Product:
  `038b7ffa6b06666985664d480340b9010fe1fdd9`
- Web: healthy at canonical DEV origin `http://127.0.0.1:39083`
- G1/G2 publication, PREP/OPS mutation and push were not performed.

## Canonical status

- PHASE 1A local account/server session: `COMPLETE_RUNTIME_VERIFIED`
- PHASE 1B central capability/route authorization: `COMPLETE_RUNTIME_VERIFIED`
- PHASE 1C-1 System master/exact Table↔System mapping: `COMPLETE_RUNTIME_VERIFIED`
- PHASE 1C-2 account/Table grant/grade administration: `COMPLETE_RUNTIME_VERIFIED`
- PHASE 1C-2H hardening: `COMPLETE_RUNTIME_VERIFIED`
- PHASE 1C-3 fixed feature-role-grade management: `COMPLETE_RUNTIME_VERIFIED`
- PHASE 1C-4 CR responsible-System/three-lane approval: `COMPLETE_RUNTIME_VERIFIED`
- PHASE 1D bounded Table enforcement slice: `COMPLETE_RUNTIME_VERIFIED` — local read/count/detail,
  request-time AND, no-N+1 hydration, higher-grade canonical Table enforcement and bounded actual
  Product Vector/AUTO/context/citation/General Chat paths are verified at the current Product.
- PHASE 1D-R deterministic provider restart: `COMPLETE_RUNTIME_VERIFIED` — tracked configuration
  plus the supported ignored DEV configuration/secret boundary reproduces Web 39083, DataHub,
  Chat, embedding and reranking after clean restart.
- MCL runtime / automatic detection: `COMPLETE_RUNTIME_VERIFIED` — current DataHub/Kafka source,
  exact checkpoint/ledger, supported schema/description/lifecycle capture, startup catch-up,
  idempotent replay, same-day scheduler receipt and restart continuation are verified.
- Actual KST 00:00 scheduler observation: `TARGET_RECHECK_REQUIRED`.
- DEV support-service gate: `PARTIAL` overall — Airflow and MinIO are
  `COMPLETE_RUNTIME_VERIFIED` through the existing DEV contracts; GX has an exact 1.19.1 execution
  seam but no implemented/proven result-to-DataHub Assertion E2E. Its missing egress contract is
  `GX_CANONICAL_RUNTIME_CONTRACT_REQUIRED`, not permission to invent a Quality architecture.
- Registration bounded authorization/preparation slice: `COMPLETE_RUNTIME_VERIFIED` — the existing
  MinIO → bulk preparation → Airflow callback → authorized current-Table candidate flow enforces
  role + grant + grade + fixed policy + Responsible System, owner isolation and count/receipt
  projection. Sparse manual-metadata receipt compatibility and one actual disposable description
  apply are also `COMPLETE_RUNTIME_VERIFIED`. Registration overall remains `PARTIAL` only for the
  remaining bulk candidate-to-CR/apply workflow acceptance.
- PHASE 1D overall: `PARTIAL` — graph provenance, provider-wide traversal/totals, deleted-grade,
  unbound Knowledge/Governance and Quality/GX surfaces remain open.
- PHASE 1E/1F: `BACKLOG`
- remote-host network acceptance: `TARGET_RECHECK_REQUIRED`
- Account/Auth core: `COMPLETE_RUNTIME_VERIFIED`; future Registration, Knowledge and Quality
  integrations own their feature-specific authorization acceptance.

## Product execution priority

```text
P0  PHASE 1D-R deterministic runtime                 → COMPLETE_RUNTIME_VERIFIED
P1  Account/Auth core                                → completed baseline; feature regression only
P2  MCL change management / automatic change capture → COMPLETE_RUNTIME_VERIFIED; midnight recheck
P3  DEV support services: Airflow / MinIO / GX       → Airflow/MinIO complete; GX partial
P4  Registration management                          → auth/preparation/manual apply complete; overall partial
P5  Governance: policy/standard document management  → mutation policy HOLD
P6  Chat: General / Vector / Auto / Graph refinement → preserve current verified baseline
P7  Knowledge / Quality                              → document current state; user definition required
P8  Admin                                             → add only minimum feature-required controls
```

Engineering Phase numbers remain for lineage and dependencies. They do not override this
user-facing product order.

## Current authority

```text
local credential + opaque server session
→ request-scoped subject_id
→ current access document
→ central 15 capabilities
→ explicit Table grant
→ normal < credential < restricted
→ fixed 8 × 5 × 3 feature policy
→ Responsible System only for workflow/business features
→ feature operation
```

- Role/System authority stays in `change-history-access-v1`; credential/session rows contain only
  authentication data.
- User↔Table grants use the bounded exact `(subject_id, canonical dataset URN)` relation.
- Exact Table↔System is the current mapping authority for new CRs. Legacy schema scopes are not
  unioned or dual-written.
- A new CR is tied to one exact responsible System. Developer/Data Steward workflow actions use
  current assignments independent of priority. Final completion needs independent Developer,
  Data Steward and Manager lanes; Admin cannot silently substitute for them.
- Historical CRs without the new lane contract remain readable and mutation-protected. History was
  not rewritten.

## Inspection Admin and browser contract

- The DEV-only `admin` inspection account remains active, login-enabled, role `admin`, maximum
  grade `restricted`, with no Responsible System. It is explicitly excluded from validation cleanup.
- Its credential is server-valid and was verified through the actual browser flow. The password was
  not reset during browser diagnosis and is not stored in Git/evidence/dashboard.
- Canonical browser address is `http://127.0.0.1:39083`. Browser GET/HEAD requests received at
  `localhost` are redirected to that configured origin; state-changing wrong-Origin requests remain
  denied. Origin/CSRF/cookie controls were not relaxed.
- Agent browser flow is verified through login, `/auth/me`, Admin menu/page and hard reload. User
  browser confirmation remains pending; an active session is not treated as confirmation.

## Fresh validation

- Independent fresh Node POC Validator at exact Product
  `038b7ffa6b06666985664d480340b9010fe1fdd9`. Effective model: Gemini 3.1 Pro High;
  authoritative worktree/branch/HEAD and Node POC authority recorded; no Product files or runtime
  changed. The coordinator separately confirmed the deployed OCI revision matches that Product.
- Node POC full suite: 104/104 PASS.
- Frontend full suite: 87 files, 592/592 PASS on the final clean rerun.
- Lint, typecheck, POC/production build, exact POC image build, Compose render and
  `git diff --check`: PASS.
- Exact Product image build/package/deploy: PASS; current Web health `ok` and OCI revision exact.
- Representative runtime: grant/no-grant, Admin, policy, immediate grant/grade/policy changes,
  direct 404, authorized counts/facets/tree/dashboard, exact AUTO inventory/citations, direct
  lineage, non-Admin Neo4j fail-closed and unauthorized mutation 403 passed.
- The former provider refusals were binding/runtime drift, not Table authorization. The existing
  DataHub, Chat, embedding and reranker contracts now survive clean supported restart from the
  selected configuration. Direct probes and actual Product General/Vector/AUTO composition passed.
  The current 2,002-row embedding generation is active. No provider, model, version or service
  architecture was added.
- A DEV-only disposable canonical Table lifecycle verified exact `normal → credential → restricted`
  resolution, tag precedence, grant/grade/fixed-policy AND, Admin data bypass, live-session grade and
  policy changes, and immediate grant removal. The asset was tag-cleared and tombstoned; all test
  users, credentials, sessions, grants and mappings were cleaned without hard deletion.
- DataHub empty domain/glossary read-back compatibility is now bounded and fail-closed: explicit
  absence equals controlled empty state, provider-managed glossary audit stamps are excluded only
  after structural validation, and all other aspects keep exact full-document comparison. Actual
  disposable Product requests passed both zero-write `ALREADY_MATCHED` and one-write
  `APPLIED_VERIFIED`; no business Table was modified.
- Web/Airflow/Neo4j/PostgreSQL/Redis/MinIO host listeners remain loopback-bound. A real second-host
  denial probe is still required.
- MCL ledger/checkpoint/CR-link/source counts are 66/2/4/2 after current-source catch-up and a
  supported disposable schema/description/lifecycle event lifecycle. Duplicate exact source
  positions remain 0.

## PHASE 1D current slice

- The covered paths now use one request-hydrated Table decision: current principal + active exact
  grant + maximum grade + fixed feature-role-grade cell. Admin has application data bypass after
  canonical identity validation; input, TABLE-only mutation, stale-CAS and Origin/CSRF integrity
  checks are unchanged.
- General Catalog/Search/Tree/Detail/count/dashboard/profile/metadata Chat visibility no longer
  uses Responsible System. Grants and fixed policy are hydrated once per request into Sets; there
  is no session snapshot or per-Table authority/provider query loop.
- Local results filter before match/sort/page/count. PostgreSQL vector restricts exact allowed URNs
  before vector ordering; memory filters before cosine/sort; empty non-Admin scope stops early.
- AUTO exact/inventory/semantic retrieval, reranking input, context and citations use authorized
  scope. General Chat remains independent of Table access.
- Direct DataHub lineage authorizes its center and filters neighbors. Non-Admin Neo4j stays empty
  until canonical Table provenance can be proved before traversal.
- Provider-side lineage/glossary filtering, deleted-asset grade history, Neo4j identity provenance
  and coarse unbound Knowledge/Governance blobs remain explicit risks; do not claim false runtime
  completeness.
- Quality/GX authorization seams do not establish an available Quality/GX runtime.

## PHASE 1D closeout / gap reduction

- Surface-level reclassification at the unchanged Product confirms local
  Catalog/Search/Tree/Detail/autocomplete/facet/count/dashboard/Monitoring and memory-vector
  enforcement as `COMPLETE_RUNTIME_VERIFIED`. This does not promote PHASE 1D overall.
- Ephemeral request instrumentation at 10, 100 and the current 1,002 Tables observed one access
  read, one grant read, one policy read and one local projection read per request, with zero
  per-Table provider calls. Authorization lookup count is not O(Table count).
- Neo4j has no stable exact DataHub Table URN property or PostgreSQL↔Neo4j identity map. Non-Admin
  graph evidence remains fail-closed; canonical pre-traversal provenance is `BLOCKED` and belongs
  in a separate Phase 4-aligned identity slice.
- Table-bound Governance/Registration seams are source-verified. Unbound Knowledge/Governance
  resources remain `PARTIAL`; Quality authorization seams are source-verified while GX runtime is
  `BLOCKED`.
- Current DEV Product runtime additionally verifies PostgreSQL pre-ranking, metadata AUTO,
  authorization-filtered context/citation, General Chat without forced Table scope, and a canonical
  higher-grade Table matrix. Immediate grant removal produced empty Catalog/vector evidence.
- Neo4j runtime still has no exact DataHub Table URN property or PostgreSQL identity bridge;
  classification is `NEEDS_KNOWLEDGE_PHASE`, with non-Admin graph kept fail-closed before traversal.
- PHASE 1D-R closed the provider restart risk at Product `91ca4db7...`: the selected ignored DEV
  environment is the single Compose/runtime input, DataHub missing-token behavior is explicit and
  DEV-local, Web-only recreate preserves 39083, and the existing reranker manager restores and
  verifies UBATCH 1,024. Clean restart plus General/Vector/AUTO runtime E2E passed.
- Embedding retention remains a separate `UNBOUNDED_ACCUMULATION_RISK`: three bindings/generations
  retain 6,002 rows total, while the active generation has 2,002 rows. No deletion was performed.
- Evidence:
  `.orchestration/evidence/DEV-PHASE1D-CLOSEOUT-GAP-REDUCTION.md` and
  `.orchestration/evidence/DEV-PHASE1D-AUTONOMOUS-PROVIDER-GRADE-E2E.md` and
  `.orchestration/evidence/DEV-PHASE1D-R-DETERMINISTIC-RESTART.md`.

## DEV support services and Registration

- Airflow 3.3.0 and the existing `datariver_bulk_registration_prepare` DAG are bound through the
  supported DEV configuration and actual Product callback. MinIO uses the existing external DEV
  endpoint/secret contract and passed part/complete/object-cleanup runtime acceptance. Neither was
  added to the base Product as a new mandatory service.
- GX remains exact-version source/runtime seam evidence only: `great-expectations==1.19.1` is
  present, but result-to-DataHub Assertion emission and a GMS/UI receipt are not implemented or
  runtime-verified. Quality Product completion is not inferred from the seam.
- Registration human routes allow only data_steward, manager and admin. Non-Admin Table operations
  require a current canonical TABLE, active exact grant, grade, fixed Registration policy and an
  exact active Table↔System mapping currently assigned to the principal. Admin data bypass still
  requires valid current TABLE identity.
- Bulk preparation is owner-scoped for non-Admin and hidden with 404 from other users. Current
  Table/mapping authority is rehydrated per request; candidates are filtered before pagination,
  count and receipt hashes. Immediate grant and mapping removal are reflected without a new login.
- Exact Product runtime passed MinIO upload, preparation create, actual Airflow callback to READY,
  full-AND candidate visibility, owner isolation, Admin bypass and immediate revocation. All
  disposable credentials, sessions, grants, mappings, assignments, users and exact MinIO objects
  were safely cleaned without deleting history. The inspection Admin was preserved.
- Product `038b7ffa...` additionally passed sparse empty manual metadata with five
  `ALREADY_MATCHED` receipts and an actual disposable description apply with one
  `APPLIED_VERIFIED` receipt. Both disposable Tables were tombstoned and all dummy authority was
  cleaned; MCL remained 2/2/66/4 and Catalog remained 2,002.
- Evidence: `.orchestration/evidence/DEV-REGISTRATION-SUPPORT-SERVICES-RUNTIME.md`.

## MCL runtime / automatic detection

- Product `6c672427...` preserves the existing two historical sources/checkpoints and scopes only
  operational capture/sync/ledger-guarantee status to the exactly configured current source.
  Historical event lists/counts remain readable and unfiltered by source.
- The current source caught up from checkpoint offset 52,942 to 55,596. Exact deterministic
  ledger count advanced from 46 to 66; an immediate replay appended zero, and duplicate exact
  source positions remain zero.
- A DEV-only disposable Dataset produced five supported normalized changes: documentation create
  and update, schema field create and add, and lifecycle delete. It remains a tombstone/history
  record; no hard delete or destructive offset reset occurred.
- Scheduler startup captured changes, reconciled the current 2,002-asset Catalog and wrote receipt
  version 2. Same-configuration Web restart preserved ledger 66, checkpoint offset/version
  55,596/2,748, receipt 2 and Catalog version 39.
- Final runtime summary is `CONTIGUOUS_CAPTURE_RECORDED`; Web is healthy at 39083 and the deployed
  OCI revision matches the Product SHA exactly. Actual KST 00:00 passage was not observed and stays
  `TARGET_RECHECK_REQUIRED`.
- Current support result: Airflow 3.3.0 and MinIO are healthy on loopback and bound to the Web
  Product through supported existing DEV contracts. MinIO's external DEV ownership remains
  explicit. GX has no result→DataHub Assertion E2E, so the aggregate support gate remains
  `PARTIAL` even though Airflow and MinIO are complete.
- Evidence: `.orchestration/evidence/DEV-MCL-RUNTIME-AUTOMATIC-DETECTION.md`.

## Gates

- G1 SOURCE_MERGE: `NOT_APPROVED`
- G2 DEV_PUBLISH: `NOT_APPROVED`
- G3 PREP mutation: `NOT_APPROVED`
- G4 OPS mutation: `NOT_APPROVED`
- Current boundary: preserve Product `038b7ffa...`; do not start PHASE 1E/1F, migration, legacy
  deletion, GX/Knowledge/Quality Product implementation or another Account/Auth refactor. The next
  smallest Registration work is the current bulk candidate-to-CR/apply workflow acceptance after
  its existing contract is confirmed. Governance document mutation stays on policy HOLD; GX
  Assertion egress lacks a canonical runtime contract; Chat General/Vector/AUTO stays verified.
