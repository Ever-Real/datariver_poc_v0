# Phase execution checklist

This is the active continuation checklist for the v0.3-to-v1 parity work. Phase 3 is deliberately
paused by the product owner on 2026-07-18 while Phase 1 and the subsequently assigned Phase 2 are
completed. It does not mark an item complete until source, focused tests and the applicable runtime
check have passed.

## Phase 1 — system blockers and required UI

- [x] P1-01 Allow the externally operated `v1.6.0rc1` only through the deployment-owned
  `DATAHUB_ALLOWED_VERSIONS` setting, constrained to the configured exact stable release.
- [x] P1-02 Confirm the capability is healthy for the explicitly allowed runtime version and retain
  mismatch degradation/enforcement for every other version.
- [x] P1-03 Repair the port-5173 Vite public OIDC/proxy configuration and verify custom-login
  redirect/callback return-to behavior.
- [x] P1-04 Restore the v0.3-positioned administrator profile dropdown with server-verified,
  React-memory identity and administrator capability state only.
- [ ] P1-05 Run the focused static/unit/browser checks; commit and push the completed Phase 1 scope.

## Phase 2 — approved seed-data workflow

- [x] P2-01 Record the semiconductor value-chain seed-data scope, safety guardrails, reproducible
  generator workflow, ingestion recipe and Airflow orchestration in the repository documentation.
- [x] P2-02 Implement and verify the approved PostgreSQL seed generation and DataHub ingestion
  workflow without changing the paused Phase 3 UI scope.

## Phase 3 — parity continuation

Source implementation is committed in `589aec3`, `2172c6d`, `6f7c233`, and `ba05ccb`. The browser
checks below used the configured administrator session at `localhost:5173` on 2026-07-18; they are
not a substitute for a release-environment ABAC or retention-policy decision.

- [x] P3-01 Complete `UX-PAR-002` through `UX-PAR-005`: authorized Resource Tree, search results,
  catalog detail and the bounded lineage entry point. After the paged DataHub reconciliation the
  browser rendered 2,010 administrator-reviewable assets (PostgreSQL 1,010; Oracle 1,000), with 50
  rows per result page and cursor-based tree expansion rather than an unbounded browser payload.
- [x] P3-02 Complete `UX-PAR-006` through `UX-PAR-011`: manual/bulk registration and governed
  change-request evidence flows. Browser verification selected
  `datariver_core.semiconductor_seed.fact_daily_stock_price` and rendered description, column, and
  typed Domain/Tag/Term change proposals plus current fields and lineage.
- [x] P3-03 Complete `UX-PAR-012` through `UX-PAR-017`: knowledge registry, change studio and
  bounded graph exploration UI backed by the real knowledge API contracts.
- [x] P3-04 Complete `UX-PAR-018` through `UX-PAR-022`: monitoring, governance and Chat capability
  states and their real API contracts. Monitoring and governance browser checks pass. For local
  development only, a security-administrator can make an explicitly labelled `EPHEMERAL_NO_STORE`
  Chat exchange when no retention policy exists; it creates no session, message, citation, or
  retention record. Production configuration rejects that switch and all ordinary users retain the
  regular retention-policy gate.
- [ ] P3-05 Complete `UX-PAR-023` reference-viewport visual and administrator/non-administrator
  browser acceptance. The administrator viewport and restored profile menu passed, and a temporary
  ordinary Keycloak identity (no workspace or administrator membership) rendered without a runtime
  error and without administrator entries. The temporary identity was removed after the test;
  agreed reference screenshots remain required acceptance input.

## Phase 3.5 — integration blocker correction

- [x] P3.5-01 Reconcile the full DataHub catalog projection through the Airflow-owned, paged sync
  contract. Host development sends the authenticated service call through APISIX; the deployed
  origin is configuration, not a source-code localhost fallback.
- [x] P3.5-02 Preserve the audited security-administrator quarantine-review scope on catalog tree,
  facets, search and detail reads. It does not become a general ABAC bypass for exports, mutations,
  or Chat evidence.
- [x] P3.5-03 Permit the labelled development-only, administrator-only no-store Chat exchange
  described in P3-04 so local retention-policy absence cannot return HTTP 409 during UI testing.
