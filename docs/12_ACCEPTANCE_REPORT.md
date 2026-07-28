# Acceptance report — development/integration baseline

Report date: 2026-07-17 (Asia/Seoul)
Artifact: historical Windows/WSL development baseline; later addenda identify their exact source
boundary
Environment: Windows + WSL2 Ubuntu 22.04, Docker Engine 29.6.0, Compose 5.2.0  
Toolchain: Python 3.12.12, uv 0.9.17, Node.js 22.19.0, npm 10.9.3  
Decision: **development and local integration baseline accepted; production release not accepted**

This historical report superseded the source-only report and the runtime-open statements in the
2026-07-14 independent reviews at the time it was written. It is not evidence for the current
working tree, a signed release artifact or production. Current status is controlled by the dated
addenda and `docs/29_MASTER_EXECUTION_BACKLOG.md`.

P0–P3 foundation addendum, updated 2026-07-16: current source checks additionally include the stable DataHub v1.6.0 release contract and typed OIDC assurance. Hardware WebAuthn requires an exact approved ACR+AMR combination and `auth_time`; OTP, generic MFA and refreshed-token `iat` cannot satisfy high-risk authorization. Browser remediation is bounded to typed authentication actions, rejects unsafe return locations, and never automatically replays a denied mutation after an authentication redirect. Compatibility migrations and the current hybrid runtime have separate live evidence below.

## Knowledge Studio Phase 6 RC preparation addendum — 2026-07-28

This addendum accepts the local source/runtime Graph Builder scaffold for RC visual testing. It
does not accept Step 2 typed-operation persistence, target production identity, HA or production
cutover.

| Gate | Result | Current executed evidence |
|---|---|---|
| Empty/manual canvas contract | PASS (local source) | Step 2 starts without a node or relation. Only a user-entered label creates a browser-memory node; drag/connect/selected delete do not mutate Draft T-Box, Publish, DataHub or Neo4j. The UI continues to report `Accepted T-Box · 0개`. |
| Lifecycle boundary | PASS (local source) | REVIEW/PUBLISHED/DISCARDED lock all scaffold mutations. A local node cannot satisfy the server Accepted-T-Box gate for A-Box transition. |
| Regression | PASS | Repository Ruff format `427` files and lint, strict mypy `421` files, backend `1,694 passed / 97 skipped`, static verification, frontend TypeScript/ESLint, `55 files / 303 tests` and production build passed. Focused Studio `2 files / 8 tests`; normalized DataHub format baseline `49 tests`. |
| Mac runtime | PASS (development) | Stable `dev-publish` applied PostgreSQL `0058 -> 0061`, roles, API/Web/Keycloak, DataHub `v1.6.0` and a 2,000-row catalog projection sync. API readiness and Web health returned success. |
| Authenticated browser journey | OPEN | The visible local browser reached the canonical Keycloak login form, but no existing user session was available. Credentials/tokens were not bypassed. Human login followed by add/drag/connect/delete/refresh capture remains the final UI sign-off gate. |

## Knowledge Studio governed Publish addendum — 2026-07-28

This addendum accepts the local-source contract at revision `0061` for independent-review
schema/mapping publication. It does not accept actual A-Box ingestion, Neo4j instance publication,
target PostgreSQL execution, a live physical-source adapter, the pending Step 2 operation writer or
Registry wide-drawer cutover.

| Gate | Result | Current executed evidence |
|---|---|---|
| Maker-checker publication | PASS (local source) | DRAFT submits to locked REVIEW; the author and service accounts cannot publish. A different reviewer needs `kg.review`, high-risk `kg.publish`, domain/classification scope and fresh Hardware WebAuthn. The same reviewer must own an exact-version/hash PASS receipt. |
| Atomic canonical materialization | PASS (local source) | Publish creates Ontology Version/element index, immutable Binding/Rule versions, Studio Release, PUBLISHED Draft references, graph schema pointer, outbox and idempotency result in one transaction with canonical T-Box/A-Box read-back. One ACTIVE Studio Release per graph is DB-enforced and its predecessor becomes ARCHIVED. |
| Instance separation | PASS (local source) | `active_studio_release_id` is separate from `active_release_id`; no `knowledge.releases`, row ingestion, DataHub mutation or Neo4j write occurs. UI reports `Ingestion: NOT_RUN`. |
| Physical-source/cleanup boundary | PASS (local source) | Registry adapter accepts exact Workspace/Asset/version/field/clearance contracts and bounded scalar rows. CSV/SQLite shells fail closed until operator registration. Cleanup is dry-run by default and only Discards exact ETag Drafts or unlinks exact hash-matched Git-untracked test files. |
| Regression/migration | PASS WITH FORMAT BASELINE | Focused backend `39`; backend `1,694 passed / 97 skipped`; Ruff lint, strict mypy over `421` files and static verification passed. Frontend TypeScript, ESLint, `54 files / 300 tests` and production build passed; focused Studio `2 files / 8 tests`. Repeated canonical generation produced SHA-256 `185641e239e82d7f6948e761fd929a618fdacaebc766cbb45f031a713728eba1`; sole head `0061`. The repository-wide format check retains only two unrelated pre-existing DataHub files. |
| External acceptance | OPEN | Isolated PostgreSQL upgrade/app-role RLS/concurrent Publish and rollback fault injection, real two-human OIDC/WebAuthn, browser accessibility, approved row adapter, WSL `linux/amd64`, full Step 2, Registry cutover, durable ingestion and managed default graphs remain open. |

## Knowledge Studio Data Enricher addendum — 2026-07-28

This addendum accepts the local source contract for normalized A-Box Binding Drafts at revision
`0060`. It does not accept actual row ingestion, materialization/publication, target PostgreSQL,
live DataHub drift or the still-pending Step 2 accepted-operation writer.

| Gate | Result | Current executed evidence |
|---|---|---|
| T-Box/A-Box boundary | PASS (local source) | A bounded accepted T-Box read index is separate from normalized source/binding/rule children. Binding PATCH has no T-Box, graph, release, Neo4j, DataHub mutation or ingestion command. |
| Source and mapping contract | PASS (local source) | Authorized Dataset discovery applies the Draft classification ceiling in the local projection. Detail uses the governed DataHub gateway/cache. Exact provider-schema and projection versions, classification, stable targets and server-returned fields are rechecked; only four typed methods and `IDENTITY@1` are representable. |
| Concurrency/security | PASS (local source) | Target-scoped PATCH requires `If-Match` and `Idempotency-Key`, locks the Draft/target/projection, returns `412` on a stale Draft and commits an exact replay snapshot. Four child tables use FORCE RLS/restrictive owner policies and composite `RESTRICT` foreign keys. |
| UI | PASS (local source) | Accepted classes render in React Flow; node selection opens the Data Binding Panel, Dataset/column mapping persists, mapped nodes become green with an accessible `Mapped · DRAFT` label, and Mapping/ingestion status remain distinct. A 412 preserves local input until explicit reload or latest-ETag overwrite. |
| Regression/migration | PASS WITH FORMAT BASELINE | Focused backend `85`; backend `1,670 passed / 97 skipped`; Ruff lint, strict mypy over `414` files and static verification passed. Frontend TypeScript, ESLint, `54 files / 296 tests` and production build passed. Repeated canonical generation produced SHA-256 `978de14ce3e5947e5be3d4d67b34aba60e5029ed542ce805596eec11785f7f40`; sole head `0060`. The repository-wide format check retains only two unrelated pre-existing DataHub files. |
| External acceptance | OPEN | Isolated PostgreSQL migration/app-role RLS/concurrency, live DataHub schema drift, browser accessibility, target WSL `linux/amd64`, the Step 2 accepted-operation writer and real A-Box ingestion/materialization remain open. |

