# DataRiver Continuous Feature Program

## Purpose

This document is the repository-local source of truth for the post-portability
feature program. The local dashboard at `http://127.0.0.1:39090` is its
non-technical presentation. Historical K0-K10, PREP hotfix, and release records
remain evidence; they are not silently converted into completion claims for the
new Epics below.

## Starting release lineage

Verified on 2026-08-29 before feature work:

- Product: `6422abe46e4f6b5e68128c981ed58c94259d479e`
- Evidence: `50380f81575322a3cdf6d18db80272fb7217c8ee`
- Handoff / `origin/dev`: `266b885fed07a59f16e87d2a2738ce079ed6dd7d`
- `origin/main`: `17f32a52de79077c433bf0beaabac81a48e46062`
  (frozen unless the user approves promotion)
- TEST PC: `TEST_PC_RUNTIME_ACCEPTED` for the starting release, including its
  accepted-state rerun
- Actual PREP: not executed for this program
- Actual OPS: not executed for this program

The current deploy contract remains the one documented by
`docs/64_PREP39083_HANDOFF.md`, `docs/65_PREP_TO_OPS_PROMOTION.md`,
`docs/66_RELEASE_CYCLE.md`, and the current `deploy/prep39083/release.json`.
Every release candidate must preserve build-once exact amd64 OCI delivery,
checksum/manifest/config/revision verification, `pull_policy: never`,
`docker compose up --no-build`, no build/pull fallback, and
`runtime_input_diff=NONE` between Product and Handoff.

## Status contract

- `QUEUED`: accepted scope, not started.
- `IN_PROGRESS`: source discovery or implementation is active.
- `LOCAL_VERIFIED`: source and focused local gates passed; runtime acceptance
  has not yet been established for runtime-reachable work.
- `TEST_PC_ACCEPTED`: the exact Product artifact passed the relevant TEST PC
  acceptance.
- `DONE`: all applicable acceptance, evidence, and dashboard gates are complete.
- `BLOCKED_EXTERNAL`: source work can continue, but a provider/host gate is not
  available.
- `NEEDS_DECISION`: only the affected policy choice is paused.
- `ARCHIVED`: completed or obsolete historical material retained with evidence.

Runtime-reachable work is never `DONE` solely because unit tests pass.

## Canonical Epic registry

| Group | Canonical IDs | Scope |
| --- | --- | --- |
| Program | PM-01..PM-05 | backlog merge, numbering, dashboard, constraints, design constraints |
| Common UX | UX-01..UX-04 | concise copy, back/close, transient state, zero console errors |
| Home | HM-01..HM-03 | coverage metrics, CR overview, data-change summary |
| Account/Admin | AC-01..AC-07 | password, profile, site settings, connections, permissions, system code, monitoring dashboards |
| Search | SR-01..SR-07 | export, accordion, lineage sizing, tree semantics/loading, detail reset/history |
| Chat | CH-01..CH-04 | recall RCA, result/evidence contract, performance, authorization parity |
| Change | CD-01 | exact Table-to-System mapping remediation |
| Knowledge | KG-01..KG-07 | refresh, scheduling, default graph, glossary, term relations, graph interlinking |
| Governance | GV-01..GV-05 | table readability, format persistence, editor scroll/paste, remove duplicate policy tab |
| Quality | DQ-01..DQ-02 | bounded bulk rules and approval-based metadata enrichment |
| Airflow | AF-01..AF-04 | import compatibility, connection, DAG operations, exact system linking |
| MCP | MP-01..MP-06 | topology, offline artifact, authorization broker, read-only default, acceptance |

The exact user-facing title and current status for all 55 Epics are maintained
in the dashboard `status.json`. The IDs above are stable across waves.

## Wave order

1. Wave A: PM, shared UX/navigation/console defects, Airflow import compatibility.
2. Wave B: Home, Profile, Search/Resource Tree, Admin basics, Monitoring add flow.
3. Wave C: Chat, Change detection, Glossary/Knowledge Graph, Governance.
4. Wave D: Quality, Airflow management, Site Management, MCP, enrichment and
   graph interlinking.
5. Wave E: integrated copy/navigation, console, performance, accessibility,
   regression, exact OCI, and TEST PC closeout.

Only lanes with disjoint file ownership run in parallel. Shared router,
navigation, server schema, and release files are integrated serially by the
Control Plane.

## Historical backlog disposition

- PREP migration/K9/MCL and unknown-state portability corrections are archived
  as completed release evidence. They remain regression contracts.
- UX1-A/B/C/D commits (`03bba20`, `e268ad3`, `3fbf24a`, `b5f4064`) are ancestors
  of the starting Handoff and must not be re-applied.
- Quarantined UX-A commit `7aa2d1c` is only a reference candidate for HM-01.
  Its three-file coverage delta must be revalidated against the current
  authorized-inventory/currentness contract before selective implementation.
- Quarantined UX-B commit `c889463` and Chat commit `e99d94a` are not merge
  candidates. Their intent may inform AC/CD/CH acceptance, but their divergent
  source and policy behavior must not overwrite the current architecture.
