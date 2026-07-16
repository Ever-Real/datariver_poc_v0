# Project plan

## Objective

Deliver a portable, Git-shareable DataRiver platform that safely wraps external DataHub, preserves the five current product areas, and creates a governed foundation for knowledge-graph authoring, versioning, publication, analysis APIs, and evidence-grounded Chat.

## Delivery principles

1. Establish contracts and canonical ownership before implementation.
2. Build a modular monolith first; extract a service only when scaling, availability, or team ownership justifies it.
3. Keep API, worker, scheduler, and projection processes independently deployable.
4. Prefer deterministic workflows and reconciliation over distributed transactions.
5. Treat security, observability, migrations, backup, and rollback as product functionality.

## Work breakdown

| Phase | Deliverable | Exit gate |
|---|---|---|
| 0. Reference | sanitized v0.3 snapshot and audit trace | no secret/cache copied; manifest present |
| 1. Foundation | controlled documents, ADRs, project skeleton, CI | architecture and license checks run |
| 2. Secure core | OIDC boundary, ABAC, workspace isolation, audit | negative authorization matrix passes |
| 3. Catalog/governance | DataHub search facade, registration, CR/outbox/reconcile | failure cannot produce false completion |
| 4. KG/Chat | draft/validate/release/projection, evidence Chat | immutable release and evidence policy tests pass |
| 5. Platform | Valkey, object store, Airflow, gateway profile, telemetry | dependency failure matrix passes |
| 6. UX/seed | all feature modules and opt-in semiconductor pack | browser E2E and deterministic seed checks pass |
| 7. Stabilization | load, soak, restore, supply-chain and security tests | Critical/High unresolved findings = 0 |

## Current delivery status — 2026-07-17

| Phase | Status | Evidence / next gate |
|---|---|---|
| 0–4 | Complete for development baseline | reference manifest, controlled docs/ADRs, OIDC + ABAC/RLS, catalog/registration/governance, KG changesets/releases/sharing/Chat and the verified 311-test backend suite |
| 5 | Complete for local integration | separate Valkey roles, SeaweedFS init, four workers, Keycloak, two paused Airflow DAGs and read-only APISIX verified live |
| 6 | Baseline complete; legacy UX parity in progress | modular React flows and deterministic 12-asset/257-node/279-edge seed pass; dense v0.3 interaction parity and full Playwright user journeys remain open |
| 7 | Partially complete | dependency/source/IaC scans, selected recovery drills and runtime logs pass; target DataHub/object contract, backup/restore, load/soak, chaos and signed promoted-image evidence remain |

## Active UX parity delivery — 2026-07-17

The development baseline above is not the final user-experience acceptance. The active delivery objective is to reproduce the v0.3 visual and workflow model on top of the governed v1 contracts. The staged status, screen-by-screen traceability, security substitutions, and acceptance protocol are controlled in [the legacy UX parity plan](15_LEGACY_UX_PARITY_PLAN.md). Stage 1 source and unit verification is complete with its authenticated visual snapshot gate still open; Stage 2 is in progress. No stage is represented as fully accepted until its source, tests, and runtime evidence pass together.

The authoritative decision and exact measurements are in [the acceptance report](12_ACCEPTANCE_REPORT.md). No phase with an open production gate is represented as production complete.

## Roles and review

The lead implementation is reviewed independently from two perspectives:

- Data architect: bounded contexts, ownership, schemas, ABAC resource model, KG lifecycle and migration correctness.
- Data engineer/SRE: OSS license/maintenance, portable deployment, Valkey memory, async delivery, observability, CI and failure recovery.

Review findings are binding unless an ADR records a reasoned exception. Both independent reviews required PostgreSQL canonical workflow state, non-canonical Valkey, a DataHub anti-corruption layer, and rebuildable graph projections.

## Definition of done

“No errors” is operationalized as measurable release gates rather than a universal guarantee:

- all unit, integration, architecture, contract, E2E and migration tests pass;
- authorization positive/negative matrix and cross-workspace isolation pass;
- no unresolved Critical/High security issue;
- external dependency outage and worker-crash scenarios preserve canonical state;
- clean-clone bootstrap, backup restore, and graph projection rebuild are demonstrated;
- SBOM, license inventory, image scan, secret scan, API snapshot, and acceptance report are produced;
- remaining limitations have owner, impact, workaround, and target milestone.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| DataHub version/API variation | capability probe, typed adapter, contract fixtures, no generic pass-through |
| full local profile exceeds PC memory | separate Compose profiles and resource budgets |
| ABAC leaks through search pagination/count | local authorized asset index before DataHub enrichment |
| duplicate external effects | transactional outbox, inbox idempotency, reconciliation hash |
| LLM non-determinism | proposal-only output, schema validation, provenance, human approval |
| S3 compatibility differences | port contract plus conformance tests; storage-specific adapters |
| graph engine license/operations | PostgreSQL release SSOT; engine is replaceable and non-public |