## Knowledge Studio Draft/Step 1 addendum — 2026-07-28

This addendum accepts the local source contract for author-only Studio Draft create/read/autosave,
bounded domain selection, ETag `412` recovery and routing from saved Step 1 to the T-Box foundation.
It does not accept target-browser storage durability, real concurrent identities or target
PostgreSQL lock/RLS behavior.

| Gate | Result | Current executed evidence |
|---|---|---|
| Command/read boundary | PASS (local source) | Typed domain/create/read/autosave/advance APIs; graph type remains server-owned; Step 1 creates no graph/release/projection. Exact domain source version, author scope, classification ABAC and endpoint alias are checked before commit. |
| Concurrency/idempotency | PASS (local source) | Auto-save/advance require quoted integer `If-Match`; stale versions use a distinct 412 domain error. Advisory-key serialization, Draft row locking and exact actor/request-bound response snapshots implement safe replay. Focused backend selection passed `27`. |
| Browser recovery | PASS (local source) | Typed form revisions enter same-origin IndexedDB before transmission; no token, role or raw tenant/Subject enters the record. Server writes are debounced 1.5 seconds, offline work retries on `online`, and a queue write failure prevents transmission. Both 412 choices preserve local input until the user decides. |
| Regression | PASS WITH FORMAT BASELINE | Backend `1,655 passed / 97 skipped`; Ruff lint, strict mypy over `412` files and static verification passed. Frontend TypeScript, ESLint, `53 files / 294 tests` and production build passed. Changed files pass Ruff format; the repository-wide format check still identifies two unrelated pre-existing DataHub files. |
| External acceptance | OPEN | Isolated PostgreSQL same-key/different-key interleavings and app-role RLS, real multi-tab/two-session conflict, storage eviction/profile deletion, supported target browsers and WSL `linux/amd64` remain external gates. |

## Phase 6E web Nginx security-header addendum — 2026-07-24

This addendum currently records the implementation, whole-source regression and focused runtime
evidence for `R5-FE-03`. Local closure still requires final independent reviews and the focused
commit. It does not accept the real TLS/APISIX edge, browsers or WSL `linux/amd64`.

| Gate | Result | Current executed evidence |
|---|---|---|
| Inheritance defect | PASS (local source) | Nginx `1.30.3` recursively merges the five canonical server `always` rules into cache-defining locations. Static verification rejects a missing merge or noncanonical rule. |
| API normalization | PASS (local runtime) | Static/unit gates require exactly the canonical five-name hide set. A fixture upstream supplied conflicting copies of all five fields; the web edge returned one canonical copy while preserving private/no-store cache, authentication, retry, exact ETag/Vary, content-disposition and request-ID fields. |
| Route/status matrix | PASS (local arm64) | Current-source image `sha256:d61cabbcf73c731829476f09572ed2b5c9157fb0f44be0cdded4b862613ad88f` passed health/runtime/root/SPA/asset/API `200`, asset `304/404`, upstream `503` and proxy-down `504`, with exact header cardinality and cache semantics. Its embedded template/main/entrypoint hashes matched current source; no replacement bind mount supplied the tested configuration. |
| Focused/static gates | PASS | New source/parser/safety tests `3/3`; empty and populated render `nginx -t/-T`; repository static verification passed. Static and live gates reject HSTS on the direct inner HTTP server while leaving approved HTTPS-edge HSTS as an external gate. |
| Whole-source regression | PASS | Backend `1,424 passed / 97 skipped`; Ruff format over `384` files, Ruff lint, strict mypy over `377` files and static verification; frontend `47 files / 266 tests`, type/lint/build. Two pre-existing async Governance assertions exposed by concurrent runs now await server detail and attachment-control rendering; the file passed `18/18` in three concurrent processes before the whole rerun passed. |
| Independent review | PASS (local source/runtime) | Final security, SRE/test and PM/traceability re-audits independently report `P0=0`, `P1=0`. Findings for exact API hide-set/application-header evidence, inner-HSTS absence, stale mounted-source evidence, document status and flaky async assertions were corrected before all applicable gates were rerun. |
| External acceptance | OPEN | Native WSL amd64 release image, real TLS/HSTS/APISIX preservation, Chrome/Firefox/Safari, OIDC callback/renewal and approved DataHub/Grafana frame journeys remain `EXTERNAL_GATE`. |

## Phase 6D Admin/auth session-epoch addendum — 2026-07-24

This addendum accepts local source closure of `R5-FE-02`. It does not accept real IdP session
semantics, target-browser cache behavior or WSL `linux/amd64`.

| Gate | Result | Current executed evidence |
|---|---|---|
| Identity hydration | PASS (local source) | Generation plus AbortController makes hydration latest-only; OIDC/server subjects must match; unload and sign-out invalidate memory first. A/B ordering, delayed unload, mismatch, cross-sub renewal, failed newer load and old-renewal/new-session races are tested. |
| Request boundary | PASS (local source) | Every request/download captures Workspace plus opaque security epoch and rechecks after fetch, renewal, retry and body parsing. Epoch drift forbids a second request, including durable-idempotency mutation retry, and discards late JSON/blob results. |
| Admin/UI teardown | PASS (local source) | Every accepted hydration suspends and rechecks Admin eligibility without remounting unrelated features. An unchanged context resumes the mounted subtree and preserves drafts; Workspace/epoch or Admin-context fingerprint change, mismatch or denial remounts/purges it. Manual refresh is no-store, validates Workspace, clears old context/confirmation/keys and remains empty on denial. |
| Cache/storage | PASS (local source) | `/auth/me` request and `/admin/me` request use no-store; both successful backend responses are `private, no-store`. Static verification finds no browser-persistent token/profile/role/Admin/epoch state; PKCE transaction state remains the bounded exception. |
| Regression | PASS | Focused `7 files / 69 tests`; backend `1,421 passed / 97 skipped`; Ruff format/lint, strict mypy over `375` files and static verification; frontend `47 files / 266 tests`, type/lint/build. No schema changed. |
| Independent review | PASS (local source) | Final security, application/persistence and PM/traceability re-audits independently report `P0=0`, `P1=0`. The earlier renewal-event, synchronous-epoch, initial-load, Admin refresh and same-session draft-preservation findings were corrected before rerunning their applicable gates. |
| External acceptance | OPEN | Real Keycloak/OIDC renewal, account/session switch, logout/rotation/revocation, multi-tab behavior, Chrome/Firefox/Safari and APISIX/Nginx cache preservation, two-human slow-response E2E and WSL `linux/amd64` remain `EXTERNAL_GATE`. |

## Phase 6C atomic Sharing hardening addendum — 2026-07-24