- [x] P3.5-04 Verify the ordinary-user viewport and administrator-menu concealment with a live OIDC
  sign-in; remove the temporary weak-password test identity immediately afterwards.

## Phase 3.5 — parity detail restoration and integration correction

The following items are the product-owner-directed continuation received on 2026-07-18.  They are
kept separate from the earlier integration blocker record so that a visual restoration is not
mistaken for an authorization or release approval.

- [x] P3.5-05 Make Governance Center and dashboard shortcuts use the in-application history
  transition, preserving the hydrated authentication state without a document reload.
- [x] P3.5-06 Complete the authorized Catalog result/detail presentation: typed table/view labels,
  real projection hierarchy and owner/domain/term/tag fields, bounded server-filtered columns,
  URN copy feedback, and the local authorization-pruned lineage graph as the primary graph action.
  The 2026-07-18 administrator browser check rendered `TABLE (1,009)` and `VIEW (1,001)` from the
  reconciled 2,010 real assets.  A field absent from the DataHub source is displayed as `—`; it is
  never inferred from the URN or fabricated in the browser.
- [x] P3.5-07 Correct typed DataHub browse-container normalization so PostgreSQL and Oracle
  database/schema paths both populate the cursor-paged Resource Tree and MANUAL selector.  Never
  reconstruct a hierarchy from a provider URN in the browser.  Provider records without a database
  container are represented by their real schema node; the verified Oracle `SEMICONDUCTOR_SEED`
  node expanded to its 1,000 assets.
- [ ] P3.5-08 Restore the v0.3-equivalent visible catalog filters and managed CSV/XLSX export entry
  points using the existing server-authorized export-job boundary; the quarantine-review scope must
  not grant export. Filters and export-job entry points are present, and the opt-in local
  `catalog-export` worker now uses an independent NOBYPASSRLS database/S3 principal. XLSX delivery
  and an authorized end-to-end download remain open; neither is simulated.
- [ ] P3.5-09 Restore registration MANUAL/BULK tab density, Korean hover help, and the v0.3
  MANUAL workbench layout.  The CR-coupled body is now replaced by an independent typed submission
  and immutable CSV-receipt stage; the Airflow-owned provider apply/read-back gate remains open.
- [x] P3.5-10 Restore change-management overview counts, status badges, complete list columns and
  the `신규 CR 신청` entry point from the same authorization-filtered change-request read model.
- [x] P3.5-11 Assess and implement a simplified administrator role-access experience over governed
  workspace membership requests.  The role templates use the live action vocabulary and canonical
  membership Access document with ETag, confirmation and audit boundaries.  RBAC improves the
  administrator experience, while server-side ABAC remains the enforcement layer; no browser or
  generic DataHub Policy API mutation path is permitted.

## Ordered parity recovery — 2026-07-18

The current implementation begins only after a new v0.3 React/API-router source audit.  The
authoritative item-level inventory is `PAR-REC-001` through `PAR-REC-017` in
[`15_LEGACY_UX_PARITY_PLAN.md`](15_LEGACY_UX_PARITY_PLAN.md).  Execute the following in order; each
number is independently committed only after its relevant checks pass.

- [x] R1-01 Home/session: verified default Workspace hydration and dashboard CSR navigation.
- [x] R1-02 Catalog: full authorized paging/tree/detail/filter/export presentation with the narrow
  administrator quarantine-review scope unchanged.
- [ ] R1-03 Registration: archive and replace the MANUAL body; compact tab parity and shared Oracle
  selector behavior are implemented.  The queued submission still requires Airflow apply/read-back
  before this recovery item is complete.
- [ ] R1-04 Change management: schema/system-assignee summary and complete typed list fields. The
  duplicate CR entry point is removed; the remaining modal restores the v0.3 multi-target/manual
  intake, private attachments and explicit non-provider `COMPLETED` workflow from ADR-0022.
- [ ] R1-05 Administration: user/system master parity and governed external-service profile master.