- YAML save/activation and retired versioned system-settings revisions remain
  archived obsolete where ADR-0048 already superseded them.
- Real IdP/Keycloak and Actual PREP/OPS execution remain external gates; they do
  not block independent source work.
- `MIGRATION_BASELINE_V2_AND_LEGACY_RETIREMENT` remains a post-PREP design
  backlog item. No legacy migration reorganization is part of these feature
  waves.

| Historical source | Canonical parent | Disposition |
| --- | --- | --- |
| `docs/15_LEGACY_UX_PARITY_PLAN.md`, `docs/16_PHASE_EXECUTION_CHECKLIST.md` | UX, SR, CD-01, AC | Merge registration/CR/admin parity intent into current workflows; do not resurrect obsolete screens. |
| `docs/21_ENTERPRISE_UI_COMPLETION_CHECKLIST.md` API gaps | KG-07, GV-02, AC-06 | `NEEDS_DECISION` until an existing or newly approved typed API contract is proven; never invent a UI-only API. |
| `docs/45_KNOWLEDGE_STUDIO_REDESIGN_EXECUTION_CHECKLIST.md` | KG-07, DQ-02 | Preserve ontology, mapping, source-reference, and review invariants as current subtask evidence. |
| `docs/52_GX_QUALITY_MANAGEMENT_PRD_CHECKLIST.md`, `docs/62_GX_DATAHUB_DATARIVER_INTEGRATION_GUIDE.md` | DQ-01, AF-03 | Merge bounded ruleset execution and allowlisted Airflow target gates into the current Epics. |
| Real Keycloak/WebAuthn/browser gates | AC-01, Wave E | `BLOCKED_EXTERNAL`; local-account work may continue independently. |
| Native target, Actual PREP, Actual OPS gates | Wave E | `BLOCKED_EXTERNAL` or user approval gate; TEST acceptance is never substituted. |
| Migration baseline V2 / legacy retirement | PM-01 | Post-PREP `NEEDS_DECISION`; current accepted migrations remain immutable. |
| Stale documentation claims recorded in `docs/29_MASTER_EXECUTION_BACKLOG.md` | PM-01 | Correct against current source/evidence incrementally without deleting historical acceptance. |

## Invariants carried into every Epic

- No fixed business URN, Dataset/Term name, host/IP, provider cardinality, or
  DEV seed in runtime paths or acceptance logic.
- DataHub v1.6.0 contracts and current canonical APIs are authoritative.
- Backend authorization and classification ceilings are never widened for UX.
- User-owned metadata is not changed by smoke or automatic verification.
- Accepted-state ownership, Product-owned PostgreSQL integrity, removed entity
  filtering, K9 consistency/LKG fencing, MCL checkpoint continuity, non-root web
  runtime, secret modes, and public-Origin/loopback-transport separation remain
  mandatory regression contracts.
- No source or state reset, no resecret, no destructive recovery, and no hidden
  rebuild fallback.

## Current execution

- PM-01..PM-05 are locally verified in the existing dashboard: the 55
  canonical Epics and eight legacy-source groups are mapped without promoting
  stale claims; program/wave/Epic views, constraints and design-constraints
  tabs, and a collapsed completion archive render over HTTP 200.
- Wave A Product `5ab575ffa3a0f8dba7657245de182ae940fdb325` is locally verified.
  Catalog close/focus/transient-route behavior, bounded graph geometry, valid
  font weights, affected-path CSP-compatible styling and shared copy cleanup are
  complete in source. The pinned Airflow 3.3.0 image parsed all six DAGs, so
  AF-01 required no Product delta. An authenticated Catalog-open 401 was not
  reproduced locally and remains an exact TEST browser/network acceptance gate.
- The exact `linux/amd64` Product archive is exported and checksum/manifest/
  config/revision verified. Evidence is recorded in
  `docs/evidence/wave-a-foundation/README.md`. Wave A remains
  `LOCAL_VERIFIED` until the existing accepted TEST state is redeployed without
  build/reset/resecret and passes 6/6 smoke plus affected browser/API checks.

## Release and TEST PC checkpoints

At a coherent wave boundary:

1. Run focused and required regression gates on the exact Product source.
2. Create Product, Evidence, and Handoff commits in that order.
3. Verify Product-to-Handoff runtime input drift is `NONE`.
4. Push the exact Handoff to `origin/dev`; do not move `origin/main`.
5. Build one `linux/amd64` OCI artifact, pin its archive checksum, child
   manifest, config, platform, and Product revision in `release.json`.
6. Transfer that exact artifact to the TEST PC and run the canonical
   `./scripts/prep39083 deploy` accepted-state redeploy without build, reset,
   resecret, or duplicate identity creation.
7. Verify 6/6 smoke and the wave-specific browser/API surfaces, then rerun the
   same command for idempotence when required.

If the TEST host or an M4 provider is unavailable, mark the runtime check
`BLOCKED_EXTERNAL` and continue disjoint source work. TEST acceptance is never
reported as Actual PREP acceptance.