This addendum accepts local source and isolated-PostgreSQL closure of `R5-BE-05H`. It retains
ADR-0045 and revision `0055`; it does not accept the preparation PC, production identity, target
load or physical retention execution.

| Gate | Result | Current executed evidence |
|---|---|---|
| Failure atomicity | PASS (local/isolated DB) | Timeout, invalid canonical JSON and injected result, monthly aggregate and deferred-commit failures each leave ledger/result/month usage at zero; a later valid call succeeds exactly once. |
| Identity and fixed capabilities | PASS (local/isolated DB) | Missing, human, inactive, expired-membership and cross-Workspace Subjects create no grant artifacts. Missing or mismatched Workspace/Subject context cannot prepare or complete, and the app role retains no direct evidence-table access. |
| Replay and concurrency | PASS (isolated PostgreSQL 17) | Permission, product-version, expired-grant, lineage, active-policy and result-deadline drift deny disclosure without executing. Invoke-first and mutation-first revoke/publish schedules use observed database lock blockers and finish without deadlock or partial evidence. |
| HTTP and quota | PASS | Rate-limit problem JSON is stable, every domain error is `private, no-store`, per-minute retry is 60 seconds and monthly retry is a database-time-derived advisory with a 60-second floor. Concurrent RPM/month admission remains exactly one and every retry rechecks the current UTC month. |
| Regression and migration | PASS | Focused `39`; clean-room PostgreSQL `13`; backend `1,419 passed / 97 skipped`; strict mypy over `374` files; static verification; frontend `46 files / 244 tests`, type/lint/build. No schema changed; canonical/additive/downgrade/tamper gates and SHA-256 `ffc0abb58b3f4550bcc5d1524ffd9cd954076d0bf73112cab19fc7b3252e7c2f` remain clean. |
| Independent review | PASS (local source/isolated DB) | Final SQL/security, persistence/test and traceability reviews each report `P0=0`, `P1=0`. A strict-mypy cleanup error and UTC-rollover Retry-After overstatement found during review were corrected and all applicable gates rerun. |
| External acceptance | OPEN | WSL `linux/amd64`, real Keycloak service Subject/issuer/client revocation and rotation, representative target lock/load/soak and accountable physical purge evidence remain `EXTERNAL_GATE`. |

## Phase 6B atomic Sharing invocation addendum — 2026-07-24

This addendum accepts local source and isolated-PostgreSQL closure of `R5-BE-05` at revision `0055`.
It does not accept the preparation PC, production identity/provider policy, target load or physical
retention execution.

| Gate | Result | Current executed evidence |
|---|---|---|
| Atomic contract | PASS (local/isolated DB) | Fixed Snapshot/Neighbors/local-Chat execution performs no external provider call. Exact result, immutable ledger and UTC-month usage commit together or not at all; replay returns the stored document without executor or quota. The authorization-only route is `410`. |
| Identity and disclosure | PASS (local/isolated DB) | V2 grants bind active non-expiring service Subject + membership + issuer + client. First call and replay recheck current authority, governed lineage, permission fingerprint and retention binding. The app role has none of seven evidence-table privileges; fixed functions are app-only and immutable/exact-result triggers must be enabled. |
| PostgreSQL and migration | PASS (isolated PostgreSQL 17) | The repository-owned clean-room harness passed `9` app/owner tests for concurrency, quota, DB-clock boundaries, rollback, replay drift, legacy usage, locking, RLS and immutable evidence. The additive path preserved three seeded 0054 rows and exact UTC-month backfill without fabricating replay bodies; empty canonical upgrade, safe no-evidence downgrade and evidence downgrade refusal also passed. Seven fail-closed probes covered disabled RLS/trigger, inherited or SET-only app assumption, app outbound SET ROLE, unsafe app attributes and runtime-owned evidence. `alembic check` was clean. |
| Determinism and regression | PASS | Canonical `0001` reproduced twice at SHA-256 `ffc0abb58b3f4550bcc5d1524ffd9cd954076d0bf73112cab19fc7b3252e7c2f`. Ruff, strict mypy over `374` files, static verification and backend `1,417 passed / 93 skipped`; frontend TypeScript, ESLint, `46 files / 244 tests` and production build passed. |
| Retention posture | PASS WITH OPEN EXECUTION GATE | Ledger `AUDIT_EVIDENCE` and replay-body `OBJECT_DATA/CHAT_CONTENT` policy/hash/deadline bindings are independently stored. Result size is rejected at 1 MiB before JSON parsing, successful responses are `private, no-store`, and disclosure is policy/deadline bound. No source or report claims physical purge, WORM promotion or production retention conformance. |
| Independent review | PASS (local source/isolated DB) | Final SQL/security, persistence/test and governance/traceability re-audits each reported `P0=0`, `P1=0` after the trust-root and seeded legacy-backfill findings were corrected and rerun. |
| External acceptance | OPEN | WSL `linux/amd64`, real Keycloak service Subject/issuer/client revocation and rotation, representative target lock/load/soak, and accountable physical purge evidence remain `EXTERNAL_GATE`. |

## Phase 6A WSL bootstrap/network addendum — 2026-07-24

This addendum accepts the local source-controlled correction for `R5-DEP-01`. It does not accept
the preparation PC, native PowerShell, target Docker Desktop, external providers or an amd64
runtime.

| Gate | Result | Current executed evidence |
|---|---|---|
| Fail-fast bootstrap | PASS (local source/process) | A blank WSL-profile invocation without a token exits `2` before creating an environment, secret or runtime path. An existing token is byte-preserved and a token supplied through an approved file path is never printed; positional token values are rejected before mutation. |
| Connector-network owner | PASS (local contract) | Bash and PowerShell wrappers validate one named external network and use inspect → conditional create → Compose for `up`, `run`, `create` and `start`. Core and optional connector models both declare it external. Deterministic fake-Docker tests prove order, repeat reuse and invalid-name rejection without changing the local daemon. |
| Quality regression | PASS | Focused `15` tests; Ruff format over `377` files, Ruff lint, strict mypy over `370` source files, static verification and backend `1,380 passed / 84 skipped`; frontend TypeScript, zero-warning ESLint, `45 files / 243 tests` and production build. |
| Architecture configuration | PASS (render only) | Native and `DOCKER_DEFAULT_PLATFORM=linux/amd64` base, local-connector and full-overlay Compose models pass `config --quiet`. This proves configuration resolution, not amd64 runtime behavior. |
| Independent review | PASS (local source) | Security and operations/portability re-reviews report `P0=0`, `P1=0` after positional-secret, symlink/reparse, same-file, atomic staging, empty/option-like network, raw-command and profile/port documentation findings were corrected. PM traceability confirms normalized IDs and no raw legacy prompt/attachment content in the change set. |
| External acceptance | OPEN | `pwsh` is absent locally. Native Windows parsing/ACL behavior, clean target WSL bootstrap, target Docker network/container attachment, amd64 image/import/migration and external Redis/S3/DataHub/Airflow/Neo4j/LLM evidence remain `EXTERNAL_GATE`. |

## Phase 5 durable Knowledge source-job addendum — 2026-07-24

