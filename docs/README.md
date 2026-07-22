# Controlled artifact index

| ID | Artifact | Purpose | Status |
|---|---|---|---|
| 00 | [Project plan](00_PROJECT_PLAN.md) | scope, work breakdown, milestones, gates | Baseline |
| 01 | [PRD](01_PRD.md) | users, outcomes, requirements, acceptance | Baseline |
| 02 | [Constraints](02_CONSTRAINTS.md) | legal, security, platform, operational limits | Baseline |
| 03 | [Architecture](03_ARCHITECTURE.md) | contexts, ownership, runtime and data flows | Baseline |
| 04 | [Feature specification](04_FEATURE_SPEC.md) | behavior by module | Target + baseline |
| 05 | [API specification](05_API_SPEC.md) | implemented HTTP contracts and backlog | Implemented baseline |
| 06 | [Data model](06_DATA_MODEL.md) | implemented DDL and backlog schemas | Implemented baseline |
| 07 | [Security and ABAC](07_SECURITY_ABAC.md) | threat model, policy and enforcement | Baseline |
| 08 | [Deployment](08_DEPLOYMENT.md) | implemented profiles and production gates | Implemented baseline |
| 09 | [Test strategy](09_TEST_STRATEGY.md) | automated, performance, security and recovery gates | Baseline |
| 10 | [Semiconductor seed](10_SEMICONDUCTOR_SEED.md) | optional deep value-chain data pack | Implemented baseline |
| 11 | [Legacy migration](11_LEGACY_MIGRATION.md) | compatibility, migration, retirement | Baseline |
| 12 | [Acceptance report](12_ACCEPTANCE_REPORT.md) | executed evidence and known limitations | Development/integration accepted; production gates open |
| 13 | [Operations runbook](13_OPERATIONS_RUNBOOK.md) | backup, restore, recovery and incident procedures | Baseline |
| 14 | [Production hardening](14_PRODUCTION_HARDENING.md) | scale assumptions, P0-P3 disposition and decision gates | Active |
| 15 | [Legacy UX parity](15_LEGACY_UX_PARITY_PLAN.md) | v0.3 visual/workflow traceability, safe substitutions and staged acceptance | Active |
| 16 | [Phase execution checklist](16_PHASE_EXECUTION_CHECKLIST.md) | current Phase 1/2 work and paused Phase 3 parity continuation | Active |
| 17 | [Semiconductor seed workflow](17_SEMICONDUCTOR_SEED_WORKFLOW.md) | restartable external schema, DataHub lineage and Airflow operation | Implemented baseline |
| 18 | [Semiconductor governance taxonomy](18_SEMICONDUCTOR_GOVERNANCE_TAXONOMY.md) | DataHub glossary/tag hierarchy and deterministic enrichment workflow | Implemented baseline |
| 19 | [Two-person CR browser acceptance](19_CR_E2E_ACCEPTANCE.md) | target-environment OIDC/WebAuthn intake, independent review and completion evidence | Active acceptance gate |
| 20 | [Enterprise UI completion PRD](20_ENTERPRISE_UI_COMPLETION_PRD.md) | CR, Knowledge Studio, profile and administrator screen requirements with governed substitutions | Implemented; API gates open |
| 21 | [Enterprise UI completion checklist](21_ENTERPRISE_UI_COMPLETION_CHECKLIST.md) | requirement-to-component/API/test traceability for the current UI completion work | Implemented; external gates open |
| 22 | [Four-menu use cases and architecture review](usecases.md) | Search, Registration, CR and Knowledge use cases, integration gates and proposed ERDs | Step 1 design baseline |
| 23 | [Catalog DataHub ingestion, metadata and export operation](23_CATALOG_DATAHUB_INGESTION_AND_EXPORT.md) | PostgreSQL/Oracle profile and Created Date limits, description sync, safe export activation | Implemented contract; remote activation gates open |
| 24 | [Low-resource multi-architecture deployment PRD](24_LOW_RESOURCE_MULTIARCH_DEPLOYMENT_PRD.md) | arm64/amd64 parity, dependency placement, configuration and migration acceptance | Active |
| 25 | [Low-resource multi-architecture execution checklist](25_LOW_RESOURCE_MULTIARCH_EXECUTION_CHECKLIST.md) | phased implementation and target-environment evidence | Active |
| 26 | [Mac arm64 to WSL amd64 migration runbook](26_MAC_TO_WSL_MIGRATION_RUNBOOK.md) | exact-source/image transfer, object reconciliation, logical restore and rollback | Active target gate |

Independent review records: [Data Architect](reviews/2026-07-14_DATA_ARCHITECT_REVIEW.md) and [Data Engineer/SRE](reviews/2026-07-14_DATA_ENGINEER_REVIEW.md).

Architecture decisions are immutable records under `adr/`. Superseded artifacts remain in Git and link to their replacement; they are not silently overwritten.

Current retention decisions: [governed retention and immutable archive](adr/0010-governed-retention-and-immutable-archive.md), [maintained S3 and archive promotion](adr/0012-maintained-s3-and-immutable-archive-promotion.md), and [Chat active-policy binding](adr/0018-chat-retention-policy-binding.md).

Current administrator decisions: [hardware WebAuthn and governed password fallback](adr/0009-hardware-webauthn-and-governed-password-fallback.md), [workspace access roles and development connection probes](adr/0024-workspace-access-roles-and-development-connection-probes.md), and [operator security modes and stable authentication renewal](adr/0025-operator-security-modes-and-stable-auth-renewal.md).

Current account/workflow/runtime decisions: [expiring membership renewal](adr/0026-expiring-human-membership-renewal.md), [CR System-role authority](adr/0027-change-request-system-role-authority.md), and [development System Settings startup activation](adr/0028-development-system-configuration-startup-activation.md).

Current development knowledge-integration decision: [intranet OpenAI-compatible adapter](adr/0030-development-intranet-openai-compatible-adapter.md).

Current local identity-lifecycle decision: [governed Keycloak identity provisioning](adr/0031-governed-keycloak-identity-provisioning.md).

Current Linux/WSL source-host scheduling decision: [Airflow loopback bridge](adr/0032-linux-source-host-airflow-loopback-bridge.md).

Current external infrastructure connector decision: [external Redis and S3 connector control plane](adr/0033-external-redis-and-s3-connector-control-plane.md).

Current multi-architecture release decision: [runtime configuration and release bundles](adr/0034-multi-architecture-runtime-configuration-and-release-bundles.md).

Current low-resource client and preparation Chat decision: [bounded client state and preparation Chat provider](adr/0035-bounded-client-state-and-preparation-chat-provider.md).

## Change control

- Requirements use stable IDs (`FR-*`, `NFR-*`, `SEC-*`).
- APIs use `/api/v1` until an incompatible contract requires a new major path.
- Database change requires an Alembic migration and an update to the data model.
- Architecture changes require an ADR.
- A release requires links from the acceptance report to machine-generated evidence.
