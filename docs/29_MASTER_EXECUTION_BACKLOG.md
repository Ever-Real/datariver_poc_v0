# Master execution backlog and requirement traceability

## Purpose and authority

This is the current delivery ledger for the accepted product requirements. It prevents interrupted
sessions, repeated requests, historical test reports, or partially merged branches from being
mistaken for completed delivery. Only normalized current requirements and their evidence are
retained here.

Accepted PRDs, specifications, ADRs, security invariants and the checklists below control delivery.
A source test is not target-environment evidence, and an external gate is never closed with a mock,
an unsafe bypass, or a historical result from another commit.

| Ledger field | Value |
|---|---|
| Created | 2026-07-23, Asia/Seoul |
| Branch / Phase 5 entry base / current local implementation | `codex/admin-policy-rbac` / `c618dea` / `HEAD` (this focused Phase 5 change set) |
| Remote comparison at Phase 5 close | local refs: `origin/main` at `313e59a`; `origin/codex/admin-policy-rbac` through `a683a93`; Phase 5 is not yet published |
| Current controlled phase | Phase 5 closes at this focused commit; continue immediately with Request group 5 `R5-BE-05` and `R5-DEP-01` |
| Final artifact order | Feature → API → Data/ERD → Screen → `README.md` → `ARCHITECTURE.md` |

## Status language

| Status | Meaning |
|---|---|
| `DONE_LOCAL` | Current source plus applicable local tests are complete. It says nothing about WSL or production. |
| `APPROVED_DONE` | The approval-gated phase is complete and the user has accepted it. |
| `AUTHORIZED` | Work may start, but no completion claim is made. |
| `PARTIAL` | A real bounded implementation exists, but one or more requested contracts or current-HEAD gates remain. |
| `PENDING` | No accepted implementation exists yet. |
| `EXTERNAL_GATE` | Completion requires the preparation PC, an external provider, independent identities, or accountable-operator evidence. |
| `CONFLICT` | The literal request and an accepted security/ownership decision differ; resolve through an ADR, never silently. |
| `STALE_EVIDENCE` | The evidence was valid for an older commit or topology and must be rerun. |

## Approval and sequencing record

- [x] Phase 1-scoped RBAC gates passed at `51d7eac`; unrelated and cross-cutting findings remain
  open under request group 5.
- [x] On 2026-07-23 the user approved the completed Phase 1 evidence and authorized Phase 2 to
  start.
- [x] On 2026-07-23 the user authorized previously unapproved work to proceed. This changes phase
  entry authority only: every phase still requires its own evidence, report and focused commit, and
  it does not authorize destructive execution or waive target-environment gates.
- [x] Legacy prompt attachments are reference-only inputs. They are not copied, staged or committed;
  only normalized requirements, decisions, checks and evidence belong in this ledger.
- [x] Phase 2 source and local exit gates pass, including actual PostgreSQL and independent P0/P1
  review. The focused Phase 2 commit establishes this boundary; target activation gates remain open.
- [x] Phase 3 started after the independently reviewed Phase 2 implementation and publication record
  at `b8ab2dd`; its changes are isolated in the current focused work package.
- [x] Phase 3 current-source local gates and independent P0/P1 reviews pass. The focused commit and
  publication at `2a0ae82` close the repository boundary; browser/WSL/provider gates remain explicit
  rather than blocking safe source continuation.
- [x] The follow-on Registration execution/evidence package over `a683a93` passes the current local
  source, deterministic migration, actual-PostgreSQL and independent P0/P1/P2 gates through `0050`
  and is committed locally at `b83a1fb`.
- [ ] Publishing `b83a1fb` and its successor `39d20d0` remains a remote-approval gate: the attempted push to
  `origin/codex/admin-policy-rbac` was rejected by the execution security reviewer because the
  substantial repository payload needs explicit destination approval. No alternate export was
  attempted, and this does not block safe local continuation.
- [x] Phase 3.7 typed BULK catalog metadata completed locally at `39d20d0`. Backend, frontend,
  deterministic migration, actual PostgreSQL and independent security/data/App/API/UI P0/P1 gates
  passed; WSL, external providers, real identities, reference-viewport and full load/recovery remain
  `EXTERNAL_GATE`.
- [x] Phase 4 entry implementation makes Knowledge publication atomic, closes direct and legacy
  release bypasses, enforces the graph/source classification envelope and separates Neo4j, Chat,
  Embedding and Reranking capability evidence. Whole-source and actual PostgreSQL gates pass;
  final independent review is `P0=0`, `P1=0`; focused implementation commit `bd0ee22` closes the
  local entry gate.
- [x] Phase 5 replaces request-time PDF analysis with a pinned, fenced and recoverable worker path.
  Whole-source, additive and empty-database PostgreSQL gates pass; final Application/UI/portability,
  DB/security and PM traceability findings are `P0=0`, `P1=0`. Target-only gates remain open.
