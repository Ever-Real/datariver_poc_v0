# Master execution backlog and requirement traceability

## Purpose and authority

## Handoff public baseline (authoritative for transfer/restart)

- 현재 작업 및 준비 PC 전달 기준은 `origin/dev`다.
- `origin` fetch/push URL은 `https://github.com/Ever-Real/datariver_v1.git`만 허용한다.
- 장기 branch는 `dev`와 `main`뿐이다. 일상 개발·검증·준비 PC 전달은 `dev`에서 수행하고,
  사용자가 요청한 검증 checkpoint만 `main`에 fast-forward 병합한다.
- 현재 commit은 `./scripts/development_cycle.py dev-publish`가 전체 source gate, Mac runtime
  적용, push와 원격 SHA 일치를 함께 검증한다. 정적인 문서 SHA를 현재 기준으로 오인하지 않는다.

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
| Branch / Phase 6E entry base / current published implementation | `dev` / `dba1186` / verified by the stable publication workflow |
| Remote comparison | `dev-publish` requires local `dev` and `origin/dev` to resolve to the same exact commit after every publication |
| Current controlled phase | Product `fca4535cab544560bd06486dc363e6df0c6df27f`: completed baselines remain verified. K4 closes Catalog Table → typed T-Box Source Proposal. K5 is `HOLD_KNOWLEDGE_ABOX_PERSISTENCE_DECISION`: the authoritative Node POC has no approved physical source-row reader, DEV source manifest/secret root or running ingestion worker, and DataHub metadata is not row evidence. K6 is not started. Registration durability and GX assertion egress remain held/blocked as named. |
| Final artifact order | Feature → API → Data/ERD → Screen → `README.md` → `ARCHITECTURE.md` |

## 2026-08-16 Node POC Account/Auth execution

The authoritative Node POC preserves one authentication-to-authorization chain:

```text
local credential / opaque server session
→ request-scoped subject_id
→ change-history-access-v1
→ central role capability
→ explicit Table grant + security grade + fixed feature policy
→ Responsible System only for workflow features
→ feature operation
```

Current Product boundary `68af3d5895a9ee553bff94e17c7a7d6cea47704a` preserves the PHASE 1D-R
baseline and is validated through `.orchestration/evidence/DEV-MCL-RUNTIME-AUTOMATIC-DETECTION.md`,
`.orchestration/evidence/DEV-PHASE1D-R-DETERMINISTIC-RESTART.md` and the preceding PHASE 1D
evidence. The current Registration/support-service acceptance is recorded in
`.orchestration/evidence/DEV-REGISTRATION-SUPPORT-SERVICES-RUNTIME.md`.
The bounded READY candidate-to-governed-CR runtime is recorded in
`.orchestration/evidence/DEV-REGISTRATION-BULK-CANDIDATE-CR-RUNTIME.md`.
The server-authoritative apply-report contract and durable-storage HOLD are recorded in
`.orchestration/evidence/DEV-REGISTRATION-APPLY-REPORT-AUTHORITY.md`.
The approved Governance document management runtime, Registration storage decision and GX contract
recovery are recorded in
`.orchestration/evidence/DEV-GOVERNANCE-DOCUMENT-MANAGEMENT-RUNTIME.md`.
The canonical menu, Registration role boundary and Knowledge K0 audit are recorded in
`.orchestration/evidence/DEV-MENU-REGISTRATION-KNOWLEDGE-K0-RUNTIME.md`.
Knowledge K1 exact identity/provenance is recorded in
`.orchestration/evidence/DEV-KNOWLEDGE-K1-IDENTITY-PROVENANCE-RUNTIME.md`.
Knowledge K2 Registry/Asset/version runtime is recorded in
`.orchestration/evidence/DEV-KNOWLEDGE-K2-REGISTRY-VERSION-RUNTIME.md`.
Knowledge K3 minimal T-Box Builder runtime is recorded in
`.orchestration/evidence/DEV-KNOWLEDGE-K3-TBOX-BUILDER-RUNTIME.md`.
Knowledge K4 Catalog Source Proposal runtime is recorded in
`.orchestration/evidence/DEV-KNOWLEDGE-K4-SOURCE-PROPOSAL-RUNTIME.md`.
The preceding PHASE 1A runtime evidence is commit
`8c1f93a456d0fe51e46987b72d66f563f6467d73`. These local commits have not been published;
`origin/dev` remains `ef41447a1d470119c1a83280e261d4be411354ef` until a future G1/G2 approval.