This addendum accepts the local pinned/fenced PDF-to-typed-DRAFT implementation at revision `0054`.
It does not accept WSL/private providers, production IAM/TLS, human browser acceptance or target
load/recovery.

| Gate | Result | Current executed evidence |
|---|---|---|
| Durable job and security boundary | PASS (local) | Submission pins source/base/graph/ontology/parser/model facts. The separate worker reauthorizes before source/provider egress and final locked persistence; drift becomes `STALE` without proposal rows. API cannot claim/finalize and worker cannot review/publish/activate/project. |
| Database | PASS (isolated PostgreSQL) | Additive `0053 -> 0054` and completely empty generated `0001 -> 0054` databases each passed `24` owner/app/worker/cross-service role tests. Dirty direct DELETE was removed; unsafe worker role membership failed canonical migration; app/worker/upload/governance/relay evidence-forgery cases failed closed. Generated `0001` was byte-identical twice at SHA-256 `a9978344ab90982c6d5f6c8929b8a976f34418d5fbcae2a8de6758171bda6f98`; `alembic check` was clean. |
| Resource and browser bounds | PASS (local) | 50 MiB, 500-page, per-page/provider-batch/vector/operation limits fail closed. Browser keeps one active-first opaque-cursor page of at most 100 jobs; the transactional cap of 20 non-terminal jobs per owner/graph keeps active work discoverable. Hidden-tab polling pauses and the same job can resume after 120 attempts. |
| Backend/frontend | PASS | Ruff, strict mypy over 370 source/test files and static verification passed; backend `1,369 passed / 84 environment-gated skipped`. TypeScript, zero-warning ESLint, frontend `45 files / 243 tests` and production build passed. |
| Independent review | PASS (local code) | Final Application/UI/portability and DB/security reviews reported `P0=0`, `P1=0`. PM traceability P1 findings were closed by matching claims to executed evidence and synchronizing phase-control records. Residual P2 hardening and owners are recorded in the Phase checklist. |
| External acceptance | OPEN | WSL `linux/amd64` image/runtime/migration, external MinIO/S3 policy, private OpenAI-compatible Chat/Embedding DNS/TLS/credentials, real IdP users and representative kill/retry/load/soak remain `EXTERNAL_GATE`. |

## Phase 4 Knowledge entry-gate addendum — 2026-07-24

This addendum covers implementation commit `bd0ee22` over base `716fb6f`. It accepts the local
publication/provider entry boundary only; it does not accept durable Knowledge jobs, general Chat
routing, MCP, WSL/private providers, production or HA.

| Gate | Result | Current executed evidence |
|---|---|---|
| Canonical publication | PASS (source/isolated PostgreSQL) | One approved changeset command atomically commits immutable release/content, canonical read-back receipt, published lineage, outbox and idempotency without activation. Fault injection and two concurrency shapes leave one exact evidence chain or zero effects. |
| Review and legacy boundary | PASS | Maker/checker/reason/time are rechecked under lock and on idempotent replay. Graph/changeset and Sharing replay is bound to the exact actor/owner/resource. The direct snapshot route returns `410`; a release without exactly one valid independently reviewed published lineage is invisible to list/snapshot/export/projection/GraphRAG, general Chat evidence, grants and release-pinned Sharing, and cannot activate. |
| Classification and source integrity | PASS | Graph ceiling is enforced at operation append, full submit/review, publication, PDF source preparation/analysis, model persistence and release consumption. Integrity/authorization precede generic policy errors; invalid legacy proposals may be rejected with redacted content but not approved. |
| Provider capabilities | PASS (local connection) + EXTERNAL GATE | Current Mac authenticated Neo4j `RETURN 1`, strict-JSON Chat, 1,024-dimensional Embedding inference and ordered finite-score reranking passed. Ollama itself does not implement `/v1/rerank`; the local evidence uses the Ollama-owned GGUF through the loopback-only `LOCAL_LLAMA_CPP` bridge. |
| Reranking System TEST | PASS (local/source contract only) | Fixed `POST /v1/rerank` TEST supports the bounded Mac `LOCAL_LLAMA_CPP` route and private `INTRANET_RERANK_V1` route. The former validates finite raw logits; the latter retains mounted-key, TLS/private-host and `[0,1]` score constraints. Both reject invalid ordered score shapes and record `RERANKING_INFERENCE`. ADR-0049 subsequently adds an optional governed Chat consumer that may only reorder an already-authorized bounded evidence bundle. |
| Database | PASS (local) | Alembic single head is `0053`; canonical `0001` regenerated twice at SHA-256 `2f38f83bfbcaf57ad6bfffb1ab182617a0dfd1ecb0766e5723924ba361fbcaa6`. Isolated PostgreSQL publication integration passed `9/9`; `0053 -> 0052 -> 0053` returned to head. The governed optional seed apply/verify/remove passed with an authorized publisher, exact 536-operation ledger and canonical-row hash; operation deletion and same-count content drift each failed closed and recovered through remove/reapply/verify/remove. |
| Backend | PASS | README-equivalent Ruff arguments passed over 375 files, strict mypy over 358 files, static verification and `1,328` pytest passes; `60` target-environment tests were explicitly skipped. The restricted sandbox prevented `uv` from opening its user cache, so the same locked `.venv` executables ran the gates. |
| Frontend and deployment shape | PASS (source/config) | TypeScript, zero-warning ESLint, `45` files / `238` tests and production build passed. Mac full, source-host infra, `linux/amd64` core/identity and graph/object-storage connector models rendered with `config --quiet`. |
| Independent audit / external acceptance | LOCAL P0/P1 CLEAR; EXTERNAL OPEN | Final independent review found `P0=0`, `P1=0`; the durable source-job phase retains one base-release/ontology pinning and pre-eligibility `P2`. The HTTP client still needs vetted-address connection pinning with original-host TLS verification to close DNS rebinding. WSL amd64 import/migration, Windows PowerShell execution, private Neo4j/Chat/Embedding/Reranking evidence, real Admin/reviewer identities and representative load/recovery remain `EXTERNAL_GATE`. |

## Typed BULK catalog metadata addendum — 2026-07-24

This addendum covers local implementation commit `39d20d0` and does not convert Mac/isolated-source
evidence into WSL, external-provider or production acceptance.