The complete item-by-item source inventory remains the controlled matrix in
[`15_LEGACY_UX_PARITY_PLAN.md`](15_LEGACY_UX_PARITY_PLAN.md). This checklist tracks sequencing, not
authorization: a checked UI item never substitutes for a server-side ABAC, retention or production
release gate.

## Resumed parity audit — 2026-07-18

The following inventory was re-created from the v0.3 React pages and their API routers before
continuing implementation.  It is a feature/contract checklist, not an archive of legacy source;
replaced source is retained only under `.legacy_archive/`.

- [x] RES-01 Audit workspace hydration (`v0.3 App`/auth) against v1 `/auth/me`, OIDC callback and
  Dashboard navigation.  The v1 contract selects an active default membership only in server
  response and holds it in React memory; authenticated browser verification remains a deployment
  gate when no local session is available.
- [x] RES-02 Audit Search (`SearchPage`, catalog router): suggestion preview, multi-keyword search,
  safe match highlighting, advanced filters, Resource Tree, dense paged table, CSV/XLSX export,
  details, bounded lineage and DataHub-lineage dialog.
- [ ] RES-03 Verify the configured DataHub lineage embedding capability with an administrator SSO
  session. Local bootstrap now accepts an exact, credential-free DataHub embed origin, and the
  locally inspected upstream response permits framing; authenticated DataHub SSO rendering remains
  open. The application must not turn an upstream DataHub 403 into a generic administrator bypass
  or send a provider token to the browser.
- [x] RES-04 Audit Registration (`IngestionPage`, `MetadataEditTable`, `ColumnEditTable`,
  `CreatableTagSelect`, ingestion router): selected table/column inputs, comma/Enter tag and term
  selection, controlled vocabulary suggestions/creation, manual CSV evidence, bulk evidence, and
  Airflow handoff.
- [ ] RES-05 Replace the v1 CR-coupled MANUAL body after archiving it.  Implement a separate,
  idempotent manual-submission aggregate, immutable audit/items, server-authored CSV receipt in
  deployment-configured `datariver-infoschema`, and an Airflow-owned apply/read-back flow.  Source
  implementation now verifies the persisted CSV before bounded typed aspect merge/read-back, but
  the configured bucket, migration `0024`, Airflow service identity and real DataHub provider run
  must still be verified together.
- [ ] RES-06 Audit and restore Change Management (`ChangeManagementPage`, `CRListTable`,
  `CRRegistrationModal`, CR router): schema/system/assignee overview, complete list fields, create
  form and lifecycle, and private request/test attachment manifests. The v1 page now opens one
  independent CR modal (never Registration), searches live DataHub-backed tables, restores
  multi-target/column and manual-table inputs, uses live Term/Tag vocabulary suggestions, and
  uploads/downloads private request/test evidence through `datariver-filefolder`. Existing targets
  are re-read server-side; manual changes complete through ADR-0022's explicit accountable workflow.
  Authenticated role-journey/browser acceptance remains.
- [ ] RES-07 Audit and restore `/admin` (`UsersPage`, `SystemsManagementView`, `ConnectionsPage`,
  user/system/config routers): subject/membership master, system/schema/assignee priority, and
  redacted approved service-profile administration.  Password provisioning, arbitrary URLs,
  raw YAML and browser-controlled connection tests remain out of scope by design.

## Phase 3.6 — governed Registration execution and evidence

This package implements ADR-0041 without converting arm64/local checks into WSL or production
claims.

- [x] REG-01 Fail closed before Manual/BULK resource reads unless the DataRiver session is an active
  human security administrator or canonical Data Steward; expose no raw claim/token evidence.
- [x] REG-02 Make Manual CSV receipt creation conditional and immutable; preserve the approved
  `UPLOAD_METADATA_MANUAL_YYMMDD_SERIAL.csv` naming contract.
- [x] REG-03 Fence Manual execution with database time, monotonic lease evidence, at most 20
  attempts and one APPLYING row per asset.
- [x] REG-04 Record append-only attempt and five-aspect read-back reports; require matching hashes
  before APPLIED.
- [x] REG-05 Provide bounded owner/Admin history, exact report polling, stale-request cancellation
  and explicit terminal/retry UI states.