| ID | Canonical status | Current evidence / completion condition |
|---|---|---|
| AUTH-1A | `COMPLETE_RUNTIME_VERIFIED` | Local Argon2id credential, hashed opaque session, request principal, access-document authority, CSRF/Origin fence, operator bootstrap, API/SPA boundary and loopback/private-network defaults were verified at Product `618b9713059ba7e31b807ceae3b401766a313668`. |
| AUTH-1B | `COMPLETE_RUNTIME_VERIFIED` | Exactly 15 centrally versioned capabilities, server principal, route classification and client-spoof defenses remain the technical baseline. The former Responsible-System-as-general-data-scope behavior was replaced by explicit Table grant + grade + fixed policy on covered reads; Responsible System remains business/workflow scope only. PHASE 1C-1 added two exact Admin routes, making the registry 51 IDs (`7/2/40/1/1`, unknown `0`). |
| AUTH-1B-R | `COMPLETE_RUNTIME_VERIFIED` core | The current Node POC keeps exactly 15 capabilities and request-time access authority while separating explicit Table grants/security grades from Responsible System. Covered Catalog/Chat/vector paths prefilter correctly; remaining Neo4j, provider-traversal and unbound-resource gaps are owned by those feature surfaces, not a reason to redesign the core authorization chain. |
| AUTH-1C-1 | `COMPLETE_RUNTIME_VERIFIED` | Product `60f5f270a56130f2ed96236d9286d0903e3360db`: System name/description update and archive preserve stable identity/history. Exact DataHub `TABLE` URN N:M System pairs use bounded `poc_state` CAS; PATCH synchronously confirms the current provider inventory and rejects deleted/type-changed/unavailable identities before CAS. Backend, Admin UI, runtime and fresh Validator checks passed with zero active validation mappings, credentials or sessions. Evidence: `.orchestration/evidence/DEV-PHASE1C1-TABLE-SYSTEM-RUNTIME.md`. |
| AUTH-1C-2 | `COMPLETE_RUNTIME_VERIFIED` | Product `f78f30fbcf0a5468ec2ce9893d06825ddd030369`: one exact `(subject_id, table_urn)` domain relation avoids access-CAS bloat; the access document retains Role/System authority and adds only `max_security_grade`. Admin user/grade/grant/Responsible-System/credential/session API and UI, targeted current-Table fail-closed validation, two-user isolation, spoof/401/403/404 negatives, credential cleanup, exact image revision and full regression are DEV-runtime verified. Evidence: `.orchestration/evidence/DEV-PHASE1C2-USER-TABLE-ACCESS-RUNTIME.md`. |
| AUTH-1C-3 | `COMPLETE_RUNTIME_VERIFIED` | Product `9df97f4975a990819db655b74b09e709dc6d5aad`: fixed 8-feature × 5-role × 3-grade (120-cell) CAS management policy, exact Admin API/UI, immutable Admin allow and role-ineligible deny, stale-CAS/shape negatives, real browser verification and fresh AGY Validator passed. PHASE 1D enforcement remains explicitly inactive. Evidence: `.orchestration/evidence/DEV-PHASE1C3-SECURITY-HARDENING-RUNTIME.md`. |
| AUTH-1C-4 | `COMPLETE_RUNTIME_VERIFIED` | Product `773cd37e6d48cbba02c999380fe1965a3b9f4e26`: request-principal CR commands now require a current exact Table, explicit grant/grade/fixed Change policy for non-Admin creation, one exact responsible System, current Developer/Data Steward workflow assignment and independent Developer/Data Steward/Manager final lanes. Admin cannot silently satisfy a lane; concurrent completion uses the existing core CAS; legacy CRs remain read-compatible and mutation-protected. The same Product also redirects noncanonical browser GETs to the configured DEV origin without weakening wrong-Origin mutation denial. Evidence: `.orchestration/evidence/DEV-PHASE1C4-CR-RESPONSIBILITY-RUNTIME.md`. |
| AUTH-1D | `PARTIAL` overall; core surfaces complete | Product `91ca4db7ca792566b7765f3366036b1d8bed2869` froze deterministic provider restart; Product `afb95a45c45ae065223faa39c53278884c935f37` preserves the Registration/Table, Governance and Chat regression baseline and closes only the bounded Knowledge K1 exact-identity projection. Request-time grant + grade + fixed-cell AND, no-N+1 hydration, local count/detail hiding, PG/memory pre-ranking and Product General/Vector/AUTO/reranking/context/citation remain `COMPLETE_RUNTIME_VERIFIED`. Overall AUTH-1D remains `PARTIAL` for provider traversal/totals, deleted grade, unbound resources and Quality/GX; K1 does not make unrestricted Graph routes complete. |
| AUTH-1E | `BACKLOG` | Retire only proven legacy auth active paths after the replacement remains runtime-verified. Preserve reusable Knowledge/Quality/Chat code, schema history and `UNKNOWN` references. |
| AUTH-1F | `BACKLOG` | Complete multi-account personal history/draft/Chat-stream isolation, session reset/revoke acceptance, every feature regression and external network acceptance. Bounded legacy authorship placeholders are not authorization authority but remain part of this acceptance. |
| AUTH-NET | `TARGET_RECHECK_REQUIRED` | DEV Web and supporting owned ports are loopback/private and local inspection passes. A real second-host negative connectivity probe is still required; do not claim public-network isolation from bind inspection alone. |
| ACCOUNT-AUTH | `COMPLETE_RUNTIME_VERIFIED` core | Local account/session, central capability, exact Table grants, security grade, fixed feature policy, Responsible-System workflow scope, CR three-lane approval and covered data reads are the completed baseline. AUTH-1E/1F and external-network acceptance remain separate later gates; feature-specific integrations are accepted with each feature. |

Account/Auth validation credentials were disabled and their sessions revoked after each matrix run.
The separate DEV inspection `admin` credential remains intentionally enabled, active and excluded
from validation cleanup. Access users and historical references remain; synthetic `checkpoint-*`
users have no credential. Scheduler/MCL deployment readiness is separate and must now be refreshed
from current source/runtime; the historical disabled/`0/9` observation is not reused as current
evidence and frozen ledger/checkpoints must not be reset.

## 2026-08-18 Canonical Product menu and Knowledge K0

The Product navigation, execution view and Korean dashboard use one current order. Supporting
services remain technical detail rather than a top-level Product menu.

| Order | Product area | Current boundary |
|---:|---|---|
| 1 | Admin — 접근관리 | completed baseline; minimum feature controls only |
| 2 | 검색 | completed local/Vector authorization baseline |
| 3 | 변경관리 | Change History and CR frozen baseline |
| 4 | 모니터링 | independent authorized read baseline |
| 5 | 등록관리 | mutation data_steward/admin only; provider apply/durability `PARTIAL` |
| 6 | 거버넌스 — 정책·표준 문서 관리 | bounded read/create/DRAFT-update/archive complete |
| 7 | Chat | General/Vector/AUTO and pre-K7 DataHub-lineage Graph complete; fallback execution/K7 partial |
| 8 | 지식관리 | K0-K4 and K5 durable A-Box ingestion bridge `COMPLETE_RUNTIME_VERIFIED`; K6 not started |
| 9 | 품질관리 | `USER_FEATURE_DEFINITION_REQUIRED`; GX technical gate separate |
| — | 기술 Backlog | support services, deployment and target gates |