| Gate | Result | Current executed evidence |
|---|---|---|
| Typed contract | PASS | Exact CSV/XLSX `CATALOG_METADATA_ROWS_*_V1` profiles compile table/column descriptions and controlled DOMAIN/TERM/TAG local UUIDs into immutable V3 row/group evidence. Browser/API contracts expose neither target URNs, arbitrary Aspects, provider documents nor fan-out mutation. |
| Low-resource boundary | PASS (local) | All candidates remain in a 64 MiB attempt-local spool and database publication uses bounded replay batches. The 10,000-row parser test stayed below 64 MiB traced allocations; isolated process RSS was 77,971,456 bytes. A parser-valid 16,159,007-byte/1,600-row file whose evidence exceeded the retired 32 MiB formula completed the full worker path. |
| Authorization and apply | PASS (source/isolated PostgreSQL) | Preparation uses coarse rejection, current target/vocabulary locks and final stable-order transaction-locking reauthorization. Concurrent membership/rule revocation blocks until commit, deterministic denial releases later locks and persists zero receipt/row/candidate evidence. Valid V2 compatibility, V2/V3 drift, same-key claim renewal, classification/generation/Restricted grants and read-back authorization are covered. |
| Database | PASS (isolated local) | Native-arm64 PostgreSQL 17 passed five reauthorization/race cases before and after `0052 -> 0051 -> 0052`; `alembic check` was clean. Canonical `0001` generation repeated byte-identically at SHA-256 `5ba6583738b074d7ee2ed008a63d9a6e91aec75b59e8fe6e7f9ad12efc5c5694`. |
| Backend | PASS | Ruff format/lint, strict mypy over 351 source/test files, static verification and `1,297` pytest passes; `51` target-environment cases were explicitly skipped and not presented as passes. |
| Frontend | PASS | `45` files / `238` Vitest tests, TypeScript, zero-warning ESLint and production build passed. Controlled-vocabulary pages are no-store, capped, stale-response-safe and provide local UUID copy feedback with narrow-sidebar wrapping. |
| Independent review | PASS WITH EXTERNAL GATES | Security/data and App/API/UI reviewers found no remaining P0/P1. Candidate-table reference-viewport typography is a P2 browser gate. |
| External acceptance | OPEN | WSL `linux/amd64`, external MinIO/S3, Airflow OIDC, DataHub 1.6 Aspect ownership/write/ambiguity/read-back, real Admin/Data-Steward/approver revocation, representative 10,000-row full-worker crash/retry/load/soak and authenticated browser viewports remain `EXTERNAL_GATE`. |

## Governed Registration execution addendum — 2026-07-23

This addendum covers Registration execution/evidence commit `b83a1fb` over base `a683a93`.
The commit is local because the substantial remote push requires explicit destination approval. It
does not convert source evidence into WSL, external-provider or production evidence.

| Gate | Result | Current executed evidence |
|---|---|---|
| Backend source | PASS | exact README Ruff gate including the receipt reconciler, strict mypy over 333 source/test files, static verification and 1,152 pytest passes; 46 explicitly environment-gated tests skipped |
| Frontend | PASS | TypeScript, zero-warning ESLint, 44 files / 230 Vitest tests and the production Vite build |
| PostgreSQL `0046`–`0050` | PASS (isolated local) | deterministic canonical `0001` SHA-256 `1ca5b11f1c78ae6a193b2beca9f5ef19d252a2c59b32f955be0d10cf298ebbce` matched across consecutive generation; PostgreSQL 17 blank `0001 -> 0050`, clean `0047 -> 0050` re-entry and exact-contract checks passed. A deliberately corrupted COMPLETED apply job bound to an APPLY_QUEUED request caused `0048` re-entry to fail closed as required |
| Registration RLS/recovery | PASS (isolated local) | 16 actual PostgreSQL tests cover `datariver_app` no-context/cross-workspace, Admin, owner-only Data Steward, service worker, inactive and expired membership reads, immutable mutation/direct-terminal-attempt negatives, expired-final Manual/BULK/CR scan-onward recovery, provider target serialization, worker-call receipt recovery and attachment principal separation |
| Manual/BULK safety | PASS (source/local) | immutable conditional receipt plus live isolated MinIO concurrent-create/read-back, projection/provider lost-update checks, DB-time leases, five-Aspect success/failure evidence, atomic 24-hour Airflow run-call receipts with proactive stale-call closure, disk-spooled XLSX parsing, read-only DB/S3 orphan classification and bounded/hidden-tab polling are tested |
| Governed apply and attachments | PASS (source/isolated PostgreSQL) | a completed DataHub apply job is not reclaimable and APPLIED/APPLY_FAILED cannot be rewound. Attachment upload returns `202 STARTED`; the existing BYPASSRLS upload principal has zero direct intent-table privileges and can acquire only one server-function claim using `FOR UPDATE SKIP LOCKED`, then HEAD plus full-byte SHA evidence is required for STORED. Actual PostgreSQL denied direct SELECT even with BYPASSRLS enabled. The app and upload roles cannot directly UPDATE an intent or INSERT an attachment; finalization rechecks current membership, action/deny rules, System/Domain/classification, TEST assignment, target binding, CR version/round/state and monotonic time and supports exact idempotent response-loss replay. Browser recovery treats network/408/5xx as ambiguous, reuses the exact upload ID, pauses while hidden, and lists only current-round STORED rows after server filtering and before a ten-row limit; partial recovery remains visible |
| JavaScript dependency audit | EXTERNAL_GATE | Type/lint/test/build passed without network. The current `npm audit` was not executed because it transmits the dependency manifest to the external npm service and no explicit disclosure approval was available; no zero-vulnerability claim is made for this source boundary |
| External acceptance | OPEN | exact WSL image/startup, external MinIO permission/immutability, Airflow OIDC DAG, DataHub 1.6 five-Aspect read-back, real Keycloak multi-human journey and representative load/crash/soak remain `EXTERNAL_GATE` |

## Mac development policy addendum — 2026-07-20

This addendum supersedes the older source counts and migration head below without converting the
historical Windows/WSL evidence into a Mac claim.

| Gate | Result | Current executed evidence |
|---|---|---|
| Account renewal | PASS | six-calendar-month human expiry, final-30-day server eligibility, one pending self-request, independent global-Admin decision and expired-membership denial; the live migration backfilled two human memberships with an expiry and preserved two service accounts without one |
| CR System authority | PASS | REVIEW and TEST require Developer evidence for every routed System; FINAL requires Developer and Data Steward for every routed System plus one role-separated global Admin; immutable authority snapshots and negative transition cases are covered |
| System Settings (historical evidence) | SUPERSEDED | This row records the former SAVE/TEST/ACTIVATE implementation. ADR-0048 now makes the selected deployment environment and mounted secrets the only live source; Admin is read-only and runs fixed deployment probes after managed restart. |
| Python gates | PASS | Ruff format/lint, strict mypy over `233` source/test files, `639` pytest tests and static architecture verification |
| Frontend gates | PASS WITH WARNING | TypeScript, zero-warning ESLint, `36` files / `148` Vitest tests and production build passed; JS `838.50 kB` / gzip `241.83 kB`, CSS `151.97 kB` / gzip `26.47 kB`; the existing chunk warning remains open |
| Migration | PASS | canonical `0001` SHA-256 `e4e8630af3604e4c3dfb676b1dddc0f91ddd4a9035cc50406a02201f90881159` was identical across consecutive generation; `71` focused compatibility/domain tests passed; the live Mac DB upgraded `0031 -> 0034`, an empty temporary DB migrated `0001 -> 0034` and was removed, and schema/grant read-back passed |
| Local runtime | PASS | rebuilt API, Web and affected workers started; direct API, Web and APISIX readiness returned 200; Ollama `0.32.1`, DataHub and Neo4j endpoints responded; APISIX now uses Docker DNS discovery and returned 200 after an API-only replacement |
| Browser | PARTIAL | a fresh in-app browser showed a stable Sign In screen for five seconds with no console errors; it had no authenticated user session, so current Admin-menu and mutation acceptance remains an explicit user-session gate |

