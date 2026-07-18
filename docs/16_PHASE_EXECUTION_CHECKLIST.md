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
  catalog detail and the bounded lineage entry point. The browser rendered ten permission-scoped
  PostgreSQL assets; the DataHub lineage view rendered the seeded `vw_cost_ledger_advanced_package`
  graph with its three upstream datasets.
- [x] P3-02 Complete `UX-PAR-006` through `UX-PAR-011`: manual/bulk registration and governed
  change-request evidence flows. Browser verification selected
  `datariver_core.semiconductor_seed.fact_daily_stock_price` and rendered description, column, and
  typed Domain/Tag/Term change proposals plus current fields and lineage.
- [x] P3-03 Complete `UX-PAR-012` through `UX-PAR-017`: knowledge registry, change studio and
  bounded graph exploration UI backed by the real knowledge API contracts.
- [ ] P3-04 Complete `UX-PAR-018` through `UX-PAR-022`: monitoring, governance and Chat capability
  states and their real API contracts. Monitoring and governance browser checks pass; an evidence
  Chat query is correctly rejected with HTTP 409 until an accountable owner activates a retention
  policy. Do not bypass this server-side retention gate with a client-side success state.
- [ ] P3-05 Complete `UX-PAR-023` reference-viewport visual and administrator/non-administrator
  browser acceptance. The administrator viewport and restored profile menu passed; the separate
  non-administrator identity and the agreed reference screenshots remain required acceptance inputs.

The complete item-by-item source inventory remains the controlled matrix in
[`15_LEGACY_UX_PARITY_PLAN.md`](15_LEGACY_UX_PARITY_PLAN.md). This checklist tracks sequencing, not
authorization: a checked UI item never substitutes for a server-side ABAC, retention or production
release gate.