### User feedback inbox

| ID | Menu | Classification | Status | Request / application point |
|---|---|---|---|---|
| `CHANGE_MONITORING_LEDGER_SURFACE_RELOCATION` | 변경관리 / 모니터링 | `NEXT_SLICE_FEEDBACK` | `BACKLOG` | Move the authoritative ledger presentation into Change Management and remove overlapping summary content only after mapping current component and independent Monitoring-route consumers. Apply in a later Change Management UX slice without duplicating the server projection or client state. |

Knowledge K0 found zero current Node Assets/drafts/releases/bindings, no verified Knowledge Neo4j
projection, no current Knowledge Chat server handler and no MCP route/server/test. Historical Python
Knowledge code is a reusable design source, not current runtime proof. Product `afb95a45...` now
closes K1 only: exact provider Table/Column URNs are pinned to graph/release-scoped deterministic
Knowledge identities and written through a fixed parameterized Neo4j projection. Actual browser
E2E produced 2 nodes, 1 edge and duplicate 0 after rerun, exact `DATAHUB_SYNC` provenance and
no-grant 403. Non-Admin unrelated graph remains fail-closed. Product `68af3d58...` closes K2 only:
the Registry renders the exact eight user columns and actual browser E2E passed create, Draft
save/reload, authenticated actor display, independent publish, one Active maximum, Active→new Draft,
history, soft archive, Chat exclusion and Viewer/direct-route negatives. Product `01e02acb...`
closes K3 typed T-Box editing with actual browser save/reload, semantic warnings, lock, stale CAS,
desktop/mobile and retained discard evidence. Product `fca4535c...` closes K4 canonical grade
compatibility and Catalog Source Proposal with exact Dataset/SchemaField provenance, reload and
zero A-Box/Neo4j growth. The K5 entry audit found reusable Draft/release/CAS, binding and K1
projection seams, but no approved current Node physical-row reader or configured DEV ingestion
authority. K5 is `HOLD_KNOWLEDGE_ABOX_PERSISTENCE_DECISION`; K6 was not started. K5 through K9
remain separate later slices.

The bounded K5 decision rejects synchronous core/CAS row ingestion because it lacks the accepted
claim/lease/fence/source-pin/attempt/Changeset authority. The user approved
`APPROVE_K5_CANONICAL_INGESTION_PLANE_DEV`, but CONTROL_PLANE reclaim found that the authoritative
Node POC has neither the canonical revision `0081` database/UUID IAM plane nor a fixed-function
identity/schema adapter to it. The temporary memory-only mock was rejected. K5 is therefore
`HOLD_KNOWLEDGE_ABOX_SCHEMA_EXPANSION`: a new POC job schema/identity mirror, direct row scan or
legacy FastAPI authority is not inferred from the approval. Product/DB/Neo4j/container remained
unchanged; K6 remains dependency-gated.

The K6 read-only entry audit found a reusable separate Knowledge Chat UI and historical bounded
GraphRAG implementation, but all four graph/release/snapshot/graphrag paths resolve to `NO_ROUTE`
in the authoritative Node Product. K1 source identities are not K5 instance evidence and general
Chat or generic Neo4j cannot substitute. K6 remains `NOT_STARTED_DEPENDENCY_GATE` until K5 has a
verified instance Release/projection; no K6 Product mutation was opened.

### Knowledge K2 audit/backlog receipts

| ID | Status | Current decision |
|---|---|---|
| `NODE_TEST_COUNT_108_TO_107_RECONCILIATION` | `CLOSED_AUDIT` | Same twelve-file script, no skip/TODO; Product `601a7ec...` consolidated two obsolete Graph contracts into one stronger DataHub-lineage-only/no-generic-Neo4j test. |
| `NODE_PROVIDER_PROBE_PARALLEL_FLAKINESS` | `BACKLOG_NON_BLOCKING` | Two parallel-only `ECONNRESET` receipts; focused and serialized runs pass. No test framework/provider redesign. |
| `FRONTEND_ASYNC_TEST_PARALLEL_FLAKINESS` | `BACKLOG_NON_BLOCKING` | Stable current evidence is the 87-file single-worker suite; address only as a small independent test slice. |
| `KNOWLEDGE_SECURITY_GRADE_CANONICAL_REALIGNMENT` | `CLOSED_IN_K4` | Current Knowledge UX/enforcement uses `normal < credential < restricted`; legacy values map read-compatibly without rewriting history. |

## 2026-08-17 Product priority realignment

Engineering Phase identifiers remain historical/dependency labels. Execution and the external
Korean dashboard use this user-facing order:

| Priority | Product area | Current boundary |
|---|---|---|
| P0 | PHASE 1D-R deterministic runtime | `COMPLETE_RUNTIME_VERIFIED` at Product `91ca4db7...` |
| P1 | Account / feature / data access | Core completed; add negative/regression acceptance when each feature integrates |
| P2 | MCL change management / automatic detection | `COMPLETE_RUNTIME_VERIFIED` for current-source catch-up, exact ledger, supported change capture and restart; actual KST midnight remains `TARGET_RECHECK_REQUIRED` |
| P3 | DEV support services | Airflow/MinIO `COMPLETE_RUNTIME_VERIFIED`; GX exact 1.19.1 seam `IMPLEMENTED_NOT_VERIFIED` because DataHub Assertion egress is absent |
| P4 | Registration | Authorization/preparation, manual-metadata apply, one READY candidate-to-governed-CR command and authoritative `NOT_STARTED` apply-report `COMPLETE_RUNTIME_VERIFIED`; mutation roles are data_steward/admin only; overall `PARTIAL` for durable preparation/outbox/provider-apply, remaining typed surfaces and target gates; accepted minimal relational direction awaits schema approval |
| P5 | Governance — policy/standard documents | `COMPLETE_RUNTIME_VERIFIED` for active-user read and data_steward/manager/admin create, DRAFT-version update and archive; viewer/developer mutation denied |
| P6 | Chat | General/Vector/AUTO and the pre-K7 DataHub-lineage-only Graph boundary are runtime-verified; actual fallback execution and K7 authorized Knowledge routing remain `PARTIAL` |
| P7 | Knowledge / Quality | Knowledge K0 through K4 Source Proposal are runtime-verified; K5 A-Box is `HOLD_KNOWLEDGE_ABOX_PERSISTENCE_DECISION` because current Node DEV has no approved physical-row authority. K6 is not started. Quality remains `USER_FEATURE_DEFINITION_REQUIRED` |
| P8 | Admin | Minimum controls required by real features only; no generic IAM/configuration console |