This is development evidence only. No production hot-reload, automatic process restart, worker
success inference, notification delivery or unsupported Neo4j/Embedding/Reranker activation is
claimed.

## Source and build evidence

| Gate | Result | Executed evidence |
|---|---|---|
| Python format/lint | PASS | Ruff format and check across backend source, tests, DAGs and static-verification scripts; generated Alembic output is verified by deterministic regeneration rather than hand formatting |
| Python type safety | PASS | strict mypy: 133 backend source files and 199 source/test files, zero issues |
| Backend behavior | PASS | 495 pytest tests: prior identity, governance, retention, RLS, search/DataHub, KG, sharing and evidence gates plus snapshot-bound managed export, immutable server-owned governance target bindings, current-target read/review/transition reauthorization, typed description preview/locking/document preservation, raw-entrypoint separation, governed aspect/one-item worker guards, mandatory optimistic source hashes, lost-completion reconciliation, version-fenced upload promotion/read-back, typed BULK persistence/API boundaries, V2 submitted-identity/candidate/root hash vectors, bounded authorization-pruned candidate reads, canonical migration-state guards, active-policy-bound Chat retention persistence and budgeted/grounded disabled-first inference routing |
| Frontend | PASS (type/lint/build and changed files); full rerun gate open | TypeScript build mode and full ESLint pass; the two registration test files pass 17/17 tests and the governed change-workbench file passes 9/9 tests. The change tests cover bounded list/filter, fresh keyboard-opened detail, explicit idempotent/version-fenced commands, 403 no-replay, 409 refresh/reconfirm and client-context cancellation. The last complete suite baseline is 18 files/75 tests, but both ordinary and single-worker current whole-suite runs reached five-minute Windows/WSL network-drive timeouts without assertion output, so an exact current whole-suite pass is not claimed |
| Frontend artifact | PASS WITH WARNING | current source build: JS 503.11 kB / gzip 143.36 kB; CSS 46.70 kB / gzip 9.12 kB. Vite reports the single JavaScript chunk above 500 kB, so route-level code splitting remains an optimization gate |
| Dependency audit | PASS | `pip-audit 2.10.0`: no known runtime vulnerabilities; `npm audit`: 0 vulnerabilities |
| Repository/IaC scan | PASS | Trivy 0.70.0 `vuln,secret,misconfig`, HIGH/CRITICAL, ignored-unfixed: zero findings after making the Keycloak non-root user explicit |
| Migration | PASS | current generated `0001` SHA-256 `5ced9db291a0d73c080c45f9dd85c235293c0084e48fe972e16cb4cafe87df61`; Alembic sole head and packaged/runtime readiness revision are `0018`. The populated local database upgraded `0017 -> 0018`. A completely empty temporary database migrated directly to head, and a separately committed canonical `0001` database advanced through every compatibility revision to the same head. Revisions `0013`-`0018` now distinguish absent, complete and partial canonical contracts; partial state fails closed and compatibility downgrade does not delete `0001`-owned objects. Deterministic regeneration, unit guards and both live paths passed |
| Assistant inference contract | PASS (source/unit only) | typed authorized package/result has no SQL, Cypher, arbitrary HTTP, tool or mutation fields; exact provider identity/region and separate external-denial/internal-monitor decisions are bound; selected fallback predicates are revalidated; model completion requires a policy-bound package/route/answer and ordered URN/version/content-hash verdict; post-call usage survives later refusal; malformed adapter/verifier returns fail closed; benchmark observations bind dataset/evaluator/scoring hashes; no adapter, endpoint, secret, ledger, durable job or provider call is wired |
| PgBouncer RLS gate | PASS (source/unit only) | the probe validates passwordless URLs, file secrets, transaction mode, single-server reuse and fail-closed workspace fixtures; PgBouncer is not deployed and no live pooler result is claimed |
| Static invariants | PASS | Compose dependencies/secrets, DataHub release and identity-assurance contracts, runtime hardening, architecture imports, least-privilege DB roles, tenant foreign keys, seed determinism and documentation links |
| Scripts/config | PASS | POSIX/Bash/PowerShell parsing and base, identity, Airflow, gateway and combined Compose interpolation |
| Reference preservation | PASS | 424 files / 4,763,143 bytes; zero missing, byte or SHA-256 mismatches; secret/cache exclusions verified |
| Independent review | PASS WITH PRODUCTION GATES | Data Architect and Data Engineer/SRE reviews are retained under `docs/reviews/` with post-review status notes |

The optional seed produced the stable logical hash `df039426579bc369f8fda8f6154005c500860ab2ab5a9e263928ef1508b0ebc9`: 12 catalog assets, 257 nodes and 279 edges. Apply, independent verify, remove and re-apply all succeeded.

## Current hybrid-development runtime evidence

The normalized v1 topology keeps PostgreSQL, cache/queue Valkey, SeaweedFS, Keycloak and APISIX in
containers. Uvicorn, the outbox relay, three workers and Vite run directly from the Windows source
tree. The separately operated DataHub core is reused and remains outside DataRiver lifecycle
ownership.