- [ ] Request groups 3 through 6 retain their stated dependency on earlier work. External gates are
  reported explicitly if the required machine or accountable human identities are unavailable.

## Canonical execution order

| Order | Work package | Entry condition | Exit evidence |
|---:|---|---|---|
| 0 | Current-state and requirement audit | accepted requirements and current source | this ledger and independent PM audit |
| 1 | Policy Book Phase 2 retention scheduler | Phase 1 approved | full local source/DB gates, independent review, focused commit; target WORM/WSL activation gates remain |
| 2 | Policy Book Phase 3 Admin closure | Phase 2 locally complete and reported | all Admin inventory rows resolved, FE/API/browser negatives, focused commit |
| 3 | Search, Registration, Manual/Bulk and CR gaps | Phase 3 complete and explicitly user-approved | unified search/matches, governed apply/report flows, current-HEAD E2E evidence |
| 4 | Neo4j/LLM preflight, Knowledge, Chat modes and MCP | required adapters prove ready | policy-safe routing, durable jobs, official JSON-RPC contracts and tests |
| 5 | Backend then frontend hardening and portability remediation | feature contracts stable | P0/P1 disposition, bounded load/soak, multiarch/bootstrap matrix, commits |
| 6 | Target WSL and release acceptance | exact release artifacts and target access | import/restore/probes/load/rollback evidence; no production/HA overclaim |
| 7 | Controlled specifications | every preceding work package and target gate complete | one reviewed file and completion report at a time in the mandated order |

## Request group 1 — architecture, low-resource and migration

| ID | Checklist item | Current status | Evidence / remaining work |
|---|---|---|---|
| R1-01 | Recheck merged changes and risks before continuing | `PARTIAL` | Phase 3.7's security/data/App/API/UI findings are closed with no remaining P0/P1 at `39d20d0`; a repository-wide risk-register refresh against the later feature phases and final HEAD is still required. |
| R1-02 | Normalize Mac `linux/aarch64→linux/arm64` and WSL `linux/x86_64→linux/amd64` | `DONE_LOCAL` + `EXTERNAL_GATE` | ADR-0034 and release scripts normalize aliases; current Mac cross-build passes. Actual WSL import/start remains open. |
| R1-03 | Keep browser and backend reads bounded for low-resource operation | `PARTIAL` | Catalog cursor/page/tree bounds exist, but Governance/Knowledge/Sharing/Admin lists, Chat DOM, lineage fan-out and large export/PDF paths remain. |
| R1-04 | Prefer environment-owned stable connection configuration over a second live DB configuration source | `DONE_LOCAL` | `.env` profiles plus mounted secrets are canonical; runtime System Settings activation stays disabled by default. Add schema-version migration for existing env files. |
| R1-05 | Make Redis, MinIO/S3, Neo4j, Airflow, DataHub, telemetry and LLM placement selectable | `PARTIAL` | External connector contracts and overlays exist. Default workers still start even when capabilities are unused; split capability processes/profiles. |
| R1-06 | Validate Mac development topology | `DONE_LOCAL` / `STALE_EVIDENCE` | Selective Mac evidence exists, but current-HEAD end-to-end feature runs must be repeated after remediation. |
| R1-07 | Export exact source and architecture-specific images | `DONE_LOCAL` / `STALE_EVIDENCE` | Offline export/checksum/platform scripts exist; artifacts predating `51d7eac` are not current release artifacts. |
| R1-08 | Import, restore and configure the WSL preparation PC | `EXTERNAL_GATE` | Exact bundle verification, PostgreSQL restore, Keycloak issuer, connectors, external providers, smoke/load/rollback remain open. |
| R1-09 | Use PRDs, checklists, independent reviews and traceable commits | `PARTIAL` | Controlled artifacts and commits exist; this ledger is the continuation index. `origin/codex/admin-policy-rbac` is published, while PR review and merge remain open. |
| R1-10 | Produce an architecture-simplification decision record | `PENDING` | For every questioned dependency/process/store, record retain/remove/externalize, rationale, cost, availability and security consequences rather than treating refactoring alone as simplification. |

When a push needs destination-trust or egress approval, request it and record the pending gate. Work
that does not depend on publication may continue, but the branch must never be described as pushed,
merged, released, or available to the preparation PC until publication actually succeeds.

## Request group 2 — Policy Book, RBAC, retention and Admin