Controlled execution DAG:

```text
1D-R closeout
→ MCL runtime / automatic detection
→ DEV support services (Airflow / MinIO / GX)
→ Registration
→ Governance
→ Chat refinement
→ Knowledge / Quality briefing
→ AUTH-1E legacy retirement / AUTH-1F final isolation
→ remaining deployment backlog
```

Conflict-free read-only audits may run in parallel. Product mutations remain one coherent bounded
slice with exact file ownership and fresh Product/deployed evidence.

## 2026-08-17 MCL runtime / automatic-detection activation

Product `6c67242756ac3ee8fef0cf6d5d8084daaa857fa5` activates the existing current
DataHub/Kafka source contract without adding a ledger, checkpoint or event service. Direct catch-up,
replay idempotency, supported description/schema/lifecycle events, scheduler startup/same-day
receipt, same-configuration restart and the current-source Monitoring summary are
`COMPLETE_RUNTIME_VERIFIED` in the Node POC.

```text
sources / checkpoints / ledger / CR-link = 2 / 2 / 66 / 4
current source exact matches              = 1
current checkpoint next_offset / version  = 55596 / 2748
duplicate exact source positions          = 0
actual KST 00:00 observation              = TARGET_RECHECK_REQUIRED
```

Historical event lists/counts retain both sources. Only operational capture/sync/ledger-guarantee
status is scoped to the configured current source. Evidence:
`.orchestration/evidence/DEV-MCL-RUNTIME-AUTOMATIC-DETECTION.md`.

The current support-service and Registration boundary is:

- Airflow 3.3.0, the exact Registration DAG and service callback are bound through the existing DEV
  contract and actual Product runtime-verified.
- MinIO is bound as the existing external DEV dependency; Product part/complete and exact object
  cleanup passed. Its cross-workspace runtime ownership remains explicit and is not converted into
  an accidental new base service.
- GX exact version/runtime seams are present, but result→DataHub Assertion emission and a GMS/UI
  receipt are absent. Status is `IMPLEMENTED_NOT_VERIFIED` / `PARTIAL` with
  `GX_PREP_OPS_CONTRACT_EVIDENCE_REQUIRED`, not a fake runtime PASS or permission to invent egress.
- Registration's existing preparation/candidate flow now allows data_steward/admin only and enforces role + grant + grade + fixed
  policy + Responsible System, owner isolation and no-leakage projection. The slice is
  `COMPLETE_RUNTIME_VERIFIED`. Sparse empty manual metadata and one actual disposable description
  apply also passed exact Product receipts. Product `5e600320...` additionally creates exactly one
  server-authored CR from one READY candidate with current authority, ETag/idempotency/CAS and zero
  provider writes. Product `78448566...` makes the canonical truthful `NOT_STARTED` apply-report a
  server-owned `change.read` projection without synthesizing apply evidence. Overall Registration
  stays `PARTIAL` for durable preparation/outbox/apply, remaining typed surfaces and target-host
  gates. The read-only decision recommends reusing the accepted relational receipt/candidate/
  provenance contract; `HOLD_REGISTRATION_DURABLE_STORAGE_DECISION` still prevents schema mutation
  before explicit approval.
- Governance active-user read and data_steward/manager/admin create, DRAFT update and archive are
  `COMPLETE_RUNTIME_VERIFIED` at Product `fd379567...`; no Knowledge privilege, Table/System ACL or
  workflow was added. Chat General/Vector/AUTO remains the verified baseline; Graph awaits Knowledge
  provenance.

## 2026-08-08 Pilot handoff recovery and inherited-change review

The immediate delivery route is now development Mac source → closed-network amd64 WSL preparation
PC → file transfer to the closed-network Linux operations PC. The preparation PC may fetch Git and
may receive pre-downloaded dependency artifacts, but Docker builds there must not contact external
APT, package or image registries. The operations PC receives only a checksum-verified release that
passed on the preparation PC; a Mac container, image, volume, environment file or secret is never
promoted as target evidence.

The attached prior-session handover is **reference-only and unverified**. Its claims are not accepted
as migration, security or production evidence until the following work is completed against the
current `origin/dev` bytes:

