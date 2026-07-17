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

## Phase 2 — pending product-owner instruction

- [ ] P2-01 Record the supplied scope, acceptance criteria and any deployment evidence requirements.
- [ ] P2-02 Implement and verify the approved Phase 2 work without changing the paused Phase 3 scope.

## Phase 3 — parity continuation (paused)

- [ ] P3-01 Complete `UX-PAR-002` through `UX-PAR-005`: authorized search, catalog detail and
  DataHub lineage browser acceptance.
- [ ] P3-02 Complete `UX-PAR-006` through `UX-PAR-011`: manual/bulk registration and governed
  change-request evidence flows.
- [ ] P3-03 Complete `UX-PAR-012` through `UX-PAR-017`: knowledge, graph and evaluation workflows.
- [ ] P3-04 Complete `UX-PAR-018` through `UX-PAR-022`: monitoring, governance and Chat capability
  states and their real API contracts.
- [ ] P3-05 Complete `UX-PAR-023` reference-viewport visual and administrator/non-administrator
  browser acceptance.

The complete item-by-item source inventory remains the controlled matrix in
[`15_LEGACY_UX_PARITY_PLAN.md`](15_LEGACY_UX_PARITY_PLAN.md). This checklist tracks sequencing, not
authorization: a checked UI item never substitutes for a server-side ABAC, retention or production
release gate.
