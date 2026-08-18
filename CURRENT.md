# CURRENT.md — DataRiver Node POC product status

## Current baseline

- Current Product SHA: `8dc782a6b8d03ee90b935593294728d2244b03a5`
- Deployed OCI revision: `8dc782a6b8d03ee90b935593294728d2244b03a5`
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
- Registration READY candidate-to-governed-CR Product:
  `5e600320e08da16c67dcb4c0e4dce76162230f04`
- Registration server-authoritative apply-report Product:
  `78448566c9cb461bacafa0afc425572d4fefd0ad`
- Governance policy/standard document management Product:
  `fd379567a220f1e677deb5225b8e0b36c1d28d8d`
- Menu topology/Registration role boundary Product:
  `536c02f61476a35ad653cac041a3d8b76cbdf5a1`
- Post-K1 menu/profile deep-link Product:
  `1eb4d5ba53078882c4ef7d7b31b28f233d9e0e30`
- Change/Monitoring combined-summary Product:
  `b0bb9f0aafc2391f80be0e24eccdfc1d5568bffc`
- Registration Manager read-only history/UX Product:
  `691b889af35fbbe49b5e2850420f877aebf5ca56`
- Quality primary-tab parity Product:
  `8dc782a6b8d03ee90b935593294728d2244b03a5`
- Knowledge K1 exact identity/provenance Product:
  `afb95a45c45ae065223faa39c53278884c935f37`
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
  `GX_PREP_OPS_CONTRACT_EVIDENCE_REQUIRED`, not permission to invent a Quality architecture.
- Registration bounded authorization/preparation slice: `COMPLETE_RUNTIME_VERIFIED` — the existing
  MinIO → bulk preparation → Airflow callback → authorized current-Table candidate flow enforces
  role + grant + grade + fixed policy + Responsible System, owner isolation and count/receipt
  projection. Sparse manual-metadata receipt compatibility and one actual disposable description
  apply are also `COMPLETE_RUNTIME_VERIFIED`. One READY metadata candidate now creates exactly one
  server-authored governed CR with current authority, ETag/idempotency and CAS fencing; the exact
  runtime proved zero provider writes. Product `78448566...` additionally makes apply-report a
  server-authoritative `change.read` projection with exact truthful `NOT_STARTED`, 404 hiding and
  private/no-store, without creating an apply job or provider evidence. Registration overall remains
  `PARTIAL` for the durable preparation/outbox/provider-apply and remaining typed/target-host
  contracts. Durable restart storage is `HOLD_REGISTRATION_DURABLE_STORAGE_DECISION`; the read-only
  recommendation is to reuse the accepted minimal relational receipt/candidate/provenance contract,
  not put execution evidence into the global core JSON blob.
- Governance policy/standard document management: `COMPLETE_RUNTIME_VERIFIED` for active-user read
  and data_steward/manager/admin create, DRAFT-version update and archive. Viewer/developer mutation,
  Data Steward lifecycle spoofing and hard delete are denied. This uses existing `change.manage`
  without giving Data Steward `knowledge.manage` or `knowledge.review`.
- Canonical top-level menu and independent Change/Monitoring/Registration routes:
  `COMPLETE_RUNTIME_VERIFIED`. Registration mutation is limited to data_steward/admin at navigation,
  page, server route and local adapter boundaries; Manager keeps Catalog access.
- Post-K1 Change/Monitoring presentation: `COMPLETE_RUNTIME_VERIFIED`. The Change page combines its
  existing CR status and detected-change linkage under `CR 및 감지 변경 현황` and links to the
  unchanged independent Monitoring route without duplicating backend or client state.
- Registration Manager read-only history/recent-run/workbench UX: `COMPLETE_RUNTIME_VERIFIED`.
  Manager can read only currently authorized execution history through one capped exact-URN batch;
  candidate and mutation routes remain 403. Manual/Bulk share one recent-run panel, and the Manual
  workbench keeps actions reachable at desktop and 390px. Registration overall remains `PARTIAL`.