| ID | Priority | Status | Required review / exit evidence |
|---|---:|---|---|
| PILOT-HO-01 | P0 | `PENDING` | Audit every post-`e23e5eb9` migration edit and the preparation database from revision `0061`. Current source contains early whole-revision returns and converts strict partial-schema failures to prints, including a no-op `0084`; an Alembic `0095` marker therefore does not prove functions, RLS, grants, constraints or indexes exist. Reconcile metadata/migrations/data-model docs, run empty-database and `0061→head` upgrades plus deliberate partial-state negatives on PostgreSQL 17, and define repair/restore handling before operations deployment. |
| PILOT-HO-02 | P0 | `PENDING` | Review the post-`e23e5eb9` Pilot release/security changes: digest stripping, image-ID mismatch acceptance, optional online frontend fallback, Keycloak `start-dev`, removal of read-only mode, direct LAN HTTP, and host-readable secret modes. Restore or explicitly approve an exact checksum/image/config/TLS/secret contract; preparation PASS must use the resulting committed bytes. |
| PILOT-HO-03 | P0 | `EXTERNAL_GATE` | On the preparation PC, fix the current environment validation without weakening the validator. `SYSTEM_CONFIGURATION_PROBE_PLAINTEXT_ALLOWED_IPS` contains exact IP literals only and must be a subset of `SYSTEM_CONFIGURATION_PROBE_ALLOWED_HOSTS`; otherwise leave the plaintext list empty. Preserve the default core service hosts and add only reviewed external connector hosts/IPs. Then rebuild/redeploy and capture fixed classification plus API/Web/OIDC, migration-head and container-health evidence. |
| PILOT-HO-04 | P1 | `PENDING` + `EXTERNAL_GATE` | Verify the external MinIO decision. `S3_CORS_MANAGEMENT_MODE=external` is acceptable only with an administrator-applied, read-back CORS policy and browser upload/download evidence; provider API incompatibility alone is not proof that CORS is correct. |
| PILOT-HO-05 | P1 | `PENDING` + `EXTERNAL_GATE` | Replace the handover's Neo4j example before use: no default password, no secret in argv/environment evidence, exact pinned amd64 image identity, dedicated secret file, fixed DataRiver network alias, persistent-volume ownership, health/read-back and PostgreSQL-canonical projection checks. |
| PILOT-HO-06 | P1 | `PENDING` | Audit `datariver-platform-amd64-distribution` independently: current required source-built images, pinned third-party images, Python/npm/OS artifacts, license/redistribution decisions, LFS object availability, checksums and offline build reproducibility. Do not rewrite its history merely because older artifacts appear unused. |
| PILOT-HO-07 | P1 | `PENDING` | Review the untracked root diagnostic/patch scripts and `test-import-dir/` as user-owned forensic material. Do not execute, stage, delete or treat them as accepted implementation until their provenance and relation to the committed migration changes are established. |
| PILOT-HO-08 | P0 | `EXTERNAL_GATE` | Promote preparation evidence to operations only after the same exact source/release checksum, amd64 image identities, offline build, database migration/repair, API/Web/OIDC and Level1/Level2 integration gates pass. Operations must use host-local reviewed `.env` and secrets, target-local backup/rollback, and its own DataHub/MinIO/Airflow/Neo4j/connectivity checks; preparation runtime state is not copied as proof. |
| PILOT-HO-09 | P2 | `PENDING` | After the preparation/operations platform is stable, resume the existing feature backlogs rather than creating parallel memory: Knowledge and Knowledge Studio, Quality authoring and Quality Run, Catalog/Search/API, governance, access/ABAC, Chat/LLM, monitoring, migrations and the controlled-document conflicts in this ledger. Revalidate any prior-session claims at the then-current exact SHA. |

Immediate stop conditions are any migration/schema uncertainty, unknown image/config identity, secret
or TLS regression, failed core health/OIDC check, or checksum/SHA mismatch. Starting containers is
not an acceptance result, and a preparation-only success is not a production or HA claim.

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

## Cross-agent handoff protocol

- Begin from a clean, fetched `dev` and record its full commit before making changes. Keep work on
  `dev`; never create a focused branch, rewrite `main`, or discard another worktree's changes.
- Read `AGENTS.md`, this ledger, `docs/README.md`, `docs/02_CONSTRAINTS.md`, the relevant PRD/spec,
  every applicable accepted ADR, and `docs/09_TEST_STRATEGY.md` before implementation. Product
  requirements and accepted ADRs remain authoritative; a handoff prompt cannot silently supersede
  them.
- Do not create another general constraints, backlog, memory or handoff document, and do not commit
  prompt transcripts or legacy attachments. Normalize newly accepted work and evidence into this
  ledger; use a new ADR only for an actual architecture decision.
- Preserve status semantics and external gates. Report only commands actually executed at the
  current commit, and never promote a mock, source-only pass or historical result to target evidence.
- Hand back the base commit, branch and HEAD, requirement/backlog IDs, commits, changed files,
  decisions, exact test results, unresolved/external gates, working-tree state and the next safe
  action. Secrets, local environment files, runtime data and generated provider artifacts are never
  part of the handoff.

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
- [x] Historical 2026-07-24 publication evidence is retained as a completed past event only.
  Current and future publication is authorized solely to Ever-Real `origin/dev`; `main` is an
  explicit owner-requested checkpoint.
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
- [x] Phase 6A locally corrects blank non-Mac token preflight and external connector-network
  startup ownership. Full source/config regressions pass; actual WSL/PowerShell/amd64 execution
  remains external. Independent security, portability and PM/traceability review reports
  `P0=0`, `P1=0` before the focused commit.
- [x] Phase 6B closes the atomic Sharing invocation contract at local commit `b6fe662`. Phase 6C
  retains ADR-0045/revision `0055` and adds the extended failure, identity, replay and lock matrix
  without treating WSL, real identity, target load or physical purge as local evidence.
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
| R1-09 | Use PRDs, checklists, independent reviews and traceable commits | `PARTIAL` | Controlled artifacts and local commits exist; this ledger is the continuation index. The remote branch is published only through `a683a93`; Phase 5 and later local work, PR review and merge remain open. |
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
| R2-12 | Resolve every Admin inventory row honestly | `DONE_LOCAL` + `EXTERNAL_GATE` | Displayed collections use bounded server cursors and stale-response guards. Per-member CR/table drill-downs now apply item-level ABAC; remaining audit/dictionary/profile-mutation gaps are explicit. Actual OIDC/WebAuthn browser acceptance remains external. |
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
| R4-01 | Probe Neo4j plus Chat, Embedding and Reranker adapters before feature execution | `DONE_LOCAL` + `EXTERNAL_GATE` | Current Mac evidence proves authenticated Neo4j `RETURN 1`, strict-JSON Chat, 1,024-dimensional Embedding inference and an ordered finite-score rerank through `LOCAL_LLAMA_CPP`. Ollama still has no rerank route; the bridge serves the Ollama-owned GGUF on fixed loopback port 11435 without inventing runtime activation. Revision `0053` retains the bounded private reranking TEST. WSL/private-provider DNS, TLS, credentials and responses remain unverified. |
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
| R4-12 | Expose selected catalog capabilities through typed HTTP APIs | `DONE_LOCAL` + `EXTERNAL_GATE` | Catalog and release-pinned Sharing APIs exist; subject-bound fixed invocations atomically commit quota/result/audit evidence and revalidate governed lineage/current authority. Target WSL/identity/load evidence remains. MCP is separately tracked by R4-13. |
| R4-13 | Expose a pinned Knowledge Asset version through bounded read-only MCP tools | `PENDING` | No current Node MCP route/server/test exists. Start only after K1 identity/provenance and later Asset/version plus Main Chat integration gates; reuse the Node modular monolith, fixed tool allowlist and service-auth pattern. Do not create a generic MCP platform, per-profile service or arbitrary Cypher surface. |

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