| ID | Checklist item | Current status | Evidence / remaining work |
|---|---|---|---|
| R2-01 | Model No, Partial and Full access per classification | `APPROVED_DONE` | Domain, persistence, migration `0041`, API and negative tests are in `51d7eac`. Missing rules deny. |
| R2-02 | Model Mask, Redact and Tokenize treatments without claiming source-row masking | `APPROVED_DONE` | Typed rule/treatment contract exists and fails closed when unavailable; no source-row masking adapter or data-value enforcement is claimed. |
| R2-03 | Bind residency regions and processing purposes | `APPROVED_DONE` | Normalized immutable Role-version rules and canonical hashes are implemented. |
| R2-04 | Preserve assignment and policy-administration evidence | `APPROVED_DONE` | Current normalized assignment plus append-only events and hardware-admin decision evidence are implemented. |
| R2-05 | Enforce Admin-only, self-change denial and separation of duties | `APPROVED_DONE` | Backend boundaries and real-DB transaction negatives pass; Phase 3 still needs browser evidence. |
| R2-05A | Define minimum and maximum retention bounds per governed data class | `DONE_LOCAL` | Exact four-class `POLICY_BOOK_V2` rules are persisted; legacy `chat_content_days` is constrained within the V2 Chat bounds and remains only the default session scheduling deadline. |
| R2-06 | Implement bounded Retention scheduler eligibility and lease fencing | `DONE_LOCAL` | Keyset scanning reaches row 26 after 25 stale rows; every expired write lease enters read-only recovery before governance checks, and write attempts plus the three-fence persistent recovery budget remain authoritative in actual PostgreSQL tests. |
| R2-07 | Recheck exact policy/version/classification/owner and every applicable Legal Hold | `DONE_LOCAL` | Hold/Role races plus inactive Workspace/Subject, expired/inactive/service membership, group/action/version/hash drift fail closed before planning and after claim with zero receipts where no write occurred. |
| R2-08 | Archive through a dedicated least-privilege port and verify immutable read-back receipts | `DONE_LOCAL` + `EXTERNAL_GATE` | The capability attestation is DB-committed before conditional `If-None-Match` create, its UUID is provider metadata, SDK retries are disabled, and cold-restart lookup binds exact attestation/full read-back with zero provider write. Policy lifecycle/V2 effectiveness, execution authorisation and capability must cover the full `[LastModified, LastModified+1s)` interval; target conformance and provider-principal attribution remain external. |
| R2-09 | Consume approved erasure intent with maker/checker/executor separation | `DONE_LOCAL` | Domain plus DB actor inequalities, fixed executor service-principal FK/config binding and SQL constraint negative pass. Physical deletion remains absent. |
| R2-10 | Add kill switch, bounded metrics and crash/restart/duplicate/hold-race tests | `DONE_LOCAL` + `EXTERNAL_GATE` | Deployment flag plus reloadable exact-value control file, fixed-label outcomes, atomic duplicate prevention, every-lease read-only recovery, three-fence transient recovery and cold-process exact receipt linkage are tested; full WSL/provider crash/soak remains external. |
| R2-11 | Connect four-class data rules and exact Role evidence to Admin UI | `DONE_LOCAL` | The Role editor covers all four classes, displays exact assignment evidence and disables manual/fallback editing for Role-bound or unverifiable legacy state. |
| R2-12 | Resolve every Admin inventory row honestly | `DONE_LOCAL` + `EXTERNAL_GATE` | Displayed collections use bounded server cursors and stale-response guards; missing audit/dictionary/profile/drill-down APIs are explicit governed-unavailable states. Actual OIDC/WebAuthn browser acceptance remains external. |
| R2-13 | Govern user registration and membership lifecycle | `DONE_LOCAL` + `EXTERNAL_GATE` | Optional Keycloak provisioning, active Role search, expiring membership/renewal and normalized evidence are wired and tested. Real IdP rollback/ceremony and multi-human acceptance remain external. |

## Request group 3 — Search, Registration, Manual/Bulk and CR