| Gate | Result | Evidence |
|---|---|---|
| Runtime routes | PASS | direct API live/ready, APISIX live and Vite-to-APISIX API proxy returned 200 |
| External DataHub | PASS (local integration) | GMS health and scoped-token GraphQL authentication succeeded; DataRiver did not start or migrate DataHub |
| Migration `0003` | PASS | populated `0002` database upgraded; watermark table has forced RLS, app `SELECT/INSERT/UPDATE` only and obsolete timestamp index is absent |
| Migration/readiness `0004` | PASS | app role received only version-table read access; direct API readiness requires the packaged sole head while liveness remains independent |
| Immutable evidence `0005` | PASS | populated database upgraded in place; citation columns/checks/unique rank and chunk constraints are present, forced RLS remains enabled and the app role has only `SELECT/INSERT`; direct `UPDATE/DELETE` were denied |
| Retention safety `0006` | PASS | populated database upgraded in place; relay pruning API/call path is absent, `datariver_relay` has zero table `DELETE` privileges, and automatic retention reports `DISABLED_NOT_READY` until governed WORM/Legal-Hold/Maker-Checker gates exist |
| Governed administrator access `0007` | PASS (backend/local DB) | typed direct and Maker-Checker APIs, exact assurance matrix, five-minute/hash/version/one-time invariants and minimal outbox events passed; clean and upgraded DB fingerprints matched for columns, constraints, indexes, RLS policies and grants; app-role protected-column/approval update and workflow DELETE were denied. The local workspace has only one eligible human security administrator, so fallback correctly remains disabled until a real second administrator and two-user browser journey exist |
| Retention governance `0008` | PASS (backend/local DB) | versioned policy proposal/independent decision and immediate Legal Hold placement/release Maker-Checker APIs passed with optimistic concurrency, idempotency and integrity hashes. Forced RLS, least-privilege column grants and append-only hold events were verified from both clean and upgraded databases. All automated deletion and erasure execution remain explicitly `DISABLED_NOT_READY`; no destructive endpoint exists |
| Erasure review `0009` | PASS (backend/local DB) | typed request/independent decision APIs bind the canonical target snapshot and active policy ID/hash, recheck applicable Legal Holds and expose no execution capability. Clean and upgraded schema fingerprints matched; cross-workspace/empty-context access, immutable-column and event mutation, stale version, duplicate payload, altered policy hash and expired approval were denied. Expired rejection remained available to close stale reviews. The populated local database upgraded in place and API/Gateway readiness returned 200 after the host source processes restarted |
| Immutable archive evidence `0010` | PASS (backend/local DB) | clean and historical migrations produced the same archive schema; capability and receipt rows are forced-RLS append-only evidence with app-role read-only grants. Exact policy/configuration/encryption/runtime-principal composite bindings, provider/full-readback checksum equality, retention read-back, literal-null version, raw Chat source and no-cascade negatives passed. No archive/export/deletion worker or target WORM claim was enabled |
| Governed classification access `0011` | PASS (backend/local DB) | four immutable policy rules, authorization/provider generations, active-policy-bound RESTRICTED grants with append-only events, and immutable inference profile versions passed forced-RLS, least-privilege, maker-checker, revocation and generation checks. Admin API/FE contracts are implemented; no external inference execution was enabled |
| Governed catalog discovery/export `0012`-`0014` | PASS (disabled-first source/local DB) | search metadata, permission-prefiltered facets/suggestions, policy/projection-aware short-TTL caches, lazy authorization-pruned hierarchy and bounded lineage are supplemented by an owner-scoped, request/security/source-snapshot-bound CSV export job. RESTRICTED export is unconditionally denied; CSV formula/NUL/record-size limits, lease fencing, multipart abort and download-time reauthorization are covered. The populated DB migration, private bucket initialization, API/APISIX readiness and a 403 negative capability probe for the Airflow service identity passed. The isolated export DB/S3 principal and worker remain disabled pending explicit provisioning approval; no live artifact-generation claim is made. Target-distribution EXPLAIN/BUFFERS, full URL state, authenticated browser visual E2E and the 60-minute soak are also not yet evidence |
| Governance target binding `0015` | PASS (source/unit/local runtime contract) | creation resolves one active DATASET through the authorization-pruned local projection and persists an immutable server-owned identity, scope, classification, lifecycle, source-version and observation binding. Reads hide newly denied targets, while review/approval/retry reject identity, scope, classification or lifecycle drift under a shared request transaction and projection share lock. Legacy unbound requests are not executable; source-version-only drift remains separately governed by optimistic hashes. Apply-time worker requester/policy reauthorization, provider-wide target serialization and external provider CAS remain open pending least-privilege worker authorization and live concurrency evidence |
| Typed BULK preparation foundation `0016` | PASS (schema/API/source/local DB; execution disabled) | existing manifests default to immutable, non-executable `FORMAT_ONLY_V1`; durable job, exact source receipt, typed candidate and exact candidate-to-change provenance tables have forced RLS, composite workspace references and `RESTRICT` deletion. API grants are read/create-only, while the existing BYPASSRLS upload role receives no new table access. Upload initiation validates the explicit profile, and create/read/list preparation APIs lock and verify the exact accepted manifest, mandatory promoted-byte SHA-256 evidence, server configuration hash, request owner and idempotency before persisting/reusing one job. Responses expose no storage coordinates, lease or parser payload. A pure bounded parser rejects malformed UTF-8/CSV/header/identity/duplicate/size inputs, preserves exact descriptions and emits golden-tested candidate plus ordered result-chain hashes; its consumer contract permits attempt-local staging only. A live app-role/RLS repository insert-get-list round-trip passed and rollback absence was verified; restarted Direct API/APISIX/Vite returned 200 and live OpenAPI exposed both preparation paths with no storage/lease/requester fields. Immutable tables have zero UPDATE/DELETE/TRUNCATE grants; the post-baseline compatibility downgrade is deliberately non-destructive because canonical `0001` owns the schema. No parser worker, candidate selection/preview or proposal creation route is enabled; a separate NOBYPASSRLS workspace/correlation-bound execution role remains an activation gate |
| Candidate submitted identity evidence `0017` | PASS (schema/source/local DB; execution disabled) | existing candidates are explicitly preserved as `LEGACY_V1` without fabricated hierarchy. New candidates default to V2 and require submitted platform/database/schema/table plus identity hash; parser/configuration, candidate and ordered-root contracts advance to golden-tested V2. The local database upgraded in place and exposed the expected default, columns and insert/update/delete rejection trigger; no grant changed and no candidate existed. The source now provides a bounded private/no-store read-only candidate page which validates READY receipt/V2 hashes, separates submitted evidence from the current target and fails the whole page for legacy/missing/denied/drifted targets after one set-based local authorization pass. After the source restart, direct API, APISIX and Vite-proxied readiness returned 200; live OpenAPI exposed the GET candidate path and an unauthenticated request with a syntactically valid workspace context failed 401. No publish worker, candidate preview or proposal command is enabled |
| Chat retention policy binding `0018` | PASS (source/unit/local DB; deletion disabled) | the fixed 90-day source fallback is removed. Final Chat persistence now uses a separate RLS-scoped unit of work, serializes against retention administration and binds policy ID/hash, database transaction time and policy-derived deadline. Existing sessions are honestly `LEGACY_UNBOUND_V1`; legacy, expired and superseded-policy sessions are append-closed. The local database reports both enforcement triggers, app-role update only on `version/updated_at`, and no retention-column update or Chat delete privilege. In a rolled-back clean-DB probe a 37-day active policy produced exactly 37 days, while legacy insert, deadline mutation and post-supersession append were denied and only one message existed. After the host source restart, direct API, APISIX and Vite-proxied readiness all returned 200 and APISIX recovered healthy. The actual local workspace has no ACTIVE retention version, so Chat content persistence intentionally returns conflict until two distinct administrators activate a policy. WORM export, expiry deletion and partition drop remain `DISABLED_NOT_READY` |
| Registration/create-time target hardening | PARTIAL (source/unit/local runtime contract) | MANUAL dataset-description editing is typed and asset-ID anchored: authorization precedes the live provider read, preview returns no raw document, an opaque quoted ETag binds workspace/asset/target/source/hash, creation re-reads and share-locks the target, preserves non-description fields and derives classification server-side. Empty clear, live no-op, invalid provider JSON, provider/source drift and asset replacement fail closed. Generic and upload-derived raw proposals additionally require deny-by-default hardware-human `change.raw.create`; both raw browser forms are removed. BULK preserves multipart quarantine/validation, isolates each promotion by validation claim, fully re-reads the accepted bytes and cleans the source only after the version-fenced DB commit receipt. Stale claims cannot overwrite the current accepted key or delete quarantine; ambiguous commits preserve both objects for reconciliation. The v0.3-style BULK workbench explicitly binds format-only versus typed profile, creates a bodyless preparation with exact manifest ETag/idempotency only after a no-store list read, and renders server state/progress without candidate or raw execution actions. Its pure parser contract is unit verified, but no worker/candidate/proposal execution exists. The governance worker rejects unsafe/unbound queued shapes and reconciles an already-observed approved `after_hash`. Target-store Object VersionId/conditional-copy evidence, malware and structural-bomb scanning, orphan reconciliation, apply-time requester/policy reauthorization, target-key serialization/provider CAS, parser execution worker, candidate preview/binding, additional typed table/column/domain/term/tag DTOs, cross-process idempotency concurrency evidence, revision/test-evidence workflow and target worker/egress separation remain open |
| Concurrent watermark | PASS | two app-role sessions advancing one workspace returned generations `[1, 2]`; rollback preserved `2`; a cross-workspace advance was denied by RLS |
| Seed generation | PASS | migration backfill `1`, remove `2`, re-apply `3`; verify was a no-op; final counts remained 12 assets/257 nodes/279 edges |
| Authorized search | PASS | same-token semiconductor `wafer` search returned the two expected authorized assets after API source reload |
| Same-token policy revocation | PASS (local direct API) | 100 iterations/scenario: inactive membership p99 100.660 ms, explicit search deny p99 167.743 ms, system/domain scope removal p99 193.388 ms; original Airflow membership restored and verified. APISIX correctly rate-limited the first high-rate attempt, so cache-policy timing was rerun directly on `:8000` |
| Local interactive OIDC assurance | PASS (flow/probe) | existing Keycloak realm migrated and re-read with no drift; an ephemeral browser-flow probe received a LoA 1 token carrying `acr=1`, `amr=pwd` and `auth_time`, and a WebAuthn-required page for LoA 2, then removed the probe user; zero probe users remained. A real USB key ceremony and hardware-token/backend journey remain a target-environment gate |