### Phase 6B atomic Sharing invocation closure — 2026-07-24

- [x] ADR-0045, PRD/checklist, API/data/security/deployment/operations/migration docs, SQLAlchemy
  metadata, generated `0001` and additive `0055` agree on subject-bound fixed local invocation.
- [x] Ledger, exact result, monthly quota and separate `AUDIT_EVIDENCE`/body retention bindings
  commit together; app direct table access, disabled triggers, malformed RLS and inherited SECDEF
  capability fail closed.
- [x] Repository-owned clean-room harness passed canonical/additive/no-evidence downgrade,
  evidence downgrade refusal, seeded legacy row/month backfill, seven tamper probes, `alembic
  check`, deterministic generation and `9` actual PostgreSQL tests. Canonical SHA-256 is
  `ffc0abb58b3f4550bcc5d1524ffd9cd954076d0bf73112cab19fc7b3252e7c2f`.
- [x] Whole backend `1,417 passed / 93 environment-gated skipped`; whole frontend `46 files / 244
  tests`, type/lint/build; Ruff, strict mypy and static verification passed.
- [x] Final independent SQL/security, persistence/test and traceability re-audits report
  `P0=0`, `P1=0`.
- [ ] WSL `linux/amd64`, real Keycloak service identity, target load/lock/soak and physical purge
  remain `EXTERNAL_GATE`.

### Phase 6C atomic Sharing hardening closure — 2026-07-24

- [x] Contract timeout, canonical serialization and three precommit persistence fault points leave
  invocation, result and monthly usage at zero; stable `429` responses carry `Retry-After` and
  `private, no-store`.
- [x] Every ineligible consumer Subject shape and missing/wrong fixed-function security context is
  denied without grant, idempotency, outbox or invocation side effects.
- [x] Permission, current-version, grant-expiry, governed-lineage, active-policy and result-deadline
  drift deny replay without invoking the result builder.
- [x] Invoke-first and mutation-first revoke/publish interleavings use observed PostgreSQL blockers,
  terminate without deadlock and expose only an old-valid success or new-valid denial.
- [x] Clean-room PostgreSQL 17 passed `13` tests; whole backend passed `1,419 / 97 skipped`, whole
  frontend passed `46 files / 244 tests`, and canonical migration SHA-256 remains
  `ffc0abb58b3f4550bcc5d1524ffd9cd954076d0bf73112cab19fc7b3252e7c2f`.
- [x] Final independent SQL/security, persistence/test and traceability audits report `P0=0`,
  `P1=0`; the focused Phase 6C commit closes this package before the next work item.
- [ ] WSL `linux/amd64`, real Keycloak identity/rotation, target load/soak and physical purge remain
  `EXTERNAL_GATE`.

### Phase 6D Admin/auth session-epoch closure — 2026-07-24

- [x] OIDC and server profile subjects must match; generation/abort fencing makes the newest
  hydration authoritative and unload/sign-out invalidates memory before completion.
- [x] The opaque in-memory security epoch binds every request/download to its Workspace. Drift
  discards late response bodies and prevents read or durable-idempotency retry across sessions.
- [x] Ordinary same-session renewal keeps the stable API client and unrelated feature state while
  an accepted-hydration revision hides and reloads Admin. An unchanged context resumes the mounted
  subtree; epoch/context drift, mismatch or denial remounts/purges it.
- [x] `/auth/me` and `/admin/me` use no-store request semantics and return
  `Cache-Control: private, no-store`; no new persistent browser authority exists.
- [x] Focused auth/API/shell/Admin tests passed `69`; whole backend passed
  `1,421 / 97 skipped`; whole frontend passed `47 files / 266 tests`; Ruff, strict mypy,
  TypeScript, ESLint, production build and static verification passed.
- [x] Final independent security/application/traceability re-audits report `P0=0`, `P1=0`; this
  checklist and the accepted source/test changes form one isolated focused commit.
- [ ] Real IdP account/session transition, multi-tab/browser cache, edge-header preservation and
  WSL `linux/amd64` acceptance remain `EXTERNAL_GATE`.

### Phase 6E web Nginx security-header closure — 2026-07-24

- [x] Reproduced the historical inheritance defect: cache-defining runtime/SPA/asset locations lost
  CSP, nosniff, referrer, frame and permissions headers while `/healthz` retained them.
- [x] Pinned Nginx `1.30.3` recursively merges the canonical five `always` rules into every
  location; static verification rejects missing merge, drifted values or missing API normalization.
- [x] Static/unit gates require the API proxy hide set to contain exactly those five names. The
  runtime matrix preserves cache, authentication, retry, exact ETag/Vary, content-disposition and
  request-ID headers.
- [x] Empty/populated renders and the native arm64 current-source image passed the offline
  health/runtime/SPA/asset/API `200/304/404/503/504` matrix with exact header cardinality. Static
  and live gates reject inner-server HSTS while real HTTPS-edge HSTS remains external.
- [x] Whole backend passed `1,424 / 97 skipped`; whole frontend passed `47 files / 266 tests`;
  Ruff, strict mypy, TypeScript, ESLint, production build and static verification passed.