| ID | Checklist item | Current status | Evidence / remaining work |
|---|---|---|---|
| R3-01 | Restore the softer v0.3-style global search presentation | `DONE_LOCAL` + `EXTERNAL_GATE` | Bounded preview, match evidence, listbox keyboard navigation and Workspace-keyed late-response purge are source-tested; authenticated reference-viewport/browser acceptance remains external. |
| R3-02 | Use the same multi-keyword logic in global and catalog search | `DONE_LOCAL` | Both surfaces now use the fixed six-field ALL-term SQL contract; query expansion is bounded to 12 unique terms and 120 characters per term. |
| R3-03 | Return all authorized `matches` in global preview | `DONE_LOCAL` | Suggestion DTO/API/cache/UI carries database/schema plus bounded plain-text match fragments and declares `match_mode=ALL`. |
| R3-04 | Explain/fix results whose visible `matches` are empty | `DONE_LOCAL` | NAME, DESCRIPTION, SCHEMA, COLUMN, TAG and TERM all produce evidence; long separated matches are split so no fragment declares a term absent from its text. |
| R3-05 | Hydrate logical name and description for table/columns | `DONE_LOCAL` + `EXTERNAL_GATE` | The fixed DataHub query now reads bounded `SchemaField.label`; UI displays it read-only as Logical Name separately from editable merged Description. Live target-version verification remains external. |
| R3-05A | Bound provider-controlled catalog projection and browser response size | `DONE_LOCAL` + `EXTERNAL_GATE` | ADR-0039, Alembic `0045`, per-source truncation evidence, workspace/limit-bound cache schema invalidation and PostgreSQL 17.10 migration/JSONB semantic smoke tests pass. Representative target-volume `EXPLAIN (ANALYZE, BUFFERS)` remains external. |
| R3-05B | Make full DataHub reconciliation deletion-safe and million-row capable | `DONE_LOCAL` + `EXTERNAL_GATE` | ADR-0040 replaces provider offsets with a fixed server-owned scroll cursor, pre-provider workspace reservation, lock-inside idempotency replay, stable-total/distinct-seen completion, adaptive response-bounded pages, server-progress retry resume and default-off tombstones. Exact target DataHub PIT/search-backend configuration plus concurrent-mutation/expiry/replay acceptance remains external; until accepted, completion reports deletion suppressed. |
| R3-06 | Manual: server-authored CSV → MinIO → Airflow → DataHub read-back | `DONE_LOCAL` + `EXTERNAL_GATE` | Sparse browser edits are rehydrated from a fresh complete provider snapshot, written once as an immutable legacy-named CSV receipt and applied through database-time leases. Five ordered Aspect writes require full hash read-back and append-only success/failure evidence. `0047` atomically binds every authenticated Airflow run-call replay to a canonical claim receipt and proactively closes an older expired receipt when a newer claim wins. Local S3 conditional-create and source/DB tests pass; external MinIO, Airflow OIDC and DataHub 1.6 end-to-end acceptance remain external. |
| R3-07 | Bulk: parse candidates and apply governed row additions to DataHub | `DONE_LOCAL` + `EXTERNAL_GATE` | Commit `39d20d0` adds exact CSV/XLSX table/column/domain/term/tag profiles, immutable V3 row/group evidence, bounded spool replay, local controlled-vocabulary UUIDs, one-candidate/one-CR fixed-Aspect compilation, transaction-locking human reauthorization and exact provider read-back. Backend `1,297 passed + 51 skipped`, frontend `45/238`, deterministic `0001`, isolated PostgreSQL `5/5` and independent P0/P1 reviews pass. External Airflow/MinIO/DataHub, real multi-actor identity, WSL amd64 and representative full-worker load/recovery remain open; raw direct writes stay forbidden. |
| R3-08 | Restrict Manual/Bulk to Admin/Data Steward and validate DataRiver OIDC | `DONE_LOCAL` + `EXTERNAL_GATE` | Active-human Admin/Data Steward authorization precedes every registration read/mutation; owner/Admin history and actual PostgreSQL Admin/Steward/service/inactive/expired/cross-workspace RLS negatives pass. Real Keycloak multi-human and external Airflow client-credential journeys remain external. |
| R3-09 | Require individual DataHub authentication for writes | `CONFLICT` | Accepted architecture uses a scoped server service principal and forbids provider credentials in the browser. Resolve desired federated user evidence versus service authorization in a new ADR. |
| R3-10 | Create `datariver-infoschema` and preserve the approved legacy filename contract | `DONE_LOCAL` + `EXTERNAL_GATE` | Storage init and `UPLOAD_METADATA_MANUAL_YYMMDD_SERIAL.csv` contract exist; verify external provider permission. |
| R3-11 | Show final enrichment/read-back report | `DONE_LOCAL` + `EXTERNAL_GATE` | Cursor-bounded owner/Admin history and an exact submission report expose ordered attempts and five Aspect outcomes without raw provider responses. Polling is bounded and hidden-tab aware. Live DataHub enrichment acceptance remains external. |
| R3-12 | Diagnose preparation-PC Change Management and run development use cases | `DONE_LOCAL` + `EXTERNAL_GATE` | CR lists use server state filters, keyset summaries and bounded selected detail/attachment/apply evidence; typed candidates atomically bind one item/outbox. `0048` prevents completed DataHub apply jobs from being reclaimed or their APPLIED/APPLY_FAILED request from being rewound. `0049`/`0050` precommit globally unique object identity; return `202 STARTED`; give the BYPASSRLS upload role zero direct ledger privileges and require its bounded `FOR UPDATE SKIP LOCKED` function to claim, HEAD and fully hash the provider bytes; then reauthorize the current human before finalization. Lost POST/finalize responses recover only by the exact client upload UUID and private status endpoint. Operator recovery is server-filtered to the current round and STORED state before a ten-row limit, pauses while the browser is hidden and surfaces partial failure. Current source and Mac PostgreSQL gates pass. WSL DB/network logs, target S3 consistency and authenticated multi-actor journeys remain external. |