- [x] REG-06 Fence BULK preparation by database time, cap typed files at 16 MiB/10,000 rows and
  publish only complete immutable receipt/candidate evidence.
- [x] REG-07 Re-read one current ACTIVE DATASET, preserve unknown provider fields and bind a V2
  candidate/receipt/object-locator SHA-256 into an ETag-fenced preview.
- [x] REG-08 Commit one candidate binding, one server-authored Change Request item and outbox
  evidence atomically; deny no-op, stale and duplicate creation.
- [x] REG-09 Replace unbounded Change Request hydration with keyset summaries, selected detail and
  hard aggregate/apply-report caps.
- [x] REG-10 Install Alembic `0046` fail-closed compatibility, forced RLS, restrictive reader
  policies, append-only evidence triggers and column-bounded grants.
- [x] REG-11 Prove a real isolated MinIO concurrent same-key conditional create and complete byte
  read-back; remove the test bucket afterward.
- [x] REG-12 Prove PostgreSQL 17 blank/current, additive `0045 -> 0046`, generated-baseline re-entry
  and malformed-column fail-closed paths; remove the disposable database afterward.
- [x] REG-13 Pass repository-wide backend/frontend/static/deterministic-migration gates on the final
  source candidate.
- [x] REG-14 Resolve all independent security/data/SRE/UI P0/P1 findings and rerun affected gates.
- [ ] REG-15 Focused Phase commit `b83a1fb` exists locally. Remote publication awaits explicit
  approval for the substantial payload to `origin/codex/admin-policy-rbac`; WSL, multi-human OIDC,
  external-Airflow and real-DataHub acceptance remain `EXTERNAL_GATE`.
- [x] REG-16 Add `0047` atomic worker call receipts, exact state history and proactive closure of
  superseded expired Manual/BULK calls; reject attempts-only fabricated supersession.
- [x] REG-17 Add `0048` exact apply-job/attempt/CR lease and privilege fencing; completed work cannot
  restart and APPLIED/APPLY_FAILED cannot be rewound by a non-governance role.
- [x] REG-18 Add `0049`/`0050` globally collision-safe attachment identities and a two-principal
  `202 STARTED -> worker claim/HEAD/full-SHA STORED -> current-human finalize` flow. Direct
  app/upload mutation and attachment INSERT are denied, and lost responses use a private bounded
  exact-ID status route or a server-filtered current-round STORED recovery list.
- [x] REG-19 Prove deterministic canonical `0001` SHA-256
  `1ca5b11f1c78ae6a193b2beca9f5ef19d252a2c59b32f955be0d10cf298ebbce`,
  blank `0001 -> 0050`, clean `0047 -> 0050` re-entry, 16 actual PostgreSQL security/recovery
  cases, and fail-closed `0048` rejection of a deliberately corrupted completed-job/request pair.
- [x] REG-20 Pass the final local gate set: backend 1,152 passed / 46 explicit external skips,
  strict mypy over 333 files, Ruff/static verification, frontend 44 files / 230 tests,
  TypeScript/ESLint and production build. `npm audit` remains an explicit external manifest-
  disclosure permission gate and is not represented as executed.

## Phase 3.7 — typed BULK catalog metadata rows

The controlled PRD and detailed TDD/acceptance checklist are in
`docs/30_TYPED_BULK_CATALOG_METADATA_PRD.md`. This phase preserves ADR-0016's one-candidate/one-CR
execution boundary and implements ADR-0042 with row-to-Aspect grouping, local vocabulary IDs and
no browser-supplied target URNs, Aspects or documents.

- [x] TB-01–03 Two wide-row profiles, canonical CSV/XLSX row/group vectors and attack negatives.
- [x] TB-04–06 separate immutable row/group evidence, fenced publication and authorized reads.
- [x] TB-07–09 fixed-Aspect compiler/binding, apply-time human reauthorization and read-back.
- [x] TB-10 bounded UI profile/template/candidate/preview states.
- [x] TB-11–12 full source, deterministic migration and actual PostgreSQL gates.
- [x] TB-13–15 independent P0/P1 audit, focused commit/publication boundary and external-gate report.