- [x] Final independent security/SRE/traceability re-audits report `P0=0`, `P1=0`; this checklist
  and the accepted source/test changes form one isolated focused commit.
- [ ] Native WSL `linux/amd64`, real TLS/HSTS/APISIX preservation, target browsers, OIDC and
  approved embedded-provider journeys remain `EXTERNAL_GATE`.

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
| R5-BE-05 | P0 | Make API-product idempotency, per-minute/monthly quota checks and invocation/result recording atomic; bind request hash and replayable response so retries cannot bypass quota or repeat work. | `DONE_LOCAL` + `EXTERNAL_GATE`; revision `0055`, subject/issuer/client grants, separate audit/body retention, fixed DB capabilities and the clean-room PostgreSQL harness pass. WSL/real Keycloak/target load/physical purge remain external. |
| R5-BE-05H | P1 | Complete the extended atomic-Sharing hardening matrix: timeout/429, all grant-Subject negatives, injected persistence failures, full expiry/lineage drift and invoke/revoke/publish interleavings. | `DONE_LOCAL` + `EXTERNAL_GATE`; Phase 6C source/clean-room DB matrix passes. WSL, real Keycloak, target load/soak and physical purge remain external. |
| R5-FE-01 | P0 | Bind global search requests/results to Workspace epoch and abort/discard cross-workspace responses. | `DONE_LOCAL`; Top Navigation keys the search component by Workspace and a late-response regression proves purge/discard. |
| R5-FE-02 | P1 | Bind Admin context/auth hydration and renewal to subject/session epoch. | `DONE_LOCAL` + `EXTERNAL_GATE`; latest-only subject-matched hydration, opaque epoch request/retry fencing, Admin revision reload/teardown and private no-store discovery pass current source. Real IdP/browser/WSL journeys remain external. |
| R5-FE-03 | P1 | Preserve CSP/security headers in every Nginx location. | `DONE_LOCAL` + `EXTERNAL_GATE`; exact inheritance/API normalization, embedded-source native arm64 runtime, full regression and independent audits pass. Target edge/browser/WSL evidence remains external. |
| R5-FE-04 | P2 | Validate runtime API/OIDC origins before any Bearer-bearing request. | `DEFERRED_BY_OWNER`; current runtime configuration selection validates neither an API same-origin `/api/v1` boundary nor an exact OIDC redirect origin before constructing Bearer/OIDC flows. A later package should fail closed on malformed/non-string/cross-origin API values, require a fixed same-origin callback plus approved HTTPS IdP (loopback-only HTTP development exception), prevent redirect following on Bearer requests, provide a bounded configuration-error UI, align the IdP origin with CSP, and add negative token-exfiltration/callback tests. No Phase 6F code remains in the worktree. |
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
| R5-DEP-01 | P0 | Fix blank WSL bootstrap token instructions and raw-Compose external-network failure. | `DONE_LOCAL` + `EXTERNAL_GATE`; token validation now precedes all persistent mutation, only approved file paths are accepted, Bash/PowerShell wrappers own validated idempotent network provisioning, operational docs use the wrappers, and native/amd64 Compose renders pass. Native PowerShell and target WSL/Docker/provider execution remain external. |
| R5-DEP-02 | P1 | Add env schema/version migration and Bash/PowerShell profile parity. | `PENDING` |
| R5-DEP-03 | P1 | Resolve the literal `.env`/Compose `linux/amd64` request against ADR-0034: compose-wide amd64 forcing conflicts with native Mac runtime safety, so runtime stays native and validated while explicit `--platform` is restricted to release builds. Record the accepted substitution and never hardcode `FROM --platform=linux/amd64`. | `CONFLICT` |
| R5-DEP-04 | P1 | Pin Airflow/APISIX/observability images and dependency hashes; reject unpinned production overrides. | `PENDING` |
| R5-DEP-05 | P1 | Reduce Compose network, host-gateway, secret, writable-path and runtime-principal blast radius per process and verify no-new-privileges/read-only/capability boundaries. | `PARTIAL`; the Knowledge worker has a non-root read-only container, worker-only spool, process-specific DB/S3/LLM secrets and no Neo4j dependency. Cross-platform review of the remaining processes is still pending. |
| R5-DEP-06 | P2 | Fingerprint controlled migration function bodies/owners during additive re-entry. | `PENDING`; current re-entry validates required object names, grants and policies but not every body hash. |
| R5-TEST-01 | P2 | Complete the remaining durable Knowledge enqueue no-row and maximum-attempt exhaustion matrices. | `PENDING`; exact unclaimed cases are listed in the Phase 5 checklist. |
| R5-ARCH-01 | P2 | Split high-complexity Admin/config/DataHub/catalog/knowledge modules only after behavior tests lock contracts. | `PENDING` |
| R5-ARCH-02 | P2 | Consolidate duplicate upload/hash/polling state machines and clean only evidenced dead legacy code. | `PENDING` |

## Change Management 제품화 잔여 backlog (2026-08-16)

이 표는 product `4aea6d19c64253130e00d997c2837b74fac4837d`와 evidence
`313a559bdd9300d3ee2021935d2dbac0319bafd1`의 DEV runtime 결과를 기준으로 한다. PREP/OPS 결과를
DEV 증거로 승격하지 않는다.