## Request group 4 — Knowledge, Chat, catalog API and MCP

| ID | Checklist item | Current status | Evidence / remaining work |
|---|---|---|---|
| R4-01 | Probe Neo4j plus Chat, Embedding and Reranker adapters before feature execution | `DONE_LOCAL` + `EXTERNAL_GATE` | Current Mac evidence proves authenticated Neo4j `RETURN 1`, strict-JSON Chat and 1,024-dimensional Embedding inference. The installed local Ollama reranker honestly fails the fixed contract: `/v1/rerank` is absent. Revision `0053` adds a bounded fixed private reranking TEST without inventing runtime activation. WSL/private-provider DNS, TLS, credentials and responses remain unverified. |
| R4-02 | Compare v0.3 code/docs and retain safe functional intent | `PARTIAL` | Registry, changesets, releases and typed studio exist; keep a traceable safe-substitution matrix. |
| R4-03 | Define and manage Knowledge Graph/Ontology assets | `PARTIAL` | Schema/domain/ontology/changeset/release contracts, durable PDF-to-DRAFT analysis and atomic independently reviewed publication/receipt-backed activation are implemented. Remaining Mode A lifecycle UX and target acceptance stay open. |
| R4-04 | Generate typed KG proposals from sources with provenance | `DONE_LOCAL` + `EXTERNAL_GATE` | Revision `0054` provides pinned, fenced, retryable/cancellable PDF-to-typed-DRAFT jobs with pre-egress and final reauthorization, atomic evidence, active-first bounded owner history and a separately credentialed worker. DB schema sources, target WSL/private-provider IAM/TLS/recovery/load and human acceptance remain external or later scope. |
| R4-05 | Populate, publish, project and evaluate graph assets | `PARTIAL` | Publication is one PostgreSQL UoW, canonical read-back is verified and activation is separate. Neo4j is only an ID-selecting rebuildable shadow: prompt evidence is rehydrated from PostgreSQL, and its receipt is bound to the exact adapter/target/hash/count. Releases without governed lineage are invisible to all release consumers. Durable projection worker/rebuild/drift/evaluation and target live acceptance remain. |
| R4-06 | Search metadata and graph assets and run graph-grounded assistant tests | `PARTIAL` | Separate bounded Knowledge GraphRAG exists; current canonical/policy hardening and general Chat integration remain. |
| R4-07 | Implement Chat `GENERAL` mode | `PARTIAL` | Grounded composer exists, but no public typed mode contract/session UX. |
| R4-08 | Implement Chat `VECTOR` mode | `PENDING` | No integrated embedding retrieval mode. |
| R4-09 | Implement Chat `GRAPH` mode | `PARTIAL` | Knowledge-specific GraphRAG exists; no general Chat mode integration. |
| R4-10 | Implement `AUTO` intent routing with explicit evidence and policy | `PENDING` | UI label is decorative; no Tool Calling/Semantic Router contract, confidence, audit or safe no-route state. |
| R4-11 | Let users select a governed Topic/Graph asset for deep answers | `PARTIAL` | Knowledge screen selects a release; general Chat topic routing is absent. |
| R4-12 | Expose selected catalog capabilities through typed HTTP APIs | `PARTIAL` | Catalog and release-pinned Sharing APIs exist and revalidate governed release lineage on list/detail, replay, publish, grant and invocation. Atomic quota/result replay hardening under R5-BE-05 and target evidence remain. |
| R4-13 | Implement official MCP JSON-RPC `tools/list` and `tools/call` | `PENDING` | No MCP route/server/test exists. Add ADR, threat model, allowlisted typed tools, pagination and authorization. |

### Phase 5 durable Knowledge source job closure — 2026-07-24

- [x] ADR-0044, PRD/checklist, SQLAlchemy metadata, generated `0001`, additive `0054`,
  feature/API/data/deployment/operations/migration docs and README agree.
- [x] Whole backend `1,369 passed / 84 environment-gated skipped`; whole frontend `45 files /
  243 tests`, type/lint/build; Ruff, strict mypy and static verification passed.
- [x] Additive `0053 -> 0054` and completely empty canonical `0001 -> 0054` PostgreSQL databases
  each passed `24` app/worker/owner/cross-service role tests. Dirty DELETE privilege was reconciled;
  unsafe worker role membership and shared evidence forgery failed closed; canonical `0001`
  reproduced twice at SHA-256
  `a9978344ab90982c6d5f6c8929b8a976f34418d5fbcae2a8de6758171bda6f98`.
