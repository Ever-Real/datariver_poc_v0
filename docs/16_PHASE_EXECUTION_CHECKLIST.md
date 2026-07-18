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
- [ ] R1-04 Change management: schema/system-assignee summary and complete typed list fields.
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
  form and lifecycle, and private request/test attachment manifests.
- [ ] RES-07 Audit and restore `/admin` (`UsersPage`, `SystemsManagementView`, `ConnectionsPage`,
  user/system/config routers): subject/membership master, system/schema/assignee priority, and
  redacted approved service-profile administration.  Password provisioning, arbitrary URLs,
  raw YAML and browser-controlled connection tests remain out of scope by design.