| ID | Priority | Item | Status / acceptance gate |
|---|---:|---|---|
| CM-PROD-01 | P1 | `VECTOR_PROVIDER_UNAVAILABLE` 복구와 Chat/vector deleted-current target 재검증 | `TARGET_RECHECK_REQUIRED`; Search/Tree current lifecycle PASS를 되돌리지 않음 |
| CM-PROD-02 | P1 | PREP targeted recheck: Linux/amd64, Kafka advertised listener, Registry, env/secret, exact boundary/catch-up | `TARGET_RECHECK_REQUIRED` |
| CM-PROD-03 | P0 | OPS validation/deployment, artifact checksum, backup/restore/rollback, compatible provider/security/HA gate | `NOT_EXECUTED` |
| CM-PROD-04 | P2 | 실제 KST 00:00 wall-clock 관찰 | `DAILY_CLOCK_NOT_OBSERVED`; startup catch-up/same-day receipt는 DEV verified |
| CM-PROD-05 | P1 | GX/Quality result와 Quality 메뉴 연계 | `BACKLOG`; 별도 workstream |
| CM-PROD-06 | P2 | Chat routing/retrieval/response refinement | `BACKLOG`; current/deleted correctness와 분리 |
| CM-PROD-07 | P2 | Vite production chunk-size warning 해소 | `BACKLOG`; 기능 blocker 아님 |
| CM-PROD-08 | P1 | POC secret-file/direct secret injection 지원 여부 결정 | `BACKLOG`; 현재 host-local ignored `.env` → container env 계약만 지원 |
| CM-PROD-09 | P1 | `Dockerfile.local retirement / drift removal`: tracked canonical Dockerfile only로 수렴 | `BACKLOG`; local file은 임시 DEV/PREP compatibility일 뿐이며 scheduler/MCL COPY·package/lock·revision drift 검증 필수 |
| CM-PROD-10 | P1 | legacy `scripts/export_poc_release.sh`의 static/simulated/no-remote bundle을 current live-provider release contract로 교체하거나 명시적으로 retire | `BACKLOG`; 현재 canonical 배포는 tracked Compose build/update runbook |
| CM-PROD-11 | P1 | DataHub Timeline retained-history initial backfill adapter와 target retention gate 구현 | `BACKLOG`; ADR-0123 계약만 존재하고 current Node runtime에는 미구현 |
| CM-PROD-12 | P1 | `REPRODUCIBLE_DEPLOYMENT_ACCEPTANCE`: `git pull → config/secrets → exact-revision build → Compose A/B up → health/smoke` 인수 계약 | `BACKLOG`; tracked Dockerfile, source/image revision equality, no manual network connect, Linux/amd64 PREP/OPS evidence로 닫는다 |
| CM-PROD-13 | P1 | `POC_SCHEMA_MIGRATION_CONTRACT`: existing-volume schema version, ordered upgrade, read-back, rollback/forward-fix 계약 | `PARTIAL`; ADR-0126 audit가 clean-volume init, runtime additive DDL, existing-volume manual apply와 checksum/ledger 부재를 확정했다. 현 `001` 동결과 이후 numbered additive migration을 권장하나 empty/current/repeat/recovery 검증 slice는 미구현 |
| CM-PROD-14 | P2 | browserless `127.0.0.1:39080` attachment URL fallback 검토/제거 | `BACKLOG`; browser runtime은 `location.origin`을 쓰며 현재 Change Management provider endpoint 계약과는 분리 |

PHASE 1C current account/access status (current Product/Evidence SHA is recorded by the phase
evidence, not inferred from this table):

| Slice | Canonical Status | Current boundary / next gate |
|---|---|---|
| PHASE 1C-2H | `COMPLETE_RUNTIME_VERIFIED` | Product `9df97f4975a990819db655b74b09e709dc6d5aad`: canonical grade/current-Table helper, concurrent last-Admin CAS invariant, atomic password-reset session revocation, exact-first mapping resolver and fresh runtime/Validator evidence passed |
| PHASE 1C-3 | `COMPLETE_RUNTIME_VERIFIED` | Product `9df97f4975a990819db655b74b09e709dc6d5aad`: fixed 120-cell management state/API/UI and POC gateway forwarding passed full source tests, DEV runtime, real browser and fresh Validator; PHASE 1D enforcement explicitly not active |
| PHASE 1C-4 | `COMPLETE_RUNTIME_VERIFIED` | Product `773cd37e6d48cbba02c999380fe1965a3b9f4e26`: exact responsible-System, request-principal workflow commands, independent three-lane completion, concurrency/legacy-read compatibility and canonical browser-origin hardening passed source, DEV runtime, browser and fresh Validator gates. |
| PHASE 1D | `PARTIAL` overall | Product `91ca4db7ca792566b7765f3366036b1d8bed2869` froze bounded local enforcement, canonical higher-grade Table matrix, PostgreSQL/memory pre-ranking, Product General/Vector/AUTO/context/citation and deterministic provider restart as `COMPLETE_RUNTIME_VERIFIED`; Product `fd379567a220f1e677deb5225b8e0b36c1d28d8d` preserves the Registration baseline and completes bounded Governance document management. Provider-wide traversal/totals, Neo4j URN provenance, deleted-grade history, unbound Knowledge and Quality/GX retain their named `PARTIAL`/`BLOCKED` states. Account/Auth core is a completed baseline; do not falsely promote those surfaces or keep expanding core auth ahead of their owning product features. |

### EPIC: MODULAR_PRODUCT_ARCHITECTURE (`P1`)

목표는 feature isolation, 변경 blast-radius 감소, domain portability, 다른 metadata platform adapter와
배포 단위 안정성이다. 현재 runtime을 대규모 refactor하지 않으며
[`ADR-0124`](adr/0124-poc-modular-product-architecture.md)의 단계와 gate를 따른다.

- [ ] `change-history`, `change-management`, `access`, `catalog-current`, `monitoring` 논리 port 고정
- [ ] `adapters/datahub`, `adapters/storage`, `application/http` dependency direction 검증
- [ ] frontend feature-local API/type 경계 정의
- [ ] provider-neutral `MetadataChangeProvider`/`CurrentCatalogProvider` conformance tests
- [ ] 실제 두 번째 provider 요구 또는 측정된 blast-radius evidence 전에는 framework/service 추가 금지

## Request group 6 — final controlled artifacts

The owner explicitly directed documentation to start after Phase 6E and deferred the remaining
hardening/testing packages. Until target WSL acceptance is supplied, these deliverables are
`target-gated` current-source summaries rather than production acceptance.
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