- [x] Application/UI/portability and DB/security independent audits reported `P0=0`, `P1=0`; PM
  traceability P1 findings were corrected before close. Residual P2 hardening is owned in the Phase
  checklist and Request group 5.
- [ ] Target WSL `linux/amd64`, external MinIO/S3 IAM, private OpenAI-compatible provider,
  distinct-human browser and target load/recovery evidence remain `EXTERNAL_GATE`.

## Request group 5 — platform audit, remediation and portability

### Completed audit evidence

- [x] Backend tree-wide static/test audit followed by DB/session/cache/memory/security hot-spot review.
- [x] Frontend tree-wide type/lint/test/build audit followed by browser state/memory/security review.
- [x] Current Mac daemon and Buildx platform capability inspection.
- [x] Backend and frontend cache-only `linux/amd64` cross-build.
- [x] arm64/amd64 registry manifest verification for nine pinned core images.
- [x] Independent software-quality, security, frontend-state and PM/Audit reviews.

### Remediation backlog

| ID | Priority | Checklist item | Status |
|---|---:|---|---|
| R5-BE-01 | P0 | Make Knowledge changeset publication one UoW and separate publish from activate; inject failures between steps. | `DONE_LOCAL`; atomic read-back-verified publication, fault injection, idempotency and concurrency pass on PostgreSQL. |
| R5-BE-02 | P0 | Rehydrate current canonical release/hash and enforce classification/provider/retention policy before GraphRAG. | `PARTIAL`; governed lineage, exact release snapshot/hash, graph/source classification and provider binding fail closed. General Chat retention/profile routing remains in the Chat phase. |
| R5-BE-03 | P0 | Prevent direct release publication from bypassing independent changeset review. | `DONE_LOCAL`; direct route is `410`, legacy unlineaged releases are hidden from all consumers and activation requires one exact reviewed lineage. |
| R5-BE-04 | P0 | Record the actual Chat provider/model/external-use audit facts. | `DONE_LOCAL` + `EXTERNAL_GATE`; current Mac Neo4j/Chat/Embedding pass, local reranking is unavailable, and WSL/private-provider facts remain target evidence. |
| R5-BE-05 | P0 | Make API-product idempotency, per-minute/monthly quota checks and invocation/result recording atomic; bind request hash and replayable response so retries cannot bypass quota or repeat work. | `PENDING` |
| R5-FE-01 | P0 | Bind global search requests/results to Workspace epoch and abort/discard cross-workspace responses. | `DONE_LOCAL`; Top Navigation keys the search component by Workspace and a late-response regression proves purge/discard. |
| R5-FE-02 | P1 | Bind Admin context/auth hydration and renewal to subject/session epoch. | `PENDING` |
| R5-FE-03 | P1 | Preserve CSP/security headers in every Nginx location. | `PENDING` |
| R5-FE-04 | P1 | Validate runtime API/OIDC origins before any Bearer-bearing request. | `PENDING` |
| R5-FE-05 | P1 | Bound Chat history/DOM and lineage concurrency/nodes; abort unmounted work. | `PENDING` |
| R5-FE-06 | P1 | Render the actual selected Chat provider/model/external-use policy instead of a hard-coded local-only assurance. | `PENDING` |
| R5-FE-07 | P1 | Replace internal object/source locators with authorized opaque evidence references in browser responses and views. | `PENDING` |
| R5-DATA-01 | P1 | Add cursor pagination/set-based reads to Governance, Knowledge, Sharing and Admin; remove identified N+1 paths. | `PENDING` |
| R5-DATA-02 | P1 | Budget API/worker DB pools against replicas and PostgreSQL `max_connections`; cap Redis pools. | `PENDING` |
| R5-DATA-03 | P1 | Move large PDF and XLSX work to bounded durable/spooled paths with explicit resource rejection. | `DONE_LOCAL` + `EXTERNAL_GATE`; XLSX uses the bounded spool path and revision `0054` moves PDF-to-DRAFT into a separate bounded worker with 50 MiB/500-page/per-page/provider-batch rejection. Target kill/retry/load/RSS evidence remains open. |
| R5-DATA-04 | P2 | Make durable same-transaction evidence fences robust to PostgreSQL XID wrap semantics. | `PENDING`; Phase 5 uses current-row `xmin`/XID equality and carries the hardening explicitly. |
| R5-DATA-05 | P2 | Add positive generic outbox schema-version/attempt checks after auditing all trusted producers. | `PENDING`; Phase 5 Knowledge events are producer-fenced and relay-immutable outside delivery fields. |
| R5-SEC-01 | P1 | Constrain System Settings probes against SSRF/DNS rebinding/localhost and response-size abuse. | `PARTIAL` + `EXTERNAL_GATE`; fixed routes/bodies, pre-DNS exact operator allowlists, resolved-address checks, nonlocal TLS/private-network enforcement, disabled redirects/environment proxies and decoded-response bounds pass. The default HTTP transport still resolves the hostname again at connect time, so vetted-address pinning with original-host TLS verification and a rebinding regression remain open before this item can close. |
| R5-SEC-02 | P1 | Harden OIDC token type/authorized-party/size and unknown-key refresh behavior. | `PENDING` |
| R5-SEC-03 | P1 | Harden the Keycloak Admin adapter proxy/TLS/environment/body-size boundary and prevent credential-bearing redirect or proxy inheritance. | `PENDING` |
| R5-SEC-04 | P1 | Fail production startup unless TrustedHost, exact CORS and public-origin/TLS settings are coherent and non-wildcard. | `PENDING` |
| R5-SEC-05 | P1 | Keep object keys, provider locators and internal endpoints out of ordinary API/UI payloads; add negative disclosure tests. | `PARTIAL`; durable Knowledge jobs use opaque snapshot/page evidence and negative API/UI tests. The same review remains open across every other ordinary payload. |
| R5-SEC-06 | P1 | Keep Keycloak realm roles/display markers non-authoritative; authorization remains exact Workspace membership, policy and RLS. | `PENDING` |
| R5-SEC-07 | P2 | Measure and further narrow the authorization-to-provider-call window for inference egress. | `PENDING`; Phase 5 reauthorizes before each bounded call and before final persistence, but does not claim zero call-time TOCTOU. |
| R5-DEP-01 | P0 | Fix blank WSL bootstrap token instructions and raw-Compose external-network failure. | `PENDING` |
| R5-DEP-02 | P1 | Add env schema/version migration and Bash/PowerShell profile parity. | `PENDING` |
| R5-DEP-03 | P1 | Resolve the literal `.env`/Compose `linux/amd64` request against ADR-0034: compose-wide amd64 forcing conflicts with native Mac runtime safety, so runtime stays native and validated while explicit `--platform` is restricted to release builds. Record the accepted substitution and never hardcode `FROM --platform=linux/amd64`. | `CONFLICT` |
| R5-DEP-04 | P1 | Pin Airflow/APISIX/observability images and dependency hashes; reject unpinned production overrides. | `PENDING` |
| R5-DEP-05 | P1 | Reduce Compose network, host-gateway, secret, writable-path and runtime-principal blast radius per process and verify no-new-privileges/read-only/capability boundaries. | `PARTIAL`; the Knowledge worker has a non-root read-only container, worker-only spool, process-specific DB/S3/LLM secrets and no Neo4j dependency. Cross-platform review of the remaining processes is still pending. |
| R5-DEP-06 | P2 | Fingerprint controlled migration function bodies/owners during additive re-entry. | `PENDING`; current re-entry validates required object names, grants and policies but not every body hash. |
| R5-TEST-01 | P2 | Complete the remaining durable Knowledge enqueue no-row and maximum-attempt exhaustion matrices. | `PENDING`; exact unclaimed cases are listed in the Phase 5 checklist. |
| R5-ARCH-01 | P2 | Split high-complexity Admin/config/DataHub/catalog/knowledge modules only after behavior tests lock contracts. | `PENDING` |
| R5-ARCH-02 | P2 | Consolidate duplicate upload/hash/polling state machines and clean only evidenced dead legacy code. | `PENDING` |