- Quality primary-tab Governance-style parity: `COMPLETE_RUNTIME_VERIFIED`. The three existing
  Quality tabs share the exact Governance tab primitive while retaining Quality roving-keyboard,
  URL/deep-link, panel layout and authorization behavior. Quality Product scope remains
  `USER_FEATURE_DEFINITION_REQUIRED`; GX was not implemented by this UI-only slice.
- Knowledge K0 existing-implementation audit: `COMPLETE_SOURCE_RUNTIME_AUDIT`.
- Knowledge K1 exact identity/provenance: `COMPLETE_RUNTIME_VERIFIED`. The current Node Product
  preserves exact provider Table and Column URNs, derives a deterministic graph/release-pinned
  Knowledge identity, performs only a fixed parameterized `KnowledgeSourceEntity`/`HAS_COLUMN`
  projection, and revalidates current Knowledge Table scope before every write. One actual browser
  Asset lifecycle produced 2 nodes, 1 edge and duplicate 0 after rerun; exact `DATAHUB_SYNC`
  provenance and no-grant 403 were verified. Knowledge overall remains `PARTIAL`; K2 Registry/
  Asset/version lifecycle is next, while Knowledge Chat, Main Chat routing, MCP and default system
  assets remain unstarted.
- PHASE 1D overall: `PARTIAL` — graph provenance, provider-wide traversal/totals, deleted-grade,
  unbound Knowledge and Quality/GX surfaces remain open.
- PHASE 1E/1F: `BACKLOG`
- remote-host network acceptance: `TARGET_RECHECK_REQUIRED`
- Account/Auth core: `COMPLETE_RUNTIME_VERIFIED`; future Registration, Knowledge and Quality
  integrations own their feature-specific authorization acceptance.

## Product execution priority