## Live Compose evidence (pre-P0-hardening runtime baseline)

The combined core + Keycloak + Airflow + APISIX stack was built and started as Compose project `datariver-next`. Local verification used alternate host ports `18080`, `18081` and `19080` because the preserved legacy stack already occupied the defaults. Clean clones retain documented defaults `8080`, `8081` and `9080`.

| Gate | Result | Evidence |
|---|---|---|
| Stack state | PASS | 16 long-running services up; every defined health check healthy; migration, object-storage init and Airflow init exited 0 |
| Runtime hardening | PASS | API, web, Keycloak and APISIX ran non-root with read-only root filesystems and `no-new-privileges`; generated/temp state used bounded tmpfs or named volumes |
| Core HTTP | PASS | direct API readiness 200, web health 200, web-to-API proxy 200, APISIX-to-API health 200 |
| Web headers | PASS | CSP present, `X-Frame-Options: DENY`, content-type/referrer/permissions headers present |
| OIDC | PASS | Keycloak discovery issuer matched `http://localhost:8081/realms/datariver`; client-credentials token had expected issuer, audience and service subject |
| Gateway enforcement | PASS | protected catalog without token 401; valid service token 200 with 12 permitted assets and an APISIX request ID |
| PostgreSQL migration | PASS | deterministic initial migration applied to PostgreSQL 17.10 without error |
| RLS isolation | PASS | application role observed 0 rows with no workspace context, 12 in the seed workspace and 0 in another workspace |
| Least privilege | PASS | application-role direct catalog `DELETE` was denied |
| Airflow | PASS | metadata DB, scheduler, triggerer and DAG processor healthy; `datariver_catalog_probe` and `datariver_catalog_sync` registered paused; import errors `[]` |
| Seed runtime | PASS | apply/verify/remove/re-apply completed against the live database with expected hash/counts and scoped service membership |
| Runtime logs | PASS | 12 application/edge/worker services scanned over the final 15-minute window; zero traceback, fatal, panic or error-severity patterns |

## Recovery and degradation evidence

| Scenario | Result | Observed behavior |
|---|---|---|
| Cache Valkey stopped | PASS | API readiness remained 200 and authorized catalog search still returned 12 correct rows |
| Cache Valkey restarted | PASS | container returned to healthy without application restart |
| API process restart | PASS | APISIX returned to readiness automatically after the transient outage |
| API container replacement | PASS | web and APISIX both returned 200 while the web container ID stayed unchanged; Nginx now re-resolves Docker DNS and retained no stale upstream IP |
| Outbox relay restart | PASS | relay returned to running state; no fatal loop appeared in final logs |
| APISIX read-only startup | PASS | generated Nginx configuration and temp paths use non-executable tmpfs; real proxied HTTP health check passed |
| Airflow cold start | PASS | API became healthy under the 90-second startup grace configured for modest developer hosts |

## Repeatable source gate

```bash
uv sync --frozen --all-extras
uv run ruff format --check backend/src backend/tests infra/airflow/dags \
  scripts/generate_initial_migration.py scripts/probe_policy_revocation.py scripts/verify_static.py
uv run ruff check backend/src backend/tests infra/airflow/dags \
  scripts/generate_initial_migration.py scripts/verify_static.py
uv run mypy backend/src backend/tests
uv run pytest backend/tests -q
uv run python scripts/verify_static.py
uv run python scripts/generate_initial_migration.py

cd frontend
npm ci
npm run typecheck
npm run lint
npm run test -- --run
npm run build
npm audit --audit-level=high
```

On the reviewed Windows/UNC workspace, Vitest was executed on a temporary `pushd` drive with `--pool=threads --maxWorkers=1 --no-file-parallelism`; this changes only local execution parallelism. Linux CI uses the canonical npm commands above.

## Remaining production acceptance gates

These items are not source defects, but they prevent a production-readiness claim:

1. Execute DataHub search/detail/sync/change apply/re-read contract tests against the target deployed DataHub version and production-like credential. Local health and GraphQL authentication passed against the separately operated development DataHub, but this is not the target contract gate.
2. Complete real multipart/CORS/copy/checksum/lifecycle tests against the target object-storage deployment and a PostgreSQL + object consistency backup/restore drill with measured RPO/RTO.
3. Run the full ABAC matrix with two real OIDC user identities, browser PKCE/password reset/hardware-WebAuthn step-up journeys, policy revocation timing, password-fallback maker-checker consumption, Legal Hold release, erasure review and audited enterprise subject/workspace administration.
4. Replace Airflow `SimpleAuthManager`, which is deliberately local-development only, with the environment's supported enterprise/FAB SSO configuration before any non-local exposure.
5. Run browser E2E, 60-minute target load/soak, queue saturation, worker kill/reclaim, DataHub fault injection and projection rebuild/chaos tests on the reference deployment shape. External inference additionally requires pre/post-call live policy/profile/attestation revalidation, durable queue/idempotency, SSE timing/cancellation, provider metrics and scaled red-team evidence.
6. Execute backend/frontend and all promoted overlay image scans in an isolated CI/release runner, retain CycloneDX SBOM and license reports, and promote digest-pinned images. Local repository/IaC scanning passed; a Docker socket was intentionally not mounted into a third-party scanner container.
7. Produce a clean-clone CI run tied to a commit SHA, immutable image digests, target-environment evidence and accountable reviewer sign-off with exception expiry.

## Conclusion

No known formatter, linter, type, unit, frontend-build, migration-graph or static-architecture error remains in the current source. The hybrid runtime, compatibility migrations through `0015`, local RLS/gateway/seed and post-hardening API smoke checks passed. The project is suitable for Git sharing and continued environment integration. Production release remains blocked by the target-system, scale/load, recovery, browser, HA, external-inference and signed supply-chain gates listed above.