## Request group 6 — final controlled artifacts

These files start only after every preceding implementation/remediation package and the required
target WSL acceptance complete. If target access is unavailable, only an explicitly user-approved
`target-gated draft` may be written; it cannot be accepted as final until target evidence is merged.
Existing `docs/04_FEATURE_SPEC.md`, `docs/05_API_SPEC.md`, and `docs/06_DATA_MODEL.md` are useful
baselines, but they are not accepted as the requested final deliverables until regenerated against
the final source and audited.

The original artifact gate 5 is executed as **5A `README.md`** and then **5B
`ARCHITECTURE.md`** to preserve the one-file-at-a-time rule; completing 5A does not close gate 5.
For every deliverable, author exactly one file, run the PM/traceability review, save it, report its
completion and residual gaps to the user, and only then begin the next file. Do not batch files.

Every final file must support a blank-slate rebuild without code archaeology. It includes assumptions,
setup inputs, unavailable/external gates, and forward/reverse stable-ID traceability across
requirement → feature → API/tool → DB → UI → test → operations.

| Order | Deliverable | Required content | Gate |
|---:|---|---|---|
| 1 | Feature specification | actors, roles, capabilities, workflows, state machines, policy, failures, NFRs, acceptance and safe substitutions | save one Markdown file, PM audit, report completion before order 2 |
| 2 | API specification | every route/tool, auth/assurance, request/response/error, cursor/idempotency/concurrency, examples, MCP and provider boundaries | complete only after feature trace passes |
| 3 | Table specification and ERD | canonical ownership, columns/types/defaults, PK/FK/UQ/CHECK/index/RLS, lifecycle, retention, migration and complete Mermaid ERD | metadata/migration/doc deterministic agreement |
| 4 | Screen specification | route, role, layout, fields/actions, loading/empty/error/denied/degraded, API mapping, pagination, accessibility and responsive behavior | current UI plus accepted unavailable states |
| 5A | `README.md` | clean initialization, selectable topology, seeds, governance, operations, migration and verification entry points | commands rerun from a clean environment where locally possible; report before 5B |
| 5B | `ARCHITECTURE.md` | system context, containers/processes, ownership, data/security flows, deployment matrices, HA/failure model, ADR index | root file is the entry-point summary; `docs/03_ARCHITECTURE.md` remains the authoritative detailed controlled architecture |
| 7 | Final audit and commit | end-to-end traceability, stale-claim scan, all applicable gates and exact residual external gates | one final documentation commit after per-file reports |

