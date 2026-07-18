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

The complete item-by-item source inventory remains the controlled matrix in
[`15_LEGACY_UX_PARITY_PLAN.md`](15_LEGACY_UX_PARITY_PLAN.md). This checklist tracks sequencing, not
authorization: a checked UI item never substitutes for a server-side ABAC, retention or production
release gate.