```text
1  Admin — 접근관리                         → completed baseline
2  검색                                    → completed local/Vector authorization baseline
3  변경관리                                → Change History / CR completed baseline
4  모니터링                                → independent authorized read baseline
5  등록관리                                → steward/admin only; overall PARTIAL
6  거버넌스 — 정책·표준 문서 관리          → bounded CRUD/archive complete
7  Chat                                    → General/Vector/AUTO complete; Graph partial
8  지식관리                                → K0 audited; K1 runtime complete; K2 Registry/version next
9  품질관리                                → USER_FEATURE_DEFINITION_REQUIRED
기술 Backlog                              → support/deployment details only
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
- Knowledge K1 independent-review validation previously logged the inspection browser out while
  switching to a disposable reviewer. The inspection account remains active/login-enabled,
  unlocked, failed attempts 0, role `admin`, grade `restricted`, with no Responsible System or Table
  grant. A current user-owned inspection session now exists; Registration validation preserved it.
  No validation cleanup may revoke or reconstruct it.

## Fresh validation

- Current Product and deployed OCI are the exact same 40-character revision
  `8dc782a6b8d03ee90b935593294728d2244b03a5`. A fresh independent Node POC Validator using Gemini
  3.1 Pro High (High) returned `PASS` after recording the exact worktree/branch/HEAD, Node POC
  authority, `/healthz=ok`, exact OCI equality and rerunning the current Quality 18/18 focused
  tests. Legacy FastAPI and secret-bearing environment dumps were not used.
- Node POC full suite: 108/108 PASS.
- Frontend full suite: 87 files, 606/606 PASS on the final single-worker rerun. Four movable
  parallel navigation/timeout failures are recorded as `FRONTEND_ASYNC_TEST_PARALLEL_FLAKINESS`;
  parallel partial results were rejected and are not completion evidence.
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
- Registration human routes allow only data_steward and admin. Non-Admin Table operations
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
- Product `5e600320...` binds one READY metadata candidate to exactly one server-authored governed
  CR. Runtime grant and mapping removal hid the candidate and denied creation immediately;
  missing/malformed/stale ETags returned 428/400/412, exact replay returned the original CR and
  changed/sibling commands returned 409. DataHub remained byte-fingerprint unchanged. Disposable
  credential/session/grant/mapping/assignment and exact MinIO objects were cleaned, while the CR
  and opaque internal binding remain immutable history.
- Product `78448566...` moves apply-report authority from browser-local construction to an exact
  server `change.read` route. Existing CRs return the canonical truthful `NOT_STARTED` schema with
  private/no-store; unknown CRs and unsupported methods are hidden with 404. No apply job, outbox,
  provider mutation or CR transition is synthesized. Preparation remains memory-backed, so canonical
  restart durability/outbox/apply ownership stays `HOLD_REGISTRATION_DURABLE_STORAGE_DECISION`.
- The read-only durability decision rejects the global `poc_state` core JSON blob for preparation
  evidence. The recommended approval direction is the already accepted minimal relational
  preparation/receipt, deterministic candidate and candidate→CR provenance contract; existing CR
  apply/test remains the sole provider-mutation owner. No schema mutation was performed.
- Product `691b889a...` adds only the bounded Manager read-only execution-history UX. Manager history
  uses one capped exact-URN request, then server request-time Table authorization and exact filtering
  before matching/counting; candidate and mutation routes remain 403. Data Steward/Admin retain the
  mutation workbench, Manual/Bulk share one recent-run panel, and 390px browser acceptance passed.
- Evidence: `.orchestration/evidence/DEV-REGISTRATION-SUPPORT-SERVICES-RUNTIME.md` and
  `.orchestration/evidence/DEV-REGISTRATION-BULK-CANDIDATE-CR-RUNTIME.md` and
  `.orchestration/evidence/DEV-REGISTRATION-APPLY-REPORT-AUTHORITY.md` and
  `.orchestration/evidence/DEV-GOVERNANCE-DOCUMENT-MANAGEMENT-RUNTIME.md` and
  `.orchestration/evidence/DEV-POST-K1-REGISTRATION-UX-RUNTIME.md`.

## Governance policy and standard documents

- Product `fd379567...` keeps read open to every active role and reuses existing `change.manage`
  only for document create, DRAFT-version append/update and archive. It does not apply Table or
  Responsible-System scope to an unbound policy/standard document.
- Data Steward does not gain Knowledge manage/review. Direct core CAS rejects non-DRAFT creation,
  hard delete, review/publication state or pointer spoofing and published-version mutation.
- Exact runtime passed create/update/archive for Data Steward, Manager and Admin, with Viewer and
  Developer mutation 403. Data Steward lifecycle spoof and hard delete also returned 403.
- Three DEV-only acceptance documents remain archived with six DRAFT versions as retained audit
  history. All five disposable profiles are inactive with disabled credentials and zero sessions;
  inspection admin was preserved.
- Evidence: `.orchestration/evidence/DEV-GOVERNANCE-DOCUMENT-MANAGEMENT-RUNTIME.md`.

## Menu topology and Knowledge K0 audit

- Product `536c02f...` aligns one exact primary menu source to Admin, Search, Change Management,
  Monitoring, Registration, Governance, Chat, Knowledge and Quality while retaining existing route
  and deep-link identities. Change, Monitoring and Registration remain independent pages.
- Registration page/route/adapter authorization now denies Manager and allows only Data Steward and
  Admin. The persisted-policy compatibility projection is limited to historical
  `registration + manager + allow`; normal policy validation and updates remain strict.
- Exact runtime passed Manager Registration 403 plus Catalog 200 and Data Steward Registration 200.
  Both disposable accounts were disabled/inactivated with zero sessions; inspection Admin remains
  preserved with one active session.
- Knowledge K0 found substantial Registry/Studio/Chat UI and local coarse-state code but zero
  current Node Assets, drafts, releases, blocks or bindings. There is no current Knowledge Neo4j
  projection receipt, Knowledge Chat server handler or MCP route/server/test.
- Historical Python Knowledge models are reusable design input only and are not current Node POC
  proof. Non-Admin graph remains fail-closed.
- Next single slice: K1 read-only exact DataHub Table/Column URN ↔ Knowledge entity ↔ Neo4j
  identity/provenance gate. No graph write, Knowledge storage migration, Main Chat routing or MCP
  implementation starts before that gate.
- Evidence: `.orchestration/evidence/DEV-MENU-REGISTRATION-KNOWLEDGE-K0-RUNTIME.md`.

## Knowledge K1 exact identity/provenance

- Product `afb95a45...` preserves the exact provider Table dataset URN and exact provider-returned
  Column schemaFieldEntity URN. It creates only deterministic graph/release/external-URN-pinned
  `KnowledgeSourceEntity` identities and the fixed `HAS_COLUMN` projection.
- An actual browser-created DEV Asset passed create, T-Box Class editing, exact Catalog binding,
  save/reload, Pre-flight, independent REVIEW/Publish and two Neo4j projection executions.
  Runtime receipt: 2 nodes, 1 edge, duplicate 0; provenance contains exact TABLE/COLUMN URNs with
  `DATAHUB_SYNC`.
- A no-grant Manager request reached the current Knowledge data-scope guard and returned 403
  `KNOWLEDGE_TABLE_FORBIDDEN`; Neo4j remained 2/1/0.
- Disposable reviewer/negative users are inactive, login-disabled, have zero sessions/grants/
  assignments. The explicitly labelled DEV evidence Asset remains ACTIVE because the current Node
  Registry archive path is a K2 gap; no hard delete or direct graph cleanup was substituted.
- The inspection admin account/credential remains intact, but its browser session was revoked by a
  reviewer-switch logout during validation. This closeout deviation is recorded; password reset or
  session reconstruction is forbidden.
- One unused candidate credential for a not-yet-created disposable reviewer was rendered in a tool
  DOM snapshot, immediately canceled and never used. Its replacement followed the memory-only path;
  no literal secret is retained in Product, Evidence or Dashboard.
- Frontend parallel timing instability is tracked as
  `FRONTEND_ASYNC_TEST_PARALLEL_FLAKINESS`; the final current-source single-worker suite is 600/600.
- Evidence: `.orchestration/evidence/DEV-KNOWLEDGE-K1-IDENTITY-PROVENANCE-RUNTIME.md`.

## Post-K1 Quality tab parity

- Product `8dc782a6...` reuses the existing Governance primary-tab classes for the three Quality top
  tabs. Quality keeps its existing tab panel layout class, roving keyboard navigation, URL state and
  authorization/data behavior.
- Desktop computed style matched Governance exactly. At 390px, the document did not overflow and
  the tab strip retained bounded horizontal scrolling with all actions reachable.
- Quality functionality and GX remain unchanged. Evidence:
  `.orchestration/evidence/DEV-POST-K1-QUALITY-TAB-PARITY-RUNTIME.md`.

## User feedback backlog

- `CHANGE_MONITORING_LEDGER_SURFACE_RELOCATION`: move the authoritative
  `data-change-status-panel` presentation into Change Management and remove overlapping Change
  summary content. Before Product mutation, map the current component and independent Monitoring
  route consumers so the existing server projection remains single-source and no duplicate client
  state/API is introduced. The user explicitly requested backlog-only treatment for now.

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
- Current boundary: preserve Product `8dc782a6...`; do not start PHASE 1E/1F, migration, legacy
  deletion, GX/Quality Product mutation or another Account/Auth refactor. Knowledge K1 is closed;
  the next single step is the bounded Chat Router audit before K2 Registry/Asset/version lifecycle
  with browser acceptance. The
  durability/outbox/provider-apply gap has a read-only recommendation and still requires
  `HOLD_REGISTRATION_DURABLE_STORAGE_DECISION` before a schema/apply mutation. Governance document
  read/create/update/archive is complete; GX requires exact PREP/OPS contract evidence; Chat
  General/Vector/AUTO stays verified.