## Known controlled-document conflicts to resolve

- [ ] `docs/03_ARCHITECTURE.md` contains an obsolete claim that current Chat makes no model call.
- [ ] `docs/04_FEATURE_SPEC.md` understates the current Bulk preparation worker while DataHub Bulk
  mutation remains genuinely absent.
- [ ] `docs/20_ENTERPRISE_UI_COMPLETION_PRD.md` and checklist still describe optional governed IdP
  user creation as absent.
- [ ] `docs/12_ACCEPTANCE_REPORT.md`, `docs/16_PHASE_EXECUTION_CHECKLIST.md`,
  `docs/21_ENTERPRISE_UI_COMPLETION_CHECKLIST.md`, `docs/25_LOW_RESOURCE_MULTIARCH_EXECUTION_CHECKLIST.md`
  and `docs/28_POLICY_BOOK_EXECUTION_CHECKLIST.md` contain scope-specific evidence from different
  commits. Add an evidence-scope/current-HEAD marker; do not merge their counts.
- [ ] Statements that no P0/P1 issue remains are stale after the current audit.
- [ ] Root `ARCHITECTURE.md` is absent; `README(KOR).md` has no declared translation-drift owner.
- [ ] MCP, Chat mode routing, global-search match fragments, Manual read-back reports and the final
  screen specification have broken requirement→API→DB→UI→test→ops traceability.

## Per-work-package start checklist

- [ ] Re-read the exact request IDs and all linked accepted ADRs.
- [ ] Confirm the worktree and preserve unrelated/user-owned changes.
- [ ] State canonical owner, external dependencies and failure mode.
- [ ] Write failing positive/negative tests before behavior changes.
- [ ] Define memory, page, concurrency, retry, timeout and idempotency bounds.
- [ ] Define authorization, assurance, workspace/RLS, secret and audit boundaries.
- [ ] Identify source-only, local runtime and target-environment gates separately.
- [ ] Assign bounded read-only independent reviews with no overlapping file ownership. Feature/UI
  packages record UI/UX, software-quality, data-engineering and data-governance/process conclusions,
  disposition and rerun evidence; the primary agent owns integration and final verification.

## Per-work-package exit checklist

- [ ] Focused tests pass, including denial, stale-version, replay and dependency-failure cases.
- [ ] Ruff/strict mypy/relevant Pytest/static checks pass for backend changes.
- [ ] TypeScript/ESLint/relevant Vitest/build pass for frontend changes.
- [ ] Schema, migration and `docs/06_DATA_MODEL.md` agree when DB changes.
- [ ] Architecture changes have an accepted ADR and deployment/docs changes have rendered configs.
- [ ] Independent findings are dispositioned and accepted fixes are rerun by the primary agent.
- [ ] Current evidence and residual external gates are written without promoting historical results.
- [ ] `git diff --check` passes; the focused commit message describes only the accepted package.

## Final release acceptance still requiring the target environment

- [ ] Exact current source and `linux/amd64` artifacts import with matching checksums and platform IDs.
- [ ] PostgreSQL logical restore and Alembic head verification succeed on WSL.
- [ ] Keycloak issuer/redirect/WebAuthn and representative positive/negative authorization succeed.
- [ ] External Redis, MinIO/S3, DataHub, Airflow, telemetry and OpenAI-compatible providers pass
  their typed probes without credentials entering the browser or DB.
- [ ] Neo4j rebuild, drift/read-back and failure recovery succeed from PostgreSQL canonical releases.
- [ ] Low-resource load/soak, backup/restore and rollback evidence is accepted.
- [ ] Single-node preparation is not represented as production HA; HA promotion requires a separate
  multi-failure-domain topology, capacity decision and recovery drill.
